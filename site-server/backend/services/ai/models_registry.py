"""
Which Ollama models does THIS machine actually have?

The main system has a 12 GB card and a fixed set of pulled models. Hardcoding
a model name means a job dies with "model not found", and picking a dense 32B
model that does not fit in VRAM means the run is offloaded to CPU and times
out (beter.md v2 #3: qwq:32b = 18.5 GB → 29/65 layers on GPU → 10-minute
timeout on every market analysis).

So model choice is made at run time from `GET /api/tags`: the configured
preference wins when it is installed, otherwise the next installed candidate
is used, smallest (= most likely to fit the GPU) first. Nothing is ever
invented — if Ollama is unreachable the configured names are returned
unchanged so behaviour matches the old code.
"""
import logging
import threading
import time

import requests
from django.conf import settings

from services.net import is_listening

logger = logging.getLogger(__name__)

TAGS_TIMEOUT = 5
CACHE_SECONDS = 60

# Embedding-only models can never answer a prompt.
EMBEDDING_MARKERS = ("embed", "minilm", "bge-", "gte-")

# Name fragments that mark a multimodal (image-capable) model.
VISION_MARKERS = ("-vl", "vl:", "vision", "llava", "moondream", "minicpm-v", "bakllava", "gemma3")

# task type (services.ai.router) → the settings key holding its model name
TASK_MODEL_KEY = {
    "REASONING": "MODEL_REASONING",
    "VISION": "MODEL_VISION",
    "CODE": "MODEL_CODER",
}

_cache = {"at": 0.0, "models": []}
_lock = threading.Lock()


def _base_url() -> str:
    return settings.UPMARKET_AI["OLLAMA_BASE_URL"].rstrip("/")


def installed(force: bool = False) -> list[dict]:
    """`[{"name", "size"}]` for every pulled model, newest cache within 60s.

    Returns [] when Ollama is unreachable — callers must treat that as
    "unknown", not as "nothing installed".
    """
    from . import ollama_remote

    base = _base_url()
    if ollama_remote.is_agent_url(base) or (
        not getattr(settings, "IS_TEST", False) and ollama_remote.use_remote(base)
    ):
        # Ollama lives on a processing node: it reports its pulled models in
        # every heartbeat (ComputeNode.capabilities["ollama_models"]), so the
        # answer comes from the database — no network, no cache needed.
        return ollama_remote.installed_models(base)
    if getattr(settings, "IS_TEST", False):
        return []  # tests must never touch the network
    with _lock:
        now = time.monotonic()
        # the empty list is cached too: "Ollama is off" is an answer, and
        # re-asking a dead endpoint costs seconds per call on Windows
        if not force and _cache["at"] and now - _cache["at"] < CACHE_SECONDS:
            return _cache["models"]
        if not is_listening(_base_url()):
            logger.info("Ollama is not listening at %s; using configured names", _base_url())
            _cache.update({"at": now, "models": []})
            return []
        try:
            response = requests.get(f"{_base_url()}/api/tags", timeout=TAGS_TIMEOUT)
            response.raise_for_status()
            raw = response.json().get("models") or []
        except Exception as exc:  # noqa: BLE001 — offline dev machine is normal
            logger.info("Could not list Ollama models (%s); using configured names", exc)
            _cache.update({"at": now, "models": []})
            return []
        models = [
            {"name": item.get("name") or item.get("model") or "", "size": int(item.get("size") or 0)}
            for item in raw
        ]
        models = [m for m in models if m["name"]]
        _cache.update({"at": now, "models": models})
        logger.info(
            "Ollama models available: %s",
            ", ".join(f"{m['name']} ({m['size'] / 1e9:.1f}GB)" for m in models) or "none",
        )
        return models


def _same_model(a: str, b: str) -> bool:
    """`qwq` matches `qwq:32b`; `qwq:latest` matches `qwq`."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    a_base, b_base = a.split(":")[0], b.split(":")[0]
    if a_base != b_base:
        return False
    # one side unqualified (or :latest) → treat as the same family
    return ":" not in a or ":" not in b or "latest" in (a.split(":")[1], b.split(":")[1])


def resolve_installed(preferred: str) -> str | None:
    """The exact installed tag matching `preferred`, or None."""
    for model in installed():
        if _same_model(preferred, model["name"]):
            return model["name"]
    return None


def _is_embedding(name: str) -> bool:
    return any(marker in name.lower() for marker in EMBEDDING_MARKERS)


def _is_vision(name: str) -> bool:
    return any(marker in name.lower() for marker in VISION_MARKERS)


def candidates(task_type: str) -> list[str]:
    """Ordered list of models to try for `task_type`, installed ones only.

    Order: the configured model for the task, then the configured fallbacks,
    then every other suitable installed model smallest-first. When Ollama
    cannot be reached the configured names are returned as-is.
    """
    conf = settings.UPMARKET_AI
    preferred = conf.get(TASK_MODEL_KEY.get(task_type, ""), "")
    wants_vision = task_type == "VISION"

    configured = [preferred] + list(conf.get("MODEL_FALLBACKS", []))
    configured = [name for name in configured if name]

    pool = installed()
    if not pool:  # Ollama unreachable → keep the old, configured behaviour
        names = list(dict.fromkeys(configured))
        if wants_vision:
            # a text-only model can never read a product photo, so it is not
            # a usable fallback here even when we cannot see what is installed
            vision_only = [name for name in names if _is_vision(name)]
            return vision_only or names[:1]
        return names

    ordered: list[str] = []
    for name in configured:
        exact = resolve_installed(name)
        if exact and exact not in ordered:
            if wants_vision and not _is_vision(exact):
                continue
            ordered.append(exact)

    extras = sorted(
        (m for m in pool if not _is_embedding(m["name"])),
        key=lambda m: m["size"] or 0,
    )
    for model in extras:
        name = model["name"]
        if name in ordered:
            continue
        if wants_vision and not _is_vision(name):
            continue
        ordered.append(name)

    if not ordered:
        # nothing suitable found (e.g. a vision task with no multimodal model):
        # fall back to whatever was configured and let the call report the truth
        ordered = list(dict.fromkeys(configured))
    return ordered
