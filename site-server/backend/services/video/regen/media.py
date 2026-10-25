"""ffprobe/ffmpeg برای بازسازیِ تکه: شمارهٔ فریمِ دقیق، ماتریسِ رنگِ صریح، خواندن/نوشتنِ فریمِ خام.

همه‌چیز بر پایهٔ **شمارهٔ فریم** است، نه ثانیه: زمانِ فریمِ i همان pts ِ i-امین بستهٔ ویدیو (به ترتیبِ نمایش)
است. خواندنِ فریمِ i با seek ِ دقیقِ ffmpeg به نیم‌فریم قبل از آن انجام می‌شود؛ اولین فریمِ خروجی همان i است
(برای CFR و VFR). بستهٔ آزمون این را با ویدیویی که شمارهٔ فریم در روشناییِ پیکسل‌هایش نوشته شده می‌سنجد.
"""
from __future__ import annotations

import bisect
import io
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np

from services.video.ffmpeg import FFMPEG, FFPROBE

logger = logging.getLogger(__name__)

#: کارهای ffmpeg روی سرورِ کوچک با اولویتِ پایین اجرا می‌شوند (همان دو هسته به سایت هم سرویس می‌دهد)
NICE = int(os.environ.get("NM_REGEN_NICE", "10"))

#: نامِ ماتریسِ رنگ در ffprobe ⇐ نامِ آن در فیلترِ scale
_MATRIX = {
    "bt709": "bt709", "bt470bg": "bt601", "smpte170m": "bt601", "bt2020nc": "bt2020", "bt2020c": "bt2020",
    "fcc": "fcc", "smpte240m": "smpte240m",
}
#: رمزگذارِ x264 این قالب‌های پیکسل را می‌پذیرد؛ بقیه ⇐ yuv420p
X264_PIX = {"yuv420p", "yuvj420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le", "yuv444p10le", "nv12"}


class MediaError(RuntimeError):
    pass


def _preexec():  # pragma: no cover — در فرزند، بینِ fork و exec
    try:
        os.nice(NICE)
    except OSError:
        pass


def _tail(err: bytes | str, n: int = 900) -> str:
    text = err.decode("utf-8", "replace") if isinstance(err, bytes) else (err or "")
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(lines[-8:])[-n:]


def run(cmd: list, *, timeout: float = 3600, input: bytes | None = None, nice: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout, input=input,
                       preexec_fn=_preexec if (nice and os.name == "posix") else None)
    if p.returncode != 0:
        raise MediaError(f"{Path(str(cmd[0])).name} ناموفق بود: {_tail(p.stderr)}")
    return p


# ───────────────────────────── probe

def _frac(text, default=None):
    try:
        f = Fraction(str(text))
        return f if f > 0 else default
    except (ValueError, ZeroDivisionError, TypeError):
        return default


def _rotation(stream: dict) -> int:
    rot = 0
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    tag = (stream.get("tags") or {}).get("rotate")
    if tag not in (None, ""):
        try:
            rot = int(float(tag))
        except ValueError:
            pass
    return rot % 360


def x264_options(path) -> dict:
    """تنظیماتِ x264 که در SEI ِ اولین فریم نوشته شده (رشتهٔ «x264 - core … options: …»)."""
    try:
        raw = run([FFMPEG, "-v", "error", "-i", path, "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "h264_mp4toannexb",
                   "-frames:v", "1", "-f", "h264", "-"], timeout=120, nice=False).stdout
    except (MediaError, subprocess.TimeoutExpired):
        return {}
    m = re.search(rb"x264 - core (\d+)[^\x00]*? - options: ([^\x00\x80]+)", raw)
    if not m:
        return {}
    opts = {}
    for kv in m.group(2).decode("latin-1").split():
        if "=" in kv:
            k, v = kv.split("=", 1)
            opts[k] = v
    opts["_core"] = m.group(1).decode()
    return opts


