"""Task-type → model routing. Never hardcode model names in business logic.

`models_for` returns an ordered list of models that are ACTUALLY installed on
this machine (see services.ai.models_registry): the configured preference
first, then fallbacks. Callers try them in order so one model that does not
fit in VRAM can no longer take a whole feature down (beter.md v2 #3).
"""
from django.conf import settings

from . import models_registry

TASK_REASONING = "REASONING"
TASK_VISION = "VISION"
TASK_CODE = "CODE"

_SETTINGS_KEY = {
    TASK_REASONING: "MODEL_REASONING",
    TASK_VISION: "MODEL_VISION",
    TASK_CODE: "MODEL_CODER",
}


def configured_model(task_type: str) -> str:
    """The model named in .env for this task, installed or not."""
    try:
        return settings.UPMARKET_AI[_SETTINGS_KEY[task_type]]
    except KeyError:
        raise ValueError(f"Unknown AI task type: {task_type}")


def models_for(task_type: str) -> list[str]:
    """Ordered candidates for this task; never empty."""
    configured_model(task_type)  # validates the task type
    found = models_registry.candidates(task_type)
    return found or [configured_model(task_type)]


def model_for(task_type: str) -> str:
    """The single best model for this task (first candidate)."""
    return models_for(task_type)[0]
