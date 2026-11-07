"""«جعبهٔ فیلترها» (نوبت ۴): محو، تیز کردن، نویز، تغییر شکل، سبک‌سازی، رندر، تنظیم‌های رنگیِ «پخته‌شده» و کارهای اندازه/بوم.

هر افکت = یک تابعِ خالص روی آرایهٔ RGB ِ uint8 (+ آلفا). خروجی در ادیتور یک **لایهٔ تصویریِ تازه** می‌شود (غیرمخرب: لایهٔ زیرین سر جایش است و
می‌شود لایه را پنهان/حذف/ماسک کرد)؛ کارهای اندازه/بوم (``kind="photo"``) عکسِ تازه‌ای در کتابخانه می‌سازند. پیش‌نمایش و خروجیِ نهایی از همین کد
می‌آیند، پس یکی‌اند. ماسکِ اختیاری (انتخابِ کاربر) اثر را فقط روی ناحیه می‌نشاند.

بی وابستگیِ تازه: numpy، opencv (headless)، scipy و Pillow که از قبل نصب‌اند.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

MAX_SIDE = 4096


class EffectError(Exception):
    """خطایی که متنش برای کاربر است."""


# ───────────────────────────── مشخصاتِ پارامتر
def R(key, title, lo, hi, default, step=1, unit=""):
    return {"key": key, "title": title, "type": "range", "min": lo, "max": hi, "default": default, "step": step, "unit": unit}


def S(key, title, options, default):
    return {"key": key, "title": title, "type": "select", "options": [[v, t] for v, t in options], "default": default}


def C(key, title, default):
    return {"key": key, "title": title, "type": "color", "default": default}


def B(key, title, default=False):
    return {"key": key, "title": title, "type": "bool", "default": default}


DEFAULT_STOPS = [[0.0, "#7c3aed"], [0.55, "#ec4899"], [1.0, "#f59e0b"]]


def G(key, title, default=None):
    """شیبِ چندتوقفی: [[جایگاه ۰..۱، "#rrggbb"], …] (۲ تا ۱۲ توقف)؛ ویرایشگرِ دیداری در فرانت."""
    return {"key": key, "title": title, "type": "stops", "default": [list(s) for s in (default or DEFAULT_STOPS)]}


def clean_stops(v, default=None) -> list[list]:
    """هر ورودی ⇒ ۲ تا ۱۲ توقفِ معتبر (جایگاه گیره‌شده و مرتب، رنگِ شش‌رقمی)؛ نامعتبر ⇒ پیش‌فرض. ≡ pro/gradients.ts › normStops"""
    out = []
    if isinstance(v, (list, tuple)):
        for s in list(v)[:12]:
            if isinstance(s, (list, tuple)) and len(s) >= 2:
                try:
                    pos = float(s[0])
                except (TypeError, ValueError):
                    continue
                col = str(s[1]).lower()
                if len(col) == 7 and col.startswith("#") and all(ch in "0123456789abcdef" for ch in col[1:]):
                    out.append([round(min(1.0, max(0.0, pos)), 3), col])
    if len(out) < 2:
        return [list(s) for s in (default or DEFAULT_STOPS)]
    out.sort(key=lambda s: s[0])
    return out


@dataclass
class Effect:
    id: str
    group: str
    title: str
    params: list = field(default_factory=list)
    kind: str = "layer"                      # layer = لایهٔ تازه | photo = عکسِ تازه در کتابخانه
    blend: str = "normal"                    # حالتِ ترکیبِ پیشنهادیِ لایهٔ نتیجه
    needs_mask: bool = False
    note: str = ""
    fn: object = None


REGISTRY: dict[str, Effect] = {}


def effect(id, group, title, params=(), kind="layer", blend="normal", needs_mask=False, note=""):
    def deco(fn):
        REGISTRY[id] = Effect(id, group, title, list(params), kind, blend, needs_mask, note, fn)
        return fn
    return deco


# ───────────────────────────── ابزارهای مشترک
def _f(a):
    return a.astype(np.float32)


def _u8(a):
    return np.clip(a, 0, 255).astype(np.uint8)


def _lum(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _hex(c, default=(255, 255, 255)):
    try:
        c = str(c).lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return default


def _scale(img_shape, px):
    """طولی که برای عکسِ ۱۰۰۰ پیکسلی گفته شده را به اندازهٔ عکسِ واقعی می‌برد (نتیجه روی پیش‌نمایشِ کوچک و خروجیِ بزرگ یکسان دیده شود)."""
    return px * max(img_shape[:2]) / 1000.0


def _remap(rgb, alpha, mx, my, border=cv2.BORDER_REFLECT):
    out = cv2.remap(rgb, mx, my, cv2.INTER_LINEAR, borderMode=border)
    a2 = cv2.remap(alpha, mx, my, cv2.INTER_LINEAR, borderMode=border) if alpha is not None else None
    return out, a2


def _grid(h, w):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return x, y


# ───────────────────────────── محو
@effect("gaussian_blur", "محو", "محوِ گاوسی", [R("radius", "شعاع", 0.5, 60, 6, 0.5, "px")])
def _gauss(rgb, a, p):
    return cv2.GaussianBlur(rgb, (0, 0), _scale(rgb.shape, p["radius"])), None


@effect("box_blur", "محو", "محوِ جعبه‌ای", [R("radius", "شعاع", 1, 50, 5, 1, "px")])
def _box(rgb, a, p):
    k = max(1, int(round(_scale(rgb.shape, p["radius"]))))
    return cv2.blur(rgb, (2 * k + 1, 2 * k + 1)), None


@effect("motion_blur", "محو", "محوِ حرکتی", [R("angle", "زاویه", 0, 180, 0, 1, "°"), R("distance", "فاصله", 1, 150, 25, 1, "px")])
def _motion(rgb, a, p):
    n = max(1, int(round(_scale(rgb.shape, p["distance"]))))
    k = np.zeros((2 * n + 1, 2 * n + 1), np.float32)
    k[n, :] = 1.0
    m = cv2.getRotationMatrix2D((n, n), p["angle"], 1.0)
    k = cv2.warpAffine(k, m, k.shape[::-1])
    k /= max(1e-6, k.sum())
    return cv2.filter2D(rgb, -1, k, borderType=cv2.BORDER_REFLECT), None


@effect("radial_blur", "محو", "محوِ شعاعی (چرخشی / زوم)", [S("mode", "نوع", [("spin", "چرخشی"), ("zoom", "زوم")], "zoom"), R("amount", "مقدار", 1, 100, 30, 1, "%"),
                                                           R("cx", "مرکز افقی", 0, 100, 50, 1, "%"), R("cy", "مرکز عمودی", 0, 100, 50, 1, "%")])
def _radial(rgb, a, p):
    h, w = rgb.shape[:2]
    c = (w * p["cx"] / 100.0, h * p["cy"] / 100.0)
    acc = np.zeros(rgb.shape, np.float32)
    n = 14
    for i in range(n):
        t = (i / (n - 1)) - 0.5
        if p["mode"] == "spin":
            m = cv2.getRotationMatrix2D(c, t * p["amount"] * 0.3, 1.0)
        else:
            m = cv2.getRotationMatrix2D(c, 0, 1.0 + t * p["amount"] / 150.0)
        acc += cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return _u8(acc / n), None


@effect("lens_blur", "محو", "محوِ لنز (بوکه)", [R("radius", "شعاعِ دیافراگم", 2, 40, 12, 1, "px"), R("boost", "درخششِ نقاطِ روشن", 0, 100, 40, 1, "%")])
def _lens(rgb, a, p):
    r = max(1, int(round(_scale(rgb.shape, p["radius"]))))
    k = np.zeros((2 * r + 1, 2 * r + 1), np.float32)
    cv2.circle(k, (r, r), r, 1.0, -1)
    k /= k.sum()
    f = _f(rgb)
    wgt = 1.0 + (p["boost"] / 100.0) * 6.0 * (_lum(f) / 255.0) ** 6
    num = cv2.filter2D(f * wgt[..., None], -1, k, borderType=cv2.BORDER_REFLECT)
    den = cv2.filter2D(wgt, -1, k, borderType=cv2.BORDER_REFLECT)
    return _u8(num / np.maximum(den[..., None], 1e-3)), None


@effect("surface_blur", "محو", "محوِ حفظ‌کنندهٔ لبه (پوست‌صاف‌کن)", [R("radius", "شعاع", 1, 25, 8, 1, "px"), R("threshold", "آستانه", 1, 100, 25, 1)],
        note="لبه‌ها را نگه می‌دارد و بخش‌های هموار را نرم می‌کند؛ برای صاف‌کردنِ پوست یا زمینه.")
def _surface(rgb, a, p):
    d = min(25, 2 * max(1, int(round(_scale(rgb.shape, p["radius"])))) + 1)
    return cv2.bilateralFilter(rgb, d, p["threshold"] * 2.0, d / 2.0), None


@effect("tilt_shift", "محو", "محوِ شیفتِ شیب (ماکت‌نما)", [R("blur", "شدتِ محو", 2, 40, 14, 1, "px"), R("center", "جای نوارِ واضح", 0, 100, 50, 1, "%"), R("band", "پهنای نوارِ واضح", 5, 80, 25, 1, "%"),
                                                           R("angle", "زاویه", -90, 90, 0, 1, "°")])
def _tilt(rgb, a, p):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    t = math.radians(p["angle"])
    d = ((y / h - p["center"] / 100.0) * math.cos(t) - (x / w - 0.5) * math.sin(t))
    half = p["band"] / 200.0
    m = np.clip((np.abs(d) - half) / max(0.05, half * 1.2), 0, 1)[..., None]
    bl = cv2.GaussianBlur(rgb, (0, 0), _scale(rgb.shape, p["blur"]))
    return _u8(_f(rgb) * (1 - m) + _f(bl) * m), None


@effect("median", "محو", "میانه (حذفِ لکه و نویزِ نقطه‌ای)", [R("radius", "شعاع", 1, 15, 2, 1, "px")])
def _median(rgb, a, p):
    k = 2 * max(1, int(round(_scale(rgb.shape, p["radius"])))) + 1
    return cv2.medianBlur(rgb, min(k, 31)), None


# ───────────────────────────── تیز کردن
def _unsharp(rgb, amount, radius, thr):
    f = _f(rgb)
    bl = cv2.GaussianBlur(f, (0, 0), max(0.1, radius))
    diff = f - bl
    if thr > 0:
        diff = np.where(np.abs(diff) < thr, 0, diff)
    return _u8(f + diff * amount)


@effect("unsharp_mask", "تیز کردن", "شارپِ ماسکِ غیرتیز", [R("amount", "مقدار", 0, 500, 120, 5, "%"), R("radius", "شعاع", 0.1, 40, 2, 0.1, "px"), R("threshold", "آستانه", 0, 100, 0, 1)])
def _unsharp_fx(rgb, a, p):
    return _unsharp(rgb, p["amount"] / 100.0, _scale(rgb.shape, p["radius"]), p["threshold"]), None


@effect("smart_sharpen", "تیز کردن", "شارپِ هوشمند (فقط روشنایی)", [R("amount", "مقدار", 0, 400, 150, 5, "%"), R("radius", "شعاع", 0.1, 20, 1.5, 0.1, "px"), R("noise", "مهارِ نویز", 0, 100, 30, 1, "%")])
def _smart_sharp(rgb, a, p):
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    y = _f(ycc[..., 0])
    bl = cv2.GaussianBlur(y, (0, 0), max(0.1, _scale(rgb.shape, p["radius"])))
    d = y - bl
    thr = p["noise"] / 100.0 * 12.0
    d = np.where(np.abs(d) < thr, 0, d)
    ycc[..., 0] = _u8(y + d * p["amount"] / 100.0)
    return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB), None


@effect("high_pass", "تیز کردن", "بالاگذر (برای شارپِ حرفه‌ای)", [R("radius", "شعاع", 0.5, 60, 4, 0.5, "px")], blend="overlay",
        note="لایهٔ خاکستری می‌سازد؛ حالتِ ترکیبِ آن «همپوشانی» است و جزئیات را تیز می‌کند.")
def _highpass(rgb, a, p):
    f = _f(rgb)
    bl = cv2.GaussianBlur(f, (0, 0), _scale(rgb.shape, p["radius"]))
    return _u8(f - bl + 128), None


# ───────────────────────────── نویز
@effect("add_noise", "نویز", "افزودنِ نویز (دانه)", [R("amount", "مقدار", 1, 100, 15, 1, "%"), S("dist", "نوع", [("gauss", "گاوسی"), ("uniform", "یکنواخت")], "gauss"), B("mono", "تک‌رنگ", True),
                                                   R("seed", "دانه", 0, 999, 1, 1)])
def _addnoise(rgb, a, p):
    rng = np.random.default_rng(int(p["seed"]))
    h, w = rgb.shape[:2]
    shape = (h, w, 1) if p["mono"] else (h, w, 3)
    s = p["amount"] * 2.55 / 2.0
    n = rng.normal(0, s, shape) if p["dist"] == "gauss" else rng.uniform(-s * 1.7, s * 1.7, shape)
    return _u8(_f(rgb) + n), None


@effect("reduce_noise", "نویز", "کاهشِ نویز", [R("strength", "شدت", 1, 30, 8, 1), R("color", "نویزِ رنگی", 1, 30, 8, 1)],
        note="روی عکس‌های بزرگ در اندازهٔ کوچک‌تر انجام و برمی‌گردد (کمی نرم‌تر می‌شود).")
def _denoise(rgb, a, p):
    h, w = rgb.shape[:2]
    k = min(1.0, 1400.0 / max(h, w))
    src = cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    out = cv2.fastNlMeansDenoisingColored(src, None, float(p["strength"]), float(p["color"]), 7, 17)
    return (cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC) if k < 1 else out), None


@effect("dust_scratches", "نویز", "گردوغبار و خراش", [R("radius", "شعاع", 1, 10, 2, 1, "px"), R("threshold", "آستانه", 0, 128, 12, 1)])
def _dust(rgb, a, p):
    k = 2 * max(1, int(round(_scale(rgb.shape, p["radius"])))) + 1
    med = cv2.medianBlur(rgb, min(k, 31))
    bad = np.abs(_f(rgb) - _f(med)).max(axis=2) > p["threshold"]
    out = rgb.copy()
    out[bad] = med[bad]
    return out, None


# ───────────────────────────── تغییر شکل (هندسه)
@effect("wave", "تغییر شکل", "موج", [R("amplitude", "دامنه", 1, 100, 20, 1, "px"), R("length", "طولِ موج", 5, 400, 90, 1, "px"), S("axis", "جهت", [("h", "افقی"), ("v", "عمودی")], "h")])
def _wave(rgb, a, p):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    amp, ln = _scale(rgb.shape, p["amplitude"]), max(4.0, _scale(rgb.shape, p["length"]))
    if p["axis"] == "h":
        x = x + amp * np.sin(2 * np.pi * y / ln)
    else:
        y = y + amp * np.sin(2 * np.pi * x / ln)
    return _remap(rgb, a, x, y)


@effect("ripple", "تغییر شکل", "موجِ آب (ریپل)", [R("amount", "مقدار", 1, 100, 25, 1), R("size", "اندازه", 1, 100, 40, 1)])
def _ripple(rgb, a, p):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    amp, ln = _scale(rgb.shape, p["amount"] * 0.25), max(6.0, _scale(rgb.shape, p["size"]))
    return _remap(rgb, a, x + amp * np.sin(2 * np.pi * y / ln), y + amp * np.sin(2 * np.pi * x / ln))


def _polar_fx(rgb, a, cx, cy, fn):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    c = (w * cx / 100.0, h * cy / 100.0)
    R0 = min(w, h) / 2.0
    dx, dy = x - c[0], y - c[1]
    r = np.sqrt(dx * dx + dy * dy)
    th = np.arctan2(dy, dx)
    inside = r < R0
    nr, nth = fn(r / R0, th)
    mx = np.where(inside, c[0] + nr * R0 * np.cos(nth), x).astype(np.float32)
    my = np.where(inside, c[1] + nr * R0 * np.sin(nth), y).astype(np.float32)
    return _remap(rgb, a, mx, my)


@effect("twirl", "تغییر شکل", "چرخش (گرداب)", [R("angle", "زاویه", -720, 720, 200, 5, "°"), R("cx", "مرکز افقی", 0, 100, 50, 1, "%"), R("cy", "مرکز عمودی", 0, 100, 50, 1, "%")])
def _twirl(rgb, a, p):
    ang = math.radians(p["angle"])
    return _polar_fx(rgb, a, p["cx"], p["cy"], lambda r, th: (r, th + ang * (1 - r) ** 2))


@effect("pinch", "تغییر شکل", "جمع / باد کردن", [R("amount", "مقدار (منفی = باد)", -100, 100, 50, 1, "%"), R("cx", "مرکز افقی", 0, 100, 50, 1, "%"), R("cy", "مرکز عمودی", 0, 100, 50, 1, "%")])
def _pinch(rgb, a, p):
    k = p["amount"] / 100.0
    return _polar_fx(rgb, a, p["cx"], p["cy"], lambda r, th: (r * np.power(np.maximum(r, 1e-6), -k * 0.6) if k else r, th))


@effect("spherize", "تغییر شکل", "کروی‌کردن", [R("amount", "مقدار", -100, 100, 60, 1, "%"), R("cx", "مرکز افقی", 0, 100, 50, 1, "%"), R("cy", "مرکز عمودی", 0, 100, 50, 1, "%")])
def _spher(rgb, a, p):
    k = p["amount"] / 100.0
    return _polar_fx(rgb, a, p["cx"], p["cy"], lambda r, th: (np.clip(r + k * (np.arcsin(np.clip(r, 0, 1)) * 2 / np.pi - r), 0, 1), th))


@effect("lens_correction", "تغییر شکل", "اصلاحِ لنز (اعوجاج و تاریکیِ گوشه)", [R("distortion", "اعوجاج (منفی = بشکه‌ای)", -100, 100, -25, 1), R("vignette", "روشن‌کردنِ گوشه‌ها", 0, 100, 30, 1, "%")])
def _lenscorr(rgb, a, p):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    cx, cy = w / 2.0, h / 2.0
    nx, ny = (x - cx) / cx, (y - cy) / cy
    r2 = nx * nx + ny * ny
    k = p["distortion"] / 100.0 * 0.35
    f = 1 + k * r2
    out, a2 = _remap(rgb, a, (cx + nx * f * cx).astype(np.float32), (cy + ny * f * cy).astype(np.float32), cv2.BORDER_CONSTANT)
    if p["vignette"]:
        g = 1 + (p["vignette"] / 100.0) * 0.9 * np.clip(r2 / 2.0, 0, 1)
        out = _u8(_f(out) * g[..., None])
    return out, a2


# ───────────────────────────── سبک‌سازی
@effect("emboss", "سبک‌سازی", "برجسته (نقش‌برجسته)", [R("angle", "زاویهٔ نور", 0, 360, 135, 1, "°"), R("height", "ارتفاع", 1, 10, 3, 1), R("amount", "شدت", 50, 400, 100, 5, "%")])
def _emboss(rgb, a, p):
    t = math.radians(p["angle"])
    dx, dy = math.cos(t), -math.sin(t)
    g = cv2.GaussianBlur(_lum(_f(rgb)), (0, 0), max(0.4, p["height"] * 0.35 * max(rgb.shape[:2]) / 1000.0))
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    e = 128 + (gx * dx + gy * dy) * p["amount"] / 100.0
    return _u8(np.repeat(e[..., None], 3, axis=2)), None


@effect("find_edges", "سبک‌سازی", "یافتنِ لبه‌ها (طرحِ خطی)", [R("strength", "شدت", 10, 300, 100, 5, "%"), B("invert", "زمینهٔ سفید", True)])
def _edges(rgb, a, p):
    g = cv2.GaussianBlur(_lum(_f(rgb)), (0, 0), 1.0)
    mag = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)) * p["strength"] / 100.0 / 2.0
    e = 255 - mag if p["invert"] else mag
    return _u8(np.repeat(e[..., None], 3, axis=2)), None


@effect("mosaic", "سبک‌سازی", "موزاییک (پیکسلی)", [R("size", "اندازهٔ خانه", 2, 100, 14, 1, "px")])
def _mosaic(rgb, a, p):
    h, w = rgb.shape[:2]
    s = max(2, int(round(_scale(rgb.shape, p["size"]))))
    small = cv2.resize(rgb, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST), None


@effect("crystallize", "سبک‌سازی", "بلورین", [R("size", "اندازهٔ بلور", 5, 120, 30, 1, "px"), R("seed", "دانه", 0, 999, 3, 1)])
def _crystal(rgb, a, p):
    h, w = rgb.shape[:2]
    s = max(4, int(round(_scale(rgb.shape, p["size"]))))
    rng = np.random.default_rng(int(p["seed"]))
    gy, gx = np.mgrid[0:h:s, 0:w:s]
    py = np.clip(gy + rng.integers(0, s, gy.shape), 0, h - 1)
    px = np.clip(gx + rng.integers(0, s, gx.shape), 0, w - 1)
    seeds = np.zeros((h, w), bool)
    seeds[py, px] = True
    _, (iy, ix) = ndimage.distance_transform_edt(~seeds, return_indices=True)
    blurred = cv2.GaussianBlur(rgb, (0, 0), s / 4.0)
    return blurred[iy, ix], None


@effect("halftone", "سبک‌سازی", "نیم‌تن (نقطه‌چین)", [R("size", "اندازهٔ نقطه", 3, 40, 9, 1, "px"), R("angle", "زاویه", 0, 90, 45, 1, "°"), B("color", "رنگی", False)])
def _halftone(rgb, a, p):
    h, w = rgb.shape[:2]
    s = max(3.0, _scale(rgb.shape, p["size"]))
    t = math.radians(p["angle"])
    x, y = _grid(h, w)
    u = x * math.cos(t) + y * math.sin(t)
    v = -x * math.sin(t) + y * math.cos(t)
    fu, fv = (u / s) % 1.0 - 0.5, (v / s) % 1.0 - 0.5
    dist = np.sqrt(fu * fu + fv * fv)
    f = _f(rgb) / 255.0

    def dots(chan):
        small = cv2.resize(chan, (max(1, int(w / s)), max(1, int(h / s))), interpolation=cv2.INTER_AREA)
        lvl = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        r = np.sqrt(np.clip(1.0 - lvl, 0, 1)) * 0.72
        return np.where(dist < r, 0.0, 1.0)

    out = np.stack([dots(f[..., i]) for i in range(3)], axis=2) if p["color"] else np.repeat(dots(_lum(f))[..., None], 3, axis=2)
    return _u8(out * 255), None


@effect("watercolor", "سبک‌سازی", "آبرنگ / نقاشی", [R("smooth", "نرمی", 10, 200, 60, 1), R("detail", "جزئیات", 5, 100, 45, 1, "%")])
def _wc(rgb, a, p):
    h, w = rgb.shape[:2]
    k = min(1.0, 1200.0 / max(h, w))
    src = cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    out = cv2.stylization(src, sigma_s=float(p["smooth"]), sigma_r=p["detail"] / 100.0)
    return (cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC) if k < 1 else out), None


@effect("oil_paint", "سبک‌سازی", "رنگ‌روغن", [R("radius", "اندازهٔ قلم‌مو", 2, 20, 7, 1)])
def _oil(rgb, a, p):
    h, w = rgb.shape[:2]
    k = min(1.0, 1200.0 / max(h, w))
    src = cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    r = max(2, int(p["radius"]))
    out = cv2.pyrMeanShiftFiltering(src, sp=r * 1.5, sr=r * 5.0, maxLevel=1)
    return (cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC) if k < 1 else out), None


@effect("cartoon", "سبک‌سازی", "کارتونی", [R("colors", "تعدادِ رنگ", 3, 16, 7, 1), R("lines", "غلظتِ خط", 0, 100, 60, 1, "%")])
def _cartoon(rgb, a, p):
    h, w = rgb.shape[:2]
    k = min(1.0, 1200.0 / max(h, w))
    src = cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    sm = src
    for _ in range(2):
        sm = cv2.bilateralFilter(sm, 9, 40, 9)
    step = 256.0 / p["colors"]
    q = _u8(np.floor(_f(sm) / step) * step + step / 2)
    gray = cv2.medianBlur(cv2.cvtColor(src, cv2.COLOR_RGB2GRAY), 5)
    edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 7)
    m = (edges / 255.0)[..., None]
    q = _u8(_f(q) * (1 - (1 - m) * p["lines"] / 100.0))
    return (cv2.resize(q, (w, h), interpolation=cv2.INTER_CUBIC) if k < 1 else q), None


@effect("pencil_sketch", "سبک‌سازی", "طرحِ مدادی", [R("shade", "سایه‌روشن", 1, 100, 25, 1, "%"), B("color", "رنگی", False)])
def _pencil(rgb, a, p):
    g, c = cv2.pencilSketch(rgb, sigma_s=60, sigma_r=0.07, shade_factor=p["shade"] / 1000.0 + 0.01)
    return (c if p["color"] else cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)), None


# ───────────────────────────── رندر (لایهٔ تازه با افکتِ نور و بافت)
def _fractal(h, w, scale, seed):
    rng = np.random.default_rng(int(seed))
    acc = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    sc = max(4.0, scale)
    for _ in range(6):
        gh, gw = max(2, int(h / sc) + 2), max(2, int(w / sc) + 2)
        n = rng.random((gh, gw)).astype(np.float32)
        acc += amp * cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
        tot += amp
        amp *= 0.55
        sc /= 2.0
        if sc < 2:
            break
    acc /= tot
    return (acc - acc.min()) / max(1e-6, acc.max() - acc.min())


@effect("clouds", "رندر", "ابر", [R("scale", "اندازه", 20, 600, 200, 5, "px"), R("seed", "دانه", 0, 999, 7, 1), C("fg", "رنگِ تیره", "#3b4a6b"), C("bg", "رنگِ روشن", "#ffffff")], blend="screen",
        note="لایهٔ ابر می‌سازد؛ حالتِ ترکیب و شفافیتش را عوض کنید.")
def _clouds(rgb, a, p):
    h, w = rgb.shape[:2]
    n = _fractal(h, w, _scale(rgb.shape, p["scale"]), p["seed"])[..., None]
    c0, c1 = np.array(_hex(p["fg"], (59, 74, 107)), np.float32), np.array(_hex(p["bg"], (255, 255, 255)), np.float32)
    return _u8(c0 * (1 - n) + c1 * n), None


@effect("lens_flare", "رندر", "شعلهٔ لنز", [R("x", "جای نور (افقی)", 0, 100, 70, 1, "%"), R("y", "جای نور (عمودی)", 0, 100, 25, 1, "%"), R("brightness", "روشنایی", 10, 300, 120, 5, "%")], blend="screen")
def _flare(rgb, a, p):
    h, w = rgb.shape[:2]
    out = np.zeros((h, w, 3), np.float32)
    x, y = _grid(h, w)
    cx, cy = w * p["x"] / 100.0, h * p["y"] / 100.0
    s = min(h, w)
    k = p["brightness"] / 100.0
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    out += (255 * k * np.exp(-(d / (s * 0.05)) ** 2))[..., None] * np.array([1.0, 0.97, 0.9])
    out += (120 * k * np.exp(-(d / (s * 0.22)) ** 1.2))[..., None] * np.array([1.0, 0.85, 0.6])
    mx, my = w / 2.0, h / 2.0
    for t, rad, col in ((0.45, 0.06, (0.4, 0.8, 1.0)), (0.9, 0.04, (1.0, 0.6, 0.4)), (1.4, 0.09, (0.5, 1.0, 0.6)), (1.9, 0.05, (1.0, 0.9, 0.5))):
        gx, gy = cx + (mx - cx) * t, cy + (my - cy) * t
        dd = np.sqrt((x - gx) ** 2 + (y - gy) ** 2)
        ring = np.exp(-((dd - s * rad) / (s * 0.012)) ** 2) * 0.55 + np.exp(-(dd / (s * rad)) ** 2) * 0.22
        out += (255 * k * 0.8 * ring)[..., None] * np.array(col)
    return _u8(out), None


@effect("spotlight", "رندر", "نورِ نقطه‌ای (افکتِ نور)", [R("x", "جای نور (افقی)", 0, 100, 50, 1, "%"), R("y", "جای نور (عمودی)", 0, 100, 40, 1, "%"), R("radius", "شعاع", 5, 100, 45, 1, "%"),
                                                       R("intensity", "شدت", 0, 100, 60, 1, "%"), R("ambient", "نورِ محیط", 0, 100, 35, 1, "%"), C("color", "رنگِ نور", "#fff4dd")])
def _spot(rgb, a, p):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    d = np.sqrt(((x - w * p["x"] / 100.0) / (w * p["radius"] / 100.0)) ** 2 + ((y - h * p["y"] / 100.0) / (w * p["radius"] / 100.0)) ** 2)
    spot = np.exp(-(d ** 2) * 1.5)
    amb = p["ambient"] / 100.0
    gain = amb + (1 - amb) * spot
    col = np.array(_hex(p["color"], (255, 244, 221)), np.float32) / 255.0
    base = _f(rgb) * gain[..., None]
    base += (255 * col) * (p["intensity"] / 100.0) * 0.35 * spot[..., None]
    return _u8(base), None


# ───────────────────────────── تنظیم‌های رنگیِ «پخته‌شده» (ماسک‌پذیر)
@effect("invert", "رنگ", "وارونه (نگاتیو)", [])
def _invert(rgb, a, p):
    return 255 - rgb, None


@effect("posterize", "رنگ", "پوستری", [R("levels", "تعدادِ سطح", 2, 32, 5, 1)])
def _poster(rgb, a, p):
    step = 255.0 / (p["levels"] - 1)
    return _u8(np.round(_f(rgb) / step) * step), None


@effect("threshold", "رنگ", "آستانه (سیاه و سفید)", [R("level", "سطح", 0, 255, 128, 1), C("dark", "رنگِ تیره", "#000000"), C("light", "رنگِ روشن", "#ffffff")])
def _thresh(rgb, a, p):
    m = (_lum(_f(rgb)) >= p["level"])[..., None]
    return _u8(np.where(m, np.array(_hex(p["light"]), np.float32), np.array(_hex(p["dark"], (0, 0, 0)), np.float32))), None


@effect("gradient_map", "رنگ", "نقشهٔ شیب (دورنگ / سه‌رنگ)", [C("c0", "سایه‌ها", "#1b1b3a"), C("c1", "میانه‌ها", "#c0467a"), C("c2", "روشنایی‌ها", "#ffe9b0"), B("three", "سه‌رنگ", True)])
def _gmap(rgb, a, p):
    t = (_lum(_f(rgb)) / 255.0)[..., None]
    c0, c1, c2 = (np.array(_hex(p[k]), np.float32) for k in ("c0", "c1", "c2"))
    if p["three"]:
        out = np.where(t < 0.5, c0 + (c1 - c0) * (t * 2), c1 + (c2 - c1) * ((t - 0.5) * 2))
    else:
        out = c0 + (c2 - c0) * t
    return _u8(out), None


@effect("photo_filter", "رنگ", "فیلترِ رنگیِ عکاسی", [C("color", "رنگ", "#ec8a00"), R("density", "غلظت", 0, 100, 25, 1, "%"), B("keep_lum", "حفظِ روشنایی", True)])
def _pfilter(rgb, a, p):
    f = _f(rgb)
    col = np.array(_hex(p["color"]), np.float32)
    out = f * (1 - p["density"] / 100.0) + (f * col / 255.0 * 1.6) * (p["density"] / 100.0)
    if p["keep_lum"]:
        out *= (_lum(f) / np.maximum(_lum(out), 1.0))[..., None]
    return _u8(out), None


@effect("channel_mixer", "رنگ", "میکسرِ کانال‌ها", [R("rr", "قرمز ⇐ قرمز", -200, 200, 110, 1, "%"), R("rg", "سبز ⇐ قرمز", -200, 200, 0, 1, "%"), R("rb", "آبی ⇐ قرمز", -200, 200, -10, 1, "%"),
                                                  R("gr", "قرمز ⇐ سبز", -200, 200, 0, 1, "%"), R("gg", "سبز ⇐ سبز", -200, 200, 100, 1, "%"), R("gb", "آبی ⇐ سبز", -200, 200, 0, 1, "%"),
                                                  R("br", "قرمز ⇐ آبی", -200, 200, 0, 1, "%"), R("bg", "سبز ⇐ آبی", -200, 200, 0, 1, "%"), R("bb", "آبی ⇐ آبی", -200, 200, 90, 1, "%"), B("mono", "سیاه‌وسفید", False)])
def _mixer(rgb, a, p):
    f = _f(rgb)
    m = np.array([[p["rr"], p["rg"], p["rb"]], [p["gr"], p["gg"], p["gb"]], [p["br"], p["bg"], p["bb"]]], np.float32) / 100.0
    out = f @ m.T
    if p["mono"]:
        out = np.repeat(out[..., :1], 3, axis=2)
    return _u8(out), None


@effect("replace_color", "رنگ", "جایگزینیِ رنگ", [C("from", "رنگِ هدف", "#c82828"), R("fuzz", "دامنه", 5, 100, 40, 1, "%"), R("hue", "تغییرِ فام", -180, 180, 120, 1, "°"), R("sat", "تغییرِ اشباع", -100, 100, 0, 1), R("light", "تغییرِ روشنایی", -100, 100, 0, 1)])
def _replace(rgb, a, p):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV_FULL).astype(np.float32)
    t = cv2.cvtColor(np.array([[_hex(p["from"], (200, 40, 40))]], np.uint8), cv2.COLOR_RGB2HSV_FULL).astype(np.float32)[0, 0]
    dh = np.minimum(np.abs(hsv[..., 0] - t[0]), 256 - np.abs(hsv[..., 0] - t[0])) / 128.0
    ds = np.abs(hsv[..., 1] - t[1]) / 255.0
    dist = np.sqrt(dh ** 2 + (0.5 * ds) ** 2)
    wgt = np.clip(1 - dist / (p["fuzz"] / 100.0 * 0.9), 0, 1) ** 1.2
    hsv[..., 0] = (hsv[..., 0] + wgt * p["hue"] / 360.0 * 256) % 256
    hsv[..., 1] = np.clip(hsv[..., 1] * (1 + wgt * p["sat"] / 100.0), 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * (1 + wgt * p["light"] / 100.0), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB_FULL), None


@effect("equalize", "رنگ", "یکسان‌سازیِ هیستوگرام", [R("amount", "مقدار", 0, 100, 100, 1, "%")])
def _equalize(rgb, a, p):
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    eq = ycc.copy()
    eq[..., 0] = cv2.equalizeHist(ycc[..., 0])
    out = cv2.cvtColor(eq, cv2.COLOR_YCrCb2RGB)
    k = p["amount"] / 100.0
    return _u8(_f(rgb) * (1 - k) + _f(out) * k), None


@effect("color_balance", "رنگ", "تعادلِ رنگ (سایه / میانه / روشن)", [R("sh_r", "سایه: سبزآبی ⇄ قرمز", -100, 100, 0, 1), R("sh_g", "سایه: سرخابی ⇄ سبز", -100, 100, 0, 1), R("sh_b", "سایه: زرد ⇄ آبی", -100, 100, 0, 1),
                                                         R("md_r", "میانه: سبزآبی ⇄ قرمز", -100, 100, 15, 1), R("md_g", "میانه: سرخابی ⇄ سبز", -100, 100, 0, 1), R("md_b", "میانه: زرد ⇄ آبی", -100, 100, -15, 1),
                                                         R("hi_r", "روشن: سبزآبی ⇄ قرمز", -100, 100, 0, 1), R("hi_g", "روشن: سرخابی ⇄ سبز", -100, 100, 0, 1), R("hi_b", "روشن: زرد ⇄ آبی", -100, 100, 0, 1)])
def _balance(rgb, a, p):
    f = _f(rgb)
    t = (_lum(f) / 255.0)[..., None]
    w_sh, w_hi = np.clip(1 - t * 2, 0, 1), np.clip(t * 2 - 1, 0, 1)
    w_md = 1 - w_sh - w_hi
    d = (w_sh * np.array([p["sh_r"], p["sh_g"], p["sh_b"]]) + w_md * np.array([p["md_r"], p["md_g"], p["md_b"]]) + w_hi * np.array([p["hi_r"], p["hi_g"], p["hi_b"]])) * 0.6
    return _u8(f + d), None



# ───────────────────────────── سبکِ لایه (پخته‌شده): از روی آلفای لایه؛ برای «فقط لایهٔ فعال» ساخته شده
STYLE_GROUP = "سبکِ لایه (پخته‌شده)"
STYLE_NOTE = "روی لایهٔ فعال اعمال می‌شود و لایهٔ تازه‌ای با همان شکل می‌سازد؛ لایهٔ اصلی پنهان می‌شود (برگشت‌پذیر). بر خلافِ سبک‌های زنده (سایه، درخشش، خطِ دور)، بعدتر با لغزنده عوض نمی‌شود."


def _blend_mode(base, over, mode):
    if mode == "multiply":
        return base * over
    if mode == "screen":
        return 1 - (1 - base) * (1 - over)
    if mode == "overlay":
        return np.where(base < 0.5, 2 * base * over, 1 - 2 * (1 - base) * (1 - over))
    return over


def _a01(alpha):
    return alpha.astype(np.float32) / 255.0


@effect("color_overlay", STYLE_GROUP, "پوششِ رنگ", [C("color", "رنگ", "#e11d48"), R("opacity", "شدت", 0, 100, 60, 1, "%"),
                                                  S("mode", "حالت", [("normal", "عادی"), ("multiply", "ضرب"), ("screen", "صفحه"), ("overlay", "روکش")], "normal")], note=STYLE_NOTE)
def _color_overlay(rgb, a, p):
    f = _f(rgb) / 255.0
    ov = np.broadcast_to(np.array(_hex(p["color"]), np.float32) / 255.0, f.shape)
    k = p["opacity"] / 100.0
    return _u8((f * (1 - k) + _blend_mode(f, ov, p["mode"]) * k) * 255), None


@effect("gradient_overlay", STYLE_GROUP, "پوششِ شیب", [C("c0", "رنگِ اول", "#7c3aed"), C("c1", "رنگِ دوم", "#f59e0b"), R("angle", "زاویه", 0, 360, 90, 1, "°"), S("kind", "نوع", [("linear", "خطی"), ("radial", "شعاعی")], "linear"),
                                                     R("opacity", "شدت", 0, 100, 70, 1, "%"), S("mode", "حالت", [("normal", "عادی"), ("multiply", "ضرب"), ("screen", "صفحه"), ("overlay", "روکش")], "normal")], note=STYLE_NOTE)
def _gradient_overlay(rgb, a, p):
    h, w = rgb.shape[:2]
    ys, xs = np.where(a > 8)
    x0, x1, y0, y1 = (xs.min(), xs.max(), ys.min(), ys.max()) if len(xs) else (0, w - 1, 0, h - 1)
    x, y = _grid(h, w)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if p["kind"] == "radial":
        t = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max(1.0, math.hypot(x1 - x0, y1 - y0) / 2.0)
    else:
        th = math.radians(p["angle"])
        dx, dy = math.cos(th), math.sin(th)
        ext = max(1.0, abs(x1 - x0) * abs(dx) + abs(y1 - y0) * abs(dy))
        t = ((x - cx) * dx + (y - cy) * dy) / ext + 0.5
    t = np.clip(t, 0, 1)[..., None]
    c0, c1 = np.array(_hex(p["c0"]), np.float32) / 255.0, np.array(_hex(p["c1"]), np.float32) / 255.0
    g = c0 + (c1 - c0) * t
    f = _f(rgb) / 255.0
    k = p["opacity"] / 100.0
    return _u8((f * (1 - k) + _blend_mode(f, g, p["mode"]) * k) * 255), None


@effect("inner_shadow", STYLE_GROUP, "سایهٔ درونی", [C("color", "رنگ", "#000000"), R("opacity", "شدت", 0, 100, 65, 1, "%"), R("distance", "فاصله", 0, 80, 8, 1, "px"), R("angle", "زاویهٔ نور", 0, 360, 120, 1, "°"),
                                                   R("blur", "نرمی", 0, 60, 10, 1, "px")], note=STYLE_NOTE)
def _inner_shadow(rgb, a, p):
    A = _a01(a)
    d, bl = _scale(rgb.shape, p["distance"]), _scale(rgb.shape, p["blur"])
    th = math.radians(p["angle"])
    m = np.float32([[1, 0, -d * math.cos(th)], [0, 1, d * math.sin(th)]])
    inv = cv2.warpAffine(1.0 - A, m, (A.shape[1], A.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=1.0)
    s = np.clip(cv2.GaussianBlur(inv, (0, 0), max(0.5, bl)) * (p["opacity"] / 100.0), 0, 1) * A
    col = np.array(_hex(p["color"], (0, 0, 0)), np.float32)
    return _u8(_f(rgb) * (1 - s[..., None]) + col * s[..., None]), None


@effect("inner_glow", STYLE_GROUP, "درخششِ درونی", [C("color", "رنگ", "#fff3b0"), R("opacity", "شدت", 0, 100, 70, 1, "%"), R("size", "اندازه", 0, 60, 8, 1, "px"), R("blur", "نرمی", 1, 60, 10, 1, "px")], note=STYLE_NOTE)
def _inner_glow(rgb, a, p):
    A = _a01(a)
    inv = 1.0 - A
    r = int(round(_scale(rgb.shape, p["size"])))
    if r > 0:
        inv = cv2.dilate(inv, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    s = np.clip(cv2.GaussianBlur(inv, (0, 0), max(0.5, _scale(rgb.shape, p["blur"]))) * (p["opacity"] / 100.0) * 1.4, 0, 1) * A
    col = np.array(_hex(p["color"], (255, 243, 176)), np.float32)
    return _u8(_f(rgb) * (1 - s[..., None]) + col * s[..., None]), None


@effect("bevel_emboss", STYLE_GROUP, "برجسته‌سازی (بوِل)", [R("depth", "عمق", 10, 400, 120, 5, "%"), R("size", "اندازه", 1, 40, 8, 1, "px"), R("soften", "نرمی", 0, 20, 2, 1, "px"), R("angle", "زاویهٔ نور", 0, 360, 120, 1, "°"),
                                                        C("hi", "رنگِ روشنایی", "#ffffff"), C("sh", "رنگِ سایه", "#000000"), R("opacity", "شدت", 0, 100, 75, 1, "%")], note=STYLE_NOTE)
def _bevel(rgb, a, p):
    A = _a01(a)
    h = cv2.GaussianBlur(A, (0, 0), max(0.6, _scale(rgb.shape, p["size"]) / 2.0)) * _scale(rgb.shape, p["size"]) * 2.0
    gx, gy = cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3)
    th = math.radians(p["angle"])
    shade = (gx * math.cos(th) - gy * math.sin(th)) * p["depth"] / 100.0
    if p["soften"] > 0:
        shade = cv2.GaussianBlur(shade, (0, 0), _scale(rgb.shape, p["soften"]) / 2.0)
    hi = np.clip(shade, 0, 1) * A * (p["opacity"] / 100.0)
    sh = np.clip(-shade, 0, 1) * A * (p["opacity"] / 100.0)
    f = _f(rgb)
    f = f * (1 - hi[..., None]) + np.array(_hex(p["hi"]), np.float32) * hi[..., None]
    f = f * (1 - sh[..., None]) + np.array(_hex(p["sh"], (0, 0, 0)), np.float32) * sh[..., None]
    return _u8(f), None


@effect("pattern_overlay", STYLE_GROUP, "پوششِ الگو", [S("pattern", "الگو", [("stripes", "راه‌راه"), ("dots", "نقطه‌چین"), ("grid", "شطرنجی"), ("checker", "مربع‌مربع")], "stripes"), R("scale", "اندازه", 4, 120, 20, 1, "px"),
                                                     R("angle", "زاویه", 0, 180, 45, 1, "°"), C("color", "رنگ", "#ffffff"), R("opacity", "شدت", 0, 100, 25, 1, "%")], note=STYLE_NOTE)
def _pattern_overlay(rgb, a, p):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    s = max(3.0, _scale(rgb.shape, p["scale"]))
    th = math.radians(p["angle"])
    u = (x * math.cos(th) + y * math.sin(th)) / s
    v = (-x * math.sin(th) + y * math.cos(th)) / s
    fu, fv = u % 1.0, v % 1.0
    if p["pattern"] == "stripes":
        m = (fu < 0.5).astype(np.float32)
    elif p["pattern"] == "dots":
        m = (np.hypot(fu - 0.5, fv - 0.5) < 0.3).astype(np.float32)
    elif p["pattern"] == "grid":
        m = ((fu < 0.12) | (fv < 0.12)).astype(np.float32)
    else:
        m = (((np.floor(u) + np.floor(v)) % 2) == 0).astype(np.float32)
    k = (m * p["opacity"] / 100.0)[..., None]
    return _u8(_f(rgb) * (1 - k) + np.array(_hex(p["color"]), np.float32) * k), None


# ───────────────────────────── تبدیلِ لایه (پخته‌شده): کجی، پرسپکتیو، تاب — مثلِ «تبدیل» ِ ویرایشگرهای حرفه‌ای، ولی نتیجه یک لایهٔ تازه است
XF_GROUP = "تبدیلِ لایه (پخته‌شده)"
XF_NOTE = "روی لایهٔ فعال (یا کلِ تصویر) اعمال می‌شود و لایهٔ تازه‌ای می‌سازد؛ لایهٔ اصلی پنهان می‌شود و می‌شود برگشت. اگر شکل از بوم بیرون بزند بریده می‌شود."


def _bbox(a):
    """کادرِ پیکسل‌های دیدنی (آلفا > ۸) ⇒ (x0, y0, x1, y1)؛ همه‌جا شفاف ⇒ کلِ بوم."""
    ys, xs = np.where(a > 8)
    if len(xs) == 0:
        h, w = a.shape
        return 0, 0, w, h
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _remap_pm(rgb, a, mx, my):
    """بازنمونه‌گیریِ RGBA ِ پیش‌ضرب‌شده (لبه‌ها هاله نمی‌گیرند)."""
    af = a.astype(np.float32) / 255.0
    pm = np.dstack([rgb.astype(np.float32) * af[..., None], a.astype(np.float32)])
    out = cv2.remap(pm, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    al = out[..., 3]
    col = np.where(al[..., None] > 0.5, out[..., :3] / np.maximum(al[..., None] / 255.0, 1e-3), 0)
    return _u8(col), _u8(al)


@effect("skew_layer", XF_GROUP, "کجی (Skew)", [R("ax", "کجیِ افقی", -60, 60, 20, 1, "°"), R("ay", "کجیِ عمودی", -60, 60, 0, 1, "°")], note=XF_NOTE)
def _skew(rgb, a, p):
    h, w = a.shape
    x0, y0, x1, y1 = _bbox(a)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    kx, ky = math.tan(math.radians(p["ax"])), math.tan(math.radians(p["ay"]))
    M = np.array([[1.0, kx], [ky, 1.0]])
    Mi = np.linalg.inv(M)
    x, y = _grid(h, w)
    dx, dy = x - cx, y - cy
    sx = cx + Mi[0, 0] * dx + Mi[0, 1] * dy
    sy = cy + Mi[1, 0] * dx + Mi[1, 1] * dy
    return _remap_pm(rgb, a, sx, sy)


@effect("perspective_layer", XF_GROUP, "پرسپکتیو", [R("top", "بالا (− باز، + جمع)", -60, 60, 25, 1, "%"), R("bottom", "پایین (− باز، + جمع)", -60, 60, 0, 1, "%"),
                                                  R("left", "چپ (− باز، + جمع)", -60, 60, 0, 1, "%"), R("right", "راست (− باز، + جمع)", -60, 60, 0, 1, "%")], note=XF_NOTE)
def _perspective(rgb, a, p):
    h, w = a.shape
    x0, y0, x1, y1 = _bbox(a)
    bw, bh = float(x1 - x0), float(y1 - y0)
    src = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    t, b, l, r = p["top"] / 100.0, p["bottom"] / 100.0, p["left"] / 100.0, p["right"] / 100.0
    dst = np.float32([
        [x0 + bw * t / 2, y0 + bh * l / 2],           # بالا-چپ
        [x1 - bw * t / 2, y0 + bh * r / 2],           # بالا-راست
        [x1 - bw * b / 2, y1 - bh * r / 2],           # پایین-راست
        [x0 + bw * b / 2, y1 - bh * l / 2],           # پایین-چپ
    ])
    H_ = cv2.getPerspectiveTransform(dst, src)          # از خروجی به منبع
    x, y = _grid(h, w)
    den = H_[2, 0] * x + H_[2, 1] * y + H_[2, 2]
    sx = (H_[0, 0] * x + H_[0, 1] * y + H_[0, 2]) / den
    sy = (H_[1, 0] * x + H_[1, 1] * y + H_[1, 2]) / den
    return _remap_pm(rgb, a, sx, sy)


@effect("warp_layer", XF_GROUP, "تاب (Warp)", [S("style", "شکل", [("arc", "قوس"), ("wave", "موج"), ("flag", "پرچم"), ("bulge", "برآمده"), ("rise", "شیب")], "arc"), R("amount", "مقدار", -100, 100, 50, 1, "%")], note=XF_NOTE)
def _warp_layer(rgb, a, p):
    from . import textlayer

    h, w = a.shape
    x0, y0, x1, y1 = _bbox(a)
    cy = (y0 + y1) / 2.0
    bh = float(y1 - y0)
    xs = np.arange(w, dtype=np.float64)
    u = np.clip(((xs + 0.5 - x0) / max(1.0, float(x1 - x0))) * 2 - 1, -1.0, 1.0)
    dy, s = textlayer.warp_params(p["style"], p["amount"] / 100.0, u, 0.25 * bh)
    y = np.arange(h, dtype=np.float64)[:, None]
    sy = cy + (y + 0.5 - cy - dy[None, :]) / s[None, :] - 0.5
    sx = np.broadcast_to(xs[None, :], (h, w))
    return _remap_pm(rgb, a, sx, sy)


# ───────────────────────────── لایهٔ پرکننده (تک‌رنگ، شیب، الگو): ورودی را نادیده می‌گیرند و کلِ بوم را می‌پوشانند
FILL_GROUP = "لایهٔ پرکننده"
FILL_NOTE = "یک لایهٔ تازهٔ تمام‌بوم می‌سازد؛ با شفافیت، حالتِ ترکیب و ماسکِ لایه می‌شود روی عکس نشاندش."

#: کتابخانهٔ شیب‌ها: کلید ⇒ (عنوان، [(جایگاه ۰..۱، رنگ)، …])
GRADIENT_PRESETS = {
    "custom": ("دلخواه (دو رنگِ زیر)", None),
    "stops": ("دلخواه با توقف‌ها (ویرایشگرِ شیب)", None),
    "sunset": ("غروب", [(0.0, "#1f1147"), (0.45, "#c0467a"), (0.8, "#f59e0b"), (1.0, "#ffe9b0")]),
    "ocean": ("اقیانوس", [(0.0, "#022c5b"), (0.5, "#0ea5e9"), (1.0, "#a5f3fc")]),
    "forest": ("جنگل", [(0.0, "#052e16"), (0.55, "#16a34a"), (1.0, "#d9f99d")]),
    "candy": ("آب‌نبات", [(0.0, "#ec4899"), (0.5, "#a855f7"), (1.0, "#60a5fa")]),
    "gold": ("طلایی", [(0.0, "#7c4a03"), (0.35, "#f59e0b"), (0.6, "#fde68a"), (1.0, "#b45309")]),
    "steel": ("فولادی", [(0.0, "#1f2937"), (0.5, "#9ca3af"), (1.0, "#f3f4f6")]),
    "mono": ("سیاه تا سفید", [(0.0, "#000000"), (1.0, "#ffffff")]),
}


def _ramp(stops, t):
    """t ∈ [0,1] (آرایه) ⇒ رنگ (…×3) با درون‌یابیِ خطی میانِ توقف‌ها."""
    pos = np.array([s[0] for s in stops], np.float32)
    cols = np.array([_hex(s[1]) for s in stops], np.float32)
    out = np.empty(t.shape + (3,), np.float32)
    for k in range(3):
        out[..., k] = np.interp(t, pos, cols[:, k])
    return out


@effect("fill_solid", FILL_GROUP, "تک‌رنگ", [C("color", "رنگ", "#e11d48")], note=FILL_NOTE)
def _fill_solid(rgb, a, p):
    out = np.empty_like(rgb)
    out[...] = _hex(p["color"])
    return out, np.full(a.shape, 255, np.uint8)


@effect("fill_gradient", FILL_GROUP, "شیب (با نمونه‌های آماده)", [S("preset", "نمونه", [(k, v[0]) for k, v in GRADIENT_PRESETS.items()], "sunset"), C("c0", "رنگِ اول (دلخواه)", "#7c3aed"),
                                                                C("c1", "رنگِ دوم (دلخواه)", "#f59e0b"), S("kind", "نوع", [("linear", "خطی"), ("radial", "شعاعی"), ("angle", "زاویه‌ای")], "linear"),
                                                                R("angle", "زاویه", 0, 360, 90, 1, "°"), B("reverse", "برعکس", False),
                                                                G("stops", "توقف‌های شیب (برای نمونهٔ «دلخواه با توقف‌ها»)")], note=FILL_NOTE)
def _fill_gradient(rgb, a, p):
    h, w = a.shape
    x, y = _grid(h, w)
    cx, cy = w / 2.0, h / 2.0
    if p["kind"] == "radial":
        tt = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max(1.0, math.hypot(cx, cy))
    elif p["kind"] == "angle":
        tt = (np.arctan2(y - cy, x - cx) / (2 * math.pi) + 0.5 + p["angle"] / 360.0) % 1.0
    else:
        th = math.radians(p["angle"])
        dx, dy = math.cos(th), math.sin(th)
        half = max(1e-6, (abs(dx) * w + abs(dy) * h) / 2.0)
        tt = ((x - cx) * dx + (y - cy) * dy) / (2 * half) + 0.5
    tt = np.clip(tt, 0, 1).astype(np.float32)
    if p["reverse"]:
        tt = 1 - tt
    stops = p["stops"] if p["preset"] == "stops" else (GRADIENT_PRESETS[p["preset"]][1] or [(0.0, p["c0"]), (1.0, p["c1"])])
    return _u8(_ramp(stops, tt)), np.full(a.shape, 255, np.uint8)


@effect("fill_pattern", FILL_GROUP, "الگو", [S("pattern", "الگو", [("stripes", "راه‌راه"), ("dots", "نقطه‌چین"), ("grid", "شطرنجی"), ("checker", "مربع‌مربع"), ("diamonds", "لوزی"), ("waves", "موجی")], "dots"),
                                              R("scale", "اندازه", 4, 200, 28, 1, "px"), R("angle", "زاویه", 0, 180, 0, 1, "°"), C("fg", "رنگِ الگو", "#ffffff"), C("bg", "رنگِ زمینه", "#1e293b"),
                                              B("transparent_bg", "زمینهٔ شفاف", False)], note=FILL_NOTE)
def _fill_pattern(rgb, a, p):
    h, w = a.shape
    x, y = _grid(h, w)
    s = max(3.0, _scale(rgb.shape, p["scale"]))
    th = math.radians(p["angle"])
    u = (x * math.cos(th) + y * math.sin(th)) / s
    v = (-x * math.sin(th) + y * math.cos(th)) / s
    fu, fv = u % 1.0, v % 1.0
    if p["pattern"] == "stripes":
        m = (fu < 0.5)
    elif p["pattern"] == "dots":
        m = np.hypot(fu - 0.5, fv - 0.5) < 0.3
    elif p["pattern"] == "grid":
        m = (fu < 0.1) | (fv < 0.1)
    elif p["pattern"] == "checker":
        m = ((np.floor(u) + np.floor(v)) % 2) == 0
    elif p["pattern"] == "diamonds":
        m = (np.abs(fu - 0.5) + np.abs(fv - 0.5)) < 0.4
    else:
        m = np.abs(fv - 0.5 - 0.25 * np.sin(2 * math.pi * fu)) < 0.12
    fg, bg = np.array(_hex(p["fg"]), np.float32), np.array(_hex(p["bg"], (30, 41, 59)), np.float32)
    out = np.where(m[..., None], fg, bg)
    al = np.where(m, 255, 0 if p["transparent_bg"] else 255).astype(np.uint8)
    return _u8(out), al


# ───────────────────────────── حذفِ شیء (سبک، روی پردازنده)
@effect("remove_object", "ترمیم", "حذفِ شیء (پرکردنِ سبک)", [S("method", "روش", [("telea", "نرم و تدریجی"), ("ns", "حفظِ خط‌ها")], "telea"), R("radius", "شعاعِ همسایگی", 2, 40, 8, 1, "px")],
        needs_mask=True, note="ناحیه‌ای را انتخاب کنید؛ برای لکه و خطِ نازک عالی است. برای حذفِ شیءِ بزرگ «پرکردنِ هوشمند» (سرورِ پردازش) بهتر است.")
def _inpaint(rgb, a, p, mask=None):
    if mask is None or not (mask > 127).any():
        raise EffectError("اول ناحیهٔ مورد نظر را انتخاب کنید.")
    m = cv2.dilate((mask > 127).astype(np.uint8) * 255, np.ones((3, 3), np.uint8), iterations=1)
    h, w = rgb.shape[:2]
    k = min(1.0, 1600.0 / max(h, w))
    src = cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    mm = cv2.resize(m, (src.shape[1], src.shape[0]), interpolation=cv2.INTER_NEAREST) if k < 1 else m
    out = cv2.inpaint(src, mm, max(2, int(p["radius"])), cv2.INPAINT_TELEA if p["method"] == "telea" else cv2.INPAINT_NS)
    return (cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC) if k < 1 else out), None


# ───────────────────────────── اندازه، بوم و برش (عکسِ تازه در کتابخانه)
def _to_img(rgb, alpha):
    im = Image.fromarray(rgb, "RGB").convert("RGBA")
    if alpha is not None:
        im.putalpha(Image.fromarray(alpha, "L"))
    return im


RES = [("lanczos", "باکیفیت (لانچوش)"), ("bicubic", "دوتایی (نرم)"), ("bilinear", "خطی"), ("nearest", "نزدیک‌ترین (پیکسلی)")]
_RES = {"lanczos": Image.Resampling.LANCZOS, "bicubic": Image.Resampling.BICUBIC, "bilinear": Image.Resampling.BILINEAR, "nearest": Image.Resampling.NEAREST}
ANCHORS = [("tl", "بالا چپ"), ("tc", "بالا وسط"), ("tr", "بالا راست"), ("ml", "وسط چپ"), ("mc", "وسط"), ("mr", "وسط راست"), ("bl", "پایین چپ"), ("bc", "پایین وسط"), ("br", "پایین راست")]


@effect("image_size", "اندازه و بوم", "اندازهٔ تصویر", [R("width", "پهنا", 16, 4096, 1080, 1, "px"), R("height", "ارتفاع", 16, 4096, 1080, 1, "px"), B("keep", "حفظِ نسبت (ارتفاع از پهنا)", True), S("resample", "روشِ بازنمونه‌گیری", RES, "lanczos")], kind="photo")
def _imgsize(img: Image.Image, p):
    w, h = int(p["width"]), int(p["height"])
    if p["keep"]:
        h = max(1, round(img.height * w / img.width))
    if max(w, h) > MAX_SIDE:
        raise EffectError(f"بزرگ‌ترین ضلع باید حداکثر {MAX_SIDE} پیکسل باشد.")
    return img.resize((w, h), _RES.get(p["resample"], Image.Resampling.LANCZOS))


@effect("canvas_size", "اندازه و بوم", "اندازهٔ بوم", [R("width", "پهنای بوم", 16, 4096, 1200, 1, "px"), R("height", "ارتفاع بوم", 16, 4096, 1200, 1, "px"), S("anchor", "لنگر (جای عکس)", ANCHORS, "mc"),
                                                    C("fill", "رنگِ زمینهٔ تازه", "#ffffff"), B("transparent", "شفاف", False)], kind="photo")
def _canvas(img: Image.Image, p):
    w, h = int(p["width"]), int(p["height"])
    if max(w, h) > MAX_SIDE:
        raise EffectError(f"بزرگ‌ترین ضلع باید حداکثر {MAX_SIDE} پیکسل باشد.")
    fill = (0, 0, 0, 0) if p["transparent"] else (*_hex(p["fill"]), 255)
    out = Image.new("RGBA", (w, h), fill)
    ax, ay = p["anchor"][1], p["anchor"][0]
    x = {"l": 0, "c": (w - img.width) // 2, "r": w - img.width}[ax] if ax in "lcr" else (w - img.width) // 2
    y = {"t": 0, "m": (h - img.height) // 2, "b": h - img.height}[ay]
    out.alpha_composite(img.convert("RGBA"), (x, y)) if (x >= 0 and y >= 0) else out.paste(img.convert("RGBA"), (x, y))
    return out


@effect("trim", "اندازه و بوم", "پاک‌کردنِ حاشیهٔ هم‌رنگ (Trim)", [S("basis", "بر اساسِ", [("alpha", "بخش‌های شفاف"), ("tl", "رنگِ گوشهٔ بالا چپ"), ("br", "رنگِ گوشهٔ پایین راست")], "tl"), R("tol", "تحمل", 0, 100, 12, 1)], kind="photo")
def _trim(img: Image.Image, p):
    a = np.asarray(img.convert("RGBA"))
    if p["basis"] == "alpha":
        m = a[..., 3] > 8
    else:
        ref = a[0, 0, :3] if p["basis"] == "tl" else a[-1, -1, :3]
        m = np.abs(a[..., :3].astype(int) - ref.astype(int)).max(axis=2) > p["tol"] * 2.55
    ys, xs = np.where(m)
    if len(xs) == 0:
        raise EffectError("چیزی برای نگه‌داشتن پیدا نشد؛ تحمل را کمتر کنید.")
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


@effect("rotate_free", "اندازه و بوم", "چرخشِ دلخواهِ بوم", [R("angle", "زاویه (درجه، ساعتگرد)", -180, 180, 15, 0.5, "°"), B("expand", "بزرگ‌کردنِ بوم تا چیزی بریده نشود", True), C("fill", "زمینه", "#ffffff"), B("transparent", "شفاف", True)], kind="photo")
def _rotfree(img: Image.Image, p):
    fill = (0, 0, 0, 0) if p["transparent"] else (*_hex(p["fill"]), 255)
    return img.convert("RGBA").rotate(-p["angle"], resample=Image.Resampling.BICUBIC, expand=bool(p["expand"]), fillcolor=fill)


def _carve(rgb: np.ndarray, n: int, protect: np.ndarray | None) -> np.ndarray:
    """n درزِ عمودی را بردار (seam carving)."""
    img = rgb.astype(np.float32)
    for _ in range(n):
        g = _lum(img)
        e = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) + np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
        if protect is not None:
            e = e + protect[:, : e.shape[1]] * 1e4
        h, w = e.shape
        dp = e.copy()
        back = np.zeros((h, w), np.int8)
        for y in range(1, h):
            left = np.concatenate([[np.inf], dp[y - 1, :-1]])
            right = np.concatenate([dp[y - 1, 1:], [np.inf]])
            stack = np.stack([left, dp[y - 1], right])
            k = stack.argmin(axis=0)
            dp[y] += stack[k, np.arange(w)]
            back[y] = k - 1
        x = int(dp[-1].argmin())
        keep = np.ones((h, w), bool)
        for y in range(h - 1, -1, -1):
            keep[y, x] = False
            x = min(max(x + int(back[y, x]), 0), w - 1)
        img = img[keep].reshape(h, w - 1, 3)
        if protect is not None:
            protect = protect[:, :w][keep].reshape(h, w - 1)
    return _u8(img)


@effect("content_aware_scale", "اندازه و بوم", "مقیاسِ آگاه از محتوا", [R("width_pct", "پهنای تازه", 40, 100, 75, 1, "%"), R("height_pct", "ارتفاعِ تازه", 40, 100, 100, 1, "%")], kind="photo",
        note="با برداشتنِ «خط‌های کم‌اهمیت» عکس را باریک می‌کند و سوژه را له نمی‌کند. برای کم‌کردنِ حداکثر ۶۰٪ و روی عکسِ حداکثر ۹۰۰ پیکسل (بزرگ‌تر کوچک می‌شود).")
def _cas(img: Image.Image, p):
    im = img.convert("RGB")
    k = min(1.0, 900.0 / max(im.size))
    if k < 1:
        im = im.resize((max(8, int(im.width * k)), max(8, int(im.height * k))), Image.Resampling.LANCZOS)
    rgb = np.asarray(im)
    nx = int(round(rgb.shape[1] * (100 - p["width_pct"]) / 100.0))
    ny = int(round(rgb.shape[0] * (100 - p["height_pct"]) / 100.0))
    if nx > 0:
        rgb = _carve(rgb, nx, None)
    if ny > 0:
        rgb = np.ascontiguousarray(np.transpose(_carve(np.ascontiguousarray(np.transpose(rgb, (1, 0, 2))), ny, None), (1, 0, 2)))
    return Image.fromarray(rgb, "RGB").convert("RGBA")


# ───────────────────────────── اجرا
def _clean_params(e: Effect, raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for sp in e.params:
        k, v = sp["key"], raw.get(sp["key"], sp["default"])
        t = sp["type"]
        if t == "range":
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = sp["default"]
            v = min(sp["max"], max(sp["min"], v))
            if sp["step"] >= 1 and float(sp["step"]).is_integer():
                v = int(round(v))
        elif t == "select":
            v = v if v in {o[0] for o in sp["options"]} else sp["default"]
        elif t == "bool":
            v = bool(v) if isinstance(v, (bool, int)) else bool(sp["default"])
        elif t == "color":
            v = v if isinstance(v, str) and len(v) in (4, 7) and v.startswith("#") else sp["default"]
        elif t == "stops":
            v = clean_stops(v, sp["default"])
        out[k] = v
    return out


# ───────────────────────────── دورِ ۸: رنگِ انتخابی (CMYK)، تُن HDR، نقطه‌نقطه، پوستری با خطِ لبه، ساتن، نورپردازیِ چندتایی

SEL_RANGES = [("reds", "قرمزها"), ("yellows", "زردها"), ("greens", "سبزها"), ("cyans", "فیروزه‌ای‌ها"), ("blues", "آبی‌ها"), ("magentas", "سرخابی‌ها"),
              ("whites", "سفیدها"), ("neutrals", "خاکستری‌ها (میانه‌ها)"), ("blacks", "سیاه‌ها")]
_SEL_HUE = {"reds": 0.0, "yellows": 60.0, "greens": 120.0, "cyans": 180.0, "blues": 240.0, "magentas": 300.0}


def _selective_weight(f, rng):
    """وزنِ ۰..۱ هر پیکسل برای محدودهٔ رنگ (نرم؛ فامِ نزدیک و اشباعِ کافی)."""
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    if rng in _SEL_HUE:
        r, g, b = f[..., 0], f[..., 1], f[..., 2]
        d = np.maximum(mx - mn, 1e-6)
        hue = np.where(mx == r, ((g - b) / d) % 6.0, np.where(mx == g, (b - r) / d + 2.0, (r - g) / d + 4.0)) * 60.0
        dist = np.abs((hue - _SEL_HUE[rng] + 180.0) % 360.0 - 180.0)
        return np.clip(1.0 - dist / 60.0, 0, 1) * np.clip(sat * 3.0, 0, 1) * np.clip(mx * 4.0, 0, 1)
    if rng == "whites":
        return np.clip((mn - 0.65) / 0.35, 0, 1)
    if rng == "blacks":
        return np.clip((0.32 - mx) / 0.32, 0, 1)
    return np.clip(1.0 - sat * 4.0, 0, 1) * np.clip(1.0 - np.abs(mx - 0.5) * 2.2, 0, 1)


@effect("selective_color", "رنگ", "رنگِ انتخابی (سیان، سرخابی، زرد، مشکی)",
        [S("range", "محدودهٔ رنگ", SEL_RANGES, "reds"), R("cyan", "سیان", -100, 100, 35, 1, "%"), R("magenta", "سرخابی", -100, 100, -20, 1, "%"),
         R("yellow", "زرد", -100, 100, 20, 1, "%"), R("black", "مشکی", -100, 100, 0, 1, "%"), B("relative", "نسبی (به‌جای مطلق)", False)],
        note="مثلِ «رنگ انتخابی» در نرم‌افزارهای چاپ: سهمِ جوهرهای سیان/سرخابی/زرد/مشکیِ یک محدودهٔ رنگ را کم و زیاد می‌کند؛ برای چند محدوده چند بار اعمال کنید.")
def _selective_color(rgb, a, p):
    f = _f(rgb) / 255.0
    k = 1.0 - f.max(axis=2)
    d = np.maximum(1.0 - k, 1e-6)
    ch = [(1.0 - f[..., i] - k) / d for i in range(3)] + [k]
    w = _selective_weight(f, p["range"])
    for i, key in enumerate(("cyan", "magenta", "yellow", "black")):
        adj = p[key] / 100.0
        if adj:
            ch[i] = ch[i] + (ch[i] * adj if p["relative"] else adj) * w
        ch[i] = np.clip(ch[i], 0, 1)
    out = np.stack([(1 - ch[0]) * (1 - ch[3]), (1 - ch[1]) * (1 - ch[3]), (1 - ch[2]) * (1 - ch[3])], axis=2)
    return _u8(out * 255.0 + 0.5), None


@effect("hdr_toning", "رنگ", "تُن HDR (جزئیاتِ سایه و روشن)",
        [R("radius", "اندازهٔ ناحیه‌ها", 5, 100, 30, 1, "px"), R("compress", "فشردنِ روشنایی", 0, 100, 55, 1, "%"), R("detail", "جزئیات", 0, 300, 150, 1, "%"),
         R("saturation", "اشباع", 0, 200, 110, 1, "%")],
        note="روشنایی به دو بخشِ «کلی» و «جزئیات» شکسته می‌شود؛ بخشِ کلی فشرده و جزئیات تقویت می‌شود تا سایه‌ها و آسمان هم‌زمان خوانا شوند.")
def _hdr_toning(rgb, a, p):
    f = _f(rgb) / 255.0 + 1e-3
    L = _lum(f)
    logL = np.log(L).astype(np.float32)
    h, w = logL.shape
    k = min(1.0, 700.0 / max(h, w))
    small = cv2.resize(logL, (max(2, int(w * k)), max(2, int(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else logL
    sp = max(2.0, _scale(rgb.shape, p["radius"]) * k)
    base_s = cv2.bilateralFilter(small, 0, 0.35, sp)
    base = cv2.resize(base_s, (w, h), interpolation=cv2.INTER_LINEAR) if k < 1 else base_s
    detail = logL - base
    comp = p["compress"] / 100.0 * 0.85
    newlog = base * (1.0 - comp) + detail * (p["detail"] / 100.0)
    newL = np.exp(newlog - float(np.percentile(newlog, 99.5)))
    out = f * (newL / L)[..., None]
    gray = _lum(out)[..., None]
    out = gray + (out - gray) * (p["saturation"] / 100.0)
    return _u8(np.clip(out, 0, 1) * 255.0 + 0.5), None


@effect("pointillize", "سبک‌سازی", "نقطه‌نقطه", [R("size", "اندازهٔ نقطه", 4, 100, 18, 1, "px"), S("bg", "زمینه", [("white", "سفید"), ("black", "سیاه"), ("blur", "همرنگِ تصویر (محو)")], "white"),
                                              R("seed", "دانه", 0, 999, 3, 1)])
def _pointillize(rgb, a, p):
    h, w = rgb.shape[:2]
    s = max(4, int(round(_scale(rgb.shape, p["size"]))))
    rng = np.random.default_rng(int(p["seed"]))
    blurred = cv2.GaussianBlur(rgb, (0, 0), s / 3.0)
    if p["bg"] == "white":
        canvas = np.full_like(rgb, 255)
    elif p["bg"] == "black":
        canvas = np.zeros_like(rgb)
    else:
        canvas = cv2.GaussianBlur(rgb, (0, 0), s)
    gy, gx = np.mgrid[0:h:s, 0:w:s]
    if gy.size > 250_000:
        raise EffectError("نقطه‌ها خیلی ریز و زیاد می‌شود؛ اندازهٔ نقطه را بزرگ‌تر کنید.")
    py = np.clip(gy + rng.integers(0, s, gy.shape), 0, h - 1).ravel()
    px = np.clip(gx + rng.integers(0, s, gx.shape), 0, w - 1).ravel()
    order = rng.permutation(len(py))
    rad = max(2, int(round(s * 0.62)))
    cols = blurred[py, px]
    for i in order:
        cv2.circle(canvas, (int(px[i]), int(py[i])), rad, tuple(int(v) for v in cols[i]), -1, cv2.LINE_AA)
    return canvas, None


@effect("poster_edges", "سبک‌سازی", "پوستری با خطِ لبه", [R("levels", "تعدادِ سطح‌ها", 2, 10, 4, 1), R("edge", "شدتِ خطِ لبه", 0, 100, 60, 1, "%"), R("width", "ضخامتِ خط", 1, 6, 2, 1, "px")],
        note="رنگ‌ها به چند سطحِ ثابت تقسیم می‌شود و روی لبه‌ها خطِ تیره می‌افتد؛ حالتِ کارتونیِ سریع.")
def _poster_edges(rgb, a, p):
    lv = int(p["levels"])
    step = 255.0 / max(1, lv - 1)
    post = np.round(_f(rgb) / step) * step
    g = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (0, 0), 1.2).astype(np.float32)
    mag = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    th = max(1.0, float(np.percentile(mag, 88)))
    edge = np.clip((mag - th * 0.5) / (th * 0.5), 0, 1)
    wpx = max(1, int(round(_scale(rgb.shape, p["width"]))))
    if wpx > 1:
        edge = cv2.dilate(edge, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (wpx, wpx)))
    out = post * (1.0 - edge[..., None] * (p["edge"] / 100.0))
    return _u8(out), None


@effect("satin", STYLE_GROUP, "ساتن", [C("color", "رنگ", "#000000"), R("opacity", "شدت", 0, 100, 50, 1, "%"), R("distance", "فاصله", 0, 80, 11, 1, "px"), R("size", "نرمی", 0, 80, 14, 1, "px"),
                                       R("angle", "زاویه", 0, 360, 19, 1, "°"), B("invert", "معکوس", False)], note=STYLE_NOTE)
def _satin(rgb, a, p):
    A = _a01(a)
    d, bl = _scale(rgb.shape, p["distance"]), _scale(rgb.shape, p["size"])
    th = math.radians(p["angle"])
    dx, dy = d * math.cos(th), -d * math.sin(th)
    m1 = np.float32([[1, 0, dx], [0, 1, dy]])
    m2 = np.float32([[1, 0, -dx], [0, 1, -dy]])
    size = (A.shape[1], A.shape[0])
    a1 = cv2.warpAffine(A, m1, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a2 = cv2.warpAffine(A, m2, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    s = np.abs(a1 - a2)
    if bl > 0.3:
        s = cv2.GaussianBlur(s, (0, 0), bl / 2.0)
    if p["invert"]:
        s = 1.0 - s
    s = np.clip(s * (p["opacity"] / 100.0), 0, 1) * A
    col = np.array(_hex(p["color"], (0, 0, 0)), np.float32)
    return _u8(_f(rgb) * (1 - s[..., None]) + col * s[..., None]), None


def _light_params():
    out = []
    defaults = [(25, 25, 80, "#ffffff"), (82, 30, 45, "#ffd9a0"), (50, 88, 0, "#a0c8ff")]
    for i, (lx, ly, pw, col) in enumerate(defaults, 1):
        out += [R(f"x{i}", f"نورِ {i}: جای افقی", 0, 100, lx, 1, "%"), R(f"y{i}", f"نورِ {i}: جای عمودی", 0, 100, ly, 1, "%"),
                R(f"power{i}", f"نورِ {i}: شدت", 0, 100, pw, 1, "%"), C(f"color{i}", f"نورِ {i}: رنگ", col)]
    return out


@effect("lighting_multi", "رندر", "نورپردازیِ چندتایی (تا سه نور + برجستگی)",
        [R("ambient", "نورِ محیط", 0, 100, 40, 1, "%"), R("radius", "گسترشِ نورها", 10, 150, 60, 1, "%"), R("relief", "برجستگیِ بافت", 0, 100, 30, 1, "%")] + _light_params(),
        note="تا سه نورِ رنگی با نقطهٔ دلخواه؛ «برجستگی» روشناییِ خودِ عکس را مثلِ بافتِ برجسته می‌خواند تا نور روی آن سایه‌روشن بسازد.")
def _lighting_multi(rgb, a, p):
    h, w = rgb.shape[:2]
    x, y = _grid(h, w)
    big = float(max(h, w))
    f = _f(rgb) / 255.0
    height = cv2.GaussianBlur(_lum(f), (0, 0), max(1.0, big / 400.0))
    k = max(0.0, p["relief"] / 100.0) * 6.0
    nx, ny = -cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3) * k, -cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3) * k
    nz = np.ones_like(nx)
    nl = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / nl, ny / nl, nz / nl
    lit = np.full((h, w, 3), p["ambient"] / 100.0, np.float32)
    rad = max(1.0, p["radius"] / 100.0 * big)
    for i in (1, 2, 3):
        power = p[f"power{i}"] / 100.0
        if power <= 0:
            continue
        lx, ly = p[f"x{i}"] / 100.0 * w, p[f"y{i}"] / 100.0 * h
        dxv, dyv = lx - x, ly - y
        dist = np.sqrt(dxv * dxv + dyv * dyv)
        fall = np.clip(1.0 - dist / rad, 0, 1) ** 2
        lz = rad * 0.35
        ln = np.sqrt(dxv * dxv + dyv * dyv + lz * lz)
        dot = (nx * dxv + ny * dyv + nz * lz) / ln
        term = np.clip(1.0 + (p["relief"] / 100.0) * (2.0 * dot - 1.0), 0, 2)
        col = np.array(_hex(p[f"color{i}"]), np.float32) / 255.0
        lit += (fall * power * 1.6 * term)[..., None] * col
    return _u8(f * lit * 255.0 + 0.5), None


def catalog() -> list[dict]:
    return [{"id": e.id, "group": e.group, "title": e.title, "kind": e.kind, "blend": e.blend, "needs_mask": e.needs_mask, "note": e.note, "params": e.params} for e in REGISTRY.values()]


def run(effect_id: str, img: Image.Image, params: dict | None, mask: Image.Image | None = None) -> tuple[Image.Image, Effect]:
    """تصویرِ RGBA ⇒ تصویرِ RGBA. افکتِ لایه‌ای با ماسک ترکیب می‌شود؛ افکتِ عکسی (اندازه/بوم) ماسک نمی‌گیرد."""
    e = REGISTRY.get(effect_id)
    if e is None:
        raise EffectError("این فیلتر شناخته نشد.")
    if max(img.size) > MAX_SIDE or min(img.size) < 4:
        raise EffectError(f"اندازهٔ عکس باید بین ۴ و {MAX_SIDE} پیکسل باشد.")
    p = _clean_params(e, params)
    if e.kind == "photo":
        return e.fn(img.convert("RGBA"), p), e
    rgba = np.asarray(img.convert("RGBA"))
    rgb, alpha = np.ascontiguousarray(rgba[..., :3]), np.ascontiguousarray(rgba[..., 3])
    m_arr = None
    if mask is not None:
        m_arr = np.asarray(mask.convert("L").resize(img.size, Image.Resampling.BILINEAR))
    if e.needs_mask:
        out_rgb, out_a = e.fn(rgb, alpha, p, m_arr)
    else:
        out_rgb, out_a = e.fn(rgb, alpha, p)
    out_a = alpha if out_a is None else out_a
    if m_arr is not None:
        w = (m_arr.astype(np.float32) / 255.0)[..., None]
        out_rgb = _u8(rgb.astype(np.float32) * (1 - w) + out_rgb.astype(np.float32) * w)
        out_a = _u8(alpha.astype(np.float32) * (1 - w[..., 0]) + out_a.astype(np.float32) * w[..., 0])
    res = np.dstack([out_rgb, out_a])
    return Image.fromarray(res, "RGBA"), e
