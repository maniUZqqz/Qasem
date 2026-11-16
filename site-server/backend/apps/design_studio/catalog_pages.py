"""قالب‌های صفحهٔ کاتالوگ: جلد، فهرست، متن، شبکهٔ محصول، محصولِ ویژه (hero)، فهرستِ قیمت، لوک‌بوک، گام‌ها، جداکننده و پشتِ جلد.

هر قالب یک «مشخصهٔ صفحه» (spec) را به عنصرهای صحنه (میلی‌متر) تبدیل می‌کند؛ شناسهٔ عنصرها پایدار است (``p<id>-name``…) تا ویرایش‌های کاربر
(overrides) بعد از بازسازیِ صفحه هم سرجایشان بمانند. متن‌ها فقط از مشخصه و محصولاتِ ثبت‌شده می‌آیند — چیزی از خودمان نمی‌سازیم.
"""
from __future__ import annotations

from . import colors, scene, typeset
from .scene import gradient

PAGE_TYPES = ("cover", "toc", "text", "grid", "hero", "price_list", "lookbook", "steps", "divider", "back")
PAGE_TYPE_FA = {"cover": "جلد", "toc": "فهرست مطالب", "text": "صفحهٔ متن", "grid": "شبکهٔ محصولات", "hero": "محصولِ ویژه", "price_list": "فهرستِ قیمت",
                "lookbook": "لوک‌بوک (تصویر)", "steps": "گام‌ها", "divider": "جداکننده", "back": "پشتِ جلد"}
LAYOUT_NAMES = {"grid": "شبکه", "hero": "محصولِ ویژه", "price_list": "فهرستِ قیمت", "lookbook": "لوک‌بوک"}

DEFAULTS = {"page_size": "A4", "orientation": "portrait", "bleed": 3.0, "margin": 0.0, "look": "", "colors": None, "heading_font": "", "body_font": "",
            "digits": "fa", "show_prices": True, "show_sku": False, "zero_price_label": "رایگان", "show_logo": True, "page_numbers": True,
            "title": "", "subtitle": "", "tagline": "", "date_text": ""}


def page_geometry(settings: dict) -> tuple[float, float, float]:
    w, h = scene.PAGE_SIZES.get(settings.get("page_size"), scene.PAGE_SIZES["A4"])
    if settings.get("orientation") == "landscape":
        w, h = h, w
    return w, h, float(settings.get("bleed", 3.0) or 0)


class Ctx:
    def __init__(self, settings: dict, kit: dict, products: dict[int, dict], store_name: str, contacts: list[dict], *, toc: list | None = None,
                 total: int = 1, has_logo: bool = False):
        self.s = {**DEFAULTS, **(settings or {})}
        self.W, self.H, self.bleed = page_geometry(self.s)
        self.u = min(self.W, self.H) / 210.0
        self.m = float(self.s.get("margin") or 0) or round(14 * self.u, 1)
        self.pal = kit["palette"]
        self.hf, self.bf = kit["fonts"]["heading"], kit["fonts"]["body"]
        self.products = products
        self.store_name = store_name
        self.contacts = contacts
        self.toc = toc or []
        self.total = total
        self.has_logo = has_logo and bool(self.s.get("show_logo", True))
        self.digits = self.s.get("digits", "fa")
        self.index = 0

    @property
    def cw(self) -> float:
        return self.W - 2 * self.m

    def T(self, text) -> str:
        return typeset.digits(text, self.digits)

    def price(self, p: dict) -> str:
        if not self.s.get("show_prices", True):
            return ""
        return typeset.price_text(p.get("price"), p.get("currency", "IRT"), self.digits, self.s.get("zero_price_label", "رایگان"))


# ───────────────────────────── اجزای مشترک

def _footer(c: Ctx, els: list, dark: bool = False) -> None:
    pal, u = c.pal, c.u
    y = c.H - c.m - 4.5 * u
    col = "#ffffff" if dark else pal["muted"]
    els.append(scene.line("ft-line", c.m, y - 2 * u, c.W - c.m, y - 2 * u, pal["line"] if not dark else colors.mix(pal["secondary"], "#ffffff", 0.25), 0.25 * u))
    els.append(scene.text("ft-name", c.W / 2, y, c.W / 2 - c.m, 4.5 * u, c.store_name, font=c.bf, weight=500, size=2.9 * u, color=col, align="right", valign="middle",
                          max_lines=1, lh=1.2, role="footer"))
    if c.s.get("page_numbers", True):
        els.append(scene.text("ft-num", c.m, y, 30 * u, 4.5 * u, str(c.index + 1), font=c.bf, weight=700, size=3.2 * u, color=pal["primary"] if not dark else "#ffffff",
                              align="left", valign="middle", max_lines=1, lh=1.2, role="page-number"))


