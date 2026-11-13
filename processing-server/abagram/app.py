"""Local test site: log in to Instagram through a real browser window, then read profiles with that session."""
import asyncio
import hmac
import json
import os
import re
import shutil
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from typing import Optional

from pydantic import BaseModel, Field

import ig_accounts
import ig_auth
import ig_export
import ig_files
import ig_import
import ig_health
import ig_login
import ig_lookup
import ig_media
import ig_prefs
import ig_share
import ig_process
import ig_proxy
import ig_queue
import ig_runs
import ig_profile
import ig_store
import ig_trend
import ig_vpn
from ig_common import DATA, age_text

ROOT = Path(__file__).parent
PORT = int(os.environ.get("IGS_PORT", "8790"))
# Listen address. Default = this machine only; on the server set IGS_HOST=0.0.0.0 and IGS_ALLOW_HOSTS=<its LAN address>.
HOST = os.environ.get("IGS_HOST", "127.0.0.1")
ALLOWED_HOSTS = {"127.0.0.1", "localhost"} | {h.strip() for h in os.environ.get("IGS_ALLOW_HOSTS", "").split(",") if h.strip()}
PROXY_RE = re.compile(r"^(https?|socks5)://[^\s]+$")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
job = ig_login.LoginJob()
store = ig_profile.Store(DATA)
media = ig_store.Media(DATA)
files = ig_files.Files(DATA)
pictures = ig_proxy.ImageCache(DATA)
queue = ig_queue.Queue()
sections = {name: ig_store.Section(DATA, name) for name in ("posts", "highlights", "similar", "details", "stories", "reels", "followers", "following")}   # grows with every step


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
    proxy: str = Field(default="", max_length=200)
    account: str = Field(default="", max_length=40)    # log in to this (other) account of his; the active account stays as it is


class CheckBody(BaseModel):
    proxy: str = Field(default="", max_length=200)


class ProfileBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)   # a name or a pasted profile link
    fresh: bool = False
    proxy: str = Field(default="", max_length=200)


class DetailsBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    codes: list[str] | None = Field(default=None, max_length=12)   # these posts, or else the most recent ones
    count: int | None = Field(default=None, ge=1, le=12)
    proxy: str = Field(default="", max_length=200)


class CheckBody2(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    proxy: str = Field(default="", max_length=200)


class HighlightsBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    ids: list[str] | None = Field(default=None, max_length=30)   # these highlights, or else the first few saved
    proxy: str = Field(default="", max_length=200)


class FollowBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    which: list[str] | None = Field(default=None, max_length=2)   # "followers", "following" (both when left out)
    proxy: str = Field(default="", max_length=200)


class DownloadBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=20)                    # "posts", "highlights" or "story"
    codes: list[str] | None = Field(default=None, max_length=50)        # posts: these ones, else every saved post
    ids: list[str] | None = Field(default=None, max_length=30)          # highlights: these ones (a highlight is never taken without a choice)
    items: list[str] | None = Field(default=None, max_length=200)       # highlights / story: only these items, else all of the chosen ones
    videos: bool = True
    again: bool = False                                                 # fetch again what is already on disk
    proxy: str = Field(default="", max_length=200)


class PostsBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    count: int | None = Field(default=None, ge=12, le=300)   # up to this many posts (never above the limit in «محدودیت‌ها»)
    proxy: str = Field(default="", max_length=200)


class LimitsBody(BaseModel):
    values: dict[str, int] = Field(default_factory=dict)


class CodeBody(BaseModel):
    code: str = Field(min_length=4, max_length=10)


class WindowBody(BaseModel):
    x: Optional[float] = Field(default=None, ge=0, le=1)
    y: Optional[float] = Field(default=None, ge=0, le=1)
    text: str = Field(default="", max_length=120)
    key: str = Field(default="", pattern=r"^(|Enter|Backspace|Tab|Escape|ArrowLeft|ArrowRight|ArrowUp|ArrowDown)$")
    dy: Optional[float] = Field(default=None, ge=-3000, le=3000)   # mouse wheel


def reply(data, status=200):
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


OPEN = {"/api/auth/login", "/api/auth/me"}          # the only answers before a login (they say nothing about anyone)
LOCAL_ME = {"username": "local", "uid": "", "role": "full", "admin": True, "until": None}   # IGS_AUTH=0: no login at all
# the server's own checks (health checks over ssh call 127.0.0.1): reading only — a POST from there needs a login too
LOOPBACK = {"127.0.0.1", "::1"}
SERVER_READ = {"username": "server", "uid": "", "role": "full", "admin": False, "until": None}
# A second machine set up from afar (his order 2026-11-07): a long random key in IGS_API_TOKEN lets the one who set
# it up use the API with the header X-Igs-Token. Off when the variable is empty or short (the default: nothing changes).
API_TOKEN = os.environ.get("IGS_API_TOKEN", "").strip()
TOKEN_ME = {"username": "setup", "uid": "", "role": "full", "admin": True, "until": None}

