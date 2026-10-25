# -*- coding: utf-8 -*-
from django import template
from django.utils.html import format_html

from .. import jalali
from ..models import currency as _currency

register = template.Library()


@register.filter
def money(value):
    """۱٬۲۳۴٬۵۶۷ با جداکنندهٔ هزارگان؛ منفی داخلِ پرانتز (رسمِ حسابداری)."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return value
    if n < 0:
        return format_html('<span class="acc-neg">({})</span>', format(-n, ','))
    return format(n, ',')


@register.filter
def money0(value):
    """مثلِ money ولی صفر را خالی نشان می‌دهد (برای ستون‌های بدهکار/بستانکار)."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return value
    return '' if n == 0 else money(n)


@register.filter
def jdate(value):
    return jalali.fmt(value)


@register.filter
def jdatetime(value):
    return jalali.fmt_datetime(value)


@register.filter
def pct(value):
    from ..services import pct as _pct
    return _pct(value)


@register.simple_tag
def currency():
    return _currency()


@register.inclusion_tag('admin/accounting/_dashboard.html', takes_context=True)
def accounting_dashboard(context):
    request = context.get('request')
    user = getattr(request, 'user', None)
    if not user or not user.has_perm('accounting.view_reports'):
        return {'show': False, 'can_add': bool(user and user.has_perm('accounting.add_journalentry'))}
    from ..reports import dashboard
    return {'show': True, 'd': dashboard(), 'currency': _currency(),
            'can_add': user.has_perm('accounting.add_journalentry'),
            'can_post': user.has_perm('accounting.post_journalentry')}
