"""ویرایشِ تکه‌ای (patch): «تیتر بزرگ‌تر شود» فقط همان صحنه/فیلد را عوض می‌کند — JSON منبعِ حقیقت است.

یک patch = فهرستی از عملیات روی طرح. همه‌چیز پیش از اعمال دوباره با specs.normalize_spec اعتبارسنجی می‌شود (اتمی: یا همه یا هیچ) و برگشت‌پذیر است
(plans.py هر نسخه را نگه می‌دارد). سه منبعِ patch: دکمه‌های سریعِ هر صحنه، چتِ فارسی (مدل ⇒ patch؛ بدونِ مدل ⇒ قاعده‌های این فایل) و اصلاحِ خودکارِ QA.

عملیات:
  {"op":"set","path":"scenes/1/tokens/font_scale","value":1.2}      مقدار را می‌گذارد (مسیر با /؛ عددِ بخش = شمارهٔ عنصرِ فهرست، از ۰)
  {"op":"remove","path":"scenes/1/camera"}                           کلید را برمی‌دارد
  {"op":"scale","path":"scenes/1/tokens/font_scale","factor":1.15,"min":0.6,"max":1.6,"default":1}   عدد را ضرب می‌کند
  {"op":"shift","path":"scenes/1/duration","by":1.5}                  عدد را جابه‌جا می‌کند
  {"op":"add_scene","at":2,"scene":{...}} · {"op":"remove_scene","index":2} · {"op":"move_scene","from":1,"to":3} · {"op":"duplicate_scene","index":1}
  {"op":"split_scene","index":1}                                      صحنهٔ پرآیتم را به دو صحنه (نیمهٔ اول/دوم) می‌شکند
"""
from __future__ import annotations

import colorsys
import copy
import re

from . import catalog, components, motionlib, specs

MAX_OPS = 12
SPLITTABLE = ("list", "checklist", "feature_cards", "icon_grid", "tags")
TOP_KEYS = {"style", "aspect", "fps", "lang", "digits", "platform", "intensity", "transition", "brand", "captions", "audio", "scenes"}


class PatchError(ValueError):
    """patch نامعتبر؛ متنِ فارسی."""


# ───────────────────────────────────────────── مسیر

def _parts(path: str) -> list:
    if not isinstance(path, str) or not path.strip("/"):
        raise PatchError("مسیرِ تغییر خالی است.")
    out: list = []
    for p in path.strip("/").split("/"):
        out.append(int(p) if re.fullmatch(r"\d{1,3}", p) else p)
    if out[0] not in TOP_KEYS:
        raise PatchError(f"مسیرِ «{path}» را نمی‌شناسم.")
    return out


def _walk(root, parts: list, create: bool):
    cur = root
    for i, p in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur):
                raise PatchError(f"عنصرِ {p + 1} در مسیر وجود ندارد.")
            cur = cur[p]
        else:
            if not isinstance(cur, dict):
                raise PatchError(f"مسیرِ «{'/'.join(map(str, parts))}» معتبر نیست.")
            if p not in cur or cur[p] is None:
                if not create:
                    raise PatchError(f"«{p}» وجود ندارد.")
                cur[p] = [] if isinstance(nxt, int) else {}
            cur = cur[p]
    return cur


def _get(root, parts: list, default=None):
    cur = root
    for p in parts:
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur):
                return default
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
    return cur


def _set(root, parts: list, value) -> None:
    cur = _walk(root, parts, True)
    last = parts[-1]
    if isinstance(last, int):
        if not isinstance(cur, list) or last > len(cur):
            raise PatchError("شمارهٔ عنصر در فهرست معتبر نیست.")
        if last == len(cur):
            cur.append(value)
        else:
            cur[last] = value
    else:
        if not isinstance(cur, dict):
            raise PatchError("مسیر معتبر نیست.")
        cur[last] = value


def _remove(root, parts: list) -> None:
    cur = _walk(root, parts, False)
    last = parts[-1]
    if isinstance(last, int):
        if isinstance(cur, list) and last < len(cur):
            del cur[last]
    elif isinstance(cur, dict):
        cur.pop(last, None)


# ───────────────────────────────────────────── عملیات

def _idx(plan: dict, v, name="index") -> int:
    try:
        i = int(v)
    except (TypeError, ValueError):
        raise PatchError(f"«{name}» عدد نیست.")
    if not 0 <= i < len(plan["scenes"]):
        raise PatchError(f"صحنهٔ {i + 1} وجود ندارد (طرح {len(plan['scenes'])} صحنه دارد).")
    return i


