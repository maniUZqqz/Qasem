"""گرافِ صحنهٔ برداریِ کوچک: مسیرها (پُر/خط)، گروه‌هایی با ماتریسِ آفاین و کاشیِ تصویریِ لوگو.

یک صحنه دو خروجیِ هم‌شکل دارد: **SVG** (متن؛ برای دانلود و ویرایش در هر نرم‌افزارِ برداری) و **تصویرِ Pillow** (نمونه‌برداریِ چندبرابر؛ برای PNG و استیکر و PDF).
همهٔ شکل‌ها (دایره، بیضی، مستطیل گوشه‌گرد، کپسول) پیش از این‌جا به فرمان‌های مسیر (M L C Z) تبدیل می‌شوند؛ پس هر دو خروجی از **همان هندسه** می‌آیند و
ناهمخوانیِ «SVG یک‌جور، PNG یک‌جور» ممکن نیست. هیچ وابستگیِ بیرونی (cairo، inkscape، resvg) لازم نیست؛ فقط Pillow.

مختصات: ``x`` به راست، ``y`` به پایین (مثلِ SVG). ماتریس ``(a, b, c, d, e, f)`` مثلِ ``matrix()`` ِ SVG:  x' = a·x + c·y + e،  y' = b·x + d·y + f.
"""
from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

Matrix = tuple[float, float, float, float, float, float]
IDENT: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
K = 0.5522847498307936          # ضریبِ تقریبِ دایره با بزیهٔ مکعبی


# ------------------------------------------------------------------ ماتریس

