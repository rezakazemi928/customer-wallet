from django.http import JsonResponse
from django.views.decorators.http import require_GET

from customers.tokens import customer_token_required


@require_GET
@customer_token_required
def list_wallets(request):
    wallets = request.customer.wallets.order_by('id')
    return JsonResponse({'wallets': [
        {
            'id': wallet.id,
            'type': wallet.type,
            'balance': str(wallet.balance),
            'user_id': str(wallet.user_id),
            'created_at': wallet.created_at.isoformat(),
            'updated_at': wallet.updated_at.isoformat(),
        }
        for wallet in wallets
    ]})
