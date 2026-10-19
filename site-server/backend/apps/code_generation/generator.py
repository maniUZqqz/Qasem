# -*- coding: utf-8 -*-
"""ساختِ پروژهٔ جنگو از روی تعریفِ استودیو.

قراردادهای ثابت (از idea.md §۳ و §۶):
  · پوشهٔ تنظیمات: config/
  · اپ‌ها زیرِ apps/
  · هر اپ: models / admin / views / urls / forms (+ templates/<app>/ برای ویوهای استاندارد)
  · قالب‌ها: templates/base.html + components/{header,footer}.html + pages/*.html
  · هر صفحه CSSِ خودش را در static/css/pages/<page>.css دارد
  · AI/کاربر فقط «بدنهٔ» یک صفحه را عوض می‌کند، نه هدر و فوتر را

⚠ هیچ فایلی بیرون از پوشهٔ همان پروژه نوشته نمی‌شود (`_safe_write`).
⚠ «ناحیهٔ دستی» (idea.md §۵.۳): فایل‌های پایتونی یک خطِ نشانه دارند؛ هر چه
   زیرِ آن باشد در تولیدهای بعدی دست‌نخورده می‌ماند. پس برنامه‌نویس می‌تواند
   کدِ خودش را زیرِ کدِ تولیدی بنویسد و هیچ‌وقت از بین نرود.
⚠ پروژهٔ واردشده (idea.md §۸): فقط اپ‌های «managed» و قالب‌های ویرایش‌شده
   نوشته می‌شوند؛ settings/urls ِ خودش فقط با یک خطِ include/اپ وصله می‌خورند.
"""
import hashlib
import os
import re

from django.utils import timezone

from .tpl import (APP_CONFIG_TPL, BASE_CSS, BASE_TPL, CART_CP, CART_FORMS, CART_PY,
                  CART_URLS, CART_VIEWS, CONTEXT_TPL, DEFAULT_BODIES, DEFAULT_BODY,
                  DEFAULT_FOOTER, DEFAULT_HEADER, ENSURE_ADMIN_TPL, MANAGE_TPL, ORDER_DONE_TPL,
                  PAGE_TPL, PRODUCT_CARD_TPL, PRODUCT_EXTRAS, README_TPL, RUN_BAT_TPL,
                  RUN_README_TPL, RUN_SH_TPL, WSGI_TPL)

__all__ = ['GenerationError', 'ProjectGenerator', 'field_code', 'model_code', 'app_files',
           'models_module', 'sha', 'SETTINGS_TPL',
           'default_template_body', 'effective_routes', 'url_names', 'CUSTOM_MARK', 'runner_files',
           'BASE_CSS', 'DEFAULT_HEADER', 'DEFAULT_FOOTER', 'DEFAULT_BODIES']

FIELD_DEFAULT_ARGS = {
    'CharField': {'max_length': 200},
    'SlugField': {'max_length': 200},
    'EmailField': {'max_length': 200},
    'URLField': {'max_length': 300},
}

CUSTOM_MARK = '# ── studio:custom ── زیرِ این خط را استودیو دست نمی‌زند؛ کدِ دستی‌ات را این‌جا بنویس ──'


def _script_safe_name(name):
    """نامِ پروژه داخلِ echo ِ bat/sh — نویسه‌های خاصِ cmd و bash حذف می‌شوند."""
    bad = '&|<>^%!"$`\\\r\n'
    return ''.join(' ' if ch in bad else ch for ch in (name or 'project')).strip() or 'project'


def runner_files(name, settings_module='config.settings'):
    """run.bat / run.sh / scripts/ensure_admin.py — اجرای یک‌کلیکه (venv + نصب + مهاجرت + ادمین + runserver).

    ⇒ {مسیرِ نسبی: (متن, مجوز)} — هم در «تولیدِ کد» نوشته می‌شود هم (اگر در پوشه نبود) در خروجیِ ZIP.
    run.bat با CRLF و بدونِ BOM؛ run.sh اجرایی (755).
    """
    safe = _script_safe_name(name)
    return {
        'run.bat': (RUN_BAT_TPL.replace('__NAME__', safe).replace('\n', '\r\n'), 0),
        'run.sh': (RUN_SH_TPL.replace('__NAME__', safe), 0o755),
        'scripts/ensure_admin.py': (ENSURE_ADMIN_TPL.replace('__SETTINGS__', settings_module or 'config.settings'), 0),
    }


def run_readme(name):
    return RUN_README_TPL.replace('__NAME__', _script_safe_name(name))


class GenerationError(Exception):
    pass


def _q(s):
    """رشتهٔ پایتونی با کوتیشنِ تکی."""
    return "'%s'" % (s or '').replace('\\', '\\\\').replace("'", "\\'")


def sha(text):
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()


