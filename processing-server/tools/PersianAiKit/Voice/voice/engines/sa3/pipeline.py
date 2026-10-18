# برگرفته از github.com/Stability-AI/stable-audio-3 (optimized/tflite) — MIT، Copyright (c) 2026 Stability AI (LICENSE).
# فقط بخش‌های متن ⇒ صدا: توکن‌ساز، T5Gemma، DiTِ «baked» (بی CFG)، زمان‌بندیِ pingpong و نمونه‌بردار.
from __future__ import annotations

import numpy as np

SAMPLE_RATE = 44100
SAMPLES_PER_LATENT = 4096
COND_TOKENS = 256
COND_DIM = 768


def valid_T_lat(seconds):
    return max(1, int(np.ceil(seconds * SAMPLE_RATE / SAMPLES_PER_LATENT)))


class Tokenizer:
    def __init__(self, model_path):
        import sentencepiece as spm
        self.sp = spm.SentencePieceProcessor()
        self.sp.LoadFromFile(str(model_path))

    def __call__(self, prompt, max_len=COND_TOKENS):
        ids = np.zeros((1, max_len), np.int32)
        mask = np.zeros((1, max_len), np.int32)
        toks = self.sp.Encode(prompt)[:max_len]
        ids[0, :len(toks)] = toks
        mask[0, :len(toks)] = 1
        return ids, mask


def _interp(path, threads):
    from ai_edge_litert import interpreter as tfl
    it = tfl.Interpreter(model_path=str(path), num_threads=threads)
    it.allocate_tensors()
    return it


class T5GemmaTFLite:
    """ids/mask int32 [1,256] ⇒ [1,256,768]."""
    def __init__(self, path, threads=4):
        self.it = _interp(path, threads)
        det = sorted(self.it.get_input_details(), key=lambda d: d["name"])
        self.i_ids, self.i_mask = det[0]["index"], det[1]["index"]
        self.out = self.it.get_output_details()[0]["index"]

    def __call__(self, ids, mask):
        self.it.set_tensor(self.i_ids, ids.astype(np.int32))
        self.it.set_tensor(self.i_mask, mask.astype(np.int32))
        self.it.invoke()
        return self.it.get_tensor(self.out).copy()


class BakedDiT:
    """DiT با شرط‌گذاریِ درونِ گراف (ثانیه‌ها و متن)؛ فقط cfg=1."""
    def __init__(self, path, L, t5_hidden, t5_mask, seconds, threads=4):
        from ai_edge_litert import interpreter as tfl
        self.it = tfl.Interpreter(model_path=str(path), num_threads=threads)
        det = self.it.get_input_details()
        pick = lambda pred: [d for d in det if pred(d)]
        self.i_x = pick(lambda d: len(d["shape"]) == 3 and d["shape"][1] == 256 and d["shape"][2] != COND_DIM)[0]
        self.i_lac = pick(lambda d: len(d["shape"]) == 3 and d["shape"][1] == 257)[0]
        self.i_t5h = pick(lambda d: len(d["shape"]) == 3 and d["shape"][2] == COND_DIM)[0]
        self.i_t5m = pick(lambda d: len(d["shape"]) == 2)[0]
        scalars = sorted(pick(lambda d: len(d["shape"]) == 1), key=lambda d: d["name"])
        self.i_t, self.i_sec = scalars[0], scalars[1]
        self.out = self.it.get_output_details()[0]["index"]
        for d, shape in ((self.i_x, [1, 256, L]), (self.i_lac, [1, 257, L]), (self.i_t5h, [1, COND_TOKENS, COND_DIM]),
                         (self.i_t5m, [1, COND_TOKENS]), (self.i_t, [1]), (self.i_sec, [1])):
            self.it.resize_tensor_input(d["index"], shape, strict=False)
        self.it.allocate_tensors()
        self.t5h = t5_hidden.astype(np.float32)
        self.t5m = t5_mask.astype(np.float32)
        self.it.set_tensor(self.i_sec["index"], np.array([seconds], np.float32))
        self.it.set_tensor(self.i_lac["index"], np.zeros((1, 257, L), np.float32))

    def __call__(self, x, t):
        self.it.set_tensor(self.i_x["index"], x.astype(np.float32))
        self.it.set_tensor(self.i_t["index"], np.array([t], np.float32))
        self.it.set_tensor(self.i_t5h["index"], self.t5h)
        self.it.set_tensor(self.i_t5m["index"], self.t5m)
        self.it.invoke()
        return self.it.get_tensor(self.out).copy()


def _logsnr_shift(t, anchor=-6.2, end=2.0):
    t = t.astype(np.float32)
    out = 1.0 / (1.0 + np.exp(end - t * (end - anchor)))
    out = np.where(t <= 0, 0.0, out)
    out = np.where(t >= 1, 1.0, out)
    return out.astype(np.float32)


def pingpong_schedule(steps, sigma_max=1.0):
    t = _logsnr_shift(np.linspace(1.0, 0.0, steps + 1).astype(np.float32)) * np.float32(sigma_max)
    t[0] = np.float32(sigma_max)
    return t


def make_noise(T_lat, steps, seed):
    rng = np.random.default_rng(seed)
    x0 = rng.standard_normal((1, 256, T_lat)).astype(np.float32)
    return x0, [rng.standard_normal((1, 256, T_lat)).astype(np.float32) for _ in range(steps)]


def sample(dit, x0, step_noise, sigmas):
    """rectified-flow pingpong."""
    steps = len(sigmas) - 1
    x = x0.copy()
    for i in range(steps):
        tc, tn = float(sigmas[i]), float(sigmas[i + 1])
        denoised = x - tc * dit(x, tc)
        x = (1 - tn) * denoised + tn * step_noise[i] if i < steps - 1 and tn > 0 else denoised
    return x
