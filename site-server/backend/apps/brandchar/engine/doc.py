"""سندِ شخصیتِ برند: همهٔ ظاهرِ شخصیت یک دیکشنریِ ساده است (داده، نه تصویر).

یک سند چهار سبکِ کشیدن را می‌راند: ``flat`` (برداریِ تخت)، ``chibi`` (گردِ کوچک و سر بزرگ)، ``sticker`` (خطِ دورِ پررنگ + حاشیهٔ سفیدِ بریده)
و ``stick`` (آدمک‌چوبیِ ماسکوت؛ از ``apps.mascot.engine``). کلیدهای ماسکوت (limb_colour، head_style، hat ...) همان نام و گزینه‌ها را دارند تا سبکِ «آدمک‌چوبی»
مستقیم از همین سند کشیده شود (``to_mascot_spec``)؛ بقیه کلیدها (outfit، bottoms، skin ...) فقط برای سبک‌های برداری‌اند.

«لایه‌های دستی» (``layers``): شکل و مسیرِ برداریِ ویرایشگر، چسبیده به یک جزء (سر، بدن، دست‌راست، یا «جهان») تا با ژست‌ها حرکت کنند.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ENGINE_VERSION = 1             # با هر تغییرِ ظاهریِ موتور بالا برود تا کَشِ قدیمی نخوانده شود

STYLES = ("flat", "chibi", "sticker", "stick")
STYLE_LABELS_FA = {"flat": "برداریِ تخت", "chibi": "گردِ کوچک (چیبی)", "sticker": "استیکرِ خط‌دور", "stick": "آدمک‌چوبی"}
STYLE_HINTS_FA = {
    "flat": "رنگ‌های تخت، بدونِ خطِ دور؛ مدرن و تمیز (مثلِ ایلاستریشنِ اپ‌ها)",
    "chibi": "سرِ بزرگ، بدنِ کوچک، چشمِ درشت و گونهٔ گلی؛ دوست‌داشتنی",
    "sticker": "خطِ دورِ پررنگ و حاشیهٔ سفیدِ بریده‌شده مثلِ استیکرِ واقعی",
    "stick": "همان آدمک‌چوبیِ ماسکوتِ برند (کشیده‌شده با کد)",
}

BODIES = ("slim", "regular", "athletic", "round")
HEAD_STYLES = ("round", "tall", "wide", "square")
EYE_STYLES = ("dots", "round", "sleepy", "big", "happy", "wink")
BROWS = ("normal", "thick", "thin", "none")
NOSES = ("none", "dot", "button")
HAIRS = ("none", "tuft", "spikes", "bob", "ponytail", "buzz", "short", "bun", "curly", "long")
HATS = ("none", "cap", "beanie", "headband", "tophat", "hood", "chef")
NECKS = ("none", "scarf", "tie", "bowtie")
EXTRAS = ("none", "glasses", "backpack", "mask", "apron")
OUTFITS = ("tshirt", "tank", "hoodie", "jersey", "suit", "track")
BOTTOMS = ("pants", "shorts", "joggers", "skirt")
SHOES = ("sneakers", "boots", "bare")
PROPS = ("none", "torch", "phone", "key", "bat", "sign", "map", "dumbbell", "barbell", "clipboard", "bag", "pan", "box", "tablet", "megaphone")
LOGOS = ("none", "chest")
EXPRESSIONS = ("neutral", "happy", "laugh", "sad", "angry", "scared", "surprised", "smirk")
ANCHORS = ("world", "head", "body", "hand")              # لایه به کدام جزء می‌چسبد
LAYER_SHAPES = ("rect", "ellipse", "line", "path")

CHOICES: dict[str, tuple] = {
    "style": STYLES, "body": BODIES, "head_style": HEAD_STYLES, "eye_style": EYE_STYLES, "brows": BROWS, "nose": NOSES, "hair": HAIRS, "hat": HATS, "neck": NECKS,
    "extra": EXTRAS, "outfit": OUTFITS, "bottoms": BOTTOMS, "shoes_type": SHOES, "prop": PROPS, "logo": LOGOS,
}
BOOLS = ("blush", "freckles", "beard")
COLOUR_KEYS = ("skin", "hair_colour", "top", "top2", "bottom", "shoes", "hat_colour", "neck_colour", "extra_colour", "prop_colour", "outline", "limb_colour", "head_fill")

CHOICE_LABELS_FA: dict[str, dict[str, str]] = {
    "style": dict(STYLE_LABELS_FA),
    "body": {"slim": "باریک", "regular": "معمولی", "athletic": "ورزشکار", "round": "گرد"},
    "head_style": {"round": "گرد", "tall": "کشیده", "wide": "پهن", "square": "گوشه‌گرد"},
    "eye_style": {"dots": "نقطه‌ای", "round": "گرد", "sleepy": "خواب‌آلود", "big": "درشت (براق)", "happy": "خندان", "wink": "چشمک"},
    "brows": {"normal": "معمولی", "thick": "پرپشت", "thin": "نازک", "none": "بدونِ ابرو"},
    "nose": {"none": "بدونِ بینی", "dot": "نقطه", "button": "گرد"},
    "hair": {"none": "بدونِ مو", "tuft": "تکه‌مو", "spikes": "موی سیخ‌سیخی", "bob": "موی کوتاهِ گرد", "ponytail": "موی بسته", "buzz": "مویِ تراشیده",
             "short": "موی کوتاه", "bun": "گیسِ جمع‌شده", "curly": "موی فر", "long": "موی بلند"},
    "hat": {"none": "بدونِ کلاه", "cap": "کلاهِ لبه‌دار", "beanie": "کلاهِ بافتنی", "headband": "هدبند", "tophat": "کلاهِ بلند", "hood": "کلاهِ کاپشن", "chef": "کلاهِ آشپز"},
    "neck": {"none": "بدونِ گردن‌آویز", "scarf": "شال", "tie": "کراوات", "bowtie": "پاپیون"},
    "extra": {"none": "بدونِ وسیلهٔ اضافه", "glasses": "عینک", "backpack": "کوله‌پشتی", "mask": "ماسک", "apron": "پیش‌بند"},
    "outfit": {"tshirt": "تی‌شرت", "tank": "رکابی", "hoodie": "هودی", "jersey": "لباسِ ورزشی", "suit": "کت و پیراهن", "track": "گرمکن"},
    "bottoms": {"pants": "شلوار", "shorts": "شلوارک", "joggers": "گرمکنِ مچ‌دار", "skirt": "دامن"},
    "shoes_type": {"sneakers": "کفشِ ورزشی", "boots": "بوت", "bare": "پابرهنه"},
    "prop": {"none": "بدونِ وسیله", "torch": "مشعل", "phone": "گوشی", "key": "کلید", "bat": "چماق", "sign": "تابلو", "map": "نقشه", "dumbbell": "دمبل",
             "barbell": "هالتر", "clipboard": "برگهٔ برنامه", "bag": "کیسهٔ خرید", "pan": "تابه", "box": "بسته", "tablet": "تبلت", "megaphone": "بلندگو"},
    "logo": {"none": "بدونِ لوگو", "chest": "لوگوی فروشگاه روی سینه"},
}
BOOL_LABELS_FA = {"blush": "گونهٔ گلی", "freckles": "کک‌ومک", "beard": "ته‌ریش"}
SKIN_PRESETS = ("#f6d7bd", "#f1c9a5", "#e0ac84", "#c68b62", "#9c6644", "#6f4630")
SKIN_PRESETS_FA = ("روشن", "گندمی روشن", "گندمی", "برنزه", "قهوه‌ای", "تیره")

DEFAULTS: dict[str, Any] = {
    "name": "", "style": "flat", "body": "regular", "head_style": "round", "eye_style": "round", "brows": "normal", "nose": "dot", "hair": "short", "hat": "none",
    "neck": "none", "extra": "none", "outfit": "tshirt", "bottoms": "pants", "shoes_type": "sneakers", "prop": "none", "logo": "none",
    "blush": False, "freckles": False, "beard": False,
    "skin": "#f1c9a5", "hair_colour": "#2b2320", "top": "#2f7fd1", "top2": "#ffffff", "bottom": "#1f2430", "shoes": "#f4f1ea", "hat_colour": "#d94a3d", "neck_colour": "#d94a3d",
    "extra_colour": "#2f7fd1", "prop_colour": "#e8a22b", "outline": "#1f2430", "limb_colour": "#1f2430", "head_fill": "#ffffff", "line_width": 17,
    "layers": [],
}
MAX_LAYERS = 60
MAX_POINTS = 120

#: هر نقش در مختصاتِ سند: (گزینه‌های اختصاصیِ ظاهر که ``brand.spec_from_brand`` نمی‌داند)
ROLE_LOOK: dict[str, dict] = {
    "coach": {"outfit": "jersey", "bottoms": "joggers", "hair": "short", "shoes_type": "sneakers", "body": "athletic", "blush": False},
    "shopkeeper": {"outfit": "tshirt", "bottoms": "pants", "hair": "short", "shoes_type": "sneakers", "body": "regular"},
    "cook": {"outfit": "tshirt", "bottoms": "pants", "hair": "none", "shoes_type": "boots", "body": "round"},
    "courier": {"outfit": "track", "bottoms": "joggers", "hair": "short", "shoes_type": "sneakers", "body": "slim"},
    "advisor": {"outfit": "suit", "bottoms": "pants", "hair": "bob", "shoes_type": "boots", "body": "slim"},
}

HAIR_TO_STICK = {"none": "none", "tuft": "tuft", "spikes": "spikes", "bob": "bob", "ponytail": "ponytail", "buzz": "tuft", "short": "tuft", "bun": "ponytail", "curly": "tuft", "long": "bob"}
EYE_TO_STICK = {"dots": "dots", "round": "round", "sleepy": "sleepy", "big": "round", "happy": "round", "wink": "dots"}
HEAD_TO_STICK = {"round": "round", "tall": "tall", "wide": "wide", "square": "wide"}

_HEX = re.compile(r"^#[0-9a-f]{6}$")


def hex_ok(v: Any, default: str) -> str:
    s = str(v or "").strip().lower()
    if len(s) == 4 and s[0] == "#":
        s = "#" + "".join(c * 2 for c in s[1:])
    return s if _HEX.match(s) else default


def _num(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, f))


def clean_layer(raw: Any, idx: int = 0) -> dict | None:
    """یک لایهٔ دستیِ برداری را امن می‌کند؛ نامعتبر ⇒ None."""
    if not isinstance(raw, dict):
        return None
    shape = raw.get("shape")
    if shape not in LAYER_SHAPES:
        return None
    box_in = raw.get("box") if isinstance(raw.get("box"), dict) else {}
    box = {"cx": _num(box_in.get("cx"), -900, 1500, 0.0), "cy": _num(box_in.get("cy"), -900, 1800, 0.0), "w": _num(box_in.get("w"), 1, 1500, 60.0),
           "h": _num(box_in.get("h"), 1, 1800, 60.0), "rot": _num(box_in.get("rot"), -360, 360, 0.0)}
    out = {"id": re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("id") or f"l{idx}"))[:24] or f"l{idx}", "name": str(raw.get("name") or "")[:40], "shape": shape,
           "anchor": raw.get("anchor") if raw.get("anchor") in ANCHORS else "world", "box": box, "fill": hex_ok(raw.get("fill"), "") or None,
           "stroke": hex_ok(raw.get("stroke"), "") or None, "sw": _num(raw.get("sw"), 0, 60, 0.0), "opacity": _num(raw.get("opacity"), 0, 1, 1.0),
           "above": bool(raw.get("above", True)), "hidden": bool(raw.get("hidden")), "locked": bool(raw.get("locked")), "radius": _num(raw.get("radius"), 0, 400, 0.0),
           "flip_x": bool(raw.get("flip_x")), "link": re.sub(r"[^a-zA-Z0-9_-]", "", str(raw.get("link") or ""))[:24], "shape_id": re.sub(r"[^a-z0-9_-]", "", str(raw.get("shape_id") or ""))[:24]}
    if out["fill"] is None and out["stroke"] is None:
        out["fill"] = "#cccccc"
    if shape == "path":
        path = raw.get("path") if isinstance(raw.get("path"), dict) else {}
        pts = []
        for p in (path.get("pts") or [])[:MAX_POINTS]:
            if not isinstance(p, dict):
                continue

            def h(v):
                return [round(_num(v[0], -4, 4, 0.0), 4), round(_num(v[1], -4, 4, 0.0), 4)] if isinstance(v, (list, tuple)) and len(v) == 2 else None

            pts.append({"x": round(_num(p.get("x"), -3, 4, 0.5), 4), "y": round(_num(p.get("y"), -3, 4, 0.5), 4), "hi": h(p.get("hi")), "ho": h(p.get("ho"))})
        if len(pts) < 2:
            return None
        out["path"] = {"closed": bool(path.get("closed")) and len(pts) > 2, "pts": pts}
    return out


def normalize(data: dict | None, *, name: str = "") -> dict:
    """سندِ کامل و امن: کلیدهای ناشناخته می‌افتند، گزینه‌ها محدود، رنگ‌ها اعتبارسنجی و لایه‌ها پاک‌سازی می‌شوند."""
    d = dict(data or {})
    out = dict(DEFAULTS)
    out["name"] = str(d.get("name") or name or "")[:80]
    for k, allowed in CHOICES.items():
        if d.get(k) in allowed:
            out[k] = d[k]
    for k in BOOLS:
        if k in d:
            out[k] = bool(d[k])
    for k in COLOUR_KEYS:
        if k in d:
            out[k] = hex_ok(d[k], out[k])
    out["line_width"] = int(_num(d.get("line_width"), 10, 26, out["line_width"]))
    layers = []
    for i, raw in enumerate((d.get("layers") or [])[:MAX_LAYERS]):
        lay = clean_layer(raw, i)
        if lay is not None:
            layers.append(lay)
    seen: set[str] = set()
    for lay in layers:                               # شناسه‌ها یکتا
        while lay["id"] in seen:
            lay["id"] = lay["id"][:20] + "x"
        seen.add(lay["id"])
    out["layers"] = layers
    return out


def doc_hash(doc: dict) -> str:
    s = normalize(doc)
    s.pop("name", None)
    return hashlib.sha256((json.dumps(s, sort_keys=True, ensure_ascii=False) + f"|e{ENGINE_VERSION}").encode()).hexdigest()[:14]


def to_mascot_spec(doc: dict) -> dict:
    """سند ⇒ spec ِ ماسکوت (آدمک‌چوبی). رنگِ دست و پا = ``limb_colour``؛ رنگِ سر = ``head_fill``."""
    s = normalize(doc)
    return {"name": s["name"], "limb_colour": s["limb_colour"], "head_fill": s["head_fill"], "outline": s["outline"], "line_width": s["line_width"],
            "head_style": HEAD_TO_STICK[s["head_style"]], "eye_style": EYE_TO_STICK[s["eye_style"]], "hat": s["hat"], "hat_colour": s["hat_colour"],
            "hair": HAIR_TO_STICK[s["hair"]], "hair_colour": s["hair_colour"], "neck": s["neck"], "neck_colour": s["neck_colour"], "extra": s["extra"], "extra_colour": s["extra_colour"],
            "prop": s["prop"], "prop_colour": s["prop_colour"], "logo": s["logo"]}


def from_mascot_spec(spec: dict, *, role: str = "coach", name: str = "") -> dict:
    """ماسکوتِ موجود ⇒ سندِ شخصیت (ظاهرِ برداری از روی رنگ‌های همان ماسکوت ساخته می‌شود)."""
    sp = dict(spec or {})
    inv_hair = {v: k for k, v in HAIR_TO_STICK.items() if k in ("none", "tuft", "spikes", "bob", "ponytail")}
    primary = hex_ok(sp.get("hat_colour") or sp.get("neck_colour") or sp.get("prop_colour"), DEFAULTS["top"])
    d = {**ROLE_LOOK.get(role, {}), "name": name or sp.get("name", ""), "style": "stick", "limb_colour": sp.get("limb_colour"), "head_fill": sp.get("head_fill"), "outline": sp.get("outline"),
         "line_width": sp.get("line_width"), "head_style": sp.get("head_style"), "eye_style": sp.get("eye_style"), "hat": sp.get("hat"), "hat_colour": sp.get("hat_colour"),
         "hair": inv_hair.get(sp.get("hair"), "short"), "hair_colour": sp.get("hair_colour"), "neck": sp.get("neck"), "neck_colour": sp.get("neck_colour"), "extra": sp.get("extra"),
         "extra_colour": sp.get("extra_colour"), "prop": sp.get("prop"), "prop_colour": sp.get("prop_colour"), "logo": sp.get("logo"),
         "top": primary, "top2": "#ffffff", "bottom": sp.get("limb_colour"), "shoes": "#f4f1ea"}
    return normalize(d, name=name)


def palette(doc: dict, *, style: str | None = None) -> list[dict]:
    """«کلیدِ رنگ»: هر رنگی که واقعاً کشیده می‌شود ⇒ [{role, hex, name}]. برای سبکِ آدمک‌چوبی همان کلیدِ ماسکوت."""
    s = normalize(doc)
    st = style or s["style"]
    if st == "stick":
        from apps.mascot.engine import spec as MS

        return [{**r, "name_fa": MS.fa_word(r["name"])} for r in MS.palette(to_mascot_spec(s))]
    from apps.mascot.engine import spec as MS

    rows = [("skin", s["skin"]), ("top", s["top"]), ("bottom", s["bottom"])]
    if s["outfit"] in ("jersey", "track", "hoodie"):
        rows.append(("top2", s["top2"]))
    if s["shoes_type"] != "bare":
        rows.append(("shoes", s["shoes"]))
    if s["hair"] != "none":
        rows.append(("hair", s["hair_colour"]))
    if s["hat"] != "none":
        rows.append(("hat", s["hat_colour"]))
    if s["neck"] != "none":
        rows.append(("neck", s["neck_colour"]))
    if s["extra"] != "none":
        rows.append(("extra", s["extra_colour"]))
    if st in ("sticker", "chibi") or s["outline"]:
        rows.append(("outline", s["outline"]))
    return [{"role": role, "hex": hx, "name": MS.colour_name(hx), "name_fa": MS.fa_word(MS.colour_name(hx))} for role, hx in rows]


def role_look(role: str) -> dict:
    return dict(ROLE_LOOK.get(role) or ROLE_LOOK["coach"])
