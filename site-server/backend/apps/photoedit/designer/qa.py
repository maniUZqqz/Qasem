"""وارسیِ قطعیِ طراحی (بی هوشِ مصنوعی) و اصلاحِ خودکار.

هر بار روی «رندرِ واقعی» کار می‌کند: زمینهٔ زیرِ هر متن (همهٔ لایه‌ها به‌جز متن‌ها) ⇒ کنتراستِ WCAG با «بدترین ۱۰٪» پیکسل‌ها.

بررسی‌ها: کنتراست (۴٫۵ برای متنِ معمولی، ۳ برای درشت)، حاشیهٔ امنِ قاب (استوری: بالا ۱۴٪ و پایین ۲۰٪)، سرریز و ریزی،
هم‌پوشانیِ متن با متن یا با محصول، سلسله‌مراتبِ اندازه، و تعادلِ بصری. اصلاحِ خودکار: رنگِ متن ⇐ کادرِ پشتِ متن ⇐
جابه‌جایی به داخلِ حاشیهٔ امن ⇐ دورکردنِ متن‌ها از هم و از محصول.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image

from .. import textlayer
from . import colorx, grid, render, typo

TEXT_KINDS = ("text", "badge_text")
LARGE_SIZE = 0.045          # کسری از پهنا (≈ ۴۹px در ۱۰۸۰) — «متنِ درشت» برای WCAG
LARGE_BOLD = 0.035
PENALTY = {"contrast": 16, "safe": 9, "overlap": 12, "tiny": 7, "product": 10, "hierarchy": 5, "balance": 4, "fonts": 3}
CAPS = {"contrast": 40, "safe": 20, "overlap": 24, "tiny": 14, "product": 20, "hierarchy": 5, "balance": 4, "fonts": 3}


def text_rect(layer: dict, W: int, H: int) -> list[float]:
    """جعبهٔ متن (با کادرِ پشتش) به کسری از بوم."""
    m = textlayer.layout(layer, W)
    size_px = m["size_px"]
    pad = float((layer.get("box") or {}).get("pad", 0)) * size_px if layer.get("box") else 0.0
    w, h = m["block_w"] + 2 * pad, m["block_h"] + 2 * pad
    cx, cy = layer["cx"] * W, layer["cy"] * H
    return [(cx - w / 2) / W, (cy - h / 2) / H, (cx + w / 2) / W, (cy + h / 2) / H]


def _is_large(layer: dict) -> bool:
    return layer["size"] >= LARGE_SIZE or (layer["weight"] >= 700 and layer["size"] >= LARGE_BOLD)


def _threshold(layer: dict) -> float:
    return colorx.WCAG_LARGE if _is_large(layer) else colorx.WCAG_NORMAL


BG_SIDE = 640          # سنجشِ کنتراست روی نسخهٔ ≤۶۴۰ پیکسلی کافی است (نمونه‌برداری نسبی است) و چند برابر سریع‌تر


def _bg_frame(build):
    """بومِ قاب‌شده به اندازهٔ کوچک (یک بار ساخته و در build نگه داشته می‌شود)."""
    small = build.get("_bg_frame")
    if small is None:
        fr = build["frame"]
        k = BG_SIDE / max(fr.size)
        small = fr if k >= 1 else fr.resize((max(64, round(fr.width * k)), max(64, round(fr.height * k))), Image.Resampling.BILINEAR)
        build["_bg_frame"] = small
    return small


def _bg_render(asset, build, exclude_ids=None):
    """رندرِ همهٔ لایه‌ها به‌جز متن‌ها (زمینهٔ زیرِ متن) روی بومِ کوچک."""
    layers = [l for l in build["state"]["layers"]
              if l["type"] != "text" and (not exclude_ids or l["id"] not in exclude_ids)
              and build["meta"].get(l["id"], {}).get("kind") not in ("strike",)]
    # جابه‌جایی/اصلاحِ متن‌ها زمینه را عوض نمی‌کند؛ فقط وقتی لایه‌های غیرمتن عوض شدند (مثلاً سایهٔ خوانایی) دوباره رندر می‌کنیم
    sig = json.dumps(layers, sort_keys=True, default=str)
    cached = build.get("_bg_cache")
    if cached and cached[0] == sig:
        return cached[1]
    img, _n = render.compose_layers(asset, _bg_frame(build), layers)
    arr = np.asarray(img.convert("RGB"))
    build["_bg_cache"] = (sig, arr)
    return arr


def _pixels(bg: np.ndarray, rect) -> np.ndarray:
    h, w = bg.shape[:2]
    x0, y0 = int(max(0, rect[0] * w)), int(max(0, rect[1] * h))
    x1, y1 = int(min(w, max(x0 + 1, rect[2] * w))), int(min(h, max(y0 + 1, rect[3] * h)))
    part = bg[y0:y1, x0:x1]
    step = max(1, int(np.sqrt(part.shape[0] * part.shape[1] / 6000)))
    return part[::step, ::step].reshape(-1, 3)


def _effective_pixels(layer: dict, px: np.ndarray) -> np.ndarray:
    """اگر پشتِ متن کادر است، رنگی که واقعاً زیرِ حروف دیده می‌شود: ترکیبِ کادر روی زمینه."""
    box = layer.get("box")
    if box and box.get("opacity", 0) >= 0.4:
        pc = np.array(colorx.hex_to_rgb(box["color"]), np.float64)
        a = float(box["opacity"])
        return (px.astype(np.float64) * (1 - a) + pc * a)
    return px


def contrast_of(layer: dict, bg: np.ndarray, W: int, H: int) -> float:
    rect = text_rect(layer, W, H)
    px = _effective_pixels(layer, _pixels(bg, rect))
    return colorx.region_contrast(colorx.hex_to_rgb(layer["color"]), px)


def _plate_color_for(text_hex: str) -> str:
    return "#0b0f1a" if colorx.luminance(colorx.hex_to_rgb(text_hex)) > 0.45 else "#ffffff"


def check(asset, build: dict, bg: np.ndarray | None = None) -> dict:
    """⇒ {score، issues:[{kind, layer, text(فارسی), value}]، metrics}. هیچ‌چیز را تغییر نمی‌دهد."""
    W, H = build["canvas"]
    fmt = build["fmt"]
    layers = build["state"]["layers"]
    meta = build["meta"]
    texts = [l for l in layers if l["type"] == "text" and meta.get(l["id"], {}).get("kind") in TEXT_KINDS]
    issues: list[dict] = []
    if bg is None:
        bg = _bg_render(asset, build)
    safe = grid.safe_rect(fmt)
    rects = {l["id"]: text_rect(l, W, H) for l in texts}
    min_ratio = 21.0
    for l in texts:
        ratio = contrast_of(l, bg, W, H)
        min_ratio = min(min_ratio, ratio)
        if ratio < _threshold(l) - 1e-6:
            issues.append({"kind": "contrast", "layer": l["id"], "value": round(ratio, 2), "text":
                           f"متنِ «{l['text'][:18]}» روی زمینه کم‌کنتراست است ({typo.fa_digits(round(ratio, 1))} از {typo.fa_digits(_threshold(l))})"})
        if meta[l["id"]].get("kind") == "text" and not grid.inside(rects[l["id"]], safe):
            issues.append({"kind": "safe", "layer": l["id"], "text": f"متنِ «{l['text'][:18]}» از حاشیهٔ امنِ قاب بیرون زده"})
        floor = typo.MIN_KEY_LEGIBLE if meta[l["id"]].get("role") in ("title", "hero", "display", "price") else typo.MIN_LEGIBLE
        if l["size"] < floor - 1e-6 and meta[l["id"]].get("kind") == "text":
            issues.append({"kind": "tiny", "layer": l["id"], "text": f"متنِ «{l['text'][:18]}» روی گوشی خیلی ریز است"})
    ids = [l["id"] for l in texts if meta[l["id"]].get("kind") == "text"]
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ov = grid.overlap_area(rects[a], rects[b])
            small = min(grid.area(rects[a]), grid.area(rects[b]))
            if small > 0 and ov / small > 0.06:
                issues.append({"kind": "overlap", "layer": b, "other": a, "text": "دو متن روی هم افتاده‌اند"})
    pbox = build.get("product_box")
    if pbox:
        for i in ids:
            a = grid.area(rects[i])
            if a > 0 and grid.overlap_area(rects[i], pbox) / a > 0.14:
                issues.append({"kind": "product", "layer": i, "text": "متن روی محصول افتاده است"})
    # سلسله‌مراتب
    big = [l for l in texts if meta[l["id"]].get("role") in ("title", "hero", "display")]
    sub = [l for l in texts if meta[l["id"]].get("role") in ("sub", "caption", "body")]
    if big and sub and max(s["size"] for s in sub) * 1.2 > max(b["size"] for b in big):
        issues.append({"kind": "hierarchy", "layer": big[0]["id"], "text": "تیتر باید دست‌کم ۲۰٪ از متنِ دوم بزرگ‌تر باشد"})
    # تعادلِ بصری: مرکزِ جرمِ جعبه‌ها (متن‌ها + محصول)
    boxes = [rects[i] for i in ids] + ([pbox] if pbox else [])
    bal = 0.0
    if len(boxes) >= 2:
        ar = np.array([grid.area(b) for b in boxes])
        if ar.sum() > 0:
            cx = float(sum(a * (b[0] + b[2]) / 2 for a, b in zip(ar, boxes)) / ar.sum())
            cy = float(sum(a * (b[1] + b[3]) / 2 for a, b in zip(ar, boxes)) / ar.sum())
            bal = max(abs(cx - 0.5), abs(cy - 0.5))
    if bal > 0.2:
        issues.append({"kind": "balance", "layer": "", "value": round(bal, 3), "text": "وزنِ بصریِ طراحی به یک سمت کشیده شده"})
    fonts = {l["font"] for l in texts}
    if len(fonts) > 2:
        issues.append({"kind": "fonts", "layer": "", "text": "بیش از دو فونتِ متفاوت؛ ظاهر شلوغ می‌شود"})
    score = 100
    spent: dict[str, int] = {}
    for it in issues:
        k = it["kind"]
        spent[k] = min(CAPS[k], spent.get(k, 0) + PENALTY[k])
    score -= sum(spent.values())
    metrics = {"min_contrast": round(min_ratio, 2) if texts else None, "texts": len(texts),
               "min_font": min((l["size"] for l in texts), default=None), "balance": round(bal, 3)}
    return {"score": max(0, min(100, score)), "issues": issues, "metrics": metrics}


# ───────────────────────────── اصلاح

def _set_plate(l: dict, text_color: str) -> None:
    l["box"] = {"color": _plate_color_for(text_color), "opacity": 0.86, "pad": 0.34, "radius": 0.22}


def _apply_plate(build: dict, layer: dict, text_color: str) -> None:
    """کادرِ پشتِ متن می‌گذارد و متن را دوباره جا می‌دهد تا «متن + کادر» از جعبهٔ خودش بیرون نزند (سرریزِ حاشیه)."""
    W, H = build["canvas"]
    m = build["meta"].get(layer["id"], {})
    _set_plate(layer, text_color)
    layer["shadow"] = None
    rect = m.get("rect")
    if not rect:
        return
    role = m.get("role")
    floor = typo.MIN_KEY_LEGIBLE if role in ("title", "hero", "display", "price") else typo.MIN_LEGIBLE
    for _ in range(2):                                    # پد به اندازهٔ متن بسته است ⇒ دو دور
        pad_px = layer["box"]["pad"] * layer["size"] * W
        max_w = (rect[2] - rect[0]) * W - 2 * pad_px
        max_h = (rect[3] - rect[1]) * H - 2 * pad_px
        if max_w < 60 or max_h < 20:
            break
        typo.fit_text(layer, W, max_w, max_h, min_size=floor, max_lines=int(m.get("max_lines") or 3))
        typo.tighten_width(layer, W, cap_px=max_w)


def fix_contrast(asset, build: dict, layer: dict, bg: np.ndarray) -> str | None:
    W, H = build["canvas"]
    meta = build["meta"][layer["id"]]
    thr = _threshold(layer)
    cands = ["#ffffff", "#111111", "#000000", build["palette"]["text"], build["palette"]["accent_text"]]
    if meta.get("auto_color", False) and not layer.get("box"):
        best, best_r = None, 0.0
        for col in cands:
            probe = dict(layer, color=col)
            r = contrast_of(probe, bg, W, H)
            if r > best_r:
                best, best_r = col, r
        if best and best_r >= thr and best != layer["color"]:
            layer["color"] = best
            return f"رنگِ متنِ «{layer['text'][:18]}» عوض شد تا روی زمینه خوانا شود"
    # اول سایهٔ ملایمِ زیرِ متن را پررنگ‌تر کن (اگر هست)؛ طبیعی‌تر از کادر است
    if not layer.get("box"):
        scrims = [l for l in build["state"]["layers"] if build["meta"].get(l["id"], {}).get("kind") == "scrim"]
        for scr in scrims:
            base_op = float(scr["fill"]["opacity"])
            for bump in (0.15, 0.3):
                scr["fill"]["opacity"] = round(min(0.9, base_op + bump), 3)
                if scr["fill"]["opacity"] > base_op and contrast_of(layer, _bg_render(asset, build), W, H) >= thr:
                    return f"سایهٔ پشتِ متنِ «{layer['text'][:18]}» پررنگ‌تر شد تا خوانا شود"
            scr["fill"]["opacity"] = base_op
    # کادرِ پشتِ متن
    probe = dict(layer)
    _set_plate(probe, layer["color"])
    if contrast_of(probe, bg, W, H) >= thr:
        _apply_plate(build, layer, layer["color"])
        return f"پشتِ متنِ «{layer['text'][:18]}» کادر گذاشتیم تا خوانا شود"
    # رنگِ متن هم باید با کادر جور شود
    for col in cands:
        probe = dict(layer, color=col)
        _set_plate(probe, col)
        if contrast_of(probe, bg, W, H) >= thr:
            layer["color"] = col
            _apply_plate(build, layer, col)
            return f"رنگِ متنِ «{layer['text'][:18]}» و کادرِ پشتش برای خوانایی تنظیم شد"
    return None


def _move_into(rect, safe) -> tuple[float, float]:
    dx = dy = 0.0
    if rect[0] < safe[0]:
        dx = safe[0] - rect[0]
    elif rect[2] > safe[2]:
        dx = safe[2] - rect[2]
    if rect[1] < safe[1]:
        dy = safe[1] - rect[1]
    elif rect[3] > safe[3]:
        dy = safe[3] - rect[3]
    return dx, dy


def sync_strikes(build: dict) -> None:
    """خطِ روی «قیمتِ قبلی» همیشه وسطِ همان متن و به پهنای خودِ متن بماند (متن ممکن است جابه‌جا یا کوچک شده باشد)."""
    W, _H = build["canvas"]
    layers = {l["id"]: l for l in build["state"]["layers"]}
    for lid, m in build["meta"].items():
        if m.get("kind") != "strike":
            continue
        t, s = layers.get(m.get("for_layer")), layers.get(lid)
        if t and s:
            widths = textlayer.layout(t, W)["widths"]
            s["cx"], s["cy"] = t["cx"], t["cy"]
            s["w"] = round(max(widths + [1.0]) / W * 1.06, 5)


def restack(build: dict) -> bool:
    """متن‌های «زیرِ فلان متن» دوباره زیرِ همان چیده می‌شوند (بعد از کادر/اصلاح اندازهٔ متن‌ها عوض شده)؛ بلوک از پایینِ حاشیهٔ امن بیرون نزند."""
    W, H = build["canvas"]
    safe = grid.safe_rect(build["fmt"])
    layers = {l["id"]: l for l in build["state"]["layers"]}
    moved = False
    for lid, m in build["meta"].items():
        aid = m.get("below_of")
        if not aid or lid not in layers or aid not in layers:
            continue
        a, f = layers[aid], layers[lid]
        ra, rf = text_rect(a, W, H), text_rect(f, W, H)
        d = (ra[3] + 0.012) - rf[1]
        dx = 0.0
        if f["align"] == "right":
            dx = ra[2] - rf[2]
        elif f["align"] == "left":
            dx = ra[0] - rf[0]
        else:
            dx = (ra[0] + ra[2]) / 2 - (rf[0] + rf[2]) / 2
        if abs(d) > 1e-4 or abs(dx) > 1e-4:
            f["cy"] = round(f["cy"] + d, 5)
            f["cx"] = round(f["cx"] + dx, 5)
            moved = True
            rf = text_rect(f, W, H)
        over = rf[3] - safe[3]
        if over > 1e-4:
            up = min(over, max(0.0, ra[1] - safe[1]))
            a["cy"], f["cy"] = round(a["cy"] - up, 5), round(f["cy"] - up, 5)
            moved = True
    return moved


def autofix(asset, build: dict, max_pass: int = 4) -> list[str]:
    """چند دور بررسی و اصلاح؛ ⇒ فهرستِ جمله‌های فارسی از آنچه اصلاح شد. ``build["qa"]`` را هم می‌نویسد."""
    W, H = build["canvas"]
    fixes: list[str] = []
    build.setdefault("fmt", build.get("fmt") or "square")
    for _ in range(max_pass):
        bg = _bg_render(asset, build)
        res = check(asset, build, bg)
        if not res["issues"]:
            break
        changed = False
        layers = {l["id"]: l for l in build["state"]["layers"]}
        safe = grid.safe_rect(build["fmt"])
        for it in res["issues"]:
            l = layers.get(it["layer"])
            k = it["kind"]
            if k == "contrast" and l:
                msg = fix_contrast(asset, build, l, bg)
                if msg:
                    fixes.append(msg)
                    changed = True
            elif k == "safe" and l:
                r = text_rect(l, W, H)
                dx, dy = _move_into(r, safe)
                if abs(dx) + abs(dy) > 1e-4:
                    l["cx"], l["cy"] = round(l["cx"] + dx, 5), round(l["cy"] + dy, 5)
                    fixes.append(f"متنِ «{l['text'][:18]}» به داخلِ حاشیهٔ امن آمد")
                    changed = True
            elif k == "tiny" and l:
                role = build["meta"][l["id"]].get("role")
                floor = typo.MIN_KEY_LEGIBLE if role in ("title", "hero", "display", "price") else typo.MIN_LEGIBLE
                l["size"] = floor
                fixes.append(f"اندازهٔ متنِ «{l['text'][:18]}» به حدِ خوانایی رسید")
                changed = True
            elif k == "overlap" and l:
                other = layers.get(it.get("other"))
                if other:
                    ro, rl = text_rect(other, W, H), text_rect(l, W, H)
                    shift = (ro[3] - rl[1]) + 0.012
                    if shift > 0 and rl[3] + shift <= safe[3]:
                        l["cy"] = round(l["cy"] + shift, 5)
                        fixes.append("متنِ تکراری‌شده از هم جدا شد")
                        changed = True
            elif k == "product" and l:
                pb = build.get("product_box")
                rl = text_rect(l, W, H)
                if pb:
                    h = rl[3] - rl[1]
                    up = pb[1] - 0.015 - h          # بالای محصول
                    down = pb[3] + 0.015            # زیرِ محصول
                    options = []
                    if up >= safe[1]:
                        options.append((abs(up - rl[1]), up))
                    if down + h <= safe[3]:
                        options.append((abs(down - rl[1]), down))
                    if options:
                        _d, ny = min(options)
                        l["cy"] = round(ny + h / 2, 5)
                        fixes.append(f"متنِ «{l['text'][:18]}» از روی محصول کنار رفت")
                        changed = True
        if restack(build):
            changed = True
        if not changed:
            break
    sync_strikes(build)
    bg = _bg_render(asset, build)
    build["qa"] = check(asset, build, bg)
    build["qa"]["fixes"] = fixes
    return fixes
