"""The send job: submits APPROVED items, one at a time, at most once each, inside every limit.

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

from ..models import Campaign, ItemStatus, OutreachItem, OutreachJob, SendAttempt
from . import campaigns, fingerprint, guard, heuristics, preparing
from .form_reasons import text_for

logger = logging.getLogger(__name__)

#: outcomes of ``post_form`` after which nothing at all left the server (so it is no attempt and costs no allowance)
NOTHING_SENT = (sh.ROBOTS_BLOCKED, sh.ROBOTS_UNAVAILABLE, sh.SSRF_BLOCKED, sh.BLOCKED_PORT, sh.BAD_URL, sh.DNS_ERROR)

RETURN_TO_APPROVED = (guard.CAMPAIGN_NOT_ACTIVE, guard.EMERGENCY_STOP, guard.SENDING_DISABLED, guard.IDENTITY_INCOMPLETE)
RETURN_TO_READY = (guard.NO_APPROVAL, guard.APPROVAL_INVALID)
TO_SKIPPED = (guard.SUPPRESSED, guard.ALREADY_CONTACTED, guard.DOMAIN_ALREADY_CONTACTED, guard.ALREADY_ATTEMPTED)


# --------------------------------------------------------------------------- small pieces


def claim(item_id: int) -> bool:
    """Take an approved item for sending. True for exactly one caller, however many race for it (at-most-once)."""
    return bool(OutreachItem.objects.filter(pk=item_id, status=ItemStatus.APPROVED).update(status=ItemStatus.SENDING, updated_at=timezone.now()))


def claim_next(campaign_id: int) -> OutreachItem | None:
    for item_id in OutreachItem.objects.filter(campaign_id=campaign_id, status=ItemStatus.APPROVED).order_by("id").values_list("id", flat=True)[:25]:
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
        item.plan = plan.to_dict()
        item.plan_checked_at = timezone.now()
        item.fingerprint = fingerprint.compute(item, plan)
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


def _send_one(job: OutreachJob, item: OutreachItem, fetcher, settings_obj: GrowthSettings) -> str:
    """Process one claimed item. Returns ``sent`` | ``failed`` | ``blocked``."""
    verdict = guard.check_item(item, phase=guard.SEND, settings_obj=settings_obj)
    if not verdict.ok:
        if verdict.code in RETURN_TO_APPROVED:
            _release(item, ItemStatus.APPROVED)
            return "blocked"
        if verdict.code in RETURN_TO_READY:
            return _blocked(job, item, verdict.code, verdict.text, ItemStatus.READY, clear_approval=True)
        status = ItemStatus.SKIPPED if verdict.code in TO_SKIPPED else ItemStatus.NEEDS_MANUAL
        return _blocked(job, item, verdict.code, verdict.text, status, clear_approval=True)

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
                item=item, url=plan.action_url[:500], method="POST", payload=payload, status_code=result.status, response_snippet=snippet,
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
        _advance_lead(item, job.created_by)
    return "sent" if accepted else "failed"


def _advance_lead(item: OutreachItem, actor) -> None:
    """After a message went out, a fresh lead becomes «تماس گرفته‌شده» (logged like any status change)."""
    try:
        if Lead.objects.filter(pk=item.lead_id, status__in=PRE_CONTACT_STATUSES).exists():
            editing.update_lead(item.lead, {"status": "contacted"}, actor)
    except Exception:  # noqa: BLE001 - the message is already sent; a status nicety must not undo anything
        logger.exception("could not advance lead %s to contacted", item.lead_id)


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
    try:
        while True:
            reason = stop_reason(job)
            if reason:
                return _stop(job, reason)
            settings_obj = GrowthSettings.load()
            if limits.cap_remaining(settings_obj) <= 0:
                return _finish(job, f"سقفِ روزانه ({settings_obj.daily_cap} پیام) پر شد؛ فردا با «ادامهٔ ارسال» ادامه بدهید.")
            item = claim_next(job.campaign_id)
            if item is None:
                return _finish(job, "")
            try:
                outcome = _send_one(job, item, fetcher, settings_obj)
            except Exception as exc:  # noqa: BLE001 - one broken item must not stop the others, nor be sent twice
                logger.exception("growth send job %s item %s failed", job.pk, item.pk)
                outcome = _crashed(job, item, exc)
            if outcome in ("sent", "failed") and _more_to_send(job, settings_obj):
                low, high = settings_obj.spacing_min_seconds, settings_obj.spacing_max_seconds
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
        with transaction.atomic():
            SendAttempt.objects.get_or_create(
                item=item, defaults={
                    "url": (item.target_url or "")[:500], "method": "POST", "outcome": "internal_error", "error": error,
                    "success_guess": SendAttempt.Guess.FAILURE,
                },
            )
            OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.SENDING).update(
                status=ItemStatus.FAILED, skip_reason="internal_error", skip_reason_text=error + " پس از ارسال؛ معلوم نیست پیام رفته یا نه.", updated_at=timezone.now()
            )
        _bump(job.pk, items_failed=1)
        return "failed"
    OutreachItem.objects.filter(pk=item.pk, status=ItemStatus.SENDING).update(
        status=ItemStatus.NEEDS_MANUAL, skip_reason="fetch_failed", skip_reason_text=error + " پیش از ارسال؛ چیزی فرستاده نشد.", approved_record=None, updated_at=timezone.now()
    )
    _bump(job.pk, items_blocked=1)
    return "blocked"


def _more_to_send(job: OutreachJob, settings_obj: GrowthSettings) -> bool:
    return limits.cap_remaining(settings_obj) > 0 and OutreachItem.objects.filter(campaign_id=job.campaign_id, status=ItemStatus.APPROVED).exists()


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
    return OutreachItem.objects.filter(campaign_id=campaign_id, status=ItemStatus.SENDING, updated_at__lt=cutoff).update(
        status=ItemStatus.FAILED, skip_reason="unknown_outcome",
        skip_reason_text="کارگر در میانهٔ ارسال متوقف شد؛ معلوم نیست پیام رفته یا نه. برای احتیاط دوباره تلاش نمی‌شود.", updated_at=timezone.now(),
    )


def prepare_resume(job: OutreachJob) -> bool:
    """Put a failed or stalled job back in the queue. False if it cannot be resumed."""
    if not can_resume(job):
        return False
    if job.kind == OutreachJob.Kind.SEND:
        recover_stuck(job.campaign_id)
    OutreachJob.objects.filter(pk=job.pk).update(status=OutreachJob.Status.QUEUED, error="", finished_at=None, cancel_requested=False, queued_at=timezone.now())
    return True
