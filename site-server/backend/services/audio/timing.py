"""Say the product's name when the product is on screen.

Each scene's narration starts at the scene's first frame. Wan, meanwhile,
reveals the product whenever the camera move gets there — often a second or
two in. «این کیف چرمی…» spoken over an empty table, with the bag arriving after
the sentence has moved on, is the voice and the picture telling two stories.

This moves each scene's narration LATER, inside its own scene, so that the
first mention of the product lands just after the product appears:

* **When the product appears** — the shop's own product photo is matched
  against the scene's frames (ORB features + RANSAC homography, OpenCV,
  offline): the number of geometrically consistent matches per frame is a
  visibility curve, and "appears" is where it first rises past halfway to its
  peak. A product visible from the first frame needs no shift.
* **When its name is said** — Whisper's word timings on the narration clip
  itself, with our own text laid onto them (`transcribe.align`), so the time
  is of the word we wrote, not of what Whisper thinks it heard. Without
  Whisper: proportional to the characters inside the measured speech span.
* **How far** — `appear + LEAD − said`, never earlier than the scene start,
  never so late that speech runs past the scene's end, at most MAX_SHIFT.
  A shift under 150 ms is not worth the edit and is skipped.

The clip keeps its exact length (silence moves from the end to the start),
so nothing downstream — the concatenation, the subtitles that are timed from
these same files, the soundscape — changes except the words' position.

Every guess is refused rather than made: no product photo, no match strong
enough, the product not named in the narration, no slack — the scene is left
as it was, and the result says why.
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FPS = 8.0
FRAME_WIDTH = 640
#: The name is said this long after the product appears: the eye finds the
#: object first, and a word that arrives with the first frame of it is early.
LEAD = 0.25
MAX_SHIFT = 2.0
MIN_SHIFT = 0.15
#: A frame counts as "product visible" at this many RANSAC inliers or more
#: (the same bar as services.video.product_region).
MIN_INLIERS = 12


@dataclass
class Alignment:
    shift: float = 0.0
    appear: float | None = None
    said: float | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "shift": round(self.shift, 2),
            "appear": None if self.appear is None else round(self.appear, 2),
            "said": None if self.said is None else round(self.said, 2),
            "note": self.note,
        }


# ------------------------------------------------------------ the picture


def product_curve(video, product_image, *, fps: float = FPS):
    """(times, inliers) — how visible the product is in each sampled frame."""
    import numpy as np

    from services.video import product_region
    from services.video.ffmpeg import FFMPEG, probe_video

    matcher = product_region.Matcher(product_image)
    info = probe_video(video)
    height = int(round(FRAME_WIDTH * info["height"] / max(1, info["width"]) / 2) * 2)
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(video), "-an",
         "-vf", f"fps={fps},scale={FRAME_WIDTH}:{height},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, timeout=180,
    ).stdout
    count = len(raw) // (FRAME_WIDTH * height)
    if not count:
        raise ValueError("ویدیو خوانده نشد")
    frames = np.frombuffer(raw[: count * FRAME_WIDTH * height], dtype=np.uint8).reshape(count, height, FRAME_WIDTH)
    scores = [matcher.find(frame).inliers for frame in frames]
    times = [i / fps for i in range(len(scores))]
    return times, scores


def appearance(times, scores) -> tuple[float | None, str]:
    """When the product first clearly shows, or (None, why not)."""
    if not scores:
        return None, "فریمی خوانده نشد"
    peak = max(scores)
    if peak < MIN_INLIERS:
        return None, "محصول در تصویر این صحنه به‌طور مطمئن پیدا نشد"
    ordered = sorted(scores)
    floor = ordered[max(0, len(ordered) * 3 // 10 - 1)]
    threshold = max(MIN_INLIERS, floor + 0.5 * (peak - floor))
    for i, value in enumerate(scores):
        # Two samples in a row: one frame of chance matches is not a reveal.
        if value >= threshold and (i + 1 >= len(scores) or scores[i + 1] >= threshold * 0.8):
            if i == 0:
                return 0.0, "محصول از اول صحنه دیده می‌شود"
            return float(times[i]), ""
    return None, "لحظه‌ی مشخصی برای ظاهر شدن محصول پیدا نشد"


# ------------------------------------------------------------ the words


_WORD = re.compile(r"[\w‌]+", re.UNICODE)


def _norm(word: str) -> str:
    table = str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "‌": ""})
    return word.translate(table).lower()


def _name_index(tokens: list[str], names: list[str]) -> int | None:
    """Index of the first token that is (the start of) the product's name."""
    wanted = {_norm(w) for name in names for w in _WORD.findall(name or "") if len(w) >= 2}
    # Words that are in half the product names in a shop are not the name.
    wanted -= {"و", "با", "برای", "این", "the", "and", "for", "with"}
    for i, token in enumerate(tokens):
        if _norm(token) in wanted:
            return i
    return None


