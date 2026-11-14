# -*- coding: utf-8 -*-
"""API ِ کاتالوگِ 21st.dev (فقط مدیر): جست‌وجو، وضعیتِ خزش، شروعِ خزش، کلیدِ API ِ مالک و گرفتنِ کدِ یک قطعه.

    GET    c21st/                ?q=&cat=&usable=1&page=&size= ⇒ {items[], total, categories[], catalog_size, crawl{}, key{}}
    POST   c21st/crawl/          ⇒ نوبتِ خزش را در صفِ Celery می‌گذارد (۲۰۲)
    POST   c21st/key/ {key} · DELETE c21st/key/   ⇒ کلیدِ API (هرگز در جواب نمی‌آید)
    POST   c21st/code/ {id}      ⇒ کدِ قطعه (فقط مجوزِ آزاد؛ با کلیدِ مالک؛ در سقفِ روزانه)
"""
from rest_framework.response import Response

from .api import bad, studio_api
from .builder import c21st


def _crawl_json() -> dict:
    st = c21st.crawl_state()
    return {"running": c21st.is_running(st), "finished": bool(st.get("finished")), "total": st.get("total", len(c21st.load())), "remaining": st.get("remaining"),
            "details_done": st.get("details_done", 0), "updated_at": st.get("updated_at", ""), "errors": (st.get("errors") or [])[-3:],
            "cats_done": len(st.get("cats_done") or []), "cats_total": len(c21st.CATEGORIES)}


def _int(v, d):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


@studio_api("GET")
def c21st_list(request):
    q = request.query_params
    out = c21st.search(q.get("q", "")[:80], q.get("cat", ""), q.get("usable") == "1", _int(q.get("page"), 1), _int(q.get("size"), 24))
    out["crawl"] = _crawl_json()
    out["key"] = c21st.key_status()
    out["max_ai_refs"] = c21st.MAX_AI_REFS
    out["note"] = ("فهرست از صفحه‌های عمومیِ .md ِ 21st.dev خزیده شده (آن‌جا برای عامل‌ها باز است؛ آموزشِ مدل ممنوع است و نمی‌کنیم). "
                   "به هوشِ مصنوعی فقط تا ۳ قطعه به‌عنوان الهام می‌رسد. هر قطعه مجوزِ خودش را دارد.")
    return Response(out)


@studio_api("POST")
def c21st_crawl(request):
    from .tasks import c21st_refresh

    if c21st.is_running():
        return Response({"ok": True, "message": "خزش هم‌اکنون در حالِ کار است.", "crawl": _crawl_json()}, status=202)
    c21st_refresh.delay(force=True)
    return Response({"ok": True, "message": "به‌روزرسانیِ کاتالوگ در صف گذاشته شد؛ چند دقیقه طول می‌کشد (۱٫۲ ثانیه بینِ هر درخواست).", "crawl": _crawl_json()}, status=202)


@studio_api("POST", "DELETE")
def c21st_key(request):
    if request.method == "DELETE":
        c21st.clear_key()
        return Response({"ok": True, "key": c21st.key_status()})
    try:
        c21st.set_key(str(request.data.get("key") or ""))
    except c21st.CatalogError as exc:
        return bad(exc)
    return Response({"ok": True, "key": c21st.key_status()})


@studio_api("POST")
def c21st_code(request):
    try:
        out = c21st.fetch_code(str(request.data.get("id") or ""))
    except c21st.CatalogError as exc:
        return bad(exc, code=409)
    return Response({"ok": True, **out, "key": c21st.key_status()})
