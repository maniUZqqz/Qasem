# -*- coding: utf-8 -*-
"""فهرستِ بلوک‌ها و تنظیماتشان — تنها منبعِ حقیقت.

پنلِ React فرمِ تنظیماتِ هر بلوک را از همین تعریف می‌سازد؛ پس افزودنِ بلوکِ تازه یعنی یک
ردیف این‌جا و یک تابعِ رندر در render.py. همهٔ برچسب‌ها فارسیِ ساده‌اند و واژهٔ فنی ندارند.
"""
from .icons import ICONS


def F(key, label, kind='text', **kw):
    d = {'key': key, 'label': label, 'kind': kind}
    d.update(kw)
    return d


def _opts(*pairs):
    return [{'value': v, 'label': l} for v, l in pairs]


LINK_HELP = 'یک صفحه از سایت را انتخاب کن یا نشانیِ کامل بنویس.'

# ─────────────────────────────── تنظیماتِ ظاهری (بی‌واژهٔ CSS)
STYLE = [
    # کلید، برچسب، نوع، گروه، آیا برای هر دستگاه جدا؟ و محدوده
    F('color', 'رنگِ متن', 'color', group='text'),
    F('size', 'اندازهٔ متن', 'slider', group='text', device=True, min=12, max=96, unit='px'),
    F('weight', 'ضخامتِ متن', 'select', group='text',
      options=_opts(('', 'پیش‌فرض'), ('400', 'معمولی'), ('600', 'نیمه‌ضخیم'), ('800', 'ضخیم'))),
    F('align', 'چینش', 'align', group='text', device=True),
    F('bg', 'رنگِ پس‌زمینه', 'color', group='bg'),
    F('bgimg', 'تصویرِ پس‌زمینه', 'image', group='bg'),
    F('overlay', 'تیره‌کردنِ تصویر', 'slider', group='bg', min=0, max=90, unit='٪'),
    F('py', 'فاصلهٔ داخلیِ بالا و پایین', 'slider', group='space', device=True, min=0, max=200, unit='px'),
    F('px', 'فاصلهٔ داخلیِ چپ و راست', 'slider', group='space', device=True, min=0, max=120, unit='px'),
    F('mt', 'فاصله از بالا', 'slider', group='space', device=True, min=0, max=160, unit='px'),
    F('mb', 'فاصله از پایین', 'slider', group='space', device=True, min=0, max=160, unit='px'),
    F('width', 'پهنا', 'slider', group='size', device=True, min=10, max=100, unit='٪'),
    F('maxw', 'بیشترین پهنا', 'slider', group='size', min=200, max=1600, unit='px'),
    F('minh', 'کمترین بلندی', 'slider', group='size', device=True, min=0, max=900, unit='px'),
    F('radius', 'گردیِ گوشه‌ها', 'slider', group='frame', min=0, max=80, unit='px'),
    F('shadow', 'سایه', 'select', group='frame',
      options=_opts(('', 'بدونِ سایه'), ('soft', 'ملایم'), ('medium', 'متوسط'), ('strong', 'پررنگ'))),
    F('border', 'رنگِ حاشیه', 'color', group='frame'),
    F('bw', 'ضخامتِ حاشیه', 'slider', group='frame', min=0, max=10, unit='px'),
    F('hide_desktop', 'در رایانه پنهان شود', 'toggle', group='visible'),
    F('hide_tablet', 'در تبلت پنهان شود', 'toggle', group='visible'),
    F('hide_phone', 'در گوشی پنهان شود', 'toggle', group='visible'),
]
STYLE_GROUPS = _opts(('text', 'متن'), ('bg', 'پس‌زمینه'), ('space', 'فاصله‌ها'), ('size', 'اندازه'),
                     ('frame', 'قاب و سایه'), ('visible', 'نمایش'))
STYLE_BY_KEY = {s['key']: s for s in STYLE}
DEVICE_KEYS = {s['key'] for s in STYLE if s.get('device')}

G_TEXT = ['color', 'size', 'weight', 'align']
G_BOX = ['bg', 'py', 'px', 'mt', 'mb', 'radius', 'shadow', 'border', 'bw']
G_VIS = ['hide_desktop', 'hide_tablet', 'hide_phone']
G_SECTION = ['color', 'align', 'bg', 'bgimg', 'overlay', 'py', 'px', 'mt', 'mb', 'maxw', 'minh', 'radius'] + G_VIS

