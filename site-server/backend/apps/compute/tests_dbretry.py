"""SQLite «database is locked» در صفِ پردازش: تکرار، ساختِ کاملِ کار، و اینکه قفل هرگز کاری را ناموفق نمی‌کند."""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.db import OperationalError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import dbretry, services as SV
from .models import ComputeJob, ComputeNode

TMP = tempfile.mkdtemp(prefix="nm-compute-lock-test-")
LOCKED = OperationalError("database is locked")


def flaky(fail_times, real):
    """تابعی که n بار «database is locked» می‌دهد و بعد کارِ واقعی را می‌کند."""
    state = {"left": fail_times, "calls": 0}

    def wrapper(*a, **kw):
        state["calls"] += 1
        if state["left"] > 0:
            state["left"] -= 1
            raise LOCKED
        return real(*a, **kw)

    wrapper.state = state
    return wrapper


@mock.patch.object(dbretry.time, "sleep", lambda s: None)
class RetryHelperTests(TransactionTestCase):
    def test_lock_errors_are_recognised_but_not_other_operational_errors(self):
        self.assertTrue(dbretry.is_lock_error(OperationalError("database is locked")))
        self.assertTrue(dbretry.is_lock_error(OperationalError("database table is locked: x")))
        self.assertFalse(dbretry.is_lock_error(OperationalError("no such table: compute_computejob")))
        self.assertFalse(dbretry.is_lock_error(ValueError("database is locked")))

    def test_retries_then_succeeds(self):
        f = flaky(3, lambda: "done")
        self.assertEqual(dbretry.call_with_retry(f), "done")
        self.assertEqual(f.state["calls"], 4)

    def test_other_errors_are_not_retried(self):
        calls = []

        def boom():
            calls.append(1)
            raise OperationalError("no such table: x")

        with self.assertRaises(OperationalError):
            dbretry.call_with_retry(boom)
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_the_tries(self):
        f = flaky(99, lambda: "x")
        with self.assertRaises(OperationalError):
            dbretry.call_with_retry(f, _tries=3)
        self.assertEqual(f.state["calls"], 3)

    def test_never_retries_inside_an_atomic_block(self):
        from django.db import transaction
        f = flaky(1, lambda: "x")
        with transaction.atomic():
            with self.assertRaises(OperationalError):
                dbretry.call_with_retry(f)
        self.assertEqual(f.state["calls"], 1, "داخلِ تراکنش تکرار بی‌معناست؛ بیرونی‌ترین لایه تکرار می‌کند")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
