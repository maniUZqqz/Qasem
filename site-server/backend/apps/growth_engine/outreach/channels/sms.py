"""The SMS channel: an adapter to NM-Mobile's gateway queue (``apps.mobile.api``).

The system never sends an SMS itself. It hands the approved message to the queue of the paired phone, which sends it from its own
SIM. NM-Mobile enforces, again and by itself: a campaign a human approved (we register it right before queueing, valid for a few
days only), its opt-out list (it also reads our do-not-contact list), the quiet hours (21:00-08:00), per-phone hourly / daily
caps and a global pause. So «ارسال شد» is honest only after the phone reports it: an item is ``handed_off`` until
``reconcile`` finds the message ``SENT`` / ``DELIVERED`` (or failed / cancelled).

The mobile app is optional: without it, or without a paired phone, the channel reports «نیاز به اپِ NM-Mobile» and stays off.
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.growth_engine.core import normalization as nz

from ..models import Channel, ItemStatus, OutreachItem, SendAttempt
from ..services import channel_config
from . import targets

logger = logging.getLogger(__name__)

APPROVAL_VALID_DAYS = 3
NEED_APP = "نیاز به اپِ NM-Mobile: "

_GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = "^{}\\[~]|€"


def segments(text: str) -> dict:
    """How many SMS parts ``text`` costs: ``{"parts", "length", "encoding", "single_limit", "part_limit"}``.

    GSM-7 (Latin, 160 / 153 per part) or UCS-2 (Persian and any other letter: 70 / 67 per part)."""
    text = text or ""
    if all(ch in _GSM7_BASIC or ch in _GSM7_EXT for ch in text):
        units = sum(2 if ch in _GSM7_EXT else 1 for ch in text)
        single, per = 160, 153
        encoding = "gsm7"
    else:
        units = len(text.encode("utf-16-le")) // 2  # characters outside the BMP take two units
        single, per = 70, 67
        encoding = "ucs2"
    parts = 0 if units == 0 else 1 if units <= single else math.ceil(units / per)
    return {"parts": parts, "length": units, "encoding": encoding, "single_limit": single, "part_limit": per}


# --------------------------------------------------------------------------- is the gateway there?


def _mobile():
    try:
        from apps.mobile import api as mobile
        from apps.mobile.models import MobileDevice, MobileSettings, SmsMessage

        return mobile, MobileDevice, MobileSettings, SmsMessage
    except Exception:  # noqa: BLE001 - the app is optional
        return None


def availability() -> tuple[bool, str, dict]:
    """(usable, Persian reason when not, {"devices", "online"})."""
    mod = _mobile()
    if mod is None:
        return False, NEED_APP + "این برنامه روی سرور نصب نیست.", {"devices": 0, "online": 0}
    _, MobileDevice, MobileSettings, _ = mod
    try:
        if not MobileSettings.get().sms_enabled:
            return False, "صفِ پیامکِ NM-Mobile خاموش است (در «دستگاه‌های موبایل» روشنش کنید).", {"devices": 0, "online": 0}
        devices = list(MobileDevice.objects.filter(revoked_at__isnull=True, sms_enabled=True))
    except Exception:  # noqa: BLE001 - tables missing: treated as "not there"
        return False, NEED_APP + "این برنامه آماده نیست.", {"devices": 0, "online": 0}
    online = sum(1 for d in devices if d.online)
    if not devices:
        return False, NEED_APP + "هنوز گوشی‌ای جفت نشده است.", {"devices": 0, "online": 0}
    return True, "", {"devices": len(devices), "online": online}


def is_opted_out(number: str) -> bool:
    mod = _mobile()
    if mod is None:
        return False
    try:
        return bool(mod[0].is_opted_out(number))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- the dry run


def prepare(item, growth) -> dict:
    problems: list[str] = []
    target = targets.resolve(item.lead, Channel.SMS)
    recipient = item.recipient or (target.recipient if target else "")
    if not recipient:
        problems.append(targets.no_target(Channel.SMS)[1])
    ok, reason, _ = availability()
    if not ok:
        problems.append(reason)
    seg = segments(item.rendered_text)
    max_parts = channel_config.sms_max_parts()
    if seg["parts"] > max_parts:
        problems.append(f"متنِ پیامک {seg['parts']} بخش است ولی حداکثر {max_parts} بخش مجاز است؛ متن را کوتاه‌تر کنید.")
    if recipient and is_opted_out(recipient):
        problems.append("این شماره قبلاً «لغو» داده و پیامکی نمی‌گیرد.")
    return {"channel": Channel.SMS, "ok": not problems, "problems": problems, "recipient": recipient, "sms": seg, "material": {"max_parts": max_parts}}


# --------------------------------------------------------------------------- handing a message to the phone


@dataclass
class QueueResult:
    ok: bool
    code: str = ""
    text: str = ""
    uid: str = ""


def campaign_ref(campaign_id: int) -> str:
    return f"ge:{campaign_id}"


def idempotency_key(item) -> str:
    return f"ge:{item.campaign_id}:item:{item.pk}"


def queue(item, actor) -> QueueResult:
    """Queue the item's message once. Never raises for a gateway refusal."""
    mod = _mobile()
    if mod is None:
        return QueueResult(False, "no_gateway", NEED_APP + "این برنامه روی سرور نیست.")
    mobile, _, _, _ = mod
    from apps.mobile.base import MobileError

    campaign = item.campaign
    ref = campaign_ref(campaign.pk)
    live = OutreachItem.objects.filter(
        campaign_id=campaign.pk, channel=Channel.SMS, status__in=[ItemStatus.APPROVED, ItemStatus.SENDING, ItemStatus.HANDED_OFF, ItemStatus.SENT],
    ).count()
    try:
        mobile.register_campaign_approval(
            ref, campaign.name, approved_by=(item.approved_record.approved_by if item.approved_record_id else None) or actor,
            valid_until=timezone.now() + timedelta(days=APPROVAL_VALID_DAYS), max_messages=max(live, 1), source="growth_engine",
        )
        message, _created = mobile.queue_sms(
            item.recipient, item.rendered_text, kind="marketing", campaign_ref=ref, idempotency_key=idempotency_key(item), created_by=actor,
        )
    except mobile.OptedOut:
        return QueueResult(False, "opted_out", "این شماره «لغو» داده و پیامکی نمی‌گیرد.")
    except MobileError as exc:
        return QueueResult(False, exc.code, exc.message)
    return QueueResult(True, uid=str(message.uid))


