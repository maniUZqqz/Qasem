"""تدوین ویدیو — سه حالت (خودکار / نیمه‌خودکار با دستور / دستی): مسیریابیِ هوشِ مصنوعی (اول Qwen روی سرورِ پردازش، بعد
Metis)، پیامِ روشن برای ۴۰۲ و گره‌ی خاموش، پیگیریِ «گرم‌ترش کن»، و API ِ فضای کارِ دستی (بسته‌ی رسانه، پروژه، پیش‌نمایشِ
سبک، رندرِ واقعی با ffmpeg).

هیچ‌جا به Metis یا Ollama ِ واقعی وصل نمی‌شود: همه‌ی ارائه‌دهنده‌ها ساختگی‌اند."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.compute.models import ComputeNode
from apps.jobs.models import Job
from apps.stores.models import Store
from services.ai import routing
from services.ai.gateway import PolicyBlocked
from services.ai.ollama import OllamaError
from services.editing import agent
from services.video.ffmpeg import FFMPEG, probe

from .models import UploadedVideo, VideoProject

TEMP_MEDIA = tempfile.mkdtemp(prefix="nm-editor-modes-")

FACTS = {
    "readable": True, "duration": 60.0, "has_audio": True, "width": 1080, "height": 1920, "fps": 30,
    "brightness": 40, "brightness_swing": 4, "colour_cast": 2, "motion": 3,
    "silence_count": 12, "silence_seconds": 18, "longest_silence": 3.1,
    "silences": [{"start": 4, "end": 7}], "clipped_pixels": 0,
}


def sh(*args):
    subprocess.run(list(args), check=True, capture_output=True, stdin=subprocess.DEVNULL)


def make_video(path: Path, *, size="320x240", seconds=2, audio=True, freq=440):
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    sh(*cmd)
    return path


class FakeModel:
    """Qwen on the processing server (or the API) — answers a canned plan or raises."""

    def __init__(self, operations=None, exc=None, name="qwen3-coder:30b"):
        self.operations, self.exc, self.name = operations, exc, name
        self.prompts: list[str] = []

    def generate_json(self, model, prompt, system=None, images=None, options=None, **_kw):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return {"operations": self.operations or []}, json.dumps({"operations": self.operations or []})

    def select_models(self, candidates):
        return [self.name]


GOOD_PLAN = [{"tool": "contrast", "params": {"amount": 1.2}, "reason": "کمی پرجان‌تر", "confidence": 0.9}]


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class EditorTestBase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("modes-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه حالت‌ها")
        self.client.force_login(self.owner)
        self.upload = UploadedVideo.objects.create(
            store=self.store, title="ویدیوی آزمون", video="uploads/videos/placeholder.mp4",
            state=UploadedVideo.State.READY, duration=60.0, facts=FACTS,
        )
        self.base = f"/api/v1/stores/{self.store.pk}"

    def plan(self, **body):
        return self.client.post(f"{self.base}/videos/{self.upload.pk}/plan/", body, content_type="application/json")


class DirectedRoutingTests(EditorTestBase):
    """«نیمه‌خودکار» = کارگردانی: اول Qwen روی سرورِ پردازش، Metis فقط پشتیبان؛ هر شکستی با جملهٔ فارسیِ روشن."""

    def routed(self, node_answer, api):
        """text_provider(store) واقعی‌ترین شکل: RoutedTextProvider با گرهٔ ساختگی و پشتیبانِ ساختگی."""
        provider = routing.RoutedTextProvider(api, task="text:PRODUCT")
        return patch("services.ai.gateway.text_provider", return_value=provider), \
            patch("services.ai.routing.node_provider", return_value=node_answer)

    def online_node(self):
        return ComputeNode.objects.create(
            name="gpu-1", capabilities={"ollama": True, "ollama_models": [routing.coder_model()]}, last_seen=timezone.now())

    @override_settings(AI_ROUTE_FORCE=True)
    def test_node_is_asked_first_and_metis_is_not_touched(self):
        self.online_node()
        node, api = FakeModel(GOOD_PLAN, name=routing.coder_model()), FakeModel(exc=OllamaError("خطای سرویس 402: no credit"))
        p1, p2 = self.routed(node, api)
        with p1, p2, patch("services.ai.router.models_for", return_value=["x"]):
            r = self.plan(mode="DIRECTED", instruction="ساده و تمیز")
        body = r.json()
        self.assertEqual(r.status_code, 200, body)
        self.assertEqual(body["ai"]["via"], "node")
        self.assertTrue(body["ai"]["ok"])
        self.assertFalse(body["ai"]["fell_back"])
        self.assertEqual([o["tool"] for o in body["operations"]], ["contrast"])
        self.assertEqual(len(node.prompts), 1)
        self.assertEqual(api.prompts, [], "Metis نباید صدا زده شود")

    @override_settings(AI_ROUTE_FORCE=True)
    def test_node_off_and_no_credit_says_exactly_that_in_persian(self):
        # سرورِ پردازش خاموش (ثبت شده ولی چند وقت است نیامده) و Metis ⇒ HTTP 402
        ComputeNode.objects.create(name="gpu-1", capabilities={"ollama": True, "ollama_models": [routing.coder_model()]})
        api = FakeModel(exc=OllamaError("خطای سرویس 402: {\"error\":\"Payment Required\"}"))
        p1, p2 = self.routed(FakeModel(GOOD_PLAN), api)
        with p1, p2, patch("services.ai.router.models_for", return_value=["x"]):
            r = self.plan(mode="DIRECTED", instruction="مثل یک یوتیوبر حرفه‌ای")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        ai = body["ai"]
        self.assertFalse(ai["ok"])
        self.assertEqual(ai["error_code"], "no_credit")
        self.assertIn("۴۰۲", ai["error"])
        self.assertIn("اعتبار", ai["error"])
        self.assertIn("سرورِ پردازش خاموش است", ai["error"], "علتِ دومِ شکست هم باید گفته شود")
        self.assertTrue(ai["used_fallback_plan"])
        self.assertTrue(body["operations"], "بی هوشِ مصنوعی هم پیشنهادِ خودکارِ مبتنی بر اندازه‌گیری می‌آید")
        self.assertEqual(len(api.prompts), 1)

    @override_settings(AI_ROUTE_FORCE=True)
    def test_node_failure_falls_back_to_the_api_and_the_answer_says_so(self):
        self.online_node()
        node = FakeModel(exc=OllamaError("model 'qwen3-coder:30b' not found (404)"), name=routing.coder_model())
        api = FakeModel(GOOD_PLAN, name="gpt-4o-mini")
        p1, p2 = self.routed(node, api)
        with p1, p2, patch("services.ai.router.models_for", return_value=["x"]):
            body = self.plan(mode="DIRECTED", instruction="x").json()
        self.assertTrue(body["ai"]["ok"])
        self.assertEqual(body["ai"]["via"], "api")
        self.assertTrue(body["ai"]["fell_back"])
        self.assertIn("نصب نیست", body["ai"]["fallback_reason"])
        self.assertEqual(len(node.prompts), 1)
        self.assertEqual(len(api.prompts), 1)

    def test_policy_block_and_other_failures_are_named(self):
        with patch("services.ai.gateway.text_provider", side_effect=PolicyBlocked("x", "TEXT", ["r"])):
            ai = self.plan(mode="DIRECTED", instruction="x").json()["ai"]
        self.assertEqual(ai["error_code"], "policy")
        self.assertIn("سیاستِ داده", ai["error"])
        for exc, code in ((OllamaError("خطای سرویس 401"), "bad_key"), (OllamaError("سهمیه تمام (429)"), "rate_limit")):
            with patch("services.ai.gateway.text_provider", return_value=FakeModel(exc=exc)), \
                    patch("services.ai.router.models_for", return_value=["x"]):
                self.assertEqual(self.plan(mode="DIRECTED", instruction="x").json()["ai"]["error_code"], code)

    def test_a_follow_up_refines_the_plan_and_a_failed_one_keeps_it(self):
        fake = FakeModel([{"tool": "contrast", "params": {"amount": 1.1}, "reason": "نرم‌تر", "confidence": 1}])
        previous = [{"tool": "contrast", "params": {"amount": 1.3}, "reason": "پرجان"},
                    {"tool": "saturation", "params": {"amount": 1.2}, "reason": "رنگ"}]
        with patch("services.ai.gateway.text_provider", return_value=fake), patch("services.ai.router.models_for", return_value=["x"]):
            body = self.plan(mode="DIRECTED", instruction="ملایم‌ترش کن", previous=previous).json()
        self.assertIn("The plan the shop is looking at right now", fake.prompts[0])
        self.assertIn("saturation", fake.prompts[0])
        self.assertEqual([o["tool"] for o in body["operations"]], ["contrast"])
        # پیگیری که جواب نگرفت ⇒ همان طرحِ فعلی می‌ماند (نه جایگزینِ بی‌ربط)
        down = FakeModel(exc=OllamaError("خطای سرویس 402"))
        with patch("services.ai.gateway.text_provider", return_value=down), patch("services.ai.router.models_for", return_value=["x"]):
            body = self.plan(mode="DIRECTED", instruction="گرم‌ترش کن", previous=previous).json()
        self.assertTrue(body["ai"]["kept_previous"])
        self.assertEqual([o["tool"] for o in body["operations"]], ["contrast", "saturation"])
        self.assertEqual(body["ai"]["error_code"], "no_credit")

    def test_suggest_and_manual_never_ask_the_model(self):
        with patch("services.editing.agent.ask_model_ex") as ask:
            self.assertEqual(self.plan(mode="SUGGEST").status_code, 200)
            self.assertEqual(self.plan(mode="MANUAL", operations=[{"tool": "contrast", "params": {"amount": 1.2}}]).status_code, 200)
        ask.assert_not_called()

    def test_explain_failure_unit(self):
        code, msg = agent.explain_failure(OllamaError("خطای سرویس 402: x"))
        self.assertEqual(code, "no_credit")
        code, _ = agent.explain_failure(RuntimeError("boom"))
        self.assertEqual(code, "error")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class WorkspaceApiTests(TestCase):
    """فضای کارِ دستی: بسته‌ی رسانه، پروژه، پیش‌نمایشِ سبک، زیرنویس، رندر (ffmpeg واقعی)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which(FFMPEG) and not shutil.which("ffmpeg"):
            return
        root = Path(TEMP_MEDIA)
        cls.small = make_video(root / "uploads/videos/small.mp4", seconds=3)
        cls.big = make_video(root / "uploads/videos/big.mp4", size="1280x720", seconds=1, audio=False)
        cls.music = root / "uploads/audio.wav"
        cls.music.parent.mkdir(parents=True, exist_ok=True)
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", str(cls.music))

    def setUp(self):
        if not hasattr(self, "small"):
            self.skipTest("ffmpeg نیست")
        self.owner = User.objects.create_user("ws-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه فضای کار")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}"
        self.up_small = UploadedVideo.objects.create(store=self.store, title="کوچک", video="uploads/videos/small.mp4",
                                                     state="READY", duration=3.0, has_audio=True)
        self.up_big = UploadedVideo.objects.create(store=self.store, title="بزرگ", video="uploads/videos/big.mp4",
                                                   state="READY", duration=1.0, has_audio=False)

    def call(self, method, url, body=None):
        fn = getattr(self.client, method)
        if body is None:
            return fn(self.base + url)
        return fn(self.base + url, json.dumps(body), content_type="application/json")

    def timeline(self, **extra):
        return {"format": {"width": 320, "height": 240, "fps": 25}, "tracks": [
            {"kind": "video", "clips": [
                {"ref": f"video:{self.up_small.pk}", "at": 0, "start": 0, "end": 2},
                {"ref": f"video:{self.up_big.pk}", "at": 2, "start": 0, "end": 1, "fit": "cover",
                 "transition": {"kind": "crossfade", "duration": 0.5}}]},
            {"kind": "text", "clips": [{"text": "قهوهٔ تازه", "at": 0.5, "duration": 1.5, "position": "bottom", "size": 9}]},
        ], **extra}

    def test_bin_lists_what_can_go_on_the_timeline_and_flags_big_clips(self):
        items = self.call("get", "/editor/bin/").json()
        by_ref = {i["ref"]: i for i in items["videos"]}
        small, big = by_ref[f"video:{self.up_small.pk}"], by_ref[f"video:{self.up_big.pk}"]
        self.assertEqual((small["kind"], small["has_audio"], small["proxy"]), ("video", True, "not_needed"))
        self.assertAlmostEqual(small["duration"], 3.0, delta=0.3)
        self.assertEqual(big["proxy"], "needed", "۷۲۰ پیکسل برای پیش‌نمایشِ مرورگر سنگین است")
        self.assertTrue(small["url"].endswith("small.mp4"))
        self.assertNotIn("path", small, "مسیرِ فایلِ سرور بیرون نمی‌رود")
        self.assertEqual(items["audio"], [])

    def test_proxy_job_builds_a_small_playable_copy_and_the_bin_then_says_ready(self):
        r = self.call("post", "/editor/proxy/", {"ref": f"video:{self.up_big.pk}"})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        item = next(i for i in self.call("get", "/editor/bin/").json()["videos"] if i["ref"] == f"video:{self.up_big.pk}")
        self.assertEqual(item["proxy"], "ready")
        proxy = Path(TEMP_MEDIA) / item["proxy_url"].split("/media/", 1)[1]
        v = next(s for s in probe(proxy)["streams"] if s["codec_type"] == "video")
        self.assertEqual(int(v["height"]), 480)
        again = self.call("post", "/editor/proxy/", {"ref": f"video:{self.up_big.pk}"}).json()
        self.assertEqual(again["proxy"], "ready")
        self.assertEqual(self.call("post", "/editor/proxy/", {"ref": "audio:1"}).status_code, 400)
        self.assertEqual(self.call("post", "/editor/proxy/", {"ref": "video:99999"}).status_code, 400)

    def test_project_crud_validation_and_no_path_smuggling(self):
        r = self.call("post", "/editor/projects/", {"title": "پروژه ۱", "data": self.timeline()})
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        pid = body["project"]["id"]
        self.assertTrue(body["check"]["ok"], body["check"])
        self.assertAlmostEqual(body["check"]["length"], 3.0, delta=0.1)
        # ref ِ ناشناخته ⇒ ذخیره می‌شود ولی «رندر نمی‌شود» و دلیلش فارسی است
        bad = self.timeline()
        bad["tracks"][0]["clips"][0]["ref"] = "video:424242"
        r = self.call("put", f"/editor/projects/{pid}/", {"data": bad})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["check"]["ok"])
        self.assertIn("پیدا نشد", r.json()["check"]["error"])
        # مسیرِ فایل به‌جای ref ⇒ نادیده گرفته می‌شود (ref لازم است)
        sneaky = self.timeline()
        sneaky["tracks"][0]["clips"][0] = {"ref": "../../etc/passwd", "path": "/etc/passwd", "at": 0, "end": 2}
        r = self.call("put", f"/editor/projects/{pid}/", {"data": sneaky})
        self.assertFalse(r.json()["check"]["ok"])
        r = self.call("post", f"/editor/projects/{pid}/render/", {})
        self.assertEqual(r.status_code, 400, "پروژهٔ ناسالم رندر نمی‌شود")
        self.assertEqual(Job.objects.filter(context__what="project").count(), 0)
        self.assertEqual(self.call("get", "/editor/projects/").json()["projects"][0]["title"], "پروژه ۱")
        self.assertEqual(self.call("put", f"/editor/projects/{pid}/", {"data": "x"}).status_code, 400)
        self.assertEqual(self.call("delete", f"/editor/projects/{pid}/").status_code, 204)
        self.assertEqual(self.call("get", f"/editor/projects/{pid}/").status_code, 404)

    def test_render_end_to_end_with_music_text_crossfade_and_program_tools(self):
        pid = self.call("post", "/editor/projects/", {"title": "نهایی"}).json()["project"]["id"]
        # صدای کتابخانه نیست ⇒ موسیقی را از ویدیوی دیگر نمی‌گیریم؛ ترکِ صدای دومِ همان ویدیو
        data = self.timeline(global_ops=[{"tool": "normalize_audio", "params": {"target": -16}},
                                         {"tool": "fade", "params": {"where": "out", "duration": 0.4}}])
        data["tracks"].append({"kind": "audio", "clips": [{"ref": f"video:{self.up_small.pk}", "at": 0, "start": 0, "end": 3, "volume": 0.3}]})
        self.call("put", f"/editor/projects/{pid}/", {"data": data})
        r = self.call("post", f"/editor/projects/{pid}/render/", {"quality": "draft"})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, "COMPLETED", job.error)
        project = VideoProject.objects.get(pk=pid)
        self.assertEqual(project.state, "READY", project.error)
        info = project.render_info
        self.assertAlmostEqual(info["seconds"], 3.0, delta=0.3)
        self.assertEqual(info["program_tools"], ["normalize_audio", "fade"])
        out = probe(Path(TEMP_MEDIA) / project.output.name)
        self.assertTrue(any(s["codec_type"] == "audio" for s in out["streams"]))
        v = next(s for s in out["streams"] if s["codec_type"] == "video")
        self.assertEqual((int(v["width"]), int(v["height"])), (320, 240))
        d = self.call("get", f"/editor/projects/{pid}/").json()["project"]
        self.assertTrue(d["output_url"].endswith(".mp4"))
        self.assertEqual(d["state"], "READY")

    def test_other_users_cannot_touch_the_workspace(self):
        pid = self.call("post", "/editor/projects/", {"title": "من"}).json()["project"]["id"]
        other = User.objects.create_user("intruder", password="x")
        self.client.force_login(other)
        for method, url in (("get", "/editor/bin/"), ("get", "/editor/projects/"), ("get", f"/editor/projects/{pid}/"),
                            ("delete", f"/editor/projects/{pid}/")):
            self.assertIn(self.call(method, url).status_code, (403, 404), (method, url))
        self.assertIn(self.call("post", f"/editor/projects/{pid}/render/", {}).status_code, (403, 404))

    def test_subtitle_lines_become_text_clips_material(self):
        srt = "1\n00:00:00,500 --> 00:00:01,800\nسلام\n\n2\n00:00:02,000 --> 00:00:03,000\nخوش آمدید\nبه فروشگاه\n"
        self.up_small.subtitles.save("s.srt", __import__("django").core.files.base.ContentFile(srt.encode("utf-8")), save=True)
        lines = self.call("post", "/editor/subtitles/", {"ref": f"video:{self.up_small.pk}"}).json()["lines"]
        self.assertEqual(lines[0], {"start": 0.5, "end": 1.8, "text": "سلام"})
        self.assertEqual(lines[1]["text"], "خوش آمدید به فروشگاه")
        r = self.call("post", "/editor/subtitles/", {"ref": f"video:{self.up_big.pk}"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("زیرنویس", r.json()["error"]["message"])
