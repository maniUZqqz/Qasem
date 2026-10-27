"""بازسازیِ یک تکه از وسطِ ویدیو: یک «جلسه» برای هر ویدیو، یک «نسخه» برای هر بار ساختن.

اصلِ ویدیو هرگز عوض نمی‌شود: جلسه یک کپیِ ثابت از آن نگه می‌دارد (hardlink — جای اضافه نمی‌گیرد). هر بار
ساختن نسخهٔ تازه‌ای است با پیش‌نمایش‌ها، نتیجهٔ کامل و نمرهٔ درز؛ کاربر یکی را «قبول» می‌کند و همان پایهٔ
ویرایش‌های بعدی (تکه‌های دیگر) می‌شود.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class RegenSession(TimeStampedModel):
    class State(models.TextChoices):
        PREPARING = "PREPARING", "در حال بررسیِ ویدیو"
        READY = "READY", "آماده"
        FAILED = "FAILED", "خطا"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="regen_sessions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    title = models.CharField("عنوان", max_length=200, blank=True)
    #: script | cut | upload | up3d | regen | file
    source_kind = models.CharField(max_length=16)
    source_ref = models.CharField(max_length=80, blank=True)
    #: کپیِ ثابتِ اصل، نسبی به MEDIA_ROOT
    original = models.CharField(max_length=400, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PREPARING)
    error = models.TextField(blank=True)
    #: ffprobe ِ اصل (بدونِ فهرستِ pts که کنارِ فایل در index.json است)
    info = models.JSONField(default=dict, blank=True)
    #: {"path": نوارِ کوچک‌نمایی (نسبی به MEDIA_ROOT), "frames": [شمارهٔ فریمِ هر خانه]}
    filmstrip = models.JSONField(default=dict, blank=True)
    #: نسخهٔ قبول‌شده — پایهٔ تکه‌های بعدی (خالی = اصل)
    current = models.ForeignKey("RegenVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "جلسهٔ بازسازیِ تکه"
        verbose_name_plural = "جلسه‌های بازسازیِ تکه"

    def __str__(self):
        return self.title or f"regen #{self.pk}"

    @property
    def dir_rel(self) -> str:
        return f"generated/regen/s{self.pk}"


class RegenVersion(TimeStampedModel):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        PREPARING = "PREPARING", "آماده‌سازی"
        GENERATING = "GENERATING", "ساختِ تکه روی سرورِ پردازش"
        STITCHING = "STITCHING", "چسباندن و وارسیِ درز"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"

    ACTIVE = ("QUEUED", "PREPARING", "GENERATING", "STITCHING")

    class Mode(models.TextChoices):
        PICTURE = "picture", "تصویرِ تازه (و اگر خواسته شد صدا)"
        AUDIO = "audio", "فقط صدای بازه"
        CUT = "cut", "حذفِ بازه (برش)"

    session = models.ForeignKey(RegenSession, on_delete=models.CASCADE, related_name="versions")
    #: picture = تکه با مدل دوباره ساخته می‌شود؛ audio = فقط صدای بازه عوض می‌شود (تصویر copy)؛ cut = بازه حذف
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.PICTURE)
    #: عملِ صدا روی بازه: {"op": keep|mute|volume|replace, "gain_db", "source": "upload:x"|"asset:12", "offset",
    #: "clip_gain_db", "mix": replace|mix, "bed_db", "fade_ms"} (برای cut خالی)
    audio = models.JSONField(default=dict, blank=True)
    number = models.PositiveIntegerField(default=1)
    #: ویدیوی ورودیِ این نسخه: خالی = اصل، وگرنه نتیجهٔ آن نسخهٔ قبول‌شده
    base = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    start_frame = models.PositiveIntegerField()
    end_frame = models.PositiveIntegerField()
    prompt = models.TextField("خواستهٔ کاربر", blank=True)
    model_prompt = models.TextField(blank=True)
    negative_prompt = models.TextField(blank=True)
    engine = models.CharField(max_length=20, default="wan22_flf")
    quality = models.CharField(max_length=8, default="480p")
    seed = models.BigIntegerField(default=1)
    #: ۱ = فقط فریمِ مرزی؛ ۵ = پنج فریم در هر سر («زمینهٔ حرکت»، آزمایشی)
    context = models.PositiveSmallIntegerField(default=1)
    #: چند فریم cross-blend در هر درز (خالی = خودکار، حدودِ ۰٫۱۲ ثانیه)
    blend = models.PositiveSmallIntegerField(null=True, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED, db_index=True)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    plan = models.JSONField(default=dict, blank=True)
    #: uid ِ کارِ apps.compute (comfy.graph)
    compute_job = models.CharField(max_length=40, blank=True)
    #: {نام: مسیرِ نسبی به MEDIA_ROOT} — result، piece، before، after، frame_before، frame_after
    files = models.JSONField(default=dict, blank=True)
    seams = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    usage_id = models.PositiveIntegerField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    discarded = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "نسخهٔ بازسازیِ تکه"
        verbose_name_plural = "نسخه‌های بازسازیِ تکه"
        constraints = [models.UniqueConstraint(fields=["session", "number"], name="regen_version_number")]

    def __str__(self):
        return f"{self.session} v{self.number} [{self.state}]"

    @property
    def dir_rel(self) -> str:
        return f"{self.session.dir_rel}/v{self.number}"

    @property
    def active(self) -> bool:
        return self.state in self.ACTIVE
