"""Instagram trend data: pages, posts (with numbers over time), hashtags, audio, per-store seeds, topic clusters, scan runs.

**Pages and posts are shared, trends are per store.** A public page and its posts are the same facts for every shop, so `IgAccount`
and `IgPost` are stored once. What counts as a trend *for a shop* depends on which pages and hashtags that shop watches (its seeds),
so clusters, hashtag/audio statistics and runs belong to a store.

Nothing here stores followers/following lists or any person who is not the owner of a watched page.
"""
from __future__ import annotations

import secrets

from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class IgSeed(TimeStampedModel):
    """A page, hashtag or keyword a store watches. Pages are scanned; hashtags/keywords say what the niche is about."""

    class Kind(models.TextChoices):
        ACCOUNT = "account", "صفحه"
        HASHTAG = "hashtag", "هشتگ"
        KEYWORD = "keyword", "واژه"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="ig_seeds")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    value = models.CharField(max_length=80)          # account: lower-case user name; hashtag: no #, underscores; keyword: normalized
    note = models.CharField(max_length=200, blank=True)
    enabled = models.BooleanField(default=True)
    #: account seeds only: is this page read by the node scan? (an imported page that nobody scans stays in the trend set)
    scrape = models.BooleanField(default=True)
    source = models.CharField(max_length=10, default="user")     # default | user | import
    last_read_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True)     # ok | private | not_found | failed
    fail_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["kind", "value"]
        constraints = [models.UniqueConstraint(fields=["store", "kind", "value"], name="uniq_ig_seed")]

    def __str__(self):
        return f"{self.kind}:{self.value}"


class IgAccount(TimeStampedModel):
    username = models.CharField(max_length=40, unique=True)
    ig_user_id = models.CharField(max_length=30, blank=True)
    full_name = models.CharField(max_length=120, blank=True)
    biography = models.TextField(blank=True)
    followers = models.PositiveBigIntegerField(null=True, blank=True)
    following = models.PositiveBigIntegerField(null=True, blank=True)
    posts_count = models.PositiveIntegerField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)
    is_business = models.BooleanField(default=False)
    category = models.CharField(max_length=80, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)       # when the source read the page
    last_read_at = models.DateTimeField(default=timezone.now)      # when we stored it
    #: what a typical matured post of this page gets (interactions); recomputed at every ingest
    baseline = models.FloatField(null=True, blank=True)
    baseline_reel = models.FloatField(null=True, blank=True)
    baseline_note = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return "@" + self.username


class IgPost(TimeStampedModel):
    class Format(models.TextChoices):
        REEL = "reel", "ریلز"
        CAROUSEL = "carousel", "کاروسل"
        PHOTO = "photo", "عکس"
        VIDEO = "video", "ویدیو"

    account = models.ForeignKey(IgAccount, on_delete=models.CASCADE, related_name="posts")
    code = models.CharField(max_length=40, unique=True)
    ig_id = models.CharField(max_length=30, blank=True)
    fmt = models.CharField(max_length=10, choices=Format.choices, default=Format.PHOTO)
    ig_kind = models.CharField(max_length=12, blank=True)          # Abagram's own word: reel | album | video | photo
    taken_at = models.DateTimeField(db_index=True)
    caption = models.TextField(blank=True)
    hashtags = models.JSONField(default=list, blank=True)
    likes = models.PositiveBigIntegerField(null=True, blank=True)
    comments = models.PositiveBigIntegerField(null=True, blank=True)
    views = models.PositiveBigIntegerField(null=True, blank=True)
    likes_hidden = models.BooleanField(default=False)
    comments_disabled = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)
    music_title = models.CharField(max_length=200, blank=True)
    music_artist = models.CharField(max_length=200, blank=True)
    music_kind = models.CharField(max_length=10, blank=True)        # music | original
    items_count = models.PositiveSmallIntegerField(default=1)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    paid_partnership = models.BooleanField(default=False)
    hook = models.CharField(max_length=240, blank=True)
    hook_type = models.CharField(max_length=12, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    # scoring (recomputed whenever the page is read again)
    score = models.FloatField(default=0.0, db_index=True)
    ratio = models.FloatField(default=0.0)                          # velocity ratio vs the page's baseline
    growth = models.FloatField(null=True, blank=True)
    explain = models.JSONField(default=dict, blank=True)
    scored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-taken_at"]
        indexes = [models.Index(fields=["account", "-taken_at"])]

    def __str__(self):
        return f"{self.account.username}/{self.code}"

    @property
    def url(self) -> str:
        return f"https://www.instagram.com/{'reel' if self.fmt == 'reel' else 'p'}/{self.code}/"


class IgPostSnapshot(models.Model):
    """The numbers of a post at one reading; two readings give the growth."""

    post = models.ForeignKey(IgPost, on_delete=models.CASCADE, related_name="snapshots")
    at = models.DateTimeField(db_index=True)
    likes = models.PositiveBigIntegerField(null=True, blank=True)
    comments = models.PositiveBigIntegerField(null=True, blank=True)
    views = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["post", "-at"])]


