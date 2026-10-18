# -*- coding: utf-8 -*-
"""APIِ JSONِ استودیو (زیرِ /api/v1/studio/) — همان منطقِ رابطِ HTML ِ قدیمی، بی‌قالب.

⚠ قاعده‌ای که همه‌جا رعایت شده: هیچ تغییری مستقیم روی فایل‌های پروژه نوشته
   نمی‌شود. کاربر «تعریف» را عوض می‌کند و بعد «تولیدِ کد» را می‌زند.
   این‌طور متادیتا و سورس هیچ‌وقت از هم جدا نمی‌افتند (idea.md §۵.۳).
   کدِ دستیِ برنامه‌نویس زیرِ خطِ «studio:custom» هر فایل می‌نشیند و می‌ماند.

قراردادِ پاسخ‌ها:
  · موفق: شیءِ به‌روزشده (+ `message` همان پیامِ فارسیِ قدیمی).
  · خطای ورودی: 400 {"error": "...", "errors": {"field": "..."}}.
  · بخشِ فقط‌خواندنیِ پروژهٔ واردشده: 403 {"error": READ_ONLY_MSG}.
  · فقط کاربرِ کارمند (IsAdminUser ⇐ is_staff)؛ احراز هویت: JWT یا سشن.
"""
import os
import re

from django.db import IntegrityError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.code_generation import envs, generator, preview_runner, services, vcs
from . import validators as V
from .helpers import (FormData, READ_ONLY_MSG, app_json, apply_field_post, apply_route_post, build_json,
                      er_data, field_json, file_content, file_count, file_tree, model_json, model_option,
                      page_json, preview_url, project_json, proposal_json, read_text, route_json,
                      route_rows, safe_view_code, shared_json, shared_parts, view_json, view_option)
from .models import App, BuildLog, Field, Model, Page, Project, Route, SharedPart, View


# ──────────────────────────────────────────────── ابزار
def studio_api(*methods):
    def deco(fn):
        return api_view(list(methods))(permission_classes([permissions.IsAdminUser])(fn))
    return deco


def _p(slug):
    return get_object_or_404(Project, slug=slug)


def bad(msg, field=None, code=400):
    body = {'error': str(msg)}
    if field:
        body['errors'] = {field: str(msg)}
    return Response(body, status=code)


def read_only():
    return Response({'error': READ_ONLY_MSG}, status=403)


def _form(request):
    return FormData(request.data)


def _is_write(request):
    return request.method in ('POST', 'PUT', 'PATCH')


# ──────────────────────────────────────────────── پروژه‌ها
@studio_api('GET', 'POST')
def project_list(request):
    if request.method == 'POST':
        return _project_create(request)
    out = []
    for pr in Project.objects.prefetch_related('apps', 'pages'):
        d = project_json(pr)
        d['preview_running'] = preview_runner.status(pr)[0]
        d['app_count'] = len(pr.apps.all())
        d['page_count'] = len(pr.pages.all())
        out.append(d)
    return Response(out)


def _project_create(request):
    post = _form(request)
    name = (post.get('name') or '').strip()
    if not name:
        return bad('نامِ پروژه لازم است.', 'name')
    slug = re.sub(r'[^a-z0-9-]', '', (post.get('slug') or '').strip().lower())
    if slug and Project.objects.filter(slug=slug).exists():
        return bad('شناسهٔ «%s» قبلاً استفاده شده.' % slug, 'slug')
    try:
        color = V.color(post.get('brand_color') or '#2f6df6')
    except ValueError:
        color = '#2f6df6'
    p = Project.objects.create(
        name=name, slug=slug,
        description=(post.get('description') or '').strip(),
        brand_color=color,
    )
    out = {'next': 'detail', 'warning': ''}
    if post.get('scaffold') == 'on':
        services.scaffold_shop(p)
        ok, summary, detail = services.generate(p, 'ساختِ پروژه از قالبِ فروشگاه')
        if ok:
            services.migrate(p)
            out['message'] = 'پروژه ساخته شد و قالبِ فروشگاه تولید شد (%s).' % summary
        else:
            out['warning'] = 'پروژه ساخته شد ولی تولیدِ کد خطا داد — جزئیات در نمای کلی.'
            out['message'] = out['warning']
        if post.get('then_ai') == 'on':
            out['next'] = 'ai'
    else:
        out['message'] = 'پروژهٔ خالی ساخته شد. از «بک‌اند» اپ و مدل اضافه کن.'
    p.refresh_from_db()
    out['project'] = project_json(p, detail=True)
    return Response(out, status=201)