# NMarketing processing node (2026-11): IGS_NODE_MODE=1 runs this site as a local service of the node agent on a computer that is
# not in the office (no AbaOne login there). The address is this computer only (127.0.0.1); every /api/ answer and the page itself
# need the key in IGS_API_TOKEN: the agent sends it as X-Igs-Token, and the person who opens the site on that computer comes in
# once through  http://127.0.0.1:<port>/?igs_key=<key>  (the node's Open-Abagram.bat does that), which sets an HttpOnly cookie.
# Without a long key nothing is answered at all.
NODE_MODE = os.environ.get("IGS_NODE_MODE") == "1"
NODE_COOKIE = "igs_node"
if NODE_MODE:
    ig_auth.ENABLED = False          # no AbaOne login in this mode; the key above is the only door
NODE_LOCKED = ("<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'><title>آباگرام</title>"
               "<body style='font-family:Tahoma,sans-serif;max-width:34rem;margin:4rem auto;line-height:2'>"
               "<h2>آباگرام روی این کامپیوتر قفل است</h2>"
               "<p>این سایت فقط از راهِ فایلِ <b>Open-Abagram.bat</b> (در پوشهٔ سرورِ پردازش) باز می‌شود؛ آن فایل کلیدِ ورود را خودش می‌فرستد.</p>"
               "</body></html>")


def node_cookie_value():
    return hmac.new(API_TOKEN.encode("utf-8"), b"igs-node-ui", "sha256").hexdigest() if len(API_TOKEN) >= 32 else ""


def node_ok(request):
    """The agent's key header, or the cookie the page-opening link set."""
    if token_ok(request):
        return True
    want = node_cookie_value()
    return bool(want) and hmac.compare_digest((request.cookies.get(NODE_COOKIE) or "").encode("utf-8"), want.encode("utf-8"))


def token_ok(request):
    given = request.headers.get("x-igs-token") or ""
    return len(API_TOKEN) >= 32 and hmac.compare_digest(given.encode("utf-8"), API_TOKEN.encode("utf-8"))


def who(request):
    return getattr(request.state, "who", None) or (None if ig_auth.ENABLED else LOCAL_ME)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Refuse hosts that are not allowed (DNS rebinding) and cross-site POSTs; every /api/ answer needs a login (his order
    2026-11-05), and the 'json' role only reaches the saved pages and their JSON (ig_auth.JSON_ROLE)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        return reply({"detail": "host not allowed"}, 403)
    if request.method == "POST" and request.headers.get("x-igs") != "1":
        return reply({"detail": "missing header"}, 403)
    path = request.url.path
    if NODE_MODE and (path == "/" or path.startswith("/api/")):
        given = request.query_params.get("igs_key") if path == "/" else None
        if given is not None and len(API_TOKEN) >= 32 and hmac.compare_digest(given.encode("utf-8"), API_TOKEN.encode("utf-8")):
            door = RedirectResponse("/", status_code=303)
            door.set_cookie(NODE_COOKIE, node_cookie_value(), max_age=30 * 86400, httponly=True, samesite="strict", path="/")
            return door
        if not node_ok(request):
            if path == "/":
                return HTMLResponse(NODE_LOCKED, status_code=401, headers={"Cache-Control": "no-store"})
            return reply({"detail": "login", "message": "این آباگرام فقط از راهِ Open-Abagram.bat روی سرورِ پردازش باز می‌شود."}, 401)
        request.state.who = TOKEN_ME
    elif ig_auth.ENABLED and path.startswith("/api/") and path not in OPEN:
        me = ig_auth.session(request.cookies.get(ig_auth.COOKIE))
        if not me and token_ok(request):
            me = TOKEN_ME
        if not me and request.method == "GET" and request.client and request.client.host in LOOPBACK:
            me = SERVER_READ
        if not me:
            return reply({"detail": "login", "message": "اول وارد آباگرام شو."}, 401)
        if me["role"] != "full" and not ig_auth.json_may(request.method, path):
            return reply({"detail": "forbidden", "message": "این بخش برای حسابِ تو باز نیست."}, 403)
        request.state.who = me
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(RequestValidationError)
async def invalid(request: Request, exc: RequestValidationError):
    # FastAPI's default 422 echoes the submitted values (the password); name the fields only.
    fields = sorted({str(e["loc"][-1]) for e in exc.errors()})
    return reply({"detail": "invalid", "fields": fields}, 422)


def start(mode, username="", password="", proxy="", fresh=False, options=None):
    proxy = proxy.strip()
    if proxy and not PROXY_RE.match(proxy):
        return reply({"detail": "invalid", "fields": ["proxy"]}, 422)
    try:
        job.start(mode, username, password, proxy, fresh, options)
    except ig_login.Busy:
        return reply({"detail": "busy"}, 409)
    return reply({"ok": True, "run": job.run})


@app.on_event("startup")
async def start_queue():
    asyncio.get_event_loop().create_task(queue.loop(job))   # «استخراج کامل» and follow-request checks run from here


@app.get("/api/status")
async def status(since: int = 0):
    return reply({**job.snapshot(max(since, 0)), "queue": queue.summary(), "prefs": ig_prefs.load(), "fast_profiles": ig_lookup.ENABLED})


