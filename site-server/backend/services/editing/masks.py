"""Free-form (Bézier) masks. §23.4

A mask is a closed path of points; each point has an anchor and two handles (offsets from the anchor), all as FRACTIONS
of the clip's box:

    {"x": 0.2, "y": 0.3, "ix": -0.05, "iy": 0.0, "ox": 0.05, "oy": 0.0}

The path is flattened (cubic segments, 24 steps each), filled, blurred by `feather` (a fraction of the short side — the
same «blur(feather × short side × 0.5)» the browser applies) and written as a grey PNG. `compose.py` feeds that image to
the layer's alpha like the rectangle/ellipse masks; when a motion track is attached (`kx` / `ky` keys) the image is
moved with an `overlay` expression, so the cut-out follows the subject.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings

from .errors import TimelineError

MIN_POINTS = 3
MAX_POINTS = 64
STEPS = 24
MAX_SIDE = 1024
CACHE_KEEP = 200


def _num(value, lo, hi, default):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return max(lo, min(hi, x))


def clean_points(raw) -> list[dict]:
    """Browser JSON → ≤ MAX_POINTS points, coordinates clamped around the box (a point may sit a little outside it)."""
    pts = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_POINTS]:
        if not isinstance(item, dict):
            continue
        pts.append({
            "x": round(_num(item.get("x"), -0.5, 1.5, 0.5), 5), "y": round(_num(item.get("y"), -0.5, 1.5, 0.5), 5),
            "ix": round(_num(item.get("ix"), -1, 1, 0.0), 5), "iy": round(_num(item.get("iy"), -1, 1, 0.0), 5),
            "ox": round(_num(item.get("ox"), -1, 1, 0.0), 5), "oy": round(_num(item.get("oy"), -1, 1, 0.0), 5),
        })
    return pts if len(pts) >= MIN_POINTS else []


def flatten(points: list[dict], steps: int = STEPS) -> list[tuple[float, float]]:
    """The closed path as a polyline in box fractions."""
    out: list[tuple[float, float]] = []
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        p0 = (a["x"], a["y"])
        p1 = (a["x"] + a["ox"], a["y"] + a["oy"])
        p2 = (b["x"] + b["ix"], b["y"] + b["iy"])
        p3 = (b["x"], b["y"])
        straight = a["ox"] == a["oy"] == 0 and b["ix"] == b["iy"] == 0
        count = 1 if straight else steps
        for s in range(count):
            t = s / count
            u = 1 - t
            x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
            y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
            out.append((x, y))
    return out


def render_png(mask: dict, width: int, height: int, out_path) -> Path:
    """Grey mask (white = the layer shows) of `mask["points"]`, `feather` and `invert`, at width×height."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    w, h = max(8, min(MAX_SIDE, int(width))), max(8, min(MAX_SIDE, int(height)))
    ss = 2 if max(w, h) <= 1100 else 1
    W, H = w * ss, h * ss
    poly = [(x * W, y * H) for x, y in flatten(mask["points"])]
    img = Image.new("L", (W, H), 0)
    ImageDraw.Draw(img).polygon(poly, fill=255)
    if ss > 1:
        img = img.resize((w, h), Image.LANCZOS)
    radius = float(mask.get("feather") or 0) * min(w, h) * 0.5
    if radius > 0.4:
        img = img.filter(ImageFilter.GaussianBlur(radius))
    if mask.get("invert"):
        img = ImageOps.invert(img)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out


def mask_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / "masks"


def render_cached(mask: dict, width: int, height: int) -> Path:
    w, h = max(8, min(MAX_SIDE, int(width))), max(8, min(MAX_SIDE, int(height)))
    key = hashlib.sha1(json.dumps([mask["points"], mask.get("feather", 0), bool(mask.get("invert")), w, h], sort_keys=True).encode()).hexdigest()[:20]
    path = mask_dir() / f"{key}.png"
    if not (path.is_file() and path.stat().st_size > 0):
        try:
            render_png(mask, w, h, path)
        except Exception as exc:  # noqa: BLE001
            raise TimelineError(f"ساختنِ ماسکِ آزاد ممکن نشد: {exc}") from exc
        for old in sorted(mask_dir().glob("*.png"), key=lambda p: p.stat().st_mtime)[:-CACHE_KEEP]:
            try:
                old.unlink()
            except OSError:
                pass
    else:
        path.touch()
    return path