@studio_api('GET', 'DELETE')
def project_detail(request, slug):
    p = _p(slug)
    if request.method == 'DELETE':
        preview_runner.stop(p)
        services.delete_workspace(p)
        name = p.name
        p.delete()
        return Response({'ok': True, 'message': 'پروژهٔ «%s» و پوشه‌اش حذف شد.' % name})
    running, port, _pid = preview_runner.status(p)
    apps = list(p.apps.prefetch_related('models__fields', 'views'))
    return Response({
        'project': project_json(p, detail=True),
        'apps': [app_json(a, models=True, counts=True) for a in apps],
        'pages': [page_json(pg) for pg in p.pages.all()],
        'builds': [build_json(b) for b in p.builds.all()[:8]],
        'model_count': Model.objects.filter(app__project=p).count(),
        'field_count': Field.objects.filter(model__app__project=p).count(),
        'view_count': View.objects.filter(app__project=p).count(),
        'route_count': len(generator.effective_routes(p)),
        'file_count': file_count(p),
        'preview_url': preview_url(request, port) if running else '',
        'history': vcs.log(p, 5),
        'proposals': [proposal_json(x) for x in p.ai_proposals.all()[:5]] if hasattr(p, 'ai_proposals') else [],
    })


# ──────────────────────────────────────────────── تنظیمات (settings.py گرافیکی)
@studio_api('GET', 'POST', 'PUT')
def project_settings(request, slug):
    p = _p(slug)
    if _is_write(request):
        post = _form(request)
        try:
            p.name = (post.get('name') or p.name).strip()
            p.site_title = (post.get('site_title') or p.name).strip()
            p.description = (post.get('description') or '').strip()
            p.brand_color = V.color(post.get('brand_color') or p.brand_color)
            if not p.is_imported:
                p.language_code = V.language(post.get('language_code'))
                p.time_zone = V.timezone_name(post.get('time_zone'))
                p.allowed_hosts = V.hosts(post.get('allowed_hosts'))
                p.extra_apps = V.dotted_lines(post.get('extra_apps'))
                p.extra_requirements = V.requirement_lines(post.get('extra_requirements'))
                p.custom_settings = V.python_code(post.get('custom_settings'), 'تنظیماتِ دستی')
        except ValueError as exc:
            return bad(exc)
        p.save()
        return Response({'ok': True, 'project': project_json(p, detail=True),
                         'message': 'تنظیمات ذخیره شد. برای نوشتن در config/settings.py «تولیدِ کد» را بزن.'})
    if p.is_imported:
        rel = p.settings_module_name.replace('.', '/') + '.py'
        code = read_text(p, rel)
    else:
        rel = 'config/settings.py'
        code = generator.ProjectGenerator(p).settings_code()
    import zoneinfo
    return Response({
        'project': project_json(p, detail=True), 'code': code, 'code_path': rel, 'languages': V.LANGUAGES,
        'timezones': sorted(z for z in zoneinfo.available_timezones() if '/' in z),
    })


# ──────────────────────────────────────────────── بک‌اندِ گرافیکی
@studio_api('GET')
def backend_studio(request, slug):
    p = _p(slug)
    apps = list(p.apps.prefetch_related('models__fields', 'views', 'routes'))
    return Response({
        'project': project_json(p),
        'apps': [app_json(a, models=True, counts=True) for a in apps],
        'er': er_data(p),
    })


@studio_api('POST')
def app_add(request, slug):
    p = _p(slug)
    post = _form(request)
    try:
        name = V.app_name(post.get('name'))
        prefix = V.url_prefix(post.get('url_prefix') or name)
    except ValueError as exc:
        return bad(exc, 'name')
    if p.apps.filter(name=name).exists():
        return bad('اپِ «%s» از قبل هست.' % name, 'name')
    if p.is_imported and os.path.exists(os.path.join(str(p.path), (p.apps_dir + '/' if p.apps_dir else '') + name)):
        return bad('پوشهٔ «%s» در پروژه از قبل هست؛ نامِ دیگری بگذار.' % name, 'name')
    app = App.objects.create(project=p, name=name, verbose_name_fa=(post.get('fa') or '').strip(),
                             description=(post.get('description') or '').strip(),
                             url_prefix=prefix, order=p.apps.count() * 10 + 100)
    return Response({'ok': True, 'app': app_json(app),
                     'message': 'اپِ «%s» ساخته شد. حالا مدل‌هایش را اضافه کن.' % name}, status=201)


