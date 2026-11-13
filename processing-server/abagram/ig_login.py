"""One job at a time: drives a real Chromium window through Instagram (login, session check, profile read)."""
import asyncio
import base64
import json
import re
import shutil
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import async_playwright

import ig_accounts
import ig_detect as d
import ig_prefs
import ig_profile as pr
import ig_runs
from ig_budget import Budget
from ig_common import BASE, DATA, HEADLESS, Busy, Fail, browser_opts, first_line, ltr
from ig_deep import DeepReader
from ig_browse import BrowseReader
from ig_follow import FollowReader
from ig_grid import GridReader
from ig_harvest import HarvestReader
from ig_lookup import LookupReader
from ig_media import MediaReader
from ig_request import RequestReader
from ig_reader import ProfileReader
from ig_reels import ReelReader

SHOT = DATA / "last.png"      # the browser folder and the session note belong to the active account (ig_accounts)
BUDGET = Budget(DATA)   # one count of what was asked of Instagram, shared by every job
LOGIN_URL = BASE + "/accounts/login/"
LOGIN_STEPS = ("browser", "page", "credentials", "answer", "save")
READ_STEPS = ("browser", "page", "read", "save")
STEPS_BY_MODE = {"login": LOGIN_STEPS, "check": LOGIN_STEPS, "profile": READ_STEPS, "details": READ_STEPS, "stories": READ_STEPS, "highlights": READ_STEPS, "follow": READ_STEPS, "posts": READ_STEPS, "request": READ_STEPS, "harvest": READ_STEPS, "lookup": READ_STEPS,
                 "browse": READ_STEPS, "download": ("plan", "download", "save")}
# Only these fields of Instagram's login reply are kept (never request bodies, never cookies).
API_KEYS = ("message", "status", "error_type", "authenticated", "user", "two_factor_required",
            "checkpoint_url", "lock", "spam", "fail_text", "feedback_title", "feedback_message")


def read_meta(account=None):
    """The session note of an account (the active one by default)."""
    try:
        return json.loads(ig_accounts.meta_file(account).read_text("utf-8"))
    except Exception:
        return None


def write_meta(username, user_id, account=None):
    meta = ig_accounts.meta_file(account)                         # taken first: an account's folder never changes with its name
    name = ig_accounts.set_identity(username, user_id, account)   # that account's entry is this person (its typed name may differ)
    meta.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pr.write_atomic(meta, json.dumps({"username": name, "user_id": user_id, "saved_at": stamp},
                                     ensure_ascii=False).encode("utf-8"))   # a power cut never leaves a broken note (= logged out)


