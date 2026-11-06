from django.urls import path

from .views import register

app_name = 'customers'

urlpatterns = [
    path('register/', register, name='register'),
]
