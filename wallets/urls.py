from django.urls import path

from .views import create_transaction, list_wallets

app_name = 'wallets'

urlpatterns = [
    path('types/<int:wallet_type_id>/transactions/', create_transaction, name='create-transaction'),
    path('', list_wallets, name='list'),
]
