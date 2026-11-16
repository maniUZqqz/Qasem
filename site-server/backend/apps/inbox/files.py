"""Attachments from the channels this app owns - for the payment-receipt flow.

`apps.customers.receipts.fetch` knows Telegram files and plain URLs. For a photo
that arrived on Bale, Rubika or WhatsApp it asks here: which platform API can turn
this file id into a download address? (Eitaa cannot, and says so: the owner is
told to open the chat, exactly as for any download that fails.)
"""
from __future__ import annotations

from . import dispatch

KIND_TO_CHANNEL = {"bale_file": "BALE", "rubika_file": "RUBIKA", "whatsapp_media": "WHATSAPP", "eitaa_file": "EITAA"}


def resolve(store, descriptor: dict) -> tuple[str, dict] | None:
    """(download url, headers) for an attachment descriptor, or None."""
    channel = KIND_TO_CHANNEL.get((descriptor or {}).get("kind", ""))
    if channel is None:
        return None
    connection = dispatch.connection_for(store, channel)
    if not dispatch.is_ready(connection):
        return None
    adapter = dispatch.adapter_for(connection)
    try:
        return adapter.file_url(descriptor)
    except Exception:  # noqa: BLE001 - a failed lookup must not break the receipt flow
        return None
