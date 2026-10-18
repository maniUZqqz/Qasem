"""ZarinPal.

The most widely used Iranian gateway, and the one a small shop is most likely
to already have a merchant id for. API v4.

Everything here is real and complete — it needs a merchant id in `.env` and
nothing else. Until one is set, `is_configured()` returns False and the
provider is simply not offered.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import PaymentError, PaymentProvider, StartResult, VerifyResult

logger = logging.getLogger(__name__)

LIVE = "https://api.zarinpal.com/pg/v4/payment"
LIVE_START = "https://www.zarinpal.com/pg/StartPay/"
SANDBOX = "https://sandbox.zarinpal.com/pg/v4/payment"
SANDBOX_START = "https://sandbox.zarinpal.com/pg/StartPay/"

TIMEOUT = 20

#: ZarinPal returns 100 on a successful request, and 100/101 on verify —
#: 101 means "already verified", which must be treated as paid rather than as
#: an error, or a double callback loses a real payment.
OK_REQUEST = {100}
OK_VERIFY = {100, 101}


class ZarinPalProvider(PaymentProvider):
    key = "zarinpal"
    label = "زرین‌پال"
    automatic = True

    def __init__(self):
        conf = getattr(settings, "UPMARKET_PAYMENT", {})
        self.merchant_id = (conf.get("ZARINPAL_MERCHANT_ID") or "").strip()
        self.sandbox = bool(conf.get("ZARINPAL_SANDBOX", False))
        self.base = SANDBOX if self.sandbox else LIVE
        self.start_base = SANDBOX_START if self.sandbox else LIVE_START

    def is_configured(self) -> bool:
        # ZarinPal merchant ids are UUIDs; a truncated one fails at request
        # time with an unhelpful message, so check the shape up front.
        return len(self.merchant_id) == 36

    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = requests.post(
                f"{self.base}/{path}", json=payload, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            raise PaymentError(f"زرین‌پال در دسترس نیست: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise PaymentError("پاسخ زرین‌پال قابل خواندن نبود.") from exc

        # v4 answers with {"data": {...}, "errors": [...] | {}}
        errors = body.get("errors")
        if errors:
            if isinstance(errors, dict):
                message = errors.get("message") or str(errors)
            else:
                message = str(errors)
            raise PaymentError(f"زرین‌پال: {message}")
        return body.get("data") or {}

    def start(self, *, amount_toman: int, description: str, callback_url: str,
              reference: str) -> StartResult:
        if not self.is_configured():
            raise PaymentError("شناسه پذیرنده زرین‌پال تنظیم نشده است.")

        data = self._post(
            "request.json",
            {
                "merchant_id": self.merchant_id,
                # ZarinPal bills in Rial. Our prices are Toman. One zero.
                "amount": amount_toman * 10,
                "description": description[:255],
                "callback_url": callback_url,
                "metadata": {"order_id": reference},
            },
        )

        if data.get("code") not in OK_REQUEST or not data.get("authority"):
            raise PaymentError(f"زرین‌پال درخواست را نپذیرفت: {data}")

        authority = data["authority"]
        return StartResult(
            token=authority,
            redirect_url=f"{self.start_base}{authority}",
            raw=data,
        )

    def verify(self, *, token: str, amount_toman: int) -> VerifyResult:
        if not self.is_configured():
            raise PaymentError("شناسه پذیرنده زرین‌پال تنظیم نشده است.")

        data = self._post(
            "verify.json",
            {
                "merchant_id": self.merchant_id,
                "amount": amount_toman * 10,
                "authority": token,
            },
        )

        code = data.get("code")
        paid = code in OK_VERIFY
        # Back to Toman for everyone downstream.
        reported_rial = int(data.get("amount") or 0)
        return VerifyResult(
            paid=paid,
            reference=str(data.get("ref_id") or ""),
            amount=reported_rial // 10 if reported_rial else amount_toman,
            raw=data,
            message="" if paid else f"code={code}",
        )
