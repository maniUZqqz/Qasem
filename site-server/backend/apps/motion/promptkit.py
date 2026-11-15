"""کیتِ پرامپت برای مدل: راهنمای فشردهٔ طراحیِ موشن + نشانه‌های سبکِ انتخابی + فقط قطعه‌هایی که به درخواست می‌خورند + چند نمونهٔ آماده
+ شمای JSON برای خروجیِ مقیدشده (Ollama format=schema؛ متیس با json_mode).

اصل: مدل ویدیو نمی‌سازد؛ «طرحِ صحنه» (JSON) می‌نویسد که قطعه‌های آماده (components.py) را کنار هم می‌گذارد و عددهایشان را تعیین می‌کند.
اندازهٔ پرامپت کران‌دار است (MAX_PROMPT_CHARS)؛ یک آزمون آن را با ایدهٔ بسیار بلند هم می‌سنجد.
"""
from __future__ import annotations

import json
import re

from . import catalog, components, motionlib, specs

MAX_PROMPT_CHARS = 9500
MAX_COMPONENTS = 8
MAX_IDEA_CHARS = 1800
CORE = ("kinetic_title", "feature_cards", "checklist")      # always offered: a headline, benefits and ticks fit nearly every request

GUIDE = """You are a motion-graphics DIRECTOR. You do not draw video: you write a SCENE PLAN (JSON) that assembles READY-MADE components and sets their numbers.
Rules of craft:
- One idea per scene. Hook in the first 1.5 s. Last scene = a call to action or the logo. Reels/Shorts total 15-30 s; each scene 3-6 s.
- Reading time: Persian needs >= 0.32 s per word + 0.7 s entrance. Titles <= 7 words, list items <= 6 words, max 5 items per list.
- Persian typography: text is RTL; animate WORDS never letters; Persian digits; no ALL CAPS; no more than 2 title lines; keep brand names as given.
- NEVER invent facts, prices, statistics, ratings or testimonials. Use only what the user gave; if a number is missing, use a text component instead of a chart.
- Prefer data components when the user gave numbers (bar_chart, line_chart, donut, counter, progress_ring, price_card); prefer steps/checklist/feature_cards for processes and benefits.
- Vary components: never repeat the same component 3 times in a row. Use a transition from the pack (wipe, push, zoom, ink, glitch, iris) sparingly, or leave it to the style.
- "narration" (optional) = what a voice says over the scene, in the same words as the on-screen text; "emphasis" = 1-3 words drawn in the accent colour.
- Keep safe zones: nothing important in the platform's UI bars (reels: top 14 %, bottom 22 %, right 10 %)."""

EASES_DOC = "ease: " + "|".join(motionlib.EASES) + " ; spring: " + "|".join(motionlib.SPRINGS) + " ; camera.move: " + "|".join(m for m in motionlib.CAMERA_MOVES if m != "none")
TRANS_DOC = "transition (into the NEXT scene): cut|fade|" + "|".join(motionlib.TRANSITION_PACK)

# ───────────────────────────────────────────── نمونه‌های آماده (few-shot)؛ متنِ فارسی، بدونِ هیچ ادعای ساختگی
EXAMPLES = [
    {"name": "promo", "uses": ("kinetic_title", "feature_cards", "social_cta", "title", "cta"), "plan": {
        "title": "معرفی سریع", "scenes": [
            {"type": "kinetic_title", "duration": 4, "text": "برنامهٔ ورزشی شما، در چند ثانیه", "emphasis": ["چند ثانیه"], "camera": {"move": "push-in", "amount": 0.4}, "narration": "برنامهٔ ورزشی شما، در چند ثانیه."},
            {"type": "feature_cards", "duration": 7, "title": "چرا؟", "cards": [{"icon": "zap", "title": "سریع", "text": "پیش‌نویس در کمتر از یک دقیقه"}, {"icon": "target", "title": "اختصاصی", "text": "برای هر ورزشکار"}], "transition": "wipe"},
            {"type": "social_cta", "duration": 4, "title": "همین حالا شروع کنید", "platform": "website", "handle": "example.ir", "button": "ورود"}]}},
    {"name": "data", "uses": ("bar_chart", "progress_ring", "counter", "stat", "title"), "plan": {
        "title": "روایتِ داده", "scenes": [
            {"type": "title", "duration": 3.5, "title": "نتیجه را ببینید", "subtitle": "سه گزینه در یک نگاه"},
            {"type": "bar_chart", "duration": 6, "title": "مقایسه", "bars": [{"label": "الف", "value": 40}, {"label": "ب", "value": 65}, {"label": "ج", "value": 90}], "unit": "٪", "transition": "push"},
            {"type": "cta", "duration": 4, "title": "بیشتر بدانید", "button": "مشاهده"}]}},
    {"name": "process", "uses": ("steps", "checklist", "icon_grid", "list"), "plan": {
        "title": "چطور کار می‌کند", "scenes": [
            {"type": "title", "duration": 3.5, "title": "در چهار قدم"},
            {"type": "steps", "duration": 8, "title": "مسیر", "steps": [{"title": "ثبت‌نام"}, {"title": "خرید"}, {"title": "تنظیم"}, {"title": "ساخت"}], "ease": "out-soft"},
            {"type": "checklist", "duration": 6, "title": "آماده‌اید؟", "items": ["مورد اول", "مورد دوم", "مورد سوم"], "transition": "iris"},
            {"type": "cta", "duration": 4, "title": "شروع کنید", "button": "ثبت‌نام"}]}},
]


