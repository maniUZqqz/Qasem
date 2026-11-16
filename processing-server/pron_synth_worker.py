#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piper speech for the pronunciation check. Runs INSIDE the `pron` environment (venvs/pron), started by pron_jobs.py.

    pron_synth_worker.py --items items.json --voice /path/fa_IR-amir-medium.onnx --out-dir wavs/

items.json = {"items": [{"id": 3, "variant": "before", "text": "..."},        # the voice's own front end (espeak-ng) reads the text
                        {"id": 3, "variant": "after",  "ipa": ["sˈaˈlɑm", ...]}]}   # our phonemes, one string per sentence

In an ``ipa`` string every character is one phoneme symbol (the Piper phoneme map is single code points); a piece written
``{{word}}`` is left to the voice's own front end (the hybrid mode: only the words the lexicon knows are overridden).
One WAV per item is written as ``<id>_<variant>.wav``; ``manifest.json`` lists them. Licence of the engine: MIT (piper-tts).
"""
import argparse
import json
import os
import re
import sys
import time
import wave

NATIVE = re.compile(r"\{\{(.+?)\}\}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--silence", type=float, default=0.25)
    args = ap.parse_args(argv)

    import numpy as np
    from piper import PiperVoice, SynthesisConfig

    t0 = time.time()
    # the check must be repeatable: the same input gives the same audio (Piper's noise is random by default and moved the
    # word error rate of an unchanged sentence by several points between two runs)
    config = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0)
    voice = PiperVoice.load(args.voice)
    rate = voice.config.sample_rate
    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.items, encoding="utf-8") as fh:
        items = json.load(fh).get("items", [])

    def native(word):
        return "".join("".join(s) for s in voice.phonemize(word)).replace(" ", "")

    def audio_for(phonemes):
        ids = voice.phonemes_to_ids(phonemes)
        audio = voice.phoneme_ids_to_audio(ids, config)
        if isinstance(audio, tuple):
            audio = audio[0]
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        return audio / peak if peak > 1e-8 else audio

    manifest = []
    for n, it in enumerate(items):
        name = "%s_%s.wav" % (it["id"], it["variant"])
        t1 = time.time()
        try:
            if it.get("ipa"):
                sentences = [list(NATIVE.sub(lambda m: native(m.group(1)), s)) for s in it["ipa"]]
            else:
                sentences = voice.phonemize(it["text"])
            chunks = []
            for ph in sentences:
                if not ph:
                    continue
                chunks.append(audio_for(ph))
                chunks.append(np.zeros(int(rate * args.silence), dtype=np.float32))
            audio = np.concatenate(chunks) if chunks else np.zeros(int(rate * 0.3), dtype=np.float32)
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            with wave.open(os.path.join(args.out_dir, name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm.tobytes())
            manifest.append({"id": it["id"], "variant": it["variant"], "file": name, "seconds": round(len(pcm) / rate, 2),
                             "took": round(time.time() - t1, 2)})
        except Exception as e:  # noqa: BLE001 - one bad sentence must not lose the others
            manifest.append({"id": it["id"], "variant": it["variant"], "file": "", "error": str(e)[:200]})
        if n % 10 == 0:
            print("SYNTH %d/%d" % (n + 1, len(items)), flush=True)
    with open(os.path.join(args.out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"voice": os.path.basename(args.voice), "sample_rate": rate, "load_s": round(time.time() - t0, 1),
                   "items": manifest}, fh, ensure_ascii=False)
    print("RESULT %d items" % len(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
