#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The pixels of «چندزاویه»: subject tracking, virtual cameras, the auto-edit and 2.5D camera moves (agent 2.11).

Runs in a Python that has numpy + OpenCV + onnxruntime (the node's own `multiangle` environment, made automatically by the
model downloader - see downloads/multiangle.json - or any Python of the computer that already has them). It is a command
line so the agent starts it as a separate process: a crash or a GPU driver hiccup can never take the agent down.

    python multiangle_engine.py status   [--models DIR]
    python multiangle_engine.py virtual  --video in.mp4 --out-dir out --models DIR --ffmpeg ffmpeg [options]
    python multiangle_engine.py move     --input in.jpg|in.mp4 --out-dir out --models DIR --ffmpeg ffmpeg --move dolly_in [options]
    python multiangle_engine.py selftest --out-dir out --models DIR --ffmpeg ffmpeg

Progress goes to stdout as `NMPROGRESS <0..1> <message>`, the answer as one line `NMRESULT <json>`; everything else is the log.

Models (all permissive licences, see downloads/multiangle.json): YuNet face detector (MIT, OpenCV Zoo), YOLOS-tiny person detector
(Apache-2.0), Depth-Anything-V2-Small (Apache-2.0). They run through onnxruntime on the GPU (CUDA, else DirectML) when there is one,
and on the CPU otherwise; a GPU that fails in the middle of a job is dropped and the job goes on on the CPU - and the result says so.
The multi-camera crops are cut from the ORIGINAL pixels with sub-pixel accuracy (area-filtered pre-scale + cubic warp), never from a
re-encoded intermediate.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import multiangle_core as mc  # noqa: E402

VERSION = "1.1"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0

#: model file names inside --models (the manifest downloads them under these names)
MODEL_FILES = {"yunet": "face_detection_yunet_2023mar.onnx", "yolos": "yolos-tiny.onnx", "depth": "depth-anything-v2-small.onnx"}
MAX_SECONDS = 180.0
ANALYSIS_FPS = 5.0
ANALYSIS_LONG = 960


class EngineError(Exception):
    """A failure the panel can show as it is (message in English, `code` for the site to translate)."""

    def __init__(self, message, code="engine"):
        super().__init__(message)
        self.code = code


def log(msg):
    sys.stderr.write("[multiangle] %s\n" % msg)
    sys.stderr.flush()


class Progress:
    def __init__(self, lo=0.0, hi=1.0):
        self.lo, self.hi = lo, hi
        self.t = 0.0

    def sub(self, lo, hi):
        return Progress(self.lo + (self.hi - self.lo) * lo, self.lo + (self.hi - self.lo) * hi)

    def __call__(self, frac, msg=""):
        now = time.time()
        if now - self.t < 0.7 and frac < 0.999:
            return
        self.t = now
        sys.stdout.write("NMPROGRESS %.4f %s\n" % (self.lo + (self.hi - self.lo) * max(0.0, min(1.0, frac)), msg))
        sys.stdout.flush()


# ───────────────────────────────────────────────────────────── ffmpeg / video plumbing

def probe(ff, path):
    """{"width","height","fps","duration","has_audio"} of a video as the viewer sees it (rotation applied)."""
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise EngineError("the video cannot be opened: %s" % os.path.basename(path), "no_video")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    nfr = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise EngineError("the video has no readable picture", "no_video")
    h, w = frame.shape[:2]
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                           timeout=60, creationflags=NO_WINDOW)
        text = r.stderr.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        text = ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else (nfr / fps if fps > 0 else 0.0)
    if not (1.0 <= fps <= 120.0):
        m2 = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
        fps = float(m2.group(1)) if m2 else 30.0
    return {"width": int(w), "height": int(h), "fps": round(fps, 3), "duration": round(float(duration), 3),
            "has_audio": bool(re.search(r"Stream #\d+:\d+.*Audio:", text))}


class Decoder:
    """Raw BGR frames out of ffmpeg: optional crop (the active picture), constant frame rate, optional scale. Iterate over it."""

    def __init__(self, ff, path, size, fps, crop=None, scale=None, start=0.0, duration=None, extra_vf=None):
        vf = []
        if crop:
            x0, y0, x1, y1 = crop
            vf.append("crop=%d:%d:%d:%d" % (x1 - x0, y1 - y0, x0, y0))
        vf.append("fps=%s" % ("%.6f" % fps).rstrip("0").rstrip("."))
        if scale:
            vf.append("scale=%d:%d:flags=area" % scale)
        if extra_vf:
            vf.append(extra_vf)
        self.shape = (scale[1], scale[0]) if scale else ((crop[3] - crop[1], crop[2] - crop[0]) if crop else (size[1], size[0]))
        cmd = [ff, "-v", "error", "-nostdin"]
        if start:
            cmd += ["-ss", "%.3f" % start]
        cmd += ["-i", path]
        if duration:
            cmd += ["-t", "%.3f" % duration]
        cmd += ["-an", "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)

    def __iter__(self):
        import numpy as np

        h, w = self.shape
        size = h * w * 3
        try:
            while True:
                buf = bytearray(size)
                view = memoryview(buf)
                got = 0
                while got < size:
                    n = self.proc.stdout.readinto(view[got:])
                    if not n:
                        break
                    got += n
                if got < size:
                    return
                yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
        finally:
            self.close()

    def close(self):
        try:
            self.proc.stdout.close()
        except OSError:
            pass
        try:
            self.proc.kill()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.SubprocessError:
            pass


def read_audio(ff, path, seconds, sr=16000):
    """Mono float32 PCM of the first `seconds` of the sound, or None when the file has no sound."""
    import numpy as np

    r = subprocess.run([ff, "-v", "error", "-nostdin", "-i", path, "-t", "%.2f" % seconds, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=600, creationflags=NO_WINDOW)
    if r.returncode != 0 or len(r.stdout) < sr * 4 // 2:
        return None
    return np.frombuffer(r.stdout, dtype=np.float32)


def encoder_args(use_nvenc, crf=19):
    if use_nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 2), "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p"]


