"""برنامهٔ بازاریابیِ فروشگاه + گزارشِ ایرادِ آزمون.

سه جدول:

* ``MarketingPlan``  — یک برنامهٔ دو‌هفته‌ای برای یک فروشگاه (تاریخِ شروع، هدف، خلاصهٔ واقعیت‌ها، گزارشِ آخرین اجرا).
* ``PlanItem``       — یک کارِ برنامه (روزِ n، نوع، بخشِ پنل که آن را می‌سازد، پیش‌نویس، پیوند به چیزهای ساخته‌شده).
* ``BugReport``      — «گزارشِ ایراد» که مالک هنگامِ آزمونِ بخش‌ها می‌فرستد (بخش، نشانی، یادداشت، عکس).

اصلِ طراحی (همان اصلِ تختهٔ کمپین): **وضعیتِ یک کار نسخهٔ دومِ حقیقت نیست.** کاری که پشتش یک رندرِ موشن، یک کارِ صفِ پردازش یا
یک ردیفِ کمپین است، وضعیتش را از همان‌ها می‌خواند (``runner.sync_plan``)؛ فقط «تصمیمِ مالک» (تأیید / انجام شد / رد) در خودِ ردیف می‌ماند.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models

from apps.common.models import TimeStampedModel
from apps.stores.models import Store


class MarketingPlan(TimeStampedModel):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="marketing_plans")
    #: چند برنامه برای یک فروشگاه ممکن است؛ کلیدِ پیش‌فرض «starter» است (برنامهٔ دو‌هفتهٔ آغازین).
    key = models.CharField(max_length=40, default="starter")
    name = models.CharField(max_length=200)
    goal = models.TextField(blank=True)
    start_date = models.DateField()
    days = models.PositiveSmallIntegerField(default=14)
    #: واقعیت‌هایی که برنامه از آن‌ها ساخته شد + ستون‌های ستون‌بندی (برای نمایش «این برنامه از چه ساخته شد»)
    summary = models.JSONField(default=dict, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    #: {"at", "by", "log": [..], "running": bool, "counts": {...}}
    last_run = models.JSONField(default=dict, blank=True)
    #: قفلِ «یک اجرا در هر لحظه»؛ اجرایی که بیش از ۲۰ دقیقه گیر کرده باشد قفلش نادیده گرفته می‌شود
    running_since = models.DateTimeField(null=True, blank=True)
    #: تیکِ پس‌زمینه (هر ۱۰ دقیقه) وضعیت‌ها را همگام می‌کند و کارهای منتظرِ هوش مصنوعی/سرورِ پردازش را پیش می‌برد
    autorun = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "برنامهٔ بازاریابی"
        verbose_name_plural = "برنامه‌های بازاریابی"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["store", "key"], name="mktplan_one_plan_per_key")]

    def __str__(self):
        return f"{self.name} ({self.store_id})"


class PlanItem(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "برنامه‌ریزی شد"
        DRAFTED = "DRAFTED", "پیش‌نویس آماده"
        WAITING_NODE = "WAITING_NODE", "منتظرِ روشن‌شدنِ سرورِ پردازش"
        RUNNING = "RUNNING", "در حالِ ساخت"
        READY = "READY", "آماده برای تأیید"
        NEEDS_YOU = "NEEDS_YOU", "نیازمندِ شما"
        FAILED = "FAILED", "ناموفق"

    class Decision(models.TextChoices):
        NONE = "", "—"
        APPROVED = "approved", "تأیید شد"
        DONE = "done", "منتشر / انجام شد"
        SKIPPED = "skipped", "رد شد"

    plan = models.ForeignKey(MarketingPlan, on_delete=models.CASCADE, related_name="items")
    #: کلیدِ یکتا در برنامه («d03.reel.1»)؛ اجرای دوباره همان ردیف را به‌روز می‌کند، ردیفِ تازه نمی‌سازد
    key = models.CharField(max_length=60)
    day = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=24)
    #: کلیدِ صفحهٔ پنل که این کار را می‌سازد (از ``apps.panel.registry``)
    section = models.CharField(max_length=40, blank=True)
    title = models.CharField(max_length=240)
    brief = models.TextField(blank=True)
    draft = models.TextField(blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.PLANNED)
    decision = models.CharField(max_length=10, choices=Decision.choices, blank=True, default="")
    needs_node = models.BooleanField(default=False)
    #: پولیشِ متن با هوش مصنوعی هنوز نشده و منتظرِ سرورِ پردازش/متیس است
    ai_wait = models.BooleanField(default=False)
    #: [{"type": "campaign_task", "id": 35, "label": "...", "url": "/stores/34/campaigns"}, ...]
    refs = models.JSONField(default=list, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=300, blank=True)
    last_error = models.TextField(blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "کارِ برنامه"
        verbose_name_plural = "کارهای برنامه"
        ordering = ["day", "order", "id"]
        constraints = [models.UniqueConstraint(fields=["plan", "key"], name="mktplan_item_key")]
        indexes = [models.Index(fields=["plan", "status"])]

    def __str__(self):
        return f"{self.key} · {self.title}"


class BugReport(TimeStampedModel):
    class State(models.TextChoices):
        NEW = "new", "جدید"
        SEEN = "seen", "دیده شد"
        FIXED = "fixed", "رفع شد"
        WONTFIX = "wontfix", "رفع نمی‌شود"

    store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="bug_reports")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    #: کلیدِ بخش (از ``apps.mktplan.guide``، مثلاً «motion»)؛ «other» اگر نامشخص بود
    section = models.CharField(max_length=60, blank=True)
    section_title = models.CharField(max_length=160, blank=True)
    page_url = models.CharField(max_length=500, blank=True)
    note = models.TextField()
    screenshot = models.FileField(upload_to="bug-reports/%Y%m/", blank=True, null=True)
    #: مرورگر، اندازهٔ صفحه، نسخهٔ نرم‌افزار، آخرین خطاهای API و جاوااسکریپت
    context = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.NEW)
    response = models.TextField(blank=True)

    class Meta:
        verbose_name = "گزارشِ ایراد"
        verbose_name_plural = "گزارش‌های ایراد"
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.section}: {self.note[:40]}"
