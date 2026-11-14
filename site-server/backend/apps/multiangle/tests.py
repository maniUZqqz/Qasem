"""«چندزاویه»: انتخاب‌ها، مسیردهیِ کار به سرورِ پردازش، گردشِ کاملِ API با یک «گرهٔ» شبیه‌سازی‌شده، پروژهٔ ادیتورِ مولتی‌کم، آماده‌سازی و آزمونِ خودکار.

گرهٔ شبیه‌سازی‌شده همان کاری را می‌کند که processing/multiangle_jobs.py می‌کند: کار را با compute.claim می‌گیرد، فایل‌های خروجی (زاویه‌ها،
multicam.mp4، plan.json، پیش‌نمایش‌ها) را در پوشهٔ خروجیِ کار می‌گذارد و compute.finish می‌زند. ffmpeg واقعی فیلم‌های کوچک می‌سازد؛ مدل‌ها لازم نیست.
"""
import json
import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.compute import services as SV
from apps.compute.models import ComputeJob, ComputeNode
from apps.content import editor_project
from apps.content.models import UploadedVideo, VideoProject
from apps.stores.models import Store
from services.editing import multiangle as ma
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG

from . import services
from .models import MultiAngleRun

TMP = Path(tempfile.mkdtemp(prefix="nmma-tests-"))
MEDIA = TMP / "media"
DATA = TMP / "data"
CLIP = TMP / "clip.mp4"
PIC = TMP / "pic.jpg"

READY_CAPS = {
    "multiangle": True, "multiangle_version": "1.0", "kinds": ["multiangle.virtual", "multiangle.move", "multiangle.selftest"], "gpu": "RTX 3060", "code": {"id": "abc123", "version": "1"},
    "multiangle_runtime": {"ok": True, "providers": ["Dml", "CPU"], "gpu": True},
    "multiangle_models": {k: {"state": "installed", "size_mb": 1} for k in ("yunet", "yolos", "depth")},
    "multiangle_ready": {"virtual": True, "move": True, "selftest": True},
}
OLD_CAPS = {"agent": "2.10", "ffmpeg": True, "commands": ["status", "update"]}          # an agent from before the feature that can be updated remotely
EMPTY_CAPS = {
    "multiangle": True, "multiangle_version": "1.0", "kinds": ["multiangle.virtual", "multiangle.move", "multiangle.selftest"], "multiangle_runtime": {"ok": False, "providers": [], "gpu": False, "message": "no python"},
    "multiangle_models": {k: {"state": "missing", "size_mb": 1} for k in ("yunet", "yolos", "depth")},
    "multiangle_ready": {"virtual": False, "move": False, "selftest": False},
}


def setUpModule():
    MEDIA.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x192:rate=25:duration=6", "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(CLIP)], check=True, stdin=subprocess.DEVNULL)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x192:rate=1:duration=1", "-frames:v", "1", str(PIC)], check=True,
                   stdin=subprocess.DEVNULL)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def make_video(path: Path, seconds=4, size="144x256", sound=True):
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}"]
    if sound:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if sound else []) + [str(path)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)


def fake_plan(seconds=4.0):
    return {
        "v": 1, "engine": "multiangle", "mode": "virtual", "version": "1.0",
        "source": {"width": 320, "height": 192, "fps": 25, "duration": seconds, "has_audio": True, "black_bars": False},
        "output": {"width": 144, "height": 256, "fps": 25.0, "format": "reel", "frames": int(seconds * 25), "duration": seconds},
        "subject_mode": "person", "subjects": [{"id": 1, "kind": "person", "coverage": 0.9, "size": 0.6}],
        "angles": [{"key": k, "label": k, "file": f"angle_{k}.mp4", "preview": f"preview_{k}.jpg", "upscale": {"median": m, "max": m + 0.1}}
                   for k, m in (("wide", 1.0), ("medium", 1.2), ("close", 1.9))],
        "skipped_angles": {"two_shot": "one_subject"}, "multicam": "multicam.mp4",
        "cuts": [{"t": 0.0, "angle": "wide"}, {"t": 1.4, "angle": "close"}, {"t": 2.6, "angle": "medium"}],
        "segments": [{"t0": 0.0, "t1": 1.4, "angle": "wide", "reason": "start"}, {"t0": 1.4, "t1": 2.6, "angle": "close", "reason": "pause"},
                     {"t0": 2.6, "t1": seconds, "angle": "medium", "reason": "forced"}],
        "cut_quality": {"segments": 3, "cuts_on_points": 1, "forced": 1, "share_on_points": 0.5, "angles_used": ["close", "medium", "wide"]},
        "audio": {"pauses": 1, "sentences": 0, "beats": 0, "bpm": 0.0, "beat_confidence": 0.0, "cut_points": ["pause"]},
        "warnings": [{"code": "upscale_soft", "angle": "close", "factor": 1.9}, {"code": "angle_skipped", "angle": "two_shot", "why": "one_subject"}],
        "device": {"models": {"yolos": "Dml", "yunet": "CPU"}, "model_fallback": [], "encoder": "nvenc"}, "seconds": 12.5,
    }


def fake_node_finishes(node, kind_prefix="multiangle.", plan=None, files=None, ok=True, error="", meta_extra=None):
    """What the node's agent does: claim, write the answer files, finish."""
    job = SV.claim(node)
    assert job is not None and job.kind.startswith(kind_prefix), job
    plan = plan or fake_plan()
    if ok:
        for a in plan.get("angles", []):
            make_video(SV.output_path(job, a["file"]))
            SV.output_path(job, a["preview"]).write_bytes(b"\xff\xd8\xff\xd9")
        if plan.get("multicam"):
            make_video(SV.output_path(job, plan["multicam"]))
        SV.output_path(job, "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    big = {}
    for p in (SV.job_root(job) / "outputs").iterdir():
        if p.suffix == ".mp4":
            import hashlib
            big[p.name] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    SV.finish(job, node, ok, error=error, meta={"primary": "plan.json", "big": big, **(meta_extra or {})})
    job.refresh_from_db()
    return job


@override_settings(MEDIA_ROOT=str(MEDIA), NM_DATA_DIR=DATA, IS_TEST=True)
class Base(APITestCase):
    caps = READY_CAPS

    def setUp(self):
        self.owner = User.objects.create_user("ma-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ آزمون")
        self.client.force_authenticate(self.owner)
        self.node = ComputeNode.objects.create(name="gpu-1", capabilities=dict(self.caps), last_seen=timezone.now())
        self.clip = self.upload(CLIP, "ویدیوی آزمون")

    def upload(self, path: Path, title: str) -> UploadedVideo:
        up = UploadedVideo(store=self.store, title=title, state="READY", duration=6.0, has_audio=True)
        rel = f"uploads/videos/{path.name}"
        (MEDIA / "uploads" / "videos").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, MEDIA / rel)
        up.video.name = rel
        up.save()
        return up

    def url(self, tail=""):
        return f"/api/v1/stores/{self.store.pk}/multiangle/{tail}"


