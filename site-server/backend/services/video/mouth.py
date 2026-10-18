"""Is the person in this clip talking? For voice-over scenes, they must not be.

Every narration here is a voice-over. A person on screen whose lips move is
either miming silently or "saying" the narrator's words with the wrong mouth —
the most artificial-looking thing a product video can do, and Wan animates
mouths freely. The prompt asks for a closed mouth (scene_state.MOUTH_CLOSED);
this measures whether the model listened.

**How.** The largest face the detector finds (OpenCV Haar, already used for
face-aware zoom) is followed through the clip at 16 fps, 96×96 greyscale.
Each crop is aligned to the first with SUB-pixel phase correlation — a slow
camera pan moves a face crop by a fraction of a pixel per frame, and integer
alignment left every edge of the face flickering as if it moved (measured).
Then, on the brightness of the inner mouth (an open mouth shows the dark
cavity):

* **contrast** — how much the inner mouth changes, relative to how much an
  equally sized patch of the upper face changes. Camera flicker, compression
  noise and a nod move both; talking moves the mouth.
* **rhythm** — how sharply that change peaks at speech rate (2–7 Hz: four or
  five syllables a second) against the rest of its spectrum. Noise is flat;
  a slow smile or a blink has no peak there.
* **amplitude** — the change in grey levels. A crisp 4 Hz peak of a tenth
  of a grey level is compression, not a mouth.

All three must agree before a scene is called talking. A face too small to
read (under ~40 px tall at the source), no face, or a face seen in only one
frame means "could not check" — never "talking".

The detector can mistake an object for a face (measured on a product render:
a red bottle came back as a "face" covering 93 % of the frame), so a candidate
must also be face-shaped: square-ish, between 0.3 % and 30 % of the frame.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

FPS = 16.0
SIZE = 96
#: Where to look for the lips inside the (padded) face crop, as fractions:
#: rows of the lower face, and the central columns. Not a fixed mouth box —
#: a face looking up has its mouth at 0.64 of the crop, one looking down at
#: 0.80 (measured on the test portrait), so the lips are FOUND (`_mouth_row`).
LIP_SEARCH_ROWS = (0.50, 0.92)
MOUTH_COLS = (0.30, 0.70)
#: The mouth window around the lip line: a little above (upper lip) and more
#: below (an opening mouth and the jaw drop downwards).
MOUTH_ABOVE, MOUTH_BELOW = 0.05, 0.11
#: The comparison patch: forehead, same size, same columns.
REFERENCE_TOP = 0.08

#: Thresholds (contrast, rhythm, amplitude), set halfway (geometrically)
#: between talking and silent as measured on a real portrait under a panning
#: camera, with a synthetic mouth. Two sets, because the regions differ.
#:
#: With YuNet landmarks (mouth window between the mouth corners, reference on
#: the bridge of the nose):
#:                   contrast  rhythm  amplitude
#:   talking 4.5 Hz    3.19     351      1.69
#:   talking, subtle   1.81     999      1.00
#:   still             0.40     277      0.23
#:   blink every 3 s   0.32     209      0.21
#:   nod at 1 Hz       0.54      69      0.45
#: Rhythm no longer separates here (a still mouth's tiny flicker can peak
#: anywhere); contrast and amplitude do, by 3× and 2×.
#:
#: Without landmarks (lips found as the darkest band, forehead reference):
#:   talking 4.5 Hz    3.58     399      0.89
#:   talking, subtle   2.65     379      0.63
#:   still             1.53      52      0.36
#:   blink every 3 s   1.30      57      0.33
#:   nod at 1 Hz       0.79       7      0.36
#:
#: Real Wan footage should be re-measured on the main system and these moved
#: if it disagrees.
THRESHOLDS = {
    "landmarks": (1.0, 150.0, 0.67),
    "fallback": (2.0, 150.0, 0.45),
}
MIN_CONTRAST, MIN_RHYTHM, MIN_AMPLITUDE = THRESHOLDS["fallback"]
SPEECH_BAND = (2.0, 7.0)

#: Face-shaped: pixel aspect w/h, and share of the frame.
ASPECT = (0.7, 1.45)
AREA = (0.003, 0.30)
MIN_FACE_PX = 40


def _face(video_path, work_dir) -> tuple[dict | None, str]:
    """The face to watch, or (None, why not)."""
    from services.video import faces
    from services.video.ffmpeg import probe_video

    ok, why = faces.available()
    if not ok:
        return None, why
    found = faces.in_video(video_path, work_dir, samples=6)
    if not found.get("looked"):
        return None, found.get("reason") or "فریمی بررسی نشد"
    if found.get("frames_with_faces", 0) < 2:
        return None, "چهره‌ای در تصویر دیده نشد"
    info = probe_video(video_path)
    width, height = info["width"], info["height"]
    candidates = []
    for box in found.get("boxes", []):
        w_px, h_px = box["w"] * width, box["h"] * height
        area = box["w"] * box["h"]
        if not (AREA[0] <= area <= AREA[1]):
            continue
        if not (ASPECT[0] <= w_px / max(1.0, h_px) <= ASPECT[1]):
            continue
        if h_px < MIN_FACE_PX:
            continue
        candidates.append({**box, "width": width, "height": height})
    if not candidates:
        return None, "چهره‌ای به اندازه‌ی کافی بزرگ و واضح برای دیدن لب‌ها نبود"
    return max(candidates, key=lambda b: b["w"] * b["h"]), ""


def _crops(video_path, face: dict):
    """The face region of every frame, SIZE×SIZE greyscale, as float (n, SIZE, SIZE)."""
    import numpy as np

    from services.video.ffmpeg import FFMPEG

    width, height = face["width"], face["height"]
    # A little margin: the box is from sampled frames and heads move.
    pad_w, pad_h = face["w"] * 0.12, face["h"] * 0.12
    x = max(0.0, face["x"] - pad_w)
    y = max(0.0, face["y"] - pad_h)
    w = min(1.0 - x, face["w"] + 2 * pad_w)
    h = min(1.0 - y, face["h"] + 2 * pad_h)
    crop = f"crop={int(w * width)}:{int(h * height)}:{int(x * width)}:{int(y * height)}"
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(video_path), "-an",
         "-vf", f"fps={FPS},{crop},scale={SIZE}:{SIZE}:flags=area,format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, timeout=120,
    ).stdout
    count = len(raw) // (SIZE * SIZE)
    if count < 8:
        return None
    frames = np.frombuffer(raw[: count * SIZE * SIZE], dtype=np.uint8).reshape(count, SIZE, SIZE)
    return frames.astype(np.float32), (w, h)


def _align(frames):
    """Each frame shifted onto the first, to a fraction of a pixel.

    Phase correlation finds the integer peak; a parabola through it and its
    neighbours gives the fraction; the shift itself is applied in the
    frequency domain, which moves an image by 0.3 px without blurring it.
    """
    import numpy as np

    size_y, size_x = frames.shape[1:]
    ky = np.fft.fftfreq(size_y)[:, None]
    kx = np.fft.fftfreq(size_x)[None, :]
    first = frames[0]
    f0 = np.fft.fft2(first - first.mean())
    out = [first]
    for frame in frames[1:]:
        spectrum = np.fft.fft2(frame)
        f1 = np.fft.fft2(frame - frame.mean())
        cross = f0 * np.conj(f1)
        cross /= np.abs(cross) + 1e-9
        corr = np.real(np.fft.ifft2(cross))
        py, px = np.unravel_index(int(np.argmax(corr)), corr.shape)

        def refine(minus, centre, plus):
            denom = minus - 2 * centre + plus
            return 0.5 * (minus - plus) / denom if denom else 0.0

        dy = py + refine(corr[(py - 1) % size_y, px], corr[py, px], corr[(py + 1) % size_y, px])
        dx = px + refine(corr[py, (px - 1) % size_x], corr[py, px], corr[py, (px + 1) % size_x])
        dy = dy - size_y if dy > size_y / 2 else dy
        dx = dx - size_x if dx > size_x / 2 else dx
        shifted = np.real(np.fft.ifft2(spectrum * np.exp(-2j * np.pi * (ky * dy + kx * dx))))
        out.append(shifted.astype(np.float32))
    return np.stack(out)


def _region(frames, box):
    top, bottom, left, right = box
    return frames[:, int(top * SIZE): int(bottom * SIZE), int(left * SIZE): int(right * SIZE)]


def _landmarks(frames) -> dict | None:
    """Eyes, nose tip and mouth corners on the median face crop (YuNet).

    Fractions of the crop. The median frame, so an opening mouth or a blink
    does not move them. None without the model, or when YuNet does not see a
    face in the crop (the fallback then finds the lips by their darkness).
    """
    import cv2
    import numpy as np

    from services.video import faces

    if not faces.YUNET_MODEL.exists() or not hasattr(cv2, "FaceDetectorYN"):
        return None
    median = np.clip(np.median(frames, axis=0), 0, 255).astype(np.uint8)
    # YuNet wants a colour image, and room around the face.
    big = cv2.resize(median, (SIZE * 3, SIZE * 3), interpolation=cv2.INTER_CUBIC)
    colour = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    detector = cv2.FaceDetectorYN.create(str(faces.YUNET_MODEL), "", (SIZE * 3, SIZE * 3),
                                         score_threshold=0.6)
    _ok, found = detector.detect(colour)
    if found is None or not len(found):
        return None
    best = max(found, key=lambda row: row[2] * row[3])
    scale = 1.0 / (SIZE * 3)
    point = lambda i: (float(best[4 + 2 * i]) * scale, float(best[5 + 2 * i]) * scale)  # noqa: E731
    return {
        "right_eye": point(0), "left_eye": point(1), "nose": point(2),
        "mouth_right": point(3), "mouth_left": point(4),
    }


def _regions_from(marks: dict) -> tuple[tuple, tuple]:
    """(mouth window, reference patch) from landmarks, as crop fractions.

    The mouth window spans the mouth corners with a margin and reaches down
    for an opening jaw. The reference is the bridge of the nose between the
    eyes and the nose tip: skin that moves with the head, the camera and the
    light, but not with the mouth — and, unlike the forehead, never hair.
    """
    (mrx, mry), (mlx, mly) = marks["mouth_right"], marks["mouth_left"]
    (rex, rey), (lex, ley) = marks["right_eye"], marks["left_eye"]
    nose_x, nose_y = marks["nose"]
    width = abs(mlx - mrx)
    lips = (mry + mly) / 2
    mouth = (lips - 0.35 * width, lips + 0.55 * width,
             min(mrx, mlx) + 0.1 * width, max(mrx, mlx) - 0.1 * width)
    eyes_y = (rey + ley) / 2
    half = 0.2 * width
    top = eyes_y + 0.25 * (nose_y - eyes_y)
    reference = (top, top + (mouth[1] - mouth[0]) * 0.6, nose_x - half, nose_x + half)
    clamp = lambda box: tuple(min(1.0, max(0.0, v)) for v in box)  # noqa: E731
    return clamp(mouth), clamp(reference)


def _mouth_row(frames) -> float:
    """The lip line, as a fraction of the crop height.

    In the lower face, the line between the lips is the darkest horizontal
    band (shadowed and pigmented), in any lighting that lets you see a face.
    Taken from the median frame, so an opening mouth does not move it.
    """
    import numpy as np

    median = np.median(frames, axis=0)
    left, right = int(MOUTH_COLS[0] * SIZE), int(MOUTH_COLS[1] * SIZE)
    top, bottom = int(LIP_SEARCH_ROWS[0] * SIZE), int(LIP_SEARCH_ROWS[1] * SIZE)
    profile = median[top:bottom, left:right].mean(axis=1)
    profile = np.convolve(profile, np.ones(3) / 3, mode="same")
    return (top + int(np.argmin(profile[1:-1])) + 1) / SIZE


def _changes(series):
    """A region's brightness over time, slow drift removed."""
    import numpy as np

    return series - np.convolve(series, np.ones(9) / 9, mode="same")


