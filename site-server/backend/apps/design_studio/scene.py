"""«صحنه»: قراردادِ مشترکِ هندسه بینِ چیدمان‌ها و همهٔ خروجی‌ها.

یک صفحه = {id، name، w، h، bleed، bg، elements[]، notes، links[]}؛ هر عنصر یک دیکشنری با ``type`` ∈ rect، ellipse، line، text، image.
واحدها: چاپ ⇒ میلی‌متر، اسلاید و UI ⇒ پیکسل. مختصات از گوشهٔ بالا-چپِ برش (trim)؛ خونریزی (bleed) به بیرون از ۰..w و ۰..h می‌رود.

عنصرِ متن پس از ``finalize_page`` یک کلیدِ ``lay`` (نتیجهٔ typeset.layout_text) دارد؛ همهٔ رندرها از همان می‌کشند.
"""
from __future__ import annotations

import copy
import re

from . import colors, fonts, typeset

TYPES = ("rect", "ellipse", "line", "text", "image")
ALIGNS = ("auto", "right", "left", "center", "justify")
MAX_ELEMENTS = 400
MAX_TEXT = 4000
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,48}$")
PT_MM = 25.4 / 72.0                  # ۱ پوینت = ۰٫۳۵۲۸ میلی‌متر

PAGE_SIZES = {"A3": (297.0, 420.0), "A4": (210.0, 297.0), "A5": (148.0, 210.0), "A6": (105.0, 148.0), "square": (200.0, 200.0)}
SLIDE_SIZE = (1920.0, 1080.0)
DEVICE_SIZES = {"desktop": (1440.0, 900.0), "tablet": (834.0, 1112.0), "phone": (390.0, 844.0)}


def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, x))


def _r(x, n=3):
    return round(float(x), n)


# ───────────────────────────── سازنده‌ها

def rect(id, x, y, w, h, fill=None, *, radius=0, stroke=None, opacity=1.0, shadow=None, **kw) -> dict:
    return {"id": id, "type": "rect", "x": x, "y": y, "w": w, "h": h, "fill": fill, "radius": radius, "stroke": stroke, "opacity": opacity,
            "shadow": shadow, **kw}


def ellipse(id, x, y, w, h, fill=None, *, stroke=None, opacity=1.0, **kw) -> dict:
    return {"id": id, "type": "ellipse", "x": x, "y": y, "w": w, "h": h, "fill": fill, "stroke": stroke, "opacity": opacity, **kw}


def line(id, x1, y1, x2, y2, color="#000000", width=0.3, *, dash=None, opacity=1.0, **kw) -> dict:
    return {"id": id, "type": "line", "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "stroke": {"color": color, "w": width}, "dash": dash,
            "opacity": opacity, **kw}


def text(id, x, y, w, h, value, *, font="vazirmatn", weight=400, size=4.0, color="#000000", align="auto", dir="auto", lh=1.5, max_lines=None,
         shrink=0.0, justify=False, valign="top", opacity=1.0, **kw) -> dict:
    return {"id": id, "type": "text", "x": x, "y": y, "w": w, "h": h, "text": value, "font": font, "weight": weight, "size": size, "color": color,
            "align": align, "dir": dir, "lh": lh, "max_lines": max_lines, "shrink": shrink, "justify": justify, "valign": valign,
            "opacity": opacity, **kw}


def image(id, x, y, w, h, src, *, fit="cover", focus=(0.5, 0.5), radius=0, opacity=1.0, stroke=None, shadow=None, **kw) -> dict:
    return {"id": id, "type": "image", "x": x, "y": y, "w": w, "h": h, "src": src, "fit": fit, "focus": list(focus), "radius": radius,
            "opacity": opacity, "stroke": stroke, "shadow": shadow, **kw}


