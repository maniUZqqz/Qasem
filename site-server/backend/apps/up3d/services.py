"""منطقِ پنل: پروژه، نسخهٔ صحنه، کار، کارگر. وب‌ها و API فقط این‌ها را صدا می‌زنند."""
import json
import os
import shutil
import traceback
import zipfile

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from up3d import compiler, director, pipeline, templates
from up3d import scene as S
from up3d.assets import registry
from up3d.validate import repair, validate

from .models import FINAL, AiSettings, Job, Project, SceneVersion, Worker

DATA = str(settings.UP3D_DATA_DIR)


def reg():
    return registry()


def data_abs(rel):
    return os.path.join(DATA, rel)


def file_url(rel):
    return settings.UP3D_FILES_URL + rel.replace('\\', '/') if rel else ''


def job_dir(job):
    d = data_abs(job.dir_rel())
    os.makedirs(d, exist_ok=True)
    return d


# ───────────────────────── نسخه‌ها

def new_version(project, doc, source='editor', note='', auto_repair=False):
    r = reg()
    changes = []
    if auto_repair:
        doc, changes, rep = repair(doc, r)
    else:
        doc = S.normalize(doc)
        rep = validate(doc, r)
    last = project.versions.order_by('-number').first()
    v = SceneVersion.objects.create(project=project, number=(last.number + 1 if last else 1), document=doc,
                                    source=source, note=note[:300], valid=rep.ok,
                                    report={**rep.to_dict(), 'changes': changes})
    project.current = v
    title = (doc.get('meta') or {}).get('title')
    if title and project.title.startswith('پروژهٔ بی‌نام'):
        project.title = title[:200]
    project.save()
    return v


# ───────────────────────── پروژه و برنامه‌ریزی

def create_project(user, brief, mode='ai', template='showcase', title=None):
    brief = dict(brief or {})
    p = Project.objects.create(title=title or brief.get('product_name') or 'پروژهٔ بی‌نام', brief=brief, owner=user)
    job = Job.objects.create(project=p, kind='plan', params={'mode': mode, 'template': template, 'brief': brief})
    job.add_log('پروژه ساخته شد؛ برنامه‌ریزی با %s' % ('هوشِ مصنوعی' if mode == 'ai' else 'قالبِ ' + template))
    return p, job


def process_plan(job):
    job.started = timezone.now()
    job.set_state('PLANNING', 'کارگردان در حالِ نوشتنِ برنامه است')
    p = job.project
    brief = job.params.get('brief') or p.brief
    ai = AiSettings.get()
    if job.params.get('mode') == 'ai' and ai.enabled and ai.api_key:
        doc, info = director.plan(brief, ai.llm(), reg(), log=job.add_log)
        src = info['source']
        if src != 'ai':
            job.add_log('AI نتوانست؛ قالب جایگزین شد: %s' % info.get('fallback_reason'))
        else:
            job.add_log('برنامهٔ AI در %s ثانیه (%d ترمیم)' % (info.get('seconds'), len(info.get('repairs', []))))
        job.report = {'director': info}
    else:
        if job.params.get('mode') == 'ai':
            job.add_log('کلیدِ AI تنظیم نشده یا خاموش است ⇐ قالبِ قاعده‌محور')
        doc = templates.build(job.params.get('template') or 'showcase', brief, reg())
        src = 'template'
    v = new_version(p, doc, src, 'برنامهٔ اولیه')
    job.version = v
    job.progress = 1.0
    job.set_state('COMPLETED' if v.valid else 'FAILED', 'نسخهٔ %d ساخته شد%s' % (v.number, '' if v.valid else ' ولی معتبر نیست'))
    return v


def ai_edit(project, instruction, user=None):
    ai = AiSettings.get()
    if not (ai.enabled and ai.api_key):
        raise director.DirectorError('کلیدِ هوشِ مصنوعی در تنظیمات (جنگو ادمین) وارد نشده')
    new, info = director.edit(project.current.document, instruction, ai.llm(), reg())
    v = new_version(project, new, 'ai-edit', instruction)
    return v, info


# ───────────────────────── کارها

