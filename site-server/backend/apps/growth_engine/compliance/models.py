"""Compliance: Growth Settings (sender identity, caps, emergency stop), the do-not-contact list, the audit log."""
from django.conf import settings
from django.db import models

DEFAULT_OPT_OUT = "اگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو»."


class GrowthSettings(models.Model):
    """One row (pk=1) with everything an operator may change about outreach. Safe defaults: sending is OFF."""

    sending_enabled = models.BooleanField("ارسالِ خودکار روشن است", default=False)
    emergency_stop = models.BooleanField("توقفِ اضطراری", default=False)
    sender_name = models.CharField("نامِ واقعیِ فرستنده", max_length=100, blank=True)
    sender_company = models.CharField("نامِ شرکت", max_length=120, blank=True)
    sender_phone = models.CharField("تلفنِ فرستنده", max_length=40, blank=True)
    sender_email = models.CharField("ایمیلِ فرستنده", max_length=200, blank=True)
    sender_website = models.CharField("وب‌سایتِ فرستنده", max_length=300, blank=True)
    opt_out_line = models.CharField("جملهٔ لغو عضویت", max_length=300, default=DEFAULT_OPT_OUT)
    daily_cap = models.PositiveSmallIntegerField("سقفِ روزانه", default=40)
    spacing_min_seconds = models.PositiveSmallIntegerField("حداقل فاصلهٔ دو ارسال (ثانیه)", default=60)
    spacing_max_seconds = models.PositiveSmallIntegerField("حداکثر فاصلهٔ دو ارسال (ثانیه)", default=120)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="آخرین ویرایش"
    )
    updated_at = models.DateTimeField("زمانِ آخرین ویرایش", auto_now=True)

    class Meta:
        verbose_name = "تنظیماتِ جذب مشتری"
        verbose_name_plural = "تنظیماتِ جذب مشتری"

    @classmethod
    def load(cls) -> "GrowthSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1  # a singleton
        super().save(*args, **kwargs)

    def identity_problems(self) -> list[str]:
        problems = []
        for value, text in (
            (self.sender_name, "نامِ واقعیِ فرستنده را بنویسید."),
            (self.sender_company, "نامِ شرکت را بنویسید."),
            (self.sender_phone, "تلفنِ فرستنده را بنویسید."),
            (self.sender_email, "ایمیلِ فرستنده را بنویسید."),
            (self.opt_out_line.strip(), "جملهٔ لغو عضویت نباید خالی باشد."),
        ):
            if not (value or "").strip():
                problems.append(text)
        return problems

    def readiness(self) -> dict:
        """Can outreach run? ``sending_enabled`` is reported separately: it is the operator's own switch."""
        problems = self.identity_problems()
        if self.emergency_stop:
            problems.append("توقفِ اضطراری فعال است.")
        return {"ok": not problems, "problems": problems}

    def __str__(self):
        return "تنظیماتِ جذب مشتری"


class SuppressionReason(models.TextChoices):
    OPT_OUT = "opt_out", "درخواستِ لغو داد"
    ASKED = "asked_not_to_contact", "خواست پیام نگیرد"
    COMPLAINT = "complaint", "شکایت کرد"
    INVALID = "invalid_contact", "راهِ تماسِ نامعتبر"
    OTHER = "other", "دلیلِ دیگر"


class SuppressionKind(models.TextChoices):
    PHONE = "phone", "تلفن"
    EMAIL = "email", "ایمیل"
    WEBSITE = "website", "وب‌سایت"
    INSTAGRAM = "instagram", "اینستاگرام"


class SuppressionEntry(models.Model):
    """An identifier that must never be contacted. No link to a lead: the identifier itself is what is blocked."""

    kind = models.CharField("نوع", max_length=12, choices=SuppressionKind.choices)
    normalized = models.CharField("کلیدِ یکتاسازی", max_length=300)
    value = models.CharField("مقدار", max_length=500)
    reason = models.CharField("دلیل", max_length=24, choices=SuppressionReason.choices, default=SuppressionReason.OTHER)
    note = models.CharField("توضیح", max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ثبت‌کننده"
    )
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "موردِ فهرستِ «تماس نگیر»"
        verbose_name_plural = "فهرستِ «تماس نگیر»"
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["kind", "normalized"], name="growth_suppression_unique")]
        indexes = [models.Index(fields=["kind", "normalized"], name="gc_suppress_lookup_idx")]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.value}"


class AuditKind(models.TextChoices):
    SETTINGS = "settings_changed", "تنظیمات عوض شد"
    STOP = "emergency_stop", "توقفِ اضطراری"
    RESUME = "emergency_resume", "رفعِ توقفِ اضطراری"
    SUPPRESS_ADDED = "suppress_added", "به فهرستِ «تماس نگیر» اضافه شد"
    SUPPRESS_REMOVED = "suppress_removed", "از فهرستِ «تماس نگیر» برداشته شد"
    CAMPAIGN = "campaign_status", "وضعیتِ کمپین عوض شد"
    APPROVAL = "approval", "تأییدِ ارسال"
    SEND = "send_attempt", "تلاش برای ارسال"


class AuditEntry(models.Model):
    """Append-only trail of the actions that matter for outreach compliance."""

    kind = models.CharField("نوع", max_length=24, choices=AuditKind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="انجام‌دهنده"
    )
    summary = models.CharField("خلاصه", max_length=300)
    data = models.JSONField("جزئیات", default=dict, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "ردِ ممیزی"
        verbose_name_plural = "ممیزی"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["kind", "-created_at"], name="gc_audit_kind_idx")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("ردِ ممیزی قابل ویرایش نیست.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_kind_display()} · {self.summary[:40]}"
