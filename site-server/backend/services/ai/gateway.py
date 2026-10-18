"""The one door between business logic and any AI provider.

Nothing under `apps/` builds an AI client itself. It asks the gateway for a
capability *on behalf of a store*, and the gateway decides which provider may
answer — checking the store's data policy before handing anything back.

    from services.ai import gateway
    provider = gateway.text_provider(store)

The `store` argument is required, and that is the point. `factory.text_provider()`
used to exist without one, which is precisely how a platform-wide provider
switch could start sending one shop's customer messages to a foreign API with
the owner neither seeing it nor agreeing. A call that cannot name whose data it
is carrying has no business making it.

When policy leaves no provider standing, the call raises `PolicyBlocked` rather
than quietly falling through to whatever is available — a store that chose
`Local Only` and got a silent API call would have been better off with no
feature at all.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from . import factory, providers

logger = logging.getLogger(__name__)

# Data classes, mirrored from ModelProvider.DataClass so callers do not have to
# import a Django model to name what they are about to send.
PRODUCT = "PRODUCT"
BRAND = "BRAND"
CUSTOMER = "CUSTOMER"

LOCAL_ONLY = "LOCAL_ONLY"
APPROVED_EXTERNAL = "APPROVED_EXTERNAL"
HYBRID = "HYBRID"

_MODE_LABEL = {
    LOCAL_ONLY: "فقط لوکال",
    APPROVED_EXTERNAL: "فقط سرویس‌های تأییدشده",
    HYBRID: "ترکیبی",
}

_DATA_LABEL = {
    PRODUCT: "محصول",
    BRAND: "برند",
    CUSTOMER: "پیام مشتری",
}


class GatewayError(RuntimeError):
    """Base for every refusal that comes from the gateway rather than a provider."""


class PolicyBlocked(GatewayError):
    """No provider may serve this capability under the store's data policy.

    Carries the per-provider reasons so the panel can say *why* instead of
    showing a bare failure — "GPU نیست" and "سیاست فروشگاه اجازه نمی‌دهد" need
    very different actions from the owner.
    """

    def __init__(self, message: str, capability: str, reasons: list[str] | None = None):
        super().__init__(message)
        self.capability = capability
        self.reasons = reasons or []


@dataclass(frozen=True)
class Policy:
    """A store's effective data policy — from its row, or the platform default."""

    mode: str
    allow_customer_data_external: bool
    is_default: bool = False

    @property
    def label(self) -> str:
        return _MODE_LABEL.get(self.mode, self.mode)


def _platform_default() -> Policy:
    """What a store gets before anyone touches the setting.

    HYBRID keeps every existing install behaving exactly as it did; an operator
    who wants the conservative default sets AI_DEFAULT_POLICY=LOCAL_ONLY.
    """
    mode = str(settings.UPMARKET_AI.get("AI_DEFAULT_POLICY", HYBRID)).upper()
    if mode not in _MODE_LABEL:
        logger.warning("AI_DEFAULT_POLICY=%s شناخته نشد؛ HYBRID استفاده شد.", mode)
        mode = HYBRID
    return Policy(mode=mode, allow_customer_data_external=False, is_default=True)


def policy_for(store) -> Policy:
    """The policy in force for this store. Never None."""
    if store is None:
        return _platform_default()
    row = getattr(store, "ai_policy", None)
    if row is None:
        return _platform_default()
    return Policy(
        mode=row.mode,
        allow_customer_data_external=row.allow_customer_data_external,
        is_default=False,
    )


def _row_for(resolved: providers.Resolved):
    """The ModelProvider behind a Resolved, when there is one.

    Defaults resolved from `.env` have no row, so their governance metadata has
    to be inferred: local means on-premise, an API means we know nothing about
    it beyond the URL — which is itself the honest answer.
    """
    if resolved.row_id is None:
        return None
    from apps.ai.models import ModelProvider

    return ModelProvider.objects.filter(pk=resolved.row_id).first()


def _allowed_data_for(resolved: providers.Resolved) -> list[str]:
    row = _row_for(resolved)
    if row is not None:
        return row.effective_allowed_data
    if resolved.is_local:
        return [PRODUCT, BRAND, CUSTOMER]
    # An .env-configured API was never reviewed by anyone, so it gets the same
    # narrow default a freshly created external row gets.
    return [PRODUCT, BRAND]


def _is_approved(resolved: providers.Resolved) -> bool:
    if resolved.is_local:
        return True
    row = _row_for(resolved)
    return bool(row and row.is_approved)


