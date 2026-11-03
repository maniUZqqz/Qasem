"""Lumetri-style colour for one clip: parameters → ffmpeg filters, and the exact maths so a browser can mirror them.

The panel shows sliders (exposure, contrast, highlights, shadows, whites, blacks, temperature, tint, saturation,
vibrance), three colour wheels, RGB/master curves, six HSL ranges and ~15 looks. The server turns the same numbers into
a short ffmpeg chain; the browser preview (TypeScript) must produce the same picture, so everything that can be a
per-channel curve IS a per-channel curve, sampled at 9 fixed points and interpolated with PCHIP — the same
interpolation ffmpeg's `curves=interp=pchip` uses. Nothing here guesses at a path or a shell: it returns strings.

Parameters (`clean` clamps and fills every key; unknown keys are dropped)
-------------------------------------------------------------------------
exposure -3..3 (stops) · contrast, highlights, shadows, whites, blacks, temperature, tint, vibrance -100..100 (0) ·
saturation 0..200 (100) · sharpen, denoise, vignette, grain, blur 0..100 (0) ·
wheels {shadows, mids, highs: [r, g, b]} each -1..1 · curves {m, r, g, b: [[x, y], ...]} (x ascending, 0..1, ends at
x=0 and x=1 are added when missing, ≤ 8 points) · hsl {red|yellow|green|cyan|blue|magenta: {h -180..180, s -100..100,
l -100..100}} · look (key of LOOKS or "") · look_amount 0..100 (100).

A look is just a parameter dict. With amount a = look_amount/100 the *effective* parameters are
    slider  = clamp(user + a * look)          (saturation: user + a * (look - 100))
    wheels  = clamp(user + a * look, -1, 1)   hsl = clamp(user + a * look)
and the look's own curves are blended at the END of the tone chain (step 7 below). Use `effective()` for that merge.

The tone chain (per channel c in r, g, b; x = i/8 for i = 0..8, y clamped to [0,1] after every step)
-----------------------------------------------------------------------------------------------------
 1. exposure      y = x * 2**exposure
 2. white balance y = y * g_c  with T = temperature/100, N = tint/100
                  g_r = 1 + 0.20*T + 0.05*N,  g_g = 1 - 0.15*N,  g_b = 1 - 0.20*T + 0.05*N      (T>0 = warmer, N>0 = magenta)
 3. contrast      C = contrast/100:  y = y + C * (P(y) - y),  P(y) = y^3 * (6y^2 - 15y + 10)   (smootherstep S-curve about 0.5)
 4. zones         all four from the same y0 (order independent):
                  y = y0 + 0.30*sh*wS(y0) + 0.30*hi*wH(y0) + 0.20*wh*y0^3 + 0.20*bl*(1-y0)^3
                  sh = shadows/100, hi = highlights/100, wh = whites/100, bl = blacks/100
                  wS(y) = (256/27)*y*(1-y)^3 (peak 1 at y=.25) · wH(y) = (256/27)*(1-y)*y^3 (peak 1 at y=.75)
 5. master curve  y = pchip(curves.m)(y)                      (skipped when it is the identity)
 6. channel curve y = pchip(curves.<c>)(y)
 7. look curves   y = y + a*(pchip(look.m)(y) - y);  y = y + a*(pchip(look.<c>)(y) - y)    (a = look_amount/100)
 8. the 9 samples are made non-decreasing (running max), rounded to 4 decimals → `tone_points`.
    ffmpeg then runs `curves=interp=pchip:r='x0/y0 x1/y1 …':g=…:b=…` (channels that are the identity are left out).

PCHIP (monotone cubic Hermite, the SciPy/MATLAB algorithm; measured within 1/255 of ffmpeg's `curves=interp=pchip`):
    h_k = x_{k+1}-x_k,  d_k = (y_{k+1}-y_k)/h_k
    interior slope m_k = 0 if d_{k-1}*d_k <= 0 else (w1+w2)/(w1/d_{k-1} + w2/d_k),  w1 = 2h_k + h_{k-1},  w2 = h_k + 2h_{k-1}
    end slopes (three-point): s = ((2h0+h1)*d0 - h0*d1)/(h0+h1); 0 if sign(s) != sign(d0); 3*d0 if sign(d0) != sign(d1) and |s| > 3|d0|
    inside [x_k, x_k+1] with u = (x-x_k)/h:  y = (2u³-3u²+1)y_k + (u³-2u²+u)h m_k + (-2u³+3u²)y_{k+1} + (u³-u²)h m_{k+1}
    (outside the first/last point: clamp to the end value). 8-bit LUT in the browser: lut[v] = round(255*f(v/255)).

After the curves (ffmpeg filter order = pipeline order; denoise/blur run first, in YUV, so lifted shadows do not amplify noise)
----------------------------------------------------------------------------------------------------------------------
 a. denoise       hqdn3d=ls:cs:lt:ct   d = denoise/100:  ls=10d, cs=7.5d, lt=15d, ct=11d
 b. blur          boxblur=lr='min(w,h)*k':lp=2:cr='min(cw,ch)*k':cp=2   k = 0.03*blur/100   (radius follows the frame size)
 c. tone          curves (above)
 d. saturation    colorchannelmixer — an exact 3x3: S = saturation/100, Y = 0.2126R + 0.7152G + 0.0722B,  c' = S*c + (1-S)*Y
                  for every channel (S=0 → R=G=B exactly). Deliberately NOT `eq=saturation`: that one is YUV-only and would
                  cost an extra RGB↔YUV round trip, and it ran after the wheels which broke «sepia» (desaturate, then tint).
 e. vibrance      vibrance=intensity=I,  I = vibrance/100  (ffmpeg's own non-linear boost of the LEAST saturated colours; the
                  browser approximates it as c' = Y + (c-Y)*(1 + I*(1-sat)*2.2), sat = max-min)
 f. hsl           one `huesaturation=hue=H:saturation=S:intensity=I:colors=<r|y|g|c|b|m>` per range that is not zero,
                  H = h (degrees), S = s/100, I = l/100
 g. wheels        colorbalance=rs/gs/bs:rm/gm/bm:rh/gh/bh = the wheel values as they are. ffmpeg's maths (measured on a grey
                  ramp, matches to ±1 level): with r,g,b in 0..1 and l = max(r,g,b) + min(r,g,b)   (note: the SUM, not the mean)
                      wS = clamp((0.333 - l)*4 + 0.5, 0, 1)
                      wM = clamp((l - 0.333)*4 + 0.5, 0, 1) * clamp((1 - l - 0.333)*4 + 0.5, 0, 1)
                      wH = clamp((l + 0.333 - 1)*4 + 0.5, 0, 1)
                      c' = clamp(c + 0.7*(shadow_c*wS + mid_c*wM + high_c*wH), 0, 1)
 h. sharpen       unsharp=5:5:amount:5:5:0,  amount = 1.5*sharpen/100
 i. vignette      vignette=angle=PI/(5-3*s),  s = max(0.1, vignette/100)   (ffmpeg: a WIDER lens angle = a stronger vignette; same
                  mapping as the clip tool in tools.py; the effect is steep — 15..30 is already clearly visible)
 j. grain         noise=alls=0.4*grain:allf=t+u
Filter-format note: curves/colorchannelmixer/vibrance/huesaturation/colorbalance are RGB filters (ffmpeg inserts one
YUV→RGB and one RGB→YUV conversion around the block); hqdn3d/boxblur/unsharp/vignette/noise are YUV.
"""
from __future__ import annotations

