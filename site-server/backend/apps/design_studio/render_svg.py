"""رندرِ صحنه به SVG (خروجیِ فریم‌های UI): خودکفا، با تصویرِ جاسازی‌شده و متنِ منحنی (پیش‌فرض) یا متنِ زنده.

متنِ منحنی در هر برنامه‌ای (Figma، Inkscape، مرورگر) دقیقاً همان شکلِ پیش‌نمایش را می‌دهد و فونت نمی‌خواهد؛ متنِ زنده ``<text>`` است
با ``font-family`` ِ فونتِ فارسی (برای ویرایش، فونت باید نصب باشد).
"""
from __future__ import annotations

import base64
import io
import math
from xml.sax.saxutils import escape

from PIL import Image

from . import colors, images, outline, render_png, scene

CSS_FAMILY = {"vazirmatn": "Vazirmatn", "estedad": "Estedad", "lalezar": "Lalezar", "shabnam": "Shabnam", "sahel": "Sahel", "samim": "Samim"}


def _n(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _data_uri(im: Image.Image, quality: int = 82) -> str:
    buf = io.BytesIO()
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255:
        im.save(buf, "PNG", optimize=True)
        mime = "image/png"
    else:
        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class _Defs:
    def __init__(self):
        self.items: list[str] = []
        self.n = 0

    def add(self, body: str, prefix: str) -> str:
        self.n += 1
        ident = f"{prefix}{self.n}"
        self.items.append(body.replace("{id}", ident))
        return ident


def _paint(fill, defs: _Defs, w: float, h: float) -> tuple[str, str]:
    """⇒ (مقدارِ fill، opacityِ اضافه)."""
    if not fill:
        return "none", ""
    if isinstance(fill, dict):
        a = math.radians(float(fill.get("angle", 90)))
        dx, dy = math.cos(a), math.sin(a)
        stops = "".join(f'<stop offset="{_n(s[0])}" stop-color="{s[1]}" stop-opacity="{_n(s[2] if len(s) > 2 else 1)}"/>' for s in fill["stops"])
        if fill.get("type") == "radial":
            gid = defs.add(f'<radialGradient id="{{id}}" cx="50%" cy="50%" r="70%">{stops}</radialGradient>', "g")
        else:
            x1, y1 = 0.5 - dx / 2, 0.5 - dy / 2
            x2, y2 = 0.5 + dx / 2, 0.5 + dy / 2
            gid = defs.add(f'<linearGradient id="{{id}}" x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}">{stops}</linearGradient>', "g")
        return f"url(#{gid})", ""
    return fill, ""


def _round_path(x, y, w, h, radius) -> str:
    rs = render_png._radii(radius, w, h)
    tl, tr, br, bl = rs
    return (f"M{_n(x + tl)} {_n(y)}H{_n(x + w - tr)}A{_n(tr)} {_n(tr)} 0 0 1 {_n(x + w)} {_n(y + tr)}V{_n(y + h - br)}"
            f"A{_n(br)} {_n(br)} 0 0 1 {_n(x + w - br)} {_n(y + h)}H{_n(x + bl)}A{_n(bl)} {_n(bl)} 0 0 1 {_n(x)} {_n(y + h - bl)}V{_n(y + tl)}"
            f"A{_n(tl)} {_n(tl)} 0 0 1 {_n(x + tl)} {_n(y)}Z")


def _shadow_filter(defs: _Defs, sh: dict) -> str:
    fid = defs.add(f'<filter id="{{id}}" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="{_n(sh.get("dx", 0))}" dy="{_n(sh.get("dy", 2))}" '
                   f'stdDeviation="{_n(float(sh.get("blur", 6)) / 2)}" flood-color="{sh.get("color", "#000000")}" flood-opacity="{_n(sh.get("opacity", 0.2))}"/></filter>', "f")
    return f' filter="url(#{fid})"'


def page_svg(page: dict, src: images.ImageSource | None = None, *, text_mode: str = "outline", max_image_px: int = 1600, with_bleed: bool = False,
             title: str = "") -> str:
    src = src or images.ImageSource()
    b = float(page.get("bleed", 0)) if with_bleed else 0.0
    W, H = page["w"] + 2 * b, page["h"] + 2 * b
    defs = _Defs()
    body: list[str] = []
    bg = page.get("bg")
    if bg:
        fill, _ = _paint(bg, defs, W, H)
        body.append(f'<rect x="0" y="0" width="{_n(W)}" height="{_n(H)}" fill="{fill}"/>')
    for e in page["elements"]:
        if e.get("hidden"):
            continue
        s = _element(e, src, defs, text_mode, max_image_px)
        if not s:
            continue
        rot = e.get("rot")
        if rot:
            s = f'<g transform="rotate({_n(rot)} {_n(e["x"] + e["w"] / 2)} {_n(e["y"] + e["h"] / 2)})">{s}</g>'
        lk = e.get("link")
        if lk and lk.get("url"):
            s = f'<a href="{escape(lk["url"], {chr(34): "&quot;"})}">{s}</a>'
        body.append(f'<g id="{escape(str(e["id"]))}">{s}</g>')
    ttl = f"<title>{escape(title)}</title>" if title else ""
    inner = "".join(body)
    if b:
        inner = f'<g transform="translate({_n(b)} {_n(b)})">{inner}</g>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{_n(W)}" height="{_n(H)}" '
            f'viewBox="0 0 {_n(W)} {_n(H)}" direction="rtl">{ttl}<defs>{"".join(defs.items)}</defs>{inner}</svg>')


