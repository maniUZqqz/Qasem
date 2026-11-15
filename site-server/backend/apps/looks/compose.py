"""ساختنِ دستورِ تصویر از یک «سبک» برای هر نوعِ تبلیغ.

SOURCE: ``compose`` idea ported from InstAI:instai/styles/library.py (``compose``) @ 2f8aa90, rewritten for store advertising:
نوعِ تبلیغ (``kind``) تعیین می‌کند چه چیزی از سبک به مدل می‌رسد.

=================  =====================================================================================================
نوع                چه می‌رسد
=================  =====================================================================================================
PRODUCT_SHOT       «عکسِ محصول» و «بهبودِ عکس»: روی عکسِ واقعیِ محصول کار می‌کنند و محصول نباید عوض شود. فقط سبک‌های
ENHANCED           ``product_safe`` مجازند و فقط تکه‌دستورهای «صحنه و نور» می‌رسد (واژه‌های بازطراحیِ سوژه حذف می‌شود).
                   سبکِ تصویرسازی‌شده ⇒ ``LookError`` با توضیحِ فارسی.
POSTER             پوستر و «تصویرِ تازه»: همهٔ سبک‌ها؛ دستورِ کامل.
NEW_IMAGE
THUMB_BG           پس‌زمینهٔ تامنیل: دستورِ کامل ولی بدونِ واژه‌های آدم/چهره/شخصیت (پس‌زمینه سوژه ندارد).
SAMPLE             تصویرِ نمونهٔ سبک (یک بطریِ ساده): مثلِ THUMB_BG.
=================  =====================================================================================================

در همهٔ نوع‌ها: واژه‌هایی که مدل را به نوشتنِ حروف می‌کشاند (typography، lettering، charts …) حذف می‌شود، چون متنِ فارسی را همیشه
خودِ برنامه با Pillow می‌کشد. نامِ هیچ استودیو یا هنرمندی هرگز وارد دستور نمی‌شود (در داده‌ها نیست؛ ``aliases`` فقط برای جست‌وجوست).
"""
from __future__ import annotations

import re

from . import fit, library, schema

PRODUCT_KINDS = ("PRODUCT_SHOT", "ENHANCED")
FULL_KINDS = ("POSTER", "NEW_IMAGE")
SUBJECTLESS_KINDS = ("THUMB_BG", "SAMPLE")
KINDS = PRODUCT_KINDS + FULL_KINDS + SUBJECTLESS_KINDS
KIND_FA = {"POSTER": "پوستر تبلیغاتی", "PRODUCT_SHOT": "عکس اینستاگرامیِ محصول", "ENHANCED": "بهبود عکس محصول", "NEW_IMAGE": "تصویرِ تازه",
           "THUMB_BG": "پس‌زمینهٔ تامنیل", "SAMPLE": "تصویرِ نمونه"}

#: تکه‌دستورهایی که مدل را به کشیدنِ حرف و نمودار می‌برد (متنِ فارسی همیشه با کد کشیده می‌شود)
TEXT_FRAGMENT = re.compile(
    r"letter|lettering|typograph|\bwords?\b|\btext\b|\bfonts?\b|\bascii\b|code lines|\bcharts?\b|infographic|readouts|\blabels?\b|\bcaptions?\b|"
    r"\bnumbers?\b|digits|\bsigns?\b|notes\b", re.I)
#: واژه‌هایی که یک «آدم/شخصیت» می‌خواهند؛ پس‌زمینه و تصویرِ نمونه (بطری) آدم ندارد
SUBJECT_FRAGMENT = re.compile(r"\bfaces?\b|\beyes?\b|character|\bfigures?\b|portrait|people|person|\bskin\b|puppets?\b|\bhero\b|\bgirls?\b|\bboys?\b|"
                              r"\bwomen\b|\bman\b|costume|armou?r|\bhair\b|acting|\bposes?\b|proportions", re.I)
