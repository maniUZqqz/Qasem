"""Silence intelligence: which pauses are dead air, which are the speaker's own punctuation, and which only the owner can judge.

The owner (1405/08/22): «حتی تشخیصِ سکوت باید بهتر شود؛ بعضی سکوت‌ها را سناریو خواسته، باید در فرانت‌اند از من بپرسد».

A threshold cannot tell a pause the script wants («…و برندهٔ جایزه … علی است») from a stumbled silence while the speaker looked for a
word.  So the decision is split in three honest parts:

* **what is certain is decided here** — breaths and commas (< 0.35 s) are never touched; a gap at the very start or end, and a gap longer
  than 4 s over a still picture, is dead air; a short pause between sentences is tightened to a natural beat;
* **what is a matter of intent is asked** — a long pause after a question or a short punchy phrase, a pause in which the picture changes (a
  slide, a demonstration, a reveal), a pause between 0.9 s and 4 s with no cue either way.  Each question carries the words before and after,
  the length, our reason and OUR suggestion, so answering is one tap;
* **what the owner answered is remembered** — per source video, in a small file next to the project data, matched by position (not by
  index) so a re-analysis that moves a boundary by a fraction of a second still finds its answer.

Pure functions over plain data (speech spans, optional ASR words, optional per-second picture activity); the only I/O is the small
answers file and `visual_activity`, which samples the picture at 2 fps.  Cuts never land inside a word when words are known.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---- thresholds (seconds).  Every one of them is a judgement about speech rhythm, documented where it is used.
BREATH = 0.35            # shorter than this is a comma or a breath: never touched
SHORTEN_UP_TO = 0.9      # up to here a pause is just tightened; beyond it intent matters
ASK_FROM = 0.9
DEAD_AIR = 4.0           # this long over a still picture nobody meant it
EDGE_MIN = 0.45          # a gap at the very start/end shorter than this is left alone
EDGE_KEEP = 0.15         # what remains of a trimmed edge gap
TARGET = 0.32            # a tightened pause becomes this long (a natural beat)
CUT_PAD = 0.12           # breath left on each side of a hard cut
PENDING_KEEP = 1.0       # a pause nobody has judged yet is tightened only down to this: still clearly a pause if the script wanted it
WORD_PAD_BEFORE = 0.04   # never cut closer than this after a word ends…
WORD_PAD_AFTER = 0.07    # …or before the next one starts
MAX_QUESTIONS = 8        # more than this is a quiz, not a question: the rest follow our suggestion
VISUAL_ACTIVE = 0.55     # per-second picture activity (0..1) above which "something happens in the pause"

ACTIONS = ("keep", "shorten", "cut")

_QUESTION_WORDS = {"آیا", "چرا", "چطور", "چگونه", "کی", "کجا", "چند", "چه", "چی", "کدام", "کدوم", "کِی", "who", "what", "why", "how", "when", "where", "which"}
_REVEAL_WORDS = {"و", "پس", "اما", "ولی", "بنابراین", "یعنی", "and", "but", "so", "then"}
_END_MARKS = "؟?!.…"
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


# --------------------------------------------------------------------------------- finding the gaps


def find_silences(spans: list, duration: float, *, min_len: float = BREATH) -> list[dict]:
    """The gaps between speech spans (and before the first / after the last), as `{start, end, len, edge}`.
    `spans` = [[s, e], …] where somebody speaks, in source seconds."""
    duration = float(duration or 0.0)
    clean = sorted((max(0.0, float(s)), min(duration, float(e))) for s, e in (spans or []) if float(e) > float(s))
    merged: list[list[float]] = []
    for s, e in clean:
        if merged and s <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    if not merged:
        return []
    out: list[dict] = []
    cursor = 0.0
    for i, (s, e) in enumerate(merged):
        if s - cursor >= min_len:
            out.append({"start": round(cursor, 3), "end": round(s, 3), "len": round(s - cursor, 3), "edge": "lead" if i == 0 and cursor == 0.0 else ""})
        cursor = e
    if duration - cursor >= min_len:
        out.append({"start": round(cursor, 3), "end": round(duration, 3), "len": round(duration - cursor, 3), "edge": "trail"})
    return out


# --------------------------------------------------------------------------------- words around a gap


def _norm(word: str) -> str:
    return "".join(ch for ch in str(word or "").translate(_FA_DIGITS).lower() if ch.isalnum())


def _around(words: list[dict], start: float, end: float, *, n: int = 6, reach: float = 3.0) -> tuple[list[dict], list[dict]]:
    before = [w for w in words if float(w["e"]) <= start + 0.05 and float(w["e"]) >= start - reach][-n:]
    after = [w for w in words if float(w["s"]) >= end - 0.05 and float(w["s"]) <= end + reach][:n]
    return before, after


def _text(ws: list[dict]) -> str:
    return " ".join(str(w.get("w", "")).strip() for w in ws).strip()


def _phrase_words_before(words: list[dict], start: float, previous_end: float) -> int:
    return sum(1 for w in words if previous_end - 0.01 <= float(w["s"]) and float(w["e"]) <= start + 0.05)


def _ends_sentence(before: list[dict]) -> bool:
    last = str(before[-1].get("w", "")).strip() if before else ""
    return bool(last) and last[-1] in _END_MARKS


def _is_question(before: list[dict]) -> bool:
    """The phrase before the gap asks something: it ends with «؟»/«?» or has a question word among its last six words."""
    if not before:
        return False
    last = str(before[-1].get("w", "")).strip()
    if last and last[-1] in "؟?":
        return True
    asking = {_norm(q) for q in _QUESTION_WORDS}
    return any(_norm(w.get("w", "")) in asking for w in before[-6:])


# --------------------------------------------------------------------------------- the picture during a gap


def _activity_in(activity: list[float] | None, start: float, end: float) -> float | None:
    """The busiest picture second (0..1, one value per source second) inside [start, end]; None when the picture was not measured.
    The MAXIMUM, not the mean: one slide turning inside a two-second pause is the whole story."""
    if not activity:
        return None
    lo, hi = int(max(0, start)), int(min(len(activity), max(start + 1e-6, end) + 0.999))
    seg = activity[lo:hi]
    return max(seg) if seg else None


def visual_activity(path, duration: float, *, frames=None, fps: float = 2.0) -> list[float]:
    """How much the PICTURE changes each second (0..1, relative to this video's own busiest seconds) — a slide turning, a hand reaching
    for the product, a reveal.  Frame differences on 160-px thumbnails at 2 fps; `frames` (n, h, w, 3 BGR) is injectable for tests."""
    import cv2
    import numpy as np

    from . import reframe

    seconds = min(float(duration), 600.0)
    if frames is None:
        w, h = reframe._probe_size(path)
        frames = reframe._frames(path, 0.0, seconds, fps, 160, w, h)
    n = len(frames)
    if n < 2:
        return []
    gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    diffs = [0.0] + [float(cv2.absdiff(gray[i], gray[i - 1]).mean()) for i in range(1, n)]
    per = max(1, int(round(fps)))
    secs = int(np.ceil(n / fps))
    raw = np.array([max(diffs[i * per:(i + 1) * per] or [0.0]) for i in range(secs)])
    ref = float(np.percentile(raw, 92)) if len(raw) else 0.0
    if ref < 0.6:                                   # an essentially still picture: nothing "happens", whatever the noise says
        return [0.0] * secs
    return [round(float(min(1.0, x / ref)), 3) for x in raw]


# --------------------------------------------------------------------------------- classification


def classify(silences: list[dict], *, words: list[dict] | None = None, activity: list[float] | None = None, duration: float = 0.0,
             spans: list | None = None) -> list[dict]:
    """Each gap → `{id, start, end, len, edge, kind, decision, suggest, confidence, reason, before, after, activity, ask}`.

    `decision` is what we do ALONE when nobody answers: keep | shorten | cut | ask.  An `ask` also carries `suggest` (what we would do)."""
    words = [w for w in (words or []) if "s" in w and "e" in w]
    speech_ends = sorted(float(e) for _, e in (spans or []))
    rows: list[dict] = []
    for i, g in enumerate(silences):
        s, e, ln = float(g["start"]), float(g["end"]), float(g["len"])
        before, after = _around(words, s, e)
        prev_end = max([x for x in speech_ends if x < s - 0.2] or [0.0]) if speech_ends else 0.0
        act = _activity_in(activity, s, e)
        row = {"id": f"s{i + 1}", "start": round(s, 3), "end": round(e, 3), "len": round(ln, 3), "edge": g.get("edge", ""), "kind": "", "decision": "keep",
               "suggest": "keep", "confidence": 0.6, "reason": "", "before": _text(before), "after": _text(after),
               "activity": None if act is None else round(act, 2), "ask": False}
        cue_visual = act is not None and act >= VISUAL_ACTIVE
        cue_question = _is_question(before)
        cue_sentence = _ends_sentence(before)
        short_phrase = bool(words) and 0 < _phrase_words_before(words, s, prev_end) <= 3
        edge = g.get("edge", "")

        if ln < BREATH:
            row.update(kind="breath", decision="keep", confidence=0.95, reason="نَفَس یا ویرگول — دست نمی‌خورد.")
        elif edge:
            if ln >= EDGE_MIN:
                row.update(kind="leading" if edge == "lead" else "trailing", decision="cut", suggest="cut", confidence=0.9,
                           reason="سکوتِ ابتدای ویدیو — کوتاه می‌شود." if edge == "lead" else "سکوتِ انتهای ویدیو — کوتاه می‌شود.")
            else:
                row.update(kind="breath", decision="keep", confidence=0.8, reason="لبهٔ ویدیو؛ کوتاه است و دست نمی‌خورد.")
        elif cue_visual and ln >= 0.7:
            row.update(kind="visual_beat", decision="ask", suggest="keep", confidence=0.7,
                       reason="در همین مکث تصویر عوض می‌شود (اسلاید، نمایش دادن یا نشان‌دادنِ چیزی) — ممکن است عمدی باشد.")
        elif ln >= DEAD_AIR:
            row.update(kind="dead_air", decision="cut", suggest="cut", confidence=0.85, reason=f"{_fa(round(ln, 1))} ثانیه سکوتِ بی‌حرکت — کوتاه می‌شود.")
        elif ln < ASK_FROM:
            if cue_question or (cue_sentence and ln >= 0.6):
                row.update(kind="beat", decision="keep", suggest="keep", confidence=0.7, reason="مکثِ کوتاه بعد از سؤال/پایانِ جمله — ریتمِ طبیعی گفتار.")
            else:
                row.update(kind="short_pause", decision="shorten", suggest="shorten", confidence=0.8,
                           reason=f"مکثِ {_fa(round(ln, 1))} ثانیه‌ای — به یک ضرب کوتاه می‌شود.")
        else:
            why = []
            suggest = "shorten"
            if cue_question:
                why.append("بعد از یک سؤال")
                suggest = "keep"
            if short_phrase:
                why.append("بعد از یک عبارتِ کوتاهِ تأکیدی")
                suggest = "keep"
            if cue_sentence and not cue_question:
                why.append("بعد از پایانِ یک جمله")
            if not why:
                why.append("دلیلِ روشنی برای حذف یا نگه‌داشتن نیست")
            row.update(kind="dramatic" if suggest == "keep" else "long_pause", decision="ask", suggest=suggest, confidence=0.5,
                       reason=f"مکثِ {_fa(round(ln, 1))} ثانیه‌ای ({'، '.join(why)}) — شاید سناریو خواسته باشد.")
        row["ask"] = row["decision"] == "ask"
        rows.append(row)
    # too many questions is a quiz: keep the most doubtful ones (longest, lowest confidence); the rest follow our suggestion quietly
    asks = [r for r in rows if r["ask"]]
    if len(asks) > MAX_QUESTIONS:
        asks.sort(key=lambda r: (r["confidence"], -r["len"]))
        for r in asks[MAX_QUESTIONS:]:
            r["ask"] = False
            r["decision"] = r["suggest"]
            r["reason"] += " (در میانِ پرسش‌های کم‌اهمیت‌تر؛ پیشنهادِ ما اعمال می‌شود.)"
    return rows


# --------------------------------------------------------------------------------- answers (remembered per source)


def _answers_dir() -> Path:
    from django.conf import settings

    base = Path(getattr(settings, "NM_DATA_DIR", None) or tempfile.gettempdir())
    path = base / "autoedit" / "silence-answers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file_for(store_id, ref: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(ref or "x"))[:80] or "x"
    return _answers_dir() / f"store{int(store_id)}__{safe}.json"


def load_answers(store_id, ref: str) -> dict:
    try:
        data = json.loads(_file_for(store_id, ref).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"answers": [], "rule": {}, "updated": None}
    if not isinstance(data, dict):
        return {"answers": [], "rule": {}, "updated": None}
    answers = [a for a in data.get("answers", []) if isinstance(a, dict) and a.get("action") in ACTIONS]
    return {"answers": answers, "rule": data.get("rule") if isinstance(data.get("rule"), dict) else {}, "updated": data.get("updated")}


def save_answers(store_id, ref: str, answers: list[dict], rule: dict | None = None) -> dict:
    """Replace the remembered answers of one source.  Invalid rows are dropped, not raised."""
    clean = []
    for a in answers or []:
        try:
            s, e, act = float(a["start"]), float(a["end"]), str(a["action"])
        except (KeyError, TypeError, ValueError):
            continue
        if act in ACTIONS and e > s >= 0:
            clean.append({"start": round(s, 3), "end": round(e, 3), "action": act})
    rule = {k: v for k, v in (rule or {}).items() if k == "ask_default" and v in (*ACTIONS, "suggest")}
    doc = {"version": 1, "ref": str(ref)[:120], "answers": clean[:200], "rule": rule, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    path = _file_for(store_id, ref)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return load_answers(store_id, ref)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def answer_for(answers: list[dict], start: float, end: float) -> str | None:
    """The remembered action for a gap: the answer whose span overlaps it by at least half of the shorter of the two."""
    best, best_ov = None, 0.0
    for a in answers or []:
        ov = _overlap(start, end, float(a["start"]), float(a["end"]))
        need = 0.5 * min(end - start, float(a["end"]) - float(a["start"]))
        if ov >= max(need, 0.05) and ov > best_ov:
            best, best_ov = a["action"], ov
    return best


# --------------------------------------------------------------------------------- the decision and the cuts


def resolve(rows: list[dict], saved: dict | None = None) -> list[dict]:
    """Final `action` (keep | shorten | cut) per gap + `pending` (still an open question)."""
    saved = saved or {"answers": [], "rule": {}}
    answers = saved.get("answers") or []
    default = (saved.get("rule") or {}).get("ask_default")
    out = []
    for r in rows:
        given = answer_for(answers, r["start"], r["end"])
        row = dict(r)
        if given:
            row.update(action=given, pending=False, answered=True)
        elif r["decision"] == "ask":
            # an open question: never cut what might be intended — follow our suggestion only when it is "keep"/"shorten"
            action = default if default in ACTIONS else ("keep" if r["suggest"] == "keep" else "shorten")
            row.update(action=action, pending=default not in ACTIONS, answered=False)
        else:
            row.update(action=r["decision"], pending=False, answered=False)
        out.append(row)
    return out


def _snap_to_words(start: float, end: float, words: list[dict]) -> tuple[float, float]:
    """Pull a cut into the gap between words: it must start after the last word that ends near its start, and end before the next word."""
    for w in words:
        ws, we = float(w["s"]), float(w["e"])
        if ws < start < we + WORD_PAD_BEFORE:
            start = we + WORD_PAD_BEFORE
        if ws - WORD_PAD_AFTER < end < we:
            end = ws - WORD_PAD_AFTER
    return start, end


def cuts_from(rows: list[dict], *, words: list[dict] | None = None, duration: float = 0.0) -> list[tuple[float, float]]:
    """The source ranges to REMOVE for the resolved gaps.  A cut keeps a natural pause behind (tightened), never touches a breath, and when
    words are known never starts or ends inside one."""
    out: list[tuple[float, float]] = []
    for r in rows:
        act = r.get("action", "keep")
        if act == "keep":
            continue
        s, e = float(r["start"]), float(r["end"])
        if r.get("edge") == "lead":
            lo, hi = 0.0, e - EDGE_KEEP
        elif r.get("edge") == "trail":
            lo, hi = s + EDGE_KEEP, (duration or e)
        elif act == "cut":
            lo, hi = s + CUT_PAD, e - CUT_PAD
        else:                                               # shorten: leave a natural beat in the middle
            keep = min(PENDING_KEEP if r.get("pending") else TARGET, e - s)
            lo, hi = s + keep / 2, e - keep / 2
        if words:
            lo, hi = _snap_to_words(lo, hi, words)
        if hi - lo >= 0.1:
            out.append((round(lo, 3), round(hi, 3)))
    return out


# --------------------------------------------------------------------------------- one call for the web layer and the tools


def words_cached(path) -> list[dict]:
    """ASR words of a file IF they are already known (the one transcript per source kept by `director.ctx`).  Never starts speech recognition."""
    try:
        from . import media_cache

        cache_file = media_cache.cache_dir() / f"asr-{media_cache._key(Path(path), 'asr-whole')}.json"
        data = media_cache._read_json(cache_file)
        if isinstance(data, list):
            return [w for w in data if isinstance(w, dict) and "s" in w and "e" in w and "w" in w]
    except Exception as exc:  # noqa: BLE001 — words are a refinement
        logger.info("no cached words for %s: %s", path, exc)
    return []


def activity_cached(path, duration: float) -> list[float]:
    """`visual_activity`, cached next to the other analyses (media_cache), so opening the review twice does not decode the video twice."""
    try:
        from . import media_cache

        cache_file = media_cache.cache_dir() / f"vact-{media_cache._key(Path(path), 'vact2')}.json"
        data = media_cache._read_json(cache_file)
        if isinstance(data, list):
            return [float(x) for x in data]
        value = visual_activity(path, duration)
        media_cache._write_atomic(cache_file, json.dumps(value).encode("utf-8"))
        return value
    except Exception as exc:  # noqa: BLE001
        logger.info("visual activity of %s unavailable: %s", path, exc)
        return []


def review(path, duration: float, *, store_id=None, ref: str = "", spans: list | None = None, words: list | None = None,
           activity: list | None = None, saved: dict | None = None) -> dict:
    """Everything the panel and the planners need for one source: the gaps, our classification, the resolved action of each, the open
    questions, the ranges to cut.  All inputs are injectable; by default they come from the shared caches."""
    from . import media_cache

    duration = float(duration or 0.0)
    spans = media_cache.speech_spans(Path(path)) if spans is None else spans
    words = words_cached(path) if words is None else words
    activity = activity_cached(path, duration) if activity is None else activity
    saved = (load_answers(store_id, ref) if store_id is not None and ref else {"answers": [], "rule": {}}) if saved is None else saved
    gaps = find_silences(spans, duration)
    rows = resolve(classify(gaps, words=words, activity=activity, duration=duration, spans=spans), saved)
    cuts = cuts_from(rows, words=words, duration=duration)
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ACTIONS}
    questions = [r for r in rows if r["ask"] and not r["answered"]]
    return {
        "ref": ref, "duration": round(duration, 2), "silences": rows, "questions": questions, "cuts": cuts,
        "counts": counts, "removed_seconds": round(sum(b - a for a, b in cuts), 2),
        "has_words": bool(words), "has_picture": bool(activity), "answered": sum(1 for r in rows if r["answered"]),
        "pending": sum(1 for r in rows if r["pending"]),
        "note": "" if words else "کلمه‌ها هنوز شناخته نشده‌اند؛ برش‌ها با انرژیِ صدا و با فاصلهٔ امن از لبهٔ گفتار انجام می‌شود (با روشن شدنِ سرورِ پردازش، روی مرزِ کلمه می‌نشیند).",
    }
