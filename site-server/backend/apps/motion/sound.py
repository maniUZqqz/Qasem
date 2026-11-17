"""صدای ویدیوی موشن: گویندهٔ فارسی با زمانِ هر کلمه، موسیقیِ زمینه با بیت، افکت‌های ساختهٔ خودِ سامانه، مخلوط با ducking و -۱۴ LUFS.

زنجیره (prepare):
  ۱) متنِ گفتارِ هر صحنه (narration یا ساختهٔ خودکار از متنِ صحنه) ⇒ TTS (استودیوی صدا: Piper روی سایت، MOSS روی گره) ⇒ برشِ سکوت‌های دو سرِ کلیپ
  ۲) زمانِ هر کلمه: از خودِ TTS اگر بدهد (Edge) ⇒ وگرنه هم‌ترازیِ اجباری با ASR ِ گره/سایت (captions.transcribe_wav) ⇒ وگرنه برآوردِ نسبتِ حروف
     ⇒ cues[] در هر صحنه؛ متنِ کینتیک و زیرنویس‌ها همان‌جا می‌آیند که کلمه گفته می‌شود
  ۳) مدتِ صحنه‌ها طوری بلند می‌شود که گفتار نبُرد؛ برشِ صحنه‌ها روی نزدیک‌ترین بیتِ موسیقی می‌نشیند (فقط به‌سمتِ بلندتر؛ هرگز گفتار را نمی‌بُرد)
  ۴) مخلوط: گوینده + افکت + موسیقی (کم‌شونده زیرِ گوینده با sidechain) ⇒ loudnorm دو‌گذره روی -۱۴ LUFS و سقفِ -۱٫۵ dBTP ⇒ mix.m4a
  ۵) mux: ویدیوی بی‌صدای رندر + mix.m4a ⇒ MP4 با صدا (روی گره یا روی سایت)

هیچ‌چیزِ این فایل شبکه نمی‌خواهد مگر انتخابِ صدای Edge/ASR ِ گره که اختیاری‌اند؛ بی‌گره و بی‌اینترنت Piper + برآورد + موسیقیِ آغازینِ سامانه کار می‌کند.
"""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

from . import specs, timeline

logger = logging.getLogger(__name__)

LEAD = 0.25                  # گفتارِ هر صحنه این‌قدر بعد از شروعِ صحنه شروع می‌شود (ورودِ عناصر)
TAIL = 0.45                  # و این‌قدر پیش از پایانِ صحنه تمام می‌شود
LUFS = -14.0
TRUE_PEAK = -1.5
SR = 48000
BEAT_TOLERANCE = 0.65        # حداکثرِ جابه‌جاییِ برش برای نشستن روی بیت (ثانیه)
SPEAKING_CPS = 13.0


class SoundError(Exception):
    """خطای قابلِ‌نمایشِ فارسی."""


class AudioPending(SoundError):
    """صدا هنوز روی سرورِ پردازش ساخته نشده؛ رندر منتظر می‌ماند و خودکار ادامه می‌یابد."""


def _ffmpeg() -> str:
    try:
        from services.video.ffmpeg import FFMPEG

        return str(FFMPEG)
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg") or "ffmpeg"


