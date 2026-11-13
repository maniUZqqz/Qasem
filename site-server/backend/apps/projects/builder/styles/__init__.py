# -*- coding: utf-8 -*-
"""سبک‌های طراحیِ سایت‌ساز: توکن‌ها، لایهٔ CSS، اعمال روی پوسته و صفحه، و دادهٔ مرجعِ ui-ux-pro-max.

نقطهٔ ورود برای بقیهٔ کد:
    STYLES / get(key)            تعریفِ یک سبک
    style_css(key)               لایهٔ CSS برای blocks.css (فقط وقتی پوسته سبک دارد)
    apply_to_theme(theme, key)   پوستهٔ تازه با رنگ‌ها و قلم‌ها و گردیِ سبک
    apply_to_doc(doc, key)       چیدمانِ بخش‌های سبک روی بلوک‌های یک صفحه (فقط variant؛ متن دست نمی‌خورد)
    public_json()                آنچه پنل لازم دارد
"""
import copy

from .. import variants
from .css import style_css, tokens_of
from .data import ORDER, STYLES
from . import uiux


def get(key):
    return STYLES.get(key)


def apply_to_theme(theme, key, keep_brand=False):
    """⇒ پوستهٔ تازه. keep_brand: رنگِ اصلی و رنگِ روی آن را نگه دار (برای برندی که رنگِ ثابت دارد)."""
    st = STYLES[key]
    out = copy.deepcopy(theme or {})
    colors = dict((out.get('colors') or {}))
    new = dict(st['theme']['colors'])
    if keep_brand and colors.get('primary'):
        new['primary'], new['on_primary'] = colors['primary'], colors.get('on_primary') or new['on_primary']
    colors.update(new)
    out['colors'] = colors
    if keep_brand and colors.get('primary'):
        out['style_keep'] = True            # رنگِ اصلیِ برند در CSSِ سبک هم جای رنگِ اصلیِ خودِ سبک می‌نشیند
    else:
        out.pop('style_keep', None)
    for k in ('font_head', 'font_body', 'button', 'radius', 'width'):
        out[k] = st['theme'][k]
    out['style'] = key
    return out


def apply_to_doc(doc, key, only=None):
    """⇒ سندِ تازه که بلوک‌های آماده‌اش چیدمانِ سبک را گرفته‌اند. variant ِ خالی = چیدمانِ پیش‌فرض (کلید پاک می‌شود)."""
    st = STYLES[key]
    out = copy.deepcopy(doc or {'v': 1, 'blocks': []})
    sections = st.get('sections') or {}

    def walk(blocks):
        for b in blocks or []:
            btype = b.get('type')
            if btype in sections and (only is None or btype in only) and variants.has_field(btype):
                want = sections[btype]
                if want and variants.has(btype, want):
                    b.setdefault('props', {})['variant'] = want
                else:
                    (b.setdefault('props', {})).pop('variant', None)
            walk(b.get('children'))
    walk(out.get('blocks'))
    return out


def clear_doc(doc):
    """⇒ سندِ تازه بدونِ هیچ «چیدمانِ بخش» (همه به پیش‌فرض برمی‌گردند)."""
    out = copy.deepcopy(doc or {'v': 1, 'blocks': []})

    def walk(blocks):
        for b in blocks or []:
            (b.get('props') or {}).pop('variant', None)
            walk(b.get('children'))
    walk(out.get('blocks'))
    return out


def public_json():
    """فهرستِ سبک‌ها برای پنل: نام، توضیح، پالت، قلم‌ها، توکن‌های قابلِ نمایش و چیدمانِ پیش‌فرضِ بخش‌ها."""
    rows = []
    for key in ORDER:
        st = STYLES[key]
        rows.append({'key': key, 'label': st['label'], 'en': st['en'], 'mood': st['mood'], 'desc': st['desc'], 'tags': st['tags'],
                     'theme': st['theme'], 'sections': st.get('sections') or {}, 'tokens': tokens_of(key),
                     'uiux': st.get('uiux') or {}})
    return rows


def find_by_text(text, limit=3):
    """نزدیک‌ترین سبک‌ها به یک متنِ فارسی/انگلیسی (برای پیشنهادِ خودکار)."""
    words = uiux._words(text)
    scored = []
    for key in ORDER:
        st = STYLES[key]
        hay = ' '.join([st['label'], st['en'], st['mood'], st['desc'], ' '.join(st['tags'])]).lower()
        s = sum(2 if w in ' '.join(st['tags']).lower() else 1 for w in words if w in hay)
        if s:
            scored.append((s, key))
    scored.sort(key=lambda x: (-x[0], ORDER.index(x[1])))
    return [k for _s, k in scored[:limit]]


__all__ = ['STYLES', 'ORDER', 'get', 'style_css', 'tokens_of', 'apply_to_theme', 'apply_to_doc', 'clear_doc', 'public_json', 'find_by_text', 'uiux']
