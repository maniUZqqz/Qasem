"""Append-only audit trail. Outreach, settings and suppression write here."""
from __future__ import annotations

from ..models import AuditEntry


def log(kind: str, actor, summary: str, data: dict | None = None) -> AuditEntry:
    actor_id = getattr(actor, "pk", None) if actor is not None and getattr(actor, "is_authenticated", True) else None
    return AuditEntry.objects.create(kind=kind, actor_id=actor_id, summary=summary[:300], data=data or {})
