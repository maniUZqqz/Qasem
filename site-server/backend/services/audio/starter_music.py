"""The shop's first background music, made by the site itself - so «موسیقیِ زمینه» works on the very first automatic edit, node on or off.

Why this exists (1405/08/23): the owner's shop had no music in its library at all, so `pick_music` ended every automatic edit with «موسیقیِ هم‌خوان …
پیدا نشد؛ از «ساخت موسیقی» یکی بساز» and the video was built without music, although he had asked for «a nice background music» and that
everything works by itself.  `services.audio.library` deliberately ships NO third-party tracks (an imperfect licence becomes a copyright strike on
the customer's account), and the music engine (ACE-Step) lives on the processing node, which may be off.  So:

* **Starter tracks** - six short instrumental beds (calm / warm / happy / energetic / inspiring / dramatic) COMPOSED AND SYNTHESISED HERE, from
  nothing but chord progressions and a few additive instruments (numpy; no sample, no loop pack, no model, no download).  The notes, the
  arrangement and the sound are ours, so there is no third-party licence to carry: they are stored with `license="CC0 - ساخته‌شدهٔ سامانه"` and are
  free for any commercial use.  They are made once (a minute of music takes a few seconds of CPU), cached under the audio library folder and copied
  into a shop's library the first time the shop needs music - they are ordinary library rows, so the shop can listen, rename, delete or replace them.
* **The node's better music** - when a processing node with ACE-Step is registered, the same moment queues a few real generated tracks
  (`studio.create_music`, durable: they wait while the node is off and are made by themselves when it comes on, then join the library and are
  ranked with the starters by `music_match`).  Best effort, once per shop per two weeks, never a failure.

Nothing here runs unless a video edit asks for music AND the shop's library has none (`ensure_for_store`).
"""
from __future__ import annotations

import fcntl
import logging
import math
import os
import shutil
import subprocess
import tempfile
import uuid
import wave
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SR = 32000
STARTER_VERSION = 1
STARTER_ENGINE = "starter"
STARTER_LICENSE = "CC0 - ساخته‌شدهٔ خودِ سامانه (بدون حق‌امتیاز)"
UPGRADE_EVERY_DAYS = 14

# ------------------------------------------------------------------ the six tracks
# chords are MIDI note lists (root first); `prog` = one chord per bar, repeated; `bars` = length of the track in bars.
_MAJ7 = (0, 4, 7, 11)
_MIN7 = (0, 3, 7, 10)
_DOM7 = (0, 4, 7, 10)
_MAJ = (0, 4, 7)
_MIN = (0, 3, 7)


def _chord(root: int, shape: tuple[int, ...]) -> list[int]:
    return [root + s for s in shape]


