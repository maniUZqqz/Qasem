#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""abagram_jobs.py - Abagram (the Instagram reader) as a managed local service of this node + the job kinds ig.scrape / ig.health.

WHAT THE NODE DOES BY ITSELF (nothing to click, nothing to install by hand)
  1. installs Abagram's Python packages into its own virtual environment <data folder>\\abagram\\venv - first from the wheels the site
     mirrors (abagram-wheels-cp311-win_amd64.zip, no internet outside the site needed), else from PyPI mirrors reachable from Iran -
     idempotently (a marker holds the hash of requirements-node.lock.txt). The node's install list (requirements.d/abagram.json, agent
     2.11) runs this through the command line below (check-packages / install-packages / check-browser / install-browser), so progress,
     errors, retries and the panel's «تلاش دوباره» button are the platform's; without the install list the supervisor installs by itself;
  2. chooses the browser: the Microsoft Edge every Windows 11 has (Playwright channel "msedge"; no download), else Chrome, else a
     Chromium build mirrored on the site (abagram-chromium-win64.zip);
  3. starts Abagram (abagram/app.py, the vendored copy next to this file) as a service bound to 127.0.0.1 on a free port with a random
     key in IGS_API_TOKEN (IGS_NODE_MODE=1: the key is the only door), keeps it alive, restarts it after an update;
  4. reports its health in the node report (caps["abagram"]): installed / running / signed in / proxy / reach / budget / what to do.

WHAT IT NEVER DOES: bypass Instagram's protections, log in by itself (the owner signs in once through Abagram's own page: run
Open-Abagram.bat on this computer), copy a session from another computer, read followers/following lists, post anything.

ig.scrape  payload {accounts:[usernames], max_accounts, pace_s:[min,max], fresh, posts_per_account, store_id, run_id}
           reads the recent posts (with their numbers) of a few pages, one profile page each, with randomized pauses, and STOPS at the
           first sign of trouble (challenge, "wait a few minutes", a full budget, a lost session, the line down). Output ig_batch.json
           (format "nm-ig-batch", version 1); meta.stopped says why it stopped early. A stop is an answer, not a failure.
ig.health  payload {test_connection, read:"<page>"}: the service report (+ one anonymous connection test, + one page read when signed in).

