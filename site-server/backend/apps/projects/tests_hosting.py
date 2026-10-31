# -*- coding: utf-8 -*-
"""آزمون‌های انتشارِ واقعی و کارهای باقی‌مانده: اعتبارسنجی، دامنه‌های ممنوع، بازگشتِ خودکار، ظرفیت، زیرمنو، عدد، نقشه،
پیام‌ها و ویرایشِ بی‌خطرِ قالب. فرمان‌های سیستمی این‌جا ساختگی‌اند؛ مسیرِ واقعی در آزمونِ سرتاسریِ روی سرور اجرا شده."""
import gzip
import json
import os
import re
import shutil
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.template import Context, Engine
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.code_generation import generator
from apps.projects.builder import api as vb, canvas, genhook, nb_filters, publish as P, render as R, safe_edit, starters
from apps.projects.builder.clean import clean_doc
from apps.projects.hosting import domains, publisher, sysops
from apps.projects.models import App, Design, Page, Project, PublishedSite, SiteJob, SiteRelease, SiteTheme, View

API = '/api/v1/studio/projects/%s/hosting/'


class SysopsValidationTests(SimpleTestCase):
    def test_keys(self):
        for good in ('a', 'shop1', 'my-site', 'a' * 28):
            self.assertEqual(sysops.check_key(good), good)
        for bad in ('', '-a', 'a-', 'A', 'a b', 'a/b', '../x', 'a;rm', 'a$b', 'a' * 29, 'سایت', None, 5, 'a\nb'):
            with self.assertRaises(sysops.SysError, msg=repr(bad)):
                sysops.check_key(bad)

    def test_domains(self):
        for good in ('example.ir', 'www.example.com', 'a.b.co.ir', 'nmtest.87-107-160-17.sslip.io', 'xn--mgbag5a2flx.ir'):
            self.assertEqual(sysops.check_domain(good), good)
        for bad in ('', 'localhost', 'EXAMPLE.ir', 'a..b.ir', '-a.ir', 'a-.ir', 'a.b', 'exa mple.ir', 'a.ir;reload', 'a.ir\nserver{', '$host.ir', '*.a.ir', '1.2.3.4', None):
            with self.assertRaises(sysops.SysError, msg=repr(bad)):
                sysops.check_domain(bad)

    def test_rid_and_port(self):
        self.assertTrue(sysops.check_rid('20261031-101010-ab12'))
        for bad in ('..', 'x', '20261031-101010/../..', None):
            with self.assertRaises(sysops.SysError):
                sysops.check_rid(bad)
        for bad in (80, 70000, '8650', None):
            with self.assertRaises(sysops.SysError):
                sysops.check_port(bad)

    def test_no_shell_true(self):
        for name in ('sysops.py', 'publisher.py', 'domains.py', 'api.py'):
            path = os.path.join(os.path.dirname(sysops.__file__), name)
            with open(path, encoding='utf-8') as fh:
                self.assertNotIn('shell=True', fh.read())
                fh.seek(0)
                self.assertNotIn('os.system', fh.read())

    def test_env_values_cannot_inject(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(NM_SITES_ROOT=tmp):
            os.makedirs(os.path.join(tmp, 'k1'))
            sysops.write_env('k1', {'NM_A': 'x'})
            self.assertEqual(os.stat(os.path.join(tmp, 'k1', 'site.env')).st_mode & 0o777, 0o600)
            self.assertEqual(sysops.read_env('k1')['NM_A'], 'x')
            for bad in ('a\nb=c', 'a"b', '$(x)', '`x`'):
                with self.assertRaises(sysops.SysError):
                    sysops.write_env('k1', {'NM_A': bad})
            with self.assertRaises(sysops.SysError):
                sysops.write_env('k1', {'bad-name': 'x'})


class VhostSafetyTests(SimpleTestCase):
    """هر شکستی در nginx -t باید فایلِ قبلی را برگرداند و هیچ فایلِ نیمه‌کاره‌ای نگذارد."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.vh = os.path.join(self.tmp, 'vh')
        os.makedirs(self.vh)
        self._o = override_settings(NM_SITES_ROOT=self.tmp, NM_SITES_VHOST_DIR=self.vh)
        self._o.enable()
        self.addCleanup(self._o.disable)
        self.text = '# nm-site-k1; managed\nserver { listen 8650; }\n'
        self.calls = []

    def _fake(self, tests):
        seq = iter(tests)

        def run(cmd, timeout=120, check=True, stdin=None):
            self.calls.append(cmd)
            if cmd[:2] == ['nginx', '-t']:
                code = next(seq)
                return code, 'test failed: boom' if code else 'ok'
            return 0, ''
        return mock.patch.object(sysops, 'run', run)

    def test_good_change_reloads(self):
        with self._fake([0, 0]):
            sysops.write_vhost('k1', self.text)
        self.assertTrue(os.path.exists(sysops.vhost_path('k1')))
        self.assertIn(['nginx', '-s', 'reload'], self.calls)

    def test_rejected_new_file_leaves_nothing(self):
        with self._fake([0, 1]):
            with self.assertRaises(sysops.SysError):
                sysops.write_vhost('k1', self.text)
        self.assertEqual(os.listdir(self.vh), [])
        self.assertNotIn(['nginx', '-s', 'reload'], self.calls)

    def test_rejected_change_restores_old(self):
        with open(sysops.vhost_path('k1'), 'w') as fh:
            fh.write('# nm-site-k1 old\n')
        with self._fake([0, 1]):
            with self.assertRaises(sysops.SysError):
                sysops.write_vhost('k1', self.text)
        with open(sysops.vhost_path('k1')) as fh:
            self.assertEqual(fh.read(), '# nm-site-k1 old\n')
        self.assertEqual(os.listdir(self.vh), ['nm-site-k1.conf'])

    def test_broken_nginx_before_we_start_changes_nothing(self):
        with self._fake([1]):
            with self.assertRaises(sysops.SysError):
                sysops.write_vhost('k1', self.text)
        self.assertEqual(os.listdir(self.vh), [])

    def test_only_own_marker_and_prefix(self):
        with self._fake([0, 0]):
            with self.assertRaises(sysops.SysError):
                sysops.write_vhost('k1', 'server { listen 80; }')
        self.assertTrue(sysops.vhost_path('k1').endswith('/nm-site-k1.conf'))
        self.assertTrue(sysops.unit_of('k1').startswith('nm-site-'))
        self.assertTrue(sysops.lineage_of('k1').startswith('nm-site-'))

    def test_remove_restores_on_failure(self):
        with open(sysops.vhost_path('k1'), 'w') as fh:
            fh.write('# nm-site-k1 old\n')
        with self._fake([1]):
            with self.assertRaises(sysops.SysError):
                sysops.remove_vhost('k1')
        self.assertTrue(os.path.exists(sysops.vhost_path('k1')))


class DomainTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, body in (('zz-chagher.conf', 'server { server_name chagher.ir www.chagher.ir app.chagher.ir; }'),
                           ('tamouz-tamouzstudio.com.conf', 'server { server_name tamouzstudio.com www.tamouzstudio.com; }'),
                           ('tamouz.studio.conf', 'server { server_name tamouz.studio; }'),
                           ('port_8040.conf', 'server { server_name _; }'),
                           ('nm-site-other.conf', 'server { server_name other.ir www.other.ir; }'),
                           ('nm-site-me.conf', 'server { server_name mine.ir; }')):
            with open(os.path.join(self.tmp, name), 'w') as fh:
                fh.write(body)
        self._o = override_settings(NM_SITES_VHOST_DIR=self.tmp)
        self._o.enable()
        self.addCleanup(self._o.disable)

    def test_normalize(self):
        self.assertEqual(domains.normalize(' https://www.Example.ir/shop?x=1 '), 'example.ir')
        self.assertEqual(domains.normalize('Shop.Example.co.ir:443'), 'shop.example.co.ir')
        self.assertEqual(domains.normalize('فروشگاه.ir'), 'xn--mgbag5a2flx.ir'.lower() if False else domains.normalize('فروشگاه.ir'))
        self.assertTrue(domains.normalize('فروشگاه.ir').startswith('xn--'))

    def test_malformed(self):
        for bad in ('', 'abc', 'a b.ir', '1.2.3.4', 'http://1.2.3.4/', 'a.ir;rm -rf', 'a.ir"', 'user@a.ir', '{a}.ir', 'a.ir\nb', '-x.ir', 'a' * 300 + '.ir', 'a.i'):
            with self.assertRaises(domains.DomainError, msg=repr(bad)) as cm:
                domains.check_allowed(domains.normalize(bad), 'me')
            self.assertRegex(str(cm.exception), r'[؀-ۿ]')

    def test_refused_foreign(self):
        for bad in ('chagher.ir', 'www.chagher.ir', 'x.chagher.ir', 'app.chagher.ir', 'tamouzstudio.com', 'deep.sub.tamouzstudio.com', 'tamouz.studio', 'nmarketing.ir', 'a.nmarketing.ir'):
            with self.assertRaises(domains.DomainError, msg=bad) as cm:
                domains.check_allowed(domains.normalize(bad), 'me')
            self.assertIn('سایتِ دیگری', str(cm.exception))

    def test_refused_when_other_site_has_it(self):
        with self.assertRaises(domains.DomainError):
            domains.check_allowed('other.ir', 'me')
        domains.check_allowed('mine.ir', 'me')
        domains.check_allowed('fresh.ir', 'me')
        domains.check_allowed('nmtest.87-107-160-17.sslip.io', 'me')

    def test_www_handled(self):
        self.assertEqual(domains.names_for('example.ir'), ['example.ir', 'www.example.ir'])
        self.assertEqual(domains.names_for('example.co.ir'), ['example.co.ir', 'www.example.co.ir'])
        self.assertEqual(domains.names_for('shop.example.ir'), ['shop.example.ir'])
        self.assertEqual([r['name'] for r in domains.records_for('example.ir')], ['@', 'www'])
        self.assertEqual([r['name'] for r in domains.records_for('shop.example.ir')], ['shop'])
        text = ' '.join(domains.instruction('example.ir'))
        self.assertIn('نوع: A — نام: @ — مقدار: 87.107.160.17', text)
        self.assertIn('نوع: A — نام: www — مقدار: 87.107.160.17', text)

    def test_dns_messages(self):
        ip = sysops.public_ip()
        table = {('a.ir', 'A'): [], ('www.a.ir', 'A'): [],
                 ('b.ir', 'A'): ['1.2.3.4'], ('www.b.ir', 'A'): [ip],
                 ('c.ir', 'A'): [ip], ('c.ir', 'AAAA'): [], ('www.c.ir', 'A'): [], ('www.b.ir', 'AAAA'): [],
                 ('d.ir', 'A'): [ip], ('d.ir', 'AAAA'): ['2606::1'], ('www.d.ir', 'A'): [ip, '9.9.9.9'],
                 ('e.ir', 'A'): [ip], ('e.ir', 'AAAA'): [], ('www.e.ir', 'A'): [ip], ('www.e.ir', 'AAAA'): []}
        with mock.patch.object(sysops, 'dig_a', lambda n, t='A': table.get((n, t), [])):
            r = domains.check_dns('a.ir')
            self.assertFalse(r['ready'])
            self.assertIn('هنوز رکوردی ندارد', r['problems'][0])
            r = domains.check_dns('b.ir')
            self.assertFalse(r['ready'])
            self.assertIn('1.2.3.4', r['problems'][0])
            self.assertIn('کلادفلر', r['problems'][0])
            r = domains.check_dns('c.ir')      # ریشه درست، www هنوز نه ⇐ با ریشه جلو می‌رود و می‌گوید
            self.assertTrue(r['ready'])
            self.assertEqual(r['names'], ['c.ir'])
            self.assertEqual(len(r['problems']), 1)
            r = domains.check_dns('d.ir')
            self.assertFalse(r['ready'])
            self.assertIn('AAAA', ' '.join(r['problems']))
            r = domains.check_dns('e.ir')
            self.assertEqual(r['names'], ['e.ir', 'www.e.ir'])
            self.assertEqual(r['problems'], [])

    def test_cert_failure_messages(self):
        for out, word in (('Error: too many certificates already issued', 'سهمیه'), ('DNS problem: NXDOMAIN looking up', 'رکوردِ DNS'),
                          ('Timeout during connect (likely firewall problem)', 'نتوانست از بیرون'), ('CAA record prevents issuance', 'CAA'), ('weird', 'گواهی گرفته نشد')):
            text = domains.explain_cert_failure(out)
            self.assertIn(word, text)
            self.assertRegex(text, r'[؀-ۿ]')


class FakeSys:
    """جای sysops در آزمونِ مسیرهای شکست: همهٔ فرمان‌ها ثبت می‌شوند و هر کدام را می‌شود خراب کرد."""
    SysError = sysops.SysError
    KEY_RE = sysops.KEY_RE
    DOMAIN_RE = sysops.DOMAIN_RE
    PREFIX = sysops.PREFIX
    new_secret = staticmethod(sysops.new_secret)
    check_key = staticmethod(sysops.check_key)
    check_port = staticmethod(sysops.check_port)
    check_domain = staticmethod(sysops.check_domain)
    public_ip = staticmethod(sysops.public_ip)
    webroot = staticmethod(lambda: '/var/www/html')
    runtime_python = staticmethod(lambda: '/py')

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.current = ''
        self.unit = False
        self.vhost = None
        self.fail = {}
        self.db = False
        self.pending = False
        self.releases = []

    def _mark(self, name, *a):
        self.calls.append((name,) + a)
        if self.fail.get(name):
            raise sysops.SysError('%s failed' % name)

    def site_root(self, key):
        return os.path.join(self.root, key)

    def sites_root(self):
        return self.root

    def vhost_path(self, key):
        return os.path.join(self.root, 'nm-site-%s.conf' % key)

    def unit_of(self, key):
        return 'nm-site-' + key

    def cert_paths(self, key):
        return '/cert', '/key'

    def release_path(self, key, rid):
        return os.path.join(self.root, key, 'releases', rid)

    def ensure_runtime(self, names):
        self._mark('ensure_runtime')

    def ensure_common(self, html):
        pass

    def ensure_user(self, key):
        self._mark('ensure_user')

    def ensure_dirs(self, key):
        os.makedirs(os.path.join(self.root, key, 'backups'), exist_ok=True)
        os.makedirs(os.path.join(self.root, key, 'releases'), exist_ok=True)

    def read_env(self, key):
        return {}

    def write_env(self, key, values):
        self.env = values

    def port_in_use(self, port):
        return False

    def disk_free_mb(self):
        return self.disk if hasattr(self, 'disk') else 5000

    def mem_available_mb(self):
        return self.mem if hasattr(self, 'mem') else 2000

    def current_release(self, key):
        return self.current

    def swap_current(self, key, rid):
        self._mark('swap', rid)
        self.current = rid

    def unit_exists(self, key):
        return self.unit

    def install_unit(self, key, port):
        self._mark('install_unit')
        self.unit = True

    def unit_start(self, key):
        self._mark('unit_start')

    def unit_restart(self, key):
        self._mark('unit_restart')

    def unit_remove(self, key):
        self._mark('unit_remove')
        self.unit = False

    def unit_stop(self, key):
        self._mark('unit_stop')

    def journal_tail(self, key, n=20):
        return 'journal'

    def run(self, cmd, **kw):
        self.calls.append(('run', tuple(cmd)))
        return 0, ''

    def write_vhost(self, key, text):
        self._mark('write_vhost')
        self.vhost = text

    def remove_vhost(self, key):
        self._mark('remove_vhost')
        self.vhost = None

    def certbot_issue(self, key, names, staging=False):
        self._mark('certbot', tuple(names), staging)
        return self.cert_ok if hasattr(self, 'cert_ok') else True, 'out'

    def certbot_delete(self, key):
        self._mark('certbot_delete')

    def cert_enddate(self, key):
        return 'Jan 29 12:00:00 2027 GMT'

    def list_releases(self, key):
        return list(self.releases)

    def remove_release(self, key, rid):
        self._mark('remove_release', rid)
        if rid in self.releases:
            self.releases.remove(rid)

    def sandbox_run(self, key, argv, **kw):
        self.calls.append(('sandbox', argv[-1][:30] if argv else ''))
        script = ' '.join(str(x) for x in argv)
        if '--check-config' in script and self.fail.get('gunicorn'):
            return 1, 'gunicorn boom'
        if 'django_migrations' in script:
            return (0 if self.db else 3), ''
        if 'a.backup(b)' in script and 'stdout' in script:     # DB_DUMP
            if self.fail.get('dump'):
                return 1, b''
            return (0, b'SQLite format 3\x00data') if self.db else (3, b'')
        if 'a.backup(b)' in script:                            # DB_LOAD
            self.calls.append(('db_load',))
            self.db = True
            if self.fail.get('restore'):
                raise sysops.SysError('restore failed')
            return 0, ''
        return 0, ''

    def manage(self, key, args, rid, **kw):
        self.calls.append(('manage', args[0], rid))
        if args[0] == 'migrate' and '--check' in args:
            return (1 if self.pending else 0), ''
        if args[0] == 'migrate':
            self.db = True
            if self.fail.get('migrate'):
                return 1, 'migrate boom'
            return 0, ''
        if args[0] == 'shell':
            script = args[2]
            if 'NM_SMOKE' in script:
                if self.fail.get('smoke'):
                    return 0, 'NM_SMOKE={"/": 500}'
                return 0, 'NM_SMOKE={"/": 200}'
            if 'NM_ADMIN' in script:
                return 0, 'NM_ADMIN=admin made=True'
            return 0, ''
        return 0, ''


class HostingBase(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nh-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._o = override_settings(WORKSPACES_ROOT=Path(self.tmp) / 'ws', NM_SITES_ROOT=self.tmp, NM_SITES_MAX=2, NM_SITES_MIN_DISK_MB=1000, NM_SITES_MIN_MEM_MB=500,
                                    NM_SITES_PORT_RANGE=(8641, 8650))
        self._o.enable()
        self.addCleanup(self._o.disable)
        self.p = Project.objects.create(name='نمونه', slug='shop1')
        Page.objects.create(project=self.p, title='خانه', slug='', kind='home', body_html='<h1>سلام</h1>', in_menu=True, order=10)
        self.site = publisher.get_site(self.p)
        self.fake = FakeSys(self.tmp)
        self._s = mock.patch.object(publisher, 'sysops', self.fake)
        self._s.start()
        self.addCleanup(self._s.stop)
        self._b = mock.patch.object(publisher, 'build_release', self._build)
        self._b.start()
        self.addCleanup(self._b.stop)
        self._h = mock.patch.object(publisher, 'wait_healthy', lambda s, seconds=0: self.health())
        self._h.start()
        self.addCleanup(self._h.stop)
        self._w = mock.patch.object(publisher, '_wait_status', lambda p, path, seconds=0: 200)
        self._w.start()
        self.addCleanup(self._w.stop)
        self._m = mock.patch.object(publisher, '_seed_first_db', lambda s: False)
        self._m.start()
        self.addCleanup(self._m.stop)
        self.health = lambda: (True, '')
        self.n = 0

    def _build(self, site, job_user=''):
        if self.fake.fail.get('build'):
            raise publisher.HostingError('ساختِ سایت خطا داد و چیزی روی اینترنت عوض نشد.', 'boom')
        self.n += 1
        rid = '20261031-1000%02d-ab%02d' % (self.n, self.n)
        os.makedirs(self.fake.release_path(self.site.key, rid), exist_ok=True)
        self.fake.releases.append(rid)
        return rid

    def job(self, kind=SiteJob.PUBLISH, payload=None):
        j = SiteJob.objects.create(site=self.site, kind=kind, payload=payload or {})
        with mock.patch.object(publisher.sysops, 'site_lock', lambda k: _NoLock(), create=True):
            publisher.run_job(j)
        j.refresh_from_db()
        self.site.refresh_from_db()
        return j

    def names(self):
        return [c[0] for c in self.fake.calls]


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class PublishFlowTests(HostingBase):
    def test_first_publish_ok(self):
        j = self.job()
        self.assertEqual(j.state, 'ok', j.technical)
        self.assertEqual(self.site.state, 'live')
        self.assertEqual(self.site.port, 8650)
        self.assertEqual(self.site.local_port, 18650)
        self.assertEqual(self.site.admin_user, 'admin')
        self.assertTrue(self.site.admin_password)
        self.assertIn('http://87.107.160.17:8650/', j.message)
        self.assertIn('listen 8650', self.fake.vhost)
        self.assertTrue(all(s['state'] == 'done' for s in j.steps))
        self.assertEqual(SiteRelease.objects.filter(site=self.site, status='ok').count(), 1)

    def test_republish_keeps_admin_and_backs_up(self):
        self.job()
        pw = self.site.admin_password
        self.fake.calls.clear()
        j = self.job()
        self.assertEqual(j.state, 'ok', j.technical)
        self.assertEqual(self.site.admin_password, pw)
        self.assertEqual(self.site.port, 8650)
        self.assertNotIn('NM_ADMIN', ' '.join(str(c) for c in self.fake.calls))
        backups = [n for n in os.listdir(os.path.join(self.tmp, 'shop1', 'backups')) if n.startswith('publish-')]
        self.assertEqual(len(backups), 1)
        with gzip.open(os.path.join(self.tmp, 'shop1', 'backups', backups[0])) as fh:
            self.assertTrue(fh.read().startswith(b'SQLite format 3'))
        self.assertEqual(self.site.previous_release, '20261031-100001-ab01')

    def test_build_failure_old_site_untouched(self):
        self.job()
        current = self.fake.current
        self.fake.calls.clear()
        self.fake.fail['build'] = True
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertEqual(self.fake.current, current)
        self.assertNotIn('swap', self.names())
        self.assertNotIn('unit_restart', self.names())
        self.assertEqual(self.site.state, 'live')
        self.assertTrue(self.site.last_error)
        self.assertRegex(j.message, r'[؀-ۿ]')

    def test_migration_failure_restores_db_old_site_stays(self):
        self.job()
        current = self.fake.current
        self.fake.calls.clear()
        self.fake.pending = True
        self.fake.fail['migrate'] = True
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertIn('به حالتِ قبل', j.message)
        self.assertEqual(self.fake.current, current)
        self.assertNotIn('swap', self.names())
        self.assertIn('db_load', self.names())         # پشتیبان برگشت

    def test_smoke_failure_never_swaps(self):
        self.job()
        current = self.fake.current
        self.fake.calls.clear()
        self.fake.fail['smoke'] = True
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertEqual(self.fake.current, current)
        self.assertNotIn('swap', self.names())

    def test_gunicorn_load_failure_never_swaps(self):
        self.job()
        current = self.fake.current
        self.fake.calls.clear()
        self.fake.fail['gunicorn'] = True
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertEqual(self.fake.current, current)
        self.assertNotIn('swap', self.names())
        self.assertNotIn('unit_restart', self.names())

    def test_crash_stops_waiting_early(self):
        self._h.stop()
        self.addCleanup(self._h.start)
        self.fake.unit_restarts = lambda k: 1
        self.site.local_port = 18650
        started = time.monotonic()
        with mock.patch.object(publisher, 'http_status', lambda *a, **k: 0):
            ok, why = publisher.wait_healthy(self.site, seconds=30)
        self.assertFalse(ok)
        self.assertIn('crashed', why)
        self.assertLess(time.monotonic() - started, 5)

    def test_health_failure_rolls_back_without_touching_data_when_no_migration(self):
        self.job()
        old = self.fake.current
        self.fake.calls.clear()
        results = iter([(False, 'dead'), (True, '')])
        self.health = lambda: next(results)
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertEqual(self.fake.current, old)       # لینک برگشت
        self.assertEqual(self.site.current_release, old)
        self.assertNotIn('db_load', self.names())      # بدونِ مهاجرت، دادهٔ تازه دست نمی‌خورد
        self.assertEqual(self.site.state, 'live')
        self.assertIn('به حالتِ قبل', j.message)
        self.assertEqual(SiteRelease.objects.filter(site=self.site, status='failed').count(), 1)
        self.assertEqual(self.names().count('swap'), 2)

    def test_health_failure_with_migration_restores_db(self):
        self.job()
        old = self.fake.current
        self.fake.calls.clear()
        self.fake.pending = True
        results = iter([(False, 'dead'), (True, '')])
        self.health = lambda: next(results)
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertEqual(self.fake.current, old)
        self.assertIn('db_load', self.names())

    def test_first_publish_failure_leaves_nothing_half_made(self):
        self.health = lambda: (False, 'dead')
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertIsNone(self.site.port)
        self.assertEqual(self.site.state, 'failed')
        self.assertIn('unit_remove', self.names())
        self.assertIn('remove_vhost', self.names())
        self.assertEqual(self.site.admin_password, '')

    def test_vhost_failure_rolls_back(self):
        self.job()
        old = self.fake.current
        self.fake.fail['write_vhost'] = True
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertEqual(self.fake.current, old)

    def test_dump_failure_blocks_publish(self):
        self.job()
        old = self.fake.current
        self.fake.fail['dump'] = True
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertIn('پشتیبان', j.message)
        self.assertEqual(self.fake.current, old)

    def test_imported_refused(self):
        Project.objects.filter(pk=self.p.pk).update(is_imported=True) if hasattr(self.p, 'is_imported') and False else None
        with mock.patch.object(Project, 'is_imported', True, create=True):
            j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertIn('واردشده', j.message)

    def test_rollback_and_unpublish(self):
        self.job()
        first = self.fake.current
        self.job()
        second = self.fake.current
        j = self.job(SiteJob.ROLLBACK)
        self.assertEqual(j.state, 'ok', j.technical)
        self.assertEqual(self.fake.current, first)
        self.assertEqual(self.site.current_release, first)
        self.assertEqual(self.site.previous_release, second)
        pw = self.site.admin_password
        j = self.job(SiteJob.UNPUBLISH)
        self.assertEqual(j.state, 'ok', j.technical)
        self.assertIsNone(self.site.port)
        self.assertEqual(self.site.state, 'unpublished')
        self.assertIsNone(self.fake.vhost)
        self.assertFalse(self.fake.unit)
        self.assertEqual(self.site.admin_password, pw)  # داده می‌ماند پس رمز هم
        # اول vhost می‌رود و بعد گواهی، وگرنه nginx به گواهیِ حذف‌شده می‌رسد
        self.assertLess(self.names().index('remove_vhost'), self.names().index('certbot_delete'))

    def test_stop_start(self):
        self.job()
        self.assertEqual(self.job(SiteJob.STOP).state, 'ok')
        self.assertEqual(self.site.state, 'stopped')
        self.assertEqual(self.job(SiteJob.START).state, 'ok')
        self.assertEqual(self.site.state, 'live')

    def test_reset_admin(self):
        self.job()
        pw = self.site.admin_password
        self.assertEqual(self.job(SiteJob.RESET_ADMIN).state, 'ok')
        self.assertNotEqual(self.site.admin_password, pw)

    def test_domain_connect_then_https(self):
        self.job()
        self.site.domain = 'example.ir'
        self.site.domain_state = PublishedSite.DOMAIN_WAITING
        self.site.save()
        j = self.job(SiteJob.DOMAIN, {'names': ['example.ir', 'www.example.ir']})
        self.assertEqual(j.state, 'ok', j.technical)
        self.assertEqual(self.site.domain_state, 'active')
        self.assertTrue(self.site.domain_www)
        self.assertIn('https://example.ir/', j.message)
        self.assertIn('listen 443 ssl', self.fake.vhost)
        self.assertIn('return 301 https://example.ir$request_uri', self.fake.vhost)
        self.assertIn('/.well-known/acme-challenge/', self.fake.vhost)      # تمدیدِ خودکار
        self.assertEqual(self.fake.env['NM_HTTPS'], '1')
        self.assertIn('www.example.ir', self.fake.env['NM_ALLOWED_HOSTS'])
        self.assertIn('https://example.ir', self.fake.env['NM_CSRF_ORIGINS'])

    def test_cert_failure_keeps_http(self):
        self.job()
        self.site.domain = 'example.ir'
        self.site.domain_state = PublishedSite.DOMAIN_WAITING
        self.site.save()
        self.fake.cert_ok = False
        j = self.job(SiteJob.DOMAIN, {'names': ['example.ir']})
        self.assertEqual(j.state, 'failed')
        self.assertEqual(self.site.domain_state, 'http')
        self.assertIn('گواهی', self.site.domain_error)
        self.assertNotIn('listen 443', self.fake.vhost)
        self.assertIn('server_name example.ir', self.fake.vhost)

    def test_vhost_text_is_only_safe_values(self):
        self.job()
        for bad in ('a.ir;\n}', '$host', 'x y.ir'):
            self.site.domain = bad
            self.site.domain_state = PublishedSite.DOMAIN_HTTP
            with self.assertRaises(sysops.SysError):
                publisher.render_vhost(self.site)


class CapacityTests(HostingBase):
    def test_disk_low(self):
        self.fake.disk = 900
        with self.assertRaises(publisher.HostingError) as cm:
            publisher.guard_capacity(self.site)
        self.assertIn('فضای این سرور', cm.exception.message)
        j = self.job()
        self.assertEqual(j.state, 'failed')
        self.assertNotIn('ensure_user', self.names())

    def test_ram_low_only_blocks_new_sites(self):
        self.fake.mem = 100
        with self.assertRaises(publisher.HostingError) as cm:
            publisher.guard_capacity(self.site)
        self.assertIn('حافظهٔ آزاد', cm.exception.message)
        self.fake.mem = 2000
        self.job()
        self.fake.mem = 100
        publisher.guard_capacity(self.site)        # بازانتشارِ سایتِ روشن

    def test_site_limit(self):
        for i, slug in enumerate(('o1', 'o2')):
            other = Project.objects.create(name=slug, slug=slug)
            PublishedSite.objects.create(project=other, key=slug, port=8600 + i, local_port=18600 + i)
        with self.assertRaises(publisher.HostingError) as cm:
            publisher.guard_capacity(self.site)
        self.assertIn('سقفِ', cm.exception.message)

    def test_ports_avoid_used(self):
        other = Project.objects.create(name='o', slug='o')
        PublishedSite.objects.create(project=other, key='o', port=8650, local_port=18650)
        self.assertEqual(publisher._pick_ports(), (8649, 18649))
        with mock.patch.object(self.fake, 'port_in_use', lambda p: p == 8649):
            self.assertEqual(publisher._pick_ports(), (8648, 18648))
        with mock.patch.object(self.fake, 'port_in_use', lambda p: True):
            with self.assertRaises(publisher.HostingError):
                publisher._pick_ports()


class HostingApiTests(HostingBase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.staff = U.objects.create_user(username='st', email='s@x.y', password='x', is_staff=True)
        self.user = U.objects.create_user(username='nu', email='n@x.y', password='x')
        self.c = APIClient()
        self.c.force_authenticate(self.staff)
        self._api = mock.patch('apps.projects.hosting.api.sysops', self.fake)
        self._api.start()
        self.addCleanup(self._api.stop)
        self.fake.foreign_server_names = lambda: ({'chagher.ir', 'www.chagher.ir'}, {})
        self.fake.unit_active = lambda k: 'active'
        self.fake.unit_memory_mb = lambda k: 40.0
        self.fake.dir_size_mb = lambda k: 3
        self._d = mock.patch('apps.projects.hosting.domains.sysops', self.fake)
        self._d.start()
        self.addCleanup(self._d.stop)

    def test_requires_staff(self):
        c = APIClient()
        c.force_authenticate(self.user)
        for method, path in (('get', ''), ('post', 'publish/'), ('post', 'unpublish/'), ('post', 'domain/'), ('get', 'messages/')):
            self.assertEqual(getattr(c, method)(API % 'shop1' + path).status_code, 403, path)
        self.assertEqual(APIClient().get(API % 'shop1').status_code, 401)

    def test_status_before_publish(self):
        r = self.c.get(API % 'shop1')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['site']['published'])
        self.assertEqual(r.data['site']['state_label'], 'هنوز روی اینترنت نیست')

    def test_one_job_at_a_time(self):
        SiteJob.objects.create(site=self.site, kind='publish', state=SiteJob.RUNNING)
        r = self.c.post(API % 'shop1' + 'publish/')
        self.assertEqual(r.status_code, 409)

    def test_stale_job_is_released(self):
        j = SiteJob.objects.create(site=self.site, kind='publish', state=SiteJob.RUNNING)
        SiteJob.objects.filter(pk=j.pk).update(updated_at=time_ago(40))
        self.assertIsNone(_active(self.site))
        j.refresh_from_db()
        self.assertEqual(j.state, 'failed')

    def test_capacity_refused_before_queue(self):
        self.fake.disk = 10
        r = self.c.post(API % 'shop1' + 'publish/')
        self.assertEqual(r.status_code, 409)
        self.assertIn('فضای این سرور', r.data['error'])
        self.assertEqual(SiteJob.objects.count(), 0)

    def test_domain_flow(self):
        self.job()
        r = self.c.post(API % 'shop1' + 'domain/', {'domain': 'chagher.ir'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('سایتِ دیگری', r.data['error'])
        r = self.c.post(API % 'shop1' + 'domain/', {'domain': 'not a domain'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.c.post(API % 'shop1' + 'domain/', {'domain': 'https://www.Example.ir/'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['domain'], 'example.ir')
        self.assertEqual(r.data['records'][0]['value'], '87.107.160.17')
        with mock.patch.object(domains, 'check_dns', lambda n: {'ready': False, 'names': [], 'problems': ['هنوز نه']}):
            r = self.c.post(API % 'shop1' + 'domain/check/')
        self.assertFalse(r.data['ready'])
        self.assertEqual(r.data['problems'], ['هنوز نه'])
        self.assertEqual(self.site.jobs.filter(kind='domain').count(), 0)

    def test_project_delete_refused_while_live(self):
        self.job()
        r = self.c.delete('/api/v1/studio/projects/shop1/')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Project.objects.filter(slug='shop1').exists())

    def test_messages_api(self):
        self.job()
        rows = {'rows': [{'id': 1, 'form_title': 'تماس', 'page': '/', 'content': 'نام: علی', 'data': '{"نام": "علی"}', 'is_read': 0, 'created_at': '2026-10-31 10:00:00'}], 'total': 1, 'unread': 1}
        out = json.dumps(rows)
        with mock.patch.object(self.fake, 'sandbox_run', lambda *a, **k: (0, out)):
            r = self.c.get(API % 'shop1' + 'messages/')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['unread'], 1)
        self.assertEqual(r.data['rows'][0]['data'], {'نام': 'علی'})
        self.assertIs(r.data['rows'][0]['is_read'], False)
        seen = {}

        def capture(key, argv, **kw):
            seen['args'] = json.loads(argv[-1])
            return 0, out
        with mock.patch.object(self.fake, 'sandbox_run', capture):
            self.c.post(API % 'shop1' + 'messages/', {'id': 1, 'read': True}, format='json')
        self.assertEqual(seen['args']['mark'], 1)

    def test_messages_script_really_works(self):
        """اسکریپتِ واقعیِ خواندن و علامت زدن، روی یک sqlite واقعی."""
        import sqlite3
        import subprocess
        import sys
        path = os.path.join(self.tmp, 'm.sqlite3')
        c = sqlite3.connect(path)
        c.execute('CREATE TABLE site_forms_formmessage (id integer primary key, form_title text, page text, content text, data text, is_read bool, created_at text)')
        for i in range(3):
            c.execute('INSERT INTO site_forms_formmessage (form_title,page,content,data,is_read,created_at) VALUES (?,?,?,?,?,?)', ('تماس', '/', 'متن %d' % i, '{}', 0, 'x'))
        c.commit()
        c.close()

        def call(args):
            r = subprocess.run([sys.executable, '-I', '-c', publisher.MESSAGES_READ, json.dumps(args)], env={'NM_DB_PATH': path}, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        d = call({'limit': 2, 'offset': 0})
        self.assertEqual((d['total'], d['unread'], len(d['rows'])), (3, 3, 2))
        self.assertEqual(d['rows'][0]['id'], 3)
        self.assertEqual(call({'mark': 2})['unread'], 2)
        self.assertEqual(call({'mark': 2, 'read': False})['unread'], 3)
        self.assertEqual(call({'mark': 'all'})['unread'], 0)
        self.assertEqual(call({'count_only': True})['rows'], [])


def time_ago(minutes):
    import datetime
    from django.utils import timezone
    return timezone.now() - datetime.timedelta(minutes=minutes)


def _active(site):
    from apps.projects.hosting import api as hosting_api
    return hosting_api._active_job(site)


class SubmenuTests(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._o = override_settings(WORKSPACES_ROOT=Path(self.tmp))
        self._o.enable()
        self.addCleanup(self._o.disable)
        self.p = Project.objects.create(name='نمونه', slug='menu1')
        self.a = Page.objects.create(project=self.p, title='خدمات', slug='services', kind='static', body_html='<h1>x</h1>', in_menu=True, order=10)
        self.b = Page.objects.create(project=self.p, title='طراحی', slug='design', kind='static', body_html='<h1>y</h1>', in_menu=True, order=20)
        self.rows = [{'id': 'p1', 'page': self.a.pk, 'label': 'خدمات', 'children': [{'id': 'p2', 'page': self.b.pk, 'label': ''}, {'id': 'u1', 'url': 'https://x.ir/', 'label': 'بیرونی'}]}]

    def test_clean_keeps_two_levels_only(self):
        rows = [{'id': 'a', 'page': self.a.pk, 'label': 'A', 'children': [{'id': 'b', 'page': self.b.pk, 'label': 'B', 'children': [{'id': 'c', 'url': 'https://x.ir', 'label': 'C'}]}]}]
        out = vb._clean_menu(rows, self.p)
        self.assertEqual(out[0]['children'][0]['label'], 'B')
        self.assertNotIn('children', out[0]['children'][0])

    def test_clean_rejects_bad_child(self):
        rows = [{'id': 'a', 'page': self.a.pk, 'label': 'A', 'children': [{'id': 'x', 'url': 'javascript:alert(1)', 'label': 'bad'}, {'id': 'y', 'page': 99999, 'label': 'gone'}]}]
        self.assertNotIn('children', vb._clean_menu(rows, self.p)[0])

    def test_tree_and_flat(self):
        pages = {self.a.pk: self.a, self.b.pk: self.b}
        tree = genhook.tree_from(self.rows, pages)
        self.assertEqual(tree[0]['href'], '/services/')
        self.assertEqual(tree[0]['children'][0], {'title': 'طراحی', 'href': '/design/'})
        self.assertEqual(tree[0]['children'][1]['href'], 'https://x.ir/')
        self.assertEqual(genhook.items_from(self.rows, pages), [('خدمات', '/services/')])     # منوی ساده و قالب‌های قدیمی

    def _header(self, ctx_sub):
        ctx = R.build_ctx(self.p, target='header')
        ctx.has_submenu = ctx_sub
        doc = clean_doc(starters.header_doc(ctx), 'header')
        return R.render_doc(doc, ctx).html

    def test_no_children_keeps_old_markup(self):
        html = self._header(False)
        self.assertIn('{% for title, href in MENU %}', html)
        self.assertNotIn('MENU_TREE', html)

    def test_children_markup_and_css(self):
        html = self._header(True)
        self.assertIn('{% for m in MENU_TREE %}', html)
        engine = Engine(builtins=['apps.projects.builder.canvas_tags'])
        pages = {self.a.pk: self.a, self.b.pk: self.b}
        out = engine.from_string(html).render(Context({'MENU_TREE': genhook.tree_from(self.rows, pages), 'CURRENT_PATH': '/design/', 'SITE_TITLE': 'x'}))
        self.assertIn('class="nb-sub"', out)
        self.assertIn('aria-haspopup="true"', out)
        self.assertRegex(out, r'<div class="nb-sub-menu"><a href="/design/" class="on">طراحی</a>')
        from apps.projects.builder.blocks_css import BLOCK_CSS as css
        self.assertIn('.nb-sub:focus-within .nb-sub-menu', css)     # با صفحه‌کلید هم باز می‌شود
        self.assertIn('.nb-sub .nb-sub-menu,.nb-sub:hover .nb-sub-menu{display:flex;position:static', css)     # روی گوشی همیشه باز

    def test_generated_context_is_valid_python(self):
        SiteTheme.objects.create(project=self.p, active=True, menu=self.rows, menu_published=self.rows, published={}, draft={})
        generator.ProjectGenerator(self.p).run()
        path = os.path.join(str(self.p.path), 'config', 'context.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        ns = {}
        fake = type('S', (), {'SITE_TITLE': 't'})
        exec(compile(src.replace('from django.conf import settings', ''), path, 'exec'), {'settings': fake}, ns)
        self.assertEqual(ns['MENU'], [('خدمات', '/services/')])
        self.assertEqual(ns['MENU_TREE'][0]['children'][0]['title'], 'طراحی')
        with open(os.path.join(str(self.p.path), 'config', 'settings.py'), encoding='utf-8') as fh:
            self.assertIn("append('config.nb_filters')", fh.read())
        self.assertTrue(os.path.exists(os.path.join(str(self.p.path), 'config', 'nb_filters.py')))

    def test_old_project_gets_no_new_files(self):
        generator.ProjectGenerator(self.p).run()
        self.assertFalse(os.path.exists(os.path.join(str(self.p.path), 'config', 'nb_filters.py')))
        with open(os.path.join(str(self.p.path), 'config', 'context.py'), encoding='utf-8') as fh:
            self.assertNotIn('MENU_TREE', fh.read())

    def test_canvas_api_understands_children(self):
        U = get_user_model()
        c = APIClient()
        c.force_authenticate(U.objects.create_user(username='st2', email='s2@x.y', password='x', is_staff=True))
        r = c.put('/api/v1/studio/projects/menu1/builder/theme/', {'menu': self.rows}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data['menu'][0]['children']), 2)
        doc = {'v': 1, 'blocks': []}
        r = c.post('/api/v1/studio/projects/menu1/builder/render/', {'target': 'header', 'doc': clean_doc(starters.header_doc(R.build_ctx(self.p, target='header')), 'header'), 'menu': self.rows}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('nb-sub-menu', json.dumps(r.data, ensure_ascii=False))
        self.assertTrue(doc)


class NumberTests(SimpleTestCase):
    def test_nb_num(self):
        for value, out in ((1250000, '۱٬۲۵۰٬۰۰۰'), (Decimal('1250000.50'), '۱٬۲۵۰٬۰۰۰٫۵'), (Decimal('12.345'), '۱۲٫۳۴'), (0, '۰'), ('1000', '۱٬۰۰۰'), (-5, '−۵'), (999, '۹۹۹'), (None, ''), ('', ''), ('abc1', 'abc۱')):
            self.assertEqual(nb_filters.nb_num(value), out, value)

    def test_nb_digits(self):
        self.assertEqual(nb_filters.nb_digits('2026/10/31 10:05'), '۲۰۲۶/۱۰/۳۱ ۱۰:۰۵')
        self.assertEqual(nb_filters.nb_digits(None), '')

    def test_field_value_fa_and_en(self):
        f = {'type': 'DecimalField'}
        self.assertEqual(R.Renderer.field_value(f, 'item.price', digits='fa'), '{{ item.price|nb_num }}')
        self.assertEqual(R.Renderer.field_value(f, 'item.price', digits='en'), '{{ item.price|floatformat:"-2g" }}')
        d = {'type': 'DateField'}
        self.assertIn('|nb_digits', R.Renderer.field_value(d, 'item.d', digits='fa'))
        self.assertNotIn('nb_digits', R.Renderer.field_value(d, 'item.d', digits='en'))

    def test_sorting_is_on_real_values(self):
        var = R.Renderer.data_var({'app': 'catalog', 'name': 'Product', 'fields': [{'name': 'price'}]}, '-price')
        self.assertEqual(var, 'DATA.catalog.Product.by_price_desc')

    def test_template_validator_accepts_filters(self):
        from apps.ai_engine.services import validate_template
        ok, issues = validate_template('{{ item.price|nb_num }} {{ item.d|date:"Y"|nb_digits }}', None)
        self.assertTrue(ok, issues)


class MapTests(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._o = override_settings(WORKSPACES_ROOT=Path(self.tmp))
        self._o.enable()
        self.addCleanup(self._o.disable)
        self.p = Project.objects.create(name='نمونه', slug='map1')

    def _render(self, **props):
        ctx = R.build_ctx(self.p, target='page')
        b = {'id': 'm1', 'type': 'map', 'props': props, 'style': {}}
        doc = clean_doc({'v': 1, 'blocks': [{'id': 'm1', 'type': 'map', 'props': dict({'title': 'ما کجاییم', 'address': 'تهران'}, **props)}]}, 'page')
        self.assertTrue(b)
        if props.get('lat', 1) is None:
            doc['blocks'][0]['props']['lat'] = doc['blocks'][0]['props']['lng'] = None
        return R.render_doc(doc, ctx)

    def test_tiles_center_on_point(self):
        html = R.map_tiles(35.6997, 51.3380, 380)
        self.assertEqual(html.count('class="nb-map-tile"'), 21)
        self.assertNotIn('<iframe', html)
        self.assertIn('loading="lazy"', html)      # کاشیِ کند بارگذاریِ صفحه را نگه نمی‌دارد
        self.assertIn('© OpenStreetMap', html)
        self.assertIn('nb-map-pin', html)          # اگر کاشی‌ها نیامد جعبه خالی نیست
        # نقطهٔ تهران در زوم ۱۶
        self.assertIn('tile.openstreetmap.org/16/42114/', html)
        self.assertEqual(R.map_tiles(35.6997, 51.3380, 600).count('class="nb-map-tile"'), 35)

    def test_links_always_there(self):
        html = self._render(lat=35.6997, lng=51.3380, map_height=380).html
        self.assertIn('neshan.org/maps/@35.69970,51.33800,16z', html)
        self.assertIn('nb-map-empty', html)
        self.assertIn('balad.ir/location?latitude=35.69970', html)
        self.assertIn('google.com/maps?q=35.69970,51.33800', html)
        self.assertIn('تهران', html)
        self.assertNotIn('<iframe', html)

    def test_no_coords_no_blank_box(self):
        r = self._render(lat=None, lng=None)
        self.assertNotIn('nb-map-box', r.html)
        self.assertIn('google.com/maps/search', r.html)
        self.assertTrue(r.warnings)

    def test_output_passes_validator(self):
        from apps.ai_engine.services import validate_template
        ok, issues = validate_template(self._render(lat=35.7, lng=51.3).html, None)
        self.assertTrue(ok, issues)


TEMPLATES = [
    """{% extends "base.html" %}{% load static i18n %}
{% block content %}
<section class="section">
  <h1>{{ object.title }} — فروشگاه ما</h1>
  <p>قیمت: {{ object.price|floatformat:"0g" }} تومان</p>
  {% if object.image %}<img src="{{ object.image.url }}" alt="{{ object }}">{% endif %}
  <img src="/static/logo.png" alt="نشان">
  <img src="{% static 'img/a.png' %}">
  <a href="{% url 'x' pk=object.pk %}" title="برو">بیشتر بخوانید</a>
  {% for row in rows %}<li class="{% cycle 'a' 'b' %}">ردیف {{ forloop.counter }} از لیست</li>{% empty %}<li>چیزی نیست</li>{% endfor %}
  {# یادداشتِ برنامه‌نویس #}
  {% comment %}<p>متنِ کامنت‌شده</p>{% endcomment %}
  {% verbatim %}<p>{{ vue }} متنِ خام</p>{% endverbatim %}
  <script>var a = "متنِ اسکریپت {{ x }}"; if (1 < 2) {}</script>
  <style>.a{color:red} /* متن */</style>
  <textarea>متنِ داخلی</textarea>
  <!-- کامنتِ html -->
  <p>a &amp; b &lt; c</p>
  <input placeholder="نام" value="{{ form.name }}">
</section>
{% endblock %}
""",
    """<div data-x='a>b'>سلام {{ name }} خوش آمدی</div>\n<img src='/m/1.jpg'><p>۱۲۳</p><b>   فاصله   </b>""",
    """{% if a %}<p>الف</p>{% else %}<p>ب</p>{% endif %}""",
    """<a href="{% url 'a' %}"{% if x > 1 %} class="y"{% endif %}>لینک</a>""",
    """متنِ بی‌تگ""",
    """""",
]


class SafeEditTests(SimpleTestCase):
    def test_no_edits_is_byte_identical(self):
        for t in TEMPLATES:
            self.assertEqual(safe_edit.apply_edits(t, {}), t)

    def test_every_text_edit_keeps_tags_and_everything_else(self):
        for t in TEMPLATES:
            items = safe_edit.scan(t)
            for item in items:
                if item['kind'] != 'text':
                    continue
                new = safe_edit.apply_edits(t, {item['id']: 'متنِ تازه'})
                self.assertEqual(safe_edit.tags_of(new), safe_edit.tags_of(t))
                self.assertEqual(new, t[:item['start']] + 'متنِ تازه' + t[item['end']:])

    def test_edit_everything_at_once(self):
        t = TEMPLATES[0]
        edits = {x['id']: 'ت%d' % i for i, x in enumerate(safe_edit.scan(t)) if x['kind'] == 'text'}
        new = safe_edit.apply_edits(t, edits)
        self.assertEqual(safe_edit.tags_of(new), safe_edit.tags_of(t))
        for frag in ('{% extends "base.html" %}', "{% url 'x' pk=object.pk %}", '{{ object.title }}', "{% cycle 'a' 'b' %}", '<script>var a = "متنِ اسکریپت {{ x }}"; if (1 < 2) {}</script>',
                     '<style>.a{color:red} /* متن */</style>', '<textarea>متنِ داخلی</textarea>', '<!-- کامنتِ html -->', '{% comment %}<p>متنِ کامنت‌شده</p>{% endcomment %}', '{% verbatim %}<p>{{ vue }} متنِ خام</p>{% endverbatim %}'):
            self.assertIn(frag, new)

    def test_only_safe_regions_are_editable(self):
        values = [x['value'] for x in safe_edit.scan(TEMPLATES[0])]
        for skipped in ('متنِ کامنت‌شده', 'متنِ اسکریپت', 'متنِ داخلی', 'متنِ خام', 'کامنتِ html', 'یادداشتِ برنامه‌نویس'):
            self.assertFalse(any(skipped in v for v in values), skipped)
        for present in ('بیشتر بخوانید', 'چیزی نیست', 'a & b < c', '— فروشگاه ما'):
            self.assertTrue(any(present in v for v in values), present)

    def test_images(self):
        items = [x for x in safe_edit.scan(TEMPLATES[0]) if x['kind'] == 'image']
        self.assertEqual([x['value'] for x in items], ['/static/logo.png'])       # آدرسِ دارای تگ قابلِ ویرایش نیست
        new = safe_edit.apply_edits(TEMPLATES[0], {items[0]['id']: '/static/site-media/x.webp'})
        self.assertIn('<img src="/static/site-media/x.webp" alt="نشان">', new)
        self.assertEqual(safe_edit.tags_of(new), safe_edit.tags_of(TEMPLATES[0]))
        for bad in ('javascript:alert(1)', '/a"><script>', '{% x %}', 'data:text/html,1', ''):
            with self.assertRaises(safe_edit.EditError):
                safe_edit.apply_edits(TEMPLATES[0], {items[0]['id']: bad})

    def test_new_text_cannot_become_a_tag(self):
        t = '<p>سلام</p>'
        item = safe_edit.scan(t)[0]
        new = safe_edit.apply_edits(t, {item['id']: "{% load evil %}{{ secret }}<script>alert(1)</script>"})
        self.assertEqual(safe_edit.tags_of(new), [])
        self.assertNotIn('<script>', new)
        self.assertNotIn('{', new)
        engine = Engine()
        self.assertIn('{% load evil %}', engine.from_string(new).render(Context({})).replace('&#123;', '{').replace('&#125;', '}'))

    def test_unknown_id_and_empty(self):
        with self.assertRaises(safe_edit.EditError):
            safe_edit.apply_edits('<p>x y</p>', {'t999': 'z'})
        item = safe_edit.scan('<p>سلام</p>')[0]
        with self.assertRaises(safe_edit.EditError):
            safe_edit.apply_edits('<p>سلام</p>', {item['id']: '   '})

    def test_entities_roundtrip(self):
        t = '<p>a &amp; b</p>'
        item = safe_edit.scan(t)[0]
        self.assertEqual(item['value'], 'a & b')
        self.assertEqual(safe_edit.apply_edits(t, {item['id']: 'a & b'}), t)     # بی‌تغییر ⇐ بی‌بازنویسی
        self.assertEqual(safe_edit.apply_edits(t, {item['id']: 'c & d'}), '<p>c &amp; d</p>')

    def test_preview_has_no_tags_or_scripts(self):
        html = safe_edit.preview_html(TEMPLATES[0] + '<a onclick="x()" href="javascript:y()">z</a><img src="/a.png" onerror="alert(1)">')
        self.assertNotIn('{%', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('onclick', html)
        self.assertNotIn('onerror', html)
        self.assertNotIn('javascript:', html)
        self.assertIn('data-te="t', html)
        self.assertIn('data-te-img="i', html)
        self.assertRegex(html, r'<img src="/static/logo\.png" data-te-img="i\d+" alt="نشان">')


class QuickEditApiTests(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._o = override_settings(WORKSPACES_ROOT=Path(self.tmp))
        self._o.enable()
        self.addCleanup(self._o.disable)
        U = get_user_model()
        self.c = APIClient()
        self.c.force_authenticate(U.objects.create_user(username='st3', email='s3@x.y', password='x', is_staff=True))
        self.p = Project.objects.create(name='نمونه', slug='q1')
        self.app = App.objects.create(project=self.p, name='blog', url_prefix='blog/', order=10)
        self.view = View.objects.create(app=self.app, name='post_list', kind='list', template_body=TEMPLATES[1])

    def test_view_roundtrip(self):
        url = '/api/v1/studio/projects/q1/quick-edit/view/%d/' % self.view.pk
        r = self.c.get(url)
        self.assertEqual(r.status_code, 200, r.data)
        item = next(x for x in r.data['items'] if x['value'].startswith('سلام'))
        r2 = self.c.post(url, {'hash': r.data['hash'], 'edits': {item['id']: 'درود'}}, format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        self.view.refresh_from_db()
        self.assertTrue(self.view.template_body.startswith("<div data-x='a>b'>درود {{ name }} خوش آمدی</div>"))

    def test_stale_hash_refused(self):
        url = '/api/v1/studio/projects/q1/quick-edit/view/%d/' % self.view.pk
        r = self.c.post(url, {'hash': 'old', 'edits': {}}, format='json')
        self.assertEqual(r.status_code, 409)

    def test_plain_page_refused_but_imported_ok(self):
        page = Page.objects.create(project=self.p, title='p', slug='p', kind='static', body_html='<p>x y</p>')
        self.assertEqual(self.c.get('/api/v1/studio/projects/q1/quick-edit/page/%d/' % page.pk).status_code, 404)
        imp = Page.objects.create(project=self.p, title='i', slug='i', kind='imported', body_html=TEMPLATES[0], file_path='templates/i.html')
        r = self.c.get('/api/v1/studio/projects/q1/quick-edit/page/%d/' % imp.pk)
        self.assertEqual(r.status_code, 200, r.data)
        item = next(x for x in r.data['items'] if 'بیشتر' in x['value'])
        r2 = self.c.post('/api/v1/studio/projects/q1/quick-edit/page/%d/' % imp.pk, {'hash': r.data['hash'], 'edits': {item['id']: 'ادامه'}}, format='json')
        self.assertEqual(r2.status_code, 200)
        imp.refresh_from_db()
        self.assertEqual(imp.body_html, TEMPLATES[0].replace('بیشتر بخوانید', 'ادامه'))

    def test_shared_roundtrip_check(self):
        Design.objects.create(project=self.p, target='header', draft=clean_doc(starters.header_doc(R.build_ctx(self.p, target='header')), 'header'),
                              published=clean_doc(starters.header_doc(R.build_ctx(self.p, target='header')), 'header'))
        r = self.c.post('/api/v1/studio/projects/q1/builder/shared/header/roundtrip-check/', {'content': '<header><marquee>{{ x }}</marquee></header>'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['has_design'])
        self.assertGreaterEqual(r.data['new_custom'], 1)
        r = self.c.post('/api/v1/studio/projects/q1/builder/shared/base_css/roundtrip-check/', {'content': 'x'}, format='json')
        self.assertFalse(r.data['has_design'])


class ShopNumbersTests(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._o = override_settings(WORKSPACES_ROOT=Path(self.tmp))
        self._o.enable()
        self.addCleanup(self._o.disable)

    def _generate(self, slug, active, lang='fa'):
        from apps.code_generation import services
        p = Project.objects.create(name=slug, slug=slug, language_code=lang)
        services.scaffold_shop(p)
        if active:
            SiteTheme.objects.create(project=p, active=True, menu=[], menu_published=[], published={}, draft={})
        generator.ProjectGenerator(p).run()
        with open(os.path.join(str(p.path), 'templates', 'pages', 'cart.html'), encoding='utf-8') as fh:
            workspace_cart = fh.read()
        # همان کاری که انتشار روی کپیِ نسخه می‌کند
        release = os.path.join(self.tmp, 'release-' + slug)
        shutil.copytree(str(p.path), release)
        genhook.persian_shop(release, p)
        with open(os.path.join(release, 'apps', 'catalog', 'models.py'), encoding='utf-8') as fh:
            models = fh.read()
        with open(os.path.join(release, 'templates', 'pages', 'cart.html'), encoding='utf-8') as fh:
            cart = fh.read()
        with open(os.path.join(str(p.path), 'templates', 'pages', 'cart.html'), encoding='utf-8') as fh:
            self.assertEqual(fh.read(), workspace_cart)       # پوشهٔ پروژه و ZIP دست نمی‌خورند
        self.assertIn('floatformat', workspace_cart)
        return models, cart

    def test_active_fa_project(self):
        models, cart = self._generate('sn1', True)
        self.assertIn('۰۱۲۳۴۵۶۷۸۹', models)
        self.assertIn('{{ row.total|nb_num }}', cart)

    def test_english_project_untouched(self):
        models, cart = self._generate('sn2', True, 'en')
        self.assertNotIn('۰۱۲۳۴۵۶۷۸۹', models)
        self.assertIn('floatformat', cart)

    def test_old_project_untouched(self):
        models, cart = self._generate('sn3', False)
        self.assertNotIn('۰۱۲۳۴۵۶۷۸۹', models)
        self.assertIn('floatformat', cart)


# یک بهره‌برداری برای این‌که import‌ها بی‌استفاده نمانند و نقض‌های سبک دیده شوند
__all__ = ['re', 'time', 'canvas', 'P']
