"""Outbound sales — صفحه ۷، minus the two parts the law does not allow yet.

`ایده‌ها پنل.md` asks for two things on this page:

1. **From a phone number**: find the person's Telegram and other social
   accounts.
2. **From a company**: find its contact routes, its HR and marketing people,
   send them a ticket, help during the call, record the call, analyse it.

Both are held, and the reasons are not engineering ones — `وضعیت ساخت.md`
records them as «دو قید حقوقی»: consent to record a call, and collecting
personal data about people who never gave it. Building either would ship a
feature whose first successful use is the problem.

**What is left after removing those is still the useful part**, and it is what
this module is: the list itself. Who you are approaching, what you know about
them, what was said, and what happens next. A shopkeeper doing outbound sales
today keeps that in their head or in a notebook, and the thing that actually
loses the deal is forgetting to call back on Tuesday.

So: no scraping, no recording, no lookup. Rows somebody typed, with a date.

**The follow-up date is the whole point.** `due()` is what makes this a tool
rather than a table — and it is why `next_action_at` is the only field besides
the name that the panel pushes you to fill in.
"""
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.stores.models import Store


class Prospect(TimeStampedModel):
    """A business this shop wants to sell to, and where that stands."""

    class Stage(models.TextChoices):
        NEW = "NEW", "تازه"
        CONTACTED = "CONTACTED", "تماس گرفته شد"
        INTERESTED = "INTERESTED", "علاقه‌مند"
        NEGOTIATING = "NEGOTIATING", "در مذاکره"
        WON = "WON", "بسته شد — فروش"
        LOST = "LOST", "بسته شد — بی‌نتیجه"

    #: Stages that no longer need a follow-up date.
    CLOSED = {Stage.WON, Stage.LOST}

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="prospects",
    )
    company = models.CharField(max_length=200, verbose_name="کسب‌وکار")
    website = models.CharField(max_length=300, blank=True)
    person = models.CharField(max_length=120, blank=True, verbose_name="شخص")
    role = models.CharField(max_length=120, blank=True, verbose_name="سمت")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    #: Whatever the shop found by hand — an Instagram handle, a Telegram
    #: username. Typed, never looked up: looking it up is the part that is held.
    social = models.CharField(
        max_length=200, blank=True,
        help_text="آی‌دی اینستاگرام یا تلگرام — اگر خودتان پیدا کردید",
    )

    stage = models.CharField(
        max_length=12, choices=Stage.choices, default=Stage.NEW,
    )
    notes = models.TextField(blank=True, verbose_name="یادداشت")
    #: What was said last time. Separate from `notes` because the last thing
    #: that happened is what you need before dialling, and digging it out of a
    #: paragraph is exactly what nobody does.
    last_outcome = models.CharField(
        max_length=300, blank=True, verbose_name="نتیجه‌ی آخرین تماس",
    )
    last_contact_at = models.DateTimeField(null=True, blank=True)
    next_action = models.CharField(
        max_length=200, blank=True, verbose_name="قدم بعدی",
    )
    next_action_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["next_action_at", "-created_at"]
        indexes = [models.Index(fields=["store", "stage", "next_action_at"])]
        verbose_name = "سرنخ فروش"
        verbose_name_plural = "سرنخ‌های فروش"

    def __str__(self):
        return self.company

    @property
    def is_closed(self) -> bool:
        return self.stage in self.CLOSED

    @property
    def is_due(self) -> bool:
        """Is a follow-up owed right now?

        A closed row is never due, whatever date is on it — otherwise every
        won deal keeps nagging, and a list that nags about nothing stops being
        read at all.
        """
        if self.is_closed or not self.next_action_at:
            return False
        return self.next_action_at <= timezone.now()


def due(store: Store):
    """Rows that owe a call today or owed one earlier. Oldest first."""
    return Prospect.objects.filter(
        store=store, next_action_at__lte=timezone.now(),
    ).exclude(stage__in=Prospect.CLOSED).order_by("next_action_at")


def counts(store: Store) -> dict:
    """One number per stage, plus how many are overdue."""
    rows = Prospect.objects.filter(store=store)
    by_stage = {stage: 0 for stage, _ in Prospect.Stage.choices}
    for stage in rows.values_list("stage", flat=True):
        by_stage[stage] = by_stage.get(stage, 0) + 1
    return {
        "total": rows.count(),
        "due": due(store).count(),
        "by_stage": by_stage,
        "open": rows.exclude(stage__in=Prospect.CLOSED).count(),
    }
