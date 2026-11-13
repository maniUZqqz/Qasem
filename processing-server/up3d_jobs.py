#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""up3d.render - the 3D video engine (Blender 4.5, Cycles on the GPU) as a compute-queue job (agent 2.12). Python 3.8+ standard library only.

Why a compute job and not the old separate `worker-3d.bat` process: the node has ONE graphics card. Ollama, ComfyUI, the voice engines and
Blender must not fight over its 12 GB. Every other heavy job already takes the node's main slot (one at a time); a 3D render is now one of
them. The site's 3D section keeps its own protocol (claim / progress / upload / finish under /3d/api/worker/), this module only calls it from
inside the job; nothing in the panel's 3D pages changes.

    payload = {"up3d_job": 36}                         render the waiting 3D job #36 of the site (the normal case)
    payload = {"package": "package.zip", "mode": "render" | "still" | "contact", "extra": [...]}
                                                       render a ready package (compiled.json + inputs/) that came with this job: the
                                                       automatic self-test uses this; outputs: render.mp4, engine_report.json, first_frame.png ...

Everything this needs is installed by bootstrap.py (requirements.d/blender-3d.json): Blender (from the site mirror, sha256-checked) and a
check that Cycles really sees the card (OptiX, else CUDA). The site keeps `up3d.render` jobs waiting until that is ready (bootstrap
blocked_kinds); an agent without this module never receives the kind (caps["kinds"]).

