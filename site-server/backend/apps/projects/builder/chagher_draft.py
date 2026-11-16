# -*- coding: utf-8 -*-
"""پیش‌نویسِ صفحهٔ فرودِ «چغر» با سبکِ طراحی و قطعه‌های آماده — بررسیِ واقعیِ کیفیتِ سایت‌ساز با محصولِ خودِ مالک.

⚠ فقط پیش‌نویس است: هیچ‌چیز منتشر نمی‌شود و به بیرون نمی‌رود. همهٔ جمله‌ها از `docs/chagher/brand-facts-fa.md` (بخشِ ۲ و ۴) آمده؛
قیمت، آمارِ تأییدنشده («۹۸٪ رضایت»)، نظرِ مشتریِ ساختگی و وعدهٔ پزشکی عمداً نیست. «بیش از ۱٬۳۰۰ حرکت» از دیتابیسِ خودِ چغر و در سندِ واقعیت‌ها آمده است.

  build(style)          ⇒ {'theme', 'page', 'header', 'footer', 'menu'} (سندهای تمیز)
  static_page(parts)    ⇒ یک HTMLِ کاملِ مستقل برای دیدنِ نتیجه در مرورگر (بی‌پایگاه‌داده؛ قلم‌ها از پوشهٔ fonts/ کنارِ فایل)
  create_draft(slug)    ⇒ پروژهٔ پیش‌نویس در سایت‌ساز (صفحهٔ اصلی + سربرگ + پابرگ + پوسته؛ active=False و بی‌انتشار)
  refresh_draft(slug)   ⇒ همان پروژه را به آخرین طرح می‌رساند (لوگو، نمادِ درست، بی‌«#»، جای تصویر) — فقط اگر مالک هنوز چیزی در آن عوض نکرده

لوگو: نشانِ عمومیِ خودِ چغر (assets/chagher/logo.webp؛ همان فایلِ chagher.ir/static/img/logo.webp، فقط بریده‌شده) به کتابخانهٔ رسانهٔ پروژه می‌آید.
تصویرِ بالای صفحه عمداً خالی است: «جای تصویر» با پیامِ «هنوز انتخاب نشده» می‌ماند تا مالک اسکرین‌شاتِ واقعیِ پنل را بگذارد؛ هرگز تصویرِ ساختگی نمی‌گذاریم.
"""
import os

from . import components as C, styles, theme as theme_mod
from .clean import clean_doc, new_block

BRAND = {'name': 'چغر', 'primary': '#126F85', 'slogan': 'با چغر چغر تر شو', 'panel': 'https://panel.chagher.ir', 'site': 'https://chagher.ir',
         'logo_url': 'https://chagher.ir/static/img/logo.webp'}
DEFAULT_STYLE = 'bento-grid'
LOGO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'chagher', 'logo.webp')
# نشانِ تیره‌آبی روی سربرگِ تیره (شفق، لوکسِ تیره) گم می‌شود؛ شناسنامهٔ برند می‌گوید روی کاشیِ سفیدِ گوشه‌گرد بیاید
LOGO_CSS = '.nbc .nb-brand .nb-logo,.nbc .nbc-fc-logo{background:#fff;border-radius:10px;padding:5px}'


def _b(key, **props):
    return new_block(C.block_type(key), **props)


