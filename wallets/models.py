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