The module also (a) tells the site every ~40 s that this node can render 3D (a Worker heartbeat with the GPU list: the site's GPU-first
routing, estimates and the «why is my job waiting» text use it) and (b) stops the agent's old default of starting worker-3d.bat by
itself, because that second process would claim 3D jobs next to a running Ollama/ComfyUI job (set NM_UP3D_LEGACY_WORKER=1 to keep it).
"""
import json
import os
import shutil
import sys
import threading
import time
import zipfile

KIND = "up3d.render"
HEARTBEAT_S = 40
_STATE = {"caps": {}, "hb_error": 0.0}


# ───────────────────────────────────────────── environment of the engine

def _env(agent):
    """The engine finds its pieces through UP3D_* (up3d/paths.py reads them when it is first imported)."""
    data = agent.DATA
    os.environ.setdefault("UP3D_ROOT", os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault("UP3D_DATA", os.path.join(data, "up3d"))
    exe = agent.blender_path()
    if exe:
        os.environ["UP3D_BLENDER"] = exe
    user = os.path.join(data, "vendor", "blender-user")
    os.environ.setdefault("UP3D_BLENDER_USER", user)
    ff = None
    try:
        if agent.gpu is not None:
            ff = agent.gpu.best_ffmpeg(data)[0]
    except Exception:  # noqa: BLE001
        ff = None
    if ff:
        os.environ["UP3D_FFMPEG"] = ff
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    os.makedirs(os.environ["UP3D_DATA"], exist_ok=True)
    return exe


def _free_gpu(agent):
    """Let go of the card before Cycles takes it: Ollama's models, ComfyUI's models, a GPU audio engine, the peers listed in gpu-peers.json."""
    m = getattr(agent, "MANAGER", None)
    if m is None:
        return
    for name in ("stop_audio", "unload_ollama", "free_comfy"):
        try:
            getattr(m, name)()
        except Exception as e:  # noqa: BLE001
            agent.warn("up3d: %s failed: %s" % (name, e))
    try:
        m.hand_over_vram("comfyui", KIND)
    except Exception as e:  # noqa: BLE001
        agent.warn("up3d: VRAM hand-over failed: %s" % e)


# ───────────────────────────────────────────── the job

class _Hooks:
    """Mirrors the 3D worker's progress into the compute job (which also keeps the site's lease on it alive) and lets the agent cancel."""

    def __init__(self, job):
        self.job = job
        self.last = 0.0

    def progress(self, state, data):
        total, frame = data.get("total"), data.get("frame")
        if total:
            frac = 0.06 + 0.9 * min(1.0, float(frame or 0) / float(total))
            msg = "3D render: frame %s of %s" % (frame or 0, total)
        else:
            frac = 0.04 if state == "SCENE_BUILDING" else 0.06
            msg = data.get("message") or ("building the 3D scene" if state == "SCENE_BUILDING" else "rendering")
        meta = {"kind": "up3d", "state": state}
        for k in ("frame", "total", "sec_per_frame"):
            if data.get(k) is not None:
                meta[k] = data[k]
        try:
            self.job.progress(frac, str(msg)[:200], meta)
        except Exception:  # noqa: BLE001 - Cancelled is read through cancelled()
            pass

    def cancelled(self):
        return bool(self.job.cancelled)


def _worker_class(agent):
    from up3d.worker import Worker
    return Worker


def _caps_key(exe):
    try:
        return "%s|%s" % (exe, os.path.getmtime(exe))
    except OSError:
        return exe


def _fresh(caps):
    """The probed capabilities are cached (one Blender run), but the presenter data (MPFB) arrives later through its own install feature:
    that one flag is looked at again every time, so scenes with a presenter start going to this node as soon as the data is there."""
    caps = dict(caps)
    user = os.environ.get("UP3D_BLENDER_USER") or ""
    caps["mpfb"] = os.path.isfile(os.path.join(user, "extensions", "user_default", "mpfb", "__init__.py"))
    return caps


def _make_worker(agent, site_base, token, **kw):
    Worker = _worker_class(agent)
    w = Worker(site_base.rstrip("/") + "/3d", token, name=agent.CONFIG.get("name"), nice=0,
               work_dir=os.path.join(os.environ["UP3D_DATA"], "worker"), log=agent.log, **kw)
    key = _caps_key(os.environ.get("UP3D_BLENDER", ""))
    if key in _STATE["caps"]:
        w.caps = _fresh(_STATE["caps"][key])
    return w, key


def _device_meta(report):
    dev = (report or {}).get("device") or {}
    t = str(dev.get("type") or "").upper()
    meta = {}
    if t in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        meta["device"] = "cuda"
        meta["device_note"] = "Cycles %s: %s" % (t, dev.get("name") or "")
    elif t == "CPU":
        meta["device"] = "cpu"
        meta["device_note"] = dev.get("note") or "Cycles ran on the CPU"
    if report:
        for k in ("denoiser", "sec_per_frame", "render_seconds", "frames_rendered", "frames_expected"):
            if report.get(k) is not None:
                meta[k] = report[k]
        if report.get("fallbacks"):
            meta["fallbacks"] = report["fallbacks"][:3]
        if (report.get("look") or {}).get("view"):
            meta["colour"] = "%s / %s" % (report["look"].get("view"), report["look"].get("look"))
    return meta


def _safe_extract(zpath, dest):
    base = os.path.abspath(dest)
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():
            target = os.path.abspath(os.path.join(base, m))
            if not (target == base or target.startswith(base + os.sep)):
                raise RuntimeError("unsafe path in the package: %s" % m)
        z.extractall(base)


def _run_package(job, agent, exe):
    """Render a ready package that travelled with the job (self-test, or a hand-made job)."""
    from up3d import pipeline
    p = job.payload
    pkg = job.input_path(p.get("package") or "package.zip")
    if not pkg:
        raise agent.JobError("the package '%s' is not in the job's inputs" % (p.get("package") or "package.zip"), retryable=False)
    jdir = os.path.join(agent.DATA, "work", "up3d-%s" % job.uid[:8])
    shutil.rmtree(jdir, ignore_errors=True)
    os.makedirs(jdir)
    _safe_extract(pkg, jdir)
    comp = os.path.join(jdir, "compiled.json")
    if not os.path.isfile(comp):
        raise agent.JobError("the package has no compiled.json", retryable=False)
    with open(comp, encoding="utf-8") as fh:
        c = json.load(fh)
    prof = c.get("profile") or {}
    os.environ.pop("UP3D_REQUIRE_GPU", None)
    if p.get("require_gpu", True) and prof.get("recommended") == "gpu" and prof.get("device") != "CPU" and prof.get("engine", "CYCLES") == "CYCLES":
        os.environ["UP3D_REQUIRE_GPU"] = "1"
    hooks = _Hooks(job)

    def ev(kind, data):
        if kind == "progress":
            hooks.progress("RENDERING", {"frame": data.get("frame"), "total": data.get("total")})
        elif kind == "stage":
            hooks.progress("RENDERING" if data.get("text") in ("render", "encode") else "SCENE_BUILDING", {"message": "stage: %s" % data.get("text")})
        elif kind == "info" and data.get("sec_per_frame"):
            hooks.progress("RENDERING", {"frame": data.get("done"), "total": data.get("total"), "sec_per_frame": data.get("sec_per_frame")})
    mode = str(p.get("mode") or "render")
    t0 = time.time()
    job.progress(0.03, "starting Blender")
    pipeline.render(jdir, ev, lambda: bool(job.cancelled), 0, int(p.get("threads") or 0), os.path.join(jdir, "engine.log"), mode=mode,
                    extra=list(p.get("extra") or []))
    names = []
    for pat in ("render.mp4", "engine_report.json"):
        src = os.path.join(jdir, pat)
        if os.path.isfile(src):
            shutil.copyfile(src, job.out(pat))
            names.append(pat)
    import glob
    for src in sorted(glob.glob(os.path.join(jdir, "contact_*.png")) + glob.glob(os.path.join(jdir, "still_*.png"))):
        shutil.copyfile(src, job.out(os.path.basename(src)))
        names.append(os.path.basename(src))
    frames = sorted(glob.glob(os.path.join(jdir, "frames", "f_*.png")))
    if frames:
        shutil.copyfile(frames[len(frames) // 3], job.out("first_frame.png"))
        names.append("first_frame.png")
    logp = os.path.join(jdir, "engine.log")
    if os.path.isfile(logp):
        with open(logp, "rb") as fh:
            fh.seek(max(0, os.path.getsize(logp) - 200000))
            data = fh.read()
        with open(job.out("engine.log"), "wb") as fh:
            fh.write(data)
    report = {}
    try:
        with open(os.path.join(jdir, "engine_report.json"), encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, ValueError):
        pass
    images = [n for n in names if n.endswith(".png") and n != "first_frame.png"]
    primary = "render.mp4" if os.path.isfile(job.out("render.mp4")) else (images[0] if images else (names[0] if names else ""))
    meta = {"primary": primary, "engine": "blender", "mode": mode,
            "frames": len(frames), "seconds": round(time.time() - t0, 1)}
    meta.update(_device_meta(report))
    if prof.get("recommended") == "gpu" and meta.get("device") == "cpu":
        meta["device_warning"] = ("این رندر باید روی کارت گرافیک اجرا می‌شد ولی روی پردازنده اجرا شد (%s)" % meta.get("device_note", ""))
    shutil.rmtree(jdir, ignore_errors=True)
    return meta


def _run_site_job(job, agent, exe):
    """Claim and render ONE waiting job of the site's 3D section (payload up3d_job) through its own worker protocol."""
    p = job.payload
    try:
        only = int(p.get("up3d_job"))
    except (TypeError, ValueError):
        raise agent.JobError("payload.up3d_job (the 3D job number) is required", retryable=False)
    hooks = _Hooks(job)
    w, key = _make_worker(agent, job.site.base, job.site.token, only_job=only, hooks=hooks, require_gpu=True)
    job.progress(0.02, "asking the 3D section for job %d" % only)
    claimed = w.run_one()
    _STATE["caps"][key] = w.caps
    if not claimed:
        return {"result": "nothing to do: the 3D job %d is not waiting for a worker (it finished, was cancelled or another worker took it)" % only,
                "up3d_job": only}
    last = w.last or {}
    meta = {"up3d_job": only, "engine": "blender", "primary": ""}
    if last.get("released") == "cancelled" or job.cancelled:
        raise agent.Cancelled()
    if last.get("released"):
        meta["result"] = "the 3D section took the job back (%s); it is dispatched again" % last["released"]
        return meta
    if last.get("ok"):
        meta.update({"result": "done", "seconds": last.get("seconds"), "files": last.get("files")})
    else:
        # the 3D section already shows the error on its job page; the compute job itself did its work, so it is not retried
        meta.update({"result": "the 3D job failed: %s" % str(last.get("error") or "")[:300], "up3d_failed": True})
    return meta


