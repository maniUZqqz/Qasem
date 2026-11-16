"""متن ⇒ منحنی (outline): هر خطِ متن با همان شکل‌دهیِ Pillow + raqm به ماسکِ پرجزئیات تبدیل و به چندضلعیِ دقیق برگردانده می‌شود.

چرا؟ راهنمای فایل‌ها می‌گوید «فونت‌ها جاسازی یا به منحنی تبدیل شوند (Convert to Curves)»؛ با منحنی‌کردن هر چاپخانه‌ای فایل را بی‌فونت باز می‌کند
و شکلِ حروفِ فارسی (اتصال‌ها، نقطه‌ها) دقیقاً همان است که روی پیش‌نمایش دیدید. مختصات به «em» (اندازهٔ قلم = ۱) و نسبت به (لبهٔ چپِ خط، خطِ پایه) است.
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from apps.photoedit import textlayer

from . import fonts

_DRAW = ImageDraw.Draw(Image.new("L", (4, 4)))
MAX_MASK_PIXELS = 24_000_000


def em_pixels(size_pt: float, quality: str = "print") -> int:
    """اندازهٔ em برای ماسک: هر چه خروجی درشت‌تر، دقیق‌تر (تا ۹۶۰ پیکسل)."""
    k = 8 if quality == "print" else 4
    lo = 160 if quality == "print" else 96
    return int(max(lo, min(960, round(size_pt * k))))


@lru_cache(maxsize=4096)
def _contours(path: str, text: str, rtl: bool, em_px: int, eps10: int) -> tuple[tuple, float]:
    """⇒ (چندضلعی‌ها، پیشروی) به em. چندضلعی‌ها tuple از tuple نقطه‌اند (قابلِ کَش)."""
    font = ImageFont.truetype(path, em_px)
    shaped = textlayer._shape(text, rtl)
    kw = textlayer._kw(rtl)
    adv = float(_DRAW.textlength(shaped, font=font, **kw))
    asc, desc = font.getmetrics()
    pad = int(em_px * 0.35) + 4
    W = int(adv) + 2 * pad + 2
    H = asc + desc + 2 * pad
    if W * H > MAX_MASK_PIXELS:
        return (), adv / em_px
    img = Image.new("L", (W, H), 0)
    ImageDraw.Draw(img).text((pad, pad + asc), shaped, font=font, fill=255, anchor="ls", **kw)
    mask = (np.asarray(img) >= 96).astype(np.uint8)
    found = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    conts = found[0] if len(found) == 2 else found[1]
    out = []
    eps = eps10 / 10.0
    for c in conts:
        if len(c) < 3:
            continue
        ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(ap) < 3:
            continue
        out.append(tuple(((float(x) + 0.5 - pad) / em_px, (float(y) + 0.5 - pad - asc) / em_px) for x, y in ap))
    return tuple(out), adv / em_px


def line_contours(text: str, font: str, weight: int, rtl: bool, em_px: int, eps: float = 0.55):
    """⇒ (فهرستِ چندضلعی‌ها به em، پیشروی به em)."""
    if not text.strip():
        return (), 0.0
    return _contours(fonts.resolve(font, weight), text, bool(rtl), int(em_px), int(round(eps * 10)))
