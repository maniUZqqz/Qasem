"""The optional model step for competitor / trend research.

Every feature that uses this works **without** it (heuristics first); the model
is asked only to *confirm* or *rank* what the heuristic already found, and only
when a text provider is actually reachable. A dead GPU node therefore costs one
fast health probe (cached for a minute), not a two-minute timeout per request.

Uses the existing gateway (policy check, provider choice) and
``recorded_json_call`` (audit row per attempt) without changing either.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

STATUS_TTL = 60


class LLMUnavailable(Exception):
    pass


def status(store) -> tuple[bool, str]:
    """(reachable, why) for this store's text provider. Cached briefly."""
    key = f"research-llm-status:{getattr(store, 'pk', 0)}"
    cached = cache.get(key)
    if cached is not None:
        return tuple(cached)
    try:
        from services.ai import factory, gateway, providers

        resolved = gateway.resolve(providers.TEXT, store)
        ok, note = factory.health(resolved)
    except Exception as exc:  # noqa: BLE001 — "not available" is the answer
        ok, note = False, f"{type(exc).__name__}: {exc}"
    result = (bool(ok), str(note)[:300])
    cache.set(key, list(result), STATUS_TTL)
    return result


def ask_json(store, *, prompt_id: str, prompt: str, system: str, validate, job=None) -> dict:
    """One audited JSON call, or LLMUnavailable without waiting on a dead node."""
    ok, note = status(store)
    if not ok:
        raise LLMUnavailable(note)
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from services.ai.gateway import text_provider
    from services.ai.router import TASK_REASONING, models_for

    parsed, _ = recorded_json_call(
        job=job,
        store=store,
        task_type=AIRequest.TaskType.REASONING,
        prompt_id=prompt_id,
        prompt_version="1",
        provider=text_provider(store),
        models=models_for(TASK_REASONING),
        prompt=prompt,
        system=system,
        validate=validate,
        validation_message="پاسخِ مدل قالبِ خواسته‌شده را نداشت",
    )
    return parsed or {}
