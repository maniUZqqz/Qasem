"""Looking at what the video model actually produced, before the customer does.

ROADMAP §9.2 calls this "یکی از اصلی‌ترین مزیت‌های فنی محصول". `_should_pause`
reads a `quality_score` from segment metadata, Auto mode waits for one, and this
module writes it.

**The split, and why it is this way.** The checks are divided by what each tool
is actually good at:

* **Code (ffmpeg + Pillow + OpenCV), free and instant** — flicker, frozen
  frames, black frames, jump cuts, exposure, colour cast. These are statistical
  properties of pixels; a model is the wrong instrument and a slow one.
* **The vision model, one call** — "is this the same person?", "is this still
  the customer's product?", "are the hands right?". These are semantic and no
  histogram will ever answer them.

That division is also §9.3's repair ladder in disguise: everything the code
layer detects as a *tone* problem (exposure, cast, flicker) it can usually fix
with a filter, without spending a second of GPU. Everything semantic, and the
few code-detected defects no filter can undo (a black clip, a frozen clip, a
jump cut), needs a regeneration — and the report says which is which.

**Three measurement rules learned the hard way, all with a test behind them:**

1. *Mean luma is the wrong exposure measure for product video.* A product on a
   white background averages 220 and is not "burnt"; a gold watch on black
   averages 35 and is not "dark". Both were being auto-"corrected" into worse
   pictures. Exposure is judged from luma **percentiles** — dark means even the
   brightest 5 % of the frame is dim; burnt means even the darkest 5 % is
   bright and a quarter of the frame is clipped.
2. *A colour cast is measured on neutral pixels only.* Averaging R−B over a
   whole frame calls an orange product a "warm cast" and white-balances the
   product's true colour away — the one thing a shop cannot forgive. Only
   near-grey pixels can carry a cast; when a frame has too few of them, cast is
   simply not measurable and nothing is proposed.
3. *Flicker, freezes and jumps live between consecutive frames.* Eight stills
   half a second apart cannot see a 4 Hz strobe (measured: Δ37 between
   neighbours, Δ2.7 at 0.5 s) and only catch a frozen tail by luck. Those come
   from `frame_stats`, which reads every frame in one ffmpeg pass.

**What this deliberately does not do.** Level 2 of §9.3 — localised inpainting
of one bad hand — is not here. Doing it honestly needs segmentation masks and
an inpainting model; faking it with a blur would make a bad frame into a
smeared frame. The report says `localized_repair_available: False` rather than
pretending.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import frame_stats
from .ffmpeg import (
    FFMPEG,
    VideoProcessingError,
    _run,
    fps_mode_args,
    probe_duration,
    probe_video,
)

logger = logging.getLogger(__name__)

#: How many frames to sample for the spatial measurements. Eight is enough to
#: see exposure and a cast drift from start to end without turning QC into its
#: own render job — and they are spread over the WHOLE clip, first to last.
SAMPLE_FRAMES = 8

#: Width of the frames the code layer measures. Histograms survive the
#: downscale; the cost does not.
SAMPLE_WIDTH = 256

#: Frames the vision model sees, and how wide. Four is enough to see identity
#: drift; 640 px is the smallest size at which hands and logos are legible —
#: at 256 px the model was being asked to count fingers on a thumbnail.
VISION_FRAMES = 4
VISION_WIDTH = 640

#: Even the brightest 5 % of the frame below this: the model gave up.
BLACK_P95 = 24.0

#: Luma percentile thresholds. "dark": the midtones sit low AND nothing in the
#: frame reaches a real highlight (a lit product on black has highlights, an
#: underexposed phone clip does not). "blown": nothing in the frame is dark AND
#: a quarter of it is clipped.
DARK_P95 = 140.0
DARK_P50 = 55.0
BLOWN_CLIP = 0.25
#: A mid-grey product on a white backdrop has p5 ≈ 120 (its own shadows), so
#: the gate sits well above that: only a frame whose DARKEST 5 % is brighter
#: than 150 has nothing left to protect.
BLOWN_P5 = 150.0

#: Consecutive-frame luma step (0–255, full range) that reads as flicker.
FLICKER_DELTA = 12.0

#: Frozen: this share of the clip, or one still stretch this long.
FROZEN_SHARE = 0.3
FROZEN_SINGLE = 1.0

#: Neutral-pixel cast (mean R−B) above which the colour is judged to lean.
CAST_DELTA = 18.0
#: Cast drift between first and last frame worth mentioning.
CAST_DRIFT = 25.0

#: Fallbacks used only when the one-pass statistics could not be taken and the
#: old 0.5-second-apart comparison is all there is.
FALLBACK_FLICKER_DELTA = 14.0
FALLBACK_FROZEN_DIFF = 1.5

#: Regeneration causes the code layer can name. They share a namespace with
#: the vision causes (CHARACTER_CONSISTENCY, OBJECT_CONSISTENCY, ANATOMY,
#: ARTIFACTS) so the prompt compiler can look any of them up.
BLACK = "BLACK"
#: The product itself is too dark to rescue with a curve (repair.NAMES has it,
#: scene_state.HINTS asks for light on the product).
DARK = "DARK"
FROZEN = "FROZEN"
MOTION_JUMP = "MOTION_JUMP"
#: The scene's colour wanders from start to end. No static filter can undo a
#: time-varying change, so it is a regeneration cause, not a repair.
COLOUR_DRIFT = "COLOUR_DRIFT"

VISION_LABELS = {
    "character_consistency": "ثبات شخصیت",
    "object_consistency": "ثبات محصول",
    "anatomy": "آناتومی",
    "artifacts": "نبود خرابی تصویری",
}
VISION_CAUSES = tuple(key.upper() for key in VISION_LABELS)


@dataclass
class Axis:
    """One scored dimension, with the reason attached.

    The reason travels with the number because "Motion Quality: 61" tells a
    shop owner nothing, and "the clip freezes for about a second" tells them
    everything.
    """

    name: str
    score: float
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "score": round(self.score, 1), "note": self.note}


@dataclass
class QCReport:
    axes: list[Axis] = field(default_factory=list)
    overall: float = 0.0
    verdict: str = "REVIEW"
    code_fixable: list[str] = field(default_factory=list)
    needs_regeneration: list[str] = field(default_factory=list)
    vision_checked: bool = False
    #: Why the vision model did not look, when it did not — a policy, an
    #: outage, a missing model. Shown to the shop instead of a bare "no".
    vision_reason: str = ""
    #: What the vision model saw in the rendered frames (colours, clothing,
    #: background, people), for the next segment's continuity.
    observed: dict = field(default_factory=dict)
    #: The raw numbers every axis was derived from. This is what the repair
    #: layer sizes its filters from, and what phase 0.5 calibrates against.
    measurements: dict = field(default_factory=dict)
    localized_repair_available: bool = False
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "overall": round(self.overall, 1),
            "verdict": self.verdict,
            "axes": [a.as_dict() for a in self.axes],
            "code_fixable": self.code_fixable,
            "needs_regeneration": self.needs_regeneration,
            "vision_checked": self.vision_checked,
            "vision_reason": self.vision_reason,
            "observed": self.observed,
            "measurements": self.measurements,
            "localized_repair_available": self.localized_repair_available,
            "error": self.error,
        }

    @property
    def judged(self) -> bool:
        """Did anything actually get looked at?

        The distinction matters more than it looks. A segment QC scored badly
        should stop an Auto run; a segment QC **could not open** should not —
        that is a system problem (a missing ffmpeg, an unreadable file), and
        turning it into an approval prompt on every single segment would make a
        configuration error look like a quality collapse.
        """
        return not self.error and bool(self.axes)

    @property
    def score_fraction(self) -> float | None:
        """0–1 for `_should_pause`, or None when nobody could look.

        None is not "it passed" — it is "there is no verdict", and the pipeline
        treats it the same way it treated the absence of a score before this
        module existed.
        """
        if not self.judged:
            return None
        return self.overall / 100.0

    def axis(self, name: str) -> Axis | None:
        return next((a for a in self.axes if a.name == name), None)


# ---------------------------------------------------------------- frames


def sample_frames(video_path, out_dir, count: int = SAMPLE_FRAMES, *,
                  width: int = SAMPLE_WIDTH, prefix: str = "qc") -> list[Path]:
    """`count` frames spread evenly over the WHOLE clip, as PNGs.

    Evenly means evenly: frame k lands at k·duration/count, so the last sample
    is near the end — where a generated clip drifts most and where a frozen
    tail lives. (The previous version took `count` frames at a fixed 2 fps,
    which on any clip longer than four seconds meant "the first four
    seconds" and nothing after.)

    Empty list when ffmpeg cannot read the file.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob(f"{prefix}_*.png"):
        try:
            stale.unlink()
        except OSError:
            pass
    pattern = out / f"{prefix}_%02d.png"

    total_frames = 0
    try:
        shape = probe_video(video_path)
        total_frames = int(shape.get("frames") or 0)
        if not total_frames and shape.get("duration") and shape.get("fps"):
            total_frames = int(round(float(shape["duration"]) * float(shape["fps"])))
    except Exception as exc:  # noqa: BLE001 — fall back to a fixed rate below
        logger.info("QC could not probe %s: %s", video_path, exc)

    if total_frames >= count >= 2:
        # Exact frame numbers, first and LAST included: frame k of count sits at
        # k·(N−1)/(count−1). The final frame is the next segment's anchor and
        # the one an image-to-video model degrades most, so it is never skipped.
        wanted = sorted({round(k * (total_frames - 1) / (count - 1)) for k in range(count)})
        expression = "+".join(f"eq(n\\,{n})" for n in wanted)
        chain = f"select='{expression}',scale={width}:-2"
        extra = fps_mode_args("passthrough")
    else:
        try:
            duration = probe_duration(video_path)
        except Exception:  # noqa: BLE001
            duration = 0.0
        rate = f"{count}/{duration:.3f}" if duration > 0 else str(max(1, count // 3))
        chain = f"fps={rate},scale={width}:-2"
        extra = []

    try:
        _run([
            FFMPEG, "-y", "-i", str(video_path),
            "-vf", chain, *extra,
            "-frames:v", str(count), "-q:v", "3", str(pattern),
        ])
    except VideoProcessingError as exc:
        logger.info("QC could not sample frames from %s: %s", video_path, exc)
        return []
    return sorted(out.glob(f"{prefix}_*.png"))


# ------------------------------------------------------------ code layer


def _luma(image) -> float:
    """Mean brightness, 0–255."""
    grey = image.convert("L")
    histogram = grey.histogram()
    total = sum(histogram)
    if not total:
        return 0.0
    return sum(i * n for i, n in enumerate(histogram)) / total


def _mean_abs_diff(a, b) -> float:
    """Average absolute pixel difference between two frames, 0–255."""
    from PIL import ImageChops

    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a.convert("L"), b.convert("L"))
    histogram = diff.histogram()
    total = sum(histogram)
    if not total:
        return 0.0
    return sum(i * n for i, n in enumerate(histogram)) / total


def _clipping(image) -> float:
    """Fraction of pixels crushed to black or blown to white."""
    histogram = image.convert("L").histogram()
    total = sum(histogram) or 1
    crushed = sum(histogram[:6])
    blown = sum(histogram[250:])
    return (crushed + blown) / total


def _mean_rgb(image) -> tuple[float, float, float]:
    small = image.convert("RGB").resize((32, 32))
    pixels = list(small.getdata())
    n = len(pixels) or 1
    return (
        sum(p[0] for p in pixels) / n,
        sum(p[1] for p in pixels) / n,
        sum(p[2] for p in pixels) / n,
    )


def luma_stats(image) -> dict:
    """Luma percentiles and clipped fractions, from the histogram.

    Percentiles rather than the mean, because the mean cannot tell a white
    background from a burnt frame or a black background from an underexposed
    one — and both mistakes turn into a filter that makes the picture worse.
    """
    histogram = image.convert("L").histogram()
    total = sum(histogram) or 1
    wanted = {5: None, 50: None, 95: None}
    seen = 0
    for value, count in enumerate(histogram):
        seen += count
        for p in wanted:
            if wanted[p] is None and seen >= total * p / 100:
                wanted[p] = value
    return {
        "p5": float(wanted[5] or 0),
        "p50": float(wanted[50] or 0),
        "p95": float(wanted[95] or 0),
        "mean": sum(i * n for i, n in enumerate(histogram)) / total,
        "clip_hi": sum(histogram[250:]) / total,
        "clip_lo": sum(histogram[:6]) / total,
    }


#: The product's own light, measured inside its outline (product_region) and
#: judged RELATIVE TO THE SHOP'S PRODUCT PHOTO (`ratio` = product midtone in
#: the video / in the photo). Absolute thresholds cannot work: a black leather
#: bag has a midtone of 40 in a perfect shot, a white sneaker 200. Measured on
#: a lamp: well lit 163/171 = 0.95; darkened to 28 % brightness 49/171 = 0.29.
PRODUCT_DARK_RATIO = 0.55
PRODUCT_LIT_RATIO = (0.7, 1.5)
PRODUCT_CLIP = 0.15
PRODUCT_BURNT_CLIP = 0.25
#: Whatever the photo says, a product whose brightest 5 % is below this is
#: not visible, and below the second a gamma lift would only show noise —
#: that is a re-render with the light on the product.
PRODUCT_INVISIBLE_P95 = 60.0
PRODUCT_RERENDER_RATIO = 0.4


def product_exposure(video_path, product_image_path, *, samples: int = 8) -> dict | None:
    """Luma percentiles INSIDE the product's outline, across the clip.

    None when the product cannot be located in enough frames (a plain
    product with no texture, or one that is not in this shot) — the frame-wide
    judgement then stands alone, as before.
    """
    import subprocess

    import numpy as np

    from services.video import product_region
    from services.video.ffmpeg import FFMPEG, probe_video

    try:
        matcher = product_region.Matcher(product_image_path)
        info = probe_video(video_path)
        width = 640
        height = int(round(width * info["height"] / max(1, info["width"]) / 2) * 2)
        duration = max(0.5, float(info.get("duration") or 5.0))
        raw = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(video_path), "-an",
             "-vf", f"fps={samples / duration:.4f},scale={width}:{height},format=gray",
             "-f", "rawvideo", "-"],
            capture_output=True, timeout=120,
        ).stdout
    except Exception as exc:  # noqa: BLE001 — a helper for one axis
        logger.info("Product exposure not measured: %s", exc)
        return None
    count = len(raw) // (width * height)
    frames = np.frombuffer(raw[: count * width * height], dtype=np.uint8).reshape(count, height, width)
    rows = []
    for frame in frames:
        found = matcher.find(frame)
        if not found.seen:
            continue
        pixels = frame[product_region.mask_for(found.polygon, frame.shape)]
        if pixels.size < 400:
            continue
        rows.append({
            "p5": float(np.percentile(pixels, 5)),
            "p50": float(np.percentile(pixels, 50)),
            "p95": float(np.percentile(pixels, 95)),
            "clip_hi": float((pixels >= 250).mean()),
            "area": float(pixels.size) / (width * height),
        })
    if len(rows) < max(2, len(frames) * 0.4):
        return None
    median = lambda key: float(np.median([r[key] for r in rows]))  # noqa: E731
    p50 = median("p50")
    return {
        "frames_seen": len(rows), "frames": len(frames),
        "p5": round(median("p5"), 1), "p50": round(p50, 1),
        "p95": round(median("p95"), 1), "clip_hi": round(median("clip_hi"), 4),
        "area": round(median("area"), 4),
        "photo_p50": None if matcher.photo_p50 is None else round(matcher.photo_p50, 1),
        "ratio": None if not matcher.photo_p50 else round(p50 / matcher.photo_p50, 2),
    }


