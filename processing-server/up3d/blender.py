"""اجرای موتورِ Blender (بی‌مانیتور) و خواندنِ پیشرفت.

پروتکلِ خروجیِ موتور (یک خط در stdout):
  UP3D:STAGE <نام>          مرحله (build, bake, render, encode, export)
  UP3D:PROGRESS <i> <n>     فریم i از n
  UP3D:INFO <json>          اطلاعاتِ دلخواه (زمانِ هر فریم، دستگاه، …)
"""
import json
import os
import subprocess
import sys
import time

from . import paths


class EngineError(Exception):
    pass


def engine_cmd(mode, compiled_path, out_dir, extra=()):
    exe = paths.blender_binary()
    if not exe:
        raise EngineError('Blender پیدا نشد (UP3D_BLENDER یا vendor/blender)')
    script = os.path.join(paths.ENGINE, 'run.py')
    return [exe, '-b', '--factory-startup', '--python-exit-code', '3', '--python', script, '--',
            '--mode', mode, '--compiled', compiled_path, '--out', out_dir] + list(extra)


def run_engine(mode, compiled_path, out_dir, on_event=None, should_cancel=None, nice=10, threads=0,
               extra=(), timeout=None, log_path=None):
    os.makedirs(out_dir, exist_ok=True)
    cmd = engine_cmd(mode, compiled_path, out_dir, list(extra) + (['--threads', str(threads)] if threads else []))
    env = dict(os.environ)
    env['BLENDER_USER_RESOURCES'] = paths.blender_user_resources()
    env['UP3D_ROOT'] = paths.ROOT
    env['PYTHONIOENCODING'] = 'utf-8'
    pre = None
    if nice and hasattr(os, 'nice'):
        pre = lambda: os.nice(nice)  # noqa: E731 — رندر هیچ‌وقت سایت‌های دیگرِ سرور را کند نکند
    flags = 0
    if sys.platform.startswith('win'):
        flags = 0x00004000   # BELOW_NORMAL_PRIORITY_CLASS
    t0 = time.time()
    log = open(log_path, 'a', encoding='utf-8') if log_path else None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, preexec_fn=pre,
                            creationflags=flags, text=True, encoding='utf-8', errors='replace', bufsize=1)
    tail = []
    try:
        for line in proc.stdout:
            line = line.rstrip('\n')
            if log:
                log.write(line + '\n')
            tail.append(line)
            tail = tail[-80:]
            if line.startswith('UP3D:') and on_event:
                parts = line.split(' ', 1)
                kind = parts[0][5:]
                payload = parts[1] if len(parts) > 1 else ''
                if kind == 'PROGRESS':
                    i, n = payload.split()[:2]
                    on_event('progress', {'frame': int(i), 'total': int(n), 'elapsed': time.time() - t0})
                elif kind == 'INFO':
                    try:
                        on_event('info', json.loads(payload))
                    except ValueError:
                        on_event('info', {'text': payload})
                else:
                    on_event(kind.lower(), {'text': payload})
            if should_cancel and should_cancel():
                proc.terminate()
                raise EngineError('لغو شد')
            if timeout and time.time() - t0 > timeout:
                proc.terminate()
                raise EngineError('زمانِ مجاز تمام شد')
        rc = proc.wait()
    finally:
        if log:
            log.close()
        if proc.poll() is None:
            proc.kill()
    if rc != 0:
        err = [l for l in tail if 'Error' in l or 'Traceback' in l or 'UP3D:ERROR' in l]
        raise EngineError('موتور با کد %s متوقف شد. %s' % (rc, ' | '.join((err or tail)[-6:])))
    return {'seconds': round(time.time() - t0, 1)}
