"""REST API (DRF) — زیرِ /api/v1/up3d/ (api_urls.py). پروتکلِ کارگر زیرِ /3d/api/worker/ (urls.py).

همهٔ نماهای پنل فقط برای کارکنان (is_staff) باز است؛ احراز هویت همان پیش‌فرضِ DRF (JWT، سشن، توکن).

/api/v1/up3d/video-projects/              GET فهرست · POST ساخت {brief, mode: ai|template, template}
/api/v1/up3d/video-projects/<id>/         GET وضعیت، نسخهٔ فعلی، کارها، خطاها
/api/v1/up3d/video-projects/<id>/plan/    POST برنامه‌ریزیِ دوباره (AI یا قالب)
/api/v1/up3d/video-projects/<id>/scene/   GET سند · PUT سندِ تازه (وارسی + نسخهٔ تازه) · ?repair=1
/api/v1/up3d/video-projects/<id>/edit/    POST ویرایش با زبانِ طبیعی {instruction}
/api/v1/up3d/video-projects/<id>/preview/ POST {profile: animatic|preview}
/api/v1/up3d/video-projects/<id>/render/  POST {profile: standard|high|ultra|...}
/api/v1/up3d/video-projects/<id>/export/  POST {format: glb|fbx|usd|blend}
/api/v1/up3d/video-projects/<id>/result/  GET آخرین ویدئوی کامل
/api/v1/up3d/scenes/                 POST {title, document} (برای SDK)
/api/v1/up3d/validate/               POST {document, repair}
/api/v1/up3d/jobs/  ·  jobs/<id>/  ·  jobs/<id>/cancel/
/api/v1/up3d/assets/?kind=...        دفترِ دارایی‌ها
/api/v1/up3d/estimate/?profile=&project=  تخمینِ زمان
/3d/api/worker/...                   پروتکلِ کارگر (توکنِ کارگر)
"""
import os

from django.contrib.auth.models import AnonymousUser
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import authentication, exceptions, permissions
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from up3d import director
from up3d.validate import repair, validate

from . import services as SV
from .models import Job, Project, Worker


def panel_view(methods):
    """نمای پنل: احراز هویتِ پیش‌فرضِ DRF (JWT، سشن، توکن) + فقط کارکنان (is_staff)."""
    def deco(fn):
        return api_view(methods)(permission_classes([permissions.IsAdminUser])(fn))
    return deco


# ───────────────────────── نمایش

def job_json(j, light=False):
    d = {'id': j.pk, 'uid': str(j.uid), 'kind': j.kind, 'kind_label': j.get_kind_display(), 'profile': j.profile,
         'state': j.state, 'state_label': j.get_state_display(), 'progress': round(j.progress, 3),
         'frames_done': j.frames_done, 'frames_total': j.frames_total, 'sec_per_frame': j.sec_per_frame,
         'message': j.message, 'error': (j.error or '')[-600:] if j.state == 'FAILED' else '',
         'worker': j.worker.name if j.worker else None, 'estimate_seconds': j.estimate_seconds,
         'created': j.created, 'started': j.started, 'finished': j.finished, 'final': j.final,
         'project': j.project_id, 'project_title': j.project.title if j.project_id else None,
         'version': j.version.number if j.version else None,
         'files': {k: SV.file_url(v) for k, v in (j.files or {}).items()}, 'cancel_requested': j.cancel_requested,
         'quality': (j.params or {}).get('quality') or None}
    if j.started and not j.final and j.state == 'RENDERING' and j.sec_per_frame and j.frames_total:
        d['eta_seconds'] = round((j.frames_total - j.frames_done) * j.sec_per_frame)
    # کارِ بی‌کارگر: پنل باید بگوید چرا منتظر است و چه کارگری می‌تواند بگیرد (نه فقط «منتظرِ کارگر»)
    d['waiting'] = SV.waiting_info(j) if (j.owner == 'worker' and j.worker_id is None and not j.final) else None
    if not light:
        d.update({'log': j.log[-8000:], 'qc': j.qc, 'report': j.report, 'params': {k: v for k, v in j.params.items()
                                                                                    if k != 'document'}})
    return d


