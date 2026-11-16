"""Everything a person (or the system) writes into a conversation.

Three kinds of outgoing text, deliberately different:

* **`reply`** - a team member answers the customer. Delivered on the customer's
  channel, recorded with its author, stops the SLA clock and takes the thread
  from the AI.
* **`system_reply`** - the system speaks (opt-out confirmation, survey, follow-up,
  payment reminder, off-hours notice). Delivered the same way, never attributed
  to a person, never counted in anyone's response time.
* **`add_note`** - an internal note. **Never delivered and never read by the AI**:
  it is stored in its own table precisely so that no code path that builds a
  prompt from `conversation.messages` can leak a colleague's opinion of the
  customer back to them.
"""
from __future__ import annotations

import re

from django.contrib.auth.models import User
from django.utils import timezone

from apps.customers import ai_retry, links
from apps.customers.models import Conversation, Message, Notification, notify
from services.publishing import channels

from . import events, sla, team
from .models import CannedReply, InternalNote, MessageMeta

MENTION_RE = re.compile(r"@([A-Za-z0-9_.\-]{2,150})")


def _target(conversation: Conversation) -> str:
    return conversation.external_id or str(conversation.customer_id)


def _deliver(conversation: Conversation, text: str) -> dict:
    try:
        return channels.send(conversation.channel, conversation.store, to=_target(conversation), text=text)
    except Exception as exc:  # noqa: BLE001 - the text must not be lost to a crash
        return {"sent": False, "reason": f"ارسال ممکن نشد ({type(exc).__name__})."}


def reply(conversation: Conversation, user: User, text: str, *, canned: CannedReply | None = None) -> dict:
    """A team member answers the customer."""
    text = (text or "").strip()
    outcome = _deliver(conversation, text)
    message = Message.objects.create(conversation=conversation, role=Message.Role.HUMAN, text=text)
    waited = sla.stop(conversation)
    MessageMeta.objects.create(
        message=message, author=user, kind=MessageMeta.Kind.REPLY,
        delivered=bool(outcome.get("sent")), delivery_error=str(outcome.get("reason", ""))[:300],
        platform_message_id=str(outcome.get("external_id", "")), response_seconds=waited,
        canned_reply=canned,
    )
    if canned is not None:
        CannedReply.objects.filter(pk=canned.pk).update(use_count=canned.use_count + 1)

    conversation.state = Conversation.State.HUMAN
    if not conversation.assigned_to_id:
        conversation.assigned_to = user
    ai_retry.clear_failed(conversation)
    conversation.save(update_fields=["state", "assigned_to", "updated_at", *ai_retry.CLEAR_FIELDS])
    events.emit(conversation.store, "message.sent", {
        "conversation_id": conversation.id, "message_id": message.id, "by": user.username,
        "channel": conversation.channel, "text": text, "delivered": bool(outcome.get("sent")),
    })
    return {"message": message, "outcome": outcome, "response_seconds": waited}


def system_reply(conversation: Conversation, text: str, *, kind: str = "SYSTEM") -> dict:
    """The system writes to the customer - not a person, not the AI turn."""
    outcome = _deliver(conversation, text)
    message = Message(conversation=conversation, role=Message.Role.AI, text=text)
    message._inbox_skip = True  # signals: this is a system line, not a bot answer
    message.save()
    MessageMeta.objects.create(
        message=message, author=None, kind=kind,
        delivered=bool(outcome.get("sent")), delivery_error=str(outcome.get("reason", ""))[:300],
        platform_message_id=str(outcome.get("external_id", "")),
    )
    return {"message": message, "outcome": outcome}


def add_note(conversation: Conversation, user: User, text: str) -> InternalNote:
    text = (text or "").strip()
    store = conversation.store
    known = {u.username.lower(): u for u in team.members(store)}
    mentions = []
    for name in MENTION_RE.findall(text):
        person = known.get(name.lower())
        if person is not None and person.username not in mentions:
            mentions.append(person.username)
    note = InternalNote.objects.create(conversation=conversation, author=user, text=text, mentions=mentions)
    for username in mentions:
        if username == user.username:
            continue
        notify(
            store, Notification.Type.ESCALATION,
            f"{user.username} شما را در یک گفتگو نام برد",
            body=text[:200], link=links.conversation_link(conversation),
            context={"conversation_id": conversation.id, "for_user": username, "mention": True},
        )
    return note


def mark_read(conversation: Conversation) -> None:
    meta = sla.meta_for(conversation)
    meta.unread_count = 0
    meta.last_read_at = timezone.now()
    meta.save(update_fields=["unread_count", "last_read_at"])


def close(conversation: Conversation, user: User | None = None) -> Conversation:
    from . import surveys

    conversation.state = Conversation.State.RESOLVED
    ai_retry.clear_failed(conversation)
    conversation.save(update_fields=["state", "updated_at", *ai_retry.CLEAR_FIELDS])
    meta = sla.meta_for(conversation)
    meta.resolved_at = timezone.now()
    meta.waiting_since = None
    meta.sla_due_at = None
    meta.save(update_fields=["resolved_at", "waiting_since", "sla_due_at"])
    events.emit(conversation.store, "conversation.closed", {
        "conversation_id": conversation.id, "by": user.username if user else "",
    })
    surveys.schedule(conversation, closed_by=user)
    return conversation