Python 3.8+ standard library only (the agent's own interpreter). Console text is English on purpose (the Windows console garbles Persian).
"""
import hashlib
import json
import os
import platform
import random
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION = "1.1"
KINDS = ("ig.scrape", "ig.health")
FEATURE = "abagram"                        # the feature name in requirements.d/abagram.json (the node's install list)
IS_WIN = sys.platform.startswith("win")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
PORT_RANGE = (8791, 8890)                  # 8790 is Abagram's own default: that one belongs to the office copy
WHEEL_PACK = "abagram-wheels-cp311-win_amd64.zip"
CHROMIUM_PACK = "abagram-chromium-win64.zip"
# the official index first whenever it answers from this computer (only the pinned names and versions of the lock file are asked for);
# the mirror that serves the same wheels from inside Iran follows (aliyun 3 s). mirror-pypi.runflare.com was here until 2026-11-13: its /simple index
# answers but every wheel download now returns HTTP 402 (payment required), so it only cost pip a retry cycle when pypi.org was blocked.
INDEX_URLS = ("https://pypi.org/simple", "https://mirrors.aliyun.com/pypi/simple")
LOOP_S = 15.0                              # the supervisor looks at the service this often
REACH_EVERY_S = 3600.0                     # one anonymous connection test per hour, no more
RETRY_INSTALL_S = (300, 900, 3600)         # after a failed install: wait, then try again by itself
MAX_RESTARTS_PER_HOUR = 6
HUNG_S = 600                               # a service that is alive but silent for this long is ended and started again
READ_TIMEOUT_S = 300                       # one page read may take this long (a VPN line can be slow)
DEFAULT_PACE_S = (45.0, 110.0)             # pause between two pages (the person-like rhythm; Abagram adds its own pauses inside a page)
PAGES_PER_ACCOUNT = 2                      # Abagram spends one or two page-budget units per profile read
BUDGET_MARGIN = 6                          # page-budget units always left for the owner's own use
MAX_ACCOUNTS = 12
NOT_RETRYABLE = {"retryable": False}

#: what the first word of an Abagram outcome means for the rest of the run
STOP_KINDS = {
    "challenge": ("challenge", "Instagram asked for a human check (challenge) - stopped, nothing more is asked of it"),
    "rate_limit": ("limit", "Instagram said to wait a few minutes (rate limit) - stopped"),
    "cooldown": ("limit", "Abagram is pausing after a rate limit - stopped"),
    "budget": ("budget", "Abagram's own hourly/daily page budget is full - stopped"),
    "session_invalid": ("not_signed_in", "Instagram threw the login out - sign in again in Abagram"),
    "automated": ("challenge", "Instagram noticed automated behaviour - stopped"),
}
LINE_KINDS = {"network", "browser", "timeout", "error", "other"}   # the line / the page, not a verdict about the account
SKIP_KINDS = {"not_found", "unreadable"}                            # about this one page only: mark it, go on


class InstallError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ServiceDown(Exception):
    pass


# ───────────────────────────────────────────── layout and small helpers

class Layout:
    """Where everything lives. The CODE (vendored abagram/) is replaced by every site update; the rest lives in the data folder."""

    def __init__(self, code_dir, data_dir):
        self.code = os.path.join(code_dir, "abagram")
        self.root = os.path.join(data_dir, "abagram")
        self.venv = os.path.join(self.root, "venv")
        self.py = os.path.join(self.venv, "Scripts", "python.exe") if IS_WIN else os.path.join(self.venv, "bin", "python")
        self.data = os.path.join(self.root, "data")            # Abagram's own data: the Instagram session of THIS computer
        self.logs = os.path.join(self.root, "logs")
        self.service_file = os.path.join(self.root, "service.json")
        self.wheelhouse = os.path.join(self.root, "wheelhouse")
        self.browser_dir = os.path.join(self.root, "browser")
        self.downloads = os.path.join(self.root, "downloads")
        self.marker = os.path.join(self.venv, ".nm-abagram.json")
        self.lock = os.path.join(self.code, "requirements-node.lock.txt")
        self.proxy_file = os.path.join(self.root, "proxy.txt")
        self.pip_cache = os.path.join(data_dir, "pip-cache")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def pid_alive(pid):
    if not pid:
        return False
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH"], capture_output=True, text=True, timeout=20,
                                 creationflags=0x08000000).stdout
            return str(int(pid)) in out
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def kill_pid(pid):
    """End a process by number (an old Abagram that stopped answering). Never raises."""
    if not pid:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(int(pid))], capture_output=True, timeout=30, creationflags=0x08000000)
        else:
            os.kill(int(pid), 15)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def port_is_free(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def choose_port(preferred=None, is_free=port_is_free, span=PORT_RANGE):
    """The remembered port when it is free, else the first free one of the range (the address the owner bookmarks stays the same)."""
    if preferred and span[0] <= int(preferred) <= span[1] and is_free(int(preferred)):
        return int(preferred)
    for port in range(span[0], span[1] + 1):
        if is_free(port):
            return port
    raise InstallError("no_port", "no free port between %d and %d" % span)


def mask_proxy(url):
    """scheme://host:port - never the user name or password of a proxy."""
    try:
        u = urllib.parse.urlparse(url or "")
        if not u.hostname:
            return ""
        return "%s://%s%s" % (u.scheme or "http", u.hostname, (":%d" % u.port) if u.port else "")
    except ValueError:
        return ""


def code_stamp(layout):
    """Changes when the vendored code changes (an update): the service is then restarted on it."""
    h = hashlib.sha1()
    try:
        for name in sorted(os.listdir(layout.code)):
            if name.endswith(".py") or name == "requirements-node.lock.txt":
                st = os.stat(os.path.join(layout.code, name))
                h.update(("%s\0%d\0%d\n" % (name, st.st_size, st.st_mtime_ns)).encode("utf-8"))
    except OSError:
        return ""
    return h.hexdigest()[:16]


def lock_spec(layout):
    try:
        with open(layout.lock, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:16]
    except OSError:
        return ""


# ───────────────────────────────────────────── a proxy for Instagram (the owner's own VPN client on this computer)

def system_proxy_hint(winreg=None):
    """http://127.0.0.1:PORT when the Windows system proxy points to a program on THIS computer (v2rayN and friends set it); never a remote
    address, never one with a password. Nothing when there is none."""
    if winreg is None:
        if not IS_WIN:
            return ""
        try:
            import winreg  # noqa: F811
        except ImportError:
            return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = winreg.QueryValueEx(key, "ProxyServer")[0]
    except OSError:
        return ""
    return parse_proxy_server(server) if enabled else ""


def parse_proxy_server(text):
    text = str(text or "").strip()
    if not text:
        return ""
    parts = [p.strip() for p in text.split(";") if p.strip()]
    pick = ""
    for p in parts:                                   # "http=127.0.0.1:10809;https=127.0.0.1:10809;socks=127.0.0.1:10808" or just host:port
        scheme, _eq, rest = p.partition("=")
        if not _eq:
            pick = p
            break
        if scheme.lower() in ("http", "https") and not pick:
            pick = rest
    m = re.match(r"^(?:https?://)?(?:127\.0\.0\.1|localhost):(\d{2,5})/?$", pick)
    return "http://127.0.0.1:%s" % m.group(1) if m else ""


def wanted_proxy(layout, env=None):
    """(url, where) the owner chose for Abagram: NM_ABAGRAM_PROXY, then <abagram folder>\\proxy.txt, then the local system proxy."""
    env = os.environ if env is None else env
    chosen = (env.get("NM_ABAGRAM_PROXY") or "").strip()
    if chosen:
        return chosen, "env"
    try:
        with open(layout.proxy_file, encoding="utf-8") as fh:
            line = (fh.readline() or "").strip()
        if line:
            return line, "file"
    except OSError:
        pass
    hint = system_proxy_hint()
    return (hint, "system") if hint else ("", "")


# ───────────────────────────────────────────── the browser

def edge_paths(env=None):
    env = os.environ if env is None else env
    out = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = env.get(var)
        if base:
            out.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    return out


def chrome_paths(env=None):
    env = os.environ if env is None else env
    out = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = env.get(var)
        if base:
            out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    return out


def find_pack_chromium(layout):
    """chrome.exe of the Chromium build unpacked from the site's pack, or ''."""
    for dirpath, _dirs, files in os.walk(layout.browser_dir):
        if "chrome.exe" in files:
            return os.path.join(dirpath, "chrome.exe")
        if dirpath.count(os.sep) - layout.browser_dir.count(os.sep) > 4:
            _dirs[:] = []
    return ""


def find_browser(layout, env=None, exists=os.path.isfile):
    """{'channel': 'msedge'|'chrome', 'path'} for an installed browser, {'exe': path} for the site's Chromium, or {} when there is none."""
    env = os.environ if env is None else env
    prefer = (env.get("NM_ABAGRAM_BROWSER") or "").strip().lower()
    if prefer == "chromium":
        exe = find_pack_chromium(layout)
        return {"exe": exe, "name": "chromium"} if exe else {}
    if not IS_WIN and not env.get("NM_ABAGRAM_FORCE_BROWSER_SEARCH"):
        return {}
    for path in edge_paths(env):
        if exists(path):
            return {"channel": "msedge", "path": path, "name": "edge"}
    for path in chrome_paths(env):
        if exists(path):
            return {"channel": "chrome", "path": path, "name": "chrome"}
    exe = find_pack_chromium(layout)
    return {"exe": exe, "name": "chromium"} if exe else {}


# ───────────────────────────────────────────── installing (idempotent)

def pip_env(layout, base=None):
    """Only our own sources: no pip.ini / PIP_* variable of this computer can add another index."""
    env = {k: v for k, v in (base if base is not None else os.environ).items()
           if k.upper() not in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PIP_NO_INDEX", "PIP_TRUSTED_HOST",
                                "PIP_CONFIG_FILE", "PIP_REQUIRE_VIRTUALENV")}
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONIOENCODING="utf-8", PIP_NO_INPUT="1",
               PIP_CACHE_DIR=layout.pip_cache)
    return env


def index_order(probe=True, timeout=6.0, urlopen=None):
    """pypi.org first when it answers (a quick HEAD), else the mirrors first and pypi.org last - so a blocked pypi.org does not cost the
    several minutes pip would spend on its retries. probe=False keeps the declared order (tests with a fake pip)."""
    if not probe:
        return list(INDEX_URLS)
    try:
        req = urllib.request.Request(INDEX_URLS[0].rstrip("/") + "/pip/", method="HEAD", headers={"User-Agent": "nm-node-abagram"})
        (urlopen or urllib.request.urlopen)(req, timeout=timeout).close()
        return list(INDEX_URLS)
    except Exception:  # noqa: BLE001 - blocked or slow from this computer
        return list(INDEX_URLS[1:]) + [INDEX_URLS[0]]


def pack_fits():
    """The mirrored wheel pack is for CPython 3.11 on 64-bit Windows."""
    return IS_WIN and sys.version_info[:2] == (3, 11) and platform.machine().lower() in ("amd64", "x86_64")


