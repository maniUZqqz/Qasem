"""کتابخانهٔ «سبک تصویر»: واژگان و نرمال‌کننده‌ها.

SOURCE: ported from InstAI:instai/styles/schema.py @ 2f8aa90, adapted for store advertising (NMarketing).

یک «سبک» (look) ظاهرِ تصویر را توصیف می‌کند: درجهٔ واقع‌نمایی + نوعِ دقیقِ هنر/انیمیشن + تکه‌دستورهای تصویر (مثبت/منفی)
+ تکه‌دستورِ ویدیو + پالتِ ۶ رنگ. یک «تمِ رنگی» (theme) پالت، نور و حال‌وهواست. هر دو در کد نگه داشته می‌شوند (فقط‌خواندنی).

تفاوت با InstAI (کارِ سریال/قسمت):
* حذف شد: فهرستِ «techniques»، «fps_feel»، پروفایلِ زیرنویس/تایپوگرافیِ تم، و پیوندِ «نردبانِ واقع‌نمایی ⇄ تم».
* افزوده شد: ``ad_fit`` (کدام تبلیغ) و ``product_safe`` (برای عکسی که محصولِ واقعی در آن است مجاز است؟) — در fit.py پر می‌شوند.
* ``gen.model`` به مدل‌هایی نگاشت می‌شود که NM واقعاً دارد (FLUX dev/schnell، SDXL، Z-Image)؛ شناسهٔ workflow های InstAI نیامده.

قاعدهٔ مجوز: در نام، توضیح، برچسب و دستورِ هیچ سبکی نامِ استودیو، فرانچایز، برند، هنرمند یا سازندهٔ محتوا نیست (آزمونِ tests_library).
سبک‌ها با ویژگی‌های بصریِ عمومی توصیف شده‌اند تا خروجی با کارِ صاحبِ حقِ مشخصی اشتباه گرفته نشود.
"""
from __future__ import annotations

import re
from typing import Any

# نردبانِ واقع‌نمایی، از عکس تا انتزاعی. ``anime_like`` = نیمه‌واقع با ویژگی‌های انیمه.
REALISM = {
    "realistic": {"fa": "واقع‌گرا", "en": "Realistic", "order": 1},
    "semi_realistic": {"fa": "نیمه‌واقع‌گرا", "en": "Semi-realistic", "order": 2},
    "anime_like": {"fa": "شبیه انیمه", "en": "Anime-like", "order": 3},
    "anime": {"fa": "انیمه", "en": "Anime", "order": 4},
    "cartoon": {"fa": "کارتون ۲بعدی", "en": "2D cartoon", "order": 5},
    "cartoon_3d": {"fa": "سه‌بعدی / عروسکی", "en": "3D / puppet", "order": 6},
    "graphic": {"fa": "گرافیکی و ساده", "en": "Graphic & flat", "order": 7},
    "stylized_art": {"fa": "هنری و دست‌ساز", "en": "Stylised handmade", "order": 8},
}
REALISM_ORDER = [k for k, _ in sorted(REALISM.items(), key=lambda kv: kv[1]["order"])]

FAMILIES = {
    "live_like": {"fa": "نمای زنده", "en": "Live-action look"},
    "illustration": {"fa": "تصویرسازی", "en": "Illustration"},
    "anime": {"fa": "انیمه", "en": "Anime"},
    "western_2d": {"fa": "کارتون غربی", "en": "Western 2D"},
    "cg_3d": {"fa": "سه‌بعدی (CG)", "en": "3D (CG)"},
    "stop_motion": {"fa": "استاپ‌موشن", "en": "Stop-motion"},
    "graphic": {"fa": "گرافیک متحرک", "en": "Motion graphics"},
    "handmade": {"fa": "دست‌ساز و هنری", "en": "Handmade / art"},
}

# رویکردِ حرکت (برای ریلز/استوری؛ موشنِ NM در کارِ دیگری از آن استفاده می‌کند).
ANIMATIONS = {
    "live_camera": {"fa": "حرکت دوربین سینمایی", "en": "Cinematic camera moves"},
    "limited_2d": {"fa": "انیمیشن محدود ۲بعدی (روی ۲ و ۳)", "en": "Limited 2D (on twos/threes)"},
    "full_2d": {"fa": "انیمیشن کامل و روان ۲بعدی", "en": "Full 2D (fluid)"},
    "rubber_hose": {"fa": "کش‌وقوسیِ قدیمی", "en": "Rubber-hose bounce"},
    "cutout": {"fa": "برش کاغذی / عروسک لایه‌ای", "en": "Cut-out / layered puppet"},
    "motion_graphics": {"fa": "موشن‌گرافیک", "en": "Motion graphics"},
    "stop_motion": {"fa": "استاپ‌موشن (روی ۲ و ۴)", "en": "Stop-motion (on twos/fours)"},
    "cg_3d": {"fa": "سه‌بعدی کامپیوتری", "en": "3D CG"},
    "toon_3d": {"fa": "سه‌بعدی با سایه‌ی کارتونی", "en": "Toon-shaded 3D"},
    "painted_parallax": {"fa": "نقاشی متحرک با پارالاکس", "en": "Painted art with parallax"},
}

