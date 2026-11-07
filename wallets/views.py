from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from customers.tokens import customer_token_required

from .decorators import redis_wallet_idempotency, validate_transaction_request
from .services import change_balance


@require_GET
@customer_token_required
def list_wallets(request):
    wallets = request.customer.wallets.select_related('wallet_type').order_by('id')
    return JsonResponse({'wallets': [
        {
            'id': wallet.id,
            'wallet_type_id': wallet.wallet_type_id,
            'wallet_type_name': wallet.wallet_type.name,
            'withdrawable': wallet.wallet_type.withdrawable,
            'balance': str(wallet.balance),
            'user_id': str(wallet.user_id),
            'created_at': wallet.created_at.isoformat(),
            'updated_at': wallet.updated_at.isoformat(),
        }
        for wallet in wallets
    ]})


@csrf_exempt
@require_POST
@customer_token_required
@validate_transaction_request
@redis_wallet_idempotency
def create_transaction(request, wallet_type_id):
    body, status_code = change_balance(
        customer=request.customer, wallet_type_id=wallet_type_id,
        kind=request.transaction_data['type'], amount=request.transaction_data['amount'],
        ensure_reservation=request.ensure_wallet_reservation,
    )
    response = JsonResponse(body, status=status_code)
    response['Cache-Control'] = 'no-store'
    return response
