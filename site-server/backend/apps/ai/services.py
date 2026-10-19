"""Shared AI-call helpers: every orchestrated call is audited in AIRequest/AIResponse."""
import logging
import time

from django.conf import settings

from services import gpu
from services.ai.ollama import (
    OllamaError,
    OllamaMalformedOutput,
    OllamaTimeout,
    OllamaUnavailable,
)

from .models import AIRequest, AIResponse

logger = logging.getLogger(__name__)

_STATUS_FOR_ERROR = [
    (OllamaTimeout, AIRequest.Status.TIMEOUT),
    (OllamaMalformedOutput, AIRequest.Status.MALFORMED_OUTPUT),
    (OllamaError, AIRequest.Status.PROVIDER_ERROR),
]


def _status_for(exc) -> str:
    for error_type, status in _STATUS_FOR_ERROR:
        if isinstance(exc, error_type):
            return status
    return AIRequest.Status.PROVIDER_ERROR


def _models_for_provider(provider, candidates: list[str]) -> list[str]:
    """Let the provider rewrite the router's candidate list for itself.

    `services.ai.router.models_for` names Ollama tags from .env. That is the
    right list for OllamaProvider and the wrong one for an OpenAI-compatible
    API, which answered every one of them with `model_not_supported` — the
    last candidate, `qwen3-vl:30b`, was the name the owner saw in the error.
    A provider that knows which model it was configured with says so here;
    anything else (including the MagicMocks the tests pass) keeps the list.
    """
    chooser = getattr(provider, "select_models", None)
    if not callable(chooser):
        return candidates
    try:
        chosen = chooser(candidates)
    except Exception as exc:  # noqa: BLE001 — a routing hint must never kill the call
        logger.warning("provider.select_models failed (%s); using router candidates", exc)
        return candidates
    if isinstance(chosen, (list, tuple)) and chosen and all(isinstance(m, str) and m for m in chosen):
        if list(chosen) != candidates:
            logger.info("AI models for %s: %s → %s", type(provider).__name__, candidates, list(chosen))
        return list(chosen)
    return candidates


def _single_call(
    *, store, task_type, prompt_id, prompt_version, provider, model, prompt,
    system=None, images=None, job=None, options=None,
):
    """One audited generate_json call against exactly one model."""
    request_row = AIRequest.objects.create(
        store=store,
        job=job,
        task_type=task_type,
        model=model,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        status=AIRequest.Status.OK,
    )
    started = time.monotonic()
    try:
        parsed, raw = provider.generate_json(
            model, prompt, system=system, images=images, options=options
        )
    except Exception as exc:  # noqa: BLE001 — the audit row must never be left "OK"
        request_row.status = _status_for(exc)
        request_row.error = str(exc)[:4000]
        request_row.latency_ms = int((time.monotonic() - started) * 1000)
        request_row.save()
        raise

    request_row.latency_ms = int((time.monotonic() - started) * 1000)
    request_row.save()
    AIResponse.objects.create(request=request_row, raw_output=raw, parsed=parsed, valid=True)
    return parsed, request_row


def recorded_json_call(
    *, store, task_type, prompt_id, prompt_version, provider, prompt,
    model=None, models=None, system=None, images=None, job=None, options=None,
    validate=None, validation_message="AI output failed validation",
):
    """Run generate_json against the first model that works, auditing each try.

    `models` is the ordered candidate list from services.ai.router.models_for
    (installed models only). When the first one fails — it does not fit in
    VRAM, times out, or cannot produce JSON — the next one is tried instead of
    losing the whole feature (beter.md v2 #3). `model=` (single name) is still
    accepted for callers that must pin one model.

    `validate(parsed) -> (ok, problems)` is checked INSIDE the loop on purpose:
    a weaker model most often fails by returning well-formed JSON that is
    missing half the keys, and that has to move on to the next model just like
    a timeout does — not kill the whole job.

    Returns (parsed, request_row). Raises the LAST error when every candidate
    failed.
    """
    candidates = [m for m in (models or ([model] if model else [])) if m]
    if not candidates:
        raise ValueError("recorded_json_call needs `model` or a non-empty `models` list")
    candidates = _models_for_provider(provider, candidates)
    conf = settings.UPMARKET_AI
    max_attempts = 1 if not conf.get("MODEL_FALLBACK_ENABLED", True) else conf.get(
        "MODEL_MAX_ATTEMPTS", 2
    )
    candidates = candidates[: max(1, int(max_attempts))]

    last_error = None
    for index, candidate in enumerate(candidates):
        if index:
            # the previous model is still holding VRAM; evict it before the
            # next attempt or the fallback inherits the same memory pressure
            gpu.unload_ollama_models(except_model=candidate)
            logger.warning(
                "AI call %s: model %s failed (%s) — retrying with %s",
                prompt_id,
                candidates[index - 1],
                last_error,
                candidate,
            )
            if job is not None:
                try:
                    job.mark_progress(
                        job.progress_step,
                        f"مدل قبلی جواب نداد؛ در حال تلاش با مدل بعدی ({candidate})",
                    )
                except Exception:  # noqa: BLE001 — progress text is cosmetic
                    pass
        try:
            parsed, request_row = _single_call(
                store=store,
                task_type=task_type,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                provider=provider,
                model=candidate,
                prompt=prompt,
                system=system,
                images=images,
                job=job,
                options=options,
            )
        except OllamaUnavailable:
            # Ollama is down, not the model — every other candidate would fail
            # against the same dead endpoint, so stop instead of stalling.
            raise
        except OllamaError as exc:
            last_error = exc
            continue

        if validate is None:
            return parsed, request_row

        ok, problems = validate(parsed)
        if ok:
            return parsed, request_row

        request_row.status = AIRequest.Status.VALIDATION_FAILED
        request_row.error = f"Missing/invalid keys: {problems}"[:4000]
        request_row.save()
        last_error = OllamaMalformedOutput(f"{validation_message}: {problems}")

    raise last_error
