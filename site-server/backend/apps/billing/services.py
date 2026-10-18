"""Quota enforcement — the gate every expensive job passes through.

Two rules shape this module:

1. **Reserve before, commit after.** A render that dies must not eat the
   month, so work takes a reservation up front and either commits it on
   success or releases it on failure.
2. **Never invent an allowance.** A store with no subscription gets the trial
   plan if one is configured and is otherwise blocked with a clear message —
   it is never quietly let through.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Plan, Subscription, Usage

logger = logging.getLogger(__name__)

# usage that still counts against the period
COUNTED = (Usage.State.RESERVED, Usage.State.COMMITTED)


class QuotaExceeded(Exception):
    """The store has run out of this month's allowance."""

    def __init__(self, metric: str, need: int, left: int, plan: str):
        self.metric, self.need, self.left, self.plan = metric, need, left, plan
        label = dict(Usage.Metric.choices).get(metric, metric)
        super().__init__(
            f"سهمیه‌ی «{label}» پلن {plan} تمام شده است. "
            f"باقی‌مانده: {left} · درخواست: {need}. "
            "برای ادامه، پلن را ارتقا بده یا تا دوره‌ی بعد صبر کن."
        )


class NoSubscription(Exception):
    """The store cannot generate anything until it has a plan."""

    def __init__(self):
        super().__init__(
            "این فروشگاه اشتراک فعالی ندارد. "
            "برای تولید محتوا ابتدا یک پلن انتخاب کن."
        )


# --------------------------------------------------------------- lookup


def billing_enabled() -> bool:
    """Is anyone selling yet?

    A fresh install has no Plan rows. Enforcing quotas then would brick the
    product before `seed_plans` has ever run, so billing switches itself on
    the moment the first plan exists and stays off until then.
    """
    return Plan.objects.exists()


def subscription_for(store, *, create_trial: bool = True) -> Subscription:
    """The store's live subscription, starting a trial when that is allowed."""
    sub = Subscription.objects.filter(store=store).select_related("plan").first()

    if sub and sub.period_end <= timezone.now():
        # the period lapsed — roll it so a returning customer is not blocked
        # by a stale window, then re-check usability
        sub.roll_period()

    if sub and sub.is_usable:
        return sub
    if sub:
        raise NoSubscription()

    if not create_trial:
        raise NoSubscription()

    trial = Plan.objects.filter(is_trial=True).order_by("sort_order").first()
    if trial is None:
        raise NoSubscription()

    days = trial.trial_days or 14
    now = timezone.now()
    return Subscription.objects.create(
        store=store,
        plan=trial,
        status=Subscription.Status.TRIALING,
        period_start=now,
        period_end=now + timedelta(days=days),
    )


def used(sub: Subscription, metric: str) -> int:
    """How much of this metric the current period has already spent."""
    total = (
        Usage.objects.filter(
            subscription=sub,
            metric=metric,
            period_start=sub.period_start,
            state__in=COUNTED,
        ).aggregate(total=Sum("quantity"))["total"]
    )
    return int(total or 0)


def remaining(sub: Subscription, metric: str) -> int:
    return max(0, sub.allowance(metric) - used(sub, metric))


def snapshot(store) -> dict:
    """Everything the UI needs to draw the usage bars."""
    if not billing_enabled():
        return {"subscription": None, "metrics": [], "blocked": False, "billing": False}
    try:
        sub = subscription_for(store, create_trial=False)
    except NoSubscription:
        return {"subscription": None, "metrics": [], "blocked": True}

    # Refunds this period, per metric. Shown next to usage on purpose: a store
    # that got three credits back should see that, not quietly notice its
    # allowance lasting longer than expected.
    refunded = {
        row["metric"]: row["total"]
        for row in Usage.objects.filter(
            subscription=sub, period_start=sub.period_start,
            state=Usage.State.REFUNDED,
        ).values("metric").annotate(total=Sum("quantity"))
    }

    metrics = []
    for metric, label in Usage.Metric.choices:
        allowed = sub.allowance(metric)
        spent = used(sub, metric)
        metrics.append({
            "metric": metric,
            "label": label,
            "allowed": allowed,
            "used": spent,
            "remaining": max(0, allowed - spent),
            "percent": round(spent / allowed * 100, 1) if allowed else 0.0,
            "refunded": refunded.get(metric, 0),
        })
    return {
        "subscription": {
            "plan": sub.plan.name,
            "plan_slug": sub.plan.slug,
            "status": sub.status,
            "status_label": sub.get_status_display(),
            "period_start": sub.period_start,
            "period_end": sub.period_end,
            "days_left": sub.days_left,
            "price_toman": sub.plan.price_toman,
        },
        "metrics": metrics,
        "blocked": not sub.is_usable,
    }


