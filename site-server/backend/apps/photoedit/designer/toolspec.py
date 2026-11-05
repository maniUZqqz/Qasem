"""کاتالوگِ ابزارهای «طراحِ خودکار» و وارسیِ سخت‌گیرانهٔ برنامه (plan).

برنامه = فهرستِ مرحله‌ها؛ هر مرحله ``{id, tool, on, params, title, why}``. همین کاتالوگ سه جا استفاده می‌شود:
  ۱) در پرامپتِ هوش مصنوعی (او فقط از همین ابزارها و بازه‌ها می‌تواند استفاده کند)،
  ۲) برای وارسی (هر مقدارِ بیرون از بازه به بازه می‌رود، کلید/ابزارِ ناشناخته دور ریخته می‌شود)،
  ۳) در پنل (مرحله‌ها به فارسیِ خوانا نشان داده و قابل‌ویرایش اند).

هر ابزار دقیقاً همتای یک کارِ ادیتورِ دستی است؛ خروجی لایه‌ها و تنظیم‌های ادیتورِ دستی می‌شود (build.py).
رنگ: ``#rrggbb`` یا نشانهٔ پالت (auto، text، text_dim، accent، accent_text، plate، bg_a، bg_b) که هنگامِ ساخت از هارمونیِ رنگِ محصول می‌آید.
"""
from __future__ import annotations

import re

from .. import catalog, fontreg
from . import colorx, grid

PALETTE_TOKENS = ("auto", "text", "text_dim", "accent", "accent_text", "plate", "bg_a", "bg_b", "white", "black")
SLOTS = grid.SLOT_NAMES + ("auto",)
ROLES = ("caption", "sub", "body", "cta", "badge", "title", "price", "hero", "display")
MAX_STEPS = 28
MAX_TEXT = 90

#: ترتیبِ مرحله‌ها در برنامه: هندسه ⇐ رنگ ⇐ لایه‌ها از پایین به بالا ⇐ خروجی. (مرحله‌ها همیشه به همین ترتیب مرتب می‌شوند.)
PHASE = {"rotate": 0, "crop": 1, "frame": 2, "grade": 3, "cutout": 4, "backdrop": 5, "shadow": 6, "local_adjust": 7, "scrim": 8,
         "shape": 9, "image": 10, "compare": 10, "badge": 11, "text": 12, "logo": 13, "ai_fill": 14, "export": 20}
SINGLE = {"rotate", "crop", "frame", "grade", "cutout", "backdrop", "shadow", "export", "logo", "compare"}


def _p(key, typ, title, default=None, *, lo=None, hi=None, options=None, help_="", max_len=None):
    return {"key": key, "type": typ, "title": title, "default": default, "min": lo, "max": hi, "options": options,
            "help": help_, "max_len": max_len}


