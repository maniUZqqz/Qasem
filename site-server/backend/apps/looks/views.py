"""«سبک تصویر» — API ِ پنل (همه زیرِ ``/api/v1/looks/``؛ خواندن برای هر کاربرِ واردشده).

    GET   /                       ⇐ همهٔ ۱۱۶ سبک + ۲۴ تم + گروه‌ها + نوع‌های تبلیغ. فیلتر: q، group، realism، ad_fit، suitability، family، product_safe،
                                    kind (برای هر ردیف می‌گوید برای آن نوعِ تبلیغ مجاز است یا نه)
    GET   <سبک>/                  ⇐ جزئیاتِ یک سبک + مجازبودن برای هر نوعِ تبلیغ
    GET   <سبک>/preview.svg       ⇐ نمونهٔ رنگیِ داخلی (بدونِ GPU؛ عمومی و کَش‌شدنی)
    GET   <سبک>/sample.jpg        ⇐ تصویرِ نمونهٔ واقعی (وقتی ساخته شده؛ وگرنه ۴۰۴)
    GET   themes/ · themes/<تم>/  ⇐ ۲۴ تمِ رنگی (پالتِ ۶ رنگ، حال‌وهوا)
    POST  compose/                ⇐ {look, kind, theme?, store?, notes?} ⇒ دستورِ مثبت/منفی، پالت و راهنمای گام. سبکِ نامناسبِ این نوع ⇒ ۴۰۰ با توضیحِ فارسی
    GET   check/?look=&kind=      ⇐ فقط «مجاز است؟»
    GET   suggest/?store=<id>     ⇐ ۳ تا ۵ سبک و ۲ تم برای این فروشگاه (از روی پروفایلِ خودش)
    GET   samples/                ⇐ وضعیتِ تصویرهای نمونه (چندتا ساخته شده، سرورِ پردازش، آزمونِ خودکار)
    POST  samples/                ⇐ فقط کارکنان: همین حالا دستهٔ بعدی را در صف بگذار (خودکار هم هر ۵ دقیقه انجام می‌شود)

نمونه‌های رنگی و تصویرِ نمونه هیچ داده‌ای از فروشگاه ندارند؛ برای ``<img src>`` (که سرآیندِ Authorization نمی‌فرستد) عمومی‌اند.
"""
from __future__ import annotations

import hashlib

from django.http import FileResponse, Http404, HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.stores import access

from . import compose, library, preview_svg, samples, schema

KIND_META = [
    {"key": k, "fa": compose.KIND_FA[k], "product_preserving": k in compose.PRODUCT_KINDS}
    for k in compose.KINDS
]


def _err(message: str, code: str = "looks", http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def _store(request, store_id):
    try:
        sid = int(store_id)
    except (TypeError, ValueError):
        return None
    return access.get_store(request.user, sid, access.CONTENT, write=False)


class PreviewThrottle(AnonRateThrottle):
    """منتخب‌گر ۱۱۶ نمونه را یک‌جا می‌خواهد؛ سقفِ پیش‌فرضِ ۳۰ در دقیقه شکستش می‌داد. فایل‌ها ساختگی، ثابت و کَش‌شدنی‌اند."""
    scope = "looks_preview"
    rate = "1500/min"


def _usable(row: dict, kind: str) -> bool:
    return kind not in compose.PRODUCT_KINDS or bool(row["product_safe"])


class LooksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = request.query_params
        kind = str(q.get("kind") or "").upper()
        if kind and kind not in compose.KINDS:
            return _err(f"نوعِ تبلیغ «{kind}» شناخته نیست.", "bad_kind")
        ps = q.get("product_safe")
        rows = library.list_entries(samples.sample_urls())
        rows = library.filter_entries(
            rows, q=q.get("q", ""), group=q.get("group", ""), realism=q.get("realism", ""), ad_fit=q.get("ad_fit", ""),
            suitability=q.get("suitability", ""), family=q.get("family", ""), product_safe=None if ps in (None, "") else ps in ("1", "true", "yes"))
        if kind:
            for r in rows:
                r["usable"] = _usable(r, kind)
        return Response({
            "count": len(rows), "total": len(library.STYLES), "styles": rows, "themes": library.list_themes(), "groups": library.groups(),
            "realism": library.realism_levels(), "ad_fits": library.ad_fits(), "kinds": KIND_META,
            "samples": samples.summary(), "refusal_example_fa": compose.refusal_text("سبکِ تصویرسازی‌شده") if kind in compose.PRODUCT_KINDS else "",
        })


class LookView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, key):
        if key not in library.STYLES:
            return _err("این سبک در کتابخانه نیست.", "not_found", status.HTTP_404_NOT_FOUND)
        out = library.entry(key, detail=True, sample_urls=samples.sample_urls())
        out["kinds"] = {k: compose.public_check(key, k) for k in compose.KINDS}
        return Response(out)