def style_tokens(style_id: str) -> str:
    st = catalog.get(style_id)
    if not st:
        return ""
    p = st["palette"]
    f, m = st["font"], st["motion"]
    return (f"STYLE {st['id']} «{st['name_fa']}» ({st['name_en']}): palette bg {p['bg']} ink {p['ink']} accent {p['accent']}/{p['accent2']}/{p['accent3']}; "
            f"fonts {f['latin']}+{f['fa']}; enter {m['enter']}, transition {st['trans']['kind']} ({st['trans']['frames']}f). {st.get('about', '')[:140]}")


def _tokens(text: str) -> set:
    t = (text or "").lower().replace("‌", " ")
    return set(w for w in re.findall(r"[\w؀-ۿ]{2,}", t))


def pick_components(idea: str, *, limit: int = MAX_COMPONENTS, must=("title", "cta")) -> list:
    """قطعه‌هایی که به درخواست می‌خورند (امتیازِ هم‌پوشانیِ کلمه‌ها با «use» ِ هر قطعه)؛ همیشه یک شروع و یک پایان؛ بقیه برای تنوع."""
    words = _tokens(idea)
    has_numbers = bool(re.search(r"[\d۰-۹]", idea or ""))
    scored = []
    for cid, c in components.COMPONENTS.items():
        use = _tokens(c["use"])
        score = len(words & use) * 2
        # پیشوند/ریشه‌ای (قیمتِ ⇐ قیمت)
        score += sum(1 for w in words if len(w) > 3 and any(u.startswith(w[:4]) for u in use if len(u) > 3)) * 0.5
        if cid in ("bar_chart", "line_chart", "donut", "counter", "progress_ring", "stat") and has_numbers:
            score += 1.5
        scored.append((score, cid))
    scored.sort(key=lambda x: (-x[0], list(components.COMPONENTS).index(x[1])))
    out = list(must)
    core = [c for c in CORE if c not in out]
    for score, cid in scored:                                   # first the pieces the request asks for (keeping room for the core)
        if score > 0 and cid not in out and len(out) < limit - len(core):
            out.append(cid)
    for cid in core:                                            # then the general-purpose pieces every explainer needs
        if len(out) < limit:
            out.append(cid)
    for score, cid in scored:                                   # then whatever else fits, up to 6 pieces for variety
        if len(out) >= min(limit, 6):
            break
        if cid not in out:
            out.append(cid)
    return out[:limit]


def catalogue(ids: list) -> str:
    lines = []
    for cid in ids:
        c = components.COMPONENTS[cid]
        fields = "; ".join(f"{n}:{components.field_doc(f)}" for n, f in c["fields"].items())
        lines.append(f"- {cid} ({c['dur'][0]}-{c['dur'][2]}s, typ {c['dur'][1]}s): {c['about']}. fields: {fields}{' [overlay ok]' if c['overlay'] else ''}")
    return "\n".join(lines)


def name_lists(ids: list) -> str:
    """The names the model may use in `icon` / `emoji` fields - only when a chosen component has such a field (a bare «icon name (107 choices)» would make it guess)."""
    fields = [f for cid in ids for f in components.COMPONENTS[cid]["fields"].values()]
    out = []

    def uses(key: str) -> bool:
        for cid in ids:
            c = components.COMPONENTS[cid]
            if key in c["fields"] or any(isinstance(f, dict) and key in (f.get("fields") or {}) for f in c["fields"].values()):
                return True
        return False

    _ = fields
    if uses("icon") and components.ICON_NAMES:
        out.append("ICON NAMES (icon fields accept only these): " + ",".join(components.ICON_NAMES))
    if uses("emoji") and components.EMOJI_NAMES:
        out.append("EMOJI NAMES (sticker.emoji with kind=emoji or burst; use one at most per 2 scenes): " + ",".join(components.EMOJI_NAMES))
    return "\n".join(out)


