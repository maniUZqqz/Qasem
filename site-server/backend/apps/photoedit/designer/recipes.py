"""الگوهای طراحی (recipes): هر الگو از «تحلیلِ عکس + متن‌ها + حال‌وهوا» یک برنامهٔ کامل می‌سازد — بی هوشِ مصنوعی.

هوشِ مصنوعی فقط الگو، متن‌ها، حال‌وهوا و اصلاحِ رنگ را پیشنهاد می‌دهد؛ چیدمان، اندازه‌ها، رنگ‌ها و حاشیه‌ها از این‌جا و از
``build``/``qa`` می‌آید (کفِ کیفیت). هر الگو سه «سبک» (variation ۰ تا ۲) دارد: سه پیشنهادِ متفاوت.

نام‌های فارسیِ مرحله‌ها (title/why) همان چیزی است که کاربر در پنل می‌بیند.
"""
from __future__ import annotations

import math
import re

from . import colorx, grid, typo

#: ابزارِ «محصول از پس‌زمینه جدا شود؟» فقط وقتی معنا دارد که زمینه ساده باشد یا عکس شفاف باشد
CUTOUT_RECIPES = ("product_ad", "story", "catalog_white", "price_tag")


def _s(tool: str, sid: str, title: str, why: str = "", **params) -> dict:
    return {"id": sid, "tool": tool, "title": title, "why": why, "on": True, "params": params}


# ───────────────────────────── متن‌ها از دستور

_DISCOUNT = re.compile(r"([\d۰-۹]{1,3})\s*(?:٪|%|درصد)")
_PRICE = re.compile(r"([\d۰-۹][\d۰-۹٬,\.]*)\s*(هزار|میلیون)?\s*(?:تومان|تومن|ریال)")
_QUOTE = re.compile(r"[«\"“]([^»\"”]{2,60})[»\"”]")


def _clean_title(t: str | None) -> str:
    t = (t or "").strip()
    if not t or re.fullmatch(r"(?i)(img|dsc|pxl|photo|image|screenshot)?[-_ ]?\d[\w\- ]*", t) or re.fullmatch(r"[A-Za-z0-9_\-. ]+", t):
        return ""
    return t[:40]


def parse_prompt(prompt: str) -> dict:
    """دستورِ فارسی ⇒ {headline?, discount?, price?, cta?, mood?, recipe?}؛ ساده و قطعی (وقتی هوشِ مصنوعی نیست)."""
    p = str(prompt or "")
    out: dict = {}
    m = _QUOTE.search(p)
    if m:
        out["headline"] = m.group(1).strip()
    m = _DISCOUNT.search(p)
    if m:
        out["discount"] = typo.en_digits(m.group(1))
    m = _PRICE.search(p)
    if m:
        out["price"] = typo.format_price(m.group(0))
    if "سفارش" in p:
        out["cta"] = "همین حالا سفارش دهید"
    elif "بخر" in p or "خرید" in p:
        out["cta"] = "همین حالا بخرید"
    elif "ببین" in p:
        out["cta"] = "ببینید"
    for words, mood in ((("لوکس", "شیک", "مشکی", "طلایی"), "elegant"), (("تیره", "دارک", "شب"), "dark"), (("گرم", "نارنجی", "پاییز"), "warm"),
                        (("سرد", "آبی", "مدرن"), "cool"), (("شاد", "پرانرژی", "رنگی", "جوان"), "vibrant"),
                        (("مینیمال", "ساده", "تمیز"), "minimal"), (("روشن", "سفید"), "light")):
        if any(w in p for w in words):
            out["mood"] = mood
            break
    out["recipe"] = infer_recipe(p)
    return out


def infer_recipe(prompt: str) -> str | None:
    p = str(prompt or "")
    for words, key in ((("قبل و بعد", "قبل‌وبعد", "قبل/بعد"), "before_after"), (("تخفیف", "حراج", "فروش ویژه", "off"), "sale_banner"),
                       (("جدید", "رونمایی", "تازه", "اولین"), "new_arrival"), (("کاتالوگ", "پس‌زمینه سفید", "پس زمینه سفید", "فروشگاهی"), "catalog_white"),
                       (("برچسب قیمت", "قیمت"), "price_tag"), (("استوری", "ریلز"), "story"),
                       (("تبلیغ", "آگهی", "پوستر"), "product_ad")):
        if any(w in p for w in words):
            return key
    return None


