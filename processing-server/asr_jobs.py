#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asr.transcribe - speech to text with faster-whisper on the GPU (agent 2.11). Python 3.8+ standard library only.

    payload = {"audio": "<input file name>", "language": "fa", "model": "small", "word_timestamps": true, "vad": true}
    outputs : transcript.json {language, duration, device, text, segments[{start,end,text,avg_logprob,words[]}], words[], ...}

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
MODELS = ("small",)


def model_dir(data, name):
    return os.path.join(data, "models", "faster-whisper-%s" % name)


def worker_command(py, audio, mdir, out, language, words, vad):
    here = os.path.dirname(os.path.abspath(__file__))
    return [py, os.path.join(here, "asr_worker.py"), "--audio", audio, "--model-dir", mdir, "--out", out,
            "--language", language or "", "--word-timestamps", "1" if words else "0", "--vad", "1" if vad else "0"]


def run(job, agent):
    p = job.payload
    name = str(p.get("model") or "small")
    if name not in MODELS:
        raise agent.JobError("whisper model '%s' is not installed on this node (available: %s)" % (name, ", ".join(MODELS)), retryable=False)
    aud = p.get("audio") or (p.get("files") or {}).get("audio")
    path = job.input_path(aud) if aud else None
    if not path:
        raise agent.JobError("audio file (audio) is required", retryable=False)
    venv = os.path.join(agent.DATA, "venvs", "asr")
    py = gpu.venv_python(venv)
    mdir = model_dir(agent.DATA, name)
    if not py or not os.path.isfile(os.path.join(mdir, "model.bin")):
        raise agent.JobError("DOWNLOADING: the speech-recognition engine is still being installed on this node (see the install panel) | "
                             "موتورِ تشخیص گفتار هنوز نصب نشده است")
    out = job.out("transcript.json")
    cmd = worker_command(py, path, mdir, out, str(p.get("language") or "fa"), p.get("word_timestamps", True), p.get("vad", True))
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
    if res.get("fallback_reason"):
        meta["device_note"] = res["fallback_reason"]
    elif res.get("device") == "cuda":
        meta["device_note"] = "CTranslate2 %s on the GPU" % res.get("compute_type")
    return meta


def install(agent):
    agent.HANDLERS[KIND] = lambda job: run(job, agent)
