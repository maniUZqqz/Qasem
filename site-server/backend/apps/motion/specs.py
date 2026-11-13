"""اعتبارسنجی و پاک‌سازیِ «پارامترهای ترکیب» (spec) — همان چیزی که فرمِ قالبی می‌سازد و هوش مصنوعی می‌نویسد.

هیچ چیزِ خارج از این فهرست به رندر نمی‌رسد: نوعِ صحنه، کلیدهای هر صحنه، طولِ متن‌ها، تعدادِ صحنه، مدت، نسبتِ تصویر.
"""
from __future__ import annotations

import re

from . import catalog

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

#: کلیدهای مجازِ هر نوعِ صحنه ⇒ (حداکثر طول)
SCENE_FIELDS = {
    "title": {"kicker": 60, "title": 140, "subtitle": 220},
    "list": {"title": 100, "items": 6, "numbered": None},
    "quote": {"text": 320, "author": 80},
    "stat": {"kicker": 60, "value": 24, "decimals": None, "prefix": 12, "suffix": 12, "label": 160, "count_up": None},
    "compare": {"title": 100, "before_label": 24, "after_label": 24, "before": 140, "after": 140, "before_image": "ref", "after_image": "ref"},
    "product": {"name": 100, "price": 40, "features": 4, "badge": 30, "image": "ref"},
    "logo": {"title": 80, "tagline": 160},
    "app": {"caption": 120, "bullets": 4, "screenshot": "ref"},
    "cta": {"title": 140, "button": 40, "note": 120},
}
ITEM_MAX = 120
REF_RE = re.compile(r"^(upload|pimg|photo|gimg):\d{1,12}$|^store-logo$|^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]{16,}$")

SCENE_LABELS_FA = {
    "title": "کارتِ عنوان", "list": "فهرست / مراحل", "quote": "نقل‌قول", "stat": "عددِ بزرگ", "compare": "قبل و بعد",
    "product": "معرفیِ محصول", "logo": "لوگو (استینگ)", "app": "نمایشِ اپ در قابِ گوشی", "cta": "دعوت به اقدام",
}

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
]

SAMPLE_SCENES = {
    "title": {"type": "title", "duration": 4, "kicker": "معرفی", "title": "عنوانِ ویدیوی شما", "subtitle": "یک جملهٔ کوتاه که مخاطب را نگه می‌دارد"},
    "list": {"type": "list", "duration": 7, "title": "سه قدمِ ساده", "items": ["قدمِ اول", "قدمِ دوم", "قدمِ سوم"], "numbered": True},
    "quote": {"type": "quote", "duration": 5, "text": "جمله‌ای که می‌ارزد به یاد بماند.", "author": "نام"},
    "stat": {"type": "stat", "duration": 4, "kicker": "عدد", "value": "1300", "suffix": "+", "label": "توضیحِ عدد"},
    "compare": {"type": "compare", "duration": 6, "title": "قبل و بعد", "before_label": "قبل", "after_label": "بعد", "before": "وضعیتِ قبل", "after": "وضعیتِ بعد"},
    "product": {"type": "product", "duration": 6, "name": "نامِ محصول", "price": "", "features": ["ویژگیِ اول", "ویژگیِ دوم"], "badge": ""},
    "logo": {"type": "logo", "duration": 3, "tagline": "شعارِ برند"},
    "app": {"type": "app", "duration": 6, "caption": "اپِ شما، در یک نگاه", "bullets": ["قابلیتِ اول", "قابلیتِ دوم", "قابلیتِ سوم"]},
    "cta": {"type": "cta", "duration": 4, "title": "همین حالا شروع کنید", "button": "ثبت‌نام", "note": ""},
}


class SpecError(ValueError):
    """خطای اعتبارسنجی؛ متنِ فارسی برای کاربر."""


def _s(v, n: int, field: str = "") -> str:
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)):
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


