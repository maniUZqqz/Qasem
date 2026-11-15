"""API ِ نسخهٔ ۲ استودیوی موشن: کتابخانهٔ قطعه‌ها، «طرحِ صحنه»ی زنده با تاریخچه، ویرایشِ تکه‌ای/چت، کنترلِ کیفیت، نقدِ بصری، صدا.

    GET    motion/library/                                 قطعه‌ها (شمای فیلدها + نمونه)، منحنی‌ها، فنرها، دوربین، گذارها، پلتفرم‌ها، قالب‌ها
    GET    motion/components/<id>/thumb/                   بندانگشتیِ هر قطعه
    GET    stores/<id>/motion/sound/                       صداها و موسیقی‌های در دسترس
    GET|POST  stores/<id>/motion/plans/                    طرح‌ها / طرحِ تازه {spec, title?}
    GET|PUT|DELETE  stores/<id>/motion/plans/<pk>/         طرح + تاریخچه / ذخیرهٔ ویرایش {spec, label?} / حذف
    POST   stores/<id>/motion/plans/<pk>/patch/            {ops, label?} ⇒ نسخهٔ تازه
    POST   stores/<id>/motion/plans/<pk>/chat/             {text, dry?} ⇒ مدل (یا قاعده‌های فارسی) patch می‌نویسد و اعمال می‌شود
    POST   stores/<id>/motion/plans/<pk>/undo|redo/        برگشت / جلوتر
    POST   stores/<id>/motion/plans/<pk>/restore/          {n}
    POST   stores/<id>/motion/plans/<pk>/qa/               {apply?, geometry?} ⇒ کنترلِ کیفیت (پس‌زمینه)؛ نتیجه در plan.qa
    POST   stores/<id>/motion/plans/<pk>/critique/         نقدِ بصری (پس‌زمینه؛ مدل نبود ⇒ منتظر و خودکار)
    POST   stores/<id>/motion/plans/<pk>/render/           {quality?, target?, qa?, critique?, title?} ⇒ رندر از همین طرح
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.db.models import Count
from django.http import FileResponse, Http404
from django.utils import timezone
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import ai, assets, catalog, components, motionlib, plans, services, specs, tasks
from . import patch as patch_mod
from .models import MotionPlan, MotionRender
from .views import _err, _store

logger = logging.getLogger(__name__)

COMPONENT_THUMBS = Path(__file__).resolve().parent / "thumbs" / "components"


class LibraryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "components": components.public_list(), "groups": components.GROUP_LABELS,
            "eases": [{"id": k, "name": v} for k, v in motionlib.EASES.items()], "springs": [{"id": k, "name": v} for k, v in motionlib.SPRINGS.items()],
            "camera_moves": [{"id": k, "name": v} for k, v in motionlib.CAMERA_MOVES.items()], "exits": [{"id": k, "name": v} for k, v in motionlib.EXIT_KINDS.items()],
            "enters": list(motionlib.ENTER_KINDS), "transitions": list(motionlib.TRANSITIONS), "transition_pack": list(motionlib.TRANSITION_PACK),
            "platforms": [{"id": k, "name": v["name"], "aspect": v["aspect"], "safe": v["safe"]} for k, v in motionlib.PLATFORMS.items() if k],
            "icons": list(components.ICON_NAMES), "icon_labels": components.ICON_LABELS, "emoji": list(components.EMOJI_NAMES), "emoji_labels": components.EMOJI_LABELS, "anchors": list(specs.ANCHORS), "sfx_kinds": list(specs.SFX_KINDS),
            "templates": specs.TEMPLATES, "schema_version": specs.SCHEMA_VERSION,
            "rules": {"read_s_per_word": motionlib.READ_S_PER_WORD, "min_font_frac": motionlib.MIN_FONT_FRAC, "min_contrast": motionlib.MIN_CONTRAST,
                      "lufs": -14, "max_words_per_scene": motionlib.MAX_WORDS_PER_SCENE},
        })


@require_GET
def component_thumb(request, cid: str):
    if cid not in components.COMPONENTS:
        raise Http404
    p = COMPONENT_THUMBS / f"{cid}.jpg"
    if not p.is_file():
        raise Http404
    resp = FileResponse(open(p, "rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


class SoundView(APIView):
    """صداهای گوینده و موسیقی‌هایی که این فروشگاه همین حالا می‌تواند بگذارد."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        voices, music, note = [], [], ""
        try:
            from services.audio import studio

            voices = [{"id": v.get("id"), "name": v.get("name"), "where": v.get("where"), "available": bool(v.get("available")), "gender": v.get("gender", "")}
                      for v in studio.voices(store)]
        except Exception as exc:  # noqa: BLE001
            note = f"فهرستِ صداها خوانده نشد: {exc}"
        try:
            from apps.ai.models import AudioAsset

            for a in AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY).order_by("-saved", "-created_at")[:40]:
                music.append({"ref": f"audio:{a.pk}", "title": a.title, "duration": round(float(a.duration or 0), 1), "bpm": (a.params or {}).get("bpm"), "license": a.license})
        except Exception:  # noqa: BLE001
            pass
        return Response({"voices": voices, "music": music, "note": note, "lufs": -14,
                         "hint": "اگر موسیقی‌ای در کتابخانه نیست، «خودکار» موسیقیِ آغازینِ سامانه (CC0) را می‌گذارد."})


class PlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        rows = MotionPlan.objects.filter(store=store).annotate(n_renders=Count("renders")).order_by("-updated_at")[:60]
        return Response({"plans": [{"id": p.pk, "title": p.title, "updated_at": p.updated_at.isoformat(), "rev": p.cursor, "style": p.spec.get("style"),
                                    "aspect": p.spec.get("aspect"), "scenes": len(p.spec.get("scenes") or []),
                                    "renders": p.n_renders} for p in rows]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        try:
            # the same untouched draft (rev 1, identical plan) is returned instead of piling up copies: every visit to the page used to leave one behind
            clean = plans._clean(request.data.get("spec") or {})
            for old in MotionPlan.objects.filter(store=store, user=request.user, cursor=1).order_by("-updated_at")[:25]:
                if plans._same(old.spec, clean):
                    return Response({"plan": plans.plan_dict(old), "reused": True}, status=status.HTTP_200_OK)
            plan = plans.create(store, request.user, request.data.get("spec") or {}, title=str(request.data.get("title") or ""),
                                source=str(request.data.get("source") or "user"), label=str(request.data.get("label") or "نسخهٔ اول"))
        except plans.PlanError as exc:
            return _err(str(exc), "invalid_spec")
        return Response({"plan": plans.plan_dict(plan)}, status=status.HTTP_201_CREATED)


class PlanView(APIView):
    permission_classes = [IsAuthenticated]

    def _plan(self, request, store_id, pk, write):
        store = _store(request, store_id, write=write)
        return store, MotionPlan.objects.filter(pk=pk, store=store).select_related("store").first()

    def get(self, request, store_id, pk):
        _, plan = self._plan(request, store_id, pk, False)
        if plan is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        return Response({"plan": plans.plan_dict(plan)})

    def put(self, request, store_id, pk):
        _, plan = self._plan(request, store_id, pk, True)
        if plan is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        notes: list = []
        try:
            spec = specs.normalize_spec(request.data.get("spec") or {}, notes=notes)
            if request.data.get("title"):
                plan.title = str(request.data["title"])[:200]
                plan.save(update_fields=["title", "updated_at"])
            plan = plans.commit(plan, spec, label=str(request.data.get("label") or "ویرایش"), source="user", coalesce=True)
        except (specs.SpecError, plans.PlanError) as exc:
            return _err(str(exc), "invalid_spec")
        return Response({"plan": plans.plan_dict(plan), "notes": notes})

    def delete(self, request, store_id, pk):
        _, plan = self._plan(request, store_id, pk, True)
        if plan is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        plan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk, action):
        store = _store(request, store_id)
        plan = MotionPlan.objects.filter(pk=pk, store=store).select_related("store").first()
        if plan is None:
            return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        d = request.data
        try:
            if action == "patch":
                plan, summary = plans.apply_ops(plan, d.get("ops"), label=str(d.get("label") or ""), source="patch")
                return Response({"plan": plans.plan_dict(plan), "changes": summary})
            if action == "chat":
                res = ai.patch_from_chat(store, plan.spec, str(d.get("text") or ""))
                if not res["ops"]:
                    return Response({"plan": plans.plan_dict(plan), "say": res["say"], "source": res["source"], "message": res.get("message", ""), "applied": False})
                if d.get("dry"):
                    return Response({"say": res["say"], "ops": res["ops"], "source": res["source"], "message": res.get("message", ""), "applied": False})
                plan, summary = plans.apply_ops(plan, res["ops"], label="چت: " + str(d.get("text") or "")[:100], source="chat")
                return Response({"plan": plans.plan_dict(plan), "say": res["say"], "source": res["source"], "message": res.get("message", ""), "changes": summary, "applied": True})
            if action in ("undo", "redo"):
                plan = plans.step(plan, -1 if action == "undo" else 1)
                return Response({"plan": plans.plan_dict(plan)})
            if action == "restore":
                plan = plans.restore(plan, int(d.get("n") or 0))
                return Response({"plan": plans.plan_dict(plan)})
            if action == "qa":
                if tasks.qa_running(plan.qa):
                    return _err("کنترلِ کیفیت همین حالا در حال اجراست؛ چند لحظه صبر کنید.", "busy", status.HTTP_409_CONFLICT)
                plan.qa = tasks.qa_start_state()
                MotionPlan.objects.filter(pk=plan.pk).update(qa=plan.qa)           # not save(): the plan's own "updated" time is the owner's edit time
                tasks._run(tasks.qa_task, plan.pk, bool(d.get("apply", True)), bool(d.get("geometry", True)))
                plan.refresh_from_db()
                return Response({"plan": plans.plan_dict(plan, with_history=False)}, status=status.HTTP_202_ACCEPTED)
            if action == "critique":
                if (plan.critique or {}).get("state") in ("waiting", "running") and (timezone.now() - plan.updated_at).total_seconds() < 3600:
                    return Response({"plan": plans.plan_dict(plan, with_history=False)}, status=status.HTTP_202_ACCEPTED)
                tasks.schedule_critique(plan)
                plan.refresh_from_db()
                return Response({"plan": plans.plan_dict(plan, with_history=False)}, status=status.HTTP_202_ACCEPTED)
            if action == "render":
                if MotionRender.objects.filter(store=store, state__in=MotionRender.ACTIVE).count() >= 6:
                    return _err("چند رندرِ فعال دارید؛ صبر کنید تا تمام شوند یا لغوشان کنید.", "too_many", status.HTTP_429_TOO_MANY_REQUESTS)
                r = services.create(store, request.user, mode=str(d.get("mode") or "template") if d.get("mode") in ("template", "ai") else "template", title=str(d.get("title") or plan.title),
                                    spec=plan.spec, quality=str(d.get("quality") or ""), target=str(d.get("target") or "") or None, plan=plan,
                                    qa=bool(d.get("qa", True)), critique=bool(d.get("critique", False)))
                tasks.dispatch(r)
                r.refresh_from_db()
                return Response({"render": services.render_dict(r), "node": services.node_status()}, status=status.HTTP_201_CREATED)
        except (plans.PlanError, patch_mod.PatchError, specs.SpecError, services.MotionError) as exc:
            return _err(str(exc), "invalid")
        return _err("کارِ نامعتبر.", "invalid_action")


__all__ = ["LibraryView", "component_thumb", "SoundView", "PlansView", "PlanView", "PlanActionView", "access", "catalog"]
