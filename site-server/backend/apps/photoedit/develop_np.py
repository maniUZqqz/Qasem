"""«ظهور» (develop) روی سرورِ سایت: پورتِ numpy/cv2 ِ موتورِ عکسِ کیت (PersianAiKit.Photo ⇐ Engine/*.cs).

هر مرحله با همان فرمول‌ها و همان ترتیبِ ``PhotoEngine.Render`` است ⇒ وقتی سرورِ پردازش خاموش است، یا وقتی لغزنده‌ها
فقط روی یک لایهٔ تنظیم / ناحیهٔ ماسک‌شده می‌نشینند، همان نتیجهٔ کیت (تا حدِ تقریب‌های زیر) روی خودِ سرورِ سایت ساخته می‌شود.

ترتیب: ترمیمِ لکه ⇒ تعادلِ سفیدی و نوردهی (خطی، گامای ۲٫۲، شانهٔ نرم) ⇒ مه‌زدایی ⇒ روشنی‌ها/سایه‌ها (پایهٔ لبه‌آگاه) ⇒
منحنی‌ها (سطوح، سیاه/سفید، کنتراست، روشنیِ میانه، RGB و هر کانال) ⇒ بافت/وضوح ⇒ رنگ (وایبرنس، اشباع، HSL، رنگ‌دهی) ⇒
نویزگیری و شارپ ⇒ اعوجاج و تاریکیِ لنز ⇒ وینیت ⇒ دانه ⇒ بریدن به ۰..۱.

ورودی/خروجی: ``float32`` به شکلِ H×W×3 با ترتیبِ **RGB** و بازهٔ ۰..۱ (کیت BGR است؛ این‌جا همه‌چیز RGB).

تفاوت‌ها با کیت (تقریب‌ها):

* ``Decode`` ِ گاما را کیت با جدولِ ۴۰۹۶تایی درون‌یابی می‌کند؛ این‌جا ``np.power`` ِ دقیق.
* نویزگیریِ روشنایی: همان ``fastNlMeansDenoising`` (h=۲+۱۶·مقدار، پنجرهٔ ۷/۲۱)؛ برای عکسِ بیش از ۶ مگاپیکسل (سرورِ سایت
  ۲ هسته است) پنجره‌ها ۳/۷ می‌شوند؛ بافتِ کلارتی با گاوسیِ کوچک‌شده.
* دانه: کیت با ``System.Random(1405)`` دانه می‌سازد؛ این‌جا ``numpy`` با بذرِ ثابتِ ۱۴۰۵ ⇒ دانه ثابت است ولی بایت‌به‌بایت همان نیست.
* ترمیمِ لکه: ``cv2.inpaint`` (Telea) روی ناحیهٔ کوچکِ دورِ لکه‌ها (برای سرعت)، مثلِ ``Retouch.Heal``.

همه‌جا ``float32``؛ کارهای نقطه‌ای نوار‌به‌نوار (حافظهٔ سرور ۳ گیگ است).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import catalog

WR, WG, WB = 0.2126, 0.7152, 0.0722
LUT_SIZE = 4096
STRIP_PIXELS = 1_500_000
BANDS = ("red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta")
CENTERS = np.array([0, 30, 60, 120, 180, 240, 270, 300, 360], dtype=np.float32)

cv2.setNumThreads(2)
_LUMA_M = np.array([[WR, WG, WB]], dtype=np.float32)


# ───────────────────────────── ابزارهای پایه

def _strips(h: int, w: int):
    step = max(1, STRIP_PIXELS // max(1, w))
    for y0 in range(0, h, step):
        yield slice(y0, min(h, y0 + step))


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = (x - np.float32(e0)) * np.float32(1.0 / (e1 - e0))
    np.clip(t, 0.0, 1.0, out=t)
    return t * t * (np.float32(3.0) - np.float32(2.0) * t)


def _luma(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    return np.ascontiguousarray(cv2.transform(img, _LUMA_M).reshape(h, w), dtype=np.float32)


def _apply_luma_ratio(img: np.ndarray, y_old: np.ndarray, y_new: np.ndarray) -> None:
    h, w = y_old.shape
    for sl in _strips(h, w):
        y0 = y_old[sl]
        y1 = y_new[sl]
        k = y1 / np.maximum(y0, np.float32(1e-4))
        low = y0 <= 1e-4
        blk = img[sl]
        if low.any():                     # سیاهِ مطلق: ضرب بی‌معناست ⇒ مثلِ کیت جمع
            d = y1 - y0
            k[low] = 1.0
            blk *= k[..., None]
            blk[low] += d[low][:, None]
        else:
            blk *= k[..., None]


def _box(src: np.ndarray, r: int) -> np.ndarray:
    return cv2.boxFilter(src, -1, (2 * r + 1, 2 * r + 1), normalize=True, borderType=cv2.BORDER_REFLECT)


def guided(I: np.ndarray, p: np.ndarray, radius: float, eps: float, work_side: int = 640) -> np.ndarray:
    """Px.Guided: فیلترِ هدایت‌شدهٔ سریع (He و همکاران) با کوچک‌کردنِ کار تا work_side."""
    h, w = I.shape
    k = min(1.0, work_side / float(max(w, h)))
    small = k < 1
    Il, pl = I, p
    if small:
        sz = (max(1, int(w * k)), max(1, int(h * k)))
        Il = cv2.resize(I, sz, interpolation=cv2.INTER_AREA)
        pl = cv2.resize(p, sz, interpolation=cv2.INTER_AREA)
    r = max(1, int(round(radius * k)))
    mean_i = _box(Il, r)
    mean_p = _box(pl, r)
    corr_i = _box(Il * Il, r)
    corr_ip = _box(Il * pl, r)
    var_i = corr_i - mean_i * mean_i
    cov_ip = corr_ip - mean_i * mean_p
    a = cov_ip / (var_i + np.float32(eps))
    b = mean_p - a * mean_i
    mean_a = _box(a, r)
    mean_b = _box(b, r)
    if small:
        mean_a = cv2.resize(mean_a, (w, h), interpolation=cv2.INTER_LINEAR)
        mean_b = cv2.resize(mean_b, (w, h), interpolation=cv2.INTER_LINEAR)
    return (mean_a * I + mean_b).astype(np.float32)


def _gaussian(src: np.ndarray, sigma: float) -> np.ndarray:
    s = max(0.3, float(sigma))
    return cv2.GaussianBlur(src, (0, 0), s, sigmaY=s, borderType=cv2.BORDER_REFLECT)


def _gaussian_wide(src: np.ndarray, sigma: float) -> np.ndarray:
    """گاوسیِ پهن (σ ≥ ۶): پایین‌گذر است ⇒ روی نسخهٔ کوچک‌شده حساب و بزرگ می‌شود (۸ برابر سریع‌تر؛ تفاوت زیرِ ۰٫۰۰۲)."""
    h, w = src.shape[:2]
    f = int(sigma // 3)
    if sigma < 6 or f < 2 or min(h, w) < 8 * f:
        return _gaussian(src, sigma)
    small = cv2.resize(src, (max(1, w // f), max(1, h // f)), interpolation=cv2.INTER_AREA)
    small = _gaussian(small, sigma / f)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _percentile01(y: np.ndarray, p: float) -> float:
    n = 4096
    idx = np.clip((y * (n - 1)).astype(np.int64), 0, n - 1)
    hist = np.bincount(idx.ravel(), minlength=n)
    target = p / 100.0 * y.size
    acc = np.cumsum(hist)
    i = int(np.searchsorted(acc, target, side="left"))
    return min(i, n - 1) / float(n - 1)


# ───────────────────────────── پارامترها

def _kit_defaults() -> dict:
    return catalog.kit_params()


def normalize_adjust(adjust: dict | None) -> dict[str, float]:
    """فقط کلیدهای کیت، در بازه؛ مقدارِ پیش‌فرض می‌افتد (مثلِ Recipe.Normalized)."""
    out: dict[str, float] = {}
    spec = _kit_defaults()
    for key, val in (adjust or {}).items():
        c = spec.get(key)
        if c is None:
            continue
        try:
            x = float(val)
        except (TypeError, ValueError):
            continue
        if x != x:
            continue
        x = max(c["min"], min(c["max"], x))
        if abs(x - c["default"]) > 1e-9:
            out[key] = x
    return out


class _P:
    """r.Get / r.Has روی یک دیکشنریِ لغزنده‌ها."""

    def __init__(self, adjust: dict):
        self.a = normalize_adjust(adjust)
        self.spec = _kit_defaults()

    def get(self, key: str) -> float:
        return self.a.get(key, float(self.spec[key]["default"]) if key in self.spec else 0.0)

    def has(self, key: str) -> bool:
        return abs(self.get(key) - float(self.spec[key]["default"])) > 1e-9


# ───────────────────────────── ترمیمِ لکه

def heal_spots(img: np.ndarray, spots: list[dict]) -> None:
    h, w = img.shape[:2]
    min_side = min(w, h)
    pts = []
    for s in spots or []:
        try:
            x, y, r = float(s["x"]), float(s["y"]), float(s.get("r", 0.01))
        except (KeyError, TypeError, ValueError):
            continue
        rr = max(1, int(round(r * min_side)))
        pts.append((int(round(x * (w - 1))), int(round(y * (h - 1))), rr))
    if not pts:
        return
    max_r = max(p[2] for p in pts)
    m = max(8, max_r * 4)
    x0 = max(0, min(p[0] - m for p in pts))
    y0 = max(0, min(p[1] - m for p in pts))
    x1 = min(w, max(p[0] + m for p in pts) + 1)
    y1 = min(h, max(p[1] + m for p in pts) + 1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for x, y, rr in pts:
        cv2.circle(mask, (x - x0, y - y0), rr, 255, -1, cv2.LINE_AA)
    crop = img[y0:y1, x0:x1]
    c8 = np.clip(crop * 255.0 + 0.5, 0, 255).astype(np.uint8)
    healed = cv2.inpaint(c8, mask, max(3.0, max_r * 0.25), cv2.INPAINT_TELEA)
    hf = healed.astype(np.float32) / 255.0
    sel = mask > 0
    crop[sel] = hf[sel]


# ───────────────────────────── تعادلِ سفیدی و نوردهی

def white_balance_gains(temperature: float, tint: float) -> tuple[float, float, float]:
    """(B, G, R) مثلِ Tone.WhiteBalanceGains."""
    t, ti = temperature / 100.0, tint / 100.0
    gr = math.exp(0.6 * t + 0.125 * ti)
    gb = math.exp(-0.6 * t + 0.125 * ti)
    gg = math.exp(-0.25 * ti)
    norm = 1.0 / (WR * gr + WG * gg + WB * gb)
    return gb * norm, gg * norm, gr * norm


def _wb_exposure(img: np.ndarray, temp: float, tint: float, ev: float) -> None:
    if temp == 0 and tint == 0 and ev == 0:
        return
    gb, gg, gr = white_balance_gains(temp, tint)
    e = 2.0 ** ev
    ks = np.array([gr * e, gg * e, gb * e], dtype=np.float32)          # R, G, B
    shoulder = float(ks.max()) > 1.0001
    inv = 1.0 / 2.2
    h, w = img.shape[:2]
    for sl in _strips(h, w):
        blk = img[sl]
        np.clip(blk, 0.0, 1.0, out=blk)
        cv2.pow(blk, 2.2, blk)
        blk *= ks
        cv2.pow(blk, inv, blk)
        if shoulder:
            m = blk > 0.9
            if m.any():
                v = blk[m]
                blk[m] = 0.9 + 0.1 * (1.0 - np.exp(-(v - 0.9) / 0.1))


# ───────────────────────────── مه‌زدایی

def _min_channel(small: np.ndarray, dr: float, dg: float, db: float) -> np.ndarray:
    return np.minimum(np.minimum(small[..., 0] / np.float32(dr), small[..., 1] / np.float32(dg)),
                      small[..., 2] / np.float32(db)).astype(np.float32)


def _dehaze(img: np.ndarray, amount: float) -> None:
    h, w = img.shape[:2]
    k = min(1.0, 600.0 / max(w, h))
    small = cv2.resize(img, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    patch = max(3, int(max(sw, sh) * 0.02)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch))
    dark = _min_channel(small, 1, 1, 1)
    dark_e = cv2.erode(dark, kernel)
    thr = _percentile01(dark_e, 99.9)
    sel = dark_e >= thr
    if sel.sum() == 0:
        air = (1.0, 1.0, 1.0)
    else:
        air = tuple(float(np.clip(small[..., c][sel].mean(), 0.3, 1.0)) for c in range(3))   # R, G, B
    norm = _min_channel(small, air[0], air[1], air[2])
    norm_e = cv2.erode(norm, kernel)
    t_raw = (1.0 - 0.95 * norm_e).astype(np.float32)
    gray = _luma(small)
    t_ref = guided(gray, t_raw, max(sw, sh) * 0.03, 1e-3, 10_000)
    t = cv2.resize(t_ref, (w, h), interpolation=cv2.INTER_LINEAR)
    a = amount / 100.0
    airv = np.array(air, dtype=np.float32)
    for sl in _strips(h, w):
        tt = np.maximum(t[sl], 0.1)[..., None]
        blk = img[sl]
        if a > 0:
            s = np.float32(a * 0.85)
            blk += s * ((blk - airv) / tt + airv - blk)
        else:
            s = (-a * 0.45 * (1.2 - tt)).astype(np.float32)
            blk += s * (airv - blk)


# ───────────────────────────── روشنی‌ها / سایه‌ها، بافت / وضوح

def _highlights_shadows(img: np.ndarray, highlights: float, shadows: float) -> None:
    y = _luma(img)
    dim = max(img.shape[:2])
    base = guided(y, y, dim * 0.025, 0.02)
    sh, hl = shadows / 100.0, highlights / 100.0
    np.clip(base, 0.0, 1.0, out=base)
    g = np.float32(sh * 1.3) * (np.float32(1.0) - _smoothstep(0.0, 0.6, base))
    g += np.float32(hl * 1.0) * _smoothstep(0.4, 1.0, base)
    del base
    v = np.exp2(g)
    v *= y
    over = v > 0.95
    if over.any():
        vo = v[over]
        v[over] = 0.95 + 0.05 * (1.0 - np.exp(-(vo - 0.95) / 0.05))
    _apply_luma_ratio(img, y, v)


def _texture_clarity(img: np.ndarray, texture: float, clarity: float) -> None:
    y = _luma(img)
    dim = max(img.shape[:2])
    y_new = y.copy()
    if clarity != 0:
        base = guided(y, y, dim * 0.015, 0.01)
        c = clarity / 100.0 * 1.2
        v = np.clip(y, 0.0, 1.0)
        mid = 4.0 * v * (1.0 - v)
        y_new += np.float32(c) * (y - base) * (0.35 + 0.65 * mid)
    if texture != 0:
        blur = _gaussian_wide(y, max(1.0, dim * 0.003))
        y_new += np.float32(texture / 100.0) * (y - blur)
    _apply_luma_ratio(img, y, y_new)


# ───────────────────────────── منحنی‌ها

def _spline(pts):
    """Tone.Spline: منحنیِ نرم و یکنوا (Fritsch–Carlson)؛ ورودی/خروجی ۰..۱ ⇒ تابعِ برداری."""
    p = sorted(((float(q[0]) / 255.0, float(q[1]) / 255.0) for q in pts), key=lambda t: t[0])
    n = len(p)
    xs = np.array([q[0] for q in p])
    ys = np.array([q[1] for q in p])
    if n == 1:
        return lambda x: np.full_like(x, ys[0])
    d = np.array([(ys[i + 1] - ys[i]) / max(1e-9, xs[i + 1] - xs[i]) for i in range(n - 1)])
    m = np.zeros(n)
    m[0], m[n - 1] = d[0], d[n - 2]
    for i in range(1, n - 1):
        m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2
    for i in range(n - 1):
        if d[i] == 0:
            m[i] = 0.0
            m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        hh = a * a + b * b
        if hh > 9:
            t = 3 / math.sqrt(hh)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]

    def f(x):
        x = np.asarray(x, dtype=np.float64)
        k = np.searchsorted(xs[1:n - 1], x, side="left") if n > 2 else np.zeros(x.shape, np.int64)
        k = np.clip(k, 0, n - 2)
        h = xs[k + 1] - xs[k]
        t = (x - xs[k]) / h
        t2 = t * t
        t3 = t2 * t
        v = ((2 * t3 - 3 * t2 + 1) * ys[k] + (t3 - 2 * t2 + t) * h * m[k]
             + (-2 * t3 + 3 * t2) * ys[k + 1] + (t3 - t2) * h * m[k + 1])
        v = np.where(x <= xs[0], ys[0], v)
        v = np.where(x >= xs[n - 1], ys[n - 1], v)
        return v

    return f


def build_base_lut(P: _P) -> tuple[np.ndarray, bool]:
    """Tone.BuildBase: سطوح ⇒ سفید/سیاه ⇒ کنتراست ⇒ روشنیِ میانه؛ جدولِ ۴۰۹۷تایی روی ۰..۱."""
    lb, lw, g = P.get("levelsBlack") / 255.0, P.get("levelsWhite") / 255.0, P.get("levelsGamma")
    if lw < lb + 0.02:
        lw = min(1.0, lb + 0.02)
    blacks, whites = P.get("blacks") / 100.0, P.get("whites") / 100.0
    contrast, bright = P.get("contrast") / 100.0, P.get("brightness") / 100.0
    identity = lb == 0 and lw == 1 and g == 1 and blacks == 0 and whites == 0 and contrast == 0 and bright == 0
    x = np.arange(LUT_SIZE + 1, dtype=np.float64) / LUT_SIZE
    ib, iw = -blacks * 0.12, 1 - whites * 0.12
    a = contrast * 0.45 if contrast > 0 else contrast * 0.6
    gamma = 2.0 ** (-bright * 0.8)
    x = np.power(np.clip((x - lb) / (lw - lb), 0, 1), 1 / g)
    x = np.clip((x - ib) / (iw - ib), 0, 1)
    x = x + a * 4 * (x - 0.5) * x * (1 - x)
    x = np.power(np.clip(x, 0, 1), gamma)
    return x, identity


def _lookup(lut: np.ndarray, v: np.ndarray) -> np.ndarray:
    n = len(lut) - 1
    f = np.clip(v, 0.0, 1.0) * np.float32(n)
    i = np.minimum(f.astype(np.int32), n - 1)
    t = f - i
    lut32 = lut.astype(np.float32)
    return lut32[i] + (lut32[i + 1] - lut32[i]) * t


def _curves(img: np.ndarray, P: _P, curve: dict | None) -> None:
    base, identity = build_base_lut(P)
    c = catalog.normalize_curve(curve or {})
    rgb = _spline(c["rgb"]) if c.get("rgb") else None
    if identity and rgb is None and not (c.get("red") or c.get("green") or c.get("blue")):
        return
    luts = []
    for key in ("red", "green", "blue"):                # RGB order
        v = base.copy()
        if rgb is not None:
            v = rgb(v)
        if c.get(key):
            v = _spline(c[key])(v)
        luts.append(np.clip(v, 0, 1))
    # جدولِ ۴۰۹۷تایی ⇐ ۶۵۵۳۶تایی (درون‌یابیِ خطی) برای یک بار برداشتنِ سه‌کاناله
    x_hi = np.linspace(0.0, 1.0, 65536)
    x_lo = np.linspace(0.0, 1.0, LUT_SIZE + 1)
    tabs = np.concatenate([np.interp(x_hi, x_lo, l) for l in luts]).astype(np.float32)
    off = (np.arange(3, dtype=np.int32) * 65536)
    h, w = img.shape[:2]
    for sl in _strips(h, w):
        blk = img[sl]
        idx = np.clip(blk, 0.0, 1.0)
        idx *= np.float32(65535.0)
        idx += np.float32(0.5)
        ii = idx.astype(np.int32)
        ii += off
        np.take(tabs, ii, out=blk, mode="clip")


# ───────────────────────────── رنگ

def _rgb_to_hsv(r, g, b):
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    d = mx - mn
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0).astype(np.float32)
    dd = np.maximum(d, 1e-6)
    h = np.where(mx == r, 60.0 * ((g - b) / dd), np.where(mx == g, 60.0 * ((b - r) / dd + 2.0), 60.0 * ((r - g) / dd + 4.0)))
    h = np.where(d < 1e-6, 0.0, h)
    h = np.where(h < 0, h + 360.0, h).astype(np.float32)
    return h, s, mx


def _hsv_to_rgb(h, s, v):
    h = (np.mod(np.mod(h, 360.0) + 360.0, 360.0) / 60.0).astype(np.float32)
    i = np.floor(h).astype(np.int32)
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    conds = [i == 0, i == 1, i == 2, i == 3, i == 4]
    r = np.select(conds, [v, q, p, p, t], default=v)
    g = np.select(conds, [t, v, v, q, p], default=p)
    b = np.select(conds, [p, p, t, v, v], default=q)
    return r.astype(np.float32), g.astype(np.float32), b.astype(np.float32)


def _tint_direction(hue: float) -> tuple[float, float, float]:
    r, g, b = _hsv_to_rgb(np.float32(hue % 360), np.float32(1), np.float32(1))
    l = WR * float(r) + WG * float(g) + WB * float(b)
    return float(r) - l, float(g) - l, float(b) - l


def _hue_tables(dh, ds, dl):
    """جدولِ ۳۶۰۱تایی (هر ۰٫۱ درجه) از درون‌یابیِ خطیِ ۹ مرکزِ فام (مثلِ ColorOps)."""
    hh = np.arange(3601, dtype=np.float32) / 10.0
    i = np.searchsorted(CENTERS[1:8], hh, side="right")
    t = (hh - CENTERS[i]) / (CENTERS[i + 1] - CENTERS[i])
    return tuple((a[i] * (1 - t) + a[i + 1] * t).astype(np.float32) for a in (dh, ds, dl))


_SKIN = None


def _skin_table() -> np.ndarray:
    global _SKIN
    if _SKIN is None:
        hh = np.arange(3601, dtype=np.float32) / 10.0
        _SKIN = np.where((hh > 5) & (hh < 50), 0.5 + 0.5 * np.abs(hh - 27.5) / 22.5, 1.0).astype(np.float32)
    return _SKIN


def _color_ops(img: np.ndarray, P: _P) -> None:
    dh = np.zeros(9, np.float32)
    ds = np.zeros(9, np.float32)
    dl = np.zeros(9, np.float32)
    hsl = False
    for i, b in enumerate(BANDS):
        dh[i] = P.get(b + "Hue") / 100.0 * 30.0
        ds[i] = P.get(b + "Sat") / 100.0
        dl[i] = P.get(b + "Lum") / 100.0
        hsl |= bool(dh[i] != 0 or ds[i] != 0 or dl[i] != 0)
    dh[8], ds[8], dl[8] = dh[0], ds[0], dl[0]
    vib, sat = P.get("vibrance") / 100.0, P.get("saturation") / 100.0
    sh_s, hi_s, bal = P.get("shadowsSat") / 100.0, P.get("highlightsSat") / 100.0, P.get("gradingBalance") / 100.0
    grading = sh_s > 0 or hi_s > 0
    if not hsl and vib == 0 and sat == 0 and not grading:
        return
    sh_t = _tint_direction(P.get("shadowsHue"))
    hi_t = _tint_direction(P.get("highlightsHue"))
    tab_h, tab_s, tab_l = _hue_tables(dh, ds, dl) if hsl else (None, None, None)
    skin = _skin_table()
    H, W = img.shape[:2]
    for sl in _strips(H, W):
        blk = img[sl]
        rgb = np.clip(blk, 0.0, 1.0)
        if hsl or vib != 0 or sat != 0:
            hch, s, v = cv2.split(cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV))
            if hsl:
                hi = np.minimum((hch * 10.0).astype(np.int32), 3600)
                hch = np.mod(hch + tab_h[hi], 360.0).astype(np.float32)
                s = np.clip(s * (1.0 + tab_s[hi]), 0.0, 1.0)
                v = np.clip(v * (1.0 + tab_l[hi] * 0.6 * np.minimum(1.0, s * 1.5)), 0.0, 1.0)
            if vib != 0:
                if vib > 0:
                    hi = np.minimum((hch * 10.0).astype(np.int32), 3600)
                    s = np.clip(s * (1.0 + vib * (1.0 - s) * skin[hi]), 0.0, 1.0)
                else:
                    s = np.clip(s * (1.0 + vib * (1.0 - s)), 0.0, 1.0)
            if sat > 0:
                s = np.clip(s * (1.0 + sat), 0.0, 1.0)
            rgb = cv2.cvtColor(cv2.merge([hch, s.astype(np.float32), v.astype(np.float32)]), cv2.COLOR_HSV2RGB)
            if sat < 0:
                l = _luma(rgb)[..., None]
                rgb = l + (rgb - l) * np.float32(1 + sat)
        if grading:
            l = _luma(rgb)
            ws = 1 - _smoothstep(0.0, 0.6 + 0.3 * bal, l)
            wh = _smoothstep(0.4 + 0.3 * bal, 1.0, l)
            ks = (sh_s * 0.3 * ws)[..., None]
            kh = (hi_s * 0.3 * wh)[..., None]
            rgb = rgb + ks * np.array(sh_t, np.float32) + kh * np.array(hi_t, np.float32)
        blk[...] = rgb


# ───────────────────────────── جزئیات

def _denoise(img: np.ndarray, luma: float, color: float) -> None:
    h, w = img.shape[:2]
    lab = cv2.cvtColor(np.clip(img, 0.0, 1.0), cv2.COLOR_RGB2LAB)
    L, A, B = cv2.split(lab)
    del lab
    big = h * w > 6_000_000
    if luma > 0:
        l8 = np.clip(L * 2.55 + 0.5, 0, 255).astype(np.uint8)
        d8 = cv2.fastNlMeansDenoising(l8, None, float(2 + luma * 16), 3 if big else 7, 7 if big else 21)
        del l8
        lf = d8.astype(np.float32) / 2.55
        L = L + np.clip(lf - L, -20.0, 20.0)
    if color > 0:
        guide = (L / 100.0).astype(np.float32)
        radius = max(2.0, max(w, h) * 0.004 * (1 + color * 3))
        wgt = min(1.0, color * 1.3)
        chans = []
        for ch in (A, B):
            a = (ch / 256.0).astype(np.float32)
            f = guided(guide, a, radius, 0.002 + color * 0.01) * 256.0
            chans.append((ch * (1 - wgt) + f * wgt).astype(np.float32))
        A, B = chans
    img[...] = cv2.cvtColor(cv2.merge([L.astype(np.float32), A, B]), cv2.COLOR_LAB2RGB)


def _sharpen(img: np.ndarray, amount: float, radius: float, masking: float) -> None:
    y = _luma(img)
    blur = _gaussian(y, max(0.4, radius))
    k = amount * 1.6
    if masking > 0:
        gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        m0 = masking * 0.35
        mask = _smoothstep(m0, m0 + 0.15, mag)
        y_new = y + np.float32(k) * (y - blur) * mask
    else:
        y_new = y + np.float32(k) * (y - blur)
    _apply_luma_ratio(img, y, y_new.astype(np.float32))


# ───────────────────────────── لنز و افکت

def _distortion(img: np.ndarray, distortion: float) -> None:
    h, w = img.shape[:2]
    k = -distortion / 100.0 * 0.25
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    R = math.sqrt(cx * cx + cy * cy)
    norm = 1 / (1 + k) if k > 0 else 1.0
    xs = ((np.arange(w, dtype=np.float32) - cx) / R)
    ys = ((np.arange(h, dtype=np.float32) - cy) / R)
    mx = np.empty((h, w), np.float32)
    my = np.empty((h, w), np.float32)
    for sl in _strips(h, w):
        n2 = xs[None, :] ** 2 + ys[sl, None] ** 2
        f = (1 + k * n2) * norm
        mx[sl] = cx + xs[None, :] * f * R
        my[sl] = cy + ys[sl, None] * f * R
    img[...] = cv2.remap(img, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT_101)


def _lens_vignette(img: np.ndarray, amount: float) -> None:
    h, w = img.shape[:2]
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    k = amount / 100.0 * 0.9
    nx = (np.arange(w, dtype=np.float32) - cx) / max(cx, 1e-6)
    ny = (np.arange(h, dtype=np.float32) - cy) / max(cy, 1e-6)
    for sl in _strips(h, w):
        g = 1 + k * (nx[None, :] ** 2 + ny[sl, None] ** 2) / 2
        img[sl] *= g[..., None].astype(np.float32)


def _vignette(img: np.ndarray, amount: float, mid: float, feather: float) -> None:
    h, w = img.shape[:2]
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    inner = 0.15 + mid * 0.7
    outer = inner + 0.05 + feather * 0.8
    nx = (np.arange(w, dtype=np.float32) - cx) / max(cx, 1e-6)
    ny = (np.arange(h, dtype=np.float32) - cy) / max(cy, 1e-6)
    for sl in _strips(h, w):
        d = np.sqrt((nx[None, :] ** 2 + ny[sl, None] ** 2) / 2)
        m = (_smoothstep(inner, outer, d) * abs(amount) * 0.85).astype(np.float32)[..., None]
        blk = img[sl]
        if amount < 0:
            blk *= (1 - m)
        else:
            blk += (1 - blk) * m


def _grain(img: np.ndarray, amount: float, size: float, scale: float) -> None:
    h, w = img.shape[:2]
    cell = max(1.0, (1 + size * 4) * scale)
    gw, gh = max(2, int(w / cell)), max(2, int(h / cell))
    rng = np.random.default_rng(1405)
    noise = rng.standard_normal((gh, gw)).astype(np.float32)
    big = cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)
    k = amount * 0.09
    for sl in _strips(h, w):
        blk = img[sl]
        l = np.clip(_luma(blk), 0.0, 1.0)
        d = big[sl] * np.float32(k) * (0.4 + 2.4 * l * (1 - l))
        blk += d[..., None]


# ───────────────────────────── ورودی

def is_neutral(adjust: dict | None, curve: dict | None = None, spots: list | None = None) -> bool:
    return not normalize_adjust(adjust) and not catalog.normalize_curve(curve or {}) and not spots


def develop(rgb: np.ndarray, adjust: dict | None, curve: dict | None = None, spots: list | None = None,
            scale: float = 1.0, inplace: bool = False) -> np.ndarray:
    """PhotoEngine.Render: rgb ⇐ float32 H×W×3 (RGB، ۰..۱) ⇒ نتیجه (نسخهٔ تازه؛ با inplace=True همان آرایه)."""
    img = rgb if (inplace and rgb.dtype == np.float32 and rgb.flags.c_contiguous) else np.array(rgb, dtype=np.float32, order="C")
    P = _P(adjust or {})
    if spots:
        heal_spots(img, spots)
    if P.has("temperature") or P.has("tint") or P.has("exposure"):
        _wb_exposure(img, P.get("temperature"), P.get("tint"), P.get("exposure"))
    if P.has("dehaze"):
        _dehaze(img, P.get("dehaze"))
    if P.has("highlights") or P.has("shadows"):
        _highlights_shadows(img, P.get("highlights"), P.get("shadows"))
    _curves(img, P, curve)
    if P.has("texture") or P.has("clarity"):
        _texture_clarity(img, P.get("texture"), P.get("clarity"))
    _color_ops(img, P)
    nr_l, nr_c = P.get("noiseLuma") / 100.0, P.get("noiseColor") / 100.0
    if nr_l > 0 or nr_c > 0:
        _denoise(img, nr_l, nr_c)
    amount = P.get("sharpen") / 100.0
    if amount > 0:
        _sharpen(img, amount, P.get("sharpenRadius") * scale, P.get("sharpenMasking") / 100.0)
    dist = P.get("distortion")
    if dist != 0:
        _distortion(img, dist)
    if P.get("lensVignette") > 0:
        _lens_vignette(img, P.get("lensVignette"))
    v = P.get("vignette")
    if v != 0:
        _vignette(img, v / 100.0, P.get("vignetteMidpoint") / 100.0, P.get("vignetteFeather") / 100.0)
    g = P.get("grain")
    if g > 0:
        _grain(img, g / 100.0, P.get("grainSize") / 100.0, scale)
    np.clip(img, 0.0, 1.0, out=img)
    return img