def _ff(args: list, timeout: int = 300) -> subprocess.CompletedProcess:
    p = subprocess.run([_ffmpeg(), "-hide_banner", "-y", *map(str, args)], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise SoundError("ffmpeg ناموفق بود: " + (p.stderr or "")[-300:])
    return p


def _ffprobe() -> str:
    sib = Path(_ffmpeg()).with_name("ffprobe")
    return str(sib) if sib.is_file() else (shutil.which("ffprobe") or "ffprobe")


def duration_of(path) -> float:
    p = subprocess.run([_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
    try:
        return float(p.stdout.strip() or 0)
    except ValueError:
        return 0.0


# ───────────────────────────────────────────── متنِ گفتار

def _join_fa(parts: list) -> str:
    parts = [p.strip().rstrip(".،!؟") for p in parts if p and p.strip()]
    return "، ".join(parts)


def auto_narration(sc: dict) -> str:
    """وقتی کاربر گفتار ننوشته: از متنِ خودِ صحنه یک جملهٔ خواندنی (فقط همان کلمه‌ها؛ هیچ چیزِ تازه‌ای اضافه نمی‌شود)."""
    t = sc.get("type")
    g = lambda k: str(sc.get(k) or "").strip()  # noqa: E731
    lst = lambda k: [str(x).strip() for x in (sc.get(k) or []) if isinstance(x, str)]  # noqa: E731
    objs = lambda k, f: [str(x.get(f) or "").strip() for x in (sc.get(k) or []) if isinstance(x, dict)]  # noqa: E731
    if t in ("title", "kinetic_title", "logo", "image_hero"):
        return _join_fa([g("kicker"), g("title") or g("text") or g("caption"), g("subtitle") or g("tagline")]) + "."
    if t in ("list", "checklist"):
        return _join_fa([g("title")]) + ". " + _join_fa(lst("items")) + "."
    if t == "quote" or t == "testimonial":
        return _join_fa([g("text") or g("quote")]) + "."
    if t == "stat":
        return _join_fa([g("kicker"), f"{g('prefix')}{g('value')}{g('suffix')} {g('label')}".strip()]) + "."
    if t == "counter":
        return _join_fa([g("kicker")] + [f"{x.get('value', '')} {x.get('unit', '')} {x.get('label', '')}".strip() for x in (sc.get("items") or []) if isinstance(x, dict)]) + "."
    if t in ("bar_chart", "line_chart", "donut", "progress_bars", "icon_grid"):
        key = {"bar_chart": "bars", "line_chart": "points", "donut": "slices", "progress_bars": "items", "icon_grid": "items"}[t]
        return _join_fa([g("title")] + objs(key, "label")) + "."
    if t in ("steps",):
        return _join_fa([g("title")] + objs("steps", "title")) + "."
    if t == "feature_cards":
        return _join_fa([g("title")] + objs("cards", "title")) + "."
    if t == "product":
        return _join_fa([g("name"), g("price")] + lst("features")) + "."
    if t == "price_card":
        return _join_fa([g("name"), f"{g('price')} {g('unit')}".strip()] + lst("features")) + "."
    if t == "compare" or t == "before_after":
        return _join_fa([g("title"), g("before"), g("after")]) + "."
    if t == "cta" or t == "social_cta":
        return _join_fa([g("title"), g("note")]) + "."
    if t == "app":
        return _join_fa([g("caption")] + lst("bullets")) + "."
    if t == "tags":
        return _join_fa([g("title")] + lst("tags")) + "."
    return _join_fa([g("title") or g("text") or g("label") or g("name")]) + "."


def narration_texts(spec: dict) -> list:
    voice = (spec.get("audio") or {}).get("voice")
    out = []
    for sc in spec["scenes"]:
        t = (sc.get("narration") or "").strip()
        if not t and voice:
            t = auto_narration(sc)
        out.append(t if len(t) > 2 else "")
    return out


# ───────────────────────────────────────────── گفتار: ساخت، برش، زمانِ کلمه‌ها

def _online_voice_blocked(store, voice_id: str) -> bool:
    """صدای Edge متن را به مایکروسافت می‌فرستد: روی فروشگاهی که سیاستِ دادهاش «فقط لوکال» است (یا سیاست خوانده نشد) ممنوع است.
    (فهرستِ صداها هم همین را «در دسترس نیست» می‌کند؛ این‌جا همان قاعده روی خودِ ساخت اعمال می‌شود، حتی اگر شناسهٔ صدا دستی در JSON نوشته شده باشد.)"""
    if not str(voice_id or "").startswith("edge:"):
        return False
    from services.audio import engines

    return bool(engines.local_only(store))


def auto_voice(store, *, local_only: bool = False) -> str:
    """بهترین صدای در دسترس (صدای سایت زودتر)؛ local_only ⇒ هیچ صدای آنلاینی؛ نبود ⇒ AudioPending (گره روشن شود) یا SoundError."""
    from services.audio import studio

    usable = [v for v in studio.voices(store) if v.get("available") and not (local_only and str(v.get("id", "")).startswith("edge:"))]
    usable.sort(key=lambda v: (v.get("where") != "site", v.get("name", "")))       # صدای سایت در یکی دو ثانیه جواب می‌دهد
    if not usable:
        from services.editing import captions

        if captions.node_registered("voice"):
            raise AudioPending("گویندهٔ فارسی روی سرورِ پردازش ساخته می‌شود؛ با روشن‌شدنش خودکار ادامه می‌یابد.")
        raise SoundError("هیچ صدای گوینده‌ای در دسترس نیست (Piper روی سایت نصب نیست و سرورِ پردازش هم خاموش است).")
    return usable[0]["id"]


POLICY_NOTE = "سیاستِ دادهٔ این فروشگاه «فقط لوکال» است و صدای آنلاینِ Edge متن را به مایکروسافت می‌فرستد؛ به‌جایش صدای محلی به‌کار رفت."


def default_synth(store, user, text: str, voice_id: str, workdir: Path, name: str, *, wait_s: float = 150.0) -> dict:
    """از استودیوی صدای فروشگاه (Piper روی سایت؛ MOSS روی گره). ⇒ {path, engine, voice, cues?, note?}

    سیاستِ داده: صدای آنلاینِ Edge روی فروشگاهِ «فقط لوکال» هرگز صدا زده نمی‌شود (متن از سایت بیرون نمی‌رود)؛ به‌جایش صدای محلی می‌آید و در گزارش می‌نویسد."""
    import time

    from apps.ai.models import AudioAsset
    from services.audio import node_audio, studio

    note = ""
    blocked = _online_voice_blocked(store, voice_id)
    if blocked:
        logger.info("motion: edge voice %s refused by the store's data policy; using a local voice", voice_id)
        voice_id, note = "auto", POLICY_NOTE
    if not voice_id or voice_id == "auto":
        voice_id = auto_voice(store, local_only=blocked)
    if voice_id.startswith("edge:"):
        got = _edge_with_cues(voice_id.split(":", 1)[1], text, workdir / f"{name}.mp3", store=store)
        if got:
            return {"path": got["path"], "engine": "edge", "voice": voice_id, "cues": got["cues"]}
    try:
        asset = studio.create_speech(store, user, text=text, voice_id=voice_id, title="موشن — گویندگی")
    except (studio.StudioError, node_audio.NodeAudioError) as exc:
        raise SoundError(str(exc)) from exc
    end = time.monotonic() + wait_s
    while asset.status in (AudioAsset.Status.PENDING, AudioAsset.Status.RUNNING) and time.monotonic() < end:
        time.sleep(2.0)
        asset = studio.sync(AudioAsset.objects.get(pk=asset.pk))
    if asset.status in (AudioAsset.Status.PENDING, AudioAsset.Status.RUNNING):
        raise AudioPending("گویندهٔ فارسی هنوز روی سرورِ پردازش ساخته نشده؛ رندر منتظر می‌ماند.")
    if asset.status != AudioAsset.Status.READY:
        raise SoundError(asset.error or "ساختنِ گفتار ناموفق بود.")
    path = studio.asset_path(asset)
    if not path:
        raise SoundError("فایلِ گفتار پیدا نشد.")
    out = {"path": Path(path), "engine": asset.engine, "voice": voice_id, "asset": asset.pk}
    if note:
        out["note"] = note
    return out


def _edge_with_cues(voice: str, text: str, out: Path, store=None) -> dict | None:
    """Edge TTS رویدادِ WordBoundary می‌دهد (زمانِ دقیقِ کلمه‌ها)؛ بی‌اینترنت/نصب‌نبودن ⇒ None و مسیرِ عادی."""
    try:
        import asyncio

        import edge_tts
    except Exception:  # noqa: BLE001
        return None
    # the Persian pronunciation layer. The cues carry the words Edge heard (the spoken text), the captions are matched to the
    # words that were WRITTEN: when the layer changes the number of words (a price or a time spelled out) the cues are
    # regrouped onto the written words afterwards (``regroup_cues``), so numbers are normalised here too.
    written = text
    try:
        from services.audio import pronounce

        text = pronounce.text_for(written, "edge", store=store) or written
    except Exception:  # noqa: BLE001
        text = written

    async def go():
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary") if "boundary" in edge_tts.Communicate.__init__.__code__.co_varnames else edge_tts.Communicate(text, voice)
        words, audio = [], bytearray()
        async for ch in comm.stream():
            if ch["type"] == "audio":
                audio.extend(ch["data"])
            elif ch["type"] == "WordBoundary":
                s = ch["offset"] / 1e7
                words.append({"w": ch["text"], "s": round(s, 3), "e": round(s + ch["duration"] / 1e7, 3)})
        return bytes(audio), words

    try:
        audio, words = asyncio.run(asyncio.wait_for(go(), 40))
    except Exception as exc:  # noqa: BLE001
        logger.info("edge word boundaries unavailable: %s", exc)
        return None
    if not audio or len(words) < 2:
        return None
    if text != written:
        words = regroup_cues(words, written, text, store=store)
    out.write_bytes(audio)
    return {"path": out, "cues": words}


def regroup_cues(cues: list, written: str, spoken: str, *, store=None) -> list:
    """Word times of the SPOKEN text -> word times of the WRITTEN text (one cue per written word).

    «ساعت ۱۴:۳۰» is spoken as five words and written as two: the cues of the spoken words that come from one written word are
    merged (first start, last end). How many spoken words a written word becomes is counted by normalising it alone; when the
    counts do not add up to the cues Edge gave, the written words share the cues in proportion, so every written word still
    gets a time and the captions stay in step with the audio."""
    orig = written.split()
    if not orig or not cues:
        return cues
    counts = []
    try:
        from services.audio import pronounce

        for w in orig:
            counts.append(max(1, len((pronounce.text_for(w, "edge", store=store) or w).split())))
    except Exception:  # noqa: BLE001
        counts = [1] * len(orig)
    n, total = len(cues), sum(counts)
    out, at = [], 0
    for i, w in enumerate(orig):
        if total == n:
            a, b = at, at + counts[i]
            at = b
        else:                                   # proportional share (also when Edge gave fewer cues than written words)
            a = min(n - 1, (i * n) // len(orig))
            b = max(a + 1, min(n, ((i + 1) * n) // len(orig)))
        group = cues[a:b] or [cues[min(n - 1, a)]]
        out.append({"w": w.strip(".،!؟?,;؛:") or w, "s": group[0]["s"], "e": group[-1]["e"]})
    return out


def speech_bounds(path) -> tuple:
    """(شروع, پایان) ثانیهٔ گفتارِ واقعی در کلیپ (silencedetect)."""
    total = duration_of(path)
    p = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-42dB:d=0.10", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", p.stderr)]
    s, e = 0.0, total
    if starts and starts[0] <= 0.05 and ends:
        s = max(0.0, ends[0] - 0.04)
    if starts and (len(starts) > len(ends) or (ends and ends[-1] >= total - 0.05)):
        e = min(total, starts[-1] + 0.06)
    if e - s < 0.2:
        s, e = 0.0, total
    return round(s, 3), round(e, 3)


def cut_clip(src, dest, start: float, end: float) -> Path:
    """بریدنِ گفتار به [start,end] و تبدیل به wav ِ ۴۸کیلوهرتزِ استریو."""
    _ff(["-i", src, "-ss", f"{start:.3f}", "-t", f"{max(0.1, end - start):.3f}", "-ar", SR, "-ac", 2, "-c:a", "pcm_s16le", dest])
    return Path(dest)


def inner_pauses(path, *, min_len: float = 0.12) -> list:
    """The real pauses INSIDE a speech clip [(start, end)] (silencedetect; the leading and trailing silence are not pauses): where the voice
    actually stops for a comma or a full stop - the anchors that make a no-ASR word-time estimate follow the recording instead of only the text."""
    total = duration_of(path)
    p = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise=-38dB:d={min_len}", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", p.stderr)]
    out = []
    for i, st in enumerate(starts):
        en = ends[i] if i < len(ends) else total
        if st <= 0.05 or en >= total - 0.05:                     # edges of the clip
            continue
        out.append((round(max(0.0, st), 3), round(en, 3)))
    return out


_BREAK_END = re.compile(r"[.!؟?]$")
_BREAK_SOFT = re.compile(r"[،,;؛:]$")


def estimate_cues(text: str, seconds: float, pauses: list | None = None) -> list:
    """Word times without ASR. The weight of a word = its letters (+ a pause after punctuation); the clip is shared out in that proportion.
    With `pauses` (the real silences of the recording, `inner_pauses`) the words are shared out PER PHRASE: a phrase ends where the voice really
    stopped, so a long sentence cannot drift away from the audio. Fewer detected pauses than punctuation marks => the strongest marks
    (full stops before commas) are matched to them in order; more => only the longest are kept."""
    words = [w for w in text.split() if re.search(r"\w", w)]
    if not words:
        return []
    weights, strength = [], []
    for w in words:
        n = len(re.sub(r"[^\w]", "", w)) + 1.5
        st = 2 if _BREAK_END.search(w) else 1 if _BREAK_SOFT.search(w) else 0
        n += {2: 6, 1: 3}.get(st, 0)
        weights.append(n)
        strength.append(st)
    if pauses:
        cand = [i for i, st in enumerate(strength[:-1]) if st]            # a break after the last word is the end of the clip, not a pause
        if cand:
            keep = sorted(sorted(cand, key=lambda i: (-strength[i], i))[: len(pauses)])
            pz = sorted(sorted(pauses, key=lambda x: -(x[1] - x[0]))[: len(keep)])
            spans, first, lo = [], 0, 0.0
            for i, (ps, pe) in zip(keep, pz):
                spans.append((first, i + 1, lo, max(lo + 0.05, ps)))
                first, lo = i + 1, pe
            spans.append((first, len(words), lo, max(lo + 0.05, seconds)))
            out = []
            for a, b, t0, t1 in spans:
                core = [len(re.sub(r"[^\w]", "", words[k])) + 1.5 for k in range(a, b)]
                tot, at = sum(core), t0
                for k, wt in zip(range(a, b), core):
                    d = (t1 - t0) * wt / tot
                    clean = words[k].strip(".،!؟?,;؛:")
                    out.append({"w": clean or words[k], "s": round(at, 3), "e": round(at + d * 0.92, 3)})
                    at += d
            return out
    tot = sum(weights)
    out, at = [], 0.0
    for w, wt in zip(words, weights):
        d = seconds * wt / tot
        clean = w.strip(".،!؟?,;؛:")
        out.append({"w": clean or w, "s": round(at, 3), "e": round(at + d * 0.92, 3)})
        at += d
    return out


def align_asr(text: str, heard: list) -> list:
    """زمانِ کلماتِ خودمان روی ساعتِ ASR (transcribe.align)؛ ⇒ cues"""
    from services.audio import transcribe as T

    words = [T.Word(text=h["w"], start=float(h["s"]), end=float(h["e"])) for h in heard]
    seg = T.Segment(text=" ".join(h["w"] for h in heard), start=words[0].start, end=words[-1].end, words=words)
    got = T.align(text, T.Transcript(segments=[seg]))
    return [{"w": w.text, "s": round(w.start, 3), "e": round(w.end, 3)} for w in got]


def word_cues(text: str, clip: Path, seconds: float, *, store=None, asr=None, given=None) -> tuple:
    """⇒ (cues نسبت به شروعِ کلیپ، منبع: «tts» | «asr» | «estimate»)."""
    if given:
        return given, "tts"
    fn = asr
    if fn is None:
        def fn(path):  # noqa: E306
            from services.editing import captions

            return captions.transcribe_wav(path, store=store, timeout_s=90)["words"]
    try:
        heard = fn(clip)
        if heard and len(heard) >= max(2, int(len(text.split()) * 0.5)):
            cues = align_asr(text, heard)
            if cues:
                return cues, "asr"
    except Exception as exc:  # noqa: BLE001 — گره خاموش/ASR نیست ⇒ برآورد (ادامه می‌دهیم)
        logger.info("motion: ASR alignment unavailable (%s) - estimating word times", exc)
    try:                                                       # no ASR: still anchor the phrases on the pauses the recording really has
        pauses = inner_pauses(clip)
    except Exception:  # noqa: BLE001
        pauses = []
    return estimate_cues(text, seconds, pauses or None), "estimate"


# ───────────────────────────────────────────── بیت‌ها و برشِ روی بیت

def music_beats(path) -> dict:
    """{"beats":[ثانیه], "bpm"}؛ با media_cache (نتیجه روی دیسک می‌ماند). شکست ⇒ بیت‌های خالی."""
    try:
        from services.editing import media_cache

        b = media_cache.beats(Path(path))
        return {"beats": [float(x) for x in b.get("beats") or []], "bpm": b.get("bpm"), "duration": b.get("duration")}
    except Exception as exc:  # noqa: BLE001
        logger.info("motion: no beats (%s)", exc)
        return {"beats": [], "bpm": None}


def regular_beats(beats: list, bpm: float | None, length: float) -> list:
    """بیت‌های تشخیص‌داده‌شده + شبکهٔ منظمِ همان تمپو (برای جاهایی که onset نبود) تا همیشه نزدیک‌ترین بیت وجود داشته باشد."""
    if not bpm or bpm < 40 or bpm > 220:
        return sorted(beats)
    step = 60.0 / bpm
    first = beats[0] if beats else 0.0
    grid = [first + k * step for k in range(int(length / step) + 2)]
    return sorted(set(round(x, 3) for x in (list(beats) + grid)))


def snap_durations(spec: dict, beats: list, minimum: list) -> list:
    """مدتِ هر صحنه طوری که لحظهٔ برش (وسطِ گذار) روی بیت بنشیند. فقط به‌سمتِ بلندتر (حداقل = minimum[i] برای نبُریدنِ گفتار) و تا BEAT_TOLERANCE."""
    if not beats:
        return [float(s["duration"]) for s in spec["scenes"]]
    fps = spec.get("fps") or 30
    _, trans_frames = timeline.style_trans(spec["style"])
    out, start = [], 0.0
    n = len(spec["scenes"])
    for i, sc in enumerate(spec["scenes"]):
        dur = max(float(sc["duration"]), minimum[i])
        if i == n - 1:
            out.append(dur)
            break
        tf = 0.0 if (sc.get("transition") or spec.get("transition")) == "cut" else min(trans_frames / fps, dur * 0.45)
        cut = start + dur - tf / 2                       # لحظهٔ برشِ دیداری
        cands = [b for b in beats if cut - 0.12 <= b <= cut + BEAT_TOLERANCE]
        if cands:
            b = min(cands, key=lambda x: abs(x - cut))
            new = max(minimum[i], b + tf / 2 - start)
            if new - dur <= BEAT_TOLERANCE + 0.2:
                dur = new
        dur = round(min(specs.MAX_SCENE_S, dur) * fps) / fps
        out.append(dur)
        start += dur - tf
    return out


# ───────────────────────────────────────────── افکتِ صوتیِ ساختهٔ خودِ سامانه (numpy؛ بدونِ هیچ نمونهٔ بیرونی)

def synth_sfx(kind: str, path: Path, level_db: float = -14.0) -> Path:
    import numpy as np

    sr = SR
    rng = np.random.default_rng({"whoosh": 1, "pop": 2, "tick": 3, "hit": 4, "rise": 5}.get(kind, 0))

    def env(n, a, d):
        t = np.arange(n) / sr
        return np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-t / d)

    if kind == "pop":
        n = int(sr * 0.22)
        t = np.arange(n) / sr
        x = np.sin(2 * np.pi * (700 * np.exp(-t * 14) + 220) * t) * env(n, 0.002, 0.05)
    elif kind == "tick":
        n = int(sr * 0.06)
        t = np.arange(n) / sr
        x = np.sin(2 * np.pi * 2300 * t) * env(n, 0.0005, 0.012)
    elif kind == "hit":
        n = int(sr * 0.55)
        t = np.arange(n) / sr
        x = np.sin(2 * np.pi * (95 * np.exp(-t * 5) + 45) * t) * env(n, 0.002, 0.16) + rng.normal(0, 0.25, n) * env(n, 0.0005, 0.03)
    elif kind == "rise":
        n = int(sr * 1.1)
        t = np.arange(n) / sr
        x = np.sin(2 * np.pi * (300 + 1400 * (t / t[-1]) ** 2) * t) * (t / t[-1]) ** 1.5 * 0.6 + rng.normal(0, 0.1, n) * (t / t[-1])
    else:  # whoosh: نویزِ فیلترشده با اوجِ وسط
        n = int(sr * 0.55)
        noise = rng.normal(0, 1, n)
        k = 40
        sm = np.convolve(noise, np.ones(k) / k, mode="same")
        t = np.linspace(0, 1, n)
        x = sm * np.sin(np.pi * t) ** 1.6 * 2.2
    x = x / (np.max(np.abs(x)) + 1e-9) * (10 ** (level_db / 20))
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())
    return Path(path)


