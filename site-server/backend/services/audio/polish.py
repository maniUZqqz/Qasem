"""From "a speech engine's output" to "a voice-over".

Raw TTS audio has tells that a listener hears without being able to name:
rumble below the voice, harsh «س» and «ش», a level that jumps between
sentences, a thin 22 kHz sample rate. A voice-over artist's audio goes
through the same few steps in every studio, and they are all cheap filters:

    rumble out → mud down → presence up → sibilance tamed →
    dynamics evened → loudness to target → 48 kHz

Nothing here adds anything that was not in the voice — no reverb, no
"warmth" plugin, no pitch change. Each step removes a defect, which is why it
is safe to run on every engine's output, Piper's and Azure's alike. The
settings are deliberately gentle: this is the polish a listener should not
notice, only miss when it is gone.

Turned on or off, and the loudness target set, in the admin (`AudioMix`).
"""
from __future__ import annotations

import logging
from pathlib import Path

from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run

logger = logging.getLogger(__name__)

#: Studio voice-over chain. Numbers chosen to be inaudible as processing:
#: -1.5 dB at 250 Hz is "less boxy", +1.5 dB at 3.2 kHz is "clearer", the
#: compressor at 2.5:1 only acts on the loudest syllables.
CHAIN = (
    "highpass=f=75",
    "equalizer=f=250:t=q:w=1.0:g=-1.5",
    "equalizer=f=3200:t=q:w=1.4:g=1.5",
    "deesser=i=0.3:m=0.5:f=0.5",
    "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=2",
)


def voice_chain(target_lufs: float = -16.0) -> str:
    return ",".join((
        "aresample=48000:resampler=soxr",
        *CHAIN,
        f"loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=9",
        "aresample=48000",
    ))


def polish_voice(source, out_path, *, target_lufs: float | None = None) -> Path:
    """Apply the voice-over chain. Returns `out_path`; raises VideoProcessingError."""
    if target_lufs is None:
        target_lufs = settings_mix().voice_lufs
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # A .wav target stays PCM: the polished voice is only an intermediate
    # (fitted, then mixed, then muxed), and every AAC pass on the way costs a
    # little high end.
    codec = ["-c:a", "pcm_s16le"] if out.suffix.lower() == ".wav" else ["-c:a", "aac", "-b:a", "160k"]
    _run([
        FFMPEG, "-y", "-i", str(source), "-vn",
        "-af", voice_chain(target_lufs),
        "-ac", "1", *codec, "-ar", "48000",
        str(out),
    ])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("پرداخت صدا خروجی نداد")
    return out


def settings_mix():
    """The admin's mix row, or its defaults when the table is not there yet."""
    try:
        from apps.ai.models import AudioMix

        return AudioMix.current()
    except Exception:  # noqa: BLE001 — before migrations / no database
        from types import SimpleNamespace

        return SimpleNamespace(
            voice_lufs=-16.0, polish_voice=True, ambience_enabled=True, ambience_lufs=-36.0,
            effects_enabled=True, effects_lufs=-26.0, background_lufs=-38.0,
            background_ceiling_lufs=-30.0, duck_db=9.0, suggest_denoise=True, min_snr_db=30.0,
        )


def maybe_polish(source, out_path) -> Path:
    """Polish when the admin says so; otherwise hand the file back untouched."""
    mix = settings_mix()
    if not getattr(mix, "polish_voice", True):
        return Path(source)
    try:
        return polish_voice(source, out_path, target_lufs=mix.voice_lufs)
    except VideoProcessingError as exc:
        logger.info("Voice polish failed, using the raw take: %s", exc)
        return Path(source)
