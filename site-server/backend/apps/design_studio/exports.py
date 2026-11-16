"""خروجی‌ها و «کدام فایل را به چه کسی بده»: PDF چاپی، PDF نمایشی، PNG/JPG هر صفحه، PPTX/PPSX، SVG، توکن‌ها و بسته‌های تحویل (چاپخانه، شبکه‌های اجتماعی، طراحِ بعدی، مشتری، جلسه، نمایشگاه، برنامه‌نویس).

هر بسته یک ZIP (مطمئن‌ترین انتخاب طبقِ راهنما) با «README-fa.txt» است که می‌گوید چه فایلی برای چیست. فایلِ بازِ InDesign/Illustrator/CorelDRAW از این‌جا ساخته نمی‌شود؛
برای «طراحِ بعدی» سورسِ کامل (JSON + PPTX + عکس‌ها + فونت‌ها و مجوزشان) داده می‌شود.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from PIL import Image

from . import catalog_doc, deck_doc, fonts, images, pdf, pptx, render_png, render_svg, scene, typeset, ui_doc, ui_frames

KINDS = {
    "print_pdf": ("PDF چاپی (بلید ۳ میلی‌متر، علامت برش)", "pdf", "application/pdf", ("catalog",)),
    "screen_pdf": ("PDF نمایشی (کم‌حجم، با پیوند)", "pdf", "application/pdf", ("catalog", "deck", "ui")),
    "png_zip": ("PNG هر صفحه (ZIP)", "zip", "application/zip", ("catalog", "deck", "ui")),
    "jpg_zip": ("JPG هر صفحه (ZIP)", "zip", "application/zip", ("catalog", "deck", "ui")),
    "pptx": ("PPTX قابل‌ویرایش", "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", ("catalog", "deck")),
    "ppsx": ("PPSX (مستقیم نمایش می‌دهد)", "ppsx", "application/vnd.openxmlformats-officedocument.presentationml.slideshow", ("deck",)),
    "svg_zip": ("SVG هر فریم (ZIP)", "zip", "application/zip", ("ui", "deck")),
    "tokens": ("توکن‌های طراحی (CSS + JSON)", "zip", "application/zip", ("ui",)),
    "pack_printer": ("بستهٔ چاپخانه", "zip", "application/zip", ("catalog",)),
    "pack_social": ("بستهٔ شبکه‌های اجتماعی", "zip", "application/zip", ("catalog", "deck", "ui")),
    "pack_source": ("بستهٔ سورس برای طراحِ بعدی", "zip", "application/zip", ("catalog", "deck", "ui")),
    "pack_customer": ("بستهٔ مشتری (دیدن و تأیید)", "zip", "application/zip", ("catalog", "deck", "ui")),
    "pack_meeting": ("بستهٔ جلسه و ارائهٔ حضوری", "zip", "application/zip", ("deck",)),
    "pack_kiosk": ("بستهٔ نمایشگاه و کیوسک", "zip", "application/zip", ("deck",)),
    "pack_dev": ("بستهٔ برنامه‌نویس (سایت)", "zip", "application/zip", ("ui",)),
}

#: «کدام فایل را به چه کسی بده» — جدولِ بخشِ ۹ راهنما، با کلیدِ بسته
RECIPIENTS = [
    {"key": "printer", "title": "چاپخانه", "doc_kinds": ["catalog"], "pack": "pack_printer", "what": "PDF با بلید ۳ میلی‌متر و علامت برش + برگهٔ مشخصات و چک‌لیست",
     "note": "رنگ‌ها RGB است؛ تبدیل به CMYK و PDF/X را چاپخانه انجام می‌دهد (از او بپرسید کدام نسخه را می‌خواهد)."},
    {"key": "social", "title": "اینستاگرام و شبکه‌های اجتماعی", "doc_kinds": ["catalog", "deck", "ui"], "pack": "pack_social",
     "what": "JPG رنگ RGB: مربع ۱۰۸۰×۱۰۸۰، عمودی ۱۰۸۰×۱۳۵۰، استوری ۱۰۸۰×۱۹۲۰", "note": ""},
    {"key": "designer", "title": "طراحِ بعدی (برای ویرایش)", "doc_kinds": ["catalog", "deck", "ui"], "pack": "pack_source",
     "what": "سورس کامل: سند (JSON)، PPTX قابل‌ویرایش، عکس‌ها، فونت‌ها و مجوزشان", "note": "فایلِ باز InDesign/Illustrator/CorelDRAW ساخته نمی‌شود."},
    {"key": "customer", "title": "مشتری (دیدن و تأیید)", "doc_kinds": ["catalog", "deck", "ui"], "pack": "pack_customer", "what": "PDF کم‌حجم + پیش‌نمایش JPG برای فرستادن در پیام‌رسان", "note": ""},
    {"key": "meeting", "title": "جلسه و ارائهٔ حضوری", "doc_kinds": ["deck"], "pack": "pack_meeting", "what": "PPTX قابل‌ویرایش + PDF پشتیبان + فونت‌ها", "note": "فونت‌ها را روی رایانهٔ ارائه نصب کنید."},
    {"key": "kiosk", "title": "نمایشگاه یا کیوسک", "doc_kinds": ["deck"], "pack": "pack_kiosk", "what": "PPSX که خودش مستقیم نمایش می‌دهد (و ویدیوی MP4 از «ساختِ ویدیو»)", "note": ""},
    {"key": "dev", "title": "برنامه‌نویس (ساختِ سایت)", "doc_kinds": ["ui"], "pack": "pack_dev", "what": "توکن‌ها (CSS/JSON)، SVG و PNG هر فریم، بلوک‌های سایت", "note": ""},
]

SOCIAL_SIZES = [("square-1080x1080", 1080, 1080), ("portrait-1080x1350", 1080, 1350), ("story-1080x1920", 1080, 1920)]


class ExportError(ValueError):
    pass


class Bundle:
    def __init__(self, kind: str, data: dict, sc: dict, info, src: images.ImageSource, title: str = "", doc_id: int = 0, checks: list | None = None):
        self.kind, self.data, self.sc, self.info, self.src = kind, data, sc, info, src
        self.title, self.doc_id, self.checks = title or "design", doc_id, checks or []

    @property
    def pages(self) -> list[dict]:
        return self.sc["pages"]

    @property
    def unit(self) -> str:
        return self.sc["unit"]

    @property
    def base(self) -> str:
        return f"{self.kind}-{self.doc_id}" if self.doc_id else self.kind


def make_bundle(kind: str, data: dict, info, src: images.ImageSource, title: str = "", doc_id: int = 0, with_checks: bool = True) -> Bundle:
    if kind == "catalog":
        sc = catalog_doc.build_scene(data, info, src)
        checks = catalog_doc.preflight(data, sc, src) if with_checks else []
    elif kind == "deck":
        sc = deck_doc.build_scene(data, info, src)
        checks = deck_doc.review(data, sc) if with_checks else []
    elif kind == "ui":
        sc = ui_frames.build_scene(data, info, with_styleguide=True)
        checks = ui_doc.review(data, sc) if with_checks else []
    else:
        raise ExportError("نوعِ سند نامعتبر است.")
    return Bundle(kind, data, sc, info, src, title, doc_id, checks)


# ───────────────────────────── رندرها

def page_label(i: int, page: dict) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", str(page.get("type") or page.get("section") or "page").lower()).strip("-") or "page"
    return f"page-{i + 1:02d}-{t}"


def _bg_color(page: dict) -> tuple:
    bg = page.get("bg")
    if isinstance(bg, dict):
        bg = bg["stops"][0][1]
    from . import colors

    r, g, b = colors.rgb(bg or "#ffffff")
    return r, g, b


def to_bytes(im: Image.Image, fmt: str = "PNG", quality: int = 92, dpi: int | None = None) -> bytes:
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, **({"dpi": (dpi, dpi)} if dpi else {}))
    else:
        im.save(buf, "PNG", optimize=True, **({"dpi": (dpi, dpi)} if dpi else {}))
    return buf.getvalue()


def page_scale(b: Bundle, page: dict, params: dict) -> float:
    if b.unit == "mm":
        return render_png.px_per_mm(float(params.get("dpi") or 150))
    return float(params.get("scale") or 1.0)


def pages_zip(b: Bundle, fmt: str, params: dict, progress=None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for i, p in enumerate(b.pages):
            im = render_png.render_page(p, b.src, scale=page_scale(b, p, params), with_bleed=bool(params.get("bleed")) and b.unit == "mm")
            z.writestr(f"{page_label(i, p)}.{'jpg' if fmt == 'JPEG' else 'png'}", to_bytes(im, fmt, int(params.get("quality") or 92), int(params.get("dpi") or 0) or None))
            if progress:
                progress((i + 1) / len(b.pages), f"صفحهٔ {typeset.digits(str(i + 1), 'fa')} از {typeset.digits(str(len(b.pages)), 'fa')}")
        if b.kind == "ui":
            sg = b.sc.get("styleguide")
            if sg:
                z.writestr("styleguide.png" if fmt == "PNG" else "styleguide.jpg", to_bytes(render_png.render_page(sg, b.src, scale=page_scale(b, sg, params)), fmt, 92))
    return out.getvalue()


def fit_canvas(im: Image.Image, w: int, h: int, bg: tuple) -> Image.Image:
    """تصویر را بدونِ بریدن در بومِ w×h می‌گذارد (وسط، با رنگِ زمینهٔ صفحه)."""
    k = min(w / im.width, h / im.height)
    r = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), bg)
    canvas.paste(r, ((w - r.width) // 2, (h - r.height) // 2))
    return canvas


def social_files(b: Bundle) -> dict[str, bytes]:
    files = {}
    for i, p in enumerate(b.pages):
        base_px = 1620 if p["w"] <= p["h"] else 1920
        scale = base_px / p["w"]
        im = render_png.render_page(p, b.src, scale=scale)
        bg = _bg_color(p)
        for name, w, h in SOCIAL_SIZES:
            files[f"social/{name}/{page_label(i, p)}.jpg"] = to_bytes(fit_canvas(im, w, h, bg), "JPEG", 92)
        if b.kind == "deck":
            files[f"social/landscape-1920x1080/{page_label(i, p)}.jpg"] = to_bytes(fit_canvas(im, 1920, 1080, bg), "JPEG", 92)
    return files


def print_pdf(b: Bundle, params: dict | None = None, marks: bool = True) -> tuple[bytes, dict]:
    p = params or {}
    opts = dict(pdf.PRINT)
    opts.update(marks=bool(p.get("marks", marks)), bleed=bool(p.get("bleed", True)), dpi=int(p.get("dpi") or 300))
    return pdf.build_pdf(b.pages, b.src, unit="mm", options=opts, title=b.title, author=getattr(b.info, "name", "") or "NMarketing",
                         subject="کاتالوگ — نسخهٔ چاپی", rtl=True, bookmarks=catalog_doc.bookmarks(b.sc))


def screen_pdf(b: Bundle) -> tuple[bytes, dict]:
    pages = list(b.pages)
    if b.kind == "ui":
        sg = b.sc.get("styleguide")
        if sg:
            pages.append(sg)
    bm = catalog_doc.bookmarks(b.sc) if b.kind == "catalog" else [(p["name"], i, 0) for i, p in enumerate(pages)]
    data, rep = pdf.build_pdf(pages, b.src, unit=b.unit, options=pdf.SCREEN, title=b.title, author=getattr(b.info, "name", "") or "NMarketing", subject=f"{b.kind}", rtl=True, bookmarks=bm)
    return data, rep


def pptx_bytes(b: Bundle, slideshow: bool = False) -> bytes:
    fam = b.sc.get("fonts") or {}
    pal = b.sc.get("palette") or {}
    data = pptx.build_pptx(b.pages, b.src, unit=b.unit, title=b.title, author=getattr(b.info, "name", "") or "NMarketing", accent=pal.get("primary", "#126f85"),
                           body_font=fam.get("body", "vazirmatn"), head_font=fam.get("heading", "vazirmatn"))
    if slideshow:
        zin = zipfile.ZipFile(io.BytesIO(data))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for item in zin.infolist():
                raw = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    raw = raw.replace(b"presentationml.presentation.main+xml", b"presentationml.slideshow.main+xml")
                z.writestr(item, raw)
        return out.getvalue()
    return data


def svg_files(b: Bundle, text_mode: str = "outline") -> dict[str, bytes]:
    files = {}
    pages = list(b.pages)
    for i, p in enumerate(pages):
        files[f"svg/{page_label(i, p)}.svg"] = render_svg.page_svg(p, b.src, text_mode=text_mode, title=p.get("name", "")).encode("utf-8")
    sg = b.sc.get("styleguide")
    if sg:
        files["svg/styleguide.svg"] = render_svg.page_svg(sg, b.src, text_mode=text_mode, title="راهنمای سبک").encode("utf-8")
    return files


def source_files(b: Bundle) -> dict[str, bytes]:
    files: dict[str, bytes] = {"source/document.json": json.dumps(b.data, ensure_ascii=False, indent=1).encode("utf-8")}
    refs = sorted({e.get("src") for p in b.pages for e in p["elements"] if e["type"] == "image" and e.get("src")})
    for ref in refs:
        path = b.src.path(ref)
        if path and path.is_file():
            files[f"images/{re.sub(r'[^A-Za-z0-9._-]+', '_', ref)}{path.suffix.lower() or '.jpg'}"] = path.read_bytes()
    used = set(f for p in b.pages for f in p.get("fonts", [])) or {"vazirmatn"}
    files.update(fonts.license_files(used))
    return files


# ───────────────────────────── README

def _checks_text(b: Bundle) -> str:
    if not b.checks:
        return ""
    mark = {"ok": "✓", "warn": "⚠", "info": "ℹ"}
    return "\n".join(f"{mark.get(c['level'], '-')} {c['title']}" + (f" — {c['detail']}" if c.get("detail") else "") for c in b.checks)


def readme(kind: str, b: Bundle, extra: dict | None = None) -> str:
    n = typeset.digits(str(len(b.pages)), "fa")
    head = f"{b.title}\n{'=' * max(8, len(b.title))}\n"
    if kind == "pack_printer":
        s = b.sc["settings"]
        return head + f"""بستهٔ چاپخانه — {n} صفحه، {s.get('page_size', 'A4')}