def analyse(frames) -> dict:
    """contrast, rhythm, amplitude from aligned face crops. Public for testing.

    Measured on a real (public-domain) portrait under a slow camera pan, with
    a synthetic mouth: open/close at 4.5 Hz and at 4 Hz half as wide, a
    blink every 3 s, and a 1 Hz nod — the table is above MIN_CONTRAST.
    """
    import numpy as np

    marks = _landmarks(frames)
    if marks is not None:
        window, reference = _regions_from(marks)
        lips = (window[0] + window[1]) / 2
    else:
        # No landmarks: the lips are the darkest band of the lower face, and
        # the forehead is the comparison.
        lips = _mouth_row(frames)
        window = (max(0.0, lips - MOUTH_ABOVE), min(1.0, lips + MOUTH_BELOW), *MOUTH_COLS)
        height = MOUTH_ABOVE + MOUTH_BELOW
        reference = (REFERENCE_TOP, REFERENCE_TOP + height, *MOUTH_COLS)
    inner = _region(frames, window).mean(axis=(1, 2))
    upper = _region(frames, reference).mean(axis=(1, 2))
    mouth_change = _changes(inner)[4:-4]
    upper_change = _changes(upper)[4:-4]
    if len(mouth_change) < 12:
        return {"contrast": 0.0, "rhythm": 0.0, "amplitude": 0.0}
    amplitude = float(np.std(mouth_change))
    contrast = float(amplitude / (np.std(upper_change) + 0.15))

    window = mouth_change * np.hanning(len(mouth_change))
    power = np.abs(np.fft.rfft(window)) ** 2
    freqs = np.fft.rfftfreq(len(window), d=1.0 / FPS)
    usable = (freqs >= 0.5) & (freqs <= FPS / 2)
    speech = (freqs >= SPEECH_BAND[0]) & (freqs <= SPEECH_BAND[1])
    floor = float(np.median(power[usable])) if usable.any() else 0.0
    rhythm = float(power[speech].max() / (floor + 1e-9)) if speech.any() else 0.0
    return {
        "contrast": round(contrast, 2),
        "rhythm": round(min(rhythm, 999.0), 1),
        "amplitude": round(amplitude, 2),
        "lips_at": round(lips, 2),
        "landmarks": marks is not None,
    }


