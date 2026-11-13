"""Repeated takes: the speaker stumbles, stops, and says the sentence again — keep the LAST attempt, cut the earlier one.

A false start sounds like «من می‌خواستم بگم … من می‌خواستم بگم که چغر یک برنامهٔ ورزشیه».  Silence removal cannot see it (there is speech
all the way) and filler removal cannot either (no «اِم»).  The words with their times can: a phrase that is followed, within a few seconds,
by a phrase that begins with the same words is an earlier try at the same sentence.

Pure functions over ASR words `[{"w", "s", "e"}]` (seconds, any common origin); no I/O.  Deliberately conservative — a wrong cut is a
sentence the owner said on purpose, so a repeat is only called a retake when the evidence is plain:

* the earlier phrase is at least two words, and the later one starts with (nearly) the same words — or the two are almost the same text;
* the later phrase is not shorter than the earlier one (a restart that goes further, or an identical second try);
* they are close: the pause between them is under `MAX_GAP` seconds;
* a single repeated word («بله بله») is emphasis, not a retake.

The cut keeps the natural pause in front of the kept take and never starts or ends inside a word.
"""
from __future__ import annotations

import difflib

#: a pause that separates two phrases
PHRASE_GAP = 0.4
#: the earlier try and the kept one are at most this far apart (end of the first → start of the second)
MAX_GAP = 5.0
#: how many of the earlier phrase's first words must open the later phrase
MIN_PREFIX = 2
#: near-identical text counts as a repeat even when the prefix differs a little (a dropped «که»)
MIN_RATIO = 0.82
#: breath left in front of the kept take
KEEP_LEAD = 0.12
#: a phrase longer than this is a paragraph, not a stumble
MAX_PHRASE_WORDS = 14

_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩ يك", "01234567890123456789 یک")
_END = "؟?!.…"


def norm(word: str) -> str:
    """Comparable form of a word: lower-case, Arabic ي ك → ی ک, no ZWNJ / punctuation / diacritics."""
    s = str(word or "").translate(_FA).replace("‌", "").lower()
    return "".join(ch for ch in s if ch.isalnum())


def phrases(words: list[dict], *, gap: float = PHRASE_GAP) -> list[dict]:
    """Group words into phrases: a pause of `gap` seconds or a sentence mark ends one.  `{start, end, words, norm}`."""
    clean = [w for w in (words or []) if isinstance(w, dict) and "s" in w and "e" in w and "w" in w and float(w["e"]) > float(w["s"])]
    clean.sort(key=lambda w: float(w["s"]))
    out: list[dict] = []
    cur: list[dict] = []
    for w in clean:
        if cur and float(w["s"]) - float(cur[-1]["e"]) >= gap:
            out.append(_make(cur))
            cur = []
        cur.append(w)
        if str(w["w"]).strip()[-1:] in _END:
            out.append(_make(cur))
            cur = []
    if cur:
        out.append(_make(cur))
    return [p for p in out if p["norm"]]


def _make(ws: list[dict]) -> dict:
    return {"start": float(ws[0]["s"]), "end": float(ws[-1]["e"]), "words": ws, "norm": [n for n in (norm(w["w"]) for w in ws) if n]}


def _prefix(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def find_retakes(words: list[dict], *, max_gap: float = MAX_GAP) -> list[dict]:
    """The earlier tries to remove: `[{start, end, text, kept_text, kept_start, why}]` (source seconds, `end` = where the kept take's lead-in begins).

    Chains collapse: of three attempts only the last one stays (the first two are listed, back to back)."""
    ph = phrases(words)
    found: list[dict] = []
    for i, a in enumerate(ph):
        if len(a["norm"]) < MIN_PREFIX or len(a["norm"]) > MAX_PHRASE_WORDS:
            continue
        for j in range(i + 1, min(len(ph), i + 4)):
            b = ph[j]
            if b["start"] - a["end"] > max_gap:
                break
            if len(b["norm"]) < len(a["norm"]) or len(b["norm"]) > MAX_PHRASE_WORDS * 2:
                continue
            need = min(len(a["norm"]), max(MIN_PREFIX, 3))
            shared = _prefix(a["norm"], b["norm"])
            ratio = difflib.SequenceMatcher(None, " ".join(a["norm"]), " ".join(b["norm"][:len(a["norm"]) + 1])).ratio()
            if shared >= need or ratio >= MIN_RATIO:
                found.append({"start": a["start"], "end": b["start"], "text": " ".join(str(w["w"]) for w in a["words"]),
                              "kept_text": " ".join(str(w["w"]) for w in b["words"]), "kept_start": b["start"],
                              "why": "همین جمله چند لحظه بعد دوباره (کامل‌تر) گفته شده" if shared >= need else "همین جمله تقریباً عیناً دوباره گفته شده"})
                break
    return found


def cuts_from(retakes: list[dict], words: list[dict] | None = None) -> list[tuple[float, float]]:
    """Source ranges to remove: from the start of the earlier try to just before the kept take (a natural breath stays in front of it)."""
    ws = [(float(w["s"]), float(w["e"])) for w in (words or []) if "s" in w and "e" in w]
    out: list[tuple[float, float]] = []
    for r in retakes:
        lo, hi = float(r["start"]) - 0.04, float(r["kept_start"]) - KEEP_LEAD
        for s, e in ws:                                    # never inside a word: start after a word that straddles lo, stop before one that straddles hi
            if s < lo < e:
                lo = s - 0.02
            if s < hi < e:
                hi = s - 0.02
        lo = max(0.0, lo)
        if hi - lo >= 0.3:
            out.append((round(lo, 3), round(hi, 3)))
    merged: list[list[float]] = []
    for lo, hi in sorted(out):
        if merged and lo <= merged[-1][1] + 0.15:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(a, b) for a, b in merged]


def describe_fa(retakes: list[dict], limit: int = 3) -> str:
    """One Persian sentence for the owner: which stumbles were removed."""
    if not retakes:
        return ""
    shown = "؛ ".join("«" + r["text"][:40] + "»" for r in retakes[:limit])
    more = f" و {len(retakes) - limit} مورد دیگر" if len(retakes) > limit else ""
    return f"دوبارگوییِ {shown}{more} (نسخهٔ آخر ماند)"

