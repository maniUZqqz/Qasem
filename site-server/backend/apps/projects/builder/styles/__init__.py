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
import re

from .. import variants
from .css import style_css, tokens_of
from .data import ORDER, STYLES
from . import uiux


def get(key):
    return STYLES.get(key)


SNAP_KEYS = ('font_head', 'font_body', 'button', 'radius', 'width')


def snapshot(theme):
    """رنگ‌ها، قلم‌ها، شکلِ دکمه و گردیِ یک پوسته؛ آنچه سبک عوض می‌کند. پیش از اولین سبک گرفته می‌شود تا برگشتن ممکن باشد."""
    theme = theme or {}
    snap = {'colors': dict(theme.get('colors') or {})}
    for k in SNAP_KEYS:
        if k in theme:
            snap[k] = theme[k]
    return snap


def _on_color(hex_color):
    """رنگِ خوانا روی یک رنگِ زمینه (سفید یا تقریباً مشکی)."""
    h = (hex_color or '').lstrip('#')
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return '#ffffff'
    return '#111827' if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else '#ffffff'


def brand_of(theme, project_brand=None):
    """رنگِ اصلیِ واقعیِ برند: رنگی که پوسته پیش از اولین سبک داشت. اگر آن عکس نیست (سبک از قبل نشسته بود، پیش از این اصلاح)،
    رنگِ برندِ ثبت‌شدهٔ پروژه؛ و اگر سبکی در کار نیست همان رنگِ اصلیِ فعلی. (بازبینیِ ۱۱/۱۳: «رنگِ اصلیِ برندم همان بماند»
    قبلاً رنگِ اصلیِ سبکِ پیشین را نگه می‌داشت.)  ⇒ (primary, on_primary) یا (None, None)"""
    theme = theme or {}
    prev = theme.get('style_prev') if theme.get('style') else None
    if isinstance(prev, dict) and (prev.get('colors') or {}).get('primary'):
        pc = prev['colors']
        return pc['primary'], pc.get('on_primary') or _on_color(pc['primary'])
    cur = theme.get('colors') or {}
    if theme.get('style') and project_brand and re.fullmatch(r'#[0-9a-fA-F]{6}', project_brand):
        return project_brand.lower(), _on_color(project_brand)
    return cur.get('primary'), cur.get('on_primary')


def apply_to_theme(theme, key, keep_brand=False, project_brand=None):
    """⇒ پوستهٔ تازه. keep_brand: رنگِ اصلیِ *برند* و رنگِ روی آن را نگه دار (نه رنگِ اصلیِ سبکی که پیش‌تر نشسته).
    پیش از اولین سبک، پوستهٔ فعلی در style_prev ذخیره می‌شود تا «برگرداندنِ پوسته به پیش از سبک» ممکن باشد."""
    st = STYLES[key]
    out = copy.deepcopy(theme or {})
    brand_primary, brand_on = brand_of(out, project_brand) if keep_brand else (None, None)
    if not out.get('style'):
        out['style_prev'] = snapshot(out)           # اولین سبک: حالتِ اصلی را نگه دار؛ سبکِ بعدی روی آن نمی‌نویسد
    colors = dict((out.get('colors') or {}))
    new = dict(st['theme']['colors'])
    if keep_brand and brand_primary:
        new['primary'], new['on_primary'] = brand_primary, brand_on or _on_color(brand_primary)
    colors.update(new)
    out['colors'] = colors
    if keep_brand and brand_primary:
        out['style_keep'] = True            # رنگِ اصلیِ برند در CSSِ سبک هم جای رنگِ اصلیِ خودِ سبک می‌نشیند
    else:
        out.pop('style_keep', None)
    for k in SNAP_KEYS:
        out[k] = st['theme'][k]
    out['style'] = key
    return out


def restore_theme(theme):
    """⇒ پوسته با رنگ‌ها و قلم‌های پیش از سبک و بدونِ هیچ سبکی؛ اگر عکسی نیست None."""
    prev = (theme or {}).get('style_prev')
    if not (theme or {}).get('style') or not isinstance(prev, dict) or not prev.get('colors'):
        return None
    out = copy.deepcopy(theme)
    for k in ('style', 'style_keep', 'style_prev'):
        out.pop(k, None)
    colors = dict(out.get('colors') or {})
    colors.update(prev['colors'])
    out['colors'] = colors
    for k in SNAP_KEYS:
        if k in prev:
            out[k] = prev[k]
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


__all__ = ['STYLES', 'ORDER', 'get', 'style_css', 'tokens_of', 'apply_to_theme', 'restore_theme', 'brand_of', 'snapshot', 'apply_to_doc', 'clear_doc', 'public_json', 'find_by_text', 'uiux']
