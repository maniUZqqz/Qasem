"""«بازتنظیمِ قاب»: the window inside a source picture that becomes the frame — and the auto-reframe that makes a
horizontal video a vertical one **following the subject**, deterministically and cheaply (no model, no network).

A reframe is `{"w","h","cx","cy"}` (+ optional `"kx"`, `"ky"` keyframes of the centre; see `timeline.Clip.reframe`).
`window_size` gives the largest window of an aspect that fits the source; `plan` looks at ≤ 150 small frames of the
clip and returns a reframe whose centre follows what matters, in this order:

1. **faces** (YuNet through `services.video.faces`, the largest face wins);
2. **motion** (the centre of what moved between two sampled frames);
3. **saliency** (spectral residual on a 64² thumbnail — what stands out: a product on a plain table);
4. otherwise the middle.

The path is then turned into a camera operator's move, not a jittery trace: a dead zone (the window stays put while the
subject stays inside the middle of it), a speed limit (a pan never whips), a light low-pass, and Ramer–Douglas–Peucker
to ≤ 24 linear keys. Everything is pure numpy/OpenCV on 3 frames per second.
"""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path

import numpy as np

from .errors import TimelineError

logger = logging.getLogger(__name__)

#: samples per second of footage and the hard cap (a 60 s clip is 150 frames of 320 px: well under a second of numpy)
SAMPLE_FPS = 3.0
MAX_SAMPLES = 150
MAX_SECONDS = 90.0
THUMB_W = 320
MAX_KEYS = 24
#: the camera ignores a subject inside this fraction of the window around its centre; and pans at most this many
#: window-widths per second.
DEAD_ZONE = 0.12
MAX_SPEED = 0.35
ASPECTS = {"9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5, "16:9": 16 / 9, "3:4": 3 / 4}


def aspect_value(aspect) -> float:
    """"9:16" | 0.5625 → w/h as a float; anything unusable raises `TimelineError` with a Persian message."""
    if isinstance(aspect, str):
        text = aspect.strip().replace("x", ":").replace("/", ":")
        if text in ASPECTS:
            return ASPECTS[text]
        if ":" in text:
            a, _, b = text.partition(":")
            try:
                aspect = float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                raise TimelineError("نسبتِ قاب نامعتبر است (مثلاً ۹:۱۶).") from None
        try:
            aspect = float(text)
        except ValueError:
            raise TimelineError("نسبتِ قاب نامعتبر است (مثلاً ۹:۱۶).") from None
    try:
        value = float(aspect)
    except (TypeError, ValueError):
        raise TimelineError("نسبتِ قاب نامعتبر است (مثلاً ۹:۱۶).") from None
    if not 0.2 <= value <= 5.0:
        raise TimelineError("نسبتِ قاب باید بین ۱:۵ و ۵:۱ باشد.")
    return value


def window_size(src_w: float, src_h: float, aspect: float, zoom: float = 1.0) -> tuple[float, float]:
    """(w, h) as fractions of the source of the largest window whose PIXEL aspect is `aspect`, shrunk by `zoom` (≥ 1)."""
    src_w, src_h = max(1.0, float(src_w)), max(1.0, float(src_h))
    src_aspect = src_w / src_h
    if aspect >= src_aspect:          # wider than the source: full width, less height
        w, h = 1.0, src_aspect / aspect
    else:                              # narrower: full height, less width
        w, h = aspect / src_aspect, 1.0
    z = max(1.0, min(4.0, float(zoom or 1.0)))
    return round(max(0.05, w / z), 4), round(max(0.05, h / z), 4)


def centred(src_w: float, src_h: float, aspect, zoom: float = 1.0, cx: float = 0.5, cy: float = 0.5) -> dict:
    """The static reframe: the largest window of `aspect` centred on (cx, cy), kept inside the source."""
    w, h = window_size(src_w, src_h, aspect_value(aspect), zoom)
    return {"w": w, "h": h, "cx": round(min(1 - w / 2, max(w / 2, cx)), 4), "cy": round(min(1 - h / 2, max(h / 2, cy)), 4)}


# ------------------------------------------------------------------ looking


def _probe_size(path) -> tuple[int, int]:
    from services.video.ffmpeg import probe

    data = probe(path)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
            # a phone video is often stored sideways with a rotation flag: ffmpeg's decoder applies it, so swap
            rot = 0
            for side in stream.get("side_data_list") or []:
                if "rotation" in side:
                    rot = int(float(side["rotation"])) % 180
            if rot == 90:
                w, h = h, w
            return w, h
    raise TimelineError("اندازهٔ تصویر خوانده نشد.")


def _frames(path, start: float, seconds: float, fps: float, thumb_w: int, src_w: int, src_h: int):
    """Raw BGR thumbnails at `fps` over [start, start+seconds] as an (n, h, w, 3) uint8 array (n may be 0)."""
    from services.video.ffmpeg import FFMPEG

    th = max(2, int(round(thumb_w * src_h / max(1, src_w) / 2)) * 2)
    cmd = [FFMPEG, "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}", "-i", str(path), "-an",
           "-vf", f"fps={fps:g},scale={thumb_w}:{th}", "-frames:v", str(MAX_SAMPLES), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=120, check=False).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TimelineError(f"فریم‌ها خوانده نشد: {exc}") from exc
    size = thumb_w * th * 3
    n = len(raw) // size
    if n == 0:
        return np.zeros((0, th, thumb_w, 3), dtype=np.uint8)
    return np.frombuffer(raw[: n * size], dtype=np.uint8).reshape(n, th, thumb_w, 3)


def _saliency(gray: np.ndarray) -> np.ndarray:
    """Spectral-residual saliency (Hou & Zhang): what in a picture does not look like the rest of it. Returns 0..1."""
    small = _resize(gray, 64, 64).astype(np.float32)
    f = np.fft.fft2(small)
    log_amp = np.log(np.abs(f) + 1e-6)
    phase = np.angle(f)
    avg = _box(log_amp, 3)
    resid = log_amp - avg
    sal = np.abs(np.fft.ifft2(np.exp(resid + 1j * phase))) ** 2
    sal = _box(sal, 5)
    lo, hi = float(sal.min()), float(sal.max())
    return (sal - lo) / (hi - lo + 1e-9)


def _resize(a: np.ndarray, w: int, h: int) -> np.ndarray:
    import cv2

    return cv2.resize(a, (w, h), interpolation=cv2.INTER_AREA)


def _box(a: np.ndarray, k: int) -> np.ndarray:
    import cv2

    return cv2.blur(a, (k, k))


def _centroid(weight: np.ndarray) -> tuple[float, float, float]:
    """(cx, cy, mass fraction) of a non-negative map in 0..1 coordinates."""
    total = float(weight.sum())
    if total <= 1e-9:
        return 0.5, 0.5, 0.0
    h, w = weight.shape
    ys, xs = np.mgrid[0:h, 0:w]
    cx = float((weight * (xs + 0.5)).sum() / total / w)
    cy = float((weight * (ys + 0.5)).sum() / total / h)
    return cx, cy, total / (w * h)


def sample_subject(frames: np.ndarray, *, faces_fn=None) -> list[dict]:
    """One {cx, cy, engine} per frame. `faces_fn(frame_bgr) -> [(cx, cy, area)]` is injectable for tests."""
    import cv2

    if faces_fn is None:
        faces_fn = _faces_yunet
    out: list[dict] = []
    prev_gray = None
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flat = float(gray.std()) < 4.0                      # a flat frame has no subject: saliency of noise is not a subject
        found = faces_fn(frame)
        if found:
            cx, cy, _ = max(found, key=lambda f: f[2])
            out.append({"cx": cx, "cy": cy, "engine": "face"})
        else:
            moved = None
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                diff = cv2.blur(diff, (7, 7))
                mask = (diff > 18).astype(np.float32)
                mx, my, mass = _centroid(mask)
                if 0.004 <= mass <= 0.6:
                    moved = {"cx": mx, "cy": my, "engine": "motion"}
            if moved is not None:
                out.append(moved)
            elif flat:
                out.append({"cx": 0.5, "cy": 0.5, "engine": "center"})
            else:
                sal = _saliency(gray)
                sal = np.where(sal > 0.6, sal, 0.0)
                sx, sy, mass = _centroid(sal)
                out.append({"cx": sx, "cy": sy, "engine": "saliency" if mass > 0 else "center"})
        prev_gray = gray
    return out


def _faces_yunet(frame) -> list[tuple[float, float, float]]:
    try:
        from services.video import faces

        boxes = faces._yunet(frame)
    except Exception:  # noqa: BLE001 — "could not look" is not "nobody"
        return []
    return [(b.centre[0], b.centre[1], b.area) for b in (boxes or []) if b.area >= faces.MIN_FACE_FRACTION]


# ------------------------------------------------------------------ the move


def camera_path(times: list[float], targets: list[float], half: float, *, dead: float = DEAD_ZONE,
                speed: float = MAX_SPEED) -> list[float]:
    """The centre of the window over time for a subject at `targets` (fractions): clamped to [half, 1-half], with a dead
    zone, a speed limit and a light low-pass. `half` = half the window size along this axis."""
    if not targets:
        return []
    lo, hi = half, 1.0 - half
    if hi <= lo:
        return [0.5] * len(targets)
    win = 2 * half
    cam = min(hi, max(lo, targets[0]))
    path = [cam]
    for i in range(1, len(targets)):
        dt = max(1e-3, times[i] - times[i - 1])
        err = targets[i] - cam
        zone = dead * win
        if abs(err) > zone:
            want = err - math.copysign(zone, err)
            step = max(-speed * win * dt, min(speed * win * dt, want))
            cam = min(hi, max(lo, cam + step))
        path.append(cam)
    if len(path) >= 3:                                  # 3-tap low-pass, ends kept
        sm = [path[0]] + [(path[i - 1] + 2 * path[i] + path[i + 1]) / 4 for i in range(1, len(path) - 1)] + [path[-1]]
        path = sm
    return path


def simplify(times: list[float], values: list[float], tolerance: float = 0.008, max_keys: int = MAX_KEYS) -> list[dict]:
    """Ramer–Douglas–Peucker on (t, v) → ≤ `max_keys` linear keys; first and last always kept."""
    n = len(times)
    if n == 0:
        return []
    if n == 1:
        return [{"t": round(times[0], 3), "v": round(values[0], 4), "e": "linear"}]
    t0, t1 = times[0], times[-1]
    span = max(1e-6, t1 - t0)

    def pts(i):
        return (times[i] - t0) / span, values[i]

    def rdp(lo: int, hi: int, tol: float, keep: set[int]) -> None:
        if hi <= lo + 1:
            return
        (x0, y0), (x1, y1) = pts(lo), pts(hi)
        worst, at = 0.0, -1
        for i in range(lo + 1, hi):
            x, y = pts(i)
            # vertical distance to the chord: the value error at that moment, which is what a viewer sees
            chord = y0 + (y1 - y0) * ((x - x0) / max(1e-9, x1 - x0))
            d = abs(y - chord)
            if d > worst:
                worst, at = d, i
        if worst > tol and at > 0:
            keep.add(at)
            rdp(lo, at, tol, keep)
            rdp(at, hi, tol, keep)

    tol = tolerance
    keep: set[int] = {0, n - 1}
    for _ in range(8):
        keep = {0, n - 1}
        rdp(0, n - 1, tol, keep)
        if len(keep) <= max_keys:
            break
        tol *= 1.6
    return [{"t": round(times[i], 3), "v": round(values[i], 4), "e": "linear"} for i in sorted(keep)]


def plan(path, start: float, end: float, aspect, *, follow: str = "auto", zoom: float = 1.0, speed: float = 1.0,
         size: tuple[int, int] | None = None, faces_fn=None, frames=None) -> dict:
    """The auto-reframe: {"reframe", "engine", "samples", "notes"}. `start`/`end` are SOURCE seconds; key times in the
    result are seconds from the clip's start on the TIMELINE (so they are divided by `speed`).
    `frames` / `size` / `faces_fn` are injectable for tests."""
    asp = aspect_value(aspect)
    src_w, src_h = size or _probe_size(path)
    w, h = window_size(src_w, src_h, asp, zoom)
    notes: list[str] = []
    base = {"w": w, "h": h, "cx": 0.5, "cy": 0.5}
    if w >= 0.999 and h >= 0.999:
        return {"reframe": base, "engine": "center", "samples": 0, "notes": ["این قاب با نسبتِ تصویر یکی است؛ چیزی بریده نمی‌شود."]}
    if follow == "center":
        return {"reframe": base, "engine": "center", "samples": 0, "notes": []}

    seconds = max(0.2, min(MAX_SECONDS, float(end) - float(start)))
    if float(end) - float(start) > MAX_SECONDS:
        notes.append(f"فقط {MAX_SECONDS:.0f} ثانیهٔ اول بررسی شد؛ بقیه روی آخرین جای پنجره می‌ماند.")
    fps = min(SAMPLE_FPS, MAX_SAMPLES / seconds)
    if frames is None:
        frames = _frames(path, start, seconds, fps, THUMB_W, src_w, src_h)
    n = len(frames)
    if n == 0:
        return {"reframe": base, "engine": "center", "samples": 0, "notes": notes + ["فریمی برای بررسی پیدا نشد؛ پنجره وسطِ قاب ماند."]}

    subject = sample_subject(frames, faces_fn=faces_fn)
    counts: dict[str, int] = {}
    for s in subject:
        counts[s["engine"]] = counts.get(s["engine"], 0) + 1
    real = {k: v for k, v in counts.items() if k != "center"}
    engine = max(real, key=lambda k: real[k]) if real else "center"
    if engine == "saliency":
        engine = "motion"                      # the UI has two honest words: where it looked, not how
    if sum(real.values()) < max(1, int(0.3 * n)):
        return {"reframe": base, "engine": "center", "samples": n,
                "notes": notes + ["سوژهٔ مشخصی پیدا نشد؛ پنجره وسطِ قاب ماند."]}

    times = [(i / fps) / max(0.05, float(speed or 1.0)) for i in range(n)]
    out = dict(base)
    for axis, size, name in (("kx", w, "cx"), ("ky", h, "cy")):
        if size >= 0.999:
            continue
        pts = camera_path(times, [s["cx" if axis == "kx" else "cy"] for s in subject], size / 2)
        keys = simplify(times, pts)
        out[name] = keys[0]["v"] if max(pts) - min(pts) >= 0.004 else round(sum(pts) / len(pts), 4)
        if len(keys) >= 2 and max(pts) - min(pts) >= 0.004:
            out[axis] = keys
    return {"reframe": out, "engine": engine, "samples": n, "notes": notes}
