"""«کدام Campaign/Channel/محتوا/Plan مشتری آورد». Phase 26's DoD.

One rule decides the shape of every number here: **a channel is credited with
what it actually produced, and nothing is inferred.**

That sounds obvious and it is where marketing dashboards usually go wrong. The
tempting mistakes, and what this does instead:

* **Signups are not customers.** Every row carries both, and the ratio between
  them is the only number that separates a channel that brings businesses from
  one that brings accounts. A dashboard that ranks channels by signup makes the
  cheapest traffic look like the best traffic.
* **Revenue we have not seen is not revenue.** Only `first_payment_toman`,
  which was written when money actually arrived. No projected lifetime value, no
  "expected" anything — those are assumptions that end up quoted as facts in a
  meeting.
* **Cost is only counted where somebody entered it.** ROI on a channel with no
  recorded spend is not infinity and not zero: it is unknown, and it says so.
  This is the same rule as the profit report's treatment of a missing cost
  price, for the same reason.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .gtm import Affiliate, Attribution, DiscountCode, ReferralCode, Reward


def _rate(part: int, whole: int) -> float | None:
    """A percentage, or None when there is nothing to divide.

    None rather than 0.0: a channel with no signups has no conversion rate, and
    printing 0٪ says it converts badly rather than that nobody came.
    """
    if not whole:
        return None
    return round(part / whole * 100, 1)


def acquisition(days: int = 90) -> dict:
    """Where customers came from, over a window."""
    since = timezone.now() - timedelta(days=days)
    rows = Attribution.objects.filter(created_at__gte=since)

    by_channel = (
        rows.values("channel")
        .annotate(
            signups=Count("id"),
            paying=Count("id", filter=Q(became_paying_at__isnull=False)),
            revenue=Sum("first_payment_toman"),
        )
        .order_by("-paying", "-signups")
    )

    labels = dict(Attribution.Channel.choices)
    channels = []
    for row in by_channel:
        signups, paying = row["signups"], row["paying"]
        channels.append({
            "channel": row["channel"],
            "title": labels.get(row["channel"], row["channel"]),
            "signups": signups,
            "paying": paying,
            "conversion": _rate(paying, signups),
            "revenue_toman": row["revenue"] or 0,
            # The number that ranks channels honestly: what one paying customer
            # from here was worth, not what one visitor was worth.
            "per_customer": (
                (row["revenue"] or 0) // paying if paying else None
            ),
        })

    total_signups = sum(c["signups"] for c in channels)
    total_paying = sum(c["paying"] for c in channels)

    return {
        "days": days,
        "channels": channels,
        "signups": total_signups,
        "paying": total_paying,
        "conversion": _rate(total_paying, total_signups),
        "revenue_toman": sum(c["revenue_toman"] for c in channels),
        "untracked": Attribution.objects.filter(
            created_at__gte=since, channel=Attribution.Channel.DIRECT,
        ).count(),
    }


def campaigns(days: int = 90, limit: int = 20) -> list[dict]:
    """Named campaigns, ranked by paying customers.

    Unnamed traffic is excluded rather than bucketed as "(none)": a campaign
    report whose top row is everything that was not a campaign is a report that
    answers a different question than it was asked.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (
        Attribution.objects.filter(created_at__gte=since)
        .exclude(campaign="")
        .values("campaign", "source", "medium")
        .annotate(
            signups=Count("id"),
            paying=Count("id", filter=Q(became_paying_at__isnull=False)),
            revenue=Sum("first_payment_toman"),
        )
        .order_by("-paying", "-signups")[:limit]
    )
    return [
        {
            "campaign": row["campaign"],
            "source": row["source"],
            "medium": row["medium"],
            "signups": row["signups"],
            "paying": row["paying"],
            "conversion": _rate(row["paying"], row["signups"]),
            "revenue_toman": row["revenue"] or 0,
        }
        for row in rows
    ]


def landing_pages(days: int = 90, limit: int = 15) -> list[dict]:
    """Which page they arrived on. Answers «کدام محتوا مشتری آورد»."""
    since = timezone.now() - timedelta(days=days)
    rows = (
        Attribution.objects.filter(created_at__gte=since)
        .exclude(landing_path="")
        .values("landing_path")
        .annotate(
            signups=Count("id"),
            paying=Count("id", filter=Q(became_paying_at__isnull=False)),
        )
        .order_by("-paying", "-signups")[:limit]
    )
    return [
        {
            "path": row["landing_path"],
            "signups": row["signups"],
            "paying": row["paying"],
            "conversion": _rate(row["paying"], row["signups"]),
        }
        for row in rows
    ]