@mock.patch.object(dbretry.time, "sleep", lambda s: None)
class QueueSurvivesLocksTests(TransactionTestCase):
    def setUp(self):
        self.node = ComputeNode.objects.create(name="gpu-1", capabilities={"comfyui": True}, last_seen=timezone.now())

    def test_enqueue_creates_the_whole_job_in_one_insert_even_through_locks(self):
        src = Path(TMP) / "in.bin"
        src.write_bytes(b"abc")
        real = ComputeJob.save
        f = flaky(2, real)
        with mock.patch.object(ComputeJob, "save", f):
            job = SV.enqueue_durable("comfy.graph", {"graph": {"1": 1}}, {"in.bin": str(src)}, dedupe=False)
        self.assertEqual(f.state["calls"], 3)
        job = ComputeJob.objects.get(pk=job.pk)
        self.assertEqual(job.inputs, {"in.bin": "inputs/in.bin"}, "ردیف باید با inputs کامل ساخته شود، نه نیمه‌کاره")
        self.assertTrue((SV.job_root(job) / "inputs" / "in.bin").is_file())
        self.assertEqual(ComputeJob.objects.count(), 1)

    def test_enqueue_that_cannot_write_leaves_nothing_behind(self):
        src = Path(TMP) / "in2.bin"
        src.write_bytes(b"xyz")
        with mock.patch.object(ComputeJob, "save", flaky(99, ComputeJob.save)):
            with self.assertRaises(OperationalError):
                SV.enqueue_durable("comfy.graph", {"graph": {"2": 2}}, {"in2.bin": str(src)}, dedupe=False)
        self.assertEqual(ComputeJob.objects.count(), 0)
        self.assertFalse(any(p.name for p in (Path(TMP) / "compute" / "jobs").glob("*/inputs/in2.bin")),
                         "پوشهٔ ورودیِ کارِ ساخته‌نشده باید پاک شود")

    def test_claim_retries_the_conditional_update(self):
        job = SV.enqueue_durable("comfy.graph", {"graph": {"3": 3}}, dedupe=False)
        real_update = SV._claim_row.__wrapped__
        f = flaky(2, real_update)
        with mock.patch.object(SV, "_claim_row", dbretry.retry_on_lock(f)):
            got = SV.claim(self.node)
        self.assertEqual(got.pk, job.pk)
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts), ("CLAIMED", 1), "قفل نباید دو بار attempt بسوزاند یا کار را دو بار بدهد")

    def test_a_lock_during_finish_does_not_fail_the_job_nor_double_count(self):
        job = SV.enqueue_durable("comfy.graph", {"graph": {"4": 4}}, dedupe=False)
        SV.claim(self.node)
        SV.output_path(job, "o.png").write_bytes(b"png")
        job.refresh_from_db()
        f = flaky(2, SV._save.__wrapped__)
        with mock.patch.object(SV, "_save", dbretry.retry_on_lock(f)):
            SV.finish(job, self.node, True, meta={"primary": "o.png"})
        job.refresh_from_db()
        self.node.refresh_from_db()
        self.assertEqual(job.state, "COMPLETED")
        self.assertEqual(self.node.jobs_done, 1)

    def test_a_lock_during_a_real_failure_requeues_instead_of_failing(self):
        job = SV.enqueue_durable("comfy.graph", {"graph": {"5": 5}}, dedupe=False)
        SV.claim(self.node)
        job.refresh_from_db()
        f = flaky(2, SV._save.__wrapped__)
        with mock.patch.object(SV, "_save", dbretry.retry_on_lock(f)):
            SV.finish(job, self.node, False, "real error")
        job.refresh_from_db()
        self.assertEqual(job.state, "QUEUED", "خطای واقعیِ اول هنوز تلاشِ دوم دارد؛ قفل چیزی را عوض نکرد")

    def test_requeue_stale_survives_a_lock(self):
        job = SV.enqueue_durable("comfy.graph", {"graph": {"6": 6}}, dedupe=False, lease_s=1)
        SV.claim(self.node)
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now() - timedelta(minutes=10))
        ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=30))
        real = ComputeJob.save
        f = flaky(2, real)
        with mock.patch.object(ComputeJob, "save", f):
            self.assertEqual(SV.requeue_stale(), 1)
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts, job.lost_count), ("QUEUED", 0, 1))


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
@mock.patch.object(dbretry.time, "sleep", lambda s: None)
class NodeEndpointsUnderLockTests(TransactionTestCase):
    def setUp(self):
        self.node = ComputeNode.objects.create(name="gpu-1", capabilities={"comfyui": True},
                                               last_seen=timezone.now() - timedelta(minutes=5))
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)

    def test_last_seen_is_not_rewritten_on_every_call(self):
        self.node.refresh_from_db()
        self.c.post("/api/v1/compute/heartbeat/", {"comfyui": True}, format="json")
        self.node.refresh_from_db()
        first = self.node.last_seen
        self.assertTrue(self.node.online)
        self.c.post("/api/v1/compute/claim/", {}, format="json")
        self.node.refresh_from_db()
        self.assertEqual(self.node.last_seen, first, "هر درخواستِ گره نباید یک نوشتن باشد (کمتر از ۸ ثانیه)")

    def test_a_lock_on_last_seen_never_breaks_the_node_call(self):
        with mock.patch.object(ComputeNode, "save", flaky(99, ComputeNode.save)):
            r = self.c.post("/api/v1/compute/claim/", {}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_persistent_lock_answers_503_retry_after_not_500(self):
        with mock.patch.object(SV, "claim", side_effect=OperationalError("database is locked")):
            r = self.c.post("/api/v1/compute/claim/", {}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r["Retry-After"], "5")
        self.assertTrue(r.json()["retry"])

    def test_other_database_errors_are_still_errors(self):
        c = APIClient(raise_request_exception=False)
        c.credentials(HTTP_AUTHORIZATION="Node " + self.node.token)
        with mock.patch.object(SV, "claim", side_effect=OperationalError("no such table: x")):
            r = c.post("/api/v1/compute/claim/", {}, format="json")
        self.assertEqual(r.status_code, 500)


class DatabaseSettingsTests(TestCase):
    def test_sqlite_is_configured_for_concurrent_writers(self):
        from django.conf import settings
        db = settings.DATABASES["default"]
        if "sqlite" not in db["ENGINE"]:
            self.skipTest("not sqlite")
        self.assertIn("busy_timeout", db["OPTIONS"]["init_command"])
        self.assertGreaterEqual(db["OPTIONS"]["timeout"], 20)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
@mock.patch.object(dbretry.time, "sleep", lambda s: None)
class JobStatusAndWakeTests(TransactionTestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.jobs.models import Job
        from apps.stores.models import Store
        self.Job = Job
        user = get_user_model().objects.create_user("owner", "o@x.io", "pw")
        self.store = Store.objects.create(owner=user, name="shop")

    def test_celery_job_status_updates_survive_a_momentary_lock(self):
        from django.db.models import Model
        job = self.Job.objects.create(store=self.store, type=self.Job.Type.IMAGE_GENERATION, state="PROCESSING")
        f = flaky(2, Model.save)
        with mock.patch.object(Model, "save", f):
            job.mark_progress(1, "نیمهٔ راه")
        job.refresh_from_db()
        self.assertEqual((job.progress_step, job.current_step_label), (1, "نیمهٔ راه"))
        self.assertEqual(f.state["calls"], 3)

    def test_waking_many_parked_jobs_is_staggered(self):
        from . import park
        node = ComputeNode.objects.create(name="gpu-1", capabilities={"comfyui": True, "slots": 50}, last_seen=timezone.now())
        for i in range(20):
            row = self.Job.objects.create(store=self.store, type=self.Job.Type.IMAGE_GENERATION, state="QUEUED")
            ComputeJob.objects.create(kind=park.PARK_KIND, state="QUEUED", queued_at=timezone.now(), timeout_s=0, request_hash="",
                                      payload={"capability": "comfyui", "task": "t", "args": [row.pk], "kwargs": {},
                                               "ref": {"model": "jobs.Job", "id": row.pk}})
        with mock.patch.object(park, "_dispatch", return_value=True) as d:
            self.assertEqual(park.wake_parked(), park.WAKE_BATCH)
            self.assertEqual(d.call_count, park.WAKE_BATCH)
            self.assertEqual(park.wake_parked(), park.WAKE_BATCH)
            self.assertEqual(park.wake_parked(), 20 - 2 * park.WAKE_BATCH)
        self.assertFalse(ComputeJob.objects.filter(kind=park.PARK_KIND, state="QUEUED").exists())
        self.assertTrue(node.online)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ScheduleGuardTests(TestCase):
    def test_window_text_must_be_a_real_clock_time(self):
        self.assertIsNone(SV.parse_window("07:61-08:00"))
        self.assertIsNone(SV.parse_window("24:00-08:00"))
        self.assertEqual(SV.parse_window("23:59-00:30"), (23 * 60 + 59, 30))

    def test_scheduled_downloads_are_not_expired_while_they_wait_for_their_time(self):
        from .models import ComputeSettings
        ComputeNode.objects.create(name="gpu-1", capabilities={"ollama": True}, last_seen=timezone.now() - timedelta(hours=1))
        cfg = ComputeSettings.get()
        cfg.max_wait_hours = 1
        cfg.save()
        later = SV.enqueue_durable("ollama.pull", {"model": "m"}, node="gpu-1", dedupe=False,
                                   not_before=timezone.now() + timedelta(hours=8))
        plain = SV.enqueue_durable("ollama.pull", {"model": "n"}, node="gpu-1", dedupe=False)
        ComputeJob.objects.filter(pk__in=[later.pk, plain.pk]).update(queued_at=timezone.now() - timedelta(hours=5))
        self.assertEqual(SV.expire_overdue(force=True), 1)
        later.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual(later.state, "QUEUED")
        self.assertEqual(plain.state, "FAILED")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class BusyNodeAndTextWakeTests(TransactionTestCase):
    def test_a_node_that_is_on_but_too_busy_means_wait_not_fail(self):
        from services.ai import priority, routing
        ComputeNode.objects.create(name="gpu-1", capabilities={"ollama": True}, last_seen=timezone.now())
        router = routing._Router("t")
        failures = {routing.LOCAL: priority.Failure("busy", "سرورِ پردازش کار را در ۴۵ ثانیه برنداشت", provider=routing.LOCAL),
                    routing.METIS: priority.Failure("no_credit", "اعتبار تمام شد", provider=routing.METIS)}
        exc = router._all_failed([routing.LOCAL, routing.METIS], failures)
        self.assertEqual(getattr(exc, "node_waiting", ""), "ollama")
        failures[routing.LOCAL] = priority.Failure("error", "خطای واقعیِ مدل", provider=routing.LOCAL)
        self.assertFalse(getattr(router._all_failed([routing.LOCAL, routing.METIS], failures), "node_waiting", ""))

    def test_text_tasks_wake_in_small_batches_other_capabilities_unaffected(self):
        from django.contrib.auth import get_user_model
        from apps.jobs.models import Job
        from apps.stores.models import Store
        from . import park
        user = get_user_model().objects.create_user("owner2", "o2@x.io", "pw")
        store = Store.objects.create(owner=user, name="shop2")
        ComputeNode.objects.create(name="gpu-1", capabilities={"ollama": True, "comfyui": True, "slots": 50}, last_seen=timezone.now())
        for cap, n in (("ollama", 7), ("comfyui", 4)):
            for _ in range(n):
                row = Job.objects.create(store=store, type=Job.Type.IMAGE_GENERATION, state="QUEUED")
                ComputeJob.objects.create(kind=park.PARK_KIND, state="QUEUED", queued_at=timezone.now(), timeout_s=0, request_hash="",
                                          payload={"capability": cap, "task": "t", "args": [row.pk], "kwargs": {},
                                                   "ref": {"model": "jobs.Job", "id": row.pk}})
        with mock.patch.object(park, "_dispatch", return_value=True):
            self.assertEqual(park.wake_parked(), 3 + 4, "اولین دقیقه: ۳ متن + هر ۴ تصویر")
            self.assertEqual(park.wake_parked(), 3)
            self.assertEqual(park.wake_parked(), 1)
        self.assertFalse(ComputeJob.objects.filter(kind=park.PARK_KIND, state="QUEUED").exists())