import copy
import math

from .errors import TimelineError  # noqa: F401  (kept for callers that catch it from here)

SAMPLES = 9
XS = [i / (SAMPLES - 1) for i in range(SAMPLES)]

# key -> (min, max, default, step, Persian title, group)
SLIDERS: dict[str, tuple] = {
    "exposure": (-3.0, 3.0, 0.0, 0.05, "نوردهی (استاپ)", "light"),
    "contrast": (-100, 100, 0, 1, "کنتراست", "light"),
    "highlights": (-100, 100, 0, 1, "هایلایت‌ها", "light"),
    "shadows": (-100, 100, 0, 1, "سایه‌ها", "light"),
    "whites": (-100, 100, 0, 1, "سفیدها", "light"),
    "blacks": (-100, 100, 0, 1, "سیاه‌ها", "light"),
    "temperature": (-100, 100, 0, 1, "دمای رنگ (سرد ↔ گرم)", "color"),
    "tint": (-100, 100, 0, 1, "تینت (سبز ↔ سرخابی)", "color"),
    "saturation": (0, 200, 100, 1, "اشباع رنگ", "color"),
    "vibrance": (-100, 100, 0, 1, "ویبرنس", "color"),
    "sharpen": (0, 100, 0, 1, "شارپ", "effects"),
    "denoise": (0, 100, 0, 1, "حذف نویز تصویر", "effects"),
    "blur": (0, 100, 0, 1, "محو", "effects"),
    "vignette": (0, 100, 0, 1, "تیرگی لبه‌ها", "effects"),
    "grain": (0, 100, 0, 1, "دانهٔ فیلم", "effects"),
}
#: sliders that a look adds to (saturation is handled separately because its neutral value is 100)
_ADDITIVE = tuple(k for k in SLIDERS if k != "saturation")

