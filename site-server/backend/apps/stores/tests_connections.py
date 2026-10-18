"""Connecting a shop's own social accounts (`ایده‌ها پنل.md` صفحه ۳، بند ۱).

The plumbing existed and no page ever asked for any of it, so the interesting
cases are all about what a settings form does to a credential:

**The token is never read back.** It belongs to the shop's own account. A
response that echoes it is a credential that ends up in a log, a screenshot or
a browser cache — and "is one set?" is all a settings page needs.

**An empty box means "leave it alone", not "delete it".** Otherwise saving a
changed Instagram link would silently disconnect publishing.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Membership, Store, StoreProfile


class ConnectionsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("conn-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.url = f"/api/v1/stores/{self.store.pk}/connections/"
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_the_token_never_comes_back(self):
        self.client.patch(self.url, {"novinhub_token": "secret-123"}, format="json")
        body = self.client.get(self.url).json()
        self.assertTrue(body["has_token"])
        self.assertNotIn("novinhub_token", body)
        self.assertNotIn("secret-123", str(body))

    def test_saving_it_actually_stores_it(self):
        self.client.patch(self.url, {"novinhub_token": " secret-123 "}, format="json")
        profile = StoreProfile.objects.get(store=self.store)
        self.assertEqual(profile.novinhub_token, "secret-123")

    def test_not_sending_the_token_leaves_it_alone(self):
        """The panel omits the field when the box is empty. If a partial update
        blanked it, editing an Instagram link would disconnect publishing."""
        self.client.patch(self.url, {"novinhub_token": "keep-me"}, format="json")
        self.client.patch(
            self.url, {"social_links": {"instagram": "https://x.ir"}}, format="json",
        )
        self.assertEqual(
            StoreProfile.objects.get(store=self.store).novinhub_token, "keep-me",
        )

    def test_an_explicit_empty_string_clears_it(self):
        self.client.patch(self.url, {"novinhub_token": "gone"}, format="json")
        self.client.patch(self.url, {"novinhub_token": ""}, format="json")
        self.assertFalse(self.client.get(self.url).json()["has_token"])

    def test_account_ids_are_trimmed_and_blanks_dropped(self):
        res = self.client.patch(
            self.url, {"novinhub_account_ids": [" 12 ", "", "34"]}, format="json",
        )
        self.assertEqual(res.json()["novinhub_account_ids"], ["12", "34"])

    def test_unknown_social_key_is_refused(self):
        """Free-form keys mean a typo becomes a link nothing ever renders."""
        res = self.client.patch(
            self.url, {"social_links": {"myspace": "https://x"}}, format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_channel_status_comes_back_with_it(self):
        body = self.client.get(self.url).json()
        self.assertTrue(body["channels"])
        self.assertIn("configured", body["channels"][0])

    def test_another_users_store_is_invisible(self):
        stranger = User.objects.create_user("conn-stranger", password="x")
        client = APIClient()
        client.force_authenticate(stranger)
        self.assertIn(client.get(self.url).status_code, (403, 404))

    def test_a_support_member_cannot_change_integrations(self):
        member = User.objects.create_user("conn-support", password="x")
        Membership.objects.create(
            store=self.store, user=member, role=Membership.Role.SUPPORT,
        )
        client = APIClient()
        client.force_authenticate(member)
        res = client.patch(self.url, {"novinhub_token": "nope"}, format="json")
        self.assertIn(res.status_code, (403, 404))
