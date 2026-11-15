"""کتابخانهٔ «سبک تصویر» (۱۱۶ سبک + ۲۴ تمِ رنگی): ثبت‌نامِ فقط‌خواندنی در کد، جست‌وجو، فیلتر و ردیفِ عمومیِ API.

SOURCE: search/filter part ported from InstAI:instai/styles/library.py @ 2f8aa90 (``_fold``، ``matches``، ``filter_styles``، ``_join``)،
adapted for store advertising. InstAI سبک‌های کاربر را هم در دیتابیس نگه می‌دارد؛ در NM فعلاً فقط سبک‌های کدیِ فقط‌خواندنی هست
(سبکِ ساخته‌شده توسط کاربر کارِ بعدی است) پس هیچ مدل و مهاجرتی لازم نیست.
"""
from __future__ import annotations

from . import fit, schema
from .aliases import known_as, terms_for
from .builtin_styles import BUILTIN_STYLES
from .builtin_themes import BUILTIN_THEMES

API_PREFIX = "/api/v1/looks"


def _sorted_styles() -> dict[str, dict]:
    rows = {k: schema.normalize_style(fit.with_fit(k, v)) for k, v in BUILTIN_STYLES.items()}
    order = lambda kv: (schema.GROUP_ORDER.index(kv[1]["group"]) if kv[1]["group"] in schema.GROUP_ORDER else 99,  # noqa: E731
                        schema.REALISM_ORDER.index(kv[1]["realism"]), kv[1]["name_en"].lower())
    return dict(sorted(rows.items(), key=order))


#: key -> ردیفِ کاملِ سبک (با ``product_safe`` و ``ad_fit``)؛ ترتیبِ مرور: گروه، بعد درجهٔ واقع‌نمایی
STYLES: dict[str, dict] = _sorted_styles()
THEMES: dict[str, dict] = {k: schema.normalize_theme(v) for k, v in BUILTIN_THEMES.items()}


def style(key: str) -> dict | None:
    return STYLES.get(str(key or ""))


def theme(key: str) -> dict | None:
    return THEMES.get(str(key or ""))


def known(key) -> str:
    """کلیدِ سبک اگر در کتابخانه هست، وگرنه ``""`` (برای پاک‌کردنِ ورودیِ کاربر)."""
    k = str(key or "")
    return k if k in STYLES else ""


def join(*parts: str) -> str:
    """تکه‌دستورها را با ویرگول می‌چسباند؛ تکراری‌ها (بدونِ توجه به حروفِ کوچک و بزرگ) یک بار می‌آید."""
    seen: list[str] = []
    for p in parts:
        for piece in [x.strip() for x in (p or "").split(",")]:
            if piece and piece.lower() not in [s.lower() for s in seen]:
                seen.append(piece)
    return ", ".join(seen)


# ───────────────────────────── ردیف‌های عمومی برای API

def entry(key: str, *, detail: bool = False, sample_urls: dict[str, str] | None = None) -> dict:
    s = STYLES[key]
    out = {
        "key": key, "name_fa": s["name_fa"], "name_en": s["name_en"], "description_fa": s["description_fa"],
        "realism": s["realism"], "realism_fa": schema.REALISM[s["realism"]]["fa"],
        "group": s["group"], "group_fa": schema.GROUPS[s["group"]]["fa"] if s["group"] in schema.GROUPS else "",
        "family": s["family"], "family_fa": schema.FAMILIES[s["family"]]["fa"],
        "animation": s["animation"], "animation_fa": schema.ANIMATIONS[s["animation"]]["fa"],
        "palette": s["palette"], "lighting": s["lighting"], "mood": s["mood"], "tags": s["tags"], "suitability": s["suitability"],
        "ad_fit": s["ad_fit"], "ad_fit_fa": [schema.AD_FITS[x]["fa"] for x in s["ad_fit"]],
        "product_safe": s["product_safe"], "theme_key": s["theme_key"],
        "preview_url": f"{API_PREFIX}/{key}/preview.svg",
        "sample_url": (sample_urls or {}).get(key) or None,
        "search_terms": terms_for(key), "known_as": known_as(key),
        "gen": {**s["gen"], "workflow_fa": schema.MODEL_WORKFLOWS.get(s["gen"]["model"], "")},
    }
    if detail:
        out.update(description_en=s["description_en"], image_positive=s["image_positive"], image_negative=s["image_negative"],
                   video_positive=s["video_positive"], video_negative=s["video_negative"], scene_fragments=fit.scene_fragments(s))
    return out


def list_entries(sample_urls: dict[str, str] | None = None) -> list[dict]:
    return [entry(k, sample_urls=sample_urls) for k in STYLES]


def theme_entry(key: str) -> dict:
    t = THEMES[key]
    return {"key": key, "name_fa": t["name_fa"], "name_en": t["name_en"], "description_fa": t["description_fa"], "palette": t["palette"],
            "lighting": t["lighting"], "mood": t["mood"], "tags": t["tags"], "mood_key": f"theme:{key}"}


def list_themes() -> list[dict]:
    return [theme_entry(k) for k in THEMES]


