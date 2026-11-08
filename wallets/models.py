from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class WalletType(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=50, unique=True)
    withdrawable = models.BooleanField(default=True)
    automatic_creation = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallet_types'

    def __str__(self) -> str:
        return self.name


class Wallet(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT, related_name='wallets',
    )
    wallet_type = models.ForeignKey(
        WalletType, on_delete=models.PROTECT, related_name='wallets',
    )
    balance = models.DecimalField(
        max_digits=20, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallets'
        constraints = [
            models.UniqueConstraint(fields=['user', 'wallet_type'], name='wallet_user_type_unique'),
            models.CheckConstraint(
                condition=models.Q(balance__gte=0), name='wallet_balance_non_negative',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.id}: {self.wallet_type.name}'


class WalletTransaction(models.Model):
    class Type(models.TextChoices):
        INCREASED = 'INCREASED', 'Increased'
        DECREASED = 'DECREASED', 'Decreased'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    id = models.BigAutoField(primary_key=True)
    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name='transactions',
    )
    type = models.CharField(max_length=9, choices=Type.choices)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(
        max_digits=20, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallet_transactions'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name='wallet_transaction_amount_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(type__in=['INCREASED', 'DECREASED']),
                name='wallet_transaction_type_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=['PENDING', 'COMPLETED', 'FAILED']),
                name='wallet_transaction_status_valid',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.id}: {self.type} {self.amount} ({self.status})'


class WalletOperation(models.Model):
    user = models.ForeignKey('customers.Customer', on_delete=models.PROTECT)
    request_id = models.UUIDField()
    fingerprint = models.JSONField()
    transaction = models.OneToOneField(
        WalletTransaction, null=True, blank=True, on_delete=models.PROTECT,
        related_name='operation',
    )
    response = models.JSONField()
    status_code = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wallet_operations'
        constraints = [
            models.UniqueConstraint(fields=['user', 'request_id'], name='wallet_operation_user_request_unique'),
        ]
