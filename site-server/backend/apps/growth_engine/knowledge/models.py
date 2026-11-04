"""Product knowledge (what NM really offers, in the team's words) and the AI-written versions of outreach messages.

``KnowledgeItem`` is the ONLY thing the AI writer may talk about: it is written by people, editable in the panel, seeded
with statements taken from what the product and its public site actually say. A price is never invented: the price item
is empty until someone types the real number («قیمت را وارد کنید»).

``GeneratedMessage`` is one AI-written version of one outreach item's message: it records what it was grounded on, the
warnings the checks raised, and which model answered; a person approves or rejects it, and approving it only replaces the
item's TEXT (the item still needs its own send approval, and a changed text voids any earlier one).
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class KnowledgeItem(TimeStampedModel):
    class Section(models.TextChoices):
        FEATURE = "feature", "قابلیت"
        BENEFIT = "benefit", "مزیت"
        LIMITATION = "limitation", "محدودیت (صادقانه بگویید)"
        AUDIENCE = "audience", "مشتریِ مناسب"
        DEMO = "demo", "نمونه / دمو"
        OFFER = "offer", "پیشنهادِ فعلی"
        PRICE = "price", "قیمت"
        NOTE = "note", "نکتهٔ دیگر"

    section = models.CharField("بخش", max_length=12, choices=Section.choices)
    title = models.CharField("عنوان", max_length=200)
    body = models.TextField("متن", blank=True, help_text="آنچه نوشته می‌شود همان است که نویسندهٔ هوشمند می‌تواند به آن تکیه کند")
    url = models.CharField("نشانی (نمونه یا پیشنهاد)", max_length=500, blank=True)
    sort_order = models.PositiveSmallIntegerField("ترتیب", default=100)
    is_active = models.BooleanField("فعال", default=True)
    seed_key = models.CharField("کلیدِ موردِ پیش‌فرض", max_length=60, null=True, blank=True, unique=True)
    note = models.CharField("یادداشتِ داخلی", max_length=400, blank=True, help_text="برای تیم؛ در پیام‌ها نمی‌آید")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="آخرین ویرایش"
    )

    class Meta:
        verbose_name = "موردِ دانشِ محصول"
        verbose_name_plural = "دانشِ محصول"
        ordering = ["section", "sort_order", "id"]
        indexes = [models.Index(fields=["is_active", "section", "sort_order"], name="gk_item_active_idx")]

    def __str__(self):
        return f"{self.get_section_display()}: {self.title}"

    @property
    def needs_value(self) -> bool:
        """A price (or an offer) waiting for its real number: nothing is made up in its place."""
        return self.section == self.Section.PRICE and not (self.body or "").strip()


class GeneratedMessage(models.Model):
    class Status(models.TextChoices):
        GENERATING = "generating", "در حال نوشتن"
        PROPOSED = "proposed", "پیشنهاد"
        APPROVED = "approved", "پذیرفته شد"
        SUPERSEDED = "superseded", "جایگزین شد"
        REJECTED = "rejected", "ردشد"
        FAILED = "failed", "ناموفق"

    item = models.ForeignKey("growth_outreach.OutreachItem", on_delete=models.CASCADE, related_name="versions", verbose_name="مورد")
    version = models.PositiveIntegerField("نسخه")
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.GENERATING)
    instructions = models.CharField("راهنمای شما به نویسنده", max_length=500, blank=True)
    subject = models.CharField("موضوع", max_length=300, blank=True)
    body = models.TextField("متنِ نوشته‌شده", blank=True, help_text="آنچه هوش مصنوعی نوشت (بدونِ امضا و جملهٔ لغو)")
    text = models.TextField("متنِ نهایی", blank=True, help_text="همان متن + امضای فرستنده + جملهٔ لغو؛ این متن جایگزینِ پیام می‌شود")
    personalization_reason = models.CharField("چرا این‌طور شخصی شد", max_length=500, blank=True)
    evidence = models.JSONField("مدارک", default=list, blank=True, help_text="[{ref, label, text}] از دانشِ محصول و اطلاعاتِ خودِ لید")
    warnings = models.JSONField("هشدارها", default=list, blank=True, help_text="[{code, text, blocking}]")
    route = models.JSONField("چه کسی نوشت", default=dict, blank=True, help_text="{via: local|metis, model, attempts}")
    error = models.CharField("خطا", max_length=600, blank=True)
    prompt_sha256 = models.CharField("sha256 پرامپت", max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="درخواست‌کننده"
    )
    created_at = models.DateTimeField("زمان", auto_now_add=True)
    finished_at = models.DateTimeField("پایانِ نوشتن", null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="تصمیم‌گیرنده"
    )
    decided_at = models.DateTimeField("زمانِ تصمیم", null=True, blank=True)

    class Meta:
        verbose_name = "نسخهٔ نوشته‌شده با هوش مصنوعی"
        verbose_name_plural = "نسخه‌های نوشته‌شده با هوش مصنوعی"
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["item", "version"], name="gk_version_unique")]
        indexes = [models.Index(fields=["item", "-version"], name="gk_version_item_idx")]

    def __str__(self):
        return f"{self.item_id} v{self.version} {self.status}"

    @property
    def blocking_warnings(self) -> list[dict]:
        return [w for w in (self.warnings or []) if w.get("blocking")]
