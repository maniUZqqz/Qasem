"""بلوک‌های سایت‌ساز ⇒ گره‌های Auto Layout (طرحِ تقریباً نهایی برای فریم‌های UI).

همان نوع و مشخصه‌های بلوک‌های سایت‌ساز (``apps/projects/builder``): hero، features، pricing، faq، cta، gallery، nav، footer و ۴۹ «قطعهٔ آماده» (c_*).
رنگ‌ها ``var:<نقش>`` (یا ``var:<نقش>@<درصد>`` ⇒ آمیخته با زمینه) هستند تا حالتِ روشن/تیره با یک متغیر عوض شود. هر دستگاه (دسکتاپ، تبلت، گوشی)
اندازه و تعدادِ ستون‌های خودش را دارد.
"""
from __future__ import annotations

DEVICES = {
    "desktop": {"w": 1440.0, "px": 64.0, "py": 96.0, "h1": 60.0, "h2": 40.0, "h3": 26.0, "lead": 22.0, "body": 17.0, "small": 14.0, "cols": 3, "gap": 24.0, "maxw": 1200.0, "nav": 76.0},
    "tablet": {"w": 834.0, "px": 40.0, "py": 72.0, "h1": 46.0, "h2": 34.0, "h3": 24.0, "lead": 20.0, "body": 16.0, "small": 13.0, "cols": 2, "gap": 20.0, "maxw": 760.0, "nav": 68.0},
    "phone": {"w": 390.0, "px": 20.0, "py": 52.0, "h1": 34.0, "h2": 28.0, "h3": 21.0, "lead": 18.0, "body": 15.0, "small": 13.0, "cols": 1, "gap": 16.0, "maxw": 390.0, "nav": 60.0},
}


def _g(props: dict, key: str, default: str = "") -> str:
    v = props.get(key, default)
    return v if isinstance(v, str) else (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default)


def _items(props: dict, key: str = "items") -> list[dict]:
    v = props.get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in str(text or "").replace("\r", "").split("\n") if ln.strip()]


