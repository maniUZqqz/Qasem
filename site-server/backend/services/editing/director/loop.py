"""The director's agent loop:  analyse → plan → apply → preview → critique → revise (≤ N rounds) → offer variants.

Pure orchestration over the other modules; every outside effect (model calls, rendering a preview, speech recognition,
file lookup) arrives through arguments, so the whole loop runs in tests with fakes and never spends a rial.

* **Analyse** (`analyze.analyze`): speech spans, beats, best moments, optional transcript.
* **Understand** (`brief.parse_prompt`, then `ai.refine_brief` when a model answers).
* **Plan** (`recipes.build_plan`): three variants from the recipe; the model may add a few steps (`ai.extra_steps`).
* **Apply** (`runner.apply_steps`) to a real project — the result is always an ordinary, editable VideoProject.
* **Critique** (`critique.critique`, deterministic rubric) → **auto-fix** (the rubric's own fix steps), up to `rounds` times;
  on the primary variant a preview is rendered and a vision model (when there is one) reviews it against the rubric.
* **Say what needed AI**: `result["degraded"]` lists, in Persian, every part that could not run and why.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from . import ai as ai_mod
from . import analyze as analyze_mod
from . import critique as critique_mod
from . import projectops as ops
from . import recipes
from .brief import PLATFORMS, RECIPES, finish_brief, parse_prompt
from .brief import looks_like_talking_video as brief_looks_talking
from .runner import apply_steps, describe_step, validate_plan
from .spec import Ctx

logger = logging.getLogger(__name__)


@dataclass
class Options:
    variants: int = 3
    rounds: int = 2
    use_ai: bool = True
    want_words: bool = True
    preview: bool = True
    music_ref: str = ""            # an audio asset the owner picked (else the first audio in `assets`, else the library)
    #: the run is worth doing only with the words (cuts on word boundaries, captions): if speech recognition is merely OFF, park the whole job
    #: in the durable queue so it starts by itself when the processing server comes back
    require_words: bool = False
    #: choices made with the panel's chips (recipe, platform, duration, pace, music, captions): they count as «the owner said so»
    override: dict = field(default_factory=dict)


def _view(step: dict, res: dict | None, round_no: int = 0) -> dict:
    d = describe_step(step)
    out = {"id": step.get("id", ""), "tool": step["tool"], "title": d["title"], "text": d["text"], "group": d["group"], "why": step.get("why", ""),
           "params": step.get("params", {}), "on": step.get("on", True), "round": round_no}
    if res is not None:
        out.update(ok=res["ok"], skipped=res["skipped"], message=res["message"], notes=res["notes"])
    return out


def _run_plan(base: dict, steps: list[dict], ctx: Ctx, platform: str, round_no: int = 0) -> tuple[dict, list[dict]]:
    project, results = apply_steps(base, steps, ctx, platform=PLATFORMS[platform]["zone"])
    by_idx = results
    views = []
    for i, s in enumerate(steps):
        views.append(_view(s, by_idx[i] if i < len(by_idx) else None, round_no))
    return project, views


def _unfixed(report: dict) -> list[str]:
    return [f"{i['title']}: {i['detail']}" for i in report["items"] if not i["ok"] and i["severity"] in ("bad", "warn")]


def _apply_override(brief: dict, override: dict) -> None:
    """Panel chips beat keywords and beat the model: they are written in as stated."""
    o = override if isinstance(override, dict) else {}
    if o.get("recipe") in RECIPES:
        brief["recipe"] = o["recipe"]
        brief["matched"].append("نوعِ ویدیو")
    if o.get("platform") in PLATFORMS:
        brief["platform"] = o["platform"]
        brief["matched"].append("پلتفرم")
        brief["notes"] = [n for n in brief.get("notes", []) if "پلتفرم گفته نشد" not in n]
    try:
        d = int(o.get("duration") or 0)
    except (TypeError, ValueError):
        d = 0
    if 6 <= d <= 180:
        brief["duration"] = d
        brief["matched"].append("مدت")
    if o.get("pace") in ("fast", "normal", "slow"):
        brief["pace"], brief["pace_explicit"] = o["pace"], True
        brief["matched"].append("ریتم")
    for key in ("music", "captions"):
        if isinstance(o.get(key), bool):
            brief[key] = o[key]
    if o.get("background") in ("keep", "blur", "color"):           # «پس‌زمینه»: همان / محو / رنگِ ساده (the chip beats the words)
        brief["background"] = o["background"]
        brief["matched"].append("پس‌زمینه")


def build_variant(key: str, brief: dict, assets: list[dict], an: dict, ctx: Ctx, *, music_ref: str, rounds: int, extra_call=None, store=None,
                  request: str = "", base: dict | None = None, steps: list[dict] | None = None) -> dict:
    """One finished variant: project + executed plan (with fix rounds) + critique. `steps` replaces the recipe (a re-run of an
    edited plan)."""
    plan = steps if steps is not None else recipes.build_plan(brief, assets, an, variant=key, music_ref=music_ref)
    project, views = _run_plan(base or ops.new_project(PLATFORMS[brief["platform"]]["preset"]), plan, ctx, brief["platform"])
    report = critique_mod.critique(project, an, brief)
    done: set[str] = set()
    all_steps = list(plan)
    rounds_used = 0
    for r in range(1, rounds + 1):
        fixes = critique_mod.auto_fixes(report, done=done)
        if not fixes:
            break
        project, res_views = _run_plan(project, [{**f, "id": f"f{r}.{i + 1}"} for i, f in enumerate(fixes)], ctx, brief["platform"], r)
        for v in res_views:
            v["why"] = v["why"] or "اصلاحِ خودکار پس از نقد"
        views += res_views
        all_steps += fixes
        report = critique_mod.critique(project, an, brief)
        rounds_used = r
    return {"key": key, "title": recipes.VARIANTS.get(key, {}).get("title", key), "project": project, "plan": views, "critique": report,
            "score": report["score"], "rounds": rounds_used, "ai_steps": 0}


def run(prompt: str, assets: list[dict], ctx: Ctx, *, store=None, options: Options | None = None, call=None, review_preview: Callable | None = None,
        progress: Callable | None = None, job=None) -> dict:
    """The whole thing. `assets` = describe dicts of the refs the owner picked. `review_preview(project) -> list[b64 jpg]` renders a low-res
    preview and returns frames (None/[] = cannot). Returns the result dict described in the module docstring."""
    opts = options or Options()
    call = call or ai_mod.call_json                    # looked up NOW (not at import) so a test that patches `ai.call_json` is honoured
    tick = progress or (lambda f, label="": None)
    degraded: list[str] = []
    request = (prompt or "").strip()
    if not any(a.get("kind") in ("video", "image") for a in assets):
        return {"error": "برای ساختنِ ویدیو دست‌کم یک ویدیو یا عکس لازم است؛ از «رسانه‌ها» انتخاب کنید.", "variants": []}

    # the music: the owner's pick, else an audio asset among the chosen ones, else the shop's library; it is analysed like any asset (its beats)
    music_ref = opts.music_ref or next((a["ref"] for a in assets if a.get("kind") == "audio"), "") or (ctx.find_music("") or "")
    to_analyse = list(assets)
    if music_ref and not any(a["ref"] == music_ref for a in to_analyse):
        item = ctx.describe(music_ref)
        if item:
            to_analyse.append(item)
        else:
            music_ref = ""

    tick(0.05, "بررسیِ فیلم‌ها و صدا…")
    an = analyze_mod.analyze(to_analyse, ctx, want_words=opts.want_words, progress=lambda f, l="": tick(0.05 + 0.25 * f, l))
    degraded += an["missing"]
    if opts.require_words and an["has_speech"] and not an.get("has_words") and an.get("asr_waiting"):
        from ..captions import waiting_error

        raise waiting_error()

    brief = parse_prompt(request, assets=assets)
    if not brief["matched"].count("نوعِ ویدیو") and not (opts.override or {}).get("recipe") and brief_looks_talking(assets, an):
        brief["recipe"] = "polish"                 # one long talking video, no recipe asked for: polish it, do not cut it into product shots
        brief["notes"].append("ویدیوی گفتاری تشخیص داده شد؛ به‌جای برش‌های کوتاهِ محصول، همان ویدیو حرفه‌ای‌تر می‌شود.")
    _apply_override(brief, opts.override)
    if brief["recipe"] == "polish" and "پلتفرم" not in brief["matched"]:      # after the chips: a platform the owner chose is never replaced
        wide = next((a for a in assets if a.get("kind") == "video" and int(a.get("width") or 0) > int(a.get("height") or 0)), None)
        boxes = [(an["by_ref"].get(a["ref"]) or {}).get("box") or {} for a in assets if a.get("kind") == "video"]
        phone = next((b for b in boxes if b.get("found") and b.get("portrait")), None)
        if phone:                                  # a phone screen recorded inside a landscape frame: its natural home is the vertical frame
            brief["notes"].append("تصویرِ واقعیِ ویدیو عمودی است (ضبطِ صفحهٔ گوشی) و دورش نوارِ سیاه دارد؛ قاب عمودی (۹:۱۶) و بدونِ نوارِ سیاه ساخته شد.")
        elif wide:                                 # a landscape source stays landscape unless the owner asks for a vertical size
            brief["platform"] = "youtube"
            brief["notes"] = [n for n in brief.get("notes", []) if "پلتفرم گفته نشد" not in n] + ["ویدیو افقی است؛ قاب افقی (۱۶:۹) نگه داشته شد. برای ریلز/استوری «چند سایز» را بزنید."]
    ai_info = {"asked": False, "ok": False, "via": "", "model": "", "error": "", "error_code": ""}
    if opts.use_ai:
        tick(0.32, "فهمیدنِ دستورِ شما…")
        brief, ai_info = ai_mod.refine_brief(store, request, assets, an, brief, call=call, job=job)
        if not ai_info.get("ok"):
            degraded.append("فهمیدنِ دستور با کلمه‌های کلیدی انجام شد چون هوش مصنوعی جواب نداد — " + (ai_info.get("error") or "در دسترس نبود"))
    brief = finish_brief(brief, assets)
    if brief.get("order"):
        pos = {r: i for i, r in enumerate(brief["order"])}
        assets = sorted(assets, key=lambda a: pos.get(a["ref"], 999))
    if brief.get("music") is not False and not music_ref:
        degraded.append("موسیقی‌ای انتخاب نشده بود و در کتابخانه‌ات نبود؛ ویدیو بدون موسیقی ساخته شد. با «موسیقیِ پس‌زمینه» یکی اضافه کن.")

    keys = recipes.variant_keys(brief)[: max(1, opts.variants)]
    variants: list[dict] = []
    for i, key in enumerate(keys):
        tick(0.35 + 0.35 * i / max(1, len(keys)), f"ساختنِ نسخهٔ «{recipes.VARIANTS[key]['title']}»…")
        variants.append(build_variant(key, brief, assets, an, ctx, music_ref=music_ref, rounds=opts.rounds, store=store, request=request))

    primary = max(variants, key=lambda v: v["score"])
    ai_ok = bool(opts.use_ai and ai_info.get("ok"))
    previewable = bool(opts.preview and review_preview is not None and ai_ok)
    if opts.preview and review_preview is not None and not ai_ok:
        degraded.append("پیش‌نمایشِ کم‌حجم و نقدِ تصویری فقط وقتی ساخته می‌شود که هوش مصنوعی در دسترس باشد؛ این بار انجام نشد.")

    vision = None
    vision_issues: list[str] = []

    def look(label: str) -> None:
        """Render a low-res preview of the primary variant and let the vision model judge it against the rubric."""
        nonlocal vision, vision_issues
        tick(label[0], label[1])
        try:
            frames = review_preview(primary["project"]) or []
        except Exception as exc:  # noqa: BLE001 — a failed preview never fails the edit
            logger.info("director preview failed: %s", exc)
            frames = []
            degraded.append("پیش‌نمایشِ کم‌حجم ساخته نشد؛ نقدِ تصویری انجام نشد.")
        if not frames:
            return
        parsed, info = ai_mod.vision_review(store, request, brief, frames, call=call, job=job)
        if parsed:
            vision = {"scores": parsed.get("scores"), "issues": (parsed.get("issues") or [])[:5], "verdict": parsed.get("verdict", ""), "via": info.get("via", "")}
            vision_issues = [f"تصویر: {i.get('what', '')} — {i.get('fix', '')}" for i in vision["issues"] if isinstance(i, dict)]
            primary["critique"]["vision"] = vision
        else:
            text = "نقدِ تصویریِ پیش‌نمایش به مدلِ بینایی نیاز دارد و انجام نشد — " + (info.get("error") or "در دسترس نبود")
            if text not in degraded:
                degraded.append(text)

    if previewable:
        look((0.72, "ساختنِ پیش‌نمایشِ کم‌حجم و نقدِ تصویری…"))
    # revise: the model may add a few steps for what the rubric cannot fix by itself (at most `rounds` times)
    ai_asked_steps = False
    revised = 0
    if ai_ok:
        for r in range(1, opts.rounds + 1):
            issues = _unfixed(primary["critique"]) + vision_issues
            if not issues:
                break
            tick(0.8 + 0.05 * r, f"نظرِ هوش مصنوعی برای بهتر شدن (دورِ {r})…")
            ai_asked_steps = True
            steps, info = ai_mod.extra_steps(store, request, ops.summary(primary["project"]), issues, call=call, job=job)
            if not steps:
                if not info.get("ok"):
                    degraded.append("پیشنهادِ مرحله‌های بیشتر به هوش مصنوعی نیاز داشت و جواب نداد.")
                break
            project, views = _run_plan(primary["project"], [{**s_, "id": f"ai{r}.{i + 1}"} for i, s_ in enumerate(steps)], ctx, brief["platform"], 90 + r)
            for v in views:
                v["why"] = v["why"] or "پیشنهادِ هوش مصنوعی"
            primary["project"] = project
            primary["plan"] += views
            primary["critique"] = critique_mod.critique(project, an, brief)
            primary["score"] = primary["critique"]["score"]
            primary["ai_steps"] += len(steps)
            revised = r
            vision_issues = []              # they were addressed (or not) by this round; the confirming look below re-asks
        if revised and previewable:
            look((0.92, "پیش‌نمایشِ نهایی برای تأیید…"))
    tick(0.97, "آماده‌سازیِ نتیجه…")
    needed = []
    if not ai_info.get("ok"):
        needed.append("درکِ دقیقِ دستور و نوشتنِ تیتر و شعار")
    if not vision:
        needed.append("نقدِ تصویریِ ویدیو و پیشنهادِ اصلاح")
    return {
        "brief": {k: v for k, v in brief.items() if k not in ("matched",)}, "platform": PLATFORMS[brief["platform"]]["title"], "recipe_title": RECIPES[brief["recipe"]]["title"],
        "ai": {**ai_info, "used_for_steps": ai_asked_steps, "enabled": opts.use_ai, "needed_for": needed}, "degraded": degraded,
        "variants": variants, "primary": primary["key"], "analysis": {"has_speech": an["has_speech"], "has_words": an.get("has_words", False), "music": music_ref},
    }


def rerun(brief: dict, steps: list[dict], assets: list[dict], ctx: Ctx, *, key: str = "a", rounds: int = 0, base: dict | None = None) -> dict:
    """Run an EDITED plan again from scratch (the owner switched a step off or changed a number): deterministic, no model."""
    an = analyze_mod.analyze(assets, ctx, want_words=False, want_moments=False)
    brief = finish_brief(brief, assets)
    clean, problems = validate_plan(steps)
    v = build_variant(key, brief, assets, an, ctx, music_ref="", rounds=rounds, steps=clean, base=base)
    v["problems"] = problems
    return v
