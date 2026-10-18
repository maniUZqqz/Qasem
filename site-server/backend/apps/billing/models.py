"""Plans, subscriptions and usage — the layer that makes the packages real.

Until this existed a store could generate for ever: the packages in the pitch
deck had no technical backing at all. Everything here answers one question
asked before every expensive job: *is this store allowed to do this right
now, and what has it already used this period?*

Quotas are counted in the units the pitch sells and the GPU actually spends:
**seconds of video**, **images**, **captions**. A reservation is taken before
the work starts and released if the job fails, so a crashed render does not
silently eat someone's month.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.stores.models import Store


class Plan(TimeStampedModel):
    """A sellable package. Mirrors دیتا/1-داده/data.json — keep the two in step."""

    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=200, blank=True)

    price_toman = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(
        default=True, help_text="در صفحه‌ی قیمت‌گذاری سایت نمایش داده شود"
    )
    is_trial = models.BooleanField(
        default=False, help_text="پلن آزمایشی — با محدودیت زمانی"
    )
    trial_days = models.PositiveSmallIntegerField(default=0)
    sort_order = models.PositiveSmallIntegerField(default=100)

    # monthly allowances
    video_seconds = models.PositiveIntegerField(
        default=0, help_text="مجموع ثانیه ویدیو در هر دوره"
    )
    images = models.PositiveIntegerField(default=0, help_text="تصویر در هر دوره")
    captions = models.PositiveIntegerField(default=0, help_text="کپشن در هر دوره")

    # hard limits that are not consumable
    max_products = models.PositiveIntegerField(default=0, help_text="۰ = نامحدود")
    max_stores = models.PositiveSmallIntegerField(default=1)
    allows_publishing = models.BooleanField(default=True)
    allows_sales_agent = models.BooleanField(default=True)

    class Meta:
        verbose_name = "پلن"
        verbose_name_plural = "پلن‌ها"
        ordering = ["sort_order", "price_toman"]

    def __str__(self):
        return f"{self.name} ({self.price_toman:,} تومان)"

    def allowance(self, metric: str) -> int:
        return {
            Usage.Metric.VIDEO_SECONDS: self.video_seconds,
            Usage.Metric.IMAGES: self.images,
            Usage.Metric.CAPTIONS: self.captions,
        }.get(metric, 0)


class Subscription(TimeStampedModel):
    """One store's current plan and billing period."""

    class Status(models.TextChoices):
        TRIALING = "TRIALING", "دوره آزمایشی"
        ACTIVE = "ACTIVE", "فعال"
        PAST_DUE = "PAST_DUE", "پرداخت‌نشده"
        CANCELLED = "CANCELLED", "لغو‌شده"
        EXPIRED = "EXPIRED", "منقضی"

    store = models.OneToOneField(
        Store, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIALING)

    period_start = models.DateTimeField(default=timezone.now)
    period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)

    # a manual top-up, so support can fix a bad render without a plan change
    bonus_video_seconds = models.PositiveIntegerField(default=0)
    bonus_images = models.PositiveIntegerField(default=0)
    bonus_captions = models.PositiveIntegerField(default=0)

    note = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "اشتراک"
        verbose_name_plural = "اشتراک‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.store.name} — {self.plan.name} ({self.get_status_display()})"

    # ------------------------------------------------------------------

    @property
    def grace_until(self):
        """End of the window a lapsed subscription keeps working.

        A renewal can fail for reasons that have nothing to do with intent to
        pay — an expired card, a gateway outage. Cutting service off at the
        exact second the period ends turns those into churn.
        """
        from django.conf import settings

        days = int(getattr(settings, "UPMARKET_PAYMENT", {}).get("GRACE_DAYS", 3))
        return self.period_end + timedelta(days=days)

    @property
    def in_grace(self) -> bool:
        now = timezone.now()
        return (
            self.status in (self.Status.ACTIVE, self.Status.PAST_DUE)
            and self.period_end <= now < self.grace_until
        )

    @property
    def is_usable(self) -> bool:
        if self.status in (self.Status.ACTIVE, self.Status.TRIALING) and (
            self.period_end > timezone.now()
        ):
            return True
        # A trial that runs out is over; only a subscription that has paid
        # before gets the benefit of the doubt.
        return self.in_grace

    @property
    def days_left(self) -> int:
        return max(0, (self.period_end - timezone.now()).days)

    def bonus(self, metric: str) -> int:
        return {
            Usage.Metric.VIDEO_SECONDS: self.bonus_video_seconds,
            Usage.Metric.IMAGES: self.bonus_images,
            Usage.Metric.CAPTIONS: self.bonus_captions,
        }.get(metric, 0)

    def allowance(self, metric: str) -> int:
        return self.plan.allowance(metric) + self.bonus(metric)

    def roll_period(self) -> None:
        """Start the next period. Usage rows are per-period, so nothing to reset."""
        length = self.period_end - self.period_start
        self.period_start = self.period_end
        self.period_end = self.period_start + (length or timedelta(days=30))
        if self.status == self.Status.TRIALING:
            self.status = self.Status.PAST_DUE  # trial over — needs a payment
        self.save(update_fields=["period_start", "period_end", "status", "updated_at"])


