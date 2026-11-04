"""The send job: submits APPROVED items, one at a time, at most once each, inside every limit.

An item is sent through ITS channel: a contact form (POST, below), an e-mail (SMTP, ``channels/email.py``) or an SMS (queued for the
paired phone, ``channels/sms.py``). Every channel goes through the same steps 1-4 and 6-8; step 5 (the fresh look at the target) is
the form re-read for a form, and the fresh e-mail account / phone / text check (inside the guard) for the others. Each channel has its
own daily cap and spacing on top of the global ones.

For each item, in this order (nothing is skipped):

1. stop checks - emergency stop, automatic sending switched off, identity incomplete, campaign not active, job cancelled;
2. the global daily cap (counted from ``SendAttempt`` rows, Tehran day, all campaigns);
3. CLAIM the item with a conditional UPDATE ``approved -> sending`` (two workers can never both get it);
4. the guard (six validations);
5. a FRESH read of the form page and a new analysis: a page that is not eligible any more, or whose fingerprint differs from
   the approved one (message, target, action or field set changed), is NOT posted - the item goes back to ``ready`` /
   ``needs_manual`` with its approval void;
6. one last stop check, then ``post_form`` ONCE (never retried: a timed-out POST may have been delivered);
7. ``SendAttempt`` (the exact payload, hidden token values redacted), the item status, a ``LeadActivity`` with the exact
   message and payload, an audit entry - in one transaction;
8. spacing: ``rng.uniform(min, max)`` seconds, slept in one-second slices that re-check the stop conditions. No wait after
   the last item.
"""
from __future__ import annotations

import logging
import random
import time

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.growth_engine.compliance.models import AuditKind, GrowthSettings
from apps.growth_engine.compliance.services import audit, limits
from apps.growth_engine.core import conf
from apps.growth_engine.core.dbretry import retry_locked
from apps.growth_engine.integrations import safe_http as sh
from apps.growth_engine.leads.choices import PRE_CONTACT_STATUSES, ActivityKind
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services import editing, history

from ..channels import email as email_channel
from ..channels import sms as sms_channel
from ..models import Campaign, Channel, ItemStatus, OutreachItem, OutreachJob, SendAttempt
from . import campaigns, channel_config, fingerprint, guard, heuristics, preparing
from .form_reasons import text_for

logger = logging.getLogger(__name__)

#: outcomes of ``post_form`` after which nothing at all left the server (so it is no attempt and costs no allowance)
NOTHING_SENT = (sh.ROBOTS_BLOCKED, sh.ROBOTS_UNAVAILABLE, sh.SSRF_BLOCKED, sh.BLOCKED_PORT, sh.BAD_URL, sh.DNS_ERROR)

RETURN_TO_APPROVED = (guard.CAMPAIGN_NOT_ACTIVE, guard.EMERGENCY_STOP, guard.SENDING_DISABLED, guard.IDENTITY_INCOMPLETE, guard.CHANNEL_DISABLED)
RETURN_TO_READY = (guard.NO_APPROVAL, guard.APPROVAL_INVALID)
TO_SKIPPED = (guard.SUPPRESSED, guard.ALREADY_CONTACTED, guard.DOMAIN_ALREADY_CONTACTED, guard.ALREADY_ATTEMPTED, guard.CHANNEL_OPTED_OUT)

#: e-mail outcomes after which nothing reached the recipient (a refusal, or the session never started): no attempt is recorded
EMAIL_NOT_DELIVERED = ("auth_failed", "recipient_refused", "sender_refused", "data_refused", "connect_error", "tls_error", "not_sent")


# --------------------------------------------------------------------------- small pieces


def claim(item_id: int) -> bool:
    """Take an approved item for sending. True for exactly one caller, however many race for it (at-most-once)."""
    return bool(OutreachItem.objects.filter(pk=item_id, status=ItemStatus.APPROVED).update(status=ItemStatus.SENDING, updated_at=timezone.now()))


def claim_next(campaign_id: int, exclude_channels: set[str] | None = None) -> OutreachItem | None:
    queryset = OutreachItem.objects.filter(campaign_id=campaign_id, status=ItemStatus.APPROVED)
    if exclude_channels:
        queryset = queryset.exclude(channel__in=list(exclude_channels))
    for item_id in queryset.order_by("id").values_list("id", flat=True)[:25]:
        if claim(item_id):
            return OutreachItem.objects.select_related("lead", "campaign", "campaign__template", "approved_record").get(pk=item_id)
    return None