def split_scene(sc: dict) -> list:
    """صحنهٔ پرآیتم ⇒ دو صحنهٔ هم‌نوع (آیتم‌ها نصف‌نصف)؛ اگر آیتمی نداشت ⇒ همان صحنه."""
    if sc.get("type") not in SPLITTABLE:        # a chart, a table or a sequence loses its meaning in halves: only independent items are split
        return [sc]
    comp = components.get(sc.get("type", ""))
    key = (comp or {}).get("items")
    if not key and comp:
        key = next((k for k, f in comp["fields"].items() if f["kind"] in ("strs", "objs")), None)
    items = sc.get(key) if key else None
    if not isinstance(items, list) or len(items) < 2:
        return [sc]
    half = (len(items) + 1) // 2
    a, b = copy.deepcopy(sc), copy.deepcopy(sc)
    a[key], b[key] = items[:half], items[half:]
    for part in (a, b):
        part["duration"] = max(specs.MIN_SCENE_S + 2.0, round(float(sc.get("duration", 5)) * 0.62, 1))
        part.pop("cues", None)
    if "narration" in sc:
        words = sc["narration"].split()
        mid = max(1, len(words) // 2)
        a["narration"], b["narration"] = " ".join(words[:mid]), " ".join(words[mid:])
        if not b["narration"]:
            b.pop("narration")
    b.pop("overlays", None)
    if b.get("title"):
        b["title"] = b["title"]
    return [a, b]


def _apply_one(plan: dict, op: dict) -> None:
    kind = op.get("op")
    if kind == "set":
        _set(plan, _parts(op.get("path")), copy.deepcopy(op.get("value")))
    elif kind == "remove":
        _remove(plan, _parts(op.get("path")))
    elif kind in ("scale", "shift"):
        parts = _parts(op.get("path"))
        cur = _get(plan, parts, None)
        if not isinstance(cur, (int, float)) or isinstance(cur, bool):
            cur = op.get("default")
        if not isinstance(cur, (int, float)):
            raise PatchError("این مقدار عدد نیست.")
        try:
            new = cur * float(op["factor"]) if kind == "scale" else cur + float(op["by"])
        except (KeyError, TypeError, ValueError):
            raise PatchError("ضریب/مقدارِ تغییر معتبر نیست.")
        lo, hi = op.get("min"), op.get("max")
        if isinstance(lo, (int, float)):
            new = max(lo, new)
        if isinstance(hi, (int, float)):
            new = min(hi, new)
        _set(plan, parts, round(new, 3))
    elif kind == "add_scene":
        sc = op.get("scene")
        if not isinstance(sc, dict):
            raise PatchError("صحنهٔ افزودنی معتبر نیست.")
        at = op.get("at", len(plan["scenes"]))
        at = max(0, min(len(plan["scenes"]), int(at)))
        plan["scenes"].insert(at, copy.deepcopy(sc))
    elif kind == "remove_scene":
        if len(plan["scenes"]) <= 1:
            raise PatchError("آخرین صحنه را نمی‌شود حذف کرد.")
        del plan["scenes"][_idx(plan, op.get("index"))]
    elif kind == "move_scene":
        a, b = _idx(plan, op.get("from"), "from"), _idx(plan, op.get("to"), "to")
        plan["scenes"].insert(b, plan["scenes"].pop(a))
    elif kind == "duplicate_scene":
        i = _idx(plan, op.get("index"))
        c = copy.deepcopy(plan["scenes"][i])
        c.pop("cues", None)
        plan["scenes"].insert(i + 1, c)
    elif kind == "split_scene":
        i = _idx(plan, op.get("index"))
        parts = split_scene(plan["scenes"][i])
        if len(parts) < 2:
            raise PatchError("این صحنه آیتمِ کافی برای تقسیم ندارد.")
        plan["scenes"][i:i + 1] = parts
    else:
        raise PatchError(f"عملیاتِ «{kind}» را نمی‌شناسم.")


def apply_patch(spec: dict, ops, *, max_total: float = specs.MAX_TOTAL_S_NODE, notes: list | None = None) -> dict:
    """طرحِ تازهٔ اعتبارسنجی‌شده؛ spec ورودی دست‌نخورده می‌ماند. خطا ⇒ PatchError (هیچ تغییری اعمال نمی‌شود)."""
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        raise PatchError("تغییری برای اعمال داده نشد.")
    if len(ops) > MAX_OPS:
        raise PatchError(f"در هر بار حداکثر {MAX_OPS} تغییر.")
    work = copy.deepcopy({k: v for k, v in spec.items() if k not in ("total_s", "safe")})
    for op in ops:
        if not isinstance(op, dict):
            raise PatchError("هر تغییر باید یک شیء باشد.")
        _apply_one(work, op)
    try:
        out = specs.normalize_spec(work, max_total=max_total, notes=notes)
    except specs.SpecError as exc:
        raise PatchError(f"پس از اعمالِ تغییر طرح معتبر نبود: {exc}") from exc
    if _strip(out) == _strip(spec):
        raise PatchError("این تغییر چیزی را عوض نکرد (فیلدِ نامعتبر یا مقدارِ تکراری).")
    return out


def _strip(s: dict) -> dict:
    return {k: v for k, v in s.items() if k not in ("total_s", "safe")}


def diff_summary(before: dict, after: dict) -> list:
    """فهرستِ کوتاهِ فارسی از آنچه عوض شده (برای نمایش به کاربر)."""
    out = []
    if len(before["scenes"]) != len(after["scenes"]):
        out.append(f"تعدادِ صحنه‌ها {len(before['scenes'])} ⇐ {len(after['scenes'])}")
    for i, (a, b) in enumerate(zip(before["scenes"], after["scenes"])):
        ch = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        if ch:
            out.append(f"صحنهٔ {i + 1}: " + "، ".join(ch))
    for k in ("style", "aspect", "platform", "transition", "intensity", "captions", "audio", "brand"):
        if before.get(k) != after.get(k):
            out.append(f"«{k}» عوض شد")
    return out


# ───────────────────────────────────────────── قاعده‌های فارسی (بدونِ هوش مصنوعی)

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ORDINALS = {"اول": 1, "اولین": 1, "یکم": 1, "دوم": 2, "دومین": 2, "سوم": 3, "سومین": 3, "چهارم": 4, "چهارمین": 4, "پنجم": 5, "پنجمین": 5,
            "ششم": 6, "ششمین": 6, "هفتم": 7, "هشتم": 8, "نهم": 9, "دهم": 10}
COLOR_WORDS = {
    "قرمز": "#e63946", "نارنجی": "#f77f00", "زرد": "#ffbe0b", "سبز": "#2a9d5c", "آبی": "#1d6fd1", "بنفش": "#7b2cbf", "صورتی": "#ef476f",
    "فیروزه": "#126f85", "سرمه": "#163f75", "سفید": "#ffffff", "مشکی": "#111111", "سیاه": "#111111", "طلایی": "#d4a017", "نقره": "#b8c0cc",
    "قهوه": "#7b4a2d", "خاکستری": "#6b7280",
}
STYLE_ALIAS = {}


def _norm(t: str) -> str:
    t = (t or "").translate(_FA_DIGITS)
    t = t.replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("‍", "")
    t = re.sub(r"[ً-ٟ]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _targets(text: str, n: int) -> list:
    """کدام صحنه‌ها؟ «صحنهٔ دوم»، «صحنه ۳»، «اولین صحنه»، «آخرین صحنه»، «همهٔ صحنه‌ها»؛ پیش‌فرض: همه (یا صحنهٔ اول وقتی از «تیتر» حرف زده)."""
    t = _norm(text)
    if re.search(r"(همه|تمام|هر)\s*(ی)?\s*صحنه", t) or "همه جا" in t:
        return list(range(n))
    if re.search(r"آخر(ین)?\s*(ی)?\s*صحنه|صحنه\s*(ی)?\s*آخر", t):
        return [n - 1]
    m = re.search(r"صحنه\s*(?:ی|ء)?\s*(\d{1,2})", t) or re.search(r"(\d{1,2})\s*(?:م|ُم)?\s*صحنه", t)
    if m and 1 <= int(m.group(1)) <= n:
        return [int(m.group(1)) - 1]
    for w, k in ORDINALS.items():
        if re.search(rf"(?:صحنه\s*(?:ی|ء)?\s*{w}\b|\b{w}\s*(?:ین)?\s*صحنه)", t) and k <= n:
            return [k - 1]
    if re.search(r"(تیتر|عنوان)", t):          # «تیتر بزرگ‌تر شود» = تیترِ ویدیو = صحنهٔ اول
        return [0]
    return []


def _warm(hexc: str, amount: float) -> str:
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    # گرم‌تر = نزدیک‌شدن به رنگ‌مایهٔ ۰٫۰۸ (نارنجی)؛ سردتر = ۰٫۵۵ (آبیِ فیروزه‌ای)
    goal = 0.08 if amount > 0 else 0.55
    d = ((goal - h + 0.5) % 1.0) - 0.5
    h = (h + d * min(1.0, abs(amount))) % 1.0
    s = max(s, 0.55)
    v = max(v, 0.6)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def rules_patch(text: str, plan: dict) -> dict:
    """فرمانِ فارسی ⇒ {"ops": [...], "say": "جملهٔ فارسی"} یا {"ops": [], "say": "نفهمیدم …"}. فقط عبارت‌های رایج."""
    t = _norm(text)
    n = len(plan["scenes"])
    tg = _targets(t, n)
    ops: list = []
    say = ""
    over = "همهٔ صحنه‌ها" if not tg else ("صحنهٔ " + "، ".join(str(i + 1) for i in tg))
    ids = tg or list(range(n))

    def per(fn):
        for i in ids:
            fn(i)

    if re.search(r"(حذف|پاک)\s*(کن|شود|بشه)?.*صحنه|صحنه.*(حذف|پاک)", t) and tg and n > 1:
        for i in sorted(tg, reverse=True):
            ops.append({"op": "remove_scene", "index": i})
        say = f"{over} حذف شد."
    elif re.search(r"(تکرار|کپی|دوباره بیاور)", t) and tg:
        ops.append({"op": "duplicate_scene", "index": tg[0]})
        say = f"{over} تکرار شد."
    elif re.search(r"(جابه ?جا|عوض|ببر|بیار|منتقل)", t) and re.search(r"صحنه", t) and not re.search(r"(بزرگ|کوچک|رنگ)", t):
        nums = [int(x) for x in re.findall(r"\d{1,2}", t)]
        words = [k for w, k in ORDINALS.items() if re.search(rf"\b{w}\b", t)]
        pair = (nums + words)[:2]
        if re.search(r"(اول|ابتدا|شروع)", t) and len(pair) >= 1 and not (len(pair) == 2 and pair[1] != 1):
            pair = [pair[0], 1]
        elif re.search(r"(آخر|انتها|پایان)", t) and len(pair) >= 1:
            pair = [pair[0], n]
        if len(pair) == 2 and all(1 <= p <= n for p in pair) and pair[0] != pair[1]:
            ops.append({"op": "move_scene", "from": pair[0] - 1, "to": pair[1] - 1})
            say = f"صحنهٔ {pair[0]} به جای صحنهٔ {pair[1]} رفت."
    if not ops and re.search(r"بزرگ ?تر|درشت ?تر|بزرگتر|درشتتر|بیشتر.*(اندازه|فونت)|اندازه.*بیشتر", t):
        per(lambda i: ops.append({"op": "scale", "path": f"scenes/{i}/tokens/font_scale", "factor": 1.18, "min": 0.6, "max": 1.6, "default": 1}))
        say = f"متنِ {over} بزرگ‌تر شد."
    elif not ops and re.search(r"کوچک ?تر|ریز ?تر|کوچکتر|ریزتر", t):
        per(lambda i: ops.append({"op": "scale", "path": f"scenes/{i}/tokens/font_scale", "factor": 0.85, "min": 0.6, "max": 1.6, "default": 1}))
        say = f"متنِ {over} کوچک‌تر شد."
    elif not ops and re.search(r"گرم ?تر|گرمتر", t):
        for i in ids:
            cur = (plan["scenes"][i].get("tokens") or {}).get("accent") or _brand_accent(plan)
            ops.append({"op": "set", "path": f"scenes/{i}/tokens/accent", "value": _warm(cur, 0.85)})
        say = f"رنگِ تأکیدِ {over} گرم‌تر شد."
    elif not ops and re.search(r"سرد ?تر|سردتر", t):
        for i in ids:
            cur = (plan["scenes"][i].get("tokens") or {}).get("accent") or _brand_accent(plan)
            ops.append({"op": "set", "path": f"scenes/{i}/tokens/accent", "value": _warm(cur, -0.7)})
        say = f"رنگِ تأکیدِ {over} سردتر شد."
    elif not ops and re.search(r"رنگ", t):
        for w, hx in COLOR_WORDS.items():
            if w in t:
                what = "bg" if re.search(r"(زمینه|پس ?زمینه|بک ?گراند)", t) else "text" if re.search(r"(متن|نوشته|تیتر|فونت)", t) else "accent"
                per(lambda i: ops.append({"op": "set", "path": f"scenes/{i}/tokens/{what}", "value": hx}))
                say = f"رنگِ {'زمینه' if what == 'bg' else 'متن' if what == 'text' else 'تأکید'}ِ {over} {w} شد."
                break
    if not ops and re.search(r"(طولانی ?تر|بیشتر نگه|مدت.*(بیشتر|زیاد)|کندتر|آهسته ?تر)", t):
        per(lambda i: ops.append({"op": "shift", "path": f"scenes/{i}/duration", "by": 1.5, "min": 1, "max": 30}))
        say = f"مدتِ {over} ۱٫۵ ثانیه بیشتر شد."
    elif not ops and re.search(r"(کوتاه ?تر|تندتر|سریع ?تر|مدت.*(کمتر|کم))", t):
        per(lambda i: ops.append({"op": "shift", "path": f"scenes/{i}/duration", "by": -1.0, "min": 1, "max": 30}))
        say = f"مدتِ {over} ۱ ثانیه کمتر شد."
    if not ops and re.search(r"(بدون|حذف).*(حرکتِ? ?دوربین|دوربین)", t):
        per(lambda i: ops.append({"op": "remove", "path": f"scenes/{i}/camera"}))
        say = f"حرکتِ دوربینِ {over} برداشته شد."
    elif not ops and re.search(r"(دوربین|زوم|نزدیک)", t):
        mv = "pull-out" if re.search(r"(دور ?تر|دور شو|دور کن|عقب)", t) else "pan-right" if "پن" in t else "push-in"
        per(lambda i: ops.append({"op": "set", "path": f"scenes/{i}/camera", "value": {"move": mv, "amount": 0.6}}))
        say = f"دوربین در {over} حرکت می‌کند ({motionlib.CAMERA_MOVES[mv]})."
    if not ops:
        for s in catalog.STYLES:
            if s["name_fa"] and _norm(s["name_fa"]) in t:
                ops.append({"op": "set", "path": "style", "value": s["id"]})
                say = f"سبک «{s['name_fa']}» شد."
                break
    if not ops and re.search(r"(زیرنویس)", t):
        ops.append({"op": "set", "path": "captions", "value": {"on": not re.search(r"(بدون|حذف|بردار|خاموش)", t), "position": "lower"}})
        say = "زیرنویسِ کلمه‌به‌کلمه تنظیم شد."
    if not ops and re.search(r"(گوینده|صدا|روایت|دوبله)", t):
        on = not re.search(r"(بدون|حذف|بردار|خاموش)", t)
        ops.append({"op": "set", "path": "audio/voice", "value": {"on": on, "voice_id": "auto"}} if on else {"op": "remove", "path": "audio/voice"})
        say = "گوینده روشن شد." if on else "گوینده برداشته شد."
    if not ops and re.search(r"(موسیقی|آهنگ)", t):
        on = not re.search(r"(بدون|حذف|بردار|خاموش)", t)
        ops.append({"op": "set", "path": "audio/music", "value": {"on": True, "ref": "auto"}} if on else {"op": "remove", "path": "audio/music"})
        say = "موسیقیِ زمینه روشن شد." if on else "موسیقی برداشته شد."
    if not ops:
        for key, pid in (("ریلز", "reels"), ("استوری", "story"), ("تیک ?تاک", "tiktok"), ("شورتس", "shorts")):
            if re.search(key, t):
                ops.append({"op": "set", "path": "platform", "value": pid})
                say = f"چیدمان برای {motionlib.PLATFORMS[pid]['name']} تنظیم شد (فاصله از نوارهای برنامه)."
                break
    if not ops:
        return {"ops": [], "say": "منظورتان را نفهمیدم. مثلاً بگویید: «تیتر بزرگ‌تر شود»، «رنگِ صحنهٔ دوم گرم‌تر»، «صحنهٔ سوم ۲ ثانیه بیشتر»، «زیرنویس اضافه کن»."}
    return {"ops": ops[:MAX_OPS], "say": say}


def _brand_accent(plan: dict) -> str:
    cols = (plan.get("brand") or {}).get("colors") or []
    if cols:
        return cols[0]
    st = catalog.get(plan.get("style", "")) or {}
    return (st.get("palette") or {}).get("accent", "#126f85")
