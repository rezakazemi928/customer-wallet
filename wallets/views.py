from django.db.models import Prefetch
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from customers.tokens import customer_token_required
from customers.types import CustomerRequest

from .types import WalletRequest, WalletTransactionGroup
from .models import WalletTransaction

from .decorators import redis_wallet_idempotency, validate_transaction_request
from .services import change_balance


@require_GET
@customer_token_required
def list_wallets(request: CustomerRequest) -> JsonResponse:
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
def create_transaction(request: WalletRequest, wallet_type_id: int) -> JsonResponse:
    body, status_code = change_balance(
        customer=request.customer, wallet_type_id=wallet_type_id,
        kind=request.transaction_data['type'], amount=request.transaction_data['amount'],
        ensure_reservation=request.ensure_wallet_reservation,
        request_id=request.wallet_request_id,
    )
    response = JsonResponse(body, status=status_code)
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
@customer_token_required
def list_transactions(request: CustomerRequest) -> JsonResponse:
    wallets = request.customer.wallets.select_related('wallet_type').order_by('wallet_type_id')
    if 'wallet_type_id' in request.GET:
        raw_id = request.GET['wallet_type_id']
        wallets = wallets.filter(wallet_type_id=int(raw_id))

    wallets = wallets.prefetch_related(Prefetch(
        'transactions',
        queryset=WalletTransaction.objects.order_by('-created_at', '-id'),
        to_attr='history',
    ))
    groups: list[WalletTransactionGroup] = []
    for wallet in wallets:
        groups.append({
            'wallet_id': wallet.pk,
            'wallet_type_id': wallet.wallet_type_id,
            'wallet_type_name': wallet.wallet_type.name,
            'transactions': [
                {
                    'id': record.pk,
                    'type': record.type,
                    'status': record.status,
                    'amount': str(record.amount),
                    'created_at': record.created_at.isoformat(),
                    'updated_at': record.updated_at.isoformat(),
                }
                for record in wallet.history
            ],
        })
    response = JsonResponse({'wallets': groups})
    response['Cache-Control'] = 'no-store'
    return response
