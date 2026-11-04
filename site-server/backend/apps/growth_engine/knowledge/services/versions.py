"""Versions of an item's message: asking the AI for one, listing them, comparing, approving (replaces the item's text) and rejecting.

Approving a version replaces the item's TEXT and subject only. The item still needs its own send approval, and ``items.edit_item``
voids an earlier one (the fingerprint binds the exact text). Nothing here sends anything.
"""
from __future__ import annotations

import difflib
import re
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import ActivityKind
from apps.growth_engine.leads.services import history
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.outreach.models import Campaign, ItemStatus, OutreachItem
from apps.growth_engine.outreach.services import items as item_service

from ..models import GeneratedMessage

STALE_AFTER = timedelta(minutes=10)
MAX_INSTRUCTIONS = 500
CAN_WRITE = (ItemStatus.PENDING, ItemStatus.READY, ItemStatus.NEEDS_MANUAL, ItemStatus.APPROVED)


def _fail(field: str, code: str, message: str):
    raise ValidationFailed([{"field": field, "code": code, "message": message}])


def request_version(item: OutreachItem, user, instructions: str = "") -> tuple[GeneratedMessage, bool]:
    """Create a ``generating`` version row. Returns ``(version, created)``; ``created`` False = one was already being written.
    The caller enqueues ``tasks.write_version`` after the transaction commits."""
    if item.campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELLED):
        _fail("campaign", "campaign_closed", "این کمپین بسته شده است.")
    if item.status not in CAN_WRITE:
        _fail("status", "not_writable", "این مورد دیگر قابل ویرایش نیست.")
    instructions = nz.normalize_text(instructions)
    if len(instructions) > MAX_INSTRUCTIONS:
        _fail("instructions", "too_long", f"راهنما از {MAX_INSTRUCTIONS} نویسه بلندتر است.")
    now = timezone.now()
    for stale in item.versions.filter(status=GeneratedMessage.Status.GENERATING, created_at__lt=now - STALE_AFTER):
        stale.status, stale.error, stale.finished_at = GeneratedMessage.Status.FAILED, "نوشتن بیش از حد طول کشید و رها شد. دوباره امتحان کنید.", now
        stale.save(update_fields=["status", "error", "finished_at"])
    running = item.versions.filter(status=GeneratedMessage.Status.GENERATING).first()
    if running is not None:
        return running, False
    for _ in range(3):  # two requests at once: the unique (item, version) makes one of them retry
        number = (item.versions.aggregate(m=Max("version"))["m"] or 0) + 1
        try:
            with transaction.atomic():
                version = GeneratedMessage.objects.create(
                    item=item, version=number, instructions=instructions, created_by=user if getattr(user, "is_authenticated", False) else None
                )
            return version, True
        except IntegrityError:
            continue
    _fail("item", "busy", "همین حالا نسخهٔ دیگری ساخته می‌شود؛ چند لحظه بعد دوباره امتحان کنید.")


def sms_size(version: GeneratedMessage) -> dict | None:
    """For an SMS item: how many parts the version's final text costs (and whether that fits what the operator allows)."""
    if version.item.channel != "sms" or not version.text:
        return None
    from apps.growth_engine.outreach.channels import sms
    from apps.growth_engine.outreach.services import channel_config

    seg = sms.segments(version.text)
    limit = channel_config.sms_max_parts()
    return {**seg, "max_parts": limit, "fits": seg["parts"] <= limit}


def version_json(version: GeneratedMessage, *, current_text: str | None = None) -> dict:
    return {
        "id": version.pk, "item_id": version.item_id, "version": version.version, "status": version.status, "status_label": version.get_status_display(),
        "instructions": version.instructions, "subject": version.subject, "body": version.body, "text": version.text,
        "personalization_reason": version.personalization_reason, "evidence": version.evidence, "warnings": version.warnings,
        "blocking_warnings": len(version.blocking_warnings), "route": version.route, "error": version.error,
        "created_by_name": version.created_by.username if version.created_by_id else "", "created_at": version.created_at,
        "finished_at": version.finished_at, "decided_by_name": version.decided_by.username if version.decided_by_id else "", "decided_at": version.decided_at,
        "same_as_current": bool(current_text is not None and version.text and version.text.strip() == current_text.strip()),
        "sms": sms_size(version),
    }


def approve(version: GeneratedMessage, user, *, acknowledge_warnings: bool = False) -> GeneratedMessage:
    """Make the version's text the item's text. Blocking warnings need an explicit acknowledgement."""
    if version.status != GeneratedMessage.Status.PROPOSED:
        _fail("status", "not_proposed", "فقط نسخهٔ «پیشنهاد» را می‌شود پذیرفت.")
    blocking = version.blocking_warnings
    if blocking and not acknowledge_warnings:
        _fail("warnings", "needs_acknowledge", "این نسخه هشدارِ جدی دارد (" + " ".join(w["text"] for w in blocking[:2]) + ") و فقط با «با این هشدار می‌پذیرم» پذیرفته می‌شود.")
    item = OutreachItem.objects.select_related("lead", "campaign", "campaign__template", "template").get(pk=version.item_id)
    with transaction.atomic():
        item_service.edit_item(item, text=version.text, subject=version.subject if version.subject else None, actor=user)
        item.versions.filter(status=GeneratedMessage.Status.APPROVED).exclude(pk=version.pk).update(status=GeneratedMessage.Status.SUPERSEDED)
        version.status, version.decided_by, version.decided_at = GeneratedMessage.Status.APPROVED, user if getattr(user, "is_authenticated", False) else None, timezone.now()
        version.save(update_fields=["status", "decided_by", "decided_at"])
        history.log_activity(
            item.lead, ActivityKind.UPDATED, actor=user, summary=f"متنِ پیام با نسخهٔ {version.version} از نویسندهٔ هوشمند عوض شد",
            data={"item_id": item.pk, "version": version.version, "acknowledged_warnings": bool(blocking), "route": version.route, "campaign_id": item.campaign_id},
        )
    return version


def reject(version: GeneratedMessage, user) -> GeneratedMessage:
    if version.status not in (GeneratedMessage.Status.PROPOSED, GeneratedMessage.Status.FAILED):
        _fail("status", "not_rejectable", "این نسخه پیشنهاد نیست.")
    version.status, version.decided_by, version.decided_at = GeneratedMessage.Status.REJECTED, user if getattr(user, "is_authenticated", False) else None, timezone.now()
    version.save(update_fields=["status", "decided_by", "decided_at"])
    return version


# --------------------------------------------------------------------------- compare

_TOKEN = re.compile(r"\s+|[^\s]+")


def compare(a_text: str, b_text: str) -> list[dict]:
    """Word-level difference: ``[{"op": "equal"|"delete"|"insert", "a": str, "b": str}]`` (``a`` = the old side, ``b`` = the new side)."""
    a, b = _TOKEN.findall(a_text or ""), _TOKEN.findall(b_text or "")
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        old, new = "".join(a[i1:i2]), "".join(b[j1:j2])
        if tag == "equal":
            ops.append({"op": "equal", "a": old, "b": new})
        else:
            if old:
                ops.append({"op": "delete", "a": old, "b": ""})
            if new:
                ops.append({"op": "insert", "a": "", "b": new})
    return ops