def merged_copy(brief: dict) -> dict:
    """متن‌های کاربر + آنچه از دستور فهمیده شد + پیش‌فرض‌ها (خالی‌ها پر می‌شود، متنِ کاربر هرگز عوض نمی‌شود)."""
    user = {k: str(v).strip() for k, v in (brief.get("copy") or {}).items() if v is not None and str(v).strip()}
    parsed = parse_prompt(brief.get("prompt", ""))
    ai = {k: str(v).strip() for k, v in (brief.get("ai_copy") or {}).items() if v}
    out = {}
    for k in ("headline", "subline", "price", "old_price", "discount", "cta", "badge"):
        out[k] = user.get(k) or ai.get(k) or (parsed.get(k) if k in parsed else "") or ""
    out["brand"] = user.get("brand") or ""
    if out["price"]:
        out["price"] = typo.format_price(out["price"])
    if out["old_price"]:
        out["old_price"] = typo.format_price(out["old_price"])
    return out


# ───────────────────────────── رنگ و نور

def auto_grade(an: dict, mood: str, *, pop: float = 1.0) -> dict:
    """لغزنده‌های ظهورِ قطعی از روی اندازه‌گیری‌ها و حال‌وهوا. فقط آنچه لازم است."""
    adj: dict = {}
    b = an["brightness"]
    p50 = max(0.08, b["p50"])
    ev = max(-1.0, min(1.0, math.log2(0.46 / p50) * 0.6))
    if abs(ev) > 0.08:
        adj["exposure"] = round(ev, 2)
    if b["contrast"] < 0.55:
        adj["contrast"] = int(min(25, (0.55 - b["contrast"]) * 80))
    adj["vibrance"] = int(10 * pop)
    adj["clarity"] = int(8 * pop)
    adj["sharpen"] = 25
    adj["sharpenMasking"] = 40
    mood_adj = {"warm": {"temperature": 12, "tint": 2}, "cool": {"temperature": -12}, "dark": {"contrast": 10, "blacks": -10},
                "elegant": {"saturation": -8, "contrast": 8, "highlights": -8}, "vibrant": {"vibrance": 22, "saturation": 8},
                "minimal": {"saturation": -4}, "light": {"exposure": 0.1, "whites": 8}}.get(mood, {})
    for k, v in mood_adj.items():
        adj[k] = round(adj.get(k, 0) + v, 2)
    return adj


# ───────────────────────────── الگوها

def _fmt_defaults(fmt: str, bottom_row: bool = True) -> dict:
    """جاگیریِ محصولِ «قهرمان». با دکمه/قیمتِ پایین: محصول بینِ تیتر (بالا) و ردیفِ پایین جا می‌گیرد تا هیچ متنی رویش نیفتد."""
    cls = grid.class_of(fmt)
    if bottom_row:
        return {"post": {"scale": 0.48, "anchor_y": 0.505, "anchor_x": 0.5}, "story": {"scale": 0.55, "anchor_y": 0.50, "anchor_x": 0.5},
                "wide": {"scale": 0.78, "anchor_y": 0.52, "anchor_x": 0.30}}[cls]
    return {"post": {"scale": 0.60, "anchor_y": 0.54, "anchor_x": 0.5}, "story": {"scale": 0.68, "anchor_y": 0.52, "anchor_x": 0.5},
            "wide": {"scale": 0.78, "anchor_y": 0.52, "anchor_x": 0.30}}[cls]


def _headline_fonts(variation: int) -> tuple[str, int]:
    return (("estedad", 800), ("lalezar", 400), ("vazirmatn", 800))[variation % 3]


def _title_role(text: str) -> str:
    return "hero" if len(text) <= 14 else "title"


def _text_steps(cp: dict, cls: str, *, variation: int, slot: str, with_cta: bool = True, align: str = "center", v: str = "start",
                role: str | None = None, ids=("h", "s")) -> list[dict]:
    out: list[dict] = []
    font, weight = _headline_fonts(variation)
    if cp["headline"]:
        out.append(_s("text", ids[0], "تیتر", "پیامِ اصلی؛ درشت‌ترین متن", text=cp["headline"], role=role or _title_role(cp["headline"]),
                      slot=slot, align=align, v=v, font=font, weight=weight, color="auto", max_lines=2))
    if cp["subline"]:
        out.append(_s("text", ids[1], "متنِ دوم", "توضیحِ کوتاه زیرِ تیتر", text=cp["subline"], role="sub", slot=slot, align=align,
                      below=ids[0] if cp["headline"] else "", font="estedad", weight=500, color="auto", max_lines=2))
    return out


