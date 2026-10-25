"""آزمونِ واقعیِ سرتاسریِ بازسازیِ تکه با ffmpeg (بی GPU): `python -m services.video.regen.selftest [--keep]`.

یک ویدیوی آزمایشی می‌سازد (حرکت + دانه + صدا)، «خروجیِ مدل» را شبیه‌سازی می‌کند — تکه‌ای که دقیقاً از فریمِ
قبل از برش شروع و به فریمِ بعد از برش می‌رسد، با سوگیریِ رنگ و نرمیِ یک مدلِ ۴۸۰p — و همهٔ مسیر را اجرا
می‌کند: نقشه ⇐ ورودی‌های مدل ⇐ تکه ⇐ چسباندن (هوشمند و کامل) ⇐ وارسیِ درز. عددها را چاپ می‌کند.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from . import assemble, media, plan as planmod, seams, stitch
from .media import FFMPEG


def make_clip(path: Path, *, fps: str = "30", seconds: float = 12, size: str = "1280x720", sei: bool = True,
              gop: int = 60) -> None:
    """testsrc2 (اجسامِ متحرک) + دانهٔ زمانی + صدای سینوسی؛ x264 با B-frame (SEI دار یا بی SEI)."""
    vf = "noise=alls=7:allf=t,format=yuv420p"
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", str(gop), "-bf", "3",
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart"]
    if not sei:  # منبعی که x264 بودنش معلوم نیست (مثلِ دوربینِ گوشی) ⇐ راهِ کامل
        cmd += ["-bsf:v", "filter_units=remove_types=6"]
    media.run(cmd + [str(path)], timeout=600)


def make_index_clip(path: Path, fps: str = "30", seconds: float = 6) -> None:
    """شمارهٔ هر فریم در ۹ نوارِ سیاه/سفید نوشته شده — برای سنجیدنِ دقیق‌بودنِ خواندنِ فریمِ i."""
    geq = "lum='if(eq(mod(floor(N/pow(2\\,floor(X*9/W)))\\,2)\\,1)\\,235\\,16)':cb=128:cr=128"
    media.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=288x64:r={fps}:d={seconds}",
               "-vf", f"geq={geq},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
               "-bf", "3", "-g", "40", str(path)], timeout=300)


def read_index(frame: np.ndarray) -> int:
    y = frame.mean(axis=2)
    w = y.shape[1]
    return sum((1 << i) for i in range(9) if y[:, int((i + 0.5) * w / 9)].mean() > 128)


class FakeModel:
    """«مدل»: برای هر فریمِ خطِ زمانیِ مدل، فریمِ منبعِ همان لحظه (به اندازهٔ مدل)، با سوگیریِ رنگ، نرمی و
    کمی جابه‌جاییِ محتوا (= «محتوای تازه») — همان چیزی که از یک مدلِ FLF ِ واقعی انتظار می‌رود: دو سر
    روی فریم‌های مرزی، وسط چیزِ دیگری."""

    def __init__(self, base: Path, info: dict, plan: dict, *, bias=(1.06, 0.97, 0.92), blur=1.2, change=True,
                 drift=0.0):
        self.base, self.info, self.plan = base, info, plan
        self.bias, self.blur, self.change = np.array(bias, np.float32), blur, change
        self.drift = drift   # مدلِ بد: تا انتهای تکه این‌قدر پیکسل جابه‌جا ⇐ به فریمِ a نمی‌رسد

    def render(self, out_dir: Path) -> dict:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = self.plan
        files = {}
        t_b = media.frame_time(self.info, p["before"])
        span = p["span"]
        for ch in p["chunks"]:
            names = []
            for k in range(ch["length"]):
                gi = ch["first_gen_index"] + k
                t = t_b + gi / p["G"] * span
                i = min(self.info["n_frames"] - 1, max(0, media.index_at(self.info, t)))
                frame = stitch.to_model(media.read_frame(self.base, self.info, i), p).astype(np.float32)
                frame = cv2.GaussianBlur(frame, (0, 0), self.blur) * self.bias
                if self.drift:
                    m = np.float32([[1, 0, self.drift * gi / p["G"]], [0, 1, 0]])
                    frame = cv2.warpAffine(frame, m, (frame.shape[1], frame.shape[0]), borderMode=cv2.BORDER_REFLECT)
                if self.change and 0 < gi < p["G"]:
                    # چیزی که در منبع نبود: دایره‌ای که وسطِ تکه پیدا و دوباره ناپدید می‌شود
                    amp = math.sin(math.pi * gi / p["G"])
                    h, w = frame.shape[:2]
                    cv2.circle(frame, (int(w * (0.3 + 0.4 * gi / p["G"])), h // 2), int(h * 0.12 * amp + 1),
                               (40.0, 200.0, 90.0), -1)
                path = out_dir / f"c{ch['index']}_{k + 1:05d}_.png"
                media.png(np.clip(frame, 0, 255).astype(np.uint8), path)
                names.append(path)
            files[ch["index"]] = names
        return files


def run_case(work: Path, name: str, *, fps="30", sei=True, start_s=4.0, end_s=6.5, context=1, keep=False,
             seconds=12, model_kw=None) -> dict:
    case = work / name
    case.mkdir(parents=True, exist_ok=True)
    src = case / "src.mp4"
    make_clip(src, fps=fps, sei=sei, seconds=seconds)
    info = media.probe(src)
    start = media.index_at(info, start_s)
    end = media.index_at(info, end_s)
    t0 = time.monotonic()
    p = planmod.make_plan(info, start, end, context=context)
    graph = planmod.build_graph(p, prompt="test", start_names=["s.png"] * len(p["start_ctx"]),
                                end_names=["e.png"] * len(p["end_ctx"]))
    s_names, e_names, files = stitch.model_inputs(p, info, src, case / "inputs", "t")
    gen_files = FakeModel(src, info, p, **(model_kw or {})).render(case / "model")
    gen = stitch.GenFrames(stitch.gen_index_files(p, gen_files), p)
    piece = case / "piece.mkv"
    st = stitch.build_piece(p, gen, info, src, piece, seed=7)
    out = case / ("out" + assemble.container_for(info))
    asm = assemble.assemble(src, info, piece, start, end, out, case / "work")
    out_info = media.probe(out)
    sm = seams.measure(src, info, out, out_info, start, end)
    # بیرونِ تکه دست نخورده؟ (هوشمند: بیت‌به‌بیت؛ کامل: PSNR بالا)
    outside = [0, max(0, start - 30), min(info["n_frames"] - 1, end + 30), info["n_frames"] - 1]
    psnr = {str(i): round(assemble._psnr(media.read_frame(out, out_info, i), media.read_frame(src, info, i)), 1)
            for i in outside}
    res = {
        "case": name, "fps": info["fps"], "frames": info["n_frames"], "range": [start, end],
        "replaced": end - start + 1, "seconds": round(time.monotonic() - t0, 1),
        "plan": {k: p[k] for k in ("G", "model_fps", "effective_fps", "speed", "gen_size", "canvas", "blend",
                                   "context", "estimate_seconds")} | {"chunks": [(c["length"], c["first_gen_index"]) for c in p["chunks"]]},
        "graph_nodes": len(graph),
        "stitch": st, "assemble": {k: v for k, v in asm.items() if k != "checks"} | {
            "checks": {k: v.get("ok") for k, v in asm["checks"].items()}},
        "seams": sm, "outside_psnr": psnr,
        "duration": [round(info["duration"], 4), round(out_info["duration"], 4)],
        "audio_md5_equal": media.audio_md5(src) == media.audio_md5(out),
    }
    if not keep:
        shutil.rmtree(case / "model", ignore_errors=True)
    return res


def check_index(work: Path) -> dict:
    src = work / "index.mp4"
    make_index_clip(src)
    info = media.probe(src)
    bad = []
    for i in (0, 1, 2, 39, 40, 41, 77, 100, 150, info["n_frames"] - 1):
        got = read_index(media.read_frame(src, info, i))
        if got != i:
            bad.append((i, got))
    run = media.read_frames(src, info, 57, 9)
    seq = [read_index(f) for f in run]
    return {"frames": info["n_frames"], "single_reads_wrong": bad, "run_57_65": seq,
            "ok": not bad and seq == list(range(57, 66))}


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    keep = "--keep" in argv
    work = Path(tempfile.mkdtemp(prefix="nmregen-selftest-"))
    results = {"index": check_index(work)}
    cases = [
        ("x264_30fps_smart", {"fps": "30", "sei": True}),
        ("nosei_25fps_full", {"fps": "25", "sei": False}),
        ("x264_30fps_long_chain", {"fps": "30", "sei": True, "start_s": 2.0, "end_s": 9.5, "seconds": 12}),
        ("x264_60fps_context5", {"fps": "60", "sei": True, "start_s": 3.0, "end_s": 4.0, "seconds": 7,
                                 "context": 5}),
        ("bad_model_detected", {"fps": "30", "sei": True, "model_kw": {"drift": 40.0}, "seconds": 9}),
    ]
    only = [a for a in argv if not a.startswith("--")]
    for name, kw in cases:
        if only and name not in only:
            continue
        results[name] = run_case(work, name, keep=keep, **kw)
    print(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print("kept:", work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
