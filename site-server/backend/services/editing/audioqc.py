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
import re
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


_NUM = r"(-?[0-9]+(?:\.[0-9]+)?|-inf)"


def loudness_stats(path) -> dict | None:
    """What the platforms measure on a file, in ONE pass of ffmpeg's ebur128 (4x oversampled true peak included):
    `{"lufs": integrated loudness or None, "tp": true peak in dBTP or None}`; None when the file cannot be measured.

    The true peak is read from the DECODED file (an AAC file decodes to floats that can be above full scale), which is exactly what the
    owner's ear and the platforms' meters see - the peak of the filter graph that fed the encoder is not."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    text = proc.stderr or ""
    mark = text.rfind("Integrated loudness:")
    if mark < 0:
        return None
    tail = text[mark:]
    lufs = tp = None
    m = re.search(r"I:\s*" + _NUM + r"\s*LUFS", tail)
    if m and m.group(1) != "-inf":
        lufs = round(float(m.group(1)), 1)
    m = re.search(r"True peak:\s*Peak:\s*" + _NUM + r"\s*dBFS", tail)
    if m:
        tp = -120.0 if m.group(1) == "-inf" else round(float(m.group(1)), 1)
    if lufs is None and tp is None:
        return None
    return {"lufs": lufs, "tp": tp}


def loudness_lufs(path) -> float | None:
    """Integrated loudness (EBU R128) via ffmpeg's ebur128 - what the platforms measure."""
    stats = loudness_stats(path)
    return stats["lufs"] if stats else None


#: the limiter works this far BELOW the true-peak ceiling (`audiofx.AAC_HEADROOM_DB`, 1.0 dB): the AAC encoder re-quantises the signal and the decoded
#: file overshoots the limiter by up to a dB (measured on the owner's own video: a -1.3 dBFS limiter came out of the encoder at +0.3 dBFS with clipped
#: samples).  It is only the starting point; `settle_loudness` MEASURES the decoded result and lowers the ceiling further until the file really holds it.
from .audiofx import AAC_HEADROOM_DB  # noqa: E402
#: a measured true peak this far above the ceiling is fixed even when the loudness is already right
PEAK_TRIGGER_DB = 0.25
#: the most gain one pass may add or take away (a very quiet recording needs +20 dB; the limiter keeps the peaks under the ceiling)
GAIN_LIMIT_DB = 24.0


def _encode_audio(src: Path, dst: Path, gain_db: float, ceiling_db: float) -> bool:
    """The picture copied untouched, the sound re-encoded with `gain_db` and a peak limiter at `ceiling_db` dBFS.  True when `dst` is a real file."""
    limit = min(0.99, max(0.0625, 10 ** (float(ceiling_db) / 20)))
    chain = (f"volume={gain_db:.2f}dB," if abs(gain_db) > 0.005 else "") + f"alimiter=limit={limit:.3f}:level=disabled:attack=3:release=40,aresample=48000"
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(src), "-map", "0", "-c", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-af", chain, "-movflags", "+faststart", str(dst)]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        dst.unlink(missing_ok=True)
        return False
    if done.returncode != 0 or not dst.is_file() or dst.stat().st_size < 1024:
        dst.unlink(missing_ok=True)
        return False
    return True


def _badness(lufs: float | None, tp: float | None, target: float | None, tp_ceiling: float) -> float:
    """Lower is better: a peak above the ceiling costs 10x what the same distance of loudness costs (a clipped file is a defect, a file
    0.5 LU quiet is not)."""
    over = max(0.0, (tp if tp is not None else tp_ceiling) - tp_ceiling)
    off = abs(target - lufs) if (target is not None and lufs is not None) else 0.0
    return 10.0 * over + off


