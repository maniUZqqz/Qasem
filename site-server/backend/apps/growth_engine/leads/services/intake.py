"""Putting a ``LeadDraft`` into the database: create a lead, or merge into an existing one.

The rules that matter:

* A draft that matches an existing lead on any identifier is a **duplicate**:
  ``create_from_draft`` raises ``DuplicateError`` and writes nothing. The caller shows the
  existing lead and lets the user merge or skip.
* A merge **never overwrites on its own**: empty fields are filled, identical values are left,
  differing values are reported as conflicts and stay as they were - unless the user named the
  field in ``overwrite_fields``.
* Every value written is stamped with its source (field-level provenance), and every create /
  merge is recorded in the lead's history and in ``LeadSource``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce
from operator import or_

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.sources import provenance
from apps.growth_engine.sources.models import LeadSource

from ..choices import ActivityKind, BusinessType, ContactKind, LeadOrigin
from ..models import BusinessProfile, ContactPoint, Lead, LeadNote
from . import history
from .dedupe import DuplicateMatch, find_duplicates_for_draft
from .drafts import FIELD_LABELS, ContactDraft, LeadDraft
from .tags import resolve_tags

SCALAR_FIELDS = ("business_name", "category", "description", "country", "city")
LIST_PROFILE_FIELDS = ("product_categories", "product_names")
SCALAR_PROFILE_FIELDS = ("language", "business_type", "address")
#: names accepted in ``overwrite_fields`` (what the user may explicitly choose to replace)
OVERWRITABLE = SCALAR_FIELDS + ("website", "instagram_url") + SCALAR_PROFILE_FIELDS

FIELD_LABELS_FA = {**FIELD_LABELS, "instagram_url": "اینستاگرام"}


class DuplicateError(Exception):
    """The draft's identifiers already belong to existing lead(s)."""

    def __init__(self, matches: list[DuplicateMatch]):
        super().__init__("duplicate lead")
        self.matches = matches


@dataclass
class SourceInfo:
    provider: str
    source_ref: str = provenance.MANUAL
    source_url: str = ""
    job: object | None = None
    raw_data: dict = field(default_factory=dict)


@dataclass
class FieldDecision:
    field: str
    existing: object
    incoming: object
    state: str  # "fill" (existing empty) | "same" | "conflict" (different, left unchanged unless overwritten)

    @property
    def label(self) -> str:
        return FIELD_LABELS_FA.get(self.field, self.field)


@dataclass
class MergePlan:
    decisions: list[FieldDecision] = field(default_factory=list)
    new_contacts: list[ContactDraft] = field(default_factory=list)
    known_contacts: list[ContactDraft] = field(default_factory=list)  # already on this lead
    foreign_contacts: list[tuple[ContactDraft, int]] = field(default_factory=list)  # owned by another lead
    new_tags: list[str] = field(default_factory=list)


@dataclass
class MergeResult:
    lead: Lead
    filled: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    added_contacts: list[dict] = field(default_factory=list)
    skipped_contacts: list[dict] = field(default_factory=list)
    tags_added: list[str] = field(default_factory=list)
    note_added: bool = False


def _actor(actor):
    return actor if actor is not None and getattr(actor, "is_authenticated", False) else None


def _origin_for(provider: str) -> str:
    return provider if provider in LeadOrigin.values else LeadOrigin.MANUAL


# --------------------------------------------------------------------------- create


def create_from_draft(draft: LeadDraft, source: SourceInfo, actor=None) -> Lead:
    """Create a lead from a valid draft. Raises ``DuplicateError`` if it already exists."""
    with transaction.atomic():
        matches = find_duplicates_for_draft(draft)
        if matches:
            raise DuplicateError(matches)
        try:
            with transaction.atomic():
                return _insert(draft, source, _actor(actor))
        except IntegrityError:
            # lost a race with a concurrent insert: the DB constraint caught what the check missed
            matches = find_duplicates_for_draft(draft)
            if matches:
                raise DuplicateError(matches) from None
            raise