# ──────────────────────────────────────────────── فیلد و مدل
def field_code(fld):
    """یک خطِ تعریفِ فیلد در models.py."""
    if fld.field_type == 'custom':
        return '    %s = %s' % (fld.name, (fld.raw_code or 'models.CharField(max_length=200)').strip())

    args, kwargs = [], []
    if fld.is_relational:
        if fld.related_model_id:
            target = fld.related_model
            same_app = target.app_id == fld.model.app_id
            args.append(_q(target.name) if same_app else _q('%s.%s' % (target.app.name, target.name)))
        elif fld.related_ref:
            ref = fld.related_ref.strip()
            args.append(ref if ref.startswith('settings.') else _q(ref))
        else:
            raise GenerationError('فیلدِ «%s» از نوعِ رابطه است ولی مدلِ مقصد ندارد.' % fld.name)
        if fld.field_type in ('ForeignKey', 'OneToOneField'):
            args.append('on_delete=models.%s' % fld.on_delete)
        if fld.related_name:
            kwargs.append('related_name=%s' % _q(fld.related_name))
    else:
        for k, v in FIELD_DEFAULT_ARGS.get(fld.field_type, {}).items():
            if k == 'max_length' and fld.max_length:
                v = fld.max_length
            kwargs.append('%s=%s' % (k, v))
        if fld.max_length and fld.field_type not in FIELD_DEFAULT_ARGS and fld.field_type not in ('TextField',):
            kwargs.append('max_length=%d' % fld.max_length)
        if fld.field_type == 'DecimalField':
            kwargs.append('max_digits=%d' % (fld.max_digits or 12))
            kwargs.append('decimal_places=%d' % (fld.decimal_places or 0))

    if fld.field_type in ('ImageField', 'FileField'):
        kwargs.append("upload_to='%s/'" % fld.model.name.lower())
    if fld.field_type in ('DateField', 'DateTimeField', 'TimeField'):
        if fld.auto_now_add:
            kwargs.append('auto_now_add=True')
        elif fld.auto_now:
            kwargs.append('auto_now=True')
    if fld.null:
        kwargs.append('null=True')
    if fld.blank:
        kwargs.append('blank=True')
    if fld.unique:
        kwargs.append('unique=True')
    if fld.db_index and not fld.unique:
        kwargs.append('db_index=True')
    if fld.choice_pairs:
        kwargs.append('choices=[%s]' % ', '.join('(%s, %s)' % (_q(k), _q(v)) for k, v in fld.choice_pairs))
    d = (fld.default or '').strip()
    if d and not (fld.auto_now or fld.auto_now_add):
        kwargs.append('default=%s' % d)
    kwargs.append('verbose_name=%s' % _q(fld.verbose_name_fa or fld.name))
    if fld.help_text_fa:
        kwargs.append('help_text=%s' % _q(fld.help_text_fa))

    inner = ', '.join(args + kwargs)
    line = '    %s = models.%s(%s)' % (fld.name, fld.field_type, inner)
    if len(line) <= 95:
        return line
    return ('    %s = models.%s(\n        %s\n    )'
            % (fld.name, fld.field_type, ',\n        '.join(args + kwargs)))


def model_code(mdl):
    if not mdl.managed and mdl.raw_code:
        return mdl.raw_code.rstrip()
    fields = list(mdl.fields.all())
    out = ['class %s(models.Model):' % mdl.name]
    out.append('    """%s — ساختهٔ استودیو."""' % (mdl.verbose_name_fa or mdl.name))
    out.append('')
    if not fields:
        out.append('    created_at = models.DateTimeField(auto_now_add=True)')
    for fld in fields:
        out.append(field_code(fld))
    out.append('')
    out.append('    class Meta:')
    out.append('        verbose_name = %s' % _q(mdl.verbose_name_fa or mdl.name))
    out.append('        verbose_name_plural = %s'
               % _q(mdl.verbose_plural_fa or mdl.verbose_name_fa or mdl.name))
    if mdl.ordering_list:
        out.append('        ordering = [%s]' % ', '.join(_q(x) for x in mdl.ordering_list))
    if mdl.has_str:
        names = {x.name for x in fields}
        target = mdl.str_field if mdl.str_field in names else None
        if not target:
            first_text = next((x for x in fields if x.is_textual), None)
            target = first_text.name if first_text else None
        out.append('')
        out.append('    def __str__(self):')
        if target:
            out.append('        return str(self.%s)' % target)
        else:
            out.append("        return '%s #%%s' %% self.pk" % mdl.name)
    return '\n'.join(out)


def _admin_code(models):
    adm = ['# -*- coding: utf-8 -*-', 'from django.contrib import admin', '']
    reg = [m for m in models if m.in_admin]
    if not reg:
        adm.append('# مدلی برای ادمین ثبت نشده است.')
        return '\n'.join(adm)
    adm.append('from .models import %s' % ', '.join(sorted(m.name for m in reg)))
    adm.append('')
    for m in reg:
        fl = list(m.fields.all())
        names = {x.name for x in fl}
        cols = [x for x in _csv(m.admin_list_display) if x in names] or \
               [x.name for x in fl if not x.is_relational and x.field_type != 'custom'][:5] or ['id']
        search = [x for x in _csv(m.admin_search_fields) if x in names] or \
                 [x.name for x in fl if x.field_type in ('CharField', 'TextField', 'SlugField')][:3]
        filters = [x for x in _csv(m.admin_list_filter) if x in names] or \
                  [x.name for x in fl if x.field_type in ('BooleanField', 'ForeignKey')][:3]
        adm.append('')
        adm.append('@admin.register(%s)' % m.name)
        adm.append('class %sAdmin(admin.ModelAdmin):' % m.name)
        adm.append('    list_display = %r' % (cols,))
        if search:
            adm.append('    search_fields = %r' % (search,))
        if filters:
            adm.append('    list_filter = %r' % (filters,))
        slug_f = next((x for x in fl if x.field_type == 'SlugField'), None)
        name_f = next((x for x in fl if x.field_type == 'CharField'), None)
        if slug_f and name_f:
            adm.append("    prepopulated_fields = {'%s': ('%s',)}" % (slug_f.name, name_f.name))
    return '\n'.join(adm)


def _csv(text):
    return [x.strip() for x in (text or '').replace('،', ',').split(',') if x.strip()]


# ──────────────────────────────────────────────── ویو، فرم، نشانی
GENERIC = {'list': 'ListView', 'detail': 'DetailView', 'create': 'CreateView',
           'update': 'UpdateView', 'delete': 'DeleteView', 'template': 'TemplateView'}


def _route_names(app):
    return {r.name for r in app.routes.all() if r.name}


def _success_url(view, names):
    if view.success_url_name:
        return "reverse_lazy(%s)" % _q(view.success_url_name)
    if view.model_id:
        for cand in ('%s_list' % view.model.snake, 'index', 'home'):
            if cand in names:
                return "reverse_lazy(%s)" % _q(cand)
    return "'/'"


