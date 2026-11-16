"""Bookkeeping that must happen no matter which door a message came through.

Why signals and not calls from the views: Telegram and Instagram messages enter
through `apps.customers.views_webhook`, the panel's test chat through
`ChatView`, the sales agent's own tools through `agent.py` - and none of them
know the inbox exists. A `post_save` on `Message` / `Conversation` is the one
place all of them pass, so the unread counter, the SLA clock, reopening a closed
thread, auto-assignment and the outgoing webhooks work for every channel
without a line changed in `apps.customers`.

The handlers do only database work. Anything that talks to the network (a
webhook delivery, an off-hours notice) is queued after the transaction commits.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.customers.models import Conversation, Message

logger = logging.getLogger(__name__)

OPEN = (Conversation.State.HUMAN, Conversation.State.ESCALATED)

_local = threading.local()


@contextmanager
def suppressed():
    """No inbox bookkeeping inside this block (demo seeding, imports, repairs).

    A conversation exists a moment before its meta row can say "this is a test",
    so seeding test data under this guard is how it stays silent: no webhook, no
    SLA clock, no assignment.
    """
    previous = getattr(_local, "off", False)
    _local.off = True
    try:
        yield
    finally:
        _local.off = previous


def _off() -> bool:
    return getattr(_local, "off", False)


def _is_test(conversation: Conversation) -> bool:
    from . import sla

    return bool(conversation.pk) and sla.is_test(conversation)


@receiver(pre_save, sender=Conversation)
def remember_old_state(sender, instance, **kwargs):
    instance._inbox_old_state = None
    if instance.pk:
        instance._inbox_old_state = (
            Conversation.objects.filter(pk=instance.pk).values_list("state", flat=True).first()
        )


@receiver(post_save, sender=Conversation)
def on_conversation_saved(sender, instance, created, **kwargs):
    if kwargs.get("raw") or _off():
        return
    try:
        _conversation_saved(instance, created)
    except Exception:  # noqa: BLE001 - bookkeeping must never break a save
        logger.exception("inbox: conversation hook failed for %s", instance.pk)


def _conversation_saved(conversation: Conversation, created: bool) -> None:
    from . import events, sla, team

    old = getattr(conversation, "_inbox_old_state", None)
    new = conversation.state
    if created:
        if not _is_test(conversation):
            events.emit(conversation.store, "conversation.created", {
                "conversation_id": conversation.id, "channel": conversation.channel,
                "customer": conversation.customer.name,
            })
        return
    if old is None or old == new or new not in OPEN:
        return
    # The thread just came into a person's hands (a handoff, or a colleague
    # taking it over): the customer is waiting for a human from now on.
    if _is_test(conversation):
        return
    last = conversation.messages.order_by("-created_at", "-id").first()
    # A handoff to ESCALATED always means "a person is needed now" (the bot's
    # last line may be a withheld draft, which the customer never saw). A plain
    # take-over by a colleague only starts the clock if the customer is the one
    # who spoke last.
    if new == Conversation.State.ESCALATED or last is None or last.role == Message.Role.CUSTOMER:
        sla.start(conversation)
    cfg = team.settings_for(conversation.store)
    assigned = team.assign(conversation) if not conversation.assigned_to_id else conversation.assigned_to
    if new == Conversation.State.ESCALATED:
        events.emit(conversation.store, "conversation.handoff", {
            "conversation_id": conversation.id, "channel": conversation.channel,
            "assigned_to": assigned.username if assigned else "",
            "reason": getattr(getattr(conversation, "inbox_meta", None), "handoff_reason", ""),
        })
    if assigned is not None:
        events.emit(conversation.store, "conversation.assigned", {
            "conversation_id": conversation.id, "assigned_to": assigned.username,
            "mode": cfg.assignment_mode,
        })


@receiver(post_save, sender=Message)
def on_message_saved(sender, instance, created, **kwargs):
    if not created or kwargs.get("raw") or _off():
        return
    try:
        if instance.role == Message.Role.CUSTOMER:
            _customer_message(instance)
        elif instance.role == Message.Role.AI:
            _ai_message(instance)
    except Exception:  # noqa: BLE001
        logger.exception("inbox: message hook failed for %s", instance.pk)


def _customer_message(message: Message) -> None:
    from . import bot, events, sla, team

    conversation = message.conversation
    store = conversation.store
    test = _is_test(conversation)
    meta = sla.meta_for(conversation)
    meta.unread_count += 1
    meta.save(update_fields=["unread_count"])

    if conversation.state == Conversation.State.RESOLVED:
        # A closed thread that gets a new message is a new problem on an old
        # thread - reopen it, otherwise the customer writes into silence (the
        # AI skips anything that is not in the AI state).
        cfg = team.settings_for(store)
        conversation.state = (
            Conversation.State.AI if cfg.bot_enabled else Conversation.State.ESCALATED
        )
        conversation.save(update_fields=["state", "updated_at"])
        meta.resolved_at = None
        meta.reopened_count += 1
        meta.save(update_fields=["resolved_at", "reopened_count"])
        if not test:
            events.emit(store, "conversation.reopened", {"conversation_id": conversation.id})

    if not test:
        events.emit(store, "message.received", {
            "conversation_id": conversation.id, "message_id": message.id,
            "channel": conversation.channel, "text": message.text,
            "customer": {"id": conversation.customer_id, "name": conversation.customer.name},
        })

    if conversation.state == Conversation.State.AI:
        bot.gate(conversation, message)
    elif conversation.state in OPEN and not test:
        # A person owes the answer; this message restarts or continues the wait.
        sla.start(conversation)
        team.assign(conversation)

    if not test and conversation.state == Conversation.State.AI:
        cfg = team.settings_for(store)
        if cfg.assign_when == "ALWAYS" and not conversation.assigned_to_id:
            team.assign(conversation)


def _ai_message(message: Message) -> None:
    from . import events

    conversation = message.conversation
    if _is_test(conversation):
        return
    if getattr(message, "_inbox_skip", False):
        return  # written by replies.system_reply, which says what it is
    events.emit(conversation.store, "message.sent", {
        "conversation_id": conversation.id, "message_id": message.id,
        "by": "bot", "channel": conversation.channel, "text": message.text,
    })
