"""شکل‌های تزئینیِ تامنیل: فلش، انفجارِ نشان، خطِ زیرِ کلمه، حلقه، کنفتی، چسب‌نواری، آیکنِ فهرست…

همه RGBA برمی‌گردانند (با لبهٔ صاف) و جابه‌جاییِ لبه‌ای که ``primitives.stylized`` اضافه کرده را خودشان نگه نمی‌دارند؛
فراخواننده با ``bbox`` مرکزچین می‌کند. بدونِ Django.
"""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from . import primitives as P


def _bezier(p0, p1, p2, n=48):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def arrow(length: float, thick: float, fill: str, outline: str | None = "#0b1020", ow: float = 0.0, bend: float = 0.28,
          angle: float = 0.0, shadow: bool = True) -> Image.Image:
    """فلشِ ضخمِ کمی خمیده (مثلِ فلشِ «اینجا را ببین»)؛ نوک به سمتِ راست‌پایین‌ِ محورِ ``angle`` (درجه، ۰ = رو به راست)."""
    L, T = int(length), int(thick)
    pad = int(ow + thick * 0.8 + 6)
    W, H = L + 2 * pad + T * 2, int(L * (abs(bend) + 0.25)) + 2 * pad + T * 3
    p0 = (pad, H / 2 + L * bend * 0.45)
    p2 = (pad + L - T * 1.2, H / 2 - L * bend * 0.45)
    p1 = ((p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2 + L * bend)
    path = _bezier(p0, p1, p2)
    left, right = [], []
    for i, (x, y) in enumerate(path):
        a = path[min(i + 1, len(path) - 1)]
        b = path[max(i - 1, 0)]
        tx, ty = a[0] - b[0], a[1] - b[1]
        n = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / n, tx / n
        w = T / 2 * (0.55 + 0.45 * i / len(path))           # از نازک به ضخیم
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    tip_dir = (path[-1][0] - path[-4][0], path[-1][1] - path[-4][1])
    n = math.hypot(*tip_dir) or 1.0
    ux, uy = tip_dir[0] / n, tip_dir[1] / n
    base = path[-1]
    head_len, head_w = T * 1.8, T * 1.7
    tip = (base[0] + ux * head_len, base[1] + uy * head_len)
    h1 = (base[0] - uy * head_w, base[1] + ux * head_w)
    h2 = (base[0] + uy * head_w, base[1] - ux * head_w)
    poly = left + [h1, tip, h2] + right[::-1]
    mask = P.polygon_mask((W, H), poly)
    img, _ = P.stylized(mask, fill, outline=outline, ow=ow,
                        shadow=(thick * 0.1, thick * 0.14, thick * 0.12, "#000000", 0.4) if shadow else None)
    img = P.crop_to_alpha(img)
    if abs(angle) > 0.01:
        img = img.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
    return img


def burst(radius: float, fill: str, outline: str | None = None, ow: float = 0.0, points: int = 14, inner: float = 0.8,
          rot: float = 0.0, shadow: bool = True) -> Image.Image:
    """انفجارِ ستاره‌ای (پشتِ قیمت/نشان)؛ مرکزِ تصویر = مرکزِ شکل."""
    r = int(radius)
    pad = int(ow + radius * 0.25 + 6)
    S = 2 * r + 2 * pad
    mask = P.polygon_mask((S, S), P.star_points(S / 2, S / 2, r, r * inner, points, rot))
    img, _ = P.stylized(mask, fill, outline=outline, ow=ow,
                        shadow=(0, radius * 0.06, radius * 0.07, "#000000", 0.4) if shadow else None)
    return img


def circle(radius: float, fill: str | None = None, ring: str | None = None, ring_w: float = 0.0, shadow: bool = False,
           alpha: float = 1.0) -> Image.Image:
    r = int(radius)
    pad = int(ring_w + radius * 0.2 + 4)
    S = 2 * r + 2 * pad
    m = P.aa_mask((S, S), lambda d, k: d.ellipse([pad * k, pad * k, (pad + 2 * r) * k, (pad + 2 * r) * k], fill=255))
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if shadow:
        img = Image.alpha_composite(img, P.soft_shadow((S, S), m, 0, radius * 0.08, radius * 0.1, "#000000", 0.4))
    if ring and ring_w:
        outer = P.dilate(m, ring_w)
        img = Image.alpha_composite(img, P.solid((S, S), ring, outer, alpha))
    if fill:
        img = Image.alpha_composite(img, P.solid((S, S), fill, m, alpha))
    return img


def ring(radius: float, width: float, color: str, alpha: float = 1.0, dash: bool = False) -> Image.Image:
    """حلقهٔ توخالی (برای دورِ گرفتنِ چیزی)."""
    r, w = int(radius), max(1, int(width))
    pad = w + 6
    S = 2 * r + 2 * pad

    def fn(d, k):
        if dash:
            n = 28
            for i in range(n):
                if i % 2 == 0:
                    d.arc([pad * k, pad * k, (pad + 2 * r) * k, (pad + 2 * r) * k], 360 / n * i, 360 / n * (i + 0.7), fill=255, width=w * k)
        else:
            d.ellipse([pad * k, pad * k, (pad + 2 * r) * k, (pad + 2 * r) * k], outline=255, width=w * k)

    return P.solid((S, S), color, P.aa_mask((S, S), fn), alpha)


def brush_stripe(w: float, h: float, color: str, slant: float = 0.18, rough: float = 0.12, seed: int = 3) -> Image.Image:
    """نوارِ «ماژیکِ هایلایت» پشتِ کلمه: چهارضلعیِ اریب با لبهٔ کمی ناصاف."""
    rnd = random.Random(seed)
    W, H = int(w), int(h)
    sk = int(H * slant)
    j = lambda: rnd.uniform(-rough, rough) * H  # noqa: E731
    pts = [(sk + j(), j()), (W - j() ** 2 * 0, j()), (W - sk + j(), H + j()), (j(), H + j())]
    pts = [(min(max(x, 0), W), min(max(y, 0), H)) for x, y in pts]
    return P.solid((W, H), color, P.polygon_mask((W, H), pts))


def tape(w: float, h: float, color: str = "#f6e7a6", rot: float = -6.0, alpha: float = 0.85) -> Image.Image:
    W, H = int(w), int(h)
    m = P.polygon_mask((W, H), [(0, 2), (W * 0.04, H * 0.2), (0, H * 0.4), (W * 0.03, H * 0.62), (0, H - 2),
                                (W, H - 2), (W * 0.97, H * 0.6), (W, H * 0.38), (W * 0.96, H * 0.18), (W, 2)])
    img = P.solid((W, H), color, m, alpha)
    return img.rotate(rot, resample=Image.Resampling.BICUBIC, expand=True)


def checklist(w: float, h: float, fg: str, bg: str, accent: str, rows: int = 4) -> Image.Image:
    """آیکنِ فهرست (کادرِ تیک‌دار + خط) برای سبکِ «لیست» وقتی عددی داده نشده."""
    W, H = int(w), int(h)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rh = H / rows
    for i in range(rows):
        y = i * rh + rh * 0.15
        bh = rh * 0.7
        box = P.rounded_mask((int(bh), int(bh)), bh * 0.22)
        img = Image.alpha_composite(img, _at(P.solid((int(bh), int(bh)), bg, box), (W, H), (W - bh, y)))
        # تیک
        tick = Image.new("RGBA", (int(bh), int(bh)), (0, 0, 0, 0))
        d = ImageDraw.Draw(tick)
        d.line([(bh * 0.2, bh * 0.52), (bh * 0.42, bh * 0.74), (bh * 0.8, bh * 0.28)], fill=P.rgba(accent), width=max(2, int(bh * 0.14)), joint="curve")
        img = Image.alpha_composite(img, _at(tick, (W, H), (W - bh, y)))
        bar_w = (W - bh * 1.4) * (0.92 - 0.14 * (i % 3))
        bar = P.rounded_mask((int(bar_w), int(bh * 0.34)), bh * 0.17)
        img = Image.alpha_composite(img, _at(P.solid((int(bar_w), int(bh * 0.34)), fg, bar, 0.9), (W, H), (W - bh * 1.25 - bar_w, y + bh * 0.33)))
    return img


def _at(layer: Image.Image, size, xy) -> Image.Image:
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(layer, (int(xy[0]), int(xy[1])), layer)
    return out


def confetti(size: tuple[int, int], colors: list[str], count: int, seed: int = 5, min_px: float = 10, max_px: float = 36,
             avoid: list[tuple[int, int, int, int]] | None = None) -> Image.Image:
    """کنفتیِ پراکنده: دایره، مربعِ چرخیده، مثلث، نقطه‌چین و زیگزاگ. ``avoid``: کادرهایی که نباید رویشان بیفتد (متنِ اصلی)."""
    rnd = random.Random(seed)
    W, H = size
    ss = 2
    big = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    placed = 0
    tries = 0
    while placed < count and tries < count * 8:
        tries += 1
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        s = rnd.uniform(min_px, max_px)
        if avoid and any(a[0] - s <= x <= a[2] + s and a[1] - s <= y <= a[3] + s for a in avoid):
            continue
        col = P.rgba(rnd.choice(colors), 235)
        kind = rnd.choice(("circle", "square", "tri", "zig", "ring"))
        k = ss
        if kind == "circle":
            d.ellipse([(x - s / 2) * k, (y - s / 2) * k, (x + s / 2) * k, (y + s / 2) * k], fill=col)
        elif kind == "ring":
            d.ellipse([(x - s / 2) * k, (y - s / 2) * k, (x + s / 2) * k, (y + s / 2) * k], outline=col, width=max(2, int(s * 0.22 * k)))
        elif kind == "square":
            a = math.radians(rnd.uniform(0, 90))
            pts = [(x + math.cos(a + i * math.pi / 2) * s * 0.7, y + math.sin(a + i * math.pi / 2) * s * 0.7) for i in range(4)]
            d.polygon([(px * k, py * k) for px, py in pts], fill=col)
        elif kind == "tri":
            a = math.radians(rnd.uniform(0, 120))
            pts = [(x + math.cos(a + i * 2 * math.pi / 3) * s * 0.75, y + math.sin(a + i * 2 * math.pi / 3) * s * 0.75) for i in range(3)]
            d.polygon([(px * k, py * k) for px, py in pts], fill=col)
        else:
            pts = [((x - s + i * s / 2) * k, (y + (s / 4 if i % 2 else -s / 4)) * k) for i in range(5)]
            d.line(pts, fill=col, width=max(2, int(s * 0.16 * k)), joint="curve")
        placed += 1
    return big.resize((W, H), Image.Resampling.LANCZOS)


def sparkle(radius: float, color: str = "#ffffff") -> Image.Image:
    """جرقهٔ چهارپَر."""
    r = int(radius)
    S = 2 * r + 4
    pts = []
    for i in range(8):
        rr = r if i % 2 == 0 else r * 0.18
        a = math.pi * i / 4 - math.pi / 2
        pts.append((S / 2 + rr * math.cos(a), S / 2 + rr * math.sin(a)))
    return P.solid((S, S), color, P.polygon_mask((S, S), pts))


def chevrons(w: float, h: float, color: str, n: int = 3, thick: float = 0.18, alpha: float = 1.0) -> Image.Image:
    """فلش‌های ‹‹‹ (برای جداکنندهٔ قبل/بعد)؛ رو به راست."""
    W, H = int(w), int(h)

    def fn(d, k):
        step = W * k / n
        for i in range(n):
            x = i * step
            tk = H * k * thick
            d.polygon([(x, 0), (x + step * 0.55, H * k / 2), (x, H * k), (x + tk, H * k), (x + step * 0.55 + tk, H * k / 2), (x + tk, 0)], fill=255)

    return P.solid((W, H), color, P.aa_mask((W, H), fn), alpha)


def lightning(w: float, h: float, fill: str = "#ffe600", outline: str = "#0b1020", ow: float = 4.0) -> Image.Image:
    W, H = int(w), int(h)
    pts = [(W * 0.55, 0), (W * 0.12, H * 0.58), (W * 0.45, H * 0.58), (W * 0.3, H), (W * 0.9, H * 0.38), (W * 0.55, H * 0.38), (W * 0.78, 0)]
    img, _ = P.stylized(P.polygon_mask((W, H), pts), fill, outline=outline, ow=ow,
                        shadow=(0, H * 0.04, H * 0.05, "#000000", 0.4))
    return img


def film_grain_overlay(size: tuple[int, int], amount: float = 0.04, seed: int = 2) -> Image.Image:
    import numpy as np

    rng = np.random.default_rng(seed)
    n = rng.normal(0, 1, (size[1], size[0])).astype("float32")
    a = np.clip(128 + n * amount * 255, 0, 255).astype("uint8")
    return Image.merge("RGBA", [Image.fromarray(a)] * 3 + [Image.new("L", size, 255)])


def quote_mark(size: float, color: str, closing: bool = True, alpha: float = 1.0) -> Image.Image:
    """علامتِ نقل‌قولِ دوتایی (” یا “) به شکلِ دو «کاما»ی پُر؛ مستقل از فونت (همیشه درست دیده می‌شود)."""
    s = max(8, int(size))
    r = s * 0.2
    gap = r * 2.5
    W, H = int(gap + r * 3.2), int(r * 4.4)
    pad = 4

    def one(d, k, ox):
        # دایره + دُمِ خمیده (کاما). closing: دایره بالا و دُم به پایین‌چپ؛ opening: قرینهٔ عمودی/افقی
        cx, cy = ox + r * 1.4, r * 1.3
        d.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=255)
        tip = (cx - r * 0.7, cy + r * 2.7)
        outer = _bezier((cx + r * 0.98, cy + r * 0.15), (cx + r * 1.15, cy + r * 1.9), tip)
        inner = _bezier(tip, (cx - r * 0.15, cy + r * 1.35), (cx - r * 0.75, cy + r * 0.5))
        d.polygon([(x * k, y * k) for x, y in outer + inner], fill=255)

    def fn(d, k):
        one(d, k, pad)
        one(d, k, pad + gap)

    m = P.aa_mask((W + 2 * pad, H + 2 * pad), fn)
    if not closing:
        m = m.transpose(Image.Transpose.ROTATE_180)
    return P.solid(m.size, color, m, alpha)
