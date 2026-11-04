from datetime import datetime, timedelta, timezone as dt_tz
from unittest import mock

from django.utils import timezone

from . import api as mobile_api
from . import sms
from .base import MobileError
from .models import MobileSettings, SmsCampaignApproval, SmsInbound, SmsMessage, SmsOptOut
from .tests_base import BASE, MobileTestCase

S = SmsMessage.State


def at_tehran(hour):
    """A moment whose Tehran wall-clock hour is `hour` (today)."""
    from zoneinfo import ZoneInfo

    t = datetime.now(ZoneInfo("Asia/Tehran")).replace(hour=hour, minute=0, second=0, microsecond=0)
    return t.astimezone(dt_tz.utc)


class QueueTests(MobileTestCase):
    def queue(self, client, **data):
        payload = {"to": "09121234567", "body": "سلام", "kind": "transactional", **data}
        return client.post(BASE + "sms/queue/", payload, format="json")

    def test_idempotency_key_returns_same_message(self):
        panel = self.panel_client()
        a = self.queue(panel, idempotency_key="order-1")
        b = self.queue(panel, idempotency_key="order-1")
        c = panel.post(BASE + "sms/queue/", {"to": "09121234567", "body": "سلام"}, format="json", HTTP_IDEMPOTENCY_KEY="order-1")
        self.assertEqual((a.status_code, b.status_code, c.status_code), (201, 200, 200))
        self.assertEqual(a.data["uid"], b.data["uid"])
        self.assertTrue(b.data["deduped"])
        self.assertEqual(SmsMessage.objects.count(), 1)

    def test_phone_cannot_queue_only_panel(self):
        r = self.queue(self.device_client())
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "panel_only"))

    def test_validation(self):
        panel = self.panel_client()
        self.assertEqual(self.queue(panel, to="12").data["error"]["code"], "bad_number")
        self.assertEqual(self.queue(panel, body="  ").data["error"]["code"], "missing_fields")
        self.assertEqual(self.queue(panel, kind="spam").data["error"]["code"], "bad_kind")
        self.assertEqual(self.queue(panel, body="x" * 1001).data["error"]["code"], "too_long")

    def test_marketing_needs_human_approval(self):
        panel = self.panel_client()
        r = self.queue(panel, kind="marketing")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "campaign_not_approved"))
        r = self.queue(panel, kind="marketing", campaign_ref="ge:1")
        self.assertEqual(r.status_code, 403)
        sms.register_campaign_approval("ge:1", "پیشنهاد", self.boss, source="growth_engine")
        self.assertEqual(self.queue(panel, kind="marketing", campaign_ref="ge:1").status_code, 201)
        sms.revoke_campaign("ge:1")
        self.assertEqual(self.queue(panel, kind="marketing", campaign_ref="ge:1").status_code, 403)

    def test_marketing_approval_limits(self):
        a = sms.register_campaign_approval("c:2", "t", self.boss, max_messages=1)
        m1, _ = mobile_api.queue_sms("09121234567", "a", "marketing", "c:2")
        self.assertTrue(a.active)
        phone = self.device_client()
        with mock.patch.object(sms, "in_quiet_hours", return_value=False):
            out = phone.post(BASE + "sms/claim/", {}, format="json").data
        self.assertEqual(len(out["messages"]), 1)
        a.refresh_from_db()
        self.assertFalse(a.active)      # max reached: the next marketing message is refused
        with self.assertRaises(MobileError):
            mobile_api.queue_sms("09121234568", "b", "marketing", "c:2")

    def test_expired_approval_refused(self):
        sms.register_campaign_approval("c:3", "t", self.boss, valid_until=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(MobileError) as cm:
            mobile_api.queue_sms("09121234567", "a", "marketing", "c:3")
        self.assertEqual(cm.exception.code, "campaign_not_approved")


class OptOutTests(MobileTestCase):
    def test_opted_out_number_is_blocked_at_queue_time(self):
        sms.add_opt_out("09121234567", user=self.boss)
        panel = self.panel_client()
        r = panel.post(BASE + "sms/queue/", {"to": "+98 912 123 4567", "body": "x", "idempotency_key": "k"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (409, "opted_out"))
        self.assertEqual(SmsMessage.objects.get().state, S.BLOCKED)
        # the same key later does not unblock it
        r2 = panel.post(BASE + "sms/queue/", {"to": "09121234567", "body": "x", "idempotency_key": "k"}, format="json")
        self.assertEqual(r2.data["state"], S.BLOCKED)

    def test_opt_out_after_queueing_blocks_at_claim(self):
        msg, _ = mobile_api.queue_sms("09121234567", "hi", "transactional")
        sms.add_opt_out("09121234567")                 # arrives while it waits
        out = self.device_client().post(BASE + "sms/claim/", {}, format="json").data
        self.assertEqual(out["messages"], [])
        msg.refresh_from_db()
        self.assertEqual(msg.state, S.BLOCKED)

    def test_otp_is_blocked_too_by_default_but_setting_can_allow(self):
        sms.add_opt_out("09121234567")
        with self.assertRaises(sms.OptedOut):
            mobile_api.queue_sms("09121234567", "کد 1234", "otp")
        s = MobileSettings.get()
        s.otp_ignores_opt_out = True
        s.save()
        msg, created = mobile_api.queue_sms("09121234567", "کد 1234", "otp")
        self.assertTrue(created)
        self.assertEqual(msg.state, S.QUEUED)

    def test_stop_reply_adds_to_global_list_even_when_forwarding_is_off(self):
        c = self.device_client()
        r = c.post(BASE + "sms/incoming/", {"messages": [
            {"client_id": "a", "from": "09121234567", "body": "لغو", "received_at": "2026-11-04T10:00:00+03:30"},
            {"client_id": "b", "from": "09129999999", "body": "سلام قیمت محصول چنده؟", "received_at": "2026-11-04T10:01:00+03:30"},
        ]}, format="json")
        self.assertEqual(r.data, {"accepted": 1, "duplicates": 0, "opt_outs_added": 1, "forwarding": False})
        self.assertTrue(sms.is_opted_out("0912 123 4567"))
        self.assertEqual(SmsInbound.objects.count(), 1)              # the non-STOP text was discarded unstored
        self.assertEqual(SmsInbound.objects.get().body, "(لغو)")
        # a repeat is a duplicate, not a second opt-out
        r = c.post(BASE + "sms/incoming/", {"messages": [{"client_id": "a", "from": "09121234567", "body": "لغو"}]}, format="json")
        self.assertEqual((r.data["accepted"], r.data["duplicates"]), (0, 1))

    def test_incoming_forwarding_on_stores_everything(self):
        s = MobileSettings.get()
        s.forward_incoming_sms = True
        s.save()
        c = self.device_client()
        r = c.post(BASE + "sms/incoming/", {"messages": [{"client_id": "b", "from": "09129999999", "body": "سلام"}]}, format="json")
        self.assertEqual((r.data["accepted"], r.data["forwarding"]), (1, True))
        self.assertEqual(SmsInbound.objects.get().body, "سلام")

    def test_stop_reply_removes_queued_marketing(self):
        sms.register_campaign_approval("c:9", "t", self.boss)
        msg, _ = mobile_api.queue_sms("09121234567", "تبلیغ", "marketing", "c:9")
        sms.add_opt_out("09121234567")
        msg.refresh_from_db()
        self.assertEqual(msg.state, S.BLOCKED)

    def test_growth_engine_suppression_list_is_honoured_read_only(self):
        try:
            from apps.growth_engine.compliance.models import SuppressionEntry
        except Exception:
            self.skipTest("growth engine not installed")
        SuppressionEntry.objects.create(kind="phone", normalized="09123334444", value="09123334444")
        self.assertTrue(sms.is_opted_out("+98 912 333 4444"))
        with self.assertRaises(sms.OptedOut):
            mobile_api.queue_sms("09123334444", "x", "transactional")


class OptOutFeedTests(MobileTestCase):
    def test_feed_pages_with_a_cursor_and_is_device_only(self):
        for i in range(5):
            sms.add_opt_out(f"091200000{i:02d}")
        c = self.device_client()
        first = c.get(BASE + "sms/optouts/?limit=3").data
        self.assertEqual((len(first["numbers"]), first["has_more"]), (3, True))
        self.assertTrue(all(n.startswith("98912") for n in first["numbers"]))
        rest = c.get(BASE + "sms/optouts/", {"since": first["next_since"], "limit": 10}).data
        self.assertEqual(sorted(first["numbers"] + rest["numbers"])[:1], ["989120000000"])
        self.assertEqual(set(first["numbers"]) | set(rest["numbers"]), {f"989120000{i:03d}" for i in range(5)})
        self.assertFalse(rest["has_more"])
        again = c.get(BASE + "sms/optouts/", {"since": rest["next_since"]}).data
        self.assertEqual((again["numbers"], again["has_more"], again["next_since"]), ([], False, rest["next_since"]))
        self.assertEqual(self.panel_client().get(BASE + "sms/optouts/").status_code, 403)       # the panel uses admin/optouts/
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(BASE + "sms/optouts/").status_code, 401)


class ClaimTests(MobileTestCase):
    def test_claim_report_flow(self):
        msg, _ = mobile_api.queue_sms("09121234567", "سلام", "otp")
        c = self.device_client()
        out = c.post(BASE + "sms/claim/", {"max": 5}, format="json").data
        self.assertEqual(len(out["messages"]), 1)
        item = out["messages"][0]
        self.assertEqual((item["to"], item["normalized"], item["kind"], item["attempt"]), ("09121234567", "989121234567", "otp", 1))
        self.assertEqual(c.post(BASE + "sms/claim/", {}, format="json").data["messages"], [])       # nothing twice
        uid = item["uid"]
        rep = lambda **kw: c.post(BASE + f"sms/{uid}/report/", kw, format="json")
        self.assertEqual(rep(state="sent").data["state"], "SENT")
        self.assertEqual(rep(state="sent").data["state"], "SENT")                                   # repeat is a no-op
        self.assertEqual(rep(state="delivered").data["state"], "DELIVERED")
        self.assertEqual(rep(state="failed", error_code="generic").data["state"], "DELIVERED")      # late failure never overrides success
        self.assertEqual(rep(state="sent").data["state"], "DELIVERED")                              # state never moves backwards
        msg.refresh_from_db()
        self.assertIsNotNone(msg.sent_at)
        self.assertIsNotNone(msg.delivered_at)

    def test_report_validation_and_ownership(self):
        msg, _ = mobile_api.queue_sms("09121234567", "x", "otp")
        a, b = self.device_client("marketer", "a"), self.device_client("boss", "b")
        uid = a.post(BASE + "sms/claim/", {}, format="json").data["messages"][0]["uid"]
        r = b.post(BASE + f"sms/{uid}/report/", {"state": "sent"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "not_yours"))
        self.assertEqual(a.post(BASE + f"sms/{uid}/report/", {"state": "weird"}, format="json").data["error"]["code"], "bad_state")
        self.assertEqual(a.post(BASE + "sms/00000000-0000-0000-0000-000000000000/report/", {"state": "sent"}, format="json").status_code, 404)

    def test_only_one_phone_gets_a_message(self):
        mobile_api.queue_sms("09121234567", "x", "otp")
        a, b = self.device_client("marketer", "a"), self.device_client("boss", "b")
        got = len(a.post(BASE + "sms/claim/", {}, format="json").data["messages"]) + len(b.post(BASE + "sms/claim/", {}, format="json").data["messages"])
        self.assertEqual(got, 1)

    def test_retryable_failure_requeues_once_then_final(self):
        msg, _ = mobile_api.queue_sms("09121234567", "x", "transactional")
        c = self.device_client()
        uid = c.post(BASE + "sms/claim/", {}, format="json").data["messages"][0]["uid"]
        self.assertEqual(c.post(BASE + f"sms/{uid}/report/", {"state": "failed", "error_code": "radio_off"}, format="json").data["state"], "QUEUED")
        out = c.post(BASE + "sms/claim/", {}, format="json").data
        self.assertEqual(out["messages"][0]["attempt"], 2)
        self.assertEqual(c.post(BASE + f"sms/{uid}/report/", {"state": "failed", "error_code": "radio_off"}, format="json").data["state"], "FAILED")

    def test_final_failure_codes_do_not_retry(self):
        msg, _ = mobile_api.queue_sms("09121234567", "x", "otp")
        c = self.device_client()
        uid = c.post(BASE + "sms/claim/", {}, format="json").data["messages"][0]["uid"]
        self.assertEqual(c.post(BASE + f"sms/{uid}/report/", {"state": "failed", "error_code": "unknown_after_restart"}, format="json").data["state"], "FAILED")

    def test_lease_expiry_requeues_transactional_but_never_marketing(self):
        sms.register_campaign_approval("c:1", "t", self.boss)
        t, _ = mobile_api.queue_sms("09121234567", "x", "transactional")
        m, _ = mobile_api.queue_sms("09121234568", "y", "marketing", "c:1")
        c = self.device_client()
        with mock.patch.object(sms, "in_quiet_hours", return_value=False):
            self.assertEqual(len(c.post(BASE + "sms/claim/", {}, format="json").data["messages"]), 2)
            later = timezone.now() + timedelta(seconds=500)
            self.assertEqual(sms.expire_leases(later), 2)
        t.refresh_from_db()
        m.refresh_from_db()
        self.assertEqual(t.state, S.QUEUED)
        self.assertEqual((m.state, m.error), (S.FAILED, "lease_expired"))
        # the phone reports the marketing SMS as sent after all: the truth wins
        uid = str(m.uid)
        self.assertEqual(c.post(BASE + f"sms/{uid}/report/", {"state": "sent"}, format="json").data["state"], "SENT")

    def test_global_pause_and_device_switch(self):
        mobile_api.queue_sms("09121234567", "x", "otp")
        c = self.device_client()
        panel = self.panel_client()
        panel.post(BASE + "monitor/actions/", {"action": "sms.pause"}, format="json")
        out = c.post(BASE + "sms/claim/", {}, format="json").data
        self.assertTrue(out["paused"])
        self.assertEqual(out["messages"], [])
        panel.post(BASE + "monitor/actions/", {"action": "sms.resume"}, format="json")
        panel.patch(BASE + f"admin/devices/{c.device_uid}/", {"sms_enabled": False}, format="json")
        self.assertTrue(c.post(BASE + "sms/claim/", {}, format="json").data["paused"])
        panel.patch(BASE + f"admin/devices/{c.device_uid}/", {"sms_enabled": True}, format="json")
        self.assertEqual(len(c.post(BASE + "sms/claim/", {}, format="json").data["messages"]), 1)

    def test_per_device_hourly_cap(self):
        s = MobileSettings.get()
        s.max_sms_per_hour = 3
        s.save()
        for i in range(6):
            mobile_api.queue_sms(f"091200000{i:02d}", "x", "transactional")
        c = self.device_client()
        out = c.post(BASE + "sms/claim/", {"max": 10}, format="json").data
        self.assertEqual(len(out["messages"]), 3)
        again = c.post(BASE + "sms/claim/", {}, format="json").data
        self.assertEqual((again["messages"], again["limited"]), ([], "hour"))
        self.assertEqual(SmsMessage.objects.filter(state=S.QUEUED).count(), 3)

    def test_marketing_has_its_own_hourly_cap_and_quiet_hours(self):
        s = MobileSettings.get()
        s.max_marketing_per_hour = 2
        s.save()
        sms.register_campaign_approval("c:7", "t", self.boss)
        for i in range(4):
            mobile_api.queue_sms(f"091200000{i:02d}", "x", "marketing", "c:7")
        c = self.device_client()
        with mock.patch.object(sms, "in_quiet_hours", return_value=True):
            self.assertEqual(c.post(BASE + "sms/claim/", {}, format="json").data["messages"], [])
        with mock.patch.object(sms, "in_quiet_hours", return_value=False):
            self.assertEqual(len(c.post(BASE + "sms/claim/", {"max": 5}, format="json").data["messages"]), 2)
            self.assertEqual(c.post(BASE + "sms/claim/", {}, format="json").data["messages"], [])

    def test_quiet_hours_function_wraps_midnight(self):
        s = MobileSettings.get()
        self.assertTrue(sms.in_quiet_hours(s, at_tehran(22)))
        self.assertTrue(sms.in_quiet_hours(s, at_tehran(3)))
        self.assertFalse(sms.in_quiet_hours(s, at_tehran(12)))
        self.assertFalse(sms.in_quiet_hours(s, at_tehran(8)))

    def test_not_before_and_sim_slot(self):
        mobile_api.queue_sms("09121234567", "later", "otp", not_before=timezone.now() + timedelta(hours=1))
        m2, _ = mobile_api.queue_sms("09121234568", "slot1", "otp")
        SmsMessage.objects.filter(pk=m2.pk).update(sim_slot=1)
        c = self.device_client()
        self.assertEqual(c.post(BASE + "sms/claim/", {"sim_slot": 0}, format="json").data["messages"], [])
        self.assertEqual(len(c.post(BASE + "sms/claim/", {"sim_slot": 1}, format="json").data["messages"]), 1)

    def test_cancel_only_queued(self):
        msg, _ = mobile_api.queue_sms("09121234567", "x", "otp")
        panel = self.panel_client()
        r = panel.post(BASE + f"sms/{msg.uid}/cancel/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(panel.post(BASE + f"sms/{msg.uid}/cancel/", {}, format="json").data["error"]["code"], "bad_state")
        self.assertEqual(self.device_client().post(BASE + "sms/claim/", {}, format="json").data["messages"], [])

    def test_queue_list_for_panel(self):
        mobile_api.queue_sms("09121234567", "x", "otp")
        r = self.panel_client().get(BASE + "sms/queue/?q=0912")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["state"], "QUEUED")