@studio_api('GET', 'POST', 'PUT', 'DELETE')
def app_detail(request, slug, pk):
    p = _p(slug)
    app = get_object_or_404(App, pk=pk, project=p)
    if request.method == 'DELETE':
        if not app.managed:
            return read_only()
        if Field.objects.filter(related_model__app=app).exclude(model__app=app).exists():
            return bad('مدل‌های این اپ در اپ‌های دیگر رابطه دارند؛ اول آن فیلدها را حذف کن.')
        name = app.name
        app.delete()
        return Response({'ok': True, 'message': 'اپِ «%s» حذف شد. «تولیدِ کد» را بزن تا از settings هم برود '
                                                '(پوشه‌اش روی دیسک برای احتیاط می‌ماند).' % name})
    if _is_write(request):
        if not app.managed:
            return read_only()
        post = _form(request)
        try:
            app.verbose_name_fa = (post.get('fa') or '').strip()
            app.description = (post.get('description') or '').strip()
            app.url_prefix = V.url_prefix(post.get('url_prefix'))
        except ValueError as exc:
            return bad(exc, 'url_prefix')
        app.save()
        return Response({'ok': True, 'app': app_json(app), 'message': 'مشخصاتِ اپ ذخیره شد.'})
    code = {}
    if app.managed:
        files = generator.app_files(app, with_product_extras=(app.name == 'catalog' and not p.is_imported))
        code = {os.path.basename(k): v for k, v in files.items()}
    else:
        for name in ('models.py', 'views.py', 'urls.py', 'admin.py', 'forms.py'):
            txt = read_text(p, '%s/%s' % (app.dir, name))
            if txt:
                code[name] = txt
    return Response({
        'project': project_json(p), 'app': app_json(app),
        'models': [model_json(m, fields=True) for m in app.models.prefetch_related('fields')],
        'views': [view_json(v) for v in app.views.select_related('model').prefetch_related('routes__app')],
        'routes': [route_json(r) for r in app.routes.select_related('view', 'app')],
        'code': code, 'code_keys': list(code.keys()),
        'kinds': View.KIND,
        'all_models': [model_option(m) for m in Model.objects.filter(app__project=p).select_related('app')],
    })


@studio_api('POST')
def model_add(request, slug):
    p = _p(slug)
    post = _form(request)
    app = get_object_or_404(App, pk=post.get('app') or 0, project=p)
    if not app.managed:
        return read_only()
    try:
        name = V.model_name(post.get('name'))
    except ValueError as exc:
        return bad(exc, 'name')
    if Model.objects.filter(app__project=p, name=name).exists():
        return bad('مدلی به نامِ «%s» در پروژه هست.' % name, 'name')
    m = Model.objects.create(app=app, name=name, verbose_name_fa=(post.get('fa') or '').strip(),
                             verbose_plural_fa=(post.get('fa_plural') or '').strip(),
                             order=app.models.count() * 10 + 10)
    if post.get('starter') == 'on':
        Field.objects.create(model=m, name='title', verbose_name_fa='عنوان', field_type='CharField',
                             max_length=200, order=10)
        Field.objects.create(model=m, name='created_at', verbose_name_fa='تاریخِ ساخت',
                             field_type='DateTimeField', auto_now_add=True, order=20)
        m.ordering = '-created_at'
        m.save(update_fields=['ordering'])
    return Response({'ok': True, 'model': model_json(m, fields=True),
                     'message': 'مدلِ «%s» ساخته شد.' % m.name}, status=201)


