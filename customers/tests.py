import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Customer


class CustomerTests(TestCase):
    def create_customer(self, **overrides):
        fields = {
            'mobile': '09123456789',
            'national_code': '0012345678',
            'birthdate': date(1995, 1, 1),
            'password': 'customer-test-password',
        }
        fields.update(overrides)
        return Customer.objects.create_user(**fields)

    def test_customer_password_and_timestamps(self):
        customer = self.create_customer()
        self.assertIsInstance(customer.pk, uuid.UUID)
        self.assertTrue(customer.check_password('customer-test-password'))
        self.assertNotEqual(customer.password, 'customer-test-password')
        self.assertIsNotNone(customer.created_at)
        previous_update = customer.updated_at
        customer.first_name = 'Ali'
        customer.save()
        self.assertGreater(customer.updated_at, previous_update)

    def test_required_fields(self):
        for field in ('mobile', 'national_code', 'password'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.create_customer(**{field: None})

    def test_mobile_and_national_code_are_unique(self):
        self.create_customer()
        for fields in (
            {'national_code': '0098765432'},
            {'mobile': '09987654321'},
        ):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    self.create_customer(**fields)

    def test_multiple_customers_can_omit_username(self):
        self.create_customer(username='')
        customer = self.create_customer(mobile='09987654321', national_code='0098765432')
        self.assertIsNone(customer.username)

    def test_admin_uses_default_django_user(self):
        user_model = get_user_model()
        self.assertEqual(user_model._meta.label, 'auth.User')
        admin = user_model.objects.create_superuser(
            username='admin', password='admin-test-password',
        )
        self.client.force_login(admin)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)

    def test_empty_password_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'Password is required.'):
            self.create_customer(password='')


class RegistrationTests(TestCase):
    url = '/api/customers/register/'

    def payload(self, **changes):
        data = {
            'mobile': '09123456789', 'national_code': '0012345678',
            'password': 'Strong-customer-pass-72!',
        }
        data.update(changes)
        return data

    def post(self, data):
        return self.client.post(self.url, data=data, content_type='application/json')

    def test_registration_hashes_password_and_does_not_expose_it(self):
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 201)
        customer = Customer.objects.get(pk=response.json()['id'])
        self.assertTrue(customer.check_password(self.payload()['password']))
        self.assertEqual(customer.national_code, '0012345678')
        self.assertIsNone(customer.birthdate)
        self.assertNotIn('password', response.json())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_required_fields(self):
        for field in ('mobile', 'national_code', 'password'):
            data = self.payload()
            del data[field]
            with self.subTest(field=field):
                response = self.post(data)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['errors'])
        self.assertEqual(Customer.objects.count(), 0)

    def test_invalid_fields(self):
        for changes in (
            {'email': 'invalid'}, {'birthdate': 'invalid'}, {'password': '123'},
            {'mobile': ['123']}, {'is_staff': True}, {'password': ''},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(self.payload(**changes)).status_code, 400)
        self.assertEqual(Customer.objects.count(), 0)

    def test_duplicates(self):
        self.assertEqual(self.post(self.payload()).status_code, 201)
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 400)
        self.assertIn('mobile', response.json()['errors'])
        self.assertEqual(Customer.objects.count(), 1)

    def test_multiple_customers_can_register_without_profile_details(self):
        self.assertEqual(self.post(self.payload()).status_code, 201)
        response = self.post(self.payload(mobile='09987654321', national_code='0098765432'))
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()['birthdate'])
        self.assertEqual(Customer.objects.count(), 2)

    def test_profile_details_can_be_set_later(self):
        response = self.post(self.payload())
        customer = Customer.objects.get(pk=response.json()['id'])
        customer.national_code = '0012345678'
        customer.birthdate = date(1995, 1, 1)
        customer.full_clean()
        customer.save()
        customer.refresh_from_db()
        self.assertEqual(customer.national_code, '0012345678')
        self.assertEqual(customer.birthdate, date(1995, 1, 1))

    def test_request_format_and_method(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(self.url, data={}).status_code, 415)
        for body in ('{', '[]', 'null'):
            response = self.client.post(self.url, data=body, content_type='application/json')
            self.assertEqual(response.status_code, 400)


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
        from .tokens import decode_access_token
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
        from .tokens import decode_access_token
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
        from .tokens import customer_token_required, create_access_token

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