def venv_ready(layout, run=subprocess.run):
    marker = read_json(layout.marker, {}) or {}
    if not os.path.isfile(layout.py) or not marker.get("spec") or marker.get("spec") != lock_spec(layout):
        return False
    try:
        r = run([layout.py, "-c", "import fastapi, uvicorn, playwright, httpx"], capture_output=True, timeout=180,
                **({"creationflags": 0x08000000} if IS_WIN else {}))
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def unpack_zip(zip_path, dest):
    """Unpack into dest, refusing paths that leave it."""
    os.makedirs(dest, exist_ok=True)
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            target = os.path.realpath(os.path.join(dest, member.filename))
            if target != root and not target.startswith(root + os.sep):
                raise InstallError("bad_zip", "unsafe path in %s: %s" % (os.path.basename(zip_path), member.filename))
        z.extractall(dest)


def fetch_site_file(agent, name, dest, say=print):
    """Download {site}/3d/files/downloads/<name> (resumable, size + sha256 checked by the site's own numbers). True when it is there."""
    import nm_fetch
    site = agent.site_base()
    token = (getattr(agent, "CONFIG", None) or {}).get("token", "")
    if not site:
        return False
    size, sha = nm_fetch.site_file_info(site, token, name, tries=1)
    if size is None:
        return False                                    # the site does not have this file (yet): the caller uses its other source
    url = "%s/3d/files/downloads/%s" % (site, urllib.parse.quote(name))
    try:
        nm_fetch.fetch(url, dest, headers=nm_fetch.site_headers(token), size=size, sha256=sha, stall=900, out=say, label=name)
    except nm_fetch.FetchError as e:
        say("could not fetch %s from the site: %s" % (name, e))
        return False
    return True


def run_pip(layout, args, say, run=subprocess.run, timeout=1800):
    cmd = [layout.py, "-m", "pip", "install", "--timeout", "60", "--retries", "3", "--progress-bar", "off"] + args
    r = run(cmd, capture_output=True, text=True, timeout=timeout, env=pip_env(layout), **({"creationflags": 0x08000000} if IS_WIN else {}))
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-4:]
    if r.returncode != 0:
        say("pip failed (code %s): %s" % (r.returncode, " | ".join(tail)[:300]))
    return r.returncode == 0


def install(layout, agent, say=print, run=subprocess.run, fetch=fetch_site_file, base_python=None, set_step=lambda s: None):
    """Make the venv and install the locked packages. Does nothing when the marker matches. Raises InstallError(code, why)."""
    if not os.path.isfile(os.path.join(layout.code, "app.py")):
        raise InstallError("code_missing", "the vendored Abagram code is missing from %s (the node update did not bring it)" % layout.code)
    if not os.path.isfile(layout.lock):
        raise InstallError("code_missing", "requirements-node.lock.txt is missing from %s" % layout.code)
    os.makedirs(layout.root, exist_ok=True)
    if not os.path.isfile(layout.py):
        set_step("creating the virtual environment")
        base = base_python or sys.executable
        r = run([base, "-m", "venv", layout.venv], capture_output=True, text=True, timeout=600,
                **({"creationflags": 0x08000000} if IS_WIN else {}))
        if r.returncode != 0 or not os.path.isfile(layout.py):
            raise InstallError("venv_failed", "python -m venv failed: %s" % ((r.stderr or r.stdout or "").strip()[-300:] or r.returncode))
    if venv_ready(layout, run):
        return "ready"
    sources = []
    if pack_fits():
        set_step("fetching the package pack from the site")
        zpath = os.path.join(layout.downloads, WHEEL_PACK)
        if fetch(agent, WHEEL_PACK, zpath, say):
            try:
                shutil.rmtree(layout.wheelhouse, ignore_errors=True)
                unpack_zip(zpath, layout.wheelhouse)
                sources.append(("find-links", layout.wheelhouse))
            except (OSError, zipfile.BadZipFile, InstallError) as e:
                say("the wheel pack could not be used (%s); using the package indexes" % e)
    sources += [("index", u) for u in index_order(probe=(run is subprocess.run))]
    tried = []
    for kind, url in sources:
        set_step("installing packages (%s)" % ((urllib.parse.urlparse(url).hostname or "index") if kind == "index" else "site pack"))
        args = ["--no-index", "--find-links", url] if kind == "find-links" else ["--index-url", url]
        say("pip install via %s" % (url if kind == "index" else "the site's wheel pack"))
        try:
            ok = run_pip(layout, args + ["-r", layout.lock], say, run)
        except (OSError, subprocess.SubprocessError) as e:
            ok = False
            tried.append("%s: %s" % (url, e))
        if ok:
            write_json(layout.marker, {"spec": lock_spec(layout), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": url, "version": VERSION})
            return "installed"
        tried.append(url)
    raise InstallError("pip_failed", "no package source worked (%s)" % "; ".join(tried)[:300])


def ensure_browser(layout, agent, say=print, fetch=fetch_site_file, set_step=lambda s: None):
    """The browser Abagram will use, fetching the site's Chromium only when no Edge/Chrome is installed."""
    found = find_browser(layout)
    if found or not IS_WIN:
        return found
    set_step("fetching the browser pack from the site")
    zpath = os.path.join(layout.downloads, CHROMIUM_PACK)
    if fetch(agent, CHROMIUM_PACK, zpath, say):
        try:
            unpack_zip(zpath, layout.browser_dir)
            return find_browser(layout)
        except (OSError, zipfile.BadZipFile, InstallError) as e:
            say("the browser pack could not be used: %s" % e)
    return {}


# ───────────────────────────────────────────── talking to the running service

class Client:
    """The local Abagram over HTTP (127.0.0.1). The key goes in X-Igs-Token; POSTs carry the site's own X-Igs header."""

    def __init__(self, port, token, host="127.0.0.1", timeout=20):
        self.base = "http://%s:%d" % (host, int(port))
        self.token = token
        self.timeout = timeout

    def call(self, method, path, body=None, timeout=None):
        headers = {"X-Igs-Token": self.token, "Accept": "application/json"}
        data = None
        if method == "POST":
            headers["X-Igs"] = "1"
            headers["Content-Type"] = "application/json"
            data = json.dumps(body if body is not None else {}).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw.decode("utf-8")) if raw else {})
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8"))
            except (ValueError, OSError):
                return e.code, {}
        except (urllib.error.URLError, OSError, ValueError, socket.timeout) as e:
            raise ServiceDown(str(e)[:200])

    def get(self, path, timeout=None):
        return self.call("GET", path, timeout=timeout)

    def post(self, path, body=None, timeout=None):
        return self.call("POST", path, body, timeout=timeout)

    def status(self):
        code, d = self.get("/api/status?since=1000000")      # since: no log lines, only the state
        if code != 200 or not isinstance(d, dict):
            raise ServiceDown("status answered HTTP %s" % code)
        return d


