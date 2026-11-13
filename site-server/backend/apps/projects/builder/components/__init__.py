# -*- coding: utf-8 -*-
"""کتابخانهٔ «قطعه‌های آماده» (سربرگ، ویژگی، قیمت، نظر، دعوت، پابرگ، سربرگِ سایت، کارت، گالری).

هر قطعه یک بلوکِ عادیِ سایت‌ساز است با نوعِ `c_<کلید>`: در بوم و در سایتِ نهایی را همان رندرکننده می‌سازد، متن‌هایش روی بوم ویرایشِ درجا دارد،
در «تنظیمات» فرمِ خودش را دارد (از روی شکاف‌ها ساخته می‌شود)، و AI/کد هم HTMLِ ساده می‌بیند. CSSِ هر قطعه فقط وقتی به صفحه می‌آید که در آن به‌کار رفته باشد.

نقطهٔ ورود:
    COMPONENTS / ORDER           تعریف‌ها
    register(BLOCKS, ...)        ثبتِ همه در فهرستِ بلوک‌ها (catalog.py یک بار صدا می‌زند)
    render(r, b)                 بلوکِ c_* ⇒ HTML (Renderer.block صدا می‌زند)
    css_for(keys)                CSSِ پایه + CSSِ مشترک + CSSِ همین قطعه‌ها
    used_in_html(html)           قطعه‌هایی که در یک HTML به‌کار رفته‌اند (از کلاسِ nbc-…)
    public_json()                آنچه پنل لازم دارد (بی‌HTML)
"""
import copy

from . import lib_cards, lib_chrome, lib_features, lib_hero, lib_pricing, lib_social, provenance
from .base_css import BASE
from .spec import CAT_ICON, CAT_LABEL, CATEGORIES, SHARED

PREFIX = 'c_'
LIBS = (lib_hero, lib_features, lib_pricing, lib_social, lib_cards, lib_chrome)
_cat_rank = {k: i for i, (k, _l, _ic) in enumerate(CATEGORIES)}

COMPONENTS = {}
for _lib in LIBS:
    for _c in _lib.SPECS:
        if _c['key'] in COMPONENTS:                      # کلیدِ تکراری یعنی خطای برنامه‌نویسی؛ همین‌جا بلند بخوان
            raise ValueError('قطعهٔ تکراری: %s' % _c['key'])
        COMPONENTS[_c['key']] = _c
ORDER = sorted(COMPONENTS, key=lambda k: (_cat_rank.get(COMPONENTS[k]['cat'], 99), list(COMPONENTS).index(k)))


def block_type(key):
    return PREFIX + key


def key_of(btype):
    """نوعِ بلوک ⇒ کلیدِ قطعه (یا None)."""
    k = btype[len(PREFIX):] if isinstance(btype, str) and btype.startswith(PREFIX) else None
    return k if k in COMPONENTS else None


def class_of(key):
    return 'nbc-' + key.replace('_', '-')


_BY_CLASS = {class_of(k): k for k in COMPONENTS}


def _field(slot):
    return {k: v for k, v in slot.items() if k not in ('default', '_row_defaults')}


def catalog_entry(comp, section_style):
    fields = [_field(s) for s in comp['slots']]
    defaults = {s['key']: copy.deepcopy(s['default']) for s in comp['slots']}
    if comp['root'] == 'header':
        style = ['color', 'bg', 'border', 'bw', 'shadow']
    elif comp['root'] == 'footer':
        style = ['color', 'bg', 'py', 'px', 'mt', 'mb', 'align']
    else:
        style = list(section_style)
    return dict(label=comp['label'], group='components', icon=CAT_ICON.get(comp['cat'], 'layout'), root=True, hint=comp['desc'],
                fields=fields, defaults=defaults, style=style, scope=comp['scope'], component=comp['key'], category=comp['cat'])


def register(blocks, section_style):
    """قطعه‌ها را به فهرستِ بلوک‌ها اضافه می‌کند (کلیدِ c_<کلید>)."""
    for key in ORDER:
        blocks[block_type(key)] = catalog_entry(COMPONENTS[key], section_style)


def meta(key):
    c = COMPONENTS[key]
    return {'key': key, 'type': block_type(key), 'cat': c['cat'], 'label': c['label'], 'desc': c['desc'], 'tags': c['tags'], 'styles': c['styles'],
            'root': c['root'], 'scope': c['scope'], 'src': provenance.public(provenance.src_of(c))}


def public_json():
    return {'categories': [{'key': k, 'label': l, 'icon': i, 'count': sum(1 for c in COMPONENTS.values() if c['cat'] == k)} for k, l, i in CATEGORIES],
            'items': [meta(k) for k in ORDER]}


# ─────────────────────────────── رندر
def render(r, b):
    from . import engine
    comp = COMPONENTS[key_of(b['type'])]
    r.use_component(comp['key'])
    p = b['props']
    inner = engine.expand(comp['html'], p, '', r)
    if '<h1' in comp['html']:
        r.headings.append((1, b))
    cls = 'nbc ' + class_of(comp['key'])
    if comp['root'] == 'header':
        inner = engine.chrome_tokens(inner, r, b['id'])
        return '<header %s>\n%s\n</header>' % (r.attrs(b, 'nb-header ' + cls + (' is-sticky' if p.get('sticky') else '')), inner)
    if comp['root'] == 'footer':
        inner = engine.chrome_tokens(inner, r, b['id'])
        return '<div %s>\n<div class="nb-wrap">\n%s\n</div>\n</div>' % (r.attrs(b, cls), inner)
    return r.shell(b, cls, inner)


# ─────────────────────────────── CSS
def css_for(keys):
    """CSSِ قطعه‌هایی که به‌کار رفته‌اند: پایه یک بار، بعد CSSِ مشترکِ لازم، بعد CSSِ هر قطعه به ترتیبِ ثابت."""
    used = [k for k in ORDER if k in set(keys)]
    if not used:
        return ''
    shared = []
    for k in used:
        for u in COMPONENTS[k]['uses']:
            if u not in shared and u in SHARED:
                shared.append(u)
    parts = ['/* قطعه‌های آماده */', BASE] + [SHARED[u] for u in shared] + [COMPONENTS[k]['css'] for k in used if COMPONENTS[k]['css']]
    return '\n'.join(parts)


def used_in_html(html):
    """⇒ فهرستِ کلیدِ قطعه‌هایی که کلاسِ ریشه‌شان در این HTML هست (برای ضمیمهٔ CSS پس از کارِ AI)."""
    import re
    found = []
    for m in re.finditer(r'class="([^"]*)"', html or ''):
        for t in m.group(1).split():
            k = _BY_CLASS.get(t)
            if k and k not in found:
                found.append(k)
    return found


__all__ = ['COMPONENTS', 'ORDER', 'PREFIX', 'register', 'render', 'css_for', 'used_in_html', 'public_json', 'meta', 'key_of', 'class_of', 'block_type', 'CAT_LABEL']
