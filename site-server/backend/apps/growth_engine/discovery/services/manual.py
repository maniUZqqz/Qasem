"""Manual discovery: one business typed in, pasted as a website / Instagram link, or named.

Four entry modes share one pipeline; they differ only in what must be present and in the
``provider`` recorded as the lead's discovery source:

    website_url     a website address (required)
    instagram_url   an Instagram profile address or @handle (required) - stored as given, never fetched
    business_name   just a name (required)
    manual          the full form (at least one of name / website / Instagram / phone / e-mail)
"""
from __future__ import annotations

from collections.abc import Mapping

from apps.growth_engine.leads.models import Lead
from apps.growth_engine.leads.services.dedupe import find_duplicates_for_draft, find_similar_by_name
from apps.growth_engine.leads.services.drafts import FieldErrors, LeadDraft, build_draft
from apps.growth_engine.leads.services.intake import (
    OVERWRITABLE,
    DuplicateError,
    MergeResult,
    SourceInfo,
    create_from_draft,
    merge_draft_into,
)
from apps.growth_engine.sources import provenance
from apps.growth_engine.sources.models import SourceProvider

MODES = {
    "website_url": (SourceProvider.WEBSITE_URL, "website", "آدرسِ وب‌سایت را بنویسید."),
    "instagram_url": (SourceProvider.INSTAGRAM_URL, "instagram", "آدرس یا نام کاربریِ پیج اینستاگرام را بنویسید."),
    "business_name": (SourceProvider.BUSINESS_NAME, "business_name", "نامِ کسب‌وکار را بنویسید."),
    "manual": (SourceProvider.MANUAL, None, ""),
}


class UnknownMode(ValueError):
    pass


def prepare(raw: Mapping, mode: str) -> tuple[LeadDraft, FieldErrors, SourceInfo]:
    """Build and validate the draft for ``mode``. Errors are not raised; the caller decides."""
    if mode not in MODES:
        raise UnknownMode(mode)
    provider, required, message = MODES[mode]
    draft, errors = build_draft(raw, source_ref=provenance.MANUAL)
    source = SourceInfo(provider=provider, source_ref=provenance.MANUAL, raw_data={k: v for k, v in raw.items() if v not in (None, "", [])})
    if required:
        present = bool(draft.business_name) if required == "business_name" else bool(
            draft.website if required == "website" else draft.instagram
        )
        has_error_on_it = any(e["field"] == required for e in errors)
        if not present and not has_error_on_it:
            errors.add(required, "required", message)
        # a lone-field mode does not need the generic "empty row" error
        errors[:] = [e for e in errors if not (e["field"] == "__row__" and e["code"] == "empty_row")]
    if mode == "website_url" and draft.website:
        source.source_url = draft.website.value
    if mode == "instagram_url" and draft.instagram:
        source.source_url = draft.instagram.value
    return draft, errors, source


def check(raw: Mapping, mode: str) -> dict:
    """Dry run: validation errors, existing duplicates and same-name hints. Writes nothing."""
    draft, errors, _ = prepare(raw, mode)
    if errors:
        return {"valid": False, "errors": list(errors), "matches": [], "similar": [], "draft": None}
    matches = find_duplicates_for_draft(draft)
    similar = find_similar_by_name(draft.business_name, exclude_ids=tuple(m.lead.pk for m in matches)) if draft.business_name else []
    return {"valid": True, "errors": [], "matches": matches, "similar": similar, "draft": draft}


def submit(raw: Mapping, mode: str, actor, *, resolution: Mapping | None = None) -> dict:
    """Create the lead, or apply the user's decision on a duplicate.

    Returns ``{"result": "created" | "merged" | "skipped", ...}``. Raises ``DuplicateError`` when the
    business already exists and no ``resolution`` was given (nothing is written in that case)."""
    draft, errors, source = prepare(raw, mode)
    if errors:
        return {"result": "invalid", "errors": list(errors)}
    action = (resolution or {}).get("action")
    if action == "skip":
        return {"result": "skipped"}
    if action == "merge":
        target = _merge_target(draft, (resolution or {}).get("target_lead"))
        if target is not None:
            overwrite = [f for f in (resolution or {}).get("overwrite_fields", []) if f in OVERWRITABLE]
            merged: MergeResult = merge_draft_into(target, draft, source, actor, overwrite)
            return {"result": "merged", "merge": merged}
        # nothing to merge into any more (it was deleted a moment ago): fall through and create
    lead = create_from_draft(draft, source, actor)
    return {"result": "created", "lead": lead}


def _merge_target(draft: LeadDraft, target_id) -> Lead | None:
    matches = find_duplicates_for_draft(draft)
    if not matches:
        return None
    if target_id:
        for match in matches:
            if match.lead.pk == int(target_id):
                return match.lead
    return matches[0].lead


__all__ = ["MODES", "UnknownMode", "check", "prepare", "submit", "DuplicateError"]
