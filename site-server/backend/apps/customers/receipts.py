"""A photo that arrives in a chat, turned into a payment receipt.

The whole "a human approves the money" rule rests on the customer being able
to *send* proof of payment, and until now they could not: the panel's upload
endpoint needs a dashboard login, which a customer does not have, and the
webhook read only text and threw photos away. So on the one channel a shop
actually uses, the flow ended at "here are the card details" and never
continued.

This closes it. The webhook stores the message and returns immediately —
downloading a file is a network call and the platform allows seconds — and
this runs afterwards, off the request.

Nothing here decides anything about the money. It attaches the image to the
open order and moves it to "waiting for your approval"; a person still looks
at the slip and presses the button.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Notification, Order, PaymentReceipt, notify

logger = logging.getLogger(__name__)

#: States in which a receipt still means something. A confirmed or cancelled
#: order does not need proof of a payment that is already settled.
OPEN_FOR_RECEIPT = (
    Order.Status.AWAITING_RECEIPT,
    Order.Status.AWAITING_APPROVAL,
    Order.Status.DRAFT,
    Order.Status.CASH_ON_DELIVERY,
)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def fetch(store, descriptor: dict) -> tuple[bytes, str] | None:
    """Download the image the platform told us about. (bytes, content-type)."""
    import requests

    from services.publishing import channels

    try:
        if descriptor.get("kind") == "telegram_file":
            token = channels.telegram_token(store)
            if not token:
                logger.warning("No Telegram token for store %s; cannot fetch file", store.id)
                return None
            meta = requests.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": descriptor["file_id"]},
                timeout=20,
            ).json()
            path = (meta.get("result") or {}).get("file_path")
            if not path:
                logger.warning("Telegram did not return a file path: %s", meta)
                return None
            url = f"https://api.telegram.org/file/bot{token}/{path}"
        elif descriptor.get("kind") == "url":
            url = descriptor["url"]
        else:
            return None

        response = requests.get(url, timeout=30, stream=True)
        if response.status_code >= 400:
            logger.warning("Could not download the image: HTTP %s", response.status_code)
            return None
        limit = settings.MAX_UPLOAD_MB * 1024 * 1024
        data = b""
        for chunk in response.iter_content(64 * 1024):
            data += chunk
            if len(data) > limit:
                logger.warning("Image over %s MB; refused", settings.MAX_UPLOAD_MB)
                return None
        return data, response.headers.get("Content-Type", "")
    except Exception as exc:  # noqa: BLE001 — a customer is waiting either way
        logger.warning("Fetching the chat image failed: %s", exc)
        return None


def _is_real_image(data: bytes) -> bool:
    """Open it before trusting it — a content-type header is just a claim."""
    import io

    from PIL import Image as PILImage

    try:
        PILImage.open(io.BytesIO(data)).verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def absorb(message) -> PaymentReceipt | None:
    """Attach the photo on `message` to this conversation's open order.

    Returns the receipt, or None when there was nothing to attach it to — a
    photo of the product, a selfie, a customer with no open order. That case
    is not an error: the image stays on the message and the agent answers the
    conversation as usual.
    """
    descriptor = (message.grounding or {}).get("image")
    if not descriptor:
        return None
    conversation = message.conversation
    store = conversation.store

    order = (
        conversation.orders.filter(status__in=OPEN_FOR_RECEIPT)
        .order_by("-created_at")
        .first()
    )
    if order is None:
        return None

    fetched = fetch(store, descriptor)
    if fetched is None:
        notify(
            store,
            Notification.Type.RECEIPT,
            f"مشتری برای سفارش #{order.id} تصویری فرستاد که دانلود نشد",
            body="عکس را از خود گفتگو در تلگرام/اینستاگرام ببینید و دستی تأیید کنید.",
            link=f"/stores/{store.id}/sales",
            context={"order_id": order.id, "conversation_id": conversation.id},
        )
        return None

    data, content_type = fetched
    if content_type and content_type.split(";")[0].strip() not in ALLOWED_TYPES:
        logger.info("Ignoring a %s attachment — not an image we accept", content_type)
        return None
    if not _is_real_image(data):
        logger.info("Ignoring an attachment that does not open as an image")
        return None

    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    receipt = PaymentReceipt.objects.create(
        order=order,
        image=ContentFile(data, name=f"receipt-{order.id}-{stamp}.jpg"),
        note=(message.text or "")[:300],
    )
    if order.status != Order.Status.AWAITING_APPROVAL:
        order.status = Order.Status.AWAITING_APPROVAL
        order.save(update_fields=["status", "updated_at"])
    notify(
        store,
        Notification.Type.RECEIPT,
        f"رسید پرداخت برای سفارش #{order.id} رسید",
        body=f"مبلغ سفارش: {order.total} — منتظر بررسی و تأیید شماست.",
        link=f"/stores/{store.id}/sales",
        context={"order_id": order.id, "receipt_id": receipt.id},
    )
    return receipt


def acknowledge(conversation, order) -> None:
    """Tell the customer the slip arrived — and only that.

    Never that the payment is accepted: a person has not looked at it yet,
    and a bot saying "payment confirmed" is exactly the promise this system
    is built not to make.
    """
    from services.publishing import channels

    channels.send(
        conversation.channel,
        conversation.store,
        to=conversation.external_id,
        text=(
            f"رسید شما برای سفارش #{order.id} دریافت شد. "
            "همکار ما بررسی می‌کند و نتیجه را همین‌جا به شما می‌گوییم."
        ),
    )
