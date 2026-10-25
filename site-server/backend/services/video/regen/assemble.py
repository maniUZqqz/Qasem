"""تکهٔ تازه در ویدیوی کامل: چسباندنِ هوشمند (بی‌رمزگذاریِ دوباره) یا رمزگذاریِ کامل با تنظیماتِ نزدیک به منبع.

**هوشمند** — منبعِ H.264 که با x264 و GOP ِ بسته ساخته شده (خروجی‌های خودِ سامانه: ویدیوی AI، ادیتور، رندرِ
سه‌بعدی). فقط از کلیدفریمِ قبل از تکه تا کلیدفریمِ بعد از آن دوباره رمزگذاری می‌شود — با **همان** تنظیماتِ x264
که در SEI ِ منبع نوشته شده — و SPS/PPS ِ تکه با منبع بایت‌به‌بایت مقایسه می‌شود. یکی بود ⇐ سه قطعه با copy
پشتِ هم: هر فریمِ بیرونِ آن چند ثانیه دقیقاً همان بیت‌های منبع است و ویدیوی ۱۰ دقیقه‌ای هم چند ثانیه کار دارد.
بعد وارسی: تعدادِ فریم، pts ِ تک‌تکِ فریم‌ها، رمزگشاییِ بی‌خطای محلِ اتصال‌ها، و نزدیکیِ فریم‌های مرزی به منبع؛
هر کدام نشد ⇐ راهِ کامل.

**کامل** — کلِ تصویر از نو (x264، یا x265 برای منبعِ HEVC)، CRF از بیت‌ریتِ منبع، همان pix_fmt، برچسب‌های رنگ و
timescale؛ زیرِ nice. هر دو راه صدا را **copy** می‌کنند (دست‌نخورده) و طول/تعدادِ فریم با منبع یکی است.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from fractions import Fraction
from pathlib import Path

import numpy as np

from . import media
from .media import FFMPEG, MediaError

logger = logging.getLogger(__name__)

#: صدای این کدک‌ها در mp4 جا می‌شود (copy)؛ بقیه ⇐ mkv
MP4_AUDIO = {"aac", "mp3", "alac", "ac3", "eac3", "opus", "flac", "mp2"}

#: نامِ گزینه در SEI ِ x264 ⇐ نامِ گزینه در -x264-params (فقط آن‌هایی که SPS/PPS یا کیفیت را تعیین می‌کنند)
_X264 = {
    "cabac": "cabac", "ref": "ref", "me": "me", "subme": "subme", "mixed_ref": "mixed-refs", "me_range": "merange",
    "chroma_me": "chroma-me", "trellis": "trellis", "8x8dct": "8x8dct", "fast_pskip": "fast-pskip", "nr": "nr",
    "decimate": "dct-decimate", "bluray_compat": "bluray-compat", "constrained_intra": "constrained-intra",
    "bframes": "bframes", "b_adapt": "b-adapt", "b_bias": "b-bias", "weightb": "weightb", "open_gop": "open-gop",
    "weightp": "weightp", "keyint": "keyint", "keyint_min": "min-keyint", "scenecut": "scenecut",
    "rc_lookahead": "rc-lookahead", "mbtree": "mbtree", "qcomp": "qcomp", "qpmin": "qpmin", "qpmax": "qpmax",
    "qpstep": "qpstep", "ip_ratio": "ipratio", "pb_ratio": "pbratio", "vbv_maxrate": "vbv-maxrate",
    "vbv_bufsize": "vbv-bufsize", "crf_max": "crf-max",
}


class AssembleError(RuntimeError):
    pass


_PROFILES = {"high": "high", "main": "main", "baseline": "baseline", "constrained baseline": "baseline",
             "high 10": "high10", "high 4:2:2": "high422", "high 4:4:4 predictive": "high444"}


def profile_args(info: dict) -> list:
    """profile و level ِ منبع برای libx264 (منبعی که سطح/پروفایلش را دستی گذاشته بود، وگرنه SPS فرق می‌کرد).
    از راهِ گزینه‌های خودِ ffmpeg، نه -x264-params (x264_param_parse «profile» را نمی‌شناسد)."""
    out = []
    prof = _PROFILES.get((info.get("profile") or "").lower())
    if prof:
        out += ["-profile:v", prof]
    lvl = int(info.get("level") or 0)
    if 9 < lvl < 100:
        out += ["-level", f"{lvl // 10}.{lvl % 10}"]
    return out


def x264_params(opts: dict, info: dict | None = None) -> str | None:
    """رشتهٔ -x264-params از روی SEI ِ منبع (None = نمی‌شود تکرارش کرد)."""
    if not opts:
        return None
    head: list = []
    if opts.get("interlaced", "0") != "0" or opts.get("sliced_threads", "0") != "0" or opts.get("intra_refresh", "0") != "0":
        return None
    parts = []
    for k, v in opts.items():
        name = _X264.get(k)
        if not name:
            continue
        if k == "keyint" and v == "infinite":
            v = "infinite"
        parts.append(f"{name}={v}")
    if "deblock" in opts:
        on, *ab = opts["deblock"].split(":")
        parts.append("no-deblock=1" if on == "0" else "deblock=" + ":".join(ab or ["0", "0"]))
    if "psy_rd" in opts:
        parts.append("psy-rd=" + opts["psy_rd"].replace(":", ","))
    if opts.get("psy") == "0":
        parts.append("psy=0")
    if "aq" in opts:
        mode, *st = opts["aq"].split(":")
        parts.append(f"aq-mode={mode}")
        if st:
            parts.append(f"aq-strength={st[0]}")
    if "b_pyramid" in opts:
        parts.append("b-pyramid=" + {"0": "none", "1": "strict", "2": "normal"}.get(opts["b_pyramid"], opts["b_pyramid"]))
    if "direct" in opts:
        parts.append("direct=" + {"0": "none", "1": "spatial", "2": "temporal", "3": "auto"}.get(opts["direct"], opts["direct"]))
    rc = opts.get("rc", "crf")
    if rc == "crf" and "crf" in opts:
        parts.append(f"crf={opts['crf']}")
    elif rc in ("abr", "2pass", "cbr") and "bitrate" in opts:
        parts.append(f"bitrate={opts['bitrate']}")
    elif rc == "cqp" and "qp" in opts:
        parts.append(f"qp={opts['qp']}")
    else:
        return None
    return ":".join(head + parts)


def _parameter_sets(path, *, seek: float | None = None) -> dict:
    cmd = [FFMPEG, "-v", "error"]
    if seek:
        cmd += ["-ss", f"{seek:.6f}"]
    cmd += ["-i", str(path), "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "h264_mp4toannexb", "-frames:v", "1",
            "-f", "h264", "-"]
    raw = media.run(cmd, timeout=120, nice=False).stdout
    out: dict[int, bytes] = {}
    for unit in raw.split(b"\x00\x00\x01"):
        unit = unit.rstrip(b"\x00")
        if unit and (unit[0] & 0x1F) in (7, 8):
            out.setdefault(unit[0] & 0x1F, unit)
    return out


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if mse < 1e-6 else float(10 * np.log10(255 ** 2 / mse))


def _filter(total: int, start: int, end: int, *, offset: float = 0.0) -> str:
    """[0:v] = ویدیوی پایه (فریم ۰…total-1)، [1:v] = تکه (start…end) ⇐ [v]."""
    parts, labels = [], []
    use_a, use_c = start > 0, end < total - 1
    n_split = int(use_a) + int(use_c)
    if n_split == 2:
        parts.append("[0:v]split=2[x0][x1]")
        src_a, src_c = "[x0]", "[x1]"
    else:
        src_a = src_c = "[0:v]"
    if use_a:
        parts.append(f"{src_a}trim=end_frame={start},setpts=PTS-STARTPTS[a]")
        labels.append("[a]")
    parts.append("[1:v]setpts=PTS-STARTPTS[p]")
    labels.append("[p]")
    if use_c:
        parts.append(f"{src_c}trim=start_frame={end + 1},setpts=PTS-STARTPTS[c]")
        labels.append("[c]")
    tail = f",setpts=PTS+{offset:.6f}/TB" if offset > 0.0005 else ""
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0{tail}[v]")
    return ";".join(parts)


def _crf_for(info: dict) -> int:
    bpp = info["bit_rate"] / max(1.0, info["width"] * info["height"] * info["fps"]) if info.get("bit_rate") else 0.08
    for limit, crf in ((0.20, 16), (0.12, 17), (0.07, 19), (0.04, 21), (0.02, 23)):
        if bpp >= limit:
            return crf
    return 24


def _encoder_args(info: dict, *, total_frames: int) -> list:
    codec = info.get("codec")
    xp = x264_params(info.get("x264") or {}, info)
    # روی این سرور (۲ هستهٔ پرمشغله) x264 ِ medium حدودِ ۴ فریم/ثانیه در ۷۲۰p است و veryfast حدودِ ۱۵؛
    # ویدیوی کوتاه با medium، بلندتر با سریع‌تر (کیفیت را CRF نگه می‌دارد، نه preset)
    mpf = total_frames * info["width"] * info["height"] / 1e6
    preset = "medium" if mpf < 300 else ("faster" if mpf < 1500 else "veryfast")
    pix = media.target_pix_fmt(info)
    if codec == "hevc" and _has_encoder("libx265"):
        args = ["-c:v", "libx265", "-preset", preset, "-crf", str(_crf_for(info) + 4), "-tag:v", "hvc1",
                "-x265-params", "log-level=error"]
    elif xp:
        args = ["-c:v", "libx264", "-preset", preset, *profile_args(info), "-x264-params", xp]
    else:
        args = ["-c:v", "libx264", "-preset", preset, "-crf", str(_crf_for(info))]
        if info.get("bit_rate"):
            args += ["-maxrate", str(int(info["bit_rate"] * 2)), "-bufsize", str(int(info["bit_rate"] * 4))]
    return args + ["-pix_fmt", pix] + media.color_tags(info, present_only=True)


_ENCODERS: dict[str, bool] = {}


def _has_encoder(name: str) -> bool:
    if name not in _ENCODERS:
        try:
            out = media.run([FFMPEG, "-hide_banner", "-encoders"], timeout=30, nice=False).stdout.decode()
            _ENCODERS[name] = f" {name} " in out
        except MediaError:
            _ENCODERS[name] = False
    return _ENCODERS[name]


def container_for(info: dict) -> str:
    return ".mp4" if all((a.get("codec") or "") in MP4_AUDIO for a in info.get("audio") or []) else ".mkv"


def smart_possible(info: dict) -> str:
    """خالی = ممکن؛ وگرنه دلیلِ نشدن (برای گزارش)."""
    if info.get("codec") != "h264":
        return "کدکِ منبع H.264 نیست"
    opts = info.get("x264") or {}
    if not opts:
        return "منبع با x264 ساخته نشده (تنظیماتش معلوم نیست)"
    if opts.get("open_gop", "0") != "0":
        return "GOP ِ باز"
    if x264_params(opts) is None:
        return "تنظیماتِ x264 ِ منبع تکرارپذیر نیست"
    if info.get("rotation"):
        return "ویدیوی چرخیده (rotation)"
    if info.get("vfr"):
        return "نرخِ فریمِ متغیر"
    if not info.get("timescale"):
        return "timebase ِ غیرعادی"
    if "mp4" not in (info.get("container") or "") and "mov" not in (info.get("container") or ""):
        return "ظرف mp4/mov نیست"
    if not info.get("keyframes"):
        return "کلیدفریم پیدا نشد"
    return ""


def _verify(out: Path, base: Path, info: dict, *, window: tuple[int, int] | None = None) -> dict:
    checks = {}
    n_out = media.count_frames(out)
    checks["frames"] = {"ok": n_out == info["n_frames"], "out": n_out, "source": info["n_frames"]}
    a0, a1 = media.audio_md5(base), media.audio_md5(out)
    checks["audio_untouched"] = {"ok": (a0 == a1) if info.get("audio") else True, "has_audio": bool(info.get("audio"))}
    out_info = media.probe(out)
    checks["duration"] = {"ok": abs(out_info["duration"] - info["duration"]) <= 1.5 / info["fps"],
                          "out": round(out_info["duration"], 4), "source": round(info["duration"], 4)}
    if window is not None:
        lo, hi = window
        t = max(0.0, media.frame_time(info, lo) - 0.01)
        p = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{t:.6f}", "-i", str(out), "-map", "0:v:0", "-frames:v",
                            str(hi - lo + 1), "-f", "null", "-"], capture_output=True, timeout=1800)
        err = p.stderr.decode("utf-8", "replace").strip()
        checks["decode"] = {"ok": p.returncode == 0 and not err, "error": err[-300:]}
    else:
        err = media.decode_check(out)
        checks["decode"] = {"ok": not err, "error": err[-300:]}
    return checks, out_info


def assemble(base, info: dict, piece, start: int, end: int, out_path, work: Path, *, prefer_smart: bool = True,
             on_progress=None) -> dict:
    """ویدیوی کامل با تکهٔ تازه در out_path. برمی‌گرداند {method, reencoded_frames, seconds, checks, …}."""
    base, piece, out_path = Path(base), Path(piece), Path(out_path)
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    n = info["n_frames"]
    why = smart_possible(info) if prefer_smart else "خاموش"
    if not why:
        try:
            res = _smart(base, info, piece, start, end, out_path, work, on_progress)
            if res.get("ok"):
                res["seconds"] = round(time.monotonic() - t0, 1)
                return res
            why = res.get("why") or "وارسی رد شد"
        except (MediaError, subprocess.TimeoutExpired, AssembleError) as exc:
            why = f"خطا: {str(exc)[:200]}"
        logger.info("regen: smart splice not used (%s) — full re-encode", why)
    res = _full(base, info, piece, start, end, out_path, on_progress)
    res["smart_skipped"] = why
    res["seconds"] = round(time.monotonic() - t0, 1)
    if not all(c.get("ok") for c in res["checks"].values()):
        bad = [k for k, c in res["checks"].items() if not c.get("ok")]
        raise AssembleError("ویدیوی نهایی وارسی را رد کرد: " + "، ".join(bad))
    return res


def _smart(base: Path, info: dict, piece: Path, start: int, end: int, out_path: Path, work: Path, on_progress) -> dict:
    n = info["n_frames"]
    keys = info["keyframes"]
    k1 = max(k for k in keys if k <= start)
    later = [k for k in keys if k > end]
    k2 = later[0] if later else n
    seg_dir = work / "seg"
    shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True)
    cuts = [c for c in (k1, k2) if 0 < c < n]
    names = []
    if cuts:
        media.run([FFMPEG, "-v", "error", "-y", "-i", base, "-map", "0:v:0", "-c", "copy", "-f", "segment",
                   "-segment_frames", ",".join(str(c) for c in cuts), "-reset_timestamps", "1",
                   "-segment_format", "mp4", str(seg_dir / "s%03d.mp4")], timeout=1800)
        names = sorted(seg_dir.glob("s*.mp4"))
    else:
        names = [base]
    expect = []
    if k1 > 0:
        expect.append(("before", k1))
    expect.append(("mid", k2 - k1))
    if k2 < n:
        expect.append(("after", n - k2))
    if len(names) != len(expect):
        return {"ok": False, "why": f"برش به {len(names)} قطعه شد؛ {len(expect)} لازم بود"}
    segs = {}
    for (role, count), path in zip(expect, names):
        got = media.count_frames(path)
        if got != count:
            return {"ok": False, "why": f"قطعهٔ {role}: {got} فریم به‌جای {count}"}
        segs[role] = path

    mid_out = work / "mid.mp4"
    xp = x264_params(info["x264"], info)
    fps = media.fps_of(info)
    local_start, local_end = start - k1, end - k1
    cmd = [FFMPEG, "-v", "error", "-y", "-i", segs["mid"], "-i", piece,
           "-filter_complex", _filter(k2 - k1, local_start, local_end), "-map", "[v]", "-an",
           "-c:v", "libx264", *profile_args(info), "-x264-params", xp, "-pix_fmt", media.target_pix_fmt(info),
           *media.color_tags(info, present_only=True), "-r", f"{fps.numerator}/{fps.denominator}",
           "-video_track_timescale", str(info["timescale"]), str(mid_out)]
    media.run_with_progress(cmd, total_frames=k2 - k1, on_progress=on_progress)
    if media.count_frames(mid_out) != k2 - k1:
        return {"ok": False, "why": "تعدادِ فریمِ قطعهٔ میانی جور نیست"}
    ps_src = _parameter_sets(segs["mid"])
    ps_new = _parameter_sets(mid_out)
    if not ps_src or ps_src != ps_new:
        return {"ok": False, "why": "SPS/PPS ِ قطعهٔ تازه با منبع یکی نشد"}

    lst = work / "list.txt"
    order = [segs.get("before"), mid_out, segs.get("after")]
    lst.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in order if p), "utf-8")
    vonly = work / "vonly.mp4"
    media.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v", "-c", "copy",
               vonly], timeout=1800)
    media.run([FFMPEG, "-v", "error", "-y", "-i", vonly, "-i", base, "-map", "0:v", "-map", "1:a?", "-c", "copy",
               "-map_metadata", "1", "-movflags", "+faststart", out_path], timeout=1800)

    lo = max([k for k in info["keyframes"] if k < k1] or [0])
    hi = min(n - 1, k2 + 30)
    checks, out_info = _verify(out_path, base, info, window=(lo, hi))
    # زمانِ تک‌تکِ فریم‌ها همان منبع: concat گاهی چند tick (زیرِ یک میلی‌ثانیه) جابه‌جا می‌کند — بی‌اثر؛
    # بیش از ۵٪ ِ یک فریم یعنی ترتیب/طول خراب شده
    out_pts = media.stream_pts(out_path)
    tb = float(Fraction(info["time_base"]))
    tol = max(1.0, 0.05 / info["fps"] / tb)
    dev = max((abs(a - b) for a, b in zip(out_pts, info["frame_pts"])), default=0) if len(out_pts) == len(
        info["frame_pts"]) else float("inf")
    checks["timestamps"] = {"ok": dev <= tol, "max_ms": round(dev * tb * 1000, 3) if dev != float("inf") else None}
    # همان فریم‌ها سرِ جایشان؟ فریمِ اول و آخرِ قطعهٔ بازسازی‌شده (اگر جزءِ تکه نیستند) باید تقریباً همان منبع باشند
    probes = [i for i in (k1, k2 - 1) if not (start <= i <= end)]
    psnr = {}
    for i in probes:
        psnr[str(i)] = round(_psnr(media.read_frame(out_path, info, i), media.read_frame(base, info, i)), 1)
    checks["alignment"] = {"ok": all(v >= 30 for v in psnr.values()), "psnr": psnr}
    ok = all(c.get("ok") for c in checks.values())
    for p in seg_dir.glob("*"):
        p.unlink(missing_ok=True)
    return {"ok": ok, "why": "" if ok else "وارسی: " + "، ".join(k for k, c in checks.items() if not c.get("ok")),
            "method": "smart", "reencoded_frames": k2 - k1, "range": [k1, k2 - 1], "checks": checks,
            "x264_params": xp}


def _full(base: Path, info: dict, piece: Path, start: int, end: int, out_path: Path, on_progress) -> dict:
    n = info["n_frames"]
    fps = media.fps_of(info)
    offset = max(0.0, info["video_start"] - info["format_start"])
    cmd = [FFMPEG, "-v", "error", "-y", "-i", base, "-i", piece, "-filter_complex", _filter(n, start, end, offset=offset),
           "-map", "[v]", "-map", "0:a?", "-c:a", "copy", *_encoder_args(info, total_frames=n),
           "-r", f"{fps.numerator}/{fps.denominator}", "-map_metadata", "0"]
    if out_path.suffix == ".mp4":
        cmd += ["-movflags", "+faststart"]
        if info.get("timescale"):
            cmd += ["-video_track_timescale", str(info["timescale"])]
    cmd.append(out_path)
    media.run_with_progress(cmd, total_frames=n, on_progress=on_progress)
    checks, _ = _verify(out_path, base, info)
    return {"ok": True, "method": "full", "reencoded_frames": n, "range": [0, n - 1], "checks": checks}
