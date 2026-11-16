"""فریم‌های UI ⇒ صحنه: توکن‌های طراحی (سبکِ ui-ux-pro-max + رنگِ برند)، متغیرهای روشن/تیره، Auto Layout، راهنمای سبک و نقطه‌های کلیکِ نمونهٔ اولیه.

یک فریم = دستگاه (دسکتاپ ۱۴۴۰، تبلت ۸۳۴، گوشی ۳۹۰) + فهرستِ گره‌ها. گره = بلوکِ سایت‌ساز (``t: block`` با همان ``type``/``props``) یا گرهٔ Auto Layout
(frame، text، button، image، rect، input، spacer). رنگ‌ها ``var:<نقش>``‌اند؛ حالتِ روشن/تیره فقط پالتِ متغیرها را عوض می‌کند.
"""
from __future__ import annotations

from . import colors, fonts, layout, scene, typeset
from . import ui_blocks as ub

DEVICE_NAMES = {"desktop": "دسکتاپ", "tablet": "تبلت", "phone": "گوشی"}
SPACE = [4, 8, 12, 16, 24, 32, 48, 64, 96]
DEFAULTS = {"style": "", "mode": "light", "font_head": "vazirmatn", "font_body": "vazirmatn", "brand_color": "", "use_brand": True, "digits": "fa", "look": "",
            "colors": None, "radius": None, "menu": []}
SHADOWS = {"soft": {"dx": 0, "dy": 10, "blur": 30, "color": "#0f172a", "opacity": 0.08}, "none": None, "hard": {"dx": 5, "dy": 5, "blur": 0, "color": "#111827", "opacity": 1.0},
           "glow": {"dx": 0, "dy": 12, "blur": 36, "color": "#5b4bdb", "opacity": 0.18}}
STYLE_SHADOW = {"neo-brutalism": "hard", "glassmorphism": "glow", "neumorphism": "soft", "claymorphism": "soft", "bento-grid": "none", "minimalism": "none"}


def style_table() -> dict:
    """۱۴ سبکِ سایت‌ساز (از apps.projects.builder.styles)؛ اگر در دسترس نبود فقط سبکِ «ساده»."""
    try:
        from apps.projects.builder import styles as st

        return {k: {"label": v["label"], "en": v.get("en", ""), "mood": v.get("mood", ""), "desc": v.get("desc", ""), "theme": v["theme"], "uiux": v.get("uiux", {})}
                for k, v in st.STYLES.items()}
    except Exception:  # noqa: BLE001
        return {"minimalism": {"label": "ساده", "en": "Minimalism", "mood": "", "desc": "", "uiux": {}, "theme": {
            "colors": {"primary": "#126f85", "on_primary": "#ffffff", "text": "#1b2b45", "text2": "#3d4b63", "muted": "#5a6b85", "line": "#dbe3ee", "bg": "#ffffff", "surface": "#f7faff"},
            "radius": 12, "button": "soft", "font_head": "vazirmatn", "font_body": "vazirmatn", "width": 1140}}}


