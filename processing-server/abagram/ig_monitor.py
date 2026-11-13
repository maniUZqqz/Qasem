"""«رصدها»: the pages he watches. Each watched page is checked about twice a day (every `every_h` hours, give or take a few
minutes so the times never form a fixed pattern): the profile with its newest posts, the active story, and the story's
pictures and videos downloaded before Instagram drops them. What is new since the check before (posts, story items) is kept
as «تازه‌ها» until he has looked at it. The checks are queue tasks (ig_queue, kind 'check'); this module keeps the list and
works out what is new. State: data/monitors.json."""
import json
import random
import time

import ig_profile as pr
import ig_store
from ig_common import DATA

FILE = DATA / "monitors.json"
EVERY_H = 12          # hours between two checks of one page (twice a day)
JITTER_MIN = 40       # ... give or take this many minutes
NEWS_MAX = 300        # «تازه‌ها» kept per page
SEEN_MAX = 2000       # post codes / story ids remembered per page


def now():
    return time.time()


class Monitors:
    def __init__(self):
        self.data = self._read()

    def _read(self):
        data = pr.read_json(FILE, {}, backup=True)
        if not isinstance(data, dict):
            data = {}
        data.setdefault("pages", [])
        return data

    def _write(self):
        DATA.mkdir(parents=True, exist_ok=True)
        pr.write_atomic(FILE, json.dumps(self.data, ensure_ascii=False, indent=1).encode("utf-8"), backup=True)

    def get(self, username):
        return next((p for p in self.data["pages"] if p["username"] == username.lower()), None)

    def add(self, username, harvest=False):
        rec = self.get(username)
        if rec is None:
            rec = {"username": username.lower(), "added_at": int(now()), "enabled": True, "every_h": EVERY_H,
                   "next_at": 0, "last_check_at": None, "checks": 0, "harvest": bool(harvest),
                   "seen_posts": None, "seen_story": [], "news": []}
            self.data["pages"].append(rec)
        else:
            rec["enabled"], rec["harvest"] = True, rec.get("harvest") or bool(harvest)
        self._write()
        return rec

    def remove(self, username):
        self.data["pages"] = [p for p in self.data["pages"] if p["username"] != username.lower()]
        self._write()

    def update(self, username, **fields):
        rec = self.get(username)
        if rec:
            rec.update(fields)
            self._write()
        return rec

    def due(self):
        return [p for p in self.data["pages"] if p["enabled"] and p["next_at"] <= now()]

    def schedule(self, username):
        """The next check, every_h from now give or take a few minutes."""
        rec = self.get(username)
        if rec:
            rec["next_at"] = int(now() + rec.get("every_h", EVERY_H) * 3600 + random.uniform(-JITTER_MIN, JITTER_MIN) * 60)
            self._write()
        return rec

    def after_check(self, username):
        """Compare what was saved now with what the page had before: new posts and new story items become «تازه‌ها».
        The very first check of a page only learns its posts (nothing is "new" yet); a story is always news while it lasts.
        Returns (new posts, new story items)."""
        rec = self.get(username)
        if rec is None:
            return 0, 0
        u, t = rec["username"], int(now())
        posts = (ig_store.Section(DATA, "posts").load(u) or {}).get("items") or []
        reel = (ig_store.Section(DATA, "stories").load(u) or {}).get("reel") or {}
        news = []
        if rec["seen_posts"] is not None:
            known = set(rec["seen_posts"])
            news += [{"id": f"p:{p['code']}", "kind": "post", "code": p["code"], "post_kind": p.get("kind"), "at": p.get("taken_at"),
                      "found_at": t, "seen": False, "thumb": bool(p.get("has_thumb"))} for p in posts if p["code"] not in known]
        story_known = set(rec["seen_story"])
        news += [{"id": f"s:{i['id']}", "kind": "story", "item": i["id"], "type": i.get("type"), "at": i.get("taken_at"),
                  "expires_at": i.get("expires_at"), "found_at": t, "seen": False, "thumb": bool(i.get("has_thumb"))}
                 for i in reel.get("items") or [] if i.get("id") and i["id"] not in story_known]
        rec["seen_posts"] = ([p["code"] for p in posts] + [c for c in rec["seen_posts"] or [] if c not in {p["code"] for p in posts}])[:SEEN_MAX]
        rec["seen_story"] = ([i["id"] for i in reel.get("items") or [] if i.get("id")] + rec["seen_story"])[:SEEN_MAX]
        rec["news"] = (sorted(news, key=lambda n: n.get("at") or 0, reverse=True) + rec["news"])[:NEWS_MAX]
        rec["last_check_at"], rec["checks"] = t, rec.get("checks", 0) + 1
        self._write()
        return sum(n["kind"] == "post" for n in news), sum(n["kind"] == "story" for n in news)

    def mark_seen(self, username, ids=None):
        rec = self.get(username)
        if rec:
            for n in rec["news"]:
                if ids is None or n["id"] in ids:
                    n["seen"] = True
            self._write()
        return rec

    def listing(self):
        """Every watched page with what the app knows of it: the profile's numbers, the whole-list progress, unseen news."""
        out, store = [], pr.Store(DATA)
        for rec in self.data["pages"]:
            prof = store.load(rec["username"]) or {}
            f = ig_store.Section(DATA, "followers").load(rec["username"]) or {}
            out.append({**{k: v for k, v in rec.items() if k not in ("seen_posts", "seen_story", "news")},
                        "profile": {k: prof.get(k) for k in ("full_name", "followers", "following", "posts", "is_private", "is_verified",
                                                              "has_avatar", "fetched_at", "category")} if prof else None,
                        "story_at": (prof.get("more") or {}).get("story_at"),
                        "followers_read": len(f.get("items") or []), "followers_done": bool((f.get("harvest") or {}).get("done")),
                        "harvest_info": {k: (f.get("harvest") or {}).get(k) for k in ("started_at", "updated_at", "pages", "runs", "note")},
                        "unseen": {"post": sum(1 for n in rec["news"] if n["kind"] == "post" and not n["seen"]),
                                   "story": sum(1 for n in rec["news"] if n["kind"] == "story" and not n["seen"])},
                        "news": rec["news"][:24]})
        return out
