"""Reading a person's active story and the items of their highlights with the signed-in browser. A mixin for LoginJob.
A story page carries its reel inside its own HTML, so the page is opened and read and NOTHING is pressed: Instagram's
"View story" button (the one that tells the owner who looked) is never clicked. Every "seen" request is counted anyway."""
import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import ig_detect as d
import ig_profile as pr
import ig_stories as sto
import ig_store
from ig_budget import Budget
from ig_common import BASE, DATA, Fail, first_line, fa

SEEN = re.compile(r"StoriesV3Seen|ViewSeen|reel_seen|media/seen", re.I)
STORY_PICS = 30       # pictures of an active story kept on disk (a story vanishes from Instagram within a day)
HIGHLIGHT_PICS = 12   # pictures kept per highlight (the highlight itself stays on Instagram)
READ_FOR = 14         # seconds a story page gets to show its reel before we say there is none


def find_reel(reels, kind, path, username):
    """The reel this page was opened for: the person's own story, or the highlight whose id is in the address."""
    for r in reels:
        if kind == "story" and r["kind"] == "story" and r["user"].lower() == username.lower():
            return r
        if kind == "highlight" and r["kind"] == "highlight" and f"/{r['id']}/" in path:
            return r
    return None


class ReelReader:
    def _reset_reels(self):
        self._seen_marks = 0

    async def _grab_seen(self, resp):
        """Count any request that would tell Instagram a story was seen (there should be none)."""
        try:
            if SEEN.search((resp.request.post_data or "") + resp.url):
                self._seen_marks += 1
        except Exception:
            return

    async def _reels(self, mode, username, proxy, options):
        limits = Budget(DATA).limits()
        saved = (ig_store.Section(DATA, "highlights").load(username) or {}).get("items") or []
        if mode == "stories":
            targets = [("story", f"/stories/{username}/", "استوری فعال")]
        else:
            wanted = options.get("ids")
            chosen = [h for h in saved if h["id"] in wanted] if wanted else saved[: limits["highlights"]]
            if not chosen:
                raise Fail("no_highlights", "این هایلایت‌ها در فهرست ذخیره‌شدهٔ این پروفایل نیست؛ پروفایل را دوباره بخوان." if wanted
                           else "برای این پروفایل هایلایتی ذخیره نشده؛ اول پروفایل را بخوان.")
            targets = [("highlight", h["url"], h["title"] or "هایلایت") for h in chosen]
        Budget(DATA).check("page", extra=len(targets))
        self.say(f"{fa(len(targets))} صفحه خوانده می‌شود؛ دکمهٔ «View story» زده نمی‌شود")
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab_seen(r)))
        read, at = {}, datetime.now(timezone.utc).isoformat(timespec="seconds")   # path -> reel
        for i, (kind, path, label) in enumerate(targets, 1):
            if i > 1:
                await d.pause(limits["pause_min"], limits["pause_max"])
            reel = await self._read_reel(kind, path, label, i, len(targets), limits, username)
            read[path] = reel
            await self._keep_reel(username, kind, reel, at)
        self.step("read", "done")
        self.step("save", "active")
        if self._seen_marks:
            self.say(f"توجه: اینستاگرام خودش {fa(self._seen_marks)} درخواست «دیده شد» فرستاد", "warn")
        else:
            self.say("هیچ درخواست «دیده شد» فرستاده نشد؛ دکمهٔ «View story» زده نشد", "ok")
        found = [r for r in read.values() if r]
        self.result = {"profile": pr.Store(DATA).load(username), "cached": False, "age": 0, "section": mode, "seen_marks": self._seen_marks,
                       "ids": [p.split("/")[3] for p in read if "/highlights/" in p], "found": len(found), "items": sum(len(r["items"]) for r in found)}
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.8)
        await self.close()
        self.state = "success"

    async def _goto(self, path):
        """Open a story address (one page is spent from the budget for each time)."""
        try:
            await self._page.goto(BASE + path, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            raise Fail("network", first_line(e))
        Budget(DATA).spend("page")

    async def _read_reel(self, kind, path, label, i, n, limits, username):
        """Open the page and take the reel out of its HTML. A story page has no menu bar, so the usual "which page is this"
        wait is not used: the loop ends the moment the reel shows, or a login page, a missing page or a redirect does."""
        page, loop = self._page, asyncio.get_event_loop()
        self.step("page", "active")
        self.say(f"رفتن به {label} ({fa(i)} از {fa(n)})")
        await self._goto(path)
        self.step("page", "done")
        self.step("read", "active")
        end, tick, pressed, reel = loop.time() + READ_FOR, 0, False, None
        while loop.time() < end:
            reel = find_reel(sto.reels_from_docs(sto.docs_from_html(await page.content())), kind, path, username)
            if reel:
                break
            if tick % 4 == 0 and await d.dismiss_cookie_banner(page):
                self.say("پنجرهٔ کوکی بسته شد")
            tick += 1
            where = await d.page_kind(page)
            if where == "form" or (where == "chooser" and pressed):
                raise Fail("session_invalid", "اینستاگرام صفحهٔ ورود نشان داد؛ نشست معتبر نیست")
            if where == "chooser":   # "continue as <remembered account>": same as the profile read does
                pressed = True
                self.say("اینستاگرام صفحهٔ «ادامه با حساب قبلی» نشان داد؛ ادامه با همان حساب را می‌زنم")
                await d.click_button(page, d.RE_CONTINUE)
                await asyncio.sleep(1.5)
                await self._goto(path)
                continue
            if await d.not_found_text(page) or not urlparse(page.url).path.startswith("/stories/"):
                break   # no such page, or Instagram sent us elsewhere (a person with no story goes back to the profile)
            await asyncio.sleep(0.5)
        if reel and kind == "highlight":
            reel["items"] = reel["items"][: limits["highlight_items"]]
        if reel:
            self.say(f"{label}: {fa(len(reel['items']))} آیتم" + (f" از {fa(reel['items_total'])}" if reel["items_total"] > len(reel["items"]) else ""), "ok")
        else:
            self.say(f"{label}: " + ("استوری فعالی پیدا نشد" if kind == "story" else "آیتمی پیدا نشد"), "warn")
        return reel

    async def _keep_pictures(self, username, reel, most):
        """A small picture of the first `most` items goes to disk (key st_<id>); every item learns whether it has one."""
        media, saved = ig_store.Media(DATA), 0
        for item in reel["items"]:
            item["has_thumb"] = False
        for item in reel["items"][:most]:
            data = await self._download(item.get("thumb") or item.get("image"))
            item["has_thumb"] = bool(data and item["id"] and media.put(username, "st_" + item["id"], data[0]))
            saved += item["has_thumb"]
            await asyncio.sleep(0.12)
        return saved

    async def _keep_reel(self, username, kind, reel, at):
        """Save one reel the moment it is read, so a later stop (a limit, Instagram saying wait) never loses it."""
        if kind == "story":
            saved = await self._keep_pictures(username, reel, STORY_PICS) if reel else 0
            ig_store.Section(DATA, "stories").save(username, {"reel": reel, "read_at": at})   # reel None = checked, nothing active
            if reel:
                self.say(f"{fa(saved)} تصویر از استوری ذخیره شد (استوری تا یک روز بعد از اینستاگرام پاک می‌شود)", "ok")
            return
        if not reel:
            return
        saved = await self._keep_pictures(username, reel, HIGHLIGHT_PICS)
        store = ig_store.Section(DATA, "reels")
        items = (store.load(username) or {}).get("highlights", {})
        items[reel["id"]] = dict(reel, read_at=at)
        store.save(username, {"highlights": items})
        self.say(f"{fa(saved)} تصویر کوچک از آیتم‌ها ذخیره شد", "ok")
