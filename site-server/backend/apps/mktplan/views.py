"""API برنامهٔ بازاریابی، راهنمای آزمون و گزارشِ ایراد."""
from __future__ import annotations

import datetime as dt
import json
import logging
import uuid

from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access
from apps.stores.models import Store

from . import clock, facts as facts_mod, guide, kinds, planner, runner
from .models import BugReport, MarketingPlan, PlanItem

logger = logging.getLogger(__name__)

PLAN_KEY = "starter"
MAX_SHOT_BYTES = 8 * 1024 * 1024
MAX_NOTE = 4000
MAX_PER_DAY = 200


def _err(msg: str, code: int = 400, **extra):
    return Response({"detail": msg, **extra}, status=code)


def _store(request, store_id, *, write: bool):
    return access.get_store(request.user, store_id, access.CAMPAIGNS, write=write)


def _plan(store) -> MarketingPlan | None:
    return MarketingPlan.objects.filter(store=store, key=PLAN_KEY).first()


# ----------------------------------------------------------------------------- برنامه

class PlanView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        plan = _plan(store)
        if plan is None:
            f = facts_mod.store_facts(store)
            return Response({"plan": None, "facts": facts_mod.summary_public(f), "node": runner.node_state(), "default_start": clock.default_start().isoformat(),
                             "default_start_fa": clock.jalali(clock.default_start()), "groups": kinds.GROUPS})
        runner.sync_plan(plan, refresh=True)
        return Response({"plan": runner.plan_public(plan)})

    def post(self, request, store_id):
        """action: create | run | restart | refresh. ‏create/restart فقط ساختار؛ run می‌سازد (در پس‌زمینه)."""
        store = _store(request, store_id, write=True)
        action = str(request.data.get("action") or "create")
        if action not in ("create", "run", "restart", "refresh", "create_run"):
            return _err("عملیاتِ نامعتبر است.")
        start = None
        raw = request.data.get("start_date")
        if raw:
            try:
                start = dt.date.fromisoformat(str(raw)[:10])
            except ValueError:
                return _err("تاریخِ شروع معتبر نیست (سال-ماه-روز).")
        plan = _plan(store)
        info: dict = {}
        if action in ("create", "create_run", "restart") or plan is None:
            if action in ("run", "refresh") and plan is None:
                return _err("هنوز برنامه‌ای ساخته نشده؛ اول «ساختنِ برنامه» را بزنید.", 404)
            plan, info = planner.ensure_plan(store, request.user, start=start, restart=(action == "restart"))
        started = ""
        if action in ("run", "create_run", "restart"):
            started = runner.run_background(plan, request.user)
        elif action == "refresh":
            runner.sync_plan(plan, refresh=True)
        plan.refresh_from_db()
        return Response({"plan": runner.plan_public(plan), "info": info, "started": started}, status=status.HTTP_200_OK)


class ItemView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, item_id):
        store = _store(request, store_id, write=True)
        item = get_object_or_404(PlanItem.objects.select_related("plan"), pk=item_id, plan__store=store)
        d = request.data.get("decision")
        if d is not None:
            if d not in ("", "approved", "done", "skipped"):
                return _err("تصمیمِ نامعتبر است.")
            item.decision = d
        if "draft" in request.data:
            item.draft = str(request.data.get("draft") or "")[:20000]
            item.ai_wait = False                               # متنی که مالک ویرایش کرد دیگر بازنویسی نمی‌شود
            item.meta = {**(item.meta or {}), "edited": True}
        item.save()
        runner.sync_item(item)
        return Response({"item": runner.item_public(item)})

    def post(self, request, store_id, item_id):
        """اجرای دوبارهٔ فقط همین کار."""
        store = _store(request, store_id, write=True)
        item = get_object_or_404(PlanItem.objects.select_related("plan"), pk=item_id, plan__store=store)
        res = runner.run_plan(item.plan, user=request.user, keys={item.key}, force=True)
        item.refresh_from_db()
        return Response({"item": runner.item_public(item), "result": {k: v for k, v in res.items() if k != "log"}})


# ----------------------------------------------------------------------------- راهنمای آزمون

class GuideView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        plan = _plan(store)
        by_kind: dict[str, dict] = {}
        if plan is not None:
            for i in plan.items.all():
                row = by_kind.setdefault(i.kind, {"total": 0, "waiting_node": 0, "ready": 0, "needs_you": 0})
                row["total"] += 1
                row["waiting_node"] += int(i.status == PlanItem.Status.WAITING_NODE)
                row["ready"] += int(i.status in (PlanItem.Status.READY, PlanItem.Status.DRAFTED))
                row["needs_you"] += int(i.status == PlanItem.Status.NEEDS_YOU)
        bugs: dict[str, int] = {}
        for sec in BugReport.objects.filter(store=store).exclude(state__in=("fixed", "wontfix")).values_list("section", flat=True):
            bugs[sec] = bugs.get(sec, 0) + 1
        sections = guide.public(store.pk)
        for s in sections:
            rows = [by_kind[k] for k in s["kinds"] if k in by_kind]
            s["plan"] = {"total": sum(r["total"] for r in rows), "waiting_node": sum(r["waiting_node"] for r in rows),
                         "ready": sum(r["ready"] for r in rows), "needs_you": sum(r["needs_you"] for r in rows)}
            s["open_bugs"] = bugs.get(s["key"], 0)
        staff = bool(request.user.is_staff)
        return Response({"sections": [s for s in sections if staff or not s["staff"]], "phases": guide.PHASES, "node": runner.node_state(),
                         "has_plan": plan is not None, "is_staff": staff, "open_bugs": sum(bugs.values())})


