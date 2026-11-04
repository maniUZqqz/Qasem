"""Lead list: search, filters, sorting - and the prefetching that keeps it free of N+1 queries."""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date

from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.sources.models import LeadSource

from ..choices import ContactKind
from ..models import ContactPoint, Lead

#: ``?ordering=`` values -> real order_by (``-id`` is added so paging is stable)
ORDERINGS = {
    "-created_at": ("-created_at", "-id"),
    "created_at": ("created_at", "id"),
    "-updated_at": ("-updated_at", "-id"),
    "updated_at": ("updated_at", "id"),
    "business_name": ("name_key", "id"),
    "-business_name": ("-name_key", "-id"),
    "status": ("status", "-created_at", "-id"),
    "-status": ("-status", "-created_at", "-id"),
    "city": ("city", "id"),
    "-city": ("-city", "-id"),
    "category": ("category", "id"),
    "-category": ("-category", "-id"),
}
DEFAULT_ORDERING = "-created_at"
HAS_FILTERS = {
    "website": Q(website__gt=""),
    "instagram": Q(instagram_url__gt=""),
}
HAS_CONTACT_KINDS = {"phone": ContactKind.PHONE, "email": ContactKind.EMAIL}


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _search_q(term: str) -> Q:
    """One search term matches the name (ignoring spaces / ZWNJ), or any text column, or a contact value."""
    text = nz.normalize_text(nz.to_ascii_digits(term))
    key = nz.search_key(term)
    condition = Q()
    if key:
        condition |= Q(name_key__contains=key)
    if text:
        condition |= (
            Q(website__icontains=text) | Q(instagram_url__icontains=text) | Q(city__icontains=text)
            | Q(category__icontains=text) | Q(description__icontains=text)
        )
        contact = Q(value__icontains=text)
        digits = re.sub(r"[\s\-()+]", "", text)
        if digits.isdigit() and len(digits) >= 3:
            contact |= Q(kind__in=[ContactKind.PHONE, ContactKind.WHATSAPP], normalized__contains=digits.lstrip("0") or digits)
        condition |= Exists(ContactPoint.objects.filter(contact, lead_id=OuterRef("pk")))
    return condition


def filter_leads(queryset: QuerySet[Lead], params: Mapping) -> QuerySet[Lead]:
    """Apply the list filters in ``params`` (a QueryDict or dict of strings)."""
    get = params.get

    archived = (get("archived") or "0").strip()
    if archived == "1":
        queryset = queryset.filter(is_archived=True)
    elif archived != "all":
        queryset = queryset.filter(is_archived=False)

    for term in (get("q") or "").split()[:8]:
        queryset = queryset.filter(_search_q(term))

    statuses = _csv(get("status"))
    if statuses:
        queryset = queryset.filter(status__in=statuses)
    origins = _csv(get("origin"))
    if origins:
        queryset = queryset.filter(origin__in=origins)
    countries = [c.upper() for c in _csv(get("country"))]
    if countries:
        queryset = queryset.filter(country__in=countries)
    if get("city"):
        queryset = queryset.filter(city__icontains=nz.normalize_text(get("city")))
    if get("category"):
        queryset = queryset.filter(category__icontains=nz.normalize_text(get("category")))
    for tag in _csv(get("tag")):
        # every named tag must be on the lead
        queryset = queryset.filter(tags__name_key=nz.search_key(tag)[:60]) if not tag.isdigit() else queryset.filter(tags__pk=int(tag))
    for what in _csv(get("has")):
        if what in HAS_FILTERS:
            queryset = queryset.filter(HAS_FILTERS[what])
        elif what in HAS_CONTACT_KINDS:
            queryset = queryset.filter(Exists(ContactPoint.objects.filter(lead_id=OuterRef("pk"), kind=HAS_CONTACT_KINDS[what])))
    if get("source_job") and str(get("source_job")).isdigit():
        queryset = queryset.filter(Exists(LeadSource.objects.filter(lead_id=OuterRef("pk"), job_id=int(get("source_job")))))
    created_from, created_to = _parse_date(get("created_from")), _parse_date(get("created_to"))
    if created_from:
        queryset = queryset.filter(created_at__date__gte=created_from)
    if created_to:
        queryset = queryset.filter(created_at__date__lte=created_to)
    return queryset.distinct() if _csv(get("tag")) else queryset


def apply_ordering(queryset: QuerySet[Lead], ordering: str | None) -> QuerySet[Lead]:
    return queryset.order_by(*ORDERINGS.get(ordering or "", ORDERINGS[DEFAULT_ORDERING]))


def with_list_prefetch(queryset: QuerySet[Lead]) -> QuerySet[Lead]:
    """Everything the list row needs in a constant number of queries."""
    return queryset.prefetch_related(
        "tags",
        Prefetch(
            "contacts",
            queryset=ContactPoint.objects.filter(kind__in=[ContactKind.PHONE, ContactKind.EMAIL]).order_by("-is_primary", "id"),
            to_attr="list_contacts",
        ),
    )
