"""API ِ «سبکِ تازه» (ویرایشگرِ سبکِ استودیوی موشن).

    GET    motion/style-schema/                                  شمای ویرایشگر: نقش‌های رنگ، قلم‌های دارای مجوز، نوع‌ها و پارامترِ هر نوع، شخصیت‌های حرکت، نگهبانِ کنتراست
    GET    stores/<id>/motion/custom-styles/                     سبک‌های این فروشگاه + همگانی‌ها
    POST   stores/<id>/motion/custom-styles/                     ذخیره {style, check_id?, scope?: store|global, base_style?}  (فقط با کنترلِ کیفیتِ قبول)
    GET|PUT|DELETE  stores/<id>/motion/custom-styles/<pk>/       یک سبک / ویرایش {style, ...} / حذف
    GET    stores/<id>/motion/custom-styles/<pk>/export/         {nm_motion_style, style}
    POST   stores/<id>/motion/custom-styles/import/              {json}|{style} ⇒ سبکِ پاک‌شده (برای ویرایشگر؛ ذخیره نمی‌شود)
    POST   stores/<id>/motion/custom-styles/validate/            {style} ⇒ سبکِ پاک‌شده + نگهبانِ کنتراست (+ پالتِ اصلاح‌شده)
    POST   stores/<id>/motion/custom-styles/describe/            {text, base_style?} ⇒ پیش‌نویس (هوش مصنوعی یا قاعده‌ای)
    POST   stores/<id>/motion/custom-styles/palette/             {colors?, dark?} ⇒ پالتِ ۸ نقشی از رنگ‌های برند (یا رنگ‌هایی که فرستاده‌اید)
    POST   stores/<id>/motion/custom-styles/preview/             {style, aspect?, scenes?} ⇒ طرحِ پیش‌نمایشِ زنده با متنِ فروشگاه (spec.style_def)
    POST   stores/<id>/motion/custom-styles/check/               {style} ⇒ کنترلِ کیفیت (پس‌زمینه)
    GET    stores/<id>/motion/custom-styles/check/<cid>/         وضعیت و گزارش
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import assets, catalog, custom, custom_ai, motionlib, services, specs, stylecheck, tasks
from .models import MotionCustomStyle, MotionStyleCheck
from .views import _err, _store

logger = logging.getLogger(__name__)

#: مقدارِ عددیِ فنرهای نام‌دار (آینهٔ presets.ts)؛ آزمونِ tests_custom آن را با presets.ts می‌سنجد
SPRING_VALUES = {
    "gentle": [26, 90, 1], "smooth": [30, 120, 1], "snappy": [20, 220, 0.8], "crisp": [40, 300, 0.7], "bouncy": [10, 160, 0.9],
    "elastic": [6, 130, 0.8], "heavy": [34, 70, 1.6], "slow-reveal": [40, 50, 1.4],
}


def _admin(user) -> bool:
    return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))


def style_schema() -> dict:
    sch = custom.schema()

    def section(sec: str, kinds) -> list:
        return [{"id": k, "label": custom.KIND_LABELS.get(sec, {}).get(k, k), "params": sch[sec].get(k, {})} for k in kinds]

    return {
        "version": custom.SCHEMA,
        "roles": list(custom.ROLES), "role_labels": custom.ROLE_FA,
        "fonts": custom.font_options(),
        "bg": section("bg", catalog.BG_KINDS), "decor": section("decor", catalog.DECOR_KINDS), "tex": section("tex", catalog.TEX_KINDS), "text": section("text", catalog.TEXT_FX),
        "enters": [{"id": k, "label": custom.KIND_LABELS["enter"].get(k, k)} for k in catalog.ENTER_KINDS],
        "transitions": [{"id": k, "label": custom.KIND_LABELS["trans"].get(k, k)} for k in catalog.TRANS_KINDS],
        "eases": [{"id": k, "label": v} for k, v in motionlib.EASES.items()],
        "springs": [{"id": k, "label": v, "value": SPRING_VALUES[k]} for k, v in motionlib.SPRINGS.items() if k in SPRING_VALUES],
        "personalities": custom.PERSONALITIES,
        "shape": custom.SHAPE_SCHEMA,
        "fx": {"chroma": [0, 10], "posterize": [2, 12], "pixel": [2, 10]},
        "guard": [{"fg": a, "bg": b, "need": n, "severity": s, "what": w} for a, b, n, s, w in custom.GUARD],
        "groups": {**catalog.GROUPS, custom.CUSTOM_GROUP: "سبک‌های من"},
        "limits": {"per_store": custom.MAX_PER_STORE, "global": custom.MAX_GLOBAL, "tex": custom.MAX_TEX, "decor": custom.MAX_DECOR},
        "blank": custom.blank_style(),
    }


class SchemaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(style_schema())


def _rows(store) -> list:
    out = []
    for r in MotionCustomStyle.objects.filter(store=store).order_by("-updated_at"):
        out.append(r.as_styledef())
    for r in MotionCustomStyle.objects.filter(store__isnull=True).order_by("-updated_at"):
        out.append(r.as_styledef())
    return out


def _style_in(request) -> dict:
    d = request.data.get("style") if isinstance(request.data, dict) else None
    if not isinstance(d, dict):
        raise custom.StyleError("سبک فرستاده نشد.")
    return d


def _owner_row(request, store, pk) -> MotionCustomStyle | None:
    row = MotionCustomStyle.objects.filter(pk=pk).first()
    if row is None:
        return None
    if row.store_id is None:
        return row                       # global: everybody reads, only an admin writes (checked by the caller)
    return row if row.store_id == store.pk else None


class ListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({"styles": _rows(store), "can_global": _admin(request.user),
                         "limits": {"per_store": custom.MAX_PER_STORE, "global": custom.MAX_GLOBAL}})

    def post(self, request, store_id):
        store = _store(request, store_id)
        try:
            raw = _style_in(request)
            clean = custom.sanitize(raw)
        except custom.StyleError as exc:
            return _err(str(exc), "invalid")
        scope = "global" if request.data.get("scope") == "global" else "store"
        if scope == "global" and not _admin(request.user):
            return _err("ساختِ سبکِ همگانی فقط برای مدیرِ سامانه است.", "forbidden", status.HTTP_403_FORBIDDEN)
        guard = custom.contrast_report(clean)
        if not guard["ok"]:
            return _err("نگهبانِ کنتراست: " + "؛ ".join(guard["errors"][:3]), "contrast", contrast=guard)
        chk = stylecheck.passed(store, clean)
        if chk is None:
            return _err("پیش از ذخیره باید کنترلِ کیفیتِ سبک اجرا و قبول شود.", "check_required", status.HTTP_409_CONFLICT)
        qs = MotionCustomStyle.objects.filter(store=store) if scope == "store" else MotionCustomStyle.objects.filter(store__isnull=True)
        if qs.count() >= (custom.MAX_PER_STORE if scope == "store" else custom.MAX_GLOBAL):
            return _err("به سقفِ تعدادِ سبک رسیده‌اید؛ یکی را حذف کنید.", "limit", status.HTTP_409_CONFLICT)
        taken = set(MotionCustomStyle.objects.values_list("style_id", flat=True))
        sid = custom.make_id(store.pk if scope == "store" else None, clean.get("name_en", ""), clean["name_fa"], taken)
        base = str(request.data.get("base_style") or "")[:60]
        row = MotionCustomStyle.objects.create(
            store=store if scope == "store" else None, style_id=sid, name_fa=clean["name_fa"], name_en=clean.get("name_en", ""), data=clean, base_style=base,
            qa={"state": "pass", "summary": chk.report.get("summary", ""), "geometry": bool(chk.report.get("geometry")), "at": chk.report.get("at", "")},
            qa_hash=chk.style_hash, thumb=chk.thumb, user=request.user)
        return Response({"style": row.as_styledef()}, status=status.HTTP_201_CREATED)


class DetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        row = _owner_row(request, store, pk)
        if row is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        return Response({"style": row.as_styledef()})

    def put(self, request, store_id, pk):
        store = _store(request, store_id)
        row = _owner_row(request, store, pk)
        if row is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        if row.store_id is None and not _admin(request.user):
            return _err("ویرایشِ سبکِ همگانی فقط برای مدیرِ سامانه است.", "forbidden", status.HTTP_403_FORBIDDEN)
        try:
            clean = custom.sanitize(_style_in(request))
        except custom.StyleError as exc:
            return _err(str(exc), "invalid")
        guard = custom.contrast_report(clean)
        if not guard["ok"]:
            return _err("نگهبانِ کنتراست: " + "؛ ".join(guard["errors"][:3]), "contrast", contrast=guard)
        h = custom.style_hash(clean)
        if h != row.qa_hash:
            chk = stylecheck.passed(store, clean)
            if chk is None:
                return _err("سبک عوض شده؛ پیش از ذخیره باید کنترلِ کیفیت دوباره اجرا و قبول شود.", "check_required", status.HTTP_409_CONFLICT)
            row.qa = {"state": "pass", "summary": chk.report.get("summary", ""), "geometry": bool(chk.report.get("geometry")), "at": chk.report.get("at", "")}
            row.qa_hash, row.thumb = chk.style_hash, chk.thumb or row.thumb
        row.name_fa, row.name_en, row.data = clean["name_fa"], clean.get("name_en", ""), clean
        row.save()
        return Response({"style": row.as_styledef()})

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        row = _owner_row(request, store, pk)
        if row is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        if row.store_id is None and not _admin(request.user):
            return _err("حذفِ سبکِ همگانی فقط برای مدیرِ سامانه است.", "forbidden", status.HTTP_403_FORBIDDEN)
        from .models import MotionRender

        if MotionRender.objects.filter(style=row.style_id, state__in=MotionRender.ACTIVE).exists():
            return _err("یک رندرِ فعال با این سبک در جریان است؛ پس از پایانش حذف کنید.", "in_use", status.HTTP_409_CONFLICT)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        row = _owner_row(request, store, pk)
        if row is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        return Response(custom.export_json({**row.data, "name_fa": row.name_fa, "name_en": row.name_en}))


class ImportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        _store(request, store_id, write=False)
        payload = request.data.get("json", request.data.get("style"))
        if payload is None:
            return _err("فایل یا JSON فرستاده نشد.", "invalid")
        try:
            st, notes = custom.import_json(payload)
        except custom.StyleError as exc:
            return _err(str(exc), "invalid")
        return Response({"style": st, "notes": notes, "contrast": custom.contrast_report(st)})


class ValidateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        _store(request, store_id, write=False)
        notes: list = []
        try:
            st = custom.sanitize(_style_in(request), notes=notes)
        except custom.StyleError as exc:
            return _err(str(exc), "invalid")
        rep = custom.contrast_report(st)
        out = {"style": st, "notes": notes, "contrast": rep, "hash": custom.style_hash(st)}
        if not rep["ok"] or rep["warnings"]:
            out["fixed_palette"] = custom.fix_palette(st)
        return Response(out)


class DescribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id, write=False)
        try:
            res = custom_ai.describe(store, str(request.data.get("text") or ""), base_id=str(request.data.get("base_style") or "") or None)
        except custom.StyleError as exc:
            return _err(str(exc), "invalid")
        res["contrast"] = custom.contrast_report(res["style"])
        return Response(res)


class PaletteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id, write=False)
        cols = request.data.get("colors")
        if not isinstance(cols, list) or not cols:
            cols = assets.store_defaults(store)["colors"]
        dark = request.data.get("dark")
        pal = custom.palette_from_colors(cols, dark if isinstance(dark, bool) else None)
        return Response({"palette": pal, "from": [c for c in cols if isinstance(c, str)][:3]})


class PreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id, write=False)
        try:
            clean = custom.sanitize(_style_in(request))
        except custom.StyleError as exc:
            return _err(str(exc), "invalid")
        aspect = str(request.data.get("aspect") or "4:5")
        if aspect not in specs.ASPECTS:
            aspect = "4:5"
        try:
            n = max(1, min(5, int(request.data.get("scenes") or 2)))
        except (TypeError, ValueError):
            n = 2
        sid = "u%d-preview" % store.pk
        with custom.draft(sid, custom.to_styledef(sid, clean, scope="store")):
            try:
                payload = services.preview_payload(store, stylecheck.preview_spec(store, sid, aspect, scenes=n))
            except (services.MotionError, specs.SpecError) as exc:
                return _err(str(exc), "invalid")
        return Response({"spec": payload})


class CheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        try:
            clean = custom.sanitize(_style_in(request))
        except custom.StyleError as exc:
            return _err(str(exc), "invalid")
        if MotionStyleCheck.objects.filter(store=store, state=MotionStyleCheck.State.RUNNING).exclude(style_hash=custom.style_hash(clean)).count() >= 3:
            return _err("چند کنترلِ کیفیتِ دیگر در جریان است؛ کمی صبر کنید.", "too_many", status.HTTP_429_TOO_MANY_REQUESTS)
        chk = stylecheck.start(store, request.user, clean)
        if chk.state == MotionStyleCheck.State.RUNNING and not (chk.report or {}).get("dispatched"):
            chk.report = {**(chk.report or {}), "dispatched": True}
            chk.save(update_fields=["report", "updated_at"])
            tasks.dispatch_style_check(chk.pk)
            chk.refresh_from_db()
        return Response({"check": stylecheck.dto(chk), "fixed_palette": None if custom.contrast_report(clean)["ok"] else custom.fix_palette(clean)})


class CheckDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, cid):
        store = _store(request, store_id, write=False)
        chk = MotionStyleCheck.objects.filter(pk=cid, store=store).first()
        if chk is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        return Response({"check": stylecheck.dto(chk)})
