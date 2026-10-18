# -*- coding: utf-8 -*-
"""محیطِ پایتونِ جدا برای هر پروژه (idea.md §۸: «نصبِ وابستگی‌ها در محیطِ ایزوله»).

پروژه‌های ساختهٔ استودیو همان venv ِ استودیو را کافی دارند (Django + Pillow).
پروژهٔ واردشده ممکن است بسته‌های دیگری بخواهد ⇒ دکمهٔ «نصبِ وابستگی‌ها» یک
`.venv` داخلِ پوشهٔ همان پروژه می‌سازد و requirements.txt را در آن نصب می‌کند.
از آن به بعد check/migrate/پیش‌نمایشِ آن پروژه با همان .venv اجرا می‌شود.
"""
import os
import subprocess
import sys
import threading

LOG = '.studio-deps.log'
STATUS = '.studio-deps.status'


def _venv_bin(root, name):
    """مسیرِ پایتون/pip ِ .venv — لینوکس bin/، ویندوز Scripts/*.exe"""
    if os.name == 'nt':
        return os.path.join(root, '.venv', 'Scripts', name + '.exe')
    return os.path.join(root, '.venv', 'bin', name)


def python_for(project):
    py = _venv_bin(str(project.path), 'python')
    return py if os.path.exists(py) else sys.executable


def has_own_env(project):
    return os.path.exists(_venv_bin(str(project.path), 'python'))


def status(project):
    try:
        with open(os.path.join(str(project.path), STATUS), encoding='utf-8') as fh:
            return fh.read().strip()
    except OSError:
        return ''


def log_tail(project, n=6000):
    try:
        with open(os.path.join(str(project.path), LOG), encoding='utf-8', errors='replace') as fh:
            return fh.read()[-n:]
    except OSError:
        return ''


def _set(project, value):
    with open(os.path.join(str(project.path), STATUS), 'w', encoding='utf-8') as fh:
        fh.write(value)


def install(project, sync=False):
    """ساختِ .venv + نصبِ requirements.txt در پس‌زمینه."""
    root = str(project.path)
    if status(project) == 'running':
        return False
    _set(project, 'running')

    def job():
        with open(os.path.join(root, LOG), 'w', encoding='utf-8') as log:
            def run(cmd, timeout):
                log.write('$ %s\n' % ' '.join(cmd))
                log.flush()
                r = subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                log.write('\n[خروجی: %d]\n' % r.returncode)
                log.flush()
                return r.returncode == 0
            try:
                ok = run([sys.executable, '-m', 'venv', '.venv'], 300)
                pip = [_venv_bin(root, 'python'), '-m', 'pip']    # ویندوز pip.exe را برای ارتقای خودش نمی‌پذیرد
                ok = ok and run(pip + ['install', '--upgrade', 'pip', 'wheel'], 600)
                if os.path.exists(os.path.join(root, 'requirements.txt')):
                    ok = ok and run(pip + ['install', '-r', 'requirements.txt'], 1800)
                else:
                    log.write('requirements.txt نبود ⇒ فقط Django نصب می‌شود.\n')
                    ok = ok and run(pip + ['install', 'Django>=4.2,<5.1', 'Pillow'], 900)
                _set(project, 'ok' if ok else 'failed')
            except Exception as exc:  # noqa
                log.write('\nخطا: %r\n' % exc)
                _set(project, 'failed')

    if sync:
        job()
    else:
        threading.Thread(target=job, daemon=True, name='deps-%s' % project.slug).start()
    return True
