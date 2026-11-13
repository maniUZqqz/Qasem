"""«پردازش» step 2 in ONE browser window (his design, 2026-11-02): the window opens once, the candidates are read one after another
in score order, and it closes only at the end, on a logout or on his «لغو». A mixin for LoginJob, job mode 'browse'.
Each next person is opened inside the open page by the app's own router (only that profile's data is asked, the page itself is
not loaded again); when the router does not take it, the same window opens the address. No search box: searching a name would
send search requests on top of the same profile request. Only what «پردازش» needs is kept — the profile and its avatar; the
pictures of posts and highlights are not fetched. Everyone counts against the page limits (30 an hour, 150 a day)."""
import asyncio
import random
import re
import time

import ig_detect as d
import ig_process
import ig_profile as pr
import ig_store
from ig_budget import Budget, Stop
from ig_common import BASE, DATA, Fail, fa, ltr
from ig_harvest import HOUR_READ, HOUR_REST, RE_PICS, SNAP_EVERY, UNIT, clock_fa
from ig_lookup import JS_POST, form_for, node_name

PAUSE = (20.0, 50.0)        # seconds between two people (as the queue waited between two single reads before)
INAPP_WAIT = 12             # seconds the app's router has to show the next profile; then the window opens the address
RELOAD_EVERY = 40           # people opened inside the page before one is opened by its address (a fresh page, a light memory)
HOLD_MAX = 65 * 60          # the hour's limit full: the window waits for room; the day's limit ends the job (the queue goes on later)
WAIT_REST = 30              # minutes, window open, after Instagram's «wait»; a second «wait» in a row ends the job
TRIES_ONE = 2               # a person that does not come up (network, timeout) this many times is marked and skipped
LINE_LOST = 3               # people in a row lost to the line: it is the line (2026-11-03 00:00–08:40 the VPN was down and 170
                            # were marked one after another) — the job ends, the queue tries again in a while, they come again
SKIP = ("not_found", "unreadable", "private", "no_link", "other")   # an answer about this one person: mark him, go on
# the fast way (IGS_FAST_PROFILES=1, his order 2026-11-02): after the first person, each one is asked by the page's own profile
# query and his numeric id — one request instead of a whole page; the same fields (2026-11-02: the web page itself sends no
# phone or e-mail either). This many people in a row with no readable reply and the window goes on the page way.
FAST_MISSES = 3
RE_WAIT = re.compile(r"feedback_required|wait a few minutes|try again later|spam", re.I)
RE_LOGIN = re.compile(r"login_required|checkpoint_required|challenge_required", re.I)
if not BASE.startswith("https://www.instagram.com"):   # the mock site in the tests: same steps, no waiting
    PAUSE, INAPP_WAIT, HOLD_MAX = (0.05, 0.1), 3, 0

# the app's own router: a new history entry and the event it listens to for back/forward — no page load
JS_INAPP = """(path) => {
  history.pushState(null, "", path);
  dispatchEvent(new PopStateEvent("popstate", {state: null}));
  return location.pathname;
}"""


