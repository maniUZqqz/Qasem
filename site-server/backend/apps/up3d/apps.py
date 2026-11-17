import re

from django.apps import AppConfig

_PERSIAN = re.compile("[\u0600-\u06ff]")


class Up3dConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.up3d"
    label = "up3d"
    verbose_name = "ویدیوی سه‌بعدی"

    def ready(self):
        # the 3D engine's voice-over goes through the same Persian pronunciation layer as every other voice (numbers, dates,
        # Latin words as words; the engine itself stays independent of NM: it only has an optional text hook)
        try:
            from services.audio import pronounce
            from up3d import tts as up3d_tts
        except Exception:  # noqa: BLE001
            return

        def _persian_text(text, provider, voice):
            if not _PERSIAN.search(text or ""):
                return text
            return pronounce.text_for(text, "plain")

        up3d_tts.TEXT_FILTER = _persian_text
