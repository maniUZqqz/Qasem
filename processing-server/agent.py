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
                  {auto: true} the kit's automatic edit; {goal: "..."} smart edit by the vision model (Ollama)
  video.edit      video recipe/export (PersianAiKit.Video :5680)
  voice.tts       text to speech (PersianAiKit.Voice :5600)      voice.asr       speech to text
                  natural / cloned voice: {voice, clone|strict: true} -> /api/voice/tts, never a Piper fallback;
                  {restore: {...}} + clips: rebuild the voice first when this node does not have it (VOICE_MISSING)
  voice.clone     build a cloned voice from read sentences + the owner's consent (/api/voice/clone + /clone/clip);
                  the Python voice service (Setup-Voice.bat) is installed automatically the first time
                  (NM_VOICE_AUTOSETUP=0 turns that off)
                  engine "moss-fa": MOSS-TTS-Realtime + Persian LoRA on the GPU (commercial use allowed); the voice comes
                  from a reference clip: {voice: "mana"|"arash"|... (kit voices) | reference: <input wav>}; strict, no fallback
  voice.sfx       ambience / sound effect from an English description (MOSS-SoundEffect v2.0): {prompt, seconds<=30}
  voice.music     instrumental background music (ACE-Step 1.5): {prompt, seconds, bpm?}
  node.bench      benchmark one voice model: {model: speech|clone|sfx|music} -> load / generation time, real-time
                  factor, peak VRAM / RAM, GPU use and the audio (bench.json + bench.wav)
  node.models     {action: "download", packages: [...]} -> runs Download-Models in the background (progress in the panel)

Start-up (agent 1.8): a checklist (Python, git, site, ffmpeg, .NET 8 + NuGet or the prebuilt kit, ComfyUI, GPU,
models) is printed and sent to the panel; editors that are not built and models that are missing are prepared in the
background while the node already takes jobs. Each voice model can be switched off from the panel
(desired["audio"] = {speech, clone, sfx, music: bool, idle_min}).
                  The three GPU audio engines run in their own venvs (Download-Models.bat installs them) and are started
                  on demand; with auto-switch ComfyUI / Ollama memory is freed first, and an idle engine stops after
                  NM_AUDIO_IDLE_S seconds (default 900) so the GPU is free for video again.
  ollama.chat     text/vision with Ollama (:11434) — payload is the /api/chat or /api/generate body
  *.http          generic relay to that service: {method, path, json|form, files:{field: input name}}
  node.update     update this folder's code from the site (update.py) and restart when idle

Agent 2.0 - code and data apart: this folder is only code. Models, Python environments, the editors (with your cloned
voices), node.json, services.json and the logs live in ONE data folder that every new copy of the code finds again
(nm_data.py: %USERPROFILE%\\NMarketing-data unless chosen otherwise). The first start moves the downloads of older
copies there instead of downloading them again. Update.bat (update.py) refreshes the code in place from the site;
a running node notices new code and restarts by itself when idle.
    python agent.py --prepare   data folder + moving older copies' downloads + registration (START.bat does this)
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

VERSION = "2.0"
HERE = os.path.dirname(os.path.abspath(__file__))                 # the code (replaced by every update)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import nm_data  # noqa: E402

DATA = nm_data.data_root(HERE)                                     # models, venvs, node.json ... (survives updates)
WORK = os.path.join(DATA, "work")
LOGS = os.path.join(DATA, "logs")
BRIDGE_DIR = os.path.join(HERE, "upmarket_comfyui_flask")


def kit_dir(*parts):
    """The PersianAiKit editors run from the data folder: their builds, models, Python env and recordings stay there."""
    return os.path.join(DATA, "tools", "PersianAiKit", *parts)


def resolve_here(rel):
    """A relative path of services.json: the data folder first (venvs, the kit), then the code folder."""
    for base in (DATA, HERE):
        cand = os.path.join(base, rel)
        if os.path.exists(cand):
            return cand
    return None

SERVICES = {
    "comfyui": ("NM_COMFYUI_URL", "http://127.0.0.1:8188"),
    "comfy_bridge": ("NM_BRIDGE_URL", "http://127.0.0.1:5000"),
    "photo": ("NM_PHOTO_URL", "http://127.0.0.1:5670"),
    "video": ("NM_VIDEO_URL", "http://127.0.0.1:5680"),
    "voice": ("NM_VOICE_URL", "http://127.0.0.1:5600"),
    "ollama": ("NM_OLLAMA_URL", "http://127.0.0.1:11434"),
    "moss": ("NM_MOSS_URL", "http://127.0.0.1:5640"),
    "sfx": ("NM_SFX_URL", "http://127.0.0.1:5641"),
    "music": ("NM_MUSIC_URL", "http://127.0.0.1:5642"),
}

#: how to start each service on THIS machine (services.json in the data folder; created with these defaults).
#: "${NM_COMFY_BAT}" / "${NM_DATA}" expand from the environment; a relative program path is looked up in the data
#: folder first (venvs\, tools\PersianAiKit\), then in this code folder (worker-3d.bat); the working folder is the code
#: folder (audio\*.py). The audio workers find models\ and vendor\ through NM_DATA.
DEFAULT_SERVICES = {
    "ollama": {"start": "ollama serve", "url": "ollama", "ready_timeout": 60, "note": "Ollama server (models load on demand)"},
    "comfyui": {"start": "${NM_COMFY_BAT}", "url": "comfyui", "ready_timeout": 240, "note": "set NM_COMFY_BAT or put the path of run_nvidia_gpu.bat here"},
    "voice": {"start": "tools\\PersianAiKit\\Voice\\Run-Server.bat", "url": "voice", "ready_timeout": 900, "note": "PersianAiKit voice server (.NET 8; run Setup-Services.bat once)"},
    "photo": {"start": "tools\\PersianAiKit\\Photo\\Run-Server.bat --Photo:OpenBrowser=false", "url": "photo", "ready_timeout": 900, "note": "PersianAiKit photo editor (.NET 8; run Setup-Services.bat once)"},
    "video": {"start": "tools\\PersianAiKit\\Video\\Run-Server.bat --Video:OpenBrowser=false", "url": "video", "ready_timeout": 900, "note": "PersianAiKit video editor (.NET 8 + ffmpeg; run Setup-Services.bat once)"},
    "worker3d": {"start": "worker-3d.bat", "url": None, "ready_timeout": 10, "note": "Blender render worker for the 3D section"},
    "moss": {"start": "venvs\\moss-tts\\Scripts\\python.exe audio\\moss_tts_server.py --port 5640 --parent-pid ${NM_AGENT_PID}",
             "url": "moss", "ready_timeout": 120, "note": "MOSS-TTS Persian speech + cloning (GPU; Download-Models.bat)"},
    "sfx": {"start": "venvs\\moss-sfx\\Scripts\\python.exe audio\\moss_sfx_server.py --port 5641 --parent-pid ${NM_AGENT_PID}",
            "url": "sfx", "ready_timeout": 120, "note": "MOSS-SoundEffect ambience / effects (GPU; Download-Models.bat)"},
    "music": {"start": "venvs\\acestep\\Scripts\\python.exe audio\\acestep_server.py --port 5642 --parent-pid ${NM_AGENT_PID}",
              "url": "music", "ready_timeout": 1200, "note": "ACE-Step 1.5 background music (GPU; Download-Models.bat)"},
}
SERVICE_KEYS = tuple(DEFAULT_SERVICES)


COMFY_PLACEHOLDER = "${NM_COMFY_BAT}"
_COMFY_FOUND = {}


def find_comfy_start():
    """Where ComfyUI lives on this machine: NM_COMFY_BAT, else run_nvidia_gpu.bat / the desktop app in the usual folders."""
    if "cmd" in _COMFY_FOUND:
        return _COMFY_FOUND["cmd"]
    env = os.environ.get("NM_COMFY_BAT", "").strip().strip('"')
    found = env if env and os.path.isfile(env) else None
    if not found and sys.platform.startswith("win"):
        home = os.path.expanduser("~")
        deep = [home, os.path.join(home, "Desktop"), os.path.join(home, "Downloads"), os.path.join(home, "Documents"),
                os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]
        shallow = ["C:\\", "D:\\", "E:\\", "F:\\", "C:\\AI", "D:\\AI"]
        hits = []
        for root in deep:
            for depth in ("*", "*/*", "*/*/*"):
                hits += glob.glob(os.path.join(root, depth, "run_nvidia_gpu.bat"))
        for root in shallow:
            for depth in ("*", "*/*"):
                hits += glob.glob(os.path.join(root, depth, "run_nvidia_gpu.bat"))
        app = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "@comfyorgcomfyui-electron", "ComfyUI.exe")
        if os.path.isfile(app):
            hits.append(app)
        hits = sorted(set(os.path.normpath(h) for h in hits), key=lambda h: (0 if "comfy" in h.lower() else 1, len(h)))
        found = hits[0] if hits else None
    _COMFY_FOUND["cmd"] = ('"%s"' % found) if found else None
    return _COMFY_FOUND["cmd"]


def load_services_cfg():
    path = os.path.join(DATA, "services.json")
    cfg = {k: dict(v) for k, v in DEFAULT_SERVICES.items()}
    existed = os.path.isfile(path)
    if existed:
        try:
            user = json.load(open(path, encoding="utf-8"))
            for k, v in (user or {}).items():
                if k in cfg and isinstance(v, dict):
                    cfg[k].update(v)
        except (OSError, ValueError) as e:
            print("services.json could not be read (%s); using defaults" % e, flush=True)
    changed = not existed
    if (cfg["comfyui"].get("start") or "").strip() in ("", COMFY_PLACEHOLDER):
        found = find_comfy_start()
        if found:
            cfg["comfyui"]["start"] = found
            cfg["comfyui"]["note"] = "found automatically; change it here if ComfyUI lives elsewhere"
            changed = True
            print("ComfyUI found: %s (saved in services.json)" % found, flush=True)
    if changed:
        try:
            os.makedirs(DATA, exist_ok=True)
            json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except OSError:
            pass
    return cfg


def editor_published(key):
    """The PersianAiKit editor has a published build (starts in seconds); otherwise the first start builds from source."""
    kit = {"voice": "Voice", "photo": "Photo", "video": "Video"}.get(key)
    return bool(kit) and os.path.isfile(kit_dir(kit, "app", "PersianAiKit.%s.Server.exe" % kit))


KIT_DIRS = {"voice": "Voice", "photo": "Photo", "video": "Video"}
#: small per-editor packages on the site ({site}/3d/files/downloads/...), built by deploy/nm/build-kit-packages.sh
KIT_APP_PACK = {"voice": "kit-app-voice.zip", "photo": "kit-app-photo.zip", "video": "kit-app-video.zip"}


def site_base():
    for path in (os.path.join(DATA, "node.json"), os.path.join(HERE, "site.json")):
        try:
            v = json.load(open(path, encoding="utf-8")).get("site")
            if v:
                return v.rstrip("/")
        except (OSError, ValueError):
            pass
    return (os.environ.get("NM_SITE") or CONFIG.get("site") or "").rstrip("/")