class IgHashtag(TimeStampedModel):
    """How a hashtag does among the pages a store watches (recomputed with the clusters)."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="ig_hashtags")
    tag = models.CharField(max_length=80)
    posts = models.PositiveIntegerField(default=0)
    accounts = models.PositiveIntegerField(default=0)
    avg_score = models.FloatField(default=0.0)
    best_score = models.FloatField(default=0.0)
    recent_posts = models.PositiveIntegerField(default=0)           # last 72 h
    score = models.FloatField(default=0.0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-score", "tag"]
        constraints = [models.UniqueConstraint(fields=["store", "tag"], name="uniq_ig_hashtag")]


class IgAudio(TimeStampedModel):
    """A sound used by reels of the watched pages."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="ig_audios")
    key = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    artist = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=10, blank=True)
    reels = models.PositiveIntegerField(default=0)
    accounts = models.PositiveIntegerField(default=0)
    total_views = models.PositiveBigIntegerField(default=0)
    avg_score = models.FloatField(default=0.0)
    score = models.FloatField(default=0.0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-score", "title"]
        constraints = [models.UniqueConstraint(fields=["store", "key"], name="uniq_ig_audio")]


class IgTrendCluster(TimeStampedModel):
    """One topic the watched pages are making right now (rebuilt after every ingest; identified by `key`)."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="ig_clusters")
    key = models.CharField(max_length=24)
    label = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, default="topic")         # topic | breakout
    fmt = models.CharField(max_length=10, default="reel")           # the format most of its posts have
    score = models.FloatField(default=0.0, db_index=True)
    size = models.PositiveIntegerField(default=0)
    accounts_count = models.PositiveIntegerField(default=0)
    post_ids = models.JSONField(default=list, blank=True)
    stats = models.JSONField(default=dict, blank=True)              # the clustering numbers (hooks, audio, formats, ratios ...)
    why = models.JSONField(default=list, blank=True)                # Persian reasons
    brief = models.JSONField(default=dict, blank=True)              # the last «ایده بساز» result
    idea_trend = models.ForeignKey("ai.Trend", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    active = models.BooleanField(default=True)                      # false = not in the latest rebuild
    dismissed = models.BooleanField(default=False)
    first_seen_at = models.DateTimeField(default=timezone.now)
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-score", "label"]
        constraints = [models.UniqueConstraint(fields=["store", "key"], name="uniq_ig_cluster")]


class IgStoreConfig(TimeStampedModel):
    store = models.OneToOneField("stores.Store", on_delete=models.CASCADE, related_name="ig_config")
    auto_scan = models.BooleanField(default=True)
    interval_h = models.PositiveSmallIntegerField(default=8)         # at most one automatic scan this often
    max_accounts = models.PositiveSmallIntegerField(default=5)       # pages read per scan (the node caps it again)
    min_reread_h = models.PositiveSmallIntegerField(default=6)       # a page is not read again sooner than this
    seeded = models.BooleanField(default=False)                      # default seeds were applied once
    dirty = models.BooleanField(default=True)                        # new data since the clusters were built
    last_auto_at = models.DateTimeField(null=True, blank=True)


class IgScanRun(TimeStampedModel):
    class State(models.TextChoices):
        QUEUED = "queued", "در صف"
        RUNNING = "running", "در حال خواندن"
        OK = "ok", "تمام شد"
        STOPPED = "stopped", "زودتر متوقف شد"
        FAILED = "failed", "ناموفق"

    class Source(models.TextChoices):
        NODE = "node", "سرورِ پردازش (آباگرام)"
        IMPORT = "import", "واردکردنِ فایلِ آباگرام"
        INGEST = "ingest", "ارسال با کلید"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="ig_runs")
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.NODE)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED, db_index=True)
    job_uid = models.CharField(max_length=40, blank=True, db_index=True)
    accounts = models.JSONField(default=list, blank=True)           # asked
    accounts_read = models.PositiveSmallIntegerField(default=0)
    posts_new = models.PositiveIntegerField(default=0)
    posts_updated = models.PositiveIntegerField(default=0)
    stop_code = models.CharField(max_length=20, blank=True)
    message = models.CharField(max_length=300, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    ingested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def active(self) -> bool:
        return self.state in (self.State.QUEUED, self.State.RUNNING)


def new_key() -> str:
    return secrets.token_urlsafe(32)


class IgSettings(models.Model):
    """One row: the key that lets something other than the node (e.g. an Abagram on another computer) post a batch."""

    ingest_key = models.CharField(max_length=64, default=new_key)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیمات اینستاگرام"

    @classmethod
    def get(cls) -> "IgSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
