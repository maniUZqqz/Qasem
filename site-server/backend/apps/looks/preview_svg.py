"""SOURCE: ported from InstAI:instai/styles/preview_svg.py @ 2f8aa90, adapted for store advertising (NMarketing).
تغییر: فقط سربرگ. تصویرِ نمونهٔ داخلیِ هر سبک (SVG از روی پالت و الگو)؛ بدونِ GPU و بدونِ دانلود.

A small built-in preview picture for every style, drawn from its palette and its `motif` (no image model, no download, no licence question).

It is a swatch, not a sample of the model's output: it shows the colour world and the kind of surface (dots, blocks, layers, glow ...) of the look.
Real sample images made by the GPU node take its place in the picker when they exist (see `samples.py`).
Pure function: `render(style)` -> an SVG document (str). Deterministic per style key.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from xml.sax.saxutils import escape

W, H = 320, 200
BG, PRI, SEC, ACC, SHD, HIL = range(6)

# motif -> (drawer, variant)
MOTIFS: dict[str, tuple[str, str]] = {
    "film": ("sky", "film"), "photo": ("sky", "photo"), "anime": ("sky", "anime"), "parallax": ("layers", "parallax"), "deco": ("sky", "deco"),
    "groovy": ("sky", "groovy"), "synth": ("sky", "synth"), "vapor": ("sky", "vapor"), "constructivist": ("shapes", "wedge"), "silhouette": ("sky", "silhouette"),
    "watercolor": ("blobs", "soft"), "paint": ("blobs", "dab"), "ink": ("blobs", "ink"), "surreal": ("blobs", "surreal"), "duotone": ("blobs", "duo"),
    "holo": ("blobs", "holo"), "glass": ("blobs", "glass"), "doubleexp": ("blobs", "double"), "tiltshift": ("blobs", "tilt"), "miniature": ("blobs", "ornate"),
    "halftone": ("dots", "ben"), "riso": ("dots", "riso"), "grain": ("dots", "grain"), "woodblock": ("strokes", "waves"),
    "sketch": ("strokes", "sketch"), "wobble": ("strokes", "wobble"), "crayon": ("strokes", "crayon"), "chalk": ("strokes", "chalk"),
    "whiteboard": ("strokes", "white"), "nouveau": ("strokes", "vine"), "stick": ("strokes", "stick"), "graffiti": ("strokes", "drips"),
    "pixel": ("blocks", "pixel"), "voxel": ("blocks", "voxel"), "bricks": ("blocks", "bricks"), "mosaic": ("blocks", "mosaic"), "stitch": ("blocks", "stitch"),
    "lowpoly": ("mesh", "poly"), "console": ("mesh", "fog"), "origami": ("mesh", "fold"), "stained": ("mesh", "cells"), "glitch": ("mesh", "glitch"),
    "flat": ("shapes", "flat"), "bauhaus": ("shapes", "bauhaus"), "memphis": ("shapes", "memphis"), "brutal": ("shapes", "brutal"), "corp": ("shapes", "corp"),
    "sticker": ("shapes", "sticker"), "geometric": ("shapes", "star"), "kawaii": ("shapes", "kawaii"),
    "neoncity": ("city", "neon"), "noir": ("city", "noir"), "neon": ("city", "sign"), "steam": ("city", "gears"),
    "cg": ("spheres", "cg"), "clay": ("spheres", "clay"), "chrome": ("spheres", "chrome"), "y2k": ("spheres", "bubble"), "felt": ("spheres", "felt"),
    "blueprint": ("grid", "blueprint"), "wire": ("grid", "wire"), "terminal": ("grid", "terminal"), "infographic": ("grid", "bars"),
    "type": ("bars", "essay"), "kinetic": ("bars", "kinetic"),
    "paper": ("layers", "paper"), "collage": ("layers", "collage"), "particles": ("particles", "dust"), "iso": ("blocks", "iso"), "cg_dummy": ("spheres", "cg"),
    "vhs": ("bars", "vhs"),
}


def _c(p: list[str], i: int) -> str:
    return p[i] if i < len(p) else p[-1]


def _lin(id_: str, a: str, b: str, vertical: bool = True) -> str:
    x2, y2 = ("0", "1") if vertical else ("1", "0")
    return f'<linearGradient id="{id_}" x1="0" y1="0" x2="{x2}" y2="{y2}"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>'


def _sky(p, r, v):
    out = [f'<defs>{_lin("g", _c(p, SHD) if v in ("synth", "vapor", "deco", "film") else _c(p, BG), _c(p, PRI) if v != "photo" else _c(p, BG))}</defs>',
           f'<rect width="{W}" height="{H}" fill="url(#g)"/>']
    sun = _c(p, ACC)
    if v == "deco":
        for i in range(9):
            a = math.pi * i / 8
            out.append(f'<line x1="160" y1="170" x2="{160 + 150 * math.cos(a):.0f}" y2="{170 - 150 * math.sin(a):.0f}" stroke="{_c(p, ACC)}" stroke-width="3" opacity=".8"/>')
        out.append(f'<circle cx="160" cy="170" r="26" fill="{sun}"/>')
    else:
        out.append(f'<circle cx="{r.randint(200, 250)}" cy="{r.randint(60, 90)}" r="{34 if v != "silhouette" else 44}" fill="{sun}" opacity=".95"/>')
        if v in ("synth", "vapor"):
            for i in range(5):
                out.append(f'<rect x="0" y="{96 + i * 9}" width="{W}" height="{2 + i}" fill="{_c(p, SHD)}" opacity=".6"/>')
    if v == "groovy":
        for i in range(6):
            out.append(f'<path d="M0 {110 + i * 14} Q80 {90 + i * 14} 160 {110 + i * 14} T320 {110 + i * 14}" fill="none" stroke="{_c(p, [SEC, ACC, PRI][i % 3])}" stroke-width="8"/>')
    else:
        base = _c(p, SHD)
        out.append(f'<path d="M0 {H} L0 {r.randint(120, 140)} Q70 {r.randint(95, 115)} 140 {r.randint(125, 140)} T{W} {r.randint(115, 135)} L{W} {H} Z" fill="{base}" opacity="{0.9 if v == "silhouette" else .55}"/>')
        out.append(f'<path d="M0 {H} L0 {r.randint(150, 165)} Q90 {r.randint(130, 150)} 180 {r.randint(155, 168)} T{W} {r.randint(150, 165)} L{W} {H} Z" fill="{base}"/>')
    if v == "film":
        out.append(f'<rect width="{W}" height="26" fill="#000"/><rect y="{H - 26}" width="{W}" height="26" fill="#000"/>')
    return "".join(out)


def _blobs(p, r, v):
    bg = _c(p, BG)
    out = [f'<rect width="{W}" height="{H}" fill="{bg}"/>']
    n = 9 if v in ("soft", "glass", "holo") else 7
    for i in range(n):
        col = _c(p, [PRI, SEC, ACC, HIL, PRI][i % 5])
        x, y, rad = r.randint(20, 300), r.randint(20, 180), r.randint(26, 70)
        if v == "ink":
            col = _c(p, SHD)
            out.append(f'<ellipse cx="{x}" cy="{y}" rx="{rad}" ry="{rad * 0.5:.0f}" fill="{col}" opacity="{0.18 + 0.08 * (i % 4)}" transform="rotate({r.randint(-30, 30)} {x} {y})"/>')
        elif v == "dab":
            out.append(f'<ellipse cx="{x}" cy="{y}" rx="{rad * 0.5:.0f}" ry="{rad * 0.22:.0f}" fill="{col}" opacity=".9" transform="rotate({r.randint(-60, 60)} {x} {y})"/>')
        elif v == "glass":
            out.append(f'<circle cx="{x}" cy="{y}" r="{rad}" fill="{col}" opacity=".85"/>')
        else:
            out.append(f'<circle cx="{x}" cy="{y}" r="{rad}" fill="{col}" opacity="{0.35 if v in ("soft", "double") else .6}"/>')
    if v == "glass":
        out.append(f'<rect x="70" y="40" width="180" height="120" rx="18" fill="#fff" opacity=".28" stroke="#fff" stroke-opacity=".7"/>')
    if v == "tilt":
        out.append(f'<rect width="{W}" height="50" fill="{bg}" opacity=".6"/><rect y="150" width="{W}" height="50" fill="{bg}" opacity=".6"/>')
    if v == "ornate":
        out.append(f'<path d="M30 190 V80 Q30 20 160 20 Q290 20 290 80 V190" fill="none" stroke="{_c(p, ACC)}" stroke-width="6"/>')
    if v == "double":
        out.append(f'<path d="M110 190 C100 120 120 70 160 60 C200 70 215 120 205 190 Z" fill="{_c(p, SHD)}" opacity=".75"/>')
    return "".join(out)


def _dots(p, r, v):
    out = [f'<rect width="{W}" height="{H}" fill="{_c(p, BG)}"/>']
    step = 14 if v != "grain" else 11
    for yi in range(0, H, step):
        for xi in range(0, W, step):
            d = math.hypot(xi - 200, yi - 90) / 160
            rad = max(0.6, step * 0.5 * (1 - min(1, d)) + (0.8 if v == "grain" else 1.2))
            col = _c(p, PRI if (xi + yi) % (2 * step) else SEC) if v != "grain" else _c(p, SHD)
            out.append(f'<circle cx="{xi + (3 if v == "riso" and yi % 28 == 0 else 0)}" cy="{yi}" r="{rad:.1f}" fill="{col}" opacity="{0.75 if v == "grain" else 1}"/>')
    if v == "ben":
        out.append(f'<path d="M60 150 L120 150 L120 120 L190 120 L190 150 L250 150" fill="none" stroke="#000" stroke-width="6"/>')
    return "".join(out)


def _strokes(p, r, v):
    dark = v in ("chalk",)
    bg = _c(p, SHD) if dark else _c(p, BG)
    out = [f'<rect width="{W}" height="{H}" fill="{bg}"/>']
    if v == "waves":
        for i in range(8):
            out.append(f'<path d="M0 {40 + i * 18} Q80 {20 + i * 18} 160 {40 + i * 18} T320 {40 + i * 18}" fill="none" stroke="{_c(p, [PRI, SEC, ACC][i % 3])}" stroke-width="6"/>')
        return "".join(out)
    if v == "stick":
        fg = _c(p, PRI)
        for x in (110, 210):
            out.append(f'<circle cx="{x}" cy="70" r="14" fill="none" stroke="{fg}" stroke-width="4"/><path d="M{x} 84 V130 M{x} 100 L{x - 24} 120 M{x} 100 L{x + 24} 90 M{x} 130 L{x - 18} 170 M{x} 130 L{x + 18} 170" stroke="{fg}" stroke-width="4" fill="none" stroke-linecap="round"/>')
        return "".join(out)
    col = _c(p, HIL) if dark else _c(p, PRI)
    wid = {"sketch": 2, "wobble": 3, "crayon": 7, "chalk": 4, "white": 4, "vine": 3, "drips": 9}.get(v, 3)
    for i in range(9):
        x0, y0 = r.randint(10, 150), r.randint(20, 180)
        c1, c2 = (r.randint(40, 280), r.randint(10, 190)), (r.randint(40, 280), r.randint(10, 190))
        out.append(f'<path d="M{x0} {y0} C{c1[0]} {c1[1]} {c2[0]} {c2[1]} {r.randint(170, 310)} {r.randint(20, 180)}" fill="none" stroke="{_c(p, [PRI, SEC, ACC][i % 3]) if v in ("crayon", "drips", "chalk") else col}" stroke-width="{wid}" stroke-linecap="round" opacity=".9"/>')
    if v == "drips":
        for i in range(6):
            x = 30 + i * 48
            out.append(f'<rect x="{x}" y="100" width="6" height="{r.randint(30, 80)}" rx="3" fill="{_c(p, [SEC, ACC][i % 2])}"/>')
    return "".join(out)


def _blocks(p, r, v):
    out = [f'<rect width="{W}" height="{H}" fill="{_c(p, BG)}"/>']
    if v == "iso":
        for gx in range(5):
            for gy in range(4):
                h = r.randint(10, 46)
                x, y = 70 + (gx - gy) * 34, 60 + (gx + gy) * 18
                top = _c(p, [PRI, SEC, ACC][(gx + gy) % 3])
                out.append(f'<polygon points="{x},{y - h} {x + 34},{y - h + 17} {x},{y - h + 34} {x - 34},{y - h + 17}" fill="{top}"/>'
                           f'<polygon points="{x - 34},{y - h + 17} {x},{y - h + 34} {x},{y + 34} {x - 34},{y + 17}" fill="{_c(p, SHD)}" opacity=".85"/>'
                           f'<polygon points="{x + 34},{y - h + 17} {x},{y - h + 34} {x},{y + 34} {x + 34},{y + 17}" fill="{_c(p, SHD)}" opacity=".6"/>')
        return "".join(out)
    s = {"pixel": 16, "voxel": 20, "bricks": 40, "mosaic": 18, "stitch": 14}.get(v, 16)
    out.append(f'<rect y="{H - 60}" width="{W}" height="60" fill="{_c(p, SHD)}"/>')
    for yi in range(0, H, s):
        for xi in range(0, W, s * (2 if v == "bricks" else 1)):
            if v == "pixel" and r.random() < .72 and yi < H - 60:
                continue
            col = _c(p, [PRI, SEC, ACC, HIL][r.randint(0, 3)])
            if v in ("mosaic",):
                out.append(f'<rect x="{xi + 1}" y="{yi + 1}" width="{s - 2}" height="{s - 2}" fill="{col}"/>')
            elif v == "bricks":
                if yi > 70 and r.random() < .5:
                    out.append(f'<rect x="{xi + 2}" y="{yi + 2}" width="{s * 2 - 4}" height="{s - 4}" rx="3" fill="{col}"/><circle cx="{xi + s * 0.5:.0f}" cy="{yi + 4}" r="5" fill="{col}" stroke="#0003"/><circle cx="{xi + s * 1.5:.0f}" cy="{yi + 4}" r="5" fill="{col}" stroke="#0003"/>')
            elif v == "stitch":
                out.append(f'<rect x="{xi + 4}" y="{yi + 5}" width="{s - 8}" height="2" fill="{col}"/><rect x="{xi + 6}" y="{yi + 3}" width="2" height="{s - 6}" fill="{col}" opacity=".7"/>')
            elif v == "voxel":
                if r.random() < .5 and yi > 60:
                    out.append(f'<rect x="{xi}" y="{yi}" width="{s}" height="{s}" fill="{col}" stroke="{_c(p, SHD)}" stroke-opacity=".5"/>')
            else:
                out.append(f'<rect x="{xi}" y="{yi}" width="{s}" height="{s}" fill="{col}"/>')
    return "".join(out)


def _mesh(p, r, v):
    out = [f'<rect width="{W}" height="{H}" fill="{_c(p, BG)}"/>']
    cols, rows = 8, 5
    pts = [[(x * W / cols + r.randint(-14, 14) * (0 < x < cols), y * H / rows + r.randint(-12, 12) * (0 < y < rows)) for x in range(cols + 1)] for y in range(rows + 1)]
    for y in range(rows):
        for x in range(cols):
            a, b, c, d = pts[y][x], pts[y][x + 1], pts[y + 1][x + 1], pts[y + 1][x]
            for tri, k in (((a, b, c), 0), ((a, c, d), 1)):
                col = _c(p, [PRI, SEC, ACC, HIL, SHD][(x * 2 + y + k + r.randint(0, 2)) % 5])
                stroke = f' stroke="{_c(p, SHD)}" stroke-width="{4 if v == "cells" else 0.5}"'
                out.append(f'<polygon points="{" ".join(f"{q[0]:.0f},{q[1]:.0f}" for q in tri)}" fill="{col}"{stroke}/>')
    if v == "fog":
        out.append(f'<rect width="{W}" height="{H}" fill="{_c(p, HIL)}" opacity=".35"/>')
    if v == "glitch":
        for i in range(6):
            out.append(f'<rect x="{r.randint(0, 200)}" y="{r.randint(0, 190)}" width="{r.randint(60, 200)}" height="{r.randint(4, 14)}" fill="{_c(p, [ACC, SEC, PRI][i % 3])}"/>')
    return "".join(out)


def _shapes(p, r, v):
    bg = _c(p, BG)
    out = [f'<rect width="{W}" height="{H}" fill="{bg}"/>']
    ink = _c(p, SHD)
    if v == "wedge":
        out.append(f'<polygon points="0,200 190,0 320,0 320,60 90,200" fill="{_c(p, PRI)}"/><polygon points="0,0 120,0 0,110" fill="{ink}"/><circle cx="240" cy="130" r="40" fill="{ink}"/>')
        return "".join(out)
    if v == "bauhaus":
        out.append(f'<circle cx="110" cy="100" r="62" fill="{_c(p, PRI)}"/><rect x="150" y="50" width="110" height="110" fill="{_c(p, SEC)}"/><polygon points="60,180 160,120 250,180" fill="{_c(p, ACC)}"/>')
        return "".join(out)
    if v == "brutal":
        out.append(f'<rect x="44" y="34" width="200" height="120" fill="{ink}"/><rect x="34" y="24" width="200" height="120" fill="{_c(p, ACC)}" stroke="{ink}" stroke-width="6"/>'
                   f'<rect x="130" y="110" width="90" height="40" fill="{_c(p, SEC)}" stroke="{ink}" stroke-width="5"/>')
        return "".join(out)
    if v == "memphis":
        for i in range(20):
            x, y = r.randint(10, 300), r.randint(10, 190)
            col = _c(p, [PRI, SEC, ACC][i % 3])
            kind = i % 4
            if kind == 0:
                out.append(f'<circle cx="{x}" cy="{y}" r="9" fill="{col}"/>')
            elif kind == 1:
                out.append(f'<polygon points="{x},{y - 12} {x + 12},{y + 10} {x - 12},{y + 10}" fill="{col}"/>')
            elif kind == 2:
                out.append(f'<path d="M{x - 16} {y} l8 -8 l8 8 l8 -8 l8 8" stroke="{col}" stroke-width="4" fill="none"/>')
            else:
                out.append(f'<rect x="{x}" y="{y}" width="16" height="16" fill="none" stroke="{col}" stroke-width="4"/>')
        return "".join(out)
    if v == "star":
        cx, cy = 160, 100
        for k, rad in enumerate((90, 66, 40)):
            pts = " ".join(f"{cx + rad * math.cos(math.pi / 4 * i + k * 0.4) * (1 if i % 2 == 0 else .62):.0f},{cy + rad * math.sin(math.pi / 4 * i + k * 0.4) * (1 if i % 2 == 0 else .62):.0f}" for i in range(16))
            out.append(f'<polygon points="{pts}" fill="{_c(p, [PRI, SEC, ACC][k])}" stroke="{ink}" stroke-width="1.5"/>')
        return "".join(out)
    if v == "corp":
        out.append(f'<ellipse cx="110" cy="150" rx="70" ry="30" fill="{_c(p, SEC)}"/><circle cx="110" cy="62" r="20" fill="{_c(p, ACC)}"/><rect x="92" y="82" width="36" height="70" rx="18" fill="{_c(p, PRI)}"/>'
                   f'<path d="M92 100 q-40 20 -50 56" stroke="{_c(p, PRI)}" stroke-width="12" stroke-linecap="round" fill="none"/><circle cx="240" cy="90" r="40" fill="{_c(p, HIL)}"/>')
        return "".join(out)
    if v == "kawaii":
        for i in range(8):
            x, y = r.randint(20, 300), r.randint(20, 180)
            out.append(f'<circle cx="{x}" cy="{y}" r="{r.randint(14, 30)}" fill="{_c(p, [PRI, SEC, ACC][i % 3])}"/><circle cx="{x - 5}" cy="{y - 2}" r="2.5" fill="{ink}"/><circle cx="{x + 5}" cy="{y - 2}" r="2.5" fill="{ink}"/>')
        return "".join(out)
    if v == "sticker":
        out.append(f'<circle cx="160" cy="100" r="64" fill="#fff" stroke="#0002" stroke-width="2"/><circle cx="160" cy="100" r="54" fill="{_c(p, PRI)}"/><circle cx="142" cy="92" r="6" fill="{ink}"/><circle cx="178" cy="92" r="6" fill="{ink}"/><path d="M142 116 q18 16 36 0" stroke="{ink}" stroke-width="4" fill="none" stroke-linecap="round"/>')
        return "".join(out)
    out.append(f'<circle cx="90" cy="110" r="52" fill="{_c(p, PRI)}"/><rect x="150" y="48" width="100" height="100" rx="14" fill="{_c(p, SEC)}"/><polygon points="230,176 270,110 310,176" fill="{_c(p, ACC)}"/>')
    return "".join(out)


def _city(p, r, v):
    out = [f'<defs>{_lin("g", _c(p, SHD), _c(p, PRI) if v != "noir" else _c(p, SEC))}</defs><rect width="{W}" height="{H}" fill="url(#g)"/>']
    if v == "sign":
        out.append(f'<rect width="{W}" height="{H}" fill="{_c(p, SHD)}"/>')
        out.append(f'<path d="M80 130 q0 -70 80 -70 q80 0 80 70" fill="none" stroke="{_c(p, SEC)}" stroke-width="9" stroke-linecap="round"/><path d="M80 130 q0 -70 80 -70 q80 0 80 70" fill="none" stroke="{_c(p, HIL)}" stroke-width="3" stroke-linecap="round"/>')
        out.append(f'<rect x="120" y="150" width="80" height="12" rx="6" fill="{_c(p, PRI)}"/>')
        return "".join(out)
    if v == "gears":
        for cx, cy, rad in ((90, 110, 50), (200, 80, 36), (250, 150, 28)):
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{rad}" fill="{_c(p, ACC)}" stroke="{_c(p, SHD)}" stroke-width="6" stroke-dasharray="8 6"/><circle cx="{cx}" cy="{cy}" r="{rad * 0.35:.0f}" fill="{_c(p, SHD)}"/>')
        return "".join(out)
    x = 0
    while x < W:
        w, h = r.randint(22, 48), r.randint(50, 150)
        out.append(f'<rect x="{x}" y="{H - h}" width="{w}" height="{h}" fill="{_c(p, SHD)}"/>')
        if v == "neon":
            out.append(f'<rect x="{x + 4}" y="{H - h + 8}" width="{w - 8}" height="3" fill="{_c(p, [SEC, ACC, PRI][r.randint(0, 2)])}"/>')
        for wy in range(H - h + 16, H - 6, 14):
            if r.random() < .45:
                out.append(f'<rect x="{x + r.randint(4, max(5, w - 10))}" y="{wy}" width="5" height="6" fill="{_c(p, ACC)}"/>')
        x += w + 2
    if v == "noir":
        for i in range(8):
            out.append(f'<polygon points="{i * 44},0 {i * 44 + 16},0 {i * 44 + 80},200 {i * 44 + 64},200" fill="#000" opacity=".22"/>')
    return "".join(out)


def _spheres(p, r, v):
    out = [f'<defs>{_lin("g", _c(p, BG), _c(p, SHD) if v == "chrome" else _c(p, BG))}'
           f'<radialGradient id="s" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="{_c(p, HIL)}"/><stop offset=".5" stop-color="{_c(p, PRI)}"/><stop offset="1" stop-color="{_c(p, SHD)}"/></radialGradient>'
           f'<radialGradient id="t" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="{_c(p, HIL)}"/><stop offset=".6" stop-color="{_c(p, SEC)}"/><stop offset="1" stop-color="{_c(p, SHD)}"/></radialGradient></defs>',
           f'<rect width="{W}" height="{H}" fill="url(#g)"/>']
    spots = [(110, 105, 62, "s"), (215, 118, 44, "t"), (250, 60, 26, "s"), (60, 40, 20, "t")]
    for x, y, rad, g in spots:
        if v == "bubble":
            out.append(f'<circle cx="{x}" cy="{y}" r="{rad}" fill="{_c(p, HIL)}" opacity=".35" stroke="{_c(p, PRI)}" stroke-width="2"/><circle cx="{x - rad * 0.3:.0f}" cy="{y - rad * 0.35:.0f}" r="{rad * 0.18:.0f}" fill="#fff" opacity=".9"/>')
        elif v == "felt":
            out.append(f'<circle cx="{x}" cy="{y}" r="{rad}" fill="{_c(p, [PRI, SEC][len(out) % 2])}" stroke="{_c(p, HIL)}" stroke-width="3" stroke-dasharray="5 4"/>')
        else:
            out.append(f'<circle cx="{x}" cy="{y}" r="{rad}" fill="url(#{g})"/>')
    out.append(f'<ellipse cx="160" cy="186" rx="130" ry="9" fill="{_c(p, SHD)}" opacity=".35"/>')
    return "".join(out)


def _grid(p, r, v):
    bg = _c(p, BG) if v != "terminal" else _c(p, SHD)
    fg = _c(p, HIL) if v in ("blueprint", "wire") else _c(p, PRI)
    out = [f'<rect width="{W}" height="{H}" fill="{bg}"/>']
    for x in range(0, W, 20):
        out.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" stroke="{fg}" stroke-opacity=".18"/>')
    for y in range(0, H, 20):
        out.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="{fg}" stroke-opacity=".18"/>')
    if v == "blueprint":
        out.append(f'<circle cx="150" cy="100" r="54" fill="none" stroke="{fg}" stroke-width="2"/><circle cx="150" cy="100" r="20" fill="none" stroke="{fg}" stroke-width="2"/><path d="M80 170 H220 M80 164 V176 M220 164 V176" stroke="{_c(p, ACC)}" stroke-width="2"/>')
    elif v == "wire":
        for k in range(1, 6):
            out.append(f'<ellipse cx="160" cy="100" rx="{k * 17}" ry="{70}" fill="none" stroke="{_c(p, PRI)}" stroke-width="1.5"/>')
        out.append(f'<ellipse cx="160" cy="100" rx="86" ry="22" fill="none" stroke="{_c(p, SEC)}" stroke-width="1.5"/>')
    elif v == "terminal":
        for i in range(8):
            out.append(f'<rect x="20" y="{22 + i * 20}" width="{r.randint(60, 240)}" height="6" fill="{_c(p, PRI)}" opacity="{0.9 - i * 0.07:.2f}"/>')
        out.append(f'<rect x="20" y="186" width="10" height="8" fill="{_c(p, HIL)}"/>')
    else:
        for i, h in enumerate((50, 90, 70, 120, 100)):
            out.append(f'<rect x="{40 + i * 52}" y="{175 - h}" width="34" height="{h}" fill="{_c(p, [PRI, SEC, ACC][i % 3])}"/>')
    return "".join(out)


def _bars(p, r, v):
    dark = v in ("vhs",) or sum(int(_c(p, BG)[i:i + 2], 16) for i in (1, 3, 5)) < 300
    out = [f'<rect width="{W}" height="{H}" fill="{_c(p, BG)}"/>']
    fg = _c(p, SHD) if not dark else _c(p, HIL)
    if v == "kinetic":
        for i, (w, c) in enumerate(((250, ACC), (170, PRI), (230, SEC), (120, ACC))):
            out.append(f'<rect x="{20 + (i % 2) * 30}" y="{22 + i * 40}" width="{w}" height="26" fill="{_c(p, c)}" transform="rotate({-4 if i % 2 else 3} 160 100)"/>')
        return "".join(out)
    if v == "vhs":
        for y in range(0, H, 4):
            out.append(f'<rect y="{y}" width="{W}" height="1" fill="#000" opacity=".25"/>')
        out.append(f'<rect y="120" width="{W}" height="9" fill="{_c(p, SEC)}" opacity=".7"/><rect y="132" width="{W}" height="3" fill="{_c(p, HIL)}" opacity=".6"/>')
        return "".join(out)
    for i, w in enumerate((200, 250, 150, 230)):
        out.append(f'<rect x="40" y="{40 + i * 28}" width="{w}" height="{18 if i else 24}" fill="{fg}" opacity="{1 if i == 0 else .75}"/>')
    out.append(f'<circle cx="270" cy="150" r="14" fill="none" stroke="{_c(p, ACC)}" stroke-width="4"/>')
    return "".join(out)


def _layers(p, r, v):
    out = [f'<defs>{_lin("g", _c(p, BG), _c(p, HIL))}</defs><rect width="{W}" height="{H}" fill="url(#g)"/>']
    for i in range(5):
        y = 70 + i * 26
        col = _c(p, [SEC, PRI, ACC, SHD, PRI][i])
        if v == "collage":
            out.append(f'<polygon points="{r.randint(0, 80)},{y} {r.randint(120, 200)},{y - r.randint(10, 30)} {r.randint(240, 320)},{y + 4} {r.randint(200, 320)},{y + 50} {r.randint(0, 100)},{y + 44}" fill="{col}" stroke="#0002"/>')
        else:
            out.append(f'<path d="M0 {y} Q60 {y - 26} 130 {y} T270 {y - 4} T320 {y} V200 H0 Z" fill="{col}" stroke="#0003" stroke-width="{2 if v == "paper" else 0}"/>')
    out.append(f'<circle cx="{r.randint(220, 270)}" cy="48" r="22" fill="{_c(p, ACC)}"/>')
    return "".join(out)


def _particles(p, r, v):
    out = [f'<defs><radialGradient id="g" cx=".5" cy=".5" r=".8"><stop offset="0" stop-color="{_c(p, PRI)}" stop-opacity=".35"/><stop offset="1" stop-color="{_c(p, BG)}"/></radialGradient></defs><rect width="{W}" height="{H}" fill="url(#g)"/>']
    for i in range(110):
        a = r.random() * math.tau
        d = abs(r.gauss(0, 1)) * 62
        x, y = 160 + math.cos(a) * d * 1.7, 100 + math.sin(a) * d
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r.choice((1, 1.5, 2, 3)):.1f}" fill="{_c(p, [PRI, SEC, ACC, HIL][i % 4])}" opacity="{r.uniform(.4, 1):.2f}"/>')
    return "".join(out)


DRAWERS = {"sky": _sky, "blobs": _blobs, "dots": _dots, "strokes": _strokes, "blocks": _blocks, "mesh": _mesh, "shapes": _shapes, "city": _city,
           "spheres": _spheres, "grid": _grid, "bars": _bars, "layers": _layers, "particles": _particles}


def render(style: dict) -> str:
    """The preview SVG of a style (`palette`, `motif`, `key`)."""
    pal = [c for c in (style.get("palette") or []) if isinstance(c, str) and c.startswith("#") and len(c) == 7] or ["#D0D7EA", "#8D9BD0", "#5B6AA8", "#F2C14E", "#20274A", "#FFFFFF"]
    key = str(style.get("key") or style.get("name_en") or "style")
    drawer, variant = MOTIFS.get(str(style.get("motif") or ""), ("shapes", "flat"))
    rnd = random.Random(key)
    body = DRAWERS[drawer](pal, rnd, variant)
    uid = hashlib.md5(key.encode()).hexdigest()[:6]      # gradient ids must not collide when two previews sit in one HTML page
    body = re.sub(r'id="([gst])"', lambda m: f'id="{m.group(1)}{uid}"', body)
    body = re.sub(r"url\(#([gst])\)", lambda m: f"url(#{m.group(1)}{uid})", body)
    title = escape(str(style.get("name_en") or key))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{title}" preserveAspectRatio="xMidYMid slice">'
            f"<title>{title}</title>{body}</svg>")
