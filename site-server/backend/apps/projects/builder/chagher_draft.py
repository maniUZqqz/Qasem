# -*- coding: utf-8 -*-
"""پیش‌نویسِ صفحهٔ فرودِ «چغر» با سبکِ طراحی و قطعه‌های آماده — بررسیِ واقعیِ کیفیتِ سایت‌ساز با محصولِ خودِ مالک.

⚠ فقط پیش‌نویس است: هیچ‌چیز منتشر نمی‌شود و به بیرون نمی‌رود. همهٔ جمله‌ها از `docs/chagher/brand-facts-fa.md` (بخشِ ۲ و ۴) آمده؛
قیمت، آمارِ تأییدنشده («۹۸٪ رضایت»)، نظرِ مشتریِ ساختگی و وعدهٔ پزشکی عمداً نیست. «بیش از ۱٬۳۰۰ حرکت» از دیتابیسِ خودِ چغر و در سندِ واقعیت‌ها آمده است.

  build(style)          ⇒ {'theme', 'page', 'header', 'footer', 'menu'} (سندهای تمیز)
  static_page(parts)    ⇒ یک HTMLِ کاملِ مستقل برای دیدنِ نتیجه در مرورگر (بی‌پایگاه‌داده؛ قلم‌ها از پوشهٔ fonts/ کنارِ فایل)
  create_draft(slug)    ⇒ پروژهٔ پیش‌نویس در سایت‌ساز (صفحهٔ اصلی + سربرگ + پابرگ + پوسته؛ active=False و بی‌انتشار)
"""
from . import components as C, styles, theme as theme_mod
from .clean import clean_doc, new_block

BRAND = {'name': 'چغر', 'primary': '#126F85', 'slogan': 'با چغر چغر تر شو', 'panel': 'https://panel.chagher.ir', 'site': 'https://chagher.ir'}
DEFAULT_STYLE = 'bento-grid'


def _b(key, **props):
    return new_block(C.block_type(key), **props)