def probe(path) -> dict:
    """همهٔ چیزی که بقیهٔ کار لازم دارد. `frame_pts` و `keyframes` بزرگ‌اند و جدا نگه داشته می‌شوند."""
    path = str(path)
    data = json.loads(run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                          timeout=120, nice=False).stdout or b"{}")
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    if v is None:
        raise MediaError("این فایل تصویرِ ویدیویی ندارد.")
    fmt = data.get("format") or {}
    tb = _frac(v.get("time_base"), Fraction(1, 90000))
    r_rate = _frac(v.get("r_frame_rate"))
    avg_rate = _frac(v.get("avg_frame_rate"))
    fps = r_rate if (r_rate and r_rate <= 240) else avg_rate
    if not fps:
        raise MediaError("نرخِ فریمِ ویدیو معلوم نیست.")

    # pts ِ همهٔ بسته‌های ویدیو، بی‌رمزگشایی (برای ۱۰ دقیقه هم چند ثانیه)
    pk = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts,dts,flags", "-of", "csv=p=0",
              path], timeout=600, nice=False).stdout.decode("utf-8", "replace")
    pts, keys, n_dts_only = [], [], 0
    for line in pk.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        p_raw, d_raw, flags = parts[0], parts[1], parts[2]
        val = p_raw if p_raw not in ("", "N/A") else d_raw
        if val in ("", "N/A"):
            n_dts_only += 1
            continue
        pts.append(int(val))
        if "K" in flags:
            keys.append(int(val))
    if not pts:
        raise MediaError("فریمی در ویدیو پیدا نشد.")
    pts.sort()
    keyframes = sorted({bisect.bisect_left(pts, k) for k in keys})
    n = len(pts)

    nominal = float(1 / fps / tb)
    deltas = np.diff(np.asarray(pts, dtype=np.float64)) if n > 1 else np.zeros(0)
    off = int(np.sum(np.abs(deltas - nominal) > 0.5 * nominal)) if deltas.size else 0
    vfr = bool(deltas.size and off > max(2, 0.01 * deltas.size))

    rotation = _rotation(v)
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if rotation in (90, 270):
        w, h = h, w
    pix = v.get("pix_fmt") or "yuv420p"
    space = (v.get("color_space") or "").lower()
    matrix = _MATRIX.get(space) or ("bt709" if max(w, h) >= 1000 or h >= 720 else "bt601")
    full_range = (v.get("color_range") == "pc") or pix.startswith("yuvj")
    fmt_start = float(fmt.get("start_time") or 0.0)
    v_start = float(v.get("start_time") or fmt_start)
    duration = float(fmt.get("duration") or v.get("duration") or 0.0)
    size = int(fmt.get("size") or os.path.getsize(path))
    bit_rate = int(v.get("bit_rate") or 0)
    audio = [{"index": s.get("index"), "codec": s.get("codec_name"), "channels": s.get("channels"),
              "sample_rate": s.get("sample_rate"), "bit_rate": s.get("bit_rate")}
             for s in streams if s.get("codec_type") == "audio"]
    if not bit_rate and duration > 0:
        audio_bps = sum(int(a.get("bit_rate") or 128000) for a in audio)
        bit_rate = max(0, int(size * 8 / duration) - audio_bps)
    codec = v.get("codec_name") or ""
    info = {
        "path_size": size,
        "container": fmt.get("format_name") or "",
        "codec": codec,
        "profile": v.get("profile") or "",
        "level": int(v.get("level") or 0) if str(v.get("level") or "").lstrip("-").isdigit() else 0,
        "pix_fmt": pix,
        "width": w, "height": h,
        "coded_width": int(v.get("width") or 0), "coded_height": int(v.get("height") or 0),
        "sar": v.get("sample_aspect_ratio") or "1:1",
        "rotation": rotation,
        "fps_num": fps.numerator, "fps_den": fps.denominator, "fps": float(fps),
        "avg_fps": float(avg_rate) if avg_rate else float(fps),
        "time_base": f"{tb.numerator}/{tb.denominator}",
        "timescale": tb.denominator if tb.numerator == 1 else 0,
        "n_frames": n,
        "duration": duration,
        "format_start": fmt_start,
        "video_start": v_start,
        "vfr": vfr,
        "bit_rate": bit_rate,
        "color_range": "pc" if full_range else "tv",
        "color_space": space, "color_transfer": v.get("color_transfer") or "",
        "color_primaries": v.get("color_primaries") or "",
        # فقط برچسب‌هایی که واقعاً در منبع نوشته شده (برای تکرارِ بایت‌به‌بایتِ VUI در چسباندنِ هوشمند)
        "raw_color": {k: v.get(f) for k, f in (("range", "color_range"), ("space", "color_space"),
                                                ("trc", "color_transfer"), ("primaries", "color_primaries"))
                      if v.get(f) and v.get(f) != "unknown"},
        "matrix": matrix,
        "hdr": (v.get("color_transfer") or "") in ("smpte2084", "arib-std-b67"),
        "field_order": v.get("field_order") or "",
        "has_b_frames": int(v.get("has_b_frames") or 0),
        "audio": audio,
        "x264": x264_options(path) if codec == "h264" else {},
        "frame_pts": pts,
        "keyframes": keyframes,
    }
    return info