def _grade(an, mood, scope="auto", pop=1.0, **extra) -> dict:
    return _s("grade", "g", "نور و رنگ", "تنظیمِ خودکارِ نور و رنگ از روی اندازه‌گیریِ همین عکس", adjust=auto_grade(an, mood, pop=pop), scope=scope, **extra)


def product_ad(b: dict) -> dict:
    fmt, an, cp, var = b["format"], b["an"], b["copy"], b["variation"]
    cls = grid.class_of(fmt)
    mood = b["mood"]
    cutout_ok = b["can_cutout"]
    steps = [_s("frame", "f", "قابِ خروجی", f"اندازهٔ {grid.FORMAT_FA.get(fmt, fmt)}", format=fmt, fit="cover", focus="smart")]
    d = _fmt_defaults(fmt, bool(cp["cta"] or cp["price"]))
    if cutout_ok:
        steps.append(_s("cutout", "c", "جداکردنِ محصول", "محصول از زمینه جدا می‌شود تا روی زمینهٔ هماهنگ با رنگش بنشیند", fit="hero", **d))
        steps.append(_s("backdrop", "bg", "زمینهٔ هماهنگ", "رنگِ زمینه از رنگِ خودِ محصول ساخته شد (هارمونی)",
                        style=("gradient", "studio", "solid")[var % 3], c0="bg_a", c1="bg_b", angle=100 + 25 * (var % 2),
                        vignette=0.18 if var == 1 else 0.0))
        steps.append(_s("shadow", "sh", "سایهٔ محصول", "سایه تا محصول روی زمینه «بایستد»", kind="both", strength=0.55))
        steps.append(_grade(an, mood, scope="all"))
        steps.append(_s("local_adjust", "la", "نورِ نقطه‌ای", "کمی نور روی محصول تا جلو بیاید", kind="spotlight", strength=0.45))
    else:
        steps.append(_grade(an, mood, scope="photo"))
        # روی خودِ عکس: تیتر همیشه بالا است (پایین برای دکمه و قیمت آزاد می‌ماند) و سایهٔ خوانایی از همان لبه می‌آید
        edge = "right" if cls == "wide" else "top"
        steps.append(_s("scrim", "sc", "سایهٔ خوانایی", "تیرگیِ نرم پشتِ متن تا روی عکس خوانا بماند", edge=edge, strength=0.55, size=0.5))
    if cls == "wide":
        slot, align = "right", "right"
    else:
        slot, align = "top", ("center" if var != 1 else "right")
    steps += _text_steps(cp, cls, variation=var, slot=slot, align=align, v="start")
    if cp["price"]:
        if cls == "wide":
            steps.append(_s("text", "p", "قیمت", "قیمت در کادرِ رنگی", text=cp["price"], role="price", slot="br", align="right", v="end",
                            plate="accent", font="estedad", weight=800, max_lines=1))
        else:
            steps.append(_s("badge", "pb", "برچسبِ قیمت", "قیمت در برچسبِ گرد کنارِ محصول", text=cp["price"], kind="pill", slot="mr", size=0.3, color="accent"))
    if cp["cta"] and not (cls == "wide" and cp["price"]):
        steps.append(_s("text", "cta", "دکمه", "فراخوان به اقدام", text=cp["cta"], role="cta", slot="cta" if cls != "wide" else "br",
                        align="center" if cls != "wide" else "right", v="center" if cls != "wide" else "end", plate="accent", font="estedad",
                        weight=700, max_lines=1))
    if b["has_logo"]:
        steps.append(_s("logo", "lg", "لوگو", "لوگوی فروشگاه", position="bl" if cls != "wide" else "tl", size=0.14))
    return {"recipe": "product_ad", "format": fmt, "mood": mood, "variation": var, "title": "تبلیغ محصول", "steps": steps}


def story(b: dict) -> dict:
    b = dict(b, format="story")
    plan = product_ad(b)
    plan["recipe"] = "story"
    plan["title"] = "استوری"
    return plan


