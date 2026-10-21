"""Continuity between five-second segments, beyond the last frame.

Wan 2.2 continues from an image. That image carries everything visible in one
frame and nothing else, which is why stitched videos drift: the jacket was blue
in segment one and the last frame happened to show the sleeve, so segment two
invents a colour. The light was warm and low; the frame shows a wall; segment
three lights it from the front.

So each segment records what the scene *is*, not only what it looked like at
the final instant, and the next segment's prompt is built from both.

Everything here is plain data. There is no model call: the state comes from the
script the LLM already wrote (§9.1) and from the previous segment's own state,
so carrying continuity costs nothing extra per segment. Vision-derived state —
reading the rendered frame to check the jacket really is still blue — belongs
to phase 21's QC, which will write into these same fields.
"""
from __future__ import annotations

import re

from dataclasses import asdict, dataclass, field

#: The axes that visibly break when they are not carried forward. Kept short on
#: purpose: every field is one more thing in the prompt, and a prompt stuffed
#: with fifty attributes describes nothing.
FIELDS = (
    "characters",
    "objects",
    "location",
    "lighting",
    "camera",
    "clothing",
    "colors",
    "action",
)


@dataclass
class SceneState:
    """What the scene contains, so the next segment does not re-invent it."""

    characters: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    location: str = ""
    lighting: str = ""
    camera: str = ""
    clothing: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    #: The only field that is *meant* to change between segments; everything
    #: else changing is usually drift.
    action: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> SceneState:
        """Build from stored JSON, ignoring anything we do not know.

        Tolerant by design: old segment rows have no state at all, and a
        renamed field must not break a resume of a job that is half done.
        """
        data = data or {}
        known = {}
        for name in FIELDS:
            value = data.get(name)
            if value is None:
                continue
            default = getattr(cls(), name)
            if isinstance(default, list):
                known[name] = [str(v) for v in value] if isinstance(value, list) else [str(value)]
            else:
                known[name] = str(value)
        return cls(**known)

    @property
    def is_empty(self) -> bool:
        return not any(getattr(self, name) for name in FIELDS)

    def carry_forward(self, action: str = "") -> SceneState:
        """The state the next segment starts from.

        Everything persists except the action — which is exactly the point.
        """
        nxt = SceneState.from_dict(self.as_dict())
        nxt.action = action
        return nxt

    def continuity_prompt(self) -> str:
        """The sentence appended to the next segment's visual prompt.

        Phrased as constraints rather than description ("the same X"), because
        a plain restatement reads to the model as a new subject to introduce,
        and it will happily introduce a second person wearing the same coat.
        """
        parts = []
        if self.characters:
            parts.append("the same " + ", ".join(self.characters))
        if self.clothing:
            parts.append("still wearing " + ", ".join(self.clothing))
        if self.objects:
            parts.append("the same " + ", ".join(self.objects))
        if self.location:
            parts.append(f"in the same {self.location}")
        if self.lighting:
            parts.append(f"unchanged lighting: {self.lighting}")
        if self.camera:
            parts.append(f"camera: {self.camera}")
        if self.colors:
            parts.append("consistent colours: " + ", ".join(self.colors))
        if not parts:
            return ""
        return "Continuity — " + "; ".join(parts) + "."


def from_scene(scene, previous: SceneState | None = None) -> SceneState:
    """State for a scene, inheriting whatever the previous segment established.

    The script's own fields win where it says something; the previous state
    fills the rest. A scene that says nothing about clothing means "as before",
    not "no clothing" — and treating silence as a reset is precisely the drift
    this module exists to stop.
    """
    base = previous.carry_forward() if previous else SceneState()
    declared = SceneState.from_dict((getattr(scene, "state", None) or {}))

    for name in FIELDS:
        value = getattr(declared, name)
        if value:
            setattr(base, name, value)

    # A new visual anchor is a deliberate cut; nothing should be carried over.
    transition = getattr(scene, "transition", None)
    if transition == "NEW_SCENE":
        base = declared

    base.action = (
        declared.action
        or getattr(scene, "motion_prompt", "")
        or ""
    )
    return base


