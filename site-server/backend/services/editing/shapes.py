"""Shapes (rectangle, ellipse, star, heart, arrow …): a vector description → one transparent PNG. §23.4

A shape on the timeline is an ordinary «image» clip whose picture is made here, so everything a picture can do —
position, scale, rotation, keyframes, fades, blend modes, masks, a motion track — works on it without a single new
filter. The browser draws the same outline (`shapes.ts` mirrors `unit_shapes`; a test compares the vertices), so the
instant preview and the render agree.

The outline lives in a unit box: every polygon is a list of (x, y) in 0..1 that the renderer stretches to the clip's
box (an ellipse or a rounded rectangle are primitives). Edges are anti-aliased by drawing 2–3× larger and shrinking
(a full-frame shape on this 3 GB server is drawn once at 1× and softened instead).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from django.conf import settings

from .errors import TimelineError

SHAPES = ("rect", "rounded", "ellipse", "triangle", "star", "polygon", "heart", "arrow", "burst")
SHAPE_TITLES = {
    "rect": "مستطیل", "rounded": "مستطیلِ گرد", "ellipse": "بیضی / دایره", "triangle": "مثلث", "star": "ستاره",
    "polygon": "چندضلعی", "heart": "قلب", "arrow": "فلش", "burst": "انفجار (برچسب)",
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_SIDE = 2048
CACHE_KEEP = 240


def _num(value, lo, hi, default):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return max(lo, min(hi, x))


def _hex(value, default):
    return str(value).lower() if _HEX.match(str(value or "")) else default


def clean(raw) -> dict:
    """The browser's shape dict → every key, clamped (never raises)."""
    raw = raw if isinstance(raw, dict) else {}
    shape = str(raw.get("shape") or "rect")
    if shape not in SHAPES:
        shape = "rect"
    default_inner = {"star": 0.45, "burst": 0.78}.get(shape, 0.5)
    return {
        "shape": shape,
        "fill": _hex(raw.get("fill"), "#ff3d71"),
        "fill2": _hex(raw.get("fill2"), "") if raw.get("fill2") else "",
        "angle": round(_num(raw.get("angle"), -180, 180, 90.0), 1),
        "fill_opacity": round(_num(raw.get("fill_opacity"), 0, 1, 1.0), 3),
        "stroke": _hex(raw.get("stroke"), "#ffffff"),
        "stroke_w": round(_num(raw.get("stroke_w"), 0, 20, 0.0), 2),
        "radius": round(_num(raw.get("radius"), 0, 50, 18.0), 1),
        "points": int(_num(raw.get("points"), 3, 16, 5)),
        "inner": round(_num(raw.get("inner"), 0.15, 0.9, default_inner), 3),
    }


# ------------------------------------------------------------------ geometry (mirrored by shapes.ts)

HEART_SAMPLES = 72