ZONES = ("shadows", "mids", "highs")
ZONE_TITLES = {"shadows": "سایه‌ها", "mids": "میانه‌ها", "highs": "هایلایت‌ها"}
CURVE_CHANNELS = ("m", "r", "g", "b")
CURVE_TITLES = {"m": "روشنایی", "r": "قرمز", "g": "سبز", "b": "آبی"}
HSL_RANGES = ("red", "yellow", "green", "cyan", "blue", "magenta")
HSL_FLAG = {"red": "r", "yellow": "y", "green": "g", "cyan": "c", "blue": "b", "magenta": "m"}
HSL_TITLES = {"red": "قرمز", "yellow": "زرد", "green": "سبز", "cyan": "فیروزه‌ای", "blue": "آبی", "magenta": "سرخابی"}
HSL_SWATCH = {"red": "#ff3b30", "yellow": "#ffd60a", "green": "#30d158", "cyan": "#32d4e6", "blue": "#0a60ff", "magenta": "#e040c8"}

LOOK_AMOUNT = (0, 100, 100)
_IDENTITY_CURVE = [[0.0, 0.0], [1.0, 1.0]]
MAX_CURVE_POINTS = 8


# ------------------------------------------------------------------ looks

LOOKS: dict[str, dict] = {
    "cinematic": {"title": "سینمایی (سبز‌آبی و نارنجی)", "params": {
        "contrast": 22, "saturation": 108, "shadows": -8, "highlights": -6,
        "wheels": {"shadows": [-0.10, 0.02, 0.12], "highs": [0.10, 0.04, -0.10]}}},
    "warm_vintage": {"title": "قدیمیِ گرم", "params": {
        "temperature": 28, "tint": 6, "contrast": -12, "blacks": 22, "saturation": 84, "highlights": -8,
        "vignette": 14, "grain": 22, "wheels": {"highs": [0.08, 0.03, -0.08]}}},
    "faded_film": {"title": "فیلمِ رنگ‌پریده", "params": {
        "contrast": -14, "blacks": 34, "saturation": 78, "highlights": -10, "grain": 18,
        "curves": {"m": [[0, 0.07], [0.5, 0.5], [1, 0.95]]}}},
    "bw": {"title": "سیاه‌وسفید", "params": {"saturation": 0, "contrast": 14}},
    "bw_contrast": {"title": "سیاه‌وسفیدِ پرکنتراست", "params": {
        "saturation": 0, "contrast": 52, "blacks": -14, "whites": 10, "vignette": 12}},
    "cool_blue": {"title": "سردِ آبی", "params": {
        "temperature": -34, "tint": -4, "saturation": 104, "wheels": {"shadows": [-0.04, 0.0, 0.10]}}},
    "vivid": {"title": "پررنگ و شاداب", "params": {
        "saturation": 132, "vibrance": 30, "contrast": 16, "highlights": -6}},
    "moody": {"title": "تیره و خاص", "params": {
        "exposure": -0.45, "contrast": 26, "saturation": 84, "shadows": -18, "vignette": 22,
        "wheels": {"shadows": [-0.03, 0.02, 0.07]}}},
    "golden_hour": {"title": "غروبِ طلایی", "params": {
        "temperature": 42, "tint": 8, "exposure": 0.15, "highlights": -12, "saturation": 112,
        "wheels": {"highs": [0.12, 0.05, -0.10]}}},
    "matte": {"title": "مات", "params": {"blacks": 32, "highlights": -14, "contrast": -10, "saturation": 90}},
    "cross_process": {"title": "کراس‌پروسس", "params": {
        "saturation": 118, "curves": {
            "r": [[0, 0], [0.25, 0.18], [0.75, 0.86], [1, 1]],
            "g": [[0, 0], [0.5, 0.52], [1, 1]],
            "b": [[0, 0.10], [0.5, 0.45], [1, 0.86]]}}},
    "pastel": {"title": "پاستلیِ نرم", "params": {
        "exposure": 0.2, "contrast": -24, "saturation": 80, "blacks": 30, "whites": -10,
        "wheels": {"highs": [0.03, 0.02, 0.05]}}},
    "sepia": {"title": "سپیا", "params": {
        "saturation": 0, "contrast": 8,
        "wheels": {"shadows": [0.10, 0.0, -0.10], "mids": [0.22, 0.02, -0.20], "highs": [0.12, 0.0, -0.14]}}},
    "neon_night": {"title": "شبِ نئونی", "params": {
        "contrast": 28, "saturation": 122, "vibrance": 20, "exposure": -0.2,
        "wheels": {"shadows": [0.06, -0.04, 0.14], "highs": [0.12, -0.02, 0.06]}}},
    "fresh_food": {"title": "غذا و کافه (گرم و شاداب)", "params": {
        "temperature": 16, "contrast": 14, "saturation": 112, "vibrance": 22, "shadows": 10, "highlights": -8}},
}


