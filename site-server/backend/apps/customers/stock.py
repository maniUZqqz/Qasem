"""Stock held, stock sold, stock given back.

Until this module existed `stock_quantity` was only ever *read*: the agent
refused to sell what the shop did not have, and then never wrote the sale
down. Two customers in the same minute could each buy the last one, and the
rule "availability comes from the database" ran on a number that had been
stale since the shop opened.

Three moments, three writes:

* **reserve** — the customer has been shown the payment details. The item is
  promised but not sold, so `stock_quantity` (what is physically on the shelf)
  stays put and `reserved_quantity` goes up. The shop owner's count still
  matches the box in the corner, which is why this is not a plain decrement.
* **apply** — the order is confirmed. It left the shelf: `stock_quantity` goes
  down and the reservation is given back at the same time.
* **release** — cancelled, or the customer never paid. The promise expires and
  `reserved_quantity` goes back down.

What the agent may sell is `available_quantity = stock_quantity -
reserved_quantity`, so a promise blocks the next customer exactly as a sale
would, and an abandoned basket stops blocking on its own.

Every transition is guarded by `Order.stock_state`, so a double click on
"confirm", a retried webhook, or an owner flipping the status in Django admin
and back cannot take the same item off the shelf twice.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.products.models import Product, ProductVariant

#: How long a customer has to pay before the goods go back on the shelf.
#: Long enough for a bank transfer at night, short enough that one abandoned
#: basket does not make the last item unsellable for a week.
RESERVATION_HOURS = 48


def _rows(order):
    """(model, id, quantity) for each line — the variant when there is one.

    Stock lives on the variant if the product has variants, and on the product
    otherwise, which is exactly how the agent checks it before selling.
    """
    for item in order.items.select_related("product", "variant").all():
        if item.variant_id:
            yield ProductVariant, item.variant_id, item.quantity
        else:
            yield Product, item.product_id, item.quantity


@transaction.atomic
def reserve(order) -> bool:
    """Promise the goods to this order. Returns False if already promised."""
    from .models import Order

    if order.stock_state in (Order.StockState.RESERVED, Order.StockState.APPLIED):
        return False
    for model, pk, quantity in _rows(order):
        model.objects.filter(pk=pk).update(
            reserved_quantity=F("reserved_quantity") + quantity
        )
    order.stock_state = Order.StockState.RESERVED
    order.reserved_until = timezone.now() + timedelta(hours=RESERVATION_HOURS)
    order.save(update_fields=["stock_state", "reserved_until", "updated_at"])
    return True


@transaction.atomic
def apply(order) -> bool:
    """The order is confirmed: take the goods off the shelf for good."""
    from .models import Order

    if order.stock_state == Order.StockState.APPLIED:
        return False
    was_reserved = order.stock_state == Order.StockState.RESERVED
    for model, pk, quantity in _rows(order):
        # `Greatest`-free floor: the column is unsigned, and a confirmation of
        # an order whose stock was edited down in the meantime must not throw.
        row = model.objects.filter(pk=pk).values("stock_quantity", "reserved_quantity").first()
        if row is None:
            continue
        update = {"stock_quantity": max(0, row["stock_quantity"] - quantity)}
        if was_reserved:
            update["reserved_quantity"] = max(0, row["reserved_quantity"] - quantity)
        model.objects.filter(pk=pk).update(**update)
    order.stock_state = Order.StockState.APPLIED
    order.reserved_until = None
    order.save(update_fields=["stock_state", "reserved_until", "updated_at"])
    return True


@transaction.atomic
def release(order) -> bool:
    """Cancelled or expired: the promise is off, the goods are sellable again.

    A confirmed order is never released — the item has already left the shop,
    and "cancelling" it would invent stock that is not there.
    """
    from .models import Order

    if order.stock_state != Order.StockState.RESERVED:
        return False
    for model, pk, quantity in _rows(order):
        row = model.objects.filter(pk=pk).values("reserved_quantity").first()
        if row is None:
            continue
        model.objects.filter(pk=pk).update(
            reserved_quantity=max(0, row["reserved_quantity"] - quantity)
        )
    order.stock_state = Order.StockState.RELEASED
    order.reserved_until = None
    order.save(update_fields=["stock_state", "reserved_until", "updated_at"])
    return True


def release_expired(now=None) -> int:
    """Give back every reservation whose deadline has passed. Returns the count.

    A scan rather than a per-order countdown: an eta task dies with the worker
    that holds it, and these workers restart routinely (see the note above
    CELERY_BEAT_SCHEDULE). A scan over rows survives anything restartable.
    """
    from .models import Order

    now = now or timezone.now()
    stale = Order.objects.filter(
        stock_state=Order.StockState.RESERVED, reserved_until__lt=now
    ).exclude(status=Order.Status.CONFIRMED)
    released = 0
    for order in stale:
        if release(order):
            released += 1
    return released
