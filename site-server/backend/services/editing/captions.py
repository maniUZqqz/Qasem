"""Auto-captions: speech → words → caption clips on a text track. §23.4 (the CapCut feature)

Three steps, each a plain function so the Celery task and the tests can use them separately:

1. `extract_audio` — the used range of a clip as 16 kHz mono wav (what every recogniser wants).
2. `transcribe_wav` — words with times. The processing node's `voice.asr` first (the GPU PC, when it is online);
   a local faster-whisper only when its model is ALREADY on disk (downloading a model from a Celery thread is how a
   caption button hangs for ten minutes); otherwise a `CaptionsUnavailable` that says what to do.
3. `group_words` + `caption_clips` — cut the word stream into screen-sized lines and turn each into a text clip
   (via `titles.clean`) with per-word times, so the title renderer can highlight the spoken word (karaoke).

**The node's answer is parsed tolerantly.** The recogniser behind `voice.asr` is the PersianAiKit (Vosk) and its JSON has
changed shape before; `words_from_asr` accepts the Vosk shape, Whisper-style `segments[].words`, flat `words`, lists of
partial results and per-segment text without words (spread evenly over the segment — a rough but honest fallback).
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from . import titles
from .errors import TimelineError

logger = logging.getLogger(__name__)

#: Longest range one caption job takes. The node handles long audio, but a ten-minute wait with no progress is
#: not something this panel can show honestly.
MAX_SECONDS = 900

OFFLINE_MESSAGE = (
    "سرور پردازش (رایانهٔ GPU) خاموش است و روی خودِ سایت هم مدلِ تشخیصِ گفتار آماده نیست؛ زیرنویسِ خودکار فعلاً ممکن نیست. "
    "سرور پردازش را روشن کنید و دوباره بزنید، یا اگر ویدیو زیرنویسِ آماده دارد آن را از بخشِ «زیرنویس» وارد کنید."
)


class CaptionsUnavailable(TimelineError):
    """Speech recognition cannot run now. Always says what to do, in Persian."""


# ------------------------------------------------------------------ parsing

_TEXT_KEYS = ("word", "w", "text", "token", "content")
_START_KEYS = ("start", "s", "begin", "from", "start_time", "start_s", "offset")
_END_KEYS = ("end", "e", "stop", "to", "end_time", "end_s")
_CHILD_KEYS = ("words", "result", "segments", "results", "utterances", "chunks", "items")


def _seconds(node: dict, keys) -> float | None:
    for key in keys:
        for name, factor in ((key, 1.0), (key + "_ms", 0.001)):
            if name in node:
                try:
                    value = float(node[name]) * factor
                except (TypeError, ValueError):
                    continue
                if value == value and value >= 0:
                    return value
    return None


def _text_of(node: dict) -> str:
    for key in _TEXT_KEYS:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _walk(node, out: list, depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(node, str):
        text = node.strip()
        if text[:1] in "[{":
            try:
                _walk(json.loads(text), out, depth + 1)
            except ValueError:
                pass
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, out, depth + 1)
        return
    if not isinstance(node, dict):
        return
    for key in _CHILD_KEYS:                       # prefer the finest level present, never count two levels
        children = node.get(key)
        if isinstance(children, list) and children:
            _walk(children, out, depth + 1)
            return
    alternatives = node.get("alternatives")
    if isinstance(alternatives, list) and alternatives:
        _walk(alternatives[0], out, depth + 1)
        return
    text, start, end = _text_of(node), _seconds(node, _START_KEYS), _seconds(node, _END_KEYS)
    if not text or start is None or end is None:
        return
    tokens = text.split()
    if len(tokens) <= 1:
        out.append({"w": text, "s": start, "e": max(end, start)})
        return
    # a stretch of text with one time span: spread the words by character count
    end = max(end, start + 0.1 * len(tokens))
    total = sum(len(t) for t in tokens) or 1
    cursor = start
    for token in tokens:
        span = (end - start) * len(token) / total
        out.append({"w": token, "s": cursor, "e": cursor + span})
        cursor += span


def words_from_asr(data) -> list[dict]:
    """The node's `asr.json` (any known shape) → [{"w","s","e"}] sorted by time, seconds rounded to ms."""
    out: list[dict] = []
    _walk(data, out)
    words = [{"w": w["w"].strip(), "s": round(w["s"], 3), "e": round(max(w["e"], w["s"]), 3)} for w in out if w["w"].strip()]
    words.sort(key=lambda w: (w["s"], w["e"]))
    return words


