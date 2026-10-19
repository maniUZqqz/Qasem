"""Per-frame statistics from one ffmpeg pass — the numbers a sampled PNG cannot give.

Flicker, a frozen tail and a jump cut all live *between consecutive frames*.
Eight stills taken half a second apart cannot see any of them: a light that
strobes at 4 Hz looks perfectly steady when you only look every 0.5 s, and a
clip that freezes for its last second is caught only if a sample happens to
fall inside the freeze. Measured here on a synthetic clip with every fourth
frame brighter: consecutive-frame ΔY = 37, half-second-apart ΔY = 2.7.

So this module reads **every** frame, once, with ffmpeg doing the arithmetic:

    scale=256:-2, signalstats, freezedetect, blackdetect, metadata=print

`signalstats` gives per-frame mean luma (YAVG), the mean absolute difference to
the previous frame (YDIF) and mean saturation; `freezedetect` and `blackdetect`
give exact spans. One pass over a 5-second 832×480 segment costs well under a
second once the frame is downscaled first; without the downscale it is ten
times that, which is why `scale` comes first in the chain.

**Camera shake is the one thing signalstats cannot say**, because it is a
displacement, not a brightness. `camera_shake` decodes about a second of
consecutive low-resolution frames and measures the global translation between
each pair (phase correlation). Intended camera motion is a *smooth* trajectory;
shake is the jitter left over after that trajectory is removed. A pan and a
handheld wobble have the same mean displacement and very different residuals,
which is exactly the distinction the old "frames differ a lot" heuristic could
not draw — it sent every moving shot through a two-pass stabiliser and a crop
it did not need.

Nothing here raises. A measurement that could not be taken comes back absent,
and the callers treat "absent" as "do not decide on this", never as "fine".
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from .ffmpeg import FFMPEG, VideoProcessingError, _run, probe_video

logger = logging.getLogger(__name__)

#: Width the whole clip is downscaled to before statistics. Brightness and
#: frame-to-frame difference survive the downscale; the cost does not.
STATS_WIDTH = 256

#: freezedetect: noise tolerance (fraction of full scale) and the shortest
#: still stretch worth reporting. The tolerance is tight on purpose — 0.001 is
#: a quarter of a luma step, which duplicated frames stay under even after
#: H.264 — because a product barely moving against a flat studio background
#: changes so few pixels that a looser tolerance (0.003) called it frozen.
#: 0.4 s is longer than any frame-rate hiccup and shorter than a freeze a
#: viewer notices.
FREEZE_NOISE = 0.001
FREEZE_MIN_SECONDS = 0.4

#: blackdetect: at least this long, with this share of dark pixels.
BLACK_MIN_SECONDS = 0.3
BLACK_PIX_THRESHOLD = 0.10

#: A consecutive-frame YDIF above this is a cut or a scene change, not motion.
#: Excluded from the flicker measurement so a deliberate cut does not read as
#: a strobe.
SCENE_CHANGE_DIFF = 40.0

#: YDIF above this, after the first frame, is a visual jump — a Wan clip that
#: teleports its subject or a hard cut inside what should be one shot.
JUMP_DIFF = 60.0

#: Luma deltas smaller than this are noise, not flicker.
FLICKER_MIN_DELTA = 4.0

_KEY = re.compile(r"^lavfi\.(?P<key>[\w.]+)=(?P<value>.*)$")
_FRAME = re.compile(r"^frame:(?P<n>\d+)\s+pts:(?P<pts>-?\d+)\s+pts_time:(?P<t>-?[\d.]+)")


def _to_full_range(value: float, color_range: str) -> float:
    """Limited-range Y (16–235) → 0–255, so every threshold in the codebase,
    which was written against Pillow's full-range histograms, keeps meaning
    what it says. Full-range sources pass through untouched."""
    if color_range == "pc":
        return max(0.0, min(255.0, value))
    return max(0.0, min(255.0, (value - 16.0) * 255.0 / 219.0))


def _parse(text: str):
    """metadata=print output → (frames, freezes, blacks, open_freeze, open_black).

    The two `open_*` values are the start of a freeze or black run that never
    got its `_end` line because the clip ended inside it."""
    frames: list[dict] = []
    current: dict | None = None
    freezes: list[tuple[float, float]] = []
    blacks: list[tuple[float, float]] = []
    freeze_start = None
    black_start = None

    for line in text.splitlines():
        line = line.strip()
        head = _FRAME.match(line)
        if head:
            current = {"n": int(head.group("n")), "t": float(head.group("t"))}
            frames.append(current)
            continue
        if current is None:
            continue
        pair = _KEY.match(line)
        if not pair:
            continue
        key, raw = pair.group("key"), pair.group("value").strip()
        try:
            value = float(raw)
        except ValueError:
            continue
        if key == "signalstats.YAVG":
            current["yavg"] = value
        elif key == "signalstats.YDIF":
            current["ydif"] = value
        elif key == "signalstats.SATAVG":
            current["sat"] = value
        elif key == "freezedetect.freeze_start":
            freeze_start = value
        elif key == "freezedetect.freeze_end":
            if freeze_start is not None:
                freezes.append((freeze_start, value))
                freeze_start = None
        elif key == "black_start":
            black_start = value
        elif key == "black_end":
            if black_start is not None:
                blacks.append((black_start, value))
                black_start = None

    return frames, freezes, blacks, freeze_start, black_start


def measure(video_path, work_dir, *, width: int = STATS_WIDTH) -> dict:
    """Everything one pass can say about a clip. Empty dict when it cannot run."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    report = work / "frame_stats.txt"

    try:
        shape = probe_video(video_path)
    except Exception as exc:  # noqa: BLE001
        logger.info("frame_stats: could not probe %s: %s", video_path, exc)
        return {}

    log_path = str(report).replace("\\", "/").replace(":", r"\:")
    chain = (
        f"scale={width}:-2,"
        "signalstats,"
        f"freezedetect=n={FREEZE_NOISE}:d={FREEZE_MIN_SECONDS},"
        f"blackdetect=d={BLACK_MIN_SECONDS}:pix_th={BLACK_PIX_THRESHOLD},"
        f"metadata=print:file='{log_path}'"
    )
    try:
        _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path),
              "-vf", chain, "-an", "-f", "null", "-"])
        text = report.read_text(encoding="utf-8", errors="replace")
    except (VideoProcessingError, OSError) as exc:
        logger.info("frame_stats: ffmpeg pass failed on %s: %s", video_path, exc)
        return {}
    finally:
        try:
            report.unlink()
        except OSError:
            pass

    frames, freezes, blacks, open_freeze, open_black = _parse(text)
    duration = float(shape.get("duration") or 0.0)
    if not duration and frames:
        duration = frames[-1]["t"]
    # A freeze or black run that reaches the end of the file never gets its
    # *_end line; close it at the duration so a frozen tail is counted.
    if open_freeze is not None and duration:
        freezes.append((open_freeze, duration))
    if open_black is not None and duration:
        blacks.append((open_black, duration))

    yavg = [_to_full_range(f["yavg"], shape["color_range"]) for f in frames if "yavg" in f]
    ydif = [f["ydif"] for f in frames[1:] if "ydif" in f]
    if len(yavg) < 2:
        return {}

    # Flicker: the largest brightness step between two neighbouring frames that
    # is not a scene change, and how often the brightness reverses direction.
    steps = []
    for index in range(1, len(yavg)):
        diff = ydif[index - 1] if index - 1 < len(ydif) else 0.0
        if diff > SCENE_CHANGE_DIFF:
            continue
        steps.append(yavg[index] - yavg[index - 1])
    big = [s for s in steps if abs(s) >= FLICKER_MIN_DELTA]
    alternations = sum(
        1 for a, b in zip(big, big[1:]) if (a > 0) != (b > 0)
    )
    frozen = sum(max(0.0, end - start) for start, end in freezes)
    black = sum(max(0.0, end - start) for start, end in blacks)
    jumps = sum(1 for d in ydif if d > JUMP_DIFF)

    ordered = sorted(yavg)

    def pct(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(len(ordered) * p))]

    return {
        "frames": len(frames),
        "fps": shape["fps"],
        "width": shape["width"],
        "height": shape["height"],
        "duration": round(duration, 3),
        "yavg_p5": round(pct(0.05), 1),
        "yavg_p50": round(pct(0.5), 1),
        "yavg_p95": round(pct(0.95), 1),
        "yavg_first": round(yavg[0], 1),
        "yavg_last": round(yavg[-1], 1),
        "flicker": round(max((abs(s) for s in steps), default=0.0), 1),
        "flicker_alternations": alternations,
        "flicker_rate": round(alternations / duration, 2) if duration else 0.0,
        "mean_ydif": round(sum(ydif) / len(ydif), 2) if ydif else 0.0,
        "max_ydif": round(max(ydif), 1) if ydif else 0.0,
        "motion_jumps": jumps,
        "frozen_seconds": round(frozen, 2),
        "frozen_share": round(frozen / duration, 3) if duration else 0.0,
        "longest_freeze": round(max((e - s for s, e in freezes), default=0.0), 2),
        "black_seconds": round(black, 2),
        "black_share": round(black / duration, 3) if duration else 0.0,
        "saturation": round(
            sum(f.get("sat", 0.0) for f in frames) / len(frames), 1
        ),
    }


