"""Business-category presets for the map provider: a Persian label -> the OpenStreetMap tags that mean it.

Only tag keys and values that are in common use on OpenStreetMap (``shop=*`` and ``craft=*``). A value of ``"*"`` means
"any value of this key". Keys and values are validated against ``SAFE_TAG`` before they are put into a query, so a preset
can never smuggle anything into the query language.
"""
from __future__ import annotations

import re

SAFE_TAG = re.compile(r"^[a-z][a-z0-9_:]{0,40}$")

#: key, Persian label, [(osm key, osm value or "*")]
PRESETS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("clothes", "پوشاک و لباس", [("shop", "clothes"), ("shop", "boutique"), ("shop", "fashion")]),
    ("shoes", "کفش", [("shop", "shoes")]),
    ("bags", "کیف و چمدان", [("shop", "bag")]),
    ("cosmetics", "لوازم آرایشی و بهداشتی", [("shop", "cosmetics"), ("shop", "perfumery"), ("shop", "beauty")]),
    ("jewelry", "طلا و جواهر", [("shop", "jewelry")]),
    ("accessories", "زیورآلات، اکسسوری و ساعت", [("shop", "fashion_accessories"), ("shop", "watches")]),
    ("gifts", "هدیه و سوغات", [("shop", "gift"), ("shop", "souvenir")]),
    ("handicrafts", "صنایع‌دستی و هنری", [("shop", "art"), ("craft", "*")]),
    ("home", "لوازم خانه و دکوراسیون", [("shop", "houseware"), ("shop", "interior_decoration"), ("shop", "furniture"), ("shop", "lighting")]),
    ("kids", "لوازم کودک و اسباب‌بازی", [("shop", "toys"), ("shop", "baby_goods")]),
    ("electronics", "موبایل و لوازم الکترونیکی", [("shop", "mobile_phone"), ("shop", "electronics"), ("shop", "computer")]),
    ("books", "کتاب و لوازم‌التحریر", [("shop", "books"), ("shop", "stationery")]),
    ("sports", "ورزش و سفر", [("shop", "sports"), ("shop", "outdoor")]),
    ("carpet", "فرش و پارچه", [("shop", "carpet"), ("shop", "fabric"), ("shop", "curtain")]),
    ("flowers", "گل و گیاه", [("shop", "florist"), ("shop", "garden_centre")]),
]

_BY_KEY = {key: (label, tags) for key, label, tags in PRESETS}


def listing() -> list[dict]:
    return [{"key": key, "label": label, "tags": [f"{k}={v}" for k, v in tags]} for key, label, tags in PRESETS]


def label_of(key: str) -> str:
    return _BY_KEY[key][0] if key in _BY_KEY else ""


def tags_of(key: str) -> list[tuple[str, str]] | None:
    """The validated (key, value) pairs of a preset, or None when the key is not a preset."""
    if key not in _BY_KEY:
        return None
    pairs = _BY_KEY[key][1]
    for k, v in pairs:
        if not SAFE_TAG.match(k) or (v != "*" and not SAFE_TAG.match(v)):
            raise ValueError(f"unsafe tag in preset {key}: {k}={v}")
    return list(pairs)