def check(resolved: providers.Resolved, policy: Policy, data_class: str) -> str | None:
    """Why this provider may not be used, or None if it may.

    Returns the reason as a sentence meant to be read by the shop owner, not
    only logged.
    """
    if resolved.is_local:
        return None

    if policy.mode == LOCAL_ONLY:
        return f"{resolved.name} سرویس بیرونی است و سیاست این فروشگاه «فقط لوکال» است."

    if policy.mode == APPROVED_EXTERNAL and not _is_approved(resolved):
        return (
            f"{resolved.name} هنوز تأیید نشده و سیاست این فروشگاه فقط "
            "سرویس‌های تأییدشده را می‌پذیرد."
        )

    if data_class not in _allowed_data_for(resolved):
        # Name the data class. "not allowed for this data type" sends the owner
        # to the wrong screen; "not allowed to receive customer messages" does not.
        label = _DATA_LABEL.get(data_class, data_class)
        return f"{resolved.name} اجازه‌ی دریافت داده‌ی «{label}» را ندارد."

    if data_class == CUSTOMER and not policy.allow_customer_data_external:
        return (
            "پیام‌های مشتری به سرویس بیرونی فرستاده نمی‌شوند مگر اینکه "
            "مالک فروشگاه صریحاً اجازه داده باشد."
        )

    return None


def resolve(capability: str, store, data_class: str = PRODUCT) -> providers.Resolved:
    """The provider that may answer this capability for this store.

    Raises PolicyBlocked when every candidate is refused, with the reasons.
    """
    policy = policy_for(store)
    found = providers.candidates(capability)
    if not found:
        raise PolicyBlocked(
            f"هیچ سرویسی برای «{capability}» تنظیم نشده است.", capability,
        )

    reasons = []
    for resolved in found:
        reason = check(resolved, policy, data_class)
        if reason is None:
            if not resolved.is_local:
                logger.info(
                    "external %s for store=%s via %s (policy=%s, data=%s)",
                    capability, getattr(store, "pk", None), resolved.name,
                    policy.mode, data_class,
                )
            return resolved
        reasons.append(reason)

    raise PolicyBlocked(
        f"سیاست داده‌ی این فروشگاه اجازه‌ی استفاده از هیچ سرویس «{capability}» را نمی‌دهد. "
        + reasons[0],
        capability,
        reasons,
    )


def client(capability: str, store, data_class: str = PRODUCT):
    """A usable provider client, after the policy check."""
    return factory.build(resolve(capability, store, data_class))


def text_provider(store, data_class: str = PRODUCT):
    """Reasoning, analysis, research, captions, scripts."""
    return client(providers.TEXT, store, data_class)


def vision_provider(store, data_class: str = PRODUCT):
    """Reads a product photo."""
    return client(providers.VISION, store, data_class)


def provider_for_task(task_type: str, store, data_class: str = PRODUCT):
    """`services.ai.router` task type → client."""
    capability = providers.TASK_CAPABILITY.get(task_type, providers.TEXT)
    return client(capability, store, data_class)


def model_name_for(capability: str, store, data_class: str = PRODUCT) -> str | None:
    """Which model will actually run — recorded on every AIRequest row."""
    try:
        return resolve(capability, store, data_class).model_name
    except PolicyBlocked:
        return None


def explain(store, data_class: str = PRODUCT) -> list[dict]:
    """What will serve each capability for this store, and what will not.

    This is the honest version of the panel's «موتور هوش مصنوعی» card: it shows
    the chosen provider, whether the data leaves our servers, and — when
    nothing is usable — the reason.
    """
    from apps.ai.models import ModelProvider

    out = []
    for capability, label in ModelProvider.Capability.choices:
        entry = {
            "capability": capability,
            "label": label,
            "provider": None,
            "kind": None,
            "model": None,
            "local": None,
            "data_location": None,
            "blocked": False,
            "reason": None,
        }
        try:
            chosen = resolve(capability, store, data_class)
        except PolicyBlocked as exc:
            entry["blocked"] = True
            entry["reason"] = exc.reasons[0] if exc.reasons else str(exc)
        else:
            row = _row_for(chosen)
            entry.update({
                "provider": chosen.name,
                "kind": chosen.kind,
                "model": chosen.model_name,
                "local": chosen.is_local,
                "data_location": (
                    row.data_location if row is not None
                    else ("ON_PREMISE" if chosen.is_local else "UNKNOWN")
                ),
            })
        out.append(entry)
    return out
