"""One agent turn, recorded — for whoever asked.

`ChatView` grew this inline: run the agent, store the reply, raise the
notifications, escalate if the model asked for a person. That was fine while
the panel's test chat was the only way in. It stopped being fine the moment a
webhook could deliver a message too, because then the same hundred lines would
exist twice, and the copy that drifts is the one nobody is looking at — the one
answering real customers on Telegram.

So the *behaviour* moved here and `ChatView` kept the *HTTP*. The view still
maps `PolicyBlocked` to 409 and `OllamaError` to 503 exactly as before; what it
no longer owns is what an answered message does to the database.

**This deliberately does not send anything.** Writing the reply and delivering
it are separate: a reply that is stored but undelivered can be retried or sent
by hand, while a reply that was delivered but not stored is invisible in the
inbox and gets answered a second time by a person.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .agent import run_sales_agent
from .models import Conversation, Message, Notification, SupportTicket, notify

logger = logging.getLogger(__name__)


@dataclass
class Turn:
    """What the agent did, for a caller that has to describe it."""

    message: Message
    result: dict

    @property
    def reply(self) -> str:
        return self.result["reply"]

    @property
    def escalated(self) -> bool:
        return bool(self.result["needs_human"])


def answer(conversation: Conversation, text: str) -> Turn:
    """Run the agent for `text` and record everything that follows.

    Raises whatever `run_sales_agent` raises — `PolicyBlocked` and the
    `OllamaError` family. Callers map those to their own surface, because "the
    shop's data policy blocked this" and "the model is down" need different
    answers and conflating them sends somebody hunting a fault that does not
    exist.
    """
    store = conversation.store
    result = run_sales_agent(conversation, text)

    message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.AI,
        text=result["reply"],
        intent=result["intent"],
        grounding={
            "action": result["action"],
            "product_ids": result["product_ids"],
            "confidence": result["confidence"],
            "order_id": result["order"].id if result["order"] else None,
            "order_error": result["order_error"],
            "payment_request": result.get("payment_request"),
            "ticket_id": result["ticket"].id if result.get("ticket") else None,
        },
        ai_request=result["ai_request"],
    )

    if result["order"]:
        notify(
            store,
            Notification.Type.ORDER,
            f"سفارش پیش‌نویس #{result['order'].id} ثبت شد",
            body=f"جمع: {result['order'].total} — گفتگو #{conversation.id}",
            link=f"/stores/{store.id}/sales",
            context={"order_id": result["order"].id},
        )
    if result.get("ticket"):
        urgent = result["ticket"].priority == SupportTicket.Priority.URGENT
        notify(
            store,
            Notification.Type.TICKET,
            ("🔴 تیکت فوری: " if urgent else "تیکت پشتیبانی: ") + result["ticket"].subject,
            body=result["ticket"].description,
            link=f"/stores/{store.id}/sales",
            context={"ticket_id": result["ticket"].id},
        )
    if result["needs_human"]:
        conversation.state = Conversation.State.ESCALATED
        notify(
            store,
            Notification.Type.ESCALATION,
            f"گفتگو #{conversation.id} به انسان ارجاع شد",
            body=f"آخرین پیام مشتری: {text[:200]}",
            link=f"/stores/{store.id}/chat",
            context={"conversation_id": conversation.id},
        )
    conversation.save()

    return Turn(message=message, result=result)