def catalog_white(b: dict) -> dict:
    fmt, an, var = b["format"], b["an"], b["variation"]
    steps = [_s("frame", "f", "قابِ خروجی", "قابِ فروشگاه/کاتالوگ", format=fmt, fit="cover", focus="smart")]
    if b["can_cutout"]:
        steps += [_s("cutout", "c", "جداکردنِ محصول", "محصول روی زمینهٔ سفید", fit="hero", scale=0.74, anchor_y=0.5, anchor_x=0.5),
                  _s("backdrop", "bg", "زمینهٔ سفید", "زمینهٔ سفیدِ تمیز برای کاتالوگ و بازار", style="gradient", c0="#ffffff",
                     c1="#eef0f3" if var else "#f8f9fb", angle=90),
                  _s("shadow", "sh", "سایهٔ نرم", "سایهٔ ملایم زیرِ محصول", kind="both", strength=0.6),
                  _grade(an, "light", scope="all", pop=0.7)]
    else:
        steps = [_s("frame", "f", "قابِ خروجی", "کلِ عکس با حاشیه (بدونِ برش)", format=fmt, fit="contain", fill="white", padding=8),
                 _grade(an, "light", scope="photo", pop=0.7)]
    if b["has_logo"] and var == 2:
        steps.append(_s("logo", "lg", "لوگو", "لوگوی کوچک", position="br", size=0.1, opacity=0.8))
    steps.append(_s("export", "ex", "خروجی", "JPEG با کیفیتِ بالا", format="jpeg", quality=94))
    return {"recipe": "catalog_white", "format": fmt, "mood": "light", "variation": var, "title": "عکسِ کاتالوگ", "steps": steps}


def sale_banner(b: dict) -> dict:
    fmt, an, cp, var = b["format"], b["an"], b["copy"], b["variation"]
    cls = grid.class_of(fmt)
    mood = b["mood"] if b["mood"] != "auto" else "vibrant"
    head = cp["headline"] or "حراجِ ویژه"
    steps = [_s("frame", "f", "قابِ خروجی", f"اندازهٔ {grid.FORMAT_FA.get(fmt, fmt)}", format=fmt, fit="cover", focus="smart"),
             _grade(an, mood, scope="photo", pop=1.3)]
    band_slot = ("top", "bottom", "top")[var % 3]
    if var == 1:
        steps.append(_s("scrim", "sc", "سایهٔ تیره", "عکس کمی تیره می‌شود تا متن بدرخشد", edge="full", strength=0.38, size=1.0))
    else:
        steps.append(_s("shape", "band", "نوارِ رنگی", "نوارِ هم‌رنگِ برند پشتِ تیتر", shape="rect", slot=band_slot, h_frac=0.62 if cls != "story" else 0.5,
                        color="accent", opacity=0.94, radius=0.0))
    font, weight = _headline_fonts(1 if var != 2 else 0)
    steps.append(_s("text", "h", "تیتر", "تیترِ درشت", text=head, role="display", slot=band_slot if var != 1 else "top", align="center", v="center",
                    font=font, weight=weight, color="accent_text" if var != 1 else "white", max_lines=2, plate="none" if var != 1 else "auto"))
    if cp["subline"]:
        steps.append(_s("text", "s", "متنِ دوم", "شرطِ تخفیف یا مهلت", text=cp["subline"], role="sub", slot="low", v="center", font="estedad",
                        weight=600, color="white", max_lines=2, plate="pill"))
    if cp["discount"]:
        steps.append(_s("badge", "d", "برچسبِ تخفیف", "درصدِ تخفیف، بزرگ و پرجلوه", text=typo.fa_digits(f"{cp['discount']}٪"), sub="تخفیف",
                        kind="circle", slot="mr" if var != 2 else "ml", size=0.32, color="accent"))
    elif cp["price"]:
        steps.append(_s("badge", "d", "برچسبِ قیمت", "قیمت در برچسب", text=cp["price"], kind="pill", slot="mr", size=0.32, color="accent"))
    cta = cp["cta"] or "همین حالا بخرید"
    steps.append(_s("text", "cta", "دکمه", "فراخوان به اقدام", text=cta, role="cta", slot="cta", plate="accent", font="estedad", weight=700, max_lines=1))
    if b["has_logo"]:
        steps.append(_s("logo", "lg", "لوگو", "لوگوی فروشگاه", position="bl", size=0.13))
    return {"recipe": "sale_banner", "format": fmt, "mood": mood, "variation": var, "title": "بنرِ تخفیف", "steps": steps}


