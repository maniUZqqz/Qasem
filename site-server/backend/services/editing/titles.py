"""Titles: Persian/English text clips rendered through libass. §23.4

The old text track drew with `drawtext`: no bidi, no wrapping, one style. Persian is the point of this panel, so
every text clip is now an ASS dialogue — libass shapes Arabic-script text and reorders mixed Persian/English/digits
correctly, wraps long lines inside the frame, and gives strokes, shadows, background boxes and animation for free.

**Two jobs.** `clean` turns whatever the browser sent into one fully-populated, clamped dict (the project JSON
stores these). `build_ass` turns a list of cleaned dicts into ONE ASS document that the renderer feeds to the `ass`
filter (see `ass_filter`). Nothing else in the editor knows ASS.

**Sizes are fractions of the frame.** A clip says «size 6» = 6 % of the frame height; the ASS is generated against the
real render size (PlayRes = width x height), so the same project renders identically at 360p preview and 1080p export.
ASS's own `Fontsize` is the font's *line* height, not its em, and the ratio differs per font (Vazirmatn's lines are
1.7 em tall): `FONTS[..]["line"]` holds the measured ratio so `size` keeps meaning «em as % of frame height», the
same thing `drawtext`'s fontsize and CSS font-size mean — which is what lets the browser preview match.

**Animation is piecewise-linear.** Every in/out preset is a function `state(t)` (opacity, scale, offset, blur,
revealed characters). The clip's time is cut at the preset's breakpoints (and at karaoke word boundaries) and each
slice becomes one dialogue whose `\\move`/`\\t` interpolates linearly between the slice's two states. That gives
ease-out slides, an overshooting pop, typewriter reveal and karaoke highlight with one mechanism — and no tag soup
that libass versions disagree about.

**User text can never inject ASS.** Braces and backslashes are escaped; `\\N`-style sequences cannot be typed in.
"""
from __future__ import annotations

import functools
import math
import re
from pathlib import Path

from .errors import TimelineError

#: Bundled fonts (Vazirmatn Regular/Bold). Passed to libass as `fontsdir`; the other families come from fontconfig.
FONTS_DIR = Path(__file__).resolve().parents[1] / "imaging" / "fonts"

#: A second line (`text2`) is this fraction of the first line's size.
LINE2 = 0.62

# ----------------------------------------------------------------- catalogue

#: key -> what the panel offers. `family` is the name libass/fontconfig resolves; `line` is ASS Fontsize / em
#: (measured by rendering a capital H with libass and with Pillow — see the tests); `bold` says whether the Bold
#: flag is meaningful (the Black/Light cuts are separate families).
FONTS: dict[str, dict] = {
    "vazir": {"title": "وزیرمتن", "family": "Vazirmatn", "css": "Vazirmatn, 'Vazir', Tahoma, sans-serif",
              "css_weight": 400, "bold": True, "line": 1.713, "file": "Vazirmatn-Bold.ttf", "weights": ["regular", "bold"]},
    "vazir_black": {"title": "وزیرمتن سیاه", "family": "Vazirmatn Black", "css": "Vazirmatn, 'Vazir', Tahoma, sans-serif",
                    "css_weight": 900, "bold": False, "line": 1.713, "file": "Vazirmatn-Bold.ttf", "weights": ["black"]},
    "vazir_light": {"title": "وزیرمتن نازک", "family": "Vazirmatn Light", "css": "Vazirmatn, 'Vazir', Tahoma, sans-serif",
                    "css_weight": 300, "bold": False, "line": 1.711, "file": "Vazirmatn-Regular.ttf", "weights": ["light"]},
    "lato": {"title": "Lato", "family": "Lato", "css": "Lato, 'Helvetica Neue', Arial, sans-serif",
             "css_weight": 400, "bold": True, "line": 1.203, "file": "", "weights": ["regular", "bold"]},
    "dejavu": {"title": "DejaVu Sans", "family": "DejaVu Sans", "css": "'DejaVu Sans', Verdana, sans-serif",
               "css_weight": 400, "bold": True, "line": 1.166, "file": "", "weights": ["regular", "bold"]},
    "dejavu_serif": {"title": "DejaVu Serif", "family": "DejaVu Serif", "css": "'DejaVu Serif', Georgia, serif",
                     "css_weight": 400, "bold": True, "line": 1.166, "file": "", "weights": ["regular", "bold"]},
    "liberation": {"title": "Liberation Sans", "family": "Liberation Sans", "css": "'Liberation Sans', Arial, sans-serif",
                   "css_weight": 400, "bold": True, "line": 1.119, "file": "", "weights": ["regular", "bold"]},
    "liberation_serif": {"title": "Liberation Serif", "family": "Liberation Serif", "css": "'Liberation Serif', 'Times New Roman', serif",
                         "css_weight": 400, "bold": True, "line": 1.110, "file": "", "weights": ["regular", "bold"]},
    "mono": {"title": "DejaVu Mono", "family": "DejaVu Sans Mono", "css": "'DejaVu Sans Mono', Consolas, monospace",
             "css_weight": 400, "bold": True, "line": 1.166, "file": "", "weights": ["regular", "bold"]},
}

