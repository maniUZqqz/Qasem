"""آزمونِ واقعیِ سرتاسری روی همین سرور: رندرِ ۳ ثانیه‌ای ۵۴۰p با متنِ فارسی ⇒ MP4 قابل‌پخش؛ کدِ نمونه؛ لایه‌های امنیتیِ زمانِ اجرا.

بدونِ ابزارِ ساخته‌شده (manage.py motion_build) این آزمون‌ها خودشان را رد می‌کنند (skip)، نه شکست."""
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import runner, samples
from .models import MotionRender

User = get_user_model()
FFMPEG = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/usr/local/bin/ffprobe"


def ready() -> bool:
    return runner.site_status()["ready"] and bool(runner.node_bin()) and (runner.repo_motion_dir() / "node_modules" / "sucrase").exists()


def probe(path: Path) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                          "stream=codec_name,width,height,nb_read_frames,r_frame_rate,pix_fmt", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    return {**d["streams"][0], "duration": float(d["format"]["duration"])}


def frame_png(video: Path, at: float, dest: Path) -> Image.Image:
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", str(dest)], check=True, capture_output=True)
    return Image.open(dest).convert("RGB")


def share_near(im: Image.Image, rgb, tol=40) -> float:
    n = sum(1 for p in im.getdata() if abs(p[0] - rgb[0]) < tol and abs(p[1] - rgb[1]) < tol and abs(p[2] - rgb[2]) < tol)
    return n / (im.size[0] * im.size[1])