class Kit:
    """سازندهٔ گره‌ها برای یک دستگاه + توکن‌ها."""

    def __init__(self, device: str, tokens: dict, *, font_head: str, font_body: str, brand_name: str = "", has_logo: bool = False, menu: list[str] | None = None,
                 links: dict | None = None):
        self.d = DEVICES[device]
        self.device = device
        self.t = tokens
        self.fh, self.fb = font_head, font_body
        self.brand = brand_name
        self.has_logo = has_logo
        self.menu = menu or []
        self.radius = float(tokens.get("radius", 14))
        self.links = links or {}
        self.phone = device == "phone"

    # ---- ساخت‌ها ----
    def text(self, text, size=None, weight=400, color="var:text", **kw) -> dict:
        n = {"t": "text", "text": text, "size": size or self.d["body"], "weight": weight, "color": color, "font": kw.pop("font", self.fb), "lh": kw.pop("lh", 1.6)}
        n.update(kw)
        return n

    def head(self, text, size=None, color="var:text", **kw) -> dict:
        return self.text(text, size or self.d["h2"], 800, color, font=self.fh, lh=kw.pop("lh", 1.3), **kw)

    def frame(self, children, **kw) -> dict:
        n = {"t": "frame", "dir": kw.pop("dir", "v"), "children": [c for c in children if c]}
        n.update(kw)
        return n

    def spacer(self, h) -> dict:
        return {"t": "spacer", "h": h, "w": "fill"}

    def button(self, label, variant="filled", link=None, size=None, id=None) -> dict:
        if not label:
            return {}
        fill = {"filled": "var:primary", "soft": "var:primary@14", "outline": None, "dark": "var:text"}.get(variant, "var:primary")
        fg = {"filled": "var:on_primary", "soft": "var:primary", "outline": "var:text", "dark": "var:bg"}.get(variant, "var:on_primary")
        stroke = {"color": "var:line", "w": 1.5} if variant == "outline" else None
        pad_y = 14 if not self.phone else 12
        r = 999 if self.t.get("button") == "round" else self.radius * 0.8
        node = self.frame([self.text(label, size or self.d["body"], 700, fg, font=self.fh, lh=1.2, align="center", w="hug")], dir="h", pad=[pad_y, 26, pad_y, 26],
                          fill=fill, radius=r, stroke=stroke, w="hug", align="center", justify="center", name=f"دکمه: {label}"[:40])
        if link:
            node["link"] = link
        if id:
            node["id"] = id
        return node

    def icon(self, size=52) -> dict:
        return self.frame([{"t": "rect", "w": size * 0.38, "h": size * 0.38, "fill": "var:primary", "radius": size * 0.12}], dir="z", w=size, h=size, fill="var:primary@14",
                          radius=size * 0.28, align="center", valign="center", name="نماد")

    def image(self, ratio=0.6, src="", radius=None, w="fill", alt="", **kw) -> dict:
        """تصویر؛ مرجعِ ناشناخته (یا خالی) ⇒ جای‌تصویر (طوسی با ضربدر) — هرگز تصویرِ ساختگی نمی‌گذاریم."""
        node = {"t": "image", "src": src if isinstance(src, str) and not src.startswith(("m:", "http")) else "", "w": w, "ratio": ratio,
                "radius": self.radius if radius is None else radius, "alt": alt}
        node.update(kw)
        return node

    def card(self, children, **kw) -> dict:
        n = self.frame(children, pad=22 if not self.phone else 18, gap=10, fill="var:surface", radius=self.radius, stroke={"color": "var:line", "w": 1.2},
                       shadow=self.t.get("shadow") or None, w="fill")
        n.update(kw)
        return n

    def grid(self, children, cols=None, gap=None, **kw) -> dict:
        return self.frame(children, dir="grid", cols=cols or self.d["cols"], gap=gap or self.d["gap"], w="fill", **kw)

    def section(self, children, bg=None, py=None, id=None, name="", align_center=False, gap=None) -> dict:
        d = self.d
        inner = self.frame(children, gap=gap if gap is not None else (36 if not self.phone else 24), w="fill", max_w=d["maxw"], align="center" if align_center else "stretch")
        n = self.frame([inner], pad=[py if py is not None else d["py"], d["px"], py if py is not None else d["py"], d["px"]], fill=bg or "var:bg", w="fill", align="stretch", name=name)
        if id:
            n["id"] = id
        return n

    def title_block(self, props: dict, center=True, light=False) -> dict | None:
        title, sub = _g(props, "title"), _g(props, "subtitle")
        kids = []
        col = "#ffffff" if light else "var:text"
        if props.get("kicker") or props.get("eyebrow"):
            kids.append(self.pill(_g(props, "kicker") or _g(props, "eyebrow"), light))
        if title:
            kids.append(self.head(title, color=col, align="center" if center else "auto", w="fill", max_w=860))
        if sub:
            kids.append(self.text(sub, self.d["lead"] if not self.phone else self.d["body"], 400, "#ffffff" if light else "var:muted", align="center" if center else "auto", w="fill", max_w=720))
        return self.frame(kids, gap=12, align="center" if center else "stretch", w="fill") if kids else None

    def pill(self, text, light=False) -> dict:
        return self.frame([self.text(text, self.d["small"], 700, "#ffffff" if light else "var:primary", font=self.fh, lh=1.2, w="hug")], dir="h", pad=[6, 16, 6, 16],
                          fill="#ffffff@18" if light else "var:primary@14", radius=999, w="hug", name="برچسب")


# ───────────────────────────── ساختِ هر خانواده

