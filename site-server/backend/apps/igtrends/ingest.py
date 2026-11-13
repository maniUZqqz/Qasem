"""Applying a batch (from the node, from a pushed request or from an imported Abagram file) to the database. Idempotent: the same batch
twice changes nothing but the readings count."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from . import engine, normalize, scoring, textproc
from .models import IgAccount, IgPost, IgPostSnapshot, IgSeed, IgStoreConfig

SNAPSHOT_EVERY = timedelta(minutes=60)
KEEP_SNAPSHOTS_DAYS = 14
GONE_AFTER = 2                     # a page reported «not found» this many times is no longer scanned


def _dt(ts):
    return datetime.fromtimestamp(ts, tz=dt_timezone.utc)


def _upsert_account(row: dict, read_at) -> IgAccount:
    acc, _ = IgAccount.objects.get_or_create(username=row["username"])
    for field in ("ig_user_id", "full_name", "biography", "category"):
        if row.get(field):
            setattr(acc, field, row[field])
    for field in ("followers", "following", "posts_count"):
        if row.get(field) is not None:
            setattr(acc, field, row[field])
    for field in ("is_verified", "is_private", "is_business"):
        if field in row:
            setattr(acc, field, bool(row[field]))
    if row.get("fetched_at"):
        acc.fetched_at = _dt(row["fetched_at"])
    acc.last_read_at = read_at
    acc.save()
    return acc


def _upsert_post(acc: IgAccount, row: dict, now) -> str:
    """'new' | 'updated' | 'same'."""
    fmt = scoring.detect_format(row.get("kind"), row.get("items_count"), row.get("width"), row.get("height"))
    hook = textproc.extract_hook(row.get("caption") or "")
    music = row.get("music") or {}
    values = {"ig_id": row.get("id") or "", "fmt": fmt, "ig_kind": row.get("kind") or "", "taken_at": _dt(row["taken_at"]),
              "caption": row.get("caption") or "", "hashtags": row.get("hashtags") or [], "likes": row.get("likes"), "comments": row.get("comments"),
              "views": row.get("views"), "likes_hidden": row.get("likes_hidden", False), "comments_disabled": row.get("comments_disabled", False),
              "pinned": row.get("pinned", False), "music_title": music.get("title", ""), "music_artist": music.get("artist", ""),
              "music_kind": music.get("kind", ""), "items_count": row.get("items_count") or 1, "width": row.get("width"), "height": row.get("height"),
              "paid_partnership": row.get("paid_partnership", False), "hook": hook["text"][:240], "hook_type": hook["type"], "last_seen_at": now}
    post = IgPost.objects.filter(code=row["code"]).first()
    if post is None:
        post = IgPost.objects.create(account=acc, code=row["code"], first_seen_at=now, **values)
        _snapshot(post, now, force=True)
        return "new"
    changed = any(getattr(post, k) != v for k, v in values.items() if k != "last_seen_at")
    for k, v in values.items():
        setattr(post, k, v)
    post.account = acc
    post.save()
    _snapshot(post, now)
    return "updated" if changed else "same"


def _snapshot(post: IgPost, now, force: bool = False) -> None:
    last = post.snapshots.order_by("-at").first()
    if not force and last is not None:
        same = (last.likes, last.comments, last.views) == (post.likes, post.comments, post.views)
        if same or now - last.at < SNAPSHOT_EVERY:
            return
    IgPostSnapshot.objects.create(post=post, at=now, likes=post.likes, comments=post.comments, views=post.views)


def _apply_seed_statuses(store, per_account: dict, now) -> None:
    for name, row in per_account.items():
        seed = IgSeed.objects.filter(store=store, kind=IgSeed.Kind.ACCOUNT, value=name).first()
        if seed is None:
            continue
        status = row.get("status") or ""
        if status in ("ok", "private", "not_found", "failed"):
            seed.last_status = status
        if status == "ok":
            seed.last_read_at, seed.fail_count = now, 0
        elif status == "private":
            seed.last_read_at = now
            seed.scrape = False
            seed.note = seed.note or "صفحهٔ خصوصی است؛ خوانده نمی‌شود"
        elif status == "not_found":
            seed.fail_count += 1
            if seed.fail_count >= GONE_AFTER:
                seed.scrape = False
                seed.note = "صفحه پیدا نشد (نامِ کاربری را بررسی کنید)"
        elif status == "failed":
            seed.fail_count += 1
        seed.save()


def prune_snapshots(now=None) -> int:
    now = now or timezone.now()
    n, _ = IgPostSnapshot.objects.filter(at__lt=now - timedelta(days=KEEP_SNAPSHOTS_DAYS)).delete()
    return n


def apply_batch(store, batch: dict, run=None, rebuild: bool = True, add_pages: bool = True) -> dict:
    """Store a (raw) batch. Raises normalize.BatchError when it is not a usable batch. Returns the numbers."""
    clean = normalize.clean_batch(batch)
    now = timezone.now()
    read_at = _dt(clean["read_at"]) if clean.get("read_at") else now
    new = updated = 0
    touched: list[IgAccount] = []
    with transaction.atomic():
        by_name = {}
        for row in clean["accounts"]:
            by_name[row["username"]] = _upsert_account(row, now if clean.get("read_at") is None else min(read_at, now))
        for row in clean["posts"]:
            result = _upsert_post(by_name[row["account"]], row, now)
            new += result == "new"
            updated += result == "updated"
        touched = list(by_name.values())
        _apply_seed_statuses(store, clean["per_account"], now)
        # an account that was read but is not a seed yet (an import, a push) joins the store's watched pages
        for name in by_name if add_pages else ():
            IgSeed.objects.get_or_create(store=store, kind=IgSeed.Kind.ACCOUNT, value=name,
                                         defaults={"source": "import", "scrape": False, "note": "از فایلِ واردشده"})
        IgStoreConfig.objects.get_or_create(store=store)
    scored = engine.rescore_accounts(touched, now)
    engine.mark_dirty_for_accounts([a.username for a in touched])
    built = engine.rebuild_store(store, now) if rebuild else None
    prune_snapshots(now)
    return {"accounts": len(touched), "posts": len(clean["posts"]), "new": new, "updated": updated, "scored": scored,
            "stopped": clean.get("stopped"), "rebuilt": built, "not_read": clean.get("not_read") or []}