# --------------------------------------------------------------------------- what the phone did


_FAILED_TEXT = {
    "no_service": "گوشی آنتن نداشت", "radio_off": "رادیوی گوشی خاموش بود", "generic": "گوشی نتوانست پیامک را بفرستد", "timeout": "گوشی در زمانِ مقرر گزارش نداد",
    "null_pdu": "گوشی پیامک را نساخت", "lease_expired": "گوشی در زمانِ مقرر گزارش نداد",
}


def _apply(item: OutreachItem, message) -> bool:
    """Move ``item`` to match the phone's report. True when something changed."""
    state = message.state
    new_status, outcome, guess, reason_code, reason_text = None, "", SendAttempt.Guess.UNCLEAR, "", ""
    if state in ("SENT", "DELIVERED"):
        new_status, outcome, guess = ItemStatus.SENT, "sent_by_phone" if state == "SENT" else "delivered", SendAttempt.Guess.SUCCESS
    elif state == "FAILED":
        why = _FAILED_TEXT.get(message.error_code) or "گوشی نتوانست پیامک را بفرستد"
        new_status, outcome, guess = ItemStatus.FAILED, "failed_on_phone", SendAttempt.Guess.FAILURE
        reason_code, reason_text = "phone_failed", f"{why}. برای احتیاط دوباره تلاش نمی‌شود."
    elif state in ("CANCELLED", "BLOCKED"):
        new_status, outcome = ItemStatus.CANCELLED, "cancelled_before_sent"
        blocked = {"opted_out": "این شماره لغو داده بود", "campaign_revoked": "کمپین متوقف یا لغو شد", "campaign_not_approved": "تأییدِ کمپین در گوشی نبود"}
        reason_code = message.error or "cancelled"
        reason_text = (blocked.get(message.error) or "پیامک پیش از ارسال لغو شد") + "؛ از گوشی فرستاده نشد."
    if new_status is None:
        return False  # still QUEUED / CLAIMED: the phone has not finished
    with transaction.atomic():
        changed = OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.HANDED_OFF).update(
            status=new_status, skip_reason=reason_code[:40], skip_reason_text=reason_text[:400], updated_at=timezone.now(),
        )
        if not changed:
            return False
        SendAttempt.objects.filter(item_id=item.pk).update(outcome=outcome[:24], success_guess=guess, error=reason_text[:400] if new_status != ItemStatus.SENT else "")
        from apps.growth_engine.leads.choices import ActivityKind
        from apps.growth_engine.leads.services import history

        history.log_activity(
            item.lead, ActivityKind.QUEUE_OUTCOME, actor=None,
            summary={"sent": "پیامک از گوشی فرستاده شد", "failed": "ارسالِ پیامک از گوشی ناموفق بود", "cancelled": "پیامک پیش از ارسال لغو شد"}[
                "sent" if new_status == ItemStatus.SENT else "failed" if new_status == ItemStatus.FAILED else "cancelled"],
            data={"outcome": outcome, "channel": Channel.SMS, "campaign_id": item.campaign_id, "item_id": item.pk, "sms_uid": str(message.uid), "error": reason_text},
        )
    if new_status == ItemStatus.SENT:
        from ..services import sending

        sending.advance_lead(item, None)
    return True


