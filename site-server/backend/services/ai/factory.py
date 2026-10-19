"""Turn a resolved provider row into a usable client.

This module knows *how* to speak to Ollama, ComfyUI or an OpenAI-compatible
API. It deliberately does not decide *whether* a given store's data may go
there — that is `services.ai.gateway`, and business logic calls the gateway,
never this module.
"""
from __future__ import annotations

import logging

from . import providers
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


def build(resolved: providers.Resolved):
    """Turn a resolved provider row into a usable client."""
    if resolved.kind == "OLLAMA":
        return OllamaProvider(
            base_url=resolved.base_url, timeout=resolved.timeout_s, model=resolved.model_name,
        )
    if resolved.kind in ("OPENAI", "HTTP"):
        return OpenAICompatProvider(
            base_url=resolved.base_url,
            api_key=resolved.api_key,
            model=resolved.model_name,
            timeout=resolved.timeout_s,
            options=resolved.options,
        )
    raise ValueError(f"«{resolved.kind}» متن تولید نمی‌کند.")


def unchecked(capability: str):
    """Build the top provider for a capability with **no policy check**.

    Only for operator-facing tooling that is about the providers themselves —
    the admin health probe, `manage.py selftest`. Business logic must go through
    `services.ai.gateway`, which knows whose data is being sent and whether that
    store allows it to leave. `apps/ai/tests_boundary.py` fails the build if a
    task or view imports this.
    """
    chosen = providers.primary(capability)
    if chosen is None:
        return OllamaProvider(), None
    logger.info(
        "%s → %s (%s · %s)",
        capability, chosen.name, chosen.kind, chosen.model_name,
    )
    return build(chosen), chosen


def health(resolved: providers.Resolved) -> tuple[bool, str]:
    """Probe a provider without running a real job. Used by the admin action."""
    try:
        if resolved.kind == "OLLAMA":
            from services.net import is_listening

            from . import models_registry, ollama_remote

            if ollama_remote.use_remote(resolved.base_url):
                nodes = ollama_remote.ollama_nodes(resolved.base_url)
                if not nodes:
                    return False, ollama_remote.unavailable_message(resolved.base_url)
                names = [m["name"] for m in ollama_remote.installed_models(resolved.base_url)]
                found = next(
                    (n for n in names if models_registry._same_model(resolved.model_name, n)), None,
                )
                where = "، ".join(n.name for n in nodes)
                if not found:
                    return False, f"مدل «{resolved.model_name}» روی سرورِ پردازش ({where}) نصب نیست."
                return True, f"سرورِ پردازش آنلاین ({where})؛ مدل {found} آماده است."

            if not is_listening(resolved.base_url):
                return False, f"چیزی روی {resolved.base_url} گوش نمی‌دهد."

            found = models_registry.resolve_installed(resolved.model_name)
            if not found:
                return False, f"مدل «{resolved.model_name}» روی این Ollama نصب نیست."
            return True, f"مدل {found} آماده است."

        if resolved.kind == "COMFYUI":
            from services.comfyui import remote
            from services.net import is_listening

            if remote.is_agent_url(resolved.base_url):
                nodes = remote.comfy_nodes_online(resolved.base_url)
                if not nodes:
                    return False, "هیچ سرورِ پردازشی با ComfyUI آنلاین نیست (صفحهٔ «سرورهای پردازش»)."
                return True, "سرورِ پردازش آنلاین: " + "، ".join(n.name for n in nodes)
            if not is_listening(resolved.base_url):
                return False, f"ComfyUI روی {resolved.base_url} بالا نیست."
            return True, "ComfyUI پاسخ می‌دهد."

        if resolved.kind in ("OPENAI", "HTTP"):
            return build(resolved).health()

        if resolved.kind == "REPLICATE":
            from services.media.api_media import replicate_health

            return replicate_health(resolved)

    except Exception as exc:  # noqa: BLE001 — the admin wants the real reason
        return False, f"{type(exc).__name__}: {exc}"
    return False, f"نوع «{resolved.kind}» شناخته نشد."
