"""Discovery jobs. Today: CSV imports. Later (M3): search-provider runs, same job vocabulary."""
from django.conf import settings
from django.db import models

from apps.growth_engine.core.models import BackgroundJob


class DiscoveryJob(BackgroundJob):
    class Kind(models.TextChoices):
        CSV_IMPORT = "csv_import", "ورود از فایل CSV"

    kind = models.CharField("نوع", max_length=20, choices=Kind.choices, default=Kind.CSV_IMPORT)
    file_name = models.CharField("نام فایل", max_length=200, blank=True)
    stored_name = models.CharField("فایلِ ذخیره‌شده", max_length=300, blank=True, help_text="بعد از پایانِ کار پاک می‌شود")
    encoding = models.CharField("کدگذاریِ فایل", max_length=16, blank=True)
    created_count = models.PositiveIntegerField("لیدِ تازه", default=0)
    merged_count = models.PositiveIntegerField("ادغام‌شده", default=0)
    skipped_count = models.PositiveIntegerField("ردشده", default=0)
    duplicate_count = models.PositiveIntegerField("تکراریِ منتظرِ تصمیم", default=0)
    error_count = models.PositiveIntegerField("ردیفِ خطادار", default=0)

    class Meta:
        verbose_name = "کارِ کشف"
        verbose_name_plural = "کارهای کشف"
        ordering = ["-id"]
        indexes = [models.Index(fields=["status", "-id"], name="gd_job_status_idx")]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} · {self.file_name or '—'} · {self.get_status_display()}"


class DiscoveryJobRow(models.Model):
    """A row of an import that did not simply become a lead: it has errors, or it is a duplicate
    waiting for a decision (and, afterwards, how that decision went)."""

    class Status(models.TextChoices):
        ERROR = "error", "خطا"
        DUPLICATE = "duplicate", "تکراری (منتظرِ تصمیم)"
        MERGED = "merged", "ادغام شد"
        SKIPPED = "skipped", "رد شد"
        CREATED = "created", "ساخته شد"

    job = models.ForeignKey(DiscoveryJob, on_delete=models.CASCADE, related_name="rows", verbose_name="کار")
    row_number = models.PositiveIntegerField("ردیفِ فایل", help_text="مثل شمارهٔ ردیف در اکسل (عنوان = ۱)")
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices)
    raw = models.JSONField("ردیفِ اصلی", default=dict, blank=True)
    payload = models.JSONField("دادهٔ نرمال‌شده", default=dict, blank=True)
    errors = models.JSONField("خطاها", default=list, blank=True)
    matches = models.JSONField("لیدهای هم‌پوشان", default=list, blank=True)
    matched_lead = models.ForeignKey(
        "growth_leads.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="لیدِ هم‌پوشان"
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="تصمیم‌گیرنده"
    )
    resolved_at = models.DateTimeField("زمانِ تصمیم", null=True, blank=True)

    class Meta:
        verbose_name = "ردیفِ کارِ کشف"
        verbose_name_plural = "ردیف‌های کارِ کشف"
        ordering = ["row_number"]
        constraints = [models.UniqueConstraint(fields=["job", "row_number"], name="gd_row_unique_per_job")]
        indexes = [models.Index(fields=["job", "status", "row_number"], name="gd_row_job_status_idx")]

    def __str__(self):
        return f"{self.job_id}:{self.row_number} {self.status}"
