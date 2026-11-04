"""«قابِ مربعِ فروشگاه» در حالتِ دستی: کالا وسطِ قاب (``crop_format`` با ``subject="auto"`` و ``view``).

* پارامترها: ``subject`` و ``view`` وارسی می‌شوند؛ پروژه‌های قدیمی (بی subject) دقیقاً همان هندسهٔ قبل را دارند.
* تشخیص: همان نقشهٔ انرژیِ «سوژه (خودکار)»؛ کالای کوچک/کنارِ عکس/شفاف؛ کالا کلِ عکس ⇒ کلِ عکس.
* خروجی: کالا کامل و با حاشیه وسطِ قاب (حتی اگر دوربین از عکس بیرون بزند)، ``view`` ِ صریح جای تشخیص را می‌گیرد،
  H ِ ``frames`` با خروجیِ واقعی یکی است، بخشِ دیدنیِ عکس همان بازنمونهٔ کامل است.
"""
import numpy as np
from django.test import SimpleTestCase
from PIL import Image, ImageDraw
from unittest import mock

from . import catalog, frames, ops

STORE = {"format": "custom", "size": 2000, "fit": "contain", "focus": "center", "fill": "white", "padding": 6}
OLD_STORE = dict(STORE)                       # آنچه نسخهٔ قبلیِ پنل در پروژه‌ها ذخیره کرده (بی subject)
AUTO = STORE | {"subject": "auto"}


def product_photo(w=1200, h=800, box=(700, 300, 900, 500), *, alpha=False, noise=2.0, seed=3) -> Image.Image:
    """زمینهٔ سفیدِ کمی نویزی + یک کالای رنگی (مستطیلِ گرد با دایره‌ای رویش)."""
    rng = np.random.default_rng(seed)
    base = np.full((h, w, 3), 245.0) + rng.normal(0, noise, (h, w, 3))
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=18, fill=(190, 40, 60), outline=(60, 10, 20), width=5)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    r = min(box[2] - box[0], box[3] - box[1]) * 0.22
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(240, 200, 60))
    if alpha:
        a = Image.new("L", (w, h), 0)
        ImageDraw.Draw(a).rounded_rectangle(box, radius=18, fill=255)
        img = img.convert("RGBA")
        img.putalpha(a)
    return img


def run(img, params, ctx=None):
    p = catalog.normalize_params("crop_format", params, strict=False)
    return ops.op_crop_format(img, p, ctx if ctx is not None else {"notes": []})


def content_box(out: Image.Image, white=200, min_count=3):
    """جعبهٔ پیکسل‌های «غیرِ سفید» در خروجی (x0, y0, x1, y1)؛ ستون/ردیفی که کمتر از ``min_count`` پیکسل دارد (نویزِ تک‌پیکسلی) نیست."""
    a = np.asarray(out.convert("RGB"), dtype=np.int16)
    mask = (a.min(axis=2) < white)
    cols, rows = np.nonzero(mask.sum(axis=0) >= min_count)[0], np.nonzero(mask.sum(axis=1) >= min_count)[0]
    return int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1


class ParamTests(SimpleTestCase):
    def test_defaults_keep_the_old_behaviour(self):
        p = catalog.normalize_params("crop_format", OLD_STORE, strict=False)
        self.assertEqual((p["subject"], p["view"]), ("", []))
        spec = {x["key"]: x for x in catalog.tools()["crop_format"]["params"]}
        self.assertEqual(spec["subject"]["default"], "")
        self.assertEqual([o["value"] for o in spec["subject"]["options"]], ["", "auto"])
        self.assertEqual((spec["view"]["type"], spec["view"]["default"]), ("view", []))

    def test_subject_and_view_are_validated(self):
        norm = lambda **kw: catalog.normalize_params("crop_format", STORE | kw, strict=False)
        self.assertEqual(norm(subject="auto")["subject"], "auto")
        self.assertEqual(norm(subject="zzz")["subject"], "")
        self.assertEqual(norm(view=[2.5, 0.4, 0.6])["view"], [2.5, 0.4, 0.6])
        self.assertEqual(norm(view=[0.2, 0.5, 0.5])["view"], [1.0, 0.5, 0.5])        # zoom ≥ ۱
        self.assertEqual(norm(view=[99, 0.5, 0.5])["view"], [8.0, 0.5, 0.5])         # zoom ≤ ۸
        self.assertEqual(norm(view=[2, -5, 9])["view"], [2.0, -1.0, 2.0])            # مرکز در [−۱، ۲]
        for bad in ([1, 2], [1, 2, 3, 4], "x", None, [True, 0.5, 0.5], ["a", 1, 1], [float("nan"), 0.5, 0.5], {"a": 1}):
            self.assertEqual(norm(view=bad)["view"], [], bad)
        self.assertEqual(norm(view=[2.123456789, 0.123456789, 0.987654321])["view"], [2.1235, 0.12346, 0.98765])

    def test_catalog_still_valid_for_every_other_tool(self):
        self.assertEqual(catalog.normalize_params("crop_format", {})["format"], "square")
        for k in ("crop_rect", "rotate", "resize"):
            self.assertIsInstance(catalog.normalize_params(k, {}), dict)


