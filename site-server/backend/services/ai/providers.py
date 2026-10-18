"""Capability → provider resolution.

Business logic asks "who can do TEXT?" and gets an ordered list of resolved
providers. It never learns whether the answer came from the RTX 3060 in the
next room or from a paid API, which is the whole point: swapping the two is
an admin decision (apps.ai.models.ModelProvider), not a code change.

When no provider row exists for a capability the configured `.env` defaults
are returned instead, so an untouched install behaves exactly as before.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

TEXT = "TEXT"
VISION = "VISION"
IMAGE = "IMAGE"
VIDEO = "VIDEO"

# task type used by services.ai.router → capability
TASK_CAPABILITY = {"REASONING": TEXT, "CODE": TEXT, "VISION": VISION}


@dataclass(frozen=True)
class Resolved:
    """One usable way to serve a capability."""

    capability: str
    kind: str
    name: str
    base_url: str
    api_key: str
    model_name: str
    timeout_s: int
    options: dict = field(default_factory=dict)
    is_local: bool = True
    row_id: int | None = None

    @property
    def uses_gpu(self) -> bool:
        """Local work consumes our own GPU minutes; remote work does not."""
        return self.is_local


def _conf() -> dict:
    return settings.UPMARKET_AI


#: Which local service serves each capability. The launcher needs this to
#: decide what to start: choosing an API for video alone should not stop
#: Ollama, and choosing one for text alone should not stop ComfyUI.
LOCAL_SERVICE = {
    TEXT: "ollama",
    VISION: "ollama",
    IMAGE: "comfyui",
    VIDEO: "comfyui",
}

#: Per-capability override key in .env.
_MODE_KEY = {
    TEXT: "AI_MODE_TEXT",
    VISION: "AI_MODE_TEXT",  # vision rides with text: same Ollama, same choice
    IMAGE: "AI_MODE_IMAGE",
    VIDEO: "AI_MODE_VIDEO",
}


def api_mode(capability: str | None = None) -> bool:
    """Is this capability served by an API rather than our own hardware?

    Called with no argument it answers for text/vision, which is what it always
    meant before per-capability modes existed — so old call sites keep working.

    Two ways to say "use an API", and the explicit one wins:

    * `AI_MODE_TEXT=api` / `AI_MODE_IMAGE=api` / `AI_MODE_VIDEO=api` — chosen
      deliberately, usually by the launcher's first-run question.
    * `AI_API_BASE_URL` being set at all — the older shortcut, which still
      implies text and vision come from an API.

    Image and video need a media API token to mean anything, so `api` without
    one is treated as local: a launcher that skipped ComfyUI on the strength of
    a setting with no credentials behind it would leave the product unable to
    render anything, with no error until the first job.
    """
    conf = _conf()
    if capability in (IMAGE, VIDEO):
        declared = str(conf.get(_MODE_KEY[capability], "")).strip().lower()
        if declared == "api":
            return bool(conf.get("MEDIA_API_TOKEN") or conf.get("MEDIA_API_BASE_URL"))
        return False

    declared = str(conf.get("AI_MODE_TEXT", "")).strip().lower()
    if declared == "api":
        return bool(conf.get("AI_API_BASE_URL"))
    if declared == "local":
        return False
    return bool(conf.get("AI_API_BASE_URL"))


def local_services_needed() -> set[str]:
    """Which local engines this machine actually has to launch.

    Answered from the resolved providers, not from .env alone, so a
    ModelProvider row pointing TEXT at an API is honoured too — the launcher
    and the product agree about what is running.
    """
    needed = set()
    for capability, service in LOCAL_SERVICE.items():
        try:
            if uses_own_gpu(capability):
                needed.add(service)
        except Exception:  # noqa: BLE001 — before migrations, assume local
            needed.add(service)
    return needed


def _default_for(capability: str) -> Resolved | None:
    """The provider implied by .env when the database has no rows."""
    conf = _conf()
    if capability in (TEXT, VISION):
        if api_mode(capability):
            model_key = "AI_API_MODEL_VISION" if capability == VISION else "AI_API_MODEL_TEXT"
            return Resolved(
                capability=capability,
                kind="OPENAI",
                name="API سازگار با OpenAI (پیش‌فرض .env)",
                base_url=conf["AI_API_BASE_URL"],
                api_key=conf["AI_API_KEY"],
                model_name=conf[model_key],
                timeout_s=int(conf.get("AI_API_TIMEOUT", 180)),
                is_local=False,
            )
        key = "MODEL_VISION" if capability == VISION else "MODEL_REASONING"
        return Resolved(
            capability=capability,
            kind="OLLAMA",
            name="Ollama (پیش‌فرض .env)",
            base_url=conf["OLLAMA_BASE_URL"],
            api_key="",
            model_name=conf[key],
            timeout_s=int(conf.get("OLLAMA_TIMEOUT", 600)),
            is_local=True,
        )
    if capability in (IMAGE, VIDEO):
        if api_mode(capability):
            return Resolved(
                capability=capability,
                kind="REPLICATE",
                name="API تصویر/ویدیو (پیش‌فرض .env)",
                base_url=conf.get("MEDIA_API_BASE_URL", ""),
                api_key=conf.get("MEDIA_API_TOKEN", ""),
                model_name=conf.get(
                    "MEDIA_API_MODEL_IMAGE" if capability == IMAGE
                    else "MEDIA_API_MODEL_VIDEO", "",
                ),
                timeout_s=int(conf.get("MEDIA_API_TIMEOUT", 900)),
                is_local=False,
            )
        return Resolved(
            capability=capability,
            kind="COMFYUI",
            name="ComfyUI (پیش‌فرض .env)",
            base_url=conf["COMFYUI_BASE_URL"],
            api_key="",
            model_name="flux_txt2img@v1" if capability == IMAGE else "wan22_i2v@v1",
            timeout_s=int(conf.get("COMFYUI_TIMEOUT", 900)),
            is_local=True,
        )
    return None


def _from_row(row) -> Resolved:
    conf = _conf()
    base = row.base_url or (
        conf["OLLAMA_BASE_URL"] if row.kind == "OLLAMA"
        else conf["COMFYUI_BASE_URL"] if row.kind == "COMFYUI"
        else ""
    )
    return Resolved(
        capability=row.capability,
        kind=row.kind,
        name=row.name,
        base_url=base,
        api_key=row.api_key,
        model_name=row.model_name,
        timeout_s=row.timeout_s,
        options=row.options or {},
        is_local=row.is_local,
        row_id=row.pk,
    )


def candidates(capability: str) -> list[Resolved]:
    """Every active provider for this capability, best first. Never empty."""
    from apps.ai.models import ModelProvider

    try:
        rows = list(
            ModelProvider.objects.filter(capability=capability, is_active=True)
            .order_by("priority", "id")
        )
    except Exception as exc:  # table missing during an early migration
        logger.info("Could not read providers (%s); using .env defaults", exc)
        rows = []

    resolved = [_from_row(row) for row in rows]
    if not resolved:
        fallback = _default_for(capability)
        return [fallback] if fallback else []
    return resolved


def primary(capability: str) -> Resolved | None:
    """The provider that should answer first."""
    found = candidates(capability)
    return found[0] if found else None


def uses_own_gpu(capability: str) -> bool:
    """Does this capability currently run on our hardware?

    Capacity planning depends on the answer: a capability served by an API
    costs money per call but zero GPU minutes, so it does not compete for the
    single GPU slot.
    """
    chosen = primary(capability)
    return bool(chosen and chosen.uses_gpu)


def summary() -> list[dict]:
    """What is serving each capability right now — for the admin and API."""
    from apps.ai.models import ModelProvider

    out = []
    for capability, label in ModelProvider.Capability.choices:
        found = candidates(capability)
        chosen = found[0] if found else None
        out.append({
            "capability": capability,
            "label": label,
            "provider": chosen.name if chosen else None,
            "kind": chosen.kind if chosen else None,
            "model": chosen.model_name if chosen else None,
            "local": chosen.is_local if chosen else None,
            "fallbacks": len(found) - 1 if found else 0,
        })
    return out
