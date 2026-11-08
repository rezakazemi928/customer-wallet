from decimal import Decimal
from uuid import UUID

from django.db import transaction

from customers.models import Customer

from .models import Wallet, WalletTransaction, WalletType, WalletOperation

from .types import OperationFingerprint, OperationResult, ReservationCheck

MAX_BALANCE = Decimal('999999999999999999.99')


def _apply_balance_change(
    *, customer: Customer, wallet_type_id: int, kind: str, amount: Decimal,
    ensure_reservation: ReservationCheck | None = None,
) -> OperationResult:
    with transaction.atomic():
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
        body: dict[str, str | int]
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


def operation_fingerprint(wallet_type_id: int, kind: str, amount: Decimal) -> OperationFingerprint:
    return {'wallet_type_id': wallet_type_id, 'type': kind, 'amount': format(amount, '.2f')}


def find_operation_result(
    customer: Customer, request_id: UUID, fingerprint: OperationFingerprint,
) -> OperationResult | None:
    operation = WalletOperation.objects.filter(user=customer, request_id=request_id).first()
    if operation is None:
        return None
    if operation.fingerprint != fingerprint:
        return {'error': 'Idempotency-Key was already used with different transaction details.'}, 409
    return operation.response, operation.status_code


def change_balance(
    *, customer: Customer, wallet_type_id: int, kind: str, amount: Decimal,
    request_id: UUID, ensure_reservation: ReservationCheck | None = None,
) -> OperationResult:
    fingerprint = operation_fingerprint(wallet_type_id, kind, amount)
    with transaction.atomic():
        Customer.objects.select_for_update().get(pk=customer.pk)
        previous = find_operation_result(customer, request_id, fingerprint)
        if previous is not None:
            return previous
        body, status_code = _apply_balance_change(
            customer=customer, wallet_type_id=wallet_type_id, kind=kind,
            amount=amount, ensure_reservation=ensure_reservation,
        )
        WalletOperation.objects.create(
            user=customer, request_id=request_id, fingerprint=fingerprint,
            transaction_id=body.get('transaction_id'), response=body, status_code=status_code,
        )
        return body, status_code
