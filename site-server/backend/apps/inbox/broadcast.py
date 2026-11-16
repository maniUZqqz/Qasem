"""Broadcast: one message to a segment, across channels, without hurting anyone.

A broadcast is the most dangerous thing this inbox can do - it speaks to
thousands of people in the shop's voice, and a bot that spams gets banned from
the platform the shop's customers actually use. So the design is a chain of
brakes, each one visible to the owner:

1. **Preview before anything** - who would receive it, on which channel, who is
   skipped and why (opted out, no address, test contact), and what the message
   will look like after `{name}` is filled in. Nothing is queued by previewing.
2. **Owner approval** - `submit` only moves a draft to `PENDING`; only someone
   who may change settings (owner / admin) can `approve`, and a member cannot
   approve their own broadcast unless they are the owner. A broadcast flagged
   `is_test` can never be approved at all.
3. **Opt-out is honoured at send time**, not only at queue time: a customer who
   wrote «لغو» an hour after approval is skipped on the minute it matters.
4. **Per-channel rate limit** (`InboxSettings.rate_limits`, messages/minute), counted
   across *all* of a store's broadcasts, so two campaigns cannot add up to a ban.
5. **A mandatory way out** - every message carries «برای لغو، «لغو» را بفرستید»
   unless the shop's text already says it.
6. **A failing channel pauses itself** - three failures in a row on one channel
   and that channel is skipped for the minute instead of hammering a dead token.

Recipients are one row per (person, channel) and, by default, one *channel* per
person (`dedupe`): the same woman on Telegram and SMS is messaged once, on her
best channel, not twice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.customers.models import Conversation, Customer, Message, Notification, notify
from apps.stores import access

from . import contacts as contacts_mod
from . import dispatch, events, norm, segments, team
from .models import (
    Broadcast, BroadcastRecipient, ChannelConnection, Contact, ContactLink, MessageMeta,
)

logger = logging.getLogger(__name__)

#: Messages per minute per channel when the store has not chosen. Conservative on
#: purpose: these are numbers a platform will not mind, not numbers it allows.
DEFAULT_RATE = {"TELEGRAM": 20, "BALE": 20, "EITAA": 15, "RUBIKA": 15, "WHATSAPP": 20, "SMS": 10, "WEBCHAT": 0}
MAX_RATE = 120
#: Best channel first, for `dedupe`. SMS is last: it costs money and is one-way.
PRIORITY = ["TELEGRAM", "BALE", "RUBIKA", "EITAA", "WHATSAPP", "SMS"]
PAUSE_AFTER_FAILURES = 3
OPT_OUT_FOOTER = "\n\nبرای لغو دریافت پیام‌ها، «لغو» را بفرستید."
#: Why a recipient was skipped, in words the owner reads (the codes are stored in the row).
SKIP_REASON_TITLES = {
    "opted_out": "پیام تبلیغاتی را لغو کرده است",
    "cancelled": "ارسال لغو شد",
    "no_address": "راه ارسال ندارد",
    "channel_off": "کانال خاموش است",
}


class BroadcastError(Exception):
    """A rule was broken. The message is Persian and shown as is."""


def rate_for(store, channel: str) -> int:
    cfg = team.settings_for(store)
    value = (cfg.rate_limits or {}).get(channel, DEFAULT_RATE.get(channel, 10))
    try:
        return max(0, min(MAX_RATE, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_RATE.get(channel, 10)


def sendable_channels(store) -> list[str]:
    """Channels that are connected, switched on and able to start a message."""
    out = []
    for conn in ChannelConnection.objects.filter(store=store, enabled=True):
        if conn.kind in PRIORITY and dispatch.is_ready(conn):
            out.append(conn.kind)
    return [k for k in PRIORITY if k in out]


def render(text: str, contact: Contact | None) -> str:
    """Fill `{name}`; add the way out. The shop's own text is never rewritten."""
    first = ((contact.name if contact else "") or "").strip().split(" ")[0] if contact else ""
    out = (text or "").replace("{name}", first or "دوست عزیز").replace("{نام}", first or "دوست عزیز")
    if "لغو" not in out:
        out += OPT_OUT_FOOTER
    return out


