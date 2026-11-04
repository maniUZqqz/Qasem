"""Tags: created on the fly, matched ignoring spaces / ZWNJ / case."""
from __future__ import annotations

from collections.abc import Iterable

from django.db import IntegrityError, transaction

from apps.growth_engine.core import normalization as nz

from ..models import LeadTag


def resolve_tags(names: Iterable[str]) -> list[LeadTag]:
    """The LeadTag rows for ``names``, creating the missing ones. Order of ``names`` is kept."""
    wanted: dict[str, str] = {}
    for name in names:
        clean = nz.normalize_text(name)[:50]
        key = nz.search_key(clean)[:60]
        if clean and key and key not in wanted:
            wanted[key] = clean
    if not wanted:
        return []
    existing = {t.name_key: t for t in LeadTag.objects.filter(name_key__in=list(wanted))}
    for key, clean in wanted.items():
        if key not in existing:
            try:
                with transaction.atomic():
                    existing[key] = LeadTag.objects.create(name=clean)
            except IntegrityError:  # created by someone else a moment ago
                existing[key] = LeadTag.objects.get(name_key=key)
    return [existing[key] for key in wanted]
