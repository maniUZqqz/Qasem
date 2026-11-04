from django.test import override_settings

from rest_framework.test import APIClient

from .models import MobileActionLog, MobileDevice, hash_token
from .tests_base import BASE, MobileTestCase
from . import phone


class PhoneTests(MobileTestCase):
    def test_normalize_all_spellings(self):
        for raw in ("09121234567", "+98 912 123 4567", "0098-912-1234567", "۰۹۱۲۱۲۳۴۵۶۷", "9121234567", "+989121234567"):
            self.assertEqual(phone.normalize(raw), "989121234567", raw)
        self.assertEqual(phone.key("09121234567"), "9121234567")
        self.assertEqual(phone.normalize("+44 20 7946 0958"), "442079460958")
        self.assertEqual(phone.national("989121234567"), "09121234567")

    def test_stop_words(self):
        for text in ("لغو", "  لغو ", "STOP", "stop.", "لغو۱۱", "لغو عضویت", "Unsubscribe", "توقف", "لغو لطفا"):
            self.assertTrue(phone.is_stop_text(text), text)
        for text in ("سلام", "لطفا سفارش من را به خاطر تاخیر زیاد لغو کنید چون نرسید", "ok", ""):
            self.assertFalse(phone.is_stop_text(text), text)


class PairingTests(MobileTestCase):
    def test_pair_staff_gets_token_and_only_hash_is_stored(self):
        r = self.pair()
        self.assertEqual(r.status_code, 201)
        token = r.data["device_token"]
        self.assertTrue(token.startswith("nmd_"))
        dev = MobileDevice.objects.get()
        self.assertEqual(dev.token_hash, hash_token(token))
        self.assertNotIn(token, str(dev.__dict__))
        self.assertEqual(r.data["user"]["username"], "marketer")
        self.assertEqual(r.data["server"]["api_version"], 1)
        log = MobileActionLog.objects.get(action="device.pair")
        self.assertEqual(log.user, self.staff)
        self.assertEqual(log.device, dev)

    def test_non_staff_and_bad_password_refused(self):
        self.assertEqual(self.pair("plain").status_code, 403)
        self.assertEqual(self.pair("plain").data["error"]["code"], "not_staff")
        c = APIClient()
        r = c.post(BASE + "pair/", {"username": "marketer", "password": "wrong", "device_name": "x", "install_id": "i"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (401, "bad_credentials"))
        self.assertEqual(MobileDevice.objects.count(), 0)

    def test_missing_fields(self):
        r = APIClient().post(BASE + "pair/", {"username": "marketer"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (400, "missing_fields"))

    def test_repair_same_install_replaces_token(self):
        t1 = self.pair().data["device_token"]
        t2 = self.pair().data["device_token"]
        self.assertNotEqual(t1, t2)
        self.assertEqual(MobileDevice.objects.count(), 1)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Device " + t1)
        self.assertEqual(c.get(BASE + "me/").status_code, 401)
        c.credentials(HTTP_AUTHORIZATION="Device " + t2)
        self.assertEqual(c.get(BASE + "me/").status_code, 200)

    def test_revoked_device_gets_401_device_revoked(self):
        c = self.device_client()
        self.assertEqual(c.get(BASE + "me/").status_code, 200)
        panel = self.panel_client()
        r = panel.post(BASE + f"admin/devices/{c.device_uid}/revoke/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        r = c.get(BASE + "me/")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (401, "device_revoked"))
        self.assertTrue(MobileActionLog.objects.filter(action="device.revoke", user=self.boss).exists())

    def test_user_losing_staff_is_refused(self):
        c = self.device_client()
        self.staff.is_staff = False
        self.staff.save()
        r = c.get(BASE + "me/")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "not_staff"))

    def test_unknown_token_and_no_token(self):
        c = APIClient()
        self.assertEqual(c.get(BASE + "me/").status_code, 401)
        c.credentials(HTTP_AUTHORIZATION="Device nmd_garbage")
        r = c.get(BASE + "me/")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (401, "device_revoked"))

    def test_unpair_revokes(self):
        c = self.device_client()
        self.assertEqual(c.post(BASE + "unpair/", {}, format="json").status_code, 200)
        self.assertEqual(c.get(BASE + "me/").status_code, 401)

    def test_phone_cannot_use_panel_endpoints(self):
        c = self.device_client()
        r = c.get(BASE + "admin/devices/")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "panel_only"))
        self.assertEqual(self.panel_client(self.plain).get(BASE + "admin/devices/").status_code, 403)

    def test_me_and_heartbeat(self):
        c = self.device_client()
        me = c.get(BASE + "me/").data
        self.assertTrue(me["settings"]["sms_enabled"])
        self.assertIn("remaining_hour", me["sms"])
        r = c.post(BASE + "heartbeat/", {"battery_percent": -1, "charging": True, "network": "wifi", "sms_ready": True,
                                         "sims": [{"slot": 0, "carrier": "Irancell"}]}, format="json")
        self.assertEqual(r.status_code, 200)
        d = MobileDevice.objects.get()
        self.assertIsNone(d.battery_percent)       # -1 means unknown
        self.assertEqual(d.network, "wifi")
        self.assertTrue(d.online)

    @override_settings(MOBILE_TEST_THROTTLE=True)
    def test_pair_is_throttled_per_ip(self):
        from django.core.cache import cache

        cache.clear()
        c = APIClient()
        codes = [c.post(BASE + "pair/", {"username": "x", "password": "y", "device_name": "d", "install_id": str(i)}, format="json").status_code
                 for i in range(12)]
        self.assertIn(429, codes)
        cache.clear()

    def test_lockout_after_repeated_bad_passwords(self):
        from django.core.cache import cache

        cache.clear()
        c = APIClient()
        for _ in range(8):
            c.post(BASE + "pair/", {"username": "marketer", "password": "no", "device_name": "d", "install_id": "z"}, format="json")
        r = c.post(BASE + "pair/", {"username": "marketer", "password": self.password, "device_name": "d", "install_id": "z"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (429, "too_many_attempts"))
        cache.clear()
