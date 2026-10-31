# -*- coding: utf-8 -*-
"""تنها جایی که انتشارِ سایت به سیستم‌عامل دست می‌زند (کاربر، systemd، nginx، certbot).

قاعده‌ها، چون این کد با دسترسیِ root اجرا می‌شود و روی همین سرور چغر و tamouz هم هستند:
  · کلید و دامنه با الگوی سفت سنجیده می‌شوند و هیچ فرمانی از راهِ شل اجرا نمی‌شود.
  · فقط فایل‌هایی با پیشوندِ خودمان نوشته می‌شوند: nm-site-*.conf و nm-site-*.service/.socket
  · هر تغییرِ nginx: اول nginx -t و بعد reload؛ اگر رد شد فایلِ قبلی برمی‌گردد و nginx دست‌نخورده می‌ماند.
  · به دادهٔ زیرِ shared/ (که مالِ کاربرِ سایت است) هیچ‌وقت مستقیم با root دست نمی‌زنیم؛ همه چیز از
    sandbox_run می‌گذرد، چون کدِ سایت می‌تواند آن‌جا symlink بکارد.
  · کدِ سایت فقط داخلِ sandbox اجرا می‌شود؛ پیش از هر reload اگر nginx از قبل خراب باشد کاری نمی‌کنیم.
"""
import fcntl
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

from django.conf import settings

KEY_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,26}[a-z0-9])?$')
DOMAIN_RE = re.compile(r'^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')
RID_RE = re.compile(r'^[0-9]{8}-[0-9]{6}(?:-[0-9a-f]{4})?$')
PREFIX = 'nm-site-'
ENV_VALUE_RE = re.compile(r'^[^\r\n\x00"\\$`]*$')
PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'


class SysError(Exception):
    """شکستِ یک کارِ سیستمی؛ متن فنی است و بالادست آن را فارسی می‌کند."""


def conf(name, default):
    return getattr(settings, name, default)


def sites_root():
    return str(conf('NM_SITES_ROOT', '/var/www/NM/sites'))


def vhost_dir():
    return str(conf('NM_SITES_VHOST_DIR', '/www/server/panel/vhost/nginx'))


def unit_dir():
    return str(conf('NM_SITES_UNIT_DIR', '/etc/systemd/system'))


def webroot():
    return str(conf('NM_SITES_WEBROOT', '/var/www/html'))


def runtime_python():
    return os.path.join(sites_root(), '_runtime', 'venv', 'bin', 'python')


# ─────────────────────────────── اعتبارسنجی
def check_key(key):
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise SysError('invalid site key: %r' % (key,))
    return key


def check_rid(rid):
    if not isinstance(rid, str) or not RID_RE.match(rid):
        raise SysError('invalid release id: %r' % (rid,))
    return rid


def check_domain(name):
    if not isinstance(name, str) or not DOMAIN_RE.match(name):
        raise SysError('invalid domain: %r' % (name,))
    return name


def check_port(port):
    if not isinstance(port, int) or not 1024 < port < 65536:
        raise SysError('invalid port: %r' % (port,))
    return port


def site_root(key):
    return os.path.join(sites_root(), check_key(key))


def user_of(key):
    return 'nms-' + check_key(key)


def unit_of(key):
    return PREFIX + check_key(key)


def lineage_of(key):
    return PREFIX + check_key(key)


def vhost_path(key):
    return os.path.join(vhost_dir(), PREFIX + check_key(key) + '.conf')


# ─────────────────────────────── اجرای فرمان
def run(cmd, timeout=120, check=True, stdin=None):
    """اجرای یک فرمان بی‌شل. ⇒ (کد، stdout متنی/بایتی). stdin اگر بایت باشد خروجی هم بایت است."""
    env = {'PATH': PATH, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, input=stdin)
    except (OSError, subprocess.SubprocessError) as exc:
        if check:
            raise SysError('%s: %s' % (cmd[0], exc))
        return 1, ''
    out = p.stdout.decode('utf-8', 'replace') + p.stderr.decode('utf-8', 'replace')
    if check and p.returncode != 0:
        raise SysError('%s failed (%d): %s' % (' '.join(cmd[:3]), p.returncode, out[-1500:]))
    return p.returncode, out


