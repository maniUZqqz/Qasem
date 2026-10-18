"""A gateway that exists only so the whole flow can be tested end to end.

Not a mock inside a test: a real provider you can select in a dev environment,
walk through in a browser, and watch activate a subscription. That matters
because the interesting bugs in payment code live in the round trip — the
redirect, the callback, the double callback — and those never appear in a unit
test that calls `verify()` directly.

Refuses to load unless DEBUG is on. A sandbox provider reachable in production
would be a way to grant free subscriptions.
"""
from __future__ import annotations

from django.conf import settings

from .base import PaymentError, PaymentProvider, StartResult, VerifyResult


class SandboxProvider(PaymentProvider):
    key = "sandbox"
    label = "درگاه آزمایشی (فقط حالت توسعه)"
    automatic = True

    def is_configured(self) -> bool:
        return bool(settings.DEBUG)

    def start(self, *, amount_toman: int, description: str, callback_url: str,
              reference: str) -> StartResult:
        if not settings.DEBUG:
            raise PaymentError("درگاه آزمایشی در حالت production در دسترس نیست.")
        token = f"sandbox-{reference}"
        joiner = "&" if "?" in callback_url else "?"
        return StartResult(
            token=token,
            # Straight back to our own callback, as a gateway would.
            redirect_url=f"{callback_url}{joiner}Authority={token}&Status=OK",
            raw={"sandbox": True, "amount_toman": amount_toman},
        )

    def verify(self, *, token: str, amount_toman: int) -> VerifyResult:
        if not settings.DEBUG:
            raise PaymentError("درگاه آزمایشی در حالت production در دسترس نیست.")
        # A token the test flow marks as failed, so the unhappy path is
        # reachable without needing a real declined card.
        failed = token.endswith("-fail")
        return VerifyResult(
            paid=not failed,
            reference="" if failed else f"SANDBOX-{token[-8:]}",
            amount=amount_toman,
            raw={"sandbox": True},
            message="پرداخت آزمایشی ناموفق" if failed else "",
        )
