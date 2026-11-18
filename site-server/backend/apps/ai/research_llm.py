"""The optional model step for competitor / trend research.

Every feature that uses this works **without** it (heuristics first); the model
is asked only to *confirm* or *rank* what the heuristic already found, and only
when a text provider is actually reachable. A dead GPU node therefore costs one
fast health probe (cached for a minute), not a two-minute timeout per request.
With the two-path router (local ⇄ Metis) "reachable" means at least one of the two paths
can be tried right now — decided from the database, never by calling Metis or the node.

Uses the existing gateway (policy check, provider choice) and
``recorded_json_call`` (audit row per attempt) without changing either.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

STATUS_TTL = 60


class LLMUnavailable(Exception):
    """هیچ مسیری برای مدل نیست. ``parkable`` = با صبر درست می‌شود (گرهٔ پردازش خاموش/شلوغ، اعتبارِ متیس، مهلت) ⇒ می‌شود «در صف تا روشن
    شدنِ سرورِ پردازش» گذاشت (compute.deferred)؛ کلیدِ نادرست / «مدل نصب نیست» ⇒ False؛ نامعلوم ⇒ None."""

    def __init__(self, *args, parkable: bool | None = None):
        super().__init__(*args)
        self.parkable = None if parkable is None else bool(parkable)


def _probe(store) -> tuple[bool, str, bool]:
    """(reachable, why, parkable). Cached briefly. parkable = «با صبر درست می‌شود» (فقط وقتی reachable نیست معنا دارد)."""
    key = f"research-llm-status:{getattr(store, 'pk', 0)}"
    cached = cache.get(key)
    if cached is not None:
        c = list(cached)
        return bool(c[0]), str(c[1]), (bool(c[2]) if len(c) > 2 else False)
    parkable = False
    try:
        from services.ai import factory, gateway, providers, routing

        provider = gateway.text_provider(store, kind=routing.RESEARCH)
        if isinstance(provider, routing.RoutedTextProvider):
            # دو مسیر (لوکال/متیس): کافی است یکی قابل‌استفاده باشد؛ بی‌هیچ درخواستی به متیس یا گره
            ok, note = provider.availability()
            if not ok:
                from apps.compute.deferred import is_outage

                parkable = is_outage(provider.unavailable_error())
        else:
            resolved = gateway.resolve(providers.TEXT, store)
            ok, note = factory.health(resolved)
    except Exception as exc:  # noqa: BLE001 — "not available" is the answer
        ok, note = False, f"{type(exc).__name__}: {exc}"
    result = (bool(ok), str(note)[:300], bool(parkable) and not ok)
    cache.set(key, list(result), STATUS_TTL)
    return result


def status(store) -> tuple[bool, str]:
    """(reachable, why) for this store's text provider. Cached briefly."""
    ok, note, _parkable = _probe(store)
    return ok, note


def outage(store) -> bool:
    """مدل الان نیست ولی «با صبر درست می‌شود» (⇒ ارزشِ «در صف تا روشن شدنِ سرورِ پردازش» دارد)؟"""
    ok, _note, parkable = _probe(store)
    return (not ok) and parkable


def ask_json(store, *, prompt_id: str, prompt: str, system: str, validate, job=None) -> dict:
    """One audited JSON call, or LLMUnavailable without waiting on a dead node."""
    ok, note = status(store)
    if not ok:
        raise LLMUnavailable(note, parkable=outage(store))
    from apps.ai.models import AIRequest
    from apps.ai.services import recorded_json_call
    from services.ai.gateway import text_provider
    from services.ai.priority import RESEARCH
    from services.ai.router import TASK_RESEARCH, models_for

    parsed, _ = recorded_json_call(
        job=job,
        store=store,
        task_type=AIRequest.TaskType.REASONING,
        prompt_id=prompt_id,
        prompt_version="1",
        # پژوهش = مدلِ استدلالِ عمیق (qwq:32b)، نه مدلِ سریعِ متنِ روزمره
        provider=text_provider(store, kind=RESEARCH),
        models=models_for(TASK_RESEARCH),
        prompt=prompt,
        system=system,
        validate=validate,
        validation_message="پاسخِ مدل قالبِ خواسته‌شده را نداشت",
    )
    return parsed or {}
