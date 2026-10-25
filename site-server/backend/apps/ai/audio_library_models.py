"""The shop's audio library: every voice-over, ambience and music bed made in the «صدا» section.

A row is made the moment a generator is pressed (status PENDING), so a long job on a processing node survives
a closed tab: the panel asks again later and the row picks up the node's output (services.audio.studio.sync).
Files live outside MEDIA_ROOT (a cloned voice is a person's voice) and are streamed only to the store's members.
`saved` separates «در کتابخانه» from a draft the shop listened to and did not keep; drafts are swept after a day.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class AudioAsset(TimeStampedModel):
    class Kind(models.TextChoices):
        SPEECH = "SPEECH", "گفتار"
        SFX = "SFX", "صدای محیط و افکت"
        MUSIC = "MUSIC", "موسیقیِ زمینه"

    class Status(models.TextChoices):
        PENDING = "PENDING", "در صف"
        RUNNING = "RUNNING", "در حالِ ساخت"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ناموفق"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="audio_assets",
                              verbose_name="فروشگاه")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    kind = models.CharField("نوع", max_length=8, choices=Kind.choices, db_index=True)
    status = models.CharField("وضعیت", max_length=8, choices=Status.choices, default=Status.PENDING)
    title = models.CharField("عنوان", max_length=120, blank=True)
    #: what the shop typed: the words to speak, or the description of the sound / music
    text = models.TextField("متن یا توضیح", blank=True)
    #: what the engine was actually given (an English description for effects and music)
    prompt = models.TextField("ورودیِ موتور", blank=True)
    params = models.JSONField("تنظیمات", default=dict, blank=True)
    engine = models.CharField("موتور", max_length=40, blank=True)
    voice_label = models.CharField("صدا", max_length=120, blank=True)
    cloned_voice = models.ForeignKey("ai.ClonedVoice", null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="assets")
    license = models.CharField("مجوز", max_length=80, blank=True)
    commercial = models.BooleanField("استفادهٔ تجاری مجاز", default=True)
    job_uid = models.UUIDField("کارِ سرورِ پردازش", null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    duration = models.FloatField("مدت (ثانیه)", default=0)
    size = models.PositiveIntegerField(default=0)
    error = models.TextField("خطا", blank=True)
    saved = models.BooleanField("در کتابخانه", default=False, db_index=True)
    #: where it went: [{"script": id, "as": "music" | "ambience", "at": iso}]
    used_in = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "صدای کتابخانه‌ی فروشگاه"
        verbose_name_plural = "کتابخانه‌ی صداهای فروشگاه‌ها"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["store", "kind", "saved"])]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.title or self.text[:40]} · {self.get_status_display()}"

    @property
    def final(self) -> bool:
        return self.status in (self.Status.READY, self.Status.FAILED)