def sfx_events(spec: dict, starts: list) -> list:
    """[(ثانیه, نوع, dB)] — افکت‌های نوشته‌شدهٔ صحنه‌ها + whoosh ِ خودکار روی هر گذار (اگر audio.sfx روشن باشد)."""
    ev = []
    for i, sc in enumerate(spec["scenes"]):
        for e in sc.get("sfx") or []:
            ev.append((starts[i] + float(e["at"]), e["kind"], float(e.get("level_db", -14))))
    if (spec.get("audio") or {}).get("sfx"):
        t = timeline.seconds(spec)
        for j in range(len(spec["scenes"]) - 1):
            if t["kinds"][j] != "cut" and t["tfs"][j] > 0:
                ev.append((t["starts"][j + 1] + t["tfs"][j] * 0.1, "whoosh", -22.0))
    return sorted(ev)


# ───────────────────────────────────────────── موسیقی

def pick_music(store, ref: str, seconds: float, mood: str = "calm"):
    """⇒ (مسیرِ فایل, {ref,title,license,bpm}) یا (None, {})."""
    from apps.ai.models import AudioAsset
    from services.audio import starter_music, studio

    if ref and ref != "auto":
        a = AudioAsset.objects.filter(pk=int(ref.split(":")[1]), store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY).first()
        rows = [a] if a else []
    else:
        starter_music.ensure_for_store(store, upgrade_on_node=False)
        rows = list(AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY).order_by("-saved", "-created_at")[:30])
        rows.sort(key=lambda r: (0 if (r.params or {}).get("mood") == mood else 1, abs(float(r.duration or 0) - seconds)))
    for a in rows:
        p = studio.asset_path(a)
        if p and Path(p).is_file():
            return Path(p), {"ref": f"audio:{a.pk}", "title": a.title, "license": a.license, "bpm": (a.params or {}).get("bpm")}
    return None, {}


