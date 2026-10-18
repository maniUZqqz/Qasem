#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UpMarket processing node (GPU machine agent).

Runs on the GPU computer. It needs NO public IP and opens NO port: it connects out to the site
with its own token, claims jobs, runs them on local services (ComfyUI, Ollama, PersianAiKit photo/
video/voice servers) and uploads the results. Two nodes never take the same job; identical requests
are not processed twice (the site de-duplicates them).

Python 3.10+ standard library only. Configuration: node.json next to this file (written automatically after
the first run), environment variables NM_SITE / NM_TOKEN / NM_NODE / NM_ENROLL_KEY, and site.json (site URL).
First run: START.bat asks for the site-wide enrollment key (panel > Processing servers > Register a new server);
the computer registers itself under its own name and receives its own token. ONE START.bat for every machine.

    python agent.py            run the node
    python agent.py --check    print a diagnostic report (site, ComfyUI, profiles, services, Blender) and exit

Protocol (every request carries "Authorization: Node <token>"):
  POST {site}/api/v1/compute/heartbeat/            presence + capabilities
  POST {site}/api/v1/compute/claim/                take one job (or none)
  GET  {site}/api/v1/compute/jobs/<uid>/package/   payload.json + input files (zip)
  POST {site}/api/v1/compute/jobs/<uid>/progress/  progress; the answer may say cancel=true
  POST {site}/api/v1/compute/jobs/<uid>/upload/    output files (multipart)
  POST {site}/api/v1/compute/jobs/<uid>/finish/    done {ok, error, meta}
  POST {site}/api/v1/compute/log/                  this node's warnings/errors (shown in the panel)

Job kinds:
  echo            connectivity test
  comfy.graph     raw ComfyUI API graph (payload.graph) + input files referenced by name
  comfy.profile   ready profile (upmarket_comfyui_flask/profiles.json): prompt, profile, controls, image
  photo.edit      photo recipe (PersianAiKit.Photo :5670)        photo.analyze   photo analysis
  video.edit      video recipe/export (PersianAiKit.Video :5680)
  voice.tts       text to speech (PersianAiKit.Voice :5600)      voice.asr       speech to text
  ollama.chat     text/vision with Ollama (:11434) — payload is the /api/chat or /api/generate body
  *.http          generic relay to that service: {method, path, json|form, files:{field: input name}}