# محورِ اصلیِ مرور: ظاهر از کجا می‌آید.
GROUPS = {
    "cinematic": {"fa": "سینمایی و واقع‌نما", "en": "Cinematic & realistic", "order": 1},
    "anime_toon": {"fa": "انیمه و کارتون", "en": "Anime & cartoon", "order": 2},
    "hand_drawn": {"fa": "نقاشی و طراحیِ دست", "en": "Drawn & painted", "order": 3},
    "cg_3d": {"fa": "سه‌بعدی و CGI", "en": "3D & CGI", "order": 4},
    "craft": {"fa": "دست‌ساز و استاپ‌موشن", "en": "Handmade & stop-motion", "order": 5},
    "graphic_design": {"fa": "جنبش‌های گرافیکی", "en": "Graphic design movements", "order": 6},
    "motion_type": {"fa": "موشن و تایپوگرافی", "en": "Motion & typography", "order": 7},
    "retro_digital": {"fa": "رترو و دیجیتال", "en": "Retro & digital", "order": 8},
}
GROUP_ORDER = [k for k, _ in sorted(GROUPS.items(), key=lambda kv: kv[1]["order"])]

# مناسبِ چه چیزی: تصویر ثابت، ویدیو (وقتی مدلِ تصویر-به-ویدیو حرکتش می‌دهد هم پایدار می‌ماند)، شخصیتِ تکرارشونده.
SUITABILITY = ["image", "video", "character"]
ASPECTS = ["9:16", "1:1", "16:9", "4:5"]

# کجا به کار می‌آید (تبلیغِ فروشگاه). product_photo = عکسی که محصولِ واقعی در آن می‌ماند (فقط نور/صحنه).
AD_FITS = {
    "product_photo": {"fa": "عکسِ محصول"},
    "poster": {"fa": "پوستر"},
    "social_post": {"fa": "پستِ شبکه‌های اجتماعی"},
    "reel": {"fa": "ریلز و ویدیوی کوتاه"},
    "story": {"fa": "استوری"},
}

# مدل‌هایی که NM دارد (processing/downloads/image.json). «sdxl_anime» نامِ قدیمیِ InstAI است و به sdxl نگاشت می‌شود.
BASE_MODELS = ["flux_dev", "flux_schnell", "sdxl", "zimage", "any"]
MODEL_ALIASES = {"sdxl_anime": "sdxl"}
#: هر مدل در NM با کدام جریانِ کار/بسته اجرا می‌شود (فقط توضیح برای پنل و مستندات؛ جریانِ واقعیِ تبلیغ را خودِ ویژگی انتخاب می‌کند)
MODEL_WORKFLOWS = {
    "flux_dev": "flux_txt2img / flux_img_edit (FLUX.1 dev fp8)",
    "flux_schnell": "FLUX.1 schnell fp8 (۴ گام)",
    "sdxl": "SDXL base / RealVisXL",
    "zimage": "Z-Image Turbo",
    "any": "هر مدلِ تصویرِ موجود",
}
# راهنمای تولیدِ هر سبک فقط «توصیه» است (گام‌ها اعمال می‌شود؛ بقیه برای نمایش به مالک)؛ هیچ نامِ فایلی نمی‌دهد که گره شاید نداشته باشد.
GEN_FIELDS = {"model": "flux_dev", "alt_model": "", "lora": [], "sampler": "euler", "scheduler": "simple", "cfg": 1.0, "guidance": 3.5, "steps": 24, "aspect": "9:16"}