# ------------------------------------------------------------ reserve


@transaction.atomic
def reserve(store, metric: str, quantity: int, *, job=None, detail="", external=False) -> Usage | None:
    """Take `quantity` off the store's allowance, or raise.

    The row is created inside a locked read of prior usage so two jobs
    starting at once cannot both slip past the last unit.
    """
    if quantity <= 0:
        raise ValueError("مقدار رزرو باید مثبت باشد.")
    if not billing_enabled():
        return None  # nothing to bill against yet

    sub = subscription_for(store)
    # lock the subscription row; concurrent reserves for the same store queue up
    sub = Subscription.objects.select_for_update().select_related("plan").get(pk=sub.pk)

    left = remaining(sub, metric)
    if quantity > left:
        raise QuotaExceeded(metric, quantity, left, sub.plan.name)

    row = Usage.objects.create(
        subscription=sub,
        store=store,
        metric=metric,
        quantity=quantity,
        state=Usage.State.RESERVED,
        period_start=sub.period_start,
        job=job,
        detail=detail[:120],
        external=external,
    )
    logger.info(
        "quota reserve store=%s %s x%s (left %s)",
        store.id, metric, quantity, left - quantity,
    )
    return row


def commit(row: Usage | None) -> None:
    """Mark reserved usage as really spent."""
    if row is None or row.state != Usage.State.RESERVED:
        return
    row.state = Usage.State.COMMITTED
    row.save(update_fields=["state", "updated_at"])


def release(row: Usage | None, reason: str = "") -> None:
    """Give a reservation back after a failed job."""
    if row is None or row.state != Usage.State.RESERVED:
        return
    row.state = Usage.State.RELEASED
    row.detail = (f"{row.detail} · آزاد شد: {reason}".strip(" ·"))[:120]
    row.save(update_fields=["state", "detail", "updated_at"])
    logger.info("quota release store=%s %s x%s (%s)",
                row.store_id, row.metric, row.quantity, reason)


class reserved:
    """Context manager: reserve, then commit on success / release on error.

        with reserved(store, Usage.Metric.IMAGES, 1, job=job):
            ...generate...
    """

    def __init__(self, store, metric, quantity, *, job=None, detail="", external=False):
        self.args = (store, metric, quantity)
        self.kwargs = {"job": job, "detail": detail, "external": external}
        self.row: Usage | None = None

    def __enter__(self) -> Usage:
        self.row = reserve(*self.args, **self.kwargs)
        return self.row

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            commit(self.row)
        else:
            release(self.row, reason=f"{exc_type.__name__}")
        return False  # never swallow


# --------------------------------------------------------------- limits


def check_product_limit(store) -> None:
    """Plans may cap how many products a store keeps."""
    if not billing_enabled():
        return
    sub = subscription_for(store)
    cap = sub.plan.max_products
    if not cap:
        return
    from apps.products.models import Product

    count = Product.objects.filter(store=store).count()
    if count >= cap:
        raise QuotaExceeded("PRODUCTS", 1, 0, sub.plan.name)


def feature_allowed(store, feature: str) -> bool:
    """`publishing` / `sales_agent` gates that are on/off rather than counted."""
    if not billing_enabled():
        return True
    try:
        sub = subscription_for(store, create_trial=False)
    except NoSubscription:
        return False
    return bool(getattr(sub.plan, f"allows_{feature}", False))
