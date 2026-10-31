# -*- coding: utf-8 -*-
"""انتشارِ واقعیِ سایت روی اینترنت: نسخه‌سازی، مهاجرت، جابه‌جاییِ اتمی، آزمایشِ سلامت، بازگشتِ خودکار.

ساختارِ هر سایت (زیرِ NM_SITES_ROOT/<key>):
    releases/<rid>/      کد؛ مالِ root و فقط‌خواندنی برای سایت
    current -> releases/<rid>
    shared/db/db.sqlite3 و shared/media/   دادهٔ سایت؛ در انتشارِ بعدی دست نمی‌خورد
    backups/             پشتیبان‌های دیتابیس؛ فقط root
    site.env             رازِ سایت؛ فقط root (systemd به فرایند می‌دهد)

هیچ‌کدام از کدهای پروژه (که می‌تواند ساختهٔ AI باشد) بیرون از sandbox ِ sysops اجرا نمی‌شود؛ حتی check و makemigrations.
"""
import base64
import gzip
import http.client
import json
import logging
import os
import re
import secrets
import shutil
import time

from django.conf import settings
from django.utils import timezone

from apps.code_generation.generator import GenerationError, ProjectGenerator
from apps.code_generation import vcs
from apps.projects.models import PublishedSite, SiteJob, SiteRelease
from . import domains, sysops

logger = logging.getLogger(__name__)

KEEP_RELEASES = 3
KEEP_PUBLISH_BACKUPS = 5
KEEP_DAILY_BACKUPS = 7
HEALTH_SECONDS = 30
COPY_SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'media', 'staticfiles', 'node_modules', 'scripts', '.pylib'}
COPY_SKIP_FILES = {'db.sqlite3', 'run.bat', 'run.sh', '.env', '.env.example', '.admin-password.txt', '.gitignore'}


class HostingError(Exception):
    """شکستی که متنش به مالک نشان داده می‌شود؛ technical فقط برای باز کردنِ «جزئیات»."""

    def __init__(self, message, technical=''):
        super().__init__(message)
        self.message = message
        self.technical = str(technical or '')[-3000:]


def conf(name, default):
    return getattr(settings, name, default)


# ─────────────────────────────── متن‌های ثابتِ داخلِ نسخه
SETTINGS_LIVE = '''# -*- coding: utf-8 -*-
"""تنظیماتِ سایتِ منتشرشده؛ ساختهٔ انتشار، فقط داخلِ همین نسخه (نه در ZIP و پیش‌نمایش)."""
import os

from .settings import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = os.environ['NM_SECRET_KEY']
ALLOWED_HOSTS = [x for x in os.environ.get('NM_ALLOWED_HOSTS', '').split(',') if x]
CSRF_TRUSTED_ORIGINS = [x for x in os.environ.get('NM_CSRF_ORIGINS', '').split(',') if x]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ['NM_DB_PATH'], 'OPTIONS': {'timeout': 20}}}
MEDIA_ROOT = os.environ['NM_MEDIA_ROOT']
STATIC_ROOT = BASE_DIR / 'staticfiles'  # noqa: F405
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if os.environ.get('NM_HTTPS') == '1':
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'handlers': {'console': {'class': 'logging.StreamHandler'}},
           'loggers': {'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False}}}
'''

ERROR_PAGE = '''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%(title)s</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:Tahoma,sans-serif;background:#f6f7fb;color:#222;text-align:center;padding:24px}h1{font-size:1.4rem;margin:0 0 12px}a{color:#2f6df6}</style></head>
<body><main><h1>%(title)s</h1><p>%(text)s</p>%(link)s</main></body></html>
'''

DOWN_PAGE = ERROR_PAGE % {'title': 'سایت موقتاً در دسترس نیست', 'text': 'لطفاً چند دقیقهٔ دیگر دوباره سر بزن.', 'link': ''}

ADMIN_SCRIPT = '''
import sys
from django.contrib.auth import get_user_model
U = get_user_model(); f = U.USERNAME_FIELD
pw = sys.stdin.read().strip()
reset = %(reset)r
def guess(k):
    k = k.lower()
    return 'admin@site.local' if 'mail' in k else ('09000000000' if ('phone' in k or 'mobile' in k) else 'admin')
u = U.objects.filter(**{f: guess(f)}).first()
made = False
if u is None:
    extra = {k: guess(k) for k in getattr(U, 'REQUIRED_FIELDS', [])}
    extra[f] = guess(f)
    u = U.objects.create_superuser(password=pw, **extra); made = True
elif reset:
    u.set_password(pw); u.is_staff = True; u.is_superuser = True; u.is_active = True; u.save()
print('NM_ADMIN=' + str(getattr(u, f)) + ' made=' + str(made or reset))
'''

SMOKE_SCRIPT = '''
import json, sys
from django.conf import settings
from django.test import Client
c = Client(raise_request_exception=False, HTTP_HOST=settings.ALLOWED_HOSTS[0])
out = {}
for path in %(paths)r:
    try:
        out[path] = c.get(path).status_code
    except Exception as exc:
        out[path] = 'خطا: %%s' %% exc
print('NM_SMOKE=' + json.dumps(out))
'''

# فقط کتابخانهٔ استاندارد؛ با پایتونِ محیطِ مشترک و -I داخلِ جعبه اجرا می‌شوند (نه کدِ سایت)
DB_DUMP = '''
import os, sqlite3, sys, tempfile
path = os.environ['NM_DB_PATH']
if not os.path.exists(path):
    sys.exit(3)
fd, tmp = tempfile.mkstemp(dir='/tmp'); os.close(fd)
a = sqlite3.connect('file:%s?mode=ro' % path, uri=True, timeout=20); b = sqlite3.connect(tmp)
a.backup(b); b.close(); a.close()
sys.stdout.buffer.write(open(tmp, 'rb').read())
'''

DB_LOAD = '''
import os, sqlite3, sys, tempfile
path = os.environ['NM_DB_PATH']
fd, tmp = tempfile.mkstemp(dir='/tmp')
with os.fdopen(fd, 'wb') as fh:
    fh.write(sys.stdin.buffer.read())
a = sqlite3.connect(tmp); b = sqlite3.connect(path, timeout=20)
a.backup(b); b.close(); a.close()
'''

SEED_CLEAN = '''
from django.apps import apps
from django.contrib.auth import get_user_model
for model in apps.get_models():
    label = model._meta.app_label
    if label in %(private)r or model._meta.db_table in ('django_session', 'django_admin_log'):
        model.objects.all().delete()
get_user_model().objects.all().delete()
print('NM_SEED_CLEAN=1')
'''

