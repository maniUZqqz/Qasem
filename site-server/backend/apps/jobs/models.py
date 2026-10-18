from django.db import models

from apps.common.models import TimeStampedModel
from apps.stores.models import Store


class Job(TimeStampedModel):
    """Persistent record of every background AI/generation job."""

    class Type(models.TextChoices):
        PRODUCT_ANALYSIS = "product_analysis", "تحلیل محصول"
        MARKET_ANALYSIS = "market_analysis", "تحلیل بازار و رقبا"
        CAPTION_GENERATION = "caption_generation", "تولید کپشن"
        IMAGE_GENERATION = "image_generation", "تولید تصویر"
        VIDEO_GENERATION = "video_generation", "تولید ویدیو"
        VIDEO_SCRIPT = "video_script_generation", "تولید سناریوی ویدیو"
        VIDEO_SEGMENT = "video_segment_generation", "تولید پلان ویدیو"
        VIDEO_CONCAT = "video_concatenation", "چسباندن پلان‌ها"
        VOICE_GENERATION = "voice_generation", "تولید گویندگی"
        PUBLISHING = "publishing", "انتشار"
        EMBEDDING_BUILD = "embedding_build", "ساخت امبدینگ محصول"
        VIDEO_ANALYSIS = "video_analysis", "تحلیل ویدیوی آپلودشده"
        VIDEO_EDIT = "video_edit", "تدوین ویدیو"

    class State(models.TextChoices):
        """Where a job is. See `apps.jobs.machine` for the legal moves.

        `RUNNING` is kept because old rows use it. New generation jobs enter
        `PROCESSING` instead, because `RUNNING` cannot tell "the GPU is busy"
        apart from "the GPU is idle because we are waiting for a human" — and
        the whole point of incremental generation is that difference.
        """

        QUEUED = "QUEUED", "در صف"
        PROCESSING = "PROCESSING", "در حال پردازش"
        PREVIEW = "PREVIEW", "پیش‌نمایش آماده"
        WAITING_APPROVAL = "WAITING_APPROVAL", "منتظر تأیید"
        APPROVED = "APPROVED", "تأیید شد"
        RENDERING = "RENDERING", "در حال رندر نهایی"
        QC = "QC", "بررسی کیفیت"
        COMPLETED = "COMPLETED", "تمام شد"
        FAILED = "FAILED", "شکست خورد"
        CANCELLED = "CANCELLED", "لغو شد"
        RUNNING = "RUNNING", "در حال اجرا (قدیمی)"

    class Mode(models.TextChoices):
        """How much the job stops to ask.

        Safe is the default on purpose. A shop owner running their first video
        should discover a bad result after five seconds of GPU, not after forty.
        """

        SAFE = "SAFE", "محافظه‌کارانه — هر قطعه را تأیید کن"
        AUTO = "AUTO", "خودکار — فقط زیر آستانه‌ی کیفیت بایست"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="jobs")
    type = models.CharField(max_length=40, choices=Type.choices)
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    progress_step = models.PositiveIntegerField(default=0)
    total_steps = models.PositiveIntegerField(default=0)
    current_step_label = models.CharField(max_length=200, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    context = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    celery_task_id = models.CharField(max_length=64, blank=True)

    mode = models.CharField(max_length=6, choices=Mode.choices, default=Mode.SAFE)
    #: What the owner is being asked to look at while state is PREVIEW or
    #: WAITING_APPROVAL — a segment index, a file URL, a quality score.
    preview = models.JSONField(default=dict, blank=True)
    #: Set when a running task should stop at its next checkpoint. A Celery
    #: task cannot be killed reliably (certainly not on Windows), so the task
    #: asks rather than being told.
    cancel_requested = models.BooleanField(default=False)

    class Meta:
        verbose_name = "کار"
        verbose_name_plural = "کارها"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["state"]), models.Index(fields=["store", "created_at"])]

    def __str__(self):
        return f"{self.type} #{self.id} [{self.state}]"

    # ---- state machine ---------------------------------------------------

    def advance(self, target: str, *, label: str = "", preview: dict | None = None):
        """Move to `target`, refusing moves the machine does not allow.

        The refusal matters more than the move: a job that jumps from
        WAITING_APPROVAL to COMPLETED has charged for work nobody approved, and
        one that re-enters RENDERING has spent GPU minutes twice.
        """
        from . import machine

        machine.check(self.state, target)
        self.state = target
        fields = ["state", "updated_at"]
        if label:
            self.current_step_label = label
            fields.append("current_step_label")
        if preview is not None:
            self.preview = preview
            fields.append("preview")
        self.save(update_fields=fields)
        return self

    @property
    def awaiting_human(self) -> bool:
        """True while nothing will happen until someone answers."""
        from . import machine

        return self.state in machine.AWAITING_HUMAN

    @property
    def holds_hardware(self) -> bool:
        """True while our own GPU/CPU is occupied by this job.

        WAITING_APPROVAL is deliberately excluded: a job parked for a human is
        not holding a card, and counting it as if it were would idle the GPU
        for as long as the owner is at lunch.
        """
        from . import machine

        return self.state in machine.BUSY

    def request_cancel(self, reason: str = "") -> bool:
        """Ask a running task to stop at its next checkpoint.

        Returns False when there is nothing to stop. The flag is separate from
        the CANCELLED state because a task that is mid-render has to finish
        cleaning up — deleting half-written files, releasing the GPU, handing
        the credit back — and it can only do that if it is still alive to read
        the flag.
        """
        from . import machine

        if self.state in machine.TERMINAL:
            return False
        self.cancel_requested = True
        if reason:
            self.current_step_label = reason[:200]
        self.save(update_fields=["cancel_requested", "current_step_label", "updated_at"])
        return True

    def cancel_pending(self) -> bool:
        """Checkpoint call for a worker: should I stop now?"""
        return Job.objects.filter(pk=self.pk, cancel_requested=True).exists()

    def mark_running(self, label=""):
        """Legacy entry point, still used by the non-video tasks.

        New generation code calls `advance(State.PROCESSING)`; this stays so a
        caption task is not forced through a state machine it does not need.
        """
        self.state = self.State.RUNNING
        self.current_step_label = label
        # tasks set total_steps just before calling this — persist it too
        self.save(update_fields=["state", "current_step_label", "total_steps", "updated_at"])

    def mark_progress(self, step, label=""):
        self.progress_step = step
        if label:
            self.current_step_label = label
        self.save(update_fields=["progress_step", "current_step_label", "updated_at"])

    def mark_completed(self, result=None):
        self.state = self.State.COMPLETED
        self.result = result or {}
        self.current_step_label = ""
        self.save(update_fields=["state", "result", "current_step_label", "updated_at"])

    def mark_failed(self, error):
        self.state = self.State.FAILED
        self.error = str(error)[:4000]
        self.save(update_fields=["state", "error", "updated_at"])

    def mark_cancelled(self, reason: str = "توسط کاربر لغو شد."):
        """Terminal cancellation, after any cleanup the task had to do."""
        self.state = self.State.CANCELLED
        self.error = reason[:4000]
        self.current_step_label = ""
        self.save(update_fields=["state", "error", "current_step_label", "updated_at"])


# Measurements live in their own module for size; Django only discovers models
# imported from here.
from .metrics import RenderMetric  # noqa: E402,F401