@studio_api('GET', 'POST', 'PUT', 'DELETE')
def model_detail(request, slug, pk):
    p = _p(slug)
    m = get_object_or_404(Model.objects.select_related('app'), pk=pk, app__project=p)
    editable = m.managed and m.app.managed
    if request.method == 'DELETE':
        if not editable:
            return read_only()
        incoming = Field.objects.filter(related_model=m).exclude(model=m)
        if incoming.exists():
            return bad('این مدل در «%s» استفاده شده؛ اول آن رابطه‌ها را حذف کن.'
                       % '، '.join('%s.%s' % (f.model.name, f.name) for f in incoming[:5]))
        app_pk, name = m.app_id, m.name
        m.delete()
        return Response({'ok': True, 'app': app_pk,
                         'message': 'مدلِ «%s» و ویوهایش حذف شد. «تولیدِ کد» را بزن تا از فایل هم برود.' % name})
    if _is_write(request):
        if not editable:
            return read_only()
        post = _form(request)
        names = {f.name for f in m.fields.all()}
        m.verbose_name_fa = (post.get('fa') or '').strip()
        m.verbose_plural_fa = (post.get('fa_plural') or '').strip()
        m.has_str = post.get('has_str') == 'on'
        m.str_field = post.get('str_field') if post.get('str_field') in names else ''
        order = [x for x in re.split(r'[,\s،]+', post.get('ordering') or '') if x]
        badf = [x for x in order if x.lstrip('-') not in names | {'id', 'pk'}]
        if badf:
            return bad('ترتیب: فیلدِ «%s» در این مدل نیست.' % ', '.join(badf), 'ordering')
        m.ordering = ', '.join(order)
        m.in_admin = post.get('in_admin') == 'on'
        for key in ('admin_list_display', 'admin_search_fields', 'admin_list_filter'):
            vals = [x for x in post.getlist(key) if x in names]
            setattr(m, key, ', '.join(vals))
        m.save()
        return Response({'ok': True, 'model': model_json(m, fields=True), 'message': 'مشخصاتِ مدل ذخیره شد.'})
    fields = list(m.fields.select_related('related_model__app'))
    return Response({
        'project': project_json(p), 'model': model_json(m), 'fields': [field_json(f) for f in fields],
        'app': app_json(m.app), 'editable': editable,
        'field_types': [t for t in Field.TYPES if t[0] != 'custom'] if editable else Field.TYPES,
        'on_delete': Field.ON_DELETE,
        'all_models': [model_option(x) for x in Model.objects.filter(app__project=p).select_related('app')],
        'incoming': [{'id': f.id, 'model_id': f.model_id,
                      'label': '%s.%s.%s' % (f.model.app.name, f.model.name, f.name)}
                     for f in Field.objects.filter(related_model=m).select_related('model__app')],
        'code': generator.model_code(m),
        'views': [view_json(v) for v in m.views.select_related('app').prefetch_related('routes__app')],
    })


@studio_api('POST')
def model_crud(request, slug, pk):
    p = _p(slug)
    m = get_object_or_404(Model, pk=pk, app__project=p)
    if not m.app.managed:
        return read_only()
    post = _form(request)
    kinds = [k for k in post.getlist('kinds') if k in services.CRUD_ORDER] or None
    made = services.add_crud(m, kinds)
    if made:
        msg = '%d ویو با نشانی و قالب ساخته شد: %s. «تولیدِ کد» را بزن.' % (len(made), '، '.join(v.name for v in made))
    else:
        msg = 'همهٔ این ویوها از قبل ساخته شده بودند.'
    return Response({'ok': True, 'made': [view_json(v) for v in made], 'app': m.app_id, 'message': msg})


# ──────────────────────────────────────────────── فیلدها
@studio_api('POST')
def field_add(request, slug):
    p = _p(slug)
    post = _form(request)
    mdl = get_object_or_404(Model, pk=post.get('model') or 0, app__project=p)
    if not (mdl.managed and mdl.app.managed):
        return read_only()
    fld = Field(model=mdl, order=(mdl.fields.count() + 1) * 10)
    try:
        apply_field_post(fld, post, p)
        if Field.objects.filter(model=mdl, name=fld.name).exists():
            raise ValueError('فیلدِ «%s» در این مدل از قبل هست.' % fld.name)
        fld.save()
    except (ValueError, IntegrityError) as exc:
        return bad(exc)
    return Response({'ok': True, 'field': field_json(fld),
                     'message': 'فیلدِ «%s» به %s اضافه شد.' % (fld.name, mdl.name)}, status=201)


@studio_api('GET', 'POST', 'PUT', 'DELETE')
def field_detail(request, slug, pk):
    p = _p(slug)
    fld = get_object_or_404(Field.objects.select_related('model__app'), pk=pk, model__app__project=p)
    editable = fld.model.managed and fld.model.app.managed
    if request.method == 'DELETE':
        if not editable:
            return read_only()
        mpk, name = fld.model_id, fld.name
        fld.delete()
        return Response({'ok': True, 'model': mpk, 'message': 'فیلدِ «%s» حذف شد.' % name})
    if _is_write(request):
        if not editable:
            return read_only()
        old_name = fld.name
        try:
            apply_field_post(fld, _form(request), p)
            if fld.name != old_name and Field.objects.filter(model=fld.model, name=fld.name).exists():
                raise ValueError('فیلدِ «%s» در این مدل از قبل هست.' % fld.name)
            fld.save()
        except (ValueError, IntegrityError) as exc:
            return bad(exc)
        return Response({'ok': True, 'field': field_json(fld),
                         'message': 'فیلدِ «%s» ذخیره شد. «تولیدِ کد» و بعد «مهاجرت» را بزن.' % fld.name})
    return Response({
        'project': project_json(p), 'field': field_json(fld), 'model': model_json(fld.model), 'editable': editable,
        'field_types': [t for t in Field.TYPES if t[0] != 'custom'],
        'on_delete': Field.ON_DELETE,
        'all_models': [model_option(x) for x in Model.objects.filter(app__project=p).select_related('app')],
        'code': generator.field_code(fld) if editable or fld.field_type != 'custom' else fld.raw_code,
    })