#: "Same product" without the vision model: the product's colour, compared
#: with its photo region by region (median chroma distance in Lab), and its
#: outline's proportions over the clip. Measured on a lamp under a panning
#: camera: unchanged 1.4; hue turned 60° halfway, worst stretch 45; squashed to
#: 70 % width halfway, proportions −30 %.
PRODUCT_COLOUR_WARN = 10.0
PRODUCT_COLOUR_BAD = 15.0
PRODUCT_SHAPE_BAD = 0.2
PRODUCT_CONSISTENCY_AXIS = "ثبات محصول (بدون بینایی)"


def product_consistency(video_path, product_image_path, *, samples: int = 8) -> dict | None:
    """Colour and proportions of the product through the clip, vs its photo.

    For when the vision model is not there to answer "is it still the same
    product" (no GPU, or vision off). None when the product cannot be found
    in enough frames — then there is nothing to say, not a verdict of "fine".
    """
    import subprocess

    import cv2
    import numpy as np

    from services.video import product_region
    from services.video.ffmpeg import FFMPEG, probe_video

    try:
        matcher = product_region.Matcher(product_image_path)
        info = probe_video(video_path)
        width = 640
        height = int(round(width * info["height"] / max(1, info["width"]) / 2) * 2)
        duration = max(0.5, float(info.get("duration") or 5.0))
        raw = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(video_path), "-an",
             "-vf", f"fps={samples / duration:.4f},scale={width}:{height}",
             "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
            capture_output=True, timeout=120,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        logger.info("Product consistency not measured: %s", exc)
        return None
    size = width * height * 3
    frames = np.frombuffer(raw[: len(raw) // size * size], dtype=np.uint8).reshape(-1, height, width, 3)
    colours, aspects = [], []
    for frame in frames:
        found = matcher.find(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        if not found.seen:
            continue
        distance = product_region.colour_distance(matcher, frame, found)
        ratio = product_region.aspect(found)
        if distance is not None:
            colours.append(distance)
        if ratio is not None:
            aspects.append(ratio)
    if len(colours) < max(3, len(frames) * 0.4):
        return None
    # The worst stretch, not the average: a product that turns blue for the
    # last second is a changed product even if it was right for four.
    tail = sorted(colours)[-max(2, len(colours) // 3):]
    # Proportions relative to the clip's own first sighting (the outline is
    # in frame fractions, so only ratios between frames are meaningful).
    shape_drift = max(abs(a / aspects[0] - 1) for a in aspects) if aspects else 0.0
    return {
        "frames_seen": len(colours), "frames": len(frames),
        "colour_median": round(float(np.median(colours)), 1),
        "colour_worst": round(float(np.median(tail)), 1),
        "shape_drift": round(shape_drift, 2),
    }


def consistency_axis(consistency: dict | None) -> tuple[Axis | None, list[str]]:
    """The code-only "same product" axis, and a regeneration cause if needed."""
    if not consistency:
        return None, []
    colour = consistency["colour_worst"]
    drift = consistency["shape_drift"]
    if colour >= PRODUCT_COLOUR_BAD or drift >= PRODUCT_SHAPE_BAD:
        parts = []
        if colour >= PRODUCT_COLOUR_BAD:
            parts.append("رنگ محصول با عکسش فرق کرده")
        if drift >= PRODUCT_SHAPE_BAD:
            parts.append(f"تناسب محصول در طول کلیپ {drift * 100:.0f}٪ عوض شده")
        return Axis(PRODUCT_CONSISTENCY_AXIS, 45.0, "، ".join(parts)), ["OBJECT_CONSISTENCY"]
    if colour >= PRODUCT_COLOUR_WARN:
        return Axis(PRODUCT_CONSISTENCY_AXIS, 75.0, "رنگ محصول کمی با عکسش فرق دارد"), []
    return Axis(PRODUCT_CONSISTENCY_AXIS, 97.0, ""), []


def _product_verdict(product: dict | None) -> str | None:
    """'lit', 'dark', 'rerender', 'burnt' or None (not measurable / ordinary)."""
    if not product:
        return None
    ratio = product.get("ratio")
    # "Invisible" only when the photo does not explain it: a black matte
    # product can have its brightest 5 % under 60 in a perfect shot.
    if product["p95"] < PRODUCT_INVISIBLE_P95 and (ratio is None or ratio < 0.8):
        return "rerender"
    if product["clip_hi"] > PRODUCT_BURNT_CLIP:
        return "burnt"
    if ratio is None:
        return None
    if ratio < PRODUCT_RERENDER_RATIO:
        return "rerender"
    if ratio < PRODUCT_DARK_RATIO:
        return "dark"
    if PRODUCT_LIT_RATIO[0] <= ratio <= PRODUCT_LIT_RATIO[1] and product["clip_hi"] < PRODUCT_CLIP:
        return "lit"
    return None


def exposure_state(stats: dict) -> str | None:
    """'black', 'dark', 'blown' or None — robust to white and black backgrounds.

    A product on white: p5 is the product's own shadows, well below 120, so it
    is not "blown" however much of the frame is pure white. A product on black:
    p95 is the product's highlights, well above 100, so it is not "dark".
    """
    if stats["p95"] < BLACK_P95:
        return "black"
    if stats["p95"] < DARK_P95 and stats["p50"] < DARK_P50:
        return "dark"
    if stats["clip_hi"] > BLOWN_CLIP and stats["p5"] > BLOWN_P5:
        return "blown"
    return None


def neutral_cast(image, *, max_sat: float = 0.30, min_share: float = 0.25) -> dict | None:
    """Colour lean measured on near-grey pixels only.

    Returns {"rb": R−B, "rg": R−G, "share": fraction of neutral pixels} or
    None when the frame has no neutral surface to judge from — a coloured
    product filling the frame is not a cast, and must not be "corrected".
    """
    small = image.convert("RGB").resize((64, 64))
    pixels = small.getdata()
    picked = []
    for r, g, b in pixels:
        top = max(r, g, b)
        if top < 40 or top > 235:
            continue
        if (top - min(r, g, b)) / top < max_sat:
            picked.append((r, g, b))
    share = len(picked) / max(1, len(pixels))
    if share < min_share:
        return None
    n = len(picked)
    r = sum(p[0] for p in picked) / n
    g = sum(p[1] for p in picked) / n
    b = sum(p[2] for p in picked) / n
    return {"rb": r - b, "rg": r - g, "share": share, "rgb": (r, g, b)}


def sharpness(image) -> float | None:
    """Laplacian variance of the grey frame — higher is sharper. None without
    OpenCV. Recorded for calibration; not scored until phase 0.5 says where
    "soft" begins for this video model."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    grey = np.asarray(image.convert("L"), dtype=np.uint8)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass
class CodeFindings:
    axes: list[Axis] = field(default_factory=list)
    code_fixable: list[str] = field(default_factory=list)
    regenerate: list[str] = field(default_factory=list)
    measurements: dict = field(default_factory=dict)


def analyze_frames(frames: list[Path], stats: dict | None = None,
                   product: dict | None = None) -> CodeFindings:
    """Everything measurable from pixels alone.

    `stats` is `frame_stats.measure(...)` when it could be taken: it carries the
    consecutive-frame facts (flicker, freezes, jumps, black runs). Without it
    the sampled frames are all there is, and the temporal axes fall back to
    the coarse comparison with a note saying so.
    """
    from PIL import Image

    found = CodeFindings()
    stats = stats or {}

    if len(frames) < 2:
        found.axes.append(Axis("پایداری تصویر", 50.0, "فریم کافی برای بررسی استخراج نشد"))
        return found

    images = []
    for path in frames:
        try:
            images.append(Image.open(path).copy())
        except Exception as exc:  # noqa: BLE001 — a bad frame is data, not a crash
            logger.debug("QC could not open %s: %s", path, exc)
    if len(images) < 2:
        found.axes.append(Axis("پایداری تصویر", 50.0, "فریم‌ها خوانده نشدند"))
        return found

    per_frame = [luma_stats(im) for im in images]
    p5 = _median([s["p5"] for s in per_frame])
    p50 = _median([s["p50"] for s in per_frame])
    p95 = _median([s["p95"] for s in per_frame])
    clip_hi = sum(s["clip_hi"] for s in per_frame) / len(per_frame)
    clip_lo = sum(s["clip_lo"] for s in per_frame) / len(per_frame)
    mean_luma = sum(s["mean"] for s in per_frame) / len(per_frame)
    aggregate = {"p5": p5, "p50": p50, "p95": p95, "clip_hi": clip_hi, "clip_lo": clip_lo}

    casts = [neutral_cast(im) for im in images]
    measurable = [c for c in casts if c is not None]
    cast_ok = len(measurable) >= max(2, len(images) // 2)
    cast_rb = sum(c["rb"] for c in measurable) / len(measurable) if cast_ok else None
    cast_drift = (
        max(c["rb"] for c in measurable) - min(c["rb"] for c in measurable) if cast_ok else 0.0
    )
    neutral_rgb = (
        [round(sum(c["rgb"][i] for c in measurable) / len(measurable), 1) for i in range(3)]
        if cast_ok else None
    )

    sharp = [s for s in (sharpness(im) for im in images) if s is not None]

    fps = float(stats.get("fps") or 0.0)
    measurements = {
        "frames_sampled": len(images),
        "p5": round(p5, 1), "p50": round(p50, 1), "p95": round(p95, 1),
        "mean_luma": round(mean_luma, 1),
        "clip_hi": round(clip_hi, 4), "clip_lo": round(clip_lo, 4),
        "cast_measurable": cast_ok,
        "cast_rb": round(cast_rb, 1) if cast_rb is not None else None,
        "cast_drift": round(cast_drift, 1),
        # Mean colour of the neutral pixels — what the colour repair aims at
        # grey, leaving every saturated (product) pixel proportionally alone.
        "neutral_rgb": neutral_rgb,
        "sharpness": round(_median(sharp), 1) if sharp else None,
        "fps": fps or None,
        "width": stats.get("width"), "height": stats.get("height"),
        "consecutive_stats": bool(stats),
    }
    for key in ("flicker", "flicker_alternations", "frozen_share", "longest_freeze",
                "motion_jumps", "black_seconds", "black_share", "mean_ydif", "max_ydif"):
        if key in stats:
            measurements[key] = stats[key]

    # ---- flicker: brightness stepping between NEIGHBOURING frames
    if stats:
        step = float(stats.get("flicker") or 0.0)
        alternations = int(stats.get("flicker_alternations") or 0)
        flickers = step > FLICKER_DELTA and (alternations >= 2 or step > 2 * FLICKER_DELTA)
        score = max(0.0, 100.0 - (step / FLICKER_DELTA) * 45.0) if flickers else 100.0
        note = f"پرش نور بین فریم‌های پشت‌سرهم ({step:.0f} از ۲۵۵، {alternations} بار)" if flickers else ""
    else:
        lumas = [s["mean"] for s in per_frame]
        deltas = [abs(b - a) for a, b in zip(lumas, lumas[1:])]
        step = max(deltas) if deltas else 0.0
        flickers = step > FALLBACK_FLICKER_DELTA
        score = max(0.0, 100.0 - (step / FALLBACK_FLICKER_DELTA) * 45.0) if flickers else 100.0
        note = f"پرش روشنایی بین نمونه‌ها ({step:.0f} از ۲۵۵)" if flickers else ""
    if flickers:
        found.code_fixable.append("FLICKER")
    found.axes.append(Axis("پیوستگی زمانی", min(100.0, score), note))

    # ---- motion: frozen stretches and jump cuts. Neither is a filter's job.
    motion = 100.0
    motion_note = ""
    if stats:
        frozen_share = float(stats.get("frozen_share") or 0.0)
        longest = float(stats.get("longest_freeze") or 0.0)
        jumps = int(stats.get("motion_jumps") or 0)
        if frozen_share > FROZEN_SHARE or longest >= FROZEN_SINGLE:
            motion = max(20.0, 100.0 - frozen_share * 120.0 - (20.0 if longest >= FROZEN_SINGLE else 0.0))
            motion_note = (
                f"کلیپ {longest:.1f} ثانیه بی‌حرکت می‌ماند" if longest >= FROZEN_SINGLE
                else f"حدود {frozen_share * 100:.0f}٪ کلیپ حرکتی ندارد"
            )
            found.regenerate.append(FROZEN)
        if jumps:
            motion = min(motion, 62.0)
            motion_note = (motion_note + " · " if motion_note else "") + "پرش ناگهانی صحنه"
            found.regenerate.append(MOTION_JUMP)
    else:
        diffs = [_mean_abs_diff(a, b) for a, b in zip(images, images[1:])]
        frozen = sum(1 for d in diffs if d < FALLBACK_FROZEN_DIFF)
        frozen_ratio = frozen / len(diffs)
        if frozen_ratio > FROZEN_SHARE:
            motion = max(0.0, 100.0 - frozen_ratio * 120.0)
            motion_note = f"حدود {frozen_ratio * 100:.0f}٪ کلیپ حرکتی ندارد"
            found.regenerate.append(FROZEN)
        elif max(diffs) > 90:
            motion = min(motion, 62.0)
            motion_note = "پرش ناگهانی صحنه بین دو فریم"
            found.regenerate.append(MOTION_JUMP)
    found.axes.append(Axis("کیفیت حرکت", min(100.0, motion), motion_note))

    # ---- exposure: percentiles, not the mean
    state = exposure_state(aggregate)
    exposure = 100.0
    exposure_note = ""
    black_run = float(stats.get("black_seconds") or 0.0) if stats else 0.0
    if state == "black":
        exposure = 10.0
        exposure_note = "تصویر تقریباً سیاه است"
        found.regenerate.append(BLACK)
    elif black_run >= 0.3:
        exposure = 35.0
        exposure_note = f"{black_run:.1f} ثانیه از کلیپ سیاه است"
        found.regenerate.append(BLACK)
    else:
        # The frame is judged first; the PRODUCT, when it can be found, has
        # the last word — it is what the video is selling. A dark frame whose
        # product is well lit is a moody shot, and brightening it would wash
        # the product out; a normal frame whose product is murky is not fine.
        verdict = _product_verdict(product)
        product_lit = verdict == "lit"
        if state == "dark" and product_lit:
            exposure = 92.0
            exposure_note = "پس‌زمینه تاریک است، ولی خود محصول خوب نور دارد"
        elif state == "dark":
            exposure = 62.0
            exposure_note = f"تصویر تاریک است (روشن‌ترین بخش‌ها {p95:.0f} از ۲۵۵)"
            found.code_fixable.append("EXPOSURE")
        elif state == "blown" and product_lit:
            exposure = 90.0
            exposure_note = "پس‌زمینه خیلی روشن است، ولی خود محصول سوخته نیست"
        elif state == "blown":
            exposure = 65.0
            exposure_note = f"تصویر سوخته است ({clip_hi * 100:.0f}٪ پیکسل‌ها کاملاً سفید)"
            found.code_fixable.append("EXPOSURE")
        elif verdict in ("dark", "rerender"):
            exposure = 55.0 if verdict == "rerender" else 66.0
            ratio = product.get("ratio")
            exposure_note = (
                "خود محصول تاریک است"
                + (f" ({ratio * 100:.0f}٪ روشنیِ عکس خود محصول)" if ratio else "")
                + "، هرچند کل تصویر روشن است"
            )
            if verdict == "rerender":
                found.regenerate.append(DARK)
        elif verdict == "burnt":
            exposure = 70.0
            exposure_note = (
                f"جزئیات روشن خود محصول سوخته است ({product['clip_hi'] * 100:.0f}٪ کاملاً سفید)"
            )
    found.axes.append(Axis("نوردهی", exposure, exposure_note))

    # ---- colour: a lean on the neutrals, and whether it wanders
    colour = 100.0
    colour_note = ""
    if cast_ok:
        if abs(cast_rb) > CAST_DELTA:
            colour = max(0.0, 100.0 - (abs(cast_rb) / CAST_DELTA) * 30.0)
            colour_note = "رنگ صحنه به گرمی زده" if cast_rb > 0 else "رنگ صحنه به سردی زده"
            found.code_fixable.append("COLOR")
        if cast_drift > CAST_DRIFT:
            colour = min(colour, 60.0)
            colour_note = (colour_note + " · " if colour_note else "") + (
                f"رنگ صحنه از اول تا آخر عوض شده ({cast_drift:.0f})"
            )
            found.regenerate.append(COLOUR_DRIFT)
    found.axes.append(Axis("ثبات رنگ", min(100.0, colour), colour_note))

    if product:
        measurements["product"] = product
    found.measurements = measurements
    return found


def code_axes(frames: list[Path], stats: dict | None = None) -> tuple[list[Axis], list[str]]:
    """Compatibility wrapper: (axes, code_fixable). Prefer `analyze_frames`."""
    found = analyze_frames(frames, stats)
    return found.axes, found.code_fixable


# ---------------------------------------------------------- vision layer

VISION_PROMPT_ID = "video_segment_qc"
VISION_PROMPT_VERSION = "2"

#: "unsure" is a legitimate answer — a frame where the product is out of shot,
#: a hand half hidden — and it lands in the REVIEW band rather than passing.
_VERDICT_SCORE = {"ok": 100.0, "minor": 75.0, "unsure": 75.0, "severe": 35.0}


def _vision_prompt(has_product_reference: bool, scene_note: str) -> str:
    reference = (
        "The FIRST image is the customer's real product photo. The rest are "
        "frames from a generated video, in order from start to end.\n"
        "object_consistency must judge whether the product in the video is "
        "still THAT product — same shape, colour, logo and proportions. This is "
        "the single most important check: the customer is selling this exact "
        "item.\n"
        if has_product_reference
        else "The images are frames from a generated video, in order from start to end.\n"
    )
    scene = f"\nThe scene was supposed to be: {scene_note}\n" if scene_note else ""
    return (
        reference
        + scene
        + "\nJudge each check by comparing the frames with each other"
        + (" and with the product photo" if has_product_reference else "")
        + ". Answer each with a verdict — \"ok\" (no problem), \"minor\" (a "
        "viewer might notice), \"severe\" (clearly wrong; the clip cannot be "
        "used), or \"unsure\" (you cannot tell from these frames) — and a short "
        "note saying what you saw and in which frame:\n"
        "- character_consistency: is the same person present throughout? Any "
        "face change, clothing change or deformation? \"ok\" if there is no "
        "person at all.\n"
        "- object_consistency: does the product keep the same shape, colour and "
        "size? Does it vanish, duplicate or turn into something else? \"ok\" if "
        "there is no product in the frames.\n"
        "- anatomy: hands, fingers, limbs. Extra fingers, fused hands, "
        "impossible joints. \"ok\" if no body parts are visible.\n"
        "- artifacts: morphing, warping, smearing, ghosting, garbage text.\n"
        "\nAlso report what you actually see, so the next clip can match it:\n"
        "- observed.product_colours: up to 3 colour words for the product\n"
        "- observed.clothing: up to 3 short items, empty if nobody is there\n"
        "- observed.background: up to 8 words\n"
        "- observed.people: how many people are visible (a number)\n"
        "\nReply with a single JSON object, nothing else:\n"
        '{"character_consistency": {"verdict": "ok|minor|severe", "note": "..."}, '
        '"object_consistency": {"verdict": "...", "note": "..."}, '
        '"anatomy": {"verdict": "...", "note": "..."}, '
        '"artifacts": {"verdict": "...", "note": "..."}, '
        '"observed": {"product_colours": [], "clothing": [], "background": "", "people": 0}, '
        '"notes": "<one short Persian sentence naming the worst problem, or empty>"}'
    )


def validate_vision(parsed) -> tuple[bool, list[str]]:
    """The QC answer has to carry a verdict per check, or it is not a QC answer.

    Accepts the categorical form above and, for older prompts and fakes, a
    bare 0–100 number per key. Either way `parsed[key]` is normalised to a
    number and the per-check notes are collected under `parsed["evidence"]`.
    """
    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    problems = []
    evidence = {}
    for key in VISION_LABELS:
        value = parsed.get(key)
        if isinstance(value, dict):
            verdict = str(value.get("verdict", "")).strip().lower()
            if verdict in _VERDICT_SCORE:
                parsed[key] = _VERDICT_SCORE[verdict]
                evidence[key] = str(value.get("note", "") or "")[:200]
                continue
            try:
                number = float(value.get("score"))
            except (TypeError, ValueError):
                problems.append(key)
                continue
            parsed[key] = max(0.0, min(100.0, number))
            evidence[key] = str(value.get("note", "") or "")[:200]
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            problems.append(key)
            continue
        parsed[key] = max(0.0, min(100.0, number))
    parsed["evidence"] = evidence
    parsed.setdefault("notes", "")
    observed = parsed.get("observed")
    parsed["observed"] = _clean_observed(observed if isinstance(observed, dict) else {})
    return (not problems), problems


def _clean_observed(raw: dict) -> dict:
    """Trim the model's observations to a size a prompt can carry."""
    def words(value, limit):
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            text = str(item).strip()[:40]
            if text and text not in out:
                out.append(text)
        return out[:limit]

    try:
        people = int(raw.get("people", 0) or 0)
    except (TypeError, ValueError):
        people = 0
    return {
        "product_colours": words(raw.get("product_colours"), 3),
        "clothing": words(raw.get("clothing"), 3),
        "background": " ".join(str(raw.get("background", "") or "").split()[:8]),
        "people": max(0, people),
    }


@dataclass
class VisionResult:
    axes: list[Axis] = field(default_factory=list)
    regenerate: list[str] = field(default_factory=list)
    checked: bool = False
    reason: str = ""
    observed: dict = field(default_factory=dict)


def _vision_frames(video_path, work_dir) -> list[Path]:
    """The frames the model sees: spread over the clip and legible."""
    frames = sample_frames(
        video_path, Path(work_dir) / "vision", VISION_FRAMES, width=VISION_WIDTH, prefix="vq",
    )
    return frames


def _encode(path: Path) -> str:
    import base64

    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _encode_reference(path: Path, width: int = VISION_WIDTH) -> str:
    """The product photo, downscaled to the same size as the frames so the
    model compares like with like (and the request stays small)."""
    import base64
    import io

    from PIL import Image

    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.width > width:
                im = im.resize((width, max(1, int(im.height * width / im.width))))
            buffer = io.BytesIO()
            im.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — send it as-is rather than not at all
        return _encode(path)


def vision_axes(
    frames: list[Path],
    *,
    store,
    product_image_path: Path | None = None,
    scene_note: str = "",
    job=None,
) -> VisionResult:
    """Ask the vision model the questions pixels cannot answer.

    `checked` is False when the model could not be reached or the store's data
    policy forbids it — and the caller must treat that as "nobody looked",
    never as "it passed". `reason` says which.
    """
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from services.ai import gateway
    from services.ai.router import TASK_VISION, models_for

    result = VisionResult()
    if not frames:
        result.reason = "فریمی برای مدل بینایی نبود"
        return result

    encoded = []
    if product_image_path and Path(product_image_path).exists():
        encoded.append(_encode_reference(Path(product_image_path)))
    for path in frames[:VISION_FRAMES]:
        encoded.append(_encode(path))

    try:
        provider = gateway.vision_provider(store)
        parsed, _row = recorded_json_call(
            job=job,
            store=store,
            task_type=AIRequest.TaskType.VISION,
            prompt_id=VISION_PROMPT_ID,
            prompt_version=VISION_PROMPT_VERSION,
            provider=provider,
            models=models_for(TASK_VISION),
            prompt=_vision_prompt(bool(product_image_path), scene_note),
            images=encoded,
            validate=validate_vision,
            validation_message="بررسی کیفیت نتیجه‌ی معتبری برنگرداند",
        )
    except Exception as exc:  # noqa: BLE001 — QC must never break a good render
        logger.info("Vision QC unavailable: %s", exc)
        result.reason = str(exc)[:200] or "مدل بینایی در دسترس نبود"
        return result

    note = str(parsed.get("notes", "") or "")
    evidence = parsed.get("evidence") or {}
    for key, label in VISION_LABELS.items():
        score = float(parsed.get(key, 100.0))
        detail = evidence.get(key) or note
        result.axes.append(Axis(label, score, detail if score < 80 else ""))
        if score < 70:
            result.regenerate.append(key.upper())
    result.checked = True
    result.observed = parsed.get("observed") or {}
    return result


# ----------------------------------------------------------------- score

#: How far the overall score may sit above its worst axis.
#:
#: A weighted mean alone is the wrong instrument for a quality gate, and the
#: test that caught it is worth keeping in mind: a nearly-black clip scored
#: **92 — "excellent"** — because three healthy axes outvoted one catastrophic
#: one. The same arithmetic would have shipped a clip of the *wrong product*
#: with a score of 85.
#:
#: Quality is closer to a minimum than an average: one thing being badly wrong
#: is enough. A pure minimum is too harsh (a single slightly-low axis would tank
#: an otherwise fine clip), so the overall is allowed this much headroom above
#: the worst and no more.
WORST_AXIS_HEADROOM = 15.0

#: Weights. Object consistency is heaviest on purpose: a beautiful clip of the
#: wrong product is worthless to a shop, while a slightly dark clip of the
#: right one is a colour curve away from fine.
#: The mouth-movement axis (services.video.mouth). Only added for a voice-over
#: scene with a readable face; talking there is a REGENERATE, not a filter.
MOUTH_AXIS = "لب ساکن"

WEIGHTS = {
    "ثبات محصول": 2.0,
    "ثبات محصول (بدون بینایی)": 1.5,
    MOUTH_AXIS: 1.2,
    "ثبات شخصیت": 1.5,
    "آناتومی": 1.3,
    "نبود خرابی تصویری": 1.2,
    "پیوستگی زمانی": 1.0,
    "کیفیت حرکت": 1.0,
    "نوردهی": 0.7,
    "ثبات رنگ": 0.6,
}


def thresholds() -> dict:
    """Verdict boundaries. Example numbers until phase 0.5 calibrates them."""
    from django.conf import settings

    conf = settings.UPMARKET_AI
    return {
        "excellent": float(conf.get("QC_EXCELLENT", 90)),
        "good": float(conf.get("QC_GOOD", 80)),
        "review": float(conf.get("QC_REVIEW", 70)),
    }


def combine(axes: list[Axis]) -> float:
    """Overall score from the axes — a weighted mean, capped by the worst one.

    See WORST_AXIS_HEADROOM for why the cap exists.
    """
    if not axes:
        return 0.0
    total_weight = sum(WEIGHTS.get(a.name, 1.0) for a in axes) or 1.0
    mean = sum(a.score * WEIGHTS.get(a.name, 1.0) for a in axes) / total_weight
    worst = min(a.score for a in axes)
    return max(0.0, min(mean, worst + WORST_AXIS_HEADROOM))


def verdict_for(score: float) -> str:
    limits = thresholds()
    if score >= limits["excellent"]:
        return "EXCELLENT"
    if score >= limits["good"]:
        return "GOOD"
    if score >= limits["review"]:
        return "REVIEW"
    return "REGENERATE"


def check_segment(
    video_path,
    work_dir,
    *,
    store,
    product_image_path=None,
    scene_note: str = "",
    job=None,
    use_vision: bool = True,
    reuse_vision: QCReport | None = None,
    mouth_check: bool = False,
) -> QCReport:
    """Full report for one rendered segment.

    Never raises. A QC engine that can break a render is worse than no QC
    engine: the segment already exists and already cost GPU minutes.

    `reuse_vision` is for the re-check after a code repair: a colour curve
    cannot change whose face it is, so the vision verdicts from the first pass
    are carried over instead of being paid for twice — and instead of being
    silently dropped, which used to turn a 77 into a 100.

    `mouth_check` is for a voice-over scene with people in it: a person
    whose lips move is "talking" with the narrator's voice, and that is a
    re-render (cause TALKING), not something a filter can fix.
    """
    report = QCReport()
    work = Path(work_dir) / "qc"
    try:
        stats = frame_stats.measure(video_path, work)
        frames = sample_frames(video_path, work, SAMPLE_FRAMES, width=SAMPLE_WIDTH)
        if not frames:
            report.error = "فریمی برای بررسی استخراج نشد"
            report.overall = 50.0
            report.verdict = "REVIEW"
            return report

        product = product_exposure(video_path, product_image_path) if product_image_path else None
        found = analyze_frames(frames, stats, product)
        axes = list(found.axes)
        regenerate = list(found.regenerate)
        report.measurements = found.measurements

        if mouth_check:
            from services.video import mouth

            lips = mouth.check(video_path, work)
            report.measurements["mouth"] = {
                k: lips.get(k) for k in ("looked", "talking", "contrast", "rhythm", "amplitude", "reason")
            }
            # No readable face is "could not check", never a penalty.
            if lips.get("looked"):
                axes.append(Axis(MOUTH_AXIS, float(lips["score"]), lips.get("reason", "")))
                if lips.get("talking"):
                    regenerate.append("TALKING")

        vision_frames: list[Path] = []
        if use_vision:
            vision_frames = _vision_frames(video_path, work)
            seen = vision_axes(
                vision_frames, store=store, product_image_path=product_image_path,
                scene_note=scene_note, job=job,
            )
            axes += seen.axes
            regenerate += seen.regenerate
            report.vision_checked = seen.checked
            report.vision_reason = seen.reason
            report.observed = seen.observed
        elif reuse_vision is not None:
            vision_names = set(VISION_LABELS.values())
            axes += [a for a in reuse_vision.axes if a.name in vision_names]
            regenerate += [c for c in reuse_vision.needs_regeneration if c in VISION_CAUSES]
            report.vision_checked = reuse_vision.vision_checked
            report.vision_reason = reuse_vision.vision_reason
            report.observed = dict(reuse_vision.observed)
        else:
            report.vision_reason = "بررسی بینایی خواسته نشد"

        # No vision model (no GPU, vision off, or it failed): whether it is
        # still the same product is measured from the pixels instead — its
        # colour against its photo and its proportions through the clip.
        if not report.vision_checked and product_image_path:
            consistency = product_consistency(video_path, product_image_path)
            axis, causes = consistency_axis(consistency)
            if axis is not None:
                axes.append(axis)
                regenerate += causes
                report.measurements["product_consistency"] = consistency

        report.overall = combine(axes)
        report.axes = axes
        report.code_fixable = found.code_fixable
        report.needs_regeneration = list(dict.fromkeys(regenerate))
        report.verdict = verdict_for(report.overall)

        # Cleanup: the frames were a means, not an artefact worth keeping.
        for frame in [*frames, *vision_frames]:
            try:
                frame.unlink()
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("QC failed for %s", video_path)
        report.error = str(exc)[:300]
        report.overall = 50.0
        report.verdict = "REVIEW"
    return report