def normalize_scene(sc: dict, idx: int = 0) -> dict:
    if not isinstance(sc, dict):
        raise SpecError(f"صحنهٔ {idx + 1} معتبر نیست.")
    typ = _s(sc.get("type"), 20) or "title"
    if typ not in SCENE_FIELDS:
        raise SpecError(f"نوعِ صحنهٔ «{typ}» را نمی‌شناسم (مجاز: {'، '.join(SCENE_FIELDS)}).")
    try:
        dur = float(sc.get("duration", 4))
    except (TypeError, ValueError):
        raise SpecError(f"مدتِ صحنهٔ {idx + 1} عدد نیست.")
    dur = max(MIN_SCENE_S, min(MAX_SCENE_S, dur))
    out: dict = {"type": typ, "duration": round(dur, 2)}
    for key, lim in SCENE_FIELDS[typ].items():
        if key not in sc:
            continue
        v = sc[key]
        if lim == "ref":
            r = _ref(v, key)
            if r:
                out[key] = r
        elif lim is None:
            if key == "decimals":
                try:
                    out[key] = max(0, min(3, int(v)))
                except (TypeError, ValueError):
                    pass
            else:
                out[key] = bool(v)
        elif key in ("items", "features", "bullets"):
            if not isinstance(v, (list, tuple)):
                raise SpecError(f"«{key}» باید فهرست باشد.")
            items = [_s(x, ITEM_MAX, key) for x in v][:lim]
            out[key] = [x for x in items if x]
        else:
            out[key] = _s(v, lim, key)
    # حداقلِ محتوا
    need = {"title": "title", "list": "items", "quote": "text", "stat": "value", "product": "name", "cta": "title", "app": "caption"}
    k = need.get(typ)
    if k and not out.get(k):
        if typ == "app" and out.get("bullets"):
            return out
        raise SpecError(f"صحنهٔ {idx + 1} («{SCENE_LABELS_FA[typ]}») «{k}» ندارد.")
    return out


def normalize_brand(b) -> dict:
    out = {"use_brand_colors": True, "show_logo": True}
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


def total_seconds(spec: dict) -> float:
    st = catalog.get(spec.get("style", ""))
    tf = 0 if not st else (0 if (spec.get("transition") or st["trans"]["kind"]) == "cut" else st["trans"]["frames"] / (spec.get("fps") or 30))
    scenes = spec.get("scenes") or []
    t = sum(s["duration"] for s in scenes)
    if len(scenes) > 1 and tf:
        t -= tf * (len(scenes) - 1)
    return max(0.0, t)


def normalize_spec(spec: dict, *, max_total: float = MAX_TOTAL_S_NODE) -> dict:
    """spec ⇒ spec پاک‌شده؛ مشکل ⇒ SpecError."""
    if not isinstance(spec, dict):
        raise SpecError("پارامترهای ویدیو معتبر نیستند.")
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
        "version": 1, "style": style, "aspect": aspect, "fps": fps, "lang": lang if lang in ("fa", "en") else "fa",
        "digits": digits if digits in ("fa", "en", "auto") else "auto",
        "brand": normalize_brand(spec.get("brand")),
        "scenes": [normalize_scene(s, i) for i, s in enumerate(scenes_in)],
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
    total = total_seconds(out)
    if total > max_total + 0.01:
        raise SpecError(f"مدتِ کلِ ویدیو {total:.0f} ثانیه است؛ حداکثر {max_total:.0f} ثانیه مجاز است.")
    out["total_s"] = round(total, 2)
    return out


def asset_refs(spec: dict) -> list[str]:
    """همهٔ منبع‌های تصویریِ spec (بدونِ تکرار)."""
    refs: list[str] = []
    b = spec.get("brand") or {}
    if b.get("logo"):
        refs.append(b["logo"])
    for sc in spec.get("scenes") or []:
        for k in ("image", "before_image", "after_image", "screenshot"):
            if sc.get(k):
                refs.append(sc[k])
    seen: set[str] = set()
    return [r for r in refs if not (r in seen or seen.add(r))]


def sample_spec(style: str = "flat-vector", template: str = "explainer", aspect: str = "9:16") -> dict:
    tpl = next((t for t in TEMPLATES if t["id"] == template), TEMPLATES[0])
    return {"version": 1, "style": style, "aspect": aspect, "fps": 30, "lang": "fa", "digits": "auto",
            "brand": {"use_brand_colors": True, "show_logo": True, "colors": []},
            "scenes": [dict(SAMPLE_SCENES[t]) for t in tpl["scenes"]]}
