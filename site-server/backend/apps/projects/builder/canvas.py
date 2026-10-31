# -*- coding: utf-8 -*-
"""ساختِ پیش‌نمایشِ بوم با همان رندرکننده.

متنِ قالبی که render.py می‌سازد این‌جا با یک موتورِ جنگوی جدا و دادهٔ بوم اجرا می‌شود:
ردیف‌های واقعی از دیتابیسِ پروژه (فقط‌خواندنی) اگر باشد، وگرنه دادهٔ نمونه‌ای از روی تعریفِ مدل.
"""
import datetime
import decimal
import os
import sqlite3

from django.template import Context, Engine

from apps.code_generation import generator
from . import genhook, theme as theme_mod
from .render import PLACEHOLDER_IMG, Renderer, build_ctx, canvas_safe, render_doc

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = Engine(libraries={'static': 'apps.projects.builder.canvas_tags'},
                         builtins=['apps.projects.builder.canvas_tags'], autoescape=True)
    return _engine


class Img:
    def __init__(self, url):
        self.url = url

    def __bool__(self):
        return bool(self.url)

    def __str__(self):
        return self.url


class Many:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows


class Row:
    def __init__(self, label, values):
        self.__dict__.update(values)
        self.__dict__['_label'] = label

    def __str__(self):
        return str(self.__dict__.get('_label') or '')

    def __getattr__(self, name):
        if name.startswith('get_') and name.endswith('_display'):
            return self.__dict__.get(name[4:-8], '')
        if name == 'get_absolute_url':
            return '#'
        if name == 'pk':
            return self.__dict__.get('id', 1)
        return ''


class Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, key):
        if isinstance(key, (slice, int)):
            return self.rows[key]
        raise TypeError(key)

    def __getattr__(self, name):
        if name.startswith('by_'):
            field = name[3:]
            desc = field.endswith('_desc')
            field = field[:-5] if desc else field
            try:
                return Query(sorted(self.rows, key=lambda r: (r.__dict__.get(field) is None, r.__dict__.get(field) or 0), reverse=desc))
            except TypeError:
                return self
        raise AttributeError(name)

    @property
    def current(self):
        return self.rows[0] if self.rows else None


SAMPLE_TEXT = 'این متنِ نمونه است و بعد از ثبتِ داده، متنِ واقعی این‌جا می‌آید.'


def sample_rows(model, n=12):
    rows = []
    for i in range(1, n + 1):
        vals = {'id': i}
        label = '%s نمونهٔ %d' % (model.get('singular') or model['label'], i)
        first = True
        for f in model['fields']:
            t, name = f['type'], f['name']
            if t == 'ImageField':
                vals[name] = Img(PLACEHOLDER_IMG)
            elif t == 'FileField':
                vals[name] = Img('#')
            elif t in ('CharField',):
                vals[name] = label if first else '%s %d' % (f['label'], i)
                first = False
            elif t == 'TextField':
                vals[name] = SAMPLE_TEXT
            elif t in ('EmailField',):
                vals[name] = 'name@example.com'
            elif t == 'URLField':
                vals[name] = 'https://example.com'
            elif t in ('DecimalField', 'FloatField'):
                vals[name] = 150000 * i
            elif t in ('IntegerField', 'PositiveIntegerField', 'BigIntegerField'):
                vals[name] = i * 3
            elif t == 'BooleanField':
                vals[name] = True
            elif t == 'DateField':
                vals[name] = datetime.date(2026, 10, min(i, 28))
            elif t == 'DateTimeField':
                vals[name] = datetime.datetime(2026, 10, min(i, 28), 10, 30)
            elif t == 'TimeField':
                vals[name] = datetime.time(10, 30)
            elif t == 'ManyToManyField':
                vals[name] = Many()
            elif t in ('ForeignKey', 'OneToOneField'):
                vals[name] = 'مرتبط %d' % i
            else:
                vals[name] = ''
        rows.append(Row(label, vals))
    return rows