def project_json(p, full=True):
    v = p.current
    d = {'id': p.pk, 'uid': str(p.uid), 'title': p.title, 'brief': p.brief, 'created': p.created, 'updated': p.updated,
         'poster': SV.file_url(p.poster), 'version': v.number if v else None, 'valid': v.valid if v else False}
    lv = p.latest_video()
    d['result'] = {'video': SV.file_url((lv.files or {}).get('final.mp4')), 'poster': SV.file_url((lv.files or {}).get('poster.jpg')),
                   'job': lv.pk, 'profile': lv.profile, 'qc': (lv.qc or {}).get('result')} if lv else None
    if full:
        d['document'] = v.document if v else None
        d['report'] = v.report if v else None
        d['jobs'] = [job_json(j, True) for j in p.jobs.select_related('worker', 'version', 'project')[:30]]
        d['versions'] = [{'number': x.number, 'source': x.source, 'note': x.note, 'valid': x.valid, 'created': x.created}
                         for x in p.versions.all()[:50]]
    return d


# ───────────────────────── پروژه‌ها

@panel_view(['GET', 'POST'])
def projects(request):
    if request.method == 'GET':
        qs = Project.objects.exclude(title='__thumbnails__').select_related('current')[:100]
        return Response([project_json(p, False) for p in qs])
    data = request.data or {}
    p, job = SV.create_project(request.user, data.get('brief') or {}, data.get('mode', 'ai'), data.get('template', 'showcase'),
                               data.get('title'))
    return Response({'project': project_json(p, False), 'job': job_json(job, True)}, status=201)


@panel_view(['GET', 'DELETE'])
def project_detail(request, pk):
    p = get_object_or_404(Project, pk=pk)
    if request.method == 'DELETE':
        p.delete()
        return Response(status=204)
    return Response(project_json(p))


@panel_view(['POST'])
def project_plan(request, pk):
    p = get_object_or_404(Project, pk=pk)
    brief = request.data.get('brief') or p.brief
    if request.data.get('brief'):
        p.brief = brief
        p.save(update_fields=['brief'])
    job = Job.objects.create(project=p, kind='plan', params={'mode': request.data.get('mode', 'ai'),
                                                             'template': request.data.get('template', 'showcase'),
                                                             'brief': brief})
    return Response(job_json(job, True), status=201)


@panel_view(['GET', 'PUT', 'POST'])
def project_scene(request, pk):
    p = get_object_or_404(Project, pk=pk)
    if request.method == 'GET':
        v = p.current
        if request.query_params.get('version'):
            if not str(request.query_params['version']).isdigit():
                raise exceptions.ValidationError('version باید عدد باشد')
            v = get_object_or_404(p.versions, number=int(request.query_params['version']))
        return Response({'version': v.number if v else None, 'document': v.document if v else None,
                         'report': v.report if v else None})
    doc = request.data.get('document')
    if not isinstance(doc, dict):
        raise exceptions.ValidationError('document لازم است')
    v = SV.new_version(p, doc, request.data.get('source', 'editor'), request.data.get('note', ''),
                       auto_repair=bool(request.data.get('repair') or request.query_params.get('repair')))
    return Response({'version': v.number, 'valid': v.valid, 'report': v.report, 'document': v.document})


@panel_view(['POST'])
def project_edit(request, pk):
    p = get_object_or_404(Project, pk=pk)
    ins = (request.data.get('instruction') or '').strip()
    if not ins:
        raise exceptions.ValidationError('دستورِ ویرایش خالی است')
    try:
        v, info = SV.ai_edit(p, ins, request.user)
    except director.DirectorError as e:
        return Response({'error': str(e)}, status=400)
    return Response({'version': v.number, 'valid': v.valid, 'diff': info['diff'], 'repairs': info['repairs'],
                     'document': v.document, 'report': v.report})


def _job_request(request, pk, kind, default_profile):
    p = get_object_or_404(Project, pk=pk)
    params = {k: v for k, v in request.data.items() if k in ('format', 'count', 'allow_cpu')}
    if isinstance(request.data.get('quality'), dict):
        params['quality'] = request.data['quality']       # SV.request_job ⇐ clean_quality (وارسی + بازه)
    try:
        job = SV.request_job(p, kind, request.data.get('profile') or default_profile, params)
    except ValueError as e:
        return Response({'error': str(e)}, status=400)
    return Response(job_json(job, True), status=201)


@panel_view(['POST'])
def project_preview(request, pk):
    return _job_request(request, pk, 'render', 'preview')


@panel_view(['POST'])
def project_render(request, pk):
    return _job_request(request, pk, 'render', 'high')


