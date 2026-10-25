"""Music under the narration, and sound effects on top. §7 (phase 22).

**We build the engine. The shop brings the music.** That split is not laziness,
it is the only version of this feature that does not eventually hurt a customer:
a track we bundled without a watertight licence becomes a copyright strike on
*their* account, on a video *they* published, and the takedown arrives weeks
later with no explanation they can act on. So the shop uploads a file they have
the right to use, or points at a library they subscribe to, and the panel says
plainly that the licence is theirs.

What is actually hard here, and what this module does:

**Ducking.** Music at a flat level either drowns the narration or is inaudible.
The fix is to pull the music down *while someone is speaking* and let it back up
in the gaps — `sidechaincompress`, driven by the voice track itself. Without it
you are choosing between a video nobody can follow and music nobody can hear.

**Length.** Music is never the length of the video. Shorter, it has to loop
without an audible seam; longer, it has to end rather than being cut off
mid-phrase — so it fades.

**A floor under the voice.** There is a level below which narration stops being
intelligible no matter how good it is, and `MUSIC_CEILING` exists so an
enthusiastic setting cannot cross it. A shop that makes the music too loud has
made a video that fails at the only thing it was for.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from services.video.ffmpeg import (
    FFMPEG,
    VideoProcessingError,
    _run,
    probe_duration,
)

logger = logging.getLogger(__name__)

#: Music this far below the narration, before ducking. Quiet enough to sit
#: under a voice, loud enough to be there.
MUSIC_DB = -22.0

#: The loudest the music may ever be set, whatever the shop asks for. Past this
#: the narration stops being intelligible, and an unintelligible narration makes
#: the video fail at the only job it had.
MUSIC_CEILING = -10.0

#: How far the music drops while someone is speaking. Not silence — a hole in
#: the music is as noticeable as music over speech.
DUCK_RATIO = 6

#: Music starts and ends on a fade. A hard cut to silence reads as a glitch.
FADE_IN = 1.0
FADE_OUT = 2.0

#: Sound effects are short by definition. Anything longer is music that arrived
#: in the wrong field.
MAX_SFX_SECONDS = 5.0


@dataclass
class Track:
    """One audio file the shop supplied, and where it goes."""

    path: Path
    #: Decibels relative to the narration. Clamped by `MUSIC_CEILING`.
    level_db: float = MUSIC_DB
    #: Seconds into the video. Only meaningful for effects.
    at: float = 0.0

    def safe_level(self) -> float:
        return min(MUSIC_CEILING, float(self.level_db))


class MusicError(Exception):
    """Something about the supplied audio is wrong, said in Persian."""


def inspect(path) -> dict:
    """What we know about a file the shop uploaded, before using it."""
    path = Path(path)
    if not path.exists():
        raise MusicError("فایل موسیقی پیدا نشد.")
    try:
        seconds = probe_duration(path)
    except VideoProcessingError as exc:
        raise MusicError(f"این فایل صوتی خوانده نشد: {exc}") from exc
    if seconds <= 0.1:
        raise MusicError("این فایل عملاً خالی است.")
    return {"seconds": round(seconds, 2), "name": path.name}


def _fit_filter(music_seconds: float, target: float) -> str:
    """Loop or trim the music to the video's length, without a seam or a cut.

    Looping is `aloop`, not concatenation: concatenating a file to itself puts a
    click at the join, and a click every thirty seconds is the kind of defect a
    viewer cannot name but does notice.
    """
    parts = []
    if music_seconds < target - 0.1:
        # -1 is "forever"; the trim below decides where it actually ends.
        parts.append("aloop=loop=-1:size=2e9")
    parts.append(f"atrim=0:{target:.3f}")
    parts.append("asetpts=N/SR/TB")
    fade_out_at = max(0.0, target - FADE_OUT)
    parts.append(f"afade=t=in:st=0:d={FADE_IN}")
    parts.append(f"afade=t=out:st={fade_out_at:.3f}:d={FADE_OUT}")
    return ",".join(parts)


def under_narration(video_path, music: Track, out_path, *, duck: bool = True) -> Path:
    """Lay music under a video that already has narration.

    The video's own audio is the voice. It stays at its level and the music
    moves around it — never the other way round.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    target = probe_duration(video_path)
    music_seconds = inspect(music.path)["seconds"]
    level = music.safe_level()
    if level != music.level_db:
        logger.info(
            "Music level capped from %.1f to %.1f dB", music.level_db, level,
        )

    fitted = _fit_filter(music_seconds, target)
    # The shop's own background is the LOWEST layer of the mix: under the
    # voice, under the effects, under the ambience. Its loudness target comes
    # from the admin (`AudioMix.background_lufs`, default −38 LUFS against a
    # −16 LUFS voice), the shop's slider moves it relative to that, and the
    # admin's ceiling caps it whatever the slider says. Normalising first
    # means the number is the loudness the viewer hears, whatever the file's
    # own loudness was — a −6 dBFS track and a −30 dBFS track used to land
    # 24 dB apart for the same setting.
    from .polish import settings_mix

    mix = settings_mix()
    lufs = min(
        float(mix.background_ceiling_lufs),
        float(mix.background_lufs) + (level - MUSIC_DB),
    )
    gain = f"loudnorm=I={lufs:.1f}:TP=-2:LRA=7"
    ratio = max(2.0, min(20.0, 1.0 + float(mix.duck_db) / 2.0))

    # `normalize=0`: amix otherwise scales every input by 1/N, which took the
    # narration down 6 dB every time music was added (measured −41 → −47 dBFS).
    # Both sides at one rate and layout before they meet: loudnorm outputs
    # 192 kHz, narration is 24–48 kHz mono, and ffmpeg 4.4's sidechaincompress
    # cannot negotiate that by itself ("No channel layout for input 1").
    common = "aresample=48000,aformat=channel_layouts=stereo"
    if duck:
        # The voice drives the compressor on the music. `asplit` because the
        # voice is needed twice: once as the side-chain key, once in the mix.
        graph = (
            f"[0:a]{common},asplit=2[voice][key];"
            f"[1:a]{fitted},{gain},{common}[bed];"
            f"[bed][key]sidechaincompress=threshold=0.03:ratio={ratio:.1f}"
            f":attack=20:release=500[ducked];"
            f"[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0"
            f":normalize=0,alimiter=limit=0.95[a]"
        )
    else:
        graph = (
            f"[0:a]{common}[voice];"
            f"[1:a]{fitted},{gain},{common}[bed];"
            f"[voice][bed]amix=inputs=2:duration=first:dropout_transition=0"
            f":normalize=0,alimiter=limit=0.95[a]"
        )

    _run([
        FFMPEG, "-y",
        "-i", str(video_path),
        "-i", str(music.path),
        "-filter_complex", graph,
        "-map", "0:v",
        "-map", "[a]",
        # The picture is untouched, so it is copied rather than re-encoded.
        # Re-encoding video to add music costs minutes and loses quality for
        # nothing.
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out),
    ])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("موسیقی روی ویدیو ننشست")
    return out


