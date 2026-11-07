"""Rendering: export presets, the ffmpeg runner (progress + cancel) and the short «exact preview» of a range.

The composition has an aspect (the project's format); an export decides the SIZE (short side in pixels), codec,
frame rate, quality and audio bitrate. The graph is built at the export size directly — every coordinate is a fraction
of the frame, every title size a % of its height — so a 720-line render is sharp, not an upscaled 360-line one.
The final render always reads the ORIGINAL files (proxies are only for scrubbing in the browser).
"""
from __future__ import annotations

import dataclasses
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import TimelineError
from .timeline import Timeline

logger = logging.getLogger(__name__)

HEAVY_SHORT_SIDE = 1440


class RenderCancelled(Exception):
    pass


@dataclass
class ExportSpec:
    codec: str = "h264"
    short_side: int | None = None          # None = the composition's own size
    fps: int | None = None
    crf: int = 19
    preset: str = "medium"
    audio_kbps: int = 160
    max_kbps: int | None = None            # bitrate cap (VBV) for platforms that insist on one
    note: str = ""


QUALITY = {                                 # (x264 crf, x264 preset, x265 crf, x265 preset)
    "high": (18, "medium", 22, "fast"),
    "medium": (22, "medium", 26, "fast"),
    "small": (27, "veryfast", 30, "veryfast"),
}

#: key → (title, group, spec fields, hint)
PRESETS: dict[str, dict] = {
    "reels": {"title": "ریلز اینستاگرام / استوری", "group": "شبکه‌های اجتماعی", "short": 1080, "fps": 30, "codec": "h264", "quality": "high",
              "audio_kbps": 192, "max_seconds": 90, "aspect": "9:16"},
    "tiktok": {"title": "تیک‌تاک", "group": "شبکه‌های اجتماعی", "short": 1080, "fps": 30, "codec": "h264", "quality": "high",
               "audio_kbps": 192, "max_seconds": 180, "aspect": "9:16"},
    "feed": {"title": "پستِ اینستاگرام (۴:۵ یا مربع)", "group": "شبکه‌های اجتماعی", "short": 1080, "fps": 30, "codec": "h264",
             "quality": "high", "audio_kbps": 160, "max_seconds": 60},
    "youtube": {"title": "یوتیوب ۱۰۸۰", "group": "شبکه‌های اجتماعی", "short": 1080, "fps": 30, "codec": "h264", "quality": "high",
                "audio_kbps": 192, "aspect": "16:9"},
    "aparat": {"title": "آپارات", "group": "شبکه‌های اجتماعی", "short": 1080, "fps": 25, "codec": "h264", "quality": "medium",
               "audio_kbps": 160, "aspect": "16:9"},
    "telegram": {"title": "تلگرام / ایتا (حجمِ کم)", "group": "پیام‌رسان", "short": 720, "fps": 30, "codec": "h264", "quality": "small",
                 "audio_kbps": 128},
    "whatsapp": {"title": "واتساپ (حجمِ خیلی کم)", "group": "پیام‌رسان", "short": 540, "fps": 30, "codec": "h264", "quality": "small",
                 "audio_kbps": 96, "max_kbps": 1800},
    "hevc": {"title": "H.265 (فایلِ کوچک‌تر، ۱۰۸۰)", "group": "کیفیتِ بالا", "short": 1080, "fps": 30, "codec": "h265", "quality": "medium",
             "audio_kbps": 192},
    "master": {"title": "مادر (اندازهٔ پروژه، کیفیتِ بالا)", "group": "کیفیتِ بالا", "short": None, "fps": None, "codec": "h264",
               "quality": "high", "audio_kbps": 256},
    "draft": {"title": "پیش‌نویسِ سریع (۵۴۰)", "group": "سریع", "short": 540, "fps": None, "codec": "h264", "quality": "small",
              "audio_kbps": 96},
}

RESOLUTIONS = (480, 540, 720, 1080, 1440)
FPS_CHOICES = (24, 25, 30, 50, 60)

