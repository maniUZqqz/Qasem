#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Photo background matting on the node: u2netp, IS-Net general and BiRefNet-lite (ONNX) -> a cut-out PNG with alpha + a mask
(agent 2.7).

Three ways to cut the subject out of a photo, all of them running ONLY on this computer (the processing node), never on the
site server:

    u2netp          ~5 MB    Apache-2.0   fast, rough edges (320 px network)
    isnet           ~170 MB  Apache-2.0   IS-Net "general use" (1024 px network), a good all-rounder
    birefnet-lite   ~220 MB  MIT          BiRefNet-lite (1024 px network), the finest edges; the same file the photo kit uses

The site queues `photo.matting` jobs {"image", "model", "feather", "keep_size"}; the answer is cutout.png (RGBA, the original
size), mask.png (8-bit grey) and photo-matting.json {"model", "seconds", "size", "device"}. A job for a model that is not here
yet is never handed to this node (the site holds it in the queue until `caps["matting_models"][model]["state"]` is
"installed"), so nothing fails just because a download has not finished.

This one file is both the library the agent uses (everything above `class Matter` needs only the standard library) and the
command line that runs a model:

    python photo_matting.py status                         what is installed here, and which Python would run it
    python photo_matting.py bench [--model all|u2netp|isnet|birefnet-lite] [--runs 3]
                                                           time every installed model on a test picture (Test-Matting.bat)
    python photo_matting.py run --model u2netp --image in.jpg --out-dir out [--feather 0] [--no-keep-size]

The models need `numpy`, `onnxruntime` and an image library (Pillow, or OpenCV) in SOME Python of this computer; `find_python()`
looks in the environments the node already has (the agent's own, the voice service, the audio engines, NM_MATTING_PYTHON) and a
Python with a GPU provider (CUDA, DirectML) wins over a CPU-only one. When none has them, `Download-Models.bat --only
matting-runtime` makes a small environment of its own (onnxruntime-directml + numpy + Pillow, ~60 MB) - only then; nothing is
installed twice. NM_MATTING_PROVIDER=cpu forces the CPU; NM_MATTING=0 switches the feature off.

Model files: u2netp / isnet live in <data folder>/models/photo-matting/ (downloads/matting.json: the site mirrors them because
the line to GitHub is slow or blocked); birefnet-lite is the photo kit's own file (downloads/photo.json), found where the kit
keeps it - it is never downloaded twice.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
GPU_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider")
RUNTIME_PACKAGE = "matting-runtime"
#: the longest side of a result when the job says keep_size=false (a smaller PNG for a quick look)
SMALL_SIDE = 1600

#: sizes are the exact byte counts of the files the manifests download (a cheap installed-check; sha256 is verified by the
#: downloader). `norm` is how the network wants its picture (rembg's recipe for the first two, ImageNet for BiRefNet).
MODELS = {
    "u2netp": {
        "label": "U²-Net سبک (u2netp)", "mb": 5, "license": "Apache-2.0", "package": "matting-u2netp",
        "file": "u2netp.onnx", "rel": ("models", "photo-matting", "u2netp.onnx"), "size": 4574861,
        "side": 320, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225), "norm": "max", "out": "minmax",
    },
    "isnet": {
        "label": "IS-Net همه‌کاره (isnet-general-use)", "mb": 170, "license": "Apache-2.0", "package": "matting-isnet",
        "file": "isnet-general-use.onnx", "rel": ("models", "photo-matting", "isnet-general-use.onnx"), "size": 178648008,
        "side": 1024, "mean": (0.485, 0.456, 0.406), "std": (1.0, 1.0, 1.0), "norm": "max", "out": "minmax",
    },
    "birefnet-lite": {
        "label": "BiRefNet سبک (birefnet-lite)", "mb": 224, "license": "MIT", "package": "photo-background",
        "file": "birefnet-lite.onnx", "rel": ("tools", "PersianAiKit", "Photo", "models", "background", "birefnet-lite.onnx"),
        "size": 224005088, "side": 1024, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225), "norm": "255",
        "out": "sigmoid",
    },
}
ORDER = ("u2netp", "isnet", "birefnet-lite")