COLOR = "color"
TOOLS: list[dict] = [
    {"key": "rotate", "title": "چرخش و صاف‌کردن", "doc": "چرخشِ ۹۰ درجه‌ای، صاف‌کردنِ افقِ کج، قرینه.",
     "params": [_p("turn", "enum", "چرخش", "0", options=["0", "90", "180", "270"]),
                _p("straighten", "num", "صاف‌کردن (درجه)", 0, lo=-15, hi=15),
                _p("flip_h", "bool", "قرینهٔ افقی", False), _p("flip_v", "bool", "قرینهٔ عمودی", False)]},
    {"key": "crop", "title": "برش", "doc": "برشِ مستطیلی به درصدِ عکس؛ برای حذفِ حاشیهٔ اضافه.",
     "params": [_p("x", "num", "از چپ ٪", 0, lo=0, hi=90), _p("y", "num", "از بالا ٪", 0, lo=0, hi=90),
                _p("w", "num", "پهنا ٪", 100, lo=10, hi=100), _p("h", "num", "ارتفاع ٪", 100, lo=10, hi=100)]},
    {"key": "frame", "title": "قابِ خروجی", "doc": "اندازهٔ نهایی برای شبکه‌ها. «پر کردن» می‌برد و سوژه را در کادر نگه می‌دارد؛ «جا دادن» نمی‌برد.",
     "params": [_p("format", "enum", "قاب", "square", options=list(grid.FORMAT_KEYS)),
                _p("fit", "enum", "روش", "cover", options=["cover", "contain"]),
                _p("focus", "enum", "سوژه کجاست", "smart", options=["smart", "center", "top", "bottom", "left", "right"]),
                _p("fill", "enum", "پرکردنِ دور (جا دادن)", "blur", options=["blur", "white", "black", "color", "transparent"]),
                _p("fill_color", COLOR, "رنگِ پرکردن", "#f3f4f6"), _p("padding", "num", "حاشیه ٪", 0, lo=0, hi=40)]},
    {"key": "grade", "title": "نور و رنگ", "doc": "لغزنده‌های ظهورِ عکس (همان ۵۸ لغزندهٔ ادیتور) و منحنی؛ یا یکی از فیلترهای آماده.",
     "params": [_p("adjust", "adjust", "لغزنده‌ها", {}), _p("curve", "curve", "منحنی", {}),
                _p("preset", "preset", "فیلترِ آماده", ""),
                _p("scope", "enum", "اثر روی", "auto", options=["auto", "photo", "all"],
                   help_="photo = فقط عکس؛ all = همهٔ لایه‌های زیرِ متن (برای محصولِ بریده‌شده)")]},
    {"key": "cutout", "title": "جداکردنِ محصول از پس‌زمینه", "doc": "محصول را از زمینه جدا می‌کند و لایهٔ جداگانه (قابل جابه‌جایی) می‌سازد.",
     "params": [_p("fit", "enum", "جاگیری", "hero", options=["keep", "center", "hero"],
                   help_="keep = همان‌جا؛ center = وسط؛ hero = درشت و وسطِ قاب"),
                _p("scale", "num", "اندازه (نسبت به ضلعِ کوچکِ قاب)", 0.64, lo=0.25, hi=0.95),
                _p("anchor_y", "num", "جای عمودی (۰ بالا تا ۱ پایین)", 0.52, lo=0.25, hi=0.8),
                _p("anchor_x", "num", "جای افقی (۰ چپ تا ۱ راست)", 0.5, lo=0.2, hi=0.8)]},
    {"key": "backdrop", "title": "زمینهٔ تازه", "doc": "زمینهٔ تک‌رنگ یا شیب با رنگ‌های هماهنگ با محصول (جایگزینِ پس‌زمینه).",
     "params": [_p("style", "enum", "نوع", "gradient", options=["solid", "gradient", "studio"]),
                _p("c0", COLOR, "رنگِ ۱", "bg_a"), _p("c1", COLOR, "رنگِ ۲", "bg_b"),
                _p("angle", "num", "زاویهٔ شیب", 100, lo=-360, hi=360), _p("vignette", "num", "تاریکیِ گوشه‌ها", 0.0, lo=0, hi=1)]},
    {"key": "shadow", "title": "سایهٔ محصول", "doc": "سایهٔ نرمِ زیرِ محصولِ بریده‌شده تا روی زمینه «بایستد».",
     "params": [_p("kind", "enum", "نوع", "both", options=["contact", "drop", "both"]),
                _p("strength", "num", "شدت", 0.5, lo=0, hi=1)]},
    {"key": "local_adjust", "title": "تنظیمِ موضعی", "doc": "نورِ نقطه‌ای روی محصول یا تیرگیِ نرمِ گوشه‌ها، با لایهٔ تنظیم و ماسکِ شعاعی.",
     "params": [_p("kind", "enum", "نوع", "spotlight", options=["spotlight", "vignette"]),
                _p("strength", "num", "شدت", 0.5, lo=0, hi=1)]},
    {"key": "scrim", "title": "سایهٔ ملایم برای خوانایی", "doc": "لکهٔ تیره/روشنِ محوشونده پشتِ متن، تا روی عکسِ شلوغ هم خوانا بماند.",
     "params": [_p("edge", "enum", "از کدام لبه", "bottom", options=["top", "bottom", "left", "right", "full", "auto"],
                   help_="auto = از سمتی که متنِ «خودکار» می‌نشیند (آرام‌ترین جای عکس)"),
                _p("strength", "num", "شدت", 0.55, lo=0.05, hi=0.95), _p("size", "num", "اندازه (نسبت به قاب)", 0.45, lo=0.15, hi=1),
                _p("color", COLOR, "رنگ", "plate")]},
    {"key": "shape", "title": "شکل", "doc": "مستطیل، بیضی یا خط؛ برای نوار، کادر، برچسب.",
     "params": [_p("shape", "enum", "شکل", "rect", options=["rect", "ellipse", "line"]),
                _p("slot", "enum", "جا", "bottom", options=list(SLOTS)),
                _p("h_frac", "num", "ارتفاع (نسبت به جا)", 1.0, lo=0.02, hi=1), _p("w_frac", "num", "پهنا (نسبت به جا)", 1.0, lo=0.05, hi=1),
                _p("color", COLOR, "رنگ", "accent"), _p("color2", COLOR, "رنگِ دوم (شیب)", ""),
                _p("opacity", "num", "پیدایی", 1.0, lo=0.05, hi=1), _p("radius", "num", "گردیِ گوشه", 0.0, lo=0, hi=1)]},
    {"key": "text", "title": "متن", "doc": "متنِ فارسی/انگلیسی با فونتِ انتخابی؛ اندازه از مقیاسِ تایپی (نقش)، همیشه داخلِ حاشیهٔ امن و بی‌سرریز.",
     "params": [_p("text", "str", "متن", "", max_len=MAX_TEXT), _p("role", "enum", "نقش (اندازه)", "title", options=list(ROLES)),
                _p("slot", "enum", "جا", "auto", options=list(SLOTS)),
                _p("align", "enum", "تراز", "center", options=["right", "center", "left"]),
                _p("v", "enum", "جای عمودی در جا", "center", options=["start", "center", "end"]),
                _p("color", COLOR, "رنگ", "auto"), _p("weight", "int", "وزن", 700, lo=300, hi=800),
                _p("font", "font", "فونت", "vazirmatn"), _p("max_lines", "int", "بیشترین خط", 3, lo=1, hi=6),
                _p("plate", "enum", "کادرِ پشتِ متن", "auto", options=["none", "auto", "solid", "pill", "accent"]),
                _p("strike", "bool", "خطِ روی متن (قیمتِ قبلی)", False), _p("scale", "num", "ضریبِ اندازه", 1.0, lo=0.5, hi=1.6),
                _p("below", "str", "زیرِ کدام مرحلهٔ متن بیاید (شناسه)", "", max_len=20)]},
    {"key": "badge", "title": "برچسب", "doc": "برچسبِ گرد یا قرصی با متنِ کوتاه (تخفیف، «جدید»، قیمت).",
     "params": [_p("text", "str", "متن", "", max_len=24), _p("sub", "str", "خطِ کوچکتر", "", max_len=24),
                _p("kind", "enum", "شکل", "circle", options=["circle", "pill"]),
                _p("slot", "enum", "جا", "tr", options=list(SLOTS)), _p("color", COLOR, "رنگ", "accent"),
                _p("size", "num", "اندازه (نسبت به پهنا)", 0.24, lo=0.1, hi=0.5), _p("font", "font", "فونت", "estedad")]},
    {"key": "compare", "title": "قبل و بعد", "doc": "نیمهٔ راستِ قاب «قبل» (عکسِ اصل) و نیمهٔ چپ «بعد» (ویرایش‌شده) با خطِ جداکننده و برچسب.",
     "params": [_p("labels", "bool", "برچسب‌های قبل/بعد", True), _p("before", "str", "برچسبِ قبل", "قبل", max_len=12),
                _p("after", "str", "برچسبِ بعد", "بعد", max_len=12)]},
    {"key": "logo", "title": "لوگو", "doc": "لوگوی فروشگاه در گوشه.",
     "params": [_p("position", "enum", "گوشه", "br", options=["tl", "tr", "bl", "br", "bottom_center", "top_center"]),
                _p("size", "num", "اندازه (نسبت به پهنا)", 0.15, lo=0.06, hi=0.35), _p("opacity", "num", "پیدایی", 0.95, lo=0.3, hi=1)]},
    {"key": "image", "title": "تصویر از کتابخانه", "doc": "عکسِ دیگری از کتابخانه (آرم، آیکون، محصولِ دوم).",
     "params": [_p("asset", "int", "شمارهٔ عکس", 0, lo=0, hi=10 ** 9), _p("slot", "enum", "جا", "br", options=list(SLOTS)),
                _p("size", "num", "اندازه (نسبت به پهنا)", 0.2, lo=0.05, hi=0.9), _p("opacity", "num", "پیدایی", 1.0, lo=0.1, hi=1)]},
    {"key": "ai_fill", "title": "پرکردنِ هوشمند (دستی)", "deferred": True,
     "doc": "حذف یا عوض‌کردنِ بخشی از عکس با هوشِ مصنوعیِ تولیدی؛ زمان‌بر است و داخلِ حلقهٔ طراحی اجرا نمی‌شود — به‌صورت پیشنهاد می‌ماند و در «دستی ⇐ پرکردنِ هوشمند» اجرا می‌شود.",
     "params": [_p("prompt", "str", "توضیحِ فارسی (چه بشود؟)", "", max_len=200)]},
    {"key": "export", "title": "خروجی", "doc": "قالب، کیفیت، حجم و اندازهٔ فایل.",
     "params": [_p("format", "enum", "قالب", "jpeg", options=["jpeg", "png", "webp"]),
                _p("quality", "int", "کیفیت", 92, lo=40, hi=100), _p("max_kb", "int", "حداکثر حجم (KB، ۰ = آزاد)", 0, lo=0, hi=20000),
                _p("long_edge", "int", "ضلعِ بلندتر (۰ = قاب)", 0, lo=0, hi=8000)]},
]
BY_KEY = {t["key"]: t for t in TOOLS}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class PlanError(ValueError):
    """برنامهٔ نامعتبر — متن برای کاربر."""


