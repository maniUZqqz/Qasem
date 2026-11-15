"""«طرحِ صحنه» (Scene Plan) نسخهٔ ۲ — تنها منبعِ حقیقتِ ویدیو؛ اعتبارسنجی و پاک‌سازیِ سمتِ سرور.

همان چیزی که فرمِ قالبی می‌سازد، هوش مصنوعی می‌نویسد و کاربر در «کارت‌های صحنه» یا JSONِ خام ویرایش می‌کند. هیچ چیزِ خارج از این فهرست به رندر
نمی‌رسد: نوعِ قطعه (components.py)، کلیدهای هر قطعه با سقفِ طولشان، تعدادِ صحنه، مدت، نسبتِ تصویر، گذار/حرکت/منحنی از نام‌های ثابتِ motionlib.py.

طرح (نسخهٔ ۲):
  version, style, aspect, fps, lang, digits, platform (⇒ safe)، brand, intensity, transition, captions{on,position}, audio{voice,music,sfx,beat_sync}, bare,
  scenes[]: type, duration, <فیلدهای قطعه>, enter, exit, ease, spring, emphasis[], camera{move,amount}, transition, tokens{accent,text,bg,font_scale,align,calm},
            overlays[]{type,at,dur,anchor,dx,dy,<فیلدها>}, narration, cues[]{w,s,e}, sfx[]{at,kind,level_db}

طرح‌های نسخهٔ ۱ (بدونِ این کلیدها) بی‌تغییر معتبرند و با upgrade به ۲ می‌روند.
"""
from __future__ import annotations

import re

from . import catalog, components, motionlib, timeline

SCHEMA_VERSION = 2
ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
ASPECT_LABELS = {"9:16": "عمودی (ریلز/استوری)", "1:1": "مربع", "4:5": "پرتره (پست)", "16:9": "افقی (یوتیوب)"}
#: کیفیتِ خروجی = ضلعِ کوتاه (پیکسل) ⇒ مقیاس نسبت به ۱۰۸۰
QUALITY = {"360": 360 / 1080, "540": 0.5, "720": 720 / 1080, "1080": 1.0}
DEFAULT_QUALITY = "720"

MAX_SCENES = 14
MIN_SCENE_S, MAX_SCENE_S = 1.0, 30.0
MAX_TOTAL_S_NODE = 120.0
MAX_TOTAL_S_SITE = 60.0
FPS_CHOICES = (24, 25, 30, 50, 60)
MAX_OVERLAYS = 4
MAX_CUES = 240
MAX_SFX = 6
MAX_NARRATION = 700
ANCHORS = ("top", "upper", "center", "lower", "bottom", "top-start", "top-end", "bottom-start", "bottom-end")
SFX_KINDS = ("whoosh", "pop", "tick", "hit", "rise")
CAPTION_POSITIONS = ("lower", "center", "upper", "bottom")

ITEM_MAX = components.ITEM_MAX
REF_RE = re.compile(r"^(upload|pimg|photo|gimg):\d{1,12}$|^store-logo$|^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]{16,}$")
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
VOICE_RE = re.compile(r"^(auto|[a-z0-9_]+:[\w.\- ]{1,60})$")
MUSIC_RE = re.compile(r"^(auto|audio:\d{1,12})$")

SCENE_LABELS_FA = {k: c["label"] for k, c in components.COMPONENTS.items()}