@panel_view(['POST'])
def project_export(request, pk):
    return _job_request(request, pk, 'export', 'animatic')


@panel_view(['POST'])
def project_contact(request, pk):
    return _job_request(request, pk, 'contact', 'preview')


@panel_view(['GET'])
def project_result(request, pk):
    p = get_object_or_404(Project, pk=pk)
    lv = p.latest_video()
    if not lv:
        return Response({'ready': False, 'message': 'هنوز ویدئوی کاملی نیست'})
    return Response({'ready': True, 'video': request.build_absolute_uri(SV.file_url(lv.files.get('final.mp4'))),
                     'poster': request.build_absolute_uri(SV.file_url(lv.files.get('poster.jpg', ''))),
                     'profile': lv.profile, 'qc': lv.qc, 'job': lv.pk})


@panel_view(['POST'])
def scenes(request):
    doc = request.data.get('document')
    if not isinstance(doc, dict):
        raise exceptions.ValidationError('document لازم است')
    p = Project.objects.create(title=request.data.get('title') or (doc.get('meta') or {}).get('title') or 'صحنهٔ API',
                               brief={}, owner=request.user)
    v = SV.new_version(p, doc, request.data.get('source', 'api'), 'از API', auto_repair=True)
    return Response({'id': p.pk, 'version': v.number, 'valid': v.valid, 'report': v.report}, status=201)


@panel_view(['POST'])
def validate_doc(request):
    doc = request.data.get('document') or {}
    if request.data.get('repair'):
        new, changes, rep = repair(doc, SV.reg())
        return Response({**rep.to_dict(), 'changes': changes, 'document': new})
    return Response(validate(doc, SV.reg()).to_dict())


@panel_view(['GET'])
def job_detail(request, pk):
    return Response(job_json(get_object_or_404(Job, pk=pk)))


@panel_view(['POST'])
def job_cancel(request, pk):
    j = get_object_or_404(Job, pk=pk)
    SV.cancel(j)
    return Response(job_json(j, True))


