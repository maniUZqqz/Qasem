"""Versioned prompt for Image Studio creative direction (Phase 9).

QwQ turns product data into a FLUX-ready English prompt plus a Persian concept
summary. Product-preserving modes must not change the product's identity.
"""
import json

from .product_analysis import product_context

IMAGE_PROMPT_ID = "image_studio"
IMAGE_PROMPT_VERSION = "3"

IMAGE_SYSTEM = (
    "You are a senior creative director for e-commerce advertising photography. "
    "You always answer with a single valid JSON object and nothing else. "
    "prompt_en and negative_en must be in ENGLISH (they feed an image diffusion model); "
    "concept_fa, headline_fa and subline_fa must be in Persian (Farsi)."
)

KINDS = {
    "POSTER": (
        "An advertising POSTER built AROUND THE PROVIDED PRODUCT PHOTO (the diffusion "
        "model edits the real photo — the product itself must stay recognizable: same "
        "shape, same color, same branding). Design a bold, campaign-style scene, "
        "background and lighting around it."
    ),
    "PRODUCT_SHOT": (
        "A professional Instagram-ready PRODUCT PHOTO: the real product staged in an "
        "appealing scene with studio-grade lighting and composition. The product itself "
        "must remain exactly the same (shape, color, branding) — only scene, background "
        "and lighting are designed."
    ),
    "ENHANCED": (
        "A product-preserving ENHANCEMENT of the existing photo: clean background, better "
        "lighting, professional look. Change as little as possible about the product; "
        "never alter its shape, color, logo or identity."
    ),
}

REQUIRED_KEYS = ["concept_fa", "prompt_en", "negative_en"]


def build_image_prompt(product, intelligence, kind, style, instructions) -> str:
    intelligence_part = ""
    if intelligence is not None:
        intelligence_part = "\n\nAI product intelligence:\n" + json.dumps(
            {
                "summary": intelligence.summary,
                "selling_points": intelligence.selling_points,
                "target_audience": intelligence.target_audience,
                "recommended_tone": intelligence.recommended_tone,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return (
        "Design one image for the following product.\n\n"
        f"{product_context(product)}"
        f"{intelligence_part}\n\n"
        f"Image type: {KINDS[kind]}\n"
        f"Requested style: {style or 'فروشگاه تصمیم نگرفته — خودت بهترین را انتخاب کن'}\n"
        f"Extra instructions from the store owner: {instructions or '-'}\n\n"
        "Produce a single JSON object:\n"
        '{"concept_fa": "...", "prompt_en": "...", "negative_en": "...", '
        '"headline_fa": "...", "subline_fa": "..."}\n\n'
        "Rules:\n"
        "- prompt_en: one rich, detailed English diffusion prompt (subject, scene, "
        "lighting, composition, style, quality tags). No camera brand names needed.\n"
        "- THE IMAGE MUST CONTAIN NO TEXT AT ALL: diffusion models cannot render Persian "
        "and produce garbled letters. State 'no text, no letters, no typography' inside "
        "prompt_en. Real Persian text is drawn onto the image later by code.\n"
        "- negative_en: things to avoid (artifacts, wrong product changes) — always "
        "include text/letters/typography/watermark terms.\n"
        "- headline_fa: a SHORT punchy Persian headline (max 6 words) that the code will "
        "draw on the poster. subline_fa: an optional smaller Persian line (max 12 words). "
        "For non-POSTER kinds these may be empty strings.\n"
        "- concept_fa: two-sentence Persian explanation of the visual concept for the owner.\n"
        "- QUALITY: the store owner's source photo is often a low-resolution "
        "phone snapshot. prompt_en must ask for a razor-sharp, high-resolution "
        "commercial result: 'ultra sharp focus, fine surface detail and texture, "
        "clean edges, professional studio lighting, high dynamic range, 8k product "
        "photography, no motion blur, no noise, no compression artifacts'.\n"
        "- negative_en must also include: 'blurry, soft focus, low resolution, "
        "pixelated, jpeg artifacts, noise, oversharpened halo, washed out'.\n"
        "- The product identity must be preserved — say so explicitly inside prompt_en "
        "(e.g. 'the exact same product, unchanged').\n"
        "- Output JSON only, no extra text."
    )


def validate_image(parsed):
    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    problems = [key for key in REQUIRED_KEYS if key not in parsed]
    if not problems and not str(parsed.get("prompt_en", "")).strip():
        problems.append("prompt_en")
    if not problems:
        parsed["concept_fa"] = str(parsed["concept_fa"]).strip()
        parsed["prompt_en"] = str(parsed["prompt_en"]).strip()
        parsed["negative_en"] = str(parsed.get("negative_en", "") or "").strip()
        parsed["headline_fa"] = str(parsed.get("headline_fa", "") or "").strip()
        parsed["subline_fa"] = str(parsed.get("subline_fa", "") or "").strip()
    return (len(problems) == 0, problems)
