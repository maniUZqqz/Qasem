"""CSV export of leads. Headers are Persian and are recognised by the importer, so an
exported file imports back (the formula guard apostrophes are removed on the way in)."""
from __future__ import annotations

from collections.abc import Iterable, Iterator

from apps.growth_engine.core import conf, csvio
from apps.growth_engine.core import normalization as nz

from ..choices import ContactKind, LeadOrigin, LeadStatus
from ..models import ContactPoint, Lead

HEADER = [
    "شناسه", "نام کسب‌وکار", "وب‌سایت", "اینستاگرام", "تلفن", "ایمیل", "واتساپ", "تلگرام", "دسته", "توضیحات",
    "کشور", "شهر", "وضعیت", "منبع کشف", "برچسب‌ها", "تاریخ ثبت (میلادی)",
]
SEPARATOR = " | "


def _phones(values: list[str]) -> str:
    return SEPARATOR.join(nz.format_phone_display(v) for v in values)


def export_rows(leads: Iterable[Lead]) -> Iterator[list[object]]:
    for lead in leads:
        by_kind: dict[str, list[str]] = {}
        for contact in lead.export_contacts:
            by_kind.setdefault(contact.kind, []).append(contact.value)
        yield [
            lead.pk,
            lead.business_name,
            lead.website,
            lead.instagram_url,
            _phones(by_kind.get(ContactKind.PHONE, [])),
            SEPARATOR.join(by_kind.get(ContactKind.EMAIL, [])),
            _phones(by_kind.get(ContactKind.WHATSAPP, [])),
            SEPARATOR.join(by_kind.get(ContactKind.TELEGRAM, [])),
            lead.category,
            lead.description,
            lead.country,
            lead.city,
            LeadStatus(lead.status).label,
            LeadOrigin(lead.origin).label,
            SEPARATOR.join(t.name for t in lead.tags.all()),
            lead.created_at.date().isoformat(),
        ]


def stream_export(queryset) -> Iterator[bytes]:
    """Stream ``queryset`` as UTF-8-BOM CSV (at most ``EXPORT_MAX_ROWS`` rows)."""
    from django.db.models import Prefetch

    limited = queryset.prefetch_related(
        "tags",
        Prefetch(
            "contacts",
            queryset=ContactPoint.objects.filter(
                kind__in=[ContactKind.PHONE, ContactKind.EMAIL, ContactKind.WHATSAPP, ContactKind.TELEGRAM]
            ).order_by("-is_primary", "id"),
            to_attr="export_contacts",
        ),
    )[: conf.get("EXPORT_MAX_ROWS")]
    return csvio.stream_csv(HEADER, export_rows(limited.iterator(chunk_size=500)))