TRACKS: list[dict] = [
    {"key": "calm", "mood": "calm", "title": "آرامش — پیانوی ملایم و پدِ آرام", "style": "calm piano ambient soft", "bpm": 72, "bars": 28, "swing": 0.0,
     "text": "موسیقیِ آرام و ملایم با پیانو و پدِ نرم، مناسبِ زیرِ صدای گوینده (calm soft piano ambient)",
     "prog": [_chord(57, _MIN7), _chord(53, _MAJ7), _chord(60, _MAJ7), _chord(55, _DOM7)],
     "layers": {"pad": 0.55, "pluck": 0.5, "bass": 0.4, "kick": 0.0, "hat": 0.0, "clap": 0.0}, "pluck_style": "piano", "arp": "slow", "reverb": 0.34, "seed": 11},
    {"key": "warm", "mood": "warm", "title": "گرم و صمیمی — کافه و جازِ ملایم", "style": "warm cozy cafe jazz gentle", "bpm": 92, "bars": 24, "swing": 0.16,
     "text": "موسیقیِ گرم و صمیمی با حالِ کافه و جازِ ملایم (warm cozy cafe jazz gentle)",
     "prog": [_chord(62, _MAJ7), _chord(59, _MIN7), _chord(55, _MAJ7), _chord(57, _DOM7)],
     "layers": {"pad": 0.35, "pluck": 0.55, "bass": 0.5, "kick": 0.2, "hat": 0.22, "clap": 0.0}, "pluck_style": "ep", "arp": "comp", "reverb": 0.26, "seed": 23},
    {"key": "happy", "mood": "happy", "title": "شاد و پرانرژی — پاپِ سبک و بامزه", "style": "happy upbeat pop bright", "bpm": 112, "bars": 28, "swing": 0.0,
     "text": "موسیقیِ شاد و پرانرژی؛ پاپِ سبک با ضربِ ملایم (happy upbeat pop bright)",
     "prog": [_chord(55, _MAJ), _chord(62, _MAJ), _chord(64, _MIN), _chord(60, _MAJ)],
     "layers": {"pad": 0.3, "pluck": 0.6, "bass": 0.5, "kick": 0.55, "hat": 0.32, "clap": 0.4}, "pluck_style": "marimba", "arp": "eighths", "reverb": 0.2, "seed": 37},
    {"key": "energetic", "mood": "energetic", "title": "پرانرژی و تند — ضربِ الکترونیک برای فروش", "style": "energetic electro dance beat fast", "bpm": 126, "bars": 32, "swing": 0.0,
     "text": "موسیقیِ پرانرژی و تند با ضربِ الکترونیک، برای ریلزِ فروش و ورزش (energetic electro dance beat)",
     "prog": [_chord(57, _MIN), _chord(53, _MAJ), _chord(60, _MAJ), _chord(55, _MAJ)],
     "layers": {"pad": 0.4, "pluck": 0.5, "bass": 0.7, "kick": 0.8, "hat": 0.4, "clap": 0.5}, "pluck_style": "synth", "arp": "sixteenths", "reverb": 0.16, "seed": 41},
    {"key": "inspiring", "mood": "inspiring", "title": "الهام‌بخش — انگیزه و پیشرفت", "style": "inspiring motivational uplifting corporate", "bpm": 100, "bars": 28, "swing": 0.0,
     "text": "موسیقیِ الهام‌بخش و انگیزشی با پدِ پرشکوه و ضربِ ملایم (inspiring motivational uplifting)",
     "prog": [_chord(62, _MAJ), _chord(57, _MAJ), _chord(59, _MIN), _chord(55, _MAJ)],
     "layers": {"pad": 0.55, "pluck": 0.45, "bass": 0.5, "kick": 0.4, "hat": 0.2, "clap": 0.28}, "pluck_style": "bell", "arp": "eighths", "reverb": 0.3, "seed": 53},
    {"key": "dramatic", "mood": "dramatic", "title": "سینمایی و دراماتیک — حال‌وهوای فیلم", "style": "cinematic dramatic trailer dark", "bpm": 80, "bars": 24, "swing": 0.0,
     "text": "موسیقیِ سینمایی و دراماتیک با پدِ عمیق و ضربه‌های آرام (cinematic dramatic trailer dark)",
     "prog": [_chord(50, _MIN), _chord(46, _MAJ7), _chord(53, _MAJ), _chord(48, _MAJ)],
     "layers": {"pad": 0.7, "pluck": 0.3, "bass": 0.55, "kick": 0.5, "hat": 0.0, "clap": 0.0}, "pluck_style": "piano", "arp": "slow", "reverb": 0.42, "seed": 67},
]


def spec_by_key(key: str) -> dict | None:
    return next((t for t in TRACKS if t["key"] == key), None)


# ------------------------------------------------------------------ synthesis

def _hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def _env(n: int, attack: float, release: float, sr: int = SR) -> np.ndarray:
    a = max(1, int(attack * sr))
    r = max(1, int(release * sr))
    e = np.ones(n, dtype=np.float32)
    a = min(a, n)
    e[:a] = np.linspace(0.0, 1.0, a, dtype=np.float32) ** 1.5
    r = min(r, n)
    e[n - r:] *= np.linspace(1.0, 0.0, r, dtype=np.float32) ** 1.5
    return e


