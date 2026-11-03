"""«قاب‌اول» (fv=2): ترتیبِ قراردادیِ کارها، پارامترهای تازهٔ crop_format، هندسهٔ قاب (frames.py)، کوچِ پروژه‌های fv=1،
کوچِ تنبل از راهِ API و فرمانِ مدیریتی. بی شبکه و بی هوشِ مصنوعی."""
import copy
import io
import itertools
import math
import os
import random
import re
import shutil
import tempfile
import time
from io import StringIO
from pathlib import Path

import cv2
import numpy as np
from django.core.management import call_command
from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from . import catalog, frames, ops, services
from .models import PhotoAsset, PhotoEdit, PhotoProject
from .tests import ApiTestBase, photo


# ───────────────────────────── ابزارهای مشترک

CANON = ["develop", "liquify", "perspective", "rotate", "crop_rect", "crop_format", "auto_tone", "look", "color",
         "compose", "text", "logo", "watermark", "resize", "export"]
BASE = {"id": "base", "type": "base"}
MAGENTA = (255, 0, 255)


def minimal(tool):
    """کوچک‌ترین پارامترِ معتبر برای هر ابزارِ سرورِ سایت."""
    return {"text": {"text": "x"}, "compose": {"layers": [dict(BASE)]}}.get(tool, {})


def op(tool, **params):
    return {"tool": tool, "params": params or minimal(tool)}


def tools_of(ops_):
    return [o["tool"] for o in ops_]


def gradient(w, h, seed=2):
    rng = np.random.default_rng(seed)
    arr = np.stack([np.tile(np.linspace(40, 200, w), (h, 1)), np.tile(np.linspace(60, 120, h)[:, None], (1, w)),
                    np.full((h, w), 90.0)], axis=2) + rng.normal(0, 3, (h, w, 3))
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def png_bytes(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def blobs(img, rgb, tol=110, min_area=60):
    """(cx, cy, مساحت) ِ تکه‌های هم‌رنگِ rgb، مرتب."""
    a = np.asarray(img.convert("RGB")).astype(int)
    m = (np.abs(a - np.array(rgb)).sum(axis=2) < tol).astype(np.uint8)
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m)
    return sorted((float(cen[i][0]) + .5, float(cen[i][1]) + .5, int(st[i][4])) for i in range(1, n) if st[i][4] >= min_area)


def rect(cx, cy, w, h, rot=0.0, color="#ff00ff", lid="r1", **kw):
    return {"id": lid, "type": "shape", "shape": "rect", "cx": cx, "cy": cy, "w": w, "h": h, "rot": rot,
            "fill": {"type": "solid", "color": color, "opacity": 1}, **kw}


def pipeline_ops(data, order):
    """مثلِ buildProOperations ِ مرورگر: compose ⇒ persp ⇒ rotate ⇒ crop_rect ⇒ crop_format (+ order برای ترتیبِ نهایی)."""
    out = [{"tool": "compose", "params": {"project": 1, "layers": data.get("layers") or [dict(BASE)]}}]
    if data.get("persp"):
        out.append({"tool": "perspective", "params": data["persp"]})
    if data.get("turn") or data.get("straighten") or data.get("flipH") or data.get("flipV"):
        out.append({"tool": "rotate", "params": {"turn": str(data.get("turn") or 0), "straighten": data.get("straighten") or 0,
                                                 "flip_h": bool(data.get("flipH")), "flip_v": bool(data.get("flipV"))}})
    c = data.get("crop")
    if c:
        out.append({"tool": "crop_rect", "params": {k: round(c[k] * 100, 1) for k in ("x", "y", "w", "h")}})
    cf = (data.get("tools") or {}).get("crop_format")
    if cf is not None:
        out.append({"tool": "crop_format", "params": cf})
    return catalog.normalize_operations(out, order)


class RenderMixin:
    """پوشهٔ موقتِ پروژه + عکسِ اصل + رندرِ لولهٔ سرور."""

    W, H = 1000, 700

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="nmframes-"))
        self.photo = gradient(self.W, self.H)
        self.asset = self.tmp / "asset.png"
        self.photo.save(self.asset)
        logo = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
        d = ImageDraw.Draw(logo)
        d.rectangle([0, 0, 199, 39], fill=(255, 0, 0, 255))        # نوارِ قرمزِ بالا
        d.rectangle([0, 40, 59, 119], fill=(0, 0, 255, 255))       # ستونِ آبیِ چپ
        logo.save(self.tmp / "logo.png")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def ctx(self):
        return {"notes": [], "scale": 1.0, "store_name": "x", "logo_path": lambda p: self.tmp / "logo.png",
                "mask_path": lambda pid, mid: (self.tmp / f"mask-{mid}.png") if (self.tmp / f"mask-{mid}.png").is_file() else None}

    def render(self, data, order, img=None):
        out, _ = ops.run((img or self.photo).copy(), pipeline_ops(data, order), self.ctx())
        return out

    def migrate(self, data, **kw):
        kw.setdefault("asset_path", self.asset)
        return frames.migrate_v1_to_v2(copy.deepcopy(data), self.W, self.H, self.tmp, **kw)

    def both(self, data):
        """رندرِ v1 (داده‌ی قدیم، ترتیبِ قدیم) و v2 (داده‌ی کوچ‌داده، ترتیبِ تازه) + داده‌ی کوچ‌داده."""
        a = self.render(data, 1)
        new, rep = self.migrate(data)
        self.assertTrue(rep["stamped"], rep)
        return a, self.render(new, 2), new, rep

    def assertSameSpot(self, a, b, rgb, tol=2.0, msg=""):
        ba, bb = blobs(a, rgb), blobs(b, rgb)
        self.assertEqual(len(ba), len(bb), f"{msg}: {ba} vs {bb}")
        self.assertTrue(ba, f"{msg}: چیزی دیده نشد")
        worst = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(ba, bb))
        self.assertLessEqual(worst, tol, f"{msg}: {worst:.2f}px")
        return worst


# ═════════════════════════════ ترتیبِ کارها

class OrderingTests(SimpleTestCase):
    def test_canonical_list_is_the_contract(self):
        self.assertEqual(list(catalog.SERVER_ORDER_V2), CANON)
        self.assertEqual(catalog.ORDER_CURRENT, 2)

    def test_every_pair_of_server_tools_is_ordered(self):
        server = [t for t in CANON if t in catalog.tools()]
        self.assertGreaterEqual(len(server), 13)
        for a, b in itertools.permutations(server, 2):
            want = [x for x in CANON if x in (a, b)]
            got = tools_of(catalog.normalize_operations([op(a), op(b)]))
            if "export" in (a, b):
                want = [x for x in want if x != "export"] + ["export"]
            self.assertEqual(got, want, (a, b))

    def test_random_shuffles_of_every_tool_end_in_canonical_order(self):
        server = [t for t in CANON if t in catalog.tools()]
        rnd = random.Random(7)
        for _ in range(25):
            lst = server[:]
            rnd.shuffle(lst)
            got = tools_of(catalog.normalize_operations([op(t) for t in lst]))
            self.assertEqual(got, [t for t in CANON if t in server])

    def test_compose_after_crop_format_and_tone_before_compose(self):
        got = tools_of(catalog.normalize_operations([op("compose"), op("text"), op("color"), op("look"), op("auto_tone"),
                                                     op("crop_format"), op("crop_rect"), op("rotate"), op("perspective")]))
        self.assertEqual(got, ["perspective", "rotate", "crop_rect", "crop_format", "auto_tone", "look", "color", "compose", "text"])
        # develop پیش از همه، resize و export آخر
        got = tools_of(catalog.normalize_operations([op("export"), op("resize"), op("compose"), op("develop")]))
        self.assertEqual(got, ["develop", "compose", "resize", "export"])

    def test_liquify_sits_between_develop_and_perspective(self):
        self.assertLess(CANON.index("develop"), CANON.index("liquify"))
        self.assertLess(CANON.index("liquify"), CANON.index("perspective"))
        if "liquify" in catalog.tools():
            got = tools_of(catalog.normalize_operations([op("perspective"), op("liquify"), op("develop"), op("color")]))
            self.assertEqual(got, ["develop", "liquify", "perspective", "color"])

    def test_node_ops_first_keep_their_order_export_last_single(self):
        raw = [op("text"), {"tool": "kit_sharpen", "params": {}}, op("crop_format"), {"tool": "kit_auto", "params": {}},
               op("export", format="png"), op("color"), op("export", format="webp")]
        got = catalog.normalize_operations(raw)
        self.assertEqual(tools_of(got), ["kit_sharpen", "kit_auto", "crop_format", "color", "text", "export"])
        self.assertEqual(got[-1]["params"]["format"], "webp", "آخرین export می‌ماند")

    def test_same_class_keeps_caller_order(self):
        raw = [op("text", text="الف"), op("color", brightness=5), op("text", text="ب"), op("color", brightness=9)]
        got = catalog.normalize_operations(raw)
        self.assertEqual(tools_of(got), ["color", "color", "text", "text"])
        self.assertEqual([o["params"]["brightness"] for o in got[:2]], [5, 9])
        self.assertEqual([o["params"]["text"] for o in got[2:]], ["الف", "ب"])

    def test_order_one_keeps_the_callers_order_exactly(self):
        raw = [op("color"), op("text"), op("crop_format"), op("compose"), op("auto_tone"), op("export"), op("resize")]
        got = tools_of(catalog.normalize_operations(raw, order=1))
        self.assertEqual(got, ["color", "text", "crop_format", "compose", "auto_tone", "resize", "export"])
        self.assertEqual(tools_of(catalog.normalize_operations(raw, 1)), got)
        # order=2 همان مجموعه را مرتب می‌کند
        self.assertEqual(tools_of(catalog.normalize_operations(raw, 2)),
                         ["crop_format", "auto_tone", "color", "compose", "text", "resize", "export"])
        # idempotent
        again = catalog.normalize_operations(catalog.normalize_operations(raw))
        self.assertEqual(tools_of(again), tools_of(catalog.normalize_operations(raw)))

    def test_off_ops_are_dropped_and_errors_kept(self):
        got = catalog.normalize_operations([dict(op("color"), on=False), op("look")])
        self.assertEqual(tools_of(got), ["look"])
        with self.assertRaises(catalog.CatalogError):
            catalog.normalize_operations([{"tool": "nope"}])
        with self.assertRaises(catalog.CatalogError):
            catalog.normalize_operations("x")

    def test_recipes_end_up_in_v2_order(self):
        for r in catalog.RECIPES:
            raw = [dict(o, on=True) for o in r["operations"]
                   if o["tool"] not in ("kit_smart", "text") or o["params"].get("goal") or o["params"].get("text")]
            if not raw:
                continue
            got = catalog.normalize_operations(raw)
            server = [t for t in tools_of(got) if catalog.tools()[t]["where"] == "server"]
            ranks = [CANON.index(t) for t in server]
            self.assertEqual(ranks, sorted(ranks), r["key"])


