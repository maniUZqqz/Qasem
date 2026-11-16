"""شخصیتِ برند (پنل ⇒ بخشِ «شخصیتِ برند»): نیمهٔ گفتار (``BrandPersona``) و نیمهٔ دیداری (``BrandCharacter``) برای هر فروشگاه، نسخه‌دار و قابلِ قفل.

* ``BrandPersona.data`` — نام، کهن‌الگو، لحن، ارزش‌ها، واژه‌ها، شعارها، سلام، جمله‌های نمونه، صدا (``persona.normalize``). ``active`` یعنی همهٔ تولیدکننده‌های
  متنِ فروشگاه (کپشن، ایجنتِ فروش، بانکِ ایده، تامنیل، موشن، سایت‌ساز) با همین لحن بنویسند (``inject``).
* ``BrandCharacter.doc`` — سندِ ظاهر (``engine.doc``): سبک، بدن، چهره، مو، لباس، رنگ‌ها و لایه‌های دستیِ ادیتور. «قفل» = تأییدِ مالک: نسخه +۱ و عکسِ فوری.
* ``CharacterRender`` — هر خروجی (پست، استیکر، برگه، SVG، PDF، تصویرِ هوش مصنوعی)؛ کَش با کلیدِ هش.
* ``CharacterConcept`` / ``CharacterAIJob`` — خلقِ هوشمند: توضیحِ فارسی ⇒ چند ایده؛ و کارِ ComfyUI روی سرورِ پردازش که تا روشن‌شدنِ گره در صفِ ماندگار می‌ماند.
* ``UsageEvent`` — «کجا به کار رفت» (موشن، تامنیل، قالبِ پست، پیامِ ایجنت، سایت، ویدیو).
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class BrandPersona(TimeStampedModel):
    store = models.OneToOneField("stores.Store", on_delete=models.CASCADE, related_name="brand_persona")
    data = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=0)
    locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    #: خاموش = لحن در هیچ تولیدکننده‌ای تزریق نشود
    active = models.BooleanField(default=True)
    #: ساخته از: manual | rule | facts | ai
    source = models.CharField(max_length=12, blank=True, default="manual")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "شخصیتِ گفتارِ برند"
        verbose_name_plural = "شخصیت‌های گفتارِ برند"

    def __str__(self):
        return f"persona {self.store_id} v{self.version}"


class PersonaVersion(TimeStampedModel):
    persona = models.ForeignKey(BrandPersona, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    source = models.CharField(max_length=12, blank=True)
    note = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-version", "-id"]
        unique_together = [("persona", "version")]


class BrandCharacter(TimeStampedModel):
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="brand_characters")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    name = models.CharField("نام", max_length=80)
    #: نقشِ آماده (apps.mascot.engine.brand.ROLES)
    role = models.CharField(max_length=16, default="coach")
    doc = models.JSONField(default=dict, blank=True)
    brand_colours = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=0)
    locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    #: شخصیتِ «اصلی» که در همهٔ جاها به کار می‌رود (هر فروشگاه یکی)
    is_primary = models.BooleanField(default=False)
    #: ایده‌ای که از آن ساخته شد {title, description, source}
    concept = models.JSONField(default=dict, blank=True)
    last_check = models.JSONField(default=dict, blank=True)
    #: ماسکوتِ هم‌نامِ این شخصیت (فقط خواندنی؛ برای صفحهٔ قدیمیِ «ماسکوتِ برند»)
    mascot = models.ForeignKey("mascot.Mascot", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-is_primary", "-updated_at", "-id"]
        verbose_name = "شخصیتِ دیداریِ برند"
        verbose_name_plural = "شخصیت‌های دیداریِ برند"

    def __str__(self):
        return self.name or f"character #{self.pk}"


class CharacterVersion(TimeStampedModel):
    character = models.ForeignKey(BrandCharacter, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    doc = models.JSONField(default=dict)
    note = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-version", "-id"]
        unique_together = [("character", "version")]


class CharacterRender(TimeStampedModel):
    class Kind(models.TextChoices):
        SHOT = "shot", "پست یا استوری"
        STICKER = "sticker", "استیکرِ شفاف"
        SHEET = "sheet", "برگهٔ مدل"
        SVG = "svg", "SVG"
        PDF = "pdf", "PDF"
        AI = "ai", "تصویرِ هوش مصنوعی"
        TEMPLATE = "template", "قالبِ پست/استوری"

    character = models.ForeignKey(BrandCharacter, on_delete=models.CASCADE, related_name="renders")
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="brandchar_renders")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SHOT)
    key = models.CharField(max_length=40, db_index=True)
    doc_hash = models.CharField(max_length=16, blank=True)
    version = models.PositiveIntegerField(default=0)
    locked = models.BooleanField(default=False)
    params = models.JSONField(default=dict, blank=True)
    qa = models.JSONField(default=dict, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    asset = models.ForeignKey("photoedit.PhotoAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    #: فایلِ غیرِ تصویری (SVG/PDF) نسبت به MEDIA_ROOT
    file = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        unique_together = [("character", "key")]
        verbose_name = "خروجیِ شخصیتِ برند"
        verbose_name_plural = "خروجی‌های شخصیتِ برند"


class CharacterConcept(TimeStampedModel):
    """یک دورِ «توصیفِ فارسی ⇒ چند ایده»."""
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="brandchar_concepts")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    description = models.TextField(blank=True)
    #: [{title، why، doc، palette}]
    options = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=8, default="rule")          # ai | rule
    note = models.CharField(max_length=240, blank=True)
    chosen = models.IntegerField(null=True, blank=True)
    character = models.ForeignKey(BrandCharacter, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]


class CharacterAIJob(TimeStampedModel):
    """تصویرِ هوش مصنوعی (ComfyUI روی سرورِ پردازش) از روی همین شخصیت. تا روشن‌شدنِ گره در صفِ ماندگار می‌ماند؛ شخصیتِ کدکشیده هرگز منتظر نمی‌ماند."""

    class State(models.TextChoices):
        QUEUED = "queued", "در صفِ سرورِ پردازش"
        RUNNING = "running", "در حالِ ساخت"
        DONE = "done", "آماده"
        FAILED = "failed", "ناموفق"

    character = models.ForeignKey(BrandCharacter, on_delete=models.CASCADE, related_name="ai_jobs")
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="brandchar_ai_jobs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    compute_uid = models.CharField(max_length=64, blank=True, db_index=True)
    mode = models.CharField(max_length=12, default="illustrated")        # illustrated | 3d | look
    look = models.CharField(max_length=60, blank=True)
    prompt = models.TextField(blank=True)
    pose = models.CharField(max_length=20, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    message = models.CharField(max_length=240, blank=True)
    error = models.TextField(blank=True)
    params = models.JSONField(default=dict, blank=True)
    #: سنجشِ ثبات در برابرِ برگهٔ قفل‌شده {ok، palette_score، silhouette، notes[]}
    consistency = models.JSONField(default=dict, blank=True)
    asset = models.ForeignKey("photoedit.PhotoAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sticker_asset = models.ForeignKey("photoedit.PhotoAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    character_version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at", "-id"]


class UsageEvent(TimeStampedModel):
    """هر جایی که شخصیت به کار رفت (برای صفحهٔ «گالری و کاربرد»)."""
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="brandchar_usage")
    character = models.ForeignKey(BrandCharacter, null=True, blank=True, on_delete=models.SET_NULL, related_name="usage")
    surface = models.CharField(max_length=20, db_index=True)
    ref = models.CharField(max_length=120, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]


class SiteBinding(TimeStampedModel):
    """پروژهٔ سایت‌ساز ⇐ فروشگاه (تا متنِ هوشِ مصنوعیِ سایت با لحنِ همان فروشگاه نوشته شود و بلوکِ «سربرگِ شخصیتِ برند» شخصیتِ آن را بگیرد)."""
    project_slug = models.CharField(max_length=120, unique=True)
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="brandchar_sites")

    class Meta:
        verbose_name = "اتصالِ سایت به فروشگاه"
