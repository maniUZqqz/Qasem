"""Reading one profile with the signed-in browser. A mixin for LoginJob (ig_login.py): it works through the
job's browser, log and steps (self._page, self.say, self.step, ...), so it has its own file but not its own life."""
import asyncio
import json
import os
import re
from urllib.parse import urlparse

import ig_detect as d
import ig_more as am
import ig_posts as ap
import ig_profile as pr
import ig_store
from ig_budget import Budget
from ig_common import BASE, CHALLENGE_MSG, DATA, Fail, age_text, fa, first_line, ltr

READ_FOR = 16              # seconds to let the profile page fill in
DOM_ALONE_AFTER = 6        # seconds to wait for Instagram's API reply once the page already shows the numbers
SETTLE_WAIT = float(os.environ.get("IGS_SETTLE_WAIT", "3"))   # seconds the small replies (highlights, similar accounts) may trail the main ones
POSTS_WAIT = float(os.environ.get("IGS_POSTS_WAIT", "6"))  # extra seconds to wait for the posts reply when the account has posts and is not private
CAPTURE_MAX = 16           # reply bodies kept for reading
CAPTURE_BYTES = 4_000_000
DUMP_BYTES = 600_000        # per reply, in the debug file
# Replies of the profile page that do not name the user inside (a list of similar accounts, a note) are kept by their query name.
KEEP_NAMES = ("PolarisProfileStoryHighlightsTray", "PolarisProfileSuggestedUsers", "PolarisProfileNoteBubble",
              "PolarisSchoolPartnerProfileBadge", "PolarisProfilePageContent", "PolarisProfilePosts")
DUMP = DATA / "last_read.json"   # what the last read saw, kept for a human to look at when something is off


