"""سبک‌های تامنیل و پوستر — هر کدام یک ترکیبِ لایه‌ایِ واقعی (پس‌زمینه، سوژهٔ بریده، عنوان با حاشیه و سایه، تزئین، نشان، لوگو).

سبک‌ها «الگوی رایجِ» تامنیل‌های پرکلیک و پوسترِ فیلم‌اند، نه کپیِ یک اثرِ مشخص: چهرهٔ بزرگ + متنِ درشت، قبل/بعد، عدد/لیست،
سؤالِ کنجکاوی‌برانگیز، مینیمالِ لوکس، پوسترِ سینمایی، کلاژِ پینترستی، قهرمانِ محصول، استیکرِ حاشیه‌دار، نئون، تیترِ خبری، رویارویی،
جلدِ مجله، پوسترِ قدیمی (رترو) و کارتِ نقل‌قول.

هر تابع فقط ``Ctx`` می‌گیرد و لایه‌ها را می‌گذارد. هیچ سبکی بدونِ عکس هم خالی نمی‌ماند (شکلِ جایگزین دارد) و هیچ متنی از ناحیهٔ
پرهیزِ پلتفرم رد نمی‌شود (``Ctx.text`` خودش کادر را کوچک می‌کند).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from PIL import Image, ImageChops

from . import palette as pm
from . import primitives as P
from . import shapes as S
from . import typo
from .render import Ctx
from .typo import TextStyle


@dataclass
class StyleDef:
    key: str
    title: str
    short: str
    pattern: str                       # توضیحِ الگو (برای «مودبرد»)
    fn: Callable[[Ctx], None]
    mood: str
    font: str
    family: str                        # youtube | poster | pinterest | product | social
    subject: str                       # none | optional | recommended
    fields: list[tuple[str, str]]      # (کلیدِ محتوا، برچسبِ فارسی)
    formats: list[str]
    needs_second: bool = False
    tips: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {"key": self.key, "title": self.title, "short": self.short, "pattern": self.pattern, "mood": self.mood,
                "mood_fa": pm.MOOD_FA.get(self.mood, ""), "font": self.font, "family": self.family, "subject": self.subject,
                "fields": [{"key": k, "label": l} for k, l in self.fields], "formats": self.formats,
                "needs_second": self.needs_second, "tips": self.tips}


# ───────────────────────────── ابزارهای مشترک

def _title_style(c: Ctx, **kw) -> TextStyle:
    p = c.pal
    base = dict(fill="#ffffff", stroke=p.ink, stroke_w=0.095, shadow=(0.02, 0.05, 0.035, "#000000", 0.55), hl=p.accent,
                auto_hl=True, font_key=c.font_key, weight=typo.FONT_CHOICES.get(c.font_key, ("", 800))[1], line_gap=1.04)
    base.update(kw)
    return TextStyle(**base)


def _sub_style(c: Ctx, **kw) -> TextStyle:
    p = c.pal
    base = dict(fill="#ffffff", stroke=p.ink, stroke_w=0.06, shadow=(0.0, 0.05, 0.04, "#000000", 0.5), font_key=c.font_key
                if c.font_key != "lalezar" else "estedad", weight=700, line_gap=1.2)
    base.update(kw)
    return TextStyle(**base)


def _text_align(c: Ctx) -> str:
    return "right" if c.orient == "wide" else "center"


def _fade_side(c: Ctx, side: str) -> str:
    """لبه‌ای از عکسِ سوژه که باید محو شود تا به متن برسد."""
    if c.orient == "wide":
        return "right" if side == "left" else "left"
    return "top"


def _fallback_hero(c: Ctx, rect, accent: str | None = None, alt: str | None = None) -> None:
    """وقتی عکسِ سوژه نیست: یک «صحنهٔ انتزاعی» (هالهٔ نرم، دو حلقه، چند نقطهٔ شناور) تا جای خالی نماند.

    عمداً هیچ شکلِ کارتونی (انفجار، جرقه) نمی‌گذارد تا خروجیِ نهایی «جاپرکن» به نظر نیاید؛ در گزارش هم هشدار می‌آید که عکسِ سوژه نیست."""
    c.warn_no_subject()
    p = c.pal
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    r = min(rect[2] - rect[0], rect[3] - rect[1]) * 0.42
    a, b = accent or p.accent, alt or p.accent2
    c.add("هالهٔ پسِ صحنه", "fx", P.glow_blob(c.size, (cx, cy), r * 1.4, a, 0.4))
    c.center_add("دیسکِ نرم", "shape", S.circle(r * 0.62, fill=a, alpha=0.18), (cx, cy))
    c.center_add("حلقهٔ بیرونی", "shape", S.ring(r, c.u(4), a, 0.7), (cx, cy))
    c.center_add("حلقهٔ میانیِ خط‌چین", "shape", S.ring(r * 0.76, c.u(3), "#ffffff", 0.4, dash=True), (cx, cy))
    base = c.rnd.uniform(0, 2 * math.pi)
    for i in range(6):                                           # نقطه‌های شناور روی حلقهٔ بیرونی
        ang = base + i * (2 * math.pi / 6) + c.rnd.uniform(-0.25, 0.25)
        rad = c.u(c.rnd.uniform(7, 14))
        c.center_add(f"نقطهٔ تزئینی {i + 1}", "shape", S.circle(rad, fill=b if i % 2 else "#ffffff", alpha=0.85),
                     (cx + math.cos(ang) * r, cy + math.sin(ang) * r))


def _kicker(c: Ctx, rect, *, bg: str | None = None, fg: str | None = None, align: str = "right", px: float = 0.036, slant: float = 0.0):
    text = c.content.get("kicker", "")
    if not typo.plain(text):
        return None
    p = c.pal
    img = typo.label(text, int(c.W * px), font_key="estedad", weight=800, fill=fg or p.ink, bg=bg or p.accent, slant=slant)
    if img is None:
        return None
    x = rect[2] - img.width if align == "right" else (rect[0] if align == "left" else (rect[0] + rect[2]) / 2 - img.width / 2)
    y = rect[3] - img.height
    return c.add("برچسبِ بالای عنوان", "badge", img, (x, y))


def _price_burst(c: Ctx, center, radius: float, fill: str, fg: str | None = None, outline: str | None = None, rot: float = -10):
    text = c.content.get("badge", "")
    if not typo.plain(text):
        return None
    p = c.pal
    center = c.fit_badge(center, radius)                       # روی عنوان/زیرعنوان/برچسب نیفتد
    c.center_add("نشانِ تخفیف/قیمت", "badge", S.burst(radius, fill, outline=outline or p.ink, ow=c.u(5), points=14, rot=rot), center)
    st = TextStyle(fill=fg or pm.on(fill), font_key="lalezar", weight=400, align="center", line_gap=1.0, stroke=None, stroke_w=0.0)
    box = (center[0] - radius * 0.68, center[1] - radius * 0.55, center[0] + radius * 0.68, center[1] + radius * 0.55)
    return c.text("متنِ نشان", text, box, st, max_lines=2, min_f=0.02, max_f=0.09, avoid=False)


# ───────────────────────────── ۱. چهرهٔ بزرگ + متنِ درشت

def face_text(c: Ctx) -> None:
    p = c.pal
    z = c.zones(sub_frac=0.46, text_h=0.42, overlap=0.05)
    tr, sr, side = z["text"], z["subject"], z["side"]
    cx, cy = (sr[0] + sr[2]) / 2, sr[1] + (sr[3] - sr[1]) * 0.5
    if c.bg_wants_photo():
        c.bg_photo(darken=0.22, saturate=1.2, vign=0.35)
        tint = P.gradient(c.size, [(0.0, p.bg1), (1.0, p.bg2)], 35).convert("RGBA")
        tint.putalpha(Image.new("L", c.size, 70))
        c.add("لایهٔ رنگیِ برند", "fx", tint)
        c.scrim(tr, 0.5)
    else:
        c.bg_gradient(35)
        c.auto_texture("rays", color="#ffffff", alpha=0.13, center=(cx, cy), n=18, rot=c.rnd.uniform(0, 20))
    c.add("نورِ پشتِ سوژه", "fx", P.glow_blob(c.size, (cx, cy), max(sr[2] - sr[0], sr[3] - sr[1]) * 0.7, p.accent2, 0.65))
    img, cut = c.subject_rgba()
    if img is None:
        _fallback_hero(c, sr)
    elif cut:
        c.put_cutout("سوژه", img, sr, valign="bottom", outline="#ffffff" if c.spec["subject"]["outline"] else None, ow=c.u(13),
                     glow=(p.accent, c.u(26), 0.5), scale=0.98)
    else:
        c.put_photo("عکسِ سوژه", img, sr, fade=_fade_side(c, side), extent=0.42, focus=(0.5, 0.3))
    if cut:
        _arrow_accent(c, sr, side)
    items = c.stack(tr, [("kicker", 0.17), ("title", 1.0), ("subtitle", 0.4)])
    al = _text_align(c)
    if "kicker" in items:
        _kicker(c, items["kicker"], align="right" if al == "right" else "center", px=0.034)
    if "title" in items:
        c.text("عنوان", c.content["title"], items["title"], _title_style(c, align=al), max_lines=3, max_f=0.19 if c.orient == "wide" else 0.16,
               ax=al if al != "center" else "center", ay="middle")
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align=al), max_lines=2, max_f=0.06, ax=al, ay="top")
    rad = c.W * (0.085 if c.orient == "wide" else 0.115)
    _price_burst(c, _badge_center(c, sr, side, rad), rad, p.accent, fg=pm.on(p.accent))
    c.finish(vign=0.28)


# ───────────────────────────── ۲. قبل / بعد

def split_ba(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    after_img, after_cut = c.subject_rgba(1)
    before_img, before_cut = c.subject_rgba(2)
    if before_img is None and after_img is not None:        # یک عکس بیشتر نیست: «قبل» همان عکسِ کم‌رنگ‌شده است
        before_img, before_cut = after_img, after_cut
    slant = int((W if wide else H) * 0.05)
    th = (y1 - y0) * 0.2
    # «قبل» سمتِ راست (خوانشِ فارسی) و «بعد» سمتِ چپ؛ در قالب‌های بلند: قبل بالا، بعد پایین
    if wide:
        pts_after = [(0, 0), (W / 2 + slant, 0), (W / 2 - slant, H), (0, H)]
        pts_before = [(W / 2 + slant, 0), (W, 0), (W, H), (W / 2 - slant, H)]
        half_after, half_before = (0, 0, W / 2 + slant, H), (W / 2 - slant, 0, W, H)
        subj_after = (0.0, y0 + (y1 - y0) * 0.22, W / 2 + slant * 0.2, y1)
        subj_before = (W / 2 - slant * 0.2, y0 + (y1 - y0) * 0.22, float(W), y1)
    else:
        pts_before = [(0, 0), (W, 0), (W, H / 2 - slant), (0, H / 2 + slant)]
        pts_after = [(0, H / 2 + slant), (W, H / 2 - slant), (W, H), (0, H)]
        half_before, half_after = (0, 0, W, H / 2 + slant), (0, H / 2 - slant, W, H)
        subj_before = (0.0, y0 + th * 1.05, float(W), H / 2 + slant * 0.1)
        subj_after = (0.0, H / 2 + slant * 0.5, float(W), float(H))
    after_bg = P.gradient(c.size, [(0.0, p.bg2), (1.0, p.accent2)], 40)
    before_bg = P.gradient(c.size, [(0.0, "#3b3f4a"), (1.0, "#8a8f9c")], 40)
    for name, pts, bg, half, srect, img, cut, is_before in (
            ("نیمهٔ بعد", pts_after, after_bg, half_after, subj_after, after_img, after_cut, False),
            ("نیمهٔ قبل", pts_before, before_bg, half_before, subj_before, before_img, before_cut, True)):
        base = bg
        if c.bg_wants_photo() and img is None:
            base = P.cover(c.inp.background.convert("RGB"), c.size)
        if img is not None and not cut:
            ph = P.cover(img.convert("RGB"), (int(half[2] - half[0]), int(half[3] - half[1])), (0.5, 0.4))
            if is_before:
                from PIL import ImageFilter

                ph = P.adjust(ph, brightness=0.72, saturation=0.15, contrast=0.9).filter(ImageFilter.GaussianBlur(c.u(2.2)))
            else:
                ph = P.adjust(ph, brightness=1.04, saturation=1.25, contrast=1.08)
            base = base.copy()
            base.paste(ph, (int(half[0]), int(half[1])))
        layer = Image.new("RGBA", c.size, (0, 0, 0, 0))
        layer.paste(base.convert("RGBA"), (0, 0), P.polygon_mask(c.size, pts))
        c.add(name, "background", layer)
        if img is not None and cut:
            tone = _desaturate(img) if is_before else img
            c.put_cutout("سوژهٔ قبل" if is_before else "سوژهٔ بعد", tone, srect, valign="bottom", scale=0.98,
                         outline="#c9ced8" if is_before else "#ffffff", ow=c.u(10), glow=None if is_before else (p.accent, c.u(22), 0.5))
        elif img is None:
            _fallback_hero(c, srect, accent="#9aa0ad" if is_before else p.accent, alt="#6b7280" if is_before else p.accent2)
    # خطِ جداکننده
    line = [(W / 2 + slant, 0), (W / 2 - slant, H)] if wide else [(0, H / 2 + slant), (W, H / 2 - slant)]
    m = P.aa_mask(c.size, lambda d, k: d.line([(x * k, y * k) for x, y in line], fill=255, width=int(c.u(14) * k)))
    div, off = P.stylized(m, "#ffffff", glow=(p.accent, c.u(16), 0.9))
    c.add("خطِ جداکننده", "accent", div, (-off[0], -off[1]))
    mid = (W / 2, H / 2)
    c.center_add("دستگیرهٔ مقایسه", "accent", S.circle(c.u(46), fill="#ffffff", ring=p.accent, ring_w=c.u(6), shadow=True), mid)
    chev = S.chevrons(c.u(40), c.u(26), p.ink, n=2, thick=0.28)
    c.center_add("پیکانِ مقایسه", "accent", chev if wide else chev.rotate(-90, expand=True), mid)
    # برچسب‌ها
    la = c.content.get("label_a") or "بعد"
    lb = c.content.get("label_b") or "قبل"
    px = c.W * 0.05
    after_l = typo.label(la, int(px), font_key="lalezar", weight=400, bg=p.accent, fill=p.ink)
    before_l = typo.label(lb, int(px), font_key="lalezar", weight=400, bg="#111827", fill="#ffffff")
    if wide:
        if after_l:
            c.add("برچسبِ بعد", "badge", after_l, (x0, y0))
        if before_l:
            c.add("برچسبِ قبل", "badge", before_l, (x1 - before_l.width, y0))
    else:
        if before_l:
            c.add("برچسبِ قبل", "badge", before_l, (x0, y0 + th * 1.1))
        if after_l:
            c.add("برچسبِ بعد", "badge", after_l, (x0, H / 2 + slant + c.u(26)))
    # نوارِ عنوان
    if wide:
        bh = int(H * 0.34)
        grad = Image.new("RGBA", (W, bh), (0, 0, 0, 255))
        grad.putalpha(P.edge_ramp((W, bh), "bottom", 1.0, 0.0, 0.9).point(lambda v: int(v * 0.82)))
        c.add("پشتِ عنوان", "fx", grad, (0, H - bh))
        tr = (x0, H - H * 0.3, x1, y1)
    else:
        bh = int(y0 + (y1 - y0) * 0.26)
        grad = Image.new("RGBA", (W, bh), (0, 0, 0, 255))
        grad.putalpha(P.edge_ramp((W, bh), "top", 1.0, 0.0, 0.9).point(lambda v: int(v * 0.82)))
        c.add("پشتِ عنوان", "fx", grad, (0, 0))
        tr = (x0, y0, x1, y0 + th * 1.0)
    items = c.stack(tr, [("title", 1.0), ("subtitle", 0.38)])
    if "title" in items:
        c.text("عنوان", c.content["title"], items["title"], _title_style(c, align="center", auto_hl=True), max_lines=2, max_f=0.1, ay="middle")
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align="center"), max_lines=1, max_f=0.045, ay="top")
    c.finish(vign=0.2)


def _flip_v(mask: Image.Image) -> Image.Image:
    return mask.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def _desaturate(img: Image.Image) -> Image.Image:
    a = img.getchannel("A") if img.mode == "RGBA" else None
    g = P.adjust(img.convert("RGB"), brightness=0.8, saturation=0.12)
    out = g.convert("RGBA")
    if a is not None:
        out.putalpha(a)
    return out


# ───────────────────────────── ۳. عدد / لیست

def number_list(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    z = c.zones(sub_frac=0.42, text_h=0.60)
    tr, sr = z["text"], z["subject"]
    if c.bg_wants_photo():
        c.bg_photo(darken=0.4, saturate=1.1)
        c.scrim(tr, 0.5)
    else:
        c.bg_gradient(60, [(0.0, p.bg1), (1.0, p.bg2)])
    band = P.polygon_mask(c.size, [(0, H * 0.58), (W, H * 0.42), (W, H * 0.58), (0, H * 0.74)] if c.orient != "wide" else
                          [(W * 0.52, 0), (W * 0.66, 0), (W * 0.48, H), (W * 0.34, H)])
    c.add("نوارِ اریب", "fx", P.solid(c.size, p.accent2, band, 0.35))
    c.texture("halftone", color="#ffffff", alpha=0.15, spacing=26, direction=45)
    num = c.content.get("number") or _lead_number(c.content.get("title", ""))
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژه", img, sr, valign="bottom", scale=0.8 if c.orient != "wide" else 0.9, outline="#ffffff", ow=c.u(10),
                     glow=(p.accent, c.u(20), 0.45))
    elif img is not None:
        c.put_photo("عکسِ سوژه", img, sr, fade=_fade_side(c, z["side"]), extent=0.4)
    x0, y0, x1, y1 = tr
    share = 0.58 if c.orient == "wide" else 0.54
    num_rect = (x0, y0, x1, y0 + (y1 - y0) * share)
    title_rect = (x0, y0 + (y1 - y0) * share, x1, y1)
    if num:
        st = TextStyle(fill=p.accent, fill2=P.lerp_hex(p.accent, "#ff7a00", 0.6), stroke=p.ink, stroke_w=0.12,
                       extrude=(p.ink, 0.07), shadow=(0.03, 0.08, 0.05, "#000000", 0.5), font_key="lalezar", weight=400, align="center")
        c.text("عدد", num, num_rect, st, max_lines=1, min_f=0.1, max_f=0.6, ay="middle", ax="center")
    else:
        ic = S.checklist(c.u(300), c.u(300), "#ffffff", p.accent, p.ink, rows=4)
        c.center_add("نمادِ فهرست", "shape", ic, ((num_rect[0] + num_rect[2]) / 2, (num_rect[1] + num_rect[3]) / 2))
    items = c.stack(title_rect, [("title", 1.0), ("subtitle", 0.35)])
    if "title" in items:
        c.text("عنوان", _strip_number(c.content["title"], num), items["title"], _title_style(c, align="center", auto_hl=True), max_lines=3, max_f=0.12)
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align="center"), max_lines=2, max_f=0.05, ay="top")
    if c.has("kicker"):
        _kicker(c, (x0, c.safe[1], x1, c.safe[1] + c.u(70)), align="right" if c.orient == "wide" else "center", px=0.03)
    c.finish(vign=0.22)


def _lead_number(title: str) -> str:
    import re

    m = re.match(r"^\s*\*?([۰-۹0-9]{1,3})\*?(?=\s|$|[:\-–—])", title or "")
    return m.group(1) if m else ""


def _strip_number(title: str, num: str) -> str:
    import re

    t = typo.clean(title)
    if num:
        t2 = re.sub(r"^\s*\*?%s\*?[\s:\-–—]*" % re.escape(num), "", t)
        if typo.plain(t2):
            return t2
    return t


# ───────────────────────────── ۴. سؤال / کنجکاوی

def question_hook(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    z = c.zones(sub_frac=0.44, text_h=0.46, overlap=0.02)
    tr, sr = z["text"], z["subject"]
    cx, cy = (sr[0] + sr[2]) / 2, (sr[1] + sr[3]) / 2
    if c.bg_wants_photo():
        c.bg_photo(darken=0.45, saturate=1.1, vign=0.5)
        c.scrim(tr, 0.45)
    else:
        c.add("پس‌زمینه", "background", P.radial(c.size, (cx, cy), max(W, H) * 0.9, [(0.0, p.bg2), (1.0, p.bg1)]))
    c.add("نورِ نقطه‌ای", "fx", P.glow_blob(c.size, (cx, cy), max(W, H) * 0.5, p.accent, 0.35))
    # علامتِ سؤالِ غولی: لبه‌اش از پشتِ سوژه بیرون می‌زند
    q = TextStyle(fill=p.accent, stroke=None, stroke_w=0.0, font_key="lalezar", weight=400, align="center", rotate=-8)
    if c.orient == "wide":
        qbox = (W * 0.18, H * 0.04, W * 0.78, H * 0.98)
    else:
        qbox = (W * 0.3, sr[1] - H * 0.02, W * 0.98, H * 0.86)
    c.text("علامتِ سؤالِ بزرگ", "؟", qbox, q, max_lines=1, min_f=0.2, max_f=1.2, avoid=False, opacity=0.38, deco=True)
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژه", img, sr, valign="bottom", scale=0.92, outline="#ffffff", ow=c.u(11), glow=(p.accent, c.u(22), 0.5))
    elif img is not None:
        c.put_photo("عکسِ سوژه", img, sr, fade=_fade_side(c, z["side"]), extent=0.4)
    # سه علامتِ ریزِ شناور دورِ سر
    w_, h_ = sr[2] - sr[0], sr[3] - sr[1]
    spots = [(sr[0] + w_ * 0.1, sr[1] + h_ * 0.25), (sr[0] + w_ * 0.88, sr[1] + h_ * 0.18), (sr[0] + w_ * 0.82, sr[1] + h_ * 0.5)]
    for i, (rx, ry) in enumerate(spots):
        s = c.u(c.rnd.uniform(70, 110))
        st = TextStyle(fill=[ "#ffffff", p.accent2, p.accent][i % 3], stroke=p.ink, stroke_w=0.1, font_key="lalezar", weight=400,
                       align="center", rotate=c.rnd.uniform(-22, 22), shadow=(0.02, 0.05, 0.03, "#000000", 0.5))
        c.text(f"علامتِ سؤالِ ریز {i + 1}", "؟", (rx - s, ry - s, rx + s, ry + s), st, max_lines=1, min_f=0.03, max_f=0.2, avoid=False, deco=True)
    if cut:
        _arrow_accent(c, sr, z["side"], color="#ffffff")
    items = c.stack(tr, [("kicker", 0.15), ("title", 1.0), ("subtitle", 0.35)])
    al = _text_align(c)
    if "kicker" in items:
        _kicker(c, items["kicker"], bg=p.accent2, fg=pm.on(p.accent2), align="right" if al == "right" else "center", px=0.032, slant=0.2)
    if "title" in items:
        c.text("عنوان", c.content["title"], items["title"], _title_style(c, align=al), max_lines=3, max_f=0.17, ax=al)
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align=al), max_lines=2, max_f=0.055, ax=al, ay="top")
    c.finish(vign=0.35)


# ───────────────────────────── ۵. مینیمالِ لوکس

def minimal_luxury(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    if c.bg_wants_photo():
        c.bg_photo(darken=0.45, blur=2, vign=0.4)
    else:
        c.add("پس‌زمینه", "background", P.radial(c.size, (W * 0.5, H * 0.42), max(W, H) * 0.85, [(0.0, p.bg2), (1.0, p.bg1)]))
    inset = c.u(26)
    frame = P.aa_mask(c.size, lambda d, k: d.rectangle([inset * k, inset * k, (W - inset) * k, (H - inset) * k], outline=255, width=max(2, int(c.u(1.8) * k))))
    c.add("قابِ باریک", "accent", P.solid(c.size, p.accent, frame, 0.9))
    wide = c.orient == "wide"
    if wide:
        sub_rect = (W * 0.04, y0, W * 0.46, y1)
        text_rect = (W * 0.5, y0 + (y1 - y0) * 0.1, x1, y1 - (y1 - y0) * 0.1)
        if c.subject_side == "right":
            sub_rect, text_rect = (W * 0.54, y0, W * 0.96, y1), (x0, text_rect[1], W * 0.5, text_rect[3])
    else:
        sub_rect = (x0, y0 + (y1 - y0) * 0.38, x1, y1 - (y1 - y0) * 0.04)
        text_rect = (x0 + (x1 - x0) * 0.04, y0 + (y1 - y0) * 0.03, x1 - (x1 - x0) * 0.04, y0 + (y1 - y0) * 0.36)
    if c.bg_wants_photo():
        c.scrim(text_rect, 0.5)
    img, cut = c.subject_rgba()
    cxs, cys = (sub_rect[0] + sub_rect[2]) / 2, (sub_rect[1] + sub_rect[3]) / 2
    if img is not None and cut:
        c.add("درخششِ زیرِ کالا", "fx", P.glow_blob(c.size, (cxs, cys), (sub_rect[2] - sub_rect[0]) * 0.7, p.accent, 0.22))
        c.put_cutout("کالا", img, sub_rect, valign="middle", scale=0.9, shadow=True)
    elif img is not None:
        c.put_photo("عکسِ کالا", img, sub_rect, radius=c.u(10), border=p.accent, bw=c.u(3), shadow=True)
    else:
        r0 = min(sub_rect[2] - sub_rect[0], sub_rect[3] - sub_rect[1])
        c.center_add("حلقهٔ تزئینی", "shape", S.ring(r0 * 0.28, c.u(3), p.accent, 0.9), (cxs, cys))
        c.center_add("حلقهٔ تزئینیِ دوم", "shape", S.ring(r0 * 0.2, c.u(2), p.accent, 0.6, dash=True), (cxs, cys))
    items = c.stack(text_rect, [("kicker", 0.14), ("title", 1.0), ("subtitle", 0.42)])
    al = "center"
    fk = c.font_key if c.font_key != "lalezar" else "estedad"
    if "kicker" in items:
        c.text("برچسبِ بالا", c.content["kicker"], items["kicker"], TextStyle(fill=p.accent, font_key="estedad", weight=700, align=al), max_lines=1,
               max_f=0.036, ay="bottom")
    if "title" in items:
        c.text("عنوان", c.content["title"], items["title"], TextStyle(fill=p.text, hl=p.accent, auto_hl=True, font_key=fk, weight=800, align=al,
                                                                   shadow=(0.0, 0.03, 0.03, "#000000", 0.35), line_gap=1.2), max_lines=3, max_f=0.115, ay="middle")
    if "subtitle" in items:
        ln = P.solid((int(c.u(120)), max(2, int(c.u(2)))), p.accent)
        c.add("خطِ جداکننده", "accent", ln, ((items["subtitle"][0] + items["subtitle"][2]) / 2 - ln.width / 2, items["subtitle"][1] - c.u(4)))
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], TextStyle(fill=p.text, font_key="estedad", weight=500, align=al, line_gap=1.3),
               max_lines=2, max_f=0.048, ay="top")
    c.finish(grain_amount=0.016, vign=0.25)


# ───────────────────────────── ۶. پوسترِ سینمایی

def cinema_poster(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    if wide:                                   # نوارهای سینمایی بالا و پایین؛ متن بینِ آن‌ها
        y0, y1 = max(y0, H * 0.095), min(y1, H * 0.905)
    if c.bg_wants_photo():
        c.bg_photo(grade=0.9, darken=0.15, vign=0.55, focus=(0.5, 0.35))
    else:
        c.add("پس‌زمینه", "background", P.gradient(c.size, [(0.0, p.bg2), (0.55, p.bg1), (1.0, "#02040a")], 90))
        c.add("پرتوِ نور", "fx", P.rays(c.size, (W * 0.5, H * 0.18), 9, p.accent, 0.1, 0, 1.0))
        c.add("مه", "fx", P.glow_blob(c.size, (W * 0.5, H * 0.5), max(W, H) * 0.7, p.accent2, 0.28))
    if wide:
        sr = (W * 0.04, H * 0.075, W * 0.5, H * 0.925) if c.subject_side == "left" else (W * 0.5, H * 0.075, W * 0.96, H * 0.925)
    else:
        sr = (W * 0.08, y0, W * 0.92, H * 0.66)
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژه", img, sr, valign="bottom", scale=1.0, shadow=False, glow=(p.accent2, c.u(34), 0.42), rim=p.accent)
    elif img is not None:
        c.put_photo("عکسِ سوژه", img, sr, fade="bottom" if not wide else None, extent=0.35, focus=(0.5, 0.3))
    ramp = P.edge_ramp(c.size, "bottom", 0.5 if not wide else 1.0, 0.0, 1.0)
    c.add("سایهٔ پایین", "fx", P.solid(c.size, "#02040a", ramp, 0.94))
    if wide:
        tr = (W * 0.48 if c.subject_side == "left" else x0, y0, x1 if c.subject_side == "left" else W * 0.52, y1)
    else:
        tr = (x0, H * 0.64, x1, y1)
    if c.bg_wants_photo():
        c.scrim(tr, 0.5)
    credits_h = (tr[3] - tr[1]) * 0.2 if c.has("credits") else 0
    items = c.stack((tr[0], tr[1], tr[2], tr[3] - credits_h), [("tagline", 0.22), ("title", 1.0), ("subtitle", 0.26)])
    cream, gold = "#fff4d6", P.lerp_hex("#e0b25a", p.accent, 0.15)
    if "tagline" in items:
        c.text("جملهٔ بالای عنوان", c.content["tagline"], items["tagline"], TextStyle(fill=cream, font_key="estedad", weight=500, align="center",
                                                                                    shadow=(0.0, 0.04, 0.04, "#000000", 0.6)), max_lines=2, max_f=0.035, ay="bottom")
    if "title" in items:
        st = TextStyle(fill=cream, fill2=gold, font_key=c.font_key if c.font_key != "lalezar" else "estedad", weight=800, align="center",
                       shadow=(0.0, 0.05, 0.05, "#000000", 0.7), glow=(p.accent2, 0.1, 0.3), line_gap=1.08)
        if c.font_key == "lalezar":
            st.font_key, st.weight = "lalezar", 400
        c.text("عنوانِ پوستر", c.content["title"], items["title"], st, max_lines=2, max_f=0.17 if not wide else 0.12, ay="middle")
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], TextStyle(fill=cream, font_key="estedad", weight=500, align="center"),
               max_lines=2, max_f=0.04, ay="top")
    if credits_h:
        cr = (tr[0], tr[3] - credits_h, tr[2], tr[3])
        c.add("خطِ بلوکِ اعتبار", "accent", P.solid((int(cr[2] - cr[0]), max(1, int(c.u(1.6)))), gold, None, 0.6), (cr[0], cr[1]))
        c.text("بلوکِ اعتبار", c.content["credits"].replace("|", " | "), (cr[0], cr[1] + c.u(8), cr[2], cr[3]),
               TextStyle(fill=cream, font_key="estedad", weight=300, align="center", line_gap=1.35), max_lines=3, max_f=0.024, min_f=0.012, ay="top")
    if wide:
        for yy in (0, H - int(H * 0.075)):
            c.add("نوارِ سینمایی", "fx", Image.new("RGBA", (W, int(H * 0.075)), (0, 0, 0, 255)), (0, yy))
    c.finish(grain_amount=0.02, vign=0.35)


# ───────────────────────────── ۷. کلاژِ پینترستی

def pinterest_collage(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    paper = pm.build("light", c.inp.brand_colors if c.spec["colors"].get("use_brand", True) else [], {"primary": c.spec["colors"].get("primary"),
                                                                                                   "secondary": c.spec["colors"].get("secondary")},
                     int(c.spec["colors"].get("variation") or 0))
    c.pal = paper
    p = paper
    c.add("کاغذ", "background", P.gradient(c.size, [(0.0, "#fbf3e4"), (1.0, "#f2e4cc")], 60))
    c.texture("halftone", color=p.accent, alpha=0.08, spacing=30, direction=None)
    wide = c.orient == "wide"
    photos = [im for im in ([c.inp.subject, c.inp.subject2] + list(c.inp.extra) + ([c.inp.background] if c.inp.background is not None else [])) if im is not None]
    swatches = [p.accent, p.accent2, P.lerp_hex(p.primary, "#ffffff", 0.35), P.lerp_hex(p.accent, "#2b2b2b", 0.2)]
    if wide:
        area = (W * 0.03, y0, W * 0.56, y1)
        text_rect = (W * 0.58, y0, x1, y1)
        if c.subject_side == "right":
            area, text_rect = (W * 0.44, y0, W * 0.97, y1), (x0, y0, W * 0.42, y1)
        cells = _grid(area, 2, 2, c.u(18))
    else:
        area = (x0, y0 + (y1 - y0) * 0.02, x1, y0 + (y1 - y0) * 0.62)
        text_rect = (x0, y0 + (y1 - y0) * 0.66, x1, y1)
        cells = _grid(area, 2, 2, c.u(18)) if c.orient != "tall" else _grid(area, 2, 2, c.u(18))
    rots = [-4.0, 3.0, 2.5, -3.0]
    for i, cell in enumerate(cells[:4]):
        rot = rots[i % 4] + c.rnd.uniform(-1.2, 1.2)
        if i < len(photos):
            c.put_photo(f"کارتِ عکس {i + 1}", photos[i] if photos[i].mode != "RGBA" else _flatten_cut(photos[i], p.paper), _inset(cell, c.u(8)),
                        radius=c.u(18), border="#ffffff", bw=c.u(9), rot=rot, shadow=True, focus=(0.5, 0.35))
        else:
            sw = P.gradient((int(cell[2] - cell[0]), int(cell[3] - cell[1])), [(0.0, swatches[i % 4]), (1.0, P.lerp_hex(swatches[i % 4], "#ffffff", 0.35))], 50)
            c.put_photo(f"کارتِ رنگ {i + 1}", sw, _inset(cell, c.u(8)), radius=c.u(18), border="#ffffff", bw=c.u(9), rot=rot, shadow=True)
    # چسب‌نوار
    for i, cell in enumerate(cells[:2]):
        c.center_add(f"چسب‌نوار {i + 1}", "accent", S.tape(c.u(130), c.u(44), rot=-12 if i == 0 else 10), ((cell[0] + cell[2]) / 2, cell[1] + c.u(10)))
    # عنوان روی نوارِ هایلایت
    items = c.stack(text_rect, [("kicker", 0.14), ("title", 1.0), ("subtitle", 0.4)])
    if "kicker" in items:
        _kicker(c, items["kicker"], bg=p.ink, fg="#ffffff", align="center" if not wide else "right", px=0.03)
    if "title" in items:
        r = items["title"]
        st = TextStyle(fill=p.ink, hl=p.accent, auto_hl=True, font_key=c.font_key, weight=typo.FONT_CHOICES.get(c.font_key, ("", 800))[1],
                       align="center" if not wide else "right", plate=("#ffffff", 0.18, 0.2), shadow=(0.0, 0.03, 0.03, "#000000", 0.18), line_gap=1.12)
        c.text("عنوان", c.content["title"], r, st, max_lines=3, max_f=0.12 if not wide else 0.11, ay="middle")
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], TextStyle(fill=p.ink, font_key="estedad", weight=500,
                                                                             align="center" if not wide else "right"), max_lines=2, max_f=0.04, ay="top")
    if c.has("badge"):
        rad = c.W * (0.075 if wide else 0.1)
        pos = (area[2] - rad * 0.4, area[3] - rad * 0.2) if wide else (x1 - rad * 0.9, area[3] - rad * 0.1)
        _price_burst(c, pos, rad, p.accent, fg=pm.on(p.accent))
    c.finish(grain_amount=0.012)


def _grid(area, cols: int, rows: int, gap: float):
    w = (area[2] - area[0] - gap * (cols - 1)) / cols
    h = (area[3] - area[1] - gap * (rows - 1)) / rows
    out = []
    for r in range(rows):
        for k in range(cols):
            x = area[0] + k * (w + gap)
            y = area[1] + r * (h + gap) + (gap * 2.2 if k % 2 == 1 else 0)
            out.append((x, y, x + w, y + h - (gap * 2.2 if k % 2 == 1 else 0)))
    return out


def _inset(r, d):
    return (r[0] + d, r[1] + d, r[2] - d, r[3] - d)


def _flatten_cut(img: Image.Image, bg: str) -> Image.Image:
    base = Image.new("RGB", img.size, P.rgb(bg))
    base.paste(img.convert("RGBA"), (0, 0), img.convert("RGBA").getchannel("A"))
    return base


# ───────────────────────────── ۸. قهرمانِ محصول

def product_hero(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    cta_img = typo.label(c.content["cta"], int(c.W * 0.04), font_key="estedad", weight=800, fill=pm.on(p.accent), bg=p.accent, radius=0.5) \
        if c.has("cta") else None
    if c.bg_wants_photo():
        c.bg_photo(darken=0.3, blur=6, saturate=1.1, vign=0.3)
    else:
        cx0 = W * (0.5 if not wide else (0.3 if c.subject_side == "left" else 0.7))
        c.add("پس‌زمینه", "background", P.radial(c.size, (cx0, H * 0.5), max(W, H) * 0.9, [(0.0, p.bg2), (1.0, p.bg1)]))
    if wide:
        pr = (W * 0.04, y0, W * 0.5, y1) if c.subject_side == "left" else (W * 0.5, y0, W * 0.96, y1)
        tr = (W * 0.52, y0, x1, y1) if c.subject_side == "left" else (x0, y0, W * 0.48, y1)
    else:
        cta_h = cta_img.height * 1.3 if cta_img else 0
        pr = (x0, y0 + (y1 - y0) * 0.32, x1, y1 - cta_h - (y1 - y0) * 0.03)
        tr = (x0, y0, x1, y0 + (y1 - y0) * 0.3)
    if c.bg_wants_photo():
        c.scrim(tr, 0.5)
    pcx, pcy = (pr[0] + pr[2]) / 2, (pr[1] + pr[3]) / 2
    rr = min(pr[2] - pr[0], pr[3] - pr[1])
    c.center_add("حلقهٔ نور", "shape", S.circle(rr * 0.5, fill=None, ring=p.accent, ring_w=c.u(5), alpha=0.5), (pcx, pcy))
    c.center_add("حلقهٔ نور ۲", "shape", S.circle(rr * 0.4, fill=p.accent, alpha=0.18), (pcx, pcy))
    c.add("درخششِ پشتِ کالا", "fx", P.glow_blob(c.size, (pcx, pcy), rr * 0.8, "#ffffff", 0.3))
    img, cut = c.subject_rgba()
    if img is not None and cut:
        sub = P.contain(P.crop_to_alpha(img), (pr[2] - pr[0]) * 0.88 * c.spec["subject"]["scale"], (pr[3] - pr[1]) * 0.8 * c.spec["subject"]["scale"])
        floor_y = pr[3] - (pr[3] - pr[1]) * 0.1
        refl = sub.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        fade = P.edge_ramp(refl.size, "top", 0.5, 0.0, 1.2).point(lambda v: int(v * 0.28))
        refl.putalpha(ImageChops.multiply(refl.getchannel("A"), fade))
        c.add("بازتابِ کف", "fx", refl, (pcx - sub.width / 2, floor_y - c.u(4)))
        sh = P.glow_blob((int(sub.width * 1.3), int(c.u(60))), (sub.width * 0.65, c.u(30)), sub.width * 0.6, "#000000", 0.6, 2.2)
        c.add("سایهٔ کف", "fx", sh, (pcx - sub.width * 0.65, floor_y - c.u(30)))
        c.add("کالا", "subject", sub, (pcx - sub.width / 2, floor_y - sub.height))
    elif img is not None:
        c.put_photo("عکسِ کالا", img, _inset(pr, rr * 0.08), radius=c.u(22), border="#ffffff", bw=c.u(7), shadow=True)
    else:
        _fallback_hero(c, pr)
    items = c.stack(tr, [("kicker", 0.15), ("title", 1.0), ("subtitle", 0.38)] + ([("cta", 0.3)] if wide else []))
    al = _text_align(c)
    if "kicker" in items:
        _kicker(c, items["kicker"], align="right" if al == "right" else "center", px=0.03)
    if "title" in items:
        c.text("عنوان", c.content["title"], items["title"], _title_style(c, align=al, stroke_w=0.07, auto_hl=True), max_lines=3, max_f=0.12, ax=al)
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align=al, stroke_w=0.0), max_lines=2, max_f=0.045, ax=al, ay="top")
    if cta_img is not None:
        if wide and "cta" in items:
            r = items["cta"]
            x = r[2] - cta_img.width if al == "right" else (r[0] + r[2]) / 2 - cta_img.width / 2
            c.add("دکمهٔ دعوت", "badge", cta_img, (x, (r[1] + r[3]) / 2 - cta_img.height / 2))
        elif not wide:
            c.add("دکمهٔ دعوت", "badge", cta_img, ((W - cta_img.width) / 2, y1 - cta_img.height))
    if c.has("badge"):
        rad = c.W * (0.075 if wide else 0.1)
        pos = (pr[2] - rad * 0.6, pr[1] + rad * 0.9) if wide else (x1 - rad * 0.8, pr[1] + rad * 0.5)
        _price_burst(c, c.clear_of_avoid(pos, rad), rad, p.accent2, fg=pm.on(p.accent2))
    c.finish(vign=0.22)


# ───────────────────────────── ۹. استیکرِ حاشیه‌دار

def sticker_outline(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    z = c.zones(sub_frac=0.46, text_h=0.44, overlap=0.06)
    tr, sr = z["text"], z["subject"]
    base_col = P.lerp_hex(p.accent2, p.bg2, 0.4)
    if c.bg_wants_photo():
        c.bg_photo(darken=0.1, saturate=1.4)
        c.scrim(tr, 0.35)
    else:
        c.add("پس‌زمینه", "background", P.gradient(c.size, [(0.0, base_col), (1.0, P.lerp_hex(base_col, p.bg1, 0.55))], 60))
        c.texture("stripes", color="#ffffff", alpha=0.18, width=60, angle=-35)
    c.add("کنفتی", "fx", S.confetti(c.size, ["#ffffff", p.accent, p.accent2, "#111827"], 38 if c.orient == "wide" else 46, c.rnd.randint(1, 999), c.u(14), c.u(40),
                                    avoid=[tuple(map(int, tr))]))
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژهٔ استیکری", img, sr, valign="bottom", scale=0.95, outline="#ffffff", ow=c.u(24), shadow=True)
    elif img is not None:
        c.put_photo("عکسِ استیکری", img, _inset(sr, c.u(20)), radius=c.u(40), border="#ffffff", bw=c.u(16), shadow=True, rot=-3)
    else:
        _fallback_hero(c, sr, accent="#ffffff", alt=p.accent)
    if cut:
        _arrow_accent(c, sr, z["side"], color="#ffffff")
    items = c.stack(tr, [("kicker", 0.14), ("title", 1.0), ("subtitle", 0.36)])
    al = _text_align(c)
    if "kicker" in items:
        _kicker(c, items["kicker"], bg="#111827", fg="#ffffff", align="right" if al == "right" else "center", px=0.032)
    if "title" in items:
        st = TextStyle(fill=p.accent, hl=p.ink, auto_hl=True, stroke="#ffffff", stroke_w=0.17, extrude=("#111827", 0.1),
                       shadow=(0.02, 0.08, 0.05, "#000000", 0.35), font_key="lalezar", weight=400, align=al, rotate=-3.5, line_gap=1.0)
        c.text("عنوانِ استیکری", c.content["title"], items["title"], st, max_lines=3, max_f=0.17, ax=al)
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align=al, stroke="#111827", stroke_w=0.12, fill="#ffffff"), max_lines=2, max_f=0.05, ax=al, ay="top")
    rad = c.W * (0.085 if c.orient == "wide" else 0.11)
    _price_burst(c, _badge_center(c, sr, z["side"], rad), rad, "#ffffff", fg="#111827", outline="#111827", rot=-14)
    c.finish()


# ───────────────────────────── ۱۰. نئون

def neon(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    z = c.zones(sub_frac=0.44, text_h=0.44, overlap=0.03)
    tr, sr = z["text"], z["subject"]
    if c.bg_wants_photo():
        c.bg_photo(darken=0.65, saturate=1.3, vign=0.5)
        c.scrim(tr, 0.4)
    else:
        c.add("پس‌زمینه", "background", P.gradient(c.size, [(0.0, p.bg1), (1.0, p.bg2)], 90))
    # شبکهٔ کفِ پرسپکتیو
    grid = Image.new("RGBA", c.size, (0, 0, 0, 0))
    from PIL import ImageDraw as _D

    d = _D.Draw(grid)
    hy = H * 0.62
    vp = (W * 0.5, hy)
    col = P.rgba(p.accent2, 150)
    for i in range(-14, 15):
        d.line([vp, (vp[0] + i * W * 0.14, H)], fill=col, width=max(1, int(c.u(2))))
    y, step = hy, c.u(14)
    while y < H:
        d.line([(0, y), (W, y)], fill=col, width=max(1, int(c.u(2))))
        y += step
        step *= 1.32
    fade = P.edge_ramp(c.size, "top", 0.5, hy / H, 1.0).point(lambda v: 255 - v)
    grid.putalpha(ImageChops.multiply(grid.getchannel("A"), fade))
    c.add("شبکهٔ کف", "fx", grid)
    c.add("هالهٔ نئونیِ اول", "fx", P.glow_blob(c.size, (W * 0.25, H * 0.3), max(W, H) * 0.5, p.accent, 0.4))
    c.add("هالهٔ نئونیِ دوم", "fx", P.glow_blob(c.size, (W * 0.8, H * 0.65), max(W, H) * 0.5, p.accent2, 0.38))
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژه", img, sr, valign="bottom", scale=0.95, outline=None, ow=0, shadow=False, glow=(p.accent2, c.u(30), 0.65), rim=p.accent2)
    elif img is not None:
        c.put_photo("عکسِ سوژه", img, sr, fade=_fade_side(c, z["side"]), extent=0.4)
    else:
        _fallback_hero(c, sr, accent=p.accent2, alt=p.accent)
    items = c.stack(tr, [("kicker", 0.14), ("title", 1.0), ("subtitle", 0.36)])
    al = _text_align(c)
    if "kicker" in items:
        c.text("برچسبِ نئونی", c.content["kicker"], items["kicker"], TextStyle(fill="#ffffff", glow=(p.accent2, 0.35, 0.9), font_key="estedad", weight=700,
                                                                               align=al), max_lines=1, max_f=0.034, ax=al, ay="bottom")
    if "title" in items:
        st = TextStyle(fill="#ffffff", stroke=p.accent, stroke_w=0.035, glow=(p.accent, 0.22, 0.95), font_key=c.font_key,
                       weight=typo.FONT_CHOICES.get(c.font_key, ("", 800))[1], align=al, hl=p.accent2, auto_hl=True, line_gap=1.04)
        c.text("عنوانِ نئونی", c.content["title"], items["title"], st, max_lines=3, max_f=0.16, ax=al)
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], TextStyle(fill="#e9d5ff", font_key="estedad", weight=500, align=al,
                                                                              glow=(p.accent, 0.15, 0.6)), max_lines=2, max_f=0.045, ax=al, ay="top")
    x0, y0, x1, y1 = c.safe
    inset = c.u(22)
    fr = P.aa_mask(c.size, lambda dr, k: dr.rounded_rectangle([inset * k, inset * k, (W - inset) * k, (H - inset) * k], radius=c.u(18) * k, outline=255, width=max(2, int(c.u(3) * k))))
    st_img, off = P.stylized(fr, p.accent, glow=(p.accent, c.u(10), 0.9))
    c.add("قابِ نئونی", "accent", st_img, (-off[0], -off[1]))
    c.finish(vign=0.3)


# ───────────────────────────── ۱۱. تیترِ خبری

def news_bold(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    red = "#d90429" if not c.spec["colors"].get("primary") and not c.inp.brand_colors else p.accent
    band_top = H * (0.52 if wide else 0.56)
    if c.bg_wants_photo():
        c.bg_photo(darken=0.2, saturate=1.15, vign=0.3)
    else:
        c.add("پس‌زمینه", "background", P.gradient(c.size, [(0.0, "#0b1020"), (1.0, p.bg2)], 50))
        c.texture("halftone", color="#ffffff", alpha=0.12, spacing=20, direction=0)
    if wide:
        sr = (0.0, 0.0, W * 0.42, band_top + H * 0.14) if c.subject_side == "left" else (W * 0.58, 0.0, float(W), band_top + H * 0.14)
    else:
        sr = (W * 0.1, y0, W * 0.9, band_top + H * 0.1)
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژه", img, sr, valign="bottom", scale=1.0, outline="#ffffff", ow=c.u(8), shadow=True)
    elif img is not None:
        c.put_photo("عکسِ سوژه", img, sr, fade=_fade_side(c, c.subject_side) if wide else "bottom", extent=0.3)
    else:
        _fallback_hero(c, sr, accent=red, alt=p.accent2)
    pts = [(0, band_top + c.u(30)), (W, band_top - c.u(10)), (W, H), (0, H)]
    c.add("نوارِ عنوان", "fx", P.solid(c.size, "#05070d", P.polygon_mask(c.size, pts), 1.0))
    stripe = P.polygon_mask(c.size, [(0, band_top + c.u(20)), (W, band_top - c.u(20)), (W, band_top - c.u(2)), (0, band_top + c.u(38))])
    c.add("لبهٔ رنگیِ نوار", "accent", P.solid(c.size, red, stripe))
    if wide:
        tr = (W * 0.4, band_top + c.u(14), x1, y1) if c.subject_side == "left" else (x0, band_top + c.u(14), W * 0.6, y1)
        al = "right"
    else:
        tr = (x0, band_top + c.u(30), x1, y1)
        al = "right"
    items = c.stack(tr, [("title", 1.0), ("subtitle", 0.34)])
    if "title" in items:
        c.text("عنوان", c.content["title"], items["title"], _title_style(c, align=al, stroke_w=0.0, shadow=(0.0, 0.04, 0.03, "#000000", 0.6),
                                                                         hl="#ffd60a", auto_hl=True), max_lines=3, max_f=0.13, ax=al)
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align=al, stroke_w=0.0, fill="#ffd60a"), max_lines=2, max_f=0.045, ax=al, ay="top")
    kick = c.content.get("kicker") or "ویژه"
    img_l = typo.label(kick, int(c.W * 0.045), font_key="lalezar", weight=400, fill="#ffffff", bg=red, slant=0.3, radius=0.2)
    if img_l:
        ky = (y0 if wide else band_top - img_l.height - c.u(34))
        c.add("برچسبِ خبری", "badge", img_l, (x1 - img_l.width, ky))
    c.finish(vign=0.2)


# ───────────────────────────── ۱۲. رویارویی

def versus(c: Ctx) -> None:
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    ia, ca = c.subject_rgba(1)
    ib, cb = c.subject_rgba(2)
    th = (y1 - y0) * (0.3 if wide else 0.2)
    if wide:
        ra, rb = (W * 0.02, y0 + th * 0.9, W * 0.5, float(H)), (W * 0.5, y0 + th * 0.9, W * 0.98, float(H))
    else:
        ra, rb = (0.0, H * 0.5, W * 0.62, float(H)), (W * 0.38, y0 + th * 1.05, float(W), H * 0.62)
    sa, sb = p.accent, p.accent2
    left = P.gradient(c.size, [(0.0, P.lerp_hex(sa, p.bg1, 0.5)), (1.0, p.bg1)], 20)
    right = P.gradient(c.size, [(0.0, p.bg1), (1.0, P.lerp_hex(sb, p.bg1, 0.45))], 20)
    mask_l = P.polygon_mask(c.size, [(0, 0), (W * 0.56, 0), (W * 0.44, H), (0, H)] if wide else [(0, 0), (W, 0), (W, H * 0.46), (0, H * 0.54)])
    base = right.convert("RGBA")
    base.paste(left.convert("RGBA"), (0, 0), mask_l)
    c.add("پس‌زمینهٔ دوتکه", "background", base)
    c.texture("rays", color="#ffffff", alpha=0.08, center=(W / 2, H / 2), n=22)
    for name, img, cut, rect, col in (("سوژهٔ اول", ia, ca, ra, sa), ("سوژهٔ دوم", ib, cb, rb, sb)):
        if img is not None and cut:
            c.put_cutout(name, img, rect, valign="bottom", scale=0.98, outline="#ffffff", ow=c.u(9), glow=(col, c.u(24), 0.55))
        elif img is not None:
            c.put_photo(name, img, _inset(rect, c.u(10)), radius=c.u(24), border="#ffffff", bw=c.u(8), shadow=True)
        else:
            _fallback_hero(c, rect, accent=col, alt="#ffffff")
    vs = TextStyle(fill="#ffffff", stroke=p.ink, stroke_w=0.1, extrude=(p.accent, 0.07), shadow=(0.03, 0.07, 0.05, "#000000", 0.5), font_key="lalezar",
                   weight=400, align="center", glow=("#ffd60a", 0.2, 0.6))
    vr = c.u(150)
    c.text("نشانِ رویارویی", "VS", (W / 2 - vr, H / 2 - vr * 0.8, W / 2 + vr, H / 2 + vr * 0.8), vs, max_lines=1, min_f=0.05, max_f=0.2, avoid=False)
    la, lb = c.content.get("label_a"), c.content.get("label_b")
    px = c.W * 0.04
    ly = (y1 - c.u(66)) if wide else None
    if la:
        img_a = typo.label(la, int(px), font_key="lalezar", weight=400, fill=pm.on(sa), bg=sa)
        if img_a:
            c.add("نامِ سوژهٔ اول", "badge", img_a, (ra[0] + c.u(20), ly if ly is not None else ra[3] - img_a.height - c.u(20)))
    if lb:
        img_b = typo.label(lb, int(px), font_key="lalezar", weight=400, fill=pm.on(sb), bg=sb)
        if img_b:
            c.add("نامِ سوژهٔ دوم", "badge", img_b, (rb[2] - img_b.width - c.u(20), ly if ly is not None else rb[3] - img_b.height - c.u(14)))
    items = c.stack((x0, y0, x1, y0 + th), [("title", 1.0), ("subtitle", 0.3)])
    if "title" in items:
        c.text("عنوان", c.content["title"], items["title"], _title_style(c, align="center"), max_lines=2, max_f=0.1, ay="middle")
    if "subtitle" in items:
        c.text("زیرعنوان", c.content["subtitle"], items["subtitle"], _sub_style(c, align="center"), max_lines=1, max_f=0.04, ay="top")
    c.finish(vign=0.28)


def _arrow_accent(c: Ctx, sr, side: str, color: str | None = None) -> None:
    """فلشِ ضخمِ «اینجا را ببین» که به سوژه اشاره می‌کند (کنارِ سر، نه روی چهره)؛ با ``accents.arrow`` خاموش می‌شود."""
    if not c.spec.get("accents", {}).get("arrow", True) or c.inp.subject is None:
        return
    p = c.pal
    L = c.W * (0.115 if c.orient == "wide" else 0.2)
    T_ = L * 0.2
    col = color or p.accent
    ow = c.u(7)
    if c.orient == "wide":
        # سوژه چپ ⇒ فلش کنارِ شانهٔ سوژه (سمتِ متن) و رو به چپ؛ سوژه راست ⇒ برعکس
        cx = sr[2] - c.W * 0.085 if side == "left" else sr[0] + c.W * 0.085
        cy = c.H * 0.5
        img = S.arrow(L, T_, col, p.ink, ow, bend=-0.3, angle=20)
        if side == "left":
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    else:
        cx = c.W * 0.15
        cy = sr[1] + (c.H - sr[1]) * 0.16
        img = S.arrow(L, T_, col, p.ink, ow, bend=-0.3, angle=20)
    c.center_add("فلشِ اشاره", "accent", img, (cx, cy))


def _badge_center(c: Ctx, sr, side: str, rad: float):
    """جای نشانِ گرد: روی شانهٔ سوژه (نه روی چهره) و بیرونِ ناحیه‌های پرهیز."""
    x0, y0, x1, y1 = c.safe
    if c.orient == "wide":
        edge = sr[2] if side == "left" else sr[0]
        pos = (edge - rad * 1.1 if side == "left" else edge + rad * 1.1, y1 - rad * 1.2)
    else:
        pos = (x1 - rad, sr[1] + rad * 1.3)
    return c.clear_of_avoid(pos, rad)


# ───────────────────────────── ۱۳. جلدِ مجله

def magazine_cover(c: Ctx) -> None:
    """جلدِ مجله: سرلوحهٔ بزرگ در بالا که سر/شانهٔ سوژه کمی روی آن می‌نشیند؛ تیترهای کاور پایین (یا ستونِ کناری در قابِ افقی)."""
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    photo_bg = c.bg_wants_photo()
    sh = y1 - y0
    light_text = photo_bg or p.dark
    if photo_bg:
        c.bg_photo(darken=0.18, saturate=1.1, vign=0.3)
    else:
        c.bg_gradient(75, [(0.0, p.bg1 if p.dark else P.lerp_hex(p.bg1, "#ffffff", 0.35)), (1.0, p.bg2)])
        gx = W * 0.5 if not wide else (W * 0.27 if c.subject_side == "left" else W * 0.73)
        c.add("نورِ پشتِ سوژه", "fx", P.glow_blob(c.size, (gx, H * 0.55), max(W, H) * 0.55, p.accent2, 0.4))
    top = y0 + sh * 0.01
    strap_h = sh * 0.06 if c.has("kicker") else 0.0
    mast_h = sh * (0.3 if wide else 0.22)
    mast = (x0, top + strap_h, x1, top + strap_h + mast_h)
    if strap_h:
        c.text("سطرِ بالای سرلوحه", c.content["kicker"], (x0, top, x1, top + strap_h),
               TextStyle(fill="#ffffff" if light_text else p.accent, font_key="estedad", weight=800, align="center"), max_lines=1, max_f=0.032, ay="middle")
        c.add("خطِ زیرِ سطرِ بالا", "accent", P.solid((int(x1 - x0), max(2, int(c.u(2.5)))), "#ffffff" if light_text else p.ink, None, 0.8), (x0, top + strap_h))
    mfont = typo.FONT_CHOICES.get(c.font_key, ("", 800))[1]
    c.text("عنوانِ سرلوحه", c.content.get("title", ""), mast,
           TextStyle(fill="#ffffff" if light_text else p.accent, stroke=p.ink if photo_bg else None, stroke_w=0.06 if photo_bg else 0.0, font_key=c.font_key,
                     weight=mfont, align="center", line_gap=0.95, shadow=(0.0, 0.03, 0.04, "#000000", 0.25)),
           max_lines=2, max_f=0.2 if not wide else 0.15, ay="middle")
    # سوژه: سرش کمی روی سرلوحه می‌افتد
    sub_top = mast[3] - mast_h * 0.1
    if wide:
        sr = (W * 0.04, sub_top, W * 0.5, float(H)) if c.subject_side == "left" else (W * 0.5, sub_top, W * 0.96, float(H))
    else:
        plate_top = y1 - sh * 0.27                  # صفحهٔ تیترهای کاور؛ سوژه روی آن می‌نشیند و چهره همیشه بالای آن می‌ماند
        sr = (W * 0.1, sub_top, W * 0.9, plate_top + sh * 0.04)
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژه", img, sr, valign="bottom", scale=1.0, shadow=True, glow=(p.accent2, c.u(22), 0.35))
    elif img is not None:
        c.put_photo("عکسِ سوژه", img, sr if wide else (0.0, sub_top, float(W), float(H)), fade="top", extent=0.22, focus=(0.5, 0.3))
    else:
        _fallback_hero(c, sr, accent=p.accent, alt=p.accent2)
    # تیترهای کاور
    if wide:
        col = (W * 0.52, mast[3] + sh * 0.04, x1, y1) if c.subject_side == "left" else (x0, mast[3] + sh * 0.04, W * 0.48, y1)
        tcol = "#ffffff" if light_text else p.ink
        if photo_bg:
            c.scrim(col, 0.4)
        shade = (0.0, 0.04, 0.05, "#000000", 0.4) if light_text else None
    else:
        fade = max(2, int(sh * 0.06))
        ph = int(H - plate_top) + fade
        mask = Image.new("L", (W, ph), 235)
        mask.paste(Image.linear_gradient("L").resize((W, fade)).point(lambda v: int(v * 235 / 255)), (0, 0))
        c.add("صفحهٔ تیترهای کاور", "fx", P.solid((W, ph), "#000000" if photo_bg else p.ink, mask), (0, int(plate_top) - fade))
        c.add("خطِ رنگیِ صفحه", "accent", P.solid((W, max(2, int(c.u(4)))), p.accent), (0, int(plate_top)))
        col = (x0 + (x1 - x0) * 0.04, plate_top + c.u(18), x1 - (x1 - x0) * 0.04, y1)
        tcol = "#ffffff"
        shade = (0.0, 0.04, 0.05, "#000000", 0.4)
    items = c.stack(col, [("subtitle", 1.0), ("tagline", 0.5)])
    if "subtitle" in items:
        r = items["subtitle"]
        bar_w = int((col[2] - col[0]) * 0.16)
        if wide:
            c.add("نوارِ رنگیِ تیتر", "accent", P.solid((bar_w, max(3, int(c.u(6)))), p.accent), (col[2] - bar_w, r[1]))
        c.text("تیترِ اصلیِ کاور", c.content["subtitle"], (r[0], r[1] + (c.u(14) if wide else 0), r[2], r[3]),
               TextStyle(fill=tcol, hl=p.accent, auto_hl=True, font_key="estedad", weight=800, align="right", line_gap=1.2, shadow=shade),
               max_lines=2, max_f=0.07 if not wide else 0.062, ax="right", ay="top")
    if "tagline" in items:
        c.text("تیترِ دومِ کاور", c.content["tagline"], items["tagline"],
               TextStyle(fill=tcol, font_key="estedad", weight=500, align="right", line_gap=1.25, shadow=shade),
               max_lines=2, max_f=0.04, ax="right", ay="top")
    rad = c.W * (0.085 if wide else 0.11)
    if wide:
        pos = (sr[2] - rad * 0.9, mast[3] + rad * 1.5) if c.subject_side == "left" else (sr[0] + rad * 0.9, mast[3] + rad * 1.5)
    else:
        pos = (W * 0.82, mast[3] + rad * 1.4)
    _price_burst(c, c.clear_of_avoid(pos, rad), rad, p.accent if p.dark else p.accent2, fg=None, rot=12)
    c.finish(grain_amount=0.012, vign=0.12)


# ───────────────────────────── ۱۴. پوسترِ قدیمی (رترو)

def _retro_grade(img: Image.Image, dark: str, light: str, strength: float = 0.3) -> Image.Image:
    """رنگ‌بندیِ چاپِ قدیمی روی سوژه (شفافیت می‌ماند)."""
    rgba = img.convert("RGBA")
    graded = P.tint_duotone(rgba, dark, light, strength).convert("RGBA")
    graded.putalpha(rgba.getchannel("A"))
    return graded


def retro_poster(c: Ctx) -> None:
    """پوسترِ چاپیِ قدیمی: کاغذِ کرم، خورشیدِ پرتوی، حلقه‌های هم‌مرکز، نوارِ عنوان با لبه‌های بریده و قابِ دوخطی."""
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    cream = P.lerp_hex(p.paper, "#efdcae", 0.55)
    cream_hi = P.lerp_hex(cream, "#ffffff", 0.35)
    main = p.bg1 if p.dark else p.accent
    second, hot, ink = p.bg2, p.accent, p.ink
    if wide:
        left = c.subject_side == "left"
        scx = W * (0.27 if left else 0.73)
        sr = (W * 0.04, H * 0.1, W * 0.5, H * 0.97) if left else (W * 0.5, H * 0.1, W * 0.96, H * 0.97)
        scy = H * 0.52
        rr = min(W * 0.2, H * 0.42)
    else:
        scx, scy = W * 0.5, H * (0.37 if H / W > 1.2 else 0.4)
        sr = (W * 0.1, y0 + (y1 - y0) * 0.08, W * 0.9, y0 + (y1 - y0) * 0.72)
        rr = min(W * 0.36, H * 0.22)
    if c.bg_wants_photo():
        c.bg_photo(darken=0.0, saturate=0.7, vign=0.15)
        c.add("لایهٔ کاغذی", "fx", Image.new("RGBA", c.size, P.rgba(cream, 150)))
    else:
        c.add("کاغذ", "background", P.radial(c.size, (W / 2, H / 2), max(W, H) * 0.75, [(0.0, cream_hi), (1.0, P.lerp_hex(cream, "#8a6a3a", 0.25))]))
    c.add("پرتوهای خورشید", "texture", P.rays(c.size, (scx, scy), 26, second, 0.22, c.rnd.uniform(0, 10)))
    c.center_add("حلقهٔ بیرونی", "shape", S.ring(rr * 1.38, c.u(4), ink, 0.85), (scx, scy))
    c.center_add("حلقهٔ میانی", "shape", S.ring(rr * 1.2, c.u(10), main, 0.9), (scx, scy))
    c.center_add("خورشید", "shape", S.circle(rr, fill=hot, ring=ink, ring_w=c.u(6)), (scx, scy))
    c.texture("halftone", color=ink, alpha=0.1, spacing=16, direction=90)
    img, cut = c.subject_rgba()
    if img is not None and cut:
        c.put_cutout("سوژه", _retro_grade(img, ink, cream, 0.28), sr, valign="bottom", scale=1.0, outline=ink, ow=c.u(10), shadow=False)
    elif img is not None:
        c.put_photo("عکسِ سوژه", _retro_grade(img, ink, cream, 0.35).convert("RGB"),
                    (sr[0] + c.u(10), sr[1], sr[2] - c.u(10), sr[3] - (0 if wide else (y1 - y0) * 0.04)), radius=c.u(14), border=ink, bw=c.u(9), shadow=False)
    else:
        _fallback_hero(c, sr, accent=main, alt=hot)
    # نوارِ عنوان با لبه‌های بریده
    if wide:
        bx0, bx1 = (W * 0.5, x1) if c.subject_side == "left" else (x0, W * 0.5)
        by0, by1 = H * 0.33, H * 0.58
    else:
        bx0, bx1 = x0, x1
        by0 = y0 + (y1 - y0) * 0.66
        by1 = by0 + (y1 - y0) * 0.17
    notch = c.u(30)
    ex = notch * 0.4
    pts = [(bx0 - ex, by0), (bx1 + ex, by0), (bx1 + ex - notch * 0.6, (by0 + by1) / 2), (bx1 + ex, by1), (bx0 - ex, by1), (bx0 - ex + notch * 0.6, (by0 + by1) / 2)]
    ribbon = P.polygon_mask(c.size, pts)
    c.add("سایهٔ نوار", "fx", P.solid(c.size, "#000000", P.blur_alpha(ImageChops.offset(ribbon, int(c.u(5)), int(c.u(8))), c.u(6)), 0.35))
    c.add("نوارِ عنوان", "accent", P.solid(c.size, main, ribbon))
    edge = P.polygon_mask(c.size, [(bx0 - ex + c.u(10), by0 + c.u(10)), (bx1 + ex - c.u(10), by0 + c.u(10)), (bx1 + ex - c.u(10), by0 + c.u(13)), (bx0 - ex + c.u(10), by0 + c.u(13))])
    c.add("خطِ نوار", "accent", P.solid(c.size, cream, edge, 0.6))
    tb = (bx0 + notch, by0 + c.u(8), bx1 - notch, by1 - c.u(8))
    c.text("عنوانِ پوستر", c.content.get("title", ""), tb,
           TextStyle(fill=cream_hi, hl=hot, auto_hl=True, font_key=c.font_key, weight=typo.FONT_CHOICES.get(c.font_key, ("", 800))[1], align="center", line_gap=1.0),
           max_lines=2, max_f=0.15 if not wide else 0.1, ay="middle")
    rest = c.stack((bx0, by1 + c.u(12), bx1, y1 if not wide else H * 0.88), [("subtitle", 1.0), ("tagline", 0.55)])
    if "subtitle" in rest:
        c.text("زیرعنوان", c.content["subtitle"], rest["subtitle"], TextStyle(fill=ink, font_key="estedad", weight=800, align="center", line_gap=1.2),
               max_lines=2, max_f=0.05, ay="top")
    if "tagline" in rest:
        c.text("جملهٔ ریز", c.content["tagline"], rest["tagline"], TextStyle(fill=P.lerp_hex(ink, cream, 0.25), font_key="estedad", weight=500, align="center"),
               max_lines=2, max_f=0.034, ay="top")
    # قابِ دوخطی
    for k, (ins, w_) in enumerate(((c.u(20), 6), (c.u(36), 2))):
        fr = P.aa_mask(c.size, lambda d, s, ins=ins, w_=w_: d.rectangle([ins * s, ins * s, (W - ins) * s, (H - ins) * s], outline=255, width=max(1, int(c.u(w_) * s))))
        c.add("قابِ دوخطی", "accent", P.solid(c.size, ink, fr, 0.9 if k == 0 else 0.7))
    if c.has("kicker"):
        lab = typo.label(c.content["kicker"], int(c.W * 0.03), font_key="estedad", weight=800, fill=cream_hi, bg=ink, radius=0.2)
        if lab:
            c.add("برچسبِ بالا", "badge", lab, (W / 2 - lab.width / 2, c.u(24) - lab.height / 2))
    rad = c.W * (0.085 if wide else 0.1)
    _price_burst(c, c.clear_of_avoid((sr[2] - rad, sr[1] + rad * 1.2), rad), rad, hot, fg=pm.on(hot), outline=ink, rot=-12)
    c.finish(grain_amount=0.03, vign=0.2)


# ───────────────────────────── ۱۵. کارتِ نقل‌قول

def _avatar(c: Ctx, img: Image.Image, cut: bool, radius: float) -> Image.Image:
    """سوژه در دایره (برای نقل‌قول): بریده ⇒ روی دیسکِ رنگی، عکس ⇒ کراپِ دایره‌ای."""
    d = int(radius * 2)
    disc = P.rounded_mask((d, d), radius)
    if cut:
        base = Image.alpha_composite(Image.new("RGBA", (d, d), (0, 0, 0, 0)), P.solid((d, d), c.pal.accent2, disc))
        sub = P.contain(P.crop_to_alpha(img), d * 0.96, d * 1.0)
        base.alpha_composite(sub, ((d - sub.width) // 2, d - sub.height))
    else:
        base = P.cover(img.convert("RGB"), (d, d), (0.5, 0.35)).convert("RGBA")
    base.putalpha(ImageChops.multiply(base.getchannel("A"), disc))
    return base


def quote_card(c: Ctx) -> None:
    """کارتِ نقل‌قول: علامتِ نقل‌قولِ بزرگ، متنِ وسط‌چین با کلمهٔ رنگی، خطِ جداکننده و نامِ گوینده؛ سوژه (اختیاری) در دایره."""
    p = c.pal
    W, H = c.W, c.H
    x0, y0, x1, y1 = c.safe
    wide = c.orient == "wide"
    sh = y1 - y0
    if c.bg_wants_photo():
        c.bg_photo(darken=0.5, blur=5, saturate=1.0, vign=0.45)
    else:
        c.bg_gradient(60, [(0.0, p.bg1), (1.0, p.bg2)])
        c.add("نور", "fx", P.glow_blob(c.size, (W * 0.5, H * 0.35), max(W, H) * 0.6, p.accent2, 0.3))
        c.texture("grid", color="#ffffff", alpha=0.035)
    img, cut = c.subject_rgba()
    has_av = img is not None
    if wide:
        left = c.subject_side == "left"
        col_w = (x1 - x0) * 0.3
        av_c = ((x0 + col_w * 0.5) if left else (x1 - col_w * 0.5), (y0 + y1) / 2)
        av_r = min(col_w * 0.5, sh * 0.34)
        tx0, tx1 = ((x0 + col_w + c.u(24), x1) if left else (x0, x1 - col_w - c.u(24))) if has_av else (x0, x1)
        area = (tx0, y0, tx1, y1)
    else:
        area = (x0, y0, x1, y1)
        av_r = min(W * 0.14, sh * 0.13)
        av_c = (W / 2, y1 - av_r * 1.05)
    ax0, ay0, ax1, ay1 = area
    ah = ay1 - ay0
    avatar_h = av_r * 2.3 if (has_av and not wide) else 0.0
    kick_h = ah * 0.06 if c.has("kicker") else 0.0
    if kick_h:
        c.text("برچسبِ بالا", c.content["kicker"], (ax0, ay0, ax1, ay0 + kick_h), TextStyle(fill=p.accent, font_key="estedad", weight=800, align="center"),
               max_lines=1, max_f=0.03, ay="middle")
    q_h = ah * (0.2 if not wide else 0.24)
    qy = ay0 + kick_h
    cx = (ax0 + ax1) / 2
    c.center_add("نشانِ نقل‌قول", "accent", S.quote_mark(q_h * 0.95, p.accent, closing=False), (cx, qy + q_h * 0.55))
    sub_h = ah * 0.16 if c.has("subtitle") else 0.0
    qt = (ax0 + (ax1 - ax0) * 0.04, qy + q_h * 1.05, ax1 - (ax1 - ax0) * 0.04, ay1 - avatar_h - sub_h - c.u(18))
    c.text("عنوانِ نقل‌قول", c.content.get("title", ""), qt,
           TextStyle(fill=p.text, hl=p.accent, auto_hl=True, font_key="estedad", weight=700, align="center", line_gap=1.4, shadow=(0.0, 0.03, 0.04, "#000000", 0.35)),
           max_lines=6, max_f=0.095 if not wide else 0.072, min_f=0.026, ay="middle")
    if sub_h:
        ly = qt[3] + c.u(8)
        ln = P.solid((int((ax1 - ax0) * 0.14), max(2, int(c.u(3)))), p.accent)
        c.add("خطِ جداکننده", "accent", ln, (cx - ln.width / 2, ly))
        c.text("گوینده", c.content["subtitle"], (ax0, ly + c.u(12), ax1, ly + c.u(12) + sub_h),
               TextStyle(fill=p.text, font_key="estedad", weight=600, align="center"), max_lines=1, max_f=0.04, ay="top")
    if has_av:
        c.center_add("سوژه", "subject", _avatar(c, img, cut, av_r), av_c)
        c.center_add("حلقهٔ سوژه", "accent", S.ring(av_r, c.u(7), "#ffffff", 1.0), av_c)
    c.finish(grain_amount=0.012, vign=0.2)


# ───────────────────────────── فهرست

COMMON = [("title", "عنوان"), ("subtitle", "زیرعنوان")]

STYLES: dict[str, StyleDef] = {s.key: s for s in (
    StyleDef("face_text", "چهرهٔ بزرگ + متنِ درشت", "سوژهٔ بریده، نورِ رنگی، عنوانِ درشت با حاشیه", "الگوی رایجِ تامنیل‌های پربازدید: یک چهره (یا کالا) خیلی بزرگ و مستقیم، پس‌زمینهٔ پرنور و پرتوی، و فقط ۲ تا ۴ کلمهٔ درشتِ پررنگ با لبهٔ ضخیم؛ کلمهٔ مهم زرد.",
             face_text, "vivid", "lalezar", "youtube", "recommended", [("kicker", "برچسبِ بالا"), ("title", "عنوان"), ("subtitle", "زیرعنوان"), ("badge", "نشان (قیمت/تخفیف)")],
             ["youtube", "aparat", "telegram", "ig_square", "ig_portrait", "story"], tips=["عنوان ۲ تا ۴ کلمه؛ کلمهٔ مهم را با * دورش بگذارید.", "چهره با نگاهِ مستقیم و بزرگ بهتر کلیک می‌گیرد."]),
    StyleDef("split_ba", "قبل / بعد", "دو نیمهٔ اریب با نوارِ مقایسه", "تصویرِ دوتکه: «قبل» (کم‌رنگ و تیره) و «بعد» (پرنور و رنگی) با خطِ جداکنندهٔ اریب، دستگیرهٔ مقایسه و یک عنوانِ کوتاه؛ برای تغییر و نتیجه.",
             split_ba, "vivid", "lalezar", "youtube", "recommended", [("title", "عنوان"), ("subtitle", "زیرعنوان"), ("label_a", "برچسبِ «بعد»"), ("label_b", "برچسبِ «قبل»")],
             ["youtube", "ig_square", "ig_portrait", "story", "pinterest", "aparat", "telegram"], True, ["عکسِ «بعد» را در سوژهٔ اول و «قبل» را در سوژهٔ دوم بگذارید؛ اگر فقط یکی دارید، نسخهٔ قبل خودکار کم‌رنگ می‌شود."]),
    StyleDef("number_list", "عدد / لیست", "عددِ غولیِ برجسته + عنوان", "تامنیلِ «۷ روش برای…»: یک عددِ خیلی بزرگ با حاشیه و برجستگی، عنوانِ کوتاه زیرش و سوژه‌ای کوچک‌تر؛ وعدهٔ یک فهرستِ مشخص.",
             number_list, "vivid", "lalezar", "youtube", "optional", [("number", "عدد"), ("title", "عنوان"), ("subtitle", "زیرعنوان"), ("kicker", "برچسبِ بالا")],
             ["youtube", "ig_portrait", "ig_square", "pinterest", "story", "aparat", "telegram"], tips=["عدد را فقط وقتی بنویسید که واقعاً همان‌قدر مورد در محتوا هست."]),
    StyleDef("question_hook", "سؤال / کنجکاوی", "علامتِ سؤالِ بزرگ + عنوانِ پرسشی", "قلابِ کنجکاوی: علامتِ «؟»ی بزرگ پشتِ سوژه، پرتوِ نورِ نقطه‌ای و عنوانی به شکلِ سؤال یا نیمه‌رازِ باز؛ بیننده برای دانستنِ جواب کلیک می‌کند.",
             question_hook, "dark", "lalezar", "youtube", "optional", [("kicker", "برچسبِ بالا"), ("title", "عنوان (سؤال)"), ("subtitle", "زیرعنوان")],
             ["youtube", "aparat", "telegram", "ig_square", "story", "ig_portrait"]),
    StyleDef("minimal_luxury", "مینیمالِ لوکس", "تیره و آرام، قابِ باریک، فضای خالی", "حسِ برندِ لوکس: زمینهٔ تیره یا کرم، قابِ باریکِ طلایی، کالا با نورِ ملایم و عنوانی آرام و باوقار؛ کمتر، گران‌تر.",
             minimal_luxury, "luxury", "estedad", "product", "recommended", [("kicker", "برچسبِ بالا"), ("title", "عنوان"), ("subtitle", "زیرعنوان")],
             ["ig_portrait", "ig_square", "pinterest", "poster", "youtube", "story"], tips=["متنِ کم و کوتاه؛ اینجا فضای خالی بخشی از طراحی است."]),
    StyleDef("cinema_poster", "پوسترِ سینمایی", "رنگ‌بندیِ فیلم، عنوانِ بلوکی، سطرِ اعتبار", "پوسترِ فیلم: رنگ‌بندیِ فیروزه‌ای-نارنجی، سوژهٔ بزرگ با لبهٔ نور، عنوانِ درشت در سومِ پایین، جملهٔ بالای عنوان و بلوکِ ریزِ «اعتبار»ها؛ برای معرفیِ یک برنامه یا ایده با حالِ سینمایی.",
             cinema_poster, "cinema", "estedad", "poster", "recommended", [("tagline", "جملهٔ بالای عنوان"), ("title", "عنوان"), ("subtitle", "زیرعنوان"), ("credits", "بلوکِ اعتبار (با | جدا کنید)")],
             ["poster", "pinterest", "story", "ig_portrait", "youtube"], tips=["بلوکِ اعتبار را فقط با نام‌های واقعی پر کنید."]),
    StyleDef("pinterest_collage", "کلاژِ پینترستی", "کارت‌های عکس، چسب‌نوار، عنوانِ هایلایت", "زیبایی‌شناسیِ پینترستی: زمینهٔ کاغذیِ گرم، کارت‌های عکسِ سفیدحاشیه با چرخشِ جزئی، چسب‌نوار و عنوانی روی نوارِ هایلایت؛ حسِ «ایدهٔ قابلِ ذخیره».",
             pinterest_collage, "light", "estedad", "pinterest", "optional", [("kicker", "برچسبِ بالا"), ("title", "عنوان"), ("subtitle", "زیرعنوان"), ("badge", "نشان")],
             ["pinterest", "ig_portrait", "story", "ig_square", "poster"], tips=["۲ تا ۴ عکس را به‌عنوانِ سوژه/عکس‌های دیگر بدهید؛ جای خالی را کارتِ رنگی پر می‌کند."]),
    StyleDef("product_hero", "قهرمانِ محصول", "کالا روی نورِ مرکزی با بازتاب", "محصولِ بزرگ و تمیز روی نورِ مرکزی با حلقهٔ نور، بازتابِ کف و سایه، عنوان و دکمهٔ دعوت به اقدام و نشانِ قیمت/تخفیف.",
             product_hero, "dark", "estedad", "product", "recommended", [("kicker", "برچسبِ بالا"), ("title", "عنوان"), ("subtitle", "زیرعنوان"), ("cta", "دکمهٔ دعوت"), ("badge", "نشان (قیمت/تخفیف)")],
             ["ig_portrait", "ig_square", "pinterest", "story", "youtube", "telegram"], tips=["عکسِ کالا با پس‌زمینهٔ بریده بهترین نتیجه را می‌دهد (دکمهٔ «حذفِ پس‌زمینه»)."]),
    StyleDef("sticker_outline", "استیکرِ حاشیه‌دار", "حاشیهٔ سفیدِ ضخیم، رنگ‌های شاد", "حالِ استیکر: زمینهٔ شادِ راه‌راه با کنفتی، سوژه با حاشیهٔ سفیدِ ضخیم و عنوانی با دو لبه (سفید و مشکی) و کمی کج.",
             sticker_outline, "warm", "lalezar", "social", "optional", [("kicker", "برچسبِ بالا"), ("title", "عنوان"), ("subtitle", "زیرعنوان"), ("badge", "نشان")],
             ["ig_square", "ig_portrait", "story", "youtube", "telegram", "pinterest"]),
    StyleDef("neon", "نئون", "تیره با درخششِ رنگی و شبکهٔ کف", "حالِ شبانه و فناوری: زمینهٔ تیره، شبکهٔ پرسپکتیوِ کف، نورِ نئونیِ دورِ سوژه و عنوانِ درخشان؛ برای بازی، فناوری، ورزش و رویدادِ شبانه.",
             neon, "neon", "lalezar", "social", "optional", [("kicker", "برچسبِ بالا"), ("title", "عنوان"), ("subtitle", "زیرعنوان")],
             ["youtube", "aparat", "telegram", "ig_square", "story", "ig_portrait", "pinterest"]),
    StyleDef("news_bold", "تیترِ خبری", "نوارِ اریبِ تیره با تیترِ درشت", "تیترِ خبری و فوری: عکس در پس‌زمینه، نوارِ اریبِ تیره با لبهٔ قرمز، تیترِ سفیدِ درشت با کلمهٔ زرد و برچسبِ «ویژه».",
             news_bold, "dark", "estedad", "youtube", "optional", [("kicker", "برچسب (پیش‌فرض: ویژه)"), ("title", "تیتر"), ("subtitle", "زیرتیتر")],
             ["youtube", "aparat", "telegram", "ig_portrait", "ig_square", "story"]),
    StyleDef("versus", "رویارویی (مقایسه)", "دو سوژه رو در رو با «VS»", "مقایسهٔ دو چیز: دو سوژه رو‌به‌روی هم روی دو رنگِ متضاد با «VS» در مرکز، عنوان بالا و نامِ هر طرف زیرش.",
             versus, "vivid", "lalezar", "youtube", "recommended", [("title", "عنوان"), ("subtitle", "زیرعنوان"), ("label_a", "نامِ سوژهٔ اول"), ("label_b", "نامِ سوژهٔ دوم")],
             ["youtube", "aparat", "telegram", "ig_square", "story"], True),
    StyleDef("magazine_cover", "جلدِ مجله", "سرلوحهٔ بزرگ، سوژه روی آن، تیترهای کاور", "جلدِ مجله: نامِ بزرگ (سرلوحه) در بالا که سرِ سوژه کمی روی آن می‌نشیند، یک تیترِ اصلی با نوارِ رنگی و یک تیترِ دوم در پایین (یا ستونِ کناری)؛ برای معرفیِ یک ویژه‌نامه، گزارش یا مصاحبه.",
             magazine_cover, "light", "lalezar", "social", "recommended", [("kicker", "سطرِ بالای سرلوحه"), ("title", "سرلوحه (نامِ بزرگ)"), ("subtitle", "تیترِ اصلیِ کاور"), ("tagline", "تیترِ دوم"), ("badge", "نشان")],
             ["ig_portrait", "pinterest", "poster", "story", "ig_square", "youtube", "telegram"], tips=["سرلوحه کوتاه باشد (۱ تا ۳ کلمه)؛ سوژهٔ بریده با ناحیهٔ بالای خالی بهترین نتیجه را می‌دهد."]),
    StyleDef("retro_poster", "پوسترِ قدیمی (رترو)", "کاغذِ کرم، خورشیدِ پرتوی، نوارِ عنوان", "پوسترِ چاپیِ قدیمی: کاغذِ کرم با دانه، خورشیدِ پرتوی و حلقه‌های هم‌مرکز پشتِ سوژه، نوارِ عنوانِ لبه‌بریده و قابِ دوخطی؛ حسِ نوستالژی و دست‌ساز.",
             retro_poster, "warm", "lalezar", "poster", "optional", [("kicker", "برچسبِ بالا"), ("title", "عنوان"), ("subtitle", "زیرعنوان"), ("tagline", "جملهٔ ریز"), ("badge", "نشان")],
             ["poster", "pinterest", "ig_portrait", "story", "ig_square", "youtube"], tips=["عنوان کوتاه؛ رنگ‌ها را ۳ تا نگه دارید تا حسِ چاپِ قدیمی بماند."]),
    StyleDef("quote_card", "کارتِ نقل‌قول", "علامتِ نقل‌قول، متنِ وسط‌چین، نامِ گوینده", "کارتِ جمله: علامتِ نقل‌قولِ بزرگ، متنِ وسط‌چین با یک کلمهٔ رنگی، خطِ جداکننده و نامِ گوینده؛ عکسِ گوینده (اختیاری) در دایره. برای جمله‌های الهام‌بخش و نکته‌های کوتاه.",
             quote_card, "dark", "estedad", "social", "optional", [("kicker", "برچسبِ بالا"), ("title", "متنِ نقل‌قول"), ("subtitle", "گوینده / منبع")],
             ["ig_square", "ig_portrait", "story", "pinterest", "youtube", "telegram", "poster"], tips=["نقل‌قول را فقط وقتی بنویسید که واقعاً از همان گوینده است؛ جملهٔ ساختگی به نامِ آدم‌ها نگذارید."]),
)}

STYLE_ORDER = list(STYLES)
