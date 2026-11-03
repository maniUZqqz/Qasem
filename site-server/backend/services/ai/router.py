"""Task-type → model routing. Never hardcode model names in business logic.

`models_for` returns an ordered list of models that are ACTUALLY installed on
this machine (see services.ai.models_registry): the configured preference
first, then fallbacks. Callers try them in order so one model that does not
fit in VRAM can no longer take a whole feature down (beter.md v2 #3).

Task types (1405/08/12): REASONING = everyday text (content, captions, chat, ad copy — a fast model),
RESEARCH = deep reasoning (market / competitor research, call analysis — a slow, careful model),
CODE and VISION as before. `services.ai.priority.TASK_KIND` maps each to the owner's setting.
"""
from . import models_registry

TASK_REASONING = "REASONING"
TASK_RESEARCH = "RESEARCH"
TASK_VISION = "VISION"
TASK_CODE = "CODE"

TASKS = (TASK_REASONING, TASK_RESEARCH, TASK_VISION, TASK_CODE)


def configured_model(task_type: str) -> str:
    """The default model for this task: .env (MODEL_TEXT / MODEL_REASONING / MODEL_VISION / MODEL_CODER), else the built-in default."""
    if task_type not in TASKS:
        raise ValueError(f"Unknown AI task type: {task_type}")
    from . import priority

    return priority.env_model(priority.kind_of_task(task_type))


def models_for(task_type: str) -> list[str]:
    """Ordered candidates for this task; never empty.

    The local model the owner picked for this kind of work (apps.ai.AiPriority — «مدل لوکال» dropdowns) goes first
    when one is picked; otherwise the .env preference decides, as before.
    """
    configured_model(task_type)  # validates the task type
    found = models_registry.candidates(task_type)
    found = found or [configured_model(task_type)]
    try:
        from . import priority

        cfg = priority.config()
        picked = (cfg.models or {}).get(priority.kind_of_task(task_type))
    except Exception:  # noqa: BLE001 — a setting must never break model lookup
        picked = ""
    if picked:
        found = [picked] + [m for m in found if m != picked]
    return found


def model_for(task_type: str) -> str:
    """The single best model for this task (first candidate)."""
    return models_for(task_type)[0]
