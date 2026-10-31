# -*- coding: utf-8 -*-
"""تنها رندرکنندهٔ بلوک‌ها: سند ⇐ HTML (قالبِ جنگو) + CSS.

عمداً دو رندرکننده نداریم. بوم (canvas) هم همین کد را صدا می‌زند؛ فقط `canvas=True` چند ویژگیِ
data-* برای انتخاب و ویرایشِ متن اضافه می‌کند و نشانیِ تصویرها را مستقیم می‌دهد. خروجی هیچ
وابستگی‌ای به جاوااسکریپتِ ویرایشگر ندارد.
"""
import json
import re
from urllib.parse import parse_qs, urlparse

from . import icons
from .catalog import BLOCKS, CONTAINERS
from .clean import esc, neutralize, safe_url, walk

ZONE_START = '/* ── studio:blocks ── این بخش را ویرایشگرِ دیداری می‌نویسد ── */'
ZONE_END = '/* ── /studio:blocks ── */'

TOKENS = {'primary': 'var(--brand)', 'on_primary': 'var(--brand-ink)', 'text': 'var(--ink)', 'text2': 'var(--ink-2)',
          'muted': 'var(--ink-3)', 'line': 'var(--line)', 'bg': 'var(--bg)', 'surface': 'var(--card)',
          'white': '#ffffff', 'black': '#000000'}
SHADOWS = {'soft': '0 1px 2px rgba(0,0,0,.04),0 8px 24px -12px rgba(0,0,0,.18)',
           'medium': '0 2px 6px rgba(0,0,0,.08),0 18px 40px -18px rgba(0,0,0,.3)',
           'strong': '0 6px 14px rgba(0,0,0,.14),0 30px 70px -24px rgba(0,0,0,.5)'}
TABLET = '@media (max-width:1024px)'
PHONE = '@media (max-width:640px)'
PLACEHOLDER_IMG = ('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 800 500%22%3E'
                   '%3Crect width=%22800%22 height=%22500%22 fill=%22%23e8ebf1%22/%3E%3Cpath d=%22M320 310l70-85 55 65 35-40 70 60z%22 '
                   'fill=%22%23b8c0cf%22/%3E%3Ccircle cx=%22345%22 cy=%22205%22 r=%2224%22 fill=%22%23b8c0cf%22/%3E%3C/svg%3E')


def color_css(v):
    if not v:
        return ''
    if v.startswith('t:'):
        return TOKENS.get(v[2:], '')
    return v


# ─────────────────────────────── محیطِ رندر
class Ctx:
    """همهٔ چیزهایی که رندر از پروژه لازم دارد؛ با کوئری نگرفتنِ تکراری."""

    def __init__(self, project=None, canvas=False, media=None, pages=None, models=None, has_cart=False, routes=None,
                 theme=None, target='page', css_prefix='../../'):
        self.project = project
        self.canvas = canvas
        self.media = media or {}
        self.pages = pages or {}
        self.models = models or {}
        self.has_cart = has_cart
        self.routes = routes or {}
        self.theme = theme or {}
        self.target = target
        self.css_prefix = css_prefix
        self.mark = False            # فقط برای مقایسهٔ متن در importer
        self.chrome_only = False     # سربرگ/پابرگ در بوم: نشانیِ مستقیم ولی بی‌انتخاب


def build_ctx(project, canvas=False, target='page', theme=None):
    from apps.projects.models import MediaAsset, Page, Route
    media = {a.pk: a for a in MediaAsset.objects.filter(project=project)}
    pages = {p.pk: p.slug for p in Page.objects.filter(project=project)}
    routes = {}
    for r in Route.objects.filter(project=project, view__kind='detail').select_related('view__model__app'):
        if r.name and r.view.model_id:
            routes['%s.%s' % (r.view.model.app.name, r.view.model.name)] = r.name
    return Ctx(project, canvas=canvas, media=media, pages=pages, models=model_index(project),
               has_cart=project.apps.filter(name='cart').exists() and project.apps.filter(name='catalog').exists(),
               routes=routes, theme=theme or {}, target=target,
               css_prefix='../../' if target == 'page' else '../')


def model_index(project):
    """مدل‌هایی که می‌شود روی سایت نشان داد، با فیلدهایشان؛ ⇒ {'catalog.Product': {...}}

    ⚠ پیام‌های فرم و سفارش‌های مشتری عمداً این‌جا نیستند تا کسی ناخواسته دادهٔ خصوصی را عمومی نکند."""
    from apps.projects.models import Model
    out = {}
    for m in Model.objects.filter(app__project=project).select_related('app').prefetch_related('fields'):
        if m.app.name == 'site_forms' or (m.app.is_core and m.app.name == 'orders'):
            continue
        fields = [{'name': f.name, 'type': f.field_type, 'label': f.verbose_name_fa or f.name,
                   'choices': bool(f.choices.strip()) if f.choices else False}
                  for f in m.fields.all() if f.field_type not in ('custom', 'JSONField', 'UUIDField', 'SlugField')]
        out['%s.%s' % (m.app.name, m.name)] = {
            'app': m.app.name, 'name': m.name, 'label': m.verbose_plural_fa or m.verbose_name_fa or m.name,
            'singular': m.verbose_name_fa or m.name,
            'fields': fields, 'pk': m.pk,
        }
    return out


TEXT_TYPES = ('CharField', 'EmailField', 'URLField')
LONG_TYPES = ('TextField',)
NUM_TYPES = ('IntegerField', 'PositiveIntegerField', 'BigIntegerField', 'FloatField', 'DecimalField')


def default_fields(model):
    """اگر کاربر چیزی انتخاب نکرده: تصویر + عنوان + عدد (قیمت) + متن."""
    fields = model['fields']
    picked = []
    for types, limit in ((('ImageField',), 1), (TEXT_TYPES, 1), (NUM_TYPES[-1:], 1), (LONG_TYPES, 1)):
        n = 0
        for f in fields:
            if f['type'] in types and n < limit and f['name'] not in picked:
                picked.append(f['name'])
                n += 1
    return picked or [f['name'] for f in fields[:3]]


