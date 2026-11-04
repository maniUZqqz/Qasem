"""Saving what a crawl found, without ever overwriting or stealing.

Rules (each one is a finding ``reason`` the panel shows):

* contacts -> ``ContactPoint`` rows carrying ``source_ref = extract:<run>``, the page URL, the evidence and the
  confidence. ``added`` | ``already_known`` (this lead already has it) | ``owned_by_other_lead`` (an identifier of
  another lead is never taken) | ``invalid`` (does not normalise).
* lead fields (business name, description, city) and profile fields (address, language) are **fill-only**:
  ``fill_empty`` | ``already_known`` (same value) | ``kept_existing`` (a different value is already there and stays).
  Filled fields get their provenance stamped ``extract:<run>``.
* the Instagram link also fills ``Lead.instagram_url`` when that is empty.
* one ``LeadSource(contact_extraction)`` per run that added anything, and one ``LeadActivity(extraction)`` per run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import IDENTIFIER_KINDS, ActivityKind
from apps.growth_engine.leads.models import BusinessProfile, ContactPoint, Lead
from apps.growth_engine.leads.services import history
from apps.growth_engine.leads.services.drafts import normalize_contact
from apps.growth_engine.sources import provenance
from apps.growth_engine.sources.models import LeadSource, SourceProvider

from .parser import CONTACT_FIELDS, Finding

LEAD_FIELD_LIMITS = {"business_name": 200, "description": 500, "city": 100}
PROFILE_FIELD_LIMITS = {"address": 400, "language": 8}


@dataclass
class ApplyResult:
    records: list[dict] = field(default_factory=list)
    contacts_added: int = 0
    fields_filled: list[str] = field(default_factory=list)


def _record(f: Finding, applied: bool, reason: str) -> dict:
    return {
        "field": f.field, "value": f.value, "source_url": f.source_url, "evidence": f.evidence,
        "confidence": f.confidence, "applied": applied, "reason": reason,
    }


def _same(a: str, b: str) -> bool:
    return nz.search_key(a) == nz.search_key(b)


def apply_findings(lead: Lead, run, findings: list[Finding], *, actor=None, home_url: str = "", pages: list[str] | None = None) -> ApplyResult:
    """Save ``findings`` for ``lead`` (one transaction). Returns what happened to each one."""
    ref = provenance.extract_ref(run.pk)
    actor_id = getattr(actor, "pk", None)
    result = ApplyResult()
    with transaction.atomic():
        lead = Lead.objects.get(pk=lead.pk)
        prov = dict(lead.provenance or {})
        lead_changed: list[str] = []
        have = {(c.kind, c.normalized) for c in lead.contacts.all()}
        primaries = set(lead.contacts.filter(is_primary=True).values_list("kind", flat=True))
        profile: BusinessProfile | None = None
        profile_prov: dict = {}
        profile_changed = False

        for f in findings:
            if f.field in CONTACT_FIELDS:
                record = _apply_contact(lead, f, ref, have, primaries, prov, lead_changed)
                if record["applied"]:
                    result.contacts_added += 1
            elif f.field in LEAD_FIELD_LIMITS:
                record = _fill_lead_field(lead, f, ref, actor_id, prov, lead_changed)
                if record["applied"]:
                    result.fields_filled.append(f.field)
            elif f.field in PROFILE_FIELD_LIMITS:
                if profile is None:
                    profile, _ = BusinessProfile.objects.get_or_create(lead=lead)
                    profile_prov = dict(profile.provenance or {})
                record = _fill_profile_field(profile, f, ref, actor_id, profile_prov)
                if record["applied"]:
                    profile_changed = True
                    result.fields_filled.append(f.field)
            else:
                record = _record(f, False, "invalid")
            result.records.append(record)

        if lead_changed:
            lead.provenance = prov
            lead.save(update_fields=[*dict.fromkeys(lead_changed), "provenance", "updated_at"])
        elif result.contacts_added:
            lead.save(update_fields=["updated_at"])
        if profile is not None and profile_changed:
            profile.provenance = profile_prov
            profile.save()
        if result.contacts_added or result.fields_filled:
            LeadSource.objects.create(
                lead=lead, provider=SourceProvider.CONTACT_EXTRACTION, source_ref=ref, source_url=home_url[:500],
                created_by_id=actor_id, raw_data={"pages": list(pages or []), "contacts_added": result.contacts_added, "fields_filled": result.fields_filled},
            )
    return result


def _apply_contact(lead: Lead, f: Finding, ref: str, have: set, primaries: set, prov: dict, lead_changed: list) -> dict:
    kind = f.field
    try:
        if kind == "contact_form":
            value = key = nz.clean_url(f.value).url
            if len(key) > 300:
                raise nz.NormalizationError("too_long", "آدرس بیش از حد بلند است.")
        else:
            value, key = normalize_contact(kind, f.value)
    except nz.NormalizationError:
        return _record(f, False, "invalid")
    if (kind, key) in have:
        return _record(f, False, "already_known")
    if kind in IDENTIFIER_KINDS and ContactPoint.objects.filter(kind=kind, normalized=key).exclude(lead=lead).exists():
        return _record(f, False, "owned_by_other_lead")
    try:
        with transaction.atomic():
            ContactPoint.objects.create(
                lead=lead, kind=kind, value=value[:500], normalized=key, label=f.label[:80], is_primary=kind not in primaries,
                source_ref=ref, source_url=f.source_url[:500], evidence=f.evidence[:300], confidence=f.confidence,
            )
    except IntegrityError:  # lost a race for an identifier: it belongs to someone else now
        return _record(f, False, "owned_by_other_lead")
    have.add((kind, key))
    primaries.add(kind)
    if kind == "instagram" and not lead.instagram_url:
        lead.instagram_url = value
        lead_changed.append("instagram_url")
        provenance.stamp(prov, "instagram_url", ref, None)
    return _record(f, True, "added")


def _fill_lead_field(lead: Lead, f: Finding, ref: str, actor_id, prov: dict, lead_changed: list) -> dict:
    name = f.field
    value = nz.normalize_text(f.value, multiline=(name == "description"))[: LEAD_FIELD_LIMITS[name]]
    if not value:
        return _record(f, False, "invalid")
    existing = getattr(lead, name)
    if not existing:
        setattr(lead, name, value)
        lead_changed.append(name)
        provenance.stamp(prov, name, ref, actor_id)
        return _record(f, True, "fill_empty")
    return _record(f, False, "already_known" if _same(existing, value) else "kept_existing")


def _fill_profile_field(profile: BusinessProfile, f: Finding, ref: str, actor_id, prov: dict) -> dict:
    name = f.field
    value = nz.normalize_text(f.value)[: PROFILE_FIELD_LIMITS[name]]
    if not value:
        return _record(f, False, "invalid")
    existing = getattr(profile, name)
    if not existing:
        setattr(profile, name, value)
        provenance.stamp(prov, name, ref, actor_id)
        return _record(f, True, "fill_empty")
    return _record(f, False, "already_known" if _same(existing, value) else "kept_existing")


def log_run_activity(lead: Lead, run, summary: str, data: dict, actor=None) -> None:
    history.log_activity(lead, ActivityKind.EXTRACTION, actor=actor, summary=summary, data=data, source_ref=provenance.extract_ref(run.pk))
