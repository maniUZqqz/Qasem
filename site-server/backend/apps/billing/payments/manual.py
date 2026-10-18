"""Bank transfer, confirmed by a human.

This is what the business does today: the customer transfers money and someone
checks. Modelling it as a provider rather than leaving it outside the system
matters, because it means a manually-paid subscription goes through the same
activation path, produces the same invoice, and lands in the same transaction
history as a gateway payment. Reconciliation later is then one table, not two.

`automatic = False` is the whole point: `verify()` never returns paid on its
own. Somebody in the admin has to say so, and that action is recorded with
their name.
"""
from __future__ import annotations

from django.conf import settings

from .base import PaymentProvider, StartResult, VerifyResult


class ManualTransferProvider(PaymentProvider):
    key = "manual"
    label = "کارت به کارت / واریز بانکی"
    automatic = False

    def is_configured(self) -> bool:
        # Needs somewhere for the customer to send the money.
        conf = getattr(settings, "UPMARKET_PAYMENT", {})
        return bool((conf.get("MANUAL_ACCOUNT_INFO") or "").strip())

    def start(self, *, amount_toman: int, description: str, callback_url: str,
              reference: str) -> StartResult:
        conf = getattr(settings, "UPMARKET_PAYMENT", {})
        # There is no gateway to redirect to; the caller shows instructions and
        # the customer uploads a receipt.
        return StartResult(
            token=reference,
            redirect_url="",
            raw={"account_info": conf.get("MANUAL_ACCOUNT_INFO", "")},
        )

    def verify(self, *, token: str, amount_toman: int) -> VerifyResult:
        return VerifyResult(
            paid=False,
            reference="",
            amount=amount_toman,
            raw={},
            message="این پرداخت باید توسط انسان تأیید شود.",
        )
