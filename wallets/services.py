from decimal import Decimal

from django.db import transaction

from customers.models import Customer

from .models import Wallet, WalletTransaction, WalletType

MAX_BALANCE = Decimal('999999999999999999.99')


def change_balance(*, customer, wallet_type_id, kind, amount, ensure_reservation=None):
    with transaction.atomic():
        # Serialize lazy creation for this customer, even across opposite transaction types.
        Customer.objects.select_for_update().get(pk=customer.pk)
        if ensure_reservation:
            ensure_reservation()
        wallet_type = WalletType.objects.filter(pk=wallet_type_id).first()
        if wallet_type is None:
            return {'error': 'Wallet type not found.'}, 404
        if kind == WalletTransaction.Type.DECREASED and not wallet_type.withdrawable:
            return {'error': 'Withdrawals are disabled for this wallet type.'}, 403

        wallet = Wallet.objects.select_for_update().filter(user=customer, wallet_type=wallet_type).first()
        if wallet is None:
            if not wallet_type.automatic_creation:
                return {'error': 'Wallet does not exist and automatic creation is disabled.'}, 404
            Wallet.objects.get_or_create(user=customer, wallet_type=wallet_type)
            wallet = Wallet.objects.select_for_update().get(user=customer, wallet_type=wallet_type)

        if ensure_reservation:
            ensure_reservation()

        new_balance = wallet.balance + amount if kind == WalletTransaction.Type.INCREASED else wallet.balance - amount
        error = None
        if new_balance < 0:
            error = 'Insufficient balance.'
        elif new_balance > MAX_BALANCE:
            error = 'Resulting balance exceeds the maximum wallet balance.'

        record = WalletTransaction.objects.create(
            wallet=wallet, type=kind, amount=amount,
            status=WalletTransaction.Status.FAILED if error else WalletTransaction.Status.COMPLETED,
        )
        if error:
            body, status_code = {'error': error, 'transaction_id': record.pk}, 400
        else:
            wallet.balance = new_balance
            wallet.save(update_fields=['balance', 'updated_at'])
            body, status_code = {
                'transaction_id': record.pk, 'wallet_id': wallet.pk,
                'wallet_type_id': wallet.wallet_type_id,
                'type': record.type, 'status': record.status,
                'amount': format(amount, '.2f'), 'balance': format(wallet.balance, '.2f'),
                'created_at': record.created_at.isoformat(),
            }, 201
        if ensure_reservation:
            ensure_reservation()
        return body, status_code
