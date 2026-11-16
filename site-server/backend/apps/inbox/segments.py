"""Segments: a saved question about contacts («مشتریِ دائمی»).

A segment is `{"match": "all"|"any", "rules": [{"field", "op", "value"}]}`.
It is evaluated in Python over a batch of pre-computed facts rather than
translated to SQL: tags and per-channel presence live in JSON lists / link
tables, SQLite cannot `contains` a JSON array, and a store's contact list is
thousands of rows, not millions. One evaluator also means the preview count the
owner sees and the recipient list a broadcast sends to cannot disagree.
"""
from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from .models import Contact, ContactLink, Segment

#: field -> (kind, label). `kind` decides which operators make sense.
FIELDS: dict[str, tuple[str, str]] = {
    "tag": ("tags", "برچسب"),
    "channel": ("set", "کانال"),
    "orders_count": ("num", "تعداد خرید"),
    "total_spent": ("num", "جمع خرید (ریال)"),
    "last_purchase_days": ("num", "روز از آخرین خرید"),
    "last_activity_days": ("num", "روز از آخرین فعالیت"),
    "first_seen_days": ("num", "روز از اولین پیام"),
    "has_phone": ("bool", "شمارهٔ موبایل دارد"),
    "opted_out": ("bool", "از پیام‌های تبلیغاتی خارج شده"),
    "name_contains": ("text", "نام شامل"),
    "source": ("text", "منبع"),
}

OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "has", "not_has", "is_true", "is_false", "contains"}

#: Segments every store gets without lifting a finger.
BUILTIN = [
    ("loyal", "مشتریِ دائمی", "۳ خرید تأییدشده یا بیشتر",
     {"match": "all", "rules": [{"field": "orders_count", "op": "gte", "value": 3}]}),
    ("recent_buyer", "خریدار اخیر", "در ۳۰ روز گذشته خرید کرده",
     {"match": "all", "rules": [{"field": "last_purchase_days", "op": "lte", "value": 30}]}),
    ("new", "تازه‌وارد", "در ۷ روز گذشته اولین پیامش را فرستاده",
     {"match": "all", "rules": [{"field": "first_seen_days", "op": "lte", "value": 7}]}),
    ("lead", "بدون خرید", "هنوز خریدی ندارد",
     {"match": "all", "rules": [{"field": "orders_count", "op": "eq", "value": 0}]}),
    ("dormant", "غیرفعال", "۶۰ روز یا بیشتر پیامی نداده",
     {"match": "all", "rules": [{"field": "last_activity_days", "op": "gte", "value": 60}]}),
    ("churn_risk", "در خطر ریزش", "خرید داشته ولی ۹۰ روز یا بیشتر از آخرین خریدش گذشته",
     {"match": "all", "rules": [
         {"field": "orders_count", "op": "gte", "value": 1},
         {"field": "last_purchase_days", "op": "gte", "value": 90}]}),
]


class RuleError(ValueError):
    """The rules are not something we can evaluate. Message is Persian."""


def ensure_builtin(store) -> list[Segment]:
    out = []
    for key, name, desc, rules in BUILTIN:
        seg, _ = Segment.objects.get_or_create(
            store=store, builtin_key=key,
            defaults={"name": name, "description": desc, "rules": rules},
        )
        out.append(seg)
    return out


def validate(rules: dict) -> dict:
    """Clean a rules document or raise `RuleError`."""
    if not isinstance(rules, dict):
        raise RuleError("قواعد بخش باید یک ساختار معتبر باشد.")
    match = rules.get("match", "all")
    if match not in ("all", "any"):
        raise RuleError("نوع ترکیب قواعد باید «همه» یا «هرکدام» باشد.")
    cleaned = []
    for rule in rules.get("rules") or []:
        field, op = rule.get("field"), rule.get("op")
        if field not in FIELDS:
            raise RuleError(f"فیلد «{field}» شناخته‌شده نیست.")
        if op not in OPS:
            raise RuleError(f"عملگر «{op}» شناخته‌شده نیست.")
        cleaned.append({"field": field, "op": op, "value": rule.get("value")})
    if len(cleaned) > 12:
        raise RuleError("حداکثر ۱۲ قاعده در یک بخش مجاز است.")
    return {"match": match, "rules": cleaned}


