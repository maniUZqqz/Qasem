"""Bulk actions on selected leads: a handful of queries, whatever the selection size."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.growth_engine.core import conf
from apps.growth_engine.core import normalization as nz

from ..choices import ActivityKind, LeadStatus
from ..models import Lead, LeadActivity, LeadTag
from . import history
from .editing import ValidationFailed
from .tags import resolve_tags

ACTIONS = ("set_status", "add_tag", "remove_tag", "archive", "unarchive", "delete")


def bulk_action(ids: list[int], action: str, payload: dict | None = None, actor=None) -> dict:
    """Run ``action`` on the leads in ``ids``. Returns ``{"affected": n, "skipped": n}``."""
    payload = payload or {}
    actor = actor if actor is not None and getattr(actor, "is_authenticated", False) else None
    if action not in ACTIONS:
        raise ValidationFailed([{"field": "action", "code": "invalid_action", "message": "عملیات ناشناخته است."}])
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not ids:
        raise ValidationFailed([{"field": "ids", "code": "empty", "message": "هیچ لیدی انتخاب نشده است."}])
    if len(ids) > conf.get("BULK_MAX_IDS"):
        raise ValidationFailed([{"field": "ids", "code": "too_many", "message": f"حداکثر {conf.get('BULK_MAX_IDS')} لید را می‌شود یک‌جا انتخاب کرد."}])
    leads = list(Lead.objects.filter(pk__in=ids))
    found = len(leads)
    with transaction.atomic():
        if action == "set_status":
            status = payload.get("status")
            if status not in LeadStatus.values:
                raise ValidationFailed([{"field": "status", "code": "invalid_status", "message": "وضعیت معتبر نیست."}])
            changing = [lead for lead in leads if lead.status != status]
            Lead.objects.filter(pk__in=[lead.pk for lead in changing]).update(status=status, updated_at=timezone.now())
            LeadActivity.objects.bulk_create(
                LeadActivity(
                    lead=lead, kind=ActivityKind.STATUS_CHANGED, actor=actor,
                    summary=f"{LeadStatus(lead.status).label} ← {LeadStatus(status).label}",
                    data={"old": lead.status, "new": status, "bulk": True},
                )
                for lead in changing
            )
            affected = len(changing)
        elif action in ("add_tag", "remove_tag"):
            name = (payload.get("tag") or "").strip()
            if not name:
                raise ValidationFailed([{"field": "tag", "code": "empty", "message": "نامِ برچسب را بنویسید."}])
            if action == "add_tag":
                tag = resolve_tags([name])[0]
                have = set(Lead.tags.through.objects.filter(leadtag_id=tag.pk, lead_id__in=[lead.pk for lead in leads]).values_list("lead_id", flat=True))
                missing = [lead for lead in leads if lead.pk not in have]
                Lead.tags.through.objects.bulk_create(
                    [Lead.tags.through(lead_id=lead.pk, leadtag_id=tag.pk) for lead in missing], ignore_conflicts=True
                )
                history.log_activities(missing, ActivityKind.TAG_ADDED, actor=actor, summary=tag.name, data={"tags": [tag.name], "bulk": True})
                affected = len(missing)
            else:
                tag = LeadTag.objects.filter(name_key=nz.search_key(name)[:60]).first()
                if not tag:
                    affected = 0
                else:
                    have_ids = set(Lead.tags.through.objects.filter(leadtag_id=tag.pk, lead_id__in=[lead.pk for lead in leads]).values_list("lead_id", flat=True))
                    holders = [lead for lead in leads if lead.pk in have_ids]
                    Lead.tags.through.objects.filter(leadtag_id=tag.pk, lead_id__in=list(have_ids)).delete()
                    history.log_activities(holders, ActivityKind.TAG_REMOVED, actor=actor, summary=tag.name, data={"tags": [tag.name], "bulk": True})
                    affected = len(holders)
        elif action in ("archive", "unarchive"):
            target = action == "archive"
            changing = [lead for lead in leads if lead.is_archived != target]
            Lead.objects.filter(pk__in=[lead.pk for lead in changing]).update(is_archived=target, updated_at=timezone.now())
            history.log_activities(changing, ActivityKind.ARCHIVED if target else ActivityKind.UNARCHIVED, actor=actor, data={"bulk": True})
            affected = len(changing)
        else:  # delete
            if payload.get("confirm") is not True:
                raise ValidationFailed([{"field": "confirm", "code": "confirm_required", "message": "حذف باید تأیید شود."}])
            Lead.objects.filter(pk__in=[lead.pk for lead in leads]).delete()
            affected = found
    return {"affected": affected, "skipped": len(ids) - affected, "missing": len(ids) - found}
