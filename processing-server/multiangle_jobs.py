#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Node side of «چندزاویه» (multi-angle video from one camera): job kinds, heartbeat capabilities and the AUTOMATIC install (agent 2.11).

Job kinds (all handled here, the pixels are done by multiangle_engine.py in a separate process):

    multiangle.virtual    one video -> several virtual cameras (wide / medium / close / two-shot / over-the-shoulder), synced clips and the
                          auto-switched multicam edit.  payload {video, angles, format, pace, handheld, rhythm, seed, sentences, out_height,
                          max_upscale, multicam, max_seconds}
    multiangle.move       one picture or clip -> a 2.5D camera move (dolly / truck / crane / orbit) with depth parallax.
                          payload {input, move, amount, duration, fps, format, ease, relief, focus, inpaint, out_height}
    multiangle.selftest   the node's acceptance run: a synthetic clip and picture through both of the above + pass checks -> selftest.json

The answer files are small ones (plan.json, previews, depth.png) through the normal upload and the videos through the resumable chunk upload
(a break in the line continues where it stopped).

Nothing here needs the owner to do anything. What the features need - a Python with numpy + OpenCV + onnxruntime and three small ONNX models -
is declared in downloads/multiangle.json (non-optional packages: the node's start-up download fetches them, and Update.bat / the panel's
update do the same) and, on top of that, `ensure_installed` asks the node's download manager for whatever is still missing right away (the
packages are small - about 0.4 GB - so they ignore the night window; NM_MULTIANGLE_AUTOINSTALL=window makes them obey it, =0 switches the
automatic install off). It re-checks every 15 minutes, so a download that failed once is tried again by itself. The heartbeat carries

    caps["multiangle"]           True when this agent knows the kinds above (the site routes them only to such nodes)
    caps["multiangle_runtime"]   {ok, providers, gpu, python, message}  - can some Python here run the engine, and on which device
    caps["multiangle_models"]    {yunet|yolos|depth: {state: installed|downloading|queued|missing|failed, size_mb, progress?}}
    caps["multiangle_ready"]     {virtual: bool, move: bool}  - what could start RIGHT NOW (the site keeps jobs queued until it is True)

The module hooks itself in with one call from agent.py: `multiangle_jobs.register(agent_module, HANDLERS)`.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "multiangle_engine.py")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
GPU_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider")
KINDS = ("multiangle.virtual", "multiangle.move", "multiangle.selftest")
PKG_RUNTIME = "multiangle-runtime"
PKG_DETECT = "multiangle-detect"
PKG_DEPTH = "multiangle-depth"
#: videos / pictures bigger than this go through the resumable chunk upload
BIG_OUTPUT = 4 * 1024 * 1024
ANGLES = ("wide", "medium", "close", "two_shot", "over_shoulder")
FORMATS = ("source", "reel", "feed", "square", "wide")
PACES = ("slow", "medium", "fast")
RHYTHMS = ("auto", "speech", "beat")
MOVES = ("dolly_in", "dolly_out", "truck_left", "truck_right", "crane_up", "crane_down", "orbit_left", "orbit_right", "push_parallax")
EASES = ("inout", "sine", "out", "linear")
INSTALL_EVERY_S = 900

#: the three model files: where they live (under <data>/models), the exact size the manifest downloads, which package brings them
MODELS = {
    "yunet": {"label": "YuNet (تشخیص چهره)", "mb": 1, "license": "MIT", "package": PKG_DETECT,
              "file": "face_detection_yunet_2023mar.onnx", "size": 232589},
    "yolos": {"label": "YOLOS-tiny (تشخیص آدم)", "mb": 25, "license": "Apache-2.0", "package": PKG_DETECT,
              "file": "yolos-tiny.onnx", "size": 26227993},
    "depth": {"label": "Depth-Anything-V2-Small (عمق)", "mb": 95, "license": "Apache-2.0", "package": PKG_DEPTH,
              "file": "depth-anything-v2-small.onnx", "size": 99060839},
}
#: what each kind needs before the site may hand it to this node
NEEDS = {"multiangle.virtual": ("yunet", "yolos"), "multiangle.move": ("depth", "yunet"),
         "multiangle.selftest": ("yunet", "yolos", "depth")}

