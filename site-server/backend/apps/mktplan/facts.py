"""واقعیت‌های فروشگاه برای ساختِ برنامه — فقط از چیزهایی که خودِ فروشگاه در NM ثبت کرده.

هیچ‌چیز ساخته نمی‌شود: نام، نوعِ کسب‌وکار، توضیح، مخاطب، لحن، شخصیتِ گفتار (شعار، ارزش‌ها، واژه‌های بگو/نگو)، محصول‌ها و نشانیِ سایت و
اپ از پروفایل و پایگاه‌داده می‌آیند. قیمت و آمار و نظرِ مشتری هرگز از این‌جا وارد متن نمی‌شود (جای‌گیرِ «[…]» می‌ماند تا خودِ مالک پر کند).
"""
from __future__ import annotations

import re
from typing import Any

from apps.ideabank import fill as idea_fill

_SENT = re.compile(r"(?<=[.!؟?])\s+|\n+")
_URL = re.compile(r"^https?://", re.I)


def _first_sentences(text: str, n: int = 2, limit: int = 220) -> str:
    parts = [p.strip() for p in _SENT.split(str(text or "")) if p.strip()]
    out = " ".join(parts[:n])
    return out[:limit].rstrip(" ،؛") if out else ""


def _persona(store) -> dict:
    """شخصیتِ گفتارِ ذخیره‌شده؛ اگر نبود پیش‌نویسِ قاعده‌محور (بدونِ هوش مصنوعی)."""
    try:
        from apps.brandchar import persona as P, persona_store

        row = persona_store.get(store)
        if row is not None and row.data:
            return P.normalize(row.data)
        return (P.draft(store) or {}).get("persona") or {}
    except Exception:  # noqa: BLE001 — شخصیت فقط لحن را بهتر می‌کند؛ نبودنش برنامه را نمی‌خواباند
        return {}


def _products(store, limit: int = 8) -> list[dict]:
    from apps.products.models import Product

    out = []
    for p in Product.objects.filter(store=store).order_by("pk")[:limit]:
        out.append({
            "id": p.pk, "name": str(p.name or "").strip(),
            "short": _first_sentences(p.short_description or p.description or "", 1, 160),
            "free": (p.price is not None and float(p.price) == 0.0),
        })
    return out


def store_facts(store) -> dict[str, Any]:
    prof = getattr(store, "profile", None)
    persona = _persona(store)
    ctx = idea_fill.context(store)
    values = ctx["values"]
    links = dict(getattr(store, "social_links", None) or {})
    site = next((str(links[k]) for k in ("app", "website", "site", "web") if _URL.match(str(links.get(k) or ""))), "")
    instagram = str(links.get("instagram") or "")
    products = _products(store)
    flagship = next((p for p in products if p["name"] and not any(ch.isdigit() for ch in p["name"])), products[0] if products else None)
    about = _first_sentences(getattr(store, "description", ""), 2)
    # «یک جمله دربارهٔ کار»: جملهٔ اولِ توضیحِ فروشگاه؛ توضیحِ لحنِ شخصیتِ گفتار (summary) توصیفِ «صدا» است نه «محصول»، پس فقط جانشین است
    one_liner = _first_sentences(getattr(store, "description", ""), 1, 200) or str(persona.get("summary") or "").strip() or str(getattr(store, "business_type", "") or "").strip()
    tagline = str(persona.get("tagline") or "").strip()
    catch = [str(x) for x in (persona.get("catchphrases") or []) if str(x).strip()]
    return {
        "store_id": store.pk,
        "name": str(store.name or "").strip(),
        "business": str(getattr(store, "business_type", "") or "").strip(),
        "about": about,
        "one_liner": one_liner,
        "audience": str(getattr(store, "target_audience", "") or "").strip(),
        "audience_short": values["مخاطب"] if ctx["known"]["مخاطب"] else "مخاطبانتان",
        "tone": str(getattr(prof, "tone", "") or getattr(prof, "brand_voice", "") or "").strip() if prof else "",
        "tagline": tagline,
        "cta": (catch[0] if catch else tagline) or "همین حالا شروع کنید",
        "summary": str(persona.get("summary") or "").strip(),
        "values": [str(v) for v in (persona.get("values") or [])][:6],
        "do_words": [str(v) for v in (persona.get("do_words") or [])][:12],
        "dont_words": [str(v) for v in (persona.get("dont_words") or [])][:20],
        "products": products,
        "flagship": flagship["name"] if flagship else "",
        "flagship_short": flagship["short"] if flagship else "",
        "site": site,
        "instagram": instagram,
        "colors": dict(getattr(store, "colors", None) or {}),
        "known": ctx["known"],
        "placeholders": ctx["values"],
    }


def source_blob(f: dict) -> str:
    """متنی که «خودِ فروشگاه نوشته»؛ عددی که فقط این‌جا هست «ادعای ساختگی» حساب نمی‌شود (نگهبانِ ایده‌ها)."""
    bits = [f.get("name", ""), f.get("business", ""), f.get("about", ""), f.get("audience", ""), f.get("tagline", ""), f.get("summary", "")]
    bits += [p["name"] + " " + p.get("short", "") for p in f.get("products", [])]
    bits += f.get("values", []) + f.get("do_words", [])
    return " ".join(str(b) for b in bits if b)


def summary_public(f: dict) -> dict:
    """بخشِ سبکِ واقعیت‌ها برای نشان‌دادن در صفحه (چه چیزی از پروفایل خوانده شد و چه چیزی خالی بود)."""
    gaps = []
    if not f["about"]:
        gaps.append("توضیحِ فروشگاه (پروفایل) خالی است")
    if not f["audience"]:
        gaps.append("مخاطبِ هدف ثبت نشده")
    if not f["products"]:
        gaps.append("هیچ محصولی ثبت نشده")
    if not f["tagline"]:
        gaps.append("شعار/شخصیتِ گفتار ثبت نشده (در «شخصیتِ برند ⇐ شخصیتِ گفتار» پر کنید)")
    if not f["site"]:
        gaps.append("نشانیِ سایت/اپ در «اتصال شبکه‌ها / پروفایل» ثبت نشده")
    return {
        "name": f["name"], "business": f["business"], "about": f["about"], "audience": f["audience"], "tone": f["tone"], "tagline": f["tagline"],
        "products": [p["name"] for p in f["products"]], "site": f["site"], "dont_words": f["dont_words"], "gaps": gaps,
    }
