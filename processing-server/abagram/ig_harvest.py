"""Reading a WHOLE followers / following list (thousands of people). A mixin for LoginJob. Like his hand: each run opens the
profile, clicks the list and scrolls it at a person's pace, and Instagram's own page asks for every next page (a position saved
from an earlier session is never sent: Instagram answers that with «wait»). People saved before are scrolled past; the new ones
are added at the end. The pages count against their own hourly and daily limits (harvests_hour / harvests_day); a full hour
keeps the list open until there is room. What was read is saved every few pages, so a stop or a restart loses nothing."""
import asyncio
import random
import re
import time
from datetime import datetime, timezone

import ig_detect as d
import ig_people as ip
import ig_profile as pr
import ig_store
from ig_budget import Budget, Stop
from urllib.parse import parse_qsl, urlencode, urlparse

from ig_common import BASE, DATA, Fail, fa

MIN_ROOM = 5               # a run starts only when the limits have room for this many pages
# seconds between two turns of the wheel that bring a page. Slow and even on purpose (2026-10-29): after 300 pages in 32 min (2–5 s)
# Instagram cut every later session off after ~45 pages; a list can only be resumed by scrolling it again from the top, so the one way
# to 24k is a session that never gets cut — about 240 pages an hour, without long silences.
# 2026-11-04 his order «اروم اروم، از ۳۰ ثانیه یه بار»: the gap is now the «محدودیت‌ها» setting harvest_scroll (_scroll_gap), the
# same for people saved before (faster, 0.8–2 s, made Instagram stop the list silently, 2026-10-29); PAUSE stays for the mock site
PAUSE = (8.0, 15.0)
SKIP_PAUSE = PAUSE
REST_EVERY, REST = 25, (30.0, 75.0)   # and a longer rest every few pages
SAVE_EVERY = 5             # pages between two saves
TRIES = 3                  # the list not loading this many times in a row (a short rest each time) starts a long rest
# his order (2026-10-29, again 2026-11-02): the Chromium window of a whole-list read is NEVER closed before the last person — every
# wait below keeps it open and goes on from the same place; only the end of the list, a logout (nothing can go on without a new
# login) or his own «لغو» end the run.
HOLD_MAX = 24 * 60 * 60    # our own limits full: the window waits for room, even a whole day
# every hour of reading, a quarter of an hour of rest with the window open (his choice 2026-11-02): less pressure on the account
HOUR_READ, HOUR_REST = 60, 15
# minutes between two pictures of the window while the list is read: a page that crashes (2026-11-02 11:07, «Target crashed» after
# 2 h and ~5,500 people) can take no picture any more, so the run keeps the one from a few minutes before
SNAP_EVERY = 5
FIRST_WAIT = 30            # seconds for the first page after the click: through the VPN the list window shows grey rows for a while
# Instagram's «wait» in the middle of the list (his order 2026-10-29: «even then do not close the page»): the window stays open, it
# rests this many minutes and goes on from the same place; after the last one it keeps resting that long, as often as needed.
WAITS = [30, 60, 120, 240, 360, 360]
# minutes, window open, when the list stops loading without a word (the page itself has already asked again, _fetch_list); after
# them the window keeps resting KEEP_REST at a time — never closed (a new session would scroll the whole saved part again).
STALL_RESTS = [10]
KEEP_REST = 30
# minutes, window open, while the list's own requests die on the way with no answer at all (the VPN dropped: 2026-10-30 09:49, after
# 1 h 23 min and 4,569 people down the list). Up to an hour, as long as the window still asks after each rest — a new session would
# have to scroll the whole saved part again (~1.5 h at that depth).
NET_RESTS = [2, 3, 5, 5, 10, 10, 10, 15]
UNIT = 60                 # seconds in one of those minutes (the tests make it short)
RE_RETRY = r"^(try again|retry|reload|تلاش دوباره)$"
if not BASE.startswith("https://www.instagram.com"):   # the mock site in the tests: same steps, no waiting
    PAUSE, REST, HOLD_MAX, FIRST_WAIT, UNIT = (0.05, 0.1), (0.1, 0.2), 0, 10, 0.02
    HOUR_READ = 500        # «an hour» of reading = 10 s here, so a long test read passes through the hourly rest a few times
    SNAP_EVERY = 500       # and a picture every 10 s
    SKIP_PAUSE = PAUSE
