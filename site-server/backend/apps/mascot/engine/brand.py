"""ماسکوتِ فروشگاه: نقش‌های آماده (مربی، فروشنده، آشپز، پیک، مشاور) و ساختنِ spec از رنگ‌های برند.

این ماژول فقط در NM هست (در InstAI نیست): شخصیتِ یک تولیدکنندهٔ کانال با شخصیتِ «چهرهٔ فروشگاه» فرق دارد. رنگِ اصلیِ برند روی دستمالِ سر/کلاه/پیش‌بند/وسیله می‌نشیند
و رنگِ دوم روی دست و پا؛ لوگوی فروشگاه روی سینه (اختیاری). هیچ نقشی ادعا یا قیمت یا آمار ندارد؛ فقط ظاهر است.
"""
from __future__ import annotations

import colorsys

from . import spec as S

DEFAULT_PRIMARY = "#2f7fd1"
INK = "#14213a"

#: نقش ⇒ ظاهر و پیشنهادها. توکنِ رنگ: primary | secondary | limb | white | amber | kraft | ink
ROLES: dict[str, dict] = {
    "coach": {
        "fa": "مربی", "hint": "هدبندِ برند، برگهٔ برنامه؛ برای ورزش، تمرین و آموزش",
        "look": {"head_style": "round", "eye_style": "round", "hair": "tuft", "hat": "headband", "neck": "none", "extra": "none", "prop": "clipboard"},
        "colours": {"hat": "primary", "prop": "primary", "extra": "primary", "neck": "primary", "hair": "ink"},
        "background": "gym", "expression": "happy", "pose": "thumbs_up", "tags": ("explain", "thumbs_up", "exercise", "point"),
    },
    "shopkeeper": {
        "fa": "فروشنده", "hint": "کلاهِ لبه‌دار و پاپیونِ برند، پیش‌بند، کیسهٔ خرید؛ برای محصول و فروشگاه",
        "look": {"head_style": "round", "eye_style": "round", "hair": "none", "hat": "cap", "neck": "bowtie", "extra": "apron", "prop": "bag"},
        "colours": {"hat": "primary", "neck": "primary", "extra": "primary", "prop": "primary", "hair": "ink"},
        "background": "counter", "expression": "happy", "pose": "hold", "tags": ("greet", "explain", "point", "cheer"),
    },
    "cook": {
        "fa": "آشپز", "hint": "کلاهِ آشپز، پیش‌بندِ برند، تابه؛ برای غذا و آشپزخانه",
        "look": {"head_style": "wide", "eye_style": "dots", "hair": "none", "hat": "chef", "neck": "none", "extra": "apron", "prop": "pan"},
        "colours": {"hat": "white", "extra": "primary", "prop": "amber", "neck": "primary", "hair": "ink"},
        "background": "kitchen", "expression": "laugh", "pose": "hold", "tags": ("explain", "cheer", "thumbs_up"),
    },
    "courier": {
        "fa": "پیک", "hint": "کلاهِ لبه‌دار و کوله‌پشتیِ برند، بسته؛ برای ارسال و سفارش",
        "look": {"head_style": "round", "eye_style": "round", "hair": "none", "hat": "cap", "neck": "none", "extra": "backpack", "prop": "box"},
        "colours": {"hat": "primary", "extra": "primary", "prop": "kraft", "neck": "primary", "hair": "ink"},
        "background": "brand", "expression": "happy", "pose": "run_a", "tags": ("greet", "exercise", "thumbs_up"),
    },
    "advisor": {
        "fa": "مشاور", "hint": "عینک و کراواتِ برند، تبلت؛ برای پاسخ به پرسش و راهنمایی",
        "look": {"head_style": "tall", "eye_style": "round", "hair": "bob", "hat": "none", "neck": "tie", "extra": "glasses", "prop": "tablet"},
        "colours": {"neck": "primary", "prop": "primary", "extra": "limb", "hat": "primary", "hair": "ink"},
        "background": "brand", "expression": "happy", "pose": "hold", "tags": ("explain", "thinking", "point", "warn"),
    },
}
DEFAULT_ROLE = "coach"


def _hsl(hx: str) -> tuple[float, float, float]:
    r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _from_hsl(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _dist(a: str, b: str) -> float:
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2 for i in (1, 3, 5)) ** 0.5


def clean_colours(colours) -> list[str]:
    out = []
    for c in colours or []:
        if isinstance(c, str):
            c = c.strip().lower()
            if len(c) == 4 and c[0] == "#":
                c = "#" + "".join(ch * 2 for ch in c[1:])
            if len(c) == 7 and c[0] == "#" and all(ch in "0123456789abcdef" for ch in c[1:]) and c not in out:
                out.append(c)
    return out


def brand_palette(colours) -> dict[str, str]:
    """رنگ‌های برند ⇒ نقش‌های ماسکوت: primary (لوازم)، secondary، limb (دست و پا؛ تیره)، ink (خطِ دور و مو)."""
    cs = clean_colours(colours)
    primary = cs[0] if cs else DEFAULT_PRIMARY
    secondary = cs[1] if len(cs) > 1 else None
    h, s, l = _hsl(secondary or primary)
    limb = _from_hsl(h, max(s, 0.35), min(max(l, 0.20), 0.38))             # دست و پا همیشه به‌اندازهٔ کافی تیره تا روی زمینهٔ روشن بخواند
    if _dist(limb, primary) < 40:                                           # دو رنگ تقریباً یکی‌اند ⇒ دست و پا را تیره‌تر کن
        limb = _from_hsl(h, max(s, 0.4), 0.22)
    ph, ps, pl = _hsl(primary)
    if pl > 0.82:                                                           # رنگِ اصلیِ بسیار روشن روی سفید دیده نمی‌شود
        primary = _from_hsl(ph, max(ps, 0.5), 0.5)
    ink = _from_hsl(h, 0.45, 0.12)                                          # تیره و کم‌اشباع ⇒ «رنگِ امضا» حساب نمی‌شود
    return {"primary": primary, "secondary": secondary or limb, "limb": limb, "ink": ink, "white": "#ffffff", "amber": "#e8a22b", "kraft": "#b0763c"}


def spec_from_brand(role: str, colours, name: str = "", *, logo: bool = False) -> dict:
    """ماسکوتِ یک نقش با رنگ‌های برند. ⇒ spec نرمال‌شده (S.normalize)."""
    r = ROLES.get(role) or ROLES[DEFAULT_ROLE]
    pal = brand_palette(colours)
    look = r["look"]
    cm = r["colours"]
    spec = {
        "name": name or r["fa"], "limb_colour": pal["limb"], "head_fill": "#ffffff", "outline": pal["ink"], "line_width": 17, **look,
        "hat_colour": pal[cm.get("hat", "primary")], "hair_colour": pal[cm.get("hair", "ink")], "neck_colour": pal[cm.get("neck", "primary")],
        "extra_colour": pal[cm.get("extra", "primary")], "prop_colour": pal[cm.get("prop", "primary")],
        "logo": "chest" if logo else "none",
    }
    return S.normalize(spec, name=name or r["fa"])


def roles_public() -> list[dict]:
    return [{"key": k, "fa": v["fa"], "hint": v["hint"], "background": v["background"], "expression": v["expression"], "pose": v["pose"], "tags": list(v["tags"])}
            for k, v in ROLES.items()]