def _view_code(view, names):
    if view.kind == 'custom':
        return (view.custom_code or '').rstrip() or ('def %s(request):\n    """TODO"""\n    from django.http import HttpResponse\n    return HttpResponse("%s")' % (view.name, view.name))
    bases = []
    if view.login_required:
        bases.append('LoginRequiredMixin')
    bases.append(GENERIC[view.kind])
    out = ['class %s(%s):' % (view.class_name, ', '.join(bases))]
    out.append('    """%s"""' % (view.description or view.get_kind_display()))
    if view.kind in view.NEEDS_MODEL:
        if not view.model_id:
            raise GenerationError('ویوِ «%s» مدل می‌خواهد.' % view.name)
        out.append('    model = %s' % view.model.name)
    out.append('    template_name = %s' % _q(view.template_name))
    if view.context_object_name:
        out.append('    context_object_name = %s' % _q(view.context_object_name))
    elif view.kind == 'list' and view.model_id:
        out.append('    context_object_name = %s' % _q(view.model.snake + '_list'))
    if view.kind == 'list':
        if view.paginate_by:
            out.append('    paginate_by = %d' % view.paginate_by)
        if view.ordering:
            out.append('    ordering = [%s]' % ', '.join(_q(x) for x in _csv(view.ordering)))
    if view.kind in ('create', 'update'):
        if view.field_list:
            out.append('    fields = [%s]' % ', '.join(_q(x) for x in view.field_list))
        else:
            out.append('    form_class = %sForm' % view.model.name)
        out.append('    success_url = %s' % _success_url(view, names))
    if view.kind == 'delete':
        out.append('    success_url = %s' % _success_url(view, names))
    out.append('')
    out.append('    def get_context_data(self, **kwargs):')
    out.append('        ctx = super().get_context_data(**kwargs)')
    out.append('        ctx[\'page_title\'] = %s' % _q(view.description or view.name))
    out.append('        return ctx')
    return '\n'.join(out)


def _views_module(app):
    views = list(app.views.all())
    names = _route_names(app)
    head = ['# -*- coding: utf-8 -*-', '"""ویوهای %s — ساختهٔ استودیو."""' % app.name]
    imports = set()
    kinds = {v.kind for v in views if v.kind != 'custom'}
    if any(v.login_required for v in views if v.kind != 'custom'):
        imports.add('from django.contrib.auth.mixins import LoginRequiredMixin')
    if kinds & {'create', 'update', 'delete'}:
        imports.add('from django.urls import reverse_lazy')
    if kinds:
        imports.add('from django.views.generic import %s' % ', '.join(sorted(GENERIC[k] for k in kinds)))
    model_names = sorted({v.model.name for v in views if v.model_id and v.kind in v.NEEDS_MODEL})
    form_names = sorted({v.model.name for v in views
                         if v.kind in ('create', 'update') and v.model_id and not v.field_list})
    # importهای کدِ دستی به بالای فایل می‌روند تا یک‌جا باشند
    bodies = []
    for v in views:
        code = _view_code(v, names)
        if v.kind == 'custom':
            kept = []
            for line in code.splitlines():
                if re.match(r'^(import |from \S+ import )', line):
                    imports.add(line.strip())
                else:
                    kept.append(line)
            code = '\n'.join(kept).strip('\n')
        bodies.append(code)
    out = head + ['']
    out += sorted(imports)
    if model_names:
        out.append('')
        out.append('from .models import %s' % ', '.join(model_names))
    if form_names:
        out.append('from .forms import %s' % ', '.join('%sForm' % n for n in form_names))
    for b in bodies:
        out += ['', '', b]
    if not views:
        out.append('# ویوهای این اپ را از «ویوها و URLها» بساز.')
    return '\n'.join(out)


def _forms_module(app):
    views = list(app.views.all())
    models = []
    for v in views:
        if v.kind in ('create', 'update') and v.model_id and not v.field_list and v.model not in models:
            models.append(v.model)
    out = ['# -*- coding: utf-8 -*-', '"""فرم‌های %s — ساختهٔ استودیو."""' % app.name,
           'from django import forms']
    if models:
        out.append('')
        out.append('from .models import %s' % ', '.join(m.name for m in models))
    for m in models:
        names = m.editable_field_names
        out += ['', '', 'class %sForm(forms.ModelForm):' % m.name, '    class Meta:',
                '        model = %s' % m.name,
                '        fields = %s' % ('[%s]' % ', '.join(_q(n) for n in names) if names else "'__all__'")]
    if not models:
        out.append('')
        out.append('# فرم‌های ساخت/ویرایش وقتی ویوِ Create/Update بسازی این‌جا می‌آیند.')
    return '\n'.join(out)


def _urls_module(app):
    routes = list(app.routes.all())
    out = ['# -*- coding: utf-8 -*-', '"""نشانی‌های %s — ساختهٔ استودیو."""' % app.name,
           'from django.urls import include, path', '', 'from . import views', '', 'urlpatterns = [']
    for r in routes:
        out.append('    ' + r.code)
    out.append(']')
    return '\n'.join(out)


