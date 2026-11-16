"""«تلفظ»: واژه‌نامهٔ فروشگاه، فهرستِ مشکل‌دارها و نتیجهٔ سنجشِ صدا → متن (ASR).

لایهٔ تلفظ (``services/audio/fa_pron``) پیش از هر موتورِ صدا اجرا می‌شود. این‌جا فقط دادهٔ قابلِ ویرایش است:

* ``LexiconEntry`` — «این واژه این‌طور خوانده شود». ``store=None`` یعنی افزودهٔ سراسری (فقط کارمندِ سایت)؛ وگرنه برای همان فروشگاه.
  مالک با بازنویسیِ ساده می‌نویسد («چِغِر»، «مَعنی»)؛ ``pn`` از آن خودکار ساخته و ذخیره می‌شود تا هر موتور از همان بخواند.
* ``ProblemWord`` — واژه‌ای که لایه نمی‌شناسد یا بررسی‌ها (ASR، واژهٔ لاتینِ ناشناخته، گزارشِ دستی) گفتند درست خوانده نمی‌شود.
* ``EvalRun`` — یک بار سنجشِ «گفتار ⇐ تشخیصِ گفتار ⇐ نرخِ خطای واژه» روی مجموعهٔ ثابتِ جمله‌ها، پیش و پس از لایه.
* ``PronSettings`` — خاموش/روشن بودنِ لایه برای فروشگاه و عمقِ آن برای هر موتور.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class PronSettings(TimeStampedModel):
    store = models.OneToOneField("stores.Store", on_delete=models.CASCADE, related_name="pron_settings")
    enabled = models.BooleanField("لایهٔ تلفظ روشن", default=True)
    ezafe = models.BooleanField("افزودنِ اضافه (-ِ / -یِ) بین واژه‌ها", default=True)
    #: {"piper": "full", "edge": "lexicon", ...}؛ خالی = پیش‌فرضِ لایه برای آن موتور
    depth = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "تنظیمِ تلفظ"
        verbose_name_plural = "تنظیم‌های تلفظ"


class LexiconEntry(TimeStampedModel):
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.CASCADE, related_name="pron_entries")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    word = models.CharField("واژه", max_length=80)
    #: آنچه مالک نوشته (بازنویسیِ ساده با فارسی یا نشانه‌گذاریِ PN)
    respelling = models.CharField("بازنویسی", max_length=160)
    #: نشانه‌گذاریِ داخلی (services/audio/fa_pron/phones.py)؛ از respelling ساخته می‌شود
    pn = models.CharField(max_length=200)
    note = models.CharField("یادداشت", max_length=200, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["word", "id"]
        constraints = [models.UniqueConstraint(fields=["store", "word"], name="pron_entry_store_word")]
        verbose_name = "واژهٔ تلفظ"
        verbose_name_plural = "واژه‌های تلفظ"

    def __str__(self):
        return f"{self.word} → {self.respelling}"


class ProblemWord(TimeStampedModel):
    class Source(models.TextChoices):
        LATIN = "latin", "واژهٔ لاتینِ ناشناخته"
        ASR = "asr", "تشخیصِ گفتار نشنید"
        MANUAL = "manual", "گزارشِ دستی"
        UNKNOWN = "unknown", "در واژه‌نامه نیست"

    class Status(models.TextChoices):
        OPEN = "open", "باز"
        FIXED = "fixed", "حل شد"
        IGNORED = "ignored", "نادیده"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="pron_problems")
    word = models.CharField(max_length=80)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    #: جمله‌ای که واژه در آن دیده شد
    context = models.CharField(max_length=300, blank=True)
    engine = models.CharField(max_length=16, blank=True)
    detail = models.CharField(max_length=300, blank=True)
    count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-count", "-updated_at"]
        constraints = [models.UniqueConstraint(fields=["store", "word", "source"], name="pron_problem_unique")]
        verbose_name = "واژهٔ مشکل‌دار"
        verbose_name_plural = "واژه‌های مشکل‌دار"


class EvalRun(TimeStampedModel):
    class State(models.TextChoices):
        WAITING = "waiting", "منتظرِ سرورِ پردازش"
        RUNNING = "running", "در حالِ اجرا"
        DONE = "done", "تمام"
        FAILED = "failed", "ناموفق"

    #: خالی = سنجشِ سراسریِ سکو (همهٔ فروشگاه‌ها می‌بینند)
    store = models.ForeignKey("stores.Store", null=True, blank=True, on_delete=models.CASCADE, related_name="pron_runs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    engine = models.CharField(max_length=16)            # piper | edge | moss
    voice = models.CharField(max_length=80, blank=True)
    sample = models.CharField(max_length=8, default="quick")   # quick | full
    depth = models.CharField(max_length=10, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.WAITING)
    message = models.CharField(max_length=300, blank=True)
    asr = models.CharField(max_length=80, blank=True)   # مدلِ تشخیصِ گفتار و دستگاه
    where = models.CharField(max_length=120, blank=True)  # گره یا «سرور»
    baseline = models.BooleanField(default=False)       # سنجشِ اولیه‌ای که همراهِ نسخه آمده
    n_sentences = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)    # quality.summarise
    rows = models.JSONField(default=list, blank=True)       # [{id, tag, ref, before, after}]
    jobs = models.JSONField(default=list, blank=True)       # uid کارهای صف
    #: وضعیتِ مرحله‌ها (Edge: ساختِ صدا روی سایت ⇐ گوش‌دادن روی گره): {"stage", "done", "dir", "error"}
    meta = models.JSONField(default=dict, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "سنجشِ تلفظ"
        verbose_name_plural = "سنجش‌های تلفظ"
