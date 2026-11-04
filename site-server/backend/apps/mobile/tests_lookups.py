"""Messenger lookup guardrails. Every platform is a fake; no real person's number is ever looked up."""
import base64
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from . import lookups, telegram_provider
from .models import LookupTicket, MobileCall, MobileSettings, ProfileLookup
from .tests_base import BASE, TMP_DATA, MobileTestCase

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
NUM = "09120001234"           # made-up number


def enable(*platforms):
    s = MobileSettings.get()
    s.lookup_platforms = {p: True for p in platforms}
    s.save()


class FakeBackend:
    """Stands in for Telethon. Records every request so tests can assert nothing extra was asked."""

    calls = []

    def __init__(self, known=None, password=False):
        self.known = known if known is not None else {"989120001234": {"id": 777, "first_name": "آزمون", "last_name": "نمونه", "username": "azmoon",
                                                                      "about": "بیوی آزمایشی", "photo": JPEG, "premium": True}}
        self.password = password

    async def send_code(self, phone):
        FakeBackend.calls.append(("send_code", phone))
        return "HASH123"

    async def sign_in(self, phone, code, code_hash):
        FakeBackend.calls.append(("sign_in", phone, code, code_hash))
        if code != "12345":
            raise type("PhoneCodeInvalidError", (Exception,), {})()
        return "password_needed" if self.password else {"id": 1, "name": "مالک", "username": "owner"}

    async def sign_in_password(self, password):
        if password != "pw":
            raise type("PasswordHashInvalidError", (Exception,), {})()
        return {"id": 1, "name": "مالک", "username": "owner"}

    async def logout(self):
        FakeBackend.calls.append(("logout",))

    async def resolve_phone(self, digits):
        FakeBackend.calls.append(("resolve", digits))
        return self.known.get(digits)


class LookupBase(MobileTestCase):
    def setUp(self):
        super().setUp()
        self.c = self.device_client()
        self.call_uid = self.c.post(BASE + "calls/live/", {"number": NUM, "direction": "in"}, format="json").data["uid"]
        FakeBackend.calls = []

    def auth(self, platform="whatsapp", number=NUM, trigger="call", call_uid="default", client=None, **kw):
        body = {"number": number, "platform": platform, "trigger": trigger, **kw}
        body["call_uid"] = self.call_uid if call_uid == "default" else call_uid
        return (client or self.c).post(BASE + "lookups/authorize/", body, format="json")

    def submit(self, ticket, **kw):
        return self.c.post(BASE + "lookups/", {"ticket": ticket, "status": "found", "on_platform": True, "display_name": "علی آزمون",
                                               "username": "@ali_test", "bio": "درباره من", **kw}, format="json")


