"""Abstract base for background jobs (CSV imports now, discovery / extraction later).

Not a table by itself: each module subclasses it and adds its own counters, so all
jobs share one vocabulary - queued / running / completed / failed / cancelled -
a progress figure, a resume cursor, a heartbeat and a cooperative cancel flag.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from . import conf


class BackgroundJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "در صف"
        RUNNING = "running", "در حال اجرا"
        COMPLETED = "completed", "تمام شد"
        FAILED = "failed", "ناموفق"
        CANCELLED = "cancelled", "لغو شد"

    FINISHED = (Status.COMPLETED, Status.FAILED, Status.CANCELLED)

    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.QUEUED, db_index=True)
    params = models.JSONField("تنظیمات", default=dict, blank=True)
    total_items = models.PositiveIntegerField("کلِ موردها", default=0)
    processed_items = models.PositiveIntegerField("پردازش‌شده", default=0)
    #: Number of the last item completely handled; a restarted job continues after it.
    cursor = models.PositiveIntegerField("نشانگرِ ادامه", default=0)
    attempts = models.PositiveSmallIntegerField("دفعاتِ اجرا", default=0)
    cancel_requested = models.BooleanField("درخواستِ لغو", default=False)
    error = models.TextField("خطا", blank=True)
    celery_task_id = models.CharField("شناسهٔ کارِ سلری", max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ساخته‌شده توسط"
    )
    queued_at = models.DateTimeField("زمانِ صف", default=timezone.now)
    started_at = models.DateTimeField("شروع", null=True, blank=True)
    finished_at = models.DateTimeField("پایان", null=True, blank=True)
    heartbeat_at = models.DateTimeField("آخرین نشانهٔ زنده بودن", null=True, blank=True)

    class Meta:
        abstract = True

    # ------------------------------------------------------------------ derived
    @property
    def is_finished(self) -> bool:
        return self.status in self.FINISHED

    @property
    def progress(self) -> int:
        """0-100. A finished job reads 100 even when it stopped early (the status says why)."""
        if self.status == self.Status.COMPLETED:
            return 100
        if not self.total_items:
            return 0
        return min(100, int(self.processed_items * 100 / self.total_items))

    @property
    def is_stalled(self) -> bool:
        """Running (or queued) but nothing has moved for a while: a worker restart or a dead broker."""
        limit = timedelta(seconds=conf.get("JOB_STALL_SECONDS"))
        now = timezone.now()
        if self.status == self.Status.RUNNING:
            return bool(self.heartbeat_at and now - self.heartbeat_at > limit)
        if self.status == self.Status.QUEUED:
            return now - self.queued_at > limit * 2
        return False

    # ------------------------------------------------------------------ transitions
    def mark_running(self) -> None:
        now = timezone.now()
        self.status = self.Status.RUNNING
        self.started_at = self.started_at or now
        self.heartbeat_at = now
        self.attempts += 1
        self.save(update_fields=["status", "started_at", "heartbeat_at", "attempts"])

    def mark_finished(self, status: str, error: str = "") -> None:
        self.status = status
        self.error = error[:2000]
        self.finished_at = timezone.now()
        self.heartbeat_at = self.finished_at
        self.save(update_fields=["status", "error", "finished_at", "heartbeat_at"])
