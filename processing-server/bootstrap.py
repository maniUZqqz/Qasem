#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automatic, idempotent installation of everything a feature needs on the node (agent 2.11). Python 3.8+ stdlib only.

The owner's goal: update the GPU computer, switch it on - and everything works by itself. So nothing a feature needs is
installed by hand. Each feature drops ONE small declarative file into `requirements.d/<feature>.json` (it travels with the
code package, so the next update brings it); this module reads them all, checks what is already there and installs the rest in
the background while the node already takes jobs.

    {"feature": "gpu-runtime", "title_fa": "...", "order": 10, "needs_gpu": true, "platform": ["win"],
     "requires": ["other-feature"],              # installed after these
     "kinds": ["asr.transcribe"],                # job kinds that WAIT (stay in the site's queue) until the feature is ready
     "items": [ {"id": "venv", "type": "venv", "name": "nodert"},
                {"id": "pip", "type": "pip", "venv": "nodert", "packages": ["numpy==1.26.4", "onnxruntime-directml==1.20.1"]},
                {"id": "node", "type": "archive", "dest": "vendor/node", "check_file": "vendor/node/node.exe", "strip": 1,
                 "sources": [{"site": "node-win-x64.zip"}, {"url": "https://nodejs.org/dist/..."}], "sha256": "..."},
                {"id": "model", "type": "files", "dest": "models/x", "files": [{"path": "a.bin", "sources": [...], "sha256": ".."}]},
                {"id": "ffmpeg", "type": "ffmpeg-nvenc"},
                {"id": "verify", "type": "cmd", "check": [...python args...]} ] }

Item types: venv, pip (pinned; PyPI first, mirrors after), archive (zip from the site mirror first, then public mirrors; sha256
checked), files (single files, hf-mirror.com before huggingface.co), ffmpeg-nvenc (an ffmpeg with a working NVENC encoder),
ort-gpu (onnxruntime inside a venv offers a GPU provider), cmd (any check/install command lines).