def tokens_for(settings: dict, brand_primary: str = "") -> dict:
    """تنظیمات ⇒ {light، dark، radius، shadow، button، space، type}."""
    s = {**DEFAULTS, **(settings or {})}
    table = style_table()
    key = s.get("style") if s.get("style") in table else next(iter(table))
    th = table[key]["theme"]
    c = dict(th["colors"])
    brand = s.get("brand_color") if colors.is_hex(s.get("brand_color")) else (brand_primary if s.get("use_brand", True) and colors.is_hex(brand_primary) else "")
    primary = colors.norm(brand or c.get("primary"), "#126f85")
    on_primary = colors.on_color(primary) if brand else c.get("on_primary") or colors.on_color(primary)
    bg = colors.norm(c.get("bg"), "#ffffff")
    surface = colors.norm(c.get("surface"), "#f7faff")
    if colors.luminance(bg) < 0.2 and not s.get("mode") == "dark":
        pass
    text = colors.ensure_contrast(colors.norm(c.get("text"), "#1b2b45"), bg)
    light = {"bg": bg, "surface": surface if surface != bg else "#ffffff", "text": text, "muted": colors.ensure_contrast(colors.norm(c.get("muted"), "#5a6b85"), bg),
             "primary": primary, "on_primary": on_primary, "secondary": colors.darken(primary, 0.35), "accent": colors.lighten(primary, 0.82),
             "line": colors.norm(c.get("line"), colors.mix(bg, text, 0.12)), "danger": "#dc2626", "dark": colors.darken(primary, 0.6), "light": colors.lighten(primary, 0.92)}
    if s.get("colors") and isinstance(s["colors"], dict):                           # بازنویسیِ متغیرهای حالتِ روشن توسطِ کاربر
        for k, v in (s["colors"].get("light") or {}).items():
            if k in light and colors.is_hex(v):
                light[k] = colors.norm(v)
    dark_bg = colors.darken(primary, 0.82) if colors.luminance(primary) > 0.05 else "#0b1220"
    dark_bg = colors.mix("#0b1220", primary, 0.10)
    d_primary = colors.lighten(primary, 0.18) if colors.contrast(primary, dark_bg) < 3.5 else primary
    for _ in range(14):                                                   # متنِ روی دکمهٔ اصلی در حالتِ تیره هم تباینِ ≥ ۴٫۵ داشته باشد
        if colors.contrast(colors.on_color(d_primary), d_primary) >= 4.5:
            break
        d_primary = colors.lighten(d_primary, 0.04)
    dark = {"bg": dark_bg, "surface": colors.lighten(dark_bg, 0.07), "text": "#f1f5f9", "muted": "#a9b6c9", "primary": d_primary, "on_primary": colors.on_color(d_primary),
            "secondary": colors.darken(d_primary, 0.3), "accent": colors.mix(dark_bg, d_primary, 0.35), "line": colors.lighten(dark_bg, 0.16), "danger": "#f87171",
            "dark": "#050a14", "light": colors.lighten(dark_bg, 0.12)}
    if s.get("colors") and isinstance(s["colors"], dict):
        for k, v in (s["colors"].get("dark") or {}).items():
            if k in dark and colors.is_hex(v):
                dark[k] = colors.norm(v)
    radius = float(s["radius"]) if s.get("radius") not in (None, "") else float(th.get("radius", 14))
    return {"style": key, "style_label": table[key]["label"], "light": light, "dark": dark, "radius": radius, "button": th.get("button", "soft"),
            "shadow": SHADOWS.get(STYLE_SHADOW.get(key, "soft")), "space": SPACE, "uiux": table[key].get("uiux", {}),
            "type": {"h1": 60, "h2": 40, "h3": 26, "lead": 22, "body": 17, "small": 14}}


def make_var(pal: dict):
    def var(c):
        if not isinstance(c, str):
            return c
        if c.startswith("var:"):
            name, _, pct = c[4:].partition("@")
            base = pal.get(name, "#000000")
            if pct:
                try:
                    return colors.mix(pal["bg"], base, max(0, min(100, int(pct))) / 100)
                except ValueError:
                    return base
            return base
        if c.startswith("#") and "@" in c:
            hx, _, pct = c.partition("@")
            try:
                return colors.mix(pal["primary"], colors.norm(hx), int(pct) / 100)
            except ValueError:
                return colors.norm(hx)
        return c
    return var


def resolve_gradient(g, var):
    return {**g, "stops": [[s[0], var(s[1])] + list(s[2:]) for s in g["stops"]]} if isinstance(g, dict) else var(g)


# ───────────────────────────── گره‌ها

def _link(node: dict) -> dict | None:
    lk = node.get("link")
    if isinstance(lk, dict):
        if lk.get("frame"):
            return {"page": str(lk["frame"])}
        if lk.get("url"):
            return {"url": lk["url"]}
    return None


