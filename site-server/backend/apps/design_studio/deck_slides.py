"""قالب‌های اسلاید (۱۹۲۰×۱۰۸۰ پیکسل): عنوان، فهرست، متن، محصول، مقایسه، آمار، خط زمان، تیم، دعوت به اقدام، جداکننده و تصویر.

هر قالب یک «مشخصهٔ اسلاید» را به عنصرهای صحنه می‌دهد. جای‌گیرهای خالی (``ph``) خاکستری‌اند و در چک‌لیست می‌آیند — چیزی از خودمان نمی‌نویسیم.
«آمار» فقط با «منبع» معنا دارد: هر عدد زیرش منبعش را می‌نویسد و بدونِ منبع در بازبینی هشدار می‌گیرد (آمارِ بی‌پشتوانه ممنوع است).
"""
from __future__ import annotations

import re

from . import colors, scene, typeset
from .scene import gradient

#: «منبع»ی که مسیرِ فایلِ داخلی است («docs/…/brand-facts-fa.md — بخش ۲») برای تماشاگر معنا ندارد؛ فقط در دادهٔ سند و بازبینی می‌ماند
_INTERNAL_SOURCE = re.compile(r"(?:^|[\s/(])docs/|[\w.-]+\.(?:md|py|txt|json|csv)\b", re.I)


def public_source(src: str) -> str:
    """نوشتهٔ «منبع» که روی اسلاید چاپ می‌شود؛ مسیرِ فایلِ داخلی ⇒ "" (چاپ نمی‌شود)."""
    src = str(src or "").strip()
    return "" if _INTERNAL_SOURCE.search(src) else src

SLIDE_TYPES = ("title", "agenda", "text", "product", "comparison", "stats", "timeline", "team", "cta", "section", "image")
SLIDE_TYPE_FA = {"title": "عنوان", "agenda": "فهرست مطالب", "text": "متن و نکته‌ها", "product": "معرفیِ محصول", "comparison": "مقایسه", "stats": "آمار (از دادهٔ واقعی)",
                 "timeline": "خط زمان / گام‌ها", "team": "تیم", "cta": "دعوت به اقدام", "section": "جداکننده", "image": "تصویر تمام‌صفحه"}
TEMPLATES = {"clean": "روشن و ساده", "bold": "پررنگ با رنگِ برند", "dark": "تیره", "soft": "ملایم"}
DEFAULTS = {"template": "clean", "look": "", "colors": None, "heading_font": "", "body_font": "", "digits": "fa", "show_prices": True, "zero_price_label": "رایگان",
            "slide_numbers": True, "show_logo": True, "footer_text": ""}
W, H = scene.SLIDE_SIZE
M = 96.0


class Ctx:
    def __init__(self, settings: dict, kit: dict, products: dict[int, dict], store_name: str, contacts: list[dict], has_logo: bool):
        self.s = {**DEFAULTS, **(settings or {})}
        self.kit = kit
        self.light = kit["palette"]
        self.dark = kit["dark"]
        self.products = products
        self.store_name = store_name
        self.contacts = contacts
        self.has_logo = has_logo and bool(self.s.get("show_logo", True))
        self.hf, self.bf = kit["fonts"]["heading"], kit["fonts"]["body"]
        self.digits = self.s.get("digits", "fa")
        self.index = 0
        self.total = 1

    def T(self, t) -> str:
        return typeset.digits(t, self.digits)

    def theme(self, kind: str) -> dict:
        """kind: «hero» (عنوان/جداکننده/دعوت) یا «body»؛ ⇒ {bg، fg، muted، primary، accent، surface، line، on_primary}."""
        tpl = self.s.get("template", "clean")
        L, D = self.light, self.dark
        if tpl == "dark":
            return {"bg": D["bg"], "fg": D["text"], "muted": D["muted"], "primary": D["primary"], "accent": D["accent"], "surface": D["surface"], "line": D["line"],
                    "on_primary": D["on_primary"], "dark": True}
        if kind == "hero" or tpl == "bold" and kind == "hero":
            bg = gradient(135, (0, L["secondary"], 1), (1, L["primary"], 1))
            return {"bg": bg, "fg": "#ffffff", "muted": colors.mix("#ffffff", L["secondary"], 0.25), "primary": L["accent"], "accent": L["accent"], "surface": colors.mix(L["secondary"], "#ffffff", 0.12),
                    "line": colors.mix(L["secondary"], "#ffffff", 0.3), "on_primary": colors.on_color(L["accent"]), "dark": True}
        if tpl == "soft":
            return {"bg": L["light"], "fg": L["text"], "muted": L["muted"], "primary": L["primary"], "accent": L["accent"], "surface": "#ffffff", "line": L["line"],
                    "on_primary": L["on_primary"], "dark": False}
        if tpl == "bold":
            return {"bg": L["bg"], "fg": L["text"], "muted": L["muted"], "primary": L["primary"], "accent": L["accent"], "surface": "#ffffff", "line": L["line"],
                    "on_primary": L["on_primary"], "dark": False}
        return {"bg": "#ffffff", "fg": L["text"], "muted": L["muted"], "primary": L["primary"], "accent": L["accent"], "surface": L["bg"], "line": L["line"],
                "on_primary": L["on_primary"], "dark": False}

    def price(self, p: dict) -> str:
        if not self.s.get("show_prices", True):
            return ""
        return typeset.price_text(p.get("price"), p.get("currency", "IRT"), self.digits, self.s.get("zero_price_label", "رایگان"))


