#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pronunciation check on the GPU node (agent 2.27). Python 3.8+ standard library only.

Two job kinds - together they are the «speak it, listen to it, compare» round trip that measures whether the Persian
pronunciation layer (the site's services/audio/fa_pron) really made a voice clearer:

voice.pron_eval   speak the sentences (twice each: the plain text, and what the layer produced) and listen to them
    payload = {"engine": "piper" | "moss", "voice": "fa_IR-amir-medium" | "<moss preset>", "language": "fa",
               "items": [{"id": 3, "variant": "before", "text": "..."},
                         {"id": 3, "variant": "after",  "ipa": ["sˈlɑm", ...]}   # piper: phonemes   |  "text": respelled text (moss)
                        ...]}
    output  : result.json = {engine, voice, asr: {model, device, compute_type, note}, synth: {...}, items: [{id, variant, hyp, audio_s}]}
              The site computes the word error rate (it holds the reference text and the normaliser); the node only hears.

voice.pron_asr    listen only: inputs are audio files (the site made them with a cloud engine), payload.files = [{"id", "variant", "name"}]
    output  : result.json with the same shape.

Piper runs in its own environment `pron` (piper-tts, MIT, with the voice files from requirements.d/pron.json); Whisper in the `asr`
environment of requirements.d/asr-gpu.json (CUDA first, CPU with a clear note). MOSS goes through the node's own audio service
(the same call a narration makes). Both installs are automatic and idempotent (bootstrap.py); until they are ready the site holds
these jobs in its queue (requirements.d/pron.json `kinds`). Nothing here changes or replaces a voice model.
"""
import json
import os
import shutil
import subprocess
import threading
import time

import gpu

KIND_EVAL = "voice.pron_eval"
KIND_ASR = "voice.pron_asr"
VOICES = ("fa_IR-amir-medium", "fa_IR-gyro-medium")
MAX_ITEMS = 160
HERE = os.path.dirname(os.path.abspath(__file__))


def _venv(agent, name):
    return os.path.join(agent.DATA, "venvs", name)


def _stream(cmd, env, job, agent, label, limit_s, frac_from, frac_to):
    """Run a worker, relay its progress lines, stop it on cancel / timeout. Returns (exit code, last lines)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, cwd=HERE,
                            universal_newlines=True, encoding="utf-8", errors="replace")
    lines = []

    def pump():
        for ln in proc.stdout:
            lines.append(ln.rstrip())

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    t0 = time.time()
    last = 0.0
    while proc.poll() is None:
        time.sleep(1.0)
        if job.cancelled or time.time() - t0 > limit_s:
            proc.kill()
            if job.cancelled:
                raise agent.Cancelled()
            raise agent.JobError("%s did not finish in %d s" % (label, limit_s))
        if time.time() - last >= 10:
            last = time.time()
            tail = next((x for x in reversed(lines) if x.startswith(("SYNTH", "ASR"))), "")
            frac = frac_from + (frac_to - frac_from) * min(0.95, (time.time() - t0) / max(60.0, limit_s / 4.0))
            job.progress(frac, "%s %s" % (label, tail))
    th.join(timeout=5)
    return proc.returncode, lines[-6:]


def piper_voice_path(agent, voice):
    voice = voice if voice in VOICES else VOICES[0]
    return os.path.join(agent.DATA, "models", "piper", voice + ".onnx")