# ----------------------------------------------------------------------------- گزارشِ ایراد

def _clean_context(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    text = json.dumps(raw, ensure_ascii=False)
    if len(text) > 24000:
        return {"truncated": True, "ua": str(raw.get("ua") or "")[:300], "version": str(raw.get("version") or "")[:40]}
    return raw


def _check_image(f) -> str | None:
    """⇒ متنِ خطا یا None. فقط تصویرِ واقعی و کوچک."""
    if f.size > MAX_SHOT_BYTES:
        return "عکس بزرگ‌تر از ۸ مگابایت است."
    try:
        from PIL import Image

        im = Image.open(f)
        im.verify()
        fmt = (im.format or "").upper()
        f.seek(0)
    except Exception:  # noqa: BLE001
        return "فایلِ ضمیمه تصویرِ معتبر نیست."
    if fmt not in ("PNG", "JPEG", "WEBP", "GIF"):
        return "فقط تصویرِ PNG، JPG یا WEBP پذیرفته می‌شود."
    return None


def bug_public(b: BugReport) -> dict:
    shot = ""
    if b.screenshot:
        try:
            shot = b.screenshot.url
        except Exception:  # noqa: BLE001
            shot = ""
    return {"id": b.pk, "store": b.store_id, "user": b.user.username if b.user_id else "", "section": b.section, "section_title": b.section_title,
            "page_url": b.page_url, "note": b.note, "screenshot": shot, "context": b.context, "state": b.state, "state_label": b.get_state_display(),
            "response": b.response, "created_at": b.created_at.isoformat()}


class BugReportsView(APIView):
    """POST: هر کاربرِ واردشده گزارش می‌فرستد (با یا بی‌فروشگاه). GET: اعضای فروشگاه گزارش‌های فروشگاه، کارکنان همه را می‌بینند."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, store_id=None):
        qs = BugReport.objects.select_related("user")
        if store_id is not None:
            store = _store(request, store_id, write=False)
            qs = qs.filter(store=store)
        elif not request.user.is_staff:
            qs = qs.filter(user=request.user)
        st = request.query_params.get("state")
        if st:
            qs = qs.filter(state=st)
        rows = list(qs[:200])
        return Response({"results": [bug_public(b) for b in rows], "open": qs.filter(state__in=("new", "seen")).count()})

    def post(self, request, store_id=None):
        store = None
        if store_id is not None:
            store = _store(request, store_id, write=False)
        elif request.data.get("store"):
            try:
                store = access.get_store(request.user, int(request.data.get("store")), None, write=False)
            except Exception:  # noqa: BLE001
                store = None
        note = str(request.data.get("note") or "").strip()
        if len(note) < 3:
            return _err("یادداشت را بنویسید (دست‌کم چند کلمه).")
        today = timezone.now() - dt.timedelta(days=1)
        if BugReport.objects.filter(user=request.user, created_at__gte=today).count() >= MAX_PER_DAY:
            return _err("سقفِ گزارش‌های امروز پر شده است.", 429)
        sec_key = str(request.data.get("section") or "").strip()
        sec = guide.by_key().get(sec_key) or guide.section_for_page(str(request.data.get("page_key") or "").strip())
        shot = request.FILES.get("screenshot")
        if shot is not None:
            bad = _check_image(shot)
            if bad:
                return _err(bad)
        b = BugReport.objects.create(
            store=store, user=request.user, section=sec["key"] if sec else (sec_key[:60] if sec_key == "other" else "other"),
            section_title=(sec["title"] if sec else str(request.data.get("section_title") or "")[:160]),
            page_url=str(request.data.get("page_url") or "")[:500], note=note[:MAX_NOTE], context=_clean_context(request.data.get("context")),
        )
        if shot is not None:
            ext = (shot.name.rsplit(".", 1)[-1] if "." in shot.name else "png")[:4].lower()
            ext = ext if ext in ("png", "jpg", "jpeg", "webp", "gif") else "png"
            b.screenshot.save(f"{uuid.uuid4().hex}.{ext}", shot, save=True)        # نامِ تصادفی: نشانیِ عکس حدس‌زدنی نیست
        logger.info("mktplan: bug report #%s section=%s url=%s", b.pk, b.section, b.page_url)
        return Response({"report": bug_public(b)}, status=status.HTTP_201_CREATED)


class BugSectionsView(APIView):
    """فهرستِ بخش‌ها برای انتخابگرِ «گزارشِ ایراد» (بی‌نیاز از فروشگاه)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = bool(request.user.is_staff)
        rows = [{"key": g["key"], "title": g["title"], "phase_title": g["phase_title"], "covers": g["covers"]} for g in guide.GUIDE if staff or not g["staff"]]
        return Response({"sections": rows + [{"key": "other", "title": "جای دیگر / نامشخص", "phase_title": "", "covers": []}]})


class BugReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not request.user.is_staff:
            return _err("فقط کارکنان وضعیتِ گزارش را عوض می‌کنند.", 403)
        b = get_object_or_404(BugReport, pk=pk)
        if "state" in request.data:
            if request.data["state"] not in dict(BugReport.State.choices):
                return _err("وضعیتِ نامعتبر است.")
            b.state = request.data["state"]
        if "response" in request.data:
            b.response = str(request.data["response"] or "")[:4000]
        b.save()
        return Response({"report": bug_public(b)})