def unit_shapes(spec: dict) -> list[tuple]:
    """[("poly", [(x, y) …]) | ("rrect", radius_fraction) | ("ellipse",)] in the 0..1 box."""
    shape = spec["shape"]
    if shape == "rect":
        return [("poly", [(0, 0), (1, 0), (1, 1), (0, 1)])]
    if shape == "rounded":
        return [("rrect", spec["radius"] / 100.0)]
    if shape == "ellipse":
        return [("ellipse",)]
    if shape == "triangle":
        return [("poly", [(0.5, 0), (1, 1), (0, 1)])]
    if shape == "arrow":
        return [("poly", [(0, 0.32), (0.58, 0.32), (0.58, 0.04), (1, 0.5), (0.58, 0.96), (0.58, 0.68), (0, 0.68)])]
    if shape in ("star", "burst", "polygon"):
        n = spec["points"] if shape != "burst" else max(8, spec["points"] * 2)
        pts = []
        if shape == "polygon":
            for i in range(n):
                a = -math.pi / 2 + 2 * math.pi * i / n
                pts.append((0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)))
        else:
            for i in range(2 * n):
                r = 0.5 if i % 2 == 0 else 0.5 * spec["inner"]
                a = -math.pi / 2 + math.pi * i / n
                pts.append((0.5 + r * math.cos(a), 0.5 + r * math.sin(a)))
        return [("poly", pts)]
    if shape == "heart":
        raw = []
        for i in range(HEART_SAMPLES):
            t = 2 * math.pi * i / HEART_SAMPLES
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            raw.append((x, y))
        x0, x1 = min(p[0] for p in raw), max(p[0] for p in raw)
        y0, y1 = min(p[1] for p in raw), max(p[1] for p in raw)
        return [("poly", [((x - x0) / (x1 - x0), (y - y0) / (y1 - y0)) for x, y in raw])]
    return [("poly", [(0, 0), (1, 0), (1, 1), (0, 1)])]


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def render_png(spec: dict, width: int, height: int, out_path) -> Path:
    """Draw `spec` (cleaned) at width×height into a PNG with an alpha channel."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    w, h = max(8, min(MAX_SIDE, int(width))), max(8, min(MAX_SIDE, int(height)))
    ss = max(1, min(3, 2400 // max(w, h)))
    W, H = w * ss, h * ss
    sw = spec["stroke_w"] / 100.0 * min(W, H)
    inset = sw / 2.0 + (0.5 * ss)
    x0, y0, x1, y1 = inset, inset, W - inset, H - inset

    def to_px(pt):
        return (x0 + pt[0] * (x1 - x0), y0 + pt[1] * (y1 - y0))

    fill_mask = Image.new("L", (W, H), 0)
    stroke_mask = Image.new("L", (W, H), 0)
    fd, sd = ImageDraw.Draw(fill_mask), ImageDraw.Draw(stroke_mask)
    for item in unit_shapes(spec):
        if item[0] == "poly":
            pts = [to_px(p) for p in item[1]]
            fd.polygon(pts, fill=255)
            if sw > 0.4:
                sd.line(pts + [pts[0]], fill=255, width=max(1, int(round(sw))), joint="curve")
        elif item[0] == "rrect":
            r = item[1] * min(x1 - x0, y1 - y0)
            fd.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=255)
            if sw > 0.4:
                sd.rounded_rectangle((x0, y0, x1, y1), radius=r, outline=255, width=max(1, int(round(sw))))
        else:
            fd.ellipse((x0, y0, x1, y1), fill=255)
            if sw > 0.4:
                sd.ellipse((x0, y0, x1, y1), outline=255, width=max(1, int(round(sw))))

    # colour plane: solid, or a linear gradient fill → fill2 along `angle`
    r, g, b = _rgb(spec["fill"])
    if spec["fill2"]:
        r2, g2, b2 = _rgb(spec["fill2"])
        a = math.radians(spec["angle"])
        dx, dy = math.cos(a), math.sin(a)
        xs = (np.arange(W, dtype=np.float32) / max(1, W - 1) - 0.5)[None, :]
        ys = (np.arange(H, dtype=np.float32) / max(1, H - 1) - 0.5)[:, None]
        u = np.clip((xs * dx + ys * dy) / (abs(dx) + abs(dy) + 1e-9) + 0.5, 0, 1)
        plane = np.stack([r + (r2 - r) * u, g + (g2 - g) * u, b + (b2 - b) * u], axis=-1).astype(np.uint8)
        colour = Image.fromarray(plane, "RGB")
    else:
        colour = Image.new("RGB", (W, H), (r, g, b))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fill_alpha = fill_mask.point(lambda v: int(v * spec["fill_opacity"]))
    img.paste(colour, (0, 0), fill_alpha)
    if sw > 0.4:
        img.paste(Image.new("RGB", (W, H), _rgb(spec["stroke"])), (0, 0), stroke_mask)
    if ss > 1:
        img = img.resize((w, h), Image.LANCZOS)
    else:
        alpha = img.getchannel("A").filter(ImageFilter.GaussianBlur(0.6))
        img.putalpha(alpha)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=False)
    return out


def shape_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "editing" / "shapes"


def render_cached(spec: dict, width: int, height: int) -> Path:
    """The PNG of this shape at this size, made once (the key is the content)."""
    w, h = max(8, min(MAX_SIDE, int(width))), max(8, min(MAX_SIDE, int(height)))
    key = hashlib.sha1(json.dumps([spec, w, h], sort_keys=True).encode()).hexdigest()[:20]
    path = shape_dir() / f"{key}.png"
    if not (path.is_file() and path.stat().st_size > 0):
        try:
            render_png(spec, w, h, path)
        except Exception as exc:  # noqa: BLE001 — a drawing bug must read as a message, not a 500
            raise TimelineError(f"ساختنِ شکل ممکن نشد: {exc}") from exc
        _trim_cache()
    else:
        path.touch()
    return path


def _trim_cache() -> None:
    files = sorted(shape_dir().glob("*.png"), key=lambda p: p.stat().st_mtime)
    for old in files[:-CACHE_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def catalogue() -> dict:
    return {"shapes": [{"key": k, "title": SHAPE_TITLES[k]} for k in SHAPES]}
