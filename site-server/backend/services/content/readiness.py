"""What is missing before a good version of this can be made. §25.

Simple mode takes what the shop already has and produces something. Advanced
mode asks first — and the whole value is in *what* it asks. A form that demands
eight fields before it will do anything is a form nobody fills in; one that
says "this needs a photo of the sole, because the scene we planned shows the
shoe from below" gets answered.

So every requirement here carries three things: what is missing, **why this
particular output needs it**, and whether generation can proceed without it.
The third matters most — a requirement that blocks everything turns an
assistant into a gatekeeper, so almost nothing is `blocking` and the rest are
framed as "this will come out better if…".

Nothing here calls a model. The checks are questions about the shop's own data:
does this product have a photo, does it have a description long enough to write
from, has anyone said what the brand sounds like. A model asked "what do you
need?" invents plausible-sounding requirements, and a shop that supplies them
gets no better output for the trouble.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Below this, a description is a name with punctuation — not enough to write a
#: caption from without inventing facts about the product.
MIN_DESCRIPTION = 40

POSTER = "POSTER"
PRODUCT_SHOT = "PRODUCT_SHOT"
CAPTION = "CAPTION"
VIDEO = "VIDEO"


@dataclass
class Requirement:
    key: str
    title: str
    why: str
    #: True only when generation genuinely cannot run. Everything else is a
    #: quality warning the owner may ignore.
    blocking: bool = False
    #: What the panel should show: "upload", "text", "choice".
    input: str = "text"
    options: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "why": self.why,
            "blocking": self.blocking,
            "input": self.input,
            "options": self.options,
        }


def _images(product) -> int:
    try:
        return product.images.count()
    except Exception:  # noqa: BLE001 — unsaved product in a form preview
        return 0


def _has_intelligence(product) -> bool:
    from apps.ai.models import ProductIntelligence

    return ProductIntelligence.objects.filter(product=product).exists()


def _brand_voice(store) -> bool:
    profile = getattr(store, "profile", None)
    if profile is None:
        return False
    return bool((profile.tone or "").strip() or (profile.brand_voice or "").strip())


def check(product, kind: str) -> list[Requirement]:
    """What this particular output would want, in the order it matters."""
    store = product.store
    missing: list[Requirement] = []

    # ---- video: the only genuinely blocking requirement in the product -----
    if kind == VIDEO and _images(product) == 0:
        missing.append(Requirement(
            key="product_image",
            title="حداقل یک عکس از محصول",
            why=(
                "ویدیو از روی عکس ساخته می‌شود، نه از روی متن. بدون عکس، "
                "مدل محصولی اختراع می‌کند که مال شما نیست."
            ),
            blocking=True,
            input="upload",
        ))

    if kind in (PRODUCT_SHOT, POSTER) and _images(product) == 0:
        missing.append(Requirement(
            key="product_image",
            title="عکس محصول",
            why=(
                "بدون عکس واقعی، خروجی یک محصولِ شبیه محصول شما می‌شود نه "
                "خودش — و مشتری چیزی را می‌بیند که نمی‌خرد."
            ),
            blocking=(kind == PRODUCT_SHOT),
            input="upload",
        ))

    # ---- quality, not blocking -------------------------------------------
    if kind == VIDEO and _images(product) < 3:
        missing.append(Requirement(
            key="more_angles",
            title="عکس از زاویه‌های دیگر",
            why=(
                "با یک زاویه، هر قطعه‌ی ویدیو همان نما را تکرار می‌کند. "
                "دو سه زاویه‌ی دیگر یعنی ویدیو واقعاً حرکت دارد."
            ),
            input="upload",
        ))

    if len((product.description or "").strip()) < MIN_DESCRIPTION:
        missing.append(Requirement(
            key="description",
            title="توضیح محصول",
            why=(
                "مدل از توضیح می‌نویسد. اگر توضیحی نباشد، یا کپشن کلی و "
                "بی‌خاصیت می‌شود یا چیزی از خودش درمی‌آورد."
            ),
            input="text",
        ))

    if not _brand_voice(store):
        missing.append(Requirement(
            key="brand_voice",
            title="لحن برند",
            why="بدون این، خروجی شبیه بقیه‌ی فروشگاه‌ها حرف می‌زند.",
            input="choice",
            options=["رسمی", "دوستانه", "حرفه‌ای", "صمیمی"],
        ))

    if kind in (VIDEO, POSTER) and not _has_intelligence(product):
        missing.append(Requirement(
            key="analysis",
            title="تحلیل محصول",
            why=(
                "نقاط فروش و مخاطب هدف از تحلیل می‌آید. بدون آن، سناریو "
                "روی حدس ساخته می‌شود."
            ),
            input="choice",
            options=["همین حالا تحلیل کن"],
        ))

    # ---- advanced-only inputs, offered rather than demanded ---------------
    if kind == VIDEO:
        missing.append(Requirement(
            key="reference",
            title="ویدیوی مرجع یا سبک دلخواه (اختیاری)",
            why=(
                "اگر نمونه‌ای در ذهن دارید، سبک و ریتمش به سناریو منتقل "
                "می‌شود. بدونش هم ساخته می‌شود، فقط سلیقه‌ی خودمان می‌شود."
            ),
            input="text",
        ))

    return missing


def summary(product, kind: str) -> dict:
    """The shape the panel renders, and the answer to "can we start?"."""
    requirements = check(product, kind)
    blocking = [r for r in requirements if r.blocking]
    return {
        "kind": kind,
        "ready": not blocking,
        "blocking": [r.as_dict() for r in blocking],
        "improvements": [r.as_dict() for r in requirements if not r.blocking],
        # Said plainly so the panel does not have to phrase it: Advanced mode
        # is worth using when there is something to answer, and pointless when
        # there is not.
        "advanced_worth_it": len(requirements) > 0,
    }
