"""کیتِ برند + «سبک» (look) + «پرسونا» برای استودیوی طراحی — از همان منبع‌هایی که ادیتورِ عکس و ایجنت می‌خوانند.

* رنگ‌ها: «سبکِ برندِ ادیتورِ عکس» (PhotoStoreSetting.brand) ⇐ رنگ‌های فروشگاه (Store.colors) ⇐ پیش‌فرضِ خنثی.
* فونت‌ها: همان سبکِ برند؛ وگرنه وزیرمتن.
* تمِ سبک (apps.looks): ۲۴ تمِ رنگی؛ اگر انتخاب شود پالت را عوض می‌کند (برند همچنان لوگو و فونت را می‌دهد).
* پرسونا: توضیحِ فروشگاه، مخاطب، لحنِ برند (StoreProfile) — برای متنِ پیش‌نویس و لحنِ خودکار.
"""
from __future__ import annotations

from . import colors, fonts


def _brand_setting(store) -> dict:
    try:
        from apps.photoedit import brand as pb

        return pb.stored_brand(store) if store is not None else {}
    except Exception:  # noqa: BLE001
        return {}


def look_themes() -> list[dict]:
    try:
        from apps.looks import library

        return [{"key": k, "name_fa": t.get("name_fa", k), "palette": list(t.get("palette") or []), "mood": t.get("mood", "")}
                for k, t in library.THEMES.items()]
    except Exception:  # noqa: BLE001
        return []


def look_theme(key: str) -> dict | None:
    if not key:
        return None
    try:
        from apps.looks import library

        return library.theme(key)
    except Exception:  # noqa: BLE001
        return None


def persona(store) -> dict:
    """{name، about، audience، business، voice، tone، style} — فقط آنچه ثبت شده."""
    if store is None:
        return {}
    prof = getattr(store, "profile", None)
    try:
        prof = store.profile
    except Exception:  # noqa: BLE001
        prof = None
    return {"name": store.name or "", "about": (store.description or "").strip(), "audience": (store.target_audience or "").strip(),
            "business": (store.business_type or "").strip(), "voice": getattr(prof, "brand_voice", "") or "", "tone": getattr(prof, "tone", "") or "",
            "style": getattr(prof, "content_style", "") or ""}


def contacts(store) -> list[dict]:
    """راه‌های تماسِ ثبت‌شده (فقط پُر)؛ [{label، value، kind}]."""
    out: list[dict] = []
    if store is None:
        return out
    c = store.contact if isinstance(getattr(store, "contact", None), dict) else {}
    labels = (("phone", "تلفن"), ("mobile", "همراه"), ("email", "ایمیل"), ("address", "نشانی"), ("website", "وب‌سایت"), ("telegram", "تلگرام"),
              ("whatsapp", "واتساپ"), ("instagram", "اینستاگرام"))
    for k, label in labels:
        v = str(c.get(k) or "").strip()
        if v:
            out.append({"label": label, "value": v, "kind": k})
    s = store.social_links if isinstance(getattr(store, "social_links", None), dict) else {}
    for k, v in s.items():
        v = str(v or "").strip()
        if v and not any(x["value"] == v for x in out):
            out.append({"label": {"instagram": "اینستاگرام", "telegram": "تلگرام"}.get(k, str(k)), "value": v, "kind": str(k)})
    return out


def kit(store, settings: dict | None = None) -> dict:
    """⇒ {name، palette، dark، fonts، has_logo، persona، look، source}."""
    s = settings or {}
    bs = _brand_setting(store)
    raw = None
    source = "default"
    if isinstance(s.get("colors"), (list, dict)) and s["colors"]:
        raw, source = s["colors"], "document"
    elif bs.get("colors"):
        raw, source = bs["colors"], "brand_kit"
    elif store is not None and isinstance(getattr(store, "colors", None), dict) and store.colors:
        raw, source = store.colors, "store"
    look = look_theme(s.get("look") or "")
    pal = colors.role_palette(raw, look)
    dark = colors.role_palette(raw, look, dark=True)
    hf = fonts.clean(s.get("heading_font") or bs.get("heading_font") or "", "")
    bf = fonts.clean(s.get("body_font") or bs.get("body_font") or "", "")
    return {"name": getattr(store, "name", "") or "", "palette": pal, "dark": dark,
            "fonts": {"heading": hf or ("estedad" if fonts.known("estedad") else fonts.DEFAULT), "body": bf or fonts.DEFAULT},
            "has_logo": bool(store is not None and getattr(store, "logo", None) and getattr(store.logo, "name", "")),
            "persona": persona(store), "look": s.get("look") or "", "source": source, "tone": bs.get("tone", "")}