def groups() -> list[dict]:
    counts: dict[str, int] = {}
    for s in STYLES.values():
        counts[s["group"]] = counts.get(s["group"], 0) + 1
    return [{"key": k, "fa": schema.GROUPS[k]["fa"], "count": counts.get(k, 0)} for k in schema.GROUP_ORDER]


def realism_levels() -> list[dict]:
    counts: dict[str, int] = {}
    for s in STYLES.values():
        counts[s["realism"]] = counts.get(s["realism"], 0) + 1
    return [{"key": k, "fa": schema.REALISM[k]["fa"], "count": counts.get(k, 0)} for k in schema.REALISM_ORDER]


def ad_fits() -> list[dict]:
    return [{"key": k, "fa": v["fa"], "count": sum(1 for s in STYLES.values() if k in s["ad_fit"])} for k, v in schema.AD_FITS.items()]


# ───────────────────────────── جست‌وجو (ساختارِ InstAI)

# نامِ کاملی که از یک فهرست چسبانده شده، کروشه و گیومه دارد («Chrome 22K (chrome metallic type)»، «پیکسل‌آرت»): این‌ها جزوِ هیچ واژه‌ای نیستند.
_PUNCTUATION = str.maketrans({c: " " for c in "()[]{}<>«»\"“”‘’,;:!?،؛؟/\\|"})


def fold(text: str) -> str:
    """حروف کوچک و یکی‌کردنِ «ي/ی»، «ك/ک»، نیم‌فاصله و ارقام (فارسی، عربی، انگلیسی)؛ تا جست‌وجو هر طور تایپ شود پیدا کند."""
    text = (text or "").translate(_PUNCTUATION)
    t = text.lower().replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("-", " ")
    return t.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


_FILLER = {"style", "styles", "look", "looks", "like", "سبک", "استایل"}     # «PS2 style»، «Lego-like bricks»: این واژه‌ها جزوِ نام نیستند


def matches(row: dict, q: str) -> bool:
    """یک ردیف به این جست‌وجو جواب می‌دهد؟ هر واژه باید در نام، توضیح، برچسب، نام‌های جست‌وجو (alias) یا کلید بیاید."""
    words = [w for w in fold(q).split() if w]
    words = [w for w in words if w not in _FILLER] or words
    if not words:
        return True
    hay = fold(" ".join([row.get("name_fa", ""), row.get("name_en", ""), row.get("description_fa", ""), " ".join(row.get("tags") or []),
                         " ".join(row.get("search_terms") or []), row.get("key", "").replace("_", " "), row.get("known_as", "")]))
    return all(w in hay for w in words)


def filter_entries(rows: list[dict], *, q: str = "", group: str = "", realism: str = "", ad_fit: str = "", suitability: str = "",
                   family: str = "", product_safe: bool | None = None) -> list[dict]:
    out = []
    for r in rows:
        if group and r.get("group") != group:
            continue
        if realism and r.get("realism") != realism:
            continue
        if family and r.get("family") != family:
            continue
        if ad_fit and ad_fit not in (r.get("ad_fit") or []):
            continue
        if suitability and suitability not in (r.get("suitability") or []):
            continue
        if product_safe is not None and bool(r.get("product_safe")) != product_safe:
            continue
        if q and not matches(r, q):
            continue
        out.append(r)
    return out


# ───────────────────────────── پیشنهاد برای فروشگاه

def suggest(store, limit: int = 5) -> dict:
    """۳ تا ۵ سبک و ۲ تم برای این فروشگاه، فقط از روی پروفایلش: نوعِ کسب‌وکار، توضیحات، مخاطب و رنگ‌های برند. هیچ آمار و ادعایی نیست."""
    matched = fit.business_matches(store)
    if matched:
        by_group = [(row[0], row[1], row[3]) for _score, row in matched[:2]]     # دو گروهِ برترِ کسب‌وکار (مثلاً «نرم‌افزار» و «ورزش» برای چغر)
    else:
        by_group = [("generic", fit.GENERIC[0], fit.GENERIC[1])]
    picks: list[dict] = []
    seen: set[str] = set()
    for depth in range(5):                                   # از هر گروه به نوبت: اولی‌ها اول
        for gkey, title, rows in by_group:
            if depth < len(rows) and len(picks) < limit:
                look_key, why = rows[depth]
                if look_key in STYLES and look_key not in seen:
                    seen.add(look_key)
                    picks.append({"look": look_key, "reason_fa": why, "business": gkey, "business_fa": title})
    themes = [{"theme": tk, "reason_fa": "رنگ‌های برندِ فروشگاه به این تم نزدیک است"}
              for tk in fit.nearest_themes(fit.brand_primary(store), THEMES, 2)]
    return {"business_fa": [g[1] for g in by_group] if matched else [], "looks": picks, "themes": themes, "matched": bool(matched),
            "basis_fa": ("بر پایهٔ نوعِ کسب‌وکار، توضیحات، مخاطب و رنگ‌های برندِ فروشگاهِ شما" if matched
                         else "نوعِ کسب‌وکارِ فروشگاه مشخص نشد؛ این‌ها انتخاب‌های عمومی‌اند")}
