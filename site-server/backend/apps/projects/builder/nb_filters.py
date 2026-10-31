# -*- coding: utf-8 -*-
"""عدد و تاریخِ فارسی در بلوک‌های پویا — ساختهٔ استودیو؛ دستی ویرایش نکن.

فقط نمایش را عوض می‌کند: مقدارِ واقعی و مرتب‌سازی (که در دیتابیس انجام می‌شود) همان عددِ معمولی می‌ماند.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

_FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
_THOUSANDS = '٬'
_DECIMAL = '٫'


@register.filter(name='nb_digits', is_safe=True)
def nb_digits(value):
    """رقم‌های انگلیسیِ هر متنی را فارسی می‌کند؛ مقدارِ خالی همان خالی می‌ماند."""
    if value is None:
        return ''
    return str(value).translate(_FA)


@register.filter(name='nb_num', is_safe=True)
def nb_num(value):
    """۱۲۳۴۵۶۷٫۵ ⇐ ۱٬۲۳۴٬۵۶۷٫۵ (حداکثر دو رقمِ اعشار و بی‌صفرِ اضافه)."""
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return nb_digits(int(value))
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return nb_digits(value)
    if not num.is_finite():
        return nb_digits(value)
    text = '{:,.2f}'.format(num).rstrip('0').rstrip('.')
    return text.replace(',', '\x00').replace('.', _DECIMAL).replace('\x00', _THOUSANDS).replace('-', '−').translate(_FA)