#: The ambience slider's neutral point: at this level the bed sits at the admin's `AudioMix.ambience_lufs`.
AMBIENCE_DB = -30.0


def _has_audio(path) -> bool:
    try:
        from services.video.ffmpeg import probe

        return any(st.get("codec_type") == "audio" for st in probe(path).get("streams") or [])
    except Exception:  # noqa: BLE001
        return True


def under_narration_layers(video_path, layers: list, out_path, *, duck: bool = True) -> Path:
    """Music AND an ambience bed under the narration in one pass: `layers` = [(Track, "music" | "ambience"), ...].

    Each bed is normalised to its own loudness target (music: `background_lufs`, ambience: `ambience_lufs`,
    both under the admin's ceiling) and each is ducked by the voice itself, so neither covers a word. A video
    without a sound track (not voiced yet) gets silence as its "voice", so beds alone still work.
    """
    layers = [(t, role) for t, role in layers if t.path and Path(t.path).exists()]
    if not layers:
        raise MusicError("نه موسیقی انتخاب شده و نه صدای محیط.")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    target = probe_duration(video_path)
    from .polish import settings_mix

    mix = settings_mix()
    ratio = max(2.0, min(20.0, 1.0 + float(mix.duck_db) / 2.0))
    common = "aresample=48000,aformat=channel_layouts=stereo"
    inputs = ["-i", str(video_path)]
    first = 1
    voice_in = "[0:a]"
    if not _has_audio(video_path):
        inputs += ["-f", "lavfi", "-t", f"{target:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        voice_in, first, duck = "[1:a]", 2, False
    n = len(layers)
    if duck:
        chains = [f"{voice_in}{common},asplit={n + 1}[voice]" + "".join(f"[key{i}]" for i in range(n))]
    else:
        chains = [f"{voice_in}{common}[voice]"]
    labels = []
    for i, (track, role) in enumerate(layers):
        inputs += ["-i", str(track.path)]
        seconds = inspect(track.path)["seconds"]
        level = track.safe_level()
        if role == "ambience":
            lufs = min(float(mix.background_ceiling_lufs), float(mix.ambience_lufs) + (level - AMBIENCE_DB))
        else:
            lufs = min(float(mix.background_ceiling_lufs), float(mix.background_lufs) + (level - MUSIC_DB))
        chains.append(f"[{first + i}:a]{_fit_filter(seconds, target)},loudnorm=I={lufs:.1f}:TP=-2:LRA=7,{common}[bed{i}]")
        if duck:
            chains.append(f"[bed{i}][key{i}]sidechaincompress=threshold=0.03:ratio={ratio:.1f}:attack=20:release=500[d{i}]")
            labels.append(f"[d{i}]")
        else:
            labels.append(f"[bed{i}]")
    chains.append(f"[voice]{''.join(labels)}amix=inputs={n + 1}:duration=first:dropout_transition=0"
                  ":normalize=0,alimiter=limit=0.95[a]")
    _run([FFMPEG, "-y", *inputs, "-filter_complex", ";".join(chains), "-map", "0:v", "-map", "[a]",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("موسیقی و صدای محیط روی ویدیو ننشست")
    return out


def add_effects(video_path, effects: list[Track], out_path) -> Path:
    """Drop short sounds in at given moments — a whoosh, a click, a ding."""
    effects = [e for e in effects if e.path and Path(e.path).exists()]
    if not effects:
        raise MusicError("هیچ افکت صوتی داده نشد.")
    if len(effects) > 12:
        # Past a dozen this is not sound design, it is a filtergraph that takes
        # longer to build than the render it decorates.
        raise MusicError("حداکثر ۱۲ افکت صوتی در یک ویدیو.")

    target = probe_duration(video_path)
    for effect in effects:
        seconds = inspect(effect.path)["seconds"]
        if seconds > MAX_SFX_SECONDS:
            raise MusicError(
                f"«{Path(effect.path).name}» {seconds:.0f} ثانیه است — این "
                "موسیقی است نه افکت. از فیلد موسیقی استفاده کنید."
            )
        if effect.at >= target:
            raise MusicError(
                f"ثانیه‌ی {effect.at:g} بعد از پایان ویدیو ({target:.0f} ثانیه) است."
            )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    chains, labels = [], []
    for index, effect in enumerate(effects, start=1):
        label = f"e{index}"
        delay = int(effect.at * 1000)
        chains.append(
            f"[{index}:a]volume={effect.safe_level():.2f}dB,"
            f"adelay={delay}|{delay}[{label}]"
        )
        labels.append(f"[{label}]")

    graph = ";".join(chains) + (
        f";[0:a]{''.join(labels)}amix=inputs={len(effects) + 1}"
        # normalize=0 keeps every input at its own level; the old volume=N
        # after a 1/N mix was the same thing done twice, with clipping risk.
        ":duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.95[a]"
    )

    command = [FFMPEG, "-y", "-i", str(video_path)]
    for effect in effects:
        command += ["-i", str(effect.path)]
    command += [
        "-filter_complex", graph,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    _run(command)
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("افکت صوتی روی ویدیو ننشست")
    return out


#: What the panel tells a shop before they upload. Not a disclaimer buried in
#: terms: the consequence lands on their account, not ours, and weeks later.
LICENCE_NOTE = (
    "موسیقی را خودتان بگذارید. ما فایل موسیقی همراه محصول نمی‌دهیم، چون اگر "
    "مجوزش کامل نباشد، استریک کپی‌رایت روی **صفحه‌ی خودتان** می‌آید نه روی ما — "
    "و هفته‌ها بعد، بدون توضیحی که بشود کاریش کرد. از کتابخانه‌ای که اشتراکش "
    "را دارید یا موسیقی بدون کپی‌رایت استفاده کنید."
)
