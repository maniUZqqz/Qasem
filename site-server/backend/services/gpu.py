"""
Best-effort VRAM coordination between Ollama and ComfyUI on a single GPU.

The main system runs 30B Ollama models AND FLUX/Wan 2.2 on the same card;
loading both at once starves whichever is working. Before ComfyUI work we ask
Ollama to unload its models, and around heavy Ollama work we ask ComfyUI to
free its VRAM. Every call is best-effort: a coordination failure must never
fail the actual generation job.

Controlled by the GPU_AUTO_UNLOAD env var (default: on).
"""

import logging

import requests
from django.conf import settings

from services.net import is_listening

logger = logging.getLogger(__name__)

# Coordination must stay cheap; never let it stall a job.
COORDINATION_TIMEOUT = 15


def _enabled() -> bool:
    if getattr(settings, "IS_TEST", False):
        return False  # never make coordination network calls inside tests
    return bool(settings.UPMARKET_AI.get("GPU_AUTO_UNLOAD", True))


def loaded_ollama_models() -> list[str]:
    """Names of the models Ollama currently holds in memory ([] on error)."""
    base_url = settings.UPMARKET_AI["OLLAMA_BASE_URL"].rstrip("/")
    if not is_listening(base_url):
        return []
    try:
        response = requests.get(f"{base_url}/api/ps", timeout=COORDINATION_TIMEOUT)
        response.raise_for_status()
        return [m.get("name") for m in response.json().get("models", []) if m.get("name")]
    except Exception as exc:  # noqa: BLE001 — coordination is best-effort
        logger.info("GPU coordination: could not list Ollama models (%s)", exc)
        return []


def unload_ollama_models(except_model: str | None = None) -> None:
    """Evict loaded Ollama models from VRAM (keep_alive=0).

    `except_model` keeps one model resident — used before switching models
    inside a job: the vision pass must not stay in VRAM while the reasoning
    model loads, or neither fits on a 12 GB card (beter.md v2 #9).
    """
    if not _enabled():
        return
    base_url = settings.UPMARKET_AI["OLLAMA_BASE_URL"].rstrip("/")
    if not is_listening(base_url):
        return
    keep = (except_model or "").strip().lower()
    for name in loaded_ollama_models():
        if keep and name.strip().lower().split(":")[0] == keep.split(":")[0]:
            continue
        try:
            requests.post(
                f"{base_url}/api/generate",
                json={"model": name, "keep_alive": 0},
                timeout=COORDINATION_TIMEOUT,
            )
            logger.info("GPU coordination: unloaded Ollama model %s", name)
        except Exception as exc:  # noqa: BLE001
            logger.info("GPU coordination: could not unload %s (%s)", name, exc)


def free_comfyui_memory() -> None:
    """Ask ComfyUI to unload its models and free VRAM (/free, ComfyUI >= 2024)."""
    if not _enabled():
        return
    base_url = settings.UPMARKET_AI["COMFYUI_BASE_URL"].rstrip("/")
    if not is_listening(base_url):
        return  # ComfyUI is not running; nothing to free
    try:
        response = requests.post(
            f"{base_url}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=COORDINATION_TIMEOUT,
        )
        if response.status_code == 404:
            # older ComfyUI without /free — nothing we can do, not an error
            logger.info("GPU coordination: ComfyUI has no /free endpoint")
        else:
            logger.info("GPU coordination: ComfyUI VRAM freed")
    except Exception as exc:
        logger.info("GPU coordination: could not free ComfyUI memory (%s)", exc)


def before_comfyui_work() -> None:
    """Call right before submitting a ComfyUI workflow."""
    unload_ollama_models()


def before_ollama_work(model: str | None = None) -> None:
    """Call right before a heavy Ollama call on the ai queue.

    Frees ComfyUI's VRAM and evicts every OTHER Ollama model, so the model
    that is about to run gets the whole card instead of the leftovers.
    """
    free_comfyui_memory()
    unload_ollama_models(except_model=model)