"""
import glob
import hashlib
import json
import mimetypes
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone

VERSION = "1.1"
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
LOGS = os.path.join(HERE, "logs")
BRIDGE_DIR = os.path.join(HERE, "upmarket_comfyui_flask")

SERVICES = {
    "comfyui": ("NM_COMFYUI_URL", "http://127.0.0.1:8188"),
    "comfy_bridge": ("NM_BRIDGE_URL", "http://127.0.0.1:5000"),
    "photo": ("NM_PHOTO_URL", "http://127.0.0.1:5670"),
    "video": ("NM_VIDEO_URL", "http://127.0.0.1:5680"),
    "voice": ("NM_VOICE_URL", "http://127.0.0.1:5600"),
    "ollama": ("NM_OLLAMA_URL", "http://127.0.0.1:11434"),
}


# ───────────────────────────────────────────── logging (console + file + site)

class SiteLog:
    """Buffers WARNING/ERROR lines and ships them to the site so problems are visible in the panel."""

    def __init__(self):
        self.site = None
        self.buf = []
        self.lock = threading.Lock()
        self.last_flush = 0.0

    def add(self, level, message):
        with self.lock:
            self.buf.append({"level": level, "message": message[:3000],
                             "ts": datetime.now(timezone.utc).isoformat()})
            if len(self.buf) > 300:
                del self.buf[:-300]

    def flush(self, force=False):
        if self.site is None:
            return
        with self.lock:
            if not self.buf or (not force and len(self.buf) < 20 and time.time() - self.last_flush < 30):
                return
            lines, self.buf = self.buf[:], []
            self.last_flush = time.time()
        try:
            self.site.post("/api/v1/compute/log/", {"lines": lines}, timeout=30)
        except Exception as e:  # noqa: BLE001 — never let log shipping break the loop
            with self.lock:
                self.buf = lines + self.buf
            print("%s  [log shipping failed: %s]" % (time.strftime("%H:%M:%S"), e), flush=True)


SITE_LOG = SiteLog()


def log(msg, level="INFO"):
    line = "%s  %s%s" % (time.strftime("%H:%M:%S"), ("" if level == "INFO" else level + ": "), msg)
    print(line, flush=True)
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(os.path.join(LOGS, "agent.log"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    if level in ("WARNING", "ERROR", "CRITICAL"):
        SITE_LOG.add(level, msg)


def warn(msg):
    log(msg, "WARNING")


def error(msg):
    log(msg, "ERROR")


# ───────────────────────────────────────────── config & helpers

def save_node_json(cfg):
    path = os.path.join(HERE, "node.json")
    try:
        json.dump({"site": cfg["site"], "token": cfg["token"], "name": cfg["name"]},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        log("Saved node.json (site, token, name) next to agent.py")
    except OSError as e:
        warn("could not write node.json: %s" % e)


def enroll(cfg, key):
    """Register this computer on the site with the site-wide enrollment key -> own token (same name = same node)."""
    name = cfg.get("name") or socket.gethostname()
    try:
        r = http("POST", cfg["site"] + "/api/v1/compute/enroll/", {"key": key, "name": name, "hostname": socket.gethostname()},
                 timeout=30)
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise SiteError("enrollment refused (HTTP %s): %s" % (e.code, detail)) from e
    except (urllib.error.URLError, OSError) as e:
        raise SiteError("site unreachable (%s): %s" % (cfg["site"], e)) from e
    cfg["token"], cfg["name"] = r["token"], r["name"]
    log("enrolled as node '%s' (%s)" % (cfg["name"], "new" if r.get("created") else "existing"))
    save_node_json(cfg)
    return cfg


def load_config(interactive=False):
    """node.json next to agent.py (saved after the first run) > environment variables > site.json (site URL only)."""
    cfg = {}
    path = os.path.join(HERE, "node.json")
    if os.path.isfile(path):
        try:
            cfg = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError) as e:
            warn("node.json could not be read (%s); ignoring it" % e)
            cfg = {}
    for key, env in (("site", "NM_SITE"), ("token", "NM_TOKEN"), ("name", "NM_NODE"), ("slots", "NM_SLOTS"),
                     ("enroll_key", "NM_ENROLL_KEY")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if not cfg.get("site"):
        try:
            cfg["site"] = json.load(open(os.path.join(HERE, "site.json"), encoding="utf-8")).get("site", "")
        except (OSError, ValueError):
            pass
    cfg["site"] = (cfg.get("site") or "").strip().rstrip("/")
    cfg["token"] = (cfg.get("token") or "").strip()
    cfg["name"] = (cfg.get("name") or socket.gethostname()).strip()
    try:
        cfg["slots"] = max(1, int(cfg.get("slots") or 1))
    except ValueError:
        cfg["slots"] = 1
    if interactive and sys.stdin and sys.stdin.isatty():
        if not cfg["site"]:
            cfg["site"] = input("Site URL (e.g. http://87.107.160.17:8040): ").strip().rstrip("/")
        if cfg["site"] and not cfg["token"] and not cfg.get("enroll_key"):
            cfg["enroll_key"] = input("Enrollment key (panel > Processing servers > Register a new server): ").strip()
    if cfg["site"] and not cfg["token"] and cfg.get("enroll_key"):
        try:
            enroll(cfg, cfg["enroll_key"])
        except SiteError as e:
            error(str(e))
    elif cfg["site"] and cfg["token"] and not os.path.isfile(path):
        save_node_json(cfg)
    return cfg


def service_url(key):
    env, default = SERVICES[key]
    return os.environ.get(env, default).rstrip("/")


def listening(url, timeout=1.0):
    p = urllib.parse.urlparse(url)
    try:
        with socket.create_connection((p.hostname or "127.0.0.1", p.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


def http(method, url, data=None, headers=None, timeout=60, raw=False):
    """Plain HTTP request. data: dict/list => JSON; bytes => as is; None => no body. Returns dict (JSON) or bytes."""
    h = {"Accept": "application/json, */*"}
    body = None
    if isinstance(data, (dict, list)):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        h["Content-Type"] = "application/json; charset=utf-8"
    elif data is not None:
        body = data
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = r.read()
        ctype = r.headers.get("Content-Type", "")
        if raw:
            return payload, dict(r.headers)
        if "json" in ctype:
            return json.loads(payload.decode("utf-8")) if payload else {}
        return payload


def multipart(fields, files):
    """multipart/form-data body. files: {field: (filename, bytes)}"""
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (fields or {}).items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode("utf-8"))
    for k, (name, content) in (files or {}).items():
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (
            boundary, k, name, ctype)).encode("utf-8") + content + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(parts), "multipart/form-data; boundary=%s" % boundary


class SiteError(Exception):
    pass


class Site:
    """The main site (static IP)."""

    def __init__(self, base, token):
        self.base = base
        self.token = token

    def _req(self, method, path, data=None, headers=None, timeout=60, raw=False):
        h = {"Authorization": "Node " + self.token}
        h.update(headers or {})
        try:
            return http(method, self.base + path, data, h, timeout=timeout, raw=raw)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            if e.code in (401, 403):
                raise SiteError("site rejected the node token (HTTP %s). The token was rotated or the node was deleted: "
                                "delete node.json and run START.bat again with the enrollment key. %s" % (e.code, detail)) from e
            raise SiteError("%s %s -> HTTP %s %s" % (method, path, e.code, detail)) from e
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise SiteError("site unreachable (%s): %s" % (self.base, e)) from e

    def post(self, path, data=None, timeout=60):
        return self._req("POST", path, data if data is not None else {}, timeout=timeout)

    def get_json(self, path, timeout=30):
        return self._req("GET", path, timeout=timeout)

    def download(self, path, dest, timeout=600):
        payload, _ = self._req("GET", path, timeout=timeout, raw=True)
        with open(dest, "wb") as fh:
            fh.write(payload)

    def upload(self, path, files, timeout=1800):
        body, ctype = multipart({}, files)
        return self._req("POST", path, body, {"Content-Type": ctype}, timeout=timeout)


# ───────────────────────────────────────────── capabilities

def gpu_names():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True,
                             text=True, timeout=15).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def blender_path():
    cands = [os.environ.get("UP3D_BLENDER", ""), os.path.join(HERE, "vendor", "blender", "blender.exe"),
             os.path.join(HERE, "vendor", "blender", "blender")]
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    base = os.path.join(pf, "Blender Foundation")
    if os.path.isdir(base):
        cands += sorted(glob.glob(os.path.join(base, "*", "blender.exe")), reverse=True)
    cands.append(shutil.which("blender") or "")
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def load_profiles():
    path = os.path.join(BRIDGE_DIR, "profiles.json")
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []


class Capabilities:
    def __init__(self, name, slots):
        self.name = name
        self.slots = slots
        self.cache = {}
        self.comfy_nodes = None
        self.comfy_nodes_at = 0
        self.last_hash = ""

    def probe(self):
        caps = {"agent": VERSION, "hostname": socket.gethostname(), "platform": platform.platform(), "slots": self.slots}
        # closed ports on Windows can each take up to a second => probe them in parallel
        threads = {key: threading.Thread(target=lambda k=key: caps.__setitem__(k, listening(service_url(k), 0.8)))
                   for key in SERVICES}
        for t in threads.values():
            t.start()
        for t in threads.values():
            t.join()
        gpus = gpu_names()
        if gpus:
            caps["gpu"] = ", ".join(gpus)
        caps["blender"] = bool(blender_path()) and os.path.isdir(os.path.join(HERE, "up3d"))
        if caps["comfyui"]:
            if self.comfy_nodes is None or time.time() - self.comfy_nodes_at > 600:
                try:
                    info = http("GET", service_url("comfyui") + "/object_info", timeout=60)
                    self.comfy_nodes = sorted(info.keys()) if isinstance(info, dict) else []
                    self.comfy_nodes_at = time.time()
                except Exception as e:  # noqa: BLE001
                    warn("could not read ComfyUI node list (/object_info): %s" % e)
                    self.comfy_nodes = self.comfy_nodes or []
            caps["comfy_nodes"] = self.comfy_nodes
            caps["lipsync"] = "LatentSyncNode" in (self.comfy_nodes or [])
            caps["comfy_profiles"] = [p["id"] for p in load_profiles()]
        if caps["ollama"]:
            try:
                tags = http("GET", service_url("ollama") + "/api/tags", timeout=10)
                caps["ollama_models"] = [m.get("name") for m in tags.get("models", []) if m.get("name")]
            except Exception:  # noqa: BLE001
                pass
        self.cache = caps
        return caps

    def changed(self):
        """Send the full capability set only when something changed (or every 5 minutes)."""
        h = hashlib.sha1(json.dumps(self.cache, sort_keys=True, default=str).encode()).hexdigest()
        if h != self.last_hash:
            self.last_hash = h
            return True
        return False


# ───────────────────────────────────────────── diagnostics (--check)

def check(cfg):
    ok_all = True

    def row(ok, label, detail=""):
        nonlocal ok_all
        ok_all = ok_all and (ok is not False)
        mark = "OK " if ok else ("-- " if ok is None else "!! ")
        print("  %s %-28s %s" % (mark, label, detail))

    print("UpMarket processing node %s — diagnostic" % VERSION)
    print("  folder: %s" % HERE)
    row(sys.version_info >= (3, 10), "Python", sys.version.split()[0] + (" (3.10+ required)" if sys.version_info < (3, 10) else ""))
    row(bool(cfg["site"]), "site URL", cfg["site"] or "missing (site.json / NM_SITE / node.json)")
    row(bool(cfg["token"]), "node token", (cfg["token"][:6] + "...") if cfg["token"]
        else "not enrolled yet: run START.bat and paste the enrollment key from the panel")
    row(True, "node name", cfg["name"])
    if cfg["site"] and cfg["token"]:
        try:
            code = None
            try:
                http("GET", cfg["site"] + "/healthz", timeout=15, raw=True)
                code = 200
            except urllib.error.HTTPError as e:
                code = e.code
            row(code == 200, "site reachable", "%s/healthz -> %s" % (cfg["site"], code))
            site = Site(cfg["site"], cfg["token"])
            r = site.post("/api/v1/compute/heartbeat/", {})
            row(True, "token accepted", "registered as '%s'" % r.get("name"))
        except Exception as e:  # noqa: BLE001
            row(False, "site / token", str(e)[:200])
    for key in SERVICES:
        up = listening(service_url(key), 1.0)
        row(up if key == "comfyui" else (True if up else None), key, service_url(key) + (" (listening)" if up else " (not running)"))
    if listening(service_url("comfyui"), 1.0):
        try:
            info = http("GET", service_url("comfyui") + "/object_info", timeout=60)
            row(True, "ComfyUI nodes", "%d node classes; LatentSync: %s" % (len(info), "LatentSyncNode" in info))
        except Exception as e:  # noqa: BLE001
            row(False, "ComfyUI nodes", str(e)[:120])
    profiles = load_profiles()
    row(bool(profiles), "profiles.json", "%d profiles in %s" % (len(profiles), BRIDGE_DIR) if profiles else "missing: " + os.path.join(BRIDGE_DIR, "profiles.json"))
    for p in profiles:
        wf = os.path.join(BRIDGE_DIR, "workflows", p.get("file", ""))
        row(os.path.isfile(wf), "  workflow " + p.get("id", "?"), p.get("file", ""))
    gpus = gpu_names()
    row(True if gpus else None, "GPU (nvidia-smi)", ", ".join(gpus) if gpus else "nvidia-smi not found")
    bl = blender_path()
    row(True if bl else None, "Blender (3D worker)", bl or "not found: install Blender 4.5 or let worker-3d.bat download it")
    for d in ("up3d", "engine", "assets"):
        row(os.path.isdir(os.path.join(HERE, d)), "  3D folder " + d, os.path.join(HERE, d))
    try:
        free = shutil.disk_usage(HERE).free // (1024 ** 3)
        row(free > 5, "free disk", "%d GB" % free)
    except OSError:
        pass
    print("RESULT: %s" % ("all good" if ok_all else "some items need attention (see !! lines)"))
    return 0 if ok_all else 1


# ───────────────────────────────────────────── ComfyUI

def comfy_upload(name, content):
    body, ctype = multipart({"overwrite": "true"}, {"image": (name, content)})
    r = http("POST", service_url("comfyui") + "/upload/image", body, {"Content-Type": ctype}, timeout=120)
    return r.get("name", name) if isinstance(r, dict) else name


def comfy_run(graph, job):
    """queue -> wait -> download outputs. Returns (saved files, primary output name)."""
    base = service_url("comfyui")
    client_id = "nm-" + uuid.uuid4().hex[:12]
    try:
        r = http("POST", base + "/prompt", {"prompt": graph, "client_id": client_id}, timeout=120)
    except urllib.error.HTTPError as e:
        raise RuntimeError("ComfyUI rejected the graph (HTTP %s): %s" % (e.code, e.read()[:600].decode("utf-8", "replace")))
    if not isinstance(r, dict) or "prompt_id" not in r:
        raise RuntimeError("ComfyUI did not accept the graph: %s" % str(r)[:400])
    pid = r["prompt_id"]
    job.progress(0.05, "queued in ComfyUI")
    deadline = time.time() + job.timeout_s
    last_report = 0
    while time.time() < deadline:
        if job.cancelled:
            try:
                http("POST", base + "/interrupt", b"", timeout=10)
            except Exception:  # noqa: BLE001
                pass
            raise Cancelled()
        try:
            hist = http("GET", base + "/history/" + pid, timeout=60)
        except Exception as e:  # noqa: BLE001
            warn("ComfyUI history poll failed: %s" % e)
            hist = {}
        entry = hist.get(pid) if isinstance(hist, dict) else None
        if entry:
            status = entry.get("status", {}) or {}
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                detail = json.dumps(msgs[-1][1], ensure_ascii=False)[:600] if msgs else str(status)[:600]
                raise RuntimeError("ComfyUI execution error: " + detail)
            outputs = entry.get("outputs", {}) or {}
            files = []
            for node_id, out in outputs.items():
                for key in ("videos", "gifs", "images", "audio"):
                    for item in out.get(key, []) or []:
                        if item.get("filename"):
                            files.append((key, item))
            if files or status.get("completed"):
                if not files:
                    raise RuntimeError("ComfyUI finished but produced no image/video output")
                saved = []
                primary = None
                for key, item in files:
                    if item.get("type") == "temp" and key == "images" and any(k in ("videos", "gifs") for k, _ in files):
                        continue  # temporary frame previews next to a video
                    q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                                "type": item.get("type", "output")})
                    data, _ = http("GET", base + "/view?" + q, timeout=600, raw=True)
                    name = os.path.basename(item["filename"])
                    dest = job.out(name)
                    with open(dest, "wb") as fh:
                        fh.write(data)
                    saved.append(dest)
                    ext = os.path.splitext(name)[1].lower()
                    if primary is None and (key in ("videos", "gifs") or ext in (".mp4", ".webm", ".mov")):
                        primary = name
                if primary is None:
                    primary = os.path.basename(saved[0])
                return saved, primary
        if time.time() - last_report > 8:
            last_report = time.time()
            job.progress(0.5, "ComfyUI rendering")
        time.sleep(2)
    raise RuntimeError("ComfyUI did not finish within %s seconds" % job.timeout_s)


def set_node_input(graph, node_id, input_name, value):
    node = graph.get(str(node_id))
    if not node:
        return False
    node.setdefault("inputs", {})[input_name] = value
    return True


def apply_profile(profile, prompt, negative, image_name, values):
    """Same logic as the Flask bridge (queue_job): profile + prompt + controls -> ready ComfyUI graph."""
    wf_path = os.path.join(BRIDGE_DIR, "workflows", profile["file"])
    if not os.path.isfile(wf_path):
        raise RuntimeError("workflow file missing: %s" % wf_path)
    graph = json.load(open(wf_path, encoding="utf-8"))
    node_map = {"image": {"prompt": ("4", "text"), "negative": ("3", "text"), "image": None},
                "edit": {"prompt": ("4", "text"), "negative": ("3", "text"), "image": ("16", "image")},
                "video": {"prompt": ("10", "text"), "negative": ("11", "text"), "image": ("1", "image")}}[profile["kind"]]
    cfg = {}
    try:
        cfg = json.load(open(os.path.join(BRIDGE_DIR, "config.json"), encoding="utf-8")).get("workflows", {}).get(profile["kind"], {})
    except (OSError, ValueError):
        pass
    set_node_input(graph, cfg.get("prompt_node_id") or node_map["prompt"][0], cfg.get("prompt_input") or node_map["prompt"][1], prompt)
    if negative is not None:
        set_node_input(graph, cfg.get("negative_prompt_node_id") or node_map["negative"][0],
                       cfg.get("negative_prompt_input") or node_map["negative"][1], negative)
    img = cfg.get("image_node_id") or (node_map["image"][0] if node_map["image"] else "")
    img_in = cfg.get("image_input") or (node_map["image"][1] if node_map["image"] else "image")
    if img and image_name:
        set_node_input(graph, img, img_in, image_name)
    defaults = profile.get("defaults", {})
    for control in profile.get("controls", []):
        name = control["name"]
        raw = values.get(name, control.get("default", defaults.get(name)))
        if raw is None:
            continue
        default = control.get("default")
        try:
            if name == "seed" or (isinstance(default, int) and not isinstance(default, bool)):
                value = int(float(raw))
            elif isinstance(default, float):
                value = float(raw)
            else:
                value = raw
        except (TypeError, ValueError):
            value = raw
        if name == "seed" and isinstance(value, int) and value < 0:
            value = int.from_bytes(os.urandom(6), "big")
        for node_id, input_name in control.get("targets", []):
            set_node_input(graph, node_id, input_name, value)
    return graph


# ───────────────────────────────────────────── job

class Cancelled(Exception):
    pass


class Job:
    def __init__(self, site, data):
        self.site = site
        self.uid = data["uid"]
        self.kind = data["kind"]
        self.payload = data.get("payload") or {}
        self.timeout_s = int(data.get("timeout_s") or 1800)
        self.dir = os.path.join(WORK, self.uid)
        self.inputs = os.path.join(self.dir, "inputs")
        self.outputs = os.path.join(self.dir, "outputs")
        self.cancelled = False

    def out(self, name):
        os.makedirs(self.outputs, exist_ok=True)
        return os.path.join(self.outputs, os.path.basename(name))

    def input_path(self, name):
        if not name:
            return None
        p = os.path.join(self.inputs, os.path.basename(name))
        return p if os.path.isfile(p) else None

    def input_bytes(self, name):
        p = self.input_path(name)
        if not p:
            raise RuntimeError("input file '%s' is not in the job package" % name)
        return open(p, "rb").read()

    def progress(self, fraction, message=""):
        try:
            r = self.site.post("/api/v1/compute/jobs/%s/progress/" % self.uid, {"progress": fraction, "message": message})
            if isinstance(r, dict) and r.get("cancel"):
                self.cancelled = True
        except SiteError as e:
            warn("progress report failed: %s" % e)
        if self.cancelled:
            raise Cancelled()

    def fetch(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.inputs, exist_ok=True)
        os.makedirs(self.outputs, exist_ok=True)
        pkg = os.path.join(self.dir, "package.zip")
        self.site.download("/api/v1/compute/jobs/%s/package/" % self.uid, pkg)
        with zipfile.ZipFile(pkg) as z:
            for member in z.namelist():
                if member.startswith("inputs/") and not member.endswith("/"):
                    with z.open(member) as src, open(os.path.join(self.inputs, os.path.basename(member)), "wb") as dst:
                        shutil.copyfileobj(src, dst)
            try:
                meta = json.loads(z.read("payload.json").decode("utf-8"))
                self.payload = meta.get("payload") or self.payload
                self.timeout_s = int(meta.get("timeout_s") or self.timeout_s)
            except (KeyError, ValueError):
                pass

    def upload_outputs(self):
        names = sorted(os.listdir(self.outputs)) if os.path.isdir(self.outputs) else []
        for i in range(0, len(names), 4):
            files = {}
            for name in names[i:i + 4]:
                files["file_" + name] = (name, open(os.path.join(self.outputs, name), "rb").read())
            self.site.upload("/api/v1/compute/jobs/%s/upload/" % self.uid, files)
        return names

    def finish(self, ok, err="", meta=None):
        self.site.post("/api/v1/compute/jobs/%s/finish/" % self.uid,
                       {"ok": ok, "error": err[:4000], "meta": meta or {}}, timeout=120)


# ───────────────────────────────────────────── handlers

def h_echo(job):
    time.sleep(min(30, float(job.payload.get("sleep", 1) or 0)))
    with open(job.out("echo.json"), "w", encoding="utf-8") as fh:
        json.dump({"node": CONFIG["name"], "payload": job.payload, "inputs": sorted(os.listdir(job.inputs))}, fh,
                  ensure_ascii=False, indent=2)
    return {"primary": "echo.json"}


def h_comfy_graph(job):
    graph = job.payload.get("graph")
    if not isinstance(graph, dict):
        raise RuntimeError("payload.graph is missing")
    for name in job.payload.get("uploads") or sorted(os.listdir(job.inputs)):
        comfy_upload(name, job.input_bytes(name))
    job.progress(0.03, "inputs uploaded to ComfyUI")
    _saved, primary = comfy_run(graph, job)
    return {"primary": primary, "engine": "comfyui"}


def h_comfy_profile(job):
    p = job.payload
    pid = p.get("profile") or p.get("profile_id") or ""
    profiles = load_profiles()
    profile = next((x for x in profiles if x["id"] == pid), None)
    if not profile:
        kind = p.get("kind", "image")
        profile = next((x for x in profiles if x["kind"] == kind), None)
    if not profile:
        raise RuntimeError("profile '%s' not found in %s" % (pid, os.path.join(BRIDGE_DIR, "profiles.json")))
    prompt = str(p.get("prompt", "")).strip()
    if not prompt:
        raise RuntimeError("prompt is empty")
    image_name = None
    img = p.get("image") or (p.get("files") or {}).get("image")
    if profile["kind"] in ("edit", "video") and not (img and job.input_path(img)):
        raise RuntimeError("image editing and video need a reference image")
    if img and job.input_path(img):
        image_name = comfy_upload("nm_%s_%s" % (job.uid[:8], os.path.basename(img)), job.input_bytes(img))
    graph = apply_profile(profile, prompt, p.get("negative_prompt"), image_name, dict(p.get("controls") or {}))
    job.progress(0.03, "profile %s" % profile["id"])
    _saved, primary = comfy_run(graph, job)
    return {"primary": primary, "engine": "comfyui", "profile": profile["id"]}


def _relay(job, service, method, path, body=None, files=None, headers=None, out_name=None, timeout=1800):
    """Request to a local service; JSON answer -> .json output file, binary answer -> file named out_name."""
    url = service_url(service) + path
    data = body
    h = dict(headers or {})
    if files:
        fs = {field: (os.path.basename(name), job.input_bytes(name)) for field, name in files.items()}
        fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)) for k, v in (body or {}).items()}
        data, ctype = multipart(fields, fs)
        h["Content-Type"] = ctype
    try:
        payload, rh = http(method, url, data, h, timeout=timeout, raw=True)
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s -> HTTP %s %s" % (path, e.code, e.read()[:400].decode("utf-8", "replace")))
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError("%s service is not reachable at %s: %s" % (service, service_url(service), e))
    ctype = (rh.get("Content-Type") or "").lower()
    if "json" in ctype:
        obj = json.loads(payload.decode("utf-8")) if payload else {}
        name = out_name or "result.json"
        with open(job.out(name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        return obj, name
    ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ".bin"
    ext = {".jpe": ".jpg", ".x-wav": ".wav"}.get(ext, ext)
    name = out_name or ("result" + ext)
    with open(job.out(name), "wb") as fh:
        fh.write(payload)
    return None, name


def h_photo_edit(job):
    p = job.payload
    img = p.get("image") or (p.get("files") or {}).get("image")
    if not img or not job.input_path(img):
        raise RuntimeError("input image (image) is required")
    fields = {}
    if p.get("recipe"):
        fields["recipe"] = p["recipe"]
    q = "?auto=1" if p.get("auto") else ""
    stem = os.path.splitext(os.path.basename(img))[0]
    fmt = ((p.get("recipe") or {}).get("output") or {}).get("format") or "jpeg"
    ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp"}.get(str(fmt).lower(), ".jpg")
    _obj, name = _relay(job, "photo", "POST", "/api/edit" + q, fields, {"file": img}, out_name=stem + "-edited" + ext)
    return {"primary": name, "engine": "photo"}


def h_photo_analyze(job):
    img = job.payload.get("image") or (job.payload.get("files") or {}).get("image")
    if not img:
        raise RuntimeError("input image (image) is required")
    _obj, name = _relay(job, "photo", "POST", "/api/analyze", {}, {"file": img}, out_name="analyze.json")
    return {"primary": name, "engine": "photo"}


def h_video_edit(job):
    p = job.payload
    vid = p.get("video") or (p.get("files") or {}).get("video")
    if not vid or not job.input_path(vid):
        raise RuntimeError("input video (video) is required")
    base = service_url("video")
    body, ctype = multipart({}, {"file": (os.path.basename(vid), job.input_bytes(vid))})
    created = http("POST", base + "/api/videos?" + urllib.parse.urlencode({"name": os.path.basename(vid)}), body,
                   {"Content-Type": ctype}, timeout=600)
    vid_id = created.get("id") if isinstance(created, dict) else None
    if not vid_id:
        raise RuntimeError("video editor did not accept the file: %s" % str(created)[:300])
    job.progress(0.1, "file handed to the video editor")
    if p.get("auto"):
        auto = http("POST", base + "/api/videos/%s/auto" % vid_id, {}, timeout=600)
        recipe = (auto or {}).get("recipe") if isinstance(auto, dict) else None
    else:
        recipe = p.get("recipe")
    exp = http("POST", base + "/api/videos/%s/export" % vid_id,
               json.dumps(recipe or {}, ensure_ascii=False).encode("utf-8"), {"Content-Type": "application/json"}, timeout=120)
    job_id = ((exp or {}).get("id") or (exp or {}).get("jobId")) if isinstance(exp, dict) else None
    if not job_id:
        raise RuntimeError("export did not start: %s" % str(exp)[:300])
    deadline = time.time() + job.timeout_s
    while time.time() < deadline:
        if job.cancelled:
            try:
                http("DELETE", base + "/api/jobs/%s" % job_id, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            raise Cancelled()
        j = http("GET", base + "/api/jobs/%s" % job_id, timeout=30)
        state = (j or {}).get("state") if isinstance(j, dict) else None
        if state == "done":
            data, _rh = http("GET", base + "/api/jobs/%s/file" % job_id, timeout=1800, raw=True)
            fname = j.get("fileName") or j.get("file_name") or "output.mp4"
            with open(job.out(fname), "wb") as fh:
                fh.write(data)
            with open(job.out("recipe.json"), "w", encoding="utf-8") as fh:
                json.dump(recipe or {}, fh, ensure_ascii=False, indent=2)
            return {"primary": os.path.basename(fname), "engine": "video"}
        if state in ("failed", "error", "cancelled"):
            raise RuntimeError("video editor: %s" % (j.get("error") or state))
        prog = j.get("progress") if isinstance(j, dict) else None
        try:
            job.progress(0.1 + 0.85 * float(prog or 0), "video export")
        except (TypeError, ValueError):
            job.progress(0.5, "video export")
        time.sleep(3)
    raise RuntimeError("video editor did not finish in time")


def h_voice_tts(job):
    p = job.payload
    text = str(p.get("text", "")).strip()
    if not text:
        raise RuntimeError("text is empty")
    body = {"text": text}
    for k in ("voice", "engine", "speed", "seed"):
        if p.get(k) not in (None, ""):
            body[k] = str(p[k])
    _obj, name = _relay(job, "voice", "POST", "/api/voice/tts", body, out_name=p.get("out") or "speech.wav", timeout=600)
    return {"primary": name, "engine": "voice"}


def h_voice_asr(job):
    p = job.payload
    aud = p.get("audio") or (p.get("files") or {}).get("audio")
    if not aud or not job.input_path(aud):
        raise RuntimeError("audio file (audio) is required")
    q = {}
    for k in ("phrases", "strict"):
        if p.get(k):
            q[k] = "|".join(p[k]) if isinstance(p[k], list) else str(p[k])
    path = "/api/asr" + ("?" + urllib.parse.urlencode(q) if q else "")
    _obj, name = _relay(job, "voice", "POST", path, {}, {"file": aud}, out_name="asr.json", timeout=600)
    return {"primary": name, "engine": "voice"}


def h_ollama(job):
    import base64

    p = dict(job.payload)
    path = p.pop("path", None) or ("/api/chat" if "messages" in p else "/api/generate")
    p.setdefault("stream", False)

    def fix_images(obj):  # images may be input file names -> base64
        if isinstance(obj, dict):
            if isinstance(obj.get("images"), list):
                obj["images"] = [base64.b64encode(job.input_bytes(x)).decode() if job.input_path(x) else x for x in obj["images"]]
            for v in obj.values():
                fix_images(v)
        elif isinstance(obj, list):
            for v in obj:
                fix_images(v)

    fix_images(p)
    _obj, name = _relay(job, "ollama", "POST", path, p, out_name="ollama.json", timeout=job.timeout_s)
    return {"primary": name, "engine": "ollama"}


def h_relay(job):
    service = job.kind.split(".", 1)[0]
    if service == "comfy":
        service = "comfyui"
    p = job.payload
    body = p.get("json") if p.get("json") is not None else p.get("form")
    _obj, name = _relay(job, service, (p.get("method") or "POST").upper(), p.get("path") or "/", body,
                        p.get("files") or None, out_name=p.get("out"), timeout=job.timeout_s)
    return {"primary": name, "engine": service}


HANDLERS = {
    "echo": h_echo,
    "comfy.graph": h_comfy_graph,
    "comfy.profile": h_comfy_profile,
    "photo.edit": h_photo_edit,
    "photo.analyze": h_photo_analyze,
    "video.edit": h_video_edit,
    "voice.tts": h_voice_tts,
    "voice.asr": h_voice_asr,
    "ollama.chat": h_ollama,
    "ollama.generate": h_ollama,
}


def run_job(site, data):
    job = Job(site, data)
    t0 = time.time()
    log("job %s (%s) claimed" % (job.uid[:8], job.kind))
    try:
        job.fetch()
        job.progress(0.01, "started on " + CONFIG["name"])
        handler = HANDLERS.get(job.kind) or (h_relay if job.kind.endswith(".http") else None)
        if handler is None:
            raise RuntimeError("this node does not know job kind '%s'" % job.kind)
        meta = handler(job) or {}
        names = job.upload_outputs()
        meta.update({"node": CONFIG["name"], "seconds": round(time.time() - t0, 1), "files": names})
        job.finish(True, meta=meta)
        log("job %s done (%ss, %d file(s))" % (job.uid[:8], meta["seconds"], len(names)))
        if not os.environ.get("NM_KEEP_WORK"):
            shutil.rmtree(job.dir, ignore_errors=True)
    except Cancelled:
        log("job %s cancelled" % job.uid[:8])
        try:
            job.finish(False, "cancelled", {"retryable": False})
        except SiteError as e:
            error("could not report the cancelled job: %s" % e)
    except Exception as e:  # noqa: BLE001
        err = "%s: %s" % (type(e).__name__, e)
        error("job %s (%s) failed: %s" % (job.uid[:8], job.kind, err))
        log(traceback.format_exc()[-1500:], "DEBUG")
        try:
            job.finish(False, err, {"node": CONFIG["name"]})
        except SiteError as e2:
            error("could not report the failed job: %s" % e2)
    finally:
        SITE_LOG.flush(force=True)


# ───────────────────────────────────────────── main loop

CONFIG = {}


def main():
    global CONFIG
    CONFIG = load_config(interactive="--print-config" not in sys.argv and "--check" not in sys.argv)
    if "--print-config" in sys.argv:
        print("NM_SITE=%s\nNM_TOKEN=%s\nNM_NODE=%s" % (CONFIG["site"], CONFIG["token"], CONFIG["name"]))
        return 0
    if "--check" in sys.argv:
        return check(CONFIG)
    if not CONFIG["site"] or not CONFIG["token"]:
        error("this computer is not enrolled yet. Run START.bat and paste the enrollment key shown in the panel "
              "(Tools > Processing servers > Register a new server); the site URL is read from site.json.")
        return 2
    os.makedirs(WORK, exist_ok=True)
    site = Site(CONFIG["site"], CONFIG["token"])
    SITE_LOG.site = site
    caps = Capabilities(CONFIG["name"], CONFIG["slots"])
    log("processing node '%s' v%s -> %s" % (CONFIG["name"], VERSION, CONFIG["site"]))
    running = []
    last_hb = 0
    last_full = 0
    backoff = 5
    announced = False
    while True:
        running = [t for t in running if t.is_alive()]
        try:
            now = time.time()
            if now - last_hb > 20:
                c = caps.probe()
                full = caps.changed() or now - last_full > 300
                r = site.post("/api/v1/compute/heartbeat/", c if full else {})
                if full:
                    last_full = now
                    on = [k for k in SERVICES if c.get(k)]
                    log("heartbeat ok (%s) - services up: %s - GPU: %s" % (
                        r.get("name", "?"), ", ".join(on) or "none", c.get("gpu", "-")))
                    if not c.get("comfyui"):
                        warn("ComfyUI is not running at %s - image/video jobs cannot be processed on this node" % service_url("comfyui"))
                    if not announced:
                        SITE_LOG.add("INFO", "agent v%s started on %s (%s); services: %s; GPU: %s" % (
                            VERSION, socket.gethostname(), platform.platform(), ", ".join(on) or "none", c.get("gpu", "-")))
                        announced = True
                last_hb = now
                SITE_LOG.flush()
            if len(running) < CONFIG["slots"]:
                r = site.post("/api/v1/compute/claim/", {})
                job = r.get("job") if isinstance(r, dict) else None
                if job:
                    t = threading.Thread(target=run_job, args=(site, job), daemon=True)
                    t.start()
                    running.append(t)
                    last_hb = 0
                    backoff = 5
                    continue
            backoff = 5
        except SiteError as e:
            warn("%s - retrying in %ss" % (e, backoff))
            time.sleep(backoff)
            backoff = min(60, backoff * 2)
            continue
        except Exception as e:  # noqa: BLE001
            error("main loop error: %s" % e)
            log(traceback.format_exc()[-800:], "DEBUG")
        time.sleep(3)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print()
