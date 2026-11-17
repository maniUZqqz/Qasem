# -*- coding: utf-8 -*-
"""آنچه در «حالتِ AI» به مدل می‌رسد: سبکِ انتخاب‌شده (توکن‌ها) + چند قطعهٔ کم‌وبیش مرتبط به‌عنوان آجر — نه کلِ کتابخانه.

اصلِ مالک: «همه‌چیز را به AI نده، بدتر می‌شود.» پس:
  · حداکثر MAX_COMPONENTS قطعه (پیش‌فرض ۵) و از هر دسته حداکثر یکی؛ اولویت با قطعه‌هایی که کاربر خودش انتخاب کرده؛
  · هر قطعه فقط اسکلتِ HTMLِ کوتاه‌شده و نامِ کلاس‌ها؛ CSSِ قطعه را خودمان بعد از پاسخ به صفحه می‌چسبانیم، پس در پرامپت نمی‌آید؛
  · کلِ بسته (JSON) هرگز از MAX_CHARS بیشتر نمی‌شود؛ اگر شد، قطعه‌های کم‌اولویت و بعد HTMLِ بلند کوتاه می‌شوند.

خروجیِ AI (بدنهٔ HTML) بعد از پاسخ با `attach_css` وارسی می‌شود: هر قطعه‌ای که در آن به‌کار رفته باشد، CSSِ خودش به صفحه اضافه می‌شود.
"""
import json
import re

from . import c21_convert, c21_embed, components as comps, styles as styles_mod
from .styles.css import DEFAULTS, tokens_of

MAX_CHARS = 9000
MAX_COMPONENTS = 5
MAX_COMPONENT_HTML = 1100
MIN_COMPONENT_HTML = 360

# صفحه‌ای از این نوع معمولاً به چه دسته‌هایی نیاز دارد (به ترتیبِ اهمیت)
PAGE_PLANS = {
    'home': ['hero', 'features', 'testimonials', 'pricing', 'cta', 'faq', 'steps'],
    'landing': ['hero', 'features', 'testimonials', 'pricing', 'cta', 'faq', 'steps'],
    'static': ['hero', 'features', 'cta', 'faq'],
    'about': ['hero', 'features', 'cards', 'cta'],
    'contact': ['hero', 'faq', 'cta'],
    'product_list': ['hero', 'cards', 'cta'],
    'header': ['navbar'],
    'footer': ['footer'],
}
DEFAULT_PLAN = ['hero', 'features', 'testimonials', 'cta']

HOWTO_FA = ('از «components» فقط همان‌هایی را که لازم است بردار: HTMLِ نمونه را عیناً (با همان کلاس‌های nb-section و nbc-…) در بدنه بگذار و '
            'فقط متن‌ها، پیوندها و تعدادِ آیتم‌ها را عوض کن؛ CSSِ این قطعه‌ها را خودمان اضافه می‌کنیم، پس برایشان CSS ننویس. '
            'رنگ‌ها و قلم‌ها را از «style» بگیر و از متغیرهای var(--brand) و var(--ink) استفاده کن؛ رنگِ ثابت و قلمِ تازه نیاور. '
            'اگر قطعه‌ای به محتوا نمی‌خورد، کنارش بگذار؛ لازم نیست همه استفاده شوند.')


def _words(text):
    return {w for w in re.split(r'[^\w؀-ۿ]+', (text or '').lower()) if len(w) > 1}


def score(comp, brief_words, style_key):
    s = 0
    if style_key and style_key in comp['styles']:
        s += 3
    hay = _words(' '.join(comp['tags']) + ' ' + comp['label'] + ' ' + comp['desc'])
    s += 2 * len(hay & brief_words)
    return s


def pick_components(brief='', style_key='', kind='home', pinned=(), limit=MAX_COMPONENTS):
    """⇒ فهرستِ کلیدِ قطعه‌ها، حداکثر `limit` تا؛ همیشه کوچک و مرتبط."""
    chosen = []
    for k in pinned or ():
        if k in comps.COMPONENTS and k not in chosen:
            chosen.append(k)
    chosen = chosen[:limit]
    words = _words(brief)
    cats_taken = {comps.COMPONENTS[k]['cat'] for k in chosen}
    plan = PAGE_PLANS.get(kind) or DEFAULT_PLAN
    if kind not in ('header', 'footer'):                       # متن «قیمت» یا «پرسش» را صریح خواسته ⇒ همان بخش‌ها اول (نه همیشه hero/features/…)
        asked = [c for c in section_intents(brief) if c in comps.CAT_LABEL and c not in ('navbar', 'footer')]
        plan = asked + [c for c in plan if c not in asked]
    for cat in plan:
        if len(chosen) >= limit:
            break
        if cat in cats_taken:
            continue
        pool = [k for k in comps.ORDER if comps.COMPONENTS[k]['cat'] == cat]
        if not pool:
            continue
        best = max(pool, key=lambda k: (score(comps.COMPONENTS[k], words, style_key), -pool.index(k)))
        chosen.append(best)
        cats_taken.add(cat)
    return chosen[:limit]


