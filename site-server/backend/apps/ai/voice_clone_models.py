"""Cloned voices — a shop's own narrator, made from someone reading a few sentences.

The recordings and the consent live HERE, on the site; the voice itself is built
on a processing node (PersianAiKit Voice, `voice.clone` job) because the site
server has no voice engine of that kind. The node keeps its own copy under
`data/voices/<node_voice_id>`; if that copy is lost (another node, a wiped
folder), the site still has every accepted clip and rebuilds it on the fly
(`services.audio.voice_clone`, «restore»).

Consent is not a checkbox state that can be flipped later: who agreed, to what
exact sentence, when and from where is stored with the voice, and nothing is
sent to a node without it. Recordings of a person's voice are personal data, so
they are kept outside MEDIA_ROOT (nginx serves that folder publicly) and are
streamed only through the store-scoped API.
"""
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class ClonedVoice(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "ضبطِ نمونه‌ها"
        BUILDING = "BUILDING", "در حالِ ساخت"
        READY = "READY", "آماده"
        FAILED = "FAILED", "ساخته نشد"

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="cloned_voices",
                              verbose_name="فروشگاه")
    name = models.CharField("نامِ صدا", max_length=60)
    person = models.CharField("صاحبِ صدا", max_length=120)
    purpose = models.CharField("کاربرد", max_length=300, blank=True)

    # ---- consent (required before a single clip is stored)
    consent_text = models.TextField("متنِ رضایت‌نامه")
    consent_at = models.DateTimeField("زمانِ رضایت")
    consent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name="ثبت‌کنندهٔ رضایت")
    consent_ip = models.GenericIPAddressField("IP ِ ثبتِ رضایت", null=True, blank=True)

    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.DRAFT)
    engine = models.CharField("موتور", max_length=40, default="pocket")
    engine_license = models.CharField("مجوزِ موتور", max_length=80, default="CC-BY-NC-4.0")
    #: the processing node that holds the built voice, and the voice's id in its PersianAiKit
    node_name = models.CharField("سرورِ پردازش", max_length=60, blank=True)
    node_voice_id = models.CharField("شناسه روی سرورِ پردازش", max_length=80, blank=True)
    build_job = models.UUIDField("کارِ ساخت", null=True, blank=True)
    #: +1 on every successful build — part of each speech job, so a rebuilt voice never reuses old audio
    revision = models.PositiveIntegerField("نسخه", default=0)
    report = models.JSONField("گزارشِ ساخت", default=dict, blank=True)
    error = models.TextField("خطا", blank=True)
    built_at = models.DateTimeField("زمانِ ساخت", null=True, blank=True)

    class Meta:
        verbose_name = "صدای کلون‌شده"
        verbose_name_plural = "صداهای کلون‌شده"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.person}) · {self.get_status_display()}"

    @property
    def usable(self) -> bool:
        """Can narrate: built at least once (a rebuild in progress keeps the previous voice on the node)."""
        return bool(self.node_voice_id) and self.revision > 0 and self.status in (self.Status.READY, self.Status.BUILDING)


class ClonedVoiceClip(TimeStampedModel):
    """One sentence read aloud: the audio (normalised WAV on disk) and both checks — the site's and the node's."""

    class Source(models.TextChoices):
        RECORD = "record", "ضبط در مرورگر"
        UPLOAD = "upload", "فایلِ آپلودی"

    voice = models.ForeignKey(ClonedVoice, on_delete=models.CASCADE, related_name="clips")
    #: the sentence number in the reading script (1…); custom sentences start at 1001
    index = models.PositiveIntegerField("شماره")
    text = models.TextField("متنِ خوانده‌شده")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.RECORD)
    original_name = models.CharField(max_length=200, blank=True)
    seconds = models.FloatField(default=0)
    snr = models.FloatField(null=True, blank=True)
    level = models.FloatField(null=True, blank=True)
    clipped = models.FloatField(default=0)
    ok = models.BooleanField("پذیرفته (وارسیِ سایت)", default=False)
    message = models.CharField(max_length=400, blank=True)
    #: the kit's verdict at the last build: {ok, message, heard, wer, snr}
    node = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "نمونهٔ صدا"
        verbose_name_plural = "نمونه‌های صدا"
        ordering = ["index"]
        unique_together = [("voice", "index")]

    def __str__(self):
        return f"{self.voice_id}#{self.index}"