def find_dotnet():
    """A .NET SDK >= 8, also when it is not on PATH (installed after this window was opened, or per-user)."""
    cands = [shutil.which("dotnet")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft"), os.path.expanduser("~")):
        if base:
            cands.append(os.path.join(base, "dotnet", "dotnet.exe" if sys.platform.startswith("win") else "dotnet"))
    cands += ["/usr/share/dotnet/dotnet", "/usr/lib/dotnet/dotnet", "/usr/bin/dotnet"]
    seen = set()
    for c in cands:
        if not c or c in seen or not os.path.isfile(c):
            continue
        seen.add(c)
        try:
            out = subprocess.run([c, "--list-sdks"], capture_output=True, text=True, timeout=30).stdout
            for line in out.splitlines():
                head = line.strip().split(".")[0]
                if head.isdigit() and int(head) >= 8:
                    return c
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def ffmpeg_ok():
    return bool(shutil.which("ffmpeg")) or os.path.isfile(kit_dir("Video", "tools", "ffmpeg", "bin", "ffmpeg.exe"))


def voice_models_ok():
    m = kit_dir("Voice", "models")
    v = os.path.join(m, "piper", "voices")
    return (os.path.isfile(os.path.join(m, "piper", "piper", "piper.exe")) and os.path.isdir(os.path.join(m, "vosk"))
            and os.path.isdir(v) and any(f.endswith(".onnx") for f in os.listdir(v)))


def download_resumable(url, dest, tick=None, attempts=10):
    """Download with HTTP Range resume: a flaky line that stops half-way continues from where it stopped."""
    part = dest + ".part"
    total = None
    last = None
    for attempt in range(1, attempts + 1):
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        headers = {"User-Agent": "nm-node/" + VERSION}
        if have:
            headers["Range"] = "bytes=%d-" % have
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                if have and r.status != 206:
                    have = 0                         # server ignored Range: start again
                cr = r.headers.get("Content-Range") or ""
                if "/" in cr:
                    total = int(cr.rsplit("/", 1)[1])
                elif r.headers.get("Content-Length"):
                    total = have + int(r.headers["Content-Length"])
                next_tick = time.time() + 30
                with open(part, "ab" if have else "wb") as fh:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        have += len(chunk)
                        if tick and time.time() > next_tick:
                            next_tick = time.time() + 30
                            tick("downloading %s: %d / %s MB" % (os.path.basename(dest), have >> 20, (total >> 20) if total else "?"))
            if total is None or have >= total:
                os.replace(part, dest)
                return dest
            last = "stopped at %d of %d bytes" % (have, total)
        except urllib.error.HTTPError as e:
            if e.code == 416 and total and have >= total:
                os.replace(part, dest)
                return dest
            if e.code in (403, 404):
                raise RuntimeError("%s -> HTTP %s" % (url, e.code))
            last = e
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            last = e
        warn("download %s: attempt %d/%d failed (%s) - resuming" % (os.path.basename(dest), attempt, attempts, last))
        time.sleep(min(30, 3 * attempt))
    raise RuntimeError("download %s failed after %d attempts: %s" % (url, attempts, last))


def fetch_pack(name, tick=None):
    """Download one package from the site and unpack only missing files into <data>/tools/PersianAiKit."""
    base = site_base()
    if not base:
        raise RuntimeError("site URL unknown (site.json)")
    kit = kit_dir()
    tmp = os.path.join(WORK, name)
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    log("fetching %s from the site" % name)
    download_resumable("%s/3d/files/downloads/%s" % (base, name), tmp, tick)
    added = 0
    with zipfile.ZipFile(tmp) as z:
        for member in z.namelist():
            if member.endswith("/") or not member.startswith("PersianAiKit/"):
                continue
            target = os.path.join(kit, *member.split("/")[1:])
            if os.path.isfile(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            added += 1
    try:
        os.remove(tmp)
    except OSError:
        pass
    log("%s: %d file(s) unpacked" % (name, added))
    return added


def run_logged(cmd, logf, tick=None, timeout=2400, label="", env=None):
    """Run a long command, write its output to logf, keep the job alive with tick(); True on exit code 0."""
    os.makedirs(os.path.dirname(logf), exist_ok=True)
    with open(logf, "w", encoding="utf-8", errors="replace") as fh:
        p = subprocess.Popen(cmd, cwd=HERE, stdout=fh, stderr=subprocess.STDOUT, env=env)
        t0 = time.time()
        while p.poll() is None:
            if time.time() - t0 > timeout:
                p.kill()
                return False
            if tick:
                tick("%s ... %ds" % (label, int(time.time() - t0)))
            for _ in range(15):
                if p.poll() is not None:
                    break
                time.sleep(2)
    return p.returncode == 0


_NUGET = {}


def nuget_reachable():
    """Can `dotnet publish` download its NuGet packages? Asked once per run (a blocked nuget.org would otherwise
    make every build wait for minutes before failing)."""
    if "ok" not in _NUGET:
        try:
            with urllib.request.urlopen(urllib.request.Request("https://api.nuget.org/v3/index.json",
                                                               headers={"User-Agent": "UpMarket-node"}), timeout=8) as r:
                _NUGET["ok"] = r.status == 200
        except Exception:  # noqa: BLE001
            _NUGET["ok"] = False
    return _NUGET["ok"]


def ensure_editor(key, tick=None):
    """Make a PersianAiKit editor runnable without any manual setup: build it with the local .NET SDK
    (the owner has one), else take the ready build from the site; then fetch what it needs (ffmpeg, voice models)."""
    kit = KIT_DIRS[key]
    root = kit_dir(kit)
    if not os.path.isdir(os.path.join(root, "src")):
        try:                                       # the kit's source comes from the code folder (first start, or new code)
            nm_data.sync_kit(DATA, HERE)
        except Exception as e:  # noqa: BLE001
            warn("could not copy the editors' source into the data folder: %s" % e)
    if not editor_published(key):
        dn = find_dotnet()
        if dn and not nuget_reachable():
            log("%s: nuget.org is not reachable - taking the ready build from the site instead of building" % key)
            dn = None
        if dn:
            proj = os.path.join(root, "src", "PersianAiKit.%s.Server" % kit, "PersianAiKit.%s.Server.csproj" % kit)
            logf = os.path.join(LOGS, "build-%s.log" % key)
            log("%s: building the editor with %s (first time only; NuGet packages are downloaded) - log: logs\\build-%s.log" % (key, dn, key))
            ok = run_logged([dn, "publish", proj, "-c", "Release", "-o", os.path.join(root, "app"), "--nologo"],
                            logf, tick, label="building the %s editor" % key)
            if ok and editor_published(key):
                log("%s editor built" % key)
            else:
                warn("%s: dotnet publish failed (last lines of logs\\build-%s.log below) - taking the ready build from the site\n%s"
                     % (key, key, "\n".join(tail_lines(logf, 8))))
        if not editor_published(key):
            fetch_pack(KIT_APP_PACK[key], tick)
        if not editor_published(key):
            raise RuntimeError("the %s editor could not be prepared (no .NET build and no site package)" % key)
    if key == "video" and not ffmpeg_ok():
        fetch_pack("kit-ffmpeg.zip", tick)
    if key == "voice" and not voice_models_ok():
        fetch_pack("kit-models-voice-min.zip", tick)
    if key == "photo" and not os.path.isfile(os.path.join(root, "models", "upscale", "realesr-general-x4v3.onnx")):
        try:
            fetch_pack("kit-models-photo.zip", tick)
        except Exception as e:  # noqa: BLE001 - optional model
            warn("photo upscaler model not fetched (%s); the editor works without it" % e)
    return True


def tail_lines(path, n=15):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 16000))
            text = fh.read().decode("utf-8", "replace")
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        return lines[-n:]
    except OSError:
        return []


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
    path = os.path.join(DATA, "node.json")
    try:
        os.makedirs(DATA, exist_ok=True)
        json.dump({"site": cfg["site"], "token": cfg["token"], "name": cfg["name"]},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        log("Saved node.json (site, token, name) in the data folder %s" % DATA)
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
    """node.json in the data folder (saved after the first run; an older layout kept it next to agent.py) >
    environment variables > site.json next to agent.py (site URL only)."""
    cfg = {}
    path = os.path.join(DATA, "node.json")
    if not os.path.isfile(path) and os.path.isfile(os.path.join(HERE, "node.json")):
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
    def ask(question):
        try:
            return input(question).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
    if interactive and sys.stdin and sys.stdin.isatty():
        if not cfg["site"]:
            cfg["site"] = ask("Site URL (e.g. http://87.107.160.17:8040): ").rstrip("/")
        if cfg["site"] and not cfg["token"] and not cfg.get("enroll_key"):
            print("This computer is not registered yet.", flush=True)
            cfg["enroll_key"] = ask("Enrollment key (panel > Processing servers > Register a new server): ")
    if cfg["site"] and not cfg["token"] and cfg.get("enroll_key"):
        try:
            enroll(cfg, cfg["enroll_key"])
        except SiteError as e:
            error(str(e))
    elif cfg["site"] and cfg["token"] and not os.path.isfile(os.path.join(DATA, "node.json")):
        save_node_json(cfg)                       # NM_TOKEN given, or node.json of an older layout: keep it in the data folder
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
            if e.code == 403 and "/jobs/" in path:
                raise JobLost("the site gave this job to another attempt: %s" % detail) from e
            if e.code in (401, 403):
                raise SiteError("site rejected the node token (HTTP %s). The token was rotated or the node was deleted: "
                                "delete node.json in the data folder (%s) and run START.bat again with the enrollment "
                                "key. %s" % (e.code, DATA, detail)) from e
            raise SiteError("%s %s -> HTTP %s %s" % (method, path, e.code, detail)) from e
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise SiteError("site unreachable (%s): %s" % (self.base, e)) from e

    def post(self, path, data=None, timeout=60):
        return self._req("POST", path, data if data is not None else {}, timeout=timeout)

    def get_json(self, path, timeout=30):
        return self._req("GET", path, timeout=timeout)

    def download(self, path, dest, timeout=600, attempts=5):
        """Streamed download with a short read timeout and a size check, retried: on a flaky line a body can stop
        half-way (seen 1405/07/27: 45 KB of 873 KB, then silence) and a single long read would hang the job."""
        last = None
        for attempt in range(1, attempts + 1):
            tmp = dest + ".part"
            try:
                req = urllib.request.Request(self.base + path, headers={"Authorization": "Node " + self.token})
                with urllib.request.urlopen(req, timeout=45) as r:
                    expected = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    with open(tmp, "wb") as fh:
                        while True:
                            chunk = r.read(256 * 1024)
                            if not chunk:
                                break
                            fh.write(chunk)
                            got += len(chunk)
                if expected and got != expected:
                    raise OSError("truncated download: %d of %d bytes" % (got, expected))
                os.replace(tmp, dest)
                if attempt > 1:
                    log("download ok on attempt %d (%d bytes)" % (attempt, got))
                return
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404):
                    raise SiteError("GET %s -> HTTP %s" % (path, e.code)) from e
                last = e
            except (urllib.error.URLError, socket.timeout, OSError) as e:
                last = e
            warn("download %s failed (attempt %d/%d): %s" % (path, attempt, attempts, last))
            time.sleep(min(30, 3 * attempt))
        raise SiteError("download failed after %d attempts: %s" % (attempts, last))

    def upload(self, path, files, timeout=1800, attempts=4):
        body, ctype = multipart({}, files)
        last = None
        for attempt in range(1, attempts + 1):
            try:
                return self._req("POST", path, body, {"Content-Type": ctype}, timeout=timeout)
            except SiteError as e:
                if "HTTP 4" in str(e):
                    raise
                last = e
                warn("upload %s failed (attempt %d/%d): %s" % (path, attempt, attempts, e))
                time.sleep(min(30, 5 * attempt))
        raise last


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
    cands = [os.environ.get("UP3D_BLENDER", ""), os.path.join(DATA, "vendor", "blender", "blender.exe"),
             os.path.join(DATA, "vendor", "blender", "blender")]
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


def memory_mb():
    """(total_mb, free_mb) of system RAM — Windows via GlobalMemoryStatusEx, Linux via /proc/meminfo."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys // 2 ** 20, m.ullAvailPhys // 2 ** 20
        info = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            info[k] = int(v.strip().split()[0])
        return info["MemTotal"] // 1024, info.get("MemAvailable", info.get("MemFree", 0)) // 1024
    except Exception:  # noqa: BLE001
        return None, None


def vram_mb():
    """(used_mb, total_mb) of the first NVIDIA GPU, via nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15).stdout.strip().splitlines()
        used, total = [int(float(x)) for x in out[0].split(",")[:2]]
        return used, total
    except Exception:  # noqa: BLE001
        return None, None


