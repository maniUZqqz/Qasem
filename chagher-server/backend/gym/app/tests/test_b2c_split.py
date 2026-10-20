# -*- coding: utf-8 -*-
"""مورد ۱ — جداییِ دنیای ورزشکار (B2C) از باشگاه (B2B).

قاعده‌هایی که نباید بشکنند:
  · روی میزبانِ B2C، خانه = لندینگِ ورزشکار؛ روی B2B همان سایتِ قبلی.
  · ابزارِ مربی روی میزبانِ B2C باز نشود.
  · ورزشکارِ شخصی در پنلِ B2B به میزبانِ خودش هدایت شود.
"""
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import CustomUser, PlatformSettings


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


B2C = 'app.chagher.ir'
B2B = 'chagher.ir'


@override_settings(ALLOWED_HOSTS=['*'], B2C_HOSTS=[B2C], B2B_HOST=B2B)
class B2CSplitTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.all().delete()
        PlatformSettings.objects.create(ai_free_programs=5)

    def test_b2c_host_gets_athlete_landing(self):
        res = self.client.get('/', HTTP_HOST=B2C)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        self.assertIn('برنامهٔ ورزشی و غذاییِ اختصاصیِ خودت', html)
        self.assertIn('باشگاهت را اسکن کن', html)
        self.assertIn(B2B, html, 'باید راهِ پنلِ باشگاه‌ها را هم نشان بدهد')

    def test_b2b_host_unchanged(self):
        res = self.client.get('/', HTTP_HOST=B2B)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('برنامهٔ ورزشی و غذاییِ اختصاصیِ خودت',
                         res.content.decode('utf-8'))

    def test_free_program_count_comes_from_admin(self):
        cfg = PlatformSettings.get_solo()
        cfg.ai_free_programs = 7
        cfg.save()
        res = self.client.get('/', HTTP_HOST=B2C)
        self.assertIn('7', res.content.decode('utf-8'))

    def test_coach_tool_is_closed_on_b2c_host(self):
        res = self.client.get(url('panel-manual-program'), HTTP_HOST=B2C)
        self.assertEqual(res.status_code, 302)
        self.assertIn(B2B, res['Location'])

    def _athlete(self):
        athlete = CustomUser.objects.create_user(
            phone_number='09120000070', password='x',
            account_type=CustomUser.ACCOUNT_TYPE_PERSONAL)
        self.client.force_login(athlete)
        return athlete

    def test_no_redirect_until_admin_turns_split_on(self):
        """قاعدهٔ ایمنی: تا رکوردِ DNS ساخته و کلید روشن نشده، هیچ هدایتی نباشد.

        وگرنه ورزشکارِ امروز به آدرسی فرستاده می‌شد که در DNS وجود ندارد.
        """
        self._athlete()
        cfg = PlatformSettings.get_solo()
        self.assertFalse(cfg.b2c_split_active, 'پیش‌فرض باید خاموش باشد')
        res = self.client.get(url('panel-me'), HTTP_HOST=B2B)
        self.assertEqual(res.status_code, 200, 'با کلیدِ خاموش نباید هدایت شود')

    def test_athlete_panel_redirects_when_split_is_on(self):
        self._athlete()
        cfg = PlatformSettings.get_solo()
        cfg.b2c_split_active = True
        cfg.save()
        res = self.client.get(url('panel-me'), HTTP_HOST=B2B)
        self.assertEqual(res.status_code, 302)
        self.assertIn(B2C, res['Location'])

    def test_coach_stays_on_b2b(self):
        coach = CustomUser.objects.create_user(phone_number='09120000071', password='x')
        self.client.force_login(coach)
        res = self.client.get(url('panel-manual-program'), HTTP_HOST=B2B)
        self.assertEqual(res.status_code, 200, 'مربی در میزبانِ خودش نباید هدایت شود')

    def test_request_flag_is_set(self):
        """`request.is_b2c` پایهٔ همهٔ قاعده‌هاست؛ باید درست ست شود."""
        res = self.client.get(url('exercise-list'), HTTP_HOST=B2C)
        self.assertEqual(res.status_code, 200)
        res = self.client.get(url('exercise-list'), HTTP_HOST=B2B)
        self.assertEqual(res.status_code, 200)
