"""The brain. §9 — «ادیتور هوشمند: مدل ارزان، ابزار قوی».

The loop §9 draws:

    ببین → تصمیم بگیر → انجام بده → دوباره ببین → اگر خوب نشد، تکرار کن

`analysis` is the seeing, `tools` is the doing, and this is the deciding. The
model's entire input is a page of measurements and a list of tool names; its
entire output is a list of `{tool, params, reason}`. It never sees the video, a
path, or a command.

**Most decisions never reach the model.** §8 is explicit that code already knows
how to do most editing, so `suggest` answers from thresholds alone: fourteen
silences found, offer to remove them. The model is asked only when the request
carries meaning a threshold cannot hold — «مثل یک یوتیوبر حرفه‌ای، ساده و بدون
افکت زیاد» — which is what DIRECTED mode is for. A shop on SUGGEST mode with no
model installed still gets a working editor.

**The second look judges each tool by its own intended effect.** After
rendering, the same measurements are taken again. A brightness lift is judged
by whether the exposure moved the right way, a white balance by whether the
neutral pixels got closer to grey, a stabiliser by whether the shake fell —
never by a single "distance from mid-grey" number, which called a darkened
white-background product shot "improved" and a shop's own vignette "worse".
An edit that made its own target worse is reported as such, with both sets of
numbers, rather than handed over as finished work. And what a person chose by
hand (MANUAL) is never vetoed: the measurements are reported, the file is kept.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import analysis, edl as edl_module, preferences, tools

logger = logging.getLogger(__name__)

#: §9's four modes.
MANUAL = "MANUAL"        # «دستی» — the shop says exactly what to do
SUGGEST = "SUGGEST"      # «پیشنهادی» — we propose, a person approves
AUTO = "AUTO"            # «خودکار» — we decide and apply
DIRECTED = "DIRECTED"    # «کارگردانی» — a sentence of direction, then decide

MODES = {
    MANUAL: "دستی — خودم می‌گویم چه کار کن",
    SUGGEST: "پیشنهادی — پیشنهاد بده، من تأیید کنم",
    AUTO: "خودکار — خودت تصمیم بگیر",
    DIRECTED: "کارگردانی — بگو چطور ادیتش کن",
}

#: Two rounds. A third has nothing left to learn: the measurements after the
#: second render differ from the first by less than the thresholds care about,
#: and each round is a full re-encode the shop waits through.
MAX_ROUNDS = 2

#: Where a dark clip's brightest 5 % should land, and where a burnt clip's
#: darkest 5 % should. Shared with services.video.repair so an upload and a
#: generated segment get the same correction for the same measurement.
DARK_TARGET_P95 = 200.0
BLOWN_TARGET_P5 = 60.0
BRIGHTNESS_SLOPE = 250.0

#: Model-proposed operations below this confidence are dropped before they
#: reach the toolbox. A small local model's confidences are noisy; this is a
#: low-pass filter, not a ranking.
MIN_CONFIDENCE = 0.5

#: The most operations one directed plan may carry. A model that answers a
#: sentence of direction with nine edits has not understood "simple".
MAX_DIRECTED_OPERATIONS = 4


@dataclass
class Plan:
    """What the agent intends, before anything is rendered."""

    edl: "edl_module.EDL"
    facts: dict = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)
    mode: str = SUGGEST
    asked_model: bool = False

    @property
    def does_nothing(self) -> bool:
        return not self.edl.operations

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "summary": self.edl.summary(),
            "facts": self.facts,
            "findings": self.findings,
            "asked_model": self.asked_model,
            **self.edl.as_dict(),
        }


@dataclass
class Outcome:
    """What actually happened, with both sets of measurements."""

    plan: Plan
    output: Path | None = None
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    improved: bool = True
    rounds: int = 0
    note: str = ""
    #: Per-tool verdicts from the second look — what each edit was meant to
    #: change, and whether it did. This is what the before/after panel reads.
    effects: list[dict] = field(default_factory=list)
    #: The noise-removal pre-pass report (engine, SNR before/after), from the
    #: round that ran it. Kept here because a later AUTO round replaces `plan`.
    denoise: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "plan": self.plan.as_dict(),
            "before": self.before,
            "after": self.after,
            "improved": self.improved,
            "rounds": self.rounds,
            "note": self.note,
            "effects": self.effects,
            "denoise": self.denoise,
        }


# ------------------------------------------------------------- code-only


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _brightness_step(facts: dict, finding: dict) -> float:
    """How much `eq=brightness` to apply, from the measurement.

    Sized from the percentiles when they exist (the same slope the segment
    repair uses); the old proportional guess only for rows analysed before
    percentiles were measured.
    """
    if finding["what"] == "dark":
        p95 = facts.get("p95")
        if p95 is not None:
            return round(_clamp((DARK_TARGET_P95 - float(p95)) / BRIGHTNESS_SLOPE, 0.03, 0.25), 3)
        return round(min(0.25, (95 - float(finding["value"])) / 400), 3)
    p5 = facts.get("p5")
    if p5 is not None:
        return round(_clamp((BLOWN_TARGET_P5 - float(p5)) / BRIGHTNESS_SLOPE, -0.25, -0.03), 3)
    return round(-(float(finding["value"]) - 180) / 400, 3)


def suggest(facts: dict, *, store=None, exclude=()) -> list[dict]:
    """What to do, from measurements alone. No model involved.

    This is §8's claim made concrete: fourteen long silences is not a judgement
    call, and neither is a colour cast. Each suggestion carries the observation
    that produced it, because «۱۴ سکوت طولانی پیدا شد، حذف شود؟» is a question a
    shop can answer and «بهینه‌سازی خودکار؟» is not.

    `exclude` names tools a previous round already applied; a second brightness
    lift on top of the first is how a picture ends up further from right than
    it started.
    """
    habits = preferences.habits(store)
    proposed: list[dict] = []
    findings = analysis.obvious_problems(facts)
    excluded = set(exclude or ()) | set(habits.get("never", []))

    # Checked across the whole set before proposing anything, not per finding.
    # A mostly-silent video reports *both* `silence` and `no_speech`, and
    # skipping only the second one still leaves the first proposing to remove
    # every quiet second — which on a video whose microphone failed means
    # removing the video.
    no_speech = any(f["what"] == "no_speech" for f in findings)

    for finding in findings:
        what = finding["what"]

        if what == "no_speech":
            continue

        if what == "silence":
            if no_speech:
                continue
            proposed.append({
                "tool": "trim_silence",
                "params": {
                    "min_silence": habits.get("min_silence", 0.6),
                    "keep": habits.get("silence_keep", 0.15),
                },
                "reason": finding["note"],
            })
        elif what in ("dark", "bright"):
            # A finding for one shot carries its window and its own numbers:
            # the lift is sized from THAT shot, and applied only there.
            window = finding.get("window")
            measured = finding.get("shot") or facts
            params = {"amount": _brightness_step(measured, finding)}
            if window:
                params.update(from_s=window[0], to_s=window[1])
            proposed.append({"tool": "brightness", "params": params, "reason": finding["note"]})
        elif what == "flicker":
            fps = float(facts.get("fps") or 0)
            size = int(_clamp(round(fps / 4) if fps else 5, 3, 10))
            proposed.append({
                "tool": "deflicker", "params": {"size": size}, "reason": finding["note"],
            })
        elif what == "colour_cast":
            # The tool warms for positive temperatures; a warm cast (R > B on
            # the neutrals) therefore wants a negative one, sized so the
            # neutral pixels land on grey (see tools.white_balance's gains).
            params = {"temperature": round(_clamp(-float(finding["value"]) / 160, -0.3, 0.3), 3)}
            if finding.get("window"):
                params.update(from_s=finding["window"][0], to_s=finding["window"][1])
            proposed.append({"tool": "white_balance", "params": params, "reason": finding["note"]})
        elif what == "shaky":
            proposed.append({
                "tool": "stabilize",
                "params": {"smoothing": habits.get("smoothing", 10), "zoom": 1},
                "reason": finding["note"],
            })
        elif what == "noisy":
            # Stronger for a worse recording, but never the maximum: past a
            # point the voice itself starts to sound processed.
            snr = float(finding["value"])
            amount = 12 if snr >= 15 else 16 if snr >= 8 else 20
            proposed.append({
                "tool": "denoise_audio", "params": {"amount": amount},
                "reason": finding["note"],
            })

    if facts.get("has_audio") and habits.get("always_normalize_audio"):
        proposed.append({
            "tool": "normalize_audio",
            "params": {"target": habits.get("audio_target", -18)},
            "reason": "همیشه بلندی صدا را یکسان می‌کنید",
        })

    return [p for p in proposed if p["tool"] not in excluded]


# ------------------------------------------------------------ model-driven


EDITOR_SYSTEM = (
    "You are a video editor's assistant. You are given measurements of a video "
    "and a fixed list of tools. You answer with a single valid JSON object and "
    "nothing else. You never invent a tool, a parameter, or a file path. You "
    "only choose tools from the list you were given."
)

#: Words in a shop's direction that name the target format, and what an editor
#: does differently for it. Crude on purpose: when nothing matches, no profile
#: is sent rather than a wrong one.
_PROFILES = (
    (("ریلز", "استوری", "شورت", "reel", "story", "short", "تیک‌تاک", "tiktok"),
     "short vertical clip: fast opening, remove every pause, captions matter, at most one zoom"),
    (("یوتیوب", "بلند", "youtube", "long"),
     "long-form: clean cuts, natural pacing, no zoom, no effects"),
    (("پادکست", "podcast", "مصاحبه", "interview"),
     "talking video: voice first (normalise, denoise), keep pauses that are punctuation"),
)

#: The facts the model needs. Everything else — forty silence spans, face
#: boxes — is for the code, and only pads the prompt.
_PROMPT_FACTS = (
    "duration", "has_audio", "width", "height", "fps", "silence_count",
    "silence_seconds", "longest_silence", "faces", "brightness", "p5", "p50", "p95",
    "clip_hi", "cast_rb", "cast_measurable", "flicker", "shake", "motion", "snr_db",
)


def _profile_for(instruction: str, facts: dict) -> str:
    text = (instruction or "").lower()
    for words, profile in _PROFILES:
        if any(word in text for word in words):
            return profile
    width, height = facts.get("width") or 0, facts.get("height") or 0
    if width and height and height > width:
        return "vertical phone video: probably a reel or story — keep it tight"
    return ""


def build_editor_prompt(facts: dict, findings: list[dict], instruction: str, *,
                        store=None) -> str:
    import json

    habits = preferences.habits(store)
    never = set(habits.get("never", []))
    catalogue = [
        {
            "tool": tool["key"],
            "does": tool["why"],
            "params": {
                p["name"]: {
                    "min": p["min"], "max": p["max"], "default": p["default"],
                    **({"choices": p["choices"]} if p["choices"] else {}),
                }
                for p in tool["params"]
            },
        }
        for tool in tools.catalogue()
        if tool["key"] not in never
    ]
    dumps = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    compact = {k: facts[k] for k in _PROMPT_FACTS if facts.get(k) is not None}

    lines = [
        "Decide how to edit this video.",
        "",
        f"Measurements:\n{dumps(compact)}",
        "",
        f"What the measurements already show:\n{dumps(findings)}",
    ]
    habit_lines = preferences.explain(store) if store is not None else []
    if habit_lines:
        lines += ["", "This shop's habits (follow them unless the request says otherwise):"]
        lines += [f"- {line}" for line in habit_lines]
    earlier = [d for d in habits.get("directions", []) if d and d != instruction]
    if earlier:
        lines += ["", "Earlier directions from this shop: " + " | ".join(earlier[-3:])]
    profile = _profile_for(instruction, facts)
    if profile:
        lines += ["", f"Target format: {profile}"]
    lines += [
        "",
        f"Tools you may use:\n{dumps(catalogue)}",
        "",
        f"The shop asked for:\n{instruction or 'یک تدوین تمیز و ساده'}",
        "",
        "Rules:",
        "- Use only tools from the list. Nothing else exists.",
        "- Stay inside each parameter's min and max.",
        "- Every `start`/`end` must be inside the video's duration.",
        f"- At most {MAX_DIRECTED_OPERATIONS} operations. Fewer is better.",
        "- Propose brightness, white_balance, stabilize or deflicker ONLY when the "
        "findings name that problem. The measurements are more reliable than a guess.",
        "- Prefer the smallest change that achieves the request. An edit nobody "
        "notices is better than one they do.",
        "- If the measurements show nothing wrong and the request asks for nothing "
        "specific, return an empty list. Doing nothing is a valid answer.",
        "- `reason` is one short Persian sentence the shop owner will read.",
        "- `confidence` is 0 to 1: how sure you are this operation serves the request.",
        "",
        'Answer exactly: {"operations": [{"tool": "...", "params": {...}, '
        '"reason": "...", "confidence": 0.0}]}',
    ]
    return "\n".join(lines)


def ask_model(facts: dict, findings: list[dict], instruction: str, *,
              store=None, job=None) -> list[dict]:
    """One call to the cheap model. Returns raw operations, still unvalidated.

    Failure here is not failure of the edit. Everything code could work out on
    its own is already in `findings`, so a missing or unreachable model costs
    the *direction* — not the editing.
    """
    try:
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from services.ai.gateway import text_provider
        from services.ai.router import TASK_REASONING, models_for

        parsed, _ = recorded_json_call(
            job=job,
            store=store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id="video_editor",
            prompt_version="2",
            provider=text_provider(store),
            models=models_for(TASK_REASONING),
            prompt=build_editor_prompt(facts, findings, instruction, store=store),
            system=EDITOR_SYSTEM,
            validate=lambda parsed: (
                isinstance((parsed or {}).get("operations"), list),
                ["operations باید فهرست باشد"],
            ),
            validation_message="مدل فهرست عملیات را برنگرداند",
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Editor model unavailable: %s", exc)
        return []

    if store is not None and instruction:
        try:
            preferences.remember_direction(store, instruction)
        except Exception as exc:  # noqa: BLE001 — remembering is a courtesy
            logger.debug("Could not remember direction: %s", exc)

    operations = []
    for raw in (parsed or {}).get("operations") or []:
        if not isinstance(raw, dict):
            continue
        confidence = raw.get("confidence")
        try:
            if confidence is not None and float(confidence) < MIN_CONFIDENCE:
                continue
        except (TypeError, ValueError):
            pass
        operations.append({k: v for k, v in raw.items() if k != "confidence"})
    return operations[:MAX_DIRECTED_OPERATIONS]


# -------------------------------------------------------------- planning


def _shape(facts: dict) -> dict | None:
    if not facts.get("width") or not facts.get("height"):
        return None
    return {
        "width": int(facts["width"]), "height": int(facts["height"]),
        "fps": facts.get("fps"), "fps_text": facts.get("fps_text"),
    }


def plan(
    source,
    work_dir,
    *,
    mode: str = SUGGEST,
    operations: list[dict] | None = None,
    instruction: str = "",
    store=None,
    job=None,
    subtitle_file=None,
    exclude=(),
) -> Plan:
    """Measure, decide, and return the plan — without touching the video."""
    source = Path(source)
    work = Path(work_dir)
    facts = analysis.describe(source, work)
    findings = analysis.obvious_problems(facts)

    if not facts.get("readable"):
        empty = edl_module.EDL(source=source, duration=0.0)
        empty.refusals = [facts.get("reason", "ویدیو خوانده نشد")]
        return Plan(edl=empty, facts=facts, findings=findings, mode=mode)

    asked = False
    if mode == MANUAL:
        raw = list(operations or [])
    elif mode == DIRECTED:
        # Direction is the one input a threshold cannot hold, so this is the
        # mode the model actually earns its call in.
        raw = ask_model(facts, findings, instruction, store=store, job=job)
        asked = True
        if not raw:
            raw = suggest(facts, store=store, exclude=exclude)
    else:  # SUGGEST and AUTO both start from what code worked out
        raw = suggest(facts, store=store, exclude=exclude)
        raw += list(operations or [])

    accepted, refusals = tools.validate(
        raw, duration=facts["duration"], has_audio=facts["has_audio"],
    )
    accepted = _dedupe(accepted)

    built = edl_module.build(
        source, accepted,
        duration=facts["duration"],
        has_audio=facts["has_audio"],
        silences=analysis.silences(source, work) if facts["has_audio"] else [],
        refusals=refusals,
        subtitle_file=subtitle_file,
        face_boxes=facts.get("face_boxes"),
        shape=_shape(facts),
    )
    return Plan(edl=built, facts=facts, findings=findings, mode=mode, asked_model=asked)


def _dedupe(operations: list[tools.Operation]) -> list[tools.Operation]:
    """One of each idempotent tool.

    Two brightness corrections in the same pass do not average — they add, and
    the picture ends up further from right than it started. Tools that are
    meant to repeat (cuts, zooms) are left alone.
    """
    seen, out = set(), []
    for operation in operations:
        # Tools that legitimately appear more than once in one plan: several
        # cuts, several zoom windows, a fade-in AND a fade-out.
        if not operation.spec.idempotent or operation.spec.key in ("zoom", "cut", "fade"):
            out.append(operation)
            continue
        # One per tool AND window: two brightness lifts on the same frames
        # add up, but one for the dim shot and one for the bright shot are two
        # different corrections.
        identity = (
            operation.tool,
            float(operation.params.get("from_s", -1) or -1),
            float(operation.params.get("to_s", -1) or -1),
        )
        if identity in seen:
            continue
        seen.add(identity)
        out.append(operation)
    return out


def _shot_for(facts: dict, params: dict) -> dict | None:
    """The measured stretch a windowed operation targets.

    From `facts["windows"]` when run() measured the rendered video on the
    operation's own window (a successful fix often erases the very cut that
    separated the shot, so re-detecting shots cannot find it again), else
    from the detected shots.
    """
    start = params.get("from_s")
    if start is None or float(start) < 0:
        return None
    key = f"{float(start):.2f}-{float(params.get('to_s', -1)):.2f}"
    if key in (facts.get("windows") or {}):
        return facts["windows"][key]
    for shot in facts.get("shots") or []:
        if abs(float(shot["start"]) - float(start)) < 0.35:
            return shot
    return None


def measure_windows(rendered, operations, work) -> dict:
    """The rendered video's numbers on each windowed operation's own window.

    Only when the edit left the timeline alone (no cut, no silence trim, no
    speed change): otherwise source seconds no longer point at the same shot
    and the operation is reported as applied, not judged.
    """
    reshaping = {"cut", "trim_silence", "speed", "transition"}
    if any(op.tool in reshaping for op in operations):
        return {}
    out = {}
    for op in operations:
        start = float(op.params.get("from_s", -1) if op.params.get("from_s") is not None else -1)
        end = float(op.params.get("to_s", -1) if op.params.get("to_s") is not None else -1)
        if start < 0 or end <= start:
            continue
        stats = analysis.window_stats(rendered, start, end, work, tag=f"after_{start:.1f}")
        if stats:
            out[f"{start:.2f}-{end:.2f}"] = {"shot": op.params.get("shot") or "?", **stats}
    return out


# --------------------------------------------------------------- judging


def _exposure_penalty(facts: dict) -> float:
    """How far the exposure is from acceptable, in luma units. 0 is fine."""
    p5 = facts.get("p5")
    p50 = facts.get("p50")
    p95 = facts.get("p95")
    clip_hi = facts.get("clip_hi")
    if p95 is None or p50 is None:
        brightness = facts.get("brightness")
        if brightness is None:
            return 0.0
        return max(0.0, 60 - float(brightness)) + max(0.0, float(brightness) - 200)
    penalty = 0.0
    if float(p50) < 55 and float(p95) < 140:
        penalty += 140 - float(p95)
    if p5 is not None and clip_hi is not None and float(p5) > 120 and float(clip_hi) > 0.25:
        penalty += (float(clip_hi) - 0.25) * 255
    return penalty


def _score(facts: dict) -> float:
    """Kept for callers that still compare two videos with one number.

    Higher is better; the absolute value means nothing and is never shown.
    Exposure counts only when it is actually wrong (percentiles), a cast only
    when measurable on neutral pixels — the two mistakes that used to make a
    white-background product shot lose to a darkened copy of itself.
    """
    if not facts.get("readable"):
        return -1.0
    penalty = _exposure_penalty(facts) / 40
    if facts.get("cast_measurable") and facts.get("cast_rb") is not None:
        penalty += max(0.0, abs(float(facts["cast_rb"])) - 8) / 40
    if facts.get("flicker") is not None:
        penalty += max(0.0, float(facts["flicker"]) - 6) / 30
    if facts.get("shake") is not None:
        penalty += max(0.0, float(facts["shake"]) - 0.004) * 200
    return max(0.0, 10.0 - penalty * 3)


def judge(before: dict, after: dict, operations) -> tuple[bool, list[dict]]:
    """Did each edit do what it was for? (improved, per-tool effects).

    A tool is judged only on the measurement it targets. Tools whose effect
    is a matter of intent — a watermark, a crop, a vignette, a rotation — are
    reported as applied and never counted against the edit. The one global
    guard is clipping: any edit that blows a lot more pixels to white has gone
    wrong whatever it meant to do.
    """
    effects: list[dict] = []
    worse: list[str] = []

    def number(facts, key):
        value = facts.get(key)
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    for operation in operations:
        key = operation.tool
        title = operation.spec.title
        verdict = "applied"
        detail = ""
        metric_before = metric_after = None
        # A correction for one shot is judged on that shot. When the shot
        # cannot be found again (a cut moved the timeline), it is reported as
        # applied rather than judged on the whole clip it never touched.
        judged_before, judged_after = before, after
        if operation.params.get("from_s") is not None and float(operation.params.get("from_s", -1)) >= 0:
            shot_before = _shot_for(before, operation.params)
            shot_after = _shot_for(after, operation.params)
            if shot_before is None or shot_after is None:
                effects.append({
                    "tool": key, "title": f"{title} (یک نما)", "verdict": "applied",
                    "detail": "این نما بعد از تدوین دوباره پیدا نشد", "before": None, "after": None,
                })
                continue
            judged_before, judged_after = shot_before, shot_after
            title = f"{title} (ثانیه‌ی {float(operation.params['from_s']):.1f} تا {float(operation.params['to_s']):.1f})"
        before_all, after_all = before, after
        before, after = judged_before, judged_after

        if key == "brightness":
            metric_before, metric_after = _exposure_penalty(before), _exposure_penalty(after)
            if metric_after < metric_before - 1:
                verdict = "better"
            elif metric_after > metric_before + 1:
                verdict = "worse"
            elif metric_before == 0 and metric_after == 0:
                verdict = "neutral"
            detail = f"روشن‌ترین بخش‌ها {before.get('p95')} → {after.get('p95')}"
        elif key == "white_balance":
            metric_before, metric_after = number(before, "cast_rb"), number(after, "cast_rb")
            if metric_before is not None and metric_after is not None:
                if abs(metric_after) < abs(metric_before) - 2:
                    verdict = "better"
                elif abs(metric_after) > abs(metric_before) + 2:
                    verdict = "worse"
                else:
                    verdict = "neutral"
                detail = f"رنگ‌زدگی {metric_before:.0f} → {metric_after:.0f}"
        elif key == "deflicker":
            metric_before, metric_after = number(before, "flicker"), number(after, "flicker")
            if metric_before is not None and metric_after is not None:
                verdict = "better" if metric_after < metric_before - 1 else (
                    "worse" if metric_after > metric_before + 1 else "neutral")
                detail = f"پرش نور {metric_before:.0f} → {metric_after:.0f}"
        elif key == "stabilize":
            metric_before, metric_after = number(before, "shake"), number(after, "shake")
            if metric_before is not None and metric_after is not None:
                verdict = "better" if metric_after < metric_before * 0.8 else (
                    "worse" if metric_after > metric_before * 1.2 else "neutral")
                detail = f"لرزش {metric_before * 1000:.1f} → {metric_after * 1000:.1f}"
        elif key == "denoise_audio":
            metric_before, metric_after = number(before, "snr_db"), number(after, "snr_db")
            if metric_before is not None and metric_after is not None:
                verdict = "better" if metric_after > metric_before + 2 else (
                    "worse" if metric_after < metric_before - 2 else "neutral")
                detail = f"فاصله‌ی صدا از نویز {metric_before:.0f} → {metric_after:.0f} دسی‌بل"
        elif key in ("trim_silence", "cut"):
            metric_before, metric_after = number(before, "duration"), number(after, "duration")
            if metric_before is not None and metric_after is not None:
                verdict = "better" if metric_after < metric_before - 0.2 else "neutral"
                detail = f"مدت {metric_before:.0f} → {metric_after:.0f} ثانیه"
        elif key == "normalize_audio":
            verdict = "applied"

        before, after = before_all, after_all
        if verdict == "worse":
            worse.append(title)
        effects.append({
            "tool": key, "title": title, "verdict": verdict, "detail": detail,
            "before": metric_before, "after": metric_after,
        })

    clip_before, clip_after = number(before, "clip_hi"), number(after, "clip_hi")
    if (clip_before is not None and clip_after is not None
            and clip_after > clip_before + 0.05):
        worse.append("سفیدشدن پیکسل‌ها")
        effects.append({
            "tool": "clipping", "title": "پیکسل‌های سوخته", "verdict": "worse",
            "detail": f"{clip_before * 100:.0f}٪ → {clip_after * 100:.0f}٪",
            "before": clip_before, "after": clip_after,
        })

    return (not worse), effects


#: A finding → the tool that addresses it. Used to keep round two from
#: re-proposing a correction round one already applied.
_TOOL_FOR_FINDING = {
    "dark": "brightness", "bright": "brightness", "flicker": "deflicker",
    "colour_cast": "white_balance", "shaky": "stabilize", "silence": "trim_silence",
    "noisy": "denoise_audio",
}


def run(
    source,
    out_path,
    work_dir,
    *,
    mode: str = AUTO,
    operations: list[dict] | None = None,
    instruction: str = "",
    store=None,
    job=None,
    subtitle_file=None,
    max_rounds: int = MAX_ROUNDS,
) -> Outcome:
    """Plan, render, look again. §9's loop, in full.

    SUGGEST mode stops after planning on purpose: the whole meaning of that mode
    is that a person sees the plan first, and rendering it would make the
    approval theatre.
    """
    source = Path(source)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    current = plan(
        source, work, mode=mode, operations=operations, instruction=instruction,
        store=store, job=job, subtitle_file=subtitle_file,
    )
    outcome = Outcome(plan=current, before=current.facts)

    if mode == SUGGEST:
        outcome.note = "پیشنهادها آماده است؛ منتظر تأیید شما."
        return outcome

    if current.does_nothing:
        outcome.note = "چیزی برای اصلاح پیدا نشد."
        outcome.after = current.facts
        return outcome

    source_now = source
    applied: set[str] = set()
    for round_number in range(1, max_rounds + 1):
        outcome.rounds = round_number
        rendered = work / f"edit_round{round_number}.mp4"

        if edl_module.needs_stabilization_pass(current.edl):
            try:
                edl_module.detect_stabilization(source_now, work, current.edl)
            except Exception as exc:  # noqa: BLE001
                logger.info("Stabilisation detect failed: %s", exc)
                current.edl.stabilize = ""
                current.edl.refusals.append(
                    "ثابت‌کردن تصویر روی این ویدیو ممکن نشد و از تدوین حذف شد"
                )

        current.edl.store = store
        edl_module.render(current.edl, rendered)
        if current.edl.denoise_report:
            outcome.denoise = dict(current.edl.denoise_report)
        applied |= {operation.tool for operation in current.edl.operations}
        outcome.output = rendered
        outcome.after = analysis.describe(rendered, work / f"after{round_number}")
        outcome.after["windows"] = measure_windows(
            rendered, current.edl.operations, work / f"after{round_number}",
        )

        # The second look: each tool against its own target. An edit that made
        # its target worse is reported as such rather than handed over as
        # finished work — unless a person chose it by hand, in which case the
        # numbers are shown and the choice is respected.
        improved, effects = judge(outcome.before, outcome.after, current.edl.operations)
        outcome.effects = effects
        if not improved and mode != MANUAL:
            worse = "، ".join(e["title"] for e in effects if e["verdict"] == "worse")
            outcome.improved = False
            outcome.note = (
                f"این تدوین تصویر را بهتر نکرد ({worse}). نسخه‌ی اصلی نگه داشته می‌شود."
            )
            outcome.output = None
            return outcome
        outcome.improved = improved

        remaining = analysis.obvious_problems(outcome.after)
        # Cuts already happened, and every correction already applied stays
        # applied: a second round may only fix what nothing has touched yet, or
        # it re-removes silences from a video that has none and stacks a second
        # brightness lift on the first.
        remaining = [
            f for f in remaining
            if f["what"] not in ("silence", "no_speech")
            and _TOOL_FOR_FINDING.get(f["what"]) not in applied
        ]
        if mode == MANUAL or not remaining or round_number == max_rounds:
            if not improved:
                outcome.note = "تدوین دستی اعمال شد؛ چند سنجه بدتر شد — اعداد را ببینید."
            else:
                outcome.note = (
                    "تدوین انجام شد." if not remaining
                    else "تدوین انجام شد؛ چند مورد جزئی باقی ماند."
                )
            break

        source_now = rendered
        # A push-in moves the crop window every frame, which the shake
        # measurement reads as camera jitter; stabilising a zoom would undo it.
        exclude = applied | ({"stabilize"} if "zoom" in applied else set())
        current = plan(
            rendered, work, mode=AUTO, store=store, job=job, exclude=exclude,
        )
        outcome.plan = current
        if current.does_nothing:
            outcome.note = "تدوین انجام شد."
            break

    return outcome
