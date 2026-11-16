"""Adapter registry: channel key -> adapter class.

`for_connection(conn)` is the only thing the rest of the app calls. SMS and the
website widget have no HTTP bot API to wrap; they live in `sms.py` /
`webchat.py` as adapters too, so `send` has one shape everywhere.
"""
from __future__ import annotations

from .base import Adapter, AdapterError, Health, Incoming, PollResult, SendResult  # noqa: F401
from .eitaa import EitaaAdapter
from .rubika import RubikaAdapter
from .tgcompat import BaleAdapter, TelegramAdapter
from .whatsapp import WhatsAppAdapter


def _registry() -> dict[str, type[Adapter]]:
    from .sms import SmsAdapter
    from .webchat import WebchatAdapter

    return {
        cls.key: cls
        for cls in (
            TelegramAdapter, BaleAdapter, EitaaAdapter, RubikaAdapter,
            WhatsAppAdapter, SmsAdapter, WebchatAdapter,
        )
    }


def adapter_class(key: str) -> type[Adapter] | None:
    return _registry().get((key or "").upper())


def by_slug(slug: str) -> type[Adapter] | None:
    for cls in _registry().values():
        if cls.slug == slug:
            return cls
    return None


def for_connection(connection) -> Adapter | None:
    cls = adapter_class(connection.kind)
    return cls(connection) if cls else None
