"""Outgoing webhooks: the inbox tells the shop's own systems what happened.

`emit(store, "message.received", {...})` writes one `WebhookDelivery` row per
active endpoint subscribed to that event; `deliver_due()` (Celery beat, every
minute, and also fired right after commit) POSTs them. The row *is* the retry
queue: a delivery that fails is retried with growing delays and the endpoint is
disabled after a run of failures, so a dead URL cannot make the queue grow
forever.

Signing: `X-Inbox-Signature: t=<unix>,v1=<hex hmac-sha256("<t>.<body>")>` with the
endpoint's secret - the same scheme Stripe popularised, so any developer already
knows how to check it. The timestamp is inside the signature so a captured
request cannot be replayed later.

**SSRF.** The URL is typed by a store owner and fetched by our server, so
without a check it is a way to make the server call its own localhost, the
cloud metadata address, or the owner's LAN. We reuse `services.safenet`'s guard:
the host is resolved *once*, refused unless every address is public, and the
request goes to the address that was checked (Host header + TLS SNI carry the
name) so DNS cannot change between "check" and "connect". Redirects are not
followed, and only ports 80/443/8080/8443 are allowed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import timedelta

import httpx
from django.db import transaction
from django.utils import timezone

from services import safenet

from .models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

#: Everything a webhook can subscribe to - also what the docs page lists.
EVENTS = {
    "message.received": "پیام تازه از مشتری",
    "message.sent": "پاسخ ارسال شد (تیم یا ربات)",
    "conversation.created": "گفتگوی تازه شروع شد",
    "conversation.assigned": "گفتگو به کسی سپرده شد",
    "conversation.handoff": "ربات گفتگو را به آدم داد",
    "conversation.closed": "گفتگو بسته شد",
    "conversation.reopened": "گفتگوی بسته‌شده دوباره باز شد",
    "sla.warning": "SLA در آستانهٔ رد شدن",
    "sla.breached": "SLA رد شد",
    "survey.answered": "مشتری نظرسنجی را پاسخ داد",
    "contact.opted_out": "مخاطب از پیام‌های تبلیغاتی خارج شد",
    "broadcast.approved": "ارسال گروهی تأیید شد",
    "broadcast.finished": "ارسال گروهی تمام شد",
}

MAX_ATTEMPTS = 6
#: Minutes to wait before attempt 2, 3, 4 ...
BACKOFF_MINUTES = [1, 5, 30, 120, 720]
DISABLE_AFTER_FAILURES = 25
TIMEOUT = 8


class UnsafeURL(ValueError):
    """The webhook URL points somewhere we will not call. Message is Persian."""


def _reject_credentials(url: str) -> None:
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url or "")
        has_userinfo = bool(parts.username or parts.password)
    except ValueError:
        raise UnsafeURL("نشانی معتبر نیست.") from None
    if has_userinfo:
        raise UnsafeURL("نشانی نباید نام‌کاربری و رمز داشته باشد.")


def check_url(url: str, resolver=None) -> str:
    """Return the URL if it is a public http(s) address, else raise `UnsafeURL`."""
    _reject_credentials(url)
    try:
        parts = safenet._prepare(url, resolver)  # noqa: SLF001 - the shared guard
    except safenet.FetchError as exc:
        raise UnsafeURL(exc.message) from exc
    del parts
    return url


def _post(url: str, body: bytes, headers: dict, *, resolver=None, transport=None) -> int:
    """POST to the address `check` approved. Returns the status code."""
    _reject_credentials(url)
    try:
        scheme, host, port, ip, path_query = safenet._prepare(url, resolver)  # noqa: SLF001
    except safenet.FetchError as exc:
        raise UnsafeURL(exc.message) from exc
    default = 443 if scheme == "https" else 80
    host_header = host if port == default else f"{host}:{port}"
    ip_s = f"[{ip}]" if ":" in ip else ip
    request_url = f"{scheme}://{ip_s}:{port}{path_query}"
    extensions = {"sni_hostname": host} if scheme == "https" else {}
    with httpx.Client(
        transport=transport or httpx.HTTPTransport(retries=0),
        timeout=httpx.Timeout(TIMEOUT, connect=5.0), follow_redirects=False, verify=True,
    ) as client:
        response = client.post(
            request_url, content=body, headers={**headers, "Host": host_header}, extensions=extensions,
        )
    return response.status_code


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    stamp = int(timestamp if timestamp is not None else time.time())
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}"


def verify_signature(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    """For the docs/tests: what a receiver does."""
    try:
        fields = dict(part.split("=", 1) for part in header.split(","))
        stamp = int(fields["t"])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - stamp) > tolerance:
        return False
    expected = sign(secret, body, stamp)
    return hmac.compare_digest(expected, header)


def emit(store, event: str, data: dict) -> int:
    """Queue `event` for every endpoint that wants it. Returns how many."""
    if event not in EVENTS:
        logger.warning("Unknown inbox event %s", event)
        return 0
    queued = 0
    event_id = "evt_" + secrets.token_hex(10)
    payload = {
        "id": event_id, "event": event, "store_id": store.id,
        "created_at": timezone.now().isoformat(), "data": data,
    }
    for endpoint in WebhookEndpoint.objects.filter(store=store, active=True):
        wanted = endpoint.events or []
        if wanted and event not in wanted:
            continue
        WebhookDelivery.objects.create(
            endpoint=endpoint, event=event, event_id=event_id, payload=payload,
        )
        queued += 1
    if queued:
        _kick()
    return queued


def _kick() -> None:
    """Try to deliver right after the surrounding transaction commits."""
    def run():
        try:
            from .tasks import deliver_webhooks

            deliver_webhooks.delay()
        except Exception:  # noqa: BLE001 - the beat will pick it up in a minute
            logger.debug("webhook kick failed", exc_info=True)

    try:
        transaction.on_commit(run)
    except Exception:  # noqa: BLE001
        pass


def deliver_one(delivery: WebhookDelivery, *, resolver=None, transport=None) -> bool:
    endpoint = delivery.endpoint
    body = json.dumps(delivery.payload, ensure_ascii=False, separators=(",", ":")).encode()
    delivery.attempts += 1
    code = None
    error = ""
    try:
        code = _post(
            endpoint.url, body,
            {
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "NM-Inbox-Webhook/1",
                "X-Inbox-Event": delivery.event,
                "X-Inbox-Delivery": delivery.event_id,
                "X-Inbox-Signature": sign(endpoint.secret, body),
            },
            resolver=resolver, transport=transport,
        )
        ok = 200 <= code < 300
        if not ok:
            error = f"پاسخ {code}"
    except UnsafeURL as exc:
        ok, error = False, str(exc)
    except httpx.HTTPError:
        ok, error = False, "اتصال برقرار نشد."
    delivery.response_code = code
    delivery.error = error[:300]
    now = timezone.now()
    if ok:
        delivery.status = WebhookDelivery.Status.OK
        endpoint.failure_count = 0
    elif delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = WebhookDelivery.Status.FAILED
        endpoint.failure_count += 1
    else:
        delay = BACKOFF_MINUTES[min(delivery.attempts - 1, len(BACKOFF_MINUTES) - 1)]
        delivery.next_attempt_at = now + timedelta(minutes=delay)
        endpoint.failure_count += 1
    delivery.save()
    endpoint.last_status = "OK" if ok else (error or "ناموفق")[:60]
    endpoint.last_delivery_at = now
    if endpoint.failure_count >= DISABLE_AFTER_FAILURES:
        endpoint.active = False
        endpoint.last_status = "غیرفعال شد: خطاهای پشت‌سرهم"
    endpoint.save(update_fields=["failure_count", "last_status", "last_delivery_at", "active", "updated_at"])
    return ok


def deliver_due(limit: int = 50, *, resolver=None, transport=None) -> dict:
    now = timezone.now()
    sent = failed = 0
    due = (
        WebhookDelivery.objects.filter(status=WebhookDelivery.Status.PENDING, next_attempt_at__lte=now)
        .select_related("endpoint").order_by("next_attempt_at")[:limit]
    )
    for delivery in due:
        if not delivery.endpoint.active:
            delivery.status = WebhookDelivery.Status.FAILED
            delivery.error = "نقطهٔ دریافت غیرفعال است."
            delivery.save(update_fields=["status", "error"])
            continue
        if deliver_one(delivery, resolver=resolver, transport=transport):
            sent += 1
        else:
            failed += 1
    # Keep the log short: a month of OK rows tells nobody anything.
    WebhookDelivery.objects.filter(
        status=WebhookDelivery.Status.OK, created_at__lt=now - timedelta(days=14),
    ).delete()
    return {"sent": sent, "failed": failed}
