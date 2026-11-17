"""مشتری‌یاب API - mounted under /api/v1/growth/finder/ (``crawler/urls.py``). Staff only, like the rest of the Growth Engine.

Views only read the request and shape the answer; the logic is in ``services/`` and ``engine/``.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from django.db.models import Count
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.growth_engine.compliance.models import AuditKind, GrowthSettings
from apps.growth_engine.compliance.services import audit, limits
from apps.growth_engine.core.pagination import GrowthPagination
from apps.growth_engine.core.permissions import IsGrowthStaff
from apps.growth_engine.core.throttles import GrowthBulkThrottle, GrowthExportThrottle
from apps.growth_engine.knowledge import products
from apps.growth_engine.leads.api_utils import validation_response
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services.editing import ValidationFailed

from . import presets
from .engine import fetch, finalize, nodebridge, runner
from .engine.sources import neshan
from .engine.sources import search as search_source
from .models import CrawlCandidate, CrawlFinding, CrawlLog, CrawlMission, CrawlRun, CrawlTask, LeadReminder, OutreachDraft
from .services import drafts as draft_service
from .services import missions, pipeline, results

logger = logging.getLogger(__name__)

SOURCE_INFO = [
    {"key": "osm", "label": missions.SOURCE_LABELS["osm"], "needs_node": False, "needs_key": False, "default": True,
     "help": "برچسب‌های هر نوعِ کسب‌وکار روی نقشه؛ مطمئن‌ترین منبع. سرورهای عمومیِ نقشه گاهی شلوغ‌اند؛ خودش دوباره امتحان می‌کند."},
    {"key": "search", "label": missions.SOURCE_LABELS["search"], "needs_node": False, "needs_key": False, "default": True,
     "help": "فقط چند جست‌وجو؛ نتیجه‌ها پیش از استفاده برای ارتباط با موضوع سنجیده می‌شوند. موتورِ Brave اگر پشتِ‌هم پرسیده شود موقتاً مسدود می‌کند؛ خودش آهسته می‌پرسد و بعد از مسدودی نیم‌ساعت استراحت می‌دهد."},
    {"key": "directory", "label": missions.SOURCE_LABELS["directory"], "needs_node": False, "needs_key": False, "default": True,
     "help": "فهرست‌هایی که robots.txt‌شان اجازه می‌دهد (مثل بدن‌فیت برای باشگاه‌ها) و نشانی‌هایی که خودتان می‌دهید."},
    {"key": "website", "label": missions.SOURCE_LABELS["website"], "needs_node": False, "needs_key": False, "default": True,
     "help": "از صفحهٔ اصلی لینکِ تماس و درباره را دنبال می‌کند: تلفن، ایمیل، شبکه‌های اجتماعی، نشانی، ساعتِ کاری."},
    {"key": "instagram", "label": missions.SOURCE_LABELS["instagram"], "needs_node": True, "needs_key": False, "default": False,
     "help": "پیج‌های عمومیِ کسب‌وکار را از روی هشتگ و مکانی که می‌نویسید پیدا می‌کند (از راهِ فهرستِ وب، نه جست‌وجو در خودِ اینستاگرام)؛ خواندنِ کاملِ پیج با آباگرام روی سرورِ پردازش است و تا روشن‌شدنش در صف می‌ماند."},
    {"key": "neshan", "label": missions.SOURCE_LABELS["neshan"], "needs_node": False, "needs_key": True, "default": False,
     "help": "فقط اگر کلیدِ API نشان را در تنظیماتِ کشف بگذارید."},
]
STAGE_LABELS = {"plan": "برنامه‌ریزی", "discover": "پیدا کردن", "dedupe": "یکی‌کردنِ تکراری‌ها", "enrich": "تکمیلِ اطلاعات", "finalize": "ساختنِ لیدها", "done": "پایان"}
STAGE_WEIGHT = {"plan": 0, "discover": 5, "dedupe": 55, "enrich": 60, "finalize": 92, "done": 100}


class FinderView(APIView):
    permission_classes = [IsGrowthStaff]


def _bad(code: str, message: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"code": code, "detail": message}, status=http)


# --------------------------------------------------------------------------- shapes


def mission_dict(m: CrawlMission, *, with_last: bool = True) -> dict:
    last = m.runs.order_by("-id").first() if with_last else None
    spec = m.spec or {}
    return {
        "id": m.pk, "name": m.name, "preset_key": m.preset_key, "store_id": m.store_id, "store_name": m.store.name if m.store else "", "product": m.product,
        "spec": spec, "types_label": [presets.TYPES[t].fa for t in spec.get("business_types", []) if t in presets.TYPES], "cities": spec.get("cities", []),
        "schedule_days": m.schedule_days, "enabled": m.enabled, "next_run_at": m.next_run_at, "last_run_at": m.last_run_at, "notes": m.notes, "is_archived": m.is_archived,
        "created_at": m.created_at, "findings": CrawlFinding.objects.filter(mission=m).count(), "drafts": OutreachDraft.objects.filter(mission=m).count(),
        "last_run": run_dict(last) if last else None, "active_run": (lambda a: a.pk if a else None)(missions.active_run(m)), "outreach": m.outreach,
    }


def run_dict(r: CrawlRun) -> dict:
    stage = r.stage
    pct = r.progress if r.status == CrawlRun.Status.COMPLETED else min(99, STAGE_WEIGHT.get(stage, 0) + int(r.progress * 0.4))
    report = (r.usage or {}).get("city_report") or {}
    return {
        "city_report": {"cities": report.get("cities") or {}, "empty": report.get("empty") or [], "notes": report.get("notes") or {}},
        "id": r.pk, "mission_id": r.mission_id, "mission_name": r.mission.name if r.mission_id else "", "trigger": r.trigger, "status": r.status, "state_label": r.state_label,
        "paused": r.paused, "pause_requested": r.pause_requested, "cancel_requested": r.cancel_requested, "stage": stage, "stage_label": STAGE_LABELS.get(stage, stage),
        "progress": pct, "message": r.message, "error": r.error, "tasks": {"total": r.tasks_total, "done": r.tasks_done, "failed": r.tasks_failed, "waiting_node": r.tasks_waiting},
        "found": r.found_count, "unique": r.unique_count, "created": r.created_count, "merged": r.merged_count, "skipped": r.skipped_count,
        "pages": r.pages_fetched, "bytes": r.bytes_fetched, "cache_hits": r.cache_hits, "usage": (r.usage or {}).get("budget", {}), "out_of_area": int((r.usage or {}).get("out_of_area") or 0), "parked_until": (r.usage or {}).get("parked_until") or None,
        "queued_at": r.queued_at, "started_at": r.started_at, "finished_at": r.finished_at, "stalled": r.is_stalled, "attempts": r.attempts,
    }


def task_dict(t: CrawlTask) -> dict:
    return {"id": t.pk, "stage": t.stage, "source": t.source, "kind": t.kind, "label": t.label or t.key[:80], "status": t.status, "attempts": t.attempts, "error": t.error,
            "result": t.result, "not_before": t.not_before, "finished_at": t.finished_at, "waiting_job": bool(t.node_job_uid)}


def _node_status() -> dict:
    out = {"crawl": {"known": False, "online": False, "ready": False, "message": ""}, "instagram": {"known": False, "online": False, "ready": False, "message": ""}}
    try:
        from apps.compute import services as SV

        known, online = SV.known_nodes("crawl"), SV.online_nodes("crawl")
        ready = [n for n in online if (n.capabilities or {}).get("crawl_ready", True)]
        out["crawl"] = {"known": bool(known), "online": bool(online), "ready": bool(ready),
                        "message": "" if ready else ("سرورِ پردازش روشن است ولی ابزارِ خزنده هنوز نصب نشده؛ خودش نصب می‌کند." if online else
                                                     ("سرورِ پردازش الان خاموش است؛ کارها در صف می‌مانند." if known else "سرورِ پردازش هنوز به‌روز نشده (نسخهٔ ۲٫۱۰). با روشن‌شدن و به‌روزرسانیِ خودکار، این قابلیت فعال می‌شود."))}
    except Exception:  # noqa: BLE001
        logger.exception("finder: node status failed")
    try:
        from apps.igtrends import status as igstatus

        st = igstatus.node_status()
        out["instagram"] = {"known": st.get("problem") not in ("no_node", "node_old"), "online": st.get("problem") != "node_offline" and st.get("problem") not in ("no_node", "node_old"),
                            "ready": bool(st.get("ready")), "message": st.get("message") or ""}
    except Exception:  # noqa: BLE001
        logger.exception("finder: instagram status failed")
    return out


def _engines_state() -> dict:
    from apps.growth_engine.discovery.models import ProviderConfig

    row = ProviderConfig.objects.filter(provider="crawler_engines").first()
    state = dict((row.config if row else {}) or {})
    state["cooldown"] = search_source.cooldowns()  # the engines that are resting right now (until when, and why)
    state["brave_api"] = bool(search_source.brave_api_key())
    return state


# --------------------------------------------------------------------------- meta


class MetaView(FinderView):
    def get(self, request):
        from apps.stores.models import Store

        sets = GrowthSettings.load()
        return Response({
            "types": presets.listing(), "groups": presets.GROUPS, "presets": presets.preset_listing(),
            "sources": [{**src, "key_set": bool(neshan.api_key())} if src["key"] == "neshan" else src for src in SOURCE_INFO],
            "stages": [{"key": s["key"], "label": s["label"], "tone": s["tone"], "statuses": s["statuses"], "primary": s["primary"]} for s in pipeline.STAGES],
            "channels": [{"key": k, "label": v, "manual": k in draft_service.MANUAL} for k, v in draft_service.CHANNELS.items()],
            "budget_limits": {k: {"min": lo, "max": hi} for k, (lo, hi) in missions.BUDGET_LIMITS.items()}, "budget_defaults": presets._DEFAULT_BUDGET,
            "stores": list(Store.objects.filter(is_active=True).order_by("name").values("id", "name")[:80]), "products": products.public(),
            "node": _node_status(), "engines": _engines_state(),
            "outreach": {"sending_enabled": sets.sending_enabled, "emergency_stop": sets.emergency_stop, "daily_cap": sets.daily_cap, "cap_remaining": limits.cap_remaining(sets),
                         "identity_problems": sets.identity_problems(), "sms_room": draft_service.sms_budget(sets)},
            "individuals": {"tag": finalize.INDIVIDUAL_TAG, "note": "مربیِ مستقل یعنی خودِ فرد کسب‌وکار است: نام و راهِ تماسِ کاری‌اش را خودش در فهرستِ عمومی گذاشته. این لیدها برچسبِ «" + finalize.INDIVIDUAL_TAG + "» دارند، "
                            "نامشان در گزارشِ اجرا نمی‌آید، و پیش از هر پیام فهرستِ «تماس نگیر» و لغوِ پیامک سنجیده می‌شود."},
            "attribution": "© OpenStreetMap contributors (ODbL)",
        })


class NeshanKeyView(FinderView):
    """The owner's Neshan API key (the one source that needs a key). Stored in the provider settings; the key itself is never returned or logged."""

    def get(self, request):
        return Response({"set": bool(neshan.api_key())})

    def put(self, request):
        from apps.growth_engine.discovery.models import ProviderConfig

        key = str(request.data.get("api_key") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._\-]{16,160}", key):
            return _bad("invalid_key", "کلید معتبر نیست (فقط حرف و عددِ انگلیسی، دست‌کم ۱۶ نویسه، بدونِ فاصله).")
        row, _ = ProviderConfig.objects.get_or_create(provider=neshan.PROVIDER_KEY)
        row.enabled, row.secrets, row.updated_by = True, {"api_key": key}, request.user
        row.save()
        audit.log(AuditKind.SETTINGS, request.user, "کلیدِ API نشان ثبت شد", {"provider": neshan.PROVIDER_KEY, "fields": ["secrets.api_key"]})
        return Response({"set": True})

    def delete(self, request):
        from apps.growth_engine.discovery.models import ProviderConfig

        ProviderConfig.objects.filter(provider=neshan.PROVIDER_KEY).update(secrets={}, enabled=False)
        audit.log(AuditKind.SETTINGS, request.user, "کلیدِ API نشان برداشته شد", {"provider": neshan.PROVIDER_KEY, "fields": ["secrets.api_key"]})
        return Response({"set": False})


