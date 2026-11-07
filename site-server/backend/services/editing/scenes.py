"""Scene-cut detection for the manual editor («تشخیصِ برش‌ها»): where does a video change shot?

`analysis.shot_boundaries` answers a different question (at most 8 shots, each at least 1 s, to colour-correct per shot). The editor wants EVERY
hard cut inside the part of the file a clip uses, as source seconds, with a sensitivity the person can change. ffmpeg's `scdet` on a small copy
of the picture is fast (many times faster than real time) and needs no GPU.
"""
from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

#: scdet score (0–100) per sensitivity: «زیاد» finds soft cuts too, «کم» only obvious ones
SENSITIVITY = {"low": 25.0, "normal": 12.0, "high": 6.0}
MIN_GAP = 0.4              # two cuts closer than this are one cut (flashes, dissolves)
MAX_CUTS = 300
MAX_SECONDS = 1800         # never scan more than half an hour in one request


def detect_cuts(path, start: float, end: float, sensitivity: str = "normal") -> dict:
    """Cuts strictly inside (start, end) as SOURCE seconds, sorted. {"cuts": [...], "threshold": x, "scanned": seconds}."""
    from services.video.ffmpeg import FFMPEG

    threshold = SENSITIVITY.get(sensitivity, SENSITIVITY["normal"])
    start = max(0.0, float(start))
    span = max(0.1, min(float(end) - start, MAX_SECONDS))
    try:
        r = subprocess.run(
            [FFMPEG, "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", str(path), "-an",
             "-vf", f"scale=320:-2,scdet=threshold={threshold}", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, stdin=subprocess.DEVNULL)
        raw = sorted(float(t) for t in re.findall(r"lavfi\.scd\.time:\s*([0-9.]+)", r.stderr))
    except Exception as exc:  # noqa: BLE001 — "no cuts found" is the safe answer
        logger.info("scene detection failed for %s: %s", path, exc)
        raw = []
    cuts: list[float] = []
    for t in raw:
        abs_t = round(start + t, 3)
        if abs_t <= start + MIN_GAP or abs_t >= start + span - MIN_GAP:
            continue
        if cuts and abs_t - cuts[-1] < MIN_GAP:
            continue
        cuts.append(abs_t)
    return {"cuts": cuts[:MAX_CUTS], "threshold": threshold, "scanned": round(span, 2)}
