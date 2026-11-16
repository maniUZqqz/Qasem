"""مشتری‌یاب (the customer finder): a general crawling tool on top of the Growth Engine.

The owner describes whom to find (business types, keywords, cities, language ...) in a **mission**; each execution of a mission
is a **run** that works through a plan of **tasks** (seeds -> fetch -> parse -> follow -> extract -> dedupe -> enrich), keeping
what it finds as **candidates** until they are written into the normal Growth Engine ``Lead`` tables. Everything a run does is
written down (``CrawlLog``), it can be paused / resumed / cancelled, and a mission can repeat itself (``schedule_days``).

Nothing here sends anything. Finding a business and writing to a business are separate steps with a human between them.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.growth_engine.core.models import BackgroundJob


class CrawlMission(TimeStampedModel):
    """The saved brief: whom to find, where, from which sources, how often. One mission = one repeatable search."""

    name = models.CharField("نام", max_length=150)
    preset_key = models.CharField("پیش‌تنظیم", max_length=60, blank=True, help_text="خالی = مأموریتِ دلخواه")
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="فروشگاه")
    product = models.CharField("محصول", max_length=20, default="nm", help_text="کدام محصول را معرفی می‌کنیم (knowledge/products.py)")
    spec = models.JSONField("مشخصاتِ جست‌وجو", default=dict, blank=True)
    schedule_days = models.PositiveSmallIntegerField("تکرار (هر چند روز)", default=0, help_text="۰ = تکرار نمی‌شود")
    enabled = models.BooleanField("تکرارِ خودکار روشن", default=True)
    next_run_at = models.DateTimeField("اجرای بعدی", null=True, blank=True)
    last_run_at = models.DateTimeField("آخرین اجرا", null=True, blank=True)
    notes = models.TextField("یادداشت", blank=True)
    outreach = models.JSONField("کمپین‌های پیش‌نویس", default=dict, blank=True, help_text="{کانال: شناسهٔ کمپین}")
    is_archived = models.BooleanField("بایگانی", default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ساخته‌شده توسط")

    class Meta:
        verbose_name = "مأموریتِ مشتری‌یاب"
        verbose_name_plural = "مأموریت‌های مشتری‌یاب"
        ordering = ["-id"]
        indexes = [models.Index(fields=["is_archived", "enabled", "next_run_at"], name="gc_mission_due_idx")]

    def __str__(self):
        return self.name


class CrawlRun(BackgroundJob):
    """One execution of a mission. ``status`` is the shared job vocabulary; ``paused`` / ``stage`` / ``message`` say more."""

    class Stage(models.TextChoices):
        PLAN = "plan", "برنامه‌ریزی"
        DISCOVER = "discover", "پیدا کردن"
        DEDUPE = "dedupe", "یکی‌کردنِ تکراری‌ها"
        ENRICH = "enrich", "تکمیلِ اطلاعات"
        FINALIZE = "finalize", "ساختنِ لیدها"
        DONE = "done", "پایان"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "دستی"
        SCHEDULE = "schedule", "زمان‌بندی"
        PRESET = "preset", "پیش‌تنظیم"

    mission = models.ForeignKey(CrawlMission, on_delete=models.CASCADE, related_name="runs", verbose_name="مأموریت")
    trigger = models.CharField("شروع", max_length=10, choices=Trigger.choices, default=Trigger.MANUAL)
    stage = models.CharField("مرحله", max_length=10, choices=Stage.choices, default=Stage.PLAN)
    pause_requested = models.BooleanField("درخواستِ توقفِ موقت", default=False)
    paused = models.BooleanField("متوقفِ موقت", default=False)
    message = models.CharField("کارِ جاری", max_length=300, blank=True)
    plan = models.JSONField("برنامه", default=list, blank=True)
    spec = models.JSONField("مشخصاتِ این اجرا", default=dict, blank=True, help_text="رونوشتِ مشخصاتِ مأموریت در لحظهٔ شروع")
    usage = models.JSONField("مصرف", default=dict, blank=True)
    tasks_total = models.PositiveIntegerField("کل کارها", default=0)
    tasks_done = models.PositiveIntegerField("انجام‌شده", default=0)
    tasks_failed = models.PositiveIntegerField("ناموفق", default=0)
    tasks_waiting = models.PositiveIntegerField("منتظرِ سرورِ پردازش", default=0)
    pages_fetched = models.PositiveIntegerField("صفحه‌های گرفته‌شده", default=0)
    bytes_fetched = models.PositiveBigIntegerField("بایتِ دریافتی", default=0)
    cache_hits = models.PositiveIntegerField("از حافظه", default=0)
    found_count = models.PositiveIntegerField("موردِ پیداشده", default=0)
    unique_count = models.PositiveIntegerField("پس از یکی‌کردن", default=0)
    created_count = models.PositiveIntegerField("لیدِ تازه", default=0)
    merged_count = models.PositiveIntegerField("ادغام در لیدِ موجود", default=0)
    skipped_count = models.PositiveIntegerField("ردشده", default=0)
    finished_ok = models.BooleanField("بی‌خطا تمام شد", default=False)

    class Meta:
        verbose_name = "اجرای مشتری‌یاب"
        verbose_name_plural = "اجراهای مشتری‌یاب"
        ordering = ["-id"]
        indexes = [models.Index(fields=["mission", "-id"], name="gc_run_mission_idx"), models.Index(fields=["status", "-id"], name="gc_run_status_idx")]

    def __str__(self):
        return f"اجرای {self.pk} · {self.mission_id}"

    @property
    def state_label(self) -> str:
        """The one word the panel shows: paused / waiting for the node / the job status."""
        if self.paused:
            return "متوقفِ موقت"
        if self.status == self.Status.COMPLETED and self.tasks_waiting:
            return "تمام شد (تکمیلِ بعضی لیدها منتظرِ سرورِ پردازش)"
        return self.get_status_display()


class CrawlTask(models.Model):
    """One unit of the plan: a search query, a map query, a directory page, a website, an Instagram page.

    ``key`` is unique per run, so asking for the same thing twice (two seeds that lead to one page) does it once."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار"
        RUNNING = "running", "در حال اجرا"
        DONE = "done", "انجام شد"
        FAILED = "failed", "ناموفق"
        SKIPPED = "skipped", "ردشد"
        WAITING_NODE = "waiting_node", "منتظرِ سرورِ پردازش"

    run = models.ForeignKey(CrawlRun, on_delete=models.CASCADE, related_name="tasks", verbose_name="اجرا")
    stage = models.CharField("مرحله", max_length=10, default="discover")
    source = models.CharField("منبع", max_length=20)
    kind = models.CharField("نوع", max_length=24)
    key = models.CharField("کلید", max_length=400)
    label = models.CharField("شرح", max_length=300, blank=True)
    params = models.JSONField("پارامترها", default=dict, blank=True)
    depth = models.PositiveSmallIntegerField("عمق", default=0)
    priority = models.PositiveSmallIntegerField("اولویت", default=100)
    status = models.CharField("وضعیت", max_length=14, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField("دفعاتِ تلاش", default=0)
    not_before = models.DateTimeField("نه زودتر از", null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField("نتیجه", default=dict, blank=True)
    error = models.CharField("خطا", max_length=500, blank=True)
    node_job_uid = models.CharField("کارِ سرورِ پردازش", max_length=64, blank=True)

    class Meta:
        verbose_name = "کارِ برنامهٔ مشتری‌یاب"
        verbose_name_plural = "کارهای برنامهٔ مشتری‌یاب"
        ordering = ["priority", "id"]
        constraints = [models.UniqueConstraint(fields=["run", "key"], name="gc_task_unique_key")]
        indexes = [models.Index(fields=["run", "status", "stage", "priority"], name="gc_task_pick_idx")]

    def __str__(self):
        return f"{self.source}:{self.kind}:{self.key[:60]}"


class CrawlLog(models.Model):
    """The run's diary, newest last. Capped per run (``runner.MAX_LOG_ROWS``) so a huge crawl cannot fill the database."""

    run = models.ForeignKey(CrawlRun, on_delete=models.CASCADE, related_name="logs", verbose_name="اجرا")
    level = models.CharField("سطح", max_length=8, default="info")  # info | warn | error
    message = models.CharField("پیام", max_length=500)
    created_at = models.DateTimeField("زمان", default=timezone.now)

    class Meta:
        verbose_name = "گزارشِ اجرا"
        verbose_name_plural = "گزارشِ اجراها"
        ordering = ["id"]
        indexes = [models.Index(fields=["run", "id"], name="gc_log_run_idx")]


class CrawlCandidate(models.Model):
    """A business as the sources described it, merged across sources, before (and after) it becomes a lead."""

    class State(models.TextChoices):
        NEW = "new", "تازه"
        CREATED = "created", "لید ساخته شد"
        MERGED = "merged", "با لیدِ موجود ادغام شد"
        SKIPPED = "skipped", "ردشد"

    run = models.ForeignKey(CrawlRun, on_delete=models.CASCADE, related_name="candidates", verbose_name="اجرا")
    name = models.CharField("نام", max_length=200)
    name_core = models.CharField("نامِ مقایسه", max_length=200, blank=True)
    category = models.CharField("دسته", max_length=120, blank=True)
    types = models.JSONField("نوع‌های کسب‌وکار", default=list, blank=True)
    city = models.CharField("شهر", max_length=100, blank=True)
    address = models.CharField("نشانی", max_length=400, blank=True)
    lat = models.FloatField("عرض", null=True, blank=True)
    lon = models.FloatField("طول", null=True, blank=True)
    phones = models.JSONField("تلفن‌ها", default=list, blank=True)
    emails = models.JSONField("ایمیل‌ها", default=list, blank=True)
    whatsapp = models.JSONField("واتساپ", default=list, blank=True)
    website = models.CharField("وب‌سایت", max_length=500, blank=True)
    instagram = models.CharField("اینستاگرام", max_length=300, blank=True)
    telegram = models.CharField("تلگرام", max_length=300, blank=True)
    contact_form = models.CharField("فرمِ تماس", max_length=500, blank=True)
    hours = models.CharField("ساعتِ کاری", max_length=400, blank=True)
    rating = models.FloatField("امتیاز", null=True, blank=True)
    sources = models.JSONField("منبع‌ها", default=list, blank=True, help_text="[{source, ref, url, at}]")
    signals = models.JSONField("نشانه‌ها", default=dict, blank=True, help_text="کلمه‌های دیده‌شده، دنبال‌کننده‌ها، بیوِ پیج ...")
    state = models.CharField("وضعیت", max_length=8, choices=State.choices, default=State.NEW)
    lead = models.ForeignKey("growth_leads.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="لید")
    score = models.PositiveSmallIntegerField("امتیاز تناسب", default=0)
    enriched = models.BooleanField("اطلاعاتِ سایتش خوانده شد", default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "نامزدِ مشتری‌یاب"
        verbose_name_plural = "نامزدهای مشتری‌یاب"
        ordering = ["id"]
        indexes = [models.Index(fields=["run", "state"], name="gc_cand_state_idx")]

    def __str__(self):
        return self.name


class CandidateKey(models.Model):
    """An identity key of a candidate (phone, domain, handle, OSM object, name+place ...): two candidates of one run that
    share a key are the same business. Unique per run, so the database is the last line of defence against duplicates."""

    run = models.ForeignKey(CrawlRun, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=320)
    candidate = models.ForeignKey(CrawlCandidate, on_delete=models.CASCADE, related_name="keys")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "key"], name="gc_candkey_unique")]


class FetchCache(models.Model):
    """The page cache: the same URL is not downloaded twice within ``expires_at`` (one run, or the next run of the same mission).

    Bodies live in files under ``<data>/crawl_cache`` (gzip), the table is only the index."""

    url_key = models.CharField(max_length=40, unique=True)
    url = models.CharField(max_length=600)
    status = models.PositiveSmallIntegerField(default=0)
    content_type = models.CharField(max_length=120, blank=True)
    final_url = models.CharField(max_length=600, blank=True)
    path = models.CharField(max_length=300, blank=True)
    size = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=24, default="ok")
    fetched_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "حافظهٔ صفحه‌ها"
        verbose_name_plural = "حافظهٔ صفحه‌ها"


