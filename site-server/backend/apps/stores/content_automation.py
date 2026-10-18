"""How much of the content work runs without being asked.

`ایده‌ها پنل.md` §صفحه ۴ describes a content page whose first item is
«تنظیم اتوماسیون و زمان‌بندی پست و همه‌ی محتواها» and whose last is a settings
block: how long videos should be, when things post, whether they post at all or
wait for approval.

None of it existed. `StoreProfile.publishing_preferences` was a `JSONField`
with no reader — a column that looks like the feature until you grep for it.

Four decisions worth reading.

**Approval is the default, and it is a choice, not a flag.** `AUTO` publishes,
`APPROVE` notifies and waits, `DRAFT` does not even queue. A shop owner who
discovers their Instagram posted something they never saw does not adjust the
setting; they stop using the product. So the safe value is the default and the
unsafe one has to be picked on purpose.

**Schedule is days-of-week plus a time, not a cron string.** The person setting
this is a shopkeeper. Two checkbox rows and a clock are a thing they can get
right; `0 9 * * 1,4` is a thing they can get wrong silently.

**Video length is seconds, and the quota is what bounds it.** Not a dropdown of
"short/medium/long" that maps to numbers nobody sees — the number *is* the
plan's unit, so the setting speaks the same language as the bill.

**Nothing here generates anything by itself.** This module stores the intent
and answers "what is due now". The scheduler and the queue stay where they are;
duplicating them behind a settings page is how two systems end up posting the
same thing twice.
"""
from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel

from .models import Store

#: Monday is 0, matching `datetime.weekday()`. Persian week starts Saturday, so
#: the order here is the order the panel shows them in, not 0..6.
WEEKDAYS = [
    (5, "شنبه"),
    (6, "یک‌شنبه"),
    (0, "دوشنبه"),
    (1, "سه‌شنبه"),
    (2, "چهارشنبه"),
    (3, "پنج‌شنبه"),
    (4, "جمعه"),
]

#: The renderer works in five-second shots and stitches them, so anything that
#: is not a multiple of five would be rounded somewhere the owner cannot see.
SEGMENT_SECONDS = 5
MIN_SECONDS = 5
MAX_SECONDS = 120


