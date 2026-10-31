# -*- coding: utf-8 -*-
"""صفحه‌های آمادهٔ فارسی برای شروع + سربرگ و پابرگِ پیش‌فرض."""
from .clean import new_block as B


def _section(*children, bg=None, py=None, align=None, full=False):
    d = {}
    if bg:
        d['bg'] = bg
    if py is not None:
        d['py'] = py
    if align:
        d['align'] = align
    return B('section', children=list(children), full=full, style={'d': d} if d else {})


def _cols(*cols, ratio='equal', gap=32, valign='center'):
    return B('columns', children=[B('column', children=list(c)) for c in cols], count=len(cols), ratio=ratio, gap=gap, valign=valign)


def _center(text, level=2):
    return B('heading', text=text, level=level, style={'d': {'align': 'center'}})


def home(ctx=None):
    return [
        B('hero', title='کسب‌وکارت را با یک سایتِ خوب شروع کن',
          subtitle='این متن نمونه است. روی هر نوشته بزن و متنِ خودت را بنویس؛ رنگ‌ها را هم از «پوسته» عوض کن.',
          btn1='تماس با ما', btn2='بیشتر بدانید'),
        B('features'),
        _section(
            _cols(
                [B('heading', text='داستانِ ما', level=2),
                 B('text', html='<p>چند جمله دربارهٔ خودت و کارت بنویس. بگو از کی شروع کرده‌ای، چه چیزی برایت مهم است و مشتری با تو چه تجربه‌ای خواهد داشت.</p>'),
                 B('button', text='دربارهٔ ما', link='#', variant='outline')],
                [B('image', alt='', style={'d': {'radius': 18, 'shadow': 'medium'}})],
            ),
            bg='t:surface'),
        B('testimonials'),
        B('faq'),
        B('cta'),
    ]


def about(ctx=None):
    return [
        B('hero', eyebrow='دربارهٔ ما', title='ما که هستیم و چرا این کار را می‌کنیم',
          subtitle='در یک جمله بگو مأموریتت چیست.', btn1='', btn2=''),
        _section(
            _cols(
                [B('image', alt='', style={'d': {'radius': 18, 'shadow': 'medium'}})],
                [B('heading', text='از کجا شروع شد', level=2),
                 B('text', html='<p>داستانِ شروعِ کارت را این‌جا بنویس. مردم به داستان‌ها اعتماد می‌کنند؛ پس ساده و صادقانه بگو.</p><p>بعد بگو الان کجا ایستاده‌ای و چه چیزی تو را از بقیه جدا می‌کند.</p>')],
            )),
        B('features', title='ارزش‌های ما', subtitle='چیزهایی که هیچ‌وقت درباره‌شان کوتاه نمی‌آییم',
          items=[{'icon': 'heart', 'title': 'صداقت', 'text': 'هر چه می‌گوییم همان است.'},
                 {'icon': 'award', 'title': 'کیفیت', 'text': 'کارِ خوب را با حوصله انجام می‌دهیم.'},
                 {'icon': 'users', 'title': 'همراهی', 'text': 'بعد از خرید هم کنارت هستیم.'}],
          style={'d': {'bg': 't:surface'}}),
        B('cta', title='می‌خواهی با هم کار کنیم؟', text='یک پیام بفرست تا گپ بزنیم.', btn='تماس با ما'),
    ]


def contact(ctx=None):
    return [
        _section(
            B('heading', text='تماس با ما', level=1, style={'d': {'align': 'center'}}),
            B('text', html='<p>هر پرسشی داری بنویس؛ معمولاً همان روز جواب می‌دهیم.</p>', style={'d': {'align': 'center'}}),
            py=48),
        B('contact_form', title='', text='', style={'p': {'py': 16}, 'd': {'py': 16}}),
        _section(
            _cols(
                [B('icon', name='phone', icon_size=32), B('heading', text='تلفن', level=3), B('text', html='<p>۰۲۱-۱۲۳۴۵۶۷۸</p>')],
                [B('icon', name='mail', icon_size=32), B('heading', text='ایمیل', level=3), B('text', html='<p>info@example.com</p>')],
                [B('icon', name='clock', icon_size=32), B('heading', text='ساعتِ کار', level=3), B('text', html='<p>شنبه تا پنجشنبه، ۹ تا ۱۷</p>')],
                valign='start'),
            py=40),
        B('map', style={'d': {'bg': 't:surface'}}),
    ]


