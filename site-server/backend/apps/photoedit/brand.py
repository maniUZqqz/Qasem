"""تنظیماتِ ادیتورِ عکسِ هر فروشگاه (نوبت ۴): «پیش‌فرضِ کمکِ هوش مصنوعی» و «سبکِ برند».

سبکِ برند یک بار ذخیره می‌شود و «طراحِ خودکار» و طراحیِ گروهی پیش‌فرض از آن استفاده می‌کنند؛ هر طراحی می‌تواند آن را برای خودش عوض کند
(``options.brand`` ِ طراحی، که روی سبکِ ذخیره‌شده می‌نشیند). هیچ‌چیزِ اینجا هوشِ مصنوعی صدا نمی‌زند.
"""
from __future__ import annotations

from . import fontreg
from .designer import colorx
from .models import PhotoAsset, PhotoStoreSetting

POSITIONS = ("tl", "tr", "bl", "br", "bottom_center", "top_center")
MAX_COLORS = 5
TONE_MAX = 200
SIZE_MIN, SIZE_MAX = 0.06, 0.30

#: هر طراحیِ خودکار حداکثر چند فراخوانیِ «بینا» (عکس + متن) به هوش مصنوعی می‌زند — برای یادداشتِ هزینه در تنظیمات
# برنامه‌ریز = ۱؛ منتقد = تعدادِ پیشنهاد × دورها. «سریع» = بدونِ نقد؛ «معمولی» = ۱ دور؛ «بهترین» = ۲ دور.
AI_COST = {"variants": 3, "fast": 1, "normal": 1 + 3 * 1, "best": 1 + 3 * 2, "batch_per_photo": 1}


def empty_brand() -> dict:
    return {"colors": [], "heading_font": "", "body_font": "", "logo": {"mode": "store", "asset": None, "position": "", "size": 0.0}, "tone": ""}


def clean(data) -> dict:
    """ورودیِ کاربر ⇒ سبکِ برندِ تمیز (چیزِ نامعتبر بی‌صدا کنار می‌رود؛ خطا فقط برای ساختارِ کاملاً غلط)."""
    d = data if isinstance(data, dict) else {}
    out = empty_brand()
    cols = d.get("colors")
    if isinstance(cols, list):
        seen: list[str] = []
        for c in cols:
            c = str(c or "").strip().lower()
            if colorx.is_hex(c) and c not in seen:
                seen.append(c)
        out["colors"] = seen[:MAX_COLORS]
    for k in ("heading_font", "body_font"):
        v = str(d.get(k) or "").strip()
        out[k] = v if v and fontreg.known(v) else ""
    lg = d.get("logo") if isinstance(d.get("logo"), dict) else {}
    mode = lg.get("mode") if lg.get("mode") in ("store", "asset", "none") else "store"
    asset = None
    if mode == "asset":
        try:
            asset = int(lg.get("asset"))
        except (TypeError, ValueError):
            asset = None
        if asset is None:
            mode = "store"
    pos = lg.get("position") if lg.get("position") in POSITIONS else ""
    try:
        size = float(lg.get("size") or 0)
    except (TypeError, ValueError):
        size = 0.0
    size = 0.0 if size <= 0 else max(SIZE_MIN, min(SIZE_MAX, size))
    out["logo"] = {"mode": mode, "asset": asset, "position": pos, "size": round(size, 3)}
    out["tone"] = " ".join(str(d.get("tone") or "").split())[:TONE_MAX]
    return out


def is_set(b: dict) -> bool:
    return bool(b and (b.get("colors") or b.get("heading_font") or b.get("body_font") or b.get("tone") or (b.get("logo") or {}).get("position")
                       or (b.get("logo") or {}).get("size") or (b.get("logo") or {}).get("mode") not in (None, "store")))


def get_setting(store) -> PhotoStoreSetting | None:
    return PhotoStoreSetting.objects.filter(store=store).first()


def ai_default(store) -> bool:
    s = get_setting(store)
    return True if s is None else bool(s.ai_assist)


def stored_brand(store) -> dict:
    s = get_setting(store)
    return clean(s.brand) if s is not None else empty_brand()


def public(store) -> dict:
    b = stored_brand(store)
    return {"ai_assist": ai_default(store), "brand": b, "brand_set": is_set(b), "ai_cost": AI_COST, "positions": list(POSITIONS)}


def save(store, data: dict) -> dict:
    s, _ = PhotoStoreSetting.objects.get_or_create(store=store)
    if "ai_assist" in data:
        s.ai_assist = bool(data.get("ai_assist"))
    if "brand" in data:
        s.brand = clean(data.get("brand"))
    s.save()
    return public(store)


def effective(store, options: dict | None) -> dict | None:
    """سبکِ برندِ مؤثر برای یک طراحی: ذخیره‌شده + بازنویسیِ همان طراحی. ``options.use_brand=False`` ⇒ None (سبکِ برند اعمال نشود)."""
    o = options or {}
    if o.get("use_brand") is False:
        return None
    base = stored_brand(store)
    ov = o.get("brand")
    if isinstance(ov, dict) and ov:
        c = clean(ov)
        # فقط کلیدهایی که کاربر در بازنویسی داده‌اند جای سبکِ ذخیره‌شده را می‌گیرند
        for k in ("colors", "heading_font", "body_font", "tone"):
            if k in ov:
                base[k] = c[k]
        if isinstance(ov.get("logo"), dict):
            lg = dict(base["logo"])
            for k in ("mode", "asset", "position", "size"):
                if k in ov["logo"]:
                    lg[k] = c["logo"][k]
            base["logo"] = lg
    return base if is_set(base) else None


def logo_asset(store, kit: dict | None) -> PhotoAsset | None:
    lg = (kit or {}).get("logo") or {}
    if lg.get("mode") == "asset" and lg.get("asset"):
        return PhotoAsset.objects.filter(store=store, pk=lg["asset"]).first()
    return None