WORD = {"followers": "فالوورها", "following": "فالووینگ‌ها"}
# the window's own next-page request, sent by the page itself (its cookies, its browser), once the window stopped asking; a reply
# that never comes is given up after a minute (then it counts as broken on the way)
JS_FETCH = """async ([url, heads]) => {
  const stop = new AbortController(), timer = setTimeout(() => stop.abort(), 60000);
  try { const r = await fetch(url, {headers: heads, credentials: "include", signal: stop.signal}); await r.text(); return r.status; }
  catch (e) { return String(e); }
  finally { clearTimeout(timer); }
}"""


RE_PICS = re.compile(r"^https://[^/]*(cdninstagram\.com|fbcdn\.net)/")   # where Instagram's pictures come from


def with_max_id(url, cursor):
    """The list request's address with another position (max_id); everything else as the page sent it."""
    u = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "max_id"] + [("max_id", cursor)]
    return u._replace(query=urlencode(q)).geturl()

# What the open list window shows when it stops moving: how many people, a loading sign, Instagram's suggestions after the list.
JS_LIST_STATE = r"""() => {
  const d = document.querySelector('div[role=dialog]');
  if (!d) return {dialog: false};
  return {dialog: true, rows: d.querySelectorAll('a[href^="/"][role=link], a[href^="/"]').length,
    spinner: !!d.querySelector('[role=progressbar], svg[aria-label="Loading..."], [data-visualcompletion="loading-state"]'),
    suggested: /suggested for you|suggestions for you/i.test(d.innerText || '')};
}"""


def clock_fa(ts):
    return fa(time.strftime("%H:%M", time.localtime(ts)))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key_of(p):
    return p["id"] or p["username"].lower()


def merge(items, people, front=False):
    """people added to items, nobody twice: in front (new followers come first) or at the end (the next page). Returns how many were new."""
    seen = {key_of(p) for p in items}
    new = [p for p in people if key_of(p) not in seen]
    if front:
        items[:0] = new
    else:
        items.extend(new)
    return len(new)


