"""Trends, and the content ideas made from them. §6 of `ایده‌ها پنل.md`.

**Trends are global; ideas are not.** What is trending in Iran today is a public
fact and the same fact for every shop, so `Trend` rows are shared and fetched
once. What a *particular* shop should make about it depends on their products
and their audience, so `TrendIdea` is per store. Storing a copy of every trend
per store would multiply the same row by the number of customers and still not
answer the question the shop actually has.

**Both carry a clock, for different reasons.** A trend goes stale because the
moment passes. An idea goes stale because the trend under it did — and an idea
whose trend has expired is shown as expired rather than quietly deleted, so a
shop that bookmarked it understands why it is no longer being suggested.
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from services.research import trends as trend_source


class Trend(TimeStampedModel):
    """One thing people were searching for, in one country, on one day."""

    title = models.CharField(max_length=200)
    region = models.CharField(max_length=4, default="IR")
    #: Google's own wording ("20K+"), kept verbatim. Parsing it into a number we
    #: would then have to defend adds precision we do not have.
    traffic = models.CharField(max_length=40, blank=True)
    context = models.JSONField(default=list, blank=True)
    image = models.URLField(blank=True)
    source = models.CharField(max_length=40, default="google_trends")
    seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-seen_at", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "region", "seen_at"], name="uniq_trend_sighting",
            )
        ]
        indexes = [models.Index(fields=["region", "-seen_at"])]

    def __str__(self):
        return f"{self.title} ({self.region})"

    @property
    def is_stale(self) -> bool:
        """«این هفته ترند است» about something eleven days old sends a shop to
        film for a moment that has passed."""
        return timezone.now() - self.seen_at > trend_source.FRESH_FOR

    @property
    def region_title(self) -> str:
        return trend_source.REGIONS.get(self.region, self.region)

    @property
    def age_hours(self) -> int:
        return int((timezone.now() - self.seen_at).total_seconds() // 3600)


class TrendIdea(TimeStampedModel):
    """«با این ترند، برای این محصول، این را بساز». §6.2"""

    class Kind(models.TextChoices):
        VIDEO = "VIDEO", "ویدیو"
        POST = "POST", "پست"
        STORY = "STORY", "استوری"
        CAPTION = "CAPTION", "متن و کپشن"

    class State(models.TextChoices):
        OPEN = "OPEN", "پیشنهاد"
        USED = "USED", "ساخته شد"
        DISMISSED = "DISMISSED", "رد شد"

    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="trend_ideas",
    )
    trend = models.ForeignKey(
        Trend, on_delete=models.CASCADE, related_name="ideas",
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="trend_ideas",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.VIDEO)
    idea = models.TextField()
    #: Why this trend has anything to do with this shop. An idea that cannot
    #: answer it is not saved — see `apps.ai.trends.suggest`.
    why = models.TextField(blank=True)
    hook = models.CharField(max_length=300, blank=True)
    state = models.CharField(
        max_length=10, choices=State.choices, default=State.OPEN,
    )
    #: Set when the shop pressed "make this", so «۶.۳ اتصال مستقیم» has a record
    #: rather than the idea vanishing into the content page.
    job_id = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "state"])]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.trend.title}"

    @property
    def expired(self) -> bool:
        return self.trend.is_stale and self.state == self.State.OPEN