def check(video_path, work_dir) -> dict:
    """{looked, talking, score, reason, contrast, rhythm, amplitude}. Never raises.

    `score` is the QC axis value: 100 for a still mouth, falling as the
    evidence of talking grows; None when it could not look.
    """
    out = {"looked": False, "talking": False, "score": None, "reason": ""}
    try:
        import numpy  # noqa: F401
    except ImportError:
        out["reason"] = "numpy نصب نیست"
        return out
    try:
        face, why = _face(video_path, Path(work_dir) / "mouth")
        if face is None:
            out["reason"] = why
            return out
        loaded = _crops(video_path, face)
        if loaded is None:
            out["reason"] = "فریم‌های چهره خوانده نشد"
            return out
        frames, _ = loaded
        numbers = analyse(_align(frames))
    except Exception as exc:  # noqa: BLE001 — a QC helper must never break a render
        logger.info("Mouth check failed for %s: %s", video_path, exc)
        out["reason"] = str(exc)[:200]
        return out

    min_contrast, min_rhythm, min_amplitude = THRESHOLDS[
        "landmarks" if numbers.get("landmarks") else "fallback"
    ]
    talking = (
        numbers["contrast"] >= min_contrast
        and numbers["rhythm"] >= min_rhythm
        and numbers["amplitude"] >= min_amplitude
    )
    # Evidence in [0, 1] per number; the weakest of the three decides.
    evidence = min(
        min(1.0, numbers["contrast"] / (min_contrast * 1.5)),
        min(1.0, numbers["rhythm"] / (min_rhythm * 1.5)),
        min(1.0, numbers["amplitude"] / (min_amplitude * 1.5)),
    )
    score = 35.0 if talking else round(100.0 - 25.0 * evidence, 1)
    out.update(numbers, looked=True, talking=talking, score=score)
    out["reason"] = (
        "آدمِ تصویر لب می‌زند، ولی صدای این صحنه گوینده‌ی روی تصویر است"
        if talking else "لب‌ها ساکن است"
    )
    return out
