"""«پردازشِ دوباره» برای کارهای فروشگاه (apps.jobs.retry)."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import retry, staleness
from .models import Job


def _fake_task(name, fn):
    return SimpleNamespace(name=name, run=fn, apply_async=mock.Mock(return_value=SimpleNamespace(id="tid-1")))


def _captions(job_id, product_id, platforms, tone="", objective="", image_id=None, video_script_id=None):
    return None


def _embed(product_id):
    return None


class RecordTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("retry-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ آزمون")
        self.job = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION, context={"product_id": 7})

    def tearDown(self):
        retry.on_task_postrun()

    def test_prerun_records_task_and_current_job(self):
        task = _fake_task("apps.content.tasks.generate_captions_task", _captions)
        retry.on_task_prerun(task=task, args=[self.job.id, 7, ["INSTAGRAM"], "گرم", "فروش"], kwargs={})
        self.assertEqual(retry.current_job_id(), self.job.id)
        self.job.refresh_from_db()
        rec = self.job.context["_task"]
        self.assertEqual(rec["name"], "apps.content.tasks.generate_captions_task")
        self.assertEqual(rec["args"], [self.job.id, 7, ["INSTAGRAM"], "گرم", "فروش"])
        self.assertEqual(self.job.context["product_id"], 7)          # بقیهٔ context دست نخورد
        retry.on_task_postrun()
        self.assertIsNone(retry.current_job_id())

    def test_task_without_job_id_first_is_ignored(self):
        task = _fake_task("apps.ai.tasks.embed_product_task", _embed)
        retry.on_task_prerun(task=task, args=[self.job.id], kwargs={})   # همان عدد، ولی product_id است
        self.assertIsNone(retry.current_job_id())
        self.job.refresh_from_db()
        self.assertNotIn("_task", self.job.context)


class RetryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("retry-owner2", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ آزمون")
        self.task = _fake_task("apps.content.tasks.generate_captions_task", _captions)
        p1 = mock.patch.object(retry, "_resolve", return_value=self.task)
        p2 = mock.patch.object(retry, "_queue_problem", return_value="")
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def _failed(self, **ctx):
        job = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION, state=Job.State.FAILED,
                                 error="لوکال: در مهلتِ مقرر جواب نداد", context=ctx)
        Job.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=2))
        job.refresh_from_db()
        return job

    def test_recorded_task_is_sent_again_on_the_same_row(self):
        job = self._failed(product_id=7, _task={"name": "apps.content.tasks.generate_captions_task",
                                                 "args": [0, 7, ["INSTAGRAM"], "گرم"], "kwargs": {}})
        job.context["_task"]["args"][0] = job.id
        Job.objects.filter(pk=job.pk).update(context=job.context)
        job.refresh_from_db()
        self.assertTrue(retry.can_retry(job))
        out = retry.retry(job)
        self.assertEqual(out.pk, job.pk)
        self.assertEqual(out.state, Job.State.QUEUED)
        self.assertEqual(out.error, "")
        self.assertEqual(out.retry_count, 1)
        self.assertEqual(out.celery_task_id, "tid-1")
        self.assertEqual(out.context["_retries"][0]["from"], "FAILED")
        self.assertIn("در مهلت", out.context["_retries"][0]["error"])
        self.assertIn("_first_created_at", out.context)
        self.task.apply_async.assert_called_once_with(args=[job.id, 7, ["INSTAGRAM"], "گرم"], kwargs={})
        # کارِ دیروزی که دوباره در صف رفت، نباید بلافاصله «مرده در صف» شمرده شود
        staleness.reap(Job.objects.filter(pk=job.pk))
        out.refresh_from_db()
        self.assertEqual(out.state, Job.State.QUEUED)

    def test_builder_for_old_failed_jobs_without_a_record(self):
        job = self._failed(product_id=7, platforms=["INSTAGRAM"], image_id=3, video_script_id=None)
        name, args, kwargs = retry.plan_for(job)
        self.assertEqual(name, "apps.content.tasks.generate_captions_task")
        self.assertEqual(args, [job.id, 7, ["INSTAGRAM"], "", "", 3, None])
        retry.retry(job)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.QUEUED)

    def test_park_placeholder_gives_the_exact_arguments(self):
        from apps.compute.models import ComputeJob
        from apps.compute.park import PARK_KIND

        job = self._failed(product_id=7)
        ComputeJob.objects.create(kind=PARK_KIND, state="CANCELLED", payload={
            "capability": "ollama", "task": "apps.content.tasks.generate_captions_task",
            "args": [job.id, 7, ["INSTAGRAM"], "صمیمی", "معرفی"], "kwargs": {}, "ref": {"model": "jobs.Job", "id": job.id}})
        self.assertEqual(retry.plan_for(job)[1], [job.id, 7, ["INSTAGRAM"], "صمیمی", "معرفی"])

    def test_completed_or_unknown_jobs_are_refused(self):
        done = Job.objects.create(store=self.store, type=Job.Type.CAPTION_GENERATION, state=Job.State.COMPLETED,
                                  context={"product_id": 7})
        self.assertFalse(retry.can_retry(done))
        with self.assertRaises(retry.RetryError) as cm:
            retry.retry(done)
        self.assertEqual(cm.exception.status, 409)
        nothing = self._failed()                       # بی product_id و بی ثبت
        self.assertFalse(retry.can_retry(nothing))
        with self.assertRaises(retry.RetryError):
            retry.retry(nothing)
        self.task.apply_async.assert_not_called()

    def test_queue_down_leaves_the_job_failed(self):
        job = self._failed(product_id=7)
        with mock.patch.object(retry, "_queue_problem", return_value="صف خاموش است"):
            with self.assertRaises(retry.RetryError) as cm:
                retry.retry(job)
        self.assertEqual(cm.exception.status, 503)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertEqual(job.retry_count, 0)

    def test_dispatch_error_marks_failed_again(self):
        job = self._failed(product_id=7)
        self.task.apply_async.side_effect = RuntimeError("broker gone")
        with self.assertRaises(retry.RetryError):
            retry.retry(job)
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertIn("اجرای دوباره", job.error)

    def test_retry_many_counts(self):
        a = self._failed(product_id=7)
        b = self._failed()                               # ورودی ندارد
        out = retry.retry_many(Job.objects.filter(pk__in=[a.pk, b.pk]))
        self.assertEqual(out["retried"], 1)
        self.assertEqual(out["skipped"], 1)

    def test_api_retry_owner_only(self):
        job = self._failed(product_id=7)
        c = APIClient()
        c.force_authenticate(self.owner)
        listed = c.get(f"/api/v1/jobs/{job.id}/")
        self.assertTrue(listed.data["can_retry"])
        r = c.post(f"/api/v1/jobs/{job.id}/retry/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["state"], "QUEUED")
        self.assertIn("دوباره", r.data["notice"])
        again = c.post(f"/api/v1/jobs/{job.id}/retry/")       # دیگر ناموفق نیست
        self.assertEqual(again.status_code, 409)
        stranger = User.objects.create_user("stranger", password="x")
        c2 = APIClient()
        c2.force_authenticate(stranger)
        self.assertEqual(c2.post(f"/api/v1/jobs/{job.id}/retry/").status_code, 404)