class _Buf:
    """A stereo buffer notes are added into (so no note allocates more than its own length)."""

    def __init__(self, seconds: float):
        self.n = int(seconds * SR)
        self.data = np.zeros((self.n, 2), dtype=np.float32)

    def add(self, start: float, sig_l: np.ndarray, sig_r: np.ndarray | None = None, gain: float = 1.0) -> None:
        i = int(start * SR)
        if i >= self.n or i < 0:
            return
        sig_r = sig_l if sig_r is None else sig_r
        m = min(len(sig_l), self.n - i)
        self.data[i:i + m, 0] += sig_l[:m] * gain
        self.data[i:i + m, 1] += sig_r[:m] * gain


def _tone(freq: float, dur: float, harmonics: list[tuple[int, float, float]], *, detune_cents: float = 0.0, phase: float = 0.0) -> np.ndarray:
    """Additive tone: (harmonic number, amplitude, decay per second) per partial; decay 0 = sustained."""
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    f = freq * 2.0 ** (detune_cents / 1200.0)
    out = np.zeros(n, dtype=np.float32)
    for h, amp, decay in harmonics:
        if f * h > SR * 0.45:
            continue
        env = np.exp(-decay * t) if decay else 1.0
        out += (amp * env * np.sin(2 * np.pi * f * h * t + phase * h)).astype(np.float32)
    return out


_PAD_H = [(1, 1.0, 0), (2, 0.5, 0), (3, 0.33, 0), (4, 0.2, 0), (5, 0.12, 0), (6, 0.08, 0)]
_PAD_SOFT = [(1, 1.0, 0), (2, 0.35, 0), (3, 0.12, 0), (4, 0.05, 0)]
_PLUCKS = {
    # (harmonic, amplitude, decay/s): a struck string / bell / marimba / electric piano / synth pluck
    "piano": [(1, 1.0, 1.6), (2, 0.55, 2.4), (3, 0.28, 3.2), (4, 0.15, 4.4), (5, 0.08, 5.5), (6, 0.04, 6.5)],
    "ep": [(1, 1.0, 1.8), (2, 0.25, 3.0), (3, 0.12, 2.4), (4, 0.18, 6.0), (6, 0.06, 7.0)],
    "marimba": [(1, 1.0, 5.5), (4, 0.5, 11.0), (10, 0.12, 18.0)],
    "bell": [(1, 1.0, 1.4), (2.76, 0.4, 2.2), (5.4, 0.25, 3.4), (8.9, 0.1, 5.0)],
    "synth": [(1, 1.0, 3.5), (2, 0.5, 4.0), (3, 0.33, 4.5), (4, 0.25, 5.0), (5, 0.2, 5.5), (6, 0.15, 6.0), (7, 0.1, 6.5)],
}


_MEMO: dict = {}


def _memo(key, make):
    """Every distinct chord / note is synthesised once per track (the progression repeats every four bars): a 28-bar track costs a few seconds."""
    hit = _MEMO.get(key)
    if hit is None:
        hit = _MEMO[key] = make()
    return hit


def _pad_voice(buf: _Buf, start: float, dur: float, notes: list[int], amp: float, soft: bool = False) -> None:
    def make():
        n = int(dur * SR)
        env = _env(n, min(1.6, dur * 0.4), min(2.0, dur * 0.5))
        harm = _PAD_SOFT if soft else _PAD_H[:4]
        left = np.zeros(n, dtype=np.float32)
        right = np.zeros(n, dtype=np.float32)
        for k, note in enumerate(notes):
            f = _hz(note)
            for det, pan in ((-7.0, 0.65), (7.0, 0.35)):
                tone = _tone(f, dur, harm, detune_cents=det, phase=0.7 * k + det) * (1.0 / (len(notes) * 2.0))
                left += tone * (1.0 - pan) * 1.6
                right += tone * pan * 1.6
        return left * env, right * env

    left, right = _memo(("pad", tuple(notes), round(dur, 3), soft), make)
    buf.add(start, left, right, amp)


