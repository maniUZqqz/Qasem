# -*- coding: utf-8 -*-
"""مورد ۷ — سرورِ هوش مصنوعیِ بی‌آی‌پی (شنونده).

دو باگی که مالک صریحاً گفت نباید پیش بیاید، این‌جا قفل می‌شوند:
  ۱) سایت تا ابد منتظرِ سرورِ خاموش نماند و درخواستِ کاربر گم نشود.
  ۲) یک درخواست به دو ارائه‌دهنده نرود و دو هزینه نشود.
"""
from unittest import mock

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from app.models import AIJob, APIConfig


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


KEY = 'worker-secret-key-123456'


class ListenerBridgeTests(APITestCase):
    def setUp(self):
        APIConfig.objects.all().delete()
        self.listener = APIConfig.objects.create(
            name='سرورِ خودم', provider_type=APIConfig.TYPE_LISTENER,
            base_url='http://unused.local', api_key=KEY, model_name='local-model',
            priority=1, is_active=True, timeout_seconds=12,
            listener_online_window=90,
        )

    def _h(self, key=KEY):
        return {'HTTP_X_WORKER_KEY': key}

    # ───────────────────────── احراز و ضربانِ قلب ─────────────────────────
    def test_wrong_key_is_rejected(self):
        res = self.client.post(url('ai-bridge-claim'), {}, format='json',
                               **self._h('bad-key'))
        self.assertEqual(res.status_code, 401)

    def test_heartbeat_marks_online(self):
        self.assertFalse(self.listener.listener_is_online())
        res = self.client.post(url('ai-bridge-heartbeat'), {'worker': 'pc-1'},
                               format='json', **self._h())
        self.assertEqual(res.status_code, 200, res.data)
        self.listener.refresh_from_db()
        self.assertTrue(self.listener.listener_is_online())
        self.assertEqual(self.listener.listener_worker_name, 'pc-1')

    def test_claim_returns_204_when_no_job(self):
        res = self.client.post(url('ai-bridge-claim'), {'worker': 'pc-1'},
                               format='json', **self._h())
        self.assertEqual(res.status_code, 204)

    # ───────────────────── باگ ۱: منتظرِ سرورِ خاموش نماند ─────────────────────
    def test_offline_listener_fails_fast(self):
        """شنوندهٔ خاموش ⇒ همان لحظه استثنا، بی‌ساختنِ کار و بی‌معطلی."""
        from app.ai_bridge import run_via_listener
        with self.assertRaises(RuntimeError):
            run_via_listener(self.listener, [{'role': 'user', 'content': 'سلام'}], 100)
        self.assertEqual(AIJob.objects.count(), 0, 'برای سرورِ خاموش کار ساخته نشود')

    def test_timeout_expires_job_and_raises(self):
        """روشن ولی بی‌جواب ⇒ مهلت تمام، کار expired، و زنجیره می‌رود سرِ بعدی."""
        from app.ai_bridge import run_via_listener
        self.listener.mark_listener_seen('pc-1')
        self.listener.timeout_seconds = 10      # کمینهٔ کد ۱۰ ثانیه است
        self.listener.save(update_fields=['timeout_seconds'])
        with self.assertRaises(TimeoutError):
            run_via_listener(self.listener, [{'role': 'user', 'content': 'سلام'}], 100)
        job = AIJob.objects.get()
        self.assertEqual(job.status, AIJob.STATUS_EXPIRED)
        self.assertIn('مهلت', job.error)

    # ───────────────── باگ ۲: دو جواب / دو هزینه برای یک درخواست ─────────────────
    def test_late_result_is_discarded(self):
        """جوابی که پس از پایانِ مهلت برسد، پذیرفته نمی‌شود."""
        job = AIJob.objects.create(provider=self.listener, payload={'messages': []},
                                   status=AIJob.STATUS_EXPIRED)
        res = self.client.post(url('ai-bridge-result', job.id), {'text': 'جوابِ دیررس'},
                               format='json', **self._h())
        self.assertEqual(res.status_code, 409)
        job.refresh_from_db()
        self.assertEqual(job.status, AIJob.STATUS_EXPIRED)
        self.assertEqual(job.result, '', 'جوابِ دیررس نباید ذخیره شود')

    def test_job_is_leased_to_one_worker_only(self):
        """کار فقط یک بار برداشته می‌شود — وگرنه دو کارگر دو بار هزینه می‌دادند."""
        AIJob.objects.create(provider=self.listener, payload={'messages': []},
                             status=AIJob.STATUS_QUEUED)
        first = self.client.post(url('ai-bridge-claim'), {'worker': 'pc-1'},
                                 format='json', **self._h())
        second = self.client.post(url('ai-bridge-claim'), {'worker': 'pc-2'},
                                  format='json', **self._h())
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 204, 'کارِ اجاره‌شده نباید دوباره داده شود')

    # ───────────────────────── جریانِ کاملِ موفق ─────────────────────────
    # این دو آزمون به کلاسِ نخ‌دارِ پایین منتقل شده‌اند (نخِ دیگر باید داده را ببیند)
    def _moved_full_round_trip(self):
        from app.ai_bridge import run_via_listener
        self.listener.mark_listener_seen('pc-1')

        answers = {}

        def fake_worker():
            """کارگرِ جعلی: کار را برمی‌دارد و جواب می‌دهد."""
            claim = self.client.post(url('ai-bridge-claim'), {'worker': 'pc-1'},
                                     format='json', **self._h())
            answers['claim'] = claim.status_code
            if claim.status_code == 200:
                job_id = claim.data['job_id']
                answers['messages'] = claim.data['messages']
                res = self.client.post(url('ai-bridge-result', job_id),
                                       {'text': 'برنامهٔ ساختهٔ سرورِ خودم',
                                        'usage': {'prompt_tokens': 11,
                                                  'completion_tokens': 22}},
                                       format='json', **self._h())
                answers['result'] = res.status_code

        import threading
        timer = threading.Timer(1.5, fake_worker)
        timer.start()
        try:
            text, usage = run_via_listener(
                self.listener, [{'role': 'user', 'content': 'یک برنامه بده'}], 500)
        finally:
            timer.join(10)

        self.assertEqual(text, 'برنامهٔ ساختهٔ سرورِ خودم')
        self.assertEqual(usage['completion_tokens'], 22)
        self.assertEqual(answers.get('claim'), 200)
        self.assertEqual(answers.get('result'), 200)
        self.assertEqual(AIJob.objects.get().status, AIJob.STATUS_DONE)

    def _moved_worker_failure(self):
        from app.ai_bridge import run_via_listener
        self.listener.mark_listener_seen('pc-1')

        def fake_worker():
            claim = self.client.post(url('ai-bridge-claim'), {'worker': 'pc-1'},
                                     format='json', **self._h())
            if claim.status_code == 200:
                self.client.post(url('ai-bridge-fail', claim.data['job_id']),
                                 {'error': 'مدل بالا نیامد'}, format='json', **self._h())

        import threading
        timer = threading.Timer(1.2, fake_worker)
        timer.start()
        try:
            with self.assertRaises(RuntimeError):
                run_via_listener(self.listener, [{'role': 'user', 'content': 'x'}], 100)
        finally:
            timer.join(10)
        self.assertEqual(AIJob.objects.get().status, AIJob.STATUS_FAILED)

    # ───────────────── زنجیره: شنوندهٔ خاموش ⇒ ارائه‌دهندهٔ بعدی ─────────────────
    def test_chain_falls_through_to_cloud(self):
        """شنونده خاموش است؛ زنجیره باید بی‌معطلی سراغِ سرویسِ ابری برود."""
        APIConfig.objects.create(
            name='ابری', provider_type=APIConfig.TYPE_API,
            base_url='https://api.example.com/v1', api_key='k',
            model_name='gpt-x', priority=2, is_active=True,
        )

        fake = _FakeCloudResponse('جوابِ ابری')
        with mock.patch('ai_engine.ai_generator.build_client'), \
             mock.patch('ai_engine.ai_generator._complete_with_provider',
                        return_value=fake), \
             mock.patch('ai_engine.ai_generator.APIConfig.resolve_model',
                        create=True, return_value='gpt-x'):
            from ai_engine.ai_generator import call_model
            response, config = call_model([{'role': 'user', 'content': 'x'}], 100,
                                          temperature=None)
        self.assertEqual(response.choices[0].message.content, 'جوابِ ابری')
        self.assertEqual(AIJob.objects.count(), 0, 'برای شنوندهٔ خاموش کار ساخته نشود')


