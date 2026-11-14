"""Is this product a digital service rather than a physical good?

Marketplaces such as Digikala, Basalam and Torob sell boxes. A software plan or
an online service has no box, no stock count and no shelf: the owner who types
«9999» in the stock field is saying «unlimited», not «I own 9999 of these».
Treating such a product like a physical one produces advice that is not just
useless but embarrassing («9999 عدد موجودی دارد و نمی‌فروشد», or a competitor
list full of wooden bookshelves for a «library of exercises»).

The signal is deliberately conservative and uses only what the shop itself
wrote: the «unlimited» stock sentinel on the product, or the shop's own
shipping policy saying the service is digital.
"""
from __future__ import annotations

from apps.common.fatext import normalize

#: stock this large is an "unlimited" marker, not a count of boxes
UNLIMITED_STOCK = 9999

_DIGITAL_HINTS = ("سرویس دیجیتال", "ارسال فیزیکی ندارد", "ارسال فیزیکی نداره", "کالای دیجیتال", "محصول دیجیتال")


def store_is_digital(store) -> bool:
    """The shop's own shipping policy says it ships nothing physical."""
    from apps.stores.models import StoreProfile

    # a fresh read, not `store.profile`: a cached profile can be older than the
    # owner's last edit
    policy = normalize(
        StoreProfile.objects.filter(store_id=store.pk).values_list("shipping_policy", flat=True).first() or ""
    )
    return any(normalize(hint) in policy for hint in _DIGITAL_HINTS)


def is_digital(product, store_digital: bool | None = None) -> bool:
    """True for an unlimited-stock marker or a digital-only shop."""
    if (product.stock_quantity or 0) >= UNLIMITED_STOCK:
        return True
    if store_digital is None:
        store_digital = store_is_digital(product.store)
    return store_digital