class ProfileReader:
    def _reset_reader(self):
        self._bodies, self._limited, self._want, self._said, self._posts = [], False, None, None, []
        self._highlights, self._similar = [], []

    async def _grab(self, resp):
        """Keep Instagram's own replies that mention the wanted user, and note any 429."""
        if not self._want:
            return
        try:
            path = urlparse(resp.url).path
            api = "/graphql" in path or path.startswith("/api/")
            if resp.status == 429 and api:
                self._limited = True
            if resp.status != 200 or not api or len(self._bodies) >= CAPTURE_MAX:
                return
            text = await resp.text()
            post = resp.request.post_data or ""
            m = re.search(r"fb_api_req_friendly_name=([A-Za-z0-9_]+)", post)
            friendly = m.group(1) if m else None
            if len(text) <= CAPTURE_BYTES and (self._said.search(text.lower()) or (friendly or "").startswith(KEEP_NAMES)):
                self._bodies.append({"path": path, "friendly": friendly, "text": text})
        except Exception:
            return

    async def _profile(self, username, proxy, fresh):
        store = pr.Store(DATA)
        self._want = username.lower()
        self._said = re.compile(r'"username"\s*:\s*"' + re.escape(self._want) + '"')  # JSON may or may not have spaces
        saved = store.load(username)
        age = pr.age_seconds(saved) if saved else None
        if saved and not fresh and age is not None and age < pr.FRESH_FOR:
            return self._serve_saved(saved, age)
        Budget(DATA).check("page")   # before any browser opens: a full hour, a full day or a pause after "wait" stops the job here
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab(r)))
        await self._open_profile(username)
        merged = await self._read_page(username)
        await self._keep(store, merged)

    def _serve_saved(self, rec, age):
        """A profile read recently: answer from disk, no browser, no request to Instagram."""
        for key in ("browser", "page", "save"):
            self.step(key, "skipped")
        self.step("read", "active")
        self.say("از ذخیره‌ها خوانده شد، " + age_text(age) + " پیش. برای خواندن دوباره از اینستاگرام «تازه‌سازی» را بزن.", "ok")
        self.step("read", "done")
        kept = len((ig_store.Section(DATA, "posts").load(rec["username"]) or {}).get("items") or [])
        self.result = {"profile": rec, "cached": True, "age": age, "posts": kept}
        self.outcome, self.state = {"kind": "ok"}, "success"

    async def _open_profile(self, username):
        url = f"{BASE}/{username}/"
        where = await self._open(url, "رفتن به پروفایل " + ltr("@" + username), chooser="continue")
        if where == "form" or (where == "other" and await d.page_kind(self._page) == "chooser"):
            raise Fail("session_invalid", "اینستاگرام صفحهٔ ورود نشان داد؛ نشست معتبر نیست")
        if where == "other" and d.on_challenge(self._page):
            raise Fail("challenge", CHALLENGE_MSG)
        if where == "other":
            if not await d.auth_cookies(self._ctx, BASE):   # the page came, logged out: not a slow line, the login is gone
                raise Fail("session_invalid", "اینستاگرام صفحه را بدون ورود نشان داد؛ نشست این حساب از بین رفته، دوباره وارد شو")
            raise Fail("timeout", "صفحهٔ اینستاگرام درست بالا نیامد")
        if urlparse(self._page.url).path.strip("/").lower() != username.lower() and not await d.not_found_text(self._page):
            # "Continue" on the remembered-account page lands on the home feed, not on the profile.
            self.say("نشست پذیرفته شد؛ دوباره می‌روم به پروفایل")
            try:
                resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
                self._nav_status = resp.status if resp else None
            except Exception as e:
                raise Fail("network", first_line(e))
            Budget(DATA).spend("page")

    async def _read_page(self, username):
        """Wait for the profile to fill in, then read it from every place it shows up."""
        self.step("read", "active")
        self.say("خواندن نام، بیو و عددها")
        page, loop = self._page, asyncio.get_event_loop()
        start, dom, api, meta = loop.time(), {}, {}, {}
        try:
            while True:
                await asyncio.sleep(0.6)
                waited = loop.time() - start
                gone = await d.not_found_text(page)
                if gone or (self._nav_status == 404 and waited > 6):
                    raise Fail("not_found", gone or "اینستاگرام پروفایلی با این یوزرنیم ندارد", gone)
                dom = await page.evaluate(d.JS_PROFILE, username) or {}
                api = pr.from_api([b["text"] for b in self._bodies], username)
                shown = bool(dom.get("stats"))
                if (shown and (api.get("followers") is not None or waited > DOM_ALONE_AFTER)) or waited > READ_FOR:
                    break
            meta = await page.evaluate(d.JS_META)
            merged = pr.merge(username, api, pr.from_dom(dom), pr.from_meta(meta))
            self._posts = await self._wait_posts(username, merged)
            await self._settle(merged)
            self._highlights = am.highlights_from_api(self._texts("PolarisProfileStoryHighlightsTray"))
            self._similar = am.similar_from_api(self._texts("PolarisProfileSuggestedUsers"), username)
            if not pr.readable(merged):
                alert = d.error_text(await d.read_alert(page))
                if alert:
                    raise Fail(d.classify_error(alert), alert, alert)
                if self._limited:
                    raise Fail("rate_limit", "اینستاگرام به درخواست‌های صفحه جواب 429 داد", detail={"http": 429})
                raise Fail("unreadable", "صفحه باز شد ولی پروفایلی در آن پیدا نشد")
        finally:
            self._dump(username, dom, meta)
        self._say_sources(merged, bool(api))
        self.step("read", "done")
        return merged

    def _texts(self, name_start):
        """The captured replies of one query of the profile page, by the start of its name."""
        return [b["text"] for b in self._bodies if (b["friendly"] or "").startswith(name_start)]

    async def _settle(self, merged):
        """The small replies of the page trail the main ones by a moment: wait briefly for those this account should have."""
        wanted = ([] if merged.get("is_private") is True else ["PolarisProfileStoryHighlightsTray"]) \
            + (["PolarisProfileSuggestedUsers"] if (merged.get("more") or {}).get("similar") else [])
        loop = asyncio.get_event_loop()
        end = loop.time() + SETTLE_WAIT
        while loop.time() < end and not all(self._texts(name) for name in wanted):
            await asyncio.sleep(0.3)

    async def _wait_posts(self, username, merged):
        """The posts reply usually lands with the rest; if it has not, give it a few seconds (never for a private or empty account)."""
        loop = asyncio.get_event_loop()
        end = loop.time() + (POSTS_WAIT if (merged.get("posts") or 0) > 0 and merged.get("is_private") is not True else 0)
        while True:
            posts = ap.posts_from_api([b["text"] for b in self._bodies], username, merged.get("user_id"))
            if posts or loop.time() >= end:
                return posts
            await asyncio.sleep(0.5)

    def _say_sources(self, merged, had_api):
        by = {}
        for source in merged["sources"].values():
            by[source] = by.get(source, 0) + 1
        names = {"api": "پاسخ شبکهٔ اینستاگرام", "dom": "خود صفحه", "meta": "برچسب‌های صفحه"}
        self.say("خوانده شد: " + "، ".join(f"{names[k]} ({fa(v)} مورد)" for k, v in by.items()), "ok")
        if not had_api:
            self.say("پاسخ شبکهٔ اینستاگرام نرسید؛ فقط از خود صفحه خوانده شد و بعضی موارد (شناسه، لینک‌ها) ممکن است نباشد", "warn")
        if merged["approx"]:
            self.say("عدد دقیق " + "، ".join({"posts": "پست", "followers": "فالوور", "following": "فالووینگ"}[k] for k in merged["approx"])
                     + " از اینستاگرام نیامد؛ عدد گردشده ذخیره شد", "warn")
        if merged.get("is_private"):
            self.say("این حساب خصوصی است")

    def _dump(self, username, dom, meta):
        """What this read saw, for a human to open when the numbers look wrong (data/last_read.json)."""
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            DUMP.write_text(json.dumps({
                "username": username, "nav_status": self._nav_status, "limited": self._limited, "dom": dom, "meta": meta, "posts_found": len(self._posts), "highlights_found": len(self._highlights), "similar_found": len(self._similar),
                "replies": [{"path": b["path"], "friendly": b["friendly"], "size": len(b["text"]), "text": b["text"][:DUMP_BYTES]}
                            for b in self._bodies[:12]]}, ensure_ascii=False, indent=1), "utf-8")
        except OSError:
            pass

    async def _download(self, url):
        """The avatar bytes, fetched through the browser's own connection and cookies; None if not safe or not an image."""
        if not pr.safe_image_url(url, BASE):
            return None
        try:
            r = await self._ctx.request.get(url, timeout=15000)
            data, kind = await r.body(), (r.headers.get("content-type") or "image/jpeg").split(";")[0]
            return (data, kind) if r.ok and kind.startswith("image/") and len(data) <= 3_000_000 else None
        except Exception:
            return None

    async def _keep_posts(self, rec):
        """Save the posts the page carried, with a small picture each (the picture bytes come from Instagram's image host)."""
        user, posts, media = rec["username"], self._posts, ig_store.Media(DATA)
        pictures = 0
        for post in posts:
            data = await self._download(post.get("thumb"))
            post["has_thumb"] = bool(data and media.put(user, post["code"], data[0]))
            pictures += post["has_thumb"]
            await asyncio.sleep(0.15)
        reason = None if posts else ("private" if rec.get("is_private") else "empty" if not rec.get("posts") else "unread")
        store = ig_store.Section(DATA, "posts")
        old = store.load(user) or {}
        if posts and old.get("items"):
            # a re-read (a watched page twice a day): new posts in front, the ones read before by «پست‌های بیشتر» stay
            fresh = {p["code"] for p in posts}
            kept = sorted(posts + [p for p in old["items"] if p["code"] not in fresh], key=lambda p: p["taken_at"], reverse=True)
            store.save(user, dict(old, items=kept, reason=reason))
        else:
            store.save(user, {"items": posts, "reason": reason})
        if posts:
            self.say(f"{fa(len(posts))} پست خوانده شد و {fa(pictures)} تصویر کوچک ذخیره شد", "ok")
        elif reason == "unread":
            self.say("اینستاگرام پست‌ها را نفرستاد؛ پست‌ها خوانده نشد", "warn")
        return len(posts)

    async def _keep_extras(self, rec):
        """Highlights (their covers are saved) and similar accounts (their pictures stay on Instagram's side)."""
        user, media = rec["username"], ig_store.Media(DATA)
        covers = 0
        for h in self._highlights:
            data = await self._download(h.get("cover"))
            h["has_cover"] = bool(data and media.put(user, "hl_" + h["id"], data[0]))
            covers += h["has_cover"]
            await asyncio.sleep(0.1)
        ig_store.Section(DATA, "highlights").save(user, {"items": self._highlights})
        ig_store.Section(DATA, "similar").save(user, {"items": self._similar})
        if self._highlights:
            self.say(f"{fa(len(self._highlights))} هایلایت خوانده شد و {fa(covers)} کاور ذخیره شد", "ok")
        if self._similar:
            self.say(f"{fa(len(self._similar))} حساب مشابه خوانده شد", "ok")

    async def _keep(self, store, merged):
        self.step("save", "active")
        avatar = await self._download(merged.get("avatar"))
        rec = store.save(pr.build(merged), avatar)
        self.say("ذخیره شد در " + ltr(f"data\\profiles\\p_{rec['username'].lower()}.json")
                 + ("" if avatar else "؛ عکس پروفایل ذخیره نشد"), "ok" if avatar else "warn")
        kept = await self._keep_posts(rec)
        await self._keep_extras(rec)
        self.result = {"profile": rec, "cached": False, "age": 0, "posts": kept}
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.8)
        await self.close()
        self.state = "success"
