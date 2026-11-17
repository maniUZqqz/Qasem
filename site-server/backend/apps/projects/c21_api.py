# -*- coding: utf-8 -*-
"""API ِ قطعه‌های 21st در سایت‌ساز (فقط مدیر): پیش‌نمایشِ تصویری، پیش‌نمایشِ زنده با پوستهٔ پروژه، گرفتنِ بلوکِ آمادهٔ درج، و فرمانِ تبدیل.

    GET  c21st/image/<شناسه>/                          ⇒ تصویرِ پیش‌نمایش (webp؛ از کارتِ اشتراکِ عمومیِ 21st.dev)
    GET  projects/<slug>/builder/c21/<کلید>/preview/   ⇒ {html, base_css, page_css, …}: همان قطعه با پوستهٔ همین پروژه (و در صورت خواستن یک سبک)
    GET  projects/<slug>/builder/c21/<کلید>/block/     ⇒ {block}: بلوکِ c21 با متن‌های نمونه؛ پنل درونِ صفحه می‌گذارد
    POST c21st/convert/                                ⇒ نوبتِ تبدیل در صفِ Celery (۲۰۲)
    GET  c21st/pipeline/                               ⇒ وضعیتِ خزش، تبدیل و کارِ گره
    GET  c21st/preview/<کلید>/                         ⇒ {doc, …}: همان قطعه در صفحه‌ای مستقل با پوستهٔ خنثی (بی‌پروژه؛ برای استودیوی طراحی)
    GET  c21st/block/<کلید>/                           ⇒ {block}: بلوکِ c21 بی‌پروژه (استودیوی طراحی در طرحِ UI می‌گذارد؛ «ساختِ سایت از طرح» همان را در سایت‌ساز می‌آورد)
"""
import re

from django.http import FileResponse, Http404
from rest_framework.response import Response

from .api import bad, studio_api
from .builder import api as vb, c21_convert as CV, c21_crawl, c21_embed as EM, c21_node, c21_pipeline, c21st, canvas, styles as styles_mod, theme as theme_mod
from .builder.clean import new_block

_ID = re.compile(r"^[A-Za-z0-9._-]{1,60}/[A-Za-z0-9._-]{1,120}$")


@studio_api("GET")
def c21_image(request, cid):
    if not _ID.match(cid or ""):
        raise Http404
    p = c21_crawl.preview_path(cid)
    if not p.is_file():
        raise Http404
    resp = FileResponse(open(p, "rb"), content_type="image/webp")
    resp["Cache-Control"] = "private, max-age=86400"
    return resp


def _rec(key):
    rec = CV.get_record(key)
    if rec is None:
        raise Http404
    return rec


@studio_api("GET")
def c21_preview(request, slug, key):
    """یک قطعهٔ 21st به‌تنهایی با پوستهٔ همین پروژه (و یک سبکِ دلخواه) برای نمایش در کتابخانه."""
    p = vb._project(slug)
    g = vb._guard(p)
    if g:
        return g
    rec = _rec(key)
    if (rec.get("rtl") or {}).get("status") == "fail":                      # پیش‌نمایشِ قطعهٔ خالی/روی‌هم‌افتاده/نخوانا هم همان ۴۰۹ ِ درج را می‌گیرد (پیش‌تر ۲۰۰ می‌داد)
        return bad(_blocked_message(rec), code=409)
    theme, menu = vb._theme_json(p)
    style = request.query_params.get("style") or ""
    if style in styles_mod.STYLES:
        theme = theme_mod.clean_theme(styles_mod.apply_to_theme(theme, style), p)
    doc = {"v": 1, "blocks": [new_block(EM.TYPE, **EM.default_props(rec))]}
    data = canvas.render_canvas(p, "page", None, doc, theme, vb._clean_menu(menu, p))
    return Response({"key": key, "id": rec["id"], "html": "".join(x["html"] for x in data["parts"]), "base_css": data["base_css"], "page_css": data["page_css"],
                     "title": rec.get("title", ""), "license": rec.get("license", ""), "author": rec.get("author", ""), "library": rec.get("library", ""), "url": rec.get("url", ""),
                     "source": rec.get("source", {}), "rtl": rec.get("rtl", {}), "texts": len(rec.get("texts", [])), "images": len(rec.get("images", []))})


def _blocked_message(rec: dict) -> str:
    why = ((rec.get("rtl") or {}).get("why") or "").strip()
    return "این قطعه برای درج بسته شده است: %s" % (why or "در راست‌به‌چپ/موبایل سرریز می‌کند.")


def _block_for(rec: dict, fa: bool, ai: bool) -> dict:
    """بلوکِ c21 با متن‌های نمونه؛ fa ⇒ فرهنگ‌لغتِ رابط، ai ⇒ بقیه با AI (اختیاری؛ شکستش درج را خراب نمی‌کند). ⇒ {block, translated, ai?}"""
    from .builder import c21_translate as TR

    props = EM.default_props(rec)
    out = {"translated": 0}
    if fa or ai:
        texts = [t.get("v", "") for t in props["texts"]]
        new, n = TR.apply_dictionary(texts)
        out["translated"] = n
        if ai:
            new, info = TR.ai_translate(new)
            out["ai"] = info
            out["translated"] += info.get("translated", 0)
        props["texts"] = [{"v": v} for v in new]
    out["block"] = new_block(EM.TYPE, **props)
    return out