def _heading(c: Ctx, els: list, title: str, kicker: str = "", dark: bool = False, y: float | None = None) -> float:
    """تیترِ صفحه با میلهٔ رنگی ⇒ y بعدی."""
    pal, u = c.pal, c.u
    y = c.m + 2 * u if y is None else y
    col = "#ffffff" if dark else pal["text"]
    if kicker:
        els.append(scene.text("kicker", c.m, y, c.cw, 5 * u, kicker, font=c.bf, weight=600, size=3.3 * u, color=pal["primary"] if not dark else pal["accent"],
                              max_lines=1, align="right"))
        y += 5 * u
    els.append(scene.text("title", c.m, y, c.cw, 12 * u, title, font=c.hf, weight=800, size=8 * u, color=col, lh=1.3, max_lines=1, shrink=0.35, align="right"))
    els.append(scene.rect("bar", c.W - c.m - 22 * u, y + 11.5 * u, 22 * u, 1.3 * u, pal["primary"] if not dark else pal["accent"], radius=0.65 * u))
    return y + 18 * u


def _logo_tile(c: Ctx, els: list, x: float, y: float, size: float, *, id: str = "logo") -> None:
    if not c.has_logo:
        return
    u = c.u
    els.append(scene.rect(id + "-tile", x, y, size, size, "#ffffff", radius=size * 0.22, shadow={"dx": 0, "dy": 0.6 * u, "blur": 2 * u, "color": "#000000", "opacity": 0.12}))
    els.append(scene.image(id, x + size * 0.14, y + size * 0.14, size * 0.72, size * 0.72, "logo", fit="contain", role="logo", alt=c.store_name))


def _pill(c: Ctx, els: list, id: str, x: float, y: float, text: str, *, size: float, fill: str, color: str, h: float, align: str = "left", max_w: float | None = None) -> float:
    """قرصِ قیمت؛ x لبهٔ چپ (align=left) یا لبهٔ راست (align=right). ⇒ پهنا."""
    wt = typeset.measure(text, c.bf, 700, size) + h * 1.1
    if max_w:
        wt = min(wt, max_w)
    x0 = x if align == "left" else x - wt
    els.append(scene.rect(id + "-bg", x0, y, wt, h, fill, radius=h / 2))
    els.append(scene.text(id, x0, y, wt, h, text, font=c.bf, weight=700, size=size, color=color, align="center", valign="middle", max_lines=1, shrink=0.3, role="price"))
    return wt


def _placeholder(c: Ctx, els: list, id: str, x: float, y: float, w: float, h: float, label: str, radius: float) -> None:
    pal = c.pal
    els.append(scene.rect(id, x, y, w, h, gradient(135, (0, pal["light"], 1), (1, pal["accent"], 1)), radius=radius))
    els.append(scene.text(id + "-ch", x, y, w, h, (label or "؟")[:1], font=c.hf, weight=800, size=min(w, h) * 0.45, color=pal["primary"], align="center", valign="middle",
                          opacity=0.55, max_lines=1))


def _product_image(c: Ctx, els: list, id: str, p: dict, x, y, w, h, radius) -> None:
    ref = (p.get("images") or [""])[0]
    if ref:
        els.append(scene.image(id, x, y, w, h, ref, radius=radius, role="product-image", alt=p.get("name", "")))
    else:
        _placeholder(c, els, id, x, y, w, h, p.get("name", ""), radius if not isinstance(radius, list) else radius[0])


def _pids(spec: dict, c: Ctx) -> list[dict]:
    out = []
    for pid in spec.get("products") or []:
        try:
            p = c.products.get(int(pid))
        except (TypeError, ValueError):
            p = None
        if p:
            out.append(p)
    return out


# ───────────────────────────── جلد