def build_prompt(scene, state: SceneState) -> str:
    """The bare positive prompt for one segment: its own text plus continuity.

    Kept minimal on purpose — this is what the tests and the panel read as
    "the scene". The quality anchors, the negative and the repair hints are
    added by `compile_prompt`, which is what the generator actually sends.
    """
    prompt = (getattr(scene, "visual_prompt", "") or "").strip()
    motion = (getattr(scene, "motion_prompt", "") or "").strip()
    if motion:
        prompt = f"{prompt}. Motion: {motion}" if prompt else f"Motion: {motion}"

    continuity = state.continuity_prompt() if state else ""
    if continuity and getattr(scene, "transition", None) != "NEW_SCENE":
        prompt = f"{prompt} {continuity}".strip()
    return prompt


# ---------------------------------------------------------------------------
#  The prompt compiler — §9.2 layer 1.
#
#  «قبل از ارسال، سیستم خودش Prompt را تقویت کند.» The script LLM writes what
#  the scene shows; this adds what every good clip needs and the model would
#  otherwise have to be lucky about: the same product all the way through, a
#  stable set, one smooth camera move, and — on a second attempt — a sentence
#  aimed at whatever went wrong the first time.
# ---------------------------------------------------------------------------

#: Words the scene text may take before it is trimmed. umT5 has room for far
#: more, but a long prompt dilutes the anchors that keep the product itself.
SCENE_WORD_BUDGET = 55
MOTION_WORD_BUDGET = 12
CONTINUITY_WORD_BUDGET = 28

#: Short by design: each phrase is one failure mode the video model has.
QUALITY_ANCHORS = (
    "the same product throughout with unchanged shape, colour and details, "
    "stable environment and lighting, one smooth continuous camera move, "
    "natural motion, no sudden transformation, no cuts, sharp commercial footage, "
    "no text"
)

#: Added to every Wan negative prompt. These are VIDEO failure modes; the
#: image negative (blurry, text, watermark...) already covers the rest.
#: Deliberately absent: "bright colors"/"vivid colors" — the Wan default
#: negative includes them and they push saturation away from the product's
#: true colour, which is the one thing a shop cannot forgive.
VIDEO_NEGATIVE = (
    "static, still image, frozen, flickering, morphing, warping, ghosting, "
    "duplicated objects, extra fingers, fused fingers, deformed hands, "
    "malformed limbs, extra limbs, disfigured face, jump cut, sudden scene change, "
    "camera shake, overexposed, jpeg artifacts"
)

#: Lips. The narration is a voice-over: a person in the frame whose mouth
#: moves is "talking" with no sound, or with somebody else's words — the
#: single most artificial-looking thing a product video can do. Wan animates
#: mouths freely unless told not to, and this pipeline runs Wan at cfg 1
#: (lightx2v distilled), where the NEGATIVE prompt is skipped entirely — so
#: the instruction has to be in the positive text.
MOUTH_CLOSED = "the person's mouth stays closed, lips still, not talking, calm neutral expression"
#: For a scene where the person is meant to speak the narration (lip-sync):
#: the face the lip-sync model needs — frontal, visible, mouth relaxed.
ON_CAMERA = (
    "the person faces the camera and looks at the viewer, face clearly visible and well lit, "
    "mouth relaxed, head steady"
)
TALKING_NEGATIVE = "talking, speaking, open mouth, moving lips, lip movement, chewing"

#: English words in a scene description that mean a person is in the frame.
_PEOPLE = re.compile(
    r"\b(?:woman|women|man|men|girl|girls|boy|boys|person|people|model|models|customer|"
    r"lady|guy|child|children|kid|kids|couple|she|he|her|his|influencer|"
    r"presenter|barista|chef|shopper|athlete|bride|groom|mother|father|friend|friends)\b",
    re.IGNORECASE,
)


def has_people(scene, state: "SceneState | None") -> bool:
    """Is somebody in this shot? From the carried state, or the scene's words."""
    if state is not None and state.characters:
        return True
    declared = (getattr(scene, "state", None) or {}).get("characters") if isinstance(
        getattr(scene, "state", None), dict) else None
    if declared:
        return True
    return bool(_PEOPLE.search(getattr(scene, "visual_prompt", "") or ""))


