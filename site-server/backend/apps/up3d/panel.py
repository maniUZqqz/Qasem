"""نماهای JSON ِ پنلِ ری‌اکت — جایگزینِ صفحه‌های HTML ِ قدیمی (views.py).

همه زیرِ /api/v1/up3d/ (api_urls.py)، فقط برای کارکنان (is_staff)، با همان احراز هویتِ پیش‌فرضِ DRF.
فایل‌هایی که مرورگر مستقیم بار می‌کند (ویدئو، پوستر، GLB، تصویرِ دارایی) هم‌چنان زیرِ /3d/ می‌مانند.
"""
import os
import uuid

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import exceptions
from rest_framework.authtoken.models import Token
from rest_framework.response import Response

from up3d import templates as T

from . import services as SV
from .api import job_json, panel_view, project_json
from .models import AiSettings, Job, Project, Upload, Worker

FINAL_STATES = ('COMPLETED', 'FAILED', 'CANCELLED')


# ───────────────────────── کمک‌ها

def worker_json(w):
    return {'id': w.pk, 'name': w.name, 'enabled': w.enabled, 'online': w.online, 'has_gpu': w.has_gpu,
            'profiles': w.profiles or [], 'capabilities': w.capabilities or {}, 'stats': w.stats or {},
            'last_seen': w.last_seen, 'jobs_done': w.jobs_done, 'created': w.created, 'token': w.token}


def ai_json():
    ai = AiSettings.get()
    return {'ready': bool(ai.enabled and ai.api_key), 'enabled': ai.enabled, 'model': ai.model,
            'tts_model': ai.tts_model, 'tts_enabled': ai.tts_enabled, 'base_url': ai.base_url or 'api.openai.com'}


def _origin(request):
    """ریشهٔ سایت (بی‌مسیر) برای نمونه‌های API و SDK."""
    return request.build_absolute_uri('/').rstrip('/')


def _worker_server(request):
    """نشانیِ پایهٔ پروتکلِ کارگر: {SERVER}/api/worker/... زیرِ /3d/ می‌ماند."""
    return request.build_absolute_uri('/3d/').rstrip('/')


def _counts():
    active = Job.objects.exclude(state__in=FINAL_STATES).exclude(project__title='__thumbnails__').count()
    online = sum(1 for w in Worker.objects.filter(enabled=True) if w.online)
    return active, online


# ───────────────────────── داشبورد و وضعیت

@panel_view(['GET'])
def dashboard(request):
    projects = Project.objects.exclude(title='__thumbnails__').select_related('current')[:24]
    jobs = Job.objects.exclude(project__title='__thumbnails__').select_related('project', 'worker', 'version')[:12]
    active, online = _counts()
    return Response({
        'projects': [project_json(p, False) for p in projects],
        'jobs': [job_json(j, True) for j in jobs],
        'workers': [worker_json(w) for w in Worker.objects.all()],
        'ai': ai_json(),
        'counts': SV.reg().counts(),
        'files_url': settings.UP3D_FILES_URL,
        'active_jobs': active,
        'workers_online': online,
        'server': _origin(request),
    })


@panel_view(['GET'])
def status(request):
    """شمارنده‌های نوارِ ناوبری (جایگزینِ nav_context) + آمادگیِ AI."""
    active, online = _counts()
    return Response({'active_jobs': active, 'workers_online': online, 'ai_ready': ai_json()['ready'],
                     'server': _origin(request), 'worker_server': _worker_server(request),
                     'files_url': settings.UP3D_FILES_URL})


@panel_view(['GET'])
def templates_list(request):
    return Response([{'id': k, **v} for k, v in T.TEMPLATES.items()])


@panel_view(['GET'])
def catalog(request):
    """دفترِ دارایی‌ها، همهٔ دسته‌ها (برای ویرایشگر، پروژهٔ تازه و کتابخانه)."""
    return Response(SV.reg().public())


# ───────────────────────── دارایی‌ها

@panel_view(['POST'])
def asset_thumbnails(request):
    """ساختِ تصویر/پیش‌نمایشِ دارایی‌ها با خودِ موتور: {kind, ids?} ⇐ کارِ thumbnail در صف."""
    kind = (request.data.get('kind') or '').strip()
    if kind not in ('character', 'motion', 'environment', 'product'):
        raise exceptions.ValidationError('دستهٔ «%s» تصویرپذیر نیست' % kind)
    ids = request.data.get('ids') or [a.id for a in SV.reg().list(kind)]
    if isinstance(ids, str):
        ids = [ids]
    jobs = []
    for aid in ids:
        if SV.reg().get(kind, aid):
            jobs.append(SV.request_thumbnail(kind, aid).pk)
    return Response({'queued': len(jobs), 'jobs': jobs, 'kind': kind,
                     'message': '%d کارِ ساختِ تصویر در صف گذاشته شد.' % len(jobs)})


