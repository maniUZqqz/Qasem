from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import Store


class StoreTenancyTests(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="Str0ngPass!x")
        self.bob = User.objects.create_user("bob", password="Str0ngPass!x")
        self.alice_store = Store.objects.create(owner=self.alice, name="Alice Shop")
        self.bob_store = Store.objects.create(owner=self.bob, name="Bob Shop")

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def test_owner_sees_only_own_stores(self):
        self.auth(self.alice)
        resp = self.client.get("/api/v1/stores/")
        self.assertEqual(resp.status_code, 200)
        names = [s["name"] for s in resp.data["results"]]
        self.assertEqual(names, ["Alice Shop"])

    def test_cannot_access_other_users_store(self):
        self.auth(self.alice)
        resp = self.client.get(f"/api/v1/stores/{self.bob_store.id}/")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.patch(f"/api/v1/stores/{self.bob_store.id}/", {"name": "hacked"})
        self.assertEqual(resp.status_code, 404)

    def test_create_store_sets_owner_and_profile(self):
        self.auth(self.alice)
        resp = self.client.post(
            "/api/v1/stores/", {"name": "کیف چرم آلیس", "business_type": "پوشاک"}
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        store = Store.objects.get(id=resp.data["id"])
        self.assertEqual(store.owner, self.alice)
        self.assertTrue(store.slug)
        self.assertIsNotNone(store.profile)

    def test_profile_update(self):
        self.auth(self.alice)
        url = f"/api/v1/stores/{self.alice_store.id}/profile/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        resp = self.client.patch(url, {"tone": "صمیمی", "shipping_policy": "ارسال ۳ روزه"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.alice_store.profile.refresh_from_db()
        self.assertEqual(self.alice_store.profile.tone, "صمیمی")

    def test_unauthenticated_rejected(self):
        resp = self.client.get("/api/v1/stores/")
        self.assertEqual(resp.status_code, 401)
