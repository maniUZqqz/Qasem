"""Competitors as things the shop keeps, not as a fact about one product.

Research already existed, but it hung off a `Product`: ask about a shoe, get a
paragraph about whoever was selling shoes that day. §3 asks for something
different — a list the shop owner maintains, with the competitor's products,
prices and business model attached, so "where do I sit against them?" has an
answer that survives longer than one query.

The distinction that shapes these models: **what we observed** and **what we
concluded** are separate fields. An observed price came from a page on a given
day and can be shown to a customer as fact; a conclusion came from a model and
is an opinion with a date on it. Mixing them is how a shop ends up repricing
against a number nobody can source.
"""
from django.db import models

from apps.common.models import TimeStampedModel
from apps.products.models import Product
from apps.stores.models import Store


class Competitor(TimeStampedModel):
    """One business this shop competes with."""

    class Kind(models.TextChoices):
        DIRECT = "DIRECT", "رقیب مستقیم"
        ADJACENT = "ADJACENT", "رقیب غیرمستقیم"
        MARKETPLACE = "MARKETPLACE", "مارکت‌پلیس (دیجی‌کالا، ترب…)"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="competitors")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.DIRECT)
    website = models.URLField(blank=True)
    instagram = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True, verbose_name="یادداشت خودِ فروشگاه‌دار")

    # ---- what the model concluded, with a date attached ------------------
    #: §3.4 — how they make money. An opinion, and labelled as one.
    revenue_model = models.TextField(blank=True)
    positioning = models.TextField(blank=True)
    strengths = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    analysed_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["store", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "name"], name="one_competitor_name_per_store"
            ),
        ]
        verbose_name = "رقیب"
        verbose_name_plural = "رقبا"

    def __str__(self):
        return f"{self.name} ({self.store.name})"

    @property
    def is_stale(self) -> bool:
        """Older than a month, so the conclusions should be read with care.

        Prices move. A positioning statement from last quarter is history, not
        intelligence, and the panel says so rather than showing it plainly.
        """
        if not self.analysed_at:
            return True
        from django.utils import timezone

        return (timezone.now() - self.analysed_at).days > 30


class CompetitorProduct(TimeStampedModel):
    """Something a competitor sells, and what it cost on the day we looked.

    §3.2 and §3.3. `observed_at` is not decoration: a price with no date is a
    claim, and repricing against one is how a shop loses money confidently.
    """

    competitor = models.ForeignKey(
        Competitor, on_delete=models.CASCADE, related_name="products"
    )
    name = models.CharField(max_length=200)
    url = models.URLField(blank=True)
    price_toman = models.PositiveBigIntegerField(null=True, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    #: Which of our own products this one competes with, when it is clear.
    matches = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="competitor_products",
    )
    source = models.CharField(
        max_length=32, blank=True,
        help_text="دیجی‌کالا، ترب، سایت خودشان، دستی…",
    )
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["competitor", "name"]
        indexes = [models.Index(fields=["competitor", "matches"])]
        verbose_name = "محصول رقیب"
        verbose_name_plural = "محصولات رقبا"

    def __str__(self):
        return f"{self.name} — {self.competitor.name}"


class Opportunity(TimeStampedModel):
    """A recommendation the shop can act on. §4.

    Stored rather than generated on every page load, for a reason that matters:
    the owner needs to be able to dismiss one and not see it again. A
    suggestion that reappears after being rejected stops being a suggestion and
    becomes noise.
    """

    class Kind(models.TextChoices):
        PRICING = "PRICING", "قیمت‌گذاری"
        NEW_PRODUCT = "NEW_PRODUCT", "محصول جدید"
        BUNDLE = "BUNDLE", "فروش مکمل"
        CHANNEL = "CHANNEL", "کانال فروش"
        CONTENT = "CONTENT", "محتوا"
        INVENTORY = "INVENTORY", "موجودی"

    class State(models.TextChoices):
        OPEN = "OPEN", "باز"
        DONE = "DONE", "انجام شد"
        DISMISSED = "DISMISSED", "رد شد"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="opportunities")
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, null=True, blank=True,
        related_name="opportunities",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=200)
    reason = models.TextField(
        help_text="چرا این پیشنهاد شد — با عددی که از آن آمده، نه حرف کلی",
    )
    action = models.CharField(max_length=300, help_text="قدم بعدی، به زبان ساده")
    #: What this was derived from. A recommendation whose source cannot be
    #: named is a guess, and the owner should be able to tell the difference.
    evidence = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)
    #: Higher is more urgent. Kept small and integer so sorting is obvious.
    priority = models.PositiveSmallIntegerField(default=50)

    class Meta:
        ordering = ["-priority", "-created_at"]
        indexes = [models.Index(fields=["store", "state", "-priority"])]
        verbose_name = "فرصت فروش"
        verbose_name_plural = "فرصت‌های فروش"

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title}"
