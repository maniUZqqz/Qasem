"""لایه‌های پروژهٔ ادیتورِ عکس: وارسیِ JSON و ترکیب (compose) با Pillow + numpy.

مختصات همه‌جا «نسبی به بوم» است؛ بوم = خودِ عکسِ پایه (W×H):

* موقعیت ``cx``، ``cy``: کسری از W و H (مرکزِ لایه).
* **همهٔ طول‌ها** (``w``، ``h``، ``size``، ``r``، ضخامتِ خط…) کسری از **پهنای بوم** W هستند (u = W).
* چرخش ``rot``: درجه، ساعتگرد، دورِ مرکزِ لایه.
* لایه‌ها از پایین به بالا؛ دقیقاً یک لایهٔ ``base`` (عکسِ پایه که کارهای پیش از ``compose`` رویش انجام شده).

نوع‌ها: base، image، text، shape (rect/ellipse/line/path)، adjust (تنظیمِ ناحیه‌ای/سراسری)، retouch (کلون و ترمیمِ قلمی)،
group (گروهِ ایزوله)، redeye (قرمزیِ چشم).
ماسک: ``paint`` (فایلِ PNG ِ خاکستری در پوشهٔ پروژه)، ``linear``، ``radial``؛ ضریبِ نهاییِ هر لایه = پیدایی × ماسک.
تصویرِ بوم در حافظه uint8 RGBA (آلفای مستقیم) است؛ ترکیب نوار‌به‌نوار با float32 انجام می‌شود (سرورِ سایت ۳ گیگ حافظه دارد).

مدلِ «pro 2» (همه اختیاری؛ پروژه‌ای که از آن‌ها استفاده نکند دقیقاً مثلِ قبل ساخته می‌شود)
------------------------------------------------------------------------------------------
* ``parent`` (شناسهٔ یک ``group`` یا None) — فهرست تخت می‌ماند؛ درخت از روی parent ساخته می‌شود: لایه‌های بی‌والد = سطحِ بالا،
  فرزندانِ گروه = لایه‌هایی که parent==id گروه دارند، به ترتیبِ فهرست. والد باید گروهِ موجود باشد، بی‌حلقه، عمقِ گروه‌ها ≤ ۴.
  ``base`` والد/clip ندارد. ترتیبِ فهرستی بینِ گروه و فرزندانش مهم نیست (فقط ترتیبِ هم‌خواهرها).
* ``group``: فرزندان در یک انباشتگرِ شفافِ هم‌اندازهٔ بوم رسم می‌شوند؛ adjust/retouch/redeye داخلِ گروه فقط روی همان انباشتگر
  اثر دارند (RGBِ آلفای مستقیم؛ پیکسل‌های شفاف rgb=0 دارند ⇒ کلیدهای فضایی مثلِ clarity نزدیکِ لبهٔ محتوا تیره می‌شوند)؛ بعد نتیجه
  با blend/opacity/mask ِ خودِ گروه روی انباشتگرِ والد می‌نشیند. گروهِ پنهان ⇒ فرزندانش هم نیستند. گروهِ بی‌فرزند یا بی‌پیکسل ⇒ رد می‌شود.
* ``clip``: لایه (image|text|shape|group) به **نزدیک‌ترین هم‌خواهرِ پایین‌تر که image|text|shape|group باشد** (حتی پنهان) بریده می‌شود؛
  اگر نباشد نادیده. آلفای لایه × «شکلِ هدف» که = آلفای تایلِ هدف (با افکتِ پخته) × ماسکِ هدف × (اگر خودِ هدف clip است، شکلِ هدفِ
  خودش) — **پیدایی (opacity) و blend ِ هدف نه**. هدفِ پنهان یا بی‌پیکسل ⇒ لایهٔ بریده‌شده دیده نمی‌شود (مثلِ فوتوشاپ).
  ``clip`` برای adjust/retouch/redeye همیشه False نرمال می‌شود.
* ``fx`` (image|text|shape): سایه/درخشش/خطِ دور، پخته در تایلِ لایه پیش از blend/opacity/mask (``fx.py``).
* ``redeye`` (``redeye.py``) و شکلِ ``path`` (``paths.py``).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import blend as blendmod
from . import catalog, develop_np, textlayer
from . import fx as fxmod
from . import paths as pathsmod
from . import redeye as redeyemod
from .blend import BLEND_MODES

MAX_LAYERS = 80
MAX_STROKES = 400
MAX_POINTS_PER_STROKE = 2000
MAX_POINTS_TOTAL = 20000
MAX_CANVAS_PIXELS = 36_000_000
FLOAT_WORK_PIXELS = 16_000_000
STRIP_PIXELS = 1_500_000
MAX_GROUP_DEPTH = 4
MAX_EYES = redeyemod.MAX_EYES
MAX_PATH_POINTS = pathsmod.MAX_POINTS
FX_MAX_PIXELS = 25_000_000       # تایلِ لایه + حاشیهٔ افکت بزرگ‌تر از این ⇒ افکت نادیده (با یادداشت)

LAYER_TYPES = ("base", "image", "text", "shape", "adjust", "retouch", "group", "redeye")
TYPE_TITLES = {"base": "عکس", "image": "تصویر", "text": "متن", "shape": "شکل", "adjust": "تنظیم", "retouch": "روتوش",
               "group": "گروه", "redeye": "قرمزیِ چشم"}
#: لایه‌هایی که می‌توانند «بُرش به لایهٔ پایین» (clip) بشوند و هدفِ بُرش باشند
CLIP_TYPES = ("image", "text", "shape", "group")
FX_TYPES = ("image", "text", "shape")
_ID_RE = re.compile(r"^[a-z0-9_-]{1,24}$")
MASK_ID_RE = re.compile(r"^[a-z0-9_-]{1,24}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
SPATIAL_KEYS = {"highlights", "shadows", "clarity", "texture", "dehaze", "sharpen", "noiseLuma", "noiseColor",
                "vignette", "lensVignette", "distortion", "grain"}


class LayerError(catalog.CatalogError):
    """لایهٔ نامعتبر — متنش برای کاربر است."""


# ───────────────────────────── وارسی

def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, x))


def _r(x, n=5):
    return round(float(x), n)


def _color(v, default="#ffffff"):
    return v.lower() if isinstance(v, str) and _HEX.match(v) else default


def _bool(v, default=False):
    if v is None:
        return default
    return v in (True, 1, "1", "true", "True", "on")


def _xy(v, default=(0.5, 0.5), lo=-3.0, hi=4.0):
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return [_r(_num(v[0], lo, hi, default[0])), _r(_num(v[1], lo, hi, default[1]))]
    return [default[0], default[1]]


def normalize_mask(m) -> dict | None:
    if not m:
        return None
    if not isinstance(m, dict):
        raise LayerError("ماسکِ لایه نامعتبر است.")
    t = m.get("type")
    inv = _bool(m.get("invert"))
    if t == "paint":
        mid = str(m.get("id") or "")
        if not MASK_ID_RE.match(mid):
            raise LayerError("شناسهٔ ماسک نامعتبر است.")
        return {"type": "paint", "id": mid, "invert": inv}
    if t == "linear":
        return {"type": "linear", "p0": _xy(m.get("p0"), (0.5, 0.0)), "p1": _xy(m.get("p1"), (0.5, 1.0)), "invert": inv}
    if t == "radial":
        return {"type": "radial", "c": _xy(m.get("c")), "rx": _r(_num(m.get("rx"), 0.001, 4, 0.25)),
                "ry": _r(_num(m.get("ry"), 0.001, 4, 0.25)), "feather": _r(_num(m.get("feather"), 0, 1, 0.5)),
                "invert": inv}
    raise LayerError("نوعِ ماسک باید paint، linear یا radial باشد.")


def _stroke_spec(v, max_w):
    if not isinstance(v, dict):
        return None
    w = _num(v.get("w"), 0, max_w, 0)
    if w <= 0:
        return None
    return {"w": _r(w), "color": _color(v.get("color"), "#000000")}


def _norm_text(src: dict, out: dict) -> None:
    out["text"] = str(src.get("text") or "")[:500]
    lines = src.get("lines")
    out["lines"] = [str(x)[:500] for x in lines[:textlayer.MAX_LINES]] if isinstance(lines, list) and lines else None
    from . import fontreg

    out["font"] = src.get("font") if fontreg.known(src.get("font")) else fontreg.DEFAULT
    wt = int(round(_num(src.get("weight"), 300, 800, 700) / 100.0) * 100)
    out["weight"] = max(300, min(800, wt))
    out["size"] = _r(_num(src.get("size"), 0.005, 0.5, 0.06))
    out["color"] = _color(src.get("color"))
    out["align"] = src.get("align") if src.get("align") in ("right", "center", "left") else "center"
    out["dir"] = src.get("dir") if src.get("dir") in ("auto", "rtl", "ltr") else "auto"
    out["line_height"] = _r(_num(src.get("line_height"), 0.8, 3, 1.35))
    out["letter_spacing"] = _r(_num(src.get("letter_spacing"), -0.1, 1, 0))
    out["width"] = _r(_num(src.get("width"), 0, 4, 0))
    out["stroke"] = _stroke_spec(src.get("stroke"), 0.3)
    sh = src.get("shadow")
    out["shadow"] = ({"color": _color(sh.get("color"), "#000000"), "opacity": _r(_num(sh.get("opacity"), 0, 1, 0.5)),
                      "blur": _r(_num(sh.get("blur"), 0, 1, 0.1)), "dx": _r(_num(sh.get("dx"), -1, 1, 0.05)),
                      "dy": _r(_num(sh.get("dy"), -1, 1, 0.05))} if isinstance(sh, dict) else None)
    bx = src.get("box")
    out["box"] = ({"color": _color(bx.get("color"), "#000000"), "opacity": _r(_num(bx.get("opacity"), 0, 1, 0.5)),
                   "pad": _r(_num(bx.get("pad"), 0, 2, 0.3)), "radius": _r(_num(bx.get("radius"), 0, 1, 0.2))}
                  if isinstance(bx, dict) else None)
    tl = src.get("tile")
    out["tile"] = ({"angle": _r(_num(tl.get("angle"), -90, 90, 28)), "gap": _r(_num(tl.get("gap"), 0.5, 5, 1.6))}
                   if isinstance(tl, dict) else None)


def _norm_fx(v) -> dict | None:
    """افکتِ لایه: {shadow, stroke, glow} هرکدام None یا شیء؛ هر سه None ⇒ None. (اشیاء با opacity/w صفر می‌مانند و فقط اثر ندارند.)"""
    if not isinstance(v, dict):
        return None
    sh, st, gl = v.get("shadow"), v.get("stroke"), v.get("glow")
    out = {"shadow": None, "stroke": None, "glow": None}
    if isinstance(sh, dict):
        out["shadow"] = {"color": _color(sh.get("color"), "#000000"), "opacity": _r(_num(sh.get("opacity"), 0, 1, 0.5)),
                         "blur": _r(_num(sh.get("blur"), 0, 0.2, 0.012)), "dx": _r(_num(sh.get("dx"), -0.5, 0.5, 0.01)),
                         "dy": _r(_num(sh.get("dy"), -0.5, 0.5, 0.01))}
    if isinstance(st, dict):
        out["stroke"] = {"color": _color(st.get("color"), "#ffffff"), "w": _r(_num(st.get("w"), 0, 0.05, 0.004)),
                         "opacity": _r(_num(st.get("opacity"), 0, 1, 1.0))}
    if isinstance(gl, dict):
        out["glow"] = {"color": _color(gl.get("color"), "#ffd479"), "opacity": _r(_num(gl.get("opacity"), 0, 1, 0.8)),
                       "blur": _r(_num(gl.get("blur"), 0, 0.2, 0.02)), "size": _r(_num(gl.get("size"), 0, 0.05, 0.006))}
    return out if any(out.values()) else None


def _handle(v):
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        dx, dy = _r(_num(v[0], -3, 3, 0)), _r(_num(v[1], -3, 3, 0))
        return None if dx == 0 and dy == 0 else [dx, dy]
    return None


def _norm_path(v) -> dict:
    """مسیرِ قلم: {closed, pts:[{x, y, hi, ho}]} — واحدها کسری از جعبهٔ لایه (w × h)؛ ≤ ۲۰۰ نقطه."""
    if not isinstance(v, dict):
        return {"closed": True, "pts": []}
    pts_in = v.get("pts") if isinstance(v.get("pts"), list) else []
    if len(pts_in) > MAX_PATH_POINTS:
        raise LayerError(f"مسیر بیشتر از {MAX_PATH_POINTS} نقطه نمی‌شود.")
    pts = []
    for p in pts_in:
        if isinstance(p, dict):
            pts.append({"x": _r(_num(p.get("x"), -2, 3, 0.5)), "y": _r(_num(p.get("y"), -2, 3, 0.5)),
                        "hi": _handle(p.get("hi")), "ho": _handle(p.get("ho"))})
    return {"closed": _bool(v.get("closed"), True), "pts": pts}


def _norm_redeye(src: dict, out: dict) -> None:
    eyes_in = src.get("eyes") if isinstance(src.get("eyes"), list) else []
    if len(eyes_in) > MAX_EYES:
        raise LayerError(f"بیشتر از {MAX_EYES} چشم در یک لایه نمی‌شود.")
    out["eyes"] = [{"x": _r(_num(e.get("x"), 0, 1, 0.5)), "y": _r(_num(e.get("y"), 0, 1, 0.5)),
                    "r": _r(_num(e.get("r"), 0.002, 0.1, 0.012))} for e in eyes_in if isinstance(e, dict)]
    out["amount"] = _r(_num(src.get("amount"), 0, 1, 1.0))
    out["darken"] = _r(_num(src.get("darken"), 0, 1, 0.6))


def _norm_shape(src: dict, out: dict) -> None:
    out["shape"] = src.get("shape") if src.get("shape") in ("rect", "ellipse", "line", "path") else "rect"
    out["w"] = _r(_num(src.get("w"), 0.0005, 4, 0.3))
    out["h"] = _r(_num(src.get("h"), 0.0005 if out["shape"] == "path" else 0.0, 4, 0.15))
    out["radius"] = _r(_num(src.get("radius"), 0, 1, 0))
    if out["shape"] == "path":
        out["path"] = _norm_path(src.get("path"))
    if "fill" in src and src["fill"] is None:
        out["fill"] = None
    else:
        f = src.get("fill")
        if isinstance(f, dict) and f.get("type") == "gradient":
            out["fill"] = {"type": "gradient", "c0": _color(f.get("c0"), "#ffffff"), "c1": _color(f.get("c1"), "#000000"),
                           "angle": _r(_num(f.get("angle"), -360, 360, 90))}
        elif isinstance(f, dict):
            out["fill"] = {"type": "solid", "color": _color(f.get("color")), "opacity": _r(_num(f.get("opacity"), 0, 1, 1))}
        else:
            out["fill"] = {"type": "solid", "color": "#ffffff", "opacity": 1.0}
    out["stroke"] = _stroke_spec(src.get("stroke"), 0.2)
    if out["shape"] == "line" and not out["stroke"]:
        out["stroke"] = {"w": 0.005, "color": "#ffffff"}


def _norm_retouch(src: dict, out: dict) -> None:
    strokes, total = [], 0
    for s in (src.get("strokes") if isinstance(src.get("strokes"), list) else [])[:MAX_STROKES]:
        if not isinstance(s, dict):
            continue
        pts = []
        for p in (s.get("pts") if isinstance(s.get("pts"), list) else [])[:MAX_POINTS_PER_STROKE]:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append([_r(_num(p[0], -1, 2, 0.5), 4), _r(_num(p[1], -1, 2, 0.5), 4)])
        if not pts:
            continue
        total += len(pts)
        if total > MAX_POINTS_TOTAL:
            raise LayerError("روتوش بیش از اندازه نقطه دارد.")
        strokes.append({"mode": "heal" if s.get("mode") == "heal" else "clone", "pts": pts,
                        "r": _r(_num(s.get("r"), 0.001, 0.3, 0.02)), "hardness": _r(_num(s.get("hardness"), 0, 1, 0.5)),
                        "opacity": _r(_num(s.get("opacity"), 0, 1, 1)), "dx": _r(_num(s.get("dx"), -2, 2, 0)),
                        "dy": _r(_num(s.get("dy"), -2, 2, 0))})
    out["strokes"] = strokes


def _check_tree(out: list[dict]) -> None:
    """parent باید گروهِ موجود باشد؛ بی‌حلقه؛ عمقِ گروه‌های تودرتو ≤ MAX_GROUP_DEPTH."""
    by_id = {o["id"]: o for o in out}
    for o in out:
        p = o.get("parent")
        if p is None:
            continue
        tgt = by_id.get(p)
        if tgt is None:
            raise LayerError(f"گروهِ «{p}» برای لایهٔ «{o['name']}» پیدا نشد.")
        if tgt["type"] != "group":
            raise LayerError(f"والدِ لایهٔ «{o['name']}» باید یک «گروه» باشد.")
    for o in out:
        seen, cur, depth = {o["id"]}, o.get("parent"), 0
        while cur is not None:
            if cur in seen:
                raise LayerError("گروه‌ها حلقه دارند (یک گروه داخلِ خودش یا فرزندش است).")
            seen.add(cur)
            depth += 1
            cur = by_id[cur].get("parent")
        # depth = تعدادِ گروه‌های بالاسرِ این لایه؛ گروهِ سطحِ بالا ⇒ عمقِ ۱
        if o["type"] == "group" and depth + 1 > MAX_GROUP_DEPTH:
            raise LayerError(f"گروه‌ها بیشتر از {MAX_GROUP_DEPTH} سطح تودرتو نمی‌شوند.")


def normalize_layers(layers, *, store=None, base: str = "one") -> list[dict]:
    """لایه‌ها را وارسی و به بازه می‌برد؛ کلیدِ ناشناخته دور ریخته می‌شود.

    ``base``: «one» دقیقاً یک لایهٔ عکس، «at_most_one» حداکثر یکی، «none» هیچ (پیش‌تنظیم‌ها).
    ``store``: اگر داده شود، عکس‌هایِ کتابخانه باید مالِ همین فروشگاه باشند.
    """
    if layers is None:
        layers = []
    if not isinstance(layers, list):
        raise LayerError("layers باید فهرست باشد.")
    if len(layers) > MAX_LAYERS:
        raise LayerError(f"بیشتر از {MAX_LAYERS} لایه نمی‌شود.")
    out, seen = [], set()
    asset_ids: set[int] = set()
    for idx, src in enumerate(layers):
        if not isinstance(src, dict):
            raise LayerError("هر لایه باید یک شیء باشد.")
        t = src.get("type")
        if t not in LAYER_TYPES:
            raise LayerError(f"نوعِ لایه «{t}» ناشناخته است.")
        lid = str(src.get("id") or f"l{idx + 1}")
        if not _ID_RE.match(lid):
            raise LayerError("شناسهٔ لایه فقط حرفِ کوچکِ لاتین، رقم، _ و - (تا ۲۴ نویسه) است.")
        if lid in seen:
            raise LayerError("شناسهٔ لایه‌ها باید یکتا باشد.")
        seen.add(lid)
        blend = src.get("blend", "normal") or "normal"
        if blend not in BLEND_MODES:
            raise LayerError(f"حالتِ ترکیبِ «{blend}» ناشناخته است.")
        o = {"id": lid, "type": t, "name": str(src.get("name") or TYPE_TITLES[t])[:60],
             "visible": _bool(src.get("visible"), True), "locked": _bool(src.get("locked")),
             "opacity": _r(_num(src.get("opacity"), 0, 1, 1)),
             "blend": "normal" if t in ("adjust", "retouch", "redeye") else blend,
             "mask": normalize_mask(src.get("mask"))}
        if t == "base":
            if src.get("parent"):
                raise LayerError("لایهٔ «عکس» نمی‌تواند داخلِ گروه باشد.")
        else:
            par = src.get("parent")
            if par is not None and par != "" and not (isinstance(par, str) and _ID_RE.match(par)):
                raise LayerError("شناسهٔ گروهِ والد نامعتبر است.")
            o["parent"] = par or None
            o["clip"] = _bool(src.get("clip")) and t in CLIP_TYPES
        if t in FX_TYPES:
            o["fx"] = _norm_fx(src.get("fx"))
        if t in ("image", "text", "shape"):
            o["cx"] = _r(_num(src.get("cx"), -3, 4, 0.5))
            o["cy"] = _r(_num(src.get("cy"), -3, 4, 0.5))
            o["rot"] = _r(_num(src.get("rot"), -3600, 3600, 0), 3)
        if t == "image":
            s = src.get("src") if isinstance(src.get("src"), dict) else {}
            if s.get("kind") == "asset":
                try:
                    aid = int(s.get("asset"))
                except (TypeError, ValueError):
                    raise LayerError("برای لایهٔ تصویر شمارهٔ عکسِ کتابخانه را بدهید.") from None
                if aid <= 0:
                    raise LayerError("شمارهٔ عکسِ کتابخانه نامعتبر است.")
                asset_ids.add(aid)
                o["src"] = {"kind": "asset", "asset": aid}
            elif s.get("kind") == "paint":
                pid = str(s.get("id") or "")
                if not MASK_ID_RE.match(pid):
                    raise LayerError("شناسهٔ لایهٔ نقاشی نامعتبر است.")
                try:
                    rev = max(0, min(10**9, int(s.get("rev") or 0)))
                except (TypeError, ValueError):
                    rev = 0
                o["src"] = {"kind": "paint", "id": pid, "rev": rev}
            else:
                o["src"] = {"kind": "logo"}
            o["w"] = _r(_num(src.get("w"), 0.001, 4, 0.25))
            o["flip_h"] = _bool(src.get("flip_h"))
            o["flip_v"] = _bool(src.get("flip_v"))
            if o["src"]["kind"] == "paint":
                # لایهٔ نقاشی همیشه کلِ بوم را می‌پوشاند (مثلِ ماسک): جابه‌جایی/چرخش/قرینه/جلوه ندارد
                o.update({"cx": 0.5, "cy": 0.5, "rot": 0, "w": 1.0, "flip_h": False, "flip_v": False, "fx": None})
        elif t == "text":
            _norm_text(src, o)
        elif t == "shape":
            _norm_shape(src, o)
        elif t == "adjust":
            o["adjust"] = develop_np.normalize_adjust(src.get("adjust") if isinstance(src.get("adjust"), dict) else {})
            o["curve"] = catalog.normalize_curve(src.get("curve"))
        elif t == "retouch":
            _norm_retouch(src, o)
        elif t == "group":
            o["collapsed"] = _bool(src.get("collapsed"))
        elif t == "redeye":
            _norm_redeye(src, o)
        out.append(o)
    _check_tree(out)
    n_base = sum(1 for o in out if o["type"] == "base")
    if base == "one" and n_base != 1:
        raise LayerError("پروژه باید دقیقاً یک لایهٔ «عکس» داشته باشد.")
    if base == "at_most_one" and n_base > 1:
        raise LayerError("پروژه بیش از یک لایهٔ «عکس» ندارد.")
    if base == "none" and n_base:
        raise LayerError("پیش‌تنظیم لایهٔ «عکس» ندارد.")
    if store is not None and asset_ids:
        from .models import PhotoAsset

        found = set(PhotoAsset.objects.filter(store=store, pk__in=asset_ids).values_list("pk", flat=True))
        if found != asset_ids:
            raise LayerError("عکسِ یکی از لایه‌ها در کتابخانهٔ این فروشگاه نیست.")
    return out


def mask_ids(layers) -> set[str]:
    """شناسهٔ ماسک‌های رنگ‌آمیزی‌شده‌ای که لایه‌ها به آن‌ها اشاره دارند."""
    out = set()
    stack = list(layers or [])
    while stack:
        l = stack.pop()
        if not isinstance(l, dict):
            continue
        m = l.get("mask")
        if isinstance(m, dict) and m.get("type") == "paint" and m.get("id"):
            out.add(str(m["id"]))
        if isinstance(l.get("children"), list):          # فهرستِ تودرتو (اگر کسی بفرستد)؛ مدلِ ما تخت است و همهٔ لایه‌ها در فهرست‌اند
            stack.extend(l["children"])
    return out


def paint_ids(layers) -> set[str]:
    """شناسهٔ لایه‌های نقاشی (src.kind == "paint") که فهرست به آن‌ها اشاره دارد."""
    out = set()
    for l in layers or []:
        if isinstance(l, dict) and l.get("type") == "image" and isinstance(l.get("src"), dict) and l["src"].get("kind") == "paint" and l["src"].get("id"):
            out.add(str(l["src"]["id"]))
    return out


def preset_layers(layers) -> list[dict]:
    """لایه‌های قابلِ استفاده در پیش‌تنظیم: بدونِ لایهٔ عکس، روتوش و قرمزیِ چشم، بدونِ ماسکِ رنگ‌آمیزی (مختصاتشان به یک عکس بسته است).

    گروه‌ها (با parent و clip) می‌مانند؛ چون فقط لایه‌های غیرِ گروه و بی‌اثر در هدف حذف می‌شوند، والدِ هیچ لایه‌ای از دست نمی‌رود
    و هدفِ clip هم عوض نمی‌شود (base/retouch/redeye هرگز هدفِ clip نیستند).
    """
    clean = []
    for l in layers if isinstance(layers, list) else []:
        if not isinstance(l, dict) or l.get("type") in ("base", "retouch", "redeye"):
            continue
        if l.get("type") == "image" and isinstance(l.get("src"), dict) and l["src"].get("kind") == "paint":
            continue
        l = dict(l)
        m = l.get("mask")
        if isinstance(m, dict) and m.get("type") == "paint":
            l["mask"] = None
        clean.append(l)
    return normalize_layers(clean, base="none")


# ───────────────────────────── ماسک‌ها

def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _mask_region(spec, ctx, state, x0, y0, x1, y1, W, H) -> np.ndarray | None:
    """ماسک روی ناحیهٔ [x0:x1, y0:y1] بوم ⇐ float32 (h, w)، یا None = بی‌ماسک."""
    if not spec:
        return None
    t = spec["type"]
    ys = (np.arange(y0, y1, dtype=np.float32) + 0.5)[:, None]
    xs = (np.arange(x0, x1, dtype=np.float32) + 0.5)[None, :]
    if t == "paint":
        arr = state["paint"].get(spec["id"])
        if arr is None:
            path = ctx["mask_path"](state["project"], spec["id"]) if ctx.get("mask_path") else None
            if path is None or not Path(path).is_file():
                ctx["notes"].append("ماسکِ یکی از لایه‌ها پیدا نشد و نادیده گرفته شد")
                arr = False
            else:
                with Image.open(path) as im:
                    g = np.asarray(im.convert("L"))
                if g.shape != (H, W):
                    g = cv2.resize(g, (W, H), interpolation=cv2.INTER_LINEAR)
                arr = g
            state["paint"][spec["id"]] = arr
        if arr is False:
            return None
        m = arr[y0:y1, x0:x1].astype(np.float32) / 255.0
    elif t == "linear":
        p0x, p0y = spec["p0"][0] * W, spec["p0"][1] * H
        vx, vy = spec["p1"][0] * W - p0x, spec["p1"][1] * H - p0y
        len2 = vx * vx + vy * vy
        if len2 < 1e-9:
            m = np.ones((y1 - y0, x1 - x0), np.float32)
        else:
            tt = ((xs - p0x) * vx + (ys - p0y) * vy) / len2
            m = 1.0 - _smooth(tt)
    else:
        cx, cy = spec["c"][0] * W, spec["c"][1] * H
        dx = (xs - cx) / (spec["rx"] * W)
        dy = (ys - cy) / (spec["ry"] * W)
        d = np.sqrt(dx * dx + dy * dy)
        inner = min(max(0.0, 1.0 - spec["feather"]), 1.0 - 1e-6)
        m = 1.0 - _smooth((d - inner) / (1.0 - inner))
    m = m.astype(np.float32)
    if spec.get("invert"):
        m = 1.0 - m
    return m


# ───────────────────────────── جابه‌جایی (affine) و رندرِ لایه‌ها

def _tile_to_np(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGBA"), dtype=np.uint8)


def place(src: Image.Image, pivot, kx, ky, cx, cy, rot, flip_h, flip_v, W, H):
    """منبعِ RGBA را با مقیاس (kx, ky) پیکسلِ بوم به ازای هر پیکسلِ منبع، حولِ pivot، در (cx, cy) بوم می‌گذارد.

    فقط ناحیهٔ دیدنیِ روی بوم ساخته می‌شود ⇒ حافظه به اندازهٔ لایه بسته نیست. ⇐ (آرایهٔ uint8 h×w×4، x0، y0) یا None.
    """
    sw, sh = src.size
    th = math.radians(rot)
    c, s = math.cos(th), math.sin(th)
    px, py = pivot
    fh = -1.0 if flip_h else 1.0
    fv = -1.0 if flip_v else 1.0
    xs_, ys_ = [], []
    for u, v in ((0, 0), (sw, 0), (sw, sh), (0, sh)):
        lx, ly = (u - px) * kx * fh, (v - py) * ky * fv
        xs_.append(cx + lx * c - ly * s)
        ys_.append(cy + lx * s + ly * c)
    x0, x1 = max(0, int(math.floor(min(xs_)))), min(W, int(math.ceil(max(xs_))))
    y0, y1 = max(0, int(math.floor(min(ys_)))), min(H, int(math.ceil(max(ys_))))
    if x1 <= x0 or y1 <= y0:
        return None
    A, B = fh * c / kx, fh * s / kx
    D, E = -fv * s / ky, fv * c / ky
    C0 = px - A * cx - B * cy
    F0 = py - D * cx - E * cy
    data = (A, B, A * x0 + B * y0 + C0, D, E, D * x0 + E * y0 + F0)
    pm = src.convert("RGBa")
    out = pm.transform((x1 - x0, y1 - y0), Image.Transform.AFFINE, data, resample=Image.Resampling.BICUBIC)
    return _tile_to_np(out.convert("RGBA")), x0, y0


def _load_image_layer(layer, ctx, state):
    src = layer["src"]
    if src["kind"] == "paint":
        pkey = ("paint", src["id"])
        pcache = state["images"]
        if pkey not in pcache:
            ppath = ctx["paint_path"](state["project"], src["id"]) if ctx.get("paint_path") else None
            if not ppath or not Path(ppath).is_file():
                ctx["notes"].append("لایهٔ نقاشی پیدا نشد و نادیده گرفته شد")
                pcache[pkey] = None
            else:
                with Image.open(ppath) as pim:
                    pcache[pkey] = pim.convert("RGBA")
        return pcache[pkey]
    key = ("asset", src["asset"]) if src["kind"] == "asset" else ("logo", 0)
    cache = state["images"]
    if key not in cache:
        params = {"source": "asset", "asset": src["asset"]} if src["kind"] == "asset" else {"source": "store"}
        path = ctx["logo_path"](params) if ctx.get("logo_path") else None
        if not path:
            ctx["notes"].append("تصویرِ یکی از لایه‌ها پیدا نشد و نادیده گرفته شد")
            cache[key] = None
        else:
            from . import ops

            img = ops.load(path).convert("RGBA")
            cache[key] = img
    return cache[key]


def _render_image(layer, ctx, state, W, H):
    img = _load_image_layer(layer, ctx, state)
    if img is None:
        return None
    if layer["src"]["kind"] == "paint":
        if img.size != (W, H):
            img = img.resize((W, H), Image.Resampling.LANCZOS if W * H < img.width * img.height else Image.Resampling.BICUBIC)
        return _tile_to_np(img), 0, 0
    sw, sh = img.size
    wpx = layer["w"] * W
    hpx = wpx * sh / sw
    if fxmod.active(layer.get("fx")):
        nw, nh = max(1, int(round(wpx))), max(1, int(round(hpx)))
        m = fxmod.margin(layer["fx"], W)
        if (nw + 2 * m) * (nh + 2 * m) <= FX_MAX_PIXELS:
            # افکت‌ها به پیکسلِ بوم اند ⇒ عکس اول به اندازهٔ بومیِ لایه می‌آید؛ قرینه پیش از افکت (جهتِ سایه قرینه نشود)
            im = img if (nw, nh) == (sw, sh) else img.resize(
                (nw, nh), Image.Resampling.LANCZOS if nw * nh < sw * sh else Image.Resampling.BICUBIC)
            if layer["flip_h"]:
                im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            if layer["flip_v"]:
                im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            tile, pivot = fxmod.bake(im, (nw / 2, nh / 2), layer["fx"], W)
            return place(tile, pivot, wpx / nw, hpx / nh, layer["cx"] * W, layer["cy"] * H, layer["rot"], False, False, W, H)
        ctx["notes"].append(f"افکتِ لایهٔ «{layer['name']}» برای اندازهٔ بزرگِ لایه نادیده گرفته شد")
    if wpx < sw * 0.75:
        nw, nh = max(1, int(round(wpx))), max(1, int(round(hpx)))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        sw, sh = img.size
    return place(img, (sw / 2, sh / 2), wpx / sw, hpx / sh, layer["cx"] * W, layer["cy"] * H, layer["rot"],
                 layer["flip_h"], layer["flip_v"], W, H)


def _gradient_rgb(size, c0, c1, angle):
    w, h = size
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    xs = (np.arange(w, dtype=np.float32) - (w - 1) / 2)[None, :]
    ys = (np.arange(h, dtype=np.float32) - (h - 1) / 2)[:, None]
    half = max(1e-6, (abs(dx) * w + abs(dy) * h) / 2)
    t = np.clip((xs * dx + ys * dy) / (2 * half) + 0.5, 0, 1)[..., None]
    a0 = np.array([int(c0[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    a1 = np.array([int(c1[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    return np.clip(a0 + (a1 - a0) * t, 0, 255).astype(np.uint8)


def _render_shape(layer, ctx, W, H):
    wpx, hpx = layer["w"] * W, layer["h"] * W
    stroke = layer["stroke"]
    sw_px = stroke["w"] * W if stroke else 0.0
    if layer["shape"] == "line":
        hpx = max(hpx, 0.0)
        box_h = max(hpx, sw_px) + 2
    else:
        box_h = hpx
    pad = int(math.ceil(sw_px / 2)) + 2
    tw, th = int(math.ceil(wpx)) + 2 * pad, int(math.ceil(box_h)) + 2 * pad
    if tw < 2 or th < 2:
        return None
    if layer["shape"] == "path":
        return _render_path(layer, ctx, W, H, wpx, hpx, sw_px, pad, tw, th)
    ss = 2 if tw * th * 4 <= 16_000_000 else 1
    big = (tw * ss, th * ss)
    fill_mask = Image.new("L", big, 0)
    stroke_mask = Image.new("L", big, 0)
    fd, sd = ImageDraw.Draw(fill_mask), ImageDraw.Draw(stroke_mask)
    x0, y0, x1, y1 = pad * ss, pad * ss, (pad + wpx) * ss, (pad + box_h) * ss
    kind = layer["shape"]
    if kind == "rect":
        rad = layer["radius"] * min(x1 - x0, y1 - y0) / 2
        if rad > 0.5:
            fd.rounded_rectangle([x0, y0, x1, y1], radius=rad, fill=255)
            if sw_px:
                sd.rounded_rectangle([x0, y0, x1, y1], radius=rad, outline=255, width=max(1, int(round(sw_px * ss))))
        else:
            fd.rectangle([x0, y0, x1, y1], fill=255)
            if sw_px:
                sd.rectangle([x0, y0, x1, y1], outline=255, width=max(1, int(round(sw_px * ss))))
    elif kind == "ellipse":
        fd.ellipse([x0, y0, x1, y1], fill=255)
        if sw_px:
            sd.ellipse([x0, y0, x1, y1], outline=255, width=max(1, int(round(sw_px * ss))))
    else:
        mid = (y0 + y1) / 2
        sd.line([(x0, mid), (x1, mid)], fill=255, width=max(1, int(round(sw_px * ss))))
    if kind == "line":
        fill_mask = None
    if ss > 1:
        stroke_mask = stroke_mask.reduce(ss)
        if fill_mask is not None:
            fill_mask = fill_mask.reduce(ss)
    tile = _paint_shape(layer, fill_mask, stroke_mask, tw, th)
    return _finish_tile(layer, tile, (tw / 2, th / 2), ctx, W, H)


def _paint_shape(layer, fill_mask, stroke_mask, tw, th):
    """ماسک‌های پر و خط (L، هم‌اندازهٔ تایل) ⇒ تایلِ RGBA ِ رنگی."""
    stroke = layer["stroke"]
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    fill = layer["fill"]
    if fill and fill_mask is not None:
        if fill["type"] == "gradient":
            rgb = Image.fromarray(_gradient_rgb((tw, th), fill["c0"], fill["c1"], fill["angle"]), "RGB").convert("RGBA")
            rgb.putalpha(fill_mask)
        else:
            col = tuple(int(fill["color"][i:i + 2], 16) for i in (1, 3, 5))
            rgb = Image.new("RGBA", (tw, th), col + (0,))
            rgb.putalpha(fill_mask.point(lambda v: int(round(v * fill["opacity"]))))
        tile = Image.alpha_composite(tile, rgb)
    if stroke and stroke_mask is not None:
        col = tuple(int(stroke["color"][i:i + 2], 16) for i in (1, 3, 5))
        st = Image.new("RGBA", (tw, th), col + (0,))
        st.putalpha(stroke_mask)
        tile = Image.alpha_composite(tile, st)
    return tile


def _bake_fx(tile, pivot, layer, ctx, W):
    """افکتِ لایه را در تایل می‌پزد؛ تایلِ خیلی بزرگ ⇒ افکت نادیده (با یادداشت)."""
    fx = layer.get("fx")
    if not fxmod.active(fx):
        return tile, pivot
    m = fxmod.margin(fx, W)
    if (tile.width + 2 * m) * (tile.height + 2 * m) > FX_MAX_PIXELS:
        ctx["notes"].append(f"افکتِ لایهٔ «{layer['name']}» برای اندازهٔ بزرگِ لایه نادیده گرفته شد")
        return tile, pivot
    return fxmod.bake(tile, pivot, fx, W)


def _finish_tile(layer, tile, pivot, ctx, W, H):
    """افکت (اگر باشد) + جاگذاری با cx, cy, rot ِ لایه (بدونِ قرینه) ⇒ (آرایه، x0، y0) یا None."""
    tile, pivot = _bake_fx(tile, pivot, layer, ctx, W)
    return place(tile, pivot, 1.0, 1.0, layer["cx"] * W, layer["cy"] * H, layer["rot"], False, False, W, H)


def _render_path(layer, ctx, W, H, wpx, hpx, sw_px, pad, tw, th):
    """شکلِ ``path``: نقطه‌ها کسری از جعبهٔ w × h ⇒ پیکسلِ تایل = pad + x·wpx (مرکزِ جعبه = محورِ لایه)."""
    path = layer.get("path") or {}
    poly = pathsmod.flatten(path, wpx, hpx)
    if len(poly) < 2:
        return None
    poly = [(x + pad, y + pad) for x, y in poly]
    ss = 2 if tw * th * 4 <= 16_000_000 else 1
    to_l = lambda cov: Image.fromarray(np.clip(np.rint(cov * 255.0), 0, 255).astype(np.uint8), "L")
    fill_mask = to_l(pathsmod.fill_coverage(poly, tw, th, ss)) if layer["fill"] else None
    stroke_mask = (to_l(pathsmod.stroke_coverage(poly, bool(path.get("closed")), sw_px, tw, th, ss))
                   if layer["stroke"] else None)
    tile = _paint_shape(layer, fill_mask, stroke_mask, tw, th)
    return _finish_tile(layer, tile, (pad + wpx / 2, pad + hpx / 2), ctx, W, H)


def _render_text(layer, ctx, W, H):
    r = textlayer.render_text(layer, W)
    if r is None:
        return None
    tile, pivot = r
    tl = layer.get("tile")
    if tl:
        pat = textlayer.tile_pattern(tile, (W, H), tl["angle"], tl["gap"])
        if fxmod.active(layer.get("fx")):
            pat, (px, py) = _bake_fx(pat, (0, 0), layer, ctx, W)      # حاشیه‌ای که بیرونِ بوم می‌افتد بریده می‌شود
            px, py = int(round(px)), int(round(py))
            pat = pat.crop((px, py, px + W, py + H))
        return _tile_to_np(pat), 0, 0
    tile, pivot = _bake_fx(tile, pivot, layer, ctx, W)
    return place(tile, pivot, 1.0, 1.0, layer["cx"] * W, layer["cy"] * H, layer["rot"], False, False, W, H)


# ───────────────────────────── ترکیب روی بوم

def _strips(y0, y1, w):
    step = max(1, STRIP_PIXELS // max(1, w))
    for a in range(y0, y1, step):
        yield a, min(y1, a + step)


class _Shape:
    """«شکلِ برش» ِ یک لایه: آلفای مؤثرش (آلفای تایل × ماسک × برشِ خودش) به uint8، روی کادرِ تایل؛ بیرونِ کادر صفر."""
    __slots__ = ("arr", "x0", "y0")

    def __init__(self, arr, x0, y0):
        self.arr, self.x0, self.y0 = arr, x0, y0

    def region(self, x0, y0, x1, y1) -> np.ndarray:
        out = np.zeros((y1 - y0, x1 - x0), np.float32)
        ax0, ay0 = max(x0, self.x0), max(y0, self.y0)
        ax1, ay1 = min(x1, self.x0 + self.arr.shape[1]), min(y1, self.y0 + self.arr.shape[0])
        if ax1 > ax0 and ay1 > ay0:
            out[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = (
                self.arr[ay0 - self.y0:ay1 - self.y0, ax0 - self.x0:ax1 - self.x0].astype(np.float32) * np.float32(1 / 255.0))
        return out


def _shape_of(tile, x0, y0, mask_spec, clip, ctx, state, W, H) -> _Shape:
    th, tw = tile.shape[:2]
    arr = np.empty((th, tw), np.uint8)
    for a, b in _strips(0, th, tw):
        s = tile[a:b, :, 3].astype(np.float32) * np.float32(1 / 255.0)
        m = _mask_region(mask_spec, ctx, state, x0, y0 + a, x0 + tw, y0 + b, W, H)
        if m is not None:
            s *= m
        if clip is not None:
            s *= clip.region(x0, y0 + a, x0 + tw, y0 + b)
        arr[a:b] = np.clip(np.rint(s * 255.0), 0, 255).astype(np.uint8)
    return _Shape(arr, x0, y0)


def _composite_tile(acc, tile, x0, y0, mode, opacity, mask_spec, ctx, state, W, H, first, clip=None):
    th, tw = tile.shape[:2]
    if first and clip is None and mode == "normal" and not mask_spec and opacity >= 0.999 and (tw, th) == (W, H):
        acc[...] = tile
        return
    for a, b in _strips(0, th, tw):
        t = tile[a:b]
        a_s = t[..., 3].astype(np.float32) * np.float32(opacity / 255.0)
        m = _mask_region(mask_spec, ctx, state, x0, y0 + a, x0 + tw, y0 + b, W, H)
        if m is not None:
            a_s *= m
        if clip is not None:
            a_s *= clip.region(x0, y0 + a, x0 + tw, y0 + b)
        if not a_s.any():
            continue
        cs = t[..., :3].astype(np.float32) / 255.0
        dst = acc[y0 + a:y0 + b, x0:x0 + tw]
        ab = dst[..., 3].astype(np.float32) / 255.0
        cb = dst[..., :3].astype(np.float32) / 255.0
        cr, ar = blendmod.composite(mode, cb, ab, cs, a_s)
        dst[..., :3] = np.clip(cr * 255.0 + 0.5, 0, 255).astype(np.uint8)
        dst[..., 3] = np.clip(ar * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _lerp_region(acc, out_f, x0, y0, opacity, mask_spec, ctx, state, W, H):
    """acc[ناحیه] ← acc + (out − acc)·(پیدایی·ماسک)  (out: float32 ۰..۱، ‌h×w×3)."""
    h, w = out_f.shape[:2]
    for a, b in _strips(0, h, w):
        m = _mask_region(mask_spec, ctx, state, x0, y0 + a, x0 + w, y0 + b, W, H)
        k = np.full((b - a, w), opacity, np.float32) if m is None else m * np.float32(opacity)
        if not k.any():
            continue
        dst = acc[y0 + a:y0 + b, x0:x0 + w, :3]
        cur = dst.astype(np.float32)
        new = cur + (out_f[a:b] * 255.0 - cur) * k[..., None]
        dst[...] = np.clip(new + 0.5, 0, 255).astype(np.uint8)


def _radial_bbox(spec, W, H):
    if not spec or spec["type"] != "radial" or spec.get("invert"):
        return None
    cx, cy = spec["c"][0] * W, spec["c"][1] * H
    rx, ry = spec["rx"] * W, spec["ry"] * W
    x0, x1 = int(max(0, math.floor(cx - rx - 2))), int(min(W, math.ceil(cx + rx + 2)))
    y0, y1 = int(max(0, math.floor(cy - ry - 2))), int(min(H, math.ceil(cy + ry + 2)))
    if x1 <= x0 or y1 <= y0:
        return (0, 0, 1, 1)
    return x0, y0, x1, y1


def _apply_adjust(acc, layer, ctx, state, W, H, box=None):
    """box: فقط برای انباشتگرِ گروه — کادرِ محتوا (x0, y0, x1, y1)؛ کلیدهای غیرفضایی بیرونِ آن حساب نمی‌شوند (آنجا شفاف است)."""
    adj = develop_np.normalize_adjust(layer.get("adjust"))
    curve = catalog.normalize_curve(layer.get("curve"))
    if not adj and not curve:
        return
    x0, y0, x1, y1 = 0, 0, W, H
    spatial = bool(SPATIAL_KEYS & set(adj))
    if box is not None and not spatial:
        x0, y0, x1, y1 = box
    bb = _radial_bbox(layer.get("mask"), W, H)
    if bb and not spatial and (bb[2] - bb[0]) * (bb[3] - bb[1]) < 0.6 * W * H:
        x0, y0, x1, y1 = max(x0, bb[0]), max(y0, bb[1]), min(x1, bb[2]), min(y1, bb[3])
        if x1 <= x0 or y1 <= y0:
            return
    w, h = x1 - x0, y1 - y0
    rgb = acc[y0:y1, x0:x1, :3].astype(np.float32) / 255.0
    scale = float(ctx.get("scale") or 1.0)
    if w * h > FLOAT_WORK_PIXELS:
        k = math.sqrt(FLOAT_WORK_PIXELS / (w * h))
        small = cv2.resize(rgb, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
        del rgb
        res = develop_np.develop(small, adj, curve, scale=scale * k, inplace=True)
        out = cv2.resize(res, (w, h), interpolation=cv2.INTER_LINEAR)
        ctx["notes"].append("لایهٔ تنظیم روی نسخهٔ کوچک‌تر (۱۶ مگاپیکسل) حساب شد")
    else:
        out = develop_np.develop(rgb, adj, curve, scale=scale, inplace=True)
    _lerp_region(acc, out, x0, y0, layer["opacity"], layer.get("mask"), ctx, state, W, H)


def _polyline_dist(pts, x0, y0, w, h, r):
    dist = np.full((h, w), np.inf, np.float32)
    n = len(pts)
    segs = [(pts[i], pts[min(i + 1, n - 1)]) for i in range(max(1, n - 1))]
    for (ax, ay), (bx, by) in segs:
        wx0 = int(max(0, math.floor(min(ax, bx) - r - x0 - 1)))
        wx1 = int(min(w, math.ceil(max(ax, bx) + r - x0 + 2)))
        wy0 = int(max(0, math.floor(min(ay, by) - r - y0 - 1)))
        wy1 = int(min(h, math.ceil(max(ay, by) + r - y0 + 2)))
        if wx1 <= wx0 or wy1 <= wy0:
            continue
        X = (np.arange(wx0, wx1, dtype=np.float32) + x0 + 0.5)[None, :]
        Y = (np.arange(wy0, wy1, dtype=np.float32) + y0 + 0.5)[:, None]
        vx, vy = bx - ax, by - ay
        len2 = vx * vx + vy * vy
        if len2 < 1e-9:
            d = np.hypot(X - ax, Y - ay)
        else:
            t = np.clip(((X - ax) * vx + (Y - ay) * vy) / len2, 0, 1)
            d = np.hypot(X - (ax + t * vx), Y - (ay + t * vy))
        sub = dist[wy0:wy1, wx0:wx1]
        np.minimum(sub, d, out=sub)
    return dist


def _shift_idx(lo, hi, shift, size):
    return np.clip(np.arange(lo, hi) + shift, 0, size - 1)


def _apply_retouch(acc, layer, ctx, state, W, H):
    strokes = layer.get("strokes") or []
    if not strokes:
        return
    groups: list[list[dict]] = []
    key_prev = None
    for s in strokes:
        key = (int(round(s["dx"] * W)), int(round(s["dy"] * H)))
        if key != key_prev:
            groups.append([])
            key_prev = key
        groups[-1].append(s)
    for grp in groups:
        sx, sy = int(round(grp[0]["dx"] * W)), int(round(grp[0]["dy"] * H))
        heal = any(s["mode"] == "heal" for s in grp)
        bx0 = by0 = 10 ** 9
        bx1 = by1 = -10 ** 9
        for s in grp:
            r = s["r"] * W
            xs = [p[0] * W for p in s["pts"]]
            ys = [p[1] * H for p in s["pts"]]
            bx0, bx1 = min(bx0, min(xs) - r - 2), max(bx1, max(xs) + r + 2)
            by0, by1 = min(by0, min(ys) - r - 2), max(by1, max(ys) + r + 2)
        x0, y0 = int(max(0, math.floor(bx0))), int(max(0, math.floor(by0)))
        x1, y1 = int(min(W, math.ceil(bx1))), int(min(H, math.ceil(by1)))
        if x1 <= x0 or y1 <= y0 or (sx == 0 and sy == 0):
            continue
        sigma = max(1.0, 0.5 * max(s["r"] for s in grp) * W)
        marg = int(math.ceil(3 * sigma)) if heal else 0
        ex0, ey0, ex1, ey1 = max(0, x0 - marg), max(0, y0 - marg), min(W, x1 + marg), min(H, y1 + marg)
        tgt = acc[ey0:ey1, ex0:ex1, :3].astype(np.float32)
        src = acc[_shift_idx(ey0, ey1, sy, H)][:, _shift_idx(ex0, ex1, sx, W), :3].astype(np.float32)
        if heal:
            blur_t = cv2.GaussianBlur(tgt, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)
            blur_s = cv2.GaussianBlur(src, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)
            sample = src + (blur_t - blur_s)
        else:
            sample = src
        # آلفای گروه = ۱ − ∏(۱ − aᵢ)
        inv = np.ones((y1 - y0, x1 - x0), np.float32)
        for s in grp:
            r = s["r"] * W
            pts = [(p[0] * W, p[1] * H) for p in s["pts"]]
            d = _polyline_dist(pts, x0, y0, x1 - x0, y1 - y0, r)
            inner = s["hardness"] * r
            al = 1.0 - _smooth((d - inner) / max(1e-6, r - inner)) if inner < r else (d <= r).astype(np.float32)
            inv *= 1.0 - al.astype(np.float32) * np.float32(s["opacity"])
        alpha = 1.0 - inv
        m = _mask_region(layer.get("mask"), ctx, state, x0, y0, x1, y1, W, H)
        k = alpha * np.float32(layer["opacity"]) * (m if m is not None else 1.0)
        iy0, ix0 = y0 - ey0, x0 - ex0
        cur = tgt[iy0:iy0 + (y1 - y0), ix0:ix0 + (x1 - x0)]
        smp = sample[iy0:iy0 + (y1 - y0), ix0:ix0 + (x1 - x0)]
        new = cur + (smp - cur) * k[..., None]
        acc[y0:y1, x0:x1, :3] = np.clip(new + 0.5, 0, 255).astype(np.uint8)


def _apply_redeye(acc, layer, ctx, state, W, H):
    """قرمزیِ چشم فقط روی کادرِ چشم‌ها (redeye.py)؛ نتیجه با پیدایی × ماسکِ لایه با رنگِ پیشین ترکیب می‌شود (مثلِ تنظیم)."""
    eyes = layer.get("eyes") or []
    box = redeyemod.union_box(eyes, W, H)
    if not eyes or box is None:
        return
    x0, y0, x1, y1 = box
    rgb = acc[y0:y1, x0:x1, :3].astype(np.float32) / 255.0
    redeyemod.fix_region(rgb, x0, y0, eyes, float(layer["amount"]), float(layer["darken"]), W, H)
    _lerp_region(acc, rgb, x0, y0, layer["opacity"], layer.get("mask"), ctx, state, W, H)


def _union(a, b):
    if a is None:
        return b
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _layer_tile(layer, ctx, state, W, H, by_parent):
    """لایهٔ پیکسل‌ساز (base|image|text|shape|group) ⇒ (تایل uint8 h×w×4، x0، y0) یا None."""
    t = layer["type"]
    if t == "base":
        return _tile_to_np(state["base"]), 0, 0
    if t == "image":
        return _render_image(layer, ctx, state, W, H)
    if t == "text":
        return _render_text(layer, ctx, W, H)
    if t == "group":
        return _render_group(layer, ctx, state, W, H, by_parent)
    return _render_shape(layer, ctx, W, H)


def _render_group(layer, ctx, state, W, H, by_parent):
    """گروهِ ایزوله: فرزندان در انباشتگرِ شفافِ تازه ⇒ نتیجه (برش‌خورده به کادرِ محتوا؛ نمایی از انباشتگر) ⇒ (تایل، x0، y0)."""
    kids = by_parent.get(layer["id"]) or []
    if not kids:
        return None
    g = np.zeros((H, W, 4), np.uint8)
    dirty = _render_level(g, kids, ctx, state, W, H, by_parent, True)
    if dirty is None:
        return None
    x0, y0, x1, y1 = dirty
    return g[y0:y1, x0:x1], x0, y0


def _render_level(acc, items, ctx, state, W, H, by_parent, in_group=False):
    """یک سطح از درخت (فهرستِ هم‌خواهرها از پایین به بالا) روی ``acc`` ⇒ کادرِ «کثیف» (x0, y0, x1, y1) یا None."""
    first = True
    dirty = None
    target_of: dict[str, str] = {}
    targets: set[str] = set()
    last_t = None
    for l in items:
        if l["type"] in CLIP_TYPES:
            if l.get("clip") and last_t is not None:
                target_of[l["id"]] = last_t
                targets.add(last_t)
            last_t = l["id"]
    shapes: dict[str, _Shape] = {}
    for layer in items:
        if not layer["visible"]:
            continue
        t = layer["type"]
        try:
            if t == "adjust":
                if not first:
                    _apply_adjust(acc, layer, ctx, state, W, H, box=dirty if in_group else None)
                continue
            if t == "retouch":
                if not first:
                    _apply_retouch(acc, layer, ctx, state, W, H)
                continue
            if t == "redeye":
                if not first:
                    _apply_redeye(acc, layer, ctx, state, W, H)
                continue
            clip = None
            tid = target_of.get(layer["id"])
            if tid is not None:
                clip = shapes.get(tid)
                if clip is None:        # هدف پنهان یا بی‌پیکسل ⇒ چیزی دیده نمی‌شود
                    continue
            r = _layer_tile(layer, ctx, state, W, H, by_parent)
            if r is None:
                continue
            tile, x0, y0 = r
            _composite_tile(acc, tile, x0, y0, layer["blend"], layer["opacity"], layer.get("mask"), ctx, state, W, H,
                            first, clip)
            if layer["id"] in targets:
                shapes[layer["id"]] = _shape_of(tile, x0, y0, layer.get("mask"), clip, ctx, state, W, H)
            dirty = _union(dirty, (x0, y0, x0 + tile.shape[1], y0 + tile.shape[0]))
            first = False
            del tile, r
        except MemoryError:
            ctx["notes"].append(f"حافظه برای لایهٔ «{layer['name']}» کافی نبود")
    return dirty


def compose(base: Image.Image, layers: list[dict], ctx: dict, project: int = 0) -> Image.Image:
    """بومِ بوم‌اندازهٔ ``base`` ⇐ ترکیبِ لایه‌ها از پایین به بالا. ``layers`` همان خروجیِ normalize_layers است.

    درخت: سطحِ بالا = لایه‌های بی‌parent؛ فرزندانِ هر گروه = لایه‌هایی با parent==id (به ترتیبِ فهرست)."""
    ctx.setdefault("notes", [])
    layers = normalize_layers(layers, base="one")
    if base.mode not in ("RGB", "RGBA"):
        base = base.convert("RGBA" if "A" in base.mode else "RGB")
    W, H = base.size
    if W * H > MAX_CANVAS_PIXELS:
        k = math.sqrt(MAX_CANVAS_PIXELS / (W * H))
        base = base.resize((max(1, int(W * k)), max(1, int(H * k))), Image.Resampling.LANCZOS)
        W, H = base.size
        ctx["notes"].append("عکس خیلی بزرگ بود؛ لایه‌ها روی نسخهٔ ۳۶ مگاپیکسلی ترکیب شدند")
    acc = np.zeros((H, W, 4), np.uint8)
    state = {"paint": {}, "images": {}, "project": project, "base": base}
    by_parent: dict = {}
    for l in layers:
        by_parent.setdefault(l.get("parent"), []).append(l)
    _render_level(acc, by_parent.get(None, []), ctx, state, W, H, by_parent)
    img = Image.fromarray(acc, "RGBA")
    if acc[..., 3].min() == 255:
        return img.convert("RGB")
    return img