def skeleton(key, limit=MAX_COMPONENT_HTML):
    """HTMLِ نمونهٔ یک قطعه با متن‌های پیش‌فرض، فشرده و بی‌شناسه."""
    from .clean import new_block
    from .render import Ctx, Renderer
    b = new_block(comps.block_type(key))
    r = Renderer(Ctx(canvas=False, target='header' if comps.COMPONENTS[key]['root'] == 'header' else 'footer' if comps.COMPONENTS[key]['root'] == 'footer' else 'page'))
    html = r.block(b)
    html = re.sub(r'\sb-[0-9a-f]{8}', '', html)
    html = re.sub(r'<svg\b.*?</svg>', '<svg/>', html, flags=re.S)
    html = re.sub(r'\s+', ' ', re.sub(r'>\s+<', '><', html)).strip()
    if len(html) > limit:
        html = html[:limit].rsplit('<', 1)[0] + '<!-- … -->'
    return html


def style_brief(key):
    st = styles_mod.STYLES[key]
    colors = st['theme']['colors']
    toks = tokens_of(key)
    changed = {k: v for k, v in toks.items() if DEFAULTS.get(k) != v and k in ('card_bd', 'card_sh', 'card_r', 'bf', 'hov', 'head_w', 'btn_sh', 'ic_r', 'sec_py', 'gap', 'hero_bg')}
    ref = styles_mod.uiux.reference_for(st)
    srow = ref.get('style') or {}
    frow = ref.get('font_pairing') or {}
    out = {'key': key, 'name': '%s (%s)' % (st['label'], st['en']), 'mood': st['mood'],
           'colors': colors, 'fonts': {'heading': st['theme']['font_head'], 'body': st['theme']['font_body']},
           'radius': st['theme']['radius'], 'button': st['theme']['button'],
           'tokens': {k: (v if len(str(v)) < 90 else str(v)[:87] + '…') for k, v in changed.items()},
           'sections': {k: v for k, v in (st.get('sections') or {}).items() if v}}
    if srow.get('effects'):
        out['effects'] = srow['effects'][:220]
    if srow.get('avoid'):
        out['avoid'] = srow['avoid'][:160]
    if frow.get('mood'):
        out['font_mood'] = frow['mood'][:120]
    if srow.get('checklist'):
        out['checklist'] = _cut(srow['checklist'], 200)
    if srow.get('rtl') and srow['rtl'] != 'full':
        out['rtl_level'] = srow['rtl']
    return out


def _size(payload):
    return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))


# ───────────────────────────── ردیف‌های مرتبط از کلِ دادهٔ ui-ux-pro-max (کوچک و محدود)

GUIDE_MAX_CHARS = 1500
GUIDE_FIELD = 150
GUIDE_HOWTO_FA = ('«guidance» فقط چند قاعدهٔ کمکیِ مرتبط است (رهنمودِ UX، الگوی صفحه، پالتِ پیشنهادی، نکتهٔ راست‌به‌چپ، یادداشتِ HTML)؛ اگر با محتوای کاربر در تضاد بود محتوا برنده است.')
KIND_UX_QUERY = {'home': 'hero navigation accessibility contrast mobile', 'landing': 'cta conversion accessibility contrast forms', 'static': 'readability typography accessibility',
                 'about': 'content readability trust accessibility', 'contact': 'forms validation accessibility touch', 'product_list': 'cards images responsive navigation',
                 'header': 'navigation touch responsive keyboard', 'footer': 'navigation accessibility links'}
CHART_WORDS = ('chart', 'graph', 'dashboard', 'analytics', 'نمودار', 'داشبورد', 'آمار', 'گزارش')