def to_layout(k: ub.Kit, node: dict, depth: int = 0) -> dict | None:
    """گرهٔ سند ⇒ گرهٔ چیدمان."""
    if not isinstance(node, dict) or node.get("hidden") or depth > 12:
        return None
    t = node.get("t")
    lk = _link(node)
    if t == "block":
        n = ub.block_to_node(k, node)
        if n is not None and lk:
            n["link"] = lk
        return n
    if t == "button":
        n = k.button(str(node.get("text") or "دکمه"), node.get("variant", "filled"), link=lk)
        if n and node.get("id"):
            n["id"] = node["id"]
        return n
    if t == "input":
        n = k.frame([k.text(str(node.get("label") or ""), k.d["small"], 600, "var:text", w="fill"),
                     k.frame([k.text(str(node.get("placeholder") or ""), k.d["body"], 400, "var:muted", w="fill")], dir="h", pad=[14, 16, 14, 16], fill="var:surface", radius=k.radius * 0.7,
                             stroke={"color": "var:line", "w": 1.5}, w="fill", align="center")], gap=6, w=node.get("w", "fill"))
        if node.get("id"):
            n["id"] = node["id"]
        return n
    if t == "icon":
        return k.icon(float(node.get("size") or 48))
    if t == "frame":
        kids = [x for x in (to_layout(k, c, depth + 1) for c in node.get("children", [])) if x]
        n = {kk: v for kk, v in node.items() if kk not in ("children", "link")}
        n["children"] = kids
        if lk:
            n["link"] = lk
        return n
    if t == "text":
        n = {kk: v for kk, v in node.items() if kk != "link"}
        n.setdefault("size", k.d["body"])
        n.setdefault("color", "var:text")
        n.setdefault("font", k.fb)
        n.setdefault("lh", 1.6)
        n.setdefault("w", "fill")
        if lk:
            n["link"] = lk
        return n
    if t == "image":
        n = {kk: v for kk, v in node.items() if kk != "link"}
        n.setdefault("ratio", 0.6)
        n.setdefault("radius", k.radius)
        if lk:
            n["link"] = lk
        return n
    if t in ("rect", "spacer"):
        n = dict(node)
        n.pop("link", None)
        if lk:
            n["link"] = lk
        return n
    return None


def frame_page(frame: dict, tokens: dict, settings: dict, info, *, mode: str | None = None) -> dict:
    """فریمِ سند ⇒ صفحهٔ صحنه (px) با ``meta``: گره‌ها (جعبه‌ها) و نقطه‌های کلیک."""
    s = {**DEFAULTS, **(settings or {})}
    device = frame.get("device") if frame.get("device") in ub.DEVICES else "desktop"
    mode = mode or frame.get("mode")
    if mode not in ("light", "dark"):
        mode = s.get("mode") if s.get("mode") in ("light", "dark") else "light"
    pal = tokens[mode if mode in ("light", "dark") else "light"]
    var = make_var(pal)
    fh, fb = fonts.clean(s.get("font_head")), fonts.clean(s.get("font_body"))
    menu = s.get("menu") or []
    kit = ub.Kit(device, tokens, font_head=fh, font_body=fb, brand_name=getattr(info, "name", "") or "", has_logo=bool(getattr(info, "has_logo", False)), menu=list(menu))
    W = float(frame.get("w") or kit.d["w"])
    kids = [x for x in (to_layout(kit, c) for c in frame.get("children", [])) if x]
    root = {"t": "frame", "dir": "v", "w": "fill", "children": kids, "id": "__root__", "align": "stretch"}
    ctx = layout.Ctx(prefix=f"{frame['id']}-", defaults={"font": fb, "weight": 400, "color": var("var:text"), "size": kit.d["body"], "lh": 1.6}, rtl=True, digits=s.get("digits", "fa"),
                     var=var)
    min_h = float(frame.get("min_h") or {"desktop": 900.0, "tablet": 1112.0, "phone": 844.0}[device])
    els, (w, h) = layout.solve(root, W, height=min_h, ctx=ctx)
    top_ids = [c.get("id") for c in kids if c.get("id")]
    nodes = []
    for nid, (x, y, bw, bh) in ctx.boxes.items():
        if nid == "__root__":
            continue
        nodes.append({"id": nid, "x": round(x, 1), "y": round(y, 1), "w": round(bw, 1), "h": round(bh, 1), "top": nid in top_ids})
    page = {"id": frame["id"], "name": frame.get("name") or DEVICE_NAMES.get(device, device), "type": "frame", "w": w, "h": max(h, min_h), "bleed": 0.0, "bg": pal["bg"],
            "elements": els, "notes": "", "unit": "px", "device": device, "mode": mode}
    page = scene.finalize_page(page, digits_mode=s.get("digits", "fa"))
    page["meta"] = {"nodes": nodes, "hotspots": hotspots(page)}
    return page


