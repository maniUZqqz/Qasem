"""Outgoing webhooks (signing, retry, SSRF) and the public API (keys, scopes, sandbox)."""
from __future__ import annotations

import json
from datetime import timedelta

import httpx
from django.utils import timezone
from rest_framework.test import APIClient

from apps.api_platform.models import APIKey, generate_key
from apps.customers.models import Conversation

from . import events, replies
from .models import Broadcast, Contact, WebhookDelivery, WebhookEndpoint
from .tests_base import InboxTestCase

PUBLIC_IP = "93.184.216.34"


def public_resolver(host, port):
    return [PUBLIC_IP]


class SigningTests(InboxTestCase):
    def test_signature_verifies_and_rejects_tampering_and_replay(self):
        body = b'{"a":1}'
        header = events.sign("topsecret", body)
        self.assertTrue(events.verify_signature("topsecret", body, header))
        self.assertFalse(events.verify_signature("topsecret", b'{"a":2}', header))
        self.assertFalse(events.verify_signature("other", body, header))
        old = events.sign("topsecret", body, timestamp=int(timezone.now().timestamp()) - 3600)
        self.assertFalse(events.verify_signature("topsecret", body, old))
        self.assertFalse(events.verify_signature("topsecret", body, "garbage"))


class DeliveryTests(InboxTestCase):
    def endpoint(self, events_list=None, url="https://hooks.example.com/inbox"):
        return WebhookEndpoint.objects.create(store=self.store, url=url, events=events_list or [], created_by=self.owner)

    def mock(self, status=200, record=None):
        def handler(request: httpx.Request):
            if record is not None:
                record.append(request)
            return httpx.Response(status)
        return httpx.MockTransport(handler)

    def test_a_message_event_is_signed_and_delivered_to_the_right_place(self):
        endpoint = self.endpoint(["message.received"])
        conversation = self.conversation(name="سارا")
        self.customer_says(conversation, "سلام، قیمت؟")
        delivery = WebhookDelivery.objects.get(endpoint=endpoint, event="message.received")
        self.assertEqual(delivery.payload["data"]["text"], "سلام، قیمت؟")
        seen: list[httpx.Request] = []
        result = events.deliver_due(resolver=public_resolver, transport=self.mock(200, seen))
        self.assertEqual(result["sent"], 1)
        request = seen[0]
        self.assertEqual(request.url.host, PUBLIC_IP)  # pinned to the address that was checked
        self.assertEqual(request.headers["host"], "hooks.example.com")
        body = request.content
        self.assertTrue(events.verify_signature(endpoint.secret, body, request.headers["x-inbox-signature"]))
        self.assertEqual(json.loads(body)["event"], "message.received")
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.OK)

    def test_an_endpoint_only_gets_the_events_it_asked_for(self):
        only_closed = self.endpoint(["conversation.closed"])
        everything = self.endpoint([], url="https://all.example.com/x")
        conversation = self.conversation(name="سارا")
        self.customer_says(conversation)
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=only_closed).count(), 0)
        self.assertGreaterEqual(WebhookDelivery.objects.filter(endpoint=everything).count(), 2)  # created + received

    def test_other_stores_never_see_our_events(self):
        WebhookEndpoint.objects.create(store=self.other_store, url="https://x.example.com/", events=[])
        self.customer_says(self.conversation())
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_test_conversations_emit_nothing(self):
        self.endpoint()
        conversation = self.conversation(channel="TELEGRAM", name="آزمایش")
        from .sla import meta_for

        meta = meta_for(conversation)
        meta.is_test = True
        meta.save()
        WebhookDelivery.objects.all().delete()
        self.customer_says(conversation)
        self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_failures_retry_with_backoff_then_give_up(self):
        endpoint = self.endpoint()
        events.emit(self.store, "conversation.closed", {"conversation_id": 1})
        delivery = WebhookDelivery.objects.get()
        for attempt in range(1, events.MAX_ATTEMPTS + 1):
            delivery.refresh_from_db()
            delivery.next_attempt_at = timezone.now() - timedelta(seconds=1)
            delivery.save()
            events.deliver_due(resolver=public_resolver, transport=self.mock(500))
            delivery.refresh_from_db()
            self.assertEqual(delivery.attempts, attempt)
        self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)
        endpoint.refresh_from_db()
        self.assertEqual(endpoint.failure_count, events.MAX_ATTEMPTS)
        self.assertTrue(endpoint.active)

    def test_the_first_failure_schedules_the_second_attempt_later(self):
        self.endpoint()
        events.emit(self.store, "conversation.closed", {})
        events.deliver_due(resolver=public_resolver, transport=self.mock(503))
        delivery = WebhookDelivery.objects.get()
        self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
        self.assertGreater(delivery.next_attempt_at, timezone.now() + timedelta(seconds=30))
        self.assertEqual(events.deliver_due(resolver=public_resolver, transport=self.mock(200))["sent"], 0)  # not due yet

    def test_a_dead_endpoint_is_switched_off_after_a_run_of_failures(self):
        endpoint = self.endpoint()
        endpoint.failure_count = events.DISABLE_AFTER_FAILURES - 1
        endpoint.save()
        events.emit(self.store, "conversation.closed", {})
        events.deliver_due(resolver=public_resolver, transport=self.mock(500))
        endpoint.refresh_from_db()
        self.assertFalse(endpoint.active)
        self.assertIn("غیرفعال", endpoint.last_status)

    def test_private_and_odd_addresses_are_refused_at_save_and_at_send(self):
        for url in ("http://127.0.0.1/hook", "http://localhost/hook", "http://10.0.0.5/x", "http://169.254.169.254/latest",
                    "http://192.168.1.10:8080/x", "ftp://example.com/x", "https://user:pw@example.com/x",
                    "https://example.com:9999/x", "not a url"):
            with self.assertRaises(events.UnsafeURL, msg=url):
                events.check_url(url, resolver=lambda h, p: ["127.0.0.1"] if h == "localhost" else [PUBLIC_IP])
        # a public name that *resolves* to a private address is refused too (DNS rebinding)
        with self.assertRaises(events.UnsafeURL):
            events.check_url("https://sneaky.example.com/x", resolver=lambda h, p: ["10.1.2.3"])
        endpoint = self.endpoint(url="https://sneaky.example.com/x")
        events.emit(self.store, "conversation.closed", {})
        events.deliver_due(resolver=lambda h, p: ["10.1.2.3"], transport=self.mock(200))
        delivery = WebhookDelivery.objects.get()
        self.assertIn("شبکهٔ داخلی", delivery.error)

    def test_redirects_are_not_followed(self):
        self.endpoint()
        events.emit(self.store, "conversation.closed", {})
        seen: list[httpx.Request] = []

        def handler(request):
            seen.append(request)
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

        events.deliver_due(resolver=public_resolver, transport=httpx.MockTransport(handler))
        self.assertEqual(len(seen), 1)
        self.assertEqual(WebhookDelivery.objects.get().response_code, 302)

    def test_panel_crud_validates_and_shows_the_secret_to_admins_only(self):
        admin, support = self.api(self.admin), self.api(self.sara)
        self.assertEqual(support.get(self.url("dev/webhooks/")).status_code, 403)
        bad = admin.post(self.url("dev/webhooks/"), {"url": "http://127.0.0.1/x"}, format="json")
        self.assertEqual(bad.status_code, 400)
        from unittest.mock import patch

        with patch("apps.inbox.events.safenet.default_resolver", public_resolver):
            ok = admin.post(self.url("dev/webhooks/"), {"url": "https://hooks.example.com/x", "events": ["sla.breached", "bogus"]}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["events"], ["sla.breached"])
        self.assertTrue(ok.json()["secret"])
        pk = ok.json()["id"]
        self.assertEqual(admin.get(self.url("dev/webhooks/")).json()["webhooks"][0]["id"], pk)
        self.assertEqual(admin.patch(self.url(f"dev/webhooks/{pk}/"), {"active": False}, format="json").json()["active"], False)
        self.assertEqual(admin.delete(self.url(f"dev/webhooks/{pk}/")).status_code, 204)

    def test_every_documented_event_is_actually_emitted_somewhere_or_documented_as_manual(self):
        """The event list on the developers page must not promise what no code sends."""
        from pathlib import Path

        source = "\n".join(p.read_text(encoding="utf-8") for p in Path(__file__).parent.glob("*.py")
                           if not p.name.startswith("tests") and p.name != "events.py")
        for name in events.EVENTS:
            literal = f'"{name}"' if name not in ("sla.warning", "sla.breached") else '"sla." + level'
            self.assertIn(literal, source, name)