class _FakeCloudResponse:
    """پاسخِ جعلیِ سرویسِ ابری، به شکلِ پاسخِ OpenAI."""

    class _Msg:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _FakeCloudResponse._Msg(content)

    def __init__(self, content):
        self.choices = [self._Choice(content)]
        self.usage = None


class ListenerThreadedTests(TransactionTestCase):
    """آزمونِ جریانِ کامل — با نخِ جدا، پس تراکنشِ آزمون نباید داده را پنهان کند."""

    def setUp(self):
        self.client = APIClient()
        APIConfig.objects.all().delete()
        AIJob.objects.all().delete()
        self.listener = APIConfig.objects.create(
            name='سرورِ خودم', provider_type=APIConfig.TYPE_LISTENER,
            base_url='http://unused.local', api_key=KEY, model_name='local-model',
            priority=1, is_active=True, timeout_seconds=20,
            listener_online_window=90,
        )

    def _h(self):
        return {'HTTP_X_WORKER_KEY': KEY}

    def test_full_round_trip(self):
        from app.ai_bridge import run_via_listener
        self.listener.mark_listener_seen('pc-1')
        self.listener.refresh_from_db()
        seen = {}

        def worker():
            from django.db import connection
            try:
                claim = self.client.post(url('ai-bridge-claim'), {'worker': 'pc-1'},
                                         format='json', **self._h())
                seen['claim'] = claim.status_code
                if claim.status_code == 200:
                    res = self.client.post(url('ai-bridge-result', claim.data['job_id']),
                                           {'text': 'برنامهٔ سرورِ خودم',
                                            'usage': {'prompt_tokens': 11,
                                                      'completion_tokens': 22}},
                                           format='json', **self._h())
                    seen['result'] = res.status_code
            finally:
                connection.close()

        import threading
        timer = threading.Timer(1.5, worker)
        timer.start()
        try:
            text, usage = run_via_listener(
                self.listener, [{'role': 'user', 'content': 'یک برنامه بده'}], 500)
        finally:
            timer.join(25)

        self.assertEqual(text, 'برنامهٔ سرورِ خودم')
        self.assertEqual(usage['completion_tokens'], 22)
        self.assertEqual(seen.get('claim'), 200)
        self.assertEqual(seen.get('result'), 200)
        self.assertEqual(AIJob.objects.get().status, AIJob.STATUS_DONE)

    def test_worker_failure_moves_on(self):
        from app.ai_bridge import run_via_listener
        self.listener.mark_listener_seen('pc-1')

        def worker():
            from django.db import connection
            try:
                claim = self.client.post(url('ai-bridge-claim'), {'worker': 'pc-1'},
                                         format='json', **self._h())
                if claim.status_code == 200:
                    self.client.post(url('ai-bridge-fail', claim.data['job_id']),
                                     {'error': 'مدل بالا نیامد'}, format='json', **self._h())
            finally:
                connection.close()

        import threading
        timer = threading.Timer(1.2, worker)
        timer.start()
        try:
            with self.assertRaises(RuntimeError):
                run_via_listener(self.listener, [{'role': 'user', 'content': 'x'}], 100)
        finally:
            timer.join(25)
        self.assertEqual(AIJob.objects.get().status, AIJob.STATUS_FAILED)
