"""Extraction jobs: creating them and running them.

How a job stays correct (same ideas as the CSV import)
------------------------------------------------------
* The slow part - fetching a site - happens OUTSIDE any transaction. Then, in ONE transaction, the lead's
  results, its page log, the run row, the job counters and the resume cursor are written together. A worker that
  dies mid-crawl therefore leaves nothing half-written, and ``run_extraction`` continues after ``cursor``.
* One bad lead never stops the job (it becomes a ``failed`` run with ``internal_error``).
* ``cancel_requested`` is polled between leads and between pages; a cancelled crawl discards its partial result.
* Leads without a website, and leads read successfully within ``EXTRACT_RECENT_DAYS``, are skipped (visibly) unless
  ``force``.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.growth_engine.core import conf
from apps.growth_engine.core.dbretry import retry_locked
from apps.growth_engine.discovery.models import DiscoveryJob
from apps.growth_engine.integrations.safe_http import SafeFetcher
from apps.growth_engine.leads.models import Lead

from ..models import ExtractionJob, ExtractionPageLog, ExtractionRun
from . import apply, crawler

logger = logging.getLogger(__name__)


def make_fetcher() -> SafeFetcher:
    """One fetcher per job run (it caches robots.txt per host). Tests replace this function."""
    return SafeFetcher()


class JobRequestError(ValueError):
    """The request cannot become a job. The message is Persian and shown to the user."""


# --------------------------------------------------------------------------- creating jobs


def _recent_success_ids(lead_ids, *, exclude_job_id: int | None = None) -> set[int]:
    cutoff = timezone.now() - timedelta(days=int(conf.get("EXTRACT_RECENT_DAYS")))
    queryset = ExtractionRun.objects.filter(lead_id__in=list(lead_ids), status=ExtractionRun.Status.DONE, finished_at__gte=cutoff)
    if exclude_job_id:
        queryset = queryset.exclude(job_id=exclude_job_id)
    return set(queryset.values_list("lead_id", flat=True))


def create_jobs(user, *, lead_ids: list[int] | None = None, discovery_job_id: int | None = None, force: bool = False) -> list[ExtractionJob]:
    """Create the job(s) for ``lead_ids`` or for every lead of a CSV import. The caller enqueues them.

    A CSV import with more leads than ``EXTRACT_MAX_LEADS_PER_JOB`` becomes several jobs (chunks). Raises
    ``JobRequestError`` when the request is malformed or nothing in it can be read."""
    limit = int(conf.get("EXTRACT_MAX_LEADS_PER_JOB"))
    if bool(lead_ids) == bool(discovery_job_id):
        raise JobRequestError("یا فهرستِ لیدها را بدهید یا یک ورودی CSV؛ هر دو یا هیچ‌کدام نشد.")
    discovery_job = None
    if lead_ids:
        ids = list(dict.fromkeys(int(i) for i in lead_ids))
        if len(ids) > limit:
            raise JobRequestError(f"در هر کار حداکثر {limit} لید را می‌شود انتخاب کرد؛ کمتر انتخاب کنید.")
        found = {lead.pk: lead for lead in Lead.objects.filter(pk__in=ids)}
        leads = [found[i] for i in ids if i in found]
        if not leads:
            raise JobRequestError("هیچ‌کدام از لیدهای انتخاب‌شده پیدا نشد.")
        scope = ExtractionJob.Scope.SINGLE if len(leads) == 1 else ExtractionJob.Scope.SELECTED
    else:
        discovery_job = DiscoveryJob.objects.filter(pk=discovery_job_id).first()
        if discovery_job is None:
            raise JobRequestError("آن ورودیِ CSV پیدا نشد.")
        leads = list(Lead.objects.filter(sources__job=discovery_job).exclude(website="").distinct().order_by("id"))
        if not leads:
            raise JobRequestError("هیچ‌کدام از لیدهای این ورودی وب‌سایت ندارد؛ چیزی برای استخراج نیست.")
        scope = ExtractionJob.Scope.CSV_IMPORT

    with_site = [lead for lead in leads if lead.website]
    recent = set() if force else _recent_success_ids([lead.pk for lead in with_site])
    eligible = [lead for lead in with_site if lead.pk not in recent]
    if not eligible:
        raise JobRequestError(
            f"چیزی برای خواندن نیست: {len(leads) - len(with_site)} لید وب‌سایت ندارد و {len(recent)} لید به‌تازگی (در {conf.get('EXTRACT_RECENT_DAYS')} روزِ گذشته) "
            "استخراج شده است. برای خواندنِ دوباره «اجبار» را بزنید."
        )

    ordered = [lead.pk for lead in leads]
    chunks = [ordered[i : i + limit] for i in range(0, len(ordered), limit)]
    jobs: list[ExtractionJob] = []
    with transaction.atomic():
        for chunk in chunks:
            job = ExtractionJob.objects.create(
                scope=scope, discovery_job=discovery_job, params={"lead_ids": chunk, "force": bool(force)}, total_items=len(chunk), created_by=user,
            )
            ExtractionRun.objects.bulk_create(ExtractionRun(job=job, lead_id=lead_id) for lead_id in chunk)
            jobs.append(job)
    return jobs


# --------------------------------------------------------------------------- running a job


def _bump(job_id: int, index: int, **counters: int) -> None:
    updates = {name: F(name) + n for name, n in counters.items()}
    ExtractionJob.objects.filter(pk=job_id).update(
        processed_items=F("processed_items") + 1, cursor=index, heartbeat_at=timezone.now(), **updates
    )


def _heartbeat(job_id: int) -> None:
    ExtractionJob.objects.filter(pk=job_id).update(heartbeat_at=timezone.now())


def _stop_requested(job_id: int) -> bool:
    row = ExtractionJob.objects.filter(pk=job_id).values_list("cancel_requested", "status").first()
    return bool(row and (row[0] or row[1] == ExtractionJob.Status.CANCELLED))


def run_extraction(job_id: int) -> str:
    """Execute (or resume) an extraction job. Returns the final status. Never raises for a lead's problems."""
    job = ExtractionJob.objects.filter(pk=job_id).first()
    if job is None:
        return "missing"
    if job.is_finished:
        return job.status
    if job.cancel_requested:
        job.mark_finished(ExtractionJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        return job.status
    job.mark_running()
    lead_ids = [int(i) for i in (job.params or {}).get("lead_ids", [])]
    force = bool((job.params or {}).get("force"))
    fetcher = make_fetcher()
    try:
        for index, lead_id in enumerate(lead_ids, 1):
            if index <= job.cursor:
                continue
            if _stop_requested(job.pk):
                return _cancel(job)
            if _process_lead(job, lead_id, index, fetcher, force) == "aborted":
                return _cancel(job)
    except Exception as exc:  # noqa: BLE001 - infrastructure (database, ...) not one lead's problem
        logger.exception("growth extraction job %s failed", job.pk)
        job.refresh_from_db()
        job.mark_finished(ExtractionJob.Status.FAILED, f"کار با خطای داخلی متوقف شد ({type(exc).__name__}). می‌توانید «ادامه» را بزنید.")
        return job.status
    finally:
        fetcher.close()
    job.refresh_from_db()
    job.mark_finished(ExtractionJob.Status.COMPLETED)
    return job.status


def _cancel(job: ExtractionJob) -> str:
    job.refresh_from_db()
    job.mark_finished(ExtractionJob.Status.CANCELLED, "به درخواستِ کاربر متوقف شد؛ لیدهای قبلاً خوانده‌شده می‌مانند.")
    return job.status


def _recently_extracted(lead_id: int, job_id: int) -> bool:
    return lead_id in _recent_success_ids([lead_id], exclude_job_id=job_id)


def _process_lead(job: ExtractionJob, lead_id: int, index: int, fetcher: SafeFetcher, force: bool) -> str:
    lead = Lead.objects.filter(pk=lead_id).first()
    if lead is None:  # deleted after the job was created
        _bump(job.pk, index, runs_skipped=1)
        return "skipped"
    run, _ = ExtractionRun.objects.get_or_create(job=job, lead=lead)
    reason = "no_website" if not lead.website else ("" if force or not _recently_extracted(lead.pk, job.pk) else "recent")
    if reason:
        def record_skip() -> None:
            with transaction.atomic():
                ExtractionRun.objects.filter(pk=run.pk).update(status=ExtractionRun.Status.SKIPPED, reason=reason, finished_at=timezone.now())
                _bump(job.pk, index, runs_skipped=1)

        retry_locked(record_skip)
        return "skipped"

    ExtractionRun.objects.filter(pk=run.pk).update(status=ExtractionRun.Status.RUNNING, started_at=timezone.now())
    try:
        crawl = crawler.crawl_site(
            lead.website, fetcher, heartbeat=lambda: _heartbeat(job.pk), should_stop=lambda: _stop_requested(job.pk),
        )
        if crawl.aborted or _stop_requested(job.pk):
            ExtractionRun.objects.filter(pk=run.pk).update(status=ExtractionRun.Status.QUEUED, started_at=None)
            return "aborted"
        retry_locked(lambda: _save_result(job, run, lead, crawl, index))  # SQLite lock conflicts are retried
        return "failed" if crawl.status == "failed" else "done"
    except Exception as exc:  # noqa: BLE001 - one broken lead must not stop the job
        logger.exception("growth extraction job %s lead %s failed", job.pk, lead_id)

        def record_failure() -> None:
            with transaction.atomic():
                ExtractionPageLog.objects.filter(run=run).delete()
                ExtractionRun.objects.filter(pk=run.pk).update(
                    status=ExtractionRun.Status.FAILED, reason="internal_error", finished_at=timezone.now(), findings=[],
                )
                _bump(job.pk, index, runs_failed=1)

        retry_locked(record_failure)
        return "failed"


def _save_result(job: ExtractionJob, run: ExtractionRun, lead: Lead, crawl: crawler.CrawlResult, index: int) -> None:
    """Everything that belongs to one lead's outcome, in one transaction (see the module docstring)."""
    now = timezone.now()
    with transaction.atomic():
        ExtractionPageLog.objects.filter(run=run).delete()
        ExtractionPageLog.objects.bulk_create(
            ExtractionPageLog(run=run, url=e.url[:500], kind=e.kind, status=e.status, outcome=e.outcome[:24], elapsed_ms=e.elapsed_ms, bytes=e.bytes, note=e.note[:300])
            for e in crawl.logs
        )
        run.pages_fetched = crawl.pages_fetched
        run.robots_state = crawl.robots_state[:16]
        run.finished_at = now
        if crawl.status == "done":
            result = apply.apply_findings(
                lead, run, crawl.findings, actor=job.created_by, home_url=crawl.home_url,
                pages=[e.url for e in crawl.logs if e.kind != "robots" and e.outcome == "ok"],
            )
            run.status, run.reason, run.findings, run.contacts_added = ExtractionRun.Status.DONE, "", result.records, result.contacts_added
            summary = f"استخراج از سایت: {result.contacts_added} راهِ تماسِ تازه" + (f"، {len(result.fields_filled)} فیلد پر شد" if result.fields_filled else "")
            apply.log_run_activity(
                lead, run, summary,
                {"run_id": run.pk, "job_id": job.pk, "pages_fetched": crawl.pages_fetched, "contacts_added": result.contacts_added,
                 "fields_filled": result.fields_filled, "findings": len(result.records)},
                actor=job.created_by,
            )
            counters = {"runs_done": 1, "pages_fetched": crawl.pages_fetched, "contacts_added": result.contacts_added}
        else:
            run.status, run.reason, run.findings, run.contacts_added = ExtractionRun.Status.FAILED, crawl.reason, [], 0
            apply.log_run_activity(
                lead, run, f"استخراج از سایت انجام نشد: {run.reason_label}",
                {"run_id": run.pk, "job_id": job.pk, "reason": crawl.reason, "pages_fetched": crawl.pages_fetched}, actor=job.created_by,
            )
            counters = {"runs_failed": 1, "pages_fetched": crawl.pages_fetched}
        run.save()
        _bump(job.pk, index, **counters)


# --------------------------------------------------------------------------- user actions


def request_cancel(job: ExtractionJob) -> ExtractionJob:
    if job.is_finished:
        return job
    if job.status == ExtractionJob.Status.QUEUED:
        job.cancel_requested = True
        job.save(update_fields=["cancel_requested"])
        job.mark_finished(ExtractionJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        return job
    ExtractionJob.objects.filter(pk=job.pk).update(cancel_requested=True)
    job.refresh_from_db()
    return job


def can_resume(job: ExtractionJob) -> bool:
    return job.status == ExtractionJob.Status.FAILED or job.is_stalled


def prepare_resume(job: ExtractionJob) -> bool:
    """Put a failed or stalled job back in the queue; it continues after its cursor. False if it cannot."""
    if not can_resume(job):
        return False
    ExtractionJob.objects.filter(pk=job.pk).update(
        status=ExtractionJob.Status.QUEUED, error="", finished_at=None, cancel_requested=False, queued_at=timezone.now()
    )
    return True