@contextmanager
def _lock(name, blocking=True):
    path = os.path.join(sites_root(), '.lock-' + name)
    os.makedirs(sites_root(), exist_ok=True)
    fh = open(path, 'w')
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except OSError:
            raise SysError('busy')
        yield
    finally:
        fh.close()


def site_lock(key):
    """یک کار در هر لحظه برای هر سایت؛ قفل با مرگِ فرایند خودش آزاد می‌شود."""
    return _lock(check_key(key), blocking=False)


def _atomic_write(path, text, mode=0o644):
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.nm-tmp-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ─────────────────────────────── کاربر و پوشه‌ها
def ensure_user(key):
    name = user_of(key)
    code, _ = run(['id', '-u', name], check=False)
    if code != 0:
        run(['useradd', '--system', '--no-create-home', '--home-dir', '/nonexistent', '--shell', '/usr/sbin/nologin',
             '--user-group', name])
    return name


def _ids(key):
    import pwd
    row = pwd.getpwnam(user_of(key))
    return row.pw_uid, row.pw_gid


def ensure_dirs(key):
    root = site_root(key)
    uid, gid = _ids(key)
    for path, mode, owner in ((root, 0o755, (0, 0)), (root + '/releases', 0o755, (0, 0)), (root + '/shared', 0o755, (0, 0)),
                              (root + '/shared/db', 0o700, (uid, gid)), (root + '/shared/media', 0o755, (uid, gid)),
                              (root + '/backups', 0o700, (0, 0))):
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            os.chmod(path, mode)
            os.chown(path, *owner)


def write_env(key, values):
    """site.env فقط برای root خواناست؛ systemd آن را می‌خواند و به فرایندِ سایت می‌دهد."""
    lines = []
    for k, v in sorted(values.items()):
        if not re.match(r'^[A-Z][A-Z0-9_]*$', k) or not ENV_VALUE_RE.match(str(v)):
            raise SysError('bad env %s' % k)
        lines.append('%s="%s"' % (k, v))
    _atomic_write(os.path.join(site_root(key), 'site.env'), '\n'.join(lines) + '\n', 0o600)


def read_env(key):
    out = {}
    try:
        with open(os.path.join(site_root(key), 'site.env'), encoding='utf-8') as fh:
            for line in fh:
                if '=' in line:
                    k, v = line.rstrip('\n').split('=', 1)
                    out[k] = v.strip('"')
    except OSError:
        pass
    return out


def new_secret():
    return secrets.token_urlsafe(50).replace('-', 'x').replace('_', 'y')