MESSAGES_READ = '''
import json, os, sqlite3, sys
args = json.loads(sys.argv[1])
path = os.environ['NM_DB_PATH']
if not os.path.exists(path):
    print(json.dumps({'rows': [], 'total': 0, 'unread': 0})); sys.exit(0)
c = sqlite3.connect(path, timeout=20)
c.row_factory = sqlite3.Row
try:
    if args.get('mark') == 'all':
        c.execute('UPDATE site_forms_formmessage SET is_read=1 WHERE is_read=0'); c.commit()
    elif args.get('mark'):
        c.execute('UPDATE site_forms_formmessage SET is_read=? WHERE id=?', (1 if args.get('read', True) else 0, int(args['mark']))); c.commit()
    total = c.execute('SELECT count(*) FROM site_forms_formmessage').fetchone()[0]
    unread = c.execute('SELECT count(*) FROM site_forms_formmessage WHERE is_read=0').fetchone()[0]
    rows = [] if args.get('count_only') else [dict(r) for r in c.execute(
        'SELECT id, form_title, page, content, data, is_read, created_at FROM site_forms_formmessage ORDER BY id DESC LIMIT ? OFFSET ?',
        (int(args.get('limit', 30)), int(args.get('offset', 0))))]
except sqlite3.OperationalError:
    total, unread, rows = 0, 0, []
print(json.dumps({'rows': rows, 'total': total, 'unread': unread}, ensure_ascii=True))
'''


# ─────────────────────────────── vhost
def _locations(key, local_port):
    root = sysops.site_root(key)
    return '''    client_max_body_size 50m;
    error_page 502 503 504 /__nm_down.html;
    location = /__nm_down.html { internal; root %(common)s; }
    location ^~ /static/ {
        alias %(root)s/current/staticfiles/;
        add_header Cache-Control "public, no-cache";
        add_header X-Content-Type-Options nosniff;
    }
    location ^~ /media/ {
        alias %(root)s/shared/media/;
        disable_symlinks on;
        expires 7d;
        add_header X-Content-Type-Options nosniff;
        add_header Content-Security-Policy "sandbox";
    }
    location / {
        proxy_pass http://127.0.0.1:%(local)d;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 8s;
        proxy_read_timeout 70s;
    }
''' % {'root': root, 'common': os.path.join(sysops.sites_root(), '_common'), 'local': sysops.check_port(local_port)}


def render_vhost(site):
    """تنها متنی که nginx از ما می‌بیند؛ فقط کلید، پورت و دامنهٔ سنجیده‌شده در آن است."""
    key = sysops.check_key(site.key)
    port = sysops.check_port(site.port)
    locs = _locations(key, site.local_port)
    log = '/www/wwwlogs/%s%s.error.log' % (sysops.PREFIX, key)
    head = '# %s%s; managed by the NMarketing publisher; do not edit\n' % (sysops.PREFIX, key)
    https = site.domain_state == PublishedSite.DOMAIN_ACTIVE and site.domain
    names = [sysops.check_domain(n) for n in site.domain_names] if site.domain and site.domain_state in (PublishedSite.DOMAIN_HTTP, PublishedSite.DOMAIN_ACTIVE, PublishedSite.DOMAIN_ISSUING) else []
    out = [head]
    # نشانیِ پورت‌دار: وقتی دامنه با قفل فعال است همان‌جا می‌فرستد تا ورود به مدیریت رمزنشده نماند
    body = ('    location / { return 301 https://%s$request_uri; }\n' % names[0]) if https else locs
    out.append('server {\n    listen %d;\n    server_name _;\n    server_tokens off;\n    access_log off;\n    error_log %s warn;\n%s}\n' % (port, log, body))
    acme = '    location ^~ /.well-known/acme-challenge/ { root %s; default_type "text/plain"; allow all; }\n' % sysops.webroot()
    if names and not https:
        out.append('server {\n    listen 80;\n    server_name %s;\n    server_tokens off;\n    access_log off;\n    error_log %s warn;\n%s%s}\n'
                   % (' '.join(names), log, acme, locs))
    if https:
        cert, priv = sysops.cert_paths(key)
        tls = '    ssl_certificate %s;\n    ssl_certificate_key %s;\n' % (cert, priv)
        out.append('server {\n    listen 80;\n    server_name %s;\n    server_tokens off;\n    access_log off;\n    error_log %s warn;\n%s    location / { return 301 https://%s$request_uri; }\n}\n'
                   % (' '.join(names), log, acme, names[0]))
        if len(names) > 1:
            out.append('server {\n    listen 443 ssl;\n    http2 on;\n    server_name %s;\n    server_tokens off;\n    access_log off;\n    error_log %s warn;\n%s    return 301 https://%s$request_uri;\n}\n'
                       % (' '.join(names[1:]), log, tls, names[0]))
        out.append('server {\n    listen 443 ssl;\n    http2 on;\n    server_name %s;\n    server_tokens off;\n    access_log off;\n    error_log %s warn;\n%s%s}\n'
                   % (names[0], log, tls, locs))
    return '\n'.join(out)


# ─────────────────────────────── کمک‌ها
def _key_for(project):
    slug = project.slug or ''
    return slug if sysops.KEY_RE.match(slug) else 'p%d' % project.pk


def public_address(site):
    if site.domain and site.domain_state == PublishedSite.DOMAIN_ACTIVE:
        return 'https://%s/' % site.domain
    return 'http://%s:%d/' % (sysops.public_ip(), site.port) if site.port else ''


def port_range():
    return tuple(conf('NM_SITES_PORT_RANGE', (8621, 8650)))


def _used_ports():
    return set(PublishedSite.objects.exclude(port=None).values_list('port', flat=True))


def _pick_ports():
    lo, hi = port_range()
    used = _used_ports()
    # از بالای بازه؛ پیش‌نمایش از پایین برمی‌دارد. پورتی که چیزی رویش گوش می‌دهد کنار گذاشته می‌شود.
    for port in range(hi, lo - 1, -1):
        local = port + 10000
        if port not in used and not sysops.port_in_use(port) and not sysops.port_in_use(local):
            return port, local
    raise HostingError('همهٔ نشانی‌های این سرور پر است. اول یک سایتِ دیگر را از اینترنت بردار.')


def get_site(project):
    site = PublishedSite.objects.filter(project=project).first()
    if site is None:
        site = PublishedSite.objects.create(project=project, key=_key_for(project))
    return site


def capacity():
    max_sites = int(conf('NM_SITES_MAX', 10))
    active = PublishedSite.objects.exclude(port=None).count()
    return {'sites': active, 'max_sites': max_sites, 'disk_free_mb': sysops.disk_free_mb(), 'mem_available_mb': sysops.mem_available_mb(),
            'min_disk_mb': int(conf('NM_SITES_MIN_DISK_MB', 1500)), 'min_mem_mb': int(conf('NM_SITES_MIN_MEM_MB', 500))}


