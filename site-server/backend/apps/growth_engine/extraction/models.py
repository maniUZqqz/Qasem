"""ExtractionJob, ExtractionRun, ExtractionPageLog.

A job is a list of leads to read (one lead, a selection, or every lead of a CSV import). Each lead gets one
``ExtractionRun`` (what was found, and why something was or was not saved); every page fetched - or refused - is
written to ``ExtractionPageLog`` (the extraction log).
"""
from django.db import models

from apps.growth_engine.core.models import BackgroundJob


class ExtractionJob(BackgroundJob):
    class Scope(models.TextChoices):
        SINGLE = "single", "یک لید"
        SELECTED = "selected", "لیدهای انتخاب‌شده"
        CSV_IMPORT = "csv_import", "همهٔ لیدهای یک ورودی CSV"

    scope = models.CharField("دامنه", max_length=12, choices=Scope.choices, default=Scope.SELECTED)
    discovery_job = models.ForeignKey(
        "growth_discovery.DiscoveryJob", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="extraction_jobs", verbose_name="ورودیِ CSV",
    )
    runs_done = models.PositiveIntegerField("موفق", default=0)
    runs_failed = models.PositiveIntegerField("ناموفق", default=0)
    runs_skipped = models.PositiveIntegerField("ردشده", default=0)
    pages_fetched = models.PositiveIntegerField("صفحه‌های خوانده‌شده", default=0)
    contacts_added = models.PositiveIntegerField("راهِ تماسِ تازه", default=0)

    class Meta:
        verbose_name = "کارِ استخراج"
        verbose_name_plural = "کارهای استخراج"
        ordering = ["-id"]
        indexes = [models.Index(fields=["status", "-id"], name="ge_job_status_idx")]

    def __str__(self):
        return f"استخراج #{self.pk} · {self.get_scope_display()} · {self.get_status_display()}"


class ExtractionRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "در صف"
        RUNNING = "running", "در حال اجرا"
        DONE = "done", "انجام شد"
        FAILED = "failed", "ناموفق"
        SKIPPED = "skipped", "ردشد"

    #: why a run failed / was skipped (``""`` for a normal run)
    REASON_LABELS = {
        "no_website": "لید وب‌سایت ندارد",
        "recent": "به‌تازگی استخراج شده (برای دوباره‌خوانی «اجبار» را بزنید)",
        "robots_blocked": "robots.txt سایت اجازه نداد",
        "robots_unavailable": "robots.txt سایت خوانده نشد؛ برای احتیاط رد شد",
        "fetch_failed": "صفحهٔ اصلی گرفته نشد",
        "no_pages": "صفحهٔ خواندنی پیدا نشد (سایت پوستهٔ جاوااسکریپتی است)",
        "internal_error": "خطای داخلی",
    }

    job = models.ForeignKey(ExtractionJob, null=True, blank=True, on_delete=models.CASCADE, related_name="runs", verbose_name="کار")
    lead = models.ForeignKey("growth_leads.Lead", on_delete=models.CASCADE, related_name="extraction_runs", verbose_name="لید")
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.QUEUED)
    reason = models.CharField("دلیل", max_length=30, blank=True)
    started_at = models.DateTimeField("شروع", null=True, blank=True)
    finished_at = models.DateTimeField("پایان", null=True, blank=True)
    pages_fetched = models.PositiveIntegerField("صفحه‌های خوانده‌شده", default=0)
    robots_state = models.CharField("وضعیتِ robots.txt", max_length=16, blank=True)
    contacts_added = models.PositiveIntegerField("راهِ تماسِ تازه", default=0)
    findings = models.JSONField("یافته‌ها", default=list, blank=True)

    class Meta:
        verbose_name = "اجرای استخراج"
        verbose_name_plural = "اجراهای استخراج"
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["job", "lead"], name="ge_run_unique_per_job_lead")]
        indexes = [
            models.Index(fields=["lead", "-id"], name="ge_run_lead_idx"),
            models.Index(fields=["lead", "status", "-finished_at"], name="ge_run_lead_status_idx"),
        ]

    @property
    def reason_label(self) -> str:
        return self.REASON_LABELS.get(self.reason, "")

    def __str__(self):
        return f"{self.lead_id} · {self.get_status_display()}"


class ExtractionPageLog(models.Model):
    run = models.ForeignKey(ExtractionRun, on_delete=models.CASCADE, related_name="pages", verbose_name="اجرا")
    url = models.CharField("آدرس", max_length=500)
    kind = models.CharField("نوع صفحه", max_length=10, help_text="home / contact / about / support / guess / robots")
    status = models.PositiveSmallIntegerField("کدِ HTTP", default=0)
    outcome = models.CharField("نتیجه", max_length=24)
    elapsed_ms = models.PositiveIntegerField("زمان (میلی‌ثانیه)", default=0)
    bytes = models.PositiveIntegerField("حجم (بایت)", default=0)
    note = models.CharField("توضیح", max_length=300, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "گزارشِ صفحهٔ استخراج"
        verbose_name_plural = "گزارشِ صفحه‌های استخراج"
        ordering = ["id"]
        indexes = [models.Index(fields=["run", "id"], name="ge_page_run_idx")]

    def __str__(self):
        return f"{self.kind} {self.url[:60]} {self.outcome}"