def gradient(angle: float, *stops, kind: str = "linear") -> dict:
    """angle: ۰ = چپ⇒راست، ۹۰ = بالا⇒پایین. stops: (موقعیت ۰..۱، رنگ[، آلفا])."""
    return {"type": kind, "angle": angle, "stops": [list(s) for s in stops]}


# ───────────────────────────── وارسی

def _clean_color(v, default=None):
    if v is None or v == "":
        return default
    if isinstance(v, dict):
        return clean_gradient(v, default)
    return colors.norm(v, default) if isinstance(v, str) and (colors.is_hex(v) or re.fullmatch(r"#[0-9a-fA-F]{3}", v)) else default


def clean_gradient(g: dict, default=None):
    stops = []
    for s in (g.get("stops") or [])[:8]:
        if isinstance(s, (list, tuple)) and len(s) >= 2 and isinstance(s[1], str):
            stops.append([_r(_num(s[0], 0, 1, 0), 4), colors.norm(s[1]), _r(_num(s[2] if len(s) > 2 else 1, 0, 1, 1), 3)])
    if len(stops) < 2:
        return default
    return {"type": "radial" if g.get("type") == "radial" else "linear", "angle": _r(_num(g.get("angle"), -720, 720, 90)), "stops": stops}


def _clean_stroke(s):
    if not isinstance(s, dict):
        return None
    w = _num(s.get("w"), 0, 200, 0)
    if w <= 0:
        return None
    return {"color": colors.norm(s.get("color"), "#000000"), "w": _r(w)}


def _clean_shadow(s):
    if not isinstance(s, dict):
        return None
    return {"dx": _r(_num(s.get("dx"), -200, 200, 0)), "dy": _r(_num(s.get("dy"), -200, 200, 2)), "blur": _r(_num(s.get("blur"), 0, 400, 6)),
            "color": colors.norm(s.get("color"), "#000000"), "opacity": _r(_num(s.get("opacity"), 0, 1, 0.2))}


def _clean_radius(v):
    if isinstance(v, (list, tuple)) and len(v) == 4:
        return [_r(_num(x, 0, 5000, 0)) for x in v]
    return _r(_num(v, 0, 5000, 0))