def stop_reason(job: OutreachJob) -> str:
    """Why the job must stop right now ("" = carry on). Re-read from the database every time."""
    settings_obj = GrowthSettings.load()
    if settings_obj.emergency_stop:
        return "توقفِ اضطراری فعال شد؛ ارسال متوقف شد."
    if not settings_obj.sending_enabled:
        return "ارسالِ خودکار در تنظیمات خاموش شد؛ ارسال متوقف شد."
    if settings_obj.identity_problems():
        return "مشخصاتِ فرستنده در تنظیمات ناقص است؛ ارسال متوقف شد."
    status = Campaign.objects.filter(pk=job.campaign_id).values_list("status", flat=True).first()
    if status != Campaign.Status.ACTIVE:
        return "کمپین متوقف یا بسته شد؛ ارسال متوقف شد."
    row = OutreachJob.objects.filter(pk=job.pk).values_list("cancel_requested", "status").first()
    if row and (row[0] or row[1] == OutreachJob.Status.CANCELLED):
        return "به درخواستِ کاربر متوقف شد."
    return ""


def _bump(job_id: int, **counters: int) -> None:
    updates = {name: F(name) + n for name, n in counters.items()}
    OutreachJob.objects.filter(pk=job_id).update(processed_items=F("processed_items") + 1, heartbeat_at=timezone.now(), **updates)


def _redacted_payload(plan) -> list[dict]:
    """The exact fields posted, in order; the values of hidden (page-given token) fields are not stored."""
    return [{"name": f.name, "value": "***" if f.hidden else f.value} for f in plan.fields if f.name]


def _release(item: OutreachItem, status: str, *, reason: str = "", text: str = "", clear_approval: bool = False, plan=None) -> None:
    """Move a claimed item to ``status`` with a reason (and optionally a refreshed plan / voided approval)."""
    fields = {"status": status, "skip_reason": reason[:40], "skip_reason_text": text[:400], "updated_at": timezone.now()}
    if clear_approval:
        fields["approved_record"] = None
    if plan is not None:
        item.plan = plan if isinstance(plan, dict) else plan.to_dict()  # a dict = the dry run of an e-mail / SMS item
        item.plan_checked_at = timezone.now()
        item.fingerprint = fingerprint.compute(item, None if isinstance(plan, dict) else plan)
        fields.update(plan=item.plan, plan_checked_at=item.plan_checked_at, fingerprint=item.fingerprint)
    OutreachItem.objects.filter(pk=item.pk).update(**fields)


def _blocked(job: OutreachJob, item: OutreachItem, code: str, text: str, status: str, *, clear_approval: bool = False, plan=None) -> str:
    _release(item, status, reason=code, text=text, clear_approval=clear_approval, plan=plan)
    audit.log(
        AuditKind.SEND, job.created_by, f"ارسال برای لید {item.lead_id} انجام نشد: {text}",
        {"item_id": item.pk, "campaign_id": item.campaign_id, "blocked": code, "status": status},
    )
    _bump(job.pk, items_blocked=1)
    return "blocked"


# --------------------------------------------------------------------------- one item


def _fresh_plan(item: OutreachItem):
    """For e-mail / SMS items the guard put the freshly computed dry run on the item; keep it with the release."""
    return item.plan if item.channel != Channel.CONTACT_FORM and isinstance(item.plan, dict) else None


