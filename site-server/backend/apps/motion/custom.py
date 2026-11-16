"""«سبکِ تازه»: سبک‌هایی که کاربر خودش می‌سازد (کاتالوگِ ثابتِ catalog.py دست‌نخورده می‌ماند).

یک سبکِ شخصی همان «ردیفِ سبک» ِ catalog.py است (پالتِ ۸ نقش، قلم، پس‌زمینه، بافت، افکتِ متن، شکلِ کارت، تزئین، شخصیتِ حرکت، گذار)، با این تفاوت‌ها:
  · هر مقدار پیش از ذخیره اعتبارسنجی و به بازهٔ مجاز بریده می‌شود (فقط نوع‌ها و پارامترهایی که موتور می‌شناسد؛ رنگ فقط hex/نقش/rgba؛ قلم فقط از مجموعهٔ دارای مجوز)؛
  · «نگهبانِ کنتراست»: ترکیبِ رنگی که متن را ناخوانا کند ذخیره نمی‌شود (و پیشنهادِ اصلاحِ خودکار می‌دهد)؛
  · شناسه جداست: `u<شناسهٔ فروشگاه>-<نام>` (فقط همان فروشگاه) یا `g-<نام>` (همگانی؛ فقط مدیر)؛ `catalog.get()` آن‌ها را هم می‌شناسد، پس همهٔ بخش‌های دیگر
    (طرح، QA، رندر) بی‌تغییر کار می‌کنند؛
  · رندر سبک را «همراهِ خودِ طرح» می‌برد (`spec.style_def`)، پس بستهٔ رندرِ گره نیازی به دانستنِ سبک‌های شخصی ندارد.

این ماژول بدونِ Django هم بار می‌شود (آزمون‌ها و ابزارها)؛ دیتابیس فقط در `lookup()` لازم است.
"""
from __future__ import annotations

import colorsys
import contextlib
import copy
import hashlib
import json
import re
import threading
from collections import defaultdict
from pathlib import Path

from . import catalog, motionlib

SCHEMA = 1
ID_RE = re.compile(r"^(?:u(\d{1,9})|g)-([a-z0-9][a-z0-9-]{1,40})$")
MAX_PER_STORE = 40
MAX_GLOBAL = 60
MAX_TEX = 4
MAX_DECOR = 6
ROLES = catalog.PAL_KEYS
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
RGBA_RE = re.compile(r"^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d{1,3})\s*)?\)$")
GRADE_RE = re.compile(r"^(?:\s*(?:contrast|saturate|brightness|grayscale|sepia)\(\s*\d{1,2}(?:\.\d{1,2})?\s*\)|\s*hue-rotate\(\s*-?\d{1,3}(?:deg)?\s*\)|\s*blur\(\s*\d(?:\.\d)?(?:px)?\s*\)){1,5}\s*$")
CUSTOM_GROUP = "custom"

#: افکت‌هایی که خودشان لبه/سایه می‌کشند: رنگِ متنشان با زمینه سنجیده نمی‌شود (QA از روی پیکسل می‌سنجد)
SELF_OUTLINED_FX = {"hard", "outline-hard", "chrome", "gold", "retro", "cutout", "brick", "spray", "cel", "sticker", "felt", "clay", "extrude", "emboss",
                    "engrave", "neon", "neon-outline", "neon-tube", "glitch", "pixel", "softglow", "gradient", "long", "misregister", "marker", "phosphor", "vhs"}


class StyleError(ValueError):
    """خطای اعتبارسنجیِ سبک؛ متنِ فارسی."""


# ───────────────────────────────────────────── fonts (the licensed set that the engine ships)

def _src_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "motion" / "remotion" / "src"


_FONTS: dict | None = None


