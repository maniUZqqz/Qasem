"""بانکِ ایده: ایده‌های خودِ فروشگاه، ستاره/پنهان و شمارندهٔ «ساخته شد از این ایده».

SOURCE: ported from InstAI:instai/ideabank/models.py @ 2f8aa90 (UserIdea / IdeaMark / IdeaUse), adapted for stores: در InstAI یک کاربر و یک بانک است،
این‌جا همهٔ ردیف‌ها **به فروشگاه** بسته‌اند (ستاره و پنهان‌کردنِ یک فروشگاه به فروشگاهِ دیگر نمی‌رسد). ایده‌های آماده در کد هستند (seeds*.py)، نه دیتابیس.
"""
from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedModel


class StoreIdea(TimeStampedModel):
    """ایده‌ای که صاحبِ فروشگاه نوشته، از ایدهٔ آماده کپی کرده، «ایده بساز» ساخته یا از ترندها ذخیره کرده."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="bank_ideas")
    key = models.CharField(max_length=64)
    data = models.JSONField(default=dict)
    based_on = models.CharField(max_length=64, blank=True, default="")
    origin = models.CharField(max_length=12, default="user")          # user | duplicate | generated | trend | imported

    class Meta:
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["store", "key"], name="ideabank_idea_unique_per_store")]

    def __str__(self):
        return f"{self.key} ({self.store_id})"


class IdeaMark(models.Model):
    """ستاره و «پنهان» برای یک ایده (آماده یا خودِ فروشگاه) در یک فروشگاه."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="bank_idea_marks")
    key = models.CharField(max_length=64)
    favorite = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["store", "key"], name="ideabank_mark_unique_per_store")]


class IdeaUse(models.Model):
    """هر بار که از یک ایده کاری شروع شد (استودیو، تقویم یا تامنیل)؛ ایده نشان می‌دهد چند بار و کجا استفاده شده."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="bank_idea_uses")
    key = models.CharField(max_length=64, db_index=True)
    target = models.CharField(max_length=12)                          # studio | calendar | thumbnail
    task_id = models.IntegerField(null=True, blank=True)              # CampaignTask ساخته‌شده برای تقویم
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["store", "key"])]