def mmul(m: Matrix, n: Matrix) -> Matrix:
    """m بعد از n (ابتدا n اعمال می‌شود)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def mapply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def mtrans(tx: float, ty: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def mscale(sx: float, sy: float | None = None) -> Matrix:
    return (sx, 0.0, 0.0, sx if sy is None else sy, 0.0, 0.0)


def mrot(deg: float) -> Matrix:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (c, s, -s, c, 0.0, 0.0)


def mscale_of(m: Matrix) -> float:
    """مقیاسِ میانگینِ ماتریس (برای پهنای خط)."""
    return math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1e-9


# ------------------------------------------------------------------ مسیرها

Cmd = tuple  # ("M", x, y) | ("L", x, y) | ("C", x1, y1, x2, y2, x, y) | ("Z",)


def r2(v: float) -> float:
    return round(v, 2)


def circle(cx: float, cy: float, r: float) -> list[Cmd]:
    return ellipse(cx, cy, r, r)


def ellipse(cx: float, cy: float, rx: float, ry: float) -> list[Cmd]:
    kx, ky = rx * K, ry * K
    return [("M", cx + rx, cy), ("C", cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry), ("C", cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy),
            ("C", cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry), ("C", cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy), ("Z",)]


def rrect(x: float, y: float, w: float, h: float, r: float) -> list[Cmd]:
    r = max(0.0, min(r, w / 2, h / 2))
    k = r * (1 - K)
    return [("M", x + r, y), ("L", x + w - r, y), ("C", x + w - k, y, x + w, y + k, x + w, y + r), ("L", x + w, y + h - r), ("C", x + w, y + h - k, x + w - k, y + h, x + w - r, y + h),
            ("L", x + r, y + h), ("C", x + k, y + h, x, y + h - k, x, y + h - r), ("L", x, y + r), ("C", x, y + k, x + k, y, x + r, y), ("Z",)]


def poly(pts: list[tuple[float, float]], closed: bool = True) -> list[Cmd]:
    if not pts:
        return []
    out: list[Cmd] = [("M", pts[0][0], pts[0][1])] + [("L", x, y) for x, y in pts[1:]]
    if closed:
        out.append(("Z",))
    return out


def rounded_poly(pts: list[tuple[float, float]], r: float) -> list[Cmd]:
    """چندضلعیِ بسته با گوشه‌های گرد (هر گوشه با یک بزیهٔ مکعبی)."""
    n = len(pts)
    if n < 3:
        return poly(pts)
    out: list[Cmd] = []
    for i in range(n):
        p0, p1, p2 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        d1 = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) or 1.0
        d2 = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
        rr = min(r, d1 / 2, d2 / 2)
        a = (p1[0] + (p0[0] - p1[0]) * rr / d1, p1[1] + (p0[1] - p1[1]) * rr / d1)
        b = (p1[0] + (p2[0] - p1[0]) * rr / d2, p1[1] + (p2[1] - p1[1]) * rr / d2)
        if i == 0:
            out.append(("M", a[0], a[1]))
        else:
            out.append(("L", a[0], a[1]))
        out.append(("C", a[0] + (p1[0] - a[0]) * 0.6, a[1] + (p1[1] - a[1]) * 0.6, b[0] + (p1[0] - b[0]) * 0.6, b[1] + (p1[1] - b[1]) * 0.6, b[0], b[1]))
    out.append(("Z",))
    return out


def capsule(x0: float, y0: float, x1: float, y1: float, w0: float, w1: float | None = None) -> list[Cmd]:
    """کپسولِ کم‌کم‌باریک از (x0,y0) با پهنای w0 تا (x1,y1) با پهنای w1 (دو سرِ گرد)."""
    w1 = w0 if w1 is None else w1
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return circle(x0, y0, max(w0, w1) / 2)
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    r0, r1 = w0 / 2, w1 / 2
    a = (x0 + nx * r0, y0 + ny * r0)
    b = (x1 + nx * r1, y1 + ny * r1)
    c = (x1 - nx * r1, y1 - ny * r1)
    d = (x0 - nx * r0, y0 - ny * r0)
    k0, k1 = r0 * K, r1 * K
    e1 = (x1 + ux * r1, y1 + uy * r1)             # نوکِ نیم‌دایرهٔ انتهایی؛ هر نیم‌دایره دو بزیهٔ ۹۰ درجه‌ای است
    return [("M", a[0], a[1]), ("L", b[0], b[1]),
            ("C", b[0] + ux * k1, b[1] + uy * k1, e1[0] + nx * k1, e1[1] + ny * k1, e1[0], e1[1]),
            ("C", e1[0] - nx * k1, e1[1] - ny * k1, c[0] + ux * k1, c[1] + uy * k1, c[0], c[1]),
            ("L", d[0], d[1]),
            ("C", d[0] - ux * k0, d[1] - uy * k0, (x0 - ux * r0) - nx * k0, (y0 - uy * r0) - ny * k0, x0 - ux * r0, y0 - uy * r0),
            ("C", (x0 - ux * r0) + nx * k0, (y0 - uy * r0) + ny * k0, a[0] - ux * k0, a[1] - uy * k0, a[0], a[1]), ("Z",)]


def curve(pts: list[tuple[float, float]], tension: float = 0.5, closed: bool = False) -> list[Cmd]:
    """منحنیِ نرمِ Catmull-Rom که از همهٔ نقطه‌ها می‌گذرد (به بزیهٔ مکعبی تبدیل شده)."""
    n = len(pts)
    if n < 2:
        return []
    out: list[Cmd] = [("M", pts[0][0], pts[0][1])]
    segs = n if closed else n - 1
    for i in range(segs):
        p0 = pts[(i - 1) % n] if (closed or i > 0) else pts[i]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if (closed or i + 2 < n) else pts[(i + 1) % n]
        t = tension / 3 * 2
        c1 = (p1[0] + (p2[0] - p0[0]) * t / 2 * 1.0, p1[1] + (p2[1] - p0[1]) * t / 2 * 1.0)
        c2 = (p2[0] - (p3[0] - p1[0]) * t / 2 * 1.0, p2[1] - (p3[1] - p1[1]) * t / 2 * 1.0)
        out.append(("C", c1[0], c1[1], c2[0], c2[1], p2[0], p2[1]))
    if closed:
        out.append(("Z",))
    return out


def from_unit_path(path: dict, box: dict) -> list[Cmd]:
    """مسیرِ ادیتور (نقطه‌ها در جعبهٔ واحد، دستگیره‌ها نسبت به نقطه به‌اندازهٔ کسری از جعبه) ⇒ فرمان‌های مسیر در مختصاتِ جزء.
    box = {cx, cy, w, h, rot} (درجه، ساعت‌گرد)؛ نقطهٔ (۰٫۵، ۰٫۵) به (cx, cy) می‌رود. همان قراردادِ ``pro/pen.ts`` (flattenPx) در ادیتورِ عکس."""
    pts = path.get("pts") or []
    if len(pts) < 2:
        return []
    w, h = float(box.get("w", 100)), float(box.get("h", 100))
    cx, cy, rot = float(box.get("cx", 0)), float(box.get("cy", 0)), float(box.get("rot", 0))
    m = mmul(mtrans(cx, cy), mrot(rot))

    def P(x, y):
        return mapply(m, (x - 0.5) * w, (y - 0.5) * h)

    out: list[Cmd] = []
    closed = bool(path.get("closed")) and len(pts) > 2
    n = len(pts)
    x0, y0 = P(pts[0]["x"], pts[0]["y"])
    out.append(("M", x0, y0))
    segs = n if closed else n - 1
    for i in range(segs):
        a, b = pts[i], pts[(i + 1) % n]
        ho, hi = a.get("ho"), b.get("hi")
        if not ho and not hi:
            if i == segs - 1 and closed:
                break
            x, y = P(b["x"], b["y"])
            out.append(("L", x, y))
            continue
        p1 = P(a["x"] + (ho[0] if ho else 0.0), a["y"] + (ho[1] if ho else 0.0))
        p2 = P(b["x"] + (hi[0] if hi else 0.0), b["y"] + (hi[1] if hi else 0.0))
        p3 = P(b["x"], b["y"])
        out.append(("C", p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]))
    if closed:
        out.append(("Z",))
    return out


# ------------------------------------------------------------------ گره‌ها

@dataclass
class P:
    """مسیر: ``fill`` و ``stroke`` رنگِ #rrggbb یا None."""
    cmds: list
    fill: str | None = None
    stroke: str | None = None
    sw: float = 0.0
    op: float = 1.0
    cap: str = "round"
    join: str = "round"


