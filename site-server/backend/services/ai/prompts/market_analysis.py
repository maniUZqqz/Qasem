"""
Versioned prompt for market/competitor analysis (Phase 6).

Core rule: never fabricate competitor data. Facts may come ONLY from the
research inputs the user provides; everything else must be category-level
reasoning clearly phrased as possibility, with a confidence grade.
"""
import json

from .product_analysis import product_context

MARKET_PROMPT_ID = "market_analysis"
MARKET_PROMPT_VERSION = "4"

MARKET_SYSTEM = (
    "You are a senior market analyst for e-commerce businesses. "
    "You always answer with a single valid JSON object and nothing else. "
    "All JSON string values must be written in Persian (Farsi). JSON keys stay in English. "
    "You NEVER invent competitor names, prices, or statistics that were not provided."
)

REQUIRED_KEYS = [
    "observations",
    "competitors",
    "comparison",
    "competitor_positioning",
    "common_messaging",
    "content_patterns",
    "pricing_observations",
    "common_customer_concerns",
    "content_gaps",
    "differentiation_opportunities",
    "strategy_summary",
    "confidence",
]

LIST_KEYS = [
    "observations",
    "competitors",
    "comparison",
    "competitor_positioning",
    "common_messaging",
    "content_patterns",
    "pricing_observations",
    "common_customer_concerns",
    "content_gaps",
    "differentiation_opportunities",
]

# v3 additions may legitimately be empty when no real data exists; a missing
# key becomes [] instead of failing the whole (10-minute) analysis run.
DEFAULTABLE_LIST_KEYS = {"competitors", "comparison"}

COMPETITOR_FIELDS = [
    "name",
    "brand",
    "product",
    "price",
    "where_sells",
    "how_sells",
    "strengths",
    "weaknesses",
    "source",
]

CONFIDENCE_VALUES = {"LOW", "MEDIUM", "HIGH"}


# Every token of prompt is prefill time, and prefill runs on the CPU for the
# layers that did not fit in VRAM. A pretty-printed dump of 20 results with
# full URLs was a large part of why market analysis hit the 10-minute timeout
# (beter.md v2 #3), so results are compacted to the fields the analysis
# actually cites.
MAX_WEB_ITEMS = 12
MAX_SNIPPET_CHARS = 140


def _domain(url: str) -> str:
    """https://www.shop.ir/x/y?z=1 -> shop.ir (the part a competitor is known by)."""
    raw = (url or "").split("//")[-1].split("/")[0]
    return raw[4:] if raw.startswith("www.") else raw


def compact_web_items(items) -> list[dict]:
    """Trim raw search results down to the facts the model may cite."""
    compacted = []
    for item in items[:MAX_WEB_ITEMS]:
        entry = {
            "source": item.get("source", ""),
            "title": (item.get("title") or "")[:120],
        }
        if item.get("price_toman") is not None:
            entry["price_toman"] = item["price_toman"]
        if item.get("seller"):
            entry["seller"] = str(item["seller"])[:60]
        site = _domain(item.get("url", ""))
        if site:
            entry["site"] = site
        snippet = (item.get("snippet") or "").strip()
        if snippet:
            entry["snippet"] = snippet[:MAX_SNIPPET_CHARS]
        compacted.append(entry)
    return compacted


