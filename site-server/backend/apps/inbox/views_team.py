"""Team, presence, settings and the numbers a team lead reads."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.customers.models import Conversation
from apps.stores import access

from . import bot, dispatch, hours, surveys, team
from .models import AgentProfile, ConversationMeta, InboxSettings
from .views_conversations import OPEN_STATES, fail

CHANNEL_KEYS = ["TELEGRAM", "BALE", "EITAA", "RUBIKA", "WEBCHAT", "SMS", "INSTAGRAM", "WHATSAPP", "WEB", "API"]

SETTINGS_FIELDS = {
    "assignment_mode": ("choice", [c for c, _ in InboxSettings.Assignment.choices]),
    "assign_when": ("choice", [c for c, _ in InboxSettings.AssignWhen.choices]),
    "assign_only_online": ("bool", None),
    "sla_first_response_min": ("int", (1, 7 * 24 * 60)),
    "sla_warn_percent": ("int", (10, 99)),
    "sla_pause_off_hours": ("bool", None),
    "working_hours": ("hours", None),
    "bot_enabled": ("bool", None),
    "bot_min_confidence": ("float", (0.0, 1.0)),
    "bot_handoff_keywords": ("strlist", None),
    "bot_offhours": ("choice", [c for c, _ in InboxSettings.OffHours.choices]),
    "offhours_message": ("text", 600),
    "greeting_message": ("text", 600),
    "survey_enabled": ("bool", None),
    "survey_text": ("text", 600),
    "survey_delay_min": ("int", (0, 7 * 24 * 60)),
    "payment_reminder_enabled": ("bool", None),
    "payment_reminder_hours": ("int", (1, 24 * 14)),
    "payment_reminder_max": ("int", (1, 5)),
    "payment_reminder_text": ("text", 600),
    "rate_limits": ("rates", None),
    "merge_by_username": ("bool", None),
    "widget": ("widget", None),
}


def settings_json(cfg: InboxSettings) -> dict:
    data = {name: getattr(cfg, name) for name in SETTINGS_FIELDS}
    data["bot_handoff_keywords_effective"] = bot.keywords_of(cfg)
    data["bot_offhours_default_message"] = bot.DEFAULT_OFFHOURS
    data["default_working_hours"] = hours.DEFAULT_HOURS
    data["open_now"] = hours.is_open(cfg.working_hours)
    return data


def _clean(kind, rule, value):
    if kind == "bool":
        return bool(value)
    if kind == "int":
        number = int(value)
        lo, hi = rule
        if not lo <= number <= hi:
            raise ValueError(f"مقدار باید بین {lo} و {hi} باشد.")
        return number
    if kind == "float":
        number = float(value)
        lo, hi = rule
        if not lo <= number <= hi:
            raise ValueError(f"مقدار باید بین {lo} و {hi} باشد.")
        return number
    if kind == "choice":
        if value not in rule:
            raise ValueError("گزینهٔ نامعتبر.")
        return value
    if kind == "text":
        return str(value or "").strip()[:rule]
    if kind == "strlist":
        return [str(v).strip()[:40] for v in (value or []) if str(v).strip()][:30]
    if kind == "hours":
        if not value:
            return {}
        days = [int(d) for d in value.get("days", []) if 0 <= int(d) <= 6]
        start, end = str(value.get("start", "09:00")), str(value.get("end", "18:00"))
        for part in (start, end):
            h, m = part.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError("ساعت نامعتبر است.")
        if end <= start:
            raise ValueError("ساعت پایان باید بعد از شروع باشد.")
        return {"days": sorted(set(days)), "start": start, "end": end}
    if kind == "rates":
        out = {}
        for key, number in (value or {}).items():
            if key.upper() in CHANNEL_KEYS:
                out[key.upper()] = max(0, min(120, int(number)))
        return out
    if kind == "widget":
        allowed = {"title", "subtitle", "welcome", "color", "position", "auto_open", "offline_subtitle"}
        out = {k: v for k, v in (value or {}).items() if k in allowed}
        color = str(out.get("color", "#2563eb"))
        if not (color.startswith("#") and len(color) in (4, 7) and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
            out["color"] = "#2563eb"
        out["position"] = "right" if out.get("position") == "right" else "left"
        out["auto_open"] = bool(out.get("auto_open"))
        for k in ("title", "subtitle", "welcome", "offline_subtitle"):
            if k in out:
                out[k] = str(out[k])[:200]
        return out
    return value


class SettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS, write=False)
        return Response(settings_json(team.settings_for(store)))

    def patch(self, request, store_id):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        cfg = team.settings_for(store)
        changed = []
        for name, value in request.data.items():
            if name not in SETTINGS_FIELDS:
                continue
            kind, rule = SETTINGS_FIELDS[name]
            try:
                setattr(cfg, name, _clean(kind, rule, value))
            except (TypeError, ValueError, AttributeError) as exc:
                return fail("bad_value", f"«{name}»: {exc}" if str(exc) else f"مقدار «{name}» نامعتبر است.")
            changed.append(name)
        if changed:
            cfg.save()
        return Response(settings_json(cfg))


class PresenceView(APIView):
    """The panel pings this while the inbox is open; the status is the person's own choice."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS)
        wanted = request.data.get("status")
        if wanted in AgentProfile.Status.values:
            profile = team.set_status(store, request.user, wanted, str(request.data.get("note", "")))
        else:
            profile = team.heartbeat(store, request.user)
        return Response({"status": profile.effective_status, "note": profile.status_note})


