"""When the AI answers, and when a person must.

The answering itself is the existing sales agent (`apps.customers.turn.answer`):
it reads the store's own knowledge - products, policies, brand voice - and goes
through the AI gateway, so the store's **data policy (local-only)** is enforced
there, not here. This module is the *gate in front of it* and the *handoff
behind it*:

before the agent runs (`gate`)
    * the bot is switched off for this store          -> a person
    * the customer asked for a person («اپراتور»…)    -> a person
    * the shop is closed and the store chose a queue  -> a person, with an
      off-hours notice when the store wants one

after the agent ran (`check_answer`)
    * its confidence is below the store's threshold   -> a person

A handoff is a state change (`ESCALATED`) plus a *reason*; the SLA clock,
assignment and the outgoing webhook all hang off that transition in
`signals.py`, so a handoff started here, by the agent's own tool, or by a
colleague clicking "take over" behaves identically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from apps.customers import links
from apps.customers.models import Conversation, Message, Notification, notify

from . import hours, norm, sla, team
from .models import InboxSettings

logger = logging.getLogger(__name__)

#: Whole-word requests for a human. Matched on normalised text; a customer who
#: writes «با پشتیبان صحبت کنم» is not asking the bot anything.
DEFAULT_KEYWORDS = [
    "اپراتور", "پشتیبان", "کارشناس", "مسئول", "مدیر", "آدم", "انسان",
    "صحبت با", "با یه نفر", "با یک نفر", "ربات نه", "human", "operator", "agent",
]

DEFAULT_GREETING = "سلام! من دستیار هوشمند فروشگاه هستم. هر سؤالی دارید بپرسید؛ اگر لازم شد همکارانمان ادامه می‌دهند."
DEFAULT_OFFHOURS = (
    "الان خارج از ساعت کاری ما هستیم. پیامتان ثبت شد و اولین ساعت کاری، "
    "همکارانمان پاسخ می‌دهند."
)
#: What the customer reads the moment a person is asked for (or the bot is off):
#: without it they would sit in silence until a human happens to look. No hours,
#: no promise of a time - the store did not say any. The store can replace it on
#: the Bot page (`InboxSettings.handoff_message`).
DEFAULT_HANDOFF_NOTICE = "گفتگو را به یکی از همکاران می‌سپارم؛ به‌زودی پاسخ می‌دهند."
DEFAULT_RECEIVED_NOTICE = "پیام شما رسید؛ یکی از همکاران پاسخ می‌دهد."


@dataclass
class Decision:
    action: str  # "bot" | "handoff"
    reason: str = ""
    notice: str = ""


def keywords_of(cfg: InboxSettings) -> list[str]:
    custom = [str(k).strip() for k in (cfg.bot_handoff_keywords or []) if str(k).strip()]
    return custom or DEFAULT_KEYWORDS


def wants_human(cfg: InboxSettings, text: str) -> str:
    """The keyword that asked for a person, or ''."""
    cleaned = norm.ascii_digits((text or "").lower())
    for word in keywords_of(cfg):
        if word.lower() in cleaned:
            return word
    return ""


def decide(conversation: Conversation, text: str, now=None) -> Decision:
    cfg = team.settings_for(conversation.store)
    if not cfg.bot_enabled:
        return Decision("handoff", "ربات برای این فروشگاه خاموش است", cfg.handoff_message or DEFAULT_RECEIVED_NOTICE)
    word = wants_human(cfg, text)
    if word:
        return Decision("handoff", f"مشتری آدم خواست («{word}»)", cfg.handoff_message or DEFAULT_HANDOFF_NOTICE)
    if hours.configured(cfg.working_hours) and not hours.is_open(cfg.working_hours, now):
        if cfg.bot_offhours == InboxSettings.OffHours.MESSAGE:
            return Decision("handoff", "خارج از ساعت کاری", cfg.offhours_message or DEFAULT_OFFHOURS)
        if cfg.bot_offhours == InboxSettings.OffHours.QUEUE:
            return Decision("handoff", "خارج از ساعت کاری")
    return Decision("bot")


def handoff(conversation: Conversation, reason: str, *, notice: str = "", tell_owner: bool = True) -> None:
    """Put the thread in a person's hands and say why."""
    meta = sla.meta_for(conversation)
    meta.handoff_reason = reason[:200]
    meta.save(update_fields=["handoff_reason"])
    conversation.state = Conversation.State.ESCALATED
    conversation.save(update_fields=["state", "updated_at"])  # signals start the SLA + assign
    if conversation.is_test or meta.is_test:
        return
    if tell_owner:
        notify(
            conversation.store, Notification.Type.ESCALATION,
            f"گفتگو منتظر پاسخ تیم است - {conversation.customer.name or 'مشتری'}",
            body=reason, link=links.conversation_link(conversation),
            context={"conversation_id": conversation.id, "reason": reason},
        )
    if notice:
        from . import replies

        transaction.on_commit(lambda: replies.system_reply(conversation, notice, kind="SYSTEM"))


def gate(conversation: Conversation, message: Message) -> Decision:
    """Run before the AI. Mutates the conversation when a person must answer."""
    if message.role != Message.Role.CUSTOMER:
        return Decision("bot")
    decision = decide(conversation, message.text)
    if decision.action == "handoff":
        handoff(conversation, decision.reason, notice=decision.notice)
    return decision


#: The sales agent grades itself LOW / MEDIUM / HIGH; the store's threshold is a
#: number so the settings page can be a slider and the rule stays comparable.
LEVELS = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.25}

HANDOFF_TEXT = "برای پاسخ دقیق‌تر، گفتگو را به یکی از همکاران می‌سپارم؛ به‌زودی پاسخ می‌دهند."


def level_value(confidence) -> float | None:
    if isinstance(confidence, (int, float)):
        return float(confidence)
    return LEVELS.get(str(confidence or "").upper())


def check_answer(conversation: Conversation, confidence, intent: str = "") -> bool:
    """After the agent answered: hand off when it was not sure. True = handed off."""
    cfg = team.settings_for(conversation.store)
    value = level_value(confidence)
    if value is not None:
        meta = sla.meta_for(conversation)
        meta.bot_confidence = value
        meta.save(update_fields=["bot_confidence"])
    if value is not None and value < cfg.bot_min_confidence:
        handoff(
            conversation,
            f"اطمینان ربات کم بود ({str(confidence).upper() if not isinstance(confidence, (int, float)) else value})",
            notice="",
        )
        return True
    return False


def after_turn(conversation: Conversation, turn) -> str | None:
    """Between «the agent answered» and «the answer is sent».

    Called by `apps.customers.views_webhook.run_agent_for`. Returns the text to
    send *instead* of the agent's answer, or None to send it as is. A
    low-confidence answer is **not sent**: it stays in the thread, marked
    `withheld`, as a draft the person who takes over can use or throw away -
    the customer gets the handoff line, never a guess.
    """
    if turn.escalated or conversation.state != Conversation.State.AI:
        return None  # the agent already asked for a person; its own words stand
    if not check_answer(conversation, turn.result.get("confidence"), turn.result.get("intent", "")):
        return None
    message = turn.message
    message.grounding = {**(message.grounding or {}), "withheld": True}
    message.save(update_fields=["grounding"])
    return team.settings_for(conversation.store).handoff_message or HANDOFF_TEXT