فایل‌ها
• print/…-print.pdf  : فایل اصلیِ چاپ؛ هر صفحه ۳ میلی‌متر بلید و علامت برش (Crop marks) دارد. عکس‌ها تا ۳۰۰ dpi در اندازهٔ چاپ؛ متن‌ها به منحنی تبدیل شده‌اند (فونت لازم نیست).
• print/…-print-bleed-only.pdf : همان با بلید ولی بدونِ علامت برش (اگر چاپخانه علامت نخواست).
• proof/…-screen.pdf : نسخهٔ کم‌حجم برای تأییدِ سریع.
• PREFLIGHT-fa.txt : چک‌لیستِ چاپخانه (نتیجهٔ بررسیِ همین فایل).

نکته‌های مهم (از راهنمای فایل‌ها)
• رنگ‌ها RGB است. تبدیلِ واقعی به CMYK و ساختِ PDF/X را چاپخانه از همین PDF انجام می‌دهد؛ از او بپرسید PDF/X-1a می‌خواهد یا PDF/X-4.
• متن‌ها و لوگوهای مهم دست‌کم ۵ میلی‌متر از لبهٔ برش فاصله دارند.
• صفحه‌ها تکی‌اند (نه دوتایی).
• اگر چاپخانه «فایلِ باز» خواست: «بستهٔ سورس» را بدهید (سند + PPTX + عکس‌ها + فونت‌ها).