def reconcile(campaign_id: int | None = None) -> int:
    """Bring ``handed_off`` items up to date with what the phone reported. Returns how many changed. Safe to call any time."""
    mod = _mobile()
    if mod is None:
        return 0
    _, _, _, SmsMessage = mod
    items = list(OutreachItem.objects.filter(status=ItemStatus.HANDED_OFF, channel=Channel.SMS).select_related("lead", "campaign")
                 .filter(**({"campaign_id": campaign_id} if campaign_id else {})))
    if not items:
        return 0
    messages = {m.idempotency_key: m for m in SmsMessage.objects.filter(idempotency_key__in=[idempotency_key(i) for i in items])}
    changed = 0
    lost_before = timezone.now() - timedelta(minutes=10)
    for item in items:
        message = messages.get(idempotency_key(item))
        if message is None:
            if item.updated_at < lost_before:  # handed over (or crashed while doing so) but the queue has no such message
                done = OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.HANDED_OFF).update(
                    status=ItemStatus.FAILED, skip_reason="not_in_queue", skip_reason_text="پیامک در صفِ گوشی پیدا نشد؛ برای احتیاط دوباره تلاش نمی‌شود.",
                    updated_at=timezone.now(),
                )
                changed += done
            continue
        try:
            changed += 1 if _apply(item, message) else 0
        except Exception:  # noqa: BLE001 - one item must not stop the others
            logger.exception("growth sms reconcile failed for item %s", item.pk)
    return changed


def revoke_pending(campaign_id: int | None = None) -> int:
    """Stop every message of the campaign (or of all campaigns) the phone has not sent yet. Returns how many items became final."""
    mod = _mobile()
    if mod is None:
        return 0
    mobile = mod[0]
    qs = OutreachItem.objects.filter(status=ItemStatus.HANDED_OFF, channel=Channel.SMS)
    if campaign_id:
        qs = qs.filter(campaign_id=campaign_id)
    campaign_ids = set(qs.values_list("campaign_id", flat=True))
    for cid in campaign_ids:
        try:
            mobile.revoke_campaign(campaign_ref(cid))
        except Exception:  # noqa: BLE001
            logger.exception("growth sms revoke failed for campaign %s", cid)
    return reconcile(campaign_id)


def body_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def digits_of(recipient: str) -> str:
    try:
        return nz.normalize_phone(recipient).e164
    except nz.NormalizationError:
        return recipient