class Usage(TimeStampedModel):
    """One consumption event, always tied to the period it was spent in.

    Rows are never mutated after the fact except to release a failed
    reservation, which keeps the ledger auditable: the sum of rows in a period
    *is* the usage, with no running total to drift.
    """

    class Metric(models.TextChoices):
        VIDEO_SECONDS = "VIDEO_SECONDS", "ثانیه ویدیو"
        IMAGES = "IMAGES", "تصویر"
        CAPTIONS = "CAPTIONS", "کپشن"

    class State(models.TextChoices):
        RESERVED = "RESERVED", "رزرو‌شده"
        COMMITTED = "COMMITTED", "مصرف‌شده"
        RELEASED = "RELEASED", "آزاد‌شده"
        # Kept apart from RELEASED on purpose. Released = the job crashed and
        # produced nothing. Refunded = it produced something, we charged for
        # it, and then the output was judged unusable. Folding the two together
        # would answer "how much are we giving back for bad output?" wrongly —
        # and that number is the one that says whether the product works.
        REFUNDED = "REFUNDED", "برگشت‌خورده (کیفیت)"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="usage"
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="usage")
    metric = models.CharField(max_length=16, choices=Metric.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    state = models.CharField(max_length=10, choices=State.choices, default=State.RESERVED)

    period_start = models.DateTimeField()
    job = models.ForeignKey(
        "jobs.Job", on_delete=models.SET_NULL, null=True, blank=True, related_name="usage"
    )
    detail = models.CharField(max_length=120, blank=True)

    # true when the work ran on someone else's API instead of our GPU
    external = models.BooleanField(default=False)

    # ---- quality ---------------------------------------------------------
    # Filled when a refund happens. `attempt` counts how many times the store
    # has asked for this same thing: the quality guarantee is defined in
    # attempts, so the number has to live on the ledger row, not in a log line.
    attempt = models.PositiveSmallIntegerField(default=1)
    #: the reservation this one is a second go at, so an attempt chain can be
    #: walked without inventing a synthetic "same thing" key
    retry_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="retries"
    )
    quality_reason = models.CharField(max_length=200, blank=True)
    quality_source = models.CharField(
        max_length=10, blank=True,
        choices=[("CUSTOMER", "نظر فروشگاه‌دار"), ("AUTO", "بررسی خودکار")],
    )

    class Meta:
        verbose_name = "مصرف سهمیه"
        verbose_name_plural = "مصرف سهمیه"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["subscription", "metric", "period_start", "state"]),
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["job", "state"]),
        ]

    def __str__(self):
        return f"{self.store_id} {self.metric} {self.quantity} [{self.state}]"


# Payments live in their own module for readability; Django needs them
# imported here to register with this app.
from .payment_models import BillingEvent, Payment  # noqa: E402,F401
