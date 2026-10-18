"""Turning product, competitor and sales data into things to actually do.

§4 asks for "Recommendation قابل اجرا", and §5 asks for real profit rather than
revenue. Those are the same job: revenue tells a shop which product moves, and
only cost tells it which product is worth moving.

**Every suggestion here is derived from arithmetic, not from a model.** That is
deliberate. A recommendation a shop owner cannot audit is one they will follow
once, be burned by, and never trust again — so each one carries the numbers it
came from in `evidence`, and the reason names them. The model's turn comes
later, when there is a real shop with real months of data to reason about;
today the arithmetic is both honest and enough.

**What "unknown" means.** A product with no cost price is excluded from profit
work entirely rather than treated as free. Treating a missing cost as zero
reports the whole selling price as margin, which makes the worst product in the
shop look like the best one — the exact opposite of the decision §5 exists to
support.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Sold this many or fewer in the window and still sitting on stock → slow.
SLOW_MOVER_SALES = 1

#: Margin below this is worth flagging. Not a universal truth — a shop may
#: deliberately sell a loss-leader — so the wording asks rather than instructs.
THIN_MARGIN_PERCENT = 15.0

#: How far above the cheapest competitor before the gap is worth mentioning.
PRICE_GAP_PERCENT = 20.0

#: Every money value in this module's output, to the same two decimals the
#: model fields use.
_CENTS = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(value).quantize(_CENTS)


def profit_report(store, days: int = 30) -> dict:
    """Per-product revenue, real profit, and what is missing to compute it.

    The `missing_cost` list is as important as the numbers: a report that
    quietly covers 4 of a shop's 30 products, while looking complete, is worse
    than one that says so.
    """
    from apps.customers.models import Order, OrderItem
    from apps.products.models import Product

    since = timezone.now() - timedelta(days=max(1, min(365, days)))

    sold = (
        OrderItem.objects.filter(
            order__store=store,
            order__status=Order.Status.CONFIRMED,
            # The day the money was accepted, like every other sales figure.
            order__confirmed_at__gte=since,
        )
        .values("product_id")
        .annotate(
            units=Sum("quantity"),
            orders=Count("order_id", distinct=True),
            # What was actually charged, line by line. Today's list price ×
            # units was a guess that got worse with every price change and
            # every discount the agent gave: raise a price and last month's
            # profit rose with it.
            revenue=Sum(F("quantity") * F("unit_price")),
        )
    )
    sold_by_product = {row["product_id"]: row for row in sold}

    rows = []
    missing_cost = []
    for product in Product.objects.filter(store=store):
        stats = sold_by_product.get(product.pk, {})
        units = int(stats.get("units") or 0)
        # The database returns the sum of a multiplication without a scale,
        # so it has to be given one here: every other money value in the API
        # is "1000.00", and one field spelling it "1000" is the sort of thing
        # a caller parses once and then gets wrong.
        revenue = _money(stats.get("revenue") or 0)

        entry = {
            "product_id": product.pk,
            "name": product.name,
            "units": units,
            "orders": int(stats.get("orders") or 0),
            "price": str(product.price),
            "cost_price": str(product.cost_price) if product.cost_price is not None else None,
            "revenue": str(revenue),
            "stock": product.stock_quantity,
            "margin_percent": product.margin_percent,
        }
        if product.cost_price is None:
            entry["profit"] = None
            missing_cost.append(product.name)
        else:
            # Real money in minus real money out, not list price minus cost.
            entry["profit"] = str(_money(revenue - product.cost_price * units))
        rows.append(entry)

    known = [r for r in rows if r["profit"] is not None]
    total_revenue = _money(sum((Decimal(r["revenue"]) for r in rows), Decimal(0)))
    total_profit = _money(sum((Decimal(r["profit"]) for r in known), Decimal(0)))

    return {
        "days": days,
        "products": sorted(rows, key=lambda r: r["units"], reverse=True),
        "total_revenue": str(total_revenue),
        # None rather than a number when nothing has a cost: a total of zero
        # would read as "you made nothing".
        "total_profit": str(total_profit) if known else None,
        "profit_covers_products": len(known),
        "missing_cost": missing_cost,
        "best_sellers": [r["name"] for r in sorted(
            rows, key=lambda r: r["units"], reverse=True,
        )[:5] if r["units"]],
        "most_profitable": [r["name"] for r in sorted(
            known, key=lambda r: Decimal(r["profit"]), reverse=True,
        )[:5] if Decimal(r["profit"]) > 0],
    }


# ------------------------------------------------------------ suggestions


def _cheapest_competitor_price(product) -> tuple[int | None, str]:
    """Lowest observed competitor price for this product, and whose it was."""
    from .competitor_models import CompetitorProduct

    row = (
        CompetitorProduct.objects
        .filter(matches=product, price_toman__isnull=False)
        .select_related("competitor")
        .order_by("price_toman")
        .first()
    )
    if row is None:
        return None, ""
    return row.price_toman, row.competitor.name


def suggest(store, days: int = 30) -> list[dict]:
    """Candidate opportunities, newest analysis wins. Nothing is saved here.

    Returned as plain dicts so the caller decides what to persist — a
    suggestion the owner already dismissed must not come back, and that check
    belongs with the stored rows.
    """
    from apps.products.models import Product

    from .competitor_models import Opportunity

    report = profit_report(store, days)
    by_id = {r["product_id"]: r for r in report["products"]}
    found = []

    for product in Product.objects.filter(store=store):
        stats = by_id.get(product.pk, {})
        units = stats.get("units", 0)

        # ---- priced well above the cheapest competitor ---------------------
        rival_price, rival_name = _cheapest_competitor_price(product)
        if rival_price and product.price:
            gap = (float(product.price) - rival_price) / rival_price * 100
            if gap > PRICE_GAP_PERCENT:
                found.append({
                    "kind": Opportunity.Kind.PRICING,
                    "product": product,
                    "title": f"«{product.name}» گران‌تر از رقیب است",
                    "reason": (
                        f"قیمت شما {int(product.price):,} تومان است و ارزان‌ترین "
                        f"قیمتِ دیده‌شده نزد «{rival_name}» {rival_price:,} تومان — "
                        f"حدود {gap:.0f}٪ اختلاف."
                    ),
                    "action": "یا قیمت را بازبینی کنید، یا در محتوا بگویید چرا گران‌تر است.",
                    "evidence": {
                        "our_price": int(product.price),
                        "competitor_price": rival_price,
                        "competitor": rival_name,
                        "gap_percent": round(gap, 1),
                    },
                    "priority": 80,
                })

        # ---- thin margin --------------------------------------------------
        margin = product.margin_percent
        if margin is not None and margin < THIN_MARGIN_PERCENT and units:
            found.append({
                "kind": Opportunity.Kind.PRICING,
                "product": product,
                "title": f"سود «{product.name}» کم است",
                "reason": (
                    f"حاشیه‌ی سود {margin:.0f}٪ است و در {days} روز گذشته "
                    f"{units} عدد فروخته. یعنی فروش هست ولی چیزی نمی‌ماند."
                ),
                # Phrased as a question: a shop may be running a loss-leader on
                # purpose, and telling them they are wrong about their own
                # strategy is how a tool gets ignored.
                "action": "اگر عمدی نیست، قیمت یا قیمت تمام‌شده را بازبینی کنید.",
                "evidence": {"margin_percent": margin, "units": units},
                "priority": 70,
            })

        # ---- sitting stock ------------------------------------------------
        if product.stock_quantity > 0 and units <= SLOW_MOVER_SALES:
            found.append({
                "kind": Opportunity.Kind.CONTENT,
                "product": product,
                "title": f"«{product.name}» موجود است ولی نمی‌فروشد",
                "reason": (
                    f"{product.stock_quantity} عدد موجودی دارد و در {days} روز "
                    f"گذشته {units} عدد فروخته."
                ),
                "action": "یک پوستر یا ویدیوی کوتاه برایش بسازید و منتشر کنید.",
                "evidence": {"stock": product.stock_quantity, "units": units},
                "priority": 55,
            })

        # ---- best seller with no companion --------------------------------
        if units >= 3:
            others = Product.objects.filter(store=store).exclude(pk=product.pk).count()
            if others:
                found.append({
                    "kind": Opportunity.Kind.BUNDLE,
                    "product": product,
                    "title": f"«{product.name}» پرفروش است — کنارش چه بفروشیم؟",
                    "reason": f"در {days} روز گذشته {units} عدد فروخته.",
                    "action": "یک محصول مکمل به ایجنت فروش معرفی کنید تا پیشنهاد بدهد.",
                    "evidence": {"units": units},
                    "priority": 60,
                })

    # ---- shop-wide: costs missing, so profit is unknowable -----------------
    if report["missing_cost"]:
        names = "، ".join(report["missing_cost"][:4])
        more = len(report["missing_cost"]) - 4
        found.append({
            "kind": Opportunity.Kind.INVENTORY,
            "product": None,
            "title": "قیمت تمام‌شده‌ی چند محصول وارد نشده",
            "reason": (
                f"بدون آن، سود واقعی قابل محاسبه نیست: {names}"
                + (f" و {more} مورد دیگر" if more > 0 else "")
            ),
            "action": "قیمت خرید هر محصول را در صفحه‌ی همان محصول وارد کنید.",
            "evidence": {"missing": report["missing_cost"]},
            # Highest priority: every other profit number depends on it.
            "priority": 90,
        })

    return found


def refresh(store, days: int = 30) -> dict:
    """Recompute suggestions and store the new ones.

    Rules that make this safe to run repeatedly:

    * A suggestion the owner **dismissed** is never recreated. That is the
      whole reason these are rows rather than a computed list.
    * An open suggestion that still applies is updated in place, so its age and
      any note stay attached.
    * An open suggestion that no longer applies is closed as done — the shop
      fixed it, and leaving it open would make the list a graveyard.
    """
    from .competitor_models import Opportunity

    candidates = suggest(store, days)
    seen_keys = set()
    created = 0
    updated = 0

    for candidate in candidates:
        key = (candidate["kind"], candidate["product"].pk if candidate["product"] else None,
               candidate["title"])
        seen_keys.add(key)

        existing = Opportunity.objects.filter(
            store=store, kind=candidate["kind"],
            product=candidate["product"], title=candidate["title"],
        ).first()

        if existing is None:
            Opportunity.objects.create(
                store=store,
                product=candidate["product"],
                kind=candidate["kind"],
                title=candidate["title"],
                reason=candidate["reason"],
                action=candidate["action"],
                evidence=candidate["evidence"],
                priority=candidate["priority"],
            )
            created += 1
            continue

        if existing.state == Opportunity.State.DISMISSED:
            continue  # the owner said no; asking again is nagging

        existing.reason = candidate["reason"]
        existing.evidence = candidate["evidence"]
        existing.priority = candidate["priority"]
        existing.state = Opportunity.State.OPEN
        existing.save(update_fields=["reason", "evidence", "priority", "state", "updated_at"])
        updated += 1

    stale = 0
    for row in Opportunity.objects.filter(store=store, state=Opportunity.State.OPEN):
        key = (row.kind, row.product_id, row.title)
        if key not in seen_keys:
            row.state = Opportunity.State.DONE
            row.save(update_fields=["state", "updated_at"])
            stale += 1

    return {"created": created, "updated": updated, "resolved": stale}
