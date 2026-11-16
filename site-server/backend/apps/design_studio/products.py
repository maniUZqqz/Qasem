"""محصولاتِ فروشگاه ⇒ «عکسِ لحظه‌ای» (snapshot) برای کاتالوگ و ارائه.

نام، توضیح، قیمت و عکس‌ها همان‌طور که در فروشگاه ثبت شده‌اند برداشته می‌شوند (قیمت هرگز ساخته یا گرد نمی‌شود). سند یک نسخهٔ ثابت نگه می‌دارد تا
خروجی‌ها پایدار باشند؛ «به‌روزرسانیِ محصولات» دوباره از فروشگاه می‌خواند.
"""
from __future__ import annotations

import re

from . import typeset

MAX_PRODUCTS = 300
SHORT_LEN = 140


def _short(p) -> str:
    s = (p.short_description or "").strip()
    if s:
        return typeset.clean_text(s, 300)
    d = re.sub(r"\s+", " ", (p.description or "").strip())
    if len(d) <= SHORT_LEN:
        return d
    cut = d[:SHORT_LEN].rsplit(" ", 1)[0]
    return cut.rstrip(" ،,؛;:.") + "…"


def snapshot(store, ids: list[int] | None = None, *, only_available: bool = True, limit: int = MAX_PRODUCTS) -> list[dict]:
    """⇒ فهرستِ محصولات (ترتیب: دسته، شناسه). هر مورد: id، name، sku، short، desc، price، compare_at، currency، category، images[ref]، attrs، tags."""
    from apps.products.models import Product

    qs = Product.objects.filter(store=store).select_related("category").prefetch_related("images", "attributes")
    if ids:
        qs = qs.filter(pk__in=ids)
    if only_available:
        qs = qs.filter(is_available=True)
    out = []
    for p in qs.order_by("category__name", "id")[:limit]:
        imgs = sorted(p.images.all(), key=lambda i: (not i.is_main, i.order, i.pk))
        out.append({
            "id": p.pk, "name": p.name, "sku": p.sku or "", "short": _short(p), "desc": typeset.clean_text(p.description, 1500),
            "price": float(p.price) if p.price is not None else None, "compare_at": float(p.compare_at_price) if p.compare_at_price is not None else None,
            "currency": p.currency or "IRT", "category": p.category.name if p.category_id else "", "category_id": p.category_id or 0,
            "images": [f"product:{i.pk}" for i in imgs[:6] if i.image],
            "attrs": [[a.key, a.value] for a in p.attributes.all()[:12]], "tags": [str(t) for t in (p.tags or [])[:8]], "brand": p.brand or "",
        })
    if ids:                                          # به ترتیبِ خواستهٔ کاربر
        order = {pk: i for i, pk in enumerate(ids)}
        out.sort(key=lambda r: order.get(r["id"], 10**9))
    return out


def by_id(items: list[dict]) -> dict[int, dict]:
    return {int(p["id"]): p for p in items}


def distinct_images(items: list[dict], src) -> list[str]:
    """عکس‌های متمایزِ محصولات (هم‌محتواها یکی حساب می‌شوند) — برای لوک‌بوک."""
    seen, out = set(), []
    for p in items:
        for ref in p.get("images", [])[:1]:
            fp = src.fingerprint(ref) if src is not None else ref
            if fp and fp not in seen:
                seen.add(fp)
                out.append(ref)
    return out