def guard_capacity(site):
    """پیش از هر انتشار. RAM فقط برای سایتِ تازه مهم است، چون بازانتشار فرایندِ تازه‌ای اضافه نمی‌کند."""
    c = capacity()
    if c['disk_free_mb'] < c['min_disk_mb']:
        raise HostingError('فضای این سرور کم است (%d مگابایت خالی مانده؛ حداقل %d لازم است) و برای این‌که سایت‌های دیگرِ روی سرور آسیب نبینند انتشار انجام نشد. نسخهٔ فعلیِ سایت سرِ جایش است.'
                           % (c['disk_free_mb'], c['min_disk_mb']))
    if not site.port:
        if c['sites'] >= c['max_sites']:
            raise HostingError('این سرور به سقفِ %d سایت رسیده. اول یک سایتِ دیگر را از اینترنت بردار.' % c['max_sites'])
        if c['mem_available_mb'] < c['min_mem_mb']:
            raise HostingError('حافظهٔ آزادِ این سرور کم است (%d مگابایت؛ حداقل %d لازم است) و یک سایتِ تازه می‌تواند بقیه را کند کند. فعلاً انتشار انجام نشد.'
                               % (c['mem_available_mb'], c['min_mem_mb']))


def _env_values(site, secret=None):
    root = sysops.site_root(site.key)
    hosts = [sysops.public_ip(), '127.0.0.1', 'localhost'] + site.domain_names
    origins = ['http://%s:%d' % (sysops.public_ip(), site.port)] if site.port else []
    https = site.domain_state == PublishedSite.DOMAIN_ACTIVE
    for n in site.domain_names:
        origins += ['https://%s' % n, 'http://%s' % n]
    old = sysops.read_env(site.key)
    key = secret or old.get('NM_SECRET_KEY') or sysops.new_secret()
    return {'NM_SECRET_KEY': key, 'DJANGO_SECRET_KEY': key, 'DJANGO_DEBUG': 'False', 'NM_ALLOWED_HOSTS': ','.join(hosts),
            'DJANGO_ALLOWED_HOSTS': ','.join(hosts), 'NM_CSRF_ORIGINS': ','.join(origins), 'NM_DB_PATH': root + '/shared/db/db.sqlite3',
            'NM_MEDIA_ROOT': root + '/shared/media', 'NM_HTTPS': '1' if https else '0'}


def http_status(port, path='/', host=None, timeout=10):
    host = host or sysops.public_ip()
    try:
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
        c.request('GET', path, headers={'Host': host, 'User-Agent': 'nm-health'})
        code = c.getresponse().status
        c.close()
        return code
    except (OSError, http.client.HTTPException):
        return 0


def _wait_status(port, path, seconds=12):
    """nginx -s reload ناهمگام است؛ پورتِ تازه چند صدم ثانیه بعد باز می‌شود."""
    deadline = time.monotonic() + seconds
    code = 0
    while time.monotonic() < deadline:
        code = http_status(port, path, timeout=8)
        if code == 200:
            return code
        time.sleep(0.5)
    return code


def wait_healthy(site, seconds=HEALTH_SECONDS):
    """سلامت از راهِ سوکتِ سرویس: صفحهٔ اصلی خطای ۵۰۰ ندهد و صفحهٔ ورودِ مدیریت بالا بیاید.
    اگر سرویس کرش کند منتظرِ پایانِ مهلت نمی‌مانیم: هر ثانیه افتادنِ سایت خرج دارد."""
    deadline = time.monotonic() + seconds
    last = 0
    while time.monotonic() < deadline:
        last = http_status(site.local_port, '/admin/login/', timeout=8)
        if last == 200:
            home = http_status(site.local_port, '/', timeout=8)
            if 0 < home < 500:
                return True, ''
            last = 'home %s' % home
        if sysops.unit_restarts(site.key) > 0:
            return False, 'service crashed; last=%s' % last
        time.sleep(1)
    return False, 'health=%s' % last


# ─────────────────────────────── گام‌های کار
class Steps:
    """پیشرفتِ قابلِ دیدن در پنل."""

    def __init__(self, job, labels):
        self.job = job
        self.rows = [{'label': x, 'state': 'wait'} for x in labels]
        self.i = -1
        self._save()

    def _save(self):
        self.job.steps = self.rows
        self.job.save(update_fields=['steps', 'updated_at'])

    def next(self):
        if self.i >= 0:
            self.rows[self.i]['state'] = 'done'
        self.i += 1
        self.rows[self.i]['state'] = 'run'
        self._save()

    def fail(self):
        if 0 <= self.i < len(self.rows):
            self.rows[self.i]['state'] = 'fail'
        self._save()

    def done(self):
        if self.i >= 0:
            self.rows[self.i]['state'] = 'done'
        self._save()


def _copy_release(project, dest):
    src = str(project.path)
    for dp, dn, fn in os.walk(src, followlinks=False):
        dn[:] = [d for d in dn if d not in COPY_SKIP_DIRS and not os.path.islink(os.path.join(dp, d))]
        rel = os.path.relpath(dp, src)
        target = os.path.normpath(os.path.join(dest, rel))
        os.makedirs(target, exist_ok=True)
        for name in fn:
            full = os.path.join(dp, name)
            if (name in COPY_SKIP_FILES or name.endswith(('.pyc', '.sqlite3', '.log')) or name.startswith(('.preview', '.studio-'))
                    or os.path.islink(full)):
                continue
            shutil.copyfile(full, os.path.join(target, name))


def _write_release_extras(path):
    with open(os.path.join(path, 'config', 'settings_live.py'), 'w', encoding='utf-8') as fh:
        fh.write(SETTINGS_LIVE)
    tpl = os.path.join(path, 'templates')
    os.makedirs(tpl, exist_ok=True)
    pages = {'404.html': ('این صفحه پیدا نشد', 'شاید نشانی را اشتباه زده باشی.'),
             '500.html': ('مشکلی پیش آمد', 'خطایی در سایت رخ داد. لطفاً چند دقیقهٔ دیگر دوباره سر بزن.')}
    for name, (title, text) in pages.items():
        target = os.path.join(tpl, name)
        if not os.path.exists(target):
            with open(target, 'w', encoding='utf-8') as fh:
                fh.write(ERROR_PAGE % {'title': title, 'text': text, 'link': '<p><a href="/">بازگشت به صفحهٔ اصلی</a></p>'})


