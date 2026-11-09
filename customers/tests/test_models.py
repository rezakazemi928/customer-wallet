import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from customers.models import Customer


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

