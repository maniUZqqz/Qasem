"""The SMS gateway: NM queues, a paired phone claims and sends from its SIM, then reports.

Rules enforced HERE (the phone does not re-implement them):
* opted-out numbers are never handed out (re-checked at claim time, not only at queue time);
* marketing SMS only from a campaign a human approved, only outside quiet hours (21:00-08:00 Tehran);
* per-device hourly / daily caps (+ a stricter hourly cap for marketing);
* global pause; per-device switch;
* idempotency key on queueing; reports only move a message forward and are safe to repeat.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import phone
from .base import MobileError
from .models import (MobileDevice, MobileSettings, SmsCampaignApproval, SmsInbound, SmsMessage, SmsOptOut)

logger = logging.getLogger(__name__)

TEHRAN = ZoneInfo("Asia/Tehran")
MAX_BODY = 1000
#: errors worth one more try (the radio may be back); everything else is final
RETRYABLE = {"no_service", "radio_off", "generic", "timeout", "null_pdu"}


# ------------------------------------------------------------------ opt-out

def is_opted_out(number) -> bool:
    k = phone.key(number)
    if len(k) < 7:
        return False
    if SmsOptOut.objects.filter(key=k).exists():
        return True
    return _growth_suppressed(k)


def _growth_suppressed(k: str) -> bool:
    """Read-only look at Growth Engine's «تماس نگیر» list, when that app is installed."""
    try:
        from django.apps import apps

        model = apps.get_model("growth_compliance", "SuppressionEntry")
    except Exception:  # noqa: BLE001 - app not installed / other label
        try:
            from django.apps import apps

            model = next((m for m in apps.get_models() if m.__name__ == "SuppressionEntry"), None)
        except Exception:  # noqa: BLE001
            model = None
    if model is None:
        return False
    try:
        return model.objects.filter(kind="phone", normalized__endswith=k).exists()
    except Exception:  # noqa: BLE001 - never let a foreign table break sending
        return False


def add_opt_out(number, reason=SmsOptOut.Reason.MANUAL, source_text="", user=None, device=None) -> tuple[SmsOptOut, bool]:
    norm = phone.normalize(number)
    if not phone.is_valid(norm):
        raise MobileError("bad_number", "شماره درست نیست.", 400)
    obj, created = SmsOptOut.objects.get_or_create(
        number=norm, defaults={"key": phone.key(norm), "reason": reason, "source_text": (source_text or "")[:200],
                               "created_by": user, "device": device})
    if created:
        # anything still waiting for this number is now blocked
        SmsMessage.objects.filter(to_number=norm, state__in=[SmsMessage.State.QUEUED]).exclude(kind=SmsMessage.Kind.OTP).update(
            state=SmsMessage.State.BLOCKED, error="opted_out")
    return obj, created


# ------------------------------------------------------------------ campaigns

def register_campaign_approval(ref, title, approved_by=None, valid_until=None, max_messages=None, source="manual") -> SmsCampaignApproval:
    ref = str(ref).strip()[:80]
    if not ref:
        raise MobileError("missing_fields", "شناسهٔ کمپین لازم است.", 400)
    obj, _ = SmsCampaignApproval.objects.update_or_create(
        ref=ref, defaults={"title": title[:200], "source": source[:30], "approved_by": approved_by, "valid_until": valid_until,
                           "max_messages": max_messages, "revoked_at": None, "approved_at": timezone.now()})
    return obj


def revoke_campaign(ref) -> int:
    n = SmsCampaignApproval.objects.filter(ref=ref, revoked_at__isnull=True).update(revoked_at=timezone.now())
    SmsMessage.objects.filter(campaign_ref=ref, state=SmsMessage.State.QUEUED).update(state=SmsMessage.State.BLOCKED,
                                                                                    error="campaign_revoked")
    return n


# ------------------------------------------------------------------ queue