@app.post("/api/login")
async def login(body: LoginBody):
    user = body.username.strip().lstrip("@")
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    other = ig_profile.clean_username(body.account) if body.account else None
    listing = ig_accounts.listing()
    if other and (other == listing["active"] or not any(a["username"] == other for a in listing["items"])):
        other = None                         # the active account (or an unknown one): an ordinary login
    active = listing["active"]
    if not other and active and user.lower() != active and (ig_login.read_meta() or {}).get("username"):
        # a different person than the active account: never in its place (that dropped the active account's login on
        # 2026-10-28). It becomes his other account, with a browser folder of its own; the active one stays as it is.
        name = ig_profile.clean_username(user)
        if not name or "@" in user or user.replace("+", "").isdigit():
            return reply({"detail": "invalid", "fields": ["username"], "message":
                          f"حساب فعال @{active} است. برای ورود به حساب دیگر، یوزرنیم آن را بنویس (نه ایمیل یا شماره) تا جدا ذخیره شود."}, 422)
        if not any(a["username"] == name for a in listing["items"]):
            ig_accounts.add(name)
        other = name
    if not other:
        return start("login", user, body.password, body.proxy)
    # his other account: a short login of its own. A queue unit of the active account is stopped for it (it keeps what it read and
    # starts again by itself afterwards); something he started by hand is not touched. A whole-list read is never stopped for it:
    # its open window is hours of scrolling (2026-10-29: a login of the second account closed it and the list had to be scrolled again).
    unit = queue.task(getattr(job, "queued", None) or "")
    if job.busy and unit and unit.get("kind") == "harvest" and unit.get("state") == "running":
        return reply({"detail": "busy", "message": "خواندن همهٔ فالوورها در جریان است و پنجره‌اش باز است؛ ورود به حساب دیگر آن را می‌بندد و "
                      "فهرست باید دوباره از اول اسکرول شود. بعد از تمام شدنش وارد شو، یا اول آن را در «فعالیت» متوقف کن."}, 409)
    where = queue.interrupt()
    if where == "manual":
        return reply({"detail": "busy"}, 409)
    try:
        for _ in range(60):
            if _idle():
                break
            await asyncio.sleep(0.5)
        r = start("login", user, body.password, body.proxy, options={"account": other})
        if r.status_code == 200:
            r = reply({"ok": True, "run": job.run, "other": other})   # the page says the active account stayed
        return r
    finally:
        queue.held = False


@app.post("/api/check")
async def check(body: CheckBody):
    return start("check", proxy=body.proxy)


@app.post("/api/profile")
async def read_profile(body: ProfileBody):
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    return start("profile", user, proxy=body.proxy, fresh=body.fresh)


@app.post("/api/details")
async def read_details(body: DetailsBody):
    user = ig_profile.clean_username(body.username)
    codes = body.codes
    if not user or (codes is not None and not all(ig_store.KEY_RE.match(c) for c in codes)):
        return reply({"detail": "invalid", "fields": ["username" if not user else "codes"]}, 422)
    return start("details", user, proxy=body.proxy, options={"codes": codes, "count": body.count})


@app.post("/api/stories")
async def read_stories(body: CheckBody2):
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    return start("stories", user, proxy=body.proxy, options={})


@app.post("/api/highlights")
async def read_highlights(body: HighlightsBody):
    user = ig_profile.clean_username(body.username)
    if not user or (body.ids is not None and not all(re.fullmatch(r"\d{1,25}", i) for i in body.ids)):
        return reply({"detail": "invalid", "fields": ["username" if not user else "ids"]}, 422)
    return start("highlights", user, proxy=body.proxy, options={"ids": body.ids})


@app.post("/api/posts")
async def read_posts(body: PostsBody):
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    return start("posts", user, proxy=body.proxy, options={"count": body.count})


@app.post("/api/follow")
async def read_follow(body: FollowBody):
    user = ig_profile.clean_username(body.username)
    if not user or (body.which is not None and (not body.which or not set(body.which) <= {"followers", "following"})):
        return reply({"detail": "invalid", "fields": ["username" if not user else "which"]}, 422)
    return start("follow", user, proxy=body.proxy, options={"which": body.which})


@app.post("/api/download")
async def download(body: DownloadBody):
    user = ig_profile.clean_username(body.username)
    bad = ("username" if not user else "target" if body.target not in ig_media.TARGETS
           else "codes" if body.codes is not None and not all(ig_store.KEY_RE.match(c) for c in body.codes)
           else "ids" if body.ids is not None and not all(re.fullmatch(r"\d{1,25}", i) for i in body.ids)
           else "items" if body.items is not None and not all(ig_files.ID_RE.match(i) for i in body.items) else None)
    if bad:
        return reply({"detail": "invalid", "fields": [bad]}, 422)
    options = {"target": body.target, "codes": body.codes, "ids": body.ids, "items": body.items, "videos": body.videos, "again": body.again}
    return start("download", user, proxy=body.proxy, options=options)


@app.get("/api/files/{username}")
async def file_list(username: str):
    """What is saved on disk for one person: key -> size, type, time (the viewer builds its pages from the keys)."""
    if not ig_profile.USERNAME_RE.match(username):
        return reply({"detail": "invalid"}, 404)
    listing = files.listing(username)
    return reply({"files": listing, "bytes": sum(f["size"] for f in listing.values()), "all_bytes": files.total_bytes()})


def ranged(path, content_type, header):
    """The file, or the part of it the browser asked for (a video player seeks with Range requests)."""
    size = path.stat().st_size
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header or "")
    start, end, status = 0, size - 1, 200
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start, end = int(m.group(1)), min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        else:
            start, end = max(0, size - int(m.group(2))), size - 1
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
    length = end - start + 1

    def chunks():
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                data = f.read(min(65536, left))
                if not data:
                    break
                left -= len(data)
                yield data

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length), "Cache-Control": "private, max-age=3600"}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(chunks(), status_code=status, media_type=content_type, headers=headers)


