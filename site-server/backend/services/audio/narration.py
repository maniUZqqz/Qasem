"""Turning one scene's written narration into the audio that ships. §7.

The three promises §7 makes, and where each one is kept:

* **«طول صدای هر صحنه با طول واقعی همان قطعه جور می‌شود — وسط جمله قطع نمی‌شود».**
  Kept by shortening the *text* before synthesis, not by cutting the audio
  after. Speeding a sentence up past about 1.25× stops sounding like a person,
  and trimming it cuts a word in half. Rewriting one sentence shorter is the
  only fix that leaves a listenable result, so `tighten` runs first, from a
  code-side estimate that costs nothing.
* **«برای صحنه‌های بدون حرف، سکوت می‌گذاریم نه صدای الکی».**
  A scene with no narration gets real silence of exactly the right length and
  is not scored — running QC on silence and reporting «شنیده شدن: ۰» would be
  flagging the thing we deliberately did.
* **«اگر بد بود، دوباره ساخته می‌شود».**
  Kept below, with one rule worth naming: **the best attempt wins, not the last
  one.** A retry can come out worse than what it replaced, and a loop that
  keeps whatever it finished with will sometimes ship the worse take after
  paying for two.

Order of operations, cheapest first: estimate, tighten if needed, synthesise,
fit, score, filter-repair, resynthesise. Everything before the last step is
free or nearly so.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from services.video.ffmpeg import (
    VideoProcessingError,
    fit_audio,
    make_silence,
    normalize_audio,
    probe_duration,
)

from . import lexicon, polish, qc
from .tts import TTSError

logger = logging.getLogger(__name__)

#: Characters per second of natural Persian narration, for the free estimate we
#: make before spending a synthesis call. Deliberately on the slow side: over-
#: estimating the length costs one short rewrite, under-estimating costs a
#: sentence cut in half.
SPEAKING_CPS = 12.5

#: How much `fit_audio` may compress before it stops sounding human. Matches the
#: default there; named here because it is the number that decides whether a
#: scene needs tightening at all.
MAX_TEMPO = 1.25

#: Two takes. A third has never turned a bad voice into a good one in practice —
#: the same engine says the same sentence the same way — and each costs the shop
#: a wait.
MAX_ATTEMPTS = 2


@dataclass
class SceneAudio:
    """What one scene's narration became, and everything worth reporting."""

    path: Path
    spoken_text: str = ""
    silent: bool = False
    attempts: int = 0
    report: qc.AudioQCReport | None = None
    warnings: list[str] = field(default_factory=list)
    tightened: bool = False

    @property
    def score(self) -> float:
        if self.report is None or not self.report.judged:
            return -1.0
        return self.report.overall

    def as_dict(self) -> dict:
        return {
            "silent": self.silent,
            "attempts": self.attempts,
            "tightened": self.tightened,
            "warnings": self.warnings,
            "qc": self.report.as_dict() if self.report else None,
        }


def estimate_seconds(text: str) -> float:
    """How long this will take to say, without asking the voice engine."""
    letters = len([c for c in (text or "") if not c.isspace()])
    return letters / SPEAKING_CPS if letters else 0.0


def fits(text: str, target_duration: float) -> bool:
    """Will this fit the scene window without being rushed or cut?"""
    if target_duration <= 0:
        return True
    return estimate_seconds(text) <= target_duration * MAX_TEMPO


TIGHTEN_SYSTEM = (
    "You shorten Persian narration lines for short advertising videos. "
    "You answer with a single valid JSON object and nothing else. "
    "You never add a claim, a price, or a feature that is not already in the "
    "original line."
)


def build_tighten_prompt(text: str, max_seconds: float, max_letters: int) -> str:
    return (
        "Shorten this Persian narration line so it can be spoken calmly in "
        f"{max_seconds:.1f} seconds — at most about {max_letters} letters "
        "(spaces excluded).\n\n"
        f"Original line:\n{text}\n\n"
        "Rules:\n"
        "- Persian only. Keep the same meaning and the same selling point.\n"
        "- Keep the product name and any number that was already there.\n"
        "- Remove filler and adjectives before removing information.\n"
        "- It must be a complete sentence, not a fragment.\n"
        "- Do not invent anything that was not in the original.\n\n"
        'Answer exactly: {"text": "..."}'
    )


