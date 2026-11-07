"""صفِ ماندگار: کارِ گرهٔ خاموش منتظر می‌ماند، با وصل شدنِ گره اجرا می‌شود، قطعِ گره تلاش نمی‌خورد، فقط خطای واقعی یا لغو می‌کُشد."""
import tempfile
import types
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import park, queue as QV, services as SV
from .models import ComputeJob, ComputeNode, ComputeSettings

TMP = tempfile.mkdtemp(prefix="nm-compute-queue-test-")
OLD = lambda: timezone.now() - timedelta(minutes=30)       # noqa: E731 — «خاموش»: آخرین حضور نیم ساعت پیش


def node(name="gpu-1", online=False, **caps):
    c = {"comfyui": True, "photo": True, "ollama": True, "voice": True}
    c.update(caps)
    return ComputeNode.objects.create(name=name, capabilities=c, last_seen=timezone.now() if online else OLD())


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class DurableQueueTests(TestCase):
    def test_offline_node_job_waits_with_persian_status_and_never_expires(self):
        node()
        job = SV.enqueue_durable("photo.edit", {"auto": True})
        self.assertEqual(job.state, "QUEUED")
        self.assertEqual(job.message, SV.NO_NODE_QUEUED_TEXT)
        # ده روز می‌گذرد و هیچ‌چیز کار را نمی‌کُشد
        ComputeJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=10),
                                                    queued_at=timezone.now() - timedelta(days=10))
        SV.requeue_stale()
        SV.expire_overdue(force=True)
        job.refresh_from_db()
        self.assertEqual(job.state, "QUEUED")
        row = QV.listing("waiting")["jobs"][0]
        self.assertEqual(row["wait_reason"], "no_node")
        self.assertEqual(row["status_text"], "در صف — منتظرِ روشن شدنِ سرورِ پردازش")
        self.assertTrue(row["can_cancel"])
        self.assertEqual(row["waiting_s"] // 86400, 10)

    def test_default_enqueue_still_fails_fast_when_nobody_online(self):
        node()
        with self.assertRaises(SV.ComputeUnavailable):
            SV.enqueue("photo.edit", {"auto": True})

    def test_durable_enqueue_refuses_only_when_no_node_could_ever_run_it(self):
        with self.assertRaises(SV.ComputeUnavailable):
            SV.enqueue_durable("photo.edit", {"x": 1})
        node(photo=False)                                   # گره هست ولی ویرایشگرِ عکس ندارد و نمی‌تواند روشنش کند
        with self.assertRaises(SV.ComputeUnavailable):
            SV.enqueue_durable("photo.edit", {"x": 1})
        node("gpu-2")
        self.assertEqual(SV.enqueue_durable("photo.edit", {"x": 1}).state, "QUEUED")

    def test_node_connects_and_runs_the_waiting_jobs_in_order(self):
        n = node()
        low = SV.enqueue_durable("photo.edit", {"n": "low"}, priority=200)
        first = SV.enqueue_durable("photo.edit", {"n": "first"}, priority=50)
        second = SV.enqueue_durable("photo.edit", {"n": "second"}, priority=50)
        self.assertIsNone(SV.claim(ComputeNode.objects.create(name="other", capabilities={"voice": True},
                                                              last_seen=timezone.now())))
        n.last_seen = timezone.now()
        n.save()
        got = [SV.claim(n).pk, SV.claim(n).pk, SV.claim(n).pk]
        self.assertEqual(got, [first.pk, second.pk, low.pk])
        first.refresh_from_db()
        self.assertEqual(first.state, "CLAIMED")
        self.assertGreaterEqual(first.waited_s, 0)

    def test_node_dropping_mid_job_requeues_without_losing_an_attempt(self):
        n = node(online=True)
        job = SV.enqueue_durable("comfy.graph", {"graph": {"1": {}}})
        job.lease_s = 1
        job.save()
        for round_ in range(1, 6):
            self.assertEqual(SV.claim(n).pk, job.pk)
            job.refresh_from_db()
            self.assertEqual(job.attempts, 1)
            # گره می‌افتد: آخرین حضور و تپش قدیمی می‌شود
            ComputeNode.objects.filter(pk=n.pk).update(last_seen=OLD())
            ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=30))
            n.refresh_from_db()
            self.assertEqual(SV.requeue_stale(), 1)
            job.refresh_from_db()
            self.assertEqual(job.state, "QUEUED")
            self.assertIsNone(job.node)
            self.assertEqual(job.attempts, 0, "قطعِ گره نباید تلاش بخورد")
            self.assertEqual(job.lost_count, round_)
            self.assertEqual(job.message, SV.LOST_NODE_TEXT)
            ComputeNode.objects.filter(pk=n.pk).update(last_seen=timezone.now())
            n.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(job.state, "QUEUED")

    def test_endless_node_killer_eventually_counts_attempts(self):
        n = node(online=True)
        job = SV.enqueue_durable("comfy.graph", {"graph": {"2": {}}})
        ComputeJob.objects.filter(pk=job.pk).update(lease_s=1, lost_count=SV.MAX_LOST_FREE)
        SV.claim(n)
        ComputeNode.objects.filter(pk=n.pk).update(last_seen=OLD())
        ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=30))
        SV.requeue_stale()
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1, "بعد از سقفِ قطع‌های بی‌تقصیر، قطع هم تلاش حساب می‌شود")
        self.assertEqual(job.state, "QUEUED")

    def test_silent_job_on_a_live_node_is_a_hung_job_and_costs_attempts(self):
        n = node(online=True)
        job = SV.enqueue_durable("comfy.graph", {"graph": {"3": {}}})
        ComputeJob.objects.filter(pk=job.pk).update(lease_s=1)
        for expected in ("QUEUED", "FAILED"):
            SV.claim(n)
            ComputeJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=30))
            SV.requeue_stale()
            job.refresh_from_db()
            self.assertEqual(job.state, expected)
            self.assertEqual(job.lost_count, 0)

    def test_real_errors_fail_after_the_retries(self):
        n = node(online=True)
        job = SV.enqueue_durable("comfy.graph", {"graph": {"4": {}}})
        SV.claim(n)
        SV.finish(job, n, False, "boom 1")
        job.refresh_from_db()
        self.assertEqual(job.state, "QUEUED")
        self.assertEqual(job.attempts, 1)
        SV.claim(n)
        SV.finish(job, n, False, "boom 2")
        job.refresh_from_db()
        self.assertEqual(job.state, "FAILED")
        self.assertIn("boom 2", job.error)
        self.assertIsNotNone(job.run_s)

    def test_cancel_works_in_every_state(self):
        n = node()
        queued = SV.enqueue_durable("photo.edit", {"c": 1})
        SV.cancel(queued)
        queued.refresh_from_db()
        self.assertEqual(queued.state, "CANCELLED")
        # روی گرهٔ زنده: فقط نشانه، گره با progress ِ بعدی می‌فهمد
        ComputeNode.objects.filter(pk=n.pk).update(last_seen=timezone.now())
        n.refresh_from_db()
        running = SV.enqueue_durable("photo.edit", {"c": 2})
        SV.claim(n)
        running.refresh_from_db()
        SV.cancel(running)
        running.refresh_from_db()
        self.assertEqual(running.state, "CLAIMED")
        self.assertTrue(running.cancel_requested)
        self.assertEqual(SV.progress(running, {"progress": 0.2}), {"cancel": True})
        # روی گرهٔ خاموش: همان لحظه لغو؛ گره وقتی برگشت از progress می‌فهمد
        ComputeNode.objects.filter(pk=n.pk).update(last_seen=OLD())
        other = SV.enqueue_durable("photo.edit", {"c": 3})
        ComputeNode.objects.filter(pk=n.pk).update(last_seen=timezone.now())
        n.refresh_from_db()
        SV.claim(n)
        other.refresh_from_db()
        ComputeNode.objects.filter(pk=n.pk).update(last_seen=OLD())
        other.refresh_from_db()
        SV.cancel(other)
        other.refresh_from_db()
        self.assertEqual(other.state, "CANCELLED")
        self.assertEqual(SV.progress(other, {"progress": 0.9, "message": "x"}), {"cancel": True})
        other.refresh_from_db()
        self.assertEqual(other.state, "CANCELLED")
        self.assertNotEqual(other.message, "x", "ردیفِ لغوشده نباید با progress ِ دیرهنگام دست بخورد")

    def test_dedupe_still_reuses_a_finished_identical_request(self):
        n = node(online=True)
        job = SV.enqueue_durable("comfy.graph", {"graph": {"5": {"seed": 1}}})
        SV.claim(n)
        SV.output_path(job, "out.png").write_bytes(b"png")
        SV.finish(job, n, True, meta={"primary": "out.png"})
        again = SV.enqueue_durable("comfy.graph", {"graph": {"5": {"seed": 1}}})
        self.assertEqual(again.pk, job.pk)
        self.assertNotEqual(SV.enqueue_durable("comfy.graph", {"graph": {"5": {"seed": 2}}}).pk, job.pk)

    def test_scheduled_job_is_not_given_before_its_time(self):
        n = node(online=True)
        job = SV.enqueue_durable("comfy.graph", {"graph": {"6": {}}}, not_before=timezone.now() + timedelta(hours=2))
        self.assertIsNone(SV.claim(n))
        row = QV.listing("waiting")["jobs"][0]
        self.assertEqual(row["wait_reason"], "scheduled")
        ComputeJob.objects.filter(pk=job.pk).update(not_before=timezone.now() - timedelta(seconds=1))
        self.assertEqual(SV.claim(n).pk, job.pk)

    def test_window_job_is_given_only_inside_the_window(self):
        n = node(online=True)
        now = SV.tehran_now()

        def window(from_h, to_h):
            a, b = now + timedelta(hours=from_h), now + timedelta(hours=to_h)
            return f"{a.hour:02d}:{a.minute:02d}-{b.hour:02d}:{b.minute:02d}"

        closed = SV.enqueue_durable("comfy.graph", {"graph": {"7": {}}}, window=window(2, 3))
        self.assertIsNone(SV.claim(n))
        self.assertEqual(QV.listing("waiting")["jobs"][0]["wait_reason"], "window")
        ComputeJob.objects.filter(pk=closed.pk).update(window=window(-1, 1))
        self.assertEqual(SV.claim(n).pk, closed.pk)

    def test_window_math(self):
        t = lambda h, m: timezone.now().replace(hour=h, minute=m, second=0, microsecond=0) - SV.TEHRAN_OFFSET  # noqa: E731
        self.assertTrue(SV.in_window("02:00-07:00", t(3, 0)))
        self.assertFalse(SV.in_window("02:00-07:00", t(8, 0)))
        self.assertTrue(SV.in_window("22:00-04:00", t(23, 30)))
        self.assertTrue(SV.in_window("22:00-04:00", t(1, 0)))
        self.assertFalse(SV.in_window("22:00-04:00", t(12, 0)))
        self.assertTrue(SV.in_window("", t(12, 0)))
        self.assertIsNone(SV.parse_window("07:00-07:00"))
        self.assertIsNone(SV.parse_window("25:00-07:00"))
        nxt = SV.next_window_start("02:00-07:00", t(8, 0))
        self.assertEqual((SV.tehran_now(nxt).hour, SV.tehran_now(nxt).minute), (2, 0))
        self.assertEqual(SV.next_clock_time("03:30", t(3, 31)).date(), (t(3, 31) + timedelta(days=1)).date())
        self.assertIsNone(SV.next_clock_time("99:99"))

    def test_optional_max_wait_expires_a_job_but_is_off_by_default(self):
        node()
        keep = SV.enqueue_durable("photo.edit", {"m": 0})
        capped = SV.enqueue_durable("photo.edit", {"m": 1}, max_wait_s=60)
        ComputeJob.objects.filter(pk__in=[keep.pk, capped.pk]).update(queued_at=timezone.now() - timedelta(hours=5))
        self.assertEqual(SV.expire_overdue(force=True), 1)
        keep.refresh_from_db()
        capped.refresh_from_db()
        self.assertEqual(keep.state, "QUEUED")
        self.assertEqual(capped.state, "FAILED")
        self.assertIn("مهلتِ انتظار", capped.error)
        cfg = ComputeSettings.get()
        cfg.max_wait_hours = 1
        cfg.save()
        self.assertEqual(SV.expire_overdue(force=True), 1)
        keep.refresh_from_db()
        self.assertEqual(keep.state, "FAILED")


