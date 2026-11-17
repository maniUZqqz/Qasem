# -*- coding: utf-8 -*-
"""«تصویر به کد»: هر تبدیل یک ردیفِ ``Conversion`` است (تاریخچهٔ هر فروشگاه). فایل‌ها در ``<NM_DATA_DIR>/img2code/conv<id>/`` می‌مانند، نه در پوشهٔ وب؛
همه از راهِ APIِ احرازشده داده می‌شوند (عکسِ صفحهٔ مشتری عمومی نمی‌شود)."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class Conversion(TimeStampedModel):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حال تبدیل"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"

    ACTIVE = ("QUEUED", "RUNNING")

    class Source(models.TextChoices):
        UPLOAD = "upload", "تصویرِ بارگذاری‌شده"
        URL = "url", "نشانیِ صفحه"

    class Mode(models.TextChoices):
        EXACT = "exact", "دقیق"
        RESPONSIVE = "responsive", "واکنش‌گرا"

    class Lang(models.TextChoices):
        AUTO = "auto", "خودکار"
        FA = "fa", "فارسی"
        EN = "en", "انگلیسی"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="img2code_conversions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField("عنوان", max_length=160, blank=True)
    source_kind = models.CharField(max_length=8, choices=Source.choices, default=Source.UPLOAD)
    source_url = models.CharField(max_length=500, blank=True)
    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.RESPONSIVE)
    lang = models.CharField(max_length=4, choices=Lang.choices, default=Lang.AUTO)
    #: پهنای مرورگر برای عکس گرفتن از نشانی (پیکسل)
    width = models.PositiveIntegerField(default=1280)
    #: متنِ صفحه از DOM خوانده شود (دقیق) نه OCR؛ فقط برای نشانی
    dom_text = models.BooleanField(default=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.QUEUED)
    step = models.CharField(max_length=20, blank=True)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    size_w = models.PositiveIntegerField(default=0)
    size_h = models.PositiveIntegerField(default=0)
    #: [{key,label,value,display,verdict,hint}] به فارسی؛ و عددهای خام
    scores = models.JSONField(default=list, blank=True)
    raw_scores = models.JSONField(default=dict, blank=True)
    report = models.JSONField(default=dict, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    #: خروجیِ «ساختِ صفحه در سایت‌ساز»
    draft_project_slug = models.CharField(max_length=120, blank=True)
    draft_page_id = models.PositiveIntegerField(null=True, blank=True)
    draft_at = models.DateTimeField(null=True, blank=True)
    #: خروجیِ «باز کردن در طراحیِ UI» (سندِ UI/UX در استودیوی طراحی)
    ui_doc_id = models.PositiveIntegerField(null=True, blank=True)
    ui_doc_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "تبدیلِ تصویر به کد"
        verbose_name_plural = "تبدیل‌های تصویر به کد"
        indexes = [models.Index(fields=["store", "-created_at"])]

    def __str__(self):
        return self.title or "تبدیل #%s" % self.pk

    @property
    def active(self) -> bool:
        return self.state in self.ACTIVE

    @property
    def dir(self) -> Path:
        return Path(settings.NM_DATA_DIR) / "img2code" / ("conv%d" % self.pk)

    @property
    def out_dir(self) -> Path:
        return self.dir / "out"
