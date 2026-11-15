"""ماسکوتِ برند (پنل › فروشگاه › محتوا): یک شخصیتِ کارتونیِ ثابت که با کد کشیده می‌شود؛ در همهٔ پست‌ها، استوری‌ها و تامنیل‌ها دقیقاً یکی است.

``Mascot.spec`` هویتِ شخصیت است (رنگ‌ها، سر، کلاه، شال، وسیله، لوگوی روی سینه)؛ همان spec همیشه همان شخصیت را می‌کشد (بدونِ GPU و بدونِ هوش مصنوعی).
«قفل» یعنی مالک ظاهر را تأیید کرده: ``version`` بالا می‌رود و تا باز کردنِ قفل spec عوض نمی‌شود؛ نسخه در کلیدِ هر رندر هست، پس با نسخهٔ تازه
فقط تصویرهای تازه ساخته می‌شود. هر خروجی (پست، استیکر، برگهٔ مدل) یک «عکسِ کتابخانهٔ ادیتورِ عکس» (``PhotoAsset``) هم هست: تامنیل‌ساز، ادیتور و موشن
(``photo:<id>``) مستقیم از آن برمی‌دارند.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class Mascot(TimeStampedModel):
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="mascots")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField("نام", max_length=80)
    #: کلیدِ نقشِ آماده (engine/brand.py: coach، shopkeeper، cook، courier، advisor)
    role = models.CharField(max_length=16, default="coach")
    #: مشخصاتِ کاملِ شخصیت (engine/spec.normalize)
    spec = models.JSONField(default=dict, blank=True)
    #: رنگ‌های برندِ این ماسکوت برای پس‌زمینه و کپشن [اصلی، دوم]؛ خالی = رنگ‌های زندهٔ برندِ فروشگاه
    brand_colours = models.JSONField(default=list, blank=True)
    #: ۰ = هنوز قفل نشده؛ با هر «تأییدِ ظاهر» یکی بالا می‌رود
    version = models.PositiveIntegerField(default=0)
    locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    #: آخرین «بررسیِ ثبات»: {at, ok, passed, total, version, failed[]}
    last_check = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "ماسکوت"
        verbose_name_plural = "ماسکوت‌ها"

    def __str__(self):
        return self.name or f"mascot #{self.pk}"


class MascotRender(TimeStampedModel):
    """یک خروجیِ ساخته‌شده؛ کَش با کلیدِ ``key`` (هشِ spec + نسخه + گزینه‌ها + رنگ‌ها + لوگو). تصویر در ``asset`` (کتابخانهٔ ادیتورِ عکس) است."""

    class Kind(models.TextChoices):
        SHOT = "shot", "پست یا استوری"
        STICKER = "sticker", "استیکرِ شفاف"
        SHEET = "sheet", "برگهٔ مدل"

    mascot = models.ForeignKey(Mascot, on_delete=models.CASCADE, related_name="renders")
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="mascot_renders")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.SHOT)
    key = models.CharField(max_length=40, db_index=True)
    spec_hash = models.CharField(max_length=16, blank=True)
    #: نسخهٔ ماسکوت هنگامِ ساخت و قفل‌بودنش
    version = models.PositiveIntegerField(default=0)
    locked = models.BooleanField(default=False)
    #: گزینه‌های ساخت (اندازه، ژست، حالت، پس‌زمینه، متن‌ها ...)
    params = models.JSONField(default=dict, blank=True)
    #: بررسیِ رنگ‌های امضا (engine/qa.check_figure)
    qa = models.JSONField(default=dict, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    asset = models.ForeignKey("photoedit.PhotoAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        unique_together = [("mascot", "key")]
        verbose_name = "خروجیِ ماسکوت"
        verbose_name_plural = "خروجی‌های ماسکوت"

    def __str__(self):
        return f"{self.mascot_id}:{self.kind}:{self.key[:8]}"
