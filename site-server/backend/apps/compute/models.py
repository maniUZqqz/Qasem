"""سرورهای پردازش (compute nodes) و کارهایی که به آن‌ها سپرده می‌شود.

سرورِ سایت IP ثابت دارد ولی GPU ندارد؛ سرورهای پردازش GPU دارند ولی IP ثابت ندارند و از
بیرون قابلِ دسترس نیستند. پس ارتباط همیشه از سمتِ سرورِ پردازش **به بیرون** است: هر
«گره» (node) با توکنِ خودش به سایت وصل می‌شود، کار می‌گیرد، انجام می‌دهد و خروجی را
پس می‌فرستد. هیچ پورتی روی سرورِ پردازش باز نمی‌شود.

دو گره (یا بیشتر) هم‌زمان کار می‌گیرند بی‌تداخل: گرفتنِ کار یک UPDATE ِ شرطی است
(«فقط اگر هنوز کسی نگرفته») و هر کار دقیقاً به یک گره می‌رسد. کارِ تکراری هم دو بار
پردازش نمی‌شود: هر درخواست یک اثرِ انگشت (hash) دارد و اگر همان درخواست به‌تازگی با
موفقیت انجام شده، همان خروجی برمی‌گردد.
"""
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel

#: پیشوندِ نوعِ کار ⇐ قابلیتی که گره باید داشته باشد
CAPABILITY_FOR_KIND = {
    "comfy": "comfyui",      # گرافِ ComfyUI (FLUX، Wan، LatentSync) یا پروفایلِ پلِ ComfyUI
    "photo": "photo",        # ویرایشگرِ عکس (PersianAiKit.Photo)
    "video": "video",        # ویرایشگرِ ویدیو (PersianAiKit.Video)
    "voice": "voice",        # صدا (PersianAiKit.Voice)
    "ollama": "ollama",      # مدل‌های متنی/بیناییِ Ollama روی GPU
    "up3d": "blender",       # موتورِ سه‌بعدی (Blender) — صفِ خودش را دارد، این‌جا فقط برای گزارش
    "echo": "any",           # آزمونِ اتصال
    "edit": "ffmpeg",        # ویرایشگرِ ویدیو: رندرِ نهایی (edit.render)، ردیابی (edit.track)، حذفِ پس‌زمینه (edit.matte)
}


def capability_for(kind: str) -> str:
    return CAPABILITY_FOR_KIND.get((kind or "").split(".", 1)[0], "any")


def new_token() -> str:
    return secrets.token_urlsafe(36)


class ComputeNode(TimeStampedModel):
    name = models.CharField("نام", max_length=60, unique=True)
    token = models.CharField(max_length=80, unique=True, default=new_token)
    enabled = models.BooleanField("فعال", default=True)
    #: آخرین گزارشِ خودِ گره: {"comfyui": true, "photo": true, "gpu": "RTX 3060", ...}
    capabilities = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    jobs_done = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=300, blank=True)
    #: خواستهٔ پنل: کدام سرویس‌ها روی این گره روشن باشند — {"ollama": true, "comfyui": true, "voice": false, ...}
    #: کلیدِ غایب = «دست نزن» (پیش‌فرضِ خودِ گره). گره در هر heartbeat این را می‌گیرد و اجرا می‌کند.
    desired = models.JSONField("سرویس‌های خواسته‌شده", default=dict, blank=True)
    #: اگر کاری بیاید که سرویسش روشن نیست (مثلاً Ollama بالاست و ویدیو خواسته شده)، گره خودش حافظهٔ موتورِ
    #: دیگر را آزاد می‌کند و سرویسِ لازم را روشن می‌کند؛ خاموش = کار منتظرِ تنظیمِ دستی می‌ماند.
    auto_switch = models.BooleanField("سوئیچِ خودکارِ سرویس‌ها", default=True)

    class Meta:
        verbose_name = "سرور پردازش"
        verbose_name_plural = "سرورهای پردازش"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def online(self) -> bool:
        return bool(self.last_seen and (timezone.now() - self.last_seen).total_seconds() < 90)

    def has(self, capability: str) -> bool:
        """این گره این توانایی را دارد: یا سرویسش الان بالاست، یا (با سوئیچِ خودکار) عاملِ گره می‌تواند
        خودش آن را روشن کند (caps["startable"][capability] از services.json ِ گره)."""
        if capability == "any":
            return True
        caps = self.capabilities or {}
        if caps.get(capability):
            return True
        return bool(self.auto_switch and (caps.get("startable") or {}).get(capability))

    def could_run(self, kind: str) -> bool:
        """گره (حتی خاموش) طبقِ آخرین گزارشش می‌تواند این نوعِ کار را بگیرد — برای صفِ ماندگار: کار تا روشن شدنِ این گره منتظر می‌ماند."""
        return self.enabled and self.has(capability_for(kind))

    def can_start(self, capability: str) -> bool:
        return bool(((self.capabilities or {}).get("startable") or {}).get(capability))

    def can_run(self, kind: str) -> bool:
        return self.enabled and self.has(capability_for(kind))


