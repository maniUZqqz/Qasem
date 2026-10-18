"""
Persian text overlay for generated posters (Phase 9 / beter.md #4).

Diffusion models cannot render Persian script — they produce garbled
pseudo-Arabic. So FLUX generates a TEXT-FREE visual and this module draws the
real headline/price with Pillow, using the bundled Vazirmatn font and proper
RTL shaping (arabic_reshaper + python-bidi when Pillow lacks libraqm).
"""

import logging
import os
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

logger = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# resolution order: env override → bundled Vazirmatn → common Windows fonts
FONT_CANDIDATES_BOLD = [
    os.getenv("POSTER_FONT_PATH", ""),
    str(FONTS_DIR / "Vazirmatn-Bold.ttf"),
    r"C:\Windows\Fonts\Vazirmatn-Bold.ttf",
    r"C:\Windows\Fonts\tahomabd.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
]
FONT_CANDIDATES_REGULAR = [
    os.getenv("POSTER_FONT_PATH", ""),
    str(FONTS_DIR / "Vazirmatn-Regular.ttf"),
    r"C:\Windows\Fonts\Vazirmatn-Regular.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
]

_HAS_RAQM = features.check("raqm")


class OverlayError(Exception):
    pass


def _find_font(candidates) -> str:
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise OverlayError("No Persian-capable TTF font found for the poster overlay.")


def shape_rtl(text: str) -> str:
    """Prepare Persian text for Pillow when libraqm is unavailable."""
    if _HAS_RAQM:
        return text  # raqm shapes and reorders on its own (direction passed at draw time)
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(text))


def _draw_kwargs():
    return {"direction": "rtl", "language": "fa"} if _HAS_RAQM else {}


def _fit_font(draw, text, font_path, max_width, start_size, min_size=18):
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        if draw.textlength(text, font=font, **_draw_kwargs()) <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(font_path, min_size)


def add_poster_text(
    image_path,
    out_path,
    headline: str,
    subline: str = "",
    badge: str = "",
):
    """
    Draw Persian poster text onto a generated image.

    headline — main line (product / campaign title), bottom-centered on a
    dark gradient band; subline — smaller line under it; badge — short text
    (e.g. price) in a pill at the top corner. Returns out_path.
    """
    headline = (headline or "").strip()
    subline = (subline or "").strip()
    badge = (badge or "").strip()
    if not (headline or subline or badge):
        raise OverlayError("Nothing to draw: empty headline/subline/badge.")

    bold = _find_font(FONT_CANDIDATES_BOLD)
    regular = _find_font(FONT_CANDIDATES_REGULAR)

    image = Image.open(image_path).convert("RGBA")
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if headline or subline:
        # legibility gradient over the bottom band
        band_height = int(height * 0.30)
        for y in range(band_height):
            alpha = int(200 * (y / band_height) ** 1.5)
            draw.line(
                [(0, height - band_height + y), (width, height - band_height + y)],
                fill=(0, 0, 0, alpha),
            )

    max_text_width = int(width * 0.88)
    cursor_y = height - int(height * 0.04)  # bottom margin; we draw upwards

    if subline:
        sub_lines = textwrap.wrap(subline, width=48)[:2]
        sub_font = ImageFont.truetype(regular, max(int(width * 0.032), 16))
        for line in reversed(sub_lines):
            shaped = shape_rtl(line)
            line_h = sub_font.getbbox("آگ")[3] + 6
            cursor_y -= line_h
            draw.text(
                (width / 2, cursor_y),
                shaped,
                font=sub_font,
                fill=(235, 235, 235, 255),
                anchor="ma",
                **_draw_kwargs(),
            )
        cursor_y -= int(height * 0.012)

    if headline:
        head_lines = textwrap.wrap(headline, width=26)[:2]
        for line in reversed(head_lines):
            shaped = shape_rtl(line)
            font = _fit_font(draw, shaped, bold, max_text_width, int(width * 0.075))
            line_h = font.getbbox("آگ")[3] + 8
            cursor_y -= line_h
            # slight shadow for pop
            draw.text(
                (width / 2 + 2, cursor_y + 2),
                shaped,
                font=font,
                fill=(0, 0, 0, 160),
                anchor="ma",
                **_draw_kwargs(),
            )
            draw.text(
                (width / 2, cursor_y),
                shaped,
                font=font,
                fill=(255, 255, 255, 255),
                anchor="ma",
                **_draw_kwargs(),
            )

    if badge:
        shaped = shape_rtl(badge)
        badge_font = _fit_font(draw, shaped, bold, int(width * 0.42), int(width * 0.045))
        pad_x, pad_y = int(width * 0.025), int(width * 0.014)
        text_w = draw.textlength(shaped, font=badge_font, **_draw_kwargs())
        text_h = badge_font.getbbox("آگ")[3]
        # RTL layout → pill sits in the top-right corner
        x1 = width - int(width * 0.04)
        x0 = x1 - text_w - 2 * pad_x
        y0 = int(height * 0.04)
        y1 = y0 + text_h + 2 * pad_y
        draw.rounded_rectangle(
            [x0, y0, x1, y1], radius=(y1 - y0) // 2, fill=(124, 58, 237, 230)
        )
        draw.text(
            ((x0 + x1) / 2, y0 + pad_y),
            shaped,
            font=badge_font,
            fill=(255, 255, 255, 255),
            anchor="ma",
            **_draw_kwargs(),
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    composed = Image.alpha_composite(image, overlay).convert("RGB")
    composed.save(out_path, quality=95)
    return out_path


# Persian digits and the Persian thousands separator. A poster that mixes
# "2,450,000" into Persian typography looks like a mock-up, not a product.
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

CURRENCY_LABEL = {
    "IRT": "تومان",
    "TOMAN": "تومان",
    "IRR": "ریال",
}


def to_persian_digits(text: str) -> str:
    """`1,250,000` → `۱٬۲۵۰٬۰۰۰` (Persian digits + Persian thousands mark)."""
    return str(text).translate(_PERSIAN_DIGITS).replace(",", "٬")


def format_price_fa(amount, currency: str = "IRT") -> str:
    """A price ready to be drawn on a Persian poster, or "" when there is none."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    label = CURRENCY_LABEL.get(str(currency or "").upper(), str(currency or "").strip())
    grouped = to_persian_digits(f"{value:,.0f}")
    return f"{grouped} {label}".strip()
