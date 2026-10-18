"""First-party analytics.

Why not Google Analytics or a hosted tracker: the cookie policy this site
publishes says we set no third-party tracking cookies, and the privacy page
says processing happens on our own servers. Bolting on a third-party script
would make both statements false — and those statements are the product's
pitch, not boilerplate.

So events land in our own database. That also happens to be what Phase 25
(Learning Engine) and Phase 26 (GTM) need: "which channel actually brings
customers" cannot be answered from someone else's dashboard.

What is deliberately *not* stored: no cookie, no fingerprint, no IP beyond the
abuse column the Lead model already keeps, nothing that identifies a person
across visits. The session id is generated per browser session and is gone when
the tab closes.
"""
from django.db import models

from apps.common.models import TimeStampedModel


class Event(TimeStampedModel):
    """One thing a visitor did on the public site."""

    class Name(models.TextChoices):
        # the funnel the marketing spec asks for, in order
        PAGE_VIEW = "page_view", "بازدید صفحه"
        CTA_CLICK = "cta_click", "کلیک روی دکمه"
        PRICING_VIEW = "pricing_view", "دیدن قیمت‌ها"
        PLAN_SELECTED = "plan_selected", "انتخاب پلن"
        CONTACT_SUBMITTED = "contact_submitted", "ارسال فرم تماس"
        SIGNUP_STARTED = "signup_started", "شروع ثبت‌نام"
        SIGNUP_COMPLETED = "signup_completed", "تکمیل ثبت‌نام"
        TOOL_USED = "tool_used", "استفاده از ابزار رایگان"

    name = models.CharField(max_length=24, choices=Name.choices)

    # Random per browser-session, not a cookie and not stable across visits.
    # Enough to stitch one visit into a funnel; useless for following someone.
    session = models.CharField(max_length=40, db_index=True)

    path = models.CharField(max_length=300, blank=True)
    locale = models.CharField(max_length=5, blank=True)
    referrer = models.CharField(max_length=300, blank=True)
    utm = models.JSONField(default=dict, blank=True)

    # Event-specific detail: which button, which plan, which tool.
    props = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["name", "-created_at"]),
            models.Index(fields=["session", "created_at"]),
        ]
        verbose_name = "رویداد"
        verbose_name_plural = "رویدادها"

    def __str__(self) -> str:
        return f"{self.get_name_display()} — {self.path or '/'}"
