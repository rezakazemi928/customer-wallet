from typing import Any

from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Customer


class CustomerRegistrationForm(forms.ModelForm):
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    class Meta:
        model = Customer
        fields = ('mobile', 'password', 'national_code')

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data.get('password'):
            customer = Customer(**{
                key: value for key, value in cleaned_data.items() if key != 'password'
            })
            try:
                validate_password(cleaned_data['password'], user=customer)
            except forms.ValidationError as exc:
                self.add_error('password', exc)
        return cleaned_data
