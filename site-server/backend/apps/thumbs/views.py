"""تامنیل‌ساز — API پنل (همه زیرِ ``stores/<id>/thumbnails/``).

    GET   /                              ⇐ قالب‌ها، سبک‌ها، فونت‌ها، رنگِ برند، وضعیتِ هوش مصنوعی/سرورِ پردازش، محصول‌ها، تاریخچهٔ اخیر
    GET   styles/<سبک>/sample.jpg        ⇐ پیش‌نمایشِ نمونهٔ یک سبک (ساختگی، کَش‌شده)
    GET   moodboard/                     ⇐ الگوهای رایجِ چیدمان (توصیفِ گزیده)
    GET/POST references/ · POST references/search/ · DELETE references/<id>/   ⇐ مرجع (پینِ پینترست، پوسترِ آزاد، عکسِ خودتان) ⇒ رنگ/حال‌وهوا/چیدمان
    POST  ideas/                         ⇐ {topic|product, format, count, number, other, ai, use_price, reference?, palette?} ⇒ ایده‌ها
    POST  preview/                       ⇐ {spec} ⇒ پیش‌نمایشِ سریع (JPEG base64)
    POST  render/                        ⇐ {spec, variants, title, ai?} ⇒ نسخه‌های A/B (کامل)
    GET   items/ · items/<id>/ (GET، PATCH، DELETE) · items/<id>/download/?fmt=png|jpg
    POST  items/<id>/editor/             ⇒ عکس در کتابخانهٔ ادیتورِ عکس
    GET   items/<id>/layers/             ⇒ فایل لایه‌دار
    GET   batches/<batch>/zip/
    POST  backgrounds/ · GET backgrounds/<uid>/ · DELETE backgrounds/<uid>/    (پس‌زمینهٔ هوش مصنوعی روی GPU)
    POST  cutout/ · GET cutout/<uid>/    (حذفِ پس‌زمینه: روی سایت یا سرورِ پردازش)
    GET   library/ · POST library/upload/ · POST library/import/
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from urllib.parse import quote

from django.http import FileResponse, Http404, HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.looks import library as looks_library
from apps.stores import access

from . import aibg, archetypes, cutout, ideation, palette, references, services, typo
from . import formats as F
from . import render as R
from .models import Thumbnail
from .styles import STYLE_ORDER, STYLES

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "thumbs", http=status.HTTP_400_BAD_REQUEST, extra: dict | None = None):
    return Response({"error": {"code": code, "message": message, **(extra or {})}}, status=http)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _not_found():
    return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)


def _store(request, store_id, write: bool = True):
    return access.get_store(request.user, store_id, access.CONTENT, write=write)


def _item(store, pk) -> Thumbnail | None:
    try:
        return Thumbnail.objects.filter(store=store, pk=int(pk)).select_related("store").first()
    except (TypeError, ValueError):
        return None


def _sample_url(store_id):
    def fn(style, fmt):
        return f"/api/v1/stores/{store_id}/thumbnails/styles/{style}/sample.jpg?fmt={fmt}"
    return fn


def styles_public() -> list[dict]:
    return [STYLES[k].public() for k in STYLE_ORDER]


def fonts_public() -> list[dict]:
    return [{"key": k, "title": v[0]} for k, v in typo.FONT_CHOICES.items()]


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        services.nudge_waiting(store)
        kit = services.brand_kit(store)
        return Response({
            "formats": [f.public() for f in F.FORMATS.values()], "default_format": F.DEFAULT_FORMAT,
            "styles": styles_public(), "fonts": fonts_public(),
            "moods": [{"key": k, "title": palette.MOOD_FA[k]} for k in palette.MOODS], "themes": palette.themes_public(),
            "brand": {"colors": kit["colors"], "heading_font": kit["heading_font"], "has_logo": kit["has_logo"], "store_name": store.name},
            "ai_background": aibg.availability_with_selftest(), "bg_presets": [{"key": k, "title": v[0]} for k, v in aibg.PRESETS.items()],
            "products": services.products_for_picker(store),
            "limits": {"max_variants": services.MAX_VARIANTS, "text": R.CONTENT_LIMITS},
            "items": [services.thumb_dict(t) for t in services.history(store, 12)],
        })


class SampleThrottle(AnonRateThrottle):
    """هر بار عوض‌کردنِ قالب ۱۵ نمونه می‌خواهد؛ سقفِ ۳۰ در دقیقهٔ پیش‌فرض بعد از چند کلیک ۴۲۹ می‌داد و تصویرِ سبک‌ها می‌شکست (بازبینیِ ۱۱/۱۳).
    فایل‌ها یک‌بار ساخته و کش می‌شوند و مجموعه‌شان محدود است (سبک × قالب)؛ پس سقفِ بالاتر خطری ندارد."""
    scope = "thumb_sample"
    rate = "600/min"


class StyleSampleView(APIView):
    """نمونهٔ ساختگیِ یک سبک. ``<img src>`` سرآیندِ Authorization نمی‌فرستد، پس بدونِ ورود هم باز می‌شود (تصویر کاملاً ساختگی و عمومی است؛
    هیچ دادهٔ فروشگاه ندارد). فقط ``?brand=1`` برای کاربرِ واردشده با رنگ‌های برندِ همان فروشگاه کشیده می‌شود."""
    permission_classes = [AllowAny]
    throttle_classes = [SampleThrottle]

    def get(self, request, store_id, key):
        if key not in STYLES:
            raise Http404()
        fmt = request.query_params.get("fmt") or STYLES[key].formats[0]
        if fmt not in F.FORMATS:
            fmt = STYLES[key].formats[0]
        brand: list[str] = []
        if request.query_params.get("brand") == "1" and request.user and request.user.is_authenticated:
            brand = services.brand_kit(_store(request, store_id, write=False))["colors"]
        tag = hashlib.sha1((",".join(brand)).encode()).hexdigest()[:8] if brand else "plain"
        p = services.photo.abs_path(f"thumbs/_samples/{key}-{fmt}-{tag}-v1.jpg")
        if not p.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")          # هم‌زمانیِ چند درخواست: خواندنِ فایلِ نیمه‌نوشته ممکن نباشد
            tmp.write_bytes(services.sample_image(key, fmt, brand))
            os.replace(tmp, p)
        resp = FileResponse(open(p, "rb"), content_type="image/jpeg")
        resp["Cache-Control"] = "private, max-age=3600"
        return resp


class MoodboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({"archetypes": archetypes.public(_sample_url(store.pk)), "origins": archetypes.ORIGINS,
                         "note": "توصیفِ گزیدهٔ الگوهای رایج است؛ از پینترست یا پوسترِ فیلم چیزی برداشته یا کپی نشده."})


class IdeasView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = request.data
        product = None
        if d.get("product"):
            from apps.products.models import Product

            try:
                product = Product.objects.filter(store=store, pk=int(d["product"])).first()
            except (TypeError, ValueError):
                product = None
            if product is None:
                return _err("محصول پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        fmt = str(d.get("format") or F.DEFAULT_FORMAT)
        if fmt not in F.FORMATS:
            return _err("قالبِ ناشناخته است.")
        number = int(d["number"]) if str(d.get("number") or "").strip().isdigit() else None
        ref = None
        if d.get("reference"):
            ref = references.get(store.pk, str(d["reference"]))
            if ref is None:
                return _err("مرجع پیدا نشد (شاید پاک شده است).", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            result = ideation.ideate(store, str(d.get("topic") or ""), product=product, fmt=fmt, count=_int(d.get("count"), 6), number=number,
                                     other=str(d.get("other") or "")[:80], use_ai=bool(d.get("ai", True)), variation=_int(d.get("variation"), 0),
                                     use_price=bool(d.get("use_price", False)))
        except ValueError as exc:
            return _err(str(exc))
        if ref is not None:
            mode = "reference" if str(d.get("palette") or "") == "reference" else "brand"
            result["ideas"] = references.restyle(result["ideas"], ref, fmt=fmt, palette_mode=mode)
            result["reference"] = {"id": ref["id"], "title": ref.get("title", ""), "mood_fa": ref["analysis"]["mood_fa"], "palette_mode": mode}
            result["message"] += f" ایده‌ها با رنگ، حال‌وهوا و چیدمانِ مرجعِ «{ref.get('title') or 'بدون‌نام'}» دوباره پوشانده شد؛ متن‌ها دست‌نخورده‌اند."
        row = services.save_idea_set(store, request.user, product, result)
        result["id"] = row.pk
        if bool(d.get("ai", True)) and result.get("via") == "rules" and (result.get("ai") or {}).get("parkable"):
            from apps.compute import deferred

            queued = deferred.defer("thumbs.ideas", store, {
                "topic": str(d.get("topic") or ""), "product_id": getattr(product, "pk", None), "fmt": fmt, "count": _int(d.get("count"), 6), "number": number,
                "other": str(d.get("other") or "")[:80], "variation": _int(d.get("variation"), 0), "use_price": bool(d.get("use_price", False))},
                user=request.user, reason=(result.get("ai") or {}).get("reason") or "")
            if queued:
                result["queued"] = queued
                result["message"] = str(result.get("message") or "").replace("وقتی هوش مصنوعی برگردد همین دکمه پیشنهادهای هوشمند می‌دهد.", "این درخواست «در صف تا روشن شدنِ سرورِ پردازش» ماند؛ ایده‌های هوشمند خودکار می‌رسد.")
        return Response(result)


class RefThrottle(UserRateThrottle):
    """جست‌وجو و گرفتنِ مرجع به سایتِ بیرونی می‌رود؛ سقفِ نرم تا ابزار به ابزارِ خزنده تبدیل نشود."""
    scope = "thumb_ref"
    rate = "40/min"


class ReferencesView(APIView):
    """GET ⇒ مرجع‌های فروشگاه (مودبردِ شما) · POST ⇒ مرجعِ تازه: فایلِ ``file`` ، یا ``{url}`` (عکس یا صفحه، مثلِ پینِ پینترست) ، یا ``{commons: {thumb_url, title, author, license, page_url}}``."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [RefThrottle]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({"references": references.listing(store.pk), "max": references.MAX_REFS_PER_STORE,
                         "pinterest_note": "پینترست API ِ عمومیِ جست‌وجو ندارد؛ پینِ دلخواه را باز کنید و نشانیِ همان صفحه را بدهید. عکس‌های پینترست در ایران فیلتر است: اگر مرورگرتان (با VPN) به آن می‌رسد خودش آن را می‌گیرد، وگرنه عکس را ذخیره و از «عکسِ خودم» بارگذاری کنید. عکس فقط تحلیل می‌شود و در خروجی نمی‌آید.",
                         "sources": references.SOURCES})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = request.data
        try:
            up = request.FILES.get("file")
            if up is not None:
                if up.size > references.MAX_IMAGE_BYTES:
                    raise references.RefError("عکس بزرگ‌تر از ۸ مگابایت است.")
                img = references._open_image(up.read())
                row = references.save(store.pk, img, source="upload", title=str(d.get("title") or os.path.splitext(os.path.basename(up.name))[0])[:160])
            elif d.get("commons"):
                c = d["commons"] if isinstance(d["commons"], dict) else {}
                img = references.fetch_commons(str(c.get("thumb_url") or ""))
                row = references.save(store.pk, img, source="commons", title=str(c.get("title") or "")[:160],
                                      extra={"page_url": str(c.get("page_url") or "")[:300], "author": str(c.get("author") or "")[:100],
                                             "license": str(c.get("license") or "")[:40], "license_url": str(c.get("license_url") or "")[:300],
                                             "image_url": str(c.get("thumb_url") or "")[:300]})
            elif d.get("url"):
                img, meta = references.fetch_url(str(d["url"]))
                row = references.save(store.pk, img, source=meta["source"], title=str(d.get("title") or meta.get("title") or "")[:160],
                                      extra={"page_url": meta["page_url"], "image_url": meta["image_url"]})
            else:
                return _err("عکس، نشانی یا یک پوسترِ آزاد بدهید.")
        except references.RefError as exc:
            return _err(str(exc), extra=exc.extra)
        return Response(row, status=status.HTTP_201_CREATED)


