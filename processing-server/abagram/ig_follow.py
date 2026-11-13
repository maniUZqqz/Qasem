"""Reading who follows a person and whom a person follows, with the signed-in browser. A mixin for LoginJob.
The profile page is opened once, the "followers" / "following" link is clicked like a hand would, and the list is scrolled in
small steps; the people come from Instagram's own replies to that (never from the dialog's text). Pages of twelve, paced and
counted against the budget, within the limits he set; Instagram itself cuts the lists of big accounts short and says so."""
import asyncio
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import ig_detect as d
import ig_people as ip
import ig_profile as pr
import ig_store
from ig_budget import Budget, Stop
from ig_common import BASE, DATA, Fail, fa

WAIT_FOR_REPLY = 8      # seconds to wait for what a click or a scroll asked for
if BASE.startswith("https://www.instagram.com"):   # through the VPN a page of people can take well over 8 s
    WAIT_FOR_REPLY = 20
WHEEL_STEPS = 8         # small wheel turns tried for one more page of people
WHEEL_PX = 360
STATS_WAIT = 12         # seconds to let the profile header show its counts
WORD = {"followers": "فالوورها", "following": "فالووینگ‌ها"}
EVERY = ("followers", "following")

# The counts of the header, with whether each one is a link (a private account we do not follow shows them as plain text).
JS_STATS = r"""() => {
  const out = {followers: null, following: null, private: /This account is private/i.test(document.body.innerText || '')};
  const header = document.querySelector('header') || document.body;
  for (const el of header.querySelectorAll('a, span, div')) {
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    const m = /^([\d.,]+ ?[KMB]?) (followers|following)$/i.exec(t);
    if (!m) continue;
    const key = m[2].toLowerCase(), link = !!el.closest('a[role=link]');
    const title = (el.querySelector('[title]') || el.closest('[title]') || {}).title || null;
    if (!out[key] || (link && !out[key].link)) out[key] = {text: m[1].replace(' ', ''), title, link};
  }
  return out;
}"""