def _examples_for(ids: list, n: int = 2) -> list:
    ranked = sorted(EXAMPLES, key=lambda e: -len(set(e["uses"]) & set(ids)))
    out = []
    for e in ranked[:n]:
        ok = [s for s in e["plan"]["scenes"] if s["type"] in ids]
        out.append(e if len(ok) == len(e["plan"]["scenes"]) else {**e, "plan": {**e["plan"], "scenes": ok or e["plan"]["scenes"][:1]}})
    return out


# ───────────────────────────────────────────── شمای JSON (خروجیِ مقیدشده)

def _prop(spec: dict) -> dict:
    k = spec["kind"]
    if k == "str":
        return {"type": "string"}
    if k == "num":
        return {"type": "number"}
    if k == "int":
        return {"type": "integer"}
    if k == "bool":
        return {"type": "boolean"}
    if k == "enum":
        return {"type": "string", "enum": list(spec["choices"])} if len(spec["choices"]) <= 16 else {"type": "string"}
    if k == "ref":
        return {"type": "string"}
    if k == "strs":
        return {"type": "array", "items": {"type": "string"}, "maxItems": spec["max_items"]}
    if k == "objs":
        return {"type": "array", "maxItems": spec["max_items"], "items": {"type": "object", "properties": {n: _prop(f) for n, f in spec["fields"].items()}}}
    return {}


def json_schema(ids: list, *, max_scenes: int = 8) -> dict:
    """شمای یک‌دست برای مدل: اجتماعِ فیلدهای قطعه‌های انتخاب‌شده (فیلدی که در دو قطعه نوعِ متفاوت دارد بی‌قید می‌شود)."""
    props: dict = {}
    for cid in ids:
        for n, f in components.COMPONENTS[cid]["fields"].items():
            if f["kind"] == "ref":
                continue                         # مدل تصویر انتخاب نمی‌کند؛ کاربر می‌دهد
            p = _prop(f)
            if n in props and props[n] != p:
                props[n] = {}
            else:
                props[n] = p
    props.pop("size", None)
    scene = {"type": "object", "properties": {
        "type": {"type": "string", "enum": list(ids)}, "duration": {"type": "number"}, "narration": {"type": "string"},
        "emphasis": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "transition": {"type": "string", "enum": ["cut", "fade", *motionlib.TRANSITION_PACK]},
        "ease": {"type": "string", "enum": list(motionlib.EASES)},
        "camera": {"type": "object", "properties": {"move": {"type": "string", "enum": [m for m in motionlib.CAMERA_MOVES if m != "none"]}, "amount": {"type": "number"}}},
        **props}, "required": ["type", "duration"]}
    return {"type": "object", "properties": {"title": {"type": "string"}, "scenes": {"type": "array", "minItems": 1, "maxItems": max_scenes, "items": scene}}, "required": ["scenes"]}


def patch_schema() -> dict:
    return {"type": "object", "properties": {
        "say": {"type": "string"},
        "ops": {"type": "array", "maxItems": patch_max(), "items": {"type": "object", "properties": {
            "op": {"type": "string", "enum": ["set", "remove", "scale", "shift", "add_scene", "remove_scene", "move_scene", "duplicate_scene", "split_scene"]},
            "path": {"type": "string"}, "value": {}, "factor": {"type": "number"}, "by": {"type": "number"}, "min": {"type": "number"}, "max": {"type": "number"},
            "index": {"type": "integer"}, "from": {"type": "integer"}, "to": {"type": "integer"}, "at": {"type": "integer"}, "scene": {"type": "object"}}, "required": ["op"]}}},
        "required": ["ops"]}


def patch_max() -> int:
    from . import patch

    return patch.MAX_OPS


# ───────────────────────────────────────────── پرامپتِ ساختنِ طرح