#: the render that existed before presets: «پیش‌نویس» / «نهایی» buttons (size unchanged)
DRAFT_VIDEO = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def catalogue() -> dict:
    return {
        "presets": [{"key": k, "title": v["title"], "group": v["group"], "short": v["short"], "fps": v["fps"], "codec": v["codec"],
                     "quality": v["quality"], "audio_kbps": v["audio_kbps"], "max_seconds": v.get("max_seconds"),
                     "aspect": v.get("aspect")} for k, v in PRESETS.items()],
        "codecs": [{"key": "h264", "title": "H.264 (سازگارترین)"}, {"key": "h265", "title": "H.265 / HEVC (کوچک‌تر، کندتر)"}],
        "qualities": [{"key": "high", "title": "بالا"}, {"key": "medium", "title": "متوسط"}, {"key": "small", "title": "کم‌حجم"}],
        "resolutions": list(RESOLUTIONS),
        "fps": list(FPS_CHOICES),
        "audio_kbps": [96, 128, 160, 192, 256, 320],
    }


def resolve(export: dict | None, timeline: Timeline) -> ExportSpec:
    """The project's `export` block (+ preset) → the encode settings, with notes for anything that does not fit."""
    e = export if isinstance(export, dict) else {}
    preset = PRESETS.get(str(e.get("preset") or ""))
    merged = dict(preset or {})
    for key in ("codec", "fps", "quality", "audio_kbps"):
        if e.get(key) not in (None, "", 0):
            merged[key] = e[key]
    if e.get("height") not in (None, "", 0):
        merged["short"] = e["height"]
    codec = "h265" if str(merged.get("codec")) == "h265" else "h264"
    q = QUALITY.get(str(merged.get("quality") or "high"), QUALITY["high"])
    crf, pset = (q[2], q[3]) if codec == "h265" else (q[0], q[1])
    short = merged.get("short")
    short = int(max(240, min(HEAVY_SHORT_SIDE, float(short)))) if short else None
    fps = merged.get("fps")
    fps = int(max(12, min(60, float(fps)))) if fps else None
    kbps = int(max(64, min(320, float(merged.get("audio_kbps") or 160))))
    spec = ExportSpec(codec=codec, short_side=short, fps=fps, crf=crf, preset=pset, audio_kbps=kbps, max_kbps=merged.get("max_kbps"))
    notes = []
    if preset:
        want = preset.get("aspect")
        if want:
            a, b = (int(x) for x in want.split(":"))
            if abs(timeline.width / timeline.height - a / b) > 0.05:
                notes.append(f"قابِ پروژه {want.replace(':', '‌:')} نیست؛ خروجی با همان قابِ پروژه ساخته می‌شود (برای {preset['title']} قابِ پروژه را در تب «خروجی» عوض کنید).")
        limit = preset.get("max_seconds")
        if limit and timeline.length > limit + 0.5:
            notes.append(f"این پلتفرم تا {limit} ثانیه می‌پذیرد؛ ویدیوی شما {timeline.length:.0f} ثانیه است.")
    try:
        target_mb = float(e.get("target_mb") or 0)
    except (TypeError, ValueError):
        target_mb = 0.0
    if 2 <= target_mb <= 500 and timeline.length > 1:
        # «حجمِ هدف»: a video-bitrate ceiling (VBV) so the file lands under the size a platform/messenger accepts
        total_kbps = target_mb * 8192 * 0.95 / timeline.length
        video_kbps = int(max(150, total_kbps - kbps))
        spec.max_kbps = min(int(spec.max_kbps), video_kbps) if spec.max_kbps else video_kbps
        notes.append(f"حجمِ هدف {target_mb:g} مگابایت: سقفِ تصویر حدود {video_kbps} کیلوبیت بر ثانیه می‌شود.")
        if video_kbps < 400 and (spec.short_side or min(timeline.width, timeline.height)) > 720:
            notes.append("برای این مدت و حجم، اندازهٔ تصویر را کمتر (مثلاً ۷۲۰) انتخاب کنید تا کیفیت نیفتد.")
    spec.note = " ".join(notes)
    return spec