# ----------------------------------------------------------------- grouping

_SENTENCE_END = re.compile(r"[.!?؟…]+[\"'»)\]]*$")
_SOFT_BREAK = re.compile(r"[,،؛;:]+$")


def group_words(words: list[dict], *, max_chars: int = 32, max_words: int = 7, max_gap: float = 0.7,
                max_dur: float = 4.5) -> list[dict]:
    """Words → screen-sized lines: [{"text","s","e","words"}] (absolute seconds, words keep absolute times)."""
    groups: list[dict] = []
    current: list[dict] = []

    def flush():
        if current:
            groups.append({"text": " ".join(w["w"] for w in current), "s": current[0]["s"], "e": current[-1]["e"],
                           "words": [dict(w) for w in current]})
            current.clear()

    for word in words:
        if current:
            joined = len(" ".join(w["w"] for w in current)) + 1 + len(word["w"])
            prev = current[-1]
            if (word["s"] - prev["e"] > max_gap or len(current) >= max_words or joined > max_chars
                    or word["e"] - current[0]["s"] > max_dur or _SENTENCE_END.search(prev["w"])
                    or (len(current) >= 4 and _SOFT_BREAK.search(prev["w"]))):
                flush()
        current.append(word)
    flush()
    return groups


#: How a caption looks unless the panel's caption style says otherwise.
DEFAULT_STYLE = {
    "font": "vazir", "bold": True, "size": 6.0, "color": "#ffffff", "stroke_color": "#000000", "stroke": 12.0,
    "box": False, "position": "bottom", "hl_color": "#ffd400", "hl_mode": "color", "shadow": 0.0,
}


def caption_clips(groups: list[dict], *, offset: float = 0.0, style: dict | None = None) -> list[dict]:
    """Groups → cleaned text-clip dicts on the timeline (`offset` = where the transcribed range starts there)."""
    merged = {**DEFAULT_STYLE, **{k: v for k, v in (style or {}).items() if v is not None}}
    clips = []
    for i, group in enumerate(groups):
        start = offset + group["s"]
        end = offset + group["e"] + 0.2
        if i + 1 < len(groups):
            nxt = offset + groups[i + 1]["s"]
            if nxt - start >= 0.1:
                end = min(end, nxt)
        end = max(end, start + 0.3)
        words = [{"w": w["w"], "s": round(max(0.0, w["s"] - group["s"]), 3), "e": round(max(0.0, w["e"] - group["s"]), 3)}
                 for w in group["words"]]
        clips.append(titles.clean({**merged, "text": group["text"], "at": round(start, 3), "duration": round(end - start, 3),
                                   "words": words, "caption": True, "label": group["text"][:20]}, i))
    return clips


# ---------------------------------------------------------------- recognising

def extract_audio(src, start: float, end: float, out_wav) -> Path:
    """[start, end] seconds of `src` (video or audio) → 16 kHz mono 16-bit wav."""
    from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run

    length = float(end) - float(start)
    if length <= 0.2:
        raise TimelineError("بازهٔ انتخاب‌شده برای زیرنویس خیلی کوتاه است.")
    if length > MAX_SECONDS:
        raise TimelineError(f"زیرنویسِ خودکار برای بازه‌های تا {MAX_SECONDS // 60} دقیقه است؛ قطعه را کوتاه‌تر کنید.")
    out = Path(out_wav)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run([FFMPEG, "-y", "-ss", f"{max(0.0, float(start)):.3f}", "-t", f"{length:.3f}", "-i", str(src), "-vn", "-ac", "1",
              "-ar", "16000", "-c:a", "pcm_s16le", str(out)])
    except VideoProcessingError as exc:
        raise TimelineError("صدای این قطعه خوانده نشد؛ شاید فایل صدا ندارد.") from exc
    if not out.exists() or out.stat().st_size < 2000:
        raise TimelineError("این قطعه صدا ندارد، پس چیزی برای زیرنویس کردن نیست.")
    return out


