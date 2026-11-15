# -*- coding: utf-8 -*-
"""ممیزیِ کیفیتِ صفِ پردازش (۱۴۰۵/۰۸/۲۴): آزمونِ خودکار هرگز جلوتر از کارِ مالک نیست، کارِ بی‌صاحبِ فراموش‌شده می‌میرد و شمارش‌ها را باد نمی‌کند،
تاریخِ نامعتبر ۴۰۰ است نه ۵۰۰، و خطای ساختنِ پاسخِ heartbeat بی‌صدا قورت داده نمی‌شود."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from . import api as compute_api
from . import park, sched
from . import queue as QV
from . import services as SV
from .models import ComputeJob, ComputeNode, NodeAuto
from .selftests import Spec, runner, scope
from .tests_platform import _Base, mk_node


def age(job, **delta):
    """کار را به گذشته می‌برد (queued_at/created_at)."""
    when = timezone.now() - timedelta(**delta)
    ComputeJob.objects.filter(pk=job.pk).update(queued_at=when, created_at=when)
    job.refresh_from_db()
    return job


class SystemPriorityTests(_Base):
    def test_selftest_jobs_always_get_the_system_priority_whatever_the_spec_says(self):
        for origin, asked in (("selftest", 15), ("selftest-thumbbg", 40), ("selftest", 5)):
            j = self.job("ollama.generate", origin=origin, priority=asked, payload={"o": origin, "p": asked})
            self.assertEqual(j.priority, SV.SYSTEM_PRIORITY, (origin, asked))
        user = self.job("ollama.generate", priority=60, payload={"u": 1})
        self.assertEqual(user.priority, 60, "a user job keeps its own number")
        self.assertGreater(SV.SYSTEM_PRIORITY, 100, "above every user number (60-100)")

    def test_the_spec_default_is_already_behind_the_user(self):
        self.assertEqual(Spec("echo").priority, SV.SYSTEM_PRIORITY)

    def test_every_self_test_origin_counts_as_system(self):
        for origin in ("selftest", "selftest-thumbbg", "selftest-thumbbg-central", "multiangle-selftest"):
            self.assertTrue(SV.is_system_origin(origin), origin)
        for origin in ("panel", "photoedit", "thumbbg", "multiangle", "", None, "downloads"):
            self.assertFalse(SV.is_system_origin(origin), origin)
        j = self.job("ollama.generate", origin="multiangle-selftest", priority=20, payload={"m": 1})
        self.assertEqual(j.priority, SV.SYSTEM_PRIORITY)
        self.assertEqual(ComputeJob.objects.filter(SV.system_origin_q()).count(), 1)

    def test_a_user_job_beats_ready_tests_even_when_the_tests_were_queued_first(self):
        tests = [self.job("ollama.generate", origin="selftest", priority=15, payload={"t": i}) for i in range(4)]
        for t in tests:
            age(t, minutes=5)
        user = self.job("ollama.generate", priority=100, payload={"user": True})
        self.assertEqual(SV.claim(self.node).pk, user.pk)

    def test_with_no_user_job_a_test_runs(self):
        t = self.job("ollama.generate", origin="selftest", priority=15)
        age(t, minutes=5)
        self.assertEqual(SV.claim(self.node).pk, t.pk)

    def test_a_test_waits_a_quiet_minute_after_a_user_job_finished(self):
        t = self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 1})
        age(t, minutes=5)
        done = self.job("ollama.generate", payload={"u": 1})
        ComputeJob.objects.filter(pk=done.pk).update(state=ComputeJob.State.COMPLETED, node=self.node, finished_at=timezone.now() - timedelta(seconds=10))
        self.assertIsNone(SV.claim(self.node), "the owner often sends several jobs in a row: the test keeps waiting")
        ComputeJob.objects.filter(pk=done.pk).update(finished_at=timezone.now() - timedelta(seconds=SV.SYSTEM_QUIET_S + 5))
        self.assertEqual(SV.claim(self.node).pk, t.pk)

    def test_an_aged_test_is_released_once_per_window_even_with_user_jobs_waiting(self):
        t1 = age(self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 1}), seconds=SV.SYSTEM_AGING_S + 60)
        t2 = age(self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 2}), seconds=SV.SYSTEM_AGING_S + 120)
        users = [self.job("ollama.generate", priority=100, payload={"u": i}) for i in range(3)]
        first = SV.claim(self.node)
        self.assertEqual(first.pk, t2.pk, "the oldest starving test goes first, ahead of the owner's jobs")
        ComputeJob.objects.filter(pk=first.pk).update(state=ComputeJob.State.COMPLETED, finished_at=timezone.now() - timedelta(minutes=5))
        second = SV.claim(self.node)
        self.assertEqual(second.pk, users[0].pk, "only one test per aging window may jump the queue")
        self.assertNotEqual(second.pk, t1.pk)

    def test_the_light_lane_still_gets_the_cheap_tests(self):
        echo = self.job("echo", origin="selftest", priority=15, payload={"e": 1})
        self.assertEqual(SV.claim(self.node, lane="light").pk, echo.pk)

    def test_system_and_user_jobs_are_read_separately_so_200_user_jobs_do_not_hide_an_aged_test(self):
        t = age(self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 1}), seconds=SV.SYSTEM_AGING_S + 60)
        for i in range(210):
            SV.enqueue("ollama.generate", {"u": i}, dedupe=False, require_online=False, priority=100)
        self.assertEqual(SV.claim(self.node).pk, t.pk)


class UnownedTtlTests(_Base):
    def test_a_forgotten_panel_test_dies_after_a_day_with_a_persian_note(self):
        old = age(self.job("echo", origin="panel", payload={"o": 1}), hours=25)
        fresh = age(self.job("echo", origin="panel", payload={"o": 2}), hours=3)
        self.assertEqual(SV.expire_overdue(force=True), 1)
        old.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(old.state, "CANCELLED")
        self.assertIn("منقضی شد", old.message)
        self.assertIn("۲۴ ساعت", old.error)
        self.assertEqual(fresh.state, "QUEUED")

    def test_other_store_less_jobs_live_seven_days(self):
        a = age(self.job("ollama.pull", origin="ai_models", payload={"tag": "x"}), days=6)
        b = age(self.job("ollama.pull", origin="ai_models", payload={"tag": "y"}), days=8)
        SV.expire_overdue(force=True)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.state, b.state), ("QUEUED", "CANCELLED"))
        self.assertIn("۷ روز", b.error)

    def test_an_old_selftest_leftover_dies_after_a_day(self):
        j = age(self.job("comfy.graph", origin="selftest-thumbbg", priority=40, payload={"g": 1}), hours=30)
        SV.expire_overdue(force=True)
        j.refresh_from_db()
        self.assertEqual(j.state, "CANCELLED")

    def test_a_job_somebody_waits_for_never_expires(self):
        from apps.stores.models import Store

        user = get_user_model().objects.create_user("owner-ttl", password="x")
        store = Store.objects.create(owner=user, name="s-ttl")
        j = self.job("photo.edit", origin="panel", payload={"s": 1}, store=store)
        age(j, days=40)
        k = self.job("photo.edit", payload={"s": 2})
        ComputeJob.objects.filter(pk=k.pk).update(job_ref=123)
        age(k, days=40)
        SV.expire_overdue(force=True)
        j.refresh_from_db()
        k.refresh_from_db()
        self.assertEqual((j.state, k.state), ("QUEUED", "QUEUED"), "a store job or a job with an owner stays in the durable queue")

    def test_a_scheduled_download_waits_for_its_own_time(self):
        later = timezone.now() + timedelta(days=2)
        j = self.job("node.models", origin="downloads", payload={"p": 1}, not_before=later)
        ComputeJob.objects.filter(pk=j.pk).update(created_at=timezone.now() - timedelta(days=9), queued_at=timezone.now() - timedelta(days=9))
        SV.expire_overdue(force=True)
        j.refresh_from_db()
        self.assertEqual(j.state, "QUEUED")

    def test_parked_placeholders_are_not_touched(self):
        ph = ComputeJob.objects.create(kind=park.PARK_KIND, payload={"capability": "ollama"}, origin="park", state="QUEUED", queued_at=timezone.now() - timedelta(days=30))
        SV.expire_overdue(force=True)
        ph.refresh_from_db()
        self.assertEqual(ph.state, "QUEUED")


class HeaderCountTests(_Base):
    def test_the_header_counts_only_real_demand(self):
        real = self.job("photo.edit", payload={"r": 1})
        stale = age(self.job("photo.edit", origin="panel", payload={"s": 1}), days=5)
        test = self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 1})
        s = QV.summary()
        self.assertEqual(s["waiting"], 1, s)
        self.assertEqual(SV.summary()["queued"], 1, "the compute page card counts the same way as the header")
        self.assertEqual((s["waiting_system"], s["waiting_stale"]), (1, 1))
        self.assertEqual(s["oldest_wait_s"] is not None and s["oldest_wait_s"] < 60, True)
        self.assertIn("۱ کار", s["text"])
        for j in (real, stale, test):
            j.refresh_from_db()
            self.assertEqual(j.state, "QUEUED")

    def test_a_store_less_job_is_real_demand_until_it_is_three_days_old(self):
        self.job("photo.edit", origin="panel", payload={"r": 1})
        age(self.job("photo.edit", origin="panel", payload={"r": 2}), days=2)
        self.assertEqual(QV.summary()["waiting"], 2)

    def test_a_job_somebody_owns_stays_counted_however_old(self):
        j = self.job("photo.edit", payload={"o": 1})
        ComputeJob.objects.filter(pk=j.pk).update(job_ref=77)
        age(j, days=10)
        self.assertEqual(QV.summary()["waiting"], 1)

    def test_old_waiting_rows_carry_the_stale_flag_for_the_badge(self):
        j = age(self.job("photo.edit", origin="panel", payload={"r": 1}), days=4)
        k = self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 1})
        rows = {r["uid"]: r for r in QV.listing(state="waiting")["jobs"]}
        self.assertTrue(rows[str(j.uid)]["stale"])
        self.assertFalse(rows[str(k.uid)]["stale"])
        self.assertTrue(rows[str(k.uid)]["system"])
        self.assertFalse(rows[str(j.uid)]["system"])

    def test_free_slots_ignore_tests_and_old_leftovers_but_count_a_running_test(self):
        for i in range(2):
            self.job("ollama.generate", origin="selftest", priority=15, payload={"t": i})
        age(self.job("ollama.generate", origin="panel", payload={"old": 1}), days=6)
        self.assertEqual(park._free_slots("ollama", {}), 1, "one slot, no real demand")
        running = self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 9})
        ComputeJob.objects.filter(pk=running.pk).update(state=ComputeJob.State.RUNNING, node=self.node)
        self.assertEqual(park._free_slots("ollama", {}), 0, "a test that is running occupies the node")
        self.job("ollama.generate", payload={"real": 1})
        ComputeJob.objects.filter(pk=running.pk).update(state=ComputeJob.State.COMPLETED)
        self.assertEqual(park._free_slots("ollama", {}), 0, "a real waiting job takes the slot")


class BackgroundJobsCountTests(_Base):
    """۱۴۰۵/۰۸/۲۴ (بازبینیِ مستقل): نشانِ هدر «۲۱ کار منتظر» می‌نوشت ولی کارِ واقعیِ مالک ۹ تا بود — ۱۲ نمونه‌تصویرِ سبک
    (origin «looksample»، بی‌فروشگاه) هم شمرده می‌شد؛ و صفحهٔ صف «منتظر ۲۳» می‌نوشت. حالا یک تعریف برای هر دو."""

    def sample(self, n=3, kind="comfy.graph"):
        return [self.job(kind, origin="looksample", payload={"look": i}) for i in range(n)]

    def test_look_samples_are_background_not_demand(self):
        self.assertTrue(SV.is_background_origin("looksample"))
        self.assertFalse(SV.is_background_origin("looksample", store_id=5), "a sample somebody's store owns is real demand")
        for origin in ("panel", "photoedit", "thumbbg", "", None, "selftest"):
            self.assertFalse(SV.is_background_origin(origin), origin)
        self.assertFalse(SV.is_system_origin("looksample"), "not a self-test: it keeps its own priority rules")
        s1, s2 = self.sample(2)
        self.assertEqual(ComputeJob.objects.filter(SV.background_origin_q()).count(), 2)
        self.assertEqual(ComputeJob.objects.filter(SV.demand_excluded_q()).count(), 2)

    def test_header_and_queue_page_use_the_same_definition(self):
        real = [self.job("photo.edit", payload={"r": i}) for i in range(2)]
        self.sample(3)
        self.job("ollama.generate", origin="selftest", priority=15, payload={"t": 1})
        stale = age(self.job("photo.edit", origin="panel", payload={"s": 1}), days=5)
        s = QV.summary()
        self.assertEqual(s["waiting"], 2, s)
        self.assertEqual((s["waiting_system"], s["waiting_background"], s["waiting_stale"]), (1, 3, 1))
        self.assertEqual(s["background"], 5, "test + samples + stale leftover")
        self.assertIn("۲ کار", s["text"])
        c = QV.counts()
        self.assertEqual(c["waiting"], s["waiting"], "the «منتظر» tab and the header chip are the same number")
        self.assertEqual(c["background"], s["background"])
        self.assertEqual(c["all"], 7, "every job is still in «همه»")
        listing = QV.listing(state="waiting")
        self.assertEqual(listing["total"], 7, "the rows are all there, the counter says how many are real")
        self.assertEqual(listing["counts"]["waiting"], 2)
        for j in real:
            j.refresh_from_db()
            self.assertEqual(j.state, "QUEUED")
        self.assertEqual(SV.summary()["queued"], 2, "the compute page card agrees too")

    def test_rows_carry_the_background_flag(self):
        samples = self.sample(1)
        real = self.job("photo.edit", payload={"r": 1})
        rows = {r["uid"]: r for r in QV.listing(state="waiting")["jobs"]}
        self.assertTrue(rows[str(samples[0].uid)]["background"])
        self.assertFalse(rows[str(samples[0].uid)]["system"])
        self.assertFalse(rows[str(real.uid)]["background"])

    def test_only_samples_waiting_means_nothing_real_is_waiting(self):
        self.sample(4)
        s = QV.summary()
        self.assertEqual((s["waiting"], s["background"]), (0, 4))
        self.assertEqual(s["text"], "صف خالی است")
        self.assertEqual(QV.counts()["waiting"], 0)

    def test_samples_do_not_eat_the_free_slots(self):
        self.sample(3, kind="ollama.generate")
        self.assertEqual(park._free_slots("ollama", {}), 1, "one slot, background samples are no demand")

    def test_the_api_exposes_the_split(self):
        staff = get_user_model().objects.create_user("q-staff", "q@x.io", "pw", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        self.job("photo.edit", payload={"r": 1})
        self.sample(2)
        d = c.get("/api/v1/compute/queue/summary/").data
        self.assertEqual((d["waiting"], d["background"]), (1, 2))
        d = c.get("/api/v1/compute/queue/?state=waiting").data
        self.assertEqual((d["counts"]["waiting"], d["counts"]["background"], d["total"]), (1, 2, 3))


class RunnerScopeTests(_Base):
    """اجرای پس از نسخهٔ تازه: کامل فقط یک بار در روز؛ بعد «سریع»."""

    FILES_A = {"ollama_jobs.py": "aa", "edit_jobs.py": "e1", "edit_render.py": "e2", "photo_matting.py": "pm", "agent.py": "ag1"}

    def setUp(self):
        super().setUp()
        self.files = dict(self.FILES_A)
        p = mock.patch.object(scope, "manifest_files", side_effect=lambda: dict(self.files))
        p.start()
        self.addCleanup(p.stop)

    def keys(self, run):
        return {r.key for r in run.results.all()}

    def finish_all_passed(self, run):
        run.results.update(state="PASSED")
        run.state = "FINISHED"
        run.save()

    def test_the_first_run_after_a_version_is_full_and_the_next_in_a_day_is_quick(self):
        first = runner.start_run(self.node, "version")
        self.assertEqual(first.trigger, "version")
        self.assertGreater(len(self.keys(first)), 15)
        self.assertEqual(first.note, "")
        self.finish_all_passed(first)
        again = runner.start_run(self.node, "version")
        self.assertEqual(again.trigger, "quick")
        self.assertIn("آزمونِ سریع", again.note)
        keys = self.keys(again)
        self.assertTrue(scope.CHEAP & keys, keys)
        self.assertNotIn("ollama_vision", keys, "an unchanged heavy feature is left to the nightly run")
        self.assertNotIn("comfy_flux", keys)
        self.assertLess(len(keys), len(self.keys(first)) / 2)

    def test_a_quick_run_adds_the_features_whose_own_files_changed(self):
        first = runner.start_run(self.node, "version")
        self.finish_all_passed(first)
        for r in first.results.filter(key__in=["edit_render", "ollama_text", "matting"]):
            self.assertTrue(r.extra.get("code_fp"), r.key)
        self.files["edit_render.py"] = "e2-new"
        quick = runner.start_run(self.node, "version")
        keys = self.keys(quick)
        self.assertIn("edit_render", keys)
        self.assertIn("autoedit_mix", keys, "its prerequisite/sibling feature rides along")
        self.assertNotIn("matting", keys)
        self.assertNotIn("ollama_text", keys)

    def test_a_feature_that_never_passed_is_included_in_a_quick_run(self):
        first = runner.start_run(self.node, "version")
        first.results.update(state="PASSED")
        first.results.filter(key="matting").update(state="FAILED")
        first.state = "FINISHED"
        first.save()
        quick = runner.start_run(self.node, "version")
        self.assertIn("matting", self.keys(quick))

    def test_a_test_that_failed_last_time_is_retested_in_the_quick_run_even_without_a_file_of_its_own(self):
        first = runner.start_run(self.node, "version")
        first.results.update(state="PASSED")
        first.results.filter(key="comfy_flux").update(state="FAILED")
        first.state = "FINISHED"
        first.save()
        quick = runner.start_run(self.node, "version")
        keys = self.keys(quick)
        self.assertIn("comfy_flux", keys, "the update may have fixed it: the owner learns now, not tomorrow night")
        self.assertNotIn("ollama_text", keys)
        self.assertIn("رد شده بود", quick.note)

    def test_an_aborted_run_does_not_count_as_the_daily_full_run(self):
        first = runner.start_run(self.node, "version")
        first.state = "ABORTED"
        first.save()
        self.assertEqual(scope.version_scope(self.node), "full")

    def test_the_manual_button_always_runs_everything(self):
        first = runner.start_run(self.node, "version")
        self.finish_all_passed(first)
        manual = runner.start_run(self.node, "manual", "owner")
        self.assertEqual(manual.trigger, "manual")
        self.assertEqual(self.keys(manual), self.keys(first))

    def test_three_packages_in_a_few_hours_run_the_full_suite_once(self):
        runs = []
        for code in ("a", "b", "c"):
            self.node.capabilities = {**self.node.capabilities, "code": {"version": "2.11", "id": code * 20}}
            self.node.save()
            run = runner.start_run(self.node, "version")
            self.finish_all_passed(run)
            runs.append(run)
        self.assertEqual([r.trigger for r in runs], ["version", "quick", "quick"])

    def test_coming_back_online_is_full_the_first_time_and_quick_when_a_full_run_just_happened(self):
        # «سرور بعد از قطعی دوباره روشن شد» (autopilot.note_presence) همان سقفِ «یک اجرای کامل در روز» را دارد
        from .models import SelfTestRun

        first = runner.start_run(self.node, "online")
        self.assertEqual(first.trigger, "online")
        self.assertGreater(len(self.keys(first)), 15)
        self.finish_all_passed(first)
        again = runner.start_run(self.node, "online")
        self.assertEqual(again.trigger, "quick")
        self.assertIn("با روشن‌شدنِ دوبارهٔ سرور", again.note)
        self.assertLess(len(self.keys(again)), len(self.keys(first)) / 2)
        self.finish_all_passed(again)
        SelfTestRun.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(hours=30))
        third = runner.start_run(self.node, "online")
        self.assertEqual(third.trigger, "online", "a day later the node is tested in full again")

    def test_the_nightly_run_is_skipped_when_a_full_run_just_happened_and_runs_otherwise(self):
        from . import autopilot
        from .models import ComputeSettings

        ComputeSettings.objects.update_or_create(pk=1, defaults={"nightly_selftest": True, "nightly_time": "00:00"})
        first = runner.start_run(self.node, "version")
        self.finish_all_passed(first)
        self.assertTrue(scope.full_run_exists(self.node, scope.NIGHTLY_SKIP_H))
        self.assertFalse(scope.full_run_exists(self.node, scope.NIGHTLY_SKIP_H, now=timezone.now() + timedelta(hours=40)))
        with mock.patch.object(runner, "advance_all", return_value={}):
            out = autopilot.tick()
        self.assertEqual(out["nightly"], 0)
        self.assertEqual(out.get("nightly_skipped"), 1, "a full run happened a moment ago: the day is used up without a second one")
        self.assertFalse(first.node.selftest_runs.filter(trigger="nightly").exists())
        NodeAuto.objects.filter(node=self.node).update(last_nightly="")
        first.results.all().delete()
        type(first).objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(hours=30))
        with mock.patch.object(runner, "advance_all", return_value={}):
            out = autopilot.tick()
        self.assertEqual(out["nightly"], 1)
        self.assertTrue(first.node.selftest_runs.filter(trigger="nightly").exists())


class HeavyHoldTests(_Base):
    def setUp(self):
        super().setUp()
        # a node that has everything the tests need (the same report SelfTestRunTests builds), so no test is skipped for a missing model
        self.node.capabilities.update({
            "gpu": "RTX 3060", "ollama_models": ["qwen3:8b", "qwq:32b", "qwen3-vl:30b"], "photo_matting": True,
            "matting_runtime": {"ok": True, "gpu": True, "providers": ["Dml"]}, "matting_models": {"u2netp": {"state": "installed"}},
            "audio": {"moss": True, "sfx": True, "music": True}, "edit": {"render": True, "nvenc": {"h264": True}},
            "comfy_profiles": ["flux-product-fast", "wan22-480p-short"],
            "bootstrap": {"summary": {"ready": 2}, "blocked_kinds": {}, "features": {"gpu-runtime": {"state": "ready", "title": "x", "items": []}}},
            "outbox": {"pending": 0}, "net": {"offline_s": 0}, "lanes": {"light": 1}})
        self.node.save()

    def test_which_tests_are_heavy(self):
        from .selftests import REGISTRY, load_all

        load_all()
        for key in ("ollama_vision", "comfy_flux", "tts_moss", "up3d_stage", "motion_studio", "autoedit_matte"):
            self.assertTrue(scope.is_heavy(REGISTRY[key]), key)
        for key in ("echo", "gpu", "ffmpeg_nvenc", "net", "bootstrap", "update_flow", "model_catalog"):
            self.assertFalse(scope.is_heavy(REGISTRY[key]), key)

    def make_run(self, only):
        return runner.start_run(self.node, "manual", only=only)

    def test_a_heavy_test_waits_while_a_user_job_is_on_the_node_then_goes(self):
        user = self.job("ollama.generate", payload={"u": 1})
        run = self.make_run(["ollama_vision"])
        r = run.results.get(key="ollama_vision")
        self.assertEqual(r.state, "WAITING", r.detail)
        self.assertIn("منتظرِ تمام شدنِ کارهای شما", r.detail)
        self.assertFalse(ComputeJob.objects.filter(origin="selftest").exists(), "no test job is built while the owner's job waits")
        ComputeJob.objects.filter(pk=user.pk).update(state=ComputeJob.State.COMPLETED, finished_at=timezone.now())
        runner.advance(run)
        r.refresh_from_db()
        self.assertIn(r.state, ("QUEUED", "RUNNING"), r.detail)
        self.assertTrue(ComputeJob.objects.filter(origin="selftest", kind="ollama.generate").exists())

    def test_a_heavy_test_does_not_wait_forever(self):
        self.job("ollama.generate", payload={"u": 1})
        run = self.make_run(["ollama_vision"])
        r = run.results.get(key="ollama_vision")
        self.assertEqual(r.state, "WAITING")
        r.extra = {**r.extra, "busy_since": timezone.now().timestamp() - scope.HEAVY_HOLD_MAX_S - 5}
        r.save()
        runner.advance(run)
        r.refresh_from_db()
        self.assertIn(r.state, ("QUEUED", "RUNNING"), "after the cap it goes, with the system priority behind the owner")
        self.assertEqual(ComputeJob.objects.get(origin="selftest", kind="ollama.generate").priority, SV.SYSTEM_PRIORITY)

    def test_a_job_scheduled_for_later_or_a_download_is_not_demand_now(self):
        self.job("ollama.generate", payload={"later": 1}, not_before=timezone.now() + timedelta(hours=5))
        self.job("ollama.pull", payload={"tag": "x"})
        self.assertEqual(scope.user_work_reason(self.node), "")
        self.job("ollama.generate", payload={"now": 1})
        self.assertIn("۱ کار", scope.user_work_reason(self.node))

    def test_the_cheap_tests_never_wait_for_the_owner(self):
        self.job("ollama.generate", payload={"u": 1})
        run = self.make_run(["echo"])
        r = run.results.get(key="echo")
        self.assertIn(r.state, ("QUEUED", "RUNNING"), r.detail)

    def test_a_test_queued_behind_the_owners_job_is_not_failed_as_stuck(self):
        run = self.make_run(["echo"])
        r = run.results.get(key="echo")
        job = ComputeJob.objects.get(uid=r.job_uid)
        self.job("ollama.generate", payload={"u": 1})
        SelfRow = type(r)
        SelfRow.objects.filter(pk=r.pk).update(started_at=timezone.now() - timedelta(seconds=runner.QUEUE_STALE_S + 600))
        runner.advance(run)
        r.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(r.state, "QUEUED", r.detail)
        self.assertIn("پشتِ کارِ شما", r.detail)
        self.assertEqual(job.state, "QUEUED")

    def test_a_test_that_queued_long_ago_but_ran_briefly_is_not_cancelled_for_the_wait(self):
        run = self.make_run(["echo"])
        r = run.results.get(key="echo")
        job = ComputeJob.objects.get(uid=r.job_uid)
        type(r).objects.filter(pk=r.pk).update(started_at=timezone.now() - timedelta(hours=2))
        ComputeJob.objects.filter(pk=job.pk).update(state=ComputeJob.State.RUNNING, node=self.node, claimed_at=timezone.now() - timedelta(seconds=5))
        runner.advance(run)
        r.refresh_from_db()
        self.assertEqual(r.state, "RUNNING", r.detail)


class ParseDateTests(_Base):
    def setUp(self):
        super().setUp()
        self.staff = get_user_model().objects.create_user("staff-q", password="x", is_staff=True)
        self.c = APIClient()
        self.c.force_authenticate(self.staff)

    def test_a_well_formed_but_impossible_date_is_a_400_with_a_persian_message(self):
        for bad in ("2026-13-45", "2026-11-14T99:00", "2026-02-30"):
            for field in ("since", "until"):
                r = self.c.get("/api/v1/compute/queue/", {field: bad})
                self.assertEqual(r.status_code, 400, (field, bad, r.content[:200]))
                self.assertIn("تاریخ نامعتبر", str(r.json()[field]))

    def test_garbage_is_ignored_and_a_good_date_still_filters(self):
        self.assertEqual(self.c.get("/api/v1/compute/queue/", {"since": "garbage"}).status_code, 200)
        self.assertEqual(self.c.get("/api/v1/compute/queue/", {"since": "2026-11-01", "until": "2026-11-30T10:00"}).status_code, 200)
        self.assertEqual(self.c.get("/api/v1/compute/queue/").status_code, 200)

    def test_the_report_endpoint_keeps_its_own_400(self):
        self.assertEqual(self.c.get("/api/v1/compute/report/", {"from": "2026-13-45"}).status_code, 400)


class HeartbeatErrorTests(_Base):
    """هر بخشِ پاسخِ heartbeat که خطا بدهد: پاسخ ۲۰۰ می‌ماند، خطا در لاگ می‌آید، در پاسخ و روی کارتِ گره دیده می‌شود."""

    def setUp(self):
        super().setUp()
        self.node = ComputeNode.objects.get(pk=self.node.pk)
        self.c = APIClient()
        self.hb = lambda: self.c.post("/api/v1/compute/heartbeat/", dict(self.node.capabilities), format="json",
                                      HTTP_AUTHORIZATION="Node " + self.node.token)
        compute_api._CTL_LOGGED.clear()

    BLOCKS = [
        ("apps.compute.commands.pending_for", "دستورِ به‌روزرسانی"),
        ("services.ai.priority.config", "راهنمای مدل‌های هوش مصنوعی"),
        ("apps.compute.schedule.control_block", "زمانِ دانلودها"),
        ("apps.compute.auto_models.control_block", "دانلودِ خودکارِ مدل‌ها"),
    ]

    def test_each_block_that_raises_still_answers_200_with_the_error(self):
        for target, title in self.BLOCKS:
            compute_api._CTL_LOGGED.clear()
            with mock.patch(target, side_effect=RuntimeError("boom-" + title)):
                with self.assertLogs("apps.compute.api", level="WARNING") as logs:
                    r = self.hb()
            self.assertEqual(r.status_code, 200, (target, r.content[:200]))
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertIn("خطا در ساختنِ", body["control_error"])
            self.assertIn(title, body["control_error"])
            self.assertIn("boom-" + title, body["control_error"])
            self.assertTrue(any("heartbeat answer" in line for line in logs.output), logs.output)
            self.assertNotIn("_errors", body)
            self.node.refresh_from_db()
            self.assertIn(title, self.node.capabilities["site_errors"][0], "stored for the node card")
            self.assertIn(title, compute_api.node_json(self.node)["site_errors"][0])

    def test_the_other_parts_of_the_answer_survive_one_failing_block(self):
        with mock.patch("apps.compute.auto_models.control_block", side_effect=RuntimeError("x")):
            body = self.hb().json()
        self.assertIn("desired", body)
        self.assertIn("downloads", body)
        self.assertNotIn("models_auto", body)

    def test_a_healthy_heartbeat_has_no_error_and_clears_the_card(self):
        with mock.patch("apps.compute.schedule.control_block", side_effect=RuntimeError("x")):
            self.hb()
        self.node.refresh_from_db()
        self.assertTrue(self.node.capabilities.get("site_errors"))
        body = self.hb().json()
        self.assertNotIn("control_error", body)
        self.node.refresh_from_db()
        self.assertFalse(self.node.capabilities.get("site_errors"))
        self.assertEqual(compute_api.node_json(self.node)["site_errors"], [])

    def test_the_error_is_logged_once_not_every_heartbeat(self):
        with mock.patch("apps.compute.commands.pending_for", side_effect=RuntimeError("same")):
            with self.assertLogs("apps.compute.api", level="WARNING") as logs:
                for _ in range(5):
                    self.hb()
        self.assertEqual(len([line for line in logs.output if "heartbeat answer" in line]), 1)

    def test_the_site_error_survives_the_next_heartbeat_without_extra_writes(self):
        with mock.patch("apps.compute.schedule.control_block", side_effect=RuntimeError("x")):
            self.hb()
            self.node.refresh_from_db()
            first = list(self.node.capabilities["site_errors"])
            self.hb()
            self.node.refresh_from_db()
        self.assertEqual(self.node.capabilities["site_errors"], first)

    def test_the_claim_answer_also_survives_a_failing_block(self):
        with mock.patch("apps.compute.auto_models.control_block", side_effect=RuntimeError("x")):
            r = self.c.post("/api/v1/compute/claim/", {}, format="json", HTTP_AUTHORIZATION="Node " + self.node.token)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_errors", r.json())
        self.assertIn("control_error", r.json())

    def test_a_failing_pull_completion_hook_is_logged_not_swallowed(self):
        job = SV.enqueue("ollama.pull", {"tag": "qwen3:8b"}, dedupe=False, require_online=False, node=self.node.name, origin="ai_models")
        ComputeJob.objects.filter(pk=job.pk).update(state=ComputeJob.State.RUNNING, node=self.node, claimed_at=timezone.now())
        with mock.patch("services.ai.model_pull.pull_completed", side_effect=RuntimeError("hook")):
            with self.assertLogs("apps.compute.api", level="WARNING") as logs:
                r = self.c.post(f"/api/v1/compute/jobs/{job.uid}/finish/", {"ok": True}, format="json", HTTP_AUTHORIZATION="Node " + self.node.token)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("pull_completed failed" in line for line in logs.output), logs.output)
