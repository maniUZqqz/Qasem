"""Glue between a conversation's channel key and the adapter that can talk to it.

`services.publishing.channels.send()` is what the rest of the product already
calls to deliver a reply (the sales agent, the old inbox reply, receipts). For
the channels this app adds it delegates here, so **one call site delivers on
every channel** and nothing upstream learned a new platform.

Telegram keeps its historic storage (`StoreProfile.telegram_bot_token`) so a
shop that already connected its bot keeps working with no migration; the
connection row only adds health, polling state and counters on top.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from . import adapters
from .models import ChannelConnection

logger = logging.getLogger(__name__)

#: Channel keys this app delivers on (the others stay with the old code path).
MANAGED = {"BALE", "EITAA", "RUBIKA", "WEBCHAT", "SMS", "WHATSAPP"}

#: Titles in one place - the connect page, the inbox filter and the broadcast
#: composer must call a channel the same thing.
TITLES = {
    "TELEGRAM": "تلگرام", "BALE": "بله", "EITAA": "ایتا", "RUBIKA": "روبیکا",
    "WEBCHAT": "چت سایت", "SMS": "پیامک", "WHATSAPP": "واتساپ",
    "INSTAGRAM": "اینستاگرام", "WEB": "چت سایت و پنل", "API": "API",
}


def connection_for(store, kind: str) -> ChannelConnection | None:
    return ChannelConnection.objects.filter(store=store, kind=(kind or "").upper()).first()


def token_for(connection: ChannelConnection) -> str:
    """The credential to use. Telegram falls back to the store's historic field."""
    token = (connection.token or "").strip()
    if token or connection.kind != ChannelConnection.Kind.TELEGRAM:
        return token
    from services.publishing import channels

    return channels.telegram_token(connection.store)


class _Bound:
    """A connection with its effective token, so adapters need no special case."""

    def __init__(self, connection: ChannelConnection):
        self._c = connection
        self.token = token_for(connection)
        self.config = connection.config or {}
        # Telegram's webhook header carries the *store's* historic secret, the
        # one the legacy endpoint already checks; every other channel has its own.
        if connection.kind == ChannelConnection.Kind.TELEGRAM:
            from apps.customers import webhooks as legacy

            self.secret = legacy.secret_for(connection.store)
        else:
            self.secret = connection.secret
        self.store = connection.store
        self.kind = connection.kind
        self.pk = connection.pk

    def __getattr__(self, name):
        return getattr(self._c, name)


def adapter_for(connection: ChannelConnection):
    cls = adapters.adapter_class(connection.kind)
    return cls(_Bound(connection)) if cls else None


def is_ready(connection: ChannelConnection | None) -> bool:
    if connection is None or not connection.enabled:
        return False
    cls = adapters.adapter_class(connection.kind)
    if cls is None:
        return False
    return (not cls.needs_token) or bool(token_for(connection))


def configured(kind: str, store) -> bool:
    return is_ready(connection_for(store, kind))


def send(kind: str, store, *, to: str, text: str) -> dict:
    """Deliver one message on a managed channel. Never raises."""
    connection = connection_for(store, kind)
    title = TITLES.get(kind.upper(), kind)
    if connection is None:
        return {"sent": False, "reason": f"کانال «{title}» هنوز وصل نشده است."}
    if not connection.enabled:
        return {"sent": False, "reason": f"کانال «{title}» خاموش است."}
    adapter = adapter_for(connection)
    if adapter is None:
        return {"sent": False, "reason": f"کانال «{title}» پشتیبانی نمی‌شود."}
    try:
        result = adapter.send(to, text)
    except Exception as exc:  # noqa: BLE001 - a reply must never be lost to a crash
        logger.exception("send on %s crashed", kind)
        return {"sent": False, "reason": f"ارسال ممکن نشد ({type(exc).__name__})."}
    now = timezone.now()
    if result.ok:
        connection.last_outbound_at = now
        connection.outbound_count += 1
        # A send that went through ends the story of an earlier failure: the card
        # must not keep a red «آخرین خطا» for a channel that works again.
        connection.last_error = ""
        connection.last_error_at = None
        connection.save(update_fields=["last_outbound_at", "outbound_count", "last_error", "last_error_at", "updated_at"])
    else:
        connection.last_error = result.reason[:300]
        connection.last_error_at = now
        connection.save(update_fields=["last_error", "last_error_at", "updated_at"])
    return result.as_dict()


def check_health(connection: ChannelConnection) -> dict:
    """Ask the platform, remember the answer, return it for the connect page."""
    adapter = adapter_for(connection)
    now = timezone.now()
    if adapter is None:
        return {"ok": False, "detail": "کانال پشتیبانی نمی‌شود.", "account": ""}
    try:
        health = adapter.health()
    except Exception as exc:  # noqa: BLE001
        logger.exception("health check crashed for %s", connection.kind)
        health = adapters.Health(False, f"بررسی ممکن نشد ({type(exc).__name__}).")
    connection.health_ok = health.ok
    connection.health_detail = health.detail[:300]
    connection.health_checked_at = now
    if health.account:
        connection.account_label = health.account[:120]
    if not health.ok:
        connection.last_error = health.detail[:300]
        connection.last_error_at = now
    else:
        connection.last_error = ""
        connection.last_error_at = None
    connection.save(update_fields=[
        "health_ok", "health_detail", "health_checked_at", "account_label",
        "last_error", "last_error_at", "updated_at",
    ])
    return {"ok": health.ok, "detail": health.detail, "account": health.account}
