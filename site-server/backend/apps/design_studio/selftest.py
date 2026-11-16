"""خودآزمونِ استودیوی طراحی (برای «آزمونِ خودکارِ سرورِ پردازش» و دستِ‌ما).

* ``run_offline()`` — بی‌گره/بی‌دیتابیس: چیدمان، کاتالوگِ چغر + PDF چاپی (اندازه و بلید)، ارائهٔ چغر + PPTX، طرحِ UI + SVG، نگهبانِ عدد و مسیرِ هوش مصنوعی با جوابِ ساختگی.
* ``node_spec(model)`` / ``node_check(text)`` — کارِ واقعیِ ``ollama.generate``: پیش‌نویسِ ارائهٔ چغر با مدلِ خودِ مالک؛ قبول یعنی JSON درست و دست‌کم ۳ اسلایدِ معتبر با نگهبانِ عدد.
* ``video_spec()`` / ``video_check(info)`` — کارِ واقعیِ ``edit.slides_mp4``: ۳ اسلایدِ کوچک ⇒ MP4 روی کارتِ گرافیک.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

from PIL import Image

from . import ai as ai_mod, catalog_doc, chagher, deck_doc, deck_slides as ds, exports, fixtures, guard, layout, pdf, render_png, ui_doc

CHECK_TIMEOUT_S = 1800
_PERSIAN = re.compile(r"[؀-ۿ]")


def node_prompt() -> tuple[str, str]:
    info = chagher.info_offline()
    prompt = deck_doc.build_prompt(info, chagher.ITEMS, chagher.FACTS, "معرفیِ کوتاهِ چغر به مربی‌های باشگاه (۶ تا ۸ اسلاید)", {"zero_price_label": "فعلاً بدونِ هزینه"}, 8)
    return prompt, deck_doc.SYSTEM


def node_spec(model: str) -> dict:
    prompt, system = node_prompt()
    return {"kind": "ollama.generate", "payload": {"model": model, "system": system, "prompt": prompt, "stream": False, "think": False, "format": "json",
                                                   "options": {"num_predict": 2200, "temperature": 0.3}}, "timeout_s": CHECK_TIMEOUT_S}


def node_check(text: str) -> tuple[bool, str]:
    parsed = ai_mod.parse_json(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("slides"), list):
        return False, "مدل JSON با کلیدِ «slides» نداد."
    info = chagher.info_offline()
    slides = deck_doc.clean_ai(parsed, chagher.ITEMS, chagher.FACTS, "معرفیِ کوتاهِ چغر", info, {})
    raw = len(parsed["slides"])
    if len(slides) < 3:
        return False, f"از {raw} اسلایدِ مدل فقط {len(slides)} تا وارسی را گذراند (نوع، محصول یا عددِ ساختگی)."
    letters = sum(len(_PERSIAN.findall(json.dumps(s, ensure_ascii=False))) for s in slides)
    if letters < 60:
        return False, "اسلایدهای مدل فارسی نیستند."
    sc = deck_doc.build_scene({"settings": {}, "products": chagher.ITEMS, "slides": slides}, info, None)
    if len(sc["pages"]) != len(slides):
        return False, "ساختِ اسلاید از پیش‌نویسِ مدل ناقص ماند."
    return True, f"{len(slides)} اسلایدِ معتبر از {raw} اسلایدِ مدل؛ نخست: «{slides[0].get('title') or slides[0]['type']}»"


def video_spec() -> dict:
    """سه اسلایدِ کوچکِ برندِ چغر ⇒ کارِ ``edit.slides_mp4`` (بدونِ فایلِ بیرونی)."""
    info = chagher.info_offline()
    data, _ = deck_doc.new_deck(info, chagher.ITEMS, {}, {"steps": chagher.STEPS, "featured": [17], "products_count": 1, "cta": chagher.CTA}, brief="آزمونِ ویدیو", use_ai=False, facts=chagher.FACTS)
    sc = deck_doc.build_scene(data, info, None)
    files, slides = {}, []
    for i, p in enumerate(sc["pages"][:3], 1):
        name = f"s{i:02d}.png"
        im = render_png.render_page(p, None, scale=640 / p["w"])
        files[name] = exports.to_bytes(im, "PNG")
        slides.append({"file": name, "duration": 2})
    return {"kind": "edit.slides_mp4", "payload": {"slides": slides, "width": 640, "height": 360, "fps": 24, "transition": "fade", "transition_s": 0.4}, "files": files, "timeout_s": 600}


def video_check(info) -> tuple[bool, str, str]:
    """video.json ⇒ (قبول؟، پیام، دستگاه)."""
    if not isinstance(info, dict):
        return False, "گزارشِ video.json از سرورِ پردازش نرسید.", ""
    enc = str(info.get("encoder") or "")
    dev = "nvenc" if enc == "h264_nvenc" else ("cpu" if enc else "")
    if int(info.get("slides") or 0) != 3 or not (5.0 <= float(info.get("duration_s") or 0) <= 7.0):
        return False, f"ویدیو درست ساخته نشد: {info}", dev
    if int(info.get("bytes") or 0) < 1500:
        return False, "فایلِ ویدیو خیلی کوچک است.", dev
    return True, f"ویدیوی ۳ اسلایدی ({info.get('duration_s')} ثانیه) با {enc} در {info.get('seconds')} ثانیه ساخته شد.", dev


def run_offline() -> dict:
    """⇒ {ok، checks:[{key، ok، detail}]}. هیچ‌چیز ذخیره نمی‌شود."""
    checks: list[dict] = []

    def check(key: str, ok: bool, detail: str):
        checks.append({"key": key, "ok": bool(ok), "detail": detail})

    # ۱) چیدمان
    els, (w, h) = layout.solve({"t": "frame", "dir": "grid", "cols": 3, "gap": 10, "children": [{"t": "rect", "h": 40} for _ in range(5)]}, 330)
    check("layout", len(els) == 5 and els[0]["x"] > els[2]["x"] and h == 90, f"شبکهٔ ۳ ستونه راست‌به‌چپ، ارتفاع {h:g}")
    # ۲) کاتالوگِ چغر + PDF چاپی
    refs = fixtures.make_images(3)
    items = fixtures.products(refs, 4)
    src = fixtures.source()
    info = chagher.info_offline()
    cat = catalog_doc.new_doc(info, items, {"zero_price_label": "فعلاً بدونِ هزینه"}, {"extra_pages": [{"type": "steps", "title": "چهار قدم", "steps": chagher.STEPS}]}, src)
    b = exports.make_bundle("catalog", cat, info, src, "کاتالوگ", 0)
    data, rep = exports.print_pdf(b)
    m = re.search(rb"/TrimBox \[([0-9. ]+)\]", data)
    trim = [float(x) for x in m.group(1).split()] if m else []
    ok = bool(trim) and abs((trim[2] - trim[0]) - 210 * 72 / 25.4) < 0.1 and rep.get("bleed_mm") == 3.0 and rep.get("marks") and data.startswith(b"%PDF")
    check("catalog_print_pdf", ok, f"{rep.get('pages')} صفحه، برش {trim}، بلید {rep.get('bleed_mm')} میلی‌متر، علامت برش، {len(data) // 1024} کیلوبایت")
    # ۳) ارائه + PPTX
    deck, _ = deck_doc.new_deck(info, chagher.ITEMS, {}, {"steps": chagher.STEPS, "featured": [17, 18], "cta": chagher.CTA}, brief="آزمون", use_ai=False, facts=chagher.FACTS)
    db = exports.make_bundle("deck", deck, info, src, "ارائه", 0)
    px = exports.pptx_bytes(db)
    z = zipfile.ZipFile(io.BytesIO(px))
    types = {s["type"] for s in deck["slides"]}
    check("deck_pptx", z.testzip() is None and "ppt/slides/slide1.xml" in z.namelist() and {"title", "agenda", "product", "stats", "timeline", "cta"} <= types,
          f"{len(db.pages)} اسلاید ({'، '.join(sorted(types))})، PPTX {len(px) // 1024} کیلوبایت")
    # ۴) طرحِ UI + SVG
    ui = ui_doc.new_doc(info, devices=("desktop", "phone"))
    ub = exports.make_bundle("ui", ui, info, src, "طرح", 0)
    svg = exports.svg_files(ub)
    check("ui_frames", len(ub.pages) == 2 and ub.pages[0]["w"] == 1440 and ub.pages[1]["w"] == 390 and all(n.endswith(".svg") for n in svg), f"{len(ub.pages)} فریم، {len(svg)} SVG")
    # ۵) نگهبانِ عدد
    allowed = guard.corpus_numbers(*[f"{p['name']} {p['short']} {p['price']}" for p in chagher.ITEMS], *[f["value"] for f in chagher.FACTS])
    check("number_guard", not guard.unsupported("۵۰ توکن و ۶۰۰٬۰۰۰ تومان", allowed) and guard.unsupported("رضایتِ ۹۸ درصد", allowed) == {"98"}, "عددِ ساختگی شناسایی می‌شود")
    # ۶) مسیرِ هوش مصنوعی با جوابِ ساختگی و بی‌هوش‌مصنوعی
    fake = lambda prompt, system: ({"slides": [{"type": "title", "title": "چغر", "subtitle": "برنامه در ۹۸ ثانیه"}, {"type": "agenda", "items": ["معرفی", "بسته‌ها"]},  # noqa: E731
                                               {"type": "product", "product": 17, "text": "پیش‌نویسِ برنامه"}, {"type": "cta", "title": "شروع کنید"}]}, {"label": "fake"})
    d1, ai1 = deck_doc.new_deck(info, chagher.ITEMS, {}, {}, brief="آزمون", use_ai=True, facts=chagher.FACTS, ask=fake)
    d2, ai2 = deck_doc.new_deck(info, chagher.ITEMS, {}, {}, brief="آزمون", use_ai=True, facts=chagher.FACTS, ask=lambda p, s: (_ for _ in ()).throw(ai_mod.AIUnavailable("متیس ۴۰۲")))
    check("ai_paths", ai1["used"] and d1["slides"][0]["subtitle"] == "" and not ai2["used"] and "۴۰۲" in ai2["message"] and len(d2["slides"]) >= 4,
          f"با هوش مصنوعی: {len(d1['slides'])} اسلاید (عددِ ساختگی حذف شد)؛ بدونِ آن: {len(d2['slides'])} اسلاید با دلیلِ فارسی")
    # ۷) هر نوعِ صفحه و اسلاید در دسترس است
    check("all_types", len(catalog_doc.cp.PAGE_TYPES) == 10 and len(ds.SLIDE_TYPES) == 11, f"{len(catalog_doc.cp.PAGE_TYPES)} نوعِ صفحه، {len(ds.SLIDE_TYPES)} نوعِ اسلاید")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
