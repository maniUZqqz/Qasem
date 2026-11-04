"""Changing an item's message, and what that does to an approval."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.growth_engine.compliance.models import AuditKind, GrowthSettings
from apps.growth_engine.compliance.services import audit
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.services.editing import ValidationFailed

from ..models import ItemStatus, OutreachItem
from . import fingerprint, generators

EDITABLE = (ItemStatus.PENDING, ItemStatus.READY, ItemStatus.NEEDS_MANUAL, ItemStatus.APPROVED)
MAX_TEXT = 5000


def invalidate_approval(item: OutreachItem, actor, why: str) -> bool:
    """An approved item goes back to ``ready`` and its approval stops counting. The ApprovalRecord itself stays (history)."""
    if item.status != ItemStatus.APPROVED:
        return False
    changed = OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.APPROVED).update(
        status=ItemStatus.READY, approved_record=None, updated_at=timezone.now()
    )
    item.status, item.approved_record = ItemStatus.READY, None
    if changed:
        audit.log(AuditKind.APPROVAL, actor, f"تأیید باطل شد (لید {item.lead_id}): {why}", {"item_id": item.pk, "campaign_id": item.campaign_id, "why": why})
    return bool(changed)


def refresh_fingerprint(item: OutreachItem, actor, why: str) -> bool:
    """Recompute the fingerprint; if it moved, save it and void any approval. Returns True when it moved."""
    new = fingerprint.compute(item)
    if new == item.fingerprint:
        return False
    item.fingerprint = new
    OutreachItem.objects.filter(pk=item.pk).update(fingerprint=new, updated_at=timezone.now())
    invalidate_approval(item, actor, why)
    return True


def edit_item(item: OutreachItem, *, text: str | None = None, subject: str | None = None, actor=None) -> OutreachItem:
    """Edit the final message text and/or subject. The opt-out line must stay in the text."""
    if item.status not in EDITABLE:
        raise ValidationFailed([{"field": "status", "code": "not_editable", "message": "این مورد دیگر قابل ویرایش نیست."}])
    errors = []
    new_text = item.rendered_text
    new_subject = item.subject
    if text is not None:
        new_text = nz.normalize_text(text, multiline=True)
        opt_out = nz.normalize_text(GrowthSettings.load().opt_out_line, multiline=True)
        if not new_text:
            errors.append({"field": "rendered_text", "code": "empty", "message": "متنِ پیام خالی است."})
        elif len(new_text) > MAX_TEXT:
            errors.append({"field": "rendered_text", "code": "too_long", "message": f"متن از {MAX_TEXT} نویسه بلندتر است."})
        elif opt_out and opt_out not in new_text:
            errors.append({"field": "rendered_text", "code": "opt_out_missing", "message": "جملهٔ لغو عضویت را از انتهای پیام حذف نکنید؛ هر پیام باید با آن تمام شود."})
    if subject is not None:
        new_subject = nz.normalize_text(subject)
        if len(new_subject) > 300:
            errors.append({"field": "subject", "code": "too_long", "message": "موضوع از ۳۰۰ نویسه بلندتر است."})
    if errors:
        raise ValidationFailed(errors)
    with transaction.atomic():
        item.rendered_text, item.subject = new_text, new_subject
        item.text_edited = item.text_edited or text is not None
        item.save(update_fields=["rendered_text", "subject", "text_edited", "updated_at"])
        refresh_fingerprint(item, actor, "پیام یا موضوع ویرایش شد")
    return item


def rerender_item(item: OutreachItem, actor=None) -> OutreachItem:
    """Rebuild the message from the template, the lead's CURRENT data and the CURRENT Growth Settings (drops manual edits)."""
    if item.status not in EDITABLE:
        raise ValidationFailed([{"field": "status", "code": "not_editable", "message": "این مورد دیگر قابل ویرایش نیست."}])
    built = generators.build_message(item.campaign.template, item.lead, GrowthSettings.load())
    with transaction.atomic():
        item.rendered_text, item.subject, item.text_edited = built.text, built.subject, False
        item.save(update_fields=["rendered_text", "subject", "text_edited", "updated_at"])
        refresh_fingerprint(item, actor, "متن دوباره از قالب ساخته شد")
    return item