class RealRenders(TestCase):
    def setUp(self):
        if not ready():
            self.skipTest("motion toolchain is not built on this machine (manage.py motion_build)")
        self.media = tempfile.mkdtemp(prefix="nmmotion-e2e-")
        self.ov = override_settings(MEDIA_ROOT=self.media)
        self.ov.enable()
        self.owner = User.objects.create_user("motion-e2e", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", colors={"primary": "#126F85", "secondary": "#163F75"})
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/motion"

    def tearDown(self):
        self.ov.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def video_of(self, render_id: int) -> Path:
        from apps.content.models import UploadedVideo

        render = MotionRender.objects.get(pk=render_id)
        return Path(UploadedVideo.objects.get(pk=render.video_id).video.path)

    def test_template_render_3s_540p_with_persian_text(self):
        spec = {"style": "flat-vector", "aspect": "9:16", "lang": "fa", "brand": {"colors": ["#126F85", "#163F75"], "use_brand_colors": True},
                "scenes": [{"type": "title", "duration": 3, "kicker": "چغر", "title": "با چغر، چغرتر شو", "subtitle": "دستیارِ هوش مصنوعیِ مربی‌ها"}]}
        r = self.api.post(f"{self.base}/renders/", {"mode": "template", "spec": spec, "quality": "540", "target": "site"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        d = self.api.get(f"{self.base}/renders/{r.json()['render']['id']}/").json()["render"]
        self.assertEqual(d["state"], "READY", d)
        self.assertEqual((d["width"], d["height"]), (540, 960))
        video = self.video_of(d["id"])
        info = probe(video)
        self.assertEqual(info["codec_name"], "h264")
        self.assertEqual((info["width"], info["height"]), (540, 960))
        self.assertEqual(info["pix_fmt"], "yuv420p")
        self.assertEqual(int(info["nb_read_frames"]), 90)
        self.assertAlmostEqual(info["duration"], 3.0, delta=0.15)
        tmp = Path(tempfile.mkdtemp())
        try:
            im = frame_png(video, 2.0, tmp / "f.png")
            bg_rgb, bg_count = Counter(im.getdata()).most_common(1)[0]
            self.assertGreater(bg_count / (540 * 960), 0.35)                      # the style's background fills most of the frame
            self.assertGreater(1 - share_near(im, bg_rgb, 12), 0.03, "the Persian title / subtitle must be drawn")
            self.assertGreater(share_near(im, (0x12, 0x6F, 0x85), 38), 0.0015, "the store's brand colour (#126F85) is used for the accent")
            band = im.crop((0, int(960 * 0.28), 540, int(960 * 0.72)))            # the text sits in the middle band
            self.assertGreater(1 - share_near(band, bg_rgb, 12), 0.06)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(d["poster_url"])
        self.assertGreater(d["bytes"], 3000)

    def test_two_styles_do_not_look_alike(self):
        frames = {}
        for style in ("pixel-art", "watercolor"):
            spec = {"style": style, "aspect": "1:1", "lang": "fa", "scenes": [{"type": "title", "duration": 2, "title": "سلام", "subtitle": "دنیا"}]}
            r = self.api.post(f"{self.base}/renders/", {"mode": "template", "spec": spec, "quality": "360", "target": "site"}, format="json")
            d = self.api.get(f"{self.base}/renders/{r.json()['render']['id']}/").json()["render"]
            self.assertEqual(d["state"], "READY", d)
            tmp = Path(tempfile.mkdtemp())
            frames[style] = frame_png(self.video_of(d["id"]), 1.2, tmp / "f.png").resize((60, 60))
            shutil.rmtree(tmp, ignore_errors=True)
        a, b = frames["pixel-art"], frames["watercolor"]
        diff = sum(abs(x[0] - y[0]) + abs(x[1] - y[1]) + abs(x[2] - y[2]) for x, y in zip(a.getdata(), b.getdata())) / (60 * 60 * 3 * 255)
        self.assertGreater(diff, 0.12, "pixel art and watercolor must be different visual systems, not a colour swap")

    def test_pixel_art_text_is_not_invisible_at_a_reduced_scale(self):
        """regression: the pixelation filter's 1-px sampling dot rounded to nothing on a page with devicePixelRatio < 1 (540p / 360p renders)."""
        spec = {"style": "pixel-art", "aspect": "1:1", "lang": "en", "scenes": [{"type": "stat", "duration": 2, "value": "88", "count_up": False}]}
        r = self.api.post(f"{self.base}/renders/", {"mode": "template", "spec": spec, "quality": "360", "target": "site"}, format="json")
        d = self.api.get(f"{self.base}/renders/{r.json()['render']['id']}/").json()["render"]
        self.assertEqual(d["state"], "READY", d)
        tmp = Path(tempfile.mkdtemp())
        try:
            im = frame_png(self.video_of(d["id"]), 1.2, tmp / "f.png")
            band = im.crop((0, int(im.size[1] * 0.25), im.size[0], int(im.size[1] * 0.75)))
            self.assertGreater(share_near(band, (0xF4, 0xF4, 0xF4), 40), 0.02, "the big pixel-art number must be drawn")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_code_mode_sample_renders(self):
        r = self.api.post(f"{self.base}/renders/", {"mode": "code", "code": samples.HELLO, "quality": "360", "target": "site", "width": 1080, "height": 1920}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        d = self.api.get(f"{self.base}/renders/{r.json()['render']['id']}/").json()["render"]
        self.assertEqual(d["state"], "READY", d)
        self.assertEqual((d["width"], d["height"]), (360, 640))
        self.assertAlmostEqual(d["duration_s"], 5.0, delta=0.2)

    def test_styled_code_sample_uses_the_studio_styles(self):
        r = self.api.post(f"{self.base}/renders/", {"mode": "code", "code": samples.STYLED, "quality": "360", "target": "site", "width": 1080, "height": 1350}, format="json")
        d = self.api.get(f"{self.base}/renders/{r.json()['render']['id']}/").json()["render"]
        self.assertEqual(d["state"], "READY", d)
        self.assertEqual((d["width"], d["height"]), (360, 450))


SANDBOX_NET = """
import React from "react";
import { AbsoluteFill, delayRender, continueRender } from "remotion";
export const config = { width: 270, height: 480, fps: 30, durationInFrames: 30 };
export default function V() {
  const [h] = React.useState(() => delayRender("probe"));
  const [res, setRes] = React.useState("PENDING");
  React.useEffect(() => {
    let done = false;
    const fin = (v) => { if (!done) { done = true; setRes(v); setTimeout(() => continueRender(h), 50); } };
    const locked = String(fetch).indexOf("nm-motion") >= 0 && String(WebSocket).length > 0;
    try { fetch("http://example.com/").then(() => fin("OPEN"), () => fin(locked ? "BLOCKED" : "OPEN")); } catch (e) { fin(locked ? "BLOCKED" : "OPEN"); }
  }, []);
  return <AbsoluteFill style={{ background: res === "BLOCKED" ? "#00ff00" : "#ff0000" }} />;
}
"""

SANDBOX_FS = """
import fs from "fs";
export const config = { width: 270, height: 480, fps: 30, durationInFrames: 10 };
export default function V() { return <div>{String(fs)}</div>; }
"""

SANDBOX_LONG = """
import { AbsoluteFill } from "remotion";
export const config = { width: 270, height: 480, fps: 30, durationInFrames: 18000 };
export default function V() { return <AbsoluteFill />; }
"""


class RuntimeSandbox(TestCase):
    """لایه‌های بعد از اسکنر: حتی اگر کدی از اسکنر رد شود (این‌جا عمداً دورش می‌زنیم)، در صفحه نمی‌تواند به بیرون برسد."""

    def setUp(self):
        if not ready():
            self.skipTest("motion toolchain is not built on this machine (manage.py motion_build)")
        self.work = Path(tempfile.mkdtemp(prefix="nmmotion-sbx-"))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def render(self, code: str, max_seconds=5):
        res = runner.compile_code(code, scan=False)
        self.assertTrue(res["ok"], res)
        (self.work / "user.js").write_text(res["js"], encoding="utf-8")
        job = {"composition": "User", "props": {}, "user_js": str(self.work / "user.js"), "out": str(self.work / "out.mp4"), "scale": 1.0, "max_seconds": max_seconds}
        return runner.run_render(job, workdir=self.work, timeout=240)

    def test_network_and_globals_are_locked_in_the_page(self):
        done = self.render(SANDBOX_NET)
        out = Path(done["out"])
        self.assertTrue(out.is_file())
        im = frame_png(out, 0.5, self.work / "f.png")
        r, g, b = im.getpixel((100, 100))
        self.assertGreater(g, 200, f"fetch / sockets must be locked in code mode (pixel {r},{g},{b})")
        self.assertLess(r, 60)

    def test_a_module_outside_the_allowlist_cannot_be_loaded_at_run_time(self):
        with self.assertRaises(runner.RenderError) as cm:
            self.render(SANDBOX_FS)
        self.assertIn("غیرمجاز", str(cm.exception))

    def test_length_cap_is_enforced_by_the_loader(self):
        done = None
        try:
            done = self.render(SANDBOX_LONG, max_seconds=2)
        except runner.RenderError:
            return                      # refused: fine
        # clamped: never longer than the cap
        self.assertLessEqual(done["frames"] / done["fps"], 2.01)
