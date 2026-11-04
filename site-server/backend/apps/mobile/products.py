"""Product lookup for the marketer on the phone: price, stock, cost, profit and the lowest price that is not a loss.

Nothing is invented. A number NM does not have is `None` (the phone shows «ثبت نشده»), never 0.
Cost / profit / floor go only to authenticated staff (the whole mobile API is staff-only).
"""
from __future__ import annotations

import math
from decimal import Decimal

from django.db.models import Q

from apps.stores import access
from apps.stores.models import Store

from . import phone
from .models import ProductPricing


def _num(value):
    """Decimal -> int when whole, else float, None stays None."""
    if value is None:
        return None
    d = Decimal(value)
    return int(d) if d == d.to_integral_value() else float(d)


def scope_stores(user):
    """Which stores this staff user may look into: superusers see every store, others their own/joined ones."""
    if getattr(user, "is_superuser", False):
        return Store.objects.all()
    return access.stores_for(user)


def normalize_query(text) -> str:
    return phone.clean_text(text)


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def term_variants(term: str) -> set:
    """The same search word as it may be stored: Latin or Persian digits, Persian or Arabic ی/ک."""
    base = phone.clean_text(term)
    fa = base.translate(_FA_DIGITS)
    out = set()
    for t in (base, fa):
        out.add(t)
        out.add(t.replace("ی", "ي").replace("ک", "ك"))
    return {t for t in out if t}


def floor_for(product, pricing) -> tuple:
    """(floor_price | None, basis). The floor is NEVER guessed: without a cost (or an owner override) it is unknown."""
    if pricing is not None and pricing.floor_price_override is not None:
        return math.ceil(pricing.floor_price_override), "owner_override"
    if product.cost_price is not None:
        extra = Decimal(pricing.extra_unit_cost or 0) if pricing is not None else Decimal(0)
        base = Decimal(product.cost_price) + extra
        margin = Decimal(pricing.min_margin_percent or 0) if pricing is not None else Decimal(0)
        return math.ceil(base * (Decimal(1) + margin / Decimal(100))), "cost_plus"
    return None, "unknown"


def serialize(product, pricing=None) -> dict:
    if pricing is None:
        pricing = getattr(product, "mobile_pricing", None)
    floor, basis = floor_for(product, pricing)
    price = Decimal(product.price) if product.price is not None else None
    max_amount = max_percent = None
    if floor is not None and price is not None and price > 0:
        amount = max(Decimal(0), price - Decimal(floor))
        max_amount = _num(amount)
        max_percent = round(float(amount / price * 100), 1)
    images = list(product.images.all()) if hasattr(product, "images") else []
    main = next((i for i in images if i.is_main), images[0] if images else None)
    return {
        "id": product.pk,
        "name": product.name,
        "sku": product.sku,
        "brand": product.brand,
        "store": {"id": product.store_id, "name": product.store.name},
        "currency": product.currency,
        "price": _num(product.price),
        "compare_at_price": _num(product.compare_at_price),
        "stock": {
            "available": product.available_quantity,
            "on_hand": product.stock_quantity,
            "reserved": product.reserved_quantity,
            "status": product.stock_status,
            "status_label": product.get_stock_status_display(),
        },
        "cost": _num(product.cost_price),
        "unit_profit": _num(product.unit_profit),
        "margin_percent": product.margin_percent,
        "floor_price": floor,
        "floor_basis": basis,
        "max_discount_percent": max_percent,
        "max_discount_amount": max_amount,
        "short_description": product.short_description or "",
        "attributes": [{"key": a.key, "value": a.value} for a in list(product.attributes.all())[:8]],
        "image_url": (main.image.url if main and main.image else None),
        "variants": [{"name": v.name, "price": _num(v.price_override), "available": v.available_quantity}
                     for v in list(product.variants.all())[:12]],
    }


def search(user, q: str, limit: int = 20) -> list[dict]:
    from apps.products.models import Product

    terms = normalize_query(q).split()
    qs = Product.objects.filter(store__in=scope_stores(user), is_available=True)
    for term in terms[:6]:
        cond = Q()
        for v in term_variants(term):
            cond |= (Q(name__icontains=v) | Q(sku__icontains=v) | Q(brand__icontains=v)
                     | Q(short_description__icontains=v) | Q(category__name__icontains=v))
        qs = qs.filter(cond)
    qs = qs.select_related("store", "mobile_pricing").prefetch_related("images", "attributes", "variants").distinct()[:max(1, min(limit, 50))]
    return [serialize(p) for p in qs]


def get_many(user, ids) -> list[dict]:
    from apps.products.models import Product

    qs = Product.objects.filter(pk__in=[int(i) for i in ids if str(i).isdigit()][:10], store__in=scope_stores(user))
    qs = qs.select_related("store", "mobile_pricing").prefetch_related("images", "attributes", "variants")
    return [serialize(p) for p in qs]


def set_pricing(user, product, data: dict) -> dict:
    """Panel edit: cost price, stock and the three floor inputs. Empty string / null clears a value."""
    def dec(name):
        v = data.get(name)
        if v is None or str(v).strip() == "":
            return None
        try:
            d = Decimal(str(phone.ascii_digits(v)).replace(",", "").strip())
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{name} عدد نیست") from exc
        if d < 0:
            raise ValueError(f"{name} منفی است")
        return d

    pricing, _ = ProductPricing.objects.get_or_create(product=product)
    for field in ("extra_unit_cost", "min_margin_percent", "floor_price_override"):
        if field in data:
            setattr(pricing, field, dec(field))
    if "note" in data:
        pricing.note = str(data.get("note") or "")[:300]
    pricing.updated_by = user
    pricing.save()
    changed = []
    if "cost_price" in data:
        product.cost_price = dec("cost_price")
        changed.append("cost_price")
    if "stock_quantity" in data:
        v = data.get("stock_quantity")
        if str(v).strip() != "":
            n = int(phone.ascii_digits(v))
            if n < 0:
                raise ValueError("موجودی منفی است")
            product.stock_quantity = n
            changed.append("stock_quantity")
    if changed:
        product.save(update_fields=changed + ["updated_at"])
    product.refresh_from_db()
    return serialize(product, pricing)