#: واژه‌های فارسیِ رایجِ «حوزهٔ کار» ⇒ معادلِ انگلیسی (دادهٔ ui-ux-pro-max انگلیسی است). ترتیبِ وقوع در متن مهم است: واژهٔ اولِ متن «سرِ» موضوع است
#: («فروشگاه لوازمِ ورزشی» ⇒ فروشگاه، نه باشگاه).
FA_EN = (('فروشگاه', 'e-commerce shop store'), ('خرید', 'e-commerce shop store'), ('ورزش', 'fitness sports gym'), ('باشگاه', 'fitness gym'), ('آموزش', 'education course learning'),
         ('دوره', 'education course'), ('رستوران', 'restaurant food'), ('کافه', 'cafe bakery'), ('پزشک', 'medical clinic'), ('کلینیک', 'medical clinic'),
         ('سلامت', 'health wellness'), ('املاک', 'real estate property'), ('موسیقی', 'music'), ('سفر', 'travel tourism'), ('گردشگری', 'travel tourism'),
         ('هتل', 'hotel hospitality'), ('حقوقی', 'legal'), ('وکیل', 'legal'), ('بانک', 'banking finance'), ('مالی', 'finance'), ('داشبورد', 'dashboard analytics'),
         ('نمودار', 'chart'), ('آمار', 'analytics'), ('کودک', 'kids education'), ('زیبایی', 'beauty spa'), ('آرایشگاه', 'beauty salon'), ('سالن', 'beauty salon'),
         ('خبر', 'news media'), ('بازی', 'gaming'), ('نمایشگاه', 'gallery museum'), ('گالری', 'gallery'), ('هوش مصنوعی', 'ai chatbot'), ('عروسی', 'wedding event'),
         ('نمونه کار', 'portfolio'), ('پرتفولیو', 'portfolio'), ('نرم افزار', 'saas software'), ('اپلیکیشن', 'mobile app'), ('استارتاپ', 'startup saas'),
         ('مشاور', 'consulting service'), ('خدمات', 'service'), ('مد', 'fashion'), ('لباس', 'fashion'), ('گل', 'florist plant'), ('دندان', 'dental'),
         ('حیوان', 'pet veterinary'), ('ساختمان', 'construction architecture'), ('معماری', 'architecture interior'), ('بیمه', 'insurance'), ('حمل', 'logistics delivery'),
         ('مجله', 'magazine blog'), ('وبلاگ', 'blog'), ('رمزارز', 'crypto'), ('خیریه', 'non-profit charity'), ('مدرسه', 'education school'), ('دانشگاه', 'education university'))

#: «بخشِ صفحه»ای که متن می‌خواهد (قیمت، پرسش، منو …) ⇒ دستهٔ قطعه‌های ما (PAGE_PLANS) + واژه‌های انگلیسی برای جست‌وجو. ترتیبِ وقوع در متن = ترتیبِ اولویت.
SECTION_INTENTS = (
    ('pricing', ('قیمت', 'تعرفه', 'پلن', 'پلان', 'اشتراک', 'بسته', 'هزینه', 'pricing', 'price', 'plans', 'subscription', 'tariff'), 'pricing plans comparison'),
    ('faq', ('پرسش', 'سوال', 'سؤال', 'faq', 'questions', 'accordion'), 'faq accordion questions'),
    ('testimonials', ('نظر', 'رضایت', 'مشتریان', 'بازخورد', 'testimonial', 'testimonials', 'reviews', 'feedback'), 'testimonials reviews social proof'),
    ('navbar', ('منو', 'ناوبری', 'ناوبر', 'هدر', 'سربرگ', 'navbar', 'navigation', 'menu', 'header'), 'navigation menu navbar'),
    ('footer', ('فوتر', 'پابرگ', 'پایین صفحه', 'footer'), 'footer'),
    ('hero', ('هیرو', 'صفحه اصلی', 'صفحه نخست', 'hero', 'banner'), 'hero'),
    ('features', ('ویژگی', 'امکانات', 'قابلیت', 'مزایا', 'مزیت', 'features', 'benefits'), 'features benefits'),
    ('steps', ('مراحل', 'نحوه', 'چگونه', 'چطور', 'روند', 'steps', 'process', 'timeline', 'how it works'), 'steps timeline process'),
    ('cta', ('ثبت نام', 'عضویت', 'خبرنامه', 'فراخوان', 'دعوت به اقدام', 'cta', 'sign up', 'signup', 'newsletter', 'call to action'), 'cta signup newsletter'),
    ('cards', ('کارت', 'محصولات', 'محصول', 'کالا', 'کاتالوگ', 'cards', 'products', 'catalog'), 'cards product'),
    ('gallery', ('گالری', 'نمونه کار', 'تصاویر', 'عکس', 'اسلایدر', 'gallery', 'portfolio', 'carousel', 'slider'), 'gallery portfolio carousel'),
    ('contact', ('تماس', 'ارتباط', 'contact'), 'contact form'),
    ('dashboard', ('داشبورد', 'نمودار', 'آمار', 'گزارش', 'پنل', 'dashboard', 'chart', 'analytics'), 'dashboard chart analytics'),
)
#: حوزه (معادلِ انگلیسیِ FA_EN) ⇒ بخش‌هایی که چنین صفحه‌ای معمولاً می‌خواهد؛ وقتی متن بخشی را صریح نخواسته، همین‌ها قطعه‌های پیشنهادی را از هم جدا می‌کند
DOMAIN_SECTIONS = {
    'e-commerce shop store': ('cards', 'gallery', 'cta'), 'fitness sports gym': ('pricing', 'testimonials', 'steps'), 'fitness gym': ('pricing', 'testimonials', 'steps'),
    'education course learning': ('features', 'steps', 'faq'), 'education course': ('features', 'steps', 'faq'), 'education school': ('features', 'faq', 'contact'),
    'education university': ('features', 'faq', 'contact'), 'restaurant food': ('gallery', 'cards', 'contact'), 'cafe bakery': ('gallery', 'cards', 'contact'),
    'medical clinic': ('testimonials', 'faq', 'contact'), 'dental': ('testimonials', 'faq', 'contact'), 'health wellness': ('features', 'testimonials', 'faq'),
    'real estate property': ('gallery', 'cards', 'contact'), 'travel tourism': ('gallery', 'cards', 'cta'), 'hotel hospitality': ('gallery', 'pricing', 'contact'),
    'legal': ('faq', 'testimonials', 'contact'), 'consulting service': ('features', 'faq', 'contact'), 'service': ('features', 'steps', 'contact'),
    'saas software': ('features', 'pricing', 'faq'), 'startup saas': ('features', 'pricing', 'cta'), 'ai chatbot': ('features', 'pricing', 'faq'), 'mobile app': ('features', 'gallery', 'cta'),
    'portfolio': ('gallery', 'features', 'contact'), 'gallery': ('gallery', 'cards'), 'gallery museum': ('gallery', 'cards'), 'music': ('gallery', 'cards', 'cta'),
    'beauty spa': ('gallery', 'pricing', 'testimonials'), 'beauty salon': ('gallery', 'pricing', 'testimonials'), 'fashion': ('cards', 'gallery', 'cta'),
    'banking finance': ('features', 'pricing', 'faq'), 'finance': ('features', 'pricing', 'faq'), 'insurance': ('features', 'pricing', 'faq'), 'dashboard analytics': ('dashboard',),
    'news media': ('cards', 'gallery'), 'magazine blog': ('cards', 'gallery'), 'blog': ('cards',), 'wedding event': ('gallery', 'steps', 'contact'),
    'kids education': ('features', 'gallery', 'contact'), 'non-profit charity': ('cta', 'steps', 'testimonials'), 'construction architecture': ('gallery', 'steps', 'contact'),
    'architecture interior': ('gallery', 'features', 'contact'), 'logistics delivery': ('steps', 'features', 'contact'), 'pet veterinary': ('features', 'testimonials', 'contact'),
}
#: دستهٔ «بخشِ صفحه» ⇒ دسته‌های کاتالوگِ 21st.dev که به آن می‌خورند
_C21_OF_INTENT = {'contact': ('form',), 'steps': ('landing-page', 'tabs'), 'dashboard': ('dashboard', 'chart', 'table', 'sidebar'), 'cards': ('card',)}