# ───────────────────────────────────────────── مخلوط و مسترینگ

def _place_filter(inputs: list) -> tuple:
    """inputs = [(index, delay_s)] ⇒ (زنجیرهٔ adelay, برچسب‌ها)."""
    chains, labels = [], []
    for k, (idx, delay) in enumerate(inputs):
        ms = max(0, int(round(delay * 1000)))
        chains.append(f"[{idx}:a]aresample={SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[p{k}]")
        labels.append(f"[p{k}]")
    return chains, labels


def build_mix(workdir: Path, total: float, voice_parts: list, sfx_parts: list, music: dict | None, out: Path) -> dict:
    """voice_parts/sfx_parts = [(path, start_s)]; music = {path, level_db}. ⇒ {lufs, true_peak, seconds}."""
    inputs: list = []
    chains: list = []
    voice_labels, sfx_labels = [], []
    idx = 0
    for path, at in voice_parts:
        inputs += ["-i", path]
        c, l = _place_filter([(idx, at)])
        chains += [c[0].replace("[p0]", f"[v{idx}]")]
        voice_labels.append(f"[v{idx}]")
        idx += 1
    for path, at in sfx_parts:
        inputs += ["-i", path]
        c, l = _place_filter([(idx, at)])
        chains += [c[0].replace("[p0]", f"[s{idx}]")]
        sfx_labels.append(f"[s{idx}]")
        idx += 1
    mus_idx = None
    if music:
        inputs += ["-i", str(music["path"])]
        mus_idx = idx
        idx += 1
    if not (voice_labels or sfx_labels or music):
        raise SoundError("هیچ صدایی برای ترکیب نیست.")
    mix_in = []
    if voice_labels:
        chains.append(("".join(voice_labels) + f"amix=inputs={len(voice_labels)}:normalize=0:duration=longest,apad=whole_dur={total:.3f}[voice]") if len(voice_labels) > 1
                      else f"{voice_labels[0]}apad=whole_dur={total:.3f}[voice]")
    if sfx_labels:
        chains.append(("".join(sfx_labels) + f"amix=inputs={len(sfx_labels)}:normalize=0:duration=longest,apad=whole_dur={total:.3f}[sfx]") if len(sfx_labels) > 1
                      else f"{sfx_labels[0]}apad=whole_dur={total:.3f}[sfx]")
    if music:
        mdur = max(0.5, float(music.get("seconds") or duration_of(music["path"])))
        loop = "aloop=loop=-1:size=2147483647," if mdur < total else ""
        db = float(music.get("level_db", -22))
        chains.append(f"[{mus_idx}:a]aresample={SR},aformat=channel_layouts=stereo,{loop}atrim=0:{total:.3f},asetpts=N/SR/TB,"
                      f"afade=t=in:st=0:d=0.8,afade=t=out:st={max(0.0, total - 1.6):.3f}:d=1.6,volume={db:.1f}dB[mus]")
        if voice_labels:
            chains.append("[voice]asplit=2[vmix][vkey]")
            chains.append("[mus][vkey]sidechaincompress=threshold=0.02:ratio=9:attack=15:release=450:makeup=1[mduck]")
            mix_in += ["[vmix]", "[mduck]"]
        else:
            mix_in.append("[mus]")
    elif voice_labels:
        mix_in.append("[voice]")
    if sfx_labels:
        mix_in.append("[sfx]")
    chains.append("".join(mix_in) + f"amix=inputs={len(mix_in)}:normalize=0:duration=longest,atrim=0:{total:.3f}[premix]" if len(mix_in) > 1 else f"{mix_in[0]}atrim=0:{total:.3f}[premix]")
    graph = ";".join(chains)
    # گذارِ ۱: اندازه‌گیری
    p = subprocess.run([_ffmpeg(), "-hide_banner", "-y", *inputs, "-filter_complex", graph + f";[premix]loudnorm=I={LUFS}:TP={TRUE_PEAK}:LRA=11:print_format=json[o]",
                        "-map", "[o]", "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr or "", re.S)
    if p.returncode != 0 or not m:
        raise SoundError("اندازه‌گیریِ بلندیِ صدا ناموفق بود: " + (p.stderr or "")[-250:])
    st = json.loads(m.group(0))
    norm = (f"loudnorm=I={LUFS}:TP={TRUE_PEAK}:LRA=11:measured_I={st['input_i']}:measured_TP={st['input_tp']}:measured_LRA={st['input_lra']}"
            f":measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true:print_format=summary")
    out.parent.mkdir(parents=True, exist_ok=True)
    _ff([*inputs, "-filter_complex", graph + f";[premix]{norm},alimiter=limit=0.89:level=false[o]", "-map", "[o]", "-ar", SR, "-ac", 2, "-c:a", "aac", "-b:a", "192k", out], timeout=900)
    # اندازه‌گیریِ نهایی (گواه)
    q = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(out), "-af", "loudnorm=I=-14:print_format=json", "-f", "null", "-"], capture_output=True, text=True, timeout=300)
    mm = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", q.stderr or "", re.S)
    final = json.loads(mm.group(0)) if mm else {}
    return {"lufs": float(final.get("input_i", st["input_i"])), "true_peak": float(final.get("input_tp", st["input_tp"])), "seconds": duration_of(out), "target": LUFS}


