from decimal import Decimal

from django import forms

from .models import WalletTransaction


class WalletTransactionForm(forms.Form):
    type = forms.ChoiceField(choices=WalletTransaction.Type.choices)
    amount = forms.DecimalField(max_digits=20, decimal_places=2, min_value=Decimal('0.01'))
