"""ابزارها و دستورهای خودکارِ «ادیتور عکس».

هر ابزار یک جا اجرا می‌شود:

* ``server`` — همین سرورِ سایت با Pillow: سبک، بی هوشِ مصنوعی، وقتی سرورِ پردازش خاموش است هم کار می‌کند
  (برش برای شبکه‌ها، اندازه، چرخش، رنگِ ساده، فیلترِ ساده، متن، لوگو، واترمارک، قالبِ خروجی).
* ``node`` — سرورِ پردازش با کیتِ PersianAiKit.Photo (کارِ ``photo.edit``؛ نسخهٔ ویرایشِ کیت = «recipe»):
  بهبودِ خودکارِ حرفه‌ای، فیلترهای کیت، ۵۸ لغزندهٔ Camera Raw، نویزگیری، شارپ، ترمیمِ لکه، حذف/تعویضِ پس‌زمینه
  (سبک یا BiRefNet)، قابِ مربعِ فروشگاه، بزرگ‌نماییِ Real-ESRGAN و ویرایشِ هوشمند با هوشِ مصنوعیِ بینا.

کلیدها، بازه‌ها و فیلترهای کیت از خودِ کدِ C# خوانده شده‌اند (kit_catalog.json ⇐ scripts/gen_photo_kit_catalog.py).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


class CatalogError(ValueError):
    """پارامتر یا ابزارِ نادرست — متنش برای کاربر است."""


@lru_cache(maxsize=1)
def kit() -> dict:
    return json.loads((Path(__file__).resolve().parent / "kit_catalog.json").read_text(encoding="utf-8"))


def kit_params() -> dict:
    return {p["key"]: p for p in kit()["params"]}


def kit_presets() -> dict:
    return {p["key"]: p for p in kit()["presets"]}


SOCIAL_FORMATS = {
    "square": (1080, 1080, "مربع ۱:۱ (پستِ اینستاگرام)"),
    "portrait": (1080, 1350, "عمودی ۴:۵ (پستِ عمودی)"),
    "story": (1080, 1920, "۹:۱۶ (استوری، ریلز، شورتز)"),
    "landscape": (1200, 630, "افقی ۱٫۹۱:۱ (بنرِ سایت، تلگرام، لینک)"),
    "wide": (1920, 1080, "افقی ۱۶:۹ (یوتیوب، اسلاید)"),
    "store": (2000, 2000, "مربعِ ۲۰۰۰ (دیجی‌کالا، باسلام، ترب)"),
}


def _opt(*pairs):
    return [{"value": v, "label": l} for v, l in pairs]


def _num(key, title, lo, hi, default, step=1, unit="", help_=""):
    return {"key": key, "title": title, "type": "number", "min": lo, "max": hi, "default": default, "step": step,
            "unit": unit, "help": help_}


def _sel(key, title, options, default, help_=""):
    return {"key": key, "title": title, "type": "select", "options": options, "default": default, "help": help_}


def _bool(key, title, default=False, help_=""):
    return {"key": key, "title": title, "type": "bool", "default": default, "help": help_}


def _text(key, title, default="", help_="", max_len=200):
    return {"key": key, "title": title, "type": "text", "default": default, "help": help_, "max": max_len}


def _color(key, title, default="#ffffff"):
    return {"key": key, "title": title, "type": "color", "default": default, "help": ""}


POSITIONS = _opt(("br", "پایین، گوشهٔ راست"), ("bl", "پایین، گوشهٔ چپ"), ("tr", "بالا، گوشهٔ راست"),
                 ("tl", "بالا، گوشهٔ چپ"), ("center", "وسط"))


def _tools() -> list[dict]:
    presets = kit()["presets"]
    return [
        # ─────────────── سرورِ سایت (سبک)
        {"key": "auto_tone", "title": "نور و رنگِ خودکار (سبک)", "where": "server", "icon": "sparkle",
         "help": "کشیدنِ تیره‌ترین و روشن‌ترین بخش‌ها تا دو سرِ هیستوگرام، رفعِ رنگ‌زدگیِ کلی و روشن کردنِ عکسِ تیره — "
                 "بی سرورِ پردازش. نسخهٔ حرفه‌ای‌اش «بهبودِ خودکارِ حرفه‌ای» است.",
         "params": [_num("strength", "شدت", 0, 100, 70)]},
        {"key": "color", "title": "نور و رنگِ ساده", "where": "server", "icon": "sun",
         "help": "روشنی، کنتراست، اشباع، گرمی و تیزی — همان لغزنده‌های ساده‌ای که همه می‌شناسند.",
         "params": [_num("brightness", "روشنی", -100, 100, 0), _num("contrast", "کنتراست", -100, 100, 0),
                    _num("saturation", "اشباعِ رنگ", -100, 100, 0), _num("warmth", "گرمی (منفی = سرد)", -100, 100, 0),
                    _num("sharpness", "تیزی", 0, 100, 0)]},
        {"key": "look", "title": "فیلترِ ساده", "where": "server", "icon": "image",
         "help": "حال‌وهوای آماده روی سرورِ سایت. فیلترهای دقیق‌ترِ کیت در «فیلترِ حرفه‌ای» است.",
         "params": [_sel("style", "فیلتر", _opt(("vivid", "پرجلوه"), ("warm", "گرم"), ("cool", "سرد"), ("bw", "سیاه‌وسفید"),
                                                ("sepia", "قهوه‌ای (قدیمی)"), ("fade", "مات و ملایم")), "vivid"),
                    _num("strength", "شدت", 0, 100, 100)]},
        {"key": "rotate", "title": "چرخش، صاف کردن و قرینه", "where": "server", "icon": "refresh",
         "help": "چرخشِ ۹۰ درجه‌ای، صاف کردنِ افقِ کج (با بریدنِ گوشه‌های خالی) و قرینه.",
         "params": [_sel("turn", "چرخش", _opt(("0", "بی‌چرخش"), ("90", "۹۰° پادساعتگرد"), ("180", "۱۸۰°"),
                                               ("270", "۹۰° ساعتگرد")), "0"),
                    _num("straighten", "صاف کردن (درجه)", -15, 15, 0, 0.5, "°"),
                    _bool("flip_h", "قرینهٔ افقی"), _bool("flip_v", "قرینهٔ عمودی")]},
        {"key": "crop_format", "title": "برش برای شبکه‌ها", "where": "server", "icon": "image",
         "help": "اندازهٔ دقیقِ هر شبکه. «پر کردن» برش می‌زند (جای سوژه را خودش پیدا می‌کند)؛ «جا دادن» چیزی را نمی‌بُرد و "
                 "دورش را با نسخهٔ محوِ خودِ عکس یا یک رنگ پر می‌کند.",
         "params": [_sel("format", "قالب", _opt(*[(k, v[2]) for k, v in SOCIAL_FORMATS.items()]), "square"),
                    _sel("fit", "روش", _opt(("cover", "پر کردن (برش)"), ("contain", "جا دادن (بی‌برش)")), "cover"),
                    _sel("focus", "سوژه کجاست", _opt(("smart", "خودکار"), ("center", "وسط"), ("top", "بالا"),
                                                    ("bottom", "پایین"), ("left", "چپ"), ("right", "راست")), "smart"),
                    _sel("fill", "پرکردنِ دور (جا دادن)", _opt(("blur", "محوِ خودِ عکس"), ("white", "سفید"),
                                                             ("black", "سیاه"), ("color", "رنگِ دلخواه")), "blur"),
                    _color("fill_color", "رنگِ دلخواه", "#f3f4f6")]},
        {"key": "resize", "title": "تغییرِ اندازه", "where": "server", "icon": "image",
         "help": "ضلعِ بلندتر به پیکسل (کوچک کردن؛ بزرگ کردنِ واقعی با «بزرگ‌نماییِ هوشمند» روی سرورِ پردازش است).",
         "params": [_num("long_edge", "ضلعِ بلندتر (پیکسل)", 200, 8000, 1600, 10, "px")]},
        {"key": "text", "title": "متن روی عکس", "where": "server", "icon": "subtitles",
         "help": "متنِ فارسی با فونتِ وزیرمتن و چیدمانِ راست‌به‌چپِ درست (مدل‌های تصویر فارسی نمی‌نویسند؛ این‌جا خودِ برنامه "
                 "می‌نویسد).",
         "params": [_text("text", "متنِ اصلی", "", "مثلاً نامِ محصول یا «تخفیفِ ویژه»", 120),
                    _text("subtext", "خطِ دوم (اختیاری)", "", "مثلاً قیمت", 160),
                    _sel("position", "جا", _opt(("bottom", "پایین"), ("top", "بالا"), ("center", "وسط")), "bottom"),
                    _num("size", "اندازه (٪ عرض)", 2, 16, 6, 0.5, "%"),
                    _color("color", "رنگِ متن", "#ffffff"),
                    _sel("band", "زمینهٔ متن", _opt(("gradient", "سایهٔ تیره"), ("box", "کادرِ تیره"),
                                                    ("light", "کادرِ روشن"), ("none", "بی‌زمینه")), "gradient")]},
        {"key": "logo", "title": "لوگو", "where": "server", "icon": "image",
         "help": "لوگوی فروشگاه (از «پروفایل برند») یا هر عکسی از کتابخانه (PNG ِ شفاف بهتر است) در گوشهٔ عکس.",
         "params": [_sel("source", "کدام لوگو", _opt(("store", "لوگوی فروشگاه"), ("asset", "عکسی از کتابخانه")), "store"),
                    _num("asset", "شمارهٔ عکسِ کتابخانه", 0, 10 ** 9, 0, 1, "", "وقتی «عکسی از کتابخانه» است"),
                    _sel("position", "جا", POSITIONS, "br"),
                    _num("size", "اندازه (٪ عرض)", 5, 50, 18, 1, "%"), _num("opacity", "پیدایی", 10, 100, 90, 1, "%"),
                    _num("margin", "فاصله از لبه", 0, 15, 4, 0.5, "%")]},
        {"key": "watermark", "title": "واترمارکِ متنی", "where": "server", "icon": "shield",
         "help": "نامِ فروشگاه (یا هر متنی) کم‌رنگ روی عکس — گوشه‌ای یا تکرارشونده روی کلِ عکس تا عکس دزدیده نشود.",
         "params": [_text("text", "متن (خالی = نامِ فروشگاه)", "", "", 80),
                    _sel("mode", "حالت", _opt(("corner", "گوشه"), ("tiled", "تکرار روی کلِ عکس")), "corner"),
                    _sel("position", "جا (حالتِ گوشه)", POSITIONS, "bl"),
                    _num("size", "اندازه (٪ عرض)", 2, 15, 4, 0.5, "%"), _num("opacity", "پیدایی", 5, 100, 40, 1, "%"),
                    _color("color", "رنگ", "#ffffff")]},
        {"key": "export", "title": "قالب و حجمِ خروجی", "where": "server", "icon": "upload",
         "help": "JPEG برای عکس، PNG برای شفاف، WebP برای سایت؛ با «حداکثر حجم» کیفیت آن‌قدر پایین می‌آید که فایل جا شود.",
         "params": [_sel("format", "قالب", _opt(("jpeg", "JPEG"), ("png", "PNG (شفاف)"), ("webp", "WebP")), "jpeg"),
                    _num("quality", "کیفیت", 40, 100, 90), _num("max_kb", "حداکثر حجم (کیلوبایت، ۰ = آزاد)", 0, 20000, 0, 10, "KB")]},

        # ─────────────── سرورِ پردازش (کیتِ PersianAiKit.Photo)
        {"key": "kit_auto", "title": "بهبودِ خودکارِ حرفه‌ای", "where": "node", "icon": "sparkle",
         "help": "کیت عکس را اندازه می‌گیرد و خودش تعادلِ سفیدی، نوردهی، سیاه/سفید، روشنی‌ها/سایه‌ها، کنتراست، مه، وایبرنس، "
                 "نویز و شارپ را تنظیم می‌کند (Auto Tone/Contrast/Color ِ Camera Raw).",
         "params": []},
        {"key": "kit_preset", "title": "فیلترِ حرفه‌ای", "where": "node", "icon": "image",
         "help": "فیلترهای آمادهٔ کیت (مثلِ پریست‌های لایت‌روم).",
         "params": [_sel("preset", "فیلتر", [{"value": p["key"], "label": p["title"], "help": p["help"]}
                                             for p in presets if p["kind"] == "look"], "clean")]},
        {"key": "kit_adjust", "title": "تنظیمِ دستیِ حرفه‌ای (Camera Raw)", "where": "node", "icon": "settings",
         "help": "۵۸ لغزندهٔ کیت: نور، رنگ، رنگ‌به‌رنگ (HSL)، رنگ‌دهیِ سایه/روشنی، سطوح، بافت/وضوح/مه، شارپ و نویز، "
                 "وینیت و دانه، اعوجاجِ لنز.",
         "params": [{"key": "adjust", "title": "لغزنده‌ها", "type": "adjust", "default": {}, "help": ""}]},
        {"key": "kit_denoise", "title": "نویزگیری", "where": "node", "icon": "sparkle",
         "help": "Non-Local Means ِ کیت روی روشنایی و رنگ — عکسِ شب و ISO بالا.",
         "params": [_num("luma", "نویزِ روشنایی", 0, 100, 40), _num("color", "نویزِ رنگ", 0, 100, 40)]},
        {"key": "kit_sharpen", "title": "شارپِ حرفه‌ای", "where": "node", "icon": "sparkle",
         "help": "ماسکِ غیرشارپ روی روشنایی با ماسکِ لبه (پوست و آسمان دست نمی‌خورد).",
         "params": [_num("amount", "مقدار", 0, 150, 50), _num("radius", "شعاع", 0.5, 3, 1, 0.1, "px"),
                    _num("masking", "فقط لبه‌ها", 0, 100, 30)]},
        {"key": "kit_heal", "title": "ترمیمِ لکه", "where": "node", "icon": "sparkle", "single": True,
         "help": "روی عکس کلیک کنید تا لکه، گرد یا خراشِ کوچک با اطرافش پر شود (Spot Healing). فقط برای یک عکس.",
         "params": [{"key": "spots", "title": "لکه‌ها", "type": "spots", "default": [], "help": ""}]},
        {"key": "kit_background", "title": "حذف یا تعویضِ پس‌زمینه", "where": "node", "icon": "image",
         "help": "«خودکار»: زمینهٔ ساده/استودیویی بی مدل (زیرِ یک ثانیه)، وگرنه هوشِ مصنوعیِ BiRefNet؛ لبه خودکار تمیز می‌شود "
                 "و سایهٔ نرمِ زیرِ کالا اختیاری است.",
         "params": [_sel("method", "روش", _opt(("auto", "خودکار"), ("quick", "سبک (زمینهٔ ساده)"),
                                               ("ai", "هوشِ مصنوعی (BiRefNet)")), "auto"),
                    _sel("bg", "زمینهٔ تازه", _opt(("white", "سفید"), ("transparent", "شفاف (PNG)"),
                                                  ("color", "رنگِ دلخواه")), "white"),
                    _color("color", "رنگِ دلخواه", "#f5f5f5"),
                    _num("shadow", "سایهٔ زیرِ کالا", 0, 100, 20),
                    _num("cleanup", "تمیزکاریِ لبه (−۱ = خودکار)", -1, 100, -1)]},
        {"key": "kit_square", "title": "قابِ مربعِ فروشگاه (کالا وسط)", "where": "node", "icon": "box",
         "help": "کالا وسطِ قابِ مربع با حاشیه (با حذفِ پس‌زمینه، کادرِ خودِ کالا؛ بی آن، کلِ عکس).",
         "params": [_num("long_edge", "ضلعِ قاب (پیکسل)", 500, 4000, 2000, 10, "px"),
                    _num("padding", "حاشیه", 0, 40, 6, 1, "%")]},
        {"key": "kit_upscale", "title": "بزرگ‌نماییِ هوشمند (Real-ESRGAN)", "where": "node", "icon": "sparkle",
         "help": "۲ یا ۴ برابر با بازسازیِ جزئیات (برای عکسِ کوچک یا فشرده). سقفِ خروجی ۴۰۹۶ پیکسل.",
         "params": [_sel("factor", "چند برابر", _opt(("2", "۲ برابر"), ("4", "۴ برابر")), "2")]},
        {"key": "kit_smart", "title": "ویرایشِ هوشمند با دستور", "where": "node", "icon": "bulb",
         "help": "هوشِ مصنوعیِ بینای سرورِ پردازش عکسِ کوچک و اندازه‌گیری‌ها را می‌بیند و لغزنده‌های کیت را تنظیم می‌کند؛ یک "
                 "بار نتیجه را می‌بیند و اصلاح می‌کند. بی مدلِ بینا ⇐ همان بهبودِ خودکار.",
         "params": [_text("goal", "چه می‌خواهید؟", "", "مثلاً: گرم و روشن، مناسبِ اینستاگرامِ کافه", 300)]},
    ]


@lru_cache(maxsize=1)
def tools() -> dict:
    return {t["key"]: t for t in _tools()}


def tool_list() -> list[dict]:
    return list(tools().values())


# ───────────────────────────── دستورهای خودکار

def _o(tool, optional=False, on=True, **params):
    return {"tool": tool, "params": params, "optional": optional, "on": on}


RECIPES = [
    {"key": "suggest", "title": "پیشنهادِ خودکار", "help": "از روی اندازه‌گیریِ همان عکس: فقط آن‌چه لازم است.",
     "operations": []},
    {"key": "instagram_post", "title": "پستِ اینستاگرام", "help": "بهبودِ نور و رنگ + برشِ مربعِ ۱۰۸۰ با سوژه در کادر.",
     "operations": [_o("kit_auto", optional=True), _o("auto_tone", optional=True, on=False, strength=60),
                    _o("crop_format", format="square", fit="cover", focus="smart"),
                    _o("export", format="jpeg", quality=90)]},
    {"key": "instagram_portrait", "title": "پستِ عمودی (۴:۵)", "help": "بیشترین جای صفحه در فیدِ اینستاگرام: ۱۰۸۰×۱۳۵۰.",
     "operations": [_o("kit_auto", optional=True), _o("auto_tone", optional=True, on=False, strength=60),
                    _o("crop_format", format="portrait", fit="cover", focus="smart"),
                    _o("export", format="jpeg", quality=90)]},
    {"key": "story", "title": "استوری و ریلز (۹:۱۶)", "help": "۱۰۸۰×۱۹۲۰ بی بریدنِ محصول: دورِ عکس با نسخهٔ محوِ خودش پر می‌شود.",
     "operations": [_o("kit_auto", optional=True), _o("auto_tone", optional=True, on=False, strength=60),
                    _o("crop_format", format="story", fit="contain", fill="blur"),
                    _o("export", format="jpeg", quality=90)]},
    {"key": "product_white", "title": "عکسِ محصول با پس‌زمینهٔ سفید",
     "help": "همان «عکسِ فروشگاهیِ» کیت: پس‌زمینه برداشته، سفید با سایهٔ نرم، کالا وسطِ مربعِ ۲۰۰۰ با حاشیهٔ ۶٪، شارپ.",
     "operations": [_o("kit_adjust", adjust={"whites": 15, "clarity": 10, "vibrance": 10}),
                    _o("kit_sharpen", amount=40, radius=1, masking=40),
                    _o("kit_background", method="auto", bg="white", shadow=25, cleanup=-1),
                    _o("kit_square", long_edge=2000, padding=6),
                    _o("export", format="jpeg", quality=92)]},
    {"key": "product_transparent", "title": "کالا بی‌پس‌زمینه (PNG)", "help": "کالا روی زمینهٔ شفاف، برای طراحی و بنر.",
     "operations": [_o("kit_adjust", adjust={"clarity": 10}), _o("kit_sharpen", amount=35, radius=1, masking=30),
                    _o("kit_background", method="auto", bg="transparent", shadow=0, cleanup=-1),
                    _o("export", format="png", quality=90)]},
    {"key": "enhance", "title": "بهبودِ کیفیتِ حرفه‌ای", "help": "بهبودِ خودکارِ کیت + بزرگ‌نماییِ ×۲ برای عکسِ کوچک.",
     "operations": [_o("kit_auto"), _o("kit_upscale", optional=True, on=False, factor="2"),
                    _o("export", format="jpeg", quality=92)]},
    {"key": "banner", "title": "بنرِ سایت و تلگرام", "help": "افقیِ ۱۲۰۰×۶۳۰ با متنِ فارسی روی عکس.",
     "operations": [_o("kit_auto", optional=True), _o("auto_tone", optional=True, on=False, strength=60),
                    _o("crop_format", format="landscape", fit="cover", focus="smart"),
                    _o("text", text="", subtext="", position="bottom", size=6, color="#ffffff", band="gradient"),
                    _o("export", format="jpeg", quality=90)]},
    {"key": "quick_fix", "title": "اصلاحِ سریع (بی سرورِ پردازش)", "help": "نور و رنگِ خودکارِ سبک + کمی تیزی، همین حالا.",
     "operations": [_o("auto_tone", strength=70), _o("color", sharpness=25), _o("export", format="jpeg", quality=90)]},
    {"key": "brand", "title": "لوگو و واترمارک", "help": "لوگوی فروشگاه در گوشه؛ واترمارکِ متنی اختیاری.",
     "operations": [_o("logo", source="store", position="br", size=18, opacity=90, margin=4),
                    _o("watermark", optional=True, on=False, text="", mode="tiled", size=4, opacity=20),
                    _o("export", format="jpeg", quality=92)]},
    {"key": "smart", "title": "ویرایش با دستور (هوشِ مصنوعی)", "help": "بگویید چه می‌خواهید؛ هوشِ مصنوعیِ بینا تنظیم می‌کند.",
     "operations": [_o("kit_smart", goal=""), _o("export", format="jpeg", quality=92)]},
    {"key": "manual", "title": "دستی", "help": "ابزارها را خودتان یکی‌یکی اضافه کنید.", "operations": []},
]
RECIPE_BY_KEY = {r["key"]: r for r in RECIPES}


def recipe_list() -> list[dict]:
    out = []
    for r in RECIPES:
        ops = [dict(o, params=normalize_params(o["tool"], o["params"], strict=False)) for o in r["operations"]]
        out.append({"key": r["key"], "title": r["title"], "help": r["help"], "operations": ops,
                    "needs_node": any(tools()[o["tool"]]["where"] == "node" and not o["optional"] for o in ops)})
    return out


# ───────────────────────────── وارسیِ پارامترها

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clamp(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return max(lo, min(hi, x))


def normalize_params(tool_key: str, params: dict | None, *, strict: bool = True) -> dict:
    """پارامترها را به بازهٔ مجاز می‌برد؛ کلیدِ ناشناخته دور ریخته می‌شود."""
    spec = tools().get(tool_key)
    if spec is None:
        raise CatalogError(f"ابزارِ «{tool_key}» نیست.")
    params = params if isinstance(params, dict) else {}
    out = {}
    for p in spec["params"]:
        k, t, v = p["key"], p["type"], params.get(p["key"], p["default"])
        if t == "number":
            x = _clamp(v, p["min"], p["max"], p["default"])
            out[k] = int(round(x)) if float(p.get("step", 1)).is_integer() else round(x, 3)
        elif t == "select":
            allowed = [o["value"] for o in p["options"]]
            v = str(v)
            if v not in allowed:
                if strict and k in params:
                    raise CatalogError(f"«{p['title']}» در «{spec['title']}» باید یکی از {', '.join(allowed)} باشد.")
                v = p["default"]
            out[k] = v
        elif t == "bool":
            out[k] = v in (True, 1, "1", "true", "True", "on")
        elif t == "text":
            out[k] = str(v or "").strip()[: p.get("max", 200)]
        elif t == "color":
            out[k] = v if isinstance(v, str) and _HEX.match(v) else p["default"]
        elif t == "adjust":
            catalog = kit_params()
            adj = {}
            for key, val in (v or {}).items() if isinstance(v, dict) else []:
                c = catalog.get(key)
                if c is None:
                    continue
                x = _clamp(val, c["min"], c["max"], c["default"])
                if abs(x - c["default"]) > 1e-9:
                    adj[key] = round(x, 3)
            out[k] = adj
        elif t == "spots":
            spots = []
            for s in (v or [])[:60] if isinstance(v, list) else []:
                if isinstance(s, dict):
                    spots.append({"x": round(_clamp(s.get("x"), 0, 1, 0.5), 4), "y": round(_clamp(s.get("y"), 0, 1, 0.5), 4),
                                  "r": round(_clamp(s.get("r"), 0.002, 0.2, 0.02), 4)})
            out[k] = spots
    if tool_key == "kit_preset" and out.get("preset") not in kit_presets():
        out["preset"] = "clean"
    return out


def normalize_operations(ops) -> list[dict]:
    """[{tool, params, on?}] ⇐ فقط آن‌هایی که روشن‌اند، با پارامترهای وارسی‌شده؛ کارهای سرورِ پردازش اول."""
    if not isinstance(ops, list):
        raise CatalogError("operations باید فهرست باشد.")
    if len(ops) > 30:
        raise CatalogError("بیشتر از ۳۰ کار در یک نسخه نمی‌شود.")
    clean = []
    for o in ops:
        if not isinstance(o, dict):
            raise CatalogError("هر کار باید {tool, params} باشد.")
        if o.get("on") is False:
            continue
        key = str(o.get("tool") or "")
        params = normalize_params(key, o.get("params"))
        if key == "kit_smart" and not params["goal"]:
            raise CatalogError("برای «ویرایشِ هوشمند» بنویسید چه می‌خواهید.")
        if key == "text" and not (params["text"] or params["subtext"]):
            raise CatalogError("برای «متن روی عکس» متن بنویسید (یا این کار را بردارید).")
        if key == "kit_heal" and not params["spots"]:
            raise CatalogError("برای «ترمیمِ لکه» روی عکس کلیک کنید تا لکه‌ها علامت بخورند.")
        clean.append({"tool": key, "params": params})
    node = [o for o in clean if tools()[o["tool"]]["where"] == "node"]
    server = [o for o in clean if tools()[o["tool"]]["where"] == "server"]
    if sum(1 for o in node if o["tool"] == "kit_smart") > 1:
        raise CatalogError("«ویرایشِ هوشمند» یک بار کافی است.")
    exports = [o for o in server if o["tool"] == "export"]
    server = [o for o in server if o["tool"] != "export"] + exports[-1:]   # قالبِ خروجی همیشه آخر
    return node + server


def split(ops: list[dict]) -> tuple[list[dict], list[dict]]:
    node = [o for o in ops if tools()[o["tool"]]["where"] == "node"]
    return node, [o for o in ops if tools()[o["tool"]]["where"] == "server"]


def titles(ops: list[dict]) -> list[str]:
    return [tools()[o["tool"]]["title"] for o in ops if o["tool"] in tools()]


# ───────────────────────────── کارهای کیت ⇐ یک «نسخهٔ ویرایش» (recipe) برای photo.edit

def kit_payload(node_ops: list[dict], *, has_server_after: bool, final_format: str | None = None) -> dict:
    """همهٔ کارهای کیت در یک کارِ photo.edit: {"recipe": {...}, "auto": bool, "goal": str}.

    کیت ترتیبِ خودش را دارد (مثلِ Camera Raw: لکه ⇐ نور و رنگ ⇐ … ⇐ پس‌زمینه ⇐ قاب)، پس ترتیبِ کارها این‌جا مهم
    نیست. خروجیِ کیت اگر کارِ سرورِ سایت دنبالش است JPEG با کیفیتِ ۹۵ (یا PNG وقتی شفاف است) — فشرده‌سازیِ دوباره
    دیده نمی‌شود و آپلودِ سرورِ پردازش کوچک می‌ماند.
    """
    recipe: dict = {}
    adjust: dict = {}
    payload: dict = {}
    transparent = False
    for o in node_ops:
        t, p = o["tool"], o["params"]
        if t == "kit_auto":
            payload["auto"] = True
        elif t == "kit_preset":
            recipe["preset"] = p["preset"]
        elif t == "kit_adjust":
            adjust.update(p["adjust"])
        elif t == "kit_denoise":
            adjust.update({"noiseLuma": p["luma"], "noiseColor": p["color"]})
        elif t == "kit_sharpen":
            adjust.update({"sharpen": p["amount"], "sharpenRadius": p["radius"], "sharpenMasking": p["masking"]})
        elif t == "kit_heal":
            recipe["spots"] = p["spots"]
        elif t == "kit_background":
            color = {"white": "#ffffff", "transparent": "transparent"}.get(p["bg"], p["color"])
            transparent = color == "transparent"
            recipe["background"] = {"remove": True, "method": p["method"], "color": color,
                                    "cleanup": p["cleanup"], "shadow": p["shadow"]}
        elif t == "kit_square":
            out = recipe.setdefault("output", {})
            out.update({"square": True, "longEdge": p["long_edge"], "padding": round(p["padding"] / 100, 3)})
        elif t == "kit_upscale":
            recipe.setdefault("output", {})["upscale"] = int(p["factor"])
        elif t == "kit_smart":
            payload["goal"] = p["goal"]
    if adjust:
        recipe["adjust"] = adjust
    out = recipe.setdefault("output", {})
    if transparent:
        out.update({"format": "png", "quality": 95})
    elif has_server_after or not final_format:
        out.update({"format": "jpeg", "quality": 95})
    else:
        out.update({"format": final_format if final_format in ("jpeg", "png", "webp") else "jpeg", "quality": 92})
    payload["recipe"] = recipe
    return payload


# ───────────────────────────── پیشنهاد از روی اندازه‌گیری

def suggest(facts: dict, findings: list[dict], *, node_online: bool) -> list[dict]:
    """کارهای لازم برای همین عکس، هر کدام با دلیلش. کارِ سرورِ پردازش وقتی خاموش است تیک نمی‌خورد (جایگزینِ سبک دارد)."""
    what = {f["what"]: f for f in findings}
    ops: list[dict] = []

    def add(tool, reason, optional=False, on=True, **params):
        ops.append({"tool": tool, "params": normalize_params(tool, params, strict=False), "reason": reason,
                    "optional": optional, "on": on})

    tone = [k for k in ("dark", "bright", "flat", "cast", "clipped") if k in what]
    if tone or "noisy" in what:
        why = "، ".join(what[k]["note"] for k in tone + (["noisy"] if "noisy" in what else []))
        add("kit_auto", why + " ⇐ کیت نور، رنگ و نویز را با هم درست می‌کند.", optional=True, on=node_online)
        add("auto_tone", why + " ⇐ نسخهٔ سبک روی همین سرور" + ("" if not node_online else " (اگر نمی‌خواهید منتظرِ سرورِ پردازش بمانید)"),
            optional=True, on=not node_online, strength=75 if "dark" in what or "flat" in what else 60)
    if "blurry" in what:
        add("kit_sharpen", what["blurry"]["note"] + " ⇐ شارپِ لبه‌ها.", optional=True, on=node_online,
            amount=60, radius=1.2, masking=35)
        add("color", what["blurry"]["note"] + " ⇐ تیزیِ سبک روی همین سرور.", optional=True, on=not node_online, sharpness=40)
    if "small" in what:
        add("kit_upscale", what["small"]["note"] + " ⇐ بزرگ‌نماییِ هوشمند ×۲.", optional=True, on=node_online, factor="2")
    if "plain_bg" in what:
        add("kit_background", what["plain_bg"]["note"] + " ⇐ اگر عکسِ محصول است، زمینهٔ سفیدِ تمیز.", optional=True, on=False,
            method="auto", bg="white", shadow=20)
    if "huge" in what:
        add("resize", what["huge"]["note"] + " ⇐ کوچک‌تر برای وب و شبکه‌ها.", long_edge=2400)
    add("export", "قالبِ خروجی", format="png" if facts.get("has_alpha") else "jpeg", quality=90)
    return ops