def _norm(text):
    """نرمال‌سازیِ فارسی برای تطبیق: ي/ك عربی، نیم‌فاصله ⇒ فاصله، فاصلهٔ اضافه."""
    t = (text or '').replace('ي', 'ی').replace('ك', 'ک').replace('‌', ' ').replace('\u200f', ' ').lower()
    return re.sub(r'\s+', ' ', t).strip()


def _find(text, kw):
    """موقعیتِ اولین وقوعِ واژه «در آغازِ یک توکن» (نه وسطِ کلمه: «گل» در «تاگل» نیست)؛ واژهٔ کوتاه (≤ ۳ حرف) فقط کاملِ توکن (با ی/ها). نیافت ⇒ -1."""
    kw = _norm(kw)
    if not kw:
        return -1
    suffix = r'(?:ی|ها|های|ای)?(?![\w؀-ۿ])' if len(kw) <= 3 else ''
    m = re.search(r'(?<![\w؀-ۿ])' + re.escape(kw) + suffix, text)
    return m.start() if m else -1


def domain_matches(brief):
    """⇒ [(موقعیت، واژه، معادلِ انگلیسی)] مرتب بر اساسِ وقوع در متن (بی‌تکرارِ معادل)."""
    text = _norm(brief)
    seen, out = set(), []
    for fa, en in FA_EN:
        pos = _find(text, fa)
        if pos >= 0 and en not in seen:
            seen.add(en)
            out.append((pos, fa, en))
    return sorted(out)


def section_intents(brief, implied=True):
    """⇒ فهرستِ دستهٔ بخش‌های صفحه که متن خواسته، به ترتیبِ وقوع (['pricing', 'faq', …]). implied: بخش‌هایی که حوزهٔ کار معمولاً می‌خواهد (DOMAIN_SECTIONS) پشتِ سرِ صریح‌ها."""
    text = _norm(brief)
    found = []
    for cat, words, _en in SECTION_INTENTS:
        pos = min((p for p in (_find(text, w) for w in words) if p >= 0), default=-1)
        if pos >= 0:
            found.append((pos, cat))
    out = [c for _p, c in sorted(found)]
    if implied:
        for _p, _fa, en in domain_matches(brief)[:2]:
            for it in DOMAIN_SECTIONS.get(en, ()):
                if it not in out:
                    out.append(it)
    return out


def en_words(brief):
    """متنِ فارسی ⇒ همان متن + معادل‌های انگلیسیِ «حوزه» و «بخش‌های صفحه» (برای جست‌وجو در دادهٔ انگلیسی)."""
    extra = ' '.join(en for _p, _fa, en in domain_matches(brief))
    sec = {c: en for c, _w, en in SECTION_INTENTS}
    extra += ' ' + ' '.join(sec[c] for c in section_intents(brief))
    return ((brief or '') + ' ' + extra).strip()


