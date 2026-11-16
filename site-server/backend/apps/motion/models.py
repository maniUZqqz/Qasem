"""«استودیوی موشن»: تاریخچهٔ رندرها و دارایی‌های بارگذاری‌شده (لوگو، عکسِ محصول، اسکرین‌شات).

ویدیوی تمام‌شده به‌صورتِ یک «ویدیوی فروشگاه» (apps.content.UploadedVideo) ثبت می‌شود تا در سطلِ رسانهٔ ادیتورِ ویدیو دیده شود؛
اینجا فقط شناسه‌اش (video_id) نگه‌داشته می‌شود تا وابستگیِ مهاجرتی به اپِ محتوا نباشد.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class MotionAsset(TimeStampedModel):
    """عکسی که کاربر برای ویدیوی موشن بارگذاری کرده (لوگو، محصول، اسکرین‌شاتِ اپ)؛ کوچک‌شده روی دیسک."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="motion_assets")
    title = models.CharField(max_length=200, blank=True)
    #: مسیر نسبت به MEDIA_ROOT
    path = models.CharField(max_length=400)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    has_alpha = models.BooleanField(default=False)
    sha1 = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"motion asset {self.pk}"


class MotionRender(TimeStampedModel):
    class Mode(models.TextChoices):
        TEMPLATE = "template", "قالبی"
        AI = "ai", "با هوش مصنوعی"
        CODE = "code", "کد (Remotion)"

    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        PREPARING = "PREPARING", "آماده‌سازی (صدا و کنترلِ کیفیت)"
        WAITING_NODE = "WAITING_NODE", "منتظرِ سرورِ پردازش"
        RENDERING = "RENDERING", "در حال رندر"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"

    class Target(models.TextChoices):
        NODE = "node", "سرورِ پردازش (GPU)"
        SITE = "site", "سایت (محدود)"

    ACTIVE = ("QUEUED", "PREPARING", "WAITING_NODE", "RENDERING")

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="motion_renders")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TEMPLATE)
    title = models.CharField(max_length=200, blank=True)
    style = models.CharField(max_length=60, blank=True)
    aspect = models.CharField(max_length=6, default="9:16")
    #: پارامترهای ترکیب (حالتِ قالبی و هوش مصنوعی)
    spec = models.JSONField(default=dict, blank=True)
    #: کدِ TSX ِ کاربر (حالتِ کد)
    code = models.TextField(blank=True)
    #: {"quality": "540", "target": "node"|"site", "fps": 30}
    options = models.JSONField(default=dict, blank=True)
    target = models.CharField(max_length=6, choices=Target.choices, default=Target.NODE)
    state = models.CharField(max_length=14, choices=State.choices, default=State.QUEUED, db_index=True)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    #: شناسهٔ کارِ صفِ پردازش (ComputeJob.uid) وقتی روی گره می‌رود
    job_uid = models.CharField(max_length=40, blank=True, db_index=True)
    duration_s = models.FloatField(default=0.0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    fps = models.PositiveSmallIntegerField(default=0)
    bytes = models.PositiveBigIntegerField(default=0)
    render_s = models.FloatField(default=0.0)
    #: «ویدیوی فروشگاه» ِ ساخته‌شده (apps.content.UploadedVideo.pk)
    video_id = models.PositiveBigIntegerField(null=True, blank=True)
    #: مسیرِ تصویرِ بندانگشتیِ ویدیو نسبت به MEDIA_ROOT
    poster = models.CharField(max_length=400, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    #: طرحِ زنده‌ای که این رندر از آن ساخته شد (MotionPlan)
    plan = models.ForeignKey("motion.MotionPlan", null=True, blank=True, on_delete=models.SET_NULL, related_name="renders")
    #: گزارشِ کنترلِ کیفیتِ همین رندر: {rounds:[{n, findings[], applied[], shots[]}], remaining[], fixed, skipped_geometry, ...}
    qa = models.JSONField(default=dict, blank=True)
    #: گزارشِ صدا: {voice:{engine,voice,cue_source,seconds}, music:{...bpm,beats}, lufs, mux:"site"|"node", has_audio}
    audio_info = models.JSONField(default=dict, blank=True)
    #: مسیرِ فایل‌های صدای آماده (نسبت به NM_DATA_DIR/motion/audio) برای ترکیب با ویدیو
    audio_dir = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "-created_at"])]

    def __str__(self):
        return f"{self.title or self.style} #{self.pk} [{self.state}]"


