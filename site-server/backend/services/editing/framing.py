"""Composition for the automatic reframe: WHERE in the frame the subject should sit, not only whether the window follows it.

`reframe.plan` already follows a face / motion / saliency with a camera operator's discipline (dead zone, speed limit, low-pass).  What
it aimed at was the subject's CENTRE — which puts a head in the middle of a vertical frame with a lot of ceiling above it and chops the
body at the chin.  A cinematographer aims at a composition:

* **headroom** — the eyes sit on the upper third line (36 % from the top), so there is a little air above the head and the face is not
  glued to the top edge;
* **lead room** — a subject who is moving (or turning) toward one side gets space on THAT side: the window is nudged toward where they
  are going, so the subject sits on the opposite third;
* **never cut a face** — the face box (plus a margin) always stays inside the window, whatever the two rules above ask;
* **a talking head stays centred** in a portrait window (the thirds rule is for subjects with somewhere to look or go).

Pure functions over plain numbers (fractions of the SOURCE frame) so the maths is tested without a single video.  `reframe.plan(...,
compose=True)` feeds the result into the same smooth camera path as before.
"""
from __future__ import annotations

#: the eyes sit this far down from the top of the window (rule of thirds, a touch above the line)
EYE_LINE = 0.36
#: the eyes are about this fraction of the face height above the face centre
EYE_OFFSET = 0.12
#: how far the window leans toward the direction of travel, in window-widths (the subject ends up near a third line)
LEAD_SHIFT = 0.16
#: a face is never allowed to come closer than this (window fractions) to an edge
FACE_MARGIN = 0.05
#: subject speed (source widths per second) at which the full lead room is given
FULL_LEAD_SPEED = 0.12


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _contain(c: float, a: float, b: float, size: float, margin: float) -> float:
    """The window centre `c` moved the least that keeps [a, b] (plus a margin) inside a window of `size`; a span wider than the window
    is centred instead."""
    lo, hi = b + margin - size / 2, a - margin + size / 2
    return (a + b) / 2 if lo > hi else clamp(c, lo, hi)


def lead_directions(times: list[float], xs: list[float], *, smooth: int = 5) -> list[float]:
    """Per sample, -1..1: which way the subject is heading (+ = to the right) — the smoothed horizontal velocity relative to
    `FULL_LEAD_SPEED`.  A subject standing still (or jittering) gets 0."""
    n = len(xs)
    if n < 3:
        return [0.0] * n
    vel = [0.0] * n
    for i in range(1, n):
        dt = max(1e-3, times[i] - times[i - 1])
        vel[i] = (xs[i] - xs[i - 1]) / dt
    vel[0] = vel[1]
    half = max(1, smooth // 2)
    out = []
    for i in range(n):
        seg = vel[max(0, i - half): i + half + 1]
        v = sum(seg) / len(seg)
        # a dead band: drifting under ~3 % of the width per second is not walking anywhere
        if abs(v) < 0.03:
            out.append(0.0)
        else:
            out.append(clamp(v / FULL_LEAD_SPEED, -1.0, 1.0))
    return out


def window_target(sx: float, sy: float, win_w: float, win_h: float, *, face_h: float | None = None, lead: float = 0.0,
                  face_box: tuple[float, float, float, float] | None = None) -> tuple[float, float]:
    """The centre the WINDOW should have for a subject at (sx, sy) — all in fractions of the source frame.

    `face_h` = the face's height as a fraction of the source frame height (None for a non-face subject); `lead` = -1..1 direction of
    travel; `face_box` = (x, y, w, h) of the face, which must stay inside the window."""
    # vertical: eyes on the upper third (a face only; motion/saliency subjects stay centred in the window)
    if face_h is not None and face_h > 0:
        eye_y = sy - EYE_OFFSET * face_h
        cy = eye_y + (0.5 - EYE_LINE) * win_h
    else:
        cy = sy
    # horizontal: lean toward the direction of travel so there is room in front of the subject
    cx = sx + lead * LEAD_SHIFT * win_w
    if face_box is not None:
        fx, fy, fw, fh = face_box
        cx = _contain(cx, fx, fx + fw, win_w, FACE_MARGIN * win_w)
        cy = _contain(cy, fy, fy + fh, win_h, FACE_MARGIN * win_h)
    return cx, cy


def targets(times: list[float], subject: list[dict], win_w: float, win_h: float) -> tuple[list[float], list[float]]:
    """Per-sample window-centre targets (x, y) for `reframe.camera_path`.  `subject` rows are `{cx, cy, engine, h?, box?}`."""
    xs = [float(s["cx"]) for s in subject]
    leads = lead_directions(times, xs) if win_w < 0.999 else [0.0] * len(xs)
    tx, ty = [], []
    for s, lead in zip(subject, leads):
        face = s.get("engine") == "face"
        x, y = window_target(float(s["cx"]), float(s["cy"]), win_w, win_h, face_h=s.get("h") if face else None, lead=lead,
                             face_box=s.get("box") if face else None)
        tx.append(x)
        ty.append(y)
    return tx, ty


def describe(subject: list[dict], win_w: float, win_h: float) -> str:
    """One Persian sentence of what the framing did (for the plan line)."""
    faces = sum(1 for s in subject if s.get("engine") == "face")
    if faces >= max(1, len(subject) // 3):
        return "چهره روی خطِ یک‌سومِ بالا (فضای سر)، با فضای جلوی سوژه هنگام حرکت و بدونِ بریدنِ صورت"
    return "قاب دنبالِ سوژه با حرکتِ نرم"