def mux(video: Path, audio: Path, out: Path) -> Path:
    """ویدیوی بی‌صدا + mix ⇒ MP4 با صدا (ویدیو کپی می‌شود، صدا AAC)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    _ff(["-i", video, "-i", audio, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy" if str(audio).endswith((".m4a", ".aac")) else "aac", "-b:a", "192k",
         "-shortest", "-movflags", "+faststart", out], timeout=600)
    return out


def has_audio(path) -> bool:
    p = subprocess.run([_ffprobe(), "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, timeout=60)
    return bool(p.stdout.strip())


# ───────────────────────────────────────────── همه با هم

def wanted(spec: dict) -> bool:
    a = spec.get("audio") or {}
    return bool(a.get("voice") or a.get("music") or a.get("sfx") or any(s.get("narration") or s.get("sfx") for s in spec["scenes"]))


def prepare(store, user, spec: dict, workdir: Path, *, synth=None, asr=None, beats_fn=None, music_fn=None, progress=None) -> dict:
    """⇒ {spec (مدت‌ها و cues به‌روز)، mix (مسیر mix.m4a)، info}. هیچ‌چیز روی spec ورودی تغییر نمی‌کند."""
    import copy

    spec = copy.deepcopy(spec)
    say = progress or (lambda p, m: None)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    audio = spec.get("audio") or {}
    info: dict = {"voice": None, "music": None, "sfx": bool(audio.get("sfx")), "target_lufs": LUFS}
    texts = narration_texts(spec)
    clips: dict = {}
    voice_cfg = audio.get("voice") or ({"voice_id": "auto"} if any(texts) else None)
    # ── ۱) گفتار
    if voice_cfg and any(texts):
        synth = synth or (lambda text, vid, name: default_synth(store, user, text, vid, workdir, name))
        sources, engines = [], set()
        for i, text in enumerate(texts):
            if not text:
                continue
            say(0.1 + 0.4 * i / max(1, len(texts)), f"ساختِ گفتارِ صحنهٔ {i + 1}")
            got = synth(text, voice_cfg.get("voice_id", "auto"), f"nar{i}")
            raw = Path(got["path"])
            s0, s1 = speech_bounds(raw)
            clip = cut_clip(raw, workdir / f"clip{i}.wav", max(0.0, s0 - 0.04), s1 + 0.08)
            secs = duration_of(clip)
            given = None
            if got.get("cues"):                       # زمانِ کلمه‌ها از خودِ TTS (نسبت به شروعِ فایلِ خام) ⇒ نسبت به کلیپِ بریده
                off = max(0.0, s0 - 0.04)
                given = [{"w": c["w"], "s": round(max(0.0, c["s"] - off), 3), "e": round(max(0.0, c["e"] - off), 3)} for c in got["cues"]]
            cues, src = word_cues(text, clip, secs, store=store, asr=asr, given=given)
            clips[i] = {"path": clip, "seconds": secs, "cues": cues}
            sources.append(src)
            engines.add(got.get("engine", ""))
            info["voice"] = {"engine": ",".join(sorted(e for e in engines if e)), "voice": got.get("voice", ""), "scenes": len(clips)}
            if got.get("note"):
                info["voice"]["note"] = got["note"]
                info["voice"]["requested"] = voice_cfg.get("voice_id", "")
        if sources:
            info["voice"]["cue_source"] = sources[0] if len(set(sources)) == 1 else "mixed"
    # ── ۲) موسیقی و بیت
    music_path, music_meta, beats = None, {}, []
    if audio.get("music"):
        say(0.55, "انتخابِ موسیقی و تشخیصِ بیت")
        rough = timeline.total_seconds(spec)
        mp, mm = (music_fn or (lambda ref, secs: pick_music(store, ref, secs)))(audio["music"].get("ref", "auto"), rough)
        if mp:
            music_path, music_meta = Path(mp), dict(mm)
            b = (beats_fn or music_beats)(music_path)
            beats = regular_beats(b.get("beats") or [], b.get("bpm"), rough + 30)
            music_meta.update({"bpm": b.get("bpm"), "beats": len(b.get("beats") or [])})
            info["music"] = music_meta
        else:
            info["music_note"] = "موسیقی‌ای در کتابخانهٔ فروشگاه پیدا نشد."
    # ── ۳) مدت‌ها: گفتار نبُرد؛ برش روی بیت
    minimum = []
    for i, sc in enumerate(spec["scenes"]):
        need = LEAD + clips[i]["seconds"] + TAIL if i in clips else 0.0
        minimum.append(max(specs.MIN_SCENE_S, need))
    durations = [max(float(sc["duration"]), minimum[i]) for i, sc in enumerate(spec["scenes"])]
    if beats and audio.get("beat_sync", True) and len(spec["scenes"]) > 1:
        tmp = dict(spec, scenes=[dict(sc, duration=d) for sc, d in zip(spec["scenes"], durations)])
        durations = snap_durations(tmp, beats, minimum)
        info["beat_sync"] = True
    for sc, d in zip(spec["scenes"], durations):
        sc["duration"] = round(min(specs.MAX_SCENE_S, d), 3)
    t = timeline.seconds(spec)
    for i, c in clips.items():
        spec["scenes"][i]["cues"] = [{"w": x["w"], "s": round(LEAD + x["s"], 3), "e": round(LEAD + x["e"], 3)} for x in c["cues"]]
        if not spec["scenes"][i].get("narration"):
            spec["scenes"][i]["narration"] = texts[i]
    total = t["total"]
    # ── ۴) مخلوط
    voice_parts = [(str(c["path"]), t["starts"][i] + LEAD) for i, c in clips.items()]
    sfx_parts = []
    if (audio.get("sfx") or any(s.get("sfx") for s in spec["scenes"])):
        cache: dict = {}
        for at, kind, db in sfx_events(spec, t["starts"]):
            key = (kind, round(db))
            if key not in cache:
                cache[key] = synth_sfx(kind, workdir / f"sfx_{kind}_{abs(round(db))}.wav", db)
            sfx_parts.append((str(cache[key]), at))
    result = {"spec": spec, "info": info, "mix": None}
    if voice_parts or sfx_parts or music_path:
        say(0.75, "مخلوط و استانداردسازیِ بلندی (‎-۱۴ LUFS)")
        mix = workdir / "mix.m4a"
        stats = build_mix(workdir, total, voice_parts, sfx_parts, {"path": music_path, "level_db": audio["music"].get("level_db", -22)} if music_path else None, mix)
        info["mix"] = stats
        result["mix"] = mix
    say(0.95, "صدا آماده شد")
    return result