# The scrolling block inside the open dialog (the tallest one): where the mouse has to be for the wheel to move the list.
JS_LIST_PANE = r"""() => {
  const dlg = document.querySelector('div[role=dialog]');
  if (!dlg) return null;
  const c = [...dlg.querySelectorAll('div')].filter(e => e.scrollHeight > e.clientHeight + 20 && /(auto|scroll)/.test(getComputedStyle(e).overflowY));
  c.sort((a, b) => b.scrollHeight - a.scrollHeight);
  if (!c.length) return null;
  const r = c[0].getBoundingClientRect();
  return {x: r.x + r.width / 2, y: r.y + r.height / 2};
}"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FollowReader:
    def _reset_follow(self):
        self._lists = []    # replies to the list requests, in the order they arrived: {'which', 'id', 'text'}
        self._refused = []  # list requests Instagram answered with an error: {'which', 'status', 'text'}
        self._failed = []   # list requests that never got an answer (the line dropped, the proxy refused): 'reason'
        self._list_req = {} # which -> {'url', 'headers'} of the first list request the page itself sent (a whole-list read asks the same way)

    async def _grab_follow(self, resp):
        """Keep Instagram's replies that carry a page of people; note a 429."""
        try:
            path = urlparse(resp.url).path
            if resp.status == 429 and path.startswith("/api/"):
                self._limited = True
                return
            m = ip.FOLLOW_PATH.match(path)
            if not m or resp.request.method != "GET":
                return
            if resp.status == 200:
                text = await resp.text()
                if ip.page_of_reply(text) is None:   # a 200 with no list in it (e.g. «status: fail, please wait»): Instagram's answer too
                    self._refused.append({"which": m.group(2), "status": 200, "text": text[:400]})
                    return
                if m.group(2) not in self._list_req:
                    self._list_req[m.group(2)] = {"url": resp.url, "headers": await resp.request.all_headers()}
                self._lists.append({"which": m.group(2), "id": m.group(1), "text": text})
            else:
                self._refused.append({"which": m.group(2), "status": resp.status, "text": (await resp.text())[:400]})
        except Exception:
            return

    def _new_page(self, which, seen):
        """The first page of people of this list that arrived after the first `seen` replies, or None."""
        for r in self._lists[seen:]:
            if r["which"] == which:
                page = ip.page_of_reply(r["text"])
                if page is not None:
                    return page
        return None

    async def _wait_stats(self):
        loop, stats = asyncio.get_event_loop(), {}
        end = loop.time() + STATS_WAIT
        while loop.time() < end:
            stats = await self._page.evaluate(JS_STATS) or {}
            if stats.get("followers") and stats.get("following"):
                break
            await asyncio.sleep(0.5)
        return stats

    async def _follow(self, username, proxy, options):
        """Open the profile once and read the lists asked for (followers, following), each up to its limit."""
        budget, limits = Budget(DATA), Budget(DATA).limits()
        wanted = [w for w in EVERY if w in (options.get("which") or EVERY)]
        plan = [(w, limits[w]) for w in wanted if limits[w] > 0]
        if not plan:
            raise Fail("no_limit", "سقف خواندن این فهرست‌ها صفر است؛ در «محدودیت‌ها» بالا ببر.")
        known = pr.Store(DATA).load(username) or {}
        rounds = sum(max(1, math.ceil(min(cap, known.get(w) or cap) / ip.PAGE)) for w, cap in plan)
        budget.check("page")
        # before any browser opens: room for a first page of each list (a long list then reads what fits and is saved as it goes;
        # demanding the whole estimate made a 500-person list impossible under a 40-an-hour cap)
        budget.check("scroll", extra=min(rounds, 2 * len(plan)))
        self.say("خواندن " + " و ".join(WORD[w] + f" (تا {fa(cap)} نفر)" for w, cap in plan))
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab_follow(r)))
        await self._open_profile(username)
        gone = await d.not_found_text(self._page)
        if gone:
            raise Fail("not_found", gone, gone)
        self.step("read", "active")
        stats, at, summary = await self._wait_stats(), now_iso(), {}
        for i, (which, cap) in enumerate(plan):
            if i:
                await d.pause(limits["pause_min"], limits["pause_max"])
            rec = {"items": [], "total": None, "more": False, "limited": False, "hidden": None, "reason": None}
            try:
                await self._read_list(which, cap, stats, limits, rec)
            except Stop as stop:
                rec["reason"] = rec["reason"] or stop.kind
                raise
            finally:
                summary[which] = self._keep_list(username, which, rec, at)   # what was read stays, even when a limit ends the rest
            if self._limited:
                raise Fail("rate_limit", "اینستاگرام به یکی از درخواست‌ها جواب 429 داد", detail={"http": 429})
        self.step("read", "done")
        self.step("save", "active")
        self.result = {"profile": pr.Store(DATA).load(username), "cached": False, "age": 0, "section": "follow", "lists": summary}
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.8)
        await self.close()
        self.state = "success"

    async def _read_list(self, which, cap, stats, limits, rec):
        """One list: click its link, take the first page, scroll for more until `cap` people (or no more). Fills `rec` as it goes."""
        info, budget, word = stats.get(which), Budget(DATA), WORD[which]
        if info:
            rec["total"] = pr.parse_count(info["text"], info.get("title"))[0]
        if rec["total"] == 0:
            rec["reason"] = "empty"
            self.say(f"{word}: صفر است، چیزی برای خواندن نیست")
            return
        if not info or not info["link"]:
            rec["reason"] = "private" if stats.get("private") else "no_link"
            self.say(f"{word}: " + ("حساب خصوصی است و تو دنبالش نمی‌کنی؛ فهرستش دیده نمی‌شود" if rec["reason"] == "private" else "لینک این فهرست در صفحه پیدا نشد"), "warn")
            return
        budget.check("scroll")
        self._lists.clear()
        try:
            await self._page.locator("header a[role=link]", has_text=re.compile(rf"\b{which}\b", re.I)).first.click(timeout=6000)
        except Exception:
            rec["reason"] = "no_link"
            self.say(f"{word}: روی لینکش نتوانستم کلیک کنم", "warn")
            return
        budget.spend("scroll")
        first = None
        for _ in range(WAIT_FOR_REPLY * 4):
            first = self._new_page(which, 0)
            if first:
                break
            await asyncio.sleep(0.25)
        if first is None:
            await self._close_list()
            self._explain_refusal(which, rec, word)
            return
        pages, stopped = [first], None
        try:
            while len(ip.merge_pages(pages)) < cap and pages[-1]["has_more"] and not self._limited:
                budget.check("scroll")
                await d.pause(limits["pause_min"], limits["pause_max"])
                more = await self._wheel_list(which, len(self._lists))
                if more is None:
                    rec["reason"] = "stalled"
                    self.say(f"{word}: صفحهٔ بعدی نیامد؛ همین‌قدر که رسید نگه داشته شد", "warn")
                    break
                budget.spend("scroll")
                pages.append(more)
        except Stop as stop:
            rec["reason"], stopped = stop.kind, stop
        finally:
            people = ip.merge_pages(pages)
            rec["items"] = people[:cap]
            rec["limited"] = any(p["limited"] for p in pages)
            rec["hidden"] = next((p["hidden"] for p in pages if p["hidden"]), None)
            rec["more"] = pages[-1]["has_more"] or len(people) > cap
            await self._close_list()
        if stopped:
            raise stopped

    def _explain_refusal(self, which, rec, word):
        """Instagram sent an error instead of a list. 'Wait' and 'log in again' stop the whole job; any other refusal is only noted."""
        refused = next((r for r in self._refused if r["which"] == which), None)
        if refused is None:
            rec["reason"] = "no_reply"
            self.say(f"{word}: اینستاگرام فهرستی نفرستاد", "warn")
            return
        try:
            said = str(json.loads(refused["text"]).get("message") or "")
        except (ValueError, AttributeError):
            said = ""
        if re.search(r"feedback_required|wait a few minutes|try again later|spam", refused["text"], re.I):
            raise Fail("rate_limit", said or "اینستاگرام گفت صبر کن", said or None, {"http": refused["status"]})
        if re.search(r"login_required|checkpoint_required|challenge_required", refused["text"], re.I):
            raise Fail("session_invalid", "اینستاگرام برای دیدن فهرست دوباره ورود خواست؛ نشست معتبر نیست", said or None, {"http": refused["status"]})
        rec["reason"], rec["http"] = "refused", refused["status"]
        self.say(f"{word}: اینستاگرام فهرست را نداد (HTTP {refused['status']})" + (f": {said}" if said else ""), "warn")

    async def _wheel(self, dy):
        """One turn of the wheel over the open list; False when there is no list to turn it over."""
        box = await self._page.evaluate(JS_LIST_PANE)
        if not box:
            return False
        await self._page.mouse.move(box["x"], box["y"])
        await self._page.mouse.wheel(0, dy)
        await asyncio.sleep(0.35)
        return True

    async def _wheel_list(self, which, seen):
        """Turn the wheel over the open list in small steps until one more page of people arrives (a jump to the very end can skip
        the marker that makes the list load more). If the marker was already in the window and never left it, back up a little
        and come again. None when nothing came."""
        for attempt in range(2):
            if attempt and not await self._wheel(-3 * WHEEL_PX):
                return None
            for _ in range(WHEEL_STEPS if not attempt else 8):
                if not await self._wheel(WHEEL_PX):
                    return None
                page = self._new_page(which, seen)
                if page:
                    await asyncio.sleep(0.4)
                    return page
            for _ in range((2 if not attempt else WAIT_FOR_REPLY) * 4):
                page = self._new_page(which, seen)
                if page:
                    return page
                await asyncio.sleep(0.25)
        return None

    async def _close_list(self):
        await self._page.keyboard.press("Escape")
        await asyncio.sleep(0.8)
        if await self._page.locator("div[role=dialog]").count():
            try:
                await self._page.locator('div[role=dialog] button:has(svg[aria-label="Close"])').first.click(timeout=2000)
            except Exception:
                pass
            await asyncio.sleep(0.5)

    def _keep_list(self, username, which, rec, at):
        """Save the list and say in one line what came out of it; returns the short summary for the job's result."""
        store = ig_store.Section(DATA, which)
        old = store.load(username) or {}
        if old.get("harvest") and rec["items"]:
            # a whole list read before: the first pages read now go in front (new followers come first), nobody is dropped
            fresh = {p["id"] or p["username"].lower() for p in rec["items"]}
            rest = [p for p in old.get("items") or [] if (p["id"] or p["username"].lower()) not in fresh]
            store.save(username, dict(old, items=rec["items"] + rest, total=rec["total"] or old.get("total"), read_at=at))
        elif rec["items"] or rec["reason"] in ("empty", "private") or not old:
            store.save(username, dict(rec, read_at=at, order="instagram"))   # a failed try never wipes a list saved before
        n, word = len(rec["items"]), WORD[which]
        tail = [f"از {fa(rec['total'])}"] if rec["total"] is not None else []
        if rec["limited"]:
            tail.append("اینستاگرام فهرست این حساب را کوتاه می‌کند")
        elif rec["more"]:
            tail.append("بیشتر هم هست")
        if rec["hidden"]:
            tail.append(f"{fa(rec['hidden'])} مورد پنهان")
        if n or not rec["reason"]:
            self.say(f"{word}: {fa(n)} نفر ذخیره شد" + (" (" + "؛ ".join(tail) + ")" if tail else ""), "ok" if n else "warn")
        return {"kept": n, "total": rec["total"], "more": rec["more"], "limited": rec["limited"], "reason": rec["reason"]}
