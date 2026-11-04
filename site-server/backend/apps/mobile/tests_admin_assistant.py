"""Panel endpoints, the AI assistant (fake model only) and the Python API other NM apps use."""
import json
from decimal import Decimal
from unittest import mock

from apps.products.models import Product

from . import api as mobile_api
from .base import MobileError
from .models import MobileSettings, SmsCampaignApproval, SmsOptOut
from .tests_base import BASE, MobileTestCase


class PanelTests(MobileTestCase):
    def test_overview_for_pairing_and_no_secrets(self):
        phone = self.device_client()
        d = self.panel_client().get(BASE + "admin/overview/").data
        self.assertTrue(d["server_url"].startswith("http"))
        self.assertEqual(d["counts"]["devices"], 1)
        self.assertEqual(len(d["pairing_steps"]), 4)
        self.assertEqual(d["telegram"]["linked"], False)
        self.assertNotIn("api_hash", json.dumps(d))
        devs = self.panel_client().get(BASE + "admin/devices/").data["results"]
        self.assertEqual((devs[0]["name"], devs[0]["user"]["username"]), ("گوشی آزمون", "marketer"))
        self.assertNotIn("token_hash", devs[0])
        self.assertNotIn(phone.token, json.dumps(devs, default=str))      # only a short prefix is ever shown

    def test_settings_validation_and_audit(self):
        p = self.panel_client()
        r = p.patch(BASE + "admin/settings/", {"max_sms_per_hour": 10, "forward_incoming_sms": True,
                                               "lookup_platforms": {"whatsapp": True, "nonsense": True}}, format="json")
        self.assertEqual(r.status_code, 200)
        s = MobileSettings.get()
        self.assertEqual((s.max_sms_per_hour, s.forward_incoming_sms), (10, True))
        self.assertEqual(s.lookup_platforms, {"whatsapp": True})            # unknown platform ignored
        self.assertEqual(p.patch(BASE + "admin/settings/", {"max_sms_per_hour": "abc"}, format="json").status_code, 400)
        self.assertEqual(p.patch(BASE + "admin/settings/", {"max_sms_per_hour": -1}, format="json").status_code, 400)
        self.assertEqual(self.device_client().patch(BASE + "admin/settings/", {}, format="json").status_code, 403)
        self.assertEqual(self.panel_client(self.plain).get(BASE + "admin/settings/").status_code, 403)
        log = p.get(BASE + "admin/actions-log/?action=settings").data
        self.assertEqual(log["results"][0]["user"], "boss")

    def test_optouts_and_approvals_roundtrip(self):
        p = self.panel_client()
        self.assertEqual(p.post(BASE + "admin/optouts/", {"number": "+98 912 111 2233", "note": "تلفنی گفت"}, format="json").status_code, 201)
        self.assertEqual(p.post(BASE + "admin/optouts/", {"number": "09121112233"}, format="json").status_code, 200)       # same number: no duplicate
        rows = p.get(BASE + "admin/optouts/?q=0912").data
        self.assertEqual((rows["count"], rows["results"][0]["number"]), (1, "09121112233"))
        oid = rows["results"][0]["id"]
        self.assertEqual(p.delete(BASE + f"admin/optouts/{oid}/").status_code, 200)
        self.assertEqual(SmsOptOut.objects.count(), 0)
        a = p.post(BASE + "admin/approvals/", {"ref": "ge:5", "title": "پیشنهاد", "max_messages": "50"}, format="json")
        self.assertEqual((a.status_code, a.data["active"], a.data["max_messages"]), (201, True, 50))
        self.assertEqual(p.post(BASE + f"admin/approvals/{a.data['id']}/revoke/", {}, format="json").data["active"], False)
        self.assertEqual(p.post(BASE + "admin/approvals/", {"ref": "x"}, format="json").status_code, 400)

    def test_consents_list_and_call_audio_needs_staff(self):
        c = self.device_client()
        c.post(BASE + "calls/consent/", {"number": "09121234567", "how": "written", "obtained_how": "پیامک تأیید"}, format="json")
        rows = self.panel_client().get(BASE + "admin/consents/").data["results"]
        self.assertEqual((rows[0]["number"], rows[0]["active"], rows[0]["by"]), ("09121234567", True, "marketer"))


