"""Reading what lies under a post (its comments and the people who liked it) with the signed-in browser. A mixin for
LoginJob like ig_reader: it works through the job's browser, log and steps. One page per post, a few scrolls, one click."""
import asyncio
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import ig_comments as ic
import ig_detect as d
import ig_profile as pr
import ig_store
from ig_budget import Budget
from ig_common import BASE, CHALLENGE_MSG, DATA, Fail, fa, ltr

LIKERS_PATH = re.compile(r"^/api/v1/media/\d+/likers/$")
PAGE_OF_COMMENTS = 15      # what one page of comments holds
WAIT_FOR_REPLY = 7         # seconds to wait for what a scroll or a click asked for


class DeepReader:
    def _reset_deep(self):
        self._pages, self._likers = [], []   # the next pages of comments and the likers reply of the post being read

    async def _grab_deep(self, resp):
        """Keep Instagram's replies to a comments scroll and to the click on the like count; note a 429."""
        try:
            path = urlparse(resp.url).path
            api = "/graphql" in path or path.startswith("/api/")
            if resp.status == 429 and api:
                self._limited = True
            if resp.status != 200 or not api:
                return
            if LIKERS_PATH.match(path):
                self._likers.append(await resp.text())
            elif "PolarisPostCommentsPagination" in (resp.request.post_data or ""):
                self._pages.append(await resp.text())
        except Exception:
            return

    async def _details(self, username, proxy, options):
        """Open the most recent saved posts one by one and read their comments and likers (within the limits he set)."""
        limits = Budget(DATA).limits()
        posts = (ig_store.Section(DATA, "posts").load(username) or {}).get("items") or []
        wanted = options.get("codes")
        chosen = [p for p in posts if p["code"] in wanted] if wanted else posts[: min(options.get("count") or limits["detail_posts"], limits["detail_posts"])]
        if not chosen:
            raise Fail("no_posts", "برای این پروفایل پستی ذخیره نشده؛ اول پروفایل را بخوان.")
        Budget(DATA).check("page", extra=len(chosen))   # before any browser opens
        self.say(f"کامنت و لایک‌کنندگان {fa(len(chosen))} پست خوانده می‌شود")
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab_deep(r)))
        store = ig_store.Section(DATA, "details")
        details = (store.load(username) or {}).get("posts", {})
        for i, post in enumerate(chosen, 1):
            if i > 1:
                await d.pause(limits["pause_min"], limits["pause_max"])
            entry = {"code": post["code"], "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            details[post["code"]] = entry
            try:
                await self._read_post(post, entry, limits, i, len(chosen))
            finally:
                store.save(username, {"posts": details})   # what was read so far stays, even when a limit (a Stop) ends the rest
            if self._limited:
                raise Fail("rate_limit", "اینستاگرام به یکی از درخواست‌ها جواب 429 داد", detail={"http": 429})
        self.step("read", "done")
        self.step("save", "active")
        rec = pr.Store(DATA).load(username)
        got = [details[p["code"]] for p in chosen]
        self.say(f"{fa(sum(len(e.get('comments') or []) for e in got))} کامنت و {fa(sum(len(e.get('likers') or []) for e in got))} لایک‌کننده ذخیره شد", "ok")
        self.result = {"profile": rec, "cached": False, "age": 0, "section": "details", "codes": [p["code"] for p in chosen]}
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.8)
        await self.close()
        self.state = "success"

    async def _read_post(self, post, entry, limits, i, n):
        code, budget = post["code"], Budget(DATA)
        self._pages.clear()
        self._likers.clear()
        where = await self._open(BASE + post["url"], f"رفتن به پست {fa(i)} از {fa(n)} " + ltr(code), chooser="continue")
        if where == "form" or (where == "other" and await d.page_kind(self._page) == "chooser"):
            raise Fail("session_invalid", "اینستاگرام صفحهٔ ورود نشان داد؛ نشست معتبر نیست")
        if where == "other" and d.on_challenge(self._page):
            raise Fail("challenge", CHALLENGE_MSG)
        gone = await d.not_found_text(self._page)
        if where == "other" or gone:
            entry["error"] = "not_found" if gone else "unreachable"
            self.say(f"پست {fa(i)} باز نشد" + (": " + ltr(gone) if gone else ""), "warn")
            return
        self.step("read", "active")
        try:
            await self._page.wait_for_selector('section svg[aria-label="Comment"]', timeout=10000)
        except Exception:
            pass
        docs = ic.docs_from_html(await self._page.content())
        comments, paging = ic.comments_from_docs(docs), ic.comment_paging(docs)
        want = limits["comments"]
        scrolls, max_scrolls = 0, min(14, math.ceil(want / PAGE_OF_COMMENTS) + 1)
        try:
            while want > len(comments) and paging["more"] and scrolls < max_scrolls:
                budget.check("scroll")
                if not await self._scroll_comments():
                    break
                budget.spend("scroll")
                scrolls += 1
                comments, paging = ic.comments_from_docs(docs + self._pages), ic.comment_paging(docs + self._pages)
                await d.pause(limits["pause_min"], limits["pause_max"])
            entry["comments"] = comments[:want]
            entry["comments_total"] = post.get("comments")
            entry["comments_more"] = paging["more"] or len(comments) > want
            await self._read_likers(post, entry, limits, budget)
        finally:
            self.say(f"پست {fa(i)} از {fa(n)}: {fa(len(entry.get('comments') or []))} کامنت و {fa(len(entry.get('likers') or []))} لایک‌کننده", "ok")

    async def _scroll_comments(self):
        """Scroll the comments list once, the way a thumb would. True when a new page of comments arrived."""
        before = len(self._pages)
        box = await self._page.evaluate(d.JS_COMMENT_PANE)
        if not box:
            return False
        await self._page.mouse.move(box["x"], box["y"])
        await self._page.mouse.wheel(0, 1500)
        for _ in range(WAIT_FOR_REPLY * 2):
            await asyncio.sleep(0.5)
            if len(self._pages) > before:
                await asyncio.sleep(0.4)
                return True
        return False

    async def _read_likers(self, post, entry, limits, budget):
        """Click the like count and take the list Instagram shows (about the first hundred people at most)."""
        if limits["likers"] <= 0:
            return
        if post.get("likes_hidden"):
            entry["likers_note"] = "hidden"
            return
        if not post.get("likes"):
            entry["likers_note"] = "none"
            return
        budget.check("scroll")
        marked = await self._page.evaluate(d.JS_LIKES_MARK)
        shown, _ = pr.parse_count(marked["likes"]) if marked else (None, False)
        if not marked or shown is None or abs(shown - post["likes"]) > max(2, post["likes"] * 0.06):
            entry["likers_note"] = "no_count"      # the number next to the heart is not the one we expect: do not click blindly
            return
        before = len(self._likers)
        try:
            await self._page.locator('[data-igs-likes="1"]').first.click(timeout=4000)
        except Exception:
            entry["likers_note"] = "no_click"
            return
        for _ in range(WAIT_FOR_REPLY * 2):
            await asyncio.sleep(0.5)
            if len(self._likers) > before:
                break
        budget.spend("scroll")
        await self._page.keyboard.press("Escape")
        found = ic.likers_from_api(self._likers[before:])
        entry["likers"] = found["users"][: limits["likers"]]
        entry["likers_total"] = found["total"]
        entry["likers_more"] = (found["total"] or 0) > len(entry["likers"])
        if not found["users"]:
            entry["likers_note"] = "empty"