ANIMATIONS_IN: dict[str, str] = {
    "none": "بدون", "fade": "محو شدن", "slide_up": "ورود از پایین", "slide_down": "ورود از بالا",
    "slide_left": "ورود از راست", "slide_right": "ورود از چپ", "pop": "جهش (پاپ)", "zoom": "زوم",
    "typewriter": "ماشین‌تحریر", "blur": "محو و واضح",
}
ANIMATIONS_OUT: dict[str, str] = {
    "none": "بدون", "fade": "محو شدن", "slide_up": "خروج به بالا", "slide_down": "خروج به پایین",
    "slide_left": "خروج به چپ", "slide_right": "خروج به راست", "pop": "جمع شدن", "zoom": "زوم",
    "typewriter": "پاک شدن حرف‌به‌حرف", "blur": "محو و تار",
}
HL_MODES: dict[str, str] = {"color": "رنگِ کلمه", "scale": "رنگ و بزرگ‌نمایی", "box": "هایلایت (ماژیک)"}
ALIGNS: dict[str, str] = {"right": "راست‌چین", "center": "وسط‌چین", "left": "چپ‌چین"}

#: What each template changes when the clip does not say otherwise. (An explicit key in the clip always wins.)
_TEMPLATE_DEFAULTS: dict[str, dict] = {
    "plain": {},
    "lower_bar": {"size": 4.8, "y": 0.80, "align": "auto", "box": False, "shadow": 14, "duration": 4.0, "anim_out": "fade"},
    "lower_box": {"size": 4.6, "y": 0.80, "align": "auto", "box": False, "box_pad": 24, "duration": 4.0, "anim_out": "fade"},
    "lower_line": {"size": 5.0, "y": 0.80, "align": "auto", "box": False, "shadow": 18, "duration": 4.0, "anim_out": "fade"},
    "title_center": {"size": 9.0, "y": 0.5, "box": False, "shadow": 14, "anim_in": "zoom", "anim_out": "fade", "duration": 3.5},
    "title_big": {"size": 13.0, "y": 0.5, "box": False, "stroke": 10, "shadow": 16, "anim_in": "pop", "anim_out": "fade",
                  "duration": 3.0},
    "quote": {"size": 6.0, "y": 0.5, "box": False, "italic": True, "bold": False, "shadow": 12, "anim_in": "fade",
              "anim_out": "fade", "duration": 4.0},
    "sticker": {"size": 7.0, "y": 0.35, "rotation": -4.0, "box": True, "box_color": "#ffd400", "box_opacity": 1.0,
                "color": "#111111", "box_pad": 28, "anim_in": "pop", "anim_out": "fade", "duration": 3.0},
    "bubble": {"size": 5.4, "y": 0.62, "box": True, "box_color": "#ffffff", "box_opacity": 0.95, "color": "#111111",
               "box_pad": 34, "bold": False, "anim_in": "pop", "anim_out": "fade", "duration": 3.5},
}

TEMPLATES: dict[str, dict] = {
    "plain": {"title": "ساده", "hint": "یک متنِ ساده با سبکِ دلخواه"},
    "lower_bar": {"title": "زیرنویسِ معرفی — نوار", "hint": "عنوان + زیرعنوان با نوارِ رنگی کنارِ متن"},
    "lower_box": {"title": "زیرنویسِ معرفی — کادر", "hint": "عنوان در کادرِ رنگی و زیرعنوان در کادرِ تیره"},
    "lower_line": {"title": "زیرنویسِ معرفی — خط", "hint": "عنوان و زیرعنوان با خطِ باریکِ رنگی"},
    "title_center": {"title": "تیترِ وسط", "hint": "تیتر درشت با زیرعنوان، ورودِ زوم"},
    "title_big": {"title": "تیترِ بزرگ", "hint": "متنِ خیلی درشت با لبه و سایه، ورودِ جهشی"},
    "quote": {"title": "نقل‌قول", "hint": "متنِ مورب با علامتِ نقل‌قول و نامِ گوینده"},
    "sticker": {"title": "استیکر", "hint": "برچسبِ زردِ کمی کج"},
    "bubble": {"title": "حباب", "hint": "حبابِ سفیدِ گفتگو"},
}
for _k, _v in TEMPLATES.items():
    _v["defaults"] = _TEMPLATE_DEFAULTS[_k]

_BASE: dict = {
    "text": "", "text2": "", "at": 0.0, "duration": 2.5, "label": "", "template": "plain", "font": "vazir", "size": 6.0,
    "bold": True, "italic": False, "color": "#ffffff", "opacity": 1.0, "stroke_color": "#000000", "stroke": 0.0,
    "shadow": 0.0, "shadow_color": "#000000", "box": True, "box_color": "#000000", "box_opacity": 0.45, "box_pad": 20.0,
    "align": "center", "position": "bottom", "x": None, "y": None, "rotation": 0.0, "scale": 1.0, "anim_in": "none",
    "anim_out": "none", "anim_dur": 0.4, "words": [], "hl_color": "#ffd400", "hl_mode": "color", "caption": False,
    "accent": "#ff3d71",
}
_POSITION_Y = {"top": 0.12, "middle": 0.5, "bottom": 0.86}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX3 = re.compile(r"^#[0-9a-fA-F]{3}$")
_RTL = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")
_STRONG = re.compile("[A-Za-z\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")


def _num(value, lo, hi, default):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, x))


def _hex(value, default):
    text = str(value or "").strip()
    if _HEX.match(text):
        return text.lower()
    if _HEX3.match(text):
        return "#" + "".join(ch * 2 for ch in text[1:]).lower()
    return default


