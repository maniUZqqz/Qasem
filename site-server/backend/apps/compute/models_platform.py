"""مدل‌های «پلتفرمِ گره» (۱۴۰۵/۰۸/۲۱): آزمونِ خودکار، به‌روزرسانیِ خودکار و زمان‌بندیِ عادلانهٔ صف.

  NodeAuto        حالتِ خودکارِ هر گره: آخرین نسخهٔ دیده‌شده، شمارندهٔ به‌روزرسانیِ خودکار، شمارندهٔ نوبت‌دهی
  SelfTestRun     یک اجرای کاملِ آزمون روی یک گره (با نسخهٔ عامل، علتِ اجرا و شمارش‌ها)
  SelfTestResult  نتیجهٔ یک آزمون (وضعیت، جزئیات، دستگاهِ به‌کاررفته، ثانیه، خروجی‌های قابلِ‌دیدن)
  RequeueRecord   کاری که پس از قبولیِ یک آزمون خودکار دوباره به صف برگشت (برای حلقه نشدن)
"""
from django.db import models

from apps.common.models import TimeStampedModel


class NodeAuto(models.Model):
    node = models.OneToOneField("compute.ComputeNode", on_delete=models.CASCADE, related_name="auto")
    #: «نسخهٔ عامل | شناسهٔ کد» ِ آخرینی که برایش آزمون ساخته شد
    last_selftest_key = models.CharField(max_length=120, blank=True)
    #: تاریخِ (تهران، YYYY-MM-DD) آخرین آزمونِ شبانه
    last_nightly = models.CharField(max_length=10, blank=True)
    #: شناسهٔ بستهٔ کدی که برایش به‌روزرسانیِ خودکار فرستاده شد و چند بار
    update_pkg = models.CharField(max_length=64, blank=True)
    update_tries = models.PositiveSmallIntegerField(default=0)
    update_last_at = models.DateTimeField(null=True, blank=True)
    update_note = models.CharField(max_length=300, blank=True)
    #: زمان‌بندیِ صف: چند کارِ کوتاه پشتِ هم از آخرین کارِ بلند گرفته شد، و موتورِ آخرین کار
    short_streak = models.PositiveSmallIntegerField(default=0)
    last_engine = models.CharField(max_length=20, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "حالتِ خودکارِ گره"
        verbose_name_plural = "حالتِ خودکارِ گره‌ها"

    def __str__(self):
        return f"auto({self.node_id})"

    @classmethod
    def of(cls, node):
        obj, _ = cls.objects.get_or_create(node=node)
        return obj


class SelfTestRun(TimeStampedModel):
    class State(models.TextChoices):
        RUNNING = "RUNNING", "در حال اجرا"
        FINISHED = "FINISHED", "تمام شد"
        ABORTED = "ABORTED", "متوقف شد"

    node = models.ForeignKey("compute.ComputeNode", on_delete=models.CASCADE, related_name="selftest_runs")
    #: version = پس از نسخهٔ تازهٔ عامل · nightly = شبانه · manual = دکمهٔ «آزمونِ کامل» · deep = با آزمون‌های سنگین
    trigger = models.CharField(max_length=12, default="manual")
    state = models.CharField(max_length=10, choices=State.choices, default=State.RUNNING, db_index=True)
    agent_version = models.CharField(max_length=20, blank=True)
    code_id = models.CharField(max_length=40, blank=True)
    by = models.CharField(max_length=60, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    #: برای هر آزمون که قبول شد، کارهای قبلاً ناموفقِ همان قابلیت دوباره به صف رفتند؟
    requeued = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "اجرای آزمونِ خودکار"
        verbose_name_plural = "اجراهای آزمونِ خودکار"
        ordering = ["-created_at"]

    def __str__(self):
        return f"selftest#{self.pk} {self.trigger} [{self.state}]"


class SelfTestResult(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING", "منتظرِ آزمونِ پیش‌نیاز"
        WAITING = "WAITING", "منتظرِ نصب"
        QUEUED = "QUEUED", "در صف"
        RUNNING = "RUNNING", "در حال اجرا"
        PASSED = "PASSED", "قبول"
        FAILED = "FAILED", "رد"
        SKIPPED = "SKIPPED", "ردشده (اجرا نشد)"

    FINAL = ("PASSED", "FAILED", "SKIPPED")

    run = models.ForeignKey(SelfTestRun, on_delete=models.CASCADE, related_name="results")
    key = models.CharField(max_length=40, db_index=True)
    label = models.CharField(max_length=120)
    group = models.CharField(max_length=20, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    optional = models.BooleanField(default=False)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING, db_index=True)
    job_uid = models.UUIDField(null=True, blank=True)
    detail = models.TextField(blank=True)
    device = models.CharField(max_length=12, blank=True)
    warning = models.CharField(max_length=300, blank=True)
    seconds = models.FloatField(null=True, blank=True)
    #: [{"name", "media", "url"}]
    artifacts = models.JSONField(default=list, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["run_id", "order"]
        unique_together = [("run", "key")]

    def __str__(self):
        return f"{self.key} [{self.state}]"

    @property
    def final(self) -> bool:
        return self.state in self.FINAL


class RequeueRecord(models.Model):
    job_uid = models.UUIDField(db_index=True)
    run = models.ForeignKey(SelfTestRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    key = models.CharField(max_length=40, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]
