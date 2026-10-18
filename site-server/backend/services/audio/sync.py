"""Put each sound on the frame where its event happens.

The script model writes "door, 1.0 s into the scene" before the video exists.
Wan then opens the door whenever it likes — at 2.3 s, say — and a door sound
that plays 1.3 seconds before the door moves is worse than no door sound: it
announces that the sound was pasted on. This module looks at the rendered
frames and moves the sound to the event.

**What is measured.** Motion, not meaning. Each frame is compared with the one
before it after removing the camera's own movement (every Wan scene has a slow
camera move on purpose — see scene_state — and without this step the whole
frame "moves" all the time). What is left is *local* motion: a door swinging,
a hand reaching, a spray of mist. It is summarised per frame as how much the
most active region moves beyond the typical region.

* **One-off events** (door, switch, shutter, spray, pour, zipper…) go to the
  steepest rise of local motion near the planned time. The sound's own first
  transient — not its file start — is what lands on that frame.
* **Rhythms** (footsteps, heels, typing) take their period from the video's
  motion, and every step in the picture gets its own step sound: the
  recording is cut into its individual steps (real footstep recordings are
  not metronomes — measured rhythm clarity 0.13–0.23 — so stretching one to
  a tempo does not line it up), and each is placed on a motion peak.

**When it cannot tell, it does not guess.** A snap needs a clear rise over the
scene's own noise (a signal-to-noise ratio, `MIN_CONFIDENCE`); a rhythm needs a
clear autocorrelation peak. Otherwise the planned time stands and the plan says
the sound was not synced — a confident wrong move would be worse than the
original guess.

Offline and cheap: frames are decoded by ffmpeg at 128×72 greyscale, and the
maths is numpy. A 5-second scene takes a few hundred milliseconds.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 128, 72
#: Analysis frame rate. Wan renders at 16 fps; anything above the source rate
#: only repeats frames.
FPS = 16.0
GRID = (8, 6)
#: How far from the planned time an event may be found (seconds).
SEARCH = 2.0
#: A snap needs the rise to stand this many noise-units above the scene's
#: baseline. Measured on synthetic scenes: a door event scores 15-40, a pure
#: camera pan 1-3.
MIN_CONFIDENCE = 6.0
#: A rhythm needs an autocorrelation peak at least this high (0..1).
MIN_RHYTHM = 0.35
#: Step periods considered (seconds per step): 1.1 to 3.3 steps a second.
STEP_PERIOD = (0.3, 0.9)
#: How long one step sound may ring before the next is cut in.
MAX_STEP = 0.35

#: How each effect is synchronised. Anything not listed is left alone
#: (the whoosh already sits on the real cut).
EVENT = "event"
RHYTHM = "rhythm"
MODES = {
    "door": EVENT, "switch": EVENT, "camera": EVENT, "spray": EVENT, "pour": EVENT,
    "clink": EVENT, "zipper": EVENT, "paper": EVENT, "cloth": EVENT,
    "footsteps": RHYTHM, "heels": RHYTHM, "keyboard": RHYTHM,
}


@dataclass
class Placement:
    """Where an effect should start, relative to its scene, and how.

    `skip` seconds are cut from the start of the recording, so that its
    attack — not a creak or a breath before it — is what lands on `at`.
    `hits` replaces the single placement for a rhythm: one entry per step,
    (seconds into the scene, clip start, clip end).
    """

    at: float
    synced: str | None = None      # EVENT, RHYTHM or None (kept as planned)
    skip: float = 0.0
    hits: list = field(default_factory=list)
    confidence: float = 0.0
    note: str = ""


# ------------------------------------------------------------------ video


def _frames(video, start: float, length: float):
    """Greyscale frames of one stretch of video, as a float array (n, H, W)."""
    import numpy as np

    from services.video.ffmpeg import FFMPEG

    cmd = [
        FFMPEG, "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.1, length):.3f}",
        "-i", str(video), "-an",
        "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:flags=area,format=gray",
        "-f", "rawvideo", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    count = len(raw) // (WIDTH * HEIGHT)
    if count < 3:
        return None
    return np.frombuffer(raw[: count * WIDTH * HEIGHT], dtype=np.uint8).reshape(
        count, HEIGHT, WIDTH).astype(np.float32)


def _shift(a, b) -> tuple[int, int]:
    """Integer (dy, dx) that best maps frame `a` onto frame `b` (phase correlation)."""
    import numpy as np

    fa = np.fft.fft2(a - a.mean())
    fb = np.fft.fft2(b - b.mean())
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    corr = np.abs(np.fft.ifft2(cross))
    dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    if dy > HEIGHT // 2:
        dy -= HEIGHT
    if dx > WIDTH // 2:
        dx -= WIDTH
    return int(dy), int(dx)


def local_motion(video, start: float, length: float, *, raw: bool = False):
    """Per-frame local motion for a stretch of video: (times, values).

    `times` are seconds from `start`. Each value is the motion of the most
    active grid block minus the median block, after the camera's translation
    between the two frames has been undone — i.e. motion the camera does not
    explain. Value k compares frame k-1 with frame k, so a change first
    visible in frame k shows at time k/FPS. Smoothed over three frames unless
    `raw`. None when the video cannot be read.
    """
    import numpy as np

    frames = _frames(video, start, length)
    if frames is None:
        return None
    rows, cols = GRID[1], GRID[0]
    bh, bw = HEIGHT // rows, WIDTH // cols
    values = [0.0]
    for i in range(1, len(frames)):
        prev, cur = frames[i - 1], frames[i]
        dy, dx = _shift(prev, cur)
        moved = np.roll(np.roll(prev, dy, axis=0), dx, axis=1)
        diff = np.abs(cur - moved)
        # The wrapped-around border is not real content.
        my, mx = abs(dy) + 1, abs(dx) + 1
        diff[:my, :] = 0
        diff[-my:, :] = 0
        diff[:, :mx] = 0
        diff[:, -mx:] = 0
        blocks = diff[: rows * bh, : cols * bw].reshape(rows, bh, cols, bw).mean(axis=(1, 3))
        flat = np.sort(blocks.ravel())
        values.append(float(flat[-1] - np.median(flat)))
    values = np.asarray(values, dtype=np.float32)
    if not raw:
        values = smooth(values)
    times = np.arange(len(values), dtype=np.float32) / FPS
    return times, values


def smooth(values):
    """3-frame moving average: one noisy frame is not an event."""
    import numpy as np

    if len(values) < 3:
        return values
    return np.convolve(values, np.ones(3, dtype=np.float32) / 3, mode="same")


# ------------------------------------------------------------------ audio


def _envelope(path, rate: int = 16000, hop: float = 0.01):
    """Onset strength of a recording, one value per `hop` seconds."""
    import numpy as np

    from services.video.ffmpeg import FFMPEG

    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate),
         "-f", "s16le", "-"],
        capture_output=True, timeout=60,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    size = int(rate * hop)
    count = len(samples) // size
    if count < 5:
        return None
    rms = np.sqrt((samples[: count * size].reshape(count, size) ** 2).mean(axis=1) + 1e-12)
    onset = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    return onset, hop


def first_transient(path) -> float:
    """Seconds from the file start to its first strong attack (0 when unclear)."""
    import numpy as np

    env = _envelope(path)
    if env is None:
        return 0.0
    onset, hop = env
    peak = float(onset.max())
    if peak <= 0:
        return 0.0
    hits = np.nonzero(onset >= 0.5 * peak)[0]
    return float(hits[0] * hop) if len(hits) else 0.0


def _period(signal, step: float, bounds=STEP_PERIOD) -> tuple[float, float]:
    """Dominant period (seconds) of a signal and how clear it is (0..1)."""
    import numpy as np

    x = np.asarray(signal, dtype=np.float64)
    x = x - x.mean()
    if len(x) < 8 or not np.any(x):
        return 0.0, 0.0
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    ac /= ac[0] + 1e-12
    lo = max(1, int(round(bounds[0] / step)))
    hi = min(len(ac) - 1, int(round(bounds[1] / step)))
    if hi <= lo:
        return 0.0, 0.0
    window = ac[lo: hi + 1]
    # A real period is a local maximum, not the edge of a decaying curve.
    best, best_value = 0, -1.0
    for i in range(1, len(window) - 1):
        if window[i] >= window[i - 1] and window[i] >= window[i + 1] and window[i] > best_value:
            best, best_value = i, float(window[i])
    if best_value <= 0:
        return 0.0, 0.0
    lag = lo + best
    # Parabolic refinement between samples: frame-rate resolution (62 ms at
    # 16 fps) is too coarse for a tempo match.
    if 0 < lag < len(ac) - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        denom = a - 2 * b + c
        offset = 0.5 * (a - c) / denom if denom else 0.0
    else:
        offset = 0.0
    return float((lag + offset) * step), best_value


def audio_steps(path) -> list[tuple[float, float]]:
    """The individual hits in a rhythmic recording: [(start, end)] in seconds.

    A hit is a local peak of onset strength above 30 % of the loudest, at
    least 0.22 s after the previous one (faster than that is one step's heel
    and toe, not two steps). Each slice starts 20 ms before its attack and
    ends before the next hit or after MAX_STEP.
    """
    env = _envelope(path)
    if env is None:
        return []
    onset, hop = env
    peak = float(onset.max())
    if peak <= 0:
        return []
    gap = int(0.22 / hop)
    hits: list[int] = []
    for i in range(1, len(onset) - 1):
        if onset[i] < 0.3 * peak or onset[i] < onset[i - 1] or onset[i] < onset[i + 1]:
            continue
        if hits and i - hits[-1] < gap:
            if onset[i] > onset[hits[-1]]:
                hits[-1] = i
            continue
        hits.append(i)
    total = len(onset) * hop
    slices = []
    for n, i in enumerate(hits):
        start = max(0.0, i * hop - 0.02)
        nxt = hits[n + 1] * hop - 0.02 if n + 1 < len(hits) else total
        slices.append((round(start, 3), round(min(nxt, start + MAX_STEP, total), 3)))
    return [s for s in slices if s[1] - s[0] >= 0.06]


# ------------------------------------------------------------------ placing


def place(video, scene_start: float, scene_length: float, key: str, planned: float,
          clip=None, *, explicit: bool = False) -> Placement:
    """Where effect `key` should start within its scene.

    `planned` is the script's (or planner's) guess, seconds into the scene;
    `explicit` says a person or the script chose that time, which narrows the
    search. `clip` is the chosen recording, whose own attack and rhythm are
    lined up with the picture. Never raises.
    """
    mode = MODES.get(key)
    keep = Placement(at=planned)
    if mode is None or video is None:
        return keep
    try:
        track = local_motion(video, scene_start, scene_length, raw=True)
    except Exception as exc:  # noqa: BLE001 — sync is an improvement, never a requirement
        logger.info("Motion analysis failed for %s: %s", key, exc)
        return keep
    if track is None:
        return keep
    times, unsmoothed = track
    values = smooth(unsmoothed)
    try:
        if mode == EVENT:
            return _place_event(times, values, unsmoothed, planned, scene_length, clip, explicit)
        return _place_rhythm(times, values, unsmoothed, planned, scene_length, clip)
    except Exception as exc:  # noqa: BLE001
        logger.info("Sync failed for %s: %s", key, exc)
        return keep


def _noise(values) -> tuple[float, float]:
    """Baseline and noise of the scene's QUIET part.

    Not the whole scene's median: a door that opens at 2 s and keeps moving
    fills half the scene with its own motion, and a baseline taken from that
    makes the event look like noise (measured: confidence 3.9 on a clear
    event). The quietest 40 % of frames is what "nothing happening" looks
    like in this scene.
    """
    import numpy as np

    ordered = np.sort(np.asarray(values, dtype=np.float64))
    quiet = ordered[: max(3, int(len(ordered) * 0.4))]
    baseline = float(np.median(quiet))
    spread = float(np.median(np.abs(quiet - baseline))) * 1.4826
    # A floor: a perfectly still scene has spread 0, and dividing by it would
    # turn the smallest flicker into a "confident" event.
    return baseline, max(spread, 0.35)


def _place_event(times, values, raw, planned, length, clip, explicit) -> Placement:
    import numpy as np

    baseline, noise = _noise(values)
    rise = np.diff(values, prepend=values[0])
    usable = times <= length - 0.2

    # Every clear event in the scene: a local maximum of the rise whose
    # following peak stands MIN_CONFIDENCE noise-units above the baseline.
    events = []  # (rise index, peak index, confidence)
    for i in range(1, len(values) - 1):
        if not usable[i] or rise[i] <= 0 or rise[i] < rise[i - 1] or rise[i] < rise[i + 1]:
            continue
        peak_i = i
        while peak_i + 1 < len(values) and values[peak_i + 1] >= values[peak_i]:
            peak_i += 1
        confidence = (float(values[peak_i]) - baseline) / noise
        if confidence >= MIN_CONFIDENCE:
            events.append((i, peak_i, confidence))
    if not events:
        best = max(((float(values[j]) - baseline) / noise for j in range(len(values))), default=0.0)
        return Placement(at=planned, confidence=round(best, 1), note="اتفاق مشخصی در تصویر دیده نشد")

    if explicit:
        # The script (or a person) named a moment: the event nearest to it is
        # the one they meant, even if another is bigger — a small hand
        # reaching for the spray bottle, not the model walking past behind.
        # Beyond SEARCH seconds it cannot have meant this one, unless it is
        # the only event there is.
        near = [e for e in events if abs(float(times[e[0]]) - planned) <= SEARCH] or events
        i, peak_i, confidence = min(near, key=lambda e: abs(float(times[e[0]]) - planned))
    else:
        # Nobody said when: the scene's most pronounced event.
        i, peak_i, confidence = max(events, key=lambda e: e[2])
    peak = float(values[peak_i])
    # Where the motion began: the first UNSMOOTHED frame, from a few frames
    # before the steepest rise, that is a quarter of the way up. Smoothing
    # spreads a rise one frame early, and a sound one frame (62 ms at 16 fps)
    # before its picture is past the 45 ms at which viewers notice audio
    # leading (ITU-R BT.1359); late by the same amount is not noticed.
    threshold = baseline + 0.25 * (peak - baseline)
    onset_i = i
    for j in range(max(0, i - 3), peak_i + 1):
        if raw[j] > threshold:
            onset_i = j
            break
    onset = float(times[onset_i])
    # The recording's attack goes on the onset frame. Its lead-in is cut
    # (keeping 50 ms, so the attack is not clipped) rather than started
    # early, which could put it before the scene or on the previous shot.
    attack = first_transient(clip) if clip is not None else 0.0
    skip = max(0.0, attack - 0.05)
    at = max(0.0, min(length - 0.2, onset - (attack - skip)))
    return Placement(at=round(at, 2), synced=EVENT, skip=round(skip, 3),
                     confidence=round(confidence, 1))


def _place_rhythm(times, values, raw, planned, length, clip, span: float = 4.0) -> Placement:
    import numpy as np

    period, clarity = _period(values, 1.0 / FPS)
    if period <= 0 or clarity < MIN_RHYTHM:
        return Placement(at=planned, confidence=round(clarity, 2), note="ضرب قدم در تصویر واضح نبود")
    # The steps in the picture: a regular grid at the measured period (from
    # the smoothed signal, which is steadier), each point snapped to the
    # nearest peak of the UNSMOOTHED motion within a quarter period — real
    # walking drifts, and smoothing turns a one-frame step into three equal
    # frames whose first is a frame early.
    baseline, noise = _noise(raw)
    peaks = [
        j for j in range(1, len(raw) - 1)
        if raw[j] > raw[j - 1] and raw[j] >= raw[j + 1] and raw[j] > baseline + 3 * noise
    ]
    if not peaks:
        return Placement(at=planned, confidence=round(clarity, 2), note="ضرب قدم در تصویر واضح نبود")
    peak_times = np.asarray([times[j] for j in peaks], dtype=np.float64)
    begin = max(0.0, planned - period / 2)
    after = peak_times[peak_times >= begin]
    first = float(after[0]) if len(after) else float(peak_times[0])
    end = min(length - 0.1, first + span)
    steps, t = [], first
    while t <= end:
        nearest = float(peak_times[int(np.argmin(np.abs(peak_times - t)))])
        at = nearest if abs(nearest - t) <= period / 4 else t
        if not steps or at - steps[-1] >= period * 0.6:
            steps.append(at)
        t = at + period
    if clip is None:
        return Placement(at=round(first, 2), synced=RHYTHM, confidence=round(clarity, 2))
    slices = audio_steps(clip)
    if len(slices) < 2:
        attack = first_transient(clip)
        skip = max(0.0, attack - 0.05)
        return Placement(at=round(max(0.0, first - (attack - skip)), 2), synced=RHYTHM,
                         skip=round(skip, 3), confidence=round(clarity, 2),
                         note="صدای قدم به قدم‌های جدا تقسیم نشد؛ فقط شروعش تنظیم شد")
    hits = []
    for n, step_at in enumerate(steps):
        # Cycle through the recording's own steps, so consecutive steps are
        # not the same sample (a machine-gun repeat is the tell of a loop).
        clip_start, clip_end = slices[n % len(slices)]
        hits.append((round(max(0.0, step_at - 0.02), 3), clip_start, clip_end))
    return Placement(at=round(steps[0], 2), synced=RHYTHM, hits=hits, confidence=round(clarity, 2))
