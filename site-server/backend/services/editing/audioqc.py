"""Quality control of a RENDERED mix: is the same speech playing twice, is the music on top of the voice, is the left channel
the right one's opposite?

Why this exists (1405/08/22, the owner: «خروجی همزمان پخش می‌شود، صداها روی هم می‌افتند و چیزی نمی‌شود فهمید»).  Three different
things make a finished video sound like several people talking at once, and each of them is a measurable property of the
FILE, not of the project that made it:

* **the same speech twice, a little apart** — a clip's own sound AND a copy of it on an audio track, a voice-over laid over the
  speaker it replaces, two takes of one sentence.  The mix has an *echo*: its auto-correlation has a clear peak at the offset;
* **music as loud as the voice** — no ducking: the voice band is masked and the words cannot be told apart;
* **phase cancellation / a mono-in-one-ear mix** — the two channels barely correlate (or anti-correlate).

`analyze(path)` measures all three on the file itself (ffmpeg → 16 kHz mono f32 → numpy), cheap enough to run after every
render (≈ 1 s for a minute of video) and the tests use it as the referee: the regression test renders a small project and
asserts the result is clean.  Nothing here changes a file.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SR = 16000
#: an echo/duplicate this close or closer is "the same moment" and is heard as a chorus/comb filter; beyond MAX_LAG it is
#: another sentence (speech repeats itself over seconds, not hundreds of milliseconds)
MIN_LAG = 0.040
MAX_LAG = 1.2
WINDOW = 6.0
HOP = 3.0
#: normalised auto-correlation at the echo lag.  A mix of x(t) + g·x(t−δ) has r = g / (1 + g²): 0.40 for an equal copy, 0.28 at −6 dB,
#: 0.15 at −12 dB.  Natural speech sits below 0.08 once pre-whitened.  0.16 is the line a listener starts to notice.
ECHO_R = 0.16
#: the share of the speech windows that must show the SAME lag before it counts (a single window can be a held vowel)
ECHO_SHARE = 0.34
ACTIVE_DB = -45.0


#: the band a human voice lives in; the echo test looks only here so a stationary tone or the hiss above the voice cannot pose as a repeat
SPEECH_BAND = (200.0, 3500.0)


def decode(path, *, channel: int | None = None, sr: int = SR, max_seconds: float = 600.0, band: tuple[float, float] | None = None) -> np.ndarray:
    """The audio of a media file as mono float32 at `sr` (empty array when there is none)."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-t", f"{max_seconds:.0f}"]
    chain = []
    if channel is not None:
        chain.append(f"pan=mono|c0=c{int(channel)}")
    else:
        cmd += ["-ac", "1"]
    if band:
        # steep (cascaded) edges: a loud tone just outside the band must not leak in and pose as a repeating signal
        chain += [f"highpass=f={band[0]:.0f}"] * 2 + [f"lowpass=f={band[1]:.0f}"] * 3
    if chain:
        cmd += ["-af", ",".join(chain)]
    cmd += ["-ar", str(sr), "-f", "f32le", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=300, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("audioqc.decode(%s) failed: %s", path, exc)
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(raw, dtype=np.float32).copy()


def _whiten(x: np.ndarray) -> np.ndarray:
    """Pre-emphasis + a gentle high-pass: removes the pitch/tonal periodicity that makes speech correlate with itself at short
    lags, so what is left in the auto-correlation is repetition, not voicing."""
    if len(x) < 4:
        return x
    y = np.empty_like(x)
    y[0] = x[0]
    y[1:] = x[1:] - 0.97 * x[:-1]
    return y


def _acorr(x: np.ndarray, lo: int, hi: int) -> np.ndarray:
    n = len(x)
    size = 1 << int(np.ceil(np.log2(2 * n)))
    spec = np.fft.rfft(x, size)
    ac = np.fft.irfft(spec * np.conj(spec))[: hi + 1]
    return ac / (ac[0] + 1e-12)


def echo_report(x: np.ndarray, sr: int = SR) -> dict:
    """Is a delayed copy of the speech in this signal?  `{"doubled": bool, "lag_s", "strength", "share", "windows"}`."""
    out = {"doubled": False, "lag_s": None, "strength": 0.0, "share": 0.0, "windows": 0}
    if len(x) < int(2 * sr):
        return out
    x = _whiten(x.astype(np.float32, copy=False))
    win, hop = int(WINDOW * sr), int(HOP * sr)
    lo, hi = int(MIN_LAG * sr), int(MAX_LAG * sr)
    found: list[tuple[float, float]] = []
    total = 0
    pos = 0
    while pos + win // 2 <= len(x):
        seg = x[pos: pos + win]
        pos += hop
        rms = float(np.sqrt(np.mean(seg ** 2)) + 1e-12)
        if 20 * np.log10(rms) < ACTIVE_DB:
            continue
        total += 1
        ac = _acorr(seg * np.hanning(len(seg)), lo, hi)[lo:]
        i = int(np.argmax(ac))
        found.append(((i + lo) / sr, float(ac[i])))
    out["windows"] = total
    if not total:
        return out
    strong = [(lag, r) for lag, r in found if r >= ECHO_R]
    if not strong:
        out["strength"] = round(max((r for _, r in found), default=0.0), 3)
        return out
    # the same lag (±12 ms) in a third of the speech windows
    best_lag, best_hits = None, []
    for lag, _ in strong:
        hits = [(l2, r2) for l2, r2 in strong if abs(l2 - lag) <= 0.012]
        if len(hits) > len(best_hits):
            best_lag, best_hits = lag, hits
    share = len(best_hits) / total
    out["share"] = round(share, 3)
    out["strength"] = round(float(np.mean([r for _, r in best_hits])), 3)
    out["lag_s"] = round(float(np.mean([l for l, _ in best_hits])), 3)
    out["doubled"] = share >= ECHO_SHARE
    return out


def channel_report(left: np.ndarray, right: np.ndarray) -> dict:
    n = min(len(left), len(right))
    if n < SR:
        return {"corr": None, "out_of_phase": False}
    l, r = left[:n], right[:n]
    if float(np.std(l)) < 1e-6 or float(np.std(r)) < 1e-6:
        return {"corr": None, "out_of_phase": False}
    c = float(np.corrcoef(l, r)[0, 1])
    return {"corr": round(c, 3), "out_of_phase": c < -0.25}


def level_db(x: np.ndarray) -> float:
    if not len(x):
        return -120.0
    return round(float(20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9)), 1)