@studio_api('POST')
def field_move(request, slug, pk):
    p = _p(slug)
    fld = get_object_or_404(Field, pk=pk, model__app__project=p)
    fields = list(fld.model.fields.all())
    i = fields.index(fld)
    j = i - 1 if _form(request).get('dir') == 'up' else i + 1
    if 0 <= j < len(fields):
        fields[i], fields[j] = fields[j], fields[i]
        for n, f in enumerate(fields, 1):
            if f.order != n * 10:
                Field.objects.filter(pk=f.pk).update(order=n * 10)
    return Response({'ok': True, 'fields': [field_json(f) for f in fld.model.fields.select_related('related_model__app')]})


# ──────────────────────────────────────────────── ویوها
@studio_api('POST')
def view_add(request, slug):
    p = _p(slug)
    post = _form(request)
    app = get_object_or_404(App, pk=post.get('app') or 0, project=p)
    if not app.managed:
        return read_only()
    kind = post.get('kind') or 'template'
    if kind not in dict(View.KIND):
        kind = 'template'
    model = None
    if kind in View.NEEDS_MODEL:
        model = Model.objects.filter(pk=post.get('model') or 0, app__project=p).first()
        if model is None:
            return bad('این نوع ویو یک مدل لازم دارد.', 'model')
    try:
        name = V.view_name(post.get('name') or ('%s_%s' % (model.snake, kind) if model else ''))
    except ValueError as exc:
        return bad(exc, 'name')
    if app.views.filter(name=name).exists():
        return bad('ویوی «%s» در این اپ هست.' % name, 'name')
    extra = {'description': (post.get('description') or '').strip(),
             'login_required': post.get('login_required') == 'on'}
    if kind == 'custom':
        extra['custom_code'] = ('def %s(request):\n    """%s"""\n    from django.http import HttpResponse\n'
                                '    return HttpResponse("سلام از %s")\n' % (name, extra['description'] or name, name))
    v = services.add_view(app, name, kind, model, with_route=post.get('route') == 'on', **extra)
    return Response({'ok': True, 'view': view_json(v),
                     'message': 'ویوی «%s» ساخته شد%s.' % (v.name, ' و نشانی‌اش هم' if v.routes.exists() else '')},
                    status=201)