def _clean_text(value, limit: int) -> str:
    """Control characters out, line breaks normalised to \n, tabs to spaces, length capped."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    text = text.replace("\t", " ")
    text = "".join(ch for ch in text if ch == "\n" or ch >= " " and ch != "\x7f")
    return text[:limit]


def is_rtl(text: str) -> bool:
    """First strong LETTER decides — the rule the browser's `dir=auto` uses (digits are weak: «۱۲۳ abc» is LTR)."""
    for ch in text or "":
        if ch.isalpha():
            return bool(_RTL.match(ch))
    return False


def plain_text(item: dict) -> str:
    """One line of the clip's text, for the editor's clip label."""
    parts = [str(item.get("text") or ""), str(item.get("text2") or "")]
    return " — ".join(" ".join(p.split()) for p in parts if p.strip())


def clean(raw: dict, index: int = 0) -> dict:
    """One text clip from the browser → every key, clamped. Raises `TimelineError` for an empty text.

    Layers, lowest first: the built-in defaults, the template's defaults, what the clip itself says.
    """
    if not isinstance(raw, dict):
        raise TimelineError("متنِ نامعتبر.")
    template = str(raw.get("template") or "plain")
    if template not in TEMPLATES:
        template = "plain"
    d = dict(_BASE)
    d.update(_TEMPLATE_DEFAULTS[template])

    def pick(key):
        value = raw.get(key)
        return d[key] if value is None else value

    text = _clean_text(raw.get("text"), 400)
    text2 = _clean_text(raw.get("text2"), 200)
    label = str(raw.get("label") or "")[:60]
    where = label or f"متن {index + 1}"
    if not text.strip() and not text2.strip():
        raise TimelineError(f"{where}: متن خالی است.")

    out: dict = {"text": text, "text2": text2, "template": template}
    out["at"] = _num(raw.get("at"), 0, 86400, 0.0)
    out["duration"] = _num(pick("duration"), 0.1, 3600, 2.5)
    out["label"] = label or plain_text({"text": text, "text2": text2})[:20]
    font = str(pick("font"))
    out["font"] = font if font in FONTS else "vazir"
    out["size"] = _num(pick("size"), 1, 30, 6.0)
    out["bold"] = bool(pick("bold"))
    out["italic"] = bool(pick("italic"))
    out["color"] = _hex(pick("color"), "#ffffff")
    out["opacity"] = _num(pick("opacity"), 0.05, 1, 1.0)
    out["stroke_color"] = _hex(pick("stroke_color"), "#000000")
    out["stroke"] = _num(pick("stroke"), 0, 100, 0.0)
    out["shadow"] = _num(pick("shadow"), 0, 100, 0.0)
    out["shadow_color"] = _hex(pick("shadow_color"), "#000000")
    out["box"] = bool(pick("box"))
    out["box_color"] = _hex(pick("box_color"), "#000000")
    out["box_opacity"] = _num(pick("box_opacity"), 0, 1, 0.45)
    out["box_pad"] = _num(pick("box_pad"), 0, 100, 20.0)
    align = str(pick("align"))
    if align not in ALIGNS:                      # "auto" (lower-thirds): follow the script of the first line
        align = ("right" if is_rtl(text or text2) else "left") if align == "auto" else "center"
    out["align"] = align
    position = str(raw.get("position") or "bottom")
    out["position"] = position if position in _POSITION_Y else "bottom"
    out["x"] = _num(raw.get("x"), 0, 1, 0.5)
    if raw.get("y") is not None:
        out["y"] = _num(raw.get("y"), 0, 1, 0.86)
    elif raw.get("position") in _POSITION_Y:
        out["y"] = _POSITION_Y[position]
    else:
        out["y"] = _num(d["y"], 0, 1, 0.86) if d["y"] is not None else _POSITION_Y[position]
    out["rotation"] = _num(pick("rotation"), -180, 180, 0.0)
    out["scale"] = _num(pick("scale"), 0.1, 4, 1.0)
    anim_in = str(raw.get("anim_in") or d["anim_in"])
    if raw.get("anim_in") is None and template.startswith("lower_"):
        anim_in = {"right": "slide_left", "left": "slide_right"}.get(align, "slide_up")
    out["anim_in"] = anim_in if anim_in in ANIMATIONS_IN else "none"
    anim_out = str(pick("anim_out"))
    out["anim_out"] = anim_out if anim_out in ANIMATIONS_OUT else "none"
    out["anim_dur"] = _num(pick("anim_dur"), 0.1, 2.0, 0.4)
    out["hl_color"] = _hex(pick("hl_color"), "#ffd400")
    hl_mode = str(pick("hl_mode"))
    out["hl_mode"] = hl_mode if hl_mode in HL_MODES else "color"
    out["caption"] = bool(pick("caption"))
    out["accent"] = _hex(pick("accent"), "#ff3d71")
    out["words"] = _clean_words(raw.get("words"), out["duration"])
    out["path"] = _clean_path(raw.get("path"), out["duration"])
    return out


def _clean_words(raw, duration: float) -> list[dict]:
    words = []
    for item in (raw if isinstance(raw, list) else [])[:400]:
        if not isinstance(item, dict):
            continue
        w = _clean_text(item.get("w", item.get("word", item.get("text"))), 60).replace("\n", " ").strip()
        if not w:
            continue
        s = _num(item.get("s", item.get("start")), 0, 3600, None)
        e = _num(item.get("e", item.get("end")), 0, 3600, None)
        if s is None or e is None:
            continue
        s = min(s, duration)
        e = max(s, min(e, duration))
        words.append({"w": w, "s": round(s, 3), "e": round(e, 3)})
    words.sort(key=lambda w: w["s"])
    return words


MAX_PATH = 80


