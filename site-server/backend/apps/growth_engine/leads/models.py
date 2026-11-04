"""Lead, ContactPoint, BusinessProfile, LeadTag, LeadNote, LeadActivity.

Design notes
------------
* ``ContactPoint`` doubles as the **identifier registry**: a partial UNIQUE
  constraint on (kind, normalized) for phone / e-mail / website / instagram means
  two leads can never share an identifier, and the database - not a racy
  "check then insert" - is the last line of duplicate defence.
* Provenance is kept per field: ``Lead.provenance`` / ``BusinessProfile.provenance``
  map a field name to ``{"source": "manual" | "csv:<file>:<row>" | "extract:<run>", "at", "by"}``;
  every ``ContactPoint`` carries its own ``source_ref`` / ``source_url`` / ``evidence`` / ``confidence``.
* ``LeadActivity`` is append-only.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimeStampedModel
from apps.growth_engine.core import normalization as nz

from .choices import (
    IDENTIFIER_KINDS,
    ActivityKind,
    BusinessType,
    ContactKind,
    LeadOrigin,
    LeadStatus,
)


class LeadTag(TimeStampedModel):
    name = models.CharField("نام", max_length=50)
    name_key = models.CharField("کلیدِ مقایسه", max_length=60, unique=True, editable=False)
    color = models.CharField("رنگ", max_length=10, default="neutral")

    class Meta:
        verbose_name = "برچسبِ لید"
        verbose_name_plural = "برچسب‌های لید"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = nz.normalize_text(self.name)[:50]
        self.name_key = nz.search_key(self.name)[:60]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Lead(TimeStampedModel):
    business_name = models.CharField("نام کسب‌وکار", max_length=200, blank=True)
    name_key = models.CharField("کلیدِ جست‌وجوی نام", max_length=200, blank=True, editable=False, db_index=True)
    website = models.CharField("وب‌سایت", max_length=500, blank=True)
    instagram_url = models.CharField("آدرس اینستاگرام", max_length=300, blank=True)
    category = models.CharField("دستهٔ کسب‌وکار", max_length=120, blank=True)
    description = models.TextField("توضیحات", blank=True)
    country = models.CharField("کشور", max_length=2, blank=True, help_text="کد دوحرفیِ ISO، مثل IR")
    city = models.CharField("شهر", max_length=100, blank=True)
    status = models.CharField("وضعیت", max_length=24, choices=LeadStatus.choices, default=LeadStatus.NEW)
    origin = models.CharField("منبعِ کشف", max_length=24, choices=LeadOrigin.choices, default=LeadOrigin.MANUAL)
    is_archived = models.BooleanField("بایگانی‌شده", default=False)
    provenance = models.JSONField("منبعِ هر فیلد", default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ثبت‌کننده"
    )
    tags = models.ManyToManyField(LeadTag, blank=True, related_name="leads", verbose_name="برچسب‌ها")

    class Meta:
        verbose_name = "لیدِ جذب مشتری"
        verbose_name_plural = "لیدهای جذب مشتری"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["is_archived", "status", "-created_at"], name="gl_lead_arch_status_idx"),
            models.Index(fields=["is_archived", "-created_at"], name="gl_lead_arch_created_idx"),
            models.Index(fields=["country", "city"], name="gl_lead_place_idx"),
            models.Index(fields=["category"], name="gl_lead_category_idx"),
            models.Index(fields=["origin"], name="gl_lead_origin_idx"),
            models.Index(fields=["-updated_at"], name="gl_lead_updated_idx"),
        ]

    def save(self, *args, **kwargs):
        self.name_key = nz.search_key(self.business_name)[:200]
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "business_name" in update_fields and "name_key" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "name_key"]
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        """The name shown in lists. Falls back to the website host or @handle - for display only, never stored."""
        if self.business_name:
            return self.business_name
        if self.website:
            try:
                return nz.clean_url(self.website).host
            except nz.NormalizationError:
                return self.website
        if self.instagram_url:
            try:
                return "@" + nz.parse_instagram(self.instagram_url).handle
            except nz.NormalizationError:
                return self.instagram_url
        return f"لید #{self.pk}"

    def __str__(self):
        return self.display_name


class ContactPoint(TimeStampedModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="contacts", verbose_name="لید")
    kind = models.CharField("نوع", max_length=16, choices=ContactKind.choices)
    value = models.CharField("مقدار", max_length=500)
    normalized = models.CharField("کلیدِ یکتاسازی", max_length=300, blank=True)
    label = models.CharField("برچسب", max_length=80, blank=True, help_text="مثلاً «موبایلِ مدیر»")
    is_primary = models.BooleanField("اصلی", default=False)
    source_ref = models.CharField("منبع", max_length=255, blank=True, help_text="manual / csv:<فایل>:<ردیف> / extract:<اجرا>")
    source_url = models.CharField("صفحهٔ منبع", max_length=500, blank=True)
    evidence = models.CharField("مدرک", max_length=300, blank=True, help_text="کجای صفحه دیده شد")
    confidence = models.PositiveSmallIntegerField("اطمینان (۰ تا ۱۰۰)", null=True, blank=True)

    class Meta:
        verbose_name = "راهِ تماس"
        verbose_name_plural = "راه‌های تماس"
        ordering = ["-is_primary", "kind", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "normalized"],
                condition=Q(kind__in=list(IDENTIFIER_KINDS)) & ~Q(normalized=""),
                name="growth_contact_identifier_unique",
            )
        ]
        indexes = [
            models.Index(fields=["kind", "normalized"], name="gl_contact_kind_norm_idx"),
            models.Index(fields=["lead", "kind"], name="gl_contact_lead_kind_idx"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.value}"


class BusinessProfile(TimeStampedModel):
    """Structured facts about the business, filled by hand now and by extraction later."""

    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name="profile", verbose_name="لید")
    language = models.CharField("زبانِ سایت/پیج", max_length=8, blank=True, help_text="fa / en / ar ...")
    business_type = models.CharField(
        "نوعِ کسب‌وکار", max_length=24, choices=BusinessType.choices, default=BusinessType.UNKNOWN
    )
    product_categories = models.JSONField("دسته‌های محصول", default=list, blank=True)
    product_names = models.JSONField("نامِ محصولات", default=list, blank=True)
    address = models.CharField("نشانی", max_length=400, blank=True)
    provenance = models.JSONField("منبعِ هر فیلد", default=dict, blank=True)

    class Meta:
        verbose_name = "پروفایلِ کسب‌وکار"
        verbose_name_plural = "پروفایل‌های کسب‌وکار"

    def __str__(self):
        return f"پروفایل {self.lead_id}"


class LeadNote(TimeStampedModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes", verbose_name="لید")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="نویسنده"
    )
    body = models.TextField("متن")

    class Meta:
        verbose_name = "یادداشتِ لید"
        verbose_name_plural = "یادداشت‌های لید"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.body[:40]


class LeadActivity(models.Model):
    """One thing that happened to a lead. Append-only: it is the lead's history."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities", verbose_name="لید")
    kind = models.CharField("نوع", max_length=24, choices=ActivityKind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="انجام‌دهنده"
    )
    summary = models.CharField("خلاصه", max_length=300, blank=True)
    data = models.JSONField("جزئیات", default=dict, blank=True)
    source_ref = models.CharField("منبع", max_length=255, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "رویدادِ لید"
        verbose_name_plural = "تاریخچهٔ لید"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["lead", "-created_at"], name="gl_activity_lead_idx"),
            models.Index(fields=["kind", "-created_at"], name="gl_activity_kind_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("تاریخچهٔ لید قابل ویرایش نیست.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_kind_display()} · {self.lead_id}"