def size_for(timeline: Timeline, short_side: int | None) -> tuple[int, int]:
    w, h = timeline.width, timeline.height
    if not short_side:
        return w, h
    k = short_side / min(w, h)
    return max(2, int(round(w * k / 2)) * 2), max(2, int(round(h * k / 2)) * 2)


def encode_args(spec: ExportSpec, *, draft: bool = False) -> list[str]:
    from services.video.ffmpeg import VIDEO_DELIVERY

    if draft:
        return list(DRAFT_VIDEO)
    if spec.codec == "h265":
        args = ["-c:v", "libx265", "-preset", spec.preset, "-crf", str(spec.crf), "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
                "-x265-params", "log-level=error", "-movflags", "+faststart"]
    else:
        args = ["-c:v", "libx264", "-preset", spec.preset, "-crf", str(spec.crf), "-pix_fmt", "yuv420p", "-profile:v", "high",
                "-movflags", "+faststart"]
    if spec.max_kbps:
        args += ["-maxrate", f"{spec.max_kbps}k", "-bufsize", f"{spec.max_kbps * 2}k"]
    return args or VIDEO_DELIVERY


def nvenc_args(spec: ExportSpec) -> list[str]:
    """The same encode on the processing node's NVIDIA encoder. `cq` runs about one step above x264's crf for a similar
    look; the node falls back to `encode_args` (CPU) when its ffmpeg or card cannot do this."""
    cq = str(min(51, int(spec.crf) + 1))
    if spec.codec == "h265":
        args = ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", cq, "-b:v", "0", "-pix_fmt", "yuv420p",
                "-tag:v", "hvc1", "-movflags", "+faststart"]
    else:
        args = ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", cq, "-b:v", "0", "-pix_fmt", "yuv420p",
                "-profile:v", "high", "-movflags", "+faststart"]
    if spec.max_kbps:
        args += ["-maxrate", f"{spec.max_kbps}k", "-bufsize", f"{spec.max_kbps * 2}k"]
    return args


# --------------------------------------------------------------------- runner


def run_ffmpeg(cmd: list[str], *, total: float = 0.0, progress=None, cancel=None, timeout: float | None = None) -> None:
    """Run ffmpeg with `-progress`, report 0..1 through `progress(fraction)`, stop when `cancel()` is true."""
    from services.video.ffmpeg import FFMPEG_TIMEOUT_SECONDS, VideoProcessingError, stderr_summary

    limit = timeout or FFMPEG_TIMEOUT_SECONDS
    err = tempfile.TemporaryFile()
    cmd = [cmd[0], "-hide_banner", "-nostats", "-loglevel", "error", "-progress", "pipe:1", *cmd[1:]]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                errors="replace")
    except FileNotFoundError as exc:
        err.close()
        raise VideoProcessingError(f"{cmd[0]} binary not found — install ffmpeg or set FFMPEG_BIN") from exc
    state = {"t": 0.0}

    def read() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    state["t"] = max(state["t"], int(line.split("=", 1)[1]) / 1e6)
                except ValueError:
                    pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    started, last = time.monotonic(), -1.0
    try:
        while proc.poll() is None:
            time.sleep(0.25)
            if cancel is not None and cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise RenderCancelled()
            if time.monotonic() - started > limit:
                proc.kill()
                raise VideoProcessingError(f"رندر بیش از {limit:.0f} ثانیه طول کشید و متوقف شد.")
            if progress is not None and total > 0 and state["t"] != last:
                last = state["t"]
                progress(min(0.99, state["t"] / total))
        reader.join(timeout=2)
        if proc.returncode != 0:
            err.seek(0)
            detail = stderr_summary(err.read().decode("utf-8", errors="replace")) or f"exit code {proc.returncode}"
            raise VideoProcessingError(f"Command failed (ffmpeg): {detail}")
    finally:
        if proc.poll() is None:
            proc.kill()
        err.close()


