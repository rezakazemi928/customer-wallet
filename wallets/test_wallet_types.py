from uuid import uuid4

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import fakeredis
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from customers.models import Customer
from customers.tokens import create_access_token
from .models import Wallet, WalletType, WalletTransaction
from .services import change_balance


class WalletTypeTests(TestCase):
    def setUp(self):
        self.user = Customer.objects.create_user(mobile='09123456789', national_code='0012345678', password='test-password')
        self.kind = WalletType.objects.create(name='automatic', automatic_creation=True)
        self.request_id = str(uuid4())
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        patcher = patch('wallets.decorators.get_redis', return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, kind='INCREASED', amount='10.00', key=None):
        return self.client.post(
            f'/api/wallets/types/{self.kind.pk}/transactions/',
            data={'type': kind, 'amount': amount}, content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {create_access_token(self.user)}',
            HTTP_IDEMPOTENCY_KEY=key or self.request_id,
        )

    def test_personal_type_is_seeded(self):
        personal = WalletType.objects.get(name='personal')
        self.assertTrue(personal.automatic_creation)
        self.assertTrue(personal.withdrawable)

    def test_first_charge_creates_wallet_and_retry_does_not_duplicate_it(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        wallet = self.user.wallets.get(wallet_type=self.kind)
        self.assertEqual(wallet.balance, Decimal('10.00'))
        self.assertEqual(response.json()['wallet_type_id'], self.kind.pk)
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.user.wallets.count(), 1)
        self.assertEqual(wallet.transactions.count(), 1)

    def test_unique_customer_type_is_enforced(self):
        Wallet.objects.create(user=self.user, wallet_type=self.kind)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.create(user=self.user, wallet_type=self.kind)

    def test_creation_disabled_requires_existing_wallet(self):
        self.kind.automatic_creation = False
        self.kind.save()
        self.assertEqual(self.post().status_code, 404)
        self.assertFalse(self.user.wallets.exists())
        Wallet.objects.create(user=self.user, wallet_type=self.kind)
        self.assertEqual(self.post(key=str(uuid4())).status_code, 201)

    def test_nonwithdrawable_wallet_rejects_decrease_but_accepts_increase(self):
        self.kind.withdrawable = False
        self.kind.save()
        self.assertEqual(self.post(kind='DECREASED').status_code, 403)
        self.assertFalse(self.user.wallets.exists())
        self.assertEqual(self.post(key=str(uuid4())).status_code, 201)
        self.assertEqual(self.post(kind='DECREASED').status_code, 403)
        wallet = self.user.wallets.get()
        self.assertEqual(wallet.balance, Decimal('10.00'))
        self.assertEqual(wallet.transactions.count(), 1)

    def test_first_withdrawal_creates_empty_wallet_and_records_insufficient_funds(self):
        response = self.post(kind='DECREASED')
        self.assertEqual(response.status_code, 400)
        wallet = self.user.wallets.get()
        self.assertEqual(wallet.balance, Decimal('0.00'))
        self.assertEqual(wallet.transactions.get().status, 'FAILED')

    def test_same_type_for_another_customer_does_not_change_their_wallet(self):
        other = Customer.objects.create_user(mobile='09987654321', national_code='0098765432', password='test-password')
        other_wallet = Wallet.objects.create(user=other, wallet_type=self.kind, balance=Decimal('50.00'))
        self.assertEqual(self.post().status_code, 201)
        other_wallet.refresh_from_db()
        self.assertEqual(other_wallet.balance, Decimal('50.00'))
        self.assertEqual(self.user.wallets.get().balance, Decimal('10.00'))


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentWalletCreationTests(TransactionTestCase):
    def test_two_requests_create_only_one_wallet(self):
        user = Customer.objects.create_user(mobile='09123456789', national_code='0012345678', password='test-password')
        kind = WalletType.objects.create(name='automatic', automatic_creation=True)
        barrier = Barrier(2)

        def run(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return change_balance(customer=user, wallet_type_id=kind.pk,
                                      kind='INCREASED', amount=Decimal('10.00'), request_id=uuid4())
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual([status for _, status in results], [201, 201])
        self.assertEqual(Wallet.objects.count(), 1)
        self.assertEqual(Wallet.objects.get().balance, Decimal('20.00'))
        self.assertEqual(WalletTransaction.objects.count(), 2)
