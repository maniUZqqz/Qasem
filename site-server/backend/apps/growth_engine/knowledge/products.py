"""Which product a piece of knowledge (and a campaign) is about.

The growth engine started as NMarketing's own lead-finder. The owner also sells his own product «چغر» (Chagher) to gym owners and personal
trainers, so every knowledge item and every campaign now carries a ``product``: the AI writer and the templates only ever see the knowledge
of the campaign's product (a Chagher message never talks about posters and videos, an NM message never about workout plans).

The sender identity (name, company, phone, opt-out line) is still one set in «تنظیماتِ جذب مشتری»: change it there before a Chagher campaign.
"""
from __future__ import annotations

DEFAULT = "nm"
PRODUCTS = {
    "nm": {"label": "NMarketing (آپ‌مارکت)", "short": "NM"},
    "chagher": {"label": "چغر (دستیار هوش مصنوعیِ مربی‌ها)", "short": "چغر"},
}


def normalize(value) -> str:
    v = str(value or "").strip().lower()
    return v if v in PRODUCTS else DEFAULT


def valid(value) -> bool:
    return str(value or "").strip().lower() in PRODUCTS


def public() -> list[dict]:
    return [{"key": k, "label": v["label"], "short": v["short"]} for k, v in PRODUCTS.items()]


def of_seed_key(seed_key: str) -> str:
    return "chagher" if str(seed_key or "").startswith("chagher_") else DEFAULT