# ---------------------------------------------------------------------------
#  Product-only scenes.
#
#  A coffee ad (script 1, 1405/07/29) came out with "a woman with a man's
#  hands" grabbing the mug from the middle of the table: the script model had
#  written "a hand reaching for it" and "a smile on a person's face" into
#  scenes 2 and 3 although nothing asked for a person, and the continuity
#  clause then carried "the same smiling person" forward. A person who
#  appears from nowhere is the most artificial thing a generated product
#  video can show, so unless a scene really needs one — the shop marked the
#  scene «گوینده در تصویر», or the product is worn or applied on the body —
#  the scene is rendered product-only: the person is cut out of its words,
#  the motion is the camera's, and the prompt says so in the POSITIVE text
#  (Wan runs at cfg 1 here, where the negative prompt is skipped).
# ---------------------------------------------------------------------------

#: Said in the positive prompt of a product-only scene, right after the scene.
PRODUCT_ONLY = (
    "product only, no people, no hands, nobody enters the frame, "
    "only the camera moves, the product stays still"
)
#: Added to the negative of a product-only scene (used once the sampler runs
#: with guidance; harmless at cfg 1).
NO_PEOPLE_NEGATIVE = (
    "person, people, human, face, hands, fingers, arm, body, extra limbs, "
    "deformed hands, text, watermark"
)
#: The motion a product-only scene gets when the script's motion was a
#: person's (a hand reaching, a face smiling).
CAMERA_ONLY_MOTION = "slow push-in on the product, camera only, nothing else moves"

#: Parts of a body, and what bodies do to a product. A hand alone is a person
#: to the video model: it has to belong to somebody, and Wan draws them.
_BODY = re.compile(
    r"\b(?:hands?|fingers?|arms?|faces?|lips|mouth|smil(?:e|es|ed|ing)|eyes|wrists?|palms?|"
    r"someone|somebody|anyone|holding|holds|grabs?|grabbing|reach(?:es|ing)?|picks? up|"
    r"sips?|sipping|wears|wearing|human|humans)\b",
    re.IGNORECASE,
)

#: Products a person naturally appears with: worn or applied on the body. Matched
#: as whole words of the product's name, category, tags and attributes —
#: never the shop's business type (a clothing shop's test coffee is coffee).
WEARABLE_WORDS = frozenset({
    # fa
    "لباس", "پوشاک", "پیراهن", "تیشرت", "تی‌شرت", "شلوار", "مانتو", "کت", "کاپشن",
    "ژاکت", "هودی", "سویشرت", "دامن", "بلوز", "تونیک", "پالتو", "جین", "شومیز",
    "کفش", "کتانی", "کتونی", "صندل", "بوت", "چکمه", "دمپایی", "کیف", "کوله",
    "عینک", "ساعت", "انگشتر", "گردنبند", "دستبند", "گوشواره", "جواهر", "زیورآلات",
    "بدلیجات", "کلاه", "شال", "روسری", "جوراب", "دستکش", "کمربند", "کراوات",
    "آرایش", "آرایشی", "رژ", "ریمل", "کرم", "لوسیون", "عطر", "ادکلن", "شامپو",
    "لاک", "مژه", "ساپورت", "لگ",
    # en
    "shirt", "t-shirt", "tshirt", "dress", "jacket", "coat", "pants", "trousers",
    "jeans", "skirt", "hoodie", "sweater", "blouse", "shoe", "shoes", "sneaker",
    "sneakers", "boot", "boots", "sandal", "sandals", "heels", "bag", "handbag",
    "backpack", "purse", "glasses", "sunglasses", "eyewear", "watch", "ring",
    "necklace", "bracelet", "earring", "earrings", "jewelry", "jewellery", "hat",
    "cap", "scarf", "hijab", "socks", "gloves", "belt", "tie", "makeup", "lipstick",
    "mascara", "cream", "lotion", "perfume", "cologne", "fragrance", "shampoo",
    "nail", "wig", "apparel", "clothing", "fashion", "wearable",
})

_TOKEN = re.compile(r"[\w‌\-]+", re.UNICODE)


def _product_words(product) -> list[str]:
    texts = [
        str(getattr(product, "name", "") or ""),
        str(getattr(product, "short_description", "") or ""),
    ]
    try:
        category = getattr(product, "category", None)
        if category is not None:
            texts.append(str(getattr(category, "name", "") or ""))
    except Exception:  # noqa: BLE001
        pass
    tags = getattr(product, "tags", None) or []
    if isinstance(tags, list):
        texts += [str(t) for t in tags]
    try:
        for attribute in product.attributes.all()[:40]:
            texts.append(f"{attribute.key} {attribute.value}")
    except Exception:  # noqa: BLE001 — a product without attributes is fine
        pass
    words = []
    for token in _TOKEN.findall(" ".join(texts).lower()):
        words.append(token)
        # «کفش‌های» → «کفش»: the stem before a zero-width joiner
        if "‌" in token:
            words.append(token.split("‌", 1)[0])
    return words


