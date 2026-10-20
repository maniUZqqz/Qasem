# -*- coding: utf-8 -*-
"""سازگاری با خانواده‌های مختلف مدل هوش مصنوعی.

سه چیزی که کاربر به شکل «کندی»، «تایم‌اوت» و «خطا با بعضی مدل‌ها» می‌دید و
اینجا قفل می‌شود:

۱. مدل‌های استدلالی `max_tokens` و `temperature` سفارشی را رد می‌کنند.
۲. یک تایم‌اوت یا ۵xx لحظه‌ای، تولید برنامه را کامل شکست می‌داد.
۳. مدل استدلالی که کل بودجه را صرف «فکر کردن» می‌کرد و متنی برنمی‌گرداند،
   «خروجی خالی» شمرده می‌شد و کل زنجیره می‌سوخت.
"""
from unittest.mock import patch

import httpx
from django.test import TestCase
from openai import APITimeoutError, BadRequestError, InternalServerError

from ai_engine.ai_generator import AllProvidersFailed, call_model, ping_model
from app.models import APIConfig

from .test_ai_failover import MESSAGES, _FakeResponse, _FakeUsage


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoiceWithFinish:
    def __init__(self, content, finish_reason='stop'):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FinishResponse:
    """پاسخی که finish_reason هم دارد — برای شبیه‌سازی رسیدن به سقف توکن."""

    def __init__(self, content='خروجی نمونه', finish_reason='stop'):
        self.choices = [_FakeChoiceWithFinish(content, finish_reason)]
        self.usage = _FakeUsage()


class _Recorder:
    """کلاینتی که هر درخواست را ثبت می‌کند و رفتارش را یک تابع تعیین می‌کند."""

    def __init__(self, behaviour):
        self.calls = []
        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.calls.append(dict(kwargs))
                result = behaviour(kwargs, len(outer.calls))
                if isinstance(result, Exception):
                    raise result
                return result

        self.chat = type('Chat', (), {'completions': Completions()})()

    def sent_params(self):
        """پارامترهای هر درخواست، بدون messages و model."""
        return [
            {k: v for k, v in call.items() if k not in ('messages', 'model')}
            for call in self.calls
        ]


def _bad_request(message, param=None, code='unsupported_parameter'):
    """خطای ۴۰۰ واقعی SDK اوپن‌ای‌آی.

    `param=None` یعنی درگاهی که فیلد ساختاریافته نمی‌دهد و فقط جمله می‌نویسد.
    """
    error = {'message': message, 'type': 'invalid_request_error', 'code': code}
    if param:
        error['param'] = param
    request = httpx.Request('POST', 'https://api.openai.com/v1/chat/completions')
    response = httpx.Response(400, request=request, json={'error': error})
    return BadRequestError(f'Error code: 400 - {error}', response=response, body=error)


def _timeout_error():
    return APITimeoutError(request=httpx.Request('POST', 'https://api.openai.com/v1'))


def _overloaded_error():
    request = httpx.Request('POST', 'https://api.metisai.ir/openai/v1')
    response = httpx.Response(503, request=request, json={'error': {}})
    return InternalServerError('overloaded', response=response, body=None)


