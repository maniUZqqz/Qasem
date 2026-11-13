"""Sending a follow request to a private account, the way a hand would: open the profile, press «Follow», and read
Instagram's own answer (POST /api/v1/friendships/create/<id>/ → friendship_status). Only private accounts get a
request (a public one would be followed at once — never done silently). A mixin for LoginJob."""
import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import ig_detect as d
import ig_profile as pr
from ig_budget import Budget
from ig_common import DATA, Fail, fa, ltr

CREATE = re.compile(r"^/api/v1/friendships/create/\d+/?$")
JS_FOLLOW_STATE = r"""() => {
  const texts = [...document.querySelectorAll('main button, main [role=button], header button')].map(b => (b.innerText || '').trim());
  const state = texts.includes('Following') ? 'following' : texts.includes('Requested') ? 'requested'
    : texts.some(t => t === 'Follow' || t === 'Follow Back') ? 'follow' : null;
  return {state, private: /This account is private|This Account is Private/i.test(document.body.innerText || '')};
}"""
FILE = DATA / "requests.json"


def load_requests():
    data = pr.read_json(FILE, {}, backup=True)
    return data if isinstance(data, dict) else {}


def save_request(username, **fields):
    data = load_requests()
    rec = dict(data.get(username.lower(), {}), **fields)
    data[username.lower()] = rec
    DATA.mkdir(parents=True, exist_ok=True)
    pr.write_atomic(FILE, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"), backup=True)
    return rec


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RequestReader:
    async def _follow_state(self, wait=12):
        loop = asyncio.get_event_loop()
        end, seen = loop.time() + wait, {}
        while loop.time() < end:
            seen = await self._page.evaluate(JS_FOLLOW_STATE) or {}
            if seen.get("state"):
                break
            await asyncio.sleep(0.5)
        return seen

    async def _request_follow(self, username, proxy, options):
        budget = Budget(DATA)
        budget.check("page")
        budget.check("scroll")
        self.say("فرستادن درخواست فالو به " + ltr("@" + username))
        answers = []

        async def grab(resp):
            try:
                if resp.request.method == "POST" and CREATE.match(urlparse(resp.url).path):
                    answers.append((resp.status, await resp.text()))
            except Exception:
                return

        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(grab(r)))
        await self._open_profile(username)
        gone = await d.not_found_text(self._page)
        if gone:
            raise Fail("not_found", gone, gone)
        self.step("read", "active")
        seen = await self._follow_state()
        state = seen.get("state")
        if state == "follow" and not seen.get("private"):
            raise Fail("public", "این حساب عمومی است؛ اطلاعاتش بدون فالو خوانده می‌شود و درخواستی فرستاده نشد.")
        if state == "follow":
            await d.pause(0.6, 1.4)
            try:
                await self._page.locator("main button, header button", has_text=re.compile(r"^\s*Follow( Back)?\s*$")).first.click(timeout=5000)
            except Exception:
                raise Fail("no_button", "دکمهٔ «Follow» در صفحه پیدا نشد یا کلیک نشد.")
            budget.spend("scroll")
            for _ in range(32):
                if answers:
                    break
                await asyncio.sleep(0.25)
            status, text = answers[0] if answers else (None, "")
            if status == 429 or re.search(r"feedback_required|wait a few minutes|spam", text or "", re.I):
                raise Fail("rate_limit", "اینستاگرام گفت صبر کن", (re.search(r'"message"\s*:\s*"([^"]+)"', text or "") or [None, None])[1], {"http": status})
            after = await self._follow_state(wait=6)
            state = after.get("state") or ("requested" if status == 200 else None)
            if state not in ("requested", "following"):
                raise Fail("unreadable", "درخواست فرستاده شد ولی جواب روشنی نیامد؛ بعداً وضعیت را بررسی کن.", detail={"http": status})
        if state is None:
            raise Fail("unreadable", "وضعیت فالو در صفحه پیدا نشد.")
        rec = save_request(username, state=state, requested_at=load_requests().get(username.lower(), {}).get("requested_at") or now_iso(),
                           checked_at=now_iso())
        word = {"requested": "درخواست فرستاده شد؛ منتظر قبول", "following": "این حساب را دنبال می‌کنی"}[state]
        self.say(word, "ok")
        self.step("read", "done")
        self.step("save", "done")
        self.result = {"profile": pr.Store(DATA).load(username), "cached": False, "age": 0, "section": "request", "request": rec}
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.8)
        await self.close()
        self.state = "success"
