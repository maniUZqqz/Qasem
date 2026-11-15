# -*- coding: utf-8 -*-
"""نگه‌داریِ فایل‌های کارها (retention.py) + سقفِ آپلودِ تکه‌ای (transfer.py): ورودی/بسته/خروجیِ کارِ تمام‌شده پاک می‌شود، کارِ در جریان هرگز،
پوشهٔ یتیم پاک می‌شود، مقدارِ آزادشده روی صفحهٔ گزارش می‌آید، و فایلِ بی‌جا (دیسکِ پر / بیش از سقف) رد می‌شود."""
import json
import os
import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import queue as QV
from . import retention
from . import services as SV
from . import transfer
from .models import ComputeJob, ComputeNode

S = ComputeJob.State


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-retention-test-"))
        self.ctx = override_settings(NM_DATA_DIR=self.tmp, IS_TEST=True)
        self.ctx.enable()
        self.node = ComputeNode.objects.create(name="gpu-r", token="r-tok", last_seen=timezone.now(),
                                               capabilities={"agent": "2.11", "ffmpeg": True, "edit": {"render": True}, "photo": True, "kinds": ["echo"]})

    def tearDown(self):
        self.ctx.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, state=S.COMPLETED, age_h=3.0, inputs=True, outputs=True, kind="photo.edit", **kw):
        """کارِ تمام‌شده با پوشهٔ واقعی (ورودی، بسته، خروجی) که age_h ساعت پیش تمام شد."""
        job = SV.enqueue(kind, {"n": kw.pop("n", time.time_ns() % 10**9)}, dedupe=False, require_online=False, **kw)
        root = SV.job_root(job)
        if inputs:
            (root / "inputs" / "in.png").write_bytes(b"i" * 1000)
            job.inputs = {"in.png": "inputs/in.png"}
        (root / "package.zip").write_bytes(b"z" * 1500)
        if outputs:
            (root / "outputs" / "out.png").write_bytes(b"o" * 3000)
        when = timezone.now() - timedelta(hours=age_h)
        result = {"outputs": [{"name": "out.png", "path": "x", "size": 3000, "media": "image"}], "meta": {}} if outputs else {}
        ComputeJob.objects.filter(pk=job.pk).update(state=state, finished_at=when, node=self.node, result=result, inputs=job.inputs or {})
        job.refresh_from_db()
        return job

    def root(self, job):
        return self.tmp / job.dir_rel