def plans(days: int = 90) -> list[dict]:
    """Which plan people actually start on. Answers «کدام Plan»."""
    from apps.billing.models import Subscription

    since = timezone.now() - timedelta(days=days)
    rows = (
        Subscription.objects.filter(created_at__gte=since)
        .values("plan__name", "plan__price_toman")
        .annotate(
            started=Count("id"),
            active=Count("id", filter=Q(status=Subscription.Status.ACTIVE)),
            cancelled=Count("id", filter=Q(status=Subscription.Status.CANCELLED)),
        )
        .order_by("-started")
    )
    return [
        {
            "plan": row["plan__name"],
            "price_toman": row["plan__price_toman"],
            "started": row["started"],
            "active": row["active"],
            "cancelled": row["cancelled"],
            # Churn among the ones that have resolved either way. Counting
            # trials still in progress as retained flatters the number.
            "churn": _rate(row["cancelled"], row["active"] + row["cancelled"]),
        }
        for row in rows
    ]


def referrals(limit: int = 20) -> dict:
    """Who is bringing us customers, and what we owe them."""
    codes = (
        ReferralCode.objects.annotate(
            signup_count=Count("attributions"),
            paying_count=Count(
                "attributions",
                filter=Q(attributions__became_paying_at__isnull=False),
            ),
        )
        .filter(signup_count__gt=0)
        .order_by("-paying_count", "-signup_count")[:limit]
    )
    partners = (
        Affiliate.objects.annotate(
            signup_count=Count("attributions"),
            paying_count=Count(
                "attributions",
                filter=Q(attributions__became_paying_at__isnull=False),
            ),
        )
        .order_by("-paying_count")[:limit]
    )

    owed = Reward.objects.filter(
        state__in=[Reward.State.PENDING, Reward.State.APPROVED],
    ).aggregate(total=Sum("amount_toman"))["total"] or 0

    return {
        "referrers": [
            {
                "code": c.code,
                "owner": c.owner.username,
                "signups": c.signup_count,
                "paying": c.paying_count,
                "conversion": _rate(c.paying_count, c.signup_count),
            }
            for c in codes
        ],
        "affiliates": [
            {
                "name": a.name,
                "code": a.code,
                "status": a.get_status_display(),
                "commission_percent": a.commission_percent,
                "signups": a.signup_count,
                "paying": a.paying_count,
            }
            for a in partners
        ],
        # What we owe but have not paid. A person pays these, deliberately;
        # nothing here moves money.
        "owed_toman": owed,
        "unpaid_count": Reward.objects.filter(
            state__in=[Reward.State.PENDING, Reward.State.APPROVED],
        ).count(),
    }


def discounts(limit: int = 20) -> list[dict]:
    """What each code cost us and what it brought."""
    rows = (
        DiscountCode.objects.annotate(
            uses=Count("redemptions"),
            given=Sum("redemptions__discount_toman"),
            taken=Sum("redemptions__price_toman"),
        )
        .filter(uses__gt=0)
        .order_by("-uses")[:limit]
    )
    return [
        {
            "code": row.code,
            "kind": row.get_kind_display(),
            "value": row.value,
            "uses": row.uses,
            "given_away_toman": row.given or 0,
            # After the discount — what actually reached us, which is the only
            # figure worth comparing against what the code cost.
            "revenue_toman": (row.taken or 0) - (row.given or 0),
            "active": row.is_active,
        }
        for row in rows
    ]


def report(days: int = 90) -> dict:
    """The whole Phase 26 dashboard in one call."""
    return {
        "acquisition": acquisition(days),
        "campaigns": campaigns(days),
        "landing_pages": landing_pages(days),
        "plans": plans(days),
        "referrals": referrals(),
        "discounts": discounts(),
        # Said out loud on every report: spend is not recorded anywhere in this
        # system, so no ROI figure here is complete. Better a stated gap than a
        # number someone quotes in a meeting.
        "caveat": (
            "هزینه‌ی تبلیغات در این سیستم ثبت نمی‌شود، پس این گزارش می‌گوید هر "
            "کانال چند مشتری و چقدر درآمد آورده — نه اینکه چقدر خرج برداشته. "
            "برای ROI واقعی باید هزینه‌ها را جای دیگری کنار این اعداد بگذارید."
        ),
    }
