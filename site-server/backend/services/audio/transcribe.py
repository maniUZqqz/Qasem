"""Speech to text, with per-word timing. §8 — «زیرنویس خودکار».

This is what makes subtitles possible for video the shop filmed themselves, and
word-level timing possible for the video we made.

**It runs locally, and that is not a detail.** The narration engine is external —
edge-tts sends the text to Microsoft, and a `Local Only` shop cannot use it at
all. Whisper is the opposite: the model runs on our own GPU, so the most
privacy-strict shop on the platform can transcribe their own footage. A shop
that cannot generate narration can still subtitle the video they shot.

**Two jobs, and they need different things.**

* *Their* video: we do not know what was said, so every word comes from the
  model — and every word can be wrong. The result carries a per-segment
  confidence so the panel can mark the shaky lines rather than presenting a
  guess in the same typeface as a fact.
* *Our* video: we already know the text exactly. Whisper is used only for
  **timing**, and its transcript is thrown away. Aligning known text to detected
  words is far more reliable than trusting the transcript, because a
  mis-recognised «نایکی» still lands at the right second.

**The model is never guessed at.** If faster-whisper is not installed, or the
model cannot be loaded, this raises with a sentence saying exactly what to
install. Returning an empty transcript would produce a video with no subtitles
and no explanation.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: `small` is the working default for Persian on a GPU box: noticeably better
#: than `base`, and fast enough that a two-minute video is not a coffee break.
#: `large-v3` is materially more accurate and several times slower — worth it
#: for a shop's hero video, not for every upload.
DEFAULT_MODEL = "small"
MODELS = ("tiny", "base", "small", "medium", "large-v3")

#: Below this, Whisper is guessing. Not dropped — shown as uncertain, because a
#: shop looking at their own video can fix a word we got wrong, and cannot fix
#: a line we silently deleted.
LOW_CONFIDENCE = -0.9

#: Persian by default. Letting Whisper auto-detect on a short clip is how a
#: fifteen-second Persian ad comes back transcribed as Arabic.
DEFAULT_LANGUAGE = "fa"


class TranscriptionUnavailable(Exception):
    """The engine is not there. Always says what to install, in Persian."""


@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: float = 1.0


@dataclass
class Segment:
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    #: Whisper's average log-probability. Negative; closer to zero is better.
    confidence: float = 0.0

    @property
    def uncertain(self) -> bool:
        return self.confidence < LOW_CONFIDENCE

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "uncertain": self.uncertain,
            "words": [
                {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
                for w in self.words
            ],
        }


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    language: str = DEFAULT_LANGUAGE
    model: str = DEFAULT_MODEL
    seconds: float = 0.0

    @property
    def words(self) -> list[Word]:
        return [word for segment in self.segments for word in segment.words]

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments).strip()

    @property
    def uncertain_count(self) -> int:
        return sum(1 for s in self.segments if s.uncertain)

    def as_dict(self) -> dict:
        return {
            "language": self.language,
            "model": self.model,
            "seconds": round(self.seconds, 2),
            "segments": [s.as_dict() for s in self.segments],
            "words": len(self.words),
            "uncertain": self.uncertain_count,
            # Said plainly, because a shop reading subtitles of their own video
            # needs to know which lines to check.
            "note": (
                f"{self.uncertain_count} خط با اطمینان پایین تشخیص داده شد و "
                "علامت خورده — قبل از انتشار نگاهشان کنید."
                if self.uncertain_count else ""
            ),
        }


# ------------------------------------------------------------------ engine

_MODEL_CACHE: dict[tuple[str, str], object] = {}


def available() -> tuple[bool, str]:
    """Is transcription possible, and if not, what is missing?"""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, (
            "faster-whisper نصب نیست. برای زیرنویس ویدیوهایی که خودتان "
            "گرفته‌اید لازم است: `pip install faster-whisper`"
        )
    return True, ""


def _load(model: str, device: str):
    """Load once per process and keep it.

    A Whisper model is hundreds of megabytes and takes seconds to load. Loading
    it per video turns a ten-second transcription into a thirty-second one, and
    a worker handling a queue pays that on every single item.
    """
    key = (model, device)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    ok, why = available()
    if not ok:
        raise TranscriptionUnavailable(why)

    from faster_whisper import WhisperModel

    try:
        # int8 on CPU and float16 on GPU: the accuracy difference on speech is
        # not measurable and the speed difference is several times.
        compute = "float16" if device == "cuda" else "int8"
        loaded = WhisperModel(model, device=device, compute_type=compute)
    except Exception as exc:  # noqa: BLE001 — a missing model file, no internet
        raise TranscriptionUnavailable(
            f"مدل «{model}» بارگذاری نشد: {exc}. اولین بار مدل باید دانلود شود، "
            "پس اینترنت لازم است. بعدش آفلاین کار می‌کند."
        ) from exc

    _MODEL_CACHE[key] = loaded
    return loaded


def _device() -> str:
    from django.conf import settings

    chosen = settings.UPMARKET_AI.get("WHISPER_DEVICE", "auto")
    if chosen in ("cpu", "cuda"):
        return chosen
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001 — no torch is a perfectly normal install
        return "cpu"


def transcribe(audio_path, *, language: str | None = None,
               model: str | None = None, hint: str = "") -> Transcript:
    """Audio → words with timings.

    `hint` is Whisper's initial prompt. For our own videos it is the narration
    we wrote, which pulls the model towards the vocabulary that is actually in
    the clip — brand names especially.
    """
    from django.conf import settings

    model = model or settings.UPMARKET_AI.get("WHISPER_MODEL", DEFAULT_MODEL)
    if model not in MODELS:
        raise TranscriptionUnavailable(
            f"مدل «{model}» را نمی‌شناسیم — یکی از این‌ها: {'، '.join(MODELS)}"
        )

    engine = _load(model, _device())
    segments, info = engine.transcribe(
        str(audio_path),
        language=language or DEFAULT_LANGUAGE,
        word_timestamps=True,
        # Whisper hallucinates confidently on silence — it invents a sentence
        # and gives it a timestamp. VAD cuts the silence before it can.
        vad_filter=True,
        initial_prompt=hint[:900] or None,
    )

    out = Transcript(
        language=getattr(info, "language", language or DEFAULT_LANGUAGE),
        model=model,
        seconds=float(getattr(info, "duration", 0.0) or 0.0),
    )
    for segment in segments:
        words = [
            Word(
                text=(w.word or "").strip(),
                start=float(w.start),
                end=float(w.end),
                probability=float(getattr(w, "probability", 1.0)),
            )
            for w in (getattr(segment, "words", None) or [])
            if (w.word or "").strip()
        ]
        out.segments.append(Segment(
            text=(segment.text or "").strip(),
            start=float(segment.start),
            end=float(segment.end),
            words=words,
            confidence=float(getattr(segment, "avg_logprob", 0.0) or 0.0),
        ))
    return out


# ---------------------------------------------------------------- alignment

_TOKEN = re.compile(r"[\w؀-ۿ‌]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def align(known_text: str, transcript: Transcript) -> list[Word]:
    """Put our own words on the model's clock.

    For a video we made, the transcript is the *wrong* thing to show — we know
    the exact text and Whisper does not. But its timing is good. So this matches
    our words against what it heard and carries our spelling with its timings.

    The matching is fuzzy on purpose: Whisper writes «نایکی» as «نایکی» or
    «نای کی» or something else entirely, and a strict match would drop the word
    and everything after it would slide.
    """
    heard = transcript.words
    if not heard:
        return []

    ours = _tokens(known_text)
    if not ours:
        return []

    theirs = [w.text for w in heard]
    matcher = difflib.SequenceMatcher(
        None, [t.lower() for t in ours], [t.lower() for t in theirs],
        autojunk=False,
    )

    out: list[Word] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                spoken = heard[j1 + offset]
                out.append(Word(
                    text=ours[i1 + offset],
                    start=spoken.start,
                    end=spoken.end,
                    probability=spoken.probability,
                ))
            continue

        # Our words that Whisper heard differently (or missed). They still have
        # to appear, at the right place — so the span it heard is divided among
        # them. A word we cannot time exactly is better slightly off than gone.
        window = heard[j1:j2] if j2 > j1 else []
        if not window:
            window = [heard[min(j1, len(heard) - 1)]]
        start, end = window[0].start, window[-1].end
        count = max(1, i2 - i1)
        step = (end - start) / count
        for offset in range(i2 - i1):
            out.append(Word(
                text=ours[i1 + offset],
                start=start + step * offset,
                end=start + step * (offset + 1),
                # Marked down: this is where it was, not where it was heard.
                probability=0.5,
            ))

    out.sort(key=lambda w: w.start)
    return out


def cues_from_words(words: list[Word], *, max_chars: int = 42,
                    max_seconds: float = 6.0) -> list[tuple[float, float, str]]:
    """Words → subtitle lines, broken where a reader needs a break.

    Breaks on three things: length, duration, and a gap between words. The gap
    matters most — a pause is where a sentence ended, and breaking there gives
    lines that match how the sentence was actually spoken.
    """
    if not words:
        return []

    lines: list[tuple[float, float, str]] = []
    current: list[Word] = []

    for word in words:
        if current:
            gap = word.start - current[-1].end
            length = len(" ".join(w.text for w in current)) + 1 + len(word.text)
            span = word.end - current[0].start
            if gap > 0.7 or length > max_chars or span > max_seconds:
                lines.append((
                    current[0].start, current[-1].end,
                    " ".join(w.text for w in current),
                ))
                current = []
        current.append(word)

    if current:
        lines.append((
            current[0].start, current[-1].end, " ".join(w.text for w in current),
        ))
    return lines
