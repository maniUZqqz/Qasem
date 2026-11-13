"""Synthetic data in Abagram's own shapes (NMarketing node tests). Invented pages: no real person, no real post."""
import json
import time
from pathlib import Path


def profile(username="demo_fit_page", **kw):
    base = {"username": username, "user_id": "9001", "full_name": "صفحهٔ آزمایشیِ تناسب اندام", "biography": "نمونهٔ ساختگی",
            "followers": 52000, "following": 120, "posts": 340, "is_private": False, "is_verified": False, "is_business": True,
            "category": "Gym/Physical Fitness Center", "fetched_at": "2026-11-10T08:00:00+00:00"}
    base.update(kw)
    return base


def post(code, kind="reel", age_h=10, likes=900, comments=40, views=15000, caption="تمرین سینه در خانه #بدنسازی #تمرین_در_خانه",
         music=None, now=None, **kw):
    now = now or int(time.time())
    p = {"code": code, "id": "1" + "".join(str(ord(c) % 10) for c in code), "kind": kind, "url": f"/{'reel' if kind == 'reel' else 'p'}/{code}/",
         "taken_at": now - age_h * 3600, "caption": caption, "hashtags": [w[1:] for w in caption.split() if w.startswith("#")],
         "mentions": ["someone_else"], "likes": likes, "comments": comments, "views": views, "likes_hidden": False,
         "comments_disabled": False, "pinned": False, "location": None, "tagged": [], "music": music, "coauthors": [], "sponsors": [],
         "paid_partnership": False, "alt": None, "items": [{"type": "video"}], "items_count": 1, "thumb": "https://example.invalid/t.jpg",
         "width": 1080, "height": 1920, "fb_likes": None, "fb_comments": None}
    p.update(kw)
    return p


def write_page(root, username, posts, prof=None):
    """Save a page the way the engine does (profiles/p_<name>.json and posts/p_<name>.json)."""
    root = Path(root)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "posts").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / f"p_{username}.json").write_text(json.dumps(prof or profile(username), ensure_ascii=False), "utf-8")
    (root / "posts" / f"p_{username}.json").write_text(json.dumps({"items": posts, "reason": None, "fetched_at": "2026-11-10T08:00:00+00:00"},
                                                                  ensure_ascii=False), "utf-8")
