"""The caption prompt's own rules, enforced in code.

The caption prompt tells the model: at most 8 hashtags (LinkedIn 3), two to four
emoji (Telegram two, LinkedIn none), never two emoji in a row, a concrete call to
action, three lengths that say different things, the price exactly as given. A
model follows that most of the time and not always. Of the 33 Instagram captions
already stored for the Chagher store, 12 broke the hashtag rule, 9 the emoji
rule, one printed the prompt's own example word inside the PRICE
(«۳۰ نیم‌فاصله تومان»), two ended «برنامه خود را با ۲۵ توکن ساخته شود.» and one
had a medium and a long text that were the same paragraph.

`caption_guard` reads a stored caption and *says* what looks wrong, for the
owner. This module acts earlier, on the model's answer, in two ways:

* **fix what has one right answer** — cut the hashtag list to the cap, drop the
  duplicates («#چغر» twice, `برنامه_ورزشی` and `برنامه ورزشی`), cap and un-stack
  the emoji. Nothing here changes what the text says.
* **detect what only a better answer can fix** — an instruction word printed as
  copy, a price that is not the shop's, a CTA that is not a call to action,
  a medium text that is the long text. `validate_captions` sends these back to
  the next model, and on the last attempt keeps the text so the owner still gets
  a draft, with the problem named by `caption_guard` next to it.

Pure functions, no model and no database, so every rule is testable with the
real strings above and works when the AI is off.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from apps.common.fatext import en_digits, normalize

from . import hashtags as hashtag_tools

#: per platform: hashtags and emoji allowed in ONE caption, i.e. the whole object
#: the model returns for the platform (short + medium + long + cta together),
#: exactly as the prompt words it: «Instagram 2-4 per caption, Telegram at most 2,
#: LinkedIn none». The budget is shared between the texts, see `limit_emoji_budget`.
LIMITS = {
    "INSTAGRAM": {"hashtags": 8, "emoji": 4},
    "TELEGRAM": {"hashtags": 8, "emoji": 2},
    "LINKEDIN": {"hashtags": 3, "emoji": 0},
}

# ── emoji ────────────────────────────────────────────────────────────────────

_E = "[\U0001F300-\U0001FAFF☀-➿⭐⬆↔-↪⌚-⏿]"
_MARK = "(?:️|[\U0001F3FB-\U0001F3FF])*"
#: one emoji as a person sees it: 🏋️‍♂️ is five code points (and a flag two), one picture
_CLUSTER = re.compile(
    f"[\U0001F1E6-\U0001F1FF]{{2}}|{_E}{_MARK}(?:‍{_E}{_MARK})*"
)


def count_emoji(text: str) -> int:
    return len(_CLUSTER.findall(text or ""))


def limit_emoji(text: str, max_n: int) -> str:
    """At most `max_n` emoji, and never two in a row (the prompt's rule).

    A run of emoji («🧠🏋️‍♂️🥗») keeps its first one. The rest is capped by
    dropping the later ones, so the hook at the start of a caption keeps its
    emoji and the trailing decoration goes.
    """
    text = text or ""
    out: list[str] = []
    pos = 0
    kept = 0
    prev_end = None
    changed = False
    for match in _CLUSTER.finditer(text):
        stacked = prev_end is not None and not text[prev_end:match.start()].strip()
        prev_end = match.end()
        if stacked or kept >= max_n:
            out.append(text[pos:match.start()])
            pos = match.end()
            changed = True
        else:
            kept += 1
    if not changed:
        return text
    out.append(text[pos:])
    result = "".join(out)
    # tidy what the removal left behind: double spaces, a space before the full stop
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"[ \t]+([.!؟?،,؛:])", r"\1", result)
    return "\n".join(line.rstrip() for line in result.split("\n")).strip()


def limit_emoji_budget(texts: dict, budget: int) -> dict:
    """`limit_emoji` over the texts of one caption with ONE shared budget.

    Each text keeps its first emoji before any text gets a second one (the hook
    of the short text, the closing emoji of the CTA), in the order the dict
    lists them, until `budget` is used up. «🧠🏋️‍♂️🥗» stacked at the end of a
    text is one emoji, as in `limit_emoji`.
    """
    clean = {key: limit_emoji(text, 99) for key, text in texts.items()}  # un-stack first
    have = {key: count_emoji(text) for key, text in clean.items()}
    keep = {key: 0 for key in clean}
    left = max(0, budget)
    progress = True
    while left > 0 and progress:
        progress = False
        for key in clean:
            if left > 0 and keep[key] < have[key]:
                keep[key] += 1
                left -= 1
                progress = True
    return {key: limit_emoji(text, keep[key]) for key, text in clean.items()}


# ── hashtags ─────────────────────────────────────────────────────────────────

def _tag_key(tag: str) -> str:
    """Two tags that Instagram would treat as one: «#چغر»/«چغر», «Fitness»/«fitness»,
    «برنامه_ورزشی»/«برنامه ورزشی»/«برنامه‌ورزشی»."""
    return normalize(tag).replace("_", "").replace(" ", "")


def clean_hashtags(tags, limit: int) -> list[str]:
    """Stored form: plain words without «#» (the panel writes the «#»), glued
    words split where the word list knows how, duplicates dropped, at most
    `limit`. The first occurrence wins, so the order the model chose (its most
    relevant tags first) survives."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in hashtag_tools.parse(tags):
        tag = hashtag_tools.repair(raw).lstrip("#").strip()
        key = _tag_key(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out[:limit]


# ── words that belong to the prompt, not to a post ───────────────────────────

#: the NAME of a typing character or a format («۳۰ نیم‌فاصله تومان»,
#: «بدون JSON»): the model copied an instruction word into the copy. Compared
#: in the `normalize` form, which has no half-space — so «نیم‌فاصله» is «نیمفاصله».
_INSTRUCTION = re.compile(
    r"(نیم\s*فاصله|half[\s_-]*space|zwnj|zero[\s_-]*width|پرامپت|\bprompt\b|\bjson\b)",
    re.IGNORECASE,
)


def instruction_leaks(text: str, context: str = "") -> list[str]:
    """Instruction words found in `text`. A word the shop's OWN data uses
    (`context`: product name, description, tags — an AI-tools shop may really
    sell «پرامپت») is not a leak."""
    own = normalize(context or "")
    return [
        m.group(1)
        for m in _INSTRUCTION.finditer(normalize(text or ""))
        if not own or normalize(m.group(1)) not in own
    ]


# ── prices ───────────────────────────────────────────────────────────────────

_AMOUNT = re.compile(r"(\d[\d,٬،.]*)\s*(هزار|میلیون|میلیارد)?\s*(تومان|تومن|ریال)")
_UNIT = {None: 1, "": 1, "هزار": 1_000, "میلیون": 1_000_000, "میلیارد": 1_000_000_000}


def _number(raw: str) -> float | None:
    digits = re.sub(r"[,٬،]", "", raw)
    if digits.count(".") > 1 or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", digits):
        digits = digits.replace(".", "")  # «1.500.000»: dots are thousands separators
    digits = digits.strip(".")
    try:
        return float(digits)
    except ValueError:
        return None


def amounts_in(text: str) -> list[int]:
    """Every price written in `text`, in toman («۳۰۰ هزار تومان» -> 300000)."""
    found: list[int] = []
    for number, unit, currency in _AMOUNT.findall(en_digits(text or "")):
        value = _number(number)
        if value is None:
            continue
        toman = value * _UNIT[unit or None] / (10 if currency == "ریال" else 1)
        found.append(int(round(toman)))
    return found


def allowed_amounts(product) -> set[int]:
    """The prices that are real for this caption: every priced product of the
    shop (a caption for one plan may quote the other: «یک برنامه ۳۰۰ هزار، هر دو ۶۰۰
    هزار») plus any amount the product's own description already states.
    Prices stay the owner's data — nothing is computed or rounded here."""
    allowed: set[int] = set()
    try:
        rows = type(product).objects.filter(store_id=product.store_id).values_list(
            "price", "compare_at_price", "currency",
        )
        for price, compare_at, currency in rows:
            for value in (price, compare_at):
                if not value:
                    continue
                toman = float(value) / (10 if str(currency).upper() in {"IRR", "RIAL", "ریال"} else 1)
                allowed.add(int(round(toman)))
    except Exception:  # noqa: BLE001 — no table, no shop: fall back to this product alone
        if getattr(product, "price", None):
            allowed.add(int(round(float(product.price))))
    store = getattr(product, "store", None)
    own_text = " ".join(
        str(part or "")
        for part in (
            product.description, product.short_description,
            getattr(store, "description", ""),  # «ارسال رایگان بالای ۵۰۰ هزار تومان»
        )
    )
    try:
        own_text += " " + " ".join(f"{a.key} {a.value}" for a in product.attributes.all())
    except Exception:  # noqa: BLE001
        pass
    allowed.update(amounts_in(own_text))
    return allowed


def own_words(product) -> str:
    """The shop's own wording for this product, to tell a leaked instruction
    word from one the shop really uses."""
    parts = [
        getattr(product, "name", ""), getattr(product, "description", ""),
        getattr(product, "short_description", ""), getattr(product, "brand", ""),
        " ".join(str(tag) for tag in (getattr(product, "tags", None) or [])),
    ]
    return " ".join(str(part or "") for part in parts)


def price_problems(text: str, allowed: set[int]) -> list[int]:
    """Amounts in `text` that are not one of the shop's own prices."""
    return [amount for amount in amounts_in(text) if amount not in allowed]


# ── call to action ───────────────────────────────────────────────────────────

_PASSIVE_END = re.compile(
    r"^(?:شود|گردد|شوند|میشود|میگردد|میشوند|است|هست|میکند|میکنیم|میکنند)$"
)
_TRAILING = re.compile(r"[\s.!؟?،,;؛:…\-—)»\"'‌️]+$")


def cta_problem(cta: str) -> str | None:
    """Why this is not a call to action, or None.

    A CTA tells the reader what to DO next, so its verb is a command («بسازید»,
    «پیام بدهید»). A verb in the third person passive («برنامه خود را با ۲۵ توکن
    ساخته شود.») or a plain statement («برنامه آماده است») asks nothing. Only
    clear cases are named; an unusual but correct command is never refused.
    """
    text = _CLUSTER.sub("", cta or "")
    text = _TRAILING.sub("", text)
    words = normalize(text).split()
    if not words:
        return None
    if _PASSIVE_END.match(words[-1]):
        shown = " ".join(re.split(r"\s+", text.strip())[-3:])
        return f"«{shown}» جملهٔ خبری/مجهول است، نه دعوت به اقدام"
    return None


# ── three lengths that must say different things ─────────────────────────────

_TOKEN = re.compile(r"\w+", re.UNICODE)
#: word-level similarity at which two texts read as the same paragraph.
SIMILARITY_LIMIT = 0.7


def similarity(a: str, b: str) -> float:
    ta = _TOKEN.findall(normalize(_CLUSTER.sub(" ", a or "")))
    tb = _TOKEN.findall(normalize(_CLUSTER.sub(" ", b or "")))
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb, autojunk=False).ratio()


def too_similar(a: str, b: str) -> bool:
    """The medium and the long text are the same paragraph. Short texts are
    never compared: two sentences of nine words can overlap by chance."""
    if min(len(_TOKEN.findall(a or "")), len(_TOKEN.findall(b or ""))) < 12:
        return False
    return similarity(a, b) >= SIMILARITY_LIMIT
