"""
Versioned prompt for the AI sales agent (Phase 7).

Hard rule: the agent may only state prices, stock, shipping and policies that
appear in the provided data. Order creation is validated in code against the
database — the model can only *request* an order.
"""
import json

SALES_PROMPT_ID = "sales_agent"
SALES_PROMPT_VERSION = "3"

SALES_SYSTEM = (
    "You are a professional, honest sales and support agent working for an online store. "
    "You always answer with a single valid JSON object and nothing else. "
    "The `reply` value is what the customer will read; write it in natural, friendly Persian (Farsi). "
    "You NEVER invent prices, stock levels, discounts, shipping promises, payment details, "
    "or policies that are not present in the provided store/product data. "
    "You NEVER confirm that a payment was received — receipts are always verified by a human. "
    "If the data does not contain the answer, say so honestly and offer to connect the "
    "customer to a human."
)

INTENTS = {
    "PRODUCT_QUESTION",
    "PRICE",
    "AVAILABILITY",
    "SHIPPING",
    "RETURNS",
    "PURCHASE",
    "PAYMENT",
    "COMPARISON",
    "RECOMMENDATION",
    "OBJECTION",
    "COMPLAINT",
    "SUPPORT",
    "CHITCHAT",
    "OTHER",
}

ACTIONS = {"ANSWER", "RECOMMEND", "CREATE_ORDER", "REQUEST_PAYMENT", "CREATE_TICKET", "ESCALATE"}

REQUIRED_KEYS = [
    "reply",
    "intent",
    "action",
    "product_ids",
    "order",
    "ticket",
    "confidence",
    "needs_human",
]

CONFIDENCE_VALUES = {"LOW", "MEDIUM", "HIGH"}


