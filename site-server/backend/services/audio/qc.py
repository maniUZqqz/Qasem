"""Listening to the narration before the customer does. §7.

§7 asks for a score on the audio, with three named questions: «تلفظ درست است؟
مکث‌ها طبیعی‌اند؟ صدا بریده‌بریده یا فلزی نیست؟». Two of those three are
measurable from the waveform. The third is not, and this module says so rather
than inventing a number for it.

**What code can hear.** Speech is an envelope: loud stretches separated by
pauses. Everything here is a property of that envelope — is there any speech at
all, is it clipping, does it stop mid-word, are the gaps the shape of breathing
or the shape of a decoder dropping frames, is it being rushed. None of that
needs a model, and a model would be slower and less certain about all of it.

**What code cannot hear.** Whether «Nike» came out as «نایکی» or as four
English letters. There is no signal-level difference between a correctly and
incorrectly pronounced word — they are both speech. So pronunciation is not
scored here; it is *prevented* upstream by `lexicon.py`, and the report carries
`unresolved` so the shop sees the words we had no pronunciation for. A
confident-looking «تلفظ: ۹۲» would be a fabricated number about the one thing
we cannot check.

**No new dependency.** Decoding goes through the ffmpeg we already require, and
the analysis is `wave` plus `array` from the standard library. numpy is present
in this environment only as somebody else's transitive dependency and building
the audio engine on top of that would be borrowing a promise nobody made.
"""
from __future__ import annotations

import array
import logging
import math
import wave
from dataclasses import dataclass, field
from pathlib import Path

from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run

logger = logging.getLogger(__name__)

#: Speech lives below 8 kHz; 16 kHz mono is plenty for an envelope and keeps a
#: thirty-second clip under a megabyte of samples.
ANALYSIS_RATE = 16_000

#: 20 ms windows. Short enough to see a dropped syllable, long enough that one
#: zero-crossing does not read as a pause.
WINDOW_MS = 20

#: Below this fraction of the clip's own speech level, a window is silence.
#: Relative rather than absolute because a quiet recording is still speech.
SILENCE_RATIO = 0.08

#: A dropout is a gap this short *or shorter*, and the number is low on purpose.
#:
#: The naive version of this axis — "count every gap under 300 ms" — flags every
#: normal clip ever recorded, because ordinary speech is full of short silences:
#: the closure of a /p/ or /t/ inside a word is 50–100 ms of near-silence, and a
#: pause between words is 150–300 ms. Both are what speech sounds like. Only a
#: gap shorter than the shortest closure a mouth can make is a decoder dropping
#: frames, and that is the thing §7 calls «بریده‌بریده».
DROPOUT_MS = 60

#: …and it only counts when the audio was loud on both sides of it. A consonant
#: closure sits in the quiet tail of a syllable; a dropped frame cuts a hole in
#: the middle of a loud one. That difference is the whole test.
DROPOUT_FLANK = 0.5

#: Natural Persian narration, characters per second of actual speech. The upper
#: bound is what matters in practice: `fit_audio` speeds narration up to fit a
#: scene, and past this it stops sounding like a person.
PACE_MIN = 8.0
PACE_MAX = 17.0

#: Speech peaking above this is on its way to the metallic, distorted sound §7
#: names. 16-bit full scale is 32767.
CLIP_LEVEL = 32_000

#: Speech in the last window means the clip was cut mid-sentence — «وسط جمله
#: قطع نمی‌شود» is the requirement this measures.
TAIL_MS = 120

#: Same cap as video QC, for the same reason: a clip that is perfect on five
#: axes and silent on the sixth is not a good clip.
WORST_AXIS_HEADROOM = 15.0

AUDIBLE = "شنیده شدن"
CONTINUITY = "پیوستگی صدا"
DISTORTION = "نبود اعوجاج"
PACE = "سرعت گفتار"
COMPLETENESS = "کامل بودن جمله"
LEVEL = "بلندی صدا"