@dataclass
class G:
    kids: list = field(default_factory=list)
    m: Matrix = IDENT
    op: float = 1.0
    name: str = ""

    def add(self, *nodes):
        for n in nodes:
            if n is not None:
                self.kids.append(n)
        return self


@dataclass
class Img:
    """کاشیِ تصویری (لوگو) که در مستطیلِ (x, y, w, h) جزء جا می‌گیرد (contain)."""
    im: Image.Image
    x: float
    y: float
    w: float
    h: float


def _d(cmds: list) -> str:
    parts = []
    for c in cmds:
        k = c[0]
        if k == "Z":
            parts.append("Z")
        else:
            parts.append(k + " ".join(f"{r2(v):g}" for v in c[1:]))
    return " ".join(parts)


# ------------------------------------------------------------------ SVG

def _png_b64(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.convert("RGBA").save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _svg_node(n, out: list, ind: int = 1) -> None:
    pad = "  " * ind
    if isinstance(n, P):
        a = [f'd="{_d(n.cmds)}"', f'fill="{n.fill}"' if n.fill else 'fill="none"']
        if n.stroke and n.sw > 0:
            a += [f'stroke="{n.stroke}"', f'stroke-width="{r2(n.sw):g}"', f'stroke-linecap="{n.cap}"', f'stroke-linejoin="{n.join}"']
        if n.op < 1:
            a.append(f'opacity="{round(n.op, 3):g}"')
        out.append(f"{pad}<path {' '.join(a)}/>")
    elif isinstance(n, G):
        a = []
        if n.name:
            a.append(f'id="{n.name}"')
        if n.m != IDENT:
            a.append('transform="matrix(%s)"' % " ".join(f"{round(v, 5):g}" for v in n.m))
        if n.op < 1:
            a.append(f'opacity="{round(n.op, 3):g}"')
        out.append(f"{pad}<g{(' ' + ' '.join(a)) if a else ''}>")
        for k in n.kids:
            _svg_node(k, out, ind + 1)
        out.append(f"{pad}</g>")
    elif isinstance(n, Img):
        out.append(f'{pad}<image x="{r2(n.x):g}" y="{r2(n.y):g}" width="{r2(n.w):g}" height="{r2(n.h):g}" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,{_png_b64(n.im)}"/>')


def to_svg(root: G, view: tuple[float, float, float, float], *, size: tuple[int, int] | None = None, background: str | None = None, title: str = "") -> str:
    """متنِ SVG. ``view`` = (x, y, عرض، ارتفاع) در مختصاتِ صحنه."""
    vx, vy, vw, vh = view
    w, h = size or (int(vw), int(vh))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{r2(vx):g} {r2(vy):g} {r2(vw):g} {r2(vh):g}" width="{w}" height="{h}">']
    if title:
        safe = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        out.append(f"  <title>{safe}</title>")
    if background:
        out.append(f'  <rect x="{r2(vx):g}" y="{r2(vy):g}" width="{r2(vw):g}" height="{r2(vh):g}" fill="{background}"/>')
    _svg_node(root, out)
    out.append("</svg>")
    return "\n".join(out)


# ------------------------------------------------------------------ Pillow

def _rgba(hx: str | None, op: float = 1.0) -> tuple[int, int, int, int] | None:
    if not hx:
        return None
    h = hx.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), max(0, min(255, int(round(255 * op))))


