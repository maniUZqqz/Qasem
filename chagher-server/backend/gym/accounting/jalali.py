# -*- coding: utf-8 -*-
"""تقویمِ جلالی بی‌وابستگی — برگردانِ پایتونیِ الگوریتمِ jalaali-js (دقیق برای ۱ تا ۳۱۷۷).

پروژه کتابخانهٔ جلالی نداشت (فقط یک تابعِ یک‌طرفه در pdf_generator)؛ برای این‌که
روی سایتِ زنده چیزی نصب نشود، این‌جا هر دو جهت نوشته شده و در تست‌ها با چند
تاریخِ شناخته و رفت‌وبرگشتِ روزبه‌روز سنجیده می‌شود.
"""
import datetime as _dt
import re

_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
           1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]

MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
          'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def _div(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _mod(a, b):
    return a - _div(a, b) * b


def _jal_cal(jy):
    """(leap, gy, march): leap==0 یعنی سالِ کبیسه؛ march روزِ ۱ فروردین در ماهِ مارس."""
    if jy < _BREAKS[0] or jy >= _BREAKS[-1]:
        raise ValueError('سالِ جلالیِ نامعتبر: %s' % jy)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def is_leap(jy):
    return _jal_cal(jy)[0] == 0


def month_length(jy, jm):
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap(jy) else 29


def to_gregorian(jy, jm, jd):
    if not (1 <= jm <= 12) or not (1 <= jd <= month_length(jy, jm)):
        raise ValueError('تاریخِ جلالیِ نامعتبر: %s/%s/%s' % (jy, jm, jd))
    _, gy, march = _jal_cal(jy)
    offset = (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1
    return _dt.date(gy, 3, march) + _dt.timedelta(days=offset)


def to_jalali(d):
    """date یا datetime ⇒ (سال، ماه، روز). datetimeِ آگاه به منطقهٔ زمانی را اول محلی کن."""
    if isinstance(d, _dt.datetime):
        d = d.date()
    gy = d.year
    jy = gy - 621
    leap, _, march = _jal_cal(jy)
    k = (d - _dt.date(gy, 3, march)).days
    if k >= 0:
        if k <= 185:
            return jy, 1 + k // 31, k % 31 + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + k // 30, k % 30 + 1


def fmt(d, empty='—'):
    """۱۴۰۵/۰۸/۰۳ (با رقمِ لاتین، هم‌خوان با بقیهٔ ادمین)."""
    if not d:
        return empty
    if isinstance(d, _dt.datetime):
        from django.utils import timezone
        if timezone.is_aware(d):
            d = timezone.localtime(d)
    jy, jm, jd = to_jalali(d)
    return '%04d/%02d/%02d' % (jy, jm, jd)


def fmt_datetime(dt, empty='—'):
    if not dt:
        return empty
    from django.utils import timezone
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return '%s %02d:%02d' % (fmt(dt.date()), dt.hour, dt.minute)


def month_title(jy, jm):
    return '%s %d' % (MONTHS[jm - 1], jy)


_PARSE_RE = re.compile(r'^\s*(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*$')


def parse(text):
    """'۱۴۰۵/۸/۳' یا '1405-08-03' ⇒ date میلادی. نامعتبر ⇒ ValueError."""
    s = str(text or '').translate(_DIGITS)
    m = _PARSE_RE.match(s)
    if not m:
        raise ValueError('تاریخ را به شکلِ ۱۴۰۵/۰۸/۰۳ بنویسید.')
    jy, jm, jd = (int(x) for x in m.groups())
    if jy < 1300 or jy > 1500:
        raise ValueError('سالِ جلالی باید چهاررقمی باشد (مثلاً ۱۴۰۵).')
    return to_gregorian(jy, jm, jd)


def month_bounds(d):
    """اولین و آخرین روزِ ماهِ جلالیِ شاملِ d (میلادی)."""
    jy, jm, _ = to_jalali(d)
    return to_gregorian(jy, jm, 1), to_gregorian(jy, jm, month_length(jy, jm))


def year_bounds(jy):
    return to_gregorian(jy, 1, 1), to_gregorian(jy, 12, month_length(jy, 12))


def to_ascii_digits(text):
    return str(text or '').translate(_DIGITS)
