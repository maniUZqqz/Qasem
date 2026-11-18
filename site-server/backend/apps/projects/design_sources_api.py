# -*- coding: utf-8 -*-
"""API ِ «منبع‌های طراحی» (فقط مدیر): کلِ دادهٔ ui-ux-pro-max با جست‌وجو، توکن‌های سبک‌ها، و رهنمودهایی که به هوشِ مصنوعی می‌رسد.

    GET design-sources/                     ⇒ {source{…}, kinds[{key,label,desc,count}], styles{total,hand,generated,groups[]}, fonts{bundled,…}, c21st{…}}
    GET design-sources/<kind>/              ?q=&page=&size=&type=&status=&rtl=&stack=&category=&file=&skill=&arabic=1&bundled=1 ⇒ {total,page,size,items[],facets{}}
    GET design-sources/docs/read/           ?path= ⇒ {path,title,text}
    GET design-sources/tokens/              ⇒ همهٔ سبک‌ها (کلید، نام، رنگ‌ها، قلم‌ها) برای هر ابزارِ طراحی
    GET design-sources/tokens/<style>/      ⇒ توکن‌های کاملِ یک سبک (theme، tokens، css_vars، css، قلم‌ها) — برای استودیوی طراحی و هر کدِ دیگر
    GET design-sources/recommend/           ?brief=&kind= ⇒ همان «guidance» که به مدلِ سایت‌ساز می‌رسد (شفافیت)
"""
import re

from rest_framework.response import Response

from .api import bad, studio_api
from .builder import ai_context, c21st, styles as S, theme as T
from .builder.styles import fonts_fa, uiux

TRIM = 700
MAX_SIZE = 60
FACET_COLS = {'styles': ('type', 'status', 'rtl'), 'stacks': ('stack', 'category'), 'ux': ('category', 'severity'), 'google_fonts': ('category',), 'icons': ('category',),
              'slides': ('file',), 'brand': ('file',), 'docs': ('skill',), 'products': ('rtl',), 'reasoning': ('severity',), 'react': ('category',), 'app': ('category',),
              'fonts': ('category',), 'motion': ('category',)}
FILTER_COLS = ('type', 'status', 'rtl', 'stack', 'category', 'file', 'skill', 'severity')


def _int(v, d):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _trim(row: dict, limit: int = TRIM, drop=()) -> dict:
    out = {}
    for k, v in row.items():
        if k in drop:
            continue
        out[k] = v[:limit] + '…' if isinstance(v, str) and len(v) > limit else v
    return out


def _site_style(style_id: str):
    key = S.style_key_for(style_id)
    if not key:
        return None
    st = S.STYLES[key]
    return {'key': key, 'label': st['label'], 'source': st.get('source', 'hand'), 'group': st.get('group', ''), 'primary': st['theme']['colors']['primary'],
            'bg': st['theme']['colors']['bg'], 'text': st['theme']['colors']['text']}


def _font_fa(key: str) -> dict:
    f = T.FONTS.get(key) or {}
    return {'key': key, 'label': f.get('label', key), 'family': f.get('family', '')}


def _decorate(kind: str, row: dict) -> dict:
    out = _trim(row, 520, drop=('text',) if kind == 'docs' else ())
    if kind == 'docs':
        out['snippet'] = re.sub(r'\s+', ' ', row.get('text', ''))[:260]
    if kind == 'styles':
        out['site'] = _site_style(row.get('id', ''))
    elif kind == 'fonts':
        h, b = fonts_fa.persian_pair(row.get('heading', ''), row.get('body', ''))
        out['fa'] = {'heading': _font_fa(h), 'body': _font_fa(b)}
    elif kind == 'google_fonts':
        key = fonts_fa.PERSIAN_OF.get(row.get('family', ''))
        fam = {v['family']: k for k, v in T.FONTS.items()}
        out['bundled'] = fam.get(row.get('family', ''), '')
        out['fa_key'] = key or ''
    elif kind == 'colors':
        out['used_by'] = [k for k, st in S.STYLES.items() if (st.get('uiux') or {}).get('palette') == row.get('product')][:6]
    return out


def _styles_extra(row):
    key = S.style_key_for(row.get('id', ''))
    if not key:
        return ''
    st = S.STYLES[key]
    return ' '.join([st['label'], st['mood'], ' '.join(st['tags'])])


def _facets(kind: str, where: dict, q: str, extra) -> dict:
    out = {}
    for col in FACET_COLS.get(kind, ()):
        counts = {}
        for r in uiux.rows(kind):
            v = str(r.get(col, '')).strip()
            if v:
                counts[v] = counts.get(v, 0) + 1
        out[col] = [{'value': k, 'count': n} for k, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:40]]
    return out


def _c21_summary(c21: list) -> dict:
    """شمارشِ کاتالوگِ 21st.dev برای تبِ «قطعه‌ها»: کل، مجوزِ آزاد، پیش‌نمایش، قابلِ درج، و چند‌تا در سایت تعاملی/ساده/ثابت‌اند (دورِ ۵)."""
    ins = [r for r in c21 if c21st.insertable(r)]
    inter = {'works': 0, 'plain': 0, 'static': 0}
    for r in ins:
        s = c21st.interact_of_row(r)
        inter[s if s in inter else 'plain'] += 1
    return {'catalog': len(c21), 'usable': sum(1 for r in c21 if r.get('usable')), 'previews': sum(1 for r in c21 if r.get('preview')), 'insertable': len(ins),
            'sections': sum(1 for r in ins if c21st.kind_of(r) == 'section'), 'interact': inter}