def default_template_body(view):
    """بدنهٔ پیش‌فرضِ قالبِ یک ویوِ استاندارد — تا کاربر/AI از صفر شروع نکند."""
    m = view.model
    app = view.app
    names = _route_names(app)
    label = (m.verbose_name_fa or m.name) if m else view.name
    plural = (m.verbose_plural_fa or label) if m else view.name
    snake = m.snake if m else view.name
    detail = '%s_detail' % snake if '%s_detail' % snake in names else ''
    create = '%s_create' % snake if '%s_create' % snake in names else ''
    update = '%s_update' % snake if '%s_update' % snake in names else ''
    delete = '%s_delete' % snake if '%s_delete' % snake in names else ''
    lst = '%s_list' % snake if '%s_list' % snake in names else ''
    ctx = view.context_object_name or ('%s_list' % snake)

    if view.kind == 'list':
        link_open = "<a href=\"{%% url '%s' obj.pk %%}\">" % detail if detail else ''
        link_close = '</a>' if detail else ''
        btn = ("<a class=\"btn sm\" href=\"{%% url '%s' %%}\">+ %s تازه</a>" % (create, label)) if create else ''
        return '''<section class="section">
  <div class="section-h"><h1>%(plural)s</h1>%(btn)s</div>
  <div class="grid">
    {%% for obj in %(ctx)s %%}
    <article class="card">
      <div class="body">
        <h3>%(lo)s{{ obj }}%(lc)s</h3>
      </div>
    </article>
    {%% empty %%}<p class="muted">هنوز چیزی ثبت نشده.</p>{%% endfor %%}
  </div>
  {%% if is_paginated %%}
  <nav class="pager" style="display:flex;gap:8px;justify-content:center;margin-top:18px">
    {%% if page_obj.has_previous %%}<a class="btn ghost sm" href="?page={{ page_obj.previous_page_number }}">قبلی</a>{%% endif %%}
    <span class="muted">صفحهٔ {{ page_obj.number }} از {{ page_obj.paginator.num_pages }}</span>
    {%% if page_obj.has_next %%}<a class="btn ghost sm" href="?page={{ page_obj.next_page_number }}">بعدی</a>{%% endif %%}
  </nav>
  {%% endif %%}
</section>''' % {'plural': plural, 'btn': btn, 'ctx': ctx, 'lo': link_open, 'lc': link_close}

    if view.kind == 'detail':
        rows = ''
        if m:
            for f in m.fields.all():
                if f.field_type == 'custom':
                    continue
                val = '{{ object.%s }}' % f.name
                if f.field_type in ('ImageField',):
                    val = '{%% if object.%s %%}<img src="{{ object.%s.url }}" alt="" style="max-width:280px;border-radius:12px">{%% endif %%}' % (f.name, f.name)
                elif f.field_type == 'BooleanField':
                    val = '{%% if object.%s %%}بله{%% else %%}خیر{%% endif %%}' % f.name
                elif f.field_type == 'ManyToManyField':
                    val = '{%% for x in object.%s.all %%}{{ x }}{%% if not forloop.last %%}، {%% endif %%}{%% endfor %%}' % f.name
                rows += '      <tr><th>%s</th><td>%s</td></tr>\n' % (f.verbose_name_fa or f.name, val)
        acts = ''
        if update:
            acts += "<a class=\"btn ghost sm\" href=\"{%% url '%s' object.pk %%}\">ویرایش</a> " % update
        if delete:
            acts += "<a class=\"btn ghost sm\" href=\"{%% url '%s' object.pk %%}\">حذف</a> " % delete
        if lst:
            acts += "<a class=\"link\" href=\"{%% url '%s' %%}\">← بازگشت به فهرست</a>" % lst
        return '''<section class="section">
  <div class="section-h"><h1>{{ object }}</h1><div>%(acts)s</div></div>
  <div class="card" style="padding:18px">
    <table>
%(rows)s    </table>
  </div>
</section>''' % {'acts': acts, 'rows': rows}

    if view.kind in ('create', 'update'):
        title = ('%s تازه' % label) if view.kind == 'create' else 'ویرایشِ {{ object }}'
        back = ("<a class=\"link\" href=\"{%% url '%s' %%}\">انصراف</a>" % lst) if lst else ''
        return '''<section class="section" style="max-width:720px">
  <h1>%(title)s</h1>
  <form method="post" enctype="multipart/form-data" class="co-form">{%% csrf_token %%}
    {{ form.non_field_errors }}
    {%% for field in form %%}
      <label>{{ field.label }}</label>
      {{ field }}
      {%% if field.help_text %%}<small class="muted">{{ field.help_text }}</small>{%% endif %%}
      {%% for e in field.errors %%}<div class="err">{{ e }}</div>{%% endfor %%}
    {%% endfor %%}
    <div style="display:flex;gap:10px;align-items:center;margin-top:14px">
      <button class="btn">ذخیره</button> %(back)s
    </div>
  </form>
</section>''' % {'title': title, 'back': back}

    if view.kind == 'delete':
        back = ("<a class=\"link\" href=\"{%% url '%s' %%}\">انصراف</a>" % lst) if lst else ''
        return '''<section class="section" style="max-width:640px">
  <h1>حذفِ «{{ object }}»</h1>
  <p class="muted">این کار برگشت‌پذیر نیست.</p>
  <form method="post">{%% csrf_token %%}
    <button class="btn">بله، حذف شود</button> %(back)s
  </form>
</section>''' % {'back': back}

    return DEFAULT_BODY % {'title': view.description or view.name}


def models_module(app, with_product_extras=False):
    models = list(app.models.all())
    all_fields = [x for m in models for x in m.fields.all()]
    defaults = ' '.join((x.default or '') + ' ' + (x.raw_code or '') for x in all_fields)
    head = ['# -*- coding: utf-8 -*-',
            '"""مدل‌های %s — ساختهٔ استودیو."""' % app.name]
    if 'uuid.' in defaults:
        head.append('import uuid')
    if any((x.related_ref or '').startswith('settings.') for x in all_fields):
        head.append('from django.conf import settings')
    head.append('from django.db import models')
    if 'timezone.' in defaults:
        head.append('from django.utils import timezone')
    body = head + ['']
    for m in models:
        body.append('')
        body.append(model_code(m))
        body.append('')
    if with_product_extras and app.name == 'catalog' and any(m.name == 'Product' for m in models):
        body.append(PRODUCT_EXTRAS)
    return '\n'.join(body)


def app_files(app, with_product_extras=False):
    """همهٔ فایل‌های پایتونیِ یک اپ ⇒ {مسیرِ نسبی: کد} — هم برای نوشتن، هم برای «پیش‌نمایشِ کد»."""
    base = app.dir
    files = {
        '%s/models.py' % base: models_module(app, with_product_extras),
        '%s/admin.py' % base: _admin_code(list(app.models.all())),
        '%s/views.py' % base: _views_module(app),
        '%s/forms.py' % base: _forms_module(app),
    }
    if app.views.exists() or app.routes.exists():
        files['%s/urls.py' % base] = _urls_module(app)
    return files



