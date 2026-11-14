# -*- coding: utf-8 -*-
"""کارگرِ رندر مثلِ یک بازدیدکنندهٔ ناشناس سقف می‌خورد (۳۰ در دقیقه): «finish»ِ رندرِ تمام‌شده 429 گرفت و کار دوباره اجرا شد (۲۰۲۶-۱۱-۱۴).
این‌جا: سقف برای کارگر برداشته شده؛ «finish» بی‌توان است؛ کلاینت 429/502/503/504 را با Retry-After دوباره می‌فرستد؛ و پایانِ نرسیده نگه داشته می‌شود
(کارِ تمام‌شده شکستِ‌خورده حساب نمی‌شود و تا رسیدنِ پایان کارِ تازه‌ای گرفته نمی‌شود)."""
import json
import os
import shutil
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from up3d import client as UC, worker as UW
from up3d.client import ApiClient, ApiError

from . import api as A, services as SV
from .models import Job, Project, Worker


class WorkerThrottleTests(SimpleTestCase):
    def test_worker_views_are_exempt_even_when_anonymous_throttling_is_on(self):
        """سقفِ «ناشناس» را روشن می‌کنیم و می‌بینیم یک نقطهٔ پایانیِ معمولی بعد از ۳۰ تا 429 می‌دهد ولی کارگر نه."""
        fac = APIRequestFactory()
        with mock.patch.object(APIView, 'throttle_classes', [AnonRateThrottle]), \
                mock.patch.object(AnonRateThrottle, 'THROTTLE_RATES', {'anon': '30/minute'}), \
                mock.patch.object(AnonRateThrottle, 'cache', LocMemCache('s3d-throttle', {})):
            @api_view(['GET'])
            @permission_classes([permissions.AllowAny])
            def control(request):
                return Response({'ok': True})

            @A.worker_api
            def worker(request):
                return Response({'ok': True})

            # worker_api بی‌توکن 401/403 می‌دهد، نه 429؛ برای سنجش با توکنِ درست می‌خواهیم
            w = mock.Mock(last_seen=None)
            with mock.patch.object(A.Worker.objects, 'filter') as flt:
                flt.return_value.first.return_value = w
                w.save = mock.Mock()
                codes_control = [control(fac.get('/x')).status_code for _ in range(40)]
                codes_worker = [worker(fac.get('/y', HTTP_AUTHORIZATION='Worker tok')).status_code for _ in range(100)]
        self.assertIn(429, codes_control, 'خودِ سقف باید در این آزمون فعال باشد')
        self.assertEqual(set(codes_worker), {200}, 'کارگر ۱۰۰ درخواست در دقیقه می‌زند و هیچ‌کدام نباید 429 شود')

    def test_every_worker_endpoint_has_no_throttle(self):
        for name in ('w_heartbeat', 'w_claim', 'w_package', 'w_progress', 'w_upload', 'w_finish', 'w_bundle'):
            self.assertEqual(getattr(A, name).cls.throttle_classes, [], name)


