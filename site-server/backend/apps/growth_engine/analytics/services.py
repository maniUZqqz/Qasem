"""Numbers for the Growth Dashboard. Every figure is a count from the database; nothing is estimated."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.growth_engine.discovery.models import DiscoveryJob
from apps.growth_engine.leads.choices import ActivityKind, ContactKind, LeadOrigin, LeadStatus
from apps.growth_engine.leads.models import ContactPoint, Lead, LeadActivity

from . import registry

DAILY_WINDOW_DAYS = 14

#: what the dashboard will show once the modules behind it exist (an honest roadmap, not numbers)
COMING_SOON = [
    {"key": "discovery_auto", "title": "کشفِ خودکار از دایرکتوری‌ها و موتورهای جست‌وجو", "milestone": "M3"},
    {"key": "research", "title": "تحلیلِ کسب‌وکار و امتیازدهی به لیدها (کیفیتِ لید)", "milestone": "M5"},
    {"key": "ai_writer", "title": "پیام‌نویسِ هوش مصنوعی و پیشنهادِ فروش", "milestone": "M6–M7"},
    {"key": "pipeline", "title": "قیف فروش و تحلیلِ نرخ تبدیل", "milestone": "M9"},
]


def build_dashboard() -> dict:
    now = timezone.now()
    today = timezone.localdate()
    active = Lead.objects.filter(is_archived=False)

    totals = active.aggregate(
        leads=Count("id"),
        new_7d=Count("id", filter=Q(created_at__gte=now - timedelta(days=7))),
        with_website=Count("id", filter=Q(website__gt="")),
        with_instagram=Count("id", filter=Q(instagram_url__gt="")),
    )
    totals["archived"] = Lead.objects.filter(is_archived=True).count()
    for key, kind in (("with_phone", ContactKind.PHONE), ("with_email", ContactKind.EMAIL), ("with_contact_form", ContactKind.CONTACT_FORM)):
        totals[key] = active.filter(Exists(ContactPoint.objects.filter(lead_id=OuterRef("pk"), kind=kind))).count()

    status_counts = dict(active.values_list("status").annotate(n=Count("id")))
    origin_counts = dict(active.values_list("origin").annotate(n=Count("id")))
    first_day = today - timedelta(days=DAILY_WINDOW_DAYS - 1)
    per_day = dict(
        active.filter(created_at__date__gte=first_day).annotate(day=TruncDate("created_at")).values_list("day").annotate(n=Count("id"))
    )
    daily = [
        {"date": (first_day + timedelta(days=i)).isoformat(), "value": per_day.get(first_day + timedelta(days=i), 0)}
        for i in range(DAILY_WINDOW_DAYS)
    ]
    cities = (
        active.exclude(city="").values("city").annotate(n=Count("id")).order_by("-n", "city")[:5]
    )
    jobs = DiscoveryJob.objects.select_related("created_by")[:5]
    activity = LeadActivity.objects.select_related("lead", "actor").exclude(
        kind__in=[ActivityKind.NOTE_EDITED, ActivityKind.CONTACT_UPDATED]
    )[:10]

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "totals": totals,
        "by_status": [{"status": v, "label": label, "count": status_counts.get(v, 0)} for v, label in LeadStatus.choices],
        "by_origin": [{"origin": v, "label": label, "count": origin_counts.get(v, 0)} for v, label in LeadOrigin.choices],
        "top_cities": [{"city": c["city"], "count": c["n"]} for c in cities],
        "daily": daily,
        "pending_duplicates": DiscoveryJob.objects.aggregate(n=Sum("duplicate_count"))["n"] or 0,
        "recent_jobs": [
            {
                "id": j.pk, "file_name": j.file_name, "status": j.status, "status_label": j.get_status_display(),
                "progress": j.progress, "created_count": j.created_count, "duplicate_count": j.duplicate_count,
                "error_count": j.error_count, "total_items": j.total_items, "queued_at": j.queued_at,
                "created_by_name": j.created_by.username if j.created_by_id else "",
            }
            for j in jobs
        ],
        "recent_activity": [
            {
                "id": a.pk, "lead_id": a.lead_id, "lead_name": a.lead.display_name, "kind": a.kind,
                "kind_label": a.get_kind_display(), "summary": a.summary, "actor_name": a.actor.username if a.actor_id else "",
                "created_at": a.created_at,
            }
            for a in activity
        ],
        "extra": registry.collect(),
        "coming_soon": COMING_SOON,
    }
