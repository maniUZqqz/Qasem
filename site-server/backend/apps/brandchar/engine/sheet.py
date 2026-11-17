"""برگهٔ مدلِ شخصیتِ برند (PNG و PDF): هویت، نمای اصلی و آینه‌ای، کلیدِ رنگ، ۸ حالتِ چهره، ۸ ژست، سبک‌ها و (اگر هست) لحنِ گفتار.

همین برگه را مالک یک بار تأیید می‌کند و مرجعِ هر تصویرِ بعدی است (کارکنان، طراح‌ها و مدل‌های تصویرساز). متنِ فارسی با موتورِ تایپوگرافیِ تامنیل‌ساز کشیده می‌شود.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from apps.mascot.engine import compose, poses, text
from apps.mascot.engine import spec as MS

from . import doc as D
from . import render as R

W, H = 2000, 1500
PAPER = (244, 241, 234, 255)
INK = (31, 36, 48, 255)


def _fa(v) -> str:
    return str(v).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _rgb(hx: str) -> tuple[int, int, int]:
    h = hx.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _cell(doc: dict, size: tuple[int, int], *, pose: str = "stand", expression: str = "neutral", flip: bool = False, zoom_head: bool = False,
          logo: Image.Image | None = None, prop: str | None = "none", style: str | None = None) -> Image.Image:
    w, h = size
    d = dict(doc, style=style) if style else doc
    lg = R.logo_for(d, logo)
    if zoom_head:
        # سر را درشت می‌کنیم: مقیاس طوری که سر ≈ ۶۲٪ِ عرضِ سلول شود و مرکزِ سر وسطِ سلول بیفتد
        if d["style"] in R.VECTOR_STYLES:
            from . import figure as F

            fit = F.STYLE[d["style"]].fit
            hx, hy, hr = F.build(d, "stand", expression, with_layers=False).head
            px = (w * 0.62) / (2 * hr * fit)
            yy = (h * 0.5 + (F.GROUND - hy) * px * fit) / h
        else:
            px = (w * 0.62) / 156
            yy = (h * 0.46 + (862 - 224) * px) / h
        a = R.actor(d, pose="stand", expression=expression, flip=flip, prop="none", x=0.5, shadow=False, height=900 * px / h, y=yy)
    else:
        a = R.actor(d, pose=pose, expression=expression, flip=flip, prop=prop, x=0.5, y=0.96, height=0.9, shadow=False)
    from apps.mascot.engine import stage

    return stage.render_actor(a, w, h, logo=lg, shadow=False).layer


def model_sheet(doc: dict, *, title: str = "", store_name: str = "", version: int | None = None, logo: Image.Image | None = None, persona: dict | None = None,
                brand: list[str] | None = None) -> Image.Image:
    d = D.normalize(doc)
    sheet = Image.new("RGBA", (W, H), PAPER)
    dr = ImageDraw.Draw(sheet)
    dr.rectangle([0, 0, W, 110], fill=INK)
    name = title or d["name"] or "؟"
    text.draw_text(sheet, name, (W - 60, 22), 58, fill="#ffffff", anchor="ra", max_w=900)
    text.draw_text(sheet, "برگهٔ مدلِ شخصیتِ برند" + (f" · نسخهٔ {_fa(version)}" if version else ""), (60, 38), 36, fill="#c8cedc", anchor="la", max_w=800)
    if store_name:
        text.draw_text(sheet, store_name, (W // 2, 36), 36, fill="#c8cedc", anchor="ma", max_w=500)

    def label(x, y, txt, px=30, anchor="ma", fill="#3c404c", weight=800):
        text.draw_text(sheet, txt, (x, y), px, fill=fill, anchor=anchor, max_w=700, weight=weight)

    for i, flip in enumerate((False, True)):
        x = 60 + i * 410
        dr.rectangle([x, 150, x + 380, 710], fill=(255, 255, 255, 255))
        sheet.alpha_composite(_cell(d, (380, 560), flip=flip, pose="stand", logo=logo), (x, 150))
    label(250, 722, "نمای اصلی")
    label(660, 722, "نمای آینه‌ای")
    kx = 900
    label(kx + 520, 150, "کلیدِ رنگ", 36)
    pal: list[dict] = []
    for c in D.palette(d):
        for q in pal:
            if q["hex"] == c["hex"]:
                q["roles"].append(c["role"])
                break
        else:
            pal.append({**c, "roles": [c["role"]]})
    role_fa = {"skin": "پوست", "top": "لباس", "top2": "رنگِ دوم", "bottom": "شلوار", "shoes": "کفش", "hair": "مو", "hat": "کلاه", "neck": "گردن‌آویز", "extra": "وسیلهٔ اضافه",
               "outline": "خط دور", "limbs": "دست و پا", "head": "سر"}
    for i, c in enumerate(pal[:12]):
        col, row = i % 2, i // 2
        x0, y0 = kx + col * 520, 210 + row * 100
        dr.rounded_rectangle([x0, y0, x0 + 82, y0 + 82], radius=16, fill=_rgb(c["hex"]) + (255,), outline=INK, width=4)
        label(x0 + 100, y0 + 4, c["hex"].upper(), 30, "la", "#1f2430")
        label(x0 + 100, y0 + 42, f"{' / '.join(role_fa.get(r, MS.fa_word(r)) for r in c['roles'])} · {MS.fa_word(c['name'])}", 26, "la", "#5a5e6a", 600)
    ny = 210 + ((min(len(pal), 12) + 1) // 2) * 100 + 14
    label(kx + 520, ny, "هویت", 32)
    lines = [f"سبکِ کشیدن: {D.STYLE_LABELS_FA[d['style']]}", f"بدن: {D.CHOICE_LABELS_FA['body'][d['body']]} · لباس: {D.CHOICE_LABELS_FA['outfit'][d['outfit']]}",
             f"مو: {D.CHOICE_LABELS_FA['hair'][d['hair']]} · کلاه: {D.CHOICE_LABELS_FA['hat'][d['hat']]}"]
    if persona:
        from apps.brandchar import persona as P

        a = P.ARCHETYPES.get(persona.get("archetype") or "")
        if a:
            lines.append(f"کهن‌الگو: {a['fa']}")
        if persona.get("catchphrases"):
            lines.append("شعار: " + persona["catchphrases"][0])
    for j, ln in enumerate(lines[:5]):
        label(kx, ny + 46 + j * 40, ln, 28, "la", "#3c404c", 600)
    label(W // 2, 780, "حالت‌های چهره", 34)
    ew = (W - 120) // 8
    for i, ex in enumerate(D.EXPRESSIONS):
        x = 60 + i * ew
        dr.rectangle([x, 826, x + ew - 10, 1046], fill=(255, 255, 255, 255))
        sheet.alpha_composite(_cell(d, (ew - 10, 220), expression=ex, zoom_head=True, logo=logo), (x, 826))
        label(x + (ew - 10) // 2, 1054, MS.fa_word(ex), 26)
    label(W // 2, 1100, "ژست‌ها", 34)
    pw = (W - 120) // len(poses.SHEET_POSES)
    for i, pz in enumerate(poses.SHEET_POSES):
        x = 60 + i * pw
        dr.rectangle([x, 1146, x + pw - 10, 1402], fill=(255, 255, 255, 255))
        sheet.alpha_composite(_cell(d, (pw - 10, 256), pose=pz, logo=logo, expression="happy"), (x, 1146))
        label(x + (pw - 10) // 2, 1408, poses.label_fa(pz), 24)
    # خطِ پایانی کاملاً داخلِ بوم (قبلاً از لبهٔ پایین بریده می‌شد): بالای آن ≥ ۴۰ پیکسل تا لبه می‌ماند
    text.draw_text(sheet, "شخصیتِ کارتونیِ کشیده‌شده با کد؛ نه آدمِ واقعی. این برگه مرجعِ همهٔ تصویرهاست.", (W - 60, 1448), 22, fill="#7a7e8a", anchor="ra", max_w=1500, weight=500)
    return sheet.convert("RGB")


def styles_page(doc: dict, *, logo: Image.Image | None = None) -> Image.Image:
    """صفحهٔ دوم: همین شخصیت در هر چهار سبکِ کشیدن (برای انتخابِ سبک)."""
    d = D.normalize(doc)
    pg = Image.new("RGBA", (W, H), PAPER)
    dr = ImageDraw.Draw(pg)
    dr.rectangle([0, 0, W, 110], fill=INK)
    text.draw_text(pg, "سبک‌های کشیدن", (W - 60, 22), 58, fill="#ffffff", anchor="ra", max_w=900)
    cw = (W - 100) // 4
    for i, st in enumerate(D.STYLES):
        x = 50 + i * cw
        dr.rectangle([x, 150, x + cw - 20, 1050], fill=(255, 255, 255, 255))
        pg.alpha_composite(_cell(d, (cw - 20, 900), pose="wave", expression="happy", logo=logo, style=st), (x, 150))
        text.draw_text(pg, D.STYLE_LABELS_FA[st], (x + (cw - 20) // 2, 1070), 34, fill="#1f2430", anchor="ma", max_w=cw - 30)
        text.draw_text(pg, D.STYLE_HINTS_FA[st], (x + (cw - 20) // 2, 1122), 22, fill="#5a5e6a", anchor="ma", max_w=cw - 40, weight=500, max_lines=3)
    return pg.convert("RGB")


def poses_page(doc: dict, *, logo: Image.Image | None = None, cols: int = 6) -> Image.Image:
    """همهٔ ۲۹ ژست روی یک صفحه."""
    d = D.normalize(doc)
    names = poses.names()
    rows = (len(names) + cols - 1) // cols
    cw, ch = (W - 100) // cols, 250
    pg = Image.new("RGBA", (W, 160 + rows * (ch + 50) + 30), PAPER)
    dr = ImageDraw.Draw(pg)
    dr.rectangle([0, 0, W, 110], fill=INK)
    text.draw_text(pg, f"همهٔ ژست‌ها ({_fa(len(names))})", (W - 60, 22), 58, fill="#ffffff", anchor="ra", max_w=900)
    for i, pz in enumerate(names):
        c, r = i % cols, i // cols
        x, y = 50 + c * cw, 140 + r * (ch + 50)
        dr.rectangle([x, y, x + cw - 14, y + ch], fill=(255, 255, 255, 255))
        pg.alpha_composite(_cell(d, (cw - 14, ch), pose=pz, expression="happy", logo=logo, prop="auto" if pz in poses.PROP_FOR_POSE else "none"), (x, y))
        text.draw_text(pg, poses.label_fa(pz), (x + (cw - 14) // 2, y + ch + 8), 24, fill="#3c404c", anchor="ma", max_w=cw - 20, weight=600)
    return pg.convert("RGB")


def pdf_bytes(doc: dict, *, title: str = "", store_name: str = "", version: int | None = None, logo: Image.Image | None = None, persona: dict | None = None) -> bytes:
    """PDF چندصفحه‌ای: برگهٔ مدل، سبک‌ها، همهٔ ژست‌ها."""
    pages = [model_sheet(doc, title=title, store_name=store_name, version=version, logo=logo, persona=persona), styles_page(doc, logo=logo), poses_page(doc, logo=logo)]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    return buf.getvalue()