def people_fit(product) -> bool:
    """Is this a product a person naturally appears with (worn, applied)?"""
    if product is None:
        return False
    return any(word in WEARABLE_WORDS for word in _product_words(product))


def mentions_people(text: str) -> bool:
    """Does this text put a person — or a part of one — in the frame?"""
    text = text or ""
    return bool(_PEOPLE.search(text) or _BODY.search(text))


def people_allowed(scene, product=None, state: "SceneState | None" = None) -> bool:
    """May this scene show a person?

    Yes when the shop asked for one (the scene is marked «گوینده در تصویر»),
    or when the product is worn or applied on the body and the scene has a
    person in it. Otherwise the scene is product-only.
    """
    if bool(getattr(scene, "speaker_on_camera", False)):
        return True
    if not people_fit(product):
        return False
    return has_people(scene, state) or mentions_people(getattr(scene, "visual_prompt", "") or "")


_CLAUSE = re.compile(r"(?<=[.;,!?])\s+")
_JOINER = re.compile(
    r"\s+(?=(?:with|while|as|and|beside|next to|near|by|in front of|then|where)\s)",
    re.IGNORECASE,
)


def without_people_text(text: str) -> str:
    """The scene's words with every clause that puts a person in cut out.

    "The same coffee cup, now with a hand reaching for it, warm lighting" →
    "The same coffee cup, warm lighting". A clause is first cut at its joining
    words ("A cup of coffee with a hand reaching for it" keeps "A cup of
    coffee"), so the product's own description survives.
    """
    kept: list[str] = []
    for clause in _CLAUSE.split((text or "").strip()):
        if not clause.strip():
            continue
        if not mentions_people(clause):
            kept.append(clause.strip())
            continue
        head: list[str] = []
        for piece in _JOINER.split(clause):
            if mentions_people(piece):
                break
            head.append(piece.strip())
        # "now with a hand…" would leave a lone "now": not a description.
        if len(" ".join(head).split()) >= 2:
            kept.append(" ".join(head).rstrip(".;,!? ") + ("," if clause.rstrip().endswith(",") else ""))
    out = " ".join(kept).strip().rstrip(",;").strip()
    return out


def without_people(state: "SceneState | None") -> "SceneState | None":
    """The same state with nobody in it: no characters, no clothing, and an
    action only if it is not a person's."""
    if state is None:
        return None
    nxt = SceneState.from_dict(state.as_dict())
    nxt.characters = []
    nxt.clothing = []
    if mentions_people(nxt.action):
        nxt.action = CAMERA_ONLY_MOTION
    return nxt


def _visual_subject(product) -> str:
    """An English description of the product from its photo analysis, if any."""
    try:
        intelligence = getattr(product, "intelligence", None)
        rows = list(getattr(intelligence, "visual_analysis", None) or [])
    except Exception:  # noqa: BLE001 — no analysis is the common case
        rows = []
    for row in rows:
        text = str((row or {}).get("what_is_visible", "") if isinstance(row, dict) else "").strip()
        letters = [ch for ch in text if ch.isalpha()]
        if letters and sum(ch.isascii() for ch in letters) / len(letters) > 0.8:
            text = without_people_text(text) or ""
            if text:
                return _trim_words(text, 16)
    return ""


def product_shot_prompt(product=None, *, product_name: str = "",
                        state: "SceneState | None" = None) -> str:
    """A product-faithful visual prompt built from what we know about the product.

    Used when the script model wrote no visual for a scene, or when cutting
    the person out of its visual left nothing about the product. The video
    starts from the shop's own photo, so "the product from the reference
    photo" is enough for Wan when the name is not English.
    """
    subject = (
        product_name
        or (english_name(product) if product is not None else "")
        or (_visual_subject(product) if product is not None else "")
        or "the product from the reference photo"
    )
    parts = [f"Commercial product shot of {subject}, centred and fully visible"]
    if state is not None and state.location:
        parts.append(f"in {state.location}")
    else:
        parts.append("on a clean surface with a softly blurred background")
    parts.append(f"{state.lighting} lighting" if state is not None and state.lighting
                 else "soft warm studio lighting")
    parts.append("sharp focus, true-to-life colours, shallow depth of field")
    parts.append("no text, no letters, no logos")
    return ", ".join(parts)


