"""Motion tracking: follow a point or a small region through a stretch of a video (OpenCV Lucas–Kanade). §23.4

The panel sends the clip's SOURCE file, the source seconds `s0..s1` to follow and a region (x, y, w, h — fractions of the
source frame, at `s0`). The result is the path of that region: per sample the source second, the centre (fractions of the
frame), the scale and the rotation relative to the first frame. The panel turns that path into keyframes of whatever is
attached (a mask, a title, a sticker) — so nothing here knows about the timeline, and the same file runs unchanged on the
processing node (`processing/edit_track.py` is an identical copy; a test fails if they differ).

How: corner features inside the region are followed frame to frame with pyramidal LK; a forward–backward check throws
away the ones that drifted; a similarity transform (translation + scale + rotation, RANSAC) fitted to the survivors moves
the region. Features are re-seeded when too few remain. When the region leaves the frame or is lost the path simply
ends early (`lost_at`) — a clear ending beats a confident wrong path.

Frames are decoded by ffmpeg at `fps` (default 15) and ≤ 640 px: the work is a few seconds for a clip, not minutes.
"""
from __future__ import annotations

import math
import subprocess

MAX_SECONDS = 60.0
MAX_FRAMES = 900
DEFAULT_FPS = 15.0
MAX_SIDE = 640


class TrackError(RuntimeError):
    pass


class TrackCancelled(Exception):
    pass


def _frames(ffmpeg: str, video: str, s0: float, dur: float, fps: float, w: int, h: int):
    """Yield gray frames (h×w uint8 ndarrays) of video[s0, s0+dur] at `fps`, scaled to w×h."""
    import numpy as np

    cmd = [ffmpeg, "-v", "error", "-ss", f"{s0:.3f}", "-t", f"{dur:.3f}", "-i", str(video), "-an", "-vf",
           f"fps={fps:g},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise TrackError("ffmpeg پیدا نشد.") from exc
    size = w * h
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w).copy()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()


def _seed(cv2, np, gray, cx: float, cy: float, hw: float, hh: float):
    h, w = gray.shape
    mask = np.zeros_like(gray)
    x0, x1 = int(max(0, cx - hw)), int(min(w, cx + hw))
    y0, y1 = int(max(0, cy - hh)), int(min(h, cy + hh))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    mask[y0:y1, x0:x1] = 255
    pts = cv2.goodFeaturesToTrack(gray, maxCorners=140, qualityLevel=0.008, minDistance=3, blockSize=5, mask=mask)
    return pts