class PublicApiTests(InboxTestCase):
    def key(self, scopes=None, test=False):
        raw, prefix, hashed = generate_key(test=test)
        row = APIKey.objects.create(store=self.store, name="k", prefix=prefix, key_hash=hashed, scopes=scopes or [],
                                    is_test=test, created_by=self.owner)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw)
        return row, client

    def test_no_key_or_a_wrong_key_is_401(self):
        self.assertEqual(APIClient().get("/api/v1/inbox-api/conversations/").status_code, 401)
        bad = APIClient()
        bad.credentials(HTTP_X_API_KEY="up_live_nope")
        self.assertEqual(bad.get("/api/v1/inbox-api/conversations/").status_code, 401)

    def test_a_key_reads_only_its_own_store(self):
        mine = self.conversation(sender="m", name="من")
        self.conversation(sender="t", store=self.other_store, name="غریبه")
        _, client = self.key()
        got = client.get("/api/v1/inbox-api/conversations/").json()["conversations"]
        self.assertEqual([c["id"] for c in got], [mine.pk])
        self.assertEqual(client.get(f"/api/v1/inbox-api/conversations/{mine.pk}/messages/").status_code, 200)
        other = Conversation.objects.get(store=self.other_store)
        self.assertEqual(client.get(f"/api/v1/inbox-api/conversations/{other.pk}/messages/").status_code, 404)

    def test_scopes_separate_reading_from_writing(self):
        _, reader = self.key(scopes=["inbox_read"])
        self.assertEqual(reader.get("/api/v1/inbox-api/conversations/").status_code, 200)
        denied = reader.post("/api/v1/inbox-api/messages/", {"sender_id": "x", "text": "y"}, format="json")
        self.assertEqual(denied.status_code, 403)
        _, writer = self.key(scopes=["inbox_write"])
        self.assertEqual(writer.get("/api/v1/inbox-api/conversations/").status_code, 403)

    def test_pushing_a_message_in_creates_a_conversation_and_a_contact(self):
        from unittest.mock import patch

        _, client = self.key()
        with patch("apps.customers.views_webhook._respond_later"):
            first = client.post("/api/v1/inbox-api/messages/", {
                "sender_id": "shop-user-7", "name": "کاربر فروشگاه", "phone": "0912 111 2233",
                "text": "سفارشم کجاست؟", "message_id": "m-1"}, format="json")
            again = client.post("/api/v1/inbox-api/messages/", {
                "sender_id": "shop-user-7", "text": "سفارشم کجاست؟", "message_id": "m-1"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertTrue(again.json()["duplicate"])
        conversation = Conversation.objects.get(store=self.store, channel="API")
        self.assertEqual(conversation.customer.inbox_link.contact.phone, "09121112233")

    def test_reply_through_the_api(self):
        conversation = self.conversation(state=Conversation.State.HUMAN)
        _, client = self.key()
        out = client.post(f"/api/v1/inbox-api/conversations/{conversation.pk}/reply/", {"text": "پیگیری شد"}, format="json").json()
        self.assertTrue(out["delivered"])
        self.assertEqual(self.sent[-1][2], "پیگیری شد")

    def test_broadcasts_from_the_api_are_drafts_and_cannot_be_approved_there(self):
        _, client = self.key()
        made = client.post("/api/v1/inbox-api/broadcasts/", {"name": "از API", "text": "سلام"}, format="json")
        self.assertEqual(made.status_code, 201)
        self.assertEqual(made.json()["status"], "DRAFT")
        self.assertIn("فقط از پنل", made.json()["notice"])
        pk = made.json()["id"]
        self.assertEqual(client.post(f"/api/v1/inbox-api/broadcasts/{pk}/approve/", {}, format="json").status_code, 404)
        self.assertEqual(Broadcast.objects.get(pk=pk).status, "DRAFT")

    def test_a_test_key_runs_every_check_and_changes_nothing(self):
        _, client = self.key(test=True)
        self.assertEqual(client.post("/api/v1/inbox-api/messages/", {"sender_id": "x", "text": "y"}, format="json").json()["sandbox"], True)
        self.assertEqual(client.post("/api/v1/inbox-api/contacts/upsert/", {"phone": "09121112233"}, format="json").json()["sandbox"], True)
        self.assertEqual(client.post("/api/v1/inbox-api/broadcasts/", {"name": "n", "text": "t"}, format="json").json()["sandbox"], True)
        self.assertEqual((Conversation.objects.count(), Contact.objects.count(), Broadcast.objects.count()), (0, 0, 0))
        # but validation still runs in the sandbox
        self.assertEqual(client.post("/api/v1/inbox-api/messages/", {"sender_id": "", "text": ""}, format="json").status_code, 400)

    def test_contacts_upsert_by_phone_and_segments_list(self):
        _, client = self.key()
        made = client.post("/api/v1/inbox-api/contacts/upsert/", {"phone": "۰۹۱۲۱۱۱۲۲۳۳", "name": "علی", "tags": ["gym"]}, format="json")
        self.assertEqual(made.status_code, 201)
        again = client.post("/api/v1/inbox-api/contacts/upsert/", {"phone": "09121112233", "tags": ["vip"]}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(sorted(again.json()["tags"]), ["gym", "vip"])
        self.assertEqual(client.post("/api/v1/inbox-api/contacts/upsert/", {"phone": "abc"}, format="json").status_code, 400)
        self.assertEqual(len(client.get("/api/v1/inbox-api/contacts/").json()["contacts"]), 1)
        self.assertGreaterEqual(len(client.get("/api/v1/inbox-api/segments/").json()["segments"]), 6)

    def test_the_platforms_key_page_documents_the_inbox_scopes(self):
        from apps.api_platform import views_keys
        from apps.inbox import views_dev

        views_dev.register_endpoint_docs()
        views_dev.register_endpoint_docs()  # idempotent
        scopes = [e["scope"] for e in views_keys.ENDPOINTS]
        self.assertEqual(scopes.count("inbox_read"), 1)
        self.assertEqual(scopes.count("inbox_write"), 1)

    def test_the_docs_endpoint_renders_with_the_real_base_url(self):
        data = self.api(self.admin).get(self.url("dev/docs/")).json()
        self.assertIn("/api/v1/inbox-api/", data["base"])
        self.assertIn(data["base"], data["markdown"])
        self.assertNotIn("{{BASE}}", data["markdown"])
        self.assertIn("X-Api-Key", data["markdown"])
        for name in ("message.received", "sla.breached", "X-Inbox-Signature"):
            self.assertIn(name, data["markdown"])
