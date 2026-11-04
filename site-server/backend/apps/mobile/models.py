"""NM-Mobile: paired phones, the SMS queue, calls, product floor prices and guarded messenger lookups.

Everything here is staff-only. The phone never holds a password: it pairs once with a staff login and then
carries a revocable device token (only its SHA-256 is stored).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings as dj_settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.models import TimeStampedModel

User = dj_settings.AUTH_USER_MODEL

LOOKUP_PLATFORMS = ("telegram", "whatsapp", "eitaa", "bale", "soroush", "rubika")


def new_device_token() -> str:
    return "nmd_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ settings (one row)

class MobileSettings(models.Model):
    sms_enabled = models.BooleanField("صفِ پیامک روشن است", default=True,
                                      help_text="خاموش = هیچ پیامکی به گوشی‌ها داده نمی‌شود (توقفِ کلیِ صف).")
    forward_incoming_sms = models.BooleanField("پیامک‌های دریافتی به NM فرستاده شود", default=False,
                                               help_text="خاموش: فقط پاسخ‌های «لغو/stop» پردازش می‌شوند و بقیه ذخیره نمی‌شوند.")
    calls_upload_enabled = models.BooleanField("بارگذاریِ ضبط تماس", default=True)
    asr_enabled = models.BooleanField("تبدیلِ تماس به متن", default=True)
    max_sms_per_hour = models.PositiveIntegerField("سقفِ پیامک در ساعت برای هر گوشی", default=120)
    max_sms_per_day = models.PositiveIntegerField("سقفِ پیامک در روز برای هر گوشی", default=600)
    max_marketing_per_hour = models.PositiveIntegerField("سقفِ پیامکِ تبلیغاتی در ساعت برای هر گوشی", default=30)
    claim_batch = models.PositiveSmallIntegerField("حداکثرِ پیامک در هر نوبت", default=5)
    poll_interval_s = models.PositiveSmallIntegerField("فاصلهٔ پرسش گوشی (ثانیه)", default=5)
    lease_seconds = models.PositiveIntegerField("مهلتِ گزارشِ ارسال (ثانیه)", default=120)
    quiet_start_hour = models.PositiveSmallIntegerField("شروعِ ساعتِ سکوتِ پیامکِ تبلیغاتی", default=21)
    quiet_end_hour = models.PositiveSmallIntegerField("پایانِ ساعتِ سکوت", default=8)
    otp_ignores_opt_out = models.BooleanField(
        "کدِ تأیید (OTP) به فهرستِ «لغو» توجه نکند", default=False,
        help_text="پیش‌فرض خاموش: شماره‌ای که لغو داده هیچ پیامی، حتی کد، نمی‌گیرد.")
    max_audio_mb = models.PositiveSmallIntegerField("بیشینهٔ حجمِ فایلِ ضبط (مگابایت)", default=100)
    default_store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                      verbose_name="فروشگاهِ پیش‌فرضِ دستیار تماس")

    # --- messenger lookups (caller identification)
    lookup_platforms = models.JSONField("پیام‌رسان‌های روشن", default=dict, blank=True,
                                        help_text='{"whatsapp": true, ...}؛ پیش‌فرض همه خاموش')
    lookup_cache_days = models.PositiveSmallIntegerField("نگهداریِ نتیجه (روز)", default=30)
    lookup_min_refresh_minutes = models.PositiveIntegerField("کمترین فاصلهٔ تازه‌سازی (دقیقه)", default=60)
    lookup_per_device_hour = models.PositiveSmallIntegerField("جستجو در ساعت برای هر گوشی", default=10)
    lookup_per_device_day = models.PositiveSmallIntegerField("جستجو در روز برای هر گوشی", default=60)
    lookup_per_platform_day = models.PositiveSmallIntegerField("جستجو در روز برای هر پیام‌رسان (کل)", default=100)
    lookup_manual_per_user_day = models.PositiveSmallIntegerField("جستجوی دستی در روز برای هر کاربر", default=20)
    lookup_burst_numbers_per_hour = models.PositiveSmallIntegerField(
        "حداکثر شماره‌ی متفاوت در ساعت از یک گوشی", default=12,
        help_text="بیشتر از این یعنی انگار فهرست می‌گردد؛ مسدود می‌شود.")

    class Meta:
        verbose_name = "تنظیماتِ موبایل"
        verbose_name_plural = "تنظیماتِ موبایل"

    def __str__(self):
        return "تنظیماتِ موبایل"

    @classmethod
    def get(cls) -> "MobileSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def platform_enabled(self, key: str) -> bool:
        return (self.lookup_platforms or {}).get(key) is True


# ------------------------------------------------------------------ devices

class MobileDevice(TimeStampedModel):
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mobile_devices")
    name = models.CharField("نام گوشی", max_length=120)
    install_id = models.CharField(max_length=64, unique=True)
    model = models.CharField(max_length=120, blank=True)
    android_version = models.CharField(max_length=20, blank=True)
    app_version = models.CharField(max_length=30, blank=True)
    token_hash = models.CharField(max_length=64, unique=True)
    token_prefix = models.CharField(max_length=12, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sms_enabled = models.BooleanField("دریافتِ پیامک برای ارسال", default=True)
    # last heartbeat
    battery_percent = models.SmallIntegerField(null=True, blank=True)
    charging = models.BooleanField(null=True, blank=True)
    network = models.CharField(max_length=12, blank=True)
    sims = models.JSONField(default=list, blank=True)
    sms_ready = models.BooleanField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "گوشیِ جفت‌شده"
        verbose_name_plural = "گوشی‌های جفت‌شده"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user})"

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    @property
    def online(self) -> bool:
        return bool(self.active and self.last_seen_at and (timezone.now() - self.last_seen_at) < timedelta(seconds=150))


class MobileActionLog(models.Model):
    """Every action taken from a phone or the panel: who, from which device, what, and how it ended."""

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="actions")
    action = models.CharField(max_length=60, db_index=True)
    target = models.CharField(max_length=80, blank=True)
    params = models.JSONField(default=dict, blank=True)
    ok = models.BooleanField(default=True)
    message = models.CharField(max_length=400, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "ثبتِ اقدام"
        verbose_name_plural = "ثبتِ اقدام‌های موبایل"
        ordering = ["-created_at", "-id"]


# ------------------------------------------------------------------ SMS

class SmsOptOut(models.Model):
    """Global «never message again» list. A number replies لغو / stop once and is never messaged again."""

    class Reason(models.TextChoices):
        STOP_REPLY = "stop_reply", "پاسخِ لغو/stop"
        MANUAL = "manual", "ثبتِ دستی"
        IMPORT = "import", "واردشده"

    number = models.CharField(max_length=20, unique=True)
    key = models.CharField(max_length=10, db_index=True)
    reason = models.CharField(max_length=12, choices=Reason.choices, default=Reason.MANUAL)
    source_text = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "شمارهٔ لغوشده"
        verbose_name_plural = "فهرستِ «پیامک نفرست»"
        ordering = ["-created_at"]


class SmsCampaignApproval(models.Model):
    """A human said yes to a marketing campaign. Marketing SMS can only come from a campaign with an active row here.

    Growth Engine (or any NM app) calls `apps.mobile.api.register_campaign_approval(...)` AFTER its own human approval.
    """

    ref = models.CharField(max_length=80, unique=True)
    title = models.CharField(max_length=200)
    source = models.CharField(max_length=30, default="manual")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    max_messages = models.PositiveIntegerField(null=True, blank=True)
    sent_count = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "تأییدِ کمپینِ پیامکی"
        verbose_name_plural = "تأییدهای کمپینِ پیامکی"
        ordering = ["-approved_at"]

    def __str__(self):
        return f"{self.ref} — {self.title}"

    @property
    def active(self) -> bool:
        if self.revoked_at:
            return False
        if self.valid_until and self.valid_until <= timezone.now():
            return False
        if self.max_messages is not None and self.sent_count >= self.max_messages:
            return False
        return True


class SmsMessage(TimeStampedModel):
    class Kind(models.TextChoices):
        OTP = "otp", "کد تأیید"
        TRANSACTIONAL = "transactional", "اطلاع‌رسانی"
        MARKETING = "marketing", "تبلیغاتی"

    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        CLAIMED = "CLAIMED", "در دستِ گوشی"
        SENT = "SENT", "فرستاده شد"
        DELIVERED = "DELIVERED", "تحویل شد"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"
        BLOCKED = "BLOCKED", "مسدود"

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    idempotency_key = models.CharField(max_length=120, unique=True, null=True, blank=True)
    to_number = models.CharField(max_length=20, db_index=True)
    to_raw = models.CharField(max_length=40, blank=True)
    body = models.TextField()
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.TRANSACTIONAL)
    campaign_ref = models.CharField(max_length=80, blank=True, db_index=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.QUEUED, db_index=True)
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="sms")
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=2)
    sim_slot = models.SmallIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    parts = models.PositiveSmallIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    not_before = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "پیامک"
        verbose_name_plural = "صفِ پیامک"
        ordering = ["-id"]
        indexes = [models.Index(fields=["state", "id"]), models.Index(fields=["device", "claimed_at"])]

    def __str__(self):
        return f"{self.to_number} [{self.state}]"


class SmsInbound(models.Model):
    device = models.ForeignKey(MobileDevice, on_delete=models.CASCADE, related_name="inbound")
    dedupe_key = models.CharField(max_length=80)
    from_number = models.CharField(max_length=20, db_index=True)
    body = models.TextField(blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    sim_slot = models.SmallIntegerField(null=True, blank=True)
    is_stop = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "پیامکِ دریافتی"
        verbose_name_plural = "پیامک‌های دریافتی"
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["device", "dedupe_key"], name="mobile_inbound_once")]


class MobileContact(models.Model):
    """Contacts the user explicitly chose to sync from the phone (used only for caller identification)."""

    device = models.ForeignKey(MobileDevice, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=200)
    number = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["device", "number"], name="mobile_contact_once")]


# ------------------------------------------------------------------ calls

class MobileCallConsent(TimeStampedModel):
    """Consent to record this person. NM's rule (same as «بازاریابی تلفنی»): no consent row, no stored recording."""

    class How(models.TextChoices):
        VERBAL = "verbal", "شفاهی، سر همان تماس و بعد از اعلام"
        WRITTEN = "written", "کتبی — پیام یا ایمیل"
        CONTRACT = "contract", "در قرارداد"

    number = models.CharField(max_length=20, unique=True)
    granted = models.BooleanField(default=False)
    how = models.CharField(max_length=10, choices=How.choices, default=How.VERBAL)
    obtained_how = models.CharField(max_length=300)
    obtained_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    declared_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "رضایتِ ضبطِ تماس (موبایل)"
        verbose_name_plural = "رضایت‌های ضبطِ تماس (موبایل)"

    @property
    def active(self) -> bool:
        return bool(self.granted and not self.revoked_at)


