"""Versioned prompt for the structured advertising video script (Phase 11).

visual_prompt / motion_prompt are ENGLISH (they feed FLUX / Wan 2.2 diffusion
models); narration/concept/cta follow the chosen narration language (fa/en) —
they feed the TTS voice-over and the user.
"""
import json

from .product_analysis import brand_context, product_context

VIDEO_SCRIPT_PROMPT_ID = "video_script"
VIDEO_SCRIPT_PROMPT_VERSION = "6"

NARRATION_LANGUAGES = {
    "fa": "Persian (Farsi)",
    "en": "English",
}

VIDEO_SCRIPT_SYSTEM = (
    "You are an expert advertising video director for social-media product ads. "
    "You always answer with a single valid JSON object and nothing else. "
    "visual_prompt and motion_prompt values must be in ENGLISH (they are used by "
    "image/video diffusion models). concept, narration and cta must be in the "
    "narration language specified in the prompt."
)

TRANSITIONS = {"CONTINUE", "TRANSITION", "NEW_SCENE"}

MAX_SCENES = 12


def build_video_script_prompt(
    product, intelligence, total_duration, segment_duration, objective, language="fa"
) -> str:
    narration_lang = NARRATION_LANGUAGES.get(language, NARRATION_LANGUAGES["fa"])
    scene_count = max(1, min(MAX_SCENES, total_duration // segment_duration))
    intelligence_part = ""
    if intelligence is not None:
        intelligence_part = "\n\nAI product intelligence:\n" + json.dumps(
            {
                "summary": intelligence.summary,
                "selling_points": intelligence.selling_points,
                "target_audience": intelligence.target_audience,
                "positioning": intelligence.positioning,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return (
        "Write a segmented advertising video script for the following product.\n\n"
        f"{product_context(product)}"
        f"{brand_context(product.store)}"
        f"{intelligence_part}\n\n"
        f"Total duration: {total_duration} seconds, split into exactly {scene_count} scenes "
        f"of {segment_duration} seconds each.\n"
        f"Campaign objective: {objective or 'فروش محصول'}\n\n"
        "The video is generated segment-by-segment with an image-to-video model; each "
        "segment starts from the LAST FRAME of the previous one, so visual continuity "
        "matters: keep the same product, environment, lighting and style across CONTINUE "
        "scenes. Use NEW_SCENE only when a hard cut is creatively necessary.\n\n"
        f"Narration language: {narration_lang} — concept, cta and every narration "
        "value MUST be written in this language.\n\n"
        "Produce a single JSON object:\n"
        '{"concept": "...", "cta": "...", "scenes": [\n'
        '  {"index": 1, "duration": ' + str(segment_duration) + ', '
        '"visual_prompt": "...EN, detailed, cinematic...", '
        '"motion_prompt": "...EN camera/subject motion...", '
        '"narration": "...", "transition": "NEW_SCENE|CONTINUE|TRANSITION", '
        '"state": {"characters": ["..."], "objects": ["..."], "location": "...", '
        '"lighting": "...", "camera": "...", "clothing": ["..."], "colors": ["..."]}, '
        '"sound": {"ambience": "<one ambience key or none>", '
        '"effects": [{"key": "<effect key>", "at": <seconds into the scene>}]}}\n]}\n\n'
        "Rules:\n"
        f"- Exactly {scene_count} scenes, index starting at 1.\n"
        "- Scene 1 transition must be NEW_SCENE (it starts from the product photo).\n"
        "- visual_prompt: rich English description of what is on screen (product, "
        "environment, lighting, style). motion_prompt: short English description of "
        "camera/subject movement suitable for an image-to-video model.\n"
        f"- narration: {narration_lang}, and it MUST fit the scene when spoken. Budget "
        f"about 2.5 words per second, so roughly {max(4, int(segment_duration * 2.5))} "
        "words for this scene — one sentence, two at most. A narration that overruns "
        "gets cut off in the finished video.\n"
        "- The narration tells a story across the scenes (hook, then benefit, then "
        "proof, then call to action); it must not repeat the same sentence with "
        "different words in every scene.\n"
        "- NO TEXT IN THE IMAGE: diffusion models cannot render Persian and produce "
        "garbled letters. Every visual_prompt must state 'no text, no letters, no "
        "logos, no typography'.\n"
        "- visual_prompt must keep the product itself unchanged across scenes (same "
        "shape, colour and branding) and ask for sharp, well-lit commercial footage.\n"
        "- motion_prompt: ONE simple camera or subject movement (slow push-in, gentle "
        "orbit, tilt up...). Image-to-video models break down on complex motion.\n"
        "- The last scene should include the call to action.\n"
        "- state: ENGLISH, short. What must stay identical in the NEXT scene: the "
        "people (at most 3 words each), the product and props, the place, the "
        "lighting, the camera, clothing, the product's colours. At most 3 items per "
        "list. Leave a field out when it is unchanged from the previous scene; on a "
        "NEW_SCENE state everything anew.\n"
        "- sound: what the scene should sound like UNDER the narration, so the video "
        "feels like a real place. ambience is ONE of: "
        f"{', '.join(_sound_keys('bed'))}, or none. effects are at most TWO of: "
        f"{', '.join(_sound_keys('spot'))} — only when that thing visibly happens in "
        "the scene (a lamp is switched on, heels walk the runway, a box is unboxed), "
        "with `at` the second it happens. Fewer is better; an ad with a sound on every "
        "move sounds like a cartoon.\n"
        "- Output JSON only, no extra text."
    )


def _sound_keys(kind: str) -> list[str]:
    from services.audio.soundscape import CATALOGUE

    return [k for k, v in CATALOGUE.items() if v.kind == kind]


def _clean_sound(raw, duration: int) -> dict:
    """The scene's sound request, restricted to sounds we can actually place."""
    if not isinstance(raw, dict):
        return {}
    from services.audio.soundscape import BED, CATALOGUE, SPOT

    out: dict = {}
    ambience = str(raw.get("ambience") or "").strip().lower()
    if ambience == "none":
        out["ambience"] = "none"
    elif ambience in CATALOGUE and CATALOGUE[ambience].kind == BED:
        out["ambience"] = ambience
    effects = []
    for item in (raw.get("effects") or [])[:2] if isinstance(raw.get("effects"), list) else []:
        key = str((item.get("key") if isinstance(item, dict) else item) or "").strip().lower()
        if key not in CATALOGUE or CATALOGUE[key].kind != SPOT:
            continue
        try:
            at = float(item.get("at", 0.5)) if isinstance(item, dict) else 0.5
        except (TypeError, ValueError):
            at = 0.5
        effects.append({"key": key, "at": round(max(0.0, min(float(duration) - 0.3, at)), 2)})
    # Kept even when empty: an explicit "no effects here" from the script model
    # is a decision, and the planner must not replace it with a keyword guess.
    if isinstance(raw.get("effects"), list):
        out["effects"] = effects
    return out


_STATE_LISTS = ("characters", "objects", "clothing", "colors")
_STATE_TEXTS = ("location", "lighting", "camera", "action")


def _clean_state(raw) -> dict:
    """The per-scene continuity state, trimmed to what a prompt can carry.

    Unknown keys are dropped, lists are capped at three short items, texts at
    eighty characters. Anything unusable becomes an empty dict rather than an
    error — see services.video.scene_state for why silence means "as before".
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key in _STATE_LISTS:
        value = raw.get(key)
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            items = []
            for item in value:
                text = str(item).strip()[:40]
                if text and text not in items:
                    items.append(text)
            if items:
                out[key] = items[:3]
    for key in _STATE_TEXTS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:80]
    return out


def validate_video_script(parsed, segment_duration: int):
    """Return (ok, problems); normalizes scenes in place (sequential re-index)."""
    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    problems = []
    for key in ["concept", "cta", "scenes"]:
        if key not in parsed:
            problems.append(key)
    scenes = parsed.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return False, problems + ["scenes"]
    normalized = []
    for position, scene in enumerate(scenes[:MAX_SCENES], start=1):
        if not isinstance(scene, dict):
            problems.append(f"scene {position}: not an object")
            continue
        visual = str(scene.get("visual_prompt", "") or "").strip()
        if not visual:
            problems.append(f"scene {position}: visual_prompt")
            continue
        transition = str(scene.get("transition", "CONTINUE")).upper()
        if transition not in TRANSITIONS:
            transition = "CONTINUE"
        try:
            duration = int(scene.get("duration") or segment_duration)
        except (TypeError, ValueError):
            duration = segment_duration
        normalized.append(
            {
                "duration": max(1, min(10, duration)),
                "visual_prompt": visual,
                "motion_prompt": str(scene.get("motion_prompt", "") or "").strip(),
                "narration": str(scene.get("narration", "") or "").strip(),
                "transition": transition,
                # Optional and tolerant: a model that answers without it must not
                # fail the script. The continuity engine fills what is missing
                # from the previous segment and from the product itself.
                "state": _clean_state(scene.get("state")),
                # Same rule for sound: absent or unknown keys → decided later
                # from the scene's own words.
                "sound": _clean_sound(scene.get("sound"), duration),
            }
        )
    # sequential re-index (no gaps, regardless of model numbering);
    # the first scene always anchors on a fresh image
    for index, scene in enumerate(normalized, start=1):
        scene["index"] = index
    if normalized:
        normalized[0]["transition"] = "NEW_SCENE"
    else:
        problems.append("scenes")
    parsed["scenes"] = normalized
    return (len(problems) == 0, problems)
