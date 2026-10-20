# -*- coding: utf-8 -*-
"""آزمونِ پلِ اپِ فلاتر ← صفحه‌های جنگو.

چیزی که این‌جا نگه داشته می‌شود، همان شکایتِ مالک است: کاربر نباید حس کند از
برنامه بیرون افتاده. یعنی ۱) دوباره وارد نشود، ۲) منوی سایتِ بازاریابی را نبیند،
۳) راهِ بازگشت داشته باشد، و ۴) مشتریِ عادیِ سایت هیچ تغییری حس نکند.
"""
import json

from django.conf import settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from app.models import CustomUser, ExerciseLibrary, PlatformSettings


def url(name, *args):
    path = reverse(name, args=args)
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def strip_prefix(path):
    prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


class AppBridgeTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(phone_number='09120000040', password='x')
        self.token = Token.objects.create(user=self.user)
        PlatformSettings.objects.all().delete()
        self.cfg = PlatformSettings.objects.create(form_check_enabled=True)
        self.ex = ExerciseLibrary.objects.create(
            external_id='9200', name='Squat', name_fa='اسکوات با هالتر', is_active=True
        )

    def _sso(self, token=None, next_path=None):
        body = {'token': token or self.token.key}
        if next_path:
            body['next'] = next_path
        return self.client.post(url('panel-sso'), data=json.dumps(body),
                                content_type='application/json')

    # ───────────────────────────── ورودِ یک‌باره ─────────────────────────────
    def test_sso_logs_in_without_a_form(self):
        res = self._sso()
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['phone_number'], '09120000040')
        self.assertEqual(self.client.session['_auth_user_id'], str(self.user.pk))
        self.assertTrue(self.client.session['from_app'])

        page = self.client.get(url('panel-home'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="password"')

    def test_sso_honours_next_from_json_body(self):
        res = self._sso(next_path=url('panel-scan'))
        self.assertEqual(strip_prefix(res.json()['next']), url('panel-scan'))

    def test_sso_get_redirects(self):
        res = self.client.get(url('panel-sso'),
                              {'token': self.token.key, 'next': url('panel-me')})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(strip_prefix(res['Location']), url('panel-me'))

    def test_sso_rejects_bad_token(self):
        res = self._sso(token='0' * 40)
        self.assertEqual(res.status_code, 401)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_sso_ignores_external_next(self):
        """آدرسِ بیرونی نباید باز شود (جلوی open redirect)."""
        for bad in ['https://evil.example/x', '//evil.example/x']:
            res = self._sso(next_path=bad)
            self.assertEqual(strip_prefix(res.json()['next']), url('panel-home'), bad)

    # ───────────────────────────── حالتِ اپ ─────────────────────────────
    def test_app_mode_hides_site_chrome(self):
        self._sso()
        for name, args in [('panel-home', ()), ('panel-scan', ()),
                           ('exercise-detail', ('9200',)), ('form-check-page', ('9200',))]:
            page = self.client.get(url(name, *args))
            self.assertEqual(page.status_code, 200, name)
            html = page.content.decode('utf-8')
            self.assertNotIn('<header>', html, name)
            self.assertNotIn('<footer>', html, name)
            self.assertNotIn('<ul class="nav-links"', html, name)
            self.assertIn('class="app-bar"', html, name)
            self.assertIn('بازگشت به اپ', html, name)

    def test_plain_website_is_untouched(self):
        """مشتریِ عادیِ سایت باید همان سایتِ همیشگی را ببیند."""
        page = self.client.get(url('exercise-detail', '9200'))
        html = page.content.decode('utf-8')
        self.assertIn('<header>', html)
        self.assertIn('<footer>', html)
        self.assertNotIn('class="app-bar"', html)

    def test_browser_login_is_not_app_mode(self):
        """ورودِ معمولی با رمز در مرورگر، حالتِ اپ نیست."""
        self.client.post(url('panel-login'),
                         {'phone_number': '09120000040', 'password': 'x'})
        page = self.client.get(url('panel-home'))
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('class="app-bar"', page.content.decode('utf-8'))

    # ───────────────────────── فهرستِ قابلیت‌ها ─────────────────────────
    def test_features_follow_admin_switch(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get(url('my-features'))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data['form_check'])
        from urllib.parse import urlparse
        scan_url = res.data['urls']['equipment_scan']
        self.assertTrue(scan_url.startswith('http'),
                        'آدرس باید مطلق باشد تا اپ مسیر را حدس نزند')
        self.assertEqual(strip_prefix(urlparse(scan_url).path), url('panel-scan'))

        self.cfg.form_check_enabled = False
        self.cfg.save()
        res = self.client.get(url('my-features'))
        self.assertFalse(res.data['form_check'],
                         'خاموشی در ادمین باید در فهرستِ قابلیت‌ها هم دیده شود')

    def test_features_need_auth(self):
        self.assertEqual(self.client.get(url('my-features')).status_code, 401)

    # ───────────────────── گره‌خوردنِ نشست به توکنِ اپ ─────────────────────
    def test_app_logout_closes_web_session(self):
        self._sso()
        self.assertEqual(self.client.get(url('panel-home')).status_code, 200)
        # کاربر در اپ «خروج» می‌زند ⇒ توکن پاک می‌شود
        self.token.delete()
        res = self.client.get(url('panel-home'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(url('panel-login'), strip_prefix(res['Location']))
        self.assertNotIn('_auth_user_id', self.client.session)
