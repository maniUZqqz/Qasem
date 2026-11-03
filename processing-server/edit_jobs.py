#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edit.track and edit.matte - the two smaller video-editor jobs of the node (agent 2.2).

edit.track   follow a point/region with OpenCV (edit_track.py - an identical copy of the site's tracking.py; the site's
             tests fail when they differ). Needs cv2 + numpy in the agent's Python; caps.edit.track says whether they are.
             The site sends a small proxy of the stretch (clip.mp4) and the region; the answer is track.json.
edit.matte   cut the subject out of every frame of a short clip: the frames go one by one to the photo kit's background
             remover (BiRefNet-lite ONNX, the model the kit already has: tools\\PersianAiKit\\Photo\\models\\background\\
             birefnet-lite.onnx) and the masks are put together into a grey video (matte.mp4) at the sampling rate. NOTHING
             is downloaded here: when the model or the photo service is missing the job says exactly what is needed.
"""
import glob
import json
import os
import shutil
import subprocess
import time

import edit_render

MODEL_REL = ("Photo", "models", "background", "birefnet-lite.onnx")
MODEL_NEEDED = (
    "MATTE_MODEL: the background-removal model is not installed on this node. Needed: the package 'photo-background' "
    "(BiRefNet-lite ONNX, ~224 MB, MIT) at %s - run Download-Models.bat (or the panel's models page) once; "
    "nothing is downloaded by this job. For faster video matting a video-matting model (for example Robust Video "
    "Matting as ONNX, ~14 MB) could be added later; none is installed. | "
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
    if not os.path.isfile(agent.kit_dir(*MODEL_REL)):
        raise agent.JobError(MODEL_NEEDED % agent.kit_dir(*MODEL_REL), retryable=False)
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
    return {"primary": "matte.mp4", "engine": "edit.matte", "frames": n, "fps": fps, "model": "birefnet-lite", "time": time.strftime("%H:%M:%S")}