def summary(info: dict) -> dict:
    """همان probe بی فهرست‌های بزرگ (برای دیتابیس و پنل)."""
    return {k: v for k, v in info.items() if k not in ("frame_pts", "keyframes")}


def save_index(info: dict, path) -> None:
    Path(path).write_text(json.dumps({"frame_pts": info["frame_pts"], "keyframes": info["keyframes"]}), "utf-8")


def load_index(info: dict, path) -> dict:
    data = json.loads(Path(path).read_text("utf-8"))
    out = dict(info)
    out["frame_pts"], out["keyframes"] = data["frame_pts"], data["keyframes"]
    return out


# ───────────────────────────── زمان ⇐ شمارهٔ فریم

def fps_of(info: dict) -> Fraction:
    return Fraction(info["fps_num"], info["fps_den"])


def frame_time(info: dict, i: int) -> float:
    """زمانِ فریمِ i در خطِ زمانیِ فایل (ثانیه از شروعِ فایل؛ همان چیزی که -ss می‌فهمد).
    فریم‌های «مجازی» (-1 و n) یک فریم قبل/بعد از دو سرِ ویدیو‌اند."""
    pts = info.get("frame_pts")
    tb = Fraction(info["time_base"])
    step = 1 / float(fps_of(info))
    n = info["n_frames"]
    if pts:
        if i < 0:
            return float(pts[0] * tb) - info["format_start"] + i * step
        if i >= n:
            return float(pts[-1] * tb) - info["format_start"] + (i - n + 1) * step
        return float(pts[i] * tb) - info["format_start"]
    return info["video_start"] - info["format_start"] + i * step


def index_at(info: dict, t: float) -> int:
    """نزدیک‌ترین فریم به ثانیهٔ t (از شروعِ فایل)."""
    pts = info.get("frame_pts")
    n = info["n_frames"]
    if not pts:
        return max(0, min(n - 1, int(round((t - (info["video_start"] - info["format_start"])) * info["fps"]))))
    tb = Fraction(info["time_base"])
    target = (t + info["format_start"]) / float(tb)
    j = bisect.bisect_left(pts, target)
    cands = [k for k in (j - 1, j) if 0 <= k < n]
    return min(cands, key=lambda k: abs(pts[k] - target)) if cands else 0


def _seek_args(info: dict, i: int) -> list:
    if i <= 0:
        return []
    t = frame_time(info, i) - 0.5 / info["fps"]
    return ["-ss", f"{max(0.0, t):.6f}"] if t > 0 else []


def scale_filter(info: dict, width: int | None = None, height: int | None = None, *, to_rgb: bool = True) -> str:
    """تبدیلِ YUV⇄RGB با ماتریس و بازهٔ صریحِ همین ویدیو — رفت و برگشت همان ماتریس ⇐ رنگ جابه‌جا نمی‌شود."""
    size = f"w={width}:h={height}:" if width and height else ""
    flags = "flags=lanczos+accurate_rnd+full_chroma_int"
    if to_rgb:
        return f"scale={size}{flags}:in_color_matrix={info['matrix']}:in_range={info['color_range']},format=rgb24"
    return f"scale={size}{flags}:out_color_matrix={info['matrix']}:out_range={info['color_range']}"