class ModelParameterAdaptationTests(TestCase):
    """خطای واقعی که کاربر گزارش کرد:

        Unsupported parameter: 'max_tokens' is not supported with this model.
        Use 'max_completion_tokens' instead.

    دو چیز باید تضمین شود: اول اینکه تولید برنامه با چنین مدلی شکست نخورد،
    دوم اینکه هزینه‌ی این کشف فقط یک بار پرداخت شود — وگرنه هر تولید برنامه
    دو درخواست شکست‌خورده‌ی اضافه می‌زند و کاربر آن را به شکل کندی می‌بیند.
    """

    def setUp(self):
        self.provider = APIConfig.objects.create(
            name='اوپن‌ای‌آی',
            base_url='https://api.openai.com/v1',
            api_key='k',
            model_name='gpt-5',
            priority=1,
            is_active=True,
        )

    @staticmethod
    def _reasoning_model(kwargs, _n):
        if 'max_tokens' in kwargs:
            return _bad_request(
                "Unsupported parameter: 'max_tokens' is not supported with this "
                "model. Use 'max_completion_tokens' instead.",
                param='max_tokens',
            )
        if kwargs.get('temperature') not in (None, 1):
            return _bad_request(
                "Unsupported value: 'temperature' does not support 0.35 with this "
                "model. Only the default (1) value is supported.",
                param='temperature', code='unsupported_value',
            )
        return _FakeResponse('برنامه تولید شد')

    def test_reasoning_model_still_produces_a_program(self):
        recorder = _Recorder(self._reasoning_model)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            response, _ = call_model(MESSAGES, max_tokens=10500, temperature=0.35)

        self.assertEqual(response.choices[0].message.content, 'برنامه تولید شد')
        self.assertEqual(recorder.sent_params()[-1], {'max_completion_tokens': 10500})

    def test_the_discovery_is_paid_for_only_once(self):
        """فراخوانی دوم باید مستقیم برود — بدون درخواست شکست‌خورده‌ی اضافه."""
        recorder = _Recorder(self._reasoning_model)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            call_model(MESSAGES, max_tokens=10500, temperature=0.35)
            first_round = len(recorder.calls)
            call_model(MESSAGES, max_tokens=10500, temperature=0.35)

        self.assertEqual(first_round, 3, 'کشف اولیه سه تلاش لازم دارد')
        self.assertEqual(
            len(recorder.calls) - first_round, 1,
            'بعد از کشف، هر تولید برنامه باید فقط یک درخواست باشد',
        )

    def test_what_was_learned_is_stored_on_the_provider(self):
        recorder = _Recorder(self._reasoning_model)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            call_model(MESSAGES, max_tokens=10500, temperature=0.35)

        self.provider.refresh_from_db()
        self.assertEqual(self.provider.token_param, 'max_completion_tokens')
        self.assertIs(self.provider.supports_temperature, False)

    def test_learning_survives_a_provider_that_fails_afterwards(self):
        """اگر بعد از کشف، درخواست شکست بخورد، کشف نباید هدر برود."""
        def rejects_then_breaks(kwargs, _n):
            if 'max_tokens' in kwargs:
                return _bad_request(
                    "Unsupported parameter: 'max_tokens' is not supported with this "
                    "model. Use 'max_completion_tokens' instead.",
                    param='max_tokens',
                )
            return RuntimeError('اعتبار تمام شد')

        recorder = _Recorder(rejects_then_breaks)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            with self.assertRaises(AllProvidersFailed):
                call_model(MESSAGES, max_tokens=100, temperature=0.35)

        self.provider.refresh_from_db()
        self.assertEqual(self.provider.token_param, 'max_completion_tokens')

    def test_changing_the_model_forgets_what_was_learned(self):
        """مدل جدید ممکن است خانواده‌ی دیگری باشد؛ کشف قبلی معتبر نیست."""
        self.provider.token_param = 'max_completion_tokens'
        self.provider.supports_temperature = False
        self.provider.save()

        self.provider.model_name = 'gpt-4o-mini'
        self.provider.save()

        self.provider.refresh_from_db()
        self.assertEqual(self.provider.token_param, '')
        self.assertIsNone(self.provider.supports_temperature)

    def test_changing_the_address_forgets_what_was_learned(self):
        self.provider.token_param = 'max_completion_tokens'
        self.provider.save()

        self.provider.base_url = 'https://api.metisai.ir/openai/v1'
        self.provider.save()

        self.provider.refresh_from_db()
        self.assertEqual(self.provider.token_param, '')

    def test_gateway_without_a_param_field_is_still_understood(self):
        """درگاهی که فیلد ساختاریافته نمی‌دهد و فقط جمله می‌نویسد."""
        def vague(kwargs, _n):
            if 'max_tokens' in kwargs:
                return _bad_request(
                    "unsupported parameter: 'max_tokens' is not supported here"
                )
            return _FakeResponse('از درگاه مبهم')

        recorder = _Recorder(vague)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            response, _ = call_model(MESSAGES, max_tokens=100, temperature=0.35)

        self.assertEqual(response.choices[0].message.content, 'از درگاه مبهم')

    def test_a_400_that_is_not_about_parameters_is_not_retried(self):
        """خطای ۴۰۰ نامربوط نباید حلقه‌ی تطبیق را راه بیندازد."""
        recorder = _Recorder(
            lambda _k, _n: _bad_request('Invalid API key provided', code='invalid_api_key')
        )
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            with self.assertRaises(AllProvidersFailed):
                call_model(MESSAGES, max_tokens=100, temperature=0.35)

        self.assertEqual(len(recorder.calls), 1)

    def test_ping_learns_the_parameters_before_the_first_real_user(self):
        """«تست اتصال» ادمین باید همان مسیر واقعی را برود و کشف را ذخیره کند."""
        recorder = _Recorder(self._reasoning_model)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            model = ping_model(self.provider)

        self.assertEqual(model, 'gpt-5')
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.token_param, 'max_completion_tokens')

    def test_ping_does_not_chase_an_empty_answer(self):
        """برای ping، پاسخ خالی مهم نیست — نباید بودجه را بزرگ کند."""
        recorder = _Recorder(lambda _k, _n: _FinishResponse('', finish_reason='length'))
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            ping_model(self.provider)

        self.assertEqual(len(recorder.calls), 1)


