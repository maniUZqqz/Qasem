"""The product knowledge: listing, creating, editing, deleting, putting a default back."""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.services.editing import ValidationFailed

from ..models import KnowledgeItem
from . import seed_data

MAX_BODY = 3000
PRICE_HINT = "قیمت را وارد کنید"


def _url(value: str, errors: list[dict]) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or len(value) > 500:
        errors.append({"field": "url", "code": "invalid_url", "message": "نشانی باید با http:// یا https:// شروع شود."})
    return value


def validate(data: Mapping, *, partial: bool = False) -> dict:
    errors: list[dict] = []
    clean: dict = {}
    if "section" in data or not partial:
        if data.get("section") not in KnowledgeItem.Section.values:
            errors.append({"field": "section", "code": "invalid", "message": "بخش را از فهرست انتخاب کنید."})
        else:
            clean["section"] = data["section"]
    if "title" in data or not partial:
        title = nz.normalize_text(str(data.get("title") or ""))
        if not title:
            errors.append({"field": "title", "code": "required", "message": "عنوان را بنویسید."})
        elif len(title) > 200:
            errors.append({"field": "title", "code": "too_long", "message": "عنوان از ۲۰۰ نویسه بلندتر است."})
        clean["title"] = title
    if "body" in data:
        body = nz.normalize_text(str(data.get("body") or ""), multiline=True)
        if len(body) > MAX_BODY:
            errors.append({"field": "body", "code": "too_long", "message": f"متن از {MAX_BODY} نویسه بلندتر است."})
        clean["body"] = body
    if "url" in data:
        clean["url"] = _url(str(data.get("url") or ""), errors)
    if "note" in data:
        note = nz.normalize_text(str(data.get("note") or ""))
        if len(note) > 400:
            errors.append({"field": "note", "code": "too_long", "message": "یادداشت از ۴۰۰ نویسه بلندتر است."})
        clean["note"] = note
    if "sort_order" in data:
        try:
            clean["sort_order"] = max(0, min(30000, int(data["sort_order"])))
        except (TypeError, ValueError):
            errors.append({"field": "sort_order", "code": "invalid_number", "message": "ترتیب باید عدد باشد."})
    if "is_active" in data:
        clean["is_active"] = bool(data["is_active"])
    if not partial and clean.get("section") != KnowledgeItem.Section.PRICE and not clean.get("body"):
        errors.append({"field": "body", "code": "required", "message": "متن را بنویسید (فقط «قیمت» می‌تواند خالی بماند تا عددِ واقعی را بنویسید)."})
    if errors:
        raise ValidationFailed(errors)
    return clean


def item_json(item: KnowledgeItem) -> dict:
    return {
        "id": item.pk, "section": item.section, "section_label": item.get_section_display(), "title": item.title, "body": item.body, "url": item.url,
        "sort_order": item.sort_order, "is_active": item.is_active, "note": item.note, "is_default": bool(item.seed_key), "seed_key": item.seed_key or "",
        "needs_value": item.needs_value, "needs_value_hint": PRICE_HINT if item.needs_value else "",
        "updated_at": item.updated_at,
    }


def listing() -> dict:
    items = list(KnowledgeItem.objects.all())
    order = {s: i for i, s in enumerate(seed_data.SECTION_ORDER)}
    items.sort(key=lambda i: (order.get(i.section, 99), i.sort_order, i.pk))
    sections = [{"key": value, "label": label} for value, label in KnowledgeItem.Section.choices]
    missing = [k for k, *_ in seed_data.KNOWLEDGE if not KnowledgeItem.objects.filter(seed_key=k).exists()]
    return {
        "sections": sections, "items": [item_json(i) for i in items],
        "summary": {
            "total": len(items), "active": sum(1 for i in items if i.is_active),
            "prices_missing": sum(1 for i in items if i.needs_value and i.is_active), "defaults_missing": len(missing),
        },
    }


def create(data: Mapping, actor) -> KnowledgeItem:
    clean = validate(data)
    return KnowledgeItem.objects.create(updated_by=actor if getattr(actor, "is_authenticated", False) else None, **clean)


def update(item: KnowledgeItem, data: Mapping, actor) -> KnowledgeItem:
    clean = validate(data, partial=True)
    if clean.get("section") and clean["section"] != item.section and item.seed_key:
        raise ValidationFailed([{"field": "section", "code": "default_item", "message": "بخشِ موردهای پیش‌فرض عوض نمی‌شود؛ یک مورد تازه بسازید."}])
    for key, value in clean.items():
        setattr(item, key, value)
    item.updated_by = actor if getattr(actor, "is_authenticated", False) else None
    item.save()
    return item


def reset_to_default(item: KnowledgeItem, actor) -> KnowledgeItem:
    """Put a default item's title / text / address back to the shipped ones (an edited price goes back to empty)."""
    for seed_key, section, title, body, url, active, note, order in seed_data.KNOWLEDGE:
        if seed_key == item.seed_key:
            item.title, item.body, item.url, item.note = title, body, url, note
            item.updated_by = actor if getattr(actor, "is_authenticated", False) else None
            item.save()
            return item
    raise ValidationFailed([{"field": "item", "code": "not_default", "message": "این مورد پیش‌فرض نیست."}])