def _send_one(job: OutreachJob, item: OutreachItem, fetcher, settings_obj: GrowthSettings) -> str:
    """Process one claimed item. Returns ``sent`` | ``failed`` | ``blocked`` | ``channel_off`` (this channel must be skipped for the rest of the run)."""
    verdict = guard.check_item(item, phase=guard.SEND, settings_obj=settings_obj)
    if not verdict.ok:
        if verdict.code == guard.CHANNEL_DISABLED:
            _release(item, ItemStatus.APPROVED)
            return "channel_off"
        if verdict.code in RETURN_TO_APPROVED:
            _release(item, ItemStatus.APPROVED)
            return "blocked"
        if verdict.code in RETURN_TO_READY:
            return _blocked(job, item, verdict.code, verdict.text, ItemStatus.READY, clear_approval=True, plan=_fresh_plan(item))
        status = ItemStatus.SKIPPED if verdict.code in TO_SKIPPED else ItemStatus.NEEDS_MANUAL
        return _blocked(job, item, verdict.code, verdict.text, status, clear_approval=True, plan=_fresh_plan(item))
    if item.channel == Channel.EMAIL:
        return _send_email(job, item)
    if item.channel == Channel.SMS:
        return _send_sms(job, item)
    return _send_form(job, item, fetcher, settings_obj)


def _send_form(job: OutreachJob, item: OutreachItem, fetcher, settings_obj: GrowthSettings) -> str:
    """The contact-form channel: a FRESH read of the page, the fingerprint check, then the one POST."""
    analysis = preparing.analyse(item, fetcher, settings_obj)  # a FRESH read of the page
    if not analysis.eligible:
        return _blocked(job, item, analysis.code or "form_not_eligible", analysis.text or guard.TEXTS[guard.FORM_NOT_ELIGIBLE],
                        ItemStatus.NEEDS_MANUAL, clear_approval=True, plan=analysis.plan)
    plan = analysis.plan
    if fingerprint.compute(item, plan) != item.approved_record.fingerprint:
        text = "فرمِ صفحه نسبت به زمانِ تأیید عوض شده؛ چیزی فرستاده نشد. دوباره بررسی و تأیید کنید."
        audit.log(AuditKind.APPROVAL, job.created_by, f"تأیید باطل شد (لید {item.lead_id}): فرم عوض شده", {"item_id": item.pk, "why": "form_changed"})
        return _blocked(job, item, "form_changed", text, ItemStatus.READY, clear_approval=True, plan=plan)

    reason = stop_reason(job)
    if reason:  # a stop arrived while we were reading the page: nothing is sent
        _release(item, ItemStatus.APPROVED)
        return "blocked"

    # ---- the one and only POST of this item
    item._post_started = True  # from here on an exception means "maybe delivered", never "safe to try again"
    result = fetcher.post_form(plan.action_url, plan.payload_pairs(), multipart=plan.enctype == "multipart", referer=plan.page_url)
    if result.outcome in NOTHING_SENT:
        code = "robots_blocked" if result.outcome == sh.ROBOTS_BLOCKED else "robots_unavailable" if result.outcome == sh.ROBOTS_UNAVAILABLE else "fetch_failed"
        text = text_for(code) if code != "fetch_failed" else f"{text_for(code)} ({result.label})"
        return _blocked(job, item, code, f"چیزی فرستاده نشد. {text}", ItemStatus.NEEDS_MANUAL, clear_approval=True, plan=plan)
    return _record_attempt(job, item, plan, result)


def _payload_of(item: OutreachItem, **extra) -> list[dict]:
    """What was handed over, as ``[{name, value}]``: recipient, subject and the message's sha256 (the text itself is on the lead's history)."""
    pairs = {"to": item.recipient, "subject": item.subject, "message_sha256": fingerprint.message_sha256(item.rendered_text), **extra}
    return [{"name": k, "value": str(v)} for k, v in pairs.items() if v not in (None, "")]


