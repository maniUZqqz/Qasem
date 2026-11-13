#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-angle video from ONE camera: the pure math (agent 2.11, feature «چندزاویه»).

Nothing in this file touches a video, a model or the network - it is numpy + the standard library only, so the same file
runs (and is unit-tested) on the site, on the node's agent Python and inside the node's engine environment
(multiangle_engine.py does the pixels). The site imports it from the `processing` folder (services/editing/multiangle.py),
so there is ONE copy of every rule.

What lives here
  1. virtual cameras      shot sizes (wide / medium / close / two-shot / over-the-shoulder), where to put the subject
                          (eye line on the upper third, lead room in front of a face that looks sideways), a camera operator
                          model (dead zone + look-ahead + critically damped spring, velocity limit, subtle handheld),
                          crop windows -> affine matrices, an «is the source big enough for this close-up» report.
  2. the auto-edit        pauses and beats found in the sound -> where a cut may fall -> which angle comes next
                          (never two almost-equal sizes in a row, an establishing wide first, close-ups on emphasis).
  3. subject tracking     a small IoU tracker that keeps ids across detections and fills the gaps.
  4. 2.5D camera moves    one image + a depth map -> dolly / truck / crane / orbit: camera poses, the pinhole projection,
                          a z-buffered forward splat that gives a BACKWARD displacement map, background-biased hole filling,
                          an edge-aware (guided) depth filter and a temporal depth stabiliser.

