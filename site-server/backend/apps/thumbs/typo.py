"""متنِ فارسیِ تامنیل: چیدمان، جاگیریِ خودکار، حاشیه/سایه/درخشش/برجسته و کلمهٔ پررنگ‌شده.

Pillow + libraqm (شکل‌دهی و جهتِ درستِ فارسی). اگر raqm نبود با arabic_reshaper + python-bidi کار می‌کند (مثلِ
``services.imaging.text_overlay``). فونت‌ها همان‌هایی‌اند که ادیتورِ عکس دارد (همه SIL OFL 1.1): لاله‌زار، استعداد، وزیرمتن، ساحل…

``render_text`` یک «بلوکِ متن» (RGBA + اندازهٔ اسمی) برمی‌گرداند؛ جاگذاری با ``place``.
کلمهٔ پررنگ‌شده: در متن بنویسید ``*کلمه*`` (یا خودکار، آخرین کلمه). ``|`` یعنی «اینجا خط را بشکن».
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, features

from . import primitives as P

HAS_RAQM = features.check("raqm")

#: نقشِ هر فونت در تامنیل: (کلید در fontreg، وزنِ پیش‌فرضِ تیتر). لاله‌زار یک وزن دارد.
FONT_CHOICES = {
    "lalezar": ("لاله‌زار — درشت و پرجلوه", 400),
    "estedad": ("استعداد — مدرن و تمیز", 800),
    "vazirmatn": ("وزیرمتن — خوانا", 800),
    "sahel": ("ساحل — گرم و گرد", 800),
    "shabnam": ("شبنم — ساده", 700),
    "samim": ("صمیم — رسمی", 700),
}
AUTO_FONT = "auto"

_RTL_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_HL_RE = re.compile(r"\*([^*]+)\*")


def is_rtl(text: str) -> bool:
    return bool(_RTL_RE.search(text or ""))


def font_path(key: str, weight: int) -> str:
    from apps.photoedit import textlayer

    return textlayer.font_path_for(key if key in FONT_CHOICES else "vazirmatn", weight)


@lru_cache(maxsize=96)
def _font(path: str, px: int):
    return ImageFont.truetype(path, px)


def _kw(rtl: bool) -> dict:
    return {"direction": "rtl", "language": "fa"} if (rtl and HAS_RAQM) else {}


def _shape(text: str, rtl: bool) -> str:
    """بدونِ raqm: شکل‌دهیِ دستی (حروفِ چسبیده + ترتیبِ راست‌به‌چپ)."""
    if HAS_RAQM or not rtl:
        return text
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(text))


def to_fa_digits(text: str) -> str:
    """رقم‌های لاتین ⇒ فارسی؛ ویرگولِ بینِ رقم‌ها ⇒ «٬». متنِ لاتینِ خالص («HIIT»، «3D»، «Wi-Fi 6») دست نمی‌خورد،
    ولی رشتهٔ فقط‌عددی («7»، «20%»، «10:30») که حرفِ لاتین ندارد هم فارسی می‌شود (کادرِ «عدد» در سبکِ عدد/لیست)."""
    if not text:
        return text
    if not is_rtl(text) and (re.search(r"[A-Za-z]", text) or not re.search(r"[0-9]", text)):
        return text
    out = text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    return re.sub(r"(?<=[۰-۹]),(?=[۰-۹])", "٬", out)


def clean(text) -> str:
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", str(text or ""))
    return re.sub(r"[ \t]+", " ", t).strip()


@dataclass
class TextStyle:
    fill: str = "#ffffff"
    fill2: str | None = None          # پایینِ گرادیانِ عمودیِ پُرکننده
    hl: str | None = None             # رنگِ کلمهٔ پررنگ‌شده
    stroke: str | None = None
    stroke_w: float = 0.0             # نسبت به اندازهٔ فونت
    shadow: tuple[float, float, float, str, float] | None = None   # (dx, dy, blur) نسبت به فونت، رنگ، شفافیت
    glow: tuple[str, float, float] | None = None                   # (رنگ، شعاع نسبت به فونت، قدرت)
    extrude: tuple[str, float] | None = None                       # (رنگ، عمق نسبت به فونت) — برجستگیِ سه‌بعدی
    align: str = "auto"               # auto | right | center | left
    line_gap: float = 1.1
    weight: int = 800
    font_key: str = "lalezar"
    rotate: float = 0.0
    #: «برچسبِ» پشتِ متن: (رنگ، پدینگِ نسبی، شعاعِ نسبی)
    plate: tuple[str, float, float] | None = None
    auto_hl: bool = False


@dataclass
class TextBlock:
    img: Image.Image                  # RGBA (شاملِ لبه‌های جلوه)
    nominal: tuple[int, int]          # اندازهٔ جعبهٔ اسمیِ متن (بدونِ جلوه‌ها)
    origin: tuple[int, int]           # جابه‌جاییِ گوشهٔ جعبهٔ اسمی داخلِ img
    lines: int
    px: int
    ink: tuple[int, int, int, int] | None = None     # کادرِ واقعیِ جوهر داخلِ img

    @property
    def size(self) -> tuple[int, int]:
        return self.img.size


def parse_marked(text: str) -> tuple[list[list[tuple[str, bool]]], bool]:
    """«الف *ب* ج|د» ⇒ [[(کلمه، پررنگ؟)…] برای هر خطِ اجباری]، و اینکه نشانه‌ای بود یا نه."""
    text = clean(text)
    forced = [seg.strip() for seg in text.split("|")] if "|" in text else [text]
    marked = bool(_HL_RE.search(text))
    out: list[list[tuple[str, bool]]] = []
    for seg in forced:
        words: list[tuple[str, bool]] = []
        pos = 0
        for m in _HL_RE.finditer(seg):
            for w in seg[pos:m.start()].split():
                words.append((w, False))
            for w in m.group(1).split():
                words.append((w, True))
            pos = m.end()
        for w in seg[pos:].split():
            words.append((w, False))
        out.append(words)
    return [ln for ln in out if ln], marked


def plain(text: str) -> str:
    """متنِ بدونِ نشانه‌ها (برای شمردن/نمایش)."""
    return re.sub(r"\s+", " ", _HL_RE.sub(r"\1", clean(text)).replace("|", " ")).strip()


def _wrap(words: list[tuple[str, bool]], widths: list[float], space: float, avail: float) -> list[list[int]] | None:
    """شکستنِ حریصانه؛ None اگر کلمه‌ای از پهنای مجاز بزرگ‌تر باشد."""
    if any(w > avail for w in widths):
        return None
    lines: list[list[int]] = []
    cur: list[int] = []
    cur_w = 0.0
    for i, w in enumerate(widths):
        add = w if not cur else space + w
        if cur and cur_w + add > avail:
            lines.append(cur)
            cur, cur_w = [i], w
        else:
            cur.append(i)
            cur_w += add
    if cur:
        lines.append(cur)
    return lines


def _balance(words, widths, space, avail, n_lines) -> list[list[int]]:
    """خط‌ها را متعادل می‌کند: کوچک‌ترین پهنایی که هنوز همان تعدادِ خط را می‌دهد."""
    lo, hi = max(widths), avail
    best = _wrap(words, widths, space, hi) or []
    for _ in range(14):
        mid = (lo + hi) / 2
        got = _wrap(words, widths, space, mid)
        if got is not None and len(got) <= n_lines:
            best, hi = got, mid
        else:
            lo = mid
    return best


def _line_width(idx: list[int], widths: list[float], space: float) -> float:
    return sum(widths[i] for i in idx) + space * max(0, len(idx) - 1)


def _layout(groups, path: str, px: int, box_w: float, style: TextStyle, rtl: bool, force: bool = False):
    """چیدمانِ همهٔ گروه‌ها در یک اندازهٔ فونت ⇒ (فاصلهٔ کلمه، [(کلمه‌ها، پهنا‌ها، خط‌ها)]) یا None اگر کلمه‌ای جا نشود."""
    f = _font(path, px)
    kw = _kw(rtl)
    sw = style.stroke_w * px
    avail = 1e9 if force else box_w - 2 * sw
    space = max(f.getlength(_shape(" ", rtl), **kw), px * 0.24)
    rows = []
    for words in groups:
        widths = [f.getlength(_shape(w, rtl), **kw) for w, _ in words]
        got = _wrap(words, widths, space, avail)
        if got is None:
            return None
        if len(groups) == 1 and len(got) > 1:
            got = _balance(words, widths, space, avail, len(got))
        rows.append((words, widths, got))
    return space, rows


def fit(text: str, path: str, box_w: float, box_h: float, style: TextStyle, *, max_lines: int = 3, min_px: int = 18,
        max_px: int = 400, rtl: bool | None = None):
    """بزرگ‌ترین اندازهٔ فونتی که متن در جعبه جا شود. ⇒ (px، خط‌ها [(کلمه،پررنگ؟)…]، پهنای هر خط، فاصلهٔ کلمه، rtl)."""
    groups, marked = parse_marked(text)
    if not groups:
        return None
    rtl = is_rtl(text) if rtl is None else rtl
    max_lines = max(max_lines, min(len(groups), 5))     # «الف|ب|ج» = سه خطِ اجباری؛ سقفِ خط نباید آن را به نقطهٔ ریز تبدیل کند
    px = int(max_px)
    floor = max(8, int(min_px * 0.45))
    res = None
    while True:
        res = _layout(groups, path, px, box_w, style, rtl)
        if res is not None:
            total_lines = sum(len(r[2]) for r in res[1])
            sw = style.stroke_w * px
            asc, desc = _font(path, px).getmetrics()
            height = px * style.line_gap * (total_lines - 1) + asc + desc + 2 * sw
            if total_lines <= max_lines and height <= box_h:
                break
        if px <= floor:
            break
        px = max(floor, int(px * 0.94) if px > 40 else px - 2)
    if res is None:                      # حتی در کوچک‌ترین اندازه یک کلمه از جعبه پهن‌تر است ⇒ بی‌شکستن
        res = _layout(groups, path, px, box_w, style, rtl, force=True)
    space, rows = res
    lines: list[list[tuple[str, bool]]] = []
    widths_out: list[float] = []
    for words, widths, got in rows:
        for idx in got:
            lines.append([words[i] for i in idx])
            widths_out.append(_line_width(idx, widths, space))
    if style.auto_hl and not marked and lines and sum(len(ln) for ln in lines) >= 3:
        last = lines[-1][-1]
        lines[-1][-1] = (last[0], True)
    return px, lines, widths_out, space, rtl


def render_text(text: str, box_w: float, box_h: float, style: TextStyle, *, max_lines: int = 3, min_px: int = 18,
                max_px: int = 400) -> TextBlock | None:
    """متن را در جعبهٔ box_w×box_h جا می‌دهد و بلوکِ RGBA با همهٔ جلوه‌ها می‌سازد. متنِ خالی ⇒ None."""
    text = clean(text)
    if not plain(text):
        return None
    path = font_path(style.font_key, style.weight)
    got = fit(text, path, box_w, box_h, style, max_lines=max_lines, min_px=min_px, max_px=max_px)
    if got is None:
        return None
    px, lines, widths, space, rtl = got
    f = _font(path, px)
    kw = _kw(rtl)
    ascent, descent = f.getmetrics()
    sw = int(round(style.stroke_w * px))
    line_h = px * style.line_gap
    nominal_w = int(math.ceil(max(widths) + 2 * sw)) if widths else int(box_w)
    nominal_w = max(nominal_w, 1)
    nominal_h = int(math.ceil(line_h * (len(lines) - 1) + ascent + descent + 2 * sw))

    # فاصلهٔ لبه برای جلوه‌ها
    pad = sw + 4
    if style.shadow:
        pad = max(pad, int(abs(style.shadow[0]) * px + abs(style.shadow[1]) * px + style.shadow[2] * px * 2.5) + 4)
    if style.glow:
        pad = max(pad, int(style.glow[1] * px * 2.6) + 4)
    if style.extrude:
        pad = max(pad, int(style.extrude[1] * px) + sw + 4)
    if style.plate:
        pad = max(pad, int(style.plate[1] * px) + 4)
    W, H = nominal_w + 2 * pad, nominal_h + 2 * pad

    align = style.align if style.align != "auto" else ("right" if rtl else "left")
    m_fill = Image.new("L", (W, H), 0)
    m_hl = Image.new("L", (W, H), 0)
    m_stroke = Image.new("L", (W, H), 0)
    d_fill, d_hl, d_stroke = ImageDraw.Draw(m_fill), ImageDraw.Draw(m_hl), ImageDraw.Draw(m_stroke)

    def draw_to(draw, xy, s, anchor, stroke):
        if stroke:
            draw.text(xy, s, font=f, fill=255, anchor=anchor, stroke_width=sw, stroke_fill=255, **kw)
        else:
            draw.text(xy, s, font=f, fill=255, anchor=anchor, **kw)

    inner_left, inner_right = pad + sw, pad + sw + (nominal_w - 2 * sw)
    inner_w = inner_right - inner_left
    for li, (line, lw) in enumerate(zip(lines, widths)):
        base = pad + sw + ascent + li * line_h
        if align == "center":
            right = inner_left + inner_w / 2 + lw / 2
            left = inner_left + inner_w / 2 - lw / 2
        elif align == "right":
            right, left = inner_right, inner_right - lw
        else:
            left, right = inner_left, inner_left + lw
        has_hl = any(h for _, h in line)
        if not has_hl:
            s = " ".join(w for w, _ in line)
            if rtl:
                draw_to(d_fill, (right, base), _shape(s, rtl), "rs", False)
                draw_to(d_stroke, (right, base), _shape(s, rtl), "rs", sw > 0)
            else:
                draw_to(d_fill, (left, base), s, "ls", False)
                draw_to(d_stroke, (left, base), s, "ls", sw > 0)
            continue
        cursor = right if rtl else left
        for w, hl in line:
            wd = f.getlength(_shape(w, rtl), **kw)
            tgt_fill = d_hl if hl else d_fill
            if rtl:
                draw_to(tgt_fill, (cursor, base), _shape(w, rtl), "rs", False)
                draw_to(d_stroke, (cursor, base), _shape(w, rtl), "rs", sw > 0)
                cursor -= wd + space
            else:
                draw_to(tgt_fill, (cursor, base), w, "ls", False)
                draw_to(d_stroke, (cursor, base), w, "ls", sw > 0)
                cursor += wd + space

    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if style.plate:
        pc, pp, pr = style.plate
        ink = ImageChops.lighter(m_stroke, ImageChops.lighter(m_fill, m_hl)).getbbox()
        if ink:
            pd = int(pp * px)
            bx = (max(0, ink[0] - pd), max(0, ink[1] - pd), min(W, ink[2] + pd), min(H, ink[3] + pd))
            plate_m = P.rounded_mask((bx[2] - bx[0], bx[3] - bx[1]), pr * px)
            full = Image.new("L", (W, H), 0)
            full.paste(plate_m, (bx[0], bx[1]))
            out = Image.alpha_composite(out, P.solid((W, H), pc, full))
    if style.shadow:
        sdx, sdy, sbl, scol, sop = style.shadow
        base = m_stroke if sw else ImageChops.lighter(m_fill, m_hl)
        sh = ImageChops.offset(base, int(round(sdx * px)), int(round(sdy * px)))
        sh = sh.filter(ImageFilter.GaussianBlur(max(0.1, sbl * px)))
        out = Image.alpha_composite(out, P.solid((W, H), scol, sh, sop))
    if style.glow:
        gc, gr, gs = style.glow
        base = m_stroke if sw else ImageChops.lighter(m_fill, m_hl)
        gl = base.filter(ImageFilter.GaussianBlur(max(0.1, gr * px)))
        out = Image.alpha_composite(out, P.solid((W, H), gc, gl, min(1.0, gs)))
        out = Image.alpha_composite(out, P.solid((W, H), gc, base.filter(ImageFilter.GaussianBlur(max(0.1, gr * px * 0.35))), min(1.0, gs)))
    if style.extrude:
        ec, ed = style.extrude
        depth = max(1, int(ed * px))
        base = m_stroke if sw else ImageChops.lighter(m_fill, m_hl)
        for k in range(depth, 0, -1):
            out = Image.alpha_composite(out, P.solid((W, H), ec, ImageChops.offset(base, k // 2 + 1, k), 1.0))
    if sw and style.stroke:
        out = Image.alpha_composite(out, P.solid((W, H), style.stroke, m_stroke))
    fill_img: Image.Image | str = style.fill
    if style.fill2:
        fill_img = P.gradient((W, H), [(0.0, style.fill), (1.0, style.fill2)], 90).convert("RGBA")
    if isinstance(fill_img, str):
        out = Image.alpha_composite(out, P.solid((W, H), fill_img, m_fill))
    else:
        layer = fill_img.copy()
        layer.putalpha(m_fill)
        out = Image.alpha_composite(out, layer)
    if style.hl:
        out = Image.alpha_composite(out, P.solid((W, H), style.hl, m_hl))
    elif m_hl.getbbox():
        out = Image.alpha_composite(out, P.solid((W, H), style.fill, m_hl))

    origin = (pad, pad)
    if abs(style.rotate) > 0.01:
        out = out.rotate(style.rotate, resample=Image.Resampling.BICUBIC, expand=True)
        # مرکزِ جعبهٔ اسمی پس از چرخش جابه‌جا می‌شود؛ اصلِ جدید = مرکزِ جعبه
        ox = out.width / 2 - nominal_w / 2
        oy = out.height / 2 - nominal_h / 2
        origin = (int(round(ox)), int(round(oy)))
    ink = out.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
    return TextBlock(img=out, nominal=(nominal_w, nominal_h), origin=origin, lines=len(lines), px=px, ink=ink)


def place(block: TextBlock, rect: tuple[float, float, float, float], ax: str = "center", ay: str = "middle"
          ) -> tuple[int, int]:
    """موقعیتِ گوشهٔ بالا-چپِ ``block.img`` تا جعبهٔ اسمیِ متن در rect با تراز (ax: right/center/left، ay: top/middle/bottom) بنشیند."""
    x0, y0, x1, y1 = rect
    nw, nh = block.nominal
    if ax == "right":
        nx = x1 - nw
    elif ax == "left":
        nx = x0
    else:
        nx = (x0 + x1) / 2 - nw / 2
    if ay == "top":
        ny = y0
    elif ay == "bottom":
        ny = y1 - nh
    else:
        ny = (y0 + y1) / 2 - nh / 2
    return int(round(nx - block.origin[0])), int(round(ny - block.origin[1]))


def label(text: str, px: int, *, font_key: str = "estedad", weight: int = 800, fill: str = "#ffffff", bg: str = "#000000",
          pad_x: float = 0.7, pad_y: float = 0.32, radius: float = 0.5, border: str | None = None, border_w: float = 0.0,
          shadow: bool = True, slant: float = 0.0) -> Image.Image | None:
    """برچسبِ کپسولی (متنِ کوتاه روی زمینهٔ رنگی) ⇒ RGBA. ``slant`` > 0 لبه‌ها را اریب می‌کند."""
    text = plain(text)
    if not text:
        return None
    rtl = is_rtl(text)
    f = _font(font_path(font_key, weight), max(8, int(px)))
    kw = _kw(rtl)
    tw = f.getlength(_shape(text, rtl), **kw)
    asc, desc = f.getmetrics()
    px_i, py_i = int(px * pad_x), int(px * pad_y)
    w, h = int(math.ceil(tw)) + 2 * px_i, asc + desc + 2 * py_i
    shadow_pad = int(px * 0.35) if shadow else 0
    bw = int(round(border_w * px))
    pad = shadow_pad + bw + 2
    base = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    if slant:
        sk = int(h * slant)
        pts = [(sk, 0), (w, 0), (w - sk, h), (0, h)]
        m = P.polygon_mask((w, h), pts)
    else:
        m = P.rounded_mask((w, h), min(h / 2, radius * h))
    big = Image.new("L", base.size, 0)
    big.paste(m, (pad, pad))
    if shadow:
        sh = ImageChops.offset(big, 0, int(px * 0.12)).filter(ImageFilter.GaussianBlur(px * 0.12))
        base = Image.alpha_composite(base, P.solid(base.size, "#000000", sh, 0.35))
    if border and bw:
        base = Image.alpha_composite(base, P.solid(base.size, border, P.dilate(big, bw)))
    base = Image.alpha_composite(base, P.solid(base.size, bg, big))
    d = ImageDraw.Draw(base)
    d.text((pad + w / 2, pad + py_i + asc), _shape(text, rtl), font=f, fill=P.rgba(fill), anchor="ms", **kw)
    return base