def cover(spec: dict, c: Ctx) -> dict:
    pal, u, W, H, m = c.pal, c.u, c.W, c.H, c.m
    els: list[dict] = []
    bg = gradient(150, (0, pal["secondary"], 1), (1, colors.darken(pal["primary"], 0.1), 1))
    els.append(scene.ellipse("deco1", W * 0.45, -H * 0.12, W * 0.95, W * 0.95, pal["accent"], opacity=0.10, role="decor"))
    els.append(scene.ellipse("deco2", -W * 0.28, H * 0.55, W * 0.8, W * 0.8, pal["primary"], opacity=0.28, role="decor"))
    els.append(scene.ellipse("deco3", W * 0.62, H * 0.72, W * 0.45, W * 0.45, "#ffffff", opacity=0.05, role="decor"))
    _logo_tile(c, els, W - m - 24 * u, m, 24 * u)
    title = spec.get("title") or c.s.get("title") or c.store_name
    sub = spec.get("subtitle") or c.s.get("subtitle") or "کاتالوگ محصولات"
    y = H * 0.20
    els.append(scene.text("kicker", m, y, c.cw, 6 * u, sub, font=c.bf, weight=600, size=4.6 * u, color=pal["accent"], max_lines=1, align="right", shrink=0.4))
    els.append(scene.rect("bar", W - m - 30 * u, y + 8.5 * u, 30 * u, 1.6 * u, pal["accent"], radius=0.8 * u))
    els.append(scene.text("title", m, y + 13 * u, c.cw, 40 * u, title, font=c.hf, weight=800, size=19 * u, color="#ffffff", lh=1.25, max_lines=2, shrink=0.45, align="right"))
    tag = spec.get("tagline") or c.s.get("tagline")
    if tag:
        els.append(scene.text("tagline", m, y + 56 * u, c.cw * 0.8, 14 * u, tag, font=c.bf, weight=400, size=5 * u, color="#ffffff", opacity=0.9, lh=1.6, max_lines=3, align="right"))
    img = spec.get("image")
    top = H * 0.60
    if img:
        els.append(scene.image("hero", m, top, c.cw, H - top - m - 12 * u, img, radius=6 * u, role="cover-image", shadow={"dx": 0, "dy": 2 * u, "blur": 6 * u, "color": "#000000", "opacity": 0.3}))
    date = spec.get("date_text") or c.s.get("date_text")
    if date:
        els.append(scene.text("date", m, H - m - 6 * u, c.cw / 2, 6 * u, date, font=c.bf, weight=500, size=3.8 * u, color="#ffffff", opacity=0.85, align="right", valign="middle", max_lines=1))
    return {"bg": bg, "elements": els}


# ───────────────────────────── فهرست

def toc(spec: dict, c: Ctx) -> dict:
    pal, u = c.pal, c.u
    els: list[dict] = []
    y = _heading(c, els, spec.get("title") or "فهرست مطالب", kicker=c.store_name)
    rows = [t for t in c.toc if t["id"] != spec["id"]]
    avail = c.H - c.m - 10 * u - y
    rh = min(13 * u, avail / max(1, len(rows)))
    for i, t in enumerate(rows):
        ry = y + i * rh
        n = typeset.digits(str(t["index"] + 1), c.digits)
        els.append(scene.rect(f"row{i}", c.m, ry, c.cw, rh - 1.5 * u, pal["surface"] if i % 2 == 0 else pal["light"], radius=2 * u, link={"page": t["id"]}))
        els.append(scene.ellipse(f"dot{i}", c.W - c.m - 9 * u, ry + (rh - 1.5 * u - 7 * u) / 2, 7 * u, 7 * u, pal["primary"]))
        els.append(scene.text(f"num{i}", c.W - c.m - 9 * u, ry + (rh - 1.5 * u - 7 * u) / 2, 7 * u, 7 * u, str(t["index"] + 1), font=c.bf, weight=700, size=3.2 * u,
                              color=pal["on_primary"], align="center", valign="middle", max_lines=1))
        els.append(scene.text(f"name{i}", c.m + 20 * u, ry, c.cw - 33 * u, rh - 1.5 * u, t["title"], font=c.bf, weight=600, size=4.4 * u, color=pal["text"],
                              valign="middle", max_lines=1, shrink=0.3, align="right", link={"page": t["id"]}))
        els.append(scene.text(f"pg{i}", c.m + 3 * u, ry, 14 * u, rh - 1.5 * u, n, font=c.bf, weight=700, size=3.8 * u, color=pal["primary"], valign="middle", align="left", max_lines=1))
    _footer(c, els)
    return {"bg": pal["bg"], "elements": els}


# ───────────────────────────── صفحهٔ متن و گام‌ها و جداکننده