def _migration_files(path):
    """{app: آخرین مهاجرت} و فهرستِ همهٔ پرونده‌های مهاجرتِ یک نسخه."""
    out = {}
    apps_dir = os.path.join(path, 'apps')
    if not os.path.isdir(apps_dir):
        return out
    for app in sorted(os.listdir(apps_dir)):
        mig = os.path.join(apps_dir, app, 'migrations')
        if os.path.isdir(mig):
            out[app] = sorted(n[:-3] for n in os.listdir(mig) if re.match(r'^\d{4}_\w+\.py$', n))
    return out


def _copy_migrations_back(project, release, before):
    """مهاجرتی که داخلِ جعبه ساخته شد به پوشهٔ پروژه هم برمی‌گردد (فقط پروندهٔ ساده با نامِ مهاجرت)."""
    after = _migration_files(release)
    new = 0
    for app, names in after.items():
        for name in names:
            if name in before.get(app, []):
                continue
            src = os.path.join(release, 'apps', app, 'migrations', name + '.py')
            if os.path.islink(src) or not os.path.isfile(src) or os.path.getsize(src) > 2000000:
                continue
            dest_dir = os.path.join(str(project.path), 'apps', app, 'migrations')
            os.makedirs(dest_dir, exist_ok=True)
            with open(src, 'rb') as a, open(os.path.join(dest_dir, name + '.py'), 'wb') as b:
                b.write(a.read())
            new += 1
    return new


def _extra_requirements(project, site, rid):
    reqs = list(project.extra_requirement_list)
    if not reqs:
        return
    for r in reqs:
        if not re.match(r'^[A-Za-z0-9_.\-\[\]]+([=<>!~]=?[A-Za-z0-9_.*\-]+(,[=<>!~]=?[A-Za-z0-9_.*\-]+)*)?$', r):
            raise HostingError('بستهٔ اضافهٔ «%s» در تنظیماتِ پروژه درست نوشته نشده.' % r)
    code, out = sysops.sandbox_run(site.key, [sysops.runtime_python(), '-m', 'pip', 'install', '--no-cache-dir', '--only-binary=:all:',
                                              '--target', '.pylib', '--disable-pip-version-check'] + reqs,
                                   release=rid, rw_release=True, timeout=600, env={'PIP_CACHE_DIR': '/tmp/pip'})
    if code != 0:
        raise HostingError('بسته‌های اضافهٔ این سایت نصب نشدند. نسخهٔ فعلیِ سایت سرِ جایش است.', out)


def build_release(site, job_user=''):
    """کدِ تازه + check + مهاجرت‌سازی + collectstatic، همه داخلِ جعبه. ⇒ rid"""
    project = site.project
    try:
        ProjectGenerator(project).run()
    except GenerationError as exc:
        raise HostingError('ساختِ سایت خطا داد و چیزی روی اینترنت عوض نشد.', exc)
    vcs.commit(project, 'انتشار روی اینترنت')
    rid = timezone.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(2)
    path = sysops.release_path(site.key, rid)
    _copy_release(project, path)
    _write_release_extras(path)
    from apps.projects.builder import genhook
    genhook.persian_shop(path, project)
    before = _migration_files(path)
    sysops.open_release_for_build(site.key, rid)
    _extra_requirements(project, site, rid)
    for args, label in ((['check'], 'وارسیِ کد'), (['makemigrations', '--noinput'], 'به‌روزرسانیِ ساختارِ داده'),
                        (['collectstatic', '--noinput', '--verbosity', '0'], 'آماده‌سازیِ فایل‌ها')):
        code, out = sysops.manage(site.key, args, rid, rw_release=True, timeout=240)
        if code != 0:
            raise HostingError('نسخهٔ تازه در مرحلهٔ «%s» خطا داد و چیزی روی اینترنت عوض نشد. نسخهٔ فعلیِ سایت سرِ جایش است.' % label, out)
    sysops.sandbox_run(site.key, [sysops.runtime_python(), '-m', 'compileall', '-q', '.'], release=rid, rw_release=True, timeout=120)
    new = _copy_migrations_back(project, path, before)
    if new:
        vcs.commit(project, 'مهاجرت (انتشار)')
    sysops.seal_release(site.key, rid)
    return rid


# ─────────────────────────────── پشتیبان
def backup_db(site, label):
    """⇒ نامِ پرونده یا '' اگر هنوز دیتابیسی نیست. خواندن داخلِ جعبه، نگه‌داری بیرون از دسترسِ سایت."""
    code, data = sysops.sandbox_run(site.key, [sysops.runtime_python(), '-I', '-c', DB_DUMP], text=False, timeout=180)
    if code == 3 or (code != 0 and not data):
        if code != 3:
            raise HostingError('از داده‌های سایت پشتیبان گرفته نشد و برای اطمینان انتشار انجام نشد. نسخهٔ فعلی سرِ جایش است.', 'dump exit %s' % code)
        return ''
    if not data.startswith(b'SQLite format 3'):
        raise HostingError('پشتیبانِ داده‌های سایت سالم نبود و برای اطمینان انتشار انجام نشد. نسخهٔ فعلی سرِ جایش است.')
    folder = os.path.join(sysops.site_root(site.key), 'backups')
    name = '%s-%s.sqlite3.gz' % (label, timezone.now().strftime('%Y%m%d-%H%M%S'))
    with gzip.open(os.path.join(folder, name), 'wb', compresslevel=6) as fh:
        fh.write(data)
    os.chmod(os.path.join(folder, name), 0o600)
    return name


def restore_db(site, name):
    folder = os.path.join(sysops.site_root(site.key), 'backups')
    if not re.match(r'^[a-z]+-\d{8}-\d{6}\.sqlite3\.gz$', name or ''):
        raise HostingError('پروندهٔ پشتیبان معتبر نیست.')
    with gzip.open(os.path.join(folder, name), 'rb') as fh:
        data = fh.read()
    sysops.sandbox_run(site.key, [sysops.runtime_python(), '-I', '-c', DB_LOAD], stdin=data, timeout=180, check=True)


def list_backups(site):
    folder = os.path.join(sysops.site_root(site.key), 'backups')
    try:
        names = [n for n in os.listdir(folder) if n.endswith('.sqlite3.gz')]
    except OSError:
        return []
    return sorted(names, key=lambda n: n.split('-', 1)[1], reverse=True)