def product_query(brief):
    """جست‌وجوی «نوعِ محصول»: واژهٔ حوزهٔ اولِ متن سر است («فروشگاه ورزشی» ⇒ فروشگاه)؛ بقیه فقط برای رتبه‌بندیِ بینِ هم‌رده‌ها. ⇒ (سر، بقیه) انگلیسی."""
    dm = domain_matches(brief)
    if not dm:
        return '', ''
    head = dm[0][2]
    rest = ' '.join(en for _p, _fa, en in dm[1:])
    return head, rest


def _cut(text, n=GUIDE_FIELD):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + '…'


def _product_rows(uiux, orig_brief, brief_en):
    """ردیفِ «نوعِ محصول» (۰ یا ۱ ردیف). واژهٔ حوزهٔ اولِ متن سر است («فروشگاه ورزشی» ⇒ E-commerce، نه Fitness)؛ بقیهٔ واژه‌ها فقط بینِ هم‌رده‌ها رتبه می‌دهند.
    متنِ فارسیِ فقط-بخش («صفحهٔ قیمت‌گذاری»، «پرسش‌های پرتکرار») نوعِ محصول ندارد ⇒ هیچ (ردیفِ بی‌ربط و پالتِ بی‌ربط به مدل نمی‌رسید)."""
    head, rest = product_query(orig_brief)
    if head:
        cands = uiux.search('products', head, limit=6)
        words = uiux._words(rest)
        if cands and words:
            fields = uiux.SEARCH_FIELDS['products']
            best = max(range(len(cands)), key=lambda i: (uiux._score(cands[i], words, fields), -i))
            return [cands[best]]
        return cands[:1]
    if section_intents(orig_brief, implied=False) and not re.search(r'[A-Za-z]{3}', orig_brief or ''):
        return []
    return uiux.search('products', brief_en, limit=1) if brief_en else []


def uiux_hints(brief='', kind='home', style_key='', max_chars=GUIDE_MAX_CHARS):
    """⇒ {'ux': […], 'pattern': {…}, 'product': {…}, 'chart': {…}, 'rtl': {…}} با «فقط ردیف‌های مرتبط» از کلِ دادهٔ ui-ux-pro-max؛ کوچک و محدود (≤ max_chars).
    نه کلِ هزاران ردیف: چند رهنمودِ UX، یک الگوی صفحه، یک ردیفِ محصول/استدلال، (اگر درخواست داده/نمودار است) یک نمودار و یک نکتهٔ راست‌به‌چپ."""
    uiux = styles_mod.uiux
    orig_brief = brief or ''
    brief = en_words(brief)
    out = {}
    ux = []
    seen = set()
    for r in uiux.search('ux', brief or '', limit=3) + uiux.search('ux', KIND_UX_QUERY.get(kind, 'accessibility contrast'), limit=6):
        key = r.get('issue')
        if key in seen or r.get('platform') in ('Mobile', 'VisionOS'):
            continue
        seen.add(key)
        ux.append({'rule': _cut(r.get('issue'), 70), 'do': _cut(r.get('do'), 110), 'dont': _cut(r.get('dont'), 90), 'severity': r.get('severity', '')})
        if len(ux) >= 4:
            break
    if ux:
        out['ux'] = ux
    pat = (uiux.search('landing', brief, limit=1) if brief else []) or uiux.search('landing', 'hero features cta', limit=1)
    if pat:
        p = pat[0]
        out['pattern'] = {'name': _cut(p.get('name'), 60), 'sections': _cut(p.get('sections'), 170), 'cta': _cut(p.get('cta'), 60), 'colors': _cut(p.get('color_strategy'), 110)}
    prod = _product_rows(uiux, orig_brief, brief)
    if prod:
        p = prod[0]
        out['product'] = {'type': _cut(p.get('product'), 50), 'style': _cut(p.get('primary_style'), 70), 'landing': _cut(p.get('landing'), 60), 'notes': _cut(p.get('notes'), 120)}
        rs = uiux.search('reasoning', p.get('product', ''), limit=1)
        if rs:
            out['product']['avoid'] = _cut(rs[0].get('anti'), 100)
        pal = uiux.by_id('colors', 'product', p.get('product', ''))
        if pal:                                                   # پالتِ پیشنهادیِ همین نوعِ محصول (فقط رنگ‌ها؛ برند اگر رنگ دارد برنده است)
            out['palette'] = {k: pal[k] for k in ('primary', 'accent', 'background', 'foreground', 'muted', 'border') if pal.get(k)}
    if any(w in (brief or '').lower() for w in CHART_WORDS):
        ch = uiux.search('charts', brief, limit=1) or uiux.search('charts', 'trend comparison', limit=1)
        if ch:
            c = ch[0]
            out['chart'] = {'data': _cut(c.get('data_type'), 50), 'use': _cut(c.get('best'), 60), 'not_when': _cut(c.get('when_not'), 90), 'a11y': _cut(c.get('a11y_fallback'), 90)}
    # یادداشتِ پشتهٔ html-tailwind (HTMLِ معنادار، دسترس‌پذیری، تصویر، فرم، واکنش‌گرایی): ۲ ردیفِ مهم، نزدیک به درخواست
    cands = [r for r in uiux.search('stacks', brief, limit=40, where={'stack': 'html-tailwind'}) + uiux.search('stacks', 'accessibility semantic images forms responsive', limit=40, where={'stack': 'html-tailwind'})
             if r.get('category') in ('Accessibility', 'Images', 'Forms', 'Responsive', 'Layout', 'Buttons') and r.get('severity') in ('High', 'Critical', 'Medium')]
    cands.sort(key=lambda r: (0 if r.get('category') == 'Accessibility' else 1, {'Critical': 0, 'High': 1}.get(r.get('severity'), 2)))
    if cands:
        out['stack'] = [{'rule': _cut(r.get('guideline'), 70), 'do': _cut(r.get('do'), 100)} for r in cands[:2]]
    rtl = uiux.search('ux', 'rtl right-to-left bidirectional mirror', limit=1)
    blob = json.dumps(rtl[0], ensure_ascii=False).lower() if rtl else ''
    if rtl and ('rtl' in blob or 'right-to-left' in blob):
        out['rtl'] = {'rule': _cut(rtl[0].get('issue'), 70), 'do': _cut(rtl[0].get('do'), 110)}
    while _size(out) > max_chars and out:                 # سقفِ سخت: از آخر کوتاه می‌شود
        if len(out.get('ux', [])) > 1:
            out['ux'].pop()
        else:
            for k in ('chart', 'stack', 'palette', 'rtl', 'product', 'ux', 'pattern'):
                if k in out:
                    out.pop(k)
                    break
    return out