بررسی
{_checks_text(b)}
"""
    if kind == "pack_social":
        return head + """بستهٔ شبکه‌های اجتماعی — JPG با رنگ RGB

پوشه‌ها: square-1080x1080 (پست مربع)، portrait-1080x1350 (پست عمودی)، story-1080x1920 (استوری)""" + (
            "، landscape-1920x1080 (افقی)" if b.kind == "deck" else "") + """.
هر صفحه بدونِ بریده شدن در بوم جا شده و رنگ زمینهٔ همان صفحه حاشیه را پر کرده است.
این فایل‌ها فقط پیش‌نویس‌اند؛ هیچ‌چیز خودکار منتشر نمی‌شود.
"""
    if kind == "pack_source":
        return head + """بستهٔ سورس برای طراحِ بعدی

• source/document.json : سندِ کامل (همهٔ صفحه‌ها، متن‌ها و تنظیمات) — با «استودیوی طراحی» دوباره باز می‌شود.
• editable/…pptx : نسخهٔ قابل‌ویرایش (متنِ زنده، راست‌به‌چپ؛ فونت‌ها را نصب کنید).
• images/ : عکس‌های اصلیِ به‌کاررفته.
• fonts/ و licenses/ : فونت‌ها و متنِ مجوزشان (همه SIL OFL 1.1؛ استفاده و جاسازی مجاز است، فروشِ جدایِ خودِ فونت مجاز نیست).
• preview/ : پیش‌نمایشِ هر صفحه.
• print/ : PDF چاپی (فقط برای کاتالوگ).