def _pluck(buf: _Buf, start: float, dur: float, note: float, amp: float, style: str, pan: float = 0.5) -> None:
    def make():
        tone = _tone(_hz(note), dur, _PLUCKS[style])
        return tone * _env(len(tone), 0.004, min(0.12, dur * 0.4))

    tone = _memo(("pluck", int(note), round(dur, 3), style), make)
    buf.add(start, tone * (1.0 - pan) * 1.4, tone * pan * 1.4, amp)


def _bass(buf: _Buf, start: float, dur: float, note: float, amp: float, punchy: bool) -> None:
    def make():
        f = _hz(note)
        n = int(dur * SR)
        t = np.arange(n, dtype=np.float32) / SR
        body = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.12 * np.sin(2 * np.pi * 3 * f * t)
        body = body * (np.exp(-(3.2 if punchy else 1.2) * t) * 0.8 + 0.2)
        return (body * _env(n, 0.008, min(0.1, dur * 0.4))).astype(np.float32)

    buf.add(start, _memo(("bass", int(note), round(dur, 3), punchy), make), None, amp * 0.8)


def _kick(buf: _Buf, start: float, amp: float) -> None:
    n = int(0.28 * SR)
    t = np.arange(n, dtype=np.float32) / SR
    freq = 46.0 + 110.0 * np.exp(-t * 28.0)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase) * np.exp(-t * 11.0)
    click = np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 90.0) * 0.2
    buf.add(start, (body + click).astype(np.float32), None, amp)


def _noise_burst(rng: np.random.Generator, dur: float, decay: float, lo_cut: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    x = rng.standard_normal(n).astype(np.float32)
    # a crude high-pass: subtract a running mean (cut-off ~ lo_cut)
    k = max(2, int(SR / max(200.0, lo_cut)))
    x = x - np.convolve(x, np.ones(k, dtype=np.float32) / k, mode="same")
    return x * np.exp(-decay * t)


def _hat(buf: _Buf, rng, start: float, amp: float, open_: bool = False) -> None:
    x = _noise_burst(rng, 0.16 if open_ else 0.05, 14.0 if open_ else 60.0, 6000.0)
    buf.add(start, x * 0.5, x * 0.4, amp * 0.5)


def _clap(buf: _Buf, rng, start: float, amp: float) -> None:
    x = _noise_burst(rng, 0.22, 20.0, 1200.0)
    n = len(x)
    t = np.arange(n, dtype=np.float32) / SR
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 28.0) * 0.4
    buf.add(start, (x * 0.7 + tone).astype(np.float32), (x * 0.6 + tone).astype(np.float32), amp * 0.55)


def _reverb(x: np.ndarray, wet: float, seed: int, seconds: float = 2.2) -> np.ndarray:
    """A synthetic room: decaying, decorrelated noise per channel, mixed in by FFT convolution."""
    from scipy.signal import fftconvolve

    rng = np.random.default_rng(seed + 1000)
    n = int(seconds * SR)
    t = np.arange(n, dtype=np.float32) / SR
    out = np.empty_like(x)
    for ch in range(2):
        ir = rng.standard_normal(n).astype(np.float32) * np.exp(-t * (3.0 / seconds * 2.3))
        # roll the highs off with time (a real room absorbs them): a one-pole low-pass whose cut-off falls with the tail
        ir[1:] = 0.55 * ir[1:] + 0.45 * ir[:-1]
        ir /= (np.sqrt(np.sum(ir ** 2)) + 1e-9)
        out[:, ch] = x[:, ch] * (1.0 - wet) + wet * fftconvolve(x[:, ch], ir, mode="full")[: len(x)] * 1.2
    return out


