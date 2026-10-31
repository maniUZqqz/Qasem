# -*- coding: utf-8 -*-
"""پوستهٔ سایت: رنگ‌ها، فونت‌ها، شکلِ دکمه — یک رنگ را عوض کن، کلِ سایت عوض می‌شود.

چرا رنگ‌ها در CSSِ مشترک (SharedPart.base_css) و بقیه در blocks.css؟
  · base_css جایی است که AI هم پوسته‌اش را می‌نویسد. پس رنگ‌ها آن‌جا «آخری برنده است» را رعایت می‌کنند:
    انتشارِ پوسته ناحیهٔ خودش را ته فایل می‌گذارد و پیشنهادِ بعدیِ AI بعد از آن می‌آید. پنلِ پوسته هم همیشه
    مقدارِ «مؤثر» را از همان فایل می‌خواند، پس هیچ‌وقت دروغ نمی‌گوید.
  · blocks.css را فقط موتور می‌نویسد؛ CSSِ پایهٔ بلوک‌ها، @font-face های محلی و سربرگ/پابرگ در آن است.
    پاک‌شدنِ پوستهٔ AI نمی‌تواند ظاهرِ بلوک‌ها را خراب کند.
"""
import os
import re

from .blocks_css import BLOCK_CSS
from .clean import clean_color

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts')
AR = 'U+0600-06FF,U+0750-077F,U+0870-088E,U+0890-0891,U+0898-08E1,U+08E3-08FF,U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FE74,U+FE76-FEFC'
LA = 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD'

FONTS = {
    'vazirmatn': {'label': 'وزیرمتن (ساده و خوانا)', 'family': 'Vazirmatn', 'weight': '100 900',
                  'files': [('vazirmatn-arabic-wght-normal.woff2', AR), ('vazirmatn-latin-wght-normal.woff2', LA)]},
    'estedad': {'label': 'استعداد (امروزی)', 'family': 'Estedad', 'weight': '100 900',
                'files': [('estedad-arabic-wght-normal.woff2', AR), ('estedad-latin-wght-normal.woff2', LA)]},
    'naskh': {'label': 'نسخ (کتابی و رسمی)', 'family': 'Noto Naskh Arabic', 'weight': '400 700',
              'files': [('noto-naskh-arabic-arabic-wght-normal.woff2', AR), ('noto-naskh-arabic-latin-wght-normal.woff2', LA)]},
    'lalezar': {'label': 'لاله‌زار (پرنقش، برای تیتر)', 'family': 'Lalezar', 'weight': '400',
                'files': [('lalezar-arabic-400-normal.woff2', AR), ('lalezar-latin-400-normal.woff2', LA)]},
}
FONT_FILES = {f for v in FONTS.values() for f, _ in v['files']}
FALLBACK = '"Segoe UI",Tahoma,sans-serif'

# کلیدِ پوسته ⇐ متغیرِ CSSِ پایه (همان متغیرهایی که صفحه‌های قدیمی و AI هم می‌فهمند)
COLOR_VARS = {'primary': '--brand', 'on_primary': '--brand-ink', 'text': '--ink', 'text2': '--ink-2', 'muted': '--ink-3',
              'line': '--line', 'bg': '--bg', 'surface': '--card'}
DEFAULT_COLORS = {'primary': '#126F85', 'on_primary': '#ffffff', 'text': '#111827', 'text2': '#374151', 'muted': '#6b7280',
                  'line': '#e5e7eb', 'bg': '#f7f8fa', 'surface': '#ffffff'}
BUTTONS = {'round': 999, 'soft': 12, 'square': 4}

PRESETS = [
    {'key': 'ocean', 'label': 'آبیِ آرام', 'colors': {'primary': '#126F85', 'bg': '#f7f8fa', 'surface': '#ffffff', 'text': '#111827'}},
    {'key': 'indigo', 'label': 'بنفشِ امروزی', 'colors': {'primary': '#4f46e5', 'bg': '#f7f7fc', 'surface': '#ffffff', 'text': '#1e1b4b'}},
    {'key': 'forest', 'label': 'سبزِ طبیعی', 'colors': {'primary': '#15803d', 'bg': '#f6f8f4', 'surface': '#ffffff', 'text': '#14231a'}},
    {'key': 'sunset', 'label': 'نارنجیِ گرم', 'colors': {'primary': '#c2410c', 'bg': '#fdf8f3', 'surface': '#ffffff', 'text': '#2b1a10'}},
    {'key': 'rose', 'label': 'صورتیِ ملایم', 'colors': {'primary': '#be185d', 'bg': '#fdf6f9', 'surface': '#ffffff', 'text': '#2d1320'}},
    {'key': 'night', 'label': 'تیره', 'colors': {'primary': '#38bdf8', 'on_primary': '#06202e', 'bg': '#0f172a', 'surface': '#1e293b', 'text': '#f1f5f9',
                                                  'text2': '#cbd5e1', 'muted': '#94a3b8', 'line': '#334155'}},
]

ZONE_START = '/* ── studio:theme ── رنگ‌های پوسته از ویرایشگرِ دیداری ── */'
ZONE_END = '/* ── /studio:theme ── */'
_ZONE_RE = re.compile(re.escape(ZONE_START) + r'.*?' + re.escape(ZONE_END) + r'\n?', re.S)


def default_theme(project=None):
    colors = dict(DEFAULT_COLORS)
    if project is not None and clean_color(project.brand_color):
        colors['primary'] = project.brand_color
    return {'colors': colors, 'font_body': 'vazirmatn', 'font_head': 'vazirmatn', 'button': 'round', 'radius': 16, 'width': 1140}


