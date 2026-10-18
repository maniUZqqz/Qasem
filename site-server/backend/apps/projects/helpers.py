# -*- coding: utf-8 -*-
"""منطقِ مشترکِ APIِ استودیو.

این‌جا سه چیز هست:
  · `FormData` — ورودیِ JSON یا فرم را با همان رابطِ `request.POST` ِ قدیمی
    (get / getlist / in) می‌دهد تا منطقِ فرم‌های رابطِ HTML ِ قبلی عیناً کار کند
    (بولی‌ها 'on'/'' می‌شوند، عددها رشته).
  · کمک‌تابع‌هایی که از views.py ِ قدیمی آمده‌اند: اعمالِ فرمِ فیلد و نشانی،
    دادهٔ نمودارِ ER، خواندنِ فایل، درختِ فایل‌ها، هدر/فوتر/CSSِ مؤثر.
  · سریال‌سازیِ صریحِ مدل‌ها (هیچ مسیرِ مطلقی جز آن‌چه رابطِ قدیمی نشان می‌داد
    بیرون نمی‌رود).
"""
import os
import re

from django.http import Http404

from apps.code_generation import generator
from . import validators as V
from .models import App, Field, Model, Route, View

MAX_PREVIEW_BYTES = 200_000
READ_ONLY_MSG = ('این بخش مالِ پروژهٔ واردشده است و فقط نمایش داده می‌شود؛ '
                 'برای افزودنِ امکانِ تازه، یک اپِ تازه بساز.')
SKIP_DIRS = {'__pycache__', 'venv', '.venv', '.git', 'staticfiles', 'media', 'node_modules'}


# ──────────────────────────────────────────────── ورودی
class FormData:
    """`request.data` (dict ِ JSON یا QueryDict ِ فرم) ⇒ رابطِ request.POST."""

    def __init__(self, data):
        self.data = data if data is not None else {}

    def __contains__(self, key):
        return key in self.data

    @staticmethod
    def _s(v):
        if v is None:
            return ''
        if v is True:
            return 'on'
        if v is False:
            return ''
        if isinstance(v, (list, tuple)):
            return FormData._s(v[0]) if v else ''
        return str(v)

    def get(self, key, default=None):
        if key not in self.data:
            return default
        return self._s(self.data.get(key))

    def getlist(self, key):
        if hasattr(self.data, 'getlist'):
            return [self._s(x) for x in self.data.getlist(key)]
        v = self.data.get(key)
        if v is None:
            return []
        if isinstance(v, (list, tuple)):
            return [self._s(x) for x in v]
        return [self._s(v)]


def _dt(v):
    return v.isoformat() if v else None


def preview_url(request, port):
    host = request.get_host().split(':')[0]
    return 'http://%s:%d/' % (host, port)


def shared_parts(p):
    """هدر/فوتر/CSSِ مؤثرِ این پروژه — برای پیش‌نمایشِ سمتِ مرورگر."""
    parts = {s.kind: s.content for s in p.shared_parts.all()}
    return {
        'base_css': parts.get('base_css') or generator.BASE_CSS % {'brand': p.brand_color},
        'header': parts.get('header') or generator.DEFAULT_HEADER,
        'footer': parts.get('footer') or generator.DEFAULT_FOOTER,
    }


# ──────────────────────────────────────────────── فایل‌ها
def read_text(p, rel):
    root = str(p.path)
    target = os.path.normpath(os.path.join(root, rel))
    # با جداکننده، مثلِ file_content؛ وگرنه «proj2/» کنارِ «proj/» هم قبول می‌شد
    if not target.startswith(root + os.sep) or not os.path.isfile(target):
        return ''
    with open(target, encoding='utf-8', errors='replace') as fh:
        return fh.read()[:MAX_PREVIEW_BYTES]


def file_count(p):
    n = 0
    if os.path.isdir(str(p.path)):
        for dp, dn, fn in os.walk(str(p.path)):
            dn[:] = [d for d in dn if d not in ('__pycache__', 'venv', '.venv', 'staticfiles', '.git', 'media')]
            n += sum(1 for f in fn if not f.endswith('.pyc') and not f.startswith(('.preview', '.studio-')))
    return n