# ------------------------------------------------------------------ clean


def _num(value, lo, hi, default):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return float(default)
    if x != x or x in (float("inf"), float("-inf")):
        return float(default)
    return round(max(lo, min(hi, x)), 4)


def _point(raw):
    if isinstance(raw, dict):
        raw = (raw.get("x"), raw.get("y"))
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if x != x or y != y:
        return None
    return (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))


def _clean_curve(raw) -> list[list[float]]:
    pts: list[tuple[float, float]] = []
    if isinstance(raw, (list, tuple)):
        for item in raw[:24]:
            p = _point(item)
            if p:
                pts.append(p)
    pts.sort(key=lambda p: p[0])
    merged: list[tuple[float, float]] = []
    for p in pts:                                    # one point per x (the last wins), minimal spacing 0.01
        if merged and p[0] - merged[-1][0] < 0.01:
            merged[-1] = p
        else:
            merged.append(p)
    if not merged or merged[0][0] > 0.0005:
        merged.insert(0, (0.0, 0.0))
    if merged[-1][0] < 0.9995:
        merged.append((1.0, 1.0))
    if len(merged) > MAX_CURVE_POINTS:               # keep both ends and spread the rest
        inner = merged[1:-1]
        keep = MAX_CURVE_POINTS - 2
        step = len(inner) / keep
        merged = [merged[0]] + [inner[int(i * step)] for i in range(keep)] + [merged[-1]]
    out = [[round(x, 4), round(y, 4)] for x, y in merged]
    if all(abs(x - y) < 1e-4 for x, y in out):
        return [list(p) for p in _IDENTITY_CURVE]
    return out


def neutral() -> dict:
    return clean(None)


