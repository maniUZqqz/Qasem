"""Celery tasks - every one safe to run twice and to run late.

The beat schedule lives in `config/settings.py` (`CELERY_BEAT_SCHEDULE`): polling
every 30 s, SLA / follow-ups / broadcasts / webhooks every minute, channel
health every 10 min. None of these assume the previous run finished: each claims
its rows (a timestamp, a status flip) before working on them.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.customers.models import Notification, notify

from . import broadcast, dispatch, events, followups, ingest, sla
from .models import ChannelConnection

logger = logging.getLogger(__name__)

def _fresh_connection() -> None:
    """Drop a stale DB connection - but never one a caller is inside a transaction on.

    An eager task run from a request or a test owns that connection; closing it
    under them is "Cannot operate on a closed database" for everything after
    (the same rule `views_webhook.run_agent_for` keeps).
    """
    if not connection.in_atomic_block:
        close_old_connections()


#: A poll claim older than this is a crashed worker, not a running one.
POLL_CLAIM_SECONDS = 25
HEALTH_EVERY = timedelta(minutes=10)


def _polling_connections():
    for connection in ChannelConnection.objects.filter(enabled=True).select_related("store", "store__profile"):
        adapter = dispatch.adapter_for(connection)
        if adapter is None or not adapter.can_poll:
            continue
        registered = bool((connection.config or {}).get("webhook_registered"))
        if connection.mode == ChannelConnection.Mode.POLLING or (
            connection.mode == ChannelConnection.Mode.AUTO and not registered
        ):
            yield connection


@shared_task(name="inbox.poll_channels")
def poll_channels() -> dict:
    """Pull new messages from every polling channel."""
    _fresh_connection()
    polled = accepted = 0
    now = timezone.now()
    for connection in _polling_connections():
        claimed = ChannelConnection.objects.filter(pk=connection.pk).filter(
            poll_claimed_at__isnull=True,
        ) | ChannelConnection.objects.filter(
            pk=connection.pk, poll_claimed_at__lt=now - timedelta(seconds=POLL_CLAIM_SECONDS),
        )
        if not claimed.update(poll_claimed_at=now):
            continue
        try:
            result = ingest.poll_connection(connection)
            polled += 1
            accepted += result.get("accepted", 0)
        except Exception:  # noqa: BLE001 - one broken channel must not stop the rest
            logger.exception("poll failed for %s", connection.pk)
        finally:
            ChannelConnection.objects.filter(pk=connection.pk).update(poll_claimed_at=None)
    # SMS arrives by a different road: phones post into the gateway's table.
    from . import sms_gateway

    for connection in ChannelConnection.objects.filter(kind="SMS", enabled=True).select_related("store"):
        try:
            result = sms_gateway.pull(connection)
            polled += 1
            accepted += result.get("accepted", 0)
        except Exception:  # noqa: BLE001
            logger.exception("sms pull failed for %s", connection.pk)
    return {"polled": polled, "accepted": accepted}


@shared_task(name="inbox.sla_tick")
def sla_tick() -> dict:
    _fresh_connection()
    return sla.tick()


@shared_task(name="inbox.followups_tick")
def followups_tick() -> dict:
    _fresh_connection()
    queued = followups.scan_payment_reminders()
    result = followups.run_due()
    result["payment_reminders_queued"] = queued
    return result


@shared_task(name="inbox.broadcast_tick")
def broadcast_tick() -> dict:
    _fresh_connection()
    return broadcast.send_tick()


@shared_task(name="inbox.deliver_webhooks")
def deliver_webhooks() -> dict:
    _fresh_connection()
    return events.deliver_due()


@shared_task(name="inbox.health_sweep")
def health_sweep() -> dict:
    """Re-check every enabled channel; tell the owner once when one goes bad."""
    _fresh_connection()
    now = timezone.now()
    checked = bad = 0
    for connection in ChannelConnection.objects.filter(enabled=True).select_related("store", "store__profile"):
        if connection.kind in ("WEBCHAT", "SMS"):
            continue
        if connection.health_checked_at and now - connection.health_checked_at < HEALTH_EVERY:
            continue
        was_ok = connection.health_ok
        result = dispatch.check_health(connection)
        checked += 1
        if not result["ok"]:
            bad += 1
            if was_ok is not False:
                notify(
                    connection.store, Notification.Type.AI_ERROR,
                    f"کانال «{dispatch.TITLES.get(connection.kind, connection.kind)}» مشکل دارد",
                    body=result["detail"][:250], link=f"/stores/{connection.store_id}/inbox/channels",
                    context={"channel": connection.kind},
                )
    return {"checked": checked, "bad": bad}


@shared_task(name="inbox.answer_later")
def answer_conversation(conversation_id: int, text: str, message_id: int | None = None) -> str:
    """Thin alias so the inbox can queue a bot answer without importing customers' views."""
    from apps.customers.views_webhook import run_agent_for

    return run_agent_for(conversation_id, text, message_id)
