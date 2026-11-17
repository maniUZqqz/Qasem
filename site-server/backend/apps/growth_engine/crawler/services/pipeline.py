"""The sales pipeline of the finder: six stages over the Growth Engine's lead statuses, follow-up reminders, the activity trail.

The Growth Engine already has twelve fine-grained lead statuses. The owner's board has six stages; each stage is a GROUP of those
statuses, and moving a card writes the stage's main status through the normal lead editor (so the history shows «وضعیت عوض شد»).
No second status field exists: the board and the lead page can never disagree.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.utils import timezone

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ActivityKind, LeadStatus
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services import editing, history
from apps.growth_engine.leads.services.editing import ValidationFailed

from ..models import CrawlFinding, LeadReminder

STAGES = [
    {"key": "new", "label": "تازه", "statuses": ["new"], "primary": "new", "tone": "neutral"},
    {"key": "researched", "label": "بررسی‌شده", "statuses": ["researched", "qualified", "ready_for_outreach"], "primary": "researched", "tone": "info"},
    {"key": "contacted", "label": "تماس گرفته‌شد", "statuses": ["contacted", "replied"], "primary": "contacted", "tone": "brand"},
    {"key": "interested", "label": "علاقه‌مند", "statuses": ["interested", "demo_scheduled", "negotiation"], "primary": "interested", "tone": "ok"},
    {"key": "customer", "label": "مشتری", "statuses": ["won"], "primary": "won", "tone": "ok"},
    {"key": "rejected", "label": "رد", "statuses": ["lost", "not_interested"], "primary": "not_interested", "tone": "bad"},
]
_BY_KEY = {s["key"]: s for s in STAGES}
_STAGE_OF_STATUS = {status: s["key"] for s in STAGES for status in s["statuses"]}


def stage_of(status: str) -> str:
    return _STAGE_OF_STATUS.get(status, "new")


def stage_label(key: str) -> str:
    return _BY_KEY[key]["label"] if key in _BY_KEY else key


def move(lead: Lead, stage_key: str, actor=None) -> Lead:
    """Move a lead to a stage. Moving to the stage it is already in changes nothing (a finer status like «پاسخ داده» is kept)."""
    stage = _BY_KEY.get(stage_key)
    if stage is None:
        raise ValidationFailed([{"field": "stage", "code": "unknown", "message": "مرحلهٔ معتبر نیست."}])
    if lead.status in stage["statuses"]:
        return lead
    editing.update_lead(lead, {"status": stage["primary"]}, actor)
    lead.refresh_from_db()
    return lead


# --------------------------------------------------------------------------- the board


def _best_score_subquery(mission_id=None):
    qs = CrawlFinding.objects.filter(lead=OuterRef("pk"))
    if mission_id:
        qs = qs.filter(mission_id=mission_id)
    return Subquery(qs.order_by("-score").values("score")[:1])


def board(*, mission_id=None, q: str = "", per_stage: int = 40, scope: str = "finder", min_score: int = 0) -> dict:
    """``{"stages": [{key, label, tone, count, cards: [...]}], "total"}``. ``scope='all'`` shows every Growth Engine lead, not only crawled ones."""
    leads = Lead.objects.filter(is_archived=False)
    if scope != "all" or mission_id:
        leads = leads.filter(crawl_findings__mission_id=mission_id) if mission_id else leads.filter(crawl_findings__isnull=False)
    leads = leads.distinct()
    if q:
        key = nz.search_key(q)
        leads = leads.filter(Q(name_key__contains=key) | Q(city__icontains=q) | Q(category__icontains=q))
    leads = leads.annotate(best_score=_best_score_subquery(mission_id))
    if min_score:
        leads = leads.filter(best_score__gte=min_score)
    now = timezone.now()
    next_due = LeadReminder.objects.filter(lead=OuterRef("pk"), done_at__isnull=True).order_by("due_at").values("due_at")[:1]
    leads = leads.annotate(next_due=Subquery(next_due))
    out = []
    for stage in STAGES:
        qs = leads.filter(status__in=stage["statuses"])
        cards = [card(lead, now) for lead in qs.order_by("-best_score", "-updated_at").prefetch_related("contacts", "tags")[:per_stage]]
        out.append({"key": stage["key"], "label": stage["label"], "tone": stage["tone"], "count": qs.count(), "cards": cards})
    return {"stages": out, "total": sum(s["count"] for s in out)}


def card(lead: Lead, now=None) -> dict:
    now = now or timezone.now()
    phones = [c.value for c in lead.contacts.all() if c.kind == "phone"]
    due = getattr(lead, "next_due", None)
    return {
        "id": lead.pk, "name": lead.display_name, "city": lead.city, "category": lead.category, "status": lead.status, "status_label": lead.get_status_display(),
        "score": getattr(lead, "best_score", None), "phone": nz.format_phone_display(phones[0]) if phones else "", "phone_raw": phones[0] if phones else "", "website": lead.website, "instagram": lead.instagram_url,
        "tags": [t.name for t in lead.tags.all()][:4], "next_due": due, "overdue": bool(due and due < now),
    }


# --------------------------------------------------------------------------- reminders


def parse_due(data: dict) -> datetime:
    """``due_at`` (ISO text, or just a date) or ``in_days`` (number). Always a timezone-aware time; defaults to tomorrow 10:00 (Tehran)."""
    raw = data.get("due_at")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationFailed([{"field": "due_at", "code": "invalid", "message": "تاریخِ پیگیری معتبر نیست."}]) from exc
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            if len(str(raw)) <= 10:  # a bare date: 10:00 in the morning
                parsed = parsed.replace(hour=10)
        return parsed
    try:
        days = int(data.get("in_days") if data.get("in_days") is not None else 1)
    except (TypeError, ValueError) as exc:
        raise ValidationFailed([{"field": "in_days", "code": "invalid", "message": "تعدادِ روز باید عدد باشد."}]) from exc
    if not 0 <= days <= 730:
        raise ValidationFailed([{"field": "in_days", "code": "out_of_range", "message": "تعدادِ روز باید بین ۰ و ۷۳۰ باشد."}])
    return (timezone.localtime(timezone.now()) + timedelta(days=days)).replace(hour=10, minute=0, second=0, microsecond=0)


def add_reminder(lead: Lead, data: dict, actor=None) -> LeadReminder:
    due = parse_due(data)
    note = nz.normalize_text(str(data.get("note") or ""))[:300]
    reminder = LeadReminder.objects.create(lead=lead, due_at=due, note=note, created_by=actor if getattr(actor, "is_authenticated", False) else None)
    history.log_activity(lead, ActivityKind.UPDATED, actor=actor, summary="یادآوریِ پیگیری ثبت شد: " + (note or "بدونِ یادداشت"),
                         data={"reminder": reminder.pk, "due_at": due.isoformat()})
    return reminder


def update_reminder(reminder: LeadReminder, data: dict, actor=None) -> LeadReminder:
    if "done" in data:
        done = bool(data["done"])
        reminder.done_at = timezone.now() if done else None
        history.log_activity(reminder.lead, ActivityKind.UPDATED, actor=actor, summary="پیگیری انجام شد" if done else "پیگیری دوباره باز شد", data={"reminder": reminder.pk})
    if "note" in data:
        reminder.note = nz.normalize_text(str(data["note"]))[:300]
    if "due_at" in data or "in_days" in data:
        reminder.due_at = parse_due(data)
        history.log_activity(reminder.lead, ActivityKind.UPDATED, actor=actor, summary="موعدِ پیگیری عوض شد", data={"reminder": reminder.pk, "due_at": reminder.due_at.isoformat()})
    reminder.save()
    return reminder


def reminder_dict(r: LeadReminder, now=None) -> dict:
    now = now or timezone.now()
    return {
        "id": r.pk, "lead_id": r.lead_id, "lead_name": r.lead.display_name, "city": r.lead.city, "status": r.lead.status, "status_label": r.lead.get_status_display(),
        "due_at": r.due_at, "note": r.note, "done_at": r.done_at, "overdue": r.done_at is None and r.due_at < now,
    }


def reminders(*, when: str = "open", lead_id=None, limit: int = 200) -> dict:
    """``when``: open (all not done) | overdue | today | week | done."""
    now = timezone.now()
    qs = LeadReminder.objects.select_related("lead")
    if lead_id:
        qs = qs.filter(lead_id=lead_id)
    end_today = timezone.localtime(now).replace(hour=23, minute=59, second=59, microsecond=0)
    base_open = qs.filter(done_at__isnull=True)
    counts = {"overdue": base_open.filter(due_at__lt=now).count(), "today": base_open.filter(due_at__gte=now, due_at__lte=end_today).count(),
              "week": base_open.filter(due_at__gte=now, due_at__lte=end_today + timedelta(days=7)).count(), "open": base_open.count()}
    if when == "overdue":
        qs = base_open.filter(due_at__lt=now)
    elif when == "today":
        qs = base_open.filter(due_at__lte=end_today)
    elif when == "week":
        qs = base_open.filter(due_at__lte=end_today + timedelta(days=7))
    elif when == "done":
        qs = qs.filter(done_at__isnull=False).order_by("-done_at")
    else:
        qs = base_open
    if when != "done":
        qs = qs.order_by("due_at")
    return {"counts": counts, "items": [reminder_dict(r, now) for r in qs[:limit]]}