def _flatten(cmds: list, m: Matrix, tol: float = 0.35) -> list[tuple[list[tuple[float, float]], bool]]:
    """فرمان‌ها ⇒ [(چندخط در مختصاتِ خروجی، بسته؟)]؛ بزیه‌ها با گام‌های متناسب با طولشان صاف می‌شوند."""
    subs: list[tuple[list[tuple[float, float]], bool]] = []
    cur: list[tuple[float, float]] = []
    for c in cmds:
        k = c[0]
        if k == "M":
            if len(cur) > 1:
                subs.append((cur, False))
            cur = [mapply(m, c[1], c[2])]
        elif k == "L":
            cur.append(mapply(m, c[1], c[2]))
        elif k == "C" and cur:
            p0 = cur[-1]
            p1, p2, p3 = mapply(m, c[1], c[2]), mapply(m, c[3], c[4]), mapply(m, c[5], c[6])
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) + math.hypot(p2[0] - p1[0], p2[1] - p1[1]) + math.hypot(p3[0] - p2[0], p3[1] - p2[1])
            steps = max(4, min(96, int(math.ceil(length / (tol * 6)))))
            for i in range(1, steps + 1):
                t = i / steps
                u = 1 - t
                cur.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
        elif k == "Z":
            if len(cur) > 2:
                subs.append((cur, True))
            cur = []
    if len(cur) > 1:
        subs.append((cur, False))
    return subs


def _walk(n, m: Matrix, op: float, out: list) -> None:
    if isinstance(n, P):
        out.append((n, m, op))
    elif isinstance(n, Img):
        out.append((n, m, op))
    elif isinstance(n, G):
        mm = mmul(m, n.m)
        for k in n.kids:
            _walk(k, mm, op * n.op, out)


def flat_items(root: G, view_m: Matrix = IDENT) -> list:
    out: list = []
    _walk(root, view_m, 1.0, out)
    return out