# ------------------------------------------------------------------ shake


def camera_shake(video_path, *, at: float | None = None, seconds: float = 1.0,
                 width: int = 160) -> dict:
    """Shake versus intended motion, from ~1 s of consecutive frames.

    Returns {"shake": residual as a fraction of frame width per frame,
    "pan": mean displacement as a fraction of width, "frames": n} — or an
    empty dict when OpenCV is missing or the clip could not be read.

    Calibrated on synthetic clips: a smooth pan and a static shot both sit
    below 0.002, a mild handheld wobble at 0.005, a strong one at 0.02–0.035.
    """
    try:
        import numpy as np
    except ImportError:
        return {}
    try:
        import cv2
    except ImportError:
        return {}

    try:
        shape = probe_video(video_path)
    except Exception as exc:  # noqa: BLE001
        logger.info("camera_shake: could not probe %s: %s", video_path, exc)
        return {}
    if not shape["width"] or not shape["height"]:
        return {}
    duration = float(shape.get("duration") or 0.0)
    if at is None:
        # The middle of the clip: the start often has the hand still settling.
        at = max(0.0, duration / 2 - seconds / 2)
    height = max(2, int(round(shape["height"] * width / shape["width"] / 2)) * 2)

    try:
        result = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error",
             "-ss", f"{at:.3f}", "-t", f"{seconds:.3f}", "-i", str(video_path),
             "-vf", f"scale={width}:{height},format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=180,
        )
    except OSError as exc:
        logger.info("camera_shake: ffmpeg unavailable: %s", exc)
        return {}
    if result.returncode != 0:
        return {}

    raw = np.frombuffer(result.stdout, np.uint8)
    count = len(raw) // (width * height)
    if count < 6:
        return {}
    frames = raw[: count * width * height].reshape(count, height, width).astype(np.float32)

    # A cut inside the window is not camera movement. Phase correlation between
    # two unrelated pictures returns a large, meaningless shift, so pairs whose
    # pixels changed wholesale are dropped before the trajectory is fitted.
    pairs = [
        (a, b) for a, b in zip(frames[:-1], frames[1:])
        if float(np.abs(b - a).mean()) <= SCENE_CHANGE_DIFF
    ]
    if len(pairs) < 6:
        return {}
    shifts = np.array([cv2.phaseCorrelate(a, b)[0] for a, b in pairs])
    kernel = np.ones(5) / 5
    smooth = np.stack(
        [np.convolve(shifts[:, axis], kernel, mode="same") for axis in range(2)], axis=1,
    )
    residual = np.hypot(*(shifts - smooth).T)
    return {
        "shake": round(float(residual.mean() / width), 4),
        "pan": round(float(np.hypot(*shifts.mean(axis=0)) / width), 4),
        "frames": int(count),
    }