def _record_simple(job: OutreachJob, item: OutreachItem, *, status: str, url: str, method: str, payload: list[dict], guess: str, outcome: str,
                   error: str, snippet: str, summary: str, activity: dict, elapsed_ms: int = 0, count: str = "items_sent") -> str:
    """One transaction: the attempt, the item's new status, the lead's history, the audit entry, the job's counter."""

    def record() -> None:
        with transaction.atomic():
            SendAttempt.objects.create(
                item=item, channel=item.channel, url=url[:500], method=method, payload=payload, status_code=0, response_snippet=snippet[:500],
                success_guess=guess, outcome=outcome[:24], error=error[:400], elapsed_ms=elapsed_ms,
            )
            OutreachItem.objects.filter(pk=item.pk).update(
                status=status, skip_reason="" if status in (ItemStatus.SENT, ItemStatus.HANDED_OFF) else "send_failed",
                skip_reason_text="" if status in (ItemStatus.SENT, ItemStatus.HANDED_OFF) else error[:400], updated_at=timezone.now(),
            )
            data = {
                "channel": item.channel, "message_text": item.rendered_text, "subject": item.subject, "recipient": item.recipient,
                "payload": payload, "error": error, "campaign_id": item.campaign_id, "template_id": item.template_id or item.campaign.template_id,
                "item_id": item.pk, **activity,
            }
            history.log_activity(item.lead, ActivityKind.QUEUE_OUTCOME, actor=job.created_by, summary=summary, data=data)
            audit.log(
                AuditKind.SEND, job.created_by, f"ارسال برای لید {item.lead_id} ({Channel(item.channel).label}): {outcome}",
                {"item_id": item.pk, "campaign_id": item.campaign_id, "channel": item.channel, "status": status, "outcome": outcome},
            )
            _bump(job.pk, **{count: 1})

    # the message may already be out: never lose its record to a SQLite lock conflict - repeat the whole (atomic) write
    retry_locked(record, attempts=10)
    return "sent" if status in (ItemStatus.SENT, ItemStatus.HANDED_OFF) else "failed"


def _send_email(job: OutreachJob, item: OutreachItem) -> str:
    """The e-mail channel: the guard already looked at the account, the address and the approval just now."""
    if stop_reason(job):
        _release(item, ItemStatus.APPROVED)
        return "blocked"
    item._post_started = True  # from here on an exception means "maybe delivered"
    started = time.monotonic()
    result = email_channel.send(item)
    elapsed = int((time.monotonic() - started) * 1000)
    if not result.ok and result.code in EMAIL_NOT_DELIVERED:
        return _blocked(job, item, f"email_{result.code}", f"چیزی فرستاده نشد. {result.text}", ItemStatus.NEEDS_MANUAL, clear_approval=True, plan=_fresh_plan(item))
    cfg = channel_config.smtp_settings()
    payload = _payload_of(item, **{"from": cfg["from_email"], "reply_to": cfg["reply_to"]})
    if result.ok:
        outcome = _record_simple(
            job, item, status=ItemStatus.SENT, url=f"mailto:{item.recipient}", method="SMTP", payload=payload, guess=SendAttempt.Guess.SUCCESS,
            outcome="smtp_accepted", error="", snippet=result.detail, summary="ایمیل فرستاده شد (سرورِ ایمیل پذیرفت)", activity={"outcome": "sent", "from": cfg["from_email"]},
            elapsed_ms=elapsed,
        )
        advance_lead(item, job.created_by)
        return outcome
    return _record_simple(  # a timeout / a dropped session: the message may have been delivered, so it is never tried again
        job, item, status=ItemStatus.FAILED, url=f"mailto:{item.recipient}", method="SMTP", payload=payload, guess=SendAttempt.Guess.UNCLEAR,
        outcome=result.code, error=result.text, snippet="", summary="ارسالِ ایمیل ناموفق بود: " + result.text, activity={"outcome": "failed", "from": cfg["from_email"]},
        elapsed_ms=elapsed, count="items_failed",
    )


def _send_sms(job: OutreachJob, item: OutreachItem) -> str:
    """The SMS channel: hand the message to the phone's queue. «ارسال شد» is only claimed after the phone reports (``reconcile``)."""
    if stop_reason(job):
        _release(item, ItemStatus.APPROVED)
        return "blocked"
    item._post_started = True
    started = time.monotonic()
    result = sms_channel.queue(item, job.created_by)
    elapsed = int((time.monotonic() - started) * 1000)
    if not result.ok:
        if result.code == "opted_out":
            return _blocked(job, item, guard.CHANNEL_OPTED_OUT, guard.TEXTS[guard.CHANNEL_OPTED_OUT], ItemStatus.SKIPPED, clear_approval=True, plan=_fresh_plan(item))
        return _blocked(job, item, f"sms_{result.code}"[:40], f"چیزی به صفِ گوشی داده نشد. {result.text}", ItemStatus.NEEDS_MANUAL, clear_approval=True, plan=_fresh_plan(item))
    parts = (item.plan or {}).get("sms", {}).get("parts") or sms_channel.segments(item.rendered_text)["parts"]
    return _record_simple(
        job, item, status=ItemStatus.HANDED_OFF, url=f"sms:{item.recipient}", method="SMS", payload=_payload_of(item, parts=parts, sms_uid=result.uid),
        guess=SendAttempt.Guess.UNCLEAR, outcome="queued_on_phone", error="", snippet=f"صفِ گوشی · {result.uid}",
        summary="پیامک به صفِ گوشی داده شد (گوشی می‌فرستد)", activity={"outcome": "queued_on_phone", "sms_uid": result.uid, "parts": parts}, elapsed_ms=elapsed,
    )