def _clean_path(raw, duration: float) -> list[dict]:
    """A title that follows a motion track: [{t, dx, dy}] — seconds from the clip's start and the displacement of the
    anchor as FRACTIONS of the frame. Linear between points (the tracker's samples are close together)."""
    pts = []
    for item in (raw if isinstance(raw, list) else [])[: MAX_PATH * 2]:
        if not isinstance(item, dict):
            continue
        t = _num(item.get("t"), 0, 3600, None)
        dx, dy = _num(item.get("dx"), -2, 2, None), _num(item.get("dy"), -2, 2, None)
        if t is None or dx is None or dy is None:
            continue
        pts.append({"t": round(min(t, duration), 3), "dx": round(dx, 5), "dy": round(dy, 5)})
    pts.sort(key=lambda p: p["t"])
    out: list[dict] = []
    for p in pts:
        if out and abs(out[-1]["t"] - p["t"]) < 0.005:
            out[-1] = p
        else:
            out.append(p)
    return out[:MAX_PATH] if len(out) >= 2 else []


def path_at(path: list[dict], t: float) -> tuple[float, float]:
    """(dx, dy) fractions at second `t` of the clip (0, 0 without a path)."""
    if not path:
        return 0.0, 0.0
    if t <= path[0]["t"]:
        return path[0]["dx"], path[0]["dy"]
    for a, b in zip(path, path[1:]):
        if t < b["t"]:
            u = (t - a["t"]) / max(1e-9, b["t"] - a["t"])
            return a["dx"] + (b["dx"] - a["dx"]) * u, a["dy"] + (b["dy"] - a["dy"]) * u
    return path[-1]["dx"], path[-1]["dy"]


# ---------------------------------------------------------------- ASS pieces

def _esc(text: str) -> str:
    """Text → ASS text that carries exactly these characters and no tags."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\u200b")        # a backslash followed by N/n/h would be an escape; a zero-width space breaks it
        elif ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ch == "\n":
            out.append("\\N")
        else:
            out.append(ch)
    return "".join(out)


def _c(color: str) -> str:
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _a(opacity: float) -> str:
    """ASS alpha (00 opaque … FF transparent) for an opacity 0..1."""
    return "&H%02X&" % int(round(255 * (1 - max(0.0, min(1.0, opacity)))))


def _ts(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _f(value: float, digits: int = 2) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


FONTS_TOKEN = "__FONTSDIR__"


def ass_filter(path, *, portable: bool = False) -> str:
    """The `ass` filter for a script file, with the bundled fonts directory (fontconfig supplies the rest).
    `portable` leaves a token (`FONTS_TOKEN`) for the fonts folder: a render on another computer (the processing node)
    puts its own copy of the same fonts there, so the titles are laid out with the same glyphs everywhere."""
    from services.video.ffmpeg import filter_path

    fonts = filter_path(FONTS_TOKEN) if portable else filter_path(FONTS_DIR)
    return f"ass=filename={filter_path(path)}:fontsdir={fonts}"


# ------------------------------------------------------------------ geometry

@functools.lru_cache(maxsize=64)
def _pil_font(path: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(path, size)


def _text_width(text: str, em: float, font: dict) -> float:
    """Width of one line in px. Pillow+raqm shapes Arabic script, so Persian measures like libass draws it;
    without the font file we fall back to half an em per character."""
    for candidate in (FONTS_DIR / font["file"],) if font.get("file") else ():
        if candidate.is_file():
            try:
                return float(_pil_font(str(candidate), max(8, int(round(em)))).getlength(text))
            except Exception:  # noqa: BLE001 — no raqm, odd glyphs
                break
    return len(text) * em * 0.52


def estimate_lines(text: str, em: float, width: float, font: dict) -> int:
    """How many lines libass will break `text` into at `width` px (greedy; good enough for sizing a bar)."""
    count = 0
    for paragraph in (text or "").split("\n"):
        line = ""
        n = 1
        for word in paragraph.split():
            trial = (line + " " + word).strip()
            if line and _text_width(trial, em, font) > width:
                n += 1
                line = word
            else:
                line = trial
        count += n
    return max(1, count)


def _geometry(it: dict, W: int, H: int) -> dict:
    """Where the clip's text block sits: wrap region, anchor, alignment number, the estimated block height, and the
    anchor's y pulled inside the frame (a bottom caption that wraps to four lines would otherwise hang off the edge)."""
    font = FONTS[it["font"]]
    em = it["size"] / 100.0 * H
    x, y = it["x"] * W, it["y"] * H
    region = min(0.88, 2 * min(it["x"], 1 - it["x"]) * 0.96) * W
    left, right = x - region / 2, x + region / 2
    template = it["template"]
    bar_w = max(3.0, em * 0.16)
    gap = em * 0.5
    has_bar = template == "lower_bar"
    if has_bar:
        if it["align"] == "right":
            right -= bar_w + gap
        else:
            left += bar_w + gap
    anchor = {"left": left, "center": (left + right) / 2, "right": right}[it["align"]]
    boxed = bool(it["box"] or template == "lower_box")
    pad = em * it["box_pad"] / 100.0 if boxed else 0.0
    g = {"font": font, "em": em, "em2": em * LINE2, "x": x, "y": y, "left": left, "right": right,
         "region": region, "anchor_x": anchor, "an": {"left": 4, "center": 5, "right": 6}[it["align"]],
         "bar_w": bar_w, "gap": gap, "has_bar": has_bar, "wrap": max(20.0, right - left - 2 * pad), "pad": pad}
    g["block_h"] = _block_height(it, g)
    half = g["block_h"] / 2 + pad + 0.01 * H
    lo, hi = half + 0.02 * H, H - half - 0.02 * H
    g["y"] = min(max(y, lo), hi) if lo <= hi else H / 2.0
    return g


