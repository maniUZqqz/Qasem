"""اندازه‌ها و «حاشیهٔ امن» هر پلتفرم برای تامنیل‌ساز.

هر قالب (format) اندازهٔ دقیقِ خروجی، حاشیهٔ امنِ عنوان و چند «ناحیهٔ پرهیز» دارد: جاهایی که خودِ پلتفرم رویِ تصویر چیزی
می‌کشد (مدتِ ویدیو، نوارِ پاسخِ استوری، دکمهٔ «ذخیره»…) یا هنگامِ نمایشِ شبکه‌ایِ پروفایل بریده می‌شود. چیدمانِ سبک‌ها متنِ
مهم را بیرونِ این ناحیه‌ها می‌گذارد (``thumbs.render``) و پیش‌نمایش می‌تواند خطِ راهنمایشان را نشان بدهد.

عددها **تقریبی** و بر پایهٔ راهنمای عمومیِ هر پلتفرم‌اند و ممکن است پلتفرم عوضشان کند؛ به همین دلیل به کاربر هم «تقریبی»
گفته می‌شود. هیچ‌جا چیزی از یک پلتفرم کپی نشده؛ فقط اندازه‌ها.
"""
from __future__ import annotations

from dataclasses import dataclass, field

Rect = tuple[float, float, float, float]       # x0, y0, x1, y1 (کسری از بوم)


@dataclass(frozen=True)
class Format:
    key: str
    title: str                    # فارسی، برای منو
    platform: str                 # گروه در منو
    size: tuple[int, int]
    #: حاشیهٔ امنِ عنوان: چپ، بالا، راست، پایین (کسری از پهنا/ارتفاع)
    margin: tuple[float, float, float, float]
    #: (x0, y0, x1, y1, یادداشتِ فارسی) — متنِ مهم این‌جاها نمی‌نشیند
    avoid: tuple[tuple[float, float, float, float, str], ...] = ()
    note: str = ""
    #: سقفِ حجمِ JPEG (کیلوبایت)؛ ۰ = بی‌سقف
    max_kb: int = 0
    aspect_label: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)

    @property
    def w(self) -> int:
        return self.size[0]

    @property
    def h(self) -> int:
        return self.size[1]

    @property
    def orient(self) -> str:
        return orientation(self.size)

    def public(self) -> dict:
        return {"key": self.key, "title": self.title, "platform": self.platform, "width": self.w, "height": self.h,
                "aspect": self.aspect_label, "orient": self.orient, "note": self.note, "max_kb": self.max_kb,
                "margin": list(self.margin), "avoid": [{"rect": list(a[:4]), "note": a[4]} for a in self.avoid]}


def orientation(size: tuple[int, int]) -> str:
    """wide: ۱۶:۹ و پهن‌تر · square: نزدیکِ مربع · portrait: ۴:۵ · tall: ۲:۳ و بلندتر (استوری، پین، پوستر)."""
    w, h = size
    r = w / float(h)
    if r >= 1.3:
        return "wide"
    if r >= 0.95:
        return "square"
    if r >= 0.72:
        return "portrait"
    return "tall"


