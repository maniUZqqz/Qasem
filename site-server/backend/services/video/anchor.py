"""Which frame the next segment starts from.

A CONTINUE segment is rendered from the previous segment's last frame (Wan
image-to-video). Whatever that frame is, the next five seconds inherit it: a
last frame caught mid-motion — a hand blurred as it moves, the camera
halfway through a whip — becomes the blurred first frame of the next clip,
and the model spends that clip trying to invent detail it was never given.

So the anchor is chosen, not taken: among the last WINDOW frames, the
sharpest one (variance of the Laplacian — the standard focus measure — with
a penalty for motion towards its neighbour). When it is not the very last
frame, the segment is TRIMMED to end on it, so the join stays seamless: the
next clip starts on exactly the frame this one ends on. At most WINDOW − 1
frames (under half a second at 16 fps) are ever cut, and only when the chosen
frame is clearly better — a trim is not free, it shortens the scene.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Frames considered, counting back from the end.
WINDOW = 8
#: The chosen frame must be this much sharper than the last one to be worth a
#: trim. Below it the difference is compression noise.
MIN_GAIN = 1.25
ANALYSIS_WIDTH = 640


@dataclass
class Choice:
    frames_back: int          # 0 = the last frame
    sharpness_last: float
    sharpness_chosen: float
    trimmed: bool = False
    note: str = ""


def _tail_frames(video_path, count: int):
    """The last `count` frames, greyscale at ANALYSIS_WIDTH, oldest first."""
    import numpy as np

    from services.video.ffmpeg import FFMPEG, probe_video

    info = probe_video(video_path)
    fps = float(info.get("fps") or 16.0)
    height = int(round(ANALYSIS_WIDTH * info["height"] / max(1, info["width"]) / 2) * 2)
    seconds = (count + 2) / fps
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-sseof", f"-{seconds:.3f}", "-i", str(video_path), "-an",
         "-vf", f"scale={ANALYSIS_WIDTH}:{height},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, timeout=60,
    ).stdout
    size = ANALYSIS_WIDTH * height
    frames = np.frombuffer(raw[: len(raw) // size * size], dtype=np.uint8).reshape(-1, height, ANALYSIS_WIDTH)
    return frames[-count:], info


def sharpness(gray) -> float:
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def choose(video_path) -> Choice:
    """The best anchor among the last WINDOW frames. Never raises."""
    import numpy as np

    try:
        # One extra frame, so the oldest candidate has a neighbour to measure
        # motion against like every other (without it, it scored as perfectly
        # still and won every time — measured: a clean clip trimmed by 7).
        frames, _info = _tail_frames(video_path, WINDOW + 1)
    except Exception as exc:  # noqa: BLE001
        return Choice(0, 0.0, 0.0, note=f"فریم‌های آخر خوانده نشد: {exc}"[:200])
    if len(frames) < 3:
        return Choice(0, 0.0, 0.0, note="کلیپ کوتاه‌تر از پنجره‌ی انتخاب است")
    scores = []
    for i in range(1, len(frames)):
        frame = frames[i]
        focus = sharpness(frame)
        # Motion towards the previous frame: a frame in the middle of a fast
        # move is softer in ways the Laplacian alone underrates.
        motion = float(np.abs(frame.astype(np.int16) - frames[i - 1].astype(np.int16)).mean())
        scores.append(focus / (1.0 + motion / 8.0))
    frames = frames[1:]
    last = len(frames) - 1
    # The LATEST frame that is about as good as the best: the smallest trim
    # that buys the sharpness.
    top = max(scores)
    best = max(i for i, score in enumerate(scores) if score >= 0.95 * top)
    back = last - best
    focus_last = sharpness(frames[last])
    focus_best = sharpness(frames[best])
    # Worth a trim only for a real gain in FOCUS: the motion term ranks the
    # candidates, but a last frame that is as sharp as the rest is kept
    # (measured: 272 vs 275 on a clean pan must not cost a frame).
    if back == 0 or focus_best < focus_last * MIN_GAIN:
        return Choice(0, focus_last, focus_last, note="فریم آخر خود بهترین است")
    return Choice(back, focus_last, focus_best)


def apply(video_path, out_dir, *, label: str) -> tuple[Path, Path, Choice]:
    """(video to keep, anchor image, the choice). Trims when a better anchor exists.

    Falls back to the untouched video and its true last frame on any failure:
    an anchor must always exist, a better one is a bonus.
    """
    from services.video.ffmpeg import FFMPEG, _run, extract_last_frame, probe_video

    out = Path(out_dir)
    video = Path(video_path)
    choice = choose(video)
    if choice.frames_back == 0:
        return video, extract_last_frame(video, out / f"{label}_last.png"), choice
    try:
        info = probe_video(video)
        total = int(info.get("frames") or round(float(info["duration"]) * float(info["fps"])))
        keep = max(1, total - choice.frames_back)
        trimmed = out / f"{label}_trimmed.mp4"
        _run([FFMPEG, "-y", "-i", str(video), "-frames:v", str(keep), "-an",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium", str(trimmed)])
        anchor = extract_last_frame(trimmed, out / f"{label}_last.png")
    except Exception as exc:  # noqa: BLE001
        logger.info("Anchor trim failed for %s: %s", label, exc)
        return video, extract_last_frame(video, out / f"{label}_last.png"), choice
    choice.trimmed = True
    choice.note = (
        f"{choice.frames_back} فریم آخر (لرزان/محو) حذف شد تا صحنه‌ی بعد از فریم واضح "
        f"شروع شود (وضوح {choice.sharpness_last:.0f} ← {choice.sharpness_chosen:.0f})"
    )
    return trimmed, anchor, choice