یادآوری: فایلِ سورس را همیشه نگه دارید؛ به دیگران «خروجی» بدهید.
"""
    if kind == "pack_customer":
        return head + f"""بستهٔ مشتری — {n} صفحه

• …-preview.pdf : PDF کم‌حجم برای دیدن و تأیید (فهرست و نشانک دارد).
• preview/ : JPG هر صفحه برای فرستادن سریع در پیام‌رسان.
"""
    if kind == "pack_meeting":
        return head + """بستهٔ جلسه و ارائهٔ حضوری

• …pptx : ارائهٔ قابل‌ویرایش با یادداشت گوینده.
• …-backup.pdf : PDF پشتیبان (اگر رایانهٔ جلسه فونت را نداشت).
• fonts/ و licenses/ : فونت‌ها را پیش از ارائه روی رایانهٔ جلسه نصب کنید (فایل‌ها را باز کنید ⇐ Install). در PPTX جاسازی نشده‌اند.
"""
    if kind == "pack_kiosk":
        return head + """بستهٔ نمایشگاه و کیوسک

• …ppsx : با دو بار کلیک مستقیم به‌صورت نمایش اجرا می‌شود.
• ویدیوی MP4 را از «ساختِ ویدیو» در صفحهٔ ارائه بگیرید (با موتور موشن؛ منتظرِ سرورِ پردازش می‌ماند).
• fonts/ : فونت‌ها را روی رایانهٔ کیوسک نصب کنید.
"""
    if kind == "pack_dev":
        return head + """بستهٔ برنامه‌نویس

