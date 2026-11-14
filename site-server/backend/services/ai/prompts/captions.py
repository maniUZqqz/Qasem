"""Versioned prompt for platform-specific caption generation (Phase 10)."""
import json

from .product_analysis import brand_context, product_context

CAPTIONS_PROMPT_ID = "captions"
CAPTIONS_PROMPT_VERSION = "6"

CAPTIONS_SYSTEM = (
    "You are an expert Persian social-media copywriter for e-commerce. "
    "You always answer with a single valid JSON object and nothing else. "
    "All caption texts are written in Persian (Farsi). JSON keys stay in English. "
    "You never invent prices, discounts, or product claims not present in the data."
)

PLATFORMS = {"INSTAGRAM", "TELEGRAM", "LINKEDIN"}

REQUIRED_CAPTION_KEYS = ["platform", "short", "medium", "long", "hashtags", "cta"]


def build_captions_prompt(
    product, intelligence, platforms, tone, objective, subject=None, avoid_ctas=None,
) -> str:
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
    avoid_part = ""
    used = [str(c).strip() for c in (avoid_ctas or []) if str(c or "").strip()]
    if used:
        # 11 of the 33 stored captions of one shop ended with the same sentence
        avoid_part = (
            "\n\nCalls to action this shop already used — write a DIFFERENT one "
            "(other verb, other next step):\n"
            + json.dumps(used[:8], ensure_ascii=False, separators=(",", ":"))
        )
    return (
        task_line
        + f"{product_context(product)}"
        f"{brand_context(product.store)}"
        f"{intelligence_part}"
        f"{subject_part}"
        f"{avoid_part}\n\n"
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
        "message, tap the link) — never a vague «همین حالا اقدام کنید». It is a "
        "command addressed to the reader («… بسازید», «… پیام بدهید»), never a passive "
        "or a statement («ساخته شود», «… است»).\n"
        "- Emojis: Instagram 2-4 per caption, Telegram at most 2, LinkedIn none. "
        "Never two emojis in a row.\n"
        "- Persian typography: write the real half-space character inside words like "
        "«می‌شود» and «پیش‌نویس», and use Persian digits in running text. Never type the "
        "NAME of a character or format (half-space, ZWNJ, JSON, prompt) or any other "
        "instruction wording inside a caption: every field must read exactly as it "
        "will be posted.\n"
        "- hashtags: Persian + English mix relevant to the product (max 8; LinkedIn max 3), "
        "each tag once. No hashtag inside the caption body.\n"
        "- Base claims only on the provided data. Mention the price only if a price "
        "is given, and write it exactly as given.\n"
        "- Inside JSON strings use \\n for line breaks — never raw newlines.\n"
        "- Do not exceed the length caps; the full JSON must stay complete and parseable.\n"
        "- Output JSON only, no extra text."
    )


def validate_captions(parsed, requested_platforms, *, product=None, strict=True):
    """Return (ok, problems). Keeps only captions for requested platforms.

    The prompt's own rules are enforced here, because a model follows them most
    of the time and not always (`apps.content.caption_rules` has the reasoning):

    * always fixed in place, they have one right answer: the hashtag list is cut
      to the cap and de-duplicated, emoji are capped and un-stacked per platform;
    * `strict=True`: what only a better answer can fix makes the answer invalid,
      so the caller moves on to the next model — an instruction word printed as
      copy («۳۰ نیم‌فاصله تومان»), a price that is not one of the shop's
      (needs `product`), a CTA that is a statement («… ساخته شود»), a medium
      text that is the long text;
    * `strict=False` (the caller's last attempt): the same findings are kept
      out of `problems`, so the owner still gets a draft — `caption_guard` then
      names each problem beside the text.
    """
    from apps.content import caption_rules as rules

    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    problems = []
    captions = parsed.get("captions")
    if not isinstance(captions, list) or not captions:
        return False, ["captions"]
    allowed_prices = rules.allowed_amounts(product) if product is not None else None
    shop_words = rules.own_words(product) if product is not None else ""
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
            # «#a #b» or «a, b» as one string: split it into tags instead of storing one odd tag
            item["hashtags"] = rules.hashtag_tools.parse(item.get("hashtags"))
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
        produced = dict(zip(lengths, [bool(text) for text in available]))
        best = max(available, key=len)
        for key, value in zip(lengths, available):
            item[key] = value or best

        # 1) fixes with one right answer
        limits = rules.LIMITS.get(platform) or rules.LIMITS["INSTAGRAM"]
        item["hashtags"] = [
            tag for tag in rules.clean_hashtags(item["hashtags"], limits["hashtags"])
            if not rules.instruction_leaks(tag, shop_words)  # a tag made of an instruction word is dropped
        ]
        item["cta"] = str(item.get("cta") or "").strip()
        fields = (*lengths, "cta")
        item.update(rules.limit_emoji_budget({key: item[key] for key in fields}, limits["emoji"]))

        # 2) what only a better answer can fix
        found: list[str] = []
        for key in (*lengths, "cta"):
            for word in rules.instruction_leaks(item[key], shop_words):
                found.append(f"{platform}: instruction word «{word}» in {key}")
        if allowed_prices is not None:
            for key in (*lengths, "cta"):
                for amount in rules.price_problems(item[key], allowed_prices):
                    found.append(f"{platform}: price {amount} in {key} is not the shop's price")
        cta_issue = rules.cta_problem(item["cta"])
        if cta_issue:
            found.append(f"{platform}: cta {cta_issue}")
        if produced["medium"] and produced["long"] and rules.too_similar(
            item["medium"], item["long"]
        ):
            found.append(f"{platform}: medium and long text are the same paragraph")
        if strict:
            problems.extend(dict.fromkeys(found))
        cleaned.append(item)
    parsed["captions"] = cleaned
    missing = set(requested_platforms) - {c["platform"] for c in cleaned}
    if missing:
        problems.append(f"missing platforms: {sorted(missing)}")
    return (len(problems) == 0, problems)
