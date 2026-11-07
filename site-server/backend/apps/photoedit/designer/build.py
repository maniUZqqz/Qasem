"""مجری: برنامهٔ طراحی (plan) ⇒ «حالتِ ادیتور» (تنظیم‌ها + لایه‌ها) — همان JSON ِ پروژهٔ ادیتورِ دستی.

هیچ‌چیزِ پخته‌شده‌ای نمی‌سازد: نتیجه لایه است (پس‌زمینه، محصولِ جداشده، سایه، شکل، متن، لوگو) و تنظیماتِ ظهور؛ در حالتِ دستی
همه قابل‌ویرایش اند. فقط محصولِ جداشده یک «عکسِ کتابخانه» (PNG شفاف) است که لایه به آن اشاره می‌کند.

مختصات: همه نسبت به بومِ نهایی (خروجیِ مرحلهٔ قاب)؛ طول‌ها کسری از پهنای بوم؛ ``cx, cy`` کسری از پهنا/ارتفاع.
لایه‌ها پس از ساخته‌شدن با ``_z`` مرتب می‌شوند تا هیچ برنامه‌ای (حتی از هوش مصنوعی) ترتیبِ لایه‌ها را به‌هم نریزد.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from PIL import Image

from .. import brand as brand_mod, catalog, develop_np, fontreg, matting, services
from ..models import PhotoAsset
from . import analyze, colorx, grid, matte, render, toolspec, typo

logger = logging.getLogger(__name__)

# ترتیبِ عمودیِ لایه‌ها (کوچک = پایین‌تر)
Z = {"base": 0, "backdrop": 10, "backdrop_fx": 12, "shadow": 20, "product": 30, "adjust": 40, "scrim": 50, "shape": 60,
     "image": 65, "badge": 70, "badge_text": 71, "text": 80, "logo": 90}


@dataclass
class Ctx:
    asset: PhotoAsset
    store: object
    user: object
    plan: dict
    fmt: str
    W: int
    H: int
    frame: Image.Image
    an: dict
    pal: dict
    rgb_small: object
    logo_aspect: float | None
    kit: dict | None = None                          # سبکِ برندِ مؤثر (brand.effective) یا None
    logo_src: dict = field(default_factory=lambda: {"kind": "logo"})
    layers: list = field(default_factory=list)       # [(z, order, layer)]
    meta: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    report: dict = field(default_factory=dict)       # step id ⇒ {ok, note, resolved}
    product: dict | None = None
    cut: dict | None = None
    has_backdrop: bool = False
    needs: dict = field(default_factory=lambda: {"ai": [], "node": [], "manual": []})
    tag: str = ""
    seq: int = 0
    texts: dict = field(default_factory=dict)        # step id ⇒ layer id (برای «زیرِ فلان متن»)


# ───────────────────────────── ابزارها

def _base_layer() -> dict:
    return {"id": "base", "type": "base", "name": "عکس", "visible": True, "locked": False, "opacity": 1, "blend": "normal",
            "mask": None}


def _common(lid: str, name: str, typ: str, opacity: float = 1.0) -> dict:
    return {"id": lid, "type": typ, "name": name[:60], "visible": True, "locked": False, "opacity": round(opacity, 4),
            "blend": "normal", "mask": None, "parent": None, "clip": False}


def _add(c: Ctx, z: int, layer: dict, **meta) -> dict:
    c.seq += 1
    c.layers.append((z, c.seq, layer))
    c.meta[layer["id"]] = dict(meta, z=z)
    return layer


def rc(c: Ctx, token: str, fallback: str = "#ffffff") -> str:
    """نشانهٔ رنگ ⇐ hex از پالت."""
    if colorx.is_hex(token):
        return token.lower()
    p = c.pal
    return {"auto": p["text"], "text": p["text"], "text_dim": p["text_dim"], "accent": p["accent"], "accent_text": p["accent_text"],
            "plate": p["plate"], "bg_a": p["bg_a"], "bg_b": p["bg_b"], "white": "#ffffff", "black": "#000000"}.get(token, fallback)


def _skip(c: Ctx, st: dict, why: str, need: str | None = None) -> None:
    c.report[st["id"]] = {"ok": False, "note": why}
    if need:
        c.needs[need].append(st["id"])


def _done(c: Ctx, st: dict, note: str = "", **resolved) -> None:
    c.report[st["id"]] = {"ok": True, "note": note, "resolved": resolved}


def _rect_layer(lid, name, cx, cy, w, h, *, fill=None, opacity=1.0, radius=0.0, shape="rect", stroke=None) -> dict:
    d = _common(lid, name, "shape", 1.0)
    d.update({"shape": shape, "cx": round(cx, 5), "cy": round(cy, 5), "w": round(w, 5), "h": round(h, 5), "rot": 0,
              "radius": radius, "stroke": stroke, "fx": None})
    if fill is not None:
        d["fill"] = fill
    else:
        d["fill"] = {"type": "solid", "color": "#000000", "opacity": round(opacity, 4)}
    return d


def _solid(color: str, opacity: float = 1.0) -> dict:
    return {"type": "solid", "color": color, "opacity": round(opacity, 4)}


# ───────────────────────────── cutout

def _frame_sig(plan: dict) -> str:
    import hashlib

    keep = [(s["tool"], s["params"]) for s in plan["steps"] if s["on"] and s["tool"] in ("rotate", "crop", "frame")]
    return hashlib.md5(json.dumps(keep, sort_keys=True).encode("utf-8")).hexdigest()[:8]


def _cut_sidecar(asset: PhotoAsset):
    return services.abs_path(asset.dir_rel) / "cut.json"


def make_cutout(c: Ctx) -> dict:
    """جداکردنِ محصول از بومِ قاب‌شده (یک بار) و ساختِ عکسِ کتابخانهٔ شفاف. ⇒ {ok, asset, bbox(کسری از بوم)، method، reason}."""
    sig = _frame_sig(c.plan)
    ref = f"dcut:{c.asset.pk}:{sig}"[:60]
    existing = PhotoAsset.objects.filter(store=c.store, source_ref=ref).first()
    if existing is not None:
        side = _cut_sidecar(existing)
        try:
            info = json.loads(side.read_text(encoding="utf-8"))
            return {"ok": True, "asset": existing.pk, "bbox": info["bbox"], "method": info.get("method", ""), "reason": "",
                    "size": [existing.width, existing.height]}
        except (OSError, ValueError, KeyError):
            pass
    m = matte.compute(c.frame, c.an["subject"]["box"])
    if not m["ok"]:
        return {"ok": False, "reason": m["reason"] or "محصول جدا نشد", "method": m["method"]}
    try:
        cut, (x0, y0, x1, y1) = matte.cutout_image(c.frame, m["mask"])
    except ValueError as exc:
        return {"ok": False, "reason": str(exc), "method": m["method"]}
    W, H = c.frame.size
    asset = services._asset_from_bytes(c.store, c.user, render.to_png_bytes(cut), title="محصولِ جداشده (طراحی)", source_ref=ref)
    bbox = [x0 / W, y0 / H, x1 / W, y1 / H]
    try:
        _cut_sidecar(asset).write_text(json.dumps({"bbox": bbox, "method": m["method"], "coverage": m["coverage"]}), encoding="utf-8")
    except OSError:
        logger.warning("designer: cut.json not written for %s", asset.pk)
    return {"ok": True, "asset": asset.pk, "bbox": bbox, "method": m["method"], "reason": "", "size": [asset.width, asset.height]}


def h_cutout(c: Ctx, st: dict) -> None:
    p = st["params"]
    if c.cut is None:
        c.cut = make_cutout(c)
    cut = c.cut
    if not cut["ok"]:
        _skip(c, st, f"محصول جدا نشد ({cut['reason']}) — طراحی روی عکسِ کامل ساخته شد. با سرورِ پردازش یا «حذف پس‌زمینه» در حالتِ دستی دقیق‌تر می‌شود.", "node")
        c.notes.append("جداسازیِ محصول انجام نشد؛ طراحی روی خودِ عکس ساخته شد.")
        return
    W, H = c.W, c.H
    bx0, by0, bx1, by1 = cut["bbox"]
    bw, bh = (bx1 - bx0) * W, (by1 - by0) * H
    sx0, sy0, sx1, sy1 = grid.safe_rect(c.fmt)
    if p["fit"] == "keep":
        k = 1.0
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    else:
        k = p["scale"] * min(W, H) / max(bw, bh)
        k = min(k, (sx1 - sx0) * W * 0.98 / max(1.0, bw), (sy1 - sy0) * H * 0.86 / max(1.0, bh))
        cx = p["anchor_x"]
        cy = p["anchor_y"]
        half_w = bw * k / W / 2
        cx = max(sx0 + half_w, min(sx1 - half_w, cx))
    w_frac = bw * k / W
    h_px = bh * k
    cy = max(sy0 + h_px / H / 2, min(sy1 - h_px / H / 2, cy)) if p["fit"] != "keep" else cy
    lid = "prod"
    layer = _common(lid, "محصول", "image")
    layer.update({"src": {"kind": "asset", "asset": cut["asset"]}, "cx": round(cx, 5), "cy": round(cy, 5), "w": round(w_frac, 5),
                  "rot": 0, "flip_h": False, "flip_v": False, "fx": None})
    _add(c, Z["product"], layer, step=st["id"], kind="product")
    c.product = {"id": lid, "cx": cx, "cy": cy, "w": w_frac, "h_px": h_px, "box": [cx - w_frac / 2, cy - h_px / H / 2, cx + w_frac / 2, cy + h_px / H / 2]}
    if cut["method"] == "cpu-model":
        c.notes.append(matting.NOTE_FA)
    _done(c, st, "محصول از زمینه جدا شد", method=cut["method"], box=[round(v, 3) for v in c.product["box"]])


def h_backdrop(c: Ctx, st: dict) -> None:
    p = st["params"]
    W, H = c.W, c.H
    c0, c1 = rc(c, p["c0"], c.pal["bg_a"]), rc(c, p["c1"], c.pal["bg_b"])
    if p["style"] == "solid":
        fill = _solid(c0)
    else:
        fill = {"type": "gradient", "c0": c0, "c1": c1 if p["style"] == "gradient" else colorx.mix(c0, c1, 0.5), "angle": p["angle"]}
    layer = _rect_layer("bg", "زمینهٔ تازه", 0.5, 0.5, 1.0, H / W, fill=fill)
    _add(c, Z["backdrop"], layer, step=st["id"], kind="backdrop")
    c.has_backdrop = True
    if p["style"] == "studio":
        cx, cy = (c.product["cx"], c.product["cy"]) if c.product else (0.5, 0.45)
        glow = _rect_layer("bgglow", "نورِ زمینه", 0.5, 0.5, 1.0, H / W, fill=_solid("#ffffff", 0.22))
        glow["mask"] = {"type": "radial", "c": [round(cx, 4), round(cy, 4)], "rx": 0.55, "ry": 0.5 * H / W, "feather": 1.0, "invert": False}
        _add(c, Z["backdrop_fx"], glow, step=st["id"], kind="backdrop_fx")
    if p["vignette"] > 0.02:
        vg = _rect_layer("bgvig", "تاریکیِ گوشه‌ها", 0.5, 0.5, 1.0, H / W, fill=_solid("#000000", min(0.7, p["vignette"] * 0.7)))
        vg["mask"] = {"type": "radial", "c": [0.5, 0.5], "rx": 0.62, "ry": 0.62 * H / W, "feather": 0.9, "invert": True}
        _add(c, Z["backdrop_fx"] + 1, vg, step=st["id"], kind="backdrop_fx")
    _done(c, st, f"زمینه {colorx.name_fa(c0)}", c0=c0, c1=c1)


def h_shadow(c: Ctx, st: dict) -> None:
    if not c.product:
        _skip(c, st, "سایه فقط برای محصولِ جداشده است")
        return
    p = st["params"]
    pr = c.product
    W, H = c.W, c.H
    if p["kind"] in ("contact", "both"):
        ell = _rect_layer("shc", "سایهٔ زیرِ محصول", 0.5, 0.5, 1.0, H / W, fill=_solid("#000000", round(0.5 * p["strength"] + 0.1, 3)))
        by = pr["box"][3] - 0.012
        ell["mask"] = {"type": "radial", "c": [round(pr["cx"], 4), round(by, 4)], "rx": round(pr["w"] * 0.5, 4),
                       "ry": round(max(0.012, pr["w"] * 0.1) * 1.0, 4), "feather": 1.0, "invert": False}
        _add(c, Z["shadow"], ell, step=st["id"], kind="shadow")
    if p["kind"] in ("drop", "both"):
        for l in (x[2] for x in c.layers):
            if l["id"] == pr["id"]:
                l["fx"] = {"shadow": {"color": "#000000", "opacity": round(0.28 * p["strength"] + 0.04, 3), "blur": 0.018, "dx": 0.0, "dy": 0.012},
                           "stroke": None, "glow": None}
    _done(c, st, "سایهٔ نرم زیرِ محصول")


def _adjust_layer(lid, name, adjust: dict, mask=None) -> dict:
    d = _common(lid, name, "adjust")
    d.pop("clip", None)
    d.update({"adjust": develop_np.normalize_adjust(adjust), "curve": {}, "mask": mask})
    return d


def h_local_adjust(c: Ctx, st: dict) -> None:
    p = st["params"]
    W, H = c.W, c.H
    if p["kind"] == "spotlight":
        box = c.product["box"] if c.product else c.an["subject"]["box"]
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        mask = {"type": "radial", "c": [round(cx, 4), round(cy, 4)], "rx": round(max(0.18, (box[2] - box[0]) * 0.75), 4),
                "ry": round(max(0.18, (box[3] - box[1]) * 0.75) * H / W, 4), "feather": 0.85, "invert": False}
        adj = {"exposure": round(0.55 * p["strength"], 3), "contrast": round(10 * p["strength"], 2)}
        name = "نورِ نقطه‌ای روی محصول"
    else:
        mask = {"type": "radial", "c": [0.5, 0.5], "rx": 0.62, "ry": round(0.62 * H / W, 4), "feather": 0.9, "invert": True}
        adj = {"exposure": round(-0.8 * p["strength"], 3)}
        name = "تیرگیِ نرمِ گوشه‌ها"
    _add(c, Z["adjust"] + 1, _adjust_layer("la" + st["id"][:8], name, adj, mask), step=st["id"], kind="adjust")
    _done(c, st, name)


def h_scrim(c: Ctx, st: dict) -> None:
    p = st["params"]
    W, H = c.W, c.H
    col = rc(c, p["color"], c.pal["plate"])
    lay = _rect_layer("scr" + st["id"][:8], "سایهٔ خوانایی", 0.5, 0.5, 1.0, H / W, fill=_solid(col, p["strength"]))
    e, s = p["edge"], p["size"]
    if e == "auto":
        e = _slot_rect(c, "auto")[0]                          # همان جایی که متنِ «خودکار» می‌نشیند
        e = e if e in ("top", "bottom", "left", "right") else "bottom"
    if e != "full":
        p0, p1 = {"bottom": ([0.5, 1.0], [0.5, 1.0 - s]), "top": ([0.5, 0.0], [0.5, s]),
                  "left": ([0.0, 0.5], [s, 0.5]), "right": ([1.0, 0.5], [1.0 - s, 0.5])}[e]
        lay["mask"] = {"type": "linear", "p0": p0, "p1": p1, "invert": False}
    _add(c, Z["scrim"], lay, step=st["id"], kind="scrim", edge=e)
    _done(c, st, "سایهٔ ملایم برای خوانایی", edge=e)


def _slot_rect(c: Ctx, name: str, prefer=None) -> tuple[str, tuple]:
    """نامِ جا ⇒ (نامِ نهایی، جعبه). auto ⇒ آرام‌ترین جای بدونِ سوژه."""
    if name != "auto":
        return name, grid.slot(name, c.fmt, c.W, c.H)
    cls = grid.class_of(c.fmt, c.W, c.H)
    cands = prefer or (("left", "right", "top", "bottom") if cls == "wide" else ("top", "bottom"))
    sc = c.an["slots"]
    best = max(cands, key=lambda k: (sc[k]["score"] + (0.02 if k == cands[0] else 0.0)))
    return best, grid.slot(best, c.fmt, c.W, c.H)


def h_shape(c: Ctx, st: dict) -> None:
    p = st["params"]
    W, H = c.W, c.H
    name, r = _slot_rect(c, p["slot"])
    sx, sy = (r[2] - r[0]) * p["w_frac"], (r[3] - r[1]) * p["h_frac"]
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    col = rc(c, p["color"], c.pal["accent"])
    col2 = rc(c, p["color2"], "") if p["color2"] else ""
    if p["shape"] == "line":
        lay = _rect_layer("sh" + st["id"][:8], "خط", cx, cy, sx, 0.0, shape="line", fill=None,
                          stroke={"color": col, "w": 0.006})
        lay["fill"] = None
    else:
        fill = {"type": "gradient", "c0": col, "c1": col2, "angle": 90} if col2 else _solid(col, p["opacity"])
        lay = _rect_layer("sh" + st["id"][:8], "شکل", cx, cy, sx, sy * H / W, fill=fill, radius=p["radius"], shape=p["shape"])
        if col2:
            lay["opacity"] = p["opacity"]
    _add(c, Z["shape"], lay, step=st["id"], kind="shape")
    _done(c, st, "شکل", slot=name)


def _text_layer(lid: str, text: str, size: float, *, font: str, weight: int, color: str, align: str, lh: float = 1.3) -> dict:
    d = _common(lid, "متن", "text")
    d.pop("clip", None)
    d.update({"text": text, "font": font, "weight": weight, "size": size, "color": color, "align": align, "dir": "auto",
              "line_height": lh, "letter_spacing": 0, "width": 0, "cx": 0.5, "cy": 0.5, "rot": 0, "stroke": None, "shadow": None,
              "box": None, "tile": None, "fx": None})
    return d


def _font_for(role: str, font: str, kit: dict | None = None) -> str:
    """فونتِ نقش. سبکِ برند: تیتر ⇐ فونتِ تیتر، متنِ دوم/توضیح/دکمه ⇐ فونتِ متن؛ بقیه (قیمت، برچسب) همان فونتِ الگو."""
    if kit:
        k = kit.get("heading_font") if role in ("display", "hero", "title") else kit.get("body_font") if role in ("sub", "caption", "cta") else ""
        if k and fontreg.known(k):
            return k
    if font and fontreg.known(font):
        return font
    return fontreg.DEFAULT


def _auto_text_color(c: Ctx, rect) -> str:
    """رنگِ «خودکار»: با زمینهٔ تازه ⇒ رنگِ متنِ پالت؛ روی خودِ عکس ⇒ بهترین از سفید/مشکی/پالت روی همان ناحیه."""
    if c.has_backdrop:
        return c.pal["text"]
    st = analyze.region_stats(c.rgb_small, rect)
    col, _r = colorx.best_text(st["pixels"], ("#ffffff", "#111111", c.pal["text"]))
    return col


def h_text(c: Ctx, st: dict) -> None:
    p = st["params"]
    W, H = c.W, c.H
    text = p["text"].strip()
    if not text:
        _skip(c, st, "متنی نوشته نشده")
        return
    role = p["role"]
    name, r = _slot_rect(c, p["slot"])
    x0, y0, x1, y1 = r
    below = c.texts.get(p.get("below") or "")
    if below:
        bl = c.meta[below]["bbox"]
        y0 = min(y1 - 0.03, bl[3] + 0.012)
        x0, x1 = c.meta[below]["slot_x"]
    size = typo.role_size(role, p["scale"])
    weight = p["weight"]
    font = _font_for(role, p["font"], c.kit)
    plate = p["plate"]
    color_tok = p["color"]
    auto_color = color_tok == "auto" and plate != "accent"
    if plate == "accent":
        color = c.pal["accent_text"] if color_tok == "auto" else rc(c, color_tok)
    else:
        color = _auto_text_color(c, r) if auto_color else rc(c, color_tok)
    lh = 1.2 if role in ("display", "hero") else 1.3
    layer = _text_layer("t" + st["id"][:10], text, size, font=font, weight=weight, color=color, align=p["align"], lh=lh)
    layer["name"] = {"display": "تیتر", "hero": "تیتر", "title": "تیتر", "price": "قیمت", "sub": "متنِ دوم", "cta": "دکمه"}.get(role, "متن")
    max_w, max_h = (x1 - x0) * W, (y1 - y0) * H
    pad = 0.0
    if plate in ("solid", "pill", "accent"):
        pad = 0.36
        layer["box"] = {"color": c.pal["accent"] if plate == "accent" else c.pal["plate"], "opacity": 1.0 if plate == "accent" else 0.88,
                        "pad": pad, "radius": 1.0 if plate in ("pill", "accent") else 0.22}
        # کادر از هر طرف pad×اندازه بیرون می‌زند؛ با اندازهٔ اولیه (بزرگ‌ترین) حساب می‌کنیم تا «متن + کادر» حتماً در جا بماند
        pad_px = pad * layer["size"] * W
        max_w = max(60.0, max_w - 2 * pad_px)
        max_h = max(20.0, max_h - 2 * pad_px)
    fit = typo.fit_text(layer, W, max_w, max_h, min_size=typo.MIN_KEY_LEGIBLE if role in ("title", "hero", "display", "price") else typo.MIN_LEGIBLE,
                        max_lines=p["max_lines"])
    if p["align"] != "center" or plate in ("solid", "pill", "accent"):
        typo.tighten_width(layer, W, cap_px=max_w)
    m = typo.measure(layer, W)
    bw, bh = m["block_w"], m["block_h"]
    outer_w = bw + 2 * pad * layer["size"] * W
    outer_h = bh + 2 * pad * layer["size"] * W
    # جای افقی: تراز + جعبه
    if p["align"] == "right":
        cxp = x1 * W - outer_w / 2
    elif p["align"] == "left":
        cxp = x0 * W + outer_w / 2
    else:
        cxp = (x0 + x1) / 2 * W
    v = p["v"] if not below else "start"
    # اگر متنِ دومی «زیرِ» این بیاید، جایش را از همین حالا کنار می‌گذاریم تا دو متن یک بلوکِ منظم شوند (نه روی هم)
    reserve = 0.0
    follow = next((s for s in c.plan["steps"] if s["on"] and s["tool"] == "text" and s["params"].get("below") == st["id"]
                   and s["params"]["text"].strip()), None)
    if follow is not None and not below:
        fp = follow["params"]
        fl = _text_layer("tmp", fp["text"], typo.role_size(fp["role"], fp["scale"]), font=_font_for(fp["role"], fp["font"], c.kit),
                         weight=fp["weight"], color="#000000", align=fp["align"])
        room = max(0.0, (y1 - y0) * H - outer_h - 0.012 * H)
        fr = typo.fit_text(fl, W, (x1 - x0) * W, room, min_size=typo.MIN_LEGIBLE, max_lines=fp["max_lines"])
        reserve = fr["block_h"] + 0.012 * H
    top_limit = y0 * H + outer_h / 2
    if v == "start":
        cyp = top_limit
    elif v == "end":
        cyp = max(top_limit, y1 * H - outer_h / 2 - reserve)
    else:
        cyp = max(top_limit, (y0 + y1) / 2 * H - reserve / 2)
    layer["cx"], layer["cy"] = round(cxp / W, 5), round(cyp / H, 5)
    if p["strike"]:
        layer["name"] += " (خط‌خورده)"
    if not c.has_backdrop and not plate:
        layer["shadow"] = {"color": "#000000" if colorx.luminance(colorx.hex_to_rgb(color)) > 0.5 else "#ffffff", "opacity": 0.35,
                           "blur": 0.14, "dx": 0.0, "dy": 0.05}
    bbox = [cxp / W - outer_w / 2 / W, cyp / H - outer_h / 2 / H, cxp / W + outer_w / 2 / W, cyp / H + outer_h / 2 / H]
    _add(c, Z["text"], layer, step=st["id"], kind="text", role=role, slot=name, rect=list(r), auto_color=auto_color, plate_pref=plate,
         bbox=bbox, slot_x=[x0, x1], strike=p["strike"], pad=pad, below_of=below or "", max_lines=p["max_lines"])
    c.texts[st["id"]] = layer["id"]
    if p["strike"]:
        text_w = max(m["widths"] + [1.0])                       # پهنای واقعیِ متن (نه جعبه)؛ خط فقط روی خودِ قیمت
        ln = _rect_layer("st" + st["id"][:8], "خطِ قیمتِ قبلی", (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, text_w / W * 1.06, 0.0,
                         shape="line", fill=None, stroke={"color": colorx.mix(color, "#e11d48", 0.5), "w": 0.004})
        ln["fill"] = None
        _add(c, Z["text"] + 1, ln, step=st["id"], kind="strike", for_layer=layer["id"])
    notes = []
    if fit["shrunk"]:
        notes.append("اندازهٔ متن کم شد تا جا شود")
    if fit["truncated"]:
        notes.append("متن بلند بود و کوتاه شد")
        c.notes.append(f"متنِ «{text[:20]}…» بلند بود و کوتاه شد.")
    _done(c, st, "؛ ".join(notes), slot=name, size=layer["size"], lines=fit["lines"], overflow=fit["overflow"])


def h_badge(c: Ctx, st: dict) -> None:
    p = st["params"]
    W, H = c.W, c.H
    text = p["text"].strip()
    if not text:
        _skip(c, st, "متنی برای برچسب نیست")
        return
    name, r = _slot_rect(c, p["slot"])
    col = rc(c, p["color"], c.pal["accent"])
    tcol = "#ffffff" if colorx.contrast("#ffffff", col) >= colorx.contrast("#111111", col) else "#111111"
    font = _font_for("badge", p["font"])
    d = p["size"]                                         # قطر، کسری از پهنا
    cx = (r[0] + r[2]) / 2
    cy = (r[1] + r[3]) / 2
    # گوشه‌ها: برچسب به گوشهٔ جعبه می‌چسبد (نه وسطِ جعبه)
    if name in ("tr", "br"):
        cx = r[2] - d / 2
    elif name in ("tl", "bl"):
        cx = r[0] + d / 2
    if name in ("tl", "tr"):
        cy = r[1] + d / 2 * W / H
    elif name in ("bl", "br"):
        cy = r[3] - d / 2 * W / H
    bid = "bd" + st["id"][:8]
    if p["kind"] == "circle":
        sh = _rect_layer(bid, "برچسب", cx, cy, d, d, fill=_solid(col), shape="ellipse")
        inner_w, inner_h = d * W * 0.74, d * W * 0.5
    else:
        sh = _rect_layer(bid, "برچسب", cx, cy, d * 1.5, d * 0.5, fill=_solid(col), shape="rect", radius=1.0)
        inner_w, inner_h = d * 1.5 * W * 0.8, d * 0.5 * W * 0.62
    sh["fx"] = {"shadow": {"color": "#000000", "opacity": 0.22, "blur": 0.012, "dx": 0.0, "dy": 0.008}, "stroke": None, "glow": None}
    _add(c, Z["badge"], sh, step=st["id"], kind="badge", rect=[cx - d / 2, cy - d / 2 * W / H, cx + d / 2, cy + d / 2 * W / H])
    tl = _text_layer("bt" + st["id"][:8], text, typo.role_size("title", 0.9), font=font, weight=800, color=tcol, align="center", lh=1.1)
    tl["name"] = "متنِ برچسب"
    maxh = inner_h * (0.62 if p["sub"] else 1.0)
    typo.fit_text(tl, W, inner_w, maxh, min_size=0.02, max_lines=2)
    m = typo.measure(tl, W)
    ty = cy * H - (m["block_h"] * 0.0 if not p["sub"] else d * W * 0.08)
    tl["cx"], tl["cy"] = round(cx, 5), round(ty / H, 5)
    _add(c, Z["badge_text"], tl, step=st["id"], kind="badge_text", role="badge", auto_color=False, bg=col)
    if p["sub"]:
        sl = _text_layer("bu" + st["id"][:8], p["sub"], typo.role_size("caption", 1.0), font=font, weight=600, color=tcol, align="center", lh=1.1)
        sl["name"] = "خطِ کوچکِ برچسب"
        typo.fit_text(sl, W, inner_w, inner_h * 0.34, min_size=0.02, max_lines=1)
        sl["cx"], sl["cy"] = round(cx, 5), round((cy * H + d * W * 0.22) / H, 5)
        _add(c, Z["badge_text"], sl, step=st["id"], kind="badge_text", role="badge", auto_color=False, bg=col)
    _done(c, st, "برچسب", slot=name)


def h_compare(c: Ctx, st: dict) -> None:
    """قبل و بعد: بومِ پایه = «بعد» (با ظهورِ طراحی)؛ «قبل» = همان قابِ بی‌ظهور، لایهٔ تصویری با ماسکِ نیمهٔ راست."""
    p = st["params"]
    W, H = c.W, c.H
    plain_state = base_state(dict(c.plan, steps=[s for s in c.plan["steps"] if s["tool"] in ("rotate", "crop", "frame")]))
    before, _n = render.render_frame(c.asset, plain_state)
    ref = f"dbef:{c.asset.pk}:{_frame_sig(c.plan)}"[:60]
    existing = PhotoAsset.objects.filter(store=c.store, source_ref=ref).first()
    asset = existing or services._asset_from_bytes(c.store, c.user, render.to_png_bytes(before.convert("RGB")),
                                                    title="قبل (طراحی)", source_ref=ref)
    lay = _common("before", "قبل", "image")
    lay.update({"src": {"kind": "asset", "asset": asset.pk}, "cx": 0.5, "cy": 0.5, "w": 1.0, "rot": 0, "flip_h": False, "flip_v": False,
                "fx": None})
    eps = 0.0015
    lay["mask"] = {"type": "linear", "p0": [0.5 + eps, 0.5], "p1": [0.5 - eps, 0.5], "invert": False}
    _add(c, Z["image"], lay, step=st["id"], kind="before")
    line = _rect_layer("cdiv", "خطِ جداکننده", 0.5, 0.5, 0.004, H / W, fill=_solid("#ffffff", 0.95))
    line["fx"] = {"shadow": {"color": "#000000", "opacity": 0.35, "blur": 0.004, "dx": 0.0, "dy": 0.0}, "stroke": None, "glow": None}
    _add(c, Z["image"] + 1, line, step=st["id"], kind="divider")
    if p["labels"]:
        for side, text in (("right", p["before"]), ("left", p["after"])):
            if not text:
                continue
            tl = _text_layer(f"cl{side[0]}", text, typo.role_size("sub", 1.0), font=_font_for("badge", "estedad"), weight=800,
                             color=c.pal["accent_text"], align="center", lh=1.1)
            tl["name"] = f"برچسبِ {text}"
            tl["box"] = {"color": c.pal["accent"], "opacity": 1.0, "pad": 0.32, "radius": 1.0}
            typo.fit_text(tl, W, 0.3 * W, 0.1 * H, min_size=0.022, max_lines=1)
            sx0, sy0, sx1, sy1 = grid.safe_rect(c.fmt)
            m = typo.measure(tl, W)
            half = (m["block_w"] / 2 + 0.32 * tl["size"] * W) / W
            tl["cx"] = round((sx1 - 0.12) if side == "right" else (sx0 + 0.12), 5)
            tl["cx"] = round(max(sx0 + half, min(sx1 - half, tl["cx"])), 5)
            tl["cy"] = round(sy0 + (m["block_h"] / 2 + 0.32 * tl["size"] * W) / H + 0.01, 5)
            _add(c, Z["badge_text"], tl, step=st["id"], kind="text", role="badge", auto_color=False, plate_pref="accent")
    _done(c, st, "قبل و بعد")


def h_logo(c: Ctx, st: dict) -> None:
    if not c.logo_aspect:
        _skip(c, st, "لوگوی فروشگاه ثبت نشده (از «پروفایل برند» اضافه کنید)")
        return
    p = st["params"]
    W, H = c.W, c.H
    lgk = (c.kit or {}).get("logo") or {}
    w = lgk.get("size") or p["size"]
    h_px = w * W / c.logo_aspect
    sx0, sy0, sx1, sy1 = grid.safe_rect(c.fmt)
    m = 0.0
    pos = lgk.get("position") or p["position"]
    cx = {"tl": sx0 + w / 2, "bl": sx0 + w / 2, "tr": sx1 - w / 2, "br": sx1 - w / 2}.get(pos, 0.5)
    cy = {"tl": sy0 + h_px / H / 2, "tr": sy0 + h_px / H / 2, "top_center": sy0 + h_px / H / 2}.get(pos, sy1 - h_px / H / 2)
    lay = _common("logo", "لوگو", "image", p["opacity"])
    lay.update({"src": dict(c.logo_src), "cx": round(cx, 5), "cy": round(cy, 5), "w": round(w, 5), "rot": 0, "flip_h": False,
                "flip_v": False, "fx": None})
    _add(c, Z["logo"], lay, step=st["id"], kind="logo", bbox=[cx - w / 2, cy - h_px / H / 2, cx + w / 2, cy + h_px / H / 2])
    _done(c, st, "لوگو", position=pos)


def h_image(c: Ctx, st: dict) -> None:
    p = st["params"]
    if not p["asset"] or not PhotoAsset.objects.filter(store=c.store, pk=p["asset"]).exists():
        _skip(c, st, "عکسِ کتابخانه پیدا نشد")
        return
    a = PhotoAsset.objects.get(pk=p["asset"])
    name, r = _slot_rect(c, p["slot"])
    w = p["size"]
    h_px = w * c.W * (a.height / max(1, a.width))
    cx = (r[0] + r[2]) / 2
    cy = (r[1] + r[3]) / 2
    lay = _common("im" + st["id"][:8], a.title or "تصویر", "image", p["opacity"])
    lay.update({"src": {"kind": "asset", "asset": a.pk}, "cx": round(cx, 5), "cy": round(cy, 5), "w": round(w, 5), "rot": 0,
                "flip_h": False, "flip_v": False, "fx": None})
    _add(c, Z["image"], lay, step=st["id"], kind="image")
    _done(c, st, "تصویر", slot=name)


def h_grade(c: Ctx, st: dict) -> None:
    """رنگ: یا لغزنده‌های عکسِ پایه (در ``state``) یا لایهٔ تنظیم روی همه. این‌جا فقط حالتِ لایه (scope=all) ساخته می‌شود."""
    p = st["params"]
    scope = p["scope"]
    if scope == "auto":
        scope = "all" if c.product else "photo"
    adj, curve = grade_values(p)
    if not adj and not curve:
        _done(c, st, "بی‌تغییر")
        return
    if scope == "all":
        lay = _adjust_layer("grade", "نور و رنگ", adj)
        lay["curve"] = curve
        _add(c, Z["adjust"], lay, step=st["id"], kind="grade")
    _done(c, st, "نور و رنگ تنظیم شد", scope=scope)


def grade_values(p: dict) -> tuple[dict, dict]:
    adj: dict = {}
    curve: dict = {}
    if p.get("preset"):
        rec = catalog.kit_presets().get(p["preset"], {}).get("recipe") or {}
        adj.update(rec.get("adjust") or {})
        curve.update(catalog.normalize_curve(rec.get("curve")))
    adj.update(p.get("adjust") or {})
    curve.update(p.get("curve") or {})
    return develop_np.normalize_adjust(adj), catalog.normalize_curve(curve)


HANDLERS = {"cutout": h_cutout, "backdrop": h_backdrop, "shadow": h_shadow, "local_adjust": h_local_adjust, "scrim": h_scrim,
            "shape": h_shape, "text": h_text, "badge": h_badge, "logo": h_logo, "image": h_image, "grade": h_grade,
            "compare": h_compare}
# مرحله‌های وابسته به محصولِ جداشده باید بعد از cutout بیایند؛ PHASE همین را تضمین می‌کند (cutout=4 < backdrop=5 < shadow=6 …).


# ───────────────────────────── ساختِ حالت

def _store_brand(store) -> list[str]:
    cols = getattr(store, "colors", None)
    if isinstance(cols, dict):
        return [v for v in cols.values() if colorx.is_hex(v)]
    if isinstance(cols, list):
        return [v for v in cols if colorx.is_hex(v)]
    return []


def _logo_aspect(store, kit: dict | None = None) -> float | None:
    try:
        la = brand_mod.logo_asset(store, kit)
        if la is not None:
            p = services.abs_path(la.original)
        elif ((kit or {}).get("logo") or {}).get("mode") == "none":
            return None
        else:
            p = services._store_logo(store)
        if p is None:
            return None
        with Image.open(p) as im:
            return im.width / max(1, im.height)
    except Exception:  # noqa: BLE001
        return None


def base_state(plan: dict) -> dict:
    """گام‌های هندسه و رنگِ عکسِ پایه ⇒ حالتِ ادیتور (بی لایه)."""
    s = render.default_state()
    for st in plan["steps"]:
        if not st["on"]:
            continue
        p = st["params"]
        if st["tool"] == "rotate":
            s["turn"] = int(p["turn"])
            s["straighten"] = p["straighten"]
            s["flipH"], s["flipV"] = bool(p["flip_h"]), bool(p["flip_v"])
        elif st["tool"] == "crop":
            s["crop"] = {"x": p["x"] / 100, "y": p["y"] / 100, "w": min(1 - p["x"] / 100, p["w"] / 100), "h": min(1 - p["y"] / 100, p["h"] / 100)}
        elif st["tool"] == "frame":
            if p["format"] != "orig":
                s["tools"]["crop_format"] = catalog.normalize_params("crop_format", {
                    "format": p["format"], "fit": p["fit"], "focus": p["focus"], "fill": p["fill"], "fill_color": p["fill_color"],
                    "padding": p["padding"]}, strict=False)
        elif st["tool"] == "export":
            s["out"] = {"format": p["format"], "quality": p["quality"], "max_kb": p["max_kb"], "long_edge": p["long_edge"]}
    return s


def build(asset: PhotoAsset, plan: dict, *, user=None, tag: str = "", src: Image.Image | None = None, kit: dict | None = None) -> dict:
    """برنامهٔ وارسی‌شده ⇒ {state, canvas, report, notes, needs, analysis, palette, meta, frame}.

    ``frame`` (تصویرِ PIL) برای رندر و وارسی نگه داشته می‌شود و در JSON نمی‌آید."""
    store = asset.store
    state = base_state(plan)
    has_cutout = any(s["on"] and s["tool"] == "cutout" for s in plan["steps"])
    # رنگِ ظهور: روی عکسِ پایه (مگر scope=all یا محصولِ جداشده در کار باشد)
    g = toolspec.find(plan, "grade")
    grade_on_photo = False
    if g:
        scope = g["params"]["scope"]
        grade_on_photo = scope == "photo" or (scope == "auto" and not has_cutout)
        if grade_on_photo:
            state["adjust"], state["curve"] = grade_values(g["params"])
    frame, fnotes = render.render_frame(asset, state, src)
    W, H = frame.size
    fmt = plan["format"]
    an = analyze.analyze(frame, fmt=fmt, facts=asset.facts, findings=asset.findings)
    rgb_small, _a = analyze._small(frame)
    brand = (kit or {}).get("colors") or _store_brand(store)
    pal = colorx.make_palette(an["dominant"], an["accent"], mood=plan.get("mood", "auto"), variation=plan.get("variation", 0), brand=brand,
                              image_luma=an["brightness"]["mean"])
    c = Ctx(asset=asset, store=store, user=user, plan=plan, fmt=fmt, W=W, H=H, frame=frame, an=an, pal=pal, rgb_small=rgb_small,
            logo_aspect=_logo_aspect(store, kit), kit=kit, tag=tag)
    la = brand_mod.logo_asset(store, kit)
    if la is not None:
        c.logo_src = {"kind": "asset", "asset": la.pk}
    c.notes += fnotes
    c.layers.append((Z["base"], 0, _base_layer()))
    c.meta["base"] = {"z": 0, "kind": "base"}
    c.has_backdrop = any(s["on"] and s["tool"] == "backdrop" for s in plan["steps"]) and has_cutout
    for st in plan["steps"]:
        if not st["on"]:
            c.report[st["id"]] = {"ok": False, "note": "خاموش"}
            continue
        t = st["tool"]
        if t in ("rotate", "crop", "frame", "export"):
            c.report[st["id"]] = {"ok": True, "note": ""}
            continue
        if t == "ai_fill":
            c.needs["manual"].append(st["id"])
            c.report[st["id"]] = {"ok": False, "note": "این مرحله در حالتِ دستی (پرکردنِ هوشمند) اجرا می‌شود", "deferred": True}
            continue
        h = HANDLERS.get(t)
        if h is None:
            c.report[st["id"]] = {"ok": False, "note": "پشتیبانی نمی‌شود"}
            continue
        if t == "backdrop" and has_cutout and (c.cut is None or not c.cut.get("ok")):
            # زمینهٔ تازه بی محصولِ جداشده کلِ عکس را می‌پوشاند ⇒ این‌جا فقط وقتی محصول جدا شده اجرا می‌شود
            if not c.product:
                _skip(c, st, "چون محصول جدا نشد، زمینهٔ تازه نگذاشتیم تا عکس پوشیده نشود")
                c.has_backdrop = False
                continue
        try:
            h(c, st)
        except Exception as exc:  # noqa: BLE001 — یک مرحلهٔ خراب نباید کلِ طراحی را بکشد
            logger.exception("designer: step %s (%s) failed", st["id"], t)
            _skip(c, st, f"این مرحله انجام نشد: {exc}")
    # محصولِ جداشده بی زمینهٔ تازه ⇒ زمینهٔ سفیدِ ساده (وگرنه عکسِ اصل پشتش دیده می‌شود)
    if c.product and not any(m.get("kind") == "backdrop" for m in c.meta.values()):
        c.notes.append("زمینهٔ تازه‌ای انتخاب نشده بود؛ زمینهٔ سفید گذاشته شد.")
        _add(c, Z["backdrop"], _rect_layer("bg", "زمینهٔ سفید", 0.5, 0.5, 1.0, H / W, fill=_solid("#ffffff")), step="", kind="backdrop")
        c.has_backdrop = True
    ordered = [x[2] for x in sorted(c.layers, key=lambda t: (t[0], t[1]))]
    state["layers"] = ordered
    return {"state": state, "canvas": [W, H], "fmt": fmt, "product_box": (c.product["box"] if c.product else None), "report": c.report, "notes": c.notes, "needs": c.needs, "analysis": analyze.public(an),
            "palette": pal, "meta": c.meta, "frame": frame, "has_backdrop": c.has_backdrop,
            "cutout": ({k: v for k, v in (c.cut or {}).items() if k != "mask"} if c.cut else None)}
