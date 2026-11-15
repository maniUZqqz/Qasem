"""تبدیلِ تاریخِ شمسی ⇄ میلادی (فقط برای مناسبت‌های ثابتِ تقویمِ شمسی).

الگوریتمِ استانداردِ jalaali (بدونِ وابستگی). برعکسِ آن (میلادی ⇒ شمسی) در ``apps.common.versioning.gregorian_to_jalali`` هست؛
آزمونِ این پوشه رفت‌وبرگشت را با همان می‌سنجد.
"""
from __future__ import annotations

import datetime as _dt

_BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178)


def _div(a: int, b: int) -> int:
    return a // b


def _jal_cal(jy: int) -> tuple[int, int, int]:
    """(leap, gy, march) برای سالِ شمسیِ jy: leap = سالِ کبیسه (۰ یعنی کبیسه)، march = روزِ مارچِ آغازِ سال."""
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(jump % 33, 4)
        jp = jm
    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(n % 33 + 3, 4)
    if jump % 33 == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = (((n + 1) % 33) - 1) % 4
    if leap == -1:
        leap = 4
    return leap, gy, march


def is_leap(jy: int) -> bool:
    return _jal_cal(jy)[0] == 0


def month_length(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap(jy) else 29


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> _dt.date:
    _leap, gy, march = _jal_cal(jy)
    start = _dt.date(gy, 3, march)
    day_of_year = (jm - 1) * 31 + jd - 1 if jm <= 7 else 6 * 31 + (jm - 7) * 30 + jd - 1
    return start + _dt.timedelta(days=day_of_year)


def next_occurrence(month: int, day: int, today: _dt.date | None = None) -> _dt.date:
    """نزدیک‌ترین تاریخِ میلادی (امروز یا بعد) برای «ماه/روزِ» ثابتِ شمسی.

    روزی که در سالِ کبیسه‌نبودنِ آن سال وجود ندارد (۳۰ اسفند) به آخرینِ روزِ ماه کشیده می‌شود."""
    from apps.common.versioning import gregorian_to_jalali

    today = today or _dt.date.today()
    jy, _jm, _jd = gregorian_to_jalali(today.year, today.month, today.day)
    for year in (jy, jy + 1):
        d = min(day, month_length(year, month))
        when = jalali_to_gregorian(year, month, d)
        if when >= today:
            return when
    return jalali_to_gregorian(jy + 1, month, min(day, month_length(jy + 1, month)))


MONTHS_FA = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def label(month: int, day: int | None = None) -> str:
    """«۱ فروردین» / «اسفندماه» برای نمایش."""
    name = MONTHS_FA[month - 1]
    return f"{day} {name}".translate(_FA) if day else f"{name}ماه"