class EnginesProbeView(FinderView):
    """POST: ask each search engine one small question and remember the answer (3 requests)."""

    throttle_classes = [GrowthBulkThrottle]

    def post(self, request):
        from apps.growth_engine.discovery.models import ProviderConfig

        fetcher = fetch.make_fetcher(read_timeout=20.0, domain_delay=2.0)
        web = fetch.WebClient(fetcher, fetch.Budget(max_requests=10, max_seconds=90), use_cache=False)
        try:
            state = search_source.probe(web)
        finally:
            web.close()
        search_source.save_probe(state)
        return Response(_engines_state())


# --------------------------------------------------------------------------- missions


class MissionListView(FinderView):
    def get(self, request):
        qs = CrawlMission.objects.select_related("store").filter(is_archived=request.query_params.get("archived") == "1")
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([mission_dict(m) for m in page])

    def post(self, request):
        try:
            mission = missions.create_mission(request.data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(mission_dict(mission), status=status.HTTP_201_CREATED)


class MissionFromPresetView(FinderView):
    def post(self, request):
        try:
            mission = missions.create_from_preset(str(request.data.get("preset") or ""), request.user, request.data.get("overrides") if isinstance(request.data.get("overrides"), dict) else None)
            run = missions.start_run(mission, request.user, trigger=CrawlRun.Trigger.PRESET) if request.data.get("start") else None
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response({"mission": mission_dict(mission), "run": run_dict(run) if run else None}, status=status.HTTP_201_CREATED)


class MissionDetailView(FinderView):
    def get(self, request, pk):
        return Response(mission_dict(get_object_or_404(CrawlMission.objects.select_related("store"), pk=pk)))

    def patch(self, request, pk):
        mission = get_object_or_404(CrawlMission, pk=pk)
        try:
            mission = missions.update_mission(mission, request.data)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(mission_dict(mission))

    def delete(self, request, pk):
        mission = get_object_or_404(CrawlMission, pk=pk)
        if missions.active_run(mission):
            return _bad("running", "این مأموریت اجرای فعال دارد؛ اول آن را لغو کنید.", status.HTTP_409_CONFLICT)
        missions.update_mission(mission, {"is_archived": True, "enabled": False})
        return Response(status=status.HTTP_204_NO_CONTENT)


class MissionRunView(FinderView):
    def post(self, request, pk):
        mission = get_object_or_404(CrawlMission, pk=pk)
        try:
            run = missions.start_run(mission, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(run_dict(run), status=status.HTTP_201_CREATED)


# --------------------------------------------------------------------------- runs


class RunListView(FinderView):
    def get(self, request):
        qs = CrawlRun.objects.select_related("mission")
        if request.query_params.get("mission", "").isdigit():
            qs = qs.filter(mission_id=int(request.query_params["mission"]))
        if request.query_params.get("active") == "1":
            qs = qs.filter(status__in=[CrawlRun.Status.QUEUED, CrawlRun.Status.RUNNING])
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([run_dict(r) for r in page])


class RunDetailView(FinderView):
    def get(self, request, pk):
        run = get_object_or_404(CrawlRun.objects.select_related("mission"), pk=pk)
        by_source: dict[str, dict[str, int]] = {}
        for source, st, n in CrawlTask.objects.filter(run=run).values_list("source", "status").annotate(n=Count("id")):
            by_source.setdefault(source, {})[st] = n
        sample = [(finalize.log_name(c), c.city, c.state) for c in CrawlCandidate.objects.filter(run=run).order_by("-id")[:8].only("name", "city", "state", "signals")]  # an independent person is never named here
        logs = list(CrawlLog.objects.filter(run=run).order_by("-id")[:40].values("id", "level", "message", "created_at"))[::-1]
        return Response({**run_dict(run), "by_source": by_source, "sample": [{"name": n, "city": c, "state": s} for n, c, s in sample], "logs": logs,
                        "spec": run.spec, "mission": {"id": run.mission_id, "name": run.mission.name}})


class RunLogsView(FinderView):
    def get(self, request, pk):
        run = get_object_or_404(CrawlRun, pk=pk)
        after = int(request.query_params["after"]) if request.query_params.get("after", "").isdigit() else 0
        rows = list(CrawlLog.objects.filter(run=run, id__gt=after).order_by("id")[:200].values("id", "level", "message", "created_at"))
        return Response({"logs": rows, "status": run.status, "stage": run.stage})


class RunTasksView(FinderView):
    def get(self, request, pk):
        run = get_object_or_404(CrawlRun, pk=pk)
        qs = CrawlTask.objects.filter(run=run)
        for param in ("status", "source", "stage"):
            if request.query_params.get(param):
                qs = qs.filter(**{param: request.query_params[param]})
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(qs.order_by("priority", "id"), request, view=self)
        return paginator.get_paginated_response([task_dict(t) for t in page])


class RunActionView(FinderView):
    """POST runs/<id>/<action>/ where action is pause | resume | cancel | sync-node."""

    def post(self, request, pk, action):
        run = get_object_or_404(CrawlRun.objects.select_related("mission"), pk=pk)
        try:
            if action == "pause":
                run = missions.pause_run(run)
            elif action == "resume":
                run = missions.resume_run(run)
            elif action == "cancel":
                run = missions.cancel_run(run)
            elif action == "sync-node":
                return Response({"result": runner.sync_node(run), "run": run_dict(CrawlRun.objects.select_related("mission").get(pk=run.pk))})
            else:
                return _bad("unknown_action", "کارِ ناشناخته.", status.HTTP_404_NOT_FOUND)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(run_dict(run))


# --------------------------------------------------------------------------- results


class ResultListView(FinderView):
    def get(self, request):
        qs = results.order(results.filter_findings(results.base_queryset(request.query_params), request.query_params), request.query_params.get("ordering"))
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(results.with_prefetch(qs), request, view=self)
        return paginator.get_paginated_response([results.result_dict(f) for f in page])


class ResultMapView(FinderView):
    def get(self, request):
        qs = results.filter_findings(results.base_queryset(request.query_params), request.query_params)
        return Response(results.map_points(qs.order_by("-score")))


class ResultExportView(FinderView):
    throttle_classes = [GrowthExportThrottle]

    def get(self, request):
        qs = results.order(results.filter_findings(results.base_queryset(request.query_params), request.query_params), request.query_params.get("ordering"))
        response = StreamingHttpResponse(results.stream_csv(qs), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="moshtari-yab-{date.today().isoformat()}.csv"'
        return response


class ResultSummaryView(FinderView):
    """Counts for the header of the results page: per level, per stage, per source."""

    def get(self, request):
        qs = results.filter_findings(results.base_queryset(request.query_params), request.query_params)
        by_level = dict(qs.values_list("level").annotate(n=Count("id")))
        by_status = dict(qs.values_list("lead__status").annotate(n=Count("id")))
        by_stage = {s["key"]: sum(by_status.get(x, 0) for x in s["statuses"]) for s in pipeline.STAGES}
        return Response({"total": qs.count(), "by_level": by_level, "by_stage": by_stage,
                         "cities": list(qs.exclude(lead__city="").values_list("lead__city").annotate(n=Count("id")).order_by("-n")[:12])})


# --------------------------------------------------------------------------- pipeline


class PipelineView(FinderView):
    def get(self, request):
        mission = request.query_params.get("mission")
        return Response(pipeline.board(
            mission_id=int(mission) if mission and mission.isdigit() else None, q=request.query_params.get("q", ""), scope=request.query_params.get("scope", "finder"),
            per_stage=min(100, int(request.query_params.get("per_stage") or 40)), min_score=int(request.query_params.get("min_score") or 0) if str(request.query_params.get("min_score") or "0").isdigit() else 0,
        ))


class LeadStageView(FinderView):
    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        try:
            lead = pipeline.move(lead, str(request.data.get("stage") or ""), request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response({"id": lead.pk, "status": lead.status, "status_label": lead.get_status_display(), "stage": pipeline.stage_of(lead.status)})


class ReminderListView(FinderView):
    def get(self, request):
        lead_id = request.query_params.get("lead")
        return Response(pipeline.reminders(when=request.query_params.get("when", "open"), lead_id=int(lead_id) if lead_id and lead_id.isdigit() else None))


class LeadReminderCreateView(FinderView):
    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        try:
            reminder = pipeline.add_reminder(lead, request.data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(pipeline.reminder_dict(reminder), status=status.HTTP_201_CREATED)


class ReminderDetailView(FinderView):
    def patch(self, request, pk):
        reminder = get_object_or_404(LeadReminder.objects.select_related("lead"), pk=pk)
        try:
            reminder = pipeline.update_reminder(reminder, request.data, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(pipeline.reminder_dict(reminder))

    def delete(self, request, pk):
        get_object_or_404(LeadReminder, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- drafts


class DraftGenerateView(FinderView):
    throttle_classes = [GrowthBulkThrottle]

    def post(self, request, pk):
        mission = get_object_or_404(CrawlMission.objects.select_related("store"), pk=pk)
        lead_ids = request.data.get("lead_ids") or []
        if request.data.get("top"):  # «بهترین N لید»
            try:
                top = max(1, min(200, int(request.data["top"])))
            except (TypeError, ValueError):
                return _bad("invalid", "تعداد باید عدد باشد.")
            lead_ids = list(CrawlFinding.objects.filter(mission=mission, lead__is_archived=False, score__gte=int(request.data.get("min_score") or 0)).order_by("-score")[:top].values_list("lead_id", flat=True))
        try:
            out = draft_service.generate(mission, [int(i) for i in lead_ids], list(request.data.get("channels") or []), request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(out, status=status.HTTP_201_CREATED)


class DraftListView(FinderView):
    def get(self, request):
        qs = OutreachDraft.objects.select_related("lead", "item", "mission")
        for param, field in (("mission", "mission_id"), ("lead", "lead_id")):
            if request.query_params.get(param, "").isdigit():
                qs = qs.filter(**{field: int(request.query_params[param])})
        for param in ("status", "channel"):
            if request.query_params.get(param):
                qs = qs.filter(**{param: request.query_params[param]})
        counts = dict(qs.values_list("status").annotate(n=Count("id")))
        paginator = GrowthPagination()
        page = paginator.paginate_queryset(qs.order_by("-updated_at"), request, view=self)
        resp = paginator.get_paginated_response([draft_service.draft_dict(d) for d in page])
        resp.data["counts"] = counts
        return resp


class DraftDetailView(FinderView):
    def patch(self, request, pk):
        draft = get_object_or_404(OutreachDraft.objects.select_related("lead", "mission", "item"), pk=pk)
        try:
            draft = draft_service.edit(draft, body=request.data.get("body"), subject=request.data.get("subject"))
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(draft_service.draft_dict(draft))


class DraftActionView(FinderView):
    """POST drafts/<id>/<action>/ - approve | reject | queue | sent (manual channels)."""

    def post(self, request, pk, action):
        draft = get_object_or_404(OutreachDraft.objects.select_related("lead", "mission", "item"), pk=pk)
        fn = {"approve": draft_service.approve, "reject": draft_service.reject, "queue": draft_service.queue, "sent": draft_service.mark_sent_manually}.get(action)
        if fn is None:
            return _bad("unknown_action", "کارِ ناشناخته.", status.HTTP_404_NOT_FOUND)
        try:
            draft = fn(draft, request.user)
        except ValidationFailed as exc:
            return validation_response(exc)
        return Response(draft_service.draft_dict(draft))


class DraftBulkView(FinderView):
    throttle_classes = [GrowthBulkThrottle]

    def post(self, request):
        ids = [int(i) for i in (request.data.get("ids") or []) if str(i).isdigit()][:200]
        action = str(request.data.get("action") or "")
        fn = {"approve": draft_service.approve, "reject": draft_service.reject, "queue": draft_service.queue}.get(action)
        if fn is None or not ids:
            return _bad("invalid", "کار یا فهرستِ پیش‌نویس‌ها معتبر نیست.")
        done, failed = 0, []
        for draft in OutreachDraft.objects.select_related("lead", "mission", "item").filter(pk__in=ids):
            try:
                fn(draft, request.user)
                done += 1
            except ValidationFailed as exc:
                failed.append({"id": draft.pk, "text": exc.errors[0]["message"] if exc.errors else "ناموفق"})
        return Response({"done": done, "failed": failed})


class NodeStatusView(FinderView):
    def get(self, request):
        return Response(_node_status())