# ───────────────────────────── قطعه‌های تبدیل‌شدهٔ 21st.dev (فقط چند تای مرتبط؛ نه کلِ کتابخانه)

MAX_C21 = 2
MIN_C21_HTML = 300
C21_HOWTO_FA = ('«c21» HTMLِ آمادهٔ چند قطعهٔ تبدیل‌شده از 21st.dev است (مجوزِ آزاد): اگر به صفحه می‌خورد عیناً با همان کلاسِ nbc21-… در بدنه بگذار و فقط متن‌ها را عوض کن؛ '
                'CSSِ آن را خودمان اضافه می‌کنیم. اگر نمی‌خورد کنارش بگذار.')
_CAT_OF_PLAN = {'hero': ('hero',), 'features': ('features', 'tabs'), 'testimonials': ('testimonials', 'marquee', 'avatar'), 'pricing': ('pricing-section',), 'cta': ('cta', 'button'),
                'faq': ('accordion',), 'steps': ('landing-page',), 'cards': ('card',), 'gallery': ('marquee', 'carousel'), 'navbar': ('navigation',), 'footer': ('footer',)}


def _c21_hay(e, row):
    """متنِ جست‌وجوی یک قطعهٔ تبدیل‌شده: عنوان + دسته + کتابخانه + برچسب‌ها و توضیحِ انگلیسیِ کاتالوگ."""
    parts = [e.get('title', ''), ' '.join(e.get('cats', [])), e.get('library', '')]
    if row:
        parts += [' '.join(row.get('tags', []) or []), row.get('description', '')]
    return _words(' '.join(parts))


def c21_suggest(brief='', kind='home', pinned=(), limit=MAX_C21):
    """⇒ حداکثر `limit` قطعهٔ تبدیل‌شده (سنجاق‌شده‌ها اول؛ بعد «بخشی که متن خواسته» (قیمت ⇒ جدولِ قیمت، پرسش ⇒ FAQ …) و امتیازِ کلمه‌های مشترک
    با عنوان/برچسب/توضیح + جورِ بودنِ دسته با نوعِ صفحه)؛ هر کدام {id, class, cat, title, html}. قطعه‌ای که به‌صورتِ ایستا خالی دیده می‌شود (rtl=fail) هرگز نمی‌آید."""
    from . import c21st
    idx = c21_convert.load_index()
    if not idx:
        return []
    chosen = [i for i in dict.fromkeys(pinned or ()) if i in idx and idx[i].get('rtl') != 'fail'][:limit]
    if len(chosen) < limit:
        words = _words(en_words(brief))
        asked = section_intents(brief)
        asked_cats = []                                   # به ترتیبِ وقوعِ بخش در متن: [(intent, {دسته‌های 21st})]
        for it in asked:
            asked_cats.append((it, set(_CAT_OF_PLAN.get(it, ())) | set(_C21_OF_INTENT.get(it, ()))))
        want = set()
        for cat in PAGE_PLANS.get(kind) or DEFAULT_PLAN:
            want.update(_CAT_OF_PLAN.get(cat, ()))
        rows = {r['id']: r for r in c21st.load() if r['id'] in idx}
        scored = []
        for cid, e in idx.items():
            if cid in chosen or e.get('rtl') == 'fail':
                continue
            ecats = set(e.get('cats', []))
            hay = _c21_hay(e, rows.get(cid))
            ask_hit = sum(1 for _it, cs in asked_cats if cs & ecats)
            s = 2 * len(words & hay) + 2 * len(want & ecats) + 8 * ask_hit
            if s:
                scored.append((s, ask_hit, e.get('bytes', 0), cid))
        scored.sort(key=lambda x: (-x[0], x[2], x[3]))             # امتیاز بالا، بعد کوچک‌تر (کم‌هزینه برای پرامپت)
        # هر بخشِ خواسته‌شده یک نمایندهٔ خودش را می‌گیرد (قیمت و پرسش با هم خواسته شدند ⇒ هر دو)
        for it, cs in asked_cats:
            if len(chosen) >= limit:
                break
            best = next((cid for _s, _h, _b, cid in scored if cid not in chosen and cs & set(idx[cid].get('cats', []))), None)
            if best:
                chosen.append(best)
        chosen += [cid for _s, _h, _b, cid in scored if cid not in chosen][:limit - len(chosen)]
    out = []
    for cid in chosen:
        e = idx[cid]
        html = c21_embed.skeleton(e['key'])
        if html:
            out.append({'id': cid, 'class': c21_convert.scope_for(e['key']), 'title': e.get('title', '')[:70], 'license': e.get('license', ''), 'cat': (e.get('cats') or [''])[0], 'html': html})
    return out