def _block_height(it: dict, g: dict) -> float:
    """Estimated height of the whole text block (lines x line pitch), for sizing decorations and keeping it in frame."""
    font = g["font"]
    n1 = estimate_lines(it["text"], g["em"], g["wrap"], font) if it["text"].strip() else 0
    n2 = estimate_lines(it["text2"], g["em2"], g["wrap"], font) if it["text2"].strip() else 0
    return n1 * g["em"] * font["line"] + n2 * g["em2"] * font["line"]


# ----------------------------------------------------------------- animation

def _ease_out(u: float) -> float:
    return 1 - (1 - u) ** 3


def _ease_in(u: float) -> float:
    return u ** 3


def _back_out(u: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2


_DIRS = {"slide_up": (0, -1), "slide_down": (0, 1), "slide_left": (-1, 0), "slide_right": (1, 0)}


def _apply(kind: str, u: float, mode: str, W: int, H: int) -> dict:
    """The change one animation makes at progress u (0..1 of its own window)."""
    st = {"alpha": 1.0, "scale": 1.0, "dx": 0.0, "dy": 0.0, "blur": 0.0, "reveal": 1.0}
    entering = mode == "in"
    p = _ease_out(u) if entering else _ease_in(u)        # 0 → 1: arrived / departed
    gone = (1 - p) if entering else p                      # how far from the resting state
    if kind == "fade":
        st["alpha"] = 1 - gone
    elif kind in _DIRS:
        dirx, diry = _DIRS[kind]
        sign = -1 if entering else 1            # in: start behind the direction of travel; out: end ahead of it
        st["dx"], st["dy"] = sign * dirx * 0.10 * W * gone, sign * diry * 0.06 * H * gone
        st["alpha"] = 1 - gone
    elif kind == "pop":
        if entering:
            st["scale"] = 0.45 + 0.55 * _back_out(u)
            st["alpha"] = min(1.0, u * 3)
        else:
            st["scale"] = 1 - 0.4 * p
            st["alpha"] = 1 - p
    elif kind == "zoom":
        st["scale"] = 1 + (0.6 * gone if entering else 0.4 * p)
        st["alpha"] = 1 - gone
    elif kind == "blur":
        st["blur"] = gone * 0.008 * H
        st["alpha"] = 1 - gone
    elif kind == "typewriter":
        st["reveal"] = u if entering else 1 - u
    return st


def _windows(it: dict, n_chars: int) -> tuple[float, float]:
    """(in, out) animation lengths, never eating more than 90 % of the clip together."""
    dur = it["duration"]
    d_in = it["anim_dur"] if it["anim_in"] != "none" else 0.0
    d_out = it["anim_dur"] if it["anim_out"] != "none" else 0.0
    if it["anim_in"] == "typewriter":
        d_in = max(d_in, 0.045 * n_chars)
    if d_in + d_out > dur * 0.9:
        k = dur * 0.9 / (d_in + d_out)
        d_in, d_out = d_in * k, d_out * k
    return d_in, d_out


def _state(it: dict, t: float, d_in: float, d_out: float, W: int, H: int) -> dict:
    st = {"alpha": 1.0, "scale": 1.0, "dx": 0.0, "dy": 0.0, "blur": 0.0, "reveal": 1.0}
    dur = it["duration"]
    parts = []
    if d_in > 0 and t < d_in:
        parts.append(_apply(it["anim_in"], max(0.0, t / d_in), "in", W, H))
    if d_out > 0 and t > dur - d_out:
        parts.append(_apply(it["anim_out"], min(1.0, (t - (dur - d_out)) / d_out), "out", W, H))
    for part in parts:
        st["alpha"] *= part["alpha"]
        st["scale"] *= part["scale"]
        st["dx"] += part["dx"]
        st["dy"] += part["dy"]
        st["blur"] = max(st["blur"], part["blur"])
        st["reveal"] = min(st["reveal"], part["reveal"])
    if it.get("path"):
        fx, fy = path_at(it["path"], t)
        st["dx"] += fx * W
        st["dy"] += fy * H
    return st


# ------------------------------------------------------------- karaoke words

def _word_plan(it: dict) -> tuple[str, list[tuple[float, float]]]:
    """(title text to show, [(active_from, active_to)] per word). With `words`, the text is mapped word by word; when
    the user edited the text so the counts differ, the words' own spelling wins (their timing is what we have)."""
    text = it["text"]
    words = it["words"]
    if not words:
        return text, []
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    if len(tokens) != len(words):
        text = " ".join(w["w"] for w in words)
    spans = []
    for i, w in enumerate(words):
        nxt = words[i + 1]["s"] if i + 1 < len(words) else it["duration"]
        end = max(w["s"] + 0.05, min(nxt, w["e"] + 0.25))
        spans.append((w["s"], end))
    return text, spans


def _pieces(text: str, text2: str, fs2: float, spans) -> tuple[list, int]:
    """The clip's text as pieces: ("t", text, word_index|None) | ("nl",) | ("ctl", tags). Returns (pieces, n_chars)."""
    pieces: list = []
    widx = 0
    chars = 0
    for li, line in enumerate(text.split("\n")):
        if li:
            pieces.append(("nl",))
        for part in re.split(r"(\s+)", line):
            if not part:
                continue
            if part.isspace():
                pieces.append(("t", " ", None))
                chars += 1
            else:
                pieces.append(("t", part, widx if spans else None))
                widx += 1
                chars += len(part)
    if text2.strip():
        pieces.append(("nl",))
        pieces.append(("ctl", "line2"))
        for li, line in enumerate(text2.split("\n")):
            if li:
                pieces.append(("nl",))
            pieces.append(("t", " ".join(line.split()), None))
            chars += len(line)
    return pieces, chars


def _render(pieces, *, reveal_chars: int | None, active: int | None, hl_open: str, hl_close: str, hide: str,
            line2_tags) -> str:
    """Pieces → ASS text. `reveal_chars` hides the rest (typewriter); `active` marks one word (karaoke)."""
    out: list[str] = []
    shown = 0
    cut = False
    for piece in pieces:
        kind = piece[0]
        if kind == "nl":
            out.append("\\N")
        elif kind == "ctl":
            if piece[1] == "line2":
                out.append(line2_tags)
            else:
                out.append(piece[1])
        else:
            text, widx = piece[1], piece[2]
            if cut:
                out.append(_esc(text))
                continue
            if reveal_chars is not None and shown + len(text) > reveal_chars:
                keep = max(0, reveal_chars - shown)
                if keep:
                    out.append(_esc(text[:keep]))
                out.append(hide)
                out.append(_esc(text[keep:]))
                cut = True
                continue
            shown += len(text)
            if active is not None and widx == active:
                out.append(hl_open + _esc(text) + hl_close)
            else:
                out.append(_esc(text))
    return "".join(out)


# ---------------------------------------------------------------- the writer

_HEADER = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
    "YCbCr Matrix: TV.709\n\n[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
    "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
    "MarginV, Encoding\n"
)
_EVENTS = "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"