# ──────────────────────────────────────────────── نقشهٔ نشانی‌ها (برای نمایش و برای AI)
def effective_routes(project):
    """همهٔ نشانی‌هایی که پروژه واقعاً خواهد داشت — برای تبِ «URLها»."""
    apps = {a.name for a in project.apps.all()}
    has_catalog = 'catalog' in apps
    has_cart = 'cart' in apps and has_catalog
    rows = [{'pattern': 'admin/', 'name': 'admin', 'view': 'admin.site.urls', 'source': 'core', 'editable': False}]
    if has_cart:
        for pat, nm, vw in (('cart/', 'cart_detail', 'cart.views.detail'),
                            ('cart/add/<int:pk>/', 'cart_add', 'cart.views.add'),
                            ('cart/update/<int:pk>/', 'cart_update', 'cart.views.update'),
                            ('cart/remove/<int:pk>/', 'cart_remove', 'cart.views.remove'),
                            ('cart/checkout/', 'checkout', 'cart.views.checkout')):
            rows.append({'pattern': pat, 'name': nm, 'view': vw, 'source': 'cart', 'editable': False})
    for pg in project.pages.all():
        if pg.is_imported or (has_cart and pg.kind in ('cart', 'checkout')):
            continue
        rows.append({'pattern': pg.url_pattern, 'name': pg.view_name, 'view': 'config.views.%s' % pg.view_name,
                     'source': 'page', 'editable': False, 'page': pg})
    if has_catalog:
        rows.append({'pattern': 'product/<slug:slug>/', 'name': 'product_detail',
                     'view': 'config.views.product_detail', 'source': 'core', 'editable': False})
    for r in project.routes.select_related('app', 'view').all():
        rows.append({'pattern': r.full_pattern, 'name': r.name, 'view': r.target,
                     'source': ('app:%s' % r.app.name) if r.app_id else 'root', 'editable': r.managed, 'route': r})
    return rows


def url_names(project):
    return sorted({r['name'] for r in effective_routes(project) if r.get('name')})


