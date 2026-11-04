"""The «facts» the in-call assistant may use: who is calling, the products being discussed, and the call so far.

Only NM data, only for staff. Cost and profit are included for the marketer's own guidance; the system prompt forbids
repeating them to the customer (see notes.ASK_SYSTEM).
"""
from __future__ import annotations

from . import callerid, products
from .models import MobileCall


def build(user, number=None, product_ids=None, call_uid=None) -> dict:
    facts = {"caller": None, "products": [], "call": None}
    summary = {"caller": None, "products": []}
    if number:
        who = callerid.lookup(user, number)
        facts["caller"] = {"name": who.get("display"), "matches": [{"source": m["source"], "name": m.get("name"), "detail": m.get("detail")}
                                                                      for m in who.get("matches", [])[:5]],
                           "history": who.get("history")}
        summary["caller"] = who.get("display")
    if product_ids:
        rows = products.get_many(user, product_ids if isinstance(product_ids, list) else [product_ids])
        for p in rows:
            facts["products"].append({
                "id": p["id"], "name": p["name"], "price": p["price"], "currency": p["currency"],
                "available_stock": p["stock"]["available"], "stock_status": p["stock"]["status_label"],
                "cost": p["cost"] if p["cost"] is not None else "ثبت نشده",
                "unit_profit": p["unit_profit"] if p["unit_profit"] is not None else "ثبت نشده",
                "floor_price": p["floor_price"] if p["floor_price"] is not None else "ثبت نشده",
                "max_discount_percent": p["max_discount_percent"] if p["max_discount_percent"] is not None else "ثبت نشده",
                "short_description": p["short_description"],
                "attributes": p["attributes"][:5],
            })
            summary["products"].append({"id": p["id"], "name": p["name"], "price": p["price"], "available": p["stock"]["available"],
                                        "floor_price": p["floor_price"]})
    if call_uid:
        try:
            call = MobileCall.objects.filter(uid=call_uid).first()
        except Exception:  # noqa: BLE001
            call = None
        if call and call.transcript:
            facts["call"] = {"summary": call.summary, "transcript_tail": call.transcript[-1500:]}
    facts["summary_for_user"] = summary
    return facts