def enqueue(to, body, kind=SmsMessage.Kind.TRANSACTIONAL, campaign_ref="", idempotency_key="", created_by=None,
            not_before=None, sim_slot=None, expires_at=None) -> tuple[SmsMessage, bool]:
    """Returns (message, created). Raises MobileError for refusals."""
    key = (idempotency_key or "").strip()[:120] or None
    if key:
        existing = SmsMessage.objects.filter(idempotency_key=key).first()
        if existing:
            return existing, False
    norm = phone.normalize(to)
    if not phone.is_valid(norm):
        raise MobileError("bad_number", "شمارهٔ گیرنده درست نیست.", 400)
    body = str(body or "").strip()
    if not body:
        raise MobileError("missing_fields", "متنِ پیامک لازم است.", 400)
    if len(body) > MAX_BODY:
        raise MobileError("too_long", f"متنِ پیامک بیش از {MAX_BODY} نویسه است.", 400)
    if kind not in SmsMessage.Kind.values:
        raise MobileError("bad_kind", "نوعِ پیامک باید otp، transactional یا marketing باشد.", 400)
    campaign_ref = (campaign_ref or "").strip()[:80]
    if kind == SmsMessage.Kind.MARKETING:
        approval = SmsCampaignApproval.objects.filter(ref=campaign_ref).first() if campaign_ref else None
        if approval is None or not approval.active:
            raise MobileError("campaign_not_approved",
                              "پیامکِ تبلیغاتی فقط از کمپینی ساخته می‌شود که یک نفر تأییدش کرده باشد.", 403)
    settings = MobileSettings.get()
    if is_opted_out(norm) and not (kind == SmsMessage.Kind.OTP and settings.otp_ignores_opt_out):
        msg = SmsMessage.objects.create(
            idempotency_key=key, to_number=norm, to_raw=str(to)[:40], body=body, kind=kind, campaign_ref=campaign_ref,
            state=SmsMessage.State.BLOCKED, error="opted_out", created_by=created_by, max_attempts=1)
        raise OptedOut(msg)
    msg = SmsMessage.objects.create(
        idempotency_key=key, to_number=norm, to_raw=str(to)[:40], body=body, kind=kind, campaign_ref=campaign_ref,
        created_by=created_by, not_before=not_before, expires_at=expires_at, sim_slot=sim_slot,
        max_attempts=1 if kind == SmsMessage.Kind.MARKETING else 2)
    return msg, True


class OptedOut(MobileError):
    def __init__(self, message: SmsMessage):
        super().__init__("opted_out", "این شماره لغو داده و دیگر پیامکی نمی‌گیرد.", 409)
        self.sms = message


def cancel(msg: SmsMessage) -> bool:
    if msg.state != SmsMessage.State.QUEUED:
        return False
    msg.state = SmsMessage.State.CANCELLED
    msg.save(update_fields=["state", "updated_at"])
    return True


# ------------------------------------------------------------------ claim

def in_quiet_hours(settings: MobileSettings, now=None) -> bool:
    hour = (now or timezone.now()).astimezone(TEHRAN).hour
    start, end = settings.quiet_start_hour, settings.quiet_end_hour
    if start == end:
        return False
    return hour >= start or hour < end if start > end else start <= hour < end


def expire_leases(now=None) -> int:
    now = now or timezone.now()
    n = SmsMessage.objects.filter(state=SmsMessage.State.QUEUED, expires_at__isnull=False, expires_at__lte=now).update(
        state=SmsMessage.State.FAILED, error="expired", error_code="expired")
    for msg in SmsMessage.objects.filter(state=SmsMessage.State.CLAIMED, lease_until__lt=now):
        if msg.kind != SmsMessage.Kind.MARKETING and msg.attempts < msg.max_attempts:
            changed = SmsMessage.objects.filter(pk=msg.pk, state=SmsMessage.State.CLAIMED).update(
                state=SmsMessage.State.QUEUED, device=None, lease_until=None, error="lease_expired")
        else:
            changed = SmsMessage.objects.filter(pk=msg.pk, state=SmsMessage.State.CLAIMED).update(
                state=SmsMessage.State.FAILED, error="lease_expired", error_code="lease_expired")
        n += changed
    return n


