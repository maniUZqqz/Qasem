"""One shoot, every platform. `ایده‌ها.md` §10.

"مشتری یک بار فیلم می‌گیرد، ده جا منتشر می‌کند."

A finished video is one aspect ratio and one length. Instagram wants 9:16 for
reels and 4:5 for the feed, a story is 15 seconds, YouTube wants 16:9. Asking a
shop to re-render for each is asking them to spend the GPU four times on a
video they already have.

**Nothing here touches a model.** Every output is ffmpeg: crop, scale, trim.
That is the point — re-rendering a 9:16 version of a clip that already exists
costs minutes of the one card, and cropping it costs seconds of CPU. The
expensive tool is the last resort here for exactly the reason it is in
`repair.py`.

**How the crop is chosen.** Centre, always. Smarter framing needs subject
detection, and a wrong guess crops the product out of its own advert — the one
failure that makes the whole output worthless rather than merely imperfect. A
centre crop is predictable, and the preview shows the owner what they get.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg import FFMPEG, VideoProcessingError, _run, probe_duration

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Format:
    key: str
    title: str
    #: width:height as integers, used to build the crop expression.
    ratio: tuple[int, int]
    #: Hard cap in seconds; None means keep the whole thing.
    max_seconds: int | None
    where: str

    @property
    def label(self) -> str:
        return f"{self.title} ({self.ratio[0]}:{self.ratio[1]})"


#: The cuts an Iranian shop actually publishes. Not a catalogue of every
#: possible size — each one here corresponds to a place they post.
FORMATS = [
    Format("reel", "ریلز اینستاگرام", (9, 16), 60, "اینستاگرام · ریلز"),
    Format("story", "استوری", (9, 16), 15, "اینستاگرام · استوری"),
    Format("feed", "پست فید", (4, 5), 60, "اینستاگرام · پست"),
    Format("square", "مربع", (1, 1), 60, "پست عمومی، تبلیغات"),
    Format("wide", "افقی", (16, 9), None, "یوتیوب، سایت، تلگرام"),
]

FORMATS_BY_KEY = {f.key: f for f in FORMATS}


def crop_filter(ratio: tuple[int, int], centre: tuple[float, float] | None = None) -> str:
    """Crop to a ratio around `centre` (fractions of the frame), then scale to
    an even-sided frame.

    Centre-of-frame when no centre is known. With one — the largest face, or
    the product's own position — the window slides so the subject stays in:
    an 832×480 clip cut to 9:16 keeps only 32 % of its columns, and a product
    standing at two thirds of the width was being cut out of its own reel.

    The `-2` in the scale keeps the height even, which h264 requires — an odd
    dimension fails the encode with a message that says nothing about ratios.
    """
    w, h = ratio
    cx, cy = centre if centre else (0.5, 0.5)
    cx = max(0.0, min(1.0, float(cx)))
    cy = max(0.0, min(1.0, float(cy)))
    # Take the largest rectangle of this ratio that fits the source, placed so
    # its centre is as close to (cx, cy) as the frame allows.
    return (
        f"crop='min(iw,ih*{w}/{h})':'min(ih,iw*{h}/{w})':"
        f"x='(iw-ow)*{cx:.3f}':y='(ih-oh)*{cy:.3f}',"
        f"scale={1080 if w >= h else -2}:{1080 if h > w else -2}:"
        "force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )


def centre_from_boxes(boxes) -> tuple[float, float] | None:
    """Where to keep the frame centred, from face boxes (dicts or Boxes)."""
    rows = []
    for box in boxes or []:
        try:
            x, y, w, h = (float(box[k]) if isinstance(box, dict) else float(getattr(box, k))
                          for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        rows.append((x + w / 2, y + h / 2, w * h))
    if not rows:
        return None
    x, y, _ = max(rows, key=lambda r: r[2])
    return x, y


def subject_centre(video_path, work_dir) -> tuple[float, float] | None:
    """Where the subject is, without a model: faces first, then whatever
    differs from the backdrop.

    The backdrop is taken as the median colour of the frame's border; pixels
    far from it are the subject, and their centroid — averaged over a few
    frames spread across the clip — is where the crop should look. When the
    mask is almost nothing or almost everything (a busy background), there is
    no subject to speak of and the centre of the frame is the honest answer.
    """
    from services.video import faces, qc

    try:
        who = faces.in_video(video_path, work_dir)
        centre = centre_from_boxes(who.get("boxes"))
        if centre:
            return centre
    except Exception as exc:  # noqa: BLE001
        logger.info("subject_centre: faces unavailable: %s", exc)

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    frames = qc.sample_frames(video_path, Path(work_dir) / "subject", 4, width=160, prefix="sub")
    xs, ys = [], []
    for frame in frames:
        try:
            pixels = np.asarray(Image.open(frame).convert("RGB"), dtype=np.float32)
        except Exception:  # noqa: BLE001
            continue
        height, width = pixels.shape[:2]
        border = np.concatenate([
            pixels[:8].reshape(-1, 3), pixels[-8:].reshape(-1, 3),
            pixels[:, :8].reshape(-1, 3), pixels[:, -8:].reshape(-1, 3),
        ])
        backdrop = np.median(border, axis=0)
        mask = np.abs(pixels - backdrop).sum(axis=2) > 40
        share = float(mask.mean())
        if share < 0.05 or share > 0.70:
            continue
        rows, cols = np.nonzero(mask)
        xs.append(float(cols.mean()) / width)
        ys.append(float(rows.mean()) / height)
    for frame in frames:
        try:
            frame.unlink()
        except OSError:
            pass
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def available_formats(source_seconds: float | None = None) -> list[dict]:
    """What can be made from a clip of this length.

    A 10-second video cannot become a 60-second reel, and offering the option
    would produce a file identical to the source under a different name — which
    reads as a broken feature rather than a sensible no-op.
    """
    rows = []
    for fmt in FORMATS:
        entry = {
            "key": fmt.key,
            "title": fmt.title,
            "label": fmt.label,
            "where": fmt.where,
            "max_seconds": fmt.max_seconds,
            "trims": bool(
                fmt.max_seconds and source_seconds and source_seconds > fmt.max_seconds
            ),
        }
        rows.append(entry)
    return rows


def make(video_path, fmt: Format, out_dir, *, filename: str | None = None,
         centre: tuple[float, float] | None = None) -> Path:
    """Produce one cut. Raises VideoProcessingError if ffmpeg refuses."""
    from .ffmpeg import VIDEO_DELIVERY

    source = Path(video_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / (filename or f"{source.stem}_{fmt.key}.mp4")

    command = [FFMPEG, "-y", "-i", str(source)]
    if fmt.max_seconds:
        command += ["-t", str(fmt.max_seconds)]
    command += [
        "-vf", crop_filter(fmt.ratio, centre),
        # Audio is copied rather than re-encoded: the narration was already
        # mixed and timed, and a second encode only loses quality.
        "-c:a", "copy",
        *VIDEO_DELIVERY,
        str(dest),
    ]
    _run(command)

    if not dest.exists() or dest.stat().st_size == 0:
        raise VideoProcessingError(f"خروجی {fmt.key} نوشته نشد")
    return dest


def make_all(video_path, out_dir, keys: list[str] | None = None) -> list[dict]:
    """Every requested cut. One failure does not lose the others.

    A shop that asked for five formats and got four plus a clear message about
    the fifth is better served than one that got an exception — the four are
    publishable today.
    """
    try:
        duration = probe_duration(video_path)
    except VideoProcessingError:
        duration = None

    # Where the subject is, measured once for every cut. None → centre crop,
    # the predictable answer when nothing stands out.
    try:
        centre = subject_centre(video_path, Path(out_dir) / "_subject")
    except Exception as exc:  # noqa: BLE001 — a centre crop is never wrong, only worse
        logger.info("Repurpose: subject centre unavailable: %s", exc)
        centre = None

    wanted = [FORMATS_BY_KEY[k] for k in (keys or list(FORMATS_BY_KEY)) if k in FORMATS_BY_KEY]
    results = []
    for fmt in wanted:
        try:
            path = make(video_path, fmt, out_dir, centre=centre)
        except VideoProcessingError as exc:
            logger.info("Repurpose to %s failed: %s", fmt.key, exc)
            results.append({
                "key": fmt.key,
                "title": fmt.title,
                "ok": False,
                "error": str(exc)[:200],
            })
            continue
        results.append({
            "key": fmt.key,
            "title": fmt.title,
            "label": fmt.label,
            "where": fmt.where,
            "ok": True,
            "path": str(path),
            "trimmed": bool(
                fmt.max_seconds and duration and duration > fmt.max_seconds
            ),
        })
    return results
