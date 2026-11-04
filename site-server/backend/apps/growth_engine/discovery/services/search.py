"""Automatic discovery: a search job asks ONE provider (map / search API) for businesses and feeds each answer through the same
pipeline as a CSV row.

How a job runs
--------------
1. **Fetch** - the provider is asked once (a map query, or a few result pages); the answer is stored as a small JSON file next
   to the job (``stored_name``) so a resumed job does not ask the outside world again.
2. **Process** - every candidate becomes a ``LeadDraft`` and goes through duplicate detection exactly like a CSV row: a new
   business becomes a lead (with its provenance / licence line), a known one becomes a «تکراری» row for a person to merge or skip.
3. **After** - the ``discovery_job_finished`` signal; if the operator asked for it, contact extraction starts on the new leads.

A provider failure (service busy, key rejected, daily cap) finishes the job as *failed* with a Persian explanation, and
«ادامه» runs it again later; nothing is half-written because step 2 only starts after step 1 succeeded.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.growth_engine.core import conf
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.integrations.safe_http import SafeFetcher
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.leads.services.intake import SourceInfo

from .. import providers
from ..models import DiscoveryJob
from ..providers import categories
from ..providers.base import Candidate, ProviderError, SearchProvider, SearchQuery
from . import csv_import, providers_config, rows as rowops

logger = logging.getLogger(__name__)

SEARCH_DIR = "growth_engine/uploads"  # the same folder the CSV uploads use: the stale-file cleanup covers both
CANCEL_POLL_EVERY = 10


def make_fetcher() -> SafeFetcher:
    """One fetcher per job run. Tests replace this function."""
    return SafeFetcher(respect_robots=False)  # API endpoints publish a usage policy; robots.txt governs page crawling


# --------------------------------------------------------------------------- validating a request


def _err(errors: list[dict], field: str, code: str, message: str) -> None:
    errors.append({"field": field, "code": code, "message": message})


def validate_request(data: Mapping) -> tuple[SearchProvider, SearchQuery, dict]:
    """Cleaned ``(provider, query, extra params)`` or ``ValidationFailed``. Nothing is fetched and nothing is written."""
    errors: list[dict] = []
    provider = providers.get(str(data.get("provider") or ""))
    if provider is None:
        raise ValidationFailed([{"field": "provider", "code": "unknown_provider", "message": "منبعِ کشف را انتخاب کنید."}])
    ready, reason = providers_config.readiness(provider)
    if not ready:
        _err(errors, "provider", "provider_not_ready", f"«{provider.label}» آماده نیست: {reason}")

    category = nz.normalize_text(str(data.get("category") or ""))
    if provider.kind == "map":
        if categories.tags_of(category) is None:
            _err(errors, "category", "bad_category", "یکی از دسته‌های فهرست را انتخاب کنید.")
    elif not 2 <= len(category) <= 120:
        _err(errors, "category", "bad_query", "عبارتِ جست‌وجو را بنویسید (۲ تا ۱۲۰ نویسه؛ مثلاً «فروشگاه لباس زنانه»).")

    city = nz.normalize_text(str(data.get("city") or ""))
    if provider.kind == "map" and not city:
        _err(errors, "city", "city_required", "نامِ شهر را بنویسید.")
    if len(city) > 100:
        _err(errors, "city", "too_long", "نامِ شهر از ۱۰۰ نویسه بلندتر است.")

    try:
        country = nz.normalize_country(str(data.get("country") or "")) or str(conf.get("DEFAULT_COUNTRY"))
    except nz.NormalizationError as exc:
        _err(errors, "country", exc.code, exc.message)
        country = ""

    try:
        max_results = int(data.get("max_results") or 100)
    except (TypeError, ValueError):
        _err(errors, "max_results", "invalid_number", "«حداکثر نتیجه» باید عدد باشد.")
        max_results = 0
    if max_results and not 1 <= max_results <= provider.max_results_limit:
        _err(errors, "max_results", "out_of_range", f"«حداکثر نتیجه» برای این منبع باید بین ۱ و {provider.max_results_limit} باشد.")

    tags = [nz.normalize_text(str(t))[:50] for t in (data.get("tags") or []) if str(t).strip()][:20]
    if errors:
        raise ValidationFailed(errors)
    query = SearchQuery(category=category, city=city, country=country, max_results=max_results, require_contact=bool(data.get("require_contact", True)))
    return provider, query, {"tags": tags, "extract_after": bool(data.get("extract_after", False))}


def describe(provider: SearchProvider, query: SearchQuery) -> str:
    what = categories.label_of(query.category) or query.category
    return f"{provider.label} · {what}" + (f" · {query.city}" if query.city else "")


def check(data: Mapping, *, fetcher_factory=None) -> dict:
    """The dry run: validate, and (map provider) resolve the city - the only call to the outside, cached afterwards."""
    provider, query, _ = validate_request(data)
    out = {"ok": True, "summary": describe(provider, query), "attribution": provider.attribution, "place": None, "notes": []}
    if provider.kind == "map":
        fetcher = (fetcher_factory or make_fetcher)()
        try:
            ctx = providers_config.context_for(provider, fetcher, lambda: False)
            place = ctx.geocode(query.city, query.country)
        except ProviderError as exc:
            raise ValidationFailed([{"field": "city", "code": exc.code, "message": exc.message}]) from exc
        finally:
            fetcher.close()
        out["place"] = {"name": place["name"], "cached": bool(place.get("cached")), "osm_url": f"https://www.openstreetmap.org/{place['osm_type']}/{place['osm_id']}"}
        out["notes"].append("فقط فروشگاه‌هایی که روی نقشه ثبت شده‌اند پیدا می‌شوند؛ بسیاری از آن‌ها تلفن یا سایت ندارند و رد می‌شوند.")
    else:
        out["notes"].append("هر نتیجه یک سایت است، نه یک کسب‌وکارِ تأییدشده؛ بعد از ساختنِ لید بهتر است «استخراجِ اطلاعاتِ تماس» اجرا شود.")
    return out


# --------------------------------------------------------------------------- creating the job


def create_job(user, data: Mapping) -> DiscoveryJob:
    """Validate and create the job row (queued). The caller dispatches the Celery task after commit."""
    provider, query, extra = validate_request(data)
    return DiscoveryJob.objects.create(
        kind=DiscoveryJob.Kind.SEARCH, file_name=describe(provider, query)[:200], created_by=user if getattr(user, "is_authenticated", False) else None,
        params={
            "provider": provider.key, "source_provider": provider.source_provider, "category": query.category,
            "category_label": categories.label_of(query.category) or query.category, "city": query.city, "country": query.country,
            "max_results": query.max_results, "require_contact": query.require_contact, "tags": extra["tags"],
            "extract_after": extra["extract_after"], "attribution": provider.attribution, "attribution_url": provider.attribution_url,
        },
    )


# --------------------------------------------------------------------------- the job


def _path(job_id: int) -> str:
    return f"{SEARCH_DIR}/search-job-{job_id}.json"


def _store(job: DiscoveryJob, rows: list[dict]) -> str:
    path = _path(job.pk)
    if default_storage.exists(path):
        default_storage.delete(path)
    default_storage.save(path, ContentFile(json.dumps(rows, ensure_ascii=False).encode("utf-8")))
    DiscoveryJob.objects.filter(pk=job.pk).update(stored_name=path, total_items=len(rows))
    return path


def _load(job: DiscoveryJob) -> list[dict] | None:
    if not job.stored_name:
        return None
    try:
        with default_storage.open(job.stored_name, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
        return data if isinstance(data, list) else None
    except (FileNotFoundError, OSError, ValueError):
        return None


def _fail(job: DiscoveryJob, message: str) -> str:
    job.refresh_from_db()
    job.mark_finished(DiscoveryJob.Status.FAILED, message)
    return job.status


def run_search(job_id: int, *, fetcher_factory=None) -> str:
    """Execute (or resume) a search job. Returns the final status. Never raises for a provider's or a candidate's problem."""
    job = DiscoveryJob.objects.filter(pk=job_id, kind=DiscoveryJob.Kind.SEARCH).first()
    if job is None:
        return "missing"
    if job.is_finished:
        return job.status
    if job.cancel_requested:
        job.mark_finished(DiscoveryJob.Status.CANCELLED, "پیش از شروع لغو شد.")
        csv_import._after_finish(job)
        return job.status
    job.mark_running()
    params = job.params or {}
    provider = providers.get(params.get("provider", ""))
    if provider is None:
        return _fail(job, "منبعِ این کار دیگر وجود ندارد.")

    rows = _load(job)
    if rows is None:
        if job.cursor:
            return _fail(job, "فایلِ موقتِ این کار پاک شده؛ یک کارِ کشفِ تازه بسازید (لیدهای ساخته‌شده می‌مانند).")
        fetcher = (fetcher_factory or make_fetcher)()
        try:
            ctx = providers_config.context_for(provider, fetcher, lambda: rowops.should_cancel(job))
            query = SearchQuery(
                category=params.get("category", ""), city=params.get("city", ""), country=params.get("country", ""),
                max_results=int(params.get("max_results", 100)), require_contact=bool(params.get("require_contact", True)),
            )
            candidates = provider.fetch(query, ctx)
        except ProviderError as exc:
            if exc.code == "cancelled":
                job.refresh_from_db()
                job.mark_finished(DiscoveryJob.Status.CANCELLED, "به درخواستِ کاربر متوقف شد.")
                csv_import._after_finish(job)
                return job.status
            logger.info("growth discovery job %s: provider %s said %s", job.pk, provider.key, exc.code)
            return _fail(job, exc.message + (" با «ادامه» دوباره امتحان می‌شود." if exc.retryable else ""))
        except Exception as exc:  # noqa: BLE001 - infrastructure, not the provider's answer
            logger.exception("growth discovery job %s failed while fetching", job.pk)
            return _fail(job, f"کار با خطای داخلی متوقف شد ({type(exc).__name__}). می‌توانید «ادامه» را بزنید.")
        finally:
            fetcher.close()
        rows = [c.to_row(provider.source_provider) for c in candidates]
        _store(job, rows)
        if not rows:
            DiscoveryJob.objects.filter(pk=job.pk).update(params={**params, "empty_note": "هیچ موردی با این مشخصات پیدا نشد (یا همه راهِ تماس نداشتند)."})

    try:
        _process(job, rows, params)
    except _Cancelled:
        job.refresh_from_db()
        job.mark_finished(DiscoveryJob.Status.CANCELLED, "به درخواستِ کاربر متوقف شد؛ موردهای ثبت‌شده می‌مانند.")
        csv_import._after_finish(job)
        return job.status
    except Exception as exc:  # noqa: BLE001 - infrastructure failure (DB locked ...), not a bad candidate
        logger.exception("growth discovery job %s failed", job.pk)
        return _fail(job, f"کار با خطای داخلی متوقف شد ({type(exc).__name__}). می‌توانید «ادامه» را بزنید.")
    job.refresh_from_db()
    job.mark_finished(DiscoveryJob.Status.COMPLETED)
    csv_import._after_finish(job)
    return job.status


class _Cancelled(Exception):
    pass


def _process(job: DiscoveryJob, rows: list[dict], params: dict) -> None:
    seen = 0
    for number, row in enumerate(rows, 1):
        if number <= job.cursor:
            continue
        if seen % CANCEL_POLL_EVERY == 0 and rowops.should_cancel(job):
            raise _Cancelled
        seen += 1
        candidate = Candidate.from_row(row)
        src = row.get("_source") or {}
        draft, errors = build_draft(
            candidate.to_raw(), source_ref=src.get("ref") or f"search:{number}", default_country=params.get("country", ""), default_city=params.get("city", ""),
        )
        if params.get("tags"):
            draft.tags = list(dict.fromkeys([*draft.tags, *params["tags"]]))
        source = SourceInfo(
            provider=src.get("provider") or params.get("source_provider") or "", source_ref=src.get("ref") or f"search:{number}",
            source_url=src.get("url", ""), job=job,
            raw_data={**{k: v for k, v in row.items() if not k.startswith("_")}, "attribution": params.get("attribution", ""), "extra": row.get("_extra") or {}},
        )
        rowops.process_draft(job, number, draft, list(errors), row, source)
