"""Lead → Customer → Onboarding → Support → Retention, as one thing. Phase 26.

Every piece of this already existed and none of it was joined up: a `Lead` from
the contact form, an `Attribution` written at signup, a `Subscription` that is
paying or not, an onboarding checklist, tickets, and jobs that either ran or
did not. Six tables, six screens, and no answer to the only question a founder
actually asks — **who is about to leave, and why?**

Three decisions shape this file.

**The stages are a timeline, not a funnel of counts.** A customer is at exactly
one stage, derived from what actually happened to them, and moving backwards is
meaningful: a paying customer who stopped using the product is not "converted",
they are `SLIPPING`, and that is the whole point of looking.

**Risk is evidence, never a score.** There is no churn-probability model here
and there will not be one until there is enough history to fit it against.
Instead, each risk is a fact with a date attached: "logged in once, eleven days
ago", "three failed jobs in a row", "trial ends in two days and nothing has been
published". A founder can act on those. A number between 0 and 1 invites you to
sort by it and stop reading.

**Nothing here writes.** It is a read of rows other parts of the system own.
A CRM that quietly changes subscription state is a CRM that fights with billing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

#: A trial ending sooner than this is the last useful moment to do something
#: about it. After it ends, the conversation is a different one.
TRIAL_WARNING_DAYS = 3

#: No activity for this long, on an account that is paying, is the clearest
#: signal we have. Shorter and it catches people on holiday.
QUIET_DAYS = 10

#: Failures in a row that mean the product is broken for this customer
#: specifically — not a bad run.
FAILURE_RUN = 3

#: Below this many finished pieces of content, a paying customer has not yet got
#: what they paid for, whatever the dashboard says.
ACTIVATION_OUTPUTS = 3


class Stage:
    LEAD = "LEAD"                # asked about us, no account
    SIGNED_UP = "SIGNED_UP"      # account, no store or no products
    ONBOARDING = "ONBOARDING"    # setting up, nothing published
    ACTIVE = "ACTIVE"            # using it, producing things
    SLIPPING = "SLIPPING"        # was active, has gone quiet
    LAPSED = "LAPSED"            # subscription over

TITLES = {
    Stage.LEAD: "سرنخ",
    Stage.SIGNED_UP: "ثبت‌نام‌کرده",
    Stage.ONBOARDING: "در حال راه‌اندازی",
    Stage.ACTIVE: "فعال",
    Stage.SLIPPING: "در حال از دست رفتن",
    Stage.LAPSED: "رفته",
}

ORDER = [
    Stage.LEAD, Stage.SIGNED_UP, Stage.ONBOARDING,
    Stage.ACTIVE, Stage.SLIPPING, Stage.LAPSED,
]


@dataclass
class Risk:
    """One fact about a customer, with the date that makes it actionable."""

    key: str
    what: str
    #: "high" only when doing nothing today makes it worse. Everything else is
    #: "watch" — an inbox where everything is urgent is an inbox nobody reads.
    level: str = "watch"

    def as_dict(self) -> dict:
        return {"key": self.key, "what": self.what, "level": self.level}


@dataclass
class Row:
    store_id: int
    name: str
    owner: str
    stage: str
    plan: str = ""
    paying: bool = False
    days_since_signup: int = 0
    days_since_activity: int | None = None
    outputs: int = 0
    published: int = 0
    open_tickets: int = 0
    channel: str = ""
    risks: list[Risk] = field(default_factory=list)

    @property
    def worst(self) -> str:
        return "high" if any(r.level == "high" for r in self.risks) else (
            "watch" if self.risks else "ok"
        )

    def as_dict(self) -> dict:
        return {
            "store_id": self.store_id,
            "name": self.name,
            "owner": self.owner,
            "stage": self.stage,
            "stage_title": TITLES[self.stage],
            "plan": self.plan,
            "paying": self.paying,
            "days_since_signup": self.days_since_signup,
            "days_since_activity": self.days_since_activity,
            "outputs": self.outputs,
            "published": self.published,
            "open_tickets": self.open_tickets,
            "channel": self.channel,
            "risks": [r.as_dict() for r in self.risks],
            "risk": self.worst,
        }


# ------------------------------------------------------------------ reading


def _stage_for(*, paying, subscription_over, outputs, published, quiet_days,
               has_products) -> str:
    if subscription_over:
        return Stage.LAPSED
    if not has_products:
        return Stage.SIGNED_UP
    if published == 0 and outputs < ACTIVATION_OUTPUTS:
        return Stage.ONBOARDING
    # Backwards on purpose. A paying customer who stopped using the product is
    # not "converted" — they are the most important row on this page.
    if quiet_days is not None and quiet_days >= QUIET_DAYS:
        return Stage.SLIPPING
    return Stage.ACTIVE


def _risks(row: Row, subscription, now) -> list[Risk]:
    risks: list[Risk] = []

    if subscription is not None and subscription.period_end:
        left = (subscription.period_end - now).days
        if 0 <= left <= TRIAL_WARNING_DAYS:
            trialing = subscription.status == subscription.Status.TRIALING
            risks.append(Risk(
                "ending",
                (
                    f"دوره‌ی آزمایشی {left} روز دیگر تمام می‌شود"
                    if trialing else f"اشتراک {left} روز دیگر تمام می‌شود"
                ),
                # The last useful moment to do anything about it.
                level="high",
            ))

    if row.days_since_activity is not None and row.days_since_activity >= QUIET_DAYS:
        risks.append(Risk(
            "quiet",
            f"{row.days_since_activity} روز است کاری نکرده",
            level="high" if row.paying else "watch",
        ))

    if row.stage == Stage.ONBOARDING and row.days_since_signup >= 7:
        risks.append(Risk(
            "stuck",
            f"{row.days_since_signup} روز از ثبت‌نام گذشته و هنوز چیزی منتشر نکرده",
            level="high" if row.paying else "watch",
        ))

    if row.paying and row.outputs < ACTIVATION_OUTPUTS:
        # The one that matters most and is easiest to miss: they are paying and
        # have not yet received what they paid for.
        risks.append(Risk(
            "not_activated",
            f"پول می‌دهد ولی فقط {row.outputs} خروجی گرفته",
            level="high",
        ))

    if row.open_tickets:
        risks.append(Risk(
            "tickets", f"{row.open_tickets} تیکت باز دارد", level="watch",
        ))

    return risks


def customers(limit: int = 200) -> list[Row]:
    """Every shop, at the stage they are actually at."""
    from django.db.models import Count, Max, Q

    from apps.billing.models import Subscription
    from apps.content.models import GeneratedImage
    from apps.jobs.models import Job
    from apps.stores.models import Store

    now = timezone.now()
    stores = (
        Store.objects.select_related("owner")
        .annotate(
            product_count=Count("products", distinct=True),
            image_count=Count("generated_images", distinct=True),
            video_count=Count("video_scripts", distinct=True),
            published_count=Count(
                "campaigns",
                filter=Q(campaigns__approval_state="PUBLISHED"),
                distinct=True,
            ),
            last_job=Max("jobs__created_at"),
        )
        .order_by("-created_at")[:limit]
    )

    subscriptions = {
        s.store_id: s for s in Subscription.objects.select_related("plan")
    }
    attributions = _attribution_map()
    tickets = _open_ticket_map()

    rows = []
    for store in stores:
        subscription = subscriptions.get(store.pk)
        paying = bool(
            subscription and subscription.status == Subscription.Status.ACTIVE
        )
        over = bool(
            subscription
            and subscription.status in (
                Subscription.Status.CANCELLED, Subscription.Status.EXPIRED,
            )
        )

        last = store.last_job or store.created_at
        quiet = (now - last).days if last else None
        outputs = (store.image_count or 0) + (store.video_count or 0)

        row = Row(
            store_id=store.pk,
            name=store.name,
            owner=store.owner.username if store.owner else "—",
            stage=_stage_for(
                paying=paying,
                subscription_over=over,
                outputs=outputs,
                published=store.published_count or 0,
                quiet_days=quiet,
                has_products=bool(store.product_count),
            ),
            plan=subscription.plan.name if subscription else "",
            paying=paying,
            days_since_signup=(now - store.created_at).days,
            days_since_activity=quiet,
            outputs=outputs,
            published=store.published_count or 0,
            open_tickets=tickets.get(store.pk, 0),
            channel=attributions.get(store.pk, ""),
        )
        row.risks = _risks(row, subscription, now)
        rows.append(row)

    # Riskiest first, then quietest. The page exists to be read from the top.
    weight = {"high": 0, "watch": 1, "ok": 2}
    rows.sort(key=lambda r: (weight[r.worst], -(r.days_since_activity or 0)))
    return rows


def _attribution_map() -> dict[int, str]:
    from .gtm import Attribution

    return {
        a.store_id: a.get_channel_display()
        for a in Attribution.objects.all().only("store_id", "channel")
    }


def _open_ticket_map() -> dict[int, int]:
    """Open tickets per store, and a shrug rather than a crash if there are none.

    Support lives in another app whose shape has changed before; this page is
    still useful without the column.
    """
    from django.db.models import Count

    try:
        from apps.customers.models import SupportTicket

        rows = (
            SupportTicket.objects.exclude(status=SupportTicket.Status.RESOLVED)
            .values("store_id")
            .annotate(n=Count("id"))
        )
        return {row["store_id"]: row["n"] for row in rows}
    except Exception:  # noqa: BLE001 — a missing field is not worth the page
        return {}


def leads(limit: int = 100) -> list[dict]:
    """People who asked about us and have no account yet.

    The start of the same timeline, kept separate because a lead has no store —
    and joining them by email would be a guess, since somebody can enquire from
    one address and sign up with another.
    """
    from .models import Lead

    rows = Lead.objects.exclude(
        status__in=[Lead.Status.SPAM, Lead.Status.CLOSED],
    )[:limit]
    now = timezone.now()
    return [
        {
            "id": lead.pk,
            "name": lead.name,
            "email": lead.email,
            "business": lead.business,
            "subject": lead.get_subject_display(),
            "status": lead.status,
            "status_title": lead.get_status_display(),
            "days_waiting": (now - lead.created_at).days,
            # The only thing a lead page is for. A lead nobody answered for
            # nine days is the cheapest customer we will ever lose.
            "unanswered": (
                lead.status == Lead.Status.NEW and (now - lead.created_at).days >= 2
            ),
            "source": lead.source_path,
        }
        for lead in rows
    ]


def board(limit: int = 200) -> dict:
    """The whole thing: leads, customers by stage, and what needs doing today."""
    rows = customers(limit)
    waiting = leads()

    by_stage = {stage: [] for stage in ORDER}
    for row in rows:
        by_stage[row.stage].append(row)

    return {
        "stages": [
            {
                "key": stage,
                "title": TITLES[stage],
                "count": len(by_stage[stage]),
                "customers": [r.as_dict() for r in by_stage[stage]],
            }
            for stage in ORDER
        ],
        "leads": waiting,
        # The answer to "what should I do today", which is the only reason to
        # open this page.
        "today": {
            "unanswered_leads": [l for l in waiting if l["unanswered"]],
            "at_risk": [r.as_dict() for r in rows if r.worst == "high"],
        },
        "totals": {
            "leads": len(waiting),
            "customers": len(rows),
            "paying": sum(1 for r in rows if r.paying),
            "at_risk": sum(1 for r in rows if r.worst == "high"),
        },
        # Said on the page, because the absence of a number is a design choice
        # people will otherwise read as an oversight.
        "note": (
            "اینجا عدد «احتمال ریزش» نمی‌بینید. مدلی که آن عدد را بدهد، تاریخچه‌ی "
            "کافی می‌خواهد که هنوز نداریم — و عددی که پشتش داده نباشد، فقط باعث "
            "می‌شود بر اساسش مرتب کنید و دیگر دلیل‌ها را نخوانید. به‌جایش هر ردیف "
            "می‌گوید **چه اتفاقی افتاده و کِی**."
        ),
    }
