#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""instai_jobs.py - InstAI (the owner's animation / story studio, github.com/maniUZqqz/Instai) as a neighbour of this node: found, kept up to date and
started by the node by itself, and its own self-test report passed on to the site.

WHY: the owner's InstAI folder on this PC came from an old "Download ZIP"; its START.bat cannot update itself, so every fix on GitHub stayed away from
it until somebody copied a fresh ZIP over the folder by hand. The owner asked that nothing be left to do by hand once the node is on, so the node does that
one time by itself, with the SAME updater InstAI ships (scripts/self_update.py: protects data / .env / models / tools / .venv, backs up every file it
replaces, never goes back to a lower version) - nothing new is invented here.

WHAT THE NODE DOES (a supervisor thread of the agent, one look every two minutes, the GitHub question at most every half hour):
  1. finds the InstAI folder (env NM_INSTAI_DIR, the remembered one, then folders whose name contains "instai" on the Desktop / in the user's folder /
     on the drive roots, up to three levels deep; a folder counts only when manage.py, instai/settings.py and VERSION are there);
  2. asks GitHub for the VERSION of main (raw file; a CDN mirror as the second way) and reads InstAI's own state: the version, whether START.bat has the updater,
     whether the server answers (http://127.0.0.1:<port>/api/health) and the report of InstAI's own self-test (data/selftest/pc.json);
  3. when the folder cannot update itself (no updater) or GitHub has a newer version AND InstAI is NOT running, runs scripts/self_update.py (fetching that
     one script from GitHub first when the old folder does not have it). A running InstAI is never touched: the update waits for it to stop;
  4. starts InstAI (START.bat with no browser and no pause) right after an update, and once when the node starts if InstAI is not running at all - not
     again after the owner stopped it with STOP.bat (until the node starts the next time);
  5. reports all of this in the heartbeat (caps["instai"]) so the panel and the site's self-test show it: found / version / update state / running / what to do.

WHAT IT NEVER DOES: touch InstAI while it runs, delete or overwrite the owner's data, .env, models, tools or virtual environments, go back to a lower version,
send anything anywhere except the two GitHub reads above, or stop the agent when something here fails (every error is a line in the report).

Switches (environment of the agent): NM_INSTAI_SYNC=0 (report only, never update or start), NM_INSTAI_START=0 (update but never start), NM_INSTAI_DIR=<folder>,
NM_INSTAI_REPO / NM_INSTAI_BRANCH, NM_INSTAI_RAW (a base URL that replaces the GitHub reads; the tests point it at a local server).

Python 3.8+ standard library only (the agent's own interpreter). Console text is English (the Windows console garbles Persian); the report carries Persian too.
"""
import functools
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

VERSION = "1.0"
REPO = "maniUZqqz/Instai"
BRANCH = "main"
IS_WIN = sys.platform.startswith("win")
UA = "NM-node-instai-sync/1.0"
FIRST_DELAY_S = 90.0
LOOP_S = 120.0
REMOTE_EVERY_S = 1800.0
RETRY_UPDATE_S = (900, 3600, 3 * 3600)        # after a failed update: wait, then try again by itself
STARTING_GRACE_S = 20 * 60                    # the first START.bat after a big jump installs packages: do not call it dead for this long
UPDATE_TIMEOUT_S = 900
MARKERS = ("manage.py", os.path.join("instai", "settings.py"), "VERSION")
SELF_UPDATE = os.path.join("scripts", "self_update.py")
STATE_FA = {
    "disabled": "همگام‌سازی خودکارِ InstAI با NM_INSTAI_SYNC=0 خاموش شده",
    "not_found": "پوشهٔ InstAI روی این رایانه پیدا نشد (پوشه‌ای که اسمش instai دارد و manage.py داخلش است)",
    "ok": "InstAI به‌روز است و کار می‌کند",
    "current": "InstAI به‌روز است ولی روشن نیست",
    "updating": "در حال به‌روزرسانیِ InstAI ...",
    "starting": "InstAI روشن شد و بستهٔ خودش را آماده می‌کند (بار اول چند دقیقه)",
    "waiting_running": "نسخهٔ تازهٔ InstAI هست ولی InstAI روشن است؛ با STOP.bat و START.bat (یا بعد از خاموش شدنش) خودکار نصب می‌شود",
    "failed": "به‌روزرسانیِ InstAI شکست خورد؛ خودش دوباره تلاش می‌کند",
}


def log(msg):
    try:
        print("[instai] " + msg, flush=True)
    except Exception:  # noqa: BLE001
        pass


def _now():
    return time.time()


def vtuple(v):
    out = []
    for part in str(v or "").strip().lstrip("vV").split(".")[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def read_text(path, limit=200000):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# ───────────────────────────────────────────── finding the folder

def is_instai_dir(path):
    return bool(path) and os.path.isdir(path) and all(os.path.exists(os.path.join(path, m)) for m in MARKERS)


def _descend(path, depth, out):
    """`path` (a folder whose name looks like InstAI) and what is inside it, `depth` more levels."""
    if is_instai_dir(path):
        out.append(path)
        return
    if depth <= 0:
        return
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return
    for n in names:
        p = os.path.join(path, n)
        if os.path.isdir(p) and not n.startswith(".") and n.lower() not in ("node_modules", "data", "models", "tools", "media", "logs"):
            _descend(p, depth - 1, out)


def search_roots(env=None):
    env = env if env is not None else os.environ
    home = env.get("USERPROFILE") or os.path.expanduser("~")
    roots = []
    for base in (home, env.get("OneDrive") or ""):
        if base:
            roots += [os.path.join(base, "Desktop"), base, os.path.join(base, "Documents"), os.path.join(base, "Downloads")]
    if IS_WIN:
        roots += ["C:\\", "D:\\", "E:\\"]
    seen, out = set(), []
    for r in roots:
        k = os.path.normcase(os.path.abspath(r))
        if k not in seen and os.path.isdir(r):
            seen.add(k)
            out.append(r)
    return out


def find_folders(env=None, remembered=""):
    """Every InstAI folder found, the one to use first: NM_INSTAI_DIR, the remembered folder, then the highest version."""
    env = env if env is not None else os.environ
    found = []
    for p in (env.get("NM_INSTAI_DIR", "").strip(), remembered):
        if is_instai_dir(p):
            found.append(os.path.abspath(p))
    if not found:
        for root in search_roots(env):
            try:
                names = sorted(os.listdir(root))
            except OSError:
                continue
            for n in names:
                if "instai" in n.lower():
                    p = os.path.join(root, n)
                    if os.path.isdir(p):
                        _descend(p, 3, found)
    uniq = []
    for p in found:
        a = os.path.abspath(p)
        if a not in uniq:
            uniq.append(a)
    if len(uniq) > 1 and not (env.get("NM_INSTAI_DIR", "").strip() or remembered):
        uniq.sort(key=lambda d: (vtuple(read_text(os.path.join(d, "VERSION")).strip()), os.path.exists(os.path.join(d, ".venv"))), reverse=True)
    return uniq


# ───────────────────────────────────────────── looking at one folder

def env_file(folder):
    out = {}
    for line in read_text(os.path.join(folder, ".env")).splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def health(folder, timeout=1.5):
    env = env_file(folder)
    host = env.get("INSTAI_HOST", "127.0.0.1")
    host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    port = env.get("INSTAI_PORT", os.environ.get("INSTAI_PORT", "8765"))
    try:
        with urllib.request.urlopen("http://%s:%s/api/health" % (host, port), timeout=timeout) as r:
            d = json.loads(r.read(20000).decode("utf-8", "replace"))
        return d if isinstance(d, dict) and d.get("ok") else None
    except Exception:  # noqa: BLE001
        return None


def own_selftest(folder):
    """The summary of InstAI's own self-test (data/selftest/pc.json), or None while it has not run."""
    data = env_file(folder).get("INSTAI_DATA_DIR") or os.path.join(folder, "data")
    rep = read_json(os.path.join(data, "selftest", "pc.json"))
    if not isinstance(rep, dict) or not isinstance(rep.get("checks"), list):
        return None
    s = rep.get("summary") or {}
    bad = [c.get("key") for c in rep["checks"] if c.get("verdict") == "fail"]
    waiting = [c.get("key") for c in rep["checks"] if c.get("verdict") == "pending"]
    warn = [c.get("key") for c in rep["checks"] if c.get("verdict") == "warn"]
    return {"state": s.get("state"), "ok": s.get("ok", 0), "warn": s.get("warn", 0), "fail": s.get("fail", 0), "pending": s.get("pending", 0),
            "failing": bad[:8], "waiting": waiting[:8], "warning": warn[:8], "version": rep.get("version"), "at": rep.get("finished_at")}


def inspect_folder(folder):
    bat = read_text(os.path.join(folder, "START.bat"))
    h = health(folder)
    last = ""
    for line in reversed(read_text(os.path.join(folder, "data", "logs", "update.log"), 100000).splitlines()):
        if line.strip():
            last = line.strip()[:200]
            break
    ver = read_text(os.path.join(folder, "VERSION"), 200).strip().splitlines()
    return {"dir": folder, "version": ver[0].strip() if ver else "",
            "mode": "git" if os.path.exists(os.path.join(folder, ".git")) else "zip",
            "start_bat_has_updater": "self_update.py" in bat, "updater_script": os.path.isfile(os.path.join(folder, SELF_UPDATE)),
            "running": h is not None, "running_version": (h or {}).get("version"), "workers": (h or {}).get("workers"),
            "last_update_line": last, "selftest": own_selftest(folder)}


# ───────────────────────────────────────────── GitHub

def raw_urls(path, env=None):
    env = env if env is not None else os.environ
    repo, branch = env.get("NM_INSTAI_REPO") or REPO, env.get("NM_INSTAI_BRANCH") or BRANCH
    custom = (env.get("NM_INSTAI_RAW") or "").rstrip("/")
    if custom:
        return ["%s/%s/%s/%s" % (custom, repo, branch, path)]
    return ["https://raw.githubusercontent.com/%s/%s/%s" % (repo, branch, path), "https://cdn.jsdelivr.net/gh/%s@%s/%s" % (repo, branch, path)]


def fetch(path, timeout=15, limit=2000000):
    """The bytes of one file of main (the first address that answers), or None."""
    for url in raw_urls(path):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(limit)
        except Exception:  # noqa: BLE001
            continue
    return None


def remote_version():
    raw = fetch("VERSION", 10, 200)
    if not raw:
        return ""
    v = raw.decode("ascii", "ignore").strip().splitlines()[0].strip() if raw.strip() else ""
    return v if re.match(r"^\d+\.\d+\.\d+$", v) else ""


def ensure_updater_script(folder):
    """An old folder has no scripts/self_update.py: take THE one script from GitHub (checked: it says what it is and compiles) and put it there."""
    dest = os.path.join(folder, SELF_UPDATE)
    if os.path.isfile(dest):
        return True, ""
    raw = fetch(SELF_UPDATE.replace(os.sep, "/"))
    if not raw:
        return False, "the updater script could not be downloaded from GitHub"
    text = raw.decode("utf-8", "replace")
    if "InstAI self-update" not in text:
        return False, "the downloaded updater script is not the expected file"
    try:
        compile(text, "self_update.py", "exec")
    except SyntaxError as e:
        return False, "the downloaded updater script does not compile (%s)" % e
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        fh.write(raw)
    os.replace(tmp, dest)
    return True, ""


def run_update(folder, run=subprocess.run):
    """InstAI's own updater, with this agent's Python (it needs only the standard library). Exit 0 = nothing to do / done, 10 = done and START.bat itself changed."""
    ok, why = ensure_updater_script(folder)
    if not ok:
        return {"ok": False, "code": None, "tail": why, "seconds": 0}
    t0 = _now()
    env = dict(os.environ)
    for k in ("INSTAI_NO_UPDATE", "INSTAI_AUTO_UPDATE"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = run([sys.executable, SELF_UPDATE], cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=UPDATE_TIMEOUT_S, **({"creationflags": 0x08000000} if IS_WIN else {}))
        out = (r.stdout or b"")
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out)
        return {"ok": r.returncode in (0, 10), "code": r.returncode, "tail": out.strip()[-600:], "seconds": round(_now() - t0, 1)}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "code": None, "tail": "%s: %s" % (type(e).__name__, e), "seconds": round(_now() - t0, 1)}


def start_instai(folder, popen=subprocess.Popen):
    """START.bat with no browser and no pause, detached. Windows only (InstAI is a Windows app); False elsewhere."""
    bat = os.path.join(folder, "START.bat")
    if not IS_WIN or not os.path.isfile(bat):
        return False
    env = dict(os.environ)
    env.update(INSTAI_NO_BROWSER="1", INSTAI_NO_PAUSE="1", INSTAI_NO_UPDATE="1")     # the update was just done (or is not wanted): do not run it again here
    try:
        popen(["cmd", "/c", "START.bat"], cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              creationflags=0x08000000 | 0x00000200, close_fds=True)         # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: no console of its own, not tied to the agent
        return True
    except OSError as e:
        log("could not start InstAI: %s" % e)
        return False


# ───────────────────────────────────────────── the supervisor

class Service:
    """One per agent. `tick()` is one look (and, when it is the right moment, one update / start); `report()` is what the heartbeat carries.
    Only the supervisor thread ticks, and the update inside a tick can take minutes, so `report()` takes no lock: it reads values that tick() replaces, never edits in place."""

    def __init__(self, data_dir="", env=None):
        self.env = env if env is not None else os.environ
        self.data_dir = data_dir
        self.lock = threading.RLock()
        self.thread = None
        self.folder = ""
        self.info = {}
        self.remote = ""
        self.remote_at = 0.0
        self.state = "not_found"
        self.last_update = None
        self.failures = 0
        self.next_try = 0.0
        self.started_at = 0.0
        self.started_this_run = False
        self.updating = False
        self.checked_at = 0.0
        self.others = []

    # -- switches
    def sync_on(self):
        return str(self.env.get("NM_INSTAI_SYNC", "1")).strip().lower() not in ("0", "off", "no", "false")

    def start_on(self):
        return str(self.env.get("NM_INSTAI_START", "1")).strip().lower() not in ("0", "off", "no", "false")

    # -- the remembered folder
    def _memo(self):
        return os.path.join(self.data_dir, "instai-node.json") if self.data_dir else ""

    def remembered(self):
        m = self._memo()
        return (read_json(m, {}) or {}).get("dir", "") if m else ""

    def remember(self, folder):
        m = self._memo()
        if m:
            try:
                os.makedirs(os.path.dirname(m), exist_ok=True)
                with open(m, "w", encoding="utf-8") as fh:
                    json.dump({"dir": folder}, fh)
            except OSError:
                pass

    # -- one look
    def tick(self, now=None, update=run_update, start=start_instai, get_remote=remote_version):
        now = now if now is not None else _now()
        folders = find_folders(self.env, self.folder or self.remembered())
        self.others = folders[1:]
        self.checked_at = now
        if not folders:
            self.folder, self.info = "", {}
            self.state = "not_found"
            return self.state
        self.folder = folders[0]
        self.remember(self.folder)
        info = self.info = inspect_folder(self.folder)
        if now - self.remote_at > REMOTE_EVERY_S or not self.remote:
            self.remote = get_remote() or self.remote
            self.remote_at = now
        stale = bool(self.remote) and vtuple(self.remote) > vtuple(info["version"])
        needs = (not info["start_bat_has_updater"]) or stale
        if not self.sync_on():
            self.state = "disabled"
            return self.state
        if needs and info["running"]:
            self.state = "waiting_running"
            return self.state
        if needs and now >= self.next_try:
            self._do_update(now, update, start)
            return self.state
        if needs and self.failures:
            self.state = "failed"
            return self.state
        if not needs and not info["running"] and not self.started_this_run and self.start_on():
            self.started_this_run = True
            self.started_at = now if start(self.folder) else self.started_at
        self.state = self._derive(now, info)
        return self.state

    def _derive(self, now, info):
        if info["running"]:
            return "ok"
        if self.started_at and now - self.started_at < STARTING_GRACE_S:
            return "starting"
        return "current"

    def _do_update(self, now, update, start):
        self.updating = True
        self.state = "updating"
        before = self.info.get("version")
        log("updating InstAI in %s (version %s, GitHub %s)" % (self.folder, before, self.remote or "?"))
        try:
            res = update(self.folder)
        finally:
            self.updating = False
        self.info = inspect_folder(self.folder)
        res["from"], res["to"], res["at"] = before, self.info["version"], time.strftime("%Y-%m-%d %H:%M:%S")
        self.last_update = res
        ok = res["ok"] and self.info["start_bat_has_updater"]
        if not ok:
            self.failures += 1
            self.next_try = now + RETRY_UPDATE_S[min(self.failures - 1, len(RETRY_UPDATE_S) - 1)]
            self.state = "failed"
            log("the InstAI update did not work: %s" % res.get("tail", "")[-200:])
            return
        self.failures = 0
        self.next_try = 0.0
        log("InstAI updated %s -> %s" % (before, self.info["version"]))
        if self.start_on() and not self.info["running"]:
            self.started_this_run = True
            if start(self.folder):
                self.started_at = now
        self.state = self._derive(now, self.info)

    # -- the thread
    def ensure_thread(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, name="instai-sync", daemon=True)
            self.thread.start()

    def _loop(self):
        time.sleep(FIRST_DELAY_S)
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the supervisor must never die or stop the agent
                log("look failed: %s: %s" % (type(e).__name__, e))
            time.sleep(LOOP_S)

    # -- what the heartbeat carries
    def report(self):
        i = self.info or {}
        st = self.state
        msg_fa = STATE_FA.get(st, "")
        if st == "failed" and self.last_update:
            msg_fa += ": " + (self.last_update.get("tail") or "")[-160:]
        if st == "waiting_running" and not i.get("start_bat_has_updater"):
            msg_fa = "پوشهٔ InstAI قدیمی است و خودش را به‌روز نمی‌کند، ولی InstAI روشن است؛ بعد از خاموش شدنش خودکار به‌روز می‌شود"
        return {"found": bool(self.folder), "dir": self.folder, "version": i.get("version", ""), "github": self.remote, "mode": i.get("mode", ""),
                "has_updater": bool(i.get("start_bat_has_updater")), "running": bool(i.get("running")), "running_version": i.get("running_version"),
                "state": st, "message_fa": msg_fa, "selftest": i.get("selftest"), "last_update": self.last_update, "others": self.others[:3],
                "sync": self.sync_on(), "checked_at": int(self.checked_at) if self.checked_at else 0, "module": VERSION}


_SERVICE = {"svc": None}


def get_service(agent=None):
    if _SERVICE["svc"] is None:
        data = ""
        try:
            import nm_data

            data = nm_data.data_root(os.path.dirname(os.path.abspath(__file__)))
        except Exception:  # noqa: BLE001
            data = ""
        _SERVICE["svc"] = Service(data)
    return _SERVICE["svc"]


def caps_for(agent):
    svc = get_service(agent)
    # under the test runner the agent's heartbeat must not look at (or start) the real InstAI of the machine
    if "unittest" not in sys.modules or os.environ.get("NM_INSTAI_IN_TESTS") == "1":
        svc.ensure_thread()
    return {"instai": svc.report()}


def register(agent):
    """agent.py calls this once: the node report entry. No job kinds: the site judges the report (backend/apps/compute/selftests/instai.py)."""
    probe = agent.Capabilities.probe
    if getattr(probe, "_instai_wrapped", False):
        return

    def probe_with_instai(self):
        caps = probe(self)
        try:
            caps.update(caps_for(agent))
        except Exception as e:  # noqa: BLE001 - never let this keep the heartbeat from going out
            agent.warn("InstAI report could not be made: %s" % e)
        return caps

    # carry over what the earlier wrappers (abagram_jobs.py ...) put on the function (their "_x_wrapped" markers): the tests and their own idempotence checks look at
    # agent.Capabilities.probe, which is now THIS function
    functools.update_wrapper(probe_with_instai, probe)
    probe_with_instai._instai_wrapped = True
    agent.Capabilities.probe = probe_with_instai


def main(argv=None):
    """python instai_jobs.py [--once]: one look from the command line (prints the report); --apply also updates / starts."""
    argv = sys.argv[1:] if argv is None else argv
    svc = get_service()
    if "--apply" not in argv:
        svc.env = dict(os.environ, NM_INSTAI_SYNC="0")
    svc.tick()
    print(json.dumps(svc.report(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