@panel_view(['POST'])
def job_allow_cpu(request, pk):
    """کارِ منتظرِ کارگرِ GPU ⇐ اجازهٔ اجرا روی کارگرِ CPU (کند ولی راه می‌افتد). فقط تا وقتی کارگری نگرفته."""
    j = get_object_or_404(Job, pk=pk)
    if j.final or j.worker_id:
        return Response({'error': 'این کار دیگر منتظرِ کارگر نیست'}, status=400)
    j.params = {**(j.params or {}), 'allow_cpu': True}
    est = SV.estimate(j.profile, j.frames_total or 0, allow_cpu=True, quality=j.params.get('quality'))
    j.estimate_seconds = est['seconds']
    j.add_log('اجازهٔ اجرا روی CPU داده شد (%s)' % (
        'کارگر: %s، تخمین ~%d دقیقه' % (est['worker'], max(1, est['seconds'] // 60)) if est['available']
        else 'فعلاً هیچ کارگری آنلاین نیست'), save=False)
    if j.state == 'SCENE_BUILDING' and j.owner == 'worker':
        j.message = ('منتظرِ کارگر — اجازهٔ CPU داده شد؛ کارگرِ آماده: %s' % '، '.join(SV.eligible_workers(j))
                     if SV.eligible_workers(j) else 'منتظرِ کارگر — اجازهٔ CPU داده شد ولی هیچ کارگری آنلاین نیست')[:400]
    j.save()
    return Response(job_json(j, True))


@panel_view(['GET'])
def jobs_list(request):
    qs = Job.objects.select_related('worker', 'version', 'project').exclude(project__title='__thumbnails__')
    if request.query_params.get('active'):
        qs = qs.exclude(state__in=('COMPLETED', 'FAILED', 'CANCELLED'))
    return Response([job_json(j, True) for j in qs[:60]])


@panel_view(['GET'])
def assets(request):
    kind = request.query_params.get('kind')
    return Response(SV.reg().public(kind))


@panel_view(['GET'])
def estimate(request):
    prof = request.query_params.get('profile', 'preview')
    pid = str(request.query_params.get('project') or '')
    p = Project.objects.filter(pk=int(pid)).first() if pid.isdigit() else None
    # تنظیمِ دستیِ کیفیت (?resolution=&samples=&frame_step=) همان ضریبی را می‌گیرد که در request_job
    try:
        q = SV.clean_quality({k: request.query_params.get(k) for k in ('resolution', 'samples', 'frame_step')})
    except ValueError as e:
        return Response({'error': str(e)}, status=400)
    frames = SV.frames_of(p.current.document, prof, q) if p and p.current else 240
    out = {'frames': frames, **SV.estimate(prof, frames, quality=q)}
    if not out['available']:
        cpu = SV.estimate(prof, frames, allow_cpu=True, quality=q)
        out['cpu_seconds'] = cpu['seconds'] if cpu['available'] else None
        out['cpu_worker'] = cpu['worker']
    return Response(out)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def asset_file(request, kind, asset_id, name):
    a = SV.reg().get(kind, asset_id)
    if not a or name not in ('thumbnail.jpg', 'preview.mp4'):
        raise Http404
    path = a.path(name)
    if not os.path.isfile(path):
        raise Http404
    return FileResponse(open(path, 'rb'))


# ───────────────────────── پروتکلِ کارگر

class WorkerAuth(authentication.BaseAuthentication):
    def authenticate(self, request):
        h = request.META.get('HTTP_AUTHORIZATION', '')
        if not h.startswith('Worker '):
            return None
        token = h.split(' ', 1)[1].strip()
        w = Worker.objects.filter(token=token, enabled=True).first()
        if not w:
            # همان توکنِ «سرورِ پردازش» (apps.compute) برای رندرِ سه‌بعدی هم کار می‌کند
            from apps.compute.models import ComputeNode
            node = ComputeNode.objects.filter(token=token, enabled=True).first()
            if node:
                w, _ = Worker.objects.get_or_create(name=node.name)
                if w.token != token or not w.enabled:
                    w.token, w.enabled = token, True
                    w.save(update_fields=['token', 'enabled'])
        if not w:
            raise exceptions.AuthenticationFailed('توکنِ کارگر نامعتبر است')
        w.last_seen = timezone.now()
        w.save(update_fields=['last_seen'])
        return (AnonymousUser(), w)


def _worker(request):
    if not isinstance(request.auth, Worker):
        raise exceptions.NotAuthenticated('فقط کارگر')
    return request.auth


worker_api = lambda fn: api_view(['GET', 'POST'])(authentication_classes([WorkerAuth])(  # noqa: E731
    permission_classes([permissions.AllowAny])(fn)))


@worker_api
def w_heartbeat(request):
    w = _worker(request)
    if isinstance(request.data, dict) and request.data:
        w.capabilities = request.data
        w.save(update_fields=['capabilities'])
    return Response({'ok': True, 'name': w.name})


@worker_api
def w_claim(request):
    w = _worker(request)
    if isinstance(request.data, dict) and request.data.get('gpu') is not None:
        w.capabilities = request.data
        w.save(update_fields=['capabilities'])
    return Response({'job': SV.claim(w)})


def _wjob(request, pk):
    w = _worker(request)
    j = get_object_or_404(Job, pk=pk)
    if j.worker_id != w.pk:
        raise exceptions.PermissionDenied('این کار مالِ کارگرِ دیگری است')
    return w, j


@worker_api
def w_package(request, pk):
    w, j = _wjob(request, pk)
    return FileResponse(open(SV.package(j), 'rb'), as_attachment=True, filename='package.zip')


@worker_api
def w_progress(request, pk):
    w, j = _wjob(request, pk)
    return Response(SV.worker_progress(j, request.data))


@worker_api
def w_upload(request, pk):
    w, j = _wjob(request, pk)
    SV.worker_upload(j, request.FILES)
    return Response({'ok': True, 'files': list(j.files)})


@worker_api
def w_finish(request, pk):
    w, j = _wjob(request, pk)
    SV.worker_finish(j, w, bool(request.data.get('ok')), str(request.data.get('error') or ''), request.data.get('seconds'))
    return Response({'ok': True})


@worker_api
def w_bundle(request):
    """بستهٔ کامل برای راه‌اندازیِ کارگرِ تازه (با توکنِ کارگر)."""
    _worker(request)
    from django.conf import settings
    path = os.path.join(settings.UP3D_DATA_DIR, 'bundle', 'up3d-worker-bundle.zip')
    if not os.path.isfile(path):
        raise Http404('بسته ساخته نشده؛ روی سرور: ./up3d.sh bundle')
    return FileResponse(open(path, 'rb'), as_attachment=True, filename='up3d-worker-bundle.zip')
