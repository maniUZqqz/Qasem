"""The director's API: catalogue, one-click tools (`director/apply`), auto-reframe, project versions, and the whole job
(analyse → recipes → three real VideoProject rows) with the model mocked. Real ffmpeg on tiny clips; no Metis, no node."""
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
from .models import UploadedVideo, VideoProject
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

    def test_run_builds_three_valid_editable_projects_without_ai_and_explains_what_was_skipped(self):
        r = self.run_director({"prompt": "ریلز معرفی چای ۱۵ ثانیه‌ای", "refs": [f"video:{self.up1.pk}", f"video:{self.up2.pk}"], "options": {"use_ai": False, "preview": False}})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        result = job.result
        self.assertEqual({p["key"] for p in result["projects"]}, {"a", "b", "c"})
        self.assertEqual(result["brief"]["platform"], "reels")
        self.assertEqual(result["brief"]["duration"], 15)
        text = " ".join(result["degraded"])
        self.assertIn("هوش مصنوعی", text) if result["ai"]["enabled"] else None
        self.assertTrue(any("زیرنویس" in d or "گفتار" in d for d in result["degraded"]), result["degraded"])   # ASR was off: said so
        for row in result["projects"]:
            project = VideoProject.objects.get(pk=row["id"])
            self.assertEqual(project.data["director"]["variant"], row["key"])
            self.assertTrue(project.data["director"]["plan"])
            verdict = editor_project.check(self.store, project.data)
            self.assertTrue(verdict["ok"], (row, verdict))
            self.assertLessEqual(verdict["length"], 22)
        for v in result["variants"]:
            self.assertTrue(all(s["text"] and s["title"] for s in v["plan"]))
            self.assertIn("score", v["critique"])

    def test_the_owner_can_switch_a_step_off_and_run_the_plan_again(self):
        refs = [f"video:{self.up1.pk}", f"video:{self.up2.pk}"]
        r = self.run_director({"prompt": "ریلز", "refs": refs, "options": {"use_ai": False, "preview": False, "variants": 1}})
        job = Job.objects.get(pk=r.json()["job_id"])
        res = job.result
        v = res["variants"][0]
        steps = [{"id": s["id"], "tool": s["tool"], "params": s["params"], "why": s["why"], "on": s["tool"] != "end_card"} for s in v["plan"] if not s["id"].startswith("f")]
        with patch("apps.content.views_director.dispatch_job", side_effect=run_inline), \
                patch("services.editing.captions.status", return_value={"node": False, "local": False, "ok": False, "message": captions.OFFLINE_MESSAGE}):
            r2 = self.call("post", "/editor/director/rerun/", {"brief": res["brief"], "steps": steps, "refs": refs, "variant": "a", "project_id": v["project_id"]})
        self.assertEqual(r2.status_code, 202, r2.content)
        job2 = Job.objects.get(pk=r2.json()["job_id"])
        self.assertEqual(job2.state, Job.State.COMPLETED, job2.error)
        again = job2.result["variants"][0]
        self.assertEqual(again["project_id"], v["project_id"])                  # the same project was replaced, not duplicated
        self.assertTrue(any(s.get("skipped") for s in again["plan"] if s["tool"] == "end_card"))
        self.assertFalse(next(i for i in again["critique"]["items"] if i["key"] == "cta")["ok"])
        self.assertEqual(VideoProject.objects.filter(store=self.store).count(), 1)

    def test_a_model_that_answers_improves_the_brief_and_one_that_fails_is_reported(self):
        refs = [f"video:{self.up1.pk}"]
        info_bad = {"asked": True, "ok": False, "via": "", "model": "", "error_code": "no_credit", "error": "اعتبارِ حسابِ سرویسِ هوش مصنوعی (Metis) تمام شده است (خطای ۴۰۲).",
                    "fell_back": False, "fallback_reason": ""}
        with patch("services.editing.director.ai.call_json", return_value=(None, info_bad)):
            r = self.run_director({"prompt": "ریلز", "refs": refs, "options": {"preview": False, "variants": 1}})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertFalse(job.result["ai"]["ok"])
        self.assertTrue(any("۴۰۲" in d for d in job.result["degraded"]))
        self.assertTrue(job.result["ai"]["needed_for"])
        VideoProject.objects.all().delete()
        good = {"recipe": "sale", "platform": "story", "duration": 12, "pace": "fast", "title": "چای تازه", "subtitle": "", "cta": "الان بخر", "discount": 20,
                "captions": True, "music": False, "look": "vivid", "hook_ref": "", "order": [], "notes_fa": ""}
        info_ok = {**info_bad, "ok": True, "error": "", "error_code": "", "via": "node", "model": "gemma3:12b"}

        def fake(store, **kw):
            return (good, info_ok) if kw["prompt_id"] == "video_director_brief" else ({"steps": []}, info_ok)
        with patch("services.editing.director.ai.call_json", side_effect=fake):
            r = self.run_director({"prompt": "", "refs": refs, "options": {"preview": False, "variants": 1}})
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

    def test_old_director_projects_are_pruned_but_a_hand_edited_one_is_kept(self):
        from . import tasks_director
        keep = VideoProject.objects.create(store=self.store, title="ویرایش‌شده", data={"director": {"run": "x"}, **self.project_data()})
        VideoProject.objects.filter(pk=keep.pk).update(created_at=keep.created_at.replace(year=2025), updated_at=keep.updated_at)     # edited long after creation
        for i in range(tasks_director.MAX_PROJECTS - 1):
            VideoProject.objects.create(store=self.store, title=f"d{i}", data={"director": {"run": "old"}, **self.project_data()})
        removed = tasks_director.prune_director_projects(self.store, 3)
        self.assertEqual(removed, 3)
        self.assertTrue(VideoProject.objects.filter(pk=keep.pk).exists())

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
