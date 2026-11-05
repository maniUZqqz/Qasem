"""Run a plan against a project: validate each step, apply it, never let one bad step spoil the rest.

`apply_steps` works on a deep copy and returns `(new_project, results)`. A result is a plain dict the UI shows next to the
step: `{"id","tool","title","text","ok","skipped","message","notes"}`. Nothing here talks to the network except through
the `Ctx` the caller passes.
"""
from __future__ import annotations

import copy
import logging

from .. import safezones
from . import projectops as ops
from .spec import Ctx, StepError, clean_params
from .tools import TOOLS, State

logger = logging.getLogger(__name__)

MAX_STEPS = 80


def normalize_step(raw, index: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    tool = str(raw.get("tool") or "").strip()
    if not tool:
        return None
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    out = {"id": str(raw.get("id") or f"s{index + 1}")[:24], "tool": tool, "params": params,
           "why": str(raw.get("why") or raw.get("reason") or "")[:240], "on": raw.get("on") is not False}
    return out


def describe_step(step: dict) -> dict:
    """The Persian line of a step (no execution): `{"title","text","group","known"}`."""
    spec = TOOLS.get(step.get("tool"))
    if spec is None:
        return {"title": str(step.get("tool")), "text": "ابزارِ ناشناخته", "group": "", "known": False}
    try:
        clean, _ = clean_params(spec, step.get("params"))
        return {"title": spec.title, "text": spec.describe(clean), "group": spec.group, "known": True}
    except StepError as exc:
        return {"title": spec.title, "text": str(exc), "group": spec.group, "known": True}


def validate_plan(steps) -> tuple[list[dict], list[str]]:
    """Raw steps → (normalised steps, Persian problems). Unknown tools and unusable params are reported, never raised."""
    out, problems = [], []
    for i, raw in enumerate(steps if isinstance(steps, list) else []):
        if len(out) >= MAX_STEPS:
            problems.append(f"فقط {MAX_STEPS} مرحلهٔ اول نگه داشته شد.")
            break
        step = normalize_step(raw, i)
        if step is None:
            problems.append(f"مرحلهٔ {i + 1} خوانده نشد.")
            continue
        spec = TOOLS.get(step["tool"])
        if spec is None:
            problems.append(f"«{step['tool']}» ابزارِ شناخته‌شده نیست و کنار گذاشته شد.")
            continue
        try:
            clean, notes = clean_params(spec, step["params"])
        except StepError as exc:
            problems.append(f"«{spec.title}»: {exc}")
            continue
        step["params"] = clean
        step["notes"] = notes
        out.append(step)
    return out, problems


def apply_steps(project: dict, steps: list[dict], ctx: Ctx | None = None, *, platform: str | None = None) -> tuple[dict, list[dict]]:
    ctx = ctx or Ctx()
    new = copy.deepcopy(project)
    preset = (new.get("format") or {}).get("preset", "reel")
    st = State(project=new, ctx=ctx, safe=safezones.margins(platform, preset))
    results: list[dict] = []
    for i, raw in enumerate(steps):
        step = normalize_step(raw, i)
        if step is None:
            results.append({"id": f"s{i + 1}", "tool": "", "title": "", "text": "", "ok": False, "skipped": False, "message": "این مرحله خوانده نشد.", "notes": []})
            continue
        spec = TOOLS.get(step["tool"])
        res = {"id": step["id"], "tool": step["tool"], "title": spec.title if spec else step["tool"], "text": "", "ok": False, "skipped": False,
               "message": "", "notes": []}
        if spec is None:
            res["message"] = f"«{step['tool']}» ابزارِ شناخته‌شده نیست."
            results.append(res)
            continue
        if not step["on"]:
            res.update(ok=True, skipped=True, message="خاموش بود؛ اجرا نشد.")
            results.append(res)
            continue
        try:
            clean, notes = clean_params(spec, step["params"])
            res["text"] = spec.describe(clean)
            res["notes"] = notes
            if "format" in new and spec.name == "set_format":
                pass
            msg = spec.fn(st, clean)
            res.update(ok=True, message=msg or res["text"])
            if spec.name == "set_format":
                st.safe = safezones.margins(platform, (new.get("format") or {}).get("preset", "reel"))
        except StepError as exc:
            res["message"] = str(exc)
        except Exception as exc:  # noqa: BLE001 — a bug in one step must not lose the whole edit
            logger.exception("director step %s failed", step["tool"])
            res["message"] = "این مرحله به‌خاطر یک خطای غیرمنتظره انجام نشد."
            res["notes"].append(str(exc)[:120])
        results.append(res)
    return new, results
