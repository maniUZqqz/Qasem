"""آزمونِ واقعیِ صدای بازه و برش با ffmpeg: `python -m services.video.regen.selftest_audio [--keep]`.

کلیپِ آزمایشی: تصویرِ متحرک با «فلش»‌های سفید در فریم‌های معلوم + صدای گفتارمانند (هارمونیک‌های ۱۸۰ هرتز با
هجاهای ۴ هرتزی) و بوق‌های بلندِ ۱ کیلوهرتزی هم‌زمان با همان فلش‌ها. هر عمل اجرا و سنجیده می‌شود: طول و
تعدادِ فریم، دست‌نخوردنِ تصویر، جای بوق‌ها نسبت به فلش‌ها (همگامیِ صدا و تصویر)، بلندیِ داخلِ بازه، نرمیِ لبه‌ها.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import assemble, audio, media
from .media import FFMPEG

FPS = 30
FLASHES = [30, 90, 150, 210, 270]           # فریم‌ها (۱، ۳، ۵، ۷، ۹ ثانیه)


def make_clip(path: Path, seconds: float = 10.0, sei: bool = True) -> None:
    flash = "+".join(f"eq(n\\,{f})" for f in FLASHES)
    speech = ("0.22*(0.5+0.5*sin(2*PI*4*t))*(sin(2*PI*180*t)+0.5*sin(2*PI*360*t)+0.3*sin(2*PI*540*t))/1.8")
    beep = "+".join(f"0.85*sin(2*PI*1000*t)*between(t\\,{f / FPS:.4f}\\,{f / FPS + 0.1:.4f})" for f in FLASHES)
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate={FPS}:duration={seconds}",
           "-f", "lavfi", "-i", f"aevalsrc=exprs='{speech}+{beep}|{speech}+{beep}':s=48000:d={seconds}",
           "-vf", f"drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='{flash}',format=yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", "60", "-bf", "3",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    if not sei:
        cmd += ["-bsf:v", "filter_units=remove_types=6"]
    media.run(cmd + [str(path)], timeout=300)


def make_tone(path: Path, freq: float = 2000.0, seconds: float = 3.0) -> None:
    media.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
               f"sine=frequency={freq}:sample_rate=44100:duration={seconds}", "-c:a", "libmp3lame", "-b:a", "128k",
               str(path)], timeout=120)


def pcm(path: Path, sr: int = 48000) -> np.ndarray:
    raw = Path(tempfile.mktemp(suffix=".f32"))
    audio.decode(path, raw, sr, 1)
    x = np.fromfile(raw, dtype=np.float32)
    raw.unlink(missing_ok=True)
    return x


def beeps(x: np.ndarray, sr: int = 48000) -> list[float]:
    """زمانِ شروعِ بوق‌ها (ثانیه): جایی که دامنه از ۰٫۶ می‌گذرد (گفتار زیرِ ۰٫۴ است)."""
    loud = np.abs(x) > 0.6
    out, last = [], -1.0
    for i in np.flatnonzero(loud):
        t = i / sr
        if t - last > 0.5:
            out.append(round(t, 4))
        last = t
    return out


def flashes(path: Path, info: dict) -> list[int]:
    frames = media.read_frames(path, info, 0, info["n_frames"], width=64, height=36)
    return [i for i, f in enumerate(frames) if f.mean() > 200]


def rms_db(x: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if x.size else 0.0
    return round(20 * math.log10(r), 1) if r > 1e-7 else -120.0


def max_step(x: np.ndarray, at: float, sr: int = 48000, win: float = 0.03) -> float:
    a, b = max(1, int((at - win) * sr)), min(x.size, int((at + win) * sr))
    return float(np.abs(np.diff(x[a:b])).max()) if b > a + 1 else 0.0


def check_op(work: Path, src: Path, info: dict, name: str, spec: dict, start: int, end: int, clip=None) -> dict:
    out = work / f"{name}.mp4"
    rep = audio.apply(src, info, spec, start, end, out, work / f"w_{name}", clip_path=clip)
    oi = media.probe(out)
    x0, x1 = pcm(src), pcm(out)
    t0, t1 = audio.range_seconds(info, start, end)
    sr = 48000
    inner = slice(int((t0 + 0.12) * sr), int((t1 - 0.12) * sr))
    outside = np.r_[0:int((t0 - 0.05) * sr), int((t1 + 0.05) * sr):min(x0.size, x1.size)]
    res = {
        "op": name, "range_s": [round(t0, 3), round(t1, 3)],
        "frames": [info["n_frames"], oi["n_frames"]], "duration": [round(info["duration"], 4), round(oi["duration"], 4)],
        "picture_untouched": audio.video_md5(src) == audio.video_md5(out),
        "beeps_before": beeps(x0), "beeps_after": beeps(x1),
        "inside_db": [rms_db(x0[inner]), rms_db(x1[inner])],
        "outside_diff_db": rms_db(x1[outside] - x0[outside]),
        "edge_step": [round(max_step(x1, t0), 3), round(max_step(x1, t1), 3), round(max_step(x0, t0), 3)],
        "report": {k: rep[k] for k in ("op", "fade_samples", "peak", "mix", "clip_shorter_by") if k in rep},
    }
    if clip is not None:
        seg = x1[inner]
        spec_ = np.abs(np.fft.rfft(seg * np.hanning(seg.size)))
        freqs = np.fft.rfftfreq(seg.size, 1 / sr)
        res["inside_peak_hz"] = round(float(freqs[int(spec_.argmax())]), 1)
    return res


def check_cut(work: Path, src: Path, info: dict, start: int, end: int, name: str = "cut") -> dict:
    vonly = work / f"{name}_v.mp4"
    out = work / f"{name}.mp4"
    asm = assemble.assemble(src, info, None, start, end, vonly, work / f"w_{name}", with_audio=False)
    rep = audio.cut(vonly, src, info, start, end, out, work / f"wa_{name}")
    oi = media.probe(out)
    x1 = pcm(out)
    removed = end - start + 1
    fl = flashes(out, oi)
    bp = beeps(x1)
    # همگامی: هر فلش و بوقِ متناظرش باید هنوز در یک لحظه باشند
    pairs = [(f, min(bp, key=lambda b: abs(b - f / FPS))) for f in fl] if bp else []
    return {
        "op": name, "removed_frames": removed, "method": asm["method"], "reencoded": asm["reencoded_frames"],
        "checks": {k: v.get("ok") for k, v in asm["checks"].items()},
        "frames": [info["n_frames"], oi["n_frames"]], "duration": [round(info["duration"], 4), round(oi["duration"], 4)],
        "expected_duration": round(info["duration"] - removed / FPS, 4),
        "flashes_after": fl, "beeps_after": bp,
        "av_offset_ms": [round((b - f / FPS) * 1000, 1) for f, b in pairs],
        "join_step": round(max_step(x1, start / FPS), 3), "xfade_ms": rep.get("xfade_ms"),
    }


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    work = Path(tempfile.mkdtemp(prefix="nmregen-audiotest-"))
    out = {}
    src = work / "src.mp4"
    make_clip(src)
    info = media.probe(src)
    out["source"] = {"frames": info["n_frames"], "duration": info["duration"], "flashes": flashes(src, info),
                     "beeps": beeps(pcm(src))}
    tone = work / "tone.mp3"
    make_tone(tone)
    s, e = 105, 164                          # ۳٫۵ تا ۵٫۵ ثانیه — فلش و بوقِ ۵ ثانیه وسطِ بازه است
    out["mute"] = check_op(work, src, info, "mute", {"op": "mute", "fade_ms": 80}, s, e)
    out["volume"] = check_op(work, src, info, "volume", {"op": "volume", "gain_db": -12, "fade_ms": 80}, s, e)
    out["replace"] = check_op(work, src, info, "replace", {"op": "replace", "offset": 0.5, "clip_gain_db": -6,
                                                            "mix": "replace", "fade_ms": 80}, s, e, clip=tone)
    out["mix"] = check_op(work, src, info, "mix", {"op": "replace", "offset": 0, "clip_gain_db": -6, "mix": "mix",
                                                    "bed_db": -14, "fade_ms": 80}, s, e, clip=tone)
    out["cut_smart"] = check_cut(work, src, info, s, e)
    out["cut_head"] = check_cut(work, src, info, 0, 44, name="cut_head")
    src2 = work / "nosei.mp4"
    make_clip(src2, sei=False)
    out["cut_full"] = check_cut(work, src2, media.probe(src2), s, e, name="cut_full")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if "--keep" in argv:
        print("kept:", work)
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
