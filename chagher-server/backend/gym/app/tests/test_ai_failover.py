# -*- coding: utf-8 -*-
"""زنجیره‌ی ارائه‌دهنده‌های هوش مصنوعی — جایگزینی خودکار هنگام قطعی.

هدف این تست‌ها یک چیز است: قطعی یک ارائه‌دهنده نباید به کاربر برسد. تا وقتی
حداقل یکی از ارائه‌دهنده‌های فعال پاسخ بدهد، تولید برنامه باید موفق شود.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_engine.ai_generator import AllProvidersFailed, build_client, call_model
from app.models import APIConfig


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, prompt_tokens=100, completion_tokens=50):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, content='خروجی نمونه', prompt_tokens=100, completion_tokens=50):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


class _FakeCompletions:
    def __init__(self, behaviour):
        self._behaviour = behaviour

    def create(self, **kwargs):
        result = self._behaviour(kwargs)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeClient:
    """کلاینت ساختگی که رفتارش را بر اساس base_url تعیین می‌کند."""

    def __init__(self, behaviour):
        self.chat = type('Chat', (), {'completions': _FakeCompletions(behaviour)})()


def _make_client_factory(per_url):
    """به‌جای ساخت کلاینت واقعی، رفتار هر آدرس را برمی‌گرداند."""
    calls = []

    def factory(config):
        calls.append(config['base_url'])
        outcome = per_url.get(config['base_url'])
        if isinstance(outcome, Exception) and isinstance(outcome, ConnectionError):
            # خطا در همان ساخت کلاینت (مثل آدرس نامعتبر)
            raise outcome
        return _FakeClient(lambda kwargs: outcome)

    factory.calls = calls
    return factory


MESSAGES = [{'role': 'user', 'content': 'سلام'}]


class FailoverTests(TestCase):
    def setUp(self):
        self.local = APIConfig.objects.create(
            name='اولامای خودم',
            provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434/v1',
            model_name='llama3.2',
            priority=1,
            is_active=True,
        )
        self.metis = APIConfig.objects.create(
            name='متیس',
            provider_type=APIConfig.TYPE_API,
            base_url='https://api.metisai.ir/openai/v1',
            api_key='metis-key',
            model_name='gpt-4o-mini',
            priority=2,
            is_active=True,
            input_price_per_million=1000,
            output_price_per_million=3000,
        )
        self.openai = APIConfig.objects.create(
            name='اوپن‌ای‌آی',
            provider_type=APIConfig.TYPE_API,
            base_url='https://api.openai.com/v1',
            api_key='openai-key',
            model_name='gpt-4o',
            priority=3,
            is_active=True,
        )

    def test_first_provider_is_used_when_healthy(self):
        factory = _make_client_factory({
            'http://localhost:11434/v1': _FakeResponse('از مدل محلی'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            response, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(response.choices[0].message.content, 'از مدل محلی')
        self.assertEqual(config['name'], 'اولامای خودم')
        self.assertEqual(factory.calls, ['http://localhost:11434/v1'])

    def test_falls_through_to_second_when_first_is_down(self):
        """سرور محلی خاموش است — کاربر نباید خطا ببیند."""
        factory = _make_client_factory({
            'http://localhost:11434/v1': ConnectionError('Connection refused'),
            'https://api.metisai.ir/openai/v1': _FakeResponse('از متیس'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            response, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(response.choices[0].message.content, 'از متیس')
        self.assertEqual(config['name'], 'متیس')

    def test_falls_through_twice(self):
        factory = _make_client_factory({
            'http://localhost:11434/v1': ConnectionError('down'),
            'https://api.metisai.ir/openai/v1': RuntimeError('اعتبار تمام شد'),
            'https://api.openai.com/v1': _FakeResponse('از اوپن‌ای‌آی'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            response, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(config['name'], 'اوپن‌ای‌آی')

    def test_empty_output_is_treated_as_failure(self):
        """پاسخ خالی از دید کاربر با قطعی فرقی ندارد."""
        factory = _make_client_factory({
            'http://localhost:11434/v1': _FakeResponse(''),
            'https://api.metisai.ir/openai/v1': _FakeResponse('پاسخ واقعی'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            response, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(config['name'], 'متیس')

    def test_raises_only_when_every_provider_fails(self):
        factory = _make_client_factory({
            'http://localhost:11434/v1': ConnectionError('down'),
            'https://api.metisai.ir/openai/v1': RuntimeError('۵۰۰'),
            'https://api.openai.com/v1': RuntimeError('timeout'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            with self.assertRaises(AllProvidersFailed) as ctx:
                call_model(MESSAGES, max_tokens=100)

        self.assertEqual(len(ctx.exception.attempts), 3)

    def test_inactive_provider_is_skipped(self):
        self.metis.is_active = False
        self.metis.save(update_fields=['is_active'])

        factory = _make_client_factory({
            'http://localhost:11434/v1': ConnectionError('down'),
            'https://api.openai.com/v1': _FakeResponse('از اوپن‌ای‌آی'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            _, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(config['name'], 'اوپن‌ای‌آی')
        self.assertNotIn('https://api.metisai.ir/openai/v1', factory.calls)

    def test_priority_change_reorders_the_chain(self):
        """تغییر اولویت در پنل ادمین باید بلافاصله ترتیب را عوض کند."""
        self.openai.priority = 0 + 1
        self.openai.save(update_fields=['priority'])
        self.local.priority = 9
        self.local.save(update_fields=['priority'])

        factory = _make_client_factory({
            'https://api.openai.com/v1': _FakeResponse('اول اوپن‌ای‌آی'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            _, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(config['name'], 'اوپن‌ای‌آی')

    def test_no_active_provider_raises_clear_error(self):
        APIConfig.objects.update(is_active=False)
        with self.assertRaises(ValueError) as ctx:
            call_model(MESSAGES, max_tokens=100)
        self.assertIn('هیچ ارائه‌دهنده فعالی', str(ctx.exception))

    def test_health_is_recorded(self):
        factory = _make_client_factory({
            'http://localhost:11434/v1': ConnectionError('Connection refused'),
            'https://api.metisai.ir/openai/v1': _FakeResponse('ok'),
        })
        with patch('ai_engine.ai_generator.build_client', factory):
            call_model(MESSAGES, max_tokens=100)

        self.local.refresh_from_db()
        self.metis.refresh_from_db()

        self.assertIsNotNone(self.local.last_failure_at)
        self.assertIn('Connection refused', self.local.last_error)
        self.assertIsNotNone(self.metis.last_success_at)
        self.assertIsNone(self.metis.last_error)


class ProviderPricingTests(TestCase):
    """هزینه باید با تعرفه‌ی ارائه‌دهنده‌ای حساب شود که واقعاً پاسخ داده."""

    def setUp(self):
        self.free_local = APIConfig.objects.create(
            name='محلی رایگان',
            provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434/v1',
            model_name='llama3.2',
            priority=1,
            is_active=True,
        )
        self.paid = APIConfig.objects.create(
            name='متیس',
            base_url='https://api.metisai.ir/openai/v1',
            api_key='k',
            model_name='gpt-4o-mini',
            priority=2,
            is_active=True,
            input_price_per_million=1000,
            output_price_per_million=3000,
        )

    def test_cost_uses_the_provider_that_answered(self):
        from decimal import Decimal

        cost = APIConfig.estimate_cost(
            1_000_000, 1_000_000, config=self.paid.as_config()
        )
        self.assertEqual(cost, Decimal('4000.0000'))

        free_cost = APIConfig.estimate_cost(
            1_000_000, 1_000_000, config=self.free_local.as_config()
        )
        self.assertEqual(free_cost, Decimal('0.0000'))

    def test_usage_carries_provider_config(self):
        from ai_engine.ai_generator import AIUsage

        usage = AIUsage.from_response(
            _FakeResponse(prompt_tokens=1000, completion_tokens=500),
            'gpt-4o-mini',
            self.paid.as_config(),
        )
        self.assertEqual(usage.provider_config['name'], 'متیس')
        self.assertEqual(usage.input_tokens, 1000)
        self.assertEqual(usage.output_tokens, 500)


class LocalOnlyLinkTests(TestCase):
    """برای سرور خودمان باید فقط لینک کافی باشد.

    نه کلید API، نه نام مدل، نه حتی پسوند /v1 — همه باید خودکار حل شوند.
    """

    def _client_with_models(self, model_ids, content='خروجی'):
        client = MagicMock()
        client.models.list.return_value = type(
            'L', (), {'data': [type('M', (), {'id': mid})() for mid in model_ids]}
        )()
        client.chat.completions.create.return_value = _FakeResponse(content)
        return client

    # ---------------- نرمال‌سازی آدرس ----------------

    def test_bare_host_gets_v1_appended(self):
        provider = APIConfig.objects.create(
            name='سرور من', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://192.168.1.50:11434', model_name='',
        )
        self.assertEqual(provider.base_url, 'http://192.168.1.50:11434/v1')

    def test_trailing_slash_is_handled(self):
        provider = APIConfig.objects.create(
            name='سرور من', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://192.168.1.50:11434/', model_name='',
        )
        self.assertEqual(provider.base_url, 'http://192.168.1.50:11434/v1')

    def test_existing_v1_is_not_doubled(self):
        provider = APIConfig.objects.create(
            name='سرور من', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://192.168.1.50:11434/v1', model_name='',
        )
        self.assertEqual(provider.base_url, 'http://192.168.1.50:11434/v1')

    def test_custom_proxy_path_is_left_alone(self):
        """اگر کاربر مسیر خودش را داده (reverse proxy)، دست نمی‌زنیم."""
        provider = APIConfig.objects.create(
            name='پراکسی', provider_type=APIConfig.TYPE_LOCAL,
            base_url='https://ai.mydomain.com/api/v1', model_name='',
        )
        self.assertEqual(provider.base_url, 'https://ai.mydomain.com/api/v1')

    # ---------------- کشف خودکار نام مدل ----------------

    def test_model_name_is_discovered_from_server(self):
        provider = APIConfig.objects.create(
            name='اولاما', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434', model_name='',
            priority=1, is_active=True,
        )
        client = self._client_with_models(['llama3.2:latest', 'qwen2.5'])

        self.assertEqual(provider.resolve_model(client), 'llama3.2:latest')

        provider.refresh_from_db()
        self.assertEqual(provider.discovered_model, 'llama3.2:latest')
        self.assertIsNotNone(provider.discovered_at)

    def test_explicit_model_name_wins_over_discovery(self):
        provider = APIConfig.objects.create(
            name='اولاما', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434', model_name='qwen2.5',
        )
        client = self._client_with_models(['llama3.2', 'qwen2.5'])

        self.assertEqual(provider.resolve_model(client), 'qwen2.5')
        client.models.list.assert_not_called()

    def test_discovery_is_cached(self):
        """کشف نباید در هر تولید برنامه تکرار شود."""
        provider = APIConfig.objects.create(
            name='اولاما', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434', model_name='',
        )
        client = self._client_with_models(['llama3.2'])

        provider.resolve_model(client)
        provider.resolve_model(client)
        provider.resolve_model(client)

        self.assertEqual(client.models.list.call_count, 1)

    def test_changing_url_invalidates_discovery(self):
        """آدرس که عوض شد، مدل کشف‌شده‌ی قبلی دیگر معتبر نیست."""
        provider = APIConfig.objects.create(
            name='اولاما', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434', model_name='',
        )
        provider.resolve_model(self._client_with_models(['llama3.2']))
        provider.refresh_from_db()
        self.assertEqual(provider.discovered_model, 'llama3.2')

        provider.base_url = 'http://192.168.1.99:11434'
        provider.save()

        provider.refresh_from_db()
        self.assertIsNone(provider.discovered_model)

    def test_server_without_models_gives_actionable_error(self):
        provider = APIConfig.objects.create(
            name='خالی', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434', model_name='',
        )
        client = self._client_with_models([])

        with self.assertRaises(ValueError) as ctx:
            provider.resolve_model(client)
        self.assertIn('ollama pull', str(ctx.exception))

    def test_cloud_provider_still_requires_model_name(self):
        provider = APIConfig.objects.create(
            name='ابری', provider_type=APIConfig.TYPE_API,
            api_key='k', model_name='',
        )
        with self.assertRaises(ValueError) as ctx:
            provider.resolve_model(MagicMock())
        self.assertIn('نام مدل', str(ctx.exception))

    # ---------------- مسیر کامل ----------------

    def test_end_to_end_with_only_a_link(self):
        """کل چیزی که کاربر وارد کرده: یک لینک. باید کار کند."""
        APIConfig.objects.create(
            name='سرور خودم',
            provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://192.168.1.50:11434',
            model_name='',
            api_key='',
            priority=1,
            is_active=True,
        )

        client = self._client_with_models(['llama3.2'], content='برنامه از سرور خودم')
        with patch('ai_engine.ai_generator.build_client', return_value=client):
            response, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(response.choices[0].message.content, 'برنامه از سرور خودم')
        self.assertEqual(config['model_name'], 'llama3.2')
        # مدل واقعاً به سرور فرستاده شد
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs['model'], 'llama3.2'
        )

    def test_discovery_failure_falls_through_to_next_provider(self):
        """اگر سرور محلی فهرست مدل نداد، زنجیره نباید متوقف شود."""
        APIConfig.objects.create(
            name='محلی خراب', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434', model_name='',
            priority=1, is_active=True,
        )
        APIConfig.objects.create(
            name='ابری', base_url='https://api.metisai.ir/openai/v1',
            api_key='k', model_name='gpt-4o-mini', priority=2, is_active=True,
        )

        broken = MagicMock()
        broken.models.list.side_effect = ConnectionError('no route to host')
        healthy = MagicMock()
        healthy.chat.completions.create.return_value = _FakeResponse('از ابری')

        def build(config):
            return broken if 'localhost' in config['base_url'] else healthy

        with patch('ai_engine.ai_generator.build_client', side_effect=build):
            _, config = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(config['name'], 'ابری')


class BuildClientTests(TestCase):
    def test_cloud_provider_without_key_is_rejected(self):
        provider = APIConfig.objects.create(
            name='ابری ناقص', provider_type=APIConfig.TYPE_API, api_key=''
        )
        with self.assertRaises(ValueError) as ctx:
            build_client(provider.as_config())
        self.assertIn('کلید API ندارد', str(ctx.exception))

    def test_local_provider_without_key_builds(self):
        """مدل محلی نباید به‌خاطر نداشتن کلید رد شود."""
        provider = APIConfig.objects.create(
            name='اولاما',
            provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434/v1',
            model_name='llama3.2',
            api_key='',
        )
        client = build_client(provider.as_config())
        self.assertIsNotNone(client)
        self.assertEqual(str(client.base_url).rstrip('/'), 'http://localhost:11434/v1')
