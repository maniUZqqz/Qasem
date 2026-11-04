"""Stable Python API of NM-Mobile for OTHER NM apps (Growth Engine, campaigns…). Import from here, not from the internals.

    from apps.mobile import api as mobile

    # After a HUMAN has approved a marketing campaign:
    mobile.register_campaign_approval("ge:42", "پیشنهاد ویژه", approved_by=user, max_messages=300)
    mobile.queue_sms("09121234567", "متن…", kind="marketing", campaign_ref="ge:42", idempotency_key="ge:42:lead:9")
    mobile.is_opted_out("09121234567")          # also honours Growth Engine's own «تماس نگیر» list

    # The one call Growth Engine (or any NM app) needs to send ONE SMS through the owner's paired phone:
    sms_id = mobile.enqueue_sms("09121234567", "متن…", source="growth", ref="item-77", campaign_ref="ge:42")
    mobile.sms_status(sms_id)       # {"state": "queued|sending|sent|delivered|failed|cancelled|blocked", "final": False, ...}

Rules enforced for you: marketing needs an active human approval, opted-out numbers are never messaged, idempotency keys are
honoured, and the phone only ever receives what passed all of that. This module never touches Growth Engine's tables.
"""
from __future__ import annotations

from . import callerid, phone
from .base import MobileError
from .models import SmsMessage
from .sms import (OptedOut, add_opt_out, cancel as cancel_sms, enqueue as _enqueue, is_opted_out, register_campaign_approval,
                  revoke_campaign)

__all__ = ["enqueue_sms", "sms_status", "sms_statuses", "queue_sms", "is_opted_out", "add_opt_out", "register_campaign_approval",
           "revoke_campaign", "cancel_sms", "OptedOut", "MobileError", "register_caller_source", "normalize_number"]

#: SmsMessage.State -> the vocabulary other apps use
_STATE = {"QUEUED": "queued", "CLAIMED": "sending", "SENT": "sent", "DELIVERED": "delivered", "FAILED": "failed",
          "CANCELLED": "cancelled", "BLOCKED": "blocked"}
_FINAL = {"delivered", "failed", "cancelled", "blocked"}


def queue_sms(to, body, kind="transactional", campaign_ref="", idempotency_key="", created_by=None, not_before=None):
    """Queue one SMS. Returns (message, created). Raises `mobile.base.MobileError` (campaign_not_approved, bad_number…) or
    `OptedOut` (a BLOCKED row is kept for the audit trail)."""
    return _enqueue(to, body, kind, campaign_ref, idempotency_key, created_by, not_before)


def register_caller_source(fn):
    """Add a read-only caller-ID source: `fn(user, normalized_number, key10) -> [{"source","name","detail","store","id","last_contact_at"}]`."""
    return callerid.register_source(fn)


def normalize_number(raw) -> str:
    return phone.normalize(raw)


def enqueue_sms(phone_number, text, *, source="growth", ref="", kind="marketing", campaign_ref="", created_by=None,
                not_before=None, expires_at=None) -> str:
    """Queue ONE outbound SMS for the owner's paired phone(s). Returns the message id (a UUID string).

    Import: ``from apps.mobile.api import enqueue_sms, sms_status``

    * ``source`` / ``ref`` identify the caller's own record (e.g. ``source="growth", ref="<campaign item id>"``). They form the
      idempotency key ``"<source>:<ref>"``: calling again with the same pair returns the SAME id and queues nothing twice.
      Leave ``ref`` empty to get no idempotency (every call queues a new message).
    * ``kind``: ``"marketing"`` (default for Growth Engine) needs ``campaign_ref`` of a campaign a human approved via
      ``register_campaign_approval(campaign_ref, title, approved_by=user, max_messages=...)``; ``"transactional"`` / ``"otp"`` do not.
    * Guardrails applied by NM-Mobile, not by you: opt-out list (global «لغو/stop» list + Growth Engine's «تماس نگیر», checked when
      queued AND again when the phone claims it), per-device hourly/daily caps and the stricter marketing cap, quiet hours
      21:00-08:00 Tehran for marketing, global pause, approval revoked/expired/exhausted, the phone's own sending speed.
    * No phone online? The message simply waits as ``queued``. With ``expires_at`` set, a message nobody picked up in time becomes
      ``failed`` with ``error_code == "expired"`` (checked whenever a phone asks for work).

    Raises ``MobileError`` with ``.code`` in ``bad_number`` / ``missing_fields`` / ``too_long`` / ``campaign_not_approved``, or
    ``OptedOut`` (a ``MobileError`` subclass, code ``opted_out``; the BLOCKED row is kept for the audit trail and its id is in
    ``exc.sms.uid``).
    """
    key = f"{source}:{ref}" if ref else ""
    msg, _created = _enqueue(phone_number, text, kind, campaign_ref, key, created_by, not_before, None, expires_at)
    return str(msg.uid)


def sms_status(sms_id) -> dict | None:
    """State of a message queued with `enqueue_sms`, or None when the id is unknown.

    ``{"id", "state", "final", "error", "error_code", "created_at", "sent_at", "delivered_at", "attempts", "device"}`` where ``state`` is
    one of ``queued`` (waiting for a phone), ``sending`` (handed to a phone, no report yet), ``sent`` (left the phone; delivery report
    may still come), ``delivered``, ``failed``, ``cancelled``, ``blocked`` (opt-out / campaign no longer approved).
    ``final`` is True for delivered / failed / cancelled / blocked (``sent`` is final enough for most callers but may still become
    ``delivered``).
    """
    try:
        m = SmsMessage.objects.select_related("device").filter(uid=str(sms_id)).first()
    except Exception:  # noqa: BLE001 - malformed id
        m = None
    if m is None:
        return None
    state = _STATE.get(m.state, m.state.lower())
    return {"id": str(m.uid), "state": state, "final": state in _FINAL, "error": m.error, "error_code": m.error_code,
            "created_at": m.created_at, "sent_at": m.sent_at, "delivered_at": m.delivered_at, "attempts": m.attempts,
            "device": m.device.name if m.device else None}


def sms_statuses(sms_ids) -> dict:
    """`{id: sms_status(id)}` for several ids at once (unknown ids map to None)."""
    return {str(i): sms_status(i) for i in list(sms_ids)[:500]}
