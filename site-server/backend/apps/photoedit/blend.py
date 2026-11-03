"""حالت‌های ترکیبِ لایه‌ها (W3C Compositing and Blending Level 1) روی آرایه‌های numpy.

``blend(mode, cb, cs)`` ⇐ B(Cb, Cs) برای رنگ‌های «مستقیم» (straight alpha) با شکلِ (..., 3) و بازهٔ ۰..۱.
``composite(...)`` ⇐ فرمولِ کاملِ ترکیب با آلفا:

    ar = as + ab (1 − as)
    Cr = ((1 − as)·ab·Cb + (1 − ab)·as·Cs + as·ab·B(Cb, Cs)) / ar
"""
from __future__ import annotations

import numpy as np

BLEND_MODES = (
    "normal", "multiply", "screen", "overlay", "soft-light", "hard-light", "darken", "lighten",
    "color-dodge", "color-burn", "difference", "exclusion", "hue", "saturation", "color", "luminosity",
)


def _lum(c: np.ndarray) -> np.ndarray:
    return 0.3 * c[..., 0] + 0.59 * c[..., 1] + 0.11 * c[..., 2]


def _clip_color(c: np.ndarray) -> np.ndarray:
    l = _lum(c)[..., None]
    n = c.min(axis=-1, keepdims=True)
    x = c.max(axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(n < 0, l + (c - l) * l / np.where(l - n == 0, 1, l - n), c)
        c = np.where(x > 1, l + (c - l) * (1 - l) / np.where(x - l == 0, 1, x - l), c)
    return c


def _set_lum(c: np.ndarray, l: np.ndarray) -> np.ndarray:
    d = (l - _lum(c))[..., None]
    return _clip_color(c + d)


def _sat(c: np.ndarray) -> np.ndarray:
    return c.max(axis=-1) - c.min(axis=-1)


def _set_sat(c: np.ndarray, s: np.ndarray) -> np.ndarray:
    mn = c.min(axis=-1, keepdims=True)
    mx = c.max(axis=-1, keepdims=True)
    rng = mx - mn
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(rng > 0, (c - mn) * s[..., None] / np.where(rng > 0, rng, 1), 0.0)
    return out


def _hard_light(cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    return np.where(cs <= 0.5, cb * (2 * cs), cb + (2 * cs - 1) - cb * (2 * cs - 1))


def _soft_light(cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    d = np.where(cb <= 0.25, ((16 * cb - 12) * cb + 4) * cb, np.sqrt(np.maximum(cb, 0)))
    return np.where(cs <= 0.5, cb - (1 - 2 * cs) * cb * (1 - cb), cb + (2 * cs - 1) * (d - cb))


def blend(mode: str, cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    if mode == "normal":
        return cs
    if mode == "multiply":
        return cb * cs
    if mode == "screen":
        return cb + cs - cb * cs
    if mode == "overlay":
        return _hard_light(cs, cb)
    if mode == "hard-light":
        return _hard_light(cb, cs)
    if mode == "soft-light":
        return _soft_light(cb, cs)
    if mode == "darken":
        return np.minimum(cb, cs)
    if mode == "lighten":
        return np.maximum(cb, cs)
    if mode == "color-dodge":
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.minimum(1.0, cb / np.where(cs >= 1, 1, 1 - cs))
        return np.where(cb <= 0, 0.0, np.where(cs >= 1, 1.0, r))
    if mode == "color-burn":
        with np.errstate(divide="ignore", invalid="ignore"):
            r = 1 - np.minimum(1.0, (1 - cb) / np.where(cs <= 0, 1, cs))
        return np.where(cb >= 1, 1.0, np.where(cs <= 0, 0.0, r))
    if mode == "difference":
        return np.abs(cb - cs)
    if mode == "exclusion":
        return cb + cs - 2 * cb * cs
    if mode == "hue":
        return _set_lum(_set_sat(cs, _sat(cb)), _lum(cb))
    if mode == "saturation":
        return _set_lum(_set_sat(cb, _sat(cs)), _lum(cb))
    if mode == "color":
        return _set_lum(cs, _lum(cb))
    if mode == "luminosity":
        return _set_lum(cb, _lum(cs))
    raise ValueError(mode)


def composite(mode: str, cb: np.ndarray, ab: np.ndarray, cs: np.ndarray, a_s: np.ndarray):
    """cb، cs: (h, w, 3) float32؛ ab، a_s: (h, w) ⇐ (Cr, ar) مستقیم (straight)."""
    a_s3 = a_s[..., None]
    ab3 = ab[..., None]
    ar = a_s + ab * (1 - a_s)
    if mode == "normal":
        num = cs * a_s3 + cb * (ab3 * (1 - a_s3))
    else:
        b = blend(mode, cb, cs)
        num = (1 - a_s3) * ab3 * cb + (1 - ab3) * a_s3 * cs + a_s3 * ab3 * b
    with np.errstate(divide="ignore", invalid="ignore"):
        cr = np.where(ar[..., None] > 1e-6, num / np.maximum(ar[..., None], 1e-6), 0.0)
    return cr.astype(np.float32), ar.astype(np.float32)