#: «قالب»‌های صفحه: یک صحنه یا یک زنجیره، با متنِ نمونه (فارسی) برای شروع
TEMPLATES = [
    {"id": "title", "name": "کارتِ عنوان", "scenes": ["title"]},
    {"id": "list", "name": "فهرست / مراحل", "scenes": ["list"]},
    {"id": "quote", "name": "نقل‌قول", "scenes": ["quote"]},
    {"id": "stat", "name": "عددِ بزرگ", "scenes": ["stat"]},
    {"id": "compare", "name": "قبل و بعد", "scenes": ["compare"]},
    {"id": "product", "name": "معرفیِ محصول", "scenes": ["product"]},
    {"id": "logo", "name": "لوگو (استینگ)", "scenes": ["logo"]},
    {"id": "app", "name": "نمایشِ اپ در قابِ گوشی", "scenes": ["app"]},
    {"id": "explainer", "name": "توضیحیِ چندصحنه‌ای", "scenes": ["title", "list", "stat", "cta"]},
    {"id": "promo", "name": "تیزرِ معرفی (تیتر، ویژگی‌ها، قیمت، دعوت)", "scenes": ["kinetic_title", "feature_cards", "price_card", "social_cta"]},
    {"id": "data_story", "name": "روایتِ داده (نمودار + حلقه + دعوت)", "scenes": ["title", "bar_chart", "progress_ring", "cta"]},
    {"id": "how_it_works", "name": "چطور کار می‌کند (مراحل + چک‌لیست)", "scenes": ["title", "steps", "checklist", "cta"]},
]

SAMPLE_SCENES = {k: dict(c["sample"]) for k, c in components.COMPONENTS.items()}


class SpecError(ValueError):
    """خطای اعتبارسنجی؛ متنِ فارسی برای کاربر."""


def _note(notes, msg: str) -> None:
    if notes is not None and msg not in notes:
        notes.append(msg)


def _s(v, n: int, field: str = "") -> str:
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise SpecError(f"مقدارِ «{field}» باید متن باشد.")
    s = str(v).replace("\r", "").replace("\x00", "").strip()
    s = re.sub(r"[‪-‮⁦-⁩]", "", s)         # کنترل‌های جهت‌دهیِ پنهان
    return s[:n]


def _ref(v, field: str) -> str:
    s = _s(v, 4_000_000, field)
    if not s:
        return ""
    if not REF_RE.match(s):
        raise SpecError(f"منبعِ تصویرِ «{field}» معتبر نیست (باید از «دارایی‌ها»، عکسِ محصول یا لوگوی فروشگاه باشد).")
    return s


def _num(v, lo: float, hi: float, default=None, notes=None, field: str = ""):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    c = max(lo, min(hi, x))
    if c != x:
        _note(notes, f"«{field}» به بازهٔ مجاز ({lo:g} تا {hi:g}) برگردانده شد.")
    return c


def _hex(v) -> str | None:
    if isinstance(v, str) and HEX_RE.match(v.strip()):
        t = v.strip()
        return (t if t.startswith("#") else "#" + t).lower()
    return None


# ───────────────────────────────────────────── یک فیلدِ قطعه

def _field(spec: dict, v, name: str, notes=None):
    """مقدارِ پاک‌شده، یا None = این فیلد نیاید."""
    k = spec["kind"]
    if k == "str":
        return _s(v, spec["max"], name)
    if k == "ref":
        return _ref(v, name) or None
    if k == "bool":
        return bool(v)
    if k == "int":
        try:
            return int(max(spec["min"], min(spec["max"], int(float(v)))))
        except (TypeError, ValueError):
            return None
    if k == "num":
        return _num(v, spec["min"], spec["max"], None, notes, name)
    if k == "enum":
        t = _s(v, 40, name)
        if t in spec["choices"]:
            return t
        if t:
            _note(notes, f"«{name}»: مقدارِ «{t}» مجاز نبود و کنار گذاشته شد.")
        return None
    if k == "strs":
        if not isinstance(v, (list, tuple)):
            raise SpecError(f"«{name}» باید فهرست باشد.")
        items = [_s(x, spec["item_max"], name) for x in v][: spec["max_items"]]
        return [x for x in items if x]
    if k == "objs":
        if not isinstance(v, (list, tuple)):
            raise SpecError(f"«{name}» باید فهرست باشد.")
        out = []
        first = next(iter(spec["fields"]))
        for row in list(v)[: spec["max_items"]]:
            if isinstance(row, (str, int, float)) and not isinstance(row, bool):
                row = {first: row}
            if not isinstance(row, dict):
                continue
            o = {}
            for fn, fs in spec["fields"].items():
                if fn in row:
                    fv = _field(fs, row[fn], f"{name}.{fn}", notes)
                    if fv not in (None, "", []):
                        o[fn] = fv
            if o:
                out.append(o)
        return out
    return None