def clean_element(src: dict, *, allow_images: bool = True) -> dict | None:
    """عنصرِ کاربر/الگو ⇒ عنصرِ تمیز (کلیدِ ناشناخته دور ریخته می‌شود). ناممکن ⇒ None."""
    if not isinstance(src, dict) or src.get("type") not in TYPES:
        return None
    t = src["type"]
    eid = str(src.get("id") or "")
    if not ID_RE.match(eid):
        return None
    o = {"id": eid, "type": t, "x": _r(_num(src.get("x"), -20000, 20000, 0)), "y": _r(_num(src.get("y"), -20000, 20000, 0)),
         "w": _r(_num(src.get("w"), -20000, 20000, 10)), "h": _r(_num(src.get("h"), -20000, 20000, 10)),
         "opacity": _r(_num(src.get("opacity"), 0, 1, 1), 3)}
    if t in ("rect", "ellipse", "image"):
        o["w"], o["h"] = max(0.0, o["w"]), max(0.0, o["h"])
    rot = _num(src.get("rot"), -360, 360, 0)
    if rot:
        o["rot"] = _r(rot, 2)
    for k in ("name", "role", "node"):
        if isinstance(src.get(k), str) and src[k]:
            o[k] = src[k][:60]
    for k in ("hidden", "locked", "ph"):
        if src.get(k):
            o[k] = True
    lk = src.get("link")
    if isinstance(lk, dict):
        if isinstance(lk.get("page"), str) and ID_RE.match(lk["page"]):
            o["link"] = {"page": lk["page"]}
        elif isinstance(lk.get("url"), str) and re.match(r"^(https?://|mailto:|tel:)", lk["url"]):
            o["link"] = {"url": lk["url"][:300]}
    if t in ("rect", "ellipse"):
        o["fill"] = _clean_color(src.get("fill"))
        o["stroke"] = _clean_stroke(src.get("stroke"))
        o["shadow"] = _clean_shadow(src.get("shadow"))
        if t == "rect":
            o["radius"] = _clean_radius(src.get("radius"))
    elif t == "line":
        o["stroke"] = _clean_stroke(src.get("stroke")) or {"color": "#000000", "w": 0.3}
        d = src.get("dash")
        o["dash"] = [_r(_num(d[0], 0.1, 100, 2)), _r(_num(d[1], 0.1, 100, 2))] if isinstance(d, (list, tuple)) and len(d) == 2 else None
    elif t == "image":
        s = src.get("src")
        if not allow_images:
            s = ""
        o["src"] = s[:80] if isinstance(s, str) else ""
        o["fit"] = "contain" if src.get("fit") == "contain" else "cover"
        f = src.get("focus")
        o["focus"] = [_r(_num(f[0], 0, 1, 0.5), 3), _r(_num(f[1], 0, 1, 0.5), 3)] if isinstance(f, (list, tuple)) and len(f) >= 2 else [0.5, 0.5]
        o["radius"] = _clean_radius(src.get("radius"))
        o["stroke"] = _clean_stroke(src.get("stroke"))
        o["shadow"] = _clean_shadow(src.get("shadow"))
        if isinstance(src.get("alt"), str):
            o["alt"] = src["alt"][:200]
    elif t == "text":
        o["text"] = typeset.clean_text(src.get("text"), MAX_TEXT)
        o["font"] = fonts.clean(src.get("font"))
        wt = int(round(_num(src.get("weight"), 300, 800, 400) / 100.0) * 100)
        o["weight"] = max(300, min(800, wt))
        o["size"] = _r(_num(src.get("size"), 0.3, 2000, 4.0), 3)
        o["color"] = colors.norm(src.get("color"), "#000000")
        o["align"] = src.get("align") if src.get("align") in ALIGNS else "auto"
        o["dir"] = src.get("dir") if src.get("dir") in ("auto", "rtl", "ltr") else "auto"
        o["lh"] = _r(_num(src.get("lh"), 0.8, 3, 1.5), 3)
        ml = src.get("max_lines")
        o["max_lines"] = int(_num(ml, 1, 200, 0)) or None if ml not in (None, "", 0) else None
        o["shrink"] = _r(_num(src.get("shrink"), 0, 0.9, 0), 3)
        o["justify"] = bool(src.get("justify"))
        o["valign"] = src.get("valign") if src.get("valign") in ("top", "middle", "bottom") else "top"
        if src.get("underline"):
            o["underline"] = True
        if src.get("strike"):
            o["strike"] = True
        bg = _clean_color(src.get("bg"))
        if bg:
            o["bg"] = bg
            o["pad"] = _r(_num(src.get("pad"), 0, 200, 0))
            o["bg_radius"] = _clean_radius(src.get("bg_radius"))
    if t in ("rect", "ellipse", "image", "text") and src.get("pad_link"):
        o["pad_link"] = True
    return o


def clean_elements(items, *, limit: int = MAX_ELEMENTS, allow_images: bool = True) -> list[dict]:
    out, seen = [], set()
    for it in (items if isinstance(items, list) else [])[:limit]:
        e = clean_element(it, allow_images=allow_images)
        if e and e["id"] not in seen:
            seen.add(e["id"])
            out.append(e)
    return out


# ───────────────────────────── ویرایش‌های کاربر روی عنصرهای الگو

OVERRIDE_KEYS = {"x", "y", "w", "h", "rot", "text", "font", "weight", "size", "color", "align", "dir", "lh", "max_lines", "shrink", "justify", "valign",
                 "fill", "stroke", "radius", "opacity", "shadow", "src", "fit", "focus", "hidden", "locked", "link", "dash", "underline", "strike",
                 "bg", "pad", "bg_radius", "name"}


