"""«استودیوی موشن»: تاریخچهٔ رندرها و دارایی‌های بارگذاری‌شده (لوگو، عکسِ محصول، اسکرین‌شات).

ویدیوی تمام‌شده به‌صورتِ یک «ویدیوی فروشگاه» (apps.content.UploadedVideo) ثبت می‌شود تا در سطلِ رسانهٔ ادیتورِ ویدیو دیده شود؛
اینجا فقط شناسه‌اش (video_id) نگه‌داشته می‌شود تا وابستگیِ مهاجرتی به اپِ محتوا نباشد.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class MotionAsset(TimeStampedModel):
    """عکسی که کاربر برای ویدیوی موشن بارگذاری کرده (لوگو، محصول، اسکرین‌شاتِ اپ)؛ کوچک‌شده روی دیسک."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="motion_assets")
    title = models.CharField(max_length=200, blank=True)
    #: مسیر نسبت به MEDIA_ROOT
    path = models.CharField(max_length=400)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    has_alpha = models.BooleanField(default=False)
    sha1 = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"motion asset {self.pk}"


class MotionRender(TimeStampedModel):
    class Mode(models.TextChoices):
        TEMPLATE = "template", "قالبی"
        AI = "ai", "با هوش مصنوعی"
        CODE = "code", "کد (Remotion)"

    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        WAITING_NODE = "WAITING_NODE", "منتظرِ سرورِ پردازش"
        RENDERING = "RENDERING", "در حال رندر"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"

    class Target(models.TextChoices):
        NODE = "node", "سرورِ پردازش (GPU)"
        SITE = "site", "سایت (محدود)"

    ACTIVE = ("QUEUED", "WAITING_NODE", "RENDERING")

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="motion_renders")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TEMPLATE)
    title = models.CharField(max_length=200, blank=True)
    style = models.CharField(max_length=60, blank=True)
    aspect = models.CharField(max_length=6, default="9:16")
    #: پارامترهای ترکیب (حالتِ قالبی و هوش مصنوعی)
    spec = models.JSONField(default=dict, blank=True)
    #: کدِ TSX ِ کاربر (حالتِ کد)
    code = models.TextField(blank=True)
    #: {"quality": "540", "target": "node"|"site", "fps": 30}
    options = models.JSONField(default=dict, blank=True)
    target = models.CharField(max_length=6, choices=Target.choices, default=Target.NODE)
    state = models.CharField(max_length=14, choices=State.choices, default=State.QUEUED, db_index=True)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    #: شناسهٔ کارِ صفِ پردازش (ComputeJob.uid) وقتی روی گره می‌رود
    job_uid = models.CharField(max_length=40, blank=True, db_index=True)
    duration_s = models.FloatField(default=0.0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    fps = models.PositiveSmallIntegerField(default=0)
    bytes = models.PositiveBigIntegerField(default=0)
    render_s = models.FloatField(default=0.0)
    #: «ویدیوی فروشگاه» ِ ساخته‌شده (apps.content.UploadedVideo.pk)
    video_id = models.PositiveBigIntegerField(null=True, blank=True)
    #: مسیرِ تصویرِ بندانگشتیِ ویدیو نسبت به MEDIA_ROOT
    poster = models.CharField(max_length=400, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "-created_at"])]

    def __str__(self):
        return f"{self.title or self.style} #{self.pk} [{self.state}]"