NO_TEXT_NEGATIVE = "text, letters, typography, words, watermark, logo, signature"
PRODUCT_NEGATIVE = ("blurry, low quality, jpeg artifacts, watermark, text, extra fingers, deformed, cropped, "
                    "altered product, different product, changed logo, changed shape, changed colour, redrawn product")


class LookError(ValueError):
    """خطایی که متنش برای کاربر است (فارسی). ``code`` برای API."""

    def __init__(self, code: str, message_fa: str):
        super().__init__(message_fa)
        self.code = code
        self.message_fa = message_fa


#: برای پیشنهاد در پیامِ «این سبک روی عکسِ محصول مجاز نیست»: سبک‌های آشناترِ عکاسیِ محصول اول می‌آیند (نه «فیلم خانگی»)
SAFE_FIRST = ("cinematic_realistic", "documentary_real", "photoreal_cgi", "noir_bw", "cineview_widescreen")


def safe_names(limit: int = 4) -> list[str]:
    safe = [k for k, s in library.STYLES.items() if s["product_safe"]]
    ordered = [k for k in SAFE_FIRST if k in safe] + [k for k in safe if k not in SAFE_FIRST]
    return [library.STYLES[k]["name_fa"] for k in ordered][:limit]


def refusal_text(look_name: str) -> str:
    ok = "، ".join(f"«{n}»" for n in safe_names(3))
    return (f"سبکِ «{look_name}» شکلِ خودِ محصول را عوض می‌کند (مثلاً خط‌دور، نقاشی یا عروسکی‌اش می‌کند)، برای همین روی «عکسِ محصول» و «بهبودِ عکس» "
            f"که باید محصولِ واقعی عیناً بماند مجاز نیست. این سبک را برای «پوستر تبلیغاتی» به کار ببرید، یا برای عکسِ محصول یکی از سبک‌های نور و صحنه "
            f"مثل {ok} را بردارید.")


def _drop(fragments: list[str], *patterns: re.Pattern) -> list[str]:
    return [f for f in fragments if not any(p.search(f) for p in patterns)]


def compose(look_key: str, kind: str, store=None, *, theme_key: str = "", notes: str = "") -> dict:
    """دستورِ مثبت/منفی، پالت و راهنمای گام/هدایت برای یک سبک. ``LookError`` اگر سبک/نوع/تم نامعتبر یا برای آن نوع مجاز نباشد."""
    k = str(kind or "").upper()
    if k not in KINDS:
        raise LookError("bad_kind", f"نوعِ تبلیغ «{kind}» شناخته نیست.")
    s = library.style(look_key)
    if s is None:
        raise LookError("unknown_look", "این سبک در کتابخانه نیست؛ از فهرستِ سبک‌ها یکی را انتخاب کنید.")
    th = None
    if theme_key:
        th = library.theme(theme_key)
        if th is None:
            raise LookError("unknown_theme", "این تمِ رنگی در کتابخانه نیست.")
    if k in PRODUCT_KINDS and not s["product_safe"]:
        raise LookError("look_changes_product", refusal_text(s["name_fa"]))

    base = fit.fragments(s["image_positive"])
    base = _drop(base, TEXT_FRAGMENT)
    guard = ""
    if k in PRODUCT_KINDS:
        positive_parts = fit.scene_fragments({**s, "image_positive": ", ".join(base)})
        positive_parts += [s["lighting"]] if s["lighting"] else []
        theme_words = _theme_words(th)
        positive = library.join(", ".join(positive_parts), theme_words, fit.PRODUCT_GUARD, notes)
        negative = library.join(PRODUCT_NEGATIVE, th["negative_fragment"] if th else "")
        guard = fit.PRODUCT_GUARD
    else:
        if k in SUBJECTLESS_KINDS:
            base = _drop(base, SUBJECT_FRAGMENT)
        positive = library.join(", ".join(base), th["prompt_fragment"] if th else "", notes)
        negative = library.join(s["image_negative"], th["negative_fragment"] if th else "", NO_TEXT_NEGATIVE)
    pal = th["palette"] if th else s["palette"]
    gen = dict(s["gen"])
    return {
        "look": look_key, "kind": k, "name_fa": s["name_fa"], "name_en": s["name_en"], "positive": positive, "negative": negative,
        "palette": pal, "theme": theme_key or "", "scene_only": k in PRODUCT_KINDS, "guard": guard,
        "hints": {"steps": gen["steps"], "guidance": gen["guidance"], "cfg": gen["cfg"], "sampler": gen["sampler"], "scheduler": gen["scheduler"],
                  "aspect": gen["aspect"], "model": gen["model"], "alt_model": gen["alt_model"]},
        "brand_colors": brand_colors(store),
    }


