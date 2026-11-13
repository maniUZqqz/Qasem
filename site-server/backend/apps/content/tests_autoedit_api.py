"""The automatic edit's API: the pause review (ask / remember), every network's size, the polish run and the command that queues the owner's re-run.
Real ffmpeg on tiny clips; no node, no model."""
import atexit
import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import silence_intel
from services.tests_autoedit_audio import SR, mux, synth_speech, write_wav
from services.video.ffmpeg import FFMPEG

from .models import DirectorDraft, UploadedVideo, VideoProject

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-autoedit-api-")
TEMP_DATA = tempfile.mkdtemp(prefix="nm-autoedit-data-")
atexit.register(shutil.rmtree, TEMP_MEDIA, ignore_errors=True)
atexit.register(shutil.rmtree, TEMP_DATA, ignore_errors=True)


def run_inline(job, task, *args, **kwargs):
    task(*args, **kwargs)
    return None


def talk_audio():
    """A talker with known pauses: 4 s speech · 1.5 s pause · 3 s · 0.35 s · 3 s · 5 s · 3 s = 19.85 s (the detector widens each gap by about half a second: soft word endings)."""
    parts = [synth_speech(4, seed=21), np.zeros(int(1.5 * SR), np.float32), synth_speech(3, seed=22), np.zeros(int(0.35 * SR), np.float32),
             synth_speech(3, seed=23), np.zeros(int(5.0 * SR), np.float32), synth_speech(3, seed=24)]
    return np.concatenate(parts)