_PROBE = (
    "import json\n"
    "import numpy\n"
    "import cv2\n"
    "import onnxruntime as o\n"
    "print(json.dumps({'np': numpy.__version__, 'cv2': cv2.__version__, 'yunet': hasattr(cv2, 'FaceDetectorYN'), 'ort': o.__version__,"
    " 'providers': list(o.get_available_providers())}))\n"
)
_LOCK = threading.Lock()
_PY_CACHE = {}
_RUNTIME = {"key": None, "value": None, "thread": None}
_RUN_LOCK = threading.Lock()                 # one multi-angle job at a time: they share the GPU and are heavy
_INSTALL = {"last": 0.0, "note": ""}


def enabled():
    return (os.environ.get("NM_MULTIANGLE") or "1").strip().lower() not in ("0", "off", "no", "false")


def _log(agent, msg):
    fn = getattr(agent, "log", None)
    (fn or print)("multiangle: %s" % msg)


def _warn(agent, msg):
    fn = getattr(agent, "warn", None)
    (fn or print)("multiangle: %s" % msg)


# ───────────────────────────────────────────── where the files are / what is installed

def model_dir(data_root):
    return os.path.join(data_root, "models", "multiangle")


def model_file(data_root, key):
    return os.path.join(model_dir(data_root), MODELS[key]["file"])


def have_model(data_root, key):
    try:
        return os.path.getsize(model_file(data_root, key)) == MODELS[key]["size"]
    except OSError:
        return False


# ───────────────────────────────────────────── which Python can run the engine

