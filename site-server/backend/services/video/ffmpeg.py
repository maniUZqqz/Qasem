"""FFmpeg helpers: last-frame extraction, concatenation, audio mixing, probing."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _resolve_binary(env_name: str, exe: str) -> str:
    """Where ffmpeg/ffprobe actually is — even when the .env says otherwise.

    `backend/.env` pins an ABSOLUTE path (Celery workers do not inherit the
    launcher's PATH), and that file travels between machines with the repo.
    So the pin is routinely a path that only exists on some other computer:
    this happened when the project folder was renamed, and it happens on every
    pull from a machine that lives at a different path. Every video, voice and
    subtitle job then died on "binary not found" naming a folder nobody on this
    machine had ever seen.

    A pin that points at a real file is respected. One that points nowhere
    falls back to the copy bundled with the project, then to PATH — the same
    two places the launcher looks, in the same order.
    """
    configured = (os.getenv(env_name) or "").strip()
    if configured and (os.path.isfile(configured) or shutil.which(configured)):
        return configured
    bundled = Path(__file__).resolve().parents[3] / "ffmpeg" / "bin" / f"{exe}.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which(exe) or configured or exe


FFMPEG = _resolve_binary("FFMPEG_BIN", "ffmpeg")
FFPROBE = _resolve_binary("FFPROBE_BIN", "ffprobe")


class VideoProcessingError(Exception):
    pass


#: One delivery profile for every MP4 a shop will publish. yuv420p because a
#: 4:4:4 or full-range source otherwise passes straight through and Instagram's
#: transcoder rejects it; High@4.1 so the level is not left to chance; and
#: +faststart so the moov atom leads and playback starts before the whole file
#: has downloaded. Audio at 48 kHz: edge-tts narration arrives at 24 kHz mono
#: and was being shipped that way.
VIDEO_DELIVERY = [
    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
    "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
    "-movflags", "+faststart",
]
AUDIO_DELIVERY = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"]


def filter_path(path) -> str:
    """A file path the way an ffmpeg FILTER option wants it.

    Filter option values are parsed on ':' — so `C:/Users/...` is read as the
    option `C` and fails with "No option name near /Users" — and on Windows
    every path has one. Forward slashes, escaped colon, single-quoted.
    """
    text = str(path).replace("\\", "/").replace(":", r"\:")
    return f"'{text}'"


def _run(cmd):
    try:
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError(
            f"{cmd[0]} binary not found — install ffmpeg or set FFMPEG_BIN/FFPROBE_BIN"
        ) from exc
    if result.returncode != 0:
        tail = (result.stderr or "")[-2000:]
        raise VideoProcessingError(f"Command failed ({cmd[0]}): {tail}")
    return result


def extract_last_frame(video_path, out_path) -> Path:
    """Extract the final frame of a video — the anchor for the next segment.

    The TRUE last frame. `-sseof -0.3 -frames:v 1` — the old fast path — gives
    the first frame at or after (end − 0.3 s), which at Wan's 16 fps is about
    five frames before the end: every join then showed the subject jump back
    by five frames of motion. Reversing the last second and taking its first
    frame costs sixteen frames of memory and is exact (measured difference to
    the real last frame: 0.0 against 2.8 before).
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run([FFMPEG, "-y", "-sseof", "-1", "-i", str(video_path),
              "-vf", "reverse", "-frames:v", "1", "-update", "1", "-q:v", "1", str(out)])
    except VideoProcessingError:
        pass
    if out.exists() and out.stat().st_size > 0:
        return out
    # Robust fallback (clips shorter than a second): decode all frames, keep
    # overwriting one image → last frame.
    _run([FFMPEG, "-y", "-i", str(video_path), "-update", "1", "-q:v", "1", str(out)])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError(f"Last frame was not written: {out}")
    return out


def probe(path) -> dict:
    result = _run([FFPROBE, "-v", "error", "-print_format", "json",
                   "-show_format", "-show_streams", str(path)])
    return json.loads(result.stdout)


def probe_duration(path) -> float:
    info = probe(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VideoProcessingError(f"Could not read duration of {path}") from exc


def _rate(text) -> float:
    """'30000/1001' → 29.97. Anything unreadable → 0."""
    try:
        num, _, den = str(text or "").partition("/")
        den_value = float(den) if den else 1.0
        return float(num) / den_value if den_value else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def probe_video(path) -> dict:
    """Shape of a video in one ffprobe call: width, height, fps, duration,
    has_audio, color_range.

    Everything downstream that builds a filter needs the same four numbers —
    a zoom that scales back to the frame, a QC pass converting limited-range
    luma, a deflicker window sized to the frame rate — and probing four times
    for them is four process launches per edit.
    """
    info = probe(path)
    video = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None,
    )
    if video is None:
        raise VideoProcessingError(f"این فایل تصویر ندارد: {path}")
    fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")) or 25.0
    try:
        duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    # A phone MP4 shot upright is stored sideways with a display-matrix
    # rotation; ffmpeg autorotates it on decode, so every filter sees the
    # PORTRAIT frame. Reporting the coded size would make a zoom scale a
    # 360×640 picture back to 640×360 and squash it.
    rotation = 0
    for side in video.get("side_data_list") or []:
        try:
            rotation = int(round(float(side.get("rotation", 0) or 0)))
        except (TypeError, ValueError):
            continue
        if rotation:
            break
    if not rotation:
        try:
            rotation = int(round(float((video.get("tags") or {}).get("rotate", 0) or 0)))
        except (TypeError, ValueError):
            rotation = 0
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return {
        "width": width,
        "height": height,
        "rotation": rotation,
        "fps": round(fps, 3),
        "fps_text": str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "25/1"),
        "duration": duration,
        "frames": int(video.get("nb_frames") or 0) or None,
        "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
        # "tv" (16–235) is what every camera and every encoder here produces;
        # "pc" is full range. signalstats reports raw sample values, so the
        # range decides how they are converted before meeting a threshold.
        "color_range": str(video.get("color_range") or "tv"),
        "pix_fmt": str(video.get("pix_fmt") or ""),
    }


