"""کتابخانهٔ ثابت‌های حرکت: منحنی‌های شتاب، فنرها، حرکت‌های دوربین، خروج‌ها، گذارها و «ناحیهٔ امنِ» هر پلتفرم.

مدل هرگز منحنی یا عددِ فنر نمی‌نویسد؛ فقط یک «نام» از همین فهرست‌ها برمی‌دارد. هر نام در `motion/remotion/src/presets.ts` (و anim.ts) هم هست
و یک آزمون (tests_lib.py) این دو فهرست را با هم مقایسه می‌کند.
"""
from __future__ import annotations

from . import catalog

#: نامِ منحنی ⇒ توضیحِ فارسی (cubic-bezier / spring در presets.ts)
EASES = {
    "linear": "خطی (سرعتِ ثابت؛ فقط برای نوارِ پیشرفت و چرخشِ دائمی)",
    "smooth": "نرم (آرام از دو سو؛ جابه‌جاییِ وسطِ صفحه)",
    "out": "ورودِ ساده (تند شروع، آرام تمام)",
    "in": "خروجِ ساده (آرام شروع، تند تمام)",
    "out-soft": "ورودِ نرم و لوکس",
    "out-expo": "ورودِ تند و دقیق (پیش‌فرضِ خوب)",
    "in-out-expo": "شتابِ سینمایی (هم‌زمان تند و آرام)",
    "snap": "ناگهانی و دقیق",
    "back": "کمی از هدف رد می‌شود و برمی‌گردد",
    "in-back": "کمی عقب می‌کشد و می‌رود",
    "elastic": "کشسان",
    "bounce": "پرشی",
}
SPRINGS = {
    "gentle": "آرام", "smooth": "نرم", "snappy": "تند و تیز", "crisp": "سفت و بی‌جهش", "bouncy": "بازیگوش (جهش)",
    "elastic": "کشسان", "heavy": "سنگین", "slow-reveal": "رونمایی آهسته",
}
CAMERA_MOVES = {
    "none": "ثابت", "push-in": "نزدیک شدن", "pull-out": "دور شدن", "pan-left": "پن به چپ", "pan-right": "پن به راست", "pan-up": "پن به بالا",
    "pan-down": "پن به پایین", "drift": "شناورِ آرام", "parallax": "پارالاکس (لایه‌ها با سرعتِ متفاوت)", "rise": "بالا آمدن",
}
EXIT_KINDS = {"none": "بدونِ خروج", "fade": "محو", "slide": "لغزیدن", "zoom": "زوم", "drop": "افتادن"}
ENTER_KINDS = {k: k for k in catalog.ENTER_KINDS}
TRANSITIONS = list(catalog.TRANS_KINDS)
#: بستهٔ گذارهایی که مالک خواسته (همه در TRANSITIONS هستند)
TRANSITION_PACK = ("wipe", "push", "zoom", "ink", "glitch", "iris")

ALIGNS = ("center", "start", "end")

#: ناحیهٔ امنِ هر پلتفرم: کسری از قاب که رابطِ کاربریِ برنامه (نام، دکمه‌ها، توضیح) رویش می‌افتد. اعدادِ تقریبیِ راهنماهای منتشرشدهٔ خودِ پلتفرم‌ها؛
#: چیدمانِ موتور (kit.area) متن را از این کناره‌ها بیرون نگه می‌دارد و QA هم همین‌ها را می‌سنجد.
PLATFORMS = {
    "reels": {"name": "ریلزِ اینستاگرام", "aspect": "9:16", "safe": {"top": 0.14, "right": 0.10, "bottom": 0.22, "left": 0.06}},
    "story": {"name": "استوریِ اینستاگرام", "aspect": "9:16", "safe": {"top": 0.14, "right": 0.06, "bottom": 0.14, "left": 0.06}},
    "tiktok": {"name": "تیک‌تاک", "aspect": "9:16", "safe": {"top": 0.12, "right": 0.14, "bottom": 0.24, "left": 0.06}},
    "shorts": {"name": "یوتیوب شورتس", "aspect": "9:16", "safe": {"top": 0.10, "right": 0.12, "bottom": 0.20, "left": 0.06}},
    "feed": {"name": "پستِ فید", "aspect": "4:5", "safe": {"top": 0.05, "right": 0.05, "bottom": 0.08, "left": 0.05}},
    "square": {"name": "پستِ مربع", "aspect": "1:1", "safe": {"top": 0.05, "right": 0.05, "bottom": 0.07, "left": 0.05}},
    "youtube": {"name": "یوتیوب (افقی)", "aspect": "16:9", "safe": {"top": 0.05, "right": 0.05, "bottom": 0.09, "left": 0.05}},
    "": {"name": "بدونِ پلتفرم", "aspect": "", "safe": {"top": 0.0, "right": 0.0, "bottom": 0.0, "left": 0.0}},
}
DEFAULT_PLATFORM = {"9:16": "reels", "4:5": "feed", "1:1": "square", "16:9": "youtube"}

# ───────────────────────── قاعده‌های تایپوگرافی و زمان‌بندی (مرجعِ QA و راهنمای مدل)
READ_S_PER_WORD = 0.32          # حداقلِ زمانِ خواندنِ هر کلمهٔ فارسی (ثانیه)؛ فارسی کندتر از انگلیسی خوانده می‌شود
READ_S_PER_WORD_EN = 0.26
ENTRANCE_S = 0.7                # ورودِ عناصر تا این ثانیه طول می‌کشد؛ زمانِ خواندن بعد از آن شروع می‌شود
MIN_FONT_FRAC = 0.018           # کوچک‌ترین اندازهٔ دلخواهِ متن نسبت به ارتفاعِ قاب (≈۳۵ پیکسل در ۱۹۲۰)؛ زیرِ ۱٫۶۵٪ هشدار، زیرِ ۱٫۳٪ خطا
MIN_FONT_WARN = 0.0165
MIN_FONT_ERROR = 0.013
MIN_CONTRAST = 3.0              # WCAG برای متنِ درشت؛ زیرِ آن اصلاح می‌شود (متنِ کوچک ۴٫۵)
MIN_CONTRAST_SMALL = 4.5
MAX_SIMULTANEOUS = 12           # بیش از این عنصرِ هم‌زمانِ متحرک = شلوغ
MAX_WORDS_PER_SCENE = 38        # صحنهٔ پرکلمه تقسیم می‌شود


def platform_safe(platform: str, aspect: str = "") -> dict:
    """کسرهای ناحیهٔ امن؛ پلتفرمِ نامشخص ⇒ صفر (چیدمانِ پیش‌فرضِ موتور)."""
    return dict((PLATFORMS.get(platform or "") or PLATFORMS[""])["safe"])
