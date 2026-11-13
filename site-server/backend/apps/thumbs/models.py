"""تامنیل‌ساز (پنل › فروشگاه › محتوا): تامنیل‌ها و کاورهای ساخته‌شده + تاریخچهٔ ایده‌ها.

هر ``Thumbnail`` یک خروجیِ کامل است (PNG + JPG + بندانگشتی) با ``spec`` ِ کاملِ سازنده؛ هر وقت بخواهید همان spec دوباره (با تغییر) ساخته
می‌شود. «پس‌زمینهٔ هوش مصنوعی» روی گرهٔ GPU ساخته می‌شود؛ تا آماده شدنش تامنیل با یک پس‌زمینهٔ موقت دیده می‌شود
(``WAITING_BG``) و خودش بعد از رسیدنِ تصویر کامل می‌شود. فایل‌ها زیرِ ``MEDIA_ROOT/thumbs/s<فروشگاه>/t<شماره>/`` اند.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class Thumbnail(TimeStampedModel):
    class State(models.TextChoices):
        READY = "READY", "آماده"
        WAITING_BG = "WAITING_BG", "منتظرِ پس‌زمینهٔ هوش مصنوعی"
        FAILED = "FAILED", "ناموفق"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="thumbnails")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField("عنوان", max_length=200, blank=True)
    format = models.CharField(max_length=24)
    style = models.CharField(max_length=32)
    #: نسخه‌هایی که با یک «بساز» (A/B) آمده‌اند
    batch = models.CharField(max_length=32, blank=True, db_index=True)
    variant = models.CharField(max_length=2, blank=True)
    variant_note = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.READY, db_index=True)
    #: مشخصاتِ کاملِ ساخت (render.clean_spec)
    spec = models.JSONField(default=dict, blank=True)
    #: {"png", "jpg", "thumb"} ⇐ مسیرِ نسبی به MEDIA_ROOT
    files = models.JSONField(default=dict, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    size_bytes = models.PositiveIntegerField(default=0)
    #: {"warnings": [...], "layers": [{name, kind, bbox}], "texts": [...], "palette": {...}, "ai": {...}}
    notes = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=300, blank=True)
    #: کارِ ComfyUI ِ پس‌زمینه (uid)
    bg_job = models.CharField(max_length=40, blank=True)
    #: کپیِ «باز شده در ادیتور عکس» (کتابخانهٔ ادیتور)
    asset = models.ForeignKey("photoedit.PhotoAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "تامنیل"
        verbose_name_plural = "تامنیل‌ها"

    def __str__(self):
        return self.title or f"thumb #{self.pk}"

    @property
    def dir_rel(self) -> str:
        return f"thumbs/s{self.store_id}/t{self.pk}"


class IdeaSet(TimeStampedModel):
    """یک بار «ایده بده»: موضوع، منبع (هوش مصنوعی/فرمول‌های آماده) و ایده‌ها — برای تاریخچه و بی‌هزینه دوباره‌دیدن."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="thumb_idea_sets")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    product = models.ForeignKey("products.Product", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    topic = models.CharField(max_length=300)
    format = models.CharField(max_length=24, blank=True)
    via = models.CharField(max_length=8, default="rules")        # ai | rules | mixed
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "مجموعهٔ ایده"
        verbose_name_plural = "مجموعه‌های ایده"

    def __str__(self):
        return self.topic[:60]
