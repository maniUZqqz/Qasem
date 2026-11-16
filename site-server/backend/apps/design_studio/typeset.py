"""حروف‌چینی: اندازه‌گیری، شکستنِ خط، ترازِ دوطرفه و جاگیری با Pillow + raqm (همان موتورِ ادیتورِ عکس).

همهٔ اندازه‌ها «واحدِ صحنه»‌اند (برای چاپ میلی‌متر، برای اسلاید و UI پیکسل). اندازه‌گیری روی یک قلمِ مرجعِ ۱۲۸ پیکسلی انجام می‌شود و خطی
مقیاس می‌گیرد؛ پس نتیجه به مقیاسِ رندر بستگی ندارد و PNG، PDF، SVG و PPTX یک شکستِ خط را می‌بینند.
"""
from __future__ import annotations

import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from apps.photoedit import textlayer

from . import fonts

REF = 128
_DRAW = ImageDraw.Draw(Image.new("L", (4, 4)))
_FA = str.maketrans("0123456789٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶۷۸۹")
_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ELLIPSIS = "…"
MAX_LINES = 200


def digits(text, mode: str = "fa") -> str:
    """«fa» رقم‌های فارسی، «en» لاتین، «keep» دست‌نخورده."""
    t = "" if text is None else str(text)
    if mode == "fa":
        return t.translate(_FA)
    if mode == "en":
        return t.translate(_EN)
    return t


