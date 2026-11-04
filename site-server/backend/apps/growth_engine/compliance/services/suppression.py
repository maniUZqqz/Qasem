"""The do-not-contact list: anyone on it is never queued and never sent anything.

Entries are identifiers (phone / e-mail / website host / Instagram handle), matched against every
contact point of a lead, so «تماس نگیر» follows the business whichever way it is reached.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from functools import reduce
from operator import or_

from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.choices import IDENTIFIER_KINDS, ActivityKind
from apps.growth_engine.leads.models import ContactPoint, Lead
from apps.growth_engine.leads.services import history
from apps.growth_engine.leads.services.drafts import normalize_contact

from ..models import AuditKind, SuppressionEntry, SuppressionReason
from . import audit


class NothingToSuppress(Exception):
    """The lead has no phone / e-mail / website / Instagram to put on the list."""


def classify(raw: str) -> tuple[str, str, str]:
    """(kind, normalized, value) from whatever a person pasted. Raises ``NormalizationError``."""
    text = nz.normalize_text(raw)
    if not text:
        raise nz.NormalizationError("empty_value", "مقدار خالی است.")
    if text.startswith("@") or re.search(r"(instagram\.com|instagr\.am)", text, re.I):
        kind = "instagram"
    elif "@" in text and "/" not in text:
        kind = "email"
    elif re.fullmatch(r"[\d\s\-+()۰-۹٠-٩.]+", text):
        kind = "phone"
    else:
        kind = "website"
    value, key = normalize_contact(kind, text)
    return kind, key, value


def add_entries(items: Iterable[tuple[str, str, str]], reason: str, note: str, actor) -> list[SuppressionEntry]:
    """Add (kind, normalized, value) triples; existing ones are left as they are. Returns the new rows."""
    reason = reason if reason in SuppressionReason.values else SuppressionReason.OTHER
    created: list[SuppressionEntry] = []
    with transaction.atomic():
        for kind, key, value in items:
            if not key:
                continue
            entry, was_created = SuppressionEntry.objects.get_or_create(
                kind=kind, normalized=key,
                defaults={"value": value[:500], "reason": reason, "note": nz.normalize_text(note)[:300],
                          "created_by": actor if getattr(actor, "is_authenticated", False) else None},
            )
            if was_created:
                created.append(entry)
        if created:
            audit.log(AuditKind.SUPPRESS_ADDED, actor, f"{len(created)} مورد به فهرستِ «تماس نگیر» اضافه شد",
                      {"entries": [{"kind": e.kind, "value": e.value} for e in created], "reason": reason})
    return created


def _lead_identifiers(lead: Lead) -> list[ContactPoint]:
    return list(lead.contacts.filter(kind__in=list(IDENTIFIER_KINDS)).exclude(normalized=""))


def suppress_lead(lead: Lead, reason: str, note: str, actor) -> list[SuppressionEntry]:
    contacts = _lead_identifiers(lead)
    if not contacts:
        raise NothingToSuppress()
    with transaction.atomic():
        created = add_entries([(c.kind, c.normalized, c.value) for c in contacts], reason, note, actor)
        history.log_activity(
            lead, ActivityKind.SUPPRESSED, actor=actor, summary="به فهرستِ «تماس نگیر» رفت",
            data={"reason": reason, "note": note, "identifiers": [{"kind": c.kind, "value": c.value} for c in contacts]},
        )
    return created


def unsuppress_lead(lead: Lead, actor) -> int:
    contacts = _lead_identifiers(lead)
    removed = 0
    with transaction.atomic():
        if contacts:
            condition = reduce(or_, (Q(kind=c.kind, normalized=c.normalized) for c in contacts))
            removed, _ = SuppressionEntry.objects.filter(condition).delete()
        history.log_activity(lead, ActivityKind.UNSUPPRESSED, actor=actor, summary="از فهرستِ «تماس نگیر» برداشته شد", data={"removed": removed})
        audit.log(AuditKind.SUPPRESS_REMOVED, actor, f"{removed} مورد از فهرستِ «تماس نگیر» برداشته شد (لید {lead.pk})", {"lead_id": lead.pk, "removed": removed})
    return removed


def remove_entry(entry: SuppressionEntry, actor) -> None:
    with transaction.atomic():
        audit.log(AuditKind.SUPPRESS_REMOVED, actor, f"«{entry.value}» از فهرستِ «تماس نگیر» برداشته شد", {"kind": entry.kind, "value": entry.value})
        entry.delete()


def matches_for_lead(lead: Lead) -> list[SuppressionEntry]:
    """Entries that block this lead (empty list = free to contact)."""
    contacts = _lead_identifiers(lead)
    if not contacts:
        return []
    condition = reduce(or_, (Q(kind=c.kind, normalized=c.normalized) for c in contacts))
    return list(SuppressionEntry.objects.filter(condition))


def suppressed_lead_ids(lead_ids: Iterable[int]) -> set[int]:
    """Which of these leads are blocked - one query, whatever the number."""
    ids = list(lead_ids)
    if not ids:
        return set()
    blocked = SuppressionEntry.objects.filter(kind=OuterRef("kind"), normalized=OuterRef("normalized"))
    rows = (
        ContactPoint.objects.filter(lead_id__in=ids, kind__in=list(IDENTIFIER_KINDS)).exclude(normalized="")
        .filter(Exists(blocked)).values_list("lead_id", flat=True).distinct()
    )
    return set(rows)