class FinishIdempotentTests(TestCase):
    def setUp(self):
        self.w = Worker.objects.create(name='gpu-t', token='tok-s3d', enabled=True, last_seen=timezone.now())
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION='Worker tok-s3d')
        self.job = Job.objects.create(kind='render', profile='preview', owner='worker', state='RENDERING', worker=self.w)

    def finish(self, body=None):
        return self.c.post('/3d/api/worker/jobs/%d/finish/' % self.job.pk, body or {'ok': True, 'seconds': 3}, format='json')

    def test_finishing_twice_changes_nothing_the_second_time(self):
        r1 = self.finish()
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertFalse(r1.json()['already'])
        self.job.refresh_from_db()
        self.w.refresh_from_db()
        self.assertEqual((self.job.state, self.job.owner, self.w.jobs_done), ('QUALITY_CHECK', 'panel', 1))
        r2 = self.finish()
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()['already'])
        self.job.refresh_from_db()
        self.w.refresh_from_db()
        self.assertEqual((self.job.state, self.w.jobs_done), ('QUALITY_CHECK', 1), 'بارِ دوم نباید آمارِ کارگر را دوبار بشمارد')

    def test_a_late_failure_does_not_resurrect_or_break_a_finished_job(self):
        self.finish()
        r = self.finish({'ok': False, 'error': 'late'})
        self.assertTrue(r.json()['already'])
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'QUALITY_CHECK')
        done = Job.objects.create(kind='render', profile='preview', owner='panel', state='COMPLETED', worker=self.w)
        self.assertFalse(SV.worker_finish(done, self.w, False, 'x'))
        done.refresh_from_db()
        self.assertEqual(done.state, 'COMPLETED')

    def test_failure_of_a_running_job_is_still_recorded_once(self):
        r = self.finish({'ok': False, 'error': 'boom'})
        self.assertFalse(r.json()['already'])
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'FAILED')
        self.assertTrue(self.finish({'ok': False, 'error': 'boom'}).json()['already'])

    def test_a_job_that_belongs_to_another_worker_is_still_refused(self):
        other = Worker.objects.create(name='other', token='tok-other', enabled=True)
        self.job.worker = other
        self.job.save()
        self.assertEqual(self.finish().status_code, 403)


class _Handler(BaseHTTPRequestHandler):
    script = []          # [(status, headers)] ؛ هر درخواست یکی را می‌خورد؛ بعد از تمام‌شدن 200
    seen = []

    def _go(self):
        _Handler.seen.append((self.command, self.path))
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        status, headers = _Handler.script.pop(0) if _Handler.script else (200, {})
        body = json.dumps({'ok': status == 200}).encode()
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _go

    def log_message(self, *a):
        pass


class ClientRetryTests(SimpleTestCase):
    def setUp(self):
        _Handler.script, _Handler.seen = [], []
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.api = ApiClient('http://127.0.0.1:%d' % self.srv.server_address[1], 'tok', scheme='Worker')
        self.sleeps = []
        self.api.sleep = self.sleeps.append

    def test_429_then_200_is_retried_and_honours_retry_after(self):
        _Handler.script = [(429, {'Retry-After': '3'}), (429, {'Retry-After': '7'})]
        self.assertEqual(self.api.post('/api/worker/jobs/1/finish/', {'ok': True}), {'ok': True})
        self.assertEqual(self.sleeps, [3, 7])
        self.assertEqual(len(_Handler.seen), 3)

    def test_retry_after_is_capped_and_gateway_errors_retry_with_backoff(self):
        _Handler.script = [(502, {}), (503, {'Retry-After': '9999'}), (504, {})]
        self.api.get('/x')
        self.assertEqual(self.sleeps, [UC.RETRY_DELAYS[0], UC.RETRY_AFTER_MAX, UC.RETRY_DELAYS[2]])

    def test_gives_up_after_the_last_retry_with_a_typed_error(self):
        _Handler.script = [(429, {})] * 10
        with self.assertRaises(ApiError) as cm:
            self.api.post('/x', {})
        self.assertEqual(cm.exception.status, 429)
        self.assertFalse(cm.exception.permanent, '۴۲۹ دائمی نیست؛ بعداً دوباره امتحان می‌شود')
        self.assertEqual(len(_Handler.seen), len(UC.RETRY_DELAYS) + 1)

    def test_client_errors_are_not_retried(self):
        for code in (400, 403, 404):
            _Handler.script, _Handler.seen = [(code, {})], []
            with self.assertRaises(ApiError) as cm:
                self.api.get('/x')
            self.assertEqual((cm.exception.status, cm.exception.permanent, len(_Handler.seen)), (code, True, 1))
        self.assertEqual(self.sleeps, [])

    def test_unreachable_server_is_retried_but_a_timeout_is_not(self):
        dead = ApiClient('http://127.0.0.1:1', 'tok')
        dead.sleep = self.sleeps.append
        with self.assertRaises(ApiError):
            dead.get('/x', retries=2)
        self.assertEqual(len(self.sleeps), 2)
        import socket
        import urllib.error
        self.sleeps.clear()
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError(socket.timeout('t'))):
            with self.assertRaises(ApiError):
                self.api.post('/x', {})
        self.assertEqual(self.sleeps, [], 'زمان‌گذشتن یعنی شاید سرور کار را کرده؛ نباید دوباره بفرستد')

    def test_download_still_gives_up_at_once_on_a_real_4xx(self):
        _Handler.script = [(404, {})]
        with self.assertRaises(ApiError):
            self.api.download('/x', os.path.join(tempfile.gettempdir(), 's3d-dl-never'), attempts=3)
        self.assertEqual(len(_Handler.seen), 1)