def group_number(n, mode: str = "fa") -> str:
    """۶۰۰۰۰۰ ⇒ «۶۰۰٬۰۰۰» (با جداکنندهٔ فارسی)؛ عددِ اعشاری هم می‌گیرد."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return digits(str(n), mode)
    if v == int(v):
        s = f"{int(v):,}"
    else:
        s = f"{v:,.2f}".rstrip("0").rstrip(".")
    s = s.replace(",", "٬" if mode == "fa" else ",")
    return digits(s, mode)


CURRENCY_FA = {"IRT": "تومان", "IRR": "ریال", "USD": "دلار", "EUR": "یورو", "AED": "درهم", "TRY": "لیر"}


def price_text(value, currency: str = "IRT", mode: str = "fa", zero_label: str = "رایگان") -> str:
    """قیمتِ ثبت‌شده در فروشگاه، همان‌طور که هست (بدونِ گرد کردن یا تبدیلِ واحد)؛ ۰ ⇒ ``zero_label``؛ خالی ⇒ ""."""
    if value is None or value == "":
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return zero_label
    return f"{group_number(v, mode)} {CURRENCY_FA.get(str(currency or 'IRT').upper(), str(currency or ''))}".strip()


# ───────────────────────────── قلم و اندازه‌گیری

@lru_cache(maxsize=256)
def _ref_font(path: str):
    return ImageFont.truetype(path, REF)


@lru_cache(maxsize=64)
def _px_font(path: str, px: int):
    return ImageFont.truetype(path, max(4, int(px)))


def is_rtl(text: str, direction: str = "auto") -> bool:
    if direction == "rtl":
        return True
    if direction == "ltr":
        return False
    return textlayer.is_rtl_text(text or "")


@lru_cache(maxsize=20000)
def _ref_len(path: str, text: str, rtl: bool) -> float:
    if not text:
        return 0.0
    return float(textlayer._len(_DRAW, text, _ref_font(path), rtl))


def measure(text: str, font: str, weight: int, size: float, rtl: bool | None = None) -> float:
    """پهنای یک خط (واحدِ صحنه)."""
    if not text:
        return 0.0
    r = is_rtl(text) if rtl is None else rtl
    return _ref_len(fonts.resolve(font, weight), text, r) * size / REF


def metrics(font: str, weight: int, size: float) -> tuple[float, float]:
    """(ascent، descent) به واحدِ صحنه."""
    asc, desc = _ref_font(fonts.resolve(font, weight)).getmetrics()
    return asc * size / REF, desc * size / REF


def baseline_offset(font: str, weight: int, size: float, line_h: float) -> float:
    """فاصلهٔ خطِ پایهٔ متن از بالای جعبهٔ خط (متن در وسطِ جعبه می‌نشیند)."""
    asc, desc = metrics(font, weight, size)
    return (line_h - (asc + desc)) / 2 + asc


# ───────────────────────────── شکستنِ خط

def _split_long(word: str, path: str, max_w: float, rtl: bool, scale: float) -> list[str]:
    """واژه‌ای که از یک خطِ کامل پهن‌تر است ⇒ تکه‌تکه (آخرین راه)."""
    out, cur = [], ""
    for ch in word:
        trial = cur + ch
        if cur and _ref_len(path, trial, rtl) * scale > max_w + 0.02:
            out.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        out.append(cur)
    return out


def wrap(text: str, font: str, weight: int, size: float, max_w: float, direction: str = "auto") -> list[tuple[str, bool]]:
    """⇒ [(خط، rtl?)]؛ \\n همیشه خطِ تازه است. حریصانه، با شکستنِ واژه‌های بیش از حد بلند."""
    path = fonts.resolve(font, weight)
    scale = size / REF
    out: list[tuple[str, bool]] = []
    for para in str(text or "").replace("\r", "").split("\n"):
        if not para.strip():
            out.append(("", is_rtl("", direction)))
            continue
        rtl = is_rtl(para, direction)
        words = [w for w in para.split(" ") if w != ""]
        cur = ""
        for w in words:
            pieces = [w]
            if _ref_len(path, w, rtl) * scale > max_w + 0.02:
                pieces = _split_long(w, path, max_w, rtl, scale)
            for j, piece in enumerate(pieces):
                if j > 0:
                    if cur:
                        out.append((cur, rtl))
                    cur = piece
                    continue
                trial = (cur + " " + piece).strip() if cur else piece
                if not cur or _ref_len(path, trial, rtl) * scale <= max_w + 0.02:
                    cur = trial
                else:
                    out.append((cur, rtl))
                    cur = piece
        out.append((cur, rtl))
        if len(out) >= MAX_LINES:
            break
    return out[:MAX_LINES]


def _truncate(line: str, rtl: bool, path: str, scale: float, max_w: float) -> str:
    """خطی که باید با «…» تمام شود."""
    words = line.split(" ")
    while words:
        cand = " ".join(words).rstrip(" ،,؛;:.") + _ELLIPSIS
        if _ref_len(path, cand, rtl) * scale <= max_w:
            return cand
        words.pop()
    return _ELLIPSIS


def layout_text(text: str, *, font: str = "vazirmatn", weight: int = 400, size: float = 4.0, w: float = 100.0, h: float | None = None,
                align: str = "auto", dir: str = "auto", lh: float = 1.5, max_lines: int | None = None, shrink: float = 0.0,
                justify: bool = False, valign: str = "top") -> dict:
    """جاگیریِ یک متن در جعبهٔ w×h.

    ⇒ {size، line_h، lines:[{t، x، y، w، rtl، words?}]، h (بلندیِ محتوا)، w (پهنای پرترین خط)، truncated، overflow، n}
    * ``shrink`` ∈ [0..1): تا این کسر از اندازه کوچک می‌شود تا در h جا شود (ابتدا کوچک‌کردن، بعد بریدن با «…»).
    * ``max_lines``: بیش از آن ⇒ خطِ آخر با «…» تمام می‌شود.
    * x از لبهٔ چپِ جعبه است (راست‌چین ⇒ x = w − پهنای خط)؛ y از بالای جعبه (با ``valign``).
    """
    text = "" if text is None else str(text)
    path = fonts.resolve(font, weight)
    size0 = float(size)
    cur = size0
    floor = size0 * (1 - max(0.0, min(0.9, shrink)))
    while True:
        raw = wrap(text, font, weight, cur, w, dir)
        truncated = False
        if max_lines and len(raw) > max_lines:
            raw = raw[:max_lines]
            line, rtl = raw[-1]
            raw[-1] = (_truncate(line, rtl, path, cur / REF, w) if line else _ELLIPSIS, rtl)
            truncated = True
        line_h = cur * lh
        need = line_h * len(raw)
        if h is not None and need > h + 1e-6 and cur > floor + 1e-6:
            cur = max(floor, cur * 0.94)
            continue
        break
    scale = cur / REF
    line_h = cur * lh
    n = len(raw)
    clipped = False
    if h is not None and need > h + 1e-6 and n > 1 and max_lines is None:
        fit_n = max(1, int(h // line_h))
        if fit_n < n:
            raw = raw[:fit_n]
            line, rtl = raw[-1]
            raw[-1] = (_truncate(line, rtl, path, scale, w) if line else _ELLIPSIS, rtl)
            truncated = True
            clipped = True
            n = fit_n
    total_h = line_h * n
    y0 = 0.0
    if h is not None and valign in ("middle", "bottom"):
        y0 = max(0.0, (h - total_h) / (2 if valign == "middle" else 1))
    lines = []
    for i, (t, rtl) in enumerate(raw):
        lw = _ref_len(path, t, rtl) * scale
        al = align if align != "auto" else ("right" if rtl else "left")
        last = i == n - 1 or raw[i + 1][0] == ""
        row = {"t": t, "w": lw, "rtl": rtl, "y": y0 + i * line_h}
        if justify and al in ("right", "left", "justify") and not last and t and " " in t and lw < w:
            words = t.split(" ")
            wl = [_ref_len(path, wd, rtl) * scale for wd in words]
            gap = (w - sum(wl)) / (len(words) - 1)
            xs, x = [], (w if rtl else 0.0)
            seq = words
            for wd, wlen in zip(seq, wl):
                if rtl:
                    x -= wlen
                    xs.append({"t": wd, "x": x, "w": wlen})
                    x -= gap
                else:
                    xs.append({"t": wd, "x": x, "w": wlen})
                    x += wlen + gap
            row["words"], row["x"], row["w"] = xs, 0.0, w
        else:
            row["x"] = {"right": w - lw, "left": 0.0, "center": (w - lw) / 2, "justify": (w - lw) if rtl else 0.0}.get(al, 0.0)
        lines.append(row)
    overflow = h is not None and total_h > h + 1e-6
    return {"size": cur, "line_h": line_h, "lines": lines, "h": total_h, "w": max([r["w"] for r in lines] or [0.0]), "n": n,
            "truncated": truncated, "clipped": clipped, "overflow": overflow, "baseline": baseline_offset(font, weight, cur, line_h), "shrunk": cur < size0 - 1e-9}


# ───────────────────────────── رسمِ متن روی تصویر

def draw_line(draw: ImageDraw.ImageDraw, x: float, baseline: float, text: str, font: str, weight: int, px_size: float, fill, rtl: bool) -> None:
    """یک خط را با لبهٔ چپِ x و خطِ پایهٔ baseline (پیکسل) می‌کشد."""
    if not text:
        return
    f = _px_font(fonts.resolve(font, weight), round(px_size))
    shaped = textlayer._shape(text, rtl)
    draw.text((x, baseline), shaped, font=f, fill=fill, anchor="ls", **textlayer._kw(rtl))


def line_width_px(text: str, font: str, weight: int, px_size: float, rtl: bool) -> float:
    f = _px_font(fonts.resolve(font, weight), round(px_size))
    return float(textlayer._len(_DRAW, text, f, rtl))


# ───────────────────────────── متنِ برنامه‌نویسی‌شده

_WS = re.compile(r"[ \t ]+")


def clean_text(text, limit: int = 4000) -> str:
    """متنِ ورودیِ کاربر ⇒ بی‌نویسهٔ کنترلی، فاصله‌های پشتِ‌هم یکی، ≤ limit."""
    t = "" if text is None else str(text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = "".join(ch for ch in t if ch == "\n" or ch == "‌" or ord(ch) >= 32)
    t = "\n".join(_WS.sub(" ", ln).strip() for ln in t.split("\n"))
    return t.strip()[:limit]
