"""CSV import: dry-run check, job creation, the job itself, and resolving duplicate rows.

How the job stays correct
-------------------------
* Each row is handled in its own transaction, and the job's counters + resume cursor are
  updated **in the same transaction**. A worker that dies mid-file leaves the database
  consistent, and ``run_import`` continues after ``cursor`` instead of starting over.
* A row never kills the job: errors become ``DiscoveryJobRow`` rows (the row-level report),
  duplicates become rows waiting for the user's decision. Nothing is overwritten automatically.
* ``cancel_requested`` is polled every few rows; rows already handled stay.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.growth_engine.core import conf, csvio
from apps.growth_engine.leads.services.drafts import LeadDraft, build_draft
from apps.growth_engine.leads.services.intake import DuplicateError, SourceInfo, create_from_draft, merge_draft_into
from apps.growth_engine.sources import provenance
from apps.growth_engine.sources.models import SourceProvider

from ..models import DiscoveryJob, DiscoveryJobRow
from ..signals import discovery_job_finished
from . import csv_mapping, csv_upload
from . import rows as rowops

logger = logging.getLogger(__name__)
CANCEL_POLL_EVERY = 20
RESOLVE_BATCH = 500


# --------------------------------------------------------------------------- shared row handling


def _parse(data: bytes) -> tuple[list[str], list[tuple[int, list[str]]], str]:
    text, encoding = csvio.decode_bytes(data)
    headers, rows, _ = csvio.read_table(text, max_rows=conf.get("CSV_MAX_ROWS"))
    return headers, rows, encoding


def _draft_for_row(headers, cells, mapping, *, file_name, row_number, params) -> tuple[LeadDraft, list[dict], dict]:
    raw = csv_mapping.row_to_raw(headers, cells, mapping)
    draft, errors = build_draft(
        raw, source_ref=provenance.csv_ref(file_name, row_number),
        default_country=params.get("default_country", ""), default_city=params.get("default_city", ""),
    )
    extra = [t for t in params.get("tags", []) if t]
    if extra:
        draft.tags = list(dict.fromkeys([*draft.tags, *extra]))
    return draft, list(errors), raw


_match_payload = rowops.match_payload


# --------------------------------------------------------------------------- dry run


def check_mapping(data: bytes, file_name: str, mapping: dict, *, default_country: str = "", default_city: str = "") -> dict:
    """Validate every row under ``mapping`` WITHOUT touching the database. Returns counts + samples."""
    headers, rows, _ = _parse(data)
    cleaned = csv_mapping.validate_mapping(mapping, headers)
    params = {"default_country": default_country, "default_city": default_city}
    valid = 0
    errors_out: list[dict] = []
    sample: list[dict] = []
    preview_n = conf.get("CSV_PREVIEW_ROWS")
    for number, cells in rows:
        draft, errors, _ = _draft_for_row(headers, cells, cleaned, file_name=file_name, row_number=number, params=params)
        if errors:
            if len(errors_out) < 20:
                errors_out.append({"row": number, "errors": errors})
        else:
            valid += 1
        if len(sample) < preview_n:
            sample.append({
                "row": number, "ok": not errors, "errors": errors,
                "summary": {
                    "business_name": draft.business_name,
                    "website": draft.website.value if draft.website else "",
                    "instagram": draft.instagram.value if draft.instagram else "",
                    "phones": [c.value for c in draft.contacts_of("phone")],
                    "emails": [c.value for c in draft.contacts_of("email")],
                    "city": draft.city, "country": draft.country, "category": draft.category, "tags": draft.tags,
                },
            })
    return {
        "total_rows": len(rows), "valid_rows": valid, "error_rows": len(rows) - valid,
        "errors": errors_out, "sample": sample, "mapping": cleaned,
    }


# --------------------------------------------------------------------------- job creation


def create_import_job(user, upload_id: str, mapping: dict, *, default_country: str = "", default_city: str = "",
                      tags: list[str] | None = None, extract_after: bool = False) -> DiscoveryJob:
    """Validate the mapping and queue nothing yet: the caller dispatches the Celery task after commit."""
    data, file_name = csv_upload.load_upload(user.pk, upload_id)
    headers, rows, encoding = _parse(data)
    cleaned = csv_mapping.validate_mapping(mapping, headers)
    data_path, _ = csv_upload._paths(user.pk, upload_id)
    return DiscoveryJob.objects.create(
        kind=DiscoveryJob.Kind.CSV_IMPORT, file_name=file_name, stored_name=data_path, encoding=encoding,
        total_items=len(rows), created_by=user,
        params={
            "mapping": cleaned, "default_country": default_country, "default_city": default_city,
            "tags": [t for t in (tags or []) if t][:20], "extract_after": bool(extract_after),
        },
    )


# --------------------------------------------------------------------------- the job


_bump = rowops.bump
_should_cancel = rowops.should_cancel


def run_import(job_id: int) -> str:
    """Execute (or resume) an import job. Returns the final status. Never raises for row problems."""
    job = DiscoveryJob.objects.filter(pk=job_id).first()
    if job is None:
        return "missing"
    if job.is_finished:
        return job.status
    if job.cancel_requested:
        job.mark_finished(DiscoveryJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        _after_finish(job)
        return job.status
    job.mark_running()
    try:
        with default_storage.open(job.stored_name, "rb") as fh:
            data = fh.read()
    except (FileNotFoundError, OSError, ValueError):
        job.mark_finished(DiscoveryJob.Status.FAILED, "فایلِ آپلودشده دیگر در سرور نیست؛ دوباره آپلود کنید.")
        _after_finish(job)
        return job.status
    try:
        headers, rows, _ = _parse(data)
    except csvio.CsvError as exc:
        job.mark_finished(DiscoveryJob.Status.FAILED, exc.message)
        _after_finish(job)
        return job.status

    params = job.params or {}
    mapping = params.get("mapping", {})
    seen = 0
    try:
        for number, cells in rows:
            if number <= job.cursor:
                continue
            if seen % CANCEL_POLL_EVERY == 0 and _should_cancel(job):
                job.refresh_from_db()
                job.mark_finished(DiscoveryJob.Status.CANCELLED, "به درخواستِ کاربر متوقف شد؛ ردیف‌های قبلاً ثبت‌شده می‌مانند.")
                _after_finish(job)
                return job.status
            seen += 1
            _process_row(job, headers, cells, number, mapping, params)
    except Exception as exc:  # noqa: BLE001 - infrastructure failure (DB locked ...), not a bad row
        logger.exception("growth csv import job %s failed", job.pk)
        job.refresh_from_db()
        job.mark_finished(DiscoveryJob.Status.FAILED, f"کار با خطای داخلی متوقف شد ({type(exc).__name__}). می‌توانید «ادامه» را بزنید.")
        return job.status
    job.refresh_from_db()
    job.mark_finished(DiscoveryJob.Status.COMPLETED)
    _after_finish(job)
    return job.status


def _process_row(job: DiscoveryJob, headers, cells, number: int, mapping: dict, params: dict) -> None:
    draft, errors, raw = _draft_for_row(headers, cells, mapping, file_name=job.file_name, row_number=number, params=params)
    row_raw = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers)}
    source = SourceInfo(provider=SourceProvider.CSV_IMPORT, source_ref=provenance.csv_ref(job.file_name, number), job=job, raw_data=row_raw)
    rowops.process_draft(job, number, draft, errors, row_raw, source)


def _after_finish(job: DiscoveryJob) -> None:
    if job.stored_name:
        csv_upload.delete_upload_files(job.stored_name)
        DiscoveryJob.objects.filter(pk=job.pk).update(stored_name="")
    discovery_job_finished.send(sender=DiscoveryJob, job=job)


# --------------------------------------------------------------------------- user actions on a job


def request_cancel(job: DiscoveryJob) -> DiscoveryJob:
    if job.is_finished:
        return job
    if job.status == DiscoveryJob.Status.QUEUED:
        job.cancel_requested = True
        job.save(update_fields=["cancel_requested"])
        job.mark_finished(DiscoveryJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        _after_finish(job)
        return job
    DiscoveryJob.objects.filter(pk=job.pk).update(cancel_requested=True)
    job.refresh_from_db()
    return job


def prepare_resume(job: DiscoveryJob) -> bool:
    """Put a stalled or failed job back in the queue; the run continues after its cursor. False if it cannot."""
    resumable = job.status == DiscoveryJob.Status.FAILED or job.is_stalled
    needs_file = job.kind != DiscoveryJob.Kind.SEARCH  # a search that failed before fetching has nothing stored: it simply fetches again
    if not resumable or (needs_file and not job.stored_name):
        return False
    DiscoveryJob.objects.filter(pk=job.pk).update(
        status=DiscoveryJob.Status.QUEUED, error="", finished_at=None, cancel_requested=False, queued_at=timezone.now()
    )
    return True


# --------------------------------------------------------------------------- the row report


ERROR_HEADER_EXTRA = ["ردیف در فایل", "خطا"]


def errors_csv_stream(job: DiscoveryJob) -> Iterator[bytes]:
    """The error rows as a CSV with their original columns plus the reasons - fix it and import it again."""
    rows = list(job.rows.filter(status=DiscoveryJobRow.Status.ERROR).order_by("row_number"))
    headers: list[str] = []
    for row in rows:
        for h in row.raw:
            if h not in headers and not h.startswith("_"):  # "_source" ... belong to provider rows, not to a file
                headers.append(h)
    body = [
        [*[r.raw.get(h, "") for h in headers], r.row_number, " ؛ ".join(e.get("message", "") for e in r.errors)] for r in rows
    ]
    return csvio.stream_csv([*headers, *ERROR_HEADER_EXTRA], body)


# --------------------------------------------------------------------------- resolving duplicates


def source_for_row(job: DiscoveryJob, row: DiscoveryJobRow) -> SourceInfo:
    """The ``SourceInfo`` of a stored row: a CSV line, or a provider candidate (its provider / reference / address are kept
    inside the row, see ``Candidate.to_row``)."""
    if job.kind == DiscoveryJob.Kind.SEARCH:
        src = (row.raw or {}).get("_source") or {}
        provider = src.get("provider") or (job.params or {}).get("source_provider") or SourceProvider.OSM_OVERPASS
        return SourceInfo(
            provider=provider, source_ref=src.get("ref") or f"search:{provider}:{row.row_number}", source_url=src.get("url", ""),
            job=job, raw_data=row.raw,
        )
    return SourceInfo(provider=SourceProvider.CSV_IMPORT, source_ref=provenance.csv_ref(job.file_name, row.row_number), job=job, raw_data=row.raw)


def resolve_rows(job: DiscoveryJob, rows, action: str, actor, *, target_lead_id: int | None = None,
                 overwrite_fields: tuple[str, ...] | list[str] = ()) -> dict:
    """Merge or skip duplicate rows. At most ``RESOLVE_BATCH`` rows per call; the result says how many are left."""
    from apps.growth_engine.leads.models import Lead

    pending = list(rows.filter(status=DiscoveryJobRow.Status.DUPLICATE).order_by("row_number")[:RESOLVE_BATCH])
    merged = skipped = created = 0
    now = timezone.now()
    for row in pending:
        with transaction.atomic():
            if action == "skip":
                row.status = DiscoveryJobRow.Status.SKIPPED
                skipped += 1
            else:
                draft = LeadDraft.from_payload(row.payload)
                source = source_for_row(job, row)
                lead = None
                if target_lead_id and any(m.get("lead_id") == target_lead_id for m in row.matches):
                    lead = Lead.objects.filter(pk=target_lead_id).first()
                lead = lead or row.matched_lead
                if lead is None and row.matches:
                    lead = Lead.objects.filter(pk__in=[m["lead_id"] for m in row.matches]).first()
                if lead is None:
                    try:  # the lead it collided with is gone: this row is no longer a duplicate
                        create_from_draft(draft, source, actor)
                        row.status = DiscoveryJobRow.Status.CREATED
                        created += 1
                    except DuplicateError as dup:
                        lead = dup.matches[0].lead
                if lead is not None:
                    merge_draft_into(lead, draft, source, actor, overwrite_fields)
                    row.status = DiscoveryJobRow.Status.MERGED
                    row.matched_lead = lead
                    merged += 1
            row.resolved_by = actor
            row.resolved_at = now
            row.save()
    DiscoveryJob.objects.filter(pk=job.pk).update(
        duplicate_count=F("duplicate_count") - len(pending), merged_count=F("merged_count") + merged,
        skipped_count=F("skipped_count") + skipped, created_count=F("created_count") + created,
    )
    remaining = job.rows.filter(status=DiscoveryJobRow.Status.DUPLICATE).count()
    return {"resolved": len(pending), "merged": merged, "skipped": skipped, "created": created, "remaining": remaining}
