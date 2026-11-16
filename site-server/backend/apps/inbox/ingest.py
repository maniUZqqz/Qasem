"""One door for every inbound message: webhook, poller, widget, SMS, API.

The existing `apps.customers.webhooks.deliver` already does the hard, correct
part - idempotent on the platform's message id, one customer per sender, one
conversation per thread. `receive` wraps it and adds what the unified inbox
needs on top:

* the contact (cross-channel identity) and its last-activity stamp,
* the connection's counters ("last message 2 minutes ago" on the connect page),
* opt-out / opt-in words and survey answers, which are *not* conversation,
* then hands the message to the bot - which may hand it straight to a person.

The conversation bookkeeping (unread counts, SLA clock, reopening, assignment,
webhooks) is **not** here: it lives in `signals.py`, on the `Message` row, so the
old Telegram/Instagram webhook - which never calls this module - gets it too.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.utils import timezone

from apps.customers import webhooks
from apps.customers.models import Conversation, Customer, Message

from . import contacts, norm
from .adapters.base import Incoming
from .models import ChannelConnection, ConversationMeta

logger = logging.getLogger(__name__)


@dataclass
class Received:
    message: Message | None  # None = duplicate delivery
    conversation: Conversation | None
    customer: Customer | None
    handled: str = ""  # "", "opt_out", "opt_in", "survey"


def _to_inbound(incoming: Incoming) -> webhooks.Inbound:
    return webhooks.Inbound(
        external_id=incoming.external_id,
        thread_id=incoming.thread_id,
        sender_id=incoming.sender_id,
        name=incoming.name or incoming.username,
        text=incoming.text,
        image=incoming.image,
    )


def receive(connection: ChannelConnection, incoming: Incoming, *, is_test: bool = False) -> Received:
    """Store one inbound message and run the unified-inbox side effects."""
    from . import signals

    store = connection.store
    channel_key = connection.kind
    # This door handles «relationship» messages itself (below); the message
    # signal must not do it a second time.
    with signals.via_ingest():
        message = webhooks.deliver(store, channel_key, _to_inbound(incoming))
    if message is None:
        return Received(None, None, None)
    conversation = message.conversation
    customer = conversation.customer
    now = timezone.now()

    contact = contacts.identify(
        customer, phone=incoming.phone, username=incoming.username, name=incoming.name,
        source=channel_key.lower(), is_test=is_test,
    )
    if is_test:
        ConversationMeta.objects.update_or_create(
            conversation=conversation, defaults={"store": store, "is_test": True},
        )
        if not contact.is_test:
            contact.is_test = True
            contact.save(update_fields=["is_test", "updated_at"])

    connection.last_inbound_at = now
    connection.inbound_count += 1
    connection.save(update_fields=["last_inbound_at", "inbound_count", "updated_at"])

    handled = handle_relationship(conversation, message, contact=contact)
    return Received(message, conversation, customer, handled)


def relationship_kind(conversation: Conversation, message: Message) -> str:
    """`survey`, `opt_out`, `opt_in` or `''` - a look at the message, no side effects.

    These messages are about the relationship, not the conversation: a customer
    answering the satisfaction survey or writing «لغو» is not a new problem on a
    closed thread. `signals` asks this so such a message never reopens the thread,
    never lights the team's unread counter and never reaches the bot; the handler
    below then does the actual work.
    """
    from . import surveys

    if surveys.is_answer(conversation, message):
        return "survey"
    return {"out": "opt_out", "in": "opt_in"}.get(contacts.opt_word(message.text), "")


def handle_relationship(conversation: Conversation, message: Message, *, contact=None) -> str:
    """Do what a relationship message asks. Returns the kind handled, or ''."""
    from . import surveys

    kind = relationship_kind(conversation, message)
    if kind == "survey":
        return "survey" if surveys.try_answer(conversation, message) else ""
    if not kind:
        return ""
    from . import events, sla
    from .replies import system_reply

    if contact is None:
        contact = contacts.identify(
            conversation.customer, source=conversation.channel.lower(), is_test=sla.is_test(conversation),
        )
    if kind == "opt_out":
        contacts.set_opt_out(contact, "ALL", True)
        events.emit(conversation.store, "contact.opted_out", {"contact_id": contact.pk, "channel": conversation.channel})
        system_reply(
            conversation,
            "از لیست پیام‌های تبلیغاتی خارج شدید و دیگر پیام گروهی دریافت نمی‌کنید. "
            "پاسخ سؤال‌های شما همچنان داده می‌شود. برای بازگشت بنویسید «عضویت».",
            kind="SYSTEM",
        )
        return "opt_out"
    contacts.set_opt_out(contact, "ALL", False)
    system_reply(conversation, "دوباره عضو شدید؛ از اخبار و پیشنهادهای ما باخبر می‌شوید.", kind="SYSTEM")
    return "opt_in"


def poll_connection(connection: ChannelConnection) -> dict:
    """Pull new messages for a polling channel. One cursor, no duplicates."""
    from . import dispatch

    adapter = dispatch.adapter_for(connection)
    if adapter is None or not adapter.can_poll:
        return {"polled": False, "reason": "این کانال پرسش دوره‌ای ندارد."}
    now = timezone.now()
    try:
        result = adapter.poll(connection.poll_cursor)
    except Exception as exc:  # noqa: BLE001 - AdapterError or anything else
        connection.last_error = str(exc)[:300]
        connection.last_error_at = now
        connection.health_ok = False
        connection.health_detail = connection.last_error
        connection.last_poll_at = now
        connection.save(update_fields=[
            "last_error", "last_error_at", "health_ok", "health_detail", "last_poll_at", "updated_at",
        ])
        return {"polled": False, "reason": connection.last_error}
    accepted = 0
    for incoming in result.messages:
        outcome = receive(connection, incoming)
        if outcome.message is not None:
            accepted += 1
            _answer_later(outcome)
    connection.poll_cursor = result.cursor or connection.poll_cursor
    connection.last_poll_at = now
    connection.health_ok = True
    connection.last_error = ""
    connection.last_error_at = None
    connection.save(update_fields=["poll_cursor", "last_poll_at", "health_ok", "last_error", "last_error_at", "updated_at"])
    return {"polled": True, "received": len(result.messages), "accepted": accepted}


def answer_later(outcome: Received) -> None:
    _answer_later(outcome)


def _answer_later(outcome: Received) -> None:
    """Ask the AI to reply - only when the bot owns the thread and nothing special happened."""
    if outcome.message is None or outcome.handled:
        return
    conversation = outcome.conversation
    # The signal may have handed the thread to a person (keyword, off hours,
    # bot disabled) - re-read rather than trust the in-memory copy.
    conversation.refresh_from_db(fields=["state"])
    if conversation.state != Conversation.State.AI and not (outcome.message.grounding or {}).get("image"):
        return
    from apps.customers.views_webhook import _respond_later

    _respond_later(conversation.id, outcome.message.text, outcome.message.id)


def text_of(value) -> str:
    return norm.ascii_digits(str(value or "")).strip()
