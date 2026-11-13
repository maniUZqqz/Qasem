"""Black bars around the real picture: a phone screen recorded inside a landscape frame, a 4:3 clip inside 16:9, a letterboxed film.

Seen on the owner's own upload (1405/08/22, `main.mp4`): the app of his product recorded on a phone, 1080 × 1920 content centred in a
1920 × 1080 frame — three quarters of every frame is black.  Everything the automatic edit decides from the *whole* frame is then wrong:
exposure (median 0 → «black slide»), the subject window, and above all the deliverable itself — a Reel made of that file is a thin strip
of picture between two black walls.

`detect()` finds the content box with ffmpeg's `cropdetect` at three places of the video (the UNION of the boxes, so a scene that fills
more of the frame later is never cut) and says whether the bars matter.  The cost is three one-second decodes.  Nothing here changes a file.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

#: pixels darker than this (0–255) are "black" for the detector
LIMIT = 24
#: bars narrower than this share of the frame (both sides together, per axis) are ignored — a thin border is not worth a crop
MIN_BAR = 0.12
#: the content must be at least this share of the frame in each direction (a lone bright logo on black is not "the picture")
MIN_CONTENT = 0.20
#: where in the video to look (shares of the duration)
SAMPLES = (0.12, 0.5, 0.88)
#: content narrower than this aspect (w/h) is a portrait picture (a phone) — a vertical frame is its natural home
PORTRAIT = 0.8

_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def _boxes(path, duration: float, ffmpeg: str, limit: int, samples) -> list[tuple[int, int, int, int]]:
    out = []
    for share in samples:
        t = max(0.0, min(max(0.0, float(duration) - 1.6), float(duration) * share))
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-v", "info", "-ss", f"{t:.2f}", "-t", "1.5", "-i", str(path), "-an",
               "-vf", f"cropdetect=limit={int(limit)}:round=2:reset=0", "-f", "null", "-"]
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=90, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        found = _CROP.findall(run.stderr or "")
        if found:
            w, h, x, y = (int(v) for v in found[-1])
            if w > 0 and h > 0:
                out.append((x, y, w, h))
    return out


def detect(path, duration: float, *, size: tuple[int, int] | None = None, ffmpeg: str | None = None, limit: int = LIMIT, samples=SAMPLES) -> dict:
    """`{"found": bool, "x", "y", "w", "h" (pixels), "frame": [W, H], "aspect", "portrait", "box": {"x", "y", "w", "h"} (shares of the frame),
    "bars": {"l", "r", "t", "b"} (shares), "reason"}`.  `found` is true only when the bars matter (≥ 12 % of an axis) and the content is a real picture."""
    from . import reframe

    if ffmpeg is None:
        from services.video.ffmpeg import FFMPEG as ffmpeg  # noqa: N811
    try:
        fw, fh = size or reframe._probe_size(Path(path))
    except Exception:  # noqa: BLE001 — unreadable: no opinion
        return {"found": False, "reason": "اندازهٔ تصویر خوانده نشد."}
    boxes = _boxes(path, duration, ffmpeg, limit, samples)
    if not boxes or not fw or not fh:
        return {"found": False, "frame": [fw, fh], "reason": "نوارِ سیاهی پیدا نشد."}
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    w, h = max(2, x1 - x0), max(2, y1 - y0)
    bar_x, bar_y = 1.0 - w / fw, 1.0 - h / fh
    base = {"frame": [fw, fh], "x": x0, "y": y0, "w": w, "h": h, "aspect": round(w / h, 4), "portrait": w / h < PORTRAIT,
            "box": {"x": round(x0 / fw, 4), "y": round(y0 / fh, 4), "w": round(w / fw, 4), "h": round(h / fh, 4)},
            "bars": {"l": round(x0 / fw, 4), "r": round((fw - x1) / fw, 4), "t": round(y0 / fh, 4), "b": round((fh - y1) / fh, 4)}}
    if w < MIN_CONTENT * fw or h < MIN_CONTENT * fh:
        return {**base, "found": False, "reason": "بخشِ روشن خیلی کوچک است؛ نوارِ سیاه حساب نشد."}
    if max(bar_x, bar_y) < MIN_BAR:
        return {**base, "found": False, "reason": "نوارِ سیاهِ قابل‌توجهی نیست."}
    side = "دو طرفِ ویدیو" if bar_x >= bar_y else "بالا و پایینِ ویدیو"
    return {**base, "found": True, "reason": f"نوارِ سیاه {side} را گرفته؛ تصویرِ واقعی {w}×{h} از {fw}×{fh} است."}


def window(box: dict) -> dict:
    """The clip's reframe window (`{"w", "h", "cx", "cy"}`, shares of the source) that shows exactly the content."""
    b = box["box"]
    return {"w": b["w"], "h": b["h"], "cx": round(b["x"] + b["w"] / 2, 4), "cy": round(b["y"] + b["h"] / 2, 4)}
