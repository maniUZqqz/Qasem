"""Taking the noise out of a voice the shop recorded — on this machine.

A shop films its product on a phone, in a shop, next to a fridge compressor
and a street. The voice is the part that sells; the hum, the hiss and the
traffic are the part that makes the video sound cheap. Four local engines,
chosen and ordered in the admin (`AudioEngine`, role DENOISE):

| engine        | what it is                               | quality   | speed     |
|---------------|------------------------------------------|-----------|-----------|
| DeepFilterNet | deep network for speech enhancement      | best      | fast, CPU |
| RNNoise       | small recurrent network, inside ffmpeg   | good      | very fast |
| noisereduce   | spectral gating (non-stationary)         | fair      | fast      |
| FFT (afftdn)  | classic spectral subtraction, in ffmpeg  | basic     | instant   |

All four are free and run offline. DeepFilterNet (MIT/Apache) is a separate
download (`manage.py audio_setup --denoise`); the RNNoise weights ship with
the project — 300 KB, and by their author's statement not subject to
copyright.

**Natural beats silent.** Every engine is held back from removing everything
it could: DeepFilterNet's attenuation is limited, RNNoise is mixed with a
little of the original. A voice with a faint room behind it sounds like a
person in a room; a voice with the room surgically removed sounds underwater,
and that artefact is more noticeable than the noise was.

**Measured, not assumed.** `measure` estimates the noise floor and the speech
level from the recording itself, before and after, and the result carries
both — so "حذف نویز" is a number the shop can see, not a promise.
"""
from __future__ import annotations

import logging
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run, filter_path, probe

from . import engines as engine_registry
from . import qc as audio_qc

logger = logging.getLogger(__name__)

#: DeepFilterNet works at 48 kHz, RNNoise too; one rate for all of them.
RATE = 48000


class DenoiseError(Exception):
    pass


@dataclass
class DenoiseResult:
    path: Path
    engine: str
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def improvement_db(self) -> float | None:
        a, b = self.after.get("snr_db"), self.before.get("snr_db")
        if a is None or b is None:
            return None
        return round(a - b, 1)

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "before": self.before,
            "after": self.after,
            "improvement_db": self.improvement_db,
            "notes": self.notes,
        }


# ------------------------------------------------------------ measuring


def _db(value: float) -> float:
    return 20 * math.log10(max(value, 1e-9) / 32768.0)


def measure(path, work_dir) -> dict:
    """Noise floor, speech level and their distance, from the file itself.

    The floor is the 10th percentile of 20 ms window levels — the quietest
    tenth of the recording, which in speech is the gaps between words, i.e.
    whatever is behind the voice. Speech is the typical level of the loud
    windows (`audio_qc.reference_level`). Their difference is an SNR estimate
    that needs no reference and no model.
    """
    try:
        samples, rate = audio_qc.decode(path, work_dir)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not decode %s for noise measurement: %s", path, exc)
        return {}
    levels = audio_qc._windows(samples, rate)
    if len(levels) < 10:
        return {}
    ordered = sorted(levels)
    floor = ordered[max(0, int(len(ordered) * 0.10) - 1)]
    speech = audio_qc.reference_level(levels)
    facts = {
        "noise_floor_db": round(_db(floor), 1),
        "speech_db": round(_db(speech), 1),
        "snr_db": round(_db(speech) - _db(floor), 1),
    }
    ratio = speech_ratio(samples, rate)
    if ratio is not None:
        facts["speech_ratio"] = round(ratio, 2)
    return facts


def speech_ratio(samples, rate: int) -> float | None:
    """Fraction of the recording in which someone is talking (Silero VAD).

    The level-based SNR above cannot tell a voice from music: a product video
    with only a soundtrack has a "floor" in the quiet bars and a "speech
    level" in the loud ones, and would be called noisy — and a speech
    denoiser run over music eats it. The VAD that ships inside faster-whisper
    (already a dependency, 2 MB, CPU) answers the question that matters
    first: is there a voice to protect at all? None when it is unavailable.
    """
    try:
        import numpy as np
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except Exception:  # noqa: BLE001 — optional dependency
        return None
    if rate != 16_000 or not len(samples):
        return None
    try:
        audio = np.frombuffer(bytes(samples), dtype=np.int16).astype(np.float32) / 32768.0
        spans = get_speech_timestamps(
            audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100),
            sampling_rate=rate,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Voice activity detection failed: %s", exc)
        return None
    talking = sum(max(0, span["end"] - span["start"]) for span in spans)
    return min(1.0, talking / len(audio))


#: Below this share of talking, the soundtrack is not a voice recording and a
#: speech denoiser has nothing to protect — only music or ambience to damage.
MIN_SPEECH_RATIO = 0.15


def is_noisy(facts: dict, *, min_snr_db: float = 30.0) -> bool:
    """Would a listener notice the noise behind a voice? Needs all three.

    Someone must be talking (see `speech_ratio`); a low SNR on a recording
    whose floor is digital silence is a quiet voice, not a noisy one; and a
    high floor under a loud voice is masked. Only a floor that is audible
    (above -60 dBFS) and close to a voice that is there is noise.
    """
    snr = facts.get("snr_db")
    floor = facts.get("noise_floor_db")
    if snr is None or floor is None:
        return False
    talking = facts.get("speech_ratio")
    if talking is not None and float(talking) < MIN_SPEECH_RATIO:
        return False
    return float(snr) < float(min_snr_db) and float(floor) > -60.0


# -------------------------------------------------------------- engines


