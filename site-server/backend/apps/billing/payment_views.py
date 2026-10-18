"""Payment endpoints.

The callback is the only public one — the gateway sends the customer's browser
there, and it carries no authentication. That is fine, because it authenticates
nothing: it looks the payment up by the gateway's own token and then asks the
gateway whether it was paid. Knowing a token gets you nothing you did not
already do.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Plan, Subscription
from .payment_models import BillingEvent, Payment
from .payment_services import start_payment, verify_payment
from .payments import PaymentError, available_providers, default_provider_key
from .views import _owned_store

logger = logging.getLogger(__name__)


def _conf() -> dict:
    return getattr(settings, "UPMARKET_PAYMENT", {})


class PaymentProviderListView(APIView):
    """What the customer can actually pay with right now."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "default": default_provider_key(),
                "providers": [
                    {"key": p.key, "label": p.label, "automatic": p.automatic}
                    for p in available_providers()
                ],
            }
        )


class PaymentStartView(APIView):
    """`POST /stores/{id}/payments/` — begin paying for a plan."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        store = _owned_store(request, pk)

        slug = str(request.data.get("plan") or "")
        plan = Plan.objects.filter(slug=slug, is_public=True).first()
        if plan is None:
            return Response(
                {"error": {"code": "unknown_plan", "message": "چنین پلنی وجود ندارد."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider_key = str(request.data.get("provider") or default_provider_key())
        if not provider_key:
            return Response(
                {"error": {"code": "no_provider",
                           "message": "هیچ درگاه پرداختی پیکربندی نشده است."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        callback = f"{_conf().get('CALLBACK_BASE', '').rstrip('/')}/api/v1/payments/callback/"

        try:
            payment, redirect_url = start_payment(
                store=store, plan=plan, provider_key=provider_key,
                callback_url=callback, actor=request.user,
            )
        except PaymentError as exc:
            return Response(
                {"error": {"code": "gateway_error", "message": str(exc)}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "invoice_number": payment.invoice_number,
                "amount_toman": payment.amount_toman,
                "provider": payment.provider,
                "redirect_url": redirect_url,
                # Manual transfer has no redirect; the panel shows these
                # instructions and waits for a receipt instead.
                "instructions": payment.gateway_response.get("account_info", ""),
            },
            status=status.HTTP_201_CREATED,
        )


class PaymentCallbackView(APIView):
    """Where the gateway returns the customer's browser.

    Accepts both GET (every Iranian gateway redirects) and POST (some also
    send a server-side notification). Both paths do the same thing: verify
    with the gateway, then send the person somewhere readable.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return self._handle(request.query_params)

    def post(self, request):
        return self._handle(request.data)

    def _handle(self, data):
        # Gateways disagree on the parameter name; accept the common ones.
        token = (
            data.get("Authority")
            or data.get("authority")
            or data.get("token")
            or data.get("trackId")
            or ""
        )
        panel = _conf().get("PANEL_URL", "").rstrip("/")

        if not token:
            return redirect(f"{panel}/?payment=missing")

        try:
            payment = verify_payment(token=str(token))
        except PaymentError as exc:
            logger.warning("Payment callback failed for %s: %s", token, exc)
            return redirect(f"{panel}/?payment=error")

        outcome = "ok" if payment.status == Payment.Status.PAID else "failed"
        store_id = payment.store_id
        return redirect(
            f"{panel}/stores/{store_id}/plan?payment={outcome}"
            f"&invoice={payment.invoice_number}"
        )


class PaymentHistoryView(APIView):
    """Invoices and billing history for one store."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        store = _owned_store(request, pk)
        payments = Payment.objects.filter(store=store).select_related("plan")[:50]
        events = BillingEvent.objects.filter(store=store)[:50]
        sub = Subscription.objects.filter(store=store).select_related("plan").first()

        return Response(
            {
                "subscription": (
                    {
                        "plan": sub.plan.name,
                        "status": sub.status,
                        "status_display": sub.get_status_display(),
                        "period_end": sub.period_end,
                        "days_left": sub.days_left,
                        "in_grace": sub.in_grace,
                        "is_usable": sub.is_usable,
                    }
                    if sub
                    else None
                ),
                "payments": [
                    {
                        "invoice_number": p.invoice_number,
                        "amount_toman": p.amount_toman,
                        "plan": p.plan.name,
                        "provider": p.provider,
                        "status": p.status,
                        "status_display": p.get_status_display(),
                        "reference": p.reference,
                        "paid_at": p.paid_at,
                        "created_at": p.created_at,
                    }
                    for p in payments
                ],
                "events": [
                    {
                        "kind": e.kind,
                        "kind_display": e.get_kind_display(),
                        "summary": e.summary,
                        "at": e.created_at,
                    }
                    for e in events
                ],
            }
        )