def _record_attempt(job: OutreachJob, item: OutreachItem, plan, result) -> str:
    guess = heuristics.judge(result.status, result.text, outcome=result.outcome)
    snippet = heuristics.visible_text(result.text)
    accepted = result.outcome == sh.OK and 200 <= result.status < 400 and guess != SendAttempt.Guess.FAILURE
    status = ItemStatus.SENT if accepted else ItemStatus.FAILED
    error = "" if accepted else (result.label if result.outcome != sh.OK else f"پاسخ HTTP {result.status}" + (" (متنِ پاسخ شبیهِ خطا بود)" if result.status < 400 else ""))
    payload = _redacted_payload(plan)

    def record() -> None:
        with transaction.atomic():
            SendAttempt.objects.create(
                item=item, channel=Channel.CONTACT_FORM, url=plan.action_url[:500], method="POST", payload=payload, status_code=result.status, response_snippet=snippet,
                success_guess=guess, outcome=result.outcome[:24], error=error[:400], elapsed_ms=result.elapsed_ms,
            )
            OutreachItem.objects.filter(pk=item.pk).update(
                status=status, skip_reason="" if accepted else "send_failed", skip_reason_text="" if accepted else error[:400], updated_at=timezone.now()
            )
            data = {
                "outcome": "sent" if accepted else "failed", "channel": "contact_form", "message_text": item.rendered_text, "subject": item.subject,
                "target_url": item.target_url, "action_url": plan.action_url, "payload": payload, "http_status": result.status,
                "success_guess": guess, "response_snippet": snippet, "error": error, "campaign_id": item.campaign_id,
                "template_id": item.campaign.template_id, "item_id": item.pk,
            }
            history.log_activity(
                item.lead, ActivityKind.QUEUE_OUTCOME, actor=job.created_by,
                summary=("پیام از راهِ فرمِ سایت فرستاده شد" if accepted else "ارسالِ پیام از راهِ فرمِ سایت ناموفق بود") + f" (HTTP {result.status or '—'})", data=data,
            )
            audit.log(
                AuditKind.SEND, job.created_by, f"ارسال برای لید {item.lead_id}: HTTP {result.status or '—'} · {guess}",
                {"item_id": item.pk, "campaign_id": item.campaign_id, "status": status, "http_status": result.status, "success_guess": guess},
            )
            _bump(job.pk, **({"items_sent": 1} if accepted else {"items_failed": 1}))

    # the message may already be delivered: never lose its record to a SQLite lock conflict - repeat the whole (atomic) write
    retry_locked(record, attempts=10)
    if accepted:
        advance_lead(item, job.created_by)
    return "sent" if accepted else "failed"


def advance_lead(item: OutreachItem, actor) -> None:
    """After a message went out, a fresh lead becomes «تماس گرفته‌شده» (logged like any status change)."""
    try:
        if Lead.objects.filter(pk=item.lead_id, status__in=PRE_CONTACT_STATUSES).exists():
            editing.update_lead(item.lead, {"status": "contacted"}, actor)
    except Exception:  # noqa: BLE001 - the message is already sent; a status nicety must not undo anything
        logger.exception("could not advance lead %s to contacted", item.lead_id)


_advance_lead = advance_lead  # the old private name (kept for the form path above)


# --------------------------------------------------------------------------- the job


