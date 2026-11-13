"""پالتِ رنگیِ هر طراحی: از رنگ‌های برندِ فروشگاه + «حالِ‌وهوا»ی سبک.

قطعی و بدونِ هوش مصنوعی. اگر فروشگاه رنگِ برند دارد، همهٔ رنگ‌ها از همان‌ها ساخته می‌شوند (تیره‌تر، روشن‌تر، مکمل)؛ وگرنه
رنگ‌های پیش‌فرضِ هر حالِ‌وهوا. متنِ اصلی همیشه با پس‌زمینه کنتراستِ کافی دارد (``ensure_contrast``).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apps.photoedit.designer import colorx

MOODS = ("vivid", "dark", "light", "cinema", "neon", "luxury", "warm", "cool")
MOOD_FA = {"vivid": "پرانرژی", "dark": "تیره", "light": "روشن و تمیز", "cinema": "سینمایی", "neon": "نئونی",
           "luxury": "لوکس", "warm": "گرم", "cool": "سرد و مدرن"}

#: رنگِ پایهٔ هر حال‌وهوا وقتی فروشگاه رنگِ برند ندارد: (اصلی، دوم)
DEFAULTS = {
    "vivid": ("#7c3aed", "#ec4899"),
    "dark": ("#1d4ed8", "#0ea5e9"),
    "light": ("#2563eb", "#f59e0b"),
    "cinema": ("#0f766e", "#ea580c"),
    "neon": ("#d946ef", "#22d3ee"),
    "luxury": ("#c9a24b", "#8a6d2b"),
    "warm": ("#ea580c", "#f59e0b"),
    "cool": ("#0ea5e9", "#6366f1"),
}


@dataclass
class Palette:
    bg1: str            # زمینهٔ اصلی (تیره‌تر)
    bg2: str            # زمینهٔ دوم (روشن‌تر یا مکمل)
    accent: str         # رنگِ تأکید (کلمهٔ مهم، دکمه، نشان)
    accent2: str        # رنگِ تأکیدِ دوم
    text: str           # رنگِ متنِ اصلی روی زمینه
    ink: str            # رنگِ تیره (حاشیهٔ متن، متنِ روی تأکید)
    paper: str          # رنگِ روشنِ ملایم (کارت‌ها، کاغذ)
    dark: bool          # زمینه تیره است؟
    primary: str        # رنگِ اصلیِ برند (یا پیش‌فرض)

    def public(self) -> dict:
        return asdict(self)


def _hsl(hex_color: str):
    return colorx.to_hsl(hex_color)


def _norm(c) -> str | None:
    c = str(c or "").strip().lower()
    return c if colorx.is_hex(c) else None


def clean_colors(values) -> list[str]:
    out: list[str] = []
    for v in values or []:
        n = _norm(v)
        if n and n not in out:
            out.append(n)
    return out[:5]


def brand_colors_of(store_colors, photo_brand_colors=None) -> list[str]:
    """رنگ‌های برند: اول «سبکِ برند»ِ ادیتورِ عکس، بعد رنگ‌هایی که در خودِ فروشگاه ثبت شده (دیکشنری یا فهرست)."""
    got = clean_colors(photo_brand_colors)
    if got:
        return got
    vals: list = []
    if isinstance(store_colors, dict):
        for key in ("primary", "main", "brand", "secondary", "accent", "second"):
            if key in store_colors:
                vals.append(store_colors[key])
        vals += [v for k, v in store_colors.items() if k not in ("primary", "main", "brand", "secondary", "accent", "second")]
    elif isinstance(store_colors, (list, tuple)):
        vals = list(store_colors)
    return clean_colors([v for v in vals if isinstance(v, str)])


def ensure_contrast(fg: str, bg: str, minimum: float = 3.0, *, light: str = "#ffffff", dark: str = "#0b1020") -> str:
    """fg اگر روی bg کنتراستِ کافی ندارد، به سفید/مشکیِ مناسب عوض می‌شود."""
    if colorx.contrast(fg, bg) >= minimum:
        return fg
    return light if colorx.contrast(light, bg) >= colorx.contrast(dark, bg) else dark


def _rot(color: str, deg: float, s: float | None = None, l: float | None = None) -> str:
    h, ss, ll = _hsl(color)
    return colorx.from_hsl(h + deg, ss if s is None else s, ll if l is None else l)


def build(mood: str, brand: list[str] | None = None, overrides: dict | None = None, variation: int = 0) -> Palette:
    """پالتِ کامل. ``variation`` (۰،۱،۲…) نسخهٔ A/B می‌سازد: جابه‌جاییِ رنگِ اصلی/دوم و چرخشِ ملایمِ فام برای رنگ‌های پیش‌فرض."""
    mood = mood if mood in MOODS else "vivid"
    brand = clean_colors(brand)
    ov = overrides or {}
    base1, base2 = DEFAULTS[mood]
    primary = _norm(ov.get("primary")) or (brand[0] if brand else base1)
    secondary = _norm(ov.get("secondary")) or (brand[1] if len(brand) > 1 else None)
    if secondary is None:
        # بدونِ رنگِ دوم: مکملِ نزدیک (۳۰ تا ۴۰ درجه) یا رنگِ دومِ پیش‌فرضِ حال‌وهوا وقتی برند نداریم
        secondary = base2 if not brand else _rot(primary, 35)
    if variation % 2 == 1:
        primary, secondary = secondary, primary
    if variation >= 2 and not brand and not ov.get("primary"):
        primary, secondary = _rot(primary, 40 * (variation // 2)), _rot(secondary, 40 * (variation // 2))
    accent_in = _norm(ov.get("accent"))

    ph, ps, pl = _hsl(primary)
    sh, ss, sl = _hsl(secondary)
    if mood in ("vivid", "warm", "cool"):
        bg1 = colorx.from_hsl(ph, max(0.55, ps), 0.26 if pl > 0.3 else pl)
        bg2 = colorx.from_hsl(sh, max(0.6, ss), 0.5)
        accent = accent_in or "#ffd400"
        accent2 = colorx.from_hsl(sh + 25, 0.9, 0.62)
        dark = True
        text, ink, paper = "#ffffff", "#0b1020", "#fff7e6"
    elif mood == "dark":
        bg1 = colorx.from_hsl(ph, min(0.5, ps), 0.07)
        bg2 = colorx.from_hsl(ph, min(0.6, ps), 0.2)
        accent = accent_in or colorx.from_hsl(sh, max(0.7, ss), 0.62)
        accent2 = colorx.from_hsl(ph, max(0.7, ps), 0.58)
        dark = True
        text, ink, paper = "#f8fafc", "#05070d", "#e2e8f0"
    elif mood == "light":
        bg1 = colorx.from_hsl(ph, min(0.55, ps), 0.94)
        bg2 = colorx.from_hsl(sh, min(0.6, ss), 0.86)
        accent = accent_in or colorx.from_hsl(ph, max(0.65, ps), 0.42)
        accent2 = colorx.from_hsl(sh, max(0.65, ss), 0.5)
        dark = False
        text, ink, paper = "#0f172a", "#0f172a", "#ffffff"
    elif mood == "cinema":
        bg1 = colorx.from_hsl(ph, min(0.6, max(0.35, ps)), 0.08)
        bg2 = colorx.from_hsl(ph, min(0.6, max(0.4, ps)), 0.24)
        accent = accent_in or colorx.from_hsl(sh, 0.8, 0.55)
        accent2 = colorx.from_hsl(ph, 0.55, 0.6)
        dark = True
        text, ink, paper = "#f4efe6", "#05070d", "#e9dcc4"
    elif mood == "neon":
        bg1 = colorx.from_hsl(ph + 220, 0.5, 0.06)
        bg2 = colorx.from_hsl(ph + 240, 0.55, 0.14)
        accent = accent_in or colorx.from_hsl(ph, 1.0, 0.62)
        accent2 = colorx.from_hsl(sh + 40, 1.0, 0.6)
        dark = True
        text, ink, paper = "#ffffff", "#05010f", "#e9d5ff"
    else:  # luxury
        bg1 = colorx.from_hsl(ph, min(0.18, ps), 0.07)
        bg2 = colorx.from_hsl(ph, min(0.2, ps), 0.14)
        accent = accent_in or (colorx.with_lightness(primary, 0.66, 0.6) if brand else "#d4af37")
        accent2 = colorx.from_hsl(_hsl(accent)[0], 0.55, 0.72)
        dark = True
        text, ink, paper = "#f5efe0", "#0a0a0a", "#efe6d2"
    if colorx.contrast(accent, bg1) < 2.2:        # تأکید روی زمینه گم شد ⇒ روشن‌ترش کن
        accent = colorx.with_lightness(accent, 0.65 if dark else 0.35)
    return Palette(bg1=bg1, bg2=bg2, accent=accent, accent2=accent2, text=text, ink=ink, paper=paper, dark=dark,
                   primary=primary)


def on(color: str, light: str = "#ffffff", dark: str = "#0b1020") -> str:
    """متنِ خوانا روی یک رنگِ دلخواه (سفید یا تیره، هرکدام کنتراستِ بیشتری دارد)."""
    return light if colorx.contrast(light, color) >= colorx.contrast(dark, color) else dark
