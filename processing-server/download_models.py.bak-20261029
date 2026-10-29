#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UpMarket processing node - ONE downloader for every model this node can run.

Reads every manifest in downloads\\*.json (voice.json, video.json, ...) and fetches what is missing:
model files (resumable, size + sha256 verified), Hugging Face snapshots, code at a pinned commit, Python
packages into their own virtual environments, and Python itself when a manifest needs a version that is not
installed. Re-runnable: whatever is already complete is skipped; partial downloads continue where they stopped.
Nothing you put on this computer is ever deleted (a file that fails verification is renamed, not removed).

    Download-Models.bat                    everything (asks once before starting)
    Download-Models.bat --list             what would be downloaded, with sizes and what is already here
    Download-Models.bat --check            test every link (no download) and print reachability + total size
    Download-Models.bat --only voice       one group (or package / item id); comma separated, repeatable
    Download-Models.bat --skip acestep     leave out a package or item id
    Download-Models.bat --all              also the optional packages (4-step video LoRA, fast video model)
    Download-Models.bat --status           what is installed / missing per package, as JSON (no network)

Nothing is downloaded twice: a model ComfyUI can already load (its models\\ folder, the folders in
extra_model_paths.yaml, ComfyUI Desktop's own folder) counts as installed; a file two items share is fetched once
and linked; all virtual environments share one pip cache (pip-cache\\). The agent (agent.py) runs this in the
background and shows the progress in the panel (--status-file); only one run at a time (logs\\download.lock).
    Download-Models.bat --hf-mirror https://hf-mirror.com     Hugging Face mirror (also: HF_ENDPOINT)
    Download-Models.bat --pip-mirror https://mirror-pypi.runflare.com/simple   extra pip index to try
    Download-Models.bat --yes              do not ask before starting

Python 3.10+ standard library only. Console text is English on purpose (the Windows console garbles Persian).
Log: logs\\download-models.log
"""
import argparse
import fnmatch
import glob
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION = "1.1"
HERE = os.path.dirname(os.path.abspath(__file__))
NM_HOME = os.environ.get("NM_HOME") or HERE
MANIFEST_DIR = os.path.join(NM_HOME, "downloads")
LOGS = os.path.join(NM_HOME, "logs")
LOG_PATH = os.path.join(LOGS, "download-models.log")
STATE_PATH = os.path.join(LOGS, "download-state.json")
LOCAL_CFG = os.path.join(NM_HOME, "downloads-local.json")
CACHE_DIR = os.path.join(NM_HOME, "downloads-cache")
HF_DEFAULT = "https://huggingface.co"
HF_FALLBACK = "https://hf-mirror.com"
CODELOAD = "https://codeload.github.com"
UA = "UpMarket-node-downloader/%s (+python %s)" % (VERSION, sys.version.split()[0])
IS_WIN = sys.platform.startswith("win")
KIND_ORDER = {"python": 0, "git": 1, "file": 2, "hf_snapshot": 2, "pip": 3}
SAFETY_MARGIN = 2 * 1024 ** 3


# ───────────────────────────────────────────── output

class Log:
    fh = None

    @classmethod
    def open(cls):
        try:
            os.makedirs(LOGS, exist_ok=True)
            cls.fh = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
            cls.fh.write("\n===== %s download_models %s =====\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), VERSION))
        except OSError:
            cls.fh = None

    @classmethod
    def write(cls, line):
        if cls.fh:
            try:
                cls.fh.write("%s  %s\n" % (time.strftime("%H:%M:%S"), line))
                cls.fh.flush()
            except OSError:
                pass


def say(msg=""):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
    Log.write(msg)


def human(n):
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return ("%.0f %s" if unit in ("B", "KB") else "%.2f %s") % (n, unit)
        n /= 1024.0
    return "%.2f TB" % n


class Progress:
    def __init__(self, label, total, start=0):
        self.label, self.total, self.done = label, total, start
        self.t0, self.last, self.base = time.time(), 0.0, start
        self.tty = sys.stdout.isatty()

    def add(self, n):
        self.done += n
        STATUS.progress(self.done, self.total)
        now = time.time()
        if now - self.last >= (0.5 if self.tty else 15):
            self.last = now
            self.show()

    def show(self, end=False):
        speed = (self.done - self.base) / max(0.001, time.time() - self.t0)
        if self.total:
            pct = 100.0 * self.done / self.total
            eta = (self.total - self.done) / speed if speed > 0 else 0
            text = "  %5.1f%%  %s / %s  %s/s  ETA %dm%02ds" % (pct, human(self.done), human(self.total), human(speed),
                                                                eta // 60, eta % 60)
        else:
            text = "  %s  %s/s" % (human(self.done), human(speed))
        if self.tty:
            sys.stdout.write("\r" + text.ljust(78) + ("\n" if end else ""))
            sys.stdout.flush()
        else:
            print(text, flush=True)


# ───────────────────────────────────────────── live status (for the agent and the panel)

class Status:
    """--status-file: what this run is doing, rewritten every few seconds (the agent sends it to the panel)."""

    def __init__(self):
        self.path = None
        self.data = {}
        self.last = 0.0
        self.base = 0

    def start(self, path, packages, items_total, bytes_total):
        self.path = path
        self.data = {"state": "running", "pid": os.getpid(), "started": time.time(), "packages": packages,
                     "items_total": items_total, "items_done": 0, "bytes_total": bytes_total, "bytes_done": 0,
                     "current": None, "failed": [], "message": ""}
        self.write(force=True)

    def item(self, item, total):
        if not self.path:
            return
        self.data["current"] = {"id": item["id"], "package": item.get("package") or "", "kind": item["kind"],
                                "title": item.get("title") or "", "done": 0, "total": total}
        self.base = self.data["bytes_done"]
        self.write(force=True)

    def progress(self, done, total):
        if not self.path or not self.data.get("current"):
            return
        cur = self.data["current"]
        delta = max(0, done - cur.get("done", 0)) if cur.get("total") == total else 0
        cur["done"], cur["total"] = done, total
        self.data["bytes_done"] += delta
        self.write()

    def item_done(self, item, status, reason=""):
        if not self.path:
            return
        self.data["items_done"] += 1
        if status == "FAILED":
            self.data["failed"].append({"id": item["id"], "package": item.get("package") or "", "reason": reason[:300]})
        self.data["current"] = None
        self.write(force=True)

    def finish(self, state, message=""):
        if not self.path:
            return
        self.data.update(state=state, message=message, current=None, finished=time.time())
        self.write(force=True)

    def write(self, force=False):
        if not self.path or (not force and time.time() - self.last < 2):
            return
        self.last = time.time()
        self.data["updated"] = self.last
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass


STATUS = Status()


def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if IS_WIN:
        import ctypes

        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lock_path():
    return os.path.join(LOGS, "download.lock")


def take_lock():
    """One download at a time (the agent's background run and a double-clicked Download-Models.bat)."""
    path = lock_path()
    try:
        other = json.load(open(path, encoding="utf-8")).get("pid")
    except (OSError, ValueError):
        other = None
    if other and int(other) != os.getpid() and pid_alive(other):
        return other
    os.makedirs(LOGS, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "since": time.time()}, fh)
    return None


def drop_lock():
    try:
        if json.load(open(lock_path(), encoding="utf-8")).get("pid") == os.getpid():
            os.remove(lock_path())
    except (OSError, ValueError):
        pass


def link_or_copy(src, dest):
    """The same file for a second item: a hard link (no extra disk) or, across drives, a copy."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


# ───────────────────────────────────────────── state (what was verified already)

class State:
    def __init__(self, path=None):
        self.path = path or STATE_PATH
        try:
            self.data = json.load(open(self.path, encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def verified(self, dest, size, sha):
        rec = self.data.get(os.path.normcase(os.path.abspath(dest)))
        try:
            st = os.stat(dest)
        except OSError:
            return False
        return bool(rec) and rec.get("size") == st.st_size == size and rec.get("mtime") == int(st.st_mtime) \
            and (not sha or rec.get("sha256") == sha)

    def mark(self, dest, sha):
        st = os.stat(dest)
        self.data[os.path.normcase(os.path.abspath(dest))] = {"size": st.st_size, "mtime": int(st.st_mtime),
                                                               "sha256": sha or ""}
        self.save()

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            json.dump(self.data, open(tmp, "w", encoding="utf-8"), indent=0)
            os.replace(tmp, self.path)
        except OSError:
            pass


# ───────────────────────────────────────────── errors

class Fail(Exception):
    """An item could not be completed. `hint` says what the owner can do about it."""

    def __init__(self, reason, hint=""):
        super().__init__(reason)
        self.reason, self.hint = reason, hint


class Unresolved(Fail):
    pass


# ───────────────────────────────────────────── local configuration + placeholders

def load_local():
    try:
        return json.load(open(LOCAL_CFG, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_local(data):
    try:
        json.dump(data, open(LOCAL_CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except OSError as e:
        say("WARNING: could not save %s: %s" % (LOCAL_CFG, e))


def python_version_of(exe, timeout=30):
    try:
        out = subprocess.run([exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2]);print(sys.executable)"],
                             capture_output=True, text=True, timeout=timeout)
        lines = out.stdout.strip().splitlines()
        if out.returncode == 0 and len(lines) >= 2:
            return lines[0].strip(), lines[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None, None


def wanted_versions(spec):
    """'3.12' / '3.10-3.12' / ['3.11', '3.12'] -> ['3.12', ...] best first."""
    if not spec:
        spec = "3.10-3.12"
    if isinstance(spec, (list, tuple)):
        vs = [str(v) for v in spec]
    elif "-" in str(spec):
        lo, hi = str(spec).split("-", 1)
        lo_minor, hi_minor = int(lo.split(".")[1]), int(hi.split(".")[1])
        vs = ["3.%d" % m for m in range(lo_minor, hi_minor + 1)]
    else:
        vs = [str(spec)]
    return sorted(set(vs), key=lambda v: -int(v.split(".")[1]))


def find_python(spec):
    """A real (non Store-stub) Python of one of the wanted versions -> path or None."""
    versions = wanted_versions(spec)
    cands = []
    for v in versions:
        tag = v.replace(".", "")
        cands.append(os.path.join(NM_HOME, "python%s" % tag, "python.exe" if IS_WIN else "bin/python3"))
        if IS_WIN:
            local = os.environ.get("LOCALAPPDATA", "")
            cands += [os.path.join(local, "Programs", "Python", "Python%s" % tag, "python.exe"),
                      os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Python%s" % tag, "python.exe"),
                      r"C:\Python%s\python.exe" % tag]
        else:
            cands += ["/usr/bin/python%s" % v, "/usr/local/bin/python%s" % v]
    if IS_WIN and shutil.which("py"):
        for v in versions:
            try:
                out = subprocess.run(["py", "-%s" % v, "-c", "import sys;print(sys.executable)"], capture_output=True,
                                     text=True, timeout=30)
                if out.returncode == 0 and out.stdout.strip():
                    cands.append(out.stdout.strip().splitlines()[-1])
            except (OSError, subprocess.SubprocessError):
                pass
    for name in ["python%s" % v for v in versions] + ["python3", "python"]:
        p = shutil.which(name)
        if p:
            cands.append(p)
    seen = set()
    for c in cands:
        if not c or c in seen or not os.path.isfile(c) or "WindowsApps" in c:
            continue
        seen.add(c)
        ver, exe = python_version_of(c)
        if ver in versions:
            return exe or c
    return None


class Context:
    """Expands {NM_HOME} {MODELS} {HF} {SITE} {COMFYUI} {COMFYUI_PYTHON} {VENV:name} - lazily, so a voice-only run
    never asks where ComfyUI is."""

    def __init__(self, hf=None, interactive=True, check=False):
        self.hf = (hf or os.environ.get("HF_ENDPOINT") or HF_DEFAULT).rstrip("/")
        self.interactive = interactive and sys.stdin is not None and sys.stdin.isatty()
        self.check = check
        self.local = load_local()
        self._comfy = None
        self._comfy_index = None
        #: sha256 -> a complete, verified file this run already has (so a second item links it)
        self.known = {}

    # ---- simple ones
    def site(self):
        for name in ("node.json", "site.json"):
            try:
                v = json.load(open(os.path.join(NM_HOME, name), encoding="utf-8")).get("site")
                if v:
                    return v.rstrip("/")
            except (OSError, ValueError):
                pass
        v = os.environ.get("NM_SITE", "").rstrip("/")
        if v:
            return v
        raise Unresolved("{SITE}: no site URL in node.json / site.json", "run START.bat once so the node knows its site")

    def hf_endpoints(self):
        out = [self.hf]
        if self.hf.rstrip("/") != HF_FALLBACK:
            out.append(HF_FALLBACK)
        if self.hf.rstrip("/") != HF_DEFAULT and HF_DEFAULT not in out:
            out.insert(1, HF_DEFAULT)
        return out

    # ---- ComfyUI
    def _ask(self, question, key, validate):
        if not self.interactive or self.check:
            return None
        for _ in range(3):
            try:
                ans = input(question).strip().strip('"')
            except EOFError:
                return None
            if not ans:
                return None
            if validate(ans):
                self.local[key] = ans
                save_local(self.local)
                return ans
            say("  not valid: %s" % ans)
        return None

    @staticmethod
    def _is_comfy(root):
        return bool(root) and os.path.isdir(os.path.join(root, "custom_nodes"))

    def comfyui(self):
        if self._comfy:
            return self._comfy
        cands = [os.environ.get("NM_COMFY_DIR", ""), self.local.get("comfyui", "")]
        bat = os.environ.get("NM_COMFY_BAT", "")
        if not bat:
            try:
                bat = (json.load(open(os.path.join(NM_HOME, "services.json"), encoding="utf-8")).get("comfyui") or {}).get("start") or ""
            except (OSError, ValueError):
                bat = ""
        bat = bat.strip()
        if bat.startswith('"'):
            bat = bat[1:].split('"', 1)[0]
        if bat and "${" not in bat:
            base = os.path.dirname(bat)
            if bat.lower().endswith("comfyui.exe"):
                try:
                    cfgp = os.path.join(os.environ.get("APPDATA", ""), "ComfyUI", "config.json")
                    cands.append(json.load(open(cfgp, encoding="utf-8")).get("basePath", ""))
                except (OSError, ValueError):
                    pass
            cands += [os.path.join(base, "ComfyUI"), base]
        for c in cands:
            c = (c or "").strip().strip('"')
            if self._is_comfy(c):
                self._comfy = os.path.abspath(c)
                return self._comfy
        got = self._ask("ComfyUI folder (the one that contains 'custom_nodes'): ", "comfyui", self._is_comfy)
        if got:
            self._comfy = os.path.abspath(got)
            return self._comfy
        raise Unresolved("{COMFYUI}: ComfyUI folder not found",
                         "set NM_COMFY_DIR to your ComfyUI folder (the one with custom_nodes) or run this once in a console window")

    def comfy_model_roots(self):
        """Every folder ComfyUI loads models from: its models\\, the folders in extra_model_paths.yaml (portable /
        manual install) and in ComfyUI Desktop's extra_models_config.yaml, and Desktop's own basePath\\models."""
        roots, yamls = [], []
        try:
            comfy = self.comfyui()
        except Unresolved:
            comfy = None
        if comfy:
            roots.append(os.path.join(comfy, "models"))
            yamls.append(os.path.join(comfy, "extra_model_paths.yaml"))
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            yamls.append(os.path.join(appdata, "ComfyUI", "extra_models_config.yaml"))
            try:
                base = json.load(open(os.path.join(appdata, "ComfyUI", "config.json"), encoding="utf-8")).get("basePath")
            except (OSError, ValueError):
                base = None
            if base:
                roots.append(os.path.join(base, "models"))
        for y in yamls:
            roots += parse_extra_model_paths(y)
        seen, out = set(), []
        for r in roots:
            key = os.path.normcase(os.path.abspath(r))
            if key not in seen and os.path.isdir(r):
                seen.add(key)
                out.append(r)
        return out

    def comfy_has(self, item):
        """A model file ComfyUI already has under ANY models\\ subfolder (unet or diffusion_models, a subfolder of
        its own, another name of the same folder) counts as installed: ComfyUI finds it by its file name, so it is
        never downloaded a second time. Returns that path or None."""
        dest = item.get("dest") or ""
        if item.get("kind") != "file" or not dest.startswith("{COMFYUI}") or "models" not in dest.replace("/", "\\").split("\\"):
            return None
        if self._comfy_index is None:
            self._comfy_index = {}
            for root in self.comfy_model_roots():
                for d, _dirs, files in os.walk(root, followlinks=True):
                    for f in files:
                        p = os.path.join(d, f)
                        try:
                            if os.path.getsize(p) > 0:
                                self._comfy_index.setdefault(f.lower(), p)
                        except OSError:
                            pass
        name = dest.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        return self._comfy_index.get(name)

    def comfyui_python(self):
        if self.local.get("comfyui_python") and os.path.isfile(self.local["comfyui_python"]):
            return self.local["comfyui_python"]
        root = self.comfyui()
        sub = ("Scripts", "python.exe") if IS_WIN else ("bin", "python")
        cands = [os.path.join(os.path.dirname(root), "python_embeded", "python.exe"),
                 os.path.join(root, "python_embeded", "python.exe"),
                 os.path.join(root, "venv", *sub), os.path.join(root, ".venv", *sub)]
        for c in cands:
            if os.path.isfile(c):
                return c
        got = self._ask("ComfyUI's python.exe (python_embeded\\python.exe or its venv): ", "comfyui_python", os.path.isfile)
        if got:
            return got
        raise Unresolved("{COMFYUI_PYTHON}: ComfyUI's own python was not found",
                         "put its path in %s as \"comfyui_python\"" % os.path.basename(LOCAL_CFG))

    # ---- expansion
    def venv_dir(self, name):
        return os.path.join(NM_HOME, "venvs", name)

    def expand(self, value):
        if not isinstance(value, str):
            return value
        out = value.replace("{NM_HOME}", NM_HOME).replace("{MODELS}", os.path.join(NM_HOME, "models"))
        if "{HF}" in out:
            out = out.replace("{HF}", self.hf)
        if "{SITE}" in out:
            out = out.replace("{SITE}", self.site())
        if "{COMFYUI_PYTHON}" in out:
            out = out.replace("{COMFYUI_PYTHON}", self.comfyui_python())
        if "{COMFYUI}" in out:
            out = out.replace("{COMFYUI}", self.comfyui())
        out = re.sub(r"\{VENV:([A-Za-z0-9_.-]+)\}", lambda m: self.venv_dir(m.group(1)), out)
        if not IS_WIN:
            out = out.replace("\\", "/")
        return out

    def url_variants(self, url):
        """A {HF} URL is tried on the configured endpoint first, then on the mirror (and the main site)."""
        if url.startswith("{HF}"):
            rest = url[len("{HF}"):]
            return [ep + rest for ep in self.hf_endpoints()]
        return [self.expand(url)]


# ───────────────────────────────────────────── HTTP

def parse_extra_model_paths(path):
    """The model folders listed in a ComfyUI extra_model_paths.yaml (no YAML library on the node):
    sections with base_path + "kind: folder" lines and multi-line "kind: |" lists. Relative paths are relative to
    base_path (or to the yaml's folder)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    sections, cur, block = [], None, None
    for raw in lines:
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        text = line.strip()
        if indent == 0:
            cur, block = {"base": None, "paths": []}, None
            sections.append(cur)
            continue
        if cur is None:
            continue
        if block is not None and indent > block:
            cur["paths"].append(text.strip("'\""))
            continue
        block = None
        key, sep, val = text.partition(":")
        if not sep:
            continue
        key, val = key.strip(), val.strip().strip("'\"")
        if key == "base_path":
            cur["base"] = val
        elif key in ("is_default", "download_model_base"):
            continue
        elif val in ("|", ">", "|-", ">-", "|+"):
            block = indent
        elif val:
            cur["paths"].append(val)
    here = os.path.dirname(os.path.abspath(path))
    out = []
    for sec in sections:
        base = os.path.expandvars(os.path.expanduser(sec["base"])) if sec["base"] else None
        if base and not os.path.isabs(base):
            base = os.path.join(here, base)
        for p in sec["paths"]:
            p = os.path.expandvars(os.path.expanduser(p))
            out.append(os.path.normpath(p if os.path.isabs(p) else os.path.join(base or here, p)))
    return out


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Python < 3.11 does not follow HTTP 308 (hf-mirror.com answers with it); treat it like 307."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, 307 if code == 308 else code, msg, headers, newurl)

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, code, msg, headers)


_OPENER = urllib.request.build_opener(_Redirects)


def request(url, method="GET", headers=None, timeout=60):
    h = {"User-Agent": UA}
    h.update(headers or {})
    return _OPENER.open(urllib.request.Request(url, headers=h, method=method), timeout=timeout)


def probe(url, timeout=30):
    """(ok, total_size_or_None, detail) using a 1-byte Range GET (works where HEAD is refused)."""
    try:
        with request(url, headers={"Range": "bytes=0-0"}, timeout=timeout) as r:
            total = None
            cr = r.headers.get("Content-Range") or ""
            if "/" in cr and cr.rsplit("/", 1)[1].strip().isdigit():
                total = int(cr.rsplit("/", 1)[1])
            elif r.status == 200 and (r.headers.get("Content-Length") or "").isdigit():
                total = int(r.headers["Content-Length"])
            return True, total, "HTTP %s" % r.status
    except urllib.error.HTTPError as e:
        if e.code == 416 and (e.headers.get("Content-Range") or "").strip().endswith("/0"):
            return True, 0, "HTTP 416 (empty file)"
        return False, None, "HTTP %s" % e.code
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return False, None, str(getattr(e, "reason", e))[:120]


def sha256_file(path, label=""):
    h = hashlib.sha256()
    size = os.path.getsize(path)
    prog = Progress(label, size) if size > 512 * 1024 ** 2 else None
    if prog:
        say("  verifying sha256 of %s (%s) ..." % (os.path.basename(path), human(size)))
    with open(path, "rb") as fh:
        while True:
            b = fh.read(4 << 20)
            if not b:
                break
            h.update(b)
            if prog:
                prog.add(len(b))
    if prog:
        prog.show(end=True)
    return h.hexdigest()


def _set_aside(path, why):
    """Never delete: a file that is not what the manifest says is renamed next to itself."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = "%s.%s-%s" % (path, why, stamp)
    os.replace(path, target)
    say("  kept the old file as %s" % os.path.basename(target))
    return target


class _WrongFile(Exception):
    pass


def fetch(urls, dest, size=None, sha256=None, label="", state=None, attempts=6):
    """Download to dest via dest.part, resuming with HTTP Range; tries every URL in turn. Raises Fail."""
    sha256 = (sha256 or "").lower() or None
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if os.path.isfile(dest):
        have = os.path.getsize(dest)
        if size is None or have == size:
            if not sha256 or (state and state.verified(dest, size, sha256)):
                return "skipped"
            if sha256_file(dest, label) == sha256:
                if state:
                    state.mark(dest, sha256)
                return "skipped"
            say("  %s is complete in size but its sha256 does not match" % os.path.basename(dest))
            _set_aside(dest, "bad")
        elif have < size and not os.path.exists(dest + ".part"):
            os.replace(dest, dest + ".part")          # an interrupted copy: continue it (sha256 decides at the end)
        else:
            _set_aside(dest, "old")
    part = dest + ".part"
    if size is None and os.path.exists(part):
        os.remove(part)                               # our own partial of a file of unknown size: start over
    complete = size == 0
    if complete:
        open(part, "wb").close()
    errors = []
    for url in urls:
        if complete:
            break
        for attempt in range(1, attempts + 1):
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if size is not None and have > size:
                open(part, "wb").close()
                have = 0
            if size is not None and have == size:
                complete = True
                break
            headers = {"Range": "bytes=%d-" % have} if have else {}
            try:
                with request(url, headers=headers, timeout=60) as r:
                    if have and r.status != 206:      # the server ignored Range: start over
                        have = 0
                    total = size
                    cr = r.headers.get("Content-Range") or ""
                    if "/" in cr and cr.rsplit("/", 1)[1].strip().isdigit():
                        total = int(cr.rsplit("/", 1)[1])
                    elif r.status == 200 and (r.headers.get("Content-Length") or "").isdigit():
                        total = int(r.headers["Content-Length"])
                    if size is not None and total is not None and total != size:
                        raise _WrongFile("%s: serves %s, the manifest says %s" % (_host(url), human(total), human(size)))
                    prog = Progress(label, total, have)
                    with open(part, "ab" if have else "wb") as fh:
                        while True:
                            b = r.read(1 << 20)
                            if not b:
                                break
                            fh.write(b)
                            prog.add(len(b))
                    prog.show(end=True)
                done = os.path.getsize(part)
                if size is None or done == size:
                    complete = True
                    break
                raise OSError("connection closed at %s of %s" % (human(done), human(size)))
            except _WrongFile as e:
                errors.append(str(e))
                break                                 # a different file there: try the next URL
            except urllib.error.HTTPError as e:
                if e.code == 416 and size is not None and have == size:
                    complete = True
                    break
                if e.code == 416:
                    open(part, "wb").close()
                errors.append("%s: HTTP %s" % (_host(url), e.code))
                if e.code in (401, 403, 404, 410):
                    break                             # this URL will not work; try the next one
            except (urllib.error.URLError, socket.timeout, OSError, http.client.HTTPException) as e:
                errors.append("%s: %s" % (_host(url), str(getattr(e, "reason", e))[:100]))
            if attempt < attempts:
                wait = min(60, 2 ** attempt)
                say("  retry %d/%d in %ds (%s)" % (attempt, attempts, wait, errors[-1] if errors else "?"))
                time.sleep(wait)
    if not complete:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        raise Fail("download incomplete (%s%s): %s" % (human(have), (" of %s" % human(size)) if size else "",
                                                       "; ".join(errors[-3:]) or "?"),
                   "run Download-Models.bat again (it continues where it stopped); behind a filter try "
                   "--hf-mirror https://hf-mirror.com or a VPN")
    if sha256:
        got = sha256_file(part, label)
        if got != sha256:
            bad = _set_aside(part, "bad")
            raise Fail("sha256 mismatch (got %s..., expected %s...); saved as %s" % (got[:12], sha256[:12],
                                                                                      os.path.basename(bad)),
                       "run again to download it once more")
    os.replace(part, dest)
    if state:
        state.mark(dest, sha256)
    return "downloaded"


def _host(url):
    try:
        return urllib.parse.urlparse(url).hostname or url[:40]
    except ValueError:
        return url[:40]


# ───────────────────────────────────────────── item handlers

def run_cmd(cmd, label="", env=None, cwd=None):
    """Run a command with its output on the console and in the log; returns the exit code."""
    say("  > %s" % " ".join('"%s"' % c if " " in str(c) else str(c) for c in cmd))
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=cwd,
                             text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        say("  could not start: %s" % e)
        return 127
    for line in p.stdout:
        line = line.rstrip()
        if line:
            say("    " + line[:300])
    return p.wait()


def same_key(item):
    return (item.get("sha256") or "").lower() or None


def do_file(item, ctx, state):
    have = ctx.comfy_has(item)
    if have:
        say("  ComfyUI already has it: %s" % have)
        return "skipped"
    dest = ctx.expand(item["dest"])
    key = same_key(item)
    twin = ctx.known.get(key) if key else None
    if twin and os.path.normcase(os.path.abspath(twin)) != os.path.normcase(os.path.abspath(dest)) \
            and os.path.isfile(twin) and os.path.getsize(twin) == item.get("size") \
            and not (os.path.isfile(dest) and os.path.getsize(dest) == item.get("size")):
        link_or_copy(twin, dest)
        state.mark(dest, key)
        say("  same file as %s - linked, not downloaded again" % twin)
        return "linked"
    urls = []
    for u in item.get("urls") or ([item["url"]] if item.get("url") else []):
        urls += ctx.url_variants(u)
    urls = list(dict.fromkeys(urls))
    res = fetch(urls, dest, item.get("size"), item.get("sha256"), item["id"], state)
    if key:
        ctx.known[key] = dest
    return res


def hf_listing(ctx, repo, revision):
    errs = []
    for ep in ctx.hf_endpoints():
        url = "%s/api/models/%s/revision/%s?blobs=true" % (ep, repo, revision)
        try:
            with request(url, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            return ep, data
        except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
            errs.append("%s: %s" % (_host(url), str(getattr(e, "reason", e))[:80]))
    raise Fail("file list of %s@%s not reachable (%s)" % (repo, revision[:10], "; ".join(errs)),
               "check the internet connection or pass --hf-mirror https://hf-mirror.com")


def snapshot_files(item, ctx, state=None):
    key = "snapshot:%s@%s" % (item["repo"], item["revision"])
    cached = state.data.get(key) if state else None
    if cached:
        data = cached                                  # a pinned revision never changes: no need to ask again
    else:
        _ep, data = hf_listing(ctx, item["repo"], item["revision"])
        if state:
            state.data[key] = {"siblings": data.get("siblings") or []}
            state.save()
    pats = item.get("files") or ["*"]
    out = []
    for s in data.get("siblings") or []:
        path = s["rfilename"]
        if path == ".gitattributes" or not any(fnmatch.fnmatch(path, p) for p in pats):
            continue
        lfs = s.get("lfs") or {}
        out.append({"path": path, "size": int(lfs.get("size") or s.get("size") or 0) if (lfs or s.get("size") is not None) else None,
                    "sha256": lfs.get("sha256")})
    if not out:
        raise Fail("no file of %s matches %s" % (item["repo"], pats), "fix the 'files' patterns in the manifest")
    return out


def do_snapshot(item, ctx, state):
    dest = ctx.expand(item["dest"])
    results = []
    for f in snapshot_files(item, ctx, state):
        urls = ["%s/%s/resolve/%s/%s" % (ep, item["repo"], item["revision"], urllib.parse.quote(f["path"]))
                for ep in ctx.hf_endpoints()]
        results.append(fetch(urls, os.path.join(dest, *f["path"].split("/")), f["size"], f["sha256"],
                             "%s/%s" % (item["id"], f["path"]), state))
    return "downloaded" if "downloaded" in results else "skipped"


def _github(url):
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def do_git(item, ctx, state):
    dest = ctx.expand(item["dest"])
    ref = item["ref"]
    marker = os.path.join(dest, ".nm-ref")
    if os.path.isfile(marker) and open(marker, encoding="utf-8").read().strip() == ref:
        return "skipped"
    git = shutil.which("git")
    if os.path.isdir(os.path.join(dest, ".git")) and git:
        head = subprocess.run([git, "-C", dest, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head == ref:
            open(marker, "w", encoding="utf-8").write(ref)
            return "skipped"
        if run_cmd([git, "-C", dest, "fetch", "--depth", "1", "origin", ref]) == 0 and \
                run_cmd([git, "-C", dest, "checkout", "FETCH_HEAD"]) == 0:
            open(marker, "w", encoding="utf-8").write(ref)
            return "downloaded"
        raise Fail("%s is a git checkout that could not be moved to %s (local changes?)" % (dest, ref[:10]),
                   "commit or move your changes in that folder, or delete the folder yourself and run again")
    if os.path.isdir(dest) and os.listdir(dest) and not os.path.isfile(marker):
        raise Fail("%s exists and was not created by this downloader" % dest,
                   "move that folder away (nothing is deleted automatically) and run again")
    if git and not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".partial-git"
        if os.path.isdir(tmp):
            _set_aside(tmp, "old")
        ok = run_cmd([git, "init", "-q", tmp]) == 0 and run_cmd([git, "-C", tmp, "remote", "add", "origin", item["url"]]) == 0 \
            and run_cmd([git, "-C", tmp, "fetch", "--depth", "1", "origin", ref]) == 0 \
            and run_cmd([git, "-C", tmp, "checkout", "-q", "FETCH_HEAD"]) == 0
        if ok:
            os.replace(tmp, dest)
            open(marker, "w", encoding="utf-8").write(ref)
            return "downloaded"
        say("  git failed; trying the zip of that commit instead")
    owner, repo = _github(item["url"])
    zips = list(item.get("zip_urls") or [])
    if owner:
        zips.insert(0, "%s/%s/%s/zip/%s" % (CODELOAD, owner, repo, ref))
    if not zips:
        raise Fail("git is not installed and there is no zip URL for %s" % item["url"],
                   "install Git for Windows (https://git-scm.com) and run again")
    os.makedirs(CACHE_DIR, exist_ok=True)
    zpath = os.path.join(CACHE_DIR, "%s-%s.zip" % (repo or item["id"], ref[:12]))
    fetch(zips, zpath, None, item.get("zip_sha256"), item["id"] + " (zip)", None)
    try:
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            top = names[0].split("/", 1)[0] + "/" if names and all(n.startswith(names[0].split("/", 1)[0] + "/") for n in names) else ""
            os.makedirs(dest, exist_ok=True)
            for n in names:
                rel = n[len(top):] if top and n.startswith(top) else n
                if not rel or rel.endswith("/"):
                    continue
                target = os.path.abspath(os.path.join(dest, *rel.split("/")))
                if not target.startswith(os.path.abspath(dest)):
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(n) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    except zipfile.BadZipFile as e:
        _set_aside(zpath, "bad")
        raise Fail("the code archive is damaged: %s" % e, "run again")
    open(marker, "w", encoding="utf-8").write(ref)
    return "downloaded"


def do_python(item, ctx, state):
    version = str(item.get("version") or "3.12")
    found = find_python(version)
    if found:
        say("  Python %s found: %s" % (version, found))
        return "skipped"
    if not IS_WIN:
        raise Fail("Python %s is not installed" % version, "install python%s with your package manager" % version)
    os.makedirs(CACHE_DIR, exist_ok=True)
    urls = [ctx.expand(u) for u in item.get("urls") or [item.get("url")]]
    installer = os.path.join(CACHE_DIR, os.path.basename(urllib.parse.urlparse(urls[0]).path))
    fetch(urls, installer, item.get("size"), item.get("sha256"), item["id"], state)
    target = ctx.expand(item.get("dest") or "{NM_HOME}\\python%s" % version.replace(".", ""))
    say("  installing Python %s (per user, no PATH change) into %s ..." % (version, target))
    code = run_cmd([installer, "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0", "Include_test=0",
                    "Include_doc=0", "Include_tcltk=0", "Shortcuts=0", "AssociateFiles=0", "TargetDir=%s" % target])
    exe = os.path.join(target, "python.exe")
    if code != 0 or not os.path.isfile(exe):
        raise Fail("the Python installer ended with code %s" % code,
                   "run %s yourself (tick 'Add to PATH' is not needed), then run Download-Models.bat again" % installer)
    return "downloaded"


def pip_marker(item, py):
    spec = json.dumps({k: item.get(k) for k in ("packages", "requirements", "no_deps")}, sort_keys=True)
    key = hashlib.sha1(spec.encode()).hexdigest()[:16]
    root = os.path.dirname(os.path.dirname(py)) if os.path.basename(os.path.dirname(py)).lower() in ("scripts", "bin") \
        else os.path.dirname(py)
    return os.path.join(root, ".nm-pip-%s.json" % re.sub(r"[^A-Za-z0-9_.-]", "_", item["id"])), key


def resolve_python(item, ctx):
    """The interpreter pip runs in; a {VENV:name} is created on demand with a matching base Python."""
    raw = item.get("python") or "{VENV:%s}" % item["id"]
    m = re.fullmatch(r"\{VENV:([A-Za-z0-9_.-]+)\}", raw.strip())
    if not m:
        py = ctx.expand(raw)
        if not os.path.isfile(py):
            raise Fail("python not found: %s" % py, "fix 'python' in the manifest")
        return py
    venv = ctx.venv_dir(m.group(1))
    py = os.path.join(venv, "Scripts", "python.exe") if IS_WIN else os.path.join(venv, "bin", "python")
    if os.path.isfile(py):
        ver, _ = python_version_of(py)
        if ver in wanted_versions(item.get("python_version")):
            return py
        raise Fail("%s was made with Python %s, this item needs %s" % (venv, ver, item.get("python_version")),
                   "rename or remove that venv folder yourself, then run again")
    base = find_python(item.get("python_version"))
    if not base:
        raise Fail("no Python %s found to create %s" % (item.get("python_version") or "3.10-3.12", venv),
                   "let the 'python312' item install it (do not --skip python) or install Python %s from python.org"
                   % (item.get("python_version") or "3.12"))
    say("  creating virtual environment %s (Python from %s)" % (venv, base))
    if run_cmd([base, "-m", "venv", venv]) != 0 or not os.path.isfile(py):
        raise Fail("python -m venv failed for %s" % venv, "see the log above")
    run_cmd([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])
    return py


def pip_attempts(item, ctx, mirrors):
    """Index sets to try, official first: [(index_url, [extra_index...], [find_links...]), ...]"""
    indexes = list(item.get("index_urls") or ["https://pypi.org/simple"]) + list(mirrors)
    extra = list(item.get("extra_index_urls") or [])
    mextra = list(item.get("mirror_extra_index_urls") or []) + extra
    flinks = list(item.get("find_links_mirrors") or [])
    out = []
    for i, idx in enumerate(dict.fromkeys(indexes)):
        out.append((idx, extra if i == 0 else mextra, [] if i == 0 else flinks))
    return out


def do_pip(item, ctx, state, mirrors=()):
    py = resolve_python(item, ctx)
    marker, key = pip_marker(item, py)
    try:
        if json.load(open(marker, encoding="utf-8")).get("spec") == key:
            return "skipped"
    except (OSError, ValueError):
        pass
    args = []
    for r in item.get("requirements") or []:
        path = ctx.expand(r)
        if not os.path.isfile(path):
            raise Fail("requirements file missing: %s" % path, "the code item it belongs to has to succeed first")
        args += ["-r", path]
    args += [ctx.expand(p) for p in item.get("packages") or []]
    if not args:
        return "skipped"
    if item.get("no_deps"):
        args.insert(0, "--no-deps")
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONIOENCODING="utf-8",
               PIP_CACHE_DIR=os.path.join(NM_HOME, "pip-cache"))     # one cache: the same wheel is fetched once
    last = None
    for idx, extra, flinks in pip_attempts(item, ctx, mirrors):
        cmd = [py, "-m", "pip", "install", "--timeout", "60", "--retries", "5", "--progress-bar", "off",
               "--index-url", idx]
        for e in extra:
            cmd += ["--extra-index-url", e]
        for f in flinks:
            cmd += ["--find-links", f]
        say("  pip via %s%s" % (_host(idx), (" + " + ", ".join(_host(e) for e in extra)) if extra else ""))
        last = run_cmd(cmd + args, env=env)
        if last == 0:
            json.dump({"spec": key, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "index": idx},
                      open(marker, "w", encoding="utf-8"))
            return "downloaded"
        say("  pip failed with code %s; trying the next package index" % last)
    raise Fail("pip install failed on every index (last exit code %s)" % last,
               "see logs\\download-models.log; behind a filter add --pip-mirror <index url>")


HANDLERS = {"file": do_file, "hf_snapshot": do_snapshot, "git": do_git, "python": do_python, "pip": do_pip}


# ───────────────────────────────────────────── manifests

def load_manifests(directory=None):
    directory = directory or MANIFEST_DIR
    groups = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError) as e:
            say("WARNING: %s is not valid JSON (%s) - skipped" % (os.path.basename(path), e))
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
            say("WARNING: %s has no 'items' list - skipped" % os.path.basename(path))
            continue
        doc.setdefault("group", os.path.splitext(os.path.basename(path))[0])
        doc["_file"] = os.path.basename(path)
        bad = [i for i in doc["items"] if not isinstance(i, dict) or i.get("kind") not in HANDLERS or not i.get("id")]
        for i in bad:
            say("WARNING: %s: item %s has an unknown kind - skipped" % (doc["_file"], (i or {}).get("id") if isinstance(i, dict) else i))
        doc["items"] = [i for i in doc["items"] if i not in bad]
        groups.append(doc)
    return groups


def _tokens(values):
    out = []
    for v in values or []:
        out += [t.strip() for t in str(v).split(",") if t.strip()]
    return out


def selected(item, group, only, skip, everything=False):
    keys = {group, item.get("package") or "", item["id"]}

    def hit(tok):
        return tok in keys or item["id"].startswith(tok + ":") or item["id"].startswith(tok + "/")
    if any(hit(t) for t in skip):
        return False
    if item.get("optional") and not everything:
        # an optional item comes only when named by its package / id (a group name alone is not enough)
        named = {item.get("package") or "", item["id"]}
        return any(t in named or item["id"].startswith(t + ":") for t in only)
    return not only or any(hit(t) for t in only)


def plan(groups, only, skip, everything=False):
    rows = []
    for g in groups:
        for it in g["items"]:
            if selected(it, g["group"], only, skip, everything):
                rows.append((g, it))
    rows.sort(key=lambda r: KIND_ORDER.get(r[1]["kind"], 9))
    return rows


# ───────────────────────────────────────────── sizes, disk

def _existing_parent(path):
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def drive_of(path):
    p = os.path.abspath(path)
    if IS_WIN:
        return os.path.splitdrive(p)[0].upper() or p
    best = "/"
    for mount in sorted({m for m in _mounts()}, key=len):
        if p == mount or p.startswith(mount.rstrip("/") + "/"):
            best = mount
    return best


def _mounts():
    try:
        return [line.split()[1] for line in open("/proc/mounts") if line.startswith("/")] + ["/"]
    except OSError:
        return ["/"]


def remaining_bytes(item, ctx):
    """(download_bytes, disk_bytes, where) still needed for this item - best effort, never raises."""
    kind = item["kind"]
    try:
        if kind == "file":
            if ctx.comfy_has(item):
                return 0, 0, NM_HOME
            dest = ctx.expand(item["dest"])
            size = item.get("size") or 0
            if os.path.isfile(dest) and os.path.getsize(dest) == size:
                return 0, 0, dest
            have = os.path.getsize(dest + ".part") if os.path.exists(dest + ".part") else 0
            return max(0, size - have), max(0, size - have), dest
        if kind == "git":
            dest = ctx.expand(item["dest"])
            done = os.path.isfile(os.path.join(dest, ".nm-ref"))
            return (0, 0, dest) if done else (item.get("size") or 0, (item.get("size") or 0) * 2, dest)
        if kind == "python":
            if find_python(item.get("version")):
                return 0, 0, NM_HOME
            return item.get("size") or 0, 200 * 1024 ** 2, ctx.expand(item.get("dest") or NM_HOME)
        if kind == "pip":
            raw = item.get("python") or ""
            m = re.fullmatch(r"\{VENV:([A-Za-z0-9_.-]+)\}", raw.strip())
            where = ctx.venv_dir(m.group(1)) if m else NM_HOME
            py = os.path.join(where, "Scripts" if IS_WIN else "bin", "python.exe" if IS_WIN else "python")
            if m and os.path.isfile(py):
                marker, key = pip_marker(item, py)
                try:
                    if json.load(open(marker, encoding="utf-8")).get("spec") == key:
                        return 0, 0, where
                except (OSError, ValueError):
                    pass
            return (item.get("estimate_mb") or 0) * 1024 ** 2, (item.get("install_mb") or 0) * 1024 ** 2, where
        if kind == "hf_snapshot":
            return item.get("size") or 0, item.get("size") or 0, ctx.expand(item["dest"])
    except Unresolved:
        return item.get("size") or 0, item.get("size") or 0, NM_HOME
    return 0, 0, NM_HOME


def disk_report(rows, ctx):
    need, total_dl = {}, 0
    for _g, it in rows:
        if _no_comfy(it, ctx):
            continue
        dl, disk, where = remaining_bytes(it, ctx)
        total_dl += dl
        d = drive_of(where)
        need.setdefault(d, [0, where])
        need[d][0] += disk
        if it["kind"] == "pip" and dl:
            cache = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "pip")
            c = drive_of(cache)
            need.setdefault(c, [0, cache])
            need[c][0] += dl
    short = []
    for d, (bytes_needed, where) in sorted(need.items()):
        free = shutil.disk_usage(_existing_parent(where)).free
        ok = free - bytes_needed >= SAFETY_MARGIN
        say("  disk %-6s needs %10s   free %10s   %s" % (d, human(bytes_needed), human(free), "ok" if ok else "NOT ENOUGH"))
        if not ok:
            short.append((d, bytes_needed, free))
    return total_dl, short


# ───────────────────────────────────────────── --list / --check

def status_of(item, ctx):
    """'have' / 'have (ComfyUI)' / 'partial' / 'download' - what this computer still needs for the item."""
    if ctx.comfy_has(item):
        return "have (ComfyUI)"
    return _status_of(item, ctx)


def _no_comfy(item, ctx):
    """A ComfyUI model file on a computer where ComfyUI was not found: it is never downloaded anywhere."""
    if not str(item.get("dest") or "").startswith("{COMFYUI}"):
        return False
    try:
        ctx.comfyui()
        return False
    except Unresolved:
        return True


def _status_of(item, ctx):
    if _no_comfy(item, ctx):
        return "no ComfyUI"
    try:
        dl, _disk, _w = remaining_bytes(item, ctx)
    except Exception:  # noqa: BLE001
        return "?"
    if dl == 0:
        return "have"
    if item["kind"] == "file":
        try:
            dest = ctx.expand(item["dest"])
        except Unresolved:
            return "download"
        if os.path.exists(dest + ".part"):
            return "partial"
    return "download"


def package_status(groups, ctx):
    """Per package: how much is on this computer and how much would still be downloaded - offline and fast
    (sizes and markers only, no hashing). What the agent reports to the panel."""
    out = {}
    for g in groups:
        titles = g.get("packages") or {}
        for it in g["items"]:
            pk = it.get("package") or it["id"]
            row = out.setdefault(pk, {"group": g["group"], "title": titles.get(pk, ""), "optional": False, "items": 0,
                                      "missing": 0, "bytes_missing": 0, "bytes_total": 0, "have_in_comfyui": 0})
            row["optional"] = row["optional"] or bool(it.get("optional"))
            size = it.get("size") if it["kind"] != "pip" else (it.get("estimate_mb") or 0) * 1024 ** 2
            row["items"] += 1
            row["bytes_total"] += size or 0
            st = status_of(it, ctx)
            if st == "have (ComfyUI)":
                row["have_in_comfyui"] += 1
            elif st not in ("have",):
                row["missing"] += 1
                try:
                    dl, _d, _w = remaining_bytes(it, ctx)
                except Exception:  # noqa: BLE001
                    dl = size or 0
                row["bytes_missing"] += dl
    for row in out.values():
        row["installed"] = row["missing"] == 0
    return out


def cmd_list(groups, rows, ctx):
    total = 0
    for g in groups:
        mine = [it for gg, it in rows if gg is g]
        if not mine:
            continue
        say("")
        say("[%s] %s  (%s)" % (g["group"], g.get("title", ""), g["_file"]))
        if g.get("license_note"):
            say("  licence: %s" % g["license_note"])
        for it in mine:
            st = status_of(it, ctx)
            size = it.get("size") if it["kind"] != "pip" else (it.get("estimate_mb") or 0) * 1024 ** 2
            if not st.startswith("have") and st != "no ComfyUI":
                total += size or 0
            say("  %-15s %-11s %10s  %s" % ("already have" if st == "have" else "skip: no ComfyUI" if st == "no ComfyUI"
                                           else st if st != "download" else "will download",
                                           it["kind"], human(size) if size else "-", it["id"]))
        chosen = {id(it) for _g, it in rows}
        extra = [it for it in g["items"] if it.get("optional") and id(it) not in chosen]
        if extra:
            pk = sorted({it.get("package") or it["id"] for it in extra})
            sz = sum(it.get("size") or (it.get("estimate_mb") or 0) * 1024 ** 2 for it in extra)
            say("  optional, not downloaded unless asked (%s): --only %s" % (human(sz), ",".join(pk)))
    say("")
    say("Still to download: about %s" % human(total))


def marker_ok(marker, env):
    """Evaluates a requirement marker (sys_platform == 'win32' and python_version == '3.11' ...) for the node."""
    def comp(m):
        var, op, val = m.group(1), m.group(2), m.group(3)
        have = env.get(var, "")
        return str(have == val if op == "==" else have != val)
    expr = re.sub(r"(\w+)\s*(==|!=)\s*['\"]([^'\"]*)['\"]", comp, marker)
    if not re.fullmatch(r"[\s()]*((True|False|and|or|not)[\s()]*)+", expr):
        return True                                    # a marker we do not understand: check the package anyway
    try:
        return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - only True/False/and/or/not remain
    except SyntaxError:
        return True


def check_pip_item(item, ctx, mirrors):
    """Each index: reachable? Each pinned package: is that version listed?"""
    lines = []
    pkgs = list(item.get("packages") or [])
    for r in item.get("requirements") or []:
        try:
            path = ctx.expand(r)
        except Unresolved:
            path = None
        if path and os.path.isfile(path):
            env = {"sys_platform": "win32", "platform_machine": "AMD64", "platform_system": "Windows",
                   "python_version": wanted_versions(item.get("python_version"))[0]}
            for line in open(path, encoding="utf-8", errors="replace"):
                line = line.split("#", 1)[0].strip()
                if line and not line.startswith("-") and "@" not in line:
                    req, _sep, marker = line.partition(";")
                    if not marker or marker_ok(marker, env):
                        pkgs.append(req.strip())
        else:
            lines.append("    requirements %s: not downloaded yet (read after its code item)" % os.path.basename(r))
    reqs = []
    for p in pkgs:
        if os.sep in p or "\\" in p or "/" in p or p.startswith("{"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*(==\s*([^\s,;]+))?", p)
        if m:
            reqs.append((re.sub(r"\[.*\]", "", m.group(1)), m.group(3)))
    ok_all = True
    attempts = pip_attempts(item, ctx, mirrors)
    for idx, extra, flinks in attempts[:1] + attempts[1:]:
        sources = [idx] + list(extra)
        cache = {}
        missing = []
        for name, ver in reqs:
            norm = re.sub(r"[-_.]+", "-", name).lower()
            found = False
            reached = False
            for src in sources:
                key = (src, norm)
                if key not in cache:
                    try:
                        with request("%s/%s/" % (src.rstrip("/"), norm), timeout=40) as r:
                            cache[key] = r.read().decode("utf-8", "replace")
                    except urllib.error.HTTPError as e:
                        cache[key] = "" if e.code == 404 else None
                    except (urllib.error.URLError, socket.timeout, OSError):
                        cache[key] = None
                page = cache[key]
                if page is None:
                    continue
                reached = True
                if not ver:
                    found = found or bool(page)
                else:
                    v = ver.replace("+", "%2B")
                    found = found or ("-%s-" % ver in page or "-%s-" % v in page or "-%s.tar" % ver in page
                                      or "-%s.zip" % ver in page or ver.replace("+", "&#43;") in page)
            if not found:
                missing.append("%s%s%s" % (name, "==" if ver else "", ver or "") + ("" if reached else " (index unreachable)"))
        verdict = "all %d packages listed" % len(reqs) if not missing else "missing: %s" % ", ".join(missing[:6])
        lines.append("    %-40s %s" % (_host(idx) + ("+" + ",".join(_host(e) for e in extra) if extra else ""), verdict))
        if not missing:
            break
        ok_all = False
    return ok_all or not missing, lines


def cmd_check(groups, rows, ctx, mirrors):
    say("")
    say("Checking every source (nothing is downloaded) ...")
    total, bad = 0, 0
    hosts = {}
    for g, it in rows:
        kind = it["kind"]
        try:
            if kind == "file":
                urls = []
                for u in it.get("urls") or [it.get("url")]:
                    urls += ctx.url_variants(u)
                results = []
                for u in dict.fromkeys(urls):
                    ok, size, detail = probe(u)
                    results.append((u, ok, size, detail))
                    hosts.setdefault(_host(u), [0, 0])[0 if ok else 1] += 1
                good = [r for r in results if r[1]]
                size_ok = any(r[2] == it.get("size") for r in good) or it.get("size") is None
                total += it.get("size") or 0
                state = "OK  " if good and size_ok else "FAIL"
                if not (good and size_ok):
                    bad += 1
                say("%s %10s  %s  [%s]" % (state, human(it.get("size")), it["id"],
                                            ", ".join("%s %s%s" % (_host(u), "ok" if ok else detail,
                                                                   "" if not ok or sz == it.get("size") else " size %s" % human(sz))
                                                      for u, ok, sz, detail in results)))
            elif kind == "hf_snapshot":
                files = snapshot_files(it, ctx)
                size = sum(f["size"] or 0 for f in files)
                total += size
                say("OK   %10s  %s  [%d files listed]" % (human(size), it["id"], len(files)))
            elif kind == "git":
                owner, repo = _github(it["url"])
                url = "%s/%s/%s/zip/%s" % (CODELOAD, owner, repo, it["ref"]) if owner else it["url"]
                ok, _size, detail = probe("https://api.github.com/repos/%s/%s/commits/%s" % (owner, repo, it["ref"])) \
                    if owner else probe(url)
                ok2, _s2, d2 = probe(url)
                total += it.get("size") or 0
                if not (ok or ok2):
                    bad += 1
                say("%s %10s  %s  [commit %s: %s, zip: %s]" % ("OK  " if ok or ok2 else "FAIL", human(it.get("size")),
                                                             it["id"], it["ref"][:10], "ok" if ok else detail,
                                                             "ok" if ok2 else d2))
            elif kind == "python":
                urls = [ctx.expand(u) for u in it.get("urls") or [it.get("url")]]
                ok, size, detail = probe(urls[0])
                total += it.get("size") or 0
                have = find_python(it.get("version"))
                if not ok and not have:
                    bad += 1
                say("%s %10s  %s  [%s; %s]" % ("OK  " if ok or have else "FAIL", human(it.get("size")), it["id"],
                                               "installer reachable" if ok else detail,
                                               ("already installed: " + have) if have else "not installed here"))
            elif kind == "pip":
                ok, lines = check_pip_item(it, ctx, mirrors)
                total += (it.get("estimate_mb") or 0) * 1024 ** 2
                if not ok:
                    bad += 1
                say("%s %10s  %s  [pip, %s]" % ("OK  " if ok else "FAIL", human((it.get("estimate_mb") or 0) * 1024 ** 2),
                                                it["id"], it.get("python")))
                for line in lines:
                    say(line)
        except Unresolved as e:
            say("SKIP %10s  %s  [%s - %s]" % (human(it.get("size")), it["id"], e.reason, e.hint))
        except Fail as e:
            bad += 1
            say("FAIL %10s  %s  [%s]" % (human(it.get("size")), it["id"], e.reason))
    say("")
    for h, (ok, ko) in sorted(hosts.items()):
        say("  host %-28s reachable for %d file(s)%s" % (h, ok, (", failed for %d" % ko) if ko else ""))
    say("Total to download (everything listed): %s; problems: %d" % (human(total), bad))
    return bad


# ───────────────────────────────────────────── main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Download every model listed in downloads\\*.json")
    ap.add_argument("--list", action="store_true", help="show what would be downloaded")
    ap.add_argument("--check", action="store_true", help="test every link, download nothing")
    ap.add_argument("--only", action="append", default=[], help="group / package / item id (comma separated)")
    ap.add_argument("--skip", action="append", default=[], help="package / item id to leave out")
    ap.add_argument("--all", action="store_true", help="also the optional packages")
    ap.add_argument("--hf-mirror", default=None, help="Hugging Face endpoint, e.g. https://hf-mirror.com")
    ap.add_argument("--pip-mirror", action="append", default=[], help="extra pip index to try after the official ones")
    ap.add_argument("--yes", "-y", action="store_true", help="do not ask before starting")
    ap.add_argument("--force", action="store_true", help="start even when the disk check says there is not enough space")
    ap.add_argument("--status", action="store_true", help="JSON: installed / missing per package (no network)")
    ap.add_argument("--status-file", default=None, help="keep a JSON progress file up to date (used by the agent)")
    ap.add_argument("--manifests", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.status:
        groups = load_manifests(args.manifests)
        ctx = Context(hf=args.hf_mirror, interactive=False, check=True)
        try:
            other = json.load(open(lock_path(), encoding="utf-8")).get("pid")
        except (OSError, ValueError):
            other = None
        print(json.dumps({"version": VERSION, "packages": package_status(groups, ctx),
                          "running": bool(other and pid_alive(other))}))
        return 0
    Log.open()
    say("UpMarket model downloader %s - %s" % (VERSION, NM_HOME))
    groups = load_manifests(args.manifests)
    if not groups:
        say("No manifests in %s - nothing to do." % (args.manifests or MANIFEST_DIR))
        return 1
    only, skip = _tokens(args.only), _tokens(args.skip)
    rows = plan(groups, only, skip, args.all)
    say("Manifests: %s" % ", ".join("%s (%d items)" % (g["_file"], len(g["items"])) for g in groups))
    if not rows:
        say("Nothing selected (check --only / --skip).")
        return 1
    ctx = Context(hf=args.hf_mirror, interactive=not args.yes, check=args.check)
    mirrors = [m.rstrip("/") for m in args.pip_mirror]
    if args.list:
        cmd_list(groups, rows, ctx)
        return 0
    if args.check:
        return 0 if cmd_check(groups, rows, ctx, mirrors) == 0 else 2
    say("")
    say("Disk space:")
    total_dl, short = disk_report(rows, ctx)
    say("To download now: about %s (%d items selected)" % (human(total_dl), len(rows)))
    if short and not args.force:
        say("")
        say("NOT ENOUGH DISK SPACE on %s. Free some space (or use --skip <package>) and run again;" % ", ".join(d for d, _n, _f in short))
        say("--force starts anyway.")
        return 3
    if not args.yes and sys.stdin is not None and sys.stdin.isatty():
        try:
            if input("Start now? [Y/n] ").strip().lower() in ("n", "no"):
                return 0
        except EOFError:
            pass
    other = take_lock()
    if other:
        say("Another download is already running (process %s) - its progress is shown in the panel" % other)
        say("(Processing servers > voice models). Nothing was started twice.")
        return 4
    state = State()
    results = []
    t0 = time.time()
    for _g, it in rows:                       # files this computer already has, verified: a twin item links them
        if it["kind"] == "file" and same_key(it):
            try:
                dest = ctx.expand(it["dest"])
            except Unresolved:
                continue
            if state.verified(dest, it.get("size"), same_key(it)):
                ctx.known.setdefault(same_key(it), dest)
    if args.status_file:
        STATUS.start(args.status_file, sorted({it.get("package") or it["id"] for _g, it in rows}), len(rows), total_dl)
    try:
        for n, (g, it) in enumerate(rows, 1):
            say("")
            try:
                left, _disk, _w = remaining_bytes(it, ctx)
            except Exception:  # noqa: BLE001
                left = 0
            STATUS.item(it, left)
            say("[%d/%d] %s  (%s, %s)" % (n, len(rows), it["id"], g["group"], it["kind"]))
            if it.get("title") and (n == 1 or rows[n - 2][1].get("title") != it.get("title")):
                say("  %s" % it["title"])
            try:
                handler = HANDLERS[it["kind"]]
                res = handler(it, ctx, state, mirrors) if it["kind"] == "pip" else handler(it, ctx, state)
                results.append((it, "OK" if res in ("downloaded", "linked") else "SKIPPED",
                                "" if res in ("downloaded", "linked") else "already complete", ""))
                say("  %s" % {"downloaded": "done", "linked": "done (linked)"}.get(res, "already complete - skipped"))
                STATUS.item_done(it, "OK")
            except Fail as e:
                results.append((it, "FAILED", e.reason, e.hint))
                say("  FAILED: %s" % e.reason)
                if e.hint:
                    say("  what to do: %s" % e.hint)
                STATUS.item_done(it, "FAILED", e.reason)
            except Exception as e:  # noqa: BLE001 - one broken item must not stop the others
                results.append((it, "FAILED", "%s: %s" % (type(e).__name__, e), "see logs\\download-models.log"))
                say("  FAILED: %s: %s" % (type(e).__name__, e))
                STATUS.item_done(it, "FAILED", "%s: %s" % (type(e).__name__, e))
    except KeyboardInterrupt:
        say("")
        say("Stopped. Partial files are kept - run Download-Models.bat again to continue.")
        STATUS.finish("stopped", "stopped by the user")
        drop_lock()
        return 130
    finally:
        drop_lock()
    say("")
    say("=" * 78)
    say("Summary (%d min):" % ((time.time() - t0) // 60))
    counts = {"OK": 0, "SKIPPED": 0, "FAILED": 0}
    for it, status, reason, hint in results:
        counts[status] += 1
        if status == "FAILED":
            say("  FAILED   %s" % it["id"])
            say("           why : %s" % reason)
            if hint:
                say("           do  : %s" % hint)
    say("  OK (downloaded/installed): %d   skipped (already complete): %d   FAILED: %d" % (
        counts["OK"], counts["SKIPPED"], counts["FAILED"]))
    if counts["FAILED"]:
        say("Run Download-Models.bat again after fixing the above; finished items are not downloaded twice.")
    else:
        say("Everything is in place. Restart START.bat so the node reports the new models to the site.")
    say("Log: %s" % LOG_PATH)
    STATUS.finish("failed" if counts["FAILED"] else "done",
                  "%d failed" % counts["FAILED"] if counts["FAILED"] else "everything is in place")
    return 2 if counts["FAILED"] else 0


if __name__ == "__main__":
    sys.exit(main())