# ═════════════════════════════ crop_format: پارامترها و رفتار

class CropFormatTests(SimpleTestCase):
    def ctx(self):
        return {"notes": []}

    def cf(self, **p):
        return catalog.normalize_params("crop_format", p)

    def test_old_stored_params_normalise_to_defaults(self):
        p = catalog.normalize_params("crop_format", {"format": "story", "fit": "contain", "focus": "smart",
                                                      "fill": "blur", "fill_color": "#f3f4f6"})
        self.assertEqual((p["size"], p["padding"], p["window"]), (2000, 0, []))
        self.assertEqual(p["format"], "story")
        for fmt in catalog.SOCIAL_FORMATS:
            self.assertEqual(self.cf(format=fmt)["format"], fmt)
        # بی هیچ پارامتری هم کار می‌کند
        d = catalog.normalize_params("crop_format", {})
        self.assertEqual((d["format"], d["fit"], d["focus"], d["fill"], d["window"], d["padding"], d["size"]),
                         ("square", "cover", "smart", "blur", [], 0, 2000))
        keys = {x["key"] for x in catalog.tools()["crop_format"]["params"]}
        self.assertTrue({"format", "size", "fit", "focus", "fill", "fill_color", "padding", "window"} <= keys)
        fmt_opts = [o["value"] for o in next(x for x in catalog.tools()["crop_format"]["params"] if x["key"] == "format")["options"]]
        self.assertIn("custom", fmt_opts)
        fills = [o["value"] for o in next(x for x in catalog.tools()["crop_format"]["params"] if x["key"] == "fill")["options"]]
        self.assertIn("transparent", fills)

    def test_size_and_padding_ranges(self):
        self.assertEqual(self.cf(format="custom", size=50)["size"], 200)
        self.assertEqual(self.cf(format="custom", size=99999)["size"], 4000)
        self.assertEqual(self.cf(format="custom", size="abc")["size"], 2000)
        self.assertEqual(self.cf(padding=-5)["padding"], 0)
        self.assertEqual(self.cf(padding=99)["padding"], 40)
        self.assertEqual(self.cf(fill="transparent")["fill"], "transparent")
        with self.assertRaises(catalog.CatalogError):
            self.cf(fill="rainbow")

    def test_window_normalisation(self):
        nw = catalog.normalize_window
        self.assertEqual(nw([0.1, 0.2, 0.5, 0.6]), [0.1, 0.2, 0.5, 0.6])
        self.assertEqual(nw((0, 0, 1, 1)), [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(nw([-0.5, 0.2, 0.5, 0.6]), [0.0, 0.2, 0.5, 0.6], "مقدارِ منفی به ۰ می‌رود")
        self.assertEqual(nw([0.1, 0.2, 0.01, 0.6]), [], "پهنای کمتر از ۰٫۰۲")
        self.assertEqual(nw([0.1, 0.2, 0.5, 0.019]), [], "ارتفاع کمتر از ۰٫۰۲")
        self.assertEqual(nw([0.6, 0.2, 0.5, 0.6]), [], "x+w > 1")
        self.assertEqual(nw([0.1, 0.6, 0.5, 0.6]), [], "y+h > 1")
        self.assertEqual(nw([0.3, 0.2, 0.7004, 0.6]), [0.3, 0.2, 0.7, 0.6], "خطای گردکردنِ مرورگر به لبه می‌چسبد")
        self.assertEqual(nw([0.3, 0.2, 0.7015, 0.6]), [], "بیش از خطای مجاز")
        for bad in (None, "x", 5, [], [1, 2, 3], [1, 2, 3, 4, 5], ["a", 0, 0.5, 0.5], [None, 0, 0.5, 0.5],
                    [float("nan"), 0, 0.5, 0.5], [True, 0, 0.5, 0.5], {"x": 0}):
            self.assertEqual(nw(bad), [], bad)
        # از راهِ normalize_params / normalize_operations هم می‌گذرد
        p = self.cf(format="portrait", window=[0.25, 0.1, 0.5, 0.8])
        self.assertEqual(p["window"], [0.25, 0.1, 0.5, 0.8])
        self.assertEqual(self.cf(window=[2, 2, 2, 2])["window"], [])
        clean = catalog.normalize_operations([{"tool": "crop_format", "params": {"window": [0.1, 0.1, 0.5, 0.5]}}])
        self.assertEqual(clean[0]["params"]["window"], [0.1, 0.1, 0.5, 0.5])

    def test_custom_size_cover_and_contain(self):
        img = photo(900, 600)
        for fit in ("cover", "contain"):
            out = ops.op_crop_format(img, self.cf(format="custom", size=640, fit=fit), self.ctx())
            self.assertEqual(out.size, (640, 640), fit)
        out = ops.op_crop_format(img, self.cf(format="custom", size=2000, fit="contain", fill="white"), self.ctx())
        self.assertEqual(out.size, (2000, 2000))
        self.assertEqual(ops.crop_format_target(self.cf(format="custom", size=777))[:2], (777, 777))
        # قالب‌های شبکه size را نادیده می‌گیرند
        self.assertEqual(ops.op_crop_format(img, self.cf(format="square", size=640), self.ctx()).size, (1080, 1080))

    def test_contain_padding_math(self):
        img = Image.new("RGB", (1000, 500), (200, 0, 0))
        out = ops.op_crop_format(img, self.cf(format="square", fit="contain", fill="white", padding=10), self.ctx())
        self.assertEqual(out.size, (1080, 1080))
        a = np.asarray(out).astype(int)
        content = (np.abs(a - 255).sum(axis=2) > 30)
        ys, xs = np.nonzero(content)
        # scale = min(1080/1000, 1080/500) · (1 − 0.2) = 0.864 ⇒ 864 × 432، وسط‌چین (108، 324)
        self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (108, 108 + 864 - 1, 324, 324 + 432 - 1))
        geo = ops.crop_format_geometry(self.cf(format="square", fit="contain", padding=10), 1000, 500)
        self.assertEqual((geo["fg"], geo["pos"]), ((864, 432), (108, 324)))
        # بی حاشیه همان قدیم
        geo0 = ops.crop_format_geometry(self.cf(format="square", fit="contain"), 1000, 500)
        self.assertEqual((geo0["fg"], geo0["pos"]), ((1080, 540), (0, 270)))
        # حاشیهٔ ۴۰٪ ⇒ ۲۰٪ اندازه
        geo40 = ops.crop_format_geometry(self.cf(format="square", fit="contain", padding=40), 1000, 500)
        self.assertEqual(geo40["fg"], (216, 108))

    def test_padding_is_ignored_for_cover(self):
        img = photo(800, 500)
        a = ops.op_crop_format(img, self.cf(format="square", fit="cover", focus="center", padding=0), self.ctx())
        b = ops.op_crop_format(img, self.cf(format="square", fit="cover", focus="center", padding=30), self.ctx())
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_legacy_behaviour_is_unchanged(self):
        img = photo(800, 400)
        # contain سفید: همان reconstruct ِ قدیم
        p = {"format": "square", "fit": "contain", "fill": "white"}
        out = ops.op_crop_format(img, catalog.normalize_params("crop_format", p), self.ctx())
        want = Image.new("RGB", (1080, 1080), "#ffffff")
        want.paste(img.resize((1080, 540), Image.Resampling.LANCZOS), (0, 270))
        self.assertEqual(out.tobytes(), want.tobytes())
        # cover وسط: برش + LANCZOS
        out = ops.op_crop_format(img, catalog.normalize_params("crop_format", {"format": "story", "focus": "center"}), self.ctx())
        scale = max(1080 / 800, 1920 / 400)
        cw, ch = min(800, int(round(1080 / scale))), min(400, int(round(1920 / scale)))
        x, y = (800 - cw) // 2, (400 - ch) // 2
        self.assertEqual(out.tobytes(), img.crop((x, y, x + cw, y + ch)).resize((1080, 1920), Image.Resampling.LANCZOS).tobytes())
        # فیلِ blur به padding بستگی ندارد (گوشه‌ها یکی‌اند)
        b0 = ops.op_crop_format(img, self.cf(format="story", fit="contain", fill="blur"), self.ctx())
        b1 = ops.op_crop_format(img, self.cf(format="story", fit="contain", fill="blur", padding=20), self.ctx())
        self.assertEqual(np.asarray(b0)[5, 5].tolist(), np.asarray(b1)[5, 5].tolist())
        self.assertEqual(b0.mode, "RGB")

    def test_window_overrides_focus_exactly(self):
        img = Image.new("RGB", (1000, 500), (200, 0, 0))
        ImageDraw.Draw(img).rectangle([500, 0, 999, 499], fill=(0, 200, 0))
        right = ops.op_crop_format(img, self.cf(format="square", focus="left", window=[0.5, 0.0, 0.5, 1.0]), self.ctx())
        self.assertEqual(right.size, (1080, 1080))
        self.assertLess(np.asarray(right)[..., 0].max(), 6, "پنجره سمتِ راست است نه focus=left")
        left = ops.op_crop_format(img, self.cf(format="square", focus="right", window=[0.0, 0.0, 0.5, 1.0]), self.ctx())
        self.assertLess(np.asarray(left)[..., 1].max(), 6)
        # هندسهٔ اعشاری: خطِ ۴ پیکسلی در x≈۳۰۰ از پنجرهٔ x∈[۱۰۰، ۵۰۰] ⇒ ۵۴۰ در خروجی
        sq = Image.new("RGB", (1000, 1000), (0, 0, 0))
        ImageDraw.Draw(sq).rectangle([298, 0, 301, 999], fill=(255, 255, 255))
        out = ops.op_crop_format(sq, self.cf(format="square", window=[0.1, 0.2, 0.4, 0.4]), self.ctx())
        row = np.asarray(out.convert("L"))[540].astype(int)
        cx = (row * np.arange(len(row))).sum() / row.sum() + 0.5
        self.assertAlmostEqual(cx, (300 - 100) / 400 * 1080, delta=1.0)
        geo = ops.crop_format_geometry(self.cf(format="square", window=[0.1, 0.2, 0.4, 0.4]), 1000, 1000)
        self.assertEqual([round(v, 6) for v in geo["box"]], [100.0, 200.0, 500.0, 600.0])
        self.assertTrue(geo["exact"])
        # window در حالتِ contain نادیده گرفته می‌شود
        c = ops.op_crop_format(img, self.cf(format="square", fit="contain", fill="white", window=[0.5, 0, 0.5, 1]), self.ctx())
        self.assertEqual(c.size, (1080, 1080))
        self.assertGreater(np.asarray(c)[..., 0].max(), 150, "contain کلِ عکس را نشان می‌دهد")

    def test_transparent_fill(self):
        img = Image.new("RGB", (800, 400), (200, 0, 0))
        out = ops.op_crop_format(img, self.cf(format="story", fit="contain", fill="transparent", padding=5), self.ctx())
        self.assertEqual((out.mode, out.size), ("RGBA", (1080, 1920)))
        a = np.asarray(out)
        self.assertEqual(int(a[0, 0, 3]), 0)
        self.assertEqual(int(a[-1, -1, 3]), 0)
        self.assertEqual(int(a[960, 540, 3]), 255)
        self.assertEqual(a[960, 540, :3].tolist(), [200, 0, 0])
        geo = ops.crop_format_geometry(self.cf(format="story", fit="contain", padding=5), 800, 400)
        l, t = geo["pos"]
        w, h = geo["fg"]
        alpha = a[..., 3]
        ys, xs = np.nonzero(alpha)
        self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (l, l + w - 1, t, t + h - 1))
        # خروجی JPEG: بیرونِ محتوا سفید می‌شود؛ PNG آلفا را نگه می‌دارد
        data, fmt = ops.encode(out, "jpeg", 95)
        j = np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(int)
        self.assertTrue((j[5, 5] > 250).all())
        data, fmt = ops.encode(out, "png")
        self.assertEqual(Image.open(io.BytesIO(data)).mode, "RGBA")
        self.assertEqual(np.asarray(Image.open(io.BytesIO(data)))[5, 5, 3], 0)
        # عکسِ دارای آلفا: آلفای خودش درون می‌ماند
        rgba = photo(400, 300, alpha=True)
        o2 = ops.op_crop_format(rgba, self.cf(format="square", fit="contain", fill="transparent"), self.ctx())
        self.assertEqual(o2.mode, "RGBA")
        self.assertEqual(int(np.asarray(o2)[0, 0, 3]), 0)
        self.assertEqual(int(np.asarray(o2)[540, 540, 3]), 255)
        # cover بی فیل: عکسِ RGB می‌ماند
        self.assertEqual(ops.op_crop_format(img, self.cf(format="square", fit="cover", fill="transparent"), self.ctx()).mode, "RGB")

    def test_run_through_ops_run_and_jpeg_flatten(self):
        img = photo(500, 300)
        clean = catalog.normalize_operations([
            {"tool": "crop_format", "params": {"format": "custom", "size": 400, "fit": "contain", "fill": "transparent", "padding": 10}},
            {"tool": "export", "params": {"format": "jpeg", "quality": 90}}])
        out, export = ops.run(img, clean, {"notes": []})
        self.assertEqual((out.mode, out.size), ("RGBA", (400, 400)))
        data, fmt = ops.encode(out, export["format"], export["quality"])
        self.assertEqual(fmt, "jpeg")
        self.assertEqual(Image.open(io.BytesIO(data)).mode, "RGB")