def _t(ctx: Ctx, els: list, id: str, x, y, w, h, text, *, ph_text: str = "", size=36, weight=400, color=None, th=None, font=None, **kw) -> None:
    """متن؛ اگر خالی بود جای‌گیرِ خاکستری (ph) می‌گذارد."""
    th = th or {}
    if str(text or "").strip():
        els.append(scene.text(id, x, y, w, h, text, font=font or ctx.bf, weight=weight, size=size, color=color or th.get("fg", "#111827"), **kw))
    elif ph_text:
        els.append(scene.text(id, x, y, w, h, ph_text, font=font or ctx.bf, weight=weight, size=size, color=th.get("muted", "#94a3b8"), ph=True, **kw))


def _logo(ctx: Ctx, els: list, x: float, y: float, size: float, th: dict) -> None:
    if not ctx.has_logo:
        return
    els.append(scene.rect("logo-tile", x, y, size, size, "#ffffff", radius=size * 0.22, shadow={"dx": 0, "dy": 4, "blur": 14, "color": "#000000", "opacity": 0.15}))
    els.append(scene.image("logo", x + size * 0.14, y + size * 0.14, size * 0.72, size * 0.72, "logo", fit="contain", role="logo", alt=ctx.store_name))


def _chrome(ctx: Ctx, els: list, th: dict) -> None:
    if ctx.s.get("slide_numbers", True):
        els.append(scene.text("sl-num", M, H - 76, 140, 40, str(ctx.index + 1), font=ctx.bf, weight=700, size=26, color=th["primary"], align="left", valign="middle", max_lines=1, role="page-number"))
    foot = ctx.s.get("footer_text") or ctx.store_name
    els.append(scene.text("sl-foot", W - M - 600, H - 76, 600, 40, foot, font=ctx.bf, weight=500, size=24, color=th["muted"], align="right", valign="middle", max_lines=1, role="footer"))


def _title(ctx: Ctx, els: list, spec: dict, th: dict, *, ph: str = "عنوانِ اسلاید", kicker: str = "") -> float:
    y = 64.0
    if kicker:
        els.append(scene.text("kicker", M, y, W - 2 * M, 36, kicker, font=ctx.bf, weight=600, size=28, color=th["primary"], max_lines=1, align="right"))
        y += 40
    _t(ctx, els, "title", M, y, W - 2 * M, 96, spec.get("title"), ph_text=ph, size=64, weight=800, th=th, font=ctx.hf, lh=1.25, max_lines=1, shrink=0.4, align="right")
    els.append(scene.rect("bar", W - M - 120, y + 92, 120, 8, th["primary"], radius=4))
    return y + 140


def _product_ref(ctx: Ctx, spec: dict) -> dict | None:
    try:
        return ctx.products.get(int(spec.get("product")))
    except (TypeError, ValueError):
        return None


# ───────────────────────────── اسلایدها