def new_arrival(b: dict) -> dict:
    fmt, an, cp, var = b["format"], b["an"], b["copy"], b["variation"]
    cls = grid.class_of(fmt)
    mood = b["mood"] if b["mood"] != "auto" else ("elegant", "light", "dark")[var % 3]
    head = cp["headline"] or "محصولِ جدید"
    slot = "bottom" if cls != "wide" else "right"
    steps = [_s("frame", "f", "قابِ خروجی", f"اندازهٔ {grid.FORMAT_FA.get(fmt, fmt)}", format=fmt, fit="cover", focus="smart"),
             _grade(an, mood, scope="photo", pop=0.9),
             _s("scrim", "sc", "سایهٔ نرم", "تیرگیِ ملایم برای خوانایی", edge="bottom" if cls != "wide" else "right", strength=0.5, size=0.55)]
    font, weight = _headline_fonts(var)
    steps.append(_s("badge", "n", "برچسبِ «جدید»", "نشانِ تازه‌بودن", text=cp["badge"] or "جدید", kind="pill", slot="tr", size=0.2, color="accent"))
    steps.append(_s("text", "h", "تیتر", "نامِ محصول یا پیام", text=head, role=_title_role(head), slot=slot, align="right", v="end" if cls != "wide" else "center",
                    font=font, weight=weight, color="white", max_lines=2, plate="none"))
    if cp["subline"]:
        steps.append(_s("text", "s", "متنِ دوم", "توضیحِ کوتاه", text=cp["subline"], role="sub", slot=slot, align="right", below="h", font="vazirmatn",
                        weight=500, color="white", max_lines=2, plate="none"))
    if b["has_logo"]:
        steps.append(_s("logo", "lg", "لوگو", "لوگوی فروشگاه", position="tl", size=0.13))
    return {"recipe": "new_arrival", "format": fmt, "mood": mood, "variation": var, "title": "محصولِ جدید", "steps": steps}


def price_tag(b: dict) -> dict:
    fmt, an, cp, var = b["format"], b["an"], b["copy"], b["variation"]
    cls = grid.class_of(fmt)
    mood = b["mood"] if b["mood"] != "auto" else "vibrant"
    steps = [_s("frame", "f", "قابِ خروجی", f"اندازهٔ {grid.FORMAT_FA.get(fmt, fmt)}", format=fmt, fit="cover", focus="smart"),
             _grade(an, mood, scope="photo", pop=1.0),
             _s("scrim", "sc", "سایهٔ نرم", "تیرگیِ ملایمِ پایین برای برچسبِ قیمت", edge="bottom", strength=0.45, size=0.4)]
    if cp["headline"]:
        font, weight = _headline_fonts(var)
        steps.append(_s("text", "h", "تیتر", "نامِ محصول", text=cp["headline"], role="title", slot="top", align="center", v="start", font=font,
                        weight=weight, color="auto", max_lines=2))
    if cp["old_price"]:
        steps.append(_s("text", "op", "قیمتِ قبلی", "قیمتِ خط‌خورده", text=cp["old_price"], role="sub", slot="bottom", align="center", v="start",
                        color="white", strike=True, font="estedad", weight=500, max_lines=1))
    price = cp["price"] or "قیمت را وارد کنید"
    steps.append(_s("text", "p", "قیمت", "قیمت، درشت در کادرِ رنگی", text=price, role="hero" if len(price) < 14 else "price", slot="bottom",
                    align="center", v="start" if cp["old_price"] else "end", below="op" if cp["old_price"] else "", plate="accent",
                    font="estedad", weight=800, max_lines=1))
    if cp["discount"]:
        steps.append(_s("badge", "d", "برچسبِ تخفیف", "درصدِ تخفیف", text=typo.fa_digits(f"{cp['discount']}٪"), sub="تخفیف", kind="circle", slot="mr",
                        size=0.26, color="accent"))
    if b["has_logo"]:
        steps.append(_s("logo", "lg", "لوگو", "لوگوی فروشگاه", position="tl", size=0.13))
    return {"recipe": "price_tag", "format": fmt, "mood": mood, "variation": var, "title": "برچسبِ قیمت", "steps": steps}


