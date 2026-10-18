"""Reading what actually happened to the posts we published. Phase 25.

`ایده‌ها.md` §18: the loop is only closed when the shop's *next* content is
shaped by how the last one did. Everything before this was the product talking;
this is the product listening.

**What is measured, and what deliberately is not.** Views, likes, comments,
saves and shares — the numbers a platform will give us. Not "sales caused by
this post": attribution across an Instagram post, a DM and a bank transfer is
a guess, and dressing a guess as a figure is how a shop ends up doubling down
on the wrong thing. Where a post and an order really are linked — the customer
mentioned it in the conversation — that link is recorded as fact instead.

**Why the numbers land in a separate model.** A `PublishJob` records that we
posted something; performance records what happened to it afterwards, arrives
hours or days later, and is re-fetched as it changes. Folding them together
would mean rewriting the publishing record every hour, and losing the ability
to say "this is what it looked like on day one".

**Honest limit.** Only channels whose API returns metrics can fill this in.
NovinHub does for Instagram; a post pushed through an n8n webhook the shop
built themselves cannot be read back unless that flow reports it. Rows for
those channels stay empty and say so, rather than showing zeros that look like
failure.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel

logger = logging.getLogger(__name__)

#: Stop re-fetching after this. A post's numbers stop moving, and asking
#: forever spends the platform's rate limit on nothing.
TRACK_FOR = timedelta(days=14)

#: How often one post is re-checked. Hourly is more than enough for something
#: that changes over days.
REFRESH_EVERY = timedelta(hours=6)


class PostPerformance(TimeStampedModel):
    """How one published post actually did."""

    publish_job = models.OneToOneField(
        "campaigns.PublishJob", on_delete=models.CASCADE, related_name="performance",
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="post_performance",
    )
    platform = models.CharField(max_length=32)

    views = models.PositiveIntegerField(null=True, blank=True)
    likes = models.PositiveIntegerField(null=True, blank=True)
    comments = models.PositiveIntegerField(null=True, blank=True)
    saves = models.PositiveIntegerField(null=True, blank=True)
    shares = models.PositiveIntegerField(null=True, blank=True)

    #: Confirmed orders of this post's product placed while this was the newest
    #: post of that product (`_count_linked_orders`). A correlation in time —
    #: nobody has measured that the post caused them. Named `linked_orders` for
    #: history; everything that shows it must say what it really is.
    linked_orders = models.PositiveIntegerField(default=0)

    fetched_at = models.DateTimeField(null=True, blank=True)
    #: Why there are no numbers, when there are none. An empty row with no
    #: explanation reads as a failure; "this channel does not report back"
    #: reads as a fact about the channel.
    unavailable_reason = models.CharField(max_length=200, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "-created_at"])]
        verbose_name = "عملکرد پست"
        verbose_name_plural = "عملکرد پست‌ها"

    def __str__(self):
        return f"{self.platform} #{self.publish_job_id}"

    @property
    def engagement(self) -> int | None:
        """Everything a person did beyond scrolling past.

        None when nothing was reported — zero would claim the post was seen and
        ignored, which is a different and much worse piece of news.
        """
        parts = [self.likes, self.comments, self.saves, self.shares]
        known = [p for p in parts if p is not None]
        return sum(known) if known else None

    @property
    def engagement_rate(self) -> float | None:
        total = self.engagement
        if total is None or not self.views:
            return None
        return round(total / self.views * 100, 2)


# ------------------------------------------------------------- collection


def _fetch_instagram(publish_job) -> dict:
    """Ask NovinHub how the post did. Returns metrics or a reason."""
    from services.publishing import novinhub

    post_id = (publish_job.response or {}).get("post_id") or (
        publish_job.response or {}
    ).get("id")
    if not post_id:
        return {"unavailable_reason": "شناسه‌ی پست از پلتفرم برنگشت."}

    try:
        stats = novinhub.post_insights(publish_job.store, post_id)
    except Exception as exc:  # noqa: BLE001 — one post must not stop the sweep
        return {"unavailable_reason": f"دریافت آمار ممکن نشد: {exc}"[:200]}

    return {
        "views": stats.get("views") or stats.get("impressions"),
        "likes": stats.get("likes"),
        "comments": stats.get("comments"),
        "saves": stats.get("saves"),
        "shares": stats.get("shares"),
        "raw": stats,
    }


#: platform → fetcher. Anything absent simply has no numbers, and says so.
FETCHERS = {
    "instagram": _fetch_instagram,
    "INSTAGRAM": _fetch_instagram,
}


def _count_linked_orders(publish_job) -> int:
    """Confirmed orders of this product placed while this post was the newest.

    Read that literally — it is a **correlation in time**, not proof that the
    post sold anything. The docstring used to claim the customer had mentioned
    the post in the conversation; nothing has ever measured that, and a figure
    that says one thing and counts another is worse than no figure.

    The window closes when the next post of the same product goes out, which
    is what stops two posts of one product from each counting the same orders
    — with a plain 14-day window, three posts of the same product turned ten
    sales into thirty, and the shop's "best performing post" was whichever one
    happened to sit in the busiest fortnight.
    """
    from apps.customers.models import Order

    from .models import PublishJob

    product = publish_job.campaign.product_id
    start = publish_job.published_at
    if not product or not start:
        return 0

    end = start + TRACK_FOR
    successor = (
        PublishJob.objects.filter(
            store=publish_job.store,
            campaign__product_id=product,
            status=PublishJob.Status.SENT,
            published_at__gt=start,
        )
        .order_by("published_at")
        .values_list("published_at", flat=True)
        .first()
    )
    if successor and successor < end:
        end = successor

    return Order.objects.filter(
        store=publish_job.store,
        status=Order.Status.CONFIRMED,
        # When the customer ordered, not when the money cleared: the question
        # is what they did after seeing the post.
        created_at__gte=start,
        created_at__lt=end,
        items__product_id=product,
    ).distinct().count()


def due_for_refresh(now=None):
    """Published posts young enough to still be changing."""
    from .models import PublishJob

    now = now or timezone.now()
    return (
        PublishJob.objects
        .filter(
            status=PublishJob.Status.SENT,
            published_at__isnull=False,
            published_at__gte=now - TRACK_FOR,
        )
        .select_related("campaign", "store", "campaign__product")
        .order_by("published_at")[:50]
    )


def collect_one(publish_job, now=None) -> PostPerformance:
    """Fetch and store the numbers for one post."""
    now = now or timezone.now()
    row, _ = PostPerformance.objects.get_or_create(
        publish_job=publish_job,
        defaults={"store": publish_job.store, "platform": publish_job.platform},
    )

    if row.fetched_at and (now - row.fetched_at) < REFRESH_EVERY:
        return row  # asking again this soon spends rate limit on nothing

    fetcher = FETCHERS.get(publish_job.platform)
    if fetcher is None:
        row.unavailable_reason = (
            f"«{publish_job.platform}» آماری برنمی‌گرداند — این کانال از طریق "
            "اتوماسیون خودتان منتشر می‌شود و عددی به ما نمی‌دهد."
        )
    else:
        result = fetcher(publish_job)
        row.unavailable_reason = result.get("unavailable_reason", "")
        for field in ("views", "likes", "comments", "saves", "shares"):
            if result.get(field) is not None:
                setattr(row, field, int(result[field]))
        if result.get("raw"):
            row.raw = result["raw"]

    row.linked_orders = _count_linked_orders(publish_job)
    row.fetched_at = now
    row.save()
    return row


def collect_all(now=None) -> dict:
    """The hourly sweep. One failure never stops the others."""
    checked = 0
    with_numbers = 0
    for publish_job in list(due_for_refresh(now)):
        try:
            row = collect_one(publish_job, now)
        except Exception as exc:  # noqa: BLE001
            logger.info("Performance fetch failed for %s: %s", publish_job.pk, exc)
            continue
        checked += 1
        if row.engagement is not None:
            with_numbers += 1
    return {"checked": checked, "with_numbers": with_numbers}


# ----------------------------------------------------------- the feedback


def what_worked(store, days: int = 90) -> dict:
    """What this shop's own audience responded to. The closed half of the loop.

    Returns patterns, not instructions. A shop whose three best posts were all
    video should be told that and left to decide; told "make more videos" it
    hears an ad for a feature.

    Says plainly when there is not enough to conclude from. Three posts is not
    a pattern, and presenting it as one is how a shop chases noise.
    """
    since = timezone.now() - timedelta(days=days)
    rows = list(
        PostPerformance.objects
        .filter(store=store, created_at__gte=since)
        .select_related("publish_job", "publish_job__campaign")
    )
    measured = [r for r in rows if r.engagement is not None]

    if len(measured) < 5:
        return {
            "enough_data": False,
            "posts": len(rows),
            "measured": len(measured),
            "message": (
                f"فقط {len(measured)} پست آمار دارد. برای نتیجه‌گیری حداقل ۵ تا "
                "لازم است — کمتر از آن، الگو نیست و دنبال کردنش یعنی دنبال "
                "کردن تصادف."
            ),
            "patterns": [],
        }

    measured.sort(key=lambda r: r.engagement or 0, reverse=True)
    best = measured[: max(1, len(measured) // 3)]

    by_platform: dict[str, list[int]] = {}
    for row in measured:
        by_platform.setdefault(row.platform, []).append(row.engagement or 0)

    patterns = []
    if len(by_platform) > 1:
        ranked = sorted(
            by_platform.items(),
            key=lambda item: sum(item[1]) / len(item[1]),
            reverse=True,
        )
        top, rest = ranked[0], ranked[-1]
        top_avg = sum(top[1]) / len(top[1])
        rest_avg = sum(rest[1]) / len(rest[1]) or 1
        if top_avg > rest_avg * 1.5:
            patterns.append({
                "kind": "platform",
                "text": (
                    f"پست‌های «{top[0]}» به‌طور میانگین {top_avg:.0f} تعامل گرفتند "
                    f"و «{rest[0]}» {rest_avg:.0f} — حدود "
                    f"{top_avg / rest_avg:.1f} برابر."
                ),
            })

    with_orders = [r for r in measured if r.linked_orders]
    if with_orders:
        patterns.append({
            "kind": "orders",
            "text": (
                f"در بازه‌ی {len(with_orders)} پست، "
                f"{sum(r.linked_orders for r in with_orders)} سفارش از همان محصول "
                "ثبت شد. این فقط هم‌زمانی است، نه اثباتِ اینکه پست فروش آورده — "
                "هر سفارش به تازه‌ترین پستِ آن محصول نسبت داده شده تا دوبار شمرده نشود."
            ),
        })

    return {
        "enough_data": True,
        "posts": len(rows),
        "measured": len(measured),
        "message": "",
        "best": [
            {
                "campaign": r.publish_job.campaign.name,
                "platform": r.platform,
                "engagement": r.engagement,
                "views": r.views,
                "rate": r.engagement_rate,
                "orders": r.linked_orders,
            }
            for r in best
        ],
        "patterns": patterns,
        "unavailable": [
            {"platform": r.platform, "reason": r.unavailable_reason}
            for r in rows if r.unavailable_reason
        ][:5],
    }