@studio_api('GET', 'POST', 'PUT', 'DELETE')
def view_detail(request, slug, pk):
    p = _p(slug)
    v = get_object_or_404(View.objects.select_related('app', 'model'), pk=pk, app__project=p)
    editable = v.managed and v.app.managed
    if request.method == 'DELETE':
        if not editable:
            return read_only()
        app_pk, name = v.app_id, v.name
        Route.objects.filter(view=v, managed=True).delete()
        v.delete()
        return Response({'ok': True, 'app': app_pk, 'message': 'ویوی «%s» و نشانی‌اش حذف شد.' % name})
    if _is_write(request):
        if not editable:
            return read_only()
        post = _form(request)
        try:
            kind = post.get('kind') or v.kind
            if kind not in dict(View.KIND):
                raise ValueError('نوعِ ویو ناشناخته است.')
            v.kind = kind
            if kind in View.NEEDS_MODEL:
                m = Model.objects.filter(pk=post.get('model') or 0, app__project=p).first()
                if m is None:
                    raise ValueError('این نوع ویو یک مدل لازم دارد.')
                v.model = m
            v.description = (post.get('description') or '').strip()
            v.login_required = post.get('login_required') == 'on'
            pb = (post.get('paginate_by') or '').strip()
            v.paginate_by = int(pb) if pb.isdigit() and int(pb) > 0 else None
            names = {f.name for f in v.model.fields.all()} if v.model_id else set()
            order = [x for x in re.split(r'[,\s،]+', post.get('ordering') or '') if x]
            if any(x.lstrip('-') not in names | {'id', 'pk'} for x in order):
                raise ValueError('ترتیب: فیلدی در مدل نیست.')
            v.ordering = ', '.join(order)
            v.form_fields = ', '.join(x for x in post.getlist('form_fields') if x in names)
            v.success_url_name = V.url_name(post.get('success_url_name'))
            con = (post.get('context_object_name') or '').strip()
            if con and not re.fullmatch(r'[a-z_][a-z0-9_]*', con):
                raise ValueError('نامِ متغیر در قالب باید انگلیسیِ کوچک باشد.')
            v.context_object_name = con
            if 'template_body' in post:
                v.template_body = post.get('template_body') or ''
                v.css = post.get('css') or ''
            if kind == 'custom':
                v.custom_code = V.python_code(post.get('custom_code'), 'کدِ ویو')
                if not re.search(r'^\s*(def|class)\s+\w+', v.custom_code, re.M):
                    raise ValueError('کدِ ویو باید یک def یا class داشته باشد.')
        except ValueError as exc:
            return bad(exc)
        v.save()
        return Response({'ok': True, 'view': view_json(v), 'code': safe_view_code(v) if editable else v.custom_code,
                         'message': 'ویو ذخیره شد. «تولیدِ کد» را بزن.'})
    model_fields = list(v.model.fields.all()) if v.model_id else []
    return Response({
        'project': project_json(p), 'view': view_json(v), 'app': app_json(v.app), 'editable': editable,
        'kinds': View.KIND, 'needs_model': sorted(View.NEEDS_MODEL),
        'all_models': [model_option(x) for x in Model.objects.filter(app__project=p).select_related('app')],
        'model_fields': [field_json(f) for f in model_fields], 'chosen_fields': v.field_list,
        'url_names': generator.url_names(p),
        'code': safe_view_code(v) if editable else v.custom_code,
        'shared': shared_parts(p),
    })


@studio_api('POST')
def view_reset(request, slug, pk):
    p = _p(slug)
    v = get_object_or_404(View, pk=pk, app__project=p)
    msg = ''
    if v.managed and v.needs_template:
        v.template_body = generator.default_template_body(v)
        v.save(update_fields=['template_body'])
        msg = 'قالبِ پیش‌فرض با نشانی‌های فعلی دوباره ساخته شد.'
    return Response({'ok': True, 'view': view_json(v), 'message': msg})


# ──────────────────────────────────────────────── نشانی‌ها (URL)
def _routes_ctx(p):
    return {
        'apps': [app_json(a) for a in p.apps.filter(managed=True)],
        'views': [view_option(v) for v in View.objects.filter(app__project=p, app__managed=True).select_related('app')],
    }


@studio_api('GET', 'POST')
def routes_page(request, slug):
    p = _p(slug)
    if request.method == 'POST':
        r = Route(project=p, order=(p.routes.count() + 1) * 10)
        try:
            apply_route_post(r, _form(request), p)
            r.save()
        except ValueError as exc:
            return bad(exc)
        return Response({'ok': True, 'route': route_json(r),
                         'message': 'نشانیِ /%s ساخته شد.' % r.full_pattern}, status=201)
    running, port, _ = preview_runner.status(p)
    base = preview_url(request, port) if running else ''
    d = {'project': project_json(p), 'rows': route_rows(p, base)}
    d.update(_routes_ctx(p))
    return Response(d)


@studio_api('GET', 'POST', 'PUT', 'DELETE')
def route_detail(request, slug, pk):
    p = _p(slug)
    r = get_object_or_404(Route, pk=pk, project=p)
    if request.method == 'DELETE':
        if not r.managed:
            return read_only()
        r.delete()
        return Response({'ok': True, 'message': 'نشانی حذف شد.'})
    if _is_write(request):
        if not r.managed:
            return read_only()
        try:
            apply_route_post(r, _form(request), p)
            r.save()
        except ValueError as exc:
            return bad(exc)
        return Response({'ok': True, 'route': route_json(r), 'message': 'نشانی ذخیره شد.'})
    d = {'project': project_json(p), 'route': route_json(r)}
    d.update(_routes_ctx(p))
    return Response(d)


