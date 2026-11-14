"""When the AI could not answer a customer: say so, and answer when it can.

Before this module a failed agent turn did exactly one thing — it created a
notification. The conversation itself stayed `AI` with the customer's message
last, the inbox counted «۰ نفر منتظر جواب», and when the GPU node or the cloud
API came back nothing ever looked at that customer again (live: two threads
stayed unanswered while 181 of 268 AI requests of one store had failed).

What this adds, in the order a thread goes through it:

1. **Record** — `mark_failed()` stamps the conversation (`ai_failed_at` and a
   Persian one-line reason). The inbox counts it as waiting, sorts it with the
   longest waits and badges it «AI جواب نداد».
2. **Acknowledge, once** — `send_ack()` sends one neutral «پیام شما رسید» so a
   real customer is not left in silence. It promises nothing about time or
   content, goes out at most once per thread, and is skipped for the panel's
   test chat.
3. **Retry when the AI is back** — `run_cycle()` (a beat task) asks the router
   whether any AI path is usable *right now* (no network, no queue) and only
   then re-runs the agent for threads younger than the window. While the AI is
   still down it does nothing — no attempt, no counter, no noise.
4. **Hand over, never drop** — past the window, or after too many failed
   attempts with the AI up, the thread becomes `ESCALATED` («منتظر انسان») with
   a notification, instead of waiting for a model that is never going to be fine.

Test conversations (the panel's «چت آزمایشی») are visible in the inbox but are
never retried or escalated automatically: the owner is looking at that page
and re-sends from it, and a test chat nobody answers is not a lost customer.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from services.ai import gateway
from services.ai.gateway import PolicyBlocked
from services.ai.ollama import OllamaError

from . import links
from .models import Conversation, Message, Notification, notify

logger = logging.getLogger(__name__)

#: What the customer is told while the AI is down. Neutral on purpose: no
#: promise about when, no claim about what was understood.
ACK_TEXT = "پیام شما رسید. همکاران ما در اولین فرصت پاسخ می‌دهند."
#: Marks that stored message as an acknowledgement (not an answer), so the
#: retry logic and the inbox preview can look through it.
ACK_MARK = "ai_failed_ack"
#: Set on a bare photo that was filed as a payment receipt (nothing to answer).
RECEIPT_MARK = "receipt_filed"

#: Columns `clear_failed` resets — pass these to `save(update_fields=...)`.
CLEAR_FIELDS = ["ai_failed_at", "ai_failed_reason", "ai_retries", "ai_retry_at", "ai_ack_at"]

_DEFAULTS = {
    # How long a failed thread is retried before it is handed to a person.
    "WINDOW_HOURS": 12.0,
    # Agent runs per beat tick — each can take minutes on a local model.
    "PER_RUN": 3,
    # Minimum time between two automatic attempts on the same thread.
    "GAP_MINUTES": 5.0,
    # Attempts made with the AI *up* before giving up and escalating.
    "MAX_ATTEMPTS": 6,
    # A turn that stored nothing for this long is considered lost (the worker
    # died, the broker dropped the task) rather than still running.
    "ORPHAN_GRACE_MINUTES": 10.0,
    "SEND_ACK": True,
}


def config() -> dict:
    out = dict(_DEFAULTS)
    out.update(getattr(settings, "CUSTOMER_AI_RETRY", {}) or {})
    return out


# ----------------------------------------------------------------- recording
def failure_reason(exc: BaseException | None) -> str:
    """One Persian sentence for the owner — never a traceback."""
    if exc is None:
        return "پاسخی برای این پیام ثبت نشد."
    if isinstance(exc, PolicyBlocked):
        return ("سیاست داده‌ی فروشگاه جلوی پاسخ AI را گرفت — " + str(exc))[:300]
    if isinstance(exc, OllamaError):
        return (str(exc) or "هوش مصنوعی در دسترس نبود.")[:300]
    return "خطای پیش‌بینی‌نشده هنگام ساختن پاسخ؛ جزئیات در لاگ سرور است."


def mark_failed(conversation: Conversation, exc: BaseException | None, *, retry: bool = False) -> None:
    """Record that the agent could not answer this thread. Never raises.

    `retry=True` is an automatic re-attempt that failed again: the *first*
    failure time is kept (it is when the customer started waiting) and only the
    attempt count and the reason move.
    """
    if conversation.state != Conversation.State.AI:
        return
    now = timezone.now()
    try:
        if retry:
            conversation.ai_retries = (conversation.ai_retries or 0) + 1
            conversation.ai_failed_at = conversation.ai_failed_at or now
        else:
            conversation.ai_failed_at = now
        conversation.ai_failed_reason = failure_reason(exc)
        conversation.save(update_fields=[
            "ai_failed_at", "ai_failed_reason", "ai_retries", "updated_at",
        ])
    except Exception:  # pragma: no cover - the customer-facing flow must go on
        logger.exception("Could not record the AI failure on conversation %s", conversation.pk)


def clear_failed(conversation: Conversation) -> bool:
    """Nothing is owed any more (answered, or a person took over).

    Changes the instance only — the caller saves (with `CLEAR_FIELDS` among its
    `update_fields`). Returns whether anything was set.
    """
    was = conversation.ai_failed_at is not None
    conversation.ai_failed_at = None
    conversation.ai_failed_reason = ""
    conversation.ai_retries = 0
    conversation.ai_retry_at = None
    conversation.ai_ack_at = None
    return was


# ------------------------------------------------------------------ the thread
def _is_ack(message: Message) -> bool:
    return bool((message.grounding or {}).get(ACK_MARK))


def pending_customer_message(conversation: Conversation) -> Message | None:
    """The customer message nobody has answered, or None.

    "Answered" means a person or the AI wrote after it. Our own
    acknowledgement does not count — it is exactly what is sent *because* the
    answer is missing. A bare payment-slip photo does not need an answer at all:
    it is filed as a receipt and acknowledged (`mark_receipt_filed`), which
    leaves no reply message behind — without this it would look «unanswered»
    ten minutes later and trigger a false «AI جواب نداد».
    """
    for message in conversation.messages.order_by("-created_at", "-id")[:12]:
        if _is_ack(message):
            continue
        if message.role != Message.Role.CUSTOMER:
            return None
        return None if (message.grounding or {}).get(RECEIPT_MARK) else message
    return None


def mark_receipt_filed(message_id: int) -> None:
    """A photo with no words was filed as a payment receipt: nothing is owed."""
    message = Message.objects.filter(pk=message_id).first()
    if message is None:
        return
    grounding = dict(message.grounding or {})
    grounding[RECEIPT_MARK] = True
    message.grounding = grounding
    message.save(update_fields=["grounding"])


def last_visible_message(conversation: Conversation) -> Message | None:
    """The last message worth showing in a list — acknowledgements are not."""
    for message in conversation.messages.order_by("-created_at", "-id")[:6]:
        if not _is_ack(message):
            return message
    return None


# ------------------------------------------------------------ acknowledgement
def send_ack(conversation: Conversation) -> bool:
    """Tell a real customer their message arrived. Once, neutral, never raises."""
    if conversation.ai_ack_at is not None or conversation.is_test:
        return False
    if not config().get("SEND_ACK", True):
        return False
    try:
        from services.publishing import channels

        outcome = channels.send(
            conversation.channel, conversation.store,
            to=conversation.external_id or str(conversation.customer_id), text=ACK_TEXT,
        )
        if not outcome.get("sent"):
            logger.info("AI-failure acknowledgement not delivered on %s: %s",
                        conversation.channel, outcome.get("reason"))
            return False
        Message.objects.create(
            conversation=conversation, role=Message.Role.AI, text=ACK_TEXT,
            intent="ack", grounding={ACK_MARK: True},
        )
        conversation.ai_ack_at = timezone.now()
        conversation.save(update_fields=["ai_ack_at", "updated_at"])
        return True
    except Exception:  # pragma: no cover - best effort
        logger.exception("Could not send the AI-failure acknowledgement")
        return False


# ----------------------------------------------------------------- availability
def ai_available(store) -> tuple[bool, str]:
    """Can *any* AI path answer a customer right now? Asks, does not try.

    The router answers from rows it already holds (node heartbeat, circuit
    breakers, whether the cloud path is configured and allowed by the shop's
    data policy) — no request leaves the server, so the beat can call this for
    every waiting thread without cost.
    """
    try:
        provider = gateway.text_provider(store, gateway.CUSTOMER)
        check = getattr(provider, "availability", None)
        if check is None:
            return True, ""
        ok, why = check()
        return bool(ok), str(why or "")
    except PolicyBlocked as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.info("AI availability could not be determined: %s", exc)
        return False, str(exc)


# ----------------------------------------------------------------------- retry
def retry_one(conversation: Conversation) -> str:
    """Run the agent again for the customer's unanswered message.

    "answered" | "failed" | "cleared" (nothing was owed after all) | "skipped".
    """
    from .views_webhook import run_agent_for

    if conversation.state != Conversation.State.AI:
        return "skipped"
    message = pending_customer_message(conversation)
    if message is None:
        clear_failed(conversation)
        conversation.save(update_fields=CLEAR_FIELDS + ["updated_at"])
        return "cleared"
    return run_agent_for(conversation.pk, message.text, None, retry=True)


def _claim(conversation: Conversation, now) -> bool:
    """Take this thread for one attempt; False when another worker has it.

    A conditional UPDATE on the old `ai_retry_at`: of two workers that read the
    same row, exactly one changes it.
    """
    updated = Conversation.objects.filter(
        pk=conversation.pk, state=Conversation.State.AI, ai_retry_at=conversation.ai_retry_at,
    ).update(ai_retry_at=now)
    if updated:
        conversation.ai_retry_at = now
    return bool(updated)


def _flag_unanswered(now, window_start, grace) -> int:
    """Threads where the agent never recorded anything (worker died mid-turn)."""
    flagged = 0
    candidates = (
        Conversation.objects
        .filter(state=Conversation.State.AI, ai_failed_at__isnull=True,
                last_customer_at__gte=window_start, last_customer_at__lte=now - grace)
        .select_related("store", "customer")
        .order_by("last_customer_at")[:100]
    )
    for conversation in candidates:
        if pending_customer_message(conversation) is None:
            continue
        mark_failed(conversation, None)
        if not conversation.is_test:
            # A test chat is flagged (the inbox should show it) but never
            # announced: its owner is the person looking at the screen.
            announce_failure(conversation)
            send_ack(conversation)
        flagged += 1
    return flagged


def announce_failure(conversation: Conversation) -> None:
    """The owner's bell: a customer is waiting and the AI did not answer."""
    notify(
        conversation.store,
        Notification.Type.AI_ERROR,
        "AI به پیام مشتری جواب نداد — مشتری منتظر است",
        body=f"گفتگو #{conversation.id}: {conversation.ai_failed_reason}"[:300],
        link=links.conversation_link(conversation),
        context={"conversation_id": conversation.id},
    )