def blocks(logo=''):
    """logo: مرجعِ تصویرِ نشان (m:<شناسه> در پروژه، یا نشانیِ https برای پیش‌نمایشِ مستقل)؛ خالی = بی‌نشان."""
    alt = BRAND['name'] if logo else ''
    nav = [_b('nav_classic', btn='ورود به پنل', btn_link=BRAND['panel'], sticky=True, logo=logo, logo_alt=alt)]
    hero_visual = new_block('section', children=[new_block('image', src='', alt='', style={'d': {'radius': 18, 'shadow': 'medium', 'width': 80, 'align': 'center'}})],
                            style={'d': {'py': 0}})
    page = [
        _b('hero_center_glow', kicker='دستیار هوش مصنوعیِ مربی‌ها', title='برنامهٔ ورزشی و غذاییِ هر ورزشکار، پیش‌نویس در کمتر از یک دقیقه',
           subtitle='چغر کنارِ مربی کار می‌کند: پیش‌نویسِ برنامه را می‌سازد و تصمیمِ نهایی با خودِ مربی است.',
           btn1='شروعِ رایگان', btn1_link=BRAND['panel'], btn2='دیدنِ امکانات', btn2_link=BRAND['site'], note='ثبت‌نام کمتر از یک دقیقه؛ بدونِ نیاز به کارتِ اعتباری'),
        hero_visual,
        _b('feat_bento_showcase', title='هر آنچه یک مربی برای ساختنِ برنامه لازم دارد', subtitle='از پیش‌نویسِ هوشمند تا خروجیِ آمادهٔ چاپ',
           items=[{'icon': 'zap', 'title': 'پیش‌نویسِ برنامه در کمتر از یک دقیقه', 'text': 'برنامهٔ ورزشی و غذاییِ اختصاصیِ هر ورزشکار؛ تصمیمِ نهایی با توست.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'list', 'title': 'دستورالعملِ شخصیِ مربی', 'text': 'قاعده‌های ثابتت را یک بار می‌نویسی و در تولیدِ هر برنامه رعایت می‌شود.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'book', 'title': 'خروجیِ PDFِ برندشده', 'text': 'حرفه‌ای و قابل‌چاپ؛ نامِ هر حرکت لینکِ آموزشِ همان حرکت است.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'camera', 'title': 'اسکنِ دستگاه‌های باشگاه', 'text': 'با دوربین؛ تا تأییدِ مربی چیزی ثبت نمی‌شود.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'gallery', 'title': 'کتابخانهٔ بیش از ۱٬۳۰۰ حرکت', 'text': 'هر حرکت با نامِ فارسی، گیف و عکس.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']},
                  {'icon': 'layout', 'title': 'برنامه‌سازِ دستی با تمپلیت', 'text': 'بدونِ هوش مصنوعی و با تمپلیت‌های آماده؛ ویرایشش رایگان است.',
                   'link_text': 'بیشتر بدانید', 'link': BRAND['site']}]),
        _b('steps_horizontal', title='چهار قدم تا اولین برنامه', subtitle='از ثبت‌نام تا برنامهٔ آماده',
           items=[{'title': 'ثبت‌نام', 'text': 'کمتر از یک دقیقه؛ شروع رایگان و بدونِ کارتِ اعتباری.'},
                  {'title': 'خریدِ توکن', 'text': 'پرداختِ آنلاین از درگاه‌های معتبر.'},
                  {'title': 'اطلاعاتِ مجموعه', 'text': 'تجهیزات، غذاها و دستورالعملِ شخصیِ خودت را وارد کن.'},
                  {'title': 'تولیدِ برنامه', 'text': 'پیش‌نویس را بگیر، ویرایش کن و تحویل بده.'}]),
        _b('card_spotlight', title='برای چه کسانی؟', subtitle='',
           items=[{'title': 'مربی‌های باشگاه', 'text': 'برنامهٔ هر عضو را سریع‌تر پیش‌نویس کن و وقتت را به همراهیِ ورزشکار بده.', 'link_text': '', 'link': ''},
                  {'title': 'مربی‌های شخصی', 'text': 'قاعده‌های خودت را یک بار بنویس تا در هر برنامه رعایت شود.', 'link_text': '', 'link': ''},
                  {'title': 'ورزشکارِ شخصی', 'text': 'با حسابِ شخصی و انتخابِ محیطِ تمرین: خانه بدونِ تجهیزات، خانه با دمبل و کش، یا باشگاه.', 'link_text': '', 'link': ''}]),
        _b('faq_two_col', title='پرسش‌های پرتکرار', subtitle='جوابِ پرسشِ تو این‌جا نبود؟ از سایتِ چغر بپرس.', btn='سایتِ چغر', btn_link=BRAND['site'],
           items=[{'q': 'چغر جایگزینِ مربی است؟', 'a': 'نه. چغر پیش‌نویسِ برنامه را می‌سازد و تصمیمِ نهایی همیشه با مربی است.'},
                  {'q': 'شروع رایگان است؟', 'a': 'بله؛ ثبت‌نام کمتر از یک دقیقه است و برای شروع به کارتِ اعتباری نیازی نیست.'},
                  {'q': 'خروجی چه شکلی است؟', 'a': 'یک PDFِ حرفه‌ای و برندشده که قابلِ چاپ است؛ نامِ هر حرکت هم لینکِ آموزشِ همان حرکت است.'}]),
        _b('cta_center_box', title=BRAND['slogan'], text='ثبت‌نام کمتر از یک دقیقه است و شروع رایگان؛ بدونِ نیاز به کارتِ اعتباری.', btn1='ساختِ حسابِ رایگان', btn1_link=BRAND['panel'],
           btn2='دیدنِ سایت', btn2_link=BRAND['site']),
    ]
    foot = [_b('footer_columns', about='چغر؛ دستیار هوش مصنوعیِ مربی‌ها. پیش‌نویسِ برنامهٔ ورزشی و غذایی را می‌سازد و تصمیمِ نهایی با مربی است.', social='',
               menu_title='دسترسیِ سریع', col2_title='چغر', col2_links='سایتِ چغر | %s\nپنلِ چغر | %s' % (BRAND['site'], BRAND['panel']),
               col3_title='شعار', col3_text=BRAND['slogan'], copy='همهٔ حقوق محفوظ است.', logo=logo, logo_alt=alt)]
    return nav, page, foot


