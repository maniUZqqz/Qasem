#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edit.track and edit.matte - the two smaller video-editor jobs of the node (agent 2.2).

edit.track   follow a point/region with OpenCV (edit_track.py - an identical copy of the site's tracking.py; the site's
             tests fail when they differ). Needs cv2 + numpy in the agent's Python; caps.edit.track says whether they are.
             The site sends a small proxy of the stretch (clip.mp4) and the region; the answer is track.json.
edit.matte   cut the subject out of a short clip into a grey video (matte.mp4). Two ways, the first one preferred:
             1. Robust Video Matting (edit_rvm.py, agent 2.5): a ~14 MB ONNX model made for video; the frames go through it one
                after the other with its recurrent state carried along, so the edge stays steady and it is fast. It needs the
                model (package 'video-matting': Download-Models.bat / the agent's start-up download, or fetched from the site
                the first time a video job finds it missing) and a Python with numpy + onnxruntime (nothing is installed here).
             2. the older way: the frames go one by one to the photo kit's background remover (BiRefNet-lite ONNX, the model
                the kit already has: tools\\PersianAiKit\\Photo\\models\\background\\birefnet-lite.onnx), slower and it flickers.
             Used when RVM cannot run; when neither can, the job says exactly what is needed.
"""
import glob
import json
import os
import shutil
import subprocess
import time

import edit_render
import edit_rvm

MODEL_REL = ("Photo", "models", "background", "birefnet-lite.onnx")
MODEL_NEEDED = (
    "MATTE_MODEL: the background-removal model is not installed on this node. Needed: the package 'photo-background' "
    "(BiRefNet-lite ONNX, ~224 MB, MIT) at %s - run Download-Models.bat (or the panel's models page) once. "
    "The faster video model (Robust Video Matting, ~14 MB, package 'video-matting') is fetched by itself from the site and "
    "runs when some Python of this computer has numpy + onnxruntime (pip install numpy onnxruntime; nothing is installed by "
    "this job). | "
    "مدلِ حذفِ پس‌زمینه روی این سرورِ پردازش نصب نیست: بستهٔ «photo-background» (BiRefNet-lite، حدود ۲۲۴ مگابایت) لازم است."
)


def run_track(job, agent):
    import edit_track

    p = job.payload
    video = job.input_path(p.get("video"))
    if not video:
        raise agent.JobError("track: the clip is not in the job package", retryable=False)
    ff = edit_render.ffmpeg_exe(agent)
    if not ff:
        raise agent.JobError("ffmpeg is not installed on this node", retryable=False)
    size = p.get("size") or [0, 0]
    job.progress(0.05, "track")
    try:
        result = edit_track.track(video, 0.0, float(p.get("duration") or 1.0), p.get("region") or {}, src_size=(int(size[0]), int(size[1])),
                                  fps=float(p.get("fps") or 15), ffmpeg=ff, progress=lambda f: job.progress(0.05 + 0.9 * f, "track"))
    except edit_track.TrackError as e:
        raise agent.JobError("TrackError: %s" % e, retryable=False)
    with open(job.out("track.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return {"primary": "track.json", "engine": "edit.track", "frames": result.get("frames")}


def _photo_ready(agent):
    """(ok, why) - the kit's model file is there and the photo service says the background AI can run."""
    model = agent.kit_dir(*MODEL_REL)
    if not os.path.isfile(model):
        return False, MODEL_NEEDED % model
    try:
        health = agent.http("GET", agent.service_url("photo") + "/api/health", timeout=20)
    except Exception as e:  # noqa: BLE001
        return False, "the photo service is not reachable (%s)" % e
    ai = ((health or {}).get("background") or {}).get("ai") or {}
    if not ai.get("installed"):
        return False, MODEL_NEEDED % model
    if not ai.get("canRun"):
        return False, "the background AI cannot run now: %s" % (ai.get("reason") or "not enough free memory")
    return True, ""


def run_matte(job, agent):
    p = job.payload
    video = job.input_path(p.get("video"))
    if not video:
        raise agent.JobError("matte: the clip is not in the job package", retryable=False)
    ff = edit_render.ffmpeg_exe(agent)
    if not ff:
        raise agent.JobError("ffmpeg is not installed on this node", retryable=False)
    why_rvm = ""
    if edit_rvm.enabled():
        try:
            return _matte_rvm(job, agent, ff, video, p)
        except edit_rvm.Unavailable as e:            # nothing was done yet: the per-frame path below takes over
            why_rvm = str(e)
            log = getattr(agent, "log", None)
            if log:
                log("matte: RVM not used (%s) - BiRefNet per frame instead" % why_rvm)
    else:
        why_rvm = "RVM is switched off (NM_RVM=0)"
    return _matte_birefnet(job, agent, ff, video, p, why_rvm)