def _arp_pattern(kind: str, chord: list[int], bar: int) -> list[tuple[float, float, int]]:
    """(position in beats, length in beats, note) inside one 4-beat bar."""
    c = chord
    up = [c[0] + 12, c[1] + 12, c[2] + 12, (c[3] if len(c) > 3 else c[0] + 12) + 12]
    if kind == "slow":                                   # one soft note per beat, rising and falling
        order = [up[0], up[1], up[2], up[1]] if bar % 2 == 0 else [up[1], up[2], up[3], up[2]]
        return [(i * 1.0, 1.5, order[i]) for i in range(4)]
    if kind == "comp":                                   # jazzy comping: chord stabs on the off beats
        return [(0.0, 1.0, up[1]), (1.5, 1.0, up[2]), (2.5, 0.8, up[3]), (3.5, 0.5, up[1])]
    if kind == "eighths":
        order = [up[0], up[1], up[2], up[1], up[0] + 12, up[2], up[1], up[0]]
        return [(i * 0.5, 0.7, order[i]) for i in range(8)]
    if kind == "sixteenths":
        order = [up[0], up[2], up[1], up[2]] * 4
        return [(i * 0.25, 0.4, order[i] - 12 if i % 8 >= 4 else order[i]) for i in range(16)]
    return []


def synthesize(spec: dict) -> np.ndarray:
    """One starter track as stereo float32 [n, 2] at SR, normalised to about -3 dBFS with a fade in and a long fade out."""
    _MEMO.clear()
    rng = np.random.default_rng(int(spec["seed"]))
    bpm = float(spec["bpm"])
    beat = 60.0 / bpm
    bar_s = 4 * beat
    bars = int(spec["bars"])
    prog = spec["prog"]
    lay = spec["layers"]
    seconds = bars * bar_s + 3.0                          # the tail rings out
    buf = _Buf(seconds)
    swing = float(spec.get("swing") or 0.0)
    for b in range(bars):
        chord = prog[b % len(prog)]
        t0 = b * bar_s
        # section dynamics: a gentle breathing over 4-bar phrases, and a fuller second half
        phrase = 0.82 + 0.18 * math.sin(math.pi * ((b % 4) / 4.0 + 0.1))
        fuller = 1.0 if b >= bars // 2 else 0.88
        level = phrase * fuller
        if lay["pad"] > 0:
            _pad_voice(buf, t0, bar_s + 0.6, [chord[0] - 12] + chord[1:], lay["pad"] * 0.55 * level, soft=spec["mood"] in ("calm", "warm"))
        if lay["bass"] > 0:
            root = chord[0]
            while root > 45:
                root -= 12
            while root < 33:
                root += 12
            if spec["mood"] in ("energetic", "happy"):
                for i in range(8):
                    if i % 4 == 2 and spec["mood"] == "energetic":
                        continue
                    _bass(buf, t0 + i * beat / 2, beat * 0.45, root + (12 if i % 4 == 3 else 0), lay["bass"] * level, True)
            elif spec["mood"] == "dramatic":
                _bass(buf, t0, bar_s * 0.98, root, lay["bass"] * level, False)
            else:
                _bass(buf, t0, beat * 1.9, root, lay["bass"] * level, False)
                _bass(buf, t0 + 2 * beat, beat * 1.9, root + (7 if b % 2 else 0), lay["bass"] * 0.8 * level, False)
        if lay["pluck"] > 0 and spec["arp"] in ("slow", "comp", "eighths", "sixteenths"):
            sparse = (b % 4 == 3) and spec["mood"] in ("calm", "dramatic")                       # a breath at the end of each phrase
            for pos, ln, note in _arp_pattern(spec["arp"], chord, b):
                if sparse and pos >= 2.0:
                    continue
                off = swing * beat * 0.5 if (pos % 1.0) >= 0.5 else 0.0
                jitter = float(rng.uniform(-0.004, 0.004))
                vel = 0.78 + 0.22 * float(rng.random())
                _pluck(buf, t0 + pos * beat + off + jitter, ln * beat, note, lay["pluck"] * 0.5 * vel * level, spec["pluck_style"], pan=0.3 + 0.4 * float(rng.random()))
        if spec["mood"] == "dramatic" and b % 4 == 0:                                            # a low impact on the first bar of a phrase
            _kick(buf, t0, lay["kick"] * 1.1)
        elif lay["kick"] > 0 and spec["mood"] != "dramatic":
            four = spec["mood"] in ("energetic",)
            hits = [0, 1, 2, 3] if four else ([0, 2.5] if spec["mood"] == "warm" else [0, 2])
            if b >= 2 or spec["mood"] == "calm":
                for h in hits:
                    _kick(buf, t0 + h * beat, lay["kick"] * (0.8 if h else 1.0) * level)
        if lay["hat"] > 0 and b >= 2:
            step = 0.5
            for i in range(int(4 / step)):
                pos = i * step
                if spec["mood"] == "energetic" and (i % 2 == 1):
                    _hat(buf, rng, t0 + pos * beat, lay["hat"] * level, open_=True)
                elif spec["mood"] != "energetic":
                    swung = swing * beat * 0.5 if i % 2 else 0.0
                    _hat(buf, rng, t0 + pos * beat + swung, lay["hat"] * (0.6 if i % 2 else 1.0) * level)
        if lay["clap"] > 0 and b >= 4:
            for h in (1, 3):
                _clap(buf, rng, t0 + h * beat, lay["clap"] * level)
    x = buf.data
    x = _reverb(x, float(spec["reverb"]), int(spec["seed"]))
    # gentle sidechain-style "breathing" for the electronic tracks: the bed ducks a little on every beat so the kick sits clear
    if spec["mood"] in ("energetic", "happy"):
        t = np.arange(len(x), dtype=np.float32) / SR
        phase = (t % beat) / beat
        x *= (0.72 + 0.28 * (1.0 - np.exp(-phase * 6.0)))[:, None].astype(np.float32)
    # a bed is judged by its loudness, not its peak: bring it to about -18 dBFS RMS (a calm pad and a drum track then sit equally loud under a voice),
    # let a soft limiter catch the drum peaks, remove DC, and keep every sample under -1 dBFS
    x = x - np.mean(x, axis=0, keepdims=True)
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9)
    x = x * (10 ** (-18.0 / 20) / rms)
    x = np.tanh(x * 1.1) / 1.1
    x = x * min(1.0, 0.89 / (float(np.max(np.abs(x))) + 1e-9))
    n = len(x)
    fade_in = np.linspace(0, 1, int(0.35 * SR), dtype=np.float32)
    x[: len(fade_in)] *= fade_in[:, None]
    fade_out = np.linspace(1, 0, int(2.8 * SR), dtype=np.float32) ** 1.4
    x[n - len(fade_out):] *= fade_out[:, None]
    return x.astype(np.float32)


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
    return path


