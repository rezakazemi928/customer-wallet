from datetime import date

from django.test import TestCase

from customers.models import Customer


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