def _style(name: str, it: dict, g: dict, *, box_layer: bool) -> str:
    font = g["font"]
    bold = -1 if (it["bold"] and font["bold"]) else 0
    outline = g["em"] * it["stroke"] / 100.0
    shadow = g["em"] * it["shadow"] / 100.0 * 0.6
    pad = g["em"] * it["box_pad"] / 100.0
    if box_layer:
        border, out_w, shad = 3, pad, 0
    else:
        border, out_w, shad = 1, outline, shadow
    return (f"Style: {name},{font['family']},{_f(g['em'] * font['line'])},{_c(it['color'])},{_c(it['color'])},"
            f"{_c(it['stroke_color'])},{_c(it['shadow_color'])},{bold},{-1 if it['italic'] else 0},0,0,100,100,0,0,"
            f"{border},{_f(out_w)},{_f(shad)},{g['an']},0,0,0,-1")


def _rect(x: float, y: float, w: float, h: float) -> str:
    return f"m 0 0 l {_f(w, 1)} 0 {_f(w, 1)} {_f(h, 1)} 0 {_f(h, 1)}"


def _item_ass(n: int, it: dict, W: int, H: int) -> tuple[list[str], list[str]]:
    g = _geometry(it, W, H)
    em, font = g["em"], g["font"]
    dur = it["duration"]
    text, spans = _word_plan(it)
    pieces, n_chars = _pieces(text, it["text2"], g["em2"] * font["line"], spans)
    d_in, d_out = _windows(it, n_chars)

    template = it["template"]
    # Per-line colours of the text layer: title in the clip's colour, second line a touch softer.
    text_opacity = it["opacity"]
    base_scale = it["scale"] * 100.0
    box_on = it["box"] or template == "lower_box"
    styles = [_style(f"T{n}", it, g, box_layer=False)]
    if box_on:
        styles.append(_style(f"B{n}", it, g, box_layer=True))

    # --- breakpoints
    marks = {0.0, dur}
    k = 6
    if d_in > 0:
        steps = min(40, max(6, n_chars)) if it["anim_in"] == "typewriter" else k
        marks.update(d_in * i / steps for i in range(steps + 1))
    if d_out > 0:
        steps = min(40, max(6, n_chars)) if it["anim_out"] == "typewriter" else k
        marks.update(dur - d_out + d_out * i / steps for i in range(steps + 1))
    for s, e in spans:
        marks.update((min(s, dur), min(e, dur)))
    marks.update(p["t"] for p in it.get("path") or [] if 0 < p["t"] < dur)
    cuts = sorted({round(min(max(m, 0.0), dur), 2) for m in marks})

    # --- the decorations (bar / line / quote mark) are drawn once per interval with the same motion as the text
    block_h = g["block_h"]
    decos = []
    if template == "lower_bar" and block_h:
        h = block_h * 0.82
        bx = g["right"] + g["gap"] if it["align"] == "right" else g["left"] - g["gap"] - g["bar_w"]
        decos.append({"x": bx, "y": g["y"] - h / 2, "w": g["bar_w"], "h": h, "color": it["accent"], "opacity": 1.0})
    elif template == "lower_line" and block_h:
        lw = min(g["region"] * 0.4, W * 0.28)
        lh = max(2.0, em * 0.09)
        lx = {"left": g["left"], "center": g["anchor_x"] - lw / 2, "right": g["right"] - lw}[it["align"]]
        decos.append({"x": lx, "y": g["y"] + block_h / 2 + em * 0.15, "w": lw, "h": lh, "color": it["accent"],
                      "opacity": 1.0})

    events: list[str] = []
    ml, mr = int(round(g["left"])), int(round(W - g["right"]))
    hl_mode, hl_color = it["hl_mode"], it["hl_color"]
    pad_px = em * it["box_pad"] / 100.0
    stroke_px = em * it["stroke"] / 100.0

    def motion(st_a, st_b, length_ms, ax, ay):
        """\\pos or \\move between the two states' offsets."""
        xa, ya = ax + st_a["dx"], ay + st_a["dy"]
        xb, yb = ax + st_b["dx"], ay + st_b["dy"]
        if abs(xa - xb) < 0.3 and abs(ya - yb) < 0.3:
            return f"\\pos({_f(xa, 1)},{_f(ya, 1)})"
        return f"\\move({_f(xa, 1)},{_f(ya, 1)},{_f(xb, 1)},{_f(yb, 1)},0,{length_ms})"

    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.01:
            continue
        mid = (a + b) / 2
        length_ms = int(round((b - a) * 1000))
        sa = _state(it, a, d_in, d_out, W, H)
        sb = _state(it, b, d_in, d_out, W, H)
        sm = _state(it, mid, d_in, d_out, W, H)
        start, end = _ts(a), _ts(b)
        active = next((i for i, (s, e) in enumerate(spans) if s <= mid < e), None) if spans else None
        reveal_chars = None
        if sm["reveal"] < 0.999:
            reveal_chars = int(round(sm["reveal"] * n_chars))

        def layer_tags(layer: str) -> str:
            """Tags that make a dialogue look like st_a at its start and st_b at its end."""
            parts = [f"\\an{g['an']}", motion(sa, sb, length_ms, g["anchor_x"], g["y"])]
            if it["rotation"]:
                parts.append(f"\\frz{_f(-it['rotation'])}")
            sc_a, sc_b = base_scale * sa["scale"], base_scale * sb["scale"]
            parts.append(f"\\fscx{_f(sc_a)}\\fscy{_f(sc_a)}")
            if layer == "box":
                box_op = 1.0 if template == "lower_box" else it["box_opacity"]
                fa = lambda s: _a(box_op * s["alpha"])  # noqa: E731
                parts.append("\\1a&HFF&\\shad0\\4a&HFF&")
                parts.append(f"\\bord{_f(pad_px)}\\3c{_c(it['accent'] if template == 'lower_box' else it['box_color'])}")
                parts.append(f"\\3a{fa(sa)}")
                tail = []
                if sc_a != sc_b:
                    tail.append(f"\\fscx{_f(sc_b)}\\fscy{_f(sc_b)}")
                if fa(sa) != fa(sb):
                    tail.append(f"\\3a{fa(sb)}")
            else:
                parts.append(f"\\1a{_a(text_opacity * sa['alpha'])}\\3a{_a(sa['alpha'])}\\4a{_a(0.6 * sa['alpha'])}")
                if sa["blur"] or sb["blur"]:
                    parts.append(f"\\blur{_f(sa['blur'])}")
                tail = []
                if sc_a != sc_b:
                    tail.append(f"\\fscx{_f(sc_b)}\\fscy{_f(sc_b)}")
                if abs(sa["alpha"] - sb["alpha"]) > 1e-3:
                    tail.append(f"\\1a{_a(text_opacity * sb['alpha'])}\\3a{_a(sb['alpha'])}\\4a{_a(0.6 * sb['alpha'])}")
                if abs(sa["blur"] - sb["blur"]) > 1e-3:
                    tail.append(f"\\blur{_f(sb['blur'])}")
            if tail:
                parts.append(f"\\t(0,{length_ms},{''.join(tail)})")
            return "{" + "".join(parts) + "}"

        # karaoke tags for the active word (static inside the slice)
        mid_scale = base_scale * sm["scale"]
        if hl_mode == "box":
            hl_open = f"{{\\1c{_c('#111111')}\\3c{_c(hl_color)}\\bord{_f(stroke_px + em * 0.16)}}}"
            hl_close = f"{{\\1c{_c(it['color'])}\\3c{_c(it['stroke_color'])}\\bord{_f(stroke_px)}}}"
        elif hl_mode == "scale":
            hl_open = f"{{\\1c{_c(hl_color)}\\fscx{_f(mid_scale * 1.12)}\\fscy{_f(mid_scale * 1.12)}}}"
            hl_close = f"{{\\1c{_c(it['color'])}\\fscx{_f(mid_scale)}\\fscy{_f(mid_scale)}}}"
        else:
            hl_open = f"{{\\1c{_c(hl_color)}}}"
            hl_close = f"{{\\1c{_c(it['color'])}}}"
        hide = "{\\1a&HFF&\\3a&HFF&\\4a&HFF&}"
        line2_text = "{\\fs%s\\b0\\1a%s}" % (_f(g["em2"] * font["line"]), _a(text_opacity * 0.9 * sm["alpha"]))
        # (the \1a inside line 2 is resolved against the slice's mid state; during an animation the 0.9 factor is
        # a rounding-level difference)

        # --- box layer(s) and decorations (layer 0), text (layer 1)
        if box_on:
            line2_box = ""
            if template == "lower_box":
                line2_box = "{\\fs%s\\b0\\3c%s\\3a%s}" % (_f(g["em2"] * font["line"]), _c("#000000"),
                                                        _a(max(it["box_opacity"], 0.7) * sm["alpha"]))
            body = _render(pieces, reveal_chars=reveal_chars, active=None, hl_open="", hl_close="", hide=hide,
                           line2_tags=line2_box or "{\\fs%s\\b0}" % _f(g["em2"] * font["line"]))
            events.append(f"Dialogue: 0,{start},{end},B{n},,{ml},{mr},0,,{layer_tags('box')}{body}")
        for d in decos:
            alpha_a, alpha_b = _a(d["opacity"] * sa["alpha"]), _a(d["opacity"] * sb["alpha"])
            pos = motion({"dx": sa["dx"], "dy": sa["dy"]}, {"dx": sb["dx"], "dy": sb["dy"]}, length_ms, d["x"], d["y"])
            fade = f"\\t(0,{length_ms},\\1a{alpha_b})" if alpha_a != alpha_b else ""
            events.append(f"Dialogue: 0,{start},{end},T{n},,0,0,0,,{{\\an7{pos}\\bord0\\shad0\\1c{_c(d['color'])}"
                          f"\\1a{alpha_a}{fade}\\p1}}{_rect(0, 0, d['w'], d['h'])}{{\\p0}}")
        if template == "quote":
            mark_em = em * 2.2
            mark_y = g["y"] - block_h / 2 - mark_em * 0.45
            qpos = motion(sa, sb, length_ms, g["x"], mark_y)
            events.append(f"Dialogue: 0,{start},{end},T{n},,{ml},{mr},0,,{{\\an5{qpos}\\fs{_f(mark_em * font['line'])}"
                          f"\\1c{_c(it['accent'])}\\1a{_a(sa['alpha'])}\\bord0\\shad0\\b1}}\u201c")
        body = _render(pieces, reveal_chars=reveal_chars, active=active, hl_open=hl_open, hl_close=hl_close, hide=hide,
                       line2_tags=line2_text)
        events.append(f"Dialogue: 1,{start},{end},T{n},,{ml},{mr},0,,{layer_tags('text')}{body}")
    return styles, events