def probe_python(py, timeout=120):
    """{"np","cv2","yunet","ort","providers"} when `py` can import numpy + cv2 + onnxruntime, else {"error": why}. Cached per path + mtime."""
    try:
        key = (py, os.path.getmtime(py))
    except OSError:
        return {"error": "not found"}
    with _LOCK:
        if key in _PY_CACHE:
            return _PY_CACHE[key]
    try:
        r = subprocess.run([py, "-c", _PROBE], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=timeout,
                           cwd=tempfile.gettempdir(), creationflags=NO_WINDOW)
        lines = r.stdout.decode("utf-8", "replace").strip().splitlines()
        if r.returncode == 0 and lines:
            info = json.loads(lines[-1])
            if not info.get("yunet"):
                info = {"error": "this OpenCV has no FaceDetectorYN (needs 4.5.4+)", **info}
        else:
            tail = (r.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
            info = {"error": tail[:200]}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        info = {"error": str(e)[:200]}
    with _LOCK:
        _PY_CACHE[key] = info
    return info


def candidate_pythons(agent=None):
    """The owner's choice, the environment this feature makes (<data>/venvs/multiangle), then every other environment of the data folder
    and the agent's own Python."""
    cands = []
    pick = (os.environ.get("NM_MULTIANGLE_PYTHON") or "").strip().strip('"')
    if pick:
        cands.append(pick)
    data = getattr(agent, "DATA", "") if agent is not None else ""
    if data:
        for rel in (("Scripts", "python.exe"), ("bin", "python")):
            cands.append(os.path.join(data, "venvs", "multiangle", *rel))
    try:
        import edit_rvm
        cands.extend(edit_rvm.candidate_pythons(agent))
    except Exception:  # noqa: BLE001
        cands.append(sys.executable)
    seen, out = set(), []
    for c in cands:
        if c and os.path.isfile(c) and os.path.normcase(os.path.abspath(c)) not in seen:
            seen.add(os.path.normcase(os.path.abspath(c)))
            out.append(c)
    return out


def find_python(agent=None, probe=True):
    """(python path, probe info) of the best Python - one with a GPU provider beats a CPU-only onnxruntime - or (None, why)."""
    best, best_rank, why = None, -1, []
    for py in candidate_pythons(agent):
        try:
            key = (py, os.path.getmtime(py))
        except OSError:
            continue
        with _LOCK:
            info = _PY_CACHE.get(key)
        if info is None:
            if not probe:
                continue
            info = probe_python(py)
        if info.get("error"):
            why.append("%s: %s" % (os.path.basename(os.path.dirname(py)) or py, info["error"]))
            continue
        rank = 2 if any(p in GPU_PROVIDERS for p in info.get("providers") or []) else 1
        if rank > best_rank:
            best, best_rank = (py, info), rank
    if best:
        return best
    return None, "no Python on this computer has numpy + OpenCV + onnxruntime (%s)" % ("; ".join(why[:3]) or "none found")


def runtime(agent=None, wait=False):
    """{"ok": True|False|None, "providers", "gpu", "message"}; None = still being probed (importing OpenCV in other Pythons takes seconds,
    so it runs once in the background)."""
    try:
        key = tuple((c, os.path.getmtime(c)) for c in candidate_pythons(agent))
    except OSError:
        key = ()
    with _LOCK:
        if _RUNTIME["key"] == key and _RUNTIME["value"] is not None:
            return dict(_RUNTIME["value"])
        t = _RUNTIME["thread"]
        running = t is not None and t.is_alive()

    def work():
        py, info = find_python(agent)
        if py:
            provs = [p.replace("ExecutionProvider", "") for p in info.get("providers") or []]
            val = {"ok": True, "providers": provs, "gpu": any(p in GPU_PROVIDERS for p in info.get("providers") or []), "cv2": info.get("cv2"),
                   "ort": info.get("ort")}
        else:
            val = {"ok": False, "providers": [], "gpu": False, "message": info if isinstance(info, str) else "no suitable Python"}
        with _LOCK:
            _RUNTIME.update(key=key, value=val)

    if not running:
        t = threading.Thread(target=work, daemon=True)
        with _LOCK:
            _RUNTIME["thread"] = t
        t.start()
    if wait:
        t.join(240)
        with _LOCK:
            if _RUNTIME["value"] is not None:
                return dict(_RUNTIME["value"])
    return {"ok": None, "providers": [], "gpu": False, "message": "checking"}


# ───────────────────────────────────────────── what the panel reads

def model_states(agent=None):
    """{"yunet": {"state": installed|downloading|queued|missing|failed, "size_mb", "progress"?, "error"?}, ...}"""
    data = getattr(agent, "DATA", "") if agent is not None else ""
    dl = getattr(agent, "DOWNLOADS", None)
    running, queued, progress, last_error = set(), set(), None, ""
    if dl is not None:
        try:
            caps = dl.caps()
            pr = caps.get("progress") or {}
            running = set(pr.get("packages") or []) if caps.get("running") else set()
            if running and pr.get("bytes_total"):
                progress = round(min(1.0, float(pr.get("bytes_done") or 0) / float(pr["bytes_total"])), 3)
            last_error = str(caps.get("error") or "")
            waiting = caps.get("waiting") or {}
            queued = set(getattr(dl, "queue", None) or []) | set(waiting.get("packages") or [])
        except Exception:  # noqa: BLE001 - never let a status read break the heartbeat
            pass
    out = {}
    for key, spec in MODELS.items():
        row = {"state": "missing", "size_mb": spec["mb"]}
        if data and have_model(data, key):
            row["state"] = "installed"
        elif spec["package"] in running:
            row["state"] = "downloading"
            if progress is not None:
                row["progress"] = progress
        elif spec["package"] in queued:
            row["state"] = "queued"
        elif last_error and (spec["file"] in last_error or spec["package"] in last_error or key in last_error):
            row["state"] = "failed"
            row["error"] = last_error[:200]
        out[key] = row
    return out


def ready_for(kind, models, rt):
    """Could this kind start right now? (runtime found and every model it needs installed)"""
    if rt.get("ok") is not True:
        return False
    return all((models.get(k) or {}).get("state") == "installed" for k in NEEDS.get(kind, ()))


def caps(agent=None):
    """The heartbeat keys of this feature."""
    if not enabled():
        return {"multiangle": False}
    models = model_states(agent)
    rt = runtime(agent)
    return {"multiangle": True, "multiangle_version": VERSION, "multiangle_runtime": rt, "multiangle_models": models,
            "multiangle_ready": {"virtual": ready_for("multiangle.virtual", models, rt), "move": ready_for("multiangle.move", models, rt),
                                 "selftest": ready_for("multiangle.selftest", models, rt)},
            "multiangle_install": dict(_INSTALL)}


# ───────────────────────────────────────────── the automatic install

def missing_packages(agent):
    """Packages (names in downloads/multiangle.json) this node still lacks."""
    data = getattr(agent, "DATA", "")
    need = []
    py, _info = find_python(agent)
    if py is None:
        need.append(PKG_RUNTIME)
    for key, spec in MODELS.items():
        if not have_model(data, key) and spec["package"] not in need:
            need.append(spec["package"])
    return need


def ensure_installed(agent, force=False):
    """Ask the node's download manager for what is missing; idempotent and cheap when everything is there. Returns a short note."""
    mode = (os.environ.get("NM_MULTIANGLE_AUTOINSTALL") or "1").strip().lower()
    if mode in ("0", "off", "no", "false"):
        return "off"
    dl = getattr(agent, "DOWNLOADS", None)
    if dl is None or not dl.available():
        _INSTALL["note"] = "download_models.py is not there"
        return _INSTALL["note"]
    need = missing_packages(agent)
    if not need:
        _INSTALL["note"] = "everything installed"
        return "ok"
    window = None if mode == "window" else ""            # "" = no limit: the packages are small
    res = dl.start(need, "multiangle: automatic install", window=window)
    _INSTALL["last"] = time.time()
    _INSTALL["note"] = "%s: %s" % (res, ", ".join(need))
    _log(agent, "installing %s (%s)" % (", ".join(need), res))
    return res


def may_install_now(agent):
    """The background installer acts only in a REAL agent that has talked to its site: importing agent.py inside a unit-test run must never
    start a download (NM_MULTIANGLE_INSTALL_IN_TESTS=1 lifts that for a test of this very function), and nothing is asked before the site has
    answered once (agent.wait_first_control(0) = «has it answered yet?», it does not wait)."""
    if "unittest" in sys.modules and os.environ.get("NM_MULTIANGLE_INSTALL_IN_TESTS") != "1":
        return False
    wait = getattr(agent, "wait_first_control", None)
    if wait is None:
        return True
    try:
        return bool(wait(0))
    except Exception:  # noqa: BLE001 - an agent that cannot say is treated as connected
        return True


def _installer(agent):
    """Background thread: once the site has answered the first time, keep the install going until everything is in place."""
    time.sleep(5)
    try:
        wait = getattr(agent, "wait_first_control", None)
        if wait:
            wait()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(25)                                       # the start-up download of the default set goes first
    while True:
        pause = INSTALL_EVERY_S
        try:
            if may_install_now(agent):
                ensure_installed(agent)
            else:
                pause = 30                               # not a real, connected agent yet: look again soon
        except Exception as e:  # noqa: BLE001 - never stop the node because of an optional feature
            _warn(agent, "automatic install failed: %s" % e)
        time.sleep(pause)


# ───────────────────────────────────────────── running the engine

def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return max(lo, min(hi, x))


def _choice(v, allowed, default):
    v = str(v or "").strip()
    return v if v in allowed else default


def build_command(kind, p, py, files, out_dir, models, ff, provider):
    """The engine command line for a job (payload values are clamped / whitelisted: nothing from the site reaches a shell)."""
    base = [py, "-X", "utf8", ENGINE]
    common = ["--out-dir", out_dir, "--models", models, "--ffmpeg", ff, "--provider", provider]
    if kind == "multiangle.virtual":
        angles = [a for a in (p.get("angles") or ["wide", "medium", "close"]) if a in ANGLES] or ["wide", "medium", "close"]
        cmd = base + ["virtual", "--video", files["video"]] + common + [
            "--angles", ",".join(angles), "--format", _choice(p.get("format"), FORMATS, "source"), "--pace", _choice(p.get("pace"), PACES, "medium"),
            "--handheld", "%.3f" % _num(p.get("handheld"), 0.0, 1.0, 0.35), "--seed", str(int(_num(p.get("seed"), 0, 1000000, 7))),
            "--rhythm", _choice(p.get("rhythm"), RHYTHMS, "auto"), "--max-seconds", "%.1f" % _num(p.get("max_seconds"), 5, 300, 180),
            "--max-upscale", "%.2f" % _num(p.get("max_upscale"), 1.1, 3.0, 1.7)]
        if p.get("out_height"):
            cmd += ["--out-height", str(int(_num(p.get("out_height"), 240, 2160, 0)))]
        if files.get("sentences"):
            cmd += ["--sentences", files["sentences"]]
        if p.get("multicam") is False:
            cmd.append("--no-multicam")
        return cmd
    if kind == "multiangle.move":
        cmd = base + ["move", "--input", files["input"]] + common + [
            "--move", _choice(p.get("move"), MOVES, "dolly_in"), "--amount", "%.3f" % _num(p.get("amount"), 0.0, 1.0, 0.5),
            "--duration", "%.2f" % _num(p.get("duration"), 1.0, 12.0, 4.0), "--fps", "%.1f" % _num(p.get("fps"), 12, 60, 30),
            "--format", _choice(p.get("format"), FORMATS, "source"), "--ease", _choice(p.get("ease"), EASES, "inout"),
            "--relief", "%.2f" % _num(p.get("relief"), 0.4, 2.5, 1.0), "--max-seconds", "%.1f" % _num(p.get("max_seconds"), 1, 12, 12)]
        if p.get("out_height"):
            cmd += ["--out-height", str(int(_num(p.get("out_height"), 240, 2160, 0)))]
        focus = str(p.get("focus") or "")
        if focus and all(c in "0123456789.,-" for c in focus):
            cmd += ["--focus", focus]
        if p.get("inpaint"):
            cmd.append("--inpaint")
        return cmd
    return base + ["selftest"] + common


def _drain(stream, sink):
    try:
        for line in iter(stream.readline, b""):
            sink.append(line.decode("utf-8", "replace").rstrip())
            if len(sink) > 400:
                del sink[:200]
    except (OSError, ValueError):
        pass


def run_engine(job, agent, cmd, out_dir, say):
    """Start the engine, follow NMPROGRESS lines, return its NMRESULT dict. Raises agent.JobError with a message for the panel."""
    log_path = os.path.join(job.dir, "multiangle-engine.log")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env, cwd=job.dir, creationflags=NO_WINDOW)
    errs = []
    threading.Thread(target=_drain, args=(proc.stderr, errs), daemon=True).start()
    result, error = None, None
    deadline = time.time() + max(120, int(job.timeout_s) - 30)
    last = 0.0
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("NMPROGRESS "):
                _t, frac, _sp, msg = (line.split(" ", 3) + ["", ""])[:4]
                now = time.time()
                if now - last >= 1.5:
                    last = now
                    try:
                        say(float(frac), "multiangle|%s" % msg.strip())
                    except ValueError:
                        pass
            elif line.startswith("NMRESULT "):
                try:
                    result = json.loads(line[9:])
                except ValueError:
                    result = None
            elif line.startswith("NMERROR "):
                try:
                    error = json.loads(line[8:])
                except ValueError:
                    error = {"code": "engine", "message": line[8:]}
            if time.time() > deadline:
                proc.kill()
                raise agent.JobError("multiangle: the engine ran out of time", retryable=False)
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(errs[-300:]))
        except OSError:
            pass
    if error:
        code = str(error.get("code") or "engine")
        retry = code in ("memory", "encode", "engine")
        raise agent.JobError("%s [%s]" % (error.get("message") or "the engine failed", code), retryable=retry)
    if result is None:
        tail = "\n".join(errs[-6:])[-600:]
        raise agent.JobError("multiangle: the engine stopped without an answer (exit %s). %s" % (proc.returncode, tail), retryable=True)
    return result