@app.get("/api/file/{username}/{key}")
async def file_get(username: str, key: str, request: Request):
    path = files.path(username, key) if ig_profile.USERNAME_RE.match(username) else None
    if not path:
        return reply({"detail": "none"}, 404)
    return ranged(path, ig_files.TYPES[path.suffix], request.headers.get("range"))


@app.get("/api/img")
async def image_proxy(u: str = ""):
    """An Instagram picture through our own server (Instagram's host forbids showing it on other sites), cached on disk."""
    found = await pictures.get(u) if ig_proxy.allowed(u) else None
    if not found:
        return reply({"detail": "none"}, 404)
    return FileResponse(found[0], media_type=found[1], headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/vid")
async def video_proxy(request: Request, u: str = ""):
    """An Instagram video streamed through our server, with the browser's Range header so seeking works."""
    opened = await ig_proxy.open_video(u, request.headers.get("range")) if ig_proxy.allowed(u) else None
    if not opened:
        return reply({"detail": "none"}, 404)
    status, headers, upstream = opened
    return StreamingResponse(upstream.aiter_raw(), status_code=status, headers={**headers, "Cache-Control": "private, max-age=3600"},
                             background=BackgroundTask(upstream.aclose))


class NameBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)


class PageBody(NameBody):
    force: bool = False       # «تقسیم کار»: queue it here although the page is another system's share


def _others_page(user, force):
    """«تقسیم کار» (ig_share): a page that is another system's share is not queued here unless he says so (force). None: go on."""
    who, index, count = ig_share.page_owner(user)
    if force or count == 1 or who == index:
        return None
    return reply({"detail": "not_mine", "owner": who, "index": index, "count": count}, 409)


class PrefsBody(BaseModel):
    values: dict = Field(default_factory=dict)


class NoticesBody(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=100)


@app.post("/api/full")
async def full_extract(body: PageBody):
    """«استخراج کامل»: every part of one page, step by step, waiting for the budget when it is full."""
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    if (other := _others_page(user, body.force)) is not None:
        return other
    return reply({"ok": True, "task": queue.add_full(user)})


class HarvestBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    which: list[str] = Field(default_factory=lambda: ["followers"], min_length=1, max_length=2)
    force: bool = False


@app.post("/api/harvest")
async def harvest(body: HarvestBody):
    """A WHOLE followers / following list: read run after run through the queue, slowly, within harvests_hour / harvests_day."""
    user = ig_profile.clean_username(body.username)
    if not user or not set(body.which) <= {"followers", "following"}:
        return reply({"detail": "invalid", "fields": ["username" if not user else "which"]}, 422)
    if (other := _others_page(user, body.force)) is not None:
        return other
    return reply({"ok": True, "task": queue.add_harvest(user, list(dict.fromkeys(body.which)))})


@app.get("/api/people/{username}/{which}")
async def people(username: str, which: str):
    """Every saved person of one list (a whole list can be tens of thousands: the dossier carries only its head)."""
    if not ig_profile.USERNAME_RE.match(username) or which not in ("followers", "following"):
        return reply({"detail": "invalid"}, 404)
    return reply(sections[which].load(username) or {})


class ProcessBody(BaseModel):
    words: list[str] = Field(default_factory=list, max_length=ig_process.MAX_WORDS)
    min_score: int = Field(default=0, ge=0, le=100)        # rank: who becomes a candidate
    username: str = Field(default="", max_length=60)        # label: whose
    label: Optional[str] = Field(default=None, pattern=r"^(farmer|seller|maker|org|other)$")   # None: back to the automatic one


class MonitorBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    harvest: bool = True      # also read the WHOLE followers list (slowly, through the queue)
    force: bool = False


# ---- his Instagram accounts: one active at a time; limits and the pause after "wait" stay shared (ig_accounts) ----
def _idle():
    """Accounts are switched only while nothing runs (a job and a queue unit use the browser of the active account)."""
    return not job.busy and not (job._task and not job._task.done())


@app.get("/api/accounts")
async def accounts():
    return reply({**ig_accounts.listing(), "idle": _idle(),
                  "watching": [t["username"] for t in queue.data["tasks"] if t["kind"] == "watch" and t["state"] in ("waiting", "running", "paused")]})


@app.post("/api/accounts")
async def account_add(body: NameBody):
    """A new account: it becomes the active one, not logged in yet — the login page logs it in."""
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    if not _idle():
        return reply({"detail": "busy"}, 409)
    if ig_accounts.add(user) is None:
        return reply({"detail": "exists", "fields": ["username"]}, 409)
    return reply({"ok": True, **ig_accounts.listing()})


@app.post("/api/accounts/{username}/{action}")
async def account_action(username: str, action: str):
    user = ig_profile.clean_username(username)
    if not user or action not in ("switch", "remove"):
        return reply({"detail": "invalid"}, 422)
    if not _idle():
        return reply({"detail": "busy"}, 409)
    ok = ig_accounts.switch(user) if action == "switch" else ig_accounts.remove(user)
    return reply({"ok": bool(ok), **ig_accounts.listing()}, 200 if ok else 404)


