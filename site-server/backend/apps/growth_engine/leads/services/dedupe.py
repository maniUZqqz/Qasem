"""Duplicate detection on normalised identifiers.

Two leads are the same business when they share a website (host), an Instagram
handle, a phone number or an e-mail address, all after normalisation. The business
name alone is never a duplicate signal (it is shown as "similar", not blocked).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce
from operator import or_

from django.db.models import Q

from apps.growth_engine.core import normalization as nz

from ..models import ContactPoint, Lead
from .drafts import LeadDraft


@dataclass
class DuplicateMatch:
    lead: Lead
    matched_on: list[dict] = field(default_factory=list)  # [{"kind", "value", "normalized"}]


def find_duplicates(identifiers: list[tuple[str, str]], *, exclude_lead_id: int | None = None) -> list[DuplicateMatch]:
    """Existing leads that own any of the (kind, normalized) pairs. Best match first.

    Archived leads are included on purpose: they still own their identifiers.
    """
    pairs = [(k, n) for k, n in identifiers if n]
    if not pairs:
        return []
    condition = reduce(or_, (Q(kind=k, normalized=n) for k, n in pairs))
    queryset = ContactPoint.objects.filter(condition).select_related("lead")
    if exclude_lead_id is not None:
        queryset = queryset.exclude(lead_id=exclude_lead_id)
    by_lead: dict[int, DuplicateMatch] = {}
    for contact in queryset.order_by("lead_id", "id"):
        match = by_lead.setdefault(contact.lead_id, DuplicateMatch(lead=contact.lead))
        match.matched_on.append({"kind": contact.kind, "value": contact.value, "normalized": contact.normalized})
    return sorted(by_lead.values(), key=lambda m: (-len(m.matched_on), m.lead.pk))


def find_duplicates_for_draft(draft: LeadDraft, *, exclude_lead_id: int | None = None) -> list[DuplicateMatch]:
    return find_duplicates(draft.identifiers(), exclude_lead_id=exclude_lead_id)


def find_similar_by_name(name: str, *, exclude_ids: tuple[int, ...] = (), limit: int = 5) -> list[Lead]:
    """Leads with the same name (ignoring spaces / ZWNJ / case). A hint only - never blocks."""
    key = nz.search_key(name)
    if len(key) < 3:
        return []
    queryset = Lead.objects.filter(name_key=key)
    if exclude_ids:
        queryset = queryset.exclude(pk__in=exclude_ids)
    return list(queryset.order_by("-created_at")[:limit])
