"""Row handling shared by every kind of discovery job (CSV rows, provider candidates).

One item = one transaction: the row's outcome and the job's counters + resume cursor are written together, so a worker that
dies in the middle leaves the database consistent and the job continues after ``cursor``. An item never kills the job:
problems become ``DiscoveryJobRow`` rows (the report), duplicates become rows that wait for a person's decision.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.growth_engine.core.dbretry import retry_locked
from apps.growth_engine.leads.services.dedupe import DuplicateMatch
from apps.growth_engine.leads.services.drafts import LeadDraft
from apps.growth_engine.leads.services.intake import DuplicateError, SourceInfo, create_from_draft

from ..models import DiscoveryJob, DiscoveryJobRow

logger = logging.getLogger(__name__)


def match_payload(matches: list[DuplicateMatch]) -> list[dict]:
    return [{"lead_id": m.lead.pk, "name": m.lead.display_name, "matched_on": m.matched_on} for m in matches]


def bump(job_id: int, row_number: int, **counters: int) -> None:
    updates = {name: F(name) + n for name, n in counters.items()}
    DiscoveryJob.objects.filter(pk=job_id).update(
        processed_items=F("processed_items") + 1, cursor=row_number, heartbeat_at=timezone.now(), **updates
    )


def should_cancel(job: DiscoveryJob) -> bool:
    fresh = DiscoveryJob.objects.filter(pk=job.pk).values_list("cancel_requested", "status").first()
    return bool(fresh and (fresh[0] or fresh[1] == DiscoveryJob.Status.CANCELLED))


def process_draft(job: DiscoveryJob, number: int, draft: LeadDraft, errors: list[dict], row_raw: dict, source: SourceInfo) -> None:
    """Create the lead (or record the error / the duplicate) for one item and advance the job. Never raises for an item's problem."""

    def attempt() -> None:
        with transaction.atomic():
            if errors:
                DiscoveryJobRow.objects.update_or_create(
                    job=job, row_number=number, defaults={"status": DiscoveryJobRow.Status.ERROR, "raw": row_raw, "errors": errors}
                )
                bump(job.pk, number, error_count=1)
                return
            try:
                create_from_draft(draft, source, job.created_by)
            except DuplicateError as dup:
                DiscoveryJobRow.objects.update_or_create(
                    job=job, row_number=number,
                    defaults={
                        "status": DiscoveryJobRow.Status.DUPLICATE, "raw": row_raw, "payload": draft.to_payload(),
                        "matches": match_payload(dup.matches), "matched_lead": dup.matches[0].lead,
                    },
                )
                bump(job.pk, number, duplicate_count=1)
                return
            bump(job.pk, number, created_count=1)

    def record_failure(exc: Exception) -> None:
        with transaction.atomic():
            DiscoveryJobRow.objects.update_or_create(
                job=job, row_number=number,
                defaults={
                    "status": DiscoveryJobRow.Status.ERROR, "raw": row_raw,
                    "errors": [{"field": "__row__", "code": "internal_error", "message": f"خطای داخلی هنگام ثبتِ این ردیف ({type(exc).__name__})."}],
                },
            )
            bump(job.pk, number, error_count=1)

    try:
        retry_locked(attempt)  # a SQLite lock conflict is retried; it is never recorded as a bad row
    except Exception as exc:  # noqa: BLE001 - one broken item must not stop the job
        logger.exception("growth discovery job %s item %s failed", job.pk, number)
        retry_locked(lambda: record_failure(exc))