@studio_api('GET')
def sources_index(request):
    info = uiux.attribution()
    kinds = [{'key': k, 'label': uiux.KIND_FA[k][0], 'desc': uiux.KIND_FA[k][1], 'count': info['counts'][k]} for k in uiux.KINDS]
    gen = sum(1 for st in S.STYLES.values() if st.get('source') == 'generated')
    c21 = c21st.load()
    return Response({
        'source': {k: info[k] for k in ('source', 'license', 'copyright', 'commit', 'commit_date', 'retrieved', 'mirror')},
        'kinds': kinds,
        'styles': {'total': len(S.STYLES), 'hand': len(S.STYLES) - gen, 'generated': gen, 'dataset_rows': info['counts']['styles'], 'groups': S.groups()},
        'fonts': {'bundled': len(T.FONTS), 'pairings': info['counts']['fonts'], 'latin_mapped': len(fonts_fa.PERSIAN_OF)},
        'c21st': _c21_summary(c21),
        'note': 'کلِ مخزنِ ui-ux-pro-max-skill (مجوز MIT، Next Level Builder) روی سرور آینه شده و همهٔ داده‌هایش این‌جاست؛ سبک‌ها، پالت‌ها و جفتِ قلم‌ها در سایت‌ساز به کار رفته‌اند.',
    })


@studio_api('GET')
def sources_kind(request, kind):
    if kind not in uiux.KINDS:
        return bad('نوعِ ناشناخته', code=404)
    q = request.query_params
    text = (q.get('q') or '')[:120]
    size = max(1, min(MAX_SIZE, _int(q.get('size'), 24)))
    page = max(1, _int(q.get('page'), 1))
    where = {c: (q.get(c) or '')[:80] for c in FILTER_COLS if q.get(c) and c in FACET_COLS.get(kind, ())}
    if q.get('arabic') == '1':
        where['arabic'] = True
    extra = _styles_extra if kind == 'styles' else None
    # دورِ ۵: جست‌وجوی فارسی در همهٔ نوع‌ها (پیش‌تر فقط سبک‌ها فارسی می‌فهمیدند: «ورزش» در «نوعِ محصول» صفر می‌داد): واژه‌های فارسی + معادلِ انگلیسیِ حوزه/بخش/ابزار (OR)
    qtext = c21st.expand_query(text) if kind != 'styles' and re.search('[؀-ۿ]', text) else text
    if kind == 'google_fonts' and q.get('bundled') == '1':
        fams = {v['family'] for v in T.FONTS.values()}
        rows = [r for r in uiux.search(kind, qtext, limit=0, where=where) if r.get('family') in fams]
        total, items = len(rows), rows[(page - 1) * size: page * size]
    else:
        total = uiux.count(kind, qtext, where, extra)
        items = uiux.search(kind, qtext, limit=size, offset=(page - 1) * size, where=where, extra=extra)
    return Response({'kind': kind, 'label': uiux.KIND_FA[kind][0], 'desc': uiux.KIND_FA[kind][1], 'total': total, 'page': page, 'size': size,
                     'items': [_decorate(kind, r) for r in items], 'facets': _facets(kind, where, text, extra), 'source': uiux.attribution()['source']})


@studio_api('GET')
def sources_doc(request):
    path = (request.query_params.get('path') or '')[:200]
    row = uiux.by_id('docs', 'path', path)
    if not row:
        return bad('مستند پیدا نشد.', code=404)
    return Response({'path': row['path'], 'title': row['title'], 'skill': row['skill'], 'chars': row['chars'], 'text': row['text'], 'also': row.get('also', [])})


def _tokens_payload(key: str, full: bool = True) -> dict:
    st = S.STYLES[key]
    th = st['theme']
    out = {'key': key, 'label': st['label'], 'en': st['en'], 'mood': st['mood'], 'group': st.get('group', ''), 'source': st.get('source', 'hand'),
           'colors': th['colors'], 'fonts': {'heading': _font_fa(th['font_head']), 'body': _font_fa(th['font_body'])}, 'radius': th['radius'], 'button': th['button'],
           'width': th['width'], 'uiux': st.get('uiux') or {}}
    if full:
        out.update(tokens=S.tokens_of(key), sections=st.get('sections') or {}, css_vars=S.css.root_vars(key), css=S.style_css(key), status=st.get('status', 'active'),
                   rtl=st.get('rtl', 'full'), desc=st['desc'], tags=st['tags'])
    return out


@studio_api('GET')
def sources_tokens(request, key=None):
    if key is None:
        return Response({'count': len(S.ORDER), 'items': [_tokens_payload(k, full=False) for k in S.ORDER]})
    if key not in S.STYLES:
        return bad('سبکِ ناشناخته', code=404)
    return Response(_tokens_payload(key))


@studio_api('GET')
def sources_recommend(request):
    brief = (request.query_params.get('brief') or '')[:600]
    kind = request.query_params.get('kind') or 'home'
    style = request.query_params.get('style') or ''
    out = ai_context.uiux_hints(brief, kind, style)
    return Response({'brief': brief, 'kind': kind, 'guidance': out, 'limit': ai_context.GUIDE_MAX_CHARS,
                     'suggested_styles': S.find_by_text(ai_context.en_words(brief) + ' ' + brief, 5)})
