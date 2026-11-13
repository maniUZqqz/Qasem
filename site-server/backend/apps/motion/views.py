"""API ِ «استودیوی موشن» (پنل › فروشگاه › محتوا).

    GET    motion/styles/                              کاتالوگِ سبک‌ها (همهٔ پارامترها) + قالب‌ها + نسبت‌ها
    GET    motion/styles/<id>/thumb/                   تصویرِ نمونهٔ سبک (عمومی)
    GET    motion/player/  |  player/player.js  |  player/fonts/<f>   پخش‌کنندهٔ زندهٔ داخلِ iframe ِ سندباکس (عمومی، با CSP)

    GET    stores/<id>/motion/                         نمای کلی: تاریخچه، وضعیتِ گره/سایت، پیش‌فرضِ برند، محدودیت‌ها، کدهای نمونه
    GET|POST  stores/<id>/motion/assets/               تصویرهای بارگذاری‌شده / بارگذاری (multipart: file)
    DELETE stores/<id>/motion/assets/<pk>/
    GET    stores/<id>/motion/sources/                 عکسِ محصول‌ها و لوگوی فروشگاه برای انتخاب
    POST   stores/<id>/motion/preview/                 {spec} ⇒ spec ِ پاک‌شده + data: URI ِ تصویرها برای پیش‌نمایش
    POST   stores/<id>/motion/ai/                      {idea, style, aspect, lang?, seconds?} ⇒ {spec, source: ai|rules, message}
    POST   stores/<id>/motion/ai-code/                 {idea, style?, aspect?} ⇒ {code, warning}
    POST   stores/<id>/motion/code/check/              {code} ⇒ {ok, error?, line?}
    GET|POST  stores/<id>/motion/renders/              تاریخچه / رندرِ تازه {mode, spec|code, title?, quality?, target?}
    GET|DELETE  stores/<id>/motion/renders/<pk>/
    POST   stores/<id>/motion/renders/<pk>/<cancel|site|retry>/
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import ai, assets, catalog, runner, safety, samples, services, specs, tasks
from .models import MotionAsset, MotionRender
from .tasks import dispatch

logger = logging.getLogger(__name__)

THUMBS_DIR = Path(__file__).resolve().parent / "thumbs"


def _err(message: str, code: str = "motion", http=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http)


def _store(request, store_id, write=True):
    return access.get_store(request.user, store_id, access.CONTENT, write=write)


# ───────────────────────────────────────────── public: catalog, thumbnails, player

class StylesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"styles": catalog.public_list(), "groups": catalog.GROUPS, "templates": specs.TEMPLATES,
                         "scene_types": [{"id": k, "name": v} for k, v in specs.SCENE_LABELS_FA.items()],
                         "aspects": [{"id": k, "name": specs.ASPECT_LABELS[k], "width": w, "height": h} for k, (w, h) in specs.ASPECTS.items()],
                         "transitions": list(catalog.TRANS_KINDS)})


@require_GET
def style_thumb(request, style_id: str):
    if not catalog.get(style_id):
        raise Http404
    p = THUMBS_DIR / f"{style_id}.jpg"
    if not p.is_file():
        raise Http404
    resp = FileResponse(open(p, "rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


# The document must be LTR: the Remotion Player lays out its fixed-size stage with an absolutely positioned box, and in an RTL document that box
# lands off-screen (the preview was a black panel). The Persian text inside the composition sets its own direction, as in the render shell.
PLAYER_HTML = """<!doctype html><html lang="fa" dir="ltr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>motion player</title><style>html,body,#root{margin:0;height:100%;background:#000;overflow:hidden}</style></head>
<body><div id="root"></div><script>window.__NM_FONT_BASE="/api/v1/motion/player/fonts/";</script>
<script src="/api/v1/motion/player/player.js?v=__V__"></script></body></html>"""

PLAYER_CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src 'self'; "
              "media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
              "frame-ancestors 'self'")


@xframe_options_sameorigin
@require_GET
def player_page(request):
    v = (runner.bundle_version() or {}).get("hash", "dev")
    resp = HttpResponse(PLAYER_HTML.replace("__V__", v), content_type="text/html; charset=utf-8")
    resp["Content-Security-Policy"] = PLAYER_CSP
    resp["Cache-Control"] = "no-cache"
    return resp


def _player_js_path() -> Path:
    return runner.data_dir() / "player" / "player.js"


@require_GET
def player_js(request):
    p = _player_js_path()
    if not p.is_file():
        return HttpResponse("// player is not built (manage.py motion_build)", content_type="application/javascript", status=404)
    resp = FileResponse(open(p, "rb"), content_type="application/javascript")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


@require_GET
def player_font(request, name: str):
    import re

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]+\.(woff2|ttf)", name):
        raise Http404
    for base in (runner.bundle_dir() / "public" / "fonts", runner.repo_motion_dir() / "remotion" / "public" / "fonts"):
        p = base / name
        if p.is_file():
            resp = FileResponse(open(p, "rb"), content_type="font/ttf" if name.endswith(".ttf") else "font/woff2")
            resp["Access-Control-Allow-Origin"] = "*"          # the player's iframe has an opaque origin: fonts are CORS-checked
            resp["Cache-Control"] = "public, max-age=604800"
            return resp
    raise Http404


# ───────────────────────────────────────────── per store

class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        rows = list(MotionRender.objects.filter(store=store).order_by("-created_at")[:40])
        for r in rows:
            if r.state in MotionRender.ACTIVE:
                _nudge(r)
        return Response({
            "renders": [services.render_dict(r) for r in rows],
            "node": services.node_status(),
            "site": {k: v for k, v in runner.site_status().items() if k in ("ready", "reasons")},
            "brand": assets.store_defaults(store),
            "limits": {"max_scenes": specs.MAX_SCENES, "max_total_node": specs.MAX_TOTAL_S_NODE, "max_total_site": specs.MAX_TOTAL_S_SITE,
                       "site_max_short_side": runner.SITE_MAX_SHORT_SIDE, "qualities": list(specs.QUALITY), "default_quality": specs.DEFAULT_QUALITY,
                       "fps": list(specs.FPS_CHOICES), "max_code_kb": 200},
            "code": {"samples": samples.SAMPLES, "allowed_imports": list(safety.ALLOWED_IMPORTS)},
            "sample_spec": specs.sample_spec(),
        })


def _nudge(r: MotionRender) -> None:
    """هر بار که پنل می‌پرسد: وضعیتِ کارِ گره را بخوان (اگر poll ِ Celery از دست رفته باشد هم رندر جلو می‌رود)."""
    try:
        if r.target == MotionRender.Target.NODE and r.state in MotionRender.ACTIVE:
            services.refresh(r)
    except Exception:  # noqa: BLE001
        logger.exception("motion: nudge of %s failed", r.pk)


class AssetsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({"assets": [assets.asset_dict(a) for a in MotionAsset.objects.filter(store=store)[:200]]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        files = request.FILES.getlist("file") or request.FILES.getlist("files")
        if not files:
            return _err("فایلی فرستاده نشد.")
        made, errors = [], []
        for f in files[:10]:
            try:
                made.append(assets.asset_dict(assets.add_upload(store, f, request.data.get("title", ""))))
            except assets.AssetError as exc:
                errors.append(f"{getattr(f, 'name', '')}: {exc}")
        if not made:
            return _err("؛ ".join(errors) or "تصویر ذخیره نشد.")
        return Response({"assets": made, "errors": errors}, status=status.HTTP_201_CREATED)


class AssetView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        a = MotionAsset.objects.filter(pk=pk, store=store).first()
        if a is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            (Path(settings.MEDIA_ROOT) / a.path).unlink(missing_ok=True)
        except OSError:
            pass
        a.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SourcesView(APIView):
    """عکسِ محصول‌ها و لوگوی فروشگاه (برای انتخابگرِ تصویرِ صحنه‌ها)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        from apps.products.models import ProductImage

        out = []
        defaults = assets.store_defaults(store)
        if defaults["logo"]:
            out.append({"ref": "store-logo", "title": "لوگوی فروشگاه", "url": defaults["logo_url"], "group": "لوگو"})
        for pi in ProductImage.objects.filter(product__store=store).select_related("product").order_by("-id")[:60]:
            try:
                out.append({"ref": f"pimg:{pi.pk}", "title": pi.product.name, "url": assets.media_url(pi.image.name), "group": "محصول"})
            except Exception:  # noqa: BLE001
                continue
        for a in MotionAsset.objects.filter(store=store)[:60]:
            out.append({"ref": f"upload:{a.pk}", "title": a.title, "url": assets.media_url(a.path), "group": "بارگذاری‌شده"})
        return Response({"sources": out})


class PreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id, write=False)
        try:
            spec = specs.normalize_spec(request.data.get("spec") or {})
            payload = services.preview_payload(store, spec)
        except (specs.SpecError, services.MotionError) as exc:
            return _err(str(exc), "invalid_spec")
        return Response({"spec": payload, "total_s": spec["total_s"]})


class AiView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = request.data
        try:
            brand = specs.normalize_brand(d.get("brand") or {})
            res = ai.script_from_idea(store, str(d.get("idea") or ""), style=str(d.get("style") or ""), aspect=str(d.get("aspect") or "9:16"),
                                      lang=str(d.get("lang") or "fa"), seconds=max(8, min(90, int(d.get("seconds") or 24))), brand=brand)
        except specs.SpecError as exc:
            return _err(str(exc), "invalid")
        return Response(res)


class AiCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = request.data
        try:
            res = ai.code_from_idea(store, str(d.get("idea") or ""), style=str(d.get("style") or ""), aspect=str(d.get("aspect") or "9:16"))
        except specs.SpecError as exc:
            return _err(str(exc), "invalid")
        except ai.AIUnavailable as exc:
            return _err(str(exc), "ai_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(res)


class CodeCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        _store(request, store_id, write=False)
        res = runner.compile_code(str(request.data.get("code") or ""))
        res.pop("js", None)
        return Response(res)


class RenderListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        rows = MotionRender.objects.filter(store=store).order_by("-created_at")[:100]
        return Response({"renders": [services.render_dict(r) for r in rows]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = request.data
        mode = str(d.get("mode") or "template")
        if mode not in (MotionRender.Mode.TEMPLATE, MotionRender.Mode.AI, MotionRender.Mode.CODE):
            return _err("حالتِ رندر معتبر نیست.")
        if MotionRender.objects.filter(store=store, state__in=MotionRender.ACTIVE).count() >= 6:
            return _err("چند رندرِ فعال دارید؛ صبر کنید تا تمام شوند یا لغوشان کنید.", "too_many", status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            size = None
            if mode == "code" and d.get("width") and d.get("height"):
                size = (int(d["width"]), int(d["height"]))
            r = services.create(store, request.user, mode=mode, title=str(d.get("title") or ""), spec=d.get("spec") if mode != "code" else None,
                                code=str(d.get("code") or ""), quality=str(d.get("quality") or ""), target=str(d.get("target") or "") or None, size=size)
        except services.MotionError as exc:
            return _err(str(exc), "invalid")
        dispatch(r)
        r.refresh_from_db()
        return Response({"render": services.render_dict(r), "node": services.node_status()}, status=status.HTTP_201_CREATED)


class RenderView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write):
        store = _store(request, store_id, write=write)
        return store, MotionRender.objects.filter(pk=pk, store=store).select_related("store").first()

    def get(self, request, store_id, pk):
        _, r = self._get(request, store_id, pk, False)
        if r is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        _nudge(r)
        r.refresh_from_db()
        d = services.render_dict(r)
        if request.query_params.get("full"):
            d["spec"], d["code"] = r.spec, r.code
        return Response({"render": d})

    def delete(self, request, store_id, pk):
        _, r = self._get(request, store_id, pk, True)
        if r is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        if r.state in MotionRender.ACTIVE:
            services.cancel(r)
        r.delete()          # ویدیوی ثبت‌شده در رسانهٔ فروشگاه می‌ماند (در ادیتور استفاده شده باشد)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RenderActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk, action):
        store = _store(request, store_id)
        r = MotionRender.objects.filter(pk=pk, store=store).select_related("store").first()
        if r is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            if action == "cancel":
                services.cancel(r)
            elif action == "site":
                r = services.switch_to_site(r)
                tasks._run(tasks.site_render_task, r.pk)
            elif action == "retry":
                if r.state not in (MotionRender.State.FAILED, MotionRender.State.CANCELLED):
                    return _err("فقط رندرِ ناموفق یا لغوشده دوباره اجرا می‌شود.")
                r.state, r.progress, r.error, r.message, r.job_uid, r.finished_at = MotionRender.State.QUEUED, 0.0, "", "در صف", "", None
                r.save()
                dispatch(r)
            else:
                return _err("کارِ نامعتبر.")
        except services.MotionError as exc:
            return _err(str(exc))
        r.refresh_from_db()
        return Response({"render": services.render_dict(r)})