def read_frames(path, info: dict, first: int, count: int, *, width: int | None = None, height: int | None = None) -> list:
    """فریم‌های first … first+count-1 به صورتِ آرایهٔ RGB (uint8، H×W×3)، با شمارهٔ دقیق."""
    if count <= 0:
        return []
    first = max(0, first)
    count = min(count, info["n_frames"] - first)
    W = width or info["width"]
    H = height or info["height"]
    cmd = [FFMPEG, "-v", "error", *_seek_args(info, first), "-i", str(path), "-map", "0:v:0", "-frames:v", str(count),
           "-vf", scale_filter(info, W, H), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = run(cmd, timeout=600).stdout
    size = W * H * 3
    frames = [np.frombuffer(raw[k * size:(k + 1) * size], dtype=np.uint8).reshape(H, W, 3)
              for k in range(len(raw) // size)]
    if len(frames) < count:
        raise MediaError(f"فقط {len(frames)} فریم از {count} فریمِ خواسته‌شده خوانده شد (از فریمِ {first}).")
    return frames


def read_frame(path, info: dict, i: int, **kw) -> np.ndarray:
    return read_frames(path, info, i, 1, **kw)[0]


def jpeg(frame: np.ndarray, *, width: int | None = None, quality: int = 85) -> bytes:
    from PIL import Image

    img = Image.fromarray(frame)
    if width and img.width > width:
        img = img.resize((width, max(2, round(img.height * width / img.width))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def png(frame: np.ndarray, path) -> None:
    from PIL import Image

    Image.fromarray(frame).save(str(path), "PNG", compress_level=3)


def load_png(path) -> np.ndarray:
    from PIL import Image

    with Image.open(str(path)) as im:
        return np.asarray(im.convert("RGB")).copy()


def filmstrip(path, info: dict, *, count: int = 24, height: int = 64) -> tuple[bytes, list]:
    """نوارِ کوچک‌نمایی برای خطِ زمانیِ پنل: یک JPEG ِ افقی + شمارهٔ فریمِ هر خانه (seek ِ سریع روی کلیدفریم)."""
    from PIL import Image

    n = info["n_frames"]
    count = max(1, min(count, n))
    width = max(2, int(round(height * info["width"] / info["height"] / 2)) * 2)
    tiles, idx = [], []
    for k in range(count):
        i = int(round((k + 0.5) * n / count)) if count > 1 else 0
        i = min(n - 1, max(0, i))
        t = max(0.0, frame_time(info, i))
        cmd = [FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-noaccurate_seek", "-i", str(path), "-map", "0:v:0",
               "-frames:v", "1", "-vf", scale_filter(info, width, height), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        try:
            raw = run(cmd, timeout=60).stdout[:width * height * 3]
        except (MediaError, subprocess.TimeoutExpired):
            raw = b""
        if len(raw) == width * height * 3:
            tiles.append(np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3))
        else:
            tiles.append(np.zeros((height, width, 3), dtype=np.uint8))
        idx.append(i)
    sprite = np.concatenate(tiles, axis=1)
    buf = io.BytesIO()
    Image.fromarray(sprite).save(buf, "JPEG", quality=70)
    return buf.getvalue(), idx


# ───────────────────────────── نوشتنِ فریم‌ها

def target_pix_fmt(info: dict) -> str:
    pix = info.get("pix_fmt") or "yuv420p"
    if pix == "yuvj420p":
        return "yuvj420p"
    return pix if pix in X264_PIX else "yuv420p"


def color_tags(info: dict, *, present_only: bool = True) -> list:
    """برچسب‌های رنگِ خروجی. present_only: فقط همان‌هایی که منبع داشت (برچسبِ اضافه SPS را عوض می‌کند و
    در ffmpeg ≥ 7 فیلترِ concat را به تبدیلِ رنگِ ناخواسته وامی‌دارد)."""
    raw = info.get("raw_color") or {} if present_only else {
        "range": info.get("color_range"), "space": info.get("color_space"), "trc": info.get("color_transfer"),
        "primaries": info.get("color_primaries")}
    tags = []
    for key, opt in (("range", "-color_range"), ("space", "-colorspace"), ("trc", "-color_trc"),
                     ("primaries", "-color_primaries")):
        if raw.get(key):
            tags += [opt, raw[key]]
    return tags


class RawWriter:
    """فریم‌های RGB را به ffmpeg می‌دهد و فایلِ میانی می‌سازد (x264 با CRF ِ خیلی پایین: عملاً بی‌اتلاف).

    stderr به فایل می‌رود، نه pipe — وگرنه وقتی ffmpeg زیاد بنویسد هر دو طرف منتظرِ هم می‌مانند."""

    def __init__(self, out_path, info: dict, *, crf: int = 4, preset: str = "veryfast"):
        self.info = info
        self.W, self.H = info["width"], info["height"]
        self.count = 0
        self.err = tempfile.TemporaryFile()
        fps = fps_of(info)
        sar = (info.get("sar") or "1:1").replace(":", "/")
        raw = info.get("raw_color") or {}
        # برچسب‌های رنگِ فریم‌ها همان منبع (یا «نامعلوم» اگر منبع نداشت)؛ وگرنه concat در ffmpeg ≥ ۷ تبدیل می‌گذارد
        params = (f"setparams=range={raw.get('range', 'unknown')}:color_primaries={raw.get('primaries', 'unknown')}"
                  f":color_trc={raw.get('trc', 'unknown')}:colorspace={raw.get('space', 'unknown')}")
        cmd = [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{self.W}x{self.H}",
               "-framerate", f"{fps.numerator}/{fps.denominator}", "-i", "-",
               "-vf", scale_filter(info, to_rgb=False) + f",format={target_pix_fmt(info)},{params},"
               f"setsar={sar if sar not in ('0/1', 'N/A') else '1'}",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-x264-params", "keyint=1000:scenecut=0",
               *color_tags(info), str(out_path)]
        self.proc = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=self.err, preexec_fn=_preexec if os.name == "posix" else None)

    def write(self, frame: np.ndarray) -> None:
        if frame.shape != (self.H, self.W, 3) or frame.dtype != np.uint8:
            raise MediaError(f"اندازهٔ فریم {frame.shape} با ویدیو ({self.H}×{self.W}) نمی‌خواند.")
        try:
            self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        except BrokenPipeError:
            self.close()
            raise
        self.count += 1

    def close(self) -> None:
        if self.proc.stdin and not self.proc.stdin.closed:
            try:
                self.proc.stdin.close()
            except BrokenPipeError:
                pass
        code = self.proc.wait(timeout=3600)
        if code != 0:
            self.err.seek(0)
            raise MediaError("نوشتنِ تکهٔ میانی ناموفق بود: " + _tail(self.err.read()))
        self.err.close()


def count_frames(path) -> int:
    out = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
               "stream=nb_read_packets", "-of", "csv=p=0", str(path)], timeout=600, nice=False).stdout
    try:
        return int(out.decode().strip().split(",")[0])
    except ValueError:
        return 0


def decode_check(path, timeout: float = 1800) -> str:
    """کلِ ویدیو را بی‌خروجی رمزگشایی می‌کند؛ متنِ خطاها (خالی = سالم)."""
    p = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
                       capture_output=True, timeout=timeout, preexec_fn=_preexec if os.name == "posix" else None)
    return _tail(p.stderr) if (p.returncode != 0 or p.stderr.strip()) else ""


def audio_md5(path) -> str:
    """اثرِ انگشتِ بسته‌های صدا (بی‌رمزگشایی) — برای سنجیدنِ «صدای اصلی دست نخورد»."""
    try:
        out = run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"],
                  timeout=600, nice=False).stdout
        return out.decode().strip()
    except MediaError:
        return ""


