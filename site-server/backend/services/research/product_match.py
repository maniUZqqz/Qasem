"""«رقیبِ کالایی» — does this competitor sell the same (or a substitutable) product?

**This module is the one place that decides it.** The shop owner said he has
his own code for «رقیب کالایی»; when it arrives it replaces
:func:`match_product` (one pair) and, if needed, :func:`classify_competitor`
(the per-competitor verdict). Everything else — the crawl, the panel, the LLM
confirmation, the opportunities page — only calls these two functions and reads
the fields of :class:`MatchResult`, so swapping the logic touches nothing else.

How the built-in heuristic decides, in plain words:

1. Both names are normalised: Persian/Arabic digits → ``0-9``, ``ي/ى → ی``,
   ``ك → ک``, half-space and punctuation → space, lower-case, filler words
   («خرید»، «قیمت»، «مدل»…) dropped. Units are glued to their number
   («۲۵۰ گرم» → ``250g``) so sizes compare as one token.
2. **Name similarity** = how much of *our* product's name appears in theirs
   (containment, because shop titles are long and marketing-padded), with
   extra weight for *identifying* tokens — brand words, model codes and sizes.
3. **Conflicts** pull the score down: the same unit with a different size
   (``250g`` vs ``1000g``) or a different model code means "similar, not the
   same" — a substitute at best.
4. **Price band**: a price within ×0.5…×2 of ours supports the match; beyond
   ×4 apart it is probably a different product (an accessory, a bulk pack, a
   machine that *uses* the product) and the score is cut hard past ×5.

Verdicts: ``score ≥ CONFIDENT`` → *same product* (``matches`` is set);
``BORDERLINE ≤ score < CONFIDENT`` → *maybe* — an LLM is asked when one is
reachable, and its yes/no + reason is recorded next to the heuristic.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

CONFIDENT = 0.62
BORDERLINE = 0.38

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CHARS = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا",
    "إ": "ا", "آ": "ا", "ؤ": "و", "‌": " ", "‏": " ", "‎": " ",
    "ـ": "",
})
_DIACRITICS = re.compile(r"[ً-ٰٟ]")
_PUNCT = re.compile(r"[^\w\s]|_", re.U)

#: Words that appear in every shop title and identify nothing.
STOPWORDS = {
    "خرید", "قیمت", "مدل", "عدد", "بسته", "اصل", "اورجینال", "جدید", "ویژه",
    "فروش", "با", "و", "در", "از", "به", "برای", "این", "که", "یک", "را",
    "همراه", "طرح", "سری", "نوع", "کد", "محصول", "کالا", "ارسال", "رایگان",
    "تخفیف", "پیشنهاد", "شگفت", "انگیز", "the", "and", "for", "with", "of",
    "new", "original", "pack", "buy", "price", "model",
}

#: Unit words glued to the preceding number («250 گرم» → "250g").
UNITS = {
    "گرم": "g", "گرمی": "g", "g": "g", "gr": "g", "کیلو": "kg", "کیلوگرم": "kg",
    "کیلویی": "kg", "kg": "kg", "میلی": "ml", "میلیلیتر": "ml", "ml": "ml",
    "سی": "cc", "cc": "cc", "لیتر": "l", "لیتری": "l", "l": "l", "عددی": "pcs",
    "عدد": "pcs", "تایی": "pcs", "متر": "m", "سانت": "cm", "سانتیمتر": "cm",
    "cm": "cm", "mm": "mm", "اینچ": "in", "گیگ": "gb", "گیگابایت": "gb", "gb": "gb",
    "ترابایت": "tb", "tb": "tb", "وات": "w", "w": "w", "میلیامپر": "mah", "mah": "mah",
    "سایز": "size",
}

_NUM_UNIT = re.compile(r"^(\d+(?:\.\d+)?)([a-z]+)$")


def normalize(text: str) -> str:
    text = (text or "").translate(_DIGITS).translate(_CHARS)
    text = _DIACRITICS.sub("", text).lower()
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    """Normalised tokens with sizes glued: ``"قهوه ۲۵۰ گرمی"`` → ``["قهوه", "250g"]``."""
    words = normalize(text).split()
    out: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        # "250g" written together
        m = _NUM_UNIT.match(word)
        if m and m.group(2) in UNITS.values():
            out.append(f"{_num(m.group(1))}{m.group(2)}")
            i += 1
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", word) and i + 1 < len(words):
            unit = UNITS.get(words[i + 1])
            if unit == "ml" and i + 2 < len(words) and words[i + 2] in ("لیتر", "لیتری"):
                i += 1  # «میلی لیتر»
            if unit:
                out.append(f"{_num(word)}{unit}")
                i += 2
                continue
        if word not in STOPWORDS and (len(word) > 1 or word.isdigit()):
            out.append(word)
        i += 1
    return out


def _num(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    return str(int(number)) if number.is_integer() else str(number)


def _is_size(token: str) -> bool:
    return bool(_NUM_UNIT.match(token))


def _is_identifying(token: str) -> bool:
    """Model codes, sizes, latin brand words — tokens that separate products."""
    if _is_size(token):
        return True
    if re.search(r"\d", token) and re.search(r"[a-z]", token):
        return True  # "s23", "ep-ta845" → "ep ta845"
    if re.fullmatch(r"[a-z]{3,}", token):
        return True  # latin brand word
    return False


@dataclass
class MatchResult:
    """What the matcher concluded about one pair. Stored in ``raw["match"]``."""

    score: float
    verdict: str  # "same" | "maybe" | "different"
    reason: str
    our_product_id: int | None = None
    our_product_name: str = ""
    shared: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    price_ratio: float | None = None
    method: str = "heuristic-v1"

    @property
    def confident(self) -> bool:
        return self.verdict == "same"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["confident"] = self.confident
        return data


def match_product(
    our_name: str,
    their_name: str,
    *,
    our_price: float | None = None,
    their_price: float | None = None,
    our_brand: str = "",
) -> MatchResult:
    """Is *their* product the same as (or a substitute for) *ours*?

    Replace this function's body with the owner's «رقیب کالایی» code; keep the
    signature and return a :class:`MatchResult`.
    """
    ours = tokens(f"{our_brand} {our_name}" if our_brand and our_brand not in our_name else our_name)
    theirs = tokens(their_name)
    if not ours or not theirs:
        return MatchResult(0.0, "different", "نامِ یکی از دو کالا خالی است.")

    our_set, their_set = set(ours), set(theirs)
    shared = [t for t in dict.fromkeys(ours) if t in their_set]

    def weight(token: str) -> float:
        return 2.0 if _is_identifying(token) else 1.0

    total = sum(weight(t) for t in our_set)
    hit = sum(weight(t) for t in shared)
    containment = hit / total if total else 0.0
    # How much of *their* name is about our product — a long title that merely
    # mentions our one word ("کیف لپ تاپ مناسب برای قهوه خوری") scores lower.
    coverage = len(shared) / max(1, len(their_set))
    score = 0.8 * containment + 0.2 * min(1.0, coverage * 2)

    # ---- conflicts: same unit, different size; different model codes ----
    conflicts: list[str] = []
    our_sizes = {_NUM_UNIT.match(t).group(2): t for t in our_set if _is_size(t)}
    their_sizes = {_NUM_UNIT.match(t).group(2): t for t in their_set if _is_size(t)}
    for unit, ours_size in our_sizes.items():
        theirs_size = their_sizes.get(unit)
        if theirs_size and theirs_size != ours_size:
            conflicts.append(f"اندازه: {ours_size} ⇄ {theirs_size}")
    our_codes = {t for t in our_set if re.search(r"\d", t) and re.search(r"[a-z]", t)}
    their_codes = {t for t in their_set if re.search(r"\d", t) and re.search(r"[a-z]", t)}
    if our_codes and their_codes and not (our_codes & their_codes):
        conflicts.append(f"کدِ مدل: {', '.join(sorted(our_codes))} ⇄ {', '.join(sorted(their_codes))}")
    if conflicts:
        score *= 0.7

    # ---- price band ---------------------------------------------------------
    ratio = None
    price_note = ""
    if our_price and their_price and our_price > 0 and their_price > 0:
        ratio = float(their_price) / float(our_price)
        if 0.5 <= ratio <= 2.0:
            score = min(1.0, score + 0.08)
            price_note = "قیمت‌ها هم‌رده‌اند"
        elif ratio < 0.2 or ratio > 5.0:
            # ×17 apart is a coffee machine next to a bag of coffee: sharing
            # the word «قهوه» does not make them the same thing.
            score *= 0.4
            price_note = f"قیمت‌ها {ratio:.1f} برابرِ هم‌اند — به‌احتمالِ زیاد کالای دیگری است"
        elif ratio < 0.25 or ratio > 4.0:
            score *= 0.6
            price_note = f"قیمت‌ها {ratio:.1f} برابرِ هم‌اند — احتمالاً کالای دیگری است"
        else:
            price_note = f"قیمت‌ها {ratio:.1f} برابرِ هم‌اند"

    score = round(max(0.0, min(1.0, score)), 3)
    if score >= CONFIDENT:
        verdict = "same"
    elif score >= BORDERLINE:
        verdict = "maybe"
    else:
        verdict = "different"

    # A one-word name («قهوه») is contained in every coffee title. Sharing the
    # word makes them *substitutes*; calling it "the same product" needs the
    # price to agree too, or a 1 kg pack gets compared with a 250 g one.
    # Even with the price in band, a long title around our one word («قهوه
    # هسته خرما یک کیلویی») is a different product that happens to share it.
    generic = len(our_set) <= 1 and not any(_is_identifying(t) for t in our_set)
    if generic and verdict == "same" and (not (ratio and 0.5 <= ratio <= 2.0) or coverage < 0.34):
        verdict = "maybe"
        score = min(score, CONFIDENT - 0.01)
        price_note = (price_note + " · " if price_note else "") + "نامِ کالای شما فقط یک واژه است"

    parts = []
    if shared:
        parts.append("واژه‌های مشترک: " + "، ".join(shared[:6]))
    else:
        parts.append("واژه‌ی مشترکی ندارند")
    if conflicts:
        parts.append("ناهمخوانی: " + "؛ ".join(conflicts))
    if price_note:
        parts.append(price_note)
    label = {"same": "همان کالا", "maybe": "شاید (جایگزین/مشابه)", "different": "کالای دیگر"}[verdict]
    reason = f"{label} — " + " · ".join(parts)

    return MatchResult(
        score=score, verdict=verdict, reason=reason, shared=shared[:10],
        conflicts=conflicts, price_ratio=round(ratio, 3) if ratio else None,
    )


def best_match(our_products, their_name: str, their_price: float | None = None) -> MatchResult:
    """Best of :func:`match_product` across the shop's products.

    ``our_products`` is any iterable of objects with ``pk``, ``name``,
    ``price`` and optionally ``brand``.
    """
    best: MatchResult | None = None
    for product in our_products:
        result = match_product(
            product.name, their_name,
            our_price=float(product.price) if getattr(product, "price", None) else None,
            their_price=their_price,
            our_brand=getattr(product, "brand", "") or "",
        )
        result.our_product_id = product.pk
        result.our_product_name = product.name
        if best is None or result.score > best.score:
            best = result
    return best or MatchResult(0.0, "different", "فروشگاه هنوز محصولی ندارد.")


def classify_competitor(match_dicts: list[dict]) -> dict:
    """Per-competitor verdict from its products' stored ``raw["match"]``.

    A competitor is a confirmed «رقیب کالایی» when at least one of its products
    is confidently the same as one of ours (by the heuristic, or by the LLM on
    a borderline case).
    """
    same = [m for m in match_dicts if m and (m.get("verdict") == "same" or (m.get("llm") or {}).get("same") is True)]
    # «جایگزین»: the model said a buyer would choose it instead. That makes
    # them a product competitor too, but their price is not *our* price, so
    # `matches` (used for price comparison) stays unset for these.
    substitute = [
        m for m in match_dicts
        if m and m not in same and (m.get("llm") or {}).get("substitute") is True
    ]
    maybe = [m for m in match_dicts if m and m.get("verdict") == "maybe" and m not in same and m not in substitute]
    our_ids = {m.get("our_product_id") for m in same + substitute if m.get("our_product_id")}
    if same:
        status = "confirmed"
        label = f"رقیبِ کالایی — {len(same)} کالای مشترک"
        if substitute:
            label += f" و {len(substitute)} جایگزین"
    elif substitute:
        status = "confirmed"
        label = f"رقیبِ کالایی (جایگزین) — {len(substitute)} کالای جایگزین، به تأییدِ مدلِ زبانی"
    elif maybe:
        status = "maybe"
        label = f"شاید رقیبِ کالایی — {len(maybe)} کالای مشابه، تأییدنشده"
    elif match_dicts:
        status = "no"
        label = "کالای مشترکی پیدا نشد"
    else:
        status = "unknown"
        label = "هنوز محصولی از این رقیب نداریم"
    return {
        "status": status, "confirmed": status == "confirmed", "label": label,
        "same": len(same), "substitute": len(substitute), "maybe": len(maybe),
        "our_products": len(our_ids),
        "checked": len(match_dicts),
    }