#: Loudness is a comfort axis, not a correctness one — a quiet narration is
#: fixable with a gain filter and does not justify regenerating anything.
WEIGHTS = {
    AUDIBLE: 3.0,
    CONTINUITY: 1.6,
    DISTORTION: 1.4,
    COMPLETENESS: 1.2,
    PACE: 1.0,
    LEVEL: 0.5,
}

#: Which axes a filter can rescue, and which need the voice engine run again.
CODE_FIXABLE = {LEVEL, DISTORTION}


@dataclass
class Axis:
    name: str
    score: float
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "score": round(self.score, 1), "note": self.note}


@dataclass
class AudioQCReport:
    axes: list[Axis] = field(default_factory=list)
    overall: float = 0.0
    verdict: str = "REVIEW"
    code_fixable: list[str] = field(default_factory=list)
    needs_resynthesis: list[str] = field(default_factory=list)
    #: Latin words with no pronunciation entry — the honest stand-in for the
    #: pronunciation axis we refuse to score.
    unresolved: list[str] = field(default_factory=list)
    duration: float = 0.0
    speech_seconds: float = 0.0
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "overall": round(self.overall, 1),
            "verdict": self.verdict,
            "axes": [a.as_dict() for a in self.axes],
            "code_fixable": self.code_fixable,
            "needs_resynthesis": self.needs_resynthesis,
            "unresolved": self.unresolved,
            "duration": round(self.duration, 2),
            "speech_seconds": round(self.speech_seconds, 2),
            "pronunciation_judged": False,
            "error": self.error,
        }

    @property
    def judged(self) -> bool:
        """Did anyone actually listen?

        Same distinction video QC makes: a bad score should stop the pipeline, a
        report that could not be produced should not — that is a missing ffmpeg,
        not a quality collapse, and treating the two the same turns a
        configuration problem into a wall of approval prompts.
        """
        return not self.error and bool(self.axes)

    @property
    def score_fraction(self) -> float | None:
        if not self.judged:
            return None
        return self.overall / 100.0

    @property
    def acceptable(self) -> bool:
        return self.verdict in ("EXCELLENT", "GOOD")


# ------------------------------------------------------------------ decoding


