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
}

#: Causes that mean "the motion the script asked for was too much for the
#: model" — on a retry the camera does the simplest thing that still moves.
_SIMPLIFY_MOTION_FOR = {"ANATOMY", "OBJECT_CONSISTENCY", "ARTIFACTS", "MOTION_JUMP"}
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
) -> tuple[str, str]:
    """(positive, negative) for one Wan segment.

    Order inside the positive is the order of importance to the model: the
    scene, its motion, the anchors, the continuity, then the repair hint. On a
    retry for a cause that implies the motion was too ambitious, the motion is
    replaced by the simplest move that still moves.
    """
    causes = [str(c).upper() for c in (hints or []) if c]
    scene_text = _trim_words((getattr(scene, "visual_prompt", "") or "").strip(), SCENE_WORD_BUDGET)
    motion = (getattr(scene, "motion_prompt", "") or "").strip()
    if attempt > 1 and any(c in _SIMPLIFY_MOTION_FOR for c in causes):
        motion = SIMPLE_MOTION
    motion = _trim_words(motion, MOTION_WORD_BUDGET)

    parts = [scene_text]
    if motion:
        parts.append(f"Motion: {motion}")
    people = has_people(scene, state)
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
    negative = ", ".join(
        part for part in (base_negative.strip().rstrip(","), VIDEO_NEGATIVE, talking) if part
    )
    return positive, negative