# ─────────────────────────────── بلوک‌ها
GROUPS = _opts(('layout', 'چیدمان'), ('basic', 'پایه'), ('ready', 'بخش‌های آماده'),
               ('data', 'نمایشِ دادهٔ سایت'), ('chrome', 'سربرگ و پابرگ'))

_ITEM_FEATURE = [F('icon', 'نماد', 'icon'), F('title', 'عنوان'), F('text', 'توضیح', 'textarea')]
_ITEM_PLAN = [F('name', 'نامِ بسته'), F('price', 'قیمت'), F('period', 'دوره'),
              F('features', 'امکانات (هر خط یکی)', 'textarea'), F('button', 'متنِ دکمه'),
              F('link', 'پیوندِ دکمه', 'link'), F('highlight', 'پیشنهادِ ویژه', 'toggle')]
_ITEM_QUOTE = [F('text', 'متنِ نظر', 'textarea'), F('name', 'نام'), F('role', 'سمت یا شهر'), F('avatar', 'تصویر', 'image')]
_ITEM_FAQ = [F('q', 'پرسش'), F('a', 'پاسخ', 'textarea')]
_ITEM_FIELD = [F('label', 'عنوانِ فیلد'),
               F('type', 'نوع', 'select', options=_opts(('text', 'متنِ کوتاه'), ('email', 'ایمیل'), ('tel', 'تلفن'),
                                                        ('number', 'عدد'), ('textarea', 'متنِ بلند'))),
               F('required', 'پرکردنش لازم است', 'toggle')]
_ITEM_GALLERY = [F('image', 'تصویر', 'image'), F('alt', 'توضیحِ تصویر')]

