# -*- coding: utf-8 -*-
"""تاریخِ شمسیِ «سال/ماه» برای رزومه — بی‌کتابخانهٔ بیرونی."""

MONTH_NAMES = ['', 'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
               'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']
_FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def fa_digits(value):
    return str(value).translate(_FA)


def format_ym(year, month=None):
    if not year:
        return ''
    if month and 1 <= month <= 12:
        return '%s %s' % (MONTH_NAMES[month], fa_digits(year))
    return fa_digits(year)


def format_range(sy, sm, ey, em, is_current, current_label='تا کنون'):
    start = format_ym(sy, sm)
    end = current_label if is_current else format_ym(ey, em)
    if start and end and start != end:
        return '%s — %s' % (start, end)
    return start or end


def to_gregorian(jy, jm=1, jd=1):
    """تبدیلِ شمسی به میلادی (الگوریتمِ رایجِ jalaali) — برای JSON-LD."""
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    for gm, length in enumerate([31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], 1):
        if gd <= length:
            return gy, gm, gd
        gd -= length
    return gy, 12, 31


def iso_ym(year, month=None):
    """«2023-10» برای schema.org؛ بی‌سال = خالی."""
    if not year:
        return ''
    gy, gm, _ = to_gregorian(int(year), int(month or 1), 1)
    return '%04d-%02d' % (gy, gm) if month else '%04d' % gy