#: What to ask for differently when a QC cause names the problem. Keyed by the
#: cause names the QC and repair layers use.
HINTS = {
    # From the mouth-movement check: the person moved their lips on a
    # voice-over scene. Stronger than MOUTH_CLOSED, which was already there.
    "TALKING": (
        "mouth firmly closed for the whole clip, lips pressed together and still, "
        "no talking, no speech, silent calm expression"
    ),
    "ANATOMY": "hands still or out of frame, no close-up of hands, product held steady",
    "OBJECT_CONSISTENCY": (
        "the exact same {product} throughout, same shape, colour and logo, fully "
        "visible, never duplicated or replaced"
    ),
    "CHARACTER_CONSISTENCY": "the same single person, same face and clothing, nobody else enters",
    "ARTIFACTS": "clean sharp footage, stable geometry, no smearing",
    "FROZEN": "continuous gentle camera movement through the whole clip",
    "MOTION_JUMP": "one slow continuous camera move, no cuts, no scene change",
    "BLACK": "well-lit, evenly exposed studio lighting on the product",
    "DARK": "bright, well-lit scene with soft even studio lighting on the product",
    "FLICKER": "steady constant lighting, no flicker",
    "COLOUR_DRIFT": "constant colour and lighting from the first frame to the last",
    # From the vision QC: somebody appeared in a scene that is product-only.
    "UNWANTED_PERSON": (
        "empty scene with only the product, no person, no hands, no face, "
        "nobody enters the frame"
    ),
}

#: Causes that mean "the motion the script asked for was too much for the
#: model" — on a retry the camera does the simplest thing that still moves.
_SIMPLIFY_MOTION_FOR = {"ANATOMY", "OBJECT_CONSISTENCY", "ARTIFACTS", "MOTION_JUMP", "UNWANTED_PERSON"}
SIMPLE_MOTION = "slow push-in on the product, camera only, nothing else moves"


def _trim_words(text: str, budget: int) -> str:
    """Cut at a sentence boundary before the budget when there is one; never
    mid-word."""
    words = (text or "").split()
    if len(words) <= budget:
        return " ".join(words)
    kept = " ".join(words[:budget])
    for stop in (". ", "; ", ", "):
        cut = kept.rfind(stop)
        if cut > len(kept) * 0.6:
            return kept[:cut].rstrip(".;, ")
    return kept.rstrip(".;, ")


def english_name(product) -> str:
    """The product's name if the video model can read it, else ''.

    Wan's text encoder is trained on English; a Persian product name inside an
    otherwise English prompt is noise at best. The scene text — which the
    script model writes in English — already describes the product, so when
    the name is Persian the anchors say "the product" and lean on that.
    """
    name = str(getattr(product, "name", "") or "").strip()
    if not name:
        return ""
    latin = sum(1 for ch in name if ch.isascii() and ch.isalpha())
    other = sum(1 for ch in name if ch.isalpha() and not ch.isascii())
    if latin >= 3 and latin >= other:
        return name[:60]
    return ""


def base_state(product=None) -> SceneState:
    """What every segment of this product's video must keep, before the script
    says anything: the product itself and its colour.

    The script prompt asks for a per-scene state, but a model that answers
    without one — the common case with small local models — must not leave the
    continuity clause empty, which is how "the same handbag" became "a
    handbag" between segments one and two.
    """
    state = SceneState()
    if product is None:
        return state
    name = english_name(product)
    if name:
        state.objects = [name]
    colours: list[str] = []
    try:
        for attribute in product.attributes.all()[:40]:
            key = str(getattr(attribute, "key", "") or getattr(attribute, "name", "")).lower()
            value = str(getattr(attribute, "value", "") or "").strip()
            if value and any(word in key for word in ("رنگ", "color", "colour")):
                for part in value.replace("،", ",").replace("/", ",").split(","):
                    part = part.strip()[:30]
                    if part and part not in colours:
                        colours.append(part)
    except Exception:  # noqa: BLE001 — a product without attributes is fine
        pass
    state.colors = colours[:3]
    return state


