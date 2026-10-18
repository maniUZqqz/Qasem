"""Roles, and the isolation they must never weaken.

Multi-user is the change most likely to open a tenant leak: thirty-two call
sites used to ask "is this store mine?" and every one of them had to become
"may this person reach this store?". A single missed spot is not a missing
feature — it is one shop reading another's customers.

So this file tests two things: that roles do what they say, and that nothing
anywhere still asks the old question.
"""
import ast
from pathlib import Path

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.products.models import Product

from . import access
from .models import Membership, Store

APPS_DIR = Path(__file__).resolve().parent.parent


class RoleMatrixTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("matrix-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه نقش‌ها")

    def _member(self, username, role):
        user = User.objects.create_user(username, password="x")
        Membership.objects.create(store=self.store, user=user, role=role)
        return user

    def test_owner_can_do_everything(self):
        for permission in access.ALL:
            self.assertTrue(access.can(self.owner, self.store, permission))

    def test_owner_needs_no_membership_row(self):
        """Ownership is the tenant's anchor, not a seat at the table.

        If it were a row, removing the last owner would orphan a paying store.
        """
        self.assertEqual(Membership.objects.filter(store=self.store).count(), 0)
        self.assertEqual(access.role_of(self.owner, self.store), access.Role.OWNER)

    def test_admin_runs_the_shop_but_does_not_spend_the_owners_money(self):
        admin = self._member("matrix-admin", Membership.Role.ADMIN)
        self.assertTrue(access.can(admin, self.store, access.CONTENT))
        self.assertTrue(access.can(admin, self.store, access.MEMBERS))
        self.assertFalse(access.can(admin, self.store, access.BILLING))

    def test_support_sees_conversations_and_not_the_invoices(self):
        support = self._member("matrix-support", Membership.Role.SUPPORT)
        self.assertTrue(access.can(support, self.store, access.CONVERSATIONS))
        self.assertFalse(access.can(support, self.store, access.BILLING))
        self.assertFalse(access.can(support, self.store, access.CAMPAIGNS))

    def test_marketing_can_read_the_catalogue_it_writes_campaigns_about(self):
        """Read is wider than write on purpose — a marketer who cannot see the
        products cannot write a campaign for them."""
        marketer = self._member("matrix-marketing", Membership.Role.MARKETING)
        self.assertFalse(access.can(marketer, self.store, access.PRODUCTS))
        self.assertTrue(access.can(marketer, self.store, access.PRODUCTS, write=False))

    def test_viewer_changes_nothing(self):
        viewer = self._member("matrix-viewer", Membership.Role.VIEWER)
        for permission in access.ALL:
            self.assertFalse(access.can(viewer, self.store, permission))

    def test_viewer_cannot_read_billing_or_the_member_list(self):
        """What the shop pays and who else has keys are the owner's business."""
        viewer = self._member("matrix-viewer2", Membership.Role.VIEWER)
        self.assertFalse(access.can(viewer, self.store, access.BILLING, write=False))
        self.assertFalse(access.can(viewer, self.store, access.MEMBERS, write=False))
        self.assertTrue(access.can(viewer, self.store, access.CONTENT, write=False))

    def test_a_stranger_has_no_role(self):
        stranger = User.objects.create_user("matrix-stranger", password="x")
        self.assertIsNone(access.role_of(stranger, self.store))
        self.assertFalse(access.can(stranger, self.store, access.CONTENT, write=False))

    def test_a_removed_member_loses_access_immediately(self):
        person = self._member("matrix-removed", Membership.Role.ADMIN)
        Membership.objects.filter(store=self.store, user=person).update(is_active=False)
        self.assertIsNone(access.role_of(person, self.store))

    def test_anonymous_has_no_role(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertIsNone(access.role_of(AnonymousUser(), self.store))


class GetStoreTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("gs-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه دسترسی")
        self.support = User.objects.create_user("gs-support", password="x")
        Membership.objects.create(
            store=self.store, user=self.support, role=Membership.Role.SUPPORT
        )
        self.stranger = User.objects.create_user("gs-stranger", password="x")

    def test_a_stranger_gets_404_not_403(self):
        """Whether this store exists is not theirs to learn."""
        from django.http import Http404

        with self.assertRaises(Http404):
            access.get_store(self.stranger, self.store.pk, access.CONTENT)

    def test_a_member_without_the_permission_gets_403_with_their_role_named(self):
        """403, not 404: hiding a store they genuinely belong to would have
        them filing a bug instead of asking for a role change."""
        with self.assertRaises(access.NoAccess) as caught:
            access.get_store(self.support, self.store.pk, access.BILLING)
        self.assertIn("پشتیبانی", str(caught.exception))

    def test_a_member_with_the_permission_gets_the_store(self):
        found = access.get_store(self.support, self.store.pk, access.CONVERSATIONS)
        self.assertEqual(found, self.store)

    def test_no_permission_argument_means_membership_is_enough(self):
        self.assertEqual(access.get_store(self.support, self.store.pk), self.store)

    def test_a_missing_store_is_404(self):
        from django.http import Http404

        with self.assertRaises(Http404):
            access.get_store(self.owner, 999_999, access.CONTENT)


class IsolationTests(TestCase):
    """The part that must not regress."""

    def setUp(self):
        self.mine = User.objects.create_user("iso-mine", password="x")
        self.theirs = User.objects.create_user("iso-theirs", password="x")
        self.my_store = Store.objects.create(owner=self.mine, name="مال من")
        self.their_store = Store.objects.create(owner=self.theirs, name="مال آن‌ها")
        Product.objects.create(store=self.my_store, name="کالای من", price=1000)
        Product.objects.create(store=self.their_store, name="کالای آن‌ها", price=2000)

    def test_stores_for_returns_only_reachable_stores(self):
        self.assertEqual(list(access.stores_for(self.mine)), [self.my_store])

    def test_a_member_sees_the_store_they_were_added_to(self):
        colleague = User.objects.create_user("iso-colleague", password="x")
        Membership.objects.create(
            store=self.my_store, user=colleague, role=Membership.Role.SUPPORT
        )
        self.assertEqual(list(access.stores_for(colleague)), [self.my_store])

    def test_membership_in_one_store_does_not_leak_another(self):
        colleague = User.objects.create_user("iso-colleague2", password="x")
        Membership.objects.create(
            store=self.my_store, user=colleague, role=Membership.Role.ADMIN
        )
        reachable = access.stores_for(colleague)
        self.assertNotIn(self.their_store, reachable)

    def test_a_store_is_listed_once_even_if_owned_and_joined(self):
        """A duplicate row would double every list the dashboard draws."""
        Membership.objects.create(
            store=self.my_store, user=self.mine, role=Membership.Role.ADMIN
        )
        self.assertEqual(access.stores_for(self.mine).count(), 1)

    def test_products_api_shows_only_reachable_stores(self):
        self.client.force_login(self.mine)
        response = self.client.get("/api/v1/products/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        names = [row["name"] for row in body.get("results", body)]
        self.assertIn("کالای من", names)
        self.assertNotIn("کالای آن‌ها", names)

    def test_a_colleague_sees_the_shared_catalogue_and_nothing_else(self):
        colleague = User.objects.create_user("iso-colleague3", password="x")
        Membership.objects.create(
            store=self.my_store, user=colleague, role=Membership.Role.CONTENT_MANAGER
        )
        self.client.force_login(colleague)
        body = self.client.get("/api/v1/products/").json()
        names = [row["name"] for row in body.get("results", body)]
        self.assertEqual(names, ["کالای من"])


class MembersAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("api-owner2", password="x", email="o@x.ir")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه اعضا")
        self.colleague = User.objects.create_user(
            "api-colleague", password="x", email="c@x.ir"
        )
        self.url = f"/api/v1/stores/{self.store.id}/members/"
        self.client.force_login(self.owner)

    def test_the_owner_appears_in_the_list(self):
        """They have no Membership row; a list of "who can get into my shop"
        that omits the owner is wrong."""
        body = self.client.get(self.url).json()
        self.assertEqual(body["members"][0]["username"], "api-owner2")
        self.assertTrue(body["members"][0]["is_owner"])

    def test_adding_a_colleague_by_username(self):
        response = self.client.post(
            self.url, {"user": "api-colleague", "role": "SUPPORT"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Membership.objects.filter(store=self.store, user=self.colleague).exists()
        )

    def test_adding_by_email_works_too(self):
        response = self.client.post(
            self.url, {"user": "c@x.ir", "role": "VIEWER"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_an_unknown_person_gets_a_message_that_says_what_to_do(self):
        response = self.client.post(
            self.url, {"user": "nobody@nowhere.ir", "role": "VIEWER"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("حساب", response.json()["error"]["message"])

    def test_adding_the_owner_again_is_refused(self):
        response = self.client.post(
            self.url, {"user": "api-owner2", "role": "ADMIN"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_an_invalid_role_is_rejected(self):
        response = self.client.post(
            self.url, {"user": "api-colleague", "role": "SUPERUSER"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_re_adding_a_removed_person_restores_the_one_seat(self):
        self.client.post(
            self.url, {"user": "api-colleague", "role": "SUPPORT"},
            content_type="application/json",
        )
        row = Membership.objects.get(store=self.store, user=self.colleague)
        self.client.delete(f"{self.url}{row.pk}/")
        self.client.post(
            self.url, {"user": "api-colleague", "role": "ADMIN"},
            content_type="application/json",
        )
        self.assertEqual(
            Membership.objects.filter(store=self.store, user=self.colleague).count(), 1
        )
        row.refresh_from_db()
        self.assertTrue(row.is_active)
        self.assertEqual(row.role, "ADMIN")

    def test_removing_access_keeps_the_record(self):
        """"Who removed me, and when?" has to have an answer."""
        self.client.post(
            self.url, {"user": "api-colleague", "role": "SUPPORT"},
            content_type="application/json",
        )
        row = Membership.objects.get(store=self.store, user=self.colleague)
        self.assertEqual(self.client.delete(f"{self.url}{row.pk}/").status_code, 204)
        row.refresh_from_db()
        self.assertFalse(row.is_active)
        self.assertIsNotNone(row.removed_at)

    def test_a_support_member_cannot_manage_members(self):
        Membership.objects.create(
            store=self.store, user=self.colleague, role=Membership.Role.SUPPORT
        )
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_a_stranger_gets_404(self):
        stranger = User.objects.create_user("api-stranger2", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_member_of_another_store_cannot_be_edited_through_mine(self):
        other_owner = User.objects.create_user("api-other-owner", password="x")
        other = Store.objects.create(owner=other_owner, name="فروشگاه دیگر")
        foreign = Membership.objects.create(
            store=other, user=self.colleague, role=Membership.Role.ADMIN
        )
        response = self.client.patch(
            f"{self.url}{foreign.pk}/", {"role": "VIEWER"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class OwnershipQueryBoundaryTests(SimpleTestCase):
    """Nothing may go back to asking the ownership question on its own.

    `owner=request.user` and `store__owner=request.user` were the right check
    when a store had exactly one user. Now they are a silent way to lock a
    colleague out — or, in a filter that is meant to widen, to leak. The access
    layer is the only place allowed to spell them.
    """

    FORBIDDEN = ("owner=request.user", "owner=self.request.user", "store__owner")

    # The access layer defines the rule.
    EXEMPT = {"stores/access.py"}

    #: Setting the owner when a store is created is the opposite of the problem:
    #: it is a write, not a query, and someone has to be recorded as owner.
    ALLOWED_FORMS = (".save(owner=",)

    def test_no_view_or_serializer_asks_about_ownership_directly(self):
        offences = []
        for path in sorted(APPS_DIR.rglob("*.py")):
            rel = path.relative_to(APPS_DIR).as_posix()
            if "__pycache__" in rel or "/migrations/" in rel or rel in self.EXEMPT:
                continue
            if path.name.startswith("test"):
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if any(form in line for form in self.ALLOWED_FORMS):
                    continue
                if any(token in line for token in self.FORBIDDEN):
                    offences.append(f"apps/{rel}:{number} → {line.strip()}")
        self.assertEqual(
            offences, [],
            "این‌ها باید از apps.stores.access رد شوند تا اعضای فروشگاه هم دسترسی داشته باشند:\n"
            + "\n".join(offences),
        )

    def test_every_permission_is_granted_to_someone_and_denied_to_someone(self):
        """A permission nobody has is dead code; one everybody has is decoration."""
        for permission in access.ALL:
            granted = [r for r, perms in access.WRITE.items() if permission in perms]
            denied = [r for r, perms in access.WRITE.items() if permission not in perms]
            self.assertTrue(granted, f"هیچ نقشی «{permission}» را ندارد")
            self.assertTrue(denied, f"همه‌ی نقش‌ها «{permission}» را دارند")

    def test_write_never_exceeds_read(self):
        """Being able to change something you cannot see is a bug, not a role."""
        for role, writable in access.WRITE.items():
            self.assertTrue(
                writable <= access.READ[role],
                f"نقش {role} می‌تواند چیزی را عوض کند که اجازه‌ی دیدنش را ندارد",
            )