def bbox_of(root: G, view_m: Matrix = IDENT, *, with_stroke: bool = True) -> tuple[float, float, float, float] | None:
    """کادرِ پیرامونِ همهٔ شکل‌ها در مختصاتِ خروجی (با نیمِ پهنای خط)."""
    x0 = y0 = 1e18
    x1 = y1 = -1e18
    for n, m, _op in flat_items(root, view_m):
        if isinstance(n, P):
            pad = (n.sw * mscale_of(m) / 2) if (with_stroke and n.stroke and n.sw > 0) else 0.0
            for pts, _closed in _flatten(n.cmds, m):
                for x, y in pts:
                    x0, y0, x1, y1 = min(x0, x - pad), min(y0, y - pad), max(x1, x + pad), max(y1, y + pad)
        elif isinstance(n, Img):
            for x, y in ((n.x, n.y), (n.x + n.w, n.y), (n.x + n.w, n.y + n.h), (n.x, n.y + n.h)):
                px, py = mapply(m, x, y)
                x0, y0, x1, y1 = min(x0, px), min(y0, py), max(x1, px), max(y1, py)
    if x0 > x1:
        return None
    return x0, y0, x1, y1


def _paste_img(layer: Image.Image, n: Img, m: Matrix, ss: float) -> None:
    from PIL import ImageOps

    sc = mscale_of(m)
    tw, th = max(1, int(round(n.w * sc))), max(1, int(round(n.h * sc)))
    pic = ImageOps.contain(n.im.convert("RGBA"), (tw, th), Image.LANCZOS)
    ox, oy = n.x + (n.w - pic.width / sc) / 2, n.y + (n.h - pic.height / sc) / 2
    base = mmul(m, mmul(mtrans(ox, oy), mscale(1.0 / sc)))          # پیکسلِ تصویر ⇒ پیکسلِ بوم
    a, b, c, d, e, f = base
    det = a * d - b * c
    if abs(det) < 1e-12:
        return
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    corners = [mapply(base, 0, 0), mapply(base, pic.width, 0), mapply(base, 0, pic.height), mapply(base, pic.width, pic.height)]
    bx0, by0 = math.floor(min(p[0] for p in corners)), math.floor(min(p[1] for p in corners))
    bx1, by1 = math.ceil(max(p[0] for p in corners)), math.ceil(max(p[1] for p in corners))
    bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
    # خروجی (X, Y) ⇒ ورودی: (u, v) = inv(base)·(X + bx0, Y + by0)
    inv = (ia, ic, ia * bx0 + ic * by0 - (ia * e + ic * f), ib, id_, ib * bx0 + id_ * by0 - (ib * e + id_ * f))
    piece = pic.transform((bw, bh), Image.AFFINE, inv, resample=Image.BICUBIC)
    _safe_blit(layer, piece, bx0, by0)