def absorb_observed(state: SceneState, observed: dict | None) -> SceneState:
    """Fill what the script left empty with what the vision QC actually saw.

    Fill-only-empty on purpose: the script's own declared values win, and a
    hallucinated colour cannot overwrite a stated one. Called only after a
    passing QC, never on a failed or unchecked report — see the pipeline.
    """
    if not observed:
        return state
    nxt = SceneState.from_dict(state.as_dict())
    colours = [str(c) for c in (observed.get("product_colours") or []) if str(c).strip()]
    clothing = [str(c) for c in (observed.get("clothing") or []) if str(c).strip()]
    background = str(observed.get("background") or "").strip()
    try:
        people = int(observed.get("people", 0) or 0)
    except (TypeError, ValueError):
        people = 0
    if not nxt.colors and colours:
        nxt.colors = colours[:3]
    if not nxt.clothing and clothing:
        nxt.clothing = clothing[:3]
    if not nxt.location and background:
        nxt.location = background[:80]
    if people == 0:
        # A product-only shot must not carry "the same person" into the next
        # prompt: that clause invites a person into a frame that had none.
        nxt.characters = []
        nxt.clothing = []
    return nxt


def compile_prompt(
    scene,
    state: SceneState | None,
    *,
    product_name: str = "",
    hints=(),
    attempt: int = 1,
    base_negative: str = "",
    allow_people: bool | None = None,
    product=None,
) -> tuple[str, str]:
    """(positive, negative) for one Wan segment.

    Order inside the positive is the order of importance to the model: the
    scene, its motion, the anchors, the continuity, then the repair hint. On a
    retry for a cause that implies the motion was too ambitious, the motion is
    replaced by the simplest move that still moves.

    `allow_people=False` renders the scene product-only (see `people_allowed`):
    the person is cut out of the scene's words and the continuity, the motion
    becomes the camera's, and "product only, no people" is said right after
    the scene. None keeps the scene as written (callers that predate the rule).
    """
    causes = [str(c).upper() for c in (hints or []) if c]
    product_only = allow_people is False
    visual = (getattr(scene, "visual_prompt", "") or "").strip()
    motion = (getattr(scene, "motion_prompt", "") or "").strip()
    if product_only:
        state = without_people(state)
        cleaned = without_people_text(visual)
        if len(cleaned.split()) < 4:
            cleaned = product_shot_prompt(product, product_name=product_name, state=state)
        visual = cleaned
        if not motion or mentions_people(motion):
            motion = CAMERA_ONLY_MOTION
    elif not visual:
        visual = product_shot_prompt(product, product_name=product_name, state=state)
    scene_text = _trim_words(visual, SCENE_WORD_BUDGET)
    if attempt > 1 and any(c in _SIMPLIFY_MOTION_FOR for c in causes):
        motion = SIMPLE_MOTION
    motion = _trim_words(motion, MOTION_WORD_BUDGET)

    parts = [scene_text]
    if product_only:
        parts.append(PRODUCT_ONLY)
    if motion:
        parts.append(f"Motion: {motion}")
    people = (not product_only) and has_people(scene, state)
    on_camera = bool(getattr(scene, "speaker_on_camera", False))
    if people:
        # Right after the motion: it is about the motion of one body part,
        # and it outranks the generic anchors.
        parts.append(ON_CAMERA if on_camera else MOUTH_CLOSED)
    parts.append(QUALITY_ANCHORS)

    continuity = state.continuity_prompt() if state else ""
    if continuity and getattr(scene, "transition", None) != "NEW_SCENE":
        parts.append(_trim_words(continuity, CONTINUITY_WORD_BUDGET))

    for cause in causes:
        template = HINTS.get(cause)
        if template:
            parts.append(template.format(product=product_name or "product"))

    positive = ". ".join(p.rstrip(". ") for p in parts if p).strip() + "."
    # Harmless at cfg 1 (skipped), and it works the day the workflow moves to
    # a guided sampler. Not for a lip-sync scene: the mouth will be redrawn
    # anyway, and forbidding it could fight the model's frontal face.
    talking = TALKING_NEGATIVE if people and not on_camera else ""
    nobody = NO_PEOPLE_NEGATIVE if product_only else ""
    negative = ", ".join(
        part for part in (base_negative.strip().rstrip(","), VIDEO_NEGATIVE, talking, nobody) if part
    )
    return positive, negative
