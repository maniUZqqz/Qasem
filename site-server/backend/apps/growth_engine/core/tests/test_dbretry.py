from unittest import mock

from django.db.utils import OperationalError
from django.test import SimpleTestCase, TestCase

from apps.growth_engine.core.dbretry import is_locked_error, retry_locked
from apps.growth_engine.core.dispatch import dispatch
from apps.growth_engine.discovery.models import DiscoveryJob


class RetryLockedTests(SimpleTestCase):
    def test_a_lock_conflict_is_repeated_until_it_works(self):
        calls, slept = [], []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise OperationalError("database is locked")
            return "done"

        self.assertEqual(retry_locked(flaky, sleep=slept.append), "done")
        self.assertEqual((len(calls), len(slept)), (3, 2))
        self.assertTrue(all(s > 0 for s in slept))

    def test_it_gives_up_after_the_attempts(self):
        calls = []

        def always():
            calls.append(1)
            raise OperationalError("database is locked")

        with self.assertRaises(OperationalError):
            retry_locked(always, attempts=3, sleep=lambda s: None)
        self.assertEqual(len(calls), 3)

    def test_other_database_errors_are_not_retried(self):
        calls = []

        def broken():
            calls.append(1)
            raise OperationalError("no such table: nope")

        with self.assertRaises(OperationalError):
            retry_locked(broken, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_only_database_errors_are_caught(self):
        with self.assertRaises(ValueError):
            retry_locked(lambda: (_ for _ in ()).throw(ValueError("x")), sleep=lambda s: None)

    def test_error_detection(self):
        self.assertTrue(is_locked_error(OperationalError("database is locked")))
        self.assertTrue(is_locked_error(OperationalError("Database table is locked")))
        self.assertFalse(is_locked_error(OperationalError("syntax error")))


class DispatchTests(TestCase):
    def test_the_task_id_is_stored_before_the_message_is_sent(self):
        job = DiscoveryJob.objects.create(file_name="x.csv")
        seen = {}

        class FakeTask:
            def apply_async(self, args, task_id):
                seen["db_value_at_send_time"] = DiscoveryJob.objects.get(pk=job.pk).celery_task_id
                seen["task_id"] = task_id

        task_id = dispatch(FakeTask(), DiscoveryJob, job.pk)
        self.assertEqual(seen["db_value_at_send_time"], task_id)
        self.assertEqual(seen["task_id"], task_id)
        self.assertEqual(len(task_id), 32)