def _graph_arg(graph: str, tmp_files: list[Path]) -> list[str]:
    """The graph can be tens of KB (a 120-clip edit): ffmpeg reads it from a file, not from argv."""
    from services.video.ffmpeg import ffmpeg_version

    handle = tempfile.NamedTemporaryFile("w", suffix=".ffgraph", delete=False, encoding="utf-8")
    handle.write(graph)
    handle.close()
    tmp_files.append(Path(handle.name))
    return ["-/filter_complex", handle.name] if ffmpeg_version() >= (7, 0) else ["-filter_complex_script", handle.name]


def render(timeline: Timeline, out_path, *, quality: str = "final", export: dict | None = None, progress=None, cancel=None,
           spans=None) -> Path:
    """Encode the arrangement. `quality="draft"` is the old fast preview of the whole project; with `export` (the
    project's export block) the encode follows the preset."""
    from services.video.ffmpeg import AUDIO_DELIVERY, FFMPEG, VideoProcessingError, filter_path

    from . import compose

    spec = resolve(export, timeline) if export else None
    if quality == "draft" and spec is None:
        spec = ExportSpec(preset="veryfast", crf=27, audio_kbps=160)
    work = timeline
    if spec is not None:
        w, h = size_for(timeline, spec.short_side if quality != "draft" or export else None)
        work = dataclasses.replace(timeline, width=w, height=h, fps=spec.fps or timeline.fps)
    built = compose.build_graph(work, spans=spans)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp_files: list[Path] = []
    try:
        graph = built.graph
        for token, text in built.texts.items():
            handle = tempfile.NamedTemporaryFile("w", suffix=".ass", delete=False, encoding="utf-8")
            handle.write(text)
            handle.close()
            tmp_files.append(Path(handle.name))
            graph = graph.replace(token, filter_path(handle.name)[1:-1])    # unquoted: the filter already quotes
        command = [FFMPEG, "-y"]
        for source, args in zip(built.inputs, built.input_args):
            command += [*args, "-i", str(source)]
        command += [*_graph_arg(graph, tmp_files), "-map", "[vout]"]
        if built.has_audio:
            audio = list(AUDIO_DELIVERY)
            if spec is not None:
                audio = ["-c:a", "aac", "-b:a", f"{spec.audio_kbps}k", "-ar", "48000"]
            command += ["-map", "[aout]", *audio]
        if spec is None:
            from services.video.ffmpeg import VIDEO_DELIVERY
            command += list(VIDEO_DELIVERY)
        else:
            command += encode_args(spec, draft=(quality == "draft" and not export))
        command += ["-threads", "2", str(out)]
        run_ffmpeg(command, total=built.length, progress=progress, cancel=cancel)
    finally:
        for path in tmp_files:
            try:
                path.unlink()
            except OSError:
                pass
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("تایم‌لاین رندر نشد")
    return out


#: output kinds beyond the normal MP4 → (file extension, Persian label)
FORMATS = {"mp4": ("mp4", "ویدیو"), "gif": ("gif", "GIF"), "frame": ("jpg", "عکسِ یک فریم"), "audio": ("m4a", "فقط صدا")}
GIF_MAX_SECONDS = 20.0           # a GIF is huge; longer ones are cut and the person is told
GIF_FPS, GIF_HEIGHT = 12, 400