class AssistantTests(MobileTestCase):
    def setUp(self):
        super().setUp()
        self.c = self.device_client()
        self.p1 = Product.objects.create(store=self.store, name="مانتو کتان", price=Decimal("900000"), cost_price=Decimal("600000"), stock_quantity=4)
        self.p2 = Product.objects.create(store=self.store, name="شال", price=Decimal("300000"), stock_quantity=0)

    def ask(self, parsed=None, error=None, **body):
        fake_provider = mock.Mock()
        captured = {}

        def fake_call(**kw):
            captured.update(kw)
            if error:
                raise error
            return (parsed or {"replies": ["قیمت ۹۰۰ هزار تومان است."], "notes": "تا ۳۰۰ هزار تخفیف ممکن است."}), mock.Mock(via="local")

        with mock.patch("services.ai.gateway.text_provider", return_value=fake_provider), \
                mock.patch("apps.ai.services.recorded_json_call", side_effect=fake_call):
            r = self.c.post(BASE + "assistant/ask/", {"question": "قیمت مانتو چنده؟", **body}, format="json")
        return r, captured

    def test_facts_reach_the_model_with_unknowns_marked_and_cost_forbidden_to_customer(self):
        r, cap = self.ask(product_ids=[self.p1.pk, self.p2.pk], number="09121234567")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["replies"], [{"text": "قیمت ۹۰۰ هزار تومان است."}])
        self.assertEqual((r.data["engine"], r.data["notes"]), ("local", "تا ۳۰۰ هزار تخفیف ممکن است."))
        prompt, system = cap["prompt"], cap["system"]
        self.assertIn("مانتو کتان", prompt)
        self.assertIn("900000", prompt)
        self.assertIn("600000", prompt)                         # the marketer may know the floor/cost ...
        self.assertIn("ثبت نشده", prompt)                       # ... and the product without a cost says so instead of 0
        self.assertIn("هرگز بهای تمام‌شده", system)             # ... but is told never to repeat it to the customer
        self.assertEqual(cap["prompt_id"], "mobile_quick_reply")
        used = {p["name"]: p for p in r.data["facts_used"]["products"]}
        self.assertEqual(used["مانتو کتان"]["floor_price"], 600000)
        self.assertIsNone(used["شال"]["floor_price"])

    def test_ai_down_gives_clear_503_not_a_made_up_answer(self):
        r, _ = self.ask(error=RuntimeError("سرور پردازش خاموش است"))
        self.assertEqual((r.status_code, r.data["error"]["code"]), (503, "ai_unavailable"))
        self.assertIn("خاموش", r.data["error"]["message"])

    def test_bad_model_output_is_rejected_by_validation(self):
        from . import notes

        self.assertFalse(notes.ask_valid({"replies": []})[0])
        self.assertFalse(notes.ask_valid("x")[0])
        self.assertTrue(notes.ask_valid({"replies": ["a"]})[0])
        self.assertFalse(notes._valid({"summary": ""})[0])
        self.assertFalse(notes._valid({"summary": "s", "sentiment": "HAPPY"})[0])
        self.assertTrue(notes._valid({"summary": "s", "sentiment": "POSITIVE", "objections": ["a"]})[0])

    def test_question_is_required_and_staff_only(self):
        self.assertEqual(self.c.post(BASE + "assistant/ask/", {}, format="json").data["error"]["code"], "missing_fields")
        self.assertEqual(self.panel_client(self.plain).post(BASE + "assistant/ask/", {"question": "x"}, format="json").status_code, 403)


class PythonApiTests(MobileTestCase):
    """What Growth Engine (or any NM app) calls: stable, and it enforces the same rules."""

    def test_queue_and_approval_hook(self):
        with self.assertRaises(MobileError) as cm:
            mobile_api.queue_sms("09121234567", "تبلیغ", kind="marketing", campaign_ref="ge:1")
        self.assertEqual(cm.exception.code, "campaign_not_approved")
        mobile_api.register_campaign_approval("ge:1", "کمپین", approved_by=self.boss, source="growth_engine")
        msg, created = mobile_api.queue_sms("09121234567", "تبلیغ", kind="marketing", campaign_ref="ge:1", idempotency_key="ge:1:9")
        again, created2 = mobile_api.queue_sms("09121234567", "تبلیغ", kind="marketing", campaign_ref="ge:1", idempotency_key="ge:1:9")
        self.assertEqual((created, created2, msg.pk == again.pk), (True, False, True))
        self.assertEqual(SmsCampaignApproval.objects.get().source, "growth_engine")
        mobile_api.revoke_campaign("ge:1")
        msg.refresh_from_db()
        self.assertEqual(msg.state, "BLOCKED")

    def test_opt_out_helpers(self):
        self.assertFalse(mobile_api.is_opted_out("09121234567"))
        mobile_api.add_opt_out("09121234567")
        self.assertTrue(mobile_api.is_opted_out("+989121234567"))
        with self.assertRaises(mobile_api.OptedOut):
            mobile_api.queue_sms("09121234567", "x")
        self.assertEqual(mobile_api.normalize_number("۰۹۱۲۱۲۳۴۵۶۷"), "989121234567")


