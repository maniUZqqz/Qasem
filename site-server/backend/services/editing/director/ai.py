"""The three questions the director asks a model — and ONLY these. Everything else is deterministic.

1. `refine_brief` — «what does this sentence mean?» → recipe, platform, length, pace, Persian title/CTA, discount, look.
2. `extra_steps`  — «what else would you change?» → at most 6 catalogue tool calls on top of the recipe (validated).
3. `vision_review` — «look at these frames of the finished preview» → rubric scores and concrete issues.

A 12B local model cannot edit a timeline by itself; it can pick a recipe, write a good Persian title and notice that the
product is out of frame. So the recipes do the editing and the model fills in the judgement. Every call goes through the
owner's routing (local model on the processing node first, then Metis, in the owner's priority) and through
`recorded_json_call`; when nothing answers the director says WHICH part needed the AI and carries on deterministically.
"""
from __future__ import annotations

import json
import logging

from .. import color
from . import brief as brief_mod
from . import tools
from .runner import validate_plan

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior social-media video editor. You are given a request, a list of media assets and measurements. "
    "You answer with a single valid JSON object and nothing else. You never invent assets, tools or parameters. "
    "All Persian text you write must be natural, short and suitable for an on-screen title."
)

RUBRIC = (
    "hook (a strong picture and text in the first 3 s), pacing (cut rhythm fits the platform), captions (readable, inside "
    "the platform's safe zone), audio (speech clearly above music), product visible, clear call-to-action at the end, length"
)


def call_json(store, *, prompt: str, prompt_id: str, validate, system: str = SYSTEM, job=None, images=None, vision: bool = False,
              version: str = "1") -> tuple[dict | None, dict]:
    """One audited model call → (parsed|None, info). `info` always explains what happened, in the owner's terms."""
    info = {"asked": True, "ok": False, "via": "", "model": "", "error_code": "", "error": "", "fell_back": False, "fallback_reason": ""}
    provider = None
    try:
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from services.ai import gateway
        from services.ai.router import TASK_REASONING, TASK_VISION, models_for

        provider = gateway.vision_provider(store) if vision else gateway.text_provider(store)
        parsed, _ = recorded_json_call(
            job=job, store=store, task_type=AIRequest.TaskType.VISION if vision else AIRequest.TaskType.REASONING,
            prompt_id=prompt_id, prompt_version=version, provider=provider, models=models_for(TASK_VISION if vision else TASK_REASONING),
            prompt=prompt, system=system, images=images, validate=validate, validation_message="جوابِ هوش مصنوعی قابلِ استفاده نبود")
    except Exception as exc:  # noqa: BLE001
        from ..agent import explain_failure

        info["error_code"], info["error"] = explain_failure(exc, provider)
        return None, info
    answered = getattr(provider, "answered_by", "")
    info["model"] = answered if isinstance(answered, str) else ""
    info["fell_back"] = getattr(provider, "fell_back", False) is True
    via = getattr(provider, "answered_via", "")
    info["via"] = "node" if via == "local" else "api" if via == "metis" else ("api" if info["model"] else "")
    info["ok"] = True
    return parsed, info


def _assets_for_prompt(assets: list[dict]) -> list[dict]:
    return [{"ref": a["ref"], "kind": a.get("kind"), "title": str(a.get("title", ""))[:40], "seconds": round(float(a.get("duration") or 0), 1),
             "has_audio": bool(a.get("has_audio"))} for a in assets[:24]]


def _dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def build_brief_prompt(request: str, assets: list[dict], an: dict, current: dict) -> str:
    facts = {"has_speech": an.get("has_speech"), "music_bpm": next((r.get("bpm") for r in an["by_ref"].values() if r.get("kind") == "audio" and r.get("bpm")), None)}
    return "\n".join([
        "Plan a short social-media video from the owner's request and assets.",
        "",
        f"Owner's request (Persian): {request or '(none — choose a good default)'}",
        f"Assets: {_dumps(_assets_for_prompt(assets))}",
        f"Measurements: {_dumps(facts)}",
        f"What keywords already say: {_dumps({k: v for k, v in current.items() if k in ('recipe', 'platform', 'duration', 'pace', 'title', 'discount')})}",
        "",
        f"recipe is one of: {_dumps(list(brief_mod.RECIPES))}",
        f"platform is one of: {_dumps(list(brief_mod.PLATFORMS))}",
        f"look is one of: {_dumps(list(color.LOOKS))} or \"\"",
        "",
        "Rules:",
        "- Do not change something the owner stated explicitly (platform, length, discount, quoted title).",
        "- title: at most 6 Persian words, concrete (product name + benefit). subtitle optional, at most 8 words.",
        "- cta: at most 5 Persian words, an imperative (e.g. «همین حالا سفارش بده»).",
        "- order: the asset refs in the order they should appear, only refs from the list; hook_ref = the asset whose best moment opens the video.",
        "",
        'Answer exactly: {"recipe":"","platform":"","duration":0,"pace":"fast|normal|slow","title":"","subtitle":"","cta":"","discount":0,'
        '"captions":true,"music":true,"look":"","hook_ref":"","order":[],"notes_fa":""}',
    ])