def nav(k: Kit, props: dict, block_id: str) -> dict:
    d = k.d
    logo = props.get("logo") or k.has_logo
    brand = ([{"t": "image", "src": "logo", "w": 44, "h": 44, "fit": "contain", "radius": 8}] if logo and k.has_logo else []) + [k.text(k.brand or "نام برند", d["h3"] * 0.8, 800, "var:text", font=k.fh, w="hug", lh=1.2)]
    menu_items = [k.text(m, d["body"], 500, "var:text", w="hug", lh=1.2) for m in k.menu[:5]]
    btn = k.button(_g(props, "btn"), "filled", link=k.links.get(block_id))
    if k.phone:
        burger = k.frame([{"t": "rect", "w": 26, "h": 3, "fill": "var:text", "radius": 2} for _ in range(3)], gap=5, w=26, h=21, name="منو")
        row = k.frame([k.frame(brand, dir="h", gap=10, w="hug", align="center"), {"t": "spacer", "w": "fill", "h": 1, "grow": 1}, burger], dir="h", align="center", w="fill", pad=[0, 0, 0, 0])
    else:
        row = k.frame([k.frame(brand, dir="h", gap=12, w="hug", align="center"), k.frame(menu_items, dir="h", gap=30, w="fill", grow=1, align="center", justify="center") if menu_items else {"t": "spacer", "w": "fill", "h": 1, "grow": 1}, btn],
                      dir="h", align="center", w="fill", gap=24)
    n = k.frame([row], pad=[0, d["px"], 0, d["px"]], h=d["nav"], fill="var:bg", w="fill", stroke={"color": "var:line", "w": 1}, align="stretch", justify="center", name="سربرگ")
    n["id"] = block_id
    if props.get("announce"):
        bar = k.frame([k.text(_g(props, "announce"), d["small"], 600, "var:on_primary", align="center", w="fill")], pad=[8, 12, 8, 12], fill="var:primary", w="fill")
        return k.frame([bar, n], id=block_id, w="fill")
    return n


