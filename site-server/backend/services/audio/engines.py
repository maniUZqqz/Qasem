"""Which engine answers, for voice, sound and noise removal.

Business code asks for a role — "I need a voice", "I need rain", "clean this
recording" — and gets an ordered list of engines to try. It never learns
whether the answer came from a model on this machine or from an API, which is
the whole point: the operator switches between them in the admin
(`apps.ai.AudioEngine`), with no code change and no restart.

Three filters decide the list, in this order:

1. **The admin.** Active rows, lowest priority number first. When the table
   has no rows for a role at all (a fresh install before migrations seeded
   it, or a test database), the defaults below apply, so an untouched system
   still speaks.
2. **The store's data policy.** A shop on «فقط لوکال» never reaches an engine
   that sends its text or recording off this machine. If that leaves nothing,
   the error says which local engine to turn on — not just "no provider".
3. **Readiness.** An engine whose model file is not downloaded, whose binary is
   missing or whose API key is empty is skipped with a reason. It stays in the
   admin list, marked, so the operator can see why it is not being used.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

VOICE = "VOICE"
SOUND = "SOUND"
DENOISE = "DENOISE"

LOCAL_KINDS = {
    "PIPER", "SOUND_LIBRARY", "PROCEDURAL", "DEEPFILTER", "RNNOISE", "SPECTRAL", "AFFTDN",
}


class NoEngine(Exception):
    """No engine can serve this role right now. Always says why, in Persian."""


@dataclass
class Engine:
    """One usable engine, resolved from an admin row or from the defaults."""

    role: str
    kind: str
    name: str
    priority: int = 100
    base_url: str = ""
    api_key: str = ""
    model_name: str = ""
    voice_fa: str = ""
    voice_fa_female: str = ""
    voice_en: str = ""
    voice_en_female: str = ""
    timeout_s: int = 120
    options: dict = field(default_factory=dict)
    row_id: int | None = None

    @property
    def is_local(self) -> bool:
        return self.kind in LOCAL_KINDS

    def voice(self, language: str = "fa", gender: str = "male") -> str:
        """The voice id for a language and gender, falling back sensibly."""
        if language == "en":
            chosen = self.voice_en_female if gender == "female" else self.voice_en
            return chosen or self.voice_en or self.voice_en_female
        chosen = self.voice_fa_female if gender == "female" else self.voice_fa
        return chosen or self.voice_fa or self.voice_fa_female

    def has_voice(self, language: str, gender: str) -> bool:
        if language == "en":
            return bool(self.voice_en_female if gender == "female" else self.voice_en)
        return bool(self.voice_fa_female if gender == "female" else self.voice_fa)


# ------------------------------------------------------------------ paths


def models_dir() -> Path:
    """Where downloaded engine files live (Piper voices, DeepFilterNet).

    Outside `backend/` and ignored by git like the bundled ffmpeg: they are
    re-downloadable dependencies, hundreds of megabytes, and git never forgets
    a binary. `manage.py audio_setup` fills it.
    """
    configured = settings.UPMARKET_AI.get("AUDIO_MODELS_DIR")
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR).parent / "models"


def piper_model_path(name: str) -> Path:
    name = (name or "fa_IR-gyro-medium").removesuffix(".onnx")
    return models_dir() / "piper" / f"{name}.onnx"


def deepfilter_binary() -> Path | None:
    configured = settings.UPMARKET_AI.get("DEEPFILTER_BIN")
    if configured and Path(configured).is_file():
        return Path(configured)
    folder = models_dir() / "deepfilter"
    # Exact names only: a glob also matched the `.part` of an interrupted
    # download, and running half an executable is not a fallback.
    for name in ("deep-filter.exe", "deep-filter"):
        candidate = folder / name
        if candidate.is_file() and candidate.stat().st_size > 1_000_000:
            return candidate
    found = shutil.which("deep-filter")
    return Path(found) if found else None


def rnnoise_model(name: str = "sh") -> Path:
    """Bundled RNNoise weights (300 KB each, tracked in git).

    `sh` is trained for speech in recordings — a person talking into a phone,
    which is what a shop's own video is. `bd` also keeps non-speech human
    sounds (laughter, breath) and suits livelier footage.
    """
    name = (name or "sh").strip().lower()
    return Path(__file__).resolve().parent / "rnnoise" / f"{name}.rnnn"


# -------------------------------------------------------------- readiness


def readiness(engine: Engine) -> tuple[bool, str]:
    """Can this engine run right now? (ready, reason when not)."""
    kind = engine.kind
    try:
        if kind == "PIPER":
            try:
                import piper  # noqa: F401
            except ImportError:
                return False, "بسته‌ی piper-tts نصب نیست — pip install piper-tts"
            # The main voice, with its config: Piper cannot load an .onnx
            # without the .json beside it, and a half-finished download
            # leaves exactly that. (A missing English voice is not fatal —
            # that narration fails over to the next engine at synthesis.)
            name = engine.model_name or engine.voice_fa or engine.voice_en
            if not name:
                return False, "هیچ صدایی برای این موتور تعریف نشده"
            model = piper_model_path(name)
            if not model.exists() or not model.with_suffix(".onnx.json").exists():
                return False, (
                    f"مدل صدای «{model.stem}» کامل دانلود نشده — "
                    "python manage.py audio_setup --voices"
                )
            return True, ""
        if kind == "EDGE":
            try:
                import edge_tts  # noqa: F401
            except ImportError:
                return False, "بسته‌ی edge-tts نصب نیست"
            return True, ""
        if kind == "GTTS":
            try:
                import gtts  # noqa: F401
            except ImportError:
                return False, "بسته‌ی gTTS نصب نیست"
            return True, ""
        if kind in ("AZURE", "OPENAI_TTS", "ELEVENLABS", "ELEVENLABS_SFX"):
            if not engine.api_key:
                return False, "کلید API وارد نشده"
            if kind == "AZURE" and not engine.base_url:
                return False, "منطقه‌ی Azure (مثلاً westeurope) وارد نشده"
            if kind == "OPENAI_TTS" and not engine.base_url:
                return False, "آدرس پایه‌ی API وارد نشده"
            return True, ""
        if kind == "SOUND_LIBRARY":
            from apps.ai.models import SoundClip

            if not SoundClip.objects.filter(is_active=True).exists():
                return False, "کتابخانه‌ی صدا خالی است — python manage.py audio_setup --library"
            return True, ""
        if kind in ("PROCEDURAL", "OPENVERSE", "AFFTDN"):
            return True, ""
        if kind == "DEEPFILTER":
            if deepfilter_binary() is None:
                return False, "DeepFilterNet دانلود نشده — python manage.py audio_setup --denoise"
            return True, ""
        if kind == "RNNOISE":
            model = rnnoise_model(engine.model_name or "sh")
            if not model.exists():
                return False, f"مدل RNNoise «{model.name}» پیدا نشد"
            return True, ""
        if kind == "SPECTRAL":
            try:
                import noisereduce  # noqa: F401
                import soundfile  # noqa: F401
            except ImportError:
                return False, "بسته‌ی noisereduce یا soundfile نصب نیست"
            return True, ""
    except Exception as exc:  # noqa: BLE001 — readiness must never raise
        return False, str(exc)[:200]
    return False, f"موتور «{kind}» شناخته نشد"


# --------------------------------------------------------------- defaults


def _defaults(role: str) -> list[Engine]:
    """What an install with an empty table uses. Mirrors the seeded rows."""
    conf = settings.UPMARKET_AI
    if role == VOICE:
        edge = Engine(
            role=VOICE, kind="EDGE", name="Edge TTS", priority=10,
            voice_fa=conf.get("TTS_VOICE_FA", "fa-IR-FaridNeural"),
            voice_fa_female="fa-IR-DilaraNeural",
            voice_en=conf.get("TTS_VOICE_EN", "en-US-AndrewNeural"),
            voice_en_female="en-US-AvaNeural",
        )
        piper = Engine(
            role=VOICE, kind="PIPER", name="Piper (آفلاین)", priority=20,
            model_name="fa_IR-gyro-medium", voice_fa="fa_IR-gyro-medium",
            voice_fa_female="fa_IR-mana-medium",
            voice_en="en_US-hfc_male-medium", voice_en_female="en_US-hfc_female-medium",
        )
        chosen = str(conf.get("TTS_PROVIDER", "edge")).lower()
        if chosen == "piper":
            return [piper, edge]
        if chosen == "gtts":
            return [Engine(role=VOICE, kind="GTTS", name="gTTS", priority=10)]
        return [edge, piper]
    if role == SOUND:
        return [
            Engine(role=SOUND, kind="SOUND_LIBRARY", name="کتابخانه‌ی صدا", priority=10),
            Engine(role=SOUND, kind="PROCEDURAL", name="ساخت با کد", priority=20),
            Engine(role=SOUND, kind="OPENVERSE", name="Openverse", priority=30),
        ]
    if role == DENOISE:
        return [
            Engine(role=DENOISE, kind="DEEPFILTER", name="DeepFilterNet", priority=10,
                   options={"atten_lim_db": 30}),
            Engine(role=DENOISE, kind="RNNOISE", name="RNNoise", priority=20, model_name="sh"),
            Engine(role=DENOISE, kind="AFFTDN", name="FFT", priority=40),
        ]
    return []


def _from_row(row) -> Engine:
    return Engine(
        role=row.role, kind=row.kind, name=row.name, priority=row.priority,
        base_url=row.base_url, api_key=row.api_key, model_name=row.model_name,
        voice_fa=row.voice_fa, voice_fa_female=row.voice_fa_female,
        voice_en=row.voice_en, voice_en_female=row.voice_en_female,
        timeout_s=row.timeout_s, options=dict(row.options or {}), row_id=row.pk,
    )


def configured(role: str) -> list[Engine]:
    """Active engines for a role, in priority order, before any filtering."""
    try:
        from apps.ai.models import AudioEngine

        rows = list(AudioEngine.objects.filter(role=role, is_active=True).order_by("priority", "id"))
        if rows:
            return [_from_row(row) for row in rows]
        if AudioEngine.objects.filter(role=role).exists():
            # Rows exist and every one is switched off: the operator turned the
            # role off on purpose. Honour it rather than falling back.
            return []
    except Exception as exc:  # noqa: BLE001 — before migrations / no database
        logger.debug("AudioEngine table unavailable: %s", exc)
    return _defaults(role)


def local_only(store) -> bool:
    """Must this work stay on this machine?

    No store means the platform default (an operator can make that
    LOCAL_ONLY), not "anything goes". And a policy that cannot be read is
    treated as the strict one: sending a shop's script to Microsoft because a
    database query failed is the one mistake here that cannot be taken back.
    """
    try:
        from services.ai import gateway

        return gateway.policy_for(store).mode == gateway.LOCAL_ONLY
    except Exception as exc:  # noqa: BLE001 — fail closed
        logger.warning("Could not read the data policy, keeping audio local: %s", exc)
        return True


@dataclass
class Resolution:
    """The engines to try, and why the others were left out."""

    engines: list[Engine]
    skipped: list[tuple[Engine, str]]

    def explain(self) -> str:
        return "؛ ".join(f"{e.name}: {why}" for e, why in self.skipped)


def resolve(role: str, store=None, *, require_local: bool | None = None) -> Resolution:
    """Engines to try for this role, filtered by policy and readiness."""
    local = local_only(store) if require_local is None else require_local
    usable, skipped = [], []
    for engine in configured(role):
        if local and not engine.is_local:
            skipped.append((engine, "سیاست فروشگاه «فقط لوکال» است"))
            continue
        ok, why = readiness(engine)
        if not ok:
            skipped.append((engine, why))
            continue
        usable.append(engine)
    return Resolution(usable, skipped)


def require(role: str, store=None) -> list[Engine]:
    """Like `resolve`, but raises a useful error when nothing is usable."""
    result = resolve(role, store)
    if result.engines:
        return result.engines
    label = {VOICE: "صداگذاری", SOUND: "صدای محیط", DENOISE: "حذف نویز"}.get(role, role)
    hint = {
        VOICE: "در ادمین «موتورهای صدا» یک گوینده‌ی لوکال (Piper) را فعال کنید و مدلش را با "
               "python manage.py audio_setup --voices دانلود کنید.",
        SOUND: "کتابخانه‌ی صدا را با python manage.py audio_setup --library پر کنید.",
        DENOISE: "RNNoise همراه پروژه است؛ آن را در ادمین فعال کنید.",
    }.get(role, "")
    detail = result.explain() or "هیچ موتوری فعال نیست"
    raise NoEngine(f"هیچ موتور {label} قابل‌استفاده‌ای نیست ({detail}). {hint}")


def status() -> list[dict]:
    """Every configured engine with its readiness — for the admin and setup."""
    out = []
    for role in (VOICE, SOUND, DENOISE):
        for engine in configured(role):
            ok, why = readiness(engine)
            out.append({
                "role": role, "kind": engine.kind, "name": engine.name,
                "priority": engine.priority, "local": engine.is_local,
                "ready": ok, "reason": why,
            })
    return out
