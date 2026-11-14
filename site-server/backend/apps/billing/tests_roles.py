"""Who may READ billing, who may CHANGE it — and what the panel is told about it.

The sidebar usage widget asks `GET /stores/<id>/usage/` on every page. That
read went through `get_store(..., BILLING)` with `write=True`, so the table of
*write* rights decided: only the owner passed. A «مدیر» (ADMIN) — who is allowed
to READ billing by `access.READ` — got a 403 on every single page, and the plan
page was closed to them too. These tests pin the split:

* read (usage, history, subscription, invoices): OWNER and ADMIN;
* change (choose a plan, pay, reject an output): OWNER only;
* everyone else: 403 with the role message; non-members: 404;
* the store payload tells the panel which of the two the caller has
  (`my_role`, `can_view_billing`), so it never has to try-and-fail.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.stores.models import Membership, Store

from .models import Subscription
from .tests import make_plans

User = get_user_model()

R = Membership.Role


class BillingRoleTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="x")
        self.trial, self.pro = make_plans()
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.base = f"/api/v1/stores/{self.store.id}"

        self.people = {}
        for role in (R.ADMIN, R.MARKETING, R.CONTENT_MANAGER, R.SUPPORT, R.VIEWER):
            user = User.objects.create_user(f"u-{role.lower()}", password="x")
            Membership.objects.create(store=self.store, user=user, role=role, is_active=True)
            self.people[role] = user
        self.outsider = User.objects.create_user("outsider", password="x")
        self.ex = User.objects.create_user("ex-admin", password="x")
        Membership.objects.create(store=self.store, user=self.ex, role=R.ADMIN, is_active=False)

    def as_(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    # ------------------------------------------------------------------ read
    def test_owner_reads_usage_and_may_manage(self):
        r = self.as_(self.owner).get(f"{self.base}/usage/")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.data["can_manage"], True)
        self.assertTrue(r.data["metrics"])

    def test_admin_reads_usage_but_may_not_manage(self):
        """The bug: the admin account got 403 here on every page."""
        r = self.as_(self.people[R.ADMIN]).get(f"{self.base}/usage/")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.data["can_manage"], False)
        self.assertEqual({m["metric"] for m in r.data["metrics"]} >= {"IMAGES"}, True)

    def test_admin_reads_history_subscription_and_invoices(self):
        c = self.as_(self.people[R.ADMIN])
        self.assertEqual(c.get(f"{self.base}/usage/history/").status_code, 200)
        self.assertEqual(c.get(f"{self.base}/subscription/").status_code, 200)
        self.assertEqual(c.get(f"{self.base}/billing/").status_code, 200)

    def test_roles_without_billing_read_still_get_the_role_message(self):
        for role in (R.MARKETING, R.CONTENT_MANAGER, R.SUPPORT, R.VIEWER):
            c = self.as_(self.people[role])
            for suffix in ("usage/", "usage/history/", "subscription/", "billing/"):
                r = c.get(f"{self.base}/{suffix}")
                self.assertEqual(r.status_code, 403, f"{role} {suffix}")
            self.assertIn("نقش شما", str(self.as_(self.people[role]).get(f"{self.base}/usage/").data))

    def test_outsiders_and_removed_members_do_not_learn_the_store_exists(self):
        for user in (self.outsider, self.ex):
            c = self.as_(user)
            for suffix in ("usage/", "usage/history/", "subscription/", "billing/"):
                self.assertEqual(c.get(f"{self.base}/{suffix}").status_code, 404, f"{user} {suffix}")

    # ---------------------------------------------------------------- change
    def test_admin_cannot_change_plan_or_pay_or_reject(self):
        c = self.as_(self.people[R.ADMIN])
        self.assertEqual(c.post(f"{self.base}/subscription/", {"plan": "pro"}).status_code, 403)
        self.assertEqual(c.post(f"{self.base}/payments/", {"plan": "pro"}).status_code, 403)
        self.assertEqual(c.post(f"{self.base}/usage/1/reject/", {}).status_code, 403)
        # …and nothing changed
        sub = Subscription.objects.get(store=self.store)
        self.assertEqual(sub.plan_id, self.trial.id)

    def test_owner_still_changes_plan(self):
        r = self.as_(self.owner).post(f"{self.base}/subscription/", {"plan": "pro"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], Subscription.Status.PAST_DUE)

    # ------------------------------------------------------- the store payload
    def test_store_payload_says_what_the_caller_may_do(self):
        expect = {
            self.owner: ("OWNER", True, True),
            self.people[R.ADMIN]: ("ADMIN", True, False),
            self.people[R.MARKETING]: ("MARKETING", False, False),
            self.people[R.SUPPORT]: ("SUPPORT", False, False),
            self.people[R.VIEWER]: ("VIEWER", False, False),
        }
        for user, (role, can_view, can_manage) in expect.items():
            r = self.as_(user).get(f"/api/v1/stores/{self.store.id}/")
            self.assertEqual(r.status_code, 200, user)
            self.assertEqual(r.data["my_role"], role, user)
            self.assertIs(r.data["can_view_billing"], can_view, user)
            self.assertIs(r.data["can_manage_billing"], can_manage, user)

    def test_store_list_carries_the_same_flags(self):
        r = self.as_(self.people[R.ADMIN]).get("/api/v1/stores/")
        self.assertEqual(r.status_code, 200)
        rows = r.data["results"] if isinstance(r.data, dict) else r.data
        mine = [row for row in rows if row["id"] == self.store.id][0]
        self.assertEqual(mine["my_role"], "ADMIN")
        self.assertIs(mine["can_view_billing"], True)
        r = self.as_(self.people[R.VIEWER]).get("/api/v1/stores/")
        rows = r.data["results"] if isinstance(r.data, dict) else r.data
        mine = [row for row in rows if row["id"] == self.store.id][0]
        self.assertIs(mine["can_view_billing"], False)

    def test_serializer_without_a_request_does_not_crash(self):
        """Other code serializes stores with no request in the context."""
        from apps.stores.serializers import StoreSerializer

        data = StoreSerializer(self.store).data
        self.assertIsNone(data["my_role"])
        self.assertIsNone(data["can_view_billing"])