def _fields(comp: dict, sc: dict, notes=None) -> dict:
    out = {}
    for key, spec in comp["fields"].items():
        if key not in sc:
            continue
        v = _field(spec, sc[key], key, notes)
        if spec["kind"] in ("str", "ref") and not v:
            if spec["kind"] == "str" and key in sc and v == "":
                out[key] = ""
            continue
        if v is None:
            continue
        out[key] = v
    return out


def _has(out: dict, key: str) -> bool:
    v = out.get(key)
    return bool(v) or v == 0 and isinstance(v, (int, float)) and not isinstance(v, bool) and key in ("value", "score", "from")


def _check_need(comp: dict, out: dict, where: str) -> None:
    need = comp["need"]
    if not need:
        return
    if not any(_has(out, k) for k in need):
        raise SpecError(f"{where} («{comp['label']}») «{' یا '.join(need)}» ندارد.")


# ───────────────────────────────────────────── یک صحنه

def _tokens(t, notes) -> dict:
    out: dict = {}
    if not isinstance(t, dict):
        return out
    for k in ("accent", "text", "bg"):
        if t.get(k) is not None:
            h = _hex(t[k])
            if h:
                out[k] = h
            else:
                _note(notes, f"رنگِ «{k}» معتبر نبود (باید #RRGGBB باشد).")
    if t.get("font_scale") is not None:
        fs = _num(t["font_scale"], 0.6, 1.6, None, notes, "font_scale")
        if fs is not None:
            out["font_scale"] = round(fs, 2)
    if t.get("align") in motionlib.ALIGNS:
        out["align"] = t["align"]
    if t.get("calm") is not None:                     # «آرام»: نقش‌های تزئینیِ پس‌زمینه (لکه‌ها، خط‌ها) برای این صحنه خاموش می‌شوند؛ خواناییِ متن
        out["calm"] = bool(t["calm"]) if not isinstance(t["calm"], str) else t["calm"].strip().lower() in ("1", "true", "yes", "on")
    return out


def _cues(raw, dur: float) -> list:
    out = []
    if not isinstance(raw, (list, tuple)):
        return out
    for c in list(raw)[:MAX_CUES]:
        if not isinstance(c, dict):
            continue
        w = _s(c.get("w"), 40)
        s, e = _num(c.get("s"), 0, 600), _num(c.get("e"), 0, 600)
        if w and s is not None and e is not None and e >= s:
            out.append({"w": w, "s": round(s, 3), "e": round(e, 3)})
    return out


def normalize_overlay(ov, idx: int, dur: float, notes=None) -> dict:
    if not isinstance(ov, dict):
        raise SpecError(f"رویهٔ {idx + 1} معتبر نیست.")
    typ = _s(ov.get("type"), 24)
    comp = components.get(typ)
    if not comp or not comp["overlay"]:
        raise SpecError(f"«{typ}» را نمی‌شود روی صحنه گذاشت (مجاز: {'، '.join(components.OVERLAY_IDS)}).")
    out = {"type": typ}
    at = _num(ov.get("at"), 0, max(0.0, dur - 0.3), 0.0, notes, "at")
    out["at"] = round(at or 0.0, 2)
    if ov.get("dur") is not None:
        d = _num(ov["dur"], 0.5, MAX_SCENE_S, None, notes, "dur")
        if d is not None:
            out["dur"] = round(d, 2)
    anchor = _s(ov.get("anchor"), 20)
    if anchor in ANCHORS:
        out["anchor"] = anchor
    for k in ("dx", "dy"):
        if ov.get(k) is not None:
            x = _num(ov[k], -0.5, 0.5, None, notes, k)
            if x is not None:
                out[k] = round(x, 3)
    out.update(_fields(comp, ov, notes))
    _check_need(comp, out, f"رویهٔ {idx + 1}")
    return out


