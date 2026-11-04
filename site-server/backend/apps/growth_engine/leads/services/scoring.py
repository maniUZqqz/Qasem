"""A plain, rule-based «امتیازِ دسترسی» (reachability score) of a lead. No AI, no guessing.

It answers one question: *how well can we actually reach this business with what we have stored?* Each reachable way adds points
and every point is explained, so a person can see why a lead scores what it does:

    mobile number ...... 25   (an SMS / a WhatsApp chat / a call can reach it)
    e-mail ............. 25   (an e-mail can reach it; a placeholder address does not count)
    website ............ 20   (the site can be read and its contact page found)
    contact form ....... 10   (the site's own form was found)
    Instagram .......... 10   (stored as given; nothing is fetched from Instagram)
    another messenger .. 5    (Telegram / Eitaa / Bale / Rubika)
    business name ...... 3    (a message can be personal)
    city ............... 2

The points add up to exactly 100. A lead on the do-not-contact list, or archived, scores 0 with that reason. It says nothing about whether
the business is a *good customer*; that needs knowledge we do not have.
"""
from __future__ import annotations

from collections.abc import Iterable

from apps.growth_engine.core import normalization as nz

from ..choices import ContactKind

POINTS = {
    "mobile": (25, "شمارهٔ موبایل دارد (پیامک، واتساپ و تماس ممکن است)"),
    "email": (25, "ایمیلِ معتبر دارد"),
    "website": (20, "وب‌سایت دارد (راهِ تماس از خودِ سایت خوانده می‌شود)"),
    "contact_form": (10, "فرمِ تماسِ سایتش پیدا شده"),
    "instagram": (10, "پیجِ اینستاگرام دارد"),
    "messenger": (5, "پیام‌رسانِ دیگری دارد (تلگرام، ایتا، بله یا روبیکا)"),
    "name": (3, "نامِ کسب‌وکار معلوم است (پیام شخصی می‌شود)"),
    "city": (2, "شهر معلوم است"),
}
LABELS = {"high": "بالا", "medium": "متوسط", "low": "کم"}
MESSENGERS = (ContactKind.TELEGRAM, ContactKind.EITAA, ContactKind.BALE, ContactKind.RUBIKA)


def _is_mobile(value: str) -> bool:
    try:
        return nz.normalize_phone(value).kind == "mobile"
    except nz.NormalizationError:
        return False


def level(value: int) -> str:
    return "high" if value >= 70 else "medium" if value >= 40 else "low"


def score(lead, contacts: Iterable, *, suppressed: bool = False) -> dict:
    """``{"value": 0-100, "level": "high|medium|low", "label": "بالا|متوسط|کم", "reasons": [{"text", "points"}]}``."""
    if suppressed:
        return {"value": 0, "level": "low", "label": LABELS["low"], "reasons": [{"text": "در فهرستِ «تماس نگیر» است؛ نباید پیام بگیرد", "points": 0}]}
    if getattr(lead, "is_archived", False):
        return {"value": 0, "level": "low", "label": LABELS["low"], "reasons": [{"text": "بایگانی شده است", "points": 0}]}
    contacts = list(contacts)
    kinds = {c.kind for c in contacts}
    have = {
        "mobile": any(c.kind == ContactKind.PHONE and _is_mobile(c.value) for c in contacts),
        "email": any(c.kind == ContactKind.EMAIL and c.value and not nz.is_placeholder_email(c.value) for c in contacts),
        "website": bool(lead.website),
        "contact_form": ContactKind.CONTACT_FORM in kinds,
        "instagram": bool(lead.instagram_url),
        "messenger": any(kind in kinds for kind in MESSENGERS),
        "name": bool((lead.business_name or "").strip()),
        "city": bool((lead.city or "").strip()),
    }
    reasons = [{"text": POINTS[key][1], "points": POINTS[key][0]} for key, ok in have.items() if ok]
    value = min(100, sum(r["points"] for r in reasons))
    if not reasons:
        reasons = [{"text": "هیچ راهِ تماسی ثبت نشده", "points": 0}]
    return {"value": value, "level": level(value), "label": LABELS[level(value)], "reasons": reasons}
