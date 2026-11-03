"""Multicam: line several recordings of the same event up by their sound. §23.4

Cameras never start together. Each recording's audio is compared with the first one's: a coarse pass on the loudness
envelope (200 Hz, any distance from the microphone looks alike there) finds the rough delay, a fine pass on the 8 kHz
waveform inside ±60 ms pins it to about a millisecond. The result per recording is its **offset** in seconds — put the
clip on the timeline at `at = offset - min(offsets)` and the same hand-clap lines up everywhere — and a confidence
(how much taller the winning correlation peak is than the rest). A low confidence means «no common sound found»: the
panel says so rather than silently lining up noise.
"""
from __future__ import annotations

import numpy as np

from . import media_cache
from .errors import TimelineError

SR = 8000
ENV_HOP = 40                 # 8000 / 40 = 200 envelope samples per second
MAX_SECONDS = 300.0
MIN_CONFIDENCE = 0.3


def _audio(path, max_seconds: float) -> np.ndarray:
    chunks = []
    for chunk in media_cache._pcm(path, SR, max_seconds=max_seconds):
        chunks.append(chunk.astype(np.float32) / 32768.0)
    if not chunks:
        raise TimelineError("این فایل صدا ندارد؛ هم‌زمان‌سازی با صدا ممکن نیست.")
    return np.concatenate(chunks)


def _envelope(x: np.ndarray) -> np.ndarray:
    n = (len(x) // ENV_HOP) * ENV_HOP
    env = np.abs(x[:n]).reshape(-1, ENV_HOP).mean(axis=1)
    # remove the slow level changes: what the cameras share is the *events*, not the room's hum
    k = 40
    kernel = np.ones(k, dtype=np.float32) / k
    env = np.maximum(0.0, env - np.convolve(env, kernel, mode="same"))
    return (env - env.mean()) / (env.std() + 1e-9)


def _xcorr(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """c[k] = Σ a[n + k] · b[n] for k = -(len(b)-1) … len(a)-1, via FFT. Index of lag k is k + len(b) - 1."""
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    fa, fb = np.fft.rfft(a, size), np.fft.rfft(b, size)
    c = np.fft.irfft(fa * np.conj(fb), size)
    return np.concatenate([c[size - (len(b) - 1):], c[:len(a)]])


def _confidence(c: np.ndarray, peak_idx: int) -> float:
    lo, hi = max(0, peak_idx - 40), min(len(c), peak_idx + 40)
    rest = np.concatenate([c[:lo], c[hi:]]) if hi - lo < len(c) else c
    spread = float(np.std(rest)) + 1e-9
    z = (float(c[peak_idx]) - float(np.mean(rest))) / spread
    # measured: a real match stands ~40σ above the rest of the correlation, unrelated sound ~6σ (the best of thousands of lags)
    return float(max(0.0, min(1.0, z / 40.0)))


def offset_between(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Seconds by which `b` starts AFTER `a` (b(t) ≈ a(t + offset)), and a 0–1 confidence."""
    ea, eb = _envelope(a), _envelope(b)
    if len(ea) < 50 or len(eb) < 50:
        raise TimelineError("صدا برای هم‌زمان‌سازی خیلی کوتاه است.")
    c = _xcorr(ea, eb)
    i = int(np.argmax(c))
    coarse = (i - (len(eb) - 1)) / (SR / ENV_HOP)
    conf = _confidence(c, i)
    # fine pass: raw waveform (high-passed by differencing) near the coarse lag
    lag0 = int(round(coarse * SR))
    win = int(min(len(a), len(b), 20 * SR))
    b0 = max(0, -lag0)
    a0 = max(0, lag0)
    seg = min(win, len(a) - a0, len(b) - b0)
    if seg > SR:
        pad = int(0.06 * SR)
        aa = np.diff(a[max(0, a0 - pad): a0 + seg + pad])
        bb = np.diff(b[b0: b0 + seg])
        fine = _xcorr(aa, bb)
        j = int(np.argmax(fine))
        shift = (j - (len(bb) - 1)) - (a0 - max(0, a0 - pad))
        if abs(shift) <= pad + 2:
            return round((lag0 + shift) / SR, 4), conf
    return round(coarse, 4), conf


def sync(paths: list, *, max_seconds: float = MAX_SECONDS, progress=None) -> list[dict]:
    """Offsets of every recording relative to the first: [{"offset": s, "confidence": 0..1, "ok": bool}], first = 0."""
    if len(paths) < 2:
        raise TimelineError("برای هم‌زمان‌سازی دست‌کم دو فایل لازم است.")
    base = _audio(paths[0], max_seconds)
    out = [{"offset": 0.0, "confidence": 1.0, "ok": True}]
    for i, p in enumerate(paths[1:], 1):
        sig = _audio(p, max_seconds)
        off, conf = offset_between(base, sig)
        out.append({"offset": off, "confidence": round(conf, 3), "ok": conf >= MIN_CONFIDENCE})
        if progress:
            progress(i / (len(paths) - 1))
    return out