# ═════════════════════════════ هندسهٔ قاب = لولهٔ سرور

class FrameGeometryTests(RenderMixin, SimpleTestCase):
    W, H = 800, 600

    def marker(self, mx, my, r=10):
        im = gradient(self.W, self.H)
        ImageDraw.Draw(im).rectangle([mx - r, my - r, mx + r - 1, my + r - 1], fill=MAGENTA)
        return im

    def run_server(self, im, state):
        ops_ = []
        for tool, p in (("perspective", frames._persp_params(state)), ("rotate", frames._rotate_params(state)),
                        ("crop_rect", frames._crop_params(state)),
                        ("crop_format", catalog.normalize_params("crop_format", frames._social_params(state) or {}))):
            if tool == "crop_format" and frames._social_params(state) is None:
                continue
            if p:
                ops_.append({"tool": tool, "params": p})
        out, _ = ops.run(im, ops_, {"notes": [], "scale": 1.0})
        return out

    def test_trivial_state_is_identity(self):
        H, size = frames.frame_geometry(self.W, self.H, {})
        self.assertEqual(size, (self.W, self.H))
        self.assertTrue(np.allclose(H, np.eye(3)))
        self.assertTrue(frames.is_trivial({"layers": [BASE], "crop": {"x": 0, "y": 0, "w": 1, "h": 1}, "turn": 0,
                                           "persp": {"tl": [0, 0], "tr": [1, 0], "br": [1, 1], "bl": [0, 1]}}))
        self.assertFalse(frames.is_trivial({"turn": 90}))
        self.assertFalse(frames.is_trivial({"tools": {"kit_square": {}}}))
        self.assertFalse(frames.is_trivial({"tools": {"crop_format": {}}}))

    def test_homography_lands_where_the_server_pipeline_puts_pixels(self):
        quads = [None, {"tl": [0.05, 0.08], "tr": [0.92, 0.02], "br": [0.97, 0.95], "bl": [0.02, 0.9]}]
        crops = [None, {"x": 0.1, "y": 0.2, "w": 0.7, "h": 0.6}]
        socials = [None, {"format": "square", "fit": "cover", "focus": "center"},
                   {"format": "story", "fit": "cover", "focus": "left"},
                   {"format": "portrait", "fit": "cover", "window": [0.2, 0.1, 0.5, 0.6]},
                   {"format": "story", "fit": "contain", "fill": "white"},
                   {"format": "custom", "size": 700, "fit": "contain", "fill": "white", "padding": 6},
                   {"format": "landscape", "fit": "contain", "fill": "transparent", "padding": 10}]
        combos = list(itertools.product(quads, crops, [0, 90, 180, 270], [0, 4.5, -7.5],
                                        [(False, False), (True, False), (False, True), (True, True)], socials))
        random.Random(11).shuffle(combos)
        checked, worst = 0, 0.0
        for q, c, t, s, fl, soc in combos[:90]:
            state = {"persp": q, "crop": c, "turn": t, "straighten": s, "flipH": fl[0], "flipV": fl[1],
                     "tools": {"crop_format": soc} if soc else {}}
            H, (wf, hf) = frames.frame_geometry(self.W, self.H, state)
            for mx, my in ((400, 300), (330, 240), (480, 330), (280, 340), (520, 250)):
                X, Y = frames._apply(H, mx, my)
                if 90 < X < wf - 90 and 90 < Y < hf - 90:     # نشانه کامل داخلِ بوم باشد
                    break
            else:
                continue
            out = self.run_server(self.marker(mx, my), state)
            self.assertEqual(out.size, (wf, hf), state)
            b = blobs(out, MAGENTA, min_area=5)
            self.assertTrue(b, state)
            err = math.hypot(b[0][0] - X, b[0][1] - Y)
            worst = max(worst, err)
            self.assertLess(err, 1.6, (state, (X, Y), b[0]))
            checked += 1
        self.assertGreater(checked, 50)

    def test_social_stage_modes(self):
        # cover با window: پنجره به قاب کشیده می‌شود
        state = {"tools": {"crop_format": {"format": "portrait", "fit": "cover", "window": [0.25, 0.1, 0.5, 0.8]}}}
        H, size = frames.frame_geometry(1000, 500, state)
        self.assertEqual(size, (1080, 1350))
        self.assertAlmostEqual(frames._apply(H, 250, 50)[0], 0.0, places=6)
        self.assertAlmostEqual(frames._apply(H, 750, 450)[1], 1350.0, places=6)
        # contain: اندازه و وسط‌چین
        state = {"tools": {"crop_format": {"format": "square", "fit": "contain", "padding": 10}}}
        H, size = frames.frame_geometry(1000, 500, state)
        self.assertEqual(size, (1080, 1080))
        self.assertEqual(tuple(round(v, 6) for v in frames._apply(H, 0, 0)), (108.0, 324.0))
        self.assertEqual(tuple(round(v, 6) for v in frames._apply(H, 1000, 500)), (972.0, 756.0))
        # cover smart بی تابعِ energy: وسط
        st = frames.frame_stages(1000, 500, {"tools": {"crop_format": {"format": "square"}}})
        self.assertTrue(st["social"]["approx"])
        st = frames.frame_stages(1000, 500, {"tools": {"crop_format": {"format": "square"}}}, energy=lambda cw, ch: (7, 0))
        self.assertEqual(st["social"]["box"][:2], (7, 0))


