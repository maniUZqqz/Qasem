# -*- coding: utf-8 -*-
"""مسیریابیِ کارهای متن و کد: اول Qwen روی سرورِ پردازش، بعد Metis.

گرهٔ مالک خاموش است، پس گره این‌جا ساختگی است؛ ولی کارها از صفِ واقعیِ apps.compute می‌گذرند
(enqueue، claim، save_output، finish، wait). مسیرِ واقعی روی GPU آزموده نشده است.
"""
import io
import json
import tempfile
import shutil
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai_engine import providers as studio_providers
from apps.ai_engine.models import AiProposal, AiRouteLog, AiSettings
from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.projects.models import Project
from services.ai import gateway, routing

CODER = 'qwen3-coder:30b'


class FakeMetis:
    """جای OpenAICompatProvider"""
    model = 'gpt-4o-mini'

    def __init__(self):
        self.calls = []

    def select_models(self, candidates):
        return [self.model]

    def generate(self, prompt, *, model=None, **kw):       # همان امضای OpenAICompatProvider
        self.calls.append(('generate', model))
        return 'پاسخ از Metis'

    def generate_json(self, model, prompt, **kw):
        self.calls.append(('generate_json', model))
        return {'ok': 'metis'}, '{"ok":"metis"}'


class FakeNode:
    """رفتارِ عاملِ گره روی همان توابعی که API گره صدا می‌زند؛ به‌جای time.sleep ِ حلقهٔ انتظار اجرا می‌شود."""

    def __init__(self, node, behaviour='ok', answer='سلام از Qwen'):
        self.node = node
        self.behaviour = behaviour
        self.answer = answer
        self.jobs = []
        self.ticks = 0

    def __call__(self, _seconds):
        self.ticks += 1
        if self.behaviour == 'ignore':
            return
        job = compute.claim(self.node)
        if job is not None:
            self.jobs.append(job)
            self.node.last_seen = timezone.now()
            self.node.save(update_fields=['last_seen'])
            if self.behaviour == 'ok':
                body = {'model': job.payload.get('model'), 'response': self.answer, 'done': True, 'done_reason': 'stop'}
                compute.save_output(job, 'ollama.json', io.BytesIO(json.dumps(body, ensure_ascii=False).encode('utf-8')))
                compute.finish(job, self.node, True)
            elif self.behaviour == 'fail':
                compute.finish(job, self.node, False, error='model "qwen3-coder:30b" not found (404)')
            elif self.behaviour == 'die':
                type(self.node).objects.filter(pk=self.node.pk).update(last_seen=timezone.now() - timedelta(minutes=5))
            elif self.behaviour == 'hang':
                pass