def _days_since(moment: datetime | None, now: datetime):
    if moment is None:
        return None
    return max(0, (now - moment).days)


def facts_for(contacts: list[Contact], now: datetime | None = None) -> dict[int, dict]:
    """Everything a rule can ask, per contact, in one batch of queries."""
    now = now or timezone.now()
    channels: dict[int, set[str]] = {c.pk: set() for c in contacts}
    ids = [c.pk for c in contacts]
    for contact_id, channel in ContactLink.objects.filter(contact_id__in=ids).values_list(
        "contact_id", "customer__conversations__channel",
    ):
        if channel:
            channels[contact_id].add(channel.upper())
    for contact_id, channel in ContactLink.objects.filter(contact_id__in=ids).values_list(
        "contact_id", "customer__channel",
    ):
        if channel:
            channels[contact_id].add(channel.upper())
    out = {}
    for c in contacts:
        out[c.pk] = {
            "tag": {str(t).lower() for t in (c.tags or [])},
            "channel": channels.get(c.pk, set()),
            "orders_count": c.orders_count,
            "total_spent": float(c.total_spent or 0),
            "last_purchase_days": _days_since(c.last_purchase_at, now),
            "last_activity_days": _days_since(c.last_activity_at, now),
            "first_seen_days": _days_since(c.first_seen_at, now),
            "has_phone": bool(c.phone),
            "opted_out": bool((c.opt_out or {}).get("ALL")),
            "name_contains": (c.name or "").lower(),
            "source": (c.source or "").lower(),
        }
    return out


def _truthy(value) -> bool:
    return value in (None, True, "true", "True", 1, "1")


def _match_rule(rule: dict, facts: dict) -> bool:
    field, op, want = rule["field"], rule["op"], rule.get("value")
    have = facts[field]
    kind, label = FIELDS[field]
    if kind in ("tags", "set"):
        value = str(want or "").lower() if kind == "tags" else str(want or "").upper()
        if op in ("has", "eq"):
            return value in have
        if op in ("not_has", "neq"):
            return value not in have
        raise RuleError(f"عملگر «{op}» برای «{label}» معنی ندارد.")
    if kind == "bool":
        if op == "is_true":
            return bool(have)
        if op == "is_false":
            return not have
        if op == "eq":
            return bool(have) == _truthy(want)
        if op == "neq":
            return bool(have) != _truthy(want)
        raise RuleError(f"عملگر «{op}» برای «{label}» معنی ندارد.")
    if kind == "text":
        value = str(want or "").lower()
        if op in ("contains", "has"):
            return value in have
        if op == "not_has":
            return value not in have
        if op == "eq":
            return value == have
        if op == "neq":
            return value != have
        raise RuleError(f"عملگر «{op}» برای «{label}» معنی ندارد.")
    # numbers
    if have is None:
        # "never bought" is neither "bought recently" nor "bought long ago" -
        # except that it IS "at least N days since", which is how dormant and
        # churn segments are written.
        return op in ("gte", "gt") and field.endswith("_days") and field != "first_seen_days"
    try:
        number = float(want)
    except (TypeError, ValueError):
        raise RuleError(f"مقدار «{label}» باید عدد باشد.") from None
    return {
        "eq": have == number, "neq": have != number, "gt": have > number,
        "gte": have >= number, "lt": have < number, "lte": have <= number,
    }.get(op, False)


def matches(rules: dict, facts: dict) -> bool:
    rule_list = rules.get("rules") or []
    if not rule_list:
        return True
    results = [_match_rule(r, facts) for r in rule_list]
    return all(results) if rules.get("match", "all") == "all" else any(results)


def contacts_in(store, rules: dict, *, include_test: bool = False) -> list[Contact]:
    """The contacts this question selects, newest activity first."""
    rules = validate(rules or {})
    qs = Contact.objects.filter(store=store)
    if not include_test:
        qs = qs.filter(is_test=False)
    contacts = list(qs)
    facts = facts_for(contacts)
    return [c for c in contacts if matches(rules, facts[c.pk])]


def count_in(store, rules: dict, **kw) -> int:
    return len(contacts_in(store, rules, **kw))