class ProxyBody(BaseModel):
    proxy: str = Field(default="", max_length=200)


@app.get("/api/health")
async def health():
    """The account-health summary for the monitoring tab (incidents, waits, a traffic-light)."""
    return reply(ig_health.summary())


@app.post("/api/admin/restart")
async def admin_restart(request: Request):
    """The setup key only (2026-11-08, a copy on another computer): end this process so the Windows task «Abagram» starts it again from
    the files on disk (it looks every 5 minutes). Refused while a job runs; the queue keeps its state on disk."""
    if not token_ok(request):
        return reply({"detail": "forbidden"}, 403)
    if job.busy or (job._task and not job._task.done()):
        return reply({"detail": "busy"}, 409)
    threading.Timer(1.0, lambda: os._exit(3)).start()
    return reply({"ok": True, "message": "restarting"})


@app.post("/api/health/test")
async def health_test(body: ProxyBody | None = None):
    """One request to Instagram through the saved proxy (or the one given): is the line/proxy working?"""
    proxy = (body.proxy.strip() if body and body.proxy else None)
    if proxy and not re.match(r"^(https?|socks5)://[^\s]+$", proxy):
        return reply({"detail": "invalid", "fields": ["proxy"]}, 422)
    return reply(await ig_health.test_connection(proxy if proxy else None))


class CountryBody(BaseModel):
    country: str = Field(default="", pattern=r"^(|auto|AUTO|[A-Za-z]{2})$")   # "" or "auto" = the gateway picks


class VpnLoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def _vpn(result):
    # a refusal of the gateway is never passed on as 401: that status means «log in to Abagram again» to the page
    return reply(result, 200 if result["ok"] else 502 if not result["reachable"] else 409)


@app.get("/api/vpn")
async def vpn_status():
    """The office VPN gateway's view of this computer: who is signed in, the chosen and the used country, the choices."""
    return _vpn(await ig_vpn.status())


@app.post("/api/vpn/country")
async def vpn_country(body: CountryBody):
    """Another exit country (another address for Instagram). Not while a job works: its connections would change mid-way."""
    if not _idle():
        return reply({"detail": "busy"}, 409)
    return _vpn(await ig_vpn.set_country(body.country))


@app.post("/api/vpn/login")
async def vpn_login(body: VpnLoginBody):
    return _vpn(await ig_vpn.login(body.username, body.password))


@app.get("/api/vpn/ip")
async def vpn_ip():
    """The address and country the internet sees right now (Cloudflare's trace), the way the jobs go."""
    return reply(await ig_vpn.exit_address())


def _process_task(source):
    t = queue.active("process", source)
    return {k: t[k] for k in ("id", "state", "note", "next_at", "which", "steps")} if t else None


@app.get("/api/process")
async def process_lists():
    """«پردازش»: the saved lists that can be processed, and the words offered by default."""
    items = [{**x, "task": _process_task(x["source"]), "filtered": bool(ig_process.get(x["source"], x["which"]))} for x in ig_process.lists()]
    return reply({"items": items, "default_words": ig_process.DEFAULT_WORDS, "limits": ig_login.BUDGET.limits()})


def _process_filters(request):
    """The filters of the results (query string): label, account (several, comma separated), contact, min_followers, q, read, city, sort."""
    q = request.query_params
    out = {k: q.get(k, "") for k in ("label", "account", "q", "read", "city", "sort") if q.get(k)}
    if q.get("contact") in ("1", "true"):
        out["contact"] = True
    if (q.get("min_followers") or "").isdigit():
        out["min_followers"] = int(q["min_followers"])
    return out


@app.get("/api/process/{source}/{which}")
async def process_view(source: str, which: str, request: Request, offset: int = 0, limit: int = 10):
    """One page of results, best first (or as he sorts), with the counts every filter shows."""
    user = ig_profile.clean_username(source)
    if not user or which not in ig_process.WHICH:
        return reply({"detail": "invalid"}, 422)
    data = ig_process.view(user, which, offset=offset, limit=limit, **_process_filters(request))
    return reply({"data": data, "task": _process_task(user)}) if data else reply({"detail": "none"}, 404)


@app.get("/api/process/{source}/{which}/export.xlsx")
async def process_export(source: str, which: str, request: Request):
    """The results he filtered, as an Excel file (best first)."""
    user = ig_profile.clean_username(source)
    if not user or which not in ig_process.WHICH:
        return reply({"detail": "invalid"}, 422)
    data, n = ig_process.export(user, which, **_process_filters(request))
    if data is None:
        return reply({"detail": "none"}, 404)
    name = f"abagram-{user}-{which}-{n}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@app.post("/api/process/{source}/{which}/{action}")