def real_rows(project, model):
    """ردیف‌های واقعیِ پروژهٔ تولیدشده، فقط‌خواندنی؛ هر خطایی ⇐ None تا نمونه نشان داده شود."""
    db = os.path.join(str(project.path), 'db.sqlite3')
    if not os.path.isfile(db):
        return None
    table = '%s_%s' % (model['app'], model['name'].lower())
    try:
        conn = sqlite3.connect('file:%s?mode=ro' % db, uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute('SELECT * FROM "%s" ORDER BY id DESC LIMIT 60' % table.replace('"', '')).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    out = []
    for raw in rows:
        keys = raw.keys()
        if 'is_active' in keys and not raw['is_active']:
            continue
        vals = {'id': raw['id'] if 'id' in keys else 0}
        label = ''
        for f in model['fields']:
            name, t = f['name'], f['type']
            col = name + '_id' if t in ('ForeignKey', 'OneToOneField') else name
            v = raw[col] if col in keys else None
            if t in ('ImageField', 'FileField'):
                v = Img('/api/v1/studio/builder-media/%s/u/%s' % (project.slug, v) if v else '')
            elif t in ('DecimalField',):
                try:
                    v = decimal.Decimal(str(v)) if v is not None else None
                except decimal.InvalidOperation:
                    v = None
            elif t == 'DateField' and v:
                try:
                    v = datetime.date.fromisoformat(str(v)[:10])
                except ValueError:
                    pass
            elif t == 'DateTimeField' and v:
                try:
                    v = datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00')[:19])
                except ValueError:
                    pass
            elif t == 'BooleanField':
                v = bool(v)
            elif t == 'ManyToManyField':
                v = Many()
            elif t in ('ForeignKey', 'OneToOneField'):
                v = '#%s' % v if v else ''
            vals[name] = v
            if not label and t == 'CharField' and v:
                label = str(v)
        out.append(Row(label or '#%s' % vals['id'], vals))
    return out


def data_context(project, ctx):
    """⇒ (DATA, مدل‌هایی که نمونه نشان داده می‌شوند)"""
    data, samples = {}, []
    for ref, model in ctx.models.items():
        rows = real_rows(project, model)
        if not rows:
            rows = sample_rows(model)
            samples.append(ref)
        data.setdefault(model['app'], {})[model['name']] = Query(rows)
    return data, samples


def render_template(text, context):
    return engine().from_string(text).render(Context(context, autoescape=True))


def _chrome_html(project, target, theme, base_ctx, context):
    """سربرگ یا پابرگِ بوم: اگر طراحی دارد از سند، وگرنه کدِ موجود یا پیش‌فرض."""
    from apps.projects.models import Design, SharedPart
    d = Design.objects.filter(project=project, target=target).first()
    css = ''
    if d and d.draft:
        c = build_ctx(project, canvas=False, target=target, theme=theme['colors'])
        c.canvas_urls = True
        rendered = render_doc(d.draft, _canvas_urls(c))
        text, css = rendered.html, rendered.css
        if target == 'footer':
            text = '<footer class="nb-footer">%s</footer>' % text
    else:
        part = SharedPart.objects.filter(project=project, kind=target).first()
        text = (part.content if part else '') or ''
        text = text.strip() or (generator.DEFAULT_HEADER if target == 'header' else generator.DEFAULT_FOOTER)
    try:
        html = render_template(text, context)
    except Exception:  # noqa — کدِ دستی ممکن است هر تگی داشته باشد
        html = canvas_safe(text)
    return html, css


def _canvas_urls(ctx):
    """رندرِ سربرگ/پابرگ در بوم: بی‌نشانگرِ انتخاب، ولی نشانیِ تصویر مستقیم."""
    ctx.canvas = True
    ctx.chrome_only = True
    return ctx


def render_canvas(project, target, page, doc, theme, menu):
    """⇒ JSONِ بوم: css، تکه‌های سطحِ بالا، سربرگ و پابرگ، هشدارها."""
    from apps.projects.models import Page, SharedPart
    ctx = build_ctx(project, canvas=True, target=target, theme=theme['colors'])
    rendered = render_doc(doc, ctx)
    pages = {p.pk: p for p in Page.objects.filter(project=project)}
    path = ('/%s/' % page.slug if page.slug else '/') if page is not None else '/'
    data, samples = data_context(project, ctx)
    context = {
        'DATA': data, 'MENU': genhook.items_from(menu, pages), 'SITE_TITLE': project.site_title or project.name,
        'CURRENT_PATH': path, 'cart': [], 'request': {'path': path}, 'products': [], 'categories': [], 'page_title': page.title if page else '',
    }
    parts = []
    for bid, text in rendered.parts:
        try:
            parts.append({'id': bid, 'html': render_template(text, context)})
        except Exception as exc:  # noqa
            parts.append({'id': bid, 'html': '<div data-bid="%s" class="nb-drop-here" data-nb-ph="1">این بخش نمایش داده نشد: %s</div>' % (bid, str(exc)[:120].replace('<', ' '))})

    part = SharedPart.objects.filter(project=project, kind='base_css').first()
    base = (part.content if part else '') or (generator.BASE_CSS % {'brand': project.brand_color})
    base = theme_mod.apply_zone(base, theme)
    chrome_css = ''
    header_html = footer_html = ''
    if target == 'page':
        header_html, c1 = _chrome_html(project, 'header', theme, ctx, context)
        footer_html, c2 = _chrome_html(project, 'footer', theme, ctx, context)
        chrome_css = '\n'.join(x for x in (c1, c2) if x)
    elif target == 'footer':
        header_html, c1 = _chrome_html(project, 'header', theme, ctx, context)
        chrome_css = c1
    elif target == 'header':
        footer_html, c2 = _chrome_html(project, 'footer', theme, ctx, context)
        chrome_css = c2
    prefix = '/api/v1/studio/builder-fonts/'
    extra = (doc or {}).get('extra_css') or ''
    return {
        'base_css': base + '\n' + theme_mod.blocks_css(theme, prefix, chrome_css),
        'page_css': rendered.css + ('\n' + extra if extra else ''),
        'parts': parts, 'header': header_html, 'footer': footer_html,
        'warnings': rendered.warnings, 'sample_models': samples, 'title': project.site_title or project.name,
    }


__all__ = ['render_canvas', 'render_template', 'data_context', 'sample_rows', 'real_rows', 'Renderer']
