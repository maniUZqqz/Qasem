# -*- coding: utf-8 -*-
"""جایگزینِ بی‌خطرِ چند تگ برای بوم: روی بوم نشانی‌های پروژه وجود ندارند."""
from django import template

from . import nb_filters

register = template.Library()
register.filters['nb_num'] = nb_filters.nb_num
register.filters['nb_digits'] = nb_filters.nb_digits


@register.simple_tag(name='url')
def fake_url(*args, **kwargs):
    return '#'


@register.simple_tag(name='static')
def fake_static(*args, **kwargs):
    return '#'