def _element(e: dict, src: images.ImageSource, defs: _Defs, text_mode: str, max_image_px: int) -> str:
    t = e["type"]
    x, y, w, h = e["x"], e["y"], e["w"], e["h"]
    op = float(e.get("opacity", 1))
    opa = f' opacity="{_n(op)}"' if op < 0.999 else ""
    filt = _shadow_filter(defs, e["shadow"]) if e.get("shadow") and e["shadow"].get("opacity", 0) > 0 else ""
    st = e.get("stroke")
    stroke = f' stroke="{st["color"]}" stroke-width="{_n(st["w"])}"' if st and st.get("w") else ""
    if t == "rect":
        fill, _ = _paint(e.get("fill"), defs, w, h)
        r = render_png._radii(e.get("radius", 0), w, h)
        if max(r) <= 0:
            return f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" fill="{fill}"{stroke}{opa}{filt}/>'
        if len(set(r)) == 1:
            return f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" rx="{_n(r[0])}" fill="{fill}"{stroke}{opa}{filt}/>'
        return f'<path d="{_round_path(x, y, w, h, r)}" fill="{fill}"{stroke}{opa}{filt}/>'
    if t == "ellipse":
        fill, _ = _paint(e.get("fill"), defs, w, h)
        return f'<ellipse cx="{_n(x + w / 2)}" cy="{_n(y + h / 2)}" rx="{_n(w / 2)}" ry="{_n(h / 2)}" fill="{fill}"{stroke}{opa}{filt}/>'
    if t == "line":
        s = e.get("stroke") or {"color": "#000000", "w": 0.3}
        dash = f' stroke-dasharray="{_n(e["dash"][0])} {_n(e["dash"][1])}"' if e.get("dash") else ""
        return f'<line x1="{_n(x)}" y1="{_n(y)}" x2="{_n(x + w)}" y2="{_n(y + h)}" stroke="{s["color"]}" stroke-width="{_n(s["w"])}"{dash}{opa}/>'
    if t == "image":
        im = src.open(e.get("src", ""), max_image_px)
        r = render_png._radii(e.get("radius", 0), w, h)
        if im is None:
            return f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" rx="{_n(r[0])}" fill="#e2e8f0"{opa}/>'
        crop, dest = images.fit_rect(im.width, im.height, w, h, e.get("fit", "cover"), e.get("focus"))
        part = im.crop(tuple(int(round(v)) for v in crop))
        k = min(1.0, max_image_px / max(part.size))
        if k < 1:
            part = part.resize((max(1, int(part.width * k)), max(1, int(part.height * k))), Image.LANCZOS)
        uri = _data_uri(part)
        clip = ""
        if max(r) > 0:
            cid = defs.add(f'<clipPath id="{{id}}"><path d="{_round_path(x, y, w, h, r)}"/></clipPath>', "c")
            clip = f' clip-path="url(#{cid})"'
        alt = escape(e.get("alt", ""))
        return (f'<g{clip}{filt}><image x="{_n(x + dest[0])}" y="{_n(y + dest[1])}" width="{_n(dest[2])}" height="{_n(dest[3])}" '
                f'preserveAspectRatio="none" href="{uri}"{opa}><title>{alt}</title></image></g>')
    if t == "text":
        return _text(e, defs, text_mode)
    return ""


def _text(e: dict, defs: _Defs, text_mode: str) -> str:
    lay = e.get("lay")
    if not lay or not lay["lines"]:
        return ""
    op = float(e.get("opacity", 1))
    opa = f' opacity="{_n(op)}"' if op < 0.999 else ""
    out = []
    if e.get("bg"):
        pad = float(e.get("pad", 0))
        fill, _ = _paint(e["bg"], defs, e["w"], e["h"])
        out.append(f'<rect x="{_n(e["x"] - pad)}" y="{_n(e["y"] - pad)}" width="{_n(e["w"] + 2 * pad)}" height="{_n((lay["h"] if e["h"] <= 0 else e["h"]) + 2 * pad)}" '
                   f'rx="{_n(render_png._radii(e.get("bg_radius", 0), e["w"], e["h"])[0])}" fill="{fill}"{opa}/>')
    size = lay["size"]
    if text_mode == "outline":
        em_px = outline.em_pixels(size * 0.75, "print")
        d = []
        for ln in lay["lines"]:
            if not ln["t"].strip():
                continue
            pieces = ln["words"] if ln.get("words") else [{"t": ln["t"], "x": ln["x"]}]
            for pc in pieces:
                polys, _ = outline.line_contours(pc["t"], e["font"], e["weight"], ln["rtl"], em_px, 0.45)
                tx, ty = e["x"] + pc["x"], e["y"] + ln["y"] + lay["baseline"]
                for poly in polys:
                    pts = [(tx + px * size, ty + py * size) for px, py in poly]
                    d.append("M" + "L".join(f"{_n(a)} {_n(b)}" for a, b in pts) + "Z")
        if d:
            out.append(f'<path d="{"".join(d)}" fill="{e["color"]}" fill-rule="evenodd"{opa}/>')
    else:
        fam = CSS_FAMILY.get(e["font"], "Vazirmatn")
        for ln in lay["lines"]:
            if not ln["t"].strip():
                continue
            base = e["y"] + ln["y"] + lay["baseline"]
            rtl = ln["rtl"]
            if rtl:
                ax, anchor = e["x"] + ln["x"] + ln["w"], "end"
            else:
                ax, anchor = e["x"] + ln["x"], "start"
            out.append(f'<text x="{_n(ax)}" y="{_n(base)}" font-family="{fam}, Vazirmatn, Tahoma, sans-serif" font-size="{_n(size)}" font-weight="{e["weight"]}" '
                       f'fill="{e["color"]}" text-anchor="{anchor}" direction="{"rtl" if rtl else "ltr"}" unicode-bidi="plaintext"{opa}>{escape(ln["t"])}</text>')
    return "".join(out)