def build_ass(items: list[dict], width: int, height: int) -> str:
    """ONE ASS document for the cleaned text clips (each with `at` and `duration` on the timeline)."""
    W, H = int(width), int(height)
    styles: list[str] = []
    events: list[tuple[float, str]] = []
    for n, raw in enumerate(items):
        it = clean(raw, n)
        s, e = _item_ass(n, it, W, H)
        styles += s
        shift = it["at"]
        for line in e:
            events.append((shift, _shift_dialogue(line, shift)))
    events.sort(key=lambda pair: pair[0])
    return _HEADER.format(w=W, h=H) + "\n".join(styles) + "\n" + _EVENTS + "\n".join(line for _, line in events) + "\n"


_DIALOGUE = re.compile(r"^(Dialogue: \d+,)(\d+:\d\d:\d\d\.\d\d),(\d+:\d\d:\d\d\.\d\d)(,.*)$", re.S)


def _parse_ts(text: str) -> float:
    h, m, s = text.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _shift_dialogue(line: str, seconds: float) -> str:
    m = _DIALOGUE.match(line)
    if not m:
        return line
    return f"{m.group(1)}{_ts(_parse_ts(m.group(2)) + seconds)},{_ts(_parse_ts(m.group(3)) + seconds)}{m.group(4)}"