# ─────────────────────────────── رندرکننده
class Renderer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.rules = []
        self.warnings = []
        self.headings = []
        self.uses_form = False

    # ── ابزارها ──
    def attrs(self, b, cls):
        """class و (فقط در بوم) ویژگی‌های انتخاب."""
        extra = b['props'].get('cls')
        klass = ('%s b-%s' % (cls, b['id'])).strip()
        if extra:
            klass = '%s %s' % (esc(extra), klass)
        out = 'class="%s"' % klass
        if self.ctx.canvas and not self.ctx.chrome_only:
            out += ' data-bid="%s" data-type="%s"' % (b['id'], b['type'])
        return out

    def ed(self, path, rich=False, multi=False):
        if not (self.ctx.mark or (self.ctx.canvas and not self.ctx.chrome_only)):
            return ''
        mode = 'rich' if rich else ('multi' if multi else 'plain')
        return ' data-nb-edit="%s" data-nb-mode="%s"' % (esc(path), mode)

    def line(self, text):
        return esc(text).replace('\n', '<br>')

    def txt(self, b, path, tag, cls='', multi=False, base=None):
        """یک متنِ قابلِ ویرایش روی بوم؛ خالی در خروجی چیزی نمی‌سازد ولی در بوم جا می‌گیرد."""
        val = self._get(b['props'] if base is None else base, path.split('.')[-1] if base is not None else path)
        if not val and not self.ctx.canvas:
            return ''
        k = ' class="%s"' % cls if cls else ''
        if not val:
            k = ' class="%s nb-blank"' % cls if cls else ' class="nb-blank"'
        return '<%s%s%s>%s</%s>' % (tag, k, self.ed(path, multi=multi), self.line(val or ''), tag)

    @staticmethod
    def _get(obj, key):
        return (obj or {}).get(key) or ''

    def link(self, value):
        u = safe_url(value)
        m = re.match(r'^page:(\d+)$', u or '')
        if m:
            slug = self.ctx.pages.get(int(m.group(1)))
            if slug is None:
                return '#'
            return '/%s/' % slug if slug else '/'
        return u or '#'

    def asset(self, ref):
        m = re.match(r'^m:(\d+)$', ref or '')
        return self.ctx.media.get(int(m.group(1))) if m else None

    def media_url(self, asset, rel=None):
        rel = rel or asset.rel_path
        name = rel[len('static/'):] if rel.startswith('static/') else rel
        if self.ctx.canvas:
            return '/api/v1/studio/builder-media/%s/%s' % (self.ctx.project.slug, name.split('/', 1)[-1])
        return "{%% static '%s' %%}" % name

    def css_url(self, ref):
        asset = self.asset(ref)
        if asset:
            name = asset.rel_path[len('static/'):]
            if self.ctx.canvas:
                return '/api/v1/studio/builder-media/%s/%s' % (self.ctx.project.slug, name.split('/', 1)[-1])
            return self.ctx.css_prefix + name
        return esc(ref) if re.match(r'^(https?://|/)', ref or '') else ''

    def img(self, ref, alt='', cls='', sizes='100vw', lazy=True, extra=''):
        k = ' class="%s"' % cls if cls else ''
        asset = self.asset(ref)
        lz = ' loading="lazy" decoding="async"' if lazy else ''
        if asset:
            srcset = ''
            variants = asset.variants or {}
            if variants:
                parts = ['%s %dw' % (self.media_url(asset, rel), int(w)) for w, rel in sorted(variants.items(), key=lambda x: int(x[0]))]
                parts.append('%s %dw' % (self.media_url(asset), asset.width or 1920))
                srcset = ' srcset="%s" sizes="%s"' % (', '.join(parts), sizes)
            dims = ' width="%d" height="%d"' % (asset.width, asset.height) if asset.width and asset.height else ''
            return '<img%s src="%s"%s alt="%s"%s%s%s>' % (k, self.media_url(asset), srcset, esc(alt or asset.alt), dims, lz, extra)
        if re.match(r'^(https?://|/)', ref or ''):
            return '<img%s src="%s" alt="%s"%s%s>' % (k, esc(ref), esc(alt), lz, extra)
        if self.ctx.canvas:
            return '<img%s src="%s" alt="" data-nb-ph="1"%s>' % (k, PLACEHOLDER_IMG, extra)
        return ''

    def warn(self, b, text):
        self.warnings.append({'id': b['id'], 'type': b['type'], 'text': text})

    def rule(self, selector, decls):
        decls = [d for d in decls if d]
        if decls:
            self.rules.append((selector, ';'.join(decls)))

    # ── تنظیماتِ ظاهری ──
    def style_css(self, b):
        st = b.get('style') or {}
        sel = '.b-%s' % b['id']
        is_section = BLOCKS[b['type']].get('root') and b['type'] != 'site_header'
        for dev, media in (('d', None), ('t', TABLET), ('p', PHONE)):
            row = st.get(dev)
            if not row:
                continue
            decls = []
            if 'color' in row:
                decls.append('color:%s' % color_css(row['color']))
            if 'size' in row:
                decls.append('font-size:%dpx' % row['size'])
            if 'weight' in row:
                decls.append('font-weight:%s' % row['weight'])
            if 'align' in row:
                a = row['align']
                decls.append('text-align:%s' % a)
                if b['type'] in ('image', 'video'):
                    decls.append('margin-inline:%s' % {'start': '0 auto', 'center': 'auto', 'end': 'auto 0'}[a])
                self.rule_at(media, '%s .nb-actions' % sel, ['justify-content:%s' % {'start': 'flex-start', 'center': 'center', 'end': 'flex-end'}[a]])
            if 'bg' in row:
                decls.append('background:%s' % color_css(row['bg']))
            if 'bgimg' in row:
                url = self.css_url(row['bgimg'])
                if url:
                    ov = (row.get('overlay') or 0) / 100.0
                    layer = 'linear-gradient(rgba(0,0,0,%.2f),rgba(0,0,0,%.2f)),' % (ov, ov) if ov else ''
                    decls.append('background-image:%surl("%s")' % (layer, url))
                    decls.append('background-size:cover;background-position:center')
            if 'py' in row:
                decls.append('padding-block:%dpx' % row['py'])
            if 'px' in row:
                decls.append('padding-inline:%dpx' % row['px'])
            if 'mt' in row:
                decls.append('margin-top:%dpx' % row['mt'])
            if 'mb' in row:
                decls.append('margin-bottom:%dpx' % row['mb'])
            if 'width' in row:
                decls.append('width:%d%%' % row['width'])
            if 'maxw' in row:
                if is_section:
                    self.rule_at(media, '%s>.nb-wrap' % sel, ['max-width:%dpx' % row['maxw']])
                else:
                    decls.append('max-width:%dpx' % row['maxw'])
            if 'minh' in row:
                decls.append('min-height:%dpx' % row['minh'])
                if is_section:
                    decls.append('display:grid;align-content:center')
            if 'radius' in row:
                decls.append('border-radius:%dpx' % row['radius'])
                decls.append('overflow:hidden')
            if 'shadow' in row:
                decls.append('box-shadow:%s' % SHADOWS.get(row['shadow'], 'none'))
            if 'border' in row or 'bw' in row:
                decls.append('border:%dpx solid %s' % (row.get('bw', 1), color_css(row.get('border')) or 'var(--line)'))
            self.rule_at(media, sel, decls)
        d = st.get('d') or {}
        # تیترِ بزرگ در گوشی خودکار کوچک می‌شود، مگر کاربر برای گوشی عددِ جدا داده باشد
        size = d.get('size')
        if size and size > 30 and 'size' not in (st.get('p') or {}):
            self.rule_at(PHONE, sel, ['font-size:%dpx' % max(24, int(size * .68))])
        hide = {'hide_desktop': '@media (min-width:1025px)', 'hide_tablet': '@media (min-width:641px) and (max-width:1024px)',
                'hide_phone': PHONE}
        for key, media in hide.items():
            if d.get(key):
                self.rule_at(media, sel, ['display:none!important'])

    def rule_at(self, media, selector, decls):
        decls = [x for x in decls if x]
        if decls:
            self.rules.append((media, selector, ';'.join(decls)))

    def css(self):
        groups = {None: [], TABLET: [], PHONE: []}
        for row in self.rules:
            media, sel, decls = row if len(row) == 3 else (None, row[0], row[1])
            groups.setdefault(media, []).append('%s{%s}' % (sel, decls))
        out = list(groups[None])
        for media in sorted(k for k in groups if k):
            if groups[media]:
                out.append('%s{%s}' % (media, ''.join(groups[media])))
        return '\n'.join(out)

    # ── درخت ──
    def children(self, b):
        kids = b.get('children') or []
        if kids:
            return '\n'.join(self.block(k) for k in kids)
        if self.ctx.canvas:
            return '<div class="nb-drop-here" data-nb-ph="1">یک بلوک این‌جا بکش یا از فهرست انتخاب کن</div>'
        return ''

    def block(self, b):
        self.style_css(b)
        fn = getattr(self, 'r_' + b['type'])
        return fn(b)

    def shell(self, b, cls, inner):
        """پوستهٔ مشترکِ بخش‌های آماده."""
        return '<section %s>\n<div class="nb-wrap">\n%s\n</div>\n</section>' % (self.attrs(b, 'nb-section ' + cls), inner)

    def head(self, b):
        """تیتر و توضیحِ بالای بخش‌های آماده."""
        parts = [self.txt(b, 'title', 'h2', 'nb-title'), self.txt(b, 'subtitle', 'p', 'nb-sub', multi=True)]
        parts = [p for p in parts if p]
        return '<div class="nb-head">%s</div>' % ''.join(parts) if parts else ''

    def cols_css(self, b, cls, key='cols', default=3):
        c = b['props'].get(key)
        if not isinstance(c, dict):
            c = {'d': c or default}
        d = c.get('d') or default
        self.rule_at(None, '.b-%s .%s' % (b['id'], cls), ['grid-template-columns:repeat(%d,minmax(0,1fr))' % d])
        self.rule_at(TABLET, '.b-%s .%s' % (b['id'], cls), ['grid-template-columns:repeat(%d,minmax(0,1fr))' % (c.get('t') or min(d, 2))])
        self.rule_at(PHONE, '.b-%s .%s' % (b['id'], cls), ['grid-template-columns:repeat(%d,minmax(0,1fr))' % (c.get('p') or 1)])

    # ── چیدمان ──
    def r_section(self, b):
        p = b['props']
        cls = '' if p.get('legacy') else 'nb-section' + (' is-full' if p.get('full') else '')
        inner_cls = p.get('inner_cls')
        kids = self.children(b)
        if inner_cls == '-':                       # بخشِ واردشده بی‌پوشش بود
            return '<section %s>\n%s\n</section>' % (self.attrs(b, cls), kids)
        return '<section %s>\n<div class="%s">\n%s\n</div>\n</section>' % (self.attrs(b, cls), esc(inner_cls or 'nb-wrap'), kids)

    def r_columns(self, b):
        p = b['props']
        n = len(b.get('children') or []) or 1
        ratio = p.get('ratio') or 'equal'
        tracks = ['minmax(0,1fr)'] * n
        if n > 1 and ratio == 'wide-first':
            tracks[0] = 'minmax(0,2fr)'
        elif n > 1 and ratio == 'wide-last':
            tracks[-1] = 'minmax(0,2fr)'
        va = {'center': 'center', 'end': 'end'}.get(p.get('valign'), 'start')
        self.rule_at(None, '.b-%s' % b['id'], ['grid-template-columns:%s' % ' '.join(tracks), 'gap:%dpx' % (p.get('gap') if p.get('gap') is not None else 24),
                                                 'align-items:%s' % va])
        if n > 2:
            self.rule_at(TABLET, '.b-%s' % b['id'], ['grid-template-columns:repeat(2,minmax(0,1fr))'])
        self.rule_at(PHONE, '.b-%s' % b['id'], ['grid-template-columns:minmax(0,1fr)'])
        kids = '\n'.join(self.block(k) for k in b.get('children') or [])
        return '<div %s>\n%s\n</div>' % (self.attrs(b, 'nb-cols'), kids)

    def r_column(self, b):
        return '<div %s>\n%s\n</div>' % (self.attrs(b, 'nb-col'), self.children(b))

    # ── پایه ──
    def r_heading(self, b):
        p = b['props']
        lv = int(p.get('level') or 2)
        self.headings.append((lv, b))
        base = '' if p.get('legacy') else 'nb-h nb-h%d' % lv
        return '<h%d %s%s>%s</h%d>' % (lv, self.attrs(b, base), self.ed('text'), self.line(p.get('text') or ''), lv)

    def r_text(self, b):
        html = neutralize(b['props'].get('html') or '')
        return '<div %s%s>%s</div>' % (self.attrs(b, '' if b['props'].get('legacy') else 'nb-text'), self.ed('html', rich=True), html)

    def r_image(self, b):
        p = b['props']
        src = p.get('src')
        if not src:
            self.warn(b, 'این تصویر هنوز انتخاب نشده.')
        elif not (p.get('alt') or (self.asset(src).alt if self.asset(src) else '')):
            self.warn(b, 'برای این تصویر توضیح بنویس تا نابینایان و گوگل هم بفهمند چیست.')
        img = self.img(src, p.get('alt'), sizes='(max-width:800px) 100vw, 800px')
        if not img:
            return ''
        if p.get('link'):
            img = '<a href="%s">%s</a>' % (esc(self.link(p['link'])), img)
        cap = '<figcaption>%s</figcaption>' % esc(p['caption']) if p.get('caption') else ''
        return '<figure %s>%s%s</figure>' % (self.attrs(b, 'nb-image'), img, cap)

    def btn(self, text, link, cls='nb-btn', path=None, new_tab=False):
        if not text:
            return ''              # دکمهٔ بی‌متن نه در سایت هست نه روی بوم؛ از تنظیمات اضافه می‌شود
        k = ' target="_blank" rel="noopener"' if new_tab else ''
        return '<a class="%s" href="%s"%s%s>%s</a>' % (cls, esc(self.link(link)), k, self.ed(path) if path else '', esc(text or ''))

    def r_button(self, b):
        p = b['props']
        cls = esc(p['btn_cls']) if p.get('btn_cls') else 'nb-btn is-%s is-%s' % (p.get('variant') or 'filled', p.get('btn_size') or 'md')
        return '<div %s>%s</div>' % (self.attrs(b, 'nb-button'), self.btn(p.get('text'), p.get('link'), cls, 'text', p.get('new_tab')))

    def r_video(self, b):
        p = b['props']
        asset = self.asset(p.get('source'))
        poster = self.asset(p.get('poster'))
        inner = ''
        if asset:
            ps = ' poster="%s"' % self.media_url(poster) if poster else ''
            inner = '<video controls preload="metadata" playsinline%s src="%s" title="%s"></video>' % (ps, self.media_url(asset), esc(p.get('title')))
        else:
            embed = video_embed(p.get('link'))
            if embed:
                inner = '<iframe src="%s" title="%s" loading="lazy" allowfullscreen></iframe>' % (esc(embed), esc(p.get('title') or 'ویدیو'))
            elif p.get('link'):
                inner = '<a class="nb-btn is-outline is-md" href="%s" target="_blank" rel="noopener">دیدنِ ویدیو</a>' % esc(safe_url(p['link']))
        if not inner:
            self.warn(b, 'ویدیو هنوز انتخاب نشده.')
            if not self.ctx.canvas:
                return ''
            inner = '<div class="nb-video-ph" data-nb-ph="1">ویدیو را از ستونِ تنظیمات انتخاب کن</div>'
        return '<div %s>%s</div>' % (self.attrs(b, 'nb-video'), inner)

    def r_spacer(self, b):
        self.rule_at(None, '.b-%s' % b['id'], ['height:%dpx' % (b['props'].get('height') or 40)])
        return '<div %s aria-hidden="true"></div>' % self.attrs(b, 'nb-spacer')

    def r_divider(self, b):
        p = b['props']
        self.rule_at(None, '.b-%s' % b['id'], ['border-top:%dpx solid %s' % (p.get('thickness') or 1, color_css(p.get('line')) or 'var(--line)')])
        return '<hr %s>' % self.attrs(b, 'nb-divider')

    def r_icon(self, b):
        p = b['props']
        self.rule_at(None, '.b-%s .nb-svg' % b['id'], ['width:%dpx' % (p.get('icon_size') or 48), 'height:%dpx' % (p.get('icon_size') or 48),
                                                       'color:%s' % (color_css(p.get('tint')) or 'var(--brand)')])
        inner = icons.svg(p.get('name'))
        if p.get('link'):
            inner = '<a href="%s" aria-label="پیوند">%s</a>' % (esc(self.link(p['link'])), inner)
        return '<div %s>%s</div>' % (self.attrs(b, 'nb-icon'), inner)

    def r_gallery(self, b):
        p = b['props']
        self.cols_css(b, 'nb-gallery-in')
        self.rule_at(None, '.b-%s .nb-gallery-in' % b['id'], ['gap:%dpx' % (p.get('gap') if p.get('gap') is not None else 12)])
        self.rule_at(None, '.b-%s img' % b['id'], ['aspect-ratio:%s' % (p.get('ratio') or '1/1').replace('/', ' / ')])
        cells = []
        for row in p.get('items') or []:
            if not row.get('image'):
                continue
            if not row.get('alt'):
                self.warn(b, 'برای تصویرهای گالری توضیح بنویس.')
            i = self.img(row['image'], row.get('alt'), sizes='(max-width:640px) 50vw, 400px')
            if i:
                cells.append('<div class="nb-gallery-cell">%s</div>' % i)
        if not cells:
            self.warn(b, 'گالری هنوز تصویری ندارد.')
            if not self.ctx.canvas:
                return ''
            cells = ['<div class="nb-gallery-cell"><img src="%s" alt="" data-nb-ph="1"></div>' % PLACEHOLDER_IMG] * 3
        return '<div %s><div class="nb-gallery-in">%s</div></div>' % (self.attrs(b, 'nb-gallery'), ''.join(cells))

    def r_custom_html(self, b):
        code = b['props'].get('code') or ''
        if self.ctx.canvas:
            code = canvas_safe(code)
            if not code.strip():
                code = '<div class="nb-drop-here" data-nb-ph="1">کدِ سفارشی</div>'
            return '<div %s data-nb-custom="1">%s</div>' % (self.attrs(b, 'nb-custom'), code)
        return '<div %s>\n%s\n</div>' % (self.attrs(b, 'nb-custom'), code)

    # ── بخش‌های آماده ──
    def r_hero(self, b):
        p = b['props']
        split = p.get('layout') == 'split'
        self.headings.append((1, b))
        actions = ''.join(x for x in (self.btn(p.get('btn1'), p.get('btn1_link'), 'nb-btn is-filled is-lg', 'btn1'),
                                      self.btn(p.get('btn2'), p.get('btn2_link'), 'nb-btn is-ghost is-lg', 'btn2')) if x)
        copy = ''.join(x for x in (self.txt(b, 'eyebrow', 'span', 'nb-eyebrow'), self.txt(b, 'title', 'h1', 'nb-hero-title'),
                                   self.txt(b, 'subtitle', 'p', 'nb-sub', multi=True),
                                   '<div class="nb-actions">%s</div>' % actions if actions else '') if x)
        media = ''
        if p.get('image') or (split and self.ctx.canvas):
            if p.get('image') and not p.get('image_alt') and not (self.asset(p['image']) and self.asset(p['image']).alt):
                self.warn(b, 'برای تصویرِ سربرگ توضیح بنویس.')
            media = self.img(p.get('image'), p.get('image_alt'), sizes='(max-width:800px) 100vw, 560px', lazy=False)
        if split:
            inner = '<div class="nb-hero-split"><div class="nb-hero-copy">%s</div><div class="nb-hero-media">%s</div></div>' % (copy, media)
        else:
            inner = '<div class="nb-hero-copy is-center">%s</div>%s' % (copy, '<div class="nb-hero-media">%s</div>' % media if media else '')
        return self.shell(b, 'nb-hero', inner)

    def r_features(self, b):
        p = b['props']
        self.cols_css(b, 'nb-grid')
        cards = []
        for i, row in enumerate(p.get('items') or []):
            base = 'items.%d.' % i
            cards.append('<article class="nb-feature"><span class="nb-feature-icon">%s</span>%s%s</article>' % (
                icons.svg(row.get('icon')),
                self.txt(b, base + 'title', 'h3', 'nb-feature-title', base=row),
                self.txt(b, base + 'text', 'p', 'nb-feature-text', multi=True, base=row)))
        return self.shell(b, 'nb-features', '%s<div class="nb-grid">%s</div>' % (self.head(b), '\n'.join(cards)))

    def r_pricing(self, b):
        p = b['props']
        items = p.get('items') or []
        self.rule_at(None, '.b-%s .nb-grid' % b['id'], ['grid-template-columns:repeat(%d,minmax(0,1fr))' % (min(len(items), 4) or 1)])
        self.rule_at(TABLET, '.b-%s .nb-grid' % b['id'], ['grid-template-columns:repeat(%d,minmax(0,1fr))' % (min(len(items), 2) or 1)])
        self.rule_at(PHONE, '.b-%s .nb-grid' % b['id'], ['grid-template-columns:minmax(0,1fr)'])
        cards = []
        for i, row in enumerate(items):
            base = 'items.%d.' % i
            feats = ''.join('<li>%s<span>%s</span></li>' % (icons.svg('check'), esc(x.strip()))
                            for x in (row.get('features') or '').splitlines() if x.strip())
            cards.append('<article class="nb-plan%s">%s%s%s<ul class="nb-plan-list">%s</ul>%s</article>' % (
                ' is-featured' if row.get('highlight') else '',
                self.txt(b, base + 'name', 'h3', 'nb-plan-name', base=row),
                self.txt(b, base + 'price', 'div', 'nb-plan-price', base=row),
                self.txt(b, base + 'period', 'div', 'nb-plan-period', base=row),
                feats,
                self.btn(row.get('button'), row.get('link'), 'nb-btn %s is-md' % ('is-filled' if row.get('highlight') else 'is-outline'), base + 'button')))
        return self.shell(b, 'nb-pricing', '%s<div class="nb-grid">%s</div>' % (self.head(b), '\n'.join(cards)))

    def r_testimonials(self, b):
        p = b['props']
        cards = []
        for i, row in enumerate(p.get('items') or []):
            base = 'items.%d.' % i
            avatar = self.img(row.get('avatar'), row.get('name'), 'nb-avatar', sizes='56px') if row.get('avatar') else ''
            if not avatar:
                avatar = '<span class="nb-avatar nb-avatar-ph">%s</span>' % esc((row.get('name') or '؟')[:1])
            cards.append('<figure class="nb-quote">%s<figcaption>%s<span>%s%s</span></figcaption></figure>' % (
                self.txt(b, base + 'text', 'blockquote', '', multi=True, base=row), avatar,
                self.txt(b, base + 'name', 'b', '', base=row), self.txt(b, base + 'role', 'small', '', base=row)))
        return self.shell(b, 'nb-testimonials', '%s<div class="nb-grid">%s</div>' % (self.head(b), '\n'.join(cards)))

    def r_faq(self, b):
        p = b['props']
        rows = []
        for i, row in enumerate(p.get('items') or []):
            base = 'items.%d.' % i
            rows.append('<details class="nb-faq-item"%s>%s%s</details>' % (
                ' open' if self.ctx.canvas else '',
                self.txt(b, base + 'q', 'summary', '', base=row), self.txt(b, base + 'a', 'p', '', multi=True, base=row)))
        return self.shell(b, 'nb-faq', '%s<div class="nb-faq-list">%s</div>' % (self.head(b), '\n'.join(rows)))

    def r_cta(self, b):
        p = b['props']
        inner = ''.join(x for x in (self.txt(b, 'title', 'h2', 'nb-title'), self.txt(b, 'text', 'p', 'nb-sub', multi=True),
                                    '<div class="nb-actions">%s</div>' % self.btn(p.get('btn'), p.get('btn_link'), 'nb-btn is-ghost is-lg', 'btn')) if x)
        return self.shell(b, 'nb-cta', '<div class="nb-cta-box">%s</div>' % inner)

    def r_contact_form(self, b):
        p = b['props']
        self.uses_form = True
        spec, rows = [], []
        for i, f in enumerate(p.get('fields') or []):
            name = 'fld_%d' % i
            ftype = f.get('type') or 'text'
            req = bool(f.get('required'))
            spec.append({'n': name, 'l': f.get('label') or name, 't': ftype, 'r': req})
            rq = ' required' if req else ''
            lab = '<label for="%s-%s">%s</label>' % (b['id'], name, self.line(f.get('label') or ''))
            if ftype == 'textarea':
                ctrl = '<textarea id="%s-%s" name="%s" rows="4"%s></textarea>' % (b['id'], name, name, rq)
            else:
                ctrl = '<input id="%s-%s" name="%s" type="%s"%s>' % (b['id'], name, name, ftype, rq)
            rows.append('<div class="nb-form-row">%s%s</div>' % (lab, ctrl))
        if not spec:
            self.warn(b, 'فرم هنوز فیلدی ندارد.')
        hidden = ('{%% csrf_token %%}<input type="hidden" name="_next" value="{{ request.path }}">'
                  '<input type="hidden" name="_form" value="%s"><input type="hidden" name="_success" value="%s">'
                  '<input type="hidden" name="_spec" value="%s">'
                  '<div class="nb-hp" aria-hidden="true"><label>وب‌سایت<input name="website" tabindex="-1" autocomplete="off"></label></div>'
                  % (esc(p.get('title') or 'فرم'), esc(p.get('success')), esc(json.dumps(spec, ensure_ascii=False))))
        form = ('<form class="nb-form" method="post" action="{%% url \'submit_form\' %%}">%s%s'
                '<button class="nb-btn is-filled is-md" type="submit"%s>%s</button></form>'
                % (hidden, ''.join(rows), self.ed('button'), esc(p.get('button') or 'فرستادن')))
        return self.shell(b, 'nb-contact', '%s%s' % (self.head_text(b), form))

    def head_text(self, b):
        parts = [self.txt(b, 'title', 'h2', 'nb-title'), self.txt(b, 'text', 'p', 'nb-sub', multi=True)]
        parts = [p for p in parts if p]
        return '<div class="nb-head">%s</div>' % ''.join(parts) if parts else ''

    def r_map(self, b):
        p = b['props']
        lat, lng = p.get('lat'), p.get('lng')
        h = p.get('map_height') or 380
        self.rule_at(None, '.b-%s .nb-map-frame' % b['id'], ['height:%dpx' % h])
        frame = ''
        link = ''
        if lat is not None and lng is not None:
            d = 0.008
            src = ('https://www.openstreetmap.org/export/embed.html?bbox=%.5f%%2C%.5f%%2C%.5f%%2C%.5f&amp;layer=mapnik&amp;marker=%.5f%%2C%.5f'
                   % (lng - d, lat - d, lng + d, lat + d, lat, lng))
            frame = '<iframe class="nb-map-frame" src="%s" title="نقشه" loading="lazy"></iframe>' % src
            link = '<a class="nb-map-link" href="https://neshan.org/maps/@%.5f,%.5f,16z" target="_blank" rel="noopener">دیدن در نقشه و مسیریابی</a>' % (lat, lng)
        else:
            self.warn(b, 'موقعیتِ نقشه هنوز وارد نشده.')
        inner = ''.join(x for x in (self.txt(b, 'title', 'h2', 'nb-title'), self.txt(b, 'address', 'p', 'nb-sub', multi=True), frame, link) if x)
        return self.shell(b, 'nb-map', inner)

    # ── دادهٔ سایت ──
    def _model(self, b):
        ref = b['props'].get('model')
        model = self.ctx.models.get(ref) if ref else None
        if not model:
            self.warn(b, 'انتخاب کن این بلوک چه چیزی را نشان بدهد.' if not ref else 'دادهٔ انتخاب‌شده دیگر در سایت نیست.')
        return ref, model

    @staticmethod
    def _pick(b, model):
        names = b['props'].get('fields') or default_fields(model)
        by = {f['name']: f for f in model['fields']}
        return [by[n] for n in names if n in by]

    @staticmethod
    def data_var(model, sort=''):
        var = 'DATA.%s.%s' % (model['app'], model['name'])
        if sort:
            desc = sort.startswith('-')
            name = sort.lstrip('-')
            if name == 'id' or any(f['name'] == name for f in model['fields']):
                var += '.by_%s%s' % (name, '_desc' if desc else '')
        return var

    @staticmethod
    def field_value(f, v, long=False):
        t = f['type']
        if f.get('choices'):
            return '{{ %s_display }}' % v
        if t == 'BooleanField':
            return '{%% if %s %%}بله{%% else %%}خیر{%% endif %%}' % v
        if t in NUM_TYPES:
            return '{{ %s|floatformat:"-2g" }}' % v
        if t == 'DateField':
            return '{{ %s|date:"Y/m/d" }}' % v
        if t == 'DateTimeField':
            return '{{ %s|date:"Y/m/d H:i" }}' % v
        if t == 'TimeField':
            return '{{ %s|time:"H:i" }}' % v
        if t == 'ManyToManyField':
            return '{%% for x in %s.all %%}{{ x }}{%% if not forloop.last %%}، {%% endif %%}{%% endfor %%}' % v
        if t == 'URLField':
            return '<a href="{{ %s }}" rel="noopener">{{ %s }}</a>' % (v, v)
        if t == 'EmailField':
            return '<a href="mailto:{{ %s }}">{{ %s }}</a>' % (v, v)
        if t == 'FileField':
            return '{%% if %s %%}<a href="{{ %s.url }}">دانلود</a>{%% endif %%}' % (v, v)
        if t in LONG_TYPES:
            return ('{{ %s|linebreaksbr }}' % v) if long else ('{{ %s|truncatechars:90 }}' % v)
        return '{{ %s }}' % v

    def r_data_list(self, b):
        p = b['props']
        ref, model = self._model(b)
        self.cols_css(b, 'nb-cards')
        if not model:
            if not self.ctx.canvas:
                return ''
            return '<div %s><div class="nb-drop-here" data-nb-ph="1">از تنظیمات انتخاب کن چه چیزی نشان داده شود</div></div>' % self.attrs(b, 'nb-data')
        fields = self._pick(b, model)
        link = p.get('link') or ''
        href = ''
        if link == 'auto':
            route = self.ctx.routes.get(ref)
            if route:
                href = "{%% url '%s' item.pk %%}" % route
            elif model['name'] == 'Product' and model['app'] == 'catalog':
                href = '{{ item.get_absolute_url }}'
        elif link and link.startswith('page:'):
            href = '%s?id={{ item.pk }}' % esc(self.link(link))
        lo, lc = ('<a href="%s">' % href, '</a>') if href else ('', '')
        image = next((f for f in fields if f['type'] == 'ImageField'), None)
        title = next((f for f in fields if f['type'] in TEXT_TYPES), None)
        parts = []
        if image:
            parts.append('{%% if item.%s %%}%s<img class="nb-card-img" src="{{ item.%s.url }}" alt="{{ item }}" loading="lazy">%s{%% endif %%}' % (image['name'], lo, image['name'], lc))
        body = []
        if title:
            body.append('<h3 class="nb-card-title">%s{{ item.%s }}%s</h3>' % (lo, title['name'], lc))
        for f in fields:
            if f in (image, title):
                continue
            var = 'item.%s' % f['name']
            val = self.field_value({**f, 'choices': False}, 'item.get_%s_display' % f['name'] if f.get('choices') else var)
            if f['type'] in LONG_TYPES:
                body.append('<p class="nb-card-text">%s</p>' % val)
            else:
                body.append('<div class="nb-card-meta"><span>%s</span><b>%s</b></div>' % (esc(f['label']), val))
        if p.get('add_to_cart') and self.ctx.has_cart and ref == 'catalog.Product':
            body.append('<form class="nb-card-cart" method="post" action="{% url \'cart_add\' item.pk %}">{% csrf_token %}'
                        '<input type="hidden" name="next" value="{{ request.path }}">'
                        '<button class="nb-btn is-filled is-sm" {% if item.stock <= 0 %}disabled{% endif %}>'
                        '{% if item.stock > 0 %}افزودن به سبد{% else %}ناموجود{% endif %}</button></form>')
        parts.append('<div class="nb-card-body">%s</div>' % ''.join(body))
        var = self.data_var(model, p.get('sort') or '')
        count = p.get('count') or 6
        tpl = ('<div class="nb-cards">{%% for item in %s|slice:":%d" %%}\n<article class="nb-card">%s</article>\n'
               '{%% empty %%}<p class="nb-empty">%s</p>{%% endfor %%}</div>') % (var, count, ''.join(parts), esc(p.get('empty') or ''))
        return '<div %s>%s</div>' % (self.attrs(b, 'nb-data'), tpl)

    def r_data_detail(self, b):
        p = b['props']
        ref, model = self._model(b)
        if not model:
            if not self.ctx.canvas:
                return ''
            return '<div %s><div class="nb-drop-here" data-nb-ph="1">از تنظیمات انتخاب کن چه چیزی نشان داده شود</div></div>' % self.attrs(b, 'nb-data')
        fields = self._pick(b, model)
        image = next((f for f in fields if f['type'] == 'ImageField'), None)
        title = next((f for f in fields if f['type'] in TEXT_TYPES), None)
        rows = []
        for f in fields:
            if f in (image, title):
                continue
            val = self.field_value({**f, 'choices': False}, 'rec.get_%s_display' % f['name'] if f.get('choices') else 'rec.%s' % f['name'], long=True)
            if f['type'] in LONG_TYPES:
                rows.append('<div class="nb-detail-text">%s</div>' % val)
            else:
                rows.append('<div class="nb-card-meta"><span>%s</span><b>%s</b></div>' % (esc(f['label']), val))
        img = ''
        if image:
            img = '{%% if rec.%s %%}<div class="nb-detail-media"><img src="{{ rec.%s.url }}" alt="{{ rec }}"></div>{%% endif %%}' % (image['name'], image['name'])
        ttl = '<h1 class="nb-detail-title">{{ rec.%s }}</h1>' % title['name'] if title else ''
        if title:
            self.headings.append((1, b))
        tpl = ('{%% with rec=%s.current %%}{%% if rec %%}<div class="nb-detail">%s<div class="nb-detail-body">%s%s</div></div>'
               '{%% else %%}<p class="nb-empty">%s</p>{%% endif %%}{%% endwith %%}') % (self.data_var(model), img, ttl, ''.join(rows), esc(p.get('empty') or ''))
        return '<div %s>%s</div>' % (self.attrs(b, 'nb-data'), tpl)

    # ── سربرگ و پابرگ ──
    def r_site_header(self, b):
        p = b['props']
        self.rule_at(None, '.b-%s .nb-logo' % b['id'], ['height:%dpx' % (p.get('logo_h') or 40)])
        brand = ''
        if p.get('logo'):
            brand += self.img(p['logo'], getattr(self.ctx.project, 'site_title', '') or 'نشانِ سایت', 'nb-logo', sizes='200px', lazy=False)
        if p.get('show_title', True) or not brand:
            brand += '<span>{{ SITE_TITLE }}</span>'
        nav = ''
        if p.get('show_menu', True):
            nav = ('<input class="nb-nav-toggle" type="checkbox" id="nb-nav-%s" aria-label="باز و بسته کردنِ منو">'
                   '<label class="nb-burger" for="nb-nav-%s" aria-hidden="true"><i></i><i></i><i></i></label>'
                   '<nav class="nb-nav" aria-label="منوی اصلی">{%% for title, href in MENU %%}'
                   '<a href="{{ href }}" class="{%% if CURRENT_PATH == href %%}on{%% endif %%}">{{ title }}</a>{%% endfor %%}</nav>') % (b['id'], b['id'])
        extra = ''
        if p.get('show_cart') and self.ctx.has_cart:
            extra += ('<a class="nb-cart" href="/cart/" aria-label="سبدِ خرید">%s{%% if cart|length %%}<span class="nb-badge">{{ cart|length }}</span>{%% endif %%}</a>'
                      % icons.svg('cart', 20))
        if p.get('btn'):
            extra += self.btn(p['btn'], p.get('btn_link'), 'nb-btn is-filled is-sm')
        cls = 'nb-header' + (' is-sticky' if p.get('sticky') else '')
        return ('<header %s>\n<div class="nb-wrap nb-header-in"><a class="nb-brand" href="/">%s</a>%s<div class="nb-header-extra">%s</div></div>\n</header>'
                % (self.attrs(b, cls), brand, nav, extra))

    def r_menu_links(self, b):
        return ('<nav %s aria-label="پیوندها">{%% for title, href in MENU %%}<a href="{{ href }}">{{ title }}</a>{%% endfor %%}</nav>'
                % self.attrs(b, 'nb-menu-links'))

    def r_copyright(self, b):
        return '<p %s>© {{ SITE_TITLE }} — <span%s>%s</span></p>' % (self.attrs(b, 'nb-copy'), self.ed('text'), esc(b['props'].get('text')))


