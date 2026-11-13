#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Motion studio on the node (agent 2.11): `motion.render` - code-driven video (Remotion 4) rendered ON THIS COMPUTER'S GPU.

The site builds the composition (a template spec, or the user's compiled code) and the renderer package; the node only has to run it.
Everything the node needs is installed AUTOMATICALLY, idempotently and without a single click, from files the site mirrors (no site
outside Iran is needed):

    <data>/motion/node/        portable Node.js (official win-x64 zip, sha256 from the manifest)
    <data>/motion/pack/        the renderer package prepared ON THE SITE: render.mjs + the bundled composition + a win32-x64
                               node_modules (@remotion/renderer with its Windows compositor, ffmpeg included)
    <data>/motion/browser/     Chrome headless shell (win64, mirrored by the site); Microsoft Edge (msedge.exe, present on Windows 11)
                               is the fallback when that download is impossible

The installer starts by itself with the first heartbeat (and again whenever the site publishes a newer package), follows the site's
download window for background downloads (a job somebody waits for is exempt), resumes interrupted downloads (nm_fetch), verifies
every file by sha256, smoke-tests the result with tiny REAL renders (one still = browser + GL backend, one second of H.264 video = the encoder and its colour handling)
and reports its state in the heartbeat:

    caps["motion_render"] = True                      (the site routes motion.render only to nodes that say so)
    caps["motion"] = {"state": "ready"|"installing"|"waiting"|"failed"|"checking"|"disabled", "step", "progress", "message",
                      "error", "pack_version", "node", "browser", "gl", "tested_at"}

The site keeps motion.render jobs queued while state != "ready". GPU: Chromium runs with the ANGLE (D3D11) backend on the video card
- compositing, rasterising and the SVG filters are the heavy part; Remotion itself can hardware-encode only on macOS, so the final
H.264 encode is libx264 on the CPU.

Job payload (validated here, never trusted): {"composition": "Template"|"User", "props": {...}, "user_js": "<compiled code>",
"scale": 0.1..1, "crf": 10..35, "max_seconds": <=120, "still": <frame, optional>}; inputs/ = the images the spec refers to.
Answer: out.mp4 (or out.png for a still) + motion-render.json.

Python 3.8+ standard library only. Console text is English; text that goes to the site (job message, caps) is Persian.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
IS_WIN = sys.platform.startswith("win")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0
MANIFEST = "nm-motion-pack.json"
MAX_USER_JS = 400 * 1024
MAX_SECONDS = 120
EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
RETRY_WAITS = (120, 300, 900, 1800)       # seconds between automatic install attempts after a failure

_LOCK = threading.RLock()
_STATE = {"state": "checking", "step": "", "progress": 0.0, "message": "", "error": "", "pack_version": "", "node": "", "browser": "",
          "gl": "", "color_space": "", "tested_at": ""}
_THREAD = {"t": None, "busy": False}
_JOBS = {"n": 0}
_AGENT = {"mod": None}

#: seams for tests (the installer is exercised with fakes: no network, no Windows, no GPU)
HOOKS = {"fetch": None, "run": None, "now": time.time, "sleep": time.sleep}


class MotionError(Exception):
    """A failure meant for the panel (Persian text). retryable=False: the site should not hand the same job out again."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def enabled():
    return (os.environ.get("NM_MOTION") or "1").strip().lower() not in ("0", "off", "no", "false")


def log(msg):
    agent = _AGENT["mod"]
    if agent is not None and hasattr(agent, "log"):
        try:
            agent.log("motion: " + msg)
            return
        except Exception:  # noqa: BLE001
            pass
    print("motion: " + msg, flush=True)


def warn(msg):
    agent = _AGENT["mod"]
    if agent is not None and hasattr(agent, "warn"):
        try:
            agent.warn("motion: " + msg)
            return
        except Exception:  # noqa: BLE001
            pass
    print("motion [!] " + msg, flush=True)


# ───────────────────────────────────────────── paths

def data_dir(agent=None):
    agent = agent or _AGENT["mod"]
    base = getattr(agent, "DATA", None) or os.environ.get("NM_DATA") or tempfile.gettempdir()
    d = os.path.join(base, "motion")
    os.makedirs(d, exist_ok=True)
    return d


def exe_name(base):
    return base + (".exe" if IS_WIN else "")


def paths(agent=None):
    d = data_dir(agent)
    return {"dir": d, "node_dir": os.path.join(d, "node"), "node": os.path.join(d, "node", exe_name("node")),
            "pack_dir": os.path.join(d, "pack"), "render": os.path.join(d, "pack", "render.mjs"),
            "bundle": os.path.join(d, "pack", "bundle"), "browser_dir": os.path.join(d, "browser"),
            "downloads": os.path.join(d, "downloads"), "state": os.path.join(d, "state.json"), "jobs": os.path.join(d, "jobs")}


# ───────────────────────────────────────────── state (what the panel sees)

def _set(**kw):
    with _LOCK:
        _STATE.update(kw)
    save_state()


def save_state(agent=None):
    try:
        p = paths(agent)["state"]
        with _LOCK:
            snap = dict(_STATE)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass


def load_state(agent=None):
    try:
        with open(paths(agent)["state"], encoding="utf-8") as fh:
            d = json.load(fh)
        for k in ("pack_version", "node", "browser", "gl", "color_space", "tested_at"):
            if d.get(k):
                _STATE[k] = d[k]
        return d
    except (OSError, ValueError):
        return {}


def snapshot():
    with _LOCK:
        return dict(_STATE)


# ───────────────────────────────────────────── helpers

def _agent_fn(name, default=None):
    agent = _AGENT["mod"]
    return getattr(agent, name, default) if agent is not None else default


def _site_cfg():
    agent = _AGENT["mod"]
    cfg = getattr(agent, "CONFIG", {}) if agent is not None else {}
    site = ""
    fn = getattr(agent, "site_base", None)          # the agent's own authority (<data>/node.json first), like bootstrap.py
    if callable(fn):
        try:
            site = fn() or ""
        except Exception:  # noqa: BLE001
            site = ""
    site = (site or os.environ.get("NM_SITE") or cfg.get("site") or "").rstrip("/")
    token = os.environ.get("NM_TOKEN") or cfg.get("token") or ""
    return site, token


def sha256_file(path, chunk=4 << 20):
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(name, dest, size=None, sha256=None, label=None):
    """Download {site}/3d/files/downloads/<name> (resumable, verified). HOOKS["fetch"] replaces it in tests."""
    if HOOKS["fetch"] is not None:
        return HOOKS["fetch"](name, dest, size, sha256)
    import urllib.parse

    import nm_fetch

    site, token = _site_cfg()
    if not site:
        raise MotionError("نشانیِ سایت روی این سرورِ پردازش معلوم نیست")
    url = "%s/3d/files/downloads/%s" % (site, urllib.parse.quote(name))
    if size is None or sha256 is None:
        s2, h2 = nm_fetch.site_file_info(site, token, name)
        size = size if size is not None else s2
        sha256 = sha256 or h2
    last = [0.0]

    def out(msg):
        now = time.time()
        if now - last[0] >= 10:
            last[0] = now
            log(msg.strip())

    try:
        return nm_fetch.fetch_with_progress(url, dest, out=out, headers=nm_fetch.site_headers(token), size=size, sha256=sha256, label=label or name)
    except nm_fetch.FetchError as e:
        raise MotionError("دانلودِ «%s» از سایت ناموفق بود: %s" % (name, str(e)[:200]))


def _safe_extract(zip_path, dest):
    """Unzip with a zip-slip guard."""
    base = os.path.abspath(dest)
    os.makedirs(base, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            target = os.path.abspath(os.path.join(base, m.filename))
            if target != base and not target.startswith(base + os.sep):
                raise MotionError("فایلِ فشردهٔ دانلودی ناامن است")
            if m.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)


def _swap(new_dir, final_dir):
    """Replace final_dir by new_dir (old copy kept until the swap worked)."""
    old = final_dir + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(final_dir):
        os.replace(final_dir, old)
    try:
        os.replace(new_dir, final_dir)
    except OSError:
        if os.path.isdir(old) and not os.path.isdir(final_dir):
            os.replace(old, final_dir)
        raise
    shutil.rmtree(old, ignore_errors=True)


def _find(root, name):
    for base, _dirs, files in os.walk(root):
        if name in files:
            return os.path.join(base, name)
    return None


def _marker(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _write_marker(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ───────────────────────────────────────────── installer

def load_manifest(agent=None):
    p = paths(agent)
    os.makedirs(p["downloads"], exist_ok=True)
    dest = os.path.join(p["downloads"], MANIFEST)
    try:
        os.remove(dest)
    except OSError:
        pass
    _fetch(MANIFEST, dest)
    try:
        with open(dest, encoding="utf-8") as fh:
            m = json.load(fh)
    except (OSError, ValueError):
        raise MotionError("فهرستِ بستهٔ موشن روی سایت خوانده نشد (هنوز ساخته نشده؟)")
    for key in ("version", "pack", "node", "browser"):
        if key not in m:
            raise MotionError("فهرستِ بستهٔ موشن روی سایت ناقص است")
    return m


def ensure_node(m, p):
    want = m["node"]["sha256"]
    if os.path.isfile(p["node"]) and _marker(os.path.join(p["node_dir"], ".nm-sha256")) == want:
        return "have"
    _set(step="node", message="دانلودِ Node.js (قابل‌حمل)", progress=0.1)
    zp = os.path.join(p["downloads"], m["node"]["name"])
    _fetch(m["node"]["name"], zp, size=m["node"].get("size"), sha256=want)
    tmp = p["node_dir"] + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    _safe_extract(zp, tmp)
    exe = _find(tmp, exe_name("node"))
    if not exe:
        raise MotionError("در بستهٔ Node.js فایلِ اجرایی پیدا نشد")
    root = os.path.dirname(exe)
    final_src = tmp
    if os.path.abspath(root) != os.path.abspath(tmp):      # the zip has one top folder (node-v20-win-x64/)
        flat = p["node_dir"] + ".flat"
        shutil.rmtree(flat, ignore_errors=True)
        os.replace(root, flat)
        shutil.rmtree(tmp, ignore_errors=True)
        final_src = flat
    _write_marker(os.path.join(final_src, ".nm-sha256"), want)
    _swap(final_src, p["node_dir"])
    try:
        os.remove(zp)
    except OSError:
        pass
    return "installed"


def ensure_pack(m, p):
    want = m["version"]
    if os.path.isfile(p["render"]) and _marker(os.path.join(p["pack_dir"], "VERSION")) == want and os.path.isdir(p["bundle"]):
        return "have"
    _set(step="pack", message="دانلودِ بستهٔ رندرِ موشن", progress=0.35)
    pk = m["pack"]
    zp = os.path.join(p["downloads"], pk["name"])
    _fetch(pk["name"], zp, size=pk.get("size"), sha256=pk.get("sha256"))
    tmp = p["pack_dir"] + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    _set(step="pack", message="بازکردنِ بستهٔ رندرِ موشن", progress=0.55)
    _safe_extract(zp, tmp)
    if not os.path.isfile(os.path.join(tmp, "render.mjs")):
        raise MotionError("بستهٔ رندرِ موشن ناقص است (render.mjs نیست)")
    _write_marker(os.path.join(tmp, "VERSION"), want)
    _swap(tmp, p["pack_dir"])
    try:
        os.remove(zp)
    except OSError:
        pass
    return "installed"


def edge_path():
    for cand in EDGE_PATHS:
        if os.path.isfile(cand):
            return cand
    return None


def ensure_browser(m, p):
    """(path, chrome_mode). The mirrored Chrome headless shell first; Edge when that cannot be had."""
    env = (os.environ.get("NM_MOTION_BROWSER") or "").strip()
    if env and os.path.isfile(env):
        return env, os.environ.get("NM_MOTION_CHROME_MODE") or "headless-shell"
    b = m["browser"]
    folder = os.path.join(p["browser_dir"], "chrome-headless-shell")
    exe = os.path.join(folder, exe_name("chrome-headless-shell"))
    if os.path.isfile(exe) and _marker(os.path.join(folder, ".nm-sha256")) == b["sha256"]:
        return exe, "headless-shell"
    _set(step="browser", message="دانلودِ مرورگرِ بی‌سر (Chrome headless shell)", progress=0.7)
    try:
        zp = os.path.join(p["downloads"], b["name"])
        _fetch(b["name"], zp, size=b.get("size"), sha256=b.get("sha256"))
        tmp = folder + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        _safe_extract(zp, tmp)
        found = _find(tmp, exe_name("chrome-headless-shell"))
        if not found:
            raise MotionError("در بستهٔ مرورگر فایلِ اجرایی پیدا نشد")
        root = os.path.dirname(found)
        flat = folder + ".flat"
        shutil.rmtree(flat, ignore_errors=True)
        os.replace(root, flat)
        shutil.rmtree(tmp, ignore_errors=True)
        _write_marker(os.path.join(flat, ".nm-sha256"), b["sha256"])
        _swap(flat, folder)
        try:
            os.remove(zp)
        except OSError:
            pass
        return exe, "headless-shell"
    except MotionError as e:
        edge = edge_path()
        if edge:
            warn("browser download failed (%s) - using Microsoft Edge" % e)
            return edge, "chrome-for-testing"
        raise


def has_gpu():
    """A discrete GPU (NVIDIA / AMD) is present: Chromium may use ANGLE/D3D11 on it."""
    if not IS_WIN:
        return False
    run = HOOKS["run"] or subprocess.run
    try:
        r = run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        if getattr(r, "returncode", 1) == 0 and "GPU" in (r.stdout or ""):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        r = run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True, timeout=25,
                creationflags=NO_WINDOW)
        names = (getattr(r, "stdout", "") or "").lower()
        return any(k in names for k in ("nvidia", "radeon", "amd ", "geforce", "rtx", "gtx"))
    except Exception:  # noqa: BLE001
        return False


def spec_selftest():
    return {"style": "flat-vector", "aspect": "9:16", "fps": 30, "lang": "fa",
            "scenes": [{"type": "title", "duration": 1, "title": "سلام موشن", "subtitle": "Motion"}]}


def smoke_test(p, browser, mode, gl):
    """Render ONE still of a tiny composition: proves node + pack + browser (+ the chosen GL backend) work together."""
    tmp = tempfile.mkdtemp(prefix="nm-motion-smoke-")
    try:
        job = {"serve": p["bundle"], "composition": "Template", "props": {"spec": spec_selftest()}, "out": os.path.join(tmp, "smoke.png"), "still": 12,
               "scale": 0.25, "browser": browser, "chrome_mode": mode, "gl": gl, "timeout_ms": 120000, "image_format": "png"}
        jf = os.path.join(tmp, "job.json")
        with open(jf, "w", encoding="utf-8") as fh:
            json.dump(job, fh)
        done, err = _run_render(p, jf, timeout=240)
        ok = bool(done) and os.path.isfile(job["out"]) and os.path.getsize(job["out"]) > 500
        return ok, (err or "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def video_smoke(p, browser, mode, gl):
    """One second of REAL video (the H.264 encode included) at a tiny size: proves the encoder settings work on this computer.
    bt709 (a standard yuv420p / TV-range file that every phone and editor plays) first, Remotion's default colour handling when that fails.
    Returns (color_space, "") or ("", last error)."""
    last = ""
    for color in ("bt709", "default"):
        tmp = tempfile.mkdtemp(prefix="nm-motion-vsmoke-")
        try:
            job = {"serve": p["bundle"], "composition": "Template", "props": {"spec": spec_selftest()}, "out": os.path.join(tmp, "smoke.mp4"), "scale": 0.25,
                   "browser": browser, "chrome_mode": mode, "gl": gl, "timeout_ms": 120000, "color_space": color, "crf": 28}
            jf = os.path.join(tmp, "job.json")
            with open(jf, "w", encoding="utf-8") as fh:
                json.dump(job, fh)
            done, err = _run_render(p, jf, timeout=300)
            if done and os.path.isfile(job["out"]) and os.path.getsize(job["out"]) > 500:
                return color, ""
            last = err or last
            warn("video smoke test with colour space %s failed: %s" % (color, (err or "")[:200]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return "", last


def _clean_env():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("NM_") and "TOKEN" not in k.upper() and "KEY" not in k.upper()}
    env["NODE_OPTIONS"] = "--max-old-space-size=2048"
    env["NO_COLOR"] = "1"
    return env


def _kill_tree(proc):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW, timeout=20)
        else:
            proc.kill()
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _run_render(p, job_file, timeout=3600, on_event=None, cancelled=None):
    """Run render.mjs; returns (done_event | None, error_text)."""
    run = HOOKS["run"]
    if run is not None:                      # tests
        return run(p, job_file, timeout, on_event, cancelled)
    node = p["node"] if os.path.isfile(p["node"]) else shutil.which("node")
    if not node:
        raise MotionError("Node.js روی این سرورِ پردازش نیست")
    proc = subprocess.Popen([node, p["render"], job_file], cwd=p["pack_dir"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                            encoding="utf-8", errors="replace", env=_clean_env(), creationflags=NO_WINDOW)
    done, err, tail = {}, "", []
    import queue

    q = queue.Queue()

    def pump(stream, tag):
        for line in stream:
            q.put((tag, line))
        q.put((tag, None))

    threads = [threading.Thread(target=pump, args=(proc.stdout, "o"), daemon=True), threading.Thread(target=pump, args=(proc.stderr, "e"), daemon=True)]
    for t in threads:
        t.start()
    ends, t0 = 0, time.time()
    try:
        while ends < 2:
            try:
                tag, line = q.get(timeout=1.0)
            except queue.Empty:
                tag, line = "", ""
            if line is None:
                ends += 1
            elif tag == "e" and line.strip():
                tail.append(line.strip())
                del tail[:-20]
            elif tag == "o" and line.strip().startswith("{"):
                try:
                    ev = json.loads(line)
                except ValueError:
                    ev = {}
                if ev.get("ev") == "done":
                    done = ev
                elif ev.get("ev") == "error":
                    err = ev.get("message") or "render error"
                if on_event:
                    on_event(ev)
            if time.time() - t0 > timeout:
                _kill_tree(proc)
                return {}, "timeout: the render took longer than %d s" % timeout
            if cancelled and cancelled():
                _kill_tree(proc)
                return {}, "cancelled"
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
    if proc.returncode not in (0, None) and not done:
        err = err or " | ".join(tail[-5:]) or "exit code %s" % proc.returncode
    return done, err


#: same rule as bootstrap.py: only "big" downloads (>= 200 MB) wait for the site's download window; the motion pack (~170 MB in all) never does.
#: A render waiting in the site's queue is never handed to a node whose toolchain is not "ready", so the exemption of a claimed job
#: could never apply - the background installer itself must start at once, or «turn the node on and it works» would take until the night.
BIG_BYTES = 200 << 20


def _small_downloads(m):
    try:
        return all(int((m.get(k) or {}).get("size") or 0) < BIG_BYTES for k in ("pack", "node", "browser"))
    except (TypeError, ValueError, AttributeError):
        return False


def _window_ok(exempt):
    allowed = _agent_fn("download_allowed", None)
    return bool(exempt) or not callable(allowed) or bool(allowed())


def _waiting_text():
    wait = _agent_fn("seconds_until_window", None)
    when = ""
    if callable(wait):
        try:
            when = " (تا ~%d دقیقهٔ دیگر)" % int(wait() // 60)
        except Exception:  # noqa: BLE001
            when = ""
    return "منتظرِ بازهٔ دانلودِ شبانه برای نصبِ ابزارِ موشن" + when


def install(agent=None, exempt=False):
    """Make the toolchain ready (idempotent). Returns the state dict.

    exempt=True: a job somebody waits for - the download window is ignored. A node that is already "ready" only re-reads the site's manifest
    (cheap); it touches nothing - and never swaps files under a running render - unless the site published a newer package."""
    with _LOCK:
        if _THREAD.get("busy"):
            return snapshot()
        _THREAD["busy"] = True
    try:
        p = paths(agent)
        for d in (p["downloads"], p["browser_dir"], p["jobs"]):
            os.makedirs(d, exist_ok=True)
        was_ready = snapshot().get("state") == "ready"
        if was_ready:
            if _JOBS["n"]:
                return snapshot()
            try:
                m = load_manifest(agent)
            except MotionError:
                return snapshot()                  # the site cannot be reached right now: stay ready with what we have
            same = (m["version"] == snapshot().get("pack_version") and os.path.isfile(p["render"])
                    and _marker(os.path.join(p["pack_dir"], "VERSION")) == m["version"])
            if same:
                return snapshot()
            if not _window_ok(exempt or _small_downloads(m)):
                return snapshot()                  # a big new package waits for the night window; the old one keeps working
        else:
            _set(state="installing", step="manifest", message="بررسیِ بستهٔ موشن روی سایت", progress=0.02, error="")
            m = load_manifest(agent)
            if not _window_ok(exempt or _small_downloads(m)):
                _set(state="waiting", message=_waiting_text(), error="")
                return snapshot()
        _set(state="installing", step="manifest", message="نصبِ خودکارِ ابزارِ موشن", progress=0.05, error="")
        ensure_node(m, p)
        ensure_pack(m, p)
        browser, mode = ensure_browser(m, p)
        _set(step="test", message="آزمونِ رندر (یک تصویرِ کوچک)", progress=0.9)
        order = ["angle", "swangle"] if has_gpu() else ["swangle"]
        gl, last_err = "", ""
        for cand in order:
            ok, err = smoke_test(p, browser, mode, cand)
            if ok:
                gl = cand
                break
            last_err = err
            warn("smoke test with gl=%s failed: %s" % (cand, err[:200]))
        if not gl:
            raise MotionError("آزمونِ رندر روی این کامپیوتر ناموفق بود: " + (last_err or "؟")[:300])
        _set(step="test", message="آزمونِ کدگذاریِ ویدیو (یک ثانیه)", progress=0.95)
        color, verr = video_smoke(p, browser, mode, gl)
        if not color:
            raise MotionError("آزمونِ کدگذاریِ ویدیو روی این کامپیوتر ناموفق بود: " + (verr or "؟")[:300])
        _set(state="ready", step="", progress=1.0, message="ابزارِ موشن آماده است", error="", pack_version=m["version"], node=p["node"], browser=browser, gl=gl, color_space=color,
             chrome_mode=mode, tested_at=time.strftime("%Y-%m-%dT%H:%M:%S"), gpu=bool(gl == "angle"))
        log("ready: pack %s, gl=%s, browser=%s" % (m["version"], gl, os.path.basename(browser)))
        return snapshot()
    except MotionError as e:
        _set(state="failed", message="نصبِ ابزارِ موشن ناموفق بود", error=str(e)[:400])
        warn("install failed: %s" % e)
        return snapshot()
    except Exception as e:  # noqa: BLE001 - never let the installer take the agent down
        _set(state="failed", message="نصبِ ابزارِ موشن ناموفق بود", error=("%s: %s" % (e.__class__.__name__, e))[:400])
        warn("install crashed: %r" % e)
        return snapshot()
    finally:
        with _LOCK:
            _THREAD["busy"] = False


def _loop(agent):
    """Background: keep trying until the toolchain is ready (and notice a newer package the site published)."""
    fails = 0
    while True:
        st = install(agent)
        if st["state"] == "ready":
            fails = 0
            HOOKS["sleep"](1800)                    # re-read the manifest every 30 minutes (a newer package => install again)
            continue
        if st["state"] == "waiting":
            HOOKS["sleep"](300)
            continue
        HOOKS["sleep"](RETRY_WAITS[min(fails, len(RETRY_WAITS) - 1)])
        fails += 1


def start_background(agent=None):
    with _LOCK:
        t = _THREAD.get("t")
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_loop, args=(agent or _AGENT["mod"],), daemon=True, name="motion-install")
        _THREAD["t"] = t
    t.start()


def caps(agent=None):
    """The heartbeat keys of this feature. The first call starts the automatic installer."""
    _AGENT["mod"] = agent or _AGENT["mod"]
    if not enabled():
        return {"motion_render": False, "motion": {"state": "disabled", "message": "غیرفعال (NM_MOTION=0)"}}
    if _THREAD.get("t") is None:
        load_state(agent)
        start_background(agent)
    st = snapshot()
    keep = {k: st.get(k, "") for k in ("state", "step", "progress", "message", "error", "pack_version", "gl", "color_space", "tested_at", "gpu")}
    keep["browser"] = os.path.basename(st.get("browser") or "")
    keep["agent_module"] = VERSION
    return {"motion_render": True, "motion": keep}


# ───────────────────────────────────────────── the job

ALLOWED_KEYS = {"composition", "props", "user_js", "scale", "crf", "max_seconds", "still", "title", "style", "mode", "render_id", "selftest", "pack"}


def validate_payload(p):
    """(cleaned payload) or MotionError(retryable=False). Nothing in the payload is ever executed by the node itself."""
    if not isinstance(p, dict):
        raise MotionError("درخواستِ رندر معتبر نیست", retryable=False)
    unknown = set(p) - ALLOWED_KEYS
    if unknown:
        raise MotionError("کلیدِ ناشناخته در درخواستِ رندر: %s" % ", ".join(sorted(unknown))[:80], retryable=False)
    comp = p.get("composition") or "Template"
    if comp not in ("Template", "User"):
        raise MotionError("نوعِ ترکیب معتبر نیست", retryable=False)
    props = p.get("props")
    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise MotionError("props باید شیء باشد", retryable=False)
    try:
        scale = float(p.get("scale", 0.5))
        crf = int(p.get("crf", 18))
        max_s = float(p.get("max_seconds", MAX_SECONDS))
    except (TypeError, ValueError):
        raise MotionError("اندازه/کیفیتِ رندر عدد نیست", retryable=False)
    if not 0.1 <= scale <= 1.0:
        raise MotionError("مقیاسِ رندر باید بین ۰٫۱ و ۱ باشد", retryable=False)
    if not 10 <= crf <= 35:
        raise MotionError("کیفیتِ کدگذاری معتبر نیست", retryable=False)
    out = {"composition": comp, "props": props, "scale": scale, "crf": crf, "max_seconds": min(MAX_SECONDS, max(1.0, max_s))}
    if p.get("still") is not None:
        out["still"] = max(0, int(p["still"]))
    if comp == "User":
        js = p.get("user_js")
        if not isinstance(js, str) or "__NM_USER_FACTORY" not in js:
            raise MotionError("کدِ کاربر (کامپایل‌شده) در درخواست نیست", retryable=False)
        if len(js.encode("utf-8")) > MAX_USER_JS:
            raise MotionError("کدِ کاربر خیلی بزرگ است", retryable=False)
        out["user_js"] = js
    return out


def _cpu_count():
    try:
        return os.cpu_count() or 4
    except Exception:  # noqa: BLE001
        return 4


def run(job, agent):
    """The `motion.render` handler."""
    _AGENT["mod"] = agent
    JobError = getattr(agent, "JobError", None)

    def fail(exc):
        if JobError is not None:
            return JobError(str(exc), retryable=getattr(exc, "retryable", True))
        return RuntimeError(str(exc))

    try:
        payload = validate_payload(job.payload)
    except MotionError as e:
        raise fail(e)
    _JOBS["n"] += 1
    try:
        return _run_job(job, agent, payload, fail)
    finally:
        _JOBS["n"] = max(0, _JOBS["n"] - 1)


def _run_job(job, agent, payload, fail):
    st = snapshot()
    if st.get("state") != "ready":
        job.progress(0.03, "نصبِ خودکارِ ابزارِ موشن روی سرورِ پردازش")
        st = install(agent, exempt=True)          # somebody waits for this render: no download window
        if st.get("state") != "ready":
            raise fail(MotionError("ابزارِ موشن روی این کامپیوتر آماده نشد: %s" % (st.get("error") or st.get("message") or "؟")))
    p = paths(agent)
    work = os.path.join(p["jobs"], job.uid)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    try:
        out_name = "out.png" if payload.get("still") is not None else "out.mp4"
        out_path = job.out(out_name)
        spec = {"serve": p["bundle"], "composition": payload["composition"], "props": payload["props"], "assets_dir": job.inputs, "out": out_path,
                "scale": payload["scale"], "crf": payload["crf"], "browser": st.get("browser"), "chrome_mode": st.get("chrome_mode") or "headless-shell",
                "gl": st.get("gl") or "swangle", "concurrency": max(1, min(4, _cpu_count() // 2)), "max_seconds": payload["max_seconds"],
                "timeout_ms": 180000, "offline": True, "color_space": st.get("color_space") or "bt709"}
        if payload.get("still") is not None:
            spec["still"] = payload["still"]
        if payload["composition"] == "User":
            uj = os.path.join(work, "user.js")
            with open(uj, "w", encoding="utf-8") as fh:
                fh.write(payload["user_js"])
            spec["user_js"] = uj
        jf = os.path.join(work, "job.json")
        t0 = time.time()
        gl_used = spec["gl"]
        last = [0.0, ""]

        def on_event(ev):
            if ev.get("ev") == "progress":
                frac = float(ev.get("progress") or 0)
                msg = "در حال رندر روی کارتِ گرافیک — فریمِ %s از %s" % (ev.get("rendered", "?"), ev.get("total", "?"))
                if ev.get("stage") == "encoding":
                    msg = "کدگذاریِ ویدیو"
                if frac - last[0] >= 0.02 or ev.get("stage") != last[1]:
                    last[0], last[1] = frac, ev.get("stage")
                    job.progress(min(0.97, 0.05 + 0.9 * frac), msg)

        def cancelled():
            return bool(getattr(job, "cancelled", False))

        def attempt():
            with open(jf, "w", encoding="utf-8") as fh:
                json.dump(spec, fh)
            return _run_render(p, jf, timeout=max(120, int(getattr(job, "timeout_s", 3600)) - 60), on_event=on_event, cancelled=cancelled)

        job.progress(0.05, "شروعِ رندر")
        done, err = attempt()
        if not done and spec["gl"] == "angle" and err and err != "cancelled":
            warn("render with the GPU backend failed (%s) - retrying on the software backend" % err[:160])
            spec["gl"] = gl_used = "swangle"
            job.progress(0.05, "تلاشِ دوباره (رندرِ نرم‌افزاری)")
            done, err = attempt()
        if err == "cancelled":
            raise fail(MotionError("لغو شد", retryable=False))
        if not done or not os.path.isfile(out_path):
            raise fail(MotionError("رندر ناموفق بود: %s" % (err or "خروجی ساخته نشد")[:300]))
        on_gpu = gl_used == "angle"
        meta = {"primary": out_name, "seconds": round(time.time() - t0, 1), "gl": gl_used, "width": done.get("width"), "height": done.get("height"),
                "fps": done.get("fps"), "frames": done.get("frames"), "bytes": done.get("bytes"), "pack": st.get("pack_version"), "engine": "remotion",
                # the node self-test reads these: "gpu" = Chromium rasterised on the video card (ANGLE/D3D11); the H.264 encode is CPU either way
                "device": "gpu" if on_gpu else "cpu",
                "device_note": ("Chromium ANGLE/D3D11 on the video card; H.264 encode on the CPU" if on_gpu
                                else "software rendering: Chromium could not use the video card (no discrete GPU found or the GPU backend failed its test)")}
        with open(job.out("motion-render.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        return meta
    finally:
        shutil.rmtree(work, ignore_errors=True)


def register(handlers, agent):
    """The ONE call agent.py makes: adds HANDLERS["motion.render"] and puts this feature into every heartbeat (it wraps
    Capabilities.probe the way multiangle_jobs.py does, so agent.py needs no second edit). The first heartbeat starts the installer."""
    _AGENT["mod"] = agent
    handlers["motion.render"] = lambda job: run(job, agent)
    cls = getattr(agent, "Capabilities", None)
    orig = getattr(cls, "probe", None)
    if orig is not None and not getattr(orig, "_motion", False):
        def probe(self):
            out = orig(self)
            try:
                out.update(caps(agent))
            except Exception as e:  # noqa: BLE001 - an optional module must never keep the heartbeat from going out
                out["motion_render"] = False
                warn("capabilities could not be read: %s" % e)
            return out

        probe._motion = True
        cls.probe = probe
    return True


# ───────────────────────────────────────────── command line (install / status by hand)

def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="motion studio toolchain of this node")
    ap.add_argument("cmd", choices=("status", "install"))
    ap.add_argument("--data", help="agent data folder (default: NM_DATA)")
    args = ap.parse_args(argv)
    if args.data:
        os.environ["NM_DATA"] = args.data
    if args.cmd == "status":
        print(json.dumps(load_state() or snapshot(), indent=1, ensure_ascii=False))
        return 0
    st = install(None, exempt=True)
    print(json.dumps(st, indent=1, ensure_ascii=False))
    return 0 if st.get("state") == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
