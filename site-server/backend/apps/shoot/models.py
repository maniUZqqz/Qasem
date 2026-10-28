"""فیلم‌برداری و عکاسیِ هدایت‌شده (پنل › محتوا، و دکمهٔ «عکس‌برداری با دوربین» در تعریفِ محصول).

یک «جلسه» (ShootSession) = یک محصول + برنامهٔ زاویه‌ها و نماها (plan). هر بار که صاحبِ فروشگاه یک زاویه یا نما را
می‌گیرد یک «برداشت» (ShootTake) ساخته و همان لحظه وارسی می‌شود (تاری، نور، محصول در کادر). خروجی‌ها (ShootOutput)
نسخه‌دارند: ویدیوی تبلیغاتی (ffmpeg روی سرورِ سایت) و پوستر (Pillow؛ حذفِ پس‌زمینه با سرورِ پردازش اگر روشن باشد).
فایل‌ها زیرِ MEDIA_ROOT/shoot/s<id>/ هستند و با حذفِ جلسه پاک می‌شوند.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class ShootSession(TimeStampedModel):
    class Purpose(models.TextChoices):
        PHOTOS = "photos", "عکس‌های محصول"
        AD = "ad", "محتوای تبلیغاتی (عکس + ویدیو)"

    class State(models.TextChoices):
        READY = "READY", "برنامه آماده"
        ANALYZING = "ANALYZING", "در حالِ تحلیلِ محصول"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="shoot_sessions")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="shoot_sessions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    purpose = models.CharField(max_length=8, choices=Purpose.choices, default=Purpose.AD)
    state = models.CharField(max_length=12, choices=State.choices, default=State.READY)
    #: برنامهٔ اعتبارسنجی‌شده (plan.validate_plan)
    plan = models.JSONField(default=dict, blank=True)
    #: ai | template | edited
    plan_source = models.CharField(max_length=12, blank=True)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    #: صدای راهنما: {"state": "RUNNING|READY|FAILED", "clips": {متن: آدرس}, "engine": ...}
    voice = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "جلسهٔ فیلم‌برداریِ هدایت‌شده"
        verbose_name_plural = "جلسه‌های فیلم‌برداریِ هدایت‌شده"
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.product_id} {self.purpose}"

    @property
    def dir_rel(self) -> str:
        return f"shoot/s{self.pk}"


class ShootTake(TimeStampedModel):
    class Kind(models.TextChoices):
        PHOTO = "photo", "عکس"
        VIDEO = "video", "ویدیو"

    session = models.ForeignKey(ShootSession, on_delete=models.CASCADE, related_name="takes")
    #: کلیدِ زاویه/نما در برنامه (p_front، v1، …)
    shot = models.CharField(max_length=40)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    #: نسبی به MEDIA_ROOT
    file = models.CharField(max_length=300)
    thumb = models.CharField(max_length=300, blank=True)
    preview = models.CharField(max_length=300, blank=True)
    mime = models.CharField(max_length=80, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    duration = models.FloatField(default=0)
    #: live | native | upload
    mode = models.CharField(max_length=12, blank=True)
    #: {"problems": [...], "metrics": {...}, "vision": {...}, "summary": "..."}
    checks = models.JSONField(default=dict, blank=True)
    #: وارسی را گذراند
    ok = models.BooleanField(default=False)
    #: کاربر (یا وارسی) پذیرفت؛ «بهترین برداشت» از میانِ پذیرفته‌ها انتخاب می‌شود
    accepted = models.BooleanField(default=False)
    score = models.FloatField(default=0)
    saved_image_id = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "برداشت"
        verbose_name_plural = "برداشت‌ها"
        ordering = ["created_at", "id"]


class ShootOutput(TimeStampedModel):
    class Kind(models.TextChoices):
        VIDEO = "video", "ویدیوی تبلیغاتی"
        POSTER = "poster", "پوسترِ تبلیغاتی"

    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حالِ ساخت"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"

    session = models.ForeignKey(ShootSession, on_delete=models.CASCADE, related_name="outputs")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    #: 9:16 | 1:1 | 4:5
    aspect = models.CharField(max_length=6, default="9:16")
    version = models.PositiveIntegerField(default=1)
    template = models.CharField(max_length=20, blank=True)
    options = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    progress = models.FloatField(default=0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    file = models.CharField(max_length=300, blank=True)
    thumb = models.CharField(max_length=300, blank=True)
    #: کجا و چطور ساخته شد (هر مرحله کجا اجرا شد، مدت، یادداشت‌ها)
    stats = models.JSONField(default=dict, blank=True)
    #: {"product_images": [...], "generated_images": [...], "uploaded_videos": [...]}
    saved = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "خروجیِ فیلم‌برداری"
        verbose_name_plural = "خروجی‌های فیلم‌برداری"
        ordering = ["-created_at", "-id"]
