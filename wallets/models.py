from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Wallet(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT, related_name='wallets',
    )
    type = models.CharField(max_length=50)
    balance = models.DecimalField(
        max_digits=20, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallets'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(balance__gte=0), name='wallet_balance_non_negative',
            ),
        ]

    def __str__(self):
        return f'{self.id}: {self.type}'


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

    def __str__(self):
        return f'{self.id}: {self.type} {self.amount} ({self.status})'