def normalize_scene(sc: dict, idx: int = 0, notes=None) -> dict:
    if not isinstance(sc, dict):
        raise SpecError(f"صحنهٔ {idx + 1} معتبر نیست.")
    typ = _s(sc.get("type"), 24) or "title"
    comp = components.get(typ)
    if comp is None:
        raise SpecError(f"نوعِ صحنهٔ «{typ}» را نمی‌شناسم (مجاز: {'، '.join(components.SCENE_IDS)}).")
    try:
        dur0 = float(sc.get("duration", 4))
    except (TypeError, ValueError):
        raise SpecError(f"مدتِ صحنهٔ {idx + 1} عدد نیست.")
    dur = max(MIN_SCENE_S, min(MAX_SCENE_S, dur0))
    if dur != dur0:
        _note(notes, f"مدتِ صحنهٔ {idx + 1} به بازهٔ {MIN_SCENE_S:g} تا {MAX_SCENE_S:g} ثانیه برگردانده شد.")
    out: dict = {"type": typ, "duration": round(dur, 2)}
    out.update(_fields(comp, sc, notes))
    _check_need(comp, out, f"صحنهٔ {idx + 1}")
    # ── ویژگی‌های مشترکِ هر صحنه: حرکت، منحنی، دوربین، گذار، رنگ، رویه، گفتار
    for key, table in (("enter", motionlib.ENTER_KINDS), ("exit", motionlib.EXIT_KINDS), ("ease", motionlib.EASES), ("spring", motionlib.SPRINGS)):
        if sc.get(key) not in (None, ""):
            v = _s(sc[key], 30, key)
            if v in table:
                out[key] = v
            else:
                _note(notes, f"صحنهٔ {idx + 1}: «{key}» = «{v}» را نمی‌شناسم و کنار گذاشتم.")
    if sc.get("transition") not in (None, ""):
        v = _s(sc["transition"], 20, "transition")
        if v in catalog.TRANS_KINDS:
            out["transition"] = v
        else:
            _note(notes, f"صحنهٔ {idx + 1}: گذارِ «{v}» را نمی‌شناسم و کنار گذاشتم.")
    if isinstance(sc.get("emphasis"), (list, tuple)):
        em = [_s(w, 24, "emphasis") for w in sc["emphasis"][:8]]
        em = [w for w in em if w]
        if em:
            out["emphasis"] = em
    cam = sc.get("camera")
    if isinstance(cam, dict) and cam.get("move") in motionlib.CAMERA_MOVES and cam.get("move") != "none":
        out["camera"] = {"move": cam["move"], "amount": round(_num(cam.get("amount"), 0, 1, 0.5, notes, "camera.amount"), 2)}
    tok = _tokens(sc.get("tokens"), notes)
    if tok:
        out["tokens"] = tok
    if isinstance(sc.get("overlays"), (list, tuple)):
        ovs = [normalize_overlay(o, i, dur, notes) for i, o in enumerate(sc["overlays"][:MAX_OVERLAYS])]
        if ovs:
            out["overlays"] = ovs
    if sc.get("narration"):
        nar = _s(sc["narration"], MAX_NARRATION, "narration")
        if nar:
            out["narration"] = nar
    cues = _cues(sc.get("cues"), dur)
    if cues:
        out["cues"] = cues
    if isinstance(sc.get("sfx"), (list, tuple)):
        fx = []
        for e in list(sc["sfx"])[:MAX_SFX]:
            if isinstance(e, dict) and e.get("kind") in SFX_KINDS:
                at = _num(e.get("at"), 0, dur, 0.0)
                fx.append({"at": round(at, 2), "kind": e["kind"], "level_db": round(_num(e.get("level_db"), -30, 0, -14.0), 1)})
        if fx:
            out["sfx"] = fx
    return out


# ───────────────────────────────────────────── برند / صدا / پلتفرم

