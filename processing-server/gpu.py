#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GPU-first helpers of the processing node (agent 2.11). Python 3.8+ standard library only.

The owner asked: "why does everything use the weak CPU and not the strong GPU?". This module is the one place that knows

  * what the GPU is doing (nvidia-smi snapshots, a per-job sampler: utilisation / VRAM / temperature / power),
  * which device a finished job really used (cuda / directml / nvenc / cpu) and WHY when it was the CPU - the verdict is
    stored in the job's meta and shown in the panel, a CPU fallback is a visible warning,
  * which ffmpeg to use (one with a working NVENC encoder first) and whether NVDEC decoding (-hwaccel cuda) works,
  * how Ollama is started for the GPU (flash attention, q8 KV cache, one model at a time) and a sensible num_ctx per
    model size, so a model that fits the card is never pushed to the CPU by a huge context,
  * the CUDA runtime DLL folders of the pip "nvidia-*" wheels (cuBLAS / cuDNN for CTranslate2 / onnxruntime-gpu).

Everything that runs a process takes an injectable `run` (tests use fakes). Nothing here raises for a missing GPU: the
answers are None / False and the caller logs the fallback.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

VERSION = "1.0"

#: kinds that are EXPECTED to use the GPU: a CPU verdict for one of them is a warning in the panel
GPU_KINDS = ("comfy.", "ollama.chat", "ollama.generate", "ollama.vision", "voice.sfx", "voice.music", "photo.matting",
             "edit.matte", "edit.render", "asr.", "selftest.ollama", "selftest.comfy", "selftest.ffmpeg", "selftest.gpu")
#: voice.tts runs on the GPU only for the MOSS engines
MOSS_ENGINES = ("moss-fa", "moss", "moss-tts")

OLLAMA_ENV = {
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_NUM_PARALLEL": "1",
}

DEVICE_FA = {"cuda": "کارت گرافیک (CUDA)", "directml": "کارت گرافیک (DirectML)", "nvenc": "کارت گرافیک (NVENC)",
             "cpu": "پردازنده (CPU)", "mixed": "کارت گرافیک + پردازنده", "unknown": "نامشخص", "none": "بدون پردازش گرافیکی"}


def expects_gpu(kind, payload=None):
    """Is this kind of job supposed to run on the GPU (so that a CPU verdict is a warning)?"""
    kind = kind or ""
    if kind == "voice.tts":
        eng = str((payload or {}).get("engine") or "").lower()
        return eng in MOSS_ENGINES
    return any(kind == k or (k.endswith(".") and kind.startswith(k)) for k in GPU_KINDS)


# ───────────────────────────────────────────── nvidia-smi

SMI_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,name"


def _num(text):
    try:
        return float(str(text).strip().split()[0])
    except (ValueError, IndexError):
        return None


def smi_exe(which=None):
    return (which or shutil.which)("nvidia-smi")


