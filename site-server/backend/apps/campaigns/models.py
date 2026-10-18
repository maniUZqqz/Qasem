from django.db import models

from apps.common.models import TimeStampedModel
from apps.content.models import Caption, GeneratedImage, VideoScript
from apps.products.models import Product
from apps.stores.models import Store


class Campaign(TimeStampedModel):
    """Groups approved marketing content for one product (Phase 14)."""

    class ApprovalState(models.TextChoices):
        DRAFT = "DRAFT", "پیش‌نویس"
        APPROVED = "APPROVED", "تأییدشده"
        REJECTED = "REJECTED", "ردشده"
        PUBLISHED = "PUBLISHED", "منتشرشده"
        ARCHIVED = "ARCHIVED", "بایگانی‌شده"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="campaigns")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="campaigns")
    name = models.CharField(max_length=200)
    goal = models.CharField(max_length=200, blank=True)
    audience = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    poster = models.ForeignKey(
        GeneratedImage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    product_image = models.ForeignKey(
        GeneratedImage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    caption = models.ForeignKey(
        Caption, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    video_script = models.ForeignKey(
        VideoScript, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approval_state = models.CharField(
        max_length=12, choices=ApprovalState.choices, default=ApprovalState.DRAFT
    )

    class Meta:
        verbose_name = "کمپین"
        verbose_name_plural = "کمپین‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.store.name})"


class PublishJob(TimeStampedModel):
    """One delivery attempt of a campaign package to n8n for one platform."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "در انتظار"
        # Claimed by a worker. Exists so two workers scanning the same minute
        # cannot both publish the same post — the shop's followers see that.
        RUNNING = "RUNNING", "در حال انتشار"
        SENT = "SENT", "منتشر شد"
        FAILED = "FAILED", "ناموفق"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="publish_jobs")
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="publish_jobs")
    platform = models.CharField(max_length=32)
    payload = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    #: When this should go out. Null means "as soon as someone presses publish".
    #: A scan picks up everything whose time has passed, so a post can be late
    #: but never early — publishing before the scheduled moment is a mistake the
    #: shop cannot undo.
    scheduled_for = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "کار انتشار"
        verbose_name_plural = "کارهای انتشار"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
        ]

    def __str__(self):
        return f"Publish {self.platform} for campaign #{self.campaign_id} [{self.status}]"


# Performance rows live in their own module; Django only discovers models
# imported from here.
from .learning import PostPerformance  # noqa: E402,F401

# The campaign board (§29.1). Its own module for size; imported here so Django
# discovers the model.
from .tasks_board import CampaignTask  # noqa: E402,F401