# ──────────────────────────────────────────────── فرانتِ سه‌بخشی
@studio_api('GET')
def frontend_studio(request, slug):
    p = _p(slug)
    parts = {s.kind: True for s in p.shared_parts.all() if s.content.strip()}
    return Response({
        'project': project_json(p), 'pages': [page_json(pg) for pg in p.pages.all()], 'parts': parts,
        'kinds': [k for k in Page.KIND if k[0] != 'imported'],
        'view_templates': [view_json(v, with_routes=False)
                           for v in View.objects.filter(app__project=p, app__managed=True).exclude(kind='custom')
                                                .select_related('app', 'model')],
    })


@studio_api('POST')
def page_add(request, slug):
    p = _p(slug)
    if p.is_imported:
        return bad('در پروژهٔ واردشده صفحهٔ تازه را با «ویوی قالبی» در یک اپِ تازه بساز.')
    post = _form(request)
    title = (post.get('title') or '').strip()
    try:
        pslug = V.page_slug(post.get('slug'))
    except ValueError as exc:
        return bad(exc, 'slug')
    if not title:
        return bad('عنوانِ صفحه لازم است.', 'title')
    if p.pages.filter(slug=pslug).exists():
        return bad('صفحه‌ای با نشانیِ «/%s» از قبل هست.' % pslug, 'slug')
    kind = post.get('kind') or 'static'
    if kind not in dict(Page.KIND) or kind == 'imported':
        kind = 'static'
    body = generator.DEFAULT_BODIES[kind] if kind in generator.DEFAULT_BODIES else generator.DEFAULT_BODY % {'title': title}
    pg = Page.objects.create(project=p, slug=pslug, title=title, kind=kind, body_html=body,
                             order=p.pages.count() * 10 + 10)
    return Response({'ok': True, 'page': page_json(pg), 'message': 'صفحهٔ «%s» اضافه شد.' % title}, status=201)


@studio_api('GET', 'POST', 'PUT', 'DELETE')
def page_detail(request, slug, pk):
    p = _p(slug)
    page = get_object_or_404(Page, pk=pk, project=p)
    if request.method == 'DELETE':
        if page.is_imported:
            return bad('قالبِ واردشده حذف نمی‌شود (فایلِ خودِ پروژه است).')
        page.delete()
        return Response({'ok': True, 'message': 'صفحه حذف شد.'})
    if _is_write(request):
        post = _form(request)
        page.body_html = (post.get('body_html') or '').replace('\r\n', '\n')
        if not page.is_imported:
            page.title = (post.get('title') or page.title).strip()
            page.css = (post.get('css') or '').replace('\r\n', '\n')
            page.in_menu = post.get('in_menu') == 'on'
        page.save()
        return Response({'ok': True, 'page': page_json(page, body=True),
                         'message': 'صفحه ذخیره شد. برای نوشتن در فایل «تولیدِ کد» را بزن.'})
    drift = False
    if page.is_imported:
        from apps.project_importer.importer import disk_drift
        drift = disk_drift(page)
    return Response({
        'project': project_json(p), 'page': page_json(page, body=True), 'drift': drift,
        'shared': shared_parts(p),
        'recent': [proposal_json(x) for x in p.ai_proposals.filter(changes__page=page).distinct()[:5]],
    })


SHARED_TARGETS = {
    'header': 'templates/components/header.html',
    'footer': 'templates/components/footer.html',
    'base_css': 'static/css/base.css',
}


@studio_api('GET', 'POST', 'PUT')
def shared_detail(request, slug, kind):
    p = _p(slug)
    if kind not in dict(SharedPart.KIND):
        raise Http404
    part, _ = SharedPart.objects.get_or_create(project=p, kind=kind)
    if _is_write(request):
        part.content = (_form(request).get('content') or '').replace('\r\n', '\n')
        part.save()
        return Response({'ok': True, 'part': shared_json(part),
                         'message': '«%s» ذخیره شد — روی همهٔ صفحه‌ها اثر دارد.' % part.get_kind_display()})
    defaults = {
        'header': generator.DEFAULT_HEADER,
        'footer': generator.DEFAULT_FOOTER,
        'base_css': generator.BASE_CSS % {'brand': p.brand_color},
    }
    return Response({
        'project': project_json(p), 'part': shared_json(part), 'default_content': defaults[kind],
        'target_file': SHARED_TARGETS[kind], 'placeholder': 'خالی = پیش‌فرضِ استودیو',
        'shared': shared_parts(p),
    })


# ──────────────────────────────────────────────── فایل‌ها
@studio_api('GET')
def file_browser(request, slug):
    p = _p(slug)
    tree, groups = file_tree(p)
    return Response({'project': project_json(p), 'tree': tree, 'groups': groups, 'mark': generator.CUSTOM_MARK})