class CrawlFinding(TimeStampedModel):
    """«این لید برای این مأموریت چقدر مناسب است» - a lead can be a good fit for one mission and a poor one for another, so the
    score lives here, not on the lead."""

    mission = models.ForeignKey(CrawlMission, on_delete=models.CASCADE, related_name="findings", verbose_name="مأموریت")
    lead = models.ForeignKey("growth_leads.Lead", on_delete=models.CASCADE, related_name="crawl_findings", verbose_name="لید")
    first_run = models.ForeignKey(CrawlRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="اولین اجرا")
    last_run = models.ForeignKey(CrawlRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="آخرین اجرا")
    score = models.PositiveSmallIntegerField("امتیاز تناسب", default=0)
    level = models.CharField("سطح", max_length=8, default="low")
    reasons = models.JSONField("دلیل‌ها", default=list, blank=True, help_text="[{text, points}]")
    matched = models.JSONField("تطبیق", default=dict, blank=True, help_text="{types, keywords, sources}")
    seen_count = models.PositiveSmallIntegerField("دفعاتِ دیده‌شدن", default=1)

    class Meta:
        verbose_name = "یافتهٔ مشتری‌یاب"
        verbose_name_plural = "یافته‌های مشتری‌یاب"
        ordering = ["-score", "-id"]
        constraints = [models.UniqueConstraint(fields=["mission", "lead"], name="gc_finding_unique")]
        indexes = [models.Index(fields=["mission", "-score"], name="gc_finding_score_idx")]


