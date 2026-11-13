"""Scoring a page's posts and rebuilding a store's topic clusters, hashtag statistics and audio statistics.

`rescore_accounts` is called after every ingest for the pages that were read; `rebuild_store` after that (and lazily when a store's
config is dirty). Both are cheap: a few hundred posts at most.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from . import clustering, explain, scoring, textproc
from .models import IgAccount, IgAudio, IgHashtag, IgPost, IgSeed, IgStoreConfig, IgTrendCluster

WINDOW_DAYS = 21                  # posts older than this are history, not trend
SCORE_DAYS = 30
HISTORY = 40                      # posts of a page used for its baseline
RECENT_H = 72


def epoch(dt: datetime) -> float:
    return dt.timestamp()


def post_interactions(post: IgPost) -> float:
    return scoring.interactions(post.likes, post.comments, post.likes_hidden)[0]


def rescore_accounts(accounts, now=None) -> int:
    """Baselines of these pages and the trend score of their recent posts. Returns the number of posts scored."""
    now = now or timezone.now()
    now_ts = epoch(now)
    scored = 0
    for acc in accounts:
        rows = list(IgPost.objects.filter(account=acc).order_by("-taken_at")[:HISTORY])
        if not rows:
            continue
        hist = [{"taken_at": epoch(p.taken_at), "interactions": post_interactions(p), "fmt": p.fmt} for p in rows]
        base_all = scoring.baseline(hist, acc.followers, None, now_ts)
        base_reel = scoring.baseline(hist, acc.followers, "reel", now_ts)
        acc.baseline, acc.baseline_reel, acc.baseline_note = base_all["value"], base_reel["value"], base_all["source"]
        acc.save(update_fields=["baseline", "baseline_reel", "baseline_note", "updated_at"])
        for p in rows:
            age_h = (now_ts - epoch(p.taken_at)) / 3600.0
            if age_h > SCORE_DAYS * 24:
                continue
            inter, estimated = scoring.interactions(p.likes, p.comments, p.likes_hidden)
            base = scoring.baseline(hist, acc.followers, p.fmt, now_ts)["value"]
            growth = growth_of(p, inter, now)
            res = scoring.post_score(inter, age_h, base, p.views if p.fmt in ("reel", "video") else None, acc.followers, growth)
            res["estimated"] = estimated
            p.score, p.ratio, p.growth, p.explain, p.scored_at = res["score"], res["ratio"], res["growth"], res, now
            p.save(update_fields=["score", "ratio", "growth", "explain", "scored_at", "updated_at"])
            scored += 1
    return scored


def growth_of(post: IgPost, inter_now: float, now) -> float | None:
    """Growth ratio from the latest earlier reading that is at least ~2 hours old."""
    prev = post.snapshots.filter(at__lte=now - timedelta(hours=2)).order_by("-at").first()
    if prev is None:
        return None
    inter_prev = scoring.interactions(prev.likes, prev.comments, post.likes_hidden)[0]
    age_prev = (epoch(prev.at) - epoch(post.taken_at)) / 3600.0
    between = (epoch(now) - epoch(prev.at)) / 3600.0
    return scoring.growth_ratio(inter_now, inter_prev, age_prev, between)


# ---- the store's view ---------------------------------------------------------------------------------------------------------

def watched_usernames(store) -> list[str]:
    return list(IgSeed.objects.filter(store=store, kind=IgSeed.Kind.ACCOUNT, enabled=True).values_list("value", flat=True))


def niche_terms(store) -> set[str]:
    return set(IgSeed.objects.filter(store=store, enabled=True, kind__in=[IgSeed.Kind.HASHTAG, IgSeed.Kind.KEYWORD])
               .values_list("value", flat=True))


def store_posts(store, now=None, days: int = WINDOW_DAYS):
    now = now or timezone.now()
    names = watched_usernames(store)
    return (IgPost.objects.filter(account__username__in=names, taken_at__gte=now - timedelta(days=days))
            .select_related("account").order_by("-taken_at")[:800])


def _post_dict(p: IgPost) -> dict:
    tags = [t for t in (p.hashtags or []) if t]
    return {"id": p.pk, "code": p.code, "account": p.account.username, "terms": textproc.terms(p.caption, tags), "tags": tags,
            "score": p.score, "ratio": p.ratio, "taken_at": epoch(p.taken_at), "fmt": p.fmt,
            "hook": {"text": p.hook, "type": p.hook_type},
            "music": {"title": p.music_title, "artist": p.music_artist, "kind": p.music_kind} if p.music_title else None}


@transaction.atomic
def rebuild_store(store, now=None) -> dict:
    """Clusters, hashtag stats and audio stats of this store from the posts of the pages it watches."""
    now = now or timezone.now()
    posts = list(store_posts(store, now))
    dicts = [_post_dict(p) for p in posts]
    clusters = clustering.cluster_posts(dicts, epoch(now), niche_terms=niche_terms(store))
    seen_keys = set()
    for c in clusters:
        stats = {k: v for k, v in c.items() if k not in ("label", "key", "post_ids", "score", "size", "accounts_count", "kind")}
        obj, created = IgTrendCluster.objects.get_or_create(store=store, key=c["key"], defaults={"label": c["label"]})
        obj.label, obj.kind, obj.fmt = c["label"], c["kind"], c["dominant_format"]
        obj.score, obj.size, obj.accounts_count = c["score"], c["size"], c["accounts_count"]
        obj.post_ids, obj.stats, obj.why = c["post_ids"], stats, explain.why_cluster(c)
        obj.active, obj.computed_at = True, now
        obj.save()
        seen_keys.add(c["key"])
    IgTrendCluster.objects.filter(store=store, active=True).exclude(key__in=seen_keys).update(active=False)
    tags = _rebuild_hashtags(store, posts, now)
    audio = _rebuild_audio(store, posts, now)
    IgStoreConfig.objects.update_or_create(store=store, defaults={"dirty": False})
    return {"clusters": len(clusters), "hashtags": tags, "audio": audio, "posts": len(posts)}


def _rebuild_hashtags(store, posts, now) -> int:
    by: dict[str, list[IgPost]] = defaultdict(list)
    for p in posts:
        for t in set(p.hashtags or []):
            if t and t not in textproc.GENERIC_TAGS:
                by[t].append(p)
    IgHashtag.objects.filter(store=store).delete()
    rows = []
    for tag, ps in by.items():
        if len(ps) < 2:
            continue
        scores = [p.score for p in ps]
        recent = sum(1 for p in ps if (epoch(now) - epoch(p.taken_at)) / 3600.0 <= RECENT_H)
        avg = sum(scores) / len(scores)
        accounts = len({p.account_id for p in ps})
        score = min(100.0, avg * (1 + 0.15 * (accounts - 1)) * (0.8 + 0.4 * recent / len(ps)))
        rows.append(IgHashtag(store=store, tag=tag[:80], posts=len(ps), accounts=accounts, avg_score=round(avg, 1), best_score=max(scores),
                              recent_posts=recent, score=round(score, 1), first_seen=min(p.taken_at for p in ps), last_seen=max(p.taken_at for p in ps)))
    rows.sort(key=lambda r: (-r.score, r.tag))
    IgHashtag.objects.bulk_create(rows[:60])
    return min(len(rows), 60)


def _rebuild_audio(store, posts, now) -> int:
    by: dict[str, list[IgPost]] = defaultdict(list)
    for p in posts:
        if p.music_title:
            key = hashlib.sha1(("%s|%s" % (p.music_title.strip().lower(), p.music_artist.strip().lower())).encode("utf-8")).hexdigest()[:20]
            by[key].append(p)
    IgAudio.objects.filter(store=store).delete()
    rows = []
    for key, ps in by.items():
        scores = [p.score for p in ps]
        accounts = len({p.account_id for p in ps})
        avg = sum(scores) / len(scores)
        recent = sum(1 for p in ps if (epoch(now) - epoch(p.taken_at)) / 3600.0 <= RECENT_H)
        score = min(100.0, avg * (1 + 0.2 * (accounts - 1)) * (0.8 + 0.4 * recent / len(ps)))
        first = ps[0]
        rows.append(IgAudio(store=store, key=key, title=first.music_title[:200], artist=first.music_artist[:200], kind=first.music_kind[:10],
                            reels=len(ps), accounts=accounts, total_views=sum(p.views or 0 for p in ps), avg_score=round(avg, 1),
                            score=round(score, 1), first_seen=min(p.taken_at for p in ps), last_seen=max(p.taken_at for p in ps)))
    rows.sort(key=lambda r: (-r.score, r.title))
    IgAudio.objects.bulk_create(rows[:40])
    return min(len(rows), 40)


def ensure_fresh(store) -> bool:
    """Rebuild when new data arrived since the last build. Returns True when it rebuilt."""
    cfg, _ = IgStoreConfig.objects.get_or_create(store=store)
    if cfg.dirty or not IgTrendCluster.objects.filter(store=store).exists() and IgSeed.objects.filter(store=store).exists():
        rebuild_store(store)
        return True
    return False


def mark_dirty_for_accounts(usernames) -> int:
    """Stores that watch any of these pages need a rebuild at their next look."""
    stores = IgSeed.objects.filter(kind=IgSeed.Kind.ACCOUNT, value__in=list(usernames)).values_list("store_id", flat=True).distinct()
    n = 0
    for sid in stores:
        IgStoreConfig.objects.update_or_create(store_id=sid, defaults={"dirty": True})
        n += 1
    return n
