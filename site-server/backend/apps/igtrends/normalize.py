"""One shape for everything that arrives: the node's batch, a pushed batch and an Abagram «abagram-page» JSON export.

The batch format ("nm-ig-batch", version 1) is what the node job `ig.scrape` writes:

    {"format": "nm-ig-batch", "version": 1, "read_at": iso, "store_id": 34, "run_id": 5,
     "accounts": [{"username", "ig_user_id", "full_name", "biography", "followers", "following", "posts_count", "is_verified",
                   "is_private", "is_business", "category", "fetched_at"}],
     "posts": [{"account", "code", "id", "kind", "taken_at"(epoch), "caption", "hashtags", "likes", "comments", "views",
                "likes_hidden", "comments_disabled", "pinned", "music": {"kind","title","artist"}|null, "items_count",
                "width", "height", "paid_partnership"}],
     "per_account": {username: {"status": "ok|private|not_found|failed|stopped", "posts": n}}, "stopped": {"code","message"}|null}

Everything is cleaned here (types, lengths, limits); nothing downstream trusts the sender.
Abagram's export also carries the followers/following of the page and their own profiles: that part is **never read**.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import textproc

FORMAT, VERSION = "nm-ig-batch", 1
EXPORT_FORMAT = "abagram-page"
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{2,40}$")
MAX_ACCOUNTS, MAX_POSTS, MAX_CAPTION = 200, 6000, 2200


class BatchError(ValueError):
    """The sender's data is not a batch / an export we can read; the message is shown to the person who sent it (Persian)."""


def _int(value, lo=0, hi=10 ** 13):
    if isinstance(value, bool) or value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def _text(value, limit):
    return str(value or "")[:limit]