async def process_action(source: str, which: str, action: str, body: ProcessBody | None = None):
    """rank (step 1: everyone scored from the list, no request) / filter (the older words-only step) / start (step 2: the
    queue reads the candidates' profiles, best first) / label (his own label for one person)."""
    user = ig_profile.clean_username(source)
    if not user or which not in ig_process.WHICH or action not in ("rank", "filter", "start", "label"):
        return reply({"detail": "invalid"}, 422)
    if action == "rank":
        if not any(x["source"] == user and x["which"] == which for x in ig_process.lists()):
            return reply({"detail": "none"}, 404)
        ig_process.run_rank(user, which, body.words if body else [], body.min_score if body else 0)
        return reply({"data": ig_process.view(user, which), "task": _process_task(user)})
    if action == "label":
        ok = body is not None and ig_process.set_label(user, which, body.username.strip().lower(), body.label)
        return reply({"ok": True}) if ok else reply({"detail": "none"}, 404)
    if action == "filter":
        words = ig_process.clean_words(body.words if body else [])
        if not words:
            return reply({"detail": "invalid", "fields": ["words"]}, 422)
        if not ig_process.lists() or not any(x["source"] == user and x["which"] == which for x in ig_process.lists()):
            return reply({"detail": "none"}, 404)
        ig_process.run_filter(user, which, words)
        return reply({"data": ig_process.view(user, which), "task": _process_task(user)})
    if not ig_process.get(user, which):
        return reply({"detail": "not filtered"}, 409)
    t = queue.add_process(user, which)
    return reply({"ok": True, "task": _process_task(user) or {"id": t["id"], "state": t["state"]}})


@app.get("/api/monitors")
async def monitors():
    """«رصدها»: the watched pages, each with its numbers, the whole-list progress and what is new."""
    return reply({"items": queue.monitors.listing()})


@app.post("/api/monitors")
async def monitor_add(body: MonitorBody):
    """Watch a page: a full extraction first (when it was never done), the whole followers list if asked, then a check about
    twice a day (newest posts, the active story and its media)."""
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    if (other := _others_page(user, body.force)) is not None:
        return other
    rec = queue.monitors.add(user, harvest=body.harvest)
    if not any(t["kind"] == "full" and t["username"] == user and t["state"] == "done" for t in queue.data["tasks"]):
        queue.add_full(user)
    queue.monitors.schedule(user)          # the first check comes after a whole cycle; the full extraction reads everything now
    if body.harvest:
        queue.add_harvest(user, ["followers"])
    return reply({"ok": True, "monitor": rec})


@app.post("/api/monitors/{username}/{action}")
async def monitor_action(username: str, action: str, body: NoticesBody | None = None):
    """pause / resume / remove / check (now) / seen (the news of this page, or the ids given)."""
    user = ig_profile.clean_username(username)
    if not user or not queue.monitors.get(user) or action not in ("pause", "resume", "remove", "check", "seen"):
        return reply({"detail": "invalid"}, 404 if user else 422)
    if action == "remove":
        queue.monitors.remove(user)
        return reply({"ok": True})
    if action == "seen":
        rec = queue.monitors.mark_seen(user, body.ids if body else None)
    elif action == "check":
        rec = queue.monitors.update(user, enabled=True)
        queue.add_check(user)
        queue.monitors.schedule(user)
    else:
        rec = queue.monitors.update(user, enabled=action == "resume")
        if action == "resume" and rec["next_at"] < 1:
            queue.monitors.schedule(user)
    return reply({"ok": True, "monitor": rec})


@app.post("/api/request")
async def follow_request(body: PageBody):
    """A follow request to a private page, then a check every request_check_min until it is accepted."""
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    if (other := _others_page(user, body.force)) is not None:
        return other
    return reply({"ok": True, "task": queue.add_watch(user)})


@app.post("/api/queue/{tid}/{action}")
async def queue_action(tid: str, action: str):
    if action not in ("pause", "resume", "cancel", "now"):
        return reply({"detail": "invalid"}, 422)
    t = queue.act(tid, action)
    return reply({"ok": bool(t), "task": t}, 200 if t else 404)


@app.post("/api/notices/read")
async def notices_read(body: NoticesBody):
    queue.read_notices(body.ids)
    return reply({"ok": True})


@app.get("/api/prefs")
async def prefs_get():
    return reply(ig_prefs.load())


@app.post("/api/prefs")
async def prefs_set(body: PrefsBody):
    bad = ig_prefs.valid(body.values)
    if bad:
        return reply({"detail": "invalid", "fields": bad}, 422)
    return reply(ig_prefs.save(body.values))


@app.get("/api/find-post/{code}")
async def find_post(code: str):
    """Which saved person has this post (a story may share someone else's post)."""
    if not ig_store.KEY_RE.match(code):
        return reply({"detail": "invalid"}, 404)
    for f in sorted((DATA / "posts").glob("p_*.json")):
        try:
            items = json.loads(f.read_text("utf-8")).get("items") or []
        except (OSError, ValueError):
            continue
        if any(p.get("code") == code for p in items):
            return reply({"username": f.stem[2:], "code": code})
    return reply({"detail": "none"}, 404)


class ForgetBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)


@app.post("/api/forget")
async def forget(body: ForgetBody):
    """Delete everything saved about one person on this computer (nothing is deleted on Instagram)."""
    user = ig_profile.clean_username(body.username)
    if not user:
        return reply({"detail": "invalid", "fields": ["username"]}, 422)
    if job.busy and (job.username or "").lower() == user.lower():
        return reply({"detail": "busy"}, 409)
    removed = 0
    targets = [store._file(user, "json"), store._file(user, "img")] + [sec._file(user) for sec in sections.values()]
    for f in targets:
        if f.is_file():
            f.unlink()
            removed += 1
    for folder in (media.dir / f"p_{user.lower()}", files.folder(user)):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return reply({"ok": True, "removed": removed})


