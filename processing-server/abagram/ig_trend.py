"""Trend reading (NMarketing node, 2026-11): the recent posts of ONE page with their numbers, taken from what the profile read
already saved. Pure functions, no browser and no request to Instagram.

It exists so the processing node never has to pull a whole dossier (followers, following, other people's profiles) just to learn
which posts of a page are doing well: this answer carries the page's public profile numbers and its posts, nothing else."""
from datetime import datetime, timezone
from pathlib import Path

import ig_profile
import ig_store
from ig_common import DATA

PROFILE_KEYS = ("username", "user_id", "full_name", "biography", "followers", "following", "posts", "is_private",
                "is_verified", "is_business", "category", "fetched_at")
POST_KEYS = ("code", "id", "kind", "taken_at", "caption", "hashtags", "likes", "comments", "views", "likes_hidden",
             "comments_disabled", "pinned", "items_count", "width", "height", "paid_partnership")
MAX_CAPTION = 2200      # Instagram's own limit for a caption
MAX_POSTS = 60


def _post(item):
    out = {k: item.get(k) for k in POST_KEYS}
    out["caption"] = (out.get("caption") or "")[:MAX_CAPTION]
    out["hashtags"] = [str(h) for h in (item.get("hashtags") or [])][:30]
    music = item.get("music")
    out["music"] = ({"kind": music.get("kind") or "", "title": str(music.get("title") or "")[:200],
                     "artist": str(music.get("artist") or "")[:200]} if isinstance(music, dict) else None)
    return out


def recent(username, root=DATA, limit=24, now=None):
    """{'username', 'profile', 'posts', 'fetched_at', 'age_s'} for a page that was read, newest post first; None when nothing
    is saved about it (the caller reads the page first)."""
    user = ig_profile.clean_username(username)
    if not user:
        return None
    root = Path(root)
    profile = ig_profile.Store(root).load(user)
    posts = ig_store.Section(root, "posts").load(user)
    if not profile and not posts:
        return None
    items = [p for p in ((posts or {}).get("items") or []) if isinstance(p, dict) and p.get("code") and p.get("taken_at")]
    items.sort(key=lambda p: p["taken_at"], reverse=True)
    limit = max(1, min(int(limit), MAX_POSTS))
    fetched = (posts or {}).get("fetched_at") or (profile or {}).get("fetched_at")
    return {"format": "nm-ig-page", "version": 1, "username": user,
            "profile": {k: (profile or {}).get(k) for k in PROFILE_KEYS},
            "posts": [_post(p) for p in items[:limit]], "post_count_saved": len(items),
            "fetched_at": fetched, "age_s": ig_profile.age_seconds({"fetched_at": fetched}, now) if fetched else None,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
