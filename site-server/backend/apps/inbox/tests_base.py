"""Shared fixtures for the inbox tests. No test here touches the network except
`FakePlatform`, a real HTTP server on 127.0.0.1 speaking each platform's format."""
from __future__ import annotations

import tempfile

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.customers.models import Conversation, Customer, Message
from apps.stores.models import Membership, Store

from . import team
from .models import AgentProfile, ChannelConnection

TMP = tempfile.mkdtemp(prefix="nm-inbox-test-")
PASSWORD = "S3cret-pass-123"


@override_settings(
    NM_DATA_DIR=TMP,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    # Any accidental platform call dies instantly on a closed port instead of
    # reaching the real internet from a test run.
    INBOX_API_BASES={k: "http://127.0.0.1:1" for k in ("BALE", "EITAA", "RUBIKA", "WHATSAPP", "TELEGRAM")},
)
class InboxTestCase(TestCase):
    """A store with an owner, an admin, two support agents and a viewer."""

    def setUp(self):
        super().setUp()
        # The legacy Telegram / Instagram senders call the internet directly.
        self.sent = []

        def fake_telegram(store, to, text):
            self.sent.append(("TELEGRAM", to, text))
            return {"sent": True, "reason": ""}

        for target, fake in (
            ("services.publishing.channels._send_telegram", fake_telegram),
            ("services.publishing.channels._send_via_integration",
             lambda channel, store, to, text: {"sent": True, "reason": ""}),
        ):
            patcher = patch(target, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.owner = User.objects.create_user("boss", "b@example.com", PASSWORD)
        self.admin = User.objects.create_user("admin1", "a@example.com", PASSWORD)
        self.sara = User.objects.create_user("sara", "s@example.com", PASSWORD)
        self.reza = User.objects.create_user("reza", "r@example.com", PASSWORD)
        self.viewer = User.objects.create_user("viewer", "v@example.com", PASSWORD)
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه آزمون")
        for user, role in (
            (self.admin, Membership.Role.ADMIN), (self.sara, Membership.Role.SUPPORT),
            (self.reza, Membership.Role.SUPPORT), (self.viewer, Membership.Role.VIEWER),
        ):
            Membership.objects.create(store=self.store, user=user, role=role)
        from apps.stores.models import StoreProfile

        profile, _ = StoreProfile.objects.get_or_create(store=self.store)
        profile.telegram_bot_token = "111:TESTTOKENTESTTOKENTESTTOKEN"
        profile.save()
        self.store.refresh_from_db()  # drop the reverse-relation cache the profile signal left behind
        self.other_owner = User.objects.create_user("other", "o@example.com", PASSWORD)
        self.other_store = Store.objects.create(owner=self.other_owner, name="فروشگاه دیگر")

    # ---- people ------------------------------------------------------
    def online(self, *users):
        for user in users:
            team.set_status(self.store, user, AgentProfile.Status.ONLINE)

    def api(self, user=None) -> APIClient:
        c = APIClient()
        c.force_authenticate(user or self.owner)
        return c

    def url(self, path: str, store=None) -> str:
        return f"/api/v1/stores/{(store or self.store).pk}/inbox/{path}"

    # ---- conversations --------------------------------------------------
    def conversation(self, channel="TELEGRAM", name="مشتری", sender="u1", state=Conversation.State.AI,
                     store=None, phone="") -> Conversation:
        store = store or self.store
        customer = Customer.objects.create(
            store=store, name=name, external_id=sender, channel=channel.lower(), phone=phone,
        )
        return Conversation.objects.create(
            store=store, customer=customer, channel=channel, external_id=sender, state=state,
        )

    def customer_says(self, conversation: Conversation, text="سلام", external_id="") -> Message:
        message = Message.objects.create(
            conversation=conversation, role=Message.Role.CUSTOMER, text=text, external_id=external_id,
        )
        conversation.refresh_from_db()
        return message

    def connect(self, kind: str, *, token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ", enabled=True,
                config=None, store=None) -> ChannelConnection:
        row, _ = ChannelConnection.objects.update_or_create(
            store=store or self.store, kind=kind,
            defaults={"token": token, "enabled": enabled, "config": config or {}},
        )
        return row
