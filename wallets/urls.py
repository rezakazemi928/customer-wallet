from django.urls import path

from .views import list_wallets

app_name = 'wallets'

urlpatterns = [
    path('', list_wallets, name='list'),
]