class RetentionTests(_Base):
    def test_a_finished_job_loses_its_zip_after_the_grace_hour_and_its_inputs_after_two_days_but_keeps_the_outputs(self):
        job = self.make(age_h=3)
        freed = retention.clean_job(job, timezone.now())
        root = self.root(job)
        self.assertEqual(freed, 1500, "only the zip (it held every input a second time)")
        self.assertFalse((root / "package.zip").exists())
        self.assertTrue((root / "inputs" / "in.png").is_file(), "a page that comes back tomorrow may still read the input (the fill mask)")
        job2 = self.make(age_h=50, n=2)
        freed = retention.clean_job(job2, timezone.now())
        self.assertEqual(freed, 1000 + 1500)
        self.assertFalse((self.root(job2) / "inputs").exists())
        self.assertTrue((self.root(job2) / "outputs" / "out.png").is_file(), "the result stays for a week")
        job2.refresh_from_db()
        self.assertTrue(job2.result["retention"]["inputs_removed"])
        self.assertEqual(len(job2.result["outputs"]), 1)

    def test_a_result_nobody_has_picked_up_yet_is_kept(self):
        from apps.photoedit.models import PhotoAsset, PhotoEdit
        from apps.stores.models import Store

        user = get_user_model().objects.create_user("owner-pend", password="x")
        store = Store.objects.create(owner=user, name="shop-pend")
        job = self.make(age_h=5 * 24, origin="photoedit", store=store, n=9)
        asset = PhotoAsset.objects.create(store=store, created_by=user, title="a", original="-")
        edit = PhotoEdit.objects.create(asset=asset, compute_job=str(job.uid), state=PhotoEdit.State.NODE)
        retention.clean_job(job, timezone.now())
        self.assertTrue((self.root(job) / "inputs" / "in.png").is_file(), "the edit page still waits for this result")
        self.assertTrue((self.root(job) / "outputs" / "out.png").is_file())
        self.assertFalse((self.root(job) / "package.zip").exists(), "the node zip is never needed again")
        PhotoEdit.objects.filter(pk=edit.pk).update(state=PhotoEdit.State.READY)
        retention.clean_job(job, timezone.now())
        self.assertFalse((self.root(job) / "inputs").exists(), "picked up and older than two days: the inputs go")
        self.assertTrue((self.root(job) / "outputs" / "out.png").is_file(), "the outputs wait for their own week")
        ComputeJob.objects.filter(pk=job.pk).update(finished_at=timezone.now() - timedelta(days=9))
        job.refresh_from_db()
        retention.clean_job(job, timezone.now())
        self.assertFalse(self.root(job).exists(), "picked up and more than a week old: gone")
        stuck = self.make(age_h=40 * 24, origin="photoedit", store=store, n=19)
        PhotoEdit.objects.create(asset=asset, number=2, compute_job=str(stuck.uid), state=PhotoEdit.State.NODE)
        retention.clean_job(stuck, timezone.now())
        self.assertFalse(self.root(stuck).exists(), "a page that never picked it up cannot hold the disk for ever (14 days)")

    def test_a_pending_check_that_cannot_be_answered_keeps_the_files(self):
        job = self.make(age_h=30 * 24, origin="regen", n=10)
        with mock.patch("apps.regen.models.RegenVersion.objects") as objs:
            objs.filter.side_effect = RuntimeError("db")
            self.assertTrue(retention.consumer_pending(job))
        self.assertFalse(retention.consumer_pending(self.make(age_h=1, origin="panel", n=11)))

    def test_nothing_is_touched_inside_the_grace_hour(self):
        job = self.make(age_h=0.3)
        self.assertEqual(retention.clean_job(job, timezone.now()), 0)
        self.assertTrue((self.root(job) / "package.zip").is_file())
        self.assertTrue((self.root(job) / "inputs" / "in.png").is_file())

    def test_a_running_or_waiting_job_is_untouched(self):
        for state in (S.RUNNING, S.CLAIMED, S.QUEUED):
            job = self.make(state=state, age_h=500)
            ComputeJob.objects.filter(pk=job.pk).update(finished_at=None if state != S.RUNNING else timezone.now() - timedelta(days=40))
            job.refresh_from_db()
            self.assertEqual(retention.clean_job(job, timezone.now()), 0, state)
            self.assertTrue((self.root(job) / "inputs" / "in.png").is_file(), state)
            self.assertTrue((self.root(job) / "outputs" / "out.png").is_file(), state)
        out = retention.run(timezone.now())
        self.assertEqual(out["jobs"], 0, "run() looks at final jobs only")

    def test_outputs_go_after_seven_days_for_a_completed_job(self):
        young = self.make(age_h=6 * 24)
        old = self.make(age_h=8 * 24)
        retention.run(timezone.now())
        self.assertTrue((self.root(young) / "outputs" / "out.png").is_file())
        self.assertFalse(self.root(old).exists(), "the whole folder is gone")
        old.refresh_from_db()
        note = old.result["retention"]
        self.assertTrue(note["outputs_removed"])
        self.assertEqual(note["outputs_gone"], ["out.png"])
        self.assertEqual(old.result["outputs"], [], "no dead link is shown")
        self.assertIn("پاک شد", QV.files_removed_text(old))

    def test_a_failed_job_keeps_its_inputs_for_the_retry_for_two_weeks(self):
        job = self.make(state=S.FAILED, age_h=10 * 24, outputs=False)
        retention.clean_job(job, timezone.now())
        self.assertTrue((self.root(job) / "inputs" / "in.png").is_file(), "'process again' needs them")
        self.assertFalse((self.root(job) / "package.zip").exists(), "the zip is rebuilt from the inputs when needed")
        job2 = self.make(state=S.FAILED, age_h=15 * 24, outputs=False)
        retention.clean_job(job2, timezone.now())
        self.assertFalse(self.root(job2).exists())

    def test_a_cancelled_job_goes_after_three_days(self):
        job = self.make(state=S.CANCELLED, age_h=4 * 24, outputs=False)
        retention.clean_job(job, timezone.now())
        self.assertFalse(self.root(job).exists())

    def test_the_result_already_copied_to_the_store_is_removed_early(self):
        from apps.jobs.models import Job
        from apps.stores.models import Store

        user = get_user_model().objects.create_user("owner-ret", password="x")
        store = Store.objects.create(owner=user, name="shop-ret")
        owner = Job.objects.create(store=store, type=Job.Type.IMAGE_GENERATION, state=Job.State.COMPLETED)
        taken = self.make(age_h=7, store=store)
        ComputeJob.objects.filter(pk=taken.pk).update(job_ref=owner.pk)
        taken.refresh_from_db()
        young = self.make(age_h=2, store=store, n=2)
        ComputeJob.objects.filter(pk=young.pk).update(job_ref=owner.pk)
        young.refresh_from_db()
        running_owner = Job.objects.create(store=store, type=owner.type, state=Job.State.PROCESSING)
        waiting = self.make(age_h=30, store=store, n=3)
        ComputeJob.objects.filter(pk=waiting.pk).update(job_ref=running_owner.pk)
        waiting.refresh_from_db()
        retention.run(timezone.now())
        self.assertFalse(self.root(taken).exists(), "the store job is done and 6+ hours passed: the copy is in the store media (inputs too)")
        taken.refresh_from_db()
        self.assertEqual(taken.result["retention"]["why"], "taken")
        self.assertIn("فروشگاه", QV.files_removed_text(taken))
        self.assertTrue((self.root(young) / "outputs" / "out.png").is_file(), "not yet: the page may still be taking it")
        self.assertTrue((self.root(waiting) / "outputs" / "out.png").is_file(), "the owner job is still running: keep")

    def test_a_job_without_an_owner_page_is_not_treated_as_copied(self):
        job = self.make(age_h=30)
        retention.run(timezone.now())
        self.assertTrue((self.root(job) / "outputs" / "out.png").is_file(), "only the 7-day rule applies")

    def test_folders_without_a_job_row_are_removed_after_a_day(self):
        jobs_dir = retention.jobs_dir()
        jobs_dir.mkdir(parents=True, exist_ok=True)
        orphan = jobs_dir / "11111111-1111-1111-1111-111111111111"
        fresh = jobs_dir / "22222222-2222-2222-2222-222222222222"
        for d in (orphan, fresh):
            (d / "inputs").mkdir(parents=True)
            (d / "inputs" / "x.bin").write_bytes(b"x" * 700)
        old = time.time() - 3 * 86400
        os.utime(orphan, (old, old))
        live = self.make(age_h=0.1)
        out = retention.run(timezone.now())
        self.assertFalse(orphan.exists())
        self.assertTrue(fresh.exists(), "newer than a day: a job may be being created right now")
        self.assertTrue(self.root(live).exists(), "a folder with a row is never an orphan")
        self.assertEqual(out["orphans"], 1)
        self.assertGreaterEqual(out["freed"], 700)

    def test_very_old_rows_go_but_failures_stay_for_the_report(self):
        done = self.make(age_h=100 * 24)
        failed = self.make(state=S.FAILED, age_h=100 * 24, outputs=False)
        cancelled = self.make(state=S.CANCELLED, age_h=100 * 24, outputs=False)
        recent = self.make(age_h=10 * 24)
        very_old_failed = self.make(state=S.FAILED, age_h=400 * 24, outputs=False)
        out = retention.run(timezone.now())
        left = set(ComputeJob.objects.values_list("pk", flat=True))
        self.assertNotIn(done.pk, left)
        self.assertNotIn(cancelled.pk, left)
        self.assertIn(failed.pk, left, "a failure stays: the report lists errors")
        self.assertIn(recent.pk, left)
        self.assertNotIn(very_old_failed.pk, left, "after a year even failures go")
        self.assertEqual(out["rows"], 3)

    def test_the_row_age_never_undercuts_the_stats_retention_setting(self):
        from .models import ComputeSettings

        ComputeSettings.objects.update_or_create(pk=1, defaults={"retention_days": 200})
        job = self.make(age_h=150 * 24)
        retention.run(timezone.now())
        self.assertTrue(ComputeJob.objects.filter(pk=job.pk).exists())

    def test_each_run_is_bounded(self):
        for i in range(retention.MAX_JOBS_PER_RUN + 15):
            self.make(age_h=3, n=i)
        out = retention.run(timezone.now())
        self.assertEqual(out["jobs"], retention.MAX_JOBS_PER_RUN)
        out2 = retention.run(timezone.now())
        self.assertEqual(out2["jobs"], 15, "the next minute continues where it stopped")

    def test_freed_space_is_summed_in_a_file_and_reported(self):
        self.make(age_h=3)
        self.make(age_h=3, n=5)
        retention.run(timezone.now())
        st = retention.load_stats()
        self.assertEqual(st["freed_total"], 2 * 1500, "the node zip of each job")
        self.assertEqual(st["jobs_total"], 2)
        self.assertGreater(st["size_bytes"], 0)
        retention.run(timezone.now())
        self.assertEqual(retention.load_stats()["freed_total"], 2 * 1500, "an empty run adds nothing")
        rep = retention.report()
        self.assertEqual(rep["jobs_cleaned"], 2)
        self.assertEqual(rep["freed_mb"], round(3000 / (1 << 20), 3))
        self.assertEqual(rep["rules"]["output_days"], 7)

    def test_maintain_never_raises_and_is_rate_limited(self):
        with mock.patch.object(retention, "run", side_effect=RuntimeError("disk")):
            self.assertEqual(retention.maintain(force=True), {"error": True})
        with mock.patch.object(retention, "run", return_value={"jobs": 0}) as r:
            retention.maintain(force=True)
            self.assertEqual(r.call_count, 1)

    def test_the_maintenance_task_runs_it(self):
        from .tasks import maintenance

        with mock.patch.object(retention, "maintain", return_value={"jobs": 0}) as m:
            out = maintenance()
        self.assertTrue(m.called)
        self.assertIn("retention", out)

    def test_the_report_api_shows_the_freed_space(self):
        self.make(age_h=3)
        retention.run(timezone.now())
        staff = get_user_model().objects.create_user("staff-ret", password="x", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        body = c.get("/api/v1/compute/report/").json()
        self.assertEqual(body["storage"]["jobs_cleaned"], 1)
        self.assertGreater(body["storage"]["freed_mb"], 0)

    def test_a_job_whose_inputs_are_gone_is_not_retried_in_place(self):
        job = self.make(state=S.FAILED, age_h=15 * 24, outputs=False, origin="panel")
        retention.clean_job(job, timezone.now())
        job.refresh_from_db()
        self.assertTrue(QV.inputs_gone(job))
        self.assertEqual(QV.retry_mode(job), "")
        self.assertIn("پاک شده", QV.retry_hint(job, ""))
        with self.assertRaises(ValueError):
            QV.retry_ex(job)
        plain = self.make(state=S.FAILED, age_h=2, outputs=False, origin="panel", n=77)
        self.assertEqual(QV.retry_mode(plain), "requeue", "still retryable while the inputs exist")

    def test_dedupe_does_not_reuse_a_job_whose_outputs_are_gone(self):
        job = self.make(age_h=8 * 24, kind="photo.edit")
        payload = job.payload
        ComputeJob.objects.filter(pk=job.pk).update(request_hash=SV.request_hash("photo.edit", payload, None))
        retention.run(timezone.now())
        again = SV.enqueue("photo.edit", payload, None, require_online=False)
        self.assertNotEqual(again.pk, job.pk)


class UploadGuardTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-upload-guard-"))
        self.ctx = override_settings(NM_DATA_DIR=self.tmp, IS_TEST=True)
        self.ctx.enable()
        self.node = ComputeNode.objects.create(name="gpu-u", token="u-tok", capabilities={"ffmpeg": True, "edit": {"render": True}}, last_seen=timezone.now())
        self.job = SV.enqueue("edit.render", {"graph": "x"}, dedupe=False)
        self.assertEqual(SV.claim(self.node).pk, self.job.pk)
        self.c = APIClient()
        self.base = f"/api/v1/compute/jobs/{self.job.uid}"
        self.free = mock.patch.object(transfer, "free_bytes", return_value=50 << 30)
        self.free.start()

    def tearDown(self):
        self.free.stop()
        self.ctx.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name, body, total, offset=0):
        return self.c.generic("PUT", f"{self.base}/chunks/{name}/?offset={offset}&total={total}", body,
                              content_type="application/octet-stream", HTTP_AUTHORIZATION="Node u-tok")

    def test_a_normal_upload_still_works(self):
        r = self.put("render.mp4", b"abc", 3)
        self.assertEqual((r.status_code, r.json()["complete"]), (200, True))

    def test_a_full_disk_refuses_the_first_chunk_with_507_and_fails_the_job_in_persian(self):
        with mock.patch.object(transfer, "free_bytes", return_value=(3 << 30) + (100 << 20)):
            r = self.put("render.mp4", b"x" * 10, 200 << 20)
        self.assertEqual(r.status_code, 507)
        self.assertIn("جای خالیِ دیسکِ سایت کم است", r.json()["error"])
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "FAILED")
        self.assertIn("جای خالیِ دیسکِ سایت کم است", self.job.error)
        self.assertFalse((self.tmp / self.job.dir_rel / "outputs" / "render.mp4.part").exists(), "nothing was written")

    def test_enough_space_beyond_the_reserve_is_accepted(self):
        with mock.patch.object(transfer, "free_bytes", return_value=(3 << 30) + (100 << 20)):
            r = self.put("render.mp4", b"x" * 10, 50 << 20)
        self.assertEqual(r.status_code, 200)

    def test_the_check_is_only_on_the_first_chunk(self):
        self.assertEqual(self.put("render.mp4", b"ab", 4).status_code, 200)
        with mock.patch.object(transfer, "free_bytes", return_value=0):
            r = self.put("render.mp4", b"cd", 4, offset=2)
        self.assertEqual((r.status_code, r.json()["complete"]), (200, True), "a started upload is finished")

    def test_the_per_job_cap_counts_all_outputs_together(self):
        with mock.patch.object(transfer, "MAX_JOB_BYTES", 1000):
            self.assertEqual(self.put("a.bin", b"a" * 600, 600).status_code, 200)
            r = self.put("b.bin", b"b" * 10, 500)
        self.assertEqual(r.status_code, 413)
        self.assertIn("سقفِ", r.json()["error"])
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "FAILED")
        self.assertIn("هر کار", self.job.error)

    def test_re_uploading_the_same_file_is_not_double_counted(self):
        with mock.patch.object(transfer, "MAX_JOB_BYTES", 1000):
            self.assertEqual(self.put("a.bin", b"a" * 600, 600).status_code, 200)
            self.assertEqual(self.put("a.bin", b"a" * 700, 700).status_code, 200)

    def test_the_hard_caps_are_what_the_audit_asked_for(self):
        self.assertEqual(transfer.MAX_JOB_BYTES, 2 << 30)
        self.assertEqual(transfer.DISK_RESERVE, 3 << 30)
        refusal = transfer.upload_refusal(self.job, Path(self.tmp) / "o.bin", Path(self.tmp) / "o.bin.part", (2 << 30) + 1)
        self.assertEqual(refusal[0], 413)