def clean(params) -> dict:
    """Every key present, every number clamped, unknown keys dropped (never raises: a bad value falls back to neutral)."""
    src = params if isinstance(params, dict) else {}
    out: dict = {}
    for key, (lo, hi, default, _step, _title, _group) in SLIDERS.items():
        out[key] = _num(src.get(key), lo, hi, default)
    wheels_in = src.get("wheels") if isinstance(src.get("wheels"), dict) else {}
    out["wheels"] = {}
    for zone in ZONES:
        raw = wheels_in.get(zone)
        raw = raw if isinstance(raw, (list, tuple)) else []
        out["wheels"][zone] = [_num(raw[i] if i < len(raw) else 0.0, -1, 1, 0.0) for i in range(3)]
    curves_in = src.get("curves") if isinstance(src.get("curves"), dict) else {}
    out["curves"] = {ch: _clean_curve(curves_in.get(ch)) for ch in CURVE_CHANNELS}
    hsl_in = src.get("hsl") if isinstance(src.get("hsl"), dict) else {}
    out["hsl"] = {}
    for key in HSL_RANGES:
        raw = hsl_in.get(key) if isinstance(hsl_in.get(key), dict) else {}
        out["hsl"][key] = {"h": _num(raw.get("h"), -180, 180, 0.0), "s": _num(raw.get("s"), -100, 100, 0.0),
                           "l": _num(raw.get("l"), -100, 100, 0.0)}
    look = str(src.get("look") or "")
    out["look"] = look if look in LOOKS else ""
    out["look_amount"] = _num(src.get("look_amount"), LOOK_AMOUNT[0], LOOK_AMOUNT[1], LOOK_AMOUNT[2])
    return out


def effective(params) -> dict:
    """The cleaned parameters with the look merged in (see the module docstring). Adds `look_curves` (or None)."""
    p = clean(params)
    e = copy.deepcopy(p)
    e["look_curves"] = None
    look = LOOKS.get(p["look"])
    a = p["look_amount"] / 100.0
    if not look or a <= 0:
        return e
    lp = clean(look["params"])
    for key in _ADDITIVE:
        lo, hi = SLIDERS[key][0], SLIDERS[key][1]
        e[key] = _num(p[key] + a * lp[key], lo, hi, SLIDERS[key][2])
    e["saturation"] = _num(p["saturation"] + a * (lp["saturation"] - 100), 0, 200, 100)
    for zone in ZONES:
        e["wheels"][zone] = [_num(p["wheels"][zone][i] + a * lp["wheels"][zone][i], -1, 1, 0.0) for i in range(3)]
    for key in HSL_RANGES:
        e["hsl"][key] = {
            "h": _num(p["hsl"][key]["h"] + a * lp["hsl"][key]["h"], -180, 180, 0.0),
            "s": _num(p["hsl"][key]["s"] + a * lp["hsl"][key]["s"], -100, 100, 0.0),
            "l": _num(p["hsl"][key]["l"] + a * lp["hsl"][key]["l"], -100, 100, 0.0),
        }
    e["look_curves"] = {"amount": a, **{ch: lp["curves"][ch] for ch in CURVE_CHANNELS}}
    return e


# ------------------------------------------------------------------ PCHIP


def _sign(v: float) -> int:
    return (v > 0) - (v < 0)


def _edge_slope(h0: float, h1: float, d0: float, d1: float) -> float:
    s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
    if _sign(s) != _sign(d0):
        return 0.0
    if _sign(d0) != _sign(d1) and abs(s) > 3 * abs(d0):
        return 3 * d0
    return s


def pchip(points):
    """A function y = f(x) through `points` (x ascending): monotone cubic Hermite, clamped to the end values outside."""
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    n = len(xs)
    if n < 2:
        const = ys[0] if ys else 0.0
        return lambda x: const
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    if n == 2:
        m = [d[0], d[0]]
    else:
        m = [0.0] * n
        for k in range(1, n - 1):
            if d[k - 1] * d[k] > 0:
                w1 = 2 * h[k] + h[k - 1]
                w2 = h[k] + 2 * h[k - 1]
                m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
        m[0] = _edge_slope(h[0], h[1], d[0], d[1])
        m[-1] = _edge_slope(h[-1], h[-2], d[-1], d[-2])

    def f(x: float) -> float:
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        k = 0
        while k < n - 2 and x > xs[k + 1]:
            k += 1
        u = (x - xs[k]) / h[k]
        u2, u3 = u * u, u * u * u
        return ((2 * u3 - 3 * u2 + 1) * ys[k] + (u3 - 2 * u2 + u) * h[k] * m[k]
                + (-2 * u3 + 3 * u2) * ys[k + 1] + (u3 - u2) * h[k] * m[k + 1])
    return f