class FakeClock:
    """ساعتِ جعلی تا آزمونِ wait() دقیقه‌ها طول نکشد: هر بار که خوانده می‌شود یک جهش جلو می‌رود."""

    def __init__(self, step=100.0):
        self.t = 0.0
        self.step = step

    def monotonic(self):
        self.t += self.step
        return self.t


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class PatientWaitTests(TestCase):
    def _patched(self, clock):
        return mock.patch.object(SV, "time", types.SimpleNamespace(monotonic=clock.monotonic, sleep=lambda s: None))

    def test_non_patient_wait_cancels_a_job_that_stays_queued(self):
        node()
        job = SV.enqueue_durable("photo.edit", {"w": 1}, timeout_s=10)
        with self._patched(FakeClock()):
            with self.assertRaises(SV.ComputeTimeout):
                SV.wait(job, timeout_s=10, poll=0)
        job.refresh_from_db()
        self.assertEqual(job.state, "CANCELLED")

    def test_patient_wait_survives_long_queueing_and_returns_when_done(self):
        n = node()
        job = SV.enqueue_durable("photo.edit", {"w": 2}, timeout_s=10)
        ticks = {"n": 0}

        def tick(j):
            ticks["n"] += 1
            if ticks["n"] == 200:                     # نوبتِ ۲۰۰ام: گره آمد و کار را تمام کرد
                n.last_seen = timezone.now()
                n.save()
                got = SV.claim(n)
                SV.finish(got, n, True)

        with self._patched(FakeClock()):
            done = SV.wait(job, timeout_s=10, poll=0, on_tick=tick, patient=True)
        self.assertEqual(done.state, "COMPLETED")
        self.assertGreaterEqual(ticks["n"], 200)

    def test_patient_wait_does_not_time_out_while_its_node_is_away(self):
        n = node(online=True)
        job = SV.enqueue_durable("photo.edit", {"w": 3}, timeout_s=10)
        SV.claim(n)
        ComputeNode.objects.filter(pk=n.pk).update(last_seen=OLD())
        job.refresh_from_db()
        ticks = {"n": 0}

        def tick(j):
            ticks["n"] += 1
            if ticks["n"] == 30:
                ComputeJob.objects.filter(pk=job.pk).update(state="QUEUED", node=None, claimed_at=None)
            if ticks["n"] == 60:
                ComputeNode.objects.filter(pk=n.pk).update(last_seen=timezone.now())
                nn = ComputeNode.objects.get(pk=n.pk)
                got = SV.claim(nn)
                SV.finish(got, nn, True)

        with self._patched(FakeClock()):
            done = SV.wait(job, timeout_s=10, poll=0, on_tick=tick, patient=True)
        self.assertEqual(done.state, "COMPLETED")

    def test_patient_wait_still_times_out_a_hung_job_on_a_live_node(self):
        n = node(online=True)
        job = SV.enqueue_durable("photo.edit", {"w": 4}, timeout_s=10)
        SV.claim(n)
        job.refresh_from_db()
        with self._patched(FakeClock()):
            with self.assertRaises(SV.ComputeTimeout):
                SV.wait(job, timeout_s=10, poll=0, patient=True)

    def test_park_after_frees_the_thread_and_cancels_the_compute_job(self):
        node()
        job = SV.enqueue_durable("comfy.graph", {"graph": {"w": 5}})
        with self._patched(FakeClock()):
            with self.assertRaises(SV.NodeWaiting) as ctx:
                SV.wait(job, timeout_s=900, poll=0, patient=True, park_after_s=120)
        self.assertEqual(ctx.exception.node_waiting, "comfyui")
        job.refresh_from_db()
        self.assertEqual(job.state, "CANCELLED")

    def test_requeue_resets_the_run_clock(self):
        n = node(online=True)
        job = SV.enqueue_durable("photo.edit", {"w": 6}, timeout_s=10)
        SV.claim(n)
        job.refresh_from_db()
        ticks = {"n": 0}

        def tick(j):
            ticks["n"] += 1
            if ticks["n"] == 4:           # پیش از پایانِ مهلتِ اجرا به صف برمی‌گردد
                ComputeJob.objects.filter(pk=job.pk).update(state="QUEUED", node=None, claimed_at=None)
            if ticks["n"] == 5:           # …و چند لحظه بعد دوباره گرفته می‌شود: ساعتِ اجرا باید از نو شروع شود
                SV.claim(n)
            if ticks["n"] == 6:
                got = ComputeJob.objects.get(pk=job.pk)
                SV.finish(got, n, True)

        with self._patched(FakeClock(step=3.0)):
            done = SV.wait(job, timeout_s=10, poll=0, on_tick=tick)
        self.assertEqual(done.state, "COMPLETED")