FORMATS: dict[str, Format] = {f.key: f for f in (
    Format("youtube", "کاور یوتیوب", "ویدیو", (1280, 720), (0.045, 0.06, 0.045, 0.07),
           avoid=((0.82, 0.84, 1.0, 1.0, "مدتِ ویدیو (پایین-راست)"),),
           note="۱۲۸۰×۷۲۰ — کمتر از ۲ مگابایت؛ مدتِ ویدیو گوشهٔ پایین-راست را می‌پوشاند.", max_kb=2000, aspect_label="۱۶:۹",
           keywords=("یوتیوب", "youtube", "ویدیو")),
    Format("aparat", "کاور آپارات", "ویدیو", (1280, 720), (0.045, 0.06, 0.045, 0.08),
           avoid=((0.0, 0.84, 0.16, 1.0, "مدتِ ویدیو (پایین-چپ)"),),
           note="۱۲۸۰×۷۲۰ — مدتِ ویدیو گوشهٔ پایین را می‌پوشاند (تقریبی).", max_kb=2000, aspect_label="۱۶:۹",
           keywords=("آپارات", "aparat")),
    Format("telegram", "کاور تلگرام", "پیام‌رسان", (1280, 720), (0.05, 0.07, 0.05, 0.07),
           avoid=((0.0, 0.0, 0.17, 0.12, "مدتِ ویدیو (بالا-چپ)"),),
           note="۱۲۸۰×۷۲۰ — پیش‌نمایشِ پست و ویدیو در کانال (تقریبی).", max_kb=2000, aspect_label="۱۶:۹",
           keywords=("تلگرام", "telegram")),
    Format("ig_portrait", "پستِ اینستاگرام ۴:۵", "اینستاگرام", (1080, 1350), (0.07, 0.06, 0.07, 0.06),
           avoid=((0.0, 0.0, 0.032, 1.0, "بریدهٔ شبکهٔ پروفایل (چپ)"), (0.968, 0.0, 1.0, 1.0, "بریدهٔ شبکهٔ پروفایل (راست)")),
           note="۱۰۸۰×۱۳۵۰ — در شبکهٔ پروفایل از دو طرف کمی بریده می‌شود؛ متنِ مهم را وسط نگه دارید.", aspect_label="۴:۵",
           keywords=("اینستاگرام", "instagram", "پست")),
    Format("ig_square", "پستِ اینستاگرام مربع", "اینستاگرام", (1080, 1080), (0.07, 0.07, 0.07, 0.07),
           note="۱۰۸۰×۱۰۸۰ — مربعِ کلاسیک.", aspect_label="۱:۱", keywords=("اینستاگرام", "مربع")),
    Format("story", "کاور ریلز / استوری", "اینستاگرام", (1080, 1920), (0.07, 0.13, 0.07, 0.18),
           avoid=((0.0, 0.0, 1.0, 0.13, "نوارِ بالا (پروفایل و پیشرفت)"), (0.0, 0.82, 1.0, 1.0, "نوارِ پاییِ پاسخ/دکمه‌ها")),
           note="۱۰۸۰×۱۹۲۰ — بالا و پایین را رابطِ برنامه می‌پوشاند؛ در شبکهٔ پروفایل فقط بخشِ میانی (۳:۴) دیده می‌شود.",
           aspect_label="۹:۱۶", keywords=("ریلز", "استوری", "reels", "story")),
    Format("pinterest", "پینِ پینترست", "پینترست", (1000, 1500), (0.07, 0.06, 0.07, 0.07),
           avoid=((0.76, 0.0, 1.0, 0.07, "دکمهٔ «ذخیره» (بالا-راست)"),),
           note="۱۰۰۰×۱۵۰۰ (۲:۳) — نسبتِ پیشنهادیِ پین.", aspect_label="۲:۳", keywords=("پینترست", "pinterest", "پین")),
    Format("poster", "پوستر فیلم ۲:۳", "پوستر", (1200, 1800), (0.07, 0.05, 0.07, 0.05),
           note="۱۲۰۰×۱۸۰۰ (۲:۳) — نسبتِ پوستر.", aspect_label="۲:۳", keywords=("پوستر", "فیلم", "poster")),
)}

DEFAULT_FORMAT = "youtube"


class UnknownFormat(KeyError):
    pass


def get(key: str) -> Format:
    try:
        return FORMATS[key]
    except KeyError as exc:
        raise UnknownFormat(key) from exc


def scaled(fmt: Format, scale: float) -> tuple[int, int]:
    """اندازهٔ بوم در یک مقیاس (پیش‌نمایش ⇒ کوچک‌تر). همیشه زوج و دست‌کم ۸۰ پیکسل."""
    s = max(0.05, float(scale))
    return max(80, int(round(fmt.w * s / 2) * 2)), max(80, int(round(fmt.h * s / 2) * 2))


def px_rect(rect: Rect, size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    return int(round(rect[0] * w)), int(round(rect[1] * h)), int(round(rect[2] * w)), int(round(rect[3] * h))


def safe_rect(fmt: Format, size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    l, t, r, b = fmt.margin
    return int(round(w * l)), int(round(h * t)), int(round(w * (1 - r))), int(round(h * (1 - b)))


def avoid_rects(fmt: Format, size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    return [px_rect(a[:4], size) for a in fmt.avoid]
