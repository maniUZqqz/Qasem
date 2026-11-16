#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch speech-to-text for the pronunciation check. Runs INSIDE the `asr` environment (venvs/asr), started by pron_jobs.py.

    pron_asr_worker.py --dir wavs/ --model-dir DIR --out hyps.json [--cpu-model-dir DIR]

Loads the Whisper model ONCE and transcribes every audio file in --dir (wav / mp3 / ogg / m4a - whatever faster-whisper decodes),
Persian, no timestamps, no prompt (a prompt would bias the recogniser towards the words we want to hear, which is exactly what the
check must not do). CUDA first, the CPU (int8, small model) when the card cannot be used - and the result says which. Licence: MIT.
"""
import argparse
import json
import os
import sys
import time

import asr_worker  # same folder: CUDA DLL paths


def load(model_dir, cpu_model_dir, device="auto"):
    from faster_whisper import WhisperModel
    import ctranslate2

    asr_worker.add_cuda_dlls()
    reason = ""
    if device in ("auto", "cuda") and ctranslate2.get_cuda_device_count() > 0:
        for ctype in ("float16", "int8_float16"):
            try:
                return WhisperModel(model_dir, device="cuda", compute_type=ctype), "cuda", ctype, "", model_dir
            except Exception as e:  # noqa: BLE001
                reason = "CUDA could not be used: %s" % str(e)[:200]
    elif device == "auto":
        reason = "CTranslate2 sees no CUDA device"
    use = cpu_model_dir or model_dir
    return WhisperModel(use, device="cpu", compute_type="int8", cpu_threads=4), "cpu", "int8", reason, use


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--cpu-model-dir", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--language", default="fa")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args(argv)
    t0 = time.time()
    model, device, compute, reason, used = load(args.model_dir, args.cpu_model_dir, args.device)
    load_s = time.time() - t0
    names = sorted(n for n in os.listdir(args.dir) if n.lower().endswith((".wav", ".mp3", ".ogg", ".m4a", ".flac")))
    results = {}
    for i, name in enumerate(names):
        t1 = time.time()
        try:
            segments, info = model.transcribe(os.path.join(args.dir, name), language=args.language or None, beam_size=5,
                                              vad_filter=False, condition_on_previous_text=False, without_timestamps=True)
            text = " ".join(s.text.strip() for s in segments).strip()
            results[name] = {"text": text, "seconds": round(time.time() - t1, 2), "duration": round(info.duration, 2)}
        except Exception as e:  # noqa: BLE001
            results[name] = {"text": "", "error": str(e)[:200]}
        if i % 10 == 0:
            print("ASR %d/%d" % (i + 1, len(names)), flush=True)
    out = {"model": os.path.basename(used.rstrip("/\\")), "device": device, "compute_type": compute, "fallback_reason": reason,
           "load_seconds": round(load_s, 1), "seconds": round(time.time() - t0, 1), "results": results}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("RESULT " + json.dumps({k: out[k] for k in ("device", "compute_type", "model", "seconds")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
