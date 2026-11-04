"""Preparing items: fetch the lead's contact page, decide whether its form may be submitted, store the dry run.

``analyse`` (no database writes) is shared with the send job, which runs it again on a FRESH copy of the page right before
posting. The prepare job (``run_prepare``) walks the items of a campaign with the same per-item transaction + counters +
cursor discipline as the CSV import and the extraction job.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.dbretry import retry_locked
from apps.growth_engine.integrations import safe_http as sh
from apps.growth_engine.integrations.safe_http import SafeFetcher

from ..models import Campaign, ItemStatus, OutreachItem, OutreachJob
from . import fingerprint, generators, targets
from .campaigns import CampaignError
from .form_analysis import FormPlan, Reason, SenderIdentity, analyze_page
from .form_reasons import text_for

logger = logging.getLogger(__name__)

#: a ``needs_manual`` item with one of these reasons is worth looking at again when «آماده‌سازی» is pressed
RETRYABLE_REASONS = ("fetch_failed", "robots_unavailable", "no_target_url")
PREPARABLE = (ItemStatus.PENDING, ItemStatus.READY)


def make_fetcher() -> SafeFetcher:
    """One fetcher per job run (it caches robots.txt per host). Tests replace this function."""
    return SafeFetcher()


def sender_identity(settings_obj: GrowthSettings) -> SenderIdentity:
    return SenderIdentity(
        name=settings_obj.sender_name, company=settings_obj.sender_company, phone=settings_obj.sender_phone,
        email=settings_obj.sender_email, website=settings_obj.sender_website,
    )


@dataclass
class Analysis:
    plan: FormPlan | None
    code: str = ""  # "" = eligible, else the reason code
    text: str = ""
    fetch_status: int = 0

    @property
    def eligible(self) -> bool:
        return self.plan is not None and self.plan.eligible and not self.code


def analyse(item: OutreachItem, fetcher: SafeFetcher, settings_obj: GrowthSettings) -> Analysis:
    """Read the item's target page and say whether (and how) its form may be submitted. Writes nothing."""
    url = item.target_url
    if not url:
        return Analysis(None, "no_target_url", text_for("no_target_url"))
    result = fetcher.get_page(url)
    if result.outcome in (sh.ROBOTS_BLOCKED, sh.ROBOTS_UNAVAILABLE):
        return Analysis(None, result.outcome, text_for(result.outcome), result.status)
    readable = result.outcome == sh.OK or (result.outcome == sh.HTTP_ERROR and result.status in (401, 403, 429, 503) and result.text)
    if not readable:
        return Analysis(None, "fetch_failed", f"{text_for('fetch_failed')} ({result.label})", result.status)
    plan = analyze_page(
        result.text, result.final_url or url, fetch_status=result.status, fetch_final_url=result.final_url or "",
        sender=sender_identity(settings_obj), message=item.rendered_text, subject=item.subject,
    )
    if plan.eligible and plan.action_url:
        allowed, state = fetcher.robots_allows(plan.action_url)
        if not allowed:
            code = "robots_unavailable" if state == "unavailable" else "robots_blocked"
            plan.verdict = "skip"
            plan.reasons.append(Reason(code=code, text=text_for(code)))
    if not plan.eligible:
        first = plan.reasons[0] if plan.reasons else Reason("form_not_eligible", "این فرم را نمی‌شود خودکار فرستاد.")
        return Analysis(plan, first.code, first.text, result.status)
    return Analysis(plan, "", "", result.status)


def store_analysis(item: OutreachItem, analysis: Analysis) -> None:
    """Write the dry run onto the item (caller saves in its own transaction)."""
    item.plan = analysis.plan.to_dict() if analysis.plan is not None else {}
    item.plan_checked_at = timezone.now()
    if analysis.eligible:
        item.status, item.skip_reason, item.skip_reason_text = ItemStatus.READY, "", ""
    else:
        item.status, item.skip_reason, item.skip_reason_text = ItemStatus.NEEDS_MANUAL, analysis.code[:40], analysis.text[:400]
    item.approved_record = None
    item.fingerprint = fingerprint.compute(item, analysis.plan)


def prepare_item(item: OutreachItem, fetcher: SafeFetcher, settings_obj: GrowthSettings) -> str:
    """Analyse one item and save the result. Returns the item's new status."""
    if suppression.matches_for_lead(item.lead):
        item.status, item.skip_reason = ItemStatus.SKIPPED, "suppressed"
        item.skip_reason_text = "در فهرستِ «تماس نگیر» است."
        item.save(update_fields=["status", "skip_reason", "skip_reason_text", "updated_at"])
        return item.status
    if not item.target_url:
        item.target_url = targets.target_url(item.lead)
    if not item.text_edited:  # pick up identity / lead changes made since the lead was added
        built = generators.build_message(item.campaign.template, item.lead, settings_obj)
        item.rendered_text, item.subject = built.text, built.subject
    analysis = analyse(item, fetcher, settings_obj)  # the slow part: no transaction is open

    def store() -> None:
        with transaction.atomic():
            store_analysis(item, analysis)
            item.save()

    retry_locked(store)  # a SQLite lock conflict is retried
    return item.status