def s_title(spec, ctx):
    th = ctx.theme("hero")
    els = [scene.ellipse("deco1", W * 0.52, -H * 0.35, W * 0.7, W * 0.7, "#ffffff", opacity=0.06, role="decor"),
           scene.ellipse("deco2", -W * 0.15, H * 0.5, W * 0.5, W * 0.5, th["accent"], opacity=0.10, role="decor")]
    _logo(ctx, els, W - M - 120, 72, 120, th)
    img = spec.get("image")
    tw = W - 2 * M - (640 if img else 0)
    if spec.get("kicker"):
        els.append(scene.text("kicker", W - M - tw, 330, tw, 44, spec["kicker"], font=ctx.bf, weight=600, size=34, color=th["accent"], align="right", max_lines=1))
    _t(ctx, els, "title", W - M - tw, 390, tw, 300, spec.get("title"), ph_text="عنوانِ ارائه", size=112, weight=800, th=th, font=ctx.hf, lh=1.2, max_lines=3, shrink=0.45, align="right")
    els.append(scene.rect("bar", W - M - 180, 372, 180, 10, th["accent"], radius=5))
    _t(ctx, els, "subtitle", W - M - tw, 720, tw, 150, spec.get("subtitle"), ph_text="زیرعنوان", size=42, weight=400, th=th, lh=1.6, max_lines=3, shrink=0.2, align="right", opacity=0.9)
    if spec.get("date"):
        els.append(scene.text("date", W - M - tw, 920, 700, 52, spec["date"], font=ctx.bf, weight=500, size=30, color=th["fg"], opacity=0.8, align="right", max_lines=1))
    if img:
        els.append(scene.image("image", M, 190, 520, 700, img, radius=36, role="image", shadow={"dx": 0, "dy": 14, "blur": 40, "color": "#000000", "opacity": 0.35}))
    return th, els


def s_agenda(spec, ctx):
    th = ctx.theme("body")
    els: list[dict] = []
    y = _title(ctx, els, spec, th, ph="دستورِ جلسه")
    items = [str(i) for i in (spec.get("items") or []) if str(i).strip()][:8]
    if not items:
        _t(ctx, els, "item0", M, y, W - 2 * M, 60, "", ph_text="موضوع‌ها را بنویس", size=36, th=th, align="right")
    n = len(items)
    cols = 2 if n > 4 else 1
    per = (n + cols - 1) // cols
    colw = (W - 2 * M - (60 if cols == 2 else 0)) / cols
    rh = min(120, (H - 140 - y) / max(1, per))
    for i, it in enumerate(items):
        c, r = divmod(i, per)
        x = W - M - colw - c * (colw + 60)
        yy = y + r * rh
        els.append(scene.rect(f"row{i}", x, yy, colw, rh - 18, th["surface"], radius=22, stroke={"color": th["line"], "w": 2}))
        els.append(scene.ellipse(f"dot{i}", x + colw - 84, yy + (rh - 18 - 60) / 2, 60, 60, th["primary"]))
        els.append(scene.text(f"num{i}", x + colw - 84, yy + (rh - 18 - 60) / 2, 60, 60, str(i + 1), font=ctx.hf, weight=800, size=30, color=th["on_primary"], align="center", valign="middle", max_lines=1))
        els.append(scene.text(f"item{i}", x + 32, yy, colw - 140, rh - 18, it, font=ctx.bf, weight=600, size=36, color=th["fg"], valign="middle", max_lines=2, shrink=0.25, align="right"))
    _chrome(ctx, els, th)
    return th, els


def s_text(spec, ctx):
    th = ctx.theme("body")
    els: list[dict] = []
    y = _title(ctx, els, spec, th)
    img = spec.get("image")
    tw = W - 2 * M - (720 if img else 0)
    bullets = [str(b) for b in (spec.get("bullets") or []) if str(b).strip()][:8]
    if not bullets and spec.get("text"):
        bullets = [spec["text"]]
    if not bullets:
        _t(ctx, els, "b0", W - M - tw, y, tw, 70, "", ph_text="نکته‌ها را بنویس", size=38, th=th, align="right")
    avail = H - 130 - y
    rh = min(130, avail / max(1, len(bullets)))
    for i, b in enumerate(bullets):
        yy = y + i * rh
        els.append(scene.ellipse(f"bul{i}", W - M - 22, yy + 24, 22, 22, th["primary"]))
        els.append(scene.text(f"b{i}", W - M - tw, yy + 6, tw - 60, rh - 6, b, font=ctx.bf, weight=400, size=38, color=th["fg"], lh=1.55, max_lines=3, shrink=0.25, align="right"))
    if img:
        els.append(scene.image("image", M, y, 620, H - 130 - y, img, radius=32, role="image", shadow={"dx": 0, "dy": 10, "blur": 30, "color": "#000000", "opacity": 0.18}))
    _chrome(ctx, els, th)
    return th, els