def text_page(spec: dict, c: Ctx) -> dict:
    pal, u = c.pal, c.u
    els: list[dict] = []
    y = _heading(c, els, spec.get("title") or "دربارهٔ ما", kicker=spec.get("kicker", ""))
    img = spec.get("image")
    if img:
        h_img = c.H * 0.28
        els.append(scene.image("image", c.m, y, c.cw, h_img, img, radius=4 * u, role="image"))
        y += h_img + 8 * u
    paras = [p for p in (spec.get("paragraphs") or []) if str(p).strip()]
    bottom = c.H - c.m - 10 * u
    n = len(paras)
    for i, p in enumerate(paras):
        share = (bottom - y) / max(1, n - i)
        h = min(share - 3 * u, 70 * u)
        els.append(scene.text(f"p{i}", c.m, y, c.cw, h, p, font=c.bf, weight=400, size=4.3 * u, color=pal["text"], lh=1.85, shrink=0.2, justify=False, align="right"))
        lay = typeset.layout_text(c.T(p), font=c.bf, weight=400, size=4.3 * u, w=c.cw, h=h, lh=1.85, shrink=0.2)
        y += min(h, lay["h"]) + 5 * u
    _footer(c, els)
    return {"bg": pal["bg"], "elements": els}


def steps_page(spec: dict, c: Ctx) -> dict:
    pal, u = c.pal, c.u
    els: list[dict] = []
    y = _heading(c, els, spec.get("title") or "گام‌ها", kicker=spec.get("kicker", ""))
    steps = [s for s in (spec.get("steps") or []) if isinstance(s, dict)][:7]
    avail = c.H - c.m - 12 * u - y
    sh = min(38 * u, avail / max(1, len(steps)))
    for i, s in enumerate(steps):
        sy = y + i * sh
        cx = c.W - c.m - 6 * u
        if i < len(steps) - 1:
            els.append(scene.line(f"conn{i}", cx + 6 * u - 6 * u, sy + 13 * u, cx, sy + sh - 1 * u, pal["line"], 0.5 * u) if False else
                       scene.rect(f"conn{i}", cx + 5.2 * u, sy + 12.5 * u, 0.8 * u, sh - 12 * u, pal["accent"]))
        els.append(scene.ellipse(f"dot{i}", cx, sy, 12 * u, 12 * u, pal["primary"]))
        els.append(scene.text(f"n{i}", cx, sy, 12 * u, 12 * u, str(i + 1), font=c.hf, weight=800, size=5.4 * u, color=pal["on_primary"], align="center", valign="middle", max_lines=1))
        els.append(scene.text(f"t{i}", c.m, sy - 0.5 * u, c.cw - 18 * u, 7 * u, s.get("title", ""), font=c.hf, weight=700, size=5 * u, color=pal["text"], max_lines=1, shrink=0.3, align="right"))
        els.append(scene.text(f"d{i}", c.m, sy + 7.5 * u, c.cw - 18 * u, sh - 10 * u, s.get("text", ""), font=c.bf, weight=400, size=3.7 * u, color=pal["muted"], lh=1.7,
                              max_lines=3, shrink=0.15, align="right"))
    _footer(c, els)
    return {"bg": pal["bg"], "elements": els}


def divider(spec: dict, c: Ctx) -> dict:
    pal, u = c.pal, c.u
    els = [scene.ellipse("deco1", -c.W * 0.3, c.H * 0.45, c.W * 0.9, c.W * 0.9, "#ffffff", opacity=0.06, role="decor"),
           scene.rect("bar", c.W - c.m - 30 * u, c.H * 0.42, 30 * u, 1.6 * u, pal["accent"], radius=0.8 * u),
           scene.text("title", c.m, c.H * 0.45, c.cw, 40 * u, spec.get("title", ""), font=c.hf, weight=800, size=15 * u, color="#ffffff", lh=1.3, max_lines=2, shrink=0.4, align="right"),
           scene.text("subtitle", c.m, c.H * 0.45 + 42 * u, c.cw * 0.8, 20 * u, spec.get("subtitle", ""), font=c.bf, size=5 * u, color="#ffffff", opacity=0.85, lh=1.7, max_lines=3, align="right")]
    _footer(c, els, dark=True)
    return {"bg": gradient(160, (0, pal["secondary"], 1), (1, pal["primary"], 1)), "elements": els}


# ───────────────────────────── شبکه