def blocks():
    nav = [_b('nav_classic', btn='ورود به پنل', btn_link=BRAND['panel'], sticky=True)]
    page = [
        _b('hero_center_glow', kicker='دستیار هوش مصنوعیِ مربی‌ها', title='برنامهٔ ورزشی و غذاییِ هر ورزشکار، پیش‌نویس در کمتر از یک دقیقه',
           subtitle='چغر کنارِ مربی کار می‌کند: پیش‌نویسِ برنامه را می‌سازد و تصمیمِ نهایی با خودِ مربی است.',
           btn1='شروعِ رایگان', btn1_link=BRAND['panel'], btn2='دیدنِ امکانات', btn2_link=BRAND['site'], note='ثبت‌نام کمتر از یک دقیقه؛ بدونِ نیاز به کارتِ اعتباری'),
        _b('feat_bento_showcase', title='هر آنچه یک مربی برای ساختنِ برنامه لازم دارد', subtitle='از پیش‌نویسِ هوشمند تا خروجیِ آمادهٔ چاپ',
           items=[{'icon': 'zap', 'title': 'پیش‌نویسِ برنامه در کمتر از یک دقیقه', 'text': 'برنامهٔ ورزشی و غذاییِ اختصاصیِ هر ورزشکار؛ تصمیمِ نهایی با توست.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'settings', 'title': 'دستورالعملِ شخصیِ مربی', 'text': 'قاعده‌های ثابتت را یک بار می‌نویسی و در تولیدِ هر برنامه رعایت می‌شود.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'book', 'title': 'خروجیِ PDFِ برندشده', 'text': 'حرفه‌ای و قابل‌چاپ؛ نامِ هر حرکت لینکِ آموزشِ همان حرکت است.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'camera', 'title': 'اسکنِ دستگاه‌های باشگاه', 'text': 'با دوربین؛ تا تأییدِ مربی چیزی ثبت نمی‌شود.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'users', 'title': 'کتابخانهٔ بیش از ۱٬۳۰۰ حرکت', 'text': 'هر حرکت با نامِ فارسی، گیف و عکس.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'layout', 'title': 'برنامه‌سازِ دستی با تمپلیت', 'text': 'بدونِ هوش مصنوعی و با تمپلیت‌های آماده؛ ویرایشش رایگان است.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']}]),
        _b('steps_horizontal', title='چهار قدم تا اولین برنامه', subtitle='از ثبت‌نام تا برنامهٔ آماده',
           items=[{'title': 'ثبت‌نام', 'text': 'کمتر از یک دقیقه؛ شروع رایگان و بدونِ کارتِ اعتباری.'},
                  {'title': 'خریدِ توکن', 'text': 'پرداختِ آنلاین از درگاه‌های معتبر.'},
                  {'title': 'اطلاعاتِ مجموعه', 'text': 'تجهیزات، غذاها و دستورالعملِ شخصیِ خودت را وارد کن.'},
                  {'title': 'تولیدِ برنامه', 'text': 'پیش‌نویس را بگیر، ویرایش کن و تحویل بده.'}]),
        _b('card_spotlight', title='برای چه کسانی؟', subtitle='',
           items=[{'title': 'مربی‌های باشگاه', 'text': 'برنامهٔ هر عضو را سریع‌تر پیش‌نویس کن و وقتت را به همراهیِ ورزشکار بده.', 'link_text': '', 'link': '#'},
                  {'title': 'مربی‌های شخصی', 'text': 'قاعده‌های خودت را یک بار بنویس تا در هر برنامه رعایت شود.', 'link_text': '', 'link': '#'},
                  {'title': 'ورزشکارِ شخصی', 'text': 'با حسابِ شخصی و انتخابِ محیطِ تمرین: خانه بدونِ تجهیزات، خانه با دمبل و کش، یا باشگاه.', 'link_text': '', 'link': '#'}]),
        _b('faq_two_col', title='پرسش‌های پرتکرار', subtitle='جوابِ پرسشِ تو این‌جا نبود؟ از سایتِ چغر بپرس.', btn='سایتِ چغر', btn_link=BRAND['site'],
           items=[{'q': 'چغر جایگزینِ مربی است؟', 'a': 'نه. چغر پیش‌نویسِ برنامه را می‌سازد و تصمیمِ نهایی همیشه با مربی است.'},
                  {'q': 'شروع رایگان است؟', 'a': 'بله؛ ثبت‌نام کمتر از یک دقیقه است و برای شروع به کارتِ اعتباری نیازی نیست.'},
                  {'q': 'خروجی چه شکلی است؟', 'a': 'یک PDFِ حرفه‌ای و برندشده که قابلِ چاپ است؛ نامِ هر حرکت هم لینکِ آموزشِ همان حرکت است.'}]),
        _b('cta_center_box', title=BRAND['slogan'], text='ثبت‌نام کمتر از یک دقیقه است و شروع رایگان؛ بدونِ نیاز به کارتِ اعتباری.', btn1='ساختِ حسابِ رایگان', btn1_link=BRAND['panel'],
           btn2='دیدنِ سایت', btn2_link=BRAND['site']),
    ]
    foot = [_b('footer_columns', about='چغر؛ دستیار هوش مصنوعیِ مربی‌ها. پیش‌نویسِ برنامهٔ ورزشی و غذایی را می‌سازد و تصمیمِ نهایی با مربی است.', social='',
               menu_title='دسترسیِ سریع', col2_title='چغر', col2_links='سایتِ چغر | %s\nپنلِ چغر | %s' % (BRAND['site'], BRAND['panel']),
               col3_title='شعار', col3_text=BRAND['slogan'], copy='همهٔ حقوق محفوظ است.')]
    return nav, page, foot


def theme(style=DEFAULT_STYLE):
    """سبک + رنگِ اصلیِ برند + قلمِ برند (وزیرمتن)؛ بقیهٔ پالت و شکل‌ها از سبک."""
    base = theme_mod.default_theme()
    base['colors']['primary'] = BRAND['primary']
    out = styles.apply_to_theme(base, style, keep_brand=True)
    out['font_head'] = out['font_body'] = 'vazirmatn'
    return theme_mod.clean_theme(out)


def menu():
    return [{'id': 'm1', 'url': BRAND['panel'], 'label': 'پنلِ چغر'}, {'id': 'm2', 'url': BRAND['site'], 'label': 'سایتِ چغر'}]


def build(style=DEFAULT_STYLE):
    nav, page, foot = blocks()
    th = theme(style)
    return {'theme': th, 'menu': menu(), 'header': clean_doc({'v': 1, 'blocks': nav}, 'header'), 'page': clean_doc({'v': 1, 'blocks': page}, 'page'),
            'footer': clean_doc({'v': 1, 'blocks': foot}, 'footer')}


def static_page(parts, fonts_prefix='fonts/', canvas=False):
    """⇒ HTMLِ کاملِ مستقل (بی‌پایگاه‌داده) از همان رندرکننده‌ای که سایتِ واقعی را می‌سازد."""
    from apps.code_generation import generator
    from . import canvas as cv, render as R
    th = parts['theme']
    out, css = {}, {}
    for target in ('header', 'page', 'footer'):
        ctx = R.Ctx(canvas=canvas, target=target, theme=th['colors'])
        r = R.render_doc(parts[target], ctx)
        out[target], css[target] = r.html, r.css
    menu_rows = [(m['label'], m['url']) for m in parts['menu']]
    context = {'MENU': menu_rows, 'MENU_TREE': [{'title': t, 'href': h, 'children': []} for t, h in menu_rows], 'SITE_TITLE': BRAND['name'], 'CURRENT_PATH': '/',
               'cart': [], 'request': {'path': '/'}, 'DATA': {}}
    body = {k: cv.render_template(v, context) for k, v in out.items()}
    base = theme_mod.apply_zone(generator.BASE_CSS % {'brand': th['colors']['primary']}, th)
    blocks_css = theme_mod.blocks_css(th, fonts_prefix, '\n'.join(css[k] for k in ('header', 'footer') if css[k]))
    return ('<!doctype html>\n<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>%s — پیش‌نویسِ صفحهٔ فرود</title>\n<style>\n%s\n%s\n%s\n</style></head>\n<body>\n%s\n<main>\n%s\n</main>\n<footer class="nb-footer">%s</footer>\n</body></html>\n'
            % (BRAND['name'], base, blocks_css, R.page_css(css['page']), body['header'], body['page'], body['footer']))


def create_draft(slug='chagher-landing', style=DEFAULT_STYLE):
    """پروژهٔ پیش‌نویس در سایت‌ساز. بی‌انتشار: SiteTheme.active نمی‌شود، چیزی ساخته یا اجرا نمی‌شود. اگر پروژه هست همان را برمی‌گرداند (چیزی بازنویسی نمی‌شود)."""
    from apps.projects.models import Design, Page, Project, SiteTheme
    from . import publish as P
    p = Project.objects.filter(slug=slug).first()
    if p is not None:
        return p, False
    parts = build(style)
    p = Project.objects.create(name='چغر — پیش‌نویسِ صفحهٔ فرود', slug=slug, brand_color=BRAND['primary'], site_title=BRAND['name'], description='پیش‌نویسِ صفحهٔ فرودِ چغر با سبکِ طراحی و قطعه‌های آماده (فقط پیش‌نویس).')
    page = Page.objects.create(project=p, title='صفحهٔ اصلی', slug='', kind='home', body_html='', in_menu=False, order=10)
    Design.objects.create(project=p, target='page', page=page, draft=parts['page'], synced_hash=P.fingerprint(p, 'page', page))
    for target in ('header', 'footer'):
        Design.objects.create(project=p, target=target, draft=parts[target], synced_hash=P.fingerprint(p, target, None))
    t, _ = SiteTheme.objects.get_or_create(project=p)
    t.draft = parts['theme']
    t.menu = parts['menu']
    t.save()
    return p, True


__all__ = ['build', 'static_page', 'create_draft', 'theme', 'BRAND']
