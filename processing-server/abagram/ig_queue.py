"""The queue: «استخراج کامل» of one person (every step, in chunks, waiting for the budget when it is full) and the
watch on a sent follow request (checked every `request_check_min`; when accepted: a notice, then a full extraction).
Each unit is an ordinary job (it shows in «فعالیت» and can be cancelled). One unit at a time, only while no job runs.
State lives in data/queue.json, so a restart of the site goes on where it was."""
import asyncio
import json
import os
import random
import time

import ig_accounts
import ig_health
import ig_lookup
import ig_monitor
import ig_process
import ig_profile as pr
import ig_request
import ig_store
from ig_budget import Budget
from ig_common import CHALLENGE_MSG, DATA, fa

FILE = DATA / "queue.json"
FULL = [("profile", "خواندن پروفایل"), ("posts", "پست‌ها"), ("stories", "استوری فعال"), ("highlights", "آیتم‌های هایلایت‌ها"),
        ("follow", "فالوورها و فالووینگ"), ("details", "کامنت و لایک‌کنندگان پست‌ها"), ("dl_posts", "دانلود عکس و ویدیوی پست‌ها"),
        ("dl_highlights", "دانلود هایلایت‌ها"), ("dl_story", "دانلود استوری")]
WATCH = [("request", "فرستادن درخواست فالو"), ("wait", "منتظر قبول")]
CHECK = [("profile", "پروفایل و پست‌های تازه"), ("stories", "استوری فعال"), ("dl_story", "دانلود استوری")]   # a watched page, twice a day
HARVEST = {"followers": "همهٔ فالوورها", "following": "همهٔ فالووینگ‌ها"}   # task 'harvest': whole lists, run after run (ig_harvest)
PROCESS = [("profiles", "خواندن پروفایل نامزدها")]   # task 'process': the candidates of «پردازش», one profile per unit
PROCESS_PAUSE = (20, 50)   # seconds between two candidates, on top of the page limits
HARVEST_ROOM = 5   # a harvest run needs room for this many pages (ig_harvest.MIN_ROOM)
NET_WAIT, NET_TRIES = 900, 8   # Instagram out of reach (no VPN, a dropped line): try again every 15 minutes, pause after 2 hours
# a whole list and «پردازش» never pause for the line (2026-11-03: the VPN was down 00:00–08:40 and the list waited for his «ادامه»):
# after those 2 hours, again every 30 minutes until it is back
NET_LONG = 1800
LINE_KINDS = ("harvest", "process")
HARVEST_HITS = 3
HARVEST_BACKOFF = [30, 60, 120, 240, 360, 360]   # minutes after the 1st, 2nd, … "wait" in a row: a whole list goes on, ever slower
HARVEST_RETRY = {"timeout", "other", "error", "unreadable", "no_reply", "browser_crash"}   # passing troubles: the whole list goes on later   # "wait" from Instagram this many times in a row pauses the task: he decides
GAP = 6            # seconds between two units of the queue
# The copy on another computer (his order 2026-11-08: «فقط بیام فایل رو اجرا کنم و ران بزنم»): what a whole-list read brings is scored
# and read by itself, with no «امتیازدهی» / «شروع خواندن» by hand. Off unless IGS_AUTO_PROCESS=1 or data/auto-process.on exists
# (the file: no change to the start script of a copy that is running).
AUTO_PROCESS = os.environ.get("IGS_AUTO_PROCESS") == "1" or (DATA / "auto-process.on").exists()
SOFT = {"private", "empty", "no_posts", "no_highlights", "no_media", "expired", "no_limit", "public", "unreadable", "other", "error", "timeout"}
STOP = {"session_invalid", "network", "browser", "cancelled", "automated", "disabled", "no_button", "challenge"}
# what a paused task says (the rest: «متوقف شد (kind)»)
STOP_NOTE = {"cancelled": "لغو شد؛ برای ادامه «ادامه» را بزن",
             "session_invalid": "از اینستاگرام بیرون افتاده‌ای؛ دوباره وارد شو، بعد «ادامه» را بزن",
             "challenge": CHALLENGE_MSG + "، بعد «ادامه» را بزن"}


def now():
    return time.time()