def hero(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    light = key in ("hero_gradient_banner",)
    split = key in ("hero_split_media", "hero_media_frame", "hero_video_thumb") or props.get("layout") == "split"
    center = not split
    col = "#ffffff" if light else "var:text"
    kids = []
    if props.get("kicker") or props.get("eyebrow"):
        kids.append(k.pill(_g(props, "kicker") or _g(props, "eyebrow"), light))
    kids.append(k.head(_g(props, "title", "تیتر"), d["h1"], col, align="center" if center else "auto", w="fill", lh=1.25))
    if props.get("subtitle"):
        kids.append(k.text(_g(props, "subtitle"), d["lead"] if not k.phone else d["body"], 400, "#ffffff" if light else "var:muted", align="center" if center else "auto", w="fill", max_w=720))
    btns = [k.button(_g(props, "btn1") or _g(props, "btn"), "filled" if not light else "dark", link=k.links.get(block_id)), k.button(_g(props, "btn2"), "outline" if not light else "soft")]
    btns = [b for b in btns if b]
    if btns:
        kids.append(k.frame(btns, dir="h" if not k.phone else "v", gap=14, w="hug" if not k.phone else "fill", align="center", justify="center" if center else "start"))
    if props.get("note"):
        kids.append(k.text(_g(props, "note"), d["small"], 400, "#ffffff" if light else "var:muted", align="center" if center else "auto", w="fill"))
    for b in _lines("\n".join(map(str, props.get("bullets") or []))) if isinstance(props.get("bullets"), list) else []:
        kids.append(k.text("✓ " + b, d["body"], 500, col, w="fill"))
    copy = k.frame(kids, gap=20 if not k.phone else 14, w="fill" if (center or k.phone) else None, grow=None if (center or k.phone) else 1, align="center" if center else "stretch")
    stats = props.get("stats") or props.get("badges")
    extra = []
    if isinstance(stats, list) and stats:
        cells = []
        for s in stats[:4]:
            if isinstance(s, dict):
                cells.append(k.frame([k.head(_g(s, "value") or _g(s, "title"), d["h3"], "var:primary" if not light else "#ffffff", align="center", w="fill"),
                                      k.text(_g(s, "label") or _g(s, "text"), d["small"], 500, "var:muted" if not light else "#ffffff", align="center", w="fill")], gap=4, w="fill", grow=1))
            elif isinstance(s, str):
                cells.append(k.pill(s, light))
        if cells:
            extra.append(k.frame(cells, dir="h" if not k.phone else "v", gap=24, w="fill", justify="center"))
    if split:
        img = k.image(0.78, _g(props, "image"), w="fill" if k.phone else 520, alt=_g(props, "image_alt") or "تصویرِ اصلی")
        body = copy if k.phone else k.frame([copy, img], dir="h", gap=48, w="fill", align="center")
        content = [body] if not k.phone else [copy, img]
    else:
        content = [copy] + extra
    bg = gradient_var() if light else ("var:bg" if key != "hero_center_glow" else "var:bg")
    n = k.section(content, bg=bg, py=d["py"] * (1.0 if not k.phone else 0.8), id=block_id, name="سربرگِ بزرگ", align_center=center, gap=40)
    if key == "hero_center_glow":
        n["children"] = [k.frame([{"t": "rect", "w": 460, "h": 460, "fill": "var:primary@10", "radius": 230, "abs": {"x": (d["w"] - 460) / 2 if not k.phone else -60, "y": 0}, "behind": True, "name": "درخشش"}] + n["children"], dir="z", w="fill", align="stretch")]
    return n


def gradient_var() -> dict:
    return {"type": "linear", "angle": 135, "stops": [[0, "var:primary", 1], [1, "var:secondary", 1]]}


def features(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    items = _items(props)
    head = k.title_block(props)
    bento = "bento" in key
    cards = []
    for i, it in enumerate(items[:9]):
        kids = [k.icon(48), k.head(_g(it, "title"), d["h3"] * 0.8, align="auto", w="fill", lh=1.3)]
        if it.get("text"):
            kids.append(k.text(_g(it, "text"), d["body"], 400, "var:muted", w="fill", lh=1.65))
        if it.get("link_text"):
            kids.append(k.text(_g(it, "link_text") + " ←", d["small"], 700, "var:primary", w="fill"))
        c = k.card(kids, gap=12)
        if bento and i == 0 and not k.phone:
            c["span"] = 2
        cards.append(c)
    if key in ("feat_icon_rows", "feat_checklist_split", "feat_alternating"):
        rows = [k.frame([k.icon(44), k.frame([k.head(_g(it, "title"), d["h3"] * 0.8, w="fill"), k.text(_g(it, "text"), d["body"], 400, "var:muted", w="fill")], gap=4, w="fill", grow=1)], dir="h", gap=16, w="fill", align="start")
                for it in items[:8]]
        body = k.frame(rows, gap=22, w="fill")
    else:
        body = k.grid(cards, cols=d["cols"] if not bento else (1 if k.phone else 3))
    return k.section([x for x in (head, body) if x], id=block_id, name="ویژگی‌ها")


def steps(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    items = _items(props)
    head = k.title_block(props)
    cells = []
    for i, it in enumerate(items[:6]):
        num = k.frame([k.text(str(i + 1), d["h3"] * 0.85, 800, "var:on_primary", font=k.fh, align="center", w="fill", lh=1.0)], w=48, h=48, fill="var:primary", radius=24, justify="center", align="center")
        cells.append(k.frame([num, k.head(_g(it, "title"), d["h3"] * 0.8, align="center" if not k.phone else "auto", w="fill"), k.text(_g(it, "text"), d["body"], 400, "var:muted", align="center" if not k.phone else "auto", w="fill")],
                             gap=10, w="fill", grow=1, align="center" if not k.phone else "stretch"))
    body = k.frame(cells, dir="h" if not k.phone else "v", gap=d["gap"] + 8, w="fill", align="start") if cells else None
    return k.section([x for x in (head, body) if x], id=block_id, name="گام‌ها")


def pricing(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    head = k.title_block(props)
    plans = _items(props)
    if key == "price_single_focus":
        plans = [{"name": _g(props, "name"), "price": _g(props, "price"), "period": _g(props, "period"), "features": _g(props, "features"), "button": _g(props, "button"), "link": _g(props, "link"), "highlight": True}]
    cards = []
    for p in plans[:4]:
        hi = bool(p.get("highlight"))
        fg = "var:on_primary" if hi else "var:text"
        feats = _lines(p.get("features", "")) if isinstance(p.get("features", ""), str) else [str(x) for x in p.get("features", [])]
        kids = [k.head(_g(p, "name"), d["h3"] * 0.8, fg, w="fill"),
                k.frame([k.head(_g(p, "price"), d["h2"] * 0.9, fg, w="hug"), k.text(_g(p, "period"), d["small"], 500, fg, w="hug")], dir="h", gap=8, w="fill", align="end")]
        kids += [k.text("✓ " + f, d["body"], 400, fg, w="fill") for f in feats[:7]]
        kids.append(k.button(_g(p, "button") or "انتخاب", "soft" if hi else "filled"))
        cards.append(k.card(kids, gap=12, fill="var:primary" if hi else "var:surface", stroke=None if hi else {"color": "var:line", "w": 1.2}))
    body = k.grid(cards, cols=min(len(cards) or 1, d["cols"])) if cards else None
    return k.section([x for x in (head, body) if x], id=block_id, name="قیمت‌ها")


def testimonials(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    head = k.title_block(props)
    items = _items(props)
    if key == "testi_big_quote":
        items = [{"text": _g(props, "text"), "name": _g(props, "name"), "role": _g(props, "role")}]
    cards = [k.card([k.text("“" + _g(it, "text") + "”", d["body"] * 1.05, 500, "var:text", w="fill", lh=1.75),
                     k.frame([{"t": "rect", "w": 40, "h": 40, "fill": "var:primary@20", "radius": 20}, k.frame([k.text(_g(it, "name"), d["body"], 700, "var:text", w="fill"), k.text(_g(it, "role"), d["small"], 400, "var:muted", w="fill")], gap=2, w="fill", grow=1)],
                             dir="h", gap=12, w="fill", align="center")], gap=16) for it in items[:6]]
    body = k.grid(cards, cols=min(d["cols"], max(1, len(cards)))) if cards else None
    return k.section([x for x in (head, body) if x], id=block_id, name="نظر مشتریان")


def faq(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    head = k.title_block(props)
    rows = []
    for it in _items(props)[:8]:
        rows.append(k.card([k.frame([k.head(_g(it, "q"), d["h3"] * 0.75, w="fill", grow=1), k.text("+", d["h3"], 700, "var:primary", w="hug")], dir="h", gap=12, w="fill", align="center"),
                            k.text(_g(it, "a"), d["body"], 400, "var:muted", w="fill")], gap=10))
    cols = 2 if key == "faq_cards_grid" and not k.phone else 1
    body = k.grid(rows, cols=cols) if rows else None
    if key == "faq_two_col" and not k.phone and head:
        btn = k.button(_g(props, "btn"), "outline")
        side = k.frame([x for x in (k.head(_g(props, "title"), d["h2"], w="fill"), k.text(_g(props, "subtitle"), d["body"], 400, "var:muted", w="fill"), btn) if x], gap=14, w=360)
        return k.section([k.frame([k.frame(rows, gap=14, w="fill", grow=1), side], dir="h", gap=48, w="fill", align="start")], id=block_id, name="پرسش‌ها")
    return k.section([x for x in (head, body) if x], id=block_id, name="پرسش‌ها")


def cta(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    btns = [b for b in (k.button(_g(props, "btn1") or _g(props, "btn"), "dark", link=k.links.get(block_id)), k.button(_g(props, "btn2"), "soft")) if b]
    kids = [k.head(_g(props, "title"), d["h2"], "#ffffff", align="center", w="fill") if props.get("title") else None,
            k.text(_g(props, "text"), d["lead"] if not k.phone else d["body"], 400, "#ffffff", align="center", w="fill", max_w=700) if props.get("text") else None,
            k.frame(btns, dir="h" if not k.phone else "v", gap=12, w="hug" if not k.phone else "fill", justify="center") if btns else None,
            k.text(_g(props, "note"), d["small"], 400, "#ffffff", align="center", w="fill") if props.get("note") else None]
    box = k.frame(kids, gap=16, pad=[48 if not k.phone else 32, 32, 48 if not k.phone else 32, 32], fill=gradient_var(), radius=k.radius * 1.5, align="center", w="fill", max_w=d["maxw"])
    return k.section([box], id=block_id, name="دعوت به اقدام", py=d["py"] * 0.7, align_center=True)


def cards_family(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    head = k.title_block(props)
    cards = []
    for it in _items(props)[:9]:
        kids = [k.image(0.62, _g(it, "image"), alt=_g(it, "title") or _g(it, "name"))]
        kids.append(k.head(_g(it, "title") or _g(it, "name"), d["h3"] * 0.8, w="fill"))
        if it.get("role") or it.get("price"):
            kids.append(k.text(_g(it, "role") or _g(it, "price"), d["small"], 600, "var:primary", w="fill"))
        if it.get("text"):
            kids.append(k.text(_g(it, "text"), d["body"], 400, "var:muted", w="fill"))
        cards.append(k.card(kids, gap=10))
    body = k.grid(cards, cols=d["cols"]) if cards else None
    return k.section([x for x in (head, body) if x], id=block_id, name="کارت‌ها")


def gallery(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    head = k.title_block(props)
    items = _items(props)[:8] or [{} for _ in range(6)]
    cells = [k.image(0.8, _g(it, "image"), alt=_g(it, "alt") or _g(it, "caption")) for it in items]
    return k.section([x for x in (head, k.grid(cells, cols=d["cols"] + (1 if not k.phone else 0), gap=12)) if x], id=block_id, name="گالری")


def footer(k: Kit, props: dict, block_id: str, key: str) -> dict:
    d = k.d
    cols = []
    about = _g(props, "about") or _g(props, "col2_text") or _g(props, "col3_text")
    brand = k.frame([k.text(k.brand or "نام برند", d["h3"], 800, "var:text", font=k.fh, w="fill"), k.text(about, d["small"], 400, "var:muted", w="fill", lh=1.7)] if about or k.brand else [], gap=10, w="fill")
    cols.append(brand)
    for ti, li in (("menu_title", None), ("col2_title", "col2_links"), ("col3_title", None)):
        title = _g(props, ti)
        if not title:
            continue
        links = _lines(_g(props, li)) if li else k.menu
        kids = [k.head(title, d["body"], w="fill")] + [k.text(x.split("|")[0].strip(), d["small"], 400, "var:muted", w="fill") for x in links[:6]]
        if ti == "col3_title" and _g(props, "col3_text"):
            kids.append(k.text(_g(props, "col3_text"), d["small"], 400, "var:muted", w="fill"))
        cols.append(k.frame(kids, gap=8, w="fill"))
    if key == "footer_big_cta":
        cols.insert(0, k.frame([k.head(_g(props, "cta_title"), d["h3"], w="fill"), k.text(_g(props, "cta_text"), d["small"], 400, "var:muted", w="fill"), k.button(_g(props, "cta_btn"), "filled")], gap=10, w="fill"))
    grid = k.grid([c for c in cols if c.get("children")], cols=min(len(cols), 4) if not k.phone else 1, gap=32)
    copy = k.text(_g(props, "copy") or _g(props, "text") or "", d["small"], 400, "var:muted", w="fill", align="center")
    body = [grid] if cols else []
    body += [{"t": "rect", "w": "fill", "h": 1, "fill": "var:line"}, copy]
    return k.section(body, bg="var:surface", py=d["py"] * 0.55, id=block_id, name="پابرگ", gap=24)


def contact_form(k: Kit, props: dict, block_id: str) -> dict:
    d = k.d
    head = k.title_block(props)
    fields = []
    for f in _items(props, "fields")[:6]:
        h = 120 if f.get("type") == "textarea" else 50
        fields.append(k.frame([k.text(_g(f, "label"), d["small"], 600, "var:text", w="fill"), k.frame([], h=h, w="fill", fill="var:surface", radius=k.radius * 0.7, stroke={"color": "var:line", "w": 1.5})], gap=6, w="fill"))
    form = k.card(fields + [k.button(_g(props, "button") or "فرستادن", "filled")], gap=16, max_w=620)
    return k.section([x for x in (head, form) if x], id=block_id, name="فرم تماس", align_center=True)


def map_block(k: Kit, props: dict, block_id: str) -> dict:
    d = k.d
    head = k.title_block(props)
    box = k.frame([k.text("📍 " + _g(props, "address"), d["body"], 600, "var:text", align="center", w="fill")], dir="z", h=float(props.get("map_height") or 320) * (0.6 if k.phone else 1), w="fill", fill="var:primary@10",
                  radius=k.radius, stroke={"color": "var:line", "w": 1.5}, align="center", valign="center", name="نقشه")
    return k.section([x for x in (head, box) if x], id=block_id, name="نقشه")


def data_list(k: Kit, props: dict, block_id: str, detail: bool = False) -> dict:
    d = k.d
    model = _g(props, "model") or "داده‌های سایت"
    cards = [k.card([k.image(0.62, alt=model), k.head("نمونه ۱" if i == 0 else f"نمونه {i + 1}", d["h3"] * 0.8, w="fill"), k.text("متنِ نمونه از دادهٔ سایت", d["small"], 400, "var:muted", w="fill")], gap=8)
             for i in range(1 if detail else 3)]
    note = k.text(f"فهرستِ پویا: {model}", d["small"], 600, "var:primary", w="fill")
    return k.section([note, k.grid(cards, cols=1 if detail else d["cols"])], id=block_id, name="دادهٔ سایت")


# ───────────────────────────── پایه‌ها

def basic(k: Kit, block: dict, block_id: str) -> dict | None:
    t, props = block["type"], block.get("props") or {}
    d = k.d
    if t == "heading":
        lvl = int(props.get("level") or 2)
        size = {1: d["h1"], 2: d["h2"], 3: d["h3"], 4: d["lead"]}.get(lvl, d["h2"])
        return k.section([k.head(_g(props, "text"), size, w="fill", align="auto")], py=16, id=block_id, name="تیتر")
    if t == "text":
        import re

        txt = re.sub(r"<[^>]+>", " ", _g(props, "html"))
        txt = re.sub(r"[ \t]+", " ", txt).strip()
        return k.section([k.text(txt, d["lead"] * 0.95, 400, "var:text", w="fill")], py=12, id=block_id, name="متن")
    if t == "image":
        return k.section([k.image(0.5, _g(props, "src"), alt=_g(props, "alt") or _g(props, "caption"))], py=16, id=block_id, name="تصویر")
    if t == "button":
        return k.section([k.button(_g(props, "text"), {"filled": "filled", "outline": "outline", "soft": "soft"}.get(_g(props, "variant"), "filled"), link=k.links.get(block_id))], py=12, id=block_id, name="دکمه", align_center=True)
    if t == "spacer":
        return {"t": "spacer", "h": float(props.get("height") or 40), "w": "fill", "id": block_id}
    if t == "divider":
        return k.section([{"t": "rect", "w": "fill", "h": float(props.get("thickness") or 1), "fill": "var:line"}], py=8, id=block_id, name="جداکننده")
    if t == "icon":
        return k.section([k.icon(float(props.get("icon_size") or 56))], py=12, id=block_id, name="نماد", align_center=True)
    if t == "gallery":
        return gallery(k, props, block_id, "gallery")
    if t == "video":
        return k.section([k.frame([k.text("▶", d["h1"], 700, "#ffffff", align="center", w="fill")], dir="z", h=320 if not k.phone else 200, w="fill", fill="var:text", radius=k.radius, align="center", valign="center", name="ویدیو")], id=block_id, name="ویدیو")
    if t == "custom_html":
        return k.section([k.text("کدِ سفارشی", d["body"], 600, "var:muted", w="fill", ph=True)], py=24, id=block_id, name="کدِ سفارشی")
    if t in ("section", "columns", "column"):
        kids = [b for b in (block_to_node(k, c) for c in block.get("children", [])) if b]
        if t == "columns":
            return k.section([k.frame(kids, dir="h" if not k.phone else "v", gap=24, w="fill", align="start")], id=block_id, name="ستون‌ها")
        return k.frame(kids, w="fill", id=block_id, name="بخش")
    return None


def c21_block(k: Kit, props: dict, block_id: str) -> dict:
    """قطعهٔ 21st.dev در طرحِ UI: کارتِ جای‌نگهدار با عنوان، دسته، متن‌های نمونه و مجوزِ قطعه. «ساختِ سایت از این طرح» همین بلوک را
    با ظاهرِ کاملش در سایت‌ساز می‌گذارد (HTMLِ پاک‌شده؛ مجوز و مبدأ همراهِ قطعه)."""
    d = k.d
    ref = _g(props, "ref")
    title, cat_label, lic, lib = "قطعهٔ آمادهٔ 21st.dev", "", "", ""
    texts = [str((t or {}).get("v", "")) for t in (props.get("texts") if isinstance(props.get("texts"), list) else []) if isinstance(t, dict)]
    try:
        from apps.projects.builder import c21_convert as CV, c21st

        rec = CV.get_record(ref)
        if rec:
            title = rec.get("title") or title
            lic, lib = str(rec.get("license") or ""), str(rec.get("library") or "")
            cats = rec.get("cats") or []
            cat_label = c21st.CATEGORIES.get(cats[0], ("",))[0] if cats else ""
            texts = [t for t in texts if t.strip()] or list(rec.get("texts") or [])
    except Exception:  # noqa: BLE001 - قطعه‌ای که از کاتالوگ رفته هم جای‌نگهدار می‌ماند
        pass
    kids = [k.pill("21st.dev" + (" · " + cat_label if cat_label else "")), k.head(title[:60], d["h3"], w="fill")]
    kids += [k.text(t[:140], d["small"], 400, "var:muted", w="fill") for t in texts[:4] if t.strip()]
    kids.append(k.text(" · ".join(x for x in (lic, lib) if x) or "مجوزِ آزاد", d["small"], 600, "var:muted", w="fill"))
    return k.section([k.card(kids, gap=10)], py=24, id=block_id, name=("21st.dev: " + title)[:40])


def block_to_node(k: Kit, block: dict) -> dict | None:
    """بلوکِ سایت‌ساز ⇒ گرهٔ چیدمان (شناسهٔ گره = شناسهٔ بلوک)."""
    t = str(block.get("type") or "")
    props = block.get("props") if isinstance(block.get("props"), dict) else {}
    bid = str(block.get("id") or "")
    key = t[2:] if t.startswith("c_") else t
    node = None
    fam = key.split("_")[0]
    if t in ("site_header",) or fam == "nav":
        node = nav(k, props, bid)
    elif t == "hero" or fam == "hero":
        node = hero(k, props, bid, key if t != "hero" else "hero")
    elif t == "features" or fam == "feat":
        node = features(k, props, bid, key)
    elif fam == "steps":
        node = steps(k, props, bid, key)
    elif t == "pricing" or fam == "price":
        node = pricing(k, props, bid, key)
    elif t == "testimonials" or fam == "testi":
        node = testimonials(k, props, bid, key)
    elif t == "faq" or fam == "faq":
        node = faq(k, props, bid, key)
    elif t == "cta" or fam == "cta":
        node = cta(k, props, bid, key)
    elif fam in ("card", "cards"):
        node = cards_family(k, props, bid, key)
    elif fam in ("gallery", "logos"):
        node = gallery(k, props, bid, key)
    elif fam == "footer":
        node = footer(k, props, bid, key)
    elif t == "menu_links" or t == "copyright":
        node = k.section([k.text(_g(props, "text") or "|".join(k.menu), k.d["small"], 400, "var:muted", w="fill", align="center")], py=12, id=bid)
    elif t == "c21":
        node = c21_block(k, props, bid)
    elif t == "contact_form":
        node = contact_form(k, props, bid)
    elif t == "map":
        node = map_block(k, props, bid)
    elif t == "data_list":
        node = data_list(k, props, bid)
    elif t == "data_detail":
        node = data_list(k, props, bid, detail=True)
    else:
        node = basic(k, {"type": t, "props": props, "children": block.get("children", [])}, bid)
    if node is None:
        node = k.section([k.text(f"بلوک «{t}»", k.d["body"], 600, "var:muted", w="fill", align="center")], py=24, id=bid)
    if bid and not node.get("id"):
        node["id"] = bid
    if bid:
        node.setdefault("name", t)
    return node