def shop(ctx=None):
    model = ''
    fields = []
    add = False
    if ctx is not None:
        for ref in ctx.models:
            if ref == 'catalog.Product':
                model = ref
                add = ctx.has_cart
                break
        if not model and ctx.models:
            model = next(iter(ctx.models))
        if ref_has(ctx, model):
            from .render import default_fields
            fields = default_fields(ctx.models[model])
    link = 'auto' if model == 'catalog.Product' else ''
    return [
        _section(
            B('heading', text='محصولات', level=1, style={'d': {'align': 'center'}}),
            B('text', html='<p>جدیدترین‌ها را این‌جا ببین.</p>', style={'d': {'align': 'center'}}),
            B('data_list', model=model, fields=fields, count=12, add_to_cart=add, link=link,
              cols={'d': 4, 't': 3, 'p': 2}, style={'d': {'mt': 24}}),
            py=48),
        B('cta', title='دنبالِ چیزِ خاصی هستی؟', text='پیام بده تا راهنمایی‌ات کنیم.', btn='تماس با ما'),
    ]


def ref_has(ctx, model):
    return bool(model and model in ctx.models)


def home_shop(ctx=None):
    list_block = shop(ctx)[0]['children'][-1]
    list_block['props']['count'] = 8
    return [
        B('hero', title='همه‌چیز برای خریدی راحت و مطمئن',
          subtitle='این متن نمونه است؛ روی آن بزن و بنویس فروشگاهت چه می‌فروشد.', btn1='دیدنِ محصولات', btn1_link='/products/', btn2=''),
        _section(_center('جدیدترین محصولات'), list_block, py=56),
        B('features', title='چرا از ما بخرید؟', subtitle='',
          items=[{'icon': 'truck', 'title': 'ارسالِ سریع', 'text': 'به سراسرِ کشور ارسال می‌کنیم.'},
                 {'icon': 'shield', 'title': 'ضمانتِ اصالت', 'text': 'همهٔ کالاها اصل و با ضمانت‌اند.'},
                 {'icon': 'chat', 'title': 'پشتیبانی', 'text': 'هر سؤالی داری کنارت هستیم.'}],
          style={'d': {'bg': 't:surface'}}),
        B('cta'),
    ]


def blank(ctx=None):
    return [_section(B('heading', text='عنوانِ صفحه', level=1), B('text'))]


STARTERS = [
    {'key': 'home', 'title': 'صفحهٔ اصلی', 'desc': 'سربرگِ بزرگ، ویژگی‌ها، داستان، نظرِ مشتریان و پرسش‌ها', 'icon': 'home', 'slug': '', 'fn': home},
    {'key': 'home_shop', 'title': 'صفحهٔ اصلیِ فروشگاه', 'desc': 'سربرگ، جدیدترین محصولات و دلایلِ خرید', 'icon': 'cart', 'slug': '', 'fn': home_shop},
    {'key': 'about', 'title': 'دربارهٔ ما', 'desc': 'داستانِ شما، ارزش‌ها و دعوت به تماس', 'icon': 'users', 'slug': 'about', 'fn': about},
    {'key': 'contact', 'title': 'تماس با ما', 'desc': 'فرمِ کارکننده، راه‌های تماس و نقشه', 'icon': 'mail', 'slug': 'contact', 'fn': contact},
    {'key': 'shop', 'title': 'فروشگاه یا فهرست', 'desc': 'فهرستِ خودکار از محصولات یا هر دادهٔ دیگرِ سایت', 'icon': 'tag', 'slug': 'shop', 'fn': shop},
    {'key': 'blank', 'title': 'صفحهٔ خالی', 'desc': 'از صفر خودت می‌چینی', 'icon': 'layout', 'slug': 'page', 'fn': blank},
]
BY_KEY = {s['key']: s for s in STARTERS}


def starter_doc(key, ctx=None):
    s = BY_KEY.get(key) or BY_KEY['blank']
    return {'v': 1, 'blocks': s['fn'](ctx)}


def starters_json():
    return [{k: s[k] for k in ('key', 'title', 'desc', 'icon', 'slug')} for s in STARTERS]


def header_doc(ctx=None):
    show_cart = bool(ctx and ctx.has_cart)
    return {'v': 1, 'blocks': [B('site_header', show_cart=show_cart)]}


def footer_doc(ctx=None):
    return {'v': 1, 'blocks': [
        _section(
            _cols(
                [B('heading', text='دربارهٔ ما', level=4),
                 B('text', html='<p>یک یا دو جمله دربارهٔ کسب‌وکارت بنویس.</p>')],
                [B('heading', text='دسترسیِ سریع', level=4), B('menu_links')],
                [B('heading', text='تماس', level=4), B('text', html='<p>۰۲۱-۱۲۳۴۵۶۷۸<br>info@example.com</p>')],
                valign='start'),
            B('divider', style={'d': {'mt': 24, 'mb': 8}}),
            B('copyright'),
            bg='t:surface', py=44),
    ]}
