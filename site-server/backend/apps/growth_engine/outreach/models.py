"""Channel, ChannelConfig, MessageTemplate, Campaign, OutreachItem, ApprovalRecord, SendAttempt, OutreachJob.

The shape that keeps outreach safe:

* ``OutreachItem`` is "one message to one business in one campaign". Two partial UNIQUE constraints make the database
  itself refuse a second message to the same business (or the same site) in a campaign.
* ``ApprovalRecord`` is append-only and bound to a fingerprint of the exact message + target + form; an approval is valid
  only while the item still carries that fingerprint (see ``services/fingerprint.py``).
* ``SendAttempt`` is one-to-one with the item: a message is posted at most once, ever.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimeStampedModel
from apps.growth_engine.core.models import BackgroundJob


class Channel(models.TextChoices):
    """A way to reach a business. The first three are sent by the system (after a human approval); the rest are done by a
    person with a ready-made link and the text to paste (no messenger account is ever automated)."""

    CONTACT_FORM = "contact_form", "فرمِ تماسِ سایت"
    EMAIL = "email", "ایمیل"
    SMS = "sms", "پیامک (از گوشیِ شما)"
    WHATSAPP = "whatsapp", "واتساپ"
    TELEGRAM = "telegram", "تلگرام"
    EITAA = "eitaa", "ایتا"
    BALE = "bale", "بله"
    RUBIKA = "rubika", "روبیکا"
    PHONE_CALL = "phone_call", "تماس تلفنی"


AUTO_CHANNELS = (Channel.CONTACT_FORM, Channel.EMAIL, Channel.SMS)
MANUAL_CHANNELS = (Channel.WHATSAPP, Channel.TELEGRAM, Channel.EITAA, Channel.BALE, Channel.RUBIKA, Channel.PHONE_CALL)
#: a campaign's channel: one of ``Channel`` or ``auto`` (every lead gets the first enabled channel, by priority, it can be reached on)
AUTO = "auto"
ANY = "any"  # a template that suits every channel
CAMPAIGN_CHANNEL_CHOICES = [*Channel.choices, (AUTO, "خودکار (بر اساسِ اولویتِ کانال‌ها)")]
TEMPLATE_CHANNEL_CHOICES = [(ANY, "همهٔ کانال‌ها"), *Channel.choices]


class ChannelConfig(TimeStampedModel):
    """The operator's settings of one channel (one row per channel, created on first change; a missing row means the defaults).

    ``config`` holds plain values (SMTP host / port / user / from ..., SMS max parts); ``secrets`` holds the SMTP password.
    Secrets are never serialised: the panel sees THAT one is set, never what it is."""

    channel = models.CharField("کانال", max_length=16, choices=Channel.choices, unique=True)
    enabled = models.BooleanField("روشن", default=False)
    priority = models.PositiveSmallIntegerField("اولویت (کمتر = زودتر)", default=100)
    daily_cap = models.PositiveSmallIntegerField("سقفِ روزانهٔ این کانال", null=True, blank=True, help_text="خالی = فقط سقفِ کلی")
    spacing_min_seconds = models.PositiveSmallIntegerField("حداقل فاصله (ثانیه)", null=True, blank=True, help_text="خالی = مثلِ تنظیماتِ کلی")
    spacing_max_seconds = models.PositiveSmallIntegerField("حداکثر فاصله (ثانیه)", null=True, blank=True)
    default_template = models.ForeignKey(
        "MessageTemplate", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="قالبِ پیش‌فرضِ این کانال"
    )
    config = models.JSONField("تنظیماتِ کانال", default=dict, blank=True)
    secrets = models.JSONField("کلیدها (هرگز نمایش داده نمی‌شود)", default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="آخرین ویرایش"
    )

    class Meta:
        verbose_name = "تنظیماتِ کانال"
        verbose_name_plural = "تنظیماتِ کانال‌ها"
        ordering = ["priority", "id"]

    def __str__(self):
        return f"{self.channel} ({'on' if self.enabled else 'off'})"


class MessageTemplate(TimeStampedModel):
    LANGUAGES = [("fa", "فارسی"), ("en", "English")]

    name = models.CharField("نام", max_length=120)
    subject = models.CharField("موضوع", max_length=200, blank=True)
    body = models.TextField("متنِ پیام")
    language = models.CharField("زبان", max_length=2, choices=LANGUAGES, default="fa")
    generator = models.CharField("روشِ ساختِ متن", max_length=30, default="placeholder")
    channel = models.CharField("کانال", max_length=16, choices=TEMPLATE_CHANNEL_CHOICES, default=ANY, help_text="این قالب برای کدام کانال نوشته شده")
    seed_key = models.CharField("کلیدِ قالبِ پیش‌فرض", max_length=60, null=True, blank=True, unique=True, help_text="فقط قالب‌های پیش‌فرضِ سامانه کلید دارند")
    is_active = models.BooleanField("فعال", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ساخته‌شده توسط"
    )

    class Meta:
        verbose_name = "قالبِ پیام"
        verbose_name_plural = "قالب‌های پیام"
        ordering = ["-id"]

    def __str__(self):
        return self.name


class Campaign(TimeStampedModel):
    class Mode(models.TextChoices):
        AUTO = "auto", "ارسال خودکار (با تأییدِ شما)"
        MANUAL = "manual", "صفِ دستی"

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        ACTIVE = "active", "فعال"
        PAUSED = "paused", "متوقف"
        COMPLETED = "completed", "تمام شد"
        CANCELLED = "cancelled", "لغو شد"

    name = models.CharField("نام", max_length=150)
    template = models.ForeignKey(MessageTemplate, on_delete=models.PROTECT, related_name="campaigns", verbose_name="قالب")
    mode = models.CharField("حالت", max_length=8, choices=Mode.choices, default=Mode.AUTO)
    channel = models.CharField("کانال", max_length=16, choices=CAMPAIGN_CHANNEL_CHOICES, default=Channel.CONTACT_FORM)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ساخته‌شده توسط"
    )
    started_at = models.DateTimeField("شروع", null=True, blank=True)
    finished_at = models.DateTimeField("پایان", null=True, blank=True)

    class Meta:
        verbose_name = "کمپینِ پیام"
        verbose_name_plural = "کمپین‌های پیام"
        ordering = ["-id"]
        indexes = [models.Index(fields=["status", "-id"], name="go_campaign_status_idx")]

    def __str__(self):
        return self.name


class ItemStatus(models.TextChoices):
    PENDING = "pending", "در انتظار آماده‌سازی"
    READY = "ready", "آمادهٔ تأیید"
    NEEDS_MANUAL = "needs_manual", "نیاز به ارسالِ دستی"
    APPROVED = "approved", "تأییدشده"
    SENDING = "sending", "در حال ارسال"
    SENT = "sent", "ارسال شد"
    FAILED = "failed", "ناموفق"
    SKIPPED = "skipped", "ردشده"
    CANCELLED = "cancelled", "لغوشده"
    MANUAL_SENT = "manual_sent", "دستی ارسال شد"
    NO_FORM = "no_form", "فرم نداشت"
    NEEDS_LOGIN = "needs_login", "نیاز به ورود داشت"
    HANDED_OFF = "handed_off", "به صفِ گوشی داده شد"
    UNREACHABLE = "unreachable", "در دسترس نبود"


#: nothing more will happen to an item in these statuses
FINAL_STATUSES = (
    ItemStatus.SENT, ItemStatus.FAILED, ItemStatus.SKIPPED, ItemStatus.CANCELLED,
    ItemStatus.MANUAL_SENT, ItemStatus.NO_FORM, ItemStatus.NEEDS_LOGIN, ItemStatus.UNREACHABLE,
)
#: an item in one of these means "this lead was already contacted (or an attempt was made) with this template"
CONTACTED_STATUSES = (ItemStatus.SENT, ItemStatus.SENDING, ItemStatus.MANUAL_SENT, ItemStatus.FAILED, ItemStatus.HANDED_OFF)
#: work still to do
OPEN_STATUSES = (ItemStatus.PENDING, ItemStatus.READY, ItemStatus.NEEDS_MANUAL, ItemStatus.APPROVED, ItemStatus.SENDING)


class OutreachItem(TimeStampedModel):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="items", verbose_name="کمپین")
    lead = models.ForeignKey("growth_leads.Lead", on_delete=models.CASCADE, related_name="outreach_items", verbose_name="لید")
    domain = models.CharField("سایت", max_length=255, blank=True, help_text="کلیدِ یکتاسازیِ وب‌سایتِ لید؛ برای «هر سایت یک پیام»")
    channel = models.CharField("کانال", max_length=16, choices=Channel.choices, default=Channel.CONTACT_FORM)
    recipient = models.CharField("گیرنده", max_length=500, blank=True, help_text="نشانیِ فرم / ایمیل / شمارهٔ موبایل / نشانیِ پیج؛ همان که پیام به آن می‌رود")
    template = models.ForeignKey(
        MessageTemplate, null=True, blank=True, on_delete=models.PROTECT, related_name="items", verbose_name="قالبِ استفاده‌شده",
        help_text="خالی = قالبِ کمپین (موردهای پیش از کانال‌ها)",
    )
    target_url = models.CharField("صفحهٔ فرم", max_length=500, blank=True)
    subject = models.CharField("موضوع", max_length=300, blank=True)
    rendered_text = models.TextField("متنِ نهاییِ پیام", blank=True)
    text_edited = models.BooleanField("متن دستی ویرایش شده", default=False)
    plan = models.JSONField("نتیجهٔ بررسیِ فرم (اجرای آزمایشی)", default=dict, blank=True)
    plan_checked_at = models.DateTimeField("زمانِ بررسیِ فرم", null=True, blank=True)
    fingerprint = models.CharField("اثر انگشت", max_length=64, blank=True)
    status = models.CharField("وضعیت", max_length=14, choices=ItemStatus.choices, default=ItemStatus.PENDING)
    skip_reason = models.CharField("کدِ دلیل", max_length=40, blank=True)
    skip_reason_text = models.CharField("دلیل", max_length=400, blank=True)
    manual_note = models.CharField("یادداشت", max_length=500, blank=True)
    approved_record = models.ForeignKey(
        "ApprovalRecord", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="آخرین تأیید"
    )
    forced = models.BooleanField("اجباری", default=False, help_text="فقط در کمپینِ دستی: با اینکه قبلاً پیام رفته بود")

    class Meta:
        verbose_name = "موردِ کمپین"
        verbose_name_plural = "موردهای کمپین"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["campaign", "lead"], name="growth_item_one_per_lead_per_campaign"),
            models.UniqueConstraint(fields=["campaign", "domain"], condition=~Q(domain=""), name="growth_item_one_per_domain_per_campaign"),
        ]
        indexes = [
            models.Index(fields=["campaign", "status", "id"], name="go_item_campaign_status_idx"),
            models.Index(fields=["lead", "status"], name="go_item_lead_status_idx"),
        ]

    def __str__(self):
        return f"{self.campaign_id}:{self.lead_id} {self.status}"


class ApprovalRecord(models.Model):
    """Who approved exactly what, when. Never updated, never deleted except together with its item."""

    item = models.ForeignKey(OutreachItem, on_delete=models.CASCADE, related_name="approvals", verbose_name="مورد")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="تأییدکننده"
    )
    approved_at = models.DateTimeField("زمانِ تأیید", auto_now_add=True)
    fingerprint = models.CharField("اثر انگشت", max_length=64)
    message_sha256 = models.CharField("sha256 متن", max_length=64)
    target_url = models.CharField("صفحهٔ فرم", max_length=500, blank=True)
    action_url = models.CharField("نشانیِ ارسال", max_length=500, blank=True)

    class Meta:
        verbose_name = "تأییدِ ارسال"
        verbose_name_plural = "تأییدهای ارسال"
        ordering = ["-id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("تأییدِ ثبت‌شده قابل ویرایش نیست.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"تأیید {self.item_id} · {self.fingerprint[:10]}"


class SendAttempt(models.Model):
    """The one and only attempt to post an item's message. Its existence blocks any second attempt."""

    class Guess(models.TextChoices):
        SUCCESS = "likely_success", "به نظر موفق"
        UNCLEAR = "unclear", "نامشخص"
        FAILURE = "likely_failure", "به نظر ناموفق"

    item = models.OneToOneField(OutreachItem, on_delete=models.CASCADE, related_name="attempt", verbose_name="مورد")
    channel = models.CharField("کانال", max_length=16, choices=Channel.choices, default=Channel.CONTACT_FORM)
    attempted_at = models.DateTimeField("زمان", auto_now_add=True)
    url = models.CharField("نشانیِ ارسال", max_length=500)
    method = models.CharField("روش", max_length=8, default="POST")
    payload = models.JSONField("دادهٔ ارسال‌شده", default=list, blank=True, help_text="لیستِ {name, value}؛ مقدارِ فیلدهای مخفیِ صفحه به «***» تبدیل شده")
    status_code = models.PositiveSmallIntegerField("کدِ HTTP", default=0)
    response_snippet = models.TextField("بخشی از پاسخ", blank=True)
    success_guess = models.CharField("حدسِ موفقیت", max_length=16, choices=Guess.choices, default=Guess.UNCLEAR)
    outcome = models.CharField("نتیجهٔ اتصال", max_length=24, blank=True)
    error = models.CharField("خطا", max_length=400, blank=True)
    elapsed_ms = models.PositiveIntegerField("زمان (میلی‌ثانیه)", default=0)

    class Meta:
        verbose_name = "تلاشِ ارسال"
        verbose_name_plural = "تلاش‌های ارسال"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["attempted_at"], name="go_attempt_time_idx"),
            models.Index(fields=["channel", "attempted_at"], name="go_attempt_channel_idx"),
        ]

    def __str__(self):
        return f"{self.item_id} {self.status_code} {self.success_guess}"


class OutreachJob(BackgroundJob):
    class Kind(models.TextChoices):
        PREPARE = "prepare", "آماده‌سازیِ فرم‌ها"
        SEND = "send", "ارسال"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="jobs", verbose_name="کمپین")
    kind = models.CharField("نوع", max_length=8, choices=Kind.choices)
    items_sent = models.PositiveIntegerField("ارسال‌شده", default=0)
    items_failed = models.PositiveIntegerField("ناموفق", default=0)
    items_blocked = models.PositiveIntegerField("ردشده/نیازمندِ دست", default=0)
    note = models.CharField("یادداشتِ پایان", max_length=400, blank=True, help_text="مثلاً «سقفِ روزانه پر شد»")

    class Meta:
        verbose_name = "کارِ پیام‌رسانی"
        verbose_name_plural = "کارهای پیام‌رسانی"
        ordering = ["-id"]
        indexes = [models.Index(fields=["campaign", "kind", "-id"], name="go_job_campaign_idx")]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} · {self.get_status_display()}"