Coordinates: crop windows are (cx, cy, ch) in fractions of the ACTIVE source area (the picture without black bars): the
window's height is `ch` of the source height, its width follows the output aspect: cw = ch * out_aspect / src_aspect.
"""
from __future__ import annotations

import math
import random

import numpy as np

VERSION = "1.0"

# ───────────────────────────────────────────────────────────── presets

#: tier = how close the shot looks (the cut planner never puts two near-equal tiers next to each other = no jump cut)
ANGLES = {
    "wide": {"label": "نمای باز", "tier": 0.0, "subjects": 1},
    "medium": {"label": "نمای متوسط", "tier": 1.0, "subjects": 1},
    "close": {"label": "نمای نزدیک", "tier": 2.0, "subjects": 1},
    "two_shot": {"label": "دو نفره", "tier": 0.6, "subjects": 2},
    "over_shoulder": {"label": "از روی شانه", "tier": 1.6, "subjects": 2},
}
ANGLE_ORDER = ("wide", "medium", "close", "two_shot", "over_shoulder")

#: output formats: key -> (w, h) ratio; "source" keeps the picture's own shape
FORMATS = {"source": None, "reel": (9, 16), "feed": (4, 5), "square": (1, 1), "wide": (16, 9)}

#: head heights that a shot shows (a "medium" is roughly waist-up, a "close-up" head and shoulders)
FACE_MULT = {"medium": 5.4, "close": 2.9, "over_shoulder": 3.3}
#: how the virtual operator behaves per shot: spring speed (1/s) for x, y, zoom; the dead zone (fraction of the window)
#: in which he does not bother; the top speed (windows per second); how much handheld wobble the shot gets
CAMERA = {
    "wide": {"omega": (1.6, 1.6, 1.1), "dead": (0.07, 0.07, 0.05), "vmax": (0.20, 0.20, 0.35), "wobble": 0.6, "lookahead": 0.35},
    "two_shot": {"omega": (1.9, 1.9, 1.3), "dead": (0.06, 0.06, 0.05), "vmax": (0.24, 0.24, 0.40), "wobble": 0.7, "lookahead": 0.35},
    "medium": {"omega": (2.6, 2.6, 1.6), "dead": (0.06, 0.05, 0.05), "vmax": (0.40, 0.40, 0.50), "wobble": 1.0, "lookahead": 0.30},
    "over_shoulder": {"omega": (2.8, 2.8, 1.7), "dead": (0.05, 0.05, 0.05), "vmax": (0.45, 0.45, 0.55), "wobble": 1.1, "lookahead": 0.28},
    "close": {"omega": (3.2, 3.2, 2.0), "dead": (0.05, 0.04, 0.05), "vmax": (0.55, 0.55, 0.60), "wobble": 1.3, "lookahead": 0.25},
}
#: the up-scaling a crop may need before we say so (1.0 = every output pixel comes from a source pixel)
UPSCALE_SOFT = 1.35
UPSCALE_HARD = 2.0


# ───────────────────────────────────────────────────────────── small helpers

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def ease_in_out(u):
    """Smoothstep: zero speed at both ends (a camera move that starts and stops softly)."""
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def ease_in_out_sine(u):
    u = np.clip(u, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def ease_out_cubic(u):
    u = np.clip(u, 0.0, 1.0)
    return 1.0 - (1.0 - u) ** 3


def ease_linear(u):
    return np.clip(u, 0.0, 1.0)


EASINGS = {"inout": ease_in_out, "sine": ease_in_out_sine, "out": ease_out_cubic, "linear": ease_linear}


def out_aspect_for(fmt, src_aspect):
    """Output width/height for a format key (`source` = the picture's own aspect)."""
    ratio = FORMATS.get(fmt)
    if not ratio:
        return float(src_aspect)
    return ratio[0] / float(ratio[1])


def max_window_height(src_aspect, out_aspect):
    """Tallest crop (fraction of the source height) whose width still fits in the source."""
    return float(min(1.0, src_aspect / out_aspect))


def window_width(ch, src_aspect, out_aspect):
    return ch * out_aspect / src_aspect


def clamp_window(cx, cy, ch, src_aspect, out_aspect, margin=0.0, min_ch=0.0):
    """Keep a crop window inside the source (numpy arrays or floats). Returns (cx, cy, ch) with the window inside
    [margin, 1 - margin] on both axes; `min_ch` stops a zoom from going past what the source's pixels can give."""
    chm = max_window_height(src_aspect, out_aspect) * (1.0 - 2.0 * margin)
    ch = np.clip(ch, min(min_ch, chm), chm)
    cw = window_width(ch, src_aspect, out_aspect)
    cx = np.clip(cx, margin + cw / 2.0, 1.0 - margin - cw / 2.0)
    cy = np.clip(cy, margin + ch / 2.0, 1.0 - margin - ch / 2.0)
    return cx, cy, ch


def window_to_affine(src_w, src_h, cx, cy, ch, roll_deg, out_w, out_h, src_aspect=None):
    """2x3 matrix (for cv2.warpAffine) that maps SOURCE pixels to OUTPUT pixels for the window (cx, cy, ch) rolled by
    `roll_deg` (positive = clockwise on screen). The window centre lands on the output centre, the window's height on the
    output height; its width follows the output shape (so the picture is never stretched)."""
    crop_h = ch * src_h
    scale = out_h / crop_h
    a = math.radians(roll_deg)
    c, s = math.cos(a) * scale, math.sin(a) * scale
    px, py = cx * src_w, cy * src_h
    # x' = c (x - px) + s (y - py) + out_w/2 ; y' = -s (x - px) + c (y - py) + out_h/2
    return np.array([[c, s, out_w / 2.0 - c * px - s * py], [-s, c, out_h / 2.0 + s * px - c * py]], dtype=np.float64)


def apply_affine(m, x, y):
    return m[0, 0] * x + m[0, 1] * y + m[0, 2], m[1, 0] * x + m[1, 1] * y + m[1, 2]


# ───────────────────────────────────────────────────────────── series helpers (tracking, smoothing)

def median_filter(x, k):
    """Running median with an odd window `k` (edges repeat). Kills one-frame detector glitches."""
    x = np.asarray(x, dtype=np.float64)
    if k <= 1 or len(x) < 3:
        return x.copy()
    k += 1 - k % 2
    pad = k // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(xp, k)
    return np.median(win, axis=1)


def fill_gaps(x, max_gap=None, hold=None):
    """Linear interpolation over NaN runs (at most `max_gap` samples long; longer runs and the ends are held for `hold`
    samples from the nearest value and stay NaN beyond that). Returns a new array."""
    x = np.asarray(x, dtype=np.float64).copy()
    n = len(x)
    good = ~np.isnan(x)
    if not good.any():
        return x
    idx = np.arange(n)
    out = x.copy()
    gi = idx[good]
    # interpolate inside
    i = 0
    while i < n:
        if good[i]:
            i += 1
            continue
        j = i
        while j < n and not good[j]:
            j += 1
        if i > 0 and j < n and (max_gap is None or j - i <= max_gap):
            out[i:j] = np.interp(idx[i:j], [i - 1, j], [x[i - 1], x[j]])
        i = j
    # hold the ends
    first, last = gi[0], gi[-1]
    h = n if hold is None else int(hold)
    for k in range(first):
        if first - k <= h:
            out[k] = x[first]
    for k in range(last + 1, n):
        if k - last <= h:
            out[k] = x[last]
    return out


def iou(a, b):
    """Intersection over union of two (x, y, w, h) boxes."""
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 1e-12 else 0.0


def box_center(b):
    return b[0] + b[2] / 2.0, b[1] + b[3] / 2.0


class Tracker:
    """Keeps subject ids across sampled frames. `update(t_index, detections)` takes dicts {"box": (x,y,w,h), "kind":
    "person"|"face", "score", "yaw"?} in source fractions; faces are matched to the person whose upper half holds them.
    `tracks()` -> list of {"id", "kind", "boxes": (n,4) array with NaN where unseen, "faces": (n,4), "yaw": (n,)}."""

    def __init__(self, n, max_miss=6, iou_min=0.08, dist_max=0.35):
        self.n = n
        self.max_miss = max_miss
        self.iou_min = iou_min
        self.dist_max = dist_max
        self._live = []          # dicts: id, box, miss, kind, rows
        self._done = []
        self._next = 1

    def _new(self, i, det):
        t = {"id": self._next, "box": tuple(det["box"]), "miss": 0, "kind": det.get("kind", "person"),
             "boxes": np.full((self.n, 4), np.nan), "faces": np.full((self.n, 4), np.nan), "yaw": np.full(self.n, np.nan),
             "score": 0.0, "hits": 0}
        self._next += 1
        self._put(t, i, det)
        self._live.append(t)

    def _put(self, t, i, det):
        b = det["box"]
        if det.get("kind") == "face":
            t["faces"][i] = b
            if det.get("yaw") is not None:
                t["yaw"][i] = det["yaw"]
            if np.isnan(t["boxes"][i]).any():
                t["boxes"][i] = _face_to_body(b)
                t["box"] = tuple(t["boxes"][i])
        else:
            t["boxes"][i] = b
            t["box"] = tuple(b)
        t["miss"] = 0
        t["hits"] += 1
        t["score"] += float(det.get("score", 0.5))

    def update(self, i, dets):
        persons = [d for d in dets if d.get("kind") != "face"]
        faces = [d for d in dets if d.get("kind") == "face"]
        pairs = []
        for ti, t in enumerate(self._live):
            for di, d in enumerate(persons):
                v = iou(t["box"], d["box"])
                cx0, cy0 = box_center(t["box"])
                cx1, cy1 = box_center(d["box"])
                dist = math.hypot(cx0 - cx1, cy0 - cy1)
                if v >= self.iou_min or dist <= self.dist_max * max(t["box"][2], t["box"][3], 0.1):
                    pairs.append((v - 0.25 * dist, ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for _s, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            self._put(self._live[ti], i, persons[di])
        for di, d in enumerate(persons):
            if di not in used_d:
                self._new(i, d)
        # faces: to the person (live, seen now) whose upper 60 % holds the face centre, else to a face-only subject
        for d in faces:
            fx, fy = box_center(d["box"])
            best, best_d = None, 1e9
            for t in self._live:
                bx = t["boxes"][i]
                if np.isnan(bx).any():
                    continue
                if bx[0] <= fx <= bx[0] + bx[2] and bx[1] - 0.05 <= fy <= bx[1] + 0.6 * bx[3]:
                    dist = abs(fx - (bx[0] + bx[2] / 2.0))
                    if dist < best_d and np.isnan(t["faces"][i]).all():
                        best, best_d = t, dist
            if best is None:                       # no person box holds it: a face-only subject (match by face/box overlap)
                for t in self._live:
                    if t["miss"] > 0 or not np.isnan(t["faces"][i]).all():
                        continue
                    ref = t["box"]
                    if iou(ref, _face_to_body(d["box"])) > 0.1 or iou(ref, d["box"]) > 0.1:
                        best = t
                        break
            if best is not None:
                self._put(best, i, d)
            else:
                self._new(i, d)
        # age everything that was not seen now
        for t in list(self._live):
            if np.isnan(t["boxes"][i]).any():
                t["miss"] += 1
                if t["miss"] > self.max_miss:
                    self._live.remove(t)
                    self._done.append(t)

    def tracks(self, min_hits=2):
        out = []
        for t in self._done + self._live:
            if t["hits"] < min_hits:
                continue
            out.append({"id": t["id"], "kind": "person" if not np.isnan(t["faces"]).all() or t["kind"] == "person" else "face",
                        "boxes": t["boxes"], "faces": t["faces"], "yaw": t["yaw"], "hits": t["hits"], "score": t["score"]})
        return out


def _face_to_body(f):
    """A rough upper-body box from a face box (used when only the face is found)."""
    x, y, w, h = f
    bw, bh = w * 2.6, h * 5.2
    return (x + w / 2.0 - bw / 2.0, y - 0.25 * h, bw, bh)


def rank_subjects(tracks, n):
    """Order tracks by importance: how long they are seen x how big they are. Returns the same dicts with `coverage`
    (share of samples seen) and `size` (median box height), best first."""
    ranked = []
    for t in tracks:
        seen = ~np.isnan(t["boxes"][:, 0])
        if not seen.any():
            continue
        cov = float(seen.sum()) / max(1, n)
        size = float(np.nanmedian(t["boxes"][seen, 3]))
        ranked.append({**t, "coverage": round(cov, 3), "size": round(size, 3), "rank": cov * (0.4 + size)})
    ranked.sort(key=lambda r: r["rank"], reverse=True)
    return ranked


# ───────────────────────────────────────────────────────────── framing: where does each virtual camera look

def _anatomy(subj):
    """(face_h, eye_x, eye_y, head_top) of a subject dict {"box", "face", "yaw"} in source fractions. A detector's face box starts
    at the brows, so the hair reaches about half a face height above it."""
    face, box = subj.get("face"), subj.get("box")
    if face is not None and not _nan(face):
        fx, fy, fw, fh = face
        top = fy - 0.45 * fh
        if box is not None and not _nan(box):
            top = min(top, box[1]) if box[1] > fy - 1.2 * fh else top
        return fh, fx + fw / 2.0, fy + 0.40 * fh, top
    if box is None or _nan(box):
        return 0.12, 0.5, 0.3, 0.2
    bx, by, bw, bh = box
    upper = (bw / max(bh, 1e-6)) > 0.7              # a box that is wide for its height = head and torso at a desk
    fh = bh * (0.20 if upper else 0.14)
    return fh, bx + bw / 2.0, by + 0.04 * bh + 0.40 * fh, by


def _nan(b):
    return any(v is None or (isinstance(v, float) and math.isnan(v)) for v in b)


def frame_for(shot, subj, src_aspect, out_aspect, subj2=None, side=0.0):
    """Where should the virtual camera `shot` look? -> (cx, cy, ch) in source fractions, BEFORE smoothing/clamping.

    wide      the whole active picture (cropped to the output shape; follows the subject sideways when it must crop)
    medium    waist-up: ~5.4 head heights, eye line on the upper third, lead room in front of a face that looks sideways
    close     head and shoulders: ~2.9 head heights, same rules
    two_shot  both subjects with air around them (needs `subj2`)
    over_shoulder   the first subject on the far third with the second one's shoulder entering the frame (needs `subj2`)
    `subj` None = no subject known: the shot becomes a plain digital zoom on the centre."""
    chm = max_window_height(src_aspect, out_aspect)
    if subj is None:
        ch = {"wide": 1.0, "medium": 0.72, "close": 0.52, "two_shot": 0.9, "over_shoulder": 0.6}.get(shot, 1.0) * chm
        return 0.5, 0.5, ch
    fh, ex, ey, top = _anatomy(subj)
    yaw = clamp(float(subj.get("yaw") or 0.0), -1.0, 1.0)
    box = subj.get("box")
    if shot == "wide":
        cx = 0.5 if window_width(chm, src_aspect, out_aspect) >= 0.999 else ex
        return cx, 0.5, chm
    if shot in ("medium", "close"):
        ch = clamp(FACE_MULT[shot] * fh, 0.16 * chm, 0.96 * chm if shot == "medium" else 0.62 * chm)
        if shot == "medium" and box is not None and not _nan(box):
            ch = min(ch, max(box[3] * 1.04, 0.3 * chm))      # never wider than the body he fills
        cw = window_width(ch, src_aspect, out_aspect)
        cx = ex + (0.16 * yaw + side) * cw
        cy = ey + (0.5 - 0.37) * ch
        cy = min(cy, top - 0.05 * ch + 0.5 * ch)           # headroom: never cut the top of the head off
        return cx, cy, ch
    if subj2 is None:
        return frame_for("medium", subj, src_aspect, out_aspect)
    fh2, ex2, ey2, top2 = _anatomy(subj2)
    if shot == "two_shot":
        x0 = min(ex - 1.2 * fh, ex2 - 1.2 * fh2)
        x1 = max(ex + 1.2 * fh, ex2 + 1.2 * fh2)
        top = min(ey - 1.4 * fh, ey2 - 1.4 * fh2)
        bot = max(ey + 3.4 * fh, ey2 + 3.4 * fh2)
        ch_need = max((bot - top), (x1 - x0) * src_aspect / out_aspect) * 1.12
        ch = clamp(ch_need, 0.3 * chm, chm)
        return (x0 + x1) / 2.0, top + 0.5 * (bot - top) + 0.02, ch
    # over the shoulder: subject 1 sits on the third far from subject 2
    ch = clamp(FACE_MULT["over_shoulder"] * fh, 0.2 * chm, 0.7 * chm)
    cw = window_width(ch, src_aspect, out_aspect)
    direction = -1.0 if ex2 < ex else 1.0              # where the second person is, seen from the first
    cx = ex + 0.17 * cw * direction                    # he sits on the far third: the shoulder of the other one enters on the near side
    cy = min(ey + (0.5 - 0.37) * ch, top - 0.05 * ch + 0.5 * ch)
    return cx, cy, ch


# ───────────────────────────────────────────────────────────── the virtual camera operator

def cd_step(x, v, target, omega, dt):
    """Exact one-step solution of a critically damped spring (no overshoot, stable for any dt)."""
    e = x - target
    ex = math.exp(-omega * dt)
    tmp = (v + omega * e) * dt
    return target + (e + tmp) * ex, (v - omega * tmp) * ex


def follow(times, targets, n, fps, params):
    """Camera path for one shot. `times` (m,) seconds of the target samples, `targets` (m, 3) = (cx, cy, ch) wanted at each
    sample. Returns (n, 3) = (cx, cy, ch) per output frame.

    Behaviour of the virtual operator: he looks `lookahead` seconds ahead (so he leads the subject, never trails it), does
    nothing while the framing is within the dead zone (a steady shot is a steady shot), and when it is not he glides to the
    wanted framing with a critically damped spring - eased start, eased stop, no overshoot - never faster than `vmax`
    (windows per second). Zoom is smoothed in log space so a zoom in and a zoom out feel equal."""
    times = np.asarray(times, dtype=np.float64)
    targets = np.asarray(targets, dtype=np.float64)
    omega, dead, vmax = params["omega"], params["dead"], params["vmax"]
    look = params.get("lookahead", 0.3)
    dt = 1.0 / fps
    t_out = np.arange(n) * dt + look
    want = np.empty((n, 3))
    for k in range(3):
        col = targets[:, k] if k < 2 else np.log(np.maximum(targets[:, 2], 1e-4))
        want[:, k] = np.interp(t_out, times, col)
    state = want[0].copy()
    vel = np.zeros(3)
    path = np.empty((n, 3))
    moving = False
    lo_f = params.get("settle", 0.30)
    for i in range(n):
        cw = window_width(math.exp(state[2]), params.get("src_aspect", 1.0), params.get("out_aspect", 1.0))
        scale = (cw, math.exp(state[2]), 1.0)
        err = want[i] - state
        rel = [abs(err[k]) / scale[k] for k in range(3)]
        hi = any(rel[k] > dead[k] for k in range(3))
        lo = all(rel[k] < dead[k] * lo_f for k in range(3))
        if not moving and hi:
            moving = True
        elif moving and lo:
            moving = False
        for k in range(3):
            goal = want[i, k] if moving else state[k]
            nx, nv = cd_step(state[k], vel[k], goal, omega[k], dt)
            cap = vmax[k] * scale[k]
            step = nx - state[k]
            if abs(step) > cap * dt:
                nx = state[k] + math.copysign(cap * dt, step)
                nv = math.copysign(cap, step)
            state[k], vel[k] = nx, nv
        path[i] = state
    path[:, 2] = np.exp(path[:, 2])
    return path


def handheld(n, fps, amount, seed=1):
    """Subtle hand-held wobble: (dx, dy, roll_deg) per frame. dx, dy are fractions of the WINDOW size (a few thousandths),
    roll is under a quarter of a degree. Built from three slow sinusoids with seeded phases - no random jitter, so the
    result is smooth and the same for the same seed."""
    rng = random.Random(seed)
    t = np.arange(n) / float(fps)
    comps = ((0.31, 1.0), (0.77, 0.55), (1.63, 0.25))
    out = []
    for amp_scale in (0.0042, 0.0034, 0.20):
        acc = np.zeros(n)
        for f, a in comps:
            acc += a * np.sin(2 * math.pi * f * t * rng.uniform(0.85, 1.15) + rng.uniform(0, 2 * math.pi))
        out.append(acc / 1.8 * amp_scale * amount)
    return out[0], out[1], out[2]


def build_path(shot, times, targets, n, fps, src_aspect, out_aspect, handheld_amount=0.35, seed=1, min_ch=0.0, push=None):
    """The full path of one virtual camera -> {"cx","cy","ch","roll"} arrays of length n (every window inside the picture)."""
    params = dict(CAMERA[shot])
    params["src_aspect"], params["out_aspect"] = src_aspect, out_aspect
    t = np.asarray(times, dtype=np.float64)
    tg = np.asarray(targets, dtype=np.float64).copy()
    if len(t) == 0:
        tg = np.array([[0.5, 0.5, max_window_height(src_aspect, out_aspect)]])
        t = np.array([0.0])
    for k in range(3):                       # one-sample glitches out
        tg[:, k] = median_filter(tg[:, k], 5)
    if push:                                  # a very slow push-in / pull-out over the whole shot (wide shots feel alive)
        tg[:, 2] = tg[:, 2] * np.interp(t, [t[0], max(t[-1], t[0] + 1e-3)], [1.0, 1.0 - push])
    path = follow(t, tg, n, fps, params)
    dx, dy, roll = handheld(n, fps, handheld_amount * params["wobble"], seed)
    margin = 0.012 * handheld_amount * params["wobble"]
    ch = path[:, 2]
    cw = window_width(ch, src_aspect, out_aspect)
    cx = path[:, 0] + dx * cw
    cy = path[:, 1] + dy * ch
    cx, cy, ch = clamp_window(cx, cy, ch, src_aspect, out_aspect, margin=margin, min_ch=min_ch)
    return {"cx": cx, "cy": cy, "ch": ch, "roll": roll}


# ───────────────────────────────────────────────────────────── quality report

def upscale_stats(ch, src_h_px, out_h_px):
    """How many OUTPUT pixels each SOURCE pixel has to cover (1.0 = none made up): {"median","max","share_over_soft"}."""
    ch = np.asarray(ch, dtype=np.float64)
    f = out_h_px / np.maximum(ch * src_h_px, 1.0)
    return {"median": float(np.median(f)), "max": float(np.max(f)), "share_over_soft": float(np.mean(f > UPSCALE_SOFT))}


def min_window_height(src_h_px, out_h_px, max_upscale=UPSCALE_HARD):
    """Smallest crop height (fraction) that does not need more than `max_upscale` up-scaling."""
    return float(out_h_px / (max_upscale * src_h_px))


def pick_output_size(src_active_w, src_active_h, out_aspect, req_h=None, max_h=1080):
    """Output (w, h) - both even. The WIDE shot is the sharpest the source can give, so the output never has more rows than
    the wide crop has (no made-up pixels in the base shot); `req_h` caps it further."""
    chm = max_window_height(src_active_w / src_active_h, out_aspect)
    wide_h = chm * src_active_h
    h = min(float(req_h or max_h), float(max_h), wide_h)
    h = max(2, int(h) // 2 * 2)
    w = max(2, int(round(h * out_aspect)) // 2 * 2)
    return w, h


def warnings_for(angle_stats, subject_mode, subjects, skipped, boundary_kinds, duration):
    """Structured warnings (the site writes the Persian text): a list of {"code", ...}."""
    out = []
    for key, st in angle_stats.items():
        if st["max"] > UPSCALE_HARD:
            out.append({"code": "upscale_hard", "angle": key, "factor": round(st["max"], 2)})
        elif st["median"] > UPSCALE_SOFT:
            out.append({"code": "upscale_soft", "angle": key, "factor": round(st["median"], 2)})
    if subject_mode in ("motion", "center"):
        out.append({"code": "no_subject", "mode": subject_mode})
    for key, why in skipped.items():
        out.append({"code": "angle_skipped", "angle": key, "why": why})
    if not boundary_kinds:
        out.append({"code": "no_cut_points"})
    if duration < 4.0:
        out.append({"code": "too_short"})
    return out


# ───────────────────────────────────────────────────────────── angles that are possible for THIS footage

def available_angles(requested, subjects, subject_mode):
    """-> (active list in ANGLE_ORDER, {skipped angle: reason}). Two-person angles need a second subject that is seen often."""
    active, skipped = [], {}
    second = len(subjects) >= 2 and subjects[1]["coverage"] >= 0.30
    for key in ANGLE_ORDER:
        if key not in requested:
            continue
        if ANGLES[key]["subjects"] == 2 and not second:
            skipped[key] = "one_subject"
            continue
        active.append(key)
    if not active:
        active = ["wide"]
    return active, skipped


# ───────────────────────────────────────────────────────────── sound: pauses and beats

def energy_db(pcm, sr, hop=0.02):
    """Short-time RMS in dB (one value per `hop` seconds) -> (env_db, hop)."""
    x = np.asarray(pcm, dtype=np.float32)
    h = max(1, int(sr * hop))
    n = (len(x) // h) * h
    if n == 0:
        return np.zeros(0), hop
    rms = np.sqrt(np.mean(x[:n].reshape(-1, h).astype(np.float64) ** 2, axis=1) + 1e-12)
    return 20.0 * np.log10(rms + 1e-9), hop


def pause_boundaries(env_db, hop, min_pause=0.30, below=22.0, floor=-62.0):
    """Quiet stretches between phrases -> [{"t": middle, "w": 0..1, "kind": "pause", "len": seconds}].
    Quiet = more than `below` dB under the speech level (90th percentile of the loudness), and under `floor`+.. always."""
    env = np.asarray(env_db, dtype=np.float64)
    if len(env) < 10:
        return []
    ref = float(np.percentile(env, 90))
    if ref < floor + 8:                                        # silence all the way: nothing to cut on
        return []
    thr = max(ref - below, floor)
    quiet = env < thr
    out = []
    i, n = 0, len(env)
    while i < n:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < n and quiet[j]:
            j += 1
        length = (j - i) * hop
        if length >= min_pause and i > 0 and j < n:            # not the very start / end of the file
            out.append({"t": round((i + j) / 2.0 * hop, 3), "w": round(min(1.0, 0.45 + length / 1.2), 3), "kind": "pause",
                        "len": round(length, 3)})
        i = j
    return out


def beat_grid(pcm, sr, bpm_range=(70.0, 180.0)):
    """Tempo and beat times of music in a clip: {"bpm", "confidence", "beats": [t...]} (confidence 0..1; below ~0.3 there is no
    steady beat). Spectral-flux onsets, tempo by autocorrelation with a gentle preference for 90-140 BPM, phase by comb."""
    x = np.asarray(pcm, dtype=np.float32)
    if len(x) < sr * 3:
        return {"bpm": 0.0, "confidence": 0.0, "beats": []}
    n_fft, hop = 1024, 256
    win = np.hanning(n_fft).astype(np.float32)
    frames = (len(x) - n_fft) // hop + 1
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    mag = np.log1p(spec * 8.0)
    flux = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    k = max(3, int(0.4 * sr / hop))
    local = np.convolve(flux, np.ones(k) / k, mode="same")
    env = np.maximum(0.0, flux - local)
    if env.std() < 1e-9:
        return {"bpm": 0.0, "confidence": 0.0, "beats": []}
    env = (env - env.mean()) / (env.std() + 1e-9)
    fr = sr / float(hop)
    lag_lo, lag_hi = int(fr * 60.0 / bpm_range[1]), int(fr * 60.0 / bpm_range[0])
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    if lag_hi >= len(ac) or lag_hi <= lag_lo:
        return {"bpm": 0.0, "confidence": 0.0, "beats": []}
    lags = np.arange(lag_lo, lag_hi + 1)
    bpms = 60.0 * fr / lags
    prior = np.exp(-0.5 * ((np.log2(bpms / 115.0)) / 0.55) ** 2)
    score = ac[lag_lo:lag_hi + 1] * (0.6 + 0.4 * prior)
    best = int(np.argmax(score))
    lag = float(lags[best])
    # refine the period with a parabola through the autocorrelation peak
    if 0 < best < len(lags) - 1:
        a, b, c = score[best - 1], score[best], score[best + 1]
        den = a - 2 * b + c
        if abs(den) > 1e-12:
            lag += 0.5 * (a - c) / den
    li = int(lags[best])
    r = float(ac[max(0, li - 1):li + 2].max() / (ac[0] + 1e-9))               # normalised autocorrelation at the beat period
    conf = float(np.clip((r - 0.10) / 0.45, 0.0, 1.0))
    period = lag
    # phase: the offset whose comb of period-spaced frames collects the most onset energy
    best_off, best_val = 0, -1e18
    for off in range(int(period)):
        pos = np.arange(off, len(env), period)
        v = float(env[np.round(pos).astype(int).clip(0, len(env) - 1)].sum())
        if v > best_val:
            best_val, best_off = v, off
    beats = (best_off + np.arange(0, (len(env) - best_off) / period) * period) / fr
    return {"bpm": round(60.0 * fr / period, 2), "confidence": round(conf, 3), "beats": [round(float(b), 3) for b in beats]}


def boundaries_from_sentences(sentences, duration):
    """The site's transcript -> cut points in the gaps between sentences: [{"t","w","kind":"sentence"}]."""
    rows = sorted((float(s["start"]), float(s["end"])) for s in sentences or [] if s.get("end") is not None and float(s["end"]) > float(s["start"]))
    out = []
    for (a0, a1), (b0, _b1) in zip(rows, rows[1:]):
        t = (a1 + b0) / 2.0 if b0 > a1 else a1
        if 0.4 < t < duration - 0.4:
            out.append({"t": round(t, 3), "w": 1.0, "kind": "sentence", "len": round(max(0.0, b0 - a1), 3)})
    return out


def merge_boundaries(*groups, min_gap=0.25):
    """One sorted list of cut points; two points closer than `min_gap` keep the stronger one."""
    allb = sorted((dict(b) for g in groups for b in g), key=lambda b: b["t"])
    out = []
    for b in allb:
        if out and b["t"] - out[-1]["t"] < min_gap:
            if b["w"] > out[-1]["w"]:
                out[-1] = b
            continue
        out.append(b)
    return out


# ───────────────────────────────────────────────────────────── the auto-edit

PACE = {"slow": (3.0, 5.5, 9.0), "medium": (2.0, 3.8, 6.5), "fast": (1.2, 2.2, 4.0)}
#: two shots whose size differs by less than this look like a jump cut when they follow each other
MIN_TIER_STEP = 0.85


def _snap(t, fps):
    return round(round(t * fps) / fps, 4)


def plan_cut_times(duration, boundaries, pace="medium", fps=30.0, energy=None, hop=0.02):
    """Where the cuts fall: -> [{"t", "reason": "pause"|"sentence"|"beat"|"forced"}]. A cut may only fall on a cut point
    (a pause between phrases, the gap between two sentences, a beat); when none is near enough a «forced» cut falls on the
    quietest moment around the wanted time. Shots are at least `min` and at most `max` seconds (see PACE)."""
    lo, pref, hi = PACE.get(pace, PACE["medium"])
    cuts = []
    t = 0.0
    pts = sorted(boundaries, key=lambda b: b["t"])
    desired = max(2, int(round(duration / pref)))
    guard = 0
    while guard < 10000:
        guard += 1
        remaining = duration - t
        if remaining < 2.0 * lo:                                   # no room for another shot of the minimum length
            break
        if remaining <= hi and len(cuts) >= desired - 1:
            break
        win_lo, win_hi = t + lo, min(t + hi, duration - lo)
        cand = [b for b in pts if win_lo <= b["t"] <= win_hi]
        if cand:
            def score(b):
                return b["w"] * 1.0 - abs(b["t"] - (t + pref)) / pref * 0.9 + (0.15 if b["kind"] == "sentence" else 0.0)
            pick = max(cand, key=score)
            cuts.append({"t": _snap(pick["t"], fps), "reason": pick["kind"]})
            t = pick["t"]
            continue
        want = min(max(t + pref, win_lo), win_hi)
        if energy is not None and len(energy):
            a, b = int(max(win_lo, want - 0.4) / hop), int(min(win_hi, want + 0.4) / hop)
            if b > a:
                want = (a + int(np.argmin(np.asarray(energy)[a:b]))) * hop
        cuts.append({"t": _snap(want, fps), "reason": "forced"})
        t = want
    return [c for c in cuts if 0.3 < c["t"] < duration - 0.3]


def assign_angles(duration, cut_times, angles, energy=None, hop=0.02, seed=7):
    """Which angle plays in every shot -> list of {"t0","t1","angle","reason"}.

    Rules: an establishing wide first (or the loosest shot there is); never the same angle twice in a row; the new shot must
    differ in size by at least MIN_TIER_STEP from the one before (no jump cuts) - relaxed only when nothing else exists;
    louder, more energetic shots lean towards closer angles; every angle is used once when there are enough shots; the last
    shot is never a close-up."""
    rng = random.Random(seed)
    keys = [a["key"] if isinstance(a, dict) else a for a in angles]
    tier = {k: ANGLES[k]["tier"] for k in keys}
    edges = [0.0] + [c["t"] for c in cut_times] + [duration]
    segs = [{"t0": edges[i], "t1": edges[i + 1], "reason": (cut_times[i - 1]["reason"] if i else "start")} for i in range(len(edges) - 1)]
    if len(keys) == 1:
        for s in segs:
            s["angle"] = keys[0]
        return segs
    # loudness of each shot relative to the clip (0..1) -> "emphasis"
    emph = []
    if energy is not None and len(energy):
        e = np.asarray(energy, dtype=np.float64)
        means = []
        for s in segs:
            a, b = int(s["t0"] / hop), max(int(s["t0"] / hop) + 1, int(s["t1"] / hop))
            means.append(float(np.mean(e[a:b])) if b <= len(e) else float(np.mean(e[a:])) if a < len(e) else -90.0)
        lo_v, hi_v = min(means), max(means)
        emph = [(m - lo_v) / (hi_v - lo_v) if hi_v > lo_v else 0.5 for m in means]
    else:
        emph = [0.5] * len(segs)
    used = {k: 0 for k in keys}
    prev = None
    run = 0
    loosest = min(keys, key=lambda k: tier[k])
    for i, s in enumerate(segs):
        last = i == len(segs) - 1
        pool = [k for k in keys if k != prev]
        strict = [k for k in pool if prev is None or abs(tier[k] - tier[prev]) >= MIN_TIER_STEP]
        pool = strict or pool
        if last and len(segs) > 2:
            soft = [k for k in pool if tier[k] <= 1.0]
            pool = soft or pool
        if i == 0:
            pick = loosest if loosest in pool else pool[0]
        else:
            want_tier = emph[i] * max(tier.values())
            def score(k):
                novelty = 1.0 / (1 + used[k])
                return novelty * 1.2 - abs(tier[k] - want_tier) * 0.35 + rng.random() * 0.05
            pick = max(pool, key=score)
        run = run + 1 if pick == prev else 1
        s["angle"] = pick
        used[pick] += 1
        prev = pick
    # make sure every angle is used when there are enough shots (swap a repeated one for an unused one where legal)
    if len(segs) >= len(keys):
        for k in keys:
            if used[k]:
                continue
            for j in range(1, len(segs) - 1):
                cur = segs[j]["angle"]
                if used[cur] < 2:
                    continue
                ok_prev = abs(tier[k] - tier[segs[j - 1]["angle"]]) >= MIN_TIER_STEP and segs[j - 1]["angle"] != k
                ok_next = abs(tier[k] - tier[segs[j + 1]["angle"]]) >= MIN_TIER_STEP and segs[j + 1]["angle"] != k
                if ok_prev and ok_next:
                    used[cur] -= 1
                    segs[j]["angle"] = k
                    used[k] += 1
                    break
    return segs


def plan_edit(duration, angles, boundaries, pace="medium", fps=30.0, energy=None, hop=0.02, seed=7):
    """Cut times + angles in one call -> {"segments", "cuts" ([{"t","angle"}] with repeats merged), "quality"}."""
    keys = [a["key"] if isinstance(a, dict) else a for a in angles]
    if duration < 2.0 * PACE.get(pace, PACE["medium"])[0] or len(keys) < 2:
        segs = [{"t0": 0.0, "t1": float(duration), "angle": keys[0], "reason": "start"}]
        times = []
    else:
        times = plan_cut_times(duration, boundaries, pace, fps, energy, hop)
        segs = assign_angles(duration, times, keys, energy, hop, seed)
    cuts, prev = [], None
    for s in segs:
        if s["angle"] != prev:
            cuts.append({"t": round(s["t0"], 3), "angle": s["angle"]})
            prev = s["angle"]
    clean = sum(1 for t in times if t["reason"] != "forced")
    quality = {"segments": len(segs), "cuts_on_points": clean, "forced": len(times) - clean,
               "share_on_points": round(clean / len(times), 3) if times else 1.0,
               "angles_used": sorted({s["angle"] for s in segs})}
    return {"segments": [{**s, "t0": round(s["t0"], 3), "t1": round(s["t1"], 3)} for s in segs], "cuts": cuts, "quality": quality}


# ───────────────────────────────────────────────────────────── active picture area (black bars)

def active_area(gray_frames, threshold=14, min_share=0.02, pad=0):
    """The picture without black bars: `gray_frames` = list of 2-D uint8 arrays of the same size. -> (x0, y0, x1, y1) in pixels
    (x1/y1 exclusive). A column / row counts when more than `min_share` of its pixels in some frame exceed `threshold`."""
    peak_cols = None
    peak_rows = None
    for g in gray_frames:
        bright = g > threshold
        cols = bright.mean(axis=0)
        rows = bright.mean(axis=1)
        peak_cols = cols if peak_cols is None else np.maximum(peak_cols, cols)
        peak_rows = rows if peak_rows is None else np.maximum(peak_rows, rows)
    if peak_cols is None:
        return 0, 0, 1, 1
    xs = np.where(peak_cols > min_share)[0]
    ys = np.where(peak_rows > min_share)[0]
    h, w = len(peak_rows), len(peak_cols)
    if len(xs) == 0 or len(ys) == 0:
        return 0, 0, w, h
    x0, x1 = max(0, int(xs[0]) - pad), min(w, int(xs[-1]) + 1 + pad)
    y0, y1 = max(0, int(ys[0]) - pad), min(h, int(ys[-1]) + 1 + pad)
    # bars thinner than 2 % are not worth a crop
    if x0 < 0.02 * w:
        x0 = 0
    if y0 < 0.02 * h:
        y0 = 0
    if x1 > 0.98 * w:
        x1 = w
    if y1 > 0.98 * h:
        y1 = h
    return x0, y0, x1, y1


def spectral_residual_saliency(gray):
    """A cheap «what stands out» map (Hou & Zhang) for footage with no face or body: 2-D float array, 0..1."""
    g = np.asarray(gray, dtype=np.float32)
    f = np.fft.fft2(g)
    log_amp = np.log(np.abs(f) + 1e-6)
    phase = np.angle(f)
    k = 3
    pad = np.pad(log_amp, k // 2, mode="edge")
    avg = sum(pad[i:i + log_amp.shape[0], j:j + log_amp.shape[1]] for i in range(k) for j in range(k)) / (k * k)
    sr = log_amp - avg
    sal = np.abs(np.fft.ifft2(np.exp(sr + 1j * phase))) ** 2
    sal = (sal - sal.min()) / (np.ptp(sal) + 1e-9)
    return sal


# ═════════════════════════════════════════════════════════════ 2.5D camera moves
#
# One picture + a depth map -> a camera that really moves. The depth network gives RELATIVE nearness d in 0..1 (1 = nearest);
# we turn it into a depth Z (focus plane = 1), move a pinhole camera, project every pixel again and keep the nearest one per
# target pixel (z-buffer). What we want from that is a BACKWARD displacement map D (where, in the original picture, does
# each new pixel come from) - sampling with it is exact where the surface was seen and, where the new camera sees something
# that was hidden before (disocclusion), the hole is filled from the FARTHEST neighbour (the background), never the
# foreground that was in front: foreground smear is the artefact that makes 2.5D look cheap.

MOVES = {
    "dolly_in": {"label": "حرکت به جلو (دالی)", "kind": "dolly", "dir": +1},
    "dolly_out": {"label": "حرکت به عقب (دالی)", "kind": "dolly", "dir": -1},
    "truck_left": {"label": "حرکت به چپ", "kind": "truck", "dir": -1},
    "truck_right": {"label": "حرکت به راست", "kind": "truck", "dir": +1},
    "crane_up": {"label": "جرثقیل: بالا رفتن", "kind": "crane", "dir": +1},
    "crane_down": {"label": "جرثقیل: پایین آمدن", "kind": "crane", "dir": -1},
    "orbit_left": {"label": "چرخش دورِ سوژه به چپ", "kind": "orbit", "dir": -1},
    "orbit_right": {"label": "چرخش دورِ سوژه به راست", "kind": "orbit", "dir": +1},
    "push_parallax": {"label": "نزدیک شدن با پارالاکس", "kind": "push", "dir": +1},
}
MOVE_ORDER = tuple(MOVES)

#: peak camera travel for amount = 1 (units of the focus distance) and the orbit's peak angle in degrees
TRAVEL = {"dolly": 0.26, "truck": 0.075, "crane": 0.06, "push": 0.18}
ORBIT_DEG = 7.0
FOCAL = 0.95            # focal length in widths of the picture (~55 degrees across)


def depth_to_z(d, focus_d, relief=1.0, z_near=0.45, z_far=3.2):
    """Nearness map (0 far .. 1 near) -> depth with the focus plane at exactly 1.0. `relief` > 1 deepens the scene."""
    d = np.asarray(d, dtype=np.float32)
    qf, qn = 1.0 / z_far, 1.0 / z_near
    q = qf + d * relief * (qn - qf)
    qfocus = qf + float(focus_d) * relief * (qn - qf)
    return (qfocus / np.maximum(q, 1e-4)).astype(np.float32)


def camera_pose(move, u, amount=0.5):
    """Pose of the camera for a move at progress u (0..1, already eased): dict(c=(x,y,z), yaw, pitch, look_at_focus).
    Moves that would expose the picture's edges start (dolly_out) or are centred (truck, crane, orbit) so the first and last
    frame are never the least-covered one; the engine adds a safe zoom for the rest."""
    spec = MOVES[move]
    kind, sign = spec["kind"], spec["dir"]
    a = float(clamp(amount, 0.0, 1.0))
    u = np.asarray(u, dtype=np.float64)
    zero = np.zeros_like(u)
    if kind == "dolly":
        trav = TRAVEL["dolly"] * a
        z = trav * u if sign > 0 else trav * (u - 1.0)      # dolly out ends on the original framing: no exposed edges
        return {"c": (zero, zero, z), "yaw": zero, "pitch": zero}
    if kind == "push":
        trav = TRAVEL["push"] * a
        return {"c": (zero, zero, trav * u), "yaw": zero, "pitch": zero}
    if kind == "truck":
        x = TRAVEL["truck"] * a * sign * (2.0 * u - 1.0)
        return {"c": (x, zero, zero), "yaw": zero, "pitch": zero}
    if kind == "crane":
        y = -TRAVEL["crane"] * a * sign * (2.0 * u - 1.0)      # y down is positive in the picture: up = negative
        pitch = np.arctan2(-y, 1.0) * 0.8                       # keep looking at the subject while rising
        return {"c": (zero, y, zero), "yaw": zero, "pitch": pitch}
    ang = np.radians(ORBIT_DEG * a) * sign * (2.0 * u - 1.0)
    return {"c": (-np.sin(ang), zero, 1.0 - np.cos(ang)), "yaw": ang, "pitch": zero}


def _rot(yaw, pitch):
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    return ry @ rx


def project_flow(z, pose_c, yaw, pitch, f_px, cx=None, cy=None):
    """Move the camera and see where every pixel goes. `z` (H, W) depth (focus = 1), pose_c = (x, y, z) camera position in the
    ORIGINAL camera frame. -> (dx, dy, z_new): the pixel at (u, v) lands on (u + dx, v + dy) at depth z_new (<= 0 = behind)."""
    h, w = z.shape
    cx = (w - 1) / 2.0 if cx is None else cx
    cy = (h - 1) / 2.0 if cy is None else cy
    u = (np.arange(w, dtype=np.float32) - cx)[None, :]
    v = (np.arange(h, dtype=np.float32) - cy)[:, None]
    px = u * z / f_px
    py = v * z / f_px
    pz = z
    r = _rot(float(yaw), float(pitch))
    tx, ty, tz = (float(pose_c[0]), float(pose_c[1]), float(pose_c[2]))
    qx, qy, qz = px - tx, py - ty, pz - tz
    # P' = R^T (P - C)
    nx = r[0, 0] * qx + r[1, 0] * qy + r[2, 0] * qz
    ny = r[0, 1] * qx + r[1, 1] * qy + r[2, 1] * qz
    nz = r[0, 2] * qx + r[1, 2] * qy + r[2, 2] * qz
    safe = np.where(nz > 0.02, nz, 1.0)
    un = f_px * nx / safe
    vn = f_px * ny / safe
    return (un - u).astype(np.float32), (vn - v).astype(np.float32), nz.astype(np.float32)


def splat_backward(dx, dy, z_new, nearness):
    """Forward-splat every pixel (2x2 footprint, nearest wins) and return, for every NEW pixel, where it came from.

    -> (bx, by, filled): bx, by (H, W) = source - target offsets (so source = target + b), `filled` bool (False = a hole)."""
    h, w = dx.shape
    big = np.float32(1e9)
    xs = np.arange(w, dtype=np.float32)[None, :]
    ys = np.arange(h, dtype=np.float32)[:, None]
    tx = xs + dx
    ty = ys + dy
    valid = (z_new > 0.02) & np.isfinite(tx) & np.isfinite(ty)
    zbuf = np.full(h * w, big, dtype=np.float32)
    srcx = np.zeros(h * w, dtype=np.float32)
    srcy = np.zeros(h * w, dtype=np.float32)
    zflat = np.where(valid, z_new, big).ravel()
    order = np.argsort(-zflat, kind="stable")              # far first, near last: the near pixel's write wins
    sx_all = np.broadcast_to(xs, (h, w)).ravel()
    sy_all = np.broadcast_to(ys, (h, w)).ravel()
    tx_f, ty_f = tx.ravel(), ty.ravel()
    ok = valid.ravel()
    order = order[ok[order]]
    for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        ix = np.floor(tx_f[order]).astype(np.int64) + ox
        iy = np.floor(ty_f[order]).astype(np.int64) + oy
        inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        sel = order[inside]
        pos = (iy[inside] * w + ix[inside])
        # nearer than what is there already? (the previous footprint passes may hold a nearer pixel)
        zs = z_new.ravel()[sel]
        better = zs < zbuf[pos]
        # inside one pass the order is far->near, so for repeated positions the last write is the nearest
        pos_b, sel_b = pos[better], sel[better]
        zbuf[pos_b] = z_new.ravel()[sel_b]
        srcx[pos_b] = sx_all[sel_b]
        srcy[pos_b] = sy_all[sel_b]
    filled = (zbuf < big).reshape(h, w)
    bx = np.where(filled, srcx.reshape(h, w) - xs, 0.0).astype(np.float32)
    by = np.where(filled, srcy.reshape(h, w) - ys, 0.0).astype(np.float32)
    return bx, by, filled, zbuf.reshape(h, w)


def _scan_candidates(vals, have, axis, reverse):
    """For every cell the nearest cell that `have` something, looking along `axis` in one direction.
    -> (index_array_of_the_source_cell or -1)."""
    h, w = have.shape
    n = w if axis == 1 else h
    ar = np.arange(n)
    shape = (1, w) if axis == 1 else (h, 1)
    ar = ar.reshape(shape)
    if not reverse:
        idx = np.where(have, ar, -1)
        return np.maximum.accumulate(idx, axis=axis)
    idx = np.where(have, ar, 10 ** 9)
    flip = np.flip(idx, axis=axis)
    acc = np.minimum.accumulate(flip, axis=axis)
    out = np.flip(acc, axis=axis)
    return np.where(out >= 10 ** 9, -1, out)


def fill_holes_far(bx, by, z, filled, max_iter=60, axis_first=None, smooth=2):
    """Fill the holes of a displacement map from the FARTHEST valid neighbour (the largest depth), so the background - never the
    foreground in front of it - fills what the new camera uncovered. For every hole the nearest valid cell is looked up along the
    rows (axis 1) and the columns (axis 0), both ways; `axis_first` (the direction the camera moved: a hole opens along it) is
    tried first and the other axis only fills what is still empty. Of the candidates the farthest wins. What is still empty (no
    valid cell in line) is then filled from its 8 neighbours step by step. The DISPLACEMENT is copied, not the source position,
    so the background texture continues behind the hole instead of smearing one pixel; inside the filled area it is smoothed
    (`smooth` passes of a masked 5x5 mean) so neighbouring rows do not pick different candidates (a comb pattern).
    Returns (bx, by, still_empty_mask)."""
    bx, by, z = bx.copy(), by.copy(), z.copy()
    h, w = filled.shape
    have = filled.copy()
    if have.all():
        return bx, by, np.zeros_like(have)
    holes0 = ~have
    big = np.float32(1e9)
    zz = np.where(have, z, -big)
    rows = np.arange(h)[:, None]
    cols = np.arange(w)[None, :]
    axes_plan = [(1, 0)] if axis_first is None else [(axis_first,), (1 - axis_first,)]
    if axis_first is None:
        axes_plan = [(1, 0)]
    for axes in axes_plan:
        holes = ~have
        if not holes.any():
            break
        best_z = np.full((h, w), -big, dtype=np.float32)
        best_x = np.zeros((h, w), dtype=np.float32)
        best_y = np.zeros((h, w), dtype=np.float32)
        for axis in axes:
            for rev in (False, True):
                idx = _scan_candidates(z, have, axis, rev)
                ok = idx >= 0
                if axis == 1:
                    src_r, src_c = np.broadcast_to(rows, (h, w)), np.where(ok, idx, 0)
                else:
                    src_r, src_c = np.where(ok, idx, 0), np.broadcast_to(cols, (h, w))
                cz = np.where(ok, z[src_r, src_c], -big)
                take = holes & ok & (cz > best_z)
                best_z = np.where(take, cz, best_z)
                best_x = np.where(take, bx[src_r, src_c], best_x)
                best_y = np.where(take, by[src_r, src_c], best_y)
        got = holes & (best_z > -big / 2)
        bx = np.where(got, best_x, bx)
        by = np.where(got, best_y, by)
        zz = np.where(got, best_z, zz)
        have = have | got
    for _ in range(max_iter):
        if have.all():
            break
        bz = np.full_like(zz, -big)
        nx = np.zeros_like(bx)
        ny = np.zeros_like(by)
        for dyy, dxx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            sz = _shift(zz, dyy, dxx, -big)
            take = sz > bz
            bz = np.where(take, sz, bz)
            nx = np.where(take, _shift(bx, dyy, dxx, 0.0), nx)
            ny = np.where(take, _shift(by, dyy, dxx, 0.0), ny)
        upd = (~have) & (bz > -big / 2)
        if not upd.any():
            break
        bx = np.where(upd, nx, bx)
        by = np.where(upd, ny, by)
        zz = np.where(upd, bz, zz)
        have = have | upd
    if smooth:
        m = (holes0 & have).astype(np.float32)
        if m.any():
            for _ in range(smooth):
                den = box_filter(m, 2).astype(np.float32) + 1e-6
                bx_s = box_filter(bx * m, 2).astype(np.float32) / den
                by_s = box_filter(by * m, 2).astype(np.float32) / den
                bx = np.where(m > 0, bx_s, bx)
                by = np.where(m > 0, by_s, by)
    return bx, by, ~have


def _shift(a, dy, dx, fill):
    out = np.full_like(a, fill)
    h, w = a.shape
    ys, yd = (slice(max(0, -dy), h - max(0, dy)), slice(max(0, dy), h - max(0, -dy)))
    xs, xd = (slice(max(0, -dx), w - max(0, dx)), slice(max(0, dx), w - max(0, -dx)))
    out[yd, xd] = a[ys, xs]
    return out


def safe_zoom(dx, dy, nearness, pct=80.0, max_zoom=1.30):
    """How much the picture must be zoomed in so the move does not show the picture's edges: from the displacement of the
    NEARER pixels (the `pct`-th percentile of the displacement magnitude, per axis)."""
    h, w = dx.shape
    ax = float(np.percentile(np.abs(dx), pct)) / w
    ay = float(np.percentile(np.abs(dy), pct)) / h
    return float(clamp(1.0 + 2.0 * max(ax, ay), 1.0, max_zoom))


def move_progress(n, ease="inout"):
    """Eased progress 0..1 for n frames (first frame 0, last frame 1)."""
    u = np.linspace(0.0, 1.0, max(2, n))
    return EASINGS.get(ease, ease_in_out)(u)


# ───────────────────────────────────────────────────────────── depth clean-up

def box_filter(a, r):
    """Mean over a (2r+1) window with replicated borders, via a summed-area table (numpy only)."""
    a = np.asarray(a, dtype=np.float64)
    pad = np.pad(a, r, mode="edge")
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / float(k * k)


def guided_filter(guide, src, r=8, eps=1e-3):
    """Edge-aware smoothing of `src` (depth) steered by `guide` (grey image 0..1): the depth keeps its steps exactly where the
    picture has edges, so parallax does not tear a halo around a person. He et al., 2010."""
    g = np.asarray(guide, dtype=np.float64)
    p = np.asarray(src, dtype=np.float64)
    mg, mp = box_filter(g, r), box_filter(p, r)
    cov = box_filter(g * p, r) - mg * mp
    var = box_filter(g * g, r) - mg * mg
    a = cov / (var + eps)
    b = mp - a * mg
    return (box_filter(a, r) * g + box_filter(b, r)).astype(np.float32)


def normalise_depth(d, lo=2.0, hi=98.0):
    """Relative depth -> 0..1 by robust percentiles. Returns (d01, (lo_value, hi_value))."""
    d = np.asarray(d, dtype=np.float32)
    a, b = np.percentile(d, [lo, hi])
    if b - a < 1e-6:
        return np.zeros_like(d), (float(a), float(b))
    return np.clip((d - a) / (b - a), 0.0, 1.0), (float(a), float(b))


class DepthSmoother:
    """Makes a video's depth maps steady: the 2nd/98th-percentile scale is smoothed over time (a depth network rescales every
    frame on its own - the whole scene would breathe) and each map is blended with the previous one (`alpha` = weight of the
    new frame). A hard scene change (the picture changes a lot) resets it."""

    def __init__(self, alpha=0.55, scale_alpha=0.25):
        self.alpha = alpha
        self.scale_alpha = scale_alpha
        self.prev = None
        self.lo = None
        self.hi = None

    def push(self, raw, cut=False):
        d = np.asarray(raw, dtype=np.float32)
        a, b = (float(v) for v in np.percentile(d, [2.0, 98.0]))
        if self.lo is None or cut:
            self.lo, self.hi, self.prev = a, b, None
        else:
            self.lo += self.scale_alpha * (a - self.lo)
            self.hi += self.scale_alpha * (b - self.hi)
        span = max(self.hi - self.lo, 1e-6)
        cur = np.clip((d - self.lo) / span, 0.0, 1.0)
        out = cur if self.prev is None else self.alpha * cur + (1.0 - self.alpha) * self.prev
        self.prev = out
        return out

    @staticmethod
    def is_cut(prev_gray, gray, thr=38.0):
        """Mean absolute difference of two small grey frames: a scene change when it is large."""
        if prev_gray is None:
            return False
        return float(np.mean(np.abs(np.asarray(prev_gray, dtype=np.float32) - np.asarray(gray, dtype=np.float32)))) > thr


def interpolate_depth(d0, d1, w):
    """Linear blend between two depth maps taken at different times (depth is computed a few times a second only)."""
    return (1.0 - w) * d0 + w * d1