def s_product(spec, ctx):
    th = ctx.theme("body")
    els: list[dict] = []
    p = _product_ref(ctx, spec)
    y = 0.0
    if p is None:
        _t(ctx, els, "title", M, 70, W - 2 * M, 100, "", ph_text="یک محصول را انتخاب کن", size=56, weight=800, th=th, font=ctx.hf, align="right")
        _chrome(ctx, els, th)
        return th, els
    pid = f"p{p['id']}"
    ref = (p.get("images") or [""])[0]
    iw = 760
    if ref:
        els.append(scene.image(pid + "-img", M, 110, iw, H - 260, ref, radius=40, role="product-image", alt=p["name"], shadow={"dx": 0, "dy": 14, "blur": 36, "color": "#000000", "opacity": 0.22}))
    else:
        els.append(scene.rect(pid + "-img", M, 110, iw, H - 260, gradient(135, (0, th["accent"], 1), (1, th["primary"], 1)), radius=40))
        els.append(scene.text(pid + "-ch", M, 110, iw, H - 260, p["name"][:1], font=ctx.hf, weight=800, size=300, color="#ffffff", opacity=0.5, align="center", valign="middle", max_lines=1))
    x = M + iw + 70
    tw = W - M - x
    if p.get("category"):
        els.append(scene.text("kicker", x, 110, tw, 40, p["category"], font=ctx.bf, weight=600, size=28, color=th["primary"], align="right", max_lines=1))
    els.append(scene.text(pid + "-name", x, 154, tw, 170, spec.get("title") or p["name"], font=ctx.hf, weight=800, size=62, color=th["fg"], lh=1.25, max_lines=3, shrink=0.4, align="right"))
    body = spec.get("text") or p.get("short") or p.get("desc") or ""
    els.append(scene.text(pid + "-desc", x, 340, tw, 250, body, font=ctx.bf, size=32, color=th["muted"] if th.get("dark") else colors.darken(th["fg"], 0.0), lh=1.7, max_lines=6, shrink=0.2, align="right"))
    points = [str(t) for t in (spec.get("points") or []) if str(t).strip()] or [f"{k}: {v}" for k, v in (p.get("attrs") or [])][:4]
    cy = 610.0
    limit = H - 270
    for i, pt in enumerate(points[:4]):
        lay = typeset.layout_text(ctx.T(pt), font=ctx.bf, weight=500, size=30, w=tw - 40, lh=1.4, max_lines=2)
        hh = max(46.0, lay["h"] + 6)
        if cy + hh > limit:
            break
        els.append(scene.ellipse(f"pt{i}-dot", W - M - 18, cy + 14, 18, 18, th["primary"]))
        els.append(scene.text(f"pt{i}", x, cy, tw - 40, hh, pt, font=ctx.bf, weight=500, size=30, color=th["fg"], lh=1.4, max_lines=2, shrink=0.15, align="right", valign="top"))
        cy += hh + 12
    price = ctx.price(p)
    if price:
        pw = min(tw, typeset.measure(price, ctx.hf, 800, 48) + 110)
        els.append(scene.rect(pid + "-price-bg", x, H - 250, pw, 100, th["primary"], radius=50))
        els.append(scene.text(pid + "-price", x, H - 250, pw, 100, price, font=ctx.hf, weight=800, size=48, color=th["on_primary"], align="center", valign="middle", max_lines=1, shrink=0.4))
    _chrome(ctx, els, th)
    return th, els