def tighten(text: str, target_duration: float, *, store=None, job=None) -> tuple[str, bool]:
    """Rewrite one line short enough to fit. Returns (text, was_tightened).

    Never raises and never returns something longer than what it was given. A
    voice job that dies because the shortening model was unreachable would be a
    worse outcome than a slightly rushed sentence, so every failure path here
    returns the original text and lets the QC axes report the consequence.
    """
    if fits(text, target_duration):
        return text, False

    budget = max(1.0, target_duration * MAX_TEMPO)
    max_letters = max(12, int(budget * SPEAKING_CPS))
    try:
        from apps.ai.models import AIRequest
        from apps.ai.services import recorded_json_call
        from services.ai.gateway import text_provider
        from services.ai.router import TASK_REASONING, models_for

        parsed, _ = recorded_json_call(
            job=job,
            store=store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id="narration_tighten",
            prompt_version="1",
            provider=text_provider(store),
            models=models_for(TASK_REASONING),
            prompt=build_tighten_prompt(text, budget, max_letters),
            system=TIGHTEN_SYSTEM,
            validate=lambda parsed: (
                bool(str((parsed or {}).get("text", "")).strip()),
                ["فیلد text خالی است"],
            ),
            validation_message="مدل خط کوتاه‌شده را برنگرداند",
        )
    except Exception as exc:  # noqa: BLE001 — shortening is an optimisation
        logger.info("Could not tighten narration: %s", exc)
        return text, False

    shorter = str((parsed or {}).get("text", "")).strip()
    # Both guards matter: a model that returns the same line, or a longer one,
    # has not helped, and accepting it would mean reporting `tightened=True`
    # about a line we did not change.
    if not shorter or len(shorter) >= len(text):
        return text, False
    return shorter, True