def _validate_brief(parsed) -> tuple[bool, list[str]]:
    if not isinstance(parsed, dict):
        return False, ["answer is not an object"]
    if parsed.get("recipe") not in brief_mod.RECIPES:
        return False, ["recipe must be one of the list"]
    return True, []


def refine_brief(store, request: str, assets: list[dict], an: dict, current: dict, *, call=call_json, job=None) -> tuple[dict, dict]:
    """The deterministic brief improved by the model. Returns (brief, ai_info); on any failure the brief is unchanged."""
    parsed, info = call(store, prompt=build_brief_prompt(request, assets, an, current), prompt_id="video_director_brief", validate=_validate_brief, job=job)
    if not parsed:
        return current, info
    out = dict(current)
    stated = set(current.get("matched") or [])
    if "نوعِ ویدیو" not in stated and parsed.get("recipe") in brief_mod.RECIPES:
        out["recipe"] = parsed["recipe"]
    if "پلتفرم" not in stated and parsed.get("platform") in brief_mod.PLATFORMS:
        out["platform"] = parsed["platform"]
    if "مدت" not in stated:
        try:
            d = int(float(parsed.get("duration") or 0))
            if 6 <= d <= 180:
                out["duration"] = d
        except (TypeError, ValueError):
            pass
    if "ریتم" not in stated and parsed.get("pace") in ("fast", "normal", "slow"):
        out["pace"] = parsed["pace"]
        out["pace_explicit"] = True
    for key, limit in (("title", 60), ("subtitle", 80), ("cta", 40)):
        text = str(parsed.get(key) or "").strip()
        if text and not (key == "title" and "عنوان" in stated):
            out[key] = text[:limit]
    if "درصدِ تخفیف" not in stated:
        try:
            d = int(float(parsed.get("discount") or 0))
            if 0 < d <= 95:
                out["discount"] = d
        except (TypeError, ValueError):
            pass
    for key in ("captions", "music"):
        if isinstance(parsed.get(key), bool) and out.get(key) is None:
            out[key] = parsed[key]
    if parsed.get("look") in color.LOOKS and not out.get("look"):
        out["look"] = parsed["look"]
    refs = {a["ref"] for a in assets}
    order = [r for r in (parsed.get("order") or []) if r in refs]
    if order:
        out["order"] = order
    if parsed.get("hook_ref") in refs:
        out["hook"] = parsed["hook_ref"]
    if parsed.get("notes_fa"):
        out["notes"] = list(out.get("notes") or []) + [str(parsed["notes_fa"])[:160]]
    return out, info


def build_steps_prompt(request: str, summary: dict, issues: list[str], an_notes: list[str]) -> str:
    return "\n".join([
        "You are improving an existing edit. The project is already built; propose a FEW extra or changed tool calls.",
        "",
        f"Owner's request (Persian): {request}",
        f"Project now: {_dumps(summary)}",
        f"What is still wrong: {_dumps(issues)}",
        f"Rubric: {RUBRIC}",
        f"Tool catalogue: {_dumps(tools.catalogue_for_model())}",
        "",
        "Rules:",
        "- Only tools from the catalogue; only clip ids that appear in 'Project now' (or aliases you create with an `id` param).",
        "- At most 6 steps. Fewer is better. Do not repeat what is already there. No step may remove the call-to-action or the captions.",
        "- Every `why` is one short Persian sentence.",
        "",
        'Answer exactly: {"steps":[{"tool":"","params":{},"why":""}]}',
    ])


def extra_steps(store, request: str, summary: dict, issues: list[str], *, call=call_json, job=None) -> tuple[list[dict], dict]:
    parsed, info = call(store, prompt=build_steps_prompt(request, summary, issues, []), prompt_id="video_director_steps",
                        validate=lambda p: (isinstance((p or {}).get("steps"), list), ["steps must be a list"]), job=job)
    if not parsed:
        return [], info
    steps, problems = validate_plan(parsed["steps"][:8])
    info["problems"] = problems
    return steps[:6], info


def build_vision_prompt(request: str, brief: dict) -> str:
    return "\n".join([
        "These images are frames, in order, from a finished short social-media video (a low-resolution preview).",
        f"The owner asked for (Persian): {request or brief.get('title', '')}. Platform: {brief.get('platform')}.",
        f"Judge it as a professional editor using this rubric: {RUBRIC}.",
        "Score each axis 0-100 and list at most 5 concrete problems; for each say which frame (1-based) and a fix.",
        "",
        'Answer exactly: {"scores":{"hook":0,"pacing":0,"captions":0,"audio":0,"product":0,"cta":0},"issues":[{"frame":1,"what":"","fix":""}],"verdict":"ok|minor|severe"}',
    ])


def _validate_vision(parsed) -> tuple[bool, list[str]]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("scores"), dict):
        return False, ["scores missing"]
    return True, []


def vision_review(store, request: str, brief: dict, frames_b64: list[str], *, call=call_json, job=None) -> tuple[dict | None, dict]:
    return call(store, prompt=build_vision_prompt(request, brief), prompt_id="video_director_vision", validate=_validate_vision, images=frames_b64, vision=True, job=job)