def normalize_brand(b) -> dict:
    out = {"use_brand_colors": True, "show_logo": True, "name": "", "colors": []}       # همیشه همین کلیدها: نرمال‌سازی ایدمپوتنت است
    if not isinstance(b, dict):
        return out
    out["name"] = _s(b.get("name"), 80)
    cols = []
    for c in (b.get("colors") or [])[:4]:
        c = _s(c, 9)
        if re.fullmatch(r"#?[0-9a-fA-F]{6}", c):
            cols.append(c if c.startswith("#") else "#" + c)
    out["colors"] = cols
    logo = _ref(b.get("logo"), "logo") if b.get("logo") else ""
    if logo:
        out["logo"] = logo
    out["use_brand_colors"] = bool(b.get("use_brand_colors", True))
    out["show_logo"] = bool(b.get("show_logo", True))
    return out


def normalize_audio(a, notes=None) -> dict:
    """{voice:{on,voice_id,speed}, music:{on,ref,level_db}, sfx, beat_sync} — فقط آنچه روشن است ذخیره می‌شود."""
    out: dict = {}
    if not isinstance(a, dict):
        return out
    v = a.get("voice")
    if isinstance(v, dict) and v.get("on"):
        vid = _s(v.get("voice_id"), 70) or "auto"
        if not VOICE_RE.match(vid):
            _note(notes, "شناسهٔ صدای گوینده معتبر نبود؛ «خودکار» گذاشته شد.")
            vid = "auto"
        out["voice"] = {"on": True, "voice_id": vid, "speed": round(_num(v.get("speed"), 0.8, 1.25, 1.0, notes, "speed"), 2)}
    m = a.get("music")
    if isinstance(m, dict) and m.get("on"):
        ref = _s(m.get("ref"), 30) or "auto"
        if not MUSIC_RE.match(ref):
            _note(notes, "موسیقیِ انتخابی معتبر نبود؛ «خودکار» گذاشته شد.")
            ref = "auto"
        out["music"] = {"on": True, "ref": ref, "level_db": round(_num(m.get("level_db"), -30, -12, -22.0, notes, "level_db"), 1)}
    if a.get("sfx") is not None:
        out["sfx"] = bool(a.get("sfx"))
    if a.get("beat_sync") is not None:
        out["beat_sync"] = bool(a.get("beat_sync"))
    return out


def total_seconds(spec: dict) -> float:
    return timeline.total_seconds(spec) if spec.get("scenes") else 0.0


