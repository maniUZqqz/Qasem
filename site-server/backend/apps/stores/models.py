from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.common.models import TimeStampedModel
from apps.common.utils import unique_slug


class Store(TimeStampedModel):
    """Tenant boundary: every business object belongs to a Store."""

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True, blank=True)
    business_type = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    target_audience = models.CharField(max_length=255, blank=True)
    contact = models.JSONField(default=dict, blank=True)
    logo = models.ImageField(upload_to="stores/logos/", blank=True, null=True)
    colors = models.JSONField(default=dict, blank=True)
    social_links = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "فروشگاه"
        verbose_name_plural = "فروشگاه‌ها"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Store, self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class StoreProfile(models.Model):
    """Brand voice, policies and AI preferences for a store."""

    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name="profile")
    brand_voice = models.CharField(max_length=100, blank=True)
    # NovinHub — publishing straight to the store's own Instagram. Left blank,
    # the shared .env token is used; left blank on both, publishing falls back
    # to the n8n webhook the owner wires up themselves.
    novinhub_token = models.CharField(
        max_length=255, blank=True,
        help_text="توکن اختصاصی نوین‌هاب این فروشگاه (اختیاری)",
    )
    novinhub_account_ids = models.JSONField(
        default=list, blank=True,
        help_text="شناسه‌ی اکانت‌های اینستاگرام که پست روی آن‌ها منتشر می‌شود",
    )
    # The bot token used to be one shared value in `.env`, which meant every
    # shop on the installation answered from the same Telegram bot — two shops
    # could not each have their own, and the second one to connect simply
    # spoke with the first one's voice.
    telegram_bot_token = models.CharField(
        max_length=255, blank=True,
        verbose_name="توکن ربات تلگرام این فروشگاه",
        help_text="از @BotFather. خالی بگذارید تا از ربات مشترک سرویس استفاده شود.",
    )
    tone = models.CharField(max_length=100, blank=True)
    content_style = models.CharField(max_length=100, blank=True)
    visual_preferences = models.JSONField(default=dict, blank=True)
    shipping_policy = models.TextField(blank=True)
    return_policy = models.TextField(blank=True)
    refund_policy = models.TextField(blank=True)
    payment_info = models.TextField(blank=True)
    business_rules = models.TextField(blank=True)
    working_hours = models.JSONField(default=dict, blank=True)
    ai_preferences = models.JSONField(default=dict, blank=True)
    publishing_preferences = models.JSONField(default=dict, blank=True)
    #: The shop owner's own photo, for the last frame of a video (§26). Kept
    #: separate from every generated image on purpose: the value of that frame
    #: is that the viewer believes it was not made up, so it may only ever come
    #: from something a person uploaded.
    owner_photo = models.ImageField(
        upload_to="stores/owner/", null=True, blank=True,
        help_text="عکس واقعی خودتان — آخر ویدیو نشان داده می‌شود",
    )
    owner_caption = models.CharField(
        max_length=120, blank=True,
        help_text="زیر عکس چه بنویسیم؟ مثلاً «مهدی، صاحب فروشگاه»",
    )
    #: How this shop's narration should sound. Only the settings the voice
    #: engine actually has: gender, pitch, speed, loudness. Age, accent and
    #: emotion do not exist for Persian — see services.audio.profile.
    voice_profile = models.JSONField(default=dict, blank=True)
    #: Default for new videos. Overridable per video — a product demo wants
    #: subtitles because most people watch muted, and a mood piece with no
    #: speech does not.
    subtitles_by_default = models.BooleanField(
        default=True, help_text="زیرنویس روی ویدیوهای تازه، مگر اینکه جدا خاموشش کنید",
    )
    subtitles_burned_by_default = models.BooleanField(
        default=False,
        help_text="زیرنویس روی خود تصویر بسوزد؟ اگر نه، فایل SRT جدا داده می‌شود",
    )
    #: The secret in this store's inbound webhook URL. Created on first use
    #: (`apps.customers.webhooks.secret_for`), never shown twice without the
    #: owner asking — it is a bearer credential, and anyone holding the URL can
    #: deliver a message that runs the sales agent on the shop's quota.
    webhook_secret = models.CharField(max_length=64, blank=True, db_index=True)
    #: How to *say* names the voice engine gets wrong: {"Nike": "نایکی"}. Only
    #: the narration is rewritten — captions still show what the shop wrote.
    #: §7: «اسم برندها و کلمه‌های خاص را درست تلفظ می‌کنیم، نه حرف به حرف».
    pronunciations = models.JSONField(
        default=dict, blank=True,
        help_text="تلفظ درست اسم‌ها برای صداگذاری — مثلاً Nike به «نایکی»",
    )

    def __str__(self):
        return f"Profile of {self.store.name}"


@receiver(post_save, sender=Store)
def create_store_profile(sender, instance, created, **kwargs):
    if created:
        StoreProfile.objects.get_or_create(store=instance)


class Membership(TimeStampedModel):
    """A person's seat in a store, with a role.

    `Store.owner` is not a row here. Ownership is the tenant's anchor — who
    pays and who can delete — and folding it into the membership table would
    make it possible to remove the last owner and orphan a paying store. The
    access layer treats the owner as OWNER without needing a row.
    """

    class Role(models.TextChoices):
        OWNER = "OWNER", "مالک"
        ADMIN = "ADMIN", "مدیر"
        MARKETING = "MARKETING", "بازاریابی"
        CONTENT_MANAGER = "CONTENT", "مدیر محتوا"
        SUPPORT = "SUPPORT", "پشتیبانی"
        VIEWER = "VIEWER", "بازدیدکننده"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="store_memberships")
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.VIEWER)
    is_active = models.BooleanField(default=True)

    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    #: Removing access should be reversible and answerable ("who removed me?"),
    #: so a seat is deactivated rather than deleted.
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["store", "user"], name="one_seat_per_user_per_store"),
        ]
        indexes = [models.Index(fields=["user", "is_active"])]
        ordering = ["store", "role", "id"]
        verbose_name = "عضو فروشگاه"
        verbose_name_plural = "اعضای فروشگاه"

    def __str__(self):
        return f"{self.user} @ {self.store} ({self.get_role_display()})"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.store_id and self.user_id and self.store.owner_id == self.user_id:
            raise ValidationError(
                "مالک فروشگاه به‌صورت خودکار دسترسی کامل دارد و نیازی به عضویت ندارد."
            )


# The sales-agent settings live in their own module for size, but Django only
# discovers models imported from here.
from .agent_settings import SalesAgentSettings  # noqa: E402,F401
from .content_automation import ContentAutomation  # noqa: E402,F401
