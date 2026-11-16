"""استودیوی طراحی: سندها (کاتالوگ، ارائه، طراحیِ UI)، خروجی‌های ساخته‌شده و نظرها.

سند = یک JSON (``data``) با ``rev`` برای ذخیرهٔ هم‌زمان؛ هندسه هیچ‌جا ذخیره نمی‌شود و هر بار از ``data`` ساخته می‌شود (پس پیش‌نمایش و خروجی یکی‌اند).
فایل‌های خروجی در ``NM_DATA_DIR/design/`` می‌مانند (عمومی نیستند؛ فقط با دانلودِ احرازشده).
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class DesignDoc(TimeStampedModel):
    class Kind(models.TextChoices):
        CATALOG = "catalog", "کاتالوگ"
        DECK = "deck", "ارائه"
        UI = "ui", "طراحی UI/UX"

    class Source(models.TextChoices):
        MANUAL = "manual", "دستی"
        RULES = "rules", "پیش‌نویسِ قاعده‌ای"
        AI = "ai", "پیش‌نویسِ هوش مصنوعی"
        SAMPLE = "sample", "نمونهٔ آماده"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="design_docs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True)
    title = models.CharField("عنوان", max_length=160, blank=True)
    data = models.JSONField(default=dict, blank=True)
    rev = models.PositiveIntegerField(default=1)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    #: {"ai": {...}، "site": {project_id، slug...}، "video": {render_id...}، "notes": [...]}
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "سندِ طراحی"
        verbose_name_plural = "سندهای طراحی"
        indexes = [models.Index(fields=["store", "kind", "-updated_at"])]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.title or self.pk}"

    @property
    def dir_rel(self) -> str:
        return f"design/s{self.store_id}/d{self.pk}"


class DesignExport(TimeStampedModel):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حالِ ساخت"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"

    ACTIVE = ("QUEUED", "RUNNING")

    doc = models.ForeignKey(DesignDoc, on_delete=models.CASCADE, related_name="exports")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    #: print_pdf | screen_pdf | png_zip | jpg_zip | pptx | ppsx | svg_zip | pack_printer | pack_social | pack_source | pack_customer | pack_meeting | pack_kiosk | pack_dev | tokens
    kind = models.CharField(max_length=24)
    params = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED, db_index=True)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    file = models.CharField(max_length=400, blank=True)
    filename = models.CharField(max_length=160, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    #: گزارشِ ساخت (اندازهٔ صفحه، خونریزی، dpi، تعدادِ صفحه…) و چک‌لیست
    info = models.JSONField(default=dict, blank=True)
    doc_rev = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "خروجیِ طراحی"
        verbose_name_plural = "خروجی‌های طراحی"

    def __str__(self):
        return f"{self.kind} #{self.pk} [{self.state}]"

    @property
    def active(self) -> bool:
        return self.state in self.ACTIVE


class DesignComment(TimeStampedModel):
    """نظر روی یک فریم (و جای دقیق روی آن) — برای بازبینیِ طرح پیش از سایت‌ساز."""

    doc = models.ForeignKey(DesignDoc, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    author_name = models.CharField(max_length=80, blank=True)
    frame_id = models.CharField(max_length=40, db_index=True)
    node_id = models.CharField(max_length=40, blank=True)
    #: جای نظر روی فریم، کسری از پهنا و بلندیِ فریم (۰..۱)
    x = models.FloatField(default=0.0)
    y = models.FloatField(default=0.0)
    text = models.TextField()
    resolved = models.BooleanField(default=False)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "نظرِ طراحی"
        verbose_name_plural = "نظرهای طراحی"
