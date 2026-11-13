"""Trend scoring for Instagram posts: how much better is this post doing than its page usually does, how fast is it growing, how fresh.

Pure functions on plain numbers (no Django), so every rule can be tested with a table. The idea in one paragraph:

* A post's *interactions* are likes + 2×comments (a comment costs more than a like). Hidden likes are estimated from the comments
  and flagged, never silently trusted.
* A page's *baseline* is what its **matured** posts (older than a day) usually get: the median, which one lucky post cannot move.
* A young post has not collected everything yet, so its interactions are *projected* to what a post that age usually ends with
  (a smooth maturity curve) before being compared with the baseline: **velocity ratio** = projected / baseline.
* **Growth** compares two readings of the same post: its rate since the last reading against its own average rate before.
* **Recency** fades a post's chance of being «now» over days.
* Reels get a **reach** bonus when they were seen by many more people than follow the page.
"""
from __future__ import annotations

import math
import statistics

LIKE_W, COMMENT_W = 1.0, 2.0
MATURE_AFTER_H = 24.0
MATURITY_TAU_H = 18.0           # a post has ~63 % of its final interactions after 18 h, ~86 % after 36 h
MIN_MATURITY = 0.15             # never project more than ~6.7x from a very young post
RECENCY_TAU_H = 72.0
MAX_RATIO = 25.0
HIDDEN_LIKES_PER_COMMENT = 12.0  # when likes are hidden: a rough, flagged estimate
DEFAULT_ER = 0.02               # a page with too little history: 2 % of its followers interact with a typical post
NEW_POST_H = 1.0


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def interactions(likes, comments, hidden: bool = False) -> tuple[float, bool]:
    """(interaction count, estimated?). None counts as unknown, not zero."""
    c = comments or 0
    if likes is None:
        if hidden or comments is not None:
            return float(c) * (COMMENT_W + HIDDEN_LIKES_PER_COMMENT * LIKE_W), True
        return 0.0, True
    return float(likes) * LIKE_W + float(c) * COMMENT_W, False


def maturity(age_h: float) -> float:
    """Share of its final interactions a post of this age has collected, 0.15–1."""
    return clamp(1.0 - math.exp(-max(age_h, 0.0) / MATURITY_TAU_H), MIN_MATURITY, 1.0)


def recency(age_h: float) -> float:
    return math.exp(-max(age_h, 0.0) / RECENCY_TAU_H)


def detect_format(kind: str | None, items_count=None, width=None, height=None) -> str:
    """reel / carousel / photo / video from Abagram's own post kind plus the picture's shape."""
    kind = (kind or "").lower()
    try:
        n = int(items_count or 1)
    except (TypeError, ValueError):
        n = 1
    if kind in ("reel", "clips") or kind == "igtv":
        return "reel"
    if kind in ("album", "carousel", "sidecar") or n > 1:
        return "carousel"
    tall = bool(width and height and float(height) / float(width) >= 1.7)
    if kind == "video":
        return "reel" if tall else "video"
    return "photo"


def baseline(posts: list[dict], followers=None, fmt: str | None = None, now_ts: float | None = None) -> dict:
    """What a typical post of this page gets. posts: [{'taken_at': epoch, 'interactions': float, 'fmt': str}].

    Uses matured posts (>= 24 h old) of the wanted format when there are at least 3 of them, else all matured posts, else
    all posts, else a default from the follower count. Returns {'value', 'n', 'source'}."""
    import time
    now_ts = now_ts or time.time()

    def pick(rows):
        vals = [r["interactions"] for r in rows if r.get("interactions") is not None]
        return vals

    matured = [p for p in posts if (now_ts - p["taken_at"]) / 3600.0 >= MATURE_AFTER_H]
    same = [p for p in matured if fmt and p.get("fmt") == fmt]
    for rows, source in ((same, "format"), (matured, "matured"), (posts, "all")):
        vals = pick(rows)
        need = 3 if source == "format" else 2
        if len(vals) >= need:
            return {"value": max(float(statistics.median(vals)), 1.0), "n": len(vals), "source": source}
    if followers:
        return {"value": max(float(followers) * DEFAULT_ER, 1.0), "n": 0, "source": "followers"}
    return {"value": 50.0, "n": 0, "source": "default"}


def velocity_ratio(inter: float, age_h: float, base: float) -> float:
    """Projected final interactions of a post of this age over what the page normally gets."""
    projected = inter / maturity(age_h)
    return clamp(projected / max(base, 1.0), 0.0, MAX_RATIO)


def growth_ratio(cur: float, prev: float, age_prev_h: float, hours_between: float) -> float | None:
    """The post's rate since the earlier reading over its own average rate until then (1 = steady, 2 = twice as fast now)."""
    if hours_between < 1.5 or age_prev_h <= 0:
        return None
    avg_before = max(prev, 1.0) / max(age_prev_h, 1.0)
    now_rate = max(cur - prev, 0.0) / hours_between
    return clamp(now_rate / avg_before, 0.0, MAX_RATIO)


def _unit(ratio: float, top: float = 10.0) -> float:
    """1x -> 0, `top`x -> 1 on a log scale; below 1x -> 0."""
    return clamp(math.log(max(ratio, 1.0)) / math.log(top))


def reach_bonus(views, followers) -> float:
    """0–0.15: a reel seen by many more people than follow the page went beyond its own audience."""
    if not views or not followers:
        return 0.0
    r = float(views) / max(float(followers), 1.0)
    return 0.15 * clamp(math.log10(r + 1.0) / 1.0)


def post_score(inter: float, age_h: float, base: float, views=None, followers=None, growth: float | None = None) -> dict:
    """The trend score (0–100) of one post and the numbers behind it."""
    ratio = velocity_ratio(inter, age_h, base)
    vpos = _unit(ratio)
    gpos = _unit(growth) if growth is not None else vpos
    bonus = reach_bonus(views, followers)
    combined = clamp(0.7 * vpos + 0.3 * gpos + bonus)
    rec = recency(age_h)
    score = 100.0 * combined * (0.35 + 0.65 * rec)
    if age_h < NEW_POST_H:                                   # a post minutes old has nothing to measure yet
        score *= 0.4
    return {"score": round(score, 1), "ratio": round(ratio, 2), "growth": None if growth is None else round(growth, 2),
            "recency": round(rec, 3), "reach_bonus": round(bonus, 3), "baseline": round(base, 1), "age_h": round(age_h, 1),
            "interactions": round(inter, 1)}