def build_market_prompt(product, intelligence=None, research_inputs: str = "", web_results=None) -> str:
    intelligence_part = ""
    if intelligence is not None:
        intelligence_part = (
            "\n\nExisting AI product intelligence:\n"
            + json.dumps(
                {
                    "summary": intelligence.summary,
                    "target_audience": intelligence.target_audience,
                    "selling_points": intelligence.selling_points,
                    "positioning": intelligence.positioning,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    research_part = (
        f"\n\nExtra notes provided by the store owner:\n{research_inputs}"
        if research_inputs.strip()
        else ""
    )
    web_part = ""
    items = (web_results or {}).get("items") or []
    if items:
        web_part = (
            "\n\nREAL search results fetched automatically by code "
            f"(fetched at {web_results.get('fetched_at', '?')}; marketplace items have "
            "prices in Toman; 'web:*' items are general web results and may reveal "
            "competitor WEBSITES — these are OBSERVED FACTS you may cite):\n"
            + json.dumps(compact_web_items(items), ensure_ascii=False, separators=(",", ":"))
        )
    elif web_results is not None:
        web_part = "\n\nAutomated marketplace search returned no results (sources may be unavailable)."
    return (
        "Perform a market and competitor analysis for the following product.\n\n"
        f"{product_context(product)}"
        f"{intelligence_part}"
        f"{web_part}"
        f"{research_part}\n\n"
        "Produce a single JSON object with exactly these keys:\n"
        '{"observations": ["..."], '
        '"competitors": [{"name": "...", "brand": "...", "product": "...", "price": "...", '
        '"where_sells": "...", "how_sells": "...", "strengths": ["..."], '
        '"weaknesses": ["..."], "source": "..."}], '
        '"comparison": ["..."], '
        '"competitor_positioning": ["..."], '
        '"common_messaging": ["..."], "content_patterns": ["..."], '
        '"pricing_observations": ["..."], "common_customer_concerns": ["..."], '
        '"content_gaps": ["..."], "differentiation_opportunities": ["..."], '
        '"strategy_summary": "...", "confidence": "LOW|MEDIUM|HIGH"}\n\n'
        "Rules:\n"
        "- All values in Persian (Farsi); confidence stays exactly LOW, MEDIUM or HIGH.\n"
        "- observations = facts extracted ONLY from the marketplace search results above "
        "and/or the owner's notes (name the source, e.g. «دیجی‌کالا: …»). "
        "If neither provided any facts, return an empty list [] — do not invent any.\n"
        "- competitors = one entry PER REAL COMPETITOR found in the search results or the "
        "owner's notes: its name/brand, the competing product, its price (with source), "
        "WHERE it sells (marketplace, own website, Instagram…) and HOW it sells "
        "(positioning, discounts, bundles…), plus its strengths and weaknesses relative "
        "to our product. Only include what the data supports; unknown fields = \"\" and "
        "unsupported claims phrased as possibility. NO invented competitors — empty list "
        "if the data shows none.\n"
        "- comparison = direct our-product-vs-competitors bullet points (price, features, "
        "quality signals, selling channels), each grounded in the data above or clearly "
        "phrased as possibility.\n"
        "- pricing_observations = only prices actually present in the search results or "
        "notes (in Toman, with the source); empty list otherwise.\n"
        "- All other sections may use general knowledge of this product category, but every "
        "unverified claim must be phrased as a possibility (e.g. \"احتمالاً…\"), never as fact.\n"
        "- Never invent competitor names, statistics, or market shares.\n"
        "- LENGTH: at most 6 competitors (the most relevant ones) and 4 to 6 items in "
        "every other list, each one line and each a different point. Do not repeat the "
        "same observation in two lists. Keep the whole JSON compact enough to finish.\n"
        "- comparison = «ما در برابر آن‌ها»: each line names what we win or lose on and "
        "why, so the owner can act on it. No generic «باید کیفیت را بالا ببریم».\n"
        "- differentiation_opportunities = things THIS store could actually do next "
        "week, not strategy-book abstractions.\n"
        "- confidence = HIGH only with substantial real inputs; LOW when reasoning is mostly generic.\n"
        "- strategy_summary = 2 to 4 sentences: who to target, at what price posture, "
        "with what message. A decision, not a description.\n"
        "- Output JSON only, no extra text."
    )


def validate_market(parsed):
    """Return (ok, problems). Tolerates a single string where a list is expected."""
    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    problems = []
    for key in DEFAULTABLE_LIST_KEYS:
        if key not in parsed or parsed[key] in ("", None):
            parsed[key] = []
    for key in REQUIRED_KEYS:
        if key not in parsed:
            problems.append(key)
    for key in LIST_KEYS:
        if key in parsed and not isinstance(parsed[key], list):
            if isinstance(parsed[key], str) and parsed[key].strip():
                parsed[key] = [parsed[key]]
            else:
                problems.append(key)
    # normalize competitor entries: dicts only, all fields present, lists coerced
    if isinstance(parsed.get("competitors"), list):
        cleaned = []
        for item in parsed["competitors"]:
            if not isinstance(item, dict):
                continue
            for field in COMPETITOR_FIELDS:
                if field in ("strengths", "weaknesses"):
                    value = item.get(field)
                    if isinstance(value, str) and value.strip():
                        item[field] = [value]
                    elif not isinstance(value, list):
                        item[field] = []
                else:
                    item[field] = str(item.get(field, "") or "").strip()
            cleaned.append(item)
        parsed["competitors"] = cleaned
    if isinstance(parsed.get("comparison"), list):
        parsed["comparison"] = [str(x) for x in parsed["comparison"] if str(x).strip()]
    if "confidence" in parsed:
        value = str(parsed["confidence"]).upper().strip()
        parsed["confidence"] = value if value in CONFIDENCE_VALUES else "LOW"
    return (len(problems) == 0, problems)