class MobileCall(TimeStampedModel):
    class Direction(models.TextChoices):
        IN = "in", "ورودی"
        OUT = "out", "خروجی"
        MISSED = "missed", "بی‌پاسخ"
        REJECTED = "rejected", "ردشده"

    class Status(models.TextChoices):
        LOGGED = "LOGGED", "ثبت شد"
        NO_CONSENT = "NO_CONSENT", "رضایت ثبت نشده"
        UPLOADED = "UPLOADED", "ضبط رسید"
        TRANSCRIBING = "TRANSCRIBING", "در حال تبدیل به متن"
        TRANSCRIBED = "TRANSCRIBED", "متن آماده شد"
        ANALYSED = "ANALYSED", "تحلیل شد"
        FAILED = "FAILED", "خطا"

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    client_id = models.CharField(max_length=80, blank=True)
    number_raw = models.CharField(max_length=40, blank=True)
    number = models.CharField(max_length=20, db_index=True)
    direction = models.CharField(max_length=10, choices=Direction.choices, default=Direction.IN)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    duration_s = models.PositiveIntegerField(default=0)
    contact_name = models.CharField(max_length=200, blank=True)
    caller_label = models.CharField(max_length=200, blank=True)
    live = models.BooleanField(default=False)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.LOGGED, db_index=True)
    audio_path = models.CharField(max_length=300, blank=True)
    audio_size = models.PositiveIntegerField(default=0)
    audio_mime = models.CharField(max_length=60, blank=True)
    audio_source = models.CharField(max_length=20, blank=True)
    transcript = models.TextField(blank=True)
    segments = models.JSONField(default=list, blank=True)
    asr_engine = models.CharField(max_length=12, blank=True)
    summary = models.TextField(blank=True)
    sentiment = models.CharField(max_length=8, blank=True)
    objections = models.JSONField(default=list, blank=True)
    commitments = models.JSONField(default=list, blank=True)
    next_steps = models.JSONField(default=list, blank=True)
    error = models.CharField(max_length=400, blank=True)

    class Meta:
        verbose_name = "تماس"
        verbose_name_plural = "تماس‌های موبایل"
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["device", "client_id"], condition=~Q(client_id=""), name="mobile_call_client_once")
        ]