def stream_pts(path, stream: str = "v:0") -> list:
    out = run([FFPROBE, "-v", "error", "-select_streams", stream, "-show_entries", "packet=pts", "-of", "csv=p=0",
               str(path)], timeout=600, nice=False).stdout.decode()
    vals = [int(x.split(",")[0]) for x in out.split() if x.split(",")[0].lstrip("-").isdigit()]
    return sorted(vals)


def encode_window(src, info: dict, out_path, first: int, last: int, *, max_height: int = 720, crf: int = 23,
                  audio: bool = True) -> None:
    """فریم‌های first … last (شامل) به یک mp4 ِ سبک برای پیش‌نمایش در مرورگر (با صدای همان بازه)."""
    first = max(0, first)
    last = min(info["n_frames"] - 1, last)
    count = last - first + 1
    t0 = frame_time(info, first)
    dur = count / info["fps"]
    h = min(max_height, info["height"])
    h -= h % 2
    w = max(2, int(round(info["width"] * h / info["height"] / 2)) * 2)
    cmd = [FFMPEG, "-v", "error", "-y", *_seek_args(info, first), "-i", str(src), "-map", "0:v:0"]
    if audio and info.get("audio"):
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k", "-t", f"{dur:.6f}"]
    cmd += ["-frames:v", str(count), "-vf", f"scale={w}:{h}:flags=lanczos,format=yuv420p", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", str(crf), "-movflags", "+faststart", str(out_path)]
    run(cmd, timeout=1800)


def run_with_progress(cmd: list, *, total_frames: int, on_progress=None, timeout: float = 7200) -> None:
    """ffmpeg با `-progress pipe:1`؛ هر چند ثانیه پیشرفت (۰…۱) گزارش می‌شود."""
    err = tempfile.TemporaryFile()
    proc = subprocess.Popen([str(c) for c in cmd[:1]] + ["-progress", "pipe:1", "-nostats"] + [str(c) for c in cmd[1:]],
                            stdout=subprocess.PIPE, stderr=err, preexec_fn=_preexec if os.name == "posix" else None)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:
            if on_progress and line.startswith(b"frame=") and total_frames:
                try:
                    on_progress(min(1.0, int(line.split(b"=")[1]) / total_frames))
                except ValueError:
                    pass
        code = proc.wait()
    finally:
        timer.cancel()
    if code != 0:
        err.seek(0)
        raise MediaError("ffmpeg ناموفق بود: " + _tail(err.read()))
    err.close()
