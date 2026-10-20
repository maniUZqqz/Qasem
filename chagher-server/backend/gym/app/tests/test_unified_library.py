# -*- coding: utf-8 -*-
"""مورد ۵ — یک کتابخانهٔ دستگاه + حرکتِ خودِ مربی.

چیزی که این‌جا نگه داشته می‌شود، همان شکایتِ مالک است: «دو کتابخانهٔ دستگاه
گسسته‌اند» و «مربی نمی‌تواند حرکت اضافه کند».
"""
import io

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from app.models import (CustomUser, Equipment, EquipmentCatalog,
                        ExerciseLibrary, PlatformSettings)


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def an_image(name='x.jpg'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), (10, 120, 130)).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


class UnifiedEquipmentTests(APITestCase):
    def setUp(self):
        self.coach = CustomUser.objects.create_user(phone_number='09120000060', password='x')
        self.client.force_authenticate(user=self.coach)
        PlatformSettings.objects.all().delete()
        PlatformSettings.objects.create()
        self.catalog = EquipmentCatalog.objects.create(
            name='دستگاه قفسهٔ سینه (پک‌دک)',
            aliases='پک دک، باترفلای، قفسه سینه',
            muscle_group='سینه',
            image=an_image('pecdeck.jpg'),
        )

    def test_manual_equipment_links_to_catalog(self):
        """دستگاهی که مربی دستی اضافه می‌کند باید به کاتالوگ گره بخورد."""
        res = self.client.post(url('equipment-list'),
                               {'name': 'قفسه سینه'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        eq = Equipment.objects.get()
        self.assertEqual(eq.catalog_id, self.catalog.id,
                         'نامِ هم‌معنی باید به همان ردیفِ کاتالوگ وصل شود')
        self.assertEqual(eq.muscle_group, 'سینه', 'گروهِ عضلانی از کاتالوگ پر شود')
        self.assertTrue(eq.display_image_url(), 'عکسِ مرجع باید دیده شود')

    def test_alias_matches_too(self):
        self.client.post(url('equipment-list'), {'name': 'باترفلای'}, format='json')
        self.assertEqual(Equipment.objects.get().catalog_id, self.catalog.id)

    def test_unknown_name_creates_pending_catalog_row(self):
        """نامِ ناشناخته ردیفِ غیرفعال می‌سازد: پیوستگی بله، آلودگیِ اسکن نه."""
        res = self.client.post(url('equipment-list'),
                               {'name': 'دستگاهِ عجیبِ باشگاهِ من'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        eq = Equipment.objects.get()
        self.assertIsNotNone(eq.catalog_id)
        row = EquipmentCatalog.objects.get(pk=eq.catalog_id)
        self.assertFalse(row.is_active, 'تا تأییدِ مدیر نباید در اسکن پیشنهاد شود')
        self.assertIn('بازبینی', row.notes or '')

    def test_api_returns_image_and_catalog(self):
        self.client.post(url('equipment-list'), {'name': 'پک دک'}, format='json')
        res = self.client.get(url('equipment-list'))
        row = (res.data if isinstance(res.data, list) else res.data['results'])[0]
        self.assertEqual(row['catalog_name'], self.catalog.name)
        self.assertTrue(row['image_url'])

    def test_ai_sees_one_name_per_equipment(self):
        """دو نامِ متفاوت از یک دستگاه، برای مدل یک سطر می‌شود."""
        self.client.post(url('equipment-list'), {'name': 'پک دک'}, format='json')
        self.client.post(url('equipment-list'), {'name': 'قفسه سینه'}, format='json')
        from ai_engine.ai_generator import get_context_data
        eq_str, _, names, _ = get_context_data(self.coach)
        self.assertEqual(len(names), 1, 'باید یک نامِ یکتا بماند: %s' % names)
        self.assertEqual(eq_str.count('\n'), 0)


class CoachExerciseTests(APITestCase):
    def setUp(self):
        self.coach = CustomUser.objects.create_user(phone_number='09120000061', password='x')
        self.other = CustomUser.objects.create_user(phone_number='09120000062', password='x')
        self.client.force_authenticate(user=self.coach)
        self.global_ex = ExerciseLibrary.objects.create(
            external_id='9300', name='Bench Press', name_fa='پرس سینه با هالتر',
            is_active=True, owner=None,
        )

    def test_coach_can_add_exercise(self):
        res = self.client.post(url('my-exercises'), {
            'name_fa': 'حرکتِ خاصِ من',
            'equipment_fa': 'هالتر',
            'steps_fa': 'گام یک\nگام دو',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        ex = ExerciseLibrary.objects.get(owner=self.coach)
        self.assertEqual(ex.name_fa, 'حرکتِ خاصِ من')
        self.assertEqual(ex.steps_fa, ['گام یک', 'گام دو'])
        self.assertTrue(ex.external_id.startswith('u%s-' % self.coach.pk))

    def test_own_exercise_is_searchable_by_owner_only(self):
        self.client.post(url('my-exercises'), {'name_fa': 'حرکتِ خاصِ من'}, format='json')
        res = self.client.get(url('exlib-list'), {'search': 'خاصِ من'})
        self.assertEqual(res.data['count'], 1)

        self.client.force_authenticate(user=self.other)
        res = self.client.get(url('exlib-list'), {'search': 'خاصِ من'})
        self.assertEqual(res.data['count'], 0, 'حرکتِ یک مربی نباید در کتابخانهٔ دیگری بیاید')

    def test_global_library_still_visible(self):
        res = self.client.get(url('exlib-list'), {'search': 'پرس سینه'})
        self.assertEqual(res.data['count'], 1)

    def test_duplicate_name_warns_but_allows(self):
        res = self.client.post(url('my-exercises'),
                               {'name_fa': 'پرس سینه با هالتر'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNotNone(res.data['similar_global'])
        self.assertIn('سراسری', res.data['message'])

    def test_edit_and_delete_own_only(self):
        created = self.client.post(url('my-exercises'), {'name_fa': 'حرکتِ من'}, format='json')
        ext = created.data['exercise']['external_id']
        res = self.client.patch(url('my-exercise-detail', ext),
                                {'name_fa': 'حرکتِ منِ اصلاح‌شده'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(ExerciseLibrary.objects.get(external_id=ext).name_fa,
                         'حرکتِ منِ اصلاح‌شده')

        # حرکتِ سراسری از این مسیر دست‌نخورده می‌ماند
        res = self.client.patch(url('my-exercise-detail', '9300'),
                                {'name_fa': 'دستکاری'}, format='json')
        self.assertEqual(res.status_code, 404)

        res = self.client.delete(url('my-exercise-detail', ext))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(ExerciseLibrary.objects.filter(external_id=ext).exists())

    def test_other_coach_cannot_touch_mine(self):
        created = self.client.post(url('my-exercises'), {'name_fa': 'حرکتِ من'}, format='json')
        ext = created.data['exercise']['external_id']
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.delete(url('my-exercise-detail', ext)).status_code, 404)