INSPIRATION_HOWTO_FA = ('«inspiration» فقط الهام است (قطعه‌هایی از کاتالوگِ 21st.dev با مجوزِ خودشان): ساختار و حسِ آن‌ها را بگیر ولی با HTML و CSSِ ساده و '
                        'کلاس‌های خودمان بنویس؛ React، Tailwind و کتابخانهٔ بیرونی وارد نکن و کدِ آن‌ها را کپی نکن.')


def build(style_key='', brief='', kind='home', pinned=(), limit=MAX_COMPONENTS, max_chars=MAX_CHARS, refs21=()):
    """⇒ {'style': …, 'components': […], 'howto': …, 'inspiration'?: […]} کوچک و محدود؛ style_key خالی = بدونِ سبک (فقط قطعه‌ها).
    refs21 = شناسهٔ قطعه‌های کاتالوگِ 21st.dev (حداکثر ۳، فقط الهام؛ برشِ کدِ کوتاه فقط برای مجوزِ آزاد و کدِ گرفته‌شده)."""
    payload = {'howto': HOWTO_FA}
    if style_key in styles_mod.STYLES:
        payload['style'] = style_brief(style_key)
    keys = pick_components(brief, style_key if style_key in styles_mod.STYLES else '', kind, pinned, limit)
    rows = []
    for k in keys:
        c = comps.COMPONENTS[k]
        rows.append({'key': k, 'class': comps.class_of(k), 'cat': c['cat'], 'purpose': '%s — %s' % (c['label'], c['desc']), 'html': skeleton(k)})
    payload['components'] = rows
    guide = uiux_hints(brief, kind, style_key if style_key in styles_mod.STYLES else '')
    if guide:
        payload['guidance'] = guide
        payload['howto'] += ' ' + GUIDE_HOWTO_FA
    idx21 = c21_convert.load_index()
    conv_refs = [i for i in dict.fromkeys(refs21 or ()) if i in idx21]
    c21rows = c21_suggest(brief, kind, conv_refs)
    if c21rows:
        payload['c21'] = c21rows
        payload['howto'] += ' ' + C21_HOWTO_FA
    insp = []
    refs21 = [i for i in (refs21 or ()) if i not in conv_refs]
    if refs21:
        from . import c21st
        insp = c21st.inspiration_for(refs21)
        if insp:
            payload['inspiration'] = insp
            payload['howto'] = payload['howto'] + ' ' + INSPIRATION_HOWTO_FA
    payload['stats'] = {'components': len(rows), 'chars': 0, 'limit': max_chars, 'inspiration': len(insp), 'guidance': len(guide or {}), 'c21': len(c21rows)}
    # سقفِ سخت (با خودِ stats): اول برشِ کدِ الهام‌ها، بعد HTMLها را کوتاه کن، بعد الهام‌ها و قطعه‌های آخر را بینداز
    guard = 0
    trimmed = set()
    while _size(payload) > max_chars and guard < 90:
        guard += 1
        if payload.get('guidance'):                       # اول رهنمودها کوتاه می‌شوند (کم‌اهمیت‌تر از قطعه‌ها)
            g = payload['guidance']
            if len(g.get('ux', [])) > 1:
                g['ux'].pop()
            else:
                for k in ('chart', 'stack', 'palette', 'rtl', 'product', 'ux', 'pattern'):
                    if k in g:
                        g.pop(k)
                        break
            if not g:
                payload.pop('guidance')
            continue
        if payload.get('c21'):                            # بعد قطعه‌های 21st: اول کوتاه، بعد از آخر حذف
            big = max((x for x in payload['c21'] if len(x['html']) > MIN_C21_HTML and id(x) not in trimmed), key=lambda x: len(x['html']), default=None)
            if big is not None:
                big['html'] = big['html'][:max(MIN_C21_HTML, int(len(big['html']) * 0.7))].rsplit('<', 1)[0] + '<!-- … -->'
                trimmed.add(id(big))
            else:
                payload['c21'].pop()
                if not payload['c21']:
                    payload.pop('c21')
                    payload['howto'] = payload['howto'].replace(' ' + C21_HOWTO_FA, '')
            continue
        longest_ex = max((x for x in insp if x.get('code_excerpt')), key=lambda x: len(x['code_excerpt']), default=None)
        if longest_ex is not None:
            if len(longest_ex['code_excerpt']) > 200:
                longest_ex['code_excerpt'] = longest_ex['code_excerpt'][:int(len(longest_ex['code_excerpt']) * 0.6)]
            else:
                longest_ex.pop('code_excerpt')
            continue
        longest = max((x for x in rows if id(x) not in trimmed), key=lambda x: len(x['html']), default=None)
        if longest and len(longest['html']) > MIN_COMPONENT_HTML:
            cut = max(MIN_COMPONENT_HTML, int(len(longest['html']) * 0.75))
            longest['html'] = longest['html'][:cut].rsplit('<', 1)[0] + '<!-- … -->'
            trimmed.add(id(longest))                     # هر قطعه یک بار کوتاه می‌شود (وگرنه با نشانِ «…» دوباره بلندتر از کف می‌شد و حلقه هرگز به حذفِ قطعه نمی‌رسید)
        elif insp:                                       # الهام اختیاری است؛ پیش از قطعه‌های اصلی کنار می‌رود
            insp.pop()
            if not insp:
                payload.pop('inspiration', None)
                payload['howto'] = payload['howto'].replace(' ' + INSPIRATION_HOWTO_FA, '')
        elif len(rows) > 1:
            rows.pop()
        else:
            break
    payload['stats']['components'] = len(rows)
    payload['stats']['inspiration'] = len(insp)
    for _ in range(3):                                   # عددِ chars خودش در اندازه حساب می‌شود؛ تا ثابت شدن
        payload['stats']['chars'] = _size(payload)
    return payload


