# -*- coding: utf-8 -*-
"""دو میزبانِ B2C (لندینگ + پنل) و مرزِ نقش‌محور.

این‌ها از بازبینیِ کلمه‌به‌کلمهٔ پرامپت درآمدند:
  · «دو تا دیگه هم برای بی‌تو‌سی اد بشه چون قرار شد هم پنل هم هوم‌پیج»
  · ورزشکار نباید ابزارِ مربی را باز کند (نه روی هیچ میزبانی)
"""
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import CustomUser, PlatformSettings


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


LANDING = 'app.chagher.ir'
PANEL = 'my.chagher.ir'
B2B = 'chagher.ir'


@override_settings(ALLOWED_HOSTS=['*'], B2C_HOSTS=[LANDING, PANEL],
                   B2C_PANEL_HOST=PANEL, B2B_HOST=B2B)
class B2CTwoHostsTests(TestCase):
    def setUp(self):
        PlatformSettings.objects.all().delete()
        PlatformSettings.objects.create(ai_free_programs=5)

    def test_landing_host_shows_landing(self):
        res = self.client.get('/', HTTP_HOST=LANDING)
        self.assertEqual(res.status_code, 200)
        self.assertIn('برنامهٔ ورزشی و غذاییِ اختصاصیِ خودت',
                      res.content.decode('utf-8'))

    def test_panel_host_goes_straight_to_athlete_panel(self):
        """قرینهٔ panel.chagher.ir: ریشه = پنل، نه لندینگ."""
        res = self.client.get('/', HTTP_HOST=PANEL)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/panel/me/', res['Location'])

    def test_landing_links_to_panel_host(self):
        res = self.client.get('/', HTTP_HOST=LANDING)
        self.assertIn(PANEL, res.content.decode('utf-8'))

    def test_b2b_landing_untouched(self):
        res = self.client.get('/', HTTP_HOST=B2B)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('برنامهٔ ورزشی و غذاییِ اختصاصیِ خودت',
                         res.content.decode('utf-8'))

    def test_athlete_cannot_open_coach_tool_on_any_host(self):
        athlete = CustomUser.objects.create_user(
            phone_number='09120000080', password='x',
            account_type=CustomUser.ACCOUNT_TYPE_PERSONAL)
        self.client.force_login(athlete)
        for host in (B2B, LANDING, PANEL):
            res = self.client.get(url('panel-manual-program'), HTTP_HOST=host)
            self.assertEqual(res.status_code, 302, host)

    def test_coach_keeps_access(self):
        coach = CustomUser.objects.create_user(phone_number='09120000081', password='x')
        self.client.force_login(coach)
        res = self.client.get(url('panel-manual-program'), HTTP_HOST=B2B)
        self.assertEqual(res.status_code, 200)

    def test_coach_tool_redirects_to_b2b_on_b2c_hosts(self):
        coach = CustomUser.objects.create_user(phone_number='09120000082', password='x')
        self.client.force_login(coach)
        res = self.client.get(url('panel-manual-program'), HTTP_HOST=LANDING)
        self.assertEqual(res.status_code, 302)
        self.assertIn(B2B, res['Location'])