def _insert(draft: LeadDraft, source: SourceInfo, actor) -> Lead:
    ref = source.source_ref
    actor_id = actor.pk if actor else None
    website = draft.website
    instagram = draft.instagram
    lead = Lead(
        business_name=draft.business_name,
        website=website.value if website else "",
        instagram_url=instagram.value if instagram else "",
        category=draft.category,
        description=draft.description,
        country=draft.country,
        city=draft.city,
        origin=_origin_for(source.provider),
        created_by=actor,
    )
    stamped = []
    prov: dict = {}
    for name, value in (
        ("business_name", lead.business_name), ("website", lead.website), ("instagram_url", lead.instagram_url),
        ("category", lead.category), ("description", lead.description), ("country", lead.country), ("city", lead.city),
    ):
        if value:
            provenance.stamp(prov, name, ref, actor_id)
            stamped.append(name)
    lead.provenance = prov
    lead.save()

    primaries: set[str] = set()
    rows = []
    for contact in draft.contacts:
        make_primary = contact.kind not in primaries
        primaries.add(contact.kind)
        rows.append(_contact_row(lead, contact, ref, make_primary))
    ContactPoint.objects.bulk_create(rows)

    if draft.profile:
        _create_profile(lead, draft.profile, ref, actor_id)

    tags = resolve_tags(draft.tags)
    if tags:
        lead.tags.add(*tags)

    LeadSource.objects.create(
        lead=lead, provider=source.provider, source_ref=ref, source_url=source.source_url or (website.value if website and source.provider == "website_url" else ""),
        job=source.job, created_by=actor, raw_data=source.raw_data or {},
    )
    history.log_activity(
        lead, ActivityKind.CREATED, actor=actor, source_ref=ref,
        summary=f"لید از «{LeadOrigin(_origin_for(source.provider)).label}» ساخته شد",
        data={"fields": stamped, "contacts": len(rows), "tags": [t.name for t in tags]},
    )
    if draft.note:
        LeadNote.objects.create(lead=lead, author=actor, body=draft.note)
        history.log_activity(lead, ActivityKind.NOTE_ADDED, actor=actor, summary=history.short(draft.note, 120))
    return lead


def _contact_row(lead: Lead, contact: ContactDraft, ref: str, primary: bool) -> ContactPoint:
    return ContactPoint(
        lead=lead, kind=contact.kind, value=contact.value, normalized=contact.normalized, label=contact.label,
        is_primary=primary, source_ref=contact.source_ref or ref, source_url=contact.source_url,
        evidence=contact.evidence, confidence=contact.confidence,
    )


def _create_profile(lead: Lead, profile: dict, ref: str, actor_id) -> BusinessProfile:
    prov: dict = {}
    for name in profile:
        provenance.stamp(prov, name, ref, actor_id)
    return BusinessProfile.objects.create(lead=lead, provenance=prov, **profile)


# --------------------------------------------------------------------------- merge planning


def _same(name: str, existing, incoming) -> bool:
    if isinstance(existing, str) and isinstance(incoming, str):
        return nz.search_key(existing) == nz.search_key(incoming)
    return existing == incoming


def _website_same(existing: str, incoming: ContactDraft) -> bool:
    try:
        return nz.clean_url(existing).identity == incoming.normalized
    except nz.NormalizationError:
        return False


def _instagram_same(existing: str, incoming: ContactDraft) -> bool:
    try:
        return nz.parse_instagram(existing).handle == incoming.normalized
    except nz.NormalizationError:
        return False


def plan_merge(lead: Lead, draft: LeadDraft) -> MergePlan:
    """What merging ``draft`` into ``lead`` would do. Read-only; also used for the duplicate preview."""
    plan = MergePlan()
    for name in SCALAR_FIELDS:
        incoming = getattr(draft, name)
        if not incoming:
            continue
        existing = getattr(lead, name)
        state = "fill" if not existing else ("same" if _same(name, existing, incoming) else "conflict")
        plan.decisions.append(FieldDecision(name, existing, incoming, state))
    for kind, lead_attr, same in (
        (ContactKind.WEBSITE, "website", _website_same), (ContactKind.INSTAGRAM, "instagram_url", _instagram_same),
    ):
        incoming = next(iter(draft.contacts_of(kind)), None)
        if incoming is None:
            continue
        existing = getattr(lead, lead_attr)
        state = "fill" if not existing else ("same" if same(existing, incoming) else "conflict")
        plan.decisions.append(FieldDecision(lead_attr, existing, incoming.value, state))
    try:
        profile = lead.profile
    except BusinessProfile.DoesNotExist:
        profile = None
    for name in SCALAR_PROFILE_FIELDS:
        incoming = draft.profile.get(name)
        if not incoming:
            continue
        existing = getattr(profile, name, "") if profile else ""
        if name == "business_type" and existing == BusinessType.UNKNOWN:
            existing = ""
        state = "fill" if not existing else ("same" if _same(name, existing, incoming) else "conflict")
        plan.decisions.append(FieldDecision(name, existing, incoming, state))

    owners = {}
    pairs = [(c.kind, c.normalized) for c in draft.contacts if c.normalized]
    if pairs:
        for cp in ContactPoint.objects.filter(reduce(or_, (Q(kind=k, normalized=n) for k, n in pairs))):
            owners[(cp.kind, cp.normalized)] = cp.lead_id
    for contact in draft.contacts:
        owner = owners.get((contact.kind, contact.normalized)) if contact.normalized else None
        if owner is None:
            plan.new_contacts.append(contact)
        elif owner == lead.pk:
            plan.known_contacts.append(contact)
        else:
            plan.foreign_contacts.append((contact, owner))
    have = set(lead.tags.values_list("name_key", flat=True)) if lead.pk else set()
    plan.new_tags = [t for t in draft.tags if nz.search_key(t)[:60] not in have]
    return plan


