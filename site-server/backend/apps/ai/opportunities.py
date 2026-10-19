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


def suggest(store, days: int = 30, channel_data: dict | None = None) -> list[dict]:
    """Candidate opportunities, newest analysis wins. Nothing is saved here.

    Returned as plain dicts so the caller decides what to persist — a
    suggestion the owner already dismissed must not come back, and that check
    belongs with the stored rows.

    ``channel_data`` is ``services.research.channels.check_products`` output;
    when given, «کجا بفروشم» (CHANNEL) suggestions are added from it.
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

    if channel_data:
        products = {p.pk: p for p in Product.objects.filter(store=store, pk__in=list(channel_data))}
        for pk, per_channel in channel_data.items():
            product = products.get(int(pk))
            if product is not None:
                found += channel_suggestions(product, per_channel)

    return found


# ------------------------------------------------------------ «کجا بفروشم»

#: Our price this far above the marketplace median is "not competitive there".
CHANNEL_PRICE_SLACK = 5.0


def channel_suggestions(product, per_channel: dict) -> list[dict]:
    """CHANNEL opportunities for one product from marketplace evidence.

    Only marketplaces that answered and where at least one listing is the same
    or a substitute product count — "this sells there" needs listings, and
    "your price is competitive there" needs their prices. No listing found is
    not turned into a suggestion: no evidence of demand is not evidence of
    opportunity.
    """
    from services.research.channels import HOME

    from .competitor_models import Opportunity

    out = []
    our_price = int(product.price) if product.price else None
    for channel, row in per_channel.items():
        if not row.get("ok") or not row.get("relevant"):
            continue
        label = row["label"]
        median_price = row.get("median_price")
        demand = row.get("demand") or {}
        demand_line = ""
        if demand.get("kind") == "sales" and demand.get("total"):
            demand_line = (
                f" این فروشنده‌ها روی هم {demand['total']:,} فروشِ ثبت‌شده در {label} دارند"
                + (f" ({demand['week']:,} در هفته‌ی اخیر)" if demand.get("week") else "")
                + "."
            )
        elif demand.get("kind") == "ratings" and demand.get("total"):
            demand_line = f" روی هم {demand['total']:,} امتیازِ خریدار دارند (نشانه‌ی خرید، نه تعدادِ فروش)."
        listing_line = (
            f"در {label} {row['relevant']} آگهیِ هم‌کالا/جایگزین از {row.get('sellers') or 'چند'} فروشنده پیدا شد"
        )
        price_line = ""
        if median_price:
            price_line = (
                f"؛ ارزان‌ترین {row['min_price']:,} و میانه‌ی قیمت {median_price:,} تومان است"
            )
        evidence = {
            "channel": channel, "channel_label": label, "query": row.get("query"),
            "listings": row.get("relevant"), "same_product": row.get("same"),
            "sellers": row.get("sellers"), "min_price": row.get("min_price"),
            "median_price": median_price, "our_price": our_price,
            "our_vs_median_percent": row.get("our_vs_median_percent"),
            "demand": demand, "links": row.get("links", []), "signup": HOME.get(channel, ""),
        }
        gap = row.get("our_vs_median_percent")
        if our_price and median_price and gap is not None and gap <= CHANNEL_PRICE_SLACK:
            where = "زیرِ" if gap < 0 else "هم‌سطحِ"
            # Far below the median usually means a different pack size, not a
            # bargain — say so instead of telling the shop it is the cheapest.
            suspicious = gap < -40
            out.append({
                "kind": Opportunity.Kind.CHANNEL,
                "product": product,
                "title": f"«{product.name}» را در {label} هم بفروشید",
                "reason": (
                    f"{listing_line}{price_line}. قیمتِ شما {our_price:,} تومان است — "
                    f"{where} میانه ({abs(gap):.0f}٪ {'کمتر' if gap < 0 else 'بیشتر'})."
                    + demand_line
                    + (
                        " اختلاف آن‌قدر زیاد است که شاید اندازه/وزنِ بسته‌ها یکی نباشد."
                        if suspicious else ""
                    )
                ),
                "action": (
                    f"اول وزن/اندازه‌ی بسته را با آگهی‌های {label} (پیوندهای زیر) مقایسه کنید؛ "
                    "اگر یکی است، با همین قیمت غرفه باز کنید — ارزان‌تر از بیشترِ فروشنده‌ها هستید."
                    if suspicious else
                    f"در {label} غرفه باز کنید و همین کالا را با همین قیمت ثبت کنید."
                ),
                "evidence": evidence,
                "priority": 75,
            })
        elif our_price and median_price and gap is not None:
            out.append({
                "kind": Opportunity.Kind.CHANNEL,
                "product": product,
                "title": f"«{product.name}» در {label} خریدار دارد، ولی قیمتِ شما بالاتر است",
                "reason": (
                    f"{listing_line}{price_line}. قیمتِ شما {our_price:,} تومان است — "
                    f"{gap:.0f}٪ بالاتر از میانه." + demand_line
                ),
                "action": (
                    f"اگر می‌خواهید در {label} بفروشید، قیمت را به میانه نزدیک کنید "
                    "یا در عنوان بگویید چرا گران‌تر است (اصالت، ارسالِ سریع، هدیه)."
                ),
                "evidence": evidence,
                "priority": 50,
            })
        else:
            out.append({
                "kind": Opportunity.Kind.CHANNEL,
                "product": product,
                "title": f"«{product.name}» در {label} فروشنده دارد",
                "reason": listing_line + price_line + "." + demand_line,
                "action": (
                    f"قیمتِ «{product.name}» را وارد کنید تا معلوم شود در {label} رقابتی است یا نه."
                    if not our_price else f"آگهی‌های {label} را باز کنید و با کالای خودتان مقایسه کنید."
                ),
                "evidence": evidence,
                "priority": 45,
            })
    return out


#: How many products one channel check covers (each costs 3 HTTP searches).
CHANNEL_CHECK_PRODUCTS = 8
CHANNEL_JOB_KIND = "channel_check"


def check_channels(store) -> dict:
    """Search the marketplaces for the shop's products and keep the report.

    The report is stored as a completed ``Job`` so the checklist can say when
    it last ran, from any worker, without a new table.
    """
    from apps.jobs.models import Job
    from apps.products.models import Product
    from services.research import channels

    products = list(
        Product.objects.filter(store=store, is_available=True).order_by("-updated_at")[:CHANNEL_CHECK_PRODUCTS]
    )
    data = channels.check_products(products) if products else {}
    problems = sorted({
        f"{row['label']}: {row.get('error')}"
        for per in data.values() for row in per.values() if not row.get("ok")
    })
    summary = {
        "kind": CHANNEL_JOB_KIND,
        "checked_at": timezone.now().isoformat(),
        "products": [{"id": p.pk, "name": p.name} for p in products],
        "channels": {
            str(pk): {
                ch: {k: v for k, v in row.items() if k != "links"} | {"links": row.get("links", [])[:3]}
                for ch, row in per.items()
            }
            for pk, per in data.items()
        },
        "problems": problems,
    }
    job = Job.objects.create(
        store=store, type=Job.Type.MARKET_ANALYSIS,
        context={"kind": CHANNEL_JOB_KIND},
    )
    job.mark_completed(summary)
    return {"data": data, "summary": summary}


def last_channel_check(store) -> dict | None:
    from apps.jobs.models import Job

    job = (
        Job.objects.filter(store=store, type=Job.Type.MARKET_ANALYSIS, context__kind=CHANNEL_JOB_KIND)
        .order_by("-created_at").first()
    )
    return job.result if job is not None else None


# ------------------------------------------------------------ what is missing


def readiness(store, days: int = 30) -> dict:
    """«چه چیزی لازم است» — which data is missing, how to add it, what it unlocks.

    Counts are of *possible* suggestions ("تا N"): adding a cost price makes
    the margin check possible for that product, it does not promise a warning.
    """
    from apps.customers.models import Order
    from apps.products.models import Product

    from .competitor_models import Competitor, CompetitorProduct

    sid = store.pk
    products = list(Product.objects.filter(store=store))
    n = len(products)
    since = timezone.now() - timedelta(days=max(1, min(365, days)))
    items = []

    items.append({
        "key": "products", "title": "محصولات", "done": n > 0,
        "detail": f"{n} محصول ثبت شده." if n else "هنوز محصولی ثبت نشده.",
        "unlocks": "همه‌ی پیشنهادهای این صفحه از روی محصولاتِ شما ساخته می‌شوند.",
        "unlocks_count": None,
        "fix": {"label": "افزودنِ محصول", "to": f"/stores/{sid}"},
    })

    missing_cost = [p for p in products if p.cost_price is None]
    items.append({
        "key": "cost_price", "title": "قیمتِ خرید (قیمتِ تمام‌شده)",
        "done": n > 0 and not missing_cost,
        "detail": (
            f"برای {len(missing_cost)} از {n} محصول وارد نشده: "
            + "، ".join(p.name for p in missing_cost[:3])
            + ("…" if len(missing_cost) > 3 else "")
        ) if missing_cost else ("برای همه وارد شده." if n else "—"),
        "unlocks": "سودِ واقعی و هشدارِ «سودِ این کالا کم است».",
        "unlocks_count": len(missing_cost),
        "fix": {"label": "واردکردنِ قیمتِ خرید", "to": f"/products/{missing_cost[0].pk}"} if missing_cost else None,
    })

    competitors = Competitor.objects.filter(store=store, is_active=True).count()
    priced = set(
        CompetitorProduct.objects.filter(
            competitor__store=store, competitor__is_active=True,
            matches__isnull=False, price_toman__isnull=False,
        ).values_list("matches_id", flat=True)
    )
    without_rival = [p for p in products if p.pk not in priced]
    items.append({
        "key": "competitors", "title": "رقیبِ هم‌کالا با قیمت",
        "done": n > 0 and not without_rival,
        "detail": (
            f"{competitors} رقیب ثبت شده؛ برای {len(priced)} از {n} محصول قیمتِ همان کالا نزدِ رقیب را داریم."
        ),
        "unlocks": "مقایسه‌ی قیمت: «از رقیب گران‌ترید» با هر دو عدد.",
        "unlocks_count": len(without_rival),
        "fix": {"label": "یافتنِ رقیب / کرالِ سایتِ رقیب", "to": f"/stores/{sid}/competitors"} if without_rival else None,
    })

    orders = Order.objects.filter(
        store=store, status=Order.Status.CONFIRMED, confirmed_at__gte=since,
    ).count()
    items.append({
        "key": "sales", "title": f"فروشِ {days} روزِ اخیر",
        "done": orders > 0,
        "detail": f"{orders} سفارشِ تأییدشده." if orders else "هیچ سفارشِ تأییدشده‌ای ثبت نشده.",
        "unlocks": "تشخیصِ کالای کم‌فروش و پرفروش، و پیشنهادِ فروشِ مکمل.",
        "unlocks_count": n if not orders else 0,
        "fix": {"label": "ثبتِ سفارش‌ها", "to": f"/stores/{sid}/sales/orders"} if not orders else None,
    })

    no_stock = [p for p in products if not p.stock_quantity]
    items.append({
        "key": "stock", "title": "موجودیِ انبار",
        "done": n > 0 and not no_stock,
        "detail": (
            f"موجودیِ {len(no_stock)} محصول صفر یا واردنشده است: "
            + "، ".join(p.name for p in no_stock[:3])
        ) if no_stock else ("وارد شده." if n else "—"),
        "unlocks": "هشدارِ «موجود است ولی نمی‌فروشد» (پیشنهادِ محتوا برای آب کردنِ موجودی).",
        "unlocks_count": len(no_stock),
        "fix": {"label": "واردکردنِ موجودی", "to": f"/products/{no_stock[0].pk}"} if no_stock else None,
    })

    last = last_channel_check(store)
    items.append({
        "key": "channels", "title": "بررسیِ بازارها (دیجی‌کالا، باسلام، ترب)",
        "done": bool(last),
        "detail": (
            f"آخرین بررسی: {last.get('checked_at', '')[:16].replace('T', ' ')} — "
            f"{len(last.get('products') or [])} محصول."
            + (" مشکل: " + "؛ ".join(last.get("problems") or []) if last.get("problems") else "")
        ) if last else "هنوز بررسی نشده.",
        "unlocks": "پیشنهادِ «کجا بفروشم»: بازاری که کالای شما در آن خریدار دارد و قیمتتان رقابتی است.",
        "unlocks_count": min(n, CHANNEL_CHECK_PRODUCTS),
        "fix": {"label": "بررسیِ بازارها", "action": "check_channels"},
    })

    return {
        "items": items,
        "done": sum(1 for i in items if i["done"]),
        "total": len(items),
        "channels": last,
    }


def refresh(store, days: int = 30, check_channels_now: bool = False) -> dict:
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

    channel_report = None
    checked_channels: set[tuple[int, str]] = set()
    channel_data = None
    if check_channels_now:
        result = check_channels(store)
        channel_data = result["data"]
        channel_report = result["summary"]
        checked_channels = {
            (int(pk), ch) for pk, per in channel_data.items()
            for ch, row in per.items() if row.get("ok")
        }
    candidates = suggest(store, days, channel_data=channel_data)
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
        existing.action = candidate["action"]
        existing.evidence = candidate["evidence"]
        existing.priority = candidate["priority"]
        existing.state = Opportunity.State.OPEN
        existing.save(update_fields=["reason", "action", "evidence", "priority", "state", "updated_at"])
        updated += 1

    stale = 0
    for row in Opportunity.objects.filter(store=store, state=Opportunity.State.OPEN):
        key = (row.kind, row.product_id, row.title)
        if row.kind == Opportunity.Kind.CHANNEL and (
            row.product_id, (row.evidence or {}).get("channel")
        ) not in checked_channels:
            # Not re-checked this time (no channel check, or the marketplace
            # did not answer): absence of evidence must not close it.
            continue
        if key not in seen_keys:
            row.state = Opportunity.State.DONE
            row.save(update_fields=["state", "updated_at"])
            stale += 1

    return {
        "created": created, "updated": updated, "resolved": stale,
        "channels": channel_report,
    }