def settle_loudness(path, *, target: float | None = -14.0, tp: float = -1.0, tolerance: float = 0.8, max_rounds: int = 3,
                    peak_trigger: float | None = None) -> dict:
    """Bring a finished mp4 to the loudness the owner asked for (-14 LUFS for the social networks) AND under the true-peak ceiling, both
    measured on the decoded FILE.

    The render's one-pass `loudnorm` is dynamic: on speech with long quiet stretches it lands 1-3 LU away from the target (measured on the
    owner's own video: -16.1 for a -14 request).  So the FILE is measured with the same meter the platforms use (EBU R128 via ebur128) and,
    when it is off by more than `tolerance` OR its true peak is above the ceiling, its sound is re-encoded with the missing gain and a peak
    limiter - the picture stream is copied untouched, so it costs seconds, never a second render.

    The limiter is not enough on its own: the AAC encoder overshoots it (see `AAC_HEADROOM_DB`).  So every candidate is DECODED and measured;
    if it still peaks above `tp` the limiter ceiling is lowered by the overshoot and the original is encoded again (always from the original -
    one generation of AAC, never a re-encode of a re-encode), and as a last resort the gain itself comes down.  The best candidate wins; if
    none is better than the file as it was, the file is left as it was.

    `target=None` = peaks only (a project that did not ask for loudness normalisation keeps its loudness; only a file that really clips is
    touched, and `peak_trigger` defaults to -0.1 dBTP then).  Never raises and never leaves a half-written file:
    `{"lufs", "target", "adjusted", "rounds", "gain_db", "before", "tp", "tp_before", "tp_ceiling"}`, `{}` when the file has no sound or cannot
    be measured."""
    path = Path(path)
    try:
        first = loudness_stats(path)
        if not first or first["lufs"] is None or first["lufs"] < -69.0:
            return {}
        before, tp_before = first["lufs"], first["tp"]
        rep: dict = {"lufs": before, "target": (float(target) if target is not None else None), "adjusted": False, "rounds": 0, "gain_db": 0.0,
                     "before": before, "tp": tp_before, "tp_before": tp_before, "tp_ceiling": float(tp)}
        trigger = float(peak_trigger) if peak_trigger is not None else (PEAK_TRIGGER_DB + float(tp) if target is not None else -0.1)
        loud_off = target is not None and abs(float(target) - before) > tolerance
        peak_over = tp_before is not None and tp_before > trigger
        if not loud_off and not peak_over:
            return rep
        gain = max(-GAIN_LIMIT_DB, min(GAIN_LIMIT_DB, float(target) - before)) if loud_off else 0.0
        ceiling = float(tp) - AAC_HEADROOM_DB
        best_score = _badness(before, tp_before, target, float(tp))
        best: tuple[Path, dict, float] | None = None
        tried: list[Path] = []
        encoded = 0
        for n in range(max(1, max_rounds)):
            tmp = path.with_name(f"{path.stem}.loud{n}{path.suffix}")
            tried.append(tmp)
            if not _encode_audio(path, tmp, gain, ceiling):
                break
            encoded += 1
            st = loudness_stats(tmp)
            if not st or st["lufs"] is None:
                break
            score = _badness(st["lufs"], st["tp"], target, float(tp))
            if score < best_score - 1e-6:
                best_score, best = score, (tmp, st, gain)
            over = (st["tp"] if st["tp"] is not None else float(tp)) - float(tp)
            short = (float(target) - st["lufs"]) if target is not None else 0.0          # > 0: still too quiet
            if over > 0.05:
                ceiling -= over + 0.2                            # the codec overshoot is measured, so the limiter goes under it by exactly that
                if n >= 1:
                    gain -= over + 0.1                           # a second miss: a plain attenuation is exact
            elif target is not None and abs(short) > tolerance * 0.5 and n + 1 < max_rounds:
                if over < -0.5:
                    ceiling += -over - 0.1                       # the first guess was too careful: work closer to the ceiling
                gain = max(-GAIN_LIMIT_DB, min(GAIN_LIMIT_DB, gain + short))      # the limiter eats part of any extra gain; the next measurement tells how much
            else:
                break                                            # holds the ceiling and the loudness is where it was asked: done
        if best is not None:
            tmp, st, used = best
            tmp.replace(path)
            rep.update(adjusted=True, gain_db=round(used, 1), lufs=st["lufs"], tp=st["tp"])
        rep["rounds"] = encoded
        for t in tried:
            t.unlink(missing_ok=True)
        return rep
    except Exception as exc:  # noqa: BLE001 - a loudness touch-up must never fail a render
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
        stats = loudness_stats(path) or {}
        rep["lufs"] = stats.get("lufs")
        if stats.get("tp") is not None:
            # the 16 kHz mono decode above is a tool for the echo / phase tests, not a peak meter: the channel average of a centred voice reads up to 3 dB
            # ABOVE either channel (measured on the owner's own video: -0.1 against a true peak of -1.1), which is how a clean file was once called clipping.
            # The verdict goes by the TRUE peak of the delivered file, per channel, the way the platforms measure it.
            rep["mono_peak_db"] = rep["peak_db"]
            rep["peak_db"] = stats["tp"]
            rep["true_peak_db"] = stats["tp"]
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
    """`analyze` for the render pipeline: swallow every error — a QC must never fail a render.  Includes the loudness meter (one more
    ffmpeg pass, about a second per minute of video) so the verdict on clipping goes by the true peak of the delivered file."""
    try:
        return analyze(Path(path), with_loudness=True)
    except Exception as exc:  # noqa: BLE001
        logger.info("audioqc failed for %s: %s", path, exc)
        return {"ok": False, "reason": "error"}