@override_settings(AI_ROUTE_FORCE=True)
class Base(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._o = override_settings(NM_DATA_DIR=Path(self.tmp), AI_NODE_CLAIM_TIMEOUT=30, AI_NODE_RUN_TIMEOUT=30)
        self._o.enable()
        self.addCleanup(self._o.disable)
        AiSettings.objects.update_or_create(pk=1, defaults={'route_mode': 'qwen_first', 'provider': 'openai', 'api_key': 'k'})

    def node(self, models=(CODER,), online=True, ollama=True, startable=False, name='gpu-1'):
        caps = {'ollama': ollama}
        if models is not None:
            caps['ollama_models'] = list(models)
        if startable:
            caps['startable'] = {'ollama': True}
        return ComputeNode.objects.create(name=name, enabled=True, capabilities=caps, auto_switch=True,
                                          last_seen=timezone.now() if online else timezone.now() - timedelta(hours=3))

    def sleeping(self, fake):
        return mock.patch('apps.compute.services.time.sleep', fake)

    def routed(self, metis=None):
        return routing.RoutedTextProvider(metis, task='test')


class RealSignatureTests(Base):
    """جایگزینِ واقعی: امضای OpenAICompatProvider با generate ِ Ollama فرق دارد و نباید با mock پنهان شود."""

    def _prov(self):
        from services.ai.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(base_url='http://x/v1', api_key='k', model='gpt-4o-mini', timeout=5)

    def test_generate_with_real_signature(self):
        from services.ai.openai_compat import OpenAICompatProvider
        self.node(online=False)
        routed = self.routed(self._prov())
        with mock.patch.object(OpenAICompatProvider, 'generate', autospec=True, return_value='ok') as g:
            self.assertEqual(routed.generate(CODER, 'سلام', system='s', format_json=True, options={'temperature': 0.2, 'num_predict': 50}), 'ok')
            self.assertEqual(routed.generate('سلام', model='m'), 'ok')
        kw = g.call_args_list[0].kwargs
        self.assertEqual((kw['model'], kw['system'], kw['json_mode'], kw['temperature'], kw['num_predict']), ('gpt-4o-mini', 's', True, 0.2, 50))
        self.assertEqual(routed.answered_by, 'gpt-4o-mini')

    def test_generate_json_with_real_signature(self):
        from services.ai.openai_compat import OpenAICompatProvider
        self.node(online=False)
        routed = self.routed(self._prov())
        with mock.patch.object(OpenAICompatProvider, 'generate_json', autospec=True, return_value=({'a': 1}, '{}')) as g:
            self.assertEqual(routed.generate_json(CODER, 'x', system='s', images=None, options={'temperature': 0.1})[0], {'a': 1})
        self.assertEqual(g.call_args.args[1], 'gpt-4o-mini')

    def test_prompt_first_form_on_node(self):
        n = self.node()
        with self.sleeping(FakeNode(n)):
            self.assertEqual(self.routed(FakeMetis()).generate('سلام', model='qwq:32b', system='s', temperature=0.5), 'سلام از Qwen')


class NodeStateTests(Base):
    def test_no_node(self):
        s = routing.node_state()
        self.assertFalse(s['ready'])
        self.assertIn('ثبت نشده', s['reason'])

    def test_offline(self):
        self.node(online=False)
        s = routing.node_state()
        self.assertFalse(s['ready'])
        self.assertFalse(s['online'])
        self.assertIn('خاموش', s['reason'])
        self.assertTrue(s['has_model'])      # از آخرین باری که روشن بود

    def test_missing_model_no_silent_substitute(self):
        self.node(models=('qwq:32b', 'qwen3-vl:30b'))
        s = routing.node_state()
        self.assertFalse(s['ready'])
        self.assertTrue(s['online'])
        self.assertIs(s['has_model'], False)
        self.assertIn(CODER, s['reason'])
        self.assertEqual(s['known_models'], ['qwq:32b', 'qwen3-vl:30b'])

    def test_ready(self):
        self.node()
        s = routing.node_state()
        self.assertTrue(s['ready'])
        self.assertEqual(s['node'], 'gpu-1')

    def test_startable_with_unknown_models_is_tried(self):
        self.node(models=None, ollama=False, startable=True)
        s = routing.node_state()
        self.assertTrue(s['ready'])
        self.assertIsNone(s['has_model'])


class GatewayRoutingTests(Base):
    def test_node_answers_through_real_queue(self):
        n = self.node()
        metis = FakeMetis()
        prov = self.routed(metis)
        self.assertEqual(prov.select_models(['qwq:32b']), [CODER])
        fake = FakeNode(n)
        with self.sleeping(fake):
            text = prov.generate(CODER, 'سلام', system='sys')
        self.assertEqual(text, 'سلام از Qwen')
        self.assertEqual(metis.calls, [])
        self.assertEqual(prov.answered_by, CODER)
        self.assertFalse(prov.fell_back)
        job = fake.jobs[0]
        job.refresh_from_db()
        self.assertEqual(job.state, ComputeJob.State.COMPLETED)
        self.assertEqual(job.payload['model'], CODER)
        self.assertEqual(job.kind, 'ollama.generate')
        self.assertEqual(job.node_wanted, 'gpu-1')
        row = AiRouteLog.objects.first()
        self.assertEqual((row.via, row.fell_back, row.model), ('node', False, CODER))

    def test_generate_json_on_node(self):
        n = self.node()
        prov = self.routed(FakeMetis())
        with self.sleeping(FakeNode(n, answer='{"a": 1}')):
            parsed, raw = prov.generate_json(CODER, 'x')
        self.assertEqual(parsed, {'a': 1})

    def test_offline_never_queues_and_is_instant(self):
        self.node(online=False)
        metis = FakeMetis()
        prov = self.routed(metis)
        self.assertEqual(prov.select_models(['qwq:32b']), ['gpt-4o-mini'])
        with self.sleeping(lambda s: self.fail('نباید منتظر بماند')):
            self.assertEqual(prov.generate('gpt-4o-mini', 'x'), 'پاسخ از Metis')
        self.assertEqual(ComputeJob.objects.count(), 0)
        self.assertTrue(prov.fell_back)
        self.assertEqual(prov.answered_by, 'gpt-4o-mini')
        self.assertIn('خاموش', prov.fallback_reason)
        row = AiRouteLog.objects.first()
        self.assertEqual((row.via, row.fell_back), ('metis', True))

    def test_missing_model_falls_back_without_job(self):
        self.node(models=('qwq:32b',))
        metis = FakeMetis()
        prov = self.routed(metis)
        self.assertEqual(prov.generate('x', 'y'), 'پاسخ از Metis')
        self.assertEqual(ComputeJob.objects.count(), 0)
        self.assertIn('نصب نیست', prov.fallback_reason)

    def test_job_failure_falls_back(self):
        n = self.node()
        metis = FakeMetis()
        prov = self.routed(metis)
        with self.sleeping(FakeNode(n, 'fail')):
            self.assertEqual(prov.generate(CODER, 'x'), 'پاسخ از Metis')
        self.assertTrue(prov.fell_back)

    def test_not_claimed_times_out_and_job_is_cancelled(self):
        n = self.node()
        metis = FakeMetis()
        prov = self.routed(metis)
        with override_settings(AI_NODE_CLAIM_TIMEOUT=0), self.sleeping(FakeNode(n, 'ignore')):
            self.assertEqual(prov.generate(CODER, 'x'), 'پاسخ از Metis')
        self.assertIn('برنداشت', prov.fallback_reason)
        self.assertEqual(ComputeJob.objects.get().state, ComputeJob.State.CANCELLED)   # گره بعداً کارِ مرده نگیرد

    def test_node_dies_mid_job(self):
        n = self.node()
        metis = FakeMetis()
        prov = self.routed(metis)
        with self.sleeping(FakeNode(n, 'die')):
            self.assertEqual(prov.generate(CODER, 'x'), 'پاسخ از Metis')
        self.assertIn('قطع شد', prov.fallback_reason)

    def test_run_timeout(self):
        n = self.node()
        metis = FakeMetis()
        prov = self.routed(metis)
        with override_settings(AI_NODE_RUN_TIMEOUT=1), self.sleeping(FakeNode(n, 'hang')):
            self.assertEqual(prov.generate(CODER, 'x'), 'پاسخ از Metis')
        self.assertIn('جواب', prov.fallback_reason)

    def test_after_first_failure_rest_goes_straight_to_metis(self):
        n = self.node()
        metis = FakeMetis()
        prov = self.routed(metis)
        fake = FakeNode(n, 'fail')
        with self.sleeping(fake):
            prov.generate(CODER, 'x')
            prov.generate(CODER, 'y')
            parsed, _ = prov.generate_json(CODER, 'z')
        self.assertEqual(parsed, {'ok': 'metis'})
        self.assertEqual(ComputeJob.objects.count(), 1)
        self.assertEqual(len(metis.calls), 3)

    def test_no_fallback_raises_when_policy_forbids(self):
        self.node(online=False)
        from services.ai.ollama import OllamaUnavailable
        prov = self.routed(None)
        with self.assertRaises(OllamaUnavailable):
            prov.generate(CODER, 'x')

    def test_metis_only_mode_skips_routing(self):
        AiSettings.objects.filter(pk=1).update(route_mode='metis_only')
        self.assertFalse(routing.wants_node())
        n = self.node()
        self.assertTrue(n)
        with mock.patch.object(gateway, 'client', return_value='direct') as c:
            self.assertEqual(gateway.text_provider(None), 'direct')
        c.assert_called_once()

    def test_gateway_returns_routed_and_respects_policy(self):
        prov = gateway.text_provider(None)
        self.assertIsInstance(prov, routing.RoutedTextProvider)
        # اگر API تعریف شده باشد برای داده‌ی محصول جایگزین هست؛ برای پیامِ مشتری (سیاستِ پیش‌فرض) نیست
        customer = gateway.text_provider(None, gateway.CUSTOMER)
        self.assertIsInstance(customer, routing.RoutedTextProvider)
        self.assertIsNone(customer.fallback)

    def test_vision_untouched(self):
        with mock.patch.object(gateway, 'client', return_value='vision-direct') as c:
            self.assertEqual(gateway.vision_provider(None), 'vision-direct')
        self.assertEqual(c.call_args[0][0], 'VISION')


class StudioRoutingTests(Base):
    def setUp(self):
        super().setUp()
        self.cfg = AiSettings.get()

    def _direct(self, text='{"from":"metis"}'):
        return mock.patch.object(studio_providers.OpenAIProvider, 'complete', return_value=text)

    def test_get_provider_choice(self):
        self.assertIsInstance(studio_providers.get_provider(self.cfg), studio_providers.RoutedProvider)
        self.assertIsInstance(studio_providers.get_provider(self.cfg, direct=True), studio_providers.OpenAIProvider)
        AiSettings.objects.filter(pk=1).update(route_mode='metis_only')
        self.assertIsInstance(studio_providers.get_provider(self.cfg), studio_providers.OpenAIProvider)
        self.cfg.provider = 'mock'
        self.assertIsInstance(studio_providers.get_provider(self.cfg), studio_providers.MockProvider)

    def test_node_answers(self):
        n = self.node()
        prov = studio_providers.get_provider(self.cfg)
        with self._direct() as m, self.sleeping(FakeNode(n, answer='{"from":"qwen"}')):
            out = prov.complete('s', 'u')
        self.assertEqual(json.loads(out), {'from': 'qwen'})
        m.assert_not_called()
        self.assertEqual(prov.answered_by, CODER)
        self.assertFalse(prov.fell_back)

    def test_falls_back_and_proposal_says_so(self):
        from apps.ai_engine import services as ai
        self.node(online=False)
        p = Project.objects.create(name='x', slug='routeproj')
        prop = AiProposal.objects.create(project=p, task='edit_page', status='running')
        prov = studio_providers.get_provider(self.cfg)
        with self._direct():
            data = ai._call(prov, prop, 's', {'task': 'x'})
        self.assertEqual(data, {'from': 'metis'})
        prop.refresh_from_db()
        self.assertEqual(prop.answered_by, self.cfg.model)
        self.assertIn('خاموش', prop.fallback_note)

    def test_node_success_note_on_proposal(self):
        from apps.ai_engine import services as ai
        n = self.node()
        p = Project.objects.create(name='x', slug='routeproj2')
        prop = AiProposal.objects.create(project=p, task='edit_page', status='running')
        prov = studio_providers.get_provider(self.cfg)
        with self._direct(), self.sleeping(FakeNode(n, answer='{"a":1}')):
            ai._call(prov, prop, 's', {'task': 'x'})
        prop.refresh_from_db()
        self.assertEqual(prop.answered_by, CODER)
        self.assertEqual(prop.fallback_note, '')


class ThemeGuardTests(TestCase):
    databases = {'default', 'studio'}
    BASE = ':root { --brand: #be185d; --brand-ink: #ffffff; --ink: #111827; --ink-2: #374151; --ink-3: #6b7280; --bg: #f7f8fa; --card: #ffffff; }'

    def test_white_text_on_light_page_is_dropped(self):
        from apps.ai_engine import services as ai
        theme = ':root { --brand: #be185d; --ink: #ffffff; --ink-2: #ffffff; --ink-3: #ffffff; --bg: #f7f8fa; }'
        fixed, dropped = ai.fix_theme_contrast(theme, self.BASE)
        self.assertEqual(sorted(dropped), ['ink', 'ink-2', 'ink-3'])
        self.assertNotIn('--ink', fixed)
        self.assertIn('--brand: #be185d', fixed)

    def test_real_dark_theme_is_kept(self):
        from apps.ai_engine import services as ai
        theme = ':root { --ink: #f8fafc; --ink-2: #cbd5e1; --ink-3: #94a3b8; --bg: #0f172a; --card: #1e293b; }'
        fixed, dropped = ai.fix_theme_contrast(theme, self.BASE)
        self.assertEqual(dropped, [])
        self.assertEqual(fixed, theme)

    def test_with_theme_applies_the_guard(self):
        from apps.ai_engine import services as ai
        out = ai._with_theme(self.BASE, ':root { --ink: #fff; } .x{color:red}', 'x')
        self.assertNotIn('--ink: #fff', out)
        self.assertIn('.x{color:red}', out)


class VisualPagesKeepBlocksTests(TestCase):
    databases = {'default', 'studio'}

    def setUp(self):
        import shutil as sh
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(sh.rmtree, self.tmp, True)
        self._o = override_settings(WORKSPACES_ROOT=Path(self.tmp), AI_RUN_SYNC=True)
        self._o.enable()
        self.addCleanup(self._o.disable)

    def test_build_uses_edit_path_on_visual_pages_and_keeps_visual_header(self):
        from apps.ai_engine import services as ai
        from apps.projects.models import Page, SharedPart
        p = Project.objects.create(name='v', slug='vp1')
        visual = Page.objects.create(project=p, title='دیداری', slug='a', kind='static', body_html='<section class="nb-section b-11111111"><h1>x</h1></section>')
        plain = Page.objects.create(project=p, title='ساده', slug='b', kind='static', body_html='<p>y</p>')
        SharedPart.objects.create(project=p, kind='header', content='<header class="nb-header b-22222222"></header>')
        seen = []

        def fake_call(provider, proposal, system, payload):
            seen.append((system, payload))
            if payload['task'] == 'shell':
                return {'summary': 's', 'header': '<header class="site-header"></header>', 'footer': '<footer class="site-footer"></footer>', 'theme_css': ':root{--ink:#111111}'}
            return {'summary': 's', 'body_html': payload['current_body'] + '<!-- x -->', 'css': None}
        AiSettings.objects.update_or_create(pk=1, defaults={'provider': 'mock'})
        with mock.patch.object(ai, '_call', fake_call):
            prop = ai.generate_frontend(p, 'گل‌فروشی', include_shell=True)
        by_task = {(pl.get('page') or {}).get('slug') or pl.get('slug'): pl['task'] for _s, pl in seen if pl['task'] != 'shell'}
        self.assertEqual(by_task['a'], 'edit_page')
        self.assertEqual(by_task['b'], 'page')
        labels = [c.target for c in prop.changes.all()]
        self.assertNotIn('shared_header', labels)     # سربرگِ دیداری جای خودش ماند
        self.assertIn('shared_footer', labels)        # پابرگِ کدی عوض می‌شود
        self.assertTrue(visual and plain)


class RouteApiTests(Base):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.c = APIClient()
        self.c.force_authenticate(U.objects.create_user(username='r1', email='r1@x.y', password='x', is_staff=True))

    def test_default_is_qwen_first(self):
        AiSettings.objects.all().delete()
        AiSettings.get()
        self.assertEqual(self.c.get('/api/v1/studio/ai/route/').data['mode'], 'qwen_first')

    def test_switch(self):
        r = self.c.post('/api/v1/studio/ai/route/', {'mode': 'metis_only'}, format='json')
        self.assertEqual(r.data['mode'], 'metis_only')
        self.assertEqual(self.c.post('/api/v1/studio/ai/route/', {'mode': 'x'}, format='json').status_code, 400)

    def test_missing_model_shown_and_download_offer(self):
        n = self.node(models=('qwq:32b',))
        r = self.c.get('/api/v1/studio/ai/route/')
        self.assertIs(r.data['node']['has_model'], False)
        r = self.c.post('/api/v1/studio/ai/route/pull/')
        self.assertEqual(r.status_code, 202, r.data)
        job = ComputeJob.objects.get()
        self.assertEqual(job.kind, 'ollama.chat')
        self.assertEqual(job.payload['path'], '/api/pull')
        self.assertEqual(job.payload['name'], CODER)
        self.assertTrue(n)

    def test_pull_refused_when_off(self):
        self.node(online=False)
        r = self.c.post('/api/v1/studio/ai/route/pull/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('خاموش', r.data['error'])
        self.assertEqual(ComputeJob.objects.count(), 0)