def speech_span(clip) -> tuple[float, float] | None:
    """(start, end) of the talking in a clip, from its own levels."""
    from services.audio import qc

    import tempfile

    with tempfile.TemporaryDirectory(prefix="timing_") as folder:
        samples, rate = qc.decode(clip, folder)
    levels = qc._windows(samples, rate)
    if not levels:
        return None
    floor = qc.silence_floor(levels)
    loud = [i for i, level in enumerate(levels) if level > floor]
    if not loud:
        return None
    step = qc.WINDOW_MS / 1000.0
    return loud[0] * step, (loud[-1] + 1) * step


def name_time(clip, spoken_text: str, names: list[str], language: str = "fa") -> tuple[float | None, str]:
    """When the product's name is said in `clip`, or (None, why not)."""
    tokens = _WORD.findall(spoken_text or "")
    index = _name_index(tokens, names)
    if index is None:
        return None, "اسم محصول در نریشن این صحنه نیامده"
    try:
        from services.audio import transcribe

        heard = transcribe.transcribe(clip, language=language, hint=spoken_text)
        words = transcribe.align(spoken_text, heard)
        target = _norm(tokens[index])
        for word in words:
            if _norm(word.text) == target:
                return float(word.start), "whisper"
    except Exception as exc:  # noqa: BLE001 — fall back to proportion
        logger.info("Word timing unavailable, estimating: %s", exc)
    span = speech_span(clip)
    if span is None:
        return None, "گفتار در این صحنه پیدا نشد"
    chars_before = len(" ".join(tokens[:index]))
    total = max(1, len(" ".join(tokens)))
    start, end = span
    return start + (end - start) * chars_before / total, "estimate"


# ------------------------------------------------------------ the shift


def plan(video, product_image, clip, spoken_text: str, names: list[str], duration: float,
         language: str = "fa") -> Alignment:
    """How far to move this scene's narration. Never raises."""
    if product_image is None:
        return Alignment(note="عکس محصول در دسترس نیست")
    try:
        times, scores = product_curve(video, product_image)
        appear, why = appearance(times, scores)
    except Exception as exc:  # noqa: BLE001
        return Alignment(note=f"تصویر بررسی نشد: {exc}"[:200])
    if appear is None or appear == 0.0:
        return Alignment(appear=appear, note=why)
    said, how = name_time(clip, spoken_text, names, language)
    if said is None:
        return Alignment(appear=appear, note=how)
    span = speech_span(clip)
    speech_end = span[1] if span else duration
    slack = max(0.0, duration - speech_end - 0.1)
    wanted = appear + LEAD - said
    shift = max(0.0, min(wanted, slack, MAX_SHIFT))
    if shift < MIN_SHIFT:
        note = ("نریشن از قبل با تصویر هماهنگ بود" if wanted < MIN_SHIFT
                else "جای خالی کافی در صحنه برای جابه‌جایی نریشن نبود")
        return Alignment(appear=appear, said=said, note=note)
    note = f"اسم محصول {shift:.1f} ثانیه دیرتر گفته شد تا با دیده‌شدنش هم‌زمان باشد"
    if shift < wanted - 0.05:
        note += " (تا جایی که صحنه جا داشت)"
    return Alignment(shift=shift, appear=appear, said=said, note=note)


def shift_clip(clip, shift: float, duration: float) -> Path:
    """Move the clip's audio `shift` seconds later, same length. In place."""
    from services.video.ffmpeg import FFMPEG, _run

    clip = Path(clip)
    moved = clip.with_name(clip.stem + "_shifted" + clip.suffix)
    delay = int(round(shift * 1000))
    _run([
        FFMPEG, "-y", "-i", str(clip),
        "-af", f"adelay={delay}:all=1,apad,asetpts=N/SR/TB",
        "-t", f"{duration:.3f}", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(moved),
    ])
    moved.replace(clip)
    return clip