# ------------------------------------------------------------------ the cache and the shop's library

def cache_dir() -> Path:
    from services.audio import studio

    path = studio.root() / "_starter"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cached_file(spec: dict) -> Path:
    return cache_dir() / f"starter_{spec['key']}_v{STARTER_VERSION}.m4a"


@contextmanager
def _lock():
    path = cache_dir() / ".lock"
    with open(path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def render_track(spec: dict, *, force: bool = False) -> Path:
    """The track as an .m4a in the cache (made once: a few seconds of CPU).  Raises RuntimeError if ffmpeg cannot encode it."""
    dest = cached_file(spec)
    if dest.is_file() and dest.stat().st_size > 20_000 and not force:
        return dest
    from services.video.ffmpeg import FFMPEG

    with tempfile.TemporaryDirectory(prefix="nm-starter-") as tmp:
        wav = write_wav(Path(tmp) / "t.wav", synthesize(spec))
        part = Path(tmp) / "t.m4a"
        proc = subprocess.run([str(FFMPEG), "-nostdin", "-y", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                               "-movflags", "+faststart", str(part)], capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        if proc.returncode != 0 or not part.is_file():
            raise RuntimeError((proc.stderr or "ffmpeg failed")[-300:])
        shutil.move(str(part), str(dest))
    return dest


def enabled() -> bool:
    try:
        from django.conf import settings

        return bool(getattr(settings, "AUTOEDIT_STARTER_MUSIC", True))
    except Exception:  # noqa: BLE001
        return False


def ensure_for_store(store, *, upgrade_on_node: bool = True) -> dict:
    """If the shop's library has no ready music, give it the starter tracks; and while its library holds starter tracks, ask the processing node
    for real generated ones (once per two weeks, see `queue_node_music`).  Returns `{"created": n, "ids": [...], "queued_node": n}`; never raises -
    the edit goes on without music rather than fail."""
    out = {"created": 0, "ids": [], "queued_node": 0}
    if store is None or not getattr(store, "pk", None) or not enabled():
        return out
    try:
        from apps.ai.models import AudioAsset
        from services.audio import studio

        have = AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY)
        if not have.exists():
            with _lock():
                if not have.exists():                                          # another worker may have just done it
                    for spec in TRACKS:
                        try:
                            src = render_track(spec)
                        except Exception as exc:  # noqa: BLE001 - one track failing must not stop the others
                            logger.warning("starter music %s could not be made: %s", spec["key"], exc)
                            continue
                        asset = AudioAsset(store=store, kind=AudioAsset.Kind.MUSIC, status=AudioAsset.Status.READY, title=spec["title"][:120], text=spec["text"],
                                           prompt=spec["style"], engine=STARTER_ENGINE, license=STARTER_LICENSE, commercial=True, saved=True,
                                           params={"bpm": spec["bpm"], "style": spec["style"], "mood": spec["mood"], "starter": spec["key"], "version": STARTER_VERSION})
                        rel = f"store_{store.pk}/music_{uuid.uuid4().hex[:16]}.m4a"
                        dest = studio.root() / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(src, dest)
                        asset.file_name = rel
                        asset.size = dest.stat().st_size
                        asset.duration = studio._probe(dest)
                        asset.save()
                        out["ids"].append(asset.pk)
                    out["created"] = len(out["ids"])
            if out["created"]:
                logger.info("starter music: %s tracks added to the library of store %s", out["created"], store.pk)
        if upgrade_on_node and AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, engine=STARTER_ENGINE).exists():
            out["queued_node"] = queue_node_music(store)
    except Exception as exc:  # noqa: BLE001
        logger.warning("starter music for store %s failed: %s", getattr(store, "pk", "?"), exc)
    return out