def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, x))


def clean_color(v, default) -> str:
    if isinstance(v, str):
        t = v.strip().lower()
        if _HEX.match(t):
            return t
        if t in PALETTE_TOKENS:
            return t
    return default


def clean_param(spec: dict, v):
    t = spec["type"]
    d = spec["default"]
    if t == "num":
        return round(_num(v, spec["min"], spec["max"], d), 4)
    if t == "int":
        return int(round(_num(v, spec["min"], spec["max"], d)))
    if t == "bool":
        return v in (True, 1, "1", "true", "True", "on")
    if t == "enum":
        return v if isinstance(v, str) and v in spec["options"] else (str(v) if (v is not None and str(v) in spec["options"]) else d)
    if t == COLOR:
        return clean_color(v, d)
    if t == "str":
        s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(v if v is not None else d or "")).strip()
        return s[: spec.get("max_len") or MAX_TEXT]
    if t == "font":
        return v if fontreg.known(v) else fontreg.DEFAULT
    if t == "adjust":
        from .. import smart

        return smart.clean_adjust(v) if isinstance(v, dict) else {}
    if t == "curve":
        return catalog.normalize_curve(v)
    if t == "preset":
        return v if isinstance(v, str) and catalog.kit_presets().get(v, {}).get("kind") == "look" else ""
    return d


