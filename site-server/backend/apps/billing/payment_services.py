"""Turning a payment into an active subscription.

The rules that must not bend, in one place:

* **Nothing is activated on the browser's word.** The callback query string is
  a hint. Money is confirmed by a call we make to the gateway.
* **The amount is ours, not the client's.** A start request names a plan; the
  price is read from that plan server-side. A client cannot propose what it
  would like to pay.
* **Verification is idempotent.** Gateways retry, users refresh the callback,
  and ZarinPal answers "already verified" the second time. Verifying twice must
  extend a subscription once.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Plan, Subscription
from .payment_models import BillingEvent, Payment
from .payments import PaymentError, get_provider

logger = logging.getLogger(__name__)


def log_event(store, kind, summary, *, actor=None, payment=None, **context):
    return BillingEvent.objects.create(
        store=store, kind=kind, summary=summary,
        actor=actor, payment=payment, context=context,
    )


def grace_days() -> int:
    """How long a lapsed subscription keeps working after its period ends.

    Cutting a paying customer off the minute a renewal fails is how you lose
    someone whose card simply expired.
    """
    return int(getattr(settings, "UPMARKET_PAYMENT", {}).get("GRACE_DAYS", 3))


def period_days() -> int:
    return int(getattr(settings, "UPMARKET_PAYMENT", {}).get("PERIOD_DAYS", 30))


# ---------------------------------------------------------------- start

@transaction.atomic
def start_payment(*, store, plan: Plan, provider_key: str, callback_url: str,
                  actor=None) -> tuple[Payment, str]:
    """Create a pending Payment and ask the gateway for a redirect URL."""
    if plan.price_toman <= 0:
        raise PaymentError("این پلن رایگان است و پرداخت لازم ندارد.")

    provider = get_provider(provider_key)

    payment = Payment.objects.create(
        store=store,
        subscription=getattr(store, "subscription", None),
        plan=plan,
        # Price comes from the plan row, never from the request body.
        amount_toman=plan.price_toman,
        provider=provider.key,
        status=Payment.Status.PENDING,
    )

    try:
        result = provider.start(
            amount_toman=payment.amount_toman,
            description=f"{plan.name} — {store.name}",
            callback_url=callback_url,
            reference=payment.invoice_number,
        )
    except PaymentError as exc:
        payment.status = Payment.Status.FAILED
        payment.error = str(exc)[:300]
        payment.save(update_fields=["status", "error", "updated_at"])
        log_event(
            store, BillingEvent.Kind.PAYMENT_FAILED,
            f"شروع پرداخت ناموفق: {exc}", actor=actor, payment=payment,
        )
        raise

    payment.token = result.token
    payment.gateway_response = result.raw
    payment.save(update_fields=["token", "gateway_response", "updated_at"])

    log_event(
        store, BillingEvent.Kind.PAYMENT_STARTED,
        f"شروع پرداخت {payment.amount_toman:,} تومان برای پلن {plan.name}",
        actor=actor, payment=payment, provider=provider.key,
    )
    return payment, result.redirect_url


# --------------------------------------------------------------- verify

@transaction.atomic
def verify_payment(*, token: str, actor=None) -> Payment:
    """Confirm a payment with the gateway and activate on success."""
    payment = (
        Payment.objects.select_for_update()
        .select_related("store", "plan")
        .filter(token=token)
        .first()
    )
    if payment is None:
        raise PaymentError("پرداختی با این شناسه پیدا نشد.")

    # Already settled: return it unchanged. A refreshed callback or a retried
    # webhook must not extend the subscription a second time.
    if payment.status == Payment.Status.PAID:
        return payment
    if payment.status in (Payment.Status.REFUNDED, Payment.Status.FAILED):
        return payment

    provider = get_provider(payment.provider)
    result = provider.verify(token=token, amount_toman=payment.amount_toman)

    if not result.paid:
        payment.status = Payment.Status.FAILED
        payment.error = result.message[:300]
        payment.gateway_response = result.raw
        payment.save(update_fields=["status", "error", "gateway_response", "updated_at"])
        log_event(
            payment.store, BillingEvent.Kind.PAYMENT_FAILED,
            f"پرداخت تأیید نشد: {result.message or 'بدون توضیح'}",
            actor=actor, payment=payment,
        )
        return payment

    # The gateway says paid — but does it agree on how much? A mismatch means
    # either a tampered request or a gateway bug, and either way this is not
    # something to activate quietly.
    if result.amount and result.amount != payment.amount_toman:
        payment.status = Payment.Status.FAILED
        payment.error = (
            f"مبلغ نخواند: انتظار {payment.amount_toman} — گزارش {result.amount}"
        )
        payment.gateway_response = result.raw
        payment.save(update_fields=["status", "error", "gateway_response", "updated_at"])
        log_event(
            payment.store, BillingEvent.Kind.PAYMENT_FAILED,
            payment.error, actor=actor, payment=payment,
        )
        logger.error("Payment %s amount mismatch: %s", payment.pk, payment.error)
        return payment

    payment.status = Payment.Status.PAID
    payment.reference = result.reference
    payment.paid_at = timezone.now()
    payment.gateway_response = result.raw
    payment.error = ""
    payment.save(
        update_fields=["status", "reference", "paid_at", "gateway_response",
                       "error", "updated_at"]
    )
    log_event(
        payment.store, BillingEvent.Kind.PAYMENT_PAID,
        f"پرداخت {payment.amount_toman:,} تومان تأیید شد (مرجع {result.reference})",
        actor=actor, payment=payment,
    )

    activate(payment, actor=actor)
    return payment


# ------------------------------------------------------------- activate

def activate(payment: Payment, *, actor=None) -> Subscription:
    """Put the store on the paid plan and start a fresh period."""
    store = payment.store
    now = timezone.now()

    sub = Subscription.objects.filter(store=store).first()
    if sub is None:
        sub = Subscription(store=store, plan=payment.plan, period_start=now,
                           period_end=now + timedelta(days=period_days()))
        created = True
        previous_plan = None
        was_active = False
    else:
        created = False
        previous_plan = sub.plan
        # "Renewed" only makes sense if it was already a paying subscription.
        # A first payment on a trial is an activation, and the audit trail is
        # read during billing disputes — calling it a renewal there is wrong.
        was_active = sub.status == Subscription.Status.ACTIVE
    sub.plan = payment.plan
    sub.status = Subscription.Status.ACTIVE
    sub.cancel_at_period_end = False

    # A renewal while still inside a paid period should extend it, not throw
    # away the days already bought. A renewal after expiry starts from now.
    base = sub.period_end if (not created and sub.period_end and sub.period_end > now) else now
    sub.period_start = now if created or base == now else sub.period_start
    sub.period_end = base + timedelta(days=period_days())
    sub.save()

    payment.subscription = sub
    payment.save(update_fields=["subscription", "updated_at"])

    # Logged before the activation line so the history reads in the order the
    # events actually happened: plan changed, then subscription activated.
    if previous_plan and previous_plan.pk != payment.plan.pk:
        log_event(
            store, BillingEvent.Kind.PLAN_CHANGED,
            f"پلن از «{previous_plan.name}» به «{payment.plan.name}» تغییر کرد",
            actor=actor, payment=payment,
            from_plan=previous_plan.slug, to_plan=payment.plan.slug,
        )

    log_event(
        store,
        BillingEvent.Kind.RENEWED if was_active else BillingEvent.Kind.ACTIVATED,
        f"اشتراک «{payment.plan.name}» تا {sub.period_end:%Y-%m-%d} فعال است",
        actor=actor, payment=payment,
        carried_over_days=max(0, (base - now).days) if not created else 0,
    )
    return sub


# --------------------------------------------------------------- manual

@transaction.atomic
def confirm_manual(payment: Payment, *, actor, reference: str = "") -> Payment:
    """Mark a bank transfer as received. Always a human decision."""
    if payment.provider != "manual":
        raise PaymentError("این پرداخت از درگاه آمده و تأیید دستی لازم ندارد.")
    if payment.status == Payment.Status.PAID:
        return payment

    payment.status = Payment.Status.PAID
    payment.reference = reference or payment.invoice_number
    payment.paid_at = timezone.now()
    payment.confirmed_by = actor
    payment.save(
        update_fields=["status", "reference", "paid_at", "confirmed_by", "updated_at"]
    )
    log_event(
        payment.store, BillingEvent.Kind.PAYMENT_PAID,
        f"واریز بانکی {payment.amount_toman:,} تومان توسط انسان تأیید شد",
        actor=actor, payment=payment,
    )
    activate(payment, actor=actor)
    return payment


@transaction.atomic
def refund(payment: Payment, *, actor, reason: str = "") -> Payment:
    """Record a refund.

    The money itself moves in the gateway's own panel — no Iranian gateway
    exposes a reliable refund API — so this records the decision rather than
    pretending to execute it. Saying so out loud beats a button that looks like
    it moved money and did not.
    """
    if payment.status != Payment.Status.PAID:
        raise PaymentError("فقط پرداخت موفق قابل بازگشت است.")

    payment.status = Payment.Status.REFUNDED
    payment.refunded_at = timezone.now()
    payment.refund_reason = reason[:300]
    payment.save(
        update_fields=["status", "refunded_at", "refund_reason", "updated_at"]
    )
    log_event(
        payment.store, BillingEvent.Kind.PAYMENT_REFUNDED,
        f"بازگشت وجه {payment.amount_toman:,} تومان — {reason or 'بدون توضیح'}",
        actor=actor, payment=payment,
    )
    return payment
