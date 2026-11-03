"""What the timeline draws on a clip, computed once per file and cached: waveform peaks, a filmstrip sprite, beat markers
and speech spans. §23.4

All four take a LOCAL file path (the caller resolves a ref to a path, as `editor_project.sources` does) and return plain
data. They cost one ffmpeg pass each, so the result is cached under ``MEDIA_ROOT/generated/editing/cache/`` keyed on
(absolute path, mtime, size, kind, parameters): replace the file and the key changes, the old entry just ages out.

Built for a 2-core / 3 GB box: ffmpeg's output is streamed through a pipe in small chunks and reduced with numpy as it
arrives — a one-hour recording never sits in memory — and the cache is bounded (`cleanup`, oldest first, called after every
write at most once a minute). Two threads (or two gunicorn workers) asking for the same key do the work once: a per-key
lock inside a process, an atomic rename across processes, so a half-written file is never read.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from django.conf import settings

from .errors import TimelineError

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 300 * 1024 * 1024
DEFAULT_MAX_AGE_DAYS = 14
_CLEANUP_EVERY = 60.0

#: Waveform decoding rate. 8 kHz mono is plenty for a picture of the loudness.
WAVE_SR = 8000
#: Beat detection works at 22.05 kHz, 1024-sample frames (46 ms), hop 512 (23 ms).
BEAT_SR = 22050
BEAT_FRAME = 1024
BEAT_HOP = 512
#: Never decode more than this for beats (a 15-minute cap keeps the pass bounded).
BEAT_MAX_SECONDS = 900
#: A single ffmpeg call that takes longer than this is stuck, not slow.
CALL_TIMEOUT = 600

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_cleanup_at = 0.0


# ------------------------------------------------------------------ cache plumbing


def cache_dir() -> Path:
    path = Path(settings.MEDIA_ROOT) / "generated" / "editing" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stat(path) -> os.stat_result:
    try:
        return Path(path).stat()
    except OSError:
        raise TimelineError("فایلِ رسانه پیدا نشد.") from None


def _key(path, kind: str, **params) -> str:
    st = _stat(path)
    raw = f"{os.path.abspath(str(path))}|{st.st_mtime_ns}|{st.st_size}|{kind}|{json.dumps(params, sort_keys=True)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            if len(_LOCKS) > 2000:           # bounded: a lock that is not held can be re-created
                for k in [k for k, v in _LOCKS.items() if not v.locked()][:1000]:
                    _LOCKS.pop(k, None)
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _write_atomic(dest: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=dest.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        # mkstemp makes 0600; the filmstrip sprite is served by nginx (another user), so make it world-readable
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _touch(path: Path) -> None:
    try:
        os.utime(path, None)                 # a hit refreshes the entry, so `cleanup` keeps what is in use
    except OSError:
        pass


def _read_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    _touch(path)
    return data


def _maybe_cleanup() -> None:
    global _cleanup_at
    now = time.monotonic()
    if now - _cleanup_at < _CLEANUP_EVERY:
        return
    _cleanup_at = now
    try:
        cleanup()
    except Exception as exc:  # noqa: BLE001 — housekeeping must never fail a request
        logger.info("media cache cleanup failed: %s", exc)


def cleanup(max_bytes: int = DEFAULT_MAX_BYTES, max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> dict:
    """Delete entries older than `max_age_days`, then the oldest-used ones until the folder fits in `max_bytes`."""
    folder = cache_dir()
    now = time.time()
    entries = []
    for p in folder.iterdir():
        try:
            st = p.stat()
        except OSError:
            continue
        if not p.is_file():
            continue
        used = max(st.st_mtime, st.st_atime)
        if p.name.endswith(".tmp") and now - st.st_mtime > 3600:          # an interrupted write
            used = 0.0
        entries.append((used, st.st_size, p))
    removed = freed = 0
    keep = []
    for used, size, p in entries:
        if used < now - max_age_days * 86400:
            try:
                p.unlink()
                removed += 1
                freed += size
            except OSError:
                keep.append((used, size, p))
        else:
            keep.append((used, size, p))
    total = sum(size for _, size, _ in keep)
    for used, size, p in sorted(keep, key=lambda e: e[0]):
        if total <= max_bytes:
            break
        try:
            p.unlink()
            removed += 1
            freed += size
            total -= size
        except OSError:
            continue
    return {"removed": removed, "freed": freed, "bytes": max(total, 0)}


# ------------------------------------------------------------------ ffmpeg helpers


def _info(path) -> dict:
    """{duration, has_audio, has_video, width, height} from ffprobe, in Persian errors."""
    from services.video.ffmpeg import VideoProcessingError, probe

    _stat(path)
    try:
        data = probe(path)
    except VideoProcessingError:
        raise TimelineError("فایل خوانده نشد؛ شاید خراب است.") from None
    info = {"duration": 0.0, "has_audio": False, "has_video": False, "width": 0, "height": 0}
    try:
        info["duration"] = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        pass
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            info["has_audio"] = True
        elif stream.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"], info["height"] = int(stream.get("width") or 0), int(stream.get("height") or 0)
    return info


def _pcm(path, sample_rate: int, *, max_seconds: float | None = None, chunk_bytes: int = 1 << 16):
    """Stream mono s16 samples of the file's audio as numpy int16 chunks (never the whole file in memory)."""
    from services.video.ffmpeg import FFMPEG

    cmd = [FFMPEG, "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sample_rate)]
    if max_seconds:
        cmd += ["-t", f"{max_seconds:.3f}"]
    cmd += ["-f", "s16le", "-"]
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + CALL_TIMEOUT
        leftover = b""
        try:
            while True:
                data = proc.stdout.read(chunk_bytes)
                if not data:
                    break
                data = leftover + data
                usable = len(data) - (len(data) % 2)
                leftover = data[usable:]
                if usable:
                    yield np.frombuffer(data[:usable], dtype="<i2")
                if time.monotonic() > deadline:
                    raise TimelineError("خواندنِ صدا بیش از حد طول کشید.")
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
        if proc.returncode not in (0, None):
            err.seek(0)
            detail = err.read().decode("utf-8", "replace").strip()[-200:]
            raise TimelineError(f"صدای فایل خوانده نشد. {detail}".strip())


# ------------------------------------------------------------------ waveform


def waveform(path, *, per_second: float = 25, max_bins: int = 6000) -> dict:
    """{"peaks": [0..1 …], "per_second": float, "duration": s} — the loudest sample of every bin (absolute, not normalised)."""
    per_second = max(1.0, min(200.0, float(per_second)))
    max_bins = max(10, min(20000, int(max_bins)))
    dest = cache_dir() / f"{_key(path, 'wave', ps=per_second, mb=max_bins)}.wave.json"
    hit = _read_json(dest)
    if hit is not None:
        return hit
    with _lock_for(dest.name):
        hit = _read_json(dest)
        if hit is not None:
            return hit
        info = _info(path)
        if not info["has_audio"]:
            raise TimelineError("این فایل صدا ندارد.")
        duration = info["duration"]
        effective = min(per_second, max_bins / duration) if duration > 0 else per_second
        bin_samples = max(1, int(round(WAVE_SR / effective)))
        peaks: list[float] = []
        carry = np.empty(0, dtype=np.int16)
        for chunk in _pcm(path, WAVE_SR):
            buf = np.concatenate([carry, chunk]) if carry.size else chunk
            n = buf.size // bin_samples
            if n:
                block = np.abs(buf[: n * bin_samples].astype(np.int32)).reshape(n, bin_samples).max(axis=1)
                peaks.extend(block.tolist())
            carry = buf[n * bin_samples:]
        if carry.size:
            peaks.append(int(np.abs(carry.astype(np.int32)).max()))
        if not peaks:
            raise TimelineError("در این فایل صدایی خوانده نشد.")
        peaks = [round(min(1.0, p / 32768.0), 3) for p in peaks[:max_bins]]
        rate = WAVE_SR / bin_samples
        result = {"peaks": peaks, "per_second": round(rate, 3), "duration": round(duration or len(peaks) / rate, 3)}
        _write_atomic(dest, json.dumps(result).encode("utf-8"))
        _maybe_cleanup()
        return result


# ------------------------------------------------------------------ filmstrip


def _thumb(path, at: float, width: int, height: int):
    from PIL import Image

    from services.video.ffmpeg import FFMPEG

    cmd = [FFMPEG, "-v", "error", "-nostdin", "-noaccurate_seek", "-ss", f"{max(0.0, at):.3f}", "-i", str(path),
           "-frames:v", "1", "-vf", f"scale={width}:{height}", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "5", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    try:
        return Image.open(io.BytesIO(out.stdout)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def filmstrip(path, *, height: int = 56, max_thumbs: int = 48, min_interval: float = 1.0) -> dict:
    """One JPEG sprite (thumbnails side by side). → {"file": Path, "count", "interval", "w", "h", "duration"}.

    Thumbnail i shows the moment `(i + 0.5) * interval`; a still image gives one thumbnail."""
    from PIL import Image

    height = max(16, min(200, int(height)))
    max_thumbs = max(1, min(200, int(max_thumbs)))
    min_interval = max(0.1, float(min_interval))
    stem = cache_dir() / _key(path, "strip", h=height, mt=max_thumbs, mi=min_interval)
    sprite, meta_file = Path(f"{stem}.strip.jpg"), Path(f"{stem}.strip.json")

    def cached():
        meta = _read_json(meta_file)
        if meta is not None and sprite.is_file():
            _touch(sprite)
            return {**meta, "file": sprite}
        return None

    hit = cached()
    if hit:
        return hit
    with _lock_for(sprite.name):
        hit = cached()
        if hit:
            return hit
        info = _info(path)
        if not info["has_video"]:
            raise TimelineError("این فایل تصویر ندارد.")
        duration = info["duration"]
        if duration <= 0.5:                                  # a still (or a one-frame clip)
            count, interval, times = 1, 1.0, [0.0]
        else:
            interval = max(min_interval, duration / max_thumbs)
            count = max(1, min(max_thumbs, int(math.ceil(duration / interval))))
            times = [max(0.0, min(duration - 0.05, (i + 0.5) * interval)) for i in range(count)]
        vw, vh = info["width"] or 16, info["height"] or 9
        width = max(16, min(240, int(round(vw * height / vh / 2.0)) * 2))
        with ThreadPoolExecutor(max_workers=2) as pool:
            images = list(pool.map(lambda t: _thumb(path, t, width, height), times))
        if not any(images):
            raise TimelineError("از این ویدیو تصویر کوچک ساخته نشد.")
        strip = Image.new("RGB", (count * width, height), (24, 24, 24))
        last = None
        for i, img in enumerate(images):
            img = img or last                                # a failed seek reuses its neighbour
            if img is not None:
                strip.paste(img, (i * width, 0))
                last = img
        buf = io.BytesIO()
        strip.save(buf, "JPEG", quality=70, optimize=True)
        _write_atomic(sprite, buf.getvalue())
        result = {"count": count, "interval": round(interval, 3), "w": width, "h": height, "duration": round(duration, 3)}
        _write_atomic(meta_file, json.dumps(result).encode("utf-8"))
        _maybe_cleanup()
        return {**result, "file": sprite}


# ------------------------------------------------------------------ beats


def _onset_envelope(path, max_seconds: float) -> np.ndarray:
    """Spectral flux per hop (log-compressed magnitudes of a Hann-windowed rFFT), computed while the audio streams in."""
    window = np.hanning(BEAT_FRAME).astype(np.float32)
    buf = np.empty(0, dtype=np.float32)
    prev = None
    flux: list[np.ndarray] = []
    for chunk in _pcm(path, BEAT_SR, max_seconds=max_seconds):
        buf = np.concatenate([buf, chunk.astype(np.float32) / 32768.0])
        if buf.size < BEAT_FRAME:
            continue
        n = (buf.size - BEAT_FRAME) // BEAT_HOP + 1
        frames = np.lib.stride_tricks.sliding_window_view(buf, BEAT_FRAME)[::BEAT_HOP][:n] * window
        mags = np.log1p(np.abs(np.fft.rfft(frames, axis=1)))
        stacked = mags if prev is None else np.vstack([prev, mags])
        diff = np.maximum(0.0, np.diff(stacked, axis=0)).sum(axis=1)
        if prev is None:
            diff = np.concatenate([[0.0], diff])
        flux.append(diff.astype(np.float32))
        prev = mags[-1:]
        buf = buf[n * BEAT_HOP:]
    return np.concatenate(flux) if flux else np.empty(0, dtype=np.float32)


def _pick_onsets(env: np.ndarray, fps: float, max_beats: int) -> list[int]:
    if env.size < 8 or float(env.max()) <= 1e-3:
        return []
    window = max(3, int(fps * 1.0) | 1)                       # about a second, odd
    kernel = np.ones(window, dtype=np.float32) / window
    local_mean = np.convolve(env, kernel, mode="same")
    threshold = np.maximum(local_mean * 1.35 + 0.08 * float(env.max()), 0.12 * float(env.max()))
    left, right = np.roll(env, 1), np.roll(env, -1)
    peak = (env > threshold) & (env >= left) & (env > right)
    peak[0] = peak[-1] = False
    candidates = np.nonzero(peak)[0]
    min_dist = max(2, int(round(0.25 * fps)))
    chosen: list[int] = []
    for i in sorted(candidates.tolist(), key=lambda i: -float(env[i])):
        if all(abs(i - j) >= min_dist for j in chosen):
            chosen.append(i)
            if len(chosen) >= max_beats:
                break
    return sorted(chosen)


def _estimate_bpm(env: np.ndarray, beats_s: list[float], fps: float) -> float | None:
    if env.size < int(fps * 4) or len(beats_s) < 4:
        return None
    x = env.astype(np.float64) - float(env.mean())
    zero_lag = float(np.dot(x, x))
    if zero_lag <= 1e-9:
        return None
    best_lag, best_score, best_ac = None, 0.0, 0.0
    for lag in range(max(2, int(fps * 60 / 200)), int(fps * 60 / 60) + 1):
        if lag >= x.size // 2:
            break
        ac = float(np.dot(x[:-lag], x[lag:])) / zero_lag
        bpm = 60.0 * fps / lag
        prior = math.exp(-0.5 * (math.log2(bpm / 120.0) / 0.7) ** 2)          # people tap near 120
        score = ac * prior
        if score > best_score:
            best_lag, best_score, best_ac = lag, score, ac
    if best_lag is None or best_ac < 0.12:
        return None
    period = best_lag / fps
    iois = np.diff(np.asarray(beats_s))
    near = iois[(iois > period * 0.75) & (iois < period * 1.25)]
    if near.size >= 3:
        period = float(np.median(near))
    bpm = 60.0 / period
    return round(bpm, 1) if 50.0 <= bpm <= 220.0 else None


def beats(path, *, max_beats: int = 400) -> dict:
    """{"beats": [seconds …], "bpm": float | None, "duration": s} — onsets of the music (CapCut-style beat sync)."""
    max_beats = max(1, min(2000, int(max_beats)))
    dest = cache_dir() / f"{_key(path, 'beats', mb=max_beats)}.beats.json"
    hit = _read_json(dest)
    if hit is not None:
        return hit
    with _lock_for(dest.name):
        hit = _read_json(dest)
        if hit is not None:
            return hit
        info = _info(path)
        if not info["has_audio"]:
            raise TimelineError("این فایل صدا ندارد.")
        env = _onset_envelope(path, BEAT_MAX_SECONDS)
        fps = BEAT_SR / BEAT_HOP
        idx = _pick_onsets(env, fps, max_beats)
        times = [round((i * BEAT_HOP + BEAT_FRAME / 2) / BEAT_SR, 3) for i in idx]
        result = {"beats": times, "bpm": _estimate_bpm(env, times, fps),
                  "duration": round(info["duration"] or env.size / fps, 3)}
        _write_atomic(dest, json.dumps(result).encode("utf-8"))
        _maybe_cleanup()
        return result


# ------------------------------------------------------------------ speech spans

_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def speech_spans(path, *, threshold_db: float = -35, min_gap: float = 0.35, min_len: float = 0.25) -> list[list[float]]:
    """[[start, end], …] where somebody is talking (or any sound above `threshold_db`): the gaps of ffmpeg's silencedetect
    inverted. A pause shorter than `min_gap` does not split a span; a span shorter than `min_len` is dropped."""
    threshold_db = max(-90.0, min(-5.0, float(threshold_db)))
    min_gap = max(0.05, float(min_gap))
    min_len = max(0.0, float(min_len))
    dest = cache_dir() / f"{_key(path, 'speech', t=threshold_db, g=min_gap, l=min_len)}.speech.json"
    hit = _read_json(dest)
    if hit is not None:
        return hit
    with _lock_for(dest.name):
        hit = _read_json(dest)
        if hit is not None:
            return hit
        from services.video.ffmpeg import FFMPEG

        info = _info(path)
        if not info["has_audio"]:
            raise TimelineError("این فایل صدا ندارد.")
        cmd = [FFMPEG, "-nostdin", "-hide_banner", "-v", "info", "-i", str(path), "-vn",
               "-af", f"silencedetect=noise={threshold_db:g}dB:d={min_gap:g}", "-f", "null", "-"]
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                                 timeout=CALL_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise TimelineError("تشخیصِ گفتار بیش از حد طول کشید.") from None
        if run.returncode != 0:
            raise TimelineError("تشخیصِ گفتار روی این فایل ممکن نشد.")
        duration = info["duration"]
        silences: list[tuple[float, float]] = []
        start = None
        for line in run.stderr.splitlines():
            m = _SIL_START.search(line)
            if m:
                start = max(0.0, float(m.group(1)))
                continue
            m = _SIL_END.search(line)
            if m and start is not None:
                silences.append((start, float(m.group(1))))
                start = None
        if start is not None:                                # silent until the end
            silences.append((start, duration))
        spans, cursor = [], 0.0
        for s, e in silences:
            if s - cursor >= min_len:
                spans.append([round(cursor, 2), round(s, 2)])
            cursor = max(cursor, e)
        if duration - cursor >= min_len:
            spans.append([round(cursor, 2), round(duration, 2)])
        _write_atomic(dest, json.dumps(spans).encode("utf-8"))
        _maybe_cleanup()
        return spans