# ──────────────────────────────────────────────── موتور
class ProjectGenerator:
    """همهٔ فایل‌های یک پروژه را می‌نویسد."""

    def __init__(self, project):
        self.p = project
        self.root = project.path
        self.written = []
        self.app_names = {a.name for a in project.apps.all()}
        self.has_catalog = 'catalog' in self.app_names and not project.is_imported
        self.has_cart = 'cart' in self.app_names and self.has_catalog
        self.warnings = []

    # ---------------------------------------------------------
    def _target(self, rel):
        target = os.path.normpath(os.path.join(str(self.root), rel))
        if not target.startswith(str(self.root)):
            raise GenerationError('مسیرِ خارج از پروژه: %s' % rel)
        return target

    def _safe_write(self, rel, body):
        target = self._target(rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(body if body.endswith('\n') else body + '\n')
        self.written.append(rel)

    def _write_managed(self, rel, body):
        """فایلِ پایتونی با «ناحیهٔ دستی»: زیرِ نشانه هر چه بود، می‌ماند."""
        target = self._target(rel)
        tail = '\n'
        if os.path.exists(target):
            with open(target, encoding='utf-8', errors='replace') as fh:
                old = fh.read()
            if CUSTOM_MARK in old:
                tail = old.split(CUSTOM_MARK, 1)[1]
                if not tail.strip():
                    tail = '\n'
        self._safe_write(rel, body.rstrip('\n') + '\n\n\n' + CUSTOM_MARK + tail)

    def _write_if_changed(self, rel, body):
        target = self._target(rel)
        if os.path.exists(target):
            with open(target, encoding='utf-8', errors='replace') as fh:
                if fh.read() == body:
                    return False
        self._safe_write(rel, body)
        return True

    def run(self):
        os.makedirs(str(self.root), exist_ok=True)
        if self.p.is_imported:
            self._imported_run()
            return self.written
        self._manage()
        self._config()
        self._apps()
        if self.has_cart:
            self._cart_app()
        if self.has_catalog:
            self._sample_data_command()
        self._templates()
        self._static()
        self._meta()
        return self.written

    # ---------------------------------------------------------
    def _manage(self):
        self._safe_write('manage.py', MANAGE_TPL % {'name': self.p.name})

    def settings_code(self):
        apps = list(self.p.apps.all())
        local = '\n'.join('    %s,' % _q(a.package) for a in apps)
        third = '\n'.join('    %s,' % _q(x) for x in self.p.extra_app_list)
        extra_cp = "        'apps.cart.context_processors.cart',\n" if self.has_cart else ''
        custom = (self.p.custom_settings or '').strip()
        return SETTINGS_TPL % {
            'local_apps': local, 'third_party': third,
            'title': (self.p.site_title or self.p.name).replace("'", "\\'"),
            'extra_cp': extra_cp,
            'lang': self.p.language_code or 'fa', 'tz': self.p.time_zone or 'Asia/Tehran',
            'hosts': ','.join(self.p.allowed_host_list),
        } + ('\n\n# ── تنظیماتِ دستی (از استودیو) ──\n%s\n' % custom if custom else '')

    def _config(self):
        apps = list(self.p.apps.all())
        self._safe_write('config/__init__.py', '')
        self._safe_write('apps/__init__.py', '')
        self._write_managed('config/settings.py', self.settings_code())

        pages = list(self.p.pages.all())
        routes = []
        for pg in pages:
            if self.has_cart and pg.kind in ('cart', 'checkout'):
                continue           # اپِ cart خودش این‌ها را سرو می‌کند
            routes.append("    path('%s', views.%s, name='%s')," %
                          (pg.url_pattern, pg.view_name, pg.view_name))
        if self.has_catalog:
            routes.append("    path('product/<slug:slug>/', views.product_detail, name='product_detail'),")
        includes = []
        if self.has_cart:
            includes.append("    path('cart/', include('apps.cart.urls')),")
        for a in apps:
            if a.name == 'cart' and self.has_cart:
                continue
            if a.views.exists() or a.routes.exists():
                includes.append("    path(%s, include(%s))," % (_q(a.effective_prefix), _q(a.package + '.urls')))
        aliases = []
        for r in self.p.routes.filter(app__isnull=True).select_related('view__app'):
            if r.view_id:
                line = 'from %s import views as %s' % (r.view.app.package, r.root_alias)
                if line not in aliases:
                    aliases.append(line)
            includes.append('    ' + r.root_code)
        self._write_managed('config/urls.py', URLS_TPL % {
            'routes': '\n'.join(routes), 'includes': '\n'.join(includes) + ('\n' if includes else ''),
            'aliases': ('\n'.join(aliases) + '\n') if aliases else '',
        })
        self._safe_write('config/wsgi.py', WSGI_TPL)
        self._safe_write('config/context.py', CONTEXT_TPL % {
            'menu': ', '.join('(%s, %s)' % (_q(pg.title), _q('/%s' % pg.slug)) for pg in pages if pg.in_menu),
        })
        self._write_managed('config/views.py', self._views_code(pages))

    def _views_code(self, pages):
        out = ['# -*- coding: utf-8 -*-',
               '"""ویوهای صفحه‌ها — ساختهٔ استودیو."""',
               'from django.db.models import Q',
               'from django.shortcuts import get_object_or_404, render', '']
        if self.has_catalog:
            out.append('from apps.catalog.models import Category, Product')
            out.append('')
        for pg in pages:
            if self.has_cart and pg.kind in ('cart', 'checkout'):
                continue
            out.append('')
            out.append('def %s(request):' % pg.view_name)
            out.append('    """%s"""' % pg.title)
            ctx = ["'page_title': %s" % _q(pg.title)]
            if self.has_catalog and pg.kind in ('home', 'product_list'):
                out.append("    q = (request.GET.get('q') or '').strip()")
                out.append("    cat = (request.GET.get('cat') or '').strip()")
                out.append('    products = Product.objects.filter(is_active=True).select_related("category")')
                out.append('    if q:')
                out.append('        products = products.filter(Q(name__icontains=q) | Q(description__icontains=q))')
                out.append('    if cat:')
                out.append('        products = products.filter(category__slug=cat)')
                out.append('    products = products[:%d]' % (12 if pg.kind == 'home' else 60))
                out.append('    categories = Category.objects.all()')
                ctx += ["'products': products", "'categories': categories",
                        "'q': q", "'cat': cat"]
            out.append('    return render(request, %r, {%s})'
                       % (pg.template_path, ', '.join(ctx)))
        if self.has_catalog:
            out.append('')
            out.append('')
            out.append('def product_detail(request, slug):')
            out.append('    """جزئیاتِ یک محصول."""')
            out.append('    product = get_object_or_404(Product, slug=slug, is_active=True)')
            out.append('    related = Product.objects.filter(is_active=True, category=product.category)'
                       '.exclude(pk=product.pk)[:4]')
            out.append("    return render(request, 'pages/product_detail.html',")
            out.append("                  {'product': product, 'related': related,")
            out.append("                   'page_title': product.name})")
        return '\n'.join(out)

    # ---------------------------------------------------------
    def _apps(self):
        for app in self.p.apps.all():
            if app.name == 'cart' and self.has_cart:
                continue               # جداگانه نوشته می‌شود
            if not app.managed:
                continue
            self._write_app(app)

    def _write_app(self, app):
        base = app.dir
        self._safe_write('%s/__init__.py' % base, '')
        self._safe_write('%s/migrations/__init__.py' % base, '')
        self._safe_write('%s/apps.py' % base, APP_CONFIG_TPL % {
            'cls': app.class_prefix, 'pkg': app.package,
            'name': app.name, 'fa': app.verbose_name_fa or app.name})
        for rel, code in app_files(app, with_product_extras=self.has_catalog).items():
            self._write_managed(rel, code)
        self._view_templates(app)

    def _view_templates(self, app):
        """قالبِ ویوهای استاندارد: templates/<app>/<view>.html + CSSِ خودش."""
        imported = self.p.is_imported
        for v in app.views.all():
            if not v.needs_template:
                continue
            body = (v.template_body or '').strip() or default_template_body(v)
            title = v.description or v.name
            if imported:
                # پروژهٔ واردشده: قالب داخلِ خودِ اپ و مستقل — base.htmlِ آن پروژه
                # ممکن است بلوک‌های دیگری داشته باشد و بدنه اصلاً دیده نشود.
                css = '<style>\n%s\n</style>\n' % v.css if v.css.strip() else ''
                tpl = STANDALONE_PAGE_TPL % {'title': title, 'body': body, 'css': css}
                self._safe_write('%s/templates/%s' % (app.dir, v.template_name), tpl)
            else:
                self._safe_write('templates/%s' % v.template_name, PAGE_TPL % {
                    'title': title, 'css': v.css_name, 'body': body})
                self._safe_write('static/css/pages/%s.css' % v.css_name,
                                 v.css or '/* CSSِ %s */\n' % v.css_name)

    def _sample_data_command(self):
        base = 'apps/catalog/management'
        self._safe_write('%s/__init__.py' % base, '')
        self._safe_write('%s/commands/__init__.py' % base, '')
        self._safe_write('%s/commands/load_sample_data.py' % base, LOAD_SAMPLES_TPL)

    def _cart_app(self):
        b = 'apps/cart'
        self._safe_write('%s/__init__.py' % b, '')
        self._safe_write('%s/migrations/__init__.py' % b, '')
        self._safe_write('%s/apps.py' % b, APP_CONFIG_TPL % {'cls': 'Cart', 'pkg': 'apps.cart', 'name': 'cart', 'fa': 'سبدِ خرید'})
        self._safe_write('%s/models.py' % b, '# سبدِ خرید روی session است؛ مدلی ندارد.\n')
        self._safe_write('%s/cart.py' % b, CART_PY)
        self._safe_write('%s/context_processors.py' % b, CART_CP)
        self._write_managed('%s/views.py' % b, CART_VIEWS)
        self._write_managed('%s/urls.py' % b, CART_URLS)
        self._write_managed('%s/forms.py' % b, CART_FORMS)

    # ---------------------------------------------------------
    def _templates(self):
        parts = {s.kind: s.content for s in self.p.shared_parts.all()}
        header = (parts.get('header') or '').strip() or DEFAULT_HEADER
        footer = (parts.get('footer') or '').strip() or DEFAULT_FOOTER
        self._safe_write('templates/base.html', BASE_TPL % {'title': self.p.site_title or self.p.name})
        self._safe_write('templates/components/header.html', header)
        self._safe_write('templates/components/footer.html', footer)
        self._safe_write('templates/components/product_card.html', PRODUCT_CARD_TPL)

        kinds = {}
        for pg in self.p.pages.all():
            kinds[pg.kind] = pg
            body = (pg.body_html or '').strip()
            if not body:
                # DEFAULT_BODIES قالبِ جنگوست (نه رشتهٔ %)؛ فقط DEFAULT_BODY عنوان می‌گیرد
                body = DEFAULT_BODIES[pg.kind] if pg.kind in DEFAULT_BODIES else DEFAULT_BODY % {'title': pg.title}
            name = pg.css_name
            self._safe_write('templates/%s' % pg.template_path, PAGE_TPL % {
                'title': pg.title, 'css': name, 'body': body})
            self._safe_write('static/css/pages/%s.css' % name, pg.css or '/* CSSِ صفحهٔ %s */\n' % name)
            pg.synced_hash = sha(pg.body_html + '\x00' + pg.css)
            pg.save(update_fields=['synced_hash'])

        if self.has_catalog:
            if 'product_detail' not in kinds:
                self._safe_write('templates/pages/product_detail.html',
                                 PAGE_TPL % {'title': '{{ product.name }}', 'css': 'product_detail',
                                             'body': DEFAULT_BODIES['product_detail']})
                self._safe_write('static/css/pages/product_detail.css', '')
        if self.has_cart:
            for k in ('cart', 'checkout'):
                if k not in kinds:
                    self._safe_write('templates/pages/%s.html' % k,
                                     PAGE_TPL % {'title': {'cart': 'سبد خرید', 'checkout': 'تسویه‌حساب'}[k],
                                                 'css': k, 'body': DEFAULT_BODIES[k]})
                    self._safe_write('static/css/pages/%s.css' % k, '')
            self._safe_write('templates/pages/order_done.html', ORDER_DONE_TPL)

    def _static(self):
        parts = {s.kind: s.content for s in self.p.shared_parts.all()}
        base_css = (parts.get('base_css') or '').strip() or (BASE_CSS % {'brand': self.p.brand_color})
        self._safe_write('static/css/base.css', base_css)

    def _meta(self):
        reqs = ['Django>=4.2,<5.1', 'Pillow>=10.0'] + self.p.extra_requirement_list
        self._safe_write('requirements.txt', '\n'.join(reqs) + '\n')
        self._safe_write('.env.example',
                         '# نمونهٔ تنظیماتِ محیط\nDJANGO_SECRET_KEY=change-me\n'
                         'DJANGO_DEBUG=True\nDJANGO_ALLOWED_HOSTS=127.0.0.1,localhost\n')
        self._safe_write('.gitignore', 'venv/\n.venv/\n__pycache__/\n*.pyc\ndb.sqlite3\nmedia/\nstaticfiles/\n.env\n'
                         '.preview.*\n.admin-password.txt\n')
        # اجرای یک‌کلیکه: run.bat (ویندوز) / run.sh (لینوکس و مک) + ساختِ ادمین بدونِ پرسش
        for rel, (body, mode) in runner_files(self.p.name, 'config.settings').items():
            self._safe_write(rel, body)
            if mode:
                try:
                    os.chmod(self._target(rel), mode)
                except OSError:
                    pass
        self._safe_write('README.md', README_TPL % {
            'name': self.p.name, 'desc': self.p.description or '—',
            'when': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'cart': 'سبدِ خرید روی session و تسویه‌حساب ⇒ ثبتِ Order' if self.has_cart else '—',
        })

    # ──────────────────────────────────────────── پروژهٔ واردشده
    def _imported_run(self):
        """فقط چیزهایی که مالِ استودیوست نوشته می‌شود (idea.md §۸ سطحِ ۲)."""
        settings_rel = self.p.settings_module_name.replace('.', '/') + '.py'
        urls_rel = (self.p.urls_module or '').replace('.', '/') + '.py' if self.p.urls_module else ''
        for app in self.p.apps.filter(managed=True):
            self._write_app(app)
            self._patch_installed_apps(settings_rel, app.package)
            if (app.views.exists() or app.routes.exists()) and urls_rel:
                self._patch_root_urls(urls_rel, app.effective_prefix, app.package)
        for pg in self.p.pages.filter(kind='imported').exclude(file_path=''):
            target = self._target(pg.file_path)
            try:
                with open(target, encoding='utf-8', errors='replace') as fh:
                    disk = fh.read()
            except OSError:
                disk = None
            if disk is not None and disk == pg.body_html:
                if pg.synced_hash != sha(disk):
                    pg.synced_hash = sha(disk)
                    pg.save(update_fields=['synced_hash'])
                continue
            # idea.md §۹: اگر فایل بیرون از استودیو هم عوض شده، کورکورانه رویش ننویس
            if disk is not None and pg.synced_hash and sha(disk) != pg.synced_hash:
                self.warnings.append('تعارض: «%s» هم بیرون از استودیو و هم در استودیو عوض شده؛ '
                                     'نوشته نشد. در ویرایشگرِ صفحه یکی را انتخاب کن.' % pg.file_path)
                continue
            self._safe_write(pg.file_path, pg.body_html)
            pg.synced_hash = sha(pg.body_html)
            pg.save(update_fields=['synced_hash'])

    def _patch_installed_apps(self, settings_rel, label):
        target = self._target(settings_rel)
        if not os.path.exists(target):
            raise GenerationError('فایلِ تنظیمات پیدا نشد: %s' % settings_rel)
        with open(target, encoding='utf-8') as fh:
            src = fh.read()
        if re.search(r'''['"]%s['"]''' % re.escape(label), src):
            return False
        m = re.search(r'INSTALLED_APPS\s*=\s*\[', src)
        if not m:
            raise GenerationError('INSTALLED_APPS در تنظیمات پیدا نشد.')
        i, depth = m.end(), 1
        while i < len(src) and depth:
            depth += {'[': 1, ']': -1}.get(src[i], 0)
            i += 1
        close = i - 1
        before = src[:close].rstrip()
        if not before.endswith(','):
            before += ','
        src = before + '\n    %s,  # studio\n' % _q(label) + src[close:]
        self._safe_write(settings_rel, src)
        return True

    def _patch_root_urls(self, urls_rel, prefix, package):
        target = self._target(urls_rel)
        if not os.path.exists(target):
            raise GenerationError('فایلِ نشانی‌ها پیدا نشد: %s' % urls_rel)
        with open(target, encoding='utf-8') as fh:
            src = fh.read()
        if package + '.urls' in src:
            return False
        if not re.search(r'from django\.urls import[^\n]*\binclude\b', src):
            if re.search(r'from django\.urls import ', src):
                src = re.sub(r'from django\.urls import ', 'from django.urls import include, ', src, count=1)
            else:
                src = 'from django.urls import include, path\n' + src
        m = re.search(r'urlpatterns\s*=\s*\[', src)
        if not m:
            raise GenerationError('urlpatterns در فایلِ نشانی‌ها پیدا نشد.')
        line = "\n    path(%s, include(%s)),  # studio" % (_q(prefix), _q(package + '.urls'))
        src = src[:m.end()] + line + src[m.end():]
        self._safe_write(urls_rel, src)
        return True


# ══════════════════════════════════════════════════════════════════
LOAD_SAMPLES_TPL = '''# -*- coding: utf-8 -*-
"""python manage.py load_sample_data — دسته و محصولِ نمونه از fixtures/sample_data.json (ساختهٔ استودیو).

با slug یکتا می‌شود؛ اجرای دوباره چیزی را تکراری نمی‌کند و دادهٔ دیگرِ تو دست نمی‌خورد.
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.catalog.models import Category, Product


class Command(BaseCommand):
    help = 'بارگذاریِ دسته و محصولِ نمونه از fixtures/sample_data.json'

    def handle(self, *args, **opts):
        path = settings.BASE_DIR / 'fixtures' / 'sample_data.json'
        if not path.exists():
            self.stdout.write('fixtures/sample_data.json نیست.')
            return
        data = json.loads(path.read_text(encoding='utf-8'))
        cats = {}
        for c in data.get('categories', []):
            obj, _ = Category.objects.update_or_create(slug=c['slug'], defaults={'name': c['name']})
            cats[c['slug']] = obj
        n = 0
        for p in data.get('products', []):
            Product.objects.update_or_create(slug=p['slug'], defaults={
                'name': p['name'], 'description': p.get('description', ''), 'price': p.get('price', 0),
                'stock': p.get('stock', 10), 'is_active': True, 'category': cats.get(p.get('category'))})
            n += 1
        self.stdout.write('%d دسته، %d محصول' % (len(cats), n))
'''


SETTINGS_TPL = '''# -*- coding: utf-8 -*-
"""تنظیماتِ پروژه — ساختهٔ Django Commerce Studio.

این فایل یک تنظیماتِ کاملاً استانداردِ جنگوست؛ بدونِ استودیو هم اجرا می‌شود.
زبان، منطقهٔ زمانی، ALLOWED_HOSTS و اپ‌های بیرونی از «تنظیمات»ِ استودیو می‌آیند.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '%(hosts)s').split(',')

SITE_TITLE = '%(title)s'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

%(third_party)s
%(local_apps)s
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'config.context.site',
%(extra_cp)s    ]},
}]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = '%(lang)s'
TIME_ZONE = '%(tz)s'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

LOGIN_URL = '/admin/login/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
X_FRAME_OPTIONS = 'SAMEORIGIN'

# پیش‌نمایشِ زندهٔ استودیو داخلِ iframe ِ پنل باز می‌شود که مبدأ/پورتِ دیگری دارد؛ در آن حالت
# (STUDIO_PREVIEW=1 را اجراکنندهٔ پیش‌نمایش می‌گذارد) قابِ هم‌مبدأ (X-Frame-Options) برداشته می‌شود.
# در اجرای عادی و نسخهٔ دانلودی سرِ جایش است.
if os.environ.get('STUDIO_PREVIEW') == '1':
    MIDDLEWARE = [m for m in MIDDLEWARE if m != 'django.middleware.clickjacking.XFrameOptionsMiddleware']
'''

URLS_TPL = '''# -*- coding: utf-8 -*-
"""نشانی‌های پروژه — ساختهٔ استودیو."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from . import views
%(aliases)s
urlpatterns = [
    path('admin/', admin.site.urls),
%(includes)s%(routes)s
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
'''

STANDALONE_PAGE_TPL = '''<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%(title)s</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css">
  <style>
    body{margin:0;font-family:Vazirmatn,Tahoma,sans-serif;background:#f6f7fb;color:#111;line-height:1.9}
    .section{max-width:1100px;margin:0 auto;padding:28px 18px}
    .grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
    .card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:14px}
    .btn{display:inline-block;background:#2f6df6;color:#fff;border:0;border-radius:10px;padding:8px 16px;text-decoration:none;cursor:pointer;font:inherit}
    .btn.ghost{background:#fff;color:#111;border:1px solid #e5e7eb}
    .muted{color:#6b7280}.link{color:#2f6df6}
    table{width:100%%;border-collapse:collapse}th,td{padding:8px 10px;border-bottom:1px solid #eee;text-align:right}
    input,textarea,select{width:100%%;padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;font:inherit}
    label{display:block;margin:10px 0 4px;font-size:.9rem;color:#374151}
  </style>
  %(css)s
</head>
<body>
%(body)s
</body>
</html>
'''