class LeadInsight(TimeStampedModel):
    """What the crawler knows about a lead beyond the Growth Engine's own columns: where it is on the map, when it is open."""

    lead = models.OneToOneField("growth_leads.Lead", on_delete=models.CASCADE, related_name="insight", verbose_name="لید")
    lat = models.FloatField("عرض", null=True, blank=True)
    lon = models.FloatField("طول", null=True, blank=True)
    geo_source = models.CharField("منبعِ مکان", max_length=20, blank=True)
    hours = models.CharField("ساعتِ کاری", max_length=400, blank=True)
    rating = models.FloatField("امتیاز", null=True, blank=True)
    types = models.JSONField("نوع‌ها", default=list, blank=True)
    signals = models.JSONField("نشانه‌ها", default=dict, blank=True)

    class Meta:
        verbose_name = "اطلاعاتِ تکمیلیِ لید"
        verbose_name_plural = "اطلاعاتِ تکمیلیِ لیدها"
        indexes = [models.Index(fields=["lat", "lon"], name="gc_insight_geo_idx")]


class LeadReminder(TimeStampedModel):
    """A follow-up: «زنگ بزن»، «دوباره پیام بده» on a date."""

    lead = models.ForeignKey("growth_leads.Lead", on_delete=models.CASCADE, related_name="reminders", verbose_name="لید")
    due_at = models.DateTimeField("موعد")
    note = models.CharField("یادداشت", max_length=300, blank=True)
    done_at = models.DateTimeField("انجام شد", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ساخته‌شده توسط")

    class Meta:
        verbose_name = "یادآوریِ پیگیری"
        verbose_name_plural = "یادآوری‌های پیگیری"
        ordering = ["due_at", "id"]
        indexes = [models.Index(fields=["done_at", "due_at"], name="gc_reminder_due_idx")]


class OutreachDraft(TimeStampedModel):
    """A drafted message for one lead on one channel, in the mission's brand voice. Written by the system, approved by a person.

    Approving a draft only says «this text is fine». For the channels the Growth Engine sends itself (SMS, e-mail, site form) the
    approved draft is put into the mission's campaign as a *ready* item - the campaign's own approval, daily caps, quiet hours and
    do-not-contact checks still stand between it and any send. For manual channels (Instagram DM, WhatsApp, Telegram ...) the person
    copies the text and sends it by hand."""

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        APPROVED = "approved", "متن تأیید شد"
        QUEUED = "queued", "در کمپین گذاشته شد"
        SENT_MANUAL = "sent_manual", "دستی فرستاده شد"
        REJECTED = "rejected", "ردشد"
        BLOCKED = "blocked", "مسدود (تماس نگیر)"

    mission = models.ForeignKey(CrawlMission, on_delete=models.CASCADE, related_name="drafts", verbose_name="مأموریت")
    lead = models.ForeignKey("growth_leads.Lead", on_delete=models.CASCADE, related_name="crawl_drafts", verbose_name="لید")
    channel = models.CharField("کانال", max_length=16)
    recipient = models.CharField("گیرنده", max_length=500, blank=True)
    subject = models.CharField("موضوع", max_length=300, blank=True)
    body = models.TextField("متن")
    warnings = models.JSONField("هشدارها", default=list, blank=True)
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.DRAFT)
    block_reason = models.CharField("دلیلِ مسدودی", max_length=300, blank=True)
    item = models.ForeignKey("growth_outreach.OutreachItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="موردِ کمپین")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="تأییدکننده")
    approved_at = models.DateTimeField("زمانِ تأیید", null=True, blank=True)

    class Meta:
        verbose_name = "پیش‌نویسِ پیام"
        verbose_name_plural = "پیش‌نویس‌های پیام"
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["mission", "lead", "channel"], name="gc_draft_unique")]
        indexes = [models.Index(fields=["mission", "status"], name="gc_draft_status_idx")]
