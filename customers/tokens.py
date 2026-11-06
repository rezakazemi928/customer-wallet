from datetime import datetime, timedelta, timezone
from functools import wraps
from uuid import UUID

import jwt
from django.conf import settings
from django.http import JsonResponse

from .models import Customer

TOKEN_LIFETIME_SECONDS = 3600


def create_access_token(customer):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {'userId': str(customer.pk), 'iat': now,
         'exp': now + timedelta(seconds=TOKEN_LIFETIME_SECONDS)},
        settings.JWT_SIGNING_KEY,
        algorithm='HS256',
    )


def decode_access_token(token):
    payload = jwt.decode(
        token, settings.JWT_SIGNING_KEY, algorithms=['HS256'],
        options={'require': ['userId', 'iat', 'exp']},
    )
    try:
        UUID(payload['userId'])
    except (ValueError, TypeError, AttributeError) as exc:
        raise jwt.InvalidTokenError('Invalid customer ID.') from exc
    if (type(payload['iat']) is not int or type(payload['exp']) is not int
            or not 0 < payload['exp'] - payload['iat'] <= TOKEN_LIFETIME_SECONDS):
        raise jwt.InvalidTokenError('Invalid token lifetime.')
    return payload


def customer_token_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        parts = request.headers.get('Authorization', '').split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return JsonResponse({'error': 'Bearer token required.'}, status=401,
                                headers={'WWW-Authenticate': 'Bearer'})
        try:
            payload = decode_access_token(parts[1])
            request.customer = Customer.objects.get(pk=payload['userId'])
        except (jwt.InvalidTokenError, Customer.DoesNotExist):
            return JsonResponse({'error': 'Invalid or expired token.'}, status=401,
                                headers={'WWW-Authenticate': 'Bearer'})
        return view(request, *args, **kwargs)
    return wrapped