def peak_db(x: np.ndarray) -> float:
    if not len(x):
        return -120.0
    return round(float(20 * np.log10(np.max(np.abs(x)) + 1e-9)), 1)


def loudness_lufs(path) -> float | None:
    """Integrated loudness (EBU R128) via ffmpeg's ebur128 — what the platforms measure."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    text = proc.stderr or ""
    mark = text.rfind("Integrated loudness:")
    if mark < 0:
        return None
    for line in text[mark:].splitlines()[1:4]:
        line = line.strip()
        if line.startswith("I:"):
            try:
                return round(float(line.split()[1]), 1)
            except (IndexError, ValueError):
                return None
    return None


def settle_loudness(path, *, target: float = -14.0, tp: float = -1.0, tolerance: float = 0.8, max_rounds: int = 2) -> dict:
    """Bring a finished mp4 to the loudness the owner asked for (-14 LUFS for the social networks).

    The render's one-pass `loudnorm` is dynamic: on speech with long quiet stretches it lands 1-3 LU away from the target (measured on the
    owner's own video: −16.1 for a −14 request).  So the FILE is measured with the same meter the platforms use (EBU R128 via ebur128) and,
    only when it is off by more than `tolerance`, its sound is re-encoded with the missing gain and a true-peak limiter — the picture stream is
    copied untouched, so it costs seconds, never a second render.  Never raises and never leaves a half-written file:
    `{"lufs", "target", "adjusted", "rounds", "gain_db"}`, `{}` when the file has no sound or cannot be measured."""
    path = Path(path)
    try:
        before = loudness_lufs(path)
        if before is None or before < -69.0:
            return {}
        rep: dict = {"lufs": before, "target": float(target), "adjusted": False, "rounds": 0, "gain_db": 0.0}
        current, total = before, 0.0
        limit = 10 ** ((float(tp) - 0.3) / 20)
        for _ in range(max_rounds):
            delta = float(target) - current
            if abs(delta) <= tolerance:
                break
            gain = max(-12.0, min(12.0, delta))
            tmp = path.with_name(path.stem + ".loud" + path.suffix)
            cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(path), "-map", "0", "-c", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                   "-af", f"volume={gain:.2f}dB,alimiter=limit={limit:.3f}:level=disabled,aresample=48000", "-movflags", "+faststart", str(tmp)]
            try:
                done = subprocess.run(cmd, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                tmp.unlink(missing_ok=True)
                break
            if done.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 1024:
                tmp.unlink(missing_ok=True)
                break
            after = loudness_lufs(tmp)
            if after is None or abs(float(target) - after) >= abs(float(target) - current):
                tmp.unlink(missing_ok=True)          # not closer (the limiter holds the peaks down): keep the file as it was
                break
            tmp.replace(path)
            current, total = after, total + gain
            rep["adjusted"] = True
            rep["rounds"] += 1
        rep["lufs"], rep["gain_db"] = current, round(total, 1)
        rep["before"] = before
        return rep
    except Exception as exc:  # noqa: BLE001 — a loudness touch-up must never fail a render
        logger.info("settle_loudness failed for %s: %s", path, exc)
        return {}


def masking_report(voice: np.ndarray, music: np.ndarray) -> dict:
    """How far the voice stands above the music when both are heard (their levels in the final mix, each measured alone)."""
    v, m = level_db(voice), level_db(music)
    return {"voice_db": v, "music_db": m, "margin_db": round(v - m, 1), "masked": (v - m) < 6.0 and m > -60}


def analyze(path, *, with_loudness: bool = False) -> dict:
    """Everything above for one rendered file.  Never raises: `{"ok": False, "reason": …}` when there is no audio."""
    mono = decode(path)
    if not len(mono):
        return {"ok": False, "reason": "no_audio"}
    rep: dict = {"ok": True, "seconds": round(len(mono) / SR, 2), "level_db": level_db(mono), "peak_db": peak_db(mono)}
    rep["echo"] = echo_report(mono)
    left, right = decode(path, channel=0), decode(path, channel=1)
    rep["channels"] = channel_report(left, right) if len(right) else {"corr": None, "out_of_phase": False}
    if with_loudness:
        rep["lufs"] = loudness_lufs(path)
    problems = []
    if rep["echo"]["doubled"]:
        problems.append("همان گفتار دو بار و با کمی فاصله شنیده می‌شود (روی هم افتادنِ صدا)")
    if rep["channels"]["out_of_phase"]:
        problems.append("دو کانالِ صدا ناهمفاز است و در پخشِ تک‌بلندگو صدا کم می‌شود")
    if rep["peak_db"] > -0.1:
        problems.append("صدا به سقف رسیده و می‌شکند")
    rep["problems"] = problems
    rep["clean"] = not problems
    return rep


def quick_check(path) -> dict:
    """`analyze` for the render pipeline: swallow every error — a QC must never fail a render."""
    try:
        return analyze(Path(path))
    except Exception as exc:  # noqa: BLE001
        logger.info("audioqc failed for %s: %s", path, exc)
        return {"ok": False, "reason": "error"}
