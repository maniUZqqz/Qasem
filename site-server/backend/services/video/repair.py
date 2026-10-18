"""Fixing what can be fixed with code, so the GPU is the last resort.

ROADMAP §9.3: "این معماری باعث می‌شود AI گران‌قیمت آخرین گزینه باشد، نه اولین
گزینه." The economics behind that sentence are the whole product: a segment
costs three to nine minutes of a card we own one of, and re-rendering it
because the exposure was low is spending that to do what a colour curve does in
two seconds.

So a failed segment goes down a ladder, cheapest first:

    detected problem → can ffmpeg fix it? → yes: filter, re-check
                                          → no:  regenerate that ONE segment

**One function decides.** `decide()` is the only place a QC report becomes an
action, and everything else — the pipeline, the Persian plan the panel shows,
the filter chain — reads its answer. Before it existed the decision was spread
across four places (the code axes, the vision axes, the verdict label and a
display-only `plan`) and a frozen clip fell through every one of them into
"REVIEW: cause unknown" while its own note said "the clip freezes".

**Amounts come from the measurement, not from a constant.** `eq=brightness`
moves mean luma by about 250 units per 1.0 (measured: +0.06 → +12, +0.15 →
+37, +0.25 → +63 on yuv420p), so a clip whose brightest 5 % sits at 70 gets
the correction that brings it to ~200, and a clip whose brightest 5 % sits at
20 is not "corrected" at all — no filter turns black into a picture, and
pretending otherwise burns a re-check and hands the next segment a grey
anchor. It goes to regeneration.

**Level 2 is deliberately absent.** Localised repair of one bad hand needs a
segmentation mask and an inpainting model. Approximating it with a blur turns a
wrong hand into a smear, which is worse — the customer can at least describe
the first problem. `qc.QCReport.localized_repair_available` stays False and the
job goes to level 3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .ffmpeg import FFMPEG, VideoProcessingError, _run

logger = logging.getLogger(__name__)

ACCEPT = "ACCEPT"
CODE_REPAIR = "CODE_REPAIR"
REGENERATE = "REGENERATE"
REVIEW = "REVIEW"

#: Where a dark clip's brightest 5 % should land, and where a burnt clip's
#: darkest 5 % should. Both leave headroom: the aim is "no longer wrong", not
#: "perfect", because the shop chose the look and we did not.
DARK_TARGET_P95 = 200.0
BLOWN_TARGET_P5 = 60.0

#: Measured slope of eq=brightness on 8-bit luma.
BRIGHTNESS_SLOPE = 250.0
MAX_BRIGHTNESS_STEP = 0.25
MIN_BRIGHTNESS_STEP = 0.03

#: Colour correction is a per-channel GAIN (colorchannelmixer), not
#: `colorbalance`: measured on this ffmpeg build, colorbalance with rm=-0.18 and
#: bm=+0.18 left a warm grey at (162,139,117) → (162,138,116) — no effect —
#: while colorchannelmixer rr=0.86:bb=1.19 brought it to (139,138,138). The
#: gains bring the neutral pixels' red and blue to their green; a saturated
#: product pixel is scaled by the same small factors and keeps its hue. Capped:
#: a bigger swing than this is a grade, not a correction.
MAX_GAIN_SWING = 0.20

#: Applied together when several problems are found, in this order. Deflicker
#: first: correcting exposure on a flickering clip bakes the flicker in.
ORDER = ["FLICKER", "EXPOSURE", "COLOR"]

#: Persian names for the causes, shared by the plan and the panel.
NAMES = {
    "EXPOSURE": "نوردهی",
    "FLICKER": "پرش نور",
    "COLOR": "رنگ",
    "CHARACTER_CONSISTENCY": "شخصیت عوض شده",
    "OBJECT_CONSISTENCY": "محصول عوض شده",
    "ANATOMY": "دست یا اندام خراب است",
    "ARTIFACTS": "خرابی تصویری",
    "BLACK": "تصویر سیاه است",
    "DARK": "تصویر خیلی تاریک است",
    "FROZEN": "کلیپ بی‌حرکت مانده",
    "MOTION_JUMP": "پرش ناگهانی صحنه",
    "COLOUR_DRIFT": "رنگ صحنه در طول کلیپ عوض می‌شود",
    "TALKING": "آدمِ تصویر لب می‌زند ولی صدا گوینده است",
}


@dataclass
class Decision:
    action: str
    causes: list[str] = field(default_factory=list)
    #: Filter strings, in application order, when action is CODE_REPAIR.
    filters: list[str] = field(default_factory=list)
    reason: str = ""
    cost: str = ""

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "causes": self.causes,
            "filters": self.filters,
            "reason": self.reason,
            "cost": self.cost,
        }


class RepairResult:
    def __init__(self, repaired: bool, path: Path, applied: list[str], note: str = "",
                 filters: list[str] | None = None):
        self.repaired = repaired
        self.path = path
        self.applied = applied
        self.note = note
        self.filters = filters or []

    def as_dict(self) -> dict:
        return {
            "repaired": self.repaired,
            "applied": self.applied,
            "filters": self.filters,
            "note": self.note,
        }


# ---------------------------------------------------------------- amounts


def _f(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


#: Where a dark clip's midtone should land after the lift.
DARK_TARGET_P50 = 110.0
#: Past this the lift is noise amplification, not a correction; the clip goes
#: to regeneration with a "well-lit" hint instead.
MAX_GAMMA = 2.8
MIN_GAMMA = 1.05
#: Above this gamma the lifted shadows show their noise; a light denoise pass
#: goes in the same chain.
DENOISE_ABOVE_GAMMA = 1.8


def _gamma_for(p50: float | None) -> float | None:
    """eq=gamma that maps the measured midtone onto DARK_TARGET_P50.

    ffmpeg's eq applies value^(1/gamma), so gamma > 1 lifts. Solving
    (p50/255)^(1/g) = target/255 gives g = ln(p50/255) / ln(target/255)
    (measured: p50 57 → g 1.78 lands on 110). Returns None when the clip is so
    dark that the gamma would exceed MAX_GAMMA.
    """
    import math

    if p50 is None:
        return 1.4
    value = max(1.0, min(254.0, float(p50)))
    if value >= DARK_TARGET_P50:
        return None
    gamma = math.log(value / 255.0) / math.log(DARK_TARGET_P50 / 255.0)
    if gamma > MAX_GAMMA:
        return None
    return max(MIN_GAMMA, gamma)


def filters_for(report) -> dict[str, str]:
    """problem → ffmpeg filter, sized from the report's measurements.

    Only the problems the report lists as code-fixable get a filter, and only
    when the numbers say a filter would do something. A cast the frame could
    not measure (no neutral pixels) gets no colour filter at all — that is the
    "coloured product is not a cast" rule, enforced a second time here.
    """
    m = report.measurements or {}
    out: dict[str, str] = {}

    if "FLICKER" in report.code_fixable:
        fps = float(m.get("fps") or 0.0)
        size = int(_clamp(round(fps / 4) if fps else 5, 3, 10))
        out["FLICKER"] = f"deflicker=size={size}:mode=pm"

    if "EXPOSURE" in report.code_fixable:
        p95 = m.get("p95")
        p50 = m.get("p50")
        p5 = m.get("p5")
        if p95 is not None and float(p95) < DARK_TARGET_P95 and (p5 is None or float(p5) <= 120):
            # A dark clip is lifted with GAMMA, not an offset: an offset large
            # enough to matter (+0.25) raises the blacks to 56 and the picture
            # goes milky; gamma leaves black at black and lifts the midtones
            # (measured: gamma 1.8 → mean 44→85, highlights 97→149, black 0→0).
            # Sized from the midtone so p50 lands near DARK_TARGET_P50.
            gamma = _gamma_for(float(p50) if p50 is not None else None)
            if gamma is not None:
                chain = f"eq=gamma={_f(gamma)}:contrast=1.04"
                if gamma > DENOISE_ABOVE_GAMMA:
                    chain += ",hqdn3d=2"
                out["EXPOSURE"] = chain
        elif p5 is not None and float(p5) > BLOWN_TARGET_P5:
            step = _clamp((BLOWN_TARGET_P5 - float(p5)) / BRIGHTNESS_SLOPE,
                          -MAX_BRIGHTNESS_STEP, -MIN_BRIGHTNESS_STEP)
            out["EXPOSURE"] = f"eq=brightness={_f(step)}"
        elif not m:
            # No measurements at all (an old report): a conservative lift.
            out["EXPOSURE"] = "eq=gamma=1.25"

    if "COLOR" in report.code_fixable:
        gains = channel_gains(m.get("neutral_rgb"))
        if gains:
            rr, bb = gains
            out["COLOR"] = f"colorchannelmixer=rr={_f(rr)}:bb={_f(bb)}"

    return out


def channel_gains(neutral_rgb) -> tuple[float, float] | None:
    """(red gain, blue gain) that turn the measured neutral colour grey.

    None when there was nothing neutral to measure — a coloured product
    filling the frame is not a cast and gets no correction at all.
    """
    if not neutral_rgb or len(neutral_rgb) != 3:
        return None
    r, g, b = (float(v) for v in neutral_rgb)
    if r < 1 or g < 1 or b < 1:
        return None
    rr = _clamp(g / r, 1 - MAX_GAIN_SWING, 1 + MAX_GAIN_SWING)
    bb = _clamp(g / b, 1 - MAX_GAIN_SWING, 1 + MAX_GAIN_SWING)
    if abs(rr - 1) < 0.02 and abs(bb - 1) < 0.02:
        return None
    return rr, bb


# --------------------------------------------------------------- decision


def decide(report) -> Decision:
    """The one place a QC report becomes an action.

    Order of the rules matters and is deliberate:

    1. Nobody looked → REVIEW. A system problem is not a quality verdict.
    2. Anything only a regeneration can fix (wrong product, wrong person, bad
       hands, artifacts, a black or frozen clip, a jump cut) → REGENERATE,
       *even if* a colour fix is also possible. A correctly lit clip of the
       wrong product is still the wrong product, and the owner would have paid
       for the filter pass as well.
    3. Code-fixable problems with a filter that would actually change
       something → CODE_REPAIR.
    4. Verdict already acceptable → ACCEPT.
    5. Otherwise → REVIEW: something is off and no rule owns it.
    """
    if report.error or not report.axes:
        return Decision(REVIEW, [], [], report.error or "چیزی بررسی نشد", "تصمیم با شماست")

    causes = list(dict.fromkeys(report.needs_regeneration or []))
    if causes:
        problems = "، ".join(NAMES.get(c, c) for c in causes)
        return Decision(
            REGENERATE, causes, [],
            f"{problems} — با کد قابل اصلاح نیست",
            # Named explicitly so the owner understands the trade before the
            # attempt counter moves.
            "یک رندر دوباره، فقط همین قطعه",
        )

    chain = filters_for(report)
    # A clip too dark for any gamma to rescue is not code-fixable, whatever
    # the exposure axis said: lifting it would only amplify noise.
    if "EXPOSURE" in report.code_fixable and "EXPOSURE" not in chain:
        m = report.measurements or {}
        p50 = m.get("p50")
        if p50 is not None and float(p50) < DARK_TARGET_P50:
            return Decision(
                REGENERATE, ["DARK"], [],
                f"{NAMES['DARK']} — با فیلتر قابل نجات نیست",
                "یک رندر دوباره، فقط همین قطعه",
            )
    wanted = [p for p in ORDER if p in chain]
    if wanted and report.verdict != "EXCELLENT":
        problems = "، ".join(NAMES.get(p, p) for p in wanted)
        return Decision(
            CODE_REPAIR, wanted, [chain[p] for p in wanted],
            f"{problems} — با فیلتر قابل اصلاح است",
            "چند ثانیه CPU، بدون GPU",
        )

    if report.verdict in ("EXCELLENT", "GOOD"):
        return Decision(ACCEPT, [], [], "کیفیت قابل قبول است", "هیچ")

    return Decision(REVIEW, [], [], "کیفیت پایین است ولی علت مشخص نشد", "تصمیم با شماست")


def can_fix_with_code(report) -> bool:
    """True when the right next step is a filter pass and nothing more."""
    return decide(report).action == CODE_REPAIR


def plan(report) -> dict:
    """What to do about this report, in words the panel can show.

    Returned rather than acted on, because the decision belongs to the
    pipeline: only it knows whether a regeneration is still within the store's
    quality guarantee.
    """
    decision = decide(report)
    return {"action": decision.action, "reason": decision.reason, "cost": decision.cost,
            "causes": decision.causes}


# ------------------------------------------------------------------ apply


def repair_with_code(video_path, report, out_path=None) -> RepairResult:
    """Apply the filters `decide()` chose. No GPU, no model call."""
    source = Path(video_path)
    decision = report if isinstance(report, Decision) else decide(report)
    if decision.action != CODE_REPAIR or not decision.filters:
        return RepairResult(False, source, [], "چیزی برای اصلاح با کد نبود")

    chain = ",".join(decision.filters)
    out = Path(out_path) if out_path else source.with_name(f"{source.stem}_fixed.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    from .ffmpeg import VIDEO_DELIVERY

    try:
        _run([
            FFMPEG, "-y", "-i", str(source),
            "-vf", chain,
            # Re-encode only the video; copying audio keeps the narration
            # untouched when this runs after the mix. The delivery profile,
            # so the repaired part matches its neighbours at the stitch.
            "-c:a", "copy",
            *VIDEO_DELIVERY,
            str(out),
        ])
    except VideoProcessingError as exc:
        logger.info("Code repair failed for %s: %s", source, exc)
        return RepairResult(False, source, [], f"اصلاح با کد انجام نشد: {exc}"[:300])

    if not out.exists() or out.stat().st_size == 0:
        return RepairResult(False, source, [], "فایل اصلاح‌شده نوشته نشد")

    logger.info("Code repair applied to %s: %s", source.name, decision.causes)
    return RepairResult(
        True, out, list(decision.causes), "با کد اصلاح شد — بدون مصرف GPU", decision.filters,
    )


#: A repair has to move its own axis at least this much to be kept.
MIN_IMPROVEMENT = 8.0

_AXIS_FOR = {"EXPOSURE": "نوردهی", "FLICKER": "پیوستگی زمانی", "COLOR": "ثبات رنگ"}


def kept_the_repair(before, after, causes: list[str]) -> tuple[bool, str]:
    """Did the filter pass actually help? Decided on the axes it targeted.

    A repair that did nothing used to be kept anyway, and its frame became
    the next segment's anchor. Now the corrected file survives only if every
    targeted axis improved and nothing else got clearly worse.
    """
    if not after.judged:
        return False, "نسخه‌ی اصلاح‌شده بررسی نشد"
    for cause in causes:
        name = _AXIS_FOR.get(cause)
        if not name:
            continue
        old = before.axis(name)
        new = after.axis(name)
        if old is None or new is None:
            continue
        if new.score < old.score + MIN_IMPROVEMENT and new.score < 95:
            return False, f"فیلتر «{NAMES.get(cause, cause)}» بهبودی نداد"
    for axis in after.axes:
        old = before.axis(axis.name)
        if old is not None and axis.score < old.score - 10:
            return False, f"«{axis.name}» بعد از فیلتر بدتر شد"
    return True, ""