def _address(contact: Contact, channel: str) -> tuple[Customer | None, str]:
    """(customer to attach the message to, platform address) for this contact+channel."""
    if channel == "SMS":
        if not norm.is_mobile(contact.phone):
            return None, ""
        customer, _ = Customer.objects.get_or_create(
            store=contact.store, channel="sms", external_id=contact.phone,
            defaults={"name": contact.name, "phone": contact.phone},
        )
        ContactLink.objects.get_or_create(
            customer=customer, defaults={"contact": contact, "matched_by": "phone"},
        )
        return customer, contact.phone
    customer = Customer.objects.filter(
        inbox_link__contact=contact, channel=channel.lower(),
    ).order_by("id").first()
    if customer is None or not customer.external_id:
        return None, ""
    return customer, customer.external_id


def build_recipients(broadcast: Broadcast, *, persist: bool = False) -> dict:
    """Work out who gets this. `persist=True` writes the `BroadcastRecipient` rows."""
    store = broadcast.store
    rules = broadcast.segment.rules if broadcast.segment_id else {}
    people = segments.contacts_in(store, rules, include_test=broadcast.is_test)
    wanted = [c.upper() for c in (broadcast.channels or [])] or sendable_channels(store)
    ready = set(sendable_channels(store))
    skipped = {"opted_out": 0, "no_address": 0, "channel_off": 0}
    rows: list[tuple[Contact, str, Customer, str]] = []
    per_channel: dict[str, int] = {}
    for person in people:
        chosen = []
        for channel in PRIORITY:
            if channel not in wanted:
                continue
            if channel not in ready:
                continue
            if person.opted_out_of(channel):
                continue
            customer, address = _address(person, channel) if persist else _peek(person, channel)
            if not address:
                continue
            chosen.append((person, channel, customer, address))
            if broadcast.dedupe:
                break
        if not chosen:
            if person.opted_out_of("ALL"):
                skipped["opted_out"] += 1
            else:
                skipped["no_address"] += 1
            continue
        for item in chosen:
            rows.append(item)
            per_channel[item[1]] = per_channel.get(item[1], 0) + 1
    off = [c for c in wanted if c not in ready]
    skipped["channel_off"] = len(off)
    if persist:
        with transaction.atomic():
            broadcast.recipients.all().delete()
            BroadcastRecipient.objects.bulk_create([
                BroadcastRecipient(
                    broadcast=broadcast, contact=person, customer=customer, channel=channel, to=address,
                ) for person, channel, customer, address in rows
            ])
    return {"people": len(people), "recipients": len(rows), "per_channel": per_channel,
            "skipped": skipped, "channels_off": off, "rows": rows}


def _peek(contact: Contact, channel: str):
    """Like `_address` but without creating rows - used by the preview."""
    if channel == "SMS":
        return (None, contact.phone) if norm.is_mobile(contact.phone) else (None, "")
    customer = Customer.objects.filter(
        inbox_link__contact=contact, channel=channel.lower(),
    ).order_by("id").first()
    return (customer, customer.external_id) if customer and customer.external_id else (None, "")


