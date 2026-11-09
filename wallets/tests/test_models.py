from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from customers.models import Customer
from wallets.models import Wallet, WalletType


class WalletTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create_user(
            mobile='09123456789', national_code='0012345678', password='wallet-test-password',
        )

    def test_customer_can_have_multiple_wallets(self):
        first = Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0])
        second = Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='savings', defaults={'automatic_creation': False})[0])
        self.assertIsInstance(first.pk, int)
        self.assertGreater(second.pk, first.pk)
        self.assertEqual(self.customer.wallets.count(), 2)
        self.assertEqual(first.user_id, self.customer.pk)
        first.refresh_from_db()
        self.assertEqual(first.balance, Decimal('0.00'))
        self.assertIsNotNone(first.created_at)

    def test_balance_preserves_decimal_amount_and_updates_timestamp(self):
        wallet = Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0])
        previous_update = wallet.updated_at
        wallet.balance = Decimal('123.45')
        wallet.save()
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('123.45'))
        self.assertGreater(wallet.updated_at, previous_update)

    def test_negative_balance_fails_validation(self):
        wallet = Wallet(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0], balance=Decimal('-0.01'))
        with self.assertRaises(ValidationError):
            wallet.full_clean()

    def test_database_rejects_negative_balance_on_insert_and_update(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0], balance=Decimal('-0.01'))
        wallet = Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(pk=wallet.pk).update(balance=Decimal('-0.01'))
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('0.00'))

    def test_wallet_requires_customer(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.create(wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0])

    def test_customer_with_wallet_cannot_be_deleted(self):
        Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0])
        with self.assertRaises(ProtectedError):
            self.customer.delete()



class WalletTransactionTests(TestCase):
    def setUp(self):
        from wallets.models import WalletTransaction
        self.transaction_model = WalletTransaction
        customer = Customer.objects.create_user(
            mobile='09123456789', national_code='0012345678', password='wallet-test-password',
        )
        self.wallet = Wallet.objects.create(user=customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0], balance=Decimal('100.00'))

    def test_wallet_has_multiple_transactions_with_exact_amounts(self):
        for kind in self.transaction_model.Type.values:
            record = self.transaction_model.objects.create(
                wallet=self.wallet, type=kind, amount=Decimal('12.34'),
            )
            record.refresh_from_db()
            self.assertEqual(record.amount, Decimal('12.34'))
            self.assertEqual(record.status, 'PENDING')
            self.assertEqual(record.wallet_id, self.wallet.pk)
            self.assertIsNotNone(record.created_at)
            previous_update = record.updated_at
            record.status = self.transaction_model.Status.COMPLETED
            record.save()
            self.assertGreater(record.updated_at, previous_update)
        self.assertEqual(self.wallet.transactions.count(), 2)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))

    def test_invalid_values_fail_validation_and_database_constraints(self):
        for changes in (
            {'amount': Decimal('0.00')}, {'amount': Decimal('-0.01')},
            {'type': 'INVALID'}, {'status': 'INVALID'},
        ):
            fields = {'wallet': self.wallet, 'type': 'INCREASED', 'amount': Decimal('1.00')}
            fields.update(changes)
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    self.transaction_model(**fields).full_clean()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.transaction_model.objects.create(**fields)

    def test_wallet_with_history_is_protected_from_deletion(self):
        self.transaction_model.objects.create(wallet=self.wallet, type='INCREASED', amount=Decimal('1.00'))
        with self.assertRaises(ProtectedError):
            self.wallet.delete()

    def test_transaction_requires_wallet(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.transaction_model.objects.create(type='INCREASED', amount=Decimal('1.00'))

