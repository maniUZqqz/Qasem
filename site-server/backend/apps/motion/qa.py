"""کنترلِ کیفیتِ قاعده‌ای (بدونِ مدل) + حلقهٔ «بسنج ⇒ اصلاح کن ⇒ دوباره بسنج».

دو لایه:
  ۱) static_findings(spec) — از خودِ طرح، بدونِ مرورگر: زمانِ خواندن (≈۰٫۳۲ ثانیه برای هر کلمهٔ فارسی)، کمینهٔ مدتِ قطعه، شلوغی (کلمه/آیتم/رویهٔ هم‌زمان)،
     همخوانیِ رنگِ تأکید با زمینه، طولِ گفتار نسبت به مدتِ صحنه.
  ۲) geometry_findings(spec, shots) — از فریم‌های واقعی: هر «shot» = هندسهٔ هر بلوکِ متن/جعبه که صفحه گزارش کرده (NMQA) + تصویرِ همان فریم.
     بیرون‌زدگی و بریدگی، هم‌پوشانیِ متن‌ها، ناحیهٔ امنِ پلتفرم، کمینهٔ اندازهٔ فونت و کنتراستِ WCAG از پیکسل‌های پشتِ متن.

هر یافته یک اصلاحِ خودکار دارد (فهرستِ عملیاتِ patch.py): کوچک/جمع‌کردنِ متن، بلندترکردنِ صحنه، رنگِ خوانا، جابه‌جاییِ رویه به ناحیهٔ امن، شکستنِ صحنهٔ شلوغ.
run_loop بعد از هر دور دوباره می‌سنجد (حداکثر ۳ دور) و گزارشِ کاملِ دورها را برمی‌گرداند.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from . import catalog, components, motionlib, patch as patch_mod, specs, timeline

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
LABELS = {
    "too_short": "مدتِ صحنه کم است", "crowded": "صحنه شلوغ است", "overflow": "متن از قاب/کادر بیرون زده", "overlap": "دو متن روی هم افتاده‌اند",
    "safe_zone": "بیرون از ناحیهٔ امنِ پلتفرم", "small_text": "متن خیلی ریز است", "low_contrast": "کنتراستِ متن کم است", "accent_contrast": "رنگِ تأکید روی زمینه کم‌رنگ است", "static_scene": "صحنهٔ طولانی و ثابت",
    "speech_longer": "گفتار از صحنه بلندتر است", "platform_missing": "پلتفرم انتخاب نشده", "overlays_busy": "رویه‌های هم‌زمانِ زیاد",
}
READ_TOLERANCE = 0.65       # a viewer reads a little faster than the average: only a clearly too short scene is flagged
PRIORITY = ["too_short", "speech_longer", "overflow", "overlap", "safe_zone", "low_contrast", "accent_contrast", "small_text", "crowded", "overlays_busy", "static_scene"]
FA_NUM = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n) -> str:
    return str(n).translate(FA_NUM)


# ───────────────────────────────────────────── رنگ (WCAG)

def parse_color(c: str):
    if not c:
        return None
    c = c.strip().lower()
    m = re.match(r"rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:[ ,/]+([\d.]+))?", c)
    if m:
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (round(float(m.group(1))), round(float(m.group(2))), round(float(m.group(3))), a)
    m = re.match(r"^#?([0-9a-f]{6})$", c)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    return None


def _lin(v: float) -> float:
    v /= 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(rgb) -> float:
    return 0.2126 * _lin(rgb[0]) + 0.7152 * _lin(rgb[1]) + 0.0722 * _lin(rgb[2])


def contrast(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mix(a, b, t: float) -> tuple:
    return tuple(round(a[k] + (b[k] - a[k]) * t) for k in range(3))


def hexof(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(x) for x in rgb[:3])


def best_text_color(bg, candidates=("#ffffff", "#111111")) -> tuple:
    """خوانا‌ترین رنگ روی bg ⇒ (hex, نسبتِ کنتراست)."""
    best = max(candidates, key=lambda h: contrast(parse_color(h), bg))
    return best, contrast(parse_color(best), bg)


# ───────────────────────────────────────────── ابزارِ یافته

def _finding(code, severity, scene, message, ops=None, **extra) -> dict:
    return {"code": code, "label": LABELS.get(code, code), "severity": severity, "scene": scene, "message": message, "ops": ops or [], "auto": bool(ops), **extra}


def _scene_words(sc: dict) -> int:
    comp = components.get(sc.get("type", ""))
    if not comp:
        return 0
    total = 0
    for key in comp["read"]:
        v = sc.get(key)
        if isinstance(v, str):
            total += specs.word_count(v)
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, str):
                    total += specs.word_count(it)
                elif isinstance(it, dict):
                    for x in it.values():
                        if isinstance(x, str):
                            total += specs.word_count(x)
                        elif isinstance(x, list):
                            total += sum(specs.word_count(y) for y in x if isinstance(y, str))
    for ov in sc.get("overlays") or []:
        oc = components.get(ov.get("type", "")) or {}
        total += sum(specs.word_count(str(ov.get(k) or "")) for k in oc.get("read", ()) if isinstance(ov.get(k), str))
    return total


def reading_needed(sc: dict, lang: str = "fa") -> float:
    """ثانیه‌ای که این صحنه برای خوانده‌شدن لازم دارد: ورودِ عناصر + کلمه‌ها × نرخ؛ حداقلِ هر قطعه؛ و گفتارِ صحنه."""
    comp = components.get(sc.get("type", "")) or {"dur": (2, 3, 6)}
    rate = motionlib.READ_S_PER_WORD if lang == "fa" else motionlib.READ_S_PER_WORD_EN
    n = _scene_words(sc)
    need = motionlib.ENTRANCE_S + n * rate
    if sc.get("type") in ("title", "stat", "cta", "logo", "kinetic_title", "countdown", "rating", "counter", "sticker"):
        need = max(need, comp["dur"][0])          # قطعه‌های پرحرکت حداقلِ خودشان را می‌خواهند
    else:
        need = max(need, comp["dur"][0] * 0.8)
    return round(need, 2)


def speech_needed(sc: dict) -> float:
    cues = sc.get("cues") or []
    if cues:
        return round(max(c["e"] for c in cues) + 0.45, 2)
    nar = sc.get("narration") or ""
    return round(specs.word_count(nar) * 0.38 + 0.6, 2) if nar else 0.0


def _items_count(sc: dict) -> int:
    comp = components.get(sc.get("type", "")) or {}
    key = comp.get("items")
    if key and isinstance(sc.get(key), list):
        return len(sc[key])
    return max((len(v) for k, v in sc.items() if isinstance(v, list) and k not in ("overlays", "cues", "emphasis", "sfx")), default=0)


def simultaneous(sc: dict) -> int:
    """برآوردِ عناصرِ متحرکِ هم‌زمان: آیتم‌ها + رویه‌ها + دوربینِ پارالاکس."""
    n = _items_count(sc) + 2 * len(sc.get("overlays") or []) + (3 if (sc.get("camera") or {}).get("move") == "parallax" else 0)
    return n + (2 if sc.get("title") or sc.get("text") else 1)


def _can_split(sc: dict) -> bool:
    return len(patch_mod.split_scene(sc)) == 2


# ───────────────────────────────────────────── لایهٔ ۱: از خودِ طرح

LONG_STATIC_S = 6.0           # a scene this long that never moves feels dead: a slow camera move is added (the reading time is a floor, not a reason to freeze)


def static_findings(spec: dict) -> list:
    out: list = []
    lang = spec.get("lang", "fa")
    st = catalog.get(spec.get("style", "")) or {}
    pal = st.get("palette") or {}
    for i, sc in enumerate(spec.get("scenes") or []):
        n = i + 1
        dur = float(sc.get("duration") or 4)
        need = reading_needed(sc, lang)
        sp = speech_needed(sc)
        if sp and sp > dur + 0.05:
            new = min(specs.MAX_SCENE_S, math.ceil(max(sp, need) * 2) / 2)
            out.append(_finding("speech_longer", "error", i, f"صحنهٔ {fa(n)}: گفتار {fa(round(sp, 1))} ثانیه است ولی صحنه {fa(round(dur, 1))} ثانیه؛ مدت به {fa(new)} ثانیه می‌رسد.",
                                [{"op": "set", "path": f"scenes/{i}/duration", "value": new}], needed=sp, duration=dur))
        elif need > dur + READ_TOLERANCE:
            new = min(specs.MAX_SCENE_S, math.ceil(need * 2) / 2)
            out.append(_finding("too_short", "warn", i, f"صحنهٔ {fa(n)}: برای خواندنِ متن حداقل {fa(round(need, 1))} ثانیه لازم است ({fa(_scene_words(sc))} کلمه)؛ مدت از {fa(round(dur, 1))} به {fa(new)} ثانیه می‌رسد.",
                                [{"op": "set", "path": f"scenes/{i}/duration", "value": new}], needed=need, duration=dur))
        eff = dur
        for f in out[-1:]:
            if f.get("scene") == i and f["code"] in ("speech_longer", "too_short"):
                eff = max(dur, float(f["ops"][0]["value"]))
        if eff >= LONG_STATIC_S and ((sc.get("camera") or {}).get("move") or "none") == "none":
            kind = "push-in" if sc.get("type") in ("title", "kinetic_title", "quote", "stat", "cta", "logo", "counter", "testimonial") else "drift"
            out.append(_finding("static_scene", "warn", i, f"صحنهٔ {fa(n)} {fa(round(eff, 1))} ثانیه است و هیچ حرکتی ندارد؛ یک حرکتِ آرامِ دوربین ({motionlib.CAMERA_MOVES.get(kind, kind)}) اضافه می‌شود.",
                                [{"op": "set", "path": f"scenes/{i}/camera", "value": {"move": kind, "amount": 0.35}}], duration=eff))
        words = _scene_words(sc)
        sim = simultaneous(sc)
        if words > motionlib.MAX_WORDS_PER_SCENE or sim > motionlib.MAX_SIMULTANEOUS:
            splittable = _can_split(sc)
            ops = [{"op": "split_scene", "index": i}] if splittable else (
                [{"op": "remove", "path": f"scenes/{i}/overlays"}] if sc.get("overlays") else [])
            out.append(_finding("crowded", "warn", i, f"صحنهٔ {fa(n)} شلوغ است ({fa(words)} کلمه، حدودِ {fa(sim)} عنصرِ هم‌زمان)" + ("؛ به دو صحنه تقسیم می‌شود." if splittable else "."), ops, words=words, simultaneous=sim))
        if len(sc.get("overlays") or []) >= 3 and not (words > motionlib.MAX_WORDS_PER_SCENE):
            out.append(_finding("overlays_busy", "info", i, f"صحنهٔ {fa(n)} {fa(len(sc['overlays']))} رویهٔ هم‌زمان دارد؛ ساده‌ترش کنید."))
        brand_cols = (spec.get("brand") or {}).get("colors") or []
        acc = parse_color(((sc.get("tokens") or {}).get("accent")) or (brand_cols[0] if brand_cols else "") or pal.get("accent") or "")
        bg = parse_color(((sc.get("tokens") or {}).get("bg")) or pal.get("bg") or "")
        if acc and bg and contrast(acc, bg) < 1.9:
            hx, ratio = best_text_color(bg, ("#ffffff", "#111111", "#ffbe0b", "#126f85", "#e63946"))
            out.append(_finding("accent_contrast", "warn", i, f"صحنهٔ {fa(n)}: رنگِ تأکید روی زمینه کم‌رنگ است (کنتراست {fa(round(contrast(acc, bg), 1))})؛ رنگِ خواناتر گذاشته می‌شود.",
                                [{"op": "set", "path": f"scenes/{i}/tokens/accent", "value": hx}], ratio=round(contrast(acc, bg), 2)))
    if not spec.get("platform") and spec.get("aspect") in ("9:16", "4:5"):
        pid = motionlib.DEFAULT_PLATFORM.get(spec["aspect"], "")
        out.append(_finding("platform_missing", "info", None, f"پلتفرمِ انتشار انتخاب نشده؛ متن‌ها با ناحیهٔ امنِ {motionlib.PLATFORMS[pid]['name']} کنترل نمی‌شوند.",
                            [{"op": "set", "path": "platform", "value": pid}]) | {"auto": False})
    return out


# ───────────────────────────────────────────── انتخابِ فریم‌های سنجش

def key_frames(spec: dict, per_scene: int = 2) -> list:
    """برای هر صحنه دو فریمِ خارج از گذار: «enter» (ورود نشسته) و «late» (پایانِ صحنه، پیش از خروج)."""
    t = timeline.compute(spec)
    fps, scenes, out = t["fps"], spec.get("scenes") or [], []
    n = len(scenes)
    for i in range(n):
        start, length = t["starts"][i], t["frames"][i]
        tin = t["tfs"][i - 1] if i > 0 else 0
        tout = t["tfs"][i] if i < n - 1 else 0
        a, b = tin + 1, length - tout - 2
        if b <= a:
            a, b = 1, max(2, length - 2)
        enter_f = a + min(int((b - a) * 0.5), int(fps * (1.3 + 0.12 * min(8, _items_count(scenes[i])))))
        late_f = a + int((b - a) * 0.92)
        late_f = max(late_f, enter_f + 1)
        out.append({"scene": i, "kind": "enter", "frame": start + enter_f})
        if per_scene > 1:
            out.append({"scene": i, "kind": "late", "frame": start + min(late_f, length - 2)})
    total = t["total"]
    for k in out:
        k["frame"] = max(0, min(total - 1, k["frame"]))
    return out


# ───────────────────────────────────────────── لایهٔ ۲: از فریم‌های واقعی

def _rect(b: dict):
    return (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])


def _inter(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _ancestors(box: dict, by_id: dict) -> set:
    out, cur, guard = set(), box.get("parent", -1), 0
    while cur is not None and cur >= 0 and guard < 50:
        out.add(cur)
        cur = (by_id.get(cur) or {}).get("parent", -1)
        guard += 1
    return out


def sample_background(image, box: dict, scale: float, text_rgb) -> tuple | None:
    """رنگِ غالبِ پشتِ متن: پیکسل‌های داخلِ کادرِ متن که از رنگِ خودِ متن دورند، در سطل‌های ۱۶تایی؛ پرتکرارترین سطل."""
    try:
        W, H = image.size
        x0, y0 = max(0, int((box["x"] + box["w"] * 0.06) * scale)), max(0, int((box["y"] + box["h"] * 0.12) * scale))
        x1, y1 = min(W, int((box["x"] + box["w"] * 0.94) * scale)), min(H, int((box["y"] + box["h"] * 0.88) * scale))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        crop = image.crop((x0, y0, x1, y1)).convert("RGB")
        crop.thumbnail((64, 64))
        px = list(crop.getdata())
    except Exception:  # noqa: BLE001
        return None
    far = [p for p in px if (p[0] - text_rgb[0]) ** 2 + (p[1] - text_rgb[1]) ** 2 + (p[2] - text_rgb[2]) ** 2 > 60 ** 2]
    if len(far) < max(6, len(px) * 0.06):
        # almost every pixel is near the text colour: the text hides in a uniform background (contrast ~1) - or its glyphs fill the whole box (never uniform)
        near: dict = {}
        for p in px:
            near.setdefault((p[0] // 16, p[1] // 16, p[2] // 16), []).append(p)
        top = max(near.values(), key=len)
        if len(top) >= len(px) * 0.85:
            return tuple(sum(c[k] for c in top) // len(top) for k in range(3))
        return None
    buckets: dict = {}
    for p in far:
        buckets.setdefault((p[0] // 16, p[1] // 16, p[2] // 16), []).append(p)
    best = max(buckets.values(), key=len)
    return tuple(sum(c[k] for c in best) // len(best) for k in range(3))


def geometry_findings(spec: dict, shots: list) -> list:
    out: list = []
    seen: set = set()
    for shot in shots:
        W, H = shot["W"], shot["H"]
        boxes = shot.get("boxes") or []
        by_id = {b["id"]: b for b in boxes}
        safe = shot.get("safe") or {}
        sc_i = shot["scene"]
        n = sc_i + 1
        texts = [b for b in boxes if b.get("kind") == "text" and b.get("scene") == sc_i and b.get("opacity", 1) >= 0.5 and b["w"] > 3 and b["h"] > 3]
        scene = spec["scenes"][sc_i] if sc_i < len(spec["scenes"]) else {}
        cur_fs = float(((scene.get("tokens") or {}).get("font_scale")) or 1.0)

        def add(f):
            key = (f["code"], f["scene"], f.get("key", ""))
            if key not in seen:
                seen.add(key)
                f["shot"] = {"kind": shot["kind"], "frame": shot["frame"]}
                out.append(f)

        shrink = {"op": "set", "path": f"scenes/{sc_i}/tokens/font_scale", "value": round(max(0.6, cur_fs * 0.85), 2)}
        can_shrink = cur_fs > 0.62
        for b in texts:
            label = (b.get("text") or "")[:24]
            off = b["x"] < -4 or b["y"] < -4 or b["x"] + b["w"] > W + 4 or b["y"] + b["h"] > H + 4
            if b.get("overflow") or b.get("clipped") or off:
                ops = [shrink] if can_shrink else ([{"op": "split_scene", "index": sc_i}] if _can_split(scene) else [])
                add(_finding("overflow", "error", sc_i, f"صحنهٔ {fa(n)}: متنِ «{label}» از قاب یا کادرش بیرون زده است.", ops, key=label, box=_slim(b)))
            size_frac = b.get("size", 0) / H if b.get("size") else 1
            if b.get("size") and size_frac < motionlib.MIN_FONT_FRAC and b.get("role") != "caption":
                # the auto-fit already shrank this text to make it fit: only fewer items per scene helps, and only when it is really too small to read
                sev = "error" if size_frac < motionlib.MIN_FONT_ERROR else "warn" if size_frac < motionlib.MIN_FONT_WARN else "info"
                ops = [{"op": "split_scene", "index": sc_i}] if (sev == "error" and _can_split(scene) and _items_count(scene) >= 3) else (
                    [{"op": "set", "path": f"scenes/{sc_i}/tokens/font_scale", "value": round(min(1.6, cur_fs * 1.15), 2)}] if (sev == "error" and cur_fs < 1.3) else [])
                add(_finding("small_text", sev, sc_i, f"صحنهٔ {fa(n)}: متنِ «{label}» فقط {fa(round(size_frac * 100, 1))}٪ ارتفاعِ قاب است (حداقل {fa(round(motionlib.MIN_FONT_FRAC * 100, 1))}٪).", ops, key=label, box=_slim(b)))
            if any(safe.get(k, 0) > 0 for k in ("top", "right", "bottom", "left")) and b.get("overlay") != "ticker":
                tol = 6
                bad = []
                if safe.get("left", 0) and b["x"] < safe["left"] - tol:
                    bad.append("چپ")
                if safe.get("right", 0) and b["x"] + b["w"] > W - safe["right"] + tol:
                    bad.append("راست")
                if safe.get("top", 0) and b["y"] < safe["top"] - tol:
                    bad.append("بالا")
                if safe.get("bottom", 0) and b["y"] + b["h"] > H - safe["bottom"] + tol:
                    bad.append("پایین")
                if bad:
                    ov_i = _overlay_index(scene, b.get("overlay"))
                    if ov_i is not None:
                        dy = -0.15 if "پایین" in bad else 0.15 if "بالا" in bad else 0.0
                        ops = [{"op": "set", "path": f"scenes/{sc_i}/overlays/{ov_i}/dy", "value": max(-0.5, min(0.5, float((scene["overlays"][ov_i]).get("dy") or 0) + dy))}] if dy else \
                              [{"op": "set", "path": f"scenes/{sc_i}/overlays/{ov_i}/anchor", "value": "center"}]
                    else:
                        usable = W - max(safe.get("left", 0), 0) - max(safe.get("right", 0), 0)
                        ops = [shrink] if (can_shrink and b["w"] > usable * 0.98) else []        # only a text wider than the safe area gets smaller
                    add(_finding("safe_zone", "warn", sc_i, f"صحنهٔ {fa(n)}: متنِ «{label}» در ناحیهٔ {'، '.join(bad)} از ناحیهٔ امنِ پلتفرم بیرون است.", ops, key=label + "".join(bad), box=_slim(b)))
        # هم‌پوشانی
        for ai in range(len(texts)):
            for bi in range(ai + 1, len(texts)):
                a, b = texts[ai], texts[bi]
                if a["id"] in _ancestors(b, by_id) or b["id"] in _ancestors(a, by_id):
                    continue
                if a.get("excl") and a.get("excl") == b.get("excl"):
                    continue                                    # stacked on purpose (before/after wipe)
                inter = _inter(_rect(a), _rect(b))
                small = min(a["w"] * a["h"], b["w"] * b["h"])
                if small > 0 and inter / small >= 0.18:
                    ov = a.get("overlay") or b.get("overlay")
                    ov_i = _overlay_index(scene, ov)
                    if ov_i is not None:
                        cur_anchor = (scene["overlays"][ov_i].get("anchor") or "lower")
                        alt = {"lower": "top", "bottom": "top", "top": "bottom", "upper": "bottom", "center": "bottom"}.get(cur_anchor, "bottom")
                        ops = [{"op": "set", "path": f"scenes/{sc_i}/overlays/{ov_i}/anchor", "value": alt}]
                    else:
                        ops = [shrink] if can_shrink else ([{"op": "split_scene", "index": sc_i}] if _can_split(scene) else [])
                    add(_finding("overlap", "error" if inter / small >= 0.4 else "warn", sc_i, f"صحنهٔ {fa(n)}: «{(a.get('text') or '')[:18]}» و «{(b.get('text') or '')[:18]}» روی هم افتاده‌اند.", ops,
                                 key=f"{a['id']}-{b['id']}", box=_slim(a)))
        # کنتراست از پیکسل
        img = shot.get("_image")
        if img is not None:
            scale = shot.get("scale", 1.0)
            accents = [parse_color(c) for c in _accent_colours(spec, scene)]

            def _is_accent(col) -> bool:
                return any(c and sum((c[k] - col[k]) ** 2 for k in range(3)) < 28 ** 2 for c in accents)

            meas = []                                                       # (box, colour, dominant colour behind it, needed ratio)
            for b in texts:
                col = parse_color(b.get("color", ""))
                if not col or col[3] < 0.5 or b.get("opacity", 1) < 0.85 or b["w"] < 24 or b["h"] < 14:
                    continue
                bg = sample_background(img, b, scale, col[:3])
                if bg is None:
                    continue
                big = (b.get("size", 0) / H) >= 0.03
                meas.append((b, col, bg, motionlib.MIN_CONTRAST if big else motionlib.MIN_CONTRAST_SMALL * 0.8))
            plain_peers = [m for m in meas if not _is_accent(m[1])]
            calm_on = bool((scene.get("tokens") or {}).get("calm"))
            for b, col, bg, need in meas:
                ratio = contrast(col[:3], bg)
                if ratio >= need:
                    continue
                is_accent = _is_accent(col)
                if is_accent:           # keep the hue of the brand: the same colour made much darker / lighter, else white / near-black
                    hx, best = best_text_color(bg, ("#ffffff", "#111111"))
                    tries = [hexof(_mix(col[:3], (0, 0, 0), 0.55)), hexof(_mix(col[:3], (255, 255, 255), 0.6)), hx]
                    good = [c for c in tries if contrast(parse_color(c), bg) >= need]
                    hx = good[0] if good else hx
                    best = contrast(parse_color(hx), bg)
                    ops = [{"op": "set", "path": f"scenes/{sc_i}/tokens/accent", "value": hx}] if best > ratio + 0.6 else []
                else:
                    # ordinary text shares ONE colour per scene: judge the candidates against EVERY text of the scene (a colour that only suits the
                    # worst-off label would turn the labels on a light background white). Moving decoration (blobs, stripes) behind the text is
                    # what makes the backdrop change from word to word: when no single colour works, the decoration is calmed for this scene.
                    def floor(rgb, peers=plain_peers) -> float:
                        return min(contrast(rgb, m[2]) / m[3] for m in peers)

                    cands = {"#ffffff": (255, 255, 255), "#111111": (17, 17, 17)}
                    hx = max(cands, key=lambda c: floor(cands[c]))
                    now = floor(col[:3])
                    if floor(cands[hx]) >= 1.0 and floor(cands[hx]) > now + 0.05:
                        ops = [{"op": "set", "path": f"scenes/{sc_i}/tokens/text", "value": hx}]
                    elif not calm_on:
                        ops = [{"op": "set", "path": f"scenes/{sc_i}/tokens/calm", "value": True}]
                    else:
                        ops = [{"op": "set", "path": f"scenes/{sc_i}/tokens/text", "value": hx}] if floor(cands[hx]) > now + 0.05 else []
                add(_finding("low_contrast", "error" if ratio < 2.0 else "warn", sc_i,
                             f"صحنهٔ {fa(n)}: متنِ «{(b.get('text') or '')[:20]}» کنتراستِ {fa(round(ratio, 1))} دارد (حداقل {fa(round(need, 1))}).", ops,
                             key=(b.get("text") or "")[:20], ratio=round(ratio, 2), box=_slim(b)))
    return out


def _accent_colours(spec: dict, scene: dict) -> list:
    st = catalog.get(spec.get("style", "")) or {}
    pal = st.get("palette") or {}
    out = [pal.get(k) for k in ("accent", "accent2", "accent3")]
    out += list((spec.get("brand") or {}).get("colors") or [])
    out.append((scene.get("tokens") or {}).get("accent"))
    return [c for c in out if c]


def _overlay_index(scene: dict, kind) -> int | None:
    if not kind:
        return None
    for i, ov in enumerate(scene.get("overlays") or []):
        if ov.get("type") == kind:
            return i
    return None


def _slim(b: dict) -> dict:
    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in b.items() if k in ("x", "y", "w", "h", "size", "role", "text", "overlay")}


# ───────────────────────────────────────────── حلقهٔ بسنج ⇒ اصلاح کن ⇒ دوباره بسنج

GROUP = {"duration": "duration", "font_scale": "font", "tokens/text": "color", "tokens/accent": "color", "tokens/calm": "color", "overlays": "overlay", "split_scene": "struct", "remove_scene": "struct"}


def _group(op: dict) -> str:
    path = str(op.get("path", ""))
    if op.get("op") in ("split_scene", "remove_scene"):
        return "struct"
    for k, g in GROUP.items():
        if k in path:
            return g
    return path or "other"


def _slim_finding(f: dict) -> dict:
    return {k: v for k, v in f.items() if k not in ("_image",)}


def _order(findings: list) -> list:
    return sorted(findings, key=lambda f: (PRIORITY.index(f["code"]) if f["code"] in PRIORITY else 99, SEVERITY_ORDER.get(f["severity"], 3)))


def apply_fixes(spec: dict, findings: list, *, max_total: float = specs.MAX_TOTAL_S_NODE) -> tuple:
    """⇒ (spec تازه, applied[], unresolved[]). از هر (صحنه، گروهِ تغییر) فقط یک اصلاح در هر دور؛ ساختاری‌ها از بالا به پایین تا شماره‌ها نپرند."""
    cur = spec
    applied, unresolved = [], []
    touched: set = set()
    work = [f for f in _order(findings) if f["severity"] in ("error", "warn") and f.get("ops") and f.get("auto", True)]
    struct = [f for f in work if any(_group(o) == "struct" for o in f["ops"])]
    plain = [f for f in work if f not in struct]
    for f in plain:
        groups = {(f["scene"], _group(o)) for o in f["ops"]}
        if groups & touched or (f["scene"], "struct") in touched:
            continue
        try:
            cur = patch_mod.apply_patch(cur, f["ops"], max_total=max_total)
        except patch_mod.PatchError as exc:
            unresolved.append({**_slim_finding(f), "why": str(exc)})
            continue
        touched |= groups
        applied.append({"code": f["code"], "scene": f["scene"], "message": f["message"], "ops": f["ops"]})
    for f in sorted(struct, key=lambda x: -(x["scene"] if x["scene"] is not None else 0)):
        if (f["scene"], "struct") in touched:
            continue
        try:
            cur = patch_mod.apply_patch(cur, f["ops"], max_total=max_total)
        except patch_mod.PatchError as exc:
            unresolved.append({**_slim_finding(f), "why": str(exc)})
            continue
        touched.add((f["scene"], "struct"))
        applied.append({"code": f["code"], "scene": f["scene"], "message": f["message"], "ops": f["ops"]})
    return cur, applied, unresolved


def run_loop(spec: dict, *, measure=None, rounds: int = 3, max_total: float = specs.MAX_TOTAL_S_NODE, on_round=None) -> dict:
    """measure(spec) ⇒ shots (یا None). ⇒ {spec, rounds[], fixed, remaining[], geometry: bool, geometry_error?}"""
    cur = spec
    report: dict = {"rounds": [], "fixed": 0, "remaining": [], "geometry": measure is not None}
    last: list = []
    for n in range(1, rounds + 1):
        shots = None
        geo: list = []
        if measure is not None:
            try:
                shots = measure(cur)
                geo = geometry_findings(cur, shots)
            except Exception as exc:  # noqa: BLE001 — مرورگر/رندر در دسترس نبود: بقیهٔ قاعده‌ها ادامه می‌دهند
                report["geometry_error"] = str(exc)[:300]
                report["geometry"] = False
                measure = None
        findings = _order(static_findings(cur) + geo)
        rec = {"n": n, "findings": [_slim_finding(f) for f in findings], "applied": [], "shots": [_shot_meta(s) for s in (shots or [])]}
        last = findings
        fixable = [f for f in findings if f["severity"] in ("error", "warn") and f.get("ops") and f.get("auto", True)]
        if not fixable:
            report["rounds"].append(rec)
            if on_round:
                on_round(rec)
            break
        new, applied, unresolved = apply_fixes(cur, findings, max_total=max_total)
        rec["applied"], rec["unresolved"] = applied, unresolved
        report["rounds"].append(rec)
        if on_round:
            on_round(rec)
        if not applied:
            break
        report["fixed"] += len(applied)
        cur = new
    if report["rounds"]:
        # آخرین دور اصلاح اعمال شد ولی دوباره سنجیده نشد ⇒ یک سنجشِ نهایی
        if report["rounds"][-1].get("applied"):
            final = static_findings(cur)
            if measure is not None:
                try:
                    final += geometry_findings(cur, measure(cur))
                except Exception as exc:  # noqa: BLE001
                    report["geometry_error"] = str(exc)[:300]
            last = _order(final)
            report["final_check"] = [_slim_finding(f) for f in last]
    report["remaining"] = [_slim_finding(f) for f in last if f["severity"] in ("error", "warn")]
    report["info"] = [_slim_finding(f) for f in last if f["severity"] == "info"]
    report["spec"] = cur
    report["ok"] = not report["remaining"]
    return report


def _shot_meta(s: dict) -> dict:
    return {k: s.get(k) for k in ("scene", "kind", "frame", "image_rel", "W", "H") if k in s}


def summary_fa(report: dict) -> str:
    fixed, rem = report.get("fixed", 0), len(report.get("remaining") or [])
    geo = "" if report.get("geometry") else " (بررسیِ هندسیِ کادر انجام نشد: ابزارِ رندر در دسترس نبود)"
    if not fixed and not rem:
        return "کنترلِ کیفیت: مشکلی پیدا نشد." + geo
    return f"کنترلِ کیفیت: {fa(fixed)} مشکل خودکار اصلاح شد" + (f"؛ {fa(rem)} مورد هنوز مانده" if rem else "؛ همه رفع شد") + "." + geo


def open_image(path):
    from PIL import Image

    im = Image.open(Path(path))
    im.load()
    return im
