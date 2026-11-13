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

from . import components as comps, styles as styles_mod
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
    return out


def _size(payload):
    return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))


def build(style_key='', brief='', kind='home', pinned=(), limit=MAX_COMPONENTS, max_chars=MAX_CHARS):
    """⇒ {'style': …, 'components': […], 'howto': …} کوچک و محدود؛ style_key خالی = بدونِ سبک (فقط قطعه‌ها)."""
    payload = {'howto': HOWTO_FA}
    if style_key in styles_mod.STYLES:
        payload['style'] = style_brief(style_key)
    keys = pick_components(brief, style_key if style_key in styles_mod.STYLES else '', kind, pinned, limit)
    rows = []
    for k in keys:
        c = comps.COMPONENTS[k]
        rows.append({'key': k, 'class': comps.class_of(k), 'cat': c['cat'], 'purpose': '%s — %s' % (c['label'], c['desc']), 'html': skeleton(k)})
    payload['components'] = rows
    payload['stats'] = {'components': len(rows), 'chars': 0, 'limit': max_chars}
    # سقفِ سخت (با خودِ stats): اول HTMLها را کوتاه کن، بعد قطعه‌های آخر را بینداز
    guard = 0
    while _size(payload) > max_chars and guard < 40:
        guard += 1
        longest = max(rows, key=lambda x: len(x['html']), default=None)
        if longest and len(longest['html']) > MIN_COMPONENT_HTML:
            cut = max(MIN_COMPONENT_HTML, int(len(longest['html']) * 0.75))
            longest['html'] = longest['html'][:cut].rsplit('<', 1)[0] + '<!-- … -->'
        elif len(rows) > 1:
            rows.pop()
        else:
            break
    payload['stats']['components'] = len(rows)
    for _ in range(3):                                   # عددِ chars خودش در اندازه حساب می‌شود؛ تا ثابت شدن
        payload['stats']['chars'] = _size(payload)
    return payload


def attach_css(html, css=''):
    """بعد از پاسخِ AI: CSSِ قطعه‌هایی که در بدنه به‌کار رفته‌اند را به CSSِ صفحه می‌چسباند (یک بار)."""
    keys = comps.used_in_html(html)
    if not keys:
        return css or ''
    block = comps.css_for(keys)
    if block and block not in (css or ''):
        return ((css or '').rstrip() + '\n\n' + block).strip() + '\n'
    return css or ''


def styled_base(base_css, style_key):
    """CSSِ پایهٔ یک پروژهٔ AI + پالتِ سبک (متغیرهای رنگ) + متغیرهای --st-*؛ AI بعد از این فقط روتوش می‌کند."""
    if style_key not in styles_mod.STYLES:
        return base_css
    from . import theme as theme_mod
    th = styles_mod.apply_to_theme(theme_mod.default_theme(), style_key)
    return '%s\n/* سبکِ طراحی: %s */\n%s\n' % (theme_mod.apply_zone(base_css, th).rstrip(), style_key, styles_mod.css.root_vars(style_key))


def options_json():
    """فهرستِ سبک‌ها و قطعه‌ها برای انتخابگرِ «حالتِ AI» (فقط نام و دسته؛ کوچک)."""
    return {'styles': [{'key': k, 'label': st['label'], 'en': st['en'], 'mood': st['mood'],
                        'colors': {x: st['theme']['colors'][x] for x in ('primary', 'bg', 'text')}} for k, st in styles_mod.STYLES.items()],
            'components': [{'key': k, 'label': comps.COMPONENTS[k]['label'], 'cat': comps.COMPONENTS[k]['cat'], 'cat_label': comps.CAT_LABEL[comps.COMPONENTS[k]['cat']]}
                           for k in comps.ORDER if comps.COMPONENTS[k]['root'] == 'section'],
            'max_components': MAX_COMPONENTS}


def style_layer_css(style_key):
    """CSSِ سبک برای صفحه‌های AI (فقط متغیرهای --st-* و قاعده‌های nb-*؛ همان که پوسته می‌نویسد)."""
    return styles_mod.style_css(style_key) if style_key in styles_mod.STYLES else ''


__all__ = ['build', 'pick_components', 'attach_css', 'options_json', 'styled_base', 'style_layer_css', 'skeleton', 'style_brief', 'MAX_CHARS', 'MAX_COMPONENTS', 'HOWTO_FA']