• tokens/tokens.css : متغیرهای CSS (حالت روشن و تیره: <html data-theme="dark">).
• tokens/tokens.json : همان توکن‌ها.
• svg/ : هر فریم SVG (متن منحنی شده).  • png/ : هر فریم PNG.
• site/blocks.json : بلوک‌های سایت‌ساز هر فریم (همان چیزی که «ساختِ سایت از این طرح» می‌سازد).
"""
    return head


# ───────────────────────────── ساختن

def zip_of(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            z.writestr(name, files[name])
    return out.getvalue()


def build(kind: str, b: Bundle, params: dict | None = None, progress=None) -> tuple[bytes, str, dict]:
    """⇒ (بایت، نامِ فایل، اطلاعاتِ ساخت)."""
    params = params or {}
    if kind not in KINDS:
        raise ExportError("نوعِ خروجی ناشناخته است.")
    label, ext, mime, doc_kinds = KINDS[kind]
    if b.kind not in doc_kinds:
        raise ExportError(f"«{label}» برای این نوع سند نیست.")
    if not b.pages:
        raise ExportError("سند صفحه‌ای ندارد.")
    base = b.base
    info: dict = {"pages": len(b.pages), "label": label}

    def step(f, msg):
        if progress:
            progress(f, msg)

    if kind == "print_pdf":
        data, rep = print_pdf(b, params)
        info.update(rep)
        info["checks"] = b.checks
        return data, f"{base}-print.pdf", info
    if kind == "screen_pdf":
        data, rep = screen_pdf(b)
        info.update(rep)
        return data, f"{base}-screen.pdf", info
    if kind in ("png_zip", "jpg_zip"):
        data = pages_zip(b, "PNG" if kind == "png_zip" else "JPEG", params, progress)
        return data, f"{base}-{'png' if kind == 'png_zip' else 'jpg'}.zip", info
    if kind in ("pptx", "ppsx"):
        step(0.3, "ساختِ اسلایدها")
        return pptx_bytes(b, kind == "ppsx"), f"{base}.{kind}", info
    if kind == "svg_zip":
        return zip_of(svg_files(b, params.get("text_mode", "outline"))), f"{base}-svg.zip", info
    if kind == "tokens":
        t = b.sc["tokens"]
        return zip_of({"tokens/tokens.css": ui_doc.tokens_css(t, b.sc["settings"]).encode("utf-8"),
                       "tokens/tokens.json": json.dumps(ui_doc.tokens_json(t, b.sc["settings"]), ensure_ascii=False, indent=1).encode("utf-8")}), f"{base}-tokens.zip", info

    files: dict[str, bytes] = {"README-fa.txt": readme(kind, b).encode("utf-8")}
    if kind == "pack_printer":
        step(0.1, "ساختِ PDF چاپی")
        a, rep = print_pdf(b, params, marks=True)
        files[f"print/{base}-print.pdf"] = a
        step(0.5, "ساختِ نسخهٔ بدونِ علامت")
        files[f"print/{base}-print-bleed-only.pdf"] = print_pdf(b, params, marks=False)[0]
        step(0.8, "ساختِ نسخهٔ نمایشی")
        files[f"proof/{base}-screen.pdf"] = screen_pdf(b)[0]
        files["PREFLIGHT-fa.txt"] = (b.title + "\n\n" + _checks_text(b)).encode("utf-8")
        info.update(rep)
        info["checks"] = b.checks
    elif kind == "pack_social":
        step(0.2, "ساختِ تصویرها")
        files.update(social_files(b))
    elif kind == "pack_source":
        step(0.1, "گردآوریِ سند و عکس‌ها")
        files.update(source_files(b))
        if b.kind in ("catalog", "deck"):
            step(0.4, "ساختِ PPTX")
            files[f"editable/{base}.pptx"] = pptx_bytes(b)
        if b.kind == "catalog":
            step(0.6, "ساختِ PDF چاپی")
            files[f"print/{base}-print.pdf"] = print_pdf(b, params)[0]
        if b.kind == "ui":
            files.update(svg_files(b))
            files["source/tokens.css"] = ui_doc.tokens_css(b.sc["tokens"], b.sc["settings"]).encode("utf-8")
        step(0.8, "پیش‌نمایش‌ها")
        for i, p in enumerate(b.pages):
            files[f"preview/{page_label(i, p)}.jpg"] = to_bytes(render_png.render_page(p, b.src, scale=min(1.0, 1200 / p["w"]) if b.unit == "px" else render_png.px_per_mm(60)), "JPEG", 85)
    elif kind == "pack_customer":
        step(0.2, "ساختِ PDF")
        files[f"{base}-preview.pdf"] = screen_pdf(b)[0]
        for i, p in enumerate(b.pages):
            files[f"preview/{page_label(i, p)}.jpg"] = to_bytes(render_png.render_page(p, b.src, scale=min(1.0, 1200 / p["w"]) if b.unit == "px" else render_png.px_per_mm(100)), "JPEG", 88)
    elif kind in ("pack_meeting", "pack_kiosk"):
        step(0.2, "ساختِ ارائه")
        if kind == "pack_meeting":
            files[f"{base}.pptx"] = pptx_bytes(b)
            files[f"{base}-backup.pdf"] = screen_pdf(b)[0]
        else:
            files[f"{base}.ppsx"] = pptx_bytes(b, slideshow=True)
        used = set(f for p in b.pages for f in p.get("fonts", [])) or {"vazirmatn"}
        files.update(fonts.license_files(used))
    elif kind == "pack_dev":
        t = b.sc["tokens"]
        files["tokens/tokens.css"] = ui_doc.tokens_css(t, b.sc["settings"]).encode("utf-8")
        files["tokens/tokens.json"] = json.dumps(ui_doc.tokens_json(t, b.sc["settings"]), ensure_ascii=False, indent=1).encode("utf-8")
        files.update(svg_files(b))
        for i, p in enumerate(b.pages):
            files[f"png/{page_label(i, p)}.png"] = to_bytes(render_png.render_page(p, b.src, scale=1.0), "PNG")
        sg = b.sc.get("styleguide")
        if sg:
            files["png/styleguide.png"] = to_bytes(render_png.render_page(sg, b.src, scale=1.0), "PNG")
        files["site/blocks.json"] = json.dumps({f["id"]: [dict((k, v) for k, v in n.items() if k != "t") for n in f.get("children", []) if n.get("t") == "block"] for f in b.data["frames"]},
                                               ensure_ascii=False, indent=1).encode("utf-8")
    info["files"] = len(files)
    return zip_of(files), f"{base}-{kind.replace('pack_', 'pack-')}.zip", info


# ───────────────────────────── پیش‌نمایش

def preview_png(b: Bundle, index: int, width: int = 900, *, styleguide: bool = False) -> bytes:
    page = b.sc["styleguide"] if styleguide else b.pages[index]
    scale = max(0.05, float(width) / page["w"])
    return to_bytes(render_png.render_page(page, b.src, scale=scale, max_image_px=int(width * 1.6) + 16), "PNG")


def data_root() -> Path:
    from django.conf import settings

    return Path(getattr(settings, "NM_DATA_DIR", Path(settings.MEDIA_ROOT).parent)) / "design"