class ContentAutomation(TimeStampedModel):
    """One store's standing instructions for content production."""

    class Approval(models.TextChoices):
        #: Generate, then publish on schedule without asking.
        AUTO = "AUTO", "خودکار منتشر شود"
        #: Generate, notify, wait. The default.
        APPROVE = "APPROVE", "بساز و برای تأیید من نگه دار"
        #: Generate and leave it in drafts. No notification, no queue.
        DRAFT = "DRAFT", "فقط بساز و در پیش‌نویس بگذار"

    class ImageMode(models.TextChoices):
        #: Text placed by code on a template the model made (§۱ پوستر تبلیغاتی).
        POSTER = "POSTER", "پوستر بیلبوردی — با متن"
        #: The product must survive untouched (§الف معرفی محصول).
        PRODUCT_SHOT = "PRODUCT_SHOT", "نمایش محصول — بدون تغییر محصول"

    class Mode(models.TextChoices):
        SIMPLE = "SIMPLE", "ساده — از همان اطلاعات محصول"
        ADVANCED = "ADVANCED", "پیشرفته — با ورودی اضافه از من"

    store = models.OneToOneField(
        Store, on_delete=models.CASCADE, related_name="content_automation",
    )

    enabled = models.BooleanField(
        default=False,
        verbose_name="اتوماسیون روشن",
        help_text="خاموش که باشد، هیچ‌چیز خودکار ساخته نمی‌شود — دکمه‌ها دستی کار می‌کنند.",
    )

    # --- what gets made ---------------------------------------------------
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.SIMPLE)
    make_video = models.BooleanField(default=True, verbose_name="ویدیو")
    make_image = models.BooleanField(default=True, verbose_name="عکس و پوستر")
    make_caption = models.BooleanField(default=True, verbose_name="کپشن")
    image_mode = models.CharField(
        max_length=14, choices=ImageMode.choices, default=ImageMode.POSTER,
    )
    video_seconds = models.PositiveSmallIntegerField(
        default=15,
        verbose_name="طول ویدیو (ثانیه)",
        help_text="مضرب ۵ — رندر پنج‌ثانیه‌ای است و بعد به هم چسبانده می‌شود.",
    )
    language = models.CharField(
        max_length=2, choices=[("fa", "فارسی"), ("en", "انگلیسی")], default="fa",
    )
    subtitles = models.BooleanField(default=True, verbose_name="زیرنویس")
    #: §۴ «آخرش باید عکس واقعی را بگذارد».
    owner_photo_ending = models.BooleanField(
        default=False,
        verbose_name="عکس واقعی خودم آخر ویدیو",
        help_text="از پروفایل برند خوانده می‌شود. اگر عکسی آپلود نشده باشد، نادیده گرفته می‌شود.",
    )
    extra_prompt = models.TextField(
        blank=True,
        verbose_name="پرامپت تکمیلی",
        help_text="هر بار به همه‌ی تولیدها اضافه می‌شود — مثلاً «زمینه‌ی روشن، بدون آدم».",
    )

    # --- when -------------------------------------------------------------
    #: `datetime.weekday()` numbers. Empty means "no scheduled days", which is
    #: what makes `enabled` alone incapable of surprising anybody.
    publish_days = models.JSONField(default=list, blank=True)
    publish_time = models.TimeField(default=time(10, 0))
    posts_per_run = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="هر بار چند محصول",
        help_text="در هر نوبت، برای چند محصول محتوا ساخته شود.",
    )
    #: Which products to rotate through. Empty means every product in the store,
    #: which is the answer that stays right when a product is added.
    product_ids = models.JSONField(default=list, blank=True)

    # --- what happens next -------------------------------------------------
    approval = models.CharField(
        max_length=8, choices=Approval.choices, default=Approval.APPROVE,
    )
    notify = models.BooleanField(
        default=True, verbose_name="وقتی آماده شد خبرم کن",
    )

    #: Set by whatever runs the schedule, read by the panel so the owner can
    #: see that it is actually running.
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "اتوماسیون تولید محتوا"
        verbose_name_plural = "اتوماسیون تولید محتوا"

    def __str__(self):
        return f"اتوماسیون {self.store.name}"

    def clean(self):
        if self.video_seconds % SEGMENT_SECONDS:
            raise ValidationError(
                {"video_seconds": f"باید مضرب {SEGMENT_SECONDS} باشد."}
            )
        if not (MIN_SECONDS <= self.video_seconds <= MAX_SECONDS):
            raise ValidationError(
                {"video_seconds": f"بین {MIN_SECONDS} و {MAX_SECONDS} ثانیه."}
            )
        bad = [d for d in (self.publish_days or []) if d not in range(7)]
        if bad:
            raise ValidationError({"publish_days": f"روز نامعتبر: {bad}"})

    # ------------------------------------------------------------------ read
    @property
    def segment_count(self) -> int:
        """How many five-second shots this length becomes."""
        return max(1, self.video_seconds // SEGMENT_SECONDS)

    @property
    def is_scheduled(self) -> bool:
        """Enabled is not the same as scheduled.

        A shop that turned automation on but picked no day has configured
        nothing, and the panel should say so rather than imply a queue.
        """
        return bool(self.enabled and self.publish_days)

    def next_run(self, now=None):
        """The next moment this is due, or `None` when it is not scheduled."""
        if not self.is_scheduled:
            return None
        now = now or timezone.localtime()
        days = sorted(int(d) for d in self.publish_days)
        for ahead in range(8):
            day = now + timedelta(days=ahead)
            if day.weekday() not in days:
                continue
            at = day.replace(
                hour=self.publish_time.hour, minute=self.publish_time.minute,
                second=0, microsecond=0,
            )
            if at > now:
                return at
        return None

    def summary(self) -> str:
        """One sentence for the panel, so nobody has to read the form back."""
        if not self.enabled:
            return "اتوماسیون خاموش است — همه‌چیز دستی ساخته می‌شود."
        if not self.publish_days:
            return "روشن است ولی هیچ روزی انتخاب نشده — چیزی زمان‌بندی نمی‌شود."
        names = [label for value, label in WEEKDAYS if value in self.publish_days]
        what = [
            label for flag, label in (
                (self.make_video, "ویدیو"),
                (self.make_image, "عکس"),
                (self.make_caption, "کپشن"),
            ) if flag
        ]
        if not what:
            return "روشن است ولی هیچ نوع محتوایی انتخاب نشده."
        ending = {
            self.Approval.AUTO: "و خودکار منتشر می‌شود",
            self.Approval.APPROVE: "و منتظر تأیید شما می‌ماند",
            self.Approval.DRAFT: "و در پیش‌نویس می‌ماند",
        }[self.Approval(self.approval)]
        return (
            f"{'، '.join(names)} ساعت {self.publish_time:%H:%M} — "
            f"{'، '.join(what)} برای {self.posts_per_run} محصول، {ending}."
        )


def automation_for(store: Store) -> ContentAutomation:
    """The store's settings, created on first read.

    Created rather than returned-as-None so the panel never has to render an
    empty state for a form, and so a `PATCH` of one field does not have to know
    whether it is the first one.
    """
    row, _ = ContentAutomation.objects.get_or_create(store=store)
    return row