def prune_backups(site):
    folder = os.path.join(sysops.site_root(site.key), 'backups')
    for label, keep in (('publish', KEEP_PUBLISH_BACKUPS), ('daily', KEEP_DAILY_BACKUPS)):
        for name in [n for n in list_backups(site) if n.startswith(label + '-')][keep:]:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def _prune_releases(site):
    keep = {sysops.current_release(site.key)}
    for r in site.releases.filter(status=SiteRelease.OK).order_by('-created_at')[:KEEP_RELEASES]:
        keep.add(r.rid)
    for rid in sysops.list_releases(site.key):
        if rid not in keep:
            sysops.remove_release(site.key, rid)
            site.releases.filter(rid=rid).exclude(status=SiteRelease.OK).delete()
    site.releases.filter(status=SiteRelease.OK).exclude(rid__in=keep).delete()


def _seed_first_db(site):
    """اولین انتشار: محتوایی که در پیش‌نمایش ساخته شده (محصول، دسته…) همراهِ سایت می‌رود؛
    کاربرها، سفارش‌ها و پیام‌های آزمایشی نه. بعد از این دیتابیسِ زنده مالِ خودش است و هرگز بازنویسی نمی‌شود."""
    src = os.path.join(str(site.project.path), 'db.sqlite3')
    if os.path.islink(src) or not os.path.isfile(src):
        return False
    with open(src, 'rb') as fh:
        data = fh.read()
    sysops.sandbox_run(site.key, [sysops.runtime_python(), '-I', '-c', DB_LOAD], stdin=data, timeout=120, check=True)
    media = os.path.join(str(site.project.path), 'media')
    if os.path.isdir(media) and not os.path.islink(media):
        code, tar = sysops.run_tar_create(media)
        if code == 0 and tar:
            sysops.sandbox_run(site.key, ['/usr/bin/tar', '-x', '--no-same-owner', '--no-same-permissions', '-C', os.path.join(sysops.site_root(site.key), 'shared', 'media')],
                               stdin=tar, timeout=120)
    return True


def _migrations_pending(site, rid):
    code, _out = sysops.manage(site.key, ['migrate', '--check'], rid, timeout=120)
    return code != 0


def _smoke(site, rid):
    pages = ['/' + (p.slug + '/' if p.slug else '') for p in site.project.pages.all()]
    paths = list(dict.fromkeys(pages + ['/', '/admin/login/']))[:40]
    code, out = sysops.manage(site.key, ['shell', '-c', SMOKE_SCRIPT % {'paths': paths}], rid, timeout=180)
    m = re.search(r'NM_SMOKE=(\{.*\})', out)
    if code != 0 or not m:
        raise HostingError('نسخهٔ تازه بالا نیامد و چیزی روی اینترنت عوض نشد. نسخهٔ فعلیِ سایت سرِ جایش است.', out)
    results = json.loads(m.group(1))
    bad = [p for p, s in results.items() if not isinstance(s, int) or s >= 500]
    if bad:
        raise HostingError('صفحهٔ «%s» در نسخهٔ تازه خطا می‌دهد و چیزی روی اینترنت عوض نشد. نسخهٔ فعلیِ سایت سرِ جایش است.' % '، '.join(bad[:3]), out)
    # خودِ gunicorn هم پیش از جابه‌جایی برنامه را بار می‌کند؛ بیشترِ خرابی‌ها این‌جا پیدا می‌شوند و سایت حتی یک لحظه هم نمی‌افتد
    code, out = sysops.sandbox_run(site.key, [sysops.runtime_python(), '-m', 'gunicorn', '--check-config', 'config.wsgi:application'], release=rid, timeout=120)
    if code != 0:
        raise HostingError('نسخهٔ تازه بالا نیامد و چیزی روی اینترنت عوض نشد. نسخهٔ فعلیِ سایت سرِ جایش است.', out)
    return results


def ensure_admin(site, rid, reset=False):
    if site.admin_password and not reset:
        return False
    password = secrets.token_urlsafe(9)
    code, out = sysops.manage(site.key, ['shell', '-c', ADMIN_SCRIPT % {'reset': bool(reset)}], rid, stdin=password.encode() + b'\n', timeout=120)
    m = re.search(r'NM_ADMIN=(\S+) made=(True|False)', out)
    if code != 0 or not m:
        raise HostingError('کاربرِ مدیریتِ سایت ساخته نشد.', out)
    if m.group(2) == 'True':
        site.admin_user = m.group(1)
        site.admin_password = password
        site.save(update_fields=['admin_user', 'admin_password'])
    return True


def _prepare_host(site):
    sysops.ensure_runtime(['Django', 'Pillow', 'gunicorn'])
    sysops.ensure_common(DOWN_PAGE)
    sysops.ensure_user(site.key)
    sysops.ensure_dirs(site.key)
    if not site.port:
        site.port, site.local_port = _pick_ports()
        site.save(update_fields=['port', 'local_port'])
    sysops.write_env(site.key, _env_values(site))


def _first_install_cleanup(site):
    """اولین انتشار شکست خورد: چیزِ نیمه‌کاره نماند. داده‌ای هم هنوز نبوده که از دست برود."""
    for fn in (sysops.remove_vhost, sysops.unit_remove):
        try:
            fn(site.key)
        except sysops.SysError as exc:
            logger.warning('cleanup %s: %s', site.key, exc)
    try:
        os.remove(os.path.join(sysops.site_root(site.key), 'current'))
    except OSError:
        pass
    site.port = None
    site.local_port = None
    site.current_release = ''
    site.save(update_fields=['port', 'local_port', 'current_release'])


