"""Call recording and what to do with it — صفحه ۷، the half that was held.

`وضعیت ساخت.md` recorded this as «معلق تا حل دو قید حقوقی»، and one of those
two is the whole design of this module rather than a reason to skip it:
**consent to record.** Consent is not a disclaimer somewhere in the terms; it
is a row saying who agreed, when, and how it was obtained. Once that exists,
recording is the ordinary thing every sales team does.

So the rule this module enforces, in code and not in a policy document:

> **No consent row, no recording.** `Recording.clean` refuses to save one, and
> nothing downstream — transcription, analysis, playback — can be reached
> without a saved row.

That is stricter than a checkbox on an upload form, on purpose: a checkbox is
something a hurried person clicks, and what it produces is indistinguishable
from consent that was actually obtained. A named, dated, sourced row is not.

**The other held half stays held, and it is a different kind of thing.**
«از روی شماره، شبکه‌های اجتماعی طرف را دربیاور» means resolving strangers'
identities from phone numbers in bulk. That is not a consent problem that a
form fixes; it is the mechanism behind doxxing, and it needs platform APIs to
be abused to work at all. It is not built here and there is no flag to turn it
on. What a shop legitimately needs — «this number, what do I already know about
them» — is `Prospect` plus `match_known_contact` below, which looks only in the
shop's own data.
"""
from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.stores.models import Store

from .models import Customer
from .outreach import Prospect

logger = logging.getLogger(__name__)

#: Longer than this and it is not a sales call, it is somebody's day. Also a
#: rough guard on transcription cost, which is per second of audio.
MAX_CALL_MINUTES = 120


class CallConsent(TimeStampedModel):
    """Permission to record this person, on the record.

    One row per prospect. `obtained_how` is required and free text because the
    honest answers differ — "said yes on the call, after the notice", "signed
    the supplier agreement", "wrote it in an email" — and a dropdown would
    flatten them into something that reads the same whether or not it happened.
    """

    class How(models.TextChoices):
        VERBAL = "VERBAL", "شفاهی، سر همان تماس و بعد از اعلام"
        WRITTEN = "WRITTEN", "کتبی — ایمیل، پیام یا قرارداد"
        CONTRACT = "CONTRACT", "در قرارداد همکاری"

    prospect = models.OneToOneField(
        Prospect, on_delete=models.CASCADE, related_name="consent",
    )
    granted = models.BooleanField(
        default=False,
        verbose_name="اجازه‌ی ضبط داده است",
        help_text="تا این تیک نخورد، هیچ فایلی برای این شخص ذخیره نمی‌شود.",
    )
    how = models.CharField(max_length=10, choices=How.choices, default=How.VERBAL)
    obtained_how = models.CharField(
        max_length=300,
        verbose_name="دقیقاً چطور",
        help_text="مثلاً «اول تماس ۱۴۰۴/۰۶/۲۰ گفتم ضبط می‌کنم و گفت اشکالی ندارد».",
    )
    obtained_at = models.DateTimeField(default=timezone.now)
    #: Consent is revocable, and a revoked one has to stop future recordings
    #: without erasing the fact that it existed when the old ones were made.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "رضایت ضبط تماس"
        verbose_name_plural = "رضایت‌های ضبط تماس"

    def __str__(self):
        return f"{self.prospect.company} — {'دارد' if self.is_active else 'ندارد'}"

    @property
    def is_active(self) -> bool:
        return bool(self.granted and not self.revoked_at)

    def clean(self):
        if self.granted and not (self.obtained_how or "").strip():
            raise ValidationError(
                {"obtained_how": "بنویسید رضایت دقیقاً چطور گرفته شد."}
            )


class Recording(TimeStampedModel):
    """One recorded call, and what came out of it."""

    class Status(models.TextChoices):
        STORED = "STORED", "ذخیره شد"
        TRANSCRIBED = "TRANSCRIBED", "پیاده شد"
        ANALYSED = "ANALYSED", "تحلیل شد"
        FAILED = "FAILED", "خطا"

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="call_recordings",
    )
    prospect = models.ForeignKey(
        Prospect, on_delete=models.CASCADE, related_name="recordings",
    )
    audio = models.FileField(upload_to="calls/")
    seconds = models.PositiveIntegerField(default=0)
    happened_at = models.DateTimeField(default=timezone.now)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.STORED,
    )
    transcript = models.TextField(blank=True)
    #: What the model made of it. Written by `analyse`, never by hand.
    summary = models.TextField(blank=True)
    #: How the call felt. Asked for and validated since day one
    #: (services/research/call_analysis.py) but, until this field existed,
    #: thrown away after every analysis — the one number on a paid call that
    #: a week of calls can be counted by.
    sentiment = models.CharField(
        max_length=8, blank=True,
        choices=[("POSITIVE", "مثبت"), ("NEUTRAL", "خنثی"), ("NEGATIVE", "منفی")],
    )
    objections = models.JSONField(default=list, blank=True)
    commitments = models.JSONField(default=list, blank=True)
    suggested_next = models.CharField(max_length=200, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-happened_at"]
        verbose_name = "ضبط تماس"
        verbose_name_plural = "ضبط تماس‌ها"

    def __str__(self):
        return f"{self.prospect.company} — {self.happened_at:%Y-%m-%d}"

    def clean(self):
        """The consent gate. Everything else in this file depends on it."""
        consent = CallConsent.objects.filter(prospect=self.prospect).first()
        if consent is None or not consent.is_active:
            raise ValidationError(
                "بدون ثبت رضایت این شخص، ضبط تماس ذخیره نمی‌شود. "
                "اول در همان سرنخ، رضایت را ثبت کنید."
            )
        if self.seconds > MAX_CALL_MINUTES * 60:
            raise ValidationError(
                {"seconds": f"بیش از {MAX_CALL_MINUTES} دقیقه — این تماس فروش نیست."}
            )

    def save(self, *args, **kwargs):
        # `full_clean` is not called by `save` in Django, and this is the one
        # rule that must not depend on a caller remembering to validate.
        self.clean()
        super().save(*args, **kwargs)


def match_known_contact(store: Store, phone: str) -> dict:
    """What this shop already knows about a number — from its own rows only.

    This is the legitimate half of «از روی شماره». It answers "have we talked
    to this person before, and where" by looking in the shop's own customers
    and prospects. It does not, and will not, ask a platform who owns a number
    that the shop has no relationship with.
    """
    number = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(number) < 7:
        return {"phone": phone, "known": False, "matches": []}

    matches = []
    tail = number[-9:]  # last nine digits: survives +98 / 0 prefixes
    for customer in Customer.objects.filter(store=store).exclude(phone=""):
        digits = "".join(ch for ch in customer.phone if ch.isdigit())
        if digits.endswith(tail):
            matches.append({
                "kind": "customer",
                "id": customer.id,
                "name": customer.name,
                "channel": customer.channel,
            })
    for prospect in Prospect.objects.filter(store=store).exclude(phone=""):
        digits = "".join(ch for ch in prospect.phone if ch.isdigit())
        if digits.endswith(tail):
            matches.append({
                "kind": "prospect",
                "id": prospect.id,
                "name": prospect.company,
                "stage": prospect.get_stage_display(),
                "social": prospect.social,
            })
    return {"phone": phone, "known": bool(matches), "matches": matches}