# ------------------------------------------------------------------ products

class ProductPricing(TimeStampedModel):
    """Owner-editable inputs for the no-loss floor price. All optional; nothing is invented when empty."""

    product = models.OneToOneField("products.Product", on_delete=models.CASCADE, related_name="mobile_pricing")
    extra_unit_cost = models.DecimalField("هزینهٔ اضافهٔ هر عدد (بسته‌بندی، کارمزد، ارسال)", max_digits=14, decimal_places=2,
                                          null=True, blank=True)
    min_margin_percent = models.DecimalField("حداقل سودِ دلخواه (درصد از بهای تمام‌شده)", max_digits=6, decimal_places=2,
                                             null=True, blank=True)
    floor_price_override = models.DecimalField("کفِ قیمتِ دستی", max_digits=14, decimal_places=2, null=True, blank=True,
                                               help_text="اگر پر باشد، همین کفِ قیمت است.")
    note = models.CharField(max_length=300, blank=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "قیمتِ پایینِ محصول"
        verbose_name_plural = "قیمت‌های پایینِ محصولات"


# ------------------------------------------------------------------ messenger lookups

class LookupTicket(models.Model):
    """One authorization to look up ONE number on ONE platform. Single use, 10 minutes."""

    token = models.CharField(max_length=64, unique=True)
    device = models.ForeignKey(MobileDevice, on_delete=models.CASCADE, related_name="lookup_tickets")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    number = models.CharField(max_length=20, db_index=True)
    platform = models.CharField(max_length=12)
    trigger = models.CharField(max_length=8)  # call | manual
    call = models.ForeignKey(MobileCall, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    refresh = models.BooleanField(default=False)
    method = models.CharField(max_length=10, default="webview")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    refunded = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["device", "created_at"]), models.Index(fields=["platform", "created_at"])]