def run_send(job_id: int, *, sleep=None, rng=None, fetcher_factory=None) -> str:
    """Execute (or resume) a send job. Returns the final status. ``sleep`` / ``rng`` are injectable for tests."""
    job = OutreachJob.objects.select_related("campaign", "campaign__template").filter(pk=job_id, kind=OutreachJob.Kind.SEND).first()
    if job is None:
        return "missing"
    if job.is_finished:
        return job.status
    if job.cancel_requested:
        job.mark_finished(OutreachJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        return job.status
    sleep = sleep or time.sleep
    rng = rng or random.Random()
    fetcher = (fetcher_factory or preparing.make_fetcher)()
    job.mark_running()
    switched_off: set[str] = set()  # channels the operator turned off while this run was going: their items wait, the rest go on
    try:
        while True:
            reason = stop_reason(job)
            if reason:
                return _stop(job, reason)
            settings_obj = GrowthSettings.load()
            if limits.cap_remaining(settings_obj) <= 0:
                return _finish(job, f"سقفِ روزانه ({settings_obj.daily_cap} پیام) پر شد؛ فردا با «ادامهٔ ارسال» ادامه بدهید.")
            capped = channel_config.capped_channels()
            item = claim_next(job.campaign_id, capped | switched_off)
            if item is None:
                return _finish(job, _waiting_note(job.campaign_id, capped, switched_off))
            try:
                outcome = _send_one(job, item, fetcher, settings_obj)
            except Exception as exc:  # noqa: BLE001 - one broken item must not stop the others, nor be sent twice
                logger.exception("growth send job %s item %s failed", job.pk, item.pk)
                outcome = _crashed(job, item, exc)
            if outcome == "channel_off":
                switched_off.add(item.channel)
                continue
            if outcome in ("sent", "failed") and _more_to_send(job, settings_obj, capped | switched_off):
                low, high = channel_config.spacing_for(item.channel, settings_obj)
                if _spacing_wait(job, rng.uniform(low, high), sleep):
                    return _stop(job, stop_reason(job) or "ارسال متوقف شد.")
    except Exception as exc:  # noqa: BLE001 - infrastructure (database ...), not one item's problem
        logger.exception("growth send job %s failed", job.pk)
        job.refresh_from_db()
        job.mark_finished(OutreachJob.Status.FAILED, f"کار با خطای داخلی متوقف شد ({type(exc).__name__}). می‌توانید «ادامه» را بزنید.")
        return job.status
    finally:
        fetcher.close()


def _crashed(job: OutreachJob, item: OutreachItem, exc: Exception) -> str:
    """An unexpected exception while handling a claimed item.

    If the POST may have gone out (it was started, or a ``SendAttempt`` exists) the item is ``failed`` and a minimal
    ``SendAttempt`` is made sure to exist, so the cap and the duplicate rules still see it and it is never sent again.
    If nothing was posted yet, the item goes to the manual queue."""
    posted = getattr(item, "_post_started", False) or SendAttempt.objects.filter(item_id=item.pk).exists()
    error = f"خطای داخلی ({type(exc).__name__})"
    if posted:
        sms = item.channel == Channel.SMS  # it may be in the phone's queue: keep it where ``reconcile`` will settle it
        with transaction.atomic():
            SendAttempt.objects.get_or_create(
                item=item, defaults={
                    "channel": item.channel, "url": (item.target_url or item.recipient or "")[:500], "method": {"email": "SMTP", "sms": "SMS"}.get(item.channel, "POST"),
                    "outcome": "internal_error", "error": error, "success_guess": SendAttempt.Guess.FAILURE,
                },
            )
            OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.SENDING).update(
                status=ItemStatus.HANDED_OFF if sms else ItemStatus.FAILED, skip_reason="internal_error",
                skip_reason_text=error + " پس از ارسال؛ معلوم نیست پیام رفته یا نه.", updated_at=timezone.now(),
            )
        _bump(job.pk, items_failed=1)
        return "failed"
    OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.SENDING).update(
        status=ItemStatus.NEEDS_MANUAL, skip_reason="fetch_failed", skip_reason_text=error + " پیش از ارسال؛ چیزی فرستاده نشد.", approved_record=None, updated_at=timezone.now()
    )
    _bump(job.pk, items_blocked=1)
    return "blocked"


def _more_to_send(job: OutreachJob, settings_obj: GrowthSettings, skip_channels: set[str] | None = None) -> bool:
    queryset = OutreachItem.objects.filter(campaign_id=job.campaign_id, status=ItemStatus.APPROVED)
    if skip_channels:
        queryset = queryset.exclude(channel__in=list(skip_channels))
    return limits.cap_remaining(settings_obj) > 0 and queryset.exists()