def file_tree(p):
    """⇒ (tree, groups) — tree فهرستِ مسیرهای نسبی، groups به تفکیکِ پوشه."""
    root = str(p.path)
    tree = []
    if os.path.isdir(root):
        for dp, dn, fn in os.walk(root):
            dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
            for name in sorted(fn):
                if name.endswith(('.pyc', '.sqlite3')) or name.startswith(('.preview', '.studio-')):
                    continue
                tree.append(os.path.relpath(os.path.join(dp, name), root).replace('\\', '/'))
                if len(tree) > 3000:
                    break
    tree.sort()
    groups = []
    for t in tree:
        d = os.path.dirname(t)
        if not groups or groups[-1][0] != d:
            groups.append([d, []])
        groups[-1][1].append({'path': t, 'name': os.path.basename(t)})
    return tree, groups


def file_content(p, rel):
    """⇒ (content, custom_zone)؛ بیرون از پوشهٔ پروژه ⇒ 404."""
    root = str(p.path)
    target = os.path.normpath(os.path.join(root, rel))
    if not target.startswith(root + os.sep) or not os.path.isfile(target):
        raise Http404('فایل پیدا نشد.')
    if os.path.getsize(target) > MAX_PREVIEW_BYTES:
        content = '— فایل بزرگ‌تر از حدِ نمایش است —'
    else:
        try:
            with open(target, encoding='utf-8') as fh:
                content = fh.read()
        except UnicodeDecodeError:
            content = '— فایلِ دودویی —'
    return content, generator.CUSTOM_MARK in content


# ──────────────────────────────────────────────── بک‌اند
def er_data(p):
    """داده‌ی نمودارِ مدل‌ها و رابطه‌ها."""
    models = []
    for a in p.apps.prefetch_related('models__fields__related_model'):
        for m in a.models.all():
            models.append({
                'id': m.id, 'app': a.name, 'name': m.name, 'fa': m.verbose_name_fa,
                'managed': m.managed and a.managed,
                'fields': [{'name': f.name, 'type': f.field_type, 'fa': f.verbose_name_fa,
                            'to': f.related_model_id, 'ref': f.related_ref if not f.related_model_id else ''}
                           for f in m.fields.all()],
            })
    return models


def apply_field_post(fld, post, project):
    """فرم ⇒ فیلد (هم برای افزودن هم ویرایش). ValueError با پیامِ فارسی."""
    ftype = post.get('field_type') or 'CharField'
    if ftype not in dict(Field.TYPES) or ftype == 'custom':
        raise ValueError('نوعِ فیلد ناشناخته است.')
    fld.name = V.field_name(post.get('name'))
    fld.verbose_name_fa = (post.get('fa') or '').strip()
    fld.field_type = ftype
    fld.help_text_fa = (post.get('help') or '').strip()
    ml = (post.get('max_length') or '').strip()
    fld.max_length = int(ml) if ml.isdigit() and int(ml) > 0 else None
    md, dp = (post.get('max_digits') or '').strip(), (post.get('decimal_places') or '').strip()
    fld.max_digits = int(md) if md.isdigit() else None
    fld.decimal_places = int(dp) if dp.isdigit() else None
    if fld.max_digits is not None and fld.decimal_places is not None and fld.decimal_places > fld.max_digits:
        raise ValueError('رقمِ اعشار نمی‌تواند از تعدادِ رقم بیشتر باشد.')
    fld.null = post.get('null') == 'on'
    fld.blank = post.get('blank') == 'on'
    fld.unique = post.get('unique') == 'on'
    fld.db_index = post.get('db_index') == 'on'
    date_mode = post.get('date_mode') or ''
    fld.auto_now_add = ftype in ('DateField', 'DateTimeField', 'TimeField') and date_mode == 'add'
    fld.auto_now = ftype in ('DateField', 'DateTimeField', 'TimeField') and date_mode == 'now'
    fld.default = V.field_default(post.get('default'), ftype) if not (fld.auto_now or fld.auto_now_add) else ''
    choices = []
    for line in (post.get('choices') or '').splitlines():
        line = line.strip()
        if not line:
            continue
        k, _, v = line.partition('=')
        if not k.strip():
            raise ValueError('گزینه‌ها: هر خط «مقدار=برچسب».')
        choices.append('%s=%s' % (k.strip(), (v or k).strip()))
    fld.choices = '\n'.join(choices) if ftype in ('CharField', 'IntegerField', 'PositiveIntegerField') else ''
    if ftype in Field.RELATIONAL:
        target = post.get('related_model') or ''
        fld.related_model = None
        fld.related_ref = ''
        if target == '__user__':
            fld.related_ref = 'settings.AUTH_USER_MODEL'
        elif target.isdigit():
            fld.related_model = Model.objects.filter(pk=int(target), app__project=project).first()
        if fld.related_model is None and not fld.related_ref:
            raise ValueError('برای فیلدِ رابطه‌ای باید «مدلِ مقصد» را انتخاب کنی.')
        fld.on_delete = post.get('on_delete') if post.get('on_delete') in dict(Field.ON_DELETE) else 'CASCADE'
        if fld.on_delete == 'SET_NULL':
            fld.null = True
        if ftype == 'ManyToManyField':
            fld.null = False                       # برای M2M بی‌معنی است و هشدار می‌دهد
            fld.blank = True if post.get('blank') == 'on' else fld.blank
        rn = (post.get('related_name') or '').strip()
        if rn and not re.fullmatch(r'[a-z_][a-z0-9_]*', rn):
            raise ValueError('نامِ برگشتی باید انگلیسیِ کوچک باشد.')
        fld.related_name = rn
    else:
        fld.related_model = None
        fld.related_ref = ''
        fld.related_name = ''
    if ftype == 'SlugField' and not fld.max_length:
        fld.max_length = 200
    return fld