def to_epoch(value):
    """Epoch seconds from an epoch number or an ISO time; None when it is neither."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 10 ** 11:                                     # milliseconds
            v /= 1000.0
        return int(v) if 946684800 <= v <= 4102444800 else None
    if isinstance(value, str) and value:
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp())
    return None


def clean_account(raw: dict) -> dict | None:
    name = str((raw or {}).get("username") or "").strip().lstrip("@").lower()
    if not USERNAME_RE.match(name):
        return None
    return {"username": name, "ig_user_id": _text(raw.get("ig_user_id") or raw.get("user_id"), 30),
            "full_name": _text(raw.get("full_name"), 120), "biography": _text(raw.get("biography"), 600),
            "followers": _int(raw.get("followers")), "following": _int(raw.get("following")),
            "posts_count": _int(raw.get("posts_count") if raw.get("posts_count") is not None else raw.get("posts"), 0, 10 ** 9),
            "is_verified": bool(raw.get("is_verified")), "is_private": bool(raw.get("is_private")),
            "is_business": bool(raw.get("is_business")), "category": _text(raw.get("category"), 80),
            "fetched_at": to_epoch(raw.get("fetched_at"))}


def clean_post(raw: dict, default_account: str = "") -> dict | None:
    code = str((raw or {}).get("code") or "").strip()
    name = str(raw.get("account") or default_account or "").strip().lstrip("@").lower()
    taken = to_epoch(raw.get("taken_at") if raw.get("taken_at") is not None else raw.get("taken_iso"))
    if not CODE_RE.match(code) or not USERNAME_RE.match(name) or taken is None:
        return None
    caption = _text(raw.get("caption"), MAX_CAPTION)
    tags = raw.get("hashtags") if isinstance(raw.get("hashtags"), list) else []
    tags = [textproc.normalize(str(t)).strip("_") for t in tags[:30]] or textproc.hashtags(caption)
    music = raw.get("music") if isinstance(raw.get("music"), dict) else None
    if music and not (music.get("title") or music.get("artist")):
        music = None
    return {"account": name, "code": code, "id": _text(raw.get("id"), 30), "kind": _text(raw.get("kind"), 12).lower(), "taken_at": taken,
            "caption": caption, "hashtags": [t for t in tags if t][:30], "likes": _int(raw.get("likes")), "comments": _int(raw.get("comments")),
            "views": _int(raw.get("views")), "likes_hidden": bool(raw.get("likes_hidden")), "comments_disabled": bool(raw.get("comments_disabled")),
            "pinned": bool(raw.get("pinned")), "items_count": _int(raw.get("items_count"), 1, 100) or 1,
            "width": _int(raw.get("width"), 1, 20000), "height": _int(raw.get("height"), 1, 20000),
            "paid_partnership": bool(raw.get("paid_partnership")),
            "music": ({"kind": _text(music.get("kind"), 10), "title": _text(music.get("title"), 200), "artist": _text(music.get("artist"), 200)}
                      if music else None)}


def clean_batch(batch: dict) -> dict:
    """Validate and clean a nm-ig-batch. Raises BatchError (Persian) when it is not one."""
    if not isinstance(batch, dict) or batch.get("format") != FORMAT:
        raise BatchError("این فایل/داده قالبِ «nm-ig-batch» ندارد.")
    if _int(batch.get("version"), 1, 99) != VERSION:
        raise BatchError("نسخهٔ قالب پشتیبانی نمی‌شود.")
    accounts_raw, posts_raw = batch.get("accounts") or [], batch.get("posts") or []
    if not isinstance(accounts_raw, list) or not isinstance(posts_raw, list):
        raise BatchError("بخش‌های accounts و posts باید فهرست باشند.")
    if len(accounts_raw) > MAX_ACCOUNTS or len(posts_raw) > MAX_POSTS:
        raise BatchError("بستهٔ داده خیلی بزرگ است (بیشینه %d صفحه و %d پست)." % (MAX_ACCOUNTS, MAX_POSTS))
    accounts, seen = [], set()
    for raw in accounts_raw:
        acc = clean_account(raw) if isinstance(raw, dict) else None
        if acc and acc["username"] not in seen:
            seen.add(acc["username"])
            accounts.append(acc)
    posts, codes = [], set()
    for raw in posts_raw:
        post = clean_post(raw) if isinstance(raw, dict) else None
        if post and post["code"] not in codes and post["account"] in seen:
            codes.add(post["code"])
            posts.append(post)
    per_account = {}
    if isinstance(batch.get("per_account"), dict):
        for name, row in list(batch["per_account"].items())[:MAX_ACCOUNTS * 2]:
            name = str(name).strip().lstrip("@").lower()
            if USERNAME_RE.match(name) and isinstance(row, dict):
                per_account[name] = {"status": _text(row.get("status"), 12), "posts": _int(row.get("posts")) or 0}
    stop = batch.get("stopped")
    stop = {"code": _text(stop.get("code"), 20), "message": _text(stop.get("message"), 300)} if isinstance(stop, dict) else None
    return {"format": FORMAT, "version": VERSION, "read_at": to_epoch(batch.get("read_at")), "store_id": _int(batch.get("store_id"), 1, 10 ** 9),
            "run_id": _int(batch.get("run_id"), 1, 10 ** 9), "accounts": accounts, "posts": posts, "per_account": per_account, "stopped": stop,
            "not_read": [str(n).lower() for n in (batch.get("not_read") or [])[:MAX_ACCOUNTS] if USERNAME_RE.match(str(n))],
            "node": _text(batch.get("node"), 60)}


def from_abagram_page(doc: dict) -> dict:
    """An Abagram «abagram-page» export (one page: profile + posts + a lot we ignore) as a batch."""
    if not isinstance(doc, dict) or doc.get("format") != EXPORT_FORMAT:
        raise BatchError("این فایل خروجیِ آباگرام (قالبِ «abagram-page») نیست.")
    if _int(doc.get("version"), 1, 99) != 1:
        raise BatchError("نسخهٔ قالبِ فایلِ آباگرام پشتیبانی نمی‌شود.")
    profile = doc.get("profile") if isinstance(doc.get("profile"), dict) else {}
    name = str(doc.get("username") or profile.get("username") or "").strip().lstrip("@").lower()
    if not USERNAME_RE.match(name):
        raise BatchError("نامِ صفحه در فایل درست نیست.")
    sections = doc.get("sections") if isinstance(doc.get("sections"), dict) else {}
    posts_sec = sections.get("posts") if isinstance(sections.get("posts"), dict) else {}
    items = posts_sec.get("items") if isinstance(posts_sec.get("items"), list) else []
    account = clean_account(dict(profile, username=name)) or {"username": name}
    read_at = to_epoch(posts_sec.get("fetched_at")) or to_epoch(profile.get("fetched_at")) or to_epoch(doc.get("exported_at"))
    rows = []
    for raw in items[:MAX_POSTS]:
        if isinstance(raw, dict):
            row = clean_post(raw, name)
            if row:
                rows.append(row)
    return {"format": FORMAT, "version": VERSION, "read_at": read_at, "accounts": [account], "posts": rows,
            "per_account": {name: {"status": "private" if account.get("is_private") else "ok", "posts": len(rows)}}, "stopped": None,
            "source": EXPORT_FORMAT}


def merge_batches(batches: list[dict]) -> dict:
    """Several one-page batches as one (the import of many files at once)."""
    out = {"format": FORMAT, "version": VERSION, "read_at": None, "accounts": [], "posts": [], "per_account": {}, "stopped": None}
    stamps = []
    for b in batches:
        out["accounts"] += b["accounts"]
        out["posts"] += b["posts"]
        out["per_account"].update(b.get("per_account") or {})
        if b.get("read_at"):
            stamps.append(b["read_at"])
    out["read_at"] = max(stamps) if stamps else None
    return out