# ───────────────────────── کارگرها

@panel_view(['GET', 'POST'])
def workers(request):
    if request.method == 'GET':
        return Response({'workers': [worker_json(w) for w in Worker.objects.all()],
                         'server': _worker_server(request)})
    name = (request.data.get('name') or '').strip() or 'worker-%s' % uuid.uuid4().hex[:5]
    prof = request.data.get('profiles') or []
    if isinstance(prof, str):
        prof = [prof]
    prof = [str(x) for x in prof if x]
    w, created = Worker.objects.get_or_create(name=name)
    w.profiles = prof
    w.save()
    return Response({'worker': worker_json(w), 'created': created,
                     'message': 'کارگرِ «%s» %s.' % (name, 'ساخته شد' if created else 'به‌روز شد')},
                    status=201 if created else 200)


@panel_view(['POST'])
def worker_toggle(request, pk):
    w = get_object_or_404(Worker, pk=pk)
    w.enabled = not w.enabled
    w.save(update_fields=['enabled'])
    return Response(worker_json(w))


@panel_view(['GET'])
def worker_bat(request, pk):
    """فایلِ راه‌اندازیِ کارگر روی ویندوز (PC با کارتِ گرافیک) — دانلود با توکنِ پنل."""
    w = get_object_or_404(Worker, pk=pk)
    tpl_path = os.path.join(str(settings.UP3D_ROOT), 'worker-windows', 'start-worker.bat.tpl')
    if not os.path.isfile(tpl_path):
        raise Http404('قالبِ start-worker.bat.tpl در UP3D_ROOT/worker-windows نیست')
    with open(tpl_path, encoding='utf-8') as fh:
        tpl = fh.read()
    body = tpl.replace('{{SERVER}}', _worker_server(request)).replace('{{TOKEN}}', w.token).replace('{{NAME}}', w.name)
    resp = HttpResponse(body.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'),
                        content_type='application/octet-stream')
    resp['Content-Disposition'] = 'attachment; filename="start-worker-%s.bat"' % w.name
    return resp


@panel_view(['GET'])
def worker_bundle(request):
    """بستهٔ کامل برای کارگرِ دیگر: هسته، موتور، دارایی‌ها، افزونهٔ MPFB و داده‌هایش."""
    path = os.path.join(str(settings.UP3D_DATA_DIR), 'bundle', 'up3d-worker-bundle.zip')
    if not os.path.isfile(path):
        raise Http404('بسته هنوز ساخته نشده؛ روی سرور: ./up3d.sh bundle')
    return FileResponse(open(path, 'rb'), as_attachment=True, filename='up3d-worker-bundle.zip')


# ───────────────────────── بارگذاری و توکن

@panel_view(['POST'])
def upload(request):
    """بارگذاریِ عکسِ برچسب، مدلِ سه‌بعدیِ محصول یا موسیقی (multipart، فیلدِ file)."""
    f = request.FILES.get('file')
    if not f:
        raise exceptions.ValidationError('فایلی نیامد')
    ext = os.path.splitext(f.name)[1].lower()
    kind = 'image' if ext in ('.png', '.jpg', '.jpeg', '.webp') else 'model' if ext in ('.glb', '.gltf', '.obj', '.fbx') \
        else 'music' if ext in ('.mp3', '.wav', '.ogg', '.m4a') else None
    if not kind:
        raise exceptions.ValidationError('نوعِ فایل پشتیبانی نمی‌شود')
    uid = uuid.uuid4().hex
    rel = os.path.join('uploads', uid + ext)
    dest = os.path.join(str(settings.UP3D_DATA_DIR), rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'wb') as fh:
        for ch in f.chunks():
            fh.write(ch)
    if kind == 'image':
        from PIL import Image
        try:
            im = Image.open(dest)
            im.verify()
        except Exception:
            os.remove(dest)
            raise exceptions.ValidationError('تصویر خراب است')
    u = Upload.objects.create(kind=kind, name=f.name[:200], path=rel, size=f.size, owner=request.user)
    return Response({'id': str(u.uid), 'path': dest, 'url': SV.file_url(rel), 'kind': kind, 'name': u.name, 'size': u.size},
                    status=201)


@panel_view(['GET'])
def api_token(request):
    """توکنِ API ِ همین کاربر (rest_framework.authtoken) — برای SDK و curl."""
    tok, _ = Token.objects.get_or_create(user=request.user)
    return Response({'token': tok.key, 'server': _origin(request), 'worker_server': _worker_server(request),
                     'username': request.user.get_username()})