_PROBE = (
    "import json\n"
    "import numpy\n"
    "import onnxruntime as o\n"
    "pil = cv = False\n"
    "try:\n"
    "    import PIL.Image\n"
    "    pil = True\n"
    "except Exception:\n"
    "    pass\n"
    "try:\n"
    "    import cv2\n"
    "    cv = True\n"
    "except Exception:\n"
    "    pass\n"
    "print(json.dumps({'ort': o.__version__, 'np': numpy.__version__, 'providers': list(o.get_available_providers()), 'pil': pil, 'cv2': cv}))\n"
)
_PY_CACHE = {}
_LOCK = threading.Lock()
_RUNTIME = {"key": None, "value": None, "thread": None}


class Unavailable(Exception):
    """The matting runtime cannot run on this node right now (no suitable Python, switched off ...)."""


def enabled():
    return (os.environ.get("NM_MATTING") or "1").strip().lower() not in ("0", "off", "no", "false")


# ───────────────────────────────────────────── where the files are / what is installed

def model_file(data_root, key):
    return os.path.join(data_root, *MODELS[key]["rel"])


def have_model(data_root, key):
    """The file is there with the manifest's size (a cheap check; the downloader verified the sha256 when it fetched it)."""
    spec = MODELS[key]
    try:
        size = os.path.getsize(model_file(data_root, key))
    except OSError:
        return False
    return size == spec["size"] if spec["size"] else size > 1 << 20


# ───────────────────────────────────────────── which Python can run it