def before_after(b: dict) -> dict:
    fmt, an, var = b["format"], b["an"], b["variation"]
    mood = b["mood"] if b["mood"] != "auto" else "light"
    steps = [_s("frame", "f", "قابِ خروجی", f"اندازهٔ {grid.FORMAT_FA.get(fmt, fmt)}", format=fmt, fit="cover", focus="smart"),
             _grade(an, mood, scope="photo", pop=1.6),
             _s("compare", "cmp", "قبل و بعد", "نیمهٔ راست اصل، نیمهٔ چپ ویرایش‌شده", labels=True, before="قبل", after="بعد")]
    if b["has_logo"]:
        steps.append(_s("logo", "lg", "لوگو", "لوگوی فروشگاه", position="bottom_center", size=0.14))
    return {"recipe": "before_after", "format": fmt, "mood": mood, "variation": var, "title": "قبل و بعد", "steps": steps}


def caption(b: dict) -> dict:
    fmt, an, cp, var = b["format"], b["an"], b["copy"], b["variation"]
    mood = b["mood"]
    steps = [_s("frame", "f", "قابِ خروجی", f"اندازهٔ {grid.FORMAT_FA.get(fmt, fmt)}", format=fmt, fit="cover", focus="smart"),
             _grade(an, mood, scope="photo")]
    if cp["headline"]:
        font, weight = _headline_fonts(var)
        steps.append(_s("scrim", "sc", "سایهٔ خوانایی", "تیرگیِ نرم از سمتی که متن می‌نشیند", edge="auto", strength=0.5, size=0.45))
        steps += _text_steps(cp, grid.class_of(fmt), variation=var, slot="auto", align="center", role=None)
    if b["has_logo"]:
        steps.append(_s("logo", "lg", "لوگو", "لوگوی فروشگاه", position="br", size=0.13))
    return {"recipe": "caption", "format": fmt, "mood": mood, "variation": var, "title": "عکس با متن", "steps": steps}


RECIPES = {
    "product_ad": {"title": "تبلیغ محصول", "help": "محصول روی زمینهٔ هماهنگ با رنگش، با تیتر، قیمت و دکمه", "fn": product_ad, "format": "square",
                   "fields": ["headline", "subline", "price", "cta"]},
    "sale_banner": {"title": "بنرِ تخفیف / حراج", "help": "نوارِ رنگی، تیترِ درشت و برچسبِ درصدِ تخفیف", "fn": sale_banner, "format": "square",
                    "fields": ["headline", "subline", "discount", "cta"]},
    "new_arrival": {"title": "محصولِ جدید", "help": "شیک و آرام با برچسبِ «جدید»", "fn": new_arrival, "format": "portrait",
                    "fields": ["headline", "subline", "badge"]},
    "story": {"title": "استوری", "help": "۹:۱۶ با رعایتِ حاشیهٔ امنِ استوری", "fn": story, "format": "story",
              "fields": ["headline", "subline", "price", "cta"]},
    "catalog_white": {"title": "عکسِ کاتالوگ (زمینهٔ سفید)", "help": "برای دیجی‌کالا، باسلام و کاتالوگ؛ بی متن", "fn": catalog_white, "format": "store",
                      "fields": []},
    "before_after": {"title": "قبل و بعد", "help": "نیمه‌نیمه، با برچسب‌ها", "fn": before_after, "format": "square", "fields": []},
    "price_tag": {"title": "برچسبِ قیمت", "help": "قیمتِ درشت (با قیمتِ قبلیِ خط‌خورده) روی عکس", "fn": price_tag, "format": "square",
                  "fields": ["headline", "price", "old_price", "discount"]},
    "caption": {"title": "عکس با شعار", "help": "یک جمله روی آرام‌ترین جای عکس", "fn": caption, "format": "square", "fields": ["headline", "subline"]},
}


def ui_list() -> list[dict]:
    return [{"key": k, "title": v["title"], "help": v["help"], "format": v["format"], "fields": v["fields"]} for k, v in RECIPES.items()]


def make_plan(recipe: str, brief: dict) -> dict:
    """الگو + یادداشتِ طراحی ⇒ برنامهٔ خام (هنوز وارسی نشده)."""
    spec = RECIPES.get(recipe) or RECIPES["caption"]
    b = dict(brief)
    b.setdefault("variation", 0)
    b["copy"] = merged_copy(b)
    b["format"] = b.get("format") or spec["format"]
    if recipe == "story":
        b["format"] = "story"
    return spec["fn"](b)