class GrowthEngineChannelTests(MobileTestCase):
    """`enqueue_sms` / `sms_status`: the contract Growth Engine uses to send through the owner's phone."""

    def claim(self, c):
        from . import sms as sms_mod

        with mock.patch.object(sms_mod, "in_quiet_hours", return_value=False):
            return c.post(BASE + "sms/claim/", {}, format="json").data["messages"]

    def test_marketing_needs_approval_then_status_follows_the_phone(self):
        with self.assertRaises(MobileError) as cm:
            mobile_api.enqueue_sms("09121234567", "پیشنهاد", source="growth", ref="item-1", campaign_ref="ge:7")
        self.assertEqual(cm.exception.code, "campaign_not_approved")
        mobile_api.register_campaign_approval("ge:7", "پیشنهاد ویژه", approved_by=self.boss, source="growth_engine")
        sid = mobile_api.enqueue_sms("09121234567", "پیشنهاد", source="growth", ref="item-1", campaign_ref="ge:7", created_by=self.boss)
        self.assertEqual(mobile_api.sms_status(sid)["state"], "queued")
        self.assertFalse(mobile_api.sms_status(sid)["final"])
        # same (source, ref) => same id, nothing queued twice
        self.assertEqual(mobile_api.enqueue_sms("09121234567", "پیشنهاد", source="growth", ref="item-1", campaign_ref="ge:7"), sid)
        self.assertEqual(mobile_api.queue_sms.__module__, "apps.mobile.api")
        phone = self.device_client()
        msgs = self.claim(phone)
        self.assertEqual([m["uid"] for m in msgs], [sid])
        self.assertEqual(mobile_api.sms_status(sid)["state"], "sending")
        phone.post(BASE + f"sms/{sid}/report/", {"state": "sent"}, format="json")
        st = mobile_api.sms_status(sid)
        self.assertEqual((st["state"], st["final"], st["device"]), ("sent", False, "گوشی آزمون"))
        phone.post(BASE + f"sms/{sid}/report/", {"state": "delivered"}, format="json")
        self.assertEqual((mobile_api.sms_status(sid)["state"], mobile_api.sms_status(sid)["final"]), ("delivered", True))

    def test_failure_is_reported_with_the_reason(self):
        sid = mobile_api.enqueue_sms("09121234567", "اطلاع", source="growth", ref="x", kind="transactional")
        phone = self.device_client()
        self.claim(phone)
        phone.post(BASE + f"sms/{sid}/report/", {"state": "failed", "error_code": "bad_number", "error": "شمارهٔ نامعتبر"}, format="json")
        st = mobile_api.sms_status(sid)
        self.assertEqual((st["state"], st["final"], st["error_code"]), ("failed", True, "bad_number"))

    def test_opt_out_guardrail_at_queue_time_and_at_claim_time(self):
        mobile_api.register_campaign_approval("ge:8", "t", approved_by=self.boss)
        sid = mobile_api.enqueue_sms("09125551111", "تبلیغ", source="growth", ref="a", campaign_ref="ge:8")
        mobile_api.add_opt_out("09125551111")                       # replies «لغو» while waiting
        self.assertEqual(self.claim(self.device_client()), [])
        self.assertEqual(mobile_api.sms_status(sid)["state"], "blocked")
        with self.assertRaises(mobile_api.OptedOut) as cm:
            mobile_api.enqueue_sms("09125551111", "باز هم تبلیغ", source="growth", ref="b", campaign_ref="ge:8")
        self.assertEqual(mobile_api.sms_status(str(cm.exception.sms.uid))["state"], "blocked")

    def test_device_caps_still_apply_and_messages_wait_when_no_phone(self):
        s = MobileSettings.get()
        s.max_sms_per_hour = 2
        s.save()
        ids = [mobile_api.enqueue_sms(f"091200000{i:02d}", "اطلاع", source="growth", ref=f"r{i}", kind="transactional") for i in range(4)]
        self.assertTrue(all(mobile_api.sms_status(i)["state"] == "queued" for i in ids))      # nobody is paired: they wait
        phone = self.device_client()
        self.assertEqual(len(self.claim(phone)), 2)
        self.assertEqual(sorted(mobile_api.sms_status(i)["state"] for i in ids), ["queued", "queued", "sending", "sending"])

    def test_unknown_ids_and_bulk_status(self):
        sid = mobile_api.enqueue_sms("09121234567", "x", source="growth", ref="1", kind="transactional")
        self.assertIsNone(mobile_api.sms_status("not-a-uuid"))
        self.assertIsNone(mobile_api.sms_status("00000000-0000-0000-0000-000000000000"))
        out = mobile_api.sms_statuses([sid, "nope"])
        self.assertEqual((out[sid]["state"], out["nope"]), ("queued", None))

    def test_expiry_drops_a_message_nobody_picked_up(self):
        from datetime import timedelta

        from django.utils import timezone

        sid = mobile_api.enqueue_sms("09121234567", "x", source="growth", ref="e", kind="transactional",
                                     expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.claim(self.device_client()), [])
        st = mobile_api.sms_status(sid)                                       # never handed out; reported as failed/expired
        self.assertEqual((st["state"], st["final"], st["error_code"]), ("failed", True, "expired"))