class ProfileLookup(models.Model):
    """One row per lookup (history, not just the latest). Only what a normal user of the platform sees."""

    class Status(models.TextChoices):
        FOUND = "found", "پیدا شد"
        NOT_FOUND = "not_found", "در این پیام‌رسان نیست"
        HIDDEN = "hidden", "پنهان/محدود"
        LOGIN_REQUIRED = "login_required", "ورود لازم است"
        ERROR = "error", "خطا"

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.CharField(max_length=20, db_index=True)
    platform = models.CharField(max_length=12, db_index=True)
    method = models.CharField(max_length=10, default="webview")
    status = models.CharField(max_length=14, choices=Status.choices)
    on_platform = models.BooleanField(null=True, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    username = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    deep_link_id = models.CharField(max_length=120, blank=True)
    avatar_path = models.CharField(max_length=300, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    field_sources = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=300, blank=True)
    looked_up_at = models.DateTimeField(default=timezone.now, db_index=True)
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    trigger = models.CharField(max_length=8, blank=True)
    call = models.ForeignKey(MobileCall, null=True, blank=True, on_delete=models.SET_NULL, related_name="profile_lookups")
    refresh = models.BooleanField(default=False)

    class Meta:
        verbose_name = "نتیجهٔ جستجوی پیام‌رسان"
        verbose_name_plural = "نتیجه‌های جستجوی پیام‌رسان"
        ordering = ["-looked_up_at", "-id"]
        indexes = [models.Index(fields=["number", "platform", "-looked_up_at"])]