def attach_css(html, css=''):
    """بعد از پاسخِ AI: CSSِ قطعه‌هایی که در بدنه به‌کار رفته‌اند را به CSSِ صفحه می‌چسباند (یک بار)."""
    css = css or ''
    keys = comps.used_in_html(html)
    if keys:
        block = comps.css_for(keys)
        if block and block not in css:
            css = (css.rstrip() + '\n\n' + block).strip() + '\n'
    k21 = c21_embed.used_in_html(html)
    if k21:
        block = c21_embed.css_for(k21)
        if block and block not in css:
            css = (css.rstrip() + '\n\n' + block).strip() + '\n'
    return css


def styled_base(base_css, style_key):
    """CSSِ پایهٔ یک پروژهٔ AI + پالتِ سبک (متغیرهای رنگ) + متغیرهای --st-*؛ AI بعد از این فقط روتوش می‌کند."""
    if style_key not in styles_mod.STYLES:
        return base_css
    from . import theme as theme_mod
    th = styles_mod.apply_to_theme(theme_mod.default_theme(), style_key)
    return '%s\n/* سبکِ طراحی: %s */\n%s\n' % (theme_mod.apply_zone(base_css, th).rstrip(), style_key, styles_mod.css.root_vars(style_key))


def options_json():
    """فهرستِ سبک‌ها و قطعه‌ها برای انتخابگرِ «حالتِ AI» (فقط نام و دسته؛ کوچک)."""
    return {'styles': [{'key': k, 'label': st['label'], 'en': st['en'], 'mood': st['mood'], 'group': st.get('group', 'عمومی'), 'source': st.get('source', 'hand'),
                        'colors': {x: st['theme']['colors'][x] for x in ('primary', 'bg', 'text')}} for k in styles_mod.ORDER for st in [styles_mod.STYLES[k]]],
            'components': [{'key': k, 'label': comps.COMPONENTS[k]['label'], 'cat': comps.COMPONENTS[k]['cat'], 'cat_label': comps.CAT_LABEL[comps.COMPONENTS[k]['cat']]}
                           for k in comps.ORDER if comps.COMPONENTS[k]['root'] == 'section'],
            'max_components': MAX_COMPONENTS}


def style_layer_css(style_key):
    """CSSِ سبک برای صفحه‌های AI (فقط متغیرهای --st-* و قاعده‌های nb-*؛ همان که پوسته می‌نویسد)."""
    return styles_mod.style_css(style_key) if style_key in styles_mod.STYLES else ''


__all__ = ['build', 'pick_components', 'attach_css', 'options_json', 'styled_base', 'style_layer_css', 'skeleton', 'style_brief', 'MAX_CHARS', 'MAX_COMPONENTS', 'HOWTO_FA']