def _safe_blit(canvas: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    w, h = canvas.size
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(layer.width, w - x), min(layer.height, h - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    canvas.alpha_composite(layer.crop((sx0, sy0, sx1, sy1)), (x + sx0, y + sy0))


def _draw_path(d: ImageDraw.ImageDraw, n: P, m: Matrix, op: float, canvas: Image.Image | None = None) -> None:
    fill = _rgba(n.fill, n.op * op)
    stroke = _rgba(n.stroke, n.op * op) if (n.stroke and n.sw > 0) else None
    width = max(1.0, n.sw * mscale_of(m)) if stroke else 0.0
    subs = _flatten(n.cmds, m)
    for pts, closed in subs:
        if fill and closed and len(pts) > 2:
            d.polygon(pts, fill=fill)
    if stroke and subs:
        _stroke(canvas, subs, stroke, width, n.cap)


def _stroke(canvas: Image.Image, subs: list, rgba: tuple, width: float, cap: str) -> None:
    """خطِ ضخیم: قطعه‌ها + دایره در هر رأس روی یک ماسکِ کوچک (بی‌دندانهٔ مفصل‌ها، بی‌دوباره‌رنگیِ شفافیت)، بعد یک بار با رنگ ترکیب می‌شود."""
    pad = width / 2 + 2
    xs = [x for pts, _c in subs for x, _y in pts]
    ys = [y for pts, _c in subs for _x, y in pts]
    x0, y0 = max(0, int(math.floor(min(xs) - pad))), max(0, int(math.floor(min(ys) - pad)))
    x1, y1 = min(canvas.width, int(math.ceil(max(xs) + pad))), min(canvas.height, int(math.ceil(max(ys) + pad)))
    if x1 <= x0 or y1 <= y0:
        return
    mask = Image.new("L", (x1 - x0, y1 - y0), 0)
    md = ImageDraw.Draw(mask)
    w = max(1, int(round(width)))
    r = width / 2
    for pts, closed in subs:
        line = pts + [pts[0]] if closed else pts
        for a, b in zip(line, line[1:]):
            md.line([(a[0] - x0, a[1] - y0), (b[0] - x0, b[1] - y0)], fill=255, width=w)
        joins = line[1:-1] if not closed else line[:-1]
        if cap == "round" and not closed:
            joins = line
        if width > 2.5:
            for x, y in joins:
                md.ellipse((x - x0 - r, y - y0 - r, x - x0 + r, y - y0 + r), fill=255)
    if rgba[3] < 255:
        mask = mask.point(lambda v, a=rgba[3]: int(v * a / 255))
    layer = Image.new("RGBA", mask.size, rgba[:3] + (255,))
    layer.putalpha(mask)
    canvas.alpha_composite(layer, (x0, y0))


def rasterize(root: G, view_m: Matrix, size: tuple[int, int], *, ss: int = 3, region: tuple[int, int, int, int] | None = None) -> Image.Image:
    """صحنه ⇒ تصویرِ RGBA شفاف به اندازهٔ ``size``. ``view_m`` صحنه را به پیکسلِ خروجی می‌برد؛ ``region`` (x0,y0,x1,y1) فقط همان ناحیه را می‌کشد (سریع‌تر).
    گره‌های هم‌پوشانِ با ``op<1`` در گروه به‌صورتِ یک لایه با هم ترکیب می‌شوند."""
    W, H = size
    if region is None:
        region = (0, 0, W, H)
    rx0, ry0, rx1, ry1 = max(0, region[0]), max(0, region[1]), min(W, region[2]), min(H, region[3])
    if rx1 <= rx0 or ry1 <= ry0:
        return Image.new("RGBA", size, (0, 0, 0, 0))
    big = Image.new("RGBA", ((rx1 - rx0) * ss, (ry1 - ry0) * ss), (0, 0, 0, 0))
    shift = mtrans(-rx0, -ry0)
    mat = mmul(mscale(ss), mmul(shift, view_m))
    _render_into(big, root, mat, 1.0, ss)
    small = big.resize((rx1 - rx0, ry1 - ry0), Image.LANCZOS)
    if (rx0, ry0, rx1, ry1) == (0, 0, W, H):
        return small
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(small, (rx0, ry0))
    return out


def _render_into(canvas: Image.Image, node, m: Matrix, op: float, ss: int) -> None:
    if isinstance(node, G):
        mm = mmul(m, node.m)
        if node.op < 1.0:
            sub = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            for k in node.kids:
                _render_into(sub, k, mm, 1.0, ss)
            a = sub.getchannel("A").point(lambda v: int(v * node.op * op))
            sub.putalpha(a)
            canvas.alpha_composite(sub)
        else:
            for k in node.kids:
                _render_into(canvas, k, mm, op, ss)
    elif isinstance(node, P):
        d = ImageDraw.Draw(canvas, "RGBA")
        if node.op < 1.0 and (node.fill and node.stroke):
            sub = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            _draw_path(ImageDraw.Draw(sub, "RGBA"), P(node.cmds, node.fill, node.stroke, node.sw, 1.0, node.cap, node.join), m, 1.0, sub)
            sub.putalpha(sub.getchannel("A").point(lambda v: int(v * node.op * op)))
            canvas.alpha_composite(sub)
        else:
            _draw_path(d, node, m, op, canvas)
    elif isinstance(node, Img):
        _paste_img(canvas, node, m, ss)