def _synth_piper(job, agent, p, items, wavs):
    py = gpu.venv_python(_venv(agent, "pron"))
    voice = piper_voice_path(agent, str(p.get("voice") or ""))
    if not py or not os.path.isfile(voice) or not os.path.isfile(voice + ".json"):
        raise agent.JobError("DOWNLOADING: the Persian pronunciation check (Piper voice + engine) is still being installed on this node "
                             "(see the install panel) | بررسیِ تلفظ هنوز نصب نشده است")
    src = job.out("items.json")
    with open(src, "w", encoding="utf-8") as fh:
        json.dump({"items": items}, fh, ensure_ascii=False)
    cmd = [py, os.path.join(HERE, "pron_synth_worker.py"), "--items", src, "--voice", voice, "--out-dir", wavs]
    env = gpu.env_with_cuda_dlls(_venv(agent, "pron"))
    env.setdefault("PYTHONUTF8", "1")
    code, tail = _stream(cmd, env, job, agent, "Piper", max(300, int(job.timeout_s or 1800) // 2), 0.05, 0.4)
    os.remove(src)
    if code != 0 or not os.path.isfile(os.path.join(wavs, "manifest.json")):
        raise agent.JobError("Piper failed (exit %s): %s" % (code, " | ".join(tail)[:400]))
    with open(os.path.join(wavs, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _synth_moss(job, agent, p, items, wavs):
    """The node's own MOSS-TTS service, the very call a narration makes (one text per item)."""
    ref = agent.moss_reference(job, p)
    url = agent.audio_ready("moss", job)
    done = []
    for n, it in enumerate(items):
        name = "%s_%s.wav" % (it["id"], it["variant"])
        t1 = time.time()
        try:
            agent.audio_run("moss", url, {"text": str(it.get("text") or ""), "reference": ref, "out": os.path.join(wavs, name),
                                          "seed": 7, "temperature": float(p.get("temperature", 0.8))},
                            timeout=max(600, int(job.timeout_s or 600)))
            done.append({"id": it["id"], "variant": it["variant"], "file": name, "took": round(time.time() - t1, 2)})
        except agent.Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - one failed sentence is counted, not fatal
            done.append({"id": it["id"], "variant": it["variant"], "file": "", "error": str(e)[:200]})
        job.progress(0.05 + 0.35 * (n + 1) / max(1, len(items)), "MOSS-TTS %d/%d" % (n + 1, len(items)))
    return {"voice": str(p.get("voice") or "moss"), "items": done}


def _listen(job, agent, wavs, out_json):
    import asr_jobs

    name, note = asr_jobs.pick_model(agent.DATA, "auto")
    py = gpu.venv_python(_venv(agent, "asr"))
    if not py or name is None:
        raise agent.JobError("DOWNLOADING: the speech-recognition engine is still being installed on this node (see the install panel) | "
                             "موتورِ تشخیص گفتار هنوز نصب نشده است")
    small = asr_jobs.model_dir(agent.DATA, "small") if asr_jobs.model_ready(agent.DATA, "small") else None
    cmd = [py, os.path.join(HERE, "pron_asr_worker.py"), "--dir", wavs, "--model-dir", asr_jobs.model_dir(agent.DATA, name),
           "--out", out_json]
    if small:
        cmd += ["--cpu-model-dir", small]
    env = gpu.env_with_cuda_dlls(_venv(agent, "asr"))
    env.setdefault("PYTHONUTF8", "1")
    code, tail = _stream(cmd, env, job, agent, "faster-whisper", max(300, int(job.timeout_s or 1800) // 2), 0.45, 0.95)
    if code != 0 or not os.path.isfile(out_json):
        raise agent.JobError("faster-whisper failed (exit %s): %s" % (code, " | ".join(tail)[:400]))
    with open(out_json, encoding="utf-8") as fh:
        res = json.load(fh)
    res["note"] = note
    return res


def _finish(job, agent, engine, voice, synth, asr, order):
    """result.json: for every (id, variant) what was heard. ``order`` = [(id, variant, file)]."""
    heard = asr.get("results", {})
    by_name = {s.get("file"): s for s in (synth or {}).get("items", []) if s.get("file")}
    rows = []
    for (iid, variant, fname) in order:
        row = heard.get(fname) or {}
        rows.append({"id": iid, "variant": variant, "hyp": row.get("text", ""), "error": row.get("error") or "",
                     "audio_s": row.get("duration"), "synth_s": (by_name.get(fname) or {}).get("took")})
    out = {"engine": engine, "voice": voice, "asr": {"model": asr.get("model"), "device": asr.get("device"),
                                                    "compute_type": asr.get("compute_type"), "note": asr.get("fallback_reason") or asr.get("note") or ""},
           "synth": {k: v for k, v in (synth or {}).items() if k != "items"}, "items": rows}
    with open(job.out("result.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return {"primary": "result.json", "engine": "pron:%s" % engine, "device": asr.get("device"), "model": asr.get("model"),
            "compute_type": asr.get("compute_type"), "items": len(rows), "asr_seconds": asr.get("seconds")}


def run_eval(job, agent):
    p = job.payload
    engine = str(p.get("engine") or "piper").lower()
    items = [it for it in (p.get("items") or []) if isinstance(it, dict) and it.get("variant") in ("before", "after")]
    if not items or len(items) > MAX_ITEMS:
        raise agent.JobError("1..%d items are required" % MAX_ITEMS, retryable=False)
    if engine not in ("piper", "moss"):
        raise agent.JobError("engine must be piper or moss", retryable=False)
    wavs = os.path.join(job.dir, "wavs")
    shutil.rmtree(wavs, ignore_errors=True)
    os.makedirs(wavs, exist_ok=True)
    job.progress(0.03, "pronunciation check: %s, %d sentences" % (engine, len(items)))
    synth = (_synth_piper if engine == "piper" else _synth_moss)(job, agent, p, items, wavs)
    order = [(i["id"], i["variant"], i.get("file") or "") for i in synth.get("items", [])]
    res = _listen(job, agent, wavs, os.path.join(job.dir, "hyps.json"))
    shutil.rmtree(wavs, ignore_errors=True)
    return _finish(job, agent, engine, str(p.get("voice") or synth.get("voice") or ""), synth, res, order)


def run_asr(job, agent):
    """Listen to audio files the site made (Edge, ...)."""
    p = job.payload
    files = [f for f in (p.get("files") or []) if isinstance(f, dict) and f.get("name")]
    if not files or len(files) > MAX_ITEMS:
        raise agent.JobError("1..%d files are required" % MAX_ITEMS, retryable=False)
    wavs = os.path.join(job.dir, "wavs")
    shutil.rmtree(wavs, ignore_errors=True)
    os.makedirs(wavs, exist_ok=True)
    order = []
    for f in files:
        src = job.input_path(f["name"])
        if not src:
            raise agent.JobError("input file %s is not in the job package" % f["name"], retryable=False)
        ext = os.path.splitext(f["name"])[1] or ".mp3"
        dst = "%s_%s%s" % (f.get("id"), f.get("variant") or "x", ext)
        shutil.copyfile(src, os.path.join(wavs, dst))
        order.append((f.get("id"), f.get("variant") or "x", dst))
    job.progress(0.1, "pronunciation check: listening to %d files" % len(order))
    res = _listen(job, agent, wavs, os.path.join(job.dir, "hyps.json"))
    shutil.rmtree(wavs, ignore_errors=True)
    synth = {"voice": str(p.get("voice") or ""), "items": []}
    return _finish(job, agent, str(p.get("engine") or "edge"), str(p.get("voice") or ""), synth, res, order)


def install(agent):
    """agent.py calls this once at start (one guarded line). A broken module never stops the agent."""
    agent.HANDLERS[KIND_EVAL] = lambda job: run_eval(job, agent)
    agent.HANDLERS[KIND_ASR] = lambda job: run_asr(job, agent)
