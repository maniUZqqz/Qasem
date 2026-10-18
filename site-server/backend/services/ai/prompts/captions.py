"""Versioned prompt for platform-specific caption generation (Phase 10)."""
import json

from .product_analysis import brand_context, product_context

CAPTIONS_PROMPT_ID = "captions"
CAPTIONS_PROMPT_VERSION = "5"

CAPTIONS_SYSTEM = (
    "You are an expert Persian social-media copywriter for e-commerce. "
    "You always answer with a single valid JSON object and nothing else. "
    "All caption texts are written in Persian (Farsi). JSON keys stay in English. "
    "You never invent prices, discounts, or product claims not present in the data."
)

PLATFORMS = {"INSTAGRAM", "TELEGRAM", "LINKEDIN"}

REQUIRED_CAPTION_KEYS = ["platform", "short", "medium", "long", "hashtags", "cta"]


def build_captions_prompt(product, intelligence, platforms, tone, objective, subject=None) -> str:
    intelligence_part = ""
    if intelligence is not None:
        intelligence_part = "\n\nAI product intelligence:\n" + json.dumps(
            {
                "summary": intelligence.summary,
                "selling_points": intelligence.selling_points,
                "target_audience": intelligence.target_audience,
                "recommended_tone": intelligence.recommended_tone,
                "marketing_angles": intelligence.marketing_angles,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    subject_part = ""
    task_line = "Write social-media captions for the following product.\n\n"
    if subject is not None:
        # beter.md #11: the caption accompanies a SPECIFIC post (image/video)
        task_line = (
            "Write social-media captions for a SPECIFIC piece of content that "
            "will be posted (described below) — the captions must talk about "
            "what the viewer actually sees in that content, not generically "
            "about the product.\n\n"
        )
        subject_part = "\n\nThe content being posted:\n" + json.dumps(
            subject, ensure_ascii=False, separators=(",", ":")
        )
    return (
        task_line
        + f"{product_context(product)}"
        f"{brand_context(product.store)}"
        f"{intelligence_part}"
        f"{subject_part}\n\n"
        f"Requested platforms: {', '.join(platforms)}\n"
        f"Requested tone: {tone or 'برند خود فروشگاه'}\n"
        f"Campaign objective: {objective or 'فروش محصول'}\n\n"
        "Produce a single JSON object:\n"
        '{"captions": [{"platform": "INSTAGRAM|TELEGRAM|LINKEDIN", "short": "...", '
        '"medium": "...", "long": "...", "hashtags": ["..."], "cta": "..."}]}\n\n'
        "Rules:\n"
        "- Exactly one caption object per requested platform.\n"
        "- short = story/one-liner (max ~80 chars). medium = normal post (max ~300 chars). "
        "long = detailed storytelling post (max ~600 chars).\n"
        "- Adapt writing style per platform (Instagram: energetic, Telegram: "
        "direct + informative, LinkedIn: professional).\n"
        "- Every caption must OPEN with a hook in its first line — a question, a "
        "number, or the problem the product solves. Never open with the product "
        "name or with «معرفی محصول».\n"
        "- The three lengths must say DIFFERENT things (a different angle each), "
        "not the same sentence stretched or trimmed.\n"
        "- Write like a person, not a brochure. Banned unless the data actually "
        "backs them: «بهترین», «بی‌نظیر», «فوق‌العاده», «کیفیت تضمینی», "
        "«با ما همراه باشید».\n"
        "- cta = one concrete action with the next step spelled out (order, direct "
        "message, tap the link) — never a vague «همین حالا اقدام کنید».\n"
        "- Emojis: Instagram 2-4 per caption, Telegram at most 2, LinkedIn none. "
        "Never two emojis in a row.\n"
        "- Persian typography: correct half-space (ZWNJ) in words like «می‌شود» and "
        "«نیم‌فاصله», and Persian digits in running text.\n"
        "- hashtags: Persian + English mix relevant to the product (max 8; LinkedIn max 3). "
        "No hashtag inside the caption body.\n"
        "- Base claims only on the provided data. Mention the price only if a price "
        "is given, and write it exactly as given.\n"
        "- Inside JSON strings use \\n for line breaks — never raw newlines.\n"
        "- Do not exceed the length caps; the full JSON must stay complete and parseable.\n"
        "- Output JSON only, no extra text."
    )


def validate_captions(parsed, requested_platforms):
    """Return (ok, problems). Keeps only captions for requested platforms."""
    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    problems = []
    captions = parsed.get("captions")
    if not isinstance(captions, list) or not captions:
        return False, ["captions"]
    cleaned = []
    for item in captions:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform", "")).upper()
        if platform not in requested_platforms:
            continue
        for key in REQUIRED_CAPTION_KEYS:
            if key not in item:
                item[key] = [] if key == "hashtags" else ""
        if not isinstance(item.get("hashtags"), list):
            item["hashtags"] = [str(item["hashtags"])] if item.get("hashtags") else []
        item["platform"] = platform

        # A caption box that renders empty looks broken to the store owner. If
        # one length is missing (a cut-off answer usually loses the last one),
        # reuse the best text we do have instead of storing "". Only a caption
        # with no text at all is a real failure worth another model.
        lengths = ["short", "medium", "long"]
        available = [str(item.get(key) or "").strip() for key in lengths]
        if not any(available):
            problems.append(f"{platform}: empty caption")
            continue
        best = max(available, key=len)
        for key, value in zip(lengths, available):
            item[key] = value or best
        cleaned.append(item)
    parsed["captions"] = cleaned
    missing = set(requested_platforms) - {c["platform"] for c in cleaned}
    if missing:
        problems.append(f"missing platforms: {sorted(missing)}")
    return (len(problems) == 0, problems)