STYLE_FIELDS = {
    "name_fa": "", "name_en": "", "description_fa": "", "description_en": "", "realism": "anime", "family": "anime", "animation": "limited_2d",
    "image_positive": "", "image_negative": "", "video_positive": "", "video_negative": "", "palette": [], "lighting": "",
    "mood": "", "sample_prompt": "", "theme_key": "", "tags": [], "notes": "",
    # کتابخانهٔ هنر/انیمیشن: گروهِ مرور، مناسبِ چه چیزی، راهنمای تولید و الگوی تصویرِ نمونهٔ داخلی
    "group": "", "suitability": ["image", "video", "character"], "gen": dict(GEN_FIELDS), "motif": "",
    # بخشِ فروشگاه (fit.py)
    "ad_fit": [], "product_safe": False,
}
THEME_FIELDS = {
    "name_fa": "", "name_en": "", "description_fa": "", "description_en": "",
    # ترتیبِ پالت: زمینه، اصلی، دوم، تأکید، سایه، روشن
    "palette": [], "lighting": "", "mood": "", "prompt_fragment": "", "negative_fragment": "", "tags": [], "notes": "",
}
PALETTE_ROLES = ["background", "primary", "secondary", "accent", "shadow", "highlight"]

_KEY = re.compile(r"[^a-z0-9_]+")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def slug(text: str, fallback: str = "preset") -> str:
    s = _KEY.sub("_", (text or "").lower().strip()).strip("_")
    return (s or fallback)[:60]


def _str(v: Any, default: str = "") -> str:
    return default if v is None else str(v).strip()


def _str_list(v: Any, limit: int = 40) -> list[str]:
    if isinstance(v, str):
        v = re.split(r"[,\n،]", v)
    return [str(x).strip() for x in (v or []) if str(x).strip()][:limit]


def _palette(v: Any) -> list[str]:
    out = []
    for c in v or []:
        c = str(c).strip()
        if _HEX.match(c):
            out.append(c.upper())
    return out[:8]


def normalize_style(data: dict | None) -> dict:
    """یک دیکشنریِ کامل و امن: کلیدِ ناشناخته دور ریخته می‌شود، شمارشی‌ها محدود می‌شوند، پالت فقط رنگِ معتبر دارد.

    کلیدهای حذف‌شده‌ی InstAI (``techniques``، ``fps_feel``) اگر در داده‌ها باشند بی‌صدا دور ریخته می‌شوند؛ پس ردیف‌های کپی‌شده بدونِ تغییر کار می‌کنند."""
    d = data or {}
    out: dict[str, Any] = {}
    for k, default in STYLE_FIELDS.items():
        v = d.get(k, default)
        if k == "palette":
            v = _palette(v)
        elif k in ("tags", "ad_fit"):
            v = _str_list(v)
            if k == "ad_fit":
                v = [x for x in v if x in AD_FITS]
        elif k == "suitability":
            v = [x for x in _str_list(v) if x in SUITABILITY] or list(default)
        elif k == "gen":
            v = normalize_gen(v)
        elif k == "group":
            v = _str(v) if _str(v) in GROUPS else ""
        elif k == "motif":
            v = _KEY.sub("", _str(v).lower())[:24]
        elif k == "product_safe":
            v = bool(v)
        else:
            v = _str(v, default if isinstance(default, str) else "")
        out[k] = v
    if out["realism"] not in REALISM:
        out["realism"] = "anime"
    if out["family"] not in FAMILIES:
        out["family"] = "anime"
    if out["animation"] not in ANIMATIONS:
        out["animation"] = "limited_2d"
    return out


def _model(v: Any) -> str:
    v = MODEL_ALIASES.get(str(v or ""), str(v or ""))
    return v if v in BASE_MODELS else ""


def normalize_gen(v: Any) -> dict:
    """راهنمای تولید: عددهای محدودشده، مدل‌های شناخته‌شده و بُعدِ تصویر. هرگز خطا نمی‌دهد."""
    base = dict(GEN_FIELDS)
    d = v if isinstance(v, dict) else {}
    for k in ("sampler", "scheduler"):
        if _str(d.get(k)):
            base[k] = _str(d[k])[:32]
    base["model"] = _model(d.get("model")) or base["model"]
    base["alt_model"] = _model(d.get("alt_model"))
    base["lora"] = [x[:120] for x in _str_list(d.get("lora"), 6)]
    if d.get("aspect") in ASPECTS:
        base["aspect"] = d["aspect"]
    for k, lo, hi, cast in (("cfg", 0.0, 30.0, float), ("guidance", 0.0, 30.0, float), ("steps", 4, 60, int)):
        try:
            base[k] = max(lo, min(hi, cast(d[k]))) if k in d else base[k]
        except (TypeError, ValueError):
            pass
    return base


def normalize_theme(data: dict | None) -> dict:
    d = data or {}
    out: dict[str, Any] = {}
    for k, default in THEME_FIELDS.items():
        v = d.get(k, default)
        if k == "palette":
            v = _palette(v)
        elif k == "tags":
            v = _str_list(v)
        else:
            v = _str(v)
        out[k] = v
    return out
