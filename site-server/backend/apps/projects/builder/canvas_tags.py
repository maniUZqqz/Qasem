# -*- coding: utf-8 -*-
"""جایگزینِ بی‌خطرِ چند تگ برای بوم: روی بوم نشانی‌های پروژه وجود ندارند."""
from django import template

register = template.Library()


@register.simple_tag(name='url')
def fake_url(*args, **kwargs):
    return '#'


@register.simple_tag(name='static')
def fake_static(*args, **kwargs):
    return '#'