class GuardrailTests(LookupBase):
    def test_everything_is_off_by_default(self):
        r = self.auth()
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "platform_disabled"))
        cfg = self.c.get(BASE + "lookups/config/").data
        self.assertFalse(any(p["enabled"] or p["ready"] for p in cfg["platforms"]))
        self.assertEqual([p["key"] for p in cfg["platforms"]], ["telegram", "whatsapp", "eitaa", "bale", "soroush", "rubika"])
        self.assertEqual(cfg["cache_days"], 30)
        self.assertTrue(all(p["warning"] for p in cfg["platforms"]))
        self.assertIn("فهرست", cfg["rules"])

    def test_call_trigger_needs_a_real_call_of_this_phone_in_last_24h(self):
        enable("whatsapp")
        self.assertEqual(self.auth(call_uid=None).data["error"]["code"], "no_matching_call")
        self.assertEqual(self.auth(call_uid="not-a-uuid").data["error"]["code"], "no_matching_call")
        self.assertEqual(self.auth(number="09125559999").data["error"]["code"], "no_matching_call")        # a number nobody called
        other = self.device_client("boss", "other-phone")
        self.assertEqual(self.auth(client=other).data["error"]["code"], "no_matching_call")                # someone else's call
        MobileCall.objects.filter(uid=self.call_uid).update(created_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(self.auth().data["error"]["code"], "no_matching_call")
        self.assertEqual(LookupTicket.objects.count(), 0)

    def test_ticket_for_a_real_call(self):
        enable("whatsapp")
        r = self.auth()
        self.assertEqual((r.status_code, r.data["allowed"], r.data["method"], r.data["normalized"]), (200, True, "webview", "989120001234"))
        self.assertEqual(LookupTicket.objects.get().token, r.data["ticket"])

    def test_bad_input(self):
        enable("whatsapp")
        self.assertEqual(self.auth(platform="facebook").data["error"]["code"], "bad_platform")
        self.assertEqual(self.auth(number="12").data["error"]["code"], "bad_number")
        self.assertEqual(self.auth(trigger="bulk").data["error"]["code"], "bad_trigger")

    def test_there_is_no_endpoint_that_accepts_a_list_of_numbers(self):
        enable("whatsapp")
        r = self.c.post(BASE + "lookups/authorize/", {"numbers": ["09120001234", "09120001235"], "platform": "whatsapp", "trigger": "manual"}, format="json")
        self.assertEqual(r.status_code, 400)                      # `number` is required; a list is not understood
        self.assertEqual(LookupTicket.objects.count(), 0)
        r = self.c.post(BASE + "lookups/authorize/", {"number": ["09120001234", "09120001235"], "platform": "whatsapp", "trigger": "manual"}, format="json")
        self.assertIn(r.status_code, (400, 200))
        self.assertLessEqual(LookupTicket.objects.count(), 1)
        for bulk in ("lookups/bulk/", "lookups/batch/", "lookups/import/"):
            self.assertEqual(self.c.post(BASE + bulk, {"numbers": ["09120001234"]}, format="json").status_code, 404)

    def test_manual_lookup_has_a_daily_quota_per_user(self):
        enable("whatsapp")
        s = MobileSettings.get()
        s.lookup_manual_per_user_day, s.lookup_burst_numbers_per_hour, s.lookup_per_device_hour = 3, 50, 50
        s.save()
        codes = [self.auth(number=f"091200010{i:02d}", trigger="manual", call_uid=None).status_code for i in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])

    def test_bulk_detector_blocks_many_different_numbers_from_one_phone(self):
        enable("whatsapp")
        s = MobileSettings.get()
        s.lookup_burst_numbers_per_hour, s.lookup_manual_per_user_day, s.lookup_per_device_hour = 4, 100, 100
        s.save()
        results = [self.auth(number=f"091200020{i:02d}", trigger="manual", call_uid=None) for i in range(8)]
        codes = [r.status_code for r in results]
        self.assertEqual(codes[:4], [200] * 4)                    # the 5th different number within the hour is refused
        self.assertEqual(results[4].data["error"]["code"], "bulk_blocked")
        self.assertEqual(results[4]["Retry-After"], "3600")
        # looking again at a number this phone already asked about is not "bulk"
        self.assertNotEqual(self.auth(number="09120002000", trigger="manual", call_uid=None).data.get("error", {}).get("code"), "bulk_blocked")

    def test_device_hour_day_and_platform_caps(self):
        enable("whatsapp", "bale")
        s = MobileSettings.get()
        s.lookup_per_device_hour, s.lookup_per_device_day, s.lookup_per_platform_day, s.lookup_burst_numbers_per_hour = 2, 3, 100, 50
        s.save()
        # same number, 3 refreshes of the same call are capped separately; use distinct calls
        uids = [self.c.post(BASE + "calls/live/", {"number": f"091200030{i:02d}", "direction": "out"}, format="json").data["uid"] for i in range(4)]
        out = [self.auth(number=f"091200030{i:02d}", call_uid=uids[i]) for i in range(4)]
        self.assertEqual([r.status_code for r in out], [200, 200, 429, 429])
        self.assertEqual(out[2].data["error"]["code"], "rate_limited")
        self.assertIn("Retry-After", out[2])
        s.lookup_per_device_hour, s.lookup_per_device_day, s.lookup_per_platform_day = 50, 50, 2
        s.save()
        LookupTicket.objects.all().delete()
        r1, r2, r3 = (self.auth(number=f"091200030{i:02d}", call_uid=uids[i]) for i in range(3))
        self.assertEqual((r1.status_code, r2.status_code, r3.status_code), (200, 200, 429))
        self.assertEqual(r3.data["error"]["code"], "rate_limited")
        self.assertEqual(self.auth(platform="bale", number="09120003000", call_uid=uids[0]).status_code, 200)    # other platform unaffected

    def test_only_three_tickets_per_call_per_platform(self):
        enable("whatsapp")
        s = MobileSettings.get()
        s.lookup_min_refresh_minutes = 0
        s.save()
        codes = [self.auth(refresh=True).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_phone_of_a_non_staff_user_is_refused(self):
        enable("whatsapp")
        self.staff.is_staff = False
        self.staff.save()
        self.assertEqual(self.auth().status_code, 403)


class TicketSubmitTests(LookupBase):
    def setUp(self):
        super().setUp()
        enable("whatsapp", "rubika")

    def ticket(self, **kw):
        return self.auth(**kw).data["ticket"]

    def test_full_cycle_stores_only_what_the_platform_returned_and_is_cached_30_days(self):
        t = self.ticket()
        r = self.submit(t, avatar_b64=base64.b64encode(JPEG).decode(), deep_link_id="961111",
                        field_sources={"display_name": "WhatsApp: push name", "bio": "WhatsApp: about", "avatar": "WhatsApp: profile photo",
                                       "password": "must be ignored"}, extra={"is_business": False, "nested": {"x": 1}})
        self.assertEqual(r.status_code, 201)
        p = r.data
        self.assertEqual((p["platform"], p["label"], p["status"], p["on_platform"], p["display_name"], p["username"]),
                         ("whatsapp", "واتساپ", "found", True, "علی آزمون", "ali_test"))
        self.assertEqual(p["field_sources"], {"display_name": "WhatsApp: push name", "bio": "WhatsApp: about", "avatar": "WhatsApp: profile photo"})
        self.assertEqual((p["age_days"], p["stale"], p["trigger"], p["method"]), (0, False, "call", "webview"))
        self.assertTrue(p["avatar_url"].endswith("/avatar/"))
        row = ProfileLookup.objects.get()
        self.assertEqual(row.extra, {"is_business": False})           # nested junk dropped
        self.assertEqual(row.number, "989120001234")
        # avatar is served to authenticated staff only
        img = self.c.get(p["avatar_url"])
        self.assertEqual((img.status_code, img["Content-Type"], b"".join(img.streaming_content)), (200, "image/jpeg", JPEG))
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(p["avatar_url"]).status_code, 401)
        # now cached: authorize without refresh returns the stored profile, no ticket
        again = self.auth()
        self.assertEqual((again.data["allowed"], again.data["reason"], again.data["cached"]["display_name"]), (False, "cached", "علی آزمون"))
        self.assertEqual(LookupTicket.objects.count(), 1)
        # after 31 days it is stale and a lookup is allowed again without refresh
        ProfileLookup.objects.update(looked_up_at=timezone.now() - timedelta(days=31))
        self.assertTrue(self.auth().data["allowed"])

    def test_ticket_is_single_use_and_bound_to_the_device(self):
        t = self.ticket()
        self.assertEqual(self.submit(t).status_code, 201)
        r = self.submit(t)
        self.assertEqual((r.status_code, r.data["error"]["code"]), (409, "ticket_used"))
        self.assertEqual(ProfileLookup.objects.count(), 1)
        t2 = self.ticket(platform="rubika")
        other = self.device_client("boss", "other")
        r = other.post(BASE + "lookups/", {"ticket": t2, "status": "found"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "bad_ticket"))
        r = self.c.post(BASE + "lookups/", {"ticket": "made-up", "status": "found"}, format="json")
        self.assertEqual(r.data["error"]["code"], "bad_ticket")

    def test_ticket_expires(self):
        t = self.ticket()
        LookupTicket.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.submit(t)
        self.assertEqual((r.status_code, r.data["error"]["code"]), (410, "ticket_expired"))

    def test_login_required_is_recorded_without_using_quota(self):
        s = MobileSettings.get()
        s.lookup_per_device_hour = 1
        s.save()
        t = self.ticket()
        r = self.c.post(BASE + "lookups/", {"ticket": t, "status": "login_required"}, format="json")
        self.assertEqual(r.data["status"], "login_required")
        self.assertTrue(LookupTicket.objects.get().refunded)
        self.assertEqual(self.auth().status_code, 200)               # quota of 1 is still free
        self.assertEqual(self.c.get(BASE + "lookups/latest/", {"number": NUM}).data["profiles"], [])     # not shown as a result

    def test_not_found_forces_on_platform_false_and_bad_status_rejected(self):
        t = self.ticket()
        r = self.c.post(BASE + "lookups/", {"ticket": t, "status": "not_found", "on_platform": True}, format="json")
        self.assertEqual((r.status_code, r.data["on_platform"]), (201, False))
        t2 = self.ticket(platform="rubika")
        self.assertEqual(self.c.post(BASE + "lookups/", {"ticket": t2, "status": "hacked"}, format="json").data["error"]["code"], "bad_status")

    def test_refresh_rules(self):
        t = self.ticket()
        self.submit(t)
        self.assertEqual(self.auth(refresh=True).data["error"]["code"], "recently_refreshed")
        ProfileLookup.objects.update(looked_up_at=timezone.now() - timedelta(minutes=61))
        r = self.auth(refresh=True)
        self.assertTrue(r.data["allowed"])
        self.submit(r.data["ticket"], display_name="نام تازه")
        rows = ProfileLookup.objects.order_by("id")
        self.assertEqual(rows.count(), 2)                              # history, not overwrite
        latest = self.c.get(BASE + "lookups/latest/", {"number": "0912 000 1234"}).data["profiles"]
        self.assertEqual([p["display_name"] for p in latest], ["نام تازه"])
        timeline = self.c.get(BASE + "lookups/", {"number": NUM}).data
        self.assertEqual([p["display_name"] for p in timeline["results"]], ["نام تازه", "علی آزمون"])

    def test_sanitising_and_limits(self):
        t = self.ticket()
        r = self.submit(t, display_name="x" * 500, bio="b" * 5000, avatar_b64=base64.b64encode(b"not an image at all").decode())
        row = ProfileLookup.objects.get()
        self.assertEqual((len(row.display_name), len(row.bio), row.avatar_path, r.data["avatar_url"]), (200, 1000, "", None))
        ProfileLookup.objects.all().delete()
        t = self.ticket()
        self.submit(t, avatar_b64=base64.b64encode(JPEG + b"\x00" * 400_000).decode())
        self.assertEqual(ProfileLookup.objects.get().avatar_path, "")      # > 300 KB refused, rest of the profile kept

    def test_webview_ticket_cannot_run_server_side_and_vice_versa(self):
        t = self.ticket()
        r = self.c.post(BASE + "lookups/server/", {"ticket": t}, format="json")
        self.assertEqual(r.data["error"]["code"], "wrong_method")

    def test_panel_can_read_but_the_timeline_needs_staff(self):
        t = self.ticket()
        self.submit(t)
        self.assertEqual(self.panel_client().get(BASE + "admin/lookups/").data["results"][0]["display_name"], "علی آزمون")
        self.assertEqual(self.panel_client().get(BASE + "lookups/", {"number": NUM}).data["count"], 1)
        self.assertEqual(self.panel_client(self.plain).get(BASE + "lookups/", {"number": NUM}).status_code, 403)

    def test_callerid_includes_profiles(self):
        self.submit(self.ticket())
        d = self.c.get(BASE + "callerid/", {"number": NUM}).data
        self.assertEqual([p["platform"] for p in d["profiles"]], ["whatsapp"])
        self.assertEqual(self.c.get(BASE + f"calls/{self.call_uid}/").data["profiles"][0]["display_name"], "علی آزمون")