def _stream_signature(path) -> tuple:
    """What has to match for two MP4s to be stream-copied back to back."""
    info = probe(path)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    return (
        video.get("codec_name"), video.get("width"), video.get("height"),
        video.get("pix_fmt"), video.get("profile"), video.get("level"),
        video.get("r_frame_rate"), video.get("sample_aspect_ratio") or "1:1",
        None if audio is None else (
            audio.get("codec_name"), audio.get("sample_rate"), audio.get("channels"),
        ),
    )


def concat_videos(video_paths, out_path) -> Path:
    """Concatenate segments: lossless when they really match, normalised otherwise.

    The concat demuxer with `-c copy` does NOT fail on mismatched parts — it
    exits 0 and writes a file whose header says 640×360 while the decoder emits
    320×180 frames from the join onwards (measured); a segment the repair layer
    re-encoded, or one from a different encoder profile, used to be stitched
    that way and play "fine" here and be rejected by Instagram. So the parts
    are probed first: identical signatures → stream copy; anything else → the
    concat FILTER with every part scaled, retimed and formatted alike, encoded
    with the delivery profile.
    """
    if not video_paths:
        raise VideoProcessingError("No video segments to concatenate")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = [Path(p) for p in video_paths]

    try:
        signatures = [_stream_signature(p) for p in parts]
        identical = len(set(signatures)) == 1
    except Exception:  # noqa: BLE001 — unreadable probe → normalise, the safe path
        signatures, identical = [], False

    if identical:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            for path in parts:
                escaped = str(path.resolve()).replace("'", "'\\''")
                fh.write(f"file '{escaped}'\n")
            list_file = fh.name
        try:
            _run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
                  "-i", list_file, "-c", "copy", "-movflags", "+faststart", str(out)])
            return out
        except VideoProcessingError:
            pass  # fall through to the normalising path
        finally:
            os.unlink(list_file)

    first = probe_video(parts[0])
    width, height = first["width"], first["height"]
    fps = first["fps_text"]
    has_audio = all(probe_video(p)["has_audio"] for p in parts)
    graph = []
    for index in range(len(parts)):
        graph.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{index}]"
        )
        if has_audio:
            graph.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo[a{index}]")
    streams = "".join(
        f"[v{i}]" + (f"[a{i}]" if has_audio else "") for i in range(len(parts))
    )
    graph.append(
        f"{streams}concat=n={len(parts)}:v=1:a={1 if has_audio else 0}[v]"
        + ("[a]" if has_audio else "")
    )
    command = [FFMPEG, "-y"]
    for path in parts:
        command += ["-i", str(path)]
    command += ["-filter_complex", ";".join(graph), "-map", "[v]"]
    if has_audio:
        command += ["-map", "[a]", *AUDIO_DELIVERY]
    command += [*VIDEO_DELIVERY, str(out)]
    _run(command)
    return out


def mix_audio(video_path, audio_path, out_path) -> Path:
    """Mux narration audio onto a video without re-encoding the video stream."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([FFMPEG, "-y", "-i", str(video_path), "-i", str(audio_path),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy", *AUDIO_DELIVERY,
          "-movflags", "+faststart", "-shortest", str(out)])
    return out


def make_silence(duration, out_path, sample_rate=48000) -> Path:
    """Generate a silent audio clip (for scenes without narration)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([FFMPEG, "-y", "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=mono",
          "-t", str(duration), "-c:a", "aac", str(out)])
    return out


def fit_audio(audio_path, out_path, target_duration, max_tempo=1.25) -> Path:
    """Fit narration into a scene window: speed up (capped), pad, trim to exact length.

    Never hard-cuts mid-speech unless the narration exceeds target*max_tempo;
    in that case the overflow is trimmed and the caller should record a warning.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(audio_path)
    filters = []
    if duration > target_duration + 0.05:
        tempo = min(duration / target_duration, max_tempo)
        filters.append(f"atempo={tempo:.4f}")
    filters.append("apad")
    _run([FFMPEG, "-y", "-i", str(audio_path), "-af", ",".join(filters),
          "-t", str(target_duration), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)])
    return out


def normalize_audio(audio_path, out_path, *, target_db=-18.0, peak_db=-1.5) -> Path:
    """Bring narration to a comfortable level and stop it hitting the ceiling.

    One filter answers both of audio QC's code-fixable axes: `loudnorm` moves
    quiet speech up and hot speech down (LEVEL), and its true-peak limiter is
    what keeps the result off the rail that makes a voice sound metallic
    (DISTORTION). Fixing those with a filter costs nothing; the alternative is
    asking the voice engine for the same sentence again and hoping.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        FFMPEG, "-y", "-i", str(audio_path),
        "-af", f"loudnorm=I={target_db}:TP={peak_db}:LRA=11",
        "-c:a", "aac", str(out),
    ])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError(f"Normalised audio was not written: {out}")
    return out


def concat_audio(audio_paths, out_path) -> Path:
    """Concatenate audio clips via the concat filter (codec-agnostic)."""
    if not audio_paths:
        raise VideoProcessingError("No audio clips to concatenate")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y"]
    for path in audio_paths:
        cmd += ["-i", str(path)]
    cmd += [
        "-filter_complex",
        f"concat=n={len(audio_paths)}:v=0:a=1",
        "-c:a", "aac",
        str(out),
    ]
    _run(cmd)
    return out