def publish(site, job):
    """کلِ انتشار. هر شکستی پیش از جابه‌جایی به سایتِ روشن دست نمی‌زند؛ بعد از جابه‌جایی برمی‌گردد."""
    project = site.project
    if project.is_imported:
        raise HostingError('پروژهٔ واردشده هنوز از این راه منتشر نمی‌شود (تنظیمات و دیتابیسِ خودش را دارد). می‌توانی ZIP را بگیری.')
    steps = Steps(job, ['بررسیِ فضای سرور', 'ساختنِ نسخهٔ تازه', 'پشتیبان از داده‌های سایت', 'به‌روزرسانیِ داده‌ها', 'آزمایشِ صفحه‌ها', 'جایگزینیِ نسخه و آزمایشِ نهایی'])
    first = not site.current_release
    prev = sysops.current_release(site.key) if site.key else ''
    migrated = False
    backup = ''
    swapped = False
    release = None
    fresh_db = False
    try:
        steps.next()
        guard_capacity(site)
        _prepare_host(site)
        steps.next()
        rid = build_release(site)
        release = SiteRelease.objects.create(site=site, rid=rid, status=SiteRelease.BUILDING, user=job.user, migrations=_migration_files(sysops.release_path(site.key, rid)))
        steps.next()
        db_exists = _db_exists(site)
        if not db_exists:
            fresh_db = True
            site.admin_user = ''
            site.admin_password = ''
            site.save(update_fields=['admin_user', 'admin_password'])
            _seed_first_db(site)
        else:
            backup = backup_db(site, 'publish')
        release.db_backup = backup
        release.save(update_fields=['db_backup'])
        steps.next()
        pending = _migrations_pending(site, rid)
        code, out = sysops.manage(site.key, ['migrate', '--noinput'], rid, timeout=280)
        migrated = pending
        if code != 0:
            raise HostingError('به‌روزرسانیِ داده‌ها خطا داد. داده‌ها به حالتِ قبل برگشتند و نسخهٔ فعلیِ سایت سرِ جایش است.', out)
        if not db_exists:
            sysops.manage(site.key, ['shell', '-c', SEED_CLEAN % {'private': ['site_forms', 'orders']}], rid, timeout=120)
        ensure_admin(site, rid)
        steps.next()
        _smoke(site, rid)
        steps.next()
        sysops.swap_current(site.key, rid)
        swapped = True
        if first or not sysops.unit_exists(site.key):
            sysops.install_unit(site.key, site.local_port)
            sysops.unit_start(site.key)
        else:
            sysops.install_unit(site.key, site.local_port)      # قالبِ سرویس هم همیشه به‌روز
            sysops.unit_start(site.key)
            sysops.unit_restart(site.key)
        ok, why = wait_healthy(site)
        if not ok:
            raise HostingError('نسخهٔ تازه روی سرور بالا نیامد و سایت خودکار به حالتِ قبل برگشت.', '%s\n%s' % (why, sysops.journal_tail(site.key, 25)))
        sysops.write_vhost(site.key, render_vhost(site))
        if not (site.domain and site.domain_state == PublishedSite.DOMAIN_ACTIVE):     # نشانیِ پورت‌دار آن موقع فقط می‌فرستد به دامنه
            for path, label in (('/admin/login/', 'نسخهٔ تازه'), ('/static/admin/css/base.css', 'فایل‌های نسخهٔ تازه')):
                code = _wait_status(site.port, path)
                if code != 200:
                    raise HostingError('%s از بیرون باز نشد و سایت به حالتِ قبل برگشت.' % label, '%s=%s' % (path, code))
        release.status = SiteRelease.OK
        release.save(update_fields=['status'])
        site.current_release = rid
        site.previous_release = prev if prev != rid else site.previous_release
        site.state = PublishedSite.LIVE
        site.last_publish_at = timezone.now()
        site.last_error = ''
        site.last_technical = ''
        site.save()
        steps.done()
        try:
            prune_backups(site)
            _prune_releases(site)
        except Exception as exc:  # noqa: BLE001 — انتشار موفق بود؛ نظافت بعداً هم می‌شود
            logger.warning('prune %s: %s', site.key, exc)
        return public_address(site)
    except HostingError as exc:
        steps.fail()
        _recover(site, prev, first, swapped, migrated, backup, release, exc, fresh_db)
        raise
    except (sysops.SysError, OSError) as exc:
        steps.fail()
        err = HostingError('انتشار کامل نشد؛ نسخهٔ فعلیِ سایت سرِ جایش است.', exc)
        _recover(site, prev, first, swapped, migrated, backup, release, err, fresh_db)
        raise err


# فایلِ خالی حساب نیست: همان makemigrations ِ مرحلهٔ ساخت با یک اتصال، db.sqlite3 ِ خالی می‌سازد
DB_HAS_DATA = '''
import os, sqlite3, sys
p = os.environ['NM_DB_PATH']
if not os.path.exists(p):
    sys.exit(3)
c = sqlite3.connect('file:%s?mode=ro' % p, uri=True, timeout=20)
sys.exit(0 if c.execute("select count(*) from sqlite_master where name='django_migrations'").fetchone()[0] else 3)
'''


def _db_exists(site):
    code, _ = sysops.sandbox_run(site.key, [sysops.runtime_python(), '-I', '-c', DB_HAS_DATA], timeout=60)
    return code == 0


def _drop_fresh_db(site):
    """دیتابیسی که همین انتشارِ شکست‌خورده ساخته بود: تا تلاشِ بعدی دوباره از پیش‌نمایش پاک‌سازی‌شده بیاید."""
    sysops.sandbox_run(site.key, [sysops.runtime_python(), '-I', '-c', 'import os\np=os.environ["NM_DB_PATH"]\nos.path.exists(p) and os.remove(p)'], timeout=60)
    site.admin_user = ''
    site.admin_password = ''
    site.save(update_fields=['admin_user', 'admin_password'])


def _recover(site, prev, first, swapped, migrated, backup, release, exc, fresh_db=False):
    """هر شکست: برگشت به آخرین حالتِ سالم. سایتی که بالا بود باید بالا بماند."""
    notes = []
    try:
        if swapped and prev:
            sysops.swap_current(site.key, prev)
        if migrated and backup:
            restore_needs_stop = sysops.unit_exists(site.key)
            if restore_needs_stop:
                sysops.run(['systemctl', 'stop', sysops.unit_of(site.key) + '.service'], check=False, timeout=60)
            restore_db(site, backup)
            notes.append('db restored')
        if prev and sysops.unit_exists(site.key):
            sysops.unit_start(site.key)
            if swapped:
                sysops.unit_restart(site.key)
            ok, why = wait_healthy(site)
            notes.append('previous healthy=%s %s' % (ok, why))
    except Exception as second:  # noqa: BLE001 — باید گزارش شود، نه این‌که خطای اول را بپوشاند
        logger.exception('recover %s', site.key)
        notes.append('recover failed: %s' % second)
    if first:
        _first_install_cleanup(site)
        site.state = PublishedSite.FAILED
    if fresh_db:
        try:
            _drop_fresh_db(site)
        except Exception as second:  # noqa: BLE001
            notes.append('drop fresh db: %s' % second)
    if release is not None:
        release.status = SiteRelease.FAILED
        release.note = exc.message[:300]
        release.save(update_fields=['status', 'note'])
        try:
            sysops.remove_release(site.key, release.rid)
        except sysops.SysError:
            pass
    site.last_error = exc.message
    site.last_technical = ('\n'.join(notes) + '\n' + exc.technical)[-3000:]
    site.save(update_fields=['last_error', 'last_technical', 'state'])


