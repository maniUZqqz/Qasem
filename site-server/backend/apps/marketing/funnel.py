"""The funnel, computed from real events.

The marketing spec asks a specific question:

    Visitor → Landing Page → Feature/Solution → Pricing → Signup → Customer

Counting events is not enough to answer it — 500 pricing views could be five
people refreshing. So every step counts **distinct sessions**, not events.

What this deliberately does *not* do is force each step to be a subset of the
one before. Picking a plan is genuinely optional — the register button on most
pages carries no plan — so a strict chain would drop real signups and report
zero. Optional steps are marked, and drop-off is measured against the last
required step. If an event is missing the report shows the gap rather than
smoothing it over.

Nothing here is estimated or modelled. If a number cannot be derived from
stored events it is not reported.
"""
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .events import Event
from .models import Lead


def _sessions(name: str, since) -> set[str]:
    return set(
        Event.objects.filter(name=name, created_at__gte=since)
        .values_list("session", flat=True)
        .distinct()
    )


def funnel(days: int = 30) -> dict:
    """Session-based funnel for the last `days` days."""
    since = timezone.now() - timedelta(days=days)

    visitors = _sessions(Event.Name.PAGE_VIEW, since)

    # "Explored" means they looked at a feature, solution or use-case page —
    # the pages built to catch intent. Reading the home page alone is not
    # exploring, so this is derived from path rather than from a event name.
    explored = set(
        Event.objects.filter(
            name=Event.Name.PAGE_VIEW,
            created_at__gte=since,
        )
        .filter(path__regex=r"/(features|solutions|use-cases)/")
        .values_list("session", flat=True)
        .distinct()
    )

    priced = _sessions(Event.Name.PRICING_VIEW, since)
    planned = _sessions(Event.Name.PLAN_SELECTED, since)
    started = _sessions(Event.Name.SIGNUP_STARTED, since)
    completed = _sessions(Event.Name.SIGNUP_COMPLETED, since)

    # (label, sessions, optional). Every step is measured among visitors, so a
    # session that arrives straight on /pricing from an ad still counts there —
    # it simply never counts as "explored".
    steps = [
        ("بازدیدکننده", visitors, False),
        ("دیدن قابلیت یا راه‌حل", explored & visitors, False),
        ("دیدن قیمت", priced & visitors, False),
        ("انتخاب پلن", planned & visitors, True),
        ("شروع ثبت‌نام", started & visitors, False),
        ("تکمیل ثبت‌نام", completed & visitors, False),
    ]

    rows = []
    first = len(visitors)
    previous_required = first
    for label, sessions, optional in steps:
        count = len(sessions)
        rows.append(
            {
                "label": label,
                "count": count,
                "optional": optional,
                "of_total": round(count / first * 100, 1) if first else 0.0,
                # Drop-off against the last *required* step. Comparing against
                # an optional one would invent a leak that is not there.
                "of_previous": (
                    None
                    if optional
                    else round(count / previous_required * 100, 1)
                    if previous_required
                    else 0.0
                ),
            }
        )
        if not optional:
            previous_required = count or previous_required

    return {
        "days": days,
        "since": since,
        "steps": rows,
        "leads": Lead.objects.filter(created_at__gte=since).count(),
    }


def by_channel(days: int = 30, limit: int = 10) -> list[dict]:
    """Which campaign source produced sessions, and how far they got.

    This is the question Phase 26 exists to answer, so the shape is chosen to
    survive: source → sessions → signups, not just a hit count.
    """
    since = timezone.now() - timedelta(days=days)

    # A visit belongs to ONE channel: the first campaign source seen in it.
    # Grouping every page view by its own utm would put the same session under
    # both "instagram" and "direct" — inflating both, and making the totals add
    # up to more than the number of real visits.
    first_source: dict[str, str] = {}
    for session, source in (
        Event.objects.filter(name=Event.Name.PAGE_VIEW, created_at__gte=since)
        .order_by("created_at")
        .values_list("session", "utm__source")
    ):
        if session not in first_source or (not first_source[session] and source):
            first_source[session] = source or ""

    sessions_by_source: dict[str, set[str]] = {}
    for session, source in first_source.items():
        sessions_by_source.setdefault(source or "مستقیم", set()).add(session)

    signed_up = _sessions(Event.Name.SIGNUP_COMPLETED, since)

    rows = [
        {
            "source": source,
            "sessions": len(sessions),
            "signups": len(sessions & signed_up),
        }
        for source, sessions in sessions_by_source.items()
    ]
    rows.sort(key=lambda r: r["sessions"], reverse=True)
    return rows[:limit]


def top_pages(days: int = 30, limit: int = 15) -> list[dict]:
    since = timezone.now() - timedelta(days=days)
    return list(
        Event.objects.filter(name=Event.Name.PAGE_VIEW, created_at__gte=since)
        .values("path")
        .annotate(views=Count("id"), sessions=Count("session", distinct=True))
        .order_by("-sessions")[:limit]
    )
