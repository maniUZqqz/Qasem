"""Messages arriving from outside. The half of the inbox that never existed.

`services/publishing/channels.py` has said `can_receive=True` for Telegram
since it was written, and **nothing implemented it**. Messages only ever
entered through `SalesAgentAPI`, which requires the shop to run their own
system and push them in. So the shop that connected a Telegram bot got a
channel that could answer but never heard anything — which reads as a broken
integration, because it is one.

Instagram is the same shape with a different reason: its `can_receive` is
`False` and honest, because reading DMs needs Meta to approve the app. That is
a form, not a feature. The code path is identical to Telegram's, so it is built
here too and gated on a flag — the day approval lands, nothing has to be
written.

Four things this has to get right, and each one is a real failure:

**A retried delivery must not answer twice.** Every platform retries when it
does not get a fast 200, and an agent that answers the same question twice
looks broken to the customer and burns the shop's quota. So delivery is
idempotent on the platform's own message id.

**An unverified caller must not reach the agent.** The URL carries a per-store
secret and the payload carries the platform's signature; both are checked. An
endpoint that runs an LLM for anyone who finds the URL is a bill somebody else
can run up.

**It answers fast and thinks later.** Platforms time out in seconds and treat a
slow reply as a failure, so the request stores the message and returns; the
agent runs after. A webhook that waits for a model is a webhook that gets
retried while the model is still thinking.

**An unknown payload is a 200, not a 500.** Platforms send delivery receipts,
read receipts, reactions and edits down the same pipe. Erroring on them makes
the platform retry, back off, and eventually disable the webhook — losing the
messages that *were* understood.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from django.conf import settings
from django.db import transaction

from apps.stores.models import Store, StoreProfile

from .models import Conversation, Customer, Message

logger = logging.getLogger(__name__)

#: Channels that can deliver here. The key is the URL segment and the value is
#: the channel key `services.publishing.channels` already uses, so a thread
#: created by a webhook is indistinguishable from one created any other way.
CHANNELS = {
    "telegram": "TELEGRAM",
    "instagram": "INSTAGRAM",
    "whatsapp": "WHATSAPP",
}


class WebhookRefused(Exception):
    """Rejected before anything was read. Never says which check failed."""


def secret_for(store: Store) -> str:
    """This store's webhook secret, created on first use.

    In the URL rather than a header because that is the only place Telegram's
    `setWebhook` can carry one, and it is the common denominator across the
    three platforms. It is a bearer credential, so it is 32 bytes of urandom
    and the panel says out loud that the URL is one.
    """
    profile, _ = StoreProfile.objects.get_or_create(store=store)
    token = (profile.webhook_secret or "").strip()
    if not token:
        token = secrets.token_urlsafe(24)
        profile.webhook_secret = token
        profile.save(update_fields=["webhook_secret"])
    return token


def store_for(secret: str) -> Store:
    """The store that owns this secret.

    Compared in constant time against every candidate rather than looked up by
    index, because a timing difference on a bearer token is a way to find one
    character at a time.
    """
    candidate = (secret or "").strip()
    if len(candidate) < 16:
        raise WebhookRefused("bad secret")
    for profile in StoreProfile.objects.exclude(webhook_secret="").select_related("store"):
        if hmac.compare_digest(profile.webhook_secret, candidate):
            return profile.store
    raise WebhookRefused("bad secret")


# --------------------------------------------------------------- signatures


def verify(channel: str, store: Store, body: bytes, headers) -> None:
    """Check the platform's own signature, when it sends one.

    Telegram signs by echoing a secret token header — it is the whole
    verification, so a missing header is a refusal rather than a shrug.
    Meta signs the body with the app secret, which is the stronger check and
    the reason `hmac.compare_digest` is here rather than `==`.
    """
    if channel == "telegram":
        expected = secret_for(store)
        got = headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not got or not hmac.compare_digest(got, expected):
            raise WebhookRefused("bad telegram secret header")
        return

    if channel in ("instagram", "whatsapp"):
        app_secret = settings.UPMARKET_AI.get("META_APP_SECRET", "")
        if not app_secret:
            # Nothing to check against. Refusing is the safe answer: an
            # unsigned payload on an unconfigured integration is more likely a
            # probe than a customer.
            raise WebhookRefused("META_APP_SECRET is not set")
        header = headers.get("X-Hub-Signature-256", "")
        if not header.startswith("sha256="):
            raise WebhookRefused("missing signature")
        digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(header[7:], digest):
            raise WebhookRefused("bad signature")
        return

    raise WebhookRefused(f"unknown channel {channel}")


# ------------------------------------------------------------- normalising


class Inbound:
    """One message, in the shape this app already understands.

    `image` is how a payment receipt gets in. A customer paying by bank
    transfer sends a photo of the slip and usually types nothing with it, and
    a parser that required text threw exactly that message away — the one
    step the whole "a human approves the money" flow depends on. It is a
    descriptor, not bytes: fetching the file is a network call, and the
    request has seconds before the platform calls the delivery failed.
    """

    __slots__ = ("external_id", "thread_id", "sender_id", "name", "text", "image")

    def __init__(self, *, external_id, thread_id, sender_id, name, text, image=None):
        self.external_id = str(external_id)
        self.thread_id = str(thread_id)
        self.sender_id = str(sender_id)
        self.name = name or ""
        self.text = text or ""
        #: {"kind": "telegram_file", "file_id": ...} or {"kind": "url", "url": ...}
        self.image = image or None


def parse(channel: str, payload: dict) -> list[Inbound]:
    """Pull the messages out of a platform payload.

    Returns an empty list for everything that is not a message a person typed
    — receipts, reactions, edits, and whatever the platform adds next. The
    caller answers 200 to those, because the alternative is the platform
    retrying a delivery nobody wants and then disabling the webhook.
    """
    if channel == "telegram":
        return _telegram(payload)
    if channel in ("instagram", "whatsapp"):
        return _meta(payload)
    return []


def _telegram(payload: dict) -> list[Inbound]:
    message = payload.get("message") or payload.get("edited_message") or {}
    text = (message.get("text") or message.get("caption") or "").strip()
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    image = _telegram_image(message)
    # A photo with no caption is the normal way a receipt arrives; requiring
    # text dropped it silently.
    if (not text and not image) or not chat.get("id"):
        return []
    name = " ".join(
        part for part in (sender.get("first_name"), sender.get("last_name")) if part
    ) or sender.get("username", "")
    return [
        Inbound(
            external_id=message.get("message_id", ""),
            thread_id=chat["id"],
            sender_id=sender.get("id") or chat["id"],
            name=name,
            text=text,
            image=image,
        )
    ]


def _telegram_image(message: dict) -> dict | None:
    """The photo in a Telegram message, if there is one.

    Telegram sends a photo as a list of sizes, smallest first; the last is the
    original. An image sent "as a file" arrives as `document` instead, which
    is what happens whenever someone forwards a receipt without compression.
    """
    photos = message.get("photo") or []
    if photos:
        biggest = photos[-1]
        if biggest.get("file_id"):
            return {"kind": "telegram_file", "file_id": biggest["file_id"]}
    document = message.get("document") or {}
    if document.get("file_id") and str(document.get("mime_type", "")).startswith("image/"):
        return {"kind": "telegram_file", "file_id": document["file_id"]}
    return None


def _meta(payload: dict) -> list[Inbound]:
    """Instagram and WhatsApp both arrive in Meta's entry/messaging envelope.

    Echoes are skipped explicitly: Meta delivers the shop's *own* replies back
    down the same webhook, and feeding those to the agent makes it answer
    itself in a loop that only stops when the quota runs out.
    """
    out: list[Inbound] = []
    for entry in payload.get("entry", []) or []:
        for event in entry.get("messaging", []) or []:
            message = event.get("message") or {}
            if message.get("is_echo"):
                continue
            text = (message.get("text") or "").strip()
            sender = (event.get("sender") or {}).get("id")
            image = _meta_image(message)
            if (not text and not image) or not sender:
                continue
            out.append(
                Inbound(
                    external_id=message.get("mid", ""),
                    thread_id=sender,
                    sender_id=sender,
                    name="",
                    text=text,
                    image=image,
                )
            )
    return out


def _meta_image(message: dict) -> dict | None:
    """Meta hands over a ready-to-download URL rather than a file id."""
    for attachment in message.get("attachments") or []:
        if attachment.get("type") != "image":
            continue
        url = (attachment.get("payload") or {}).get("url")
        if url:
            return {"kind": "url", "url": url}
    return None


# ------------------------------------------------------------------ storing


def deliver(store: Store, channel_key: str, inbound: Inbound) -> Message | None:
    """Store one message. Returns `None` when it is a duplicate.

    The platform's message id is what makes this safe to call twice: every
    platform retries when it does not get a fast 200, and an agent that answers
    the same question twice looks broken and bills the shop for the privilege.
    """
    with transaction.atomic():
        customer, _ = Customer.objects.get_or_create(
            store=store,
            external_id=inbound.sender_id,
            channel=channel_key.lower(),
            defaults={"name": inbound.name},
        )
        # A name that arrives later is worth keeping — the first message from a
        # platform often has none.
        if inbound.name and not customer.name:
            customer.name = inbound.name
            customer.save(update_fields=["name"])

        conversation, _ = Conversation.objects.get_or_create(
            store=store,
            customer=customer,
            channel=channel_key,
            external_id=inbound.thread_id,
            defaults={"state": Conversation.State.AI},
        )

        if inbound.external_id and Message.objects.filter(
            conversation=conversation, external_id=inbound.external_id,
        ).exists():
            return None

        grounding = {"channel": channel_key}
        if inbound.image:
            grounding["image"] = inbound.image
        message = Message.objects.create(
            conversation=conversation,
            role=Message.Role.CUSTOMER,
            # A bare photo has no words. The inbox still has to show the owner
            # that something arrived, so it says so in the thread.
            text=inbound.text or ("[تصویر]" if inbound.image else ""),
            external_id=inbound.external_id,
            grounding=grounding,
        )

    conversation.last_customer_at = message.created_at
    conversation.save(update_fields=["last_customer_at", "updated_at"])
    return message