def s_comparison(spec, ctx):
    th = ctx.theme("body")
    els: list[dict] = []
    y = _title(ctx, els, spec, th, ph="مقایسه")
    cols = []
    for it in (spec.get("items") or [])[:3]:
        if not isinstance(it, dict):
            continue
        p = None
        try:
            p = ctx.products.get(int(it.get("product"))) if it.get("product") not in (None, "") else None
        except (TypeError, ValueError):
            p = None
        name = it.get("name") or (p["name"] if p else "")
        price = it.get("price") or (ctx.price(p) if p else "")
        pts = [str(x) for x in (it.get("points") or []) if str(x).strip()] or ([f"{k}: {v}" for k, v in (p.get("attrs") or [])][:5] if p else [])
        if p and not pts and p.get("short"):
            pts = [p["short"]]
        cols.append({"name": name, "price": price, "points": pts, "ref": (p.get("images") or [""])[0] if p else it.get("image", ""), "id": f"c{len(cols)}", "hi": bool(it.get("highlight"))})
    if not cols:
        _t(ctx, els, "c0", M, y, W - 2 * M, 70, "", ph_text="دو یا سه مورد را برای مقایسه انتخاب کن", size=38, th=th, align="right")
    n = max(1, len(cols))
    gap = 40
    cw = (W - 2 * M - gap * (n - 1)) / n
    ch = H - 130 - y
    for i, c in enumerate(cols):
        x = W - M - cw - i * (cw + gap)
        hl = c["hi"]
        els.append(scene.rect(c["id"] + "-card", x, y, cw, ch, th["primary"] if hl else th["surface"], radius=30, stroke=None if hl else {"color": th["line"], "w": 2},
                              shadow={"dx": 0, "dy": 8, "blur": 24, "color": "#000000", "opacity": 0.10}))
        fg = th["on_primary"] if hl else th["fg"]
        yy = y + 34
        els.append(scene.text(c["id"] + "-name", x + 34, yy, cw - 68, 110, c["name"], font=ctx.hf, weight=800, size=38, color=fg, lh=1.3, max_lines=2, shrink=0.35, align="right"))
        yy += 112
        if c["price"]:
            els.append(scene.text(c["id"] + "-price", x + 34, yy, cw - 68, 70, c["price"], font=ctx.hf, weight=800, size=46, color=th["accent"] if hl else th["primary"], align="right", max_lines=1, shrink=0.4))
            yy += 90
        els.append(scene.line(c["id"] + "-rule", x + 34, yy, x + cw - 34, yy, th["on_primary"] if hl else th["line"], 2, opacity=0.5))
        yy += 24
        per = max(1, int((y + ch - 30 - yy) // 78))
        for j, pt in enumerate(c["points"][:per]):
            els.append(scene.text(f"{c['id']}-pt{j}", x + 34, yy + j * 78, cw - 68, 70, pt, font=ctx.bf, weight=400, size=28, color=fg, lh=1.5, max_lines=2, shrink=0.2, align="right"))
    _chrome(ctx, els, th)
    return th, els


def s_stats(spec, ctx):
    th = ctx.theme("body")
    els: list[dict] = []
    y = _title(ctx, els, spec, th, ph="عددهایی که واقعی‌اند")
    items = [i for i in (spec.get("items") or []) if isinstance(i, dict)][:4]
    if not items:
        _t(ctx, els, "s0", M, y, W - 2 * M, 70, "", ph_text="آمارِ واقعی را همراهِ منبعش بنویس", size=38, th=th, align="right")
    n = max(1, len(items))
    gap = 36
    cw = (W - 2 * M - gap * (n - 1)) / n
    ch = 460
    for i, it in enumerate(items):
        x = W - M - cw - i * (cw + gap)
        sid = f"s{i}"
        els.append(scene.rect(sid + "-card", x, y + 20, cw, ch, th["surface"], radius=30, stroke={"color": th["line"], "w": 2}))
        els.append(scene.rect(sid + "-bar", x + cw - 12, y + 60, 8, 120, th["primary"], radius=4))
        val = str(it.get("value", ""))
        els.append(scene.text(sid + "-value", x + 24, y + 60, cw - 80, 150, val, font=ctx.hf, weight=800, size=96 if len(val) <= 8 else 60, color=th["primary"], align="right", valign="middle",
                              max_lines=1 if len(val) <= 8 else 2, shrink=0.45, lh=1.2))
        els.append(scene.text(sid + "-label", x + 24, y + 230, cw - 48, 110, it.get("label", ""), font=ctx.bf, weight=600, size=34, color=th["fg"], lh=1.4, max_lines=3, shrink=0.25, align="right"))
        src = str(it.get("source") or "").strip()
        shown = public_source(src)
        if shown:
            els.append(scene.text(sid + "-src", x + 24, y + 20 + ch - 90, cw - 48, 70, "منبع: " + shown, font=ctx.bf, size=22, color=th["muted"], lh=1.4, max_lines=2, align="right", valign="bottom"))
        elif src:
            pass                                    # منبعِ داخلی (مسیرِ فایل): در سند و بازبینی می‌ماند ولی روی اسلاید و ویدیو چاپ نمی‌شود
        else:
            els.append(scene.text(sid + "-src", x + 24, y + 20 + ch - 90, cw - 48, 70, "منبع را بنویس", font=ctx.bf, size=22, color=th["muted"], ph=True, align="right", valign="bottom"))
    _chrome(ctx, els, th)
    return th, els


def s_timeline(spec, ctx):
    th = ctx.theme("body")
    els: list[dict] = []
    y = _title(ctx, els, spec, th, ph="گام‌ها")
    steps = [s for s in (spec.get("steps") or []) if isinstance(s, dict)][:6]
    if not steps:
        _t(ctx, els, "t0", M, y, W - 2 * M, 70, "", ph_text="گام‌ها را بنویس", size=38, th=th, align="right")
    n = max(1, len(steps))
    cw = (W - 2 * M) / n
    ly = y + 90
    els.append(scene.rect("axis", M + cw / 2, ly + 28, (W - 2 * M) - cw, 6, th["line"], radius=3))
    for i, s in enumerate(steps):
        cx = W - M - cw / 2 - i * cw
        els.append(scene.ellipse(f"dot{i}", cx - 34, ly, 68, 68, th["primary"], stroke={"color": th["surface"], "w": 8}))
        els.append(scene.text(f"n{i}", cx - 34, ly, 68, 68, str(i + 1), font=ctx.hf, weight=800, size=34, color=th["on_primary"], align="center", valign="middle", max_lines=1))
        els.append(scene.text(f"t{i}", cx - cw / 2 + 14, ly + 100, cw - 28, 90, s.get("title", ""), font=ctx.hf, weight=800, size=34, color=th["fg"], align="center", lh=1.3, max_lines=2, shrink=0.3))
        els.append(scene.text(f"d{i}", cx - cw / 2 + 14, ly + 200, cw - 28, 300, s.get("text", ""), font=ctx.bf, size=26, color=th["muted"], align="center", lh=1.65, max_lines=7, shrink=0.15))
    _chrome(ctx, els, th)
    return th, els


def s_team(spec, ctx):
    th = ctx.theme("body")
    els: list[dict] = []
    y = _title(ctx, els, spec, th, ph="تیم")
    mem = [m for m in (spec.get("members") or []) if isinstance(m, dict)][:6]
    if not mem:
        _t(ctx, els, "m0", M, y, W - 2 * M, 70, "", ph_text="نامِ هر عضو و سمتش را بنویس (اطلاعاتِ واقعی)", size=38, th=th, align="right")
    n = max(1, len(mem))
    gap = 30
    cw = min(330.0, (W - 2 * M - gap * (n - 1)) / n)
    total = cw * n + gap * (n - 1)
    x0 = W - (W - total) / 2
    for i, m in enumerate(mem):
        x = x0 - cw - i * (cw + gap)
        mid = f"m{i}"
        els.append(scene.rect(mid + "-card", x, y + 20, cw, 520, th["surface"], radius=30, stroke={"color": th["line"], "w": 2}))
        d = min(220, cw - 60)
        px = x + (cw - d) / 2
        if m.get("photo"):
            els.append(scene.image(mid + "-photo", px, y + 60, d, d, m["photo"], radius=d / 2, role="image", alt=m.get("name", "")))
        else:
            els.append(scene.ellipse(mid + "-photo", px, y + 60, d, d, th["accent"]))
            els.append(scene.text(mid + "-init", px, y + 60, d, d, (m.get("name") or "؟")[:1], font=ctx.hf, weight=800, size=110, color=th["primary"], align="center", valign="middle", max_lines=1))
        els.append(scene.text(mid + "-name", x + 20, y + 60 + d + 30, cw - 40, 80, m.get("name", ""), font=ctx.hf, weight=800, size=34, color=th["fg"], align="center", lh=1.3, max_lines=2, shrink=0.3))
        els.append(scene.text(mid + "-role", x + 20, y + 60 + d + 120, cw - 40, 90, m.get("role", ""), font=ctx.bf, size=26, color=th["muted"], align="center", lh=1.4, max_lines=2, shrink=0.2))
    _chrome(ctx, els, th)
    return th, els


def s_cta(spec, ctx):
    th = ctx.theme("hero")
    els = [scene.ellipse("deco1", -W * 0.2, -H * 0.4, W * 0.6, W * 0.6, "#ffffff", opacity=0.07, role="decor"),
           scene.ellipse("deco2", W * 0.6, H * 0.45, W * 0.55, W * 0.55, th["accent"], opacity=0.12, role="decor")]
    _logo(ctx, els, W - M - 110, 72, 110, th)
    _t(ctx, els, "title", M + 200, 250, W - 2 * M - 200, 250, spec.get("title"), ph_text="دعوت به اقدام", size=96, weight=800, th=th, font=ctx.hf, lh=1.25, max_lines=2, shrink=0.45, align="right")
    _t(ctx, els, "text", M + 200, 520, W - 2 * M - 200, 150, spec.get("text"), ph_text="", size=40, th=th, lh=1.6, max_lines=3, shrink=0.2, align="right", opacity=0.92)
    btn = spec.get("button")
    if btn:
        bw = typeset.measure(btn, ctx.hf, 800, 44) + 150
        els.append(scene.rect("button-bg", W - M - bw, 720, bw, 110, th["accent"], radius=55, shadow={"dx": 0, "dy": 10, "blur": 28, "color": "#000000", "opacity": 0.25},
                              **({"link": {"url": spec["link"]}} if str(spec.get("link", "")).startswith(("http://", "https://")) else {})))
        els.append(scene.text("button", W - M - bw, 720, bw, 110, btn, font=ctx.hf, weight=800, size=44, color=th["on_primary"], align="center", valign="middle", max_lines=1, shrink=0.4))
    if spec.get("note"):
        els.append(scene.text("note", M + 200, 870, W - 2 * M - 200, 60, spec["note"], font=ctx.bf, size=28, color=th["fg"], opacity=0.85, align="right", max_lines=2))
    return th, els


def s_section(spec, ctx):
    th = ctx.theme("hero")
    els = [scene.ellipse("deco1", -W * 0.1, H * 0.35, W * 0.6, W * 0.6, "#ffffff", opacity=0.07, role="decor"),
           scene.rect("bar", W - M - 180, 410, 180, 10, th["accent"], radius=5)]
    _t(ctx, els, "title", M, 440, W - 2 * M, 260, spec.get("title"), ph_text="عنوانِ بخش", size=120, weight=800, th=th, font=ctx.hf, lh=1.2, max_lines=2, shrink=0.45, align="right")
    _t(ctx, els, "subtitle", M, 720, W - 2 * M - 300, 150, spec.get("subtitle"), ph_text="", size=42, th=th, lh=1.6, max_lines=2, align="right", opacity=0.9)
    return th, els


def s_image(spec, ctx):
    th = ctx.theme("hero")
    els = []
    if spec.get("image"):
        els.append(scene.image("image", 0, 0, W, H, spec["image"], role="image"))
        if spec.get("caption"):
            els.append(scene.rect("shade", 0, H * 0.7, W, H * 0.3, gradient(90, (0, "#000000", 0.0), (1, "#000000", 0.72)), role="decor"))
            els.append(scene.text("caption", M, H - 190, W - 2 * M, 130, spec["caption"], font=ctx.hf, weight=800, size=64, color="#ffffff", lh=1.3, max_lines=2, shrink=0.4, align="right"))
    else:
        els.append(scene.text("image-ph", M, H / 2 - 40, W - 2 * M, 80, "تصویر را انتخاب کن", font=ctx.bf, size=44, color=th["muted"], ph=True, align="center", max_lines=1))
    return th, els


BUILDERS = {"title": s_title, "agenda": s_agenda, "text": s_text, "product": s_product, "comparison": s_comparison, "stats": s_stats, "timeline": s_timeline, "team": s_team,
            "cta": s_cta, "section": s_section, "image": s_image}


def slide_title(spec: dict, ctx: Ctx) -> str:
    if spec.get("title"):
        return str(spec["title"])
    if spec["type"] == "product":
        p = _product_ref(ctx, spec)
        if p:
            return p["name"]
    return SLIDE_TYPE_FA.get(spec["type"], spec["type"])


def build_slide(spec: dict, ctx: Ctx) -> dict:
    fn = BUILDERS.get(spec.get("type"))
    if fn is None:
        raise ValueError(f"نوعِ اسلاید «{spec.get('type')}» ناشناخته است.")
    th, els = fn(spec, ctx)
    els = scene.apply_overrides(els, spec.get("overrides"), spec.get("extra"))
    bg = th["bg"]
    return {"id": spec["id"], "name": slide_title(spec, ctx), "type": spec["type"], "w": W, "h": H, "bleed": 0.0, "bg": bg, "elements": els, "notes": spec.get("notes", ""), "unit": "px"}