class TransientErrorTests(TestCase):
    """یک قطعی لحظه‌ای نباید تولید برنامه را بسوزاند.

    مهم‌ترین حالت وقتی است که فقط یک ارائه‌دهنده تنظیم شده باشد — آنجا
    زنجیره‌ای برای عقب‌نشینی وجود ندارد و تایم‌اوت مستقیم به کاربر می‌رسد.
    """

    def setUp(self):
        APIConfig.objects.create(
            name='تنها ارائه‌دهنده',
            base_url='https://api.metisai.ir/openai/v1',
            api_key='k', model_name='gpt-4o-mini',
            priority=1, is_active=True,
        )
        patcher = patch('ai_engine.ai_generator.RETRY_SLEEP_SECONDS', 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_timeout_is_retried_instead_of_failing(self):
        def flaky(_kwargs, n):
            return _timeout_error() if n == 1 else _FakeResponse('بعد از تکرار')

        recorder = _Recorder(flaky)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            response, _ = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(response.choices[0].message.content, 'بعد از تکرار')
        self.assertEqual(len(recorder.calls), 2)

    def test_a_server_that_keeps_timing_out_is_given_up_on(self):
        recorder = _Recorder(lambda _k, _n: _timeout_error())
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            with self.assertRaises(AllProvidersFailed):
                call_model(MESSAGES, max_tokens=100)

        self.assertEqual(len(recorder.calls), 2, 'یک تلاش اولیه + یک تکرار')

    def test_server_overload_is_retried_too(self):
        def overloaded(_kwargs, n):
            return _overloaded_error() if n == 1 else _FakeResponse('سرور سرپا شد')

        recorder = _Recorder(overloaded)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            response, _ = call_model(MESSAGES, max_tokens=100)

        self.assertEqual(response.choices[0].message.content, 'سرور سرپا شد')


class ReasoningBudgetTests(TestCase):
    """مدل استدلالی ممکن است کل بودجه را صرف فکر کردن کند و متنی ندهد.

    قبلاً این حالت «خروجی خالی» شمرده می‌شد، کل زنجیره می‌سوخت و کاربر خطا
    می‌گرفت — در حالی که مدل سالم بود و فقط بودجه کم بود.
    """

    def setUp(self):
        APIConfig.objects.create(
            name='مدل استدلالی',
            base_url='https://api.openai.com/v1',
            api_key='k', model_name='o4-mini',
            priority=1, is_active=True,
            token_param='max_completion_tokens',
        )

    def test_empty_answer_because_of_budget_is_retried_with_more(self):
        def hungry(kwargs, _n):
            if kwargs.get('max_completion_tokens', 0) < 12000:
                return _FinishResponse('', finish_reason='length')
            return _FinishResponse('برنامه کامل')

        recorder = _Recorder(hungry)
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            response, _ = call_model(MESSAGES, max_tokens=6500, temperature=None)

        self.assertEqual(response.choices[0].message.content, 'برنامه کامل')
        self.assertEqual(
            [call['max_completion_tokens'] for call in recorder.calls],
            [6500, 13000],
        )

    def test_the_bigger_budget_is_tried_only_once(self):
        recorder = _Recorder(lambda _k, _n: _FinishResponse('', finish_reason='length'))
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            with self.assertRaises(AllProvidersFailed):
                call_model(MESSAGES, max_tokens=6500, temperature=None)

        self.assertEqual(len(recorder.calls), 2)

    def test_a_full_answer_is_never_asked_for_twice(self):
        recorder = _Recorder(lambda _k, _n: _FinishResponse('برنامه کامل'))
        with patch('ai_engine.ai_generator.build_client', return_value=recorder):
            call_model(MESSAGES, max_tokens=6500, temperature=None)

        self.assertEqual(len(recorder.calls), 1)