clean_quality = compiler.clean_quality      # تنظیمِ دستیِ کیفیت: {resolution, samples, frame_step, denoise, motion_blur}


def frames_of(doc, profile_id, quality=None):
    p = compiler.with_overrides(reg().get('render_profile', profile_id), quality)
    fps = doc['output']['fps']
    n = int(round(doc['output']['duration'] * fps))
    return max(1, n // max(1, int((p or {}).get('frame_step', 1))))


def estimate(profile_id, frames, allow_cpu=False, quality=None):
    """تخمینِ زمان: از آمارِ واقعیِ کارگرها، وگرنه از پروفایل. تنظیمِ دستی با ضریبِ پیکسل×نمونه."""
    p = reg().get('render_profile', profile_id)
    scale = compiler.quality_scale(p, quality)
    best = None
    for w in Worker.objects.filter(enabled=True):
        if not w.online or not (w.accepts(p) or allow_cpu):
            continue
        st = (w.stats or {}).get(profile_id)
        spf = (st['sec_per_frame'] if st else ((p or {}).get('est_sec_per_frame_cpu', 10) / (8.0 if w.has_gpu else 1.0))) * scale
        if best is None or spf < best[0]:
            best = (spf, w)
    if best is None:
        spf = (p or {}).get('est_sec_per_frame_cpu', 10) * scale
        return {'seconds': spf * frames + 60, 'worker': None, 'sec_per_frame': round(spf, 2), 'available': False,
                'needs_gpu': (p or {}).get('recommended') == 'gpu'}
    return {'seconds': best[0] * frames + 60, 'worker': best[1].name, 'sec_per_frame': round(best[0], 2), 'available': True,
            'needs_gpu': (p or {}).get('recommended') == 'gpu'}


# ───────────────────────── مسیرِ کار: اول GPU

def gpu_class(job, prof=None):
    """کاری که جایش روی GPU است (رندرِ کیفیتِ «استاندارد» به بالا)."""
    prof = prof if prof is not None else reg().get('render_profile', job.profile)
    return job.kind == 'render' and (prof or {}).get('recommended') == 'gpu'


MIN_WORKER = (1, 1, 0)


def worker_version(worker):
    v = str((worker.capabilities or {}).get('version') or '0')
    try:
        return tuple(int(x) for x in v.split('.')[:3])
    except ValueError:
        return (0,)


def needs_mpfb(job):
    doc = (job.params or {}).get('document') or (job.version.document if job.version_id else None) or {}
    r = reg()
    for a in doc.get('actors') or []:
        ch = r.get('character', a.get('character'))
        if ch is not None and ch.get('provider', 'mpfb') == 'mpfb':
            return True
    return False


def capable(worker, job=None):
    """این کارگر می‌تواند کار بگیرد؟ کارگرِ قدیمی (پوشهٔ processing ِ به‌روزنشده) کار نمی‌گیرد — بستهٔ کار و
    پروتکلش عوض شده؛ کارگرِ بی‌دادهٔ MPFB کارِ با مجریِ ساخته‌شده (MPFB) نمی‌گیرد."""
    if worker_version(worker) < MIN_WORKER:
        return False
    if job is not None and (worker.capabilities or {}).get('mpfb') is False and needs_mpfb(job):
        return False
    return True


def busy(worker):
    return Job.objects.filter(worker=worker, owner='worker').exclude(state__in=FINAL).exists()


def gpu_workers(prof=None, idle_only=False):
    """کارگرهای GPU ِ آنلاین که این پروفایل را می‌پذیرند."""
    out = []
    for w in Worker.objects.filter(enabled=True):
        if not (w.online and w.has_gpu and capable(w)):
            continue
        if prof is not None and not w.accepts(prof):
            continue
        if idle_only and busy(w):
            continue
        out.append(w)
    return out


def leave_for_gpu(job, prof, worker):
    """کارگرِ بی‌GPU این کار را برندارد؟ — اگر کارگرِ GPU ِ بیکار آنلاین است، همیشه؛ اگر GPU سرش گرم است،
    فقط کارهای GPU-کلاس منتظرِ او می‌مانند و کارهای سبک (انیمیک، پیش‌نمایش، تصویر) همین‌جا انجام می‌شوند."""
    if worker.has_gpu:
        return False
    gpus = gpu_workers(prof if job.kind == 'render' else None)
    if not gpus:
        return False
    if any(not busy(g) for g in gpus):
        return True
    return gpu_class(job, prof)


def release_reason(job, worker):
    """کارگرِ CPU که کارِ GPU-کلاس (با اجازهٔ CPU) را می‌سازد آن را رها کند؟
    handoff: کارگرِ GPU ِ بیکار آنلاین شد ⇐ کار به او می‌رود.
    yield:   کارِ سبکی در صف است که همین کارگر می‌تواند بگیرد ⇐ موقتاً کنار می‌رود (فریم‌ها می‌مانند و بعد ادامه می‌دهد)."""
    if worker.has_gpu or job.kind != 'render':
        return None
    r = reg()
    prof = r.get('render_profile', job.profile)
    if not gpu_class(job, prof):
        return None
    if gpu_workers(prof, idle_only=True):
        return 'handoff'
    for j in Job.objects.filter(owner='worker', worker__isnull=True, state='SCENE_BUILDING', cancel_requested=False):
        p2 = r.get('render_profile', j.profile)
        if not gpu_class(j, p2) and (j.kind != 'render' or (p2 is not None and worker.accepts(p2))):
            return 'yield'
    return None


def gpu_nodes():
    """سرورهای پردازشِ دارای GPU و آمادگیِ رندرِ سه‌بعدی‌شان (برای پنل: چرا GPU کار نمی‌گیرد و چطور روشنش کنیم)."""
    try:
        from apps.compute.models import ComputeNode
    except Exception:       # noqa: BLE001 — اپِ سرورهای پردازش نصب نیست
        return []
    out = []
    workers = {w.name: w for w in Worker.objects.all()}
    for n in ComputeNode.objects.filter(enabled=True):
        caps = n.capabilities or {}
        if not caps.get('gpu'):
            continue
        w = workers.get(n.name)
        managed = (caps.get('managed') or {}).get('worker3d')
        out.append({
            'id': n.pk, 'name': n.name, 'online': n.online, 'gpu': caps.get('gpu'), 'agent': caps.get('agent'),
            'blender': bool(caps.get('blender')), 'worker3d_running': bool(caps.get('worker3d')), 'managed': managed,
            'startable': bool((caps.get('startable') or {}).get('worker3d')), 'desired': (n.desired or {}).get('worker3d'),
            'auto_switch': n.auto_switch, 'worker_online': bool(w and w.online), 'worker_gpu': bool(w and w.has_gpu),
            'worker_blender': (w.capabilities or {}).get('blender_version') if w else None,
            'worker_version': (w.capabilities or {}).get('version') if w else None,
            'worker_capable': bool(w and capable(w)), 'worker_mpfb': (w.capabilities or {}).get('mpfb') if w else None,
        })
    return out


def wants_gpu_worker(node):
    """هماهنگ‌کنندهٔ گره: کارِ سه‌بعدیِ منتظر هست و این گره GPU و «رندرِ سه‌بعدی»ِ قابلِ روشن‌کردن دارد ⇐
    کارگرِ سه‌بعدیِ گره روشن شود (worker-3d.bat؛ اگر Blender نیست خودش یک بار دانلود می‌کند)."""
    caps = node.capabilities or {}
    if not caps.get('gpu') or not (caps.get('startable') or {}).get('worker3d'):
        return False
    waiting = Job.objects.filter(owner='worker', worker__isnull=True, state='SCENE_BUILDING', cancel_requested=False).exists()
    if waiting:
        return True
    # کارِ GPU-کلاسی که الان روی CPU ِ سرور ساخته می‌شود ⇐ با آمدنِ GPU واگذار می‌شود
    for j in Job.objects.filter(owner='worker', worker__isnull=False, kind='render').exclude(state__in=FINAL).select_related('worker'):
        if j.worker and not j.worker.has_gpu and gpu_class(j):
            return True
    return False


def eligible_workers(job):
    """کارگرهای آنلاینی که همین حالا می‌توانند این کار را بگیرند — همان شرطِ claim() (با اولویتِ GPU)."""
    prof = reg().get('render_profile', job.profile)
    allow = bool((job.params or {}).get('allow_cpu'))
    return [w.name for w in Worker.objects.filter(enabled=True)
            if w.online and capable(w, job) and (job.kind != 'render' or allow or (prof is not None and w.accepts(prof)))
            and not leave_for_gpu(job, prof, w)]


def waiting_info(job):
    """چرا این کار هنوز کارگر ندارد (برای پنل): به GPU نیاز دارد؟ اجازهٔ CPU؟ کدام کارگرها آنلاین/مناسب‌اند."""
    prof = reg().get('render_profile', job.profile) or {}
    online = [w.name for w in Worker.objects.filter(enabled=True) if w.online]
    return {'needs_gpu': job.kind == 'render' and prof.get('recommended') == 'gpu',
            'allow_cpu': bool((job.params or {}).get('allow_cpu')), 'online': online, 'eligible': eligible_workers(job),
            'gpu_online': [w.name for w in gpu_workers()], 'gpu_nodes': gpu_nodes()}


def game_pack_doc(character_id):
    """صحنهٔ «بستهٔ بازی»: همهٔ حرکت‌های بدن پشتِ سرِ هم (هر کدام بعداً یک کلیپِ جدا)."""
    r = reg()
    doc = S.new_scene('game pack', 10, '1:1')
    doc['environment'] = {'id': 'studio_warm', 'params': {'decor': False}}
    doc['lighting'] = {'id': 'soft_beauty', 'params': {}}
    doc['actors'] = [{'id': 'host', 'character': character_id, 'mark': 'center'}]
    doc['products'] = [{'id': 'p1', 'asset': 'perfume_bottle', 'name': 'UpMarket', 'surface': 'table_right'}]
    order = ['idle', 'talk', 'wave_hello', 'nod', 'thumbs_up', 'hand_on_chest', 'open_arms', 'point_at',
             'pick_up', 'present', 'rotate_show', 'spray', 'put_down']
    t = 0.2
    for mid in order:
        m = r.get('motion', mid)
        if not m:
            continue
        d = m['duration']['default']
        doc['actions'].append({'actor': 'host', 'motion': mid, 'start': round(t, 3), 'duration': d, 'params': {'product': 'p1'}
                               if (m.get('product') or {}).get('param') else {}})
        if not m.get('layer'):
            t += d + 0.4
    doc['output']['duration'] = round(t + 0.5, 2)
    doc['shots'] = [{'shot': 'wide', 'start': 0, 'duration': doc['output']['duration'], 'subject': 'host', 'move': 'static'}]
    doc, _, rep = repair(doc, r)
    return doc


def request_job(project, kind='render', profile='preview', params=None, version=None, user=None):
    v = version or project.current
    params = dict(params or {})
    if kind == 'export' and params.get('format') == 'game_pack':
        ch = (v.document.get('actors') or [{}])[0].get('character') if v else None
        params['document'] = game_pack_doc(ch or reg().default('character').id)
    if not v:
        raise ValueError('این پروژه هنوز صحنه ندارد')
    if not v.valid:
        raise ValueError('صحنه ایرادِ ترمیم‌نشده دارد؛ اول «ترمیمِ خودکار» یا ویرایش')
    if kind in ('export', 'contact') and not profile:
        profile = 'animatic' if kind == 'export' else 'preview'
    if not reg().get('render_profile', profile):
        raise ValueError('پروفایلِ «%s» نیست' % profile)
    q = clean_quality(params.get('quality')) if params.get('quality') else {}
    if q:
        params['quality'] = q
    else:
        params.pop('quality', None)
    fr = frames_of(v.document, profile, q) if kind == 'render' else (params.get('count', 6) if kind == 'contact' else 0)
    est = estimate(profile, fr, bool(params.get('allow_cpu')), q)
    job = Job.objects.create(project=project, version=v, kind=kind, profile=profile, params=params or {},
                             state='PLANNED', frames_total=fr, estimate_seconds=est['seconds'])
    job.add_log('درخواست: %s با پروفایلِ %s%s (تخمین ~%d دقیقه، %s)' % (
        job.get_kind_display(), profile, (' + تنظیمِ دستی ' + '، '.join('%s=%s' % kv for kv in q.items())) if q else '',
        max(1, est['seconds'] // 60),
        'کارگر: ' + est['worker'] if est['available'] else
        ('فعلاً کارگرِ مناسب آنلاین نیست' + (' — این کیفیت کارگرِ GPU می‌خواهد' if est.get('needs_gpu') else ''))))
    return job


def cancel(job):
    if job.final:
        return
    job.cancel_requested = True
    job.save(update_fields=['cancel_requested'])
    if job.owner == 'panel' or job.worker is None:
        job.set_state('CANCELLED', 'لغو شد')


def process_prepare(job):
    """نیمهٔ پنل: صدا، لب، برچسب، compile ⇐ آماده برای کارگر."""
    job.started = timezone.now()
    job.set_state('SCENE_BUILDING', 'آماده‌سازی: برچسب، صدا، هماهنگیِ لب')
    ai = AiSettings.get()
    doc = job.params.get('document') or job.version.document
    info = pipeline.prepare(doc, job_dir(job), job.profile, ai.tts(), log=job.add_log, reg=reg(),
                            profile_overrides=job.params.get('quality') or None)
    if job.kind == 'render':
        job.frames_total = len(range(1, info['frames'] + 1, info['frame_step']))
    job.owner = 'worker'
    what = '%d فریم، ' % job.frames_total if job.frames_total else ''
    # پیامِ انتظار باید بگوید «چرا»: کارگرِ آماده هست، یا این کیفیت GPU می‌خواهد و GPU آنلاین نیست
    eligible = eligible_workers(job)
    if eligible:
        msg = 'منتظرِ کارگرِ رندر (%s%dx%d) — کارگرِ آماده: %s' % (what, *info['resolution'], '، '.join(eligible))
    else:
        prof = reg().get('render_profile', job.profile) or {}
        why = ('کیفیتِ «%s» کارگرِ GPU می‌خواهد و کارگرِ GPU آنلاین نیست؛ یا کارگرِ GPU راه بیندازید، یا «اجرا روی CPU» (کند) یا لغو'
               % job.profile) if job.kind == 'render' and prof.get('recommended') == 'gpu' else 'هیچ کارگری آنلاین نیست'
        msg = 'منتظرِ کارگر (%s%dx%d) — %s' % (what, *info['resolution'], why)
    job.set_state('SCENE_BUILDING', msg)


def engine_mode(job):
    if job.kind == 'render':
        return 'render', []
    if job.kind == 'export':
        return 'export', ['--format', job.params.get('format', 'glb')]
    if job.kind == 'contact':
        return 'contact', ['--count', str(job.params.get('count', 6))]
    if job.kind == 'thumbnail':
        return job.params.get('mode', 'still'), (['--frame', str(job.params.get('frame', 1))]
                                                  if job.params.get('mode', 'still') == 'still' else [])
    return 'render', []


def claim(worker):
    """یک کار به این کارگر. GPU اول: کارگرِ بی‌GPU کاری را که کارگرِ GPU ِ آنلاین می‌تواند بگیرد برنمی‌دارد،
    و از میانِ کارهای مجاز، اول کارهای سبک (کارِ GPU-کلاس با «اجازهٔ CPU» آخر از همه)."""
    r = reg()
    with transaction.atomic():
        # کارگری که کار می‌خواهد بیکار است ⇐ کارِ نیمه‌تمامی که هنوز به نامِ اوست (فرایندش ری‌استارت شده) دوباره به خودش
        # می‌رسد و از فریم‌های ساخته‌شده ادامه می‌دهد — مگر کارگرِ GPU ِ بیکار منتظرش باشد
        for job in Job.objects.select_for_update().filter(worker=worker, owner='worker', cancel_requested=False).exclude(
                state__in=FINAL).order_by('created'):
            if release_reason(job, worker) == 'handoff' or not capable(worker, job):
                job.worker = None
                job.state = 'SCENE_BUILDING'
                job.add_log('کارگرِ %s دوباره راه افتاد؛ کار به صف برگشت' % worker.name, save=False)
                job.save()
                continue
            job.claimed = timezone.now()
            job.add_log('کارگرِ %s دوباره راه افتاد؛ ادامهٔ همان کار' % worker.name, save=False)
            job.save()
            mode, extra = engine_mode(job)
            return {'id': job.pk, 'uid': str(job.uid), 'kind': job.kind, 'profile': job.profile, 'params': job.params,
                    'mode': mode, 'extra': extra}
        jobs = list(Job.objects.select_for_update().filter(owner='worker', worker__isnull=True, state='SCENE_BUILDING',
                                                           cancel_requested=False).order_by('created'))
        if not worker.has_gpu:
            jobs.sort(key=lambda j: (gpu_class(j, r.get('render_profile', j.profile)), j.created))
        for job in jobs:
            prof = r.get('render_profile', job.profile)
            if job.kind == 'render' and not (worker.accepts(prof) or job.params.get('allow_cpu')):
                continue
            if not capable(worker, job) or leave_for_gpu(job, prof, worker):
                continue
            job.worker = worker
            job.claimed = timezone.now()
            job.add_log('کارگرِ %s کار را گرفت' % worker.name, save=False)
            job.save()
            mode, extra = engine_mode(job)
            return {'id': job.pk, 'uid': str(job.uid), 'kind': job.kind, 'profile': job.profile, 'params': job.params,
                    'mode': mode, 'extra': extra}
    return None


def package(job):
    """بستهٔ کار برای کارگر: compiled.json + inputs/ (برچسب، مدل، و پوشه‌های دارایی‌های بسته — بازگشتی)."""
    d = job_dir(job)
    z = os.path.join(d, 'package.zip')
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(os.path.join(d, 'compiled.json'), 'compiled.json')
        inputs = os.path.join(d, 'inputs')
        if os.path.isdir(inputs):
            for dp, _, fns in os.walk(inputs):
                for f in fns:
                    full = os.path.join(dp, f)
                    zf.write(full, os.path.relpath(full, d).replace(os.sep, '/'))
    return z


def worker_progress(job, data, worker=None):
    worker = worker or job.worker
    why = release_reason(job, worker) if worker is not None else None
    if why:
        job.worker = None
        job.state = 'SCENE_BUILDING'
        job.message = ('به کارگرِ GPU واگذار شد (فریم‌های CPU روی سرور نگه داشته شد)' if why == 'handoff' else
                       'موقتاً کنار رفت تا کارِ کوتاهِ در صف انجام شود؛ بعد از همان فریم ادامه می‌دهد')
        job.add_log('کارگرِ %s: %s' % (worker.name, job.message), save=False)
        job.save()
        return {'cancel': True, 'release': why}
    st = data.get('state')
    if st in ('SCENE_BUILDING', 'RENDERING') and job.state != st:
        job.state = st
    if data.get('total'):
        job.frames_total = int(data['total'])
        job.frames_done = int(data.get('frame') or 0)
        job.progress = min(0.99, job.frames_done / max(1, job.frames_total))
    if data.get('sec_per_frame'):
        job.sec_per_frame = float(data['sec_per_frame'])
    if data.get('message'):
        job.message = data['message'][:400]
        job.add_log(data['message'], save=False)
    job.save()
    return {'cancel': job.cancel_requested}


def worker_upload(job, files):
    d = job_dir(job)
    out = dict(job.files or {})
    for field, f in files.items():
        name = os.path.basename(f.name)
        dest = os.path.join(d, name)
        with open(dest, 'wb') as fh:
            for chunk in f.chunks():
                fh.write(chunk)
        out[name] = os.path.join(job.dir_rel(), name)
    job.files = out
    job.save(update_fields=['files'])


def worker_finish(job, worker, ok, error='', seconds=None):
    if not ok:
        job.error = error
        job.owner = 'panel'
        job.set_state('CANCELLED' if job.cancel_requested else 'FAILED', 'کارگر: ' + (error[:300] or 'خطا'))
        return
    rp = os.path.join(job_dir(job), 'engine_report.json')
    if os.path.isfile(rp):
        with open(rp, encoding='utf-8') as fh:
            job.report = {**(job.report or {}), 'engine': json.load(fh)}
    eng = (job.report or {}).get('engine', {})
    if eng.get('sec_per_frame') and job.kind == 'render':
        st = dict(worker.stats or {})
        old = st.get(job.profile, {'sec_per_frame': eng['sec_per_frame'], 'n': 0})
        n = old['n'] + 1
        st[job.profile] = {'sec_per_frame': round((old['sec_per_frame'] * old['n'] + eng['sec_per_frame']) / n, 2), 'n': n}
        worker.stats = st
    worker.jobs_done += 1
    worker.save()
    job.owner = 'panel'
    job.frames_done = job.frames_total
    job.set_state('QUALITY_CHECK', 'خروجیِ کارگر رسید (%s ثانیه)' % seconds)


def process_finish(job):
    d = job_dir(job)
    if job.kind == 'render':
        job.set_state('ASSEMBLING', 'مونتاژ: صدا، نوشته‌های فارسی، موسیقی')
        out = pipeline.finish(d, log=job.add_log, reg=reg())
        files = dict(job.files or {})
        files['final.mp4'] = os.path.join(job.dir_rel(), 'final.mp4')
        if out.get('poster'):
            files['poster.jpg'] = os.path.join(job.dir_rel(), os.path.basename(out['poster']))
            job.project.poster = files['poster.jpg']
            job.project.save(update_fields=['poster', 'updated'])
        job.files = files
        job.qc = out['qc']
        job.progress = 1.0
        msg = {'pass': 'تمام شد؛ کنترلِ کیفیت قبول', 'warn': 'تمام شد؛ با هشدارِ کیفیت', 'fail': 'تمام شد ولی کنترلِ کیفیت رد کرد'}
        job.set_state('COMPLETED', msg[out['qc']['result']])
    elif job.kind == 'thumbnail':
        a = reg().get(job.params['asset_kind'], job.params['asset_id'])
        src = None
        for name, rel in (job.files or {}).items():
            if name.endswith('.png') and src is None:
                src = data_abs(rel)
            if name == 'render.mp4':
                shutil.copyfile(data_abs(rel), os.path.join(a.folder, 'preview.mp4'))
        if src:
            from PIL import Image
            im = Image.open(src).convert('RGB')
            im.thumbnail((480, 480))
            im.save(os.path.join(a.folder, 'thumbnail.jpg'), quality=88)
        job.progress = 1.0
        job.set_state('COMPLETED', 'تصویرِ دارایی ساخته شد')
    else:
        job.progress = 1.0
        job.set_state('COMPLETED', 'خروجی آماده است (%d فایل)' % len(job.files or {}))


def requeue_stale():
    """کارِ کارگری که بیش از ۱۰ دقیقه خبری از او نیست، دوباره به صف برمی‌گردد."""
    n = 0
    for job in Job.objects.filter(owner='worker', worker__isnull=False).exclude(state__in=FINAL):
        w = job.worker
        if w and w.last_seen and (timezone.now() - w.last_seen).total_seconds() > 600:
            job.worker = None
            job.add_log('کارگرِ %s بی‌خبر ماند؛ کار دوباره در صف' % w.name, save=False)
            job.state = 'SCENE_BUILDING'
            job.save()
            n += 1
    return n


def recover_interrupted():
    """بعد از ری‌استارت/قطعیِ هماهنگ‌کننده: کارهای نیمه‌کارهٔ پنل به آخرین گامِ امن برمی‌گردند."""
    back = {'PLANNING': 'PENDING', 'SCENE_BUILDING': 'PLANNED', 'ASSEMBLING': 'QUALITY_CHECK'}
    n = 0
    for job in Job.objects.filter(owner='panel', state__in=list(back)):
        job.add_log('هماهنگ‌کننده دوباره روشن شد؛ «%s» از سر گرفته می‌شود' % job.get_state_display(), save=False)
        job.state = back[job.state]
        job.save()
        n += 1
    return n


def orchestrate_once():
    did = 0
    for job in Job.objects.filter(cancel_requested=True, owner='panel').exclude(state__in=FINAL):
        job.set_state('CANCELLED', 'لغو شد')
    for job in Job.objects.filter(owner='panel').exclude(state__in=FINAL).order_by('created')[:5]:
        try:
            if job.kind == 'plan' and job.state == 'PENDING':
                process_plan(job)
            elif job.kind != 'plan' and job.state in ('PENDING', 'PLANNED'):
                process_prepare(job)
            elif job.state == 'QUALITY_CHECK':
                process_finish(job)
            else:
                continue
            did += 1
        except Exception as e:
            job.error = traceback.format_exc()[-4000:]
            job.owner = 'panel'
            job.set_state('FAILED', str(e)[:380])
            did += 1
    requeue_stale()
    return did


# ───────────────────────── تصویرِ دارایی‌ها (با خودِ موتور)

def thumbnail_doc(kind, asset_id):
    r = reg()
    doc = S.new_scene('thumb', 3.0, '1:1' if kind != 'motion' else '9:16')
    doc['environment'] = {'id': 'studio_warm', 'params': {'decor': False}}
    doc['lighting'] = {'id': 'soft_beauty', 'params': {}}
    ch = r.default('character').id
    if kind == 'environment':
        doc['environment']['id'] = asset_id
        doc['lighting']['id'] = r.get('environment', asset_id).get('default_lighting', 'soft_beauty')
        doc['actors'] = [{'id': 'host', 'character': ch, 'mark': 'center'}]
        doc['products'] = [{'id': 'p1', 'asset': 'perfume_bottle', 'name': 'UpMarket', 'surface': list(r.get('environment', asset_id)['surfaces'])[0]}]
        doc['shots'] = [{'shot': 'medium', 'start': 0, 'duration': 3, 'subject': 'host', 'move': 'static',
                         'params': {'height': 1.5, 'lens': 35, 'fstop': 4.0}}]
        doc['output']['aspect'] = '4:5'
    elif kind == 'character':
        doc['actors'] = [{'id': 'host', 'character': asset_id, 'mark': 'center'}]
        doc['shots'] = [{'shot': 'medium_close', 'start': 0, 'duration': 3, 'subject': 'host', 'move': 'static'}]
        doc['output']['aspect'] = '4:5'
    elif kind == 'product':
        doc['products'] = [{'id': 'p1', 'asset': asset_id, 'name': 'UpMarket', 'surface': 'table_center',
                            'params': {'brand': 'UpMarket 3D'}}]
        doc['shots'] = [{'shot': 'product_hero', 'start': 0, 'duration': 3, 'subject': 'p1', 'move': 'static'}]
    elif kind == 'motion':
        m = r.get('motion', asset_id)
        d = m['duration']['default']
        doc['output']['duration'] = round(d + 1.0, 2)
        doc['actors'] = [{'id': 'host', 'character': ch, 'mark': 'center'}]
        doc['products'] = [{'id': 'p1', 'asset': 'perfume_bottle', 'name': 'UpMarket', 'surface': 'table_right'}]
        acts = []
        t = 0.3
        req = (m.get('product') or {}).get('requires')
        if req == 'in_hand':
            acts.append({'actor': 'host', 'motion': 'pick_up', 'start': 0.1, 'duration': 1.2, 'params': {'product': 'p1'}})
            t = 1.4
            doc['output']['duration'] = round(d + 2.4, 2)
        acts.append({'actor': 'host', 'motion': asset_id, 'start': t, 'duration': d, 'params': {'product': 'p1'}})
        doc['actions'] = acts
        doc['shots'] = [{'shot': 'medium', 'start': 0, 'duration': doc['output']['duration'], 'subject': 'host', 'move': 'static'}]
    doc, _, rep = repair(doc, r)
    return doc


def request_thumbnail(kind, asset_id):
    doc = thumbnail_doc(kind, asset_id)
    p, _ = Project.objects.get_or_create(title='__thumbnails__', defaults={'brief': {}})
    if kind == 'motion':
        params = {'asset_kind': kind, 'asset_id': asset_id, 'mode': 'render', 'document': doc}
        prof = 'animatic'
    else:
        params = {'asset_kind': kind, 'asset_id': asset_id, 'mode': 'still', 'frame': 30, 'document': doc}
        prof = 'preview'
    return Job.objects.create(project=p, kind='thumbnail', profile=prof, params=params, state='PLANNED')
