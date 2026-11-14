#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Speech to text with faster-whisper on the GPU. Runs INSIDE the `asr` environment (venvs/asr), started by asr_jobs.py.

    asr_worker.py --check                         exit 0 when CTranslate2 sees a CUDA device (prints what it found)
    asr_worker.py --audio in.wav --model-dir DIR --out result.json [--language fa] [--word-timestamps 1] [--device auto]

CUDA 12 runtime DLLs (cuBLAS, cuDNN 9) come from the pip wheels nvidia-cublas-cu12 / nvidia-cudnn-cu12; their folders are put on
the DLL search path BEFORE ctranslate2 is imported. If CUDA cannot be used the model is loaded on the CPU (int8) and the result
says so (`device: "cpu"`, `fallback_reason`) - the node shows that as a visible warning. License of the engine: MIT.
"""
import argparse
import json
import os
import sys
import time


def add_cuda_dlls():
    """Put <site-packages>/nvidia/*/bin on the DLL search path (Windows) and on PATH."""
    added = []
    for base in sys.path:
        root = os.path.join(base, "nvidia")
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            for sub in ("bin", "lib"):
                d = os.path.join(root, name, sub)
                if os.path.isdir(d):
                    added.append(d)
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(d)
                        except OSError:
                            pass
    if added:
        os.environ["PATH"] = os.pathsep.join(added + [os.environ.get("PATH", "")])
    return added


def check():
    add_cuda_dlls()
    try:
        import ctranslate2
    except Exception as e:  # noqa: BLE001
        print("ctranslate2 does not import: %s" % e)
        return 2
    n = ctranslate2.get_cuda_device_count()
    print("ctranslate2 %s: %d CUDA device(s); compute types: %s" % (
        ctranslate2.__version__, n, ", ".join(sorted(ctranslate2.get_supported_compute_types("cuda"))) if n else "-"))
    return 0 if n else 3


def transcribe(args):
    add_cuda_dlls()
    from faster_whisper import WhisperModel
    import ctranslate2
    t0 = time.time()
    want_cuda = args.device in ("auto", "cuda") and ctranslate2.get_cuda_device_count() > 0
    device, compute, reason = "cpu", "int8", ""
    model = None
    model_dir = args.model_dir
    if want_cuda:
        # float16 first; when the card is shared with Ollama (a big model resident in VRAM) the same weights in int8_float16 need about half the memory
        for ctype in ("float16", "int8_float16"):
            try:
                model = WhisperModel(model_dir, device="cuda", compute_type=ctype)
                device, compute = "cuda", ctype
                reason = "" if ctype == "float16" else "float16 did not fit in the free VRAM; %s on the card" % ctype
                break
            except Exception as e:  # noqa: BLE001 - missing cuBLAS/cuDNN DLLs, out of memory ...
                reason = "CUDA could not be used: %s" % str(e)[:200]
    elif args.device == "auto":
        reason = "CTranslate2 sees no CUDA device"
    if model is None:
        if getattr(args, "cpu_model_dir", None):
            model_dir = args.cpu_model_dir          # the big model on a CPU takes minutes per minute of speech: the small one answers
            reason = (reason + "; " if reason else "") + "the small model ran on the CPU"
        model = WhisperModel(model_dir, device="cpu", compute_type="int8", cpu_threads=4)
    load_s = time.time() - t0
    t1 = time.time()
    segments, info = model.transcribe(args.audio, language=args.language or None, word_timestamps=bool(int(args.word_timestamps)),
                                      vad_filter=bool(int(args.vad)), beam_size=5, condition_on_previous_text=False)
    segs, words = [], []
    for s in segments:
        row = {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(), "avg_logprob": round(s.avg_logprob, 3)}
        if s.words:
            row["words"] = [{"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3), "probability": round(w.probability, 3)}
                            for w in s.words]
            words.extend(row["words"])
        segs.append(row)
    out = {"language": info.language, "language_probability": round(info.language_probability, 3), "duration": round(info.duration, 2),
           "device": device, "compute_type": compute, "fallback_reason": reason, "load_seconds": round(load_s, 1),
           "seconds": round(time.time() - t1, 1), "text": " ".join(s["text"] for s in segs), "segments": segs, "words": words,
           "model": os.path.basename(model_dir.rstrip("/\\")), "engine": "faster-whisper"}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("RESULT " + json.dumps({k: out[k] for k in ("device", "compute_type", "duration", "seconds", "load_seconds")}))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--audio")
    ap.add_argument("--model-dir")
    ap.add_argument("--cpu-model-dir", default=None, help="a smaller model for the CPU path (used only when the card cannot be used)")
    ap.add_argument("--out")
    ap.add_argument("--language", default="fa")
    ap.add_argument("--word-timestamps", default="1")
    ap.add_argument("--vad", default="1")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args(argv)
    if args.check:
        return check()
    if not (args.audio and args.model_dir and args.out):
        ap.error("--audio, --model-dir and --out are required")
    return transcribe(args)


if __name__ == "__main__":
    sys.exit(main())
