"""The automatic look: exposure, contrast, white balance, noise and sharpness decided per shot from what was MEASURED, with skin kept safe.

The measurements already exist (`analysis.window_stats`: the 5th / 50th / 95th luma percentile, the share of burnt pixels, and the red-blue
imbalance of the neutral pixels).  This module turns them into the clip's colour block (`color.py`: exposure in stops, contrast, highlights,
shadows, temperature, saturation, sharpen, denoise) — the same numbers the manual editor's sliders show and its preview mirrors, so the owner
sees the correction as ordinary sliders and can change any of it, and the BEFORE/AFTER comparison is the editor's own.

Rules, each one a thing a colourist does by habit:

* **Exposure to the middle, never into the clip.**  Aim the median at a pleasant level (118 for footage with a person, 112 otherwise) but never
  push the brightest 5 % past 238 and never lift more than ±1 stop (a bigger move is a different problem: ask for a re-shoot, don't fake it).
* **Contrast only where it is flat** (the 5–95 % spread under 150) and never where the highlights are already burnt.
* **Burnt highlights are pulled down** in proportion to how many there are.
* **White balance only when the neutrals really lean** (|R−B| > 6) and only by the measured amount; with a face in frame at most ±12 on the
  temperature slider so skin never goes green or blue.
* **Skin-tone safe**: with a face, saturation never goes above +8 % and shadow lift is limited, so a face is not pushed orange or grey.
* **Noise follows light**: dark footage (median under 70) gets a gentle denoise; sharpening is mild and is dropped when denoising is strong
  (sharpening noise makes it worse).
* **Do nothing when nothing is wrong** — a correct shot returns an empty block and the plan line says so.  A near-black or near-white shot
  (a slide, a title card) cannot be exposure-measured and is left alone.

Everything is clamped to the ranges `color.clean` accepts.
"""
from __future__ import annotations

import math

TARGET_MEDIAN = 112.0
TARGET_MEDIAN_FACE = 118.0
MAX_STOPS = 1.0
MAX_STOPS_FACE = 0.8
HIGH_CEILING = 238.0
FLAT_SPREAD = 150.0
CAST_MIN = 6.0
CAST_MAX_FACE = 12.0
DARK_MEDIAN = 70.0
UNMEASURABLE_LOW = 8.0           # a median under this (a black slide) tells nothing about exposure
UNMEASURABLE_HIGH = 247.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def plan(stats: dict | None, *, has_face: bool = False, height: int = 0) -> dict:
    """`stats` = `{p5, p50, p95, clip_hi, cast_rb, cast_measurable}` of one shot → `{"color": {…}, "report": [{what, from, to, note}], "changed": bool}`."""
    out: dict = {"color": {}, "report": [], "changed": False, "skipped": ""}
    if not stats or stats.get("p50") is None:
        out["skipped"] = "نور و رنگِ این نما اندازه‌گیری نشد."
        return out
    p5, p50, p95 = float(stats.get("p5") or 0.0), float(stats["p50"]), float(stats.get("p95") or 0.0)
    clip_hi = float(stats.get("clip_hi") or 0.0)
    if p50 < UNMEASURABLE_LOW or p50 > UNMEASURABLE_HIGH:
        out["skipped"] = "تصویر تقریباً سیاه یا سفید است (اسلاید یا کارتِ متن)؛ نور دست نخورد."
        return out
    col: dict = {}
    rep = out["report"]

    # --- exposure: median to the target, highlights protected
    target = TARGET_MEDIAN_FACE if has_face else TARGET_MEDIAN
    want = math.log2(target / max(p50, 1.0))
    cap = MAX_STOPS_FACE if has_face else MAX_STOPS
    stops = _clamp(want * 0.85, -cap, cap)
    if stops > 0 and p95 > 0:
        stops = min(stops, math.log2(HIGH_CEILING / p95)) if p95 < HIGH_CEILING else 0.0
    if abs(stops) >= 0.08:
        col["exposure"] = round(stops, 2)
        rep.append({"what": "exposure", "from": round(p50), "to": round(p50 * 2 ** stops), "note": "روشن‌تر" if stops > 0 else "تیره‌تر"})

    # --- contrast: only a flat picture, never one that is already burnt
    spread = p95 - p5
    if spread < FLAT_SPREAD and clip_hi < 0.02:
        col["contrast"] = round(_clamp((FLAT_SPREAD - spread) / 3.0, 4, 24))
        rep.append({"what": "contrast", "from": round(spread), "to": round(spread * (1 + col["contrast"] / 100)), "note": "کنتراستِ کم‌رمق بیشتر شد"})
    # --- burnt highlights come down
    if clip_hi >= 0.03:
        col["highlights"] = -round(_clamp(clip_hi * 450, 10, 45))
        rep.append({"what": "highlights", "from": round(clip_hi * 100, 1), "to": round(clip_hi * 100 * 0.5, 1), "note": "نقاط سوخته کم شد"})
    # --- lifted blacks / crushed shadows
    if p5 > 45:
        col["blacks"] = -round(_clamp((p5 - 30) / 1.6, 6, 30))
    elif p5 < 6 and p50 < 95 and not has_face:
        col["shadows"] = 18
    elif p5 < 6 and p50 < 95 and has_face:
        col["shadows"] = 8                                       # skin keeps its shadows: a small lift only

    # --- white balance: measured, never guessed; gentler with a face
    cast = stats.get("cast_rb")
    if stats.get("cast_measurable") and cast is not None and abs(float(cast)) > CAST_MIN:
        limit = CAST_MAX_FACE if has_face else 25
        col["temperature"] = round(_clamp(-float(cast) * 1.1, -limit, limit))
        rep.append({"what": "white_balance", "from": round(float(cast), 1), "to": round(float(cast) * 0.3, 1),
                    "note": "رنگ‌زدگیِ گرم گرفته شد" if float(cast) > 0 else "رنگ‌زدگیِ سرد گرفته شد"})

    # --- colour: skin-safe
    if p50 < 90 or spread < FLAT_SPREAD:
        col["saturation"] = 108 if has_face else 112
    if not has_face and "contrast" in col:
        col["vibrance"] = 10

    # --- noise follows light
    denoise = 0
    if p50 < DARK_MEDIAN:
        denoise = round(_clamp((DARK_MEDIAN - p50) * 0.6, 12, 38))
        col["denoise"] = denoise
        rep.append({"what": "denoise", "from": round(p50), "to": denoise, "note": "نویزِ تصویرِ کم‌نور گرفته شد"})
    if height >= 700:
        col["sharpen"] = 8 if denoise >= 25 else 14

    out["color"] = col
    out["changed"] = bool({k for k in col if k not in ("sharpen", "saturation", "vibrance")})
    if not out["changed"]:
        out["color"] = {}
        out["skipped"] = "نور و رنگِ این نما درست است؛ دست نخورد."
    return out


def merge_into_clip(clip: dict, color: dict) -> dict:
    """Write the automatic block INTO the clip's colour block without erasing what the owner or a look already set (the owner's slider wins)."""
    block = dict(clip.get("color") or {})
    for k, v in color.items():
        if k not in block or block[k] in (None, 0, 100, 0.0):
            block[k] = v
    clip["color"] = block
    return clip


def summary_fa(report: list[dict]) -> str:
    notes = [r["note"] for r in report]
    return "، ".join(dict.fromkeys(notes)) if notes else ""
