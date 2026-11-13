"""Reading more posts than a profile page carries at first: the page is scrolled the way a thumb would, and each batch of twelve
that Instagram's page asks for arrives as a reply (PolarisProfilePostsTabContentQuery_connection) that ig_posts already reads.
A mixin for LoginJob. The saved posts are never cut down: what is read is merged into what is there."""
import asyncio
import math
import re
from urllib.parse import urlparse

import ig_detect as d
import ig_posts as ap
import ig_profile as pr
import ig_store
from ig_budget import Budget, Stop
from ig_common import DATA, Fail, fa

PAGE = 12                 # posts one batch holds
WAIT_FOR_REPLY = 8        # seconds to wait for the next batch after a scroll
FIRST_WAIT = 12           # seconds for the page's own first batch
WHEEL_STEPS = 6
WHEEL_PX = 700
QUERY = re.compile(r"fb_api_req_friendly_name=(PolarisProfilePosts[A-Za-z0-9_]*)")


class GridReader:
    def _reset_grid(self):
        self._grid = []     # texts of the replies that carry posts, in the order they came

    async def _grab_grid(self, resp):
        try:
            path = urlparse(resp.url).path
            if resp.status == 429 and path.startswith("/api/"):
                self._limited = True
                return
            if resp.status == 200 and "/graphql" in path and QUERY.search(resp.request.post_data or ""):
                self._grid.append(await resp.text())
        except Exception:
            return

    async def _more_posts(self, username, proxy, options):
        """Open the profile, scroll its grid until `count` posts (never above the limit) or the end, and merge them into the saved posts."""
        budget, limits = Budget(DATA), Budget(DATA).limits()
        profile = pr.Store(DATA).load(username)
        if not profile:
            raise Fail("no_profile", "برای این پروفایل چیزی ذخیره نشده؛ اول پروفایل را بخوان.")
        if profile.get("is_private") is True:
            raise Fail("private", "این حساب خصوصی است؛ پست‌هایش دیده نمی‌شود.")
        cap = min(options.get("count") or limits["posts"], limits["posts"])
        total = profile.get("posts")
        if total == 0:
            raise Fail("empty", "این حساب هنوز پستی ندارد.")
        want = min(cap, total) if total else cap
        budget.check("page")
        budget.check("scroll", extra=max(0, math.ceil((want - PAGE) / PAGE)))     # before any browser opens
        self.say(f"خواندن تا {fa(want)} پست")
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab_grid(r)))
        await self._open_profile(username)
        gone = await d.not_found_text(self._page)
        if gone:
            raise Fail("not_found", gone, gone)
        self.step("read", "active")
        posts = await self._first_posts(username, profile, want)
        if not posts:
            if self._limited:
                raise Fail("rate_limit", "اینستاگرام به یکی از درخواست‌ها جواب 429 داد", detail={"http": 429})
            raise Fail("unreadable", "اینستاگرام پست‌ها را نفرستاد؛ پست‌های ذخیره‌شده دست نخورد.")
        stalled, stop = None, None
        try:
            while len(posts) < want and not self._limited:
                budget.check("scroll")
                await d.pause(limits["pause_min"], limits["pause_max"])
                if not await self._scroll_grid(len(self._grid)):
                    stalled = "stalled" if len(posts) < min(want, total or want) else None
                    break
                budget.spend("scroll")
                posts = ap.posts_from_api(self._grid, username, profile.get("user_id"), limit=want)
                self.say(f"{fa(len(posts))} پست تا الان")
        except Stop as s:
            stop = s
        new = await self._keep_grid(username, posts)     # what was read stays, even when a limit or a 429 ends the rest
        if stop:
            raise stop
        if self._limited:
            raise Fail("rate_limit", "اینستاگرام به یکی از درخواست‌ها جواب 429 داد", detail={"http": 429})
        if stalled:
            self.say("صفحهٔ بعدی پست‌ها نیامد؛ همین‌قدر که رسید نگه داشته شد", "warn")
        self.step("read", "done")
        self.step("save", "active")
        merged = ig_store.Section(DATA, "posts").load(username) or {}
        self.result = {"profile": profile, "cached": False, "age": 0, "section": "posts", "read": len(posts), "new": new, "saved": len(merged.get("items") or []), "total": total}
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.8)
        await self.close()
        self.state = "success"

    async def _first_posts(self, username, profile, want):
        """The page's own first batch (it trails the header by a moment)."""
        loop = asyncio.get_event_loop()
        end, posts = loop.time() + FIRST_WAIT, []
        while loop.time() < end:
            posts = ap.posts_from_api(self._grid, username, profile.get("user_id"), limit=want)
            if posts:
                break
            await asyncio.sleep(0.5)
        return posts

    async def _scroll_grid(self, seen):
        """Turn the wheel over the page until one more batch of posts arrives. True when it did."""
        for _ in range(WHEEL_STEPS):
            await self._page.mouse.move(640, 500)
            await self._page.mouse.wheel(0, WHEEL_PX)
            await asyncio.sleep(0.4)
            if len(self._grid) > seen:
                await asyncio.sleep(0.4)
                return True
        for _ in range(WAIT_FOR_REPLY * 4):
            if len(self._grid) > seen:
                return True
            await asyncio.sleep(0.25)
        return False

    async def _keep_grid(self, username, posts):
        """Merge the posts read into the saved ones (newer data wins, nothing is dropped), give new ones a thumbnail; returns how many were new."""
        store, media = ig_store.Section(DATA, "posts"), ig_store.Media(DATA)
        old = store.load(username) or {}
        by_code = {p["code"]: p for p in old.get("items") or []}
        new = sum(1 for p in posts if p["code"] not in by_code)
        for p in posts:
            p["has_thumb"] = (by_code.get(p["code"]) or {}).get("has_thumb", False)
            by_code[p["code"]] = p
        for p in by_code.values():
            if not p.get("has_thumb") and p.get("thumb"):
                data = await self._download(p["thumb"])
                p["has_thumb"] = bool(data and media.put(username, p["code"], data[0]))
                await asyncio.sleep(0.15)
        merged = sorted(by_code.values(), key=lambda p: p["taken_at"], reverse=True)
        store.save(username, {"items": merged, "reason": None})
        self.say(f"{fa(new)} پست تازه ذخیره شد؛ روی هم {fa(len(merged))} پست", "ok")
        return new