def apply_route_post(route, post, p):
    app_id = post.get('app') or ''
    route.app = App.objects.filter(pk=int(app_id), project=p, managed=True).first() if app_id.isdigit() else None
    route.pattern = V.url_pattern(post.get('pattern'))
    route.name = V.url_name(post.get('name'))
    view_id = post.get('view') or ''
    route.view = View.objects.filter(pk=int(view_id), app__project=p).first() if view_id.isdigit() else None
    route.view_text = (post.get('view_text') or '').strip()
    if route.view is None and not route.view_text:
        raise ValueError('یک ویو انتخاب کن (یا ویوی متنی بنویس).')
    if route.view is not None and route.app is not None and route.view.app_id != route.app_id:
        raise ValueError('ویوی انتخاب‌شده مالِ اپِ دیگری است؛ یا اپِ همان ویو را انتخاب کن یا «ریشه».')
    if route.name:
        clash = Route.objects.filter(project=p, name=route.name).exclude(pk=route.pk)
        if clash.exists() or route.name in {r['name'] for r in generator.effective_routes(p)
                                            if r.get('source') in ('core', 'cart', 'page')}:
            raise ValueError('نامِ نشانیِ «%s» تکراری است.' % route.name)
    return route


def safe_view_code(v):
    try:
        return generator._view_code(v, generator._route_names(v.app))
    except generator.GenerationError as exc:
        return '# %s' % exc


def route_rows(p, base=''):
    """نقشهٔ کاملِ نشانی‌ها (effective_routes) به شکلِ JSON."""
    rows = []
    for r in generator.effective_routes(p):
        route = r.get('route')
        page = r.get('page')
        rows.append({
            'pattern': r['pattern'], 'name': r.get('name') or '', 'view': r.get('view') or '',
            'source': r['source'], 'editable': bool(r.get('editable')),
            'live': (base + r['pattern']) if base and '<' not in r['pattern'] else '',
            'page_id': page.id if page is not None else None,
            'route_id': route.id if route is not None else None,
            'route_view_id': route.view_id if route is not None else None,
            'route_managed': route.managed if route is not None else None,
        })
    return rows