class OptionsTests(TestCase):
    def test_virtual_options_are_cleaned(self):
        o = services.clean_virtual({"angles": ["close", "wide", "evil", "wide"], "format": "xx", "pace": "turbo", "handheld": 9, "rhythm": "?", "max_upscale": 0})
        self.assertEqual(o["angles"], ["wide", "close"])                       # in the planner's order, only known ones, no repeats
        self.assertEqual((o["format"], o["pace"], o["rhythm"]), ("source", "medium", "auto"))
        self.assertEqual(o["handheld"], 1.0)
        self.assertEqual(o["max_upscale"], 1.1)

    def test_at_least_two_angles(self):
        with self.assertRaises(services.MultiAngleError):
            services.clean_virtual({"angles": ["wide"]})
        with self.assertRaises(services.MultiAngleError):
            services.clean_virtual({"angles": ["nonsense", "x"]})

    def test_move_options_are_cleaned(self):
        o = services.clean_move({"move": "teleport", "amount": 7, "duration": 100, "format": "reel", "ease": "bounce", "relief": 0, "inpaint": 1})
        self.assertEqual((o["move"], o["amount"], o["duration"], o["format"], o["ease"], o["relief"], o["inpaint"]), ("dolly_in", 1.0, 12.0, "reel", "inout", 0.4, True))

    def test_presets_cover_the_core(self):
        p = services.presets()
        core = ma.core()
        self.assertEqual([a["key"] for a in p["angles"]], list(core.ANGLE_ORDER))
        self.assertEqual([m["key"] for m in p["moves"]], list(core.MOVE_ORDER))
        self.assertTrue(all(a["label"] and a["hint"] for a in p["angles"]))
        self.assertTrue(all(m["label"] and m["hint"] for m in p["moves"]))
        self.assertEqual({a["key"] for a in p["angles"] if a["needs_two"]}, {"two_shot", "over_shoulder"})
        self.assertTrue(set(ma.FORMAT_FA) >= set(core.FORMATS))
        self.assertTrue(set(ma.PACE_FA) >= set(core.PACE))

    def test_every_warning_code_has_persian_text(self):
        for w in ({"code": "upscale_hard", "angle": "close", "factor": 2.4}, {"code": "upscale_soft", "angle": "medium", "factor": 1.5}, {"code": "no_subject", "mode": "motion"},
                  {"code": "no_subject", "mode": "center"}, {"code": "angle_skipped", "angle": "two_shot", "why": "one_subject"}, {"code": "no_cut_points"},
                  {"code": "too_short"}, {"code": "holes_large", "share": 0.2}, {"code": "trimmed", "seconds": 180}):
            text = ma.warning_text(w)
            self.assertRegex(text, r"[؀-ۿ]", w)
            self.assertNotIn("{", text)
        self.assertIn("۲٫۴", ma.warning_text({"code": "upscale_hard", "angle": "close", "factor": 2.4}))
        self.assertEqual(ma.warnings_fa([{"code": "too_short"}, {"code": "too_short"}, "x"]), [ma.warning_text({"code": "too_short"})])

    def test_no_adobe_names_in_the_ui_texts(self):
        blob = " ".join(list(ma.ANGLE_FA.values()) + list(ma.MOVE_FA.values()) + list(ma.CHECK_FA.values()) + list(ma.ANGLE_HINT_FA.values()) + list(ma.MOVE_HINT_FA.values()))
        for bad in ("Adobe", "Photoshop", "Premiere", "After Effects", "فتوشاپ", "پریمیر"):
            self.assertNotIn(bad, blob)

    def test_the_shared_math_is_the_nodes_own_file(self):
        self.assertTrue(str(ma.core_path()).endswith("processing/multiangle_core.py"))
        self.assertTrue(ma.core_path().is_file())
        self.assertEqual(ma.core().VERSION, "1.1")


@override_settings(MEDIA_ROOT=str(MEDIA), NM_DATA_DIR=DATA, IS_TEST=True)
class Routing(TestCase):
    def test_capability_and_labels(self):
        from apps.compute.models import capability_for
        from apps.compute import queue as QV

        for kind in ("multiangle.virtual", "multiangle.move", "multiangle.selftest"):
            self.assertEqual(capability_for(kind), "multiangle")
            self.assertTrue(QV.KIND_LABELS[kind])

    def test_only_a_node_that_advertises_the_kind_gets_it(self):
        old = ComputeNode.objects.create(name="old", capabilities={"agent": "2.9", "ffmpeg": True}, last_seen=timezone.now())
        with self.assertRaises(SV.ComputeUnavailable):
            SV.enqueue_durable("multiangle.virtual", {"video": "a.mp4"}, {})                  # nobody registered that can do it
        new = ComputeNode.objects.create(name="new", capabilities=dict(READY_CAPS), last_seen=timezone.now())
        job = SV.enqueue_durable("multiangle.virtual", {"video": "a.mp4"}, {})
        self.assertIsNone(SV.claim(old))
        got = SV.claim(new)
        self.assertEqual(got.pk, job.pk)

    def test_the_job_waits_until_the_node_is_ready(self):
        node = ComputeNode.objects.create(name="warming", capabilities=dict(EMPTY_CAPS), last_seen=timezone.now())
        job = SV.enqueue_durable("multiangle.move", {"input": "a.png"}, {})
        self.assertIsNone(SV.claim(node))                                                     # queued, not failed
        job.refresh_from_db()
        self.assertEqual(job.state, "QUEUED")
        caps = dict(EMPTY_CAPS)
        caps["multiangle_ready"] = {"virtual": True, "move": False, "selftest": False}
        node.capabilities = caps
        node.save()
        self.assertIsNone(SV.claim(node))                                                     # virtual is ready, move is not
        node.capabilities = dict(READY_CAPS)
        node.save()
        self.assertEqual(SV.claim(node).pk, job.pk)

    def test_the_queue_page_says_why_it_waits(self):
        from apps.compute import queue as QV

        ComputeNode.objects.create(name="warming", capabilities=dict(EMPTY_CAPS), last_seen=timezone.now())
        job = SV.enqueue_durable("multiangle.virtual", {"video": "a.mp4"}, {})
        row = QV.one(job)
        self.assertIn("چندزاویه", row["status_text"])