def clean_step(raw, idx: int = 0) -> dict:
    """یک مرحله ⇒ مرحلهٔ وارسی‌شده. ابزارِ ناشناخته ⇒ PlanError."""
    if not isinstance(raw, dict):
        raise PlanError("هر مرحله باید یک شیء باشد.")
    tool = raw.get("tool")
    spec = BY_KEY.get(tool)
    if spec is None:
        raise PlanError(f"ابزارِ «{tool}» در طراحِ خودکار نیست.")
    params_in = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    params = {p["key"]: clean_param(p, params_in.get(p["key"], p["default"])) for p in spec["params"]}
    sid = str(raw.get("id") or f"s{idx + 1}")
    sid = re.sub(r"[^a-z0-9_-]", "", sid.lower())[:20] or f"s{idx + 1}"
    step = {"id": sid, "tool": tool, "on": raw.get("on") is not False, "params": params,
            "title": str(raw.get("title") or spec["title"])[:80], "why": str(raw.get("why") or "")[:300]}
    if raw.get("ai"):
        step["ai"] = True
    return step


def clean_plan(raw) -> tuple[dict, list[str]]:
    """برنامهٔ خام ⇒ (برنامهٔ وارسی‌شده، یادداشت‌های فارسی از آنچه دور ریخته/اصلاح شد)."""
    notes: list[str] = []
    if not isinstance(raw, dict):
        raise PlanError("برنامه باید یک شیء باشد.")
    steps_in = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    if len(steps_in) > MAX_STEPS:
        notes.append(f"بیش از {MAX_STEPS} مرحله نمی‌شود؛ بقیه دور ریخته شد.")
        steps_in = steps_in[:MAX_STEPS]
    steps: list[dict] = []
    seen_single: set[str] = set()
    used_ids: set[str] = set()
    for i, s in enumerate(steps_in):
        try:
            st = clean_step(s, i)
        except PlanError as exc:
            notes.append(str(exc))
            continue
        if st["tool"] in SINGLE:
            if st["tool"] in seen_single:
                notes.append(f"«{BY_KEY[st['tool']]['title']}» یک بار کافی است؛ تکراری دور ریخته شد.")
                continue
            seen_single.add(st["tool"])
        base = st["id"]
        n = 2
        while st["id"] in used_ids:
            st["id"] = f"{base}{n}"
            n += 1
        used_ids.add(st["id"])
        steps.append(st)
    steps.sort(key=lambda s: PHASE.get(s["tool"], 12))          # پایدار: هم‌فاز به ترتیبِ نوشتن
    fmt = raw.get("format")
    mood = raw.get("mood") if raw.get("mood") in colorx.MOODS else "auto"
    plan = {"version": 1, "recipe": str(raw.get("recipe") or "free")[:30], "format": fmt if fmt in grid.FORMAT_KEYS else "square",
            "mood": mood, "variation": int(_num(raw.get("variation"), 0, 5, 0)), "title": str(raw.get("title") or "")[:80],
            "steps": steps}
    fr = next((s for s in steps if s["tool"] == "frame"), None)
    if fr and fr["on"]:
        plan["format"] = fr["params"]["format"]
    return plan, notes


