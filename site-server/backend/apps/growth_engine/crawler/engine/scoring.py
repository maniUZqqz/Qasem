"""«امتیازِ تناسب»: how well a found business fits a mission, with every point explained in Persian.

Rule-based and deterministic (no AI, no guessing); every point comes from something stored about the business, and a person can read
exactly why a lead scored what it did. It is NOT a prediction that the business will buy - only «does this look like the kind of
business we asked for, in the place we asked for, and can we reach it».

    type confirmed by a map / directory entry .... 18      the name says what it is ........................ 8
    its own site names the kind of business ....... 10      found only by a web search (name + snippet fit) .. 6
    city matches ................................... 8      has map coordinates ............................... 4
    mobile number 14 (landline only 6) · e-mail 8 · website 8 · Instagram 8 · WhatsApp / Telegram 4 · contact form 3
    address 2 · opening hours 2 · rating 4.0+ 3
    signals that fit the mission's product (the words in ``BusinessType.fit_words`` on its site / bio) ... up to 10
    a public Instagram page with 1000+ followers 4 · a business account 2
    found by two or more independent sources ...... 5
    no way to reach it at all ..................... -25
"""
from __future__ import annotations

from apps.growth_engine.core import normalization as nz

from .. import presets
from . import textnorm

LEVELS = {"high": "مناسب", "medium": "متوسط", "low": "کم"}


def level(value: int) -> str:
    return "high" if value >= 70 else "medium" if value >= 45 else "low"


def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _is_mobile(value: str) -> bool:
    try:
        return nz.normalize_phone(value).kind == "mobile"
    except nz.NormalizationError:
        return False


def score(c, spec: dict) -> dict:
    """``c`` is a ``CrawlCandidate`` (or anything with the same attributes). Returns value / level / label / reasons / matched."""
    reasons: list[dict] = []

    def add(points: int, text: str) -> None:
        reasons.append({"text": text, "points": points})

    wanted = [presets.get_type(t) for t in spec.get("business_types", []) if presets.get_type(t)]
    wanted_keys = {t.key for t in wanted}
    sources = {s.get("source") for s in (c.sources or []) if s.get("source")}
    matched_types = [t for t in (c.types or []) if t in wanted_keys]
    sig = c.signals or {}
    site = sig.get("site") or {}
    ig = sig.get("ig") or {}

    # --- is it the right kind of business?
    mapped = bool(sources & {"osm", "directory", "neshan"})
    if matched_types and mapped:
        add(18, f"روی نقشه/فهرست «{presets.get_type(matched_types[0]).fa}» ثبت شده")
    words = list(site.get("words") or [])
    if words:
        add(10, f"سایتش از «{words[0]}» نام می‌برد")
    name_words = textnorm.text_has_any(c.name, [w for t in wanted for w in t.words] + [str(k) for k in spec.get("keywords", [])])
    if name_words and not matched_types:
        add(8, f"نامش «{name_words[0]}» دارد")
    elif name_words and matched_types:
        add(3, f"نامش «{name_words[0]}» دارد")
    if sources == {"search"} or (sources <= {"search", "website"} and "search" in sources and not matched_types):
        serp = sig.get("serp") or {}
        hay = f"{serp.get('title', '')} {serp.get('snippet', '')}"
        if textnorm.text_has_any(hay, [w for t in wanted for w in t.words]):
            add(6, "نتیجهٔ جست‌وجوی وب با نوعِ کسب‌وکار می‌خواند")

    # --- is it in the right place?
    cities = [nz.search_key(x) for x in spec.get("cities", []) if x]
    if c.city and nz.search_key(c.city) in cities:
        add(8, f"در «{c.city}» است")
    if c.lat is not None and c.lon is not None:
        add(4, "جای دقیقش روی نقشه معلوم است")

    # --- can we reach it?
    phones = list(c.phones or [])
    if any(_is_mobile(p) for p in phones):
        add(14, "شمارهٔ موبایل دارد (پیامک، واتساپ و تماس ممکن است)")
    elif phones:
        add(6, "تلفنِ ثابت دارد")
    if c.emails:
        add(8, "ایمیل دارد")
    if c.website:
        add(8, "وب‌سایت دارد")
    if c.instagram:
        add(8, "پیجِ اینستاگرام دارد")
    if c.telegram or c.whatsapp:
        add(4, "تلگرام یا واتساپ دارد")
    if c.contact_form:
        add(3, "فرمِ تماسِ سایتش پیدا شده")
    if c.address:
        add(2, "نشانی دارد")
    if c.hours:
        add(2, "ساعتِ کاری‌اش معلوم است")
    if c.rating and c.rating >= 4.0:
        add(3, f"امتیازِ {_fa(c.rating)} از ۵ دارد")

    # --- does it look like a customer for what the mission sells?
    fit = list(site.get("fit_words") or [])
    bio_fit = textnorm.text_has_any(str(ig.get("bio") or ""), [w for t in wanted for w in t.fit_words])
    fit = list(dict.fromkeys([*fit, *bio_fit]))
    if fit:
        add(min(10, 4 * len(fit)), "از «" + "»، «".join(fit[:3]) + "» نام می‌برد (نشانهٔ تناسب)")
    followers = ig.get("followers")
    if isinstance(followers, int) and followers >= 1000:
        add(4, f"پیجِ عمومیِ اینستاگرامش {_fa(followers)} دنبال‌کننده دارد")
    if ig.get("is_business"):
        add(2, "پیجِ اینستاگرامش حسابِ تجاری است")
    size = spec.get("size", "any")
    if isinstance(followers, int):
        if size == "large" and followers < 2000:
            add(-4, "پیجِ اینستاگرامش از اندازهٔ خواسته‌شده (بزرگ) کوچک‌تر است")
        elif size == "small" and followers >= 20000:
            add(-4, "پیجِ اینستاگرامش از اندازهٔ خواسته‌شده (کوچک) بزرگ‌تر است")
    want_lang = spec.get("language", "fa")
    site_lang = str(site.get("lang") or "").lower()[:2]
    if want_lang in ("fa", "en") and site_lang and site_lang != want_lang:
        add(-6, "زبانِ سایتش با زبانِ خواسته‌شده نمی‌خواند")
    if len(sources) >= 2:
        add(5, "از چند منبعِ مستقل تأیید شد")

    reachable = bool(phones or c.emails or c.website or c.instagram or c.telegram or c.whatsapp or c.contact_form)
    if not reachable:
        add(-25, "هیچ راهِ تماسی پیدا نشد")
    value = max(0, min(100, sum(r["points"] for r in reasons)))
    return {
        "value": value, "level": level(value), "label": LEVELS[level(value)], "reasons": reasons,
        "matched": {"types": matched_types, "words": words[:6], "fit_words": fit[:6], "sources": sorted(sources)},
    }
