"""Stickers: a small built-in pack of transparent PNGs (emoji from Noto Color Emoji, badges and arrows drawn with `shapes.py`,
Persian price/sale badges laid out with Pillow + libraqm and Vazirmatn). §23.4

A sticker is an ordinary image on the timeline (`ref="sticker:<key>"`), so it moves, scales, fades, gets masks and follows a
motion track like any photo. The PNGs are made on first use and kept under ``MEDIA_ROOT/generated/editing/stickers/``
(512×512, a few KB each); the panel shows them from the same files.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from . import shapes
from .errors import TimelineError
from .titles import FONTS_DIR

logger = logging.getLogger(__name__)

SIZE = 512
EMOJI_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",
)

#: key → (title, emoji)
EMOJI: dict[str, tuple[str, str]] = {
    "fire": ("آتش", "\U0001F525"), "heart": ("قلب", "\u2764\ufe0f"), "star": ("ستارهٔ طلایی", "\u2b50"), "sparkles": ("درخشش", "\u2728"),
    "thumbs_up": ("لایک", "\U0001F44D"), "party": ("جشن", "\U0001F389"), "hundred": ("صد", "\U0001F4AF"), "love_eyes": ("عاشق", "\U0001F60D"),
    "laugh": ("خنده", "\U0001F602"), "clap": ("تشویق", "\U0001F44F"), "cart": ("سبد خرید", "\U0001F6D2"), "gift": ("هدیه", "\U0001F381"),
    "pin": ("موقعیت", "\U0001F4CD"), "phone": ("تلفن", "\u260e\ufe0f"), "bolt": ("رعد", "\u26a1"), "check": ("تیک", "\u2705"),
    "alert": ("هشدار", "\u2757"), "boom": ("انفجار", "\U0001F4A5"), "tag": ("برچسبِ قیمت", "\U0001F3F7\ufe0f"), "bell": ("زنگ", "\U0001F514"),
    "coffee": ("قهوه", "\u2615"), "cake": ("کیک", "\U0001F370"), "sun": ("خورشید", "\u2600\ufe0f"), "crown": ("تاج", "\U0001F451"),
}

#: key → (title, shape spec, text | None, text colour, text size as a fraction of the box)
BADGES: dict[str, tuple[str, dict, str | None, str, float]] = {
    "sale": ("تخفیف", {"shape": "burst", "points": 12, "inner": 0.8, "fill": "#e11d48", "stroke": "#ffffff", "stroke_w": 2.0}, "تخفیف", "#ffffff", 0.2),
    "new": ("جدید", {"shape": "ellipse", "fill": "#16a34a", "stroke": "#ffffff", "stroke_w": 3.0}, "جدید", "#ffffff", 0.26),
    "free_ship": ("ارسال رایگان", {"shape": "rounded", "radius": 28, "fill": "#2563eb", "stroke": "#ffffff", "stroke_w": 3.0}, "ارسال رایگان", "#ffffff", 0.14),
    "bestseller": ("پرفروش", {"shape": "star", "points": 5, "inner": 0.5, "fill": "#f59e0b", "stroke": "#ffffff", "stroke_w": 2.5}, "پرفروش", "#1f2937", 0.13),
    "off50": ("۵۰٪", {"shape": "burst", "points": 10, "inner": 0.78, "fill": "#facc15", "stroke": "#b45309", "stroke_w": 2.0}, "۵۰٪", "#7f1d1d", 0.32),
    "special": ("ویژه", {"shape": "heart", "fill": "#a855f7", "fill2": "#ec4899", "angle": 90, "stroke": "#ffffff", "stroke_w": 3.0}, "ویژه", "#ffffff", 0.2),
    "arrow_right": ("فلشِ راست", {"shape": "arrow", "fill": "#f97316", "stroke": "#ffffff", "stroke_w": 3.0}, None, "#fff", 0),
    "arrow_ring": ("حلقه", {"shape": "ellipse", "fill": "#ffffff", "fill_opacity": 0.0, "stroke": "#ef4444", "stroke_w": 6.0}, None, "#fff", 0),
    "triangle_warn": ("مثلثِ هشدار", {"shape": "triangle", "fill": "#facc15", "stroke": "#111827", "stroke_w": 4.0}, "!", "#111827", 0.4),
}


def sticker_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / "stickers"


def _emoji_font_path() -> str | None:
    for cand in EMOJI_FONT_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return None


def _raqm() -> bool:
    try:
        from PIL import features

        return bool(features.check("raqm"))
    except Exception:  # noqa: BLE001
        return False


def available() -> list[dict]:
    """[{key, title, group}] of the stickers this machine can draw."""
    out = []
    if _raqm():
        out += [{"key": k, "title": v[0], "group": "badge"} for k, v in BADGES.items()]
    else:
        out += [{"key": k, "title": v[0], "group": "badge"} for k, v in BADGES.items() if v[2] is None]
    if _emoji_font_path():
        out += [{"key": k, "title": v[0], "group": "emoji"} for k, v in EMOJI.items()]
    return out


def _emoji_png(emoji: str, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(_emoji_font_path(), 109)
    tile = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((80, 80), emoji, font=font, embedded_color=True, anchor="mm")
    box = tile.getbbox()
    if box is None:
        raise TimelineError("ایموجی ساخته نشد.")
    tile = tile.crop(box)
    k = (SIZE * 0.92) / max(tile.size)
    tile = tile.resize((max(1, int(tile.width * k)), max(1, int(tile.height * k))), Image.LANCZOS)
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    img.paste(tile, ((SIZE - tile.width) // 2, (SIZE - tile.height) // 2), tile)
    img.save(out, "PNG")


def _badge_png(spec: dict, text: str | None, color: str, size: float, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    cleaned = shapes.clean(spec)
    base = SIZE
    h = SIZE if cleaned["shape"] != "rounded" else int(SIZE * 0.5)
    shapes.render_png(cleaned, base, h, out)
    img = Image.open(out).convert("RGBA")
    if text:
        font_file = Path(FONTS_DIR) / "Vazirmatn-Bold.ttf"
        font_path = str(font_file) if font_file.is_file() else None
        font = ImageFont.truetype(font_path, max(10, int(SIZE * size)), layout_engine=ImageFont.Layout.RAQM) if font_path else ImageFont.load_default()
        draw = ImageDraw.Draw(img)
        kw = {"direction": "rtl", "language": "fa"} if text != "!" and font_path else {}
        draw.text((base / 2, h / 2 + (base * 0.02 if text == "!" else 0)), text, font=font, fill=color, anchor="mm", **kw)
    full = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    full.paste(img, (0, (SIZE - img.height) // 2), img)
    full.save(out, "PNG")


def path_of(key: str) -> Path:
    """The PNG of sticker `key` (made now if it is the first time). Raises TimelineError for an unknown key."""
    key = str(key or "")
    if not key.replace("_", "").isalnum():
        raise TimelineError(f"استیکر «{key}» نامعتبر است.")
    out = sticker_dir() / f"{key}.png"
    if out.is_file() and out.stat().st_size > 0:
        return out
    sticker_dir().mkdir(parents=True, exist_ok=True)
    try:
        if key in EMOJI:
            if not _emoji_font_path():
                raise TimelineError("فونتِ ایموجی روی این سرور نیست.")
            _emoji_png(EMOJI[key][1], out)
        elif key in BADGES:
            title, spec, text, color, size = BADGES[key]
            if text and text != "!" and not _raqm():
                raise TimelineError("چیدنِ متنِ فارسی (libraqm) روی این سرور نیست.")
            _badge_png(spec, text, color, size, out)
        else:
            raise TimelineError(f"استیکر «{key}» پیدا نشد.")
    except TimelineError:
        raise
    except Exception as exc:  # noqa: BLE001
        out.unlink(missing_ok=True)
        raise TimelineError(f"ساختنِ استیکر «{key}» ممکن نشد: {exc}") from exc
    out.chmod(0o644)
    return out


def title_of(key: str) -> str:
    return (EMOJI.get(key) or BADGES.get(key) or (key,))[0]