class BrowseReader:
    async def _browse(self, source, proxy, options):
        which = options.get("which") if options.get("which") in ig_process.WHICH else "followers"
        budget, store = Budget(DATA), pr.Store(DATA)
        budget.check("page")   # before any browser opens: a full hour, a full day or the pause after «wait» stops the job here
        done, failed, tries = [], {}, {}
        self.result = {"browse": {"done": done, "failed": failed}}   # filled as it goes: a stop keeps it
        self.say("خواندن پروفایل‌ها در یک پنجره: مرورگر یک بار باز می‌شود و نامزدها به ترتیب امتیاز یکی‌یکی خوانده می‌شوند")
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab(r)))
        fast, self._query = bool(options.get("fast")), None
        if fast:   # the first profile opened teaches the page's own profile query (ig_lookup), the next ones are asked by it
            self._ctx.on("response", lambda r: self._spawn(self._grab_query(r)))
        await self._ctx.route(RE_PICS, self._no_picture)   # the pictures on each profile page are never read here
        self._crashed = False
        self._page.on("crash", lambda _p: setattr(self, "_crashed", True))
        opened, inside, by_router, by_query, misses, waits, snapped = 0, 0, 0, 0, 0, 0, 0.0
        self._read_since, self._yield, self._lost = time.time(), False, 0
        while not self._yield:
            # one lost to the line comes again later, not again in this window
            batch = [b for b in ig_process.next_candidates(source, which, len(failed) + 1) if b["username"] not in failed][:1]
            if not batch:
                break
            name = batch[0]["username"]
            if self._crashed:
                await self._browse_reopen()
                inside = RELOAD_EVERY   # the new tab is not on Instagram yet: the next one by its address
            quick = fast and opened and self._query is not None and batch[0].get("id") and misses < FAST_MISSES
            await self._browse_room(budget, "lookup" if quick else "page")
            if time.time() - snapped >= SNAP_EVERY * UNIT:   # a fresh picture of the window every few minutes
                snapped = time.time()
                await self._snap()
            if opened and time.time() - self._read_since >= HOUR_READ * UNIT:
                self.say(f"استراحتِ ساعتی تا فشار روی حساب کم شود؛ پنجره باز می‌ماند و ساعت "
                         f"{clock_fa(time.time() + HOUR_REST * UNIT)} ادامه می‌دهد", "warn")
                await self._browse_sleep(HOUR_REST * UNIT)
                self._read_since = time.time()
            elif opened:
                await self._browse_sleep(random.uniform(*PAUSE))
            if self._yield:   # the followers list is due: step aside before the next person
                break
            try:
                merged = await self._browse_fast(batch[0]) if quick else None
                if merged is not None:
                    how, misses = "query", 0
                else:
                    if quick:   # no readable reply by the query: this one as a page; a few in a row and the page way stays
                        misses += 1
                        if misses == FAST_MISSES:
                            self.say("خواندن سریع چند بار پشت سر هم جواب خوانا نداد؛ از این‌جا پروفایل‌ها با باز کردن صفحه خوانده می‌شوند", "warn")
                        await self._browse_room(budget, "page")
                    how = await self._browse_open(name, opened and inside < RELOAD_EVERY)
                    merged = await self._read_page(name)
            except Fail as f:
                waits = await self._browse_trouble(f, source, which, name, waits, tries, failed)
                opened += 1
                continue
            except Exception:
                if not self._crashed:
                    raise
                continue   # the page crashed while he was read: the top of the loop opens a new tab, he comes again
            inside = inside + 1 if how == "inside" else 0 if how == "address" else inside
            by_router, by_query = by_router + (how == "inside"), by_query + (how == "query")
            opened, waits, self._lost = opened + 1, 0, 0
            rec = await self._browse_keep(store, merged)
            ig_process.mark(source, which, name, "done")
            done.append(name)
            if rec["username"].lower() != name.lower():
                self.say(f"{ltr('@' + name)} یوزرنیمش را عوض کرده: {ltr('@' + rec['username'])}")
            if len(done) % 5 == 0:
                c = ig_process.counts(ig_process.get(source, which), mine=True)
                ways = f"{fa(by_query)} تا سریع، " if fast else ""
                self.say(f"{fa(len(done))} پروفایل در این پنجره خوانده شد ({ways}{fa(by_router)} تا داخلِ همان صفحه)؛ "
                         f"{fa(c['done'] + c['failed'])} از {fa(c['total'])} نامزد", "ok")
        self.step("read", "done")
        self.step("save", "done")
        if self._yield:
            self.result["browse"]["yielded"] = True
            self.say(f"نوبتِ خواندنِ فالوورها رسید؛ این پنجره بعد از {fa(len(done))} نفر کنار می‌رود و بعد از آن از همین‌جا ادامه می‌دهد", "ok")
        else:
            self.say(f"همهٔ نامزدها خوانده شد: {fa(len(done))} نفر در این پنجره" + (f"، {fa(len(failed))} نفر خوانده نشد" if failed else ""), "ok")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.5)
        await self.close()
        self.state = "success"

    async def _browse_sleep(self, seconds):
        """A rest that ends early when the whole followers list is due (the queue sets _yield): the window then steps aside after
        this person, the list reads, and «پردازش» goes on from the same place afterwards (his wish 2026-11-02: both go on)."""
        end = time.time() + seconds
        while time.time() < end and not getattr(self, "_yield", False):
            await asyncio.sleep(min(5.0, max(0.0, end - time.time())))

    def _browse_want(self, name):
        """Forget the last person's replies and listen for this one's (ProfileReader keeps the replies that name the wanted user)."""
        self._reset_reader()
        self._want, self._nav_status = name.lower(), None
        self._said = re.compile(r'"username"\s*:\s*"' + re.escape(self._want) + '"')

    async def _inapp(self, name):
        """The app's own router to /name/. True once the page header shows that very person (so nothing of the last profile
        is read into this one) within INAPP_WAIT seconds; False and nothing spent otherwise."""
        try:
            await self._page.evaluate(JS_INAPP, f"/{name}/")
        except Exception:
            return False
        loop = asyncio.get_event_loop()
        end = loop.time() + INAPP_WAIT
        while loop.time() < end:
            await asyncio.sleep(0.5)
            try:
                dom = await self._page.evaluate(d.JS_PROFILE, name) or {}
            except Exception:
                return False
            if (dom.get("username") or "").strip().lower() == name.lower() and dom.get("stats"):
                Budget(DATA).spend("page")
                return True
        return False

    async def _browse_open(self, name, inside):
        """One person's profile in the open window: inside the page when allowed, else (or when the router did not take it)
        by its address — the same checks as any profile read (logged out, the remembered-account page, a slow line)."""
        self._browse_want(name)
        if inside and await self._inapp(name):
            return "inside"
        self._browse_want(name)   # the router's replies, if any, belong to no one now
        await self._open_profile(name)
        return "address"

    async def _browse_fast(self, person):
        """One person by the page's own profile query, sent from inside the open page with his numeric id: the merged profile,
        or None when the reply carries no readable profile (he is then opened as a page). «wait» and «log in again» raise."""
        q = self._query
        r = await self._page.evaluate(JS_POST, [q["url"], q["headers"], form_for(q["form"], person)]) or {}
        Budget(DATA).spend("lookup")
        status, text = r.get("status"), r.get("text") or ""
        if status == 429 or RE_WAIT.search(text[:3000]):
            raise Fail("rate_limit", "اینستاگرام به خواندن سریع گفت صبر کن", detail={"http": status})
        if RE_LOGIN.search(text[:3000]):
            raise Fail("session_invalid", "اینستاگرام برای ادامه دوباره ورود خواست", detail={"http": status})
        name = node_name(text, person["id"]) or person["username"]
        merged = pr.merge(name, pr.from_api([text], name), {}, {})
        self._posts = []
        return merged if status == 200 and pr.readable(merged) else None

    async def _browse_keep(self, store, merged):
        """Only what «پردازش» needs: the profile with its avatar (one picture). The posts the page carried are kept without their
        pictures, and never over a list read before; highlights and similar accounts are left to a full read of that page."""
        rec = store.save(pr.build(merged), await self._download(merged.get("avatar")))
        if self._posts:
            posts = ig_store.Section(DATA, "posts")
            if not (posts.load(rec["username"]) or {}).get("items"):
                posts.save(rec["username"], {"items": [dict(p, has_thumb=False) for p in self._posts], "reason": None})
        return rec

    async def _browse_room(self, budget, kind="page"):
        """The limits of this kind of read (a page, or a fast one): an hour's limit full waits with the window open; a full day
        (or the pause after «wait») ends the job — the queue goes on when there is room, and meanwhile the whole-list read can
        have its turn."""
        try:
            budget.check(kind)
        except Stop as stop:
            at = budget.free_at(kind)   # the pause after «wait» counts in it too
            if at - time.time() > HOLD_MAX:
                raise
            why = "اینستاگرام گفته بود صبر کن" if stop.kind == "cooldown" else \
                "سقف ساعتیِ خواندنِ سریع پر شد" if kind == "lookup" else "سقف ساعتیِ صفحه‌ها پر شد"
            self.say(f"{why}؛ پنجره باز می‌ماند و ساعت {clock_fa(at)} ادامه می‌دهد", "warn")
            await self._browse_sleep(max(1.0, at - time.time()))
            self._read_since = time.time()   # that wait was the hour's rest too

    async def _browse_trouble(self, f, source, which, name, waits, tries, failed):
        """One person did not come. Instagram's «wait»: one rest with the window open, then the same person again (a second
        «wait» in a row ends the job: the queue rests longer). A slow line: him again, TRIES_ONE times. An answer about him
        alone: he is marked and the next one comes. Anything else (logged out, a challenge) ends the job. Returns the «wait»s in a row."""
        if f.kind == "rate_limit":
            if waits >= 1:
                raise f
            self.say(f"اینستاگرام گفت صبر کن؛ پنجره باز می‌ماند و ساعت {clock_fa(time.time() + WAIT_REST * UNIT)} از همین نفر ادامه می‌دهد", "warn")
            await self._browse_sleep(WAIT_REST * UNIT)
            self._read_since = time.time()
            return waits + 1
        if f.kind in ("network", "timeout"):
            tries[name] = tries.get(name, 0) + 1
            if tries[name] < TRIES_ONE:
                self.say(f"{ltr('@' + name)}: صفحه درست بالا نیامد؛ کمی بعد دوباره", "warn")
                await self._browse_sleep(random.uniform(*PAUSE))
                return waits
        elif f.kind not in SKIP:
            raise f
        ig_process.mark(source, which, name, "failed", f.kind)
        failed[name] = f.kind
        self.say(f"{ltr('@' + name)}: خوانده نشد ({f.kind})؛ نفر بعدی", "warn")
        if f.kind in ("network", "timeout"):
            self._lost = getattr(self, "_lost", 0) + 1
            if self._lost >= LINE_LOST:
                self.say(f"{fa(self._lost)} نفر پشت سر هم به خاطر خط نیامد؛ فیلترشکن قطع است — پنجره کنار می‌رود و صف کمی بعد دوباره امتحان می‌کند", "warn")
                raise Fail("network", "the line is down")
        return waits

    async def _browse_reopen(self):
        """The page crashed: a new tab in the same browser (the same session); the next person is opened by its address."""
        self.say("صفحهٔ مرورگر کرش کرد؛ در همان مرورگر یک زبانهٔ تازه باز می‌شود و از نفر بعدی ادامه می‌دهد", "warn")
        old, self._crashed = self._page, False
        self._page = await self._ctx.new_page()
        self._page.on("crash", lambda _p: setattr(self, "_crashed", True))
        try:
            await old.close()
        except Exception:
            pass