def apply_overrides(elements: list[dict], overrides: dict | None, extra: list | None) -> list[dict]:
    """بر عنصرهای الگو اعمال می‌کند: overrides[id] = {کلید: مقدار}؛ extra = عنصرهای افزودهٔ کاربر (بالای همه)."""
    ov = overrides if isinstance(overrides, dict) else {}
    out = []
    for el in elements:
        o = ov.get(el["id"])
        if isinstance(o, dict):
            el = {**el, **{k: v for k, v in o.items() if k in OVERRIDE_KEYS}}
            if "text" in o:
                el["ph"] = False
        out.append(el)
    out.extend(clean_elements(extra or [], limit=120))
    return out


# ───────────────────────────── نهاییِ صفحه

def finalize_page(page: dict, *, digits_mode: str = "keep") -> dict:
    """عنصرها را وارسی، متن‌ها را جاگیری و ``bbox``/``lay`` را پر می‌کند؛ عنصرِ مخفی حذف می‌شود."""
    els = []
    seen: set[str] = set()
    for src in page.get("elements") or []:
        if src.get("hidden"):
            continue
        e = clean_element(src) if not src.get("_trusted") else {k: v for k, v in src.items() if k != "_trusted"}
        if not e:
            continue
        if e["id"] in seen:
            n = 2
            while f"{e['id']}-{n}" in seen:
                n += 1
            e["id"] = f"{e['id']}-{n}"
        seen.add(e["id"])
        if e["type"] == "text":
            txt = typeset.digits(e.get("text", ""), digits_mode) if e.get("text") else ""
            e["text"] = txt
            e["lay"] = typeset.layout_text(txt, font=e["font"], weight=e["weight"], size=e["size"], w=max(0.5, e["w"]), h=e["h"] if e["h"] > 0 else None,
                                           align=e["align"], dir=e["dir"], lh=e["lh"], max_lines=e["max_lines"], shrink=e["shrink"],
                                           justify=e["justify"], valign=e["valign"])
        els.append(e)
    page = {**page, "elements": els[:MAX_ELEMENTS + 150]}
    page.setdefault("bleed", 0.0)
    page.setdefault("notes", "")
    page["fonts"] = sorted({e["font"] for e in els if e["type"] == "text"})
    return page


def bbox(e: dict) -> tuple[float, float, float, float]:
    x, y, w, h = e["x"], e["y"], e["w"], e["h"]
    if e["type"] == "line":
        return min(x, x + w), min(y, y + h), abs(w), abs(h)
    return x, y, w, h


def text_problem(e: dict) -> bool:
    """متنی که واقعاً بیش از جعبه‌اش بود (جا نشد یا حتی پس از کوچک‌شدن بریده شد). بریدنِ عمدیِ توضیحِ کارت (max_lines بدونِ shrink) مشکل نیست."""
    lay = e.get("lay")
    if e.get("type") != "text" or not lay:
        return False
    return bool(lay.get("overflow") or lay.get("clipped") or (lay.get("truncated") and float(e.get("shrink") or 0) > 0))


def public_page(page: dict) -> dict:
    """نسخهٔ سبکِ صحنه برای پنل: همهٔ عنصرها، ولی ``lay`` فقط خلاصه (برای کادرِ انتخاب و ویرایشگر)."""
    out = {k: v for k, v in page.items() if k != "elements"}
    els = []
    for e in page["elements"]:
        d = {k: v for k, v in e.items() if k != "lay"}
        if e["type"] == "text" and e.get("lay"):
            lay = e["lay"]
            d["lay"] = {"size": _r(lay["size"]), "n": lay["n"], "h": _r(lay["h"]), "overflow": lay["overflow"], "truncated": lay["truncated"],
                        "shrunk": lay["shrunk"], "bad": text_problem(e)}
        els.append(d)
    out["elements"] = els
    return out


def deepcopy(x):
    return copy.deepcopy(x)
