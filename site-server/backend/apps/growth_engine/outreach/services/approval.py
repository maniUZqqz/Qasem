"""Human approval of items: the exact message + target + form, bound to a fingerprint, recorded immutably."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.growth_engine.compliance.models import AuditKind, GrowthSettings
from apps.growth_engine.compliance.services import audit

from ..models import ApprovalRecord, Campaign, ItemStatus, OutreachItem
from . import fingerprint, guard
from .form_analysis import FormPlan


def approve_items(campaign: Campaign, *, item_ids: list[int] | None = None, all_ready: bool = False, actor=None) -> dict:
    """Approve the given items (or every ``ready`` one). Each is re-checked by the guard; nothing the guard refuses is approved.

    Returns ``{"approved": n, "refused": [{"item_id", "code", "text"}]}``."""
    queryset = campaign.items.select_related("lead", "campaign", "campaign__template")
    if all_ready:
        queryset = queryset.filter(status=ItemStatus.READY)
    else:
        queryset = queryset.filter(pk__in=list(item_ids or []))
    items = list(queryset.order_by("id"))
    found = {item.pk for item in items}
    refused = [
        {"item_id": i, "code": "not_found", "text": "این مورد در این کمپین نیست."}
        for i in dict.fromkeys(item_ids or []) if not all_ready and i not in found
    ]
    settings_obj = GrowthSettings.load()
    approved: list[int] = []
    for item in items:
        result = guard.check_item(item, phase=guard.APPROVE, settings_obj=settings_obj)
        if not result.ok:
            refused.append({"item_id": item.pk, "code": result.code, "text": result.text})
            continue
        try:
            with transaction.atomic():
                _approve_one(item, actor)
        except _Raced:
            refused.append({"item_id": item.pk, "code": guard.NOT_READY, "text": guard.TEXTS[guard.NOT_READY]})
            continue
        approved.append(item.pk)
    if approved:
        audit.log(AuditKind.APPROVAL, actor, f"{len(approved)} مورد تأیید شد (کمپین «{campaign.name}»)", {"campaign_id": campaign.pk, "item_ids": approved})
    return {"approved": len(approved), "refused": refused}


def _approve_one(item: OutreachItem, actor) -> None:
    plan = FormPlan.from_dict(item.plan)
    current = fingerprint.compute(item, plan)
    if current != item.fingerprint:  # the stored value drifted (should not happen): trust the recomputed one
        item.fingerprint = current
    record = ApprovalRecord.objects.create(
        item=item, approved_by=actor if getattr(actor, "is_authenticated", False) else None, fingerprint=item.fingerprint,
        message_sha256=fingerprint.message_sha256(item.rendered_text), target_url=item.target_url, action_url=plan.action_url,
    )
    updated = OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.READY).update(
        status=ItemStatus.APPROVED, approved_record=record, fingerprint=item.fingerprint, updated_at=timezone.now()
    )
    if not updated:  # someone else changed it a moment ago: the transaction rolls the record back
        raise _Raced()


class _Raced(Exception):
    pass


def revoke_items(campaign: Campaign, item_ids: list[int], actor=None) -> int:
    """Take approval back from approved items (they return to ``ready``). Returns how many."""
    items = list(campaign.items.filter(pk__in=item_ids, status=ItemStatus.APPROVED))
    n = OutreachItem.objects.filter(pk__in=[i.pk for i in items], status=ItemStatus.APPROVED).update(
        status=ItemStatus.READY, approved_record=None, updated_at=timezone.now()
    )
    if n:
        audit.log(AuditKind.APPROVAL, actor, f"تأیید {n} مورد پس گرفته شد (کمپین «{campaign.name}»)", {"campaign_id": campaign.pk, "item_ids": [i.pk for i in items], "revoked": True})
    return n