def _synthesize(tts, text: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return Path(tts.synthesize(text, out_path))


def narrate_scene(
    *,
    tts,
    text: str,
    target_duration: float,
    out_path,
    work_dir,
    store=None,
    job=None,
    scene_label: str = "",
    max_attempts: int = MAX_ATTEMPTS,
    score: bool = True,
) -> SceneAudio:
    """One scene's narration: spoken form, fitted length, scored, repaired.

    Never raises for a quality reason. The only exception that escapes is a TTS
    failure on the *first* attempt, because at that point there is no audio at
    all and pretending otherwise would put a silent gap in the middle of a
    finished video without telling anyone.
    """
    out_path = Path(out_path)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    label = scene_label or out_path.stem

    # --- silence, on purpose ---------------------------------------------
    if not (text or "").strip():
        make_silence(target_duration, out_path)
        return SceneAudio(path=out_path, silent=True)

    # --- what the voice should actually say -------------------------------
    spoken = lexicon.apply(text, store)
    spoken, was_tightened = tighten(spoken, target_duration, store=store, job=job)

    result = SceneAudio(path=out_path, spoken_text=spoken, tightened=was_tightened)
    if was_tightened:
        result.warnings.append(
            f"نریشن {label} برای جا شدن در صحنه کوتاه‌تر نوشته شد"
        )
    unresolved = lexicon.unresolved_latin(spoken, store)
    if unresolved:
        result.warnings.append(
            f"تلفظ این کلمه‌ها را نداریم و حرف‌به‌حرف خوانده می‌شوند: "
            f"{'، '.join(unresolved[:5])}"
        )

    best: tuple[float, Path, qc.AudioQCReport | None] | None = None

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        raw = work / f"{out_path.stem}_take{attempt}.mp3"
        try:
            # The engine may write a different file than asked (Piper writes
            # PCM .wav rather than encoding an .mp3 it would only decode again).
            raw = _synthesize(tts, spoken, raw)
        except TTSError:
            if attempt == 1:
                raise
            # A later take failing is survivable: an earlier one exists.
            logger.info("Narration take %s failed for %s", attempt, label)
            break
        # Studio polish before anything measures it: rumble out, sibilance
        # tamed, level to target, 48 kHz. QC then scores the voice the viewer
        # will actually hear, not the engine's raw output.
        raw = polish.maybe_polish(raw, work / f"{out_path.stem}_polished{attempt}.wav")

        raw_seconds = probe_duration(raw)
        if raw_seconds > target_duration * MAX_TEMPO + 0.05:
            result.warnings.append(
                f"نریشن {label} ({raw_seconds:.1f} ثانیه) از پنجره‌ی صحنه "
                f"({target_duration:.1f} ثانیه) بلندتر است"
            )

        candidate = work / f"{out_path.stem}_fit{attempt}.m4a"
        fit_audio(raw, candidate, target_duration, max_tempo=MAX_TEMPO)

        if not score:
            _publish(candidate, out_path)
            return result

        report = qc.check(candidate, work, text=spoken, store=store)

        # Filters first: the two axes they cover are the two that never need a
        # second synthesis, and trying them costs milliseconds.
        if report.judged and not report.acceptable and report.code_fixable \
                and not report.needs_resynthesis:
            repaired = work / f"{out_path.stem}_fixed{attempt}.m4a"
            try:
                # To the same target as the polish, or the "fix" would move a
                # polished voice 2 dB off the level the mix is built around.
                normalize_audio(candidate, repaired, target_db=polish.settings_mix().voice_lufs)
                after = qc.check(repaired, work, text=spoken, store=store)
                if after.overall > report.overall:
                    candidate, report = repaired, after
                    result.warnings.append(f"بلندی صدای {label} اصلاح شد")
            except VideoProcessingError as exc:
                logger.info("Could not normalise %s: %s", label, exc)

        # Best, not last. A retry is allowed to be worse than what it replaced,
        # and keeping the worse take after paying for both is the failure this
        # avoids.
        if best is None or report.overall > best[0]:
            best = (report.overall, candidate, report)

        if not report.judged or report.acceptable:
            break

        if attempt < max_attempts:
            result.warnings.append(
                f"صدای {label} نمره‌ی {report.overall:.0f} گرفت و دوباره ساخته شد"
            )

    if best is None:
        # Every take failed after the first one already succeeded — not
        # reachable through the loop above, but silence is the safe floor.
        make_silence(target_duration, out_path)
        result.silent = True
        result.warnings.append(f"صدای {label} ساخته نشد و جایش سکوت گذاشته شد")
        return result

    _publish(best[1], out_path)
    result.report = best[2]
    return result


def _publish(candidate: Path, out_path: Path) -> None:
    """Move the winning take into place."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if Path(candidate) == out_path:
        return
    out_path.write_bytes(Path(candidate).read_bytes())


def summarize(results: list[SceneAudio]) -> dict:
    """One verdict for a whole narration track.

    The overall score is the **worst** scene, not the mean. A video is watched
    start to finish; one unlistenable scene is the thing the viewer remembers,
    and averaging it against five good ones describes a listening experience
    nobody has.
    """
    scored = [r for r in results if r.report is not None and r.report.judged]
    warnings = [w for r in results for w in r.warnings]
    if not scored:
        return {
            "scored": 0,
            "silent": sum(1 for r in results if r.silent),
            "overall": None,
            "verdict": "UNJUDGED",
            "warnings": warnings,
        }
    worst = min(r.report.overall for r in scored)
    return {
        "scored": len(scored),
        "silent": sum(1 for r in results if r.silent),
        "overall": round(worst, 1),
        "verdict": qc.verdict_for(worst),
        "weakest_scene": min(scored, key=lambda r: r.report.overall).path.stem,
        "retries": sum(max(0, r.attempts - 1) for r in results),
        "warnings": warnings,
    }
