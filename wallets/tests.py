from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from customers.models import Customer

from .models import Wallet


class WalletTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create_user(
            mobile='09123456789', national_code='0012345678', password='wallet-test-password',
        )

    def test_customer_can_have_multiple_wallets(self):
        first = Wallet.objects.create(user=self.customer, type='personal')
        second = Wallet.objects.create(user=self.customer, type='savings')
        self.assertIsInstance(first.pk, int)
        self.assertGreater(second.pk, first.pk)
        self.assertEqual(self.customer.wallets.count(), 2)
        self.assertEqual(first.user_id, self.customer.pk)
        first.refresh_from_db()
        self.assertEqual(first.balance, Decimal('0.00'))
        self.assertIsNotNone(first.created_at)

    def test_balance_preserves_decimal_amount_and_updates_timestamp(self):
        wallet = Wallet.objects.create(user=self.customer, type='personal')
        previous_update = wallet.updated_at
        wallet.balance = Decimal('123.45')
        wallet.save()
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('123.45'))
        self.assertGreater(wallet.updated_at, previous_update)

    def test_negative_balance_fails_validation(self):
        wallet = Wallet(user=self.customer, type='personal', balance=Decimal('-0.01'))
        with self.assertRaises(ValidationError):
            wallet.full_clean()

    def test_database_rejects_negative_balance_on_insert_and_update(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.create(user=self.customer, type='personal', balance=Decimal('-0.01'))
        wallet = Wallet.objects.create(user=self.customer, type='personal')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(pk=wallet.pk).update(balance=Decimal('-0.01'))
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('0.00'))

    def test_wallet_requires_customer(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.create(type='personal')

    def test_customer_with_wallet_cannot_be_deleted(self):
        Wallet.objects.create(user=self.customer, type='personal')
        with self.assertRaises(ProtectedError):
            self.customer.delete()
