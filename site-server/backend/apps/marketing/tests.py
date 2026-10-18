from django.test import TestCase

from .models import Lead

URL = "/api/v1/leads/"

VALID = {
    "name": "مهدی رنجبران",
    "email": "mehdi@example.com",
    "message": "سلام، می‌خواهم برای فروشگاه پوشاکم دمو ببینم.",
}


class LeadIntakeTests(TestCase):
    def test_anonymous_can_submit(self):
        """The whole point: no account needed to reach us."""
        res = self.client.post(URL, VALID, content_type="application/json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()["ok"])

        lead = Lead.objects.get()
        self.assertEqual(lead.name, "مهدی رنجبران")
        self.assertEqual(lead.status, Lead.Status.NEW)

    def test_optional_fields_are_optional(self):
        res = self.client.post(URL, VALID, content_type="application/json")
        self.assertEqual(res.status_code, 201)
        lead = Lead.objects.get()
        self.assertEqual(lead.phone, "")
        self.assertEqual(lead.business, "")

    def test_short_message_rejected(self):
        """A three-word message is never a real enquiry."""
        res = self.client.post(
            URL, {**VALID, "message": "سلام"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("message", res.json())
        self.assertEqual(Lead.objects.count(), 0)

    def test_bad_email_rejected(self):
        res = self.client.post(
            URL, {**VALID, "email": "not-an-email"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Lead.objects.count(), 0)

    def test_honeypot_looks_like_success_but_stores_nothing(self):
        """A bot must not learn that it was caught."""
        res = self.client.post(
            URL, {**VALID, "website": "http://spam.example"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(Lead.objects.count(), 0)

    def test_client_cannot_set_status(self):
        """Status is ours. A POST claiming CONVERTED must not be believed."""
        res = self.client.post(
            URL,
            {**VALID, "status": Lead.Status.CONVERTED, "notes": "injected"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        lead = Lead.objects.get()
        self.assertEqual(lead.status, Lead.Status.NEW)
        self.assertEqual(lead.notes, "")

    def test_attribution_is_captured(self):
        res = self.client.post(
            URL,
            {
                **VALID,
                "source_path": "/solutions/clothing-businesses",
                "referrer": "https://www.google.com/",
                "utm": {"source": "instagram", "campaign": "launch"},
            },
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        lead = Lead.objects.get()
        self.assertEqual(lead.source_path, "/solutions/clothing-businesses")
        self.assertEqual(lead.utm["source"], "instagram")

    def test_unknown_utm_keys_dropped(self):
        """utm is analytics, not a place for the client to store payloads."""
        res = self.client.post(
            URL,
            {**VALID, "utm": {"source": "x", "evil": "y" * 500}},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        lead = Lead.objects.get()
        self.assertEqual(set(lead.utm), {"source"})

    def test_ip_and_user_agent_recorded(self):
        res = self.client.post(
            URL,
            VALID,
            content_type="application/json",
            HTTP_USER_AGENT="Mozilla/5.0 test",
        )
        self.assertEqual(res.status_code, 201)
        lead = Lead.objects.get()
        self.assertEqual(lead.user_agent, "Mozilla/5.0 test")
        self.assertIsNotNone(lead.ip)

    def test_response_leaks_nothing(self):
        """The form needs 'it worked' — not the row we just wrote."""
        res = self.client.post(URL, VALID, content_type="application/json")
        self.assertEqual(set(res.json()), {"ok", "message"})
