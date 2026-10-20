# -*- coding: utf-8 -*-
"""تست‌های دستگاه‌ها، غذاها و تولید/ویرایش برنامه با AI موک‌شده"""
from unittest.mock import patch, MagicMock

from rest_framework import status

from app.models import (
    APIConfig, ClientProgram, Equipment, EquipmentCategory, GymBrand,
    GymClient, Meal,
)
from .utils import BaseAPITestCase, create_user
from ai_engine.ai_generator import AIUsage


def _usage(input_tokens=1200, output_tokens=800, model_name='test-model'):
    """مصرف توکن ساختگی مدل — خروجی موتور هوش مصنوعی حالا سه‌تایی است."""
    return AIUsage(
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class EquipmentAPITests(BaseAPITestCase):
    url = '/api/equipments/'

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.other = create_user(phone='09127654321')
        self.auth(self.user)

    def test_create_and_list(self):
        response = self.client.post(self.url, {
            'name': 'پرس سینه',
            'muscle_group': 'سینه',
            'description': 'دستگاه پرس سینه',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Equipment.objects.get().user, self.user)

        response = self.client.get(self.url)
        self.assertEqual(len(response.data), 1)

    def test_other_users_equipment_not_visible(self):
        Equipment.objects.create(user=self.other, name='اسکات')
        response = self.client.get(self.url)
        self.assertEqual(len(response.data), 0)


class EquipmentCategoryAPITests(BaseAPITestCase):
    """دسته‌بندی‌ها باید بین باشگاه‌ها ایزوله باشند (رفع نشت بین‌مستأجری)"""
    url = '/api/equipment-categories/'

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.other = create_user(phone='09127654321')
        self.auth(self.user)

    def test_create_assigns_owner(self):
        response = self.client.post(self.url, {'name': 'قدرتی'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        category = EquipmentCategory.objects.get()
        self.assertEqual(category.owner, self.user)

    def test_other_coach_categories_not_visible(self):
        EquipmentCategory.objects.create(owner=self.other, name='دسته باشگاه دیگر')
        response = self.client.get(self.url)
        self.assertEqual(len(response.data), 0)

    def test_global_categories_visible_but_readonly(self):
        category = EquipmentCategory.objects.create(owner=None, name='دسته سراسری')
        response = self.client.get(self.url)
        self.assertEqual(len(response.data), 1)
        self.assertTrue(response.data[0]['is_global'])

        response = self.client.patch(f'{self.url}{category.id}/', {'name': 'تغییر'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.delete(f'{self.url}{category.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_edit_or_delete_other_coach_category(self):
        category = EquipmentCategory.objects.create(owner=self.other, name='دسته دیگری')
        response = self.client.patch(f'{self.url}{category.id}/', {'name': 'هک'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.delete(f'{self.url}{category.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(EquipmentCategory.objects.filter(pk=category.pk).exists())

    def test_own_category_editable(self):
        category = EquipmentCategory.objects.create(owner=self.user, name='دسته من')
        response = self.client.patch(f'{self.url}{category.id}/', {'name': 'دسته جدید'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        category.refresh_from_db()
        self.assertEqual(category.name, 'دسته جدید')

    def test_equipment_cannot_use_other_coach_category(self):
        category = EquipmentCategory.objects.create(owner=self.other, name='دسته دیگری')
        response = self.client.post('/api/equipments/', {
            'name': 'پرس سینه', 'category': category.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class MealAPITests(BaseAPITestCase):
    url = '/api/meals/'

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.other = create_user(phone='09127654321')
        self.auth(self.user)

    def test_create_and_list(self):
        response = self.client.post(self.url, {
            'name': 'قرمه‌سبزی',
            'description': 'خورشت سنتی',
            'calories': 550,
            'protein': 30.0,
            'carbs': 45.0,
            'fat': 25.0,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Meal.objects.get().user, self.user)

    def test_other_users_meal_not_visible(self):
        Meal.objects.create(
            user=self.other, name='کوکو', description='-', calories=1,
            protein=1, carbs=1, fat=1,
        )
        response = self.client.get(self.url)
        self.assertEqual(len(response.data), 0)


class GenerateProgramAPITests(BaseAPITestCase):
    url = '/api/programs/generate/'

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.user.token_balance = 100
        self.user.save()
        self.auth(self.user)

    def test_insufficient_tokens_returns_402(self):
        self.user.token_balance = 10
        self.user.save()
        response = self.client.post(self.url, {'name': 'علی'})
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(ClientProgram.objects.count(), 0)

    @patch('app.views.generate_program', return_value=('برنامه ورزشی تستی', 'برنامه غذایی تستی', _usage()))
    def test_generate_success_deducts_tokens(self, mock_generate):
        response = self.client.post(self.url, {
            'name': 'علی',
            'age': 25,
            'gender': 'M',
            'height': 180,
            'weight': 80,
            'program_days': 5,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['remaining_tokens'], 50)

        program = ClientProgram.objects.get()
        self.assertEqual(program.generated_workout, 'برنامه ورزشی تستی')
        self.assertEqual(program.generated_meal_plan, 'برنامه غذایی تستی')
        self.assertEqual(program.tokens_consumed, 50)
        self.assertEqual(program.program_type, 'both')
        mock_generate.assert_called_once_with(program.id, 'both')

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 50)

    @patch('app.views.generate_program', return_value=('برنامه ورزشی تستی', None, _usage()))
    def test_workout_only_costs_25_and_skips_meal(self, mock_generate):
        """فقط برنامه ورزشی: 25 توکن — برنامه غذایی نباید تولید شود"""
        response = self.client.post(self.url, {'name': 'علی', 'program_type': 'workout'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['remaining_tokens'], 75)  # 100 - 25

        program = ClientProgram.objects.get()
        self.assertEqual(program.program_type, 'workout')
        self.assertEqual(program.tokens_consumed, 25)
        self.assertEqual(program.generated_workout, 'برنامه ورزشی تستی')
        self.assertIsNone(program.generated_meal_plan)
        mock_generate.assert_called_once_with(program.id, 'workout')

    @patch('app.views.generate_program', return_value=(None, 'برنامه غذایی تستی', _usage()))
    def test_meal_only_costs_25_and_skips_workout(self, mock_generate):
        """فقط برنامه غذایی: 25 توکن — برنامه ورزشی نباید تولید شود"""
        response = self.client.post(self.url, {'name': 'علی', 'program_type': 'meal'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['remaining_tokens'], 75)  # 100 - 25

        program = ClientProgram.objects.get()
        self.assertEqual(program.program_type, 'meal')
        self.assertEqual(program.tokens_consumed, 25)
        self.assertIsNone(program.generated_workout)
        self.assertEqual(program.generated_meal_plan, 'برنامه غذایی تستی')
        mock_generate.assert_called_once_with(program.id, 'meal')

    def test_invalid_program_type_rejected(self):
        response = self.client.post(self.url, {'name': 'علی', 'program_type': 'invalid'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_workout_only_insufficient_tokens(self):
        """با 20 توکن نمی‌توان برنامه 25 توکنی گرفت"""
        self.user.token_balance = 20
        self.user.save()
        response = self.client.post(self.url, {'name': 'علی', 'program_type': 'workout'})
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data['required_tokens'], 25)

    @patch('app.views.generate_program', side_effect=ValueError('خطای تستی AI'))
    def test_generate_ai_failure_returns_500(self, mock_generate):
        response = self.client.post(self.url, {'name': 'علی'})
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        # پیام خطای داخلی به کلاینت درز نمی‌کند
        self.assertNotIn('خطای تستی AI', response.data['error'])

    @patch('app.views.generate_program', side_effect=ValueError('خطای تستی AI'))
    def test_generate_ai_failure_refunds_tokens(self, mock_generate):
        """اگر AI شکست بخورد: توکن برمی‌گردد و رکورد ناتمام باقی نمی‌ماند"""
        self.client.post(self.url, {'name': 'علی'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100)
        self.assertEqual(ClientProgram.objects.count(), 0)

    @patch('app.views.generate_program', return_value=('برنامه ورزشی تستی', 'برنامه غذایی تستی', _usage()))
    def test_extra_notes_saved_on_program(self, mock_generate):
        """فیلد توضیحات تکمیلی باید در برنامه ذخیره و در پاسخ برگردد"""
        response = self.client.post(self.url, {
            'name': 'علی',
            'extra_notes': 'فقط شب‌ها تمرین می‌کند و به شنا علاقه دارد',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        program = ClientProgram.objects.get()
        self.assertEqual(program.extra_notes, 'فقط شب‌ها تمرین می‌کند و به شنا علاقه دارد')
        self.assertEqual(
            response.data['program']['extra_notes'],
            'فقط شب‌ها تمرین می‌کند و به شنا علاقه دارد',
        )

    def test_invalid_program_days(self):
        response = self.client.post(self.url, {'name': 'علی', 'program_days': 9})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


def _fake_completion(content, prompt_tokens=100, completion_tokens=50):
    """پاسخ ساختگی مدل با ساختار واقعی.

    MagicMock خام کافی نیست: شمارش توکن از روی `usage` خوانده و به int تبدیل
    می‌شود، و int(MagicMock) خطا می‌دهد.
    """
    message = type('M', (), {'content': content})()
    choice = type('C', (), {'message': message})()
    usage = type('U', (), {
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
    })()
    return type('R', (), {'choices': [choice], 'usage': usage})()


class ExtraNotesInPromptTests(BaseAPITestCase):
    """توضیحات تکمیلی باید به پرامپت هوش مصنوعی برسد.

    عمداً فقط `build_client` جایگزین می‌شود، نه کل زنجیره: این‌طور مسیر
    واقعی انتخاب ارائه‌دهنده و ساخت پرامپت هم زیر تست می‌رود.
    """

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        super().setUp()
        APIConfig.objects.create(
            name='تستی', api_key='k', model_name='test-model',
            priority=1, is_active=True,
        )

    def test_extra_notes_reaches_ai_prompt(self):
        from ai_engine.ai_generator import generate_program

        with patch('ai_engine.ai_generator.build_client') as mock_build:
            completion = mock_build.return_value.chat.completions.create
            completion.return_value = _fake_completion('## برنامه ورزشی\nتست')

            user = create_user(phone='09121234567')
            program = ClientProgram.objects.create(
                user=user, name='علی', program_type='workout',
                extra_notes='فقط شب‌ها تمرین می‌کند',
            )
            generate_program(program.id, 'workout')

        sent_prompt = completion.call_args.kwargs['messages'][1]['content']
        self.assertIn('توضیحات تکمیلی', sent_prompt)
        self.assertIn('فقط شب‌ها تمرین می‌کند', sent_prompt)

    def test_coach_instructions_reach_ai_prompt(self):
        """دستورالعمل ثابت مربی هم باید در پرامپت باشد."""
        from ai_engine.ai_generator import generate_program

        user = create_user(phone='09121234567')
        GymBrand.objects.create(
            user=user, gym_name='باشگاه تست',
            program_instructions='همیشه اسکات را اول جلسه بگذار',
        )

        with patch('ai_engine.ai_generator.build_client') as mock_build:
            completion = mock_build.return_value.chat.completions.create
            completion.return_value = _fake_completion('## برنامه ورزشی\nتست')

            program = ClientProgram.objects.create(
                user=user, name='علی', program_type='workout',
            )
            generate_program(program.id, 'workout')

        sent_prompt = completion.call_args.kwargs['messages'][1]['content']
        self.assertIn('همیشه اسکات را اول جلسه بگذار', sent_prompt)

    def test_generation_survives_first_provider_outage(self):
        """قطعی ارائه‌دهنده‌ی اول نباید تولید برنامه را بشکند."""
        from ai_engine.ai_generator import generate_program

        APIConfig.objects.all().delete()
        APIConfig.objects.create(
            name='محلی خاموش', provider_type=APIConfig.TYPE_LOCAL,
            base_url='http://localhost:11434/v1', model_name='llama3.2',
            priority=1, is_active=True,
        )
        APIConfig.objects.create(
            name='ابری سالم', base_url='https://api.metisai.ir/openai/v1',
            api_key='k', model_name='gpt-4o-mini', priority=2, is_active=True,
        )

        def build(config):
            if 'localhost' in config['base_url']:
                raise ConnectionError('Connection refused')
            client = MagicMock()
            client.chat.completions.create.return_value = _fake_completion(
                '## برنامه ورزشی\nاز ارائه‌دهنده دوم'
            )
            return client

        user = create_user(phone='09121234567')
        program = ClientProgram.objects.create(
            user=user, name='علی', program_type='workout',
        )

        with patch('ai_engine.ai_generator.build_client', side_effect=build):
            workout, meal, usage = generate_program(program.id, 'workout')

        self.assertIn('از ارائه‌دهنده دوم', workout)
        self.assertEqual(usage.provider_config['name'], 'ابری سالم')


class EditProgramAPITests(BaseAPITestCase):
    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.user.token_balance = 100
        self.user.save()
        self.program = ClientProgram.objects.create(
            user=self.user, name='علی',
            generated_workout='برنامه اولیه', generated_meal_plan='غذای اولیه',
            tokens_consumed=50,
        )
        self.auth(self.user)

    @patch('app.views.edit_program_with_feedback', return_value=('برنامه اصلاح‌شده', 'غذای اصلاح‌شده', _usage()))
    def test_edit_success(self, mock_edit):
        url = f'/api/programs/{self.program.id}/edit/'
        response = self.client.post(url, {'feedback': 'روز سوم را سبک‌تر کن'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.program.refresh_from_db()
        self.assertEqual(self.program.generated_workout, 'برنامه اصلاح‌شده')
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 75)  # 100 - 25

    @patch('app.views.edit_program_with_feedback', return_value=('w', 'm', _usage()))
    def test_edit_costs_same_as_single_section_program(self, mock_edit):
        """ویرایش ۲۵ توکن است — هم‌قیمت برنامه فقط-ورزشی/فقط-غذایی"""
        from app.views import TOKEN_COSTS, PROGRAM_TYPE_COSTS
        self.assertEqual(TOKEN_COSTS['edit_program'], 25)
        self.assertEqual(PROGRAM_TYPE_COSTS['workout'], 25)
        self.assertEqual(PROGRAM_TYPE_COSTS['meal'], 25)
        self.assertEqual(PROGRAM_TYPE_COSTS['both'], 50)

    def test_edit_insufficient_tokens_reports_25(self):
        self.user.token_balance = 24
        self.user.save()
        response = self.client.post(
            f'/api/programs/{self.program.id}/edit/', {'feedback': 'تست'}
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data['required_tokens'], 25)

    def test_edit_other_users_program_404(self):
        other = create_user(phone='09127654321')
        other.token_balance = 100
        other.save()
        self.auth(other)
        url = f'/api/programs/{self.program.id}/edit/'
        response = self.client.post(url, {'feedback': 'تست'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProgramDetailHistoryTests(BaseAPITestCase):
    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.user = create_user(phone='09121234567')
        self.program = ClientProgram.objects.create(
            user=self.user, name='علی',
            generated_workout='ورزشی', generated_meal_plan='غذایی',
        )
        self.auth(self.user)

    def test_program_detail(self):
        response = self.client.get(f'/api/programs/{self.program.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'علی')

    def test_program_detail_scoped_to_owner(self):
        other = create_user(phone='09127654321')
        self.auth(other)
        response = self.client.get(f'/api/programs/{self.program.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_history_lists_generated_programs(self):
        ClientProgram.objects.create(user=self.user, name='بدون خروجی')  # نباید در تاریخچه بیاید
        response = self.client.get('/api/programs/history/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'علی')

    def test_history_includes_meal_only_program(self):
        """برنامه فقط-غذایی هم باید در تاریخچه بیاید"""
        ClientProgram.objects.create(
            user=self.user, name='رضا', program_type='meal',
            generated_meal_plan='فقط غذایی',
        )
        response = self.client.get('/api/programs/history/')
        self.assertEqual(len(response.data), 2)
        names = {item['name'] for item in response.data}
        self.assertIn('رضا', names)

    @patch('app.views.generate_workout_pdf', return_value=(b'%PDF-1.4 fake', 'pdf'))
    def test_workout_pdf_download(self, mock_pdf):
        response = self.client.get(f'/api/programs/{self.program.id}/pdf-workout/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_workout_pdf_without_program_400(self):
        empty = ClientProgram.objects.create(user=self.user, name='خالی')
        response = self.client.get(f'/api/programs/{empty.id}/pdf-workout/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CoachClientProgramHistoryTests(BaseAPITestCase):
    """مربی باید برنامه‌های هر مشتری را در تاریخچه پیدا کند تا بتواند ویرایششان کند.

    قبلاً فیلتر client_id فقط برنامه‌هایی را برمی‌گرداند که خودِ ورزشکار ساخته
    بود؛ برنامه‌ای که مربی برای او ساخته بود گم می‌شد و مربی ID لازم برای
    ویرایش را پیدا نمی‌کرد.
    """

    def setUp(self):
        # قاعدهٔ «۵ برنامهٔ رایگانِ هوش مصنوعی» این‌جا خاموش است؛ این آزمون
        # ریاضیِ کسرِ توکن را می‌سنجد، نه سهمیهٔ رایگان را.
        from app.models import PlatformSettings as _PS
        _PS.objects.all().delete()
        _PS.objects.create(ai_free_programs=0)
        self.coach = create_user(phone='09121234567', gym_name='باشگاه من')
        self.coach.token_balance = 200
        self.coach.save()
        self.gym_client = GymClient.objects.create(gym_owner=self.coach, name='رضا')
        self.client.post('/api/client-access/', {'access_code': self.gym_client.access_code})
        self.gym_client.refresh_from_db()
        self.athlete = self.gym_client.client_user
        self.auth(self.coach)

    def test_client_filter_includes_coach_made_program(self):
        by_coach = ClientProgram.objects.create(
            user=self.coach, name='رضا', generated_workout='ساخت مربی')
        by_athlete = ClientProgram.objects.create(
            user=self.athlete, name='رضا', generated_workout='ساخت ورزشکار')

        response = self.client.get(f'/api/programs/history/?client_id={self.gym_client.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item['id'] for item in response.data}
        self.assertEqual(ids, {by_coach.id, by_athlete.id})

    def test_client_filter_works_before_code_activation(self):
        """مشتری‌ای که هنوز کد را فعال نکرده هم باید برنامه‌هایش پیدا شود"""
        inactive = GymClient.objects.create(gym_owner=self.coach, name='سارا')
        program = ClientProgram.objects.create(
            user=self.coach, name='سارا', generated_workout='ساخت مربی')

        response = self.client.get(f'/api/programs/history/?client_id={inactive.id}')
        self.assertEqual([item['id'] for item in response.data], [program.id])

    def test_client_filter_excludes_other_clients(self):
        ClientProgram.objects.create(user=self.coach, name='رضا', generated_workout='مال رضا')
        ClientProgram.objects.create(user=self.coach, name='سارا', generated_workout='مال سارا')

        response = self.client.get(f'/api/programs/history/?client_id={self.gym_client.id}')
        self.assertEqual([item['name'] for item in response.data], ['رضا'])

    def test_client_filter_rejects_other_coachs_client(self):
        stranger = create_user(phone='09127654321', gym_name='باشگاه دیگر')
        foreign = GymClient.objects.create(gym_owner=stranger, name='کسی')
        response = self.client.get(f'/api/programs/history/?client_id={foreign.id}')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('app.views.edit_program_with_feedback', return_value=('اصلاح‌شده', 'غذای اصلاح‌شده', _usage()))
    def test_coach_can_edit_program_he_made_for_client(self, mock_edit):
        program = ClientProgram.objects.create(
            user=self.coach, name='رضا',
            generated_workout='اولیه', generated_meal_plan='غذای اولیه')
        response = self.client.post(
            f'/api/programs/{program.id}/edit/', {'feedback': 'سبک‌تر کن'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        program.refresh_from_db()
        self.assertEqual(program.generated_workout, 'اصلاح‌شده')
        self.coach.refresh_from_db()
        self.assertEqual(self.coach.token_balance, 175)  # 200 - 25

    @patch('app.views.edit_program_with_feedback', return_value=('اصلاح‌شده', 'غذای اصلاح‌شده', _usage()))
    def test_coach_can_edit_program_athlete_made(self, mock_edit):
        program = ClientProgram.objects.create(
            user=self.athlete, name='رضا',
            generated_workout='اولیه', generated_meal_plan='غذای اولیه')
        response = self.client.post(
            f'/api/programs/{program.id}/edit/', {'feedback': 'سبک‌تر کن'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        program.refresh_from_db()
        self.assertEqual(program.generated_workout, 'اصلاح‌شده')
