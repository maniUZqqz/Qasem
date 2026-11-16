"""استودیوی طراحی — API پنل (همه زیرِ ``stores/<id>/design/``).

    GET    /                          ⇐ نمای کلی: فونت‌ها، سبک‌ها، قالب‌ها، «کدام فایل را به چه کسی بده»، فهرستِ سندها، محصولات، وضعیتِ هوش مصنوعی و سرورِ پردازش
    GET·POST docs/                    ⇐ فهرست / ساختنِ سند (kind=catalog|deck|ui + options)
    GET·PATCH·DELETE docs/<id>/       ⇐ سند (data) · تغییرِ عنوان · حذف
    POST   docs/<id>/ops/             ⇐ {ops:[…]، rev} ویرایش‌ها (همه با کنترلِ rev)
    GET    docs/<id>/scene/           ⇐ هندسهٔ همهٔ صفحه‌ها + چک‌لیست (برای کادرِ انتخاب)       GET docs/<id>/preview/<page>.png?w=900
    GET·POST docs/<id>/exports/       ⇐ خروجی‌ها / ساختنِ خروجی (kind: print_pdf، screen_pdf، png_zip، pptx، pack_printer…)
    GET    exports/<id>/ · exports/<id>/download/
    POST   docs/<id>/designer/ · video/ · site/ · ai/        GET·POST docs/<id>/comments/ · PATCH·DELETE comments/<id>/
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import ai as ai_mod, bridges, brand, catalog_pages as cp, deck_doc, deck_slides as ds, exports, fonts, scene, services, ui_doc, ui_frames as uf
from .models import DesignComment, DesignDoc, DesignExport

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "design", http=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http)


def _store(request, store_id, write: bool = True):
    return access.get_store(request.user, store_id, access.CONTENT, write=write)


def _doc(store, pk) -> DesignDoc | None:
    return DesignDoc.objects.filter(store=store, pk=pk).select_related("store").first()


def _nf():
    return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _guard(fn):
    try:
        return fn(), None
    except services.Conflict as exc:
        return None, _err(str(exc), "conflict", status.HTTP_409_CONFLICT)
    except (services.DesignError, exports.ExportError) as exc:
        return None, _err(str(exc))


# ───────────────────────────── نمای کلی

def _media_url(rel: str) -> str:
    from django.conf import settings

    return f"{settings.MEDIA_URL.rstrip('/')}/{rel.lstrip('/')}" if rel else ""


def _product_rows(store) -> list[dict]:
    from apps.products.models import Product

    rows = []
    for p in Product.objects.filter(store=store).prefetch_related("images").order_by("category__name", "id")[:300]:
        imgs = sorted(p.images.all(), key=lambda i: (not i.is_main, i.order, i.pk))
        rows.append({"id": p.pk, "name": p.name, "price": float(p.price) if p.price is not None else None, "currency": p.currency, "available": p.is_available, "category": p.category.name if p.category_id else "",
                     "image_ref": f"product:{imgs[0].pk}" if imgs and imgs[0].image else "", "image_url": imgs[0].image.url if imgs and imgs[0].image else "", "has_description": bool((p.description or "").strip())})
    return rows


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        ok, why = ai_mod.status(store)
        docs = [services.doc_summary(d) for d in DesignDoc.objects.filter(store=store)[:200]]
        table = uf.style_table()
        return Response({
            "store": {"id": store.pk, "name": store.name, "has_logo": bool(store.logo and store.logo.name)},
            "docs": docs, "products": _product_rows(store),
            "fonts": fonts.catalogue(), "looks": brand.look_themes(),
            "ui": {"styles": [{"key": k, "label": v["label"], "en": v["en"], "mood": v["mood"], "desc": v["desc"], "colors": v["theme"]["colors"], "radius": v["theme"].get("radius")} for k, v in table.items()],
                   "devices": [{"key": k, "label": uf.DEVICE_NAMES[k], "w": uf.ub.DEVICES[k]["w"]} for k in uf.ub.DEVICES]},
            "catalog": {"page_types": [{"key": k, "label": cp.PAGE_TYPE_FA[k]} for k in cp.PAGE_TYPES], "page_sizes": [{"key": k, "w": w, "h": h} for k, (w, h) in scene.PAGE_SIZES.items()],
                        "defaults": cp.DEFAULTS, "layouts": cp.LAYOUT_NAMES},
            "deck": {"slide_types": [{"key": k, "label": ds.SLIDE_TYPE_FA[k]} for k in ds.SLIDE_TYPES], "templates": [{"key": k, "label": v} for k, v in ds.TEMPLATES.items()], "defaults": ds.DEFAULTS},
            "exports": {k: {"label": v[0], "ext": v[1], "kinds": list(v[3])} for k, v in exports.KINDS.items()}, "recipients": exports.RECIPIENTS,
            "ai": {"ok": bool(ok), "message": why}, "node": bridges.node_state(),
        })


class FontFileView(APIView):
    """فونت‌ها (SIL OFL) برای @font-face ِ پنل؛ عمومی و فقط‌خواندنی (مرورگر برای فونت سرآیندِ ورود نمی‌فرستد)."""
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, key, weight):
        if not fonts.known(key) or int(weight) not in fonts.weights_of(key):
            raise Http404
        p = Path(fonts.resolve(key, int(weight)))
        if not p.is_file():
            raise Http404
        r = FileResponse(open(p, "rb"), content_type="font/ttf")
        r["Cache-Control"] = "public, max-age=604800, immutable"
        return r


# ───────────────────────────── سندها

class DocListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        qs = DesignDoc.objects.filter(store=store)
        if request.query_params.get("kind") in ("catalog", "deck", "ui"):
            qs = qs.filter(kind=request.query_params["kind"])
        return Response({"docs": [services.doc_summary(d) for d in qs[:200]]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        doc, err = _guard(lambda: services.create_doc(store, request.user, str(d.get("kind") or ""), title=str(d.get("title") or ""), options=d.get("options") if isinstance(d.get("options"), dict) else {}))
        if err:
            return err
        return Response({"doc": services.doc_public(doc)}, status=status.HTTP_201_CREATED)


class DocView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        doc = _doc(store, pk)
        return _nf() if doc is None else Response({"doc": services.doc_public(doc)})

    def patch(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        d = _body(request)
        if "title" in d:
            services.rename(doc, str(d.get("title") or ""))
        return Response({"doc": services.doc_public(doc)})

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OpsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        d = _body(request)
        ops = d.get("ops") if isinstance(d.get("ops"), list) else []
        out, err = _guard(lambda: services.apply_ops(doc, ops, d.get("rev")))
        if err:
            return err
        return Response({"doc": services.doc_public(out)})


class SceneView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        mode = request.query_params.get("mode") if request.query_params.get("mode") in ("light", "dark") else None
        out, err = _guard(lambda: services.scene_public(doc, mode=mode))
        return err or Response(out)


class PreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk, page):
        store = _store(request, store_id, write=False)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        try:
            w = int(request.query_params.get("w") or 900)
        except ValueError:
            w = 900
        mode = request.query_params.get("mode") if request.query_params.get("mode") in ("light", "dark") else None
        data, err = _guard(lambda: services.preview_bytes(doc, page, w, mode))
        if err:
            return err
        r = HttpResponse(data, content_type="image/png")
        r["Cache-Control"] = "private, max-age=3600"
        return r


# ───────────────────────────── خروجی‌ها

class ExportListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        rows = list(doc.exports.all()[:30])
        for e in rows:
            if e.kind == "mp4" and e.active:
                bridges.refresh_video(e)
        return Response({"exports": [services.export_dict(e) for e in rows]})

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        d = _body(request)
        e, err = _guard(lambda: services.start_export(doc, str(d.get("kind") or ""), d.get("params") if isinstance(d.get("params"), dict) else {}, request.user))
        return err or Response({"export": services.export_dict(e)}, status=status.HTTP_201_CREATED)


class ExportView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, pk, write=False):
        store = _store(request, store_id, write=write)
        return DesignExport.objects.filter(pk=pk, doc__store=store).select_related("doc", "doc__store").first()

    def get(self, request, store_id, pk):
        e = self._get(request, store_id, pk)
        if e is None:
            return _nf()
        if e.kind == "mp4" and e.active:
            e = bridges.refresh_video(e)
        return Response({"export": services.export_dict(e)})

    def delete(self, request, store_id, pk):
        e = self._get(request, store_id, pk, write=True)
        if e is None:
            return _nf()
        if e.file:
            try:
                (exports.data_root() / e.file).unlink(missing_ok=True)
            except OSError:
                pass
        e.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        e = DesignExport.objects.filter(pk=pk, doc__store=store).first()
        p = services.export_file(e) if e else None
        if p is None:
            return _nf()
        mime = exports.KINDS.get(e.kind, ("", "", "application/octet-stream"))[2] if e.kind != "mp4" else "video/mp4"
        r = FileResponse(open(p, "rb"), content_type=mime)
        r["Content-Disposition"] = f'attachment; filename="{e.filename}"'
        return r


# ───────────────────────────── پل‌ها

class DesignerView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        out, err = _guard(lambda: bridges.edit_in_designer(doc, str(_body(request).get("page") or ""), request.user))
        return err or Response(out, status=status.HTTP_201_CREATED)


class VideoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        e, err = _guard(lambda: bridges.deck_to_video(doc, request.user, _body(request)))
        return err or Response({"export": services.export_dict(e), "node": bridges.node_state()}, status=status.HTTP_201_CREATED)


class SiteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        if not request.user.is_staff:
            return _err("سایت‌ساز فقط برای کارکنان است؛ طرح را به آن‌ها بدهید.", "forbidden", status.HTTP_403_FORBIDDEN)
        out, err = _guard(lambda: bridges.create_site(doc, request.user, _body(request)))
        return err or Response({"site": out}, status=status.HTTP_201_CREATED)


class AiView(APIView):
    """پیش‌نویسِ دوبارهٔ ارائه از یک خلاصه (هوش مصنوعی یا قاعده‌ها). فقط اسلایدها عوض می‌شود."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None or doc.kind != "deck":
            return _nf()
        d = _body(request)
        info = services.store_info(store, doc.data.get("settings") or {})
        items = doc.data.get("products") or []
        data, ai = deck_doc.new_deck(info, items, doc.data.get("settings"), d.get("options") if isinstance(d.get("options"), dict) else {}, brief=str(d.get("brief") or doc.data.get("brief") or "")[:1200],
                                     use_ai=bool(d.get("use_ai", True)), facts=doc.data.get("facts") or None, store=store)
        doc.data["slides"] = data["slides"]
        doc.data["brief"] = data["brief"]
        doc.meta = {**(doc.meta or {}), "ai": ai}
        doc.rev += 1
        doc.save(update_fields=["data", "meta", "rev", "updated_at"])
        return Response({"doc": services.doc_public(doc), "ai": ai})