def build_prompt(idea: str, *, style: str, aspect: str = "9:16", lang: str = "fa", seconds: int = 24, brand_name: str = "", about: str = "",
                 platform: str = "", ids: list | None = None) -> dict:
    """⇒ {system, user, schema, ids}. ids = قطعه‌های مجاز (پیش‌فرض: pick_components)."""
    idea = (idea or "").strip()[:MAX_IDEA_CHARS]
    ids = [i for i in (ids or pick_components(idea)) if i in components.COMPONENTS][:MAX_COMPONENTS]
    ex = _examples_for(ids)
    plat = platform or motionlib.DEFAULT_PLATFORM.get(aspect, "")
    safe = motionlib.platform_safe(plat)
    system = "\n".join([
        GUIDE,
        f"Language of all on-screen text: {'Persian (Farsi)' if lang == 'fa' else 'English'}. Aspect {aspect}; platform {plat or 'none'}"
        + (f" (safe margins top {safe['top']:.0%}, bottom {safe['bottom']:.0%})" if plat else "") + f". Total about {seconds} seconds, 3 to 7 scenes.",
        style_tokens(style),
        "COMPONENTS you may use (type = id; set only the listed fields; every text field has a maximum length):", catalogue(ids), name_lists(ids),
        EASES_DOC, TRANS_DOC,
        "Reply with ONE JSON object {\"title\": str, \"scenes\": [...]} and nothing else.",
        "EXAMPLES of valid replies:", *[json.dumps(e["plan"], ensure_ascii=False, separators=(",", ":")) for e in ex],
    ])
    user = (f"Brand: {brand_name or '-'}. " + (f"About the brand (facts you may use): {about[:420]}. " if about else "") + f"\nIdea (Persian):\n{idea}")
    total = len(system) + len(user)
    if total > MAX_PROMPT_CHARS:           # کران: نمونه‌ها و سپس قطعه‌های آخر را کم می‌کنیم
        ex = ex[:1]
        ids = ids[:6]
        system = system[: system.index("COMPONENTS you may use")] + "COMPONENTS you may use:\n" + catalogue(ids) + "\n" + name_lists(ids) + "\n" + EASES_DOC + "\n" + TRANS_DOC + "\nReply with ONE JSON object and nothing else.\nEXAMPLE:\n" + \
            json.dumps(ex[0]["plan"], ensure_ascii=False, separators=(",", ":"))
    return {"system": system, "user": user, "schema": json_schema(ids), "ids": ids, "chars": len(system) + len(user)}


# ───────────────────────────────────────────── پرامپتِ ویرایشِ تکه‌ای (چت)

PATCH_GUIDE = """You edit a video SCENE PLAN with a JSON PATCH. Change ONLY what the user asked; keep everything else.
Ops: {"op":"set","path":"scenes/1/tokens/font_scale","value":1.2} | {"op":"scale","path":"scenes/1/tokens/font_scale","factor":1.15,"min":0.6,"max":1.6,"default":1}
| {"op":"shift","path":"scenes/2/duration","by":1.5} | {"op":"remove","path":"scenes/1/camera"} | {"op":"add_scene","at":2,"scene":{...}} | {"op":"remove_scene","index":2}
| {"op":"move_scene","from":1,"to":3} | {"op":"duplicate_scene","index":1} | {"op":"split_scene","index":1}.
Paths use / and 0-based scene numbers (the user says "scene 2" = index 1). Scene fields: tokens{accent,text,bg: "#rrggbb", font_scale 0.6-1.6, align, calm: true = no decorative blobs/lines behind the text}, duration 1-30, enter, exit, ease, spring,
camera{move,amount}, transition, emphasis[], overlays[], narration, plus the component's own fields. Colours: warmer = orange/yellow accent, cooler = teal/blue accent.
"bigger title" = scale tokens/font_scale x1.15-1.25; "longer" = shift duration +1..2. Reply with ONE JSON object {"say": "<one Persian sentence about what you changed>", "ops": [...]}."""


def compact_plan(spec: dict) -> str:
    keep = {k: v for k, v in spec.items() if k not in ("total_s", "safe", "assets", "brand")}
    sc = []
    for i, s in enumerate(keep.get("scenes") or []):
        s = {k: v for k, v in s.items() if k != "cues"}
        sc.append({"i": i, **s})
    keep["scenes"] = sc
    out = json.dumps(keep, ensure_ascii=False, separators=(",", ":"))
    return out[:6000]


def build_patch_prompt(spec: dict, request: str) -> dict:
    user = f"PLAN:\n{compact_plan(spec)}\n\nREQUEST (Persian): {(request or '').strip()[:500]}"
    return {"system": PATCH_GUIDE, "user": user, "schema": patch_schema(), "chars": len(PATCH_GUIDE) + len(user)}


def style_gallery_hint(style_id: str) -> dict:
    st = catalog.get(style_id) or {}
    return {"id": style_id, "name": st.get("name_fa", ""), "palette": st.get("palette", {})}


__all__ = ["build_prompt", "build_patch_prompt", "pick_components", "json_schema", "patch_schema", "MAX_PROMPT_CHARS", "specs"]
