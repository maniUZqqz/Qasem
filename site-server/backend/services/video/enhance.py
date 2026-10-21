"""The finishing pass: a generated video made smoother, sharper and bigger — with code.

Wan 2.2 renders 832×480 at 16 fps, and the node saves it at about 400 kb/s.
On a phone that reads as "low quality" before anyone looks at the content:
16 fps judders on every camera move, 480 lines are soft next to everything else
in the feed, and the low bitrate leaves blocks and bands in the warm, smooth
gradients a product shot is full of. A bigger generation model is not the
answer (it would not fit the 12 GB card); this pass is. It runs on the site
server with ffmpeg alone, so it works whether or not the GPU node is online.

What it does, in this order (each step is chosen for where it is cheapest and
does the most good):

1. **Light denoise** (`hqdn3d`) at the source size — removes the encoder's
   mosquito noise, which would otherwise be read as motion by step 3 and
   sharpened into grit by step 5.
2. **Deband** — smooths the stair-steps the low bitrate left in gradients.
3. **Motion interpolation 16 → 32 fps** (`minterpolate`, motion-compensated,
   adaptive overlapped blocks). Done at the SOURCE size: measured on this
   2-core server it is ~22 s per 5-second segment at 832×480 when the CPU is
   free, and it would cost 2.25× that after the upscale. Its scene-change
   detector leaves hard cuts alone instead of blending across them.
4. **Upscale to 720p** with lanczos. 832×480 is within 3% of 16:9, so it is
   scaled to cover 1280×720 and the few rows of overflow are cropped — a true
   16:9 frame no platform letterboxes. Other shapes keep their own aspect.
5. **Contrast-adaptive sharpening** (`cas`) — restores edge contrast lost to
   the upscale without the halos of a plain unsharp mask.
6. **Encode** once, x264 CRF 18, yuv420p, +faststart. Preset `medium` by
   default: on this server `slow` saved 2% of the size for the same CRF while
   competing with the 3D renderer for the same two cores.

Rules that make it safe to run on every video:

* **Skip-safe.** Any failure returns `ok=False` and the caller keeps the raw
  video; a finishing pass must never cost the shop the video itself.
* **Same length.** `minterpolate` ends one source frame early; the last frame
  is held and the output cut to the source's exact duration, so narration,
  effects and subtitles timed against the segments still line up.
* **Nothing done twice.** A source already at the target fps or size skips that
  step; the result says what was actually applied.
* **Gentle.** ffmpeg runs under `nice`, because the same two cores serve the
  website and other sites on this server.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .ffmpeg import FFMPEG, VideoProcessingError, _quiet, probe_video, stderr_summary

logger = logging.getLogger(__name__)

#: 832×480 is 1.733, 16:9 is 1.778 — 2.5% apart. Within this tolerance the
#: frame is scaled to COVER the standard size and the overflow cropped.
ASPECT_TOLERANCE = 0.04

DEBAND = "deband=1thr=0.015:2thr=0.015:3thr=0.015:range=16:blur=1"


def _conf(name: str, default):
    try:
        from django.conf import settings

        return (getattr(settings, "UPMARKET_AI", None) or {}).get(name, default)
    except Exception:  # noqa: BLE001 — usable without Django settings too
        return default


def config() -> dict:
    """The finishing settings, from `settings.UPMARKET_AI` (`VIDEO_ENHANCE_*`)."""
    return {
        "enabled": bool(_conf("VIDEO_ENHANCE", True)),
        "fps": int(_conf("VIDEO_ENHANCE_FPS", 32)),
        # mci = motion-compensated (best); blend = cross-fade frames (fast,
        # ghosts on motion); off = keep the source frame rate.
        "interpolation": str(_conf("VIDEO_ENHANCE_INTERPOLATION", "mci")).lower(),
        "short_side": int(_conf("VIDEO_ENHANCE_SHORT_SIDE", 720)),
        "long_side": int(_conf("VIDEO_ENHANCE_LONG_SIDE", 1280)),
        "sharpen": float(_conf("VIDEO_ENHANCE_SHARPEN", 0.45)),
        "denoise": str(_conf("VIDEO_ENHANCE_DENOISE", "1.5:1.5:4:4") or ""),
        "deband": bool(_conf("VIDEO_ENHANCE_DEBAND", True)),
        "crf": int(_conf("VIDEO_ENHANCE_CRF", 18)),
        "preset": str(_conf("VIDEO_ENHANCE_PRESET", "medium")),
        "nice": int(_conf("VIDEO_ENHANCE_NICE", 10)),
        # Seconds of wall clock allowed per second of video. Measured: ~13–19
        # s/s with the 3D renderer busy on the same cores; 40 leaves room.
        "seconds_per_second": float(_conf("VIDEO_ENHANCE_SECONDS_PER_SECOND", 40)),
        "min_timeout": float(_conf("VIDEO_ENHANCE_MIN_TIMEOUT", 600)),
        "max_timeout": float(_conf("VIDEO_ENHANCE_MAX_TIMEOUT", 3600)),
    }


def target_size(width: int, height: int, short_side: int = 720,
                long_side: int = 1280) -> tuple[int, int, str]:
    """(width, height, mode) for the output frame.

    mode: `cover` = scale to cover the standard frame and crop the overflow
    (source within ASPECT_TOLERANCE of it); `fit` = keep the source aspect,
    short side to `short_side`; `none` = already that big, leave it.
    """
    if width <= 0 or height <= 0 or short_side <= 0:
        return width, height, "none"
    portrait = height > width
    src_short, src_long = (width, height) if portrait else (height, width)
    if src_short >= short_side:
        return width, height, "none"
    wanted = long_side / short_side
    ratio = src_long / src_short
    if long_side > 0 and abs(ratio - wanted) / wanted <= ASPECT_TOLERANCE:
        return (short_side, long_side, "cover") if portrait else (long_side, short_side, "cover")
    new_long = int(round(src_long * short_side / src_short / 2.0)) * 2
    return (short_side, new_long, "fit") if portrait else (new_long, short_side, "fit")


def build_filters(info: dict, cfg: dict) -> tuple[list[str], list[str], dict]:
    """(filter chain, steps applied, expected output shape) for one source."""
    chain: list[str] = []
    applied: list[str] = []
    if cfg.get("denoise"):
        chain.append(f"hqdn3d={cfg['denoise']}")
        applied.append("denoise")
    if cfg.get("deband"):
        chain.append(DEBAND)
        applied.append("deband")

    fps = float(info.get("fps") or 0) or 16.0
    target_fps = int(cfg.get("fps") or 0)
    out_fps = fps
    mode = cfg.get("interpolation", "mci")
    if mode != "off" and target_fps and target_fps > fps * 1.05:
        # Two cloned source frames BEFORE interpolating: minterpolate stops at
        # the last input frame and ignores a tpad placed after it (measured on
        # script 1: 483 frames = 15.094 s for a 15.188 s source; padded first,
        # 486 frames = exactly 15.188 s once -t cuts it).
        chain.append("tpad=stop_mode=clone:stop=2")
        if mode == "blend":
            chain.append(f"framerate=fps={target_fps}")
        else:
            chain.append(
                f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc"
                ":me_mode=bidir:vsbmc=1:scd=fdiff"
            )
        applied.append(f"interpolate_{mode}")
        out_fps = float(target_fps)

    width, height = int(info.get("width") or 0), int(info.get("height") or 0)
    out_w, out_h, fit = target_size(width, height, int(cfg.get("short_side") or 0),
                                    int(cfg.get("long_side") or 0))
    if fit == "cover":
        chain.append(
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase"
            f":force_divisible_by=2:flags=lanczos,crop={out_w}:{out_h}"
        )
        applied.append("upscale")
    elif fit == "fit":
        chain.append(f"scale={out_w}:{out_h}:flags=lanczos")
        applied.append("upscale")

    sharpen = float(cfg.get("sharpen") or 0)
    if sharpen > 0:
        chain.append(f"cas=strength={min(1.0, sharpen):.2f}")
        applied.append("sharpen")

    # The output is cut to the source's exact length (-t), so the picture is
    # never shorter than the sound laid on it later.
    chain.append("format=yuv420p")
    return chain, applied, {"width": out_w, "height": out_h, "fps": out_fps}


def _describe(path: Path) -> dict:
    info = probe_video(path)
    return {
        "width": info["width"],
        "height": info["height"],
        "fps": info["fps"],
        "duration": round(float(info["duration"] or 0), 3),
        "has_audio": info["has_audio"],
        "bytes": path.stat().st_size if path.exists() else 0,
    }


@dataclass
class EnhanceResult:
    ok: bool
    path: Path | None = None
    applied: list[str] = field(default_factory=list)
    seconds: float = 0.0
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    note: str = ""
    engine: str = "ffmpeg"
    settings: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "file": self.path.name if self.path else None,
            "applied": self.applied,
            "seconds": round(self.seconds, 1),
            "before": self.before,
            "after": self.after,
            "note": self.note,
            "engine": self.engine,
            "settings": self.settings,
        }


def _lower_priority(level: int):
    if os.name != "posix" or level <= 0:
        return None

    def apply():  # runs in the child between fork and exec
        try:
            os.nice(level)
        except OSError:
            pass

    return apply


def _run_niced(cmd: list, *, timeout: float, nice: int) -> None:
    cmd = _quiet(cmd)
    try:
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=timeout,
            preexec_fn=_lower_priority(nice),
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError(f"{cmd[0]} binary not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoProcessingError(
            f"بهبود کیفیت بیش از {timeout:.0f} ثانیه طول کشید و متوقف شد"
        ) from exc
    if result.returncode != 0:
        detail = stderr_summary(result.stderr) or f"exit code {result.returncode}"
        raise VideoProcessingError(f"ffmpeg: {detail}")


def enhance(source, out_path, *, cfg: dict | None = None) -> EnhanceResult:
    """Finish one video. Never raises: `ok=False` means keep the source."""
    cfg = {**config(), **(cfg or {})}
    source = Path(source)
    out = Path(out_path)
    started = time.monotonic()
    settings_used = {k: cfg[k] for k in ("fps", "interpolation", "short_side", "long_side",
                                         "sharpen", "denoise", "deband", "crf", "preset")}
    if not cfg.get("enabled", True):
        return EnhanceResult(ok=False, note="بهبود کیفیت خاموش است", settings=settings_used)
    try:
        info = probe_video(source)
        before = _describe(source)
    except Exception as exc:  # noqa: BLE001 — unreadable source: keep it as it is
        return EnhanceResult(ok=False, note=f"ویدیو خوانده نشد: {exc}"[:300],
                             settings=settings_used)

    chain, applied, expected = build_filters(info, cfg)
    if not any(step.startswith("interpolate") or step == "upscale" for step in applied):
        # Already at the target size and frame rate: re-encoding it only to
        # denoise and sharpen is not worth a generation of compression.
        return EnhanceResult(ok=False, before=before, settings=settings_used,
                             note="ویدیو از قبل در اندازه و نرخ فریم هدف است")

    duration = float(info.get("duration") or 0)
    timeout = max(float(cfg["min_timeout"]),
                  min(float(cfg["max_timeout"]), duration * float(cfg["seconds_per_second"])))
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.stem + ".part" + out.suffix)
    command = [FFMPEG, "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
               "-vf", ",".join(chain)]
    if duration > 0:
        command += ["-t", f"{duration:.3f}"]
    command += [
        "-c:v", "libx264", "-preset", str(cfg["preset"]), "-crf", str(int(cfg["crf"])),
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "copy", "-movflags", "+faststart", str(partial),
    ]
    try:
        _run_niced(command, timeout=timeout, nice=int(cfg.get("nice") or 0))
        after_info = probe_video(partial)
        got = float(after_info.get("duration") or 0)
        # Less than one source frame of slack: narration, effects and
        # subtitles are timed against the source length.
        if duration and got < duration - 0.05:
            raise VideoProcessingError(
                f"خروجی کوتاه‌تر از اصل است ({got:.2f} از {duration:.2f} ثانیه)"
            )
        if (after_info["width"], after_info["height"]) != (expected["width"], expected["height"]):
            raise VideoProcessingError(
                f"اندازه‌ی خروجی {after_info['width']}×{after_info['height']} است، "
                f"نه {expected['width']}×{expected['height']}"
            )
        os.replace(partial, out)
        after = _describe(out)
    except Exception as exc:  # noqa: BLE001 — skip-safe by contract
        partial.unlink(missing_ok=True)
        logger.warning("Video enhancement of %s failed: %s", source, exc)
        return EnhanceResult(ok=False, before=before, applied=applied,
                             seconds=time.monotonic() - started, settings=settings_used,
                             note=f"بهبود کیفیت انجام نشد و ویدیوی اصلی ماند: {exc}"[:400])
    return EnhanceResult(ok=True, path=out, applied=applied, before=before, after=after,
                         seconds=time.monotonic() - started, settings=settings_used)
