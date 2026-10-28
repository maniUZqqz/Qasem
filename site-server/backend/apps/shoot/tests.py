"""آزمون‌های فیلم‌برداریِ هدایت‌شده: برنامه، الگوی جایگزین، وارسیِ عکس و ویدیو، آپلودِ تکه‌تکه، تدوین و پوستر.

همه با فایل‌های ساختگی (Pillow و ffmpeg ِ lavfi) و MEDIA_ROOT ِ موقت؛ بی‌اینترنت (هوش مصنوعی و گفتار mock می‌شوند).
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from rest_framework.test import APIClient

from apps.products.models import Product
from apps.stores.models import Store

from . import checks, media, poster, render, services
from . import plan as planmod
from .models import ShootOutput, ShootSession, ShootTake

def make_photo(path, *, blur=False, dark=False, offset=(0.0, 0.0), scale=0.45, size=(1200, 1600)):
    w, h = size
    img = Image.new("RGB", size, (236, 234, 228))
    d = ImageDraw.Draw(img)
    pw, ph = int(w * scale), int(h * scale * 0.8)
    cx, cy = int(w / 2 + offset[0] * w), int(h / 2 + offset[1] * h)
    x0, y0 = cx - pw // 2, cy - ph // 2
    d.rectangle([x0, y0, x0 + pw, y0 + ph], fill=(170, 55, 40))
    for i in range(0, pw, 14):
        d.line([(x0 + i, y0), (x0 + i, y0 + ph)], fill=(250, 210, 90), width=3)
    for j in range(0, ph, 22):
        d.line([(x0, y0 + j), (x0 + pw, y0 + j)], fill=(40, 30, 30), width=2)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(14))
    if dark:
        img = ImageEnhance.Brightness(img).enhance(0.15)
    img.save(path, "JPEG", quality=90)
    return Path(path)


def make_clip(path, seconds=3.0, size="360x640", src="testsrc2"):
    spec = f"{src}:size={size}:rate=30" if "=" in src else f"{src}=size={size}:rate=30"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([media_ff(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    spec, "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264",
                    "-preset", "ultrafast", str(path)], check=True)
    return Path(path)


def make_tone(path, seconds=6.0, freq=440):
    subprocess.run([media_ff(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", "-ac", "1", str(path)], check=True)
    return Path(path)


def media_ff():
    from services.video.ffmpeg import FFMPEG

    return FFMPEG


def probe(path):
    from services.video.ffmpeg import probe as ff_probe

    info = ff_probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"w": int(v["width"]), "h": int(v["height"]), "dur": float(info["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in info["streams"])}


class Base(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.TMP = tempfile.mkdtemp(prefix="shoot-tests-")
        cls._media = override_settings(MEDIA_ROOT=cls.TMP)
        cls._media.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media.disable()
        shutil.rmtree(cls.TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        U = get_user_model()
        self.user = U.objects.create_user("owner", "o@x.io", "pw")
        self.store = Store.objects.create(owner=self.user, name="فروشگاهِ آزمون")
        self.product = Product.objects.create(store=self.store, name="قهوهٔ عربیکا ۲۵۰ گرمی", price=250000,
                                              description="دانهٔ تازه برشته. عطرِ شکلاتی. آسیابِ متوسط.")
        self.work = Path(tempfile.mkdtemp(dir=self.TMP))


# ───────────────────────────── برنامه

class PlanTests(Base):
    def test_category_detection(self):
        self.assertEqual(planmod.detect_category("قهوه ترک"), "food")
        self.assertEqual(planmod.detect_category("کفش کتانی مردانه"), "shoes")
        self.assertEqual(planmod.detect_category("چیزِ ناشناخته"), "generic")
        # نام بر توضیح مقدم است؛ کلیدواژهٔ کوتاه فقط کلمهٔ کامل
        self.assertEqual(planmod.detect_category("ماگ سرامیکی قرمز", "مناسبِ قهوه و چای"), "home")
        self.assertEqual(planmod.detect_category("نوشیدنی انرژی‌زا"), "generic")

    def test_template_plan_is_complete(self):
        plan = planmod.template_plan(self.product)
        self.assertEqual(plan["category"], "food")
        self.assertGreaterEqual(len(plan["photos"]), 3)
        self.assertGreaterEqual(len(plan["video"]), 2)
        for p in plan["photos"]:
            self.assertTrue(p["instruction"] and p["key"].startswith("p_"))
            self.assertIn("arrow", p["overlay"])
        for i, v in enumerate(plan["video"], 1):
            self.assertEqual(v["key"], f"v{i}")
            self.assertTrue(2 <= v["duration"] <= 12)
            self.assertGreaterEqual(len(v["cues"]), 2)
            self.assertIn("ثانیه", v["instruction"])
        self.assertIn("تومان", plan["ad"]["price"])

    def test_validate_garbage_falls_back(self):
        plan, problems = planmod.validate_plan("not json", self.product)
        self.assertTrue(problems)
        self.assertEqual(plan["category"], "food")
        self.assertGreaterEqual(len(plan["photos"]), 3)

    def test_validate_cleans_model_output(self):
        raw = {
            "category": "food", "product_type": "قهوه", "features": ["عطرِ شکلاتی", "", "عطرِ شکلاتی", "تازه"],
            "photos": [{"angle": "front", "instruction": "روبه‌رو بگیر، کاملاً صاف و وسطِ کادر"},
                       {"angle": "45"}, {"angle": "spaceship"}, {"angle": "front"}, {"angle": "macro"}],
            "video": [{"move": "orbit", "duration": 99, "degrees": 900, "direction": "up",
                       "cues": [{"at": 0, "text": "شروع"}, {"at": 50, "text": "x"}]},
                      {"move": "dolly_in", "duration": "abc"}, {"move": "teleport"}],
            "ad": {"headline": "ق" * 200, "cta": ""},
        }
        plan, problems = planmod.validate_plan(raw, self.product)
        angles = [p["angle"] for p in plan["photos"]]
        self.assertEqual(angles[:3], ["front", "three_quarter", "detail"])
        self.assertEqual(len(angles), len(set(angles)))
        self.assertEqual(plan["features"], ["عطرِ شکلاتی", "تازه"])
        orbit = plan["video"][0]
        self.assertEqual((orbit["move"], orbit["duration"], orbit["degrees"], orbit["direction"]),
                         ("orbit", 12, 360, "right"))
        self.assertEqual(orbit["cues"], planmod.move_cues(orbit), "یک cue ِ معتبر کافی نیست ⇐ cue های قطعی")
        self.assertEqual(plan["video"][1]["move"], "push_in")
        self.assertEqual(plan["video"][1]["duration"], planmod.MOVES["push_in"]["duration"])
        self.assertEqual(len(plan["ad"]["headline"]), 60)
        self.assertEqual(plan["ad"]["cta"], "همین حالا سفارش بده")
        self.assertTrue(any("spaceship" in p for p in problems))
        self.assertTrue(any("teleport" in p for p in problems))

    def test_analyze_fallback_when_ai_unavailable(self):
        with mock.patch.object(planmod, "ask_model", return_value=(None, "قطع")):
            plan, source, notes = planmod.analyze(self.product)
        self.assertEqual(source, "template")
        self.assertIn("الگوی آماده", notes[0])
        self.assertGreaterEqual(len(plan["video"]), 2)

    def test_analyze_uses_ai_when_available(self):
        raw = {"category": "food", "photos": [{"angle": "top"}, {"angle": "detail"}, {"angle": "scale"}],
               "video": [{"move": "tilt", "direction": "down"}, {"move": "push_in"}],
               "features": ["عطرِ شکلاتی"]}
        with mock.patch.object(planmod, "ask_model", return_value=(raw, "بینایی + متن")):
            plan, source, _notes = planmod.analyze(self.product)
        self.assertEqual(source, "ai")
        self.assertEqual([p["angle"] for p in plan["photos"]], ["top", "detail", "scale"])
        self.assertEqual(plan["video"][0]["overlay"]["arrow"], "down")

    def test_ask_model_never_raises(self):
        with mock.patch("services.ai.gateway.text_provider", side_effect=RuntimeError("down")):
            raw, why = planmod.ask_model(self.product)
        self.assertIsNone(raw)
        self.assertIn("down", why)


# ───────────────────────────── وارسیِ عکس و ویدیو

class CheckTests(Base):
    def _judge(self, **kw):
        path = make_photo(self.work / "p.jpg", **kw)
        img = Image.open(path)
        return checks.judge_photo(checks.photo_metrics(img), planmod.ANGLES["front"]["check"])

    def codes(self, result):
        return {p["code"] for p in result["problems"]}

    def test_good_photo_passes(self):
        r = self._judge()
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.codes(r) & {"blurry", "dark", "small", "off_center"})

    def test_blurry_photo_fails(self):
        r = self._judge(blur=True)
        self.assertFalse(r["ok"])
        self.assertIn("blurry", self.codes(r))

    def test_dark_photo_fails(self):
        r = self._judge(dark=True)
        self.assertFalse(r["ok"])
        self.assertIn("dark", self.codes(r))

    def test_low_key_shallow_focus_photo_passes(self):
        # پس‌زمینهٔ تیره و محو + محصولِ تیز (مثلِ عکسِ واقعیِ ماگ که اول «تار و تاریک» حساب می‌شد): قبول
        img = Image.new("RGB", (1200, 1200), (30, 26, 22))
        d = ImageDraw.Draw(img)
        for i in range(0, 1200, 40):
            d.line([(i, 0), (i, 1200)], fill=(60, 50, 40), width=10)
        img = img.filter(ImageFilter.GaussianBlur(25))
        d = ImageDraw.Draw(img)
        d.rectangle([380, 360, 820, 860], fill=(240, 120, 100))
        for j in range(370, 860, 18):
            d.line([(380, j), (820, j)], fill=(255, 245, 235), width=3)
        path = self.work / "lowkey.jpg"
        img.save(path, quality=90)
        r = checks.judge_photo(checks.photo_metrics(Image.open(path)), planmod.ANGLES["front"]["check"])
        self.assertFalse(self.codes(r) & {"blurry", "soft", "dark"}, r)
        self.assertTrue(r["ok"], r)

    def test_small_and_off_center(self):
        r = self._judge(scale=0.15)
        self.assertIn("small", self.codes(r))
        r = self._judge(scale=0.3, offset=(0.3, 0.0))
        self.assertIn("off_center", self.codes(r))
        msg = next(p["message"] for p in r["problems"] if p["code"] == "off_center")
        self.assertIn("راست", msg)

    def test_vision_merge(self):
        base = {"ok": True, "score": 95.0, "problems": []}
        bad = checks.merge_vision(base, {"product_visible": False, "centered": True, "angle_ok": True,
                                         "verdict": "retake", "problems": ["محصول پیدا نیست"]})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["problems"][0]["message"], "محصول پیدا نیست")
        self.assertLess(bad["score"], 95)
        self.assertEqual(checks.merge_vision(base, None), base)

    def test_video_checks(self):
        clip = make_clip(self.work / "c.mp4", seconds=1.5)
        m = checks.video_metrics(clip, self.work / "w")
        self.assertAlmostEqual(m["duration"], 1.5, delta=0.2)
        r = checks.judge_video(m, {"min_seconds": 3})
        self.assertIn("short", {p["code"] for p in r["problems"]})
        clip2 = make_clip(self.work / "c2.mp4", seconds=4)
        r2 = checks.judge_video(checks.video_metrics(clip2, self.work / "w"), {"min_seconds": 3})
        self.assertTrue(r2["ok"], r2)


# ───────────────────────────── API: جلسه، آپلودِ تکه‌تکه، ذخیره در محصول

class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.c = APIClient()
        self.c.force_authenticate(self.user)
        self.base = f"/api/v1/stores/{self.store.pk}/shoot/"

    def _session(self, purpose="ad"):
        r = self.c.post(self.base + "sessions/", {"product": self.product.pk, "purpose": purpose,
                                                  "analyze": False}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def _upload(self, sid, shot, kind, path, *, chunk=200_000, name=None):
        data = Path(path).read_bytes()
        uid = "test" + shot.replace("_", "") + str(len(data))
        url = f"{self.base}sessions/{sid}/upload/"
        offset, last = 0, None
        while offset < len(data):
            part = data[offset:offset + chunk]
            last = self.c.post(url, {"upload_id": uid, "offset": offset, "total": len(data), "kind": kind,
                                     "shot": shot, "name": name or Path(path).name, "mode": "native",
                                     "vision": "0", "chunk": SimpleUploadedFile("c", part)}, format="multipart")
            self.assertIn(last.status_code, (200, 201), last.data)
            offset = last.data["received"]
        return last.data["take"]

    def test_overview_and_session(self):
        r = self.c.get(self.base)
        self.assertEqual(r.status_code, 200)
        self.assertIn("capabilities", r.data)
        self.assertEqual(r.data["products"][0]["id"], self.product.pk)
        s = self._session()
        self.assertEqual(s["plan_source"], "template")
        self.assertEqual(self.c.get(f"{self.base}sessions/{s['id']}/").data["id"], s["id"])

    def test_reuse_photo_session(self):
        s1 = self._session("photos")
        r = self.c.post(self.base + "sessions/", {"product": self.product.pk, "purpose": "photos", "reuse": True,
                                                  "analyze": False}, format="json")
        self.assertEqual(r.data["id"], s1["id"])

    def test_patch_plan_validates(self):
        s = self._session()
        plan = s["plan"]
        plan["video"][0]["duration"] = 500
        plan["photos"] = plan["photos"][:1] + [{"angle": "nope"}]
        r = self.c.patch(f"{self.base}sessions/{s['id']}/", {"plan": plan}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["plan_source"], "edited")
        self.assertEqual(r.data["plan"]["video"][0]["duration"], 12)
        self.assertGreaterEqual(len(r.data["plan"]["photos"]), 3)

    def test_chunked_upload_resume_and_checks(self):
        s = self._session("photos")
        photo = make_photo(self.work / "front.jpg")
        data = photo.read_bytes()
        url = f"{self.base}sessions/{s['id']}/upload/"
        first = self.c.post(url, {"upload_id": "resume-test-1", "offset": 0, "total": len(data), "kind": "photo",
                                  "shot": "p_front", "chunk": SimpleUploadedFile("c", data[:1000])},
                            format="multipart")
        self.assertEqual(first.data["received"], 1000)
        wrong = self.c.post(url, {"upload_id": "resume-test-1", "offset": 0, "total": len(data), "kind": "photo",
                                  "shot": "p_front", "chunk": SimpleUploadedFile("c", data[:1000])},
                            format="multipart")
        self.assertEqual(wrong.status_code, 409)
        self.assertEqual(wrong.data["received"], 1000)
        self.assertEqual(self.c.get(url, {"upload_id": "resume-test-1"}).data["received"], 1000)
        rest = self.c.post(url, {"upload_id": "resume-test-1", "offset": 1000, "total": len(data), "kind": "photo",
                                 "shot": "p_front", "vision": "0", "chunk": SimpleUploadedFile("c", data[1000:])},
                           format="multipart")
        self.assertEqual(rest.status_code, 201, rest.data)
        take = rest.data["take"]
        self.assertTrue(take["ok"], take)
        self.assertTrue(take["accepted"])
        self.assertTrue(take["thumb"].startswith("/media/shoot/"))

    def test_blurry_upload_asks_retake_and_save_photos_in_order(self):
        s = self._session("photos")
        keys = [p["key"] for p in s["plan"]["photos"]]
        bad = self._upload(s["id"], keys[0], "photo", make_photo(self.work / "b.jpg", blur=True))
        self.assertFalse(bad["ok"])
        self.assertFalse(bad["accepted"])
        self.assertTrue(bad["summary"])
        good0 = self._upload(s["id"], keys[0], "photo", make_photo(self.work / "g0.jpg"))
        good1 = self._upload(s["id"], keys[1], "photo", make_photo(self.work / "g1.jpg", scale=0.5))
        self.assertTrue(good0["accepted"] and good1["accepted"])
        r = self.c.post(f"{self.base}sessions/{s['id']}/save-photos/", {}, format="json")
        self.assertEqual(len(r.data["created"]), 2)
        images = list(self.product.images.order_by("order", "id"))
        self.assertEqual([i.pk for i in images], r.data["created"])
        self.assertTrue(images[0].is_main)
        self.assertIn(s["plan"]["photos"][0]["title"], images[0].alt_text)
        again = self.c.post(f"{self.base}sessions/{s['id']}/save-photos/", {}, format="json")
        self.assertEqual(again.data["created"], [], "دوباره زدن تکراری نمی‌سازد")

    def test_take_accept_toggle_and_delete(self):
        s = self._session("photos")
        bad = self._upload(s["id"], "p_" + s["plan"]["photos"][0]["angle"], "photo",
                           make_photo(self.work / "b.jpg", blur=True))
        url = f"{self.base}sessions/{s['id']}/takes/{bad['id']}/"
        self.assertTrue(self.c.patch(url, {"accepted": True}, format="json").data["accepted"])
        self.assertEqual(self.c.delete(url).status_code, 204)
        self.assertFalse(ShootTake.objects.filter(pk=bad["id"]).exists())

    def test_outputs_require_takes(self):
        s = self._session()
        r = self.c.post(f"{self.base}sessions/{s['id']}/outputs/", {"kind": "poster", "aspects": ["1:1"]},
                        format="json")
        self.assertEqual(r.status_code, 400)

    def test_other_user_cannot_see(self):
        s = self._session()
        other = get_user_model().objects.create_user("x", "x@x.io", "pw")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(f"{self.base}sessions/{s['id']}/").status_code, 404)


# ───────────────────────────── تدوین و پوستر

class RenderTests(Base):
    def _session_with_takes(self, n_video=2, photo=True):
        session = services.create_session(self.store, self.product, self.user, purpose="ad", analyze=False)
        for i, shot in enumerate(session.plan["video"][:n_video]):
            rel = f"{session.dir_rel}/takes/{shot['key']}_1.mp4"
            media.abs_path(rel).parent.mkdir(parents=True, exist_ok=True)
            make_clip(media.abs_path(rel), seconds=shot["duration"] + 1,
                      src="testsrc2" if i % 2 == 0 else "smptebars")
            ShootTake.objects.create(session=session, shot=shot["key"], kind="video", file=rel, width=360,
                                     height=640, duration=shot["duration"] + 1, ok=True, accepted=True, score=90,
                                     checks={"metrics": {"brightness": 90}})
        # یک برداشتِ بدتر برای همان نما که نباید انتخاب شود
        worse = f"{session.dir_rel}/takes/v1_2.mp4"
        make_clip(media.abs_path(worse), seconds=2, src="color=c=black")
        ShootTake.objects.create(session=session, shot="v1", kind="video", file=worse, width=360, height=640,
                                 duration=2, ok=True, accepted=True, score=40)
        if photo:
            rel = f"{session.dir_rel}/takes/{session.plan['photos'][0]['key']}_1.jpg"
            make_photo(media.abs_path(rel))
            ShootTake.objects.create(session=session, shot=session.plan["photos"][0]["key"], kind="photo",
                                     file=rel, width=1200, height=1600, ok=True, accepted=True, score=95)
        return session

    def test_best_take_is_highest_scored_accepted(self):
        session = self._session_with_takes()
        self.assertEqual(services.best_take(session, "v1").score, 90)

    @mock.patch.dict(render.SIZES, {"9:16": (360, 640), "1:1": (360, 360)})
    def test_video_pipeline_with_music_and_voice(self):
        session = self._session_with_takes()
        tone = make_tone(self.work / "music.wav", 20)
        voice = make_tone(self.work / "voice.mp3", 4, 220)
        out = services.new_output(session, kind="video", aspect="9:16", template="bold",
                                  options={"stabilize": True, "transition": "fade", "music": 1,
                                           "voiceover": True, "logo": True, "texts": {}})
        with mock.patch.object(render, "music_path", return_value=(tone, "آزمون")), \
                mock.patch("apps.shoot.voice.voiceover", return_value=(voice, "آزمون")):
            result = render.render_video(out)
        path = media.abs_path(result["file"])
        info = probe(path)
        self.assertEqual((info["w"], info["h"]), (360, 640))
        self.assertTrue(info["audio"])
        v = session.plan["video"]
        expected = v[0]["duration"] + v[1]["duration"] + render.STILL_SECONDS + 3.0 - 3 * render.XF
        self.assertAlmostEqual(info["dur"], expected, delta=0.6)
        self.assertEqual(result["stats"]["segments"][0]["take"],
                         services.best_take(session, "v1").pk, "بهترین برداشت انتخاب شد")
        self.assertTrue(media.abs_path(result["thumb"]).is_file())
        self.assertTrue(any("موسیقی" in s["step"] for s in result["stats"]["steps"]))
        self.assertEqual(result["stats"]["stabilized"], media.capabilities()["stabilize"])

    @mock.patch.dict(render.SIZES, {"9:16": (360, 640), "1:1": (360, 360)})
    def test_video_square_from_landscape_without_transitions(self):
        session = self._session_with_takes(n_video=0)
        shot = session.plan["video"][0]
        rel = f"{session.dir_rel}/takes/wide.mp4"
        make_clip(media.abs_path(rel), seconds=5, size="640x360")
        ShootTake.objects.create(session=session, shot=shot["key"], kind="video", file=rel, width=640, height=360,
                                 duration=5, ok=True, accepted=True, score=99)
        out = services.new_output(session, kind="video", aspect="1:1", template="clean",
                                  options={"stabilize": False, "transition": "none", "texts": {"features": []}})
        result = render.render_video(out)
        info = probe(media.abs_path(result["file"]))
        self.assertEqual((info["w"], info["h"]), (360, 360))
        self.assertTrue(info["audio"], "صدای بی‌صدا هم باید باشد (اینستاگرام)")

    def test_render_task_marks_ready_or_failed(self):
        from .tasks import render_poster_task

        session = self._session_with_takes(n_video=0, photo=False)
        out = services.new_output(session, kind="poster", aspect="1:1", template="clean", options={})
        render_poster_task(out.pk)
        out.refresh_from_db()
        self.assertEqual(out.state, ShootOutput.State.FAILED)
        self.assertIn("عکس", out.error)

    def test_poster_templates_and_sizes(self):
        photo = Image.open(make_photo(self.work / "p.jpg"))
        cut = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
        ImageDraw.Draw(cut).ellipse([50, 50, 350, 550], fill=(200, 40, 40, 255))
        texts = {"title": "قهوهٔ عربیکای تازه‌برشته با عطرِ شکلاتی", "features": ["عطرِ شکلاتی", "برشتِ متوسط",
                                                                             "وزن: ۲۵۰ گرم"],
                 "price": "۲۵۰٬۰۰۰ تومان", "old_price": "۳۰۰٬۰۰۰ تومان", "cta": "همین حالا سفارش بده"}
        for template in poster.TEMPLATES:
            for aspect, size in poster.SIZES.items():
                for cutout in (None, cut):
                    img = poster.compose(photo, size=size, template=template, texts=texts, cutout=cutout,
                                         store_name="فروشگاهِ آزمون")
                    self.assertEqual(img.size, size)
                    lo, hi = img.convert("L").getextrema()
                    self.assertGreater(hi - lo, 100, (template, aspect))

    def test_render_poster_without_node_uses_blur(self):
        session = self._session_with_takes(n_video=0)
        out = services.new_output(session, kind="poster", aspect="4:5", template="bold",
                                  options={"cutout": True, "texts": {"cta": "بخرید"}})
        with mock.patch("apps.photoedit.services.node_status", return_value={"online": False, "nodes": []}):
            result = render.render_poster(out)
        img = Image.open(media.abs_path(result["file"]))
        self.assertEqual(img.size, (1080, 1350))
        self.assertFalse(result["stats"]["cutout"])
        self.assertIn("خاموش", result["stats"]["notes"][0])

    def test_output_to_product_and_content(self):
        session = self._session_with_takes(n_video=0)
        out = services.new_output(session, kind="poster", aspect="1:1", template="minimal", options={"cutout": False})
        result = render.render_poster(out)
        services.set_output(out, state=ShootOutput.State.READY, file=result["file"], thumb=result["thumb"])
        r1 = services.output_to_product(out)
        self.assertTrue(self.product.images.filter(pk=r1["product_image"]).exists())
        r2 = services.output_to_content(out)
        from apps.content.models import GeneratedImage

        self.assertEqual(GeneratedImage.objects.get(pk=r2["generated_image"]).kind, "POSTER")

    def test_delete_session_removes_files(self):
        session = self._session_with_takes(n_video=1, photo=False)
        folder = media.abs_path(session.dir_rel)
        self.assertTrue(folder.is_dir())
        services.delete_session(session)
        self.assertFalse(folder.exists())
        self.assertFalse(ShootSession.objects.filter(pk=session.pk).exists())
