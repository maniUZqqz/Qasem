"""Authenticating a shop's own system, and metering what it uses.

The rule that shapes this: **an API call costs exactly what the same action
costs in the panel**. A caption generated through the API spends the same
caption from the same monthly allowance, because it spends the same GPU minute.
Anything else turns the API into a way around the plan, and the GPU does not
care which door the request came through.
"""
from __future__ import annotations

import logging
import time

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import APICall, APIKey, hash_key

logger = logging.getLogger(__name__)

HEADER = "HTTP_X_API_KEY"


class APIKeyUser:
    """A stand-in for `request.user` that is a store, not a person.

    DRF wants a user object. What is actually calling is a shop's server, and
    pretending it is the owner would put their name on every audit row — so
    this carries the store and says plainly that it is not a person.
    """

    is_authenticated = True
    is_anonymous = False
    is_staff = False
    is_superuser = False
    is_active = True

    def __init__(self, key: APIKey):
        self.api_key = key
        self.store = key.store
        self.username = f"api:{key.prefix}"
        # DRF and Django's own helpers assume every user has one. Without it
        # the default throttle raised AttributeError on every real call — a
        # 500 the whole test suite missed, because `IS_TEST` skips throttling.
        self.pk = key.pk
        self.id = key.pk

    def __str__(self):
        return self.username


class APIKeyAuthentication(authentication.BaseAuthentication):
    """`X-Api-Key: up_live_…`

    Deliberately not `Authorization: Bearer` — that header already carries the
    panel's JWT, and a request holding both would be ambiguous about which
    identity the shop meant.
    """

    def authenticate(self, request):
        raw = request.META.get(HEADER, "").strip()
        if not raw:
            return None  # let other authenticators try

        key = APIKey.objects.select_related("store").filter(
            key_hash=hash_key(raw)
        ).first()

        # One message for "no such key" and "revoked key": telling a caller
        # which of the two they hit is telling them whether they guessed a real
        # prefix.
        if key is None or not key.usable:
            raise exceptions.AuthenticationFailed(
                "کلید API معتبر نیست یا باطل شده است."
            )

        key.touch()
        return (APIKeyUser(key), key)

    def authenticate_header(self, request):
        return "X-Api-Key"


def record(request, response, endpoint: str, started: float) -> None:
    """Keep one line about this call so the shop can debug their integration."""
    user = getattr(request, "user", None)
    key = getattr(user, "api_key", None)
    if key is None:
        return
    try:
        APICall.objects.create(
            key=key,
            store=key.store,
            endpoint=endpoint,
            status_code=response.status_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=(
                str(getattr(response, "data", {}).get("error", {}).get("message", ""))[:200]
                if response.status_code >= 400 else ""
            ),
        )
    except Exception as exc:  # noqa: BLE001 — logging must not break the call
        logger.debug("Could not record API call: %s", exc)


def quota_error(exc) -> dict:
    """Turn a QuotaExceeded into something a machine caller can act on."""
    return {
        "error": {
            "code": "quota_exceeded",
            "message": str(exc),
            # Named so an integration can back off rather than retry in a loop.
            "retry_after": "next_billing_period",
        }
    }
