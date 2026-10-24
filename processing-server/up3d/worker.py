"""کارگرِ رندر. روی سرور (اولویتِ پایین) یا هر کامپیوترِ دیگری (مثلاً PC با RTX) اجرا می‌شود،
از پنل کار می‌گیرد، Blender را اجرا می‌کند و خروجی را برمی‌گرداند.

    python -m up3d worker --server http://SERVER:8030 --token TOKEN [--name gpu-pc] [--profiles all]

پروتکل (همه با سرآیندِ Authorization: Worker <token>):
  POST /api/worker/heartbeat/                 اعلامِ حضور و توانایی‌ها
  POST /api/worker/claim/                     گرفتنِ یک کار (یا هیچ)
  GET  /api/worker/jobs/<id>/package/         بستهٔ کار (compiled.json + برچسب‌ها + مدل‌ها)
  POST /api/worker/jobs/<id>/progress/        پیشرفت (پاسخ ممکن است cancel=true باشد)
  POST /api/worker/jobs/<id>/upload/          فایل‌های خروجی
  POST /api/worker/jobs/<id>/finish/          پایان (موفق/ناموفق)
"""
import glob
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
import traceback
import zipfile

from . import __version__, paths, pipeline
from .client import ApiClient, ApiError


def probe_devices():
    """GPU های قابلِ استفادهٔ Cycles را با خودِ Blender می‌پرسد (یک بار)."""
    exe = paths.blender_binary()
    if not exe:
        return {'blender': None, 'gpu': None}
    code = ("import bpy\nres=[]\np=bpy.context.preferences.addons['cycles'].preferences\n"
            "for t in ('OPTIX','CUDA','HIP','ONEAPI','METAL'):\n"
            "    try:\n        p.compute_device_type=t; p.get_devices()\n"
            "        res += ['%s:%s' % (t, d.name) for d in p.devices if d.type==t]\n"
            "    except Exception: pass\nprint('UP3D-DEVICES', '|'.join(res))\nprint('UP3D-VERSION', bpy.app.version_string)")
    try:
        out = subprocess.run([exe, '-b', '--factory-startup', '--python-expr', code], capture_output=True, text=True,
                             timeout=180).stdout
    except Exception as e:
        return {'blender': exe, 'gpu': None, 'error': str(e)}
    dev = ver = ''
    for line in out.splitlines():
        if line.startswith('UP3D-DEVICES'):
            dev = line.split(' ', 1)[1] if ' ' in line else ''
        if line.startswith('UP3D-VERSION'):
            ver = line.split(' ', 1)[1]
    gpus = [d for d in dev.split('|') if d]
    return {'blender': exe, 'blender_version': ver, 'gpu': gpus or None}


