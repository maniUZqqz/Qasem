"""ادیتورِ عکس (پنل › فروشگاه › محتوا): کتابخانهٔ عکس‌ها و نسخه‌های ویرایش.

اصلِ هر عکس هرگز عوض نمی‌شود: «عکس» (PhotoAsset) یک کپیِ ثابت نگه می‌دارد و هر بار ویرایش یک «نسخه» (PhotoEdit) است
با فهرستِ کارها، وضعیت و نتیجه. کارهای سبک (برش، اندازه، متن، لوگو، رنگِ ساده) روی سرورِ سایت انجام می‌شود؛
کارهای کیتِ PersianAiKit.Photo (بهبودِ حرفه‌ای، حذفِ پس‌زمینه، بزرگ‌نمایی، ویرایشِ هوشمند) با کارِ photo.edit به
سرورِ پردازش می‌رود و نسخه تا برگشتنش «منتظرِ سرورِ پردازش» می‌ماند.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class PhotoAsset(TimeStampedModel):
    class Kind(models.TextChoices):
        UPLOAD = "upload", "آپلود"
        PRODUCT = "product", "عکسِ محصول"
        GENERATED = "generated", "تصویرِ ساخته‌شده"
        EDIT = "edit", "نسخهٔ ویرایش‌شده"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="photo_assets")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    product = models.ForeignKey("products.Product", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    title = models.CharField("عنوان", max_length=200, blank=True)
    source_kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.UPLOAD)
    #: product_image:<id> | generated:<id> | edit:<id> | ""
    source_ref = models.CharField(max_length=60, blank=True, db_index=True)
    #: کپیِ ثابتِ اصل، نسبی به MEDIA_ROOT
    original = models.CharField(max_length=400)
    thumb = models.CharField(max_length=400, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    size_bytes = models.PositiveIntegerField(default=0)
    has_alpha = models.BooleanField(default=False)
    #: اندازه‌گیریِ سبکِ سرورِ سایت (روشنایی، کنتراست، رنگ‌زدگی، تیزی، نویز، زمینه)
    facts = models.JSONField(default=dict, blank=True)
    findings = models.JSONField(default=list, blank=True)
    #: تحلیلِ کیت روی سرورِ پردازش (photo.analyze): {"state", "text", "notes", "stats", "auto"}
    kit_analysis = models.JSONField(default=dict, blank=True)
    analysis_job = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "عکسِ ادیتور"
        verbose_name_plural = "عکس‌های ادیتورِ عکس"

    def __str__(self):
        return self.title or f"photo #{self.pk}"

    @property
    def dir_rel(self) -> str:
        return f"photoedit/s{self.store_id}/a{self.pk}"


class PhotoEdit(TimeStampedModel):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "در صف"
        NODE = "NODE", "روی سرورِ پردازش"
        SERVER = "SERVER", "ساخت روی سرورِ سایت"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"
        CANCELLED = "CANCELLED", "لغو شد"

    ACTIVE = ("QUEUED", "NODE", "SERVER")

    asset = models.ForeignKey(PhotoAsset, on_delete=models.CASCADE, related_name="edits")
    number = models.PositiveIntegerField(default=1)
    #: نسخه‌هایی که با یک «اعمال» روی چند عکس ساخته شدند
    batch = models.CharField(max_length=32, blank=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    #: کلیدِ دستورِ خودکار (catalog.RECIPES) — خالی = دستی
    recipe = models.CharField(max_length=40, blank=True)
    #: [{"tool": "...", "params": {...}}] به همان ترتیبِ اجرا (اول کارهای سرورِ پردازش، بعد سرورِ سایت)
    operations = models.JSONField(default=list, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED, db_index=True)
    progress = models.FloatField(default=0.0)
    message = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    #: uid ِ کارِ apps.compute (photo.edit)
    compute_job = models.CharField(max_length=40, blank=True)
    #: {نام: مسیرِ نسبی به MEDIA_ROOT} — result، preview، thumb، node
    files = models.JSONField(default=dict, blank=True)
    #: {"after": اندازه‌گیری‌های نتیجه، "kit": {recipe, notes, used_ai…}, "server": [{tool, note}], "node": نام، …}
    stats = models.JSONField(default=dict, blank=True)
    #: {"product_images": [...], "generated_images": [...], "assets": [...]}
    saved = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "نسخهٔ ویرایشِ عکس"
        verbose_name_plural = "نسخه‌های ویرایشِ عکس"
        constraints = [models.UniqueConstraint(fields=["asset", "number"], name="photoedit_number")]

    def __str__(self):
        return f"{self.asset} v{self.number} [{self.state}]"

    @property
    def dir_rel(self) -> str:
        return f"{self.asset.dir_rel}/v{self.number}"

    @property
    def active(self) -> bool:
        return self.state in self.ACTIVE