def grid(spec: dict, c: Ctx) -> dict:
    pal, u = c.pal, c.u
    els: list[dict] = []
    items = _pids(spec, c)
    y = _heading(c, els, spec.get("title") or "محصولات", kicker=spec.get("kicker", ""))
    cols = max(1, min(4, int(spec.get("cols") or c.s.get("grid_cols") or 2)))
    rows = max(1, min(5, int(spec.get("rows") or c.s.get("grid_rows") or 3)))
    gap = 5 * u
    area_b = c.H - c.m - 10 * u
    cw = (c.cw - gap * (cols - 1)) / cols
    ch = (area_b - y - gap * (rows - 1)) / rows
    k = {1: 1.15, 2: 1.0, 3: 0.82, 4: 0.7}[cols]
    pad = 3 * u * k
    for i, p in enumerate(items[:cols * rows]):
        r, col = divmod(i, cols)
        x = c.W - c.m - cw - col * (cw + gap)                         # راست‌چین: ستونِ اول سمتِ راست
        yy = y + r * (ch + gap)
        pid = f"p{p['id']}"
        els.append(scene.rect(pid + "-card", x, yy, cw, ch, pal["surface"], radius=3.2 * u, stroke={"color": pal["line"], "w": 0.25 * u},
                              shadow={"dx": 0, "dy": 0.8 * u, "blur": 2.5 * u, "color": "#000000", "opacity": 0.07}))
        ih = min(cw * 0.72, ch * 0.5)
        _product_image(c, els, pid + "-img", p, x + pad, yy + pad, cw - 2 * pad, ih, 2.2 * u)
        ny = yy + pad + ih + 2.5 * u * k
        price = c.price(p)
        price_h = 7.2 * u * k if price else 0
        name_h = 2 * 4.6 * u * k * 1.3
        els.append(scene.text(pid + "-name", x + pad, ny, cw - 2 * pad, name_h, p["name"], font=c.hf, weight=700, size=4.4 * u * k, color=pal["text"], lh=1.3, max_lines=2,
                              shrink=0.2, align="right"))
        dy = ny + name_h + 1.2 * u
        dh = yy + ch - pad - price_h - dy - 1 * u
        if dh > 5 * u and p.get("short"):
            els.append(scene.text(pid + "-desc", x + pad, dy, cw - 2 * pad, dh, p["short"], font=c.bf, weight=400, size=3.1 * u * k, color=pal["muted"], lh=1.6,
                                  max_lines=max(1, int(dh // (3.1 * u * k * 1.6))), align="right"))
        if price:
            _pill(c, els, pid + "-price", x + pad, yy + ch - pad - price_h, price, size=3.5 * u * k, fill=pal["primary"], color=pal["on_primary"], h=price_h, max_w=cw - 2 * pad)
        if c.s.get("show_sku") and p.get("sku"):
            els.append(scene.text(pid + "-sku", x + cw / 2, yy + ch - pad - price_h, cw / 2 - pad, price_h, p["sku"], font=c.bf, size=2.8 * u * k, color=pal["muted"],
                                  align="right", valign="middle", max_lines=1))
    _footer(c, els)
    return {"bg": pal["bg"], "elements": els}


# ───────────────────────────── محصولِ ویژه

def hero(spec: dict, c: Ctx) -> dict:
    pal, u, W, H, m = c.pal, c.u, c.W, c.H, c.m
    els: list[dict] = []
    items = _pids({"products": [spec.get("product")]}, c)
    if not items:
        return {"bg": pal["bg"], "elements": els}
    p = items[0]
    pid = f"p{p['id']}"
    ih = H * 0.50
    ref = (p.get("images") or [""])[0]
    if ref:
        els.append(scene.image(pid + "-img", -c.bleed, -c.bleed, W + 2 * c.bleed, ih + c.bleed, ref, role="product-image", alt=p["name"]))
    else:
        els.append(scene.rect(pid + "-img", -c.bleed, -c.bleed, W + 2 * c.bleed, ih + c.bleed, gradient(135, (0, pal["secondary"], 1), (1, pal["primary"], 1))))
    els.append(scene.rect("shade", -c.bleed, ih * 0.42, W + 2 * c.bleed, ih * 0.58, gradient(90, (0, "#000000", 0.0), (1, "#000000", 0.72)), role="decor"))
    if p.get("category"):
        els.append(scene.text("kicker", m, ih - 31 * u, c.cw, 5 * u, p["category"], font=c.bf, weight=600, size=3.6 * u, color=pal["accent"], max_lines=1, align="right"))
    els.append(scene.text(pid + "-name", m, ih - 25 * u, c.cw, 22 * u, spec.get("title") or p["name"], font=c.hf, weight=800, size=10 * u, color="#ffffff", lh=1.25,
                          max_lines=2, shrink=0.4, align="right"))
    y = ih + 9 * u
    body = spec.get("text") or p.get("desc") or p.get("short") or ""
    bh = min(H * 0.20, 60 * u)
    if body:
        els.append(scene.text(pid + "-desc", m, y, c.cw, bh, body, font=c.bf, weight=400, size=4.1 * u, color=pal["text"], lh=1.8, shrink=0.25, max_lines=9, align="right"))
        y += min(bh, typeset.layout_text(c.T(body), font=c.bf, size=4.1 * u, w=c.cw, h=bh, lh=1.8, shrink=0.25, max_lines=9)["h"]) + 5 * u
    points = [str(x) for x in (spec.get("points") or []) if str(x).strip()]
    if not points:
        points = [f"{k}: {v}" for k, v in (p.get("attrs") or [])][:6] or [str(t) for t in (p.get("tags") or [])][:6]
    cx = c.W - m
    cy = y
    for i, pt in enumerate(points[:8]):
        wt = typeset.measure(pt, c.bf, 500, 3.3 * u) + 7 * u
        if cx - wt < m:
            cx = c.W - m
            cy += 9.5 * u
        if cy + 8 * u > H - m - 34 * u:
            break
        els.append(scene.rect(f"pt{i}-bg", cx - wt, cy, wt, 8 * u, pal["light"], radius=4 * u))
        els.append(scene.text(f"pt{i}", cx - wt, cy, wt, 8 * u, pt, font=c.bf, weight=500, size=3.3 * u, color=pal["primary"], align="center", valign="middle", max_lines=1, shrink=0.3))
        cx -= wt + 3 * u
    price = c.price(p)
    by = H - m - 38 * u
    if price:
        els.append(scene.rect("pricebox", m, by, 72 * u, 22 * u, pal["primary"], radius=4 * u))
        els.append(scene.text(pid + "-price", m + 4 * u, by + 3 * u, 64 * u, 11 * u, price, font=c.hf, weight=800, size=7.2 * u, color=pal["on_primary"], align="center", valign="middle",
                              max_lines=1, shrink=0.4))
        if p.get("compare_at") and p.get("price") and p["compare_at"] > p["price"]:
            els.append(scene.text(pid + "-old", m + 4 * u, by + 14 * u, 64 * u, 6 * u, c.price({**p, "price": p["compare_at"]}), font=c.bf, size=3.4 * u, color=pal["on_primary"],
                                  opacity=0.8, align="center", max_lines=1, strike=True))
    info = []
    if p.get("sku") and c.s.get("show_sku"):
        info.append(f"کد: {p['sku']}")
    if p.get("brand"):
        info.append(p["brand"])
    if info:
        els.append(scene.text(pid + "-info", W - m - 80 * u, by + 6 * u, 80 * u, 10 * u, " · ".join(info), font=c.bf, size=3.4 * u, color=pal["muted"], align="right", max_lines=2))
    _footer(c, els)
    return {"bg": pal["bg"], "elements": els}


# ───────────────────────────── فهرستِ قیمت

def price_list(spec: dict, c: Ctx) -> dict:
    pal, u = c.pal, c.u
    els: list[dict] = []
    items = _pids(spec, c)
    y = _heading(c, els, spec.get("title") or "فهرستِ قیمت", kicker=spec.get("kicker", ""))
    hh = 9 * u
    els.append(scene.rect("thead", c.m, y, c.cw, hh, pal["primary"], radius=[2 * u, 2 * u, 0, 0]))
    els.append(scene.text("th-name", c.m + 4 * u, y, c.cw - 60 * u, hh, "محصول", font=c.bf, weight=700, size=3.5 * u, color=pal["on_primary"], valign="middle", align="right", max_lines=1))
    show_sku = c.s.get("show_sku")
    if show_sku:
        els.append(scene.text("th-sku", c.m + 52 * u, y, 30 * u, hh, "کد", font=c.bf, weight=700, size=3.5 * u, color=pal["on_primary"], valign="middle", align="center", max_lines=1))
    els.append(scene.text("th-price", c.m + 4 * u, y, 48 * u, hh, "قیمت", font=c.bf, weight=700, size=3.5 * u, color=pal["on_primary"], valign="middle", align="left", max_lines=1))
    y += hh
    avail = c.H - c.m - 10 * u - y
    rh = min(16 * u, avail / max(1, min(len(items), 16)))
    for i, p in enumerate(items[:16]):
        ry = y + i * rh
        pid = f"p{p['id']}"
        els.append(scene.rect(pid + "-row", c.m, ry, c.cw, rh, pal["surface"] if i % 2 == 0 else pal["light"]))
        th = rh - 3 * u
        _product_image(c, els, pid + "-img", p, c.W - c.m - th - 2 * u, ry + 1.5 * u, th, th, 1.5 * u)
        els.append(scene.text(pid + "-name", c.m + (62 * u if show_sku else 52 * u), ry + 1 * u, c.cw - th - 8 * u - (62 * u if show_sku else 52 * u), 6 * u, p["name"], font=c.bf, weight=700,
                              size=3.8 * u, color=pal["text"], max_lines=1, shrink=0.3, align="right", valign="middle"))
        if p.get("short"):
            els.append(scene.text(pid + "-desc", c.m + (62 * u if show_sku else 52 * u), ry + 7 * u, c.cw - th - 8 * u - (62 * u if show_sku else 52 * u), rh - 8 * u, p["short"], font=c.bf, size=2.8 * u,
                                  color=pal["muted"], max_lines=1, align="right"))
        if show_sku:
            els.append(scene.text(pid + "-sku", c.m + 52 * u, ry, 30 * u, rh, p.get("sku", ""), font=c.bf, size=3 * u, color=pal["muted"], align="center", valign="middle", max_lines=1))
        els.append(scene.text(pid + "-price", c.m + 4 * u, ry, 48 * u, rh, c.price(p), font=c.bf, weight=700, size=3.7 * u, color=pal["primary"], align="left", valign="middle",
                              max_lines=1, shrink=0.3))
    els.append(scene.line("tfoot", c.m, y + min(len(items), 16) * rh, c.W - c.m, y + min(len(items), 16) * rh, pal["primary"], 0.5 * u))
    if c.s.get("show_prices", True):
        els.append(scene.text("note", c.m, y + min(len(items), 16) * rh + 2 * u, c.cw, 6 * u, spec.get("note", ""), font=c.bf, size=2.9 * u, color=pal["muted"], max_lines=2, align="right"))
    _footer(c, els)
    return {"bg": pal["bg"], "elements": els}


# ───────────────────────────── لوک‌بوک

def lookbook(spec: dict, c: Ctx) -> dict:
    pal, u, W, H, m = c.pal, c.u, c.W, c.H, c.m
    els: list[dict] = []
    refs = [r for r in (spec.get("images") or []) if r][:5]
    caps = spec.get("captions") or []
    if not refs:
        return {"bg": pal["bg"], "elements": els}

    def cap(i: int, x: float, y: float, w: float, h: float) -> None:
        t = caps[i] if i < len(caps) else ""
        if t:
            els.append(scene.rect(f"cap{i}-shade", x, y + h - 14 * u, w, 14 * u, gradient(90, (0, "#000000", 0.0), (1, "#000000", 0.65)), radius=[0, 0, 2.5 * u, 2.5 * u], role="decor"))
            els.append(scene.text(f"cap{i}", x + 4 * u, y + h - 11 * u, w - 8 * u, 8 * u, t, font=c.bf, weight=600, size=3.8 * u, color="#ffffff", max_lines=1, shrink=0.3, align="right", valign="middle"))

    if len(refs) == 1:
        els.append(scene.image("img0", -c.bleed, -c.bleed, W + 2 * c.bleed, H + 2 * c.bleed, refs[0], role="image"))
        if caps and caps[0]:
            els.append(scene.rect("cap0-shade", -c.bleed, H * 0.78, W + 2 * c.bleed, H * 0.22 + c.bleed, gradient(90, (0, "#000000", 0.0), (1, "#000000", 0.7)), role="decor"))
            els.append(scene.text("cap0", m, H - m - 16 * u, c.cw, 14 * u, caps[0], font=c.hf, weight=800, size=8 * u, color="#ffffff", max_lines=2, shrink=0.4, align="right"))
        return {"bg": pal["dark"], "elements": els}
    y0 = _heading(c, els, spec.get("title") or "لوک‌بوک", kicker=spec.get("kicker", ""))
    area_b = H - m - 10 * u
    gap = 4 * u
    ah = area_b - y0
    if len(refs) == 2:
        h1 = (ah - gap) / 2
        for i in range(2):
            yy = y0 + i * (h1 + gap)
            els.append(scene.image(f"img{i}", m, yy, c.cw, h1, refs[i], radius=3 * u, role="image"))
            cap(i, m, yy, c.cw, h1)
    else:
        big_h = ah * 0.56
        els.append(scene.image("img0", m, y0, c.cw, big_h, refs[0], radius=3 * u, role="image"))
        cap(0, m, y0, c.cw, big_h)
        rest = refs[1:]
        n = len(rest)
        sw = (c.cw - gap * (n - 1)) / n
        sh = ah - big_h - gap
        for i, r in enumerate(rest):
            x = W - m - sw - i * (sw + gap)
            els.append(scene.image(f"img{i + 1}", x, y0 + big_h + gap, sw, sh, r, radius=3 * u, role="image"))
            cap(i + 1, x, y0 + big_h + gap, sw, sh)
    _footer(c, els)
    return {"bg": pal["bg"], "elements": els}


# ───────────────────────────── پشتِ جلد

def back(spec: dict, c: Ctx) -> dict:
    pal, u, W, H, m = c.pal, c.u, c.W, c.H, c.m
    els = [scene.ellipse("deco1", -W * 0.2, -H * 0.1, W * 0.8, W * 0.8, pal["primary"], opacity=0.30, role="decor"),
           scene.ellipse("deco2", W * 0.5, H * 0.65, W * 0.9, W * 0.9, pal["accent"], opacity=0.07, role="decor")]
    y = H * 0.26
    if c.has_logo:
        _logo_tile(c, els, W / 2 - 15 * u, y - 36 * u, 30 * u)
    els.append(scene.text("title", m, y, c.cw, 14 * u, spec.get("title") or c.store_name, font=c.hf, weight=800, size=11 * u, color="#ffffff", align="center", max_lines=1, shrink=0.4))
    text = spec.get("text") or ""
    if text:
        els.append(scene.text("text", m + 10 * u, y + 18 * u, c.cw - 20 * u, 40 * u, text, font=c.bf, size=4.4 * u, color="#ffffff", opacity=0.92, lh=1.85, align="center", max_lines=6, shrink=0.2))
    contacts = [x for x in (spec.get("contacts") or c.contacts) if isinstance(x, dict) and x.get("value")]
    cy = H * 0.60
    for i, ct in enumerate(contacts[:6]):
        els.append(scene.text(f"ct{i}", m + 12 * u, cy + i * 9 * u, c.cw - 24 * u, 8 * u, f"{ct.get('label', '')}: {ct['value']}" if ct.get("label") else ct["value"], font=c.bf, weight=500,
                              size=4 * u, color="#ffffff", align="center", max_lines=1, shrink=0.3, valign="middle",
                              **({"link": {"url": ("mailto:" if ct.get("kind") == "email" else "https://") + ct["value"].replace("https://", "").replace("http://", "")}}
                                 if ct.get("kind") in ("website", "email") else {})))
    return {"bg": gradient(160, (0, pal["dark"], 1), (1, pal["secondary"], 1)), "elements": els}


BUILDERS = {"cover": cover, "toc": toc, "text": text_page, "grid": grid, "hero": hero, "price_list": price_list, "lookbook": lookbook, "steps": steps_page,
            "divider": divider, "back": back}


def page_title(spec: dict, c: Ctx) -> str:
    """عنوانِ صفحه در فهرست."""
    t = spec.get("title")
    if t:
        return str(t)
    if spec["type"] == "hero":
        p = c.products.get(int(spec.get("product") or 0))
        return p["name"] if p else "محصولِ ویژه"
    if spec["type"] == "back":
        return "تماس با ما"
    return PAGE_TYPE_FA.get(spec["type"], spec["type"])


def build_page(spec: dict, c: Ctx) -> dict:
    """مشخصهٔ صفحه ⇒ صفحهٔ صحنه (هنوز finalize نشده)."""
    fn = BUILDERS.get(spec.get("type"))
    if fn is None:
        raise ValueError(f"نوعِ صفحهٔ «{spec.get('type')}» ناشناخته است.")
    built = fn(spec, c)
    els = scene.apply_overrides(built["elements"], spec.get("overrides"), spec.get("extra"))
    return {"id": spec["id"], "name": page_title(spec, c), "type": spec["type"], "w": c.W, "h": c.H, "bleed": c.bleed, "bg": built["bg"], "elements": els,
            "notes": spec.get("notes", ""), "unit": "mm"}
