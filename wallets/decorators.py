import json
import logging
from functools import lru_cache, wraps
from uuid import uuid4

from django.conf import settings
from django.http import JsonResponse
from redis import Redis
from redis.exceptions import RedisError

from .forms import WalletTransactionForm

logger = logging.getLogger(__name__)
IN_PROGRESS_TTL = 120
COMPLETED_TTL = 180

# Only the worker that reserved this key may replace or release it.
FINISH_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('set', KEYS[1], 'COMPLETED', 'EX', ARGV[2])
end
return nil
"""
RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class ReservationExpired(Exception):
    pass


@lru_cache(maxsize=1)
def get_redis():
    return Redis.from_url(settings.REDIS_URL, decode_responses=True,
                          socket_connect_timeout=2, socket_timeout=2)


def transaction_cache_key(customer_id, wallet_type_id, kind):
    return f'wallet-type-operation:{customer_id}:{wallet_type_id}:{kind}'


def validate_transaction_request(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.content_type != 'application/json':
            return JsonResponse({'error': 'Content-Type must be application/json.'}, status=415)
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'Invalid JSON body.'}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({'error': 'Body must be a JSON object.'}, status=400)
        errors = {}
        for field, value in data.items():
            if field not in ('type', 'amount'):
                errors[field] = ['Unknown field.']
            elif not isinstance(value, str):
                errors[field] = ['Must be a string.']
        if errors:
            return JsonResponse({'errors': errors}, status=400)
        form = WalletTransactionForm(data)
        if not form.is_valid():
            return JsonResponse({'errors': dict(form.errors)}, status=400)
        request.transaction_data = form.cleaned_data
        return view(request, *args, **kwargs)
    return wrapped


def redis_wallet_idempotency(view):
    """Requires authenticated customer and validated transaction_data on request."""
    @wraps(view)
    def wrapped(request, wallet_type_id, *args, **kwargs):
        client = get_redis()
        key = transaction_cache_key(request.customer.pk, wallet_type_id, request.transaction_data['type'])
        owner = f'IN_PROGRESS:{uuid4()}'
        try:
            if not client.set(key, owner, nx=True, ex=IN_PROGRESS_TTL):
                return JsonResponse(
                    {'error': 'A request for this wallet and transaction type is already in progress or was recently processed.'},
                    status=409,
                )
        except RedisError:
            return JsonResponse({'error': 'Duplicate-request protection is unavailable. Try again later.'}, status=503)

        def ensure_reservation():
            if client.get(key) != owner:
                raise ReservationExpired

        # Recheck after waiting for the wallet row lock, before changing money.
        request.ensure_wallet_reservation = ensure_reservation
        try:
            response = view(request, wallet_type_id, *args, **kwargs)
        except ReservationExpired:
            return JsonResponse({'error': 'Request reservation expired. No balance change was committed.'}, status=409)
        except RedisError:
            return JsonResponse({'error': 'Duplicate-request protection is unavailable. Try again later.'}, status=503)
        try:
            if response.status_code == 404:
                client.eval(RELEASE_SCRIPT, 1, key, owner)
            elif response.status_code < 500:
                if not client.eval(FINISH_SCRIPT, 1, key, owner, COMPLETED_TTL):
                    logger.warning('Wallet request completed after losing its Redis reservation.')
        except RedisError:
            # The database may already have committed: preserve its actual response.
            logger.exception('Could not finalize Redis wallet request reservation.')
        return response
    return wrapped