@app.get("/api/profiles")
async def saved_profiles(offset: int = 0, limit: int = 5):
    return reply(store.listing(max(offset, 0), min(max(limit, 1), 50)))


@app.get("/api/dossier/{username}")
async def dossier(username: str):
    """Everything saved about one person; lists that can get long have their own paged endpoints."""
    if not ig_profile.USERNAME_RE.match(username):
        return reply({"detail": "invalid"}, 404)
    return reply({"profile": store.load(username), **{name: head(name, sec.load(username)) for name, sec in sections.items()}})


@app.get("/api/trend/{username}")
async def trend_posts(username: str, limit: int = 24):
    """The recent posts of one page with their numbers (NMarketing's trend finder) — never the followers or anyone else's data."""
    if not ig_profile.USERNAME_RE.match(username):
        return reply({"detail": "invalid"}, 404)
    found = await asyncio.to_thread(ig_trend.recent, username, DATA, max(1, min(limit, ig_trend.MAX_POSTS)))
    return reply(found) if found else reply({"detail": "none", "message": "از این صفحه چیزی ذخیره نشده؛ اول خواندنش را بزن."}, 404)


HEAD = 300   # people of a list the dossier carries; the rest come from /api/people


def head(name, data):
    """A long followers / following list as its head only (trimmed: True, count = all saved)."""
    if name not in ("followers", "following") or not data or len(data.get("items") or []) <= HEAD:
        return data
    return dict(data, items=data["items"][:HEAD], count=len(data["items"]), trimmed=True)