def clean_theme(data, project=None):
    """ورودیِ پنل ⇐ پوستهٔ معتبر (هر چیز ناشناخته ⇐ پیش‌فرض)."""
    base = default_theme(project)
    data = data if isinstance(data, dict) else {}
    src = data.get('colors') if isinstance(data.get('colors'), dict) else {}
    for key in COLOR_VARS:
        v = str(src.get(key) or '')
        if re.fullmatch(r'#[0-9a-fA-F]{6}', v):
            base['colors'][key] = v.lower()
    for key in ('font_body', 'font_head'):
        if data.get(key) in FONTS:
            base[key] = data[key]
    if data.get('button') in BUTTONS:
        base['button'] = data['button']
    try:
        base['radius'] = max(0, min(40, int(data.get('radius', base['radius']))))
        base['width'] = max(800, min(1600, int(data.get('width', base['width']))))
    except (TypeError, ValueError):
        pass
    return base


def _expand_hex(v):
    v = v.strip().lower()
    if re.fullmatch(r'#[0-9a-f]{3}', v):
        return '#' + ''.join(c * 2 for c in v[1:])
    return v if re.fullmatch(r'#[0-9a-f]{6}', v) else None


def effective_colors(base_css):
    """مقدارِ واقعیِ هر متغیر: آخرین تعریف در CSSِ مشترک برنده است."""
    out = {}
    text = re.sub(r'/\*.*?\*/', '', base_css or '', flags=re.S)
    for key, var in COLOR_VARS.items():
        found = re.findall(r'%s\s*:\s*([^;}]+)' % re.escape(var), text)
        if found:
            v = _expand_hex(found[-1])
            if v:
                out[key] = v
    return out


def theme_for_editor(theme_row, project, base_css):
    """پوستهٔ پیش‌نویس + اگر AI یا کد بعد از انتشار رنگ‌ها را عوض کرده، همان را نشان بده."""
    data = clean_theme(theme_row.draft if theme_row and theme_row.draft else None, project)
    eff = effective_colors(base_css)
    published = (theme_row.published or {}).get('colors') if theme_row else None
    if theme_row is None or not theme_row.draft:
        data['colors'].update(eff)                  # بارِ اول: همان رنگ‌ها و گردیِ فعلیِ سایت
        found = re.findall(r'--r\s*:\s*(\d+)px', re.sub(r'/\*.*?\*/', '', base_css or '', flags=re.S))
        if found:
            data['radius'] = max(0, min(40, int(found[-1])))
    elif published:
        for key, v in eff.items():                  # بیرون از ویرایشگر عوض شده؟
            if published.get(key) != v and theme_row.draft.get('colors', {}).get(key) == published.get(key):
                data['colors'][key] = v
    return data


def colors_zone(theme):
    c = theme['colors']
    decls = ' '.join('%s: %s;' % (COLOR_VARS[k], c[k]) for k in COLOR_VARS)
    return '%s\n:root { %s --r: %dpx; --r-sm: %dpx; }\n%s\n' % (ZONE_START, decls, theme['radius'], max(0, theme['radius'] - 6), ZONE_END)


def apply_zone(base_css, theme):
    """ناحیهٔ رنگ‌ها را از هر جا هست برمی‌دارد و ته فایل می‌گذارد (آخری برنده است)."""
    body = _ZONE_RE.sub('', base_css or '').rstrip()
    return '%s\n\n%s' % (body, colors_zone(theme))


def font_faces(theme, prefix='../fonts/'):
    used = []
    for key in (theme.get('font_body'), theme.get('font_head')):
        if key in FONTS and key not in used:
            used.append(key)
    if 'vazirmatn' not in used:
        used.append('vazirmatn')                    # صفحه‌های قدیمیِ سایت هم بی‌فونت نمانند
    out = []
    for key in used:
        f = FONTS[key]
        for name, rng in f['files']:
            out.append('@font-face{font-family:"%s";font-style:normal;font-weight:%s;font-display:swap;src:url("%s%s") format("woff2");unicode-range:%s}'
                       % (f['family'], f['weight'], prefix, name, rng))
    return '\n'.join(out), used


def blocks_css(theme, prefix='../fonts/', chrome_css=''):
    """static/css/blocks.css (در بوم هم همین متن به‌صورتِ درون‌خطی می‌آید)."""
    faces, _ = font_faces(theme, prefix)
    body = FONTS.get(theme.get('font_body'), FONTS['vazirmatn'])['family']
    head = FONTS.get(theme.get('font_head'), FONTS['vazirmatn'])['family']
    tokens = (':root{--nb-font-body:"%s",%s;--nb-font-head:"%s","%s",%s;--nb-btn-radius:%dpx;--nb-width:%dpx}'
              % (body, FALLBACK, head, body, FALLBACK, BUTTONS.get(theme.get('button'), 999), theme.get('width') or 1140))
    parts = [faces, tokens, BLOCK_CSS]
    if (chrome_css or '').strip():
        parts.append('/* سربرگ و پابرگ */\n' + chrome_css.strip())
    return '\n'.join(parts) + '\n'


def public_json():
    return {'fonts': [{'value': k, 'label': v['label'], 'family': v['family']} for k, v in FONTS.items()],
            'presets': PRESETS, 'buttons': [{'value': 'round', 'label': 'کاملاً گرد'}, {'value': 'soft', 'label': 'کمی گرد'},
                                            {'value': 'square', 'label': 'گوشه‌دار'}]}