class TeamView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS, write=False)
        days = max(1, min(int(request.query_params.get("days", 30) or 30), 365))
        return Response({
            "members": team.performance(store, days=days),
            "days": days,
            "unassigned_open": Conversation.objects.filter(
                store=store, assigned_to__isnull=True,
                state__in=[Conversation.State.HUMAN, Conversation.State.ESCALATED],
            ).count(),
        })


class TeamMemberView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, username):
        store = access.get_store(request.user, store_id, access.SETTINGS)
        user = get_object_or_404(User, username=username)
        if not access.can(user, store, access.CONVERSATIONS, write=True):
            return fail("not_a_member", "این شخص عضو تیم پاسخ‌گویی نیست.")
        profile = team.profile_for(store, user)
        data = request.data
        if "accepts_chats" in data:
            profile.accepts_chats = bool(data["accepts_chats"])
        if "channels" in data:
            profile.channels = [c.upper() for c in (data["channels"] or []) if c.upper() in CHANNEL_KEYS]
        if "skills" in data:
            profile.skills = [str(s).strip()[:30] for s in (data["skills"] or []) if str(s).strip()][:20]
        if "max_open" in data:
            try:
                profile.max_open = max(1, min(200, int(data["max_open"])))
            except (TypeError, ValueError):
                return fail("bad_value", "سقف گفتگوی هم‌زمان باید عدد باشد.")
        if "display_name" in data:
            profile.display_name = str(data["display_name"])[:80]
        profile.save()
        return Response({"ok": True})


class StatsView(APIView):
    """The one-screen summary: queue, SLA, response times, survey, channels."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONVERSATIONS, write=False)
        days = max(1, min(int(request.query_params.get("days", 30) or 30), 365))
        since = timezone.now() - timedelta(days=days)
        real = Conversation.objects.filter(store=store).exclude(
            Q(inbox_meta__is_test=True) | Q(customer__channel="web-test"))
        metas = ConversationMeta.objects.filter(store=store, is_test=False)
        firsts = metas.filter(first_human_reply_at__gte=since, first_response_seconds__isnull=False)
        avg = firsts.aggregate(a=Avg("first_response_seconds"))["a"]
        per_channel = {}
        for channel, state in real.values_list("channel", "state"):
            row = per_channel.setdefault(channel, {"open": 0, "closed": 0})
            row["closed" if state == Conversation.State.RESOLVED else "open"] += 1
        return Response({
            "days": days,
            "open": real.filter(state__in=OPEN_STATES).count(),
            "waiting_for_person": real.filter(
                state__in=[Conversation.State.HUMAN, Conversation.State.ESCALATED]).count(),
            "unassigned": real.filter(
                state__in=[Conversation.State.HUMAN, Conversation.State.ESCALATED],
                assigned_to__isnull=True).count(),
            "resolved": real.filter(state=Conversation.State.RESOLVED, updated_at__gte=since).count(),
            "sla_breaches": metas.filter(sla_breached_at__gte=since).count(),
            "avg_first_response_seconds": int(avg) if avg is not None else None,
            "bot_handoffs": metas.exclude(handoff_reason="").filter(conversation__updated_at__gte=since).count(),
            "per_channel": per_channel,
            "survey": surveys.summary(store, days=days),
            "channels": [
                {"kind": c.kind, "enabled": c.enabled, "ready": dispatch.is_ready(c),
                 "health_ok": c.health_ok, "last_inbound_at": c.last_inbound_at}
                for c in store.inbox_channels.all()
            ],
        })
