"""Reading many profiles fast («پردازش»). A mixin for LoginJob, job mode 'lookup'. One browser session for a whole batch: the
first person's profile is opened like a hand, which teaches us the page's own profile query (PolarisProfilePageContentQuery:
its address, headers and form, the page's live tokens included). Each next person is asked with that same query from inside the
open page, by their numeric id (Instagram's pk never changes, a username can) — one request instead of a whole page.
The tokens are learned again in every session (a token kept from an earlier session is never sent: that is what made Instagram
say «wait» to the old followers reader). Every person counts against the lookup limits; «wait» or «log in again» ends the run."""
import asyncio
import json
import os
import random
import re
from urllib.parse import parse_qsl, urlencode, urlparse

import ig_profile as pr
from ig_budget import Budget
from ig_common import BASE, DATA, Fail, fa, ltr

# OFF until he says so (2026-10-29: «بنویس ولی دیپلوی نکن تا خودم بگم»). On = IGS_FAST_PROFILES=1 in start.sh, then a restart.
# Off, «پردازش» reads one whole profile page per person, as before. The tests turn it on for themselves.
ENABLED = os.environ.get("IGS_FAST_PROFILES") == "1"
QUERY = "PolarisProfilePageContentQuery"
PAUSE = (3.0, 7.0)            # seconds between two people: a person going from profile to profile
REST_EVERY, REST = 20, (20.0, 45.0)
QUERY_WAIT = 30               # seconds the first page has to send its profile query
if not BASE.startswith("https://www.instagram.com"):   # the mock site in the tests: same steps, no waiting
    PAUSE, REST, QUERY_WAIT = (0.05, 0.1), (0.1, 0.2), 10
SEND = re.compile(r"^(x-|content-type$|accept$)", re.I)   # the headers a page may set on its own fetch (the browser adds the rest)

JS_POST = r"""async ([url, headers, body]) => {
  try {
    const r = await fetch(url, {method: 'POST', headers, body, credentials: 'include'});
    return {status: r.status, text: await r.text()};
  } catch (e) { return {status: 0, text: String(e)}; }
}"""


def form_for(form, person):
    """The page's own form with only the person changed: variables.id / user_id get the numeric id, variables.username the name."""
    out = []
    for k, v in form:
        if k == "variables":
            try:
                var = json.loads(v)
            except ValueError:
                var = {}
            for key in ("id", "user_id", "userID", "target_id"):
                if key in var and person.get("id"):
                    var[key] = str(person["id"])
            if "username" in var:
                var["username"] = person["username"]
            v = json.dumps(var, separators=(",", ":"))
        out.append((k, v))
    return urlencode(out)


def node_name(text, pid):
    """The person's current username in a reply asked by id (it may have changed since the list was read)."""
    for doc in pr.parse_body(text):
        stack = [doc]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if str(cur.get("pk") or cur.get("id") or "") == str(pid) and isinstance(cur.get("username"), str):
                    return cur["username"]
                stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
            elif isinstance(cur, list):
                stack.extend(v for v in cur if isinstance(v, (dict, list)))
    return None


class LookupReader:
    async def _grab_query(self, resp):
        """The first profile query the page itself sends: its address, the headers a page may set, and its form."""
        try:
            req = resp.request
            if req.method != "POST" or self._query is not None or resp.status != 200:
                return
            body = req.post_data or ""
            if f"fb_api_req_friendly_name={QUERY}" not in body:
                return
            heads = {k: v for k, v in (await req.all_headers()).items() if SEND.match(k)}
            self._query = {"url": resp.url, "headers": heads, "form": parse_qsl(body, keep_blank_values=True)}
        except Exception:
            return

    async def _lookup(self, username, proxy, options):
        people = [p for p in options.get("people") or [] if p.get("username")]
        if not people:
            raise Fail("other", "کسی برای خواندن نبود")
        budget, store = Budget(DATA), pr.Store(DATA)
        budget.check("page")
        budget.check("lookup")
        self._query, done, failed = None, [], {}
        self.result = {"lookup": {"done": done, "failed": failed, "asked": len(people)}}   # filled as it goes: a stop keeps it
        self.say(f"خواندن سریع {fa(len(people))} پروفایل با یک بار باز کردن مرورگر")
        await self._launch(proxy)
        self._ctx.on("response", lambda r: self._spawn(self._grab_query(r)))
        await self._open_profile(people[0]["username"])     # like a hand: the page sends its own profile query once
        loop = asyncio.get_event_loop()
        end = loop.time() + QUERY_WAIT
        while self._query is None and loop.time() < end:
            await asyncio.sleep(0.25)
        if self._query is None:
            raise Fail("no_query", "صفحهٔ پروفایل درخواست همیشگی‌اش را نفرستاد؛ خواندن سریع این بار ممکن نشد")
        self.step("read", "active")
        q = self._query
        for i, person in enumerate(people):
            budget.check("lookup")                            # a full hour or day ends the run; what was read is saved one by one
            if i:
                await asyncio.sleep(random.uniform(*(REST if i % REST_EVERY == 0 else PAUSE)))
            r = await self._page.evaluate(JS_POST, [q["url"], q["headers"], form_for(q["form"], person)])
            budget.spend("lookup")
            status, text = r.get("status"), r.get("text") or ""
            if status == 429 or re.search(r"feedback_required|wait a few minutes|try again later|spam", text[:3000], re.I):
                raise Fail("rate_limit", f"اینستاگرام گفت صبر کن؛ خواندن سریع بعد از {fa(len(done))} نفر متوقف شد", detail={"http": status})
            if re.search(r"login_required|checkpoint_required|challenge_required", text[:3000], re.I):
                raise Fail("session_invalid", "اینستاگرام برای ادامه دوباره ورود خواست", detail={"http": status})
            name = (node_name(text, person["id"]) if person.get("id") else None) or person["username"]
            merged = pr.merge(name, pr.from_api([text], name), {}, {})
            if status != 200 or not pr.readable(merged):
                failed[person["username"]] = "not_found" if status == 200 else f"http_{status}"
                continue
            rec = store.save(pr.build(merged), await self._download(merged.get("avatar")))
            done.append(person["username"])
            if rec["username"].lower() != person["username"].lower():
                self.say(f"{ltr('@' + person['username'])} یوزرنیمش را عوض کرده: {ltr('@' + rec['username'])}")
            if len(done) % 5 == 0 or i == len(people) - 1:
                self.say(f"{fa(len(done))} از {fa(len(people))} پروفایل خوانده شد" + (f"، {fa(len(failed))} نفر خوانده نشد" if failed else ""))
        self.step("read", "done")
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(0.5)
        await self.close()
        self.state = "success"