def mark_lost(account=None):
    """Instagram threw the account out (a run ended as session_invalid). The note keeps who it was but says the login is gone, so
    the site asks for a new login and the queue waits for it instead of opening logged-out windows (2026-10-30: «ادامه» pressed four
    times on a logged-out account, every run ending on «continue as … / use another profile»). A new login writes a fresh note."""
    meta = read_meta(account)
    if meta and not meta.get("lost_at"):
        meta["lost_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        pr.write_atomic(ig_accounts.meta_file(account), json.dumps(meta, ensure_ascii=False).encode("utf-8"))


def clear_saved_session():
    """Forget the ACTIVE account's saved login (its browser folder and note); the other accounts are not touched."""
    folder = ig_accounts.profile_dir()
    shutil.rmtree(folder, ignore_errors=True)
    ig_accounts.meta_file().unlink(missing_ok=True)
    return not folder.exists()


def has_profile():
    try:
        folder = ig_accounts.profile_dir()
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False


async def shutdown(ctx, pw):
    # Closing a browser whose page is wedged (Instagram unreachable) can hang forever; a timeout means a cancel always finishes.
    try:
        if ctx:
            await asyncio.wait_for(ctx.close(), timeout=15)
    except Exception:
        try:
            if ctx and ctx.browser:
                await asyncio.wait_for(ctx.browser.close(), timeout=5)
        except Exception:
            pass
    try:
        if pw:
            await asyncio.wait_for(pw.stop(), timeout=10)
    except Exception:
        pass


class LoginJob(ProfileReader, DeepReader, ReelReader, FollowReader, HarvestReader, LookupReader, BrowseReader, GridReader, MediaReader,
               RequestReader):
    def __init__(self):
        self.run = 0
        self.on_finish = None    # called with the final snapshot of every run (the queue listens)
        self.options = {}
        self._reset()

    def _reset(self):
        self.state, self.mode, self.username, self.cur = "idle", None, None, None
        self.account = None      # the account this job works for: the active one, or (a login only) the one being logged in
        self.log, self.outcome, self.result = [], None, None
        self.steps = {k: "idle" for k in LOGIN_STEPS}
        self._task = self._ctx = self._pw = self._page = self._api = None
        self._code = asyncio.Queue()
        self._bg = set()
        self._shots = 0
        self._nav_status = None
        self._reset_reader()
        self._reset_deep()
        self._reset_reels()
        self._reset_follow()
        self._reset_grid()

    @property
    def busy(self):
        return self.state in ("running", "need_code", "need_manual")

    def say(self, msg, level="info"):
        self.log.append({"i": len(self.log), "t": time.strftime("%H:%M:%S"),
                         "level": level, "msg": msg, "step": self.cur})

    def step(self, key, state):
        if state == "active":
            self.cur = key
        self.steps[key] = state

    def snapshot(self, since=0):
        return {"run": self.run, "state": self.state, "mode": self.mode, "busy": self.busy, "username": self.username or None,
                "started_at": getattr(self, "started_at", None), "options": self.options, "queued": getattr(self, "queued", None),
                "steps": [{"key": k, "state": v} for k, v in self.steps.items()],
                "log": self.log[since:], "next": len(self.log),
                "outcome": self.outcome, "result": self.result,
                "browser_open": self._ctx is not None, "session": read_meta(), "profile_exists": has_profile(), "budget": BUDGET.snapshot()}

    def start(self, mode, username="", password="", proxy="", fresh=False, options=None):
        if self.busy or (self._task and not self._task.done()):
            raise Busy()  # also while the previous attempt is still closing its window
        old = (self._ctx, self._pw)
        self._reset()
        self.run += 1
        self.state, self.mode, self.username = "running", mode, username
        self.started_at = time.time()
        self.options = {k: v for k, v in (options or {}).items() if k != "password"}
        self.queued = (options or {}).get("_task")
        who = (options or {}).get("account")
        self.account = who.lower() if mode == "login" and who and who.lower() != (ig_accounts.listing()["active"] or "") else None
        self.steps = {k: "idle" for k in STEPS_BY_MODE[mode]}
        self._task = asyncio.create_task(self._run(mode, username, password, proxy, old, fresh, options or {}))

    def submit_code(self, code):
        if self.state == "need_code":
            self._code.put_nowait(code)
            return True
        return False

    # Chromium without a window (the server): the site shows Instagram's page live and passes his clicks and typing on.
    def remote_ok(self):
        return self._page is not None and self.state in ("need_manual", "need_code")

    async def remote_view(self):
        """Chrome's own capture (CDP): Playwright's screenshot waits for fonts and animations to settle, and on some of
        Instagram's pages (codeentry) that never happens."""
        if not self.remote_ok():
            return None
        page = self._page
        try:
            if getattr(self, "_cdp_page", None) is not page:
                self._cdp, self._cdp_page = await self._ctx.new_cdp_session(page), page
            shot = await asyncio.wait_for(self._cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70}), 6)
            return base64.b64decode(shot["data"])
        except Exception:
            self._cdp_page = None
        try:
            return await page.screenshot(type="jpeg", quality=70, timeout=4000, animations="disabled")
        except Exception:
            return None

    async def remote_input(self, x=None, y=None, text="", key="", dy=None):
        """x, y are fractions of the picture (0..1). Never logged: what he types may be a code."""
        if not self.remote_ok():
            return False
        try:
            if x is not None and y is not None:
                size = self._page.viewport_size or {"width": 1280, "height": 860}
                await self._page.mouse.click(x * size["width"], y * size["height"])
            if text:
                await self._page.keyboard.type(text, delay=60)
            if key:
                await self._page.keyboard.press(key)
            if dy:
                await self._page.mouse.wheel(0, dy)
            return True
        except Exception:
            return False

    def cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
        elif self._ctx is not None:
            self._spawn(self.close())

    async def close(self):
        ctx, pw, self._ctx, self._pw, self._page = self._ctx, self._pw, None, None, None
        await shutdown(ctx, pw)

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    @staticmethod
    def proxy_opts(proxy):
        u = urlparse(proxy)
        opts = {"server": f"{u.scheme}://{u.hostname}" + (f":{u.port}" if u.port else "")}
        if u.username:
            opts["username"], opts["password"] = u.username, u.password or ""
        return opts

    async def _run(self, mode, username, password, proxy, old, fresh=False, options=None):
        try:
            await shutdown(*old)
            if mode == "check":
                await self._check(proxy)
            elif mode == "profile":
                await self._profile(username, proxy, fresh)
            elif mode == "details":
                await self._details(username, proxy, options or {})
            elif mode in ("stories", "highlights"):
                await self._reels(mode, username, proxy, options or {})
            elif mode == "follow":
                await self._follow(username, proxy, options or {})
            elif mode == "harvest":
                await self._harvest(username, proxy, options or {})
            elif mode == "lookup":
                await self._lookup(username, proxy, options or {})
            elif mode == "browse":
                await self._browse(username, proxy, options or {})
            elif mode == "posts":
                await self._more_posts(username, proxy, options or {})
            elif mode == "download":
                await self._media(username, proxy or ig_prefs.load()["proxy"], options or {})
            elif mode == "request":
                await self._request_follow(username, proxy, options or {})
            else:
                await self._login(username, password, proxy)
        except asyncio.CancelledError:
            self.outcome = {"kind": "cancelled"}
            self.say("لغو شد؛ مرورگر بسته شد", "warn")
            try:
                await self.close()
            finally:
                self.state = "cancelled"   # the cancel always finishes, even if closing the window failed
        except Fail as f:
            await self._fail(f)
        except Exception as e:
            await self._fail(Fail("error", first_line(e)))
        finally:
            password = None  # never kept past the attempt
            try:
                # «فعالیت»: this run, its steps and its whole log — and the window's last picture when this run took one
                ig_runs.record(self.snapshot(0), SHOT if self._shots and SHOT.exists() else None)
            except Exception:
                pass
            if self.on_finish:
                try:
                    self.on_finish(self.snapshot(len(self.log)))
                except Exception:
                    pass

    async def _fail(self, f):
        for key, state in self.steps.items():
            if state == "active":
                self.steps[key] = "failed"
        detail, shown = dict(f.detail or {}), None
        if f.kind in ("timeout", "other", "session_invalid", "unreadable", "challenge") and self._page:
            detail.update(await d.describe_page(self._page))  # what the unfamiliar page offered
            shown = await d.page_text(self._page)
        if f.msg and not detail:
            detail["error"] = f.msg
        if f.kind == "rate_limit":
            BUDGET.cool(f.ig_message or f.msg or "rate limit")  # Instagram said wait: stay quiet for a while
        if f.kind == "session_invalid":
            try:
                mark_lost(self.account)
            except Exception:
                pass
        self.outcome = {"kind": f.kind, "ig_message": f.ig_message, "page_text": shown, "detail": detail or None,
                        "note": f.msg if f.kind in ("budget", "cooldown") else None, "shot": await self._snap()}
        if f.kind in ("not_found", "budget", "cooldown"):
            await self.close()  # the screenshot and Instagram's own sentence say it all; a limit has nothing to show in a window
        self.state = "failed"
        if f.ig_message:
            line = "اینستاگرام: " + ltr(f.msg)
        elif f.kind in ("network", "browser", "error"):
            line = ltr(f.msg or f.kind)  # raw English error text from the browser
        else:
            line = f.msg or f.kind
        self.say(line, "err")

    async def _snap(self):
        """Screenshot of the Instagram window, so a wrong parse never hides what it showed."""
        if not self._page:
            return False
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(SHOT), timeout=8000)
            self._shots += 1
            return self._shots
        except Exception:
            return False

    async def _launch(self, proxy):
        self.step("browser", "active")
        self.say("باز کردن مرورگر (Chromium)")
        PROFILE = ig_accounts.profile_dir(self.account)          # this job's account: the active one's folder, or the one being logged in
        PROFILE.mkdir(parents=True, exist_ok=True)
        # Without a window unless he turned «نمایش پنجرهٔ Chromium» on (IGS_HEADLESS=1 forces it off for the tests).
        opts = dict(user_data_dir=str(PROFILE), headless=HEADLESS or not ig_prefs.load()["show_browser"], locale="en-US",
                    viewport={"width": 1280, "height": 860},
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"], **browser_opts())
        proxy = proxy or ig_prefs.load()["proxy"]      # his saved proxy when a job (the queue) passed none
        if proxy:
            opts["proxy"] = self.proxy_opts(proxy)
            self.say("اتصال از راه پراکسی " + ltr(opts["proxy"]["server"]))
        try:
            self._pw = await async_playwright().start()
            try:
                # Playwright switches the sandbox off by default, which makes Chromium show a scary banner.
                self._ctx = await self._pw.chromium.launch_persistent_context(chromium_sandbox=True, **opts)
            except Exception:
                self._ctx = await self._pw.chromium.launch_persistent_context(**opts)
        except Exception as e:
            raise Fail("browser", first_line(e))
        self._ctx.on("response", lambda r: self._spawn(self._on_response(r)))
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        self.step("browser", "done")

    async def _on_response(self, resp):
        """Keep the useful fields of Instagram's own login reply (it says if the user exists)."""
        if resp.request.method != "POST":
            return
        path = urlparse(resp.url).path
        if not re.search(r"/accounts/login|two_factor|/challenge", path):
            return
        info = {"http": resp.status, "path": path}
        try:
            body = await resp.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            info.update({k: str(body[k])[:200] for k in API_KEYS if k in body})
        self._api = info
        self.say("پاسخ سرور اینستاگرام: " + ltr(f"HTTP {resp.status}" + (f" ({info['status']})" if "status" in info else "")))

    async def _open(self, url, label, chooser="another", login=False):
        """Load url and settle on a page we know: 'form', 'home' or 'other' (the step stays open then).
        Instagram's "continue as <remembered account>" page is pressed through here: chooser='another'
        goes on with new credentials, chooser='continue' reuses the remembered account."""
        self.step("page", "active")
        self.say(label)
        try:
            resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            self._nav_status = resp.status if resp else None
        except Exception as e:
            raise Fail("network", first_line(e))
        BUDGET.spend("page")
        loop = asyncio.get_event_loop()
        end, n, presses, last = loop.time() + 75, 0, 0, 0.0   # through the VPN a page can take over half a minute to draw
        while loop.time() < end:
            if n % 4 == 0 and await d.dismiss_cookie_banner(self._page):
                self.say("پنجرهٔ کوکی بسته شد")
            n += 1
            kind = await d.page_kind(self._page)
            if kind in ("form", "home"):
                self.step("page", "done")
                return kind
            if not login and d.on_challenge(self._page):   # every address goes there until a person passes it: no use waiting
                return "other"
            if n % 4 == 2:
                if login and await d.unavailable(self._page):   # only the login page: elsewhere it means «not found»
                    return "other"
                if re.search(r"wait a few minutes|try again later", await d.page_text(self._page) or "", re.I):
                    return "other"                               # Instagram said wait: the page will not come
            now = loop.time()
            if kind == "chooser" and presses < 3 and now - last > 6:
                presses, last = presses + 1, now
                who = await d.chooser_account(self._page)
                self.say("اینستاگرام صفحهٔ «ادامه با حساب قبلی» نشان داد" + (" (" + ltr(who) + ")" if who else "")
                         + "؛ " + ("ادامه با همان حساب را می‌زنم" if chooser == "continue" else "«حساب دیگر» را می‌زنم"))
                await d.click_button(self._page, d.RE_CONTINUE if chooser == "continue" else d.RE_ANOTHER)
            await asyncio.sleep(0.5)
        return "other"

    async def _login(self, username, password, proxy):
        await self._launch(proxy)
        # A new login replaces the saved one: drop its auth cookies, keep the device cookies.
        for name in ("sessionid", "ds_user_id"):
            try:
                await self._ctx.clear_cookies(name=name)
            except Exception:
                pass
        where = await self._open(LOGIN_URL, "رفتن به صفحهٔ ورود اینستاگرام", login=True)
        if where == "other":   # «Page isn't available» on /accounts/login/: the home page carries the form now
            where = await self._open(BASE + "/", "صفحهٔ ورود باز نشد؛ ورود از صفحهٔ اصلی اینستاگرام")
        if where == "home":
            return await self._finish_reused("نشست قبلی هنوز معتبر بود")
        if where == "other":
            raise Fail("timeout", "صفحهٔ ورود اینستاگرام درست بالا نیامد")
        page = self._page
        self.step("credentials", "active")
        self.say("تایپ یوزرنیم و پسورد، مثل یک آدم")
        await d.pause(0.4, 0.9)
        await self._click_field(page, d.SEL_USER)
        await d.human_type(page, username)
        await d.pause(0.3, 0.8)
        await self._click_field(page, d.SEL_PASS)
        await d.human_type(page, password)
        await d.pause(0.4, 0.9)
        self._api = None
        await page.keyboard.press("Enter")
        self.step("credentials", "done")
        self.say("فرم ارسال شد؛ منتظر پاسخ اینستاگرام")
        await self._await_answer()
        await self._save(username)

    async def _click_field(self, page, selector):
        """A click on a login field. Instagram's cookie window can come a few seconds after the form (2026-11-10, exit FI:
        «Allow the use of cookies…» covered the form and the click waited 30 s for nothing): it is closed and the click tried
        again."""
        for attempt in range(3):
            try:
                await page.locator(selector).first.click(timeout=10000)
                return
            except Exception:
                if attempt == 2:
                    raise
                if await d.dismiss_cookie_banner(page):
                    self.say("پنجرهٔ کوکی بسته شد")
                await asyncio.sleep(1.0)

    async def _publish(self, kind, msg=None):
        """What the page shows when a step needs the human; the caller flips the state after this."""
        shot = await self._snap()
        self.outcome = {"kind": kind, "ig_message": msg, "page_text": await d.page_text(self._page),
                        "detail": await d.describe_page(self._page), "shot": shot}

    async def _await_answer(self):
        """Poll the page until Instagram accepts, asks for something, or refuses."""
        self.step("answer", "active")
        loop = asyncio.get_event_loop()
        started = loop.time()
        deadline = started + 150   # through the VPN Instagram can take over a minute to answer the form
        sent_at, tries, manual, blank_at = None, 0, False, None
        while True:
            await asyncio.sleep(0.6)
            now = loop.time()
            p = await d.probe(self._page, self._ctx, BASE)
            blank_at = (blank_at or now) if p.kind == "pending" and not p.form else None
            lost = blank_at is not None and now - blank_at > 8  # a page we were never taught, for 8 s
            if manual and not (p.kind == "need_manual" or lost):
                manual, self.state = False, "running"
            if p.kind == "logged_in":
                self.step("answer", "done")
                self.say("اینستاگرام ورود را پذیرفت", "ok")
                return
            if p.kind == "error":
                kind = d.classify_error(p.text, "code" if sent_at else "login")
                raise Fail(d.refine(kind, self._api), p.text, p.text, self._api)
            if p.kind == "need_code":
                rejected = sent_at is not None and now - sent_at > 2 and d.error_text(p.text)
                if sent_at is not None and not rejected:
                    if now > deadline:
                        raise Fail("timeout", "اینستاگرام به کد جواب نداد", detail=self._api)
                    continue
                if rejected:
                    tries += 1
                    self.say("کد قبول نشد: " + ltr(p.text), "err")
                    if tries >= 3:
                        raise Fail("bad_code", p.text, p.text, self._api)
                if await self._ask_code(p.text if rejected else None):
                    sent_at = loop.time()
                    deadline = sent_at + 60
                continue
            if p.kind == "need_manual" or lost:
                if not manual:
                    manual = True
                    deadline = max(deadline, now + 600)
                    await self._publish("challenge", d.error_text(p.text))
                    self.state = "need_manual"
                    self.say("اینستاگرام صفحه‌ای نشان داد که باید خودت در پنجرهٔ مرورگر انجامش بدهی", "warn")
                if now > deadline:
                    raise Fail("timeout", "این مرحله در پنجرهٔ مرورگر انجام نشد")
                continue
            if now > deadline:
                raise Fail("timeout", "جواب روشنی از اینستاگرام نیامد", detail=self._api)
            if p.form and now - started > 120:  # the form is still there and nothing we know of was said (its button spins meanwhile)
                raise Fail("timeout", "اینستاگرام بعد از ارسال فرم چیزی که بشناسم نشان نداد", detail=self._api)

    async def _ask_code(self, error):
        """Show the code box in the site and wait for a code. False if the page moved on by itself
        (the code was typed in the window, or another way was chosen there)."""
        await self._publish("two_factor", error)
        self.state = "need_code"  # after the outcome is complete, so the page never shows a half-filled card
        self.say("اینستاگرام کد تأیید خواست؛ کد را در سایت (یا در خود پنجره) وارد کن", "warn")
        loop = asyncio.get_event_loop()
        end = loop.time() + 300
        while True:
            try:
                code = await asyncio.wait_for(self._code.get(), 1.0)
                break
            except asyncio.TimeoutError:
                pass
            if loop.time() > end:
                raise Fail("timeout", "کدی وارد نشد")
            if (await d.probe(self._page, self._ctx, BASE)).kind != "need_code":
                self.state = "running"
                self.say("صفحهٔ اینستاگرام خودش جلو رفت")
                return False
        self.state = "running"
        self.say("تایپ کد در صفحهٔ اینستاگرام")
        field = await d.code_locator(self._page)
        await field.fill("")
        await field.click()
        await d.human_type(self._page, code)
        await d.pause(0.4, 0.8)
        if not await d.click_button(self._page, r"^(continue|confirm|submit|next|verify)$"):
            await self._page.keyboard.press("Enter")
        return True

    async def _dismiss_prompts(self):
        """Instagram's 'Save your login info?' and notification prompts. Save info keeps this browser trusted."""
        await asyncio.sleep(1.5)
        for _ in range(4):
            clicked = await d.click_button(self._page, r"^save info$") or await d.click_button(self._page, r"^not now$")
            if not clicked:
                break
            self.say("یک پنجرهٔ پیشنهادی اینستاگرام بسته شد")
            await asyncio.sleep(1.5)

    async def _save(self, username):
        self.step("save", "active")
        self.say("بستن پیشنهادهای اینستاگرام و خواندن نام حساب")
        await self._dismiss_prompts()
        who = await d.read_identity(self._page) or {}
        uid = ((await d.auth_cookies(self._ctx, BASE)) or {}).get("user_id")
        name = who.get("username") or username
        self.result = {"username": name, "user_id": uid, "avatar": who.get("avatar"),
                       "reused": False, "verified": bool(who)}
        write_meta(name, uid, self.account)
        self.say("نشست برای " + ltr("@" + name) + " ذخیره شد", "ok")
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(1.0)
        await self.close()  # closing flushes the cookies to the profile folder
        self.state = "success"  # only now: a new attempt must not start while the old window closes

    async def _finish_reused(self, label):
        self.step("credentials", "skipped")
        self.step("answer", "done")
        self.step("save", "active")
        self.say(label, "ok")
        await self._dismiss_prompts()
        who = await d.read_identity(self._page) or {}
        uid = ((await d.auth_cookies(self._ctx, BASE)) or {}).get("user_id")
        name = who.get("username") or (read_meta(self.account) or {}).get("username")
        self.result = {"username": name, "user_id": uid, "avatar": who.get("avatar"),
                       "reused": True, "verified": bool(who)}
        if not read_meta(self.account):
            write_meta(name or "", uid, self.account)  # a session found in the profile, e.g. one finished by hand
        self.step("save", "done")
        self.outcome = {"kind": "ok"}
        await asyncio.sleep(1.0)
        await self.close()
        self.state = "success"

    async def _check(self, proxy):
        await self._launch(proxy)
        where = await self._open(BASE + "/", "باز کردن اینستاگرام با نشست ذخیره‌شده", chooser="continue")
        if where == "home":
            return await self._finish_reused("اینستاگرام هنوز این نشست را قبول دارد")
        self.step("page", "done")
        self.step("credentials", "skipped")
        self.step("answer", "active")
        if where == "form" or await d.page_kind(self._page) == "chooser":
            raise Fail("session_invalid", "اینستاگرام صفحهٔ ورود نشان داد؛ نشست معتبر نیست")
        # Pressing Continue led somewhere else (a code, a confirmation): carry on as a login would.
        await self._await_answer()
        await self._save((read_meta() or {}).get("username") or "")