class Worker:
    def __init__(self, server, token, name=None, profiles=None, nice=15, threads=0, work_dir=None, once=False, log=print):
        self.api = ApiClient(server, token, scheme='Worker')
        self.name = name or socket.gethostname()
        self.profiles = profiles
        self.nice = nice
        self.threads = threads
        self.work = work_dir or os.path.join(paths.DATA, 'worker')
        self.once = once
        self.log = log
        os.makedirs(self.work, exist_ok=True)
        self.caps = None

    def capabilities(self):
        if self.caps is None:
            dev = probe_devices()
            ud = paths.blender_user_resources()
            mpfb = os.path.isfile(os.path.join(ud, 'extensions', 'user_default', 'mpfb', '__init__.py'))
            self.caps = {'name': self.name, 'version': __version__, 'os': platform.platform(), 'cpu_count': os.cpu_count(),
                         'profiles': self.profiles or 'auto', 'mpfb': mpfb, 'features': ['ping', 'release', 'packs', 'clips', 'editor'],
                         **dev}
            if not mpfb:
                self.log('هشدار: دادهٔ کاراکترهای MPFB در %s نیست ⇐ کارهای با مجریِ ساخته‌شده به این کارگر داده نمی‌شود' % ud)
            self.log('کارگر %s · Blender %s · GPU: %s' % (self.name, dev.get('blender_version'), dev.get('gpu') or 'ندارد'))
        return self.caps

    def loop(self):
        last_hb = 0
        while True:
            try:
                if time.time() - last_hb > 30:
                    self.api.post('/api/worker/heartbeat/', self.capabilities())
                    last_hb = time.time()
                r = self.api.post('/api/worker/claim/', self.capabilities())
                job = r.get('job')
                if job:
                    self.run_job(job)
                    last_hb = 0
                    if self.once:
                        return
                    continue
            except ApiError as e:
                self.log('پنل در دسترس نیست: %s' % e)
            if self.once:
                return
            time.sleep(6)

    @staticmethod
    def _digest(path):
        if not os.path.isfile(path):
            return None
        with open(path, 'rb') as fh:
            return hashlib.sha1(fh.read()).hexdigest()

    def run_job(self, job):
        jid = job['id']
        jdir = os.path.join(self.work, str(jid))
        # کارِ نیمه‌تمامی که دوباره به همین کارگر رسید (ری‌استارت، یا واگذاریِ موقت): فریم‌های ساخته‌شده نگه داشته می‌شوند
        # و اگر compiled.json همان باشد، رندر از همان‌جا ادامه می‌یابد (موتور فریمِ موجود را دوباره نمی‌سازد)
        old_digest = self._digest(os.path.join(jdir, 'compiled.json'))
        keep = os.path.join(self.work, '%s.frames-keep' % jid)
        shutil.rmtree(keep, ignore_errors=True)
        if old_digest and os.path.isdir(os.path.join(jdir, 'frames')):
            os.replace(os.path.join(jdir, 'frames'), keep)
        shutil.rmtree(jdir, ignore_errors=True)
        os.makedirs(jdir)
        self.log('کارِ %s (%s، %s) گرفته شد' % (jid, job.get('kind'), job.get('profile')))
        pkg = os.path.join(jdir, 'package.zip')
        last = [0.0]
        cancel = [False]
        release = [None]           # handoff (به GPU) / yield (جا برای کارِ کوتاه) ⇐ بی‌finish، فریم‌ها می‌مانند
        cur_state = ['SCENE_BUILDING']

        def report(state, **kw):
            cur_state[0] = state
            try:
                r = self.api.post('/api/worker/jobs/%s/progress/' % jid, {'state': state, **kw})
                if r.get('cancel'):
                    cancel[0] = True
                if r.get('release'):
                    release[0] = r['release']
                    cancel[0] = True
            except ApiError as e:
                self.log('گزارشِ پیشرفت نرسید: %s' % e)

        # تپشِ قلب در طولِ کار: فریمِ سنگینِ CPU ده‌ها دقیقه چیزی گزارش نمی‌کند؛ بی این، پنل کارگر را «آفلاین»
        # می‌دید و بعد از ۱۰ دقیقه کار را دوباره در صف می‌گذاشت در حالی که این‌جا هنوز رندر می‌شد
        stop = threading.Event()

        def pinger():
            while not stop.wait(30):
                report(cur_state[0])
        threading.Thread(target=pinger, daemon=True).start()

        def on_event(kind, data):
            if kind == 'stage':
                st = {'build': 'SCENE_BUILDING', 'animate': 'SCENE_BUILDING', 'bake': 'SCENE_BUILDING',
                      'render': 'RENDERING', 'encode': 'RENDERING', 'export': 'RENDERING'}.get(data.get('text'), None)
                if st:
                    report(st, message='مرحله: %s' % data.get('text'))
            elif kind == 'progress' and time.time() - last[0] > 4:
                last[0] = time.time()
                report('RENDERING' if self._rendering else 'SCENE_BUILDING', frame=data['frame'], total=data['total'],
                       elapsed=round(data['elapsed'], 1))
            elif kind == 'info' and 'sec_per_frame' in data:
                report('RENDERING', sec_per_frame=data['sec_per_frame'], frame=data.get('done'), total=data.get('total'))
            elif kind == 'info' and data.get('device'):
                report('RENDERING', message='دستگاه: %s' % json.dumps(data.get('device'), ensure_ascii=False))
        self._rendering = False
        try:
            report('SCENE_BUILDING', message='دریافتِ بسته')
            self.api.download('/api/worker/jobs/%s/package/' % jid, pkg)
            with zipfile.ZipFile(pkg) as z:
                z.extractall(jdir)
            if os.path.isdir(keep):
                if old_digest and old_digest == self._digest(os.path.join(jdir, 'compiled.json')):
                    os.replace(keep, os.path.join(jdir, 'frames'))
                    n = len(glob.glob(os.path.join(jdir, 'frames', 'f_*.png')))
                    report('SCENE_BUILDING', message='ادامهٔ رندر از %d فریمِ ساخته‌شده' % n)
                else:
                    shutil.rmtree(keep, ignore_errors=True)
            kind = job.get('kind', 'render')
            t0 = time.time()

            def ev(k, d):
                if k == 'stage' and d.get('text') in ('render', 'export', 'encode'):
                    self._rendering = True
                on_event(k, d)
            mode = job.get('mode') or {'render': 'render', 'export': 'export', 'contact': 'contact'}.get(kind, 'render')
            extra = list(job.get('extra') or [])
            pipeline.render(jdir, ev, lambda: cancel[0], self.nice, self.threads,
                            os.path.join(jdir, 'engine.log'), mode=mode, extra=extra)
            files = {}
            for name in ('render.mp4', 'engine_report.json'):
                p = os.path.join(jdir, name)
                if os.path.isfile(p):
                    files[name.replace('.', '_')] = p
            for i, p in enumerate(sorted(glob.glob(os.path.join(jdir, 'scene.*')))):
                files['export_%d' % i] = p
            for i, p in enumerate(sorted(glob.glob(os.path.join(jdir, 'contact_*.png')) +
                                         glob.glob(os.path.join(jdir, 'still_*.png')))):
                files['image_%02d' % i] = p
            frames = sorted(glob.glob(os.path.join(jdir, 'frames', 'f_*.png')))
            if frames:
                files['first_frame'] = frames[len(frames) // 3]
            log = os.path.join(jdir, 'engine.log')
            if os.path.isfile(log):
                files['engine_log'] = log
            report('RENDERING', message='فرستادنِ خروجی (%d فایل)' % len(files))
            self.api.upload('/api/worker/jobs/%s/upload/' % jid, files)
            self.api.post('/api/worker/jobs/%s/finish/' % jid, {'ok': True, 'seconds': round(time.time() - t0, 1)})
            self.log('کارِ %s تمام شد (%.0f ثانیه)' % (jid, time.time() - t0))
        except Exception as e:
            if release[0]:
                why = {'handoff': 'به کارگرِ GPU واگذار شد', 'yield': 'برای کارِ کوتاه‌ترِ در صف موقتاً کنار رفت'}.get(
                    release[0], release[0])
                self.log('کارِ %s %s؛ فریم‌های ساخته‌شده نگه داشته شد' % (jid, why))
                return
            traceback.print_exc()
            msg = str(e)[:1500]
            try:
                log = os.path.join(jdir, 'engine.log')
                if os.path.isfile(log):
                    self.api.upload('/api/worker/jobs/%s/upload/' % jid, {'engine_log': log})
                self.api.post('/api/worker/jobs/%s/finish/' % jid, {'ok': False, 'error': msg, 'cancelled': cancel[0]})
            except ApiError:
                pass
            self.log('کارِ %s ناموفق: %s' % (jid, msg))
        finally:
            stop.set()
            if not os.environ.get('UP3D_KEEP_WORK') and not release[0]:
                shutil.rmtree(os.path.join(jdir, 'frames'), ignore_errors=True)
