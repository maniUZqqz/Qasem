"""تاریخ و ساعتِ برنامه (وقتِ تهران، تقویمِ شمسی)."""
from __future__ import annotations

import datetime as dt
import re

from django.utils import timezone

from apps.common.fatext import fa_digits
from apps.common.versioning import gregorian_to_jalali

try:  # ایران از ۱۴۰۱ ساعتِ تابستانی ندارد؛ اگر پایگاهِ منطقه‌های زمانی نبود +۰۳:۳۰ ثابت است
    from zoneinfo import ZoneInfo

    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # noqa: BLE001
    TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))

# python weekday(): Monday=0 ... Sunday=6
WEEKDAYS_FA = {5: "شنبه", 6: "یک‌شنبه", 0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه", 3: "پنجشنبه", 4: "جمعه"}

#: ساعتِ پیشنهادیِ انتشار برای هر نوع (تهران)؛ پست/ریلز شب، استوری ظهر و عصر
HOUR_FOR = {"reel": (19, 30), "carousel": (19, 30), "post": (19, 30), "story": (12, 30), "video_edit": (19, 30), "email": (10, 0), "sms": (11, 0), "dm": (11, 0)}


def today_tehran() -> dt.date:
    return timezone.now().astimezone(TEHRAN).date()


def default_start(today: dt.date | None = None) -> dt.date:
    """شروعِ برنامه: فردا (برنامه امروز ساخته می‌شود، اجرا از فردا)."""
    return (today or today_tehran()) + dt.timedelta(days=1)


def day_date(start: dt.date, day: int) -> dt.date:
    return start + dt.timedelta(days=max(1, int(day)) - 1)


def at(date: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(date.year, date.month, date.day, hour, minute, tzinfo=TEHRAN)


def when_for(kind: str, date: dt.date) -> dt.datetime:
    h, m = HOUR_FOR.get(kind, (14, 0))
    return at(date, h, m)


def jalali(date: dt.date) -> str:
    jy, jm, jd = gregorian_to_jalali(date.year, date.month, date.day)
    return fa_digits(f"{jy:04d}/{jm:02d}/{jd:02d}")


def fa_when(when: dt.datetime) -> str:
    when = when.astimezone(TEHRAN)
    return f"{WEEKDAYS_FA[when.weekday()]} {jalali(when.date())} ساعت {fa_digits(f'{when.hour:02d}:{when.minute:02d}')} (تهران)"


#: خطِ «موعدِ پیشنهادیِ انتشار …» که پیش‌نویس‌های قدیمیِ کمپین دارند؛ موقعِ زمان‌بندیِ تازه همان یک خط عوض می‌شود
_DUE_LINE = re.compile(r"^موعدِ پیشنهادی(?:ِ انتشار)?:.*$", re.M)


def retime_detail(detail: str, when: dt.datetime) -> str:
    """متنِ توضیحِ یک کار را با موعدِ تازه هماهنگ می‌کند (اگر چنین خطی دارد)."""
    line = f"موعدِ پیشنهادیِ انتشار: {fa_when(when)} — فقط پیشنهاد؛ چیزی خودکار منتشر نمی‌شود."
    if _DUE_LINE.search(detail or ""):
        return _DUE_LINE.sub(line, detail, count=1)
    return detail