class PreviewSvgView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PreviewThrottle]

    def get(self, request, key):
        s = library.style(key)
        if s is None:
            raise Http404()
        svg = preview_svg.render({**s, "key": key})
        resp = HttpResponse(svg, content_type="image/svg+xml; charset=utf-8")
        resp["Cache-Control"] = "public, max-age=86400"
        resp["ETag"] = '"' + hashlib.md5(svg.encode()).hexdigest()[:16] + '"'
        return resp


class SampleImageView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PreviewThrottle]

    def get(self, request, key):
        p = samples.sample_path(key)
        if p is None:
            raise Http404()
        resp = FileResponse(open(p, "rb"), content_type="image/jpeg")
        resp["Cache-Control"] = "public, max-age=3600"
        return resp


class ThemesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"themes": library.list_themes()})


class ThemeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, key):
        if library.theme(key) is None:
            return _err("این تمِ رنگی در کتابخانه نیست.", "not_found", status.HTTP_404_NOT_FOUND)
        out = library.theme_entry(key)
        out["prompt_fragment"] = library.THEMES[key]["prompt_fragment"]
        out["roles"] = dict(zip(schema.PALETTE_ROLES, library.THEMES[key]["palette"]))
        return Response(out)


class ComposeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        store = None
        if d.get("store") not in (None, ""):
            store = _store(request, d.get("store"))
        try:
            out = compose.compose(str(d.get("look") or ""), str(d.get("kind") or "POSTER"), store, theme_key=str(d.get("theme") or ""),
                                  notes=str(d.get("notes") or "")[:300])
        except compose.LookError as exc:
            return _err(exc.message_fa, exc.code)
        return Response(out)


class CheckView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = request.query_params
        look, kind = str(q.get("look") or ""), str(q.get("kind") or "POSTER")
        if look and look not in library.STYLES:
            return _err("این سبک در کتابخانه نیست.", "unknown_look", status.HTTP_404_NOT_FOUND)
        return Response(compose.public_check(look, kind) if look else {"ok": False, "code": "no_look", "message_fa": "سبکی انتخاب نشده است."})


class SuggestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        store = _store(request, request.query_params.get("store"))
        if store is None:
            return _err("شناسهٔ فروشگاه لازم است.", "store_required")
        try:
            limit = max(3, min(5, int(request.query_params.get("limit") or 5)))
        except ValueError:
            limit = 5
        return Response(library.suggest(store, limit))


class SamplesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import selftest

        out = samples.status()
        try:
            out["selftest"] = selftest.status()
        except Exception:  # noqa: BLE001 — نمایشِ آزمون نباید صفحه را بخواباند
            out["selftest"] = {"state": "none", "message": ""}
        return Response(out)

    def post(self, request):
        if not getattr(request.user, "is_staff", False):
            return _err("فقط کارکنانِ سایت می‌توانند ساختِ تصویرهای نمونه را دستی شروع کنند؛ خودکار هم هر ۵ دقیقه انجام می‌شود.", "forbidden",
                        status.HTTP_403_FORBIDDEN)
        got = samples.harvest()
        res = samples.queue_chunk(limit=samples.CHUNK)
        return Response({**res, **got, "status": samples.status()}, status=status.HTTP_202_ACCEPTED if res["queued"] else status.HTTP_200_OK)
