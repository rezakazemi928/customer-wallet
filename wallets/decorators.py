import json
import logging
from functools import lru_cache, wraps
from uuid import UUID, uuid4

from django.conf import settings
from django.http import JsonResponse
from redis import Redis
from redis.exceptions import RedisError

from .forms import WalletTransactionForm
from .services import find_operation_result, operation_fingerprint

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


def transaction_cache_key(customer_id, request_id):
    return f'wallet-request:{customer_id}:{request_id}'


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
        try:
            request_id = UUID(request.headers.get('Idempotency-Key', ''))
        except (ValueError, TypeError, AttributeError):
            return JsonResponse({'error': 'A valid UUID Idempotency-Key header is required.'}, status=400)
        request.wallet_request_id = request_id
        fingerprint = operation_fingerprint(
            wallet_type_id, request.transaction_data['type'], request.transaction_data['amount'],
        )

        def saved_response():
            result = find_operation_result(request.customer, request_id, fingerprint)
            if result is None:
                return None
            body, status = result
            response = JsonResponse(body, status=status)
            response['Cache-Control'] = 'no-store'
            return response

        previous = saved_response()
        if previous is not None:
            return previous
        client = get_redis()
        key = transaction_cache_key(request.customer.pk, request_id)
        owner = f'IN_PROGRESS:{uuid4()}'
        try:
            if not client.set(key, owner, nx=True, ex=IN_PROGRESS_TTL):
                previous = saved_response()
                if previous is not None:
                    return previous
                return JsonResponse(
                    {'error': 'This request ID is already being processed. Retry with the same Idempotency-Key.'},
                    status=409,
                )
        except RedisError:
            return JsonResponse({'error': 'Duplicate-request protection is unavailable. Try again later.'}, status=503)

        def ensure_reservation():
            if client.get(key) != owner:
                raise ReservationExpired

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
            logger.exception('Could not finalize Redis wallet request reservation.')
        return response
    return wrapped
