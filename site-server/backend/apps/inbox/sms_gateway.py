"""The bridge between the unified inbox and `apps.mobile`'s phone gateway.

Outbound is the SMS adapter (a queue the phones drain). Inbound is the reverse:
phones post what they receive into `SmsInbound`, and `pull` turns the *new* rows
into inbox conversations. Three rules keep that from becoming a leak, because
the same SIM that receives customers' texts also receives the owner's bank codes:

* **only new messages** - when the channel is switched on the cursor jumps to the
  newest existing row, so months of old private SMS are never imported;
* **only people the shop knows** - by default a text is accepted only from a
  number that is already a contact, or that we have already written to; a store
  that really runs a public number turns "accept unknown numbers" on;
* **only real mobile numbers** - bank short codes and alphanumeric senders
  (`3000…`, `BANK`) are never conversations.
"""
from __future__ import annotations

import logging

from django.db.models import Max

from apps.mobile import phone as mphone
from apps.mobile.models import MobileDevice, MobileSettings, SmsInbound, SmsMessage

from . import ingest, norm, team
from .adapters.base import Incoming
from .models import ChannelConnection, Contact

logger = logging.getLogger(__name__)


def devices_for(store):
    users = [u.pk for u in team.members(store)]
    return MobileDevice.objects.filter(user_id__in=users, revoked_at__isnull=True)


def status(store) -> dict:
    settings = MobileSettings.get()
    phones = list(devices_for(store))
    online = [d for d in phones if d.online and d.sms_enabled]
    return {
        "paused": not settings.sms_enabled,
        "forwarding": settings.forward_incoming_sms,
        "online": len(online),
        "phones": [
            {"name": d.name, "online": d.online, "sms_ready": d.sms_ready, "battery": d.battery_percent}
            for d in phones
        ],
    }


def available(store) -> bool:
    info = status(store)
    return bool(info["online"]) and not info["paused"]


def start(connection: ChannelConnection) -> None:
    """Switching the channel on: begin at *now*, never at the beginning of time."""
    newest = SmsInbound.objects.aggregate(m=Max("id"))["m"] or 0
    connection.poll_cursor = str(newest)
    connection.save(update_fields=["poll_cursor", "updated_at"])


def _known(store, number_norm: str) -> bool:
    local = norm.normalize_phone(mphone.national(number_norm))
    if local and Contact.objects.filter(store=store, phone=local).exists():
        return True
    return SmsMessage.objects.filter(to_number=number_norm).exists()


def _real_mobile(number_norm: str) -> bool:
    return number_norm.startswith("989") and len(number_norm) == 12


def pull(connection: ChannelConnection) -> dict:
    """Turn new phone-received texts into conversations. Idempotent per row id."""
    store = connection.store
    cursor = int(connection.poll_cursor or 0)
    accept_unknown = bool((connection.config or {}).get("accept_unknown"))
    devices = list(devices_for(store).values_list("pk", flat=True))
    rows = list(SmsInbound.objects.filter(id__gt=cursor, device_id__in=devices).order_by("id")[:200])
    accepted = skipped = 0
    last = cursor
    for row in rows:
        last = row.pk
        sender = mphone.normalize(row.from_number)
        if not _real_mobile(sender) or not (accept_unknown or _known(store, sender)):
            skipped += 1
            continue
        local = mphone.national(sender)
        body = "لغو" if row.is_stop and row.body == "(لغو)" else (row.body or "").strip()
        if not body:
            skipped += 1
            continue
        outcome = ingest.receive(connection, Incoming(
            external_id=f"sms{row.pk}", thread_id=sender, sender_id=sender, phone=local, text=body[:2000],
        ))
        if outcome.message is not None:
            accepted += 1
            ingest.answer_later(outcome)
    if last != cursor:
        connection.poll_cursor = str(last)
        connection.save(update_fields=["poll_cursor", "updated_at"])
    return {"polled": True, "received": len(rows), "accepted": accepted, "skipped": skipped}


def send_marketing(to: str, text: str, *, campaign_ref: str):
    """Broadcast SMS: marketing kind, which the gateway only accepts from an approved campaign."""
    from apps.mobile import sms
    from apps.mobile.base import MobileError

    try:
        message, _ = sms.enqueue(to, text, kind=SmsMessage.Kind.MARKETING, campaign_ref=campaign_ref)
    except MobileError as exc:
        return {"sent": False, "reason": exc.message}
    return {"sent": True, "reason": "", "external_id": str(message.uid)}


def approve_campaign(broadcast, user) -> None:
    """A person approved the broadcast: tell the gateway, so it will accept marketing SMS."""
    sms_count = (broadcast.stats or {}).get("per_channel", {}).get("SMS", 0)
    if not sms_count:
        return
    from apps.mobile import sms

    sms.register_campaign_approval(
        campaign_ref(broadcast), f"ارسال گروهی: {broadcast.name}", approved_by=user,
        max_messages=sms_count + 5, source="inbox",
    )


def revoke_campaign(broadcast) -> None:
    from apps.mobile import sms

    sms.revoke_campaign(campaign_ref(broadcast))


def campaign_ref(broadcast) -> str:
    return f"inbox-broadcast-{broadcast.pk}"
