"""LeadDraft: a validated, normalised description of a lead, before it touches the database.

Manual entry, CSV rows (and later: search providers, website extraction) all build a
``LeadDraft`` through ``build_draft``. Validation errors are collected per field so a CSV
row can report all of its problems at once. Nothing is invented: a field that is empty
stays empty.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from apps.growth_engine.core import normalization as nz

from ..choices import IDENTIFIER_KINDS, BusinessType, ContactKind

#: scalar field limits (kept in step with the model columns)
LIMITS = {"business_name": 200, "category": 120, "description": 5000, "city": 100, "address": 400, "note": 5000}
MAX_TAGS = 20

FIELD_LABELS = {
    "business_name": "نام کسب‌وکار", "website": "وب‌سایت", "instagram": "اینستاگرام", "phone": "تلفن", "email": "ایمیل",
    "whatsapp": "واتساپ", "telegram": "تلگرام", "category": "دسته", "description": "توضیحات", "country": "کشور",
    "city": "شهر", "tags": "برچسب‌ها", "note": "یادداشت", "language": "زبان", "business_type": "نوع کسب‌وکار",
    "address": "نشانی", "product_categories": "دسته‌های محصول", "product_names": "نام محصولات",
}


@dataclass
class ContactDraft:
    kind: str
    value: str
    normalized: str
    label: str = ""
    source_ref: str = ""
    source_url: str = ""
    evidence: str = ""
    confidence: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping) -> "ContactDraft":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class LeadDraft:
    business_name: str = ""
    category: str = ""
    description: str = ""
    country: str = ""
    city: str = ""
    tags: list[str] = field(default_factory=list)
    note: str = ""
    profile: dict = field(default_factory=dict)  # language, business_type, address, product_categories, product_names
    contacts: list[ContactDraft] = field(default_factory=list)

    # ---------------------------------------------------------------- derived
    def contacts_of(self, kind: str) -> list[ContactDraft]:
        return [c for c in self.contacts if c.kind == kind]

    @property
    def website(self) -> ContactDraft | None:
        return next(iter(self.contacts_of(ContactKind.WEBSITE)), None)

    @property
    def instagram(self) -> ContactDraft | None:
        return next(iter(self.contacts_of(ContactKind.INSTAGRAM)), None)

    def identifiers(self) -> list[tuple[str, str]]:
        """(kind, normalized) pairs that identify this business."""
        seen: list[tuple[str, str]] = []
        for c in self.contacts:
            pair = (c.kind, c.normalized)
            if c.kind in IDENTIFIER_KINDS and c.normalized and pair not in seen:
                seen.append(pair)
        return seen

    @property
    def has_content(self) -> bool:
        return bool(self.business_name or self.identifiers())

    # ---------------------------------------------------------------- (de)serialisation for DiscoveryJobRow
    def to_payload(self) -> dict:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Mapping) -> "LeadDraft":
        return cls(
            business_name=payload.get("business_name", ""),
            category=payload.get("category", ""),
            description=payload.get("description", ""),
            country=payload.get("country", ""),
            city=payload.get("city", ""),
            tags=list(payload.get("tags", [])),
            note=payload.get("note", ""),
            profile=dict(payload.get("profile", {})),
            contacts=[ContactDraft.from_dict(c) for c in payload.get("contacts", [])],
        )


class FieldErrors(list):
    """A list of ``{"field", "code", "message"}`` dicts."""

    def add(self, field_name: str, code: str, message: str) -> None:
        self.append({"field": field_name, "code": code, "message": message})


# --------------------------------------------------------------------------- per-kind normalisation


def normalize_contact(kind: str, raw: str) -> tuple[str, str]:
    """(value, normalized) for one contact value. Raises ``NormalizationError``."""
    if kind == ContactKind.PHONE or kind == ContactKind.WHATSAPP:
        ref = nz.normalize_phone(raw)
        return ref.normalized, ref.normalized
    if kind == ContactKind.EMAIL:
        address = nz.normalize_email(raw)
        return address, address
    if kind == ContactKind.WEBSITE:
        clean = nz.clean_url(raw)
        return clean.url, clean.identity
    if kind == ContactKind.INSTAGRAM:
        ref = nz.parse_instagram(raw)
        return ref.url, ref.handle
    if kind == ContactKind.TELEGRAM:
        handle, key = nz.parse_handle(raw, ("t.me", "telegram.me", "telegram.dog"), "تلگرام")
        return f"https://t.me/{handle}", key
    if kind == ContactKind.EITAA:
        handle, key = nz.parse_handle(raw, ("eitaa.com",), "ایتا")
        return f"https://eitaa.com/{handle}", key
    if kind == ContactKind.BALE:
        handle, key = nz.parse_handle(raw, ("ble.ir", "bale.ai"), "بله")
        return f"https://ble.ir/{handle}", key
    if kind == ContactKind.RUBIKA:
        handle, key = nz.parse_handle(raw, ("rubika.ir",), "روبیکا")
        return f"https://rubika.ir/{handle}", key
    if kind in (ContactKind.LINKEDIN, ContactKind.CONTACT_FORM):
        clean = nz.clean_url(raw)
        return clean.url, clean.identity
    value = nz.normalize_text(raw)[:500]
    if not value:
        raise nz.NormalizationError("empty_value", "مقدار خالی است.")
    return value, ""


def _is_instagram_url(text: str) -> bool:
    return bool(re.search(r"(^|//|\.)(instagram\.com|instagr\.am)(/|$)", text.strip(), re.I))


# --------------------------------------------------------------------------- the builder


def build_draft(
    raw: Mapping, *, source_ref: str = "manual", default_country: str = "", default_city: str = ""
) -> tuple[LeadDraft, FieldErrors]:
    """Validate and normalise ``raw`` (field name -> value). Returns the draft and any errors.

    A draft with errors must not be saved. ``raw`` may use these keys: business_name, website,
    instagram, phone, email, whatsapp, telegram, category, description, country, city, tags, note,
    language, business_type, address, product_categories, product_names.
    """
    errors = FieldErrors()
    draft = LeadDraft()

    def text_field(key: str, multiline: bool = False) -> str:
        value = nz.normalize_text(_as_text(raw.get(key)), multiline=multiline)
        limit = LIMITS.get(key)
        if limit and len(value) > limit:
            errors.add(key, "too_long", f"«{FIELD_LABELS.get(key, key)}» از {limit} نویسه بلندتر است.")
            return value[:limit]
        return value

    draft.business_name = text_field("business_name")
    draft.category = text_field("category")
    draft.description = text_field("description", multiline=True)
    draft.city = text_field("city") or nz.normalize_text(default_city)
    draft.note = text_field("note", multiline=True)

    # country
    try:
        draft.country = nz.normalize_country(_as_text(raw.get("country"))) or default_country
    except nz.NormalizationError as exc:
        errors.add("country", exc.code, exc.message)

    contacts: list[ContactDraft] = []

    def add_contact(kind: str, field_name: str, value: str) -> None:
        try:
            normalized_value, key = normalize_contact(kind, value)
        except nz.NormalizationError as exc:
            errors.add(field_name, exc.code, f"{FIELD_LABELS.get(field_name, field_name)}: {exc.message}")
            return
        if any(c.kind == kind and c.normalized == key for c in contacts):
            return  # the same value twice in one row
        contacts.append(ContactDraft(kind=kind, value=normalized_value, normalized=key, source_ref=source_ref))

    website_raw = nz.normalize_text(_as_text(raw.get("website")))
    instagram_raw = nz.normalize_text(_as_text(raw.get("instagram")))
    if website_raw and _is_instagram_url(website_raw):
        # someone pasted the Instagram page into the website box: file it where it belongs
        if not instagram_raw:
            instagram_raw, website_raw = website_raw, ""
        else:
            errors.add("website", "website_is_instagram", "در خانهٔ وب‌سایت لینکِ اینستاگرام گذاشته شده؛ آن را در خانهٔ اینستاگرام بگذارید.")
            website_raw = ""
    if website_raw:
        add_contact(ContactKind.WEBSITE, "website", website_raw)
    if instagram_raw:
        add_contact(ContactKind.INSTAGRAM, "instagram", instagram_raw)
    for value in nz.split_multi(raw.get("phone")):
        add_contact(ContactKind.PHONE, "phone", value)
    for value in nz.split_multi(raw.get("email")):
        add_contact(ContactKind.EMAIL, "email", value)
    for value in nz.split_multi(raw.get("whatsapp")):
        add_contact(ContactKind.WHATSAPP, "whatsapp", value)
    for value in nz.split_multi(raw.get("telegram")):
        add_contact(ContactKind.TELEGRAM, "telegram", value)
    draft.contacts = contacts

    # tags
    tags: list[str] = []
    keys: set[str] = set()
    for tag in nz.split_multi(raw.get("tags")):
        name = nz.normalize_text(tag)[:50]
        key = nz.search_key(name)
        if name and key not in keys:
            keys.add(key)
            tags.append(name)
    if len(tags) > MAX_TAGS:
        errors.add("tags", "too_many_tags", f"حداکثر {MAX_TAGS} برچسب مجاز است.")
        tags = tags[:MAX_TAGS]
    draft.tags = tags

    # profile
    profile: dict = {}
    language = nz.normalize_text(_as_text(raw.get("language"))).lower()
    if language:
        if re.fullmatch(r"[a-z]{2,3}", language):
            profile["language"] = language
        else:
            errors.add("language", "invalid_language", "زبان باید کد کوتاهی مثل fa یا en باشد.")
    business_type = nz.normalize_text(_as_text(raw.get("business_type")))
    if business_type:
        resolved = _resolve_choice(BusinessType, business_type)
        if resolved:
            profile["business_type"] = resolved
        else:
            errors.add("business_type", "invalid_business_type", f"نوعِ کسب‌وکارِ «{business_type[:30]}» شناخته نشد.")
    address = text_field("address")
    if address:
        profile["address"] = address
    for key in ("product_categories", "product_names"):
        values = [nz.normalize_text(v)[:120] for v in nz.split_multi(raw.get(key))]
        values = [v for v in values if v]
        if values:
            profile[key] = values[:50]
    draft.profile = profile

    if not draft.has_content:
        # only report this when nothing else is wrong, otherwise the real problem is hidden behind it
        if not errors:
            errors.add("__row__", "empty_row", "هیچ‌کدام از «نام»، «وب‌سایت»، «اینستاگرام»، «تلفن» یا «ایمیل» پر نشده است.")
    return draft, errors


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value)


def _resolve_choice(choices, text: str) -> str | None:
    """Accept the stored key (``online_store``) or the Persian label."""
    key = nz.search_key(text)
    for value, label in choices.choices:
        if key in (nz.search_key(value), nz.search_key(label)):
            return value
    return None
