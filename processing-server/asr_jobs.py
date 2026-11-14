#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asr.transcribe - speech to text with faster-whisper on the GPU (agent 2.11). Python 3.8+ standard library only.

    payload = {"audio": "<input file name>", "language": "fa", "model": "auto", "word_timestamps": true, "vad": true}
    outputs : transcript.json {language, duration, device, text, segments[{start,end,text,avg_logprob,words[]}], words[], ...}

`model`: "auto" (or empty) = the BEST model installed on this node (large-v3-turbo when requirements.d/asr-large.json has put it there, else
small); an explicit name is honoured when installed, otherwise the best installed one answers and `meta.model_note` says so - a 1.6 GB model
that is still downloading never makes a job fail.  The heartbeat advertises `caps.asr_models` (what is installed, best first).

The engine lives in the `asr` environment that bootstrap.py installs (requirements.d/asr-gpu.json); the job runs asr_worker.py there.
The site holds `asr.transcribe` jobs in its queue until this feature is ready (bootstrap blocked_kinds). CUDA first; if the card cannot be
used the worker falls back to the CPU and says why (meta.device = "cpu", meta.device_note) - a visible warning in the panel.
"""
import json
import os
import subprocess
import threading
import time

import gpu

KIND = "asr.transcribe"
#: best first.  large-v3-turbo (requirements.d/asr-large.json) hears Persian far better than small (requirements.d/asr-gpu.json) - the words it
#: returns decide where the automatic edit cuts and what the subtitles say.
MODELS = ("large-v3-turbo", "small")
AUTO_NAMES = ("", "auto", "best")
#: a model.bin smaller than this is a download in progress, not a model
MIN_MODEL_BYTES = {"large-v3-turbo": 1_500_000_000, "small": 400_000_000}
SUPPORT_FILES = ("config.json", "tokenizer.json")


def model_dir(data, name):
    return os.path.join(data, "models", "faster-whisper-%s" % name)


def model_ready(data, name):
    d = model_dir(data, name)
    try:
        if os.path.getsize(os.path.join(d, "model.bin")) < MIN_MODEL_BYTES.get(name, 1):
            return False
    except OSError:
        return False
    return all(os.path.isfile(os.path.join(d, f)) for f in SUPPORT_FILES)


def installed_models(data):
    """The Whisper models that are really on this node, best first (the heartbeat advertises this as caps.asr_models)."""
    return [m for m in MODELS if model_ready(data, m)]


def pick_model(data, wanted):
    """-> (name, note).  `wanted` = payload model.  name is None when nothing is installed."""
    have = installed_models(data)
    asked = str(wanted or "").strip().lower()
    if not have:
        return None, ""
    if asked in AUTO_NAMES:
        return have[0], ""
    if asked in have:
        return asked, ""
    return have[0], "model '%s' is not on this node yet; '%s' answered" % (asked, have[0])


def worker_command(py, audio, mdir, out, language, words, vad, cpu_model_dir=None):
    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [py, os.path.join(here, "asr_worker.py"), "--audio", audio, "--model-dir", mdir, "--out", out,
           "--language", language or "", "--word-timestamps", "1" if words else "0", "--vad", "1" if vad else "0"]
    if cpu_model_dir and cpu_model_dir != mdir:
        cmd += ["--cpu-model-dir", cpu_model_dir]      # the card cannot be used: the small model on the CPU, not the big one (minutes per minute of speech)
    return cmd


def run(job, agent):
    p = job.payload
    asked = str(p.get("model") or "auto").strip().lower()
    if asked not in MODELS and asked not in AUTO_NAMES:
        raise agent.JobError("whisper model '%s' is unknown (known: %s, auto)" % (asked, ", ".join(MODELS)), retryable=False)
    name, model_note = pick_model(agent.DATA, asked)
    aud = p.get("audio") or (p.get("files") or {}).get("audio")
    path = job.input_path(aud) if aud else None
    if not path:
        raise agent.JobError("audio file (audio) is required", retryable=False)
    venv = os.path.join(agent.DATA, "venvs", "asr")
    py = gpu.venv_python(venv)
    if not py or name is None:
        raise agent.JobError("DOWNLOADING: the speech-recognition engine is still being installed on this node (see the install panel) | "
                             "موتورِ تشخیص گفتار هنوز نصب نشده است")
    mdir = model_dir(agent.DATA, name)
    small = model_dir(agent.DATA, "small") if model_ready(agent.DATA, "small") else None
    out = job.out("transcript.json")
    cmd = worker_command(py, path, mdir, out, str(p.get("language") or "fa"), p.get("word_timestamps", True), p.get("vad", True), cpu_model_dir=small)
    env = gpu.env_with_cuda_dlls(venv)
    env.setdefault("PYTHONUTF8", "1")
    job.progress(0.1, "faster-whisper: starting")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                            universal_newlines=True, encoding="utf-8", errors="replace")
    lines = []
    th = threading.Thread(target=lambda: [lines.append(ln.rstrip()) for ln in proc.stdout], daemon=True)
    th.start()
    limit = max(120, int(job.timeout_s or 1800) - 30)
    last_say = 0.0
    while proc.poll() is None:
        time.sleep(1.0)
        if job.cancelled or time.time() - t0 > limit:
            proc.kill()
            if job.cancelled:
                raise agent.Cancelled()
            raise agent.JobError("speech recognition did not finish in %d s" % limit)
        if time.time() - last_say >= 10:
            last_say = time.time()
            job.progress(0.3, "faster-whisper: transcribing ... %ds" % int(time.time() - t0))
    th.join(timeout=5)
    if proc.returncode != 0 or not os.path.isfile(out):
        raise agent.JobError("faster-whisper failed (exit %s): %s" % (proc.returncode, " | ".join(lines[-4:])[:400]))
    with open(out, encoding="utf-8") as fh:
        res = json.load(fh)
    meta = {"primary": "transcript.json", "engine": "faster-whisper", "model": res.get("model"), "language": res.get("language"),
            "audio_seconds": res.get("duration"), "device": res.get("device"), "compute_type": res.get("compute_type"),
            "load_s": res.get("load_seconds"), "asr_seconds": res.get("seconds")}
    meta["model_requested"] = asked
    if model_note:
        meta["model_note"] = model_note
    if res.get("fallback_reason"):
        meta["device_note"] = res["fallback_reason"]
    elif res.get("device") == "cuda":
        meta["device_note"] = "CTranslate2 %s on the GPU" % res.get("compute_type")
    return meta


def install(agent):
    agent.HANDLERS[KIND] = lambda job: run(job, agent)