# ───────────────────────────── نظرها

class CommentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        return Response({"comments": [services.comment_dict(c) for c in doc.comments.all()[:500]]})

    def post(self, request, store_id, pk):
        store = _store(request, store_id)
        doc = _doc(store, pk)
        if doc is None:
            return _nf()
        c, err = _guard(lambda: services.add_comment(doc, request.user, _body(request)))
        return err or Response({"comment": services.comment_dict(c)}, status=status.HTTP_201_CREATED)


class CommentView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, store_id, cid, write=True):
        store = _store(request, store_id, write=write)
        return DesignComment.objects.filter(pk=cid, doc__store=store).first()

    def patch(self, request, store_id, cid):
        c = self._get(request, store_id, cid)
        if c is None:
            return _nf()
        d = _body(request)
        if "resolved" in d:
            c.resolved = bool(d["resolved"])
        if "text" in d and str(d["text"]).strip():
            c.text = str(d["text"])[:1200]
        c.save()
        return Response({"comment": services.comment_dict(c)})

    def delete(self, request, store_id, cid):
        c = self._get(request, store_id, cid)
        if c is None:
            return _nf()
        c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SampleView(APIView):
    """«نمونهٔ آماده» (برای چغر: کاتالوگ + ارائهٔ کوتاه + طرحِ صفحهٔ فرود از دادهٔ واقعی)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        out, err = _guard(lambda: services.create_sample(store, request.user, send_to_site=bool(request.user.is_staff and _body(request).get("site", True))))
        return err or Response(out, status=status.HTTP_201_CREATED)


class UiCatalogView(APIView):
    """فهرستِ بلوک‌های سایت‌ساز برای افزودن به فریم (همان تعریفِ سایت‌ساز؛ فرمِ هر بلوک از ``fields`` ساخته می‌شود)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        _store(request, store_id, write=False)
        return Response(ui_doc.block_catalog())