# --------------------------------------------------------------------------- merge


def merge_draft_into(
    lead: Lead, draft: LeadDraft, source: SourceInfo, actor=None, overwrite_fields: tuple[str, ...] | list[str] = ()
) -> MergeResult:
    """Merge a draft into an existing lead. Fill-only unless fields are named in ``overwrite_fields``."""
    actor = _actor(actor)
    actor_id = actor.pk if actor else None
    overwrite = {f for f in overwrite_fields if f in OVERWRITABLE}
    ref = source.source_ref
    with transaction.atomic():
        lead = Lead.objects.get(pk=lead.pk)
        plan = plan_merge(lead, draft)
        result = MergeResult(lead=lead)
        prov = dict(lead.provenance or {})
        lead_changed: list[str] = []
        profile_changes: dict = {}

        for decision in plan.decisions:
            apply = decision.state == "fill" or (decision.state == "conflict" and decision.field in overwrite)
            if decision.state == "same":
                continue
            if not apply:
                result.conflicts.append(
                    {"field": decision.field, "label": decision.label, "existing": decision.existing, "incoming": decision.incoming}
                )
                continue
            (result.filled if decision.state == "fill" else result.overwritten).append(decision.field)
            if decision.field in SCALAR_PROFILE_FIELDS:
                profile_changes[decision.field] = decision.incoming
            else:
                setattr(lead, decision.field, decision.incoming)
                lead_changed.append(decision.field)
                provenance.stamp(prov, decision.field, ref, actor_id)
        if lead_changed:
            lead.provenance = prov
            lead.save(update_fields=[*lead_changed, "provenance", "updated_at"])

        profile = _merge_profile(lead, draft, profile_changes, result, ref, actor_id)

        have_primary = set(lead.contacts.filter(is_primary=True).values_list("kind", flat=True))
        for contact in plan.new_contacts:
            try:
                with transaction.atomic():
                    ContactPoint.objects.create(
                        lead=lead, kind=contact.kind, value=contact.value, normalized=contact.normalized, label=contact.label,
                        is_primary=contact.kind not in have_primary, source_ref=contact.source_ref or ref,
                        source_url=contact.source_url, evidence=contact.evidence, confidence=contact.confidence,
                    )
                have_primary.add(contact.kind)
                result.added_contacts.append({"kind": contact.kind, "value": contact.value})
            except IntegrityError:
                result.skipped_contacts.append({"kind": contact.kind, "value": contact.value, "reason": "owned_by_other_lead"})
        for contact, owner_id in plan.foreign_contacts:
            result.skipped_contacts.append(
                {"kind": contact.kind, "value": contact.value, "reason": "owned_by_other_lead", "lead_id": owner_id}
            )

        if plan.new_tags:
            tags = resolve_tags(plan.new_tags)
            lead.tags.add(*tags)
            result.tags_added = [t.name for t in tags]
        if draft.note:
            LeadNote.objects.create(lead=lead, author=actor, body=draft.note)
            result.note_added = True

        LeadSource.objects.create(
            lead=lead, provider=source.provider, source_ref=ref, source_url=source.source_url, job=source.job,
            created_by=actor, raw_data=source.raw_data or {},
        )
        history.log_activity(
            lead, ActivityKind.MERGED, actor=actor, source_ref=ref,
            summary="اطلاعاتِ تازه با این لید ادغام شد",
            data={
                "filled": result.filled, "overwritten": result.overwritten,
                "conflicts": [c["field"] for c in result.conflicts],
                "contacts_added": result.added_contacts, "contacts_skipped": result.skipped_contacts,
                "tags_added": result.tags_added,
            },
        )
        lead.refresh_from_db()
        result.lead = lead
        return result


def _merge_profile(lead: Lead, draft: LeadDraft, changes: dict, result: MergeResult, ref: str, actor_id):
    list_additions = {
        name: [v for v in draft.profile.get(name, []) if v]
        for name in LIST_PROFILE_FIELDS
        if draft.profile.get(name)
    }
    if not changes and not list_additions:
        return None
    profile, _ = BusinessProfile.objects.get_or_create(lead=lead)
    prov = dict(profile.provenance or {})
    for name, value in changes.items():
        setattr(profile, name, value)
        provenance.stamp(prov, name, ref, actor_id)
    for name, values in list_additions.items():
        current = list(getattr(profile, name) or [])
        known = {nz.search_key(v) for v in current}
        fresh = [v for v in values if nz.search_key(v) not in known]
        if fresh:
            setattr(profile, name, current + fresh)
            provenance.stamp(prov, name, ref, actor_id)
            result.filled.append(name)
    profile.provenance = prov
    profile.save()
    return profile
