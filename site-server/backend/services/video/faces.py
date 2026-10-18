"""Where the people and the product are in the frame. §8.

Two jobs, both of which need the same answer — *what part of this frame must
not be covered or cropped away*:

* **Smart zoom.** A push-in that crops somebody's forehead off is worse than no
  zoom at all, so the crop window is anchored on what is actually in the shot.
* **Subtitle placement.** A caption across someone's mouth is the one placement
  everybody notices, and the default position — bottom centre — is exactly
  where a person standing in frame usually is.

**YuNet, with the Haar cascades as a fallback.** YuNet is OpenCV's own small
neural face detector (`cv2.FaceDetectorYN`, 230 KB ONNX, MIT, bundled in
`models/` — no download, CPU, no VRAM). Measured on five images with known
answers it was right five times; the Haar cascades it replaces were right
once: they missed a three-quarter face and a fashion model's face, and found
a "face" in a red bottle (93 % of the frame) and in a sofa cushion. The
cascades are still here for an install where the model file is missing.

**Frontal *and* profile.** YuNet handles a head turned well past three
quarters. The Haar fallback runs the profile cascade twice (it only detects
one direction, so the frame is mirrored and searched again).

A miss still degrades gracefully: the subtitle goes to its default position,
which is where it would have been with no detection at all.

**Every function answers "I could not look" differently from "there is nobody
there".** A missing OpenCV and an empty frame lead to opposite decisions: the
first means fall back to the default, the second means the frame is free.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Below this fraction of the frame, a "face" is a pattern in the carpet.
MIN_FACE_FRACTION = 0.01

#: The bundled YuNet model, and the confidence it must reach.
YUNET_MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
YUNET_SCORE = 0.7

#: How much of the frame's height the subtitle band occupies, per position.
#: Used to test whether a caption would land on somebody.
BAND = 0.18

#: A zoom that crops closer than this to a face edge is going to clip an ear or
#: a chin on the next frame, when the person moves.
FACE_MARGIN = 0.06


@dataclass
class Box:
    """A region of interest, in fractions of the frame (0–1)."""

    x: float
    y: float
    w: float
    h: float
    kind: str = "face"

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def centre(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h

    def as_dict(self) -> dict:
        return {
            "x": round(self.x, 4), "y": round(self.y, 4),
            "w": round(self.w, 4), "h": round(self.h, 4),
            "kind": self.kind,
        }


def available() -> tuple[bool, str]:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False, (
            "OpenCV نصب نیست. برای زوم روی چهره و جای هوشمند زیرنویس لازم است: "
            "`pip install opencv-python-headless`"
        )
    return True, ""


def _cascade(name: str = "haarcascade_frontalface_default.xml"):
    import cv2

    path = Path(cv2.data.haarcascades) / name
    if not path.exists():  # pragma: no cover — a broken OpenCV install
        raise RuntimeError(f"فایل تشخیص چهره پیدا نشد: {path}")
    return cv2.CascadeClassifier(str(path))


def in_image(image_path) -> list[Box]:
    """Faces in one frame, as fractions of the frame.

    Fractions rather than pixels so the answer survives every later scale and
    crop — the same numbers are valid for the 1080×1920 reel and the 1080×1080
    square cut from it.
    """
    ok, why = available()
    if not ok:
        raise RuntimeError(why)

    import cv2

    frame = cv2.imread(str(image_path))
    if frame is None:
        raise RuntimeError(f"این فریم خوانده نشد: {image_path}")

    height, width = frame.shape[:2]
    neural = _yunet(frame)
    if neural is not None:
        return _merge([b for b in neural if b.area >= MIN_FACE_FRACTION])

    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    grey = cv2.equalizeHist(grey)
    smallest = (int(width * 0.05), int(height * 0.05))

    def detect(cascade_name, image):
        return _cascade(cascade_name).detectMultiScale(
            image, scaleFactor=1.1, minNeighbors=5, minSize=smallest,
        )

    found = list(detect("haarcascade_frontalface_default.xml", grey))

    # Sideways heads. The profile cascade only finds one direction, so the
    # mirrored frame is searched for the other — and a hit there has to be
    # flipped back into the original frame's coordinates.
    try:
        found += list(detect("haarcascade_profileface.xml", grey))
        for (x, y, w, h) in detect("haarcascade_profileface.xml", cv2.flip(grey, 1)):
            found.append((width - x - w, y, w, h))
    except RuntimeError:  # pragma: no cover — cascade file absent
        logger.debug("Profile cascade unavailable; frontal faces only")

    boxes = []
    for (x, y, w, h) in found:
        box = Box(x / width, y / height, w / width, h / height, "face")
        if box.area >= MIN_FACE_FRACTION:
            boxes.append(box)

    # One box per person: the frontal and profile passes routinely both find
    # the same three-quarter-view face, and two boxes on one head would make a
    # zoom think it has two people to keep in frame.
    return _merge(boxes)


def _yunet(frame) -> list[Box] | None:
    """Faces by YuNet, or None when the detector cannot run here."""
    import cv2

    if not YUNET_MODEL.exists() or not hasattr(cv2, "FaceDetectorYN"):
        return None
    height, width = frame.shape[:2]
    try:
        detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (width, height),
                                             score_threshold=YUNET_SCORE)
        _ok, found = detector.detect(frame)
    except cv2.error as exc:  # pragma: no cover — a broken OpenCV build
        logger.info("YuNet unavailable, using the cascades: %s", exc)
        return None
    boxes = []
    for row in ([] if found is None else found):
        x, y, w, h = (float(v) for v in row[:4])
        x, y = max(0.0, x), max(0.0, y)
        w, h = min(w, width - x), min(h, height - y)
        if w > 0 and h > 0:
            boxes.append(Box(x / width, y / height, w / width, h / height, "face"))
    return boxes


def in_video(video_path, work_dir, *, samples: int = 6) -> dict:
    """Faces across a whole clip, merged into the regions to protect.

    Sampled rather than every frame: a person does not usually leave the frame
    mid-shot, and decoding every frame to find that out costs more than the
    edit it informs.
    """
    from services.video import qc

    ok, why = available()
    if not ok:
        return {"looked": False, "reason": why, "boxes": [], "faces": 0}

    # Spread over the whole clip (a person who walks in at second twenty is
    # still a person) and wide enough for the cascade to see a face at 5 % of
    # the frame — at 256 px that minimum was a twelve-pixel smudge.
    frames = qc.sample_frames(
        video_path, Path(work_dir) / "faces", count=samples, width=512, prefix="face",
    )
    if not frames:
        # "Could not look" — a missing ffmpeg, an unreadable file. Not the same
        # as "nobody is there", and the caller must not treat it as such.
        return {
            "looked": False,
            "reason": "فریمی برای بررسی استخراج نشد",
            "boxes": [],
            "faces": 0,
        }

    per_frame, total = [], 0
    for frame in frames:
        try:
            boxes = in_image(frame)
        except Exception as exc:  # noqa: BLE001 — one bad frame is data
            logger.debug("Face detection failed on %s: %s", frame, exc)
            continue
        total += len(boxes)
        per_frame.append(boxes)

    merged = _merge([b for boxes in per_frame for b in boxes])
    return {
        "looked": True,
        "reason": "",
        "boxes": [b.as_dict() for b in merged],
        # Frames with somebody in them, not the number of detections: three
        # sightings of one person is one person.
        "faces": len(merged),
        "frames_with_faces": sum(1 for boxes in per_frame if boxes),
        "frames_sampled": len(per_frame),
        "raw_detections": total,
    }


def _merge(boxes: list[Box], overlap: float = 0.3) -> list[Box]:
    """One box per person, not one per sighting."""
    merged: list[Box] = []
    for box in sorted(boxes, key=lambda b: -b.area):
        for existing in merged:
            if _overlap(box, existing) > overlap:
                # Widen to cover both: the person moved between samples, and
                # the region to protect is everywhere they were.
                right = max(existing.x + existing.w, box.x + box.w)
                bottom = max(existing.bottom, box.bottom)
                existing.x = min(existing.x, box.x)
                existing.y = min(existing.y, box.y)
                existing.w = right - existing.x
                existing.h = bottom - existing.y
                break
        else:
            merged.append(Box(box.x, box.y, box.w, box.h, box.kind))
    return merged


def _overlap(a: Box, b: Box) -> float:
    left = max(a.x, b.x)
    top = max(a.y, b.y)
    right = min(a.x + a.w, b.x + b.w)
    bottom = min(a.bottom, b.bottom)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    union = a.area + b.area - intersection
    return intersection / union if union else 0.0


# ------------------------------------------------------------- decisions


def best_caption_position(boxes, *, default: str = "bottom") -> str:
    """Where the subtitle can go without landing on a person.

    `boxes` may be dicts or `Box`es — the analysis layer stores them as dicts.
    An empty list means the frame is clear, and the default stands; that is
    correct, because bottom-centre is the right answer whenever it is free.
    """
    rows = [b if isinstance(b, Box) else Box(**{
        k: b[k] for k in ("x", "y", "w", "h")
    }) for b in (boxes or [])]
    if not rows:
        return default

    bands = {
        "bottom": (1.0 - BAND, 1.0),
        "middle": (0.5 - BAND / 2, 0.5 + BAND / 2),
        "top": (0.0, BAND),
    }
    # The default first: a caption that could stay where it belongs should.
    order = [default] + [k for k in ("bottom", "middle", "top") if k != default]

    for name in order:
        low, high = bands[name]
        if not any(box.bottom > low and box.y < high for box in rows):
            return name
    # Everywhere is occupied. Bottom is still the least bad — a subtitle over a
    # chest is readable; one over a mouth is what people complain about.
    return "bottom"


def zoom_window(boxes, scale: float) -> tuple[float, float]:
    """Where to centre a push-in, as fractions of the frame.

    Anchored on the biggest face when there is one, because a zoom that crops
    a forehead off is worse than no zoom. With nobody in shot it returns the
    centre, which is what an un-anchored zoom does anyway.
    """
    rows = [b if isinstance(b, Box) else Box(**{
        k: b[k] for k in ("x", "y", "w", "h")
    }) for b in (boxes or [])]
    if not rows:
        return 0.5, 0.5

    biggest = max(rows, key=lambda b: b.area)
    x, y = biggest.centre
    # Faces sit in the upper half of a portrait; centring on the exact middle of
    # the box puts the crop low and cuts the top of the head.
    y = max(0.0, y - biggest.h * 0.15)

    # Keep the crop window inside the frame, or ffmpeg silently clamps it and
    # the zoom drifts somewhere nobody chose.
    half_w = 1.0 / (2 * max(1.01, scale))
    half_h = half_w
    return (
        min(max(x, half_w), 1 - half_w),
        min(max(y, half_h), 1 - half_h),
    )


def safe_to_zoom(boxes, scale: float) -> tuple[bool, str]:
    """Would this zoom cut somebody off?"""
    rows = [b if isinstance(b, Box) else Box(**{
        k: b[k] for k in ("x", "y", "w", "h")
    }) for b in (boxes or [])]
    if not rows:
        return True, ""

    centre_x, centre_y = zoom_window(rows, scale)
    half = 1.0 / (2 * max(1.01, scale))
    left, right = centre_x - half, centre_x + half
    top, bottom = centre_y - half, centre_y + half

    for box in rows:
        if (box.x < left - FACE_MARGIN or box.x + box.w > right + FACE_MARGIN
                or box.y < top - FACE_MARGIN or box.bottom > bottom + FACE_MARGIN):
            return False, (
                f"با این بزرگ‌نمایی ({scale:g}×) بخشی از چهره از کادر بیرون "
                "می‌افتد. عدد کوچک‌تری بگذارید."
            )
    return True, ""
