"""Where every sound in a video comes from — chosen in the admin, not in code.

Three jobs, three kinds of engine, one table:

* **VOICE** — the narrator. Text in, a human voice out.
* **SOUND** — everything that is not a person talking: rain on a window,
  footsteps on a wooden floor, a café behind the counter, the whoosh on a
  product reveal.
* **DENOISE** — taking the hum, hiss and traffic out of a voice the shop
  recorded on a phone.

Each role has several engines, local and remote, and the operator decides
which one is used by ticking «فعال» and setting «اولویت». Engines are tried in
priority order, and the next one takes over when one fails — so a local,
offline engine can sit behind an online one and a video still gets its voice
the day the internet is down. The same list is what the per-store data
policy filters: a shop on «فقط لوکال» only ever reaches the engines marked
local, whatever order they are in.

The mix itself — how loud each layer sits under the voice — is `AudioMix`,
one row, also in the admin.
"""
from django.db import models

from apps.common.models import TimeStampedModel


class AudioEngine(TimeStampedModel):
    """One way to make (or clean) a sound, and its place in the queue."""

    class Role(models.TextChoices):
        VOICE = "VOICE", "گوینده (متن به گفتار)"
        SOUND = "SOUND", "صدای محیط و افکت"
        DENOISE = "DENOISE", "حذف نویز"

    class Kind(models.TextChoices):
        # ---- voice ------------------------------------------------------
        NODE_MOSS = "NODE_MOSS", "MOSS-TTS فارسی — سرورِ پردازش، تجاری مجاز (Apache-2.0)"
        PIPER = "PIPER", "Piper — لوکال، آفلاین، رایگان، تجاری مجاز"
        EDGE = "EDGE", "Edge TTS — آنلاین، غیررسمی (بدونِ مجوزِ تجاریِ مایکروسافت)"
        AZURE = "AZURE", "Azure Speech — API پولی (مایکروسافت)"
        OPENAI_TTS = "OPENAI_TTS", "API گفتار سازگار با OpenAI"
        ELEVENLABS = "ELEVENLABS", "ElevenLabs — API پولی"
        GTTS = "GTTS", "Google Translate TTS — فقط انگلیسی، غیررسمی"
        # ---- sound ------------------------------------------------------
        SOUND_LIBRARY = "SOUND_LIBRARY", "کتابخانه‌ی صدای واقعی — لوکال، آفلاین"
        NODE_SFX = "NODE_SFX", "MOSS-SoundEffect — سرورِ پردازش، تجاری مجاز (Apache-2.0)"
        PROCEDURAL = "PROCEDURAL", "ساخت صدای محیط با کد — لوکال، آفلاین"
        OPENVERSE = "OPENVERSE", "Openverse / Freesound (CC0) — آنلاین، رایگان"
        ELEVENLABS_SFX = "ELEVENLABS_SFX", "ElevenLabs Sound Effects — API پولی"
        # ---- denoise ----------------------------------------------------
        DEEPFILTER = "DEEPFILTER", "DeepFilterNet — لوکال، بهترین کیفیت"
        RNNOISE = "RNNOISE", "RNNoise — لوکال، سریع"
        SPECTRAL = "SPECTRAL", "noisereduce — لوکال"
        AFFTDN = "AFFTDN", "فیلتر FFT ساده — لوکال"

    #: Which kinds run on our own machine. Everything else sends data out —
    #: the narration text, a search phrase, a customer's recording.
    #: NODE_* run on our own processing server: nothing leaves the company either.
    LOCAL_KINDS = {
        Kind.NODE_MOSS, Kind.NODE_SFX,
        Kind.PIPER, Kind.SOUND_LIBRARY, Kind.PROCEDURAL,
        Kind.DEEPFILTER, Kind.RNNOISE, Kind.SPECTRAL, Kind.AFFTDN,
    }

    #: Which kinds belong to which role. The admin form refuses a mismatch
    #: rather than saving a voice engine that is asked to remove noise.
    ROLE_KINDS = {
        Role.VOICE: {Kind.NODE_MOSS, Kind.PIPER, Kind.EDGE, Kind.AZURE, Kind.OPENAI_TTS, Kind.ELEVENLABS, Kind.GTTS},
        Role.SOUND: {Kind.SOUND_LIBRARY, Kind.NODE_SFX, Kind.PROCEDURAL, Kind.OPENVERSE, Kind.ELEVENLABS_SFX},
        Role.DENOISE: {Kind.DEEPFILTER, Kind.RNNOISE, Kind.SPECTRAL, Kind.AFFTDN},
    }

    role = models.CharField("نقش", max_length=8, choices=Role.choices)
    kind = models.CharField("موتور", max_length=16, choices=Kind.choices)
    name = models.CharField("نام", max_length=80)
    is_active = models.BooleanField("فعال", default=True)
    priority = models.PositiveSmallIntegerField(
        "اولویت", default=100, help_text="کمتر = زودتر امتحان می‌شود",
    )

    base_url = models.CharField(
        "آدرس سرویس", max_length=255, blank=True,
        help_text="برای Azure منطقه (مثلاً westeurope) یا آدرس کامل؛ برای API "
                  "سازگار با OpenAI آدرس پایه (…/v1). برای موتورهای لوکال خالی.",
    )
    api_key = models.CharField(
        "کلید API", max_length=255, blank=True,
        help_text="هرگز در پنل یا API برگردانده نمی‌شود.",
    )
    model_name = models.CharField(
        "مدل", max_length=120, blank=True,
        help_text="Piper: نام فایل مدل (fa_IR-amir-medium) · OpenAI: gpt-4o-mini-tts · "
                  "ElevenLabs: eleven_v3 · RNNoise: sh یا bd",
    )
    voice_fa = models.CharField(
        "صدای فارسی (مرد)", max_length=120, blank=True,
        help_text="Edge/Azure: fa-IR-FaridNeural · OpenAI: onyx · ElevenLabs: شناسه‌ی صدا",
    )
    voice_fa_female = models.CharField("صدای فارسی (زن)", max_length=120, blank=True)
    voice_en = models.CharField("صدای انگلیسی (مرد)", max_length=120, blank=True)
    voice_en_female = models.CharField("صدای انگلیسی (زن)", max_length=120, blank=True)
    timeout_s = models.PositiveIntegerField("حداکثر زمان (ثانیه)", default=120)
    options = models.JSONField(
        "تنظیمات پیشرفته", default=dict, blank=True,
        help_text="JSON. Piper: length_scale، noise_scale، noise_w، sentence_silence · "
                  "DeepFilterNet: atten_lim_db · ElevenLabs: stability، similarity_boost",
    )
    notes = models.TextField("یادداشت", blank=True)

    checked_at = models.DateTimeField("آخرین آزمایش", null=True, blank=True)
    is_healthy = models.BooleanField("سالم", null=True, blank=True)
    last_error = models.TextField("آخرین خطا", blank=True)

    class Meta:
        verbose_name = "موتور صدا"
        verbose_name_plural = "موتورهای صدا"
        ordering = ["role", "priority", "id"]

    def __str__(self):
        return f"{self.get_role_display()} · {self.name}"

    @property
    def is_local(self) -> bool:
        return self.kind in self.LOCAL_KINDS

    def clean(self):
        from django.core.exceptions import ValidationError

        allowed = self.ROLE_KINDS.get(self.role, set())
        if self.kind not in allowed:
            raise ValidationError({
                "kind": f"«{self.get_kind_display()}» برای نقش «{self.get_role_display()}» نیست.",
            })


