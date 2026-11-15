"""خطِ زمانِ ویدیو: طولِ هر صحنه (فریم)، هم‌پوشانیِ گذارها، شروعِ هر صحنه و کلِ ویدیو.

آینهٔ دقیقِ `motion/remotion/src/timeline.ts` (computeTimeline) است؛ آزمونِ tests_lib.py هر دو را روی چند طرح اجرا و مقایسه می‌کند.
رندر، QA، همگام‌سازیِ صدا و برشِ روی بیت همه از همین‌جا زمانِ هر صحنه را می‌گیرند تا هیچ‌جا حسابِ جداگانه نباشد.
"""
from __future__ import annotations

import math

from . import catalog


def _round(x: float) -> int:
    return int(math.floor(x + 0.5))        # Math.round ِ جاوااسکریپت (نه گردکردنِ بانکیِ پایتون)


def style_trans(style_id: str) -> tuple[str, int]:
    st = catalog.get(style_id) or {}
    t = st.get("trans") or {"kind": "fade", "frames": 12}
    return str(t.get("kind") or "fade"), int(t.get("frames") or 12)


def compute(spec: dict, fps: int | None = None) -> dict:
    """⇒ {frames[], starts[], tfs[], kinds[], total, fps} (فریم)."""
    fps = int(fps or spec.get("fps") or 30)
    scenes = spec.get("scenes") or []
    style_kind, style_frames = style_trans(spec.get("style", ""))
    frames = []
    for s in scenes:
        try:
            d = float(s.get("duration") or 4)
        except (TypeError, ValueError):
            d = 4.0
        frames.append(max(fps, _round(max(1.0, min(60.0, d)) * fps)))
    tfs, kinds = [], []
    for j in range(len(frames) - 1):
        kind = scenes[j].get("transition") or spec.get("transition") or style_kind
        cap = int(math.floor(min(frames[j], frames[j + 1]) * 0.45))
        tfs.append(0 if kind == "cut" else max(0, min(style_frames, cap)))
        kinds.append(kind)
    starts, at = [], 0
    for i, f in enumerate(frames):
        starts.append(at)
        at += f - (tfs[i] if i < len(frames) - 1 else 0)
    return {"frames": frames, "starts": starts, "tfs": tfs, "kinds": kinds, "total": max(1, at), "fps": fps}


def seconds(spec: dict) -> dict:
    """همان خطِ زمان به ثانیه: starts / ends (شروع و پایانِ هر صحنه روی خطِ زمانِ ویدیو) و کل."""
    t = compute(spec)
    fps = t["fps"]
    return {"starts": [s / fps for s in t["starts"]], "ends": [(s + f) / fps for s, f in zip(t["starts"], t["frames"])],
            "durations": [f / fps for f in t["frames"]], "tfs": [x / fps for x in t["tfs"]], "kinds": t["kinds"], "total": t["total"] / fps, "fps": fps}


def total_seconds(spec: dict) -> float:
    return seconds(spec)["total"] if spec.get("scenes") else 0.0
