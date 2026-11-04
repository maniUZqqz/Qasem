"""Writing to the lead's history. Every change to a lead goes through here."""
from __future__ import annotations

from collections.abc import Iterable

from ..models import Lead, LeadActivity


def _actor_id(actor) -> int | None:
    return getattr(actor, "pk", None) if actor is not None and getattr(actor, "is_authenticated", True) else None


def log_activity(
    lead: Lead, kind: str, *, actor=None, summary: str = "", data: dict | None = None, source_ref: str = ""
) -> LeadActivity:
    return LeadActivity.objects.create(
        lead=lead, kind=kind, actor_id=_actor_id(actor), summary=summary[:300], data=data or {}, source_ref=source_ref[:255]
    )


def log_activities(
    leads: Iterable[Lead], kind: str, *, actor=None, summary: str = "", data: dict | None = None
) -> int:
    """One activity per lead in a single INSERT (bulk operations)."""
    actor_id = _actor_id(actor)
    rows = [LeadActivity(lead=lead, kind=kind, actor_id=actor_id, summary=summary[:300], data=data or {}) for lead in leads]
    LeadActivity.objects.bulk_create(rows)
    return len(rows)


def short(value, limit: int = 160):
    """A value trimmed for storing in history (full text lives on the lead itself)."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value