def preview(broadcast: Broadcast) -> dict:
    """What this broadcast would do, without doing any of it."""
    plan = build_recipients(broadcast, persist=False)
    samples = [
        {"to": c.name or c.phone or "-", "channel": ch, "text": render(broadcast.text, c)}
        for c, ch, _cust, _addr in plan["rows"][:3]
    ]
    minutes = 0
    for channel, count in plan["per_channel"].items():
        rate = max(1, rate_for(broadcast.store, channel))
        minutes = max(minutes, -(-count // rate))
    warnings = []
    if len(render(broadcast.text, None)) > 480 and "SMS" in plan["per_channel"]:
        warnings.append("متن برای پیامک بلند است (بیش از ۴۸۰ نویسه) و رد می‌شود.")
    if plan["channels_off"]:
        warnings.append("کانال‌های خاموش یا وصل‌نشده کنار گذاشته شدند.")
    if broadcast.is_test:
        warnings.append("این ارسال آزمایشی است؛ هرگز فرستاده نمی‌شود.")
    return {
        "people": plan["people"], "recipients": plan["recipients"],
        "per_channel": plan["per_channel"], "skipped": plan["skipped"],
        "channels_off": plan["channels_off"], "samples": samples,
        "estimated_minutes": minutes, "warnings": warnings,
    }


def submit(broadcast: Broadcast, user) -> Broadcast:
    if broadcast.status not in (Broadcast.Status.DRAFT, Broadcast.Status.REJECTED):
        raise BroadcastError("فقط پیش‌نویس را می‌شود برای تأیید فرستاد.")
    if not (broadcast.text or "").strip():
        raise BroadcastError("متن پیام خالی است.")
    plan = build_recipients(broadcast, persist=True)
    if not plan["recipients"]:
        raise BroadcastError("هیچ گیرنده‌ای پیدا نشد؛ بخش یا کانال‌ها را عوض کنید.")
    broadcast.status = Broadcast.Status.PENDING
    broadcast.review_note = ""
    broadcast.stats = {"recipients": plan["recipients"], "per_channel": plan["per_channel"], "sent": 0, "failed": 0}
    broadcast.save(update_fields=["status", "review_note", "stats", "updated_at"])
    notify(
        broadcast.store, Notification.Type.ESCALATION,
        f"ارسال گروهی منتظر تأیید شماست: {broadcast.name}",
        body=f"{plan['recipients']} گیرنده", link=f"/stores/{broadcast.store_id}/inbox/broadcasts",
        context={"broadcast_id": broadcast.pk, "for_role": "approver"},
    )
    return broadcast


def can_approve(user, broadcast: Broadcast) -> tuple[bool, str]:
    store = broadcast.store
    if not access.can(user, store, access.SETTINGS, write=True):
        return False, "فقط مالک یا مدیر فروشگاه می‌تواند ارسال گروهی را تأیید کند."
    if broadcast.is_test:
        return False, "ارسال آزمایشی را نمی‌شود تأیید کرد."
    if broadcast.created_by_id == user.pk and store.owner_id != user.pk:
        return False, "ارسالی که خودتان ساخته‌اید را باید شخص دیگری تأیید کند."
    return True, ""


def approve(broadcast: Broadcast, user) -> Broadcast:
    ok, why = can_approve(user, broadcast)
    if not ok:
        raise BroadcastError(why)
    if broadcast.status != Broadcast.Status.PENDING:
        raise BroadcastError("این ارسال منتظر تأیید نیست.")
    # Re-resolve at approval: people may have opted out or left since submit.
    plan = build_recipients(broadcast, persist=True)
    if not plan["recipients"]:
        raise BroadcastError("حالا هیچ گیرنده‌ای باقی نمانده است.")
    broadcast.status = Broadcast.Status.APPROVED
    broadcast.approved_by = user
    broadcast.approved_at = timezone.now()
    broadcast.stats = {**(broadcast.stats or {}), "recipients": plan["recipients"], "per_channel": plan["per_channel"]}
    broadcast.save(update_fields=["status", "approved_by", "approved_at", "stats", "updated_at"])
    from . import sms_gateway

    sms_gateway.approve_campaign(broadcast, user)
    events.emit(broadcast.store, "broadcast.approved", {"broadcast_id": broadcast.pk, "recipients": plan["recipients"]})
    return broadcast


def reject(broadcast: Broadcast, user, note: str = "") -> Broadcast:
    if not access.can(user, broadcast.store, access.SETTINGS, write=True):
        raise BroadcastError("فقط مالک یا مدیر فروشگاه می‌تواند ارسال گروهی را رد کند.")
    if broadcast.status != Broadcast.Status.PENDING:
        raise BroadcastError("این ارسال منتظر تأیید نیست.")
    broadcast.status = Broadcast.Status.REJECTED
    broadcast.review_note = note[:300]
    broadcast.save(update_fields=["status", "review_note", "updated_at"])
    return broadcast


def cancel(broadcast: Broadcast, user) -> Broadcast:
    if broadcast.status in (Broadcast.Status.SENT, Broadcast.Status.CANCELLED):
        raise BroadcastError("این ارسال تمام یا لغو شده است.")
    broadcast.status = Broadcast.Status.CANCELLED
    broadcast.save(update_fields=["status", "updated_at"])
    broadcast.recipients.filter(status=BroadcastRecipient.Status.QUEUED).update(
        status=BroadcastRecipient.Status.SKIPPED, skip_reason="cancelled",
    )
    from . import sms_gateway

    sms_gateway.revoke_campaign(broadcast)
    return broadcast


def _thread_for(row: BroadcastRecipient) -> Conversation:
    conversation, _ = Conversation.objects.get_or_create(
        store=row.broadcast.store, customer=row.customer, channel=row.channel, external_id=row.to,
        defaults={"state": Conversation.State.AI},
    )
    return conversation


def _send_one(row: BroadcastRecipient) -> bool:
    from services.publishing import channels

    contact = Contact.objects.get(pk=row.contact_id)  # fresh: opt-out may have changed
    if contact.opted_out_of(row.channel):
        row.status, row.skip_reason = BroadcastRecipient.Status.SKIPPED, "opted_out"
        row.save(update_fields=["status", "skip_reason"])
        return True  # not a channel failure
    text = render(row.broadcast.text, contact)
    if row.channel == "SMS":
        # The phone gateway only takes marketing SMS from a campaign a person
        # approved (registered in `approve`), and enforces its own quiet hours.
        from . import sms_gateway

        outcome = sms_gateway.send_marketing(row.to, text, campaign_ref=sms_gateway.campaign_ref(row.broadcast))
    else:
        outcome = channels.send(row.channel, row.broadcast.store, to=row.to, text=text)
    now = timezone.now()
    if outcome.get("sent"):
        conversation = _thread_for(row)
        message = Message(conversation=conversation, role=Message.Role.AI, text=text)
        message._inbox_skip = True
        message.save()
        MessageMeta.objects.create(
            message=message, kind=MessageMeta.Kind.BROADCAST, delivered=True,
            platform_message_id=str(outcome.get("external_id", "")),
        )
        row.status, row.sent_at = BroadcastRecipient.Status.SENT, now
        row.save(update_fields=["status", "sent_at"])
        return True
    row.status, row.error = BroadcastRecipient.Status.FAILED, str(outcome.get("reason", ""))[:300]
    row.save(update_fields=["status", "error"])
    return False


def send_tick(now: datetime | None = None) -> dict:
    """Send what the per-channel limits allow. Called every minute by the beat."""
    now = now or timezone.now()
    stats = {"sent": 0, "failed": 0, "finished": 0}
    live = Broadcast.objects.filter(
        status__in=[Broadcast.Status.APPROVED, Broadcast.Status.SENDING], is_test=False,
    ).select_related("store").order_by("approved_at", "id")
    for broadcast in live:
        if broadcast.scheduled_at and broadcast.scheduled_at > now:
            continue
        if broadcast.status == Broadcast.Status.APPROVED:
            broadcast.status = Broadcast.Status.SENDING
            broadcast.started_at = now
            broadcast.save(update_fields=["status", "started_at", "updated_at"])
        for channel in {r for r in broadcast.recipients.filter(
            status=BroadcastRecipient.Status.QUEUED).values_list("channel", flat=True)}:
            budget = rate_for(broadcast.store, channel) - BroadcastRecipient.objects.filter(
                broadcast__store=broadcast.store, channel=channel,
                status=BroadcastRecipient.Status.SENT, sent_at__gte=now - timedelta(seconds=60),
            ).count()
            if budget <= 0:
                continue
            streak = 0
            queue = broadcast.recipients.filter(
                status=BroadcastRecipient.Status.QUEUED, channel=channel,
            ).select_related("contact", "customer", "broadcast", "broadcast__store").order_by("id")[:budget]
            for row in queue:
                if _send_one(row):
                    streak = 0
                    if row.status == BroadcastRecipient.Status.SENT:
                        stats["sent"] += 1
                else:
                    stats["failed"] += 1
                    streak += 1
                    if streak >= PAUSE_AFTER_FAILURES:
                        break  # this channel is unwell; try again next minute
        _refresh(broadcast, stats, now)
    return stats


def _refresh(broadcast: Broadcast, stats: dict, now: datetime) -> None:
    rows = broadcast.recipients
    counts = {
        "sent": rows.filter(status=BroadcastRecipient.Status.SENT).count(),
        "failed": rows.filter(status=BroadcastRecipient.Status.FAILED).count(),
        "queued": rows.filter(status=BroadcastRecipient.Status.QUEUED).count(),
        "skipped": rows.filter(status=BroadcastRecipient.Status.SKIPPED).count(),
    }
    broadcast.stats = {**(broadcast.stats or {}), **counts}
    fields = ["stats", "updated_at"]
    if counts["queued"] == 0:
        broadcast.status = Broadcast.Status.SENT
        broadcast.finished_at = now
        fields += ["status", "finished_at"]
        stats["finished"] += 1
        events.emit(broadcast.store, "broadcast.finished", {"broadcast_id": broadcast.pk, **counts})
    broadcast.save(update_fields=fields)
