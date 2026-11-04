"""Column mapping for CSV imports: what the importer understands, and a first guess from the header names."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from apps.growth_engine.core import normalization as nz

#: the fields a CSV column can feed. ``multi`` columns may be mapped from several CSV columns and
#: may hold several values in one cell (separated by | ; ، , or a new line).
TARGETS = [
    {"key": "business_name", "label": "نام کسب‌وکار", "multi": False},
    {"key": "website", "label": "وب‌سایت", "multi": False},
    {"key": "instagram", "label": "اینستاگرام (آدرس یا @نام)", "multi": False},
    {"key": "phone", "label": "تلفن / موبایل", "multi": True},
    {"key": "email", "label": "ایمیل", "multi": True},
    {"key": "whatsapp", "label": "واتساپ", "multi": True},
    {"key": "telegram", "label": "تلگرام", "multi": True},
    {"key": "category", "label": "دستهٔ کسب‌وکار", "multi": False},
    {"key": "description", "label": "توضیحات", "multi": False},
    {"key": "country", "label": "کشور", "multi": False},
    {"key": "city", "label": "شهر", "multi": False},
    {"key": "tags", "label": "برچسب‌ها", "multi": True},
    {"key": "note", "label": "یادداشت", "multi": False},
    {"key": "address", "label": "نشانی", "multi": False},
    {"key": "language", "label": "زبان (fa / en ...)", "multi": False},
    {"key": "business_type", "label": "نوع کسب‌وکار", "multi": False},
    {"key": "product_categories", "label": "دسته‌های محصول", "multi": True},
    {"key": "product_names", "label": "نام محصولات", "multi": True},
]
TARGET_KEYS = {t["key"]: t for t in TARGETS}
IDENTIFYING = {"business_name", "website", "instagram", "phone", "email"}

#: header words (Persian and English) -> target. Matched ignoring spaces / ZWNJ / case.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "business_name": ("name", "business", "businessname", "company", "shop", "store", "shopname", "storename", "brand", "title",
                      "نام", "نامکسبوکار", "کسبوکار", "نامفروشگاه", "فروشگاه", "برند", "نامبرند", "عنوان", "نامتجاری", "شرکت", "نامشرکت"),
    "website": ("website", "web", "site", "url", "link", "homepage", "domain", "وبسایت", "وبسایت", "سایت", "آدرسسایت", "لینکسایت", "دامنه", "آدرسوبسایت"),
    "instagram": ("instagram", "ig", "insta", "اینستاگرام", "اینستا", "پیج", "صفحهاینستاگرام", "آیدیاینستاگرام", "پیجاینستاگرام"),
    "phone": ("phone", "mobile", "tel", "telephone", "cell", "contact", "تلفن", "موبایل", "شماره", "شمارهتماس", "همراه", "شمارهموبایل", "شمارهتلفن", "تماس"),
    "email": ("email", "mail", "emailaddress", "ایمیل", "پستالکترونیک", "ایمیلآدرس"),
    "whatsapp": ("whatsapp", "واتساپ", "واتساپ", "واتس", "واتساب"),
    "telegram": ("telegram", "tg", "تلگرام"),
    "category": ("category", "type", "industry", "niche", "دسته", "دستهبندی", "نوعکسبوکار", "صنف", "حوزهفعالیت", "زمینهفعالیت", "گروه"),
    "description": ("description", "about", "bio", "desc", "توضیحات", "توضیح", "درباره", "معرفی", "بیو"),
    "country": ("country", "کشور"),
    "city": ("city", "town", "شهر"),
    "tags": ("tags", "tag", "labels", "برچسب", "برچسبها", "تگ", "تگها"),
    "note": ("note", "notes", "comment", "comments", "یادداشت", "یادداشتها", "نظر"),
    "address": ("address", "location", "آدرس", "نشانی", "آدرسفیزیکی"),
    "language": ("language", "lang", "زبان"),
    "business_type": ("businesstype", "نوعفعالیت", "نوعکسبوکار"),
    "product_categories": ("productcategories", "productcategory", "دستهمحصول", "دستههایمحصول"),
    "product_names": ("products", "productnames", "محصولات", "ناممحصولات"),
}
_LOOKUP: dict[str, str] = {}
for _target, _words in SYNONYMS.items():
    for _word in _words:
        _LOOKUP.setdefault(nz.search_key(_word), _target)
# «شناسه» / id columns are never data we import
_IGNORED = {nz.search_key(w) for w in ("id", "شناسه", "ردیف", "row", "index", "تاریخثبت", "وضعیت", "منبعکشف", "تاریخ")}


class MappingError(ValueError):
    pass


def suggest_mapping(headers: Sequence[str]) -> dict[str, str]:
    """{header: target key or ""} guessed from the header names. Each single-value target is
    suggested for the first matching column only."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for header in headers:
        key = nz.search_key(header)
        target = _LOOKUP.get(key, "")
        if key in _IGNORED:
            target = ""
        if target and not TARGET_KEYS[target]["multi"] and target in used:
            target = ""
        # "تلفن 2", "phone2" -> same target as "phone"
        if not target:
            stripped = key.rstrip("0123456789")
            if stripped != key and stripped:
                candidate = _LOOKUP.get(stripped, "")
                if candidate and TARGET_KEYS[candidate]["multi"]:
                    target = candidate
        if target:
            used.add(target)
        mapping[header] = target
    return mapping


def validate_mapping(mapping: Mapping[str, str], headers: Sequence[str]) -> dict[str, str]:
    """Cleaned mapping (unknown headers dropped, empty targets removed) or ``MappingError`` (Persian)."""
    cleaned: dict[str, str] = {}
    counts: dict[str, int] = {}
    for header, target in mapping.items():
        if not target:
            continue
        if header not in headers:
            raise MappingError(f"ستونِ «{header}» در فایل نیست.")
        if target not in TARGET_KEYS:
            raise MappingError(f"مقصدِ «{target}» شناخته نشد.")
        counts[target] = counts.get(target, 0) + 1
        if counts[target] > 1 and not TARGET_KEYS[target]["multi"]:
            raise MappingError(f"بیشتر از یک ستون به «{TARGET_KEYS[target]['label']}» وصل شده است.")
        cleaned[header] = target
    if not (set(cleaned.values()) & IDENTIFYING):
        raise MappingError("دست‌کم یکی از ستون‌های «نام کسب‌وکار»، «وب‌سایت»، «اینستاگرام»، «تلفن» یا «ایمیل» باید وصل شود.")
    return cleaned


def row_to_raw(headers: Sequence[str], cells: Sequence[str], mapping: Mapping[str, str]) -> dict[str, object]:
    """One CSV row -> the ``raw`` dict that ``build_draft`` takes (multi targets collect lists)."""
    raw: dict[str, object] = {}
    for index, header in enumerate(headers):
        target = mapping.get(header)
        if not target:
            continue
        value = cells[index].strip() if index < len(cells) else ""
        if not value:
            continue
        if TARGET_KEYS[target]["multi"]:
            raw.setdefault(target, []).append(value)  # type: ignore[union-attr]
        else:
            raw[target] = value
    return raw
