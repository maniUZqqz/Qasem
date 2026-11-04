"""The manual queue: a person submits the message by hand and records what happened.

Outcomes: ``sent`` -> ``manual_sent``, ``no_form`` -> ``no_form``, ``needs_login`` -> ``needs_login``, ``skipped`` -> ``skipped``.
Each one is written to the lead's history with the EXACT message text that was shown; ``sent`` also moves a fresh lead
to «تماس گرفته‌شده». A lead on the do-not-contact list can never be recorded as «sent».
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import PRE_CONTACT_STATUSES, ActivityKind
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services import editing, history
from apps.growth_engine.leads.services.editing import ValidationFailed

from ..models import Campaign, ItemStatus, OutreachItem
from . import campaigns, guard

logger = logging.getLogger(__name__)

OUTCOMES = {
    "sent": ItemStatus.MANUAL_SENT,
    "no_form": ItemStatus.NO_FORM,
    "needs_login": ItemStatus.NEEDS_LOGIN,
    "skipped": ItemStatus.SKIPPED,
}
SUMMARIES = {
    "sent": "پیام دستی ارسال شد",
    "no_form": "فرمِ تماس پیدا نشد (ارسالِ دستی انجام نشد)",
    "needs_login": "برای ارسال باید وارد حساب شد (ارسالِ دستی انجام نشد)",
    "skipped": "از صفِ پیام رد شد",
}
ALLOWED_FROM = (ItemStatus.PENDING, ItemStatus.READY, ItemStatus.NEEDS_MANUAL)


def record_outcome(item: OutreachItem, outcome: str, note: str = "", actor=None) -> OutreachItem:
    if outcome not in OUTCOMES:
        raise ValidationFailed([{"field": "outcome", "code": "invalid_outcome", "message": "نتیجه باید یکی از «ارسال شد»، «فرم نداشت»، «نیاز به ورود» یا «رد» باشد."}])
    note = nz.normalize_text(note)
    if len(note) > 500:
        raise ValidationFailed([{"field": "note", "code": "too_long", "message": "یادداشت از ۵۰۰ نویسه بلندتر است."}])
    campaign = item.campaign
    if campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELLED):
        raise ValidationFailed([{"field": "campaign", "code": "campaign_closed", "message": "این کمپین بسته شده است."}])
    if item.status not in ALLOWED_FROM:
        raise ValidationFailed([{"field": "status", "code": "not_open", "message": "برای این مورد قبلاً نتیجه ثبت شده یا هنوز تأییدِ خودکار دارد (اول لغوِ تأیید را بزنید)."}])
    if outcome == "sent":
        if suppression.matches_for_lead(item.lead):
            raise ValidationFailed([{"field": "outcome", "code": guard.SUPPRESSED, "message": guard.TEXTS[guard.SUPPRESSED]}])
        if not item.forced and guard.contacted_elsewhere(item):
            raise ValidationFailed([{"field": "outcome", "code": guard.ALREADY_CONTACTED, "message": guard.TEXTS[guard.ALREADY_CONTACTED]}])
    status = OUTCOMES[outcome]
    with transaction.atomic():
        changed = OutreachItem.objects.filter(pk=item.pk, status__in=ALLOWED_FROM).update(
            status=status, manual_note=note, approved_record=None, updated_at=timezone.now(),
            skip_reason="" if outcome == "sent" else item.skip_reason,
        )
        if not changed:
            raise ValidationFailed([{"field": "status", "code": "not_open", "message": "این مورد همین حالا تغییر کرد؛ صفحه را تازه کنید."}])
        item.status, item.manual_note = status, note
        history.log_activity(
            item.lead, ActivityKind.QUEUE_OUTCOME, actor=actor, summary=SUMMARIES[outcome] + (f": {note}" if note else ""),
            data={
                "outcome": outcome, "channel": "manual", "message_text": item.rendered_text, "subject": item.subject,
                "target_url": item.target_url, "note": note, "campaign_id": item.campaign_id, "template_id": campaign.template_id, "item_id": item.pk,
            },
        )
        if campaign.mode == Campaign.Mode.MANUAL and campaign.status == Campaign.Status.DRAFT:
            campaigns.start(campaign, actor)  # working the queue is running the campaign
    if outcome == "sent" and Lead.objects.filter(pk=item.lead_id, status__in=PRE_CONTACT_STATUSES).exists():
        try:
            editing.update_lead(item.lead, {"status": "contacted"}, actor)
        except Exception:  # noqa: BLE001 - the outcome is recorded; a status nicety must not undo it
            logger.exception("could not advance lead %s to contacted", item.lead_id)
    campaigns.maybe_complete(campaign)
    return item