@studio_api("GET", "POST")
def c21_block(request, slug, key):
    """GET ?fa=1 ⇒ بلوکِ آماده (فرهنگ‌لغتِ فارسی)؛ POST {ai: true} ⇒ همان + ترجمهٔ بقیهٔ متن‌ها با AI (متیس بی‌اعتبار ⇒ پیامِ فارسی در ``ai`` و بلوکِ فرهنگ‌لغت)."""
    p = vb._project(slug)
    g = vb._guard(p)
    if g:
        return g
    rec = _rec(key)
    if (rec.get("rtl") or {}).get("status") == "fail":
        return bad(_blocked_message(rec), code=409)
    if request.method == "POST":
        return Response(_block_for(rec, True, bool(request.data.get("ai"))))
    return Response(_block_for(rec, request.query_params.get("fa") == "1", False))


@studio_api("GET")
def c21_preview_free(request, key):
    """پیش‌نمایشِ بی‌پروژه (استودیوی طراحی): صفحهٔ مستقلِ HTML با پوستهٔ خنثی؛ پنل آن را در iframe ِ بی‌اسکریپت (srcdoc) نشان می‌دهد."""
    from .builder import c21_rtl

    rec = _rec(key)
    if (rec.get("rtl") or {}).get("status") == "fail":
        return bad(_blocked_message(rec), code=409)
    pv = EM.preview_page(key)
    if not pv:
        raise Http404
    return Response({"key": key, "id": rec["id"], "doc": c21_rtl.PAGE % (pv["css"], pv["html"]), "title": rec.get("title", ""), "license": rec.get("license", ""),
                     "author": rec.get("author", ""), "library": rec.get("library", ""), "url": rec.get("url", ""), "cats": rec.get("cats", []),
                     "source": {k: (rec.get("source") or {}).get(k, "") for k in ("repo", "license", "copyright")}})


@studio_api("GET")
def c21_block_free(request, key):
    rec = _rec(key)
    if (rec.get("rtl") or {}).get("status") == "fail":
        return bad(_blocked_message(rec), code=409)
    return Response({**_block_for(rec, request.query_params.get("fa") != "0", False), "title": rec.get("title", ""), "cats": rec.get("cats", []), "license": rec.get("license", ""),
                     "library": rec.get("library", "")})


@studio_api("POST")
def c21_convert_start(request):
    from .tasks import c21_convert

    if not CV.toolchain_ready():
        return bad("جعبه‌ابزارِ تبدیل روی سرور نصب نیست (deploy/c21/install.sh).", code=409)
    c21_convert.delay(force=True)
    return Response({"ok": True, "message": "تبدیلِ قطعه‌ها در صف گذاشته شد؛ هر نوبت چند دقیقه طول می‌کشد.", "pipeline": pipeline_json()}, status=202)


def pipeline_json() -> dict:
    st = c21_pipeline.pipeline_state()
    rows = c21st.load()
    node = c21_node.state()
    libs = c21_crawl.load_libs()
    no_source = waiting = 0
    for r in rows:                                               # «بدونِ کدِ عمومی» = تلاش شد و پیدا نشد، یا کتابخانه‌اش مخزنِ عمومی ندارد (هرگز تبدیل نمی‌شود)؛ «در انتظار» = مخزن دارد و نوبتش نرسیده
        if not r.get("usable"):
            continue
        state = (r.get("conv") or {}).get("state")
        if state == "no-source":
            no_source += 1
        elif state is None:
            if (libs.get(r.get("library_id") or "") or {}).get("github"):
                waiting += 1
            else:
                no_source += 1
    converted = sum(1 for r in rows if (r.get("conv") or {}).get("state") == "ok")
    insertable = sum(1 for r in rows if c21st.insertable(r))             # تبدیل‌شده ≠ قابلِ درج: «خالیِ ایستا»، سرریز، متنِ نخوانا، رویِ‌هم‌افتاده یا بی‌متن بسته می‌شود
    kinds = {"section": 0, "widget": 0}
    for e in CV.load_index().values():
        if e.get("rtl") != "fail" and e.get("kind") in kinds:
            kinds[e["kind"]] += 1
    return {"toolchain": CV.toolchain_ready(), "converted": converted, "insertable": insertable, "blocked": max(0, converted - insertable), "kinds": kinds,
            "failed": sum(1 for r in rows if (r.get("conv") or {}).get("state") == "failed"), "no_source": no_source, "waiting": waiting,
            "license_blocked": sum(1 for r in rows if (r.get("conv") or {}).get("state") == "license"), "last": {k: st.get(k) for k in ("converted", "failed", "libs_done", "remaining_libs", "finished_at")},
            "errors": (st.get("errors") or [])[-3:], "node": {"pending": len(node.get("pending", [])), "jobs": node.get("jobs", 0), "ingested": node.get("ingested", 0)}}


@studio_api("GET")
def c21_pipeline_status(request):
    from .c21st_api import _crawl_json

    return Response({"crawl": _crawl_json(), "pipeline": pipeline_json()})
