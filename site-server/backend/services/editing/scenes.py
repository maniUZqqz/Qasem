"""Scene-cut detection for the manual editor («تشخیصِ برش‌ها») and the automatic edit: where does a video change shot?

`analysis.shot_boundaries` answers a different question (at most 8 shots, each at least 1 s, to colour-correct per shot). The editor wants EVERY
hard cut inside the part of the file a clip uses, as source seconds, with a sensitivity the person can change.

Why this is not ffmpeg's `scdet` any more (1405/08/23, the owner's own video): `scdet` scores a hard cut from a selfie camera to a recorded phone
screen at only 10 (its default bar for "a cut" was 12) because both pictures are bright and mostly low-contrast - the frame-to-frame score is a
mean of per-pixel differences squashed against the previous change.  So the automatic edit never split that video, treated the face part as a
screen recording and corrected neither its light nor its framing.  A hard cut changes the PICTURE, not just the pixels, so two measures are
combined on a tiny (64x36) copy of every frame:

* the mean absolute luma difference between a frame and the one before it (a real cut: 28-39 on the owner's video; the interface of the recorded
  app changing page, scrolling or a hand moving: 2-9),
* the distance between the colour histograms of the three frames BEFORE and the three AFTER (0.5 x L1, 0..1) - a camera flash or a single
  glitch frame does not move it, a different scene does.

A frame is a cut when both measures pass the bar of the chosen sensitivity.  One pass of ffmpeg over a 64x36 copy is several times faster than
real time and needs no GPU; `scdet` stays as the fallback if the numpy path ever fails.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading

import numpy as np

logger = logging.getLogger(__name__)

#: legacy `scdet` score (0-100) per sensitivity, kept for the fallback path and for callers that compare levels: «زیاد» finds soft cuts too, «کم» only obvious ones
SENSITIVITY = {"low": 25.0, "normal": 12.0, "high": 6.0}
#: the bars of the combined detector per sensitivity: (mean luma difference 0-255, histogram distance 0-1).  The luma bar is what separates a
#: cut (28-39 on the owner's video) from an app changing page (2-9); the histogram bar only rejects a flash or a brightness jump of the same picture.
RULES = {"low": (26.0, 0.12), "normal": (16.0, 0.12), "high": (11.0, 0.10)}
THUMB_W, THUMB_H = 64, 36
SCAN_FPS = 30              # frames per second looked at (a 25 / 30 fps source is compared frame by frame; a 60 fps one every other frame)
BINS = 6                   # histogram bins per colour channel
WINDOW = 3                 # frames on each side of a candidate for the histogram comparison
MIN_GAP = 0.4              # two cuts closer than this are one cut (flashes, dissolves)
MAX_CUTS = 300
MAX_SECONDS = 1800         # never scan more than half an hour in one request
CHUNK_FRAMES = 600
SCAN_TIMEOUT_S = 900


def _frames(path, start: float, span: float, ffmpeg: str):
    """Yield (chunk of frames as uint8 [n, H, W, 3]) from one ffmpeg pass over the thumbnails of the stretch; raises on a failed run."""
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", str(path), "-an", "-sn",
           "-vf", f"fps={SCAN_FPS},scale={THUMB_W}:{THUMB_H}:flags=area,format=rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    timer = threading.Timer(SCAN_TIMEOUT_S, proc.kill)
    timer.start()
    frame_bytes = THUMB_W * THUMB_H * 3
    try:
        while True:
            raw = proc.stdout.read(frame_bytes * CHUNK_FRAMES)
            if not raw:
                break
            n = len(raw) // frame_bytes
            if n:
                yield np.frombuffer(raw[: n * frame_bytes], dtype=np.uint8).reshape(n, THUMB_H, THUMB_W, 3)
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.wait()


def measure(path, start: float, span: float, ffmpeg: str) -> tuple[np.ndarray, np.ndarray]:
    """(mad[n], hist_dist[n]) per frame of the stretch at SCAN_FPS: `mad[i]` = mean |luma(i) - luma(i-1)|, `hist_dist[i]` = the histogram distance
    between the WINDOW frames before and the WINDOW frames from frame i on (0 where the window does not fit)."""
    mads: list[np.ndarray] = []
    hists: list[np.ndarray] = []
    prev = None
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    for chunk in _frames(path, start, span, ffmpeg):
        gray = chunk.astype(np.float32) @ weights                               # [n, H, W]
        first = np.abs(gray[0] - prev).mean() if prev is not None else 0.0
        diff = np.abs(gray[1:] - gray[:-1]).mean(axis=(1, 2)) if len(gray) > 1 else np.zeros(0, dtype=np.float32)
        mads.append(np.concatenate([[first], diff]).astype(np.float32))
        prev = gray[-1]
        q = (chunk.astype(np.int32) * BINS) // 256
        idx = (q[..., 0] * BINS + q[..., 1]) * BINS + q[..., 2]                  # [n, H, W] -> one colour cell per pixel
        flat = idx.reshape(len(idx), -1)
        h = np.stack([np.bincount(row, minlength=BINS ** 3) for row in flat]).astype(np.float32)
        hists.append(h / float(flat.shape[1]))
    if not mads:
        return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)
    mad = np.concatenate(mads)
    hist = np.concatenate(hists)
    n = len(mad)
    dist = np.zeros(n, dtype=np.float32)
    if n >= 2 * WINDOW:
        csum = np.concatenate([np.zeros((1, hist.shape[1]), dtype=np.float64), np.cumsum(hist.astype(np.float64), axis=0)])
        i = np.arange(WINDOW, n - WINDOW + 1)
        after = (csum[i + WINDOW] - csum[i]) / WINDOW
        before = (csum[i] - csum[i - WINDOW]) / WINDOW
        dist[i] = (0.5 * np.abs(after - before).sum(axis=1)).astype(np.float32)
    return mad, dist


def pick_cuts(mad: np.ndarray, dist: np.ndarray, sensitivity: str, fps: float = SCAN_FPS) -> list[tuple[float, float, float]]:
    """[(seconds from the start of the scan, mad, hist_dist)] of the frames that are a cut at this sensitivity, one per MIN_GAP (the strongest)."""
    pix_bar, hist_bar = RULES.get(sensitivity, RULES["normal"])
    hits = np.flatnonzero((mad >= pix_bar) & (dist >= hist_bar))
    out: list[tuple[float, float, float]] = []
    for i in hits:
        t = float(i) / fps
        if out and t - out[-1][0] < MIN_GAP:
            if mad[i] > out[-1][1]:
                out[-1] = (t, float(mad[i]), float(dist[i]))          # the same event: keep its sharpest frame
            continue
        out.append((t, float(mad[i]), float(dist[i])))
    return out


def _scdet(path, start: float, span: float, threshold: float, ffmpeg: str) -> list[float]:
    """The old detector (ffmpeg scdet on a 320 px copy): seconds from `start`."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", str(path), "-an",
                        "-vf", f"scale=320:-2,scdet=threshold={threshold}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, stdin=subprocess.DEVNULL)
    return sorted(float(t) for t in re.findall(r"lavfi\.scd\.time:\s*([0-9.]+)", r.stderr))


