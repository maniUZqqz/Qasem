"""
Sales-agent orchestration: retrieve real store data → one structured qwq call →
code-side grounding (validate product ids, create orders ONLY from DB data).
"""
import logging
from decimal import Decimal

from apps.ai.models import AIRequest
from apps.ai.services import recorded_json_call
from services.ai.embeddings import semantic_product_ids
from services.ai import gateway
from services.ai.gateway import text_provider
from services.ai.prompts import sales_agent as prompts
from services.ai.ollama import OllamaMalformedOutput
from services.ai.router import TASK_REASONING, models_for

from apps.stores import agent_settings

from . import stock
from .models import Conversation, Message, Order, OrderItem, SupportTicket

logger = logging.getLogger(__name__)


class SalesRulesUnmet(OllamaMalformedOutput):
    """No model produced a reply that obeyed the shop's own `never_say` rules.

    Subclasses the malformed-output error so existing callers — which already
    hand the conversation to a person when the AI cannot answer — keep working
    without knowing this case exists.
    """


CATALOG_LIMIT = 12
HISTORY_LIMIT = 10

# order states the customer can still pay for
OPEN_ORDER_STATES = [Order.Status.DRAFT, Order.Status.AWAITING_RECEIPT]


def keyword_products(store, text, limit=CATALOG_LIMIT):
    """Real DB retrieval: token match on name/description/brand; fallback to newest."""
    from django.db.models import Q

    qs = store.products.filter(is_available=True)
    tokens = [t for t in text.split() if len(t) >= 2][:8]
    if tokens:
        query = Q()
        for token in tokens:
            query |= (
                Q(name__icontains=token)
                | Q(description__icontains=token)
                | Q(brand__icontains=token)
                | Q(attributes__value__icontains=token)
            )
        matched = qs.filter(query).distinct()[:limit]
        if matched:
            remaining = limit - len(matched)
            if remaining > 0:
                extra = qs.exclude(id__in=[p.id for p in matched])[:remaining]
                return list(matched) + list(extra)
            return list(matched)
    return list(qs[:limit])


def relevant_products(store, text, limit=CATALOG_LIMIT):
    """Catalog retrieval for the agent.

    With EMBEDDINGS_ENABLED, semantic (vector) search ranks first and keyword
    matches fill the rest; otherwise (or on any embedding failure) it is the
    plain keyword retrieval — behavior is identical to before the feature.
    """
    semantic_ids = semantic_product_ids(store, text, limit=limit)
    if not semantic_ids:
        return keyword_products(store, text, limit)
    by_id = {
        p.id: p
        for p in store.products.filter(id__in=semantic_ids, is_available=True)
    }
    products = [by_id[pid] for pid in semantic_ids if pid in by_id]
    if len(products) < limit:
        seen = {p.id for p in products}
        for product in keyword_products(store, text, limit):
            if product.id not in seen:
                products.append(product)
                seen.add(product.id)
            if len(products) >= limit:
                break
    return products[:limit]


def catalog_payload(products):
    payload = []
    for product in products:
        payload.append(
            {
                "id": product.id,
                "name": product.name,
                "price": str(product.price),
                "currency": product.currency,
                # What is actually sellable. The model quotes this number to
                # the customer, and quoting the shelf count would promise
                # items another customer is paying for right now.
                "stock_quantity": product.available_quantity,
                "stock_status": product.stock_status,
                "short_description": product.short_description or product.description[:300],
                "attributes": {a.key: a.value for a in product.attributes.all()},
                "variants": [
                    {
                        "id": v.id,
                        "name": v.name,
                        "stock_quantity": v.available_quantity,
                        "price": str(v.price_override or product.price),
                    }
                    for v in product.variants.all()
                ],
            }
        )
    return payload


def history_text(conversation, limit=HISTORY_LIMIT):
    messages = list(conversation.messages.order_by("-created_at")[:limit])[::-1]
    labels = {Message.Role.CUSTOMER: "Customer", Message.Role.AI: "Agent", Message.Role.HUMAN: "Human agent"}
    return "\n".join(f"{labels.get(m.role, m.role)}: {m.text}" for m in messages)