@app.get("/api/media/{username}/{key}")
async def media_file(username: str, key: str):
    path = media.path(username, key) if ig_profile.USERNAME_RE.match(username) else None
    if not path:
        return reply({"detail": "none"}, 404)
    with open(path, "rb") as f:
        kind = ig_store.sniff_image(f.read(16))
    return FileResponse(path, media_type=kind or "application/octet-stream", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/avatar/{username}")
async def avatar(username: str):
    found = store.avatar(username) if ig_profile.USERNAME_RE.match(username) else None
    if not found:
        return reply({"detail": "none"}, 404)
    return FileResponse(found[0], media_type=found[1], headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/limits")
async def get_limits():
    return reply(ig_login.BUDGET.snapshot())


@app.post("/api/limits")
async def set_limits(body: LimitsBody):
    _, bad = ig_login.BUDGET.set_limits(body.values)
    if bad:
        return reply({"detail": "invalid", "fields": bad}, 422)
    return reply(ig_login.BUDGET.snapshot())


@app.post("/api/limits/reset")
async def reset_limits():
    ig_login.BUDGET.reset_limits()
    return reply(ig_login.BUDGET.snapshot())


@app.post("/api/cooldown/clear")
async def clear_cooldown():
    ig_login.BUDGET.clear_cooldown()
    return reply(ig_login.BUDGET.snapshot())


@app.post("/api/code")
async def code(body: CodeBody):
    ok = job.submit_code(re.sub(r"\s+", "", body.code))
    return reply({"ok": ok}, 200 if ok else 409)


@app.post("/api/cancel")
async def cancel():
    job.cancel()
    return reply({"ok": True})


@app.post("/api/session/clear")
async def clear_session():
    if job.busy:
        return reply({"detail": "busy"}, 409)
    await job.close()
    return reply({"ok": ig_login.clear_saved_session()})


@app.get("/api/runs")
async def runs(limit: int = 100, task: str = ""):
    """«فعالیت»: the jobs that ended, newest first (no logs); only one queue task's runs when asked."""
    return reply({"items": ig_runs.listing(limit, task or None)})


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str):
    rec = ig_runs.get(run_id)
    return reply(rec) if rec else reply({"detail": "none"}, 404)


@app.get("/api/runs/{run_id}/picture")
async def run_picture(run_id: str):
    """The window's last picture of that run (taken every few minutes while a whole list is read, and when it stops)."""
    path = ig_runs.picture(run_id)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"}) if path \
        else reply({"detail": "none"}, 404)


@app.get("/api/window")
async def window_view():
    """The live page of a login that waits for him (Chromium without a window, on the server)."""
    picture = await job.remote_view()
    if picture is None:
        return reply({"detail": "none"}, 409)
    return Response(picture, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/window")
async def window_input(body: WindowBody):
    ok = await job.remote_input(body.x, body.y, body.text, body.key, body.dy)
    return reply({"ok": True}) if ok else reply({"detail": "none"}, 409)


@app.get("/api/shot")
async def shot():
    if not ig_login.SHOT.exists():
        return reply({"detail": "none"}, 404)
    return FileResponse(ig_login.SHOT, headers={"Cache-Control": "no-store"})


# ---- the site's own login (AbaOne account, only the people he added: ig_auth) ----
class AuthBody(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class UserBody(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    role: str = Field(pattern=r"^(full|json)$")


@app.post("/api/auth/login")
async def auth_login(body: AuthBody, request: Request):
    """The AbaOne username and password go to LoginApi only; nothing about the account is said before they are right."""
    address = request.client.host if request.client else "?"
    wait = ig_auth.waiting(address)
    if wait:
        return reply({"detail": "wait", "message": f"چند بار پشت سر هم رمز اشتباه بود؛ {age_text(wait)} دیگر دوباره امتحان کن."}, 429)
    uid, why = await ig_auth.abaone_login(body.username.strip(), body.password)
    if why == "down":
        return reply({"detail": "down", "message": "سرورِ ورودِ آبا وان جواب نداد؛ کمی بعد دوباره امتحان کن."}, 503)
    if not uid:
        ig_auth.failed(address)
        return reply({"detail": "wrong", "message": "نام کاربری یا رمز درست نیست."}, 401)
    if not ig_auth.role_of(body.username, uid):
        return reply({"detail": "denied", "message": "حسابِ آبا وانت درست است، ولی هنوز به آباگرام اضافه نشده‌ای. از مدیر بخواه اضافه‌ات کند."}, 403)
    key = ig_auth.start_session(body.username, uid)
    r = reply({"ok": True, "me": ig_auth.session(key)})
    r.set_cookie(ig_auth.COOKIE, key, max_age=ig_auth.TTL, httponly=True, samesite="strict", path="/")
    return r


@app.get("/api/auth/me")
async def auth_me(request: Request):
    if not ig_auth.ENABLED:
        return reply({"me": LOCAL_ME, "auth": False})
    me = ig_auth.session(request.cookies.get(ig_auth.COOKIE))
    return reply({"me": me, "auth": True}) if me else reply({"detail": "login"}, 401)


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    ig_auth.end_session(request.cookies.get(ig_auth.COOKIE))
    r = reply({"ok": True})
    r.delete_cookie(ig_auth.COOKIE, path="/")
    return r


@app.get("/api/auth/users")
async def auth_users(request: Request):
    if not (who(request) or {}).get("admin"):
        return reply({"detail": "forbidden", "message": "فقط مدیر فهرستِ کاربران را می‌بیند."}, 403)
    items = sorted(ig_auth.users().values(), key=lambda u: u.get("added_at") or 0)
    return reply({"items": items, "admins": sorted(ig_auth.ADMINS), "login_api": ig_auth.LOGIN_API})


@app.post("/api/auth/users")
async def auth_user_add(body: UserBody, request: Request):
    """A person who may come in (or a new role for him); he is known by his AbaOne username."""
    me = who(request) or {}
    if not me.get("admin"):
        return reply({"detail": "forbidden"}, 403)
    rec = ig_auth.add_user(body.username, body.role, me.get("uid"))
    return reply({"ok": True, "user": rec}) if rec else reply({"detail": "invalid", "fields": ["username"]}, 422)


@app.post("/api/auth/users/{username}/remove")
async def auth_user_remove(username: str, request: Request):
    if not (who(request) or {}).get("admin"):
        return reply({"detail": "forbidden"}, 403)
    return reply({"ok": True}) if ig_auth.remove_user(username) else reply({"detail": "none"}, 404)


# ---- «تبادلِ JSON»: a page's JSON out (ig_export) and back in (ig_import) ----
MAX_UPLOAD = 300 * 1024 * 1024


@app.get("/api/exchange")
async def exchange():
    return reply({"items": await asyncio.to_thread(ig_export.pages)})


def _batched(pieces, size=1 << 16):
    """The export's small pieces sent in blocks of ~64 KB (one hop to the worker thread per block, not per person)."""
    buf, n = [], 0
    for piece in pieces:
        buf.append(piece)
        n += len(piece)
        if n >= size:
            yield "".join(buf).encode("utf-8")
            buf, n = [], 0
    if buf:
        yield "".join(buf).encode("utf-8")


@app.get("/api/export/{username}")
async def export_page(username: str, request: Request):
    """Everything saved about one page, its whole lists with each person's own profile, as one JSON file (made on the fly)."""
    user = username.lower()
    if not ig_profile.USERNAME_RE.match(user) or not ig_export.saved_anything(user):
        return reply({"detail": "none", "message": "از این پیج چیزی ذخیره نشده."}, 404)
    me = who(request) or {}
    return StreamingResponse(_batched(ig_export.chunks(user, by=me.get("username"))), media_type="application/json; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{ig_export.filename(user)}"', "Cache-Control": "no-store"})


def _open_lists(page):
    """The lists of this page whose whole-list read is open right now (the import leaves those files alone)."""
    return ig_export.LISTS if job.busy and job.mode == "harvest" and (job.username or "").lower() == page else ()


@app.post("/api/import")
async def import_page(request: Request):
    """A page's JSON file (the body as it is): merged into what is saved here — nothing deleted, newer wins."""
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
        return reply({"detail": "big", "message": "فایل بزرگ‌تر از ۳۰۰ مگابایت است."}, 413)
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > MAX_UPLOAD:
            return reply({"detail": "big", "message": "فایل بزرگ‌تر از ۳۰۰ مگابایت است."}, 413)
    try:
        doc = await asyncio.to_thread(ig_import.read, bytes(data))
        report = await asyncio.to_thread(ig_import.merge, doc, DATA, _open_lists)
    except ig_import.Refused as e:
        return reply({"detail": "refused", "message": str(e)}, 422)
    return reply({"ok": True, "report": report})


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}/"
    print("instagramScrape on", url)
    if os.environ.get("IGS_NO_BROWSER") != "1":
        threading.Timer(1.2, webbrowser.open, [url]).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
