# -*- coding: utf-8 -*-
"""APIِ واردکردنِ پروژهٔ جنگوی موجود: فرم/اجرای واردکردن، گزارشِ سازگاری،
نصبِ وابستگی‌ها در محیطِ جدا، بازخوانیِ قالب از دیسک."""
import json
import re

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.code_generation import envs, preview_runner
from apps.projects.helpers import FormData, app_json, page_json, project_json
from apps.projects.models import Project
from . import importer


def studio_api(*methods):
    def deco(fn):
        return api_view(list(methods))(permission_classes([permissions.IsAdminUser])(fn))
    return deco


def bad(msg, field=None, code=400):
    body = {'error': str(msg)}
    if field:
        body['errors'] = {field: str(msg)}
    return Response(body, status=code)


@studio_api('GET', 'POST')
def import_form(request):
    if request.method == 'POST':
        post = FormData(request.data)
        name = (post.get('name') or '').strip()
        slug = re.sub(r'[^a-z0-9-]', '', (post.get('slug') or '').strip().lower())
        f = request.FILES.get('zip')
        server_path = (post.get('server_path') or '').strip()
        if not name:
            return bad('نامِ پروژه لازم است.', 'name')
        if slug and Project.objects.filter(slug=slug).exists():
            return bad('شناسهٔ «%s» قبلاً استفاده شده.' % slug, 'slug')
        if not f and not server_path:
            return bad('یا فایلِ ZIP بده یا مسیرِ پوشه روی سرور.', 'zip')
        try:
            p, report = importer.import_project(name, slug, zip_file=f, server_path=server_path or None)
        except importer.ImportError_ as exc:
            return bad('وارد نشد: %s' % exc)
        return Response({'ok': True, 'project': project_json(p), 'report': _report_json(report),
                         'message': 'پروژه وارد و تحلیل شد — گزارشِ سازگاری را ببین.'}, status=201)
    return Response({'roots': list(getattr(settings, 'IMPORT_SERVER_ROOTS', []))})


def _report_json(report):
    return {'level': report.level, 'level_display': report.get_level_display(),
            'warnings': report.warning_list, 'unsupported': report.unsupported_list,
            'created_at': report.created_at.isoformat() if report.created_at else None}


@studio_api('GET')
def import_report(request, slug):
    p = get_object_or_404(Project, slug=slug)
    report = getattr(p, 'import_report', None)
    if report is None:
        return Response({'error': 'این پروژه واردشده نیست.'}, status=404)
    try:
        data = json.loads(report.data or '{}')
    except ValueError:
        data = {}
    apps = list(p.apps.prefetch_related('models', 'views', 'routes'))
    return Response({
        'project': project_json(p, detail=True), 'report': _report_json(report), 'data': data,
        'apps': [app_json(a, counts=True) for a in apps],
        'pages': [page_json(pg) for pg in p.pages.filter(kind='imported')],
        'model_count': sum(a.models.count() for a in apps),
        'route_count': p.routes.count(),
        'deps_status': envs.status(p), 'deps_log': envs.log_tail(p, 5000),
        'own_env': envs.has_own_env(p),
        'preview_running': preview_runner.status(p)[0],
    })


@studio_api('POST')
def deps_install(request, slug):
    p = get_object_or_404(Project, slug=slug)
    if envs.install(p):
        msg = ('ساختِ محیطِ جدا و نصبِ وابستگی‌ها شروع شد؛ چند دقیقه طول می‌کشد. '
               'همین صفحه وضعیت را نشان می‌دهد.')
        started = True
    else:
        msg, started = 'نصب در حالِ اجراست.', False
    return Response({'ok': True, 'started': started, 'message': msg, 'deps_status': envs.status(p)})


@studio_api('POST')
def page_reload(request, slug, pk):
    """فایلِ روی دیسک را دوباره بخوان (وقتی بیرون از استودیو عوض شده)."""
    p = get_object_or_404(Project, slug=slug)
    page = get_object_or_404(p.pages, pk=pk)
    msg = ''
    if page.file_path:
        importer.reload_page_from_disk(page)
        msg = 'از روی فایل بازخوانی شد.'
    return Response({'ok': True, 'page': page_json(page, body=True), 'message': msg})
