"""Admin for sound — the one place voice, ambience and noise removal are switched.

Three screens:

* **موتورهای صدا** — every engine for each role (voice, ambience/effects,
  noise removal), local and API side by side. Tick «فعال», set «اولویت»; the
  lowest active number is used and the next takes over when it fails. «آزمایش»
  makes a real sample with the engine and links it, so the choice is made by
  ear, not by name.
* **تنظیمات میکس صدا** — one row: how loud each layer sits under the voice.
* **کتابخانه‌ی صدا** — the real recordings ambience and effects are drawn from.
  Upload your own; it is trimmed and loudness-matched on save.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .audio_models import AudioEngine, AudioMix, SoundClip

logger = logging.getLogger(__name__)

SAMPLE_TEXT_FA = (
    "سلام! این نمونه‌ی صدای گوینده‌ی آپ‌مارکت است. کت اورسایز کرم، با پارچه‌ی نرم "
    "و دوخت تمیز، همین حالا با ارسال رایگان."
)
SAMPLE_TEXT_EN = "Hello! This is a sample of the UpMarket narrator. Free delivery, today only."


def _media_url(path: Path) -> str:
    from services.media import files as media

    return f"{settings.MEDIA_URL}{media.media_rel(path)}"


def _test_dir() -> Path:
    folder = Path(settings.MEDIA_ROOT) / "audio_tests"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _player(url: str) -> str:
    return format_html(
        '<audio controls preload="none" src="{}" style="height:28px;vertical-align:middle"></audio> '
        '<a href="{}" target="_blank">دانلود</a>', url, url,
    )


class AudioEngineForm(forms.ModelForm):
    """Keeps a saved API key when the field is left empty.

    The key is never rendered back into the page (it would sit in the HTML of
    every admin who opens the row). Leaving the box empty keeps the current
    key; typing «-» removes it.
    """

    api_key = forms.CharField(
        label="کلید API", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="خالی بگذارید تا کلید قبلی بماند؛ برای پاک کردن «-» بنویسید.",
    )

    class Meta:
        model = AudioEngine
        fields = "__all__"

    def clean_api_key(self):
        value = (self.cleaned_data.get("api_key") or "").strip()
        if value == "-":
            return ""
        if not value and self.instance and self.instance.pk:
            return self.instance.api_key
        return value


@admin.register(AudioEngine)
class AudioEngineAdmin(admin.ModelAdmin):
    name_en = "Audio engines"
    description = (
        "گوینده، صدای محیط و افکت، و حذف نویز — هرکدام از کجا می‌آید. «فعال» را تیک بزنید "
        "و «اولویت» را بدهید: کمترین عدد اول امتحان می‌شود و اگر کار نکرد، بعدی جایش را "
        "می‌گیرد. «آزمایش» یک نمونه‌ی واقعی می‌سازد تا با گوش انتخاب کنید."
    )
    form = AudioEngineForm
    list_display = [
        "role", "name", "kind", "where", "priority", "is_active", "readiness_badge", "health_badge",
    ]
    list_display_links = ["name"]
    list_editable = ["priority", "is_active"]
    list_filter = ["role", "kind", "is_active"]
    search_fields = ["name", "model_name", "voice_fa"]
    actions = ["test_engine", "make_primary", "activate", "deactivate"]
    readonly_fields = ["readiness_detail", "checked_at", "is_healthy", "last_error", "created_at", "updated_at"]
    ordering = ["role", "priority", "id"]

    fieldsets = [
        ("چه کاری", {
            "fields": ["role", "kind", "name", "is_active", "priority", "readiness_detail"],
            "description": (
                "«اولویت» کمتر یعنی زودتر. می‌توانید موتور آنلاین را اول بگذارید و موتور "
                "آفلاین را پشتش، تا روزی که اینترنت نیست ویدیو بی‌صدا نماند — یا برعکس. "
                "فروشگاهی که سیاستش «فقط لوکال» است، فقط موتورهای لوکال را می‌بیند."
            ),
        }),
        ("اتصال (فقط سرویس‌های API)", {
            "fields": ["base_url", "api_key", "model_name", "timeout_s"],
            "description": (
                "Azure: در «آدرس سرویس» منطقه را بنویسید (مثلاً westeurope). "
                "API سازگار با OpenAI: آدرس پایه تا /v1. ElevenLabs: آدرس را خالی بگذارید. "
                "Piper: در «مدل» نام فایل صدا (مثلاً fa_IR-gyro-medium)."
            ),
        }),
        ("صداها (فقط گوینده)", {
            "fields": ["voice_fa", "voice_fa_female", "voice_en", "voice_en_female"],
            "description": (
                "Edge/Azure: fa-IR-FaridNeural (مرد) و fa-IR-DilaraNeural (زن). "
                "Piper: نام مدل (fa_IR-gyro-medium، fa_IR-ganji-medium، …)؛ صدای زن "
                "فارسی آفلاین: fa_IR-mana-medium (کمی کم‌وضوح‌تر از دیلارای آنلاین). "
                "OpenAI: alloy، onyx، nova، … · ElevenLabs: شناسه‌ی صدا از پنل ElevenLabs."
            ),
        }),
        ("تنظیمات پیشرفته", {
            "fields": ["options", "notes"],
            "classes": ["collapse"],
            "description": (
                "JSON. Piper: {\"sentence_silence\": 0.25} — و فقط اگر لازم شد "
                "length_scale (بزرگ‌تر = کندتر)، noise_scale و noise_w؛ خالی بماند تنظیم خود صدا به کار می‌رود · "
                "OpenAI: {\"instructions\": \"گرم و صمیمی\"} · "
                "DeepFilterNet: {\"atten_lim_db\": 30} · RNNoise: {\"mix\": 0.9}"
            ),
        }),
        ("سلامت", {"fields": ["checked_at", "is_healthy", "last_error"]}),
    ]

    # ---------------------------------------------------------------- columns

    @admin.display(description="اجرا روی")
    def where(self, obj):
        return "🖥️ همین سیستم (آفلاین)" if obj.is_local else "☁️ سرویس بیرونی"

    def _readiness(self, obj):
        from services.audio import engines

        return engines.readiness(engines._from_row(obj))

    @admin.display(description="آماده؟")
    def readiness_badge(self, obj):
        ok, why = self._readiness(obj)
        if ok:
            return format_html('<span style="color:#0a0">● آماده</span>')
        return format_html('<span style="color:#b26b00" title="{}">● {}</span>', why, why[:60])

    @admin.display(description="آمادگی")
    def readiness_detail(self, obj):
        if not obj.pk:
            return "بعد از ذخیره نشان داده می‌شود."
        ok, why = self._readiness(obj)
        return "آماده است." if ok else why

    @admin.display(description="آخرین آزمایش")
    def health_badge(self, obj):
        if obj.is_healthy is None:
            return format_html('<span style="color:#888">آزمایش نشده</span>')
        if obj.is_healthy:
            return format_html('<span style="color:#0a0">● سالم</span>')
        return format_html('<span style="color:#c00" title="{}">● خطا</span>', obj.last_error[:200])

    # ---------------------------------------------------------------- actions

    @admin.action(description="آزمایش — یک نمونه‌ی واقعی بساز")
    def test_engine(self, request, queryset):
        for row in queryset:
            try:
                detail = self._run_test(row)
                row.is_healthy, row.last_error = True, ""
                self.message_user(request, format_html("{}: {}", row.name, detail), messages.SUCCESS)
            except Exception as exc:  # noqa: BLE001 — a failed test is the answer
                row.is_healthy, row.last_error = False, str(exc)[:1000]
                self.message_user(request, f"{row.name}: {exc}"[:500], messages.ERROR)
            row.checked_at = timezone.now()
            row.save(update_fields=["is_healthy", "last_error", "checked_at"])

    def _run_test(self, row) -> str:
        from services.audio import engines

        engine = engines._from_row(row)
        ok, why = engines.readiness(engine)
        if not ok:
            raise RuntimeError(why)
        folder = _test_dir()
        if row.role == AudioEngine.Role.VOICE:
            return self._test_voice(engine, folder)
        if row.role == AudioEngine.Role.SOUND:
            return self._test_sound(engine, folder)
        return self._test_denoise(engine, folder)

    def _test_voice(self, engine, folder: Path) -> str:
        import time

        from services.audio import polish, tts

        parts = []
        for language, text in (("fa", SAMPLE_TEXT_FA), ("en", SAMPLE_TEXT_EN)):
            if not engine.voice(language):
                continue
            provider = tts.build_provider(engine, language)
            started = time.monotonic()
            raw = provider.synthesize(text, folder / f"engine{engine.row_id}_{language}_raw.mp3")
            seconds = time.monotonic() - started
            final = polish.maybe_polish(raw, folder / f"engine{engine.row_id}_{language}.m4a")
            parts.append(format_html(
                "{} ({} ثانیه) {}", "فارسی" if language == "fa" else "انگلیسی",
                f"{seconds:.1f}", _player(_media_url(final)),
            ))
        if not parts:
            raise RuntimeError("هیچ صدایی برای این موتور تعریف نشده")
        return format_html(" · ".join(["{}"] * len(parts)), *parts)

    def _test_sound(self, engine, folder: Path) -> str:
        from services.audio import soundscape

        work = folder / f"sound{engine.row_id}"
        work.mkdir(parents=True, exist_ok=True)
        if engine.kind == "SOUND_LIBRARY":
            picked = soundscape._from_library("rain", "admin-test", work) or next(
                (found for found in (soundscape._from_library(k, "admin-test", work)
                                     for k in soundscape.CATALOGUE) if found), None,
            )
        elif engine.kind == "PROCEDURAL":
            picked = soundscape._procedural("rain", 8.0, work)
        elif engine.kind == "OPENVERSE":
            imported = soundscape.fetch_openverse("rain", limit=1, work=work)
            picked = soundscape._from_library("rain", "admin-test", work) if imported else None
        else:
            picked = soundscape._elevenlabs(engine, "rain", 6.0, work)
        if picked is None:
            raise RuntimeError("صدایی ساخته یا پیدا نشد")
        copy = folder / f"engine{engine.row_id}_{picked.key}.m4a"
        copy.write_bytes(Path(picked.path).read_bytes())
        return format_html("{} — {} {}", soundscape.CATALOGUE[picked.key].label,
                           picked.title, _player(_media_url(copy)))

    def _test_denoise(self, engine, folder: Path) -> str:
        """A known voice under a known noise, cleaned, with both numbers."""
        from services.audio import denoise, engines, tts
        from services.video.ffmpeg import FFMPEG, _run

        clean_voice = folder / "denoise_voice.wav"
        if not clean_voice.exists():
            voices = engines.resolve(engines.VOICE).engines
            if not voices:
                raise RuntimeError("برای آزمایش، یک گوینده‌ی آماده لازم است")
            spoken = tts.build_provider(voices[0], "fa").synthesize(
                SAMPLE_TEXT_FA, folder / "denoise_voice_raw.mp3",
            )
            _run([FFMPEG, "-y", "-i", str(spoken), "-ar", "48000", "-ac", "1", str(clean_voice)])
        noisy = folder / "denoise_noisy.wav"
        # Voice plus a fridge-like hum and street-like pink noise.
        _run([FFMPEG, "-y", "-i", str(clean_voice),
              "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.05:r=48000",
              "-f", "lavfi", "-i", "sine=f=100:r=48000",
              "-filter_complex", "[2:a]volume=0.03[hum];[0:a][1:a][hum]amix=inputs=3:duration=first:normalize=0",
              "-ac", "1", str(noisy)])

        original = engines._from_row(AudioEngine.objects.get(pk=engine.row_id))
        runner = denoise._RUNNERS[original.kind]
        work = folder / f"denoise{engine.row_id}"
        work.mkdir(parents=True, exist_ok=True)
        wav_in = denoise._to_wav(noisy, work / "in.wav")
        out = folder / f"engine{engine.row_id}_denoised.wav"
        runner(original, wav_in, out, 1.0)
        before, after = denoise.measure(wav_in, work), denoise.measure(out, work)
        return format_html(
            "فاصله‌ی صدا از نویز از {} به {} دسی‌بل رسید · قبل {} · بعد {}",
            before.get("snr_db"), after.get("snr_db"),
            _player(_media_url(noisy)), _player(_media_url(out)),
        )

    @admin.action(description="این را اول کن (اولویت اول در نقش خودش)")
    def make_primary(self, request, queryset):
        for row in queryset:
            others = AudioEngine.objects.filter(role=row.role).exclude(pk=row.pk).order_by("priority", "id")
            row.priority, row.is_active = 1, True
            row.save(update_fields=["priority", "is_active", "updated_at"])
            for position, other in enumerate(others, start=2):
                if other.priority != position * 10:
                    other.priority = position * 10
                    other.save(update_fields=["priority", "updated_at"])
            self.message_user(request, f"«{row.name}» حالا اولین {row.get_role_display()} است.")

    @admin.action(description="فعال کردن")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} موتور فعال شد.")

    @admin.action(description="غیرفعال کردن")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} موتور غیرفعال شد.")


@admin.register(AudioMix)
class AudioMixAdmin(admin.ModelAdmin):
    name_en = "Audio mix"
    description = (
        "بلندی هر لایه‌ی صدا زیر صدای گوینده، و اینکه کدام لایه روشن باشد. همه‌ی اعداد "
        "«بلندی هدف» به LUFS هستند، نه افزایش صدا: هر لایه جدا به عدد خودش می‌رسد و بعد "
        "روی هم می‌آید — گوینده بالا، افکت زیرش، صدای محیط زیرتر و پس‌زمینه‌ی آپلودی "
        "فروشگاه از همه پایین‌تر."
    )
    fieldsets = [
        ("گوینده", {"fields": ["voice_lufs", "polish_voice"]}),
        ("صدای محیط و افکت", {
            "fields": ["ambience_enabled", "ambience_lufs", "effects_enabled", "effects_lufs"],
            "description": "صدای محیط باید «حس» شود، نه «شنیده». پیش‌فرض ۲۰ دسی‌بل زیر گوینده است.",
        }),
        ("پس‌زمینه‌ی آپلودی فروشگاه", {
            "fields": ["background_lufs", "background_ceiling_lufs", "duck_db"],
            "description": (
                "موسیقی یا صدایی که خود فروشگاه آپلود می‌کند. پایین‌ترین لایه است و هر "
                "وقت گوینده حرف می‌زند به اندازه‌ی «پایین آمدن» آرام‌تر می‌شود."
            ),
        }),
        ("حذف نویز", {"fields": ["suggest_denoise", "min_snr_db"]}),
    ]

    def has_add_permission(self, request):
        return not AudioMix.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class SoundClipForm(forms.ModelForm):
    category = forms.ChoiceField(label="دسته")

    class Meta:
        model = SoundClip
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from services.audio.soundscape import CATALOGUE

        self.fields["category"].choices = [
            (k.key, f"{k.label} ({'صدای محیط' if k.kind == 'bed' else 'افکت'})")
            for k in CATALOGUE.values()
        ]


@admin.register(SoundClip)
class SoundClipAdmin(admin.ModelAdmin):
    name_en = "Sound library"
    description = (
        "صداهای واقعی‌ای که صدای محیط و افکت‌های ویدیو از آن‌ها برداشته می‌شود — همه روی "
        "همین سیستم و آفلاین. فایل خودتان را هم می‌توانید آپلود کنید: موقع ذخیره، سکوت "
        "ابتدا و انتهایش بریده و بلندی‌اش یکسان می‌شود."
    )
    form = SoundClipForm
    list_display = ["category_label", "title", "duration", "loudness_lufs", "origin", "licence",
                    "is_active", "player"]
    list_filter = ["category", "origin", "is_active", "licence"]
    list_editable = ["is_active"]
    search_fields = ["title", "creator", "category"]
    readonly_fields = ["duration", "loudness_lufs", "player", "created_at", "updated_at"]
    actions = ["fetch_more"]
    fieldsets = [
        (None, {"fields": ["category", "title", "file", "player", "is_active"]}),
        ("منبع و مجوز", {"fields": ["origin", "licence", "creator", "source_url", "attribution"]}),
        ("اندازه‌گیری", {"fields": ["duration", "loudness_lufs", "quality_note"]}),
    ]

    @admin.display(description="دسته")
    def category_label(self, obj):
        from services.audio.soundscape import CATALOGUE

        kind = CATALOGUE.get(obj.category)
        return kind.label if kind else obj.category

    @admin.display(description="پخش")
    def player(self, obj):
        if not obj.file:
            return "—"
        return format_html(
            '<audio controls preload="none" src="{}" style="height:28px"></audio>', obj.file.url,
        )

    def save_model(self, request, obj, form, change):
        """Uploaded files go through the same preparation as downloaded ones."""
        super().save_model(request, obj, form, change)
        if "file" not in form.changed_data or not obj.file:
            return
        from services.audio import soundscape

        import tempfile

        from django.core.files import File

        from services.media import files as media

        try:
            old_name = obj.file.name
            # Prepared in a temp folder and saved back through the storage, so
            # this works the same on local disk and on S3.
            with tempfile.TemporaryDirectory(prefix="clip_") as folder, \
                    media.reading(obj.file) as source:
                prepared = Path(folder) / f"{Path(old_name).stem}.m4a"
                duration, loudness = soundscape.prepare_file(source, obj.category, prepared)
                with prepared.open("rb") as handle:
                    obj.file.save(f"{obj.category}/{Path(old_name).stem}.m4a", File(handle), save=False)
            obj.duration, obj.loudness_lufs = duration, loudness
            obj.save()
            if old_name != obj.file.name:
                obj.file.storage.delete(old_name)
            self.message_user(request, f"آماده شد: {duration:.1f} ثانیه، بلندی یکسان‌شده.")
        except Exception as exc:  # noqa: BLE001
            obj.is_active = False
            obj.quality_note = str(exc)[:300]
            obj.save(update_fields=["is_active", "quality_note", "updated_at"])
            self.message_user(request, f"این فایل آماده نشد و غیرفعال ماند: {exc}", messages.ERROR)

    @admin.action(description="دو صدای دیگر برای همین دسته‌ها از Freesound (CC0) بیاور")
    def fetch_more(self, request, queryset):
        from services.audio import soundscape

        categories = sorted(set(queryset.values_list("category", flat=True)))
        total = 0
        for category in categories:
            total += len(soundscape.fetch_openverse(category, limit=2))
        self.message_user(request, f"{total} صدای تازه به کتابخانه اضافه شد.")
