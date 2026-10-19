# -*- coding: utf-8 -*-
"""پیش‌نمایشِ زنده: پروژهٔ تولیدشده را روی یک پورتِ جدا اجرا می‌کند.

همان چیزی است که در idea.md «اجرای ایزوله روی همان سرور» نامیده شده —
هر پروژه یک فرایندِ مستقلِ runserver با pid و لاگِ خودش داخلِ پوشهٔ
همان پروژه. استودیو فقط روشن/خاموشش می‌کند.

⚠ رمزِ ادمینِ پیش‌نمایش هر بار تصادفی است (نه admin/admin) چون پورت‌ها رو به
   اینترنت باز است؛ در صفحهٔ «پیش‌نمایش» نشان داده می‌شود.
"""
import json
import os
import secrets
import signal
import socket
import subprocess
import time

from django.conf import settings

from . import envs

PID_FILE = '.preview.pid'
PORT_FILE = '.preview.port'
LOG_FILE = '.preview.log'
PASS_FILE = '.preview.admin'

# کاربرِ ادمینِ پیش‌نمایش؛ با مدلِ کاربرِ سفارشی (ایمیل/موبایل به‌جای نام) هم کار کند
ADMIN_SCRIPT = """
import os
from django.contrib.auth import get_user_model
U = get_user_model(); f = U.USERNAME_FIELD; pw = os.environ['PREVIEW_ADMIN_PASSWORD']
def guess(k):
    k = k.lower()
    return 'admin@local.test' if 'mail' in k else ('09000000000' if ('phone' in k or 'mobile' in k) else 'admin')
u = U.objects.filter(**{f: guess(f)}).first()
if u is None:
    extra = {k: guess(k) for k in getattr(U, 'REQUIRED_FIELDS', [])}
    extra[f] = guess(f)
    u = U.objects.create_superuser(password=pw, **extra)
u.set_password(pw); u.is_staff = True; u.is_superuser = True; u.is_active = True; u.save()
print('STUDIO_ADMIN_USER=' + str(getattr(u, f)))
"""


def _p(project, name):
    return os.path.join(str(project.path), name)


WINDOWS = os.name == 'nt'


def _alive(pid):
    if WINDOWS:
        # ⚠ در ویندوز os.kill(pid, 0) یعنی Ctrl+C فرستادن؛ با API ِ خودِ ویندوز بپرس
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259              # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    # زامبی را زنده حساب نکن
    try:
        with open('/proc/%d/stat' % pid) as fh:
            return fh.read().split()[2] != 'Z'
    except OSError:
        return True


def _kill(pid):
    if WINDOWS:
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (OSError, ProcessLookupError, AttributeError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass


def status(project):
    """(در حالِ اجرا؟، پورت، pid)"""
    try:
        pid = int(open(_p(project, PID_FILE)).read().strip())
        port = int(open(_p(project, PORT_FILE)).read().strip())
    except (OSError, ValueError):
        return False, None, None
    if not _alive(pid):
        return False, port, None
    return True, port, pid


def admin_login(project):
    """⇒ (نامِ کاربری، رمز) ادمینِ پیش‌نمایش؛ اگر ساخته نشد ('', '')."""
    try:
        data = json.loads(open(_p(project, PASS_FILE), encoding='utf-8').read())
        return data.get('user') or '', data.get('password') or ''
    except (OSError, ValueError):
        return '', ''


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def _pick_port():
    lo, hi = settings.PREVIEW_PORT_RANGE
    for port in range(lo, hi + 1):
        if _port_free(port):
            return port
    raise RuntimeError('پورتِ آزادی در بازهٔ %d–%d نیست.' % (lo, hi))


def log_tail(project, n=4000):
    try:
        with open(_p(project, LOG_FILE), encoding='utf-8', errors='replace') as fh:
            return fh.read()[-n:]
    except OSError:
        return ''


def env_for(project):
    root = str(project.path)
    return dict(os.environ, PYTHONPATH=root, DJANGO_SETTINGS_MODULE=project.settings_module_name,
                DJANGO_ALLOWED_HOSTS='*', DJANGO_DEBUG='True', PYTHONUNBUFFERED='1',
                # پروژهٔ اصلیِ واردشده خودش استودیو را سوار می‌کند؛ این‌جا نباید
                STUDIO_MOUNTED='False',
                # تنظیماتِ تولیدشده با این پرچم X-Frame-Options را برمی‌دارد تا پیش‌نمایش داخلِ
                # iframe ِ پنل (پورتِ دیگر) باز شود
                STUDIO_PREVIEW='1')


def start(project):
    """اجرا؛ اگر از قبل روشن است همان را برمی‌گرداند. ⇒ (port, pid)"""
    running, port, pid = status(project)
    if running:
        return port, pid

    root = str(project.path)
    env = env_for(project)
    py = envs.python_for(project)
    logf = open(_p(project, LOG_FILE), 'ab')

    # ۱) مهاجرت + کاربرِ ادمینِ پیش‌نمایش با رمزِ تازه — فقط برای دیدن
    subprocess.run([py, 'manage.py', 'migrate', '--noinput'],
                   cwd=root, env=env, stdout=logf, stderr=logf, timeout=300)
    password = secrets.token_urlsafe(9)
    r = subprocess.run([py, 'manage.py', 'shell', '-c', ADMIN_SCRIPT],
                       cwd=root, env=dict(env, PREVIEW_ADMIN_PASSWORD=password),
                       stdout=subprocess.PIPE, stderr=logf, timeout=120)
    out = (r.stdout or b'').decode('utf-8', 'replace')
    logf.write(r.stdout or b'')
    user = ''
    for line in out.splitlines():
        if line.startswith('STUDIO_ADMIN_USER='):
            user = line.split('=', 1)[1].strip()
    with open(_p(project, PASS_FILE), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'user': user, 'password': password if user else ''}))

    # ۲) خودِ سرور، در سشنِ جدا تا با استودیو گره نخورد
    port = _pick_port()
    detach = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {'start_new_session': True}
    proc = subprocess.Popen(
        [py, 'manage.py', 'runserver', '%s:%d' % (getattr(settings, 'PREVIEW_BIND', '0.0.0.0'), port), '--noreload'],
        cwd=root, env=env, stdout=logf, stderr=logf, close_fds=True, **detach)
    with open(_p(project, PID_FILE), 'w') as fh:
        fh.write(str(proc.pid))
    with open(_p(project, PORT_FILE), 'w') as fh:
        fh.write(str(port))

    # تا ۱۲ ثانیه صبر کن که پورت باز شود
    for _ in range(24):
        time.sleep(0.5)
        if not _port_free(port):
            break
        if proc.poll() is not None:
            break
    return port, proc.pid


def stop(project):
    running, port, pid = status(project)
    if pid:
        _kill(pid)
    for name in (PID_FILE, PORT_FILE):
        try:
            os.remove(_p(project, name))
        except OSError:
            pass
    return running