class ReferenceSearchView(APIView):
    """POST ``{q}`` ⇒ پوسترهای آزادِ ویکی‌مدیا کامنز (مجوزِ آزاد؛ پدیدآور و مجوز کنارِ هر نتیجه)."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [RefThrottle]

    def post(self, request, store_id):
        _store(request, store_id, write=False)
        try:
            rows = references.search_commons(str(request.data.get("q") or ""), limit=_int(request.data.get("limit"), 12))
        except references.RefError as exc:
            return _err(str(exc))
        return Response({"results": rows, "note": "فقط پرونده‌های با مجوزِ آزاد (مالکیتِ عمومی، CC0، CC BY، CC BY-SA). عکس فقط برای تحلیلِ رنگ و چیدمان است."})


class ReferenceView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, rid):
        store = _store(request, store_id)
        if not references.delete(store.pk, rid):
            return _not_found()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id, write=False)
        try:
            return Response(services.preview(store, request.data.get("spec")))
        except services.ThumbError as exc:
            return _err(str(exc))


class RenderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = request.data
        try:
            made = services.create(store, request.user, d.get("spec"), variants=_int(d.get("variants"), 1), title=str(d.get("title") or "")[:200],
                                   ai=d.get("ai") if isinstance(d.get("ai"), dict) else None)
        except services.ThumbError as exc:
            return _err(str(exc))
        return Response({"items": [services.thumb_dict(t, full=True) for t in made], "batch": made[0].batch if made else ""}, status=status.HTTP_201_CREATED)


class ItemListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        services.nudge_waiting(store)
        try:
            before = int(request.query_params.get("before") or 0) or None
            limit = int(request.query_params.get("limit") or 40)
        except ValueError:
            before, limit = None, 40
        rows = services.history(store, limit, before)
        return Response({"items": [services.thumb_dict(t) for t in rows], "has_more": len(rows) >= limit})


class ItemView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        t = _item(store, pk)
        if t is None:
            return _not_found()
        if t.state == Thumbnail.State.WAITING_BG:
            services.refresh(t)
            t.refresh_from_db()
        return Response(services.thumb_dict(t, full=True))

    def patch(self, request, store_id, pk):
        store = _store(request, store_id)
        t = _item(store, pk)
        if t is None:
            return _not_found()
        patch = request.data.get("spec") if isinstance(request.data.get("spec"), dict) else {}
        if "title" in request.data:
            t.title = str(request.data.get("title") or "")[:200]
        try:
            t = services.rerender(t, patch, user=request.user)
        except services.ThumbError as exc:
            return _err(str(exc))
        return Response(services.thumb_dict(t, full=True))

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        t = _item(store, pk)
        if t is None:
            return _not_found()
        services.delete(t)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ItemDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        t = _item(store, pk)
        kind = "png" if request.query_params.get("fmt") == "png" else "jpg"
        rel = (t.files or {}).get(kind) if t else None
        if not rel or not services.photo.abs_path(rel).is_file():
            raise Http404()
        resp = FileResponse(open(services.photo.abs_path(rel), "rb"), content_type="image/png" if kind == "png" else "image/jpeg")
        resp["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(services.safe_name(t.title, kind))
        return resp


class ItemEditorView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        t = _item(store, pk)
        if t is None:
            return _not_found()
        try:
            asset = services.open_in_editor(t, request.user)
        except (services.ThumbError, services.photo.PhotoError) as exc:
            return _err(str(exc))
        return Response({"asset": services.photo.asset_dict(asset), "url": f"/stores/{store.pk}/photo-editor?asset={asset.pk}&mode=manual"},
                        status=status.HTTP_201_CREATED)


class ItemLayersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        t = _item(store, pk)
        if t is None:
            raise Http404()
        try:
            data, _notes = services.layered_file(t)
        except Exception as exc:  # noqa: BLE001
            logger.exception("thumbs: layered export failed")
            return _err(f"فایل لایه‌دار ساخته نشد: {exc}")
        resp = HttpResponse(data, content_type="image/vnd.adobe.photoshop")
        resp["Content-Disposition"] = f'attachment; filename="thumbnail-{t.pk}-layers.psd"'
        return resp


class BatchZipView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, batch):
        store = _store(request, store_id, write=False)
        data = services.zip_batch(store, batch)
        if data is None:
            raise Http404()
        resp = HttpResponse(data, content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="thumbnails-{batch}.zip"'
        return resp


class BackgroundsView(APIView):
    """پس‌زمینهٔ هوش مصنوعی: دستور (preset / متنِ فارسی / سبک) ⇒ کارِ GPU در صفِ ماندگار."""
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        _store(request, store_id, write=False)
        return Response({"availability": aibg.availability(), "presets": [{"key": k, "title": v[0]} for k, v in aibg.PRESETS.items()]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = request.data
        fmt = str(d.get("format") or F.DEFAULT_FORMAT)
        if fmt not in F.FORMATS:
            return _err("قالبِ ناشناخته است.")
        style = d.get("style") if d.get("style") in STYLES else ""
        colors = services.brand_kit(store)["colors"] if d.get("use_brand", True) else []
        look = looks_library.known(d.get("look"))
        raw_theme = str(d.get("theme") or "")
        theme = palette.theme_key(raw_theme) or raw_theme
        prompt, info = aibg.resolve_prompt(store, text=str(d.get("text") or "")[:400], preset=str(d.get("preset") or ""), style=style, colors=colors,
                                           prompt_en=str(d.get("prompt_en") or "")[:400], look=look, theme=theme if theme in looks_library.THEMES else "")
        jobs, errors = [], []
        count = max(1, min(3, _int(d.get("count"), 1)))
        for i in range(count):
            try:
                seed = int(d["seed"]) + i if str(d.get("seed") or "").strip().isdigit() else None
                jobs.append(aibg.request(store, request.user, prompt_en=prompt, fmt=fmt, seed=seed, hints=info.get("hints"),
                                         meta={"style": style, "preset": info["preset"], "look": info["look"], "theme": info["theme"]}))
            except aibg.BgError as exc:
                errors.append(str(exc))
                break
        if not jobs:
            return _err(errors[0] if errors else "ساخته نشد.", "bg_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"jobs": jobs, "prompt": prompt, "note": info["note"], "errors": errors}, status=status.HTTP_201_CREATED)


class BackgroundStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, uid):
        store = _store(request, store_id, write=False)
        out = aibg.status(store, uid)
        if out is None:
            return _not_found()
        return Response(out)

    def delete(self, request, store_id, uid):
        store = _store(request, store_id)
        return Response({"cancelled": bool(aibg.cancel(store, uid))})


class CutoutView(APIView):
    """حذفِ پس‌زمینه: ``model`` = rvm (روی سایت، همین حالا) یا u2netp / isnet / birefnet-lite (سرورِ پردازش، صفِ ماندگار)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response(cutout.node_models(store))

    def post(self, request, store_id):
        store = _store(request, store_id)
        try:
            asset = services.PhotoAsset.objects.filter(store=store, pk=int(request.data.get("asset") or 0)).first()
        except (TypeError, ValueError):
            asset = None
        if asset is None:
            return _not_found()
        model = str(request.data.get("model") or "rvm")
        if model == "rvm":
            return Response(cutout.run_site(store, request.user, asset))
        from apps.photoedit import matting_nodes as mn

        if model not in mn.NODE_MODELS:
            return _err("مدلِ ناشناخته است.")
        got = mn.request(store, request.user, asset, [model])
        if not got["jobs"]:
            return _err((got["skipped"] or [{"message": "ثبت نشد."}])[0]["message"], "bg_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"state": "queued", "job": got["jobs"][0], "uid": got["jobs"][0].get("uid", "")}, status=status.HTTP_201_CREATED)


class CutoutStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, uid):
        store = _store(request, store_id, write=False)
        from apps.compute.models import ComputeJob
        from apps.photoedit import matting_nodes as mn

        job = ComputeJob.objects.filter(uid=uid, store=store, kind=mn.JOB_KIND).first()
        if job is None:
            return _not_found()
        st = mn.job_state(job)
        if st["state"] == "ready":
            ref = f"thumbcutjob:{job.uid}"[:60]
            asset = services.PhotoAsset.objects.filter(store=store, source_ref=ref).first()
            if asset is None:
                m = re.match(r"photo-a(\d+)", str((job.payload or {}).get("image", "")))
                origin = services.PhotoAsset.objects.filter(store=store, pk=int(m.group(1))).first() if m else None
                path = mn.result_file(job)
                if origin is not None and path is not None:
                    asset = mn.import_result(store, request.user, origin, path, st.get("model") or "؟")
                    asset.source_ref = ref
                    asset.save(update_fields=["source_ref"])
            if asset is not None:
                st["asset"] = services.library_row(asset)
        return Response(st)


class LibraryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        include = request.query_params.get("include")
        return Response({"assets": services.library(store, include_id=int(include) if str(include or "").isdigit() else None)})


class LibraryUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, store_id):
        store = _store(request, store_id)
        files = request.FILES.getlist("files") or request.FILES.getlist("file")
        if not files:
            return _err("عکسی نیامد (فیلدِ files).")
        made, errors = [], []
        for f in files[:10]:
            try:
                made.append(services.photo.add_upload(store, request.user, f))
            except services.photo.PhotoError as exc:
                errors.append(str(exc))
        code = status.HTTP_201_CREATED if made else status.HTTP_400_BAD_REQUEST
        return Response({"assets": [services.library_row(a) for a in made], "errors": errors}, status=code)


class LibraryImportView(APIView):
    """عکسِ محصول ⇒ کتابخانه: ``{ref: "product_image:12"}``."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        try:
            asset, _created = services.photo.add_ref(store, request.user, str(request.data.get("ref") or ""))
        except services.photo.PhotoError as exc:
            return _err(str(exc))
        return Response({"asset": services.library_row(asset)}, status=status.HTTP_201_CREATED)