def convert(src, dest, fmt: str, *, t0: float | None = None, t1: float | None = None, frame_t: float = 0.0, spec: ExportSpec | None = None,
            cancel=None) -> dict:
    """Turn a finished render into another output: the in–out range only (`mp4`), a GIF, one still frame, or the sound alone.

    Times are seconds of the finished file (the timeline starts at 0). Returns {"cut": seconds actually kept, "note": sentence or ""}.
    Never reads the original media: it works on what the editor already rendered, so every effect, title and mix is in it."""
    import subprocess

    from services.video.ffmpeg import FFMPEG, VideoProcessingError, probe_duration

    src, dest = Path(src), Path(dest)
    total = probe_duration(src)
    a = max(0.0, min(float(t0 or 0.0), total - 0.1))
    b = total if t1 is None else max(a + 0.1, min(float(t1), total))
    note = ""
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    if fmt == "frame":
        t = max(0.0, min(float(frame_t or 0.0), total - 0.04))
        cmd += ["-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dest)]
        kept = 0.0
    elif fmt == "gif":
        if b - a > GIF_MAX_SECONDS:
            b = a + GIF_MAX_SECONDS
            note = f"GIF بیشتر از {int(GIF_MAX_SECONDS)} ثانیه نمی‌شود؛ ابتدای بازه برداشته شد."
        vf = (f"fps={GIF_FPS},scale=-2:{GIF_HEIGHT}:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
              f"[s1][p]paletteuse=dither=bayer:bayer_scale=5")
        cmd += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src), "-an", "-vf", vf, "-loop", "0", str(dest)]
        kept = b - a
    elif fmt == "audio":
        kbps = int(spec.audio_kbps) if spec else 192
        cmd += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src), "-vn", "-c:a", "aac", "-b:a", f"{kbps}k", "-ar", "48000", "-movflags", "+faststart", str(dest)]
        kept = b - a
    else:  # "mp4": only a range of the picture + sound, re-encoded the same way as a normal export
        enc = encode_args(spec) if spec is not None else list(DRAFT_VIDEO)
        kbps = int(spec.audio_kbps) if spec else 160
        cmd += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(src), *enc, "-c:a", "aac", "-b:a", f"{kbps}k", "-ar", "48000", "-threads", "2", str(dest)]
        kept = b - a
    if cancel and cancel():
        raise RenderCancelled()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise VideoProcessingError(f"ساختنِ خروجیِ «{FORMATS.get(fmt, ('', fmt))[1]}» نشد: {(r.stderr or '').strip()[-200:]}")
    return {"cut": round(kept, 2), "note": note}


def render_preview(timeline: Timeline, out_path, t0: float, t1: float, *, height: int = 360, progress=None, cancel=None,
                   spans=None) -> dict:
    """«پیش‌نمایشِ دقیقِ این بازه»: the real graph for [t0, t1] at a small size — what the browser cannot do exactly
    (stabilise, denoise, the xfade library, chroma-key quality, speed ramps …) is all here."""
    from . import timeline as tlmod

    t1 = min(float(t1), t0 + 20.0, max(t0 + 0.2, timeline.length))
    part = tlmod.window(timeline, t0, t1)
    if not any(t.clips for t in part.tracks if t.kind == "video"):
        raise TimelineError("در این بازه تصویری نیست.")
    w, h = size_for(timeline, height)
    small = dataclasses.replace(part, width=w, height=h, fps=min(timeline.fps, 24))
    spec = ExportSpec(preset="veryfast", crf=29, audio_kbps=96)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    from services.video.ffmpeg import FFMPEG, VideoProcessingError, filter_path

    from . import compose

    built = compose.build_graph(small, spans=spans, need_base=False)
    tmp_files: list[Path] = []
    try:
        graph = built.graph
        for token, text in built.texts.items():
            handle = tempfile.NamedTemporaryFile("w", suffix=".ass", delete=False, encoding="utf-8")
            handle.write(text)
            handle.close()
            tmp_files.append(Path(handle.name))
            graph = graph.replace(token, filter_path(handle.name)[1:-1])
        command = [FFMPEG, "-y"]
        for source, args in zip(built.inputs, built.input_args):
            command += [*args, "-i", str(source)]
        command += [*_graph_arg(graph, tmp_files), "-map", "[vout]"]
        if built.has_audio:
            command += ["-map", "[aout]", "-c:a", "aac", "-b:a", "96k", "-ar", "48000"]
        command += [*encode_args(spec), "-threads", "2", str(out)]
        run_ffmpeg(command, total=built.length, progress=progress, cancel=cancel)
    finally:
        for path in tmp_files:
            try:
                path.unlink()
            except OSError:
                pass
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("پیش‌نمایشِ دقیق ساخته نشد")
    return {"path": out, "t0": t0, "t1": t1, "size": f"{w}x{h}", "seconds": round(built.length, 2), "notes": built.notes}
