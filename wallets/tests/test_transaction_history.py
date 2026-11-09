from decimal import Decimal

from django.test import TestCase

from customers.models import Customer
from customers.tokens import create_access_token
from wallets.models import Wallet, WalletType, WalletTransaction


class TransactionHistoryTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create_user(mobile='09123456789', national_code='0012345678', password='history-password')
        other = Customer.objects.create_user(mobile='09987654321', national_code='0098765432', password='history-password')
        self.personal = WalletType.objects.get(name='personal')
        self.savings = WalletType.objects.create(name='savings')
        self.wallet = Wallet.objects.create(user=self.customer, wallet_type=self.personal)
        self.second_wallet = Wallet.objects.create(user=self.customer, wallet_type=self.savings)
        self.first = WalletTransaction.objects.create(wallet=self.wallet, type='INCREASED', amount=Decimal('12.34'), status='COMPLETED')
        self.latest = WalletTransaction.objects.create(wallet=self.wallet, type='DECREASED', amount=Decimal('15.00'), status='FAILED')
        hidden = Wallet.objects.create(user=other, wallet_type=self.personal)
        self.hidden_transaction = WalletTransaction.objects.create(wallet=hidden, type='INCREASED', amount=Decimal('99.00'))
        self.auth = f'Bearer {create_access_token(self.customer)}'

    def get(self, query=''):
        return self.client.get('/api/wallets/transactions/' + query, HTTP_AUTHORIZATION=self.auth)

    def test_history_is_grouped_ordered_and_scoped_to_customer(self):
        # One authentication query, one wallet/type query and one transaction query.
        with self.assertNumQueries(3):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        groups = response.json()['wallets']
        self.assertEqual(len(groups), 2)
        personal = next(group for group in groups if group['wallet_type_id'] == self.personal.pk)
        self.assertEqual(personal['wallet_id'], self.wallet.pk)
        self.assertEqual(personal['wallet_type_name'], 'personal')
        self.assertEqual([row['id'] for row in personal['transactions']], [self.latest.pk, self.first.pk])
        self.assertEqual(personal['transactions'][0]['status'], 'FAILED')
        self.assertEqual(personal['transactions'][1]['amount'], '12.34')
        self.assertIn('updated_at', personal['transactions'][0])
        savings = next(group for group in groups if group['wallet_type_id'] == self.savings.pk)
        self.assertEqual(savings['transactions'], [])
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_filter_by_wallet_type(self):
        groups = self.get(f'?wallet_type_id={self.personal.pk}').json()['wallets']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['wallet_type_id'], self.personal.pk)
        self.assertEqual(len(groups[0]['transactions']), 2)

    def test_missing_wallet_returns_empty_without_creation(self):
        kind = WalletType.objects.create(name='unused', automatic_creation=True)
        count = self.customer.wallets.count()
        for type_id in (kind.pk, 999999):
            response = self.get(f'?wallet_type_id={type_id}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'wallets': []})
        self.assertEqual(self.customer.wallets.count(), count)

    def test_invalid_query(self):
        for value in ('', 'abc', '-1', '0', '1.2', '9' * 30, '9223372036854775808'):
            with self.subTest(value=value):
                self.assertEqual(self.get(f'?wallet_type_id={value}').status_code, 400)
        self.assertEqual(self.get('?wallet_type_id=1&wallet_type_id=2').status_code, 400)

    def test_no_wallets(self):
        empty = Customer.objects.create_user(mobile='09121111111', national_code='0011111111', password='history-password')
        self.auth = f'Bearer {create_access_token(empty)}'
        self.assertEqual(self.get().json(), {'wallets': []})

    def test_requires_token_and_get(self):
        self.assertEqual(self.client.get('/api/wallets/transactions/').status_code, 401)
        self.assertEqual(self.client.get('/api/wallets/transactions/', HTTP_AUTHORIZATION='Bearer invalid').status_code, 401)
        self.assertEqual(self.client.post('/api/wallets/transactions/', HTTP_AUTHORIZATION=self.auth).status_code, 405)