# ------------------------------------------------------------------ tone maths


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _smootherstep(y: float) -> float:
    return y * y * y * (y * (6 * y - 15) + 10)


_ZONE_NORM = 256.0 / 27.0


def _gains(e: dict) -> tuple[float, float, float]:
    t, n = e["temperature"] / 100.0, e["tint"] / 100.0
    return 1 + 0.20 * t + 0.05 * n, 1 - 0.15 * n, 1 - 0.20 * t + 0.05 * n


def _is_identity(curve) -> bool:
    return all(abs(p[0] - p[1]) < 1e-4 for p in curve)


class _Tone:
    """Prepared per-parameter-set state so 9 (or 256) evaluations do not rebuild the curves."""

    def __init__(self, e: dict):
        self.e = e
        self.gains = _gains(e)
        self.master = None if _is_identity(e["curves"]["m"]) else pchip(e["curves"]["m"])
        self.chan = [None if _is_identity(e["curves"][c]) else pchip(e["curves"][c]) for c in "rgb"]
        lc = e.get("look_curves")
        self.look_a = lc["amount"] if lc else 0.0
        self.look_master = pchip(lc["m"]) if lc and not _is_identity(lc["m"]) else None
        self.look_chan = [pchip(lc[c]) if lc and not _is_identity(lc[c]) else None for c in "rgb"]

    def value(self, ci: int, x: float) -> float:
        e = self.e
        y = _clamp01(x * 2.0 ** e["exposure"])
        y = _clamp01(y * self.gains[ci])
        c = e["contrast"] / 100.0
        if c:
            y = _clamp01(y + c * (_smootherstep(y) - y))
        sh, hi, wh, bl = (e["shadows"] / 100.0, e["highlights"] / 100.0, e["whites"] / 100.0, e["blacks"] / 100.0)
        if sh or hi or wh or bl:
            y0 = y
            y = _clamp01(y0 + 0.30 * sh * _ZONE_NORM * y0 * (1 - y0) ** 3 + 0.30 * hi * _ZONE_NORM * (1 - y0) * y0 ** 3
                         + 0.20 * wh * y0 ** 3 + 0.20 * bl * (1 - y0) ** 3)
        if self.master:
            y = _clamp01(self.master(y))
        if self.chan[ci]:
            y = _clamp01(self.chan[ci](y))
        a = self.look_a
        if a > 0:
            if self.look_master:
                y = _clamp01(y + a * (self.look_master(y) - y))
            if self.look_chan[ci]:
                y = _clamp01(y + a * (self.look_chan[ci](y) - y))
        return y


def tone_value(params, channel: str, x: float) -> float:
    """The exact (un-sampled) tone curve of one channel ("r" | "g" | "b") at x in 0..1."""
    return _Tone(effective(params)).value("rgb".index(channel), x)


def _tone_points_eff(e: dict) -> dict[str, list[tuple[float, float]]]:
    tone = _Tone(e)
    out = {}
    for ci, ch in enumerate("rgb"):
        run, pts = 0.0, []
        for x in XS:
            run = max(run, tone.value(ci, x))
            pts.append((round(x, 4), round(run, 4)))
        out[ch] = pts
    return out


def tone_points(params) -> dict[str, list[tuple[float, float]]]:
    """{"r": [(x, y) × 9], "g": …, "b": …} — what `curves` is fed; mirror these with PCHIP in the browser."""
    return _tone_points_eff(effective(params))


# ------------------------------------------------------------------ ffmpeg


def _f(value) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


def _curve_arg(points) -> str:
    return " ".join(f"{_f(x)}/{_f(y)}" for x, y in points)


def _is_diagonal(points) -> bool:
    return all(abs(x - y) < 0.0015 for x, y in points)


