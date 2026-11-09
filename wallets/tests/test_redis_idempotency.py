import time
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import fakeredis
from django.http import JsonResponse
from django.test import SimpleTestCase
from redis.exceptions import ConnectionError

from wallets.decorators import (
    redis_wallet_idempotency, transaction_cache_key,
)


class RedisIdempotencyTests(SimpleTestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.request = SimpleNamespace(customer=SimpleNamespace(pk=uuid4()),
                                       transaction_data={'type': 'INCREASED', 'amount': Decimal('10.00')},
                                       headers={'Idempotency-Key': str(uuid4())})
        self.key = transaction_cache_key(self.request.customer.pk, self.request.headers['Idempotency-Key'])
        patcher = patch('wallets.decorators.get_redis', return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        lookup = patch('wallets.decorators.find_operation_result', return_value=None)
        lookup.start()
        self.addCleanup(lookup.stop)

    def test_completed_key_expires_after_three_minutes(self):
        @redis_wallet_idempotency
        def view(request, wallet_id):
            self.assertGreaterEqual(self.redis.ttl(self.key), 119)
            self.assertLessEqual(self.redis.ttl(self.key), 120)
            return JsonResponse({}, status=201)

        self.assertEqual(view(self.request, 1).status_code, 201)
        self.assertEqual(self.redis.get(self.key), 'COMPLETED')
        self.assertGreaterEqual(self.redis.ttl(self.key), 179)
        self.assertLessEqual(self.redis.ttl(self.key), 180)
        self.assertEqual(view(self.request, 1).status_code, 409)
        with patch('time.time', return_value=time.time() + 181):
            self.assertEqual(view(self.request, 1).status_code, 201)

    def test_in_progress_key_expires_after_two_minutes(self):
        self.redis.set(self.key, 'IN_PROGRESS:other', ex=120)
        view = redis_wallet_idempotency(lambda request, wallet_id: JsonResponse({}, status=201))
        self.assertEqual(view(self.request, 1).status_code, 409)
        with patch('time.time', return_value=time.time() + 121):
            self.assertEqual(view(self.request, 1).status_code, 201)

    def test_atomic_reservation_allows_only_one_simultaneous_request(self):
        entered = Event()
        finish = Event()

        @redis_wallet_idempotency
        def view(request, wallet_id):
            entered.set()
            if not finish.wait(timeout=5):
                raise RuntimeError('Timed out waiting for test')
            return JsonResponse({}, status=201)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(view, self.request, 1)
            self.assertTrue(entered.wait(timeout=5))
            try:
                second = pool.submit(view, self.request, 1).result(timeout=5)
                self.assertEqual(second.status_code, 409)
            finally:
                finish.set()
            self.assertEqual(first.result(timeout=5).status_code, 201)

    def test_old_worker_cannot_overwrite_new_reservation(self):
        @redis_wallet_idempotency
        def view(request, wallet_id):
            self.redis.set(self.key, 'IN_PROGRESS:new-owner', ex=120)
            return JsonResponse({}, status=201)

        with self.assertLogs('wallets.decorators', level='WARNING'):
            self.assertEqual(view(self.request, 1).status_code, 201)
        self.assertEqual(self.redis.get(self.key), 'IN_PROGRESS:new-owner')

    def test_old_worker_cannot_delete_new_reservation(self):
        @redis_wallet_idempotency
        def view(request, wallet_id):
            self.redis.set(self.key, 'IN_PROGRESS:new-owner', ex=120)
            return JsonResponse({}, status=404)

        view(self.request, 1)
        self.assertEqual(self.redis.get(self.key), 'IN_PROGRESS:new-owner')

    def test_missing_wallet_releases_reservation(self):
        view = redis_wallet_idempotency(lambda request, wallet_id: JsonResponse({}, status=404))
        self.assertEqual(view(self.request, 1).status_code, 404)
        self.assertIsNone(self.redis.get(self.key))

    def test_redis_failure_prevents_execution(self):
        def view(request, wallet_id):
            self.fail('Wallet operation must not run')
        with patch.object(self.redis, 'set', side_effect=ConnectionError):
            self.assertEqual(redis_wallet_idempotency(view)(self.request, 1).status_code, 503)

    def test_finalization_failure_preserves_committed_response(self):
        view = redis_wallet_idempotency(lambda request, wallet_id: JsonResponse({'balance': '10.00'}, status=201))
        with patch.object(self.redis, 'eval', side_effect=ConnectionError):
            with self.assertLogs('wallets.decorators', level='ERROR'):
                self.assertEqual(view(self.request, 1).status_code, 201)
        self.assertTrue(self.redis.get(self.key).startswith('IN_PROGRESS:'))

    def test_lost_reservation_is_detected_before_money_changes(self):
        @redis_wallet_idempotency
        def view(request, wallet_id):
            self.redis.delete(self.key)
            request.ensure_wallet_reservation()
            self.fail('Reservation should have expired')
        self.assertEqual(view(self.request, 1).status_code, 409)
