"""Leads from the public website.

A Lead is platform-level, not store-level: it arrives before the person has an
account, so it cannot hang off a Store the way Notification does. It belongs to
*us*, and it is read in the Django admin.

Deliberately minimal. The contact form asks for as little as it can get away
with — every extra required field costs conversions — so most columns are
optional and the serializer enforces only what is genuinely needed.
"""
from django.db import models

from apps.common.models import TimeStampedModel


class Lead(TimeStampedModel):
    """Someone who filled the contact form on the public site."""

    class Status(models.TextChoices):
        NEW = "NEW", "جدید"
        CONTACTED = "CONTACTED", "تماس گرفته شد"
        QUALIFIED = "QUALIFIED", "واجد شرایط"
        CONVERTED = "CONVERTED", "تبدیل به مشتری"
        SPAM = "SPAM", "اسپم"
        CLOSED = "CLOSED", "بسته‌شده"

    class Subject(models.TextChoices):
        DEMO = "DEMO", "درخواست دمو"
        PRICING = "PRICING", "سؤال درباره قیمت"
        SUPPORT = "SUPPORT", "پشتیبانی"
        PARTNERSHIP = "PARTNERSHIP", "همکاری"
        OTHER = "OTHER", "موضوع دیگر"

    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    business = models.CharField(max_length=160, blank=True)
    subject = models.CharField(
        max_length=16, choices=Subject.choices, default=Subject.OTHER
    )
    message = models.TextField()

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    # Free-text for whoever follows up; never shown to the lead.
    notes = models.TextField(blank=True)

    # --- attribution -----------------------------------------------------
    # Which page and which campaign produced this lead. Phase 26 (GTM) needs
    # this to answer "which channel actually brings customers"; capturing it
    # now costs nothing and cannot be reconstructed later.
    source_path = models.CharField(max_length=300, blank=True)
    referrer = models.CharField(max_length=300, blank=True)
    utm = models.JSONField(default=dict, blank=True)

    # --- abuse handling --------------------------------------------------
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["email"]),
        ]
        verbose_name = "لید"
        verbose_name_plural = "لیدها"

    def __str__(self) -> str:
        return f"{self.name} <{self.email}> — {self.get_status_display()}"


# Analytics lives in its own module for readability; Django needs it imported
# here to register the model with this app.
from .events import Event  # noqa: E402,F401


# GTM: referral, affiliate, discount codes and attribution (phase 26). Their own
# module for size; imported here so Django discovers them.
from .gtm import (  # noqa: E402,F401
    Affiliate,
    Attribution,
    DiscountCode,
    Redemption,
    ReferralCode,
    Reward,
)