def nvenc_ok(ff):
    """Can this ffmpeg encode with the card? (a 5-frame test encode; cached per process)"""
    if os.environ.get("NM_MULTIANGLE_NVENC", "").strip() == "0":
        return False
    if "ok" in nvenc_ok.__dict__:
        return nvenc_ok.ok
    try:
        r = subprocess.run([ff, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=black:s=256x256:r=10:d=1", "-frames:v", "5", "-c:v", "h264_nvenc",
                            "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=60, creationflags=NO_WINDOW)
        nvenc_ok.ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        nvenc_ok.ok = False
    return nvenc_ok.ok


class Encoder:
    """One output file: raw BGR frames in, H.264 (+ the source's sound, trimmed to the same stretch) out."""

    def __init__(self, ff, out, size, fps, audio_from=None, start=0.0, duration=None, nvenc=False):
        self.out, self.size, self.nvenc = out, size, nvenc
        self.ff, self.fps, self.audio_from, self.start, self.duration = ff, fps, audio_from, start, duration
        self.proc = None
        self.frames = 0
        self._open(nvenc)

    def _open(self, nvenc):
        w, h = self.size
        cmd = [self.ff, "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (w, h), "-r", "%.6f" % self.fps, "-i", "-"]
        if self.audio_from:
            if self.start:
                cmd += ["-ss", "%.3f" % self.start]
            cmd += ["-i", self.audio_from]
            if self.duration:
                cmd += ["-t", "%.3f" % self.duration]
            cmd += ["-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest"]
        else:
            cmd += ["-map", "0:v:0"]
        cmd += encoder_args(nvenc) + ["-movflags", "+faststart", self.out]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NO_WINDOW)

    def write(self, frame):
        try:
            self.proc.stdin.write(frame.tobytes() if not frame.flags["C_CONTIGUOUS"] else memoryview(frame))
            self.frames += 1
        except (OSError, ValueError):
            err = self._finish_err()
            raise EngineError("the encoder stopped: %s" % err[-300:], "encode")

    def _finish_err(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            err = self.proc.stderr.read().decode("utf-8", "replace")
        except OSError:
            err = ""
        self.proc.wait()
        return err

    def close(self):
        err = self._finish_err()
        if self.proc.returncode != 0 or not os.path.isfile(self.out) or os.path.getsize(self.out) <= 0:
            raise EngineError("the encoder failed: %s" % err[-300:], "encode")
        return self.out


# ───────────────────────────────────────────────────────────── models

class Session:
    """An onnxruntime session on the best provider, with a logged fallback to the CPU when the GPU fails mid-job."""

    def __init__(self, path, provider="auto", name=""):
        import onnxruntime as ort

        self.ort, self.path, self.name = ort, path, name
        self.provider_pref = provider
        self.fell_back = False
        self.last_error = ""
        avail = ort.get_available_providers()
        order = []
        want = (provider or "auto").lower()
        if want in ("auto", "cuda") and "CUDAExecutionProvider" in avail:
            order.append("CUDAExecutionProvider")
        if want in ("auto", "dml", "directml") and "DmlExecutionProvider" in avail:
            order.append("DmlExecutionProvider")
        self.session = None
        for first in (order, []):
            try:
                self.session = self._make(first + ["CPUExecutionProvider"])
                break
            except Exception as e:  # noqa: BLE001
                if not first:
                    raise
                self.last_error = str(e)[:200]
                log("%s: GPU provider %s failed to start (%s) - CPU instead" % (name, first, self.last_error))
                self.fell_back = True
        self.provider = self.session.get_providers()[0].replace("ExecutionProvider", "")
        self.inputs = [i.name for i in self.session.get_inputs()]

    def _make(self, providers):
        so = self.ort.SessionOptions()
        so.graph_optimization_level = self.ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.log_severity_level = 3
        if "DmlExecutionProvider" in providers:
            so.enable_mem_pattern = False
            so.execution_mode = self.ort.ExecutionMode.ORT_SEQUENTIAL
        if "CPUExecutionProvider" == providers[0]:
            so.intra_op_num_threads = max(1, (os.cpu_count() or 2))
        return self.ort.InferenceSession(self.path, so, providers=providers)

    def run(self, feed):
        try:
            return self.session.run(None, feed)
        except Exception as e:  # noqa: BLE001
            if self.provider == "CPU":
                raise
            self.last_error = str(e)[:200]
            log("%s: the %s run failed (%s) - continuing on the CPU" % (self.name, self.provider, self.last_error))
            self.session = self._make(["CPUExecutionProvider"])
            self.provider = "CPU"
            self.fell_back = True
            return self.session.run(None, feed)


class Models:
    def __init__(self, folder, provider="auto"):
        self.folder, self.provider = folder, provider
        self.yunet = self.yolos = self.depth = None
        self._depth_size = 392

    def path(self, key):
        return os.path.join(self.folder or "", MODEL_FILES[key])

    def have(self, key):
        return bool(self.folder) and os.path.isfile(self.path(key))

    def face_detector(self, w, h):
        import cv2

        if not self.have("yunet"):
            return None
        if self.yunet is None:
            self.yunet = cv2.FaceDetectorYN.create(self.path("yunet"), "", (w, h), 0.70, 0.30, 2000)
        self.yunet.setInputSize((w, h))
        return self.yunet

    def faces(self, bgr):
        """[{"box": (x,y,w,h) fractions, "kind": "face", "score", "yaw"}]"""
        h, w = bgr.shape[:2]
        det = self.face_detector(w, h)
        if det is None:
            return []
        _n, rows = det.detect(bgr)
        out = []
        for r in (rows if rows is not None else []):
            x, y, bw, bh = [float(v) for v in r[:4]]
            if bw < 6 or bh < 6:
                continue
            rex, lex, nx = float(r[4]), float(r[6]), float(r[8])           # right eye (image left), left eye, nose
            half = max(abs(lex - rex) / 2.0, 1.0)
            yaw = max(-1.0, min(1.0, (nx - (rex + lex) / 2.0) / half))
            out.append({"box": (x / w, y / h, bw / w, bh / h), "kind": "face", "score": float(r[14]), "yaw": yaw})
        return out

    def persons(self, bgr, thr=0.55):
        """[{"box": (x,y,w,h) fractions, "kind": "person", "score"}] from YOLOS-tiny (COCO class 1)."""
        import cv2
        import numpy as np

        if not self.have("yolos"):
            return []
        if self.yolos is None:
            self.yolos = Session(self.path("yolos"), self.provider, "yolos")
        h, w = bgr.shape[:2]
        short = 384.0
        s = short / min(h, w)
        nh, nw = max(32, int(round(h * s / 16)) * 16), max(32, int(round(w * s / 16)) * 16)
        img = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(np.float32) / 255.0
        img = (img - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
        logits, boxes = self.yolos.run({self.yolos.inputs[0]: np.ascontiguousarray(img.transpose(2, 0, 1)[None])})[:2]
        logits, boxes = logits[0], boxes[0]
        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        prob = e / e.sum(axis=1, keepdims=True)
        score = prob[:, 1]
        out = []
        for i in np.argsort(-score):
            if score[i] < thr:
                break
            cx, cy, bw, bh = [float(v) for v in boxes[i]]
            box = (max(0.0, cx - bw / 2), max(0.0, cy - bh / 2), min(1.0, bw), min(1.0, bh))
            if any(mc.iou(box, o["box"]) > 0.6 for o in out):
                continue
            out.append({"box": box, "kind": "person", "score": float(score[i])})
        return out

    def depth_map(self, bgr, size=None):
        """Relative nearness (float32, bigger = nearer) at the size of the picture the net saw -> resized by the caller."""
        import cv2
        import numpy as np

        if not self.have("depth"):
            raise EngineError("the depth model is not installed on this node", "no_model")
        if self.depth is None:
            self.depth = Session(self.path("depth"), self.provider, "depth")
        h, w = bgr.shape[:2]
        short = int(size or self._depth_size)
        s = short / float(min(h, w))
        nh, nw = max(14, int(round(h * s / 14)) * 14), max(14, int(round(w * s / 14)) * 14)
        img = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_CUBIC)[:, :, ::-1].astype(np.float32) / 255.0
        img = (img - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
        out = self.depth.run({self.depth.inputs[0]: np.ascontiguousarray(img.transpose(2, 0, 1)[None])})[0]
        return np.asarray(out, dtype=np.float32).reshape(out.shape[-2], out.shape[-1])

    def devices(self):
        d = {}
        for k in ("yolos", "depth"):
            s = getattr(self, k)
            if s is not None:
                d[k] = s.provider
        if self.yunet is not None:
            d["yunet"] = "CPU"
        fell = [k for k in ("yolos", "depth") if getattr(self, k) is not None and getattr(self, k).fell_back]
        return d, fell


# ───────────────────────────────────────────────────────────── analysis: who is in the picture, when

def sample_active_area(ff, path, info, duration, start=0.0):
    """The picture without black bars (the UNION of what every sampled frame shows), from a handful of frames spread over the part of the clip
    that is used. Bars that change inside this union are handled per frame by scan_rects."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(path)
    grays = []
    try:
        for k in range(6):
            t = start + duration * (0.04 + 0.92 * k / 5.0)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, fr = cap.read()
            if ok and fr is not None:
                g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
                grays.append(g)
    finally:
        cap.release()
    if not grays:
        return (0, 0, info["width"], info["height"])
    h, w = grays[0].shape
    x0, y0, x1, y1 = mc.active_area(grays, threshold=16, min_share=0.03)
    # even sizes (video encoders) and a sanity floor
    x0, y0 = x0 // 2 * 2, y0 // 2 * 2
    x1, y1 = max(x0 + 64, x1 // 2 * 2), max(y0 + 64, y1 // 2 * 2)
    return (int(x0), int(y0), int(min(w, x1)), int(min(h, y1)))


SCAN_LONG = 360


def scan_rects(ff, path, info, crop, fps, start, duration, progress=None):
    """The picture rectangle of EVERY frame inside `crop` (fractions of the crop), for clips whose black strips change while they play
    (a composite: a 9:16 picture, then at second 8 a narrower layout). One more decode of the clip, scaled down to ~360 px and read as gray,
    so it costs seconds, not minutes. Returns an (n, 4) array (multiangle_core.clean_rects) or None when the clip could not be read."""
    import cv2

    x0, y0, x1, y1 = crop
    aw, ah = x1 - x0, y1 - y0
    k = min(1.0, SCAN_LONG / float(max(aw, ah)))
    sw, sh = max(32, int(aw * k) // 2 * 2), max(32, int(ah * k) // 2 * 2)
    want = max(2, int(round(duration * fps)))
    rects = []
    dec = Decoder(ff, path, (info["width"], info["height"]), fps, crop=crop, scale=(sw, sh), start=start, duration=duration)
    for fr in dec:
        rects.append(mc.frame_rect(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)))
        if progress is not None and len(rects) % 30 == 0:
            progress(min(1.0, len(rects) / float(want)), "bars")
        if len(rects) >= want:
            break
    if len(rects) < 2:
        return None
    return mc.clean_rects(rects, fps, pad=(1.5 / sw, 1.5 / sh))


def analyse(ff, path, info, crop, models, duration, progress, start=0.0):
    """Walk the clip at ANALYSIS_FPS and find the people / faces; return the per-sample subject series."""
    import cv2
    import numpy as np

    aw, ah = crop[2] - crop[0], crop[3] - crop[1]
    k = min(1.0, ANALYSIS_LONG / float(max(aw, ah)))
    sw, sh = max(32, int(aw * k) // 2 * 2), max(32, int(ah * k) // 2 * 2)
    n = max(2, int(duration * ANALYSIS_FPS))
    tracker = mc.Tracker(n, max_miss=int(1.6 * ANALYSIS_FPS))
    motion = np.zeros((n, 3))                    # x, y, energy of the frame difference
    sal = np.zeros((n, 2))
    prev = None
    dec = Decoder(ff, path, (info["width"], info["height"]), ANALYSIS_FPS, crop=crop, scale=(sw, sh), start=start, duration=duration)
    i = 0
    have_models = models.have("yunet") or models.have("yolos")
    for frame in dec:
        if i >= n:
            break
        dets = []
        if have_models:
            dets = models.faces(frame) + models.persons(frame)
        tracker.update(i, dets)
        if dets:
            full_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            tracker.annotate(i, lambda box, face: mc.find_head_top(full_gray, face, box))
        gray = cv2.cvtColor(cv2.resize(frame, (64, int(64 * sh / sw) // 2 * 2 or 2), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        s = mc.spectral_residual_saliency(gray)
        yy, xx = np.unravel_index(int(np.argmax(cv2.GaussianBlur(s.astype(np.float32), (0, 0), 2.0))), s.shape)
        sal[i] = (xx / float(s.shape[1]), yy / float(s.shape[0]))
        if prev is not None:
            diff = np.abs(gray.astype(np.float32) - prev.astype(np.float32))
            e = float(diff.mean())
            if e > 1.0:
                ys, xs = np.mgrid[0:diff.shape[0], 0:diff.shape[1]]
                wsum = diff.sum() + 1e-6
                motion[i] = ((diff * xs).sum() / wsum / diff.shape[1], (diff * ys).sum() / wsum / diff.shape[0], e)
            else:
                motion[i] = (np.nan, np.nan, e)
        else:
            motion[i] = (np.nan, np.nan, 0.0)
        prev = gray
        i += 1
        progress(min(1.0, i / float(n)), "analysis")
    got = i
    if got < 2:
        raise EngineError("the video could not be decoded", "no_video")
    tracks = mc.rank_subjects(tracker.tracks(), n)
    return {"n": got, "tracks": tracks, "motion": motion[:got], "saliency": sal[:got], "size": (aw, ah)}


def subject_series(track, n, fps_a):
    """One subject's boxes / face boxes / yaw as gap-filled arrays (None where the subject is never seen)."""
    import numpy as np

    gap = int(1.5 * fps_a)
    box = np.stack([mc.fill_gaps(mc.median_filter(track["boxes"][:n, k], 3) if not np.isnan(track["boxes"][:n, k]).any() else track["boxes"][:n, k], gap, int(1.0 * fps_a)) for k in range(4)], axis=1)
    face = np.stack([mc.fill_gaps(track["faces"][:n, k], int(0.8 * fps_a), int(0.5 * fps_a)) for k in range(4)], axis=1)
    yaw = mc.fill_gaps(track["yaw"][:n], int(1.0 * fps_a), int(0.5 * fps_a))
    top = np.full(n, np.nan)
    if track.get("tops") is not None and not np.isnan(track["tops"][:n]).all():
        # the measured top of the head: a gap-filled, lightly smoothed series (a head top is a slow thing); the ends hold
        top = mc.fill_gaps(track["tops"][:n], int(1.5 * fps_a), int(2.0 * fps_a))
        known = ~np.isnan(top)
        if known.sum() >= 3:
            top[known] = mc.median_filter(top[known], 5)
    return box, face, yaw, top


def series_row(box, face, yaw, top, i):
    import numpy as np

    b = box[i]
    if np.isnan(b).any():
        return None
    f = face[i]
    return {"box": tuple(float(v) for v in b), "face": None if np.isnan(f).any() else tuple(float(v) for v in f),
            "yaw": 0.0 if np.isnan(yaw[i]) else float(yaw[i]), "top": None if np.isnan(top[i]) else float(top[i])}


def pick_subjects(an):
    """-> (mode, primary series, secondary series | None, descriptions)."""
    tracks = an["tracks"]
    n = an["n"]
    good = [t for t in tracks if t["coverage"] >= 0.15]
    if good:
        prim = subject_series(good[0], n, ANALYSIS_FPS)
        sec = subject_series(good[1], n, ANALYSIS_FPS) if len(good) > 1 and good[1]["coverage"] >= 0.30 else None
        return ("person" if good[0]["kind"] == "person" else "face"), prim, sec, good
    return "motion", None, None, []


def fallback_series(an, n):
    """No person or face: follow the odd-one-out / the motion with a heavily smoothed centre, as a loose 'subject' box."""
    import numpy as np

    mo = an["motion"][:n]
    sa = an["saliency"][:n]
    cx = np.where(np.isnan(mo[:, 0]), sa[:, 0], 0.6 * mo[:, 0] + 0.4 * sa[:, 0])
    cy = np.where(np.isnan(mo[:, 1]), sa[:, 1], 0.6 * mo[:, 1] + 0.4 * sa[:, 1])
    cx = mc.median_filter(cx, 9)
    cy = mc.median_filter(cy, 9)
    # a slow average: the "subject" of a clip without one is the region where things keep happening
    k = int(2.0 * ANALYSIS_FPS)
    ker = np.ones(k) / k
    cx = np.convolve(np.pad(cx, (k, k), mode="edge"), ker, mode="same")[k:-k]
    cy = np.convolve(np.pad(cy, (k, k), mode="edge"), ker, mode="same")[k:-k]
    box = np.stack([cx - 0.12, cy - 0.25, np.full(n, 0.24), np.full(n, 0.5)], axis=1)
    return box, np.full((n, 4), np.nan), np.zeros(n), np.full(n, np.nan)


# ───────────────────────────────────────────────────────────── the virtual cameras

def cut_window(frame, win, out_size, pre_cache=None):
    """Cut one angle's picture from a full frame: `win` = (cx, cy, ch, roll). Area-filtered pre-scale when the crop is much bigger
    than the output, then ONE sub-pixel cubic warp (position, zoom and roll in a single resampling)."""
    import cv2

    cx, cy, ch, roll = win
    h, w = frame.shape[:2]
    ow, oh = out_size
    s = ch * h / float(oh)
    src = frame
    if s > 1.5:
        q = s / 1.2
        key = round(q, 2)
        if pre_cache is not None and key in pre_cache:
            src = pre_cache[key]
        else:
            src = cv2.resize(frame, (max(2, int(round(w / q))), max(2, int(round(h / q)))), interpolation=cv2.INTER_AREA)
            if pre_cache is not None:
                pre_cache[key] = src
    sh, sw = src.shape[:2]
    m = mc.window_to_affine(sw, sh, cx, cy, ch, roll, ow, oh)
    return cv2.warpAffine(src, m, (ow, oh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def run_virtual(a, progress):
    import cv2
    import numpy as np

    os.makedirs(a.out_dir, exist_ok=True)
    ff = a.ffmpeg
    t_all = time.time()
    models = Models(a.models, a.provider)
    info = probe(ff, a.video)
    duration = min(float(a.duration or info["duration"]), info["duration"] or 1e9, float(a.max_seconds))
    if duration < 1.0:
        raise EngineError("the video is shorter than a second", "too_short")
    start = float(a.start or 0.0)
    fps = float(a.fps) if a.fps else min(30.0, info["fps"])
    n_frames = int(duration * fps)
    progress(0.01, "probe")
    crop = sample_active_area(ff, a.video, info, duration, start)
    aw, ah = crop[2] - crop[0], crop[3] - crop[1]
    bars = (aw, ah) != (info["width"], info["height"])
    src_aspect = aw / float(ah)
    out_aspect = mc.out_aspect_for(a.format, src_aspect)
    # black strips that come and go inside that picture (a layout switch at second 8): the rectangle of every frame, so no angle shows a strip
    rects = scan_rects(ff, a.video, info, crop, fps, start, duration, progress.sub(0.015, 0.03))
    rects = mc.resample_rects(rects, n_frames) if rects is not None else None
    moving_bars = rects is not None and mc.rects_vary(rects)
    if not moving_bars:
        rects = None
    wide_scale = mc.effective_wide_scale(rects, src_aspect, out_aspect) if moving_bars else 1.0
    out_w, out_h = mc.pick_output_size(aw, ah, out_aspect, a.out_height or None, 1080, wide_scale=wide_scale)

    # 1. who is where
    an = analyse(ff, a.video, info, crop, models, duration, progress.sub(0.03, 0.30), start)
    n_a = an["n"]
    mode, prim, sec, good = pick_subjects(an)
    if prim is None:
        prim = fallback_series(an, n_a)
    t_a = (np.arange(n_a) + 0.5) / ANALYSIS_FPS
    requested = [k for k in a.angles.split(",") if k in mc.ANGLES]
    if not requested:
        requested = ["wide", "medium", "close"]
    active, skipped = mc.available_angles(requested, good if good else [], mode)
    if mode == "motion" and not good:
        active = [k for k in active if mc.ANGLES[k]["subjects"] == 1] or ["wide"]
        skipped = {k: "one_subject" for k in requested if k not in active and mc.ANGLES[k]["subjects"] == 2}

    # 2. the paths of every camera
    s1_rows = [series_row(*prim, i) for i in range(n_a)]
    s2_rows = [series_row(*sec, i) if sec is not None else None for i in range(n_a)]
    all_targets = {}
    for key in active:
        all_targets[key] = [mc.frame_for(key, s1_rows[i], src_aspect, out_aspect, subj2=s2_rows[i]) for i in range(n_a)]
    # where the head is, frame by frame: the hard rule that no close shot ever cuts the hair (mc.keep_headroom)
    head_top = mc.head_top_series(t_a, [mc.head_top_of(r) if r is not None else float("nan") for r in s1_rows], n_frames, fps)
    if not a.out_height:
        # «auto» height: as many rows as the tightest shot can carry without being blown up much (never fewer than 720 unless the
        # picture itself is smaller, never more than the wide shot has)
        tight = min(float(np.median([r[2] for r in rows])) for rows in all_targets.values())
        want_h = max(720.0, min(1080.0, tight * ah * 1.5))
        out_w, out_h = mc.pick_output_size(aw, ah, out_aspect, want_h, 1080, wide_scale=wide_scale)
    log("source %dx%d (picture %dx%d%s%s), %.2f fps, %.1f s -> output %dx%d" % (info["width"], info["height"], aw, ah, " after cutting black bars" if bars else "",
                                                                          ", bars change %d times" % (len(mc.rect_segments(rects, fps)) - 1) if moving_bars else "", fps, duration, out_w, out_h))
    min_ch = mc.min_window_height(ah, out_h, a.max_upscale)
    paths, stats = {}, {}
    for idx, key in enumerate(active):
        targets = all_targets[key]
        push = 0.04 if key == "wide" else None
        paths[key] = mc.build_path(key, t_a, targets, n_frames, fps, src_aspect, out_aspect, handheld_amount=a.handheld, seed=a.seed + idx, min_ch=min_ch, push=push,
                                   rects=rects, head_top=head_top if key in ("medium", "close", "over_shoulder") else None)
        stats[key] = mc.upscale_stats(paths[key]["ch"], ah, out_h)
    progress(0.32, "paths")

    # 3. the cut plan: where the sound allows a cut, which angle plays
    pcm = read_audio(ff, a.video, duration) if info["has_audio"] else None
    boundaries, kinds, beat = [], [], None
    energy, hop = None, 0.02
    if pcm is not None and len(pcm) > 16000:
        energy, hop = mc.energy_db(pcm, 16000)
        sentences = []
        if a.sentences and os.path.isfile(a.sentences):
            try:
                sentences = json.load(open(a.sentences, encoding="utf-8"))
            except (OSError, ValueError):
                sentences = []
        sb = mc.boundaries_from_sentences(sentences, duration) if sentences else []
        pb = mc.pause_boundaries(energy, hop)
        bb = []
        if a.rhythm in ("auto", "beat"):
            beat = mc.beat_grid(pcm, 16000)
            if beat["confidence"] >= (0.45 if a.rhythm == "auto" else 0.30):
                bb = [{"t": b, "w": 0.55 if a.rhythm == "auto" else 0.9, "kind": "beat"} for b in beat["beats"] if 0.5 < b < duration - 0.5]
        if a.rhythm == "beat":
            boundaries = bb or pb
        elif a.rhythm == "speech":
            boundaries = mc.merge_boundaries(sb, pb)
        else:
            boundaries = mc.merge_boundaries(sb, pb, bb)
    else:
        if a.rhythm in ("auto", "beat"):
            beat = {"bpm": 0.0, "confidence": 0.0, "beats": []}
    kinds = sorted({b["kind"] for b in boundaries})
    plan = mc.plan_edit(duration, active, boundaries, a.pace, fps, energy, hop, a.seed)

    # 4. render: ONE decode of the original, every angle cut from it
    use_nv = nvenc_ok(ff)
    encoders = {}
    names = {}
    for key in active:
        names[key] = "angle_%s.mp4" % key
        encoders[key] = Encoder(ff, os.path.join(a.out_dir, names[key]), (out_w, out_h), fps, a.video, start, duration, use_nv)
    multi = None
    if a.multicam and len(active) >= 2 and len(plan["segments"]) >= 2:
        multi = Encoder(ff, os.path.join(a.out_dir, "multicam.mp4"), (out_w, out_h), fps, a.video, start, duration, use_nv)
    seg_of = [None] * n_frames
    for s in plan["segments"]:
        for f in range(int(round(s["t0"] * fps)), min(n_frames, int(round(s["t1"] * fps)))):
            seg_of[f] = s["angle"]
    shot_frames = {}
    preview_at = int(n_frames * 0.4)
    dec = Decoder(ff, a.video, (info["width"], info["height"]), fps, crop=crop, start=start, duration=duration, extra_vf=None)
    done = 0
    try:
        for fi, frame in enumerate(dec):
            if fi >= n_frames:
                break
            cache = {}
            cut = {}
            for key in active:
                p = paths[key]
                cut[key] = cut_window(frame, (p["cx"][fi], p["cy"][fi], p["ch"][fi], p["roll"][fi]), (out_w, out_h), cache)
                encoders[key].write(cut[key])
            if multi is not None:
                multi.write(cut[seg_of[fi] or active[0]])
            if fi == preview_at:
                shot_frames = {k: v.copy() for k, v in cut.items()}
                shot_frames["_source"] = frame.copy()
            done = fi + 1
            if fi % 15 == 0:
                progress(done / float(n_frames), "render")
    finally:
        dec.close()
    files = {}
    for key, enc in encoders.items():
        enc.close()
        files[key] = names[key]
    if multi is not None:
        multi.close()
    for key, img in shot_frames.items():
        if key != "_source":
            cv2.imwrite(os.path.join(a.out_dir, "preview_%s.jpg" % key), img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if done < n_frames * 0.9:
        raise EngineError("only %d of %d frames could be decoded" % (done, n_frames), "decode")

    dev, fell = models.devices()
    subjects = [{"id": t["id"], "kind": t["kind"], "coverage": t["coverage"], "size": t["size"]} for t in good[:3]]
    result = {
        "v": 1, "engine": "multiangle", "mode": "virtual", "version": VERSION,
        "source": {"width": info["width"], "height": info["height"], "fps": info["fps"], "duration": info["duration"], "has_audio": info["has_audio"],
                   "active": {"x": crop[0], "y": crop[1], "w": aw, "h": ah}, "black_bars": bars or moving_bars,
                   "bars_change": mc.rect_segments(rects, fps, (aw, ah)) if moving_bars else []},
        "output": {"width": out_w, "height": out_h, "fps": fps, "format": a.format, "frames": done, "duration": round(done / fps, 3)},
        "subject_mode": mode, "subjects": subjects,
        "angles": [{"key": k, "label": mc.ANGLES[k]["label"], "file": files[k], "preview": "preview_%s.jpg" % k,
                    "window": {"ch_median": round(float(np.median(paths[k]["ch"])), 4), "ch_min": round(float(paths[k]["ch"].min()), 4), "ch_max": round(float(paths[k]["ch"].max()), 4)},
                    "upscale": {"median": round(stats[k]["median"], 3), "max": round(stats[k]["max"], 3)}} for k in active],
        "skipped_angles": skipped,
        "multicam": "multicam.mp4" if multi is not None else None,
        "cuts": plan["cuts"], "segments": plan["segments"], "cut_quality": plan["quality"],
        "audio": {"pauses": sum(1 for b in boundaries if b["kind"] == "pause"), "sentences": sum(1 for b in boundaries if b["kind"] == "sentence"),
                  "beats": len(beat["beats"]) if beat else 0, "bpm": beat["bpm"] if beat else 0.0, "beat_confidence": beat["confidence"] if beat else 0.0,
                  "cut_points": kinds},
        "warnings": mc.warnings_for(stats, mode, good, skipped, kinds, duration),
        "device": {"models": dev, "model_fallback": fell, "encoder": "nvenc" if use_nv else "x264"},
        "seconds": round(time.time() - t_all, 1),
    }
    with open(os.path.join(a.out_dir, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    progress(1.0, "done")
    return result


# ───────────────────────────────────────────────────────────── 2.5D camera moves

def load_image(path):
    import cv2

    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise EngineError("the picture cannot be read", "no_image")
    return img


def crop_to_aspect(img, aspect, cx, cy):
    """Centre a crop of the given aspect (w/h) on (cx, cy) as fractions - the biggest one that fits."""
    h, w = img.shape[:2]
    if w / float(h) > aspect:
        cw, ch = h * aspect, float(h)
    else:
        cw, ch = float(w), w / aspect
    x0 = int(round(min(max(cx * w - cw / 2, 0), w - cw)))
    y0 = int(round(min(max(cy * h - ch / 2, 0), h - ch)))
    return img[y0:y0 + int(round(ch)), x0:x0 + int(round(cw))], (x0, y0, int(round(cw)), int(round(ch)))


class Warper:
    """Everything a 2.5D move needs per frame: depth (from keys, guided to the picture), pose, splat, fill, remap."""

    def __init__(self, out_size, grid_long, move, amount, relief, focus_d, zoom_extra, hole_inpaint):
        import numpy as np

        self.ow, self.oh = out_size
        k = min(1.0, grid_long / float(max(out_size)))
        self.gw, self.gh = max(16, int(self.ow * k)), max(16, int(self.oh * k))
        self.move, self.amount, self.relief, self.focus_d = move, amount, relief, focus_d
        self.f_px = mc.FOCAL * self.gw
        self.zoom = 1.0
        self.zoom_extra = zoom_extra
        self.hole_inpaint = hole_inpaint
        self.sx = self.ow / float(self.gw)
        self.sy = self.oh / float(self.gh)
        self.np = np
        self.holes_share = []
        self._maps = None

    def depth_z(self, d):
        return mc.depth_to_z(d, self.focus_d, self.relief)

    def pose_flow(self, d, u):
        np = self.np
        pose = mc.camera_pose(self.move, np.asarray(u), self.amount)
        c = tuple(float(np.asarray(v)) for v in pose["c"])
        return mc.project_flow(self.depth_z(d), c, float(np.asarray(pose["yaw"])), float(np.asarray(pose["pitch"])), self.f_px)

    def fit_zoom(self, d):
        """Safe zoom from the extreme poses of this move (computed once, on the first depth map)."""
        zs = []
        for u in (0.0, 0.5, 1.0):
            dx, dy, _z = self.pose_flow(d, u)
            zs.append(mc.safe_zoom(dx, dy, d))
        self.zoom = max(zs) * self.zoom_extra
        return self.zoom

    def _build_maps(self):
        np = self.np
        ys, xs = np.mgrid[0:self.oh, 0:self.ow].astype(np.float32)
        cxo, cyo = (self.ow - 1) / 2.0, (self.oh - 1) / 2.0
        midx = cxo + (xs - cxo) / self.zoom
        midy = cyo + (ys - cyo) / self.zoom
        gx = (midx / self.sx).astype(np.float32)
        gy = (midy / self.sy).astype(np.float32)
        self._maps = (midx.astype(np.float32), midy.astype(np.float32), gx, gy)

    def render(self, img_bgr, d_grid, u):
        """One frame: the picture (output size) seen by the moved camera."""
        import cv2

        np = self.np
        dx, dy, zn = self.pose_flow(d_grid, u)
        bx, by, filled, zbuf = mc.splat_backward(dx, dy, zn, d_grid)
        bx, by, empty = mc.fill_holes_far(bx, by, zbuf, filled, axis_first=1 if float(np.abs(dx).mean()) >= float(np.abs(dy).mean()) else 0)
        self.holes_share.append(float((~filled).mean()))
        if empty.any():
            bx[empty] = 0.0
            by[empty] = 0.0
        if self._maps is None:
            self._build_maps()
        midx, midy, gx, gy = self._maps
        Dx = cv2.remap(bx, gx, gy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        Dy = cv2.remap(by, gx, gy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        mapx = midx + Dx * self.sx
        mapy = midy + Dy * self.sy
        out = cv2.remap(img_bgr, mapx, mapy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101)
        if self.hole_inpaint:
            hole = cv2.resize((~filled).astype(np.uint8) * 255, (self.ow, self.oh), interpolation=cv2.INTER_NEAREST)
            if hole.mean() > 1.0:
                # holes closed by background extension look right for narrow gaps; wide ones get a content-aware touch-up (half size)
                small = cv2.resize(out, (self.ow // 2, self.oh // 2), interpolation=cv2.INTER_AREA)
                m = cv2.dilate(cv2.resize(hole, (self.ow // 2, self.oh // 2), interpolation=cv2.INTER_NEAREST), np.ones((3, 3), np.uint8))
                fixed = cv2.inpaint(small, m, 3, cv2.INPAINT_TELEA)
                up = cv2.resize(fixed, (self.ow, self.oh), interpolation=cv2.INTER_CUBIC)
                soft = cv2.GaussianBlur(cv2.resize(m, (self.ow, self.oh), interpolation=cv2.INTER_NEAREST), (0, 0), 2.0)[:, :, None].astype(np.float32) / 255.0
                out = (out.astype(np.float32) * (1 - soft) + up.astype(np.float32) * soft).astype(np.uint8)
        return out


def depth_grid(models, bgr, gw, gh, size):
    import cv2

    d = models.depth_map(bgr, size)
    return cv2.resize(d, (gw, gh), interpolation=cv2.INTER_CUBIC)


def run_move(a, progress):
    import cv2
    import numpy as np

    os.makedirs(a.out_dir, exist_ok=True)
    ff = a.ffmpeg
    t_all = time.time()
    models = Models(a.models, a.provider)
    if a.move not in mc.MOVES:
        raise EngineError("unknown move %s" % a.move, "bad_move")
    is_video = os.path.splitext(a.input)[1].lower() in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
    fps = float(a.fps or 30.0)
    focus_xy = None
    if a.focus:
        try:
            fx, fy = [float(v) for v in a.focus.split(",")]
            focus_xy = (min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0))
        except ValueError:
            focus_xy = None
    progress(0.02, "load")
    union = None                                  # a video: the picture area every frame lies in (pixels of the full frame)
    rects = None                                  # a video: the picture rectangle of every frame inside `union` (fractions)
    if is_video:
        info = probe(ff, a.input)
        duration = min(info["duration"], float(a.max_seconds) if a.max_seconds < MAX_SECONDS else 12.0)
        fps = min(fps, info["fps"]) if info["fps"] else fps
        first = None
        for first in Decoder(ff, a.input, (info["width"], info["height"]), fps, duration=1.0):
            first = first.copy()
            break
        if first is None:
            raise EngineError("the video has no readable picture", "no_video")
        base = first
        union = sample_active_area(ff, a.input, info, duration)
        rects = scan_rects(ff, a.input, info, union, fps, 0.0, duration)
    else:
        info = None
        duration = float(a.duration or 4.0)
        base = load_image(a.input)
    n_frames = max(2, int(round(duration * fps)))
    # black bars (a vertical clip inside a 16:9 frame, a letterboxed film): the move works on the picture only. A video's bars may change while
    # it plays (a layout switch): every frame has its own picture box, the move always works on the picture of THAT frame
    if union is not None and rects is not None:
        ux0, uy0, ux1, uy1 = union

        def frame_box(i):
            r = rects[min(i, len(rects) - 1)]
            x0, y0 = ux0 + int(round(r[0] * (ux1 - ux0))) // 2 * 2, uy0 + int(round(r[1] * (uy1 - uy0))) // 2 * 2
            x1, y1 = ux0 + int(round(r[2] * (ux1 - ux0))) // 2 * 2, uy0 + int(round(r[3] * (uy1 - uy0))) // 2 * 2
            return x0, y0, max(x0 + 64, x1), max(y0 + 64, y1)
    else:
        bx0, by0, bx1, by1 = mc.active_area([cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)], threshold=16, min_share=0.03)
        bx0, by0, bx1, by1 = bx0 // 2 * 2, by0 // 2 * 2, max(bx0 // 2 * 2 + 64, bx1 // 2 * 2), max(by0 // 2 * 2 + 64, by1 // 2 * 2)

        def frame_box(i):
            return bx0, by0, bx1, by1
    box0 = frame_box(0)
    bars_vary = rects is not None and mc.rects_vary(rects)
    base = base[box0[1]:box0[3], box0[0]:box0[2]]
    bh, bw = base.shape[:2]
    src_aspect = bw / float(bh)
    out_aspect = mc.out_aspect_for(a.format, src_aspect)
    # the focus: a face if there is one, else the middle
    if focus_xy is None:
        faces = models.faces(cv2.resize(base, (min(960, bw), int(bh * min(960, bw) / bw)))) if models.have("yunet") else []
        if faces:
            f = max(faces, key=lambda r: r["box"][2] * r["box"][3])["box"]
            focus_xy = (f[0] + f[2] / 2, f[1] + f[3] / 2)
        else:
            focus_xy = (0.5, 0.5)
    crop_img, crop_box = crop_to_aspect(base, out_aspect, focus_xy[0], focus_xy[1])
    ch_px, cw_px = crop_img.shape[:2]
    long_cap = 1920 if max(cw_px, ch_px) > 1920 else max(cw_px, ch_px)
    sc = min(1.0, a.out_height / float(ch_px) if a.out_height else 1.0, 1080.0 / ch_px if ch_px > 1080 and out_aspect < 1.2 else 1.0, long_cap / float(max(cw_px, ch_px)))
    ow, oh = max(2, int(cw_px * sc) // 2 * 2), max(2, int(ch_px * sc) // 2 * 2)
    fx_local = (focus_xy[0] * bw - crop_box[0]) / float(crop_box[2])
    fy_local = (focus_xy[1] * bh - crop_box[1]) / float(crop_box[3])
    # the focus point in pixels of the full frame: a frame with another picture box keeps the same point still
    focus_px = (box0[0] + focus_xy[0] * bw, box0[1] + focus_xy[1] * bh)

    def prep(frame, fi=0):
        x0, y0, x1, y1 = frame_box(fi)
        frame = frame[y0:y1, x0:x1]
        if (x0, y0, x1, y1) == box0:
            c = frame[crop_box[1]:crop_box[1] + crop_box[3], crop_box[0]:crop_box[0] + crop_box[2]]
        else:
            fh, fw = frame.shape[:2]
            c, _ = crop_to_aspect(frame, out_aspect, min(max((focus_px[0] - x0) / float(fw), 0.0), 1.0), min(max((focus_px[1] - y0) / float(fh), 0.0), 1.0))
        return cv2.resize(c, (ow, oh), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)

    img0 = cv2.resize(crop_img, (ow, oh), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
    warp = Warper((ow, oh), a.grid, a.move, a.amount, a.relief, 0.5, a.zoom, a.inpaint)
    gw, gh = warp.gw, warp.gh
    depth_px = 518 if (models.depth is not None and models.depth.provider != "CPU") else int(a.depth_size)
    dep_ready = models.have("depth")
    if not dep_ready:
        raise EngineError("the depth model is not installed on this node", "no_model")

    def depth_for(frame_small, smoother, prev_gray, gray_now):
        raw = depth_grid(models, frame_small, gw, gh, depth_px)
        cut = mc.DepthSmoother.is_cut(prev_gray, gray_now)
        return smoother.push(raw, cut=cut)

    def guided(d, bgr_small):
        g = cv2.cvtColor(cv2.resize(bgr_small, (gw, gh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        d = cv2.medianBlur(np.ascontiguousarray(d, dtype=np.float32), 3)            # salt-and-pepper out before the edge-aware step
        return np.clip(mc.guided_filter(g, d, r=max(3, gw // 64), eps=1e-3), 0.0, 1.0)

    smoother = mc.DepthSmoother(alpha=0.6 if is_video else 1.0)
    keys = []                                    # (frame index, depth grid)
    progress(0.05, "depth")
    if is_video:
        stride = max(1, int(round(fps / float(a.depth_fps))))
        prev_gray = None
        for fi, fr in enumerate(Decoder(ff, a.input, (info["width"], info["height"]), fps, duration=duration)):
            if fi >= n_frames:
                break
            if fi % stride == 0 or fi == n_frames - 1:
                small = prep(fr, fi)
                gray = cv2.cvtColor(cv2.resize(small, (32, 32), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
                keys.append((fi, depth_for(small, smoother, prev_gray, gray)))
                prev_gray = gray
                progress(0.05 + 0.40 * fi / float(n_frames), "depth")
    else:
        keys.append((0, depth_for(img0, smoother, None, None)))
        progress(0.40, "depth")
    if not keys:
        raise EngineError("the video could not be decoded", "no_video")
    d0 = keys[0][1]
    # focus depth: the median depth around the focus point of the first frame (kept for the whole move: a steady pivot)
    px, py = int(min(max(fx_local, 0.05), 0.95) * gw), int(min(max(fy_local, 0.05), 0.95) * gh)
    rw, rh = max(2, gw // 12), max(2, gh // 12)
    warp.focus_d = float(np.median(d0[max(0, py - rh):py + rh, max(0, px - rw):px + rw]))
    zoom = warp.fit_zoom(d0)
    ease_u = mc.move_progress(n_frames, a.ease)
    use_nv = nvenc_ok(ff)
    enc = Encoder(ff, os.path.join(a.out_dir, "move.mp4"), (ow, oh), fps, a.input if is_video else None, 0.0, duration if is_video else None, use_nv)

    def depth_at(fi, frame_small):
        # between two depth keys: linear blend, then pull the edges to this frame's picture
        j = 0
        while j + 1 < len(keys) and keys[j + 1][0] <= fi:
            j += 1
        if j + 1 < len(keys) and keys[j + 1][0] > keys[j][0]:
            w = (fi - keys[j][0]) / float(keys[j + 1][0] - keys[j][0])
            d = mc.interpolate_depth(keys[j][1], keys[j + 1][1], w)
        else:
            d = keys[j][1]
        return guided(d, frame_small)

    preview_i = n_frames // 2
    preview = None
    frames_iter = iter(Decoder(ff, a.input, (info["width"], info["height"]), fps, duration=duration)) if is_video else None
    last = img0
    for fi in range(n_frames):
        if is_video:
            fr = next(frames_iter, None)
            small = prep(fr, fi) if fr is not None else last
            last = small
        else:
            small = img0
        d = depth_at(fi, small)
        out = warp.render(small, d, float(ease_u[fi]))
        enc.write(out)
        if fi == preview_i:
            preview = out.copy()
            cv2.imwrite(os.path.join(a.out_dir, "depth.png"), (cv2.resize(d, (ow, oh), interpolation=cv2.INTER_CUBIC).clip(0, 1) * 255).astype(np.uint8))
        if fi % 6 == 0:
            progress(0.45 + 0.54 * fi / float(n_frames), "render")
    enc.close()
    if preview is not None:
        cv2.imwrite(os.path.join(a.out_dir, "preview.jpg"), preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
    dev, fell = models.devices()
    holes = warp.holes_share
    result = {
        "v": 1, "engine": "multiangle", "mode": "move25d", "version": VERSION, "move": a.move, "amount": a.amount,
        "input": "video" if is_video else "image", "output": {"width": ow, "height": oh, "fps": fps, "frames": n_frames, "duration": round(n_frames / fps, 3), "format": a.format},
        "bars_change": mc.rect_segments(rects, fps, (union[2] - union[0], union[3] - union[1])) if bars_vary else [],
        "focus": {"x": round(focus_xy[0], 3), "y": round(focus_xy[1], 3), "depth": round(warp.focus_d, 3)},
        "safe_zoom": round(zoom, 3), "depth_keys": len(keys), "holes": {"mean": round(float(np.mean(holes)), 4), "max": round(float(np.max(holes)), 4)},
        "file": "move.mp4", "preview": "preview.jpg", "depth": "depth.png",
        "device": {"models": dev, "model_fallback": fell, "encoder": "nvenc" if use_nv else "x264"}, "seconds": round(time.time() - t_all, 1),
        "warnings": ([{"code": "holes_large", "share": round(float(np.max(holes)), 3)}] if float(np.max(holes)) > 0.08 else []),
    }
    with open(os.path.join(a.out_dir, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    progress(1.0, "done")
    return result


# ───────────────────────────────────────────────────────────── status + self test

def run_status(a):
    info = {"engine": VERSION, "core": mc.VERSION, "python": sys.version.split()[0]}
    try:
        import numpy
        info["numpy"] = numpy.__version__
    except Exception as e:  # noqa: BLE001
        info["numpy"] = None
        info["error"] = "numpy: %s" % e
    try:
        import cv2
        info["cv2"] = cv2.__version__
        info["yunet_api"] = hasattr(cv2, "FaceDetectorYN")
    except Exception as e:  # noqa: BLE001
        info["cv2"] = None
        info["error"] = "cv2: %s" % e
    try:
        import onnxruntime as ort
        info["onnxruntime"] = ort.__version__
        info["providers"] = list(ort.get_available_providers())
    except Exception as e:  # noqa: BLE001
        info["onnxruntime"] = None
        info["error"] = "onnxruntime: %s" % e
    info["models"] = {k: os.path.isfile(os.path.join(a.models or "", f)) for k, f in MODEL_FILES.items()}
    return info


def make_selftest_inputs(ff, out_dir):
    """A synthetic clip (a bright moving shape with sound, no real person: nothing personal in a test) and a synthetic photo."""
    clip = os.path.join(out_dir, "selftest-in.mp4")
    photo = os.path.join(out_dir, "selftest-in.png")
    cmd = [ff, "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=8",
           "-f", "lavfi", "-i", "sine=frequency=220:duration=8,volume=0.5,apad", "-filter_complex",
           "[1:a]volume='if(lt(mod(t,2.6),2.0),1,0.01)':eval=frame[a]", "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "8", clip]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=120, creationflags=NO_WINDOW)
    subprocess.run([ff, "-v", "error", "-nostdin", "-y", "-i", clip, "-frames:v", "1", "-vf", "select=eq(n\\,60)", photo], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=60, creationflags=NO_WINDOW)
    return clip, photo


def make_selftest_bars(ff, out):
    """640x360, 4 s at 25 fps: a 288 px wide picture for 2 s, then a 216 px wide one - black strips that change at second 2 (like a composite)."""
    f = "lutyuv=y='clip(val,70,235)'"
    cmd = [ff, "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=288x360:rate=25:duration=2", "-f", "lavfi", "-i", "testsrc2=size=216x360:rate=25:duration=2",
           "-filter_complex", "[0:v]%s,pad=640:360:176:0:black[a];[1:v]%s,pad=640:360:212:0:black[b];[a][b]concat=n=2:v=1:a=0[v]" % (f, f),
           "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=120, creationflags=NO_WINDOW)


def run_selftest(a, progress):
    """One small real job of each kind on synthetic input + the pass checks the site reads (selftest.json)."""
    import numpy as np

    os.makedirs(a.out_dir, exist_ok=True)
    checks = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})

    st = run_status(a)
    check("runtime", bool(st.get("numpy") and st.get("cv2") and st.get("onnxruntime")), "numpy %s, cv2 %s, onnxruntime %s %s" % (st.get("numpy"), st.get("cv2"), st.get("onnxruntime"), st.get("providers")))
    check("models", all(st["models"].values()), json.dumps(st["models"]))
    if not (st.get("numpy") and st.get("cv2") and st.get("onnxruntime")) or not all(st["models"].values()):
        return _selftest_done(a, checks)
    work = os.path.join(a.out_dir, "selftest-work")
    os.makedirs(work, exist_ok=True)
    clip, photo = make_selftest_inputs(a.ffmpeg, work)
    # 0. black strips that change in the middle of a clip are found on the very frame they change (no model involved)
    try:
        bars = os.path.join(work, "selftest-bars.mp4")
        make_selftest_bars(a.ffmpeg, bars)
        binfo = probe(a.ffmpeg, bars)
        union = sample_active_area(a.ffmpeg, bars, binfo, 4.0)
        rects = scan_rects(a.ffmpeg, bars, binfo, union, 25.0, 0.0, 4.0)
        segs = mc.rect_segments(rects, 25.0) if rects is not None else []
        check("virtual.bars", len(segs) == 2 and abs(segs[1]["t0"] - 2.0) <= 0.1 and abs(union[0] - 176) <= 8 and abs(union[2] - 464) <= 8,
              "%d steps, switch at %s s, picture x %s-%s" % (len(segs), segs[1]["t0"] if len(segs) > 1 else "-", union[0], union[2]))
    except Exception as e:  # noqa: BLE001
        check("virtual.bars", False, "%s: %s" % (type(e).__name__, e))
    # 1. virtual cameras on the synthetic clip
    va = argparse.Namespace(video=clip, out_dir=os.path.join(work, "virtual"), models=a.models, ffmpeg=a.ffmpeg, angles="wide,medium,close", format="source", pace="fast", handheld=0.35,
                            seed=3, sentences="", rhythm="speech", provider=a.provider, max_seconds=60.0, out_height=360, max_upscale=2.0, start=0.0, duration=0.0, fps=0.0, multicam=True)
    try:
        r = run_virtual(va, progress.sub(0.05, 0.55))
        want_frames = int(8 * 25)
        ok_files = all(os.path.isfile(os.path.join(va.out_dir, x["file"])) for x in r["angles"])
        check("virtual.angles", len(r["angles"]) >= 2 and ok_files, "%d angles" % len(r["angles"]))
        check("virtual.synced", all(abs(r["output"]["frames"] - want_frames) <= 2 for _ in [0]), "%d frames of %d" % (r["output"]["frames"], want_frames))
        check("virtual.cuts", len(r["segments"]) >= 2 and r["multicam"] and os.path.isfile(os.path.join(va.out_dir, "multicam.mp4")), "%d shots" % len(r["segments"]))
        check("virtual.on_sound", r["cut_quality"]["cuts_on_points"] >= 1, json.dumps(r["cut_quality"]))
        check("virtual.models_ran", bool(r["device"]["models"]), json.dumps(r["device"]))
    except Exception as e:  # noqa: BLE001
        check("virtual", False, "%s: %s" % (type(e).__name__, e))
    # 2. a 2.5D move on the synthetic photo
    ma = argparse.Namespace(input=photo, out_dir=os.path.join(work, "move"), models=a.models, ffmpeg=a.ffmpeg, move="truck_right", amount=0.8, duration=2.0, fps=25.0, format="source",
                            ease="inout", relief=1.0, zoom=1.0, grid=320, depth_size=252, depth_fps=6, inpaint=False, provider=a.provider, max_seconds=12.0, out_height=360, focus="")
    try:
        r2 = run_move(ma, progress.sub(0.55, 0.95))
        import cv2
        cap = cv2.VideoCapture(os.path.join(ma.out_dir, "move.mp4"))
        frames = []
        ok, fr = cap.read()
        while ok:
            frames.append(fr)
            ok, fr = cap.read()
        cap.release()
        moved = float(np.abs(frames[0].astype(np.float32) - frames[-1].astype(np.float32)).mean()) if len(frames) > 2 else 0.0
        check("move.frames", len(frames) >= 45, "%d frames" % len(frames))
        check("move.parallax", moved > 1.0, "mean change first->last frame %.2f" % moved)
        check("move.depth", os.path.isfile(os.path.join(ma.out_dir, "depth.png")), json.dumps(r2["device"]))
    except Exception as e:  # noqa: BLE001
        check("move", False, "%s: %s" % (type(e).__name__, e))
    return _selftest_done(a, checks)


def _selftest_done(a, checks):
    res = {"v": 1, "engine": "multiangle", "mode": "selftest", "ok": all(c["ok"] for c in checks), "checks": checks, "version": VERSION}
    with open(os.path.join(a.out_dir, "selftest.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    return res


# ───────────────────────────────────────────────────────────── command line

def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(s):
        s.add_argument("--models", default="")
        s.add_argument("--ffmpeg", default="ffmpeg")
        s.add_argument("--out-dir", default="out")
        s.add_argument("--provider", default=os.environ.get("NM_MULTIANGLE_PROVIDER") or "auto", help="auto | cuda | dml | cpu")
        s.add_argument("--max-seconds", type=float, default=MAX_SECONDS)

    s = sub.add_parser("status")
    s.add_argument("--models", default="")
    s = sub.add_parser("virtual")
    common(s)
    s.add_argument("--video", required=True)
    s.add_argument("--angles", default="wide,medium,close")
    s.add_argument("--format", default="source", choices=sorted(mc.FORMATS))
    s.add_argument("--pace", default="medium", choices=sorted(mc.PACE))
    s.add_argument("--handheld", type=float, default=0.35)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--sentences", default="")
    s.add_argument("--rhythm", default="auto", choices=("auto", "speech", "beat"))
    s.add_argument("--out-height", type=int, default=0)
    s.add_argument("--max-upscale", type=float, default=1.7)
    s.add_argument("--start", type=float, default=0.0)
    s.add_argument("--duration", type=float, default=0.0)
    s.add_argument("--fps", type=float, default=0.0)
    s.add_argument("--no-multicam", dest="multicam", action="store_false")
    s = sub.add_parser("move")
    common(s)
    s.add_argument("--input", required=True)
    s.add_argument("--move", default="dolly_in")
    s.add_argument("--amount", type=float, default=0.5)
    s.add_argument("--duration", type=float, default=4.0)
    s.add_argument("--fps", type=float, default=30.0)
    s.add_argument("--format", default="source", choices=sorted(mc.FORMATS))
    s.add_argument("--ease", default="inout", choices=sorted(mc.EASINGS))
    s.add_argument("--relief", type=float, default=1.0)
    s.add_argument("--zoom", type=float, default=1.0, help="extra zoom factor on top of the safe zoom")
    s.add_argument("--grid", type=int, default=640, help="long side of the depth / flow grid")
    s.add_argument("--depth-size", type=int, default=392, help="short side the depth network sees on the CPU (518 on a GPU)")
    s.add_argument("--depth-fps", type=float, default=6.0)
    s.add_argument("--inpaint", action="store_true")
    s.add_argument("--out-height", type=int, default=0)
    s.add_argument("--focus", default="", help="x,y fractions of the picture to keep still (default: the face, else the middle)")
    s = sub.add_parser("selftest")
    common(s)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "status":
        print("NMRESULT " + json.dumps(run_status(a)))
        return 0
    progress = Progress()
    try:
        if a.cmd == "virtual":
            res = run_virtual(a, progress)
        elif a.cmd == "move":
            res = run_move(a, progress)
        else:
            res = run_selftest(a, progress)
        print("NMRESULT " + json.dumps(res, ensure_ascii=False))
        return 0
    except EngineError as e:
        print("NMERROR " + json.dumps({"code": e.code, "message": str(e)}, ensure_ascii=False))
        return 3
    except MemoryError:
        print("NMERROR " + json.dumps({"code": "memory", "message": "out of memory"}))
        return 4


if __name__ == "__main__":
    sys.exit(main())