class VirtualFlow(Base):
    def post_virtual(self, **extra):
        return self.client.post(self.url("runs/"), {"mode": "virtual", "source": f"video:{self.clip.pk}", "angles": ["wide", "medium", "close", "two_shot"], "format": "reel",
                                                    "pace": "fast", **extra}, format="json")

    def test_overview_lists_sources_presets_and_status(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"video:{self.clip.pk}", [v["ref"] for v in r.data["sources"]["videos"]])
        self.assertTrue(r.data["presets"]["angles"] and r.data["presets"]["moves"])
        self.assertTrue(r.data["status"]["ready"]["virtual"] and r.data["status"]["ready"]["move"])
        self.assertTrue(r.data["status"]["online"])
        self.assertEqual(r.data["status"]["nodes"][0]["name"], "gpu-1")

    def test_a_run_is_queued_with_a_clean_payload(self):
        r = self.post_virtual(handheld=7, pace="hyper")
        self.assertEqual(r.status_code, 201, r.data)
        run = MultiAngleRun.objects.get(pk=r.data["run"]["id"])
        self.assertEqual(run.state, "QUEUED")
        job = ComputeJob.objects.get(uid=run.job_uid)
        self.assertEqual(job.kind, "multiangle.virtual")
        p = job.payload
        self.assertEqual((p["format"], p["pace"], p["handheld"], p["angles"]), ("reel", "medium", 1.0, ["wide", "medium", "close", "two_shot"]))
        self.assertTrue(p["video"].startswith("source"))
        self.assertIn(p["video"], job.inputs)                                                  # the video travels with the job
        self.assertTrue((SV.job_root(job) / job.inputs[p["video"]]).is_file())
        self.assertEqual(p["max_seconds"], 180.0)

    def test_the_source_must_be_the_stores_own(self):
        other = User.objects.create_user("other", password="x")
        other_store = Store.objects.create(owner=other, name="دیگری")
        theirs = UploadedVideo.objects.create(store=other_store, title="x", state="READY")
        r = self.client.post(self.url("runs/"), {"mode": "virtual", "source": f"video:{theirs.pk}"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(MultiAngleRun.objects.count(), 0)
        r = self.client.post(self.url("runs/"), {"mode": "virtual", "source": "../../etc/passwd"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_another_user_cannot_see_the_page(self):
        stranger = User.objects.create_user("stranger", password="x")
        self.client.force_authenticate(stranger)
        self.assertIn(self.client.get(self.url()).status_code, (403, 404))
        self.assertIn(self.client.post(self.url("runs/"), {"mode": "virtual", "source": "video:1"}, format="json").status_code, (403, 404))

    def test_no_registered_node_is_a_clear_error_and_no_run_is_left(self):
        ComputeNode.objects.all().delete()
        r = self.post_virtual()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(MultiAngleRun.objects.count(), 0)
        self.assertRegex(r.data["error"]["message"], r"[؀-ۿ]")

    def test_the_whole_flow_node_to_editor(self):
        r = self.post_virtual()
        run_id = r.data["run"]["id"]
        # while nobody has taken it, the page shows the queue text
        r = self.client.get(self.url(f"runs/{run_id}/"))
        self.assertEqual(r.data["run"]["state"], "QUEUED")
        self.assertTrue(r.data["run"]["message"])
        # the node works (progress is mirrored) ...
        job = SV.claim(self.node)
        SV.progress(job, {"progress": 0.4, "message": "multiangle|render"})
        r = self.client.get(self.url(f"runs/{run_id}/"))
        self.assertEqual(r.data["run"]["state"], "RUNNING")
        self.assertAlmostEqual(r.data["run"]["progress"], 0.4, places=2)
        self.assertEqual(r.data["run"]["message"], "ساختنِ زاویه‌ها")
        # ... and finishes
        plan = fake_plan()
        for a in plan["angles"]:
            make_video(SV.output_path(job, a["file"]))
            SV.output_path(job, a["preview"]).write_bytes(b"\xff\xd8\xff\xd9")
        make_video(SV.output_path(job, "multicam.mp4"))
        SV.output_path(job, "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        import hashlib
        big = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (SV.job_root(job) / "outputs").glob("*.mp4")}
        SV.finish(job, self.node, True, meta={"primary": "plan.json", "big": big})
        r = self.client.get(self.url(f"runs/{run_id}/"))
        run = r.data["run"]
        self.assertEqual(run["state"], "READY", run)
        self.assertEqual([a["key"] for a in run["angles"]], ["wide", "medium", "close"])
        self.assertTrue(all(a["url"].startswith("/media/generated/multiangle/run") for a in run["angles"]))
        self.assertTrue(run["multicam_url"].endswith("multicam.mp4"))
        self.assertEqual(len(run["cuts"]), 3)
        self.assertEqual(run["cuts"][1]["reason_label"], "مکثِ گفتار")
        self.assertEqual(run["subject"], "آدم")
        self.assertEqual(run["skipped"][0]["key"], "two_shot")
        self.assertTrue(any("«نمای نزدیک»" in w for w in run["warnings"]))
        self.assertTrue(any("دو نفره" in w for w in run["warnings"]))
        # every angle is a video of the store (the editor's bin) and the files were moved into media
        for a in run["angles"]:
            up = UploadedVideo.objects.get(pk=a["upload"])
            self.assertEqual(up.store_id, self.store.pk)
            self.assertTrue(Path(up.video.path).is_file())
            self.assertGreater(up.duration, 3.0)
            self.assertTrue(up.has_audio)
        self.assertEqual(UploadedVideo.objects.filter(store=self.store, facts__source="multiangle").count(), 4)        # 3 angles + the multicam
        self.assertFalse((SV.job_root(job) / "outputs" / "angle_wide.mp4").exists())                                  # moved, not copied
        # the editor project: a multicam group with the automatic cuts
        r = self.client.post(self.url(f"runs/{run_id}/editor/"))
        self.assertEqual(r.status_code, 200, r.data)
        project = VideoProject.objects.get(pk=r.data["project_id"])
        data = project.data
        seq = next(iter(data["sequences"].values()))
        info = seq["multicam"]
        self.assertEqual([a["label"] for a in info["angles"]], ["نمای باز", "نمای متوسط", "نمای نزدیک"])
        self.assertEqual([(c["t"], c["angle"]) for c in info["cuts"]], [(0.0, 0), (1.4, 2), (2.6, 1)])
        self.assertEqual([c["ref"] for c in seq["tracks"][0]["clips"]], [info["angles"][i]["ref"] for i in (0, 2, 1)])
        self.assertEqual(data["tracks"][0]["clips"][0]["ref"], "seq:" + next(iter(data["sequences"])))
        self.assertEqual(data["format"]["preset"], "reel")
        self.assertTrue(editor_project.check(self.store, data)["ok"])
        # idempotent: the second click opens the same project
        r2 = self.client.post(self.url(f"runs/{run_id}/editor/"))
        self.assertEqual(r2.data["project_id"], project.pk)
        self.assertEqual(VideoProject.objects.filter(store=self.store).count(), 1)
        # deleting the run removes the files and the clips it added
        r = self.client.delete(self.url(f"runs/{run_id}/"))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(UploadedVideo.objects.filter(facts__source="multiangle").count(), 0)
        self.assertFalse((MEDIA / "generated" / "multiangle" / f"run{run_id}").exists())

    def test_a_corrupt_file_from_the_node_fails_the_run_cleanly(self):
        r = self.post_virtual()
        run_id = r.data["run"]["id"]
        job = SV.claim(self.node)
        plan = fake_plan()
        for a in plan["angles"]:
            make_video(SV.output_path(job, a["file"]))
            SV.output_path(job, a["preview"]).write_bytes(b"x")
        make_video(SV.output_path(job, "multicam.mp4"))
        SV.output_path(job, "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        SV.finish(job, self.node, True, meta={"primary": "plan.json", "big": {"angle_wide.mp4": {"bytes": 5, "sha256": "0" * 64}}})
        r = self.client.get(self.url(f"runs/{run_id}/"))
        self.assertEqual(r.data["run"]["state"], "FAILED")
        self.assertIn("اندازهٔ", r.data["run"]["error"])
        self.assertEqual(UploadedVideo.objects.filter(facts__source="multiangle").count(), 0)

    def test_a_missing_plan_fails_the_run(self):
        r = self.post_virtual()
        run_id = r.data["run"]["id"]
        job = SV.claim(self.node)
        SV.finish(job, self.node, True, meta={"primary": "plan.json"})
        r = self.client.get(self.url(f"runs/{run_id}/"))
        self.assertEqual(r.data["run"]["state"], "FAILED")
        self.assertIn("plan.json", r.data["run"]["error"])

    def test_a_node_error_becomes_a_persian_message(self):
        run_id = self.post_virtual().data["run"]["id"]
        job = SV.claim(self.node)
        SV.finish(job, self.node, False, error="the video cannot be opened: x.mp4 [no_video]", meta={"retryable": False})
        r = self.client.get(self.url(f"runs/{run_id}/"))
        self.assertEqual(r.data["run"]["state"], "FAILED")
        self.assertIn("ویدیو خوانده نشد", r.data["run"]["error"])
        self.assertEqual(services.error_fa("boom\nsomething odd happened"), "ساخت روی سرورِ پردازش ناموفق بود: something odd happened")
        self.assertIn("حافظه", services.error_fa("x [memory]"))

    def test_cancel(self):
        run_id = self.post_virtual().data["run"]["id"]
        SV.claim(self.node)
        r = self.client.post(self.url(f"runs/{run_id}/cancel/"))
        self.assertEqual(r.data["run"]["state"], "CANCELLED")
        job = ComputeJob.objects.get(uid=MultiAngleRun.objects.get(pk=run_id).job_uid)
        self.assertTrue(job.cancel_requested or job.state == "CANCELLED")

    def test_the_editor_needs_a_finished_run(self):
        run_id = self.post_virtual().data["run"]["id"]
        r = self.client.post(self.url(f"runs/{run_id}/editor/"))
        self.assertEqual(r.status_code, 400)

    def test_old_runs_are_pruned(self):
        for _ in range(services.MAX_RUNS + 3):
            MultiAngleRun.objects.create(store=self.store, state="READY", title="old")
        self.post_virtual()
        self.assertLessEqual(MultiAngleRun.objects.filter(store=self.store).count(), services.MAX_RUNS + 1)

    def test_the_transcript_travels_as_sentences(self):
        self.clip.transcript = [{"start": 0.0, "end": 2.0, "text": "a"}, {"start": 2.5, "end": 4.0, "text": "b"}, {"start": "x", "end": 1}]
        self.clip.save()
        run_id = self.post_virtual().data["run"]["id"]
        job = ComputeJob.objects.get(uid=MultiAngleRun.objects.get(pk=run_id).job_uid)
        self.assertEqual(job.payload["sentences"], [{"start": 0.0, "end": 2.0}, {"start": 2.5, "end": 4.0}])


class MoveFlow(Base):
    def test_a_move_from_a_video_end_to_end(self):
        r = self.client.post(self.url("runs/"), {"mode": "move25d", "source": f"video:{self.clip.pk}", "move": "orbit_left", "amount": 0.7, "duration": 3, "format": "reel"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        run_id = r.data["run"]["id"]
        job = ComputeJob.objects.get(uid=MultiAngleRun.objects.get(pk=run_id).job_uid)
        self.assertEqual(job.kind, "multiangle.move")
        self.assertEqual((job.payload["move"], job.payload["amount"], job.payload["duration"], job.payload["format"]), ("orbit_left", 0.7, 3.0, "reel"))
        job = SV.claim(self.node)
        make_video(SV.output_path(job, "move.mp4"), seconds=3)
        SV.output_path(job, "preview.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        SV.output_path(job, "depth.png").write_bytes(b"\x89PNG")
        plan = {"v": 1, "mode": "move25d", "move": "orbit_left", "file": "move.mp4", "preview": "preview.jpg", "depth": "depth.png", "safe_zoom": 1.08,
                "output": {"width": 144, "height": 256, "fps": 30, "frames": 90, "duration": 3.0}, "warnings": [{"code": "holes_large", "share": 0.12}],
                "device": {"models": {"depth": "Dml"}, "model_fallback": [], "encoder": "nvenc"}}
        SV.output_path(job, "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        import hashlib
        p = SV.output_path(job, "move.mp4")
        SV.finish(job, self.node, True, meta={"big": {"move.mp4": {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}}})
        run = self.client.get(self.url(f"runs/{run_id}/")).data["run"]
        self.assertEqual(run["state"], "READY", run)
        self.assertTrue(run["move"]["url"].endswith("move.mp4"))
        self.assertTrue(run["move"]["depth"].endswith("depth.png"))
        self.assertEqual(run["move"]["label"], "چرخش دورِ سوژه به چپ")
        self.assertTrue(any("پس‌زمینه" in w for w in run["warnings"]))
        self.assertTrue(UploadedVideo.objects.filter(pk=run["move"]["upload"], store=self.store).exists())
        self.assertEqual(self.client.post(self.url(f"runs/{run_id}/editor/")).status_code, 400)         # a move has no multicam

    def test_a_move_from_a_photo_is_accepted(self):
        from apps.photoedit.models import PhotoAsset

        rel = "photoedit/test_pic.jpg"
        (MEDIA / "photoedit").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PIC, MEDIA / rel)
        fields = {f.name for f in PhotoAsset._meta.fields}
        kw = {"store": self.store, "original": rel}
        if "title" in fields:
            kw["title"] = "عکس"
        asset = PhotoAsset.objects.create(**kw)
        r = self.client.post(self.url("runs/"), {"mode": "move25d", "source": f"photo:{asset.pk}", "move": "dolly_in"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        job = ComputeJob.objects.get(uid=MultiAngleRun.objects.get(pk=r.data["run"]["id"]).job_uid)
        self.assertTrue(job.payload["input"].endswith(".jpg"))
        self.assertFalse(MultiAngleRun.objects.get(pk=r.data["run"]["id"]).params["video"])

    def test_a_virtual_run_needs_a_video(self):
        from apps.photoedit.models import PhotoAsset

        rel = "photoedit/test_pic2.jpg"
        (MEDIA / "photoedit").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PIC, MEDIA / rel)
        asset = PhotoAsset.objects.create(store=self.store, original=rel)
        r = self.client.post(self.url("runs/"), {"mode": "virtual", "source": f"photo:{asset.pk}"}, format="json")
        self.assertEqual(r.status_code, 400)


class WhileTheNodeIsOld(Base):
    """The only node is still on software from before the feature (or off): «بساز» registers the job; it waits in the durable queue and runs after
    the node has updated itself. Nothing is refused, nothing is left for the owner to do."""

    caps = OLD_CAPS

    def test_a_virtual_run_is_queued_for_an_old_node(self):
        r = self.client.post(self.url("runs/"), {"mode": "virtual", "source": f"video:{self.clip.pk}", "angles": ["wide", "medium", "close"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        run = MultiAngleRun.objects.get(pk=r.data["run"]["id"])
        self.assertEqual(run.state, "QUEUED")
        job = ComputeJob.objects.get(uid=run.job_uid)
        self.assertEqual((job.kind, job.state), ("multiangle.virtual", "QUEUED"))
        self.assertIn(job.payload["video"], job.inputs)
        self.assertIn("خودکار به‌روز", run.message)
        self.assertEqual(r.data["run"]["state"], "QUEUED")
        self.assertIsNone(SV.claim(self.node))                                              # the old agent is never offered the kind

    def test_a_2_5d_move_from_a_video_and_from_a_photo_is_queued_too(self):
        from apps.photoedit.models import PhotoAsset

        r = self.client.post(self.url("runs/"), {"mode": "move25d", "source": f"video:{self.clip.pk}", "move": "truck_right"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rel = "photoedit/test_pic_old.jpg"
        (MEDIA / "photoedit").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PIC, MEDIA / rel)
        asset = PhotoAsset.objects.create(store=self.store, original=rel)
        r2 = self.client.post(self.url("runs/"), {"mode": "move25d", "source": f"photo:{asset.pk}", "move": "dolly_in"}, format="json")
        self.assertEqual(r2.status_code, 201, r2.data)
        self.assertEqual(MultiAngleRun.objects.filter(state="QUEUED").count(), 2)
        self.assertEqual(ComputeJob.objects.filter(kind="multiangle.move", state="QUEUED").count(), 2)

    def test_the_queued_job_runs_once_the_node_has_updated_and_is_ready(self):
        r = self.client.post(self.url("runs/"), {"mode": "virtual", "source": f"video:{self.clip.pk}", "angles": ["wide", "close"]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        run_id = r.data["run"]["id"]
        self.assertIsNone(SV.claim(self.node))
        self.node.capabilities = dict(READY_CAPS)                                           # the heartbeat after the automatic update
        self.node.save()
        fake_node_finishes(self.node)
        run = self.client.get(self.url(f"runs/{run_id}/")).data["run"]
        self.assertEqual(run["state"], "READY", run)

    def test_the_page_and_the_queue_say_the_node_will_update_itself(self):
        from apps.compute import queue as QV

        self.client.post(self.url("runs/"), {"mode": "virtual", "source": f"video:{self.clip.pk}", "angles": ["wide", "close"]}, format="json")
        job = ComputeJob.objects.get(kind="multiangle.virtual")
        self.assertIn("به‌روز", QV.one(job)["status_text"])
        ov = self.client.get(self.url()).data
        self.assertTrue(ov["status"]["can_queue"])
        self.assertIn("به‌روز", ov["runs"][0]["message"])
        ComputeNode.objects.all().update(last_seen=timezone.now() - timedelta(hours=5))     # switched off in the meantime
        ov = self.client.get(self.url()).data
        self.assertEqual(ov["status"]["message"], services.UPDATE_OFFLINE_AUTO)
        self.assertEqual(ov["runs"][0]["message"], services.UPDATE_OFFLINE_AUTO)

    def test_nothing_registered_is_still_a_clear_503_and_leaves_no_run(self):
        ComputeNode.objects.all().delete()
        r = self.client.post(self.url("runs/"), {"mode": "move25d", "source": f"video:{self.clip.pk}", "move": "dolly_in"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (503, "no_node"))
        self.assertEqual((MultiAngleRun.objects.count(), ComputeJob.objects.filter(kind__startswith="multiangle.").count()), (0, 0))


class Pickers(Base):
    def test_pictures_carry_their_real_size_not_zero(self):
        from apps.photoedit.models import PhotoAsset

        rel = "photoedit/test_pic_size.jpg"
        (MEDIA / "photoedit").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PIC, MEDIA / rel)
        PhotoAsset.objects.create(store=self.store, original=rel)
        src = self.client.get(self.url()).data["sources"]
        imgs = [i for i in src["images"] if i["ref"].startswith("photo:")]
        self.assertTrue(imgs)
        self.assertEqual((imgs[0]["width"], imgs[0]["height"]), (320, 192))
        self.assertTrue(any(v["ref"] == f"video:{self.clip.pk}" for v in src["videos"]))
        self.assertEqual(services._image_size("/elsewhere/x.jpg"), (0, 0))
        self.assertEqual(services._image_size("/media/none.jpg"), (0, 0))


class EditorProject(TestCase):
    def angles(self, offsets=(0, 0, 0)):
        return [{"ref": f"video:{i + 1}", "label": f"cam{i}", "duration": 10.0, "has_audio": True, "offset": o} for i, o in enumerate(offsets)]

    def resolve(self, ref):
        return {"path": str(CLIP), "kind": "video", "has_audio": True, "duration": 10.0, "width": 320, "height": 192}

    def test_the_project_is_valid_for_the_servers_own_parser(self):
        data = ma.build_project(self.angles(), [{"t": 0, "angle": 0}, {"t": 3.0, "angle": 2}, {"t": 6.5, "angle": 1}], 10.0, 1080, 1920, 30)
        line = tl.from_project(data, self.resolve)
        line.validate()
        self.assertAlmostEqual(line.length, 10.0, places=1)
        self.assertEqual(data["format"]["preset"], "reel")

    def test_cuts_are_normalised(self):
        data = ma.build_project(self.angles(), [{"t": 3.0, "angle": 1}, {"t": 3.01, "angle": 2}, {"t": 5.0, "angle": 2}, {"t": 6.0, "angle": 0}, {"t": 99, "angle": 0}, {"t": 7, "angle": 9}],
                                10.0, 1920, 1080, 25)
        seq = next(iter(data["sequences"].values()))
        cuts = seq["multicam"]["cuts"]
        self.assertEqual(cuts[0], {"t": 0.0, "angle": 2})                       # a cut at 0 is always there (near-duplicates: the later one wins)
        self.assertEqual([c["angle"] for c in cuts], [2, 0])                    # nothing past the end or on a missing angle, no repeats
        clips = seq["tracks"][0]["clips"]
        self.assertEqual(len(clips), 2)
        self.assertAlmostEqual(clips[0]["end"], 6.0, places=2)
        self.assertEqual(data["format"]["preset"], "wide")

    def test_real_cameras_keep_their_offsets(self):
        data = ma.build_project(self.angles((0, 2.0)), [{"t": 0, "angle": 0}, {"t": 5.0, "angle": 1}], 12.0, 1920, 1080, 30)
        seq = next(iter(data["sequences"].values()))
        self.assertEqual([a["offset"] for a in seq["multicam"]["angles"]], [0, 2.0])
        second = seq["tracks"][0]["clips"][1]
        self.assertEqual((second["at"], second["start"]), (5.0, 3.0))           # at 5 s on the timeline = 3 s into a camera that started at 2 s
        tl.from_project(data, self.resolve).validate()

    def test_a_silent_audio_angle_means_no_audio_track_clip(self):
        a = self.angles()
        for x in a:
            x["has_audio"] = False
        data = ma.build_project(a, [{"t": 0, "angle": 0}, {"t": 4, "angle": 1}], 10.0, 1080, 1080, 30)
        seq = next(iter(data["sequences"].values()))
        self.assertEqual(seq["multicam"]["audio"], -1)
        self.assertEqual(seq["tracks"][1]["clips"], [])

    def test_two_angles_at_least(self):
        with self.assertRaises(ValueError):
            ma.build_project(self.angles()[:1], [], 5.0, 1080, 1920, 30)


@override_settings(MEDIA_ROOT=str(MEDIA), NM_DATA_DIR=DATA, IS_TEST=True)
class RealCameras(Base):
    """Two REAL recordings of one event, started 1 s apart: lined up by sound, auto-switched, as an editor project (no node involved)."""

    def make_pair(self):
        import numpy as np

        sr = 16000
        rng = np.random.default_rng(5)
        phrases, gap = [2.2, 1.6, 2.4], 0.6
        parts = []
        for d in phrases:
            t = np.arange(int(d * sr)) / sr
            phrase = (0.35 * np.sin(2 * np.pi * 190 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)) + 0.08 * rng.standard_normal(len(t))).astype(np.float32)
            for at in np.cumsum(rng.uniform(0.15, 0.45, size=int(d / 0.15))):          # hand claps and consonants: sharp events every few hundred ms
                i = int(at * sr)
                if i + 400 < len(phrase):
                    phrase[i:i + 400] += (0.9 * rng.standard_normal(400) * np.exp(-np.arange(400) / 90.0)).astype(np.float32)
            parts.append(phrase)
            parts.append((0.003 * rng.standard_normal(int(gap * sr))).astype(np.float32))
        sound = np.concatenate(parts)
        out = []
        for name, delay in (("camA", 0.0), ("camB", 1.0)):
            pcm = np.concatenate([np.zeros(int(delay * sr), dtype=np.float32), sound])
            wav = TMP / f"{name}.wav"
            import wave
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
            mp4 = TMP / f"{name}.mp4"
            subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=160x96:rate=25:duration={len(pcm) / sr:.2f}", "-i", str(wav), "-c:v", "libx264",
                            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(mp4)], check=True, stdin=subprocess.DEVNULL)
            out.append(self.upload(mp4, name))
        return out

    def test_two_real_cameras_are_synced_and_cut(self):
        a, b = self.make_pair()
        r = self.client.post(self.url("real/"), {"sources": [f"video:{a.pk}", f"video:{b.pk}"], "pace": "fast"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertAlmostEqual(abs(r.data["offsets"][1] - r.data["offsets"][0]), 1.0, delta=0.06)
        self.assertGreaterEqual(r.data["cuts"], 2)
        project = VideoProject.objects.get(pk=r.data["project_id"])
        seq = next(iter(project.data["sequences"].values()))
        self.assertEqual(len(seq["multicam"]["angles"]), 2)
        self.assertEqual(seq["multicam"]["cuts"][0]["t"], 0.0)
        self.assertTrue(editor_project.check(self.store, project.data)["ok"])

    def test_unrelated_sound_is_refused(self):
        a = self.upload(CLIP, "یک")
        other = TMP / "noise.mp4"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=25:duration=6", "-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:a=0.3", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(other)], check=True, stdin=subprocess.DEVNULL)
        b = self.upload(other, "دو")
        r = self.client.post(self.url("real/"), {"sources": [f"video:{a.pk}", f"video:{b.pk}"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(VideoProject.objects.count(), 0)

    def test_needs_two_to_four_videos_with_sound(self):
        a = self.upload(CLIP, "یک")
        self.assertEqual(self.client.post(self.url("real/"), {"sources": [f"video:{a.pk}"]}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url("real/"), {"sources": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url("real/"), {"sources": ["video:1", "../x"]}, format="json").status_code, 400)


@override_settings(MEDIA_ROOT=str(MEDIA), NM_DATA_DIR=DATA, IS_TEST=True)
class Preparation(TestCase):
    """The node installs itself; the site only asks when the node is not already doing it, and tests it once it is ready."""

    def node(self, caps, name="gpu-1", online=True):
        return ComputeNode.objects.create(name=name, capabilities=dict(caps), last_seen=timezone.now() if online else timezone.now() - timedelta(hours=2))

    def test_status_explains_each_situation(self):
        s = services.status()
        self.assertFalse(s["online"])
        self.assertIn("START.bat", s["message"])
        self.assertFalse(s["can_queue"])                                     # nothing registered: a job has nothing to wait for
        self.node(OLD_CAPS, "old")
        s = services.status()
        self.assertEqual(s["needs_update"], ["old"])
        self.assertTrue(s["can_queue"])
        self.assertIn("خودکار به‌روز", s["update_text"])                     # auto-update is on by default: nothing for the owner to do
        self.assertNotIn("Update.bat", s["update_text"])
        self.node(EMPTY_CAPS, "warm")
        s = services.status()
        self.assertEqual(s["needs_update"], [])
        self.assertFalse(s["ready"]["virtual"])
        self.assertIn("نصبِ خودکار", s["message"])
        ComputeNode.objects.all().delete()
        self.node(READY_CAPS, "ok")
        s = services.status()
        self.assertTrue(s["ready"]["virtual"] and s["ready"]["move"])
        self.assertIn("آماده", s["message"])
        self.assertTrue(s["nodes"][0]["runtime"]["gpu"])

    def test_an_old_node_that_is_off_says_it_updates_itself_when_switched_on(self):
        self.node(OLD_CAPS, "old", online=False)
        s = services.status()
        self.assertFalse(s["online"])
        self.assertEqual(s["message"], services.UPDATE_OFFLINE_AUTO)
        self.assertEqual(s["update_text"], services.UPDATE_OFFLINE_AUTO)
        self.assertIn("خاموش است", s["message"])
        self.assertIn("خودش به‌روز می‌شود", s["message"])

    def test_with_auto_update_off_the_owner_is_told_what_to_run_and_that_jobs_wait(self):
        from apps.compute.models import ComputeSettings

        cfg = ComputeSettings.get()
        cfg.auto_update = False
        cfg.save()
        self.node(OLD_CAPS, "old", online=False)
        s = services.status()
        self.assertEqual(s["message"], services.UPDATE_OFFLINE_MANUAL)
        self.assertIn("Update.bat", s["message"])
        self.assertIn("در صف می‌مانند", s["message"])
        ComputeNode.objects.all().update(last_seen=timezone.now())
        self.assertEqual(services.status()["message"], services.UPDATE_TEXT)

    def test_an_old_node_that_is_on_says_the_update_is_automatic(self):
        self.node(OLD_CAPS, "old")
        self.assertEqual(services.status()["message"], services.UPDATE_ONLINE_AUTO)

    def test_an_agent_without_the_update_command_is_told_to_start_it_again(self):
        self.node({"agent": "2.2", "ffmpeg": True}, "ancient")
        s = services.status()
        self.assertEqual(s["message"], services.UPDATE_NO_COMMAND)
        self.assertTrue(s["can_queue"])
        self.assertIn("START.bat", s["message"])

    def test_an_offline_node_says_so(self):
        self.node(READY_CAPS, "off", online=False)
        s = services.status()
        self.assertFalse(s["online"])
        self.assertIn("خاموش", s["message"])

    def test_install_is_requested_once_with_the_right_packages(self):
        node = self.node(EMPTY_CAPS)
        self.assertEqual(services.prepare_node(node), "requested: multiangle-runtime, multiangle-detect, multiangle-depth")
        job = ComputeJob.objects.get(kind="node.models")
        self.assertEqual(job.payload["packages"], ["multiangle-depth", "multiangle-detect", "multiangle-runtime"])
        self.assertEqual(job.node_wanted, "gpu-1")
        self.assertEqual(job.window, "")                                                      # now, not the night window
        self.assertEqual(services.prepare_node(node), "installing")                           # the second call does nothing
        self.assertEqual(ComputeJob.objects.filter(kind="node.models").count(), 1)

    def test_only_what_is_missing_is_requested(self):
        caps = dict(READY_CAPS)
        caps["multiangle_ready"] = {"virtual": True, "move": False, "selftest": False}
        caps["multiangle_models"] = {**READY_CAPS["multiangle_models"], "depth": {"state": "missing", "size_mb": 95}}
        node = self.node(caps)
        self.assertEqual(services.prepare_node(node), "requested: multiangle-depth")

    def test_a_node_that_is_already_downloading_is_left_alone(self):
        caps = dict(EMPTY_CAPS)
        caps["models"] = {"running": True}
        self.assertEqual(services.prepare_node(self.node(caps)), "installing")
        self.assertFalse(ComputeJob.objects.filter(kind="node.models").exists())

    def test_autocheck_prepares_then_tests_each_node_once(self):
        node = self.node(EMPTY_CAPS)
        out = services.autocheck()
        self.assertTrue(out["gpu-1"].startswith("requested"))
        self.assertFalse(MultiAngleRun.objects.exists())                                      # not ready: no test yet
        node.capabilities = dict(READY_CAPS)
        node.save()
        out = services.autocheck()
        self.assertTrue(out["gpu-1"].startswith("selftest"))
        run = MultiAngleRun.objects.get(mode="selftest")
        job = ComputeJob.objects.get(uid=run.job_uid)
        self.assertEqual((job.kind, job.node_wanted, job.payload), ("multiangle.selftest", "gpu-1", {"selftest": True}))
        self.assertEqual(services.autocheck()["gpu-1"], "ok")                                 # a test is running: no second one
        self.assertEqual(MultiAngleRun.objects.filter(mode="selftest").count(), 1)

    def _finish_selftest(self, node, ok):
        job = SV.claim(node)
        checks = [{"name": "runtime", "ok": True, "detail": "x"}, {"name": "move.parallax", "ok": ok, "detail": "mean change 0.2"}]
        SV.output_path(job, "selftest.json").write_text(json.dumps({"ok": ok, "checks": checks, "version": "1.0"}), encoding="utf-8")
        SV.finish(job, node, True, meta={"primary": "selftest.json", "ok": ok})

    def test_a_passing_self_test_is_recorded_and_not_repeated(self):
        node = self.node(READY_CAPS)
        services.autocheck()
        self._finish_selftest(node, True)
        services.autocheck()                                                                  # refreshes the finished run
        run = MultiAngleRun.objects.get(mode="selftest")
        self.assertEqual(run.state, "READY")
        self.assertEqual(run.message, "گذشت ✓")
        self.assertEqual(services.autocheck()["gpu-1"], "ok")
        self.assertEqual(MultiAngleRun.objects.filter(mode="selftest").count(), 1)
        summary = services.status()["nodes"][0]["selftest"]
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["checks"][0]["label"], ma.CHECK_FA["runtime"])

    def test_a_failing_self_test_is_shown_and_retried_after_hours_or_on_a_new_version(self):
        node = self.node(READY_CAPS)
        services.autocheck()
        self._finish_selftest(node, False)
        services.autocheck()
        run = MultiAngleRun.objects.get(mode="selftest")
        self.assertEqual(run.state, "FAILED")
        self.assertIn("حرکتِ دوربینِ ۲٫۵بعدی", run.error)
        self.assertEqual(services.autocheck()["gpu-1"], "ok")                                 # not retried at once
        MultiAngleRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(hours=services.SELFTEST_RETRY_HOURS + 1))
        self.assertTrue(services.autocheck()["gpu-1"].startswith("selftest"))
        # a new node version is tested again even after a pass
        for r in MultiAngleRun.objects.all():
            MultiAngleRun.objects.filter(pk=r.pk).update(state="READY")
        caps = dict(READY_CAPS)
        caps["code"] = {"id": "newer", "version": "2"}
        node.capabilities = caps
        node.save()
        self.assertTrue(services.autocheck()["gpu-1"].startswith("selftest"))

    def test_the_page_can_ask_for_the_install_and_staff_can_run_the_test(self):
        user = User.objects.create_user("owner2", password="x", is_staff=False)
        store = Store.objects.create(owner=user, name="s")
        self.client_user = user
        from rest_framework.test import APIClient

        c = APIClient()
        c.force_authenticate(user)
        self.node(EMPTY_CAPS)
        r = c.post(f"/api/v1/stores/{store.pk}/multiangle/prepare/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["nodes"]["gpu-1"].startswith("requested"))
        self.assertEqual(c.post(f"/api/v1/stores/{store.pk}/multiangle/selftest/").status_code, 403)
        staff = User.objects.create_user("staff", password="x", is_staff=True)
        store2 = Store.objects.create(owner=staff, name="s2")
        c2 = APIClient()
        c2.force_authenticate(staff)
        self.assertEqual(c2.post(f"/api/v1/stores/{store2.pk}/multiangle/selftest/").status_code, 201)

    def test_the_beat_task_is_registered(self):
        from django.conf import settings

        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["multiangle-autocheck"]["task"], "apps.multiangle.tasks.autocheck")
        from . import tasks

        with mock.patch.object(services, "autocheck", return_value={"x": "ok"}):
            self.assertEqual(tasks.autocheck(), {"x": "ok"})
        with mock.patch.object(services, "autocheck", side_effect=RuntimeError("boom")):
            self.assertEqual(tasks.autocheck(), {"error": "boom"})                           # a failure never stops the beat
