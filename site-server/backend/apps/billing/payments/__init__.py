"""Provider registry.

`get_provider()` is the only way the rest of the code obtains a gateway, so
there is exactly one place that decides what is available and whether it is
usable.
"""
from __future__ import annotations

from django.conf import settings

from .base import PaymentError, PaymentProvider, StartResult, VerifyResult
from .manual import ManualTransferProvider
from .sandbox import SandboxProvider
from .zarinpal import ZarinPalProvider

_CLASSES = [ZarinPalProvider, ManualTransferProvider, SandboxProvider]


def all_providers() -> list[PaymentProvider]:
    return [cls() for cls in _CLASSES]


def available_providers() -> list[PaymentProvider]:
    """Only the ones that could actually take a payment right now."""
    return [p for p in all_providers() if p.is_configured()]


def get_provider(key: str) -> PaymentProvider:
    for provider in all_providers():
        if provider.key == key:
            if not provider.is_configured():
                raise PaymentError(f"درگاه «{provider.label}» پیکربندی نشده است.")
            return provider
    raise PaymentError(f"درگاه «{key}» شناخته نشد.")


def default_provider_key() -> str:
    """What the UI should pre-select."""
    configured = getattr(settings, "UPMARKET_PAYMENT", {}).get("DEFAULT_PROVIDER", "")
    available = {p.key for p in available_providers()}
    if configured in available:
        return configured
    for key in ("zarinpal", "sandbox", "manual"):
        if key in available:
            return key
    return ""


__all__ = [
    "PaymentError",
    "PaymentProvider",
    "StartResult",
    "VerifyResult",
    "all_providers",
    "available_providers",
    "get_provider",
    "default_provider_key",
]