def snapshot(run=None, which=None, timeout=10):
    """One nvidia-smi reading of the first GPU: {util, vram_used_mb, vram_total_mb, temp_c, power_w, name} or None."""
    exe = smi_exe(which)
    if not exe:
        return None
    try:
        out = (run or subprocess.run)([exe, "--query-gpu=" + SMI_QUERY, "--format=csv,noheader,nounits"],
                                      capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    line = (out or "").strip().splitlines()
    if not line:
        return None
    parts = [p.strip() for p in line[0].split(",")]
    if len(parts) < 3:
        return None
    util, used, total = _num(parts[0]), _num(parts[1]), _num(parts[2])
    if util is None and used is None:
        return None
    return {"util": int(util) if util is not None else None, "vram_used_mb": int(used) if used is not None else None,
            "vram_total_mb": int(total) if total is not None else None,
            "temp_c": int(_num(parts[3])) if len(parts) > 3 and _num(parts[3]) is not None else None,
            "power_w": round(_num(parts[4]), 1) if len(parts) > 4 and _num(parts[4]) is not None else None,
            "name": parts[5] if len(parts) > 5 else ""}


def driver_info(run=None, which=None):
    exe = smi_exe(which)
    if not exe:
        return {}
    try:
        out = (run or subprocess.run)([exe, "--query-gpu=driver_version,name", "--format=csv,noheader"],
                                      capture_output=True, text=True, timeout=15).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return {}
    if not out:
        return {}
    parts = [p.strip() for p in out[0].split(",")]
    return {"driver": parts[0], "name": parts[1] if len(parts) > 1 else ""}


def compute_apps(run=None, which=None):
    """Programs that hold the GPU right now: [{pid, name, vram_mb|None}] (Windows WDDM often hides the VRAM figure)."""
    exe = smi_exe(which)
    if not exe:
        return []
    try:
        out = (run or subprocess.run)([exe, "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
                                      capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    apps = []
    for line in (out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit():
            apps.append({"pid": int(parts[0]), "name": re.split(r"[\\/]", parts[1])[-1],
                         "vram_mb": int(_num(parts[2])) if len(parts) > 2 and _num(parts[2]) is not None else None})
    return apps


class GpuSampler:
    """Samples the GPU while a job runs (default every 3 s) and answers a small summary - utilisation, VRAM, heat, power and a
    thinned series for the panel's chart. One sampler per job; `snap` can be replaced in tests."""

    def __init__(self, interval=3.0, snap=None, max_points=40):
        self.interval = max(0.2, float(interval))
        self.snap = snap or snapshot
        self.max_points = max_points
        self.rows = []                     # (t, util, vram_used, temp, power)
        self.total = None
        self.name = ""
        self.t0 = time.time()
        self._stop = threading.Event()
        self._thread = None

    def sample(self):
        s = self.snap()
        if not s:
            return None
        self.total = s.get("vram_total_mb") or self.total
        self.name = s.get("name") or self.name
        self.rows.append((round(time.time() - self.t0, 1), s.get("util"), s.get("vram_used_mb"), s.get("temp_c"), s.get("power_w")))
        return s

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.sample()
            except Exception:  # noqa: BLE001 - sampling must never hurt a job
                pass
            self._stop.wait(self.interval)

    def start(self):
        self.t0 = time.time()
        self.sample()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gpu-sampler")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        try:
            self.sample()
        except Exception:  # noqa: BLE001
            pass
        return self.summary()

    def summary(self):
        return summarize(self.rows, self.total, self.name, self.max_points)


def summarize(rows, total=None, name="", max_points=40):
    """rows: (t, util, vram_used_mb, temp_c, power_w) -> the dict stored in the job meta (empty dict without samples)."""
    if not rows:
        return {}
    utils = [r[1] for r in rows if r[1] is not None]
    vram = [r[2] for r in rows if r[2] is not None]
    temps = [r[3] for r in rows if r[3] is not None]
    power = [r[4] for r in rows if r[4] is not None]
    step = max(1, (len(rows) + max_points - 1) // max_points)
    series = [[r[0], r[1], r[2]] for r in rows[::step]]
    out = {"samples": len(rows), "name": name or "", "vram_total_mb": total}
    if utils:
        out.update(util_avg=round(sum(utils) / len(utils), 1), util_max=max(utils))
    if vram:
        out.update(vram_min_mb=min(vram), vram_max_mb=max(vram), vram_start_mb=vram[0])
    if temps:
        out["temp_max_c"] = max(temps)
    if power:
        out["power_max_w"] = max(power)
    out["series"] = series
    return out


# ───────────────────────────────────────────── which device did a job really use?

ACTIVE_UTIL = 12          # %: a GPU that never went above this was idle
ACTIVE_VRAM_MB = 250      # MB: ...and one whose memory never grew by this much was not loaded


def gpu_was_busy(summary):
    if not summary:
        return None
    util_max = summary.get("util_max")
    grown = None
    if summary.get("vram_max_mb") is not None and summary.get("vram_start_mb") is not None:
        grown = summary["vram_max_mb"] - summary["vram_start_mb"]
    if util_max is None and grown is None:
        return None
    return bool((util_max or 0) >= ACTIVE_UTIL or (grown or 0) >= ACTIVE_VRAM_MB)


def provider_device(provider):
    """'CUDAExecutionProvider' / 'DmlExecutionProvider' / 'CPUExecutionProvider' -> cuda / directml / cpu."""
    p = str(provider or "").lower()
    if "cuda" in p or "tensorrt" in p:
        return "cuda"
    if "dml" in p or "directml" in p:
        return "directml"
    if "cpu" in p:
        return "cpu"
    return ""


def norm_device(value):
    """'dml' / 'DirectML' / 'cuda bfloat16' / 'CPUExecutionProvider' -> cuda | directml | nvenc | cpu | mixed | '' (unknown word)."""
    v = str(value or "").strip().lower()
    if not v:
        return ""
    if v in DEVICE_FA:
        return v
    if v.startswith("cuda") or "tensorrt" in v:
        return "cuda"
    if v.startswith("dml") or "directml" in v:
        return "directml"
    if v.startswith("nvenc"):
        return "nvenc"
    if v.startswith("cpu"):
        return "cpu"
    return ""


def classify(kind, payload, meta, summary):
    """The verdict stored with every finished job: (device, note, warning).

    A handler that knows the device says so in its meta (meta["device"], meta["device_note"]); otherwise it is inferred from
    meta["provider"] (ONNX), meta["encoder"] (ffmpeg) or the GPU samples taken while the job ran. `warning` is a Persian
    sentence when the job was supposed to use the GPU and did not."""
    meta = meta or {}
    device = norm_device(meta.get("device"))
    note = str(meta.get("device_note") or "")
    if not device:
        dev = provider_device(meta.get("provider"))
        if dev:
            device = dev
            note = note or "ONNX provider %s" % meta.get("provider")
    if not device and meta.get("encoder"):
        enc = str(meta["encoder"])
        if "NVENC" in enc.upper():
            device = "nvenc"
            note = note or enc
        else:
            device = "cpu"
            note = note or "software encoder (%s)" % enc
    if not device:
        busy = gpu_was_busy(summary)
        if busy is True:
            device, note = "cuda", note or "inferred from nvidia-smi: the GPU was busy during the job"
        elif busy is False:
            device, note = "cpu", note or "inferred from nvidia-smi: the GPU stayed idle during the job"
        else:
            device = "unknown"
    warning = ""
    if device in ("cpu", "mixed") and expects_gpu(kind, payload):
        why = note or "reason not reported"
        warning = ("این کار قرار بود روی کارت گرافیک اجرا شود ولی %s اجرا شد (%s)" % (
            "روی پردازنده" if device == "cpu" else "بخشی از آن روی پردازنده", why))
    return device, note, warning


def stamp_meta(meta, kind, payload, summary):
    """Add device / device_note / device_warning / gpu to a finished job's meta (never overwrites a handler's own `device`)."""
    meta = dict(meta or {})
    device, note, warning = classify(kind, payload, meta, summary)
    meta["device"] = device
    if note:
        meta["device_note"] = note[:300]
    if warning:
        meta["device_warning"] = warning[:400]
    if summary:
        meta["gpu"] = summary
    return meta


# ───────────────────────────────────────────── ffmpeg: NVENC / NVDEC

def _run_default(cmd, timeout=60):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=timeout)


_FF = {}


def ffmpeg_report(ff, run=None, force=False):
    """What this ffmpeg can do for the GPU: {path, version, nvenc_h264, nvenc_hevc, cuda_decode, hwaccels, encoders_nv, error}.
    NVENC is proven with a real five-frame encode (an encoder that is merely compiled in proves nothing); NVDEC with a real
    hardware decode of a clip the encoder just made. Cached per path + mtime."""
    run = run or _run_default
    try:
        key = (ff, os.path.getmtime(ff))
    except OSError:
        return {"path": ff, "error": "file not found"}
    if key in _FF and not force:
        return _FF[key]
    rep = {"path": ff, "nvenc_h264": False, "nvenc_hevc": False, "cuda_decode": False, "hwaccels": [], "encoders_nv": []}
    try:
        ver = run([ff, "-hide_banner", "-version"], 30).stdout.decode("utf-8", "replace")
        m = re.search(r"version\s+(\S+)", ver)
        rep["version"] = m.group(1) if m else ""
        enc = run([ff, "-hide_banner", "-encoders"], 30).stdout.decode("utf-8", "replace")
        rep["encoders_nv"] = sorted(set(re.findall(r"\b((?:h264|hevc|av1)_nvenc)\b", enc)))
        hw = run([ff, "-hide_banner", "-hwaccels"], 30).stdout.decode("utf-8", "replace")
        rep["hwaccels"] = [ln.strip() for ln in hw.splitlines()[1:] if ln.strip()]
    except Exception as e:  # noqa: BLE001
        rep["error"] = "ffmpeg did not run: %s" % e
        _FF[key] = rep
        return rep
    tmp = tempfile.mkdtemp(prefix="nm-ffgpu-")
    try:
        for label, codec in (("nvenc_h264", "h264_nvenc"), ("nvenc_hevc", "hevc_nvenc")):
            if codec not in rep["encoders_nv"]:
                continue
            clip = os.path.join(tmp, codec + ".mp4")
            try:
                r = run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=1.2", "-frames:v", "10",
                         "-c:v", codec, "-pix_fmt", "yuv420p", clip], 40)
                rep[label] = r.returncode == 0 and os.path.isfile(clip)
                if r.returncode != 0:
                    rep.setdefault("nvenc_error", (r.stderr or b"").decode("utf-8", "replace").strip()[-300:])
            except Exception as e:  # noqa: BLE001
                rep.setdefault("nvenc_error", str(e)[:200])
            if label == "nvenc_h264" and rep[label] and "cuda" in rep["hwaccels"]:
                try:
                    r = run([ff, "-v", "error", "-hwaccel", "cuda", "-i", clip, "-f", "null", "-"], 40)
                    rep["cuda_decode"] = r.returncode == 0
                except Exception:  # noqa: BLE001
                    pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _FF[key] = rep
    return rep


def ffmpeg_candidates(data_dir="", extra=()):
    """Every ffmpeg worth asking, the owner's choice first: NM_FFMPEG, the ones this node installed itself, the kit's, PATH."""
    cands = list(extra or [])
    env = (os.environ.get("NM_FFMPEG") or "").strip().strip('"')
    if env:
        cands.insert(0, env)
    exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    if data_dir:
        cands += [os.path.join(data_dir, "vendor", "ffmpeg", "bin", exe),
                  os.path.join(data_dir, "tools", "PersianAiKit", "Video", "tools", "ffmpeg", "bin", exe)]
    which = shutil.which("ffmpeg")
    if which:
        cands.append(which)
    seen, out = set(), []
    for c in cands:
        if c and os.path.isfile(c) and os.path.normcase(os.path.abspath(c)) not in seen:
            seen.add(os.path.normcase(os.path.abspath(c)))
            out.append(c)
    return out


def best_ffmpeg(data_dir="", run=None, extra=(), probe=True):
    """(path, report): an ffmpeg with a working NVENC encoder wins; otherwise the first one that runs (and the report says the
    GPU encoder is missing so the bootstrap can install one from the site's mirror). (None, {}) when there is none."""
    cands = ffmpeg_candidates(data_dir, extra)
    if not cands:
        return None, {}
    if not probe:
        return cands[0], {"path": cands[0]}
    first = None
    for c in cands:
        if probe == "cached":                  # never start ffmpeg here: use what a full probe already learned
            try:
                rep = _FF.get((c, os.path.getmtime(c)))
            except OSError:
                rep = None
            if rep is None:
                if first is None:
                    first = (c, {"path": c, "pending": True})
                continue
        else:
            rep = ffmpeg_report(c, run)
        if rep.get("error"):
            continue
        if rep.get("nvenc_h264"):
            return c, rep
        if first is None:
            first = (c, rep)
    return first if first else (cands[0], {"path": cands[0], "error": "no ffmpeg answered"})


def hwaccel_args(rep):
    """Input arguments that decode on the card (frames come back to system memory, so every software filter still works)."""
    if os.environ.get("NM_NO_HWACCEL"):
        return []
    return ["-hwaccel", "cuda"] if (rep or {}).get("cuda_decode") else []


# ───────────────────────────────────────────── VRAM hand-over between Ollama / ComfyUI / audio engines / other programs

def settle_vram(before_mb, wait_s=12.0, step=1.0, snap=None, sleep=time.sleep, min_gain_mb=300):
    """After Ollama models were unloaded / ComfyUI was told to free memory (both answer at once, the memory is returned a moment
    later) wait until nvidia-smi shows it. Returns the MB that were freed (0 when nothing changed within `wait_s`)."""
    snap = snap or snapshot
    if before_mb is None:
        return 0
    waited, best = 0.0, 0
    while waited <= wait_s:
        s = snap()
        used = (s or {}).get("vram_used_mb")
        if used is None:
            return 0
        best = max(best, before_mb - used)
        if best >= min_gain_mb and waited >= 2.0:
            break
        sleep(step)
        waited += step
    return max(0, int(best))


def peers(data_dir):
    """Other programs on this PC that hold VRAM and can be asked to let go: <data>/gpu-peers.json = [{"name", "free": url}]."""
    try:
        with open(os.path.join(data_dir, "gpu-peers.json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        return [r for r in rows if isinstance(r, dict) and r.get("free")]
    except (OSError, ValueError):
        return []


def free_peers(data_dir, post):
    """POST to every peer's `free` URL (InstAI's GPU turn-taker, another ComfyUI ...); returns the names that answered."""
    done = []
    for r in peers(data_dir):
        try:
            post(r["free"])
            done.append(r.get("name") or r["free"])
        except Exception:  # noqa: BLE001 - a peer that is not running holds no VRAM
            pass
    return done


# ───────────────────────────────────────────── Ollama on the GPU

def ollama_env(env=None):
    """Environment for `ollama serve` started by the agent: GPU-friendly defaults; a value the owner already set wins."""
    out = dict(os.environ if env is None else env)
    for k, v in OLLAMA_ENV.items():
        out.setdefault(k, v)
    return out


KV_MB_PER_GB = 14.0       # q8 KV cache: roughly 14 MB per 1k tokens for every GB of weights (qwen3-8b: ~70 MB / 1k at 5 GB)
OS_RESERVE_MB = 1300      # the desktop, the driver and CUDA's own context
CTX_MIN, CTX_MAX, CTX_STEP = 4096, 32768, 1024
CTX_DEFAULT = 16384       # what a normal prompt gets when more would fit: Ollama reserves the whole KV cache at load, so a 32k cache for a
                          # 200-token question only costs load time and VRAM; a longer prompt raises it (up to CTX_MAX)


def num_ctx_for(model_bytes, vram_total_mb, prompt_chars=0, num_predict=1024):
    """A context length for a model of `model_bytes` on a card with `vram_total_mb`: as large as still fits next to the weights
    (never below 4096, never above 32768), raised only as far as the prompt really needs. Returns (num_ctx, fits_gpu)."""
    if not vram_total_mb:
        return CTX_MIN, None
    model_mb = (model_bytes or 0) / 1e6 * 1.06
    room = vram_total_mb - OS_RESERVE_MB - model_mb
    fit_all = CTX_MIN                              # the most context that still fits next to the weights
    if model_mb and room <= 0:
        fit = CTX_MIN                          # the weights alone do not fit: keep the cache small so more layers stay on the card
        fits = False
    else:
        per_1k = max(20.0, (model_mb / 1000.0) * KV_MB_PER_GB) if model_mb else 60.0
        fit = int(room / per_1k * 1024) if model_mb else 8192
        fit = max(CTX_MIN, min(CTX_MAX, fit // CTX_STEP * CTX_STEP))
        fits = True
        fit_all = fit
        fit = min(fit, CTX_DEFAULT)
    need = int(prompt_chars / 2.2 + num_predict + 256)
    ctx = fit
    if need > fit:
        ctx = min(CTX_MAX, ((need + CTX_STEP - 1) // CTX_STEP) * CTX_STEP)
        if fits and ctx > fit_all:
            fits = None                            # the prompt forces more than still fits next to the weights: may spill, the job says so
    return int(ctx), fits


def ps_gpu_share(ps):
    """From Ollama's /api/ps: (percent of the loaded model that sits in VRAM or None, model name)."""
    models = (ps or {}).get("models") or []
    if not models:
        return None, ""
    m = models[0]
    size, vram = m.get("size") or 0, m.get("size_vram") or 0
    if not size:
        return None, m.get("name") or ""
    return round(100.0 * vram / size, 1), m.get("name") or ""


def ollama_device(ps):
    """('cuda'|'mixed'|'cpu', note) from /api/ps: how much of the model sits on the card."""
    pct, name = ps_gpu_share(ps)
    if pct is None:
        return "unknown", "Ollama did not report a loaded model"
    if pct >= 99:
        return "cuda", "%s: 100%% of the model in VRAM" % name
    if pct <= 1:
        return "cpu", "%s: none of the model fits in VRAM (all layers on the CPU)" % name
    return "mixed", "%s: %.0f%% of the model in VRAM, the rest on the CPU (the model is larger than the free VRAM)" % (name, pct)


# ───────────────────────────────────────────── CUDA runtime DLLs of the pip nvidia-* wheels, torch

def nvidia_dll_dirs(site_packages):
    """bin folders of the pip 'nvidia-*' wheels (cublas, cudnn, cuda_runtime ...) inside a site-packages folder."""
    out = []
    base = os.path.join(site_packages or "", "nvidia")
    try:
        for name in sorted(os.listdir(base)):
            for sub in ("bin", "lib"):
                d = os.path.join(base, name, sub)
                if os.path.isdir(d):
                    out.append(d)
    except OSError:
        pass
    return out


def venv_site_packages(venv):
    for rel in (("Lib", "site-packages"),):
        d = os.path.join(venv, *rel)
        if os.path.isdir(d):
            return d
    lib = os.path.join(venv, "lib")
    try:
        for name in os.listdir(lib):
            d = os.path.join(lib, name, "site-packages")
            if os.path.isdir(d):
                return d
    except OSError:
        pass
    return ""


def venv_python(venv):
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        p = os.path.join(venv, *rel)
        if os.path.isfile(p):
            return p
    return ""


def env_with_cuda_dlls(venv, base_env=None):
    """os.environ plus the venv's nvidia DLL folders at the front of PATH (what CTranslate2 / onnxruntime-gpu need on Windows)."""
    env = dict(os.environ if base_env is None else base_env)
    dirs = nvidia_dll_dirs(venv_site_packages(venv))
    if dirs:
        env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    return env


TORCH_PROBE = (
    "import json\n"
    "r={'torch':None,'cuda':False}\n"
    "try:\n"
    " import torch\n"
    " r['torch']=torch.__version__\n"
    " r['cuda']=bool(torch.cuda.is_available())\n"
    " r['cuda_version']=getattr(torch.version,'cuda',None)\n"
    " if r['cuda']:\n"
    "  r['device']=torch.cuda.get_device_name(0)\n"
    "except Exception as e:\n"
    " r['error']=str(e)[:200]\n"
    "print(json.dumps(r))\n"
)


def torch_report(py, run=None, timeout=90):
    """Does the torch of this Python see the GPU? {torch, cuda, cuda_version, device} or {error}."""
    if not py or not os.path.isfile(py):
        return {"error": "python not found"}
    try:
        out = (run or subprocess.run)([py, "-I", "-c", TORCH_PROBE], capture_output=True, text=True, timeout=timeout).stdout
        line = [ln for ln in (out or "").splitlines() if ln.startswith("{")]
        return json.loads(line[-1]) if line else {"error": "no answer"}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"error": str(e)[:200]}


ORT_PROBE = (
    "import json\n"
    "try:\n"
    " import onnxruntime as o\n"
    " print(json.dumps({'ort':o.__version__,'providers':list(o.get_available_providers())}))\n"
    "except Exception as e:\n"
    " print(json.dumps({'error':str(e)[:200]}))\n"
)


def ort_report(py, run=None, timeout=90):
    if not py or not os.path.isfile(py):
        return {"error": "python not found"}
    try:
        out = (run or subprocess.run)([py, "-I", "-c", ORT_PROBE], capture_output=True, text=True, timeout=timeout).stdout
        line = [ln for ln in (out or "").splitlines() if ln.startswith("{")]
        return json.loads(line[-1]) if line else {"error": "no answer"}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"error": str(e)[:200]}


# ───────────────────────────────────────────── one report for the panel / the self-test

def node_gpu_report(data_dir="", run=None, which=None):
    """Everything about the GPU path of this computer in one dict (heartbeat caps["gpu_info"], selftest.gpu)."""
    snap = snapshot(run, which)
    drv = driver_info(run, which)
    rep = {"visible": bool(snap), "driver": drv.get("driver", ""), "name": (snap or {}).get("name") or drv.get("name", ""),
           "vram_total_mb": (snap or {}).get("vram_total_mb"), "vram_used_mb": (snap or {}).get("vram_used_mb"),
           "util": (snap or {}).get("util"), "temp_c": (snap or {}).get("temp_c")}
    try:
        major = int((drv.get("driver") or "0").split(".")[0])
        rep["driver_ok"] = major >= 527
    except ValueError:
        rep["driver_ok"] = None
    ff, ffrep = best_ffmpeg(data_dir, run) if data_dir is not None else (None, {})
    rep["ffmpeg"] = {k: ffrep.get(k) for k in ("path", "version", "nvenc_h264", "nvenc_hevc", "cuda_decode", "error") if k in ffrep}
    return rep