def hotspots(page: dict) -> list[dict]:
    out = []
    for e in page["elements"]:
        lk = e.get("link")
        if lk and lk.get("page"):
            x, y, w, h = scene.bbox(e)
            out.append({"el": e["id"], "x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1), "to": lk["page"]})
    return out


# ───────────────────────────── راهنمای سبک

def styleguide_page(tokens: dict, settings: dict, info) -> dict:
    """صفحهٔ «راهنمای سبک»: رنگ‌ها (روشن و تیره با تباین)، مقیاسِ تایپ، فاصله‌ها، گردی، دکمه و فیلد؛ همه از توکن‌ها."""
    s = {**DEFAULTS, **(settings or {})}
    fh, fb = fonts.clean(s.get("font_head")), fonts.clean(s.get("font_body"))
    kit = ub.Kit("desktop", tokens, font_head=fh, font_body=fb, brand_name=getattr(info, "name", "") or "", has_logo=False)
    L, D = tokens["light"], tokens["dark"]

    def swatch(name_fa, key, pal):
        v = pal[key]
        other = pal["bg"] if key not in ("bg",) else pal["text"]
        if key in ("primary", "secondary", "accent", "danger", "muted", "text", "surface", "line", "bg", "on_primary", "dark", "light"):
            against = pal["primary"] if key == "on_primary" else other
        ratio = colors.contrast(v, against)
        return kit.frame([{"t": "rect", "w": "fill", "h": 74, "fill": v, "radius": 12, "stroke": {"color": pal["line"], "w": 1}},
                          kit.text(name_fa, 15, 700, pal["text"], w="fill", lh=1.3), kit.text(f"{v.upper()}", 13, 500, pal["muted"], w="fill", lh=1.2, dir="ltr", align="left"),
                          kit.text(f"تباین {typeset.digits('%.1f' % ratio, 'fa')}", 12, 500, pal["muted"], w="fill", lh=1.2)], gap=4, w="fill")

    ROLE_FA = [("bg", "زمینه"), ("surface", "سطح"), ("text", "متن"), ("muted", "متنِ کم‌رنگ"), ("primary", "اصلی"), ("on_primary", "روی اصلی"), ("secondary", "ثانویه"),
               ("accent", "تأکیدِ ملایم"), ("line", "خط"), ("danger", "خطا")]

    def palette_block(title, pal):
        cells = [swatch(fa, k, pal) for k, fa in ROLE_FA]
        return kit.frame([kit.text(title, 22, 800, pal["text"], font=fh, w="fill"), kit.frame(cells, dir="grid", cols=5, gap=14, w="fill")], gap=14, w="fill", pad=24, fill=pal["bg"],
                         radius=18, stroke={"color": pal["line"], "w": 1.5})

    type_rows = []
    for nm, fa, size, wt in (("h1", "تیتر ۱", tokens["type"]["h1"], 800), ("h2", "تیتر ۲", tokens["type"]["h2"], 800), ("h3", "تیتر ۳", tokens["type"]["h3"], 700),
                             ("lead", "متنِ درشت", tokens["type"]["lead"], 400), ("body", "متنِ اصلی", tokens["type"]["body"], 400), ("small", "متنِ ریز", tokens["type"]["small"], 400)):
        type_rows.append(kit.frame([kit.text(f"{fa} · {typeset.digits(str(size), 'fa')} پیکسل", 13, 600, L["muted"], w=220),
                                    kit.text("نمونهٔ متنِ فارسی ۱۲۳۴۵", size, wt, L["text"], font=fh if nm.startswith("h") else fb, w="fill", lh=1.35)], dir="h", gap=20, w="fill", align="center"))
    space_row = kit.frame([kit.frame([{"t": "rect", "w": float(v), "h": 28, "fill": L["primary"], "radius": 4}, kit.text(typeset.digits(str(v), "fa"), 12, 600, L["muted"], w="hug")], gap=6, w="hug", align="center")
                           for v in tokens["space"]], dir="h", gap=24, w="fill", align="end")
    radius_row = kit.frame([kit.frame([{"t": "rect", "w": 90, "h": 60, "fill": L["accent"], "radius": r, "stroke": {"color": L["primary"], "w": 1.5}}, kit.text(typeset.digits(str(int(r)), "fa") + " پیکسل", 12, 600, L["muted"], w=90, align="center")],
                                      gap=6, w="hug", align="center") for r in (0, tokens["radius"] / 2, tokens["radius"], tokens["radius"] * 1.6, 999)], dir="h", gap=24, w="fill")
    btn_row = kit.frame([kit.button("دکمهٔ اصلی", "filled"), kit.button("دکمهٔ حاشیه‌دار", "outline"), kit.button("دکمهٔ ملایم", "soft"),
                         kit.frame([kit.text("نام", 13, 600, "var:text", w="fill"), kit.frame([kit.text("مثلاً علی", 16, 400, "var:muted", w="fill")], dir="h", pad=[12, 14, 12, 14], fill="var:surface",
                                                                                                radius=kit.radius * 0.7, stroke={"color": "var:line", "w": 1.5}, w="fill")], gap=6, w=260)], dir="h", gap=16, w="fill", align="end")

    def section(title, body):
        return kit.frame([kit.text(title, 22, 800, L["text"], font=fh, w="fill"), body], gap=14, w="fill")

    page_nodes = [kit.frame([kit.frame([kit.text("راهنمای سبک", 44, 800, L["text"], font=fh, w="fill", lh=1.2),
                                        kit.text(f"سبک: {tokens['style_label']} · فونتِ تیتر: {fonts.FONT_INFO.get(fh, {}).get('title', fh)} · فونتِ متن: {fonts.FONT_INFO.get(fb, {}).get('title', fb)} · گردیِ پایه: {typeset.digits(str(int(tokens['radius'])), 'fa')} پیکسل",
                                                 16, 400, L["muted"], w="fill")], gap=8, w="fill"),
                              palette_block("متغیرهای حالتِ روشن", L), palette_block("متغیرهای حالتِ تیره", D),
                              section("مقیاسِ تایپ", kit.frame(type_rows, gap=14, w="fill")), section("فاصله‌ها (۴ پیکسلی)", space_row), section("گردیِ گوشه‌ها", radius_row),
                              section("دکمه و فیلد", btn_row)], gap=36, pad=[64, 64, 64, 64], w="fill")]
    ctx = layout.Ctx(prefix="sg-", defaults={"font": fb, "weight": 400, "color": L["text"], "size": 16, "lh": 1.6}, rtl=True, digits=s.get("digits", "fa"), var=make_var(L))
    root = {"t": "frame", "dir": "v", "w": "fill", "children": page_nodes, "fill": L["bg"]}
    els, (w, h) = layout.solve(root, 1440.0, ctx=ctx)
    page = {"id": "styleguide", "name": "راهنمای سبک", "type": "styleguide", "w": w, "h": h, "bleed": 0.0, "bg": L["bg"], "elements": els, "notes": "", "unit": "px", "device": "desktop", "mode": "light"}
    page = scene.finalize_page(page, digits_mode=s.get("digits", "fa"))
    page["meta"] = {"nodes": [], "hotspots": []}
    return page


def brand_primary_of(info) -> str:
    """رنگِ اصلیِ برندِ فروشگاه (از کیتِ برند)؛ خالی اگر معلوم نیست."""
    try:
        return (getattr(info, "kit_for", None) and info.kit_for({}) or {}).get("palette", {}).get("primary", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def build_scene(data: dict, info, *, mode_override: str | None = None, with_styleguide: bool = False) -> dict:
    s = {**DEFAULTS, **(data.get("settings") or {})}
    tokens = tokens_for(s, brand_primary_of(info))
    pages = []
    for f in (data.get("frames") or [])[:30]:
        if isinstance(f, dict) and f.get("id"):
            pages.append(frame_page(f, tokens, s, info, mode=mode_override))
    sc = {"kind": "ui", "unit": "px", "pages": pages, "settings": s, "tokens": tokens, "rtl": True}
    if with_styleguide:
        sc["styleguide"] = styleguide_page(tokens, s, info)
    return sc