class MotionPlan(TimeStampedModel):
    """«طرحِ صحنه»ی زنده: JSON منبعِ حقیقتِ ویدیو + تاریخچهٔ نسخه‌ها (برگشت/جلوتر) + گزارشِ کنترلِ کیفیت و نقدِ بصری."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="motion_plans")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField(max_length=200, blank=True)
    spec = models.JSONField(default=dict, blank=True)
    #: شمارهٔ نسخهٔ فعلی در MotionPlanRev
    cursor = models.PositiveIntegerField(default=0)
    #: آخرین گزارشِ QA (قاعده‌ای) روی نسخهٔ فعلی
    qa = models.JSONField(default=dict, blank=True)
    #: نقدِ بصری: {state: idle|waiting|running|done|failed|unavailable, rounds:[{n, issues[], patch[], before[], after[]}], message}
    critique = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["store", "-updated_at"])]

    def __str__(self):
        return f"{self.title or 'طرح'} #{self.pk}"


class MotionPlanRev(models.Model):
    """یک نسخه از طرح (برای برگشت/جلوتر و دیدنِ «چه کسی چه چیزی را عوض کرد»)."""

    plan = models.ForeignKey(MotionPlan, on_delete=models.CASCADE, related_name="revs")
    n = models.PositiveIntegerField()
    spec = models.JSONField(default=dict)
    label = models.CharField(max_length=160, blank=True)
    #: user | ai | chat | patch | qa | critique | audio | import
    source = models.CharField(max_length=12, default="user")
    ops = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["n"]
        constraints = [models.UniqueConstraint(fields=["plan", "n"], name="motion_planrev_unique_n")]


class MotionCustomStyle(TimeStampedModel):
    """«سبکِ تازه»: سبکی که کاربر ساخته (فروشگاهی یا همگانیِ مدیر). `data` همان ردیفِ سبک است (custom.sanitize)، بدونِ شناسه."""

    #: خالی = همگانی (فقط مدیر می‌سازد؛ همهٔ فروشگاه‌ها می‌بینند)
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.CASCADE, related_name="motion_custom_styles")
    style_id = models.CharField(max_length=60, unique=True)
    name_fa = models.CharField(max_length=60)
    name_en = models.CharField(max_length=60, blank=True)
    data = models.JSONField(default=dict)
    #: سبکی که از رویش ساخته شد (کپی) یا خالی = از صفر
    base_style = models.CharField(max_length=60, blank=True)
    #: گزارشِ کنترلِ کیفیتی که این نسخه را پذیرفت + امضای محتوایی که سنجیده شد
    qa = models.JSONField(default=dict, blank=True)
    qa_hash = models.CharField(max_length=40, blank=True)
    #: بندانگشتی (نسبت به MEDIA_ROOT)
    thumb = models.CharField(max_length=400, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["store", "-updated_at"])]

    def __str__(self):
        return f"{self.name_fa} ({self.style_id})"

    @property
    def scope(self) -> str:
        return "global" if self.store_id is None else "store"

    def as_styledef(self) -> dict:
        from . import custom

        d = custom.to_styledef(self.style_id, self.data, scope=self.scope)
        d["name_fa"], d["name_en"] = self.name_fa, self.name_en or d.get("name_en", "")
        d["pk"] = self.pk
        d["store_id"] = self.store_id
        d["base_style"] = self.base_style
        d["updated_at"] = self.updated_at.isoformat() if self.updated_at else ""
        if self.thumb:
            from django.conf import settings as dj

            d["thumb_url"] = (getattr(dj, "MEDIA_URL", "/media/") or "/media/").rstrip("/") + "/" + self.thumb.lstrip("/")
        d["qa"] = {k: (self.qa or {}).get(k) for k in ("state", "summary", "geometry", "at") if k in (self.qa or {})}
        return d


class MotionStyleCheck(TimeStampedModel):
    """کنترلِ کیفیتِ یک سبکِ پیش‌نویس (پیش از ذخیره): رندرِ واقعیِ فریم‌ها با متنِ فروشگاه + نگهبانِ کنتراست. ذخیره فقط با یک check ِ «قبول» با همان امضا ممکن است."""

    class State(models.TextChoices):
        RUNNING = "running", "در حال اجرا"
        PASS = "pass", "قبول"
        FAIL = "fail", "رد"
        ERROR = "error", "خطا"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="motion_style_checks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    style_hash = models.CharField(max_length=40, db_index=True)
    style = models.JSONField(default=dict)
    state = models.CharField(max_length=8, choices=State.choices, default=State.RUNNING, db_index=True)
    report = models.JSONField(default=dict, blank=True)
    thumb = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "-created_at"])]
