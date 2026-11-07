from decimal import Decimal

from django.db import transaction

from .models import Wallet, WalletTransaction

MAX_BALANCE = Decimal('999999999999999999.99')


def change_balance(*, customer, wallet_id, kind, amount, ensure_reservation=None):
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().filter(pk=wallet_id, user=customer).first()
        if wallet is None:
            # Do not reveal whether another customer's wallet exists.
            return {'error': 'Wallet not found.'}, 404

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
                'type': record.type, 'status': record.status,
                'amount': format(amount, '.2f'), 'balance': format(wallet.balance, '.2f'),
                'created_at': record.created_at.isoformat(),
            }, 201
        if ensure_reservation:
            ensure_reservation()
        return body, status_code