def summarize_status(d):
    """What the node report needs from Abagram's /api/status."""
    queue = d.get("queue") or {}
    prefs = d.get("prefs") or {}
    budget = d.get("budget") or {}
    limits = budget.get("limits") or {}
    used = budget.get("used") or {}
    page = used.get("page") or {}
    cool = budget.get("cooldown") or None
    session = d.get("session") or {}
    return {"busy": bool(d.get("busy")), "state": d.get("state"), "run": d.get("run"),
            "signed_in": bool(queue.get("signed_in")), "account": session.get("username") or "",
            "proxy": mask_proxy(prefs.get("proxy") or ""), "has_proxy": bool(prefs.get("proxy")),
            "cooldown_until": int(cool["until"]) if cool and cool.get("until") else None,
            "cooldown_reason": (cool or {}).get("reason") or "",
            "pages_hour": [int(page.get("hour") or 0), int(limits.get("pages_hour") or 0)],
            "pages_day": [int(page.get("day") or 0), int(limits.get("pages_day") or 0)]}


# ───────────────────────────────────────────── the service (supervisor)

class Service:
    """Installs, starts, watches and restarts Abagram. One per node. All the slow work happens in its own thread."""

    def __init__(self, agent, layout=None, say=None, run=subprocess.run, popen=subprocess.Popen, clock=time.time):
        self.agent = agent
        self.layout = layout or Layout(agent.HERE, agent.DATA)
        self.say = say or (lambda m: agent.log("abagram: " + m))
        self.run, self.popen, self.clock = run, popen, clock
        self.lock = threading.RLock()
        self.thread = None
        self.stop_flag = False
        self.state = "absent"          # absent | installing | starting | up | down | error
        self.step = ""
        self.error = ""
        self.error_code = ""
        self.install_fails = 0
        self.next_install_at = 0.0
        self.proc = None
        self.pid = None
        self.port = None
        self.token = None
        self.browser = {}
        self.restarts = []             # times of restarts (last hour)
        self.last = None               # summarize_status of the last poll
        self.last_ok = 0.0
        self.reach = None              # {'ok','status','ms','via','at'}
        self.reach_at = 0.0
        self.proxy_applied = ""
        self.proxy_source = ""
        self.started_stamp = ""
        self.down_since = 0.0
        self.announced = set()

    # ---- the report the node sends with every heartbeat (cheap: no network)
    def client(self):
        if not (self.port and self.token):
            return None
        return Client(self.port, self.token)

    def problem(self):
        """A short code for what stands between the owner and a working reader (None = ready)."""
        if self.state in ("absent", "installing"):
            return "installing"
        if self.state == "error" and not self.port:
            return "install_error"
        if self.state == "starting":
            return "starting"
        if self.state != "up" or not self.last:
            return "service_down"
        if not self.last.get("signed_in"):
            return "not_signed_in"
        if self.reach is not None and self.reach.get("ok") is False:
            return "unreachable"
        if self.last.get("cooldown_until") and self.last["cooldown_until"] > self.clock():
            return "cooldown"
        return None

    def report(self):
        last = self.last or {}
        rep = {"version": VERSION, "state": self.state, "step": self.step, "problem": self.problem(),
               "ready": self.problem() is None, "installed": os.path.isfile(self.layout.py) and bool(read_json(self.layout.marker)),
               "error": self.error[:300], "error_code": self.error_code,
               "port": self.port, "url": ("http://127.0.0.1:%d/" % self.port) if self.port else "", "open_with": "Open-Abagram.bat",
               "browser": {k: v for k, v in (self.browser or {}).items() if k in ("name", "channel")} or None,
               "signed_in": bool(last.get("signed_in")), "account": last.get("account") or "", "busy": bool(last.get("busy")),
               "proxy": last.get("proxy") or "", "proxy_source": getattr(self, "proxy_source", ""),
               "reach": ({k: self.reach.get(k) for k in ("ok", "status", "via")} if self.reach else None),
               "pages_hour": last.get("pages_hour"), "pages_day": last.get("pages_day"),
               "cooldown_until": last.get("cooldown_until"), "restarts_last_hour": len([t for t in self.restarts if t > self.clock() - 3600])}
        return rep

    # ---- the supervisor thread
    def ensure_thread(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_flag = False
            self.thread = threading.Thread(target=self._loop, name="abagram-supervisor", daemon=True)
            self.thread.start()

    def stop_thread(self):
        self.stop_flag = True

    def _loop(self):
        while not self.stop_flag:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the supervisor must never die
                self._fail("supervisor", "%s: %s" % (type(e).__name__, e), keep_state=True)
            for _ in range(int(LOOP_S * 2)):
                if self.stop_flag:
                    return
                time.sleep(0.5)

    def tick(self):
        """One round: install if needed, start if needed, poll, apply the proxy, test the reach now and then. Safe to call from tests."""
        now = self.clock()
        if not self._installed():
            managed = self._install_list_item("packages")
            if managed is not None:
                # the node's install list (requirements.d/abagram.json, agent 2.11) is doing it, with its own retries and the panel's
                # «تلاش دوباره» button: this supervisor only mirrors what it says and never installs in parallel
                if managed.get("state") == "failed":
                    self._fail("pip_failed", str(managed.get("error") or "the install failed")[:300])
                else:
                    self.state, self.error = "installing", ""
                    self.step = str(managed.get("detail") or "waiting for the install list")[:120]
                return
            if now < self.next_install_at:
                return
            self.state, self.error = "installing", ""
            try:
                self._install()
            except InstallError as e:
                self.install_fails += 1
                self.next_install_at = now + RETRY_INSTALL_S[min(self.install_fails - 1, len(RETRY_INSTALL_S) - 1)]
                self._fail(e.code, str(e))
                return
            self.install_fails = 0
        self.browser = ensure_browser(self.layout, self.agent, self.say, set_step=self._set_step) or self.browser
        if self.browser == {} and IS_WIN:
            self._fail("no_browser", "no Edge/Chrome is installed and the site has no browser pack", keep_state=True)
            return
        self._ensure_running()
        self._poll()
        if self.state == "up":
            self._apply_proxy()
            self._maybe_reach()
            self._maybe_restart_for_update()

    def _install_list_item(self, item_id):
        """The state dict of one item of the install list's «abagram» feature, or None when the install list does not manage Abagram on
        this node (bootstrap.py missing, or no requirements.d/abagram.json): then this supervisor installs by itself."""
        boot = getattr(self.agent, "BOOTSTRAP", None)
        if boot is None:
            return None
        try:
            if not any(s.get("feature") == FEATURE for s in boot.specs):
                return None
            return dict(boot.item_state(FEATURE, item_id))
        except Exception:  # noqa: BLE001
            return None

    def _set_step(self, text):
        self.step = text

    def _fail(self, code, text, keep_state=False):
        first = (code, text[:80]) not in self.announced
        self.error, self.error_code = text, code
        if not keep_state:
            self.state = "error"
        if first:                                           # once per distinct problem, so the panel log does not fill up
            self.announced.add((code, text[:80]))
            msg = "Abagram on this node: %s - %s | آباگرام روی این سرور پردازش: %s" % (code, text[:200], FA_PROBLEMS.get(code, "خطا"))
            self.agent.warn(msg) if hasattr(self.agent, "warn") else self.say(msg)

    # ---- installing
    def _installed(self):
        return venv_ready(self.layout, self.run)

    def _install(self):
        self.say("installing (once) - Python packages and the browser")
        self._notify("نصب خودکارِ آباگرام شروع شد (فقط یک بار؛ چند دقیقه طول می‌کشد) | Abagram install started on this node")
        result = install(self.layout, self.agent, self.say, self.run, set_step=self._set_step)
        self.step = ""
        self.say("packages: %s" % result)
        if result == "installed":
            self._notify("آباگرام نصب شد | Abagram packages installed")

    def _notify(self, text):
        add = getattr(getattr(self.agent, "SITE_LOG", None), "add", None)
        if add:
            try:
                add("INFO", text)
            except Exception:  # noqa: BLE001
                pass

    # ---- running
    def _service_info(self):
        return read_json(self.layout.service_file, {}) or {}

    def _env(self):
        env = dict(os.environ)
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", IGS_PORT=str(self.port), IGS_HOST="127.0.0.1", IGS_DATA=self.layout.data,
                   IGS_API_TOKEN=self.token, IGS_NODE_MODE="1", IGS_AUTH="0", IGS_NO_BROWSER="1",
                   PLAYWRIGHT_BROWSERS_PATH=os.path.join(self.layout.root, "pw-browsers"))
        for k in ("IGS_BROWSER_CHANNEL", "IGS_BROWSER_EXE"):
            env.pop(k, None)
        if self.browser.get("channel"):
            env["IGS_BROWSER_CHANNEL"] = self.browser["channel"]
        elif self.browser.get("exe"):
            env["IGS_BROWSER_EXE"] = self.browser["exe"]
        return env

    def _ensure_running(self):
        info = self._service_info()
        if self.token is None:
            saved = info.get("token") or ""
            self.token = saved if len(saved) >= 32 else secrets.token_urlsafe(36)
        if self.port is None and info.get("port"):
            self.port = info["port"]
        alive = (self.proc is not None and self.proc.poll() is None) or (self.proc is None and pid_alive(self.pid or info.get("pid")))
        if alive and self.proc is not None:
            hung = self.state == "down" and self.down_since and self.clock() - self.down_since > HUNG_S
            if not hung:
                return                                      # ours and alive (a slow answer is not a reason to restart it)
            self.say("the service has not answered for %d minutes - restarting it" % (HUNG_S // 60))
            self.stop_service()
        elif alive:                                         # started by an earlier run of the agent: adopt it when it answers
            try:
                Client(info.get("port") or self.port, self.token, timeout=10).status()
                self.pid, self.port, self.started_stamp = info.get("pid"), info.get("port") or self.port, info.get("code_stamp", "")
                self.state = "up"
                return
            except ServiceDown:
                if self.state == "up" or self.down_since == 0:
                    self.down_since = self.clock()
                if self.clock() - self.down_since <= HUNG_S:
                    self.state = "down"
                    return
                kill_pid(info.get("pid"))                   # an old copy that stopped answering: end it, start a clean one
        if self.proc is not None or self.state == "up":
            self.restarts.append(self.clock())
            self.say("the service stopped (exit code %s) - starting it again" % (self.proc.poll() if self.proc else "?"))
        self.restarts = [t for t in self.restarts if t > self.clock() - 3600]
        if len(self.restarts) > MAX_RESTARTS_PER_HOUR:
            self._fail("restart_loop", "the service stopped %d times within an hour; waiting" % len(self.restarts), keep_state=True)
            self.state = "down"
            return
        self._start()

    def _start(self):
        self.state = "starting"
        self.port = choose_port(self.port)
        os.makedirs(self.layout.logs, exist_ok=True)
        os.makedirs(self.layout.data, exist_ok=True)
        log_path = os.path.join(self.layout.logs, "abagram.log")
        try:
            if os.path.getsize(log_path) > 5 * 1024 * 1024:
                os.replace(log_path, log_path + ".old")
        except OSError:
            pass
        logf = open(log_path, "ab")
        kw = {"creationflags": 0x08000000 | 0x00000200} if IS_WIN else {"start_new_session": True}   # no window, own process group
        self.proc = self.popen([self.layout.py, "app.py"], cwd=self.layout.code, env=self._env(), stdout=logf, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, **kw)
        self.pid = self.proc.pid
        self.started_stamp = code_stamp(self.layout)
        write_json(self.layout.service_file, {"port": self.port, "token": self.token, "pid": self.pid, "code_stamp": self.started_stamp,
                                              "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "version": VERSION})
        self.say("started on http://127.0.0.1:%d/ (pid %s)" % (self.port, self.pid))
        for _ in range(60):                                 # up to ~30 s to answer
            if self.proc.poll() is not None:
                break
            try:
                Client(self.port, self.token, timeout=3).status()
                self.state = "up"
                return
            except ServiceDown:
                time.sleep(0.5)
        self.state = "down"
        self._fail("start_failed", "the service did not answer after starting (see %s)" % log_path, keep_state=True)

    def _poll(self):
        if not (self.port and self.token):
            return
        try:
            self.last = summarize_status(Client(self.port, self.token, timeout=10).status())
            self.last_ok = self.clock()
            if self.state != "up":
                self.say("the service answers")
            self.state = "up"
            self.down_since = 0.0
            if self.error_code in ("start_failed", "restart_loop", "supervisor"):
                self.error, self.error_code = "", ""
        except ServiceDown as e:
            if self.state == "up":
                self.say("the service does not answer: %s" % e)
                self.down_since = self.clock()
            self.state = "down"

    def _apply_proxy(self):
        """Set Abagram's proxy from the owner's choice / the local system proxy when it has none yet (Instagram is filtered in Iran)."""
        if not self.last or self.last.get("has_proxy"):
            self.proxy_source = "abagram" if self.last and self.last.get("has_proxy") else ""
            return
        url, where = wanted_proxy(self.layout)
        if not url or url == self.proxy_applied:
            return
        try:
            code, _d = Client(self.port, self.token).post("/api/prefs", {"values": {"proxy": url}})
        except ServiceDown:
            return
        if code == 200:
            self.proxy_applied, self.proxy_source = url, where
            self.say("Abagram's proxy set to %s (from %s)" % (mask_proxy(url), where))
            self.reach_at = 0                               # test the line again with it
        else:
            self.say("Abagram refused the proxy %s (HTTP %s)" % (mask_proxy(url), code))
            self.proxy_applied = url

    def _maybe_reach(self, force=False):
        if not force and self.clock() - self.reach_at < REACH_EVERY_S:
            return self.reach
        self.reach_at = self.clock()
        try:
            code, d = Client(self.port, self.token, timeout=30).post("/api/health/test", {})
        except ServiceDown:
            return self.reach
        if code == 200 and isinstance(d, dict):
            self.reach = {"ok": bool(d.get("ok")), "status": d.get("status"), "ms": d.get("ms"), "via": d.get("via"), "at": int(self.clock())}
        return self.reach

    def test_reach(self):
        return self._maybe_reach(force=True)

    def _maybe_restart_for_update(self):
        """The vendored code was replaced by an update: restart the service on it (only when it is idle)."""
        stamp = code_stamp(self.layout)
        if not stamp or not self.started_stamp or stamp == self.started_stamp or (self.last or {}).get("busy"):
            return
        try:
            code, _d = Client(self.port, self.token).post("/api/admin/restart", {})
        except ServiceDown:
            return
        if code == 200:
            self.say("code updated - the service restarts on the new code")
            self.started_stamp = ""
            self.state = "down"                             # the next tick starts it again

    def stop_service(self):
        """Used by tests and a clean shutdown: end the process this object started."""
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=15)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass


FA_PROBLEMS = {
    "code_missing": "کدِ آباگرام در بستهٔ به‌روزرسانی نبود",
    "venv_failed": "ساختنِ محیطِ پایتون برای آباگرام شکست خورد",
    "pip_failed": "نصبِ بسته‌های پایتونِ آباگرام شکست خورد (خودکار دوباره تلاش می‌شود)",
    "no_port": "پورتِ آزاد پیدا نشد",
    "bad_zip": "بستهٔ دانلودی سالم نبود",
    "no_browser": "مرورگری (Edge یا Chrome) روی این کامپیوتر نیست و بستهٔ مرورگر هم روی سایت نیست",
    "start_failed": "آباگرام بعد از روشن شدن جواب نداد",
    "restart_loop": "آباگرام چندین بار پشتِ سرِ هم از کار افتاد؛ کمی صبر می‌کنم",
    "supervisor": "خطای ناظرِ آباگرام",
}

_SERVICES = {}


def get_service(agent):
    key = os.path.join(agent.DATA, "abagram")
    svc = _SERVICES.get(key)
    if svc is None:
        svc = _SERVICES[key] = Service(agent)
    return svc


# ───────────────────────────────────────────── ig.scrape

def clean_accounts(raw, limit=MAX_ACCOUNTS * 4):
    out, seen = [], set()
    for item in raw or []:
        name = str(item or "").strip().lstrip("@").lower()
        if USERNAME_RE.match(name) and name not in seen:
            seen.add(name)
            out.append(name)
    return out[:limit]


def page_room(summary, margin=BUDGET_MARGIN):
    """How many profile reads Abagram's own budget leaves (it counts page opens; a profile read costs one or two)."""
    rooms = []
    for key in ("pages_hour", "pages_day"):
        used, cap = (summary.get(key) or [0, 0])
        if cap:
            rooms.append(cap - used - margin)
    return max(0, min(rooms) // PAGES_PER_ACCOUNT) if rooms else MAX_ACCOUNTS


def stopped(code, message, **extra):
    return dict({"code": code, "message": message}, **extra)


def gate(summary, now):
    """The reason this run must not even start, or None."""
    if not summary.get("signed_in"):
        return stopped("not_signed_in", "Abagram on this node is not signed in to Instagram yet")
    until = summary.get("cooldown_until")
    if until and until > now:
        return stopped("limit", "Abagram is pausing after Instagram said to wait (until %s)" % time.strftime("%H:%M", time.localtime(until)))
    if page_room(summary) <= 0:
        return stopped("budget", "Abagram's page budget for this hour/day is used up")
    return None


def read_one(client, name, fresh, limit, progress, sleep, timeout_s=READ_TIMEOUT_S, clock=time.time):
    """Read one page. Returns ('ok', doc) | ('skip', why) | ('stop', stopped-dict) | ('line', why)."""
    deadline = clock() + 90
    while True:
        code, d = client.post("/api/profile", {"username": name, "fresh": bool(fresh)})
        if code == 200 and d.get("ok"):
            run = d.get("run")
            break
        if code == 409 and clock() < deadline:             # someone (the owner, in the Abagram page) is using the browser: wait
            progress("waiting for Abagram to be free")
            sleep(5)
            continue
        if code == 409:
            return "stop", stopped("busy", "Abagram stayed busy with another job for 90 seconds")
        if code == 422:
            return "skip", "invalid_name"
        return "line", "HTTP %s" % code
    end = clock() + timeout_s
    st = {}
    while clock() < end:
        sleep(2)
        st = client.status()
        if st.get("run") == run and not st.get("busy") and st.get("state") in ("success", "failed", "cancelled"):
            break
    else:
        try:
            client.post("/api/cancel", {})
        except ServiceDown:
            pass
        return "line", "timeout"
    outcome = st.get("outcome") or {}
    kind = outcome.get("kind") or ("ok" if st.get("state") == "success" else "error")
    if kind == "ok":
        code, doc = client.get("/api/trend/%s?limit=%d" % (urllib.parse.quote(name), limit))
        if code == 200 and isinstance(doc, dict):
            if (doc.get("profile") or {}).get("is_private"):
                return "skip", "private"
            return "ok", doc
        return "line", "no data after the read (HTTP %s)" % code
    if kind in STOP_KINDS:
        c, msg = STOP_KINDS[kind]
        return "stop", stopped(c, msg, outcome=kind, note=str(outcome.get("note") or outcome.get("ig_message") or "")[:200])
    if kind in SKIP_KINDS:
        return "skip", kind
    if kind == "cancelled":
        return "stop", stopped("cancelled", "the read was cancelled")
    return "line", kind


def batch_account(doc):
    prof = doc.get("profile") or {}
    return {"username": doc.get("username") or prof.get("username"), "ig_user_id": prof.get("user_id") or "", "full_name": prof.get("full_name") or "",
            "biography": prof.get("biography") or "", "followers": prof.get("followers"), "following": prof.get("following"),
            "posts_count": prof.get("posts"), "is_verified": bool(prof.get("is_verified")), "is_private": bool(prof.get("is_private")),
            "is_business": bool(prof.get("is_business")), "category": prof.get("category") or "", "fetched_at": prof.get("fetched_at") or doc.get("fetched_at")}


def batch_posts(doc):
    name = doc.get("username") or (doc.get("profile") or {}).get("username")
    out = []
    for p in doc.get("posts") or []:
        row = {k: p.get(k) for k in ("code", "id", "kind", "taken_at", "caption", "hashtags", "likes", "comments", "views", "likes_hidden",
                                      "comments_disabled", "pinned", "music", "items_count", "width", "height", "paid_partnership")}
        row["account"] = name
        out.append(row)
    return out


def scrape(client, accounts, *, max_accounts=5, pace=DEFAULT_PACE_S, fresh=True, limit=24, progress=lambda f, m: None,
           sleep=time.sleep, rng=None, clock=time.time, node="", timeout_s=READ_TIMEOUT_S):
    """Read the recent posts of a few pages, politely. Returns the batch (format nm-ig-batch) - never raises for a Instagram-side problem."""
    rng = rng or random.Random()
    batch = {"format": "nm-ig-batch", "version": 1, "source": "abagram-node", "node": node,
             "read_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(clock())), "accounts": [], "posts": [],
             "per_account": {}, "stopped": None}
    names = clean_accounts(accounts)
    if not names:
        batch["stopped"] = stopped("no_accounts", "no valid page names were given")
        return batch
    try:
        summary = summarize_status(client.status())
    except ServiceDown as e:
        batch["stopped"] = stopped("service_down", "Abagram on this node does not answer (%s)" % e)
        return batch
    why = gate(summary, clock())
    if why:
        batch["stopped"] = why
        return batch
    todo = names[:max(1, min(int(max_accounts), MAX_ACCOUNTS, page_room(summary)))]
    lo = max(15.0, float(pace[0]))
    hi = max(lo, float(pace[1]))
    line_fails = 0
    for i, name in enumerate(todo):
        if i:
            wait = rng.uniform(lo, hi)
            progress(i / len(todo), "pause %d s before the next page" % wait)
            slept = 0.0
            while slept < wait:                                  # in small steps: the site's lease on the job stays alive
                step = min(15.0, wait - slept)
                sleep(step)
                slept += step
                progress(i / len(todo), "pause")
        progress(i / len(todo), "reading %s (%d of %d)" % (name, i + 1, len(todo)))
        try:
            kind, res = read_one(client, name, fresh, limit, lambda m: progress(i / len(todo), m), sleep, timeout_s, clock)
        except ServiceDown as e:
            batch["stopped"] = stopped("service_down", "Abagram stopped answering (%s)" % e)
            break
        if kind == "ok":
            line_fails = 0
            batch["accounts"].append(batch_account(res))
            posts = batch_posts(res)
            batch["posts"] += posts
            batch["per_account"][name] = {"status": "ok", "posts": len(posts)}
        elif kind == "skip":
            batch["per_account"][name] = {"status": res, "posts": 0}
        elif kind == "stop":
            batch["per_account"][name] = {"status": "stopped", "posts": 0}
            batch["stopped"] = res
            break
        else:                                                    # the line / the page: two in a row means the line is down
            line_fails += 1
            batch["per_account"][name] = {"status": "failed", "posts": 0, "why": str(res)[:120]}
            if line_fails >= 2:
                batch["stopped"] = stopped("unreachable", "two pages in a row could not be reached (%s) - the line or the proxy is down" % res)
                break
    batch["not_read"] = [n for n in names if n not in batch["per_account"]]
    progress(1.0, "done")
    return batch


# ───────────────────────────────────────────── job handlers

def _rng_from(payload):
    seed = payload.get("seed")
    return random.Random(seed) if seed is not None else random.Random()


SCRAPE_LOCK = threading.Lock()      # one Instagram reading at a time on this node (Abagram runs one browser job at a time anyway)


def _take_scrape_lock(job, wait_s=3600):
    """Wait for an earlier ig.scrape to end, keeping the site's lease on this job alive."""
    end = time.time() + wait_s
    while not SCRAPE_LOCK.acquire(timeout=15):
        job.progress(0.02, "waiting for the earlier Instagram reading to finish")
        if time.time() > end:
            raise RuntimeError("another Instagram reading kept this node busy for an hour")


def run_scrape(job, agent, service=None, sleep=time.sleep):
    _take_scrape_lock(job)
    try:
        return _run_scrape(job, agent, service, sleep)
    finally:
        SCRAPE_LOCK.release()


def _run_scrape(job, agent, service=None, sleep=time.sleep):
    p = job.payload or {}
    svc = service or get_service(agent)
    client = svc.client()
    pace = p.get("pace_s") or DEFAULT_PACE_S
    try:
        pace = (float(pace[0]), float(pace[1]))
    except (TypeError, ValueError, IndexError):
        pace = DEFAULT_PACE_S

    def progress(fraction, message):
        job.progress(0.05 + 0.9 * max(0.0, min(1.0, fraction)), message[:120])

    if client is None:
        batch = {"format": "nm-ig-batch", "version": 1, "source": "abagram-node", "accounts": [], "posts": [], "per_account": {},
                 "stopped": stopped(svc.problem() or "service_down", "Abagram is not running on this node yet"), "not_read": []}
    else:
        job.progress(0.03, "checking Abagram")
        try:
            batch = scrape(client, p.get("accounts"), max_accounts=int(p.get("max_accounts") or 5), pace=pace, fresh=p.get("fresh", True),
                           limit=int(p.get("posts_per_account") or 24), progress=progress, sleep=sleep, rng=_rng_from(p),
                           node=(getattr(agent, "CONFIG", None) or {}).get("name", ""), timeout_s=int(p.get("read_timeout_s") or READ_TIMEOUT_S))
        except Exception as e:                                   # a Cancelled from job.progress: stop the browser run too, then pass it on
            if type(e).__name__ == "Cancelled":
                try:
                    client.post("/api/cancel", {})
                except ServiceDown:
                    pass
            raise
    batch["store_id"], batch["run_id"] = p.get("store_id"), p.get("run_id")
    with open(job.out("ig_batch.json"), "w", encoding="utf-8") as fh:
        json.dump(batch, fh, ensure_ascii=False)
    stop = batch.get("stopped")
    return {"primary": "ig_batch.json", "engine": "abagram", "accounts_read": len(batch["accounts"]), "posts": len(batch["posts"]),
            "per_account": batch.get("per_account"), "stopped": stop, "not_read": batch.get("not_read"), "report": svc.report()}


def run_health(job, agent, service=None, sleep=time.sleep):
    p = job.payload or {}
    svc = service or get_service(agent)
    job.progress(0.1, "abagram health")
    if p.get("test_connection") and svc.client() is not None:
        svc.test_reach()
    rep = svc.report()
    meta = {"engine": "abagram", "report": rep, "ok": bool(rep.get("state") == "up")}
    page = str(p.get("read") or "").strip().lstrip("@").lower()
    if page and USERNAME_RE.match(page) and svc.client() is not None and rep.get("ready"):
        job.progress(0.4, "reading one page")
        batch = scrape(svc.client(), [page], max_accounts=1, pace=(15, 15), fresh=bool(p.get("fresh", False)), limit=6,
                       progress=lambda f, m: job.progress(0.4 + 0.5 * f, m[:120]), sleep=sleep, node=(getattr(agent, "CONFIG", None) or {}).get("name", ""))
        meta["read"] = {"page": page, "accounts_read": len(batch["accounts"]), "posts": len(batch["posts"]), "stopped": batch.get("stopped")}
    elif page:
        meta["read"] = {"page": page, "skipped": rep.get("problem") or "not_ready"}
    return meta


# ───────────────────────────────────────────── registration into agent.py (one guarded line there)

def caps_for(agent):
    svc = get_service(agent)
    # under the test runner the agent's heartbeat must not start the real installer (it built a 222 MB venv in a temp
    # data folder on every test run and filled the server disk, 11/13); tests that want it set NM_ABAGRAM_IN_TESTS=1
    if "unittest" not in sys.modules or os.environ.get("NM_ABAGRAM_IN_TESTS") == "1":
        svc.ensure_thread()
    return {"instagram": True, "abagram": svc.report()}


def register(agent):
    """agent.py calls this once: the job kinds, their capability, the node report entry, and 'no job slot' (they use no GPU)."""
    agent.HANDLERS["ig.scrape"] = lambda job: run_scrape(job, agent)
    agent.HANDLERS["ig.health"] = lambda job: run_health(job, agent)
    agent.BACKGROUND_KINDS = tuple(agent.BACKGROUND_KINDS) + tuple(k for k in KINDS if k not in agent.BACKGROUND_KINDS)
    probe = agent.Capabilities.probe
    if getattr(probe, "_abagram_wrapped", False):
        return

    def probe_with_abagram(self):
        caps = probe(self)
        try:
            caps.update(caps_for(agent))
        except Exception as e:  # noqa: BLE001 - never let this keep the heartbeat from going out
            agent.warn("abagram report could not be made: %s" % e)
        return caps

    probe_with_abagram._abagram_wrapped = True
    agent.Capabilities.probe = probe_with_abagram


# ───────────────────────────────────────────── command line (Open-Abagram.bat)

def _layout_from_here():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import nm_data
    return Layout(here, nm_data.data_root(here))


class SiteShim:
    """What fetch_site_file() needs from the agent (the site's address and this node's token), read from node.json: the install list
    runs the commands below in their own process, where the running agent is not at hand."""

    def __init__(self, layout):
        cfg = {}
        for path in (os.path.join(os.path.dirname(layout.root), "node.json"), os.path.join(os.path.dirname(layout.code), "site.json")):
            d = read_json(path, {}) or {}
            for k in ("site", "token"):
                if d.get(k) and not cfg.get(k):
                    cfg[k] = d[k]
        self.CONFIG = {"token": cfg.get("token", "")}
        self._site = (os.environ.get("NM_SITE") or cfg.get("site") or "").rstrip("/")

    def site_base(self):
        return self._site


def cli_check_packages(layout):
    ok = venv_ready(layout)
    print("packages: %s" % ("ready" if ok else "not installed (or the lock file changed)"), flush=True)
    return 0 if ok else 1


def cli_install_packages(layout):
    """Called by the node's install list (requirements.d/abagram.json): make the environment and install the locked packages - first from
    the site's wheel pack, then the package mirrors. Idempotent; exit code 0 = ready."""
    try:
        res = install(layout, SiteShim(layout), say=lambda m: print(m, flush=True), set_step=lambda s: print("step: %s" % s, flush=True))
    except InstallError as e:
        print("FAILED (%s): %s" % (e.code, e), flush=True)
        return 1
    print("packages: %s" % res, flush=True)
    return 0


def cli_check_browser(layout):
    found = find_browser(layout)
    print("browser: %s" % (found.get("name") or "none found"), flush=True)
    return 0 if found else 1


def cli_install_browser(layout):
    found = ensure_browser(layout, SiteShim(layout), say=lambda m: print(m, flush=True), set_step=lambda s: print("step: %s" % s, flush=True))
    if found:
        print("browser: %s" % (found.get("name") or "ok"), flush=True)
        return 0
    print("FAILED (no_browser): no Microsoft Edge or Google Chrome is installed on this computer and the site has no browser pack "
          "(%s). Install Edge or Chrome, or put %s in the site's downloads folder." % (CHROMIUM_PACK, CHROMIUM_PACK), flush=True)
    return 1


#: the commands the node's install list (requirements.d/abagram.json) runs: command word -> function name in this module
CLI_COMMANDS = {"check-packages": "cli_check_packages", "install-packages": "cli_install_packages",
                "check-browser": "cli_check_browser", "install-browser": "cli_install_browser"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    layout = _layout_from_here()
    info = read_json(layout.service_file, {}) or {}
    if cmd in CLI_COMMANDS:
        return globals()[CLI_COMMANDS[cmd]](layout)
    if cmd == "open-ui":
        if not (info.get("port") and info.get("token")) or not pid_alive(info.get("pid")):
            print("[!] Abagram is not running on this computer yet. Keep START.bat open; the first start installs it by itself (a few minutes).")
            print("    Look at the node page in the panel for the progress, then run this file again.")
            return 1
        import webbrowser
        url = "http://127.0.0.1:%d/?igs_key=%s" % (info["port"], info["token"])
        print("Opening Abagram in your browser (%s) ..." % ("http://127.0.0.1:%d/" % info["port"]))
        print("Sign in to Instagram on its first page. If Instagram is blocked, open Settings > Proxy in Abagram and put your VPN's local")
        print("address there (v2rayN: http://127.0.0.1:10809).")
        webbrowser.open(url)
        return 0
    if cmd == "status":
        print(json.dumps({"service": {k: info.get(k) for k in ("port", "pid", "started_at", "version")}, "running": pid_alive(info.get("pid")),
                          "installed": bool(read_json(layout.marker)), "logs": layout.logs}, indent=1))
        return 0
    print("usage: abagram_jobs.py open-ui | status | check-packages | install-packages | check-browser | install-browser")
    return 2


if __name__ == "__main__":
    sys.exit(main())