class HarvestReader:
    async def _harvest(self, username, proxy, options):
        which = options.get("which") if options.get("which") in WORD else "followers"
        word, budget, store = WORD[which], Budget(DATA), ig_store.Section(DATA, which)
        saved = store.load(username) or {}
        h = dict(saved.get("harvest") or {})
        if h.get("done") and not options.get("again"):
            self.say(f"{word}: همه قبلاً خوانده شده ({fa(len(saved.get('items') or []))} نفر)", "ok")
            return await self._harvest_end(username, which, saved, h, None)
        budget.check("page")
        lim = budget.limits()
        budget.check("harvest", extra=min(MIN_ROOM, lim["harvests_hour"], lim["harvests_day"]))
        self.say(f"خواندن همهٔ {word} مثل اسکرول دست: فهرست باز می‌شود و آرام پایین می‌رود")
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab_follow(r)))
        self._ctx.on("requestfailed", self._list_failed)
        self._ctx.on("request", self._list_asked)
        self._ctx.on("requestfinished", self._list_done)
        # the pictures of thousands of rows are never needed here (the names come in the list's own replies): not fetching them
        # keeps the window's memory small (2026-11-02 11:07 the page crashed after 2 h, ~5,500 people down)
        await self._ctx.route(RE_PICS, self._no_picture)
        self._pending, self._asks = {}, 0
        await self._open_profile(username)
        self._crashed = False
        self._page.on("crash", lambda _p: setattr(self, "_crashed", True))
        gone = await d.not_found_text(self._page)
        if gone:
            raise Fail("not_found", gone, gone)
        self.step("read", "active")
        stats = await self._wait_stats()
        info = stats.get(which)
        total = pr.parse_count(info["text"], info.get("title"))[0] if info else saved.get("total")
        if not info or not info["link"]:
            raise Fail("private" if stats.get("private") else "no_link",
                       "حساب خصوصی است و دنبالش نمی‌کنی؛ فهرستش دیده نمی‌شود" if stats.get("private") else "لینک این فهرست در صفحه پیدا نشد")
        first = await self._open_list(which, word)
        items = list(saved.get("items") or [])
        added = merge(items, first["users"], front=True)
        h.setdefault("started_at", now_iso())
        h["runs"] = h.get("runs", 0) + 1
        if first["limited"]:                       # a big account: Instagram shows others only part of the list
            h.update(done=True, next=None, more=False, note="limited")
            self.say(f"{word}: اینستاگرام فهرست این حساب را کوتاه می‌کند؛ بیشتر از این داده نمی‌شود", "warn")
        elif not h.get("next"):                    # the first run (or a list done before and read again): from the top
            h.update(next=first["next"], more=first["has_more"], done=not first["has_more"])
        if added and h.get("pages"):
            self.say(f"{word}: {fa(added)} نفر تازه در اول فهرست")
        rec = {"items": items, "total": total, "which": which}
        stopped = None
        try:
            await self._harvest_scroll(which, word, rec, h, store, username, saved, first)
        except Stop as stop:
            h["note"], stopped = stop.kind, stop
        finally:
            try:
                await self._close_list()
            except Exception:
                pass
            self._harvest_save(store, username, saved, rec, h)
        if stopped:
            raise stopped
        return await self._harvest_end(username, which, store.load(username) or {}, h, rec)

    async def _open_list(self, which, word):
        """Click the list link like a hand and take the first page (it also teaches us the page's own request)."""
        budget = Budget(DATA)
        self._lists.clear()
        try:
            await self._page.locator("header a[role=link]", has_text=re.compile(rf"\b{which}\b", re.I)).first.click(timeout=6000)
        except Exception:
            raise Fail("no_link", f"{word}: روی لینکش نتوانستم کلیک کنم")
        budget.spend("harvest")
        for _ in range(FIRST_WAIT * 4):
            first = self._new_page(which, 0)
            if first and self._list_req.get(which):
                return first
            await asyncio.sleep(0.25)
        rec = {}
        self._explain_refusal(which, rec, word)    # 'wait' and 'log in again' raise here
        raise Fail("no_reply", f"{word}: اینستاگرام فهرستی نفرستاد")

    async def _harvest_scroll(self, which, word, rec, h, store, username, saved, first):
        """Like his hand: the open list is scrolled and Instagram's own page asks for each next page, with its own fresh position.
        A position saved from an earlier session is never sent (Instagram answered that with «wait» at once, 2026-10-28). People
        saved before are scrolled past and the new ones go at the end. Nothing closes the window but the end of the list, a logout
        or his «لغو» (his order): full limits wait for room, every hour of reading rests a quarter of an hour, Instagram's «wait»
        rests 30 min … 6 h (then 6 h at a time), a list that stops loading is asked by the page itself and then rests 10 … 30 min
        at a time — each time it goes on from the same place."""
        budget, seen, since, fails = Budget(DATA), len(self._lists), len(self._refused), len(self._failed)
        pages, stalls, rests, waits, skipping, asks, fetching = 0, 0, 0, 0, False, self._asks, False
        self._read_since, snapped = time.time(), 0.0
        known, more = len(saved.get("items") or []), first["has_more"]
        while more and not h.get("done"):
            if self._crashed:   # the page crashed: a new tab in the same browser goes on from the same place
                if not (pages and self._list_req.get(which)):   # no page of this session yet: no position of its own to go on from
                    raise Fail("browser_crash", f"{word}: صفحهٔ مرورگر کرش کرد")
                self._harvest_save(store, username, saved, rec, h)
                await self._harvest_reopen(username, word)
                fetching, stalls = True, 0
                continue
            try:
                budget.check("harvest")
            except Stop:
                at = budget.free_at("harvest")
                if at - time.time() > HOLD_MAX:
                    raise
                self._harvest_save(store, username, saved, rec, h)
                self.say(f"{word}: سقف پر شد؛ فهرست باز می‌ماند و ساعت {clock_fa(at)} ادامه می‌دهد", "warn")
                await asyncio.sleep(max(1.0, at - time.time()))
                continue
            if time.time() - snapped >= SNAP_EVERY * UNIT:   # a fresh picture of the window every few minutes (see SNAP_EVERY)
                snapped = time.time()
                await self._snap()
            if time.time() - self._read_since >= HOUR_READ * UNIT:   # an hour of reading: a quarter of an hour of rest, window open
                await self._harvest_rest(store, username, saved, rec, h, HOUR_REST,
                                         f"{word}: استراحتِ ساعتی تا فشار روی حساب کم شود؛ پنجره باز می‌ماند و")
                continue
            rest_now = pages and pages % REST_EVERY == 0
            await asyncio.sleep(random.uniform(*REST) if rest_now else self._scroll_gap())
            try:
                page = await (self._fetch_list(which, seen, h.get("next")) if fetching else self._wheel_list(which, seen))
            except Exception:
                if not self._crashed:
                    raise
                continue   # the top of the loop opens the new tab
            said = self._harvest_said(which, since)
            if said == "login":
                raise Fail("session_invalid", "اینستاگرام برای ادامهٔ فهرست دوباره ورود خواست")
            if said == "wait":
                waits += 1   # after the last step it keeps resting that long: the window is never closed (his order)
                await self._harvest_rest(store, username, saved, rec, h, WAITS[min(waits, len(WAITS)) - 1],
                                         f"{word}: اینستاگرام گفت صبر کن ({fa(waits)} بار پشت سر هم)؛ فهرست باز می‌ماند و")
                since, self._limited = len(self._refused), False
                continue
            if page is None:
                stalls += 1
                if stalls == 1:   # the first silence of a series: say what Instagram did (or did not do), with a picture of the page
                    await self._harvest_signed_out()
                    await self._harvest_why(which, word, since, fails)
                dead = len(self._failed) > fails or any(time.time() - at > 60 for _, at in self._pending.values())
                if (dead or stalls >= TRIES) and not fetching and pages and self._list_req.get(which):
                    # Instagram's list never asks again after a request broken on the way (2026-10-30 09:49 and 19:25, 4,569 and 6,436
                    # people down) and sometimes just stops asking (20:35, 3,121 down): the page itself sends that same request — same
                    # address and headers, this session's own fresh position — and goes on that way; a new session would first scroll
                    # the whole saved part again (~2 h)
                    fetching, stalls = True, 0
                    why = "درخواستِ فهرست در راه از بین رفت و پنجره دیگر نمی‌پرسد" if dead else "پنجرهٔ فهرست دیگر صفحهٔ بعد را نمی‌خواهد"
                    self.say(f"{word}: {why}؛ همان درخواست را خودش دوباره می‌فرستد و از همین‌جا ادامه می‌دهد", "warn")
                    await asyncio.sleep(random.uniform(*REST))
                    continue
                if stalls < TRIES:
                    self.say(f"{word}: صفحهٔ بعد هنوز نیامد؛ کمی صبر و دوباره", "warn")
                    await asyncio.sleep(random.uniform(*REST))
                    continue
                # its requests die on the way (no answer at all) while the window still asks: the network, not Instagram — hold longer
                lost = len(self._failed) > fails and self._asks > asks
                holds = NET_RESTS if lost else STALL_RESTS
                minutes = holds[rests] if rests < len(holds) else KEEP_REST   # then KEEP_REST at a time: never closed (his order)
                rests, stalls, asks = rests + 1, 0, self._asks
                await self._harvest_rest(store, username, saved, rec, h, minutes,
                                         f"{word}: اتصال به اینستاگرام قطع است (فیلترشکن)؛ پنجره باز می‌ماند و" if lost
                                         else f"{word}: فهرست جلو نمی‌رود؛ پنجره باز می‌ماند و")
                continue
            stalls = rests = waits = 0
            seen, fails = len(self._lists), len(self._failed)
            budget.spend("harvest")
            pages += 1
            skipping = merge(rec["items"], page["users"]) == 0
            more = page["has_more"]
            h.update(next=page.get("next"), more=more, pages=h.get("pages", 0) + 1, note=None)
            if not more:
                h["done"] = True
            if pages % SAVE_EVERY == 0 or h.get("done"):
                self._harvest_save(store, username, saved, rec, h)
                left = f" از {fa(rec['total'])}" if rec.get("total") else ""
                past = "؛ هنوز از روی نفرهای ذخیره‌شده رد می‌شود" if skipping and pages * ip.PAGE < known + ip.PAGE else ""
                self.say(f"{word}: {fa(len(rec['items']))}{left} نفر تا الان{past}")

    async def _harvest_rest(self, store, username, saved, rec, h, minutes, text):
        """Save, say until when, rest with the window open, then nudge the list (its own «try again», a small turn back)."""
        self._harvest_save(store, username, saved, rec, h)
        self.say(f"{text} ساعت {clock_fa(time.time() + minutes * UNIT)} از همین‌جا ادامه می‌دهد", "warn")
        await asyncio.sleep(minutes * UNIT)
        self._read_since = time.time()   # any long rest counts as the hour's rest
        await self._harvest_signed_out()
        try:
            await d.click_button(self._page, RE_RETRY)
            await self._wheel(-2 * 360)
        except Exception:
            pass

    async def _harvest_signed_out(self):
        """Instagram logged the account out in the middle of the list (2026-10-30 10:48, together with a «wait»: after the rest the
        window showed «continue as kamel_ia1985 / use another profile»). Then nothing can go on until he logs in again."""
        try:
            gone = await d.page_kind(self._page) in ("form", "chooser") or not await d.auth_cookies(self._ctx, BASE)
        except Exception:
            return
        if gone:
            raise Fail("session_invalid", "اینستاگرام وسط فهرست این حساب را از حساب بیرون کرد؛ دوباره وارد شو تا ادامه دهد")

    async def _no_picture(self, route):
        try:
            await (route.abort() if route.request.resource_type == "image" else route.continue_())
        except Exception:
            pass

    def _scroll_gap(self):
        """Seconds until the next turn of the list, saved people or new: his «محدودیت‌ها» setting (30 s), read every time so a
        change there counts at once. The mock site keeps its short pause."""
        if PAUSE[1] < 1:
            return random.uniform(*PAUSE)
        return float(Budget(DATA).limits()["harvest_scroll"])

    async def _harvest_reopen(self, username, word):
        """The page crashed (its memory ran out: 2026-11-02 11:07): a new tab in the same browser — the same session, so the
        position saved a moment ago is still this session's own — and the list goes on from there, asked by the page itself."""
        self.say(f"{word}: صفحهٔ مرورگر کرش کرد؛ در همان مرورگر یک زبانهٔ تازه باز می‌شود و از همین‌جا ادامه می‌دهد", "warn")
        old, self._crashed = self._page, False
        self._page = await self._ctx.new_page()
        self._page.on("crash", lambda _p: setattr(self, "_crashed", True))
        try:
            await old.close()
        except Exception:
            pass
        tries = 0
        while True:   # the line down at that moment (2026-11-03 00:00: ERR_TIMED_OUT closed the window) is no end of the list
            try:
                await self._page.goto(f"{BASE}/{username}/", wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as e:
                if "net::" not in str(e) and "Timeout" not in str(e):
                    raise
                minutes = NET_RESTS[tries] if tries < len(NET_RESTS) else KEEP_REST
                tries += 1
                self.say(f"{word}: صفحهٔ پیج از راه خط باز نشد؛ پنجره باز می‌ماند و ساعت "
                         f"{clock_fa(time.time() + minutes * UNIT)} دوباره امتحان می‌کند", "warn")
                await asyncio.sleep(minutes * UNIT)
        await asyncio.sleep(random.uniform(*REST))
        await self._harvest_signed_out()

    async def _fetch_list(self, which, seen, cursor):
        """One more page the way the window asks for it — its own address and headers, this session's position — sent by the page
        itself once the window stopped asking (the switch in _harvest_scroll). None when nothing came."""
        req = self._list_req.get(which)
        if not req or not cursor:
            return None
        heads = {k: v for k, v in req["headers"].items() if k.lower().startswith("x-")}
        try:
            await asyncio.wait_for(self._page.evaluate(JS_FETCH, [with_max_id(req["url"], cursor), heads]), 75)
        except Exception:
            return None
        for _ in range(40):   # the reply is kept by the page's own listener (_grab_follow), a moment after it arrived
            page = self._new_page(which, seen)
            if page:
                return page
            await asyncio.sleep(0.25)
        return None

    def _list_asked(self, req):
        """A list request the page sent: kept until its answer comes (a request Instagram holds without answering stays here)."""
        try:
            if ip.FOLLOW_PATH.match(urlparse(req.url).path):
                self._pending[id(req)] = (req, time.time())
                self._asks += 1
        except Exception:
            pass

    def _list_done(self, req):
        self._pending.pop(id(req), None)

    def _list_failed(self, req):
        """A list request that never got an answer (no response at all): kept for the diagnosis of a stall."""
        self._pending.pop(id(req), None)
        try:
            if ip.FOLLOW_PATH.match(urlparse(req.url).path):
                self._failed.append(str(req.failure or "failed")[:160])
        except Exception:
            pass

    async def _harvest_why(self, which, word, since, fails):
        """Why the list did not move: Instagram's answer (code and message), a request that never got through, or no request at
        all (the window asked for nothing) — plus what the window shows, and a screenshot of it in the run's log."""
        bad = [r for r in self._refused[since:] if r["which"] == which]
        lost = self._failed[fails:]
        waiting = [time.time() - at for _, at in self._pending.values()]   # asked, never finished nor failed (never awaited here)
        try:
            box = await self._page.evaluate(JS_LIST_STATE) or {}
        except Exception:
            box = {}
        parts = []
        if bad:
            parts.append(f"اینستاگرام به درخواست فهرست جواب HTTP {bad[-1]['status']} داد: " + re.sub(r"\s+", " ", bad[-1]["text"])[:140])
        if lost:
            parts.append(f"درخواست فهرست به اینستاگرام نرسید ({lost[-1]})")
        if waiting:
            parts.append(f"یک درخواست فهرست فرستاده شده و اینستاگرام {fa(round(max(waiting)))} ثانیه است جوابش را نداده")
        if not bad and not lost and not waiting:
            parts.append("پنجرهٔ فهرست درخواست تازه‌ای نفرستاد")
        if box:
            parts.append(f"در پنجره {fa(box.get('rows', 0))} نفر دیده می‌شود" + ("، علامت بارگذاری هست" if box.get("spinner") else "")
                         + ("، «Suggested for you» آمده" if box.get("suggested") else "") + ("" if box.get("dialog") else "، پنجرهٔ فهرست بسته شده"))
        await self._snap()
        self.say(f"{word}: " + "؛ ".join(parts), "warn")

    def _harvest_said(self, which, since):
        """What Instagram answered to the page's own list requests since `since`: 'wait', 'login' or None."""
        bad = next((r for r in self._refused[since:] if r["which"] == which), None)
        text = bad["text"] if bad else ""
        if getattr(self, "_limited", False) or re.search(r"feedback_required|wait a few minutes|try again later|spam", text, re.I):
            return "wait"
        if re.search(r"login_required|checkpoint_required|challenge_required", text, re.I):
            return "login"
        return None

    def _harvest_save(self, store, username, saved, rec, h):
        h["updated_at"] = now_iso()
        store.save(username, dict(saved, items=rec["items"], total=rec.get("total") or saved.get("total"), more=not h.get("done"),
                                  limited=h.get("note") == "limited", reason=None if h.get("done") else h.get("note"),
                                  read_at=h["updated_at"], order="instagram", harvest=h))

    async def _harvest_end(self, username, which, saved, h, rec):
        n, total = len(saved.get("items") or []), saved.get("total")
        self.step("read", "done")
        self.step("save", "done")
        if h.get("done"):
            self.say(f"{WORD[which]}: تمام شد، {fa(n)} نفر ذخیره شد", "ok")
        self.result = {"profile": pr.Store(DATA).load(username), "cached": rec is None, "age": 0, "section": "harvest",
                       "harvest": {"which": which, "kept": n, "total": total, "done": bool(h.get("done")), "pages": h.get("pages", 0),
                                   "note": h.get("note")}}
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.8)
        await self.close()
        self.state = "success"
