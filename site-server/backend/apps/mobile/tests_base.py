"""Shared helpers for the NM-Mobile tests. Nothing here talks to a real SMS gateway, phone, Telegram or AI provider."""
from __future__ import annotations

import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.stores.models import Membership, Store

from .models import MobileSettings

BASE = "/api/v1/mobile/"
TMP_DATA = tempfile.mkdtemp(prefix="nm-mobile-test-")


@override_settings(NM_DATA_DIR=TMP_DATA, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MobileTestCase(TestCase):
    password = "S3cret-pass-123"

    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user("marketer", "m@example.com", self.password, is_staff=True)
        self.boss = User.objects.create_user("boss", "b@example.com", self.password, is_staff=True, is_superuser=True)
        self.plain = User.objects.create_user("plain", "p@example.com", self.password)
        self.store = Store.objects.create(owner=self.boss, name="فروشگاه آزمون")
        # the marketer works in this store (role MARKETING), exactly how NM gives a colleague access to a shop
        Membership.objects.create(store=self.store, user=self.staff, role=Membership.Role.MARKETING)
        MobileSettings.get()

    # ---- clients
    def pair(self, username="marketer", install_id="inst-1", name="گوشی آزمون", **extra):
        c = APIClient()
        r = c.post(BASE + "pair/", {"username": username, "password": self.password, "device_name": name, "install_id": install_id, **extra},
                   format="json")
        return r

    def device_client(self, username="marketer", install_id="inst-1"):
        r = self.pair(username, install_id)
        assert r.status_code == 201, r.content
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Device " + r.data["device_token"])
        c.token = r.data["device_token"]
        c.device_uid = r.data["device"]["uid"]
        return c

    def panel_client(self, user=None):
        c = APIClient()
        c.force_authenticate(user or self.boss)
        return c

    def post(self, client, path, data=None, **kw):
        return client.post(BASE + path, data or {}, format=kw.pop("format", "json"), **kw)

    def get(self, client, path, **params):
        return client.get(BASE + path, params)