class ServiceManager:
    """Starts/stops local services on the panel's request and frees GPU memory when switching engines.

    Services the agent started itself can be stopped; a service someone else started is "external":
    for Ollama we can still unload its models, for ComfyUI we can free its VRAM, others are left alone."""

    def __init__(self):
        self.cfg = load_services_cfg()
        self.procs = {}          # key -> Popen we started
        self.warned = set()
        self.applied = None
        self.lock = threading.Lock()

    # ---- state
    def running(self, key):
        url_key = self.cfg.get(key, {}).get("url")
        if url_key:
            return listening(service_url(url_key), 0.8)
        p = self.procs.get(key)
        return bool(p and p.poll() is None)

    def startable(self, key):
        if key in AUDIO_ENGINES:
            return audio_installed(key)
        cmd = (self.cfg.get(key, {}).get("start") or "").strip()
        if not cmd:
            return False
        if "${NM_COMFY_BAT}" in cmd and not os.environ.get("NM_COMFY_BAT"):
            return False
        return True

    def startable_map(self):
        return {key: self.startable(key) for key in SERVICE_KEYS}

    def managed_map(self):
        out = {}
        for key in SERVICE_KEYS:
            p = self.procs.get(key)
            if p and p.poll() is None:
                out[key] = "agent"
            elif self.running(key):
                out[key] = "external"
            else:
                out[key] = "off"
        return out

    # ---- commands
    def _command(self, key):
        cmd = (self.cfg.get(key, {}).get("start") or "").strip()
        for var in ("NM_COMFY_BAT",):
            cmd = cmd.replace("${%s}" % var, os.environ.get(var, ""))
        cmd = cmd.replace("${NM_AGENT_PID}", str(os.getpid())).replace("${NM_DATA}", DATA)
        cmd = cmd.strip()
        if not cmd:
            return None
        first = cmd.split('"')[1] if cmd.startswith('"') else cmd.split(" ")[0]
        if first.lower().endswith((".bat", ".cmd", ".exe")) and not os.path.isabs(first):
            cand = resolve_here(first)                    # venvs\..\python.exe, tools\PersianAiKit\..: data folder
            if cand and os.path.isfile(cand):
                if cmd.startswith('"'):
                    cmd = '"%s"%s' % (cand, cmd[len(first) + 2:])
                else:
                    cmd = '"%s"%s' % (cand, cmd[len(first):])
        return cmd

    def log_path(self, key):
        return os.path.join(LOGS, "service-%s.log" % key)

    @staticmethod
    def _ps_command(cmd):
        """'"C:\\x\\Run-Server.bat" args' / 'ollama serve' -> PowerShell call operator form."""
        if cmd.startswith('"'):
            first, rest = cmd[1:].split('"', 1)
        else:
            parts = cmd.split(" ", 1)
            first, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        return "& '%s' %s" % (first.replace("'", "''"), rest.strip())

    def start(self, key, wait=True, tick=None):
        if self.running(key):
            return True
        cmd = self._command(key)
        if not cmd or (key == "comfyui" and COMFY_PLACEHOLDER in (self.cfg["comfyui"].get("start") or "")):
            if key not in self.warned:
                self.warned.add(key)
                warn("cannot start %s: no start command (edit services.json%s)" % (
                    key, ' -> "comfyui" -> "start" = path of run_nvidia_gpu.bat, or set NM_COMFY_BAT' if key == "comfyui" else ""))
            return False
        if key in KIT_DIRS:
            try:
                ensure_editor(key, tick)
            except Exception as e:  # noqa: BLE001
                error("cannot prepare the %s editor: %s" % (key, e))
                return False
        os.makedirs(LOGS, exist_ok=True)
        env = dict(os.environ, NM_DATA=DATA)              # the audio workers / worker-3d.bat find models\ vendor\ there
        if key == "photo":
            env.update(photo_ai_env(env))   # «smart edit» of the photo kit -> this node's Ollama vision model
        dn = find_dotnet() if key in KIT_DIRS else None
        if dn and not shutil.which("dotnet"):
            env["PATH"] = os.path.dirname(dn) + os.pathsep + env.get("PATH", "")
        logf = self.log_path(key)
        log("starting %s: %s  (output: logs\\%s)" % (key, cmd, os.path.basename(logf)))
        try:
            if sys.platform.startswith("win"):
                ps = "%s 2>&1 | Tee-Object -FilePath '%s'" % (self._ps_command(cmd), logf.replace("'", "''"))
                self.procs[key] = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                                                   cwd=HERE, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                self.procs[key] = subprocess.Popen("%s >> '%s' 2>&1" % (cmd, logf), cwd=HERE, shell=True, env=env,
                                                   start_new_session=True)
        except OSError as e:
            error("could not start %s: %s" % (key, e))
            return False
        if not wait:
            return True
        deadline = time.time() + int(self.cfg.get(key, {}).get("ready_timeout") or 60)
        next_note = time.time() + 60
        while time.time() < deadline:
            if self.running(key):
                log("%s is up" % key)
                return True
            p = self.procs.get(key)
            if p and p.poll() is not None and self.cfg.get(key, {}).get("url"):
                error("%s exited right after start (code %s). Last lines of logs\\%s:\n%s" % (
                    key, p.returncode, os.path.basename(logf), "\n".join(tail_lines(logf)) or "(empty)"))
                return False
            if time.time() > next_note:
                next_note = time.time() + 30
                last = tail_lines(logf, 1)
                log("still waiting for %s ... %s" % (key, (last[0][:120] if last else "")))
                if tick:
                    tick("starting %s ..." % key)
            time.sleep(2)
        warn("%s did not come up within %ss. Last lines of logs\\%s:\n%s" % (
            key, int(self.cfg.get(key, {}).get("ready_timeout") or 60), os.path.basename(logf), "\n".join(tail_lines(logf)) or "(empty)"))
        return False

    def stop(self, key):
        p = self.procs.get(key)
        if p and p.poll() is None:
            log("stopping %s (pid %s)" % (key, p.pid))
            try:
                if sys.platform.startswith("win"):
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=30)
                else:
                    import signal
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception as e:  # noqa: BLE001
                warn("stop %s failed: %s" % (key, e))
            self.procs.pop(key, None)
            return True
        if self.running(key):
            if key == "ollama":
                return self.unload_ollama()
            if key == "comfyui":
                return self.free_comfy()
            if key not in self.warned:
                self.warned.add(key)
                warn("%s was started outside the agent; it cannot be stopped from the panel (only services the agent started can)" % key)
            return False
        return True

    def unload_ollama(self):
        """Free VRAM held by Ollama models (keeps the server running)."""
        if not self.running("ollama"):
            return True
        base = service_url("ollama")
        try:
            ps = http("GET", base + "/api/ps", timeout=10)
            names = [m.get("name") for m in (ps.get("models") or []) if m.get("name")] if isinstance(ps, dict) else []
            for name in names:
                http("POST", base + "/api/generate", {"model": name, "keep_alive": 0}, timeout=60)
            if names:
                log("ollama: unloaded %s" % ", ".join(names))
            return True
        except Exception as e:  # noqa: BLE001
            warn("ollama unload failed: %s" % e)
            return False

    def free_comfy(self):
        """Ask ComfyUI to drop its models and cached memory (server keeps running)."""
        if not self.running("comfyui"):
            return True
        try:
            http("POST", service_url("comfyui") + "/free", {"unload_models": True, "free_memory": True}, timeout=60, raw=True)
            log("comfyui: models unloaded / memory freed")
            return True
        except Exception as e:  # noqa: BLE001
            warn("comfyui free failed: %s" % e)
            return False

    # ---- panel desired state
    def apply(self, desired):
        """Bring services to the panel's desired state; missing key = leave as is (node default)."""
        if not isinstance(desired, dict):
            return
        with self.lock:
            prev = self.applied or {}
            for key, want in desired.items():
                if key not in SERVICE_KEYS:
                    continue
                if want and not self.running(key):
                    self.start(key)                       # "on": keep it alive
                elif want is False and prev.get(key) != want and self.running(key):
                    self.stop(key)                        # "off": stop it when the panel switches it off
            for key in AUDIO_ENGINES:                     # a voice model switched off in the panel: free its VRAM now
                if not audio_allowed(key) and key in self.procs and self.procs[key].poll() is None:
                    log("audio: %s was switched off in the panel - stopping it" % AUDIO_ENGINES[key]["label"])
                    self.stop(key)
            self.applied = dict(desired)

    def default_boot(self, desired):
        """Node default when the panel has not decided: the 3D worker starts if Blender and the up3d folder exist."""
        if "worker3d" not in (desired or {}) and blender_path() and os.path.isdir(os.path.join(HERE, "up3d")):
            self.start("worker3d", wait=False)

    def prepare_for(self, kind, auto_switch, tick=None, payload=None):
        """Before a job: make sure its engine is up; with auto-switch also free the other engine's memory."""
        audio = audio_engine_for(kind, payload)
        if audio:
            return self.prepare_audio(audio, auto_switch, tick, purpose=audio_purpose(kind, payload))
        family = kind.split(".", 1)[0]
        need = {"comfy": "comfyui", "ollama": "ollama", "voice": "voice", "photo": "photo", "video": "video"}.get(family)
        if not need:
            return
        if auto_switch:
            if need in ("comfyui", "ollama"):
                self.stop_audio()                 # a GPU audio engine left loaded would starve ComfyUI / Ollama
            if need == "comfyui":
                self.unload_ollama()
            elif need == "ollama":
                self.free_comfy()
            if not self.running(need):
                log("auto-switch: %s job needs %s — starting it" % (kind, need))
                self.start(need, tick=tick)
        elif not self.running(need):
            raise RuntimeError("%s is not running on this node and auto-switch is off (turn it on in the panel or start the service)" % need)

    # ---- GPU audio engines (moss / sfx / music): on demand, one at a time, stopped when idle
    def prepare_audio(self, key, auto_switch, tick=None, purpose=None):
        if not audio_allowed(key, purpose):
            raise JobError(audio_disabled_message(key, purpose), retryable=False)
        if not audio_installed(key):
            pkg = AUDIO_ENGINES[key]["package"]
            if DOWNLOADS.downloading(pkg):
                raise JobError("DOWNLOADING: the models of %s are still being downloaded (%s) - the job is tried again "
                               "later | مدل‌های «%s» هنوز در حالِ دانلود است" % (
                                   AUDIO_ENGINES[key]["label"], DOWNLOADS.percent_text(), AUDIO_ENGINES[key]["label"]))
            raise JobError(audio_missing_message(key), retryable=False)
        AUDIO_USE[key] = time.time()
        if self.running(key):
            return
        others = [k for k in AUDIO_ENGINES if k != key and self.running(k)]
        if auto_switch:
            self.unload_ollama()
            self.free_comfy()
            for k in others:
                self.stop(k)
        else:
            used, total = vram_mb()
            need = AUDIO_ENGINES[key]["vram_mb"]
            if total and total - (used or 0) < need:
                raise JobError(
                    "auto-switch is off and the GPU has only %d MB free; %s needs about %d MB. Turn auto-switch on in the "
                    "panel (services of this node) or stop ComfyUI / Ollama | سوئیچِ خودکار خاموش است و حافظهٔ کارتِ "
                    "گرافیک کافی نیست؛ سوئیچِ خودکار را در پنل روشن کنید" % (total - (used or 0), AUDIO_ENGINES[key]["label"], need))
        log("audio: starting %s for this job" % AUDIO_ENGINES[key]["label"])
        if not self.start(key, tick=tick):
            raise JobError("%s did not start; last lines of logs\\service-%s.log:\n%s" % (
                AUDIO_ENGINES[key]["label"], key, "\n".join(tail_lines(self.log_path(key), 8)) or "(empty)"))

    def stop_audio(self, keep=None):
        for k in AUDIO_ENGINES:
            if k != keep and k in self.procs and self.procs[k].poll() is None and not AUDIO_BUSY.get(k):
                self.stop(k)

    def reap_audio(self, idle_s=None):
        """Stop a GPU audio engine nobody used for a while, so ComfyUI / Ollama get the VRAM back."""
        if idle_s is None:
            idle_s = os.environ.get("NM_AUDIO_IDLE_S") or 60 * float(audio_settings()["idle_min"])
        idle_s = float(idle_s)
        for k in AUDIO_ENGINES:
            p = self.procs.get(k)
            if p and p.poll() is None and not AUDIO_BUSY.get(k) and time.time() - AUDIO_USE.get(k, 0) > idle_s:
                log("audio: %s idle for %d min - stopping it to free the GPU" % (AUDIO_ENGINES[k]["label"], idle_s // 60))
                self.stop(k)


MANAGER = None
STATE = {"auto_switch": True, "desired": {}}


class Capabilities:
    def __init__(self, name, slots):
        self.name = name
        self.slots = slots
        self.cache = {}
        self.comfy_nodes = None
        self.comfy_nodes_at = 0
        self.last_hash = ""

    def probe(self):
        caps = {"agent": VERSION, "hostname": socket.gethostname(), "platform": platform.platform(), "slots": self.slots,
                "data_dir": DATA}
        try:                       # which package of the code this folder has (Update.bat writes it); none = a zip copy
            ver = json.load(open(os.path.join(HERE, ".nm-version.json"), encoding="utf-8"))
            caps["code"] = {"version": ver.get("version"), "id": str(ver.get("id") or "")[:16]}
        except (OSError, ValueError):
            pass
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
        caps["voice_clone"] = voice_clone_installed()     # natural voices + cloning (else installed on first use)
        caps["audio"] = {k: audio_installed(k) for k in AUDIO_ENGINES}   # MOSS speech / effects / music (Download-Models.bat)
        caps["models"] = DOWNLOADS.caps()                                 # per package installed / downloading (progress)
        if STATE.get("preflight"):
            caps["preflight"] = STATE["preflight"]
        total, free = memory_mb()
        if total:
            caps["ram_total_mb"], caps["ram_free_mb"] = total, free
        used, vtotal = vram_mb()
        if vtotal:
            caps["vram_used_mb"], caps["vram_total_mb"] = used, vtotal
        if MANAGER is not None:
            caps["managed"] = MANAGER.managed_map()
            caps["startable"] = MANAGER.startable_map()   # the site may route jobs here when auto-switch can start the engine
            caps["worker3d"] = MANAGER.running("worker3d")
        caps["auto_switch"] = STATE["auto_switch"]
        if caps["comfyui"]:
            if self.comfy_nodes is None or time.time() - self.comfy_nodes_at > 600:
                try:
                    info = http("GET", service_url("comfyui") + "/object_info", timeout=60)
                    self.comfy_nodes = sorted(info.keys()) if isinstance(info, dict) else []
                    self.comfy_nodes_at = time.time()
                    models = {}
                    for node_name, label in (("UpscaleModelLoader", "upscale"), ("FrameInterpolationModelLoader", "frame_interpolation"),
                                             ("CheckpointLoaderSimple", "checkpoints"), ("UNETLoader", "unet"), ("LoraLoader", "loras")):
                        req = (((info.get(node_name) or {}).get("input") or {}).get("required") or {}) if isinstance(info, dict) else {}
                        for spec in req.values():
                            if isinstance(spec, list) and spec and isinstance(spec[0], list):
                                models[label] = [str(x) for x in spec[0]][:60]
                                break
                    self.comfy_models = models
                except Exception as e:  # noqa: BLE001
                    warn("could not read ComfyUI node list (/object_info): %s" % e)
                    self.comfy_nodes = self.comfy_nodes or []
            caps["comfy_nodes"] = self.comfy_nodes
            caps["comfy_models"] = getattr(self, "comfy_models", {})
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

    print("UpMarket processing node %s - diagnostic" % VERSION)
    print("  code folder: %s" % HERE)
    print("  data folder: %s (%s)" % (DATA, nm_data.configured(HERE)[1] or "default"))
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
        if key == "comfy_bridge" and not up:
            row(None, key, "not needed (the agent applies the profiles to ComfyUI itself)")
            continue
        if key in AUDIO_ENGINES and not up:
            row(None, key, service_url(key) + " (started by the agent when a job needs it)")
            continue
        row(up if key == "comfyui" else (True if up else None), key, service_url(key) + (" (listening)" if up else " (not running; the panel can start it)"))
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
    used, vtotal = vram_mb()
    if vtotal:
        row(True, "VRAM", "%d / %d MB used" % (used, vtotal))
    total, free = memory_mb()
    if total:
        row(True, "RAM", "%d MB free of %d MB" % (free, total))
    svc = load_services_cfg()
    for key in SERVICE_KEYS:
        cmd = (svc.get(key, {}).get("start") or "")
        has = bool(cmd.strip()) and COMFY_PLACEHOLDER not in cmd
        hint = "none - the panel cannot start it (services.json)"
        if key == "comfyui" and not has:
            hint = "ComfyUI not found: write the path of run_nvidia_gpu.bat in services.json -> comfyui -> start"
        row(True if has else None, "start cmd: " + key, cmd if has else hint)
    # ---- the PersianAiKit editors: .NET, published builds, ffmpeg, models (Setup-Services.bat does all of it)
    sdk = None
    try:
        out = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True, timeout=20).stdout
        vers = [ln.split()[0] for ln in out.splitlines() if ln.strip() and ln[0].isdigit()]
        sdk = max((v for v in vers if int(v.split(".")[0]) >= 8), default=None)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    row(True, ".NET SDK (optional)", sdk or "not needed - Setup-Services.bat downloads the ready editors from the site")
    for key, kit in (("photo", "Photo"), ("video", "Video"), ("voice", "Voice")):
        pub = editor_published(key)
        row(True if pub else None, "  %s editor build" % key,
            "published (starts in seconds)" if pub else "not prepared - run Setup-Services.bat once (downloads it from the site)")
    kit_ff = kit_dir("Video", "tools", "ffmpeg", "bin", "ffmpeg.exe")
    ff = shutil.which("ffmpeg") or (kit_ff if os.path.isfile(kit_ff) else None)
    row(True if ff else None, "  ffmpeg (video editor)", ff or "not found - Setup-Services.bat brings it from the site")
    vm = kit_dir("Voice", "models")
    have_voice = os.path.isfile(os.path.join(vm, "piper", "piper", "piper.exe")) and os.path.isdir(os.path.join(vm, "vosk"))
    row(True if have_voice else None, "  voice models", vm if have_voice else "Piper/Vosk missing - Setup-Services.bat brings them from the site (text-to-speech needs them)")
    vc_ok = voice_clone_installed()
    for key, eng in AUDIO_ENGINES.items():
        miss = audio_missing(key)
        row(True if not miss else None, "  %s" % eng["label"][:26],
            "installed (venvs\\%s)" % eng["venv"] if not miss else
            "not installed - Download-Models.bat --only %s (about %s GB)" % (eng["package"], eng["gb"]))
    row(True if vc_ok else None, "  voice cloning service",
        "installed (voice\\.venv + Pocket-TTS)" if vc_ok else
        "not installed - the first voice.clone job installs it (~0.7 GB), or run Setup-Voice.bat in %s" % kit_dir("Voice"))
    pm = kit_dir("Photo", "models", "upscale", "realesr-general-x4v3.onnx")
    row(True if os.path.isfile(pm) else None, "  photo models", pm if os.path.isfile(pm) else "upscaler missing (optional) - Setup-Services.bat downloads it")
    bl = blender_path()
    row(True if bl else None, "Blender (3D worker)", bl or "not found: install Blender 4.5 or let worker-3d.bat download it")
    for d in ("up3d", "engine", "assets"):
        row(os.path.isdir(os.path.join(HERE, d)), "  3D folder " + d, os.path.join(HERE, d))
    try:
        free = shutil.disk_usage(DATA if os.path.isdir(DATA) else HERE).free // (1024 ** 3)
        row(free > 5, "free disk (data folder)", "%d GB" % free)
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

class JobLost(Exception):
    """The site re-queued this job (lease expired) - our result for it is no longer wanted."""


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
        self.progress(0.01, "downloading inputs")
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


# ───────────────────────────────────────────── voice service (natural voices, cloning)

class JobError(RuntimeError):
    """A failure meant for the panel. retryable=False: the site should not hand the same job out again."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class VoiceMissing(JobError):
    """The kit does not have the voice the job names (built on another node, or its folder was wiped)."""

    def __init__(self, message):
        super().__init__(message, retryable=False)


VOICE_ROOT = kit_dir("Voice")
VOICE_GATEWAY_PORT = int(os.environ.get("NM_VOICE_GATEWAY_PORT") or 5620)
VOICE_SETUP_HINT = (
    "VOICE_SETUP: the natural-voice / voice-cloning service of PersianAiKit is not installed on this node. "
    "Run Setup-Voice.bat once (in the data folder: %s; Python 3.10-3.13 x64), then restart START.bat. | "
    "سرویسِ صدای طبیعی و کلونِ صدا روی این سرورِ پردازش نصب نیست: یک بار "
    "Setup-Voice.bat را در %s اجرا کنید (پایتونِ ۳٫۱۰ تا ۳٫۱۳) و START.bat را دوباره باز کنید." % (VOICE_ROOT, VOICE_ROOT)
)
_VOICE_LOCK = threading.Lock()
_VOICE_GATEWAY = {}


def voice_venv_python():
    sub = ("Scripts", "python.exe") if sys.platform.startswith("win") else ("bin", "python")
    return os.path.join(VOICE_ROOT, "voice", ".venv", *sub)


def pocket_model_ok():
    return os.path.isfile(os.path.join(VOICE_ROOT, "models", "tts", "pocket-fa", "flow_lm_step.onnx.data"))


def voice_clone_installed():
    return os.path.isfile(voice_venv_python()) and pocket_model_ok()


def kit_request(method, path, data=None, headers=None, timeout=600):
    """Request to the local voice kit -> (status, body, headers). HTTP errors are returned, not raised."""
    h = {"Accept": "application/json, */*"}
    body = None
    if isinstance(data, (dict, list)):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        h["Content-Type"] = "application/json; charset=utf-8"
    elif data is not None:
        body = data
    h.update(headers or {})
    req = urllib.request.Request(service_url("voice") + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise JobError("voice service is not reachable at %s: %s" % (service_url("voice"), e))


def kit_error(status, body):
    """The kit's {"error": "..."} (Persian) with the status."""
    try:
        msg = json.loads(body.decode("utf-8")).get("error")
    except (ValueError, UnicodeDecodeError, AttributeError):
        msg = None
    return "%s (HTTP %s)" % (msg or (body or b"")[:300].decode("utf-8", "replace").strip() or "no message", status)


def voice_engines():
    """(voice service up?, Pocket-TTS ready?, error) as the kit sees it."""
    try:
        status, body, _h = kit_request("GET", "/api/voice/engines", timeout=20)
    except JobError as e:
        return False, False, str(e)
    if status != 200:
        return False, False, kit_error(status, body)
    try:
        r = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False, False, "unreadable answer from /api/voice/engines"
    pocket = any(isinstance(e, dict) and e.get("id") == "pocket" and e.get("available") for e in r.get("engines") or [])
    return bool(r.get("gateway")), pocket, r.get("error") or ""


def setup_voice_service(tick=None):
    """First use on a node: what Setup-Voice.bat does, limited to what speech and cloning need (the voice venv, the
    Python packages, the Pocket-TTS model ~490 MB). NM_VOICE_AUTOSETUP=0 turns it off. JobError says what to do
    by hand when it cannot. Interrupted downloads resume on the next try."""
    if os.environ.get("NM_VOICE_AUTOSETUP", "1").strip() == "0":
        raise JobError(VOICE_SETUP_HINT + " (automatic setup is off: NM_VOICE_AUTOSETUP=0)", retryable=False)
    if not ((3, 10) <= sys.version_info[:2] <= (3, 13)):
        raise JobError(VOICE_SETUP_HINT + " (this agent runs on Python %d.%d; the voice service needs 3.10-3.13)"
                       % sys.version_info[:2], retryable=False)
    req = os.path.join(VOICE_ROOT, "voice", "requirements.txt")
    dl = os.path.join(VOICE_ROOT, "tools", "download_voice_models.py")
    if not (os.path.isfile(req) and os.path.isfile(dl) and os.path.isfile(os.path.join(VOICE_ROOT, "voice", "gateway.py"))):
        raise JobError(VOICE_SETUP_HINT + " (voice kit files are missing: update the processing folder with Update.bat "
                       "or git pull)", retryable=False)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    log("voice: installing the natural-voice / cloning service on this node (first time only, about 0.7 GB) "
        "- logs\\setup-voice-*.log")
    py = voice_venv_python()
    if not os.path.isfile(py):
        logf = os.path.join(LOGS, "setup-voice-venv.log")
        ok = run_logged([sys.executable, "-m", "venv", os.path.join(VOICE_ROOT, "voice", ".venv")], logf, tick,
                        timeout=900, label="voice: creating the Python environment", env=env)
        if not ok or not os.path.isfile(py):
            raise JobError(VOICE_SETUP_HINT + " (python -m venv failed:\n%s)" % "\n".join(tail_lines(logf, 6)))
    pip = [py, "-m", "pip", "install", "--disable-pip-version-check", "--retries", "10", "--timeout", "60"]
    logf = os.path.join(LOGS, "setup-voice-packages.log")
    if not run_logged(pip + ["-r", req], logf, tick, timeout=3600, label="voice: installing Python packages", env=env):
        warn("voice: voice\\requirements.txt did not fully install (last lines below); installing only what speech and "
             "cloning need - sound effects stay off until Setup-Voice.bat\n%s" % "\n".join(tail_lines(logf, 6)))
        logf = os.path.join(LOGS, "setup-voice-packages-core.log")
        if not run_logged(pip + ["numpy>=1.24", "onnxruntime>=1.18", "sentencepiece>=0.2"], logf, tick, timeout=3600,
                          label="voice: installing core packages", env=env):
            raise JobError(VOICE_SETUP_HINT + " (pip failed:\n%s)" % "\n".join(tail_lines(logf, 6)))
    if not pocket_model_ok():
        logf = os.path.join(LOGS, "setup-voice-models.log")
        ok = run_logged([py, dl, "--only", "pocket-fa"], logf, tick, timeout=5400,
                        label="voice: downloading Pocket-TTS (490 MB)", env=env)
        if not ok or not pocket_model_ok():
            raise JobError(VOICE_SETUP_HINT + " (model download stopped; it resumes on the next try:\n%s)"
                           % "\n".join(tail_lines(logf, 6)))
    log("voice: natural-voice / cloning service installed")


def start_voice_gateway(tick=None):
    """The kit starts its Python voice service only when the kit itself starts. If this agent started the kit,
    restart it; otherwise run the service directly on the kit's address (it stops together with this agent)."""
    if MANAGER is not None:
        p = MANAGER.procs.get("voice")
        if p is not None and p.poll() is None:
            log("voice: restarting the voice editor so it starts the newly installed voice service")
            MANAGER.stop("voice")
            time.sleep(3)
            if MANAGER.start("voice", tick=tick):
                return
    p = _VOICE_GATEWAY.get("proc")
    if p is not None and p.poll() is None:
        return
    gw = os.path.join(VOICE_ROOT, "voice", "gateway.py")
    cmd = [voice_venv_python(), gw, "--port", str(VOICE_GATEWAY_PORT), "--data", os.path.join(VOICE_ROOT, "data"),
           "--models", os.path.join(VOICE_ROOT, "models"), "--parent-pid", str(os.getpid())]
    os.makedirs(LOGS, exist_ok=True)
    logf = os.path.join(LOGS, "voice-gateway.log")
    log("voice: starting the voice service on port %d (output: logs\\voice-gateway.log)" % VOICE_GATEWAY_PORT)
    try:
        fh = open(logf, "a", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
        _VOICE_GATEWAY["proc"] = subprocess.Popen(
            cmd, cwd=os.path.dirname(gw), stdout=fh, stderr=subprocess.STDOUT, creationflags=flags,
            env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
    except OSError as e:
        raise JobError(VOICE_SETUP_HINT + " (could not start the voice service: %s)" % e)


def ensure_voice_service(tick=None):
    """Natural voices and cloning need the kit's Python voice service with Pocket-TTS. Installs it the first time,
    starts it when it is down; JobError (with the manual fix) when that is not possible."""
    up, pocket, err = voice_engines()
    if up and pocket:
        return True
    with _VOICE_LOCK:
        up, pocket, err = voice_engines()
        if up and pocket:
            return True
        if "not reachable" in (err or ""):
            raise JobError("the PersianAiKit voice editor is not running on this node (%s); start it from the panel "
                           "(services of this node) or turn auto-switch on | ویرایشگرِ صدا روی این سرورِ پردازش روشن نیست" % err)
        if not voice_clone_installed():
            setup_voice_service(tick)
        if not up:
            start_voice_gateway(tick)
        deadline = time.time() + 240             # first start loads Pocket-TTS (10-20 s)
        while time.time() < deadline:
            up, pocket, err = voice_engines()
            if up and pocket:
                log("voice: natural voices / cloning ready")
                return True
            if tick:
                tick("voice: waiting for the voice service ...")
            time.sleep(3)
        extra = "\n".join(tail_lines(os.path.join(LOGS, "voice-gateway.log"), 8)) if _VOICE_GATEWAY.get("proc") else ""
        raise JobError(VOICE_SETUP_HINT + " (%s)%s" % (
            err or ("the voice service is up but the Pocket-TTS model is missing" if up else "the voice service did not come up"),
            ("\n" + extra) if extra else ""))


def _job_tick(job, fraction):
    """Keeps the site's lease on the job alive during long preparations (one progress call per 25 s)."""
    last = [0.0]

    def tick(msg):
        if time.time() - last[0] >= 25:
            last[0] = time.time()
            job.progress(fraction, str(msg)[:120])
    return tick


def _header(headers, name):
    return (headers or {}).get(name.lower())


def _kit_clone(job, name, person, purpose, clips, lo=0.15, hi=0.8, replace=""):
    """Create voice `name` in the kit from read sentences [{file, index, text}] -> (voice id, per-clip verdicts).
    An existing voice with the same id (an earlier build) is deleted first: a rebuild, not a second voice."""
    for old in [x for x in dict.fromkeys((replace, name)) if x]:
        status, body, _h = kit_request("DELETE", "/api/voice/voices/" + urllib.parse.quote(old, safe=""), timeout=60)
        if status not in (200, 404):
            warn("voice: could not delete the old voice %s: %s" % (old, kit_error(status, body)))
    status, body, _h = kit_request("POST", "/api/voice/clone",
                                   {"name": name, "person": person or "", "purpose": purpose or "", "consent": True},
                                   timeout=60)
    if status != 200:
        raise JobError("voice clone: the kit refused to create the voice: %s" % kit_error(status, body))
    vid = (json.loads(body.decode("utf-8")) or {}).get("id")
    if not vid:
        raise JobError("voice clone: the kit returned no voice id")
    results = []
    for i, c in enumerate(clips):
        q = urllib.parse.urlencode({"voice": vid, "index": int(c["index"]), "text": c.get("text") or ""})
        status, body, _h = kit_request("POST", "/api/voice/clone/clip?" + q, job.input_bytes(c["file"]),
                                       {"Content-Type": "audio/wav"}, timeout=300)
        try:
            r = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            r = {}
        if status != 200 or not isinstance(r, dict):
            r = {"ok": False, "message": (r.get("error") if isinstance(r, dict) else None) or kit_error(status, body)}
        r["index"] = int(c["index"])
        results.append(r)
        job.progress(lo + (hi - lo) * (i + 1) / max(1, len(clips)), "voice clone: clip %d/%d checked" % (i + 1, len(clips)))
    return vid, results


def _save_consent(vid, consent):
    """The owner's consent next to the recordings on this node too (VOICE-SETUP.md 6.1: consent.json)."""
    d = os.path.join(VOICE_ROOT, "data", "voices", vid)
    if os.path.isdir(d) and isinstance(consent, dict):
        try:
            with open(os.path.join(d, "consent.json"), "w", encoding="utf-8") as fh:
                json.dump(consent, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass


def h_voice_clone(job):
    """Build a cloned voice: consent + read sentences -> kit voice id, per-clip verdicts, reference and a test sentence."""
    p = job.payload
    if str(p.get("engine") or "").lower() in MOSS_ENGINES:
        return h_moss_clone(job)
    consent = p.get("consent") or {}
    if consent.get("given") is not True or not consent.get("text"):
        raise JobError("voice clone refused: the owner's consent is missing from the job", retryable=False)
    clips = [c for c in (p.get("clips") or []) if isinstance(c, dict) and job.input_path(c.get("file"))]
    if not clips:
        raise JobError("voice clone: no recordings in the job package", retryable=False)
    name = str(p.get("name") or "").strip()
    if not name:
        raise JobError("voice clone: the voice name is missing", retryable=False)
    t0 = time.time()
    job.progress(0.05, "voice clone: preparing the voice service")
    ensure_voice_service(_job_tick(job, 0.05))
    vid, results = _kit_clone(job, name, p.get("person"), p.get("purpose"), clips, replace=str(p.get("replace") or ""))
    accepted = [r for r in results if r.get("ok")]
    out = {"ready": False, "voice_id": None, "engine": "pocket", "clips": results, "accepted": len(accepted),
           "minutes": max([float(r.get("minutes") or 0) for r in accepted] or [0]), "node": CONFIG.get("name")}
    if not accepted:
        kit_request("DELETE", "/api/voice/voices/" + urllib.parse.quote(vid, safe=""), timeout=60)
        with open(job.out("clone.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        return {"primary": "clone.json", "engine": "voice:clone", "ready": False}
    _save_consent(vid, consent)
    status, body, _h = kit_request("GET", "/api/voice/voices/%s/sample" % urllib.parse.quote(vid, safe=""), timeout=60)
    if status == 200 and body:
        with open(job.out("ref.wav"), "wb") as fh:
            fh.write(body)
    job.progress(0.85, "voice clone: speaking a test sentence in the new voice")
    sample_text = str(p.get("sample_text") or "سلام! این صدای ساخته شده من است.")
    status, body, headers = kit_request("POST", "/api/voice/tts", {"text": sample_text, "voice": vid}, timeout=900)
    if status != 200:
        raise JobError("voice clone: the voice was made but speaking with it failed: %s" % kit_error(status, body))
    with open(job.out("sample.wav"), "wb") as fh:
        fh.write(body)
    try:
        check = float(_header(headers, "X-Voice-Check"))
    except (TypeError, ValueError):
        check = None
    out.update(ready=True, voice_id=vid, check=check, sample_text=sample_text, took=round(time.time() - t0, 1))
    with open(job.out("clone.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    log("voice clone: %s ready (%d of %d clips accepted, check %s)" % (vid, len(accepted), len(results), check))
    return {"primary": "clone.json", "engine": "voice:clone", "voice_id": vid, "ready": True}


def _natural_tts(job, p, text, out, setup=True):
    """Speech in a natural or cloned voice (/api/voice/tts). Rebuilds a missing cloned voice when the job carries it."""
    if setup:
        job.progress(0.05, "preparing the voice service")
        ensure_voice_service(_job_tick(job, 0.05))
    body = {"text": text}
    for k in ("voice", "engine", "seed"):
        if p.get(k) not in (None, ""):
            body[k] = str(p[k])
    restored = None
    for attempt in (1, 2):
        status, data, headers = kit_request("POST", "/api/voice/tts", body, timeout=max(600, int(job.timeout_s or 600)))
        if status == 200:
            break
        msg = kit_error(status, data)
        if status in (404, 409) and attempt == 1 and body.get("voice"):
            restore = p.get("restore")
            if not (isinstance(restore, dict) and restore.get("clips") and (restore.get("consent") or {}).get("given")):
                raise VoiceMissing("VOICE_MISSING: voice '%s' is not on this node: %s" % (body["voice"], msg))
            job.progress(0.1, "rebuilding the voice on this node from its recordings")
            clips = [c for c in restore["clips"] if isinstance(c, dict) and job.input_path(c.get("file"))]
            vid, results = _kit_clone(job, str(restore.get("name") or body["voice"]), restore.get("person"),
                                      restore.get("purpose"), clips, lo=0.1, hi=0.5)
            if not any(r.get("ok") for r in results):
                kit_request("DELETE", "/api/voice/voices/" + urllib.parse.quote(vid, safe=""), timeout=60)
                raise JobError("could not rebuild voice '%s' on this node: %s" % (
                    body["voice"], "; ".join(str(r.get("message")) for r in results)[:600]), retryable=False)
            _save_consent(vid, restore.get("consent"))
            restored = body["voice"] = vid
            continue
        if status == 503:
            raise JobError(VOICE_SETUP_HINT + " (" + msg + ")")
        raise JobError("voice: speech failed: %s" % msg, retryable=status >= 500)
    with open(job.out(out), "wb") as fh:
        fh.write(data)
    meta = {"primary": out, "engine": "voice:" + (_header(headers, "X-Voice-Engine") or "pocket")}
    try:
        meta["check"] = float(_header(headers, "X-Voice-Check"))
    except (TypeError, ValueError):
        pass
    if restored:
        meta.update(voice_id=restored, restored=True)
    return meta


# ───────────────────────────────────────────── GPU audio engines (MOSS-TTS, MOSS-SoundEffect, ACE-Step)

MOSS_ENGINES = ("moss-fa", "moss", "moss-tts")
AUDIO_ENGINES = {
    "moss": {"label": "MOSS-TTS Persian speech", "venv": "moss-tts", "package": "moss-tts", "gb": 15, "vram_mb": 9500,
             "files": ["models/moss-tts/MOSS-TTS-Realtime/model.safetensors",
                       "models/moss-tts/MOSS-Audio-Tokenizer/model-00001-of-00002.safetensors",
                       "models/moss-tts/MOSS-Audio-Tokenizer/model-00002-of-00002.safetensors",
                       "models/moss-tts/persian-lora/adapter_model.safetensors",
                       "models/moss-tts/persian-lora/fa_normalize.py",
                       "models/moss-tts/persian-lora/ref.wav",
                       "vendor/MOSS-TTS/moss_tts_realtime/inferencer.py"]},
    "sfx": {"label": "MOSS-SoundEffect ambience/effects", "venv": "moss-sfx", "package": "moss-sfx", "gb": 12, "vram_mb": 8000,
            "files": ["models/moss-sfx/MOSS-SoundEffect-v2.0/transformer/diffusion_pytorch_model.safetensors",
                      "models/moss-sfx/MOSS-SoundEffect-v2.0/text_encoder/model-00001-of-00002.safetensors",
                      "models/moss-sfx/MOSS-SoundEffect-v2.0/text_encoder/model-00002-of-00002.safetensors",
                      "models/moss-sfx/MOSS-SoundEffect-v2.0/vae/vae_128d_48k.pth",
                      "vendor/MOSS-TTS/moss_soundeffect_v2/pipeline_moss_soundeffect.py"]},
    "music": {"label": "ACE-Step background music", "venv": "acestep", "package": "acestep", "gb": 12, "vram_mb": 7000,
              "files": ["models/acestep/checkpoints/acestep-v15-turbo/model.safetensors",
                        "models/acestep/checkpoints/vae/diffusion_pytorch_model.safetensors",
                        "models/acestep/checkpoints/Qwen3-Embedding-0.6B/model.safetensors",
                        "vendor/ACE-Step-1.5/acestep/api_server.py"]},
}
AUDIO_USE = {}          # engine -> last time a job needed it (idle reaping)
AUDIO_BUSY = {}         # engine -> jobs running on it right now


AUDIO_ROWS = {"speech": "moss", "clone": "moss", "sfx": "sfx", "music": "music"}
ROW_LABEL = {"speech": "Persian speech (MOSS-TTS)", "clone": "voice cloning", "sfx": "ambience / effects (MOSS-SoundEffect)",
             "music": "background music (ACE-Step)"}
ROW_FA = {"speech": "گفتار", "clone": "کلونِ صدا", "sfx": "صدای محیط", "music": "موسیقی"}


def audio_settings():
    """The panel's switches for the voice models (desired["audio"]); missing = on, idle 15 minutes."""
    d = (STATE.get("desired") or {}).get("audio") or {}
    out = {k: d.get(k) is not False for k in AUDIO_ROWS}
    try:
        out["idle_min"] = max(1, min(240, int(d.get("idle_min") or 15)))
    except (TypeError, ValueError):
        out["idle_min"] = 15
    return out


def audio_allowed(key, purpose=None):
    s = audio_settings()
    if purpose in AUDIO_ROWS:
        return s[purpose]
    return any(s[row] for row, k in AUDIO_ROWS.items() if k == key)


def audio_purpose(kind, payload=None):
    p = payload or {}
    if kind == "voice.sfx":
        return "sfx"
    if kind == "voice.music":
        return "music"
    if kind == "voice.clone" or p.get("clone") or p.get("reference"):
        return "clone"
    return "speech"


def audio_disabled_message(key, purpose=None):
    row = purpose if purpose in AUDIO_ROWS else next((r for r, k in AUDIO_ROWS.items() if k == key), "speech")
    return ("DISABLED: %s is switched off for this node in the panel (Processing servers > voice models) | «%s» برای "
            "این سرورِ پردازش در پنل خاموش است (سرورهای پردازش › مدل‌های صدا)" % (ROW_LABEL[row], ROW_FA[row]))


def audio_engine_for(kind, payload=None):
    if kind == "voice.sfx":
        return "sfx"
    if kind == "voice.music":
        return "music"
    if kind in ("voice.tts", "voice.clone") and str((payload or {}).get("engine") or "").lower() in MOSS_ENGINES:
        return "moss"
    return None


def audio_venv_python(key):
    venv = os.path.join(DATA, "venvs", AUDIO_ENGINES[key]["venv"])
    return os.path.join(venv, "Scripts", "python.exe") if sys.platform.startswith("win") else os.path.join(venv, "bin", "python")


def audio_missing(key):
    """What Download-Models.bat still has to bring for this engine (relative paths); [] = installed."""
    eng = AUDIO_ENGINES[key]
    miss = [f for f in eng["files"] if not os.path.isfile(os.path.join(DATA, *f.split("/")))]
    py = audio_venv_python(key)
    venv = os.path.dirname(os.path.dirname(py))
    if not os.path.isfile(py) or not glob.glob(os.path.join(venv, ".nm-pip-venv-%s*.json" % eng["venv"])):
        miss.append("venvs/%s (Python packages)" % eng["venv"])
    return miss


def audio_installed(key):
    return not audio_missing(key)


def audio_missing_message(key):
    eng = AUDIO_ENGINES[key]
    miss = audio_missing(key)
    return ("MODELS_MISSING: %s is not installed on this node (missing: %s). In the processing folder run "
            "Download-Models.bat (or only this engine: Download-Models.bat --only %s, about %s GB), then restart START.bat. | "
            "مدل‌های «%s» روی این سرورِ پردازش نصب نیست. در پوشهٔ پردازش Download-Models.bat را اجرا کنید (فقط همین: "
            "Download-Models.bat --only %s، حدود %s گیگابایت) و بعد START.bat را دوباره باز کنید."
            % (eng["label"], ", ".join(miss[:3]) + (" ..." if len(miss) > 3 else ""), eng["package"], eng["gb"],
               eng["label"], eng["package"], eng["gb"]))


def audio_ready(key, job, limit=1500):
    """Wait until the engine answers /health as ready (the first load reads 5-12 GB from disk). Returns its URL."""
    url = service_url(key)
    deadline = time.time() + limit
    tick = _job_tick(job, 0.05)
    last = ""
    while time.time() < deadline:
        try:
            h = http("GET", url + "/health", timeout=15)
        except Exception as e:  # noqa: BLE001 - not listening yet
            h, last = None, str(e)[:120]
        if isinstance(h, dict):
            status = h.get("status") or ((h.get("data") or {}).get("status") if isinstance(h.get("data"), dict) else None)
            if status in ("ready", "ok"):
                return url
            if status == "error":
                raise JobError("%s could not load its model: %s (logs\\service-%s.log)" % (
                    AUDIO_ENGINES[key]["label"], h.get("error") or "?", key), retryable=False)
            last = "loading"
        tick("loading %s ..." % AUDIO_ENGINES[key]["label"])
        time.sleep(3)
    raise JobError("%s did not become ready in %d s (%s); see logs\\service-%s.log" % (
        AUDIO_ENGINES[key]["label"], limit, last, key))


def audio_run(key, url, body, timeout):
    """POST /run on one of our workers; their errors come back as JobError with the worker's words."""
    AUDIO_BUSY[key] = AUDIO_BUSY.get(key, 0) + 1
    AUDIO_USE[key] = time.time()
    try:
        return http("POST", url + "/run", body, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:  # noqa: BLE001
            msg = None
        if e.code == 507:
            raise JobError("%s ran out of GPU memory (%s). Close other GPU programs or turn auto-switch on | حافظهٔ "
                           "کارتِ گرافیک تمام شد" % (AUDIO_ENGINES[key]["label"], msg or "out of memory"))
        raise JobError("%s: %s" % (AUDIO_ENGINES[key]["label"], msg or "HTTP %s" % e.code), retryable=e.code >= 500)
    except (urllib.error.URLError, OSError) as e:
        raise JobError("%s is not reachable at %s: %s" % (AUDIO_ENGINES[key]["label"], url, e))
    finally:
        AUDIO_BUSY[key] -= 1
        AUDIO_USE[key] = time.time()


def kit_reference_voices():
    """The Persian reference voices shipped with the kit (voices.json: id, name, gender, file, licence)."""
    folder = os.path.join(VOICE_ROOT, "voice", "voices")
    try:
        rows = json.load(open(os.path.join(folder, "voices.json"), encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    out = {r["id"]: os.path.join(folder, r["file"]) for r in rows if isinstance(r, dict) and r.get("id") and r.get("file")}
    out["lora"] = os.path.join(DATA, "models", "moss-tts", "persian-lora", "ref.wav")
    return out


def moss_reference(job, p):
    """The clip whose voice MOSS speaks in: an attached reference (a shop's cloned voice) or a named kit voice."""
    ref = p.get("reference")
    if ref:
        path = job.input_path(ref)
        if not path:
            raise JobError("reference '%s' is not in the job package" % ref, retryable=False)
        return path
    voice = str(p.get("voice") or "mana").replace("preset:", "").replace("kit:", "")
    path = kit_reference_voices().get(voice)
    if not path or not os.path.isfile(path):
        raise JobError("reference voice '%s' is not on this node (tools\\PersianAiKit\\Voice\\voice\\voices); update the "
                       "processing folder with Update.bat (or git pull)" % voice, retryable=False)
    return path


def h_moss_tts(job):
    p = job.payload
    text = str(p.get("text", "")).strip()
    if not text:
        raise JobError("text is empty", retryable=False)
    out = os.path.basename(str(p.get("out") or "speech.wav"))
    ref = moss_reference(job, p)
    url = audio_ready("moss", job)
    job.progress(0.2, "MOSS-TTS: speaking")
    r = audio_run("moss", url, {"text": text, "reference": ref, "out": job.out(out), "seed": p.get("seed"),
                                "temperature": p.get("temperature", 0.8)}, timeout=max(600, int(job.timeout_s or 600)))
    if not os.path.isfile(job.out(out)):
        raise JobError("MOSS-TTS returned no audio")
    return {"primary": out, "engine": "voice:moss-fa", "seconds": (r or {}).get("seconds"),
            "voice": p.get("voice") or ("clone" if p.get("reference") else "mana"), "license": "Apache-2.0"}


def h_moss_clone(job):
    """A cloned voice for MOSS: nothing to train - the voice is the reference the site made from the accepted clips.
    The node checks it really speaks: a test sentence in the new voice, plus the reference itself."""
    p = job.payload
    consent = p.get("consent") or {}
    if consent.get("given") is not True or not consent.get("text"):
        raise JobError("voice clone refused: the owner's consent is missing from the job", retryable=False)
    ref = p.get("reference")
    ref_path = job.input_path(ref) if ref else None
    if not ref_path:
        raise JobError("voice clone (MOSS): the reference recording is missing from the job package", retryable=False)
    clips = [c for c in (p.get("clips") or []) if isinstance(c, dict)]
    url = audio_ready("moss", job)
    job.progress(0.5, "MOSS-TTS: speaking a test sentence in the new voice")
    sample_text = str(p.get("sample_text") or "سلام! این صدای ساخته شده من است.")
    t0 = time.time()
    audio_run("moss", url, {"text": sample_text, "reference": ref_path, "out": job.out("sample.wav")},
              timeout=max(600, int(job.timeout_s or 600)))
    shutil.copyfile(ref_path, job.out("ref.wav"))
    out = {"ready": True, "voice_id": str(p.get("name") or "moss-voice"), "engine": "moss-fa", "check": None,
           "sample_text": sample_text, "took": round(time.time() - t0, 1), "node": CONFIG.get("name"),
           "clips": [{"index": c.get("index"), "ok": True, "message": "در مرجعِ صدای MOSS به کار رفت" if c.get("in_reference")
                      else "پذیرفته (وارسیِ سایت)", "seconds": c.get("seconds")} for c in clips],
           "accepted": len(clips)}
    with open(job.out("clone.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return {"primary": "clone.json", "engine": "voice:moss-fa", "voice_id": out["voice_id"], "ready": True}


def h_voice_sfx(job):
    p = job.payload
    prompt = str(p.get("prompt") or "").strip()
    if not prompt:
        raise JobError("prompt (an English description of the sound) is empty", retryable=False)
    try:
        seconds = min(30.0, max(0.5, float(p.get("seconds") or 10)))
    except (TypeError, ValueError):
        raise JobError("seconds must be a number", retryable=False)
    out = os.path.basename(str(p.get("out") or "sfx.wav"))
    url = audio_ready("sfx", job)
    job.progress(0.2, "MOSS-SoundEffect: generating %.1f s" % seconds)
    r = audio_run("sfx", url, {"prompt": prompt, "seconds": seconds, "out": job.out(out), "steps": p.get("steps"),
                               "cfg_scale": p.get("cfg_scale"), "seed": p.get("seed") or 0,
                               "negative_prompt": p.get("negative_prompt") or ""}, timeout=max(600, int(job.timeout_s or 600)))
    return {"primary": out, "engine": "audio:moss-sfx", "seconds": (r or {}).get("seconds", seconds), "license": "Apache-2.0"}


def _ace(url, method, path, body=None, timeout=120):
    r = http(method, url + path, body, timeout=timeout)
    if isinstance(r, dict) and "data" in r and ("code" in r or "error" in r):
        if r.get("code") not in (None, 200) or r.get("error"):
            raise JobError("ACE-Step: %s" % (r.get("error") or "code %s" % r.get("code")))
        return r.get("data")
    return r


def h_voice_music(job):
    p = job.payload
    prompt = str(p.get("prompt") or "").strip()
    if not prompt:
        raise JobError("prompt (style of the music, in English) is empty", retryable=False)
    try:
        seconds = min(240.0, max(10.0, float(p.get("seconds") or 30)))
    except (TypeError, ValueError):
        raise JobError("seconds must be a number", retryable=False)
    out = os.path.basename(str(p.get("out") or "music.wav"))
    url = audio_ready("music", job)
    seed = p.get("seed")
    body = {"prompt": prompt, "lyrics": "[Instrumental]", "instrumental": True, "thinking": False,
            "use_cot_caption": False, "use_cot_language": False, "audio_duration": seconds,
            "inference_steps": int(p.get("steps") or 8), "batch_size": 1, "audio_format": "wav",
            "use_random_seed": seed in (None, ""), "seed": int(seed) if seed not in (None, "") else -1}
    if p.get("bpm"):
        body["bpm"] = int(p["bpm"])
    if p.get("key"):
        body["key_scale"] = str(p["key"])
    AUDIO_BUSY["music"] = AUDIO_BUSY.get("music", 0) + 1
    try:
        task = _ace(url, "POST", "/release_task", body)
        task_id = (task or {}).get("task_id") if isinstance(task, dict) else None
        if not task_id:
            raise JobError("ACE-Step did not accept the task: %s" % str(task)[:300])
        deadline = time.time() + max(600, int(job.timeout_s or 600))
        tick = _job_tick(job, 0.3)
        while time.time() < deadline:
            rows = _ace(url, "POST", "/query_result", {"task_id_list": [task_id]}) or []
            row = rows[0] if isinstance(rows, list) and rows else {}
            status = row.get("status") if isinstance(row, dict) else None
            if status == 1:
                items = row.get("result")
                items = json.loads(items) if isinstance(items, str) else (items or [])
                file_url = (items[0] or {}).get("file") if items else None
                if not file_url:
                    raise JobError("ACE-Step finished without a file: %s" % str(row)[:300])
                data = http("GET", url + file_url if file_url.startswith("/") else file_url, timeout=600)
                if not isinstance(data, (bytes, bytearray)) or len(data) < 64:
                    raise JobError("ACE-Step returned no audio file: %s" % str(data)[:300])
                with open(job.out(out), "wb") as fh:
                    fh.write(data)
                metas = (items[0] or {}).get("metas") or {}
                return {"primary": out, "engine": "audio:acestep", "seconds": metas.get("duration") or seconds,
                        "bpm": metas.get("bpm"), "license": "MIT"}
            if status == 2:
                raise JobError("ACE-Step failed: %s" % str(row.get("result") or row)[:400])
            tick("ACE-Step: composing %d s of music" % seconds)
            AUDIO_USE["music"] = time.time()
            time.sleep(2)
        raise JobError("ACE-Step did not finish in time")
    finally:
        AUDIO_BUSY["music"] -= 1
        AUDIO_USE["music"] = time.time()


# ───────────────────────────────────────────── models: the downloader in the background

DOWNLOADER = os.path.join(HERE, "download_models.py")


class DownloadManager:
    """Runs download_models.py in the background (one run at a time; more packages queue up) and tells the panel
    what is installed per package and how far a download is (logs\\download-status.json)."""

    def __init__(self):
        self.proc = None
        self.packages = None            # None = the default set
        self.queue = []
        self.status = None
        self.status_at = 0.0
        self.lock = threading.Lock()
        self.status_file = os.path.join(LOGS, "download-status.json")
        self.last_error = ""
        self.retry_at = 0.0             # a failed default download is tried again by itself (pip source down, ...)
        self.retry_s = float(os.environ.get("NM_DOWNLOAD_RETRY_S") or 3600)

    def available(self):
        return os.path.isfile(DOWNLOADER)

    def refresh(self, force=False):
        """Per package installed / missing (download_models.py --status: offline, a second or two)."""
        if not self.available():
            return None
        if not force and self.status is not None and time.time() - self.status_at < 120:
            return self.status
        try:
            out = subprocess.run([sys.executable, DOWNLOADER, "--status"], capture_output=True, text=True, timeout=180,
                                 cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.status = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else None
        except Exception as e:  # noqa: BLE001
            self.last_error = "status: %s" % e
        self.status_at = time.time()
        return self.status

    def running(self):
        if self.proc is not None and self.proc.poll() is None:
            return True
        try:   # a Download-Models.bat the owner started by hand holds the same lock
            pid = json.load(open(os.path.join(LOGS, "download.lock"), encoding="utf-8")).get("pid")
        except (OSError, ValueError):
            return False
        return bool(pid) and _pid_alive(pid)

    def progress(self):
        try:
            return json.load(open(self.status_file, encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def percent_text(self):
        pr = self.progress() or {}
        total = pr.get("bytes_total") or 0
        return "%d%%" % (100 * (pr.get("bytes_done") or 0) / total) if total else "starting"

    def downloading(self, package):
        if not self.running():
            return False
        pr = self.progress() or {}
        return self.packages is None or package in (pr.get("packages") or self.packages or [])

    def missing_default(self):
        st = self.refresh() or {}
        return [p for p, row in (st.get("packages") or {}).items() if not row.get("optional") and not row.get("installed")]

    def start(self, packages=None, reason=""):
        """Start (or queue) a background download. packages=None: the default set (everything not optional)."""
        with self.lock:
            if not self.available():
                return "missing downloader"
            if self.running():
                if packages:
                    self.queue = sorted(set(self.queue) | set(packages))
                return "queued"
            os.makedirs(LOGS, exist_ok=True)
            cmd = [sys.executable, DOWNLOADER, "--yes", "--status-file", self.status_file]
            if packages:
                cmd += ["--only", ",".join(sorted(packages))]
            logf = open(os.path.join(LOGS, "download-models-agent.log"), "a", encoding="utf-8", errors="replace")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
            try:
                self.proc = subprocess.Popen(cmd, cwd=HERE, stdout=logf, stderr=subprocess.STDOUT, creationflags=flags,
                                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
            except OSError as e:
                self.last_error = str(e)
                return "failed: %s" % e
            self.packages = list(packages) if packages else None
            log("models: downloading %s in the background%s (progress in the panel; log: logs\\download-models-agent.log)"
                % (", ".join(packages) if packages else "the default set", (" - " + reason) if reason else ""))
            return "started"

    def poll(self):
        """Called by the main loop: a finished run refreshes the status and starts what was queued."""
        if self.proc is not None and self.proc.poll() is not None:
            code = self.proc.returncode
            self.proc = None
            self.refresh(force=True)
            if code not in (0, 4):
                pr = self.progress() or {}
                self.last_error = "download ended with code %s: %s" % (code, "; ".join(
                    "%s: %s" % (f.get("id"), f.get("reason")) for f in (pr.get("failed") or [])[:3]))
                self.retry_at = time.time() + self.retry_s
                warn("models: %s - tried again in %d min (and on every START.bat)" % (self.last_error, self.retry_s // 60))
            else:
                self.retry_at = 0.0
                log("models: download finished")
            if self.queue:
                nxt, self.queue = self.queue, []
                self.start(nxt, "queued from the panel")
        elif self.proc is None and self.retry_at and time.time() > self.retry_at:
            self.retry_at = 0.0
            if self.missing_default() and not self.running():
                self.start(None, "retrying the download that failed earlier")

    def caps(self):
        st = self.status or {}
        pkgs = {p: {"installed": bool(r.get("installed")), "optional": bool(r.get("optional")), "title": r.get("title", ""),
                    "missing_mb": int((r.get("bytes_missing") or 0) // 2 ** 20), "total_mb": int((r.get("bytes_total") or 0) // 2 ** 20),
                    "in_comfyui": r.get("have_in_comfyui", 0)}
                for p, r in (st.get("packages") or {}).items()}
        out = {"packages": pkgs, "running": self.running(), "error": self.last_error[:300]}
        pr = self.progress() if out["running"] else None
        if pr:
            cur = pr.get("current") or {}
            out["progress"] = {"packages": pr.get("packages"), "bytes_done": pr.get("bytes_done"),
                               "bytes_total": pr.get("bytes_total"), "items_done": pr.get("items_done"),
                               "items_total": pr.get("items_total"), "current": cur.get("id"),
                               "current_done": cur.get("done"), "current_total": cur.get("total")}
        return out


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if sys.platform.startswith("win"):
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


DOWNLOADS = DownloadManager()


# ───────────────────────────────────────────── start-up checklist (START.bat) + background repair

def _mark(ok):
    fancy = bool(os.environ.get("WT_SESSION")) or not sys.platform.startswith("win")
    if ok is True:
        return "[✓]" if fancy else "[OK]"
    if ok is False:
        return "[✗]" if fancy else "[X ]"
    return "[..]"


def nvidia_driver():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=driver_version", "--format=csv,noheader"], capture_output=True, text=True,
                             timeout=15).stdout.strip().splitlines()
        return out[0].strip() if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def preflight(cfg, site=None, out=print):
    """Everything this node needs, checked in a few seconds; what is missing is said in one line with what happens
    next. Re-running it when all is in place changes nothing. The same rows go to the panel."""
    rows = []

    def row(key, ok, label, detail):
        rows.append({"key": key, "ok": ok, "label": label, "detail": detail})
        try:
            out("  %s %-22s %s" % (_mark(ok), label, detail))
        except UnicodeEncodeError:
            out("  %s %-22s %s" % ("[OK]" if ok else "[X ]" if ok is False else "[..]", label, detail))

    out("UpMarket processing node %s - start-up checklist" % VERSION)
    row("python", sys.version_info >= (3, 10), "Python", sys.version.split()[0])
    row("data", os.path.isdir(DATA), "data folder", "%s (models, environments, node.json; kept across updates)" % DATA)
    git = shutil.which("git")
    row("git", True if git else None, "git", "installed" if git else "not installed (not needed: Update.bat updates the "
        "code from the site, models come as zip files)")
    if site is not None:
        try:
            r = site.post("/api/v1/compute/heartbeat/", {}, timeout=15)
            row("site", True, "site + registration", "%s, node '%s'" % (cfg["site"], (r or {}).get("name") or cfg["name"]))
        except SiteError as e:
            row("site", False, "site + registration", "%s (check the internet connection; a rejected token: delete "
                "node.json in the data folder and run START.bat again)" % str(e)[:150])
    row("ffmpeg", True if ffmpeg_ok() else None, "ffmpeg", "found" if ffmpeg_ok() else "missing - fetched in the background "
        "with the video editor")
    dn = find_dotnet()
    unbuilt = [k for k in KIT_DIRS if not editor_published(k)]
    row("dotnet", True if dn else None, ".NET 8 SDK", dn or "not installed - the editors come ready-built from the site")
    if dn and unbuilt:
        ok = nuget_reachable()
        row("nuget", ok, "NuGet", "reachable" if ok else "nuget.org not reachable - the ready-built editors come from the site")
    row("editors", True if not unbuilt else None, "photo/video/voice editors",
        "built" if not unbuilt else "%s: preparing in the background (build, or the ready build from the site)" % ", ".join(unbuilt))
    comfy = find_comfy_start()
    row("comfyui", True if comfy else False, "ComfyUI", comfy.strip('"') if comfy else
        "run_nvidia_gpu.bat not found - set NM_COMFY_BAT or services.json -> comfyui -> start")
    gpus = gpu_names()
    drv = nvidia_driver()
    drv_ok = None
    try:
        drv_ok = float((drv or "0").split(".")[0]) >= 527
    except ValueError:
        pass
    row("gpu", bool(gpus) and drv_ok is not False, "GPU", ("%s, driver %s%s" % (gpus[0], drv or "?", "" if drv_ok is not False
        else " (CUDA 12 needs 527+; update the NVIDIA driver)")) if gpus else "no NVIDIA GPU found (nvidia-smi)")
    st = DOWNLOADS.refresh(force=True) if DOWNLOADS.available() else None
    if st is None:
        row("models", None, "models", "download_models.py not found (update the folder with Update.bat)")
    else:
        pk = st.get("packages") or {}
        missing = {p: r for p, r in pk.items() if not r.get("optional") and not r.get("installed")}
        optional = [p for p, r in pk.items() if r.get("optional") and not r.get("installed")]
        if missing:
            gb = sum(r.get("bytes_missing") or 0 for r in missing.values()) / 1e9
            row("models", None, "models", "%s missing (%.1f GB) - downloading in the background%s" % (
                ", ".join(sorted(missing)), gb, " (already running)" if st.get("running") else ""))
        else:
            row("models", True, "models", "all present%s" % (" (optional, from the panel: %s)" % ", ".join(sorted(optional))
                                                             if optional else ""))
        free = shutil.disk_usage(DATA if os.path.isdir(DATA) else HERE).free / 1e9
        need = sum(r.get("bytes_missing") or 0 for r in missing.values()) / 1e9
        row("disk", free > need + 2, "disk", "%.0f GB free%s" % (free, (", %.0f GB needed" % need) if need else ""))
    STATE["preflight"] = [{"key": r["key"], "ok": r["ok"], "detail": r["detail"][:200]} for r in rows]
    return rows


def background_setup():
    """After the checklist: build or fetch what is missing, then download the default models - while jobs run."""
    try:
        for key in KIT_DIRS:
            needs = not editor_published(key) or (key == "video" and not ffmpeg_ok()) or (key == "voice" and not voice_models_ok())
            if needs:
                try:
                    ensure_editor(key)
                except Exception as e:  # noqa: BLE001
                    warn("could not prepare the %s editor in the background: %s" % (key, e))
        if DOWNLOADS.available() and DOWNLOADS.missing_default() and not DOWNLOADS.running():
            DOWNLOADS.start(None, "found missing at start-up")
    except Exception as e:  # noqa: BLE001
        warn("background setup: %s" % e)


# ───────────────────────────────────────────── benchmark («تست» in the panel)

class Sampler:
    """Peak VRAM, GPU use and system RAM while a test runs (nvidia-smi every half second)."""

    def __init__(self):
        self.vram, self.util, self.ram_used = [], [], []
        self.stop_flag = threading.Event()
        self.thread = None

    def _gpu(self):
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None, None
        try:
            line = subprocess.run([exe, "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
            used, util = [float(x) for x in line.split(",")[:2]]
            return used, util
        except Exception:  # noqa: BLE001
            return None, None

    def _loop(self):
        while not self.stop_flag.is_set():
            used, util = self._gpu()
            if used is not None:
                self.vram.append(used)
                self.util.append(util)
            total, free = memory_mb()
            if total:
                self.ram_used.append(total - free)
            self.stop_flag.wait(0.5)

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=15)
        return {"vram_peak_mb": max(self.vram) if self.vram else None,
                "gpu_util_peak": max(self.util) if self.util else None,
                "gpu_util_avg": round(sum(self.util) / len(self.util), 1) if self.util else None,
                "ram_peak_used_mb": max(self.ram_used) if self.ram_used else None}


BENCH = {
    "speech": {"key": "moss", "payload": {"engine": "moss-fa", "voice": "mana", "out": "bench.wav",
                                         "text": "سلام! این یک آزمایشِ کوتاه از گفتارِ فارسی است. محصولِ تازهٔ ما امروز با ارسالِ رایگان به دستِ شما می‌رسد."}},
    "clone": {"key": "moss", "payload": {"engine": "moss-fa", "voice": "lora", "clone": True, "out": "bench.wav",
                                        "text": "این صدای ساخته‌شده از روی چند جمله است و هر متنی را با همان صدا می‌خواند."}},
    "sfx": {"key": "sfx", "payload": {"prompt": "light rain on a window, distant thunder", "seconds": 5, "out": "bench.wav"}},
    "music": {"key": "music", "payload": {"prompt": "calm acoustic guitar and soft piano, warm, instrumental", "seconds": 15,
                                          "out": "bench.wav", "seed": 42}},
}


def wav_seconds(path):
    import wave

    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:  # noqa: BLE001
        return None


def h_node_bench(job):
    """«تست»: a standard short job on one voice model, measured: cold model load, generation time, real-time factor,
    peak VRAM / RAM and GPU use. The engine is stopped first (when the agent runs it and it is idle) so the load is real."""
    model = str(job.payload.get("model") or "speech")
    if model not in BENCH:
        raise JobError("unknown model '%s' (speech, clone, sfx, music)" % model, retryable=False)
    key = BENCH[model]["key"]
    if not audio_allowed(key, model):
        raise JobError(audio_disabled_message(key, model), retryable=False)
    if not audio_installed(key):
        raise JobError(audio_missing_message(key), retryable=False)
    base_used, vram_total = vram_mb()
    ram_total, _free = memory_mb()
    cold = True
    if MANAGER is not None and MANAGER.running(key):
        if key in MANAGER.procs and not AUDIO_BUSY.get(key):
            MANAGER.stop(key)
            time.sleep(2)
            base_used, vram_total = vram_mb()
        else:
            cold = False                      # started outside the agent or busy: measured warm
    sampler = Sampler()
    sampler.start()
    t0 = time.time()
    try:
        if MANAGER is not None:
            MANAGER.prepare_audio(key, STATE["auto_switch"], _job_tick(job, 0.05), purpose=model)
        audio_ready(key, job)
        load_s = time.time() - t0
        job.payload = dict(BENCH[model]["payload"])
        t1 = time.time()
        handler = {"moss": h_moss_tts, "sfx": h_voice_sfx, "music": h_voice_music}[key]
        meta = handler(job) or {}
        gen_s = time.time() - t1
    finally:
        peaks = sampler.stop()
    audio_s = wav_seconds(job.out("bench.wav")) or float(meta.get("seconds") or 0) or None
    rtf = round(gen_s / audio_s, 3) if audio_s else None
    result = {"model": model, "engine": AUDIO_ENGINES[key]["label"], "cold": cold, "load_s": round(load_s, 1),
              "gen_s": round(gen_s, 1), "audio_s": round(audio_s, 1) if audio_s else None, "rtf": rtf,
              "vram_base_mb": base_used, "vram_total_mb": vram_total, "ram_total_mb": ram_total,
              "node": CONFIG.get("name"), "gpu": ", ".join(gpu_names()) or None, "agent": VERSION, **peaks}
    with open(job.out("bench.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    log("bench %s: load %.1fs, generate %.1fs for %ss of audio (RTF %s), peak VRAM %s MB" % (
        model, load_s, gen_s, result["audio_s"], rtf, peaks.get("vram_peak_mb")))
    return {"primary": "bench.wav", "engine": "bench:" + key, "bench": result}


def h_node_models(job):
    """The panel's «دانلود»: run Download-Models in the background for these packages (or the default set)."""
    p = job.payload
    pkgs = [str(x) for x in (p.get("packages") or []) if str(x).strip()]
    if p.get("action") == "refresh":
        st = DOWNLOADS.refresh(force=True)
        res = {"refreshed": bool(st)}
    else:
        res = {"result": DOWNLOADS.start(pkgs or None, "asked from the panel"), "packages": pkgs or "default"}
    with open(job.out("models.json"), "w", encoding="utf-8") as fh:
        json.dump({**res, "status": DOWNLOADS.caps()}, fh, ensure_ascii=False, indent=2)
    return {"primary": "models.json", "engine": "node", **res}


# ───────────────────────────────────────────── code updates (update.py / Update.bat / the panel)

CODE_FILES = ("agent.py", "nm_data.py", "update.py", "download_models.py", ".nm-version.json")


def code_stamp():
    """Size + time of the code files: when Update.bat (or git pull) changes them, the node restarts on the new code."""
    out = []
    for name in CODE_FILES:
        try:
            st = os.stat(os.path.join(HERE, name))
            out.append((name, st.st_size, int(st.st_mtime)))
        except OSError:
            out.append((name, None, None))
    return tuple(out)


def _updater():
    import importlib
    import update as upd                                 # update.py next to this file
    return importlib.reload(upd)


def h_node_update(job):
    """The panel's «به‌روزرسانی»: update this folder's code from the site; the node restarts on it when idle."""
    lines = []
    try:
        rc = _updater().run(auto=False, check_only=bool(job.payload.get("check")), out=lines.append)
    except Exception as e:  # noqa: BLE001
        raise JobError("update failed: %s" % e, retryable=False)
    for ln in lines:
        log("update: %s" % ln)
    with open(job.out("update.json"), "w", encoding="utf-8") as fh:
        json.dump({"rc": rc, "lines": lines, "from": VERSION}, fh, ensure_ascii=False, indent=2)
    if rc != 0:
        raise JobError("update failed: %s" % (lines[-1] if lines else "?"), retryable=False)
    return {"primary": "update.json", "engine": "node", "lines": lines[-5:], "from": VERSION}


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


def _relay(job, service, method, path, body=None, files=None, headers=None, out_name=None, timeout=1800,
           resp_headers=None):
    """Request to a local service; JSON answer -> .json output file, binary answer -> file named out_name.
    resp_headers (a dict) receives the response headers."""
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
        if resp_headers is not None:
            resp_headers.update(rh or {})
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


def photo_ai_env(env):
    """Environment for the photo editor's «smart edit» (POST /api/docs/{id}/ai-edit = an OpenAI-compatible vision model).
    Default: this node's own Ollama (no key, no internet) with the vision models it has. NM_PHOTO_AI=off keeps the kit's
    appsettings.json; Photo__Ai__BaseUrl already in the environment wins. Without a vision model the kit falls back to
    its free automatic edit and says so (usedAi=false)."""
    if str(env.get("NM_PHOTO_AI", "")).strip().lower() in ("0", "off", "false", "no") or env.get("Photo__Ai__BaseUrl"):
        return {}
    models = (env.get("NM_PHOTO_AI_MODELS") or "").strip() or ",".join(ollama_vision_models()) or \
        "qwen3-vl:30b,qwen2.5vl:7b,llava:7b"
    return {"Photo__Ai__BaseUrl": service_url("ollama") + "/v1", "Photo__Ai__Models": models,
            "Photo__Ai__TimeoutSeconds": str(env.get("NM_PHOTO_AI_TIMEOUT") or 900)}


VISION_HINTS = ("-vl", "vl:", "vl-", "vision", "llava", "minicpm-v", "moondream", "gemma3", "llama4", "mistral-small3")


def ollama_vision_models():
    """Ollama models on this node that can see images (by their names)."""
    try:
        tags = http("GET", service_url("ollama") + "/api/tags", timeout=5)
    except Exception:  # noqa: BLE001 - Ollama is not running: the kit falls back to its free automatic edit
        return []
    names = [str(m.get("name") or "") for m in (tags or {}).get("models") or [] if isinstance(m, dict)]
    return [n for n in names if any(h in n.lower() for h in VISION_HINTS)]


def _header(rh, name):
    for k, v in (rh or {}).items():
        if k.lower() == name.lower():
            return v
    return None


PHOTO_EXT = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg"}


def _photo_sidecar(job, info):
    """photo-edit.json next to the photo: the recipe the kit really used (auto / smart edit), notes, whether AI ran."""
    with open(job.out("photo-edit.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)


def h_photo_edit(job):
    """photo.edit: one photo + the kit's recipe (sliders, preset, curve, crop, spots, background, output) -> edited photo.
    auto: the kit's free automatic edit under the recipe. goal: «smart edit» - the vision model behind the kit's
    /api/docs/{id}/ai-edit sets the sliders; the site's frame/background/crop/spots stay as asked."""
    p = job.payload
    img = p.get("image") or (p.get("files") or {}).get("image")
    if not img or not job.input_path(img):
        raise RuntimeError("input image (image) is required")
    recipe = p.get("recipe") or {}
    stem = os.path.splitext(os.path.basename(img))[0]
    goal = str(p.get("goal") or "").strip()
    if goal:
        return _photo_smart_edit(job, img, recipe, goal, stem)
    fields = {}
    if recipe:
        fields["recipe"] = recipe
    q = "?auto=1" if p.get("auto") else ""
    fmt = (recipe.get("output") or {}).get("format") or "jpeg"
    ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp"}.get(str(fmt).lower(), ".jpg")
    rh = {}
    _obj, name = _relay(job, "photo", "POST", "/api/edit" + q, fields, {"file": img}, out_name=stem + "-edited" + ext,
                        resp_headers=rh)
    real = PHOTO_EXT.get((_header(rh, "Content-Type") or "").split(";")[0].strip().lower())
    if real and not name.endswith(real):   # a transparent photo asked as JPEG comes back as PNG
        fixed = stem + "-edited" + real
        os.replace(job.out(name), job.out(fixed))
        name = fixed
    info = {"auto": bool(p.get("auto"))}
    used = _header(rh, "X-Recipe")
    if used:
        try:
            info["recipe"] = json.loads(urllib.parse.unquote(used))
        except ValueError:
            pass
    _photo_sidecar(job, info)
    return {"primary": name, "engine": "photo"}


def _photo_smart_edit(job, img, recipe, goal, stem):
    base = service_url("photo")

    def call(method, path, data=None, headers=None, timeout=1800):
        try:
            return http(method, base + path, data, headers, timeout=timeout, raw=True)
        except urllib.error.HTTPError as e:
            raise RuntimeError("%s -> HTTP %s %s" % (path, e.code, e.read()[:400].decode("utf-8", "replace")))
        except (urllib.error.URLError, OSError) as e:
            raise RuntimeError("photo service is not reachable at %s: %s" % (base, e))

    body, ctype = multipart({}, {"file": (os.path.basename(img), job.input_bytes(img))})
    raw, _h = call("POST", "/api/docs?name=" + urllib.parse.quote("nm-" + job.uid[:8]), body,
                   {"Content-Type": ctype}, timeout=300)
    doc_id = (json.loads(raw.decode("utf-8") or "{}") or {}).get("id")
    if not doc_id:
        raise RuntimeError("the photo service did not return a document id")
    try:
        job.progress(0.15, "smart edit: the vision model looks at the photo")
        raw, _h = call("POST", "/api/docs/%s/ai-edit" % doc_id, {"goal": goal, "recipe": recipe})
        res = json.loads(raw.decode("utf-8") or "{}") or {}
        final = dict(res.get("recipe") or {})
        for key in ("output", "background", "crop", "spots"):   # the frame and the background are the site's choice
            if recipe.get(key) is not None:
                final[key] = recipe[key]
            else:
                final.pop(key, None)
        job.progress(0.7, "smart edit: rendering the full-size photo")
        data, rh = call("POST", "/api/docs/%s/export" % doc_id, final)
        ext = PHOTO_EXT.get((_header(rh, "Content-Type") or "").split(";")[0].strip().lower(), ".jpg")
        name = stem + "-edited" + ext
        with open(job.out(name), "wb") as fh:
            fh.write(data)
        _photo_sidecar(job, {"goal": goal, "recipe": final, "notes": res.get("notes"), "usedAi": res.get("usedAi"),
                             "error": res.get("error"), "steps": res.get("steps")})
    finally:
        try:
            http("DELETE", base + "/api/docs/%s" % doc_id, timeout=30)
        except Exception:  # noqa: BLE001 - a leftover document only costs disk on the node
            pass
    return {"primary": name, "engine": "photo", "smart": True}


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
    if str(p.get("engine") or "").lower() in MOSS_ENGINES:
        return h_moss_tts(job)              # never falls back to Piper: the site chose MOSS on purpose
    text = str(p.get("text", "")).strip()
    if not text:
        raise JobError("text is empty", retryable=False)
    out = os.path.basename(str(p.get("out") or "speech.wav"))
    engine = str(p.get("engine") or "").lower()
    voice = str(p.get("voice") or "")
    # natural voices / cloning (/api/voice/tts) need the kit's Python voice service; Piper (/api/tts) is always there.
    # A cloned (or strict) request never falls back: a shop that chose its own voice must not get somebody else's.
    strict = bool(p.get("clone") or p.get("strict"))
    natural = strict or (engine and engine != "piper") or bool(voice and not voice.startswith(("fa_IR-", "piper:")))
    if natural:
        if strict:
            return _natural_tts(job, p, text, out)
        try:
            return _natural_tts(job, p, text, out, setup=False)
        except JobError as e:
            warn("natural voice '%s' unavailable (%s) - using Piper (send strict=true to fail instead)"
                 % (voice or engine, str(e)[:160]))
    piper = {"text": text}
    if p.get("speed") not in (None, ""):
        piper["speed"] = str(p["speed"])
    if voice.startswith("piper:"):
        voice = voice[len("piper:"):]
    if voice.startswith("fa_IR-"):
        piper["voice"] = voice
    _obj, name = _relay(job, "voice", "POST", "/api/tts", piper, out_name=out, timeout=600)
    return {"primary": name, "engine": "voice:piper"}


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
    "voice.clone": h_voice_clone,
    "voice.sfx": h_voice_sfx,
    "voice.music": h_voice_music,
    "node.bench": h_node_bench,
    "node.models": h_node_models,
    "node.update": h_node_update,
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
        if MANAGER is not None:
            job.progress(0.02, "preparing services")
            last = [0.0]

            def tick(msg):
                # keep the site's lease on this job alive while services are prepared / started (it re-queues after 10 min)
                if time.time() - last[0] >= 25:
                    last[0] = time.time()
                    job.progress(0.02, msg[:120])

            MANAGER.prepare_for(job.kind, STATE["auto_switch"], tick, payload=job.payload)
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
        meta = {"node": CONFIG["name"]}
        if getattr(e, "retryable", True) is False:
            meta["retryable"] = False          # e.g. VOICE_MISSING: the site re-sends it with the recordings instead
        try:
            job.finish(False, err, meta)
        except JobLost:
            warn("job %s: the site had already put it back in the queue (no news from this node for too long); "
                 "this attempt is discarded" % job.uid[:8])
        except SiteError as e2:
            error("could not report the failed job: %s" % e2)
    finally:
        SITE_LOG.flush(force=True)


# ───────────────────────────────────────────── main loop

CONFIG = {}
RESTART_CODE = 75            # "restart me on the new code" (START.bat restarts the agent either way)


def set_data_root(root):
    """Point every data path at this folder (the first start chooses it; normally the same as at import)."""
    global DATA, WORK, LOGS, VOICE_ROOT
    DATA = root
    WORK = os.path.join(DATA, "work")
    LOGS = os.path.join(DATA, "logs")
    VOICE_ROOT = kit_dir("Voice")
    DOWNLOADS.status_file = os.path.join(LOGS, "download-status.json")
    os.environ["NM_DATA"] = DATA          # download_models.py, update.py, the audio workers, worker-3d.bat agree


def prepare_data():
    """The data folder, the downloads of older copies moved into it, the editors' source - on every start (fast when
    there is nothing to do)."""
    try:
        root, _summary = nm_data.prepare(HERE, out=lambda m: print(m, flush=True))
    except Exception as e:  # noqa: BLE001 - never keep the node down because of it
        print("note: the data folder could not be prepared fully (%s)" % e, flush=True)
        root = DATA
    set_data_root(root)
    return root


def _confirm_update():
    try:
        if _updater().confirm():
            log("update confirmed: agent v%s reached the site" % VERSION)
    except Exception as e:  # noqa: BLE001
        warn("could not record the update as good: %s" % e)
    return True


def main():
    global CONFIG
    if "--prepare" in sys.argv:                   # START.bat, before the loop: data folder + registration
        prepare_data()
        CONFIG = load_config(interactive=True)
        if CONFIG["site"] and CONFIG["token"]:
            print("Node '%s' -> %s   (data folder: %s)" % (CONFIG["name"], CONFIG["site"], DATA), flush=True)
            return 0
        print("[!] This computer is not registered: no site URL (site.json) or no enrollment key.", flush=True)
        return 2
    if "--print-config" in sys.argv or "--check" in sys.argv:
        os.environ["NM_DATA"] = DATA
    else:
        prepare_data()
    CONFIG = load_config(interactive="--print-config" not in sys.argv and "--check" not in sys.argv)
    if "--print-config" in sys.argv:
        print("NM_SITE=%s\nNM_TOKEN=%s\nNM_NODE=%s\nNM_DATA=%s" % (CONFIG["site"], CONFIG["token"], CONFIG["name"], DATA))
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
    global MANAGER
    MANAGER = ServiceManager()
    log("processing node '%s' v%s -> %s" % (CONFIG["name"], VERSION, CONFIG["site"]))
    try:
        preflight(CONFIG, site)
    except Exception as e:  # noqa: BLE001 - a checklist problem must not keep the node down
        warn("start-up checklist failed: %s" % e)
    threading.Thread(target=background_setup, daemon=True).start()

    def take_control(r):
        """desired services / auto-switch come back with every heartbeat and claim."""
        if not isinstance(r, dict):
            return
        if "auto_switch" in r:
            STATE["auto_switch"] = bool(r["auto_switch"])
        if isinstance(r.get("desired"), dict):
            if r["desired"] != STATE["desired"]:
                log("panel wants: %s (auto-switch %s)" % (json.dumps(r["desired"]), "on" if STATE["auto_switch"] else "off"))
            STATE["desired"] = r["desired"]
            MANAGER.apply(r["desired"])

    booted = False
    running = []
    last_hb = 0
    last_full = 0
    backoff = 5
    announced = False
    comfy_state = None
    stamp = code_stamp()
    started = time.time()
    confirmed = False
    draining = False
    while True:
        running = [t for t in running if t.is_alive()]
        if not draining and code_stamp() != stamp:
            draining = True
            log("the code of this folder was updated - restarting on it %s" % (
                "when the running job(s) end" if running else "now"))
        if draining and not running:
            SITE_LOG.add("INFO", "agent v%s on %s restarts on the updated code" % (VERSION, socket.gethostname()))
            SITE_LOG.flush(force=True)
            try:
                MANAGER.stop_audio()
                _updater().request_restart("code updated while running")
            except Exception as e:  # noqa: BLE001
                warn("restart preparation: %s" % e)
            return RESTART_CODE
        if not confirmed and time.time() - started > 120:
            confirmed = _confirm_update()             # ran two minutes without stopping: the update is good
        if MANAGER is not None:
            try:
                MANAGER.reap_audio()
                DOWNLOADS.poll()
            except Exception as e:  # noqa: BLE001 - housekeeping must not stop the node
                warn("audio idle check failed: %s" % e)
        try:
            now = time.time()
            if now - last_hb > 20:
                c = caps.probe()
                full = caps.changed() or now - last_full > 300
                r = site.post("/api/v1/compute/heartbeat/", c if full else {})
                take_control(r)
                if not confirmed:
                    confirmed = _confirm_update()     # this version reached the site: an update is good
                if not booted:
                    booted = True
                    MANAGER.default_boot(STATE["desired"])
                if full:
                    last_full = now
                    on = [k for k in SERVICES if c.get(k)]
                    log("heartbeat ok (%s) - services up: %s - GPU: %s" % (
                        r.get("name", "?"), ", ".join(on) or "none", c.get("gpu", "-")))
                    if not c.get("comfyui"):
                        if not MANAGER.startable("comfyui"):
                            state, text = "down", ("ComfyUI is not running at %s and the agent cannot start it (no start command in "
                                                   "services.json / NM_COMFY_BAT) - image/video jobs cannot be processed on this node"
                                                   % service_url("comfyui"))
                        elif not STATE["auto_switch"]:
                            state, text = "manual", ("ComfyUI is off and auto-switch is off - switch it on from the panel "
                                                     "(services of this node) or enable auto-switch; image/video jobs wait until then")
                        else:
                            state, text = "ondemand", "ComfyUI is off; it will be started on demand (auto-switch) or from the panel"
                        if comfy_state != state:
                            (log if state == "ondemand" else warn)(text)
                            comfy_state = state
                    else:
                        comfy_state = "up"
                    if not announced:
                        SITE_LOG.add("INFO", "agent v%s started on %s (%s); services: %s; GPU: %s" % (
                            VERSION, socket.gethostname(), platform.platform(), ", ".join(on) or "none", c.get("gpu", "-")))
                        announced = True
                last_hb = now
                SITE_LOG.flush()
            if len(running) < CONFIG["slots"] and not draining:
                r = site.post("/api/v1/compute/claim/", {})
                take_control(r)
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
