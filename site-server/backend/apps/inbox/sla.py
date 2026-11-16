"""The SLA clock: how long a customer may wait for a person.

One number per store (`sla_first_response_min`) and one clock per conversation
(`ConversationMeta.waiting_since` -> `sla_due_at`). The clock:

* **starts** when a person starts owing an answer - a handoff from the bot, or a
  new customer message on a thread a person already holds;
* **pauses over closed hours** when the store asks for it, by starting from the
  next opening time - nobody should be "late" at 3 am Friday;
* **stops** when a person replies (`team`/`replies.py` calls `stop`).

`tick` is the Celery beat half: warns at `sla_warn_percent` of the allowance and
again when it is breached, each exactly once per waiting stretch (the
`sla_warned_at` / `sla_breached_at` columns are the memory).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from apps.customers import links
from apps.customers.models import Conversation, Notification, notify

from . import hours as hours_mod
from .models import ConversationMeta, InboxSettings


def meta_for(conversation: Conversation) -> ConversationMeta:
    meta, _ = ConversationMeta.objects.get_or_create(
        conversation=conversation, defaults={"store": conversation.store},
    )
    return meta


def is_test(conversation: Conversation) -> bool:
    """A thread the owner started to try things out - by customer channel or by the inbox flag.

    Asked of the database, not of a cached `inbox_meta`: the flag is set from a
    different object than the one a long-running task may be holding.
    """
    if conversation.is_test:
        return True
    return ConversationMeta.objects.filter(conversation_id=conversation.pk, is_test=True).exists()


def _start_point(cfg: InboxSettings, now: datetime) -> datetime:
    if cfg.sla_pause_off_hours and hours_mod.configured(cfg.working_hours):
        return hours_mod.next_open(cfg.working_hours, now)
    return now


def start(conversation: Conversation, now: datetime | None = None) -> ConversationMeta:
    """A person now owes this customer an answer. Idempotent while waiting."""
    now = now or timezone.now()
    meta = meta_for(conversation)
    if meta.waiting_since is not None:
        return meta
    from .team import settings_for

    cfg = settings_for(conversation.store)
    meta.waiting_since = now
    meta.sla_due_at = _start_point(cfg, now) + timedelta(minutes=cfg.sla_first_response_min)
    meta.sla_warned_at = None
    meta.sla_breached_at = None
    meta.save(update_fields=["waiting_since", "sla_due_at", "sla_warned_at", "sla_breached_at"])
    return meta


def stop(conversation: Conversation, now: datetime | None = None) -> int | None:
    """A person answered. Returns the seconds the customer waited, if known."""
    now = now or timezone.now()
    meta = meta_for(conversation)
    waited = None
    if meta.waiting_since is not None:
        waited = max(0, int((now - meta.waiting_since).total_seconds()))
    fields = ["waiting_since", "sla_due_at", "unread_count"]
    meta.waiting_since = None
    meta.sla_due_at = None
    if meta.first_human_reply_at is None:
        meta.first_human_reply_at = now
        meta.first_response_seconds = waited
        fields += ["first_human_reply_at", "first_response_seconds"]
    meta.save(update_fields=fields)
    return waited


def status_of(meta: ConversationMeta | None, now: datetime | None = None) -> str:
    """`ok`, `warning`, `breached`, or `none` - what the inbox row shows."""
    if meta is None or meta.waiting_since is None or meta.sla_due_at is None:
        return "none"
    if meta.sla_breached_at is not None:
        return "breached"
    now = now or timezone.now()
    if now >= meta.sla_due_at:
        return "breached"
    from .team import settings_for

    cfg = settings_for(meta.store)
    start_at = meta.sla_due_at - timedelta(minutes=cfg.sla_first_response_min)
    allowance = (meta.sla_due_at - start_at).total_seconds() or 1
    used = (now - start_at).total_seconds() / allowance
    return "warning" if used * 100 >= cfg.sla_warn_percent else "ok"


def tick(now: datetime | None = None) -> dict:
    """Warn and flag. Safe to run every minute, and to run twice."""
    now = now or timezone.now()
    warned = breached = 0
    rows = (
        ConversationMeta.objects.filter(waiting_since__isnull=False, sla_due_at__isnull=False, is_test=False)
        .select_related("conversation", "conversation__store", "conversation__customer")
    )
    for meta in rows:
        conversation = meta.conversation
        if conversation.state not in (Conversation.State.HUMAN, Conversation.State.ESCALATED):
            continue
        state = status_of(meta, now)
        if state == "breached" and meta.sla_breached_at is None:
            meta.sla_breached_at = now
            meta.save(update_fields=["sla_breached_at"])
            breached += 1
            _alert(conversation, "SLA رد شد", "مشتری بیش از زمان مجاز منتظر پاسخ مانده است.", meta, "breached")
        elif state == "warning" and meta.sla_warned_at is None:
            meta.sla_warned_at = now
            meta.save(update_fields=["sla_warned_at"])
            warned += 1
            _alert(conversation, "SLA در آستانهٔ رد شدن", "کمی بعد مشتری از زمان مجاز انتظار می‌گذرد.", meta, "warning")
    return {"warned": warned, "breached": breached}


def _alert(conversation: Conversation, title: str, body: str, meta: ConversationMeta, level: str) -> None:
    who = conversation.assigned_to.username if conversation.assigned_to_id else ""
    notify(
        conversation.store,
        Notification.Type.ESCALATION,
        f"{title} - {conversation.customer.name or 'مشتری'}",
        body=body,
        link=links.conversation_link(conversation),
        context={
            "conversation_id": conversation.id, "sla": level,
            "for_user": who, "due_at": meta.sla_due_at.isoformat() if meta.sla_due_at else "",
        },
    )
    from . import events

    events.emit(conversation.store, "sla." + level, {
        "conversation_id": conversation.id, "assigned_to": who,
        "waiting_since": meta.waiting_since.isoformat() if meta.waiting_since else None,
    })
