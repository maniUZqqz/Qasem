"""«چندزاویه»: هر بار ساختن یک «اجرا» (MultiAngleRun) است — یا چند زاویهٔ مجازی از یک فیلم، یا یک حرکتِ دوربینِ ۲٫۵بعدی، یا آزمونِ خودکارِ سرورِ پردازش.

کارِ سنگین روی سرورِ پردازش (GPU) انجام می‌شود؛ این‌جا فقط وضعیت و نتیجه نگه داشته می‌شود. فایل‌های نتیجه در
`<MEDIA_ROOT>/generated/multiangle/run<id>/` می‌مانند و هر زاویه یک «ویدیوی آپلودشده» (UploadedVideo) هم می‌شود تا در سطلِ رسانهٔ ادیتور باشد.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class MultiAngleRun(TimeStampedModel):
    class Mode(models.TextChoices):
        VIRTUAL = "virtual", "زاویه‌های مجازی"
        MOVE = "move25d", "حرکتِ دوربینِ ۲٫۵بعدی"
        SELFTEST = "selftest", "آزمونِ خودکار"

    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حال ساخت"
        INGEST = "INGEST", "آوردنِ نتیجه به سایت"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"

    ACTIVE = ("QUEUED", "RUNNING", "INGEST")

    #: آزمونِ خودکار فروشگاه ندارد
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.CASCADE, related_name="multiangle_runs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.VIRTUAL)
    state = models.CharField(max_length=10, choices=State.choices, default=State.QUEUED)
    title = models.CharField("عنوان", max_length=200, blank=True)
    #: مرجعِ ورودی در ادیتور: video:12 / edited:12 / script:7 / photo:3 / pimg:9
    source_ref = models.CharField(max_length=40, blank=True)
    #: انتخاب‌های کاربر (پاک‌سازی‌شده)
    params = models.JSONField(default=dict, blank=True)
    #: uid ِ کارِ سرورِ پردازش (ComputeJob)
    job_uid = models.CharField(max_length=40, blank=True, db_index=True)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    #: خروجیِ موتور (plan.json): زاویه‌ها، برش‌ها، هشدارها، دستگاه
    plan = models.JSONField(default=dict, blank=True)
    #: {"angles": {key: {"rel", "preview", "upload"}}, "multicam": {...}, "move": {...}} — مسیرها نسبی به MEDIA_ROOT
    files = models.JSONField(default=dict, blank=True)
    #: متنِ فارسیِ هشدارها
    warnings = models.JSONField(default=list, blank=True)
    #: پروژهٔ ادیتور (VideoProject) که از این اجرا ساخته شد
    project_id = models.PositiveBigIntegerField(null=True, blank=True)
    #: آزمونِ خودکار: [{name, ok, detail}]
    checks = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "اجرای چندزاویه"
        verbose_name_plural = "اجراهای چندزاویه"

    def __str__(self):
        return self.title or f"multiangle #{self.pk}"

    @property
    def active(self) -> bool:
        return self.state in self.ACTIVE

    @property
    def dir_rel(self) -> str:
        return f"generated/multiangle/run{self.pk}"