def find(plan: dict, tool: str) -> dict | None:
    return next((s for s in plan["steps"] if s["tool"] == tool and s["on"]), None)


def ui_catalog() -> list[dict]:
    """کاتالوگ برای پنل (JSON)."""
    out = []
    for t in TOOLS:
        out.append({"key": t["key"], "title": t["title"], "doc": t["doc"], "deferred": bool(t.get("deferred")),
                    "params": [{k: v for k, v in p.items() if k != "help" or v} for p in t["params"]]})
    return out


def prompt_catalog() -> str:
    """کاتالوگِ فشرده برای پرامپتِ هوش مصنوعی (انگلیسی/فارسیِ کوتاه؛ کلیدها لاتین)."""
    lines = []
    for t in TOOLS:
        if t.get("deferred"):
            continue
        ps = []
        for p in t["params"]:
            if p["type"] in ("num", "int"):
                ps.append(f"{p['key']}:{p['min']}..{p['max']}")
            elif p["type"] == "enum":
                ps.append(f"{p['key']}:{'|'.join(p['options'])}")
            elif p["type"] == "bool":
                ps.append(f"{p['key']}:bool")
            elif p["type"] == COLOR:
                ps.append(f"{p['key']}:#hex|{'|'.join(PALETTE_TOKENS[:8])}")
            elif p["type"] == "font":
                ps.append(f"{p['key']}:{'|'.join([fontreg.DEFAULT] + fontreg.available())}")
            elif p["type"] == "str":
                ps.append(f"{p['key']}:text")
            elif p["type"] == "adjust":
                ps.append("adjust:{exposure,contrast,highlights,shadows,temperature,vibrance,saturation,clarity,vignette,...}")
            else:
                ps.append(f"{p['key']}")
        lines.append(f"- {t['key']} ({t['title']}): {t['doc']} params {{{', '.join(ps)}}}")
    return "\n".join(lines)
