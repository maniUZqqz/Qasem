"""Topic clusters of Instagram posts: «what are the pages in this niche all making right now».

Plain dicts in, plain dicts out (no Django), deterministic (ties are broken by the term itself), tested with synthetic posts.

How a cluster is found: every post has topic *features* (its hashtags, its content words, neighbouring word pairs - textproc.terms).
A feature that two or more posts share and that is not on nearly every post is a *candidate topic*. Candidates are tried from the
strongest down (hashtags and word pairs weigh more than single words; rarer beats common); each takes all the posts that carry it and
are still free. A topic needs at least two posts. A single post that is far above its page's normal becomes a *breakout* of its own.

A cluster's score rewards the best posts in it (the mean of its top three post scores), how many different pages it spans (a topic
several pages make at once is a trend, one page repeating itself is not) and how recent it is.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter

from . import textproc

MIN_POSTS = 2
MAX_SHARE = 0.6                  # a feature on more than 60 % of the posts is the niche itself, not a topic inside it
MAX_CLUSTERS = 12
BREAKOUT_SCORE = 60.0
BREAKOUT_RATIO = 3.0
MAX_BREAKOUTS = 3
RECENT_H = 72.0


def cluster_key(label_terms: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(label_terms)).encode("utf-8")).hexdigest()[:12]


def _weight(term: str, count: int, n: int) -> float:
    kind = 1.6 if term.startswith("#") else 1.3 if " " in term else 1.0
    return count * kind * math.log(1.0 + n / count)


def _top(counter: Counter, k: int):
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:k]


def _cluster_stats(members: list[dict], now_ts: float, term: str | None, kind: str) -> dict:
    scores = sorted((m["score"] for m in members), reverse=True)
    top3 = sum(scores[:3]) / max(1, len(scores[:3]))
    accounts = {m["account"] for m in members}
    breadth = min(1.6, 1.0 + 0.2 * (len(accounts) - 1))
    recent = sum(1 for m in members if (now_ts - m["taken_at"]) / 3600.0 <= RECENT_H)
    share = recent / len(members)
    momentum = 0.8 + 0.4 * share
    score = min(100.0, top3 * breadth * momentum)
    fmts = Counter(m["fmt"] for m in members)
    tags = Counter(t for m in members for t in m.get("tags", []) if t not in textproc.GENERIC_TAGS)
    hooks, seen = [], set()
    for m in sorted(members, key=lambda m: -m["score"]):
        h = (m.get("hook") or {})
        text = (h.get("text") or "").strip()
        if text and (h.get("type"), text[:30]) not in seen and len(hooks) < 4:
            seen.add((h.get("type"), text[:30]))
            hooks.append({"text": text, "type": h.get("type") or "statement", "account": m["account"], "code": m.get("code"), "score": m["score"]})
    audio = Counter()
    audio_info = {}
    for m in members:
        music = m.get("music") or {}
        if music.get("title"):
            key = "%s|%s" % (music["title"].strip().lower(), (music.get("artist") or "").strip().lower())
            audio[key] += 1
            audio_info[key] = {"title": music["title"], "artist": music.get("artist") or "", "kind": music.get("kind") or ""}
    ratios = sorted(m["ratio"] for m in members)
    return {
        "score": round(score, 1), "size": len(members), "accounts": sorted(accounts), "accounts_count": len(accounts),
        "recent": recent, "recent_share": round(share, 2), "formats": dict(fmts),
        "dominant_format": _top(fmts, 1)[0][0] if fmts else "reel", "median_ratio": round(ratios[len(ratios) // 2], 2),
        "best_ratio": round(ratios[-1], 2), "hashtags": [t for t, _ in _top(tags, 8)], "hooks": hooks,
        "audio": [dict(audio_info[k], uses=c) for k, c in _top(audio, 3) if c >= 1],
        "top_posts": [m["id"] for m in sorted(members, key=lambda m: -m["score"])[:6]],
        "kind": kind, "term": term,
    }


def cluster_posts(posts: list[dict], now_ts: float, max_clusters: int = MAX_CLUSTERS, niche_terms: set[str] | None = None) -> list[dict]:
    """posts: [{'id','account','terms':set,'tags':[...],'score','ratio','taken_at','fmt','hook','music','code'}]. Returns clusters, best first.

    `niche_terms` (the store's own seed hashtags/keywords) only break ties and mark a cluster as inside the niche; they never create one."""
    niche_terms = {textproc.tag_phrase(str(t).lstrip("#")) for t in (niche_terms or set())}
    n = len(posts)
    out: list[dict] = []
    if n == 0:
        return out
    df: Counter = Counter()
    for p in posts:
        df.update(p["terms"])
    ceiling = max(2, int(MAX_SHARE * n)) if n >= 5 else n
    candidates = [t for t, c in df.items() if 2 <= c <= ceiling]
    candidates.sort(key=lambda t: (-_weight(t, df[t], n), t))
    taken: set = set()
    for term in candidates:
        members = [p for p in posts if term in p["terms"] and p["id"] not in taken]
        if len(members) < MIN_POSTS:
            continue
        taken.update(m["id"] for m in members)
        stats = _cluster_stats(members, now_ts, term, "topic")
        co = Counter(t for m in members for t in m["terms"] if t != term and not t.startswith("#") and " " not in t)
        partner = next((t for t, c in _top(co, 3) if c >= max(2, int(0.6 * len(members))) and t not in term), None)
        label = textproc.display_term(term) + (" · " + partner if partner and " " not in textproc.display_term(term) else "")
        stats.update({"label": label[:80], "key": cluster_key([term]), "post_ids": [m["id"] for m in members]})
        words = {textproc.display_term(term)}
        stats["in_niche"] = bool(niche_terms) and any(nt and (nt in w or w in nt) for w in words for nt in niche_terms)
        if stats["in_niche"]:
            stats["score"] = round(min(100.0, stats["score"] * 1.1), 1)
        out.append(stats)
        if len(out) >= max_clusters * 2:
            break
    # breakouts: single posts far above their page's normal that no topic took
    singles = [p for p in posts if p["id"] not in taken and p["score"] >= BREAKOUT_SCORE and p["ratio"] >= BREAKOUT_RATIO]
    for p in sorted(singles, key=lambda p: -p["score"])[:MAX_BREAKOUTS]:
        stats = _cluster_stats([p], now_ts, None, "breakout")
        hook = (p.get("hook") or {}).get("text") or ""
        label = hook[:60] if hook else (textproc.display_term("#" + p["tags"][0]) if p.get("tags") else "پستِ پرفروغ")
        stats.update({"label": label, "key": cluster_key(["post", p.get("code") or str(p["id"])]), "post_ids": [p["id"]], "in_niche": False})
        out.append(stats)
    out.sort(key=lambda c: (-c["score"], c["label"]))
    return out[:max_clusters]