class AudioMix(TimeStampedModel):
    """How loud each layer sits, and which layers are on. One row.

    Every level is a loudness TARGET in LUFS, not a gain. A gain applied to a
    file of unknown loudness means nothing — the same "-20 dB" is a whisper on
    one recording and a shout on another. Each layer is normalised to its own
    target and then summed, so the order of these numbers IS the order a
    listener hears: voice on top, effects under it, ambience under those, and
    the shop's own background lowest of all.
    """

    voice_lufs = models.FloatField(
        "بلندی صدای گوینده (LUFS)", default=-16.0,
        help_text="استاندارد شبکه‌های اجتماعی حدود ۱۴- تا ۱۶- است.",
    )
    polish_voice = models.BooleanField(
        "پرداخت صدای گوینده", default=True,
        help_text="حذف غرش بم، نرم‌کردن «س» و «ش»، فشرده‌سازی ملایم و یکسان‌سازی "
                  "بلندی — برای اینکه صدا مثل ضبط استودیو بنشیند نه خروجی خام موتور.",
    )
    ambience_enabled = models.BooleanField("صدای محیط (باران، خیابان، کافه…)", default=True)
    ambience_lufs = models.FloatField(
        "بلندی صدای محیط (LUFS)", default=-36.0,
        help_text="خیلی پایین‌تر از گوینده؛ فقط باید «حس» شود.",
    )
    effects_enabled = models.BooleanField("افکت‌های لحظه‌ای (قدم، در، ووش…)", default=True)
    effects_lufs = models.FloatField("بلندی افکت‌ها (LUFS)", default=-26.0)
    background_lufs = models.FloatField(
        "بلندی پس‌زمینه‌ی آپلودی فروشگاه (LUFS)", default=-38.0,
        help_text="پایین‌ترین لایه: موسیقی یا صدایی که خود فروشگاه آپلود می‌کند، "
                  "زیر همه‌چیز و بدون مزاحمت برای گوینده.",
    )
    background_ceiling_lufs = models.FloatField(
        "بیشترین بلندی مجاز پس‌زمینه (LUFS)", default=-30.0,
        help_text="هر تنظیمی که فروشگاه بدهد، از این بلندتر نمی‌شود.",
    )
    duck_db = models.FloatField(
        "پایین آمدن پس‌زمینه‌ها وقتی گوینده حرف می‌زند (dB)", default=9.0,
    )
    suggest_denoise = models.BooleanField(
        "پیشنهاد خودکار حذف نویز برای ویدیوی آپلودی", default=True,
    )
    min_snr_db = models.FloatField(
        "حداقل فاصله‌ی صدا از نویز (dB)", default=30.0,
        help_text="اگر صدای ضبط‌شده کمتر از این از نویز زمینه بلندتر باشد، "
                  "حذف نویز پیشنهاد می‌شود.",
    )

    class Meta:
        verbose_name = "تنظیمات میکس صدا"
        verbose_name_plural = "تنظیمات میکس صدا"

    def __str__(self):
        return "تنظیمات میکس صدا"

    @classmethod
    def current(cls) -> "AudioMix":
        """The one row, created with defaults the first time it is asked for."""
        row = cls.objects.order_by("id").first()
        if row is None:
            row = cls.objects.create()
        return row