@override_settings(MEDIA_ROOT=TEMP_MEDIA, NM_DATA_DIR=Path(TEMP_DATA))
class AutoEditApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (shutil.which(FFMPEG) or shutil.which("ffmpeg")):
            return
        root = Path(TEMP_MEDIA) / "uploads/videos"
        root.mkdir(parents=True, exist_ok=True)
        audio = talk_audio()
        cls.seconds = len(audio) / SR
        cls.talk = mux(root / "ae_talk.mp4", write_wav(root / "ae_talk.wav", audio), cls.seconds)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        shutil.rmtree(TEMP_DATA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not hasattr(self, "talk"):
            self.skipTest("ffmpeg نیست")
        shutil.rmtree(Path(TEMP_MEDIA) / "generated", ignore_errors=True)
        shutil.rmtree(Path(TEMP_DATA) / "autoedit", ignore_errors=True)        # the remembered answers belong to one test, not to the class
        self.owner = User.objects.create_user("ae-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه تدوین")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up = UploadedVideo.objects.create(store=self.store, title="main.mp4", video="uploads/videos/ae_talk.mp4", state="READY", duration=self.seconds, has_audio=True)
        self.ref = f"video:{self.up.pk}"

    def call(self, method, url, body=None):
        fn = getattr(self.client, method)
        return fn(self.base + url) if body is None else fn(self.base + url, json.dumps(body), content_type="application/json")

    # ------------------------------------------------------------ the pause review
    def test_the_review_decides_what_is_certain_and_asks_what_is_not(self):
        r = self.call("get", f"/autoedit/silences/?ref={self.ref}")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        between = lambda lo, hi: next(s for s in d["silences"] if lo <= s["len"] <= hi and not s["edge"])      # noqa: E731 - the detector widens a gap by ≈ 0.3–0.6 s
        self.assertEqual(between(4.2, 6.0)["decision"], "cut", "5 s over a still picture is dead air")
        self.assertEqual(between(0.4, 0.89)["decision"], "shorten")
        asked = [q for q in d["questions"] if 1.4 <= q["len"] <= 2.6]
        self.assertTrue(asked, d["questions"])
        self.assertIn(asked[0]["suggest"], ("keep", "shorten"))
        self.assertTrue(asked[0]["reason"])
        self.assertEqual(d["words"] in ("off", "waiting", "later", "ready"), True)
        self.assertGreater(d["removed_seconds"], 4.0)

    def test_an_answer_is_remembered_and_changes_the_cuts(self):
        first = self.call("get", f"/autoedit/silences/?ref={self.ref}").json()
        q = first["questions"][0]
        r = self.call("post", "/autoedit/silences/", {"ref": self.ref, "answers": [{"start": q["start"], "end": q["end"], "action": "keep"}]})
        self.assertEqual(r.status_code, 200, r.content)
        again = self.call("get", f"/autoedit/silences/?ref={self.ref}").json()
        self.assertEqual(again["answered"], 1)
        self.assertEqual(len(again["questions"]), len(first["questions"]) - 1)
        row = next(s for s in again["silences"] if abs(s["start"] - q["start"]) < 0.01)
        self.assertEqual((row["action"], row["answered"]), ("keep", True))
        self.assertLess(again["removed_seconds"], first["removed_seconds"] + 0.01)

    def test_the_answers_are_per_store_and_a_foreign_ref_is_refused(self):
        other = Store.objects.create(owner=User.objects.create_user("ae-other", password="x"), name="دیگری")
        self.client.force_login(other.owner)
        r = self.client.get(f"/api/v1/stores/{other.pk}/autoedit/silences/?ref={self.ref}")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/api/v1/stores/{other.pk}/autoedit/silences/", json.dumps({"ref": self.ref, "answers": []}), content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_bad_requests_are_clear(self):
        self.assertEqual(self.call("get", "/autoedit/silences/").status_code, 400)
        self.assertEqual(self.call("post", "/autoedit/silences/", {"ref": self.ref}).status_code, 400)
        self.assertEqual(self.call("get", "/autoedit/silences/?ref=video:99999").status_code, 400)

    def test_the_upload_edit_uses_the_decisions_not_every_silence(self):
        """The classic upload flow: `trim_silence` cuts what the review decided; the doubtful pause stays (tightened) until the owner answers."""
        from services.editing import agent

        work = Path(TEMP_MEDIA) / "generated" / "editing" / "upload_x"
        work.mkdir(parents=True, exist_ok=True)
        plan = agent.plan(self.talk, work, mode=agent.MANUAL, operations=[{"tool": "trim_silence", "params": {"min_silence": 0.6, "keep": 0.15}}],
                          store=self.store, silence_ref=self.ref)
        self.assertIsNotNone(plan.silence)
        self.assertTrue(plan.silence["questions"])
        removed = sum(s.length for s in plan.edl.keep) - self.seconds
        self.assertLess(sum(s.length for s in plan.edl.keep), self.seconds - 3.0)
        summary = agent.silence_summary(plan.silence)
        self.assertTrue(summary["questions"])


    # ------------------------------------------------------------ the light before/after
    def dark_upload(self):
        root = Path(TEMP_MEDIA) / "uploads/videos"
        out = root / "ae_dark.mp4"
        if not out.exists():
            import subprocess

            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=12:d=4,eq=brightness=-0.28:contrast=0.7", "-pix_fmt", "yuv420p", str(out)],
                           check=True, capture_output=True)
        return UploadedVideo.objects.create(store=self.store, title="تاریک", video="uploads/videos/ae_dark.mp4", state="READY", duration=4.0, has_audio=False)

    def test_the_light_preview_brightens_a_dark_shot_and_leaves_a_good_one(self):
        import base64

        import cv2

        def mean_luma(data_url):
            raw = base64.b64decode(data_url.split(",", 1)[1])
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
            return float(img.mean())

        dark = self.dark_upload()
        r = self.call("get", f"/autoedit/look-preview/?ref=video:{dark.pk}&t=2")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertTrue(d["changed"], d)
        self.assertGreater(mean_luma(d["after"]), mean_luma(d["before"]) + 6, "the corrected frame is brighter than the shot")
        self.assertTrue(d["note"])
        self.assertEqual(self.call("get", "/autoedit/look-preview/?ref=video:99999&t=1").status_code, 400)
        self.assertEqual(self.call("get", "/autoedit/look-preview/").status_code, 400)

    def test_the_light_preview_leaves_a_recorded_phone_screen_alone_like_the_edit_does(self):
        """The owner's own upload is a phone screen recorded inside a landscape frame: the polish run does not touch its light, so the
        before/after must not promise a correction either (it used to show «darker, cold cast corrected» for the black bars + app screen)."""
        import subprocess

        root = Path(TEMP_MEDIA) / "uploads/videos"
        out = root / "ae_screen.mp4"
        if not out.exists():
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=100x180:r=12:d=4,eq=brightness=-0.2:contrast=0.7,pad=320:180:110:0:black",
                            "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True)
        row = UploadedVideo.objects.create(store=self.store, title="ضبطِ صفحه", video="uploads/videos/ae_screen.mp4", state="READY", duration=4.0, has_audio=False)
        r = self.call("get", f"/autoedit/look-preview/?ref=video:{row.pk}&t=2")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertFalse(d["changed"], d)
        self.assertIn("ضبطِ صفحه", d["note"])
        self.assertEqual(d["before"], d["after"])

    # ------------------------------------------------------------ sizes
    def test_the_size_catalogue(self):
        d = self.call("get", "/autoedit/sizes/").json()
        self.assertIn("ig_reel", {s["key"] for s in d["sizes"]})
        self.assertTrue(set(d["default"]) <= {s["key"] for s in d["sizes"]})

    def project(self):
        return {"format": {"width": 1920, "height": 1080, "fps": 12, "preset": "wide"}, "tracks": [
            {"id": "t1", "kind": "video", "name": "تصویر ۱", "muted": False, "locked": False, "clips": [
                {"id": "c1", "type": "media", "ref": self.ref, "label": "main", "kind": "video", "at": 0, "start": 0, "end": 10, "src": self.seconds, "opacity": 1, "x": 0, "y": 0,
                 "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": True, "has_audio": True, "effects": [], "transition": None}]},
            {"id": "t2", "kind": "audio", "name": "گفتار", "role": "speech", "muted": False, "locked": False, "clips": []},
            {"id": "t3", "kind": "audio", "name": "موسیقی", "role": "music", "muted": False, "locked": False, "clips": []}],
            "global_ops": [], "markers": [], "inout": None}

    def test_one_project_becomes_one_project_and_one_export_per_network(self):
        project = VideoProject.objects.create(store=self.store, title="گفت‌وگو", data=self.project())
        sent = []
        with patch("apps.content.views_autoedit.dispatch_job", side_effect=lambda job, task, *a, **k: sent.append((job, a)) or None):
            r = self.call("post", f"/editor/projects/{project.pk}/sizes/", {"sizes": ["ig_reel", "ig_post", "yt_wide", "nope"]})
        self.assertEqual(r.status_code, 202, r.content)
        out = r.json()
        self.assertEqual([j["size"] for j in out["jobs"]], ["ig_reel", "ig_post", "yt_wide"])
        self.assertEqual(len(sent), 3)
        made = {j["size"]: VideoProject.objects.get(pk=j["project_id"]) for j in out["jobs"]}
        self.assertEqual((made["ig_reel"].data["format"]["width"], made["ig_reel"].data["format"]["height"]), (1080, 1920))
        self.assertEqual((made["ig_post"].data["format"]["width"], made["ig_post"].data["format"]["height"]), (1080, 1350))
        self.assertEqual(made["yt_wide"].data["format"]["width"], 1920)
        self.assertEqual(made["ig_reel"].data["export"]["preset"], "reels")
        self.assertIn("ریلز", made["ig_reel"].title)
        self.assertEqual(Job.objects.filter(store=self.store, context__what="project").count(), 3)
        project.refresh_from_db()
        self.assertEqual(project.data["format"]["preset"], "wide", "the source project is untouched")

    def test_no_sizes_is_a_clear_error(self):
        project = VideoProject.objects.create(store=self.store, title="x", data=self.project())
        self.assertEqual(self.call("post", f"/editor/projects/{project.pk}/sizes/", {"sizes": ["nope"]}).status_code, 400)

    # ------------------------------------------------------------ the polish run and the owner's re-run
    def run_polish(self, **body):
        """The polish job runs inline; the renders it hands over to are only RECORDED (`self.sent` = [(job, task name, args)]), never started."""
        self.sent = []

        def record(job, task, *a, **k):
            self.sent.append((job, getattr(task, "__name__", str(task)), a))
            return None

        def route(job, task, *a, **k):
            """views_autoedit starts the polish job (inline here) AND the per-network renders (recorded)."""
            if getattr(task, "__name__", "") == "render_project_task":
                return record(job, task, *a, **k)
            return run_inline(job, task, *a, **k)

        with patch("apps.content.views_autoedit.dispatch_job", side_effect=route), patch("apps.content.tasks_director.dispatch_job", side_effect=record):
            return self.call("post", f"/videos/{self.up.pk}/autoedit/", body)

    def test_the_polish_run_makes_an_editable_draft_with_the_polish_plan(self):
        r = self.run_polish()
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        draft = DirectorDraft.objects.filter(store=self.store).latest("id")
        self.assertEqual(draft.data["director"]["brief"]["recipe"], "polish")
        tools = [s["tool"] for s in draft.data["director"]["plan"]]
        for needed in ("add_clip", "smart_cuts", "auto_look", "auto_mix", "set_loudness"):
            self.assertIn(needed, tools)
        self.assertNotIn("end_card", tools)
        cuts = next(s for s in draft.data["director"]["plan"] if s["tool"] == "smart_cuts")
        self.assertTrue(cuts.get("ok"), cuts)
        self.assertIn("مکثِ مبهم", cuts["message"], "the doubtful pause is left for the owner")

    def test_the_command_queues_the_recent_upload_once_and_parks_when_the_node_is_off(self):
        out = StringIO()
        call_command("queue_autoedit_rerun", "--dry-run", "--min-seconds", "5", stdout=out)
        self.assertIn(f"upload {self.up.pk}", out.getvalue())
        self.assertEqual(Job.objects.filter(context__origin="autoedit-rerun").count(), 0)
        with patch("apps.content.management.commands.queue_autoedit_rerun.dispatch_job", side_effect=lambda job, task, *a, **k: None) as fake:
            call_command("queue_autoedit_rerun", "--min-seconds", "5", stdout=StringIO())
            call_command("queue_autoedit_rerun", "--min-seconds", "5", stdout=StringIO())
        self.assertEqual(fake.call_count, 1, "a second run must not queue the same upload twice")
        job = Job.objects.get(context__origin="autoedit-rerun")
        self.assertEqual(job.context["upload_id"], self.up.pk)
        args = fake.call_args[0]
        payload = args[3]
        self.assertTrue(payload["options"]["require_words"])
        self.assertFalse(payload["options"]["use_ai"], "LOCAL_ONLY: no cloud AI")
        self.assertEqual(payload["options"]["override"]["recipe"], "polish")

    def test_a_run_that_needs_the_words_parks_itself_while_the_node_is_off(self):
        """require_words + a registered-but-offline processing server → the job is parked, not failed and not half-done."""
        from services.editing import captions

        def waiting(ref, a, b):
            raise captions.waiting_error()

        from services.editing.director import loop
        from services.tests_autoedit_quality import PolishRecipeTests
        from services.tests_director import FakeAI

        t = PolishRecipeTests()
        with self.assertRaises(captions.CaptionsUnavailable) as caught:
            loop.run("", [t.TALK], t.ctx(words=waiting), options=loop.Options(variants=1, rounds=0, use_ai=False, preview=False, require_words=True), call=FakeAI(fail="all"))
        self.assertTrue(getattr(caught.exception, "node_waiting", ""))
        done = loop.run("", [t.TALK], t.ctx(words=waiting), options=loop.Options(variants=1, rounds=0, use_ai=False, preview=False, require_words=False), call=FakeAI(fail="all"))
        self.assertEqual(done["brief"]["recipe"], "polish", "without require_words the run goes on with energy-based cuts")

    # ------------------------------------------------------------ the OUTPUT: the run ends in a render, not in a draft only
    def test_the_polish_run_hands_its_result_to_the_final_render(self):
        r = self.run_polish()
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        out = job.result["delivered"]
        self.assertEqual(len(out["renders"]), 1, out)
        project = VideoProject.objects.get(pk=out["project_id"])
        self.assertEqual(project.state, VideoProject.State.RENDERING)
        render_job, name, args = self.sent[-1]
        self.assertEqual(name, "render_project_task")
        self.assertEqual(render_job.context["origin"], "autoedit")
        self.assertEqual(render_job.context["quality"], "final")
        self.assertEqual(args[1], project.pk)
        self.assertTrue((Path(TEMP_MEDIA) / args[3]).is_file(), "the render works on a snapshot of the project")
        self.assertEqual(DirectorDraft.objects.get(pk=out["renders"][0]["project_id"] and DirectorDraft.objects.filter(project=project).first().pk).project_id, project.pk,
                         "the draft became the project (and is not rendered twice)")

    def test_deliver_off_leaves_only_the_draft(self):
        r = self.run_polish(deliver=False)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        self.assertNotIn("delivered", job.result)
        self.assertEqual(VideoProject.objects.filter(store=self.store).count(), 0)
        self.assertEqual(self.sent, [])

    def test_the_run_can_deliver_every_network_at_once(self):
        r = self.run_polish(sizes=["ig_reel", "yt_wide", "ig_post"])
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        renders = job.result["delivered"]["renders"]
        self.assertEqual([x["size"] for x in renders], ["ig_reel", "yt_wide", "ig_post"])
        shapes = {x["size"]: VideoProject.objects.get(pk=x["project_id"]).data["format"] for x in renders}
        self.assertEqual((shapes["ig_reel"]["width"], shapes["ig_reel"]["height"]), (1080, 1920))
        self.assertEqual((shapes["ig_post"]["width"], shapes["ig_post"]["height"]), (1080, 1350))
        self.assertEqual(len([s for s in self.sent if s[1] == "render_project_task"]), 3)

    def test_the_caption_mode_of_the_polish_run_reaches_the_project_of_every_network(self):
        r = self.run_polish(sizes=["ig_reel", "yt_wide"], captions="soft")
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        for x in job.result["delivered"]["renders"]:
            self.assertEqual(VideoProject.objects.get(pk=x["project_id"]).data["export"]["captions"], "soft", x["size"])

    def test_without_a_caption_mode_the_projects_say_nothing_so_captions_stay_in_the_picture(self):
        r = self.run_polish(sizes=["ig_reel"])
        job = Job.objects.get(pk=r.json()["job_id"])
        project = VideoProject.objects.get(pk=job.result["delivered"]["renders"][0]["project_id"])
        self.assertNotIn("captions", project.data.get("export") or {})

    def test_a_single_project_can_be_exported_for_a_network_with_separate_subtitles(self):
        project = VideoProject.objects.create(store=self.store, title="گفت‌وگو", data=self.project())
        with patch("apps.content.views_autoedit.dispatch_job", side_effect=lambda job, task, *a, **k: None):
            r = self.call("post", f"/editor/projects/{project.pk}/sizes/", {"sizes": ["ig_reel"], "captions": "soft"})
        self.assertEqual(r.status_code, 202, r.content)
        made = VideoProject.objects.get(pk=r.json()["jobs"][0]["project_id"])
        self.assertEqual(made.data["export"]["captions"], "soft")

    def test_the_queued_run_of_the_command_delivers_too(self):
        with patch("apps.content.management.commands.queue_autoedit_rerun.dispatch_job", side_effect=lambda job, task, *a, **k: None) as fake:
            call_command("queue_autoedit_rerun", "--min-seconds", "5", stdout=StringIO())
        self.assertTrue(fake.call_args[0][3]["options"]["deliver"])

    def test_the_fill_job_renders_after_the_missing_steps_are_in(self):
        """Captions that had to wait for the node are filled in LATER; only then is the draft rendered (so the output has its subtitles)."""
        from services.editing.director import drafts as drafts_mod

        from .tasks_director import director_fill_task

        draft = drafts_mod.create(self.store, run="r1", job_id=None, key="a", title="پیش‌نویس", data=self.project(), score=70, length=10)
        fill = Job.objects.create(store=self.store, type=Job.Type.VIDEO_EDIT, context={"what": "director_fill"})
        sent = []
        with patch("apps.compute.park.gate", return_value=False), patch("apps.content.tasks_director.dispatch_job", side_effect=lambda job, task, *a, **k: sent.append(a) or None):
            director_fill_task(fill.id, {"items": [], "deliver": {"draft": draft.pk, "parent": 1, "sizes": []}})
        fill.refresh_from_db()
        self.assertEqual(fill.state, "COMPLETED", fill.error)
        self.assertEqual(len(fill.result["delivered"]["renders"]), 1, fill.result)
        self.assertEqual(len(sent), 1)

    def test_a_draft_the_owner_already_opened_is_never_rendered_behind_their_back(self):
        from services.editing.director import drafts as drafts_mod

        from .tasks_director import deliver_draft

        draft = drafts_mod.create(self.store, run="r2", job_id=None, key="a", title="باز شده", data=self.project(), score=70, length=10)
        drafts_mod.promote(draft)
        with patch("apps.content.tasks_director.dispatch_job") as fake:
            out = deliver_draft(self.store, {"draft": draft.pk, "parent": 1, "sizes": []})
        self.assertIn("skipped", out)
        fake.assert_not_called()