class GeometryTests(SimpleTestCase):
    def old_contain(self, tw, th, w, h, pad):
        scale = min(tw / w, th / h) * (1.0 - 2.0 * pad / 100.0)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        return (nw, nh), ((tw - nw) // 2, (th - nh) // 2)

    def test_saved_projects_keep_their_framing(self):
        for fmt, size in (("custom", 2000), ("square", 0), ("story", 0), ("landscape", 0)):
            for w, h in ((1200, 800), (800, 1200), (1000, 1000), (3000, 500)):
                for pad in (0, 6, 25):
                    for extra in ({}, {"subject": ""}, {"subject": "", "view": [3, 0.2, 0.3]}):
                        p = catalog.normalize_params("crop_format", STORE | {"format": fmt, "size": size or 2000, "padding": pad} | extra,
                                                     strict=False)
                        geo = ops.crop_format_geometry(p, w, h)
                        tw, th = geo["size"]
                        fg, pos = self.old_contain(tw, th, w, h, pad)
                        self.assertEqual((geo["mode"], geo["fg"], geo["pos"]), ("contain", fg, pos), (fmt, w, h, pad, extra))
                        self.assertNotIn("view", geo)

    def test_auto_without_a_detection_is_the_old_geometry_and_says_so(self):
        p = catalog.normalize_params("crop_format", AUTO, strict=False)
        geo = ops.crop_format_geometry(p, 1200, 800)
        self.assertTrue(geo["approx"])
        self.assertEqual((geo["fg"], geo["pos"]), self.old_contain(2000, 2000, 1200, 800, 6))
        # تشخیص «کلِ عکس» (None) یا دوربینِ خنثی ⇒ دقیقاً همان
        for view in (None, [1.0, 0.5, 0.5]):
            geo = ops.crop_format_geometry(p, 1200, 800, None, lambda v=view: v)
            self.assertNotIn("view", geo)
            self.assertEqual((geo["fg"], geo["pos"]), self.old_contain(2000, 2000, 1200, 800, 6))

    def test_camera_math(self):
        p = catalog.normalize_params("crop_format", AUTO | {"view": [2.0, 0.25, 0.75]}, strict=False)
        geo = ops.crop_format_geometry(p, 1200, 800)
        v = geo["view"]
        base = min(2000 / 1200, 2000 / 800) * (1 - 0.12)
        self.assertAlmostEqual(v["scale"], base * 2.0, places=9)
        fw, fh = 1200 * v["scale"], 800 * v["scale"]
        # نقطهٔ (cx, cy) ِ عکس وسطِ قاب می‌افتد
        self.assertAlmostEqual(v["left"] + 0.25 * fw, 1000.0, places=6)
        self.assertAlmostEqual(v["top"] + 0.75 * fh, 1000.0, places=6)
        self.assertEqual(geo["fg"], (round(fw), round(fh)))
        H, size = frames.social_stage(1200, 800, AUTO | {"view": [2.0, 0.25, 0.75]})[:2]
        self.assertEqual(size, (2000, 2000))
        X, Y, W = H @ np.array([0.25 * 1200, 0.75 * 800, 1.0])
        self.assertAlmostEqual(X / W, 1000.0, places=6)
        self.assertAlmostEqual(Y / W, 1000.0, places=6)
        # فاصلهٔ دو نقطه با مقیاس می‌خورد
        A = H @ np.array([0.0, 0.0, 1.0])
        B = H @ np.array([1200.0, 0.0, 1.0])
        self.assertAlmostEqual(B[0] - A[0], fw, places=6)


class DetectionTests(SimpleTestCase):
    def test_off_centre_product_box(self):
        img = product_photo(box=(700, 300, 900, 500))
        e, sx, sy, alpha = ops._energy_arrays(img, False)
        self.assertFalse(alpha)
        x0, y0, x1, y1 = ops._subject_box(e, alpha)
        got = (x0 / sx, y0 / sy, x1 / sx, y1 / sy)
        for g, want in zip(got, (700, 300, 900, 500)):
            self.assertLess(abs(g - want), 12, got)             # ≈ ۳ پیکسلِ کوچک‌نما
        view = ops.subject_view(img, 2000, 2000)
        self.assertIsNotNone(view)
        zoom, cx, cy = view
        self.assertAlmostEqual(cx, 0.6667, delta=0.012)
        self.assertAlmostEqual(cy, 0.5, delta=0.015)
        # جعبه کمی (دو پیکسلِ کوچک‌نما از هر سو) از کالا بزرگ‌تر درمی‌آید ⇒ بزرگ‌نمایی کمی کمتر از ۶ (سقف) ولی نه خیلی
        self.assertTrue(4.8 <= zoom <= ops.SUBJECT_ZOOM_MAX, zoom)

    def test_whole_photo_when_the_product_fills_the_frame(self):
        img = product_photo(box=(20, 20, 1180, 780))
        self.assertIsNone(ops.subject_view(img, 2000, 2000))
        self.assertIsNone(ops.subject_view(Image.new("RGB", (900, 600), (240, 240, 240)), 2000, 2000))   # هیچ سوژه‌ای نیست
        busy = np.random.default_rng(1).integers(0, 255, (600, 900, 3), dtype=np.uint8)
        self.assertIsNone(ops.subject_view(Image.fromarray(busy, "RGB"), 2000, 2000))                     # همه‌جا لبه ⇒ کلِ عکس

    def test_transparent_cutout_uses_the_alpha(self):
        img = product_photo(box=(100, 120, 400, 320), alpha=True)
        e, sx, sy, alpha = ops._energy_arrays(img, False)
        self.assertTrue(alpha)
        x0, y0, x1, y1 = ops._subject_box(e, alpha)
        for g, want in zip((x0 / sx, y0 / sy, x1 / sx, y1 / sy), (100, 120, 400, 320)):
            self.assertLess(abs(g - want), 8)

    def test_zoom_is_capped_and_tiny_specks_are_noise(self):
        img = product_photo(w=2000, h=1500, box=(990, 740, 1010, 760))
        self.assertIsNone(ops.subject_view(img, 2000, 2000))                    # ۲۰ پیکسل = کمتر از ۰٫۴٪ ⇒ نویز
        view = ops.subject_view_from_box(4000, 3000, (1900, 1400, 2100, 1600), 2000, 2000)
        self.assertEqual(view[0], ops.SUBJECT_ZOOM_MAX)
        self.assertIsNone(ops.subject_view_from_box(1000, 1000, (30, 30, 970, 970), 2000, 2000))


class RenderTests(SimpleTestCase):
    def check_centred(self, out, expect_frac=0.88, tol=30):
        self.assertEqual(out.size, (2000, 2000))
        x0, y0, x1, y1 = content_box(out)
        self.assertLess(abs((x0 + x1) / 2 - 1000), tol, (x0, y0, x1, y1))
        self.assertLess(abs((y0 + y1) / 2 - 1000), tol, (x0, y0, x1, y1))
        longest = max(x1 - x0, y1 - y0)
        self.assertTrue(0.76 <= longest / 2000 <= 0.90, longest)          # کالا قاب (منهای حاشیه) را تقریباً پر می‌کند، بی‌بریدگی
        self.assertGreaterEqual(min(x0, y0, 2000 - x1, 2000 - y1), 2000 * 0.06 - 25)      # حاشیه ≥ ۶٪ (کالا بریده نشده)
        return x0, y0, x1, y1

    def test_off_centre_product_is_centred_whole_with_a_margin(self):
        out = run(product_photo(box=(700, 300, 900, 500)), AUTO)
        self.check_centred(out)
        # کالای دورتر هم همین
        out = run(product_photo(box=(150, 480, 330, 700)), AUTO)
        self.check_centred(out)

    def test_product_at_the_photo_edge_is_not_cut_and_the_outside_is_filled(self):
        # کالا چسبیده به لبهٔ راستِ عکس ⇒ دوربین از عکس بیرون می‌زند؛ بیرون = سفیدِ «پرکردنِ دور»
        img = product_photo(box=(1000, 300, 1190, 520))
        out = run(img, AUTO)
        self.check_centred(out, tol=30)
        a = np.asarray(out.convert("RGB"), dtype=np.int16)
        self.assertTrue((a[:, -40:].min(axis=2) >= 235).all())                     # کنارِ راست خالی/سفید
        # شمارِ پیکسل‌های رنگیِ کالا به مقیاسِ مجذور می‌خورد (چیزی بریده نشده)
        orig = np.asarray(img.convert("RGB"), dtype=np.int16)
        n0 = int(((orig[..., 0] > 150) & (orig[..., 1] < 90)).sum())               # قرمزِ کالا
        n1 = int(((a[..., 0] > 150) & (a[..., 1] < 90)).sum())
        view = ops.subject_view(img, 2000, 2000)
        scale = min(2000 / 1200, 2000 / 800) * 0.88 * view[0]
        self.assertLess(abs(n1 / (n0 * scale * scale) - 1), 0.04)

    def test_saved_frame_without_subject_is_pixel_identical_to_before(self):
        img = product_photo(box=(700, 300, 900, 500))
        old = run(img, OLD_STORE)
        with mock.patch.object(ops, "subject_view", side_effect=AssertionError("نباید صدا زده شود")):
            same = run(img, OLD_STORE | {"subject": "", "view": [4, 0.2, 0.2]})
        self.assertEqual(old.tobytes(), same.tobytes())
        x0, y0, x1, y1 = content_box(old)
        self.assertLess(x1 - x0, 400)                                              # همان «کالای کوچک در وسطِ قاب» ِ قدیم

    def test_product_filling_the_photo_equals_the_whole_photo_frame(self):
        img = product_photo(box=(20, 20, 1180, 780))
        self.assertEqual(run(img, AUTO).tobytes(), run(img, OLD_STORE).tobytes())

    def test_explicit_view_replaces_detection(self):
        img = product_photo(box=(700, 300, 900, 500))
        with mock.patch.object(ops, "subject_view", side_effect=AssertionError("view صریح است؛ تشخیص نباید اجرا شود")):
            out = run(img, AUTO | {"view": [3.0, 0.6667, 0.5]})
        x0, y0, x1, y1 = content_box(out)
        self.assertLess(abs((x0 + x1) / 2 - 1000), 14)
        # کشیدنِ عکس: مرکز را ۰٫۰۵ عرضِ عکس به راست ببر ⇒ کالا در قاب به چپ می‌رود
        moved = run(img, AUTO | {"view": [3.0, 0.7167, 0.5]})
        mx0, _my0, mx1, _my1 = content_box(moved)
        shift = ((x0 + x1) / 2) - ((mx0 + mx1) / 2)
        want = 0.05 * 1200 * min(2000 / 1200, 2000 / 800) * 0.88 * 3.0
        self.assertLess(abs(shift - want), 6)

    def test_fallback_detection_on_the_server_matches_the_browser_contract(self):
        # بی view (کارِ بی‌مرورگر) سرور خودش همان تشخیص را می‌کند ⇒ خروجی = خروجیِ view ِ صریحِ همان تشخیص
        img = product_photo(box=(700, 300, 900, 500))
        view = ops.subject_view(img, 2000, 2000)
        a = run(img, AUTO)
        b = run(img, AUTO | {"view": view})
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_visible_part_equals_a_full_resize_reference(self):
        img = product_photo(w=900, h=600, box=(500, 150, 700, 350))
        p = catalog.normalize_params("crop_format", AUTO | {"view": [2.6, 0.67, 0.42]}, strict=False)
        got = ops.op_crop_format(img, p, {"notes": []})
        geo = ops.crop_format_geometry(p, 900, 600)
        v = geo["view"]
        ref = Image.new("RGB", (2000, 2000), "white")
        full = img.resize((round(900 * v["scale"]), round(600 * v["scale"])), Image.Resampling.LANCZOS)
        ref.paste(full, (round(v["left"]), round(v["top"])))
        diff = np.abs(np.asarray(got, dtype=np.int16) - np.asarray(ref, dtype=np.int16))
        self.assertLess(float(diff.mean()), 1.2)
        self.assertLess(float(np.percentile(diff, 99.9)), 120)           # فقط لبهٔ کالا کمی فرق دارد

    def test_other_fills_work_with_the_camera(self):
        img = product_photo(box=(1000, 300, 1190, 520))
        for fill in ("black", "color", "blur", "transparent"):
            out = run(img, AUTO | {"fill": fill, "fill_color": "#336699"})
            self.assertEqual(out.size, (2000, 2000))
            if fill == "transparent":
                self.assertEqual(out.mode, "RGBA")
                self.assertEqual(out.getpixel((1990, 5))[3], 0)
        self.assertEqual(run(img, AUTO | {"fill": "black"}).getpixel((1990, 1000)), (0, 0, 0))
        self.assertEqual(run(img, AUTO | {"fill": "color", "fill_color": "#336699"}).getpixel((1990, 5)), (0x33, 0x66, 0x99))

    def test_transparent_cutout_is_centred_by_its_alpha(self):
        out = run(product_photo(box=(100, 120, 400, 320), alpha=True), AUTO | {"fill": "transparent"})
        a = np.asarray(out)[..., 3]
        ys, xs = np.nonzero(a > 128)
        self.assertLess(abs((xs.min() + xs.max()) / 2 - 1000), 20)
        self.assertLess(abs((ys.min() + ys.max()) / 2 - 1000), 20)

    def test_non_square_frames_fit_by_the_larger_ratio(self):
        out = run(product_photo(box=(700, 300, 900, 500)), {"format": "story", "fit": "contain", "fill": "white", "padding": 6,
                                                           "subject": "auto"})
        self.assertEqual(out.size, (1080, 1920))
        x0, y0, x1, y1 = content_box(out)
        self.assertLess(abs((x0 + x1) / 2 - 540), 14)
        self.assertLess(abs((y0 + y1) / 2 - 960), 14)
        self.assertTrue(0.76 <= (x1 - x0) / 1080 <= 0.90, x1 - x0)           # عرض محدودکننده است

    def test_no_memory_blowup_for_tiny_products(self):
        img = product_photo(w=4000, h=3000, box=(1900, 1400, 2100, 1600))
        out = run(img, AUTO)                                                # zoom تا ۶ برابر؛ فقط بخشِ داخلِ قاب ساخته می‌شود
        self.assertEqual(out.size, (2000, 2000))


class FramesStageTests(SimpleTestCase):
    def test_server_state_geometry_matches_the_render(self):
        state = {"tools": {"crop_format": AUTO | {"view": [2.2, 0.62, 0.48]}}}
        H, (wf, hf) = frames.frame_geometry(1200, 800, state)
        self.assertEqual((wf, hf), (2000, 2000))
        img = product_photo(box=(700, 300, 900, 500))
        out = run(img, AUTO | {"view": [2.2, 0.62, 0.48]})
        # مرکزِ کالا (800، ۴۰۰) با H به همان جایی می‌رسد که کالا در خروجی دیده می‌شود
        X, Y, W = H @ np.array([800.0, 400.0, 1.0])
        x0, y0, x1, y1 = content_box(out)
        self.assertLess(abs(X / W - (x0 + x1) / 2), 3)
        self.assertLess(abs(Y / W - (y0 + y1) / 2), 3)

    def test_state_without_a_view_uses_the_detector_when_given(self):
        img = product_photo(box=(700, 300, 900, 500))
        state = {"tools": {"crop_format": AUTO}}
        H0, _ = frames.frame_geometry(1200, 800, state)
        self.assertTrue(frames.frame_stages(1200, 800, state)["social"]["approx"])
        view = ops.subject_view(img, 2000, 2000)
        H1, size = frames.frame_geometry(1200, 800, state, subject=lambda: view)
        self.assertFalse(np.allclose(H0, H1))
        X, Y, W = H1 @ np.array([800.0, 400.0, 1.0])
        self.assertLess(abs(X / W - 1000), 40)
        self.assertLess(abs(Y / W - 1000), 40)