def normalize_spec(spec: dict, *, max_total: float = MAX_TOTAL_S_NODE, notes: list | None = None) -> dict:
    """spec ⇒ spec پاک‌شده (نسخهٔ ۲)؛ مشکل ⇒ SpecError. `notes` (فهرست) اگر داده شود، توضیحِ فارسیِ هر اصلاحِ بی‌صدا در آن می‌آید."""
    if not isinstance(spec, dict):
        raise SpecError("پارامترهای ویدیو معتبر نیستند.")
    ver = spec.get("version", 1)
    try:
        ver = int(ver)
    except (TypeError, ValueError):
        ver = 1
    if ver > SCHEMA_VERSION:
        raise SpecError(f"نسخهٔ طرح ({ver}) از نسخهٔ این سامانه ({SCHEMA_VERSION}) جدیدتر است.")
    style = _s(spec.get("style"), 60)
    if not catalog.get(style):
        raise SpecError(f"سبکِ «{style}» پیدا نشد.")
    aspect = _s(spec.get("aspect"), 6) or "9:16"
    if aspect not in ASPECTS:
        raise SpecError("نسبتِ تصویر باید یکی از ۹:۱۶، ۱:۱، ۴:۵ یا ۱۶:۹ باشد.")
    scenes_in = spec.get("scenes")
    if not isinstance(scenes_in, list) or not scenes_in:
        raise SpecError("حداقل یک صحنه لازم است.")
    if len(scenes_in) > MAX_SCENES:
        raise SpecError(f"حداکثر {MAX_SCENES} صحنه.")
    fps = spec.get("fps", 30)
    try:
        fps = int(fps)
    except (TypeError, ValueError):
        fps = 30
    if fps not in FPS_CHOICES:
        fps = 30
    lang = _s(spec.get("lang"), 2) or "fa"
    digits = _s(spec.get("digits"), 4) or "auto"
    out = {
        "version": SCHEMA_VERSION, "style": style, "aspect": aspect, "fps": fps, "lang": lang if lang in ("fa", "en") else "fa",
        "digits": digits if digits in ("fa", "en", "auto") else "auto",
        "brand": normalize_brand(spec.get("brand")),
        "scenes": [normalize_scene(s, i, notes) for i, s in enumerate(scenes_in)],
    }
    try:
        k = float(spec.get("intensity", 1))
    except (TypeError, ValueError):
        k = 1.0
    out["intensity"] = round(max(0.5, min(1.5, k)), 2)
    tr = _s(spec.get("transition"), 20)
    if tr:
        if tr not in catalog.TRANS_KINDS:
            raise SpecError(f"گذارِ «{tr}» را نمی‌شناسم.")
        out["transition"] = tr
    platform = _s(spec.get("platform"), 12)
    if platform:
        if platform in motionlib.PLATFORMS and platform:
            out["platform"] = platform
            out["safe"] = motionlib.platform_safe(platform, aspect)
        else:
            _note(notes, f"پلتفرمِ «{platform}» را نمی‌شناسم و کنار گذاشتم.")
    cap = spec.get("captions")
    if isinstance(cap, dict) and cap.get("on"):
        pos = _s(cap.get("position"), 10)
        out["captions"] = {"on": True, "position": pos if pos in CAPTION_POSITIONS else "lower"}
    if spec.get("bare"):
        out["bare"] = True                # زمینهٔ مشکیِ ساده بدونِ تزئین: برای کلیپی که روی تایم‌لاین با ترکیبِ screen روی تصویر می‌نشیند
    aud = normalize_audio(spec.get("audio"), notes)
    if aud:
        out["audio"] = aud
    total = total_seconds(out)
    if total > max_total + 0.01:
        raise SpecError(f"مدتِ کلِ ویدیو {total:.0f} ثانیه است؛ حداکثر {max_total:.0f} ثانیه مجاز است.")
    out["total_s"] = round(total, 2)
    return out


def upgrade(spec: dict) -> dict:
    """هر طرحِ قدیمی (نسخهٔ ۱ یا بدونِ نسخه) ⇒ نسخهٔ ۲ (فقط نسخه عوض می‌شود؛ کلیدهای تازه همه اختیاری‌اند)."""
    return normalize_spec(spec)


def asset_refs(spec: dict) -> list:
    """همهٔ منبع‌های تصویریِ spec (بدونِ تکرار)."""
    refs: list = []
    b = spec.get("brand") or {}
    if b.get("logo"):
        refs.append(b["logo"])
    for sc in spec.get("scenes") or []:
        for holder in [sc, *(sc.get("overlays") or [])]:
            comp = components.get(holder.get("type", ""))
            for key, fs in (comp["fields"].items() if comp else []):
                if fs["kind"] == "ref" and holder.get(key):
                    refs.append(holder[key])
    seen: set = set()
    return [r for r in refs if not (r in seen or seen.add(r))]


def sample_spec(style: str = "flat-vector", template: str = "explainer", aspect: str = "9:16") -> dict:
    tpl = next((t for t in TEMPLATES if t["id"] == template), TEMPLATES[0])
    return {"version": SCHEMA_VERSION, "style": style, "aspect": aspect, "fps": 30, "lang": "fa", "digits": "auto",
            "brand": {"use_brand_colors": True, "show_logo": True, "colors": []},
            "scenes": [dict(SAMPLE_SCENES[t]) for t in tpl["scenes"]]}


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text or "") if re.search(r"\w", w)])
