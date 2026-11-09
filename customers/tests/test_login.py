from django.test import TestCase

from customers.models import Customer


class LoginTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create_user(
            mobile='09123456789', national_code='0012345678',
            password='Strong-customer-pass-72!',
        )

    def post(self, **changes):
        data = {'mobile': self.customer.mobile, 'password': 'Strong-customer-pass-72!'}
        data.update(changes)
        return self.client.post('/api/customers/login/', data=data,
                                content_type='application/json')

    def test_login_returns_one_hour_token(self):
        from customers.tokens import decode_access_token
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['expires_in'], 3600)
        self.assertEqual(data['token_type'], 'Bearer')
        payload = decode_access_token(data['access_token'])
        self.assertEqual(payload['userId'], str(self.customer.pk))
        self.assertEqual(payload['exp'] - payload['iat'], 3600)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertNotIn('password', data)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_invalid_credentials_have_same_error(self):
        wrong_password = self.post(password='incorrect')
        unknown_mobile = self.post(mobile='09999999999')
        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(unknown_mobile.status_code, 401)
        self.assertEqual(wrong_password.json(), unknown_mobile.json())

    def test_invalid_input(self):
        for changes in ({'password': ''}, {'mobile': None}, {'mobile': []},
                        {'password': 123}, {'extra': 'value'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(**changes).status_code, 400)
        for body in ('{', '[]', '{}', '{"mobile":"09123456789"}'):
            response = self.client.post('/api/customers/login/', data=body,
                                        content_type='application/json')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/customers/login/').status_code, 405)
        self.assertEqual(self.client.post('/api/customers/login/').status_code, 415)

    def test_expired_forged_and_incomplete_tokens_are_rejected(self):
        import time
        import jwt
        from django.conf import settings
        from customers.tokens import decode_access_token
        now = int(time.time())
        base = {'userId': str(self.customer.pk), 'iat': now, 'exp': now + 3600}
        invalid = [
            jwt.encode(base, 'incorrect-signing-key-at-least-32-bytes', algorithm='HS256'),
            jwt.encode({**base, 'iat': now - 3601, 'exp': now - 1},
                       settings.JWT_SIGNING_KEY, algorithm='HS256'),
            jwt.encode({'userId': str(self.customer.pk)},
                       settings.JWT_SIGNING_KEY, algorithm='HS256'),
            jwt.encode({**base, 'userId': 'invalid'}, settings.JWT_SIGNING_KEY, algorithm='HS256'),
            jwt.encode({**base, 'exp': now + 7200}, settings.JWT_SIGNING_KEY, algorithm='HS256'),
            'malformed',
        ]
        for token in invalid:
            with self.subTest(token=token), self.assertRaises(jwt.InvalidTokenError):
                decode_access_token(token)

    def test_bearer_decorator(self):
        from django.http import JsonResponse
        from django.test import RequestFactory
        from customers.tokens import customer_token_required, create_access_token

        @customer_token_required
        def protected(request):
            return JsonResponse({'id': str(request.customer.pk)})

        factory = RequestFactory()
        token = create_access_token(self.customer)
        response = protected(factory.get('/', HTTP_AUTHORIZATION=f'Bearer {token}'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(protected(factory.get('/')).status_code, 401)
        self.assertEqual(protected(factory.get('/', HTTP_AUTHORIZATION='Bearer bad')).status_code, 401)
        self.customer.delete()
        self.assertEqual(protected(factory.get('/', HTTP_AUTHORIZATION=f'Bearer {token}')).status_code, 401)