def detect_cuts(path, start: float, end: float, sensitivity: str = "normal") -> dict:
    """Cuts strictly inside (start, end) as SOURCE seconds, sorted. {"cuts": [...], "threshold": x, "scanned": seconds, "engine": "frames"|"scdet"}."""
    from services.video.ffmpeg import FFMPEG

    sens = sensitivity if sensitivity in RULES else "normal"
    threshold = SENSITIVITY[sens]
    start = max(0.0, float(start))
    span = max(0.1, min(float(end) - start, MAX_SECONDS))
    engine = "frames"
    try:
        mad, dist = measure(path, start, span, FFMPEG)
        if not len(mad):
            raise RuntimeError("no frames decoded")
        raw = [t for t, _m, _d in pick_cuts(mad, dist, sens)]
    except Exception as exc:  # noqa: BLE001 - the numpy path must never cost the owner the edit: fall back to the old detector
        logger.info("frame-based shot detection failed for %s (%s); using scdet", path, exc)
        engine = "scdet"
        try:
            raw = _scdet(path, start, span, threshold, FFMPEG)
        except Exception as exc2:  # noqa: BLE001 - "no cuts found" is the safe answer
            logger.info("scene detection failed for %s: %s", path, exc2)
            raw = []
    cuts: list[float] = []
    for t in raw:
        abs_t = round(start + t, 3)
        if abs_t <= start + MIN_GAP or abs_t >= start + span - MIN_GAP:
            continue
        if cuts and abs_t - cuts[-1] < MIN_GAP:
            continue
        cuts.append(abs_t)
    return {"cuts": cuts[:MAX_CUTS], "threshold": threshold, "scanned": round(span, 2), "engine": engine}
