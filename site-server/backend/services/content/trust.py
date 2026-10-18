"""The real photo at the end. §26, and §1 of the poster section.

§26 asks for something small and unusually important: after all the generated
footage, put a **real** photo — the shop owner, or the untouched product — at
the end. «پوستر برای جذب، عکس واقعی برای اعتماد.»

**The one rule that makes this work: the photo must not be generated.** A
`GeneratedImage` is disqualified here no matter how real it looks, including the
`ENHANCED` kind that started from the shop's own photo. The whole value of this
feature is the viewer's belief that this part was not made up, and the first
time we append something AI touched, the feature has become the opposite of
itself. So `choose` reads only from uploaded sources and refuses rather than
substituting.

**And when there is no real photo, the answer is "no", not "something".** A
shop with nothing uploaded gets a clear ask for one — not a stock image, not the
logo, not a generated stand-in.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from services.video.ffmpeg import (
    FFMPEG, VIDEO_DELIVERY, VideoProcessingError, _run, probe_duration,
)

logger = logging.getLogger(__name__)

#: How long the card holds. Long enough to read a name, short enough that it is
#: not the part of the video people remember.
HOLD_SECONDS = 2.5

#: The fade into it. Cutting hard from motion to a still reads as a glitch.
FADE_SECONDS = 0.4


@dataclass
class RealPhoto:
    """A photo we are willing to stand behind as real.

    `path` is a real file on disk, because the next thing to touch it is
    ffmpeg. When storage is remote it is a temporary download, and `opened`
    holds it until `close()` — so this is used through `open_real_photo`, not
    constructed and forgotten.
    """

    path: Path
    caption: str
    #: "owner" or "product" — the panel words the two differently, and a shop
    #: should know which one it is about to publish.
    kind: str
    opened: contextlib.ExitStack | None = field(default=None, repr=False)

    def close(self) -> None:
        if self.opened is not None:
            self.opened.close()
            self.opened = None

    def as_dict(self) -> dict:
        # No path. This goes to the panel, and a temp filename on our disk is
        # not something a customer's browser has any use for.
        return {"caption": self.caption, "kind": self.kind}


class NoRealPhoto(Exception):
    """Nothing uploaded that we can honestly call real. Always says what to do."""


def choose(store, product=None, *, prefer: str = "owner") -> RealPhoto:
    """The real photo to close with, or a refusal naming what is missing.

    Never falls back to a generated image. Reading from `GeneratedImage` here —
    even the `ENHANCED` kind that began as the shop's own photo — would turn the
    one honest frame in the video into another made-up one.
    """
    owner = _owner_photo(store)
    real_product = _product_photo(product)

    order = [owner, real_product] if prefer == "owner" else [real_product, owner]
    for candidate in order:
        if candidate is not None:
            return candidate

    raise NoRealPhoto(
        "برای این کار یک عکس واقعی لازم است — یا عکس خودتان در تنظیمات فروشگاه، "
        "یا یک عکس واقعی از محصول. عکس‌هایی که AI ساخته اینجا به کار نمی‌آید، "
        "چون کل فایده‌ی این بخش این است که بیننده بداند این یکی واقعی است."
    )


def _owner_photo(store) -> RealPhoto | None:
    try:
        profile = store.profile
    except Exception:  # noqa: BLE001 — no profile row yet
        return None
    photo = getattr(profile, "owner_photo", None)
    if not photo:
        return None
    opened = _materialise(photo)
    if opened is None:
        return None
    stack, path = opened
    return RealPhoto(
        path=path,
        caption=(profile.owner_caption or store.name)[:120],
        kind="owner",
        opened=stack,
    )


def _product_photo(product) -> RealPhoto | None:
    """The shop's own upload of the product, never a generated one."""
    if product is None:
        return None
    image = (
        product.images.filter(is_main=True).first()
        or product.images.order_by("order", "id").first()
    )
    if image is None or not image.image:
        return None
    opened = _materialise(image.image)
    if opened is None:
        return None
    stack, path = opened
    return RealPhoto(
        path=path,
        caption=(image.alt_text or product.name)[:120],
        kind="product",
        opened=stack,
    )


def _materialise(field_file):
    """A real file on disk for something in storage, plus its cleanup.

    Returns None when the row points at a file that is not there. That case
    used to be reached on *every* S3 deployment, because `.path` raises there
    and the `except` swallowed it — so a shop with a perfectly good photo was
    told they had none. A silent "no" is the one answer this module must never
    give by accident.
    """
    from services.media import files as media

    stack = contextlib.ExitStack()
    try:
        path = stack.enter_context(media.reading(field_file))
    except Exception as exc:  # noqa: BLE001 — a missing file is data
        stack.close()
        logger.info("Real photo unavailable (%s): %s", field_file.name, exc)
        return None
    if not Path(path).exists():
        stack.close()
        return None
    return stack, Path(path)


def video_shape(video_path) -> tuple[int, int, str]:
    """(width, height, fps) of a video, for matching a still to it.

    Concatenation is unforgiving: the still has to match the video's resolution,
    frame rate, sample aspect ratio and pixel format exactly, and the failure
    when it does not is a file that plays fine for the shop and is rejected by
    Instagram. So the still is built to these numbers rather than guessed at.
    """
    from services.video.ffmpeg import probe

    info = probe(video_path)
    stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None,
    )
    if stream is None:
        raise VideoProcessingError("این فایل ویدیو ندارد")

    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if not width or not height:
        raise VideoProcessingError("اندازه‌ی ویدیو خوانده نشد")

    rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1")
    try:
        numerator, _, denominator = rate.partition("/")
        fps = float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    return width, height, f"{fps:.4f}".rstrip("0").rstrip(".")


def append_to_video(video_path, photo: RealPhoto, out_path, *,
                    seconds: float = HOLD_SECONDS) -> Path:
    """Hold the real photo at the end of a finished video."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video_path)
    width, height, fps = video_shape(video_path)

    filtergraph = (
        f"[0:v]scale={width}:{height},setsar=1,fps={fps},format=yuv420p[main];"
        # Pad, never crop. Cropping a person's photo to fill a 9:16 frame cuts
        # their head off often enough that padding is the only safe default —
        # and the whole point of this frame is that a person is in it.
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p,"
        f"fade=t=in:st=0:d={FADE_SECONDS}[tail];"
        "[main][tail]concat=n=2:v=1:a=0[v]"
    )

    _run([
        FFMPEG, "-y",
        "-i", str(video_path),
        "-loop", "1", "-t", f"{seconds:.2f}", "-i", str(photo.path),
        "-filter_complex", filtergraph,
        "-map", "[v]",
        # The video's own audio, ending where it ended. A still frame with the
        # narration still talking over it is worse than silence: the sentence is
        # about footage nobody is looking at any more.
        "-map", "0:a?",
        *VIDEO_DELIVERY,
        "-c:a", "copy",
        str(out),
    ])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("عکس واقعی به انتهای ویدیو اضافه نشد")
    logger.info("Appended %s photo to a %.1fs video", photo.kind, duration)
    return out


@contextlib.contextmanager
def open_real_photo(store, product=None, *, prefer: str = "owner"):
    """`choose`, with the temporary file cleaned up afterwards."""
    photo = choose(store, product, prefer=prefer)
    try:
        yield photo
    finally:
        photo.close()


def available(store, product=None) -> dict:
    """What the panel needs to decide whether to offer this at all."""
    try:
        photo = choose(store, product)
    except NoRealPhoto as exc:
        return {"available": False, "reason": str(exc), "photo": None}
    try:
        return {"available": True, "reason": "", "photo": photo.as_dict()}
    finally:
        photo.close()
