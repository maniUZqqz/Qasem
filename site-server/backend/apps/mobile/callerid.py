"""Caller ID from NM's OWN data only.

Sources (all read-only): store customers, sales prospects, website leads, Growth Engine leads (when that app is
installed), earlier calls / SMS through paired phones, and contacts the user chose to sync from the phone.
Messenger profiles come from `lookups` (owner-approved, guarded) and are merged in by the view.

Other NM apps can add a source: `callerid.register_source(fn)` with `fn(user, norm, key) -> list[dict]`.
"""
from __future__ import annotations

import logging

from django.apps import apps

from . import phone

logger = logging.getLogger(__name__)

_EXTRA_SOURCES = []

#: order decides which name is shown when several sources know the number
PRIORITY = ["customer", "prospect", "growth_lead", "lead", "synced_contact", "previous_call"]


def register_source(fn):
    if fn not in _EXTRA_SOURCES:
        _EXTRA_SOURCES.append(fn)
    return fn


def _same(raw, k) -> bool:
    return bool(raw) and phone.key(raw) == k


def _customers(user, norm, k):
    from apps.customers.models import Customer

    from .products import scope_stores

    out = []
    qs = Customer.objects.filter(store__in=scope_stores(user)).exclude(phone="").select_related("store")
    for c in qs.only("id", "name", "phone", "channel", "store__name", "updated_at").iterator(chunk_size=500):
        if _same(c.phone, k):
            out.append({"source": "customer", "name": c.name or f"مشتری {c.pk}", "detail": f"مشتری از کانالِ {c.channel}",
                        "store": c.store.name, "id": c.pk, "last_contact_at": c.updated_at})
    return out


def _prospects(user, norm, k):
    from apps.customers.outreach import Prospect

    from .products import scope_stores

    out = []
    for p in Prospect.objects.filter(store__in=scope_stores(user)).exclude(phone="").select_related("store").iterator(chunk_size=500):
        if _same(p.phone, k):
            name = p.company + (f" — {p.person}" if p.person else "")
            out.append({"source": "prospect", "name": name, "detail": f"سرنخِ فروش ({p.get_stage_display()})",
                        "store": p.store.name, "id": p.pk, "last_contact_at": p.last_contact_at})
    return out


def _website_leads(user, norm, k):
    from apps.marketing.models import Lead

    out = []
    for l in Lead.objects.exclude(phone="").only("id", "name", "phone", "business", "created_at").iterator(chunk_size=500):
        if _same(l.phone, k):
            out.append({"source": "lead", "name": l.name or l.business, "detail": "از فرمِ تماسِ وب‌سایت",
                        "store": "", "id": l.pk, "last_contact_at": l.created_at})
    return out


def _growth_leads(user, norm, k):
    """Growth Engine leads, READ-ONLY, only when the app is installed. Never written, never listed in bulk."""
    try:
        ContactPoint = next(m for m in apps.get_models() if m.__name__ == "ContactPoint" and m._meta.app_label.startswith("growth"))
    except StopIteration:
        return []
    out = []
    try:
        for cp in ContactPoint.objects.filter(kind="phone", normalized__endswith=k).select_related("lead")[:5]:
            out.append({"source": "growth_lead", "name": cp.lead.display_name, "detail": "لیدِ جذب مشتری",
                        "store": "", "id": cp.lead_id, "last_contact_at": None})
    except Exception:  # noqa: BLE001 - the foreign schema may change; this is optional
        logger.info("growth lead lookup unavailable", exc_info=True)
    return out


def _synced_contacts(user, norm, k):
    from .models import MobileContact

    return [{"source": "synced_contact", "name": c.name, "detail": "مخاطبِ همگام‌شده از گوشی", "store": "", "id": c.pk,
             "last_contact_at": None}
            for c in MobileContact.objects.filter(device__user=user, number__endswith=k)[:3]]


def _history(norm):
    from .models import MobileCall, SmsInbound, SmsMessage

    calls = MobileCall.objects.filter(number=norm)
    last = calls.order_by("-started_at").first()
    return {
        "calls": calls.count(),
        "sms_out": SmsMessage.objects.filter(to_number=norm).count(),
        "sms_in": SmsInbound.objects.filter(from_number=norm).count(),
        "last_call_at": last.started_at if last else None,
        "_last_name": (last.contact_name if last and last.contact_name else ""),
    }


def lookup(user, number) -> dict:
    norm = phone.normalize(number)
    k = phone.key(norm)
    matches = []
    if len(k) >= 7:
        for source in (_customers, _prospects, _growth_leads, _website_leads, _synced_contacts, *_EXTRA_SOURCES):
            try:
                matches.extend(source(user, norm, k))
            except Exception:  # noqa: BLE001
                logger.exception("caller id source %s failed", getattr(source, "__name__", source))
    hist = _history(norm) if norm else {"calls": 0, "sms_out": 0, "sms_in": 0, "last_call_at": None, "_last_name": ""}
    last_name = hist.pop("_last_name")
    if hist["calls"]:
        matches.append({"source": "previous_call", "name": last_name or "", "detail": f"{hist['calls']} تماسِ قبلی",
                        "store": "", "id": None, "last_contact_at": hist["last_call_at"]})
    if hist["sms_out"] or hist["sms_in"]:
        matches.append({"source": "previous_sms", "name": "", "detail": f"{hist['sms_out']} پیامکِ فرستاده، {hist['sms_in']} دریافتی",
                        "store": "", "id": None, "last_contact_at": None})
    display = None
    for src in PRIORITY:
        hit = next((m for m in matches if m["source"] == src and m.get("name")), None)
        if hit:
            display = hit["name"]
            break
    if display is None:
        hit = next((m for m in matches if m.get("name")), None)
        display = hit["name"] if hit else None
    return {"number": str(number), "normalized": norm, "display": display, "known": bool(matches), "matches": matches,
            "history": hist}


def display_for(user, number) -> str:
    return lookup(user, number).get("display") or ""
