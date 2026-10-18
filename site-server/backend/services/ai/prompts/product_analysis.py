"""
Versioned prompts for the product-analysis pipeline.

VISION (qwen3-vl): understand each product image.
REASONING (qwq): synthesize structured product intelligence.
All user-facing values are produced in Persian; JSON keys stay English.
"""

VISION_PROMPT_ID = "product_image_analysis"
VISION_PROMPT_VERSION = "1"

REASONING_PROMPT_ID = "product_intelligence"
REASONING_PROMPT_VERSION = "3"

REASONING_SYSTEM = (
    "You are a senior e-commerce marketing strategist. "
    "You always answer with a single valid JSON object and nothing else. "
    "All JSON string values must be written in Persian (Farsi). JSON keys stay in English."
)

REQUIRED_KEYS = [
    "summary",
    "target_audience",
    "selling_points",
    "weaknesses",
    "objections",
    "marketing_angles",
    "positioning",
    "recommended_tone",
    "content_ideas",
    "use_cases",
]

LIST_KEYS = [
    "target_audience",
    "selling_points",
    "weaknesses",
    "objections",
    "marketing_angles",
    "content_ideas",
    "use_cases",
]


def product_context(product) -> str:
    attributes = ", ".join(f"{a.key}: {a.value}" for a in product.attributes.all()) or "-"
    return (
        f"Store: {product.store.name} ({product.store.business_type or '-'})\n"
        f"Store description: {product.store.description or '-'}\n"
        f"Product name: {product.name}\n"
        f"Description: {product.description or '-'}\n"
        f"Short description: {product.short_description or '-'}\n"
        f"Brand: {product.brand or '-'}\n"
        f"Price: {product.price} {product.currency}\n"
        f"Attributes: {attributes}\n"
        f"Tags: {', '.join(product.tags) if product.tags else '-'}"
    )


def brand_context(store) -> str:
    """The shop's own voice, for prompts that WRITE in that voice.

    The owner is asked for this during onboarding and content stays blocked
    until they answer (services/content/readiness.py), yet nothing downstream
    read it: every caption and every script came out in the model's default
    voice, identical for a surgical-instruments shop and a children's toy
    shop. Left empty it returns "", so the prompt looks exactly as before.

    Not added to the vision or analysis prompts on purpose — those describe
    what is really there, and a brand voice would colour the facts.
    """
    profile = getattr(store, "profile", None)
    if profile is None:
        return ""
    parts = [
        ("Brand voice", (profile.brand_voice or "").strip()),
        ("Preferred tone", (profile.tone or "").strip()),
        ("Content style", (profile.content_style or "").strip()),
    ]
    written = [f"{label}: {value}" for label, value in parts if value]
    if not written:
        return ""
    return (
        "\n\nThe shop's own voice (set by the owner — follow it; it outranks "
        "any default style of yours):\n" + "\n".join(written)
    )


def build_vision_prompt(product) -> str:
    return (
        "You are analyzing a product photo for an online store.\n\n"
        f"{product_context(product)}\n\n"
        "Look at the attached image carefully and answer as a single JSON object "
        "with exactly these keys (values in Persian):\n"
        '{"what_is_visible": "...", "photo_quality": "...", "background": "...", '
        '"lighting": "...", "strengths": ["..."], "problems": ["..."], '
        '"instagram_ready": true/false}\n'
        "Describe only what you actually see. Do not invent details."
    )


def build_reasoning_prompt(product, visual_analyses) -> str:
    visual_part = ""
    if visual_analyses:
        import json as _json

        # compact: every prompt token is prefill time on a partly-offloaded model
        visual_part = (
            "\n\nVisual analysis of the product photos (from a vision model):\n"
            + _json.dumps(visual_analyses, ensure_ascii=False, separators=(",", ":"))
        )
    return (
        "Analyze the following product for marketing purposes.\n\n"
        f"{product_context(product)}"
        f"{visual_part}\n\n"
        "Produce a single JSON object with exactly these keys:\n"
        '{"summary": "...", "target_audience": ["..."], "selling_points": ["..."], '
        '"weaknesses": ["..."], "objections": ["..."], "marketing_angles": ["..."], '
        '"positioning": "...", "recommended_tone": "...", "content_ideas": ["..."], '
        '"use_cases": ["..."]}\n\n'
        "Rules:\n"
        "- All values in Persian (Farsi), written naturally — not translated-sounding.\n"
        "- Base claims only on the provided data; clearly speculative items must be "
        "phrased as possibilities, not facts.\n"
        "- LENGTH: summary = 2 to 3 short sentences. Every list = 4 to 6 items, each "
        "one line, each a DIFFERENT idea — never pad a list by rewording an earlier "
        "item, and never repeat the same idea across two different lists.\n"
        "- weaknesses = weak points of the PRODUCT or the OFFER as a buyer would "
        "perceive them (price, durability, limited options, competition...). This is "
        "the store owner's product page, so NEVER write about our own catalogue data "
        "being incomplete — sentences like 'no description was provided' or 'the brand "
        "is not mentioned' are forbidden and useless to the owner.\n"
        "- objections = realistic customer objections, each phrased in the customer's "
        "own words, as a question or complaint they would actually type.\n"
        "- selling_points = concrete, checkable advantages, not slogans. Avoid empty "
        "superlatives such as «بهترین», «بی‌نظیر», «فوق‌العاده» with nothing behind them.\n"
        "- target_audience = specific segments (who they are and why they buy), not "
        "'everyone' or a bare age range.\n"
        "- positioning = one or two sentences on where this product sits against "
        "typical competitors, and for whom it is the right choice.\n"
        "- recommended_tone = a few words describing the voice to write in.\n"
        "- content_ideas = concrete posts this store could publish, each naming the "
        "format (ریلز / پست / استوری / کاروسل) and what actually happens in it.\n"
        "- use_cases = real situations in which the product is used.\n"
        "- Output JSON only, no extra text."
    )


def validate_intelligence(parsed):
    """Return (ok, missing_or_bad_keys)."""
    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    problems = []
    for key in REQUIRED_KEYS:
        if key not in parsed:
            problems.append(key)
    for key in LIST_KEYS:
        if key in parsed and not isinstance(parsed[key], list):
            # tolerate a single string by wrapping it
            if isinstance(parsed[key], str) and parsed[key].strip():
                parsed[key] = [parsed[key]]
            else:
                problems.append(key)
    return (len(problems) == 0, problems)