def usage(device: MobileDevice, settings: MobileSettings, now=None) -> dict:
    now = now or timezone.now()
    base = SmsMessage.objects.filter(device=device, claimed_at__isnull=False).exclude(state=SmsMessage.State.BLOCKED)
    hour = base.filter(claimed_at__gte=now - timedelta(hours=1))
    day = base.filter(claimed_at__gte=now - timedelta(days=1))
    sent_hour = hour.count()
    return {
        "sent_last_hour": sent_hour,
        "remaining_hour": max(0, settings.max_sms_per_hour - sent_hour),
        "remaining_day": max(0, settings.max_sms_per_day - day.count()),
        "marketing_hour": hour.filter(kind=SmsMessage.Kind.MARKETING).count(),
        "queued_total": SmsMessage.objects.filter(state=SmsMessage.State.QUEUED).count(),
    }


def claim(device: MobileDevice, max_n=None, sim_slot=None, now=None) -> dict:
    now = now or timezone.now()
    settings = MobileSettings.get()
    expire_leases(now)
    use = usage(device, settings, now)
    out = {"messages": [], "paused": False, "limited": None, "retry_after_s": settings.poll_interval_s,
           "limits": {"remaining_hour": use["remaining_hour"], "remaining_day": use["remaining_day"]}}
    if not settings.sms_enabled or not device.sms_enabled:
        out["paused"] = True
        out["retry_after_s"] = max(settings.poll_interval_s, 30)
        return out
    want = min(int(max_n or settings.claim_batch), settings.claim_batch)
    if use["remaining_hour"] <= 0:
        out["limited"] = "hour"
        out["retry_after_s"] = 60
        return out
    if use["remaining_day"] <= 0:
        out["limited"] = "day"
        out["retry_after_s"] = 600
        return out
    want = min(want, use["remaining_hour"], use["remaining_day"])
    marketing_left = max(0, settings.max_marketing_per_hour - use["marketing_hour"])
    quiet = in_quiet_hours(settings, now)

    candidates = SmsMessage.objects.filter(state=SmsMessage.State.QUEUED).filter(
        Q(not_before__isnull=True) | Q(not_before__lte=now)).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).order_by("id")
    if sim_slot is not None:
        candidates = candidates.filter(Q(sim_slot__isnull=True) | Q(sim_slot=sim_slot))
    claimed = []
    for msg in candidates[:200]:
        if len(claimed) >= want:
            break
        if is_opted_out(msg.to_number) and not (msg.kind == SmsMessage.Kind.OTP and settings.otp_ignores_opt_out):
            SmsMessage.objects.filter(pk=msg.pk, state=SmsMessage.State.QUEUED).update(state=SmsMessage.State.BLOCKED, error="opted_out")
            continue
        if msg.kind == SmsMessage.Kind.MARKETING:
            if quiet or marketing_left <= 0:
                continue
            approval = SmsCampaignApproval.objects.filter(ref=msg.campaign_ref).first()
            if approval is None or not approval.active:
                SmsMessage.objects.filter(pk=msg.pk, state=SmsMessage.State.QUEUED).update(state=SmsMessage.State.BLOCKED,
                                                                                         error="campaign_not_approved")
                continue
        with transaction.atomic():
            won = SmsMessage.objects.filter(pk=msg.pk, state=SmsMessage.State.QUEUED).update(
                state=SmsMessage.State.CLAIMED, device=device, claimed_at=now,
                lease_until=now + timedelta(seconds=settings.lease_seconds), attempts=F("attempts") + 1, error="")
            if not won:
                continue
            if msg.kind == SmsMessage.Kind.MARKETING:
                SmsCampaignApproval.objects.filter(ref=msg.campaign_ref).update(sent_count=F("sent_count") + 1)
                marketing_left -= 1
        msg.refresh_from_db()
        claimed.append(msg)
    out["messages"] = [{
        "uid": str(m.uid), "to": m.to_raw or phone.national(m.to_number), "normalized": m.to_number, "body": m.body,
        "kind": m.kind, "sim_slot": m.sim_slot, "attempt": m.attempts, "lease_seconds": settings.lease_seconds,
    } for m in claimed]
    if claimed:
        out["retry_after_s"] = 1
    after = usage(device, settings, now)
    out["limits"] = {"remaining_hour": after["remaining_hour"], "remaining_day": after["remaining_day"]}
    return out


