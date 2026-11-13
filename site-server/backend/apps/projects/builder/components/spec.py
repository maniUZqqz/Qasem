# -*- coding: utf-8 -*-
"""سازندهٔ تعریفِ قطعه‌ها: شکاف‌ها (فیلدهای فرمِ تنظیمات) و خودِ قطعه."""

CATEGORIES = [
    ('hero', 'سربرگ‌های بزرگ', 'hero'), ('features', 'ویژگی‌ها و مزیت‌ها', 'cards'), ('steps', 'گام‌ها و روند', 'list'),
    ('pricing', 'قیمت و بسته‌ها', 'price'), ('testimonials', 'نظرِ مشتریان', 'quote'), ('cta', 'دعوت به اقدام', 'megaphone'),
    ('faq', 'پرسش‌های پرتکرار', 'help'), ('cards', 'کارت‌ها', 'cards'), ('gallery', 'گالری و نمونه‌کار', 'gallery'),
    ('navbar', 'سربرگِ سایت (منو)', 'hero'), ('footer', 'پابرگِ سایت', 'layout'),
]
CAT_LABEL = {k: l for k, l, _i in CATEGORIES}
CAT_ICON = {k: i for k, _l, i in CATEGORIES}


def _f(key, label, kind, default, **kw):
    d = {'key': key, 'label': label, 'kind': kind, 'default': default}
    d.update(kw)
    return d


def T(key, label, default='', **kw):
    return _f(key, label, 'text', default, inline=True, **kw)


def A(key, label, default='', **kw):
    return _f(key, label, 'textarea', default, inline=True, **kw)


def L(key, label, default='#'):
    return _f(key, label, 'link', default)


def IM(key, label, default=''):
    return _f(key, label, 'image', default)


def IC(key, label, default='star'):
    return _f(key, label, 'icon', default)


def TG(key, label, default=False):
    return _f(key, label, 'toggle', default)


def SEL(key, label, options, default):
    return _f(key, label, 'select', default, options=[{'value': v, 'label': l} for v, l in options])


def ITEMS(key, label, fields, rows, item_label='title', add_label='افزودنِ مورد'):
    """fields: همان T/A/L/IM/IC؛ rows: فهرستِ دیکشنری‌های پیش‌فرض."""
    return _f(key, label, 'items', rows, fields=[{k: v for k, v in f.items() if k != 'default'} for f in fields],
              add_label=add_label, item_label=item_label, _row_defaults={f['key']: f['default'] for f in fields})


SHARED = {}          # کلید ⇒ CSSِ مشترکِ چند قطعه (مثلاً نوارِ متحرک)؛ فقط یک بار و فقط اگر قطعه‌ای از آن استفاده کند می‌آید


def C(key, cat, label, desc, slots, html, css='', tags='', styles='', scope=None, root='section', src=None, uses=''):
    """key با زیرخط (مثل hero_center_glow)؛ نوعِ بلوک c_<key> می‌شود و کلاسِ CSS «nbc-<key با خط‌تیره>».

    root: 'section' (بخشِ صفحه)، 'header' (سربرگِ سایت) یا 'footer' (پابرگ).
    src: مبدأ و مجوز (provenance.py)؛ بی‌آن یعنی «طراحیِ خودمان» بی‌کدِ شخصِ ثالث.
    uses: کلیدهای SHARED که این قطعه لازم دارد.
    """
    return {'key': key, 'cat': cat, 'label': label, 'desc': desc, 'slots': slots, 'html': html.strip(), 'css': css.strip(),
            'tags': tags.split(), 'styles': styles.split(), 'scope': scope or (['header'] if root == 'header' else ['footer'] if root == 'footer' else ['page']),
            'root': root, 'src': src, 'uses': uses.split()}


def row(**kw):
    return dict(kw)