@studio_api('GET')
def file_read(request, slug):
    p = _p(slug)
    rel = request.query_params.get('f') or ''
    if not rel:
        raise Http404('فایل پیدا نشد.')
    content, custom_zone = file_content(p, rel)
    return Response({'rel': rel, 'content': content, 'custom_zone': custom_zone, 'mark': generator.CUSTOM_MARK})


# ──────────────────────────────────────────────── تاریخچه (Git)
@studio_api('GET')
def history(request, slug):
    p = _p(slug)
    return Response({'project': project_json(p), 'commits': vcs.log(p, 80), 'git': vcs.available()})


@studio_api('GET')
def history_commit(request, slug, sha):
    p = _p(slug)
    commit = vcs.show(p, sha)
    if commit is None:
        raise Http404('نسخه پیدا نشد.')
    return Response(commit)


# ──────────────────────────────────────────────── پیش‌نمایشِ زنده
def _preview_state(request, p):
    running, port, pid = preview_runner.status(p)
    user, password = preview_runner.admin_login(p)
    return {
        'project': project_json(p), 'running': running, 'port': port, 'pid': pid,
        'url': preview_url(request, port) if running else '',
        'log': preview_runner.log_tail(p, 3000),
        'admin_user': user, 'admin_password': password,
        'own_env': envs.has_own_env(p), 'exists_on_disk': p.exists_on_disk,
    }


@studio_api('GET')
def preview(request, slug):
    return Response(_preview_state(request, _p(slug)))


@studio_api('POST')
def preview_start(request, slug):
    p = _p(slug)
    if not p.exists_on_disk:
        return bad('اول «تولیدِ کد» را بزن.')
    ok, msg = True, ''
    try:
        port, pid = preview_runner.start(p)
        if preview_runner.status(p)[0]:
            msg = 'پیش‌نمایش روی پورتِ %d روشن شد.' % port
        else:
            ok, msg = False, 'پیش‌نمایش بالا نیامد — لاگِ پایین را ببین.'
    except Exception as exc:  # noqa
        ok, msg = False, 'پیش‌نمایش روشن نشد: %s' % exc
    d = _preview_state(request, p)
    d.update({'ok': ok, 'message': msg})
    return Response(d)


@studio_api('POST')
def preview_stop(request, slug):
    p = _p(slug)
    preview_runner.stop(p)
    d = _preview_state(request, p)
    d.update({'ok': True, 'message': 'پیش‌نمایش خاموش شد.'})
    return Response(d)


# ──────────────────────────────────────────────── عملیات
@studio_api('POST')
def do_build(request, slug):
    p = _p(slug)
    ok, summary, detail = services.generate(p, (_form(request).get('message') or '').strip() or None)
    msg = ('کد تولید و وارسی شد — %s.' % summary) if ok else 'تولید/وارسی خطا داد — جزئیات در «نمای کلی».'
    # اگر پیش‌نمایش روشن است، با کدِ تازه دوباره بالا بیاید
    if preview_runner.status(p)[0]:
        preview_runner.stop(p)
        try:
            preview_runner.start(p)
        except Exception:  # noqa
            pass
    p.refresh_from_db()
    return Response({'ok': ok, 'summary': summary, 'detail': detail, 'message': msg,
                     'project': project_json(p, detail=True)})


@studio_api('POST')
def do_migrate(request, slug):
    p = _p(slug)
    if not p.exists_on_disk:
        return bad('اول «تولیدِ کد» را بزن.')
    ok, detail = services.migrate(p)
    BuildLog.objects.create(project=p, ok=ok, summary='مهاجرت', detail=detail)
    msg = 'مهاجرت انجام شد (جدول‌های دیتابیس به‌روز شد).' if ok else 'مهاجرت خطا داد — جزئیات در گزارشِ تولیدها.'
    return Response({'ok': ok, 'detail': detail, 'message': msg, 'project': project_json(p, detail=True)})


@studio_api('GET')
def do_export(request, slug):
    p = _p(slug)
    if not p.exists_on_disk:
        return bad('اول «تولیدِ کد» را بزن.')
    with_git = request.query_params.get('git') == '1'
    buf = services.export_zip(p, with_git=with_git)
    return FileResponse(buf, as_attachment=True, content_type='application/zip',
                        filename='%s%s.zip' % (p.slug, '-git' if with_git else ''))