def run(job, agent):
    exe = _env(agent)
    if not exe or not os.path.isfile(exe):
        raise agent.JobError("DOWNLOADING: Blender is still being installed on this node (see the install panel) | "
                             "Blender هنوز روی این سرور نصب نشده است؛ نصبِ خودکار در حال انجام است")
    _free_gpu(agent)
    payload = job.payload or {}
    meta = _run_package(job, agent, exe) if (payload.get("package") or job.input_path("package.zip")) else _run_site_job(job, agent, exe)
    meta.setdefault("blender", os.path.basename(os.path.dirname(exe)))
    return meta


# ───────────────────────────────────────────── the node tells the site it can render 3D

def _heartbeat_loop(agent):
    time.sleep(60)               # let the agent settle and the first jobs claim
    w = None
    while True:
        try:
            exe = agent.blender_path()
            site = getattr(getattr(agent, "SITE_LOG", None), "site", None)      # the agent's Site (base url + node token)
            if exe and site is not None:
                _env(agent)
                if w is None or _caps_key(exe) not in _STATE["caps"]:
                    w, key = _make_worker(agent, site.base, site.token)
                    w.capabilities()                       # one Blender run (devices + version), cached
                    _STATE["caps"][key] = w.caps
                w.caps = _fresh(w.caps)
                w.api.post("/api/worker/heartbeat/", w.caps)
        except Exception as e:  # noqa: BLE001 - say it, rarely; the next round tries again
            if time.time() - _STATE["hb_error"] > 900:
                _STATE["hb_error"] = time.time()
                agent.warn("up3d: could not tell the 3D section about this node (%s)" % str(e)[:200])
        time.sleep(HEARTBEAT_S)