def _local_model_cached() -> bool:
    """Is a faster-whisper model already on this machine? (Never download one from a request.)"""
    try:
        from django.conf import settings

        model = (getattr(settings, "UPMARKET_AI", {}) or {}).get("WHISPER_MODEL", "small")
    except Exception:  # noqa: BLE001
        model = "small"
    roots = [os.environ.get("HF_HOME"), os.path.join(os.path.expanduser("~"), ".cache", "huggingface")]
    for root in filter(None, roots):
        hub = Path(root) / "hub"
        if hub.is_dir() and any(hub.glob(f"models--*faster-whisper-{model}*")):
            return True
    return False


def _local_ready() -> bool:
    try:
        from services.audio import transcribe

        ok, _why = transcribe.available()
    except Exception:  # noqa: BLE001
        return False
    return bool(ok and _local_model_cached())


def status() -> dict:
    """What the panel can say BEFORE the user presses the button: {"node": bool, "local": bool, "ok": bool, "message"}."""
    node = False
    try:
        from apps.compute import services as compute

        node = bool(compute.online_nodes("voice"))
    except Exception:  # noqa: BLE001 — compute app unavailable in this process
        node = False
    local = _local_ready()
    return {"node": node, "local": local, "ok": node or local, "message": "" if (node or local) else OFFLINE_MESSAGE}


def _result_words(compute, job) -> list[dict]:
    path = compute.output_path(job, "asr.json")
    if not Path(path).is_file():
        for out in job.outputs():
            if str(out.get("name", "")).lower().endswith(".json"):
                path = compute.output_path(job, out["name"])
                break
    if not Path(path).is_file():
        raise CaptionsUnavailable("سرور پردازش جوابی برنگرداند؛ دوباره تلاش کنید.")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        raise CaptionsUnavailable("جوابِ سرور پردازش خوانده نشد.") from exc
    return words_from_asr(data)


def transcribe_wav(wav, *, store=None, on_tick=None, timeout_s: int = 900) -> dict:
    """wav → {"words": [{"w","s","e"}], "text": str, "engine": "node"|"local"}; raises `CaptionsUnavailable`."""
    wav = Path(wav)
    try:
        from apps.compute import services as compute

        nodes = compute.online_nodes("voice")
    except Exception:  # noqa: BLE001
        compute, nodes = None, []

    if nodes:
        try:
            job = compute.enqueue("voice.asr", {"audio": "audio.wav"}, files={"audio.wav": wav}, store=store,
                                  origin="video-editor-captions", timeout_s=timeout_s)
            job = compute.wait(job, timeout_s, on_tick=on_tick)
        except compute.ComputeUnavailable:
            nodes = []
        except compute.ComputeCancelled as exc:
            raise CaptionsUnavailable("زیرنویسِ خودکار لغو شد.") from exc
        except compute.ComputeTimeout as exc:
            raise CaptionsUnavailable("سرور پردازش در زمانِ مقرر زیرنویس را تمام نکرد؛ بازهٔ کوتاه‌تری را امتحان کنید.") from exc
        except compute.ComputeFailed as exc:
            raise CaptionsUnavailable(f"سرور پردازش نتوانست گفتار را تشخیص بدهد: {exc}") from exc
        else:
            words = _result_words(compute, job)
            if not words:
                raise CaptionsUnavailable("در این بخش گفتاری شنیده نشد.")
            return {"words": words, "text": " ".join(w["w"] for w in words), "engine": "node"}

    if _local_ready():
        from services.audio import transcribe

        try:
            heard = transcribe.transcribe(wav, language="fa")
        except transcribe.TranscriptionUnavailable as exc:
            raise CaptionsUnavailable(str(exc)) from exc
        words = [{"w": w.text, "s": round(w.start, 3), "e": round(w.end, 3)} for seg in heard.segments for w in seg.words]
        if not words:
            raise CaptionsUnavailable("در این بخش گفتاری شنیده نشد.")
        return {"words": words, "text": " ".join(w["w"] for w in words), "engine": "local"}

    raise CaptionsUnavailable(OFFLINE_MESSAGE)