def video_embed(url):
    u = (url or '').strip()
    if not u:
        return ''
    try:
        pr = urlparse(u)
    except ValueError:
        return ''
    host = (pr.hostname or '').lower().replace('www.', '')
    if host == 'aparat.com':
        m = re.match(r'^/(?:v|video/video/embed/videohash)/([\w-]+)', pr.path)
        return 'https://www.aparat.com/video/video/embed/videohash/%s/vt/frame' % m.group(1) if m else ''
    if host in ('youtube.com', 'm.youtube.com'):
        vid = parse_qs(pr.query).get('v', [''])[0]
        m = re.match(r'^/(?:embed|shorts)/([\w-]+)', pr.path)
        vid = vid or (m.group(1) if m else '')
        return 'https://www.youtube-nocookie.com/embed/%s' % vid if re.fullmatch(r'[\w-]{5,20}', vid or '') else ''
    if host == 'youtu.be':
        vid = pr.path.strip('/')
        return 'https://www.youtube-nocookie.com/embed/%s' % vid if re.fullmatch(r'[\w-]{5,20}', vid) else ''
    return ''


_TPL_RE = re.compile(r'{#.*?#}|{%.*?%}', re.S)
_VAR_RE = re.compile(r'{{.*?}}', re.S)
_SCRIPT_RE = re.compile(r'<script\b[^>]*>.*?</script\s*>|<script\b[^>]*/?>', re.I | re.S)
_ON_RE = re.compile(r"""\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_JS_URL_RE = re.compile(r"""(href|src)\s*=\s*(["']?)\s*javascript:[^"'\s>]*\2""", re.I)


def canvas_safe(code):
    """کدِ سفارشی روی بوم: تگِ جنگو و اسکریپت اجرا نمی‌شود؛ فقط ظاهرش دیده می‌شود."""
    out = _TPL_RE.sub('', code or '')
    out = _VAR_RE.sub('…', out)
    out = _SCRIPT_RE.sub('', out)
    out = _ON_RE.sub('', out)
    out = _JS_URL_RE.sub(r'\1="#"', out)
    return out


# ─────────────────────────────── وارسیِ دسترس‌پذیری
def _lum(hexv):
    h = hexv.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + .05) / (lo + .05)


def _hex_of(v, theme):
    if not v:
        return None
    if v.startswith('t:'):
        return {'white': '#ffffff', 'black': '#000000'}.get(v[2:]) or theme.get(v[2:])
    return v[:7] if len(v) >= 7 else v


def check_contrast(blocks, r, bg=None, fg=None):
    theme = r.ctx.theme or {}
    for b in blocks or []:
        d = (b.get('style') or {}).get('d') or {}
        here_bg = _hex_of(d.get('bg'), theme) or bg
        here_fg = _hex_of(d.get('color'), theme) or fg
        if d.get('bgimg'):
            here_bg = None
        if b['type'] in ('heading', 'text', 'section', 'column') and here_fg and here_bg:
            try:
                if contrast(here_fg, here_bg) < 3:
                    r.warn(b, 'رنگِ این متن با پس‌زمینه‌اش به‌سختی خوانده می‌شود.')
            except (ValueError, IndexError):
                pass
        check_contrast(b.get('children'), r, here_bg, here_fg)


def check_headings(r):
    levels = [lv for lv, _ in r.headings]
    h1 = [b for lv, b in r.headings if lv == 1]
    if len(h1) > 1:
        r.warn(h1[1], 'این صفحه بیش از یک تیترِ اصلی دارد؛ بهتر است فقط یکی باشد.')
    prev = None
    for lv, b in r.headings:
        if prev is not None and lv > prev + 1:
            r.warn(b, 'درجهٔ این تیتر پله جا انداخته؛ برای گوگل و نابینایان بهتر است پشتِ سرِ هم باشد.')
        prev = lv
    return levels


# ─────────────────────────────── ورودی‌های اصلی
class Rendered:
    def __init__(self, html, css, warnings, uses_form, parts):
        self.html = html
        self.css = css
        self.warnings = warnings
        self.uses_form = uses_form
        self.parts = parts            # [(id, html)] بلوک‌های سطحِ بالا؛ برای به‌روزرسانیِ تکه‌ایِ بوم


def render_doc(doc, ctx):
    r = Renderer(ctx)
    parts = []
    for b in (doc or {}).get('blocks') or []:
        parts.append((b['id'], r.block(b)))
    check_contrast((doc or {}).get('blocks'), r)
    if ctx.target == 'page':
        check_headings(r)
    html = '\n\n'.join(h for _, h in parts if h)
    gen = r.css()
    return Rendered(html, gen, r.warnings, r.uses_form, parts)


def page_css(gen_css, extra=''):
    """CSSِ صفحه: بخشِ تولیدی بینِ دو نشانه + CSSِ دستی/AI که باید بماند."""
    out = ''
    if gen_css.strip():
        out = '%s\n%s\n%s\n' % (ZONE_START, gen_css.strip(), ZONE_END)
    if (extra or '').strip():
        out += ('\n' if out else '') + extra.strip() + '\n'
    return out


def split_page_css(css):
    """⇒ (بخشِ تولیدی، باقیِ CSS)"""
    css = css or ''
    i, j = css.find(ZONE_START), css.find(ZONE_END)
    if i < 0 or j < i:
        return '', css.strip()
    return css[i + len(ZONE_START):j].strip(), (css[:i] + css[j + len(ZONE_END):]).strip()


def has_block(doc, btype):
    return any(b['type'] == btype for b in walk((doc or {}).get('blocks')))


__all__ = ['Ctx', 'Renderer', 'Rendered', 'build_ctx', 'render_doc', 'page_css', 'split_page_css', 'model_index', 'default_fields',
           'CONTAINERS', 'ZONE_START', 'ZONE_END', 'has_block', 'canvas_safe', 'video_embed', 'contrast']