# ─────────────────────────────── محیطِ پایتونِ مشترکِ سایت‌ها
def ensure_runtime(names):
    """venv ِ فقط‌خواندنی و مشترک تا هر سایت ۱۰۰ مگابایت جدا نخورد. بسته‌ها از روی همان نسخه‌هایی که پیش‌نمایش
    با آن‌ها آزموده شده کپی می‌شوند، نه از اینترنت (files.pythonhosted.org از این سرور گاهی قطع می‌شود)."""
    import importlib.metadata as md
    base = os.path.join(sites_root(), '_runtime')
    ready = os.path.join(base, 'READY')
    if os.path.exists(ready):
        return False
    os.makedirs(base, exist_ok=True)
    os.chmod(sites_root(), 0o755)
    os.chmod(base, 0o755)
    venv = os.path.join(base, 'venv')
    shutil.rmtree(venv, ignore_errors=True)
    run(['/usr/bin/python3', '-m', 'venv', venv], timeout=300)
    site = run([os.path.join(venv, 'bin', 'python'), '-I', '-c', 'import site;print(site.getsitepackages()[0])'])[1].strip()
    seen, todo = {}, list(names)
    while todo:
        name = todo.pop()
        low = re.sub(r'[-_.]+', '-', name).lower()
        if low in seen:
            continue
        dist = md.distribution(name)
        seen[low] = dist.version
        for f in dist.files or []:
            rel = str(f)
            if rel.startswith('..') or '__pycache__' in rel:
                continue
            target = os.path.join(site, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(str(f.locate()), target)
        for req in dist.requires or []:
            if 'extra ==' in req:
                continue
            todo.append(re.match(r'^[A-Za-z0-9_.\-]+', req).group(0))
    run([os.path.join(venv, 'bin', 'python'), '-I', '-m', 'compileall', '-q', site], check=False, timeout=300)
    run([os.path.join(venv, 'bin', 'python'), '-I', '-c', 'import django,PIL,gunicorn'], timeout=30)
    with open(ready, 'w') as fh:
        fh.write(' '.join('%s==%s' % kv for kv in sorted(seen.items())) + '\n')
    return True


def ensure_common(down_html):
    folder = os.path.join(sites_root(), '_common')
    os.makedirs(folder, exist_ok=True)
    os.chmod(folder, 0o755)
    _atomic_write(os.path.join(folder, '__nm_down.html'), down_html, 0o644)


# ─────────────────────────────── جعبهٔ ایزوله
def sandbox_props(key, extra_rw=(), memory_mb=None, cpu=None):
    """خواصِ مشترکِ سرویس و اجراهای موقت. فقط سیستم‌فایلِ خودِ سایت و همان venv دیده می‌شود."""
    root = site_root(key)
    user = user_of(key)
    runtime = os.path.join(sites_root(), '_runtime')
    props = [
        'User=%s' % user, 'Group=%s' % user,
        'NoNewPrivileges=yes', 'PrivateTmp=yes', 'PrivateDevices=yes', 'ProtectSystem=strict', 'ProtectHome=yes',
        'ProtectKernelTunables=yes', 'ProtectKernelModules=yes', 'ProtectKernelLogs=yes', 'ProtectControlGroups=yes',
        'ProtectClock=yes', 'ProtectHostname=yes', 'ProtectProc=invisible', 'ProcSubset=pid',
        'RestrictNamespaces=yes', 'RestrictRealtime=yes', 'RestrictSUIDSGID=yes', 'LockPersonality=yes',
        'CapabilityBoundingSet=', 'AmbientCapabilities=', 'SystemCallArchitectures=native',
        'SystemCallFilter=@system-service', 'SystemCallFilter=~@privileged @resources', 'SystemCallErrorNumber=EPERM', 'UMask=0027',
        # هیچ سوکتِ محلی: نه redis/mysql/سوکتِ گانیکورنِ بقیه. فقط TCP
        'RestrictAddressFamilies=AF_INET AF_INET6',
        'IPAddressAllow=127.0.0.53/32',
    ]
    # سوکتِ سرویس را systemd می‌دهد، پس این قاعده به درخواست‌های nginx نمی‌خورد؛ فقط تماسِ بیرونیِ کدِ سایت را می‌بندد
    props += ['IPAddressDeny=%s' % x for x in ('localhost', 'link-local', 'multicast', '10.0.0.0/8', '172.16.0.0/12',
                                               '192.168.0.0/16', public_ip())]
    hidden = ('/var/www', '/www', '/srv', '/opt', '/mnt', '/media', '/var/log', '/var/lib', '/var/spool', '/var/backups', '/var/mail',
              '/etc/letsencrypt', '/etc/nginx', '/etc/ssh', '/etc/systemd', '/etc/ssl/private', '/etc/redis', '/boot', '/lost+found')
    props += ['TemporaryFileSystem=%s:ro' % x for x in hidden if os.path.isdir(x)]
    props += ['BindReadOnlyPaths=%s' % root, 'BindReadOnlyPaths=%s' % runtime,
              'InaccessiblePaths=-%s/backups' % root, 'InaccessiblePaths=-%s/site.env' % root, 'BindPaths=%s/shared' % root]
    props += [
        'MemoryMax=%dM' % (memory_mb or conf('NM_SITES_MEMORY_MAX_MB', 192)),
        'MemorySwapMax=64M',
        'CPUQuota=%d%%' % (cpu or conf('NM_SITES_CPU_QUOTA', 40)),
        'TasksMax=48', 'LimitNOFILE=1024', 'LimitCORE=0', 'Nice=5', 'IOWeight=50',
    ]
    for path in extra_rw:
        props.append('BindPaths=%s' % path)
    return props


def public_ip():
    return str(conf('NM_SITES_PUBLIC_IP', '87.107.160.17'))


def _env_props(key, release_path, extra=None):
    env = {'DJANGO_SETTINGS_MODULE': 'config.settings_live', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
           'PYTHONPATH': '%s:%s/.pylib' % (release_path, release_path), 'HOME': '/tmp', 'LANG': 'C.UTF-8'}
    env.update(extra or {})
    return env


def sandbox_run(key, argv, release=None, rw_release=False, stdin=None, timeout=300, check=False, env=None, text=True,
                memory_mb=None, cpu=None):
    """یک فرمان داخلِ همان جعبهٔ سرویس (کدِ سایت هرگز بیرون از این اجرا نمی‌شود). ⇒ (کد، خروجی)."""
    root = site_root(key)
    cwd = os.path.join(root, 'releases', check_rid(release)) if release else os.path.join(root, 'shared')
    extra_rw = [cwd] if (release and rw_release) else []
    props = sandbox_props(key, extra_rw, memory_mb=memory_mb or 320, cpu=cpu or 80) + \
        ['RuntimeMaxSec=%d' % timeout, 'WorkingDirectory=%s' % cwd]
    cmd = ['systemd-run', '--quiet', '--wait', '--pipe', '--collect', '--service-type=exec',
           '--unit=%s-job-%s' % (unit_of(key), secrets.token_hex(4))]
    for p in props:
        cmd += ['-p', p]
    if os.path.exists(os.path.join(root, 'site.env')):
        cmd += ['-p', 'EnvironmentFile=%s/site.env' % root]
    for k, v in _env_props(key, cwd, env).items():
        cmd += ['-E', '%s=%s' % (k, v)]
    cmd += ['--'] + list(argv)
    proc_env = {'PATH': PATH, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 30, env=proc_env, input=stdin,
                           stdin=None if stdin is not None else subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        if check:
            raise SysError('sandbox: %s' % exc)
        return 1, '' if text else b''
    if check and p.returncode != 0:
        raise SysError('sandbox %s failed (%d): %s' % (argv[0], p.returncode, (p.stdout + p.stderr).decode('utf-8', 'replace')[-1800:]))
    if not text:
        return p.returncode, p.stdout
    return p.returncode, (p.stdout + p.stderr).decode('utf-8', 'replace')


def manage(key, args, release, **kw):
    return sandbox_run(key, [runtime_python(), 'manage.py'] + list(args), release=release, **kw)


# ─────────────────────────────── نسخه‌ها
def release_path(key, rid):
    return os.path.join(site_root(key), 'releases', check_rid(rid))


def open_release_for_build(key, rid):
    """پوشهٔ ساخت را موقتاً به کاربرِ سایت می‌دهد (تا collectstatic و makemigrations داخلِ جعبه بنویسند)."""
    uid, gid = _ids(key)
    _chown_tree(release_path(key, rid), uid, gid)


def seal_release(key, rid):
    """بعدِ ساخت: همه چیز مالِ root و فقط‌خواندنی. symlink هرچه کاشته شده پاک می‌شود."""
    top = release_path(key, rid)
    for dp, dn, fn in os.walk(top, followlinks=False):
        for name in list(dn) + fn:
            full = os.path.join(dp, name)
            if os.path.islink(full):
                os.remove(full)
                if name in dn:
                    dn.remove(name)
    _chown_tree(top, 0, 0)
    for dp, dn, fn in os.walk(top, followlinks=False):
        os.chmod(dp, 0o755)
        for name in fn:
            full = os.path.join(dp, name)
            os.chmod(full, 0o644 if not os.access(full, os.X_OK) else 0o755)


def _chown_tree(top, uid, gid):
    os.lchown(top, uid, gid)
    for dp, dn, fn in os.walk(top, followlinks=False):
        for name in dn + fn:
            os.lchown(os.path.join(dp, name), uid, gid)


def current_release(key):
    try:
        return os.path.basename(os.readlink(os.path.join(site_root(key), 'current')))
    except OSError:
        return ''


def swap_current(key, rid):
    """جابه‌جاییِ اتمی. nginx فایل‌های ایستا را از همین لینک می‌خواند."""
    root = site_root(key)
    release_path(key, rid)
    tmp = os.path.join(root, '.current-%s' % secrets.token_hex(4))
    os.symlink(os.path.join('releases', rid), tmp)
    os.replace(tmp, os.path.join(root, 'current'))


def remove_release(key, rid):
    if rid == current_release(key):
        raise SysError('refusing to delete the current release')
    shutil.rmtree(release_path(key, rid), ignore_errors=True)


def list_releases(key):
    try:
        return sorted(x for x in os.listdir(os.path.join(site_root(key), 'releases')) if RID_RE.match(x))
    except OSError:
        return []


def run_tar_create(path):
    p = subprocess.run(['tar', '-c', '-C', path, '.'], capture_output=True, timeout=300, env={'PATH': PATH})
    return p.returncode, p.stdout


# ─────────────────────────────── systemd
def _unit_text(key, local_port):
    root = site_root(key)
    env = _env_props(key, root + '/current')
    lines = ['# managed by the NMarketing publisher; do not edit', '[Unit]', 'Description=NMarketing published site %s' % key,
             'After=network.target', 'Requires=%s.socket' % unit_of(key), 'StartLimitIntervalSec=120', 'StartLimitBurst=6', '',
             '[Service]', 'Type=exec', 'WorkingDirectory=%s/current' % root, 'EnvironmentFile=%s/site.env' % root]
    lines += ['Environment=%s=%s' % (k, v) for k, v in env.items()]
    lines += ['ExecStart=%s -m gunicorn config.wsgi:application --chdir %s/current --workers 1 --threads 3 --worker-tmp-dir /tmp '
              '--timeout 60 --graceful-timeout 20 --max-requests 5000 --max-requests-jitter 500 --no-control-socket --error-logfile -'
              % (runtime_python(), root),
              'Restart=always', 'RestartSec=3', 'TimeoutStopSec=25', 'KillMode=mixed', 'SyslogIdentifier=%s' % unit_of(key)]
    lines += sandbox_props(key)
    lines += ['', '[Install]', 'WantedBy=multi-user.target', '']
    return '\n'.join(lines)


def _socket_text(key, local_port):
    return '\n'.join(['# managed by the NMarketing publisher; do not edit', '[Unit]', 'Description=Socket of published site %s' % key, '',
                      '[Socket]', 'ListenStream=127.0.0.1:%d' % check_port(local_port), 'FreeBind=no', 'NoDelay=yes', 'Backlog=128', '',
                      '[Install]', 'WantedBy=sockets.target', ''])


def install_unit(key, local_port):
    name = unit_of(key)
    _atomic_write(os.path.join(unit_dir(), name + '.service'), _unit_text(key, local_port))
    _atomic_write(os.path.join(unit_dir(), name + '.socket'), _socket_text(key, local_port))
    run(['systemctl', 'daemon-reload'])


def unit_start(key):
    name = unit_of(key)
    run(['systemctl', 'reset-failed', name + '.service', name + '.socket'], check=False)
    run(['systemctl', 'enable', '--now', name + '.socket'])
    run(['systemctl', 'enable', '--now', name + '.service'])


def unit_restart(key):
    name = unit_of(key)
    run(['systemctl', 'reset-failed', name + '.service'], check=False)
    run(['systemctl', 'restart', name + '.service'], timeout=60)


def unit_stop(key):
    name = unit_of(key)
    run(['systemctl', 'disable', '--now', name + '.service', name + '.socket'], check=False, timeout=60)


def unit_remove(key):
    name = unit_of(key)
    unit_stop(key)
    for ext in ('.service', '.socket'):
        try:
            os.remove(os.path.join(unit_dir(), name + ext))
        except OSError:
            pass
    run(['systemctl', 'daemon-reload'], check=False)
    run(['systemctl', 'reset-failed', name + '.service', name + '.socket'], check=False)


def unit_active(key):
    code, out = run(['systemctl', 'is-active', unit_of(key) + '.service'], check=False)
    return out.strip() or 'unknown'


def unit_exists(key):
    return os.path.exists(os.path.join(unit_dir(), unit_of(key) + '.service'))


def unit_restarts(key):
    """چند بار از آخرین reset-failed کرش کرده."""
    code, out = run(['systemctl', 'show', '-p', 'NRestarts', '--value', unit_of(key) + '.service'], check=False, timeout=20)
    try:
        return int(out.strip())
    except ValueError:
        return 0


def unit_memory_mb(key):
    code, out = run(['systemctl', 'show', '-p', 'MemoryCurrent', '--value', unit_of(key) + '.service'], check=False)
    try:
        return round(int(out.strip()) / 1048576, 1)
    except ValueError:
        return None


def journal_tail(key, lines=40):
    code, out = run(['journalctl', '-u', unit_of(key) + '.service', '-n', str(int(lines)), '--no-pager', '-o', 'short-iso'], check=False, timeout=30)
    return out


# ─────────────────────────────── nginx
def nginx_test():
    return run(['nginx', '-t'], check=False, timeout=60)


def _nginx_reload():
    run(['nginx', '-s', 'reload'], timeout=60)


def write_vhost(key, text):
    """نوشتن + nginx -t + reload؛ اگر رد شد فایلِ قبلی برمی‌گردد و nginx هیچ‌وقت کانفیگِ خراب نمی‌بیند."""
    path = vhost_path(key)
    if not text.startswith('# ' + PREFIX):
        raise SysError('vhost text without our marker')
    with _lock('nginx'):
        code, out = nginx_test()
        if code != 0:
            raise SysError('nginx was already failing its test; nothing changed: %s' % out[-800:])
        old = None
        if os.path.exists(path):
            with open(path, encoding='utf-8') as fh:
                old = fh.read()
        _atomic_write(path, text)
        code, out = nginx_test()
        if code != 0:
            _restore(path, old)
            raise SysError('nginx rejected the new config; restored: %s' % out[-800:])
        try:
            _nginx_reload()
        except SysError:
            _restore(path, old)
            raise


def _restore(path, old):
    if old is None:
        try:
            os.remove(path)
        except OSError:
            pass
    else:
        _atomic_write(path, old)


def remove_vhost(key):
    path = vhost_path(key)
    if not os.path.exists(path):
        return False
    with _lock('nginx'):
        with open(path, encoding='utf-8') as fh:
            old = fh.read()
        os.remove(path)
        code, out = nginx_test()
        if code != 0:
            _restore(path, old)
            raise SysError('nginx failed after removing the vhost; restored: %s' % out[-800:])
        _nginx_reload()
    return True


def vhost_exists(key):
    return os.path.exists(vhost_path(key))


def foreign_server_names():
    """نام‌های سایت‌های دیگرِ این سرور (هر vhost که پیشوندِ ما را ندارد) + سایت‌های منتشرشدهٔ دیگر."""
    own, foreign = {}, set()
    for name in os.listdir(vhost_dir()):
        path = os.path.join(vhost_dir(), name)
        if not name.endswith('.conf') or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
        except OSError:
            continue
        names = set()
        for m in re.finditer(r'server_name\s+([^;]+);', text):
            names.update(x.strip().lower() for x in m.group(1).split())
        names = {n for n in names if '.' in n and not n.startswith(('_', '~'))}
        if name.startswith(PREFIX):
            own[name[len(PREFIX):-len('.conf')]] = names
        else:
            foreign |= names
    return foreign, own


# ─────────────────────────────── گواهی
def certbot_issue(key, names, staging=False):
    """⇒ (ok، متنِ certbot). با webroot، پس تمدیدِ خودکارِ certbot.timer هم همین راه را می‌رود."""
    for n in names:
        check_domain(n)
    cmd = ['certbot', 'certonly', '--webroot', '-w', webroot(), '--cert-name', lineage_of(key), '--non-interactive',
           '--agree-tos', '--keep-until-expiring', '--expand']
    if staging:
        cmd += ['--staging', '--register-unsafely-without-email']
    for n in names:
        cmd += ['-d', n]
    code, out = run(cmd, timeout=280, check=False)
    return code == 0, out


def certbot_delete(key):
    if os.path.exists('/etc/letsencrypt/renewal/%s.conf' % lineage_of(key)):
        run(['certbot', 'delete', '--cert-name', lineage_of(key), '--non-interactive'], check=False, timeout=120)


def cert_paths(key):
    live = '/etc/letsencrypt/live/%s' % lineage_of(key)
    return live + '/fullchain.pem', live + '/privkey.pem'


def cert_enddate(key):
    code, out = run(['openssl', 'x509', '-noout', '-enddate', '-in', cert_paths(key)[0]], check=False, timeout=20)
    return out.split('=', 1)[1].strip() if code == 0 and '=' in out else ''


def renew_dry_run(key):
    return run(['certbot', 'renew', '--no-random-sleep-on-renew', '--dry-run', '--cert-name', lineage_of(key), '--non-interactive'], check=False, timeout=280)


def dig_a(name, rtype='A'):
    """رکوردها از چند DNS عمومی؛ اگر این‌ها در دسترس نبودند DNS ِ خودِ سرور."""
    found = []
    for server in ('@1.1.1.1', '@8.8.8.8'):
        code, out = run(['dig', '+short', '+time=3', '+tries=1', rtype, name, server], check=False, timeout=12)
        if code == 0:
            for line in out.split():
                if (rtype == 'A' and re.match(r'^\d+\.\d+\.\d+\.\d+$', line)) or (rtype == 'AAAA' and ':' in line):
                    if line not in found:
                        found.append(line)
    return found


# ─────────────────────────────── ظرفیت
def disk_free_mb():
    return shutil.disk_usage(sites_root() if os.path.isdir(sites_root()) else '/').free // 1048576


def mem_available_mb():
    with open('/proc/meminfo') as fh:
        for line in fh:
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) // 1024
    return 0


def port_in_use(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', check_port(port))) == 0


def dir_size_mb(key):
    code, out = run(['du', '-sm', '--one-file-system', '-P', site_root(key)], check=False, timeout=60)
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return None


# ─────────────────────────────── حذفِ کامل (فقط با درخواستِ صریح)
def purge(key):
    if unit_exists(key) or vhost_exists(key):
        raise SysError('still published')
    shutil.rmtree(site_root(key), ignore_errors=True)
    try:
        os.remove('/www/wwwlogs/%s%s.error.log' % (PREFIX, check_key(key)))
    except OSError:
        pass
    run(['userdel', user_of(key)], check=False)
    run(['groupdel', user_of(key)], check=False)