def signed_in():
    """Does the active account have a saved login? Without one the queue asks nothing of Instagram (an anonymous page view from a
    new machine is exactly what the first login should not be preceded by); its tasks simply wait for him to log in."""
    try:
        meta = json.loads(ig_accounts.meta_file().read_text("utf-8"))
        return bool(meta.get("username")) and not meta.get("lost_at")   # Instagram threw it out: wait for a new login (ig_login.mark_lost)
    except Exception:
        return False


def next_morning(hour=8):
    """Epoch seconds of the next HOUR:00 on the server's clock (Asia/Tehran)."""
    lt = time.localtime()
    today = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, 0, 0, 0, 0, -1))
    return today if today > now() + 3600 else time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, hour, 0, 0, 0, 0, -1))


def ip_page():
    return 12   # people on one page of a list (ig_people.PAGE)


def hhmm(ts):
    return fa(time.strftime("%H:%M", time.localtime(ts)))


class Queue:
    def __init__(self):
        self.data = self._read()
        self.last_end = 0.0
        self.job = None
        self.held = False        # true only for the few seconds a unit is being stopped to make room for a login of his other account
        self.monitors = ig_monitor.Monitors()

    # ---- storage ----
    def _read(self):
        data = pr.read_json(FILE, {}, backup=True)   # damaged after a power cut: its .bak, never an empty queue
        if not isinstance(data, dict):
            data = {}
        data.setdefault("tasks", [])
        data.setdefault("notices", [])
        for t in data["tasks"]:              # a unit cut off by a restart runs again, cleanly
            if t["state"] == "running":
                t["state"], t["run"] = "waiting", None
            t.pop("interrupted", None)
        return data

    def _write(self):
        DATA.mkdir(parents=True, exist_ok=True)
        pr.write_atomic(FILE, json.dumps(self.data, ensure_ascii=False, indent=1).encode("utf-8"), backup=True)

    def task(self, tid):
        return next((t for t in self.data["tasks"] if t["id"] == tid), None)

    def active(self, kind, username):
        return next((t for t in self.data["tasks"] if t["kind"] == kind and t["username"] == username.lower()
                     and t["state"] in ("waiting", "running", "paused")), None)

    def notice(self, kind, username, title, text=""):
        self.data["notices"].append({"id": f"n{int(now() * 1000)}", "at": int(now()), "kind": kind, "username": username,
                                     "title": title, "text": text, "read": False})
        self.data["notices"] = self.data["notices"][-60:]

    # ---- adding work ----
    def _new(self, kind, username, steps):
        stamp, taken = int(now() * 1000), {x["id"] for x in self.data["tasks"]}
        while f"t{stamp}" in taken:   # two tasks in the same millisecond (the watched pages' checks, made in one go): never one id
            stamp += 1
        t = {"id": f"t{stamp}", "kind": kind, "username": username.lower(), "state": "waiting",
             "created_at": int(now()), "updated_at": int(now()), "next_at": 0, "run": None, "note": "",
             "steps": [{"key": k, "title": title, "state": "idle", "note": "", "done": 0, "total": None} for k, title in steps]}
        self.data["tasks"].append(t)
        self.data["tasks"] = [x for x in self.data["tasks"] if x["state"] not in ("done", "failed", "cancelled")] + \
            [x for x in self.data["tasks"] if x["state"] in ("done", "failed", "cancelled")][-20:]
        self._write()
        return t

    def add_full(self, username):
        return self.active("full", username) or self._new("full", username, FULL)

    def add_watch(self, username):
        return self.active("watch", username) or self._new("watch", username, WATCH)

    def add_harvest(self, username, which):
        """A whole followers / following list (or both): one task per page, one step per list."""
        t = self.active("harvest", username)
        if t is None:
            return self._new("harvest", username, [(w, HARVEST[w]) for w in which])
        for w in which:
            if not self._step(t, w):
                t["steps"].append({"key": w, "title": HARVEST[w], "state": "idle", "note": "", "done": 0, "total": None})
        if t["state"] == "paused":
            t["state"], t["note"], t["next_at"] = "waiting", "", 0
        self._write()
        return t

    def add_process(self, source, which):
        """«پردازش» step 2: read the candidates of one list one by one (ig_process keeps who is left)."""
        t = self.active("process", source)
        if t is None:
            t = self._new("process", source, PROCESS)
        elif t["state"] == "paused":
            t["state"], t["note"], t["next_at"] = "waiting", "", 0
        t["which"], t["hits"] = which, 0
        self._write()
        return t

    def act(self, tid, action):
        t = self.task(tid)
        if not t:
            return None
        if action == "cancel" and t["state"] != "running":
            t["state"], t["note"] = "cancelled", "لغو شد"
        elif action == "pause" and t["state"] == "waiting":
            t["state"], t["note"] = "paused", "متوقف شد"
        elif action in ("resume", "now") and t["state"] in ("paused", "waiting"):
            if action == "resume":   # his «ادامه»: the counts of «wait» / failed opens start again
                t["hits"] = t["tries"] = t["stalls"] = 0
            t["state"], t["note"], t["next_at"] = "waiting", "", 0
        t["updated_at"] = int(now())
        self._write()
        return t

    def read_notices(self, ids=None):
        for n in self.data["notices"]:
            if ids is None or n["id"] in ids:
                n["read"] = True
        self._write()

    def summary(self):
        tasks = [t for t in self.data["tasks"] if t["state"] in ("waiting", "running", "paused")]
        recent = [t for t in self.data["tasks"] if t["state"] not in ("waiting", "running", "paused")][-5:]
        notes = self.data["notices"]
        pages = self.monitors.data["pages"]
        return {"tasks": tasks, "recent": recent, "unread": sum(1 for n in notes if not n["read"]), "notices": notes[-8:][::-1],
                "signed_in": signed_in(),
                "watched": [p["username"] for p in pages],   # «رصدها»: the pages watched (light: status is asked every few seconds)
                "watch_unseen": sum(1 for p in pages for n in p["news"] if not n["seen"])}

    # ---- what to do next ----
    @staticmethod
    def _step(t, key):
        return next((s for s in t["steps"] if s["key"] == key), None)

    def _plan(self, t):
        """(step key, mode, options, fresh) of the next unit, or None when the task is finished. Marks finished steps."""
        u, lim = t["username"], Budget(DATA).limits()
        sec = lambda name: ig_store.Section(DATA, name).load(u) or {}  # noqa: E731
        if t["kind"] == "watch":
            return ("request", "request", {}, False) if self._step(t, "request")["state"] != "done" else ("wait", "profile", {}, True)
        if t["kind"] == "process":
            s, which = self._step(t, "profiles"), t.get("which", "followers")
            fast = ig_lookup.ENABLED and not t.get("slow")       # the fast reader only when it is switched on
            batch = ig_process.next_candidates(u, which, 1)
            c = ig_process.counts(ig_process.get(u, which), mine=True)   # «تقسیم کار»: this system's share
            s["done"], s["total"] = c["done"] + c["failed"], c["total"]
            if not batch:
                s["state"] = "done"
                return None
            # ONE window reads them all, one after another (ig_browse); with the fast reader on, by the page's own query
            return "profiles", "browse", {"which": which, **({"fast": True} if fast else {})}, True
        if t["kind"] == "harvest":
            for s in t["steps"]:
                if s["state"] in ("done", "skipped", "failed"):
                    continue
                saved = sec(s["key"])
                s["done"], s["total"] = len(saved.get("items") or []), saved.get("total")
                if (saved.get("harvest") or {}).get("done"):
                    s["state"], s["note"] = "done", "اینستاگرام بیشتر از این نشان نمی‌دهد" if saved["harvest"].get("note") == "limited" else ""
                    continue
                return s["key"], "harvest", {"which": s["key"]}, False
            return None
        prof = pr.Store(DATA).load(u) or {}
        closed = prof.get("is_private") and not (prof.get("relation") or {}).get("following")
        for s in t["steps"]:
            k = s["key"]
            if s["state"] in ("done", "skipped", "failed"):
                continue
            if k == "profile":
                return k, "profile", {}, True
            if closed:
                s["state"], s["note"] = "skipped", "حساب خصوصی است و دنبالش نمی‌کنی"
                continue
            if k in ("posts", "stories", "follow"):
                return k, k, {}, False
            if k == "highlights":
                tray = [h["id"] for h in sec("highlights").get("items") or []]
                read = sec("reels").get("highlights") or {}
                todo = [i for i in tray if i not in read]
                s["total"], s["done"] = len(tray), len(tray) - len(todo)
                if todo:
                    return k, "highlights", {"ids": todo[: lim["highlights"]]}, False
                s["state"], s["note"] = ("done", "") if tray else ("skipped", "هایلایتی ندارد")
            elif k == "details":
                codes = [p["code"] for p in sec("posts").get("items") or []]
                have = sec("details").get("posts") or {}
                todo = [c for c in codes if c not in have]
                s["total"], s["done"] = len(codes), len(codes) - len(todo)
                if todo:
                    return k, "details", {"codes": todo[: lim["detail_posts"]]}, False
                s["state"], s["note"] = ("done", "") if codes else ("skipped", "پستی ندارد")
            elif k == "dl_posts":
                if sec("posts").get("items"):
                    return k, "download", {"target": "posts", "videos": True}, False
                s["state"], s["note"] = "skipped", "پستی ندارد"
            elif k == "dl_highlights":
                ids = list((sec("reels").get("highlights") or {}).keys())
                left = [i for i in ids if i not in s.get("ids_done", [])]
                s["total"], s["done"] = len(ids), len(ids) - len(left)
                if left:
                    return k, "download", {"target": "highlights", "ids": left[:10], "videos": True}, False
                s["state"], s["note"] = ("done", "") if ids else ("skipped", "هایلایتی خوانده نشده")
            elif k == "dl_story":
                if sec("stories").get("reel"):
                    return k, "download", {"target": "story", "videos": True}, False
                s["state"], s["note"] = "skipped", "استوری فعالی نبود"
        return None

    def _limit_notice(self, t):
        """A task waits because a limit is full or Instagram said wait: tell him once (he may switch account by hand)."""
        if any(n["kind"] == "limit" and n["username"] == t["username"] and not n["read"] for n in self.data["notices"]):
            return
        self.notice("limit", t["username"], f"@{t['username']}: سقف پر شد یا اینستاگرام گفت صبر کن", t.get("note") or "")

    def interrupt(self):
        """Make room for a login of another account. What runs now: nothing ('none'), a queue unit ('unit': it is stopped, keeps what
        it read, and the queue starts it again by itself after the login), or something he started by hand ('manual': left alone)."""
        job = self.job
        if job is None or not (job.busy or (job._task and not job._task.done())):
            return "none"
        t = self.task(getattr(job, "queued", None) or "")
        if t is None or t["state"] != "running":
            return "manual"
        t["interrupted"] = True
        self.held = True
        self._write()
        job.cancel()
        return "unit"

    def add_check(self, username):
        return self.active("check", username) or self._new("check", username, CHECK)

    def _watched(self):
        """A watched page whose time has come gets a check task (not while a full extraction of it is still going)."""
        for m in self.monitors.due():
            if not self.active("full", m["username"]):
                self.add_check(m["username"])
            self.monitors.schedule(m["username"])

    def tick(self):
        job = self.job
        if job is not None and job.busy and job.mode == "browse" and not getattr(job, "_yield", False) and self._harvest_due():
            job._yield = True   # the followers list is due: the one-window «پردازش» steps aside after this person (ig_browse)
        if job is None or job.busy or (job._task and not job._task.done()) or now() - self.last_end < GAP or self.held:
            return
        if not signed_in():
            return
        self._watched()
        due = [t for t in self.data["tasks"] if t["state"] == "waiting" and t["next_at"] <= now()]
        if not due:
            return
        t = min(due, key=lambda x: x["created_at"])
        unit = self._plan(t)
        if unit is None:
            return self._done(t)
        key, mode, opts, fresh = unit
        who = opts.pop("_who", None) or t["username"]     # a process unit reads one candidate, not the page itself
        try:
            job.start(mode, who, fresh=fresh, options={**opts, "_task": t["id"], "_step": key})
        except Exception:
            return
        t["state"], t["run"], t["note"], t["updated_at"] = "running", job.run, "", int(now())
        self._step(t, key)["state"] = "active"
        self._write()

    def _harvest_due(self):
        """A whole-list read waiting for its turn right now (his wish 2026-11-02: the followers go on while «پردازش» reads)."""
        return signed_in() and any(t["kind"] == "harvest" and t["state"] == "waiting" and t["next_at"] <= now() for t in self.data["tasks"])

    def _done(self, t):
        t["state"], t["updated_at"] = "done", int(now())
        if t["kind"] in ("check", "full") and self.monitors.get(t["username"]):
            posts, story = self.monitors.after_check(t["username"])
            if posts or story:
                what = "، ".join(x for x in (f"{fa(posts)} پست تازه" if posts else "", f"{fa(story)} استوری تازه" if story else "") if x)
                self.notice("monitor_new", t["username"], f"@{t['username']}: {what}", "در «رصدها» ببین.")
        if t["kind"] == "harvest":
            got = "، ".join(f"{s['title']}: {fa(s['done'])} نفر" for s in t["steps"])
            whole = all(s["state"] == "done" for s in t["steps"])
            self.notice("harvest_done", t["username"], f"فهرست کامل @{t['username']} خوانده شد" if whole
                        else f"خواندن فهرست @{t['username']} نیمه‌کاره ماند", got)
        if t["kind"] == "process":
            c = ig_process.counts(ig_process.get(t["username"], t.get("which", "followers")), mine=True)
            self.notice("process_done", t["username"], f"پردازش @{t['username']} تمام شد",
                        f"{fa(c['done'])} نامزد خوانده شد" + (f"، {fa(c['failed'])} نفر خوانده نشد" if c["failed"] else "") + ". نتیجه در «پردازش».")
        if t["kind"] == "full":
            failed = [s["title"] for s in t["steps"] if s["state"] == "failed"]
            self.notice("full_done", t["username"], f"استخراج کامل @{t['username']} تمام شد",
                        "مرحله‌های ناموفق: " + "، ".join(failed) if failed else "همهٔ مرحله‌ها انجام شد.")
        self._write()

    # ---- a unit ended ----
    def finished(self, s):
        self.last_end = now()
        ig_health.record(s)      # every job's end feeds the account-health log (monitoring tab)
        t = self.task(s.get("queued") or "")
        if not t or t["state"] != "running":
            return
        opts = s.get("options") or {}
        step = self._step(t, opts.get("_step"))
        kind = (s.get("outcome") or {}).get("kind")
        if t.pop("interrupted", None) and kind == "cancelled":
            # stopped to make room for a login: not a failure and not a pause — the same unit simply runs again afterwards
            t["run"], t["state"], t["updated_at"], t["next_at"], t["note"] = None, "waiting", int(now()), 0, ""
            if step and step["state"] == "active":
                step["state"] = "idle"
            self._write()
            return
        t["run"], t["state"], t["updated_at"] = None, "waiting", int(now())
        if t["kind"] == "process":
            return self._processed(t, step, s, kind)
        if s["state"] == "success":
            t["net"] = 0
            self._advance(t, step, s, opts)
        elif t["kind"] == "harvest" and kind in ("budget", "cooldown", "rate_limit"):
            # a full limit is normal for a whole list (what was read is saved); Instagram's "wait" several times in a row is not
            b, step["state"] = Budget(DATA), "idle"
            t["hits"] = t.get("hits", 0) + 1 if kind == "rate_limit" else 0
            # Instagram's "wait": a longer rest each time it says it again (30 min … 6 h); he asked for the whole list to go on by itself.
            # Only after six in a row (about 20 hours of "wait") it stops for him.
            rest = HARVEST_BACKOFF[min(t["hits"], len(HARVEST_BACKOFF)) - 1] * 60 if kind == "rate_limit" else 600
            t["next_at"] = max(b.free_at("page"), b.free_at("harvest", min(HARVEST_ROOM, b.limits()["harvests_hour"])), now() + rest) + 5
            self._limit_notice(t)
            if t["hits"] >= len(HARVEST_BACKOFF):
                t["state"], t["note"] = "paused", f"اینستاگرام {fa(t['hits'])} بار پشت سر هم گفت صبر کن؛ متوقف شد تا خودت «ادامه» بزنی"
            else:
                t["note"] = (f"اینستاگرام گفت صبر کن ({fa(t['hits'])} بار پشت سر هم)؛ " if kind == "rate_limit" else "سقف ساعتی پر شد؛ ") + "ادامه از ساعت " + hhmm(t["next_at"])
        elif t["kind"] == "harvest" and kind in HARVEST_RETRY:
            # a page that did not come up through a slow line is not the end of a whole list: again later, three times in a row at most
            t["tries"], step["state"] = t.get("tries", 0) + 1, "idle"
            if t["tries"] >= HARVEST_HITS and kind == "no_reply":
                self._next_morning(t)
            elif t["tries"] >= HARVEST_HITS:
                t["state"], t["note"] = "paused", f"صفحهٔ پیج {fa(t['tries'])} بار پشت سر هم درست باز نشد؛ متوقف شد تا خودت «ادامه» بزنی"
            elif kind == "no_reply":   # not even the first page of the list came: Instagram is holding the account back — two hours
                t["next_at"] = now() + 7200
                t["note"] = "اینستاگرام فهرست را نداد (این حساب الان محدود است)؛ تلاش دوباره ساعت " + hhmm(t["next_at"])
            else:
                t["next_at"] = now() + 900
                t["note"] = "صفحهٔ پیج درست باز نشد؛ تلاش دوباره ساعت " + hhmm(t["next_at"])
        elif kind in ("budget", "cooldown", "rate_limit"):
            self._limit_notice(t)
            b = Budget(DATA)
            # the unit may need more than one free slot: never try again sooner than 10 minutes (a refused start asks nothing of Instagram)
            t["next_at"] = max(b.free_at("page"), b.free_at("scroll"), now() + 600) + 5
            if step["key"] == "follow" and kind == "budget" and (s.get("outcome") or {}).get("shot"):   # it stopped half way: what was read is saved
                step["state"], step["note"] = "done", "تا جایی که سقف ساعتی اجازه داد خوانده شد"
                t["next_at"] = 0
            else:
                step["state"] = "idle"
                t["note"] = "منتظر جای خالی در بودجه تا ساعت " + hhmm(t["next_at"])
        elif kind == "network" and (t.get("net", 0) + 1 < NET_TRIES or t["kind"] in LINE_KINDS):
            t["net"] = t.get("net", 0) + 1
            step["state"], t["next_at"] = "idle", now() + (NET_WAIT if t["net"] < NET_TRIES else NET_LONG)
            t["note"] = "اینستاگرام در دسترس نیست (فیلترشکن روشن است؟)؛ تلاش دوباره ساعت " + hhmm(t["next_at"])
        elif kind in STOP:
            step["state"], t["state"] = "idle", "paused"
            if kind == "network":
                t["note"] = "دو ساعت است اینستاگرام در دسترس نیست؛ فیلترشکن را روشن کن و «ادامه» را بزن"
            t["note"] = STOP_NOTE.get(kind, f"متوقف شد ({kind})؛ مشکل را رفع کن و «ادامه» را بزن")
        elif kind == "not_found":
            step["state"], t["state"], t["note"] = "failed", "failed", "این صفحه در اینستاگرام پیدا نشد"
            self.notice("failed", t["username"], f"@{t['username']} پیدا نشد", "کار صف متوقف شد.")
        elif t["kind"] == "watch" and kind == "public":
            self._accepted(t, "این حساب عمومی است؛ درخواست لازم نبود")
        else:
            step["state"], step["note"] = "failed", kind or "error"
        if t["kind"] == "harvest" and AUTO_PROCESS:
            self._auto_process(t["username"], (step or {}).get("key") or "followers")
        self._write()

    def _auto_process(self, source, which):
        """After each run of a whole list (AUTO_PROCESS): everyone it has brought so far gets a score (run_rank keeps whoever was
        read before, his words and his lowest score) and a «پردازش» task reads them best first, in the list's rests."""
        try:
            if not (ig_store.Section(DATA, which).load(source) or {}).get("items"):
                return
            prev = ig_process.get(source, which) or {}
            ig_process.run_rank(source, which, prev.get("words") or [], prev.get("min_score") or 0)
            if not self.active("process", source) and ig_process.next_candidates(source, which, 1):
                self.add_process(source, which)
        except Exception:
            pass   # scoring is a help: a whole-list read never stops for it

    def _processed(self, t, step, s, kind):
        """One candidate of «پردازش» was read (or not). A person that cannot be read is marked and skipped; a full limit or
        Instagram's "wait" makes the task wait (three "wait"s in a row pause it); a stop (logged out, network) pauses it."""
        who, which, b = s.get("username") or "", t.get("which", "followers"), Budget(DATA)
        step["state"] = "idle"
        if s["state"] == "success":
            t["net"] = 0
        fast = (s.get("result") or {}).get("lookup")
        if fast:   # the fast reader: what it read and who could not be read count, however the run ended
            for name in fast.get("done") or []:
                ig_process.mark(t["username"], which, name, "done")
            for name, why in (fast.get("failed") or {}).items():
                ig_process.mark(t["username"], which, name, "failed", why)
        if s.get("mode") == "lookup" and kind == "no_query":
            t["slow"], t["next_at"] = True, now() + 30
            t["note"] = "خواندن سریع این بار نشد؛ پروفایل‌ها یکی‌یکی و کامل خوانده می‌شوند"
            return self._write()
        browse = s.get("mode") == "browse"   # one window for every candidate: it marks each person itself as it goes
        if fast and s["state"] == "success":
            t["hits"], t["tries"], t["next_at"] = 0, 0, now() + random.uniform(*PROCESS_PAUSE)
        elif browse and s["state"] == "success":   # the window read everyone there was: the next plan finds nobody and ends
            t["hits"], t["tries"], t["next_at"] = 0, 0, 0
        elif s["state"] == "success":
            ig_process.mark(t["username"], which, who, "done")
            t["hits"], t["next_at"] = 0, now() + random.uniform(*PROCESS_PAUSE)
        elif kind in ("budget", "cooldown", "rate_limit"):
            t["hits"] = t.get("hits", 0) + 1 if kind == "rate_limit" else 0
            # the fast reader has its own limit too (2026-11-03 21:08: its day was full and the window opened every 10 minutes for one page)
            room = b.free_at("lookup") if s.get("mode") == "lookup" or (browse and (s.get("options") or {}).get("fast")) else 0
            t["next_at"] = max(b.free_at("page"), room, now() + (1800 if kind == "rate_limit" else 600)) + 5
            self._limit_notice(t)
            if t["hits"] >= HARVEST_HITS:
                t["state"], t["note"] = "paused", f"اینستاگرام {fa(t['hits'])} بار پشت سر هم گفت صبر کن؛ متوقف شد تا خودت «ادامه» بزنی"
            else:
                t["note"] = ("اینستاگرام گفت صبر کن؛ " if kind == "rate_limit" else "سقف پر شد؛ ") + "ادامه از ساعت " + hhmm(t["next_at"])
            return self._write()
        elif kind in STOP and kind != "network":   # the line is no reason to stop «پردازش»: it tries again below
            t["state"], t["note"] = "paused", STOP_NOTE.get(kind, f"متوقف شد ({kind})؛ مشکل را رفع کن و «ادامه» را بزن")
            return self._write()
        elif kind == "network":
            t["net"] = t.get("net", 0) + 1
            t["next_at"] = now() + (NET_WAIT if t["net"] < NET_TRIES else NET_LONG)
            t["note"] = "اینستاگرام در دسترس نیست (فیلترشکن؟)؛ خودش ساعت " + hhmm(t["next_at"]) + " دوباره امتحان می‌کند"
            return self._write()
        elif (s.get("mode") == "lookup" or browse) and kind in HARVEST_RETRY:   # a passing trouble of the whole run: nobody is to blame
            t["tries"] = t.get("tries", 0) + 1
            if t["tries"] >= HARVEST_HITS:
                what = "خواندن پروفایل‌ها" if browse else "خواندن سریع"
                t["state"], t["note"] = "paused", f"{what} {fa(t['tries'])} بار پشت سر هم نشد؛ متوقف شد تا خودت «ادامه» بزنی"
                return self._write()
            t["next_at"] = now() + 900
        elif browse:   # any other end of the window: who was read is marked already; again in a while
            t["next_at"] = now() + 900
        else:   # not found, unreadable, any other answer about this one person: skip him, go on with the next
            ig_process.mark(t["username"], which, who, "failed", kind or "error")
            t["next_at"] = now() + random.uniform(*PROCESS_PAUSE)
        c = ig_process.counts(ig_process.get(t["username"], which), mine=True)
        step["done"], step["total"] = c["done"] + c["failed"], c["total"]
        t["note"] = f"{fa(step['done'])} از {fa(step['total'])} نامزد خوانده شد"
        self._write()

    def _next_morning(self, t):
        """Three sessions in a row cut off (or no list at all): Instagram holds this account back for the day (2026-10-29: after 300 pages
        in 32 min every list was cut to its first page). The list waits for the next morning by itself; after three such days it stops
        for him."""
        t["days"] = t.get("days", 0) + 1
        t["stalls"] = t["tries"] = 0
        if t["days"] > HARVEST_HITS:
            t["state"], t["note"] = "paused", "اینستاگرام سه روز پشت سر هم فهرست را کوتاه کرد؛ متوقف شد تا خودت «ادامه» بزنی"
            return
        t["next_at"] = next_morning()
        t["note"] = f"اینستاگرام امروز دیدن فهرست را برای این حساب محدود کرده؛ خودش ساعت {hhmm(t['next_at'])} فردا دوباره امتحان می‌کند"

    def _advance(self, t, step, s, opts):
        res = s.get("result") or {}
        if t["kind"] == "watch":
            return self._watch(t, step, res)
        if t["kind"] == "harvest":
            got = res.get("harvest") or {}
            before = step.get("done") or 0
            step["state"], step["done"], step["total"], t["hits"], t["tries"] = "idle", got.get("kept", step["done"]), got.get("total"), 0, 0
            stalled, moved = got.get("note") == "stalled", got.get("kept", 0) - before >= ip_page()
            # only a session cut off before it added anyone counts as «held back» (one that read people and then stopped does not)
            t["stalls"] = t.get("stalls", 0) + 1 if stalled and not moved else 0
            if moved:
                t["days"] = 0          # the list moved again: the days of «held back» start over
            if t["stalls"] >= HARVEST_HITS:
                self._next_morning(t)
            elif not got.get("done"):
                # a breather between two runs: held back (cut before anyone new) two hours — a new session at once only scrolled the same
                # first pages again (2026-10-29); cut after new people 10 min; a run that ended its chunk 5 min.
                t["next_at"] = now() + (7200 if t["stalls"] else 600 if stalled else 300)
                t["note"] = f"{fa(got.get('kept', 0))} نفر تا الان؛ نوبت بعد ساعت {hhmm(t['next_at'])}"
            return
        if step["key"] == "dl_highlights":
            step.setdefault("ids_done", []).extend(opts.get("ids") or [])
            step["state"] = "idle"            # the planner decides whether more are left
        elif step["key"] in ("highlights", "details"):
            step["state"] = "idle"
        else:
            step["state"] = "done"

    def _watch(self, t, step, res):
        every = Budget(DATA).limits()["request_check_min"] * 60
        if step["key"] == "request":
            state = (res.get("request") or {}).get("state")
            step["state"] = "done"
            if state == "following":
                return self._accepted(t, "این حساب را از قبل دنبال می‌کردی")
            t["next_at"] = now() + every
            t["note"] = "درخواست فرستاده شد؛ بررسی بعدی ساعت " + hhmm(t["next_at"])
            self._step(t, "wait")["state"] = "active"
            return
        rel = ((res.get("profile") or {}).get("relation")) or {}
        if rel.get("following"):
            return self._accepted(t, "درخواست قبول شد")
        if rel.get("requested") is False and rel.get("following") is False:
            t["state"], t["note"] = "done", "درخواست رد یا پس گرفته شد"
            self._step(t, "wait")["state"] = "failed"
            ig_request.save_request(t["username"], state="declined", checked_at=ig_request.now_iso())
            return self.notice("declined", t["username"], f"@{t['username']} درخواست را قبول نکرد", "درخواست دیگر در انتظار نیست.")
        t["next_at"] = now() + every
        t["note"] = "هنوز منتظر قبول؛ بررسی بعدی ساعت " + hhmm(t["next_at"])
        ig_request.save_request(t["username"], checked_at=ig_request.now_iso())

    def _accepted(self, t, why):
        t["state"], t["note"] = "done", why
        for s in t["steps"]:
            s["state"] = "done"
        ig_request.save_request(t["username"], state="following", accepted_at=ig_request.now_iso())
        self.notice("accepted", t["username"], f"@{t['username']} درخواستت را قبول کرد", "استخراج کامل این پیج خودکار شروع شد.")
        self.add_full(t["username"])

    async def loop(self, job):
        self.job = job
        job.on_finish = self.finished
        while True:
            await asyncio.sleep(3)
            try:
                self.tick()
            except Exception as e:      # never let the queue stop the site
                print("queue:", e)