class SoundClip(TimeStampedModel):
    """One real recording in the local sound library.

    Rows rather than a folder listing, so the admin can browse, disable or
    add sounds, and so every clip carries where it came from and under what
    licence — a sound in a published ad is a claim that we were allowed to
    use it.
    """

    class Origin(models.TextChoices):
        OPENVERSE = "OPENVERSE", "Freesound از طریق Openverse"
        UPLOAD = "UPLOAD", "آپلود مدیر"
        ELEVENLABS = "ELEVENLABS", "ساخته‌شده با ElevenLabs"
        PROCEDURAL = "PROCEDURAL", "ساخته‌شده با کد"
        MOSS = "MOSS", "ساخته‌شده با MOSS-SoundEffect"

    category = models.CharField("دسته", max_length=40, db_index=True)
    title = models.CharField("عنوان", max_length=200, blank=True)
    file = models.FileField("فایل", upload_to="sound_library/")
    duration = models.FloatField("مدت (ثانیه)", default=0)
    loudness_lufs = models.FloatField("بلندی (LUFS)", null=True, blank=True)
    origin = models.CharField("منبع", max_length=12, choices=Origin.choices, default=Origin.UPLOAD)
    licence = models.CharField("مجوز", max_length=40, blank=True)
    creator = models.CharField("سازنده", max_length=200, blank=True)
    source_url = models.URLField("نشانی منبع", blank=True, max_length=500)
    attribution = models.CharField("متن ذکر منبع", max_length=400, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    quality_note = models.CharField("یادداشت کیفیت", max_length=300, blank=True)

    class Meta:
        verbose_name = "صدای کتابخانه"
        verbose_name_plural = "کتابخانه‌ی صدا"
        ordering = ["category", "-duration"]

    def __str__(self):
        return f"{self.category} · {self.title or self.file.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.write_sidecar()

    def write_sidecar(self) -> None:
        """Everything the row knows, in a JSON file beside the audio.

        The library folder is tracked in git; the database is not. The
        sidecar is what lets another machine rebuild the rows
        (`audio_setup --reindex`) — including a clip the admin switched off,
        which would otherwise come back on.
        """
        import json
        from pathlib import Path

        if not self.file:
            return
        try:
            audio = Path(self.file.path)
        except Exception:  # noqa: BLE001 — shared storage has no local path
            return
        if not audio.exists():
            return
        payload = {
            "category": self.category, "title": self.title, "origin": self.origin,
            "licence": self.licence, "creator": self.creator, "source_url": self.source_url,
            "attribution": self.attribution, "is_active": self.is_active,
            "quality_note": self.quality_note,
        }
        try:
            audio.with_suffix(".json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8",
            )
        except OSError:
            pass
