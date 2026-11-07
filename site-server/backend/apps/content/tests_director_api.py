"""The director's API: catalogue, one-click tools (`director/apply`), auto-reframe, project versions, and the whole job
(analyse → recipes → three lightweight drafts) with the model mocked. Real ffmpeg on tiny clips; no Metis, no node."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import captions
from services.video.ffmpeg import FFMPEG

from . import editor_project
from .models import DirectorDraft, UploadedVideo, VideoProject
from .tests_editor_modes import make_video

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-director-api-")


def run_inline(job, task, *args, **kwargs):
    """`dispatch_job` stand-in: run the task function right here (no broker in tests)."""
    task(*args, **kwargs)
    return None


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class DirectorApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (shutil.which(FFMPEG) or shutil.which("ffmpeg")):
            return
        root = Path(TEMP_MEDIA)
        cls.wide = make_video(root / "uploads/videos/d_wide.mp4", size="320x180", seconds=4)
        cls.tall = make_video(root / "uploads/videos/d_tall.mp4", size="180x320", seconds=3, freq=660)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "wide"):
            self.skipTest("ffmpeg نیست")
        shutil.rmtree(Path(TEMP_MEDIA) / "generated", ignore_errors=True)       # versions of an earlier test's project (pks are reused)
        self.owner = User.objects.create_user("dir-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه کارگردان")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up1 = UploadedVideo.objects.create(store=self.store, title="چای سبز", video="uploads/videos/d_wide.mp4", state="READY", duration=4.0, has_audio=True)
        self.up2 = UploadedVideo.objects.create(store=self.store, title="بسته‌بندی", video="uploads/videos/d_tall.mp4", state="READY", duration=3.0, has_audio=True)

    def call(self, method, url, body=None):
        fn = getattr(self.client, method)
        if body is None:
            return fn(self.base + url)
        return fn(self.base + url, json.dumps(body), content_type="application/json")

    def project_data(self):
        return {"format": {"width": 240, "height": 426, "fps": 12, "preset": "reel"}, "tracks": [
            {"id": "t1", "kind": "video", "name": "تصویر ۱", "muted": False, "locked": False, "clips": [
                {"id": "c1", "type": "media", "ref": f"video:{self.up1.pk}", "label": "چای", "kind": "video", "at": 0, "start": 0, "end": 4, "src": 4, "opacity": 1, "x": 0, "y": 0,
                 "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": True, "has_audio": True, "effects": [], "transition": None}]},
            {"id": "t2", "kind": "audio", "name": "گفتار", "role": "speech", "muted": False, "locked": False, "clips": []},
            {"id": "t3", "kind": "audio", "name": "موسیقی", "role": "music", "muted": False, "locked": False, "clips": []}],
            "global_ops": [], "markers": [], "inout": None}

    # ------------------------------------------------------------ catalogue
    def test_catalogue_describes_tools_recipes_safe_zones_and_what_is_available(self):
        c = self.call("get", "/editor/director/catalogue/").json()
        self.assertGreaterEqual(len(c["tools"]), 30)
        self.assertEqual({r["key"] for r in c["recipes"]}, {"product_showcase", "unboxing", "before_after", "sale", "testimonial", "slideshow"})
        self.assertEqual({z["key"] for z in c["safe_zones"]}, {"reels", "story", "tiktok", "shorts", "feed"})
        self.assertIn("ok", c["captions"])
        self.assertIn("node", c["ai"])
        self.assertEqual({v["key"] for v in c["variants"]}, {"a", "b", "c"})
        e = self.call("get", "/editor/catalogue/").json()
        self.assertEqual(len(e["safe_zones"]), 5)                              # the manual editor reads the same bands
        other = User.objects.create_user("dir-intruder", password="x")
        self.client.force_login(other)
        self.assertIn(self.call("get", "/editor/director/catalogue/").status_code, (403, 404))

    # ------------------------------------------------------------ one-click tools
    def test_apply_runs_sound_tools_on_the_posted_project_and_reports_each_step(self):
        data = self.project_data()
        r = self.call("post", "/editor/director/apply/", {"data": data, "steps": [
            {"tool": "set_loudness", "params": {"on": True}},
            {"tool": "clean_voice", "params": {"clip": "all", "level": "light"}},
            {"tool": "ducking", "params": {"on": True, "amount_db": 14}},
            {"tool": "add_music", "params": {}},                                # no music anywhere → a Persian reason, not a crash
            {"tool": "teleport", "params": {}}]})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual([x["ok"] for x in body["results"]], [True, True, True, False])
        self.assertIn("موسیقی", body["results"][3]["message"])
        self.assertEqual(body["data"]["master"]["loudness"]["target"], -14)
        self.assertTrue(body["data"]["tracks"][0]["clips"][0]["audio"]["denoise_ai"])
        self.assertEqual(body["data"]["ducking"]["amount_db"], 14)
        self.assertEqual(len(body["notes"]), 1)                                 # the unknown tool
        self.assertTrue(body["check"]["ok"], body["check"])                     # the result still renders
        self.assertNotIn("denoise_ai", json.dumps(data))                        # the request body object is not what changed server-side state

    def test_remove_silence_on_the_tone_says_there_is_nothing_to_cut(self):
        r = self.call("post", "/editor/director/apply/", {"data": self.project_data(), "steps": [{"tool": "remove_silence", "params": {}}]})
        res = r.json()["results"][0]
        self.assertFalse(res["ok"])
        self.assertIn("سکوت", res["message"])

    def test_remove_fillers_through_apply_says_why_when_speech_recognition_is_off(self):
        with patch("services.editing.captions.status", return_value={"node": False, "local": False, "ok": False, "message": captions.OFFLINE_MESSAGE}):
            r = self.call("post", "/editor/director/apply/", {"data": self.project_data(), "steps": [{"tool": "remove_fillers", "params": {}}]})
        res = r.json()["results"][0]
        self.assertFalse(res["ok"])
        self.assertTrue(res["message"])

    def test_apply_validates_its_input(self):
        self.assertEqual(self.call("post", "/editor/director/apply/", {"steps": []}).status_code, 400)
        self.assertEqual(self.call("post", "/editor/director/apply/", {"data": self.project_data(), "steps": []}).status_code, 400)
        other = User.objects.create_user("dir-intruder2", password="x")
        self.client.force_login(other)
        self.assertIn(self.call("post", "/editor/director/apply/", {"data": self.project_data(), "steps": [{"tool": "ducking", "params": {}}]}).status_code, (403, 404))

    # ------------------------------------------------------------ reframe
    def test_reframe_returns_a_vertical_window_over_a_wide_clip(self):
        r = self.call("post", "/editor/reframe/", {"ref": f"video:{self.up1.pk}", "start": 0, "end": 4, "aspect": "9:16"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertAlmostEqual(body["reframe"]["w"], 0.3164, places=3)
        self.assertEqual(body["reframe"]["h"], 1.0)
        self.assertIn(body["engine"], ("face", "motion", "center"))
        self.assertLessEqual(len(body["reframe"].get("kx", [])), 24)
        project = self.project_data()
        project["tracks"][0]["clips"][0]["reframe"] = body["reframe"]
        self.assertTrue(editor_project.check(self.store, project)["ok"])           # the renderer accepts what the API returned

    def test_reframe_errors_are_persian(self):
        self.assertEqual(self.call("post", "/editor/reframe/", {"ref": "video:99999", "aspect": "9:16"}).status_code, 404)
        r = self.call("post", "/editor/reframe/", {"ref": f"video:{self.up1.pk}", "aspect": "abc"})
        self.assertEqual(r.status_code, 400)
        r = self.call("post", "/editor/reframe/", {"ref": f"video:{self.up1.pk}", "start": 0, "end": 3, "aspect": "16:9"})
        self.assertEqual((r.json()["reframe"]["w"], r.json()["reframe"]["h"]), (1.0, 1.0))
        self.assertTrue(r.json()["notes"])

    # ------------------------------------------------------------ versions
    def test_versions_snapshot_list_and_restore_with_a_safety_snapshot(self):
        row = VideoProject.objects.create(store=self.store, title="نسخه‌ها", data=self.project_data())
        self.assertEqual(self.call("get", f"/editor/projects/{row.pk}/versions/").json()["versions"], [])
        self.assertEqual(self.call("post", f"/editor/projects/{row.pk}/versions/", {"label": "پیش از تیتر"}).status_code, 201)
        changed = self.project_data()
        changed["tracks"][0]["clips"][0]["end"] = 2
        self.call("put", f"/editor/projects/{row.pk}/", {"data": changed})
        listing = self.call("get", f"/editor/projects/{row.pk}/versions/").json()["versions"]
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["label"], "پیش از تیتر")
        r = self.call("post", f"/editor/projects/{row.pk}/versions/{listing[0]['name']}/")
        self.assertEqual(r.status_code, 200, r.content)
        row.refresh_from_db()
        self.assertEqual(row.data["tracks"][0]["clips"][0]["end"], 4)
        self.assertEqual(len(self.call("get", f"/editor/projects/{row.pk}/versions/").json()["versions"]), 2)     # + the safety snapshot
        self.assertEqual(self.call("post", f"/editor/projects/{row.pk}/versions/../../etc/").status_code, 404)
        self.assertEqual(self.call("post", f"/editor/projects/{row.pk}/versions/nope.json/").status_code, 400)

    def test_versions_keep_only_the_newest_twenty(self):
        from . import views_director
        row = VideoProject.objects.create(store=self.store, title="v", data=self.project_data())
        for i in range(23):
            views_director.snapshot(row, f"n{i}")
        self.assertLessEqual(len(self.call("get", f"/editor/projects/{row.pk}/versions/").json()["versions"]), 20)

    # ------------------------------------------------------------ the whole job
    def run_director(self, body, **patches):
        with patch("apps.content.views_director.dispatch_job", side_effect=run_inline), \
                patch("services.editing.captions.status", return_value={"node": False, "local": False, "ok": False, "message": captions.OFFLINE_MESSAGE}):
            r = self.call("post", "/editor/director/run/", body)
        return r

    def test_run_builds_three_valid_editable_drafts_without_ai_and_explains_what_was_skipped(self):
        r = self.run_director({"prompt": "ریلز معرفی چای ۱۵ ثانیه‌ای", "refs": [f"video:{self.up1.pk}", f"video:{self.up2.pk}"], "options": {"use_ai": False, "preview": False}})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        result = job.result
        self.assertEqual({p["key"] for p in result["drafts"]}, {"a", "b", "c"})
        self.assertEqual(VideoProject.objects.count(), 0, "a «بساز» must not create real projects any more")
        self.assertEqual(DirectorDraft.objects.filter(store=self.store).count(), 3)
        self.assertEqual(result["draft_days"], 7)
        self.assertEqual(result["brief"]["platform"], "reels")
        self.assertEqual(result["brief"]["duration"], 15)
        text = " ".join(result["degraded"])
        self.assertIn("هوش مصنوعی", text) if result["ai"]["enabled"] else None
        self.assertTrue(any("زیرنویس" in d or "گفتار" in d for d in result["degraded"]), result["degraded"])   # ASR was off: said so
        for row in result["drafts"]:
            draft = DirectorDraft.objects.get(pk=row["id"])
            self.assertEqual(draft.data["director"]["variant"], row["key"])
            self.assertTrue(draft.data["director"]["plan"])
            verdict = editor_project.check(self.store, draft.data)
            self.assertTrue(verdict["ok"], (row, verdict))
            self.assertLessEqual(verdict["length"], 22)
        for v in result["variants"]:
            self.assertTrue(all(s["text"] and s["title"] for s in v["plan"]))
            self.assertIn("score", v["critique"])
            self.assertIsNone(v["project_id"])
            self.assertTrue(v["draft_id"])

    def test_the_owner_can_switch_a_step_off_and_run_the_plan_again(self):
        refs = [f"video:{self.up1.pk}", f"video:{self.up2.pk}"]
        r = self.run_director({"prompt": "ریلز", "refs": refs, "options": {"use_ai": False, "preview": False, "variants": 1}})
        job = Job.objects.get(pk=r.json()["job_id"])
        res = job.result
        v = res["variants"][0]
        steps = [{"id": s["id"], "tool": s["tool"], "params": s["params"], "why": s["why"], "on": s["tool"] != "end_card"} for s in v["plan"] if not s["id"].startswith("f")]
        with patch("apps.content.views_director.dispatch_job", side_effect=run_inline), \
                patch("services.editing.captions.status", return_value={"node": False, "local": False, "ok": False, "message": captions.OFFLINE_MESSAGE}):
            r2 = self.call("post", "/editor/director/rerun/", {"brief": res["brief"], "steps": steps, "refs": refs, "variant": "a", "draft_id": v["draft_id"]})
        self.assertEqual(r2.status_code, 202, r2.content)
        job2 = Job.objects.get(pk=r2.json()["job_id"])
        self.assertEqual(job2.state, Job.State.COMPLETED, job2.error)
        again = job2.result["variants"][0]
        self.assertEqual(again["draft_id"], v["draft_id"])                      # the same draft was replaced, not duplicated
        self.assertTrue(any(s.get("skipped") for s in again["plan"] if s["tool"] == "end_card"))
        self.assertFalse(next(i for i in again["critique"]["items"] if i["key"] == "cta")["ok"])
        self.assertEqual(DirectorDraft.objects.filter(store=self.store).count(), 1)
        self.assertEqual(VideoProject.objects.filter(store=self.store).count(), 0)

    def test_a_model_that_answers_improves_the_brief_and_one_that_fails_is_reported(self):
        refs = [f"video:{self.up1.pk}"]
        info_bad = {"asked": True, "ok": False, "via": "", "model": "", "error_code": "no_credit", "error": "اعتبارِ حسابِ سرویسِ هوش مصنوعی (Metis) تمام شده است (خطای ۴۰۲).",
                    "fell_back": False, "fallback_reason": ""}
        with patch("services.editing.director.ai.call_json", return_value=(None, info_bad)):
            r = self.run_director({"prompt": "ریلز", "refs": refs, "options": {"preview": False, "variants": 1, "use_ai": True}})       # AI is OFF by default: ask for it
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertFalse(job.result["ai"]["ok"])
        self.assertTrue(any("۴۰۲" in d for d in job.result["degraded"]))
        self.assertTrue(job.result["ai"]["needed_for"])
        DirectorDraft.objects.all().delete()
        good = {"recipe": "sale", "platform": "story", "duration": 12, "pace": "fast", "title": "چای تازه", "subtitle": "", "cta": "الان بخر", "discount": 20,
                "captions": True, "music": False, "look": "vivid", "hook_ref": "", "order": [], "notes_fa": ""}
        info_ok = {**info_bad, "ok": True, "error": "", "error_code": "", "via": "node", "model": "gemma3:12b"}

        def fake(store, **kw):
            return (good, info_ok) if kw["prompt_id"] == "video_director_brief" else ({"steps": []}, info_ok)
        with patch("services.editing.director.ai.call_json", side_effect=fake):
            r = self.run_director({"prompt": "", "refs": refs, "options": {"preview": False, "variants": 1, "use_ai": True}})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual((job.result["brief"]["recipe"], job.result["brief"]["platform"], job.result["brief"]["title"]), ("sale", "story", "چای تازه"))
        self.assertEqual(job.result["ai"]["via"], "node")

    def test_run_validates_and_refuses_a_second_concurrent_run(self):
        self.assertEqual(self.call("post", "/editor/director/run/", {"prompt": "x", "refs": []}).status_code, 400)
        Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, state=Job.State.RUNNING, context={"what": "director"})
        r = self.call("post", "/editor/director/run/", {"prompt": "x", "refs": [f"video:{self.up1.pk}"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("کارگردان", r.json()["error"]["message"])

    def test_a_missing_ref_is_skipped_with_a_note_and_no_visuals_fails_clearly(self):
        r = self.run_director({"prompt": "ریلز", "refs": [f"video:{self.up1.pk}", "video:424242"], "options": {"use_ai": False, "preview": False, "variants": 1}})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertTrue(any("پیدا نشد" in d for d in job.result["degraded"]))
        Job.objects.all().delete()
        r = self.run_director({"prompt": "ریلز", "refs": ["video:424242"], "options": {"use_ai": False, "preview": False}})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertIn("ویدیو یا عکس", job.error)

    def test_a_transcript_is_listened_to_once_and_then_kept(self):
        from services.editing.director.ctx import store_ctx
        calls = []

        def fake_transcribe(wav, store=None, **kw):
            calls.append(1)
            return {"words": [{"w": "سلام", "s": 0.2, "e": 0.6}], "text": "سلام", "engine": "node"}
        ctx = store_ctx(self.store, asr=True)
        with patch("services.editing.captions.status", return_value={"node": True, "local": False, "ok": True, "message": ""}),                 patch("services.editing.captions.transcribe_wav", side_effect=fake_transcribe):
            first = ctx.words(f"video:{self.up1.pk}", 0.0, 3.0)
            again = store_ctx(self.store, asr=True).words(f"video:{self.up1.pk}", 0.0, 3.0)
        self.assertEqual(first, again)
        self.assertEqual(len(calls), 1)
        pieces = store_ctx(self.store, asr=True).words(f"video:{self.up1.pk}", 0.1, 0.5)          # any other range of the same file: still no new job
        self.assertEqual(len(calls), 1)
        self.assertEqual(pieces[0]["w"], "سلام")
        self.assertEqual(pieces[0]["s"], 0.1)                                                       # times are relative to the range start

    def test_panel_choices_count_as_stated_and_the_model_cannot_override_them(self):
        refs = [f"video:{self.up1.pk}"]
        wrong = {"recipe": "unboxing", "platform": "youtube", "duration": 90, "pace": "slow", "title": "", "subtitle": "", "cta": "", "discount": 0, "captions": True, "music": True, "look": "", "hook_ref": "", "order": [], "notes_fa": ""}
        ok = {"asked": True, "ok": True, "via": "node", "model": "m", "error_code": "", "error": "", "fell_back": False, "fallback_reason": ""}
        with patch("services.editing.director.ai.call_json", side_effect=lambda store, **kw: (wrong, ok) if kw["prompt_id"] == "video_director_brief" else ({"steps": []}, ok)):
            r = self.run_director({"prompt": "", "refs": refs, "options": {"preview": False, "variants": 1, "override": {"recipe": "sale", "platform": "tiktok", "duration": 20, "pace": "fast", "music": False}}})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        b = job.result["brief"]
        self.assertEqual((b["recipe"], b["platform"], b["duration"], b["pace"], b["music"]), ("sale", "tiktok", 20, "fast", False))


    # ------------------------------------------------------------ drafts and editor settings (round 4)
    def run_plain(self, **opts):
        r = self.run_director({"prompt": "ریلز", "refs": [f"video:{self.up1.pk}", f"video:{self.up2.pk}"], "options": {"use_ai": False, "preview": False, **opts}})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        return job.result

    def test_settings_default_clamp_validate_and_keep_other_preferences(self):
        from apps.stores.models import StoreProfile
        StoreProfile.objects.update_or_create(store=self.store, defaults={"ai_preferences": {"editing": {"never": ["stabilize"]}}})
        s = self.call("get", "/editor/settings/").json()
        self.assertEqual((s["ai_default"], s["draft_days"], s["min_days"], s["max_days"]), (False, 7, 1, 30), "the owner's decision: the AI tick starts OFF")
        self.assertEqual((s["max_drafts"], s["min_drafts"], s["max_drafts_limit"]), (60, 10, 200))
        self.assertIn("اعتبار", s["cost_note"])
        self.assertIn("هزینه", s["cost_note"])
        self.assertEqual(self.call("put", "/editor/settings/", {"ai_default": False}).json()["ai_default"], False)
        self.assertEqual(self.call("put", "/editor/settings/", {"draft_days": 100}).json()["draft_days"], 30)
        self.assertEqual(self.call("put", "/editor/settings/", {"draft_days": 0}).json()["draft_days"], 1)
        self.assertEqual(self.call("put", "/editor/settings/", {"draft_days": "3"}).json()["draft_days"], 3)
        self.assertEqual(self.call("put", "/editor/settings/", {"draft_days": "x"}).status_code, 400)
        self.assertEqual(self.call("put", "/editor/settings/", {"ai_default": "yes"}).status_code, 400)
        self.assertEqual(self.call("put", "/editor/settings/", {"max_drafts": 5}).json()["max_drafts"], 10)
        self.assertEqual(self.call("put", "/editor/settings/", {"max_drafts": 9999}).json()["max_drafts"], 200)
        self.assertEqual(self.call("put", "/editor/settings/", {"max_drafts": "40"}).json()["max_drafts"], 40)
        self.assertEqual(self.call("put", "/editor/settings/", {"max_drafts": "x"}).status_code, 400)
        self.assertEqual(self.call("put", "/editor/settings/", {"max_drafts": 60}).json()["max_drafts"], 60)
        again = self.call("get", "/editor/settings/").json()
        self.assertEqual((again["ai_default"], again["draft_days"]), (False, 3))          # a failed PUT changed nothing
        self.assertEqual(StoreProfile.objects.get(store=self.store).ai_preferences["editing"], {"never": ["stabilize"]})
        cat = self.call("get", "/editor/director/catalogue/").json()
        self.assertEqual(cat["settings"]["ai_default"], False)                           # the panel learns the default from the catalogue
        other = User.objects.create_user("set-intruder", password="x")
        self.client.force_login(other)
        self.assertIn(self.call("get", "/editor/settings/").status_code, (403, 404))
        self.assertIn(self.call("put", "/editor/settings/", {"ai_default": True}).status_code, (403, 404))

    def test_the_ai_tick_starts_from_the_store_default_and_one_run_can_still_override_it(self):
        refs = [f"video:{self.up1.pk}"]
        asked = []

        def fake(store, **kw):
            asked.append(kw["prompt_id"])
            return (None, {"asked": True, "ok": False, "via": "", "model": "", "error": "x", "error_code": "x", "fell_back": False, "fallback_reason": ""})
        self.call("put", "/editor/settings/", {"ai_default": False})
        with patch("services.editing.director.ai.call_json", side_effect=fake):
            r = self.run_director({"prompt": "ریلز", "refs": refs, "options": {"preview": False, "variants": 1}})            # no use_ai given
        res = Job.objects.get(pk=r.json()["job_id"]).result
        self.assertEqual((res["ai"]["enabled"], asked), (False, []), "default OFF: the model must not be called at all")
        with patch("services.editing.director.ai.call_json", side_effect=fake):
            r = self.run_director({"prompt": "ریلز", "refs": refs, "options": {"preview": False, "variants": 1, "use_ai": True}})
        res = Job.objects.get(pk=r.json()["job_id"]).result
        self.assertTrue(res["ai"]["enabled"])
        self.assertIn("video_director_brief", asked)                                      # the per-run tick wins over the default
        self.call("put", "/editor/settings/", {"ai_default": True})
        asked.clear()
        with patch("services.editing.director.ai.call_json", side_effect=fake):
            r = self.run_director({"prompt": "ریلز", "refs": refs, "options": {"preview": False, "variants": 1}})
        self.assertTrue(Job.objects.get(pk=r.json()["job_id"]).result["ai"]["enabled"])
        self.assertTrue(asked)

    def test_draft_lifetime_follows_the_store_setting(self):
        from datetime import timedelta
        from django.utils import timezone
        self.call("put", "/editor/settings/", {"draft_days": 2})
        res = self.run_plain(variants=1)
        self.assertEqual(res["draft_days"], 2)
        d = DirectorDraft.objects.get(pk=res["drafts"][0]["id"])
        self.assertAlmostEqual((d.expires_at - timezone.now()).total_seconds(), timedelta(days=2).total_seconds(), delta=120)
        listing = self.call("get", "/editor/director/drafts/").json()
        self.assertEqual((listing["draft_days"], listing["drafts"][0]["days_left"]), (2, 2))

    def test_drafts_list_open_once_and_delete(self):
        res = self.run_plain()
        listing = self.call("get", "/editor/director/drafts/").json()
        self.assertEqual({d["key"] for d in listing["drafts"]}, {"a", "b", "c"})
        self.assertTrue(all(d["days_left"] == 7 and d["project_id"] is None for d in listing["drafts"]))
        a = next(d for d in listing["drafts"] if d["key"] == "a")
        r = self.call("post", f"/editor/director/drafts/{a['id']}/open/")
        self.assertEqual(r.status_code, 200, r.content)
        pid = r.json()["project_id"]
        project = VideoProject.objects.get(pk=pid)
        self.assertEqual(project.data["director"]["variant"], "a")
        self.assertEqual(project.data["tracks"], DirectorDraft.objects.get(pk=a["id"]).data["tracks"])           # nothing lost on the way
        self.assertEqual(self.call("post", f"/editor/director/drafts/{a['id']}/open/").json()["project_id"], pid)     # a double click: same project
        self.assertEqual(VideoProject.objects.count(), 1)
        self.assertEqual({d["key"] for d in self.call("get", "/editor/director/drafts/").json()["drafts"]}, {"b", "c"})   # opened ones leave the list
        b = next(d for d in listing["drafts"] if d["key"] == "b")
        self.assertEqual(self.call("delete", f"/editor/director/drafts/{b['id']}/").status_code, 204)
        self.assertEqual(self.call("delete", f"/editor/director/drafts/{b['id']}/").status_code, 404)
        self.assertEqual(self.call("delete", f"/editor/director/drafts/{a['id']}/").status_code, 404)          # an opened one is not a draft any more
        self.assertEqual(len(self.call("get", "/editor/director/drafts/").json()["drafts"]), 1)
        self.assertTrue(VideoProject.objects.filter(pk=pid).exists())
        other = User.objects.create_user("draft-intruder", password="x")
        self.client.force_login(other)
        c = next(d for d in listing["drafts"] if d["key"] == "c")
        self.assertIn(self.call("post", f"/editor/director/drafts/{c['id']}/open/").status_code, (403, 404))
        self.assertIn(self.call("delete", f"/editor/director/drafts/{c['id']}/").status_code, (403, 404))
        self.assertEqual(DirectorDraft.objects.filter(pk=c["id"]).count(), 1)
        self.assertEqual(res["draft_days"], 7)

    def test_unopened_drafts_expire_by_age_and_an_opened_project_never_does(self):
        from datetime import timedelta
        from django.utils import timezone
        from services.editing.director import drafts as drafts_mod
        self.run_plain()
        mine = list(DirectorDraft.objects.filter(store=self.store).order_by("key"))
        opened = drafts_mod.promote(mine[0])
        edited = VideoProject.objects.create(store=self.store, title="ویرایش‌شده", data=self.project_data())
        old = timezone.now() - timedelta(days=30)
        VideoProject.objects.filter(pk__in=[opened.pk, edited.pk]).update(created_at=old, updated_at=old)         # ancient, but a real project
        DirectorDraft.objects.filter(pk=mine[1].pk).update(expires_at=timezone.now() - timedelta(minutes=1))     # one unopened draft is past its window
        out = drafts_mod.purge(self.store)
        self.assertEqual(out["expired"], 1)
        self.assertEqual(set(DirectorDraft.objects.filter(store=self.store).values_list("key", flat=True)), {"a", "c"})
        self.assertEqual(VideoProject.objects.count(), 2, "purging must never delete a real project")
        # the pointer of an opened draft is kept for a day (a double click), then it goes; the project stays; the other unopened draft is still inside its 7 days
        out = drafts_mod.purge(self.store, now=timezone.now() + timedelta(days=2))
        self.assertEqual((out["pointers"], out["expired"]), (1, 0))
        self.assertEqual(set(DirectorDraft.objects.filter(store=self.store).values_list("key", flat=True)), {"c"})
        self.assertTrue(VideoProject.objects.filter(pk=opened.pk).exists() and VideoProject.objects.filter(pk=edited.pk).exists())
        out = drafts_mod.purge(self.store, now=timezone.now() + timedelta(days=8))
        self.assertEqual(out["expired"], 1)
        self.assertEqual(VideoProject.objects.count(), 2)

    def test_nothing_expires_before_its_window_and_the_listing_purges_lazily(self):
        from datetime import timedelta
        from django.utils import timezone
        self.run_plain(variants=2)
        DirectorDraft.objects.filter(store=self.store).update(expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(len(self.call("get", "/editor/director/drafts/").json()["drafts"]), 2)
        DirectorDraft.objects.filter(store=self.store).update(expires_at=timezone.now() - timedelta(seconds=5))
        self.assertEqual(self.call("get", "/editor/director/drafts/").json()["drafts"], [])
        self.assertEqual(DirectorDraft.objects.count(), 0)

    def test_the_oldest_unopened_drafts_expire_beyond_the_cap(self):
        from datetime import timedelta
        from django.utils import timezone
        from services.editing.director import drafts as drafts_mod
        base = {"tracks": [], "director": {"run": "x"}}
        for i in range(drafts_mod.MAX_DRAFTS + 3):
            d = DirectorDraft.objects.create(store=self.store, run=f"r{i}", key="a", title=f"d{i}", data=base, expires_at=timezone.now() + timedelta(days=5))
            DirectorDraft.objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(minutes=drafts_mod.MAX_DRAFTS + 3 - i))
        out = drafts_mod.purge(self.store)
        self.assertEqual(out["over_cap"], 3)
        self.assertEqual(DirectorDraft.objects.filter(store=self.store).count(), drafts_mod.MAX_DRAFTS)
        self.assertFalse(DirectorDraft.objects.filter(title="d0").exists())                  # the oldest went first
        self.assertTrue(DirectorDraft.objects.filter(title=f"d{drafts_mod.MAX_DRAFTS + 2}").exists())

    def test_the_cap_is_a_store_setting_and_purge_follows_it(self):
        from datetime import timedelta
        from django.utils import timezone
        from services.editing.director import drafts as drafts_mod
        self.call("put", "/editor/settings/", {"max_drafts": 12})
        base = {"tracks": [], "director": {"run": "x"}}
        for i in range(15):
            d = DirectorDraft.objects.create(store=self.store, run=f"r{i}", key="a", title=f"d{i}", data=base, expires_at=timezone.now() + timedelta(days=5))
            DirectorDraft.objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(minutes=20 - i))
        out = drafts_mod.purge(self.store)
        self.assertEqual(out["over_cap"], 3)
        self.assertEqual(DirectorDraft.objects.filter(store=self.store).count(), 12)
        self.assertEqual(self.call("get", "/editor/director/drafts/").json()["max_drafts"], 12, "the list tells the panel the store's own cap")

    def test_the_shared_preview_file_goes_only_when_the_last_draft_of_its_run_goes(self):
        res = self.run_plain(variants=2)
        draft = DirectorDraft.objects.get(pk=res["drafts"][0]["id"])
        folder = Path(TEMP_MEDIA) / "generated" / "editing" / f"director_{draft.job_id}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "preview.mp4").write_bytes(b"x" * 2048)
        ids = [d["id"] for d in res["drafts"]]
        self.assertEqual(self.call("delete", f"/editor/director/drafts/{ids[0]}/").status_code, 204)
        self.assertTrue((folder / "preview.mp4").exists(), "the second draft still needs the preview")
        self.assertEqual(self.call("delete", f"/editor/director/drafts/{ids[1]}/").status_code, 204)
        self.assertFalse(folder.exists())

    def test_a_rerun_never_overwrites_a_project_the_owner_opened(self):
        refs = [f"video:{self.up1.pk}", f"video:{self.up2.pk}"]
        res = self.run_plain(variants=1)
        v = res["variants"][0]
        opened = self.call("post", f"/editor/director/drafts/{v['draft_id']}/open/").json()["project_id"]
        before = json.dumps(VideoProject.objects.get(pk=opened).data, sort_keys=True)
        steps = [{"id": s["id"], "tool": s["tool"], "params": s["params"], "why": s["why"], "on": s["tool"] != "end_card"} for s in v["plan"] if not s["id"].startswith("f")]
        with patch("apps.content.views_director.dispatch_job", side_effect=run_inline), \
                patch("services.editing.captions.status", return_value={"node": False, "local": False, "ok": False, "message": captions.OFFLINE_MESSAGE}):
            r = self.call("post", "/editor/director/rerun/", {"brief": res["brief"], "steps": steps, "refs": refs, "variant": "a", "draft_id": v["draft_id"]})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(json.dumps(VideoProject.objects.get(pk=opened).data, sort_keys=True), before)
        self.assertNotEqual(job.result["variants"][0]["draft_id"], v["draft_id"])                 # it became a NEW draft instead
        self.assertEqual(len(self.call("get", "/editor/director/drafts/").json()["drafts"]), 1)

    # ------------------------------------------------------------ migrating the old auto-created projects
    def test_migration_moves_only_untouched_director_projects_after_writing_a_backup(self):
        import io
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        data = {**self.project_data(), "director": {"run": "old1", "variant": "a", "critique": {"score": 83}, "plan": [], "prompt": "x"}}
        untouched = VideoProject.objects.create(store=self.store, title="دست‌نخورده", data=data)
        edited = VideoProject.objects.create(store=self.store, title="ویرایش‌شده", data=data)
        VideoProject.objects.filter(pk=edited.pk).update(updated_at=timezone.now() + timedelta(minutes=10))
        rendered = VideoProject.objects.create(store=self.store, title="رندرشده", data=data, state=VideoProject.State.READY)
        snap = VideoProject.objects.create(store=self.store, title="نسخه‌دار", data=data)
        (Path(TEMP_MEDIA) / "generated" / "editing" / f"project_{snap.pk}" / "versions").mkdir(parents=True, exist_ok=True)
        plain = VideoProject.objects.create(store=self.store, title="معمولی", data=self.project_data())
        out = io.StringIO()
        call_command("director_drafts", "migrate", "--dry-run", stdout=out)
        self.assertIn("candidates: 1", out.getvalue())
        self.assertEqual(DirectorDraft.objects.count(), 0)                                        # a dry run changes nothing
        backup = Path(TEMP_MEDIA) / "backup" / "projects.json"
        out = io.StringIO()
        call_command("director_drafts", "migrate", "--backup", str(backup), stdout=out)
        self.assertIn("moved 1", out.getvalue())
        saved = json.loads(backup.read_text(encoding="utf-8"))
        self.assertEqual([x["id"] for x in saved], [untouched.pk])
        self.assertEqual(saved[0]["data"]["director"]["run"], "old1")
        self.assertFalse(VideoProject.objects.filter(pk=untouched.pk).exists())
        for keep in (edited, rendered, snap, plain):
            self.assertTrue(VideoProject.objects.filter(pk=keep.pk).exists(), keep.title)
        d = DirectorDraft.objects.get()
        self.assertEqual((d.title, d.score, d.key, d.run), ("دست‌نخورده", 83, "a", "old1"))
        self.assertEqual(d.data["tracks"], data["tracks"])
        self.assertGreater(d.expires_at, timezone.now() + timedelta(days=6))                       # a full fresh window from the migration
        out = io.StringIO()
        call_command("director_drafts", "migrate", "--backup", str(backup), stdout=out)
        self.assertIn("nothing to do", out.getvalue())                                            # idempotent
        out = io.StringIO()
        call_command("director_drafts", "stats", stdout=out)
        self.assertIn("drafts=1", out.getvalue())

    def test_migration_refuses_to_run_without_a_backup_path(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        VideoProject.objects.create(store=self.store, title="x", data={**self.project_data(), "director": {"run": "o"}})
        with self.assertRaises(CommandError):
            call_command("director_drafts", "migrate")
        self.assertEqual(VideoProject.objects.count(), 1)


    # ------------------------------------------------------------ scene-cut detection (round 4)
    def two_scene_video(self, name, cut_at=2.0, total=5.0):
        import subprocess
        path = Path(TEMP_MEDIA) / "uploads/videos" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", f"color=c=red:s=160x90:r=10:d={cut_at}", "-f", "lavfi", "-i", f"color=c=blue:s=160x90:r=10:d={total - cut_at}",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
        return UploadedVideo.objects.create(store=self.store, title="دو صحنه", video=f"uploads/videos/{name}", state="READY", duration=total, has_audio=False)

    def test_scene_detection_finds_the_cut_and_stays_quiet_when_there_is_none(self):
        up = self.two_scene_video("scenes_cut.mp4")
        r = self.call("post", "/editor/scenes/", {"ref": f"video:{up.pk}"})
        self.assertEqual(r.status_code, 200, r.content)
        cuts = r.json()["cuts"]
        self.assertEqual(len(cuts), 1, cuts)
        self.assertAlmostEqual(cuts[0], 2.0, delta=0.25)
        # a window that excludes the cut finds nothing; the times are always SOURCE seconds
        self.assertEqual(self.call("post", "/editor/scenes/", {"ref": f"video:{up.pk}", "start": 2.5, "end": 5}).json()["cuts"], [])
        late = self.call("post", "/editor/scenes/", {"ref": f"video:{up.pk}", "start": 1, "end": 4}).json()["cuts"]
        self.assertEqual(len(late), 1)
        self.assertAlmostEqual(late[0], 2.0, delta=0.25)
        plain = self.call("post", "/editor/scenes/", {"ref": f"video:{self.up1.pk}"}).json()
        self.assertEqual(plain["cuts"], [])                                       # the test pattern never cuts

    def test_scene_detection_validates_and_is_private(self):
        up = self.two_scene_video("scenes_cut2.mp4")
        self.assertEqual(self.call("post", "/editor/scenes/", {"ref": "video:424242"}).status_code, 404)
        self.assertEqual(self.call("post", "/editor/scenes/", {"ref": f"video:{up.pk}", "start": "x"}).status_code, 400)
        self.assertEqual(self.call("post", "/editor/scenes/", {"ref": f"video:{up.pk}", "start": 4.9, "end": 5}).status_code, 400)
        self.assertEqual(self.call("post", "/editor/scenes/", {"ref": f"video:{up.pk}", "sensitivity": "weird"}).status_code, 200)    # unknown level = normal
        other = User.objects.create_user("scene-intruder", password="x")
        self.client.force_login(other)
        self.assertIn(self.call("post", "/editor/scenes/", {"ref": f"video:{up.pk}"}).status_code, (403, 404))

    def test_the_cuts_are_close_together_only_once(self):
        from services.editing import scenes
        self.assertGreater(scenes.SENSITIVITY["low"], scenes.SENSITIVITY["normal"], "less sensitive = a higher bar")
        self.assertGreater(scenes.SENSITIVITY["normal"], scenes.SENSITIVITY["high"])


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class AudioUploadTests(TestCase):
    """«آپلودِ صدای ضبط‌شده»: a phone recording becomes a library sound the editor can use."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (shutil.which(FFMPEG) or shutil.which("ffmpeg")):
            return
        import subprocess
        cls.dir = Path(tempfile.mkdtemp(prefix="nm-upload-"))
        cls.m4a = cls.dir / "voice.m4a"
        subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-c:a", "aac", str(cls.m4a)], check=True, capture_output=True)
        cls.junk = cls.dir / "x.txt"
        cls.junk.write_text("not audio")
        cls.bad = cls.dir / "fake.mp3"
        cls.bad.write_bytes(b"\x00" * 5000)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "dir", TEMP_MEDIA), ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "m4a"):
            self.skipTest("ffmpeg نیست")
        self.owner = User.objects.create_user("up-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه آپلود")
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.pk}/audio/assets/upload/"

    def send(self, path, **extra):
        with open(path, "rb") as f:
            return self.client.post(self.url, {"file": f, **extra})

    def test_a_phone_recording_becomes_a_saved_ready_library_sound_the_bin_lists(self):
        with patch("apps.compute.services.data_root", return_value=Path(TEMP_MEDIA) / "data"):
            r = self.send(self.m4a, title="گویندگیِ من", kind="speech")
            self.assertEqual(r.status_code, 201, r.content)
            body = r.json()
            self.assertEqual((body["kind"], body["status"], body["saved"]), ("SPEECH", "READY", True))
            self.assertGreater(body["duration"], 1.5)
            from . import editor_project
            item = editor_project.describe(self.store, f"audio:{body['id']}")
            self.assertEqual(item["kind"], "audio")
            self.assertIn(f"audio:{body['id']}", [x["ref"] for x in editor_project.bin_items(self.store)["audio"]])

    def test_bad_files_get_persian_refusals(self):
        with patch("apps.compute.services.data_root", return_value=Path(TEMP_MEDIA) / "data"):
            self.assertEqual(self.send(self.junk).status_code, 400)
            r = self.send(self.bad)
            self.assertEqual(r.status_code, 400)
            self.assertIn("خوانده نشد", r.json()["error"]["message"])
            self.assertEqual(self.client.post(self.url, {}).status_code, 400)
        other = User.objects.create_user("up-intruder", password="x")
        self.client.force_login(other)
        self.assertIn(self.send(self.m4a).status_code, (403, 404))
