"""Word error rate for the ASR round-trip and the result table.

The idea (docs/pronunciation): speak a sentence with an engine, listen to it with a
speech recogniser, compare what the recogniser heard with what we *meant*. If a
change to the pronunciation layer makes the recogniser hear the right words more
often, the voice really got clearer. WER on its own is not "naturalness", but it is
an honest, repeatable, automatic number, and a regression here is a real regression.

Pure Python, stdlib only (the node uses it too).
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from .normalize import normalize

_PUNCT = re.compile(r"[،,.؟?!؛;:«»\"'()\[\]{}…\-–—_*#]")
_MARKS = re.compile("[ً-ْٰٔ]")
_EZAFE_YE = re.compile("(?<=ه)‌ی(?![آ-ی])")

#: Spoken variants that a recogniser writes the colloquial way; both sides are folded
#: so the metric does not punish a recogniser for being colloquial.
_FOLD = {
    "یه": "یک", "هست": "است", "هستش": "است", "میشه": "می‌شود", "میکنه": "می‌کند",
    "اینجا": "اینجا", "اون": "آن", "این": "این", "بود": "بود",
}


def fold(text: str) -> list[str]:
    """Words of ``text`` in a comparable form (numbers spelled, no punctuation or marks)."""
    t = normalize(text, collect=False).text
    t = _MARKS.sub("", t)
    t = _EZAFE_YE.sub("", t)          # «برنامه‌ی» is the word «برنامه» (the ی is the ezafe, not a word): a recogniser writes it without
    t = _PUNCT.sub(" ", t)
    t = t.replace("‌", " ").replace("ي", "ی").replace("ك", "ک")
    words = [w for w in t.split() if w]
    return [_FOLD.get(w, w) for w in words]


def _distance(ref: list[str], hyp: list[str]) -> tuple[int, int, int, int]:
    """Levenshtein with a backtrace: (substitutions, deletions, insertions, len(ref))."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    i, j, s, d, ins = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            if ref[i - 1] != hyp[j - 1]:
                s += 1
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            d += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return s, d, ins, n


@dataclass
class Score:
    errors: int
    words: int
    sub: int = 0
    dele: int = 0
    ins: int = 0
    missed: list[str] = field(default_factory=list)   # reference words the recogniser did not hear

    @property
    def wer(self) -> float:
        return self.errors / self.words if self.words else 0.0


def score(reference: str, hypothesis: str) -> Score:
    ref, hyp = fold(reference), fold(hypothesis)
    s, d, i, n = _distance(ref, hyp)
    hyp_set = set(hyp)
    return Score(errors=s + d + i, words=n, sub=s, dele=d, ins=i,
                 missed=[w for w in ref if w not in hyp_set])


def corpus_wer(pairs: list[tuple[str, str]]) -> float:
    """Total errors / total reference words over many (reference, hypothesis) pairs."""
    errs = words = 0
    for ref, hyp in pairs:
        sc = score(ref, hyp)
        errs += sc.errors
        words += sc.words
    return errs / words if words else 0.0


def summarise(rows: list[dict]) -> dict:
    """Aggregate result rows.

    Each row: ``{"tag", "ref", "before": hyp or None, "after": hyp or None}``.
    Returns overall and per-tag WER before/after and the sentences that got worse.
    """
    def agg(sel: list[dict]) -> dict:
        out = {"n": len(sel)}
        for variant in ("before", "after"):
            pairs = [(r["ref"], r[variant]) for r in sel if r.get(variant) is not None]
            out[variant] = round(corpus_wer(pairs), 4) if pairs else None
        if out["before"] is not None and out["after"] is not None:
            out["delta"] = round(out["after"] - out["before"], 4)
        return out

    tags = sorted({r["tag"] for r in rows})
    worse = []
    for r in rows:
        if r.get("before") is None or r.get("after") is None:
            continue
        b, a = score(r["ref"], r["before"]), score(r["ref"], r["after"])
        if a.errors > b.errors:
            worse.append({"tag": r["tag"], "ref": r["ref"], "before": b.errors, "after": a.errors})
    return {"overall": agg(rows), "by_tag": {t: agg([r for r in rows if r["tag"] == t]) for t in tags},
            "worse": worse[:25], "median_sentence_wer_after": _median_after(rows)}


def _median_after(rows: list[dict]) -> float | None:
    vals = [score(r["ref"], r["after"]).wer for r in rows if r.get("after") is not None]
    return round(statistics.median(vals), 4) if vals else None