def rollback(site, job):
    """بازگشت به نسخهٔ قبلی. داده پاک نمی‌شود: اگر نسخهٔ تازه مهاجرت داشته، فقط همان مهاجرت‌ها برعکس می‌شوند
    و اگر برگشت‌پذیر نبودند، بازگشت انجام نمی‌شود."""
    steps = Steps(job, ['پشتیبان از داده‌های سایت', 'برگرداندنِ ساختارِ داده', 'جایگزینیِ نسخه و آزمایش'])
    current = sysops.current_release(site.key)
    target = site.previous_release
    if not target or target == current or not os.path.isdir(sysops.release_path(site.key, target)):
        raise HostingError('نسخهٔ قبلی‌ای برای برگشت نیست.')
    steps.next()
    backup = backup_db(site, 'publish')
    steps.next()
    cur_mig = _migration_files(sysops.release_path(site.key, current))
    old_mig = _migration_files(sysops.release_path(site.key, target))
    reversed_any = False
    for app, names in cur_mig.items():
        wanted = old_mig.get(app, [])
        if names == wanted:
            continue
        code, out = sysops.manage(site.key, ['migrate', app, wanted[-1] if wanted else 'zero', '--noinput'], current, timeout=240)
        reversed_any = True
        if code != 0:
            if backup:
                restore_db(site, backup)
            steps.fail()
            raise HostingError('ساختارِ داده در نسخهٔ فعلی عوض شده و برگرداندنش بدونِ از دست رفتنِ داده ممکن نیست؛ برای همین سایت همین‌طور که بود ماند.', out)
    steps.next()
    sysops.swap_current(site.key, target)
    sysops.unit_start(site.key)
    sysops.unit_restart(site.key)
    ok, why = wait_healthy(site)
    if not ok:
        sysops.swap_current(site.key, current)
        if backup and reversed_any:
            sysops.run(['systemctl', 'stop', sysops.unit_of(site.key) + '.service'], check=False, timeout=60)
            restore_db(site, backup)
        sysops.unit_start(site.key)
        sysops.unit_restart(site.key)
        steps.fail()
        raise HostingError('نسخهٔ قبلی بالا نیامد؛ همان نسخهٔ فعلی نگه داشته شد.', why)
    site.previous_release = current
    site.current_release = target
    site.state = PublishedSite.LIVE
    site.last_error = ''
    site.save(update_fields=['previous_release', 'current_release', 'state', 'last_error'])
    steps.done()
    return public_address(site)


# ─────────────────────────────── دامنه
def _restart_for_env(site):
    sysops.write_env(site.key, _env_values(site))
    if sysops.unit_exists(site.key) and site.state == PublishedSite.LIVE:
        sysops.unit_restart(site.key)
        ok, why = wait_healthy(site)
        if not ok:
            raise HostingError('سایت بعد از تغییرِ دامنه بالا نیامد.', why)


def connect_domain(site, job, names, staging=False):
    """DNS درست است: vhost ِ http ⇐ گواهی ⇐ https. هر شکستی در گواهی سایت را با http روشن نگه می‌دارد."""
    steps = Steps(job, ['آماده‌سازیِ نشانی', 'گرفتنِ گواهیِ امنیت (تا یک دقیقه)', 'روشن‌کردنِ قفلِ امن (https)'])
    steps.next()
    site.domain_www = len(names) > 1
    site.domain_state = PublishedSite.DOMAIN_HTTP
    site.domain_error = ''
    site.save(update_fields=['domain_www', 'domain_state', 'domain_error'])
    previous_vhost = None
    if os.path.exists(sysops.vhost_path(site.key)):
        with open(sysops.vhost_path(site.key), encoding='utf-8') as fh:
            previous_vhost = fh.read()
    try:
        sysops.write_vhost(site.key, render_vhost(site))
        _restart_for_env(site)
    except sysops.SysError as exc:
        site.domain_state = PublishedSite.DOMAIN_FAILED
        site.domain_error = 'تنظیمِ این دامنه روی سرور پذیرفته نشد و چیزی عوض نشد.'
        site.save(update_fields=['domain_state', 'domain_error'])
        steps.fail()
        if previous_vhost:
            sysops.write_vhost(site.key, previous_vhost)
        raise HostingError(site.domain_error, exc)
    steps.next()
    ok, out = sysops.certbot_issue(site.key, names, staging=staging)
    if not ok:
        site.domain_error = domains.explain_cert_failure(out)
        site.save(update_fields=['domain_error'])
        steps.fail()
        raise HostingError(site.domain_error, out)
    steps.next()
    site.domain_state = PublishedSite.DOMAIN_ACTIVE
    site.domain_staging = bool(staging)
    site.cert_expires = sysops.cert_enddate(site.key)
    site.save(update_fields=['domain_state', 'domain_staging', 'cert_expires'])
    try:
        sysops.write_vhost(site.key, render_vhost(site))
        _restart_for_env(site)
    except (sysops.SysError, HostingError) as exc:
        site.domain_state = PublishedSite.DOMAIN_HTTP
        site.domain_error = 'گواهی گرفته شد ولی روشن‌کردنِ https روی سرور نشد؛ سایت با http کار می‌کند.'
        site.save(update_fields=['domain_state', 'domain_error'])
        sysops.write_vhost(site.key, render_vhost(site))
        steps.fail()
        raise HostingError(site.domain_error, exc)
    steps.done()
    return public_address(site)


def disconnect_domain(site, job):
    steps = Steps(job, ['جدا کردنِ دامنه'])
    steps.next()
    site.domain = ''
    site.domain_www = False
    site.domain_state = PublishedSite.DOMAIN_NONE
    site.domain_error = ''
    site.domain_staging = False
    site.cert_expires = ''
    site.save(update_fields=['domain', 'domain_www', 'domain_state', 'domain_error', 'domain_staging', 'cert_expires'])
    if site.port:
        sysops.write_vhost(site.key, render_vhost(site))
        _restart_for_env(site)
    sysops.certbot_delete(site.key)
    steps.done()
    return public_address(site)


# ─────────────────────────────── روشن/خاموش/برداشتن
def stop(site, job):
    steps = Steps(job, ['خاموش کردنِ سایت'])
    steps.next()
    sysops.unit_stop(site.key)
    site.state = PublishedSite.STOPPED
    site.save(update_fields=['state'])
    steps.done()


def start(site, job):
    steps = Steps(job, ['روشن کردنِ سایت'])
    steps.next()
    guard = capacity()
    if guard['mem_available_mb'] < guard['min_mem_mb']:
        steps.fail()
        raise HostingError('حافظهٔ آزادِ این سرور کم است (%d مگابایت) و فعلاً نمی‌شود سایت را روشن کرد.' % guard['mem_available_mb'])
    sysops.unit_start(site.key)
    ok, why = wait_healthy(site)
    if not ok:
        steps.fail()
        raise HostingError('سایت روشن نشد.', '%s\n%s' % (why, sysops.journal_tail(site.key, 25)))
    site.state = PublishedSite.LIVE
    site.last_error = ''
    site.save(update_fields=['state', 'last_error'])
    steps.done()


