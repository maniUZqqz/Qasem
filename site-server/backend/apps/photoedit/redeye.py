"""رفعِ قرمزیِ چشم (لایهٔ ``redeye``)، فقط روی کادرِ هر چشم.

لایه: ``{"type":"redeye","eyes":[{"x":0.41,"y":0.32,"r":0.012}],"amount":1.0,"darken":0.6}`` — x و y کسری از W و H، r کسری از W.

فرمول (numpy و GLSL یکی؛ همهٔ رنگ‌ها ۰..۱ در فضای نمایش، sRGB ِ همان بایت‌ها)::

    d      = فاصلهٔ مرکزِ پیکسل (x+0.5، y+0.5) از مرکزِ چشم، به پیکسل        (r_px = r·W، مرکز = (x·W، y·H))
    w      = 1 - smoothstep(0.75·r_px, 1.2·r_px, d)
    neutral= (G + B) / 2
    ratio  = R / max(1e-4, neutral + 0.04)
    m      = smoothstep(1.4, 2.4, ratio) · smoothstep(0.15, 0.35, R) · w · amount
    R'     = R + (min(R, neutral·(1 − 0.5·darken)) − R) · m
    G'     = G · (1 − 0.4·darken·m)
    B'     = B · (1 − 0.4·darken·m)

smoothstep(e0, e1, x) = t²(3−2t) با t = clamp((x−e0)/(e1−e0), 0, 1). چند چشم **پشتِ هم به ترتیبِ فهرست** اعمال می‌شود (چشمِ i
روی خروجیِ چشمِ i−1). بیرونِ d > ۱٫۲·r_px هیچ چیز عوض نمی‌شود، پس فقط کادرِ ⌊x·W−1.2r⌋…⌈x·W+1.2r⌉ محاسبه می‌شود.
نتیجه با ``layers._lerp_region`` (پیدایی × ماسکِ لایه) با رنگِ پیشین ترکیب می‌شود، مثلِ لایهٔ تنظیم.
"""
from __future__ import annotations

import math

import numpy as np

MAX_EYES = 16


def smoothstep(e0: float, e1: float, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def eye_box(eye: dict, W: int, H: int):
    """کادرِ پیکسلیِ چشم (x0, y0, x1, y1) درون بوم، یا None."""
    r = eye["r"] * W
    cx, cy = eye["x"] * W, eye["y"] * H
    ext = 1.2 * r + 1.0
    x0, x1 = max(0, int(math.floor(cx - ext))), min(W, int(math.ceil(cx + ext)))
    y0, y1 = max(0, int(math.floor(cy - ext))), min(H, int(math.ceil(cy + ext)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def union_box(eyes: list[dict], W: int, H: int):
    boxes = [b for b in (eye_box(e, W, H) for e in eyes) if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def fix_region(rgb: np.ndarray, ox: int, oy: int, eyes: list[dict], amount: float, darken: float, W: int, H: int) -> None:
    """rgb: float32 ۰..۱ (h, w, 3) که گوشهٔ بالا-چپش بومِ (ox, oy) است؛ درجا تغییر می‌کند."""
    h, w = rgb.shape[:2]
    for eye in eyes:
        box = eye_box(eye, W, H)
        if not box:
            continue
        x0, y0, x1, y1 = max(box[0], ox), max(box[1], oy), min(box[2], ox + w), min(box[3], oy + h)
        if x1 <= x0 or y1 <= y0:
            continue
        sub = rgb[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        r_px = eye["r"] * W
        xs = (np.arange(x0, x1, dtype=np.float32) + 0.5)[None, :]
        ys = (np.arange(y0, y1, dtype=np.float32) + 0.5)[:, None]
        d = np.hypot(xs - eye["x"] * W, ys - eye["y"] * H)
        wgt = 1.0 - smoothstep(0.75 * r_px, 1.2 * r_px, d)
        R, G, B = sub[..., 0], sub[..., 1], sub[..., 2]
        neutral = (G + B) * 0.5
        ratio = R / np.maximum(1e-4, neutral + 0.04)
        m = smoothstep(1.4, 2.4, ratio) * smoothstep(0.15, 0.35, R) * wgt * np.float32(amount)
        new_r = R + (np.minimum(R, neutral * (1.0 - 0.5 * darken)) - R) * m
        k = 1.0 - 0.4 * darken * m
        sub[..., 0] = new_r
        sub[..., 1] = G * k
        sub[..., 2] = B * k


def reference_pixel(rgb, px: float, py: float, eye: dict, amount: float, darken: float, W: int, H: int):
    """همان فرمول با ریاضیِ خالصِ پایتون برای یک پیکسل (px، py = مرکزِ پیکسل به px)؛ برای آزمون و مستند."""
    def ss(e0, e1, x):
        t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
        return t * t * (3 - 2 * t)

    R, G, B = (float(v) for v in rgb)
    r_px = eye["r"] * W
    d = math.hypot(px - eye["x"] * W, py - eye["y"] * H)
    w = 1 - ss(0.75 * r_px, 1.2 * r_px, d)
    neutral = (G + B) / 2
    ratio = R / max(1e-4, neutral + 0.04)
    m = ss(1.4, 2.4, ratio) * ss(0.15, 0.35, R) * w * amount
    return (R + (min(R, neutral * (1 - 0.5 * darken)) - R) * m, G * (1 - 0.4 * darken * m), B * (1 - 0.4 * darken * m))
