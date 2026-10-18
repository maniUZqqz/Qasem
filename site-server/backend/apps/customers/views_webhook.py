"""The endpoint a platform posts to. See `webhooks.py` for why it exists.

It does as little as possible and then returns. Telegram gives a webhook a few
seconds before it calls the delivery failed and retries; Meta is stricter and
will disable a webhook that keeps timing out. An LLM turn does not fit in that
budget on a bad day, so the message is stored, `200` goes back, and the agent
runs after.

**Always 200, except for a caller that failed verification.** A platform that
gets anything else retries, backs off, and eventually stops delivering — so a
payload we do not understand, a duplicate, or a message on a conversation a
human has taken over are all "thank you, received". The refusals are 403, and
they say nothing about which check failed.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db import close_old_connections
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from services.ai.gateway import PolicyBlocked
from services.ai.ollama import OllamaError

from . import webhooks
from .models import Conversation, Message, Notification, notify
from .turn import answer

logger = logging.getLogger(__name__)


def _respond_later(conversation_id: int, text: str, message_id: int | None = None) -> None:
    """Run the agent for a message already stored.

    Celery when there is a broker, inline when there is not. Development runs
    with `CELERY_TASK_ALWAYS_EAGER`, and a webhook that only works with a
    worker running is one nobody can try out.
    """
    from .tasks import answer_inbound

    answer_inbound.delay(conversation_id, text, message_id)


@method_decorator(csrf_exempt, name="dispatch")
class InboundWebhook(View):
    """`/api/v1/webhooks/<channel>/<secret>/` — one message in.

    A plain Django view, not DRF: the body has to be read as raw bytes to check
    Meta's signature over exactly what was sent, and DRF has already parsed and
    thrown those bytes away by the time a handler runs.
    """

    def get(self, request, channel, secret):
        """Meta's subscription handshake.

        Meta verifies a webhook by asking for it with a challenge before it
        will send anything. Telegram has no handshake, so this is a 404 there
        rather than a pretend success.
        """
        if channel not in ("instagram", "whatsapp"):
            return HttpResponse(status=404)
        try:
            webhooks.store_for(secret)
        except webhooks.WebhookRefused:
            return HttpResponse(status=403)

        expected = settings.UPMARKET_AI.get("META_VERIFY_TOKEN", "")
        given = request.GET.get("hub.verify_token", "")
        if not expected or given != expected:
            return HttpResponse(status=403)
        return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")

    def post(self, request, channel, secret):
        if channel not in webhooks.CHANNELS:
            return HttpResponse(status=404)

        body = request.body
        try:
            store = webhooks.store_for(secret)
            webhooks.verify(channel, store, body, request.headers)
        except webhooks.WebhookRefused as exc:
            logger.warning("Webhook refused on %s: %s", channel, exc)
            return HttpResponse(status=403)

        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            # Not a retry-worthy failure: the same bytes will not parse next
            # time either.
            return JsonResponse({"ok": True, "ignored": "unparseable"})

        channel_key = webhooks.CHANNELS[channel]
        accepted = 0
        for inbound in webhooks.parse(channel, payload):
            message = webhooks.deliver(store, channel_key, inbound)
            if message is None:
                continue  # already delivered
            accepted += 1
            conversation = message.conversation
            # A thread a person took over must not get an AI reply on top of
            # theirs — the customer would get two answers from "one" shop.
            # A photo still goes through: downloading it and filing it as a
            # receipt is bookkeeping, not an answer, and it must happen even
            # while a human is handling the conversation.
            if conversation.state == Conversation.State.AI or inbound.image:
                _respond_later(conversation.id, inbound.text, message.id)

        return JsonResponse({"ok": True, "accepted": accepted})


def run_agent_for(conversation_id: int, text: str, message_id: int | None = None) -> None:
    """The body of the task, importable without Celery.

    Failure here is the shop's problem to see, not the platform's to retry: the
    message is already stored, so the owner can answer it by hand from the
    inbox. Telling the platform it failed would only produce a duplicate.
    """
    close_old_connections()
    try:
        conversation = Conversation.objects.select_related("store").get(pk=conversation_id)
    except Conversation.DoesNotExist:
        return

    # A payment slip, before anything else. It is filed even on a thread a
    # human has taken over, and it never waits behind a model call.
    if message_id is not None:
        receipt = _file_receipt(conversation, message_id)
        if receipt is not None and not text.strip():
            # A photo with no words needs no answer from the agent — the
            # acknowledgement has already gone out.
            return

    if conversation.state != Conversation.State.AI:
        return

    store = conversation.store
    try:
        turn = answer(conversation, text)
    except PolicyBlocked as exc:
        notify(
            store,
            Notification.Type.AI_ERROR,
            "سیاست داده‌ی فروشگاه جلوی پاسخ AI را گرفت",
            body=f"گفتگو #{conversation.id}: {exc}",
            link=f"/stores/{store.id}/data",
            context={"conversation_id": conversation.id, "policy": True},
        )
        return
    except OllamaError as exc:
        notify(
            store,
            Notification.Type.AI_ERROR,
            "AI به پیام مشتری جواب نداد — مشتری منتظر است",
            body=f"گفتگو #{conversation.id}: {exc}",
            link=f"/stores/{store.id}/inbox",
            context={"conversation_id": conversation.id},
        )
        return

    _send(conversation, turn.reply)


def _file_receipt(conversation: Conversation, message_id: int):
    """Turn an image on this message into a payment receipt, if it is one.

    Never raises: a shop whose Telegram is briefly unreachable must still get
    the customer's question answered, and the owner is told separately when a
    download fails.
    """
    from . import receipts

    message = Message.objects.filter(pk=message_id, conversation=conversation).first()
    if message is None or not (message.grounding or {}).get("image"):
        return None
    try:
        receipt = receipts.absorb(message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not file the receipt image: %s", exc)
        return None
    if receipt is not None:
        try:
            receipts.acknowledge(conversation, receipt.order)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Receipt stored but the customer was not told: %s", exc)
    return receipt


def _send(conversation: Conversation, reply: str) -> None:
    """Deliver the reply on the channel it came in on.

    A send that fails is recorded on the message rather than raised: the reply
    is already in the inbox, and the owner pressing "send" by hand is a better
    outcome than a traceback nobody reads.
    """
    from services.publishing import channels

    try:
        outcome = channels.send(
            conversation.channel, conversation.store,
            to=conversation.external_id, text=reply,
        )
    except Exception as exc:  # noqa: BLE001 - never lose a stored reply
        logger.warning("Could not deliver reply on %s: %s", conversation.channel, exc)
        # The same two keys `channels.send` returns. They used to be `ok` and
        # `error` here, which no sender has ever returned: every successful
        # reply raised "پاسخ ساخته شد ولی فرستاده نشد", and a real failure
        # showed an empty reason because the text lives in `reason`.
        outcome = {"sent": False, "reason": str(exc)}

    if not outcome.get("sent"):
        notify(
            conversation.store,
            Notification.Type.AI_ERROR,
            "پاسخ ساخته شد ولی فرستاده نشد",
            body=f"گفتگو #{conversation.id} — {outcome.get('reason', '')}"[:300],
            link=f"/stores/{conversation.store.id}/inbox",
            context={"conversation_id": conversation.id},
        )
