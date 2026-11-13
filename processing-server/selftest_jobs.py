#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Node-side kinds of the automatic acceptance run (agent 2.11): small real jobs that prove the GPU path of this computer.

  selftest.gpu     nvidia-smi sees the card, driver >= 527, VRAM, torch.cuda in every environment that has torch,
                   onnxruntime GPU provider in the node environment, the ffmpeg that would be used          -> gpu.json
  selftest.ffmpeg  a real NVENC encode (and an NVDEC decode of the result) of a 2 s test pattern, timed        -> nvenc.mp4, ffmpeg.json

The site (apps/compute/selftests) turns the outputs into pass / fail. Everything else the suite checks uses the normal job kinds
(ollama.generate, comfy.graph, photo.matting ...). Python 3.8+ standard library only.
"""
import glob
import json
import os
import subprocess
import sys
import time

import gpu

KINDS = ("selftest.gpu", "selftest.ffmpeg")


def _venv_pythons(data):
    out = []
    for d in sorted(glob.glob(os.path.join(data, "venvs", "*"))):
        py = gpu.venv_python(d)
        if py:
            out.append((os.path.basename(d), py))
    return out


def h_gpu(job, agent):
    t0 = time.time()
    rep = gpu.node_gpu_report(agent.DATA)
    rep["envs"] = {}
    for name, py in _venv_pythons(agent.DATA):
        row = {}
        tr = gpu.torch_report(py)
        if tr.get("torch"):
            row["torch"] = tr
        ort = gpu.ort_report(py)
        if ort.get("ort"):
            row["onnxruntime"] = ort
        if row:
            rep["envs"][name] = row
    own = gpu.torch_report(sys.executable)
    if own.get("torch"):
        rep["envs"]["agent-python"] = {"torch": own}
    rep["agent"] = agent.VERSION
    rep["seconds"] = round(time.time() - t0, 1)
    with open(job.out("gpu.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    device = "cuda" if rep.get("visible") else "cpu"
    return {"primary": "gpu.json", "engine": "selftest", "device": device, "device_note": rep.get("name") or "no NVIDIA GPU"}


def h_ffmpeg(job, agent):
    ff, rep = gpu.best_ffmpeg(agent.DATA)
    if not ff:
        raise agent.JobError("ffmpeg was not found on this node", retryable=False)
    out = job.out("nvenc.mp4")
    codec = "h264_nvenc" if rep.get("nvenc_h264") else "libx264"
    cmd = [ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=2", "-f", "lavfi",
           "-i", "sine=frequency=440:duration=2", "-c:v", codec, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out]
    t0 = time.time()
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=120)
    enc_s = round(time.time() - t0, 2)
    if r.returncode != 0 or not os.path.isfile(out):
        raise agent.JobError("ffmpeg (%s) failed: %s" % (codec, (r.stderr or b"").decode("utf-8", "replace")[-300:]))
    dec = {"ok": None, "seconds": None}
    if "cuda" in (rep.get("hwaccels") or []) and codec == "h264_nvenc":
        t1 = time.time()
        d = subprocess.run([ff, "-v", "error", "-hwaccel", "cuda", "-i", out, "-f", "null", "-"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=120)
        dec = {"ok": d.returncode == 0, "seconds": round(time.time() - t1, 2),
               "error": (d.stderr or b"").decode("utf-8", "replace")[-200:] if d.returncode else ""}
    info = {"ffmpeg": ff, "version": rep.get("version"), "encoder": codec, "nvenc_h264": bool(rep.get("nvenc_h264")),
            "nvenc_hevc": bool(rep.get("nvenc_hevc")), "encode_seconds": enc_s, "size": os.path.getsize(out), "nvdec": dec,
            "hwaccels": rep.get("hwaccels"), "nvenc_error": rep.get("nvenc_error", "")}
    with open(job.out("ffmpeg.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)
    device = "nvenc" if codec == "h264_nvenc" else "cpu"
    note = ("NVENC H.264 encode in %.1f s" % enc_s) if device == "nvenc" else (
        "this ffmpeg has no working NVENC encoder (%s) - libx264 on the CPU was used" % (rep.get("nvenc_error") or "encoder missing"))
    return {"primary": "nvenc.mp4", "engine": "selftest", "device": device, "device_note": note,
            "encoder": "NVENC H.264" if device == "nvenc" else "libx264"}


def install(agent):
    agent.HANDLERS["selftest.gpu"] = lambda job: h_gpu(job, agent)
    agent.HANDLERS["selftest.ffmpeg"] = lambda job: h_ffmpeg(job, agent)
