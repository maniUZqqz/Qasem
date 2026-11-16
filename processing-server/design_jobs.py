#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Node side of the Design studio («استودیوی طراحی»): `edit.slides_mp4` - a deck's slide pictures -> one MP4 with cross-fades, on this GPU.

    payload  {slides: [{file, duration}], width, height, fps, transition ("fade" | "none" | any ffmpeg xfade name), transition_s, crf, title}
    inputs   the slide pictures (PNG/JPG), by the names in payload.slides[].file
    outputs  out.mp4 and video.json {frames, duration_s, width, height, fps, encoder, seconds}

The picture work is ffmpeg only (no extra install: the ffmpeg the video editor already uses); the encoder is h264_nvenc when the card has it,
otherwise libx264 - the answer says which one was used, so the site's acceptance run can tell a GPU encode from a CPU one.
The kind rides the `edit.*` family (capability "ffmpeg"); an agent without this module never advertises it in caps["kinds"], so such a node is
never offered the job (it waits in the durable queue). Hook: `design_jobs.register(HANDLERS, agent_module)` - one guarded call from agent.py.
"""
import json
import os
import shutil
import subprocess
import sys
import time

VERSION = "1.0"
KIND = "edit.slides_mp4"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
XFADE_OK = {"fade", "fadeblack", "fadewhite", "wipeleft", "wiperight", "slideleft", "slideright", "dissolve", "smoothleft", "smoothright", "circleopen", "none"}
MAX_SLIDES = 60
MAX_SIDE = 3840


class DesignError(Exception):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def _find_ffmpeg(agent):
    try:
        import edit_render

        ff = edit_render.ffmpeg_exe(agent, probe=True) or edit_render.ffmpeg_exe(agent)       # full probe: the ffmpeg with a working NVENC wins
        if ff:
            return ff
    except Exception:  # noqa: BLE001
        pass
    try:
        import motion_jobs

        ff = motion_jobs.find_ffmpeg()
        if ff:
            return ff
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg")


def validate(p):
    """(cleaned payload) or DesignError(retryable=False). Nothing in the payload is executed by the node."""
    if not isinstance(p, dict):
        raise DesignError("درخواست معتبر نیست", retryable=False)
    slides = []
    for s in (p.get("slides") or [])[:MAX_SLIDES]:
        name = os.path.basename(str((s or {}).get("file") or ""))
        try:
            dur = float((s or {}).get("duration", 4))
        except (TypeError, ValueError):
            dur = 4.0
        if name and name.lower().endswith((".png", ".jpg", ".jpeg")):
            slides.append({"file": name, "duration": max(1.0, min(60.0, dur))})
    if not slides:
        raise DesignError("اسلایدی در درخواست نیست", retryable=False)
    w = max(320, min(MAX_SIDE, int(p.get("width") or 1920))) // 2 * 2
    h = max(180, min(MAX_SIDE, int(p.get("height") or 1080))) // 2 * 2
    fps = max(10, min(60, int(p.get("fps") or 30)))
    tr = str(p.get("transition") or "fade")
    tr = tr if tr in XFADE_OK else "fade"
    ts = max(0.0, min(2.0, float(p.get("transition_s") if p.get("transition_s") is not None else 0.6)))
    if tr == "none":
        ts = 0.0
    return {"slides": slides, "width": w, "height": h, "fps": fps, "transition": tr, "transition_s": ts, "crf": max(14, min(34, int(p.get("crf") or 22)))}


def build_command(ff, files, p, encoder, out):
    """ffmpeg argv: every picture is looped for its time, scaled/padded to the canvas, then chained with xfade (or concat when there is no fade)."""
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    n = len(files)
    W, H, fps, T = p["width"], p["height"], p["fps"], p["transition_s"]
    for idx, (f, s) in enumerate(zip(files, p["slides"])):
        extra = T if idx < n - 1 else 0.0
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", "%.3f" % (s["duration"] + extra), "-i", f]
    parts = []
    for i in range(n):
        parts.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1,fps=%d,format=yuv420p[v%d]" % (i, W, H, W, H, fps, i))
    if n == 1:
        last = "[v0]"
    elif T <= 0:
        parts.append("".join("[v%d]" % i for i in range(n)) + "concat=n=%d:v=1:a=0[vout]" % n)
        last = "[vout]"
    else:
        cum, prev = 0.0, "[v0]"
        for k in range(1, n):
            cum += p["slides"][k - 1]["duration"]
            lab = "[x%d]" % k
            parts.append("%s[v%d]xfade=transition=%s:duration=%.3f:offset=%.3f%s" % (prev, k, p["transition"], T, max(0.0, cum), lab))
            prev = lab
        last = prev
    cmd += ["-filter_complex", ";".join(parts), "-map", last]
    if encoder == "h264_nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(p["crf"] + 1), "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(p["crf"])]
    cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    return cmd


def total_seconds(p):
    return sum(s["duration"] for s in p["slides"])


def run(job, agent):
    """The `edit.slides_mp4` handler."""
    JobError = getattr(agent, "JobError", None)

    def fail(exc):
        if JobError is not None:
            return JobError(str(exc), retryable=getattr(exc, "retryable", True))
        return RuntimeError(str(exc))

    try:
        p = validate(job.payload)
    except DesignError as e:
        raise fail(e)
    ff = _find_ffmpeg(agent)
    if not ff:
        raise fail(DesignError("ffmpeg روی این کامپیوتر پیدا نشد", retryable=True))
    files = []
    for s in p["slides"]:
        path = job.input_path(s["file"]) if hasattr(job, "input_path") else os.path.join(job.inputs, s["file"])
        if not path or not os.path.isfile(path):
            raise fail(DesignError("تصویرِ اسلاید «%s» در بستهٔ کار نیست" % s["file"], retryable=False))
        files.append(path)
    out = job.out("out.mp4")
    t0 = time.time()
    job.progress(0.05, "ساختِ ویدیوی ارائه")
    used, err = "", ""
    for encoder in ("h264_nvenc", "libx264"):
        cmd = build_command(ff, files, p, encoder, out)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=max(300, int(getattr(job, "timeout_s", 1800)) - 60), creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise fail(DesignError("ساختِ ویدیو بیش از حد طول کشید", retryable=True))
        if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 1000:
            used = encoder
            break
        err = (r.stderr or b"")[-300:].decode("utf-8", "replace")
        try:
            os.remove(out)
        except OSError:
            pass
    if not used:
        raise fail(DesignError("ffmpeg ویدیو را نساخت: %s" % err, retryable=True))
    info = {"frames": int(total_seconds(p) * p["fps"]), "duration_s": round(total_seconds(p), 2), "width": p["width"], "height": p["height"],
            "fps": p["fps"], "encoder": used, "seconds": round(time.time() - t0, 2), "slides": len(files), "bytes": os.path.getsize(out)}
    with open(job.out("video.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh)
    job.progress(0.98, "ویدیو آماده شد (%s)" % ("کارتِ گرافیک" if used == "h264_nvenc" else "پردازنده"), info)
    return info


def register(handlers, agent):
    """The ONE call agent.py makes: adds HANDLERS['edit.slides_mp4'] (agent.py publishes sorted(HANDLERS) as caps['kinds'])."""
    handlers[KIND] = lambda job: run(job, agent)
    return True
