# -*- coding: utf-8 -*-
from django import template

from ..jalali import fa_digits
from ..thumbs import thumbnail

register = template.Library()


@register.simple_tag
def thumb(field_file, width, height=None, crop=False):
    """{% thumb member.photo 400 400 True %} ⇒ نشانیِ نسخهٔ کوچکِ WebP."""
    return thumbnail(field_file, int(width), int(height) if height else None, bool(crop))


@register.filter
def fa(value):
    """ارقامِ فارسی."""
    if value is None:
        return ''
    return fa_digits(value)
