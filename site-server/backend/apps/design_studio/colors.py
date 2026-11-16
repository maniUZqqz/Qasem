"""رنگ: ابزارهای کوچکِ هگز، تباینِ WCAG و ساختنِ «پالتِ نقش‌ها» از کیتِ برند + «تمِ سبک» (looks).

پالت = {bg، surface، text، muted، primary، on_primary، secondary، accent، line، dark، light، danger}. متنِ روی هر زمینه باید تباینِ ≥ ۴٫۵
داشته باشد؛ ``ensure_contrast`` رنگِ متن را تا آن‌جا تیره/روشن می‌کند (همان قاعدهٔ سایت‌ساز).
"""
from __future__ import annotations

import re

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex(v) -> bool:
    return isinstance(v, str) and bool(HEX_RE.match(v))


def norm(v, default="#000000") -> str:
    if isinstance(v, str):
        s = v.strip().lower()
        if re.fullmatch(r"#[0-9a-f]{3}", s):
            s = "#" + "".join(c * 2 for c in s[1:])
        if HEX_RE.match(s):
            return s
    return default


def rgb(h: str) -> tuple[int, int, int]:
    h = norm(h).lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(r, g, b) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(x)))) for x in (r, g, b))


def mix(a: str, b: str, t: float) -> str:
    """t=0 ⇒ a، t=1 ⇒ b."""
    ra, rb = rgb(a), rgb(b)
    return to_hex(*[x + (y - x) * t for x, y in zip(ra, rb)])


def lighten(c: str, t: float) -> str:
    return mix(c, "#ffffff", t)


def darken(c: str, t: float) -> str:
    return mix(c, "#000000", t)


def luminance(c: str) -> float:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(x) for x in rgb(c))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def on_color(bg: str) -> str:
    """سفید یا مشکیِ نرم، هرکدام که روی bg تباینِ بیشتری دارد."""
    return "#ffffff" if contrast("#ffffff", bg) >= contrast("#111827", bg) else "#111827"


def ensure_contrast(fg: str, bg: str, minimum: float = 4.5) -> str:
    if contrast(fg, bg) >= minimum:
        return fg
    target = "#000000" if luminance(bg) > 0.4 else "#ffffff"
    for step in range(1, 21):
        cand = mix(fg, target, step * 0.05)
        if contrast(cand, bg) >= minimum:
            return cand
    return on_color(bg)


def rgba(c: str, a: float) -> tuple[int, int, int, int]:
    r, g, b = rgb(c)
    return r, g, b, max(0, min(255, int(round(a * 255))))


def role_palette(colors: list[str] | dict | None, look: dict | None = None, dark: bool = False) -> dict:
    """کیتِ برند (فهرست یا دیکشنریِ رنگ) + تمِ سبک (اختیاری) ⇒ پالتِ نقش‌ها.

    فهرستِ برند: [اصلی، ثانویه، روشن/تأکید، زمینه، متن]. دیکشنری: primary/secondary/accent/background/text. تمِ سبک
    (looks.THEMES[..]['palette'] = [زمینه، اصلی، ثانویه، تأکید، سایه، هایلایت]) فقط وقتی داده شده جای رنگ‌های برند را می‌گیرد.
    """
    base: dict[str, str] = {}
    if isinstance(colors, dict):
        for k_src, k in (("primary", "primary"), ("secondary", "secondary"), ("accent", "accent"),
                         ("background", "bg"), ("bg", "bg"), ("text", "text")):
            if is_hex(colors.get(k_src)):
                base[k] = norm(colors[k_src])
    elif isinstance(colors, (list, tuple)):
        cs = [norm(c) for c in colors if is_hex(c)]
        for k, i in (("primary", 0), ("secondary", 1), ("accent", 2), ("bg", 3), ("text", 4)):
            if i < len(cs):
                base[k] = cs[i]
    if look and isinstance(look.get("palette"), (list, tuple)) and len(look["palette"]) >= 4:
        p = [norm(c) for c in look["palette"]]
        base = {"bg": p[0], "primary": p[1], "secondary": p[2], "accent": p[3]}
        if len(p) > 5:
            base["highlight"] = p[5]
    primary = base.get("primary", "#126f85")
    secondary = base.get("secondary") or darken(primary, 0.35)
    bg = base.get("bg", "#f7faff")
    if luminance(bg) < 0.35 and not dark:                    # تمِ تیره ⇒ روشن‌ترین رنگ را زمینهٔ صفحه نکن؛ صفحه همچنان روشن بماند
        surface_dark = bg
        bg = lighten(primary, 0.93)
    else:
        surface_dark = None
    accent = base.get("accent") or lighten(primary, 0.85)
    text = ensure_contrast(base.get("text") or "#1b2b45", bg)
    if dark:
        bg_d = surface_dark or darken(secondary, 0.55)
        return {"bg": bg_d, "surface": lighten(bg_d, 0.08), "text": "#f1f5f9", "muted": "#a8b4c6", "primary": ensure_contrast(lighten(primary, 0.15), bg_d, 3.0),
                "on_primary": on_color(lighten(primary, 0.15)), "secondary": secondary, "accent": accent, "line": lighten(bg_d, 0.18),
                "dark": darken(bg_d, 0.4), "light": "#ffffff", "danger": "#ef4444"}
    on_p = on_color(primary)
    return {"bg": bg, "surface": "#ffffff", "text": text, "muted": ensure_contrast(mix(text, bg, 0.45), bg, 4.5), "primary": primary,
            "on_primary": on_p, "secondary": secondary, "accent": accent, "line": mix(bg, text, 0.12), "dark": darken(secondary, 0.25),
            "light": lighten(primary, 0.92), "danger": "#dc2626"}
