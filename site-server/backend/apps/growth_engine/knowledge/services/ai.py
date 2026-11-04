"""The one place the AI writer talks to the platform's AI routing (``services.ai.gateway``).

The gateway is the platform's single door to AI: it tries the processing node first (local gemma3:12b) and Metis after it (or the
other way round, as the owner's priority setting says), and it classifies every failure in Persian ("اعتبار تمام شده (۴۰۲)",
"سرورِ پردازش خاموش است"). Growth Engine passes NO store (this is internal marketing, not a shop's data) and names the data class
``BRAND`` (public facts about a business and about our own product), so the platform's default data policy applies.

Nothing else imports the gateway: tests replace ``complete_json`` and never make a real AI call.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

UNAVAILABLE_PREFIX = "هوش مصنوعی الان در دسترس نیست. "
TEMPLATE_HINT = " می‌توانید همین پیام را از قالب بسازید؛ قالب‌ها بدونِ هوش مصنوعی کار می‌کنند."
TIMEOUT_SECONDS = 240


class AiUnavailable(Exception):
    """No route could answer (node off, credit gone, policy ...). ``message`` is Persian and says what to do."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _reason(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text[:500] if text else type(exc).__name__


def complete_json(system: str, prompt: str, *, timeout: int = TIMEOUT_SECONDS) -> tuple[dict, dict]:
    """Ask the routed text model for a JSON object. Returns ``(parsed, route)``; ``route`` = ``{"via", "model", "attempts"}``.

    Raises ``AiUnavailable`` (never anything else) when no route answers."""
    try:
        from services.ai import gateway
        from services.ai.router import TASK_REASONING, models_for

        provider = gateway.text_provider(None, gateway.BRAND, kind="text")
        models = models_for(TASK_REASONING)
        result = provider.generate_json(models[0] if models else None, prompt, system=system, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - every failure of every route becomes one plain message
        logger.info("growth ai writer: no route answered (%s)", type(exc).__name__)
        raise AiUnavailable(UNAVAILABLE_PREFIX + _reason(exc) + "." + TEMPLATE_HINT) from exc
    parsed = result[0] if isinstance(result, (tuple, list)) and result else result
    if not isinstance(parsed, dict):
        raise AiUnavailable("پاسخِ هوش مصنوعی ساختارِ درست نداشت." + TEMPLATE_HINT)
    route = {
        "via": getattr(provider, "answered_via", "") or getattr(provider, "answered_by", "") or "",
        "model": (provider.last_model() if hasattr(provider, "last_model") else "") or "",
        "attempts": list(getattr(provider, "attempts", []) or [])[:4],
    }
    return parsed, route


def status() -> dict:
    """What the AI routing looks like right now (best effort; never raises): the order the owner chose and whether each side is ready."""
    try:
        from services.ai import priority, routing

        cfg = priority.config()
        order = cfg.order("text")
        node = routing.node_state("text")
        return {
            "known": True, "order": order, "first": order[0] if order else "",
            "local": {"ready": bool(node.get("ready")), "reason": "" if node.get("ready") else str(node.get("reason") or "")},
            "model": priority.local_model("text", cfg),
        }
    except Exception as exc:  # noqa: BLE001
        return {"known": False, "reason": _reason(exc)}
