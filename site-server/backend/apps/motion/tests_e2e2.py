"""آزمونِ واقعیِ نسخهٔ ۲ روی همین سرور (بدونِ ابزارِ ساخته‌شده خودشان را رد می‌کنند):

  · هر ۳۳ قطعه با متنِ فارسی در ۳ نسبتِ ۹:۱۶، ۱:۱ و ۱۶:۹ فریمِ واقعی می‌دهد و از کنترلِ کیفیتِ هندسی (بدونِ خطا) می‌گذرد؛
  · یک رندرِ واقعیِ سرتاسری با گویندهٔ فارسی (Piper) + موسیقی + افکت: MP4 با صدا، ‎-۱۴ LUFS، زمانِ کلمه‌ها، گزارشِ QA؛
  · (فقط با NM_REAL_WORLD_OUT=<پوشه>) دو ویدیوی کوتاهِ «چغر» با واقعیت‌های docs/chagher/brand-facts-fa.md؛ فریم‌ها و گزارش‌ها همان‌جا ذخیره می‌شود.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.stores.models import Store

from . import components, pipeline, qa, qa_browser, runner, services, sound, specs
from .models import MotionRender

User = get_user_model()
FFMPEG = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/usr/local/bin/ffprobe"
OUT = os.environ.get("NM_REAL_WORLD_OUT", "")


def ready() -> bool:
    return runner.site_status()["ready"] and (runner.tools_dir() / "qa.mjs").is_file()


def sample_specs(aspect: str) -> list:
    """هر ۳۳ قطعه، ≤۱۴ صحنه در هر طرح ⇒ ۳ طرح؛ همان نمونه‌های فارسیِ کتابخانه."""
    ids = [i for i in components.COMPONENTS if not os.environ.get("NM_E2E_ONLY") or i in os.environ["NM_E2E_ONLY"].split(",")]
    out = []
    for k in range(0, len(ids), 12):
        scenes = [dict(components.COMPONENTS[i]["sample"]) for i in ids[k:k + 12]]
        out.append({"style": "flat-vector", "aspect": aspect, "fps": 30, "lang": "fa", "platform": "reels" if aspect == "9:16" else "",
                    "brand": {"use_brand_colors": True, "show_logo": False, "colors": ["#126F85", "#163F75"]}, "scenes": scenes})
    return out


class Base(TestCase):
    def setUp(self):
        if not ready():
            self.skipTest("motion toolchain (bundle + browser + qa.mjs) is not built on this machine (manage.py motion_build)")
        self.media = tempfile.mkdtemp(prefix="nmmotion-e2e2-")
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()
        self.owner = User.objects.create_user("motion-e2e2", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", description="دستیار هوش مصنوعیِ مربی‌ها", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.work = Path(tempfile.mkdtemp(prefix="nmmotion-e2e2-work-"))

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)


class EveryComponent(Base):
    def test_every_component_renders_in_three_aspects_and_passes_the_geometry_qa(self):
        problems, warns, before_loop, total = [], [], [], 0
        lock = runner.SiteLock()
        lock.acquire()
        try:
            for aspect in ("9:16", "1:1", "16:9"):
                for n, raw in enumerate(sample_specs(aspect)):
                    spec = specs.normalize_spec(raw)
                    out_dir = Path(OUT) / "components" / aspect.replace(":", "x") if OUT else None
                    measure = qa_browser.make_measure(self.store, workdir=self.work / f"{aspect[0]}{n}", media_dir=out_dir, prefix=f"p{n}")
                    shots = measure(spec)
                    self.assertEqual(len(shots), 2 * len(spec["scenes"]))
                    for s in shots:
                        total += 1
                        texts = [b for b in s["boxes"] if b["kind"] == "text" and b["scene"] == s["scene"]]
                        sc = spec["scenes"][s["scene"]]
                        if not texts and sc["type"] not in ("countdown", "ticker"):          # the marquee draws its own, deliberately cropped text
                            problems.append(f"{aspect} scene {s['scene']} ({sc['type']}) drew no text")
                    for f in qa.geometry_findings(spec, shots):
                        label = f"{aspect} {spec['scenes'][f['scene']]['type']}: {f['code']} - {f['message']}"
                        before_loop.append(label + (" [auto-fix]" if f["ops"] else " [no fix]"))
                        if f["severity"] == "error" and not f["ops"]:
                            problems.append(label)                                      # an error the loop could not even try to fix
                    # the loop: whatever it can fix is fixed and re-measured; no error may remain
                    rep = qa.run_loop(spec, measure=measure, rounds=3, max_total=specs.MAX_TOTAL_S_NODE)
                    for f in rep["remaining"]:
                        label = f"{aspect} {f['message']}"
                        (problems if f["severity"] == "error" else warns).append(label + " (after the loop)")
        finally:
            lock.release()
        if OUT:
            Path(OUT).mkdir(parents=True, exist_ok=True)
            (Path(OUT) / "components-qa.json").write_text(json.dumps({"shots": total, "errors": problems, "warnings": warns, "raw_findings_before_the_loop": before_loop}, ensure_ascii=False, indent=1), encoding="utf-8")
        self.assertEqual(problems, [], "\n".join(problems))
        if not os.environ.get("NM_E2E_ONLY"):
            self.assertGreaterEqual(total, 33 * 2 * 3)


def probe_audio(path: Path) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,codec_name,channels,sample_rate,duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def loudness(path: Path) -> float:
    import re

    p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-af", "loudnorm=I=-14:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r'"input_i"\s*:\s*"(-?[\d.]+)"', p.stderr).group(1))


def run_pipeline(store, owner, spec: dict, title: str, quality: str = "540") -> MotionRender:
    r = services.create(store, owner, mode="template", title=title, spec=spec, quality=quality, target="site", qa=True)
    outcome = pipeline.prepare_render(r, geometry=True)
    r.refresh_from_db()
    assert outcome == "ready", (outcome, r.message, r.error)
    services.start(r)
    services.render_on_site(r)
    r.refresh_from_db()
    return r


@override_settings(AUTOEDIT_STARTER_MUSIC=True)          # the site's own starter music (CC0) - switched off in test runs by default
class EndToEnd(Base):
    def test_a_real_render_with_voice_music_and_sfx_has_synced_words_and_minus_14_lufs(self):
        if not Path(FFMPEG).exists():
            self.skipTest("ffmpeg missing")
        spec = specs.normalize_spec({
            "style": "flat-vector", "aspect": "9:16", "fps": 30, "lang": "fa", "platform": "reels",
            "brand": {"use_brand_colors": True, "show_logo": False, "colors": ["#126F85", "#163F75"]},
            "scenes": [
                {"type": "kinetic_title", "duration": 2, "text": "با چغر، چغر تر شو", "narration": "با چغر، چغر تر شو"},
                {"type": "checklist", "duration": 2, "title": "چه دارد؟", "items": ["برنامهٔ ورزشی", "برنامهٔ غذایی", "خروجی PDF"]},
            ],
            "audio": {"voice": {"on": True, "voice_id": "auto"}, "music": {"on": True, "ref": "auto", "level_db": -20}, "sfx": True, "beat_sync": True},
        })
        r = run_pipeline(self.store, self.owner, spec, "e2e-sound", quality="360")
        self.assertEqual(r.state, MotionRender.State.READY, r.error or r.message)
        info = r.audio_info
        self.assertTrue(info.get("has_audio"), info)
        self.assertIn(info["voice"]["cue_source"], ("estimate", "asr", "tts", "mixed"))
        self.assertTrue(info.get("music"), info)
        final = r.spec
        for sc in final["scenes"]:
            self.assertTrue(sc.get("cues"))
        self.assertGreater(final["scenes"][0]["duration"], 2.0)             # the speech stretched the scene
        from apps.content.models import UploadedVideo

        uv = UploadedVideo.objects.get(pk=r.video_id)
        path = Path(self.media) / uv.video.name
        streams = probe_audio(path)["streams"]
        self.assertEqual({s["codec_type"] for s in streams}, {"video", "audio"})
        self.assertTrue(uv.has_audio)
        lufs = loudness(path)
        self.assertTrue(-16.0 <= lufs <= -12.0, lufs)
        self.assertTrue(r.qa["rounds"], "the quality check ran before the render")
        self.assertTrue(r.qa["geometry"], r.qa.get("geometry_error"))


CHAGHER_FACTS = "docs/chagher/brand-facts-fa.md"


def chagher_specs() -> list:
    """دو ویدیوی کوتاه با واقعیت‌های brand-facts-fa.md: هیچ قیمتِ تأییدنشده، آماری یا نظرِ مشتریِ ساختگی."""
    brand = {"use_brand_colors": True, "show_logo": False, "colors": ["#126F85", "#163F75"]}
    a = {"style": "flat-vector", "aspect": "9:16", "fps": 30, "lang": "fa", "platform": "reels", "brand": brand, "scenes": [
        {"type": "kinetic_title", "duration": 3, "kicker": "چغر", "text": "با چغر، چغر تر شو", "emphasis": ["چغر"],
         "overlays": [{"type": "sticker", "kind": "emoji", "emoji": "muscle", "anchor": "top-end", "at": 0.8}]},
        {"type": "feature_cards", "duration": 5, "title": "دستیار هوش مصنوعیِ مربی‌ها", "cards": [
            {"icon": "zap", "title": "سریع", "text": "پیش‌نویسِ برنامه در کمتر از یک دقیقه"},
            {"icon": "target", "title": "اختصاصی", "text": "برنامهٔ ورزشی و غذاییِ هر ورزشکار"},
            {"icon": "clipboard-list", "title": "خروجیِ PDF", "text": "برندشده و قابل‌چاپ"}], "transition": "wipe"},
        {"type": "steps", "duration": 4, "title": "چهار قدم", "steps": [{"title": "ثبت‌نام"}, {"title": "خریدِ توکن"}, {"title": "واردکردنِ اطلاعاتِ مجموعه"}, {"title": "تولیدِ برنامه"}], "transition": "push"},
        {"type": "social_cta", "duration": 4, "title": "همین حالا امتحان کنید", "platform": "website", "handle": "chagher.ir", "note": "پیش‌نویس؛ تصمیمِ نهایی با مربی است", "button": "ورود به چغر"}],
         "audio": {"voice": {"on": True, "voice_id": "auto"}, "music": {"on": True, "ref": "auto", "level_db": -22}, "sfx": True, "beat_sync": True}}
    b = {"style": "flat-vector", "aspect": "9:16", "fps": 30, "lang": "fa", "platform": "reels", "brand": brand, "captions": {"on": True, "position": "lower"}, "scenes": [
        {"type": "title", "duration": 3, "kicker": "چغر", "title": "هزینهٔ ساخت با هوش مصنوعی", "subtitle": "بر حسبِ توکن"},
        {"type": "bar_chart", "duration": 4, "title": "چند توکن؟", "bars": [{"label": "برنامهٔ کامل", "value": 50}, {"label": "فقط ورزشی", "value": 25}, {"label": "فقط غذایی", "value": 25}, {"label": "ویرایش", "value": 25}], "unit": "توکن", "transition": "zoom"},
        {"type": "counter", "duration": 3, "kicker": "کتابخانهٔ حرکت‌ها", "items": [{"value": "1300", "unit": "+", "label": "حرکت با نامِ فارسی، گیف و عکس"}], "transition": "iris"},
        {"type": "cta", "duration": 3, "title": "برنامهٔ ورزشی و غذاییِ هر ورزشکار", "button": "شروعِ رایگان", "note": "بدونِ کارتِ اعتباری"}],
         "audio": {"voice": {"on": True, "voice_id": "auto"}, "music": {"on": True, "ref": "auto", "level_db": -22}, "sfx": True, "beat_sync": True}}
    return [("chagher-intro", a), ("chagher-tokens", b)]


@override_settings(AUTOEDIT_STARTER_MUSIC=True)
class RealWorld(Base):
    def test_two_chagher_videos_through_the_whole_pipeline(self):
        if not OUT:
            self.skipTest("set NM_REAL_WORLD_OUT=<folder> to make the two Chagher videos")
        out = Path(OUT)
        out.mkdir(parents=True, exist_ok=True)
        from apps.content.models import UploadedVideo

        summary = {}
        for name, raw in chagher_specs():
            spec = specs.normalize_spec(raw)
            before = [(s["type"], s["duration"]) for s in spec["scenes"]]
            r = run_pipeline(self.store, self.owner, spec, name, quality="540")
            uv = UploadedVideo.objects.filter(pk=r.video_id).first()
            summary[name] = {"state": r.state, "error": r.error, "before": before, "after": [(s["type"], s["duration"]) for s in r.spec["scenes"]], "qa": r.qa, "audio": r.audio_info,
                             "bytes": r.bytes, "duration_s": r.duration_s}
            if uv is not None:
                mp4 = Path(self.media) / uv.video.name
                shutil.copyfile(mp4, out / f"{name}.mp4")
                for k, at in enumerate([0.9, 3.5, 7.0, 10.5, 14.0, max(0.5, r.duration_s - 1.5)]):
                    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(mp4), "-frames:v", "1", "-vf", "scale=360:-2", str(out / f"{name}-f{k}.jpg")], check=False)
                summary[name]["lufs"] = loudness(mp4)
            (out / f"{name}.json").write_text(json.dumps(summary[name], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            self.assertEqual(r.state, MotionRender.State.READY, r.error)
            self.assertEqual([f["message"] for f in r.qa["remaining"] if f["severity"] == "error"], [], "no unresolved error is left in a plan the pipeline delivers")
            self.assertTrue(r.audio_info.get("has_audio"))
        self.assertEqual(len(summary), 2)
        _ = sound, qa


class Overlays(Base):
    def test_overlays_render_on_top_of_a_scene_inside_the_platforms_safe_area(self):
        spec = specs.normalize_spec({
            "style": "flat-vector", "aspect": "9:16", "fps": 30, "lang": "fa", "platform": "reels",
            "brand": {"use_brand_colors": True, "show_logo": False, "colors": ["#126F85", "#163F75"]},
            "scenes": [{"type": "title", "duration": 6, "title": "با چغر، چغر تر شو", "subtitle": "دستیار هوش مصنوعیِ مربی‌ها", "overlays": [
                {"type": "lower_third", "name": "نامِ مربی", "role": "مربیِ نمونه", "at": 0.5},
                {"type": "sticker", "text": "جدید", "kind": "burst", "anchor": "top-end", "at": 0.5},
                {"type": "social_cta", "handle": "chagher.ir", "platform": "website", "anchor": "bottom-start", "at": 0.5, "title": "ما را ببینید"}]}],
        })
        lock = runner.SiteLock()
        lock.acquire()
        try:
            shots = qa_browser.make_measure(self.store, workdir=self.work / "ov", media_dir=None, prefix="ov")(spec)
        finally:
            lock.release()
        seen = {b["overlay"] for s in shots for b in s["boxes"] if b.get("overlay")}
        self.assertTrue({"lower_third", "sticker"} <= seen, seen)
        errors = [f["message"] for f in qa.geometry_findings(spec, shots) if f["severity"] == "error"]
        self.assertEqual(errors, [], "\n".join(errors))