def _to_wav(source, out: Path, *, channels: int = 1) -> Path:
    """The source's audio as plain PCM, on the video's clock.

    The cleaned track is muxed back as a separate input, so it no longer
    carries the container's timestamps. `aresample=async=1:first_pts=0` pads a
    late-starting track and fills gaps with silence here, so sample N of the
    WAV is still at the same moment as the frame it was recorded with — phone
    recordings with a few dropped audio packets otherwise drift out of lip
    sync by the end.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([FFMPEG, "-y", "-i", str(source), "-vn",
          "-af", "aresample=async=1:first_pts=0", "-ac", str(channels),
          "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)])
    return out


def _source_channels(source) -> int:
    try:
        streams = probe(source).get("streams") or []
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        return int(audio.get("channels") or 1)
    except Exception:  # noqa: BLE001 — mono is the safe answer
        return 1


def _deepfilter(engine, wav: Path, out: Path, strength: float) -> Path:
    binary = engine_registry.deepfilter_binary()
    if binary is None:
        raise DenoiseError("DeepFilterNet دانلود نشده")
    # Attenuation limit: how many dB of noise it may remove at most. 100 would
    # be "everything"; 25–35 keeps a trace of the room so the voice does not
    # sound processed.
    limit = float(engine.options.get("atten_lim_db", 30)) * max(0.3, min(1.5, strength))
    out_dir = out.parent / "dfn"
    out_dir.mkdir(parents=True, exist_ok=True)
    # -D: compensate the STFT window and look-ahead. Without it the cleaned
    # voice arrives ~30 ms late — just enough to make lips look dubbed.
    result = subprocess.run(
        [str(binary), "-D", "--atten-lim-db", f"{limit:.0f}", "-o", str(out_dir), str(wav)],
        capture_output=True, text=True, timeout=engine.timeout_s or 600,
    )
    produced = out_dir / wav.name
    if result.returncode != 0 or not produced.exists():
        raise DenoiseError(f"DeepFilterNet failed: {(result.stderr or result.stdout)[-300:]}")
    produced.replace(out)
    return out


def _rnnoise(engine, wav: Path, out: Path, strength: float) -> Path:
    model = engine_registry.rnnoise_model(engine.model_name or "sh")
    if not model.exists():
        raise DenoiseError(f"مدل RNNoise پیدا نشد: {model}")
    # A little of the original stays in (mix < 1): the network's output alone
    # has the faintly gated sound of a phone call.
    mix = max(0.5, min(1.0, float(engine.options.get("mix", 0.9)) * strength))
    _run([FFMPEG, "-y", "-i", str(wav), "-af",
          f"arnndn=m={filter_path(model)}:mix={mix:.2f}",
          "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)])
    return out


def _spectral(engine, wav: Path, out: Path, strength: float) -> Path:
    import noisereduce
    import soundfile

    audio, rate = soundfile.read(str(wav))
    reduced = noisereduce.reduce_noise(
        y=audio, sr=rate, stationary=bool(engine.options.get("stationary", False)),
        prop_decrease=max(0.3, min(1.0, float(engine.options.get("prop_decrease", 0.85)) * strength)),
    )
    soundfile.write(str(out), reduced, rate, subtype="PCM_16")
    return out


def _afftdn(engine, wav: Path, out: Path, strength: float) -> Path:
    reduction = max(3, min(30, int(float(engine.options.get("nr", 12)) * strength)))
    _run([FFMPEG, "-y", "-i", str(wav), "-af",
          f"afftdn=nr={reduction}:nf=-40:tn=1",
          "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)])
    return out


_RUNNERS = {
    "DEEPFILTER": _deepfilter,
    "RNNOISE": _rnnoise,
    "SPECTRAL": _spectral,
    "AFFTDN": _afftdn,
}


def clean(source, out_path, work_dir, *, store=None, strength: float = 1.0) -> DenoiseResult:
    """The voice track of `source`, with the noise taken out, as a 48 kHz WAV.

    Tries the admin's denoise engines in order; the first that succeeds wins.
    `strength` scales every engine's setting around its natural default (1.0).
    Raises DenoiseError only when every engine failed.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out = Path(out_path)
    raw = _to_wav(source, work / "denoise_in.wav")
    channels = _source_channels(source)
    before = measure(raw, work)

    try:
        chain = engine_registry.require(engine_registry.DENOISE, store)
    except engine_registry.NoEngine as exc:
        raise DenoiseError(str(exc)) from exc

    errors = []
    for engine in chain:
        runner = _RUNNERS.get(engine.kind)
        if runner is None:
            continue
        try:
            runner(engine, raw, out, strength)
        except (DenoiseError, VideoProcessingError, subprocess.SubprocessError, OSError, ValueError) as exc:
            errors.append(f"{engine.name}: {exc}")
            logger.info("Denoise engine %s failed: %s", engine.name, exc)
            continue
        except Exception as exc:  # noqa: BLE001 — a library raising anything else
            errors.append(f"{engine.name}: {exc}")
            logger.info("Denoise engine %s failed: %s", engine.name, exc)
            continue
        if not out.exists() or out.stat().st_size == 0:
            errors.append(f"{engine.name}: خروجی خالی")
            continue
        after = measure(out, work)
        if channels > 1:
            # Cleaned as mono (the voice is centred anyway), handed back with
            # the channel count it came in with, so a stereo video does not
            # come out of the editor as a one-sided or mono file.
            stereo = out.with_name(out.stem + "_st.wav")
            _run([FFMPEG, "-y", "-i", str(out), "-ac", str(min(channels, 2)),
                  "-ar", str(RATE), "-c:a", "pcm_s16le", str(stereo)])
            stereo.replace(out)
        result = DenoiseResult(path=out, engine=engine.name, before=before, after=after)
        if errors:
            result.notes.append("موتورهای قبلی کار نکردند: " + " | ".join(errors))
        return result
    raise DenoiseError("حذف نویز انجام نشد — " + " | ".join(errors))
