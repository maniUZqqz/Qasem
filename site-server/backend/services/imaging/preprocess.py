"""
Clean up a store owner's product photo before it is handed to the diffusion
model.

img2img inherits the input's flaws: a small, soft, badly-exposed phone photo
comes back as a big, soft, badly-exposed poster (beter.md v2 #4). Upscaling
and normalising the source first gives the sampler real detail to work with,
which is worth far more than any wording in the prompt.

Everything here is deterministic image processing (Pillow only) — no model,
no network, no extra VRAM.
"""

import logging
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

# Below this, a photo is genuinely low-res and needs the most help.
LOW_RES_PIXELS = 700 * 700

JPEG_QUALITY = 96


def _cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale to fully cover width x height, then centre-crop to exactly that."""
    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        return image
    scale = max(width / src_w, height / src_h)
    new_size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    resized = image.resize(new_size, Image.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def prepare_source_image(source_path, out_path, width: int, height: int) -> Path:
    """Write an upscaled, tidied copy of `source_path` sized for the workflow.

    Returns the path actually written; on any failure the original path is
    returned unchanged, because a rough source image is still better than a
    failed job.
    """
    source_path, out_path = Path(source_path), Path(out_path)
    try:
        with Image.open(source_path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            original_pixels = image.width * image.height

            # even exposure and colour before anything is scaled up
            image = ImageOps.autocontrast(image, cutoff=1)

            image = _cover_resize(image, width, height)

            # LANCZOS upscaling softens edges; restore them. A photo that was
            # tiny to begin with needs a firmer hand than one that was already
            # bigger than the target.
            weak = original_pixels < LOW_RES_PIXELS
            image = image.filter(
                ImageFilter.UnsharpMask(
                    radius=2 if weak else 1.4,
                    percent=140 if weak else 90,
                    threshold=3,
                )
            )
            if weak:
                image = ImageEnhance.Color(image).enhance(1.06)

            out_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path, format="PNG", optimize=True)
        logger.info(
            "Prepared source image %s -> %s (%sx%s)", source_path.name, out_path.name, width, height
        )
        return out_path
    except Exception as exc:  # noqa: BLE001 — never fail a job over preprocessing
        logger.warning("Source image preprocessing failed for %s: %s", source_path, exc)
        return source_path
