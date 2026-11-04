"""LeadSource: where (and how) a lead's information came from.

One row per discovery event. A lead found by a CSV import and later merged with a
manual entry has two sources; nothing is overwritten, both stay on record.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class SourceProvider(models.TextChoices):
    MANUAL = "manual", "ثبت دستی"
    WEBSITE_URL = "website_url", "آدرس وب‌سایت"
    INSTAGRAM_URL = "instagram_url", "پیج اینستاگرام"
    BUSINESS_NAME = "business_name", "نام کسب‌وکار"
    CSV_IMPORT = "csv_import", "فایل CSV"
    CONTACT_EXTRACTION = "contact_extraction", "استخراج از سایتِ خودِ کسب‌وکار"
    # M3 adds search_api / directory providers here


class LeadSource(models.Model):
    lead = models.ForeignKey("growth_leads.Lead", on_delete=models.CASCADE, related_name="sources", verbose_name="لید")
    provider = models.CharField("روشِ کشف", max_length=24, choices=SourceProvider.choices)
    source_ref = models.CharField("مرجع", max_length=255, blank=True, help_text="manual / csv:<فایل>:<ردیف> / extract:<اجرا>")
    source_url = models.CharField("آدرسِ منبع", max_length=500, blank=True)
    discovered_at = models.DateTimeField("زمانِ کشف", default=timezone.now)
    job = models.ForeignKey(
        "growth_discovery.DiscoveryJob", null=True, blank=True, on_delete=models.SET_NULL, related_name="sources",
        verbose_name="کارِ کشف",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ثبت‌کننده"
    )
    raw_data = models.JSONField("دادهٔ خامِ ورودی", default=dict, blank=True, help_text="همان چیزی که کاربر یا فایل داده، بدون دست‌کاری")

    class Meta:
        verbose_name = "منبعِ لید"
        verbose_name_plural = "منبع‌های لید"
        ordering = ["discovered_at", "id"]
        indexes = [
            models.Index(fields=["lead", "discovered_at"], name="gs_source_lead_idx"),
            models.Index(fields=["provider", "discovered_at"], name="gs_source_provider_idx"),
            models.Index(fields=["job"], name="gs_source_job_idx"),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} · {self.source_ref or '—'}"