# --------------------------------------------------------------------------- the job


def create_prepare_job(campaign: Campaign, user=None) -> OutreachJob:
    """Queue (but not enqueue) a prepare job for the items that need it; returns a running one if there already is one."""
    if campaign.mode != Campaign.Mode.AUTO:
        raise CampaignError("manual_campaign", "کمپینِ «صفِ دستی» آماده‌سازیِ فرم ندارد.")
    if campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELLED):
        raise CampaignError("campaign_closed", "این کمپین بسته شده است.")
    running = campaign.jobs.filter(kind=OutreachJob.Kind.PREPARE, status__in=[OutreachJob.Status.QUEUED, OutreachJob.Status.RUNNING]).first()
    if running and not running.is_stalled:
        return running
    wanted = Q(status__in=PREPARABLE) | Q(status=ItemStatus.NEEDS_MANUAL, skip_reason__in=RETRYABLE_REASONS)
    ids = list(campaign.items.filter(wanted).order_by("id").values_list("id", flat=True))
    if not ids:
        raise CampaignError("nothing_to_prepare", "موردی برای آماده‌سازی نیست.")
    return OutreachJob.objects.create(
        campaign=campaign, kind=OutreachJob.Kind.PREPARE, params={"item_ids": ids}, total_items=len(ids),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _bump(job_id: int, index: int, **counters: int) -> None:
    updates = {name: F(name) + n for name, n in counters.items()}
    OutreachJob.objects.filter(pk=job_id).update(processed_items=F("processed_items") + 1, cursor=index, heartbeat_at=timezone.now(), **updates)


def _stop_requested(job_id: int) -> bool:
    row = OutreachJob.objects.filter(pk=job_id).values_list("cancel_requested", "status").first()
    return bool(row and (row[0] or row[1] == OutreachJob.Status.CANCELLED))


def run_prepare(job_id: int) -> str:
    """Execute (or resume) a prepare job. Never raises for one item's problem."""
    job = OutreachJob.objects.select_related("campaign", "campaign__template").filter(pk=job_id, kind=OutreachJob.Kind.PREPARE).first()
    if job is None:
        return "missing"
    if job.is_finished:
        return job.status
    if job.cancel_requested:
        job.mark_finished(OutreachJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        return job.status
    job.mark_running()
    item_ids = [int(i) for i in (job.params or {}).get("item_ids", [])]
    settings_obj = GrowthSettings.load()
    fetcher = make_fetcher()
    try:
        for index, item_id in enumerate(item_ids, 1):
            if index <= job.cursor:
                continue
            if _stop_requested(job.pk):
                job.refresh_from_db()
                job.mark_finished(OutreachJob.Status.CANCELLED, "به درخواستِ کاربر متوقف شد؛ موردهای آماده‌شده می‌مانند.")
                return job.status
            item = OutreachItem.objects.select_related("lead", "campaign", "campaign__template").filter(pk=item_id).first()
            if item is None or item.status not in (*PREPARABLE, ItemStatus.NEEDS_MANUAL):
                _bump(job.pk, index)
                continue
            try:
                status = prepare_item(item, fetcher, settings_obj)
                _bump(job.pk, index, items_blocked=0 if status == ItemStatus.READY else 1)
            except Exception as exc:  # noqa: BLE001 - one broken item must not stop the job
                logger.exception("growth outreach prepare job %s item %s failed", job.pk, item_id)
                OutreachItem.objects.filter(pk=item_id).update(
                    status=ItemStatus.NEEDS_MANUAL, skip_reason="fetch_failed", skip_reason_text=f"خطای داخلی هنگام بررسیِ فرم ({type(exc).__name__}).",
                    updated_at=timezone.now(),
                )
                _bump(job.pk, index, items_failed=1)
    except Exception as exc:  # noqa: BLE001 - infrastructure
        logger.exception("growth outreach prepare job %s failed", job.pk)
        job.refresh_from_db()
        job.mark_finished(OutreachJob.Status.FAILED, f"کار با خطای داخلی متوقف شد ({type(exc).__name__}). می‌توانید «ادامه» را بزنید.")
        return job.status
    finally:
        fetcher.close()
    job.refresh_from_db()
    job.mark_finished(OutreachJob.Status.COMPLETED)
    return job.status