def _waiting_note(campaign_id: int, capped: set[str], switched_off: set[str]) -> str:
    """Why approved items are still waiting when the job has nothing it may send right now ("" = nothing is waiting)."""
    waiting = list(OutreachItem.objects.filter(campaign_id=campaign_id, status=ItemStatus.APPROVED).values_list("channel", flat=True).distinct())
    notes = []
    for channel in waiting:
        label = Channel(channel).label
        if channel in switched_off:
            notes.append(f"کانالِ «{label}» خاموش است")
        elif channel in capped:
            notes.append(f"سقفِ روزانهٔ کانالِ «{label}» پر شد")
    return ("؛ ".join(notes) + "؛ فردا یا پس از روشن کردن با «ادامهٔ ارسال» ادامه بدهید.") if notes else ""


def _spacing_wait(job: OutreachJob, seconds: float, sleep) -> bool:
    """Wait ``seconds`` in one-second slices. True when a stop condition appeared (the caller ends the job)."""
    remaining = float(seconds)
    while remaining > 0:
        step = min(1.0, remaining)
        sleep(step)
        remaining -= step
        OutreachJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now())
        if stop_reason(job):
            return True
    return False


def _finish(job: OutreachJob, note: str) -> str:
    job.refresh_from_db()
    job.note = note[:400]
    job.save(update_fields=["note"])
    job.mark_finished(OutreachJob.Status.COMPLETED)
    try:
        sms_channel.reconcile(job.campaign_id)  # messages the phone has already settled
    except Exception:  # noqa: BLE001 - the job is done; the panel's refresh will try again
        logger.exception("growth sms reconcile after job %s failed", job.pk)
    campaigns.maybe_complete(job.campaign)
    return job.status


def _stop(job: OutreachJob, reason: str) -> str:
    job.refresh_from_db()
    job.mark_finished(OutreachJob.Status.CANCELLED, reason)
    return job.status


# --------------------------------------------------------------------------- user actions on a job


def request_cancel(job: OutreachJob) -> OutreachJob:
    if job.is_finished:
        return job
    if job.status == OutreachJob.Status.QUEUED:
        job.cancel_requested = True
        job.save(update_fields=["cancel_requested"])
        job.mark_finished(OutreachJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        return job
    OutreachJob.objects.filter(pk=job.pk).update(cancel_requested=True)
    job.refresh_from_db()
    return job


def can_resume(job: OutreachJob) -> bool:
    return job.status == OutreachJob.Status.FAILED or job.is_stalled


def recover_stuck(campaign_id: int) -> int:
    """Items left in ``sending`` by a worker that died: whether they were posted is unknown, so they are marked ``failed``
    (never retried automatically) instead of risking a second message."""
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(seconds=int(conf.get("JOB_STALL_SECONDS")))
    stuck = OutreachItem.objects.filter(campaign_id=campaign_id, status=ItemStatus.SENDING, updated_at__lt=cutoff)
    # an SMS may already sit in the phone's queue: ``reconcile`` settles it by looking there (and marks it failed if it is not there)
    handed = stuck.filter(channel=Channel.SMS).update(status=ItemStatus.HANDED_OFF, skip_reason="unknown_outcome", updated_at=timezone.now())
    others = stuck.exclude(channel=Channel.SMS).update(
        status=ItemStatus.FAILED, skip_reason="unknown_outcome",
        skip_reason_text="کارگر در میانهٔ ارسال متوقف شد؛ معلوم نیست پیام رفته یا نه. برای احتیاط دوباره تلاش نمی‌شود.", updated_at=timezone.now(),
    )
    return handed + others


def prepare_resume(job: OutreachJob) -> bool:
    """Put a failed or stalled job back in the queue. False if it cannot be resumed."""
    if not can_resume(job):
        return False
    if job.kind == OutreachJob.Kind.SEND:
        recover_stuck(job.campaign_id)
    OutreachJob.objects.filter(pk=job.pk).update(status=OutreachJob.Status.QUEUED, error="", finished_at=None, cancel_requested=False, queued_at=timezone.now())
    return True