def fonts() -> dict:
    """{key: {family, license, subsets[], weights[], fa: bool}} از همان فایل‌هایی که موتور می‌خواند (fonts.generated.json + fonts.licenses.json)."""
    global _FONTS
    if _FONTS is None:
        out: dict = {}
        try:
            man = json.loads((_src_dir() / "fonts.generated.json").read_text(encoding="utf-8"))
            lic = json.loads((_src_dir() / "fonts.licenses.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            man, lic = {}, {}
        for k, v in man.items():
            files = v.get("files") or []
            subs = sorted({f.get("subset") for f in files if f.get("subset")})
            out[k] = {"family": v.get("family", k), "license": (lic.get(k) or {}).get("license", "OFL-1.1"), "subsets": subs,
                      "weights": sorted({f.get("w") for f in files if f.get("w")}), "fa": ("arabic" in subs or "all" in subs)}
        _FONTS = out
    return _FONTS


def font_options() -> list:
    return [{"key": k, "family": v["family"], "license": v["license"], "fa": v["fa"], "weights": v["weights"]} for k, v in sorted(fonts().items(), key=lambda kv: kv[1]["family"].lower())]


# ───────────────────────────────────────────── parameter schema of every kind (derived from the 96 built-in styles: always in step with the engine)

PARAM_LABELS = {
    "n": "تعداد", "op": "شفافیت", "opacity": "شفافیت", "speed": "سرعت", "size": "اندازه", "color": "رنگ", "colors": "رنگ‌ها", "base": "رنگِ پایه", "from": "از رنگِ",
    "to": "تا رنگِ", "mid": "رنگِ میانی", "angle": "زاویه", "drift": "جابه‌جاییِ آرام", "flip": "برعکس در صحنه‌های زوج", "line": "رنگِ خط", "w": "پهنا", "h": "ارتفاع",
    "veil": "پرده روی زمینه", "veilColor": "رنگِ پرده", "dot": "رنگِ نقطه", "r": "شعاع", "a": "رنگِ اول", "b": "رنگِ دوم", "c": "رنگ", "alt": "رنگِ صحنه‌های زوج",
    "glow": "رنگِ درخشش", "core": "رنگِ هسته", "depth": "عمق", "shadow": "رنگِ سایه", "stroke_c": "رنگِ دور", "sw": "ضخامتِ دور", "hi": "رنگِ هایلایت", "gap": "فاصله",
    "layers": "تعدادِ لایه", "sun": "خورشید", "sunColor": "رنگِ خورشید", "sunY": "جایگاهِ خورشید", "horizon": "خطِ افق", "parallax": "پارالاکس", "amp": "دامنه",
    "spread": "پراکندگی", "sky": "رنگ‌های آسمان", "stars": "ستاره‌ها", "moon": "ماه", "castle": "قلعه", "win": "رنگِ پنجره‌ها", "bld": "رنگِ ساختمان‌ها",
    "bars": "تعدادِ نوار", "rate": "نرخِ تغییر", "grain": "دانه", "mode": "حالت", "kinds": "شکل‌ها", "outline": "فقط خط", "spin": "چرخش", "avoid": "دوری از متن",
    "glow_": "درخشش", "arrow": "پیکان", "ratio": "نسبت", "angle_": "زاویه", "blend": "ترکیب", "rgb": "رنگ", "roll": "غلتیدن", "gap_": "فاصله", "at": "جایگاه",
    "cols": "ستون‌ها", "jitter": "بی‌نظمی", "dark": "تیرگیِ آجرها", "mortar": "رنگِ ملات", "brick": "رنگِ آجر", "fiber": "الیاف", "edge": "لبه", "plank": "پهنای تخته",
    "cell": "اندازهٔ سلول", "lead": "رنگِ سرب", "leadw": "ضخامتِ سرب", "contrast": "کنتراست", "seed": "دانه‌ی تصادف", "gx": "x", "gy": "y", "link": "فاصلهٔ پیوند",
    "blobs": "رنگِ لکه‌ها", "soft": "نرمی", "tilt": "کجی", "floor": "کف", "floorBase": "رنگِ کف", "fa": "رنگِ کفِ اول", "fb": "رنگِ کفِ دوم", "move": "حرکت",
    "stops": "رنگ‌ها", "sparkles": "جرقه‌ها", "sweep": "رنگِ جاروب", "bokehColor": "رنگِ بوکه", "light": "رنگِ نور", "thread": "نخِ اول", "thread2": "نخِ دوم",
    "thread3": "نخِ سوم", "weave": "بافت", "band": "نوار", "cloud": "رنگِ ابر", "crisp": "لبهٔ تیز", "shadow_": "سایه", "cy": "ارتفاع", "left": "رنگِ چپ", "right": "رنگِ راست",
    "top": "رنگِ بالا", "bob": "نوسان", "lineOp": "شفافیتِ خط", "major": "هر چند خط یک خطِ پررنگ", "majorLine": "رنگِ خطِ پررنگ", "maskA": "ماسک ۱", "maskB": "ماسک ۲",
    "opA": "شفافیتِ ۱", "opB": "شفافیتِ ۲", "bg2": "رنگِ دوم", "grout": "رنگِ درز", "ground": "رنگِ زمین", "blur": "تاری", "wobble": "لرزش", "c2": "رنگِ ۲", "c3": "رنگِ ۳", "c4": "رنگِ ۴",
    "sticker": "رنگِ برچسب", "pixel": "اندازهٔ پیکسل", "amp_": "دامنه", "sway": "تاب", "gold": "رنگِ طلا", "stroke": "رنگِ دور", "spikes": "تعدادِ پره",
}
# parameters that are ALWAYS a fraction 0..1 whatever the built-in values happen to be
_UNIT = {"op", "opacity", "veil", "soft", "lineOp", "maskA", "maskB", "opA", "opB", "contrast", "jitter", "dark", "edge", "fiber", "grain", "crisp"}
_ANGLE = {"angle", "skew", "tilt", "spin"}
_ENUM_NAMES = {"mode", "floor", "blend"}


def _tname(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        if v in ROLES:
            return "role"
        if v.startswith("#") or v.startswith("rgba") or v.startswith("rgb("):
            return "color"
        return "str"
    if isinstance(v, list):
        if v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            return "numlist"
        if all(isinstance(x, str) for x in v):
            return "strlist"
        return "list"
    return "obj"


def _derive(items) -> dict:
    """items: iterable of (kind, params) ⇒ {kind: {param: spec}}"""
    seen: dict = defaultdict(lambda: defaultdict(lambda: {"t": set(), "nums": [], "strs": set()}))
    for kind, params in items:
        seen[kind]
        for k, v in params.items():
            e = seen[kind][k]
            e["t"].add(_tname(v))
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                e["nums"].append(float(v))
            elif isinstance(v, str):
                e["strs"].add(v)
            elif isinstance(v, list):
                e["strs"].update(x for x in v if isinstance(x, str))
    out: dict = {}
    for kind, params in seen.items():
        ps: dict = {}
        for k, e in params.items():
            t = e["t"]
            if "obj" in t and k == "pal":
                ps[k] = {"t": "palmap", "label": "نقشِ رنگ‌ها در صحنه‌های زوج"}
                continue
            if "obj" in t or "list" in t:
                continue
            if "num" in t and len(t) == 1:
                nums = e["nums"]
                lo, hi = min(nums), max(nums)
                if k in _UNIT or (lo >= 0 and hi <= 1.0 and k not in ("n", "seed")):
                    spec = {"t": "num", "min": 0.0, "max": 1.0 if k in _UNIT or hi <= 1.0 else hi}
                    if k not in _UNIT and hi <= 1.0:
                        spec["max"] = 1.0
                elif k in _ANGLE:
                    spec = {"t": "num", "min": -360.0, "max": 360.0}
                elif k == "n":
                    spec = {"t": "num", "min": 0.0, "max": max(8.0, hi * 2), "int": True}
                elif k in ("layers", "bars", "major", "cols", "stars", "spikes", "seed"):
                    spec = {"t": "num", "min": 0.0 if k != "layers" else 1.0, "max": max(8.0, hi * 2), "int": True}
                else:
                    spec = {"t": "num", "min": 0.0 if lo >= 0 else lo * 3, "max": hi * 3 if hi > 0 else 1.0}
                spec["min"], spec["max"] = round(spec["min"], 3), round(spec["max"], 3)
                spec["default"] = sorted(nums)[len(nums) // 2]
            elif t == {"bool"}:
                spec = {"t": "bool"}
            elif t <= {"role", "color"}:
                spec = {"t": "color"}
            elif t == {"str"} and k in _ENUM_NAMES:
                spec = {"t": "enum", "choices": sorted(e["strs"] | ({"screen", "overlay", "multiply"} if k == "blend" else set()))}
            elif t == {"str"} and k == "at":
                spec = {"t": "pos"}
            elif t == {"str"} and k == "mode":
                spec = {"t": "enum", "choices": sorted(e["strs"])}
            elif t == {"strlist"}:
                if k == "kinds":
                    spec = {"t": "enumlist", "choices": sorted(e["strs"] | {"tri", "ring", "cross", "half", "circle", "square"}), "max": 6}
                else:
                    spec = {"t": "colors", "max": 8}
            elif t == {"numlist"}:
                spec = {"t": "rgb"}
            elif t <= {"color", "role", "str"} and "str" in t and all((s in ROLES) or s.startswith(("#", "rgb")) for s in e["strs"]):
                spec = {"t": "color"}
            else:
                continue
            spec["label"] = PARAM_LABELS.get(k, k)
            ps[k] = spec
        out[kind] = ps
    return out


_SCHEMA: dict | None = None


def schema() -> dict:
    """{"bg": {kind: {param: spec}}, "decor": ..., "tex": ..., "text": ...} — specs: color | colors | num | bool | enum | enumlist | pos | rgb."""
    global _SCHEMA
    if _SCHEMA is None:
        bgs, decs, texs, txts = [], [], [], []
        for s in catalog.STYLES:
            for b in [s["bg"]] + ([s["bg2"]] if s.get("bg2") else []):
                bgs.append((b["kind"], {k: v for k, v in b.items() if k != "kind"}))
            for d in s["decor"]:
                decs.append((d["kind"], {k: v for k, v in d.items() if k != "kind"}))
            for t in s["tex"]:
                texs.append((t["kind"], {k: v for k, v in t.items() if k != "kind"}))
            txts.append((s["text"]["fx"], {k: v for k, v in s["text"].items() if k != "fx"}))
        sch = {"bg": _derive(bgs), "decor": _derive(decs), "tex": _derive(texs), "text": _derive(txts)}
        for sec, kinds in (("bg", catalog.BG_KINDS), ("decor", catalog.DECOR_KINDS), ("tex", catalog.TEX_KINDS), ("text", catalog.TEXT_FX)):
            for k in kinds:
                sch[sec].setdefault(k, {})
        _SCHEMA = sch
    return _SCHEMA


KIND_LABELS = {
    "bg": {"solid": "تک‌رنگ", "linear": "گرادیانِ خطی", "radial": "گرادیانِ دایره‌ای", "bands": "نوارهای پله‌ای", "grid": "شبکه", "dots": "نقطه‌چین", "stripes": "راه‌راه",
           "checker": "شطرنجی", "paper": "کاغذ", "notebook": "دفترچه", "whiteboard": "وایت‌برد", "chalk": "تختهٔ گچی", "halftone": "هاف‌تون", "mesh": "گرادیانِ توری",
           "lowpoly": "لو‌پلی", "stained": "شیشهٔ رنگی", "isocubes": "مکعب‌های ایزومتریک", "isogrid": "شبکهٔ ایزومتریک", "studs": "برجسته‌های لگو", "hills": "تپه‌ها",
           "clouds": "ابرها", "nightsky": "آسمانِ شب", "skyline": "افقِ شهر", "sunset": "غروبِ سینت‌ویو", "wood": "چوب", "bricks": "آجر", "blinds": "کرکره",
           "parchment": "پوستِ کهنه", "wash": "لکه‌های آبرنگ", "newsprint": "روزنامه", "arcs": "کمان‌های دههٔ ۷۰", "fans": "بادبزنِ آرت‌دکو", "girih": "گره‌چینی",
           "constellation": "صورت‌فلکی", "hud": "رابطِ HUD", "towers": "برج‌های شیشه‌ای", "studio": "استودیو", "spotlight": "نورافکن", "layers": "لایه‌های کاغذ",
           "rays": "پرتوها", "noise": "نویز و نوار", "mosaic": "موزاییک", "ornament": "گل‌وبوته", "waves": "موج", "holo": "هولوگرام", "doubleexp": "نوردهیِ دوگانه",
           "tiltshift": "تیلت‌شیفت", "cloth": "پارچه"},
    "decor": {"confetti": "کاغذرنگی", "sparkles": "جرقه", "pixels": "پیکسل‌ها", "corners": "گوشه‌ها", "bubbles": "حباب", "shapes": "شکل‌های شناور", "blobs": "لکه‌ها",
              "speed": "خط‌های سرعت", "burst": "انفجار", "rain": "باران", "smoke": "دود", "gears": "چرخ‌دنده", "splats": "لکهٔ رنگ", "bars": "نوارها", "birds": "پرنده‌ها",
              "petals": "گلبرگ", "doodles": "خط‌خطی", "stickman": "آدمِ چوبی", "orbs": "گوی‌ها", "cubes": "مکعب‌ها", "letterbox": "نوارِ سینمایی", "flare": "نورِ لنز",
              "dust": "غبار", "particles": "ذره‌ها", "frame": "قاب", "bauhaus": "باهاوس", "shine": "برق", "grain": "دانه", "kawaii": "کاواییِ شناور"},
    "tex": {"grain": "دانه", "halftone": "هاف‌تون", "scanlines": "خطوطِ پویش", "crosshatch": "هاشور", "paper": "دانهٔ کاغذ", "dither": "دیترینگ", "vignette": "تیرگیِ گوشه",
            "bloom": "درخشش", "chalkdust": "گچ‌گرد", "flicker": "چشمک", "scratches": "خط‌وخش", "vhs": "VHS", "crt": "صفحهٔ CRT", "stitch": "بخیه"},
    "text": {"plain": "ساده", "outline": "دورخط", "hard": "سایهٔ سخت", "outline-hard": "دورخط و سایهٔ سخت", "long": "سایهٔ بلند", "extrude": "برجسته", "neon": "نئون",
             "neon-outline": "نئونِ خطی", "neon-tube": "لولهٔ نئون", "chrome": "کروم", "gold": "طلایی", "gradient": "گرادیان", "emboss": "برجسته‌کاری", "clay": "خمیری",
             "chalk": "گچی", "hand": "دست‌نویس", "pencil": "مداد", "ink": "جوهری", "glitch": "گلیچ", "misregister": "چاپِ ناهم‌تراز", "stamp": "مُهر", "sticker": "برچسب",
             "pixel": "پیکسلی", "fold": "تاخورده", "cel": "سل‌شید", "retro": "رترو", "engrave": "حکاکی", "phosphor": "فسفری", "vhs": "VHS", "marker": "ماژیک",
             "cutout": "بریده‌شده", "felt": "نمدی", "glass": "شیشه‌ای", "brick": "آجری", "softglow": "درخششِ نرم", "spray": "اسپری"},
    "enter": {"pop": "جهش", "rise": "بالا آمدن", "drop": "افتادن", "slide": "لغزیدن", "wipe": "پاک‌شدن", "type": "تایپ", "scan": "اسکن", "flip": "ورق‌خوردن", "unfold": "بازشدن",
              "spin": "چرخش", "blur": "ازتاری", "bloom": "شکوفایی", "stamp": "مُهر", "swing": "تاب", "build": "ساختن", "glitch": "گلیچ", "sweep": "جاروب", "squash": "له‌شدن",
              "zoompunch": "ضربهٔ زوم", "float": "شناور", "slam": "کوبیدن", "lightup": "روشن‌شدن", "grow": "رشد", "fade": "محو"},
    "trans": {"cut": "برش", "fade": "محو", "dip": "محو به سیاه", "slide": "لغزش", "push": "هل‌دادن", "cover": "پوشاندن", "wipe": "پاک‌کردن", "wipe-diag": "پاک‌کردنِ مورب",
              "zoom": "زوم", "iris": "عنبیه", "curtain": "پرده", "flip": "ورق", "spin": "چرخش", "whip": "شلاق", "glitch": "گلیچ", "roll": "غلتش", "blocks": "بلوک‌ها",
              "flash": "فلش", "ink": "جوهر"},
}

# ───────────────────────────────────────────── shape (card / button) options
SHAPE_SCHEMA = {
    "radius": {"t": "num", "min": 0, "max": 60, "label": "گردیِ گوشه"},
    "border": {"t": "num", "min": 0, "max": 12, "label": "ضخامتِ قاب"},
    "bc": {"t": "color", "label": "رنگِ قاب"},
    "shadow": {"t": "enum", "choices": ["none", "soft", "hard", "glow", "inner", "float", "long"], "label": "سایه"},
    "sc": {"t": "color", "label": "رنگِ سایه"},
    "offset": {"t": "num", "min": 0, "max": 16, "label": "فاصلهٔ سایهٔ سخت"},
    "fill": {"t": "fill", "label": "رنگِ کارت"},
    "extra": {"t": "enum", "choices": ["", "band", "corner", "rivets", "studs", "tape", "titlebar"], "label": "نشانِ کارت"},
    "clip": {"t": "enum", "choices": ["", "notch", "torn"], "label": "برشِ گوشه"},
    "dash": {"t": "bool", "label": "قابِ خط‌چین"},
    "tilt": {"t": "num", "min": -3, "max": 3, "label": "کجیِ کارت (درجه)"},
    "badge": {"t": "color", "label": "رنگِ نشان"},
    "bar": {"t": "color", "label": "رنگِ نوار"},
    "badgeRound": {"t": "bool", "label": "نشانِ گرد"},
    "bandColor": {"t": "color", "label": "رنگِ نوار"},
    "fillGradient": {"t": "num", "min": 0, "max": 360, "label": "زاویهٔ گرادیانِ کارت"},
    "filter": {"t": "enum", "choices": ["", "url(#nm-chalk)", "url(#nm-ink)", "url(#nm-rough)"], "label": "لبهٔ دست‌کشیده"},
}
FIXED_FX = {"chroma": (0, 10), "posterize": (2, 12), "pixel": (2, 10)}
FONT_CASES = ("none", "upper")

# ───────────────────────────────────────────── «شخصیتِ حرکت» presets (fill enter + spring + ease + stagger + step + wobble in one click)
PERSONALITIES = [
    {"id": "soft", "name": "نرم و شناور", "motion": {"enter": "float", "spring": [28, 70, 1.3], "ease": "out-soft", "stagger": 10, "stepFps": None, "wobble": 0}, "trans": ["fade", 22]},
    {"id": "snappy", "name": "تند و دقیق", "motion": {"enter": "slide", "spring": [20, 220, 0.8], "ease": "out-expo", "stagger": 5, "stepFps": None, "wobble": 0}, "trans": ["wipe", 12]},
    {"id": "bouncy", "name": "فنری و شاد", "motion": {"enter": "pop", "spring": [10, 160, 0.9], "ease": "back", "stagger": 6, "stepFps": None, "wobble": 0}, "trans": ["slide", 14]},
    {"id": "heavy", "name": "سنگین و سینمایی", "motion": {"enter": "bloom", "spring": [34, 70, 1.6], "ease": "in-out-expo", "stagger": 14, "stepFps": None, "wobble": 0,
                                                      "cam": {"zoom": 0.08}}, "trans": ["dip", 26]},
    {"id": "stepped", "name": "پله‌ای (استاپ‌موشن)", "motion": {"enter": "rise", "spring": [16, 140, 0.9], "ease": "snap", "stagger": 6, "stepFps": 8, "wobble": 0}, "trans": ["slide", 12]},
    {"id": "handmade", "name": "دست‌ساز و لرزان", "motion": {"enter": "wipe", "spring": [30, 140, 1.0], "ease": "smooth", "stagger": 8, "stepFps": 12, "wobble": 3}, "trans": ["wipe", 16]},
    {"id": "punchy", "name": "ضربه‌ای و پرانرژی", "motion": {"enter": "zoompunch", "spring": [11, 220, 0.75], "ease": "snap", "stagger": 4, "stepFps": None, "wobble": 0}, "trans": ["whip", 10]},
    {"id": "glitchy", "name": "گلیچ و دیجیتال", "motion": {"enter": "glitch", "spring": [22, 200, 0.8], "ease": "snap", "stagger": 4, "stepFps": 15, "wobble": 0}, "trans": ["glitch", 14]},
]


# ───────────────────────────────────────────── colours

def hexn(v) -> str | None:
    if isinstance(v, str) and HEX_RE.match(v.strip()):
        t = v.strip().lower()
        return t if t.startswith("#") else "#" + t
    return None


def _rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lin(v: float) -> float:
    v /= 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def lum(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _to_hex(r, g, b) -> str:
    return "#%02x%02x%02x" % (max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))


def mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return _to_hex(*(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def push_contrast(fg: str, bg: str, need: float) -> str:
    """نزدیک‌ترین رنگ به fg (همان رنگمایه) که روی bg کنتراستِ need بدهد: به سمتِ سیاه/سفید می‌رود."""
    if ratio(fg, bg) >= need:
        return fg
    target = "#000000" if lum(bg) > 0.4 else "#ffffff"
    for step in range(1, 21):
        c = mix(fg, target, step / 20)
        if ratio(c, bg) >= need:
            return c
    return target


def hsl_hex(h: float, s: float, l: float) -> str:  # noqa: E741
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s)))
    return _to_hex(r * 255, g * 255, b * 255)


def to_hsl(hx: str) -> tuple:
    r, g, b = (x / 255 for x in _rgb(hx))
    h, l, s = colorsys.rgb_to_hls(r, g, b)  # noqa: E741
    return h, s, l


def palette_from_colors(colors: list, dark: bool | None = None) -> dict:
    """۱ تا ۳ رنگِ برند ⇒ پالتِ ۸ نقشی که کنتراستِ لازم را دارد (زمینهٔ روشن یا تیره از رنگِ اول)."""
    cols = [c for c in (hexn(x) for x in (colors or [])) if c][:3] or ["#126f85"]
    base = cols[0]
    h, s, l = to_hsl(base)  # noqa: E741
    if dark is None:
        dark = l < 0.45
    if dark:
        bg, bg2 = hsl_hex(h, min(0.55, s), 0.10), hsl_hex(h, min(0.5, s), 0.17)
        ink, paper = "#f5f7fb", "#e9eef7"
    else:
        bg, bg2 = hsl_hex(h, min(0.6, s * 0.7), 0.96), hsl_hex(h, min(0.5, s * 0.6), 0.90)
        ink, paper = hsl_hex(h, min(0.45, s), 0.12), "#ffffff"
    a1 = push_contrast(cols[0], bg, 3.0)
    a2 = push_contrast(cols[1] if len(cols) > 1 else hsl_hex(h + 0.08, max(0.5, s), 0.5), bg, 3.0)
    a3 = push_contrast(cols[2] if len(cols) > 2 else hsl_hex(h - 0.1, max(0.5, s), 0.55), bg, 2.2)
    muted = push_contrast(mix(ink, bg, 0.45), bg, 3.0)
    return {"bg": bg, "bg2": bg2, "ink": ink, "paper": paper, "accent": a1, "accent2": a2, "accent3": a3, "muted": muted}


# ───────────────────────────────────────────── contrast guard

#: (نقشِ جلو، نقشِ پشت، کمینهٔ «خطا»، کمینهٔ «هشدار», توضیحِ فارسی). «TEXT» = رنگی که متنِ اصلی با آن کشیده می‌شود (`text.color`، پیش‌فرض: جوهر)
GUARD = [
    ("TEXT", "bg", 4.5, 4.5, "متنِ اصلی روی زمینه"),
    ("accent", "bg", None, 3.0, "رنگِ تأکید (کلمهٔ پررنگ، دکمه) روی زمینه"),
    ("muted", "bg", None, 3.0, "متنِ کم‌رنگ (خاموش) روی زمینه"),
    ("ink", "bg2", None, 3.0, "متنِ اصلی روی زمینهٔ دوم (صحنه‌های زوج)"),
    ("accent2", "bg", None, 1.8, "رنگِ تأکیدِ دوم روی زمینه"),
    ("accent3", "bg", None, 1.6, "رنگِ تأکیدِ سوم روی زمینه"),
]
ROLE_FA = {"bg": "زمینه", "bg2": "زمینهٔ دوم", "ink": "جوهر (متن)", "paper": "کاغذ (کارت)", "accent": "تأکید", "accent2": "تأکیدِ دوم", "accent3": "تأکیدِ سوم", "muted": "خاموش"}
#: نسبتِ کنتراستِ متنِ اصلی که برای افکت‌هایی که خودشان دور/سایه می‌کشند کافی است (سنجشِ دقیق‌تر را QA از روی پیکسل می‌کند)
OUTLINED_TEXT_MIN = 3.0


def text_role(style: dict) -> str:
    c = (style.get("text") or {}).get("color")
    return c if c in ROLES else "ink"


def contrast_report(style: dict) -> dict:
    """⇒ {ok, checks[{fg, bg, ratio, need, severity, ok, message}], errors[], warnings[]}. روی پالتِ ۸ نقش؛ کنتراستِ واقعیِ پیکسل‌ها را QA بعداً می‌سنجد."""
    pal = style["palette"]
    fx = (style.get("text") or {}).get("fx", "plain")
    checks = []
    for fg, bg, err, warn, what in GUARD:
        role = text_role(style) if fg == "TEXT" else fg
        r = ratio(pal[role], pal[bg])
        e_need = err
        if fg == "TEXT" and fx in SELF_OUTLINED_FX:
            # the effect draws its own outline / shadow (the pixel check of the QA judges the real result): the palette may only warn for a coloured text,
            # and the plain ink colour keeps a lower bar
            e_need = OUTLINED_TEXT_MIN if role == "ink" else None
        w_need = warn
        if e_need is not None and r < e_need:
            sev, need = "error", e_need
        elif w_need is not None and r < w_need:
            sev, need = "warn", w_need
        else:
            sev, need = "ok", e_need or w_need
        label = what + (f" («{ROLE_FA.get(role, role)}»)" if fg == "TEXT" and role != "ink" else "")
        checks.append({"fg": role, "bg": bg, "ratio": round(r, 2), "need": need, "severity": sev, "ok": sev == "ok",
                       "message": f"{label}: کنتراست {r:.1f} (حداقل {need:g})" if sev != "ok" else f"{label}: {r:.1f}"})
    errs = [c for c in checks if c["severity"] == "error"]
    warns = [c for c in checks if c["severity"] == "warn"]
    return {"ok": not errs, "checks": checks, "errors": [c["message"] for c in errs], "warnings": [c["message"] for c in warns]}


def fix_palette(style: dict) -> dict:
    """اصلاحِ خودکارِ پالت: هر نقشِ جلو را (با همان رنگمایه) تا حدِ لازم روشن/تیره می‌کند. ⇒ پالتِ تازه (۸ نقش).
    اصلاحِ «هشدار» هرگز یک «خطا» را خراب نمی‌کند (جوهرِ روشن روی زمینهٔ تیره نباید برای زمینهٔ دومِ روشن دوباره تیره شود)."""
    pal = dict(style["palette"])
    fx = (style.get("text") or {}).get("fx", "plain")
    role_t = text_role(style)

    def hard_ok(p: dict) -> bool:
        need = OUTLINED_TEXT_MIN if (fx in SELF_OUTLINED_FX and role_t == "ink") else (None if fx in SELF_OUTLINED_FX else 4.5)
        return need is None or ratio(p[role_t], p["bg"]) >= need

    for _ in range(2):
        for fg, bg, err, warn, _w in GUARD:
            role = role_t if fg == "TEXT" else fg
            need = max(x for x in (err, warn) if x is not None)
            if fg == "TEXT" and fx in SELF_OUTLINED_FX:
                need = 3.5
            if ratio(pal[role], pal[bg]) < need:
                cand = {**pal, role: push_contrast(pal[role], pal[bg], need)}
                if err is not None or hard_ok(cand):
                    pal = cand
    return pal


# ───────────────────────────────────────────── validation

def _clean_text(v, n: int) -> str:
    s = str(v or "").replace("\r", "").replace("\x00", "")
    s = re.sub(r"[‪-‮⁦-⁩]", "", s)
    return re.sub(r"\s+", " ", s).strip()[:n]


def _num(v, lo: float, hi: float, default=None, *, integer=False, notes=None, what=""):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    c = max(lo, min(hi, x))
    if c != x and notes is not None and what:
        notes.append(f"«{what}» به بازهٔ مجاز ({lo:g} تا {hi:g}) برگردانده شد.")
    return int(round(c)) if integer else round(c, 4)


def _color(v, *, allow_rgba=True):
    if isinstance(v, str):
        t = v.strip()
        if t in ROLES:
            return t
        h = hexn(t)
        if h:
            return h
        if allow_rgba and RGBA_RE.match(t):
            return re.sub(r"\s+", "", t)
    return None


def _clean_params(params: dict, spec: dict, where: str, notes: list) -> dict:
    out = {}
    for k, v in (params or {}).items():
        if k in ("kind", "fx"):
            continue
        sp = spec.get(k)
        if sp is None:
            notes.append(f"{where}: پارامترِ «{k}» نامعتبر بود و کنار گذاشته شد.")
            continue
        t = sp["t"]
        if t == "num":
            x = _num(v, sp["min"], sp["max"], None, integer=bool(sp.get("int")), notes=notes, what=f"{where} · {sp.get('label', k)}")
            if x is not None:
                out[k] = x
        elif t == "bool":
            out[k] = bool(v)
        elif t == "color":
            c = _color(v)
            if c:
                out[k] = c
            else:
                notes.append(f"{where}: رنگِ «{sp.get('label', k)}» معتبر نبود.")
        elif t == "colors":
            lst = [_color(x) for x in (v if isinstance(v, list) else [])]
            lst = [c for c in lst if c][: sp.get("max", 8)]
            if lst:
                out[k] = lst
        elif t == "enum":
            if v in sp["choices"]:
                out[k] = v
        elif t == "enumlist":
            lst = [x for x in (v if isinstance(v, list) else []) if x in sp["choices"]][: sp.get("max", 6)]
            if lst:
                out[k] = lst
        elif t == "pos":
            if isinstance(v, str) and re.fullmatch(r"\d{1,3}% \d{1,3}%", v.strip()):
                out[k] = v.strip()
        elif t == "rgb":
            if isinstance(v, list) and len(v) == 3:
                out[k] = [int(_num(x, 0, 255, 0)) for x in v]
        elif t == "palmap":
            if isinstance(v, dict):
                m = {a: b for a, b in v.items() if a in ROLES and b in ROLES}
                if m:
                    out[k] = m
    return out


def _clean_kind(item, section: str, kinds, where: str, notes: list, kind_key="kind"):
    if not isinstance(item, dict):
        raise StyleError(f"{where}: ساختارِ نامعتبر.")
    kind = item.get(kind_key)
    if kind not in kinds:
        raise StyleError(f"{where}: نوعِ «{kind}» را موتور نمی‌شناسد.")
    out = {kind_key: kind}
    out.update(_clean_params(item, schema()[section].get(kind, {}), f"{where} ({KIND_LABELS.get(section, {}).get(kind, kind)})", notes))
    return out


def blank_style() -> dict:
    """سبکِ «از صفر»: کاغذیِ روشن و مینیمال با پالتِ آبی؛ همه‌چیز معتبر و خوانا."""
    return {
        "name_fa": "سبکِ تازه", "name_en": "My style", "about": "", "tags": [], "group": CUSTOM_GROUP,
        "palette": {"bg": "#f7faff", "bg2": "#dbe6ff", "ink": "#1b2b45", "paper": "#ffffff", "accent": "#126f85", "accent2": "#163f75", "accent3": "#e08a1e", "muted": "#5a6b85"},
        "font": {"latin": "vazirmatn", "fa": "vazirmatn", "weight": 700, "body_latin": None, "body_fa": None, "case": "none", "track": 0, "lh": 1.3},
        "bg": {"kind": "linear", "from": "bg", "to": "bg2", "angle": 170}, "bg2": None, "tex": [{"kind": "grain", "opacity": 0.05}],
        "text": {"fx": "plain"}, "shape": {"radius": 20, "border": 0, "shadow": "soft", "fill": "paper"},
        "decor": [{"kind": "blobs", "n": 4, "colors": ["accent", "accent2", "accent3"], "op": 0.18}],
        "motion": {"enter": "rise", "spring": [24, 120, 1.0], "ease": "out-expo", "stagger": 7, "stepFps": None, "wobble": 0, "cam": None},
        "trans": {"kind": "fade", "frames": 16}, "fx": {},
    }


def sanitize(raw: dict, *, notes: list | None = None, strict_contrast: bool = False) -> dict:
    """ورودیِ خام (از فرم، JSON واردشده یا مدل) ⇒ سبکِ پاک‌شده (بدونِ شناسه). مشکلِ اساسی ⇒ StyleError. بخشی که نبود از «سبکِ از صفر» می‌آید.
    strict_contrast=True: پالتی که نگهبانِ کنتراست را رد کند هم StyleError می‌دهد."""
    notes = notes if notes is not None else []
    if not isinstance(raw, dict):
        raise StyleError("سبک باید یک شیء JSON باشد.")
    base = blank_style()
    name_fa = _clean_text(raw.get("name_fa"), 40)
    if len(name_fa) < 2:
        raise StyleError("برای سبک یک نامِ فارسی بنویسید (حداقل دو حرف).")
    name_en = _clean_text(raw.get("name_en"), 40) or ""
    out: dict = {"name_fa": name_fa, "name_en": name_en or _slugify(name_fa, "My style").replace("-", " ").title(), "inspired": None,
                 "about": _clean_text(raw.get("about"), 240), "tags": [t for t in (_clean_text(x, 20) for x in (raw.get("tags") or []) if isinstance(x, str)) if t][:6]}
    g = raw.get("group")
    out["group"] = g if g in catalog.GROUPS or g == CUSTOM_GROUP else CUSTOM_GROUP
    # palette: all eight roles, as hex
    pal_in = raw.get("palette") if isinstance(raw.get("palette"), dict) else {}
    pal = {}
    for k in ROLES:
        h = hexn(pal_in.get(k))
        if not h:
            if pal_in.get(k) is not None:
                notes.append(f"رنگِ «{ROLE_FA[k]}» معتبر نبود؛ مقدارِ پیش‌فرض گذاشته شد.")
            h = base["palette"][k]
        pal[k] = h
    out["palette"] = pal
    # fonts: only the licensed set
    F = fonts()
    fin = raw.get("font") if isinstance(raw.get("font"), dict) else {}

    def pick(key, need_fa=False, optional=False):
        v = fin.get(key)
        if optional and not v:
            return None
        if isinstance(v, str) and v in F and (not need_fa or F[v]["fa"]):
            return v
        if v:
            notes.append(f"قلمِ «{v}» در مجموعهٔ دارای مجوز نیست یا حروفِ فارسی ندارد؛ وزیرمتن گذاشته شد.")
        return None if optional else "vazirmatn"

    out["font"] = {
        "latin": pick("latin"), "fa": pick("fa", need_fa=True), "weight": _num(fin.get("weight"), 300, 900, 700, integer=True, notes=notes, what="وزنِ قلم") // 100 * 100,
        "body_latin": pick("body_latin", optional=True), "body_fa": pick("body_fa", need_fa=True, optional=True),
        "case": fin.get("case") if fin.get("case") in FONT_CASES else "none", "track": _num(fin.get("track"), -0.05, 0.4, 0.0, notes=notes, what="فاصلهٔ حروف"),
        "lh": _num(fin.get("lh"), 1.0, 1.8, 1.3, notes=notes, what="ارتفاعِ خط"),
    }
    # backgrounds
    where = "پس‌زمینه"
    out["bg"] = _clean_kind(raw.get("bg") or base["bg"], "bg", catalog.BG_KINDS, where, notes)
    out["bg2"] = _clean_kind(raw["bg2"], "bg", catalog.BG_KINDS, "پس‌زمینهٔ صحنه‌های زوج", notes) if raw.get("bg2") else None
    tex_in = raw.get("tex") if isinstance(raw.get("tex"), list) else []
    if len(tex_in) > MAX_TEX:
        notes.append(f"حداکثر {MAX_TEX} بافت مجاز است؛ بقیه کنار گذاشته شد.")
    out["tex"] = [_clean_kind(t, "tex", catalog.TEX_KINDS, "بافت", notes) for t in tex_in[:MAX_TEX]]
    dec_in = raw.get("decor") if isinstance(raw.get("decor"), list) else []
    if len(dec_in) > MAX_DECOR:
        notes.append(f"حداکثر {MAX_DECOR} تزئین مجاز است؛ بقیه کنار گذاشته شد.")
    out["decor"] = [_clean_kind(d, "decor", catalog.DECOR_KINDS, "تزئین", notes) for d in dec_in[:MAX_DECOR]]
    tin = raw.get("text") if isinstance(raw.get("text"), dict) else base["text"]
    out["text"] = _clean_kind(tin, "text", catalog.TEXT_FX, "افکتِ متن", notes, kind_key="fx")
    # card / button shape
    sh_in = raw.get("shape") if isinstance(raw.get("shape"), dict) else {}
    sh = {}
    for k, sp in SHAPE_SCHEMA.items():
        if k not in sh_in:
            continue
        v = sh_in[k]
        t = sp["t"]
        if t == "num":
            x = _num(v, sp["min"], sp["max"], None, integer=k in ("radius", "border", "offset", "fillGradient"), notes=notes, what=sp["label"])
            if x is not None:
                sh[k] = x
        elif t == "bool":
            sh[k] = bool(v)
        elif t == "color":
            c = _color(v)
            if c:
                sh[k] = c
        elif t == "enum":
            if v in sp["choices"]:
                if v != "":
                    sh[k] = v
        elif t == "fill":
            c = _color(v)
            if v in ("glass", "none"):
                sh[k] = v
            elif c:
                sh[k] = c
    sh.setdefault("radius", 16)
    sh.setdefault("border", 0)
    sh.setdefault("shadow", "soft")
    sh.setdefault("fill", "paper")
    out["shape"] = sh
    # motion personality
    m = raw.get("motion") if isinstance(raw.get("motion"), dict) else {}
    sp = m.get("spring") if isinstance(m.get("spring"), (list, tuple)) and len(m.get("spring")) == 3 else base["motion"]["spring"]
    cam_in = m.get("cam") if isinstance(m.get("cam"), dict) else None
    cam = None
    if cam_in:
        cam = {}
        if cam_in.get("zoom") is not None:
            cam["zoom"] = _num(cam_in["zoom"], 0, 0.15, 0.0, notes=notes, what="زومِ دوربین")
        if cam_in.get("rot") is not None:
            cam["rot"] = _num(cam_in["rot"], -5, 5, 0.0, notes=notes, what="چرخشِ دوربین")
        if cam_in.get("sway") is not None:
            cam["sway"] = _num(cam_in["sway"], 0, 12, 0.0, notes=notes, what="تابِ دوربین")
        pan = cam_in.get("pan")
        if isinstance(pan, (list, tuple)) and len(pan) == 2:
            cam["pan"] = [_num(pan[0], -60, 60, 0.0, notes=notes, what="پنِ دوربین"), _num(pan[1], -60, 60, 0.0, notes=notes, what="پنِ دوربین")]
        cam = cam or None
    step = m.get("stepFps")
    out["motion"] = {
        "enter": m.get("enter") if m.get("enter") in catalog.ENTER_KINDS else base["motion"]["enter"],
        "spring": [_num(sp[0], 1, 80, 24, notes=notes, what="میراییِ فنر"), _num(sp[1], 20, 400, 120, notes=notes, what="سفتیِ فنر"), _num(sp[2], 0.2, 3, 1.0, notes=notes, what="جرمِ فنر")],
        "ease": m.get("ease") if m.get("ease") in motionlib.EASES else "out-expo",
        "stagger": _num(m.get("stagger"), 0, 24, 7, integer=True, notes=notes, what="تأخیرِ پله‌ای"),
        "stepFps": _num(step, 4, 24, None, integer=True, notes=notes, what="فریم‌برثانیهٔ پله‌ای") if step else None,
        "wobble": _num(m.get("wobble"), 0, 8, 0, notes=notes, what="لرزشِ دست"), "cam": cam,
    }
    tr = raw.get("trans") if isinstance(raw.get("trans"), dict) else {}
    out["trans"] = {"kind": tr.get("kind") if tr.get("kind") in catalog.TRANS_KINDS else "fade", "frames": _num(tr.get("frames"), 0, 40, 16, integer=True, notes=notes, what="طولِ گذار")}
    fx_in = raw.get("fx") if isinstance(raw.get("fx"), dict) else {}
    fx: dict = {}
    for k, (lo, hi) in FIXED_FX.items():
        if fx_in.get(k):
            fx[k] = _num(fx_in[k], lo, hi, lo, notes=notes, what=k)
    g = fx_in.get("grade")
    if isinstance(g, str) and g.strip():
        if GRADE_RE.match(g.strip()):
            fx["grade"] = g.strip()
        else:
            notes.append("فیلترِ رنگِ کلِ تصویر معتبر نبود و کنار گذاشته شد.")
    out["fx"] = fx
    rep = contrast_report(out)
    if strict_contrast and not rep["ok"]:
        raise StyleError("نگهبانِ کنتراست: " + "؛ ".join(rep["errors"]))
    return out


def canonical(style: dict) -> str:
    """JSONِ یکتا برای امضا (بدونِ شناسه/نامِ نمایشی که کیفیتِ رندر را عوض نمی‌کنند)."""
    d = {k: v for k, v in style.items() if k not in ("id", "scope", "store_id", "thumb_url", "custom", "qa", "created_at", "updated_at")}
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def style_hash(style: dict) -> str:
    return hashlib.sha256(canonical(style).encode("utf-8")).hexdigest()[:24]


# ───────────────────────────────────────────── ids

_TRANSLIT = str.maketrans({"ا": "a", "آ": "a", "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "ژ": "zh",
                           "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "gh", "ک": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m",
                           "ن": "n", "و": "v", "ه": "h", "ی": "y", "ي": "y", "ئ": "e", "ء": "", "ة": "h", "أ": "a", "ؤ": "v", "إ": "e", "‌": "-", "۰": "0", "۱": "1", "۲": "2",
                           "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"})


def _slugify(text: str, fallback: str = "style") -> str:
    s = (text or "").translate(_TRANSLIT).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:28].strip("-")
    return s if len(s) >= 2 else re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-")[:28] or "style"


def make_id(store_id: int | None, name_en: str, name_fa: str, taken) -> str:
    """u<store>-<slug> (همگانی: g-<slug>)؛ تکراری ⇒ -2، -3 ..."""
    prefix = "g" if store_id is None else f"u{int(store_id)}"
    slug = _slugify(name_en, "") if name_en and name_en != "My style" else ""
    if len(slug) < 2:
        slug = _slugify(name_fa, "style")
    cand = f"{prefix}-{slug}"
    n = 1
    while cand in taken or cand in {s["id"] for s in catalog.STYLES}:
        n += 1
        cand = f"{prefix}-{slug[:26]}-{n}"
    return cand


def parse_id(style_id: str):
    """⇒ (kind, store_id) برای شناسهٔ سبکِ شخصی: ("store", 12) | ("global", None) | None."""
    m = ID_RE.match(style_id or "")
    if not m:
        return None
    return ("store", int(m.group(1))) if m.group(1) else ("global", None)


def usable_by(style_id: str, store_id: int) -> bool:
    p = parse_id(style_id)
    return bool(p) and (p[0] == "global" or p[1] == int(store_id))


# ───────────────────────────────────────────── the full StyleDef that the engine reads

def to_styledef(style_id: str, data: dict, *, scope: str = "store") -> dict:
    """سبکِ ذخیره‌شده ⇒ ردیفِ کاملِ StyleDef (همان شکلِ catalog.S)."""
    d = copy.deepcopy(dict(data))
    d["id"] = style_id
    d["custom"] = True
    d["scope"] = scope
    d.setdefault("inspired", None)
    d.setdefault("fits", "")
    d.setdefault("tags", [])
    d["group_label"] = "سبک‌های من" if scope == "store" else "سبک‌های همگانی"
    return d


def render_def(style: dict) -> dict:
    """آنچه به رندر/QA/پخش‌کننده می‌رود (`spec.style_def`): فقط فیلدهایی که موتور می‌خواند."""
    keep = ("id", "name_fa", "name_en", "inspired", "group", "about", "palette", "font", "bg", "bg2", "tex", "text", "shape", "decor", "motion", "trans", "fx")
    return copy.deepcopy({k: style.get(k) for k in keep if k in style})


# ───────────────────────────────────────────── registry hook used by catalog.get()

_DRAFTS = threading.local()


@contextlib.contextmanager
def draft(style_id: str, styledef: dict):
    """پیش‌نویسِ ذخیره‌نشده را (فقط در همین رشته و تا پایانِ بلوک) برای catalog.get() قابلِ‌دیدن می‌کند: کنترلِ کیفیتِ یک سبکِ تازه، طرح و زمان‌بندی و
    اعتبارسنجی را با همان کدی انجام می‌دهد که برای سبکِ ذخیره‌شده کار می‌کند."""
    cur = getattr(_DRAFTS, "m", None)
    if cur is None:
        cur = _DRAFTS.m = {}
    prev = cur.get(style_id)
    cur[style_id] = styledef
    try:
        yield styledef
    finally:
        if prev is None:
            cur.pop(style_id, None)
        else:
            cur[style_id] = prev


def lookup(style_id: str) -> dict | None:
    """سبکِ شخصی از دیتابیس (یا None). catalog.get() این را برای شناسه‌های `u…-…` / `g-…` صدا می‌زند."""
    if not ID_RE.match(style_id or ""):
        return None
    d = (getattr(_DRAFTS, "m", None) or {}).get(style_id)
    if d is not None:
        return d
    try:
        from .models import MotionCustomStyle

        row = MotionCustomStyle.objects.filter(style_id=style_id).first()
    except Exception:  # noqa: BLE001 — بدونِ دیتابیس (ابزارهای بیرونِ Django) سبکِ شخصی وجود ندارد
        return None
    return row.as_styledef() if row else None


# ───────────────────────────────────────────── export / import

def export_json(style: dict) -> dict:
    d = {k: v for k, v in style.items() if k not in ("id", "scope", "store_id", "thumb_url", "custom", "qa", "created_at", "updated_at", "group_label", "fits")}
    return {"nm_motion_style": SCHEMA, "style": d}


def import_json(payload) -> tuple[dict, list]:
    """JSONِ خروجی (یا خودِ شیء سبک) ⇒ (سبکِ پاک‌شده, یادداشت‌ها). نسخهٔ جدیدتر یا ساختارِ ناشناخته ⇒ StyleError."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise StyleError("فایل JSON معتبر نیست.") from exc
    if not isinstance(payload, dict):
        raise StyleError("فایل JSON معتبر نیست.")
    ver = payload.get("nm_motion_style")
    if ver is not None and (not isinstance(ver, int) or ver > SCHEMA):
        raise StyleError("این فایل با نسخهٔ جدیدتری از سامانه ساخته شده است.")
    raw = payload.get("style") if isinstance(payload.get("style"), dict) else payload
    notes: list = []
    return sanitize(raw, notes=notes), notes