# ------------------------------------------------------------ browser helpers

def preview_spec(item: dict) -> dict:
    """What a browser needs to approximate the clip (sizes as fractions of the frame, so any preview size works)."""
    it = clean(item)
    font = FONTS[it["font"]]
    region = min(0.88, 2 * min(it["x"], 1 - it["x"]) * 0.96)
    return {
        "template": it["template"], "text": it["text"], "text2": it["text2"], "line2": LINE2,
        "font": it["font"], "css": font["css"], "weight": 700 if (it["bold"] and font["bold"]) else font["css_weight"],
        "italic": it["italic"], "size": it["size"] / 100.0, "line_height": font["line"],
        "color": it["color"], "opacity": it["opacity"],
        "stroke": {"color": it["stroke_color"], "w": it["stroke"] / 100.0},
        "shadow": {"color": it["shadow_color"], "d": it["shadow"] / 100.0},
        "box": {"on": bool(it["box"] or it["template"] == "lower_box"), "color": it["box_color"],
                "opacity": it["box_opacity"], "pad": it["box_pad"] / 100.0},
        "accent": it["accent"], "align": it["align"], "anchor": {"x": it["x"], "y": it["y"]}, "region_w": region,
        "rotation": it["rotation"], "scale": it["scale"],
        "anim": {"in": it["anim_in"], "out": it["anim_out"], "dur": it["anim_dur"]},
        "words": it["words"], "hl_color": it["hl_color"], "hl_mode": it["hl_mode"], "caption": it["caption"],
        "rtl": is_rtl(it["text"] or it["text2"]),
    }


def catalogue() -> dict:
    """Everything the panel lists in its title pickers, with Persian names."""
    return {
        "fonts": [{"key": k, "title": v["title"], "css": v["css"], "weight": v["css_weight"], "bold": v["bold"]}
                  for k, v in FONTS.items()],
        "templates": [{"key": k, "title": v["title"], "hint": v["hint"], "defaults": v["defaults"]}
                      for k, v in TEMPLATES.items()],
        "animations_in": [{"key": k, "title": v} for k, v in ANIMATIONS_IN.items()],
        "animations_out": [{"key": k, "title": v} for k, v in ANIMATIONS_OUT.items()],
        "hl_modes": [{"key": k, "title": v} for k, v in HL_MODES.items()],
        "aligns": [{"key": k, "title": v} for k, v in ALIGNS.items()],
        "line2_ratio": LINE2,
    }