def track(video, s0: float, s1: float, region: dict, *, src_size: tuple[int, int], fps: float = DEFAULT_FPS,
          ffmpeg: str = "ffmpeg", progress=None, cancel=None) -> dict:
    """Follow `region` {x, y, w, h} (fractions at `s0`) through `video` between source seconds s0 and s1.

    `src_size` is the DISPLAYED (width, height) of the video (a rotated phone clip is passed already turned).
    → {"samples": [{"s", "x", "y", "scale", "rot"}], "lost_at": float | None, "fps", "frames", "size": [w, h]}
    """
    import cv2
    import numpy as np

    s0, s1 = max(0.0, float(s0)), float(s1)
    if s1 <= s0 + 0.2:
        raise TrackError("بازهٔ ردیابی خیلی کوتاه است.")
    s1 = min(s1, s0 + MAX_SECONDS)
    fps = max(4.0, min(30.0, float(fps or DEFAULT_FPS)))
    if (s1 - s0) * fps > MAX_FRAMES:
        fps = MAX_FRAMES / (s1 - s0)
    sw, sh = int(src_size[0]), int(src_size[1])
    if sw < 16 or sh < 16:
        raise TrackError("ابعادِ ویدیو معلوم نیست.")
    k = min(1.0, MAX_SIDE / max(sw, sh))
    w, h = max(16, int(round(sw * k / 2)) * 2), max(16, int(round(sh * k / 2)) * 2)
    rx = max(0.0, min(1.0, float(region.get("x", 0.4))))
    ry = max(0.0, min(1.0, float(region.get("y", 0.4))))
    rw = max(0.02, min(1.0 - rx, float(region.get("w", 0.2))))
    rh = max(0.02, min(1.0 - ry, float(region.get("h", 0.2))))
    cx, cy = (rx + rw / 2) * w, (ry + rh / 2) * h
    hw, hh = rw * w / 2, rh * h / 2
    hw, hh = max(hw, 8.0), max(hh, 8.0)
    scale, rot = 1.0, 0.0
    samples: list[dict] = []
    lost_at = None
    prev = None
    pts = None
    total = max(1, int((s1 - s0) * fps))
    lk = dict(winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    affine = getattr(cv2, "estimateAffinePartial2D", None)
    n = 0
    for gray in _frames(ffmpeg, str(video), s0, s1 - s0, fps, w, h):
        t = s0 + n / fps
        if prev is None:
            pts = _seed(cv2, np, gray, cx, cy, hw, hh)
            if pts is None or len(pts) < 4:
                raise TrackError("در این ناحیه چیزِ قابلِ ردیابی (لبه یا بافت) نیست؛ ناحیهٔ دیگری را انتخاب کنید.")
            samples.append({"s": round(t, 3), "x": round(cx / w, 5), "y": round(cy / h, 5), "scale": 1.0, "rot": 0.0})
        else:
            if cancel is not None and cancel():
                raise TrackCancelled()
            nxt, st, _err = cv2.calcOpticalFlowPyrLK(prev, gray, pts, None, **lk)
            back, st2, _ = cv2.calcOpticalFlowPyrLK(gray, prev, nxt, None, **lk)
            ok = (st.reshape(-1) == 1) & (st2.reshape(-1) == 1) & (np.linalg.norm((pts - back).reshape(-1, 2), axis=1) < 1.2)
            good_prev, good_next = pts.reshape(-1, 2)[ok], nxt.reshape(-1, 2)[ok]
            if len(good_next) < 5:
                lost_at = t
                break
            if affine is not None and len(good_next) >= 6:
                M, inl = affine(good_prev, good_next, method=cv2.RANSAC, ransacReprojThreshold=2.0)
            else:
                M = None
            if M is None:
                d = np.median(good_next - good_prev, axis=0)
                M = np.array([[1, 0, d[0]], [0, 1, d[1]]], dtype=np.float64)
            c = M @ np.array([cx, cy, 1.0])
            s_step = math.hypot(M[0, 0], M[1, 0])
            if not (0.5 < s_step < 2.0):
                lost_at = t
                break
            cx, cy = float(c[0]), float(c[1])
            scale *= s_step
            rot += math.degrees(math.atan2(M[1, 0], M[0, 0]))
            hw, hh = hw * s_step, hh * s_step
            if cx < -0.1 * w or cx > 1.1 * w or cy < -0.1 * h or cy > 1.1 * h:
                lost_at = t
                break
            samples.append({"s": round(t, 3), "x": round(cx / w, 5), "y": round(cy / h, 5), "scale": round(scale, 5), "rot": round(rot, 3)})
            pts = good_next.reshape(-1, 1, 2).astype(np.float32)
            if len(pts) < 24 or n % 12 == 0:                       # top up with fresh corners of the moved region
                fresh = _seed(cv2, np, gray, cx, cy, hw, hh)
                if fresh is not None and len(fresh):
                    pts = np.concatenate([pts, fresh.astype(np.float32)], axis=0)[:200]
        prev = gray
        n += 1
        if progress is not None and n % 5 == 0:
            progress(min(0.99, n / total))
    if len(samples) < 2:
        raise TrackError("ردیابی از همان فریمِ اول از دست رفت؛ ناحیهٔ دیگری یا بازهٔ کوتاه‌تری را امتحان کنید.")
    return {"samples": samples, "lost_at": None if lost_at is None else round(lost_at, 3), "fps": round(fps, 3), "frames": len(samples),
            "size": [w, h]}