def _nonzero(values) -> bool:
    return any(abs(v) > 1e-6 for v in values)


def build_filters(params) -> list[str]:
    """ffmpeg video filter fragments, in order. Empty for the neutral parameter set (the caller adds nothing)."""
    e = effective(params)
    out: list[str] = []

    d = e["denoise"] / 100.0
    if d > 0.004:
        out.append(f"hqdn3d={_f(10 * d)}:{_f(7.5 * d)}:{_f(15 * d)}:{_f(11 * d)}")
    if e["blur"] > 0.4:
        k = _f(0.03 * e["blur"] / 100.0)
        out.append(f"boxblur=lr='min(w\\,h)*{k}':lp=2:cr='min(cw\\,ch)*{k}':cp=2")

    pts = _tone_points_eff(e)
    args = [f"{ch}='{_curve_arg(pts[ch])}'" for ch in "rgb" if not _is_diagonal(pts[ch])]
    if args:
        out.append("curves=interp=pchip:" + ":".join(args))

    s = e["saturation"] / 100.0
    if abs(s - 1.0) > 1e-4:
        wr, wg, wb = 0.2126, 0.7152, 0.0722
        k = 1 - s
        out.append(
            "colorchannelmixer="
            f"rr={_f(s + k * wr)}:rg={_f(k * wg)}:rb={_f(k * wb)}:"
            f"gr={_f(k * wr)}:gg={_f(s + k * wg)}:gb={_f(k * wb)}:"
            f"br={_f(k * wr)}:bg={_f(k * wg)}:bb={_f(s + k * wb)}")

    if abs(e["vibrance"]) > 0.4:
        out.append(f"vibrance=intensity={_f(e['vibrance'] / 100.0)}")

    for key in HSL_RANGES:
        v = e["hsl"][key]
        if _nonzero((v["h"], v["s"], v["l"])):
            out.append(f"huesaturation=hue={_f(v['h'])}:saturation={_f(v['s'] / 100.0)}"
                       f":intensity={_f(v['l'] / 100.0)}:colors={HSL_FLAG[key]}")

    wheel = []
    for zone, tag in (("shadows", "s"), ("mids", "m"), ("highs", "h")):
        for i, ch in enumerate("rgb"):
            v = e["wheels"][zone][i]
            if abs(v) > 1e-6:
                wheel.append(f"{ch}{tag}={_f(v)}")
    if wheel:
        out.append("colorbalance=" + ":".join(wheel))

    if e["sharpen"] > 0.4:
        out.append(f"unsharp=5:5:{_f(1.5 * e['sharpen'] / 100.0)}:5:5:0")
    if e["vignette"] > 0.4:
        out.append(f"vignette=angle=PI/{_f(5 - 3 * max(0.1, e['vignette'] / 100.0))}")
    if e["grain"] > 0.4:
        out.append(f"noise=alls={_f(0.4 * e['grain'])}:allf=t+u")
    return out


def is_neutral(params) -> bool:
    return not build_filters(params)


# ------------------------------------------------------------------ the panel


def catalogue() -> dict:
    """JSON-able description for the panel: slider ranges, wheels, curve channels, HSL ranges and the looks."""
    return {
        "sliders": [{"key": k, "min": v[0], "max": v[1], "default": v[2], "step": v[3], "title": v[4], "group": v[5]}
                    for k, v in SLIDERS.items()],
        "wheels": [{"key": z, "title": ZONE_TITLES[z]} for z in ZONES],
        "curves": [{"key": c, "title": CURVE_TITLES[c]} for c in CURVE_CHANNELS],
        "hsl": [{"key": k, "title": HSL_TITLES[k], "color": HSL_SWATCH[k]} for k in HSL_RANGES],
        "look_amount": {"min": LOOK_AMOUNT[0], "max": LOOK_AMOUNT[1], "default": LOOK_AMOUNT[2]},
        "looks": [{"key": k, "title": v["title"], "params": clean(v["params"])} for k, v in LOOKS.items()],
        "samples": SAMPLES,
    }
