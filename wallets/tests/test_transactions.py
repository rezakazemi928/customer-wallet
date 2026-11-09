from uuid import uuid4

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import Mock, patch

from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from customers.models import Customer
from customers.tokens import create_access_token

from wallets.models import Wallet, WalletType, WalletTransaction, WalletOperation
from wallets.services import change_balance


class TransactionEndpointTests(TestCase):
    def setUp(self):
        import fakeredis
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        patcher = patch('wallets.decorators.get_redis', return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = Customer.objects.create_user(
            mobile='09123456789', national_code='0012345678', password='transaction-test-password',
        )
        self.wallet = Wallet.objects.create(user=self.user, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0], balance=Decimal('100.00'))
        self.url = f'/api/wallets/types/{self.wallet.wallet_type_id}/transactions/'
        self.auth = f'Bearer {create_access_token(self.user)}'
        self.request_id = str(uuid4())

    def post(self, amount='25.00', kind='DECREASED', url=None, key=None):
        return self.client.post(
            url or self.url, data={'type': kind, 'amount': amount}, content_type='application/json',
            HTTP_AUTHORIZATION=self.auth, HTTP_IDEMPOTENCY_KEY=self.request_id if key is None else key,
        )

    def test_increase_decrease_and_exact_balance_withdrawal(self):
        self.assertEqual(self.post(kind='INCREASED').json()['balance'], '125.00')
        self.assertEqual(self.post(amount='125.00', key=str(uuid4())).json()['balance'], '0.00')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('0.00'))
        self.assertEqual(self.wallet.transactions.filter(status='COMPLETED').count(), 2)

    def test_retries_replay_without_another_charge(self):
        original = self.post()
        self.post(kind='INCREASED', amount='10.00', key=str(uuid4()))
        retry = self.post(amount='25')
        self.assertEqual(original.status_code, 201)
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(retry.json(), original.json())
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('85.00'))
        self.assertEqual(self.wallet.transactions.count(), 2)

    def test_scope_blocks_changed_amount_but_allows_another_wallet(self):
        self.post()
        for kwargs in ({'amount': '26.00'},):
            self.assertEqual(self.post(**kwargs).status_code, 409)
        other = Wallet.objects.create(user=self.user, wallet_type=WalletType.objects.get_or_create(name='savings', defaults={'automatic_creation': False})[0])
        self.assertEqual(self.post(kind='INCREASED', url=f'/api/wallets/types/{other.wallet_type_id}/transactions/', key=str(uuid4())).status_code, 201)
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_insufficient_balance_is_recorded_and_duplicate_blocked_after_topup(self):
        response = self.post(amount='101.00')
        self.assertEqual(response.status_code, 400)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))
        self.assertEqual(self.wallet.transactions.get().status, 'FAILED')
        self.post(kind='INCREASED', amount='200.00', key=str(uuid4()))
        self.assertEqual(self.post(amount='101.00').status_code, 400)
        self.assertEqual(self.post(amount='101.00').json(), response.json())
        self.assertEqual(self.wallet.transactions.count(), 2)

    def test_ownership_and_missing_wallet(self):
        other = Customer.objects.create_user(
            mobile='09987654321', national_code='0098765432', password='other-test-password',
        )
        wallet = Wallet.objects.create(user=other, wallet_type=WalletType.objects.get_or_create(name='private', defaults={'automatic_creation': False})[0])
        for wallet_id in (wallet.wallet_type_id, wallet.wallet_type_id + 100):
            response = self.post(url=f'/api/wallets/types/{wallet_id}/transactions/', key=str(uuid4()))
            self.assertEqual(response.status_code, 404)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_key_is_scoped_to_customer(self):
        self.post()
        other = Customer.objects.create_user(
            mobile='09987654321', national_code='0098765432', password='other-test-password',
        )
        wallet = Wallet.objects.create(user=other, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0])
        self.auth = f'Bearer {create_access_token(other)}'
        response = self.post(kind='INCREASED', url=f'/api/wallets/types/{wallet.wallet_type_id}/transactions/')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.redis.dbsize(), 2)

    def test_invalid_amounts_and_types(self):
        for amount in ('0', '-1', '0.001', 'NaN', 'Infinity', '1000000000000000000.00', 25, None):
            with self.subTest(amount=amount):
                self.assertEqual(self.post(amount=amount).status_code, 400)
        self.assertEqual(self.post(kind='INVALID').status_code, 400)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_overflow_returns_error_without_changing_balance(self):
        # SQLite cannot represent the model's maximum NUMERIC(20, 2) exactly.
        # Use a smaller limit to exercise the same overflow branch on every backend.
        with patch('wallets.services.MAX_BALANCE', Decimal('100.00')):
            response = self.post(kind='INCREASED', amount='0.01')
        self.assertEqual(response.status_code, 400)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))

    def test_authentication_and_request_format(self):
        self.assertEqual(self.client.post(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url, HTTP_AUTHORIZATION=self.auth).status_code, 405)
        headers = {'HTTP_AUTHORIZATION': self.auth}
        self.assertEqual(self.client.post(self.url, **headers).status_code, 415)
        for body in ('{', '[]', '{}', '{"amount":"1"}', '{"type":"INCREASED"}'):
            self.assertEqual(self.client.post(
                self.url, data=body, content_type='application/json', **headers,
            ).status_code, 400)

    def test_database_failure_rolls_back_money_and_transaction(self):
        with patch('wallets.models.Wallet.save', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.post()
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))
        self.assertFalse(WalletTransaction.objects.exists())
        self.assertEqual(self.post().status_code, 409)

    def test_reservation_loss_before_commit_rolls_back_money(self):
        from wallets.decorators import ReservationExpired
        reservation = Mock(side_effect=[None, None, ReservationExpired])
        with self.assertRaises(ReservationExpired):
            change_balance(
                customer=self.user, wallet_type_id=self.wallet.wallet_type_id,
                kind='DECREASED', amount=Decimal('25.00'),
                ensure_reservation=reservation, request_id=uuid4(),
            )
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))
        self.assertFalse(WalletTransaction.objects.exists())

    def test_missing_and_invalid_request_id(self):
        for key in ('', 'invalid', 'x' * 1000):
            self.assertEqual(self.post(key=key).status_code, 400)
        self.assertFalse(WalletTransaction.objects.exists())
        self.assertEqual(self.redis.dbsize(), 0)

    def test_new_id_allows_another_withdrawal_immediately(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post(key=str(uuid4())).status_code, 201)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('50.00'))

    def test_replay_survives_redis_loss_and_outage(self):
        original = self.post()
        self.redis.flushall()
        with patch('wallets.decorators.get_redis', side_effect=AssertionError('Redis should not be needed')):
            retry = self.post()
        self.assertEqual(retry.json(), original.json())
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_operation_record_failure_rolls_back_balance(self):
        with patch('wallets.services.WalletOperation.objects.create', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.post()
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('100.00'))
        self.assertFalse(WalletTransaction.objects.exists())
        self.assertFalse(WalletOperation.objects.exists())

    def test_same_key_different_type_or_wallet_conflicts(self):
        self.post()
        self.assertEqual(self.post(kind='INCREASED').status_code, 409)
        self.assertEqual(self.post(url='/api/wallets/types/99999/transactions/').status_code, 409)


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentTransactionTests(TransactionTestCase):
    def setUp(self):
        self.user = Customer.objects.create_user(
            mobile='09123456789', national_code='0012345678', password='transaction-test-password',
        )
        self.wallet = Wallet.objects.create(user=self.user, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0], balance=Decimal('100.00'))

    def run_requests(self, keys):
        barrier = Barrier(2)

        def run(key):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return change_balance(customer=self.user, wallet_type_id=self.wallet.wallet_type_id,
                                      kind='DECREASED', amount=Decimal('75.00'), request_id=key)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, keys))

    def test_concurrent_withdrawals_cannot_overdraw(self):
        responses = self.run_requests([uuid4(), uuid4()])
        self.assertEqual(sorted(status for _, status in responses), [201, 400])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('25.00'))
        self.assertEqual(WalletTransaction.objects.filter(status='COMPLETED').count(), 1)
        self.assertEqual(WalletTransaction.objects.filter(status='FAILED').count(), 1)

    def test_concurrent_same_operation_changes_balance_once(self):
        request_id = uuid4()
        responses = self.run_requests([request_id, request_id])
        self.assertEqual(responses[0], responses[1])
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('25.00'))
        self.assertEqual(WalletOperation.objects.count(), 1)
        self.assertEqual(WalletTransaction.objects.count(), 1)