#: the ACE-Step styles worth asking the node for (studio.MUSIC_STYLES ids): a calm bed for talking videos, a bright one, a cinematic one
NODE_STYLES = ("calm", "upbeat", "cinematic")


#: a failed try (no node registered, engine not installed, the day's allowance used) is not repeated for this long
RETRY_AFTER_HOURS = 6


def queue_node_music(store, styles=NODE_STYLES, seconds: float = 60.0) -> int:
    """Queue real generated tracks on the processing node (durable: they wait while it is off and are made by themselves when it comes on).  Once per
    shop per UPGRADE_EVERY_DAYS; a refusal is remembered for RETRY_AFTER_HOURS so an edit never pays for asking again.  Returns how many were queued."""
    try:
        from django.utils import timezone

        from apps.ai.models import AudioAsset
        from services.audio import studio

        now = timezone.now()
        if AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, engine="acestep", created_at__gt=now - timedelta(days=UPGRADE_EVERY_DAYS)).exists():
            return 0
        mark = AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC, engine=STARTER_ENGINE).order_by("id").first()
        if mark is not None:
            tried = (mark.params or {}).get("node_music_tried_at")
            try:
                if tried and now - datetime.fromisoformat(tried) < timedelta(hours=RETRY_AFTER_HOURS):
                    return 0
            except (TypeError, ValueError):
                pass
        queued = 0
        for style in styles:
            try:
                asset = studio.create_music(store, None, style=style, seconds=seconds)
            except studio.StudioError as exc:
                logger.info("node music (%s) not queued: %s", style, exc)
                break                                                          # no node / no engine / the day's allowance: the same answer for the rest
            if getattr(asset, "pk", None):
                AudioAsset.objects.filter(pk=asset.pk).update(saved=True)       # a library track from the start (drafts are swept after a day)
            queued += 1
        if not queued and mark is not None:
            AudioAsset.objects.filter(pk=mark.pk).update(params={**(mark.params or {}), "node_music_tried_at": now.isoformat()})
        return queued
    except Exception as exc:  # noqa: BLE001
        logger.info("node music not queued: %s", exc)
        return 0