class ComputeJob(TimeStampedModel):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        CLAIMED = "CLAIMED", "گرفته شد"
        RUNNING = "RUNNING", "در حال پردازش"
        COMPLETED = "COMPLETED", "تمام شد"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"

    FINAL = ("COMPLETED", "FAILED", "CANCELLED")

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=40, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    #: {نامِ منطقی: مسیرِ نسبی زیرِ پوشهٔ کار}
    inputs = models.JSONField(default=dict, blank=True)
    priority = models.PositiveSmallIntegerField(default=100)
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED, db_index=True)
    node = models.ForeignKey(ComputeNode, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs")
    #: گره‌ای که این کار فقط به آن داده شود (خالی = هر گرهٔ توانا)
    node_wanted = models.CharField(max_length=60, blank=True)
    request_hash = models.CharField(max_length=64, blank=True, db_index=True)
    dedupe_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    origin = models.CharField(max_length=40, blank=True)
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=2)
    timeout_s = models.PositiveIntegerField(default=1800)
    lease_s = models.PositiveIntegerField(default=600)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    #: {"outputs": [{"name", "path", "size", "media"}], "meta": {...}}
    result = models.JSONField(default=dict, blank=True)
    cancel_requested = models.BooleanField(default=False)
    claimed_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    #: آخرین باری که کار وارد صف شد (ثبت، یا برگشت پس از قطعِ گره/خطا) — برای «چند وقت منتظر مانده»
    queued_at = models.DateTimeField("آخرین ورود به صف", null=True, blank=True)
    #: ثانیه‌ای که پیش از آخرین گرفته‌شدن در صف ماند (برای گزارش)
    waited_s = models.FloatField("ثانیهٔ انتظار در صف", null=True, blank=True)
    #: ثانیه‌ای که روی گره اجرا شد (از گرفته‌شدن تا پایان)
    run_s = models.FloatField("ثانیهٔ اجرا", null=True, blank=True)
    #: چند بار گره وسطِ کار قطع شد و کار بی‌خبر ماند؛ از تلاش‌ها کم نمی‌شود (فقط خطای واقعی تلاش را می‌خورد)
    lost_count = models.PositiveSmallIntegerField("دفعاتِ قطعِ گره وسطِ کار", default=0)
    #: سقفِ انتظار در صف به ثانیه؛ ۰ = بی‌پایان (پیش‌فرض). اگر بیشتر بماند ناموفق می‌شود.
    max_wait_s = models.PositiveIntegerField("سقفِ انتظار (ثانیه؛ ۰ = بی‌پایان)", default=0)
    #: زمان‌بندی: پیش از این لحظه هیچ گره‌ای کار را نمی‌گیرد
    not_before = models.DateTimeField("شروعِ زمان‌بندی‌شده", null=True, blank=True)
    #: بازهٔ مجازِ شروع به وقتِ تهران، مثلاً «02:00-07:00»؛ خالی = همیشه
    window = models.CharField("بازهٔ مجازِ شروع", max_length=11, blank=True)
    #: دسته برای فهرست/گزارش: «download» برای دانلودها
    category = models.CharField("دسته", max_length=20, blank=True, db_index=True)

    class Meta:
        verbose_name = "کار پردازشی"
        verbose_name_plural = "کارهای پردازشی"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["state", "priority", "created_at"])]

    def __str__(self):
        return f"{self.kind} {str(self.uid)[:8]} [{self.state}]"

    @property
    def final(self) -> bool:
        return self.state in self.FINAL

    @property
    def dir_rel(self) -> str:
        return f"compute/jobs/{self.uid}"

    def outputs(self) -> list:
        return list((self.result or {}).get("outputs") or [])

    @property
    def required_capability(self) -> str:
        return capability_for(self.kind)