# ------------------------------------------------------------------ report

def report(device: MobileDevice, msg: SmsMessage, state: str, error_code="", error="", at=None, parts=None) -> SmsMessage:
    if msg.device_id != device.id:
        raise MobileError("not_yours", "این پیامک به این گوشی داده نشده بود.", 403)
    state = (state or "").lower()
    if state not in ("sent", "delivered", "failed"):
        raise MobileError("bad_state", "وضعیت باید sent، delivered یا failed باشد.", 400)
    now = at or timezone.now()
    S = SmsMessage.State
    cur = msg.state
    if state == "sent":
        if cur in (S.SENT, S.DELIVERED):
            return msg
        msg.state, msg.sent_at, msg.error, msg.error_code = S.SENT, now, "", ""
    elif state == "delivered":
        if cur == S.DELIVERED:
            return msg
        msg.state, msg.delivered_at = S.DELIVERED, now
        msg.sent_at = msg.sent_at or now
        msg.error, msg.error_code = "", ""
    else:  # failed
        if cur in (S.SENT, S.DELIVERED, S.FAILED, S.CANCELLED):
            return msg           # a late failure never overrides a success
        code = (error_code or "").strip()[:40]
        if (msg.kind != SmsMessage.Kind.MARKETING and msg.attempts < msg.max_attempts and code in RETRYABLE):
            msg.state, msg.device, msg.lease_until = S.QUEUED, None, None
            msg.error, msg.error_code = (error or code)[:300], code
            msg.save()
            return msg
        msg.state = S.FAILED
        msg.error, msg.error_code = (error or code or "failed")[:300], code
    if parts:
        msg.parts = int(parts)
    msg.lease_until = None
    msg.save()
    return msg


# ------------------------------------------------------------------ incoming

def ingest_incoming(device: MobileDevice, items) -> dict:
    settings = MobileSettings.get()
    accepted = duplicates = opt_outs = 0
    for it in items[:200]:
        if not isinstance(it, dict):
            continue
        sender = phone.normalize(it.get("from"))
        body = str(it.get("body") or "")[:2000]
        if not sender:
            continue
        stop = phone.is_stop_text(body)
        if not settings.forward_incoming_sms and not stop:
            continue                       # not forwarded, not stored
        cid = str(it.get("client_id") or "").strip()[:80] or hashlib.sha1(f"{sender}|{it.get('received_at')}|{body}".encode()).hexdigest()
        received = _parse_dt(it.get("received_at"))
        row, created = SmsInbound.objects.get_or_create(
            device=device, dedupe_key=cid,
            defaults={"from_number": sender, "body": body if settings.forward_incoming_sms else "(لغو)", "received_at": received,
                      "sim_slot": it.get("sim_slot") if isinstance(it.get("sim_slot"), int) else None, "is_stop": stop})
        if not created:
            duplicates += 1
            continue
        accepted += 1
        if stop:
            _, new = add_opt_out(sender, SmsOptOut.Reason.STOP_REPLY, body, device=device)
            opt_outs += int(new)
    return {"accepted": accepted, "duplicates": duplicates, "opt_outs_added": opt_outs,
            "forwarding": settings.forward_incoming_sms}


def _parse_dt(value):
    from django.utils.dateparse import parse_datetime

    if not value:
        return None
    dt = parse_datetime(str(value))
    if dt and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt
