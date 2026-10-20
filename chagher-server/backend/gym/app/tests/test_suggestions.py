# -*- coding: utf-8 -*-
"""تست‌های پیشنهاد دستگاه‌ها و حرکات (برای هر دو دنیای B2B و B2C)"""
from rest_framework import status

from app.models import CustomUser, Equipment
from app.suggestions import get_suggestions
from .utils import BaseAPITestCase, create_user


def create_personal(phone='09150000001'):
    return CustomUser.objects.create_user(
        phone_number=phone, password='StrongPass123',
        account_type=CustomUser.ACCOUNT_TYPE_PERSONAL,
    )


class SuggestionRankingTests(BaseAPITestCase):
    """پرتکرارترین‌ها باید بالاتر از کاتالوگ پایه بیایند"""

    def setUp(self):
        self.coach = create_user(phone='09121234567')

    def test_starter_catalog_when_no_data(self):
        """شروع سرد: بدون داده واقعی هم پیشنهاد خالی نیست"""
        items = get_suggestions(user=self.coach)
        self.assertGreater(len(items), 0)
        self.assertTrue(all(i['source'] == 'starter' for i in items))

    def test_popular_equipment_ranks_first(self):
        # سه مربی «اسکوات هالتر» ثبت می‌کنند، دو نفر «تردمیل»
        for i in range(3):
            u = create_user(phone='0912000000%d' % i)
            Equipment.objects.create(user=u, name='اسکوات هالتر', muscle_group='پا')
        for i in range(2):
            u = create_user(phone='0912888888%d' % i)
            Equipment.objects.create(user=u, name='تردمیل', muscle_group='هوازی')

        items = get_suggestions(user=self.coach)
        self.assertEqual(items[0]['name'], 'اسکوات هالتر')
        self.assertEqual(items[0]['usage_count'], 3)
        self.assertEqual(items[0]['source'], 'community')

        self.assertEqual(items[1]['name'], 'تردمیل')
        self.assertEqual(items[1]['usage_count'], 2)

    def test_junk_entry_by_single_user_not_suggested(self):
        """ورودی بی‌معنی که فقط یک نفر ثبت کرده نباید به بقیه پیشنهاد شود"""
        u = create_user(phone='09120000009')
        Equipment.objects.create(user=u, name='asdasd123', muscle_group='')

        items = get_suggestions(user=self.coach, limit=100)
        self.assertNotIn('asdasd123', {i['name'] for i in items})

    def test_junk_becomes_suggestion_after_enough_users(self):
        """همان نام وقتی چند کاربر ثبتش کنند، دیگر پرکاربرد شمرده می‌شود"""
        for i in range(2):
            u = create_user(phone='0912777777%d' % i)
            Equipment.objects.create(user=u, name='دستگاه محلی من', muscle_group='پا')

        items = get_suggestions(user=self.coach, limit=100)
        match = next((i for i in items if i['name'] == 'دستگاه محلی من'), None)
        self.assertIsNotNone(match)
        self.assertEqual(match['usage_count'], 2)

    def test_catalog_name_shown_even_with_single_user(self):
        """نام معتبر کاتالوگ حتی با یک ثبت هم می‌ماند (نام آشناست، آشغال نیست)"""
        u = create_user(phone='09120000008')
        Equipment.objects.create(user=u, name='بارفیکس', muscle_group='پشت')

        items = get_suggestions(user=self.coach, limit=100)
        match = next((i for i in items if i['name'] == 'بارفیکس'), None)
        self.assertIsNotNone(match)
        self.assertEqual(match['usage_count'], 1)

    def test_usage_counts_distinct_users_not_rows(self):
        """یک کاربر با ثبت چندباره نباید آمار را باد کند"""
        u = create_user(phone='09120000001')
        for _ in range(4):
            Equipment.objects.create(user=u, name='پرس سینه هالتر', muscle_group='سینه')
        # نام کاتالوگی است پس با یک کاربر هم نمایش داده می‌شود

        items = get_suggestions(user=self.coach)
        match = next(i for i in items if i['name'] == 'پرس سینه هالتر')
        self.assertEqual(match['usage_count'], 1)

    def test_already_added_flag_for_coach(self):
        Equipment.objects.create(user=self.coach, name='پلانک', muscle_group='شکم')
        items = get_suggestions(user=self.coach)
        match = next(i for i in items if i['name'] == 'پلانک')
        self.assertTrue(match['already_added'])
        others = [i for i in items if i['name'] != 'پلانک']
        self.assertTrue(all(not i['already_added'] for i in others))


class SuggestionFilterTests(BaseAPITestCase):
    def setUp(self):
        self.user = create_user(phone='09121234567')

    def test_home_none_only_bodyweight(self):
        """خانه بدون تجهیزات نباید دستگاه باشگاهی پیشنهاد دهد"""
        items = get_suggestions(user=self.user, training_place='home_none')
        names = {i['name'] for i in items}
        self.assertIn('پلانک', names)
        self.assertNotIn('پرس پا', names)
        self.assertNotIn('تردمیل', names)

    def test_home_basic_includes_dumbbell(self):
        items = get_suggestions(user=self.user, training_place='home_basic', limit=100)
        names = {i['name'] for i in items}
        self.assertIn('پرس سینه دمبل', names)
        self.assertNotIn('پرس پا', names)

    def test_public_gym_includes_machines(self):
        items = get_suggestions(user=self.user, training_place='public_gym', limit=100)
        names = {i['name'] for i in items}
        self.assertIn('پرس پا', names)

    def test_gym_equipment_not_leaked_into_home(self):
        """دستگاه باشگاهی که کاربران ثبت کرده‌اند نباید در محیط خانگی بیاید"""
        other = create_user(phone='09129999999')
        Equipment.objects.create(user=other, name='پرس پا', muscle_group='پا')
        items = get_suggestions(user=self.user, training_place='home_none', limit=100)
        self.assertNotIn('پرس پا', {i['name'] for i in items})

    def test_muscle_group_filter(self):
        items = get_suggestions(user=self.user, muscle_group='سینه', limit=100)
        self.assertTrue(len(items) > 0)
        self.assertTrue(all('سینه' in i['muscle_group'] for i in items))

    def test_search_filter(self):
        items = get_suggestions(user=self.user, search='پلانک', limit=100)
        self.assertTrue(all('پلانک' in i['name'] for i in items))

    def test_limit_is_capped(self):
        items = get_suggestions(user=self.user, limit=9999)
        self.assertLessEqual(len(items), 100)

    def test_invalid_limit_falls_back(self):
        items = get_suggestions(user=self.user, limit='abc')
        self.assertEqual(len(items), 20)


class SuggestionAPITests(BaseAPITestCase):
    url = '/api/equipment-suggestions/'

    def test_requires_auth(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_coach_gets_suggestions(self):
        self.auth(create_user(phone='09121234567'))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(response.data['count'], 0)
        self.assertIn('muscle_groups', response.data)

    def test_personal_user_gets_suggestions(self):
        """کاربر شخصی (B2C) هم باید پیشنهاد بگیرد"""
        self.auth(create_personal())
        response = self.client.get(self.url + '?training_place=home_none')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {i['name'] for i in response.data['results']}
        self.assertIn('پلانک', names)
        self.assertNotIn('پرس پا', names)

    def test_gym_client_gets_suggestions(self):
        """ورزشکار باشگاه هم مسدود نیست"""
        user = CustomUser.objects.create_user(
            phone_number='09900000001', password=None,
            account_type=CustomUser.ACCOUNT_TYPE_GYM_CLIENT,
        )
        self.auth(user)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)

    def test_query_params_pass_through(self):
        self.auth(create_user(phone='09121234567'))
        response = self.client.get(self.url + '?muscle_group=پا&limit=3')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(response.data['count'], 3)


class BulkAddTests(BaseAPITestCase):
    url = '/api/equipments/bulk-add/'

    def setUp(self):
        self.coach = create_user(phone='09121234567')
        self.auth(self.coach)

    def test_bulk_add_creates_equipment_with_muscle_group(self):
        response = self.client.post(self.url, {
            'names': ['اسکوات هالتر', 'پلانک'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sorted(response.data['created']), sorted(['اسکوات هالتر', 'پلانک']))

        squat = Equipment.objects.get(user=self.coach, name='اسکوات هالتر')
        self.assertEqual(squat.muscle_group, 'پا')  # از کاتالوگ پر شده

    def test_duplicates_are_skipped(self):
        Equipment.objects.create(user=self.coach, name='پلانک', muscle_group='شکم')
        response = self.client.post(self.url, {'names': ['پلانک', 'برپی']}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['created'], ['برپی'])
        self.assertEqual(response.data['skipped'], ['پلانک'])
        self.assertEqual(Equipment.objects.filter(user=self.coach, name='پلانک').count(), 1)

    def test_empty_list_rejected(self):
        response = self.client.post(self.url, {'names': []}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_personal_user_cannot_bulk_add(self):
        """کاربر شخصی تجهیزات باشگاه ثبت نمی‌کند"""
        self.auth(create_personal())
        response = self.client.post(self.url, {'names': ['پلانک']}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_added_equipment_shows_as_already_added(self):
        self.client.post(self.url, {'names': ['برپی']}, format='json')
        response = self.client.get('/api/equipment-suggestions/?search=برپی')
        match = next(i for i in response.data['results'] if i['name'] == 'برپی')
        self.assertTrue(match['already_added'])