def _deliver(job, agent, out_dir, say):
    """Small files -> normal outputs; big ones (the videos) -> resumable chunk upload. Returns {name: {bytes, sha256}} of the big ones."""
    big = {}
    names = sorted(os.listdir(out_dir))
    import edit_render

    for name in names:
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            continue
        if os.path.getsize(path) >= BIG_OUTPUT:
            say(0.93, "multiangle|upload")
            up = edit_render.upload_resumable(job, agent, path, name, lambda msg, frac: job.progress(min(0.99, frac), "multiangle|upload"))
            big[name] = {"bytes": up["bytes"], "sha256": up["sha256"]}
        else:
            shutil.copyfile(path, job.out(name))
    return big


def run(job, agent):
    """The handler of every multiangle.* kind (registered by `register`)."""
    if not enabled():
        raise agent.JobError("multiangle is switched off on this node (NM_MULTIANGLE=0)", retryable=False)
    import edit_render

    p = job.payload or {}
    kind = job.kind
    ff = edit_render.ffmpeg_exe(agent)
    if not ff:
        raise agent.JobError("ffmpeg is not installed on this node (the video kit brings it)", retryable=False)
    models = model_dir(agent.DATA)
    for key in NEEDS.get(kind, ()):
        if not have_model(agent.DATA, key):
            raise agent.JobError("the model %s is not installed on this node yet (package %s)" % (key, MODELS[key]["package"]), retryable=True)
    py, info = find_python(agent)
    if py is None:
        raise agent.JobError("this node cannot run multiangle yet: %s" % info, retryable=True)
    files = {}
    if kind == "multiangle.virtual":
        files["video"] = job.input_path(p.get("video"))
        if not files["video"]:
            raise agent.JobError("the video is not in the job package", retryable=False)
        sent = p.get("sentences")
        if isinstance(sent, list) and sent:
            path = os.path.join(job.dir, "sentences.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([{"start": float(s["start"]), "end": float(s["end"])} for s in sent[:2000] if isinstance(s, dict) and "start" in s and "end" in s], fh)
            files["sentences"] = path
    elif kind == "multiangle.move":
        files["input"] = job.input_path(p.get("input"))
        if not files["input"]:
            raise agent.JobError("the picture is not in the job package", retryable=False)
    work = os.path.join(job.dir, "multiangle-out")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    provider = os.environ.get("NM_MULTIANGLE_PROVIDER") or "auto"
    cmd = build_command(kind, p, py, files, work, models, ff, provider)

    def say(frac, msg):
        job.progress(max(0.02, min(0.97, 0.03 + 0.9 * frac)), msg)

    say(0.0, "multiangle|prepare")
    t0 = time.time()
    with _RUN_LOCK:
        result = run_engine(job, agent, cmd, work, say)
    big = _deliver(job, agent, work, say)
    shutil.rmtree(work, ignore_errors=True)
    meta = {"primary": "selftest.json" if kind == "multiangle.selftest" else "plan.json", "engine": "multiangle", "mode": result.get("mode"),
            "version": VERSION, "big": big, "python": os.path.basename(os.path.dirname(py)), "providers": info.get("providers"),
            "seconds_total": round(time.time() - t0, 1)}
    if kind == "multiangle.selftest":
        meta["ok"] = bool(result.get("ok"))
        meta["checks"] = result.get("checks")
    else:
        meta["device"] = result.get("device")
        meta["warnings"] = result.get("warnings")
        meta["output"] = result.get("output")
    return meta


# ───────────────────────────────────────────── hooking into the agent

def register(agent, handlers):
    """Called once from agent.py: adds the handlers, adds this feature to every heartbeat and starts the automatic install."""
    if not enabled():
        return False
    for kind in KINDS:
        handlers[kind] = (lambda job, _a=agent: run(job, _a))
    orig = agent.Capabilities.probe
    if not getattr(orig, "_multiangle", False):
        def probe(self):
            out = orig(self)
            try:
                out.update(caps(agent))
            except Exception as e:  # noqa: BLE001 - never let this keep the heartbeat from going out
                out["multiangle"] = False
                _warn(agent, "capabilities could not be read: %s" % e)
            return out

        probe._multiangle = True
        agent.Capabilities.probe = probe
    if (os.environ.get("NM_MULTIANGLE_AUTOINSTALL") or "1").strip().lower() not in ("0", "off", "no", "false"):
        threading.Thread(target=_installer, args=(agent,), daemon=True, name="multiangle-install").start()
    return True