def _lighten(hexv, k):
    h = hexv.lstrip('#')
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return '#%02x%02x%02x' % tuple(round(c + (255 - c) * k) for c in rgb)


def readable_colors(colors):
    """رنگِ برند روی زمینهٔ تیره (شفق، لوکسِ تیره) تباینِ ۳٫۳ می‌داد و متنِ کوچکِ آن (برچسبِ بالای تیتر، دکمهٔ دوم) خوانده نمی‌شد.
    برندِ فیروزه‌ای همان خانواده می‌ماند ولی آن‌قدر روشن می‌شود که روی زمینه دست‌کم ۴٫۵ باشد؛ متنِ روی دکمهٔ پُر هم تیره می‌شود.
    روی زمینهٔ روشنی که برند روی آن خوانا است هیچ‌چیز عوض نمی‌شود (رنگِ برند همان است)؛ روی زمینهٔ روشنِ کم‌تباین (مثلاً بژِ «شبیه‌واقعی») همان فیروزه‌ای ولی تیره‌تر می‌شود."""
    from .render import contrast
    out = dict(colors)
    if contrast(out['primary'], out['bg']) >= 4.5:
        return out
    from .styles.gen_core import lum, shade
    light_bg = lum(out['bg']) > 0.4
    for step in range(1, 41):
        cand = shade(BRAND['primary'], step * 0.02) if light_bg else _lighten(BRAND['primary'], step * 0.015)
        if contrast(cand, out['bg']) >= 4.5:
            out['primary'] = cand
            break
    out['on_primary'] = out['bg'] if contrast(out['bg'], out['primary']) >= contrast('#ffffff', out['primary']) else '#ffffff'
    return out


def theme(style=DEFAULT_STYLE):
    """سبک + رنگِ اصلیِ برند + قلمِ برند (وزیرمتن)؛ بقیهٔ پالت و شکل‌ها از سبک."""
    base = theme_mod.default_theme()
    base['colors']['primary'] = BRAND['primary']
    out = styles.apply_to_theme(base, style, keep_brand=True)
    out['colors'] = readable_colors(out['colors'])
    out['font_head'] = out['font_body'] = 'vazirmatn'
    return theme_mod.clean_theme(out)


def menu():
    return [{'id': 'm1', 'url': BRAND['panel'], 'label': 'پنلِ چغر'}, {'id': 'm2', 'url': BRAND['site'], 'label': 'سایتِ چغر'}]


def build(style=DEFAULT_STYLE, logo=''):
    nav, page, foot = blocks(logo)
    th = theme(style)
    extra = {'extra_css': LOGO_CSS} if logo else {}
    return {'theme': th, 'menu': menu(), 'header': clean_doc({'v': 1, 'blocks': nav, **extra}, 'header'), 'page': clean_doc({'v': 1, 'blocks': page}, 'page'),
            'footer': clean_doc({'v': 1, 'blocks': foot, **extra}, 'footer')}


def static_page(parts, fonts_prefix='fonts/', canvas=False):
    """⇒ HTMLِ کاملِ مستقل (بی‌پایگاه‌داده) از همان رندرکننده‌ای که سایتِ واقعی را می‌سازد."""
    from apps.code_generation import generator
    from . import canvas as cv, render as R
    th = parts['theme']
    out, css = {}, {}
    for target in ('header', 'page', 'footer'):
        ctx = R.Ctx(canvas=canvas, target=target, theme=th['colors'])
        r = R.render_doc(parts[target], ctx)
        out[target], css[target] = r.html, r.css + ('\n' + parts[target]['extra_css'] if parts[target].get('extra_css') else '')
    menu_rows = [(m['label'], m['url']) for m in parts['menu']]
    context = {'MENU': menu_rows, 'MENU_TREE': [{'title': t, 'href': h, 'children': []} for t, h in menu_rows], 'SITE_TITLE': BRAND['name'], 'CURRENT_PATH': '/',
               'cart': [], 'request': {'path': '/'}, 'DATA': {}}
    body = {k: cv.render_template(v, context) for k, v in out.items()}
    base = theme_mod.apply_zone(generator.BASE_CSS % {'brand': th['colors']['primary']}, th)
    blocks_css = theme_mod.blocks_css(th, fonts_prefix, '\n'.join(css[k] for k in ('header', 'footer') if css[k]))
    return ('<!doctype html>\n<html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>%s — پیش‌نویسِ صفحهٔ فرود</title>\n<style>\n%s\n%s\n%s\n</style></head>\n<body>\n%s\n<main>\n%s\n</main>\n<footer class="nb-footer">%s</footer>\n</body></html>\n'
            % (BRAND['name'], base, blocks_css, R.page_css(css['page']), body['header'], body['page'], body['footer']))