def _matte_rvm(job, agent, ff, video, p):
    """Robust Video Matting: one pass over the clip with the recurrent state carried from frame to frame."""
    size = p.get("size") or [0, 0]
    try:
        w, h = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        w = h = 0
    if w < 16 or h < 16:
        w, h = edit_rvm.probe_size(ff, video)
    w, h = edit_rvm.even_size(w, h)
    fps = max(2.0, min(30.0, float(p.get("fps") or 24)))
    frames = int(float(p.get("duration") or 0) * fps) + 1 if p.get("duration") else 0
    job.progress(0.02, "prepare")
    out = job.out("matte.mp4")
    meta = edit_rvm.run(job, agent, ff, video, (w, h), fps, frames or 1, out, lambda message, fraction: job.progress(fraction, message),
                        limit=float(os.environ.get("NM_RVM_TIMEOUT_S") or 3600))
    return {"primary": "matte.mp4", "engine": "edit.matte", "frames": meta.get("frames"), "fps": fps, "model": meta.get("model", "rvm-mobilenetv3"),
            "provider": meta.get("provider", ""), "ratio": meta.get("ratio"), "seconds": meta.get("seconds"), "time": time.strftime("%H:%M:%S")}


def _matte_birefnet(job, agent, ff, video, p, why_rvm=""):
    """The older way: every frame through the photo kit's BiRefNet-lite (slower, flickers). `why_rvm` says why RVM was not used."""
    if not os.path.isfile(agent.kit_dir(*MODEL_REL)):
        raise agent.JobError(MODEL_NEEDED % agent.kit_dir(*MODEL_REL) + (" | RVM: %s" % why_rvm if why_rvm else ""), retryable=False)
    if getattr(agent, "MANAGER", None) is not None:
        job.progress(0.02, "prepare")
        agent.MANAGER.prepare_for("photo.edit", agent.STATE.get("auto_switch", True))
    ok, why = _photo_ready(agent)
    if not ok:
        raise agent.JobError(why, retryable=False)
    fps = max(2.0, min(12.0, float(p.get("fps") or 6)))
    work = os.path.join(job.dir, "matte")
    frames, masks = os.path.join(work, "frames"), os.path.join(work, "masks")
    os.makedirs(frames)
    os.makedirs(masks)
    r = subprocess.run([ff, "-v", "error", "-y", "-i", video, "-an", "-vf", "fps=%g,scale='min(1024,iw)':-2" % fps, "-q:v", "3",
                        os.path.join(frames, "f_%05d.jpg")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=600)
    files = sorted(glob.glob(os.path.join(frames, "f_*.jpg")))
    if r.returncode != 0 or not files:
        raise RuntimeError("could not cut frames: %s" % r.stderr.decode("utf-8", "replace")[-300:])
    base = agent.service_url("photo")
    n = len(files)
    for i, f in enumerate(files, 1):
        job.progress(0.05 + 0.85 * (i - 1) / n, "matte|%d|%d" % (i, n))
        with open(f, "rb") as fh:
            body, ctype = agent.multipart({}, {"file": (os.path.basename(f), fh.read())})
        doc = agent.http("POST", base + "/api/docs?name=" + os.path.basename(f), body, {"Content-Type": ctype}, timeout=300)
        did = (doc or {}).get("id") or (doc or {}).get("Id")
        if not did:
            raise RuntimeError("the photo kit did not accept a frame: %s" % str(doc)[:200])
        try:
            agent.http("POST", base + "/api/docs/%s/background?method=ai&force=1" % did, b"", timeout=900)
            png, _h = agent.http("GET", base + "/api/docs/%s/mask" % did, timeout=120, raw=True)
        finally:
            try:
                agent.http("DELETE", base + "/api/docs/%s" % did, timeout=30)
            except Exception:  # noqa: BLE001
                pass
        with open(os.path.join(masks, "m_%05d.png" % i), "wb") as fh:
            fh.write(png)
    job.progress(0.92, "matte|encode")
    out = job.out("matte.mp4")
    r = subprocess.run([ff, "-v", "error", "-y", "-framerate", "%g" % fps, "-i", os.path.join(masks, "m_%05d.png"), "-vf", "format=gray",
                        "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=600)
    shutil.rmtree(work, ignore_errors=True)
    if r.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError("could not build the matte video: %s" % r.stderr.decode("utf-8", "replace")[-300:])
    return {"primary": "matte.mp4", "engine": "edit.matte", "frames": n, "fps": fps, "model": "birefnet-lite", "rvm_skipped": why_rvm,
            "time": time.strftime("%H:%M:%S")}
