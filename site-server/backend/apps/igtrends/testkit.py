"""Synthetic data for the tests of apps.igtrends: invented pages and posts in Abagram's shapes. No real person, no real post."""
from __future__ import annotations

import time

from django.contrib.auth.models import User
from django.utils import timezone

from apps.stores.models import Store

NOW = 1_800_000_000          # a fixed «now» (epoch) for the pure functions


def make_store(name="باشگاه آزمایشی", owner="ig-owner", business_type="gym"):
    user = User.objects.create_user(owner, password="x")
    return user, Store.objects.create(owner=user, name=name, business_type=business_type)


def abagram_post(code, age_h=10, kind="reel", likes=900, comments=40, views=15000, caption="تمرین سینه در خانه #بدنسازی #تمرین_در_خانه",
                 music=None, now=None, **kw):
    now = now or int(time.time())
    p = {"code": code, "id": "9" + str(abs(hash(code)) % 10 ** 8), "kind": kind, "taken_at": now - int(age_h * 3600), "caption": caption,
         "hashtags": [w[1:] for w in caption.split() if w.startswith("#")], "mentions": ["someone_else"], "likes": likes, "comments": comments,
         "views": views, "likes_hidden": False, "comments_disabled": False, "pinned": False, "music": music, "items_count": 1,
         "width": 1080, "height": 1920, "paid_partnership": False, "thumb": "https://example.invalid/t.jpg"}
    p.update(kw)
    return p


def abagram_profile(username, followers=20000, **kw):
    p = {"username": username, "user_id": "700" + str(len(username)), "full_name": "صفحهٔ ساختگی", "biography": "نمونه", "followers": followers,
         "following": 100, "posts": 200, "is_private": False, "is_verified": False, "is_business": True, "category": "Gym",
         "fetched_at": "2026-11-10T08:00:00+00:00"}
    p.update(kw)
    return p


def abagram_export(username, posts, followers=20000, **profile):
    """An «abagram-page» export (format of ig_export.py) - including a followers list that must never be read."""
    return {"format": "abagram-page", "version": 1, "username": username, "exported_by": "tester", "exported_at": "2026-11-10T09:00:00+00:00",
            "profile": abagram_profile(username, followers, **profile),
            "sections": {"posts": {"items": posts, "reason": None, "fetched_at": "2026-11-10T08:30:00+00:00"}, "highlights": None, "similar": None,
                         "details": None, "stories": None, "reels": None},
            "files": None,
            "followers": {"total": 2, "items": [{"username": "follower_a", "profile": {"username": "follower_a", "biography": "PRIVATE-FOLLOWER-DATA"}},
                                                 {"username": "follower_b"}], "with_profile": 1},
            "following": None}


def node_batch(store_id, run_id=None, pages=None, stopped=None, now=None):
    """What `ig.scrape` writes. pages: {username: [post dict (abagram_post shape)]}."""
    now = now or int(time.time())
    accounts, posts, per = [], [], {}
    for name, rows in (pages or {}).items():
        accounts.append({"username": name, "ig_user_id": "1", "full_name": "x", "biography": "", "followers": 20000, "following": 10, "posts_count": 100,
                         "is_verified": False, "is_private": False, "is_business": True, "category": "Gym", "fetched_at": now})
        for r in rows:
            posts.append(dict(r, account=name))
        per[name] = {"status": "ok", "posts": len(rows)}
    return {"format": "nm-ig-batch", "version": 1, "source": "abagram-node", "node": "TEST", "read_at": now, "store_id": store_id, "run_id": run_id,
            "accounts": accounts, "posts": posts, "per_account": per, "stopped": stopped, "not_read": []}


def niche_pages(now=None):
    """Three pages in one niche: two make «home workout» reels (one of them breaking out), one makes diet carousels."""
    now = now or int(time.time())
    return {
        "fit_home_a": [
            abagram_post("HA1", 6, "reel", 4200, 160, 90000, "تمرین در خانه بدون وسیله؛ ۳ حرکت برای شکم #تمرین_در_خانه #تمرین_شکم", now=now,
                         music={"kind": "music", "title": "آهنگ اول", "artist": "هنرمند"}),
            abagram_post("HA2", 30, "reel", 700, 20, 12000, "تمرین پا در خانه #تمرین_در_خانه #تمرین_پا", now=now),
            abagram_post("HA3", 60, "reel", 650, 25, 11000, "تمرین سینه در خانه #تمرین_در_خانه", now=now),
            abagram_post("HA4", 100, "photo", 600, 18, None, "صبحانهٔ سالم #رژیم_غذایی", now=now),
            abagram_post("HA5", 140, "reel", 720, 30, 13000, "تمرین بازو در خانه #تمرین_در_خانه", now=now),
        ],
        "fit_home_b": [
            abagram_post("HB1", 12, "reel", 3000, 90, 60000, "تمرین در خانه با کش؛ چرا هیچ‌کس این حرکت را درست نمی‌زند؟ #تمرین_در_خانه", now=now,
                         music={"kind": "music", "title": "آهنگ اول", "artist": "هنرمند"}),
            abagram_post("HB2", 40, "reel", 500, 12, 8000, "حرکات کششی بعد از تمرین #حرکات_کششی", now=now),
            abagram_post("HB3", 80, "reel", 480, 15, 7500, "تمرین در خانه برای مبتدی‌ها #تمرین_در_خانه", now=now),
            abagram_post("HB4", 120, "reel", 510, 10, 8200, "تمرین شانه #تمرین_شانه", now=now),
        ],
        "diet_coach": [
            abagram_post("DC1", 20, "album", 900, 40, None, "۵ اشتباه رایج در رژیم غذایی #رژیم_غذایی #کاهش_وزن", now=now, items_count=6),
            abagram_post("DC2", 70, "album", 880, 35, None, "برنامه غذایی هفتگی #رژیم_غذایی", now=now, items_count=5),
            abagram_post("DC3", 110, "album", 910, 38, None, "پروتئین کافی بخورید #پروتئین #رژیم_غذایی", now=now, items_count=4),
        ],
    }