def _try_create_order(store, conversation, order_request, products_by_id):
    """Create a DRAFT order strictly from database data. Returns (order, error)."""
    product_id = order_request.get("product_id")
    try:
        quantity = int(order_request.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1:
        return None, "تعداد سفارش نامعتبر است."

    product = products_by_id.get(product_id) or store.products.filter(
        id=product_id, is_available=True
    ).first()
    if product is None:
        return None, "محصول انتخاب‌شده در فروشگاه یافت نشد."

    variant = None
    variant_id = order_request.get("variant_id")
    if variant_id:
        variant = product.variants.filter(id=variant_id).first()
        if variant is None:
            return None, "واریانت انتخاب‌شده برای این محصول وجود ندارد."
        # `available_quantity`, not `stock_quantity`: an item already
        # promised to someone who is paying for it right now is not for sale.
        if variant.available_quantity < quantity:
            return None, "موجودی این واریانت کافی نیست."
    elif product.available_quantity < quantity:
        return None, "موجودی محصول کافی نیست."

    unit_price = (variant.price_override if variant and variant.price_override else product.price)
    order = Order.objects.create(
        store=store,
        customer=conversation.customer,
        conversation=conversation,
        status=Order.Status.DRAFT,
        total=Decimal(unit_price) * quantity,
    )
    OrderItem.objects.create(
        order=order, product=product, variant=variant, quantity=quantity, unit_price=unit_price
    )
    return order, None


def open_orders_payload(conversation):
    """Open (payable) orders of this conversation, from the database."""
    orders = conversation.orders.filter(status__in=OPEN_ORDER_STATES).prefetch_related(
        "items__product"
    )
    return [
        {
            "order_id": order.id,
            "status": order.status,
            "total": str(order.total),
            "items": [f"{item.quantity}× {item.product.name}" for item in order.items.all()],
        }
        for order in orders
    ]


def run_sales_agent(conversation: Conversation, customer_text: str) -> dict:
    """One grounded agent turn. Returns a result dict; raises OllamaError family on failure."""
    store = conversation.store
    profile = store.profile
    products = relevant_products(store, customer_text)
    products_by_id = {p.id: p for p in products}
    catalog = catalog_payload(products)
    open_orders = open_orders_payload(conversation)

    # The shop's own rules for how this agent talks and what it may promise.
    settings = agent_settings.settings_for(store)
    banned = settings.banned_phrases

    def check(parsed):
        """Structure first, then the shop's own rules.

        A reply that breaks a `never_say` rule is treated exactly like malformed
        JSON: the next model gets a turn. Putting the phrases in the prompt makes
        the model *usually* comply; this is what makes it a rule. If no model
        produces a clean reply, the caller below hands the customer to a person
        rather than sending something the owner forbade.
        """
        ok, problems = prompts.validate_sales(parsed)
        if not ok:
            return ok, problems
        broken = agent_settings.violations(parsed.get("reply", ""), banned)
        if broken:
            return False, [f"عبارت ممنوع: {phrase}" for phrase in broken]
        return True, []

    # A customer's own words, not the shop's copy: this is the one call
    # site that carries third-party personal data, so it says so.
    provider = text_provider(store, gateway.CUSTOMER)
    try:
        parsed, request_row = recorded_json_call(
            store=store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id=prompts.SALES_PROMPT_ID,
            prompt_version=prompts.SALES_PROMPT_VERSION,
            provider=provider,
            models=models_for(TASK_REASONING),
            prompt=prompts.build_sales_prompt(
                store, profile, catalog, history_text(conversation), customer_text,
                open_orders, rules=settings.as_prompt_rules(),
            ),
            system=prompts.SALES_SYSTEM,
            # a half-formed reply falls through to the next installed model rather
            # than leaving the customer with an error
            validate=check,
            validation_message="پاسخ فروشنده ناقص بود",
        )
    except OllamaMalformedOutput:
        if not banned:
            raise
        # Every model produced something the owner forbade. Saying nothing is
        # better than saying the forbidden thing, so a person takes over.
        logger.warning(
            "Sales agent could not produce a reply within store #%s rules", store.id,
        )
        raise SalesRulesUnmet(
            "پاسخ AI با قوانین فروشگاه نخواند و به همکار انسانی ارجاع شد."
        )

    # Grounding: only real products of THIS store may be referenced.
    valid_ids = [pid for pid in parsed["product_ids"] if pid in products_by_id]
    dropped = set(parsed["product_ids"]) - set(valid_ids)
    if dropped:
        logger.warning("Sales agent referenced unknown product ids %s — dropped", dropped)

    action = parsed["action"]
    order = None
    order_error = None
    if action == "CREATE_ORDER":
        if parsed.get("order"):
            order, order_error = _try_create_order(
                store, conversation, parsed["order"], products_by_id
            )
        else:
            order_error = "درخواست سفارش ناقص بود."
        if order is None:
            action = "ANSWER"

    # REQUEST_PAYMENT is grounded in code: it needs a real open order AND real
    # payment_info; otherwise the turn degrades honestly instead of promising
    # payment steps that do not exist.
    payment_request = None
    if action == "REQUEST_PAYMENT":
        payable = conversation.orders.filter(status__in=OPEN_ORDER_STATES).first()
        if payable is None:
            order_error = "سفارش بازی برای پرداخت وجود ندارد."
            action = "ANSWER"
        elif not profile.payment_info.strip():
            # the model was told to escalate without payment_info; enforce it
            action = "ESCALATE"
        else:
            payable.status = Order.Status.AWAITING_RECEIPT
            payable.save(update_fields=["status", "updated_at"])
            # The customer has the payment details in hand; hold the goods for
            # them so the next chat cannot sell the same last one.
            stock.reserve(payable)
            payment_request = {"order_id": payable.id, "payment_info": profile.payment_info}

    # CREATE_TICKET: the ticket row is real and always visible to the owner.
    ticket = None
    if action == "CREATE_TICKET":
        ticket_data = parsed.get("ticket")
        if ticket_data:
            ticket = SupportTicket.objects.create(
                store=store,
                customer=conversation.customer,
                conversation=conversation,
                subject=ticket_data["subject"],
                description=ticket_data.get("description", ""),
                priority=(
                    SupportTicket.Priority.URGENT
                    if ticket_data.get("urgent")
                    else SupportTicket.Priority.NORMAL
                ),
            )
        else:
            action = "ESCALATE"

    return {
        "reply": parsed["reply"].strip(),
        "intent": parsed["intent"],
        "action": action,
        "product_ids": valid_ids,
        "order": order,
        "order_error": order_error,
        "payment_request": payment_request,
        "ticket": ticket,
        "confidence": parsed["confidence"],
        "needs_human": parsed["needs_human"] or action == "ESCALATE",
        "ai_request": request_row,
    }
