"""Scheduled follow-ups, payment reminders and the survey send - one runner.

A `FollowUp` is a promise with a due time: «فردا به این مشتری یادآوری کن»,
«اگر تا ۲۴ ساعت رسید نفرستاد، یادآوری کن», «بعد از بستن، نظرسنجی بفرست». The
beat calls `run_due` every minute; each row is claimed by flipping its status
inside a transaction, so two workers never send the same reminder.

What a follow-up never does:
* it never writes to a **test** conversation (it records that it would have);
* it never messages a customer about an order that is no longer waiting on them
  (payment reminders re-check the order at send time);
* it never sends on a channel that is switched off - it fails with the reason,
  so the owner sees it instead of the reminder silently vanishing.

Payment reminders are transactional (they are about the customer's own order),
so the marketing opt-out does not stop them; a customer who does not want them
can say so to a person.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.customers import links
from apps.customers.models import Conversation, Notification, Order, notify

from . import sla, surveys
from .models import FollowUp

logger = logging.getLogger(__name__)

DEFAULT_PAYMENT_TEXT = (
    "سلام! سفارش شما هنوز منتظر پرداخت است. اگر پرداخت کرده‌اید، "
    "تصویر رسید را همین‌جا بفرستید تا تأیید شود؛ اگر سؤالی دارید بپرسید."
)


def create(
    store, *, conversation: Conversation | None, text: str, due_at: datetime, by,
    kind: str = FollowUp.Kind.FOLLOWUP, target: str = FollowUp.Target.CUSTOMER,
    order=None, assigned_to=None, is_test: bool = False,
) -> FollowUp:
    return FollowUp.objects.create(
        store=store, conversation=conversation, order=order, kind=kind, target=target,
        text=text.strip(), due_at=due_at, created_by=by, assigned_to=assigned_to or by,
        is_test=is_test or bool(conversation is not None and sla.is_test(conversation)),
    )


def cancel(followup: FollowUp) -> FollowUp:
    if followup.status == FollowUp.Status.PENDING:
        followup.status = FollowUp.Status.CANCELLED
        followup.save(update_fields=["status", "updated_at"])
    return followup


def scan_payment_reminders(now: datetime | None = None) -> int:
    """Queue a reminder for every order that has waited too long for its receipt."""
    from .models import InboxSettings

    now = now or timezone.now()
    created = 0
    for cfg in InboxSettings.objects.filter(payment_reminder_enabled=True).select_related("store"):
        store = cfg.store
        cutoff = now - timedelta(hours=max(1, cfg.payment_reminder_hours))
        orders = Order.objects.filter(
            store=store, status=Order.Status.AWAITING_RECEIPT, updated_at__lte=cutoff,
            conversation__isnull=False,
        ).select_related("conversation")
        for order in orders:
            sent = FollowUp.objects.filter(order=order, kind=FollowUp.Kind.PAYMENT).exclude(
                status=FollowUp.Status.CANCELLED,
            )
            if sent.count() >= cfg.payment_reminder_max:
                continue
            last = sent.order_by("-due_at").first()
            if last is not None and last.due_at > now - timedelta(hours=cfg.payment_reminder_hours):
                continue  # one per interval, not a burst
            create(
                store, conversation=order.conversation, order=order, due_at=now, by=None,
                text=cfg.payment_reminder_text or DEFAULT_PAYMENT_TEXT, kind=FollowUp.Kind.PAYMENT,
            )
            created += 1
    return created


def run_due(now: datetime | None = None, limit: int = 100) -> dict:
    now = now or timezone.now()
    done = failed = skipped = 0
    ids = list(
        FollowUp.objects.filter(status=FollowUp.Status.PENDING, due_at__lte=now)
        .order_by("due_at").values_list("pk", flat=True)[:limit]
    )
    for pk in ids:
        with transaction.atomic():
            row = FollowUp.objects.select_for_update().filter(pk=pk, status=FollowUp.Status.PENDING).first()
            if row is None:
                continue  # another worker took it
            outcome = _execute(row, now)
        if outcome == "sent":
            done += 1
        elif outcome == "failed":
            failed += 1
        else:
            skipped += 1
    return {"sent": done, "failed": failed, "skipped": skipped}


def _finish(row: FollowUp, status: str, error: str = "") -> str:
    row.status = status
    row.error = error[:300]
    if status == FollowUp.Status.SENT:
        row.sent_at = timezone.now()
    row.save(update_fields=["status", "error", "sent_at", "updated_at"])
    return "sent" if status == FollowUp.Status.SENT else ("failed" if status == FollowUp.Status.FAILED else "skipped")


def _execute(row: FollowUp, now: datetime) -> str:
    from . import replies

    conversation = row.conversation
    if row.target == FollowUp.Target.AGENT:
        who = row.assigned_to.username if row.assigned_to_id else ""
        notify(
            row.store, Notification.Type.ESCALATION, "یادآوری پیگیری",
            body=row.text[:200],
            link=links.conversation_link(conversation) if conversation else "",
            context={"for_user": who, "followup_id": row.pk,
                     "conversation_id": conversation.id if conversation else None},
        )
        return _finish(row, FollowUp.Status.SENT)
    if conversation is None:
        return _finish(row, FollowUp.Status.FAILED, "گفتگویی برای ارسال نیست.")
    if row.is_test or sla.is_test(conversation):
        return _finish(row, FollowUp.Status.CANCELLED, "نمونهٔ آزمایشی؛ چیزی فرستاده نشد.")
    if row.kind == FollowUp.Kind.PAYMENT:
        order = row.order
        if order is None or order.status != Order.Status.AWAITING_RECEIPT:
            return _finish(row, FollowUp.Status.CANCELLED, "سفارش دیگر منتظر پرداخت نیست.")
    kind = {"PAYMENT": "PAYMENT", "SURVEY": "SURVEY"}.get(row.kind, "FOLLOWUP")
    result = replies.system_reply(conversation, row.text, kind=kind)
    if not result["outcome"].get("sent"):
        return _finish(row, FollowUp.Status.FAILED, str(result["outcome"].get("reason", "")))
    if row.kind == FollowUp.Kind.SURVEY:
        surveys.mark_sent(conversation, agent=row.assigned_to)
        meta = sla.meta_for(conversation)
        meta.survey_sent_at = now
        meta.save(update_fields=["survey_sent_at"])
    return _finish(row, FollowUp.Status.SENT)
