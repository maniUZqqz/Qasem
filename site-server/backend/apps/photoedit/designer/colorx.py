"""رنگ در طراحیِ خودکار: کنتراستِ WCAG، هارمونیِ رنگ از روی پالتِ محصول، پالتِ عکس.

هیچ هوشِ مصنوعی‌ای این‌جا نیست؛ همه قطعی و آزمون‌پذیر است. رنگ‌ها همه ``#rrggbb`` اند.
"""
from __future__ import annotations

import colorsys
import re

import numpy as np

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

WCAG_NORMAL = 4.5       # متنِ معمولی
WCAG_LARGE = 3.0        # متنِ درشت (≥ ۱۸٫۶۷px پررنگ یا ≥ ۲۴px) — در بومِ ۱۰۸۰: اندازهٔ حدودِ ≥ ۴٫۵٪ پهنا


def is_hex(v) -> bool:
    return isinstance(v, str) and bool(_HEX.match(v))


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(float(v))))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lin(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luminance(rgb) -> float:
    """روشناییِ نسبیِ WCAG (۰ تا ۱) برای یک رنگ."""
    r, g, b = _lin(rgb)
    return float(0.2126 * r + 0.7152 * g + 0.0722 * b)


def luminance_array(arr) -> np.ndarray:
    """روشناییِ نسبیِ هر پیکسل؛ arr: (..., 3) uint8/float ۰..۲۵۵."""
    a = _lin(np.asarray(arr))
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def contrast(a, b) -> float:
    """نسبتِ کنتراستِ WCAG بینِ دو رنگ (۱ تا ۲۱)؛ a و b: hex یا (r,g,b)."""
    ra = hex_to_rgb(a) if isinstance(a, str) else a
    rb = hex_to_rgb(b) if isinstance(b, str) else b
    la, lb = luminance(ra), luminance(rb)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def contrast_pixels(text_rgb, pixels) -> np.ndarray:
    """کنتراستِ یک رنگِ متن با هر پیکسلِ پس‌زمینه ⇒ آرایه."""
    lt = luminance(text_rgb)
    lp = luminance_array(pixels).reshape(-1)
    hi = np.maximum(lt, lp)
    lo = np.minimum(lt, lp)
    return (hi + 0.05) / (lo + 0.05)


def region_contrast(text_rgb, pixels, pct: float = 10.0) -> float:
    """«بدترین ۱۰٪» کنتراست: ۹۰٪ پیکسل‌های زیرِ متن حداقل همین‌قدر کنتراست دارند."""
    px = np.asarray(pixels).reshape(-1, 3)
    if px.size == 0:
        return 21.0
    return float(np.percentile(contrast_pixels(text_rgb, px), pct))


def mix(a: str, b: str, t: float) -> str:
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def to_hsl(h: str) -> tuple[float, float, float]:
    r, g, b = (v / 255.0 for v in hex_to_rgb(h))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    return hh * 360.0, ss, ll


def from_hsl(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360.0) / 360.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return rgb_to_hex([r * 255, g * 255, b * 255])


def with_lightness(h: str, l: float, s: float | None = None) -> str:
    hh, ss, _ = to_hsl(h)
    return from_hsl(hh, ss if s is None else s, l)


def best_text(bg_pixels, candidates=("#ffffff", "#111111"), pct: float = 10.0) -> tuple[str, float]:
    """از میانِ نامزدها رنگی که روی این پس‌زمینه بیشترین «بدترین‌۱۰٪ کنتراست» را دارد."""
    best, best_r = candidates[0], -1.0
    for c in candidates:
        r = region_contrast(hex_to_rgb(c), bg_pixels, pct)
        if r > best_r:
            best, best_r = c, r
    return best, best_r


_NAMES = [  # (فام، نام) — برای توضیحِ پالت به فارسی
    (15, "قرمز"), (40, "نارنجی"), (65, "زرد"), (95, "لیمویی"), (160, "سبز"), (195, "فیروزه‌ای"),
    (255, "آبی"), (290, "بنفش"), (335, "صورتی"), (361, "قرمز"),
]


def name_fa(h: str) -> str:
    hh, ss, ll = to_hsl(h)
    if ll < 0.12:
        return "مشکی"
    if ll > 0.92:
        return "سفید"
    if ss < 0.12:
        return "خاکستری روشن" if ll > 0.6 else "خاکستری" if ll > 0.3 else "خاکستریِ تیره"
    base = next(n for lim, n in _NAMES if hh < lim)
    if base == "نارنجی" and ll < 0.35:
        return "قهوه‌ای"
    tone = "روشنِ " if ll > 0.72 else "تیرهٔ " if ll < 0.28 else ""
    return (tone + base).strip()


def palette_from_pixels(px, k: int = 5) -> list[dict]:
    """k-means روی پیکسل‌ها (N×3 uint8) ⇒ [{hex, share, name}] به ترتیبِ سهم. N کوچک و قطعی (seed ثابت)."""
    import cv2

    px = np.asarray(px, dtype=np.float32).reshape(-1, 3)
    if len(px) < 16:
        return []
    if len(px) > 4000:
        idx = np.linspace(0, len(px) - 1, 4000).astype(int)       # نمونه‌گیریِ یکنواخت (قطعی)
        px = px[idx]
    k = max(1, min(k, len(np.unique(px.astype(np.uint8), axis=0))))
    cv2.setRNGSeed(7)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _c, labels, centers = cv2.kmeans(px, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.reshape(-1), minlength=k).astype(float)
    order = np.argsort(-counts)
    out = []
    for i in order:
        hx = rgb_to_hex(centers[i])
        out.append({"hex": hx, "share": round(float(counts[i] / counts.sum()), 3), "name": name_fa(hx)})
    return out


def pick_dominant_and_accent(palette: list[dict]) -> tuple[str, str]:
    """رنگِ غالبِ «رنگی» (نه خاکستری/سفید) و پرجلوه‌ترین رنگِ مهم؛ اگر عکس بی‌رنگ بود، همان غالب."""
    if not palette:
        return "#64748b", "#f59e0b"
    chromatic = [p for p in palette if to_hsl(p["hex"])[1] > 0.18 and 0.12 < to_hsl(p["hex"])[2] < 0.9]
    dom = (chromatic or palette)[0]["hex"]
    cands = [p for p in chromatic if p["share"] >= 0.05] or chromatic
    accent = max(cands, key=lambda p: to_hsl(p["hex"])[1] * (0.5 + p["share"]))["hex"] if cands else dom
    return dom, accent


MOODS = ("auto", "light", "dark", "warm", "cool", "vibrant", "elegant", "minimal")
MOOD_FA = {"auto": "خودکار", "light": "روشن و تمیز", "dark": "تیره و جدی", "warm": "گرم", "cool": "سرد و مدرن",
           "vibrant": "پرانرژی", "elegant": "شیک و لوکس", "minimal": "مینیمال"}


def make_palette(dominant: str, accent: str, *, mood: str = "auto", variation: int = 0, brand: list[str] | None = None,
                 image_luma: float = 0.5) -> dict:
    """پالتِ طراحی: bg_a/bg_b (زمینهٔ شیب)، text، text_dim، accent، accent_text، plate، dark (آیا زمینه تیره است).

    هارمونی از رنگِ محصول: روشن = تینتِ بسیار کم‌رنگِ همان فام؛ تیره = سایهٔ عمیقِ همان فام؛ گرم/سرد = چرخشِ فام؛
    پرانرژی = اشباعِ بالا؛ شیک = مشکیِ گرم + طلایی. ``variation`` (۰..۲) وقتی mood=auto است سه حالتِ مختلف می‌دهد.
    اگر برند رنگ داشت (brand[0]) رنگِ تأکید همان می‌شود. متن همیشه روی زمینه ≥ ۴٫۵ کنتراست دارد.
    """
    if not is_hex(dominant):
        dominant = "#64748b"
    if not is_hex(accent):
        accent = dominant
    if mood not in MOODS:
        mood = "auto"
    if mood == "auto":
        mood = ("light", "dark", "vibrant")[int(variation) % 3] if image_luma >= 0.35 else ("dark", "light", "vibrant")[int(variation) % 3]
    h, s, l = to_hsl(dominant)
    s_ = max(0.25, min(0.75, s))
    if mood == "light":
        a, b = from_hsl(h, 0.30, 0.96), from_hsl(h + 8, 0.34, 0.88)
        text = from_hsl(h, 0.35, 0.12)
        acc = from_hsl(to_hsl(accent)[0], max(0.55, to_hsl(accent)[1]), 0.42)
    elif mood == "dark":
        a, b = from_hsl(h, s_ * 0.8, 0.10), from_hsl(h + 10, s_ * 0.9, 0.20)
        text = "#ffffff"
        acc = from_hsl(to_hsl(accent)[0] + 0.0, max(0.6, to_hsl(accent)[1]), 0.62)
    elif mood == "warm":
        a, b = from_hsl(32, 0.55, 0.94), from_hsl(22, 0.62, 0.82)
        text = from_hsl(18, 0.45, 0.14)
        acc = from_hsl(14, 0.78, 0.46)
    elif mood == "cool":
        a, b = from_hsl(210, 0.35, 0.95), from_hsl(222, 0.45, 0.86)
        text = from_hsl(224, 0.45, 0.13)
        acc = from_hsl(214, 0.8, 0.45)
    elif mood == "vibrant":
        a, b = from_hsl(h, 0.78, 0.52), from_hsl(h + 28, 0.80, 0.40)
        text = "#ffffff"
        acc = from_hsl(h + 180, 0.85, 0.55)
    elif mood == "elegant":
        a, b = "#16120e", "#2b231a"
        text = "#f6efe2"
        acc = "#c9a24a"
    else:  # minimal
        a, b = "#ffffff", "#f1f2f4"
        text = "#16181d"
        acc = from_hsl(h, max(0.5, s), 0.40)
    if brand:
        for cand in brand:
            if is_hex(cand):
                acc = cand
                break
    mid = mix(a, b, 0.5)
    # متن روی زمینه ≥ ۴٫۵؛ اگر نه، بهترین از سفید/تقریباً-سیاه
    if contrast(text, mid) < WCAG_NORMAL:
        text = next((c for c in ("#ffffff", "#111111", "#000000") if contrast(c, mid) >= WCAG_NORMAL),
                    "#ffffff" if contrast("#ffffff", mid) >= contrast("#000000", mid) else "#000000")
    dark = luminance(hex_to_rgb(mid)) < 0.3
    accent_text = "#ffffff" if contrast("#ffffff", acc) >= contrast("#111111", acc) else "#111111"
    if contrast(accent_text, acc) < WCAG_NORMAL:       # رنگِ تأکید برای دکمه خیلی «وسط» است ⇒ کمی تیره/روشن
        acc = with_lightness(acc, 0.30) if accent_text == "#ffffff" else with_lightness(acc, 0.68)
        accent_text = "#ffffff" if contrast("#ffffff", acc) >= contrast("#111111", acc) else "#111111"
        if contrast(accent_text, acc) < WCAG_NORMAL:
            accent_text = "#ffffff" if contrast("#ffffff", acc) >= contrast("#000000", acc) else "#000000"
    return {"mood": mood, "bg_a": a, "bg_b": b, "text": text, "text_dim": mix(text, mid, 0.28), "accent": acc,
            "accent_text": accent_text, "plate": "#0b0f1a" if not dark else "#ffffff", "dark": bool(dark),
            "dominant": dominant}