class ComputeNodeLog(models.Model):
    """لاگِ سرورِ پردازش که خودش به سایت می‌فرستد (خطاها و هشدارها) — تا بدونِ رفتن پای آن سیستم ببینیم چه شده."""
    node = models.ForeignKey(ComputeNode, on_delete=models.CASCADE, related_name="logs", verbose_name="سرور")
    level = models.CharField("سطح", max_length=10, default="INFO")
    message = models.TextField("پیام")
    logged_at = models.DateTimeField("زمان روی سرورِ پردازش", null=True, blank=True)
    created_at = models.DateTimeField("زمان دریافت", auto_now_add=True)

    class Meta:
        verbose_name = "لاگِ سرورِ پردازش"
        verbose_name_plural = "لاگ‌های سرورهای پردازش"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.node.name} {self.level}: {self.message[:60]}"


class ComputeSettings(models.Model):
    """تنظیمِ مسیرِ پردازش (یک ردیف): تصویر/ویدیو روی کدام سرور ساخته شود. از پنلِ «سرورهای پردازش» عوض می‌شود."""
    image_video_node = models.CharField(
        "سرورِ تصویر و ویدیو", max_length=60, blank=True,
        help_text="خالی = هر سرورِ پردازشی که ComfyUI دارد؛ نامِ سرور = فقط همان سرور")
    enroll_key = models.CharField(
        "کلیدِ ثبتِ سرورهای پردازش", max_length=80, default=new_token,
        help_text="روی هر کامپیوترِ گرافیکی فقط START.bat اجرا می‌شود و این کلید را می‌گیرد؛ خودش ثبت می‌شود و توکنِ خودش را می‌گیرد")
    #: صفِ ماندگار: کارِ منتظرِ گره بعد از چند ساعت ناموفق شود؟ ۰ = هرگز (پیش‌فرض: تا وصل شدنِ گره منتظر می‌ماند)
    max_wait_hours = models.PositiveIntegerField(
        "سقفِ انتظارِ کارها (ساعت؛ ۰ = بی‌پایان)", default=0,
        help_text="۰ یعنی کارِ منتظر هرگز به‌خاطرِ خاموش بودنِ سرورِ پردازش ناموفق نمی‌شود؛ فقط با خطای واقعی یا لغوِ شما")
    #: دانلودها: «now» همین الان، «window» فقط در بازهٔ شبانه
    download_mode = models.CharField("زمانِ دانلودها", max_length=10, default="now")
    download_window = models.CharField("بازهٔ شبانهٔ دانلود (وقتِ تهران)", max_length=11, default="02:00-07:00")
    #: نگه‌داریِ آمار و سابقه (روز) برای گزارشِ سرورهای پردازش
    retention_days = models.PositiveIntegerField("نگه‌داریِ آمار (روز)", default=30)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیماتِ مسیرِ پردازش"
        verbose_name_plural = "تنظیماتِ مسیرِ پردازش"

    def __str__(self):
        return "مسیرِ پردازش"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

# «تست» of the voice models per node (apps.compute.voice_models).
from .bench_models import AudioBenchmark  # noqa: E402,F401
# «گزارشِ سرورها»: نوبت‌های اتصال و نمونه‌های منابع (apps.compute.report).
from .models_report import ComputeNodeSample, ComputeNodeSession  # noqa: E402,F401