# ──────────────────────────────────────────────── سریال‌سازی
def project_json(p, detail=False):
    d = {
        'id': p.id, 'name': p.name, 'slug': p.slug, 'description': p.description,
        'status': p.status, 'status_display': p.get_status_display(),
        'last_error': p.last_error, 'source': p.source, 'is_imported': p.is_imported,
        'brand_color': p.brand_color, 'site_title': p.site_title,
        'generated_at': _dt(p.generated_at), 'created_at': _dt(p.created_at), 'updated_at': _dt(p.updated_at),
        'exists_on_disk': p.exists_on_disk, 'settings_module_name': p.settings_module_name,
    }
    if detail:
        d.update({
            'language_code': p.language_code, 'time_zone': p.time_zone, 'allowed_hosts': p.allowed_hosts,
            'extra_apps': p.extra_apps, 'extra_requirements': p.extra_requirements,
            'custom_settings': p.custom_settings, 'settings_module': p.settings_module,
            'urls_module': p.urls_module, 'apps_dir': p.apps_dir,
            # همان چیزی که «نمای کلی» قدیمی نشان می‌داد
            'path': str(p.path),
        })
    return d


def app_json(a, models=False, views=False, routes=False, counts=False):
    d = {
        'id': a.id, 'name': a.name, 'verbose_name_fa': a.verbose_name_fa, 'description': a.description,
        'is_core': a.is_core, 'managed': a.managed, 'path': a.path, 'url_prefix': a.url_prefix,
        'effective_prefix': a.effective_prefix, 'dir': a.dir, 'order': a.order,
    }
    if counts:
        d['model_count'] = a.models.count()
        d['view_count'] = a.views.count()
        d['route_count'] = a.routes.count()
    if models:
        d['models'] = [model_json(m, fields=True) for m in a.models.all()]
    if views:
        d['views'] = [view_json(v) for v in a.views.all()]
    if routes:
        d['routes'] = [route_json(r) for r in a.routes.all()]
    return d


def model_option(m):
    return {'id': m.id, 'app_id': m.app_id, 'app_name': m.app.name, 'name': m.name,
            'verbose_name_fa': m.verbose_name_fa, 'label': '%s.%s' % (m.app.name, m.name)}


def model_json(m, fields=False, views=False):
    d = {
        'id': m.id, 'app': m.app_id, 'app_name': m.app.name, 'name': m.name, 'label': '%s.%s' % (m.app.name, m.name),
        'verbose_name_fa': m.verbose_name_fa, 'verbose_plural_fa': m.verbose_plural_fa,
        'has_str': m.has_str, 'str_field': m.str_field, 'ordering': m.ordering, 'in_admin': m.in_admin,
        'admin_list_display': m.admin_list_display, 'admin_search_fields': m.admin_search_fields,
        'admin_list_filter': m.admin_list_filter,
        'list_display': [x.strip() for x in m.admin_list_display.split(',') if x.strip()],
        'search_fields': [x.strip() for x in m.admin_search_fields.split(',') if x.strip()],
        'list_filter': [x.strip() for x in m.admin_list_filter.split(',') if x.strip()],
        'managed': m.managed, 'raw_code': m.raw_code, 'order': m.order, 'snake': m.snake,
        'field_count': len(m.fields.all()),
    }
    if fields:
        d['fields'] = [field_json(f) for f in m.fields.all()]
    if views:
        d['views'] = [view_json(v) for v in m.views.all()]
    return d


def field_json(f):
    rel = ''
    if f.related_model_id:
        rel = '%s.%s' % (f.related_model.app.name, f.related_model.name)
    return {
        'id': f.id, 'model': f.model_id, 'name': f.name, 'verbose_name_fa': f.verbose_name_fa,
        'field_type': f.field_type, 'field_type_display': f.get_field_type_display(),
        'max_length': f.max_length, 'max_digits': f.max_digits, 'decimal_places': f.decimal_places,
        'null': f.null, 'blank': f.blank, 'unique': f.unique, 'db_index': f.db_index,
        'auto_now': f.auto_now, 'auto_now_add': f.auto_now_add, 'default': f.default,
        'choices': f.choices, 'help_text_fa': f.help_text_fa,
        'related_model': f.related_model_id, 'related_model_label': rel, 'related_ref': f.related_ref,
        'on_delete': f.on_delete, 'related_name': f.related_name, 'raw_code': f.raw_code, 'order': f.order,
        'is_relational': f.is_relational, 'is_textual': f.is_textual, 'target_label': f.target_label,
    }


def view_option(v):
    return {'id': v.id, 'app_id': v.app_id, 'app_name': v.app.name, 'name': v.name,
            'kind_display': v.get_kind_display(), 'label': '%s.%s' % (v.app.name, v.name)}