# ───────────────────────────── پارک (کارهای Celery)

class FakeTask:
    name = "apps.content.tasks.generate_image_task"

    class request:                                               # noqa: N801
        id = "task-1"
        args = (7, 8, "ENHANCED")
        kwargs = {"style": ""}
        delivery_info = {"routing_key": "gpu"}
        called_directly = False


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True, CELERY_TASK_ALWAYS_EAGER=False)
class ParkTests(TestCase):
    def setUp(self):
        from apps.jobs.models import Job
        from apps.stores.models import Store
        self.Job = Job
        self.user = get_user_model().objects.create_user("owner", "o@x.io", "pw")
        self.store = Store.objects.create(owner=self.user, name="shop")
        self.job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION, state=Job.State.PROCESSING)
        self.patch = mock.patch.object(park, "_current_task", return_value=FakeTask)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        gpu = mock.patch("apps.jobs.cancellation._release_gpu")        # آزمون به Ollama ِ واقعی دست نزند
        gpu.start()
        self.addCleanup(gpu.stop)

    def test_node_waiting_error_parks_instead_of_failing(self):
        node()
        self.job.mark_failed(SV.NodeWaiting("x", "comfyui"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "QUEUED")
        self.assertEqual(self.job.current_step_label, SV.NO_NODE_QUEUED_TEXT)
        self.assertEqual(self.job.error, "")
        ph = ComputeJob.objects.get(kind=park.PARK_KIND)
        self.assertEqual(ph.payload["task"], FakeTask.name)
        self.assertEqual(ph.payload["args"], [7, 8, "ENHANCED"])
        self.assertEqual(ph.payload["ref"], {"model": "jobs.Job", "id": self.job.pk})
        row = QV.listing("waiting")["jobs"][0]
        self.assertTrue(row["parked"])
        self.assertEqual(row["wait_reason"], "no_node")

    def test_parked_job_is_not_reaped_as_dead(self):
        from apps.jobs import staleness
        node()
        self.job.mark_failed(SV.NodeWaiting("x", "comfyui"))
        self.Job.objects.filter(pk=self.job.pk).update(created_at=timezone.now() - timedelta(days=3))
        self.assertEqual(staleness.reap(), 0)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "QUEUED")

    def test_plain_errors_and_unknown_nodes_and_eager_mode_still_fail(self):
        node()
        self.job.mark_failed(RuntimeError("real error"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "FAILED")
        self.assertFalse(ComputeJob.objects.filter(kind=park.PARK_KIND).exists())
        ComputeNode.objects.all().delete()                       # هیچ سروری ثبت نیست: منتظرِ هیچ نمی‌مانیم
        self.job.state = "PROCESSING"
        self.job.save()
        self.job.mark_failed(SV.NodeWaiting("x", "comfyui"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "FAILED")
        node()
        self.job.state = "PROCESSING"
        self.job.save()
        with override_settings(CELERY_TASK_ALWAYS_EAGER=True):
            self.job.mark_failed(SV.NodeWaiting("x", "comfyui"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "FAILED")

    def test_wake_dispatches_the_same_task_when_the_node_comes_back(self):
        n = node()
        self.job.mark_failed(SV.NodeWaiting("x", "comfyui"))
        with mock.patch.object(park, "_dispatch", return_value=True) as dispatch:
            self.assertEqual(park.wake_parked(), 0)
            dispatch.assert_not_called()
            n.last_seen = timezone.now()
            n.save()
            self.assertEqual(park.wake_parked(), 1)
            dispatch.assert_called_once()
            self.assertEqual(dispatch.call_args[0][1]["args"], [7, 8, "ENHANCED"])
        self.assertFalse(ComputeJob.objects.filter(kind=park.PARK_KIND).exists())
        self.job.refresh_from_db()
        self.assertIn("node_wait", self.job.context)

    def test_cancelling_the_waiting_entry_cancels_the_users_job(self):
        node()
        self.job.mark_failed(SV.NodeWaiting("x", "comfyui"))
        ph = ComputeJob.objects.get(kind=park.PARK_KIND)
        SV.cancel(ph)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "CANCELLED")

    def test_user_cancelling_their_job_stops_the_wakeup(self):
        n = node()
        self.job.mark_failed(SV.NodeWaiting("x", "comfyui"))
        self.Job.objects.filter(pk=self.job.pk).update(cancel_requested=True)
        n.last_seen = timezone.now()
        n.save()
        with mock.patch.object(park, "_dispatch", return_value=True) as dispatch:
            park.wake_parked()
            dispatch.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "CANCELLED")

    def test_gate_parks_before_any_work_and_lets_live_nodes_through(self):
        n = node()
        self.assertTrue(park.gate(self.job, "comfyui"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "QUEUED")
        n.last_seen = timezone.now()
        n.save()
        self.assertFalse(park.gate(self.job, "comfyui"))

    def test_all_providers_failed_carries_the_waiting_flag_only_for_an_offline_local_route(self):
        from services.ai import priority, routing
        router = routing._Router("t")
        failures = {routing.LOCAL: priority.Failure("offline", "سرورِ پردازش خاموش است.", provider=routing.LOCAL),
                    routing.METIS: priority.Failure("no_credit", "اعتبار تمام شد", provider=routing.METIS)}
        node()
        exc = router._all_failed([routing.LOCAL, routing.METIS], failures)
        self.assertEqual(getattr(exc, "node_waiting", ""), "ollama")
        failures[routing.LOCAL] = priority.Failure("no_model", "مدل نصب نیست", provider=routing.LOCAL)
        self.assertFalse(getattr(router._all_failed([routing.LOCAL, routing.METIS], failures), "node_waiting", ""))
        ComputeNode.objects.all().delete()
        failures[routing.LOCAL] = priority.Failure("offline", "خاموش", provider=routing.LOCAL)
        self.assertFalse(getattr(router._all_failed([routing.LOCAL, routing.METIS], failures), "node_waiting", ""))


# ───────────────────────────── API ِ صفِ پردازش

@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class QueueApiTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user("boss", "b@x.io", "pw", is_staff=True)
        self.user = get_user_model().objects.create_user("pleb", "p@x.io", "pw")
        self.c = APIClient()
        self.c.force_authenticate(self.staff)

    def test_only_staff_can_see_or_touch_the_queue(self):
        plain = APIClient()
        plain.force_authenticate(self.user)
        for url in ("/api/v1/compute/queue/", "/api/v1/compute/queue/summary/"):
            self.assertEqual(plain.get(url).status_code, 403)
            self.assertIn(APIClient().get(url).status_code, (401, 403))
        job = SV.enqueue("echo", {}, require_online=False)
        self.assertEqual(plain.post(f"/api/v1/compute/queue/{job.uid}/cancel/").status_code, 403)

    def test_listing_groups_positions_and_counts(self):
        n = node()
        a = SV.enqueue_durable("photo.edit", {"i": 1})
        b = SV.enqueue_durable("photo.edit", {"i": 2})
        v = SV.enqueue_durable("voice.tts", {"i": 3})
        r = self.c.get("/api/v1/compute/queue/?state=waiting")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["counts"]["waiting"], 3)
        rows = {row["uid"]: row for row in r.data["jobs"]}
        self.assertEqual(rows[str(a.uid)]["position"], 1)
        self.assertEqual(rows[str(b.uid)]["position"], 2)
        self.assertEqual(rows[str(v.uid)]["position"], 1, "صفِ هر توانایی جداست")
        n.last_seen = timezone.now()
        n.save()
        rows = {row["uid"]: row for row in self.c.get("/api/v1/compute/queue/?state=waiting").data["jobs"]}
        self.assertEqual(rows[str(b.uid)]["status_text"], "در صف — نفرِ ۲ام")
        self.assertEqual(rows[str(a.uid)]["status_text"], "در صف — نوبتِ بعدی")
        got = SV.claim(n)
        r = self.c.get("/api/v1/compute/queue/?state=running")
        self.assertEqual([j["uid"] for j in r.data["jobs"]], [str(got.uid)])
        self.assertIn("در حال پردازش روی «gpu-1»", r.data["jobs"][0]["status_text"])
        r = self.c.get("/api/v1/compute/queue/?kind=voice")
        self.assertEqual({j["kind"] for j in r.data["jobs"]}, {"voice.tts"})
        self.assertEqual(self.c.get("/api/v1/compute/queue/?q=photo").data["total"], 2)

    def test_summary_for_the_header(self):
        node()
        SV.enqueue_durable("photo.edit", {"s": 1})
        d = self.c.get("/api/v1/compute/queue/summary/").data
        self.assertEqual((d["waiting"], d["running"], d["nodes_total"], d["nodes_online"]), (1, 0, 1, 0))
        self.assertEqual(d["text"], "۱ کار منتظرِ سرورِ پردازش")

    def test_cancel_and_retry_from_the_panel(self):
        n = node(online=True)
        job = SV.enqueue_durable("comfy.graph", {"graph": {"a": 1}})
        r = self.c.post(f"/api/v1/compute/queue/{job.uid}/cancel/")
        self.assertEqual(r.data["state"], "CANCELLED")
        self.assertFalse(r.data["can_retry"], "کارِ تولیدِ تصویر را فقط از صفحهٔ خودش می‌شود دوباره زد")
        self.assertEqual(self.c.post(f"/api/v1/compute/queue/{job.uid}/retry/").status_code, 400)
        pull = SV.enqueue_durable("ollama.pull", {"model": "gemma3:12b"}, node=n.name, dedupe=False)
        SV.cancel(pull)
        r = self.c.post(f"/api/v1/compute/queue/{pull.uid}/retry/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["state"], "QUEUED")
        pull.refresh_from_db()
        self.assertEqual((pull.attempts, pull.lost_count), (0, 0))

    def test_cancel_all_waiting(self):
        node()
        SV.enqueue_durable("photo.edit", {"z": 1})
        SV.enqueue_durable("voice.tts", {"z": 2})
        r = self.c.post("/api/v1/compute/queue/cancel-waiting/", {"kind": "photo"}, format="json")
        self.assertEqual(r.data["cancelled"], 1)
        self.assertEqual(ComputeJob.objects.filter(state="QUEUED").count(), 1)

    def test_pinned_offline_and_model_reasons(self):
        node("gpu-9")
        job = SV.enqueue_durable("comfy.graph", {"graph": {"p": 1}}, node="gpu-9")
        row = QV.listing("waiting")["jobs"][0]
        self.assertEqual(row["wait_reason"], "pinned_offline")
        self.assertIn("«gpu-9»", row["status_text"])
        ComputeNode.objects.filter(name="gpu-9").update(enabled=False)
        self.assertEqual(QV.listing("waiting")["jobs"][0]["wait_reason"], "pinned_gone")
        job.delete()
        ComputeNode.objects.filter(name="gpu-9").update(enabled=True, last_seen=timezone.now(),
                                                         capabilities={"voice": True, "audio": {"moss": False}})
        SV.enqueue_durable("voice.tts", {"engine": "moss-fa", "text": "hi"})
        self.assertEqual(QV.listing("waiting")["jobs"][0]["wait_reason"], "model")

    def test_settings_roundtrip_and_validation(self):
        r = self.c.post("/api/v1/compute/settings/", {"max_wait_hours": 48, "download_mode": "window",
                                                      "download_window": "01:30-06:00", "retention_days": 14},
                        format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["max_wait_hours"], r.data["download_mode"], r.data["download_window"]), (48, "window", "01:30-06:00"))
        for bad in ({"download_window": "7-8"}, {"download_mode": "later"}, {"max_wait_hours": "x"}, {"retention_days": 0}):
            self.assertEqual(self.c.post("/api/v1/compute/settings/", bad, format="json").status_code, 400)
        self.assertEqual(ComputeSettings.get().max_wait_hours, 48)

    def test_panel_test_submit_waits_instead_of_failing(self):
        node()
        r = self.c.post("/api/v1/compute/submit/", {"kind": "photo.edit", "payload": "{}"}, format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["state"], "QUEUED")
        ComputeNode.objects.all().delete()
        r = self.c.post("/api/v1/compute/submit/", {"kind": "photo.edit", "payload": "{}", "dedupe": "0"}, format="multipart")
        self.assertEqual(r.status_code, 503)


# ───────────────────────────── صدا و کلونِ صدا: بی‌سرور هم در صف می‌مانند

@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class VoiceQueueTests(TestCase):
    def test_audio_studio_job_waits_for_the_node_instead_of_failing(self):
        from services.audio import node_audio
        node(audio={"moss": True, "sfx": True, "music": True})
        with self.assertRaises(node_audio.NodeAudioError) as ctx:         # مسیرِ بی‌صبرِ قدیمی (روایتِ ویدیو با زنجیرهٔ جایگزین)
            node_audio.pick_node("moss", purpose="speech")
        self.assertEqual(ctx.exception.code, "offline")
        self.assertEqual(node_audio.pick_node("moss", purpose="speech", allow_offline=True), "")
        job = node_audio.enqueue("moss", "voice.tts", {"text": "سلام", "engine": "moss-fa"}, purpose="speech",
                                 durable=True)
        self.assertEqual((job.state, job.node_wanted, job.message), ("QUEUED", "", SV.NO_NODE_QUEUED_TEXT))
        n = ComputeNode.objects.get()
        n.last_seen = timezone.now()
        n.save()
        self.assertEqual(SV.claim(n).pk, job.pk)

    def test_audio_job_with_the_engine_switched_off_is_still_refused(self):
        from services.audio import node_audio
        node(audio={"moss": True}, )
        ComputeNode.objects.update(desired={"audio": {"speech": False}})
        with self.assertRaises(node_audio.NodeAudioError) as ctx:
            node_audio.pick_node("moss", purpose="speech", allow_offline=True)
        self.assertEqual(ctx.exception.code, "offline", "هیچ‌کس روشن نیست و خاموشیِ پنل فقط برای گرهٔ آنلاین پیام می‌دهد")
        ComputeNode.objects.all().delete()
        with self.assertRaises(node_audio.NodeAudioError):
            node_audio.pick_node("moss", purpose="speech", allow_offline=True)

    def test_voice_clone_waiting_flag_and_durable_pick(self):
        from services.audio import voice_clone as vc
        node(voice=True)
        with self.assertRaises(vc.NodeOffline) as ctx:
            vc.pick_node(None)
        self.assertEqual(getattr(ctx.exception, "node_waiting", ""), "voice")
        self.assertEqual(vc.pick_node(None, allow_offline=True), "gpu-1")
        ComputeNode.objects.all().delete()
        with self.assertRaises(vc.NodeOffline) as ctx2:
            vc.pick_node(None, allow_offline=True)
        self.assertFalse(getattr(ctx2.exception, "node_waiting", ""), "سرورِ ثبت‌شده‌ای نیست؛ منتظرِ هیچ نمی‌مانیم")
