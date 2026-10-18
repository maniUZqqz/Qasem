"""Campaign as a task manager. §29.1 of `ایده‌ها پنل.md`.

§29.1 draws the shape:

    Campaign
    ├── Marketing Tasks
    ├── Advertising Tasks
    ├── Content Tasks
    ├── Sales Tasks
    └── Other Business Tasks

and says the page must cover «از ایده و برنامه‌ریزی تا اجرای فعالیت‌ها».

**The decision that matters: a content task is not a copy of a job.** A task
that says "make the video" and a `Job` that is actually rendering it are the
same piece of work, and two rows for one thing drift apart within a day — the
job finishes, the task still says "in progress", and the shop stops believing
the board. So a task can *point at* a job, and when it does, its state is read
from that job rather than stored. The only tasks with a state of their own are
the ones nothing else is tracking: «با عکاس تماس بگیر», «بودجه را تأیید کن».

**Nothing here does the work.** A task manager that silently started renders
would spend a shop's allowance on rows they were still planning with.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class CampaignTask(TimeStampedModel):
    """One thing that has to happen for this campaign."""

    class Kind(models.TextChoices):
        MARKETING = "MARKETING", "بازاریابی"
        ADVERTISING = "ADVERTISING", "تبلیغات"
        CONTENT = "CONTENT", "محتوا"
        SALES = "SALES", "فروش"
        OTHER = "OTHER", "سایر"

    class State(models.TextChoices):
        TODO = "TODO", "انجام نشده"
        DOING = "DOING", "در حال انجام"
        BLOCKED = "BLOCKED", "گیر کرده"
        DONE = "DONE", "انجام شد"
        DROPPED = "DROPPED", "لغو شد"

    class Priority(models.IntegerChoices):
        LOW = 1, "کم"
        NORMAL = 2, "معمولی"
        HIGH = 3, "زیاد"

    campaign = models.ForeignKey(
        "Campaign", on_delete=models.CASCADE, related_name="tasks",
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE, related_name="campaign_tasks",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(max_length=200)
    detail = models.TextField(blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.TODO)
    priority = models.IntegerField(choices=Priority.choices, default=Priority.NORMAL)
    assigned_to = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campaign_tasks",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    #: The job doing this work, when there is one. Its state wins over `state`
    #: — see `effective_state`.
    job = models.ForeignKey(
        "jobs.Job", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="campaign_tasks",
    )
    #: Why this task exists, when something proposed it. Written down because a
    #: board full of tasks nobody remembers asking for is a board people ignore.
    because = models.CharField(max_length=300, blank=True)
    order = models.PositiveIntegerField(default=0)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "-priority", "id"]
        indexes = [models.Index(fields=["store", "state"])]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.title}"

    @property
    def effective_state(self) -> str:
        """The task's state, or its job's if a job is doing the work.

        Read rather than stored so the board cannot disagree with reality. Two
        rows for one piece of work drift apart within a day, and a board the
        shop has caught lying once is a board they stop reading.
        """
        if self.job_id is None:
            return self.state
        job_state = self.job.state
        if job_state in ("COMPLETED",):
            return self.State.DONE
        if job_state in ("FAILED", "CANCELLED"):
            return self.State.BLOCKED
        if job_state in ("PREVIEW", "WAITING_APPROVAL"):
            # Not DOING: nothing is happening and nothing will until a person
            # looks. Showing it as in-progress is how a job waits three days.
            return self.State.BLOCKED
        return self.State.DOING

    @property
    def is_late(self) -> bool:
        if self.due_at is None or self.effective_state in (
            self.State.DONE, self.State.DROPPED,
        ):
            return False
        return timezone.now() > self.due_at

    @property
    def waiting_on_person(self) -> bool:
        """Blocked by a job parked for approval — someone can unblock it now."""
        return (
            self.job_id is not None
            and self.job.state in ("PREVIEW", "WAITING_APPROVAL")
        )

    def mark(self, state: str) -> None:
        """Set the state a person controls. Refuses on job-backed tasks.

        Letting someone tick off a task whose render is still going produces a
        board that says done over a job that is not, which is the exact failure
        `effective_state` exists to prevent.
        """
        if self.job_id is not None:
            raise ValueError(
                "وضعیت این کار از روی خود کار سیستمی خوانده می‌شود و دستی عوض نمی‌شود."
            )
        self.state = state
        self.done_at = timezone.now() if state == self.State.DONE else None
        self.save(update_fields=["state", "done_at", "updated_at"])


def board(campaign) -> dict:
    """Everything on this campaign, grouped the way §29.1 groups it."""
    tasks = list(
        campaign.tasks.select_related("job", "assigned_to").all()
    )
    columns = []
    for kind, title in CampaignTask.Kind.choices:
        rows = [t for t in tasks if t.kind == kind]
        columns.append({
            "kind": kind,
            "title": title,
            "tasks": rows,
            "done": sum(1 for t in rows if t.effective_state == CampaignTask.State.DONE),
            "total": len(rows),
        })

    done = sum(1 for t in tasks if t.effective_state == CampaignTask.State.DONE)
    return {
        "columns": columns,
        "total": len(tasks),
        "done": done,
        # Percent of tasks, not percent of effort. Named that way in the UI too:
        # a campaign whose one remaining task is the video is not 90% finished.
        "percent": round(done / len(tasks) * 100) if tasks else 0,
        "late": [t for t in tasks if t.is_late],
        "waiting": [t for t in tasks if t.waiting_on_person],
    }


#: What a campaign almost always needs, in the order it usually happens. Used
#: as a starting point a shop edits — not as a process they must follow.
STARTER = [
    (CampaignTask.Kind.MARKETING, "مخاطب این کمپین را مشخص کن", ""),
    (CampaignTask.Kind.CONTENT, "عکس یا پوستر محصول را بساز", ""),
    (CampaignTask.Kind.CONTENT, "کپشن و متن فروش را بنویس", ""),
    (CampaignTask.Kind.CONTENT, "ویدیوی تبلیغاتی را بساز", ""),
    (CampaignTask.Kind.ADVERTISING, "زمان انتشار را تعیین کن", ""),
    (CampaignTask.Kind.SALES, "ایجنت فروش را برای سؤال‌های این کمپین آماده کن", ""),
    (CampaignTask.Kind.MARKETING, "بعد از انتشار، نتیجه را ببین", ""),
]


def seed(campaign, *, because: str = "") -> list[CampaignTask]:
    """Put the usual tasks on an empty board.

    Only on an empty one. Re-seeding a board someone has already worked on
    would resurrect tasks they deliberately deleted, and there is no way for
    them to tell our suggestion apart from their own row afterwards.
    """
    if campaign.tasks.exists():
        return []
    return CampaignTask.objects.bulk_create([
        CampaignTask(
            campaign=campaign,
            store=campaign.store,
            kind=kind,
            title=title,
            detail=detail,
            because=because or "فهرست پیش‌فرض کمپین — هرکدام را نمی‌خواهید پاک کنید",
            order=index,
        )
        for index, (kind, title, detail) in enumerate(STARTER)
    ])