def import_logo(project):
    """نشانِ چغر را (از فایلِ همراهِ برنامه، نه از اینترنت) به کتابخانهٔ رسانهٔ همین پروژه می‌آورد ⇒ مرجعِ «m:<شناسه>». دوباره صدا بزنی همان فایل برمی‌گردد."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from . import media
    with open(LOGO_FILE, 'rb') as fh:
        data = fh.read()
    asset = media.save_upload(project, SimpleUploadedFile('chagher-logo.webp', data, content_type='image/webp'), alt=BRAND['name'])
    return 'm:%d' % asset.pk


def create_draft(slug='chagher-landing', style=DEFAULT_STYLE):
    """پروژهٔ پیش‌نویس در سایت‌ساز. بی‌انتشار: SiteTheme.active نمی‌شود، چیزی ساخته یا اجرا نمی‌شود. اگر پروژه هست همان را برمی‌گرداند (چیزی بازنویسی نمی‌شود)."""
    from apps.projects.models import Design, Page, Project, SiteTheme
    from . import publish as P
    p = Project.objects.filter(slug=slug).first()
    if p is not None:
        return p, False
    p = Project.objects.create(name='چغر — پیش‌نویسِ صفحهٔ فرود (%s)' % styles.STYLES[style]['label'], slug=slug, brand_color=BRAND['primary'], site_title=BRAND['name'], description='پیش‌نویسِ صفحهٔ فرودِ چغر با سبکِ طراحی و قطعه‌های آماده (فقط پیش‌نویس).')
    parts = build(style, logo=import_logo(p))
    page = Page.objects.create(project=p, title='صفحهٔ اصلی', slug='', kind='home', body_html='', in_menu=False, order=10)
    Design.objects.create(project=p, target='page', page=page, draft=parts['page'], synced_hash=P.fingerprint(p, 'page', page))
    for target in ('header', 'footer'):
        Design.objects.create(project=p, target=target, draft=parts[target], synced_hash=P.fingerprint(p, target, None))
    t, _ = SiteTheme.objects.get_or_create(project=p)
    t.draft = parts['theme']
    t.menu = parts['menu']
    t.save()
    return p, True


def refresh_draft(slug='chagher-landing'):
    """پیش‌نویسِ ساخته‌شده را به آخرین طرح می‌رساند (لوگو، نمادِ درست، بی‌پیوندِ «#»، جای تصویر). ⇒ (انجام شد؟، دلیل).

    فقط اگر مالک هنوز دست نزده باشد: هر سه سند (صفحه، سربرگ، پابرگ) rev == 1، بی‌نسخهٔ ذخیره‌شده و بی‌انتشار. هر ذخیره‌ای از ویرایشگر rev را بالا می‌برد؛
    پس اگر چیزی عوض شده باشد چیزی بازنویسی نمی‌شود. پوسته (سبکِ انتخاب‌شده) هم دست نمی‌خورد؛ فقط سندها."""
    from apps.projects.models import Design, Project
    p = Project.objects.filter(slug=slug).first()
    if p is None:
        return False, 'پروژه‌ای با این نام نیست'
    designs = list(Design.objects.filter(project=p).select_related('page'))
    by = {(d.target): d for d in designs}
    if set(by) != {'page', 'header', 'footer'} or len(designs) != 3:
        return False, 'سندهای پروژه همان سه‌تای پیش‌نویس نیست'
    head = (by['header'].draft or {}).get('blocks') or [{}]
    if str((head[0].get('props') or {}).get('logo') or '').startswith('m:'):
        return False, 'همین حالا طرحِ آخر (با لوگو) را دارد'
    for d in designs:
        if d.rev != 1 or d.published or d.published_at or d.versions.exists():
            return False, 'مالک در «%s» چیزی را ذخیره یا منتشر کرده؛ دست نخورد' % d.target
    parts = build(DEFAULT_STYLE, logo=import_logo(p))
    for target in ('page', 'header', 'footer'):
        d = by[target]
        d.draft = parts[target]
        d.rev += 1                      # ویرایشگری که همین حالا باز است با ذخیره‌اش 409 می‌گیرد، نه این‌که روی طرحِ تازه بنویسد
        d.save(update_fields=['draft', 'rev', 'updated_at'])
    if p.site_title != BRAND['name'] and p.site_title.startswith(BRAND['name']):
        # نامِ پیش‌نویس («چغر — پیش‌نویسِ صفحهٔ فرود (بنتو)») نامِ سایت هم شده بود و کنارِ لوگو در سربرگ و پابرگ می‌آمد؛ نامِ سایت فقط «چغر» است
        p.site_title = BRAND['name']
        p.save(update_fields=['site_title'])
    return True, 'به‌روز شد'


__all__ = ['build', 'static_page', 'create_draft', 'refresh_draft', 'import_logo', 'theme', 'BRAND']
