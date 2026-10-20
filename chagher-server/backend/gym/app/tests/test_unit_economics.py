# -*- coding: utf-8 -*-
"""بهای تمام‌شده: هر فراخوانی مدل باید تفکیک‌شده و با تعرفه‌ی لحظه ثبت شود."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework import status

from app.models import (
    AIUsageLog, APIConfig, ClientProgram, CustomUser, TokenPackage,
)
from app.tests.utils import BaseAPITestCase, create_user


def _pricing(inp='30000', out='120000'):
    return APIConfig.objects.create(
        name='متیس', api_key='k', model_name='gpt-4o-mini',
        input_price_per_million=Decimal(inp),
        output_price_per_million=Decimal(out),
        is_active=True,
    )


class TokenUnitPriceTests(TestCase):
    """نرخ فروش هر توکن از بسته‌ی فعال می‌آید، نه از یک عدد ثابت در کد."""

    def test_zero_when_no_active_package(self):
        self.assertEqual(AIUsageLog.current_token_unit_price(), Decimal('0'))

    def test_derived_from_price_per_fifty(self):
        TokenPackage.objects.create(
            name='عادی', token_amount=1000,
            price_per_50_tokens=Decimal('40000'), is_active=True,
        )
        self.assertEqual(AIUsageLog.current_token_unit_price(), Decimal('800.0000'))

    def test_inactive_package_is_ignored(self):
        TokenPackage.objects.create(
            name='قدیمی', token_amount=100,
            price_per_50_tokens=Decimal('10'), is_active=False,
        )
        self.assertEqual(AIUsageLog.current_token_unit_price(), Decimal('0'))


class UsageLogRecordingTests(BaseAPITestCase):
    """تولید و ویرایش هرکدام یک سطر مستقل می‌سازند."""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.user.token_balance = 500
        self.user.save()
        self.auth(self.user)
        _pricing()
        TokenPackage.objects.create(
            name='عادی', token_amount=1000,
            price_per_50_tokens=Decimal('40000'), is_active=True,
        )

    @patch('app.views.generate_program')
    def test_generate_writes_one_row_with_snapshot_pricing(self, mock_generate):
        from ai_engine.ai_generator import AIUsage

        mock_generate.return_value = (
            'برنامه ورزشی', 'برنامه غذایی',
            AIUsage(model_name='gpt-4o-mini', input_tokens=10_000, output_tokens=5_000),
        )

        response = self.client.post('/api/programs/generate/', {
            'name': 'علی', 'program_days': 3, 'program_type': 'both',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        log = AIUsageLog.objects.get()
        self.assertEqual(log.operation, AIUsageLog.OP_GENERATE)
        self.assertEqual(log.program_type, 'both')
        self.assertEqual(log.input_tokens, 10_000)
        self.assertEqual(log.output_tokens, 5_000)
        # 10k*30000/1M + 5k*120000/1M
        self.assertEqual(log.cost, Decimal('900.0000'))
        # ۵۰ توکن × ۸۰۰ تومان
        self.assertEqual(log.tokens_charged, 50)
        self.assertEqual(log.revenue, Decimal('40000.0000'))
        self.assertEqual(log.margin, Decimal('39100.0000'))
        # تعرفه عکس‌برداری شده تا تغییر بعدی قیمت، گذشته را بازنویسی نکند
        self.assertEqual(log.input_price_per_million, Decimal('30000.00'))
        self.assertEqual(log.output_price_per_million, Decimal('120000.00'))

    @patch('app.views.generate_program')
    def test_single_section_program_is_charged_half(self, mock_generate):
        from ai_engine.ai_generator import AIUsage

        mock_generate.return_value = (
            'برنامه ورزشی', None,
            AIUsage(model_name='gpt-4o-mini', input_tokens=4_000, output_tokens=2_000),
        )
        self.client.post('/api/programs/generate/', {
            'name': 'علی', 'program_days': 3, 'program_type': 'workout',
        })

        log = AIUsageLog.objects.get()
        self.assertEqual(log.program_type, 'workout')
        self.assertEqual(log.tokens_charged, 25)
        self.assertEqual(log.revenue, Decimal('20000.0000'))

    @patch('app.views.edit_program_with_feedback')
    @patch('app.views.generate_program')
    def test_edit_adds_a_second_row_without_losing_the_first(self, mock_generate, mock_edit):
        from ai_engine.ai_generator import AIUsage

        mock_generate.return_value = (
            'برنامه ورزشی', 'برنامه غذایی',
            AIUsage(model_name='gpt-4o-mini', input_tokens=10_000, output_tokens=5_000),
        )
        self.client.post('/api/programs/generate/', {
            'name': 'علی', 'program_days': 3, 'program_type': 'both',
        })
        program = ClientProgram.objects.get()

        mock_edit.return_value = (
            'برنامه ورزشی ۲', 'برنامه غذایی ۲',
            AIUsage(model_name='gpt-4o-mini', input_tokens=3_000, output_tokens=1_000),
        )
        response = self.client.post(
            f'/api/programs/{program.id}/edit/', {'feedback': 'سبک‌تر شود'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        logs = AIUsageLog.objects.order_by('id')
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs[0].operation, AIUsageLog.OP_GENERATE)
        self.assertEqual(logs[1].operation, AIUsageLog.OP_EDIT)
        self.assertEqual(logs[1].tokens_charged, 25)
        # 3k*30000/1M + 1k*120000/1M = 90 + 120
        self.assertEqual(logs[1].cost, Decimal('210.0000'))

        # مجموع روی خود برنامه هم باید جمع هر دو باشد
        program.refresh_from_db()
        self.assertEqual(program.ai_cost, Decimal('1110.0000'))

    @patch('app.views.generate_program')
    def test_failed_generation_writes_no_row(self, mock_generate):
        mock_generate.side_effect = RuntimeError('boom')
        self.client.post('/api/programs/generate/', {
            'name': 'علی', 'program_days': 3, 'program_type': 'both',
        })
        self.assertEqual(AIUsageLog.objects.count(), 0)


class UnitEconomicsAdminTests(BaseAPITestCase):
    """صفحه‌ی گزارش باید با داده و بدون داده رندر شود."""

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.staff = CustomUser.objects.create_superuser(
            phone_number='09129999999', password='AdminPass123',
        )
        self.client.force_login(self.staff)

    def test_report_renders_when_empty(self):
        response = self.client.get('/admin/app/uniteconomicsreport/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('بهای تمام‌شده', response.content.decode('utf-8'))

    def test_report_shows_per_type_breakdown(self):
        _pricing()
        TokenPackage.objects.create(
            name='عادی', token_amount=1000,
            price_per_50_tokens=Decimal('40000'), is_active=True,
        )
        coach = create_user(phone='09121111111')
        AIUsageLog.objects.create(
            user=coach, operation=AIUsageLog.OP_GENERATE, program_type='both',
            model_name='gpt-4o-mini', input_tokens=10_000, output_tokens=5_000,
            cost=Decimal('900'), tokens_charged=50,
            token_unit_price=Decimal('800'), revenue=Decimal('40000'),
        )

        response = self.client.get('/admin/app/uniteconomicsreport/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn('برنامه ورزشی + غذایی', body)
        self.assertIn('39,100', body)   # سود هر مورد

    def test_report_warns_when_tariff_is_missing(self):
        APIConfig.objects.create(
            name='بدون تعرفه', api_key='k', model_name='m', is_active=True,
        )
        response = self.client.get('/admin/app/uniteconomicsreport/')
        self.assertIn('تعرفه‌ی مدل ثبت نشده است', response.content.decode('utf-8'))