BLOCKS = {
    # ── چیدمان ──
    'section': dict(
        label='بخش', group='layout', icon='layout', container=True, root=True,
        hint='یک نوارِ پهن از صفحه که چیزهای دیگر را داخلش می‌گذاری',
        fields=[F('full', 'تمام‌عرضِ صفحه', 'toggle')],
        defaults={'full': False}, style=G_SECTION),
    'columns': dict(
        label='ستون‌ها', group='layout', icon='columns', structural=True,
        hint='چند ستون کنارِ هم؛ در گوشی زیرِ هم می‌آیند',
        fields=[F('count', 'تعدادِ ستون', 'select', options=_opts((1, 'یک'), (2, 'دو'), (3, 'سه'), (4, 'چهار'))),
                F('ratio', 'تقسیمِ پهنا', 'select',
                  options=_opts(('equal', 'مساوی'), ('wide-first', 'اولی پهن‌تر'), ('wide-last', 'آخری پهن‌تر'))),
                F('gap', 'فاصلهٔ ستون‌ها', 'slider', min=0, max=80, unit='px'),
                F('valign', 'چینشِ عمودی', 'select',
                  options=_opts(('start', 'بالا'), ('center', 'وسط'), ('end', 'پایین')))],
        defaults={'count': 2, 'ratio': 'equal', 'gap': 24, 'valign': 'start'},
        style=['bg', 'py', 'px', 'mt', 'mb', 'radius'] + G_VIS),
    'column': dict(
        label='ستون', group='layout', icon='column', container=True, hidden=True, fields=[], defaults={},
        style=['color', 'align', 'bg', 'py', 'px', 'radius', 'shadow', 'border', 'bw'] + G_VIS),

    # ── پایه ──
    'heading': dict(
        label='تیتر', group='basic', icon='heading',
        fields=[F('text', 'متن', 'text', inline=True),
                F('level', 'درجهٔ تیتر', 'select',
                  options=_opts((1, 'تیترِ اصلیِ صفحه'), (2, 'تیترِ بخش'), (3, 'تیترِ کوچک'), (4, 'تیترِ ریز')))],
        defaults={'text': 'یک تیترِ خوب بنویس', 'level': 2}, style=G_TEXT + ['mt', 'mb', 'maxw'] + G_VIS),
    'text': dict(
        label='متن', group='basic', icon='text',
        fields=[F('html', 'متن', 'rich', inline=True)],
        defaults={'html': '<p>این‌جا متنت را بنویس. روی همین متن بزن و تایپ کن.</p>'},
        style=G_TEXT + ['mt', 'mb', 'maxw'] + G_VIS),
    'image': dict(
        label='تصویر', group='basic', icon='image',
        fields=[F('src', 'تصویر', 'image'), F('alt', 'توضیحِ تصویر (برای نابینایان و گوگل)'),
                F('caption', 'زیرنویس'), F('link', 'با کلیک برود به', 'link', help=LINK_HELP)],
        defaults={'src': '', 'alt': '', 'caption': '', 'link': ''},
        style=['align', 'width', 'radius', 'shadow', 'border', 'bw', 'mt', 'mb'] + G_VIS),
    'button': dict(
        label='دکمه', group='basic', icon='button',
        fields=[F('text', 'متنِ دکمه', 'text', inline=True), F('link', 'با کلیک برود به', 'link', help=LINK_HELP),
                F('variant', 'شکل', 'select', options=_opts(('filled', 'پررنگ'), ('outline', 'حاشیه‌دار'), ('soft', 'کم‌رنگ'))),
                F('btn_size', 'اندازه', 'select', options=_opts(('sm', 'کوچک'), ('md', 'معمولی'), ('lg', 'بزرگ'))),
                F('new_tab', 'در زبانهٔ تازه باز شود', 'toggle')],
        defaults={'text': 'دکمه', 'link': '#', 'variant': 'filled', 'btn_size': 'md', 'new_tab': False},
        style=['align', 'mt', 'mb'] + G_VIS),
    'video': dict(
        label='ویدیو', group='basic', icon='video',
        fields=[F('source', 'ویدیو', 'image', accept='video'),
                F('link', 'یا نشانیِ ویدیو در آپارات یا یوتیوب', 'text', dir='ltr'),
                F('poster', 'تصویرِ پیش از پخش', 'image'), F('title', 'توضیحِ ویدیو')],
        defaults={'source': '', 'link': '', 'poster': '', 'title': ''},
        style=['width', 'radius', 'shadow', 'mt', 'mb'] + G_VIS),
    'spacer': dict(
        label='فاصله', group='basic', icon='spacer',
        fields=[F('height', 'بلندی', 'slider', min=4, max=240, unit='px')],
        defaults={'height': 40}, style=G_VIS),
    'divider': dict(
        label='خطِ جداکننده', group='basic', icon='divider',
        fields=[F('thickness', 'ضخامت', 'slider', min=1, max=10, unit='px'),
                F('line', 'رنگ', 'color')],
        defaults={'thickness': 1, 'line': 't:line'}, style=['width', 'mt', 'mb'] + G_VIS),
    'icon': dict(
        label='نماد', group='basic', icon='star',
        fields=[F('name', 'نماد', 'icon'), F('icon_size', 'اندازه', 'slider', min=16, max=160, unit='px'),
                F('tint', 'رنگ', 'color'), F('link', 'با کلیک برود به', 'link')],
        defaults={'name': 'star', 'icon_size': 48, 'tint': 't:primary', 'link': ''},
        style=['align', 'mt', 'mb'] + G_VIS),
    'gallery': dict(
        label='گالری', group='basic', icon='gallery',
        fields=[F('items', 'تصویرها', 'items', fields=_ITEM_GALLERY, add_label='افزودنِ تصویر', item_label='image'),
                F('cols', 'تعداد در هر ردیف', 'slider', min=1, max=6, device=True),
                F('gap', 'فاصله', 'slider', min=0, max=40, unit='px'),
                F('ratio', 'شکلِ تصویرها', 'select',
                  options=_opts(('1/1', 'مربع'), ('4/3', 'افقی'), ('3/4', 'عمودی'), ('16/9', 'پهن')))],
        defaults={'items': [], 'cols': {'d': 3, 't': 3, 'p': 2}, 'gap': 12, 'ratio': '1/1'},
        style=['radius', 'mt', 'mb'] + G_VIS),
    'custom_html': dict(
        label='کدِ سفارشی', group='basic', icon='code', advanced=True,
        hint='برای حرفه‌ای‌ها: هر چه بنویسی عیناً در صفحه می‌نشیند',
        fields=[F('code', 'کد', 'code')], defaults={'code': ''}, style=G_VIS),

    # ── بخش‌های آماده ──
    'hero': dict(
        label='سربرگِ بزرگ', group='ready', icon='hero', root=True,
        hint='تیترِ بزرگ، توضیح و دکمه در ابتدای صفحه',
        fields=[F('eyebrow', 'نوشتهٔ کوچکِ بالا', inline=True), F('title', 'تیتر', inline=True),
                F('subtitle', 'توضیح', 'textarea', inline=True),
                F('btn1', 'متنِ دکمهٔ اول', inline=True), F('btn1_link', 'پیوندِ دکمهٔ اول', 'link'),
                F('btn2', 'متنِ دکمهٔ دوم', inline=True), F('btn2_link', 'پیوندِ دکمهٔ دوم', 'link'),
                F('image', 'تصویر', 'image'), F('image_alt', 'توضیحِ تصویر'),
                F('layout', 'چیدمان', 'select', options=_opts(('center', 'وسط‌چین'), ('split', 'متن کنارِ تصویر')))],
        defaults={'eyebrow': 'به سایتِ ما خوش آمدی', 'title': 'تیترِ اصلیِ سایتت را این‌جا بنویس',
                  'subtitle': 'در یکی دو جمله بگو چه کاری انجام می‌دهی و چرا مشتری باید تو را انتخاب کند.',
                  'btn1': 'شروع کنید', 'btn1_link': '#', 'btn2': 'بیشتر بدانید', 'btn2_link': '#',
                  'image': '', 'image_alt': '', 'layout': 'center'},
        style=G_SECTION),
    'features': dict(
        label='کارت‌های ویژگی', group='ready', icon='cards', root=True,
        fields=[F('title', 'تیتر', inline=True), F('subtitle', 'توضیح', 'textarea', inline=True),
                F('cols', 'تعداد در هر ردیف', 'slider', min=1, max=4, device=True),
                F('items', 'کارت‌ها', 'items', fields=_ITEM_FEATURE, add_label='افزودنِ کارت', item_label='title')],
        defaults={'title': 'چرا ما؟', 'subtitle': 'سه دلیل برای این‌که با خیالِ راحت انتخابمان کنی',
                  'cols': {'d': 3, 't': 2, 'p': 1},
                  'items': [{'icon': 'zap', 'title': 'سریع', 'text': 'کارت را در کم‌ترین زمان تحویل می‌دهیم.'},
                            {'icon': 'shield', 'title': 'مطمئن', 'text': 'کیفیت را تضمین می‌کنیم و کنارت می‌مانیم.'},
                            {'icon': 'heart', 'title': 'با حوصله', 'text': 'به هر پرسشی با دقت جواب می‌دهیم.'}]},
        style=G_SECTION),
    'pricing': dict(
        label='جدولِ قیمت', group='ready', icon='price', root=True,
        fields=[F('title', 'تیتر', inline=True), F('subtitle', 'توضیح', 'textarea', inline=True),
                F('items', 'بسته‌ها', 'items', fields=_ITEM_PLAN, add_label='افزودنِ بسته', item_label='name')],
        defaults={'title': 'بسته‌ها', 'subtitle': 'بسته‌ای را انتخاب کن که با کارت جور است',
                  'items': [
                      {'name': 'پایه', 'price': '۴۹۰٬۰۰۰ تومان', 'period': 'ماهانه', 'features': 'امکانِ اول\nامکانِ دوم',
                       'button': 'انتخاب', 'link': '#', 'highlight': False},
                      {'name': 'حرفه‌ای', 'price': '۹۹۰٬۰۰۰ تومان', 'period': 'ماهانه',
                       'features': 'همهٔ امکاناتِ پایه\nپشتیبانیِ ویژه\nگزارشِ ماهانه',
                       'button': 'انتخاب', 'link': '#', 'highlight': True},
                      {'name': 'سازمانی', 'price': 'تماس بگیرید', 'period': '', 'features': 'همهٔ امکانات\nمشاورهٔ اختصاصی',
                       'button': 'تماس', 'link': '#', 'highlight': False}]},
        style=G_SECTION),
    'testimonials': dict(
        label='نظرِ مشتریان', group='ready', icon='quote', root=True,
        fields=[F('title', 'تیتر', inline=True),
                F('items', 'نظرها', 'items', fields=_ITEM_QUOTE, add_label='افزودنِ نظر', item_label='name')],
        defaults={'title': 'مشتریان چه می‌گویند', 'items': [
            {'text': 'کارشان تمیز و سریع بود و همیشه جواب می‌دادند.', 'name': 'سارا محمدی', 'role': 'تهران', 'avatar': ''},
            {'text': 'نتیجه از چیزی که فکر می‌کردم بهتر شد.', 'name': 'علی رضایی', 'role': 'اصفهان', 'avatar': ''},
            {'text': 'با خیالِ راحت به دوستانم معرفی کرده‌ام.', 'name': 'مریم احمدی', 'role': 'شیراز', 'avatar': ''}]},
        style=G_SECTION),
    'faq': dict(
        label='پرسش‌های پرتکرار', group='ready', icon='help', root=True,
        fields=[F('title', 'تیتر', inline=True),
                F('items', 'پرسش‌ها', 'items', fields=_ITEM_FAQ, add_label='افزودنِ پرسش', item_label='q')],
        defaults={'title': 'پرسش‌های پرتکرار', 'items': [
            {'q': 'چطور سفارش بدهم؟', 'a': 'از دکمهٔ تماس پیام بفرست تا راهنمایی‌ات کنیم.'},
            {'q': 'زمانِ تحویل چقدر است؟', 'a': 'معمولاً بینِ دو تا پنج روزِ کاری.'}]},
        style=G_SECTION),
    'cta': dict(
        label='دعوت به اقدام', group='ready', icon='megaphone', root=True,
        fields=[F('title', 'تیتر', inline=True), F('text', 'توضیح', 'textarea', inline=True),
                F('btn', 'متنِ دکمه', inline=True), F('btn_link', 'پیوندِ دکمه', 'link')],
        defaults={'title': 'آماده‌ای شروع کنیم؟', 'text': 'همین امروز پیام بده؛ مشاوره رایگان است.',
                  'btn': 'تماس با ما', 'btn_link': '#'},
        style=G_SECTION),
    'contact_form': dict(
        label='فرمِ تماس', group='ready', icon='mail', root=True,
        hint='پیام‌ها در مدیریتِ سایت ذخیره می‌شوند',
        fields=[F('title', 'تیتر', inline=True), F('text', 'توضیح', 'textarea', inline=True),
                F('fields', 'فیلدهای فرم', 'items', fields=_ITEM_FIELD, add_label='افزودنِ فیلد', item_label='label'),
                F('button', 'متنِ دکمه', inline=True), F('success', 'پیامِ پس از فرستادن')],
        defaults={'title': 'با ما در تماس باش', 'text': 'پیامت را بنویس؛ زود جواب می‌دهیم.',
                  'fields': [{'label': 'نام', 'type': 'text', 'required': True},
                             {'label': 'شمارهٔ تماس', 'type': 'tel', 'required': True},
                             {'label': 'پیام', 'type': 'textarea', 'required': True}],
                  'button': 'فرستادن', 'success': 'پیامت رسید. به‌زودی با تو تماس می‌گیریم.'},
        style=G_SECTION),
    'map': dict(
        label='نقشه', group='ready', icon='map', root=True,
        fields=[F('title', 'تیتر', inline=True), F('address', 'نشانی', 'textarea', inline=True),
                F('lat', 'عرضِ جغرافیایی', 'decimal'), F('lng', 'طولِ جغرافیایی', 'decimal'),
                F('map_height', 'بلندیِ نقشه', 'slider', min=200, max=700, unit='px')],
        defaults={'title': 'ما کجاییم', 'address': 'تهران، خیابانِ نمونه، پلاکِ ۱', 'lat': 35.6997, 'lng': 51.3380,
                  'map_height': 380},
        style=G_SECTION),

    # ── دادهٔ سایت ──
    'data_list': dict(
        label='فهرست از داده‌ها', group='data', icon='list',
        hint='مثلاً محصولات یا نوشته‌ها؛ خودکار از داده‌های سایت می‌آید',
        fields=[F('model', 'چه چیزی نشان داده شود؟', 'model'),
                F('fields', 'کدام اطلاعاتِ هر مورد؟', 'fields'),
                F('count', 'چند مورد؟', 'slider', min=1, max=48),
                F('sort', 'ترتیب', 'sort'),
                F('cols', 'تعداد در هر ردیف', 'slider', min=1, max=6, device=True),
                F('link', 'با کلیک روی هر مورد برود به', 'detail_link'),
                F('add_to_cart', 'دکمهٔ «افزودن به سبد» هم باشد', 'toggle', only_if='cart'),
                F('empty', 'اگر موردی نبود این را نشان بده')],
        defaults={'model': '', 'fields': [], 'count': 6, 'sort': '', 'cols': {'d': 3, 't': 2, 'p': 1}, 'link': '',
                  'add_to_cart': False, 'empty': 'هنوز موردی ثبت نشده است.'},
        style=['color', 'align', 'mt', 'mb', 'radius'] + G_VIS),
    'data_detail': dict(
        label='جزئیاتِ یک مورد', group='data', icon='detail',
        hint='برای صفحه‌ای که با کلیک روی یک مورد از فهرست باز می‌شود',
        fields=[F('model', 'چه چیزی نشان داده شود؟', 'model'),
                F('fields', 'کدام اطلاعات؟', 'fields'),
                F('empty', 'اگر مورد پیدا نشد این را نشان بده')],
        defaults={'model': '', 'fields': [], 'empty': 'این مورد پیدا نشد.'},
        style=['color', 'align', 'mt', 'mb'] + G_VIS),

    # ── سربرگ و پابرگِ سایت ──
    'site_header': dict(
        label='سربرگِ سایت', group='chrome', icon='hero', scope=['header'], root=True,
        fields=[F('logo', 'نشان (لوگو)', 'image'), F('logo_h', 'بلندیِ نشان', 'slider', min=20, max=90, unit='px'),
                F('show_title', 'نامِ سایت هم نوشته شود', 'toggle'),
                F('show_menu', 'منو نشان داده شود', 'toggle'),
                F('show_cart', 'پیوندِ سبدِ خرید', 'toggle', only_if='cart'),
                F('btn', 'متنِ دکمهٔ کنارِ منو'), F('btn_link', 'پیوندِ دکمه', 'link'),
                F('sticky', 'هنگامِ پایین‌رفتن بالای صفحه بماند', 'toggle')],
        defaults={'logo': '', 'logo_h': 40, 'show_title': True, 'show_menu': True, 'show_cart': False,
                  'btn': '', 'btn_link': '#', 'sticky': True},
        style=['color', 'bg', 'py', 'border', 'bw', 'shadow']),
    'menu_links': dict(
        label='فهرستِ منو', group='chrome', icon='list', scope=['footer'],
        fields=[], defaults={}, style=['color', 'size', 'mt', 'mb'] + G_VIS),
    'copyright': dict(
        label='نوشتهٔ پایانِ سایت', group='chrome', icon='text', scope=['footer'],
        fields=[F('text', 'متن', inline=True)], defaults={'text': 'همهٔ حقوق محفوظ است.'},
        style=['color', 'size', 'align', 'mt', 'mb'] + G_VIS),
}

