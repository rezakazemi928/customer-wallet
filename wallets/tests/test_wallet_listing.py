from decimal import Decimal

from django.test import TestCase

from customers.models import Customer
from wallets.models import Wallet, WalletType


class WalletEndpointTests(TestCase):
    def setUp(self):
        from customers.tokens import create_access_token
        self.customer = Customer.objects.create_user(
            mobile='09123456789', national_code='0012345678', password='wallet-test-password',
        )
        self.other = Customer.objects.create_user(
            mobile='09987654321', national_code='0098765432', password='other-test-password',
        )
        self.authorization = f'Bearer {create_access_token(self.customer)}'

    def test_lists_only_authenticated_customers_wallets(self):
        first = Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='personal', defaults={'automatic_creation': True})[0], balance=Decimal('123.45'))
        second = Wallet.objects.create(user=self.customer, wallet_type=WalletType.objects.get_or_create(name='savings', defaults={'automatic_creation': False})[0])
        Wallet.objects.create(user=self.other, wallet_type=WalletType.objects.get_or_create(name='private', defaults={'automatic_creation': False})[0])
        response = self.client.get(
            f'/api/wallets/?user_id={self.other.pk}', HTTP_AUTHORIZATION=self.authorization,
        )
        self.assertEqual(response.status_code, 200)
        wallets = response.json()['wallets']
        self.assertEqual([wallet['id'] for wallet in wallets], [first.id, second.id])
        self.assertEqual(wallets[0]['balance'], '123.45')
        self.assertEqual(wallets[1]['balance'], '0.00')
        self.assertEqual(wallets[0]['wallet_type_name'], 'personal')
        self.assertEqual(wallets[0]['user_id'], str(self.customer.pk))
        self.assertIn('created_at', wallets[0])
        self.assertIn('updated_at', wallets[0])

    def test_no_wallets_returns_empty_list(self):
        response = self.client.get('/api/wallets/', HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'wallets': []})

    def test_missing_invalid_expired_and_forged_tokens(self):
        import time
        import jwt
        from django.conf import settings
        now = int(time.time())
        expired = jwt.encode(
            {'userId': str(self.customer.pk), 'iat': now - 3601, 'exp': now - 1},
            settings.JWT_SIGNING_KEY, algorithm='HS256',
        )
        forged = jwt.encode(
            {'userId': str(self.customer.pk), 'iat': now, 'exp': now + 3600},
            'different-signing-key-at-least-32-bytes', algorithm='HS256',
        )
        for authorization in ('', 'Bearer invalid', f'Bearer {expired}', f'Bearer {forged}'):
            with self.subTest(authorization=authorization):
                response = self.client.get('/api/wallets/', HTTP_AUTHORIZATION=authorization)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('wallets', response.json())

    def test_post_is_not_allowed(self):
        response = self.client.post('/api/wallets/', HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual(response.status_code, 405)