class _FakeApi:
    def __init__(self):
        self.down = True
        self.calls = []
        self.status = 503

    def post(self, path, data=None, **kw):
        self.calls.append((path, data))
        if path.endswith('/finish/') and self.down:
            raise ApiError('POST %s ⇐ %d' % (path, self.status), status=self.status)
        return {'ok': True}

    def get(self, path, **kw):
        return {}

    def download(self, path, dest, **kw):
        with zipfile.ZipFile(dest, 'w') as z:
            z.writestr('compiled.json', json.dumps({'profile': {}}))
        return dest

    def upload(self, path, files, **kw):
        self.calls.append((path, sorted(files)))
        return {'ok': True}


class PendingFinishTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='s3d-w-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.api = _FakeApi()
        self.w = self.worker()

    def worker(self):
        w = UW.Worker('http://x', 't', work_dir=self.tmp, log=lambda *a: None)
        w.api = self.api
        w.caps = {'name': 'x'}
        return w

    def finishes(self):
        return [d for p, d in self.api.calls if p.endswith('/finish/')]

    def test_a_finished_render_is_not_failed_nor_rerun_when_finish_cannot_be_delivered(self):
        with mock.patch.object(UW.pipeline, 'render', lambda *a, **k: None), mock.patch.object(UW.Worker, '_gpu_policy', lambda *a: None):
            self.w.run_job({'id': 7, 'kind': 'render', 'profile': 'preview'})
        self.assertTrue(self.w.last['ok'])
        self.assertTrue(self.w.last['pending_finish'])
        self.assertTrue(all(d['ok'] for d in self.finishes()), 'شکستِ ارسال نباید «کار ناموفق» گزارش شود')
        self.assertIn('7', self.w._pending)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'pending-finish.json')))

    def test_pending_finish_survives_a_worker_restart_and_is_sent_once_the_panel_is_back(self):
        self.assertFalse(self.w.send_finish(9, {'ok': True, 'seconds': 1.5}))
        again = self.worker()
        self.assertEqual(again._pending, {'9': {'ok': True, 'seconds': 1.5}})
        self.assertFalse(again.flush_pending())
        self.api.down = False
        self.assertTrue(again.flush_pending())
        self.assertEqual(again._pending, {})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'pending-finish.json')))
        self.assertEqual(self.finishes()[-1], {'ok': True, 'seconds': 1.5})

    def test_a_permanent_refusal_is_dropped_not_retried_forever(self):
        self.api.status = 403
        self.assertTrue(self.w.send_finish(11, {'ok': True}))
        self.assertEqual(self.w._pending, {})

    def test_loop_does_not_claim_new_work_while_a_finish_is_pending(self):
        self.w.send_finish(13, {'ok': True})
        claims = []
        orig = self.api.post
        self.api.post = lambda path, data=None, **kw: (claims.append(path) if path.endswith('/claim/') else None) or orig(path, data, **kw)

        class Stop(Exception):
            pass

        def stop(_s):
            raise Stop()
        with mock.patch.object(UW.time, 'sleep', stop):
            with self.assertRaises(Stop):
                self.w.loop()
        self.assertEqual(claims, [], 'تا پایانِ کارِ قبلی نرسیده کارِ تازه نگیر؛ وگرنه پنل همان کار را دوباره می‌دهد')
