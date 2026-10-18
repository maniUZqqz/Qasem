"""B-roll — covering the moments where the main shot has nothing to show. §8

The idea document asks the question this module answers: «اینجا چه تصویر کمکی
بگذاریم؟» — what supporting image goes here.

**It comes from the shop's own pictures, never from stock.** A stock photo of a
generic shoe in a video selling *this* shoe is the single clearest signal that
nobody was paying attention, and it is exactly the "AI slop" impression the rest
of the product works to avoid. So the sources are, in order of preference: the
shop's own product photographs, then the product shots we generated from those
photographs, then posters. All three are pictures of the thing being sold.

**Where B-roll goes is decided by measurement, not by taste.** A cut needs
covering when the picture is doing nothing while the narration is doing
something:

* the camera is static — nothing is moving, so a still image loses nothing
* the speaker is talking through it — there is a reason to keep watching
* it runs long enough to be worth a cut, and not so long that the video
  becomes a slideshow

**And it refuses more often than it accepts.** A video cut to B-roll every four
seconds is a video nobody believes was made by a person. `MAX_SHARE` caps how
much of the runtime can be covered, and the cheapest correct answer is usually
"leave it alone".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Shorter than this and a cut-away is a flicker, not a shot.
MIN_SHOT = 1.5

#: Longer than this and the viewer forgets there was a camera. The narration
#: keeps running underneath, so this is about attention, not information.
MAX_SHOT = 4.0

#: Never cover more than this fraction of the video. Past it the result is a
#: slideshow with a voice-over, which is a different product and a worse one.
MAX_SHARE = 0.35

#: Below this frame-to-frame difference the camera is effectively still, so a
#: held image costs the viewer nothing.
STATIC_MOTION = 4.0

#: Two cuts closer together than this read as a stutter.
MIN_GAP = 2.0


@dataclass
class Shot:
    """One supporting image, and when it covers the main footage."""

    start: float
    end: float
    #: Where the picture came from: "photo", "generated", or "poster".
    source: str
    reference: str = ""
    why: str = ""

    @property
    def seconds(self) -> float:
        return max(0.0, self.end - self.start)

    def as_dict(self) -> dict:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "seconds": round(self.seconds, 2),
            "source": self.source,
            "reference": self.reference,
            "why": self.why,
        }


@dataclass
class Plan:
    shots: list[Shot] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    duration: float = 0.0

    @property
    def covered(self) -> float:
        return sum(s.seconds for s in self.shots)

    @property
    def share(self) -> float:
        return self.covered / self.duration if self.duration else 0.0

    def as_dict(self) -> dict:
        return {
            "shots": [s.as_dict() for s in self.shots],
            "count": len(self.shots),
            "covered_seconds": round(self.covered, 1),
            "share": round(self.share, 3),
            "refusals": self.refusals,
            "summary": (
                f"{len(self.shots)} تصویر کمکی، روی "
                f"{round(self.share * 100)}٪ ویدیو"
                if self.shots else "جایی برای تصویر کمکی پیدا نشد"
            ),
        }


# ------------------------------------------------------------------ sources


def available_images(product) -> list[dict]:
    """Pictures of the thing being sold, best first.

    The shop's own photograph beats anything we generated from it: it is the
    actual object, and a shop looking at their own video recognises it.
    """
    out: list[dict] = []

    for image in product.images.all()[:20]:
        out.append({
            "source": "photo",
            "reference": image.image.name,
            "url": image.image.url if image.image else "",
            "why": "عکس خودِ شما از محصول",
        })

    from apps.content.models import GeneratedImage

    generated = GeneratedImage.objects.filter(product=product).order_by("-created_at")
    for image in generated[:20]:
        kind = image.kind
        out.append({
            "source": "generated" if kind != GeneratedImage.Kind.POSTER else "poster",
            "reference": image.image.name,
            "url": image.image.url if image.image else "",
            "why": {
                GeneratedImage.Kind.PRODUCT_SHOT: "عکس محصول که ساختیم",
                GeneratedImage.Kind.ENHANCED: "عکس بهبودیافته‌ی خودتان",
                GeneratedImage.Kind.POSTER: "پوستر همین محصول",
            }.get(kind, "تصویر تولیدشده"),
        })

    return out


# ------------------------------------------------------------------ placing


def _speaking_spans(facts: dict) -> list[tuple[float, float]]:
    """When somebody is talking, from the silences we already measured."""
    duration = float(facts.get("duration") or 0)
    silences = facts.get("silences") or []
    if not duration:
        return []
    if not silences:
        return [(0.0, duration)]

    spans, cursor = [], 0.0
    for quiet in sorted(silences, key=lambda s: s["start"]):
        start, end = float(quiet["start"]), float(quiet["end"])
        if start > cursor + 0.1:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 0.1:
        spans.append((cursor, duration))
    return spans


def plan(facts: dict, images: list[dict], *, wanted: int | None = None) -> Plan:
    """Where supporting images would help, and where they would not.

    Returns refusals as well as shots, because "we did not put B-roll here"
    is a decision a shop should be able to see the reason for.
    """
    duration = float(facts.get("duration") or 0)
    result = Plan(duration=duration)

    if not images:
        result.refusals.append(
            "هیچ عکسی از این محصول نداریم. اول یک عکس آپلود کنید یا "
            "عکس محصول بسازید."
        )
        return result
    if duration < MIN_SHOT * 3:
        result.refusals.append(
            f"این ویدیو {duration:.0f} ثانیه است — کوتاه‌تر از آن که بریدن "
            "به تصویر کمکی کمکی بکند."
        )
        return result

    motion = float(facts.get("motion") or 0)
    if motion > STATIC_MOTION:
        # A moving camera is already giving the viewer something. Cutting away
        # from it is taking away the one thing that was working.
        result.refusals.append(
            f"دوربین در حرکت است (حرکت {motion:.0f}) — تصویر خودش چیزی برای "
            "دیدن دارد و بریدن از آن، همان چیز را می‌گیرد."
        )
        return result

    speaking = _speaking_spans(facts)
    if not speaking:
        result.refusals.append(
            "کسی در این ویدیو حرف نمی‌زند — تصویر کمکی روی سکوت، فقط سکوت "
            "است با عکس."
        )
        return result

    budget = duration * MAX_SHARE
    limit = wanted if wanted is not None else len(images)
    picked: list[Shot] = []
    used = 0.0
    index = 0

    # Longest speaking stretch first: that is where the picture has been doing
    # nothing for the longest, which is where a cut buys the most.
    for start, end in sorted(speaking, key=lambda s: s[1] - s[0], reverse=True):
        if len(picked) >= limit or used >= budget:
            break
        length = end - start
        if length < MIN_SHOT * 2:
            continue

        # Placed inside the stretch, not at its edges: cutting exactly on the
        # first or last word of a sentence is the cut people notice.
        shot_len = min(MAX_SHOT, max(MIN_SHOT, length / 3))
        if used + shot_len > budget:
            shot_len = budget - used
            if shot_len < MIN_SHOT:
                break
        at = start + (length - shot_len) / 2

        if any(abs(at - s.start) < MIN_GAP for s in picked):
            continue

        image = images[index % len(images)]
        index += 1
        picked.append(Shot(
            start=at, end=at + shot_len,
            source=image["source"], reference=image["reference"],
            why=(
                f"{image['why']} — {length:.0f} ثانیه حرف زده می‌شود و تصویر "
                "ثابت است"
            ),
        ))
        used += shot_len

    picked.sort(key=lambda s: s.start)
    result.shots = picked

    if not picked:
        result.refusals.append(
            "جای مناسبی پیدا نشد — هر بخشِ حرف‌زدن کوتاه‌تر از آن است که "
            "بریدن به آن بیارزد."
        )
    return result


# ----------------------------------------------------------------- filters


def overlay_filters(shots: list[Shot], image_paths: dict) -> list[str]:
    """ffmpeg overlays that hold each picture over the footage for its window.

    Full-frame rather than a corner inset: a small picture-in-picture on a
    portrait phone video is too small to read, and the point is to show the
    product, not to decorate the frame.
    """
    filters = []
    for index, shot in enumerate(shots):
        path = image_paths.get(shot.reference)
        if not path:
            continue
        filters.append({
            "index": index,
            "path": str(path),
            "enable": f"between(t,{shot.start:.3f},{shot.end:.3f})",
            # Scaled to cover and cropped, so a square product photo does not
            # letterbox a 9:16 reel with black bars down both sides.
            "scale": "scale=iw*max(1080/iw\\,1920/ih):ih*max(1080/iw\\,1920/ih),"
                     "crop=1080:1920",
        })
    return filters