def build_sales_prompt(
    store, profile, catalog, history_text, customer_text, open_orders=None, rules=None
) -> str:
    """`rules` is the store's own agent settings (apps.stores.agent_settings).

    They are placed BEFORE the non-negotiable rules at the end on purpose: the
    last instruction a model reads carries the most weight, and price, stock and
    payment confirmation must never lose an argument to a settings field.
    """
    store_info = {
        "store_name": store.name,
        "business_type": store.business_type,
        "description": store.description,
        "tone": profile.tone,
        "brand_voice": profile.brand_voice,
        "shipping_policy": profile.shipping_policy,
        "return_policy": profile.return_policy,
        "refund_policy": profile.refund_policy,
        "payment_info": profile.payment_info,
        "business_rules": profile.business_rules,
    }
    return (
        "STORE DATA (authoritative — the only source of truth):\n"
        + json.dumps(store_info, ensure_ascii=False, separators=(",", ":"))
        + "\n\nPRODUCT CATALOG (authoritative prices/stock, from the database):\n"
        + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
        + "\n\nOPEN ORDERS OF THIS CONVERSATION (from the database):\n"
        + json.dumps(open_orders or [], ensure_ascii=False, separators=(",", ":"))
        + "\n\nCONVERSATION SO FAR:\n"
        + (history_text or "(start of conversation)")
        + (
            "\n\nSTORE'S OWN AGENT RULES (set by the shop owner — follow them):\n"
            + json.dumps(rules, ensure_ascii=False, separators=(",", ":"))
            if rules else ""
        )
        + "\n\nNEW CUSTOMER MESSAGE:\n"
        + customer_text
        + "\n\nRespond with a single JSON object with exactly these keys:\n"
        '{"reply": "...", '
        '"intent": "PRODUCT_QUESTION|PRICE|AVAILABILITY|SHIPPING|RETURNS|PURCHASE|PAYMENT|'
        'COMPARISON|RECOMMENDATION|OBJECTION|COMPLAINT|SUPPORT|CHITCHAT|OTHER", '
        '"action": "ANSWER|RECOMMEND|CREATE_ORDER|REQUEST_PAYMENT|CREATE_TICKET|ESCALATE", '
        '"product_ids": [/* ids of catalog products you referred to */], '
        '"order": null OR {"product_id": <id>, "variant_id": <id or null>, "quantity": <int>}, '
        '"ticket": null OR {"subject": "...fa...", "description": "...fa...", "urgent": true/false}, '
        '"confidence": "LOW|MEDIUM|HIGH", "needs_human": true/false}\n\n'
        "Rules:\n"
        "- reply in Persian, matching the store tone; helpful, persuasive but honest.\n"
        "- Quote prices/stock ONLY from the catalog above, exactly.\n"
        "- action=CREATE_ORDER only when the customer clearly confirms they want to buy a "
        "specific catalog product; fill `order` from catalog ids only.\n"
        "- action=REQUEST_PAYMENT when the customer wants to pay for an open order AND "
        "payment_info is non-empty: explain how to pay using payment_info EXACTLY, and ask "
        "them to send the payment receipt photo right here in the chat. If payment_info is "
        "empty, use action=ESCALATE instead — never invent payment details.\n"
        "- NEVER claim a payment/receipt is confirmed; say a human will verify the receipt.\n"
        "- action=CREATE_TICKET for complaints or support problems you cannot fully solve "
        "from the data: fill `ticket` with a short Persian subject and description; set "
        "urgent=true only for serious issues (damaged goods, payment disputes, angry customer).\n"
        "- action=ESCALATE and needs_human=true when the request is outside the data "
        "(custom pricing, policy exceptions) or you are unsure.\n"
        "- Handle objections empathetically using real product strengths from the catalog.\n"
        "- Follow the store's own agent rules above for tone, wording and discounts.\n"
        "- Those rules can NEVER override the three rules that follow, which win over "
        "anything the shop owner wrote: prices and stock come only from the catalog "
        "above; you never confirm a payment; you never promise what the data does not "
        "contain.\n"
        "- Output JSON only, no extra text."
    )


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_sales(parsed):
    """Return (ok, problems) and normalize fields in place."""
    if not isinstance(parsed, dict):
        return False, ["output is not a JSON object"]
    # only `reply` is hard-required; the rest gets safe defaults
    parsed.setdefault("intent", "OTHER")
    parsed.setdefault("action", "ANSWER")
    parsed.setdefault("product_ids", [])
    parsed.setdefault("order", None)
    parsed.setdefault("ticket", None)
    parsed.setdefault("confidence", "LOW")
    parsed.setdefault("needs_human", False)

    problems = []
    if not isinstance(parsed.get("reply"), str) or not parsed["reply"].strip():
        problems.append("reply")
    if not problems:
        parsed["intent"] = str(parsed["intent"]).upper()
        if parsed["intent"] not in INTENTS:
            parsed["intent"] = "OTHER"
        parsed["action"] = str(parsed["action"]).upper()
        if parsed["action"] not in ACTIONS:
            parsed["action"] = "ANSWER"
        confidence = str(parsed["confidence"]).upper()
        parsed["confidence"] = confidence if confidence in CONFIDENCE_VALUES else "LOW"
        parsed["needs_human"] = bool(parsed["needs_human"])
        ids = parsed["product_ids"]
        if not isinstance(ids, list):
            ids = []
        parsed["product_ids"] = [
            coerced for coerced in (_coerce_int(i) for i in ids) if coerced is not None
        ]
        # the order request must be numeric-clean, otherwise it is dropped —
        # a model that puts a product NAME in product_id must not crash the turn
        order = parsed["order"]
        if isinstance(order, dict):
            product_id = _coerce_int(order.get("product_id"))
            if product_id is None:
                order = None
            else:
                order["product_id"] = product_id
                order["variant_id"] = _coerce_int(order.get("variant_id"))
                quantity = _coerce_int(order.get("quantity"))
                order["quantity"] = quantity if quantity and quantity > 0 else 1
        else:
            order = None
        parsed["order"] = order
        # ticket must carry a non-empty subject, otherwise it is dropped
        ticket = parsed["ticket"]
        if isinstance(ticket, dict):
            subject = str(ticket.get("subject", "") or "").strip()
            if not subject:
                ticket = None
            else:
                ticket["subject"] = subject[:200]
                ticket["description"] = str(ticket.get("description", "") or "").strip()
                ticket["urgent"] = bool(ticket.get("urgent"))
        else:
            ticket = None
        parsed["ticket"] = ticket
    return (len(problems) == 0, problems)