def _take_over_service(agent):
    """The agent used to start worker-3d.bat by itself whenever Blender existed: a second GPU consumer next to the compute jobs. The 3D renders are
    compute jobs now, so the `worker3d` service has no start command any more (the agent then reports it as not startable and never starts it,
    whatever services.json of an older run says) and the first-boot default skips it. NM_UP3D_LEGACY_WORKER=1 keeps the old behaviour."""
    if os.environ.get("NM_UP3D_LEGACY_WORKER") == "1" or getattr(agent, "_up3d_service_taken", False):
        return
    orig_load = agent.load_services_cfg

    def load_services_cfg():
        cfg = orig_load()
        if isinstance(cfg.get("worker3d"), dict):
            cfg["worker3d"] = dict(cfg["worker3d"], start="", note="3D renders run as compute jobs (up3d.render) inside the agent")
        return cfg
    agent.load_services_cfg = load_services_cfg
    SM = getattr(agent, "ServiceManager", None)
    if SM is not None and hasattr(SM, "default_boot"):
        orig_boot = SM.default_boot

        def default_boot(self, desired):
            d = dict(desired or {})
            d.setdefault("worker3d", False)       # "decided already": the first-boot default must not start worker-3d.bat
            return orig_boot(self, d)
        SM.default_boot = default_boot
    agent._up3d_service_taken = True


def install(agent):
    agent.HANDLERS[KIND] = lambda job: run(job, agent)
    _take_over_service(agent)
    threading.Thread(target=_heartbeat_loop, args=(agent,), daemon=True, name="up3d-heartbeat").start()