def view_json(v, with_routes=True):
    d = {
        'id': v.id, 'app': v.app_id, 'app_name': v.app.name, 'name': v.name, 'label': '%s.%s' % (v.app.name, v.name),
        'kind': v.kind, 'kind_display': v.get_kind_display(),
        'model': v.model_id, 'model_name': v.model.name if v.model_id else '',
        'description': v.description, 'template_body': v.template_body, 'css': v.css,
        'paginate_by': v.paginate_by, 'ordering': v.ordering, 'form_fields': v.form_fields,
        'field_list': v.field_list, 'login_required': v.login_required,
        'success_url_name': v.success_url_name, 'context_object_name': v.context_object_name,
        'custom_code': v.custom_code, 'managed': v.managed, 'order': v.order,
        'class_name': v.class_name, 'template_name': v.template_name, 'needs_template': v.needs_template,
    }
    if with_routes:
        d['routes'] = [{'id': r.id, 'pattern': r.pattern, 'full_pattern': r.full_pattern, 'name': r.name}
                       for r in v.routes.all()]
    return d


def route_json(r):
    return {
        'id': r.id, 'app': r.app_id, 'app_name': r.app.name if r.app_id else '',
        'pattern': r.pattern, 'full_pattern': r.full_pattern, 'name': r.name,
        'view': r.view_id, 'view_label': ('%s.%s' % (r.view.app.name, r.view.name)) if r.view_id else '',
        'view_text': r.view_text, 'managed': r.managed, 'order': r.order,
        'target': r.target, 'code': r.code if r.app_id else r.root_code,
    }


def page_json(pg, body=False):
    d = {
        'id': pg.id, 'title': pg.title, 'slug': pg.slug, 'kind': pg.kind, 'kind_display': pg.get_kind_display(),
        'in_menu': pg.in_menu, 'file_path': pg.file_path, 'order': pg.order, 'is_imported': pg.is_imported,
        'template_path': pg.template_path, 'css_name': pg.css_name, 'view_name': pg.view_name,
        'url_pattern': pg.url_pattern, 'body_length': len(pg.body_html or ''), 'has_css': bool(pg.css),
    }
    if body:
        d['body_html'] = pg.body_html
        d['css'] = pg.css
    return d


def shared_json(s):
    return {'kind': s.kind, 'kind_display': s.get_kind_display(), 'content': s.content}


def build_json(b):
    return {'id': b.id, 'ok': b.ok, 'summary': b.summary, 'detail': b.detail,
            'files_written': b.files_written, 'created_at': _dt(b.created_at)}


def proposal_json(pr):
    return {
        'id': pr.id, 'task': pr.task, 'task_display': pr.get_task_display(), 'title': pr.title,
        'prompt_text': pr.prompt_text, 'summary': pr.summary, 'status': pr.status,
        'status_display': pr.get_status_display(), 'error': pr.error, 'provider_model': pr.provider_model,
        'calls': pr.calls, 'created_at': _dt(pr.created_at), 'applied_at': _dt(pr.applied_at),
        'is_running': pr.is_running, 'can_apply': pr.can_apply, 'can_revert': pr.can_revert,
        'change_count': pr.changes.count(),
    }


def change_json(ch):
    return {
        'id': ch.id, 'target': ch.target, 'target_display': ch.get_target_display(), 'label': ch.label,
        'page': ch.page_id, 'view': ch.view_id, 'old': ch.old_content, 'new': ch.new_content,
        'diff': ch.diff_text, 'valid': ch.valid, 'issues': [x for x in (ch.issues or '').splitlines() if x.strip()],
        'order': ch.order, 'is_css': ch.is_css, 'is_html': ch.is_html, 'unchanged': ch.unchanged,
    }


__all__ = [
    'FormData', 'MAX_PREVIEW_BYTES', 'READ_ONLY_MSG', 'preview_url', 'shared_parts', 'read_text',
    'file_count', 'file_tree', 'file_content', 'er_data', 'apply_field_post', 'apply_route_post',
    'safe_view_code', 'route_rows', 'project_json', 'app_json', 'model_option', 'model_json',
    'field_json', 'view_option', 'view_json', 'route_json', 'page_json', 'shared_json', 'build_json',
    'proposal_json', 'change_json',
]
