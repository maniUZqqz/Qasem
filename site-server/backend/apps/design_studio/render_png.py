"""رندرِ صحنه به PNG/JPG با Pillow: شکل، شیب، سایه، تصویر (cover/contain)، متنِ فارسی (raqm)، چرخش و علامتِ برش.

``render_page(page, src, scale=…)`` ⇒ تصویرِ RGB. ``scale`` = پیکسل به ازای هر واحدِ صحنه (چاپ: ۳۰۰ dpi ⇒ ۱۱٫۸۱۱ پیکسل بر میلی‌متر).
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import colors, images, typeset

DPI_MM = 1 / 25.4
MAX_PIXELS = 36_000_000
AA = 3                      # بیش‌نمونه‌گیریِ شکل‌ها


def px_per_mm(dpi: float) -> float:
    return dpi * DPI_MM


# ───────────────────────────── شکل‌ها

def _radii(r, w: float, h: float) -> list[float]:
    lim = min(w, h) / 2
    if isinstance(r, (list, tuple)) and len(r) == 4:
        return [max(0.0, min(lim, float(x))) for x in r]
    v = max(0.0, min(lim, float(r or 0)))
    return [v, v, v, v]


def shape_mask(w: int, h: int, radius, kind: str = "rect", inset: float = 0.0) -> Image.Image:
    """ماسکِ L با لبه‌های نرم؛ radius به پیکسل. inset: کوچک‌کردنِ شکل (برای حاشیه)."""
    w, h = max(1, w), max(1, h)
    if kind == "rect" and not radius and not inset:
        return Image.new("L", (w, h), 255)
    big = Image.new("L", (w * AA, h * AA), 0)
    d = ImageDraw.Draw(big)
    ins = inset * AA
    box = [ins, ins, w * AA - 1 - ins, h * AA - 1 - ins]
    if box[2] <= box[0] or box[3] <= box[1]:
        return Image.new("L", (w, h), 0)
    if kind == "ellipse":
        d.ellipse(box, fill=255)
    else:
        rs = [x * AA for x in _radii(radius, w, h)]
        rs = [max(0.0, x - ins) for x in rs]
        if max(rs) <= 0.5:
            d.rectangle(box, fill=255)
        else:
            d.rounded_rectangle(box, radius=max(rs), fill=255, corners=tuple(r > 0.5 for r in rs))
    return big.resize((w, h), Image.LANCZOS)


def gradient_image(w: int, h: int, g: dict) -> Image.Image:
    """شیبِ خطی/شعاعی ⇒ RGBA."""
    w, h = max(1, w), max(1, h)
    stops = sorted(g.get("stops") or [[0, "#000000", 1], [1, "#ffffff", 1]], key=lambda s: s[0])
    pos = np.array([s[0] for s in stops], dtype=np.float32)
    cols = np.array([list(colors.rgb(s[1])) + [255 * (s[2] if len(s) > 2 else 1)] for s in stops], dtype=np.float32)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    if g.get("type") == "radial":
        cx, cy = w / 2, h / 2
        t = np.sqrt(((xs - cx) / (w / 2 + 1e-6)) ** 2 + ((ys - cy) / (h / 2 + 1e-6)) ** 2)
    else:
        a = math.radians(float(g.get("angle", 90)))
        dx, dy = math.cos(a), math.sin(a)
        proj = (xs - w / 2) * dx + (ys - h / 2) * dy
        span = abs(w * dx) + abs(h * dy) or 1.0
        t = proj / span + 0.5
    t = np.clip(t, 0, 1)
    out = np.empty((h, w, 4), dtype=np.uint8)
    for ch in range(4):
        out[..., ch] = np.clip(np.interp(t, pos, cols[:, ch]), 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _fill_layer(w: int, h: int, fill) -> Image.Image | None:
    if not fill:
        return None
    if isinstance(fill, dict):
        return gradient_image(w, h, fill)
    r, g, b = colors.rgb(fill)
    return Image.new("RGBA", (w, h), (r, g, b, 255))


def _with_alpha(layer: Image.Image, mask: Image.Image, opacity: float) -> Image.Image:
    a = layer.getchannel("A")
    a = Image.fromarray((np.asarray(a, dtype=np.float32) * np.asarray(mask, dtype=np.float32) / 255.0 * opacity).clip(0, 255).astype(np.uint8), "L")
    layer = layer.copy()
    layer.putalpha(a)
    return layer


def _blit(canvas: Image.Image, layer: Image.Image, left: int, top: int) -> None:
    """alpha-composite با بریدنِ بخشِ بیرونِ بوم."""
    cw, ch = canvas.size
    lw, lh = layer.size
    x0, y0 = max(0, left), max(0, top)
    x1, y1 = min(cw, left + lw), min(ch, top + lh)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (left, top, left + lw, top + lh):
        layer = layer.crop((x0 - left, y0 - top, x1 - left, y1 - top))
    canvas.alpha_composite(layer, (x0, y0))


# ───────────────────────────── عنصرها

class Renderer:
    def __init__(self, src: images.ImageSource | None, scale: float, *, max_image_px: int | None = None):
        self.src = src or images.ImageSource()
        self.s = float(scale)
        self.missing: list[str] = []
        self.max_image_px = max_image_px

    # ---- مختصات ----
    def _box(self, e: dict, ox: float, oy: float) -> tuple[int, int, int, int]:
        x, y, w, h = e["x"], e["y"], e["w"], e["h"]
        if e["type"] == "line":
            x, y, w, h = min(x, x + w), min(y, y + h), abs(w), abs(h)
        return (round((x + ox) * self.s), round((y + oy) * self.s), max(1, round(w * self.s)), max(1, round(h * self.s)))

    def element(self, canvas: Image.Image, e: dict, ox: float, oy: float) -> None:
        if e.get("hidden"):
            return
        if e.get("rot"):
            self._rotated(canvas, e, ox, oy)
            return
        t = e["type"]
        if t in ("rect", "ellipse"):
            self._shape(canvas, e, ox, oy)
        elif t == "image":
            self._image(canvas, e, ox, oy)
        elif t == "text":
            self._text(canvas, e, ox, oy)
        elif t == "line":
            self._line(canvas, e, ox, oy)

    def _rotated(self, canvas: Image.Image, e: dict, ox: float, oy: float) -> None:
        x, y, w, h = self._box(e, ox, oy)
        diag = int(math.hypot(w, h)) + 8
        pad = (diag - min(w, h)) // 2 + 8
        lay = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
        e2 = {k: v for k, v in e.items() if k != "rot"}
        e2["x"], e2["y"] = pad / self.s, pad / self.s
        self.element(lay, e2, 0, 0)
        lay = lay.rotate(-float(e["rot"]), resample=Image.BICUBIC, expand=True)
        cx, cy = x + w / 2, y + h / 2
        _blit(canvas, lay, round(cx - lay.width / 2), round(cy - lay.height / 2))

    def _shadow(self, canvas: Image.Image, e: dict, mask: Image.Image, x: int, y: int) -> None:
        sh = e.get("shadow")
        if not sh or sh.get("opacity", 0) <= 0:
            return
        blur = float(sh.get("blur", 0)) * self.s
        pad = int(blur * 1.6) + 2
        w, h = mask.size
        big = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        big.paste(mask, (pad, pad))
        if blur > 0.4:
            big = big.filter(ImageFilter.GaussianBlur(blur / 2.2))
        col = Image.new("RGBA", big.size, colors.rgba(sh.get("color", "#000000"), 1.0))
        col.putalpha(big.point(lambda v: int(v * float(sh.get("opacity", 0.2)))))
        _blit(canvas, col, x - pad + round(float(sh.get("dx", 0)) * self.s), y - pad + round(float(sh.get("dy", 0)) * self.s))

    def _shape(self, canvas: Image.Image, e: dict, ox: float, oy: float) -> None:
        x, y, w, h = self._box(e, ox, oy)
        if w * h > MAX_PIXELS:
            return
        op = float(e.get("opacity", 1))
        kind = e["type"]
        radius = [r * self.s for r in _radii(e.get("radius", 0), e["w"], e["h"])] if kind == "rect" else 0
        simple = kind == "rect" and not any(radius) and not e.get("shadow") and not isinstance(e.get("fill"), dict) and op >= 1
        stroke = e.get("stroke")
        if simple and e.get("fill") and not stroke:
            d = ImageDraw.Draw(canvas)
            d.rectangle([x, y, x + w - 1, y + h - 1], fill=colors.rgba(e["fill"], 1.0))
            return
        mask = shape_mask(w, h, radius, kind)
        self._shadow(canvas, e, mask, x, y)
        fl = _fill_layer(w, h, e.get("fill"))
        if fl is not None:
            _blit(canvas, _with_alpha(fl, mask, op), x, y)
        if stroke and stroke.get("w", 0) > 0:
            sw = max(1.0, stroke["w"] * self.s)
            outer = shape_mask(w, h, radius, kind)
            inner = shape_mask(w, h, radius, kind, inset=sw)
            ring = Image.fromarray(np.clip(np.asarray(outer, dtype=np.int16) - np.asarray(inner, dtype=np.int16), 0, 255).astype(np.uint8), "L")
            col = Image.new("RGBA", (w, h), colors.rgba(stroke.get("color", "#000000"), 1.0))
            _blit(canvas, _with_alpha(col, ring, op), x, y)

    def _line(self, canvas: Image.Image, e: dict, ox: float, oy: float) -> None:
        st = e.get("stroke") or {"color": "#000000", "w": 0.3}
        sw = max(1.0, st["w"] * self.s)
        x1, y1 = (e["x"] + ox) * self.s, (e["y"] + oy) * self.s
        x2, y2 = (e["x"] + e["w"] + ox) * self.s, (e["y"] + e["h"] + oy) * self.s
        pad = int(sw) + 3
        lx, ly = int(min(x1, x2)) - pad, int(min(y1, y2)) - pad
        w, h = int(abs(x2 - x1)) + 2 * pad + 1, int(abs(y2 - y1)) + 2 * pad + 1
        big = Image.new("L", (w * AA, h * AA), 0)
        d = ImageDraw.Draw(big)
        p1 = ((x1 - lx) * AA, (y1 - ly) * AA)
        p2 = ((x2 - lx) * AA, (y2 - ly) * AA)
        dash = e.get("dash")
        if dash:
            total = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
            a, b = dash[0] * self.s * AA, dash[1] * self.s * AA
            pos = 0.0
            ux, uy = (p2[0] - p1[0]) / total, (p2[1] - p1[1]) / total
            while pos < total:
                end = min(total, pos + a)
                d.line([(p1[0] + ux * pos, p1[1] + uy * pos), (p1[0] + ux * end, p1[1] + uy * end)], fill=255, width=int(sw * AA))
                pos += a + b
        else:
            d.line([p1, p2], fill=255, width=int(sw * AA))
        mask = big.resize((w, h), Image.LANCZOS)
        col = Image.new("RGBA", (w, h), colors.rgba(st.get("color", "#000000"), 1.0))
        _blit(canvas, _with_alpha(col, mask, float(e.get("opacity", 1))), lx, ly)

    def _image(self, canvas: Image.Image, e: dict, ox: float, oy: float) -> None:
        x, y, w, h = self._box(e, ox, oy)
        if w * h > MAX_PIXELS:
            return
        radius = [r * self.s for r in _radii(e.get("radius", 0), e["w"], e["h"])]
        im = self.src.open(e.get("src", ""), self.max_image_px or int(max(w, h) * 1.6 + 8))
        mask = shape_mask(w, h, radius)
        self._shadow(canvas, e, mask, x, y)
        if im is None:
            self.missing.append(e.get("src", ""))
            ph = Image.new("RGBA", (w, h), (226, 232, 240, 255))
            d = ImageDraw.Draw(ph)
            d.line([(0, 0), (w, h)], fill=(203, 213, 225, 255), width=max(1, w // 120))
            d.line([(w, 0), (0, h)], fill=(203, 213, 225, 255), width=max(1, w // 120))
            _blit(canvas, _with_alpha(ph, mask, float(e.get("opacity", 1))), x, y)
            return
        crop, dest = images.fit_rect(im.width, im.height, w, h, e.get("fit", "cover"), e.get("focus"))
        part = im.crop(tuple(int(round(v)) for v in crop)).convert("RGBA")
        dw, dh = max(1, round(dest[2])), max(1, round(dest[3]))
        part = part.resize((dw, dh), Image.LANCZOS)
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        lay.paste(part, (round(dest[0]), round(dest[1])))
        if e.get("fit") == "contain":
            mask = Image.fromarray(np.asarray(lay.getchannel("A")), "L") if not any(radius) else mask
        _blit(canvas, _with_alpha(lay, mask, float(e.get("opacity", 1))), x, y)
        if e.get("stroke") and e["stroke"].get("w", 0) > 0:
            self._shape(canvas, {"type": "rect", "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"], "fill": None, "radius": e.get("radius", 0),
                                 "stroke": e["stroke"], "opacity": e.get("opacity", 1)}, ox, oy)

    def _text(self, canvas: Image.Image, e: dict, ox: float, oy: float) -> None:
        lay = e.get("lay")
        if not lay or not lay["lines"]:
            return
        s = self.s
        op = float(e.get("opacity", 1))
        if e.get("bg"):
            pad = float(e.get("pad", 0))
            self._shape(canvas, {"type": "rect", "x": e["x"] - pad, "y": e["y"] - pad, "w": e["w"] + 2 * pad, "h": lay["h"] + 2 * pad if e["h"] <= 0 else e["h"] + 2 * pad,
                                 "fill": e["bg"], "radius": e.get("bg_radius", 0), "opacity": op}, ox, oy)
        target = canvas
        left = top = 0
        if op < 1:
            x, y, w, h = self._box(e, ox, oy)
            pad = int(e["size"] * s)
            target = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
            left, top = x - pad, y - pad
        d = ImageDraw.Draw(target)
        col = colors.rgba(e["color"], 1.0)
        px = lay["size"] * s
        for ln in lay["lines"]:
            if not ln["t"]:
                continue
            base_y = (e["y"] + oy + ln["y"] + lay["baseline"]) * s - top
            base_x = (e["x"] + ox) * s - left
            if ln.get("words"):
                for wd in ln["words"]:
                    typeset.draw_line(d, base_x + wd["x"] * s, base_y, wd["t"], e["font"], e["weight"], px, col, ln["rtl"])
            else:
                typeset.draw_line(d, base_x + ln["x"] * s, base_y, ln["t"], e["font"], e["weight"], px, col, ln["rtl"])
            if e.get("underline") or e.get("strike"):
                lw = ln["w"] * s
                lx = base_x + ln["x"] * s
                th = max(1.0, px * 0.06)
                if e.get("underline"):
                    d.rectangle([lx, base_y + px * 0.12, lx + lw, base_y + px * 0.12 + th], fill=col)
                if e.get("strike"):
                    d.rectangle([lx, base_y - px * 0.28, lx + lw, base_y - px * 0.28 + th], fill=col)
        if target is not canvas:
            a = target.getchannel("A").point(lambda v: int(v * op))
            target.putalpha(a)
            _blit(canvas, target, left, top)


# ───────────────────────────── صفحه

def draw_bg(canvas: Image.Image, bg) -> None:
    if not bg:
        return
    if isinstance(bg, dict):
        canvas.alpha_composite(gradient_image(canvas.width, canvas.height, bg))
    else:
        ImageDraw.Draw(canvas).rectangle([0, 0, canvas.width, canvas.height], fill=colors.rgba(bg, 1.0))


def render_page(page: dict, src: images.ImageSource | None = None, *, scale: float = 1.0, with_bleed: bool = False, marks: bool = False,
                transparent: bool = False, max_image_px: int | None = None, report: list | None = None) -> Image.Image:
    """⇒ تصویرِ RGB (یا RGBA با transparent). with_bleed ⇒ خونریزی هم می‌آید؛ marks ⇒ علامتِ برش (به اضافهٔ حاشیه)."""
    b = float(page.get("bleed", 0)) if (with_bleed or marks) else 0.0
    slug = 7.0 if marks else 0.0                          # حاشیهٔ علامت‌ها (میلی‌متر) بیرونِ خونریزی
    W = page["w"] + 2 * b + 2 * slug
    H = page["h"] + 2 * b + 2 * slug
    pw, ph = max(1, round(W * scale)), max(1, round(H * scale))
    if pw * ph > MAX_PIXELS:
        k = math.sqrt(MAX_PIXELS / (pw * ph))
        scale *= k
        pw, ph = max(1, round(W * scale)), max(1, round(H * scale))
    canvas = Image.new("RGBA", (pw, ph), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    r = Renderer(src, scale, max_image_px=max_image_px)
    off = b + slug
    # پس‌زمینه تا لبهٔ خونریزی
    bg_canvas = canvas if not marks else canvas.crop((round(slug * scale), round(slug * scale), pw - round(slug * scale), ph - round(slug * scale)))
    draw_bg(bg_canvas, page.get("bg"))
    if marks:
        canvas.paste(bg_canvas, (round(slug * scale), round(slug * scale)))
    for e in page["elements"]:
        r.element(canvas, e, off, off)
    if marks:
        _crop_marks(canvas, page, scale, b, slug)
    if report is not None:
        report.extend(r.missing)
    return canvas if transparent else canvas.convert("RGB")


def _crop_marks(canvas: Image.Image, page: dict, scale: float, bleed: float, slug: float) -> None:
    d = ImageDraw.Draw(canvas)
    k = scale
    x0, y0 = (slug + bleed) * k, (slug + bleed) * k
    x1, y1 = x0 + page["w"] * k, y0 + page["h"] * k
    L = 5.0 * k
    gap = (bleed + 0.5) * k
    w = max(1, round(0.25 * 0.3528 * 2.83 * k * 0.5)) if False else max(1, round(0.12 * k))
    for (cx, cy, sx, sy) in ((x0, y0, -1, -1), (x1, y0, 1, -1), (x0, y1, -1, 1), (x1, y1, 1, 1)):
        d.line([(cx + sx * gap, cy), (cx + sx * (gap + L), cy)], fill=(0, 0, 0, 255), width=w)
        d.line([(cx, cy + sy * gap), (cx, cy + sy * (gap + L))], fill=(0, 0, 0, 255), width=w)