def escalate(conversation: Conversation, why: str) -> None:
    """Give the thread to a person: it becomes «منتظر انسان» in the inbox."""
    clear_failed(conversation)
    conversation.state = Conversation.State.ESCALATED
    conversation.save(update_fields=CLEAR_FIELDS + ["state", "updated_at"])
    notify(
        conversation.store,
        Notification.Type.ESCALATION,
        f"گفتگو #{conversation.id} به انسان ارجاع شد",
        body=why[:300],
        link=links.conversation_link(conversation),
        context={"conversation_id": conversation.id, "ai_failed": True},
    )


def run_cycle(now=None) -> dict:
    """One beat tick. Cheap when the AI is down, bounded when it is up."""
    cfg = config()
    now = now or timezone.now()
    window_start = now - timedelta(hours=float(cfg["WINDOW_HOURS"]))
    gap = timedelta(minutes=float(cfg["GAP_MINUTES"]))
    summary = {"flagged": 0, "escalated": 0, "retried": 0, "answered": 0, "failed": 0,
               "waiting_for_ai": 0}

    summary["flagged"] = _flag_unanswered(
        now, window_start, timedelta(minutes=float(cfg["ORPHAN_GRACE_MINUTES"])),
    )

    failed = (
        Conversation.objects
        .filter(state=Conversation.State.AI, ai_failed_at__isnull=False)
        .exclude(customer__channel="web-test")
        .select_related("store", "customer")
        .order_by("last_customer_at", "id")
    )

    # Hand over what has waited too long, or has failed too often with the AI up.
    for conversation in failed.filter(
        Q(last_customer_at__lt=window_start)
        | Q(ai_retries__gte=int(cfg["MAX_ATTEMPTS"]))
    )[:50]:
        escalate(
            conversation,
            "AI در این مدت جواب نداد؛ لطفاً خودتان به مشتری پاسخ بدهید."
            if (conversation.ai_retries or 0) < int(cfg["MAX_ATTEMPTS"])
            else "AI چند بار تلاش کرد و نتوانست جواب بدهد؛ لطفاً خودتان پاسخ بدهید.",
        )
        summary["escalated"] += 1

    down: set[int] = set()
    for conversation in failed.filter(last_customer_at__gte=window_start)[:50]:
        if summary["retried"] >= int(cfg["PER_RUN"]):
            break
        if conversation.ai_retry_at and conversation.ai_retry_at > now - gap:
            continue
        if conversation.store_id in down:
            summary["waiting_for_ai"] += 1
            continue
        ok, _why = ai_available(conversation.store)
        if not ok:
            down.add(conversation.store_id)
            summary["waiting_for_ai"] += 1
            continue
        if not _claim(conversation, now):
            continue
        summary["retried"] += 1
        outcome = retry_one(conversation)
        if outcome == "answered":
            summary["answered"] += 1
        elif outcome == "failed":
            summary["failed"] += 1
    return summary