CONTAINERS = {k for k, v in BLOCKS.items() if v.get('container')}
ROOT_ONLY = {k for k, v in BLOCKS.items() if v.get('root')}
# بلوک‌هایی که در سند می‌مانند ولی در فهرستِ افزودن نیستند یا فقط جای خاصی می‌آیند
LEGACY_PROPS = ('cls', 'inner_cls', 'btn_cls')


def default_props(btype):
    import copy
    return copy.deepcopy(BLOCKS[btype].get('defaults', {}))


def catalog_json():
    """همان چیزی که پنلِ React از رویش کتابخانهٔ بلوک و فرمِ تنظیمات را می‌سازد."""
    blocks = []
    for key, b in BLOCKS.items():
        blocks.append({
            'type': key, 'label': b['label'], 'group': b['group'], 'icon': b.get('icon', 'layout'),
            'hint': b.get('hint', ''), 'container': bool(b.get('container')), 'root': bool(b.get('root')),
            'structural': bool(b.get('structural')), 'hidden': bool(b.get('hidden')),
            'advanced': bool(b.get('advanced')), 'scope': b.get('scope') or [],
            'fields': b.get('fields', []), 'style': b.get('style', []), 'defaults': default_props(key),
        })
    return {'blocks': blocks, 'groups': GROUPS, 'style': STYLE, 'style_groups': STYLE_GROUPS, 'icons': ICONS}
