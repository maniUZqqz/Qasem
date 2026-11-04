#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Robust Video Matting on the node - the fast, steady way to cut the subject out of a video (agent 2.5).

RVM (PeterL1n/RobustVideoMatting, mobilenetv3, ONNX fp32, ~14 MB) is a model made for VIDEO: it carries a small recurrent
state from frame to frame, so the edge of the subject stays put instead of flickering the way a per-frame model (BiRefNet)
does, and it is an order of magnitude faster. License of the model: GPL-3.0 (internal use on the owner's own computer).

    python edit_rvm.py --model rvm_mobilenetv3_fp32.onnx --video clip.mp4 --out matte.mp4 --ffmpeg ffmpeg --fps 24 --size 406x720

This one file is both the library that edit_jobs.py / edit_render.py use (everything above `class Matter` needs only the
standard library, Python 3.8+) and the command line that actually runs the model. The model needs `numpy` and `onnxruntime`
in SOME Python of this computer; `find_python()` looks in the agent's own Python and then in the environments the node
already has (the voice service, the audio engines). Nothing is installed here: when no Python has them, `status()` says so,
caps.edit.matte_engine stays on BiRefNet and the job uses the old per-frame path. NM_RVM=0 turns RVM off altogether;
NM_RVM_PYTHON=<python.exe> names the Python to use; NM_RVM_PROVIDER=cpu forces the CPU.

The model file comes from the site ({site}/3d/files/downloads/, mirrored there because the line to GitHub is slow or blocked),
resumable and checked by size + sha256 (downloads/matting.json is the one place that knows both): Download-Models.bat and the
agent's start-up download it like every other model, and `ensure_model()` fetches it when the first video job finds it missing.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

VERSION = "1.0"
PACKAGE = "video-matting"
MODEL_FILE = "rvm_mobilenetv3_fp32.onnx"
MANIFEST_NAME = "matting.json"
MANIFEST_ID = "matting:rvm-mobilenetv3-fp32"
#: RVM's own guidance: pick downsample_ratio so the long side the network sees is ~256-512 px (1080p -> 0.25, 4K -> 0.125)
TARGET_SIDE = 480
MIN_RATIO = 0.125
#: the first frame is fed this many extra times so the recurrent state has settled before the first real output
WARMUP = 2
GPU_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider")
HERE = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0

_PROBE = (
    "import json\n"
    "import numpy\n"
    "import onnxruntime as o\n"
    "print(json.dumps({'ort': o.__version__, 'np': numpy.__version__, 'providers': list(o.get_available_providers())}))\n"
)
_PY_CACHE = {}              # (python path, mtime) -> probe result (dict) or {"error": ...}
_SHA_OK = {}                # model path -> (size, mtime) already verified against the manifest in this process
_LOCK = threading.Lock()


class Unavailable(Exception):
    """RVM cannot run on this node right now (no Python with onnxruntime, model not fetchable, switched off ...)."""


# ───────────────────────────────────────────── what to do for a frame size

def downsample_ratio(width, height):
    """RVM's `downsample_ratio` for a frame: 1.0 up to 512 px (the network already sees a small picture), else the ratio that
    brings the long side to about TARGET_SIDE px - 0.667 for a 720-px proxy, 0.25 for 1080p, 0.125 for 4K and above."""
    side = max(int(width), int(height))
    if side <= 512:
        return 1.0
    return round(max(MIN_RATIO, min(1.0, float(TARGET_SIDE) / side)), 3)


def even_size(width, height):
    """The matte video is H.264 yuv420p: both sides even."""
    return max(2, int(width) // 2 * 2), max(2, int(height) // 2 * 2)


def enabled():
    return (os.environ.get("NM_RVM") or "1").strip().lower() not in ("0", "off", "no", "false")


# ───────────────────────────────────────────── the model file and its manifest

def manifest_item(path=None):
    """The one item of downloads/matting.json: {id, urls, dest, size, sha256, ...}."""
    path = path or os.path.join(HERE, "downloads", MANIFEST_NAME)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    for item in doc.get("items") or []:
        if item.get("id") == MANIFEST_ID:
            return item
    raise Unavailable("downloads/%s has no item %s" % (MANIFEST_NAME, MANIFEST_ID))


def model_file(data_root):
    """Where the model lives: <data folder>/models/video-matting/ (the manifest's dest: {MODELS}\\video-matting\\...)."""
    return os.path.join(data_root, "models", "video-matting", MODEL_FILE)


def have_model(data_root):
    """The file is there and has the size the manifest says (a cheap check; the checksum is verified when it is used)."""
    path = model_file(data_root)
    try:
        return os.path.isfile(path) and os.path.getsize(path) == int(manifest_item().get("size") or -1)
    except (OSError, ValueError, Unavailable):
        return False


def _sha256(path):
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verified(path, item=None):
    """The file at `path` is the model of the manifest (size + sha256; the hash of 14 MB is checked once per process)."""
    try:
        item = item or manifest_item()
        st = os.stat(path)
    except (OSError, Unavailable):
        return False
    if st.st_size != int(item.get("size") or -1):
        return False
    key = (st.st_size, st.st_mtime_ns)
    with _LOCK:
        if _SHA_OK.get(path) == key:
            return True
    if _sha256(path) != str(item.get("sha256") or "").lower():
        return False
    with _LOCK:
        _SHA_OK[path] = key
    return True


def ensure_model(agent, say=None, stall=180):
    """The model's path; fetched from the site when it is missing (the first video job on a node that never ran
    Download-Models). Raises Unavailable with the reason when it cannot be had (the job then uses BiRefNet)."""
    import nm_fetch

    item = manifest_item()
    path = model_file(agent.DATA)
    if verified(path, item):
        return path
    base = ""
    try:
        base = agent.site_base()
    except Exception:  # noqa: BLE001
        base = ""
    token = ((getattr(agent, "CONFIG", None) or {}).get("token")) or os.environ.get("NM_TOKEN") or ""
    urls = []
    for u in item.get("urls") or []:
        if "{SITE}" in u:
            if not base:
                continue                                    # this node does not know its site
            u = u.replace("{SITE}", base.rstrip("/"))
        if "{" not in u:
            urls.append(u)
    if not urls:
        raise Unavailable("no download address for the video-matting model (the site address of this node is unknown)")
    tmp = path + ".lazy"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    errors = []
    for url in urls:
        try:
            if say:
                say("model|%s" % os.path.basename(path))
            headers = nm_fetch.site_headers(token) if base and url.startswith(base) else {}
            nm_fetch.fetch(url, tmp, headers=headers, size=int(item["size"]), sha256=item.get("sha256"), stall=stall,
                           label=os.path.basename(path), out=lambda m: None)
            os.replace(tmp, path)
            return path
        except nm_fetch.FetchError as e:
            errors.append(str(e))
        except OSError as e:
            errors.append(str(e))
    raise Unavailable("the video-matting model (%s, 14 MB) could not be fetched: %s" % (MODEL_FILE, "; ".join(errors)[:300]))


# ───────────────────────────────────────────── which Python can run it

def probe_python(py, timeout=90):
    """{"ort", "np", "providers"} when `py` can import numpy + onnxruntime, else {"error": why}. Cached per path + mtime."""
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
        else:
            tail = (r.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
            info = {"error": tail[:200]}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        info = {"error": str(e)[:200]}
    with _LOCK:
        _PY_CACHE[key] = info
    return info


def candidate_pythons(agent=None):
    """Pythons worth asking, best guesses first: the owner's choice, the agent's own, the voice service's environment, the
    audio engines' environments in the data folder."""
    cands = []
    pick = (os.environ.get("NM_RVM_PYTHON") or "").strip().strip('"')
    if pick:
        cands.append(pick)
    cands.append(sys.executable)
    if agent is not None:
        try:
            cands.append(agent.voice_venv_python())
        except Exception:  # noqa: BLE001
            pass
        venvs = os.path.join(getattr(agent, "DATA", "") or "", "venvs")
        try:
            for name in sorted(os.listdir(venvs)):
                for rel in (("Scripts", "python.exe"), ("bin", "python")):
                    cands.append(os.path.join(venvs, name, *rel))
        except OSError:
            pass
    seen, out = set(), []
    for c in cands:
        if c and os.path.isfile(c) and os.path.normcase(os.path.abspath(c)) not in seen:
            seen.add(os.path.normcase(os.path.abspath(c)))
            out.append(c)
    return out


def find_python(agent=None, probe=True):
    """(python path, probe info) of the best Python for RVM - one whose onnxruntime has a GPU provider wins over a CPU-only
    one - or (None, why)."""
    if not enabled():
        return None, "RVM is switched off (NM_RVM=0)"
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
    return None, "no Python on this computer has numpy + onnxruntime (%s)" % ("; ".join(why[:3]) or "none found")


def status(agent=None, probe=True):
    """What the heartbeat says about RVM: {"runtime", "model", "provider", "ort"}."""
    py, info = find_python(agent, probe)
    out = {"runtime": bool(py), "model": False, "provider": "", "ort": ""}
    if py:
        provs = info.get("providers") or []
        out["provider"] = next((p.replace("ExecutionProvider", "") for p in GPU_PROVIDERS if p in provs), "CPU")
        out["ort"] = str(info.get("ort") or "")
    else:
        out["why"] = str(info)[:200]
    try:
        out["model"] = have_model(agent.DATA) if agent is not None else False
    except Exception:  # noqa: BLE001
        out["model"] = False
    return out


# ───────────────────────────────────────────── running it from the agent

def run(job, agent, ff, video, size, fps, frames, out_path, say, limit=3600.0):
    """Cut `video` (sampled at `fps`) into the grey video `out_path`. → meta {"frames", "fps", "model", "provider", "ratio"}.
    Raises Unavailable BEFORE anything is done when RVM cannot run (the caller falls back to BiRefNet); a failure after the
    model started is a RuntimeError (and the job fails with its text)."""
    py, info = find_python(agent)
    if py is None:
        raise Unavailable(info)
    model = ensure_model(agent, lambda message: say(message, 0.04))
    w, h = size
    cmd = [py, os.path.abspath(__file__), "--model", model, "--video", video, "--out", out_path, "--ffmpeg", ff, "--fps", "%g" % fps,
           "--size", "%dx%d" % (w, h), "--frames", str(int(frames))]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    errf = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir(), env=env,
                            creationflags=NO_WINDOW)
    state = {"done": 0, "result": None}

    def read():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("PROGRESS "):
                try:
                    state["done"] = int(line.split()[1])
                except (ValueError, IndexError):
                    pass
            elif line.startswith("RESULT "):
                try:
                    state["result"] = json.loads(line[7:])
                except ValueError:
                    pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    started = time.time()
    try:
        while proc.poll() is None:
            time.sleep(0.5)
            say("matte|%d|%d" % (min(state["done"], int(frames)), int(frames)), min(0.95, 0.06 + 0.84 * state["done"] / max(1.0, float(frames))))
            if time.time() - started > limit:
                proc.kill()
                raise RuntimeError("RVM did not finish in %d s" % limit)
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
    if proc.returncode != 0 or not state["result"] or not os.path.isfile(out_path):
        raise RuntimeError("RVM failed (exit %s): %s" % (proc.returncode, tail or "no message"))
    meta = dict(state["result"])
    meta["python_ort"] = info.get("ort")
    return meta


# ───────────────────────────────────────────── the model itself (needs numpy + onnxruntime)

class Matter:
    """One RVM session. `step(frame)` takes an RGB uint8 array (H, W, 3) and returns the alpha as a uint8 array (H, W);
    the recurrent state is carried from call to call (`stateful=False` forgets it every frame - only for comparisons)."""

    def __init__(self, model, provider="auto", threads=0, stateful=True, ratio=None):
        import numpy as np
        import onnxruntime as ort

        self.np, self.ort = np, ort
        self.model, self.threads, self.stateful, self.fixed_ratio = model, int(threads or 0), stateful, ratio
        self.wanted = (provider or "auto").lower()
        self.sess = self._open(self.wanted)
        self.provider = self.sess.get_providers()[0]
        self.reset()

    def _open(self, wanted):
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
        return ort.InferenceSession(self.model, sess_options=opts, providers=chain)

    def reset(self):
        z = self.np.zeros((1, 1, 1, 1), dtype=self.np.float32)
        self.rec = [z, z, z, z]

    def step(self, rgb):
        np = self.np
        h, w = rgb.shape[:2]
        ratio = self.fixed_ratio or downsample_ratio(w, h)
        x = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32)[None]
        x *= 1.0 / 255.0
        if not self.stateful:
            self.reset()
        feed = {"src": x, "r1i": self.rec[0], "r2i": self.rec[1], "r3i": self.rec[2], "r4i": self.rec[3],
                "downsample_ratio": np.array([ratio], dtype=np.float32)}
        try:
            pha, r1, r2, r3, r4 = self.sess.run(["pha", "r1o", "r2o", "r3o", "r4o"], feed)
        except Exception:  # noqa: BLE001 - a GPU that ran out of memory: finish on the CPU (the state is plain numpy)
            if self.provider == "CPUExecutionProvider":
                raise
            self.sess = self._open("cpu")
            self.provider = self.sess.get_providers()[0]
            pha, r1, r2, r3, r4 = self.sess.run(["pha", "r1o", "r2o", "r3o", "r4o"], feed)
        self.rec = [r1, r2, r3, r4]
        return (np.clip(pha[0, 0], 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    def warm(self, rgb, times=WARMUP):
        """Let the state settle on the first frame (output thrown away)."""
        for _ in range(int(times)):
            self.step(rgb)


# ───────────────────────────────────────────── the command line (the job)

def probe_size(ff, video):
    """(width, height) of the first video stream, read from ffmpeg's own banner."""
    r = subprocess.run([ff, "-hide_banner", "-i", video], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    for line in r.stderr.decode("utf-8", "replace").splitlines():
        if " Video:" in line:
            m = re.search(r"[ ,](\d{2,5})x(\d{2,5})[ ,\[]", line + " ")
            if m:
                return int(m.group(1)), int(m.group(2))
    raise RuntimeError("could not read the size of the clip")


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Robust Video Matting: a clip -> a grey matte video")
    ap.add_argument("--model", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--size", default="")
    ap.add_argument("--frames", type=int, default=0, help="expected number of frames (progress only)")
    ap.add_argument("--provider", default=os.environ.get("NM_RVM_PROVIDER") or "auto")
    ap.add_argument("--warmup", type=int, default=WARMUP)
    ap.add_argument("--no-state", action="store_true", help="forget the state every frame (comparison only)")
    args = ap.parse_args(argv)
    import numpy as np

    fps = max(1.0, min(60.0, args.fps))
    if args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
    else:
        w, h = probe_size(args.ffmpeg, args.video)
    w, h = even_size(w, h)
    matter = Matter(args.model, args.provider, stateful=not args.no_state)
    dec = subprocess.Popen([args.ffmpeg, "-v", "error", "-i", args.video, "-an", "-vf", "fps=%g,scale=%d:%d:flags=bilinear" % (fps, w, h),
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    enc = subprocess.Popen([args.ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "%dx%d" % (w, h), "-framerate", "%g" % fps,
                            "-i", "-", "-vf", "format=gray", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            args.out], stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
    size = w * h * 3
    n, t0, enc_broke = 0, time.time(), False
    try:
        while True:
            buf = dec.stdout.read(size)
            if len(buf) < size:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
            if n == 0 and not args.no_state:
                matter.warm(frame, args.warmup)
            try:
                enc.stdin.write(matter.step(frame).tobytes())
            except (BrokenPipeError, OSError):
                enc_broke = True                      # the encoder died: its own message is read below
                break
            n += 1
            if n % 4 == 0:
                print("PROGRESS %d" % n, flush=True)
    finally:
        try:
            dec.stdout.close()
            dec.kill()
            dec.wait()
        except OSError:
            pass
        try:
            enc.stdin.close()
        except OSError:
            pass
    err = enc.stderr.read().decode("utf-8", "replace")
    enc.wait()
    if enc_broke or enc.returncode != 0 or not os.path.isfile(args.out):
        raise RuntimeError("could not encode the matte video: %s" % (err[-300:] or "ffmpeg stopped"))
    if n == 0:
        raise RuntimeError("no frames could be read from the clip")
    seconds = round(time.time() - t0, 2)
    print("RESULT " + json.dumps({"frames": n, "fps": fps, "model": "rvm-mobilenetv3", "provider": matter.provider.replace("ExecutionProvider", ""),
                                  "ratio": downsample_ratio(w, h), "size": [w, h], "seconds": seconds,
                                  "fps_run": round(n / max(0.001, seconds), 1)}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(1)
