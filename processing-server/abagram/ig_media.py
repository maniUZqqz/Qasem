"""Downloading the pictures and videos of posts, highlights and the active story to disk. A mixin for LoginJob that needs no browser:
the addresses come from the saved data, the files from Instagram's picture hosts (the way a page loads them). Only what was asked for
is fetched, a file or a whole job above the limits is skipped, and an address that has expired says so instead of failing in silence."""
import asyncio
import time

import httpx

import ig_detect as d
import ig_files as fl
import ig_profile as pr
import ig_store
from ig_budget import Budget
from ig_common import BASE, DATA, Fail, fa

AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
CHUNK = 64 * 1024
MB = 1024 * 1024
TARGETS = ("posts", "highlights", "story")
WHY = {"expired": "آدرس منقضی شده", "too_big": "از سقف حجم یک فایل بزرگ‌تر است", "job_mb": "به سقف حجم این دانلود خورد", "bad": "فایل عکس یا ویدیو نبود",
       "failed": "دانلود نشد"}


class MediaReader:
    def _media_plan(self, username, options):
        """The files to fetch for what he chose, from the saved data. Highlights are never taken without a choice."""
        target, videos = options.get("target"), options.get("videos", True)
        if target == "posts":
            posts = (ig_store.Section(DATA, "posts").load(username) or {}).get("items") or []
            if not posts:
                raise Fail("no_posts", "برای این پروفایل پستی ذخیره نشده؛ اول پروفایل را بخوان.")
            plan = fl.plan_posts(posts, options.get("codes"), videos)
        elif target == "highlights":
            if not options.get("ids"):
                raise Fail("no_selection", "هایلایت‌ها فقط با انتخاب خودت دانلود می‌شوند؛ هایلایت‌ها را مشخص کن.")
            saved = (ig_store.Section(DATA, "reels").load(username) or {}).get("highlights") or {}
            plan = [x for hid in options["ids"] if saved.get(hid) for x in fl.plan_reel(saved[hid], f"h{hid}_", options.get("items"), videos)]
        elif target == "story":
            reel = (ig_store.Section(DATA, "stories").load(username) or {}).get("reel")
            plan = fl.plan_reel(reel, "s", options.get("items"), videos) if reel else []
        else:
            raise Fail("error", "نوع دانلود را نمی‌شناسم")
        if not plan:
            raise Fail("no_media", "چیزی برای دانلود پیدا نشد؛ اول آیتم‌ها را بخوان (پروفایل، هایلایت یا استوری).")
        return plan

    async def _media(self, username, proxy, options):
        limits, files = Budget(DATA).limits(), fl.Files(DATA)
        self.step("plan", "active")
        plan = self._media_plan(username, options)
        planned, plan = len(plan), plan[: limits["media_files"]]
        self.say(f"{fa(len(plan))} فایل برای دانلود" + (f" (از {fa(planned)}؛ بقیه به سقف «فایل در هر دانلود» خورد)" if planned > len(plan) else ""))
        self.step("plan", "done")
        self.step("download", "active")
        max_bytes, job_bytes = limits["media_file_mb"] * MB, limits["media_job_mb"] * MB
        out = {"planned": planned, "saved": 0, "had": 0, "expired": 0, "too_big": 0, "bad": 0, "failed": 0, "bytes": 0, "stopped": None}
        try:
            client = httpx.AsyncClient(proxy=proxy or None, follow_redirects=True, timeout=httpx.Timeout(30.0, read=60.0),
                                       headers={"User-Agent": AGENT, "Accept": "*/*", "Referer": BASE + "/"})
        except Exception as e:   # for example a socks5 proxy without the optional package
            raise Fail("network", f"اتصال دانلود ساخته نشد: {e}")
        async with client:
            fetched = 0
            for i, item in enumerate(plan, 1):
                if files.path(username, item["key"]) and not options.get("again"):
                    out["had"] += 1
                    continue
                gone = fl.expiry_of(item["url"])
                if (gone and gone < time.time()) or not pr.safe_image_url(item["url"], BASE):
                    out["expired" if gone and gone < time.time() else "bad"] += 1
                    continue
                if out["bytes"] >= job_bytes:
                    out["stopped"] = "job_mb"
                    break
                if fetched:
                    await d.pause(0.25, 0.7)
                fetched += 1
                why, size = await self._fetch(client, files, username, item, max_bytes, job_bytes - out["bytes"])
                if why == "saved":
                    out["saved"] += 1
                    out["bytes"] += size
                    if out["saved"] % 5 == 0 or item["type"] == "video":
                        self.say(f"{fa(i)} از {fa(len(plan))}: {item['key']} ({size / MB:.1f} مگابایت)")
                    continue
                self.say(f"{item['key']}: {WHY.get(why, WHY['failed'])}", "warn")
                if why == "job_mb":
                    out["stopped"] = "job_mb"
                    break
                out[why if why in out else "failed"] += 1
        self.step("download", "done")
        self.step("save", "active")
        if not out["saved"] and not out["had"] and out["expired"]:
            raise Fail("expired", "آدرس فایل‌ها منقضی شده؛ دوباره بخوان (پروفایل، هایلایت یا استوری) و بعد دانلود کن.")
        tail = [f"{fa(out[k])} {label}" for k, label in (("had", "از قبل بود"), ("expired", "منقضی"), ("too_big", "بزرگ‌تر از سقف"), ("failed", "ناموفق")) if out[k]]
        self.say(f"{fa(out['saved'])} فایل دانلود شد، {out['bytes'] / MB:.1f} مگابایت" + (" (" + "؛ ".join(tail) + ")" if tail else ""), "ok" if out["saved"] or out["had"] else "warn")
        self.result = {"profile": pr.Store(DATA).load(username), "cached": False, "age": 0, "section": "download", "target": options.get("target"), "files": out}
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.3)
        self.state = "success"

    async def _fetch(self, client, files, username, item, max_bytes, room):
        """One file into place. ('saved', bytes) or (the reason it was not saved, 0)."""
        part = files.partial(username, item["key"])
        limit = min(max_bytes, room)
        try:
            async with client.stream("GET", item["url"]) as r:
                if r.status_code == 429:
                    raise Fail("rate_limit", "سرور تصویرهای اینستاگرام به یکی از درخواست‌ها جواب 429 داد", detail={"http": 429})
                if r.status_code != 200:
                    return ("expired" if r.status_code in (403, 404, 410) else "failed"), 0
                declared = int(r.headers.get("content-length") or 0)
                written = 0
                if declared > limit:
                    return ("too_big" if declared > max_bytes else "job_mb"), 0
                with open(part, "wb") as f:
                    async for chunk in r.aiter_bytes(CHUNK):
                        written += len(chunk)
                        if written > limit:
                            return ("too_big" if written > max_bytes else "job_mb"), 0
                        f.write(chunk)
            with open(part, "rb") as f:
                kind = fl.sniff(f.read(16))
            if kind is None or kind.split("/")[0] != item["type"]:
                return "bad", 0
            files.commit(username, item["key"], part, kind)
            return "saved", written
        except httpx.HTTPError:
            return "failed", 0
        finally:
            part.unlink(missing_ok=True)