def decode(path, work_dir) -> tuple[array.array, int]:
    """Any audio file → 16-bit mono samples at ANALYSIS_RATE.

    Raises VideoProcessingError when ffmpeg cannot read the file; callers above
    turn that into `report.error`, never into a crash.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "qc_analysis.wav"
    _run([
        FFMPEG, "-y", "-i", str(path),
        "-ac", "1", "-ar", str(ANALYSIS_RATE), "-acodec", "pcm_s16le",
        str(wav),
    ])
    with wave.open(str(wav), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        rate = handle.getframerate()
    samples = array.array("h")
    samples.frombytes(frames)
    return samples, rate


def _windows(samples: array.array, rate: int) -> list[float]:
    """RMS per 20 ms window.

    Straight Python over roughly 1500 windows for a thirty-second clip. Slower
    than numpy and irrelevantly so — the ffmpeg decode above costs more.
    """
    size = max(1, int(rate * WINDOW_MS / 1000))
    out = []
    for start in range(0, len(samples) - size + 1, size):
        chunk = samples[start:start + size]
        total = 0
        for value in chunk:
            total += value * value
        out.append(math.sqrt(total / size))
    return out


def reference_level(levels: list[float]) -> float:
    """The level speech is typically at — not the single loudest window.

    The floor used to be 8 % of the loudest 20 ms window. Phone footage has
    claps, mic bumps, door slams and plosives: one −1 dBFS click put the whole
    conversation below the floor (measured: 9 s of "silence" in a 20 s clip
    became 18 s), so `trim_silence` removed the talking and the subtitles
    mis-timed. The 90th percentile of the active windows is what a person
    means by "how loud the speech is".
    """
    peak = max(levels, default=0.0)
    if peak <= 0:
        return 0.0
    active = sorted(level for level in levels if level > peak * 0.02)
    if len(active) < 25:
        return peak
    return active[min(len(active) - 1, int(len(active) * 0.9))]


def silence_floor(levels: list[float]) -> float:
    return reference_level(levels) * SILENCE_RATIO


#: Leaving silence needs this much more than entering it (hysteresis), and a
#: burst of "speech" shorter than this many windows inside a pause is noise.
EXIT_RATIO = 1.5
MIN_SPEECH_WINDOWS = 3


def silence_mask(levels: list[float], floor: float) -> list[bool]:
    """True where the window is silent, with hysteresis.

    Enter silence when the level drops to the floor; leave it only when the
    level rises to 1.5× the floor, and ignore speech runs shorter than 60 ms
    inside a pause — otherwise a single noisy window splits one pause into
    two, and the editor keeps a stutter of a pause on each side of it.
    """
    silent = []
    in_silence = False
    for level in levels:
        if in_silence:
            in_silence = level < floor * EXIT_RATIO
        else:
            in_silence = level <= floor
        silent.append(in_silence)
    # Absorb short speech bursts between two silent stretches.
    index = 0
    while index < len(silent):
        if not silent[index]:
            run_start = index
            while index < len(silent) and not silent[index]:
                index += 1
            run_length = index - run_start
            if (run_length < MIN_SPEECH_WINDOWS and run_start > 0
                    and index < len(silent)):
                for k in range(run_start, index):
                    silent[k] = True
        else:
            index += 1
    return silent


def _runs_of_silence(levels: list[float], floor: float) -> list[tuple[int, int]]:
    """Silent stretches strictly *between* speech, as (start, length) windows.

    Leading and trailing silence is excluded on purpose: a pause before the
    first word is padding we asked for, and a pause after the last one is the
    scene ending. Neither is a defect; only gaps inside speech are.
    """
    silent = silence_mask(levels, floor)
    speech = [i for i, quiet in enumerate(silent) if not quiet]
    if len(speech) < 2:
        return []
    runs, start = [], None
    for index in range(speech[0], speech[-1] + 1):
        if silent[index]:
            start = index if start is None else start
        elif start is not None:
            runs.append((start, index - start))
            start = None
    return runs


def _dropouts(levels: list[float], floor: float, peak: float) -> list[int]:
    """Holes punched in loud speech — the ones that sound like broken audio.

    Two conditions, and both are needed. Short, because a gap longer than a
    consonant closure is a pause a person made. Flanked by loud audio, because
    that is what separates a dropped frame from the natural quiet at the end of
    a syllable — the mouth gets quiet gradually, a decoder does not.
    """
    limit = max(1, int(DROPOUT_MS / WINDOW_MS))
    flank = peak * DROPOUT_FLANK
    out = []
    for start, length in _runs_of_silence(levels, floor):
        if length > limit:
            continue
        before = levels[start - 1] if start > 0 else 0.0
        after = levels[start + length] if start + length < len(levels) else 0.0
        if before >= flank and after >= flank:
            out.append(start)
    return out


# -------------------------------------------------------------------- axes


def _score_from(value: float, good: float, bad: float) -> float:
    """Linear score where `good` is 100 and `bad` is 0, either direction."""
    if good == bad:
        return 100.0
    fraction = (value - bad) / (good - bad)
    return max(0.0, min(100.0, fraction * 100.0))


def measure(samples: array.array, rate: int, *, text: str = "") -> list[Axis]:
    """Every axis the waveform can answer."""
    if not samples:
        return [Axis(AUDIBLE, 0.0, "فایل صدا خالی است")]

    levels = _windows(samples, rate)
    if not levels:
        return [Axis(AUDIBLE, 0.0, "صدا کوتاه‌تر از یک پنجره‌ی تحلیل است")]

    window_seconds = WINDOW_MS / 1000
    peak_level = max(levels)
    floor = silence_floor(levels)
    speech = [level for level in levels if level > floor]
    speech_seconds = len(speech) * window_seconds
    duration = len(levels) * window_seconds

    axes: list[Axis] = []

    # --- is there speech at all -------------------------------------------
    # Absolute, not relative: a clip of pure noise has a peak and a floor and a
    # perfectly respectable ratio between them, and is still silence.
    #
    # The threshold is digital near-silence (about -49 dBFS), not "quiet". A
    # narration recorded too softly is a real clip that the LEVEL axis reports
    # and a gain filter fixes; calling it inaudible here would send it back to
    # the voice engine, which would return exactly the same quiet audio.
    absolute_peak = max(abs(v) for v in samples)
    if absolute_peak < 120 or speech_seconds < 0.15:
        axes.append(Axis(
            AUDIBLE, 0.0,
            "چیزی در این فایل شنیده نمی‌شود — موتور صدا فایل ساخته ولی حرفی در آن نیست",
        ))
        return axes

    # Measured against how long the TEXT takes to say, when we know the text —
    # not against the scene window. A three-word call to action in a five-
    # second scene is 26 % speech by design, and scoring that as "barely
    # audible" sent a perfect take back to the voice engine, which said the
    # same three words again and was marked down again.
    letters = len([c for c in text if not c.isspace()]) if text else 0
    expected = letters / 12.5 if letters else 0.0
    if expected > 0:
        span = min(duration, max(expected, 0.5)) if duration else expected
        talk_ratio = speech_seconds / span if span else 0
        axes.append(Axis(
            AUDIBLE,
            _score_from(talk_ratio, good=0.55, bad=0.15),
            f"{round(min(1.0, talk_ratio) * 100)}٪ متن شنیده می‌شود",
        ))
    else:
        talk_ratio = speech_seconds / duration if duration else 0
        axes.append(Axis(
            AUDIBLE,
            _score_from(talk_ratio, good=0.55, bad=0.12),
            f"{round(talk_ratio * 100)}٪ این قطعه حرف است",
        ))

    # --- choppy or continuous ---------------------------------------------
    drops = _dropouts(levels, floor, peak_level)
    per_second = len(drops) / speech_seconds if speech_seconds else 0
    axes.append(Axis(
        CONTINUITY,
        _score_from(per_second, good=0.2, bad=2.0),
        (
            f"{len(drops)} قطع ناگهانی وسط حرف — صدا بریده‌بریده است"
            if per_second > 0.6 else "صدا پیوسته است"
        ),
    ))

    # --- distortion --------------------------------------------------------
    clipped = sum(1 for value in samples if abs(value) >= CLIP_LEVEL)
    clip_fraction = clipped / len(samples)
    axes.append(Axis(
        DISTORTION,
        _score_from(clip_fraction, good=0.0002, bad=0.02),
        (
            "صدا در جاهایی به سقف خورده و فلزی شنیده می‌شود"
            if clip_fraction > 0.004 else "اعوجاج محسوسی ندارد"
        ),
    ))

    # --- cut off mid-sentence ---------------------------------------------
    tail = max(1, int(TAIL_MS / WINDOW_MS))
    ends_talking = any(level > floor for level in levels[-tail:])
    axes.append(Axis(
        COMPLETENESS,
        35.0 if ends_talking else 100.0,
        (
            "قطعه وسط حرف تمام می‌شود — نریشن از پنجره‌ی صحنه بلندتر بوده"
            if ends_talking else "جمله تمام شده و بعدش سکوت است"
        ),
    ))

    # --- pace --------------------------------------------------------------
    # Only when we know what was supposed to be said; characters per second of
    # speech is meaningless without the text.
    letters = len([c for c in text if not c.isspace()]) if text else 0
    if letters and speech_seconds:
        rate_cps = letters / speech_seconds
        if rate_cps > PACE_MAX:
            score = _score_from(rate_cps, good=PACE_MAX, bad=PACE_MAX * 1.8)
            note = "تندتر از حرف‌زدن طبیعی — نریشن برای جا شدن در صحنه فشرده شده"
        elif rate_cps < PACE_MIN:
            score = _score_from(rate_cps, good=PACE_MIN, bad=PACE_MIN * 0.4)
            note = "کندتر از حرف‌زدن طبیعی"
        else:
            score, note = 100.0, "سرعت گفتار طبیعی است"
        axes.append(Axis(PACE, score, note))

    # --- loudness ----------------------------------------------------------
    mean_speech = sum(speech) / len(speech)
    dbfs = 20 * math.log10(mean_speech / 32768) if mean_speech > 0 else -90
    if dbfs > -12:
        score, note = _score_from(dbfs, good=-12, bad=-3), "بلندتر از حد معمول"
    elif dbfs < -30:
        score, note = _score_from(dbfs, good=-30, bad=-48), "خیلی آرام — باید بلندتر شود"
    else:
        score, note = 100.0, f"بلندی مناسب ({round(dbfs)} dBFS)"
    axes.append(Axis(LEVEL, score, note))

    return axes


# ------------------------------------------------------------------ verdict


def thresholds() -> dict:
    from django.conf import settings

    conf = settings.UPMARKET_AI
    return {
        "excellent": float(conf.get("AUDIO_QC_EXCELLENT", 88)),
        "good": float(conf.get("AUDIO_QC_GOOD", 75)),
        "review": float(conf.get("AUDIO_QC_REVIEW", 62)),
    }


def combine(axes: list[Axis]) -> float:
    """Weighted mean, capped by the worst axis — same rule as video QC.

    A narration that is loud, clean, well-paced and completely inaudible is not
    an 80. The cap is what keeps one catastrophic axis from being averaged away
    by five good ones.
    """
    if not axes:
        return 0.0
    total = sum(WEIGHTS.get(a.name, 1.0) for a in axes) or 1.0
    mean = sum(a.score * WEIGHTS.get(a.name, 1.0) for a in axes) / total
    worst = min(a.score for a in axes)
    return max(0.0, min(mean, worst + WORST_AXIS_HEADROOM))


def verdict_for(score: float) -> str:
    limits = thresholds()
    if score >= limits["excellent"]:
        return "EXCELLENT"
    if score >= limits["good"]:
        return "GOOD"
    if score >= limits["review"]:
        return "REVIEW"
    return "RESYNTHESIZE"


def check(audio_path, work_dir, *, text: str = "", store=None) -> AudioQCReport:
    """Full report for one narration clip. Never raises.

    The audio already exists and already cost a round trip to the voice engine;
    a QC pass that can throw would turn a cosmetic problem into a failed job.
    """
    from . import lexicon

    report = AudioQCReport()
    report.unresolved = lexicon.unresolved_latin(text, store) if text else []
    try:
        samples, rate = decode(audio_path, work_dir)
    except VideoProcessingError as exc:
        report.error = f"صدا قابل خواندن نبود: {exc}"
        return report
    except Exception as exc:  # noqa: BLE001 — QC must not break the pipeline
        logger.exception("Audio QC could not read %s", audio_path)
        report.error = f"صدا قابل خواندن نبود: {exc}"
        return report

    report.duration = len(samples) / rate if rate else 0.0
    report.axes = measure(samples, rate, text=text)

    levels = _windows(samples, rate)
    floor = silence_floor(levels)
    report.speech_seconds = (
        sum(1 for level in levels if level > floor) * (WINDOW_MS / 1000)
    )
    report.overall = combine(report.axes)
    report.verdict = verdict_for(report.overall)

    weak = [a.name for a in report.axes if a.score < 70]
    report.code_fixable = [name for name in weak if name in CODE_FIXABLE]
    report.needs_resynthesis = [name for name in weak if name not in CODE_FIXABLE]
    return report