class TelegramTests(LookupBase):
    def setUp(self):
        super().setUp()
        telegram_provider.BACKEND_FACTORY = lambda: FakeBackend()
        self.addCleanup(setattr, telegram_provider, "BACKEND_FACTORY", None)
        for n in ("account.json", "pending.json", "api.json", "cooldown.json"):
            telegram_provider._remove(n)
        self.panel = self.panel_client()

    def tg(self, **body):
        return self.panel.post(BASE + "admin/lookups/telegram/", body, format="json")

    def link(self):
        self.tg(action="save_api", api_id="12345", api_hash="0123456789abcdef0123456789abcdef")
        self.tg(action="send_code", phone="09120009999")
        return self.tg(action="code", code="12345")

    def test_not_ready_until_owner_links_account(self):
        enable("telegram")
        r = self.auth(platform="telegram")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (503, "platform_not_ready"))
        cfg = self.c.get(BASE + "lookups/config/").data["platforms"][0]
        self.assertEqual((cfg["key"], cfg["enabled"], cfg["ready"], cfg["method"]), ("telegram", True, False, "server"))

    def test_linking_flow_phone_code_password_and_secrets_never_echoed(self):
        telegram_provider.BACKEND_FACTORY = lambda: FakeBackend(password=True)
        self.assertEqual(self.tg(action="save_api", api_id="x", api_hash="y").status_code, 400)
        r = self.tg(action="save_api", api_id="12345", api_hash="0123456789abcdef0123456789abcdef")
        self.assertEqual((r.status_code, r.data["api_configured"], r.data["api_id"]), (200, True, 12345))
        self.assertNotIn("0123456789abcdef", str(r.data))
        self.assertEqual(self.tg(action="code", code="1").status_code, 400)                  # code before phone
        r = self.tg(action="send_code", phone="09120009999")
        self.assertEqual((r.data["pending"], r.data["pending_phone"]), ("code", "+989****999"))
        self.assertNotIn("09120009999", str(r.data))
        self.assertEqual(self.tg(action="code", code="00000").status_code, 400)             # wrong code: Persian message
        r = self.tg(action="code", code="12345")
        self.assertEqual((r.status_code, r.data["pending"], r.data["linked"]), (200, "password", False))
        self.assertEqual(self.tg(action="password", password="bad").status_code, 400)
        r = self.tg(action="password", password="pw")
        self.assertEqual((r.data["linked"], r.data["account"]["username"], r.data["pending"]), (True, "owner", None))
        self.assertIn(("send_code", "+989120009999"), FakeBackend.calls)
        self.assertTrue(telegram_provider.is_ready())
        # only staff panel can do it; the phone cannot
        self.assertEqual(self.c.post(BASE + "admin/lookups/telegram/", {"action": "unlink"}, format="json").status_code, 403)
        self.assertEqual(self.tg(action="unlink").data["linked"], False)
        self.assertEqual(self.tg(action="frobnicate").data["error"]["code"], "unknown_action")

    def test_secrets_are_stored_in_data_dir_with_private_permissions(self):
        import os
        import stat

        self.link()
        d = telegram_provider._dir()
        self.assertTrue(str(d).startswith(TMP_DATA))
        for name in ("api.json", "account.json"):
            self.assertEqual(stat.S_IMODE(os.stat(d / name).st_mode) & 0o077, 0, name)
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode) & 0o077, 0)

    def test_server_side_lookup_uses_resolve_phone_for_exactly_one_number(self):
        enable("telegram")
        self.link()
        r = self.auth(platform="telegram")
        self.assertEqual((r.data["allowed"], r.data["method"]), (True, "server"))
        FakeBackend.calls = []
        out = self.c.post(BASE + "lookups/server/", {"ticket": r.data["ticket"]}, format="json")
        self.assertEqual(out.status_code, 201)
        p = out.data
        self.assertEqual((p["platform"], p["method"], p["status"], p["on_platform"], p["display_name"], p["username"], p["bio"]),
                         ("telegram", "server", "found", True, "آزمون نمونه", "azmoon", "بیوی آزمایشی"))
        self.assertEqual(p["field_sources"]["avatar"], "تلگرام: عکس پروفایل")
        self.assertTrue(p["avatar_url"])
        self.assertEqual(FakeBackend.calls, [("resolve", "989120001234")])               # one request, one number, nothing else
        # ticket cannot be replayed
        self.assertEqual(self.c.post(BASE + "lookups/server/", {"ticket": r.data["ticket"]}, format="json").data["error"]["code"], "ticket_used")

    def test_not_found_on_telegram(self):
        enable("telegram")
        self.link()
        uid = self.c.post(BASE + "calls/live/", {"number": "09125550101", "direction": "in"}, format="json").data["uid"]
        t = self.auth(platform="telegram", number="09125550101", call_uid=uid).data["ticket"]
        p = self.c.post(BASE + "lookups/server/", {"ticket": t}, format="json").data
        self.assertEqual((p["status"], p["on_platform"], p["display_name"]), ("not_found", False, None))

    def test_flood_wait_pauses_and_refunds(self):
        enable("telegram")
        self.link()
        t = self.auth(platform="telegram").data["ticket"]

        class Flood(FakeBackend):
            async def resolve_phone(self, digits):
                raise telegram_provider._flood(90)

        telegram_provider.BACKEND_FACTORY = lambda: Flood()
        r = self.c.post(BASE + "lookups/server/", {"ticket": t}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (503, "flood_wait"))
        self.assertTrue(LookupTicket.objects.get().refunded)
        # while the cooldown lasts the backend is not even asked
        t2 = self.auth(platform="telegram", refresh=True).data["ticket"]
        telegram_provider.BACKEND_FACTORY = lambda: (_ for _ in ()).throw(AssertionError("must not be called during cooldown"))
        r = self.c.post(BASE + "lookups/server/", {"ticket": t2}, format="json")
        self.assertEqual(r.data["error"]["code"], "flood_wait")

    def test_unlink_forgets_the_session(self):
        self.link()
        self.assertTrue(telegram_provider.is_ready())
        self.tg(action="unlink")
        self.assertFalse(telegram_provider.is_ready())
        self.assertIn(("logout",), FakeBackend.calls)