State lives in <data>/bootstrap-state.json; `status()` is what the heartbeat reports (progress, errors, the tail of the install
log) and what the panel shows with a retry button. A failed item is retried by itself after 10 / 30 / 90 / 240 minutes (a
dropped line fixes itself); `retry()` is the panel button. Big items obey the site's download window; the rest never wait.
"""
import collections
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = "bootstrap-state.json"
RETRY_AFTER_S = (600, 1800, 5400, 14400)
# checked from Iran (2026-11-12): pypi.org itself answers, and the Iranian mirror (0.2 s) and aliyun (3 s) serve the same wheels.
# The official index goes first whenever it answers (nothing but the pinned names / versions is trusted from a third-party mirror
# unless pypi.org is unreachable from this computer); then the mirrors, fastest first.
PYPI_INDEXES = ("https://pypi.org/simple", "https://mirror-pypi.runflare.com/simple", "https://mirrors.aliyun.com/pypi/simple")
HF_HOSTS = ("https://hf-mirror.com", "https://huggingface.co")
TAIL_LINES = 14
BIG_BYTES = 200 << 20


class BootstrapError(Exception):
    pass


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_req(req):
    """'numpy==1.26.4' -> ('numpy', '==', '1.26.4'); 'pkg>=2' -> ('pkg', '>=', '2'); 'pkg' -> ('pkg', '', '')."""
    m = re.match(r"^\s*([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(==|>=|<=|~=|!=|<|>)?\s*([A-Za-z0-9_.+!*\-]*)", req)
    if not m:
        raise BootstrapError("cannot read requirement %r" % req)
    return norm(m.group(1)), m.group(3) or "", m.group(4) or ""


def _vkey(v):
    parts = []
    for p in re.split(r"[.+\-]", v):
        parts.append((0, int(p)) if p.isdigit() else (-1, 0))
    return parts


def satisfied(installed, op, wanted):
    if installed is None:
        return False
    if not op or not wanted:
        return True
    if op == "==":
        return installed.split("+")[0] == wanted.split("+")[0] or installed == wanted
    a, b = _vkey(installed.split("+")[0]), _vkey(wanted.split("+")[0])
    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b, "~=": a >= b, "!=": a != b}.get(op, False)


class Ctx:
    """What an installer step may use; tests replace `run` / `fetch`."""

    def __init__(self, data, agent=None, run=None, fetch=None, site=None, token="", download_allowed=None, say=None,
                 py=None, gpu_present=None, plat=None):
        self.data = data
        self.agent = agent
        self.site = (site or "").rstrip("/")
        self.token = token
        self.py = py or sys.executable
        self.download_allowed = download_allowed or (lambda: True)
        self.say = say or (lambda msg, frac=None: None)
        self._run = run
        self._fetch = fetch
        self.gpu_present = gpu_present if gpu_present is not None else self._has_gpu()
        self.plat = plat or ("win" if sys.platform.startswith("win") else "linux")

    @staticmethod
    def _has_gpu():
        import shutil
        return bool(shutil.which("nvidia-smi"))

    def path(self, *parts):
        return os.path.join(self.data, *parts)

    def venv_dir(self, name):
        return self.path("venvs", name)

    def venv_python(self, name):
        for rel in (("Scripts", "python.exe"), ("bin", "python")):
            p = os.path.join(self.venv_dir(name), *rel)
            if os.path.isfile(p):
                return p
        return ""

    def run(self, cmd, timeout=600, env=None, on_line=None, stall_s=None):
        """Run a command, stream its output to on_line; returns (returncode, tail_text)."""
        if self._run is not None:
            return self._run(cmd, timeout=timeout, env=env, on_line=on_line)
        env2 = dict(os.environ)
        env2.update(env or {})
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env2,
                             universal_newlines=True, encoding="utf-8", errors="replace")
        tail = collections.deque(maxlen=60)
        last_out = [time.time()]

        def reader():
            for line in p.stdout:
                line = line.rstrip()
                if line:
                    tail.append(line)
                    last_out[0] = time.time()
                    if on_line:
                        on_line(line)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t0 = time.time()
        while p.poll() is None:
            time.sleep(1.0)
            if time.time() - t0 > timeout:
                p.kill()
                tail.append("(killed: time limit %ds)" % timeout)
                break
            if stall_s and time.time() - last_out[0] > stall_s:
                p.kill()
                tail.append("(killed: no output for %d s)" % stall_s)
                break
        t.join(timeout=5)
        return (p.returncode if p.returncode is not None else -9), "\n".join(tail)

    def fetch(self, url, dest, size=None, sha256=None, label=None):
        if self._fetch is not None:
            return self._fetch(url, dest, size=size, sha256=sha256, label=label)
        import nm_fetch
        if self.site and url.startswith(self.site + "/3d/files/downloads/") and not (size and sha256):
            s2, h2 = nm_fetch.site_file_info(self.site, self.token, url.rsplit("/", 1)[1])      # what the site itself says it holds
            size, sha256 = size or s2, sha256 or h2
        nm_fetch.fetch_with_progress(url, dest, out=lambda m: self.say(str(m).strip()[:120]), every=15.0,
                                     size=size, sha256=sha256, stall=int(os.environ.get("NM_STALL_S") or 900), label=label)
        return dest


# ───────────────────────────────────────────── item types: each has check(ctx, item) -> (ok, detail) and install(ctx, item)

def _venv_check(ctx, item):
    py = ctx.venv_python(item["name"])
    return bool(py), py or "venv %s is not created" % item["name"]


def _venv_install(ctx, item):
    d = ctx.venv_dir(item["name"])
    os.makedirs(os.path.dirname(d), exist_ok=True)
    ctx.say("creating the Python environment %s" % item["name"], 0.2)
    rc, tail = ctx.run([ctx.py, "-m", "venv", d], timeout=300)
    if rc != 0 or not ctx.venv_python(item["name"]):
        raise BootstrapError("venv creation failed: %s" % tail[-300:])


DIST_PROBE = (
    "import json,sys\n"
    "try:\n"
    " from importlib import metadata as m\n"
    "except ImportError:\n"
    " import importlib_metadata as m\n"
    "want=json.loads(sys.argv[1]); out={}\n"
    "for n in want:\n"
    " try: out[n]=m.version(n)\n"
    " except Exception: out[n]=None\n"
    "print(json.dumps(out))\n"
)


def installed_versions(ctx, py, names):
    rc, tail = ctx.run([py, "-I", "-c", DIST_PROBE, json.dumps(list(names))], timeout=120)
    for line in reversed(tail.splitlines()):
        if line.startswith("{"):
            try:
                return {norm(k): v for k, v in json.loads(line).items()}
            except ValueError:
                break
    return {}


def _pip_check(ctx, item):
    py = ctx.venv_python(item["venv"]) if item.get("venv") else ctx.py
    if not py:
        return False, "venv %s missing" % item.get("venv")
    reqs = [parse_req(r) for r in item["packages"]]
    have = installed_versions(ctx, py, [r[0] for r in reqs])
    missing = [("%s%s%s" % (n, op, v)) for n, op, v in reqs if not satisfied(have.get(n), op, v)]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, ", ".join("%s %s" % (n, have.get(n)) for n, _, _ in reqs)


def index_order(ctx, indexes=PYPI_INDEXES, timeout=6.0):
    """pypi.org first when it answers from this computer (a quick HEAD), otherwise the mirrors first and pypi.org last. Tests that fake
    the command runner / downloader keep the declared order."""
    if ctx._run is not None or ctx._fetch is not None:
        return list(indexes)
    try:
        import urllib.request
        req = urllib.request.Request(indexes[0].rstrip("/") + "/pip/", method="HEAD", headers={"User-Agent": "nm-node-bootstrap"})
        urllib.request.urlopen(req, timeout=timeout).close()
        return list(indexes)
    except Exception:  # noqa: BLE001 - blocked / slow: the mirrors carry the same pinned wheels
        return list(indexes[1:]) + [indexes[0]]


def _pip_install(ctx, item):
    py = ctx.venv_python(item["venv"]) if item.get("venv") else ctx.py
    if not py:
        raise BootstrapError("venv %s is missing" % item.get("venv"))
    if item.get("big") and not ctx.download_allowed():            # e.g. the CUDA wheels (~1 GB): obey the site's download window
        raise BootstrapError("WAIT: waiting for the download window")
    cache = ctx.path("pip-cache")
    os.makedirs(cache, exist_ok=True)
    env = {"PIP_CACHE_DIR": cache, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1", "PYTHONUTF8": "1",
           "PIP_DEFAULT_TIMEOUT": "60", "PIP_RETRIES": "5"}
    pkgs = list(item["packages"])
    seen = {"n": 0}
    last_err = ""
    for idx, index in enumerate(item.get("index_urls") or index_order(ctx)):
        cmd = [py, "-m", "pip", "install", "--prefer-binary", "--index-url", index] + [a for a in item.get("extra_args", [])]
        for fl in item.get("find_links", []):
            cmd += ["--find-links", fl]
        if item.get("no_deps"):
            cmd.append("--no-deps")
        cmd += pkgs

        def on_line(line):
            seen["n"] += 1
            if line.startswith(("Downloading", "Collecting", "Installing collected", "Successfully")):
                ctx.say("pip: " + line[:100], min(0.9, 0.2 + seen["n"] * 0.02))

        ctx.say("pip install from %s" % re.sub(r"^https?://", "", index).split("/")[0], 0.2)
        rc, tail = ctx.run(cmd, timeout=int(item.get("timeout_s") or 7200), env=env, on_line=on_line, stall_s=1800)
        if rc == 0:
            return
        last_err = tail[-500:]
        ctx.say("pip failed on %s, trying the next source" % index.split("/")[2], 0.2)
    raise BootstrapError("pip install failed on every source: %s" % last_err)


def _sha256_file(path, chunk=1 << 20):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def _source_urls(ctx, sources):
    urls = []
    for s in sources or []:
        if isinstance(s, str):
            urls.append(s)
        elif s.get("site") and ctx.site:
            urls.append("%s/3d/files/downloads/%s" % (ctx.site, s["site"]))
        elif s.get("url"):
            urls.append(s["url"])
        elif s.get("hf"):
            for host in HF_HOSTS:
                urls.append("%s/%s" % (host, s["hf"]))
    return urls


def _fetch_any(ctx, urls, dest, size=None, sha256=None, label=None):
    last = "no source"
    for u in urls:
        try:
            ctx.fetch(u, dest, size=size, sha256=sha256, label=label or os.path.basename(dest))
            return u
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (u.split("/")[2] if "//" in u else u, str(e)[:200])
            ctx.say("source failed (%s) - trying the next" % last[:100])
    raise BootstrapError("download failed from every source (%s)" % last)


def _marker(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _archive_check(ctx, item):
    dest = ctx.path(*item["dest"].split("/"))
    cf = item.get("check_file")
    if cf and not os.path.isfile(ctx.path(*cf.split("/"))):
        return False, "%s is missing" % cf
    mk = _marker(os.path.join(dest, ".nm-bootstrap.json"))
    if item.get("sha256") and mk.get("sha256") != item["sha256"].lower():
        return False, "installed archive differs from the pinned one"
    if not cf and not mk:
        return False, "not installed"
    return True, cf or item["dest"]


def _archive_install(ctx, item):
    if item.get("big", True) and not ctx.download_allowed():
        raise BootstrapError("WAIT: waiting for the download window")
    dest = ctx.path(*item["dest"].split("/"))
    os.makedirs(dest, exist_ok=True)
    tmp = ctx.path("work", "bootstrap-%s.zip" % item["id"])
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    urls = _source_urls(ctx, item.get("sources"))
    ctx.say("downloading %s" % os.path.basename(urls[0]) if urls else "no source", 0.1)
    used = _fetch_any(ctx, urls, tmp, size=item.get("size"), sha256=item.get("sha256"), label=item["id"])
    strip = int(item.get("strip") or 0)
    ctx.say("unpacking", 0.8)
    n = 0
    with zipfile.ZipFile(tmp) as z:
        for member in z.namelist():
            if member.endswith("/"):
                continue
            parts = member.split("/")[strip:]
            if not parts or any(p in ("", "..") for p in parts):
                continue
            target = os.path.join(dest, *parts)
            if os.path.isfile(target) and os.path.getsize(target) == z.getinfo(member).file_size and not item.get("overwrite"):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(member) as src, open(target, "wb") as dst:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    dst.write(b)
            n += 1
    sha = (item.get("sha256") or _sha256_file(tmp)).lower()
    with open(os.path.join(dest, ".nm-bootstrap.json"), "w", encoding="utf-8") as fh:
        json.dump({"sha256": sha, "source": used, "files": n, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
    try:
        os.remove(tmp)
    except OSError:
        pass


def _files_check(ctx, item):
    base = ctx.path(*item["dest"].split("/"))
    for f in item["files"]:
        p = os.path.join(base, *f["path"].split("/"))
        if not os.path.isfile(p):
            return False, "%s is missing" % f["path"]
        if f.get("size") and os.path.getsize(p) != int(f["size"]):
            return False, "%s has the wrong size" % f["path"]
    return True, item["dest"]


def _files_install(ctx, item):
    base = ctx.path(*item["dest"].split("/"))
    total = sum(int(f.get("size") or 0) for f in item["files"])
    if (item.get("big") or total >= BIG_BYTES) and not ctx.download_allowed():
        raise BootstrapError("WAIT: waiting for the download window")
    done = 0
    for f in item["files"]:
        p = os.path.join(base, *f["path"].split("/"))
        if os.path.isfile(p) and (not f.get("size") or os.path.getsize(p) == int(f["size"])):
            done += 1
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        ctx.say("downloading %s (%d/%d)" % (f["path"], done + 1, len(item["files"])), 0.1 + 0.8 * done / max(1, len(item["files"])))
        _fetch_any(ctx, _source_urls(ctx, f.get("sources")), p, size=f.get("size"), sha256=f.get("sha256"), label=f["path"])
        done += 1


def _ffmpeg_check(ctx, item):
    if not ctx.gpu_present:
        return True, "skipped: no NVIDIA GPU"
    import gpu
    ff, rep = gpu.best_ffmpeg(ctx.data)
    if ff and rep.get("nvenc_h264"):
        return True, "%s (NVENC works)" % ff
    return False, ("no ffmpeg found" if not ff else "ffmpeg %s has no working NVENC (%s)" % (ff, rep.get("nvenc_error") or "encoder missing"))


def _ffmpeg_install(ctx, item):
    sub = dict(item, type="archive", dest="tools/PersianAiKit", strip=1, big=True, id=item["id"],
               check_file="tools/PersianAiKit/Video/tools/ffmpeg/bin/ffmpeg.exe",
               sources=item.get("sources") or [{"site": item.get("from_site") or "kit-ffmpeg.zip"}])
    sub.pop("sha256", None)
    if not ctx.plat == "win":
        raise BootstrapError("the NVENC ffmpeg package is for Windows; install an ffmpeg with NVENC (e.g. from BtbN) on this computer")
    _archive_install(ctx, sub)
    ok, why = _ffmpeg_check(ctx, item)
    if not ok:
        raise BootstrapError("the ffmpeg of the site mirror was installed but NVENC still does not work: %s (is the NVIDIA driver "
                             "525+ installed?)" % why)


def _ort_check(ctx, item):
    py = ctx.venv_python(item["venv"])
    if not py:
        return False, "venv %s missing" % item["venv"]
    import gpu
    rep = gpu.ort_report(py, run=None if ctx._run is None else (lambda cmd, **kw: _Res(*ctx._run(cmd, timeout=90, env=None, on_line=None))))
    if rep.get("error"):
        return False, "onnxruntime does not import: %s" % rep["error"]
    prov = rep.get("providers") or []
    if ctx.gpu_present and not any(p in prov for p in ("CUDAExecutionProvider", "DmlExecutionProvider")):
        return False, "onnxruntime %s has no GPU provider (%s)" % (rep.get("ort"), ", ".join(prov))
    return True, "onnxruntime %s: %s" % (rep.get("ort"), ", ".join(p.replace("ExecutionProvider", "") for p in prov))


class _Res:
    def __init__(self, rc, text):
        self.returncode, self.stdout = rc, text


def _ort_install(ctx, item):
    raise BootstrapError("onnxruntime has no GPU provider: %s" % _ort_check(ctx, item)[1])


def _cmd_check(ctx, item):
    if not item.get("check"):
        return False, "no check"
    rc, tail = ctx.run(_expand(ctx, item["check"]), timeout=int(item.get("check_timeout_s") or 120))
    return rc == 0, tail[-200:]


def _cmd_install(ctx, item):
    if not item.get("install"):
        raise BootstrapError("nothing to install")
    rc, tail = ctx.run(_expand(ctx, item["install"]), timeout=int(item.get("timeout_s") or 3600), stall_s=1800)
    if rc != 0:
        raise BootstrapError("command failed: %s" % tail[-300:])


def _expand(ctx, cmd):
    out = []
    for a in cmd:
        a = a.replace("{DATA}", ctx.data).replace("{PY}", ctx.py).replace("{HERE}", HERE)
        a = re.sub(r"\{VENVPY:([A-Za-z0-9_-]+)\}", lambda m: ctx.venv_python(m.group(1)) or "python", a)
        out.append(a)
    return out


ITEM_TYPES = {
    "venv": (_venv_check, _venv_install),
    "pip": (_pip_check, _pip_install),
    "archive": (_archive_check, _archive_install),
    "files": (_files_check, _files_install),
    "ffmpeg-nvenc": (_ffmpeg_check, _ffmpeg_install),
    "ort-gpu": (_ort_check, _ort_install),
    "cmd": (_cmd_check, _cmd_install),
}


# ───────────────────────────────────────────── specs and the engine

def load_specs(folder):
    """(specs, errors): every requirements.d/*.json, sorted by `order`. A broken file is reported, never fatal."""
    specs, errors = [], []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                spec = json.load(fh)
            if not isinstance(spec, dict) or not spec.get("feature") or not isinstance(spec.get("items"), list):
                raise ValueError("needs 'feature' and 'items'")
            for it in spec["items"]:
                if it.get("type") not in ITEM_TYPES:
                    raise ValueError("unknown item type %r" % it.get("type"))
                it.setdefault("id", it["type"])
            spec["_file"] = os.path.basename(path)
            specs.append(spec)
        except (OSError, ValueError) as e:
            errors.append({"file": os.path.basename(path), "error": str(e)[:200]})
    specs.sort(key=lambda s: (int(s.get("order") or 100), s["feature"]))
    return specs, errors


def applicable(spec, ctx):
    if spec.get("needs_gpu") and not ctx.gpu_present:
        return False, "no NVIDIA GPU on this computer"
    plats = spec.get("platform")
    if plats and ctx.plat not in plats:
        return False, "not for this operating system"
    return True, ""


class Bootstrap:
    def __init__(self, ctx, specs_dir, state_path=None, clock=time.time, sleep=time.sleep):
        self.ctx = ctx
        self.specs_dir = specs_dir
        self.state_path = state_path or os.path.join(ctx.data, STATE_FILE)
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.RLock()
        self.state = self._load()
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
        self.thread = None
        self.running_item = None
        self.specs, self.spec_errors = load_specs(specs_dir)

    # ---- state
    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, ensure_ascii=False)
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    def item_state(self, feature, item_id):
        return self.state.setdefault(feature, {}).setdefault(item_id, {"state": "idle"})

    def _set(self, feature, item_id, **kw):
        with self.lock:
            st = self.item_state(feature, item_id)
            st.update(kw)
            st["at"] = self.clock()
            self._save()

    # ---- the work
    def reload(self):
        self.specs, self.spec_errors = load_specs(self.specs_dir)

    def feature_ready(self, feature):
        spec = next((s for s in self.specs if s["feature"] == feature), None)
        if not spec:
            return False
        ok, _ = applicable(spec, self.ctx)
        if not ok:
            return True
        return all(self.item_state(feature, it["id"]).get("state") in ("ready", "skipped") for it in spec["items"])

    def _due(self, st):
        """May a failed item be tried again now? (automatic retries back off; a manual retry clears `failed`)."""
        if st.get("state") != "failed":
            return True
        tries = int(st.get("tries") or 0)
        if tries > len(RETRY_AFTER_S):
            return False
        return self.clock() - st.get("at", 0) >= RETRY_AFTER_S[min(tries - 1, len(RETRY_AFTER_S) - 1)] if tries else True

    def process_item(self, spec, item):
        """check -> install -> check again. Returns True when the item is ready."""
        f, iid = spec["feature"], item["id"]
        check, install = ITEM_TYPES[item["type"]]
        st = self.item_state(f, iid)
        ctx = self.ctx

        def say(msg, frac=None):
            self._set(f, iid, state="installing", detail=str(msg)[:160],
                      **({"progress": round(frac * 20) / 20.0} if frac is not None else {}))

        ctx.say = say
        try:
            ok, detail = check(ctx, item)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, "check failed: %s" % e
        if ok:
            self._set(f, iid, state="ready", detail=str(detail)[:200], progress=1.0, error="", tail=[])
            return True
        if not self._due(st):
            return False
        self._set(f, iid, state="installing", detail="installing ...", progress=0.05, tries=int(st.get("tries") or 0),
                  error="", tail=[])
        self.running_item = (f, iid)
        try:
            install(ctx, item)
            ok, detail = check(ctx, item)
            if not ok:
                raise BootstrapError("installed, but the check still fails: %s" % detail)
        except BootstrapError as e:
            msg = str(e)
            if msg.startswith("WAIT:"):
                self._set(f, iid, state="waiting", detail=msg[5:].strip(), error="")
                return False
            self._fail(f, iid, st, msg)
            return False
        except Exception as e:  # noqa: BLE001
            self._fail(f, iid, st, "%s: %s" % (type(e).__name__, e))
            return False
        finally:
            self.running_item = None
        self._set(f, iid, state="ready", detail=str(detail)[:200], progress=1.0, error="", tail=[], tries=0)
        return True

    def _fail(self, f, iid, st, msg):
        tries = int(st.get("tries") or 0) + 1
        lines = [ln for ln in msg.splitlines() if ln.strip()][-TAIL_LINES:]
        self._set(f, iid, state="failed", error=lines[-1][:300] if lines else msg[:300], tail=lines, tries=tries,
                  detail="failed (try %d)" % tries)

    def run_once(self):
        """One pass over every feature in order. Returns how many items are not ready yet."""
        self.reload()
        pending = 0
        done_features = set()
        for spec in self.specs:
            f = spec["feature"]
            ok, why = applicable(spec, self.ctx)
            if not ok:
                for it in spec["items"]:
                    self._set(f, it["id"], state="skipped", detail=why)
                continue
            reqs = spec.get("requires") or []
            if any(r not in done_features and not self.feature_ready(r) for r in reqs):
                for it in spec["items"]:
                    if self.item_state(f, it["id"]).get("state") not in ("ready",):
                        self._set(f, it["id"], state="waiting", detail="waiting for: " + ", ".join(reqs))
                pending += 1
                continue
            blocked = False
            for it in spec["items"]:
                if blocked:
                    if self.item_state(f, it["id"]).get("state") != "ready":
                        self._set(f, it["id"], state="waiting", detail="waiting for the previous step")
                    pending += 1
                    continue
                if not self.process_item(spec, it):
                    blocked = True
                    pending += 1
            if not blocked:
                done_features.add(f)
        return pending

    def loop(self):
        while not self.stop_flag.is_set():
            try:
                pending = self.run_once()
            except Exception as e:  # noqa: BLE001 - the loop never dies
                pending = 1
                self.state.setdefault("_error", str(e)[:200])
            self.wake.wait(60 if pending else 1800)
            self.wake.clear()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.loop, daemon=True, name="bootstrap")
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        self.wake.set()

    def retry(self, feature=None):
        """The panel's retry button: failed items get a fresh try now (their counters reset)."""
        n = 0
        with self.lock:
            for f, items in self.state.items():
                if f.startswith("_") or (feature and f != feature) or not isinstance(items, dict):
                    continue
                for iid, st in items.items():
                    if isinstance(st, dict) and st.get("state") in ("failed", "waiting"):
                        st.update(state="idle", tries=0, error="")
                        n += 1
            self._save()
        self.wake.set()
        return n

    # ---- what the heartbeat and the panel read
    def status(self):
        feats, blocked, summary = {}, {}, collections.Counter()
        for spec in self.specs:
            f = spec["feature"]
            ok, why = applicable(spec, self.ctx)
            items = []
            states = []
            for it in spec["items"]:
                st = self.item_state(f, it["id"]) if ok else {"state": "skipped", "detail": why}
                states.append(st.get("state", "idle"))
                items.append({"id": it["id"], "type": it["type"], "title": it.get("title") or it["id"], "state": st.get("state", "idle"),
                              "progress": st.get("progress"), "detail": (st.get("detail") or "")[:160],
                              "error": (st.get("error") or "")[:300], "tail": (st.get("tail") or [])[-TAIL_LINES:],
                              "tries": st.get("tries", 0)})
            if not ok:
                fstate = "skipped"
            elif all(s in ("ready", "skipped") for s in states):
                fstate = "ready"
            elif "failed" in states:
                fstate = "failed"
            elif "installing" in states:
                fstate = "installing"
            else:
                fstate = "waiting"
            summary[fstate] += 1
            feats[f] = {"title": spec.get("title_fa") or spec.get("title") or f, "state": fstate, "kinds": spec.get("kinds") or [],
                        "items": items, "applicable": ok, "why": why if not ok else ""}
            if ok and fstate != "ready":
                for k in spec.get("kinds") or []:
                    blocked[k] = "%s: %s" % (f, fstate)
        return {"v": 1, "features": feats, "summary": dict(summary), "blocked_kinds": blocked, "errors": self.spec_errors,
                "running": bool(self.running_item and self.running_item[0]) and list(self.running_item) or None}