def _theme_words(th: dict | None) -> str:
    """تم برای عکسِ محصول: فقط «رنگ‌بندیِ صحنه» (نه واژه‌هایی مثل «matte materials» که سطحِ محصول را عوض می‌کند)."""
    if not th:
        return ""
    return library.join(*[f for f in fit.fragments(th["prompt_fragment"]) if not fit.DENY.search(f.lower())])


def brand_colors(store) -> list[str]:
    if store is None:
        return []
    colors = getattr(store, "colors", None)
    vals = []
    if isinstance(colors, dict):
        vals = [colors.get(key) for key in ("primary", "main", "brand", "secondary", "accent")]
    elif isinstance(colors, (list, tuple)):
        vals = list(colors)
    out: list[str] = []
    for v in vals:
        if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v.strip()) and v.strip().upper() not in out:
            out.append(v.strip().upper())
    return out[:4]


def check(look_key: str, kind: str) -> None:
    """فقط اعتبارسنجی (بدونِ ساختنِ دستور): ``LookError`` اگر این سبک برای این نوع مجاز نیست. برای صفحهٔ API."""
    compose(look_key, kind)


def look_block(c: dict) -> str:
    """بلوکِ «Look:» برای کارگردانِ هوش مصنوعی (QwQ/Qwen) در ``image_studio.build_image_prompt``."""
    lines = [f"Look chosen by the store owner: {c['name_en']}",
             f"Build prompt_en from these look fragments (keep them, in your own sentence): {c['positive']}",
             f"Put these in negative_en: {c['negative']}",
             "prompt_en MUST carry these look fragments (rewritten into your own sentence) and negative_en MUST include the negatives above. "
             "Never name any studio, brand, artist or franchise in prompt_en or negative_en."]
    if c["scene_only"]:
        lines.append("PRODUCT RULE: this look may change ONLY the scene, lighting, background and colour grade. The product itself (shape, colour, material, "
                     "logo) stays exactly as in the photo: no outlines, no painting or cartoon style on the product.")
    else:
        lines.append("The look applies to the whole picture; the product must still be recognisable (same shape, same colours, same branding).")
    return "\n".join(lines)


def ensure_in_prompt(prompt_en: str, c: dict) -> str:
    """دستورِ نهاییِ تصویر: اگر کارگردانِ هوش مصنوعی دستور را بازنویسی کرد و تکه‌ای از سبک (یا محافظِ «همان محصول») جا افتاد، همین‌جا اضافه می‌شود؛
    پس سبکِ انتخاب‌شده همیشه به مدلِ تصویر می‌رسد، حتی اگر کارگردان آن را نادیده بگیرد."""
    have = (prompt_en or "").lower()
    extra = [f for f in fit.fragments(c["positive"]) if f.lower() not in have]
    return library.join(prompt_en, ", ".join(extra))


def merge_negative(negative_en: str, c: dict) -> str:
    return library.join(negative_en, c["negative"])


def public_check(look_key: str, kind: str) -> dict:
    """برای API: ``{ok, code?, message_fa?}`` بدونِ پرتابِ خطا."""
    try:
        check(look_key, kind)
        return {"ok": True}
    except LookError as exc:
        return {"ok": False, "code": exc.code, "message_fa": exc.message_fa}
