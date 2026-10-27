"""صدای یک بازه: بماند، بی‌صدا، آرام‌تر، صدای تازه (جای اصلی یا روی آن)، یا برشِ کاملِ بازه.

* **نمونه‌دقیق.** کلِ صدا یک بار به PCM ِ خام (float32، همان نرخ و همان تعدادِ کانال) روی دیسک باز می‌شود و
  با numpy.memmap فقط نمونه‌های همان بازه (و چند ده میلی‌ثانیهٔ لبه‌ها) دست می‌خورد — بی بار کردنِ کلِ صدا در
  حافظه، پس ویدیوی ۱۰ دقیقه‌ای هم روی این سرور جا می‌شود.
* **لبه‌ها.** هر تغییر در دو لبهٔ بازه با منحنیِ هم‌توان (cos/sin) محو می‌شود؛ پیش‌فرض ۸۰ میلی‌ثانیه و همیشه
  داخلِ بازه، پس صدای بیرونِ بازه دست نمی‌خورد. برش: دو طرفِ جای خالی با یک crossfade ِ کوتاهِ متقارن به هم
  می‌رسند تا «تق» نزند و طولِ صدا دقیقاً به اندازهٔ تصویرِ حذف‌شده کم شود.
* **همگامی.** تصویر copy می‌شود (بیت‌به‌بیت)؛ صدا با همان کدک/نرخ/کانال و بیت‌ریتی کمی بالاتر از اصل دوباره
  رمزگذاری و با همان شروعِ زمانی (start_time ِ جریانِ صدا) کنارِ تصویر می‌نشیند. وارسی: md5 ِ بسته‌های تصویر،
  طولِ صدا و شروعش.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import media
from .media import FFMPEG, FFPROBE, MediaError

DEFAULT_FADE_MS = 80
CUT_XFADE_MS = 30
OPS = ("keep", "mute", "volume", "replace", "cut")
#: کدکِ صدای خروجی ⇐ رمزگذارِ ffmpeg
ENCODERS = {"aac": "aac", "mp3": "libmp3lame", "opus": "libopus", "vorbis": "libvorbis", "flac": "flac",
            "ac3": "ac3", "eac3": "eac3"}


class AudioError(RuntimeError):
    pass


def stream_info(path) -> dict | None:
    """اولین جریانِ صدا: کدک، نرخ، کانال، بیت‌ریت، شروع و طول (نسبت به شروعِ فایل)."""
    import json

    out = media.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", "-select_streams",
                     "a:0", str(path)], timeout=120, nice=False).stdout
    data = json.loads(out or b"{}")
    streams = data.get("streams") or []
    if not streams:
        return None
    s = streams[0]
    fmt_start = float((data.get("format") or {}).get("start_time") or 0.0)
    return {
        "codec": s.get("codec_name") or "aac", "sample_rate": int(s.get("sample_rate") or 48000),
        "channels": int(s.get("channels") or 2), "bit_rate": int(s.get("bit_rate") or 0),
        "start": float(s.get("start_time") or fmt_start) - fmt_start,
        "duration": float(s.get("duration") or (data.get("format") or {}).get("duration") or 0.0),
        "layout": s.get("channel_layout") or "",
    }


def _raw_cmd_in(sr: int, ch: int, path) -> list:
    return ["-f", "f32le", "-ar", str(sr), "-ac", str(ch), "-i", str(path)]


def decode(path, raw_path, sr: int, ch: int, *, seek: float = 0.0, length: float | None = None) -> int:
    """صدا ⇐ PCM ِ خامِ float32 در raw_path؛ تعدادِ نمونه (بر کانال)."""
    cmd = [FFMPEG, "-v", "error", "-y"]
    if seek > 0:
        cmd += ["-ss", f"{seek:.6f}"]
    cmd += ["-i", str(path), "-map", "0:a:0", "-vn"]
    if length is not None:
        cmd += ["-t", f"{max(0.0, length):.6f}"]
    cmd += ["-ar", str(sr), "-ac", str(ch), "-f", "f32le", str(raw_path)]
    media.run(cmd, timeout=1800)
    return os.path.getsize(raw_path) // (4 * ch)


def fit_length(raw_path, n: int, ch: int, sr: int, duration: float) -> int:
    """بسته‌های AAC ِ آخر تا ۱۰۲۴ نمونه سکوتِ اضافه دارند که رمزگشا گاهی پس نمی‌گیرد؛ بی بریدنش صدای نتیجه
    چند میلی‌ثانیه از اصل بلندتر می‌شد. فقط همین دنبالهٔ کوچک بریده می‌شود (نه چیزِ بیشتر)."""
    want = int(round(duration * sr)) if duration > 0 else n
    if 0 < want < n and n - want <= 2048:
        os.truncate(raw_path, want * ch * 4)
        return want
    return n


def silence(raw_path, n: int, ch: int) -> None:
    with open(raw_path, "wb") as fh:
        fh.truncate(n * ch * 4)


def ramp(n: int) -> np.ndarray:
    """۰ ⇐ ۱ در n نمونه، نیم‌موجِ سینوسی (هم‌توان در کنارِ cos)."""
    if n <= 0:
        return np.zeros(0, np.float32)
    x = (np.arange(n, dtype=np.float64) + 0.5) / n
    return np.sin(x * math.pi / 2).astype(np.float32)


def _gain(n: int, fade: int, level: float) -> np.ndarray:
    """منحنیِ بلندیِ صدای اصلی در بازه: ۱ ⇐ level در fade نمونهٔ اول، level در وسط، level ⇐ ۱ در آخر (هم‌توان)."""
    g = np.full(n, level, np.float32)
    if fade:
        up = ramp(fade)                       # 0→1
        down = np.sqrt(np.clip(1 - up ** 2, 0, 1))  # 1→0 (cos)
        g[:fade] = level + (1 - level) * down
        g[n - fade:] = level + (1 - level) * up
    return g


def edit_samples(raw_path, n_total: int, ch: int, sr: int, s0: int, s1: int, spec: dict, clip_raw=None,
                 clip_n: int = 0) -> dict:
    """بازهٔ [s0, s1) ِ فایلِ خام را درجا تغییر می‌دهد (keep/mute/volume/replace). برمی‌گرداند گزارش."""
    op = spec.get("op", "keep")
    s0, s1 = max(0, s0), min(n_total, s1)
    n = s1 - s0
    if n <= 0 or op == "keep":
        return {"op": op, "samples": max(0, n)}
    fade = int(round(float(spec.get("fade_ms", DEFAULT_FADE_MS)) / 1000 * sr))
    fade = max(0, min(fade, n // 3))
    mm = np.memmap(raw_path, dtype=np.float32, mode="r+", shape=(n_total, ch))
    region = np.array(mm[s0:s1], dtype=np.float32)
    report = {"op": op, "samples": n, "fade_samples": fade}
    if op == "mute":
        out = region * _gain(n, fade, 0.0)[:, None]
    elif op == "volume":
        level = 10 ** (float(spec.get("gain_db", -12)) / 20)
        out = region * _gain(n, fade, level)[:, None]
        report["gain_db"] = float(spec.get("gain_db", -12))
    elif op == "replace":
        bed = 0.0 if spec.get("mix", "replace") == "replace" else 10 ** (float(spec.get("bed_db", -14)) / 20)
        new = np.zeros((n, ch), np.float32)
        if clip_raw is not None and clip_n > 0:
            clip = np.memmap(clip_raw, dtype=np.float32, mode="r", shape=(clip_n, ch))
            take = min(n, clip_n)
            new[:take] = clip[:take]
            report["clip_samples"] = int(clip_n)
            report["clip_shorter_by"] = round(max(0, n - clip_n) / sr, 3)
        new *= 10 ** (float(spec.get("clip_gain_db", 0)) / 20)
        g_new = np.ones(n, np.float32)
        if fade:
            g_new[:fade] = ramp(fade)
            g_new[n - fade:] = ramp(fade)[::-1]
        out = region * _gain(n, fade, bed)[:, None] + new * g_new[:, None]
        report["mix"] = spec.get("mix", "replace")
    else:
        raise AudioError(f"عملِ صدای ناشناخته: {op}")
    peak = float(np.abs(out).max()) if out.size else 0.0
    if peak > 1.0:          # محدودکنندهٔ نرم فقط روی همین بازه
        out = np.tanh(out)
    report["peak"] = round(peak, 3)
    mm[s0:s1] = out
    mm.flush()
    del mm
    return report


def cut_samples(raw_in, raw_out, n_total: int, ch: int, sr: int, s0: int, s1: int, xfade_ms: int = CUT_XFADE_MS) -> int:
    """[s0, s1) حذف؛ دو لبه با crossfade ِ متقارنِ کوتاه به هم می‌رسند. طولِ خروجی دقیقاً n_total-(s1-s0)."""
    s0, s1 = max(0, s0), min(n_total, s1)
    x = int(round(xfade_ms / 1000 * sr))
    half = min(x // 2, s0, n_total - s1, max(0, (s1 - s0) // 2))
    src = np.memmap(raw_in, dtype=np.float32, mode="r", shape=(n_total, ch))
    with open(raw_out, "wb") as out:
        step = 1 << 20
        for a in range(0, s0 - half, step):
            out.write(np.ascontiguousarray(src[a:min(a + step, s0 - half)]).tobytes())
        if half:
            fade_in = ramp(2 * half)[:, None]
            fade_out = np.sqrt(np.clip(1 - fade_in ** 2, 0, 1))
            joined = src[s0 - half:s0 + half] * fade_out + src[s1 - half:s1 + half] * fade_in
            out.write(np.ascontiguousarray(joined.astype(np.float32)).tobytes())
        for a in range(s1 + half, n_total, step):
            out.write(np.ascontiguousarray(src[a:min(a + step, n_total)]).tobytes())
    del src
    return n_total - (s1 - s0)


def _encoder(codec: str) -> str:
    enc = ENCODERS.get(codec, "aac")
    try:
        out = media.run([FFMPEG, "-hide_banner", "-encoders"], timeout=30, nice=False).stdout.decode()
    except MediaError:
        return "aac"
    return enc if f" {enc} " in out else "aac"


def mux(video_src, raw_path, out_path, a: dict, *, offset: float) -> None:
    """تصویرِ video_src (copy) + صدای خام (رمزگذاری با کدکِ اصل) ⇐ out_path. offset = شروعِ صدا در خطِ زمانِ فایل."""
    enc = _encoder(a["codec"])
    br = max(128000, int((a.get("bit_rate") or 160000) * 1.25))
    cmd = [FFMPEG, "-v", "error", "-y", "-i", str(video_src)]
    if abs(offset) > 1e-4:
        cmd += ["-itsoffset", f"{offset:.6f}"]
    cmd += _raw_cmd_in(a["sample_rate"], a["channels"], raw_path)
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", enc]
    if enc not in ("flac",):
        cmd += ["-b:a", str(min(br, 320000))]
    cmd += ["-ar", str(a["sample_rate"]), "-map_metadata", "0"]
    if str(out_path).endswith(".mp4"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out_path))
    media.run(cmd, timeout=3600)


def video_md5(path) -> str:
    try:
        return media.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"],
                         timeout=1800, nice=False).stdout.decode().strip()
    except MediaError:
        return ""


def range_seconds(info: dict, start: int, end: int) -> tuple[float, float]:
    """[t0, t1) ِ بازه در خطِ زمانِ فایل: از شروعِ فریمِ start تا پایانِ فریمِ end."""
    return media.frame_time(info, start), media.frame_time(info, end + 1)


def load_clip(spec: dict, clip_path, raw_path, sr: int, ch: int, length: float) -> int:
    offset = max(0.0, float(spec.get("offset", 0.0)))
    return decode(clip_path, raw_path, sr, ch, seek=offset, length=length)


def apply(base, info: dict, spec: dict, start: int, end: int, out_path, work: Path, *, clip_path=None) -> dict:
    """یک عملِ صدا روی بازهٔ [start, end] ِ ویدیوی base ⇐ out_path (تصویر copy). برای keep/mute/volume/replace."""
    work.mkdir(parents=True, exist_ok=True)
    op = spec.get("op", "keep")
    a = stream_info(base)
    t0, t1 = range_seconds(info, start, end)
    raw = work / "audio.f32"
    if a is None:
        if op != "replace":
            raise AudioError("این ویدیو صدا ندارد؛ فقط «صدای تازه» ممکن است.")
        a = {"codec": "aac", "sample_rate": 48000, "channels": 2, "bit_rate": 160000, "start": 0.0,
             "duration": info["duration"]}
        n_total = int(round(info["duration"] * a["sample_rate"]))
        silence(raw, n_total, 2)
        created = True
    else:
        n_total = decode(base, raw, a["sample_rate"], a["channels"])
        n_total = fit_length(raw, n_total, a["channels"], a["sample_rate"], a["duration"])
        created = False
    sr, ch = a["sample_rate"], a["channels"]
    s0 = int(round((t0 - a["start"]) * sr))
    s1 = int(round((t1 - a["start"]) * sr))
    clip_raw, clip_n = None, 0
    if op == "replace":
        if not clip_path:
            raise AudioError("فایلِ صدای تازه انتخاب نشده.")
        clip_raw = work / "clip.f32"
        clip_n = load_clip(spec, clip_path, clip_raw, sr, ch, (s1 - s0) / sr)
    report = edit_samples(raw, n_total, ch, sr, s0, s1, spec, clip_raw, clip_n)
    mux(base, raw, out_path, a, offset=a["start"])
    report.update({"t0": round(t0, 4), "t1": round(t1, 4), "sample_rate": sr, "channels": ch,
                   "created_track": created, "codec": a["codec"]})
    return report


def cut(video_only, base, info: dict, start: int, end: int, out_path, work: Path) -> dict:
    """صدای base بی بازهٔ [start, end] + تصویرِ video_only (که همین بازه از آن برداشته شده) ⇐ out_path."""
    work.mkdir(parents=True, exist_ok=True)
    a = stream_info(base)
    t0, t1 = range_seconds(info, start, end)
    if a is None:
        shutil.copyfile(video_only, out_path)
        return {"op": "cut", "audio": False, "t0": t0, "t1": t1}
    sr, ch = a["sample_rate"], a["channels"]
    raw = work / "audio.f32"
    n_total = fit_length(raw, decode(base, raw, sr, ch), ch, sr, a["duration"])
    s0 = int(round((t0 - a["start"]) * sr))
    s1 = int(round((t1 - a["start"]) * sr))
    raw_cut = work / "audio_cut.f32"
    n_out = cut_samples(raw, raw_cut, n_total, ch, sr, s0, s1)
    raw.unlink(missing_ok=True)
    offset = a["start"] if s0 > 0 else max(0.0, a["start"])
    mux(video_only, raw_cut, out_path, a, offset=offset)
    return {"op": "cut", "audio": True, "t0": round(t0, 4), "t1": round(t1, 4), "removed_samples": s1 - s0,
            "samples_out": n_out, "sample_rate": sr, "xfade_ms": CUT_XFADE_MS}


# ───────────────────────────── شکلِ موج برای پنل

def peaks(path, t_from: float, t_to: float, buckets: int = 800) -> list[float]:
    """بیشینهٔ دامنه در هر بازهٔ کوچک (۰…۱، با ریشهٔ دوم تا گفتارِ آرام هم دیده شود). صدا نداشت ⇐ []."""
    span = max(0.01, t_to - t_from)
    buckets = max(10, min(4000, int(buckets)))
    sr = 8000 if span > 20 else 16000
    with tempfile.TemporaryDirectory(prefix="nmregen-wave-") as d:
        raw = Path(d) / "w.f32"
        try:
            n = decode(path, raw, sr, 1, seek=max(0.0, t_from), length=span)
        except MediaError:
            return []
        if n == 0:
            return []
        x = np.abs(np.fromfile(raw, dtype=np.float32))
    # ffmpeg از ثانیهٔ seek به بعد می‌دهد؛ تا انتهای span پر می‌شود (اگر صدا کوتاه‌تر بود صفر)
    total = int(span * sr)
    if x.size < total:
        x = np.concatenate([x, np.zeros(total - x.size, np.float32)])
    edges = np.linspace(0, total, buckets + 1).astype(int)
    out = [float(x[a:b].max()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]
    top = max(out) or 1.0
    return [round(math.sqrt(v / top), 3) for v in out]


def level_db(path, t_from: float, t_to: float) -> float | None:
    """بلندیِ RMS (dBFS) ِ یک بازه — برای گزارشِ «قبل/بعد» در لبه‌ها."""
    with tempfile.TemporaryDirectory(prefix="nmregen-lvl-") as d:
        raw = Path(d) / "l.f32"
        try:
            n = decode(path, raw, 16000, 1, seek=max(0.0, t_from), length=max(0.005, t_to - t_from))
        except MediaError:
            return None
        if n == 0:
            return None
        x = np.fromfile(raw, dtype=np.float32)
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    return round(20 * math.log10(rms), 1) if rms > 1e-6 else -120.0


def probe_clip(path) -> float:
    """طولِ یک فایلِ صدا (ثانیه)؛ صفر = صدا ندارد."""
    try:
        out = media.run([FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(path)], timeout=60, nice=False).stdout.decode().strip()
        if stream_info(path) is None:
            return 0.0
        return float(out.split(",")[0] or 0)
    except (MediaError, ValueError, subprocess.TimeoutExpired):
        return 0.0
