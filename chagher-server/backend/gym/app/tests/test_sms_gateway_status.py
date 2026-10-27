"""وضعیتِ گوشیِ پیامک در ادمین: آخرین خواندن/تأییدِ گوشی ثبت و نشان داده می‌شود."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app import sms_gateway
from app.models import SMSOutbox


class GatewayStatusTests(TestCase):
    def setUp(self):
        cache.delete(sms_gateway.SEEN_KEY)
        sms_gateway._last_write.clear()

    def test_phone_poll_and_mark_are_remembered(self):
        item = SMSOutbox.enqueue('09120000000', '1234')
        r = self.client.get('/api/next-otp/', HTTP_USER_AGENT='Dart/3.13 (dart:io)')
        self.assertEqual(r.status_code, 200)
        r = self.client.post('/api/mark-sent/', data='{"id": "%s"}' % item.id, content_type='application/json',
                             HTTP_USER_AGENT='Dart/3.13 (dart:io)')
        self.assertEqual(r.status_code, 200)
        seen = sms_gateway.gateway_status()
        self.assertEqual(seen['poll_phone']['pending'], 1)
        self.assertTrue(seen['mark_phone']['ok'])
        self.assertNotIn('poll_other', seen)

    def test_browser_is_not_counted_as_phone(self):
        self.client.get('/api/next-otp/', HTTP_USER_AGENT='Mozilla/5.0')
        seen = sms_gateway.gateway_status()
        self.assertIn('poll_other', seen)
        self.assertNotIn('poll_phone', seen)

    def test_admin_banner(self):
        User = get_user_model()
        admin = User.objects.create_superuser(**{User.USERNAME_FIELD: '09000000001', 'password': 'x-test-123'}) \
            if User.USERNAME_FIELD != 'username' else User.objects.create_superuser('t_admin', 'a@b.c', 'x-test-123')
        self.client.force_login(admin)
        r = self.client.get('/admin/app/smsoutbox/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'هنوز یک بار هم سر نزده')
        self.client.get('/api/next-otp/', HTTP_USER_AGENT='Dart/3.13 (dart:io)')
        r = self.client.get('/admin/app/smsoutbox/')
        self.assertContains(r, 'گوشیِ پیامک وصل است')