# ═════════════════════════════ کوچِ fv=1 ⇒ fv=2

class MigrationTests(RenderMixin, SimpleTestCase):
    def test_trivial_frame_only_stamps(self):
        data = {"layers": [BASE, rect(0.4, 0.5, 0.2, 0.1, 15)], "tools": {"look": {"style": "warm"}}, "adjust": {"exposure": 0.2},
                "crop": {"x": 0, "y": 0, "w": 1, "h": 1}, "turn": 0, "persp": None}
        new, rep = self.migrate(data)
        self.assertEqual(new.pop("fv"), 2)
        self.assertEqual(new, data)
        self.assertTrue(rep["trivial"] and rep["stamped"] and rep["changed"])
        # بدونِ لایه و داده‌ی خالی
        new, rep = self.migrate({})
        self.assertEqual(new, {"fv": 2})
        self.assertTrue(rep["trivial"])

    def test_crop_only(self):
        data = {"layers": [BASE, rect(0.5, 0.5, 0.2, 0.1)], "crop": {"x": 0.2, "y": 0.2, "w": 0.6, "h": 0.6}}
        a, b, new, rep = self.both(data)
        self.assertEqual(a.size, b.size)
        self.assertEqual(self.render(new, 2).size, (600, 420))
        self.assertSameSpot(a, b, MAGENTA, 1.0, "crop")
        L = new["layers"][1]
        # k = ۱ · W / Wf = ۱۰۰۰/۶۰۰
        self.assertAlmostEqual(L["w"], 0.2 * 1000 / 600, places=4)
        self.assertAlmostEqual(L["h"], 0.1 * 1000 / 600, places=4)
        self.assertAlmostEqual(L["cx"], 0.5, places=4)
        self.assertEqual(new["fv"], 2)
        self.assertEqual(new["crop"], data["crop"], "ورودی‌های قاب می‌مانند")

    def test_rotate_straighten_flip_persp_and_combo(self):
        cases = {
            "rotate90+straighten": {"turn": 90, "straighten": 5},
            "turn270+flipH": {"turn": 270, "flipH": True},
            "flipV+straighten": {"flipV": True, "straighten": -6.5},
            "persp": {"persp": {"tl": [0.05, 0.08], "tr": [0.92, 0.02], "br": [0.97, 0.95], "bl": [0.02, 0.9]}},
            "combo": {"turn": 90, "straighten": -3, "flipV": True, "crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                      "persp": {"tl": [0.03, 0.05], "tr": [0.97, 0.0], "br": [0.99, 0.98], "bl": [0.0, 0.95]},
                      "tools": {"crop_format": {"format": "portrait", "fit": "contain", "fill": "white", "padding": 5}}},
        }
        for name, fr in cases.items():
            # زیرِ پرسپکتیو شکلِ لایه در نمای قدیم تغییر شکل می‌داد و در مدلِ تازه نه ⇒ لایهٔ کوچک‌تر
            size = (0.08, 0.04) if ("persp" in name or "persp" in fr) else (0.2, 0.08)
            data = {"layers": [BASE, rect(0.55, 0.45, size[0], size[1], 12)], **fr}
            a, b, new, rep = self.both(data)
            self.assertEqual(a.size, b.size, name)
            self.assertSameSpot(a, b, MAGENTA, 2.0, name)
            ba, bb = blobs(a, MAGENTA), blobs(b, MAGENTA)
            self.assertAlmostEqual(bb[0][2] / ba[0][2], 1.0, delta=0.05, msg=name)

    def test_cover_smart_gets_an_explicit_window(self):
        data = {"layers": [BASE], "turn": 90, "crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                "tools": {"crop_format": {"format": "story", "fit": "cover", "focus": "smart"}}}
        # در عکس یک سوژهٔ پر جزئیات بگذار تا پنجره وسط نیفتد
        img = self.photo.copy()
        ImageDraw.Draw(img).ellipse([650, 80, 900, 330], fill=(250, 250, 250), outline=(0, 0, 0), width=8)
        img.save(self.asset)
        new, rep = self.migrate(data)
        win = new["tools"]["crop_format"]["window"]
        self.assertEqual(len(win), 4, rep)
        # مستقل حساب کن
        im = ops.load(self.asset)
        im = ops.op_rotate(im, catalog.normalize_params("rotate", {"turn": "90"}), {})
        im = ops.op_crop_rect(im, catalog.normalize_params("crop_rect", {"x": 10, "y": 10, "w": 80, "h": 80}), {})
        p = catalog.normalize_params("crop_format", {"format": "story", "fit": "cover", "focus": "smart"})
        geo = ops.crop_format_geometry(p, im.width, im.height, lambda cw, ch: ops._energy_offset(im, cw, ch))
        x0, y0, x1, y1 = geo["box"]
        want = [x0 / im.width, y0 / im.height, (x1 - x0) / im.width, (y1 - y0) / im.height]
        for g, w in zip(win, want):
            self.assertAlmostEqual(g, w, places=5)
        self.assertTrue(any("خودکار" in n for n in rep["notes"]))
        # رندرِ v2 (بی لایه) ≈ رندرِ v1 که smart را روی خودش حساب می‌کرد
        a = self.render(data, 1, img)
        b = self.render(new, 2, img)
        self.assertEqual(a.size, b.size)
        d = np.abs(np.asarray(a).astype(int) - np.asarray(b).astype(int)).mean()
        self.assertLess(d, 1.0)
        # بی فایلِ اصل: نمی‌شود با اطمینان کوچ داد
        again, rep2 = self.migrate(data, asset_path=None)
        self.assertFalse(rep2["stamped"])
        self.assertEqual(again, data)
        self.assertIn("خودکار", rep2["error"])

    def test_contain_blur_and_other_fills(self):
        for fill in ("blur", "white", "black", "transparent"):
            data = {"layers": [BASE, rect(0.5, 0.5, 0.2, 0.1)],
                    "tools": {"crop_format": {"format": "story", "fit": "contain", "fill": fill}}}
            a, b, new, rep = self.both(data)
            self.assertEqual(a.size, (1080, 1920))
            self.assertSameSpot(a, b, MAGENTA, 1.0, fill)
        self.assertEqual(b.mode, "RGBA")

    def test_kit_square_becomes_custom_contain_white(self):
        data = {"layers": [BASE, rect(0.5, 0.5, 0.2, 0.1)], "tools": {"kit_square": {"long_edge": 1200, "padding": 10},
                                                                       "kit_background": {"bg": "white"}}}
        new, rep = self.migrate(data)
        self.assertTrue(rep["stamped"])
        self.assertNotIn("kit_square", new["tools"])
        self.assertIn("kit_background", new["tools"], "کارهای دیگرِ کیت دست نمی‌خورند")
        cf = new["tools"]["crop_format"]
        self.assertEqual((cf["format"], cf["size"], cf["fit"], cf["fill"], cf["padding"]), ("custom", 1200, "contain", "white", 10))
        # scale = min(1200/1000, 1200/700) · 0.8 = 0.96 ⇒ w' = 0.2·1000·0.96/1200
        L = new["layers"][1]
        self.assertAlmostEqual(L["w"], 0.2 * 1000 * 0.96 / 1200, places=4)
        self.assertAlmostEqual(L["cx"], 0.5, places=4)
        self.assertAlmostEqual(L["cy"], 0.5, places=4)
        out = self.render(new, 2)
        self.assertEqual(out.size, (1200, 1200))
        b = blobs(out, MAGENTA)[0]
        self.assertAlmostEqual(b[0], 600, delta=1.5)
        self.assertAlmostEqual(b[2], (0.2 * 1000 * 0.96) * (0.1 * 1000 * 0.96), delta=900)
        # با قالبِ شبکه‌ها هم: قالبِ شبکه‌ها می‌ماند
        both = {"layers": [BASE], "tools": {"kit_square": {}, "crop_format": {"format": "story", "fit": "contain"}}}
        new2, rep2 = self.migrate(both)
        self.assertNotIn("kit_square", new2["tools"])
        self.assertEqual(new2["tools"]["crop_format"]["format"], "story")
        self.assertTrue(any("کنار گذاشته" in n for n in rep2["notes"]))

    def test_layer_fields_scale_and_rotate(self):
        k_data = {"crop": {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.8}, "layers": [
            BASE,
            {"id": "t1", "type": "text", "text": "سلام", "size": 0.05, "width": 0.4, "cx": 0.5, "cy": 0.5, "rot": 10,
             "stroke": {"w": 0.08, "color": "#000000"}, "shadow": {"color": "#000000", "opacity": 0.5, "blur": 0.1, "dx": 0.05, "dy": 0.05},
             "box": {"color": "#000000", "opacity": 0.5, "pad": 0.3, "radius": 0.2}, "letter_spacing": 0.02},
            {"id": "i1", "type": "image", "src": {"kind": "logo"}, "cx": 0.4, "cy": 0.3, "w": 0.2, "rot": 0},
            rect(0.6, 0.7, 0.3, 0.12, 0, stroke={"w": 0.01, "color": "#ffffff"}, radius=0.3, fx={
                "shadow": {"color": "#000000", "opacity": 0.5, "blur": 0.01, "dx": 0.01, "dy": 0.01},
                "stroke": {"color": "#ffffff", "w": 0.004, "opacity": 1}, "glow": {"color": "#ffd479", "opacity": 0.8, "blur": 0.02, "size": 0.006}}),
        ]}
        new, rep = self.migrate(k_data)
        k = 1000 / 500        # Wf = ۵۰۰
        t, i, s = new["layers"][1], new["layers"][2], new["layers"][3]
        self.assertAlmostEqual(t["size"], 0.05 * k, places=4)
        self.assertAlmostEqual(t["width"], 0.4 * k, places=4)
        self.assertEqual((t["stroke"], t["shadow"], t["box"], t["letter_spacing"]),
                         (k_data["layers"][1]["stroke"], k_data["layers"][1]["shadow"], k_data["layers"][1]["box"], 0.02),
                         "استروک، سایه و کادرِ متن نسبت به فونت‌اند")
        self.assertAlmostEqual(t["rot"], 10.0, places=3)
        self.assertAlmostEqual(t["cx"], (0.5 * 1000 - 250) / 500, places=4)
        self.assertAlmostEqual(t["cy"], (0.5 * 700 - 70) / 560, places=4)
        self.assertAlmostEqual(i["w"], 0.2 * k, places=4)
        self.assertAlmostEqual(s["w"], 0.3 * k, places=4)
        self.assertAlmostEqual(s["h"], 0.12 * k, places=4)
        self.assertAlmostEqual(s["stroke"]["w"], 0.01 * k, places=4)
        self.assertEqual(s["radius"], 0.3)
        self.assertAlmostEqual(s["fx"]["shadow"]["blur"], 0.01 * k, places=4)
        self.assertAlmostEqual(s["fx"]["shadow"]["dx"], 0.01 * k, places=4)
        self.assertAlmostEqual(s["fx"]["stroke"]["w"], 0.004 * k, places=4)
        self.assertAlmostEqual(s["fx"]["glow"]["size"], 0.006 * k, places=4)
        self.assertEqual(s["fx"]["glow"]["opacity"], 0.8)
        # چرخش: ۹۰ درجه پادساعتگرد ⇒ rot − ۹۰، با flip عکسِ لایه قرینه می‌شود
        r90, _ = self.migrate({"turn": 90, "layers": [BASE, rect(0.5, 0.5, 0.1, 0.1, 30), {"id": "i1", "type": "image", "src": {"kind": "logo"}, "w": 0.1}]})
        self.assertAlmostEqual(r90["layers"][1]["rot"], -60.0, places=3)
        rf, _ = self.migrate({"flipH": True, "layers": [BASE, rect(0.5, 0.5, 0.1, 0.1, 30), {"id": "i1", "type": "image", "src": {"kind": "logo"}, "w": 0.1}]})
        self.assertAlmostEqual(rf["layers"][1]["rot"], -30.0, places=3)
        self.assertTrue(rf["layers"][2]["flip_h"])
        self.assertFalse(rf["layers"][1].get("flip_h", False))

    def test_newer_layer_types_group_redeye_path_are_mapped_too(self):
        data = {"crop": {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.8}, "layers": [
            BASE,
            {"id": "g1", "type": "group", "name": "گروه", "mask": {"type": "linear", "p0": [0.5, 0.2], "p1": [0.5, 0.45]}},
            {"id": "re", "type": "redeye", "parent": "g1", "amount": 1.0, "darken": 0.6,
             "eyes": [{"x": 0.5, "y": 0.5, "r": 0.01}, {"x": 0.6, "y": 0.4, "r": 0.02}]},
            {"id": "pa", "type": "shape", "shape": "path", "parent": "g1", "cx": 0.5, "cy": 0.5, "w": 0.3, "h": 0.2, "rot": 5,
             "path": {"closed": True, "pts": [{"x": 0.1, "y": 0.2, "hi": None, "ho": [0.1, 0]}]}, "clip": True}]}
        new, rep = self.migrate(data)
        self.assertTrue(rep["stamped"], rep)
        g, re_, pa = new["layers"][1:]
        self.assertEqual((g["type"], g["name"]), ("group", "گروه"))
        self.assertAlmostEqual(g["mask"]["p0"][1], (0.2 * 700 - 70) / 560, places=4)
        self.assertEqual((re_["parent"], re_["amount"], re_["darken"]), ("g1", 1.0, 0.6))
        e0, e1 = re_["eyes"]
        self.assertAlmostEqual(e0["x"], 0.5, places=4)
        self.assertAlmostEqual(e0["y"], (350 - 70) / 560, places=4)
        self.assertAlmostEqual(e0["r"], 0.02, places=4)
        self.assertAlmostEqual(e1["x"], (600 - 250) / 500, places=4)
        self.assertAlmostEqual(e1["r"], 0.04, places=4)
        self.assertEqual(pa["path"], data["layers"][3]["path"], "مسیر در واحدهای جعبه است ⇒ دست نمی‌خورد")
        self.assertEqual((pa["parent"], pa["clip"]), ("g1", True))
        self.assertAlmostEqual(pa["w"], 0.6, places=4)
        self.assertAlmostEqual(pa["h"], 0.4, places=4)
        self.assertAlmostEqual(pa["rot"], 5.0, places=3)

    def test_image_and_rotated_layers_render_in_the_same_place(self):
        for name, fr in {"turn90": {"turn": 90}, "flipH": {"flipH": True}, "flipV+str": {"flipV": True, "straighten": 6},
                         "turn270+flipH+crop": {"turn": 270, "flipH": True, "crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}},
                         "contain": {"tools": {"crop_format": {"format": "story", "fit": "contain", "fill": "white", "padding": 4}}}
                         }.items():
            data = {"layers": [BASE, {"id": "i1", "type": "image", "src": {"kind": "logo"}, "cx": 0.55, "cy": 0.5, "w": 0.3,
                                      "rot": 25, "flip_h": False, "flip_v": False}], **fr}
            a, b, new, _rep = self.both(data)
            for rgb in ((255, 0, 0), (0, 0, 255)):
                self.assertSameSpot(a, b, rgb, 2.0, f"{name} {rgb}")

    def test_masks_linear_and_radial_specs(self):
        base = {"layers": [BASE, rect(0.5, 0.5, 1.0, 0.7, mask={"type": "radial", "c": [0.6, 0.55], "rx": 0.15, "ry": 0.1, "feather": 0.3, "invert": True}),
                           {"id": "adj", "type": "adjust", "adjust": {"exposure": 0.5},
                            "mask": {"type": "linear", "p0": [0.5, 0.2], "p1": [0.5, 0.45], "invert": False}}]}
        new, _ = self.migrate({**base, "crop": {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.8}})
        r, lin = new["layers"][1]["mask"], new["layers"][2]["mask"]
        self.assertEqual(r["type"], "radial")
        self.assertAlmostEqual(r["c"][0], (0.6 * 1000 - 250) / 500, places=4)
        self.assertAlmostEqual(r["c"][1], (0.55 * 700 - 70) / 560, places=4)
        self.assertAlmostEqual(r["rx"], 0.15 * 2, places=4)
        self.assertAlmostEqual(r["ry"], 0.1 * 2, places=4)
        self.assertEqual((r["feather"], r["invert"]), (0.3, True))
        self.assertAlmostEqual(lin["p0"][1], (0.2 * 700 - 70) / 560, places=4)
        self.assertAlmostEqual(lin["p1"][1], (0.45 * 700 - 70) / 560, places=4)
        # بعد از چرخشِ ۹۰ درجه محورهای بیضی جابه‌جا می‌شوند
        new90, _ = self.migrate({**base, "turn": 90})
        r90 = new90["layers"][1]["mask"]
        k = 1000 / 700
        self.assertAlmostEqual(r90["rx"], 0.1 * k, places=4)
        self.assertAlmostEqual(r90["ry"], 0.15 * k, places=4)

    def test_paint_mask_is_rewarped_and_original_kept(self):
        m = Image.new("L", (500, 350), 0)
        ImageDraw.Draw(m).rectangle([300, 150, 399, 249], fill=255)         # سند: x∈[۶۰۰،۸۰۰) y∈[۳۰۰،۵۰۰)
        m.save(self.tmp / "mask-pm.png")
        orig = (self.tmp / "mask-pm.png").read_bytes()
        cover = rect(0.5, 0.5, 1.0, 0.7, mask={"type": "paint", "id": "pm", "invert": False})
        fr = {"turn": 90, "crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
              "tools": {"crop_format": {"format": "square", "fit": "cover", "focus": "center"}}}
        data = {"layers": [BASE, cover], **fr}
        a = self.render(data, 1)                       # پیش از کوچ (ماسکِ قدیم روی دیسک)
        new, rep = self.migrate(data)
        self.assertEqual(rep["masks"], 1)
        self.assertEqual(rep["mask_ids"], ["pm"])
        self.assertEqual((self.tmp / "v1-mask-pm.png").read_bytes(), orig, "اصلِ ماسک نگه داشته می‌شود")
        warped = Image.open(self.tmp / "mask-pm.png")
        self.assertEqual(warped.mode, "L")
        self.assertEqual(warped.size, (1080, 1080), "اندازهٔ بومِ نهایی")
        b = self.render(new, 2)
        self.assertSameSpot(a, b, MAGENTA, 2.5, "paint mask")
        # ماسکِ بازنویسی‌شده جای درست را می‌پوشاند: مرکزِ تکهٔ سفید = H(مرکزِ سند)
        H, _ = frames.frame_geometry(self.W, self.H, fr)
        X, Y = frames._apply(H, 700, 400)
        arr = np.asarray(warped)
        self.assertGreater(int(arr[int(Y), int(X)]), 250)
        self.assertLess(int(arr[10, 10]), 5)
        # ایدمپوتنت: بار دوم دست نمی‌زند
        mtime = (self.tmp / "mask-pm.png").stat().st_mtime_ns
        again, rep2 = frames.migrate_v1_to_v2(new, self.W, self.H, self.tmp, asset_path=self.asset)
        self.assertTrue(rep2["already"])
        self.assertIs(again, new)
        self.assertEqual((self.tmp / "mask-pm.png").stat().st_mtime_ns, mtime)
        # ذخیرهٔ ناموفق و کوچِ دوباره از همان داده‌ی اصل: نتیجه عیناً یکی است (منبع = v1-mask)
        first = (self.tmp / "mask-pm.png").read_bytes()
        _new2, _ = self.migrate(data)
        self.assertEqual((self.tmp / "mask-pm.png").read_bytes(), first)

    def test_dry_run_writes_nothing(self):
        Image.new("L", (100, 70), 255).save(self.tmp / "mask-pm.png")
        before = (self.tmp / "mask-pm.png").read_bytes()
        data = {"turn": 90, "layers": [BASE, rect(0.5, 0.5, 0.2, 0.1, mask={"type": "paint", "id": "pm"})]}
        new, rep = self.migrate(data, write_masks=False)
        self.assertTrue(rep["stamped"])
        self.assertEqual(rep["masks"], 1)
        self.assertEqual((self.tmp / "mask-pm.png").read_bytes(), before)
        self.assertFalse((self.tmp / "v1-mask-pm.png").exists())
        # ماسکِ بی فایل: یادداشت، نه خطا
        new, rep = self.migrate({"turn": 90, "layers": [BASE, rect(0.5, 0.5, 0.2, 0.1, mask={"type": "paint", "id": "gone"})]})
        self.assertTrue(rep["stamped"])
        self.assertTrue(any("gone" in n for n in rep["notes"]))

    def test_retouch_strokes_follow_the_photo(self):
        photo_ = self.photo.copy()
        ImageDraw.Draw(photo_).rectangle([180, 180, 239, 239], fill=(0, 255, 0))
        photo_.save(self.asset)
        stroke = {"mode": "clone", "pts": [[0.7, 0.64]], "r": 0.05, "hardness": 1, "opacity": 1,
                  "dx": (210 - 700) / 1000, "dy": (210 - 450) / 700}
        for name, fr in {"crop": {"crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}}, "turn90+str": {"turn": 90, "straighten": 4},
                         "persp": {"persp": {"tl": [0.05, 0.08], "tr": [0.92, 0.02], "br": [0.97, 0.95], "bl": [0.02, 0.9]}},
                         "cover": {"tools": {"crop_format": {"format": "square", "fit": "cover", "focus": "center"}}},
                         "contain": {"tools": {"crop_format": {"format": "story", "fit": "contain", "fill": "white", "padding": 8}}}}.items():
            data = {"layers": [BASE, {"id": "rt", "type": "retouch", "strokes": [stroke]}], **fr}
            a = self.render(data, 1, photo_)
            new, rep = self.migrate(data)
            self.assertTrue(rep["stamped"], rep)
            b = self.render(new, 2, photo_)
            self.assertSameSpot(a, b, (0, 255, 0), 2.5, name)
            self.assertEqual(len(blobs(b, (0, 255, 0))), 2, "منبع و کپی")
        # عددی: برشِ ۵۰٪ ⇒ شعاع ×۲
        new, _ = self.migrate({"crop": {"x": 0.25, "y": 0, "w": 0.5, "h": 1}, "layers": [BASE, {"id": "rt", "type": "retouch", "strokes": [stroke]}]})
        s = new["layers"][1]["strokes"][0]
        self.assertAlmostEqual(s["r"], 0.05 * 2, places=4)
        self.assertAlmostEqual(s["pts"][0][0], (0.7 * 1000 - 250) / 500, places=4)
        self.assertAlmostEqual(s["dx"], -490 / 500, places=4)
        self.assertAlmostEqual(s["dy"], -240 / 700, places=4)

    def test_idempotent_and_never_stamps_twice(self):
        data = {"turn": 90, "layers": [BASE, rect(0.5, 0.5, 0.2, 0.1)]}
        new, rep = self.migrate(data)
        self.assertTrue(rep["changed"])
        again, rep2 = frames.migrate_v1_to_v2(new, self.W, self.H, self.tmp)
        self.assertIs(again, new)
        self.assertEqual((rep2["already"], rep2["changed"]), (True, False))
        self.assertEqual(again["layers"][1]["cx"], new["layers"][1]["cx"])
        v3, rep3 = frames.migrate_v1_to_v2({"fv": 3, "turn": 90}, self.W, self.H, self.tmp)
        self.assertEqual(v3, {"fv": 3, "turn": 90})
        self.assertTrue(rep3["already"])
        # ورودی دست‌نخورده می‌ماند (کپی کار می‌کند)
        orig = {"turn": 90, "layers": [BASE, rect(0.5, 0.5, 0.2, 0.1)]}
        snap = copy.deepcopy(orig)
        frames.migrate_v1_to_v2(orig, self.W, self.H, self.tmp)
        self.assertEqual(orig, snap)

    def test_garbage_never_raises_and_is_left_unchanged(self):
        junk = [None, [], "x", 5, {"layers": "abc"}, {"layers": [None, 5, "x", {"type": 3}, {}], "turn": 90},
                {"turn": "x", "crop": {"x": "a", "w": None}, "persp": {"tl": "bad"}, "layers": [BASE]},
                {"turn": 90, "layers": [{"type": "shape", "cx": "q", "cy": None, "w": float("inf"), "rot": float("nan"),
                                         "mask": {"type": "radial", "c": "zz", "rx": "a"}}]},
                {"turn": 90, "layers": [{"type": "retouch", "strokes": [None, 3, {"pts": "x"}, {"pts": [[1], "a"], "r": "z"}]}]},
                {"turn": 90, "layers": [{"type": "text", "tile": 5, "cx": 1e99, "size": 1e99}]},
                {"tools": "no", "turn": 90}, {"tools": {"crop_format": "oops", "kit_square": 5}, "turn": 90},
                {"persp": {"tl": [0, 0], "tr": [0, 0], "br": [0, 0], "bl": [0, 0]}, "layers": [BASE, rect(0.5, 0.5, 0.2, 0.1)]},
                {"persp": {"tl": [0, 0], "tr": [1, 1], "br": [2, 2], "bl": [-1, -1]}, "layers": [BASE]},
                {"crop": {"x": 0.9, "y": 0.9, "w": 0.0001, "h": 0.0001}, "layers": [BASE, rect(0.5, 0.5, 0.2, 0.1)]},
                {"straighten": 1e9, "turn": 12345, "layers": [BASE]}]
        for item in junk:
            snap = copy.deepcopy(item)
            out, rep = frames.migrate_v1_to_v2(item, self.W, self.H, self.tmp, asset_path=self.asset)
            self.assertEqual(item, snap if not isinstance(snap, float) else item)      # ورودی تغییر نکرد
            self.assertIn("stamped", rep)
            if not rep["stamped"]:
                self.assertIs(out, item, item)
            else:
                self.assertEqual(out["fv"], 2)
        # اندازهٔ عکس نامعلوم یا نامعتبر
        out, rep = frames.migrate_v1_to_v2({"turn": 90, "layers": [BASE]}, 0, 0, self.tmp)
        self.assertFalse(rep["stamped"])
        self.assertNotIn("fv", out)
        out, rep = frames.migrate_v1_to_v2({"turn": 90}, None, None, None)
        self.assertFalse(rep["stamped"])
        out, rep = frames.migrate_v1_to_v2({"turn": 90, "layers": [BASE]}, self.W, self.H, None)
        self.assertTrue(rep["stamped"], "بی پوشهٔ پروژه هم لایه‌ها کوچ می‌خورند")
        # تباه‌شدگی: چهارضلعیِ صفر، مقیاسِ صفر
        out, rep = frames.migrate_v1_to_v2({"persp": {"tl": [0, 0], "tr": [0, 0], "br": [0, 0], "bl": [0, 0]}, "layers": [BASE]},
                                           self.W, self.H, self.tmp)
        self.assertFalse(rep["stamped"])
        self.assertTrue(rep["error"])
        self.assertNotIn("fv", out)


# ═════════════════════════════ سرویس: ترتیب، تلاش دوباره، پیش‌نمایش = خروجی

class ServicesOrderTests(ApiTestBase):
    def post_edit(self, aid, ops_, recipe="manual"):
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": recipe, "operations": ops_}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"]), r.json()["edits"][0]

    def test_new_edits_are_ordered_and_stamped(self):
        (aid,) = self.upload(photo(400, 300))
        e, d = self.post_edit(aid, [op("text", text="قهوه"), op("crop_format", format="square", fit="cover", focus="center"),
                                    op("auto_tone"), {"tool": "export", "params": {"format": "png"}}])
        self.assertEqual(tools_of(e.operations), ["crop_format", "auto_tone", "text", "export"])
        self.assertEqual(e.stats["order"], 2)
        self.assertEqual(d["order"], 2)
        self.assertEqual(e.state, "READY", e.error)
        with Image.open(self.media / e.files["result"]) as im:
            self.assertEqual(im.size, (1080, 1080))

    def test_retry_of_a_legacy_edit_reproduces_the_legacy_order(self):
        (aid,) = self.upload(photo(400, 300))
        legacy_ops = catalog.normalize_operations([op("text", text="همسان"), op("crop_format", format="square", focus="center"),
                                                   {"tool": "export", "params": {"format": "png"}}], order=1)
        self.assertEqual(tools_of(legacy_ops), ["text", "crop_format", "export"])
        old = PhotoEdit.objects.create(asset=PhotoAsset.objects.get(pk=aid), number=1, recipe="manual", operations=legacy_ops,
                                       state=PhotoEdit.State.READY, message="آماده")
        self.assertNotIn("order", old.stats)
        self.assertEqual(services.edit_dict(old)["order"], 1)
        r = self.api.post(f"{self.base}/edits/{old.pk}/retry/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        new = PhotoEdit.objects.get(pk=r.json()["new"]["id"])
        self.assertEqual(tools_of(new.operations), ["text", "crop_format", "export"], "ترتیبِ قدیمی عیناً")
        self.assertEqual(new.stats["order"], 1)
        self.assertEqual(new.state, "READY", new.error)
        # نسخهٔ تازه: تلاش دوباره ترتیبِ تازه را نگه می‌دارد
        fresh, _d = self.post_edit(aid, [op("text", text="همسان"), op("crop_format", format="square", focus="center"),
                                         {"tool": "export", "params": {"format": "png"}}])
        self.assertEqual(tools_of(fresh.operations), ["crop_format", "text", "export"])
        r = self.api.post(f"{self.base}/edits/{fresh.pk}/retry/", {}, format="json")
        again = PhotoEdit.objects.get(pk=r.json()["new"]["id"])
        self.assertEqual(tools_of(again.operations), ["crop_format", "text", "export"])
        self.assertEqual(again.stats["order"], 2)
        # ترتیب‌ها واقعاً فرق دارند: متنی که پیش از برش کشیده شده با برش بزرگ می‌شود، متنِ تازه روی بومِ نهایی کشیده می‌شود
        a = np.asarray(Image.open(self.media / new.files["result"]).convert("RGB")).astype(int)
        b = np.asarray(Image.open(self.media / again.files["result"]).convert("RGB")).astype(int)
        self.assertEqual(a.shape, b.shape)
        self.assertGreater(np.abs(a - b).mean(), 0.2)

    def test_preview_and_export_share_the_order_and_the_pixels(self):
        (aid,) = self.upload(photo(400, 300))
        asset = PhotoAsset.objects.get(pk=aid)
        layers_ = [dict(BASE), rect(0.8, 0.2, 0.25, 0.1, 15, color="#ff00ff"),
                   {"id": "tx", "type": "text", "text": "تخفیف ویژه", "size": 0.09, "cx": 0.5, "cy": 0.85, "color": "#ffffff",
                    "box": {"color": "#000000", "opacity": 0.6, "pad": 0.3, "radius": 0.3}}]
        wanted = [op("crop_format", format="square", fit="cover", focus="center", window=[0.2, 0.0, 0.75, 1.0]),
                  op("color", brightness=10), {"tool": "compose", "params": {"project": 0, "layers": layers_}},
                  {"tool": "export", "params": {"format": "png"}}]
        shuffled = [wanted[2], wanted[1], wanted[3], wanted[0]]
        data1, info1 = services.preview(asset, wanted)
        data2, info2 = services.preview(asset, shuffled)
        self.assertEqual(data1, data2, "پیش‌نمایش ترتیبِ فراخواننده را نمی‌خواهد")
        self.assertEqual(info1["size"], [1080, 1080])
        e, _d = self.post_edit(aid, shuffled)
        self.assertEqual(e.state, "READY", e.error)
        self.assertEqual(tools_of(e.operations), ["crop_format", "color", "compose", "export"])
        res = np.asarray(Image.open(self.media / e.files["result"]).convert("RGB")).astype(int)
        pre = np.asarray(Image.open(io.BytesIO(data1)).convert("RGB")).astype(int)
        self.assertEqual(res.shape, pre.shape)
        self.assertLess(np.abs(res - pre).mean(), 2.5, "پیش‌نمایش (JPEG) و خروجی یک تصویرند")
        # لایهٔ سرخابی در همان جا: هر دو
        for img in (res, pre):
            m = (np.abs(img - np.array(MAGENTA)).sum(axis=2) < 90)
            ys, xs = np.nonzero(m)
            self.assertGreater(len(xs), 500)
            self.assertAlmostEqual(xs.mean(), 0.8 * 1080, delta=6)
            self.assertAlmostEqual(ys.mean(), 0.2 * 1080, delta=6)
        # لایه روی برشِ پنجره‌ای: متن آخر است ⇒ سفید و بدونِ رنگ‌خوردگی
        txt = res[int(0.85 * 1080) - 40:int(0.85 * 1080) + 40, 300:780]
        self.assertGreater(int((txt.min(axis=2) > 240).sum()), 200)

    def test_preset_operations_follow_the_v2_order(self):
        data = {"adjust": {"exposure": 0.3}, "tools": {"color": {"brightness": 5}, "look": {"style": "warm"},
                                                         "crop_format": {"format": "square"}, "auto_tone": {"strength": 50}},
                "layers": [{"id": "tx", "type": "text", "text": "x", "size": 0.05}], "output": {"format": "jpeg", "long_edge": 500}}
        got = tools_of(services.preset_operations(data, False))
        self.assertEqual(got, ["develop", "crop_format", "auto_tone", "look", "color", "compose", "resize", "export"])
        got = tools_of(services.preset_operations(data, True))
        self.assertEqual(got, ["kit_adjust", "crop_format", "auto_tone", "look", "color", "compose", "resize", "export"])
        # و create_edits هم همان را نگه می‌دارد
        self.assertEqual(tools_of(catalog.normalize_operations(services.preset_operations(data, False))), tools_of(services.preset_operations(data, False)))


# ═════════════════════════════ کوچِ تنبل از راهِ API و فرمانِ مدیریتی

class LazyMigrationApiTests(ApiTestBase):
    def mask(self, pid, mid="m1"):
        m = Image.new("L", (80, 60), 0)
        m.paste(255, (40, 20, 70, 50))
        r = self.api.put(f"{self.base}/projects/{pid}/masks/{mid}/", png_bytes(m), content_type="image/png")
        self.assertEqual(r.status_code, 200, r.content)

    def make(self, aid, data, title="پروژه"):
        r = self.api.post(f"{self.base}/projects/", {"asset": aid, "title": title, "data": data}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["project"]

    def v1(self, **kw):
        return {"layers": [dict(BASE), rect(0.7, 0.4, 0.2, 0.1, 0, mask={"type": "paint", "id": "m1", "invert": False})], **kw}

    def test_create_and_save_do_not_migrate(self):
        (aid,) = self.upload(photo(400, 300))
        p = self.make(aid, self.v1(turn=90))
        self.assertEqual(p["rev"], 1)
        self.assertNotIn("fv", p["data"])
        self.assertNotIn("migration", p)
        r = self.api.put(f"{self.base}/projects/{p['id']}/", {"data": self.v1(turn=90), "rev": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["project"]["rev"], 2)
        self.assertNotIn("fv", r.json()["project"]["data"])
        r = self.api.put(f"{self.base}/projects/{p['id']}/", {"data": {}, "rev": 1}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertNotIn("migration", r.json()["project"])
        self.assertEqual(r.json()["project"]["rev"], 2)
        # فهرست هم دست نمی‌زند
        lst = self.api.get(f"{self.base}/projects/?asset={aid}").json()["projects"]
        self.assertEqual(PhotoProject.objects.get(pk=p["id"]).rev, 2)
        self.assertEqual(len(lst), 1)

    def test_get_migrates_once_and_keeps_the_original(self):
        (aid,) = self.upload(photo(400, 300))
        p = self.make(aid, self.v1(turn=90, crop={"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}))
        self.mask(p["id"])
        row = PhotoProject.objects.get(pk=p["id"])
        before = copy.deepcopy(row.data)
        d = self.media / row.dir_rel
        orig_mask = (d / "mask-m1.png").read_bytes()
        stamp = row.updated_at
        r = self.api.get(f"{self.base}/projects/{p['id']}/")
        self.assertEqual(r.status_code, 200, r.content)
        proj = r.json()["project"]
        self.assertEqual(proj["data"]["fv"], 2)
        self.assertEqual(proj["rev"], 2)
        self.assertTrue(proj["migration"]["migrated"])
        self.assertFalse(proj["migration"]["trivial"])
        row.refresh_from_db()
        self.assertEqual(row.legacy, before, "JSON ِ اصل در legacy می‌ماند")
        self.assertNotIn("fv", row.legacy)
        self.assertEqual(row.updated_at, stamp, "ترتیبِ فهرست با بازکردن عوض نمی‌شود")
        # لایه جابه‌جا شد: تصویر ۴۰۰×۳۰۰، چرخش ۹۰°، برش ۸۰٪
        L = proj["data"]["layers"][1]
        self.assertNotEqual((L["cx"], L["cy"]), (0.7, 0.4))
        self.assertAlmostEqual(L["rot"], -90.0, places=2)
        # ماسکِ اصل کنارِ فایل‌ها، و در نقشهٔ ماسک‌ها نیست
        self.assertEqual((d / "v1-mask-m1.png").read_bytes(), orig_mask)
        self.assertEqual(sorted(proj["masks"]), ["m1"])
        self.assertNotEqual((d / "mask-m1.png").read_bytes(), orig_mask)
        with Image.open(d / "mask-m1.png") as im:
            self.assertEqual(im.size, (240, 320), "اندازهٔ بومِ نهایی: ۳۰۰×۴۰۰ پس از چرخش، ۸۰٪ برش")
        # بار دوم: دوباره کوچ نمی‌شود
        r2 = self.api.get(f"{self.base}/projects/{p['id']}/").json()["project"]
        self.assertEqual(r2["rev"], 2)
        self.assertNotIn("migration", r2)
        self.assertEqual(r2["data"], proj["data"])
        # ذخیره‌ی مرورگر (با fv=2) دوباره کوچ نمی‌خورد و ماسکِ اصل پاک نمی‌شود (gc)
        old = time.time() - 7200
        os.utime(d / "v1-mask-m1.png", (old, old))
        r3 = self.api.put(f"{self.base}/projects/{p['id']}/", {"data": r2["data"], "rev": 2}, format="json")
        self.assertEqual(r3.status_code, 200, r3.content)
        self.assertEqual(r3.json()["project"]["rev"], 3)
        self.assertEqual(r3.json()["project"]["data"]["fv"], 2)
        self.assertTrue((d / "v1-mask-m1.png").is_file())
        row.refresh_from_db()
        self.assertEqual(row.legacy, before, "legacy دوباره نوشته نمی‌شود")

    def test_trivial_empty_and_old_tab_saves(self):
        (aid,) = self.upload(photo(400, 300))
        p = self.make(aid, {"adjust": {"exposure": 0.4}})
        proj = self.api.get(f"{self.base}/projects/{p['id']}/").json()["project"]
        self.assertEqual(proj["data"]["fv"], 2)
        self.assertEqual(proj["data"]["adjust"], {"exposure": 0.4})
        self.assertTrue(proj["migration"]["trivial"])
        # تبِ قدیمی (بی fv) ذخیره کند ⇒ دفعهٔ بعد دوباره با معنای v1 کوچ می‌خورد (برچسبِ اشتباه نمی‌خورد)
        r = self.api.put(f"{self.base}/projects/{p['id']}/", {"data": {"turn": 90, "layers": [dict(BASE), rect(0.5, 0.5, 0.2, 0.1)]}}, format="json")
        self.assertNotIn("fv", r.json()["project"]["data"])
        again = self.api.get(f"{self.base}/projects/{p['id']}/").json()["project"]
        self.assertEqual(again["data"]["fv"], 2)
        self.assertAlmostEqual(again["data"]["layers"][1]["rot"], -90.0, places=2)

    def test_unconvertible_project_is_returned_untouched(self):
        (aid,) = self.upload(photo(400, 300))
        bad = {"persp": {"tl": [0, 0], "tr": [0, 0], "br": [0, 0], "bl": [0, 0]}, "layers": [dict(BASE), rect(0.5, 0.5, 0.2, 0.1)]}
        p = self.make(aid, bad)
        r = self.api.get(f"{self.base}/projects/{p['id']}/")
        self.assertEqual(r.status_code, 200)
        proj = r.json()["project"]
        self.assertNotIn("fv", proj["data"])
        self.assertEqual(proj["rev"], 1)
        self.assertFalse(proj["migration"]["migrated"])
        self.assertTrue(proj["migration"]["error"])
        row = PhotoProject.objects.get(pk=p["id"])
        self.assertEqual(row.legacy, {})
        self.assertEqual(row.rev, 1)

    def test_management_command_dry_run_and_real(self):
        (a1, a2) = self.upload(photo(400, 300), photo(300, 400, seed=3))
        triv = self.make(a1, {"adjust": {"exposure": 0.1}}, "ساده")
        framed = self.make(a2, self.v1(turn=270, flipH=True, tools={"crop_format": {"format": "story", "fit": "contain", "fill": "white"}}), "قاب‌دار")
        self.mask(framed["id"])
        done = self.make(a1, {"fv": 2, "layers": [dict(BASE)]}, "تمام")
        d = self.media / PhotoProject.objects.get(pk=framed["id"]).dir_rel
        mask_before = (d / "mask-m1.png").read_bytes()
        def summary(*args):
            out = StringIO()
            call_command("photoedit_migrate_frames", *args, stdout=out)
            m = re.search(r"SUMMARY (.*)", out.getvalue())
            self.assertTrue(m, out.getvalue())
            return {k: int(v) for k, v in (kv.split("=") for kv in m.group(1).split())}, out.getvalue()

        s, text = summary("--dry-run")
        self.assertIn("dry-run", text)
        self.assertEqual((s["dry_run"], s["total"], s["already"], s["migrated"], s["trivial"], s["failed"], s["masks"]),
                         (1, 3, 1, 2, 1, 0, 1))
        for pk in (triv["id"], framed["id"]):
            row = PhotoProject.objects.get(pk=pk)
            self.assertNotIn("fv", row.data)
            self.assertEqual((row.rev, row.legacy), (1, {}))
        self.assertEqual((d / "mask-m1.png").read_bytes(), mask_before)
        self.assertFalse((d / "v1-mask-m1.png").exists())
        s, text = summary()
        self.assertEqual((s["dry_run"], s["total"], s["already"], s["migrated"], s["trivial"], s["failed"], s["masks"]),
                         (0, 3, 1, 2, 1, 0, 1))
        for pk in (triv["id"], framed["id"], done["id"]):
            self.assertEqual(PhotoProject.objects.get(pk=pk).data["fv"], 2)
        row = PhotoProject.objects.get(pk=framed["id"])
        self.assertEqual(row.rev, 2)
        self.assertTrue(row.legacy)
        self.assertEqual(PhotoProject.objects.get(pk=done["id"]).rev, 1, "fv=2 دست نخورد")
        self.assertTrue((d / "v1-mask-m1.png").is_file())
        s, text = summary()
        self.assertEqual((s["total"], s["already"], s["migrated"], s["failed"]), (3, 3, 0, 0))