def probe_python(py, timeout=90):
    """{"ort", "np", "providers", "pil", "cv2"} when `py` can import numpy + onnxruntime, else {"error": why}. Cached per path + mtime."""
    try:
        key = (py, os.path.getmtime(py))
    except OSError:
        return {"error": "not found"}
    with _LOCK:
        if key in _PY_CACHE:
            return _PY_CACHE[key]
    try:
        r = subprocess.run([py, "-c", _PROBE], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                           timeout=timeout, cwd=tempfile.gettempdir(), creationflags=NO_WINDOW)
        lines = r.stdout.decode("utf-8", "replace").strip().splitlines()
        if r.returncode == 0 and lines:
            info = json.loads(lines[-1])
            if not (info.get("pil") or info.get("cv2")):
                info = {"error": "no image library (Pillow or OpenCV)", **info}
        else:
            tail = (r.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
            info = {"error": tail[:200]}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        info = {"error": str(e)[:200]}
    with _LOCK:
        _PY_CACHE[key] = info
    return info


def candidate_pythons(agent=None):
    """Pythons worth asking: the owner's choice, the agent's own, the voice service, the audio engines, the matting
    environment this feature makes (all under <data>/venvs)."""
    cands = []
    pick = (os.environ.get("NM_MATTING_PYTHON") or "").strip().strip('"')
    if pick:
        cands.append(pick)
    try:
        import edit_rvm
        cands.extend(edit_rvm.candidate_pythons(agent))
    except Exception:  # noqa: BLE001
        cands.append(sys.executable)
    data = getattr(agent, "DATA", "") if agent is not None else ""
    if data:
        for rel in (("Scripts", "python.exe"), ("bin", "python")):
            cands.append(os.path.join(data, "venvs", "matting", *rel))
    seen, out = set(), []
    for c in cands:
        if c and os.path.isfile(c) and os.path.normcase(os.path.abspath(c)) not in seen:
            seen.add(os.path.normcase(os.path.abspath(c)))
            out.append(c)
    return out


def find_python(agent=None, probe=True):
    """(python path, probe info) of the best Python - a GPU provider beats a CPU-only onnxruntime - or (None, why)."""
    if not enabled():
        return None, "photo matting is switched off (NM_MATTING=0)"
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
    return None, "no Python on this computer has numpy + onnxruntime + Pillow (%s)" % ("; ".join(why[:3]) or "none found")


def runtime(agent=None, wait=False):
    """What the heartbeat reports: {"ok": True|False|None, "providers": [...], "message": "..."}; None = still being probed
    (the probe imports onnxruntime in other Pythons - seconds - so it runs once in the background)."""
    try:
        key = tuple((c, os.path.getmtime(c)) for c in candidate_pythons(agent)) + (enabled(),)
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
            val = {"ok": True, "providers": [p.replace("ExecutionProvider", "") for p in info.get("providers") or []],
                   "ort": info.get("ort"), "gpu": any(p in GPU_PROVIDERS for p in info.get("providers") or [])}
        else:
            val = {"ok": False, "providers": [], "message": info if isinstance(info, str) else "no suitable Python"}
        with _LOCK:
            _RUNTIME.update(key=key, value=val)

    if not running:
        t = threading.Thread(target=work, daemon=True)
        with _LOCK:
            _RUNTIME["thread"] = t
        t.start()
    if wait:
        t.join(180)
        with _LOCK:
            if _RUNTIME["value"] is not None:
                return dict(_RUNTIME["value"])
    return {"ok": None, "providers": [], "message": "checking"}


# ───────────────────────────────────────────── what the panel reads

def model_states(agent=None):
    """{"u2netp": {"state": installed|downloading|queued|missing|failed, "size_mb", "progress"?, "error"?}, ...}"""
    data = getattr(agent, "DATA", "") if agent is not None else ""
    dl = getattr(agent, "DOWNLOADS", None)
    running, queued, current, progress, last_error, waiting = set(), set(), "", None, "", {}
    if dl is not None:
        try:
            caps = dl.caps()
            pr = caps.get("progress") or {}
            running = set(pr.get("packages") or []) if caps.get("running") else set()
            if running and pr.get("bytes_total"):
                progress = round(min(1.0, float(pr.get("bytes_done") or 0) / float(pr["bytes_total"])), 3)
            current = str(pr.get("current") or "")
            last_error = str(caps.get("error") or "")
            waiting = caps.get("waiting") or {}
            queued = set(getattr(dl, "queue", None) or []) | set(waiting.get("packages") or [])
        except Exception:  # noqa: BLE001 - never let a status read break the heartbeat
            pass
    out = {}
    for key in ORDER:
        spec = MODELS[key]
        row = {"state": "missing", "size_mb": spec["mb"]}
        if data and have_model(data, key):
            row["state"] = "installed"
            try:
                row["size_mb"] = max(1, round(os.path.getsize(model_file(data, key)) / 1048576))
            except OSError:
                pass
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


def caps(agent=None):
    """The heartbeat keys of this feature."""
    if not enabled():
        return {"photo_matting": False}
    return {"photo_matting": True, "matting_models": model_states(agent), "matting_runtime": runtime(agent)}


# ───────────────────────────────────────────── the job

def _json_line(line, tag):
    if line.startswith(tag + " "):
        try:
            return json.loads(line[len(tag) + 1:])
        except ValueError:
            return None
    return None


def run(job, agent):
    """The `photo.matting` handler: one photo -> cutout.png + mask.png + photo-matting.json (or a timing test with bench=true)."""
    p = job.payload or {}
    key = str(p.get("model") or "")
    if key not in MODELS:
        raise agent.JobError("مدلِ «%s» را نمی‌شناسم؛ یکی از %s" % (key, "، ".join(ORDER)), retryable=False)
    if not enabled():
        raise agent.JobError("photo matting is switched off on this node (NM_MATTING=0)", retryable=False)
    path = model_file(agent.DATA, key)
    if not have_model(agent.DATA, key):
        raise agent.JobError("مدلِ %s هنوز روی سرورِ پردازش نصب نیست (Download-Models.bat --only %s)" % (key, MODELS[key]["package"]),
                             retryable=True)
    py, info = find_python(agent)
    if py is None:
        raise agent.JobError("محیطِ اجرای جداسازی روی این سرور نیست: %s (Download-Models.bat --only %s)" % (info, RUNTIME_PACKAGE),
                             retryable=True)
    bench = bool(p.get("bench"))
    image = None
    if not bench:
        image = job.input_path(p.get("image"))
        if not image:
            raise agent.JobError("the photo is not in the job package", retryable=False)
    out_dir = os.path.dirname(job.out("cutout.png"))
    cmd = [py, os.path.abspath(__file__), "bench" if bench else "run", "--model", key, "--model-file", path, "--out-dir", out_dir,
           "--provider", os.environ.get("NM_MATTING_PROVIDER") or "auto"]
    if bench:
        cmd += ["--runs", "2", "--json"]
    else:
        cmd += ["--image", image, "--feather", str(max(0.0, min(40.0, float(p.get("feather") or 0))))]
        if p.get("keep_size") is False:
            cmd.append("--no-keep-size")
    job.progress(0.1, "matting|%s" % key)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    errf = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, stdin=subprocess.DEVNULL, cwd=HERE, env=env, creationflags=NO_WINDOW)
    state = {"result": None, "phase": ""}

    def read():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            r = _json_line(line, "RESULT")
            if r is not None:
                state["result"] = r
            elif line.startswith("PHASE "):
                state["phase"] = line[6:]

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    started = last_tick = time.time()
    limit = float(os.environ.get("NM_MATTING_TIMEOUT_S") or max(120, min(1800, job.timeout_s)))
    try:
        while proc.poll() is None:
            time.sleep(0.4)
            if time.time() - last_tick >= 5.0:                            # keep the lease alive and see a cancel quickly
                last_tick = time.time()
                job.progress(min(0.9, 0.1 + (time.time() - started) / max(30.0, limit) * 0.8), "matting|%s|%s" % (key, state["phase"]))
            if time.time() - started > limit:
                proc.kill()
                raise RuntimeError("the matting model did not finish in %d s" % limit)
    except BaseException:                  # cancelled by the site (job.progress raises) or too slow: stop the model
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join(5)
        proc.stdout.close()
        errf.close()
        raise
    reader.join(5)
    proc.stdout.close()
    errf.seek(0)
    tail = errf.read().decode("utf-8", "replace").strip()[-600:]
    errf.close()
    res = state["result"]
    if proc.returncode != 0 or not res:
        corrupt = "INVALID_PROTOBUF" in tail or "Protobuf parsing failed" in tail or "load model" in tail.lower()
        raise agent.JobError(("فایلِ مدلِ %s خراب است؛ دوباره دانلودش کنید. " % key if corrupt else "جداسازی شکست خورد: ") + (tail or "no message"),
                             retryable=False)
    if bench:
        with open(job.out("photo-matting.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        return {"primary": "photo-matting.json", "engine": "photo.matting", "bench": True, **res}
    for name in ("cutout.png", "mask.png"):
        if not os.path.isfile(job.out(name)):
            raise agent.JobError("the model finished but %s is missing" % name, retryable=False)
    with open(job.out("photo-matting.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    return {"primary": "cutout.png", "engine": "photo.matting", "model": key, "seconds": res.get("seconds"), "size": res.get("size"),
            "device": res.get("device"), "python_ort": info.get("ort")}


# ───────────────────────────────────────────── the models themselves (need numpy + onnxruntime + Pillow/OpenCV)

class Matter:
    """One model session. `predict(rgb)` takes an RGB uint8 array (H, W, 3) and returns the alpha as a float32 array (H, W) in [0, 1]."""

    def __init__(self, key, model_file_path, provider="auto", threads=0):
        import numpy as np
        import onnxruntime as ort

        self.np, self.ort, self.key, self.spec = np, ort, key, MODELS[key]
        self.threads = int(threads or 0)
        self.sess = self._open(model_file_path, (provider or "auto").lower())
        self.provider = self.sess.get_providers()[0]
        self.path = model_file_path
        inp = self.sess.get_inputs()[0]
        shp = inp.shape
        side = None
        if len(shp) == 4 and isinstance(shp[2], int) and isinstance(shp[3], int) and shp[2] == shp[3] and shp[2] > 0:
            side = shp[2]
        self.side = side or self.spec["side"]
        self.input_name = inp.name

    def _open(self, path, wanted):
        ort = self.ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        if self.threads:
            opts.intra_op_num_threads = self.threads
        have = ort.get_available_providers()
        chain = []
        if wanted in ("auto", "gpu", "cuda", "dml"):
            for p in GPU_PROVIDERS:
                if p in have and (wanted in ("auto", "gpu") or p.lower().startswith(wanted)):
                    chain.append(p)
        if "DmlExecutionProvider" in chain:
            opts.enable_mem_pattern = False
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        chain.append("CPUExecutionProvider")
        return ort.InferenceSession(path, sess_options=opts, providers=chain)

    # -- picture helpers (Pillow first, OpenCV when Pillow is not there)
    def _resize(self, arr, w, h, smooth_up=False):
        np = self.np
        try:
            from PIL import Image
            if arr.dtype == np.uint8:
                return np.asarray(Image.fromarray(arr).resize((w, h), Image.LANCZOS))
            return np.asarray(Image.fromarray(arr.astype("float32")).resize((w, h), Image.BICUBIC))
        except ImportError:
            import cv2
            interp = cv2.INTER_CUBIC if (smooth_up or arr.dtype != np.uint8) else cv2.INTER_AREA
            return cv2.resize(arr, (w, h), interpolation=interp)

    def _feed(self, rgb):
        np, spec = self.np, self.spec
        small = self._resize(rgb, self.side, self.side)
        a = np.asarray(small, dtype=np.float32)
        a = a / (float(a.max()) or 1.0) if spec["norm"] == "max" else a / 255.0
        a = (a - np.array(spec["mean"], dtype=np.float32)) / np.array(spec["std"], dtype=np.float32)
        return {self.input_name: np.ascontiguousarray(a.transpose(2, 0, 1)[None], dtype=np.float32)}

    def _post(self, out):
        np = self.np
        p = np.asarray(out[0], dtype=np.float32)
        p = p[0, 0] if p.ndim == 4 else (p[0] if p.ndim == 3 else p)
        if self.spec["out"] == "sigmoid":
            if float(p.min()) < 0.0 or float(p.max()) > 1.0:          # logits -> probability (an already-sigmoid export stays as it is)
                p = 1.0 / (1.0 + np.exp(-np.clip(p, -30.0, 30.0)))
        else:
            lo, hi = float(p.min()), float(p.max())
            p = (p - lo) / ((hi - lo) or 1.0)
        return np.clip(p, 0.0, 1.0)

    def predict(self, rgb):
        np = self.np
        h, w = rgb.shape[:2]
        feed = self._feed(rgb)
        try:
            out = self.sess.run(None, feed)
        except Exception:  # noqa: BLE001 - a GPU that ran out of memory: finish on the CPU
            if self.provider == "CPUExecutionProvider":
                raise
            self.sess = self._open(self.path, "cpu")
            self.provider = self.sess.get_providers()[0]
            out = self.sess.run(None, feed)
        mask = self._post(out)
        if mask.shape != (h, w):
            mask = np.clip(np.asarray(self._resize(mask.astype("float32"), w, h, smooth_up=True), dtype=np.float32), 0.0, 1.0)
        return mask


def _read_rgb(path):
    """(H, W, 3) uint8, EXIF rotation applied; Pillow first, OpenCV otherwise."""
    import numpy as np
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        return np.asarray(im)
    except ImportError:
        import cv2
        arr = cv2.imread(path, cv2.IMREAD_COLOR)
        if arr is None:
            raise RuntimeError("cannot read the photo")
        return cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)


def _feather(alpha, radius):
    if radius <= 0:
        return alpha
    try:
        from PIL import Image, ImageFilter
        import numpy as np
        im = Image.fromarray((alpha * 255.0 + 0.5).astype("uint8")).filter(ImageFilter.GaussianBlur(radius))
        return np.asarray(im, dtype="float32") / 255.0
    except ImportError:
        import cv2
        k = int(radius * 3) * 2 + 1
        return cv2.GaussianBlur(alpha, (k, k), radius)


def _write_png(path, arr):
    try:
        from PIL import Image
        Image.fromarray(arr).save(path, "PNG", compress_level=3)
    except ImportError:
        import cv2
        a = arr if arr.ndim == 2 else cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
        ok, buf = cv2.imencode(".png", a, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        if not ok:
            raise RuntimeError("cannot write the PNG")
        with open(path, "wb") as fh:
            fh.write(buf.tobytes())


def cut(matter, rgb, feather=0.0, keep_size=True):
    """-> (rgba uint8 (H, W, 4), mask uint8 (H, W)); the long side is cut to SMALL_SIDE when keep_size is False."""
    import numpy as np
    if not keep_size and max(rgb.shape[:2]) > SMALL_SIDE:
        s = SMALL_SIDE / float(max(rgb.shape[:2]))
        rgb = matter._resize(rgb, max(1, int(rgb.shape[1] * s)), max(1, int(rgb.shape[0] * s)))
    alpha = _feather(matter.predict(rgb), feather)
    mask = (np.clip(alpha, 0.0, 1.0) * 255.0 + 0.5).astype("uint8")
    return np.dstack([rgb, mask]), mask


def synthetic_photo(w=1024, h=768):
    """A test picture (no real photo needed): a soft gradient background and a textured 'subject' in the middle."""
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w].astype("float32")
    bg = np.dstack([60 + 90 * xx / w, 110 + 60 * yy / h, 150 - 50 * xx / w])
    cx, cy, rx, ry = w * 0.5, h * 0.52, w * 0.22, h * 0.36
    inside = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 < 1.0
    tex = 170 + 70 * np.sin(xx / 9.0) * np.cos(yy / 11.0)
    subj = np.dstack([tex, 90 + 0 * tex, 60 + 0.3 * tex])
    return np.clip(np.where(inside[..., None], subj, bg), 0, 255).astype("uint8")


def _data_root():
    try:
        import nm_data
        return nm_data.data_root(HERE)
    except Exception:  # noqa: BLE001
        return os.environ.get("NM_DATA") or os.path.join(os.path.expanduser("~"), "NMarketing-data")


def _cli_status(args):
    class A:     # a tiny stand-in for the agent: only DATA is needed for the status
        DATA = args.data_root or _data_root()
        DOWNLOADS = None
    py, info = find_python(A)
    if args.runtime_ok:
        return 0 if py else 1
    out = {"data": A.DATA, "models": model_states(A)}
    out["python"] = py
    out["runtime"] = info if py else {"ok": False, "message": info}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cli_test(args):
    """Re-runs `bench` inside the Python that has onnxruntime (the agent's own usually does not)."""
    class A:
        DATA = args.data_root or _data_root()
        DOWNLOADS = None
    py, info = find_python(A)
    if py is None:
        print("No Python on this computer can run the models yet: %s" % info)
        print("Install the runtime (and the models) with Install-Matting.bat, then run this test again.")
        return 1
    print("Python: %s (onnxruntime %s, %s)" % (py, info.get("ort"), ", ".join(p.replace("ExecutionProvider", "") for p in info.get("providers") or [])))
    cmd = [py, os.path.abspath(__file__), "bench", "--model", args.model, "--runs", str(args.runs), "--data-root", A.DATA]
    return subprocess.call(cmd, env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))


def _cli_run(args):
    rgb = _read_rgb(args.image)
    t0 = time.time()
    print("PHASE loading %s" % args.model, flush=True)
    matter = Matter(args.model, args.model_file, args.provider)
    print("PHASE running", flush=True)
    rgba, mask = cut(matter, rgb, feather=args.feather, keep_size=not args.no_keep_size)
    os.makedirs(args.out_dir, exist_ok=True)
    _write_png(os.path.join(args.out_dir, "cutout.png"), rgba)
    _write_png(os.path.join(args.out_dir, "mask.png"), mask)
    res = {"model": args.model, "seconds": round(time.time() - t0, 2), "size": [int(rgba.shape[1]), int(rgba.shape[0])],
           "device": matter.provider.replace("ExecutionProvider", "").replace("Dml", "dml").replace("CUDA", "cuda").replace("CPU", "cpu")}
    print("RESULT " + json.dumps(res), flush=True)
    return 0


def _bench_one(key, path, provider, runs, out_dir=None):
    import numpy as np
    rgb = synthetic_photo()
    t0 = time.time()
    matter = Matter(key, path, provider)
    load = time.time() - t0
    times = []
    rgba = mask = None
    for _ in range(max(1, runs)):
        t = time.time()
        rgba, mask = cut(matter, rgb)
        times.append(time.time() - t)
    inside = float(mask[300:460, 420:600].mean()) / 255.0
    corner = float(mask[:80, :80].mean()) / 255.0
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        _write_png(os.path.join(out_dir, "cutout.png"), rgba)
        _write_png(os.path.join(out_dir, "mask.png"), mask)
    return {"model": key, "device": matter.provider.replace("ExecutionProvider", "").lower().replace("dml", "dml"),
            "load_s": round(load, 2), "run_s": round(min(times), 2), "runs": len(times), "image": "1024x768 synthetic",
            "subject_mask": round(inside, 3), "corner_mask": round(corner, 3),
            "plausible": bool(inside > 0.5 and corner < 0.4), "onnxruntime": matter.ort.__version__}


def _cli_bench(args):
    root = args.data_root or _data_root()
    keys = ORDER if args.model in ("all", "", None) else (args.model,)
    results = []
    for key in keys:
        path = args.model_file if (args.model_file and len(keys) == 1) else model_file(root, key)
        if not os.path.isfile(path):
            results.append({"model": key, "error": "not installed (Download-Models.bat --only %s)" % MODELS[key]["package"]})
            continue
        print("PHASE bench %s" % key, flush=True)
        try:
            results.append(_bench_one(key, path, args.provider, args.runs, args.out_dir if len(keys) == 1 else None))
        except Exception as e:  # noqa: BLE001 - one broken model must not hide the others
            results.append({"model": key, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    if len(keys) == 1:
        print("RESULT " + json.dumps(results[0], ensure_ascii=False), flush=True)
        return 0 if "error" not in results[0] else 1
    if args.json:
        print("RESULT " + json.dumps({"results": results}, ensure_ascii=False), flush=True)
    else:
        for r in results:
            if "error" in r:
                print("%-14s  %s" % (r["model"], r["error"]))
            else:
                print("%-14s  %-4s  load %5.1fs  run %5.2fs  subject %.2f  corner %.2f  %s" % (
                    r["model"], r["device"], r["load_s"], r["run_s"], r["subject_mask"], r["corner_mask"], "OK" if r["plausible"] else "CHECK"))
    return 0 if all("error" not in r for r in results) else 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Photo background matting on the node")
    sub = ap.add_subparsers(dest="cmd")
    st = sub.add_parser("status")
    st.add_argument("--data-root", default="")
    st.add_argument("--runtime-ok", action="store_true", help="print nothing; exit 0 when some Python here can run the models, else 1")
    ts = sub.add_parser("test", help="find the right Python and time every installed model on a test picture (Test-Matting.bat)")
    ts.add_argument("--model", default="all")
    ts.add_argument("--data-root", default="")
    ts.add_argument("--runs", type=int, default=3)
    bn = sub.add_parser("bench")
    bn.add_argument("--model", default="all")
    bn.add_argument("--model-file", default="")
    bn.add_argument("--data-root", default="")
    bn.add_argument("--out-dir", default="")
    bn.add_argument("--provider", default=os.environ.get("NM_MATTING_PROVIDER") or "auto")
    bn.add_argument("--runs", type=int, default=3)
    bn.add_argument("--json", action="store_true")
    rn = sub.add_parser("run")
    rn.add_argument("--model", required=True, choices=list(MODELS))
    rn.add_argument("--model-file", required=True)
    rn.add_argument("--image", required=True)
    rn.add_argument("--out-dir", required=True)
    rn.add_argument("--feather", type=float, default=0.0)
    rn.add_argument("--no-keep-size", action="store_true")
    rn.add_argument("--provider", default=os.environ.get("NM_MATTING_PROVIDER") or "auto")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        return _cli_status(args)
    if args.cmd == "test":
        return _cli_test(args)
    if args.cmd == "bench":
        return _cli_bench(args)
    if args.cmd == "run":
        return _cli_run(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