def unpublish(site, job):
    """سرویس و vhost می‌روند؛ داده و پشتیبان‌ها می‌مانند. انتشارِ دوباره همان داده را برمی‌دارد."""
    steps = Steps(job, ['برداشتنِ سایت از اینترنت'])
    steps.next()
    try:
        backup_db(site, 'publish')
    except HostingError as exc:
        logger.warning('unpublish backup %s: %s', site.key, exc.technical)
    sysops.remove_vhost(site.key)      # اول vhost تا nginx به گواهیِ حذف‌شده نرسد
    sysops.unit_remove(site.key)
    sysops.certbot_delete(site.key)
    site.state = PublishedSite.UNPUBLISHED
    site.port = None
    site.local_port = None
    site.current_release = ''
    site.previous_release = ''
    site.domain_state = PublishedSite.DOMAIN_WAITING if site.domain else PublishedSite.DOMAIN_NONE
    site.domain_staging = False
    site.cert_expires = ''
    site.last_error = ''
    site.save()
    try:
        os.remove(os.path.join(sysops.site_root(site.key), 'current'))
    except OSError:
        pass
    for rid in sysops.list_releases(site.key):
        sysops.remove_release(site.key, rid)
    site.releases.all().delete()
    steps.done()


def reset_admin(site, job):
    steps = Steps(job, ['ساختنِ رمزِ تازهٔ مدیریت'])
    steps.next()
    rid = sysops.current_release(site.key)
    if not rid:
        steps.fail()
        raise HostingError('اول سایت را منتشر کن.')
    ensure_admin(site, rid, reset=True)
    steps.done()


def run_job(job):
    """نقطهٔ ورودِ Celery. خطا فقط در خودِ کار ثبت می‌شود."""
    site = job.site
    job.state = SiteJob.RUNNING
    job.save(update_fields=['state', 'updated_at'])
    payload = job.payload or {}
    try:
        with sysops.site_lock(site.key):
            if job.kind == SiteJob.PUBLISH:
                site.state = PublishedSite.PUBLISHING if not site.current_release else site.state
                site.save(update_fields=['state'])
                address = publish(site, job)
                job.message = 'سایت روی اینترنت است: %s' % address
            elif job.kind == SiteJob.ROLLBACK:
                job.message = 'سایت به نسخهٔ قبلی برگشت: %s' % rollback(site, job)
            elif job.kind == SiteJob.DOMAIN:
                job.message = 'دامنه وصل شد: %s' % connect_domain(site, job, payload['names'], staging=bool(payload.get('staging')))
            elif job.kind == SiteJob.DOMAIN_OFF:
                disconnect_domain(site, job)
                job.message = 'دامنه جدا شد. سایت از نشانیِ قبلی باز می‌شود.'
            elif job.kind == SiteJob.STOP:
                stop(site, job)
                job.message = 'سایت خاموش شد.'
            elif job.kind == SiteJob.START:
                start(site, job)
                job.message = 'سایت روشن شد.'
            elif job.kind == SiteJob.UNPUBLISH:
                unpublish(site, job)
                job.message = 'سایت از اینترنت برداشته شد. داده‌هایش نگه داشته شده‌اند.'
            elif job.kind == SiteJob.RESET_ADMIN:
                reset_admin(site, job)
                job.message = 'رمزِ تازهٔ مدیریت ساخته شد.'
            else:
                raise HostingError('کارِ ناشناخته.')
        job.state = SiteJob.OK
    except HostingError as exc:
        job.state = SiteJob.FAILED
        job.message = exc.message
        job.technical = exc.technical
    except sysops.SysError as exc:
        job.state = SiteJob.FAILED
        job.message = 'این کار الان انجام نشد؛ کارِ دیگری روی همین سایت در جریان است یا سرور خطا داد.'
        job.technical = str(exc)[-3000:]
    except Exception as exc:  # noqa: BLE001 — کار باید «شکست‌خورده» بشود، نه تا ابد «در حال انجام»
        logger.exception('hosting job %s', job.pk)
        job.state = SiteJob.FAILED
        job.message = 'این کار با خطای پیش‌بینی‌نشده تمام شد.'
        job.technical = repr(exc)[-3000:]
    job.finished_at = timezone.now()
    job.save(update_fields=['state', 'message', 'technical', 'finished_at', 'updated_at'])
    return job


# ─────────────────────────────── پیام‌های فرم
def read_messages(site, limit=30, offset=0, mark=None, read=True, count_only=False):
    args = json.dumps({'limit': int(limit), 'offset': int(offset), 'mark': mark, 'read': bool(read), 'count_only': bool(count_only)})
    code, out = sysops.sandbox_run(site.key, [sysops.runtime_python(), '-I', '-c', MESSAGES_READ, args], timeout=60)
    if code != 0:
        raise HostingError('پیام‌ها الان خوانده نشدند.', out)
    start_i = out.find('{"rows"')
    data = json.loads(out[start_i:]) if start_i >= 0 else {'rows': [], 'total': 0, 'unread': 0}
    for row in data['rows']:
        try:
            row['data'] = json.loads(row.get('data') or '{}')
        except ValueError:
            row['data'] = {}
        row['is_read'] = bool(row.get('is_read'))
    return data


# ─────────────────────────────── نگه‌داریِ روزانه
def daily_maintenance():
    """پشتیبانِ روزانه با نگه‌داریِ محدود، تاریخِ گواهی‌ها و کوتاه کردنِ لاگِ خطا."""
    done = []
    for site in PublishedSite.objects.exclude(port=None):
        try:
            name = backup_db(site, 'daily')
            prune_backups(site)
            if site.domain_state == PublishedSite.DOMAIN_ACTIVE:
                site.cert_expires = sysops.cert_enddate(site.key) or site.cert_expires
                site.save(update_fields=['cert_expires'])
            log = '/www/wwwlogs/%s%s.error.log' % (sysops.PREFIX, site.key)
            if os.path.exists(log) and os.path.getsize(log) > 5 * 1048576:
                with open(log, 'r+b') as fh:
                    fh.truncate(0)
            done.append((site.key, name))
        except Exception as exc:  # noqa: BLE001 — یک سایت نباید بقیه را بی‌پشتیبان بگذارد
            logger.warning('daily %s: %s', site.key, exc)
            done.append((site.key, 'failed: %s' % exc))
    return done


__all__ = ['publish', 'rollback', 'run_job', 'get_site', 'capacity', 'render_vhost', 'HostingError', 'public_address', 'base64']
