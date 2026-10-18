"""The public API: keys, scopes, and the rule that it costs the same.

Two things carry most of the weight here:

* **The key is never stored.** Only a hash, the way a password is. A key table
  an attacker can read is a table of live credentials to every shop using the
  API.
* **A call through the API costs the same allowance as the same action in the
  panel.** Anything else turns the API into a way around the plan, and the GPU
  does not care which door the request came through.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.jobs.models import Job
from apps.products.models import Product
from apps.stores.models import Store

from .models import APICall, APIKey, generate_key, hash_key


class KeyGenerationTests(TestCase):
    def test_the_plaintext_is_never_the_stored_value(self):
        raw, prefix, hashed = generate_key()
        self.assertNotEqual(raw, hashed)
        self.assertEqual(hashed, hash_key(raw))

    def test_the_prefix_is_visible_so_four_keys_can_be_told_apart(self):
        raw, prefix, _ = generate_key()
        self.assertTrue(raw.startswith(prefix))
        self.assertTrue(prefix.startswith("up_live_"))

    def test_two_keys_are_never_the_same(self):
        self.assertNotEqual(generate_key()[0], generate_key()[0])

    def test_a_key_is_long_enough_that_guessing_is_hopeless(self):
        raw, _, _ = generate_key()
        self.assertGreater(len(raw), 40)


class KeyStateTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("key-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه کلید")
        self.raw, prefix, hashed = generate_key()
        self.key = APIKey.objects.create(
            store=self.store, name="سایت", prefix=prefix, key_hash=hashed,
        )

    def test_a_fresh_key_is_usable(self):
        self.assertTrue(self.key.usable)

    def test_a_revoked_key_is_not(self):
        self.key.is_active = False
        self.key.revoked_at = timezone.now()
        self.assertFalse(self.key.usable)

    def test_an_expired_key_is_not(self):
        self.key.expires_at = timezone.now() - timedelta(days=1)
        self.assertTrue(self.key.is_expired)
        self.assertFalse(self.key.usable)

    def test_no_scopes_means_everything(self):
        """The common case; narrowing is for a key only one system uses."""
        self.assertTrue(self.key.allows("caption"))
        self.assertTrue(self.key.allows("video"))

    def test_a_narrowed_key_allows_only_what_it_lists(self):
        self.key.scopes = ["caption"]
        self.assertTrue(self.key.allows("caption"))
        self.assertFalse(self.key.allows("video"))


class AuthenticationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("auth-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه احراز")
        self.product = Product.objects.create(store=self.store, name="کفش", price=1000)
        self.raw, prefix, hashed = generate_key()
        self.key = APIKey.objects.create(
            store=self.store, name="سرور", prefix=prefix, key_hash=hashed,
        )
        self.url = "/api/v1/public/caption/"

    def _call(self, key=None, **body):
        headers = {"HTTP_X_API_KEY": key} if key else {}
        return self.client.post(
            self.url, body or {"product_id": self.product.pk},
            content_type="application/json", **headers,
        )

    def test_a_valid_key_is_accepted(self):
        response = self._call(self.raw)
        self.assertIn(response.status_code, (202, 503))  # 503 when the queue is down

    def test_no_key_is_rejected(self):
        self.assertIn(self._call().status_code, (401, 403))

    def test_a_wrong_key_is_rejected(self):
        self.assertEqual(self._call("up_live_totallywrong").status_code, 401)

    def test_a_revoked_key_gets_the_same_message_as_a_wrong_one(self):
        """Telling a caller which of the two they hit is telling them whether
        they guessed a real prefix."""
        wrong = self._call("up_live_totallywrong")
        self.key.is_active = False
        self.key.save()
        revoked = self._call(self.raw)
        self.assertEqual(wrong.status_code, revoked.status_code)
        self.assertEqual(wrong.json()["detail"], revoked.json()["detail"])

    def test_a_narrowed_key_cannot_call_outside_its_scope(self):
        self.key.scopes = ["sales_agent"]
        self.key.save()
        response = self._call(self.raw)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "scope_denied")

    def test_using_a_key_records_that_it_was_used(self):
        """So a shop can answer "is this key still in use?" before deleting it."""
        self._call(self.raw)
        self.key.refresh_from_db()
        self.assertIsNotNone(self.key.last_used_at)
        self.assertGreaterEqual(self.key.call_count, 1)

    def test_a_call_is_logged_for_debugging(self):
        self._call(self.raw)
        self.assertTrue(APICall.objects.filter(store=self.store).exists())

    def test_another_shops_product_is_invisible(self):
        other_owner = User.objects.create_user("auth-other", password="x")
        other = Store.objects.create(owner=other_owner, name="فروشگاه دیگر")
        foreign = Product.objects.create(store=other, name="کفش", price=1)

        response = self._call(self.raw, product_id=foreign.pk)
        self.assertEqual(response.status_code, 404)


class KeyManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("mgmt-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه مدیریت")
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.pk}/api-keys/"

    def test_creating_a_key_shows_the_secret_exactly_once(self):
        created = self.client.post(
            self.url, {"name": "سایت"}, content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertIn("secret", created.json())
        self.assertIn("فقط همین یک بار", created.json()["warning"])

        listed = self.client.get(self.url).json()["keys"]
        self.assertNotIn("secret", listed[0])
        self.assertNotIn("key_hash", listed[0])

    def test_a_key_needs_a_name(self):
        """Four unnamed keys in a config file is a problem for the shop, not us."""
        response = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_revoking_keeps_the_row(self):
        """"Which key made these 4000 requests last Tuesday?" has to stay
        answerable."""
        created = self.client.post(
            self.url, {"name": "سایت"}, content_type="application/json",
        ).json()["key"]

        self.client.delete(f"{self.url}{created['id']}/")

        key = APIKey.objects.get(pk=created["id"])
        self.assertFalse(key.is_active)
        self.assertIsNotNone(key.revoked_at)

    def test_the_documentation_travels_with_the_keys(self):
        """A separate doc drifts, and a shop debugging at midnight against
        stale docs concludes the API is broken."""
        body = self.client.get(self.url).json()
        scopes = {e["scope"] for e in body["endpoints"]}
        self.assertEqual(
            scopes,
            {"sales_agent", "caption", "video", "poster", "showcase", "job_status"},
        )
        self.assertEqual(body["header"], "X-Api-Key")

    def test_every_documented_endpoint_says_whether_it_blocks(self):
        """An integration written for a synchronous call that returns a job id
        breaks on the first request."""
        for endpoint in self.client.get(self.url).json()["endpoints"]:
            self.assertIn("sync", endpoint)
            self.assertTrue(endpoint["note"])

    def test_a_stranger_cannot_see_the_keys(self):
        stranger = User.objects.create_user("mgmt-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_support_member_cannot_create_keys(self):
        from apps.stores.models import Membership

        colleague = User.objects.create_user("mgmt-support", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.SUPPORT,
        )
        self.client.force_login(colleague)
        response = self.client.post(
            self.url, {"name": "x"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class DocumentedShapeTests(TestCase):
    """The poster and showcase endpoints make opposite promises."""

    def test_poster_and_showcase_are_separate_endpoints(self):
        from .views_keys import ENDPOINTS

        paths = {e["scope"]: e["path"] for e in ENDPOINTS}
        self.assertNotEqual(paths["poster"], paths["showcase"])

    def test_the_showcase_doc_says_the_real_product_is_kept(self):
        """Hiding that behind a flag is how a caller gets the wrong one."""
        from .views_keys import ENDPOINTS

        showcase = next(e for e in ENDPOINTS if e["scope"] == "showcase")
        self.assertIn("محصول واقعی", showcase["note"])


class ThrottleTests(TestCase):
    """The path the rest of the suite never runs.

    `APIThrottle.allow_request` short-circuits when `IS_TEST` is set, so every
    other test in this file skips throttling entirely — and that is exactly
    where a 500 lived: DRF's default `get_cache_key` reaches for
    `request.user.pk`, and the thing calling this API is a key, not a person.
    Found by running the API for real, not by the suite.
    """

    def setUp(self):
        owner = User.objects.create_user("throttle-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه سقف")
        raw, prefix, hashed = generate_key()
        self.key = APIKey.objects.create(
            store=self.store, name="سرور", prefix=prefix, key_hash=hashed,
        )

    def _request(self, key=None):
        from types import SimpleNamespace

        from apps.api_platform.auth import APIKeyUser

        return SimpleNamespace(
            user=APIKeyUser(key) if key else SimpleNamespace(pk=1, is_authenticated=True),
            META={},
        )

    def test_the_cache_key_does_not_need_a_person(self):
        from apps.api_platform.views import APIThrottle

        cache_key = APIThrottle().get_cache_key(self._request(self.key), None)
        self.assertIsNotNone(cache_key)
        self.assertIn(self.key.prefix, cache_key)

    def test_two_keys_of_one_shop_are_throttled_apart(self):
        """Each key is one integration. A loop in the shop's website should not
        take down their CRM sync."""
        from apps.api_platform.views import APIThrottle

        _, prefix, hashed = generate_key()
        other = APIKey.objects.create(
            store=self.store, name="CRM", prefix=prefix, key_hash=hashed,
        )
        throttle = APIThrottle()
        self.assertNotEqual(
            throttle.get_cache_key(self._request(self.key), None),
            throttle.get_cache_key(self._request(other), None),
        )

    def test_the_api_user_has_the_attributes_django_assumes(self):
        from apps.api_platform.auth import APIKeyUser

        user = APIKeyUser(self.key)
        for attribute in ("pk", "id", "is_authenticated", "is_anonymous",
                          "is_staff", "is_active", "username"):
            self.assertTrue(hasattr(user, attribute), attribute)

    def test_an_api_caller_is_never_staff(self):
        """It carries a store, not a person. Treating it as one would put a
        shop's name on every audit row and hand it the admin surface."""
        from apps.api_platform.auth import APIKeyUser

        user = APIKeyUser(self.key)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)


class SandboxTests(TestCase):
    """A test key that costs nothing. §9.16

    The property that makes it worth having rather than a toy: **a sandbox call
    that succeeds is a live call that will succeed.** Everything up to the point
    where work would be queued runs identically — auth, scope, the product
    lookup, the argument validation — so the tests below are mostly about
    proving the sandbox does *not* skip those.
    """

    def setUp(self):
        owner = User.objects.create_user("sandbox-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه تست")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1_250_000,
        )
        self.raw, prefix, hashed = generate_key(test=True)
        self.key = APIKey.objects.create(
            store=self.store, name="تست", prefix=prefix, key_hash=hashed,
            is_test=True,
        )

    def _call(self, path, **body):
        return self.client.post(
            path, body, content_type="application/json",
            HTTP_X_API_KEY=self.raw,
        )

    def test_a_test_key_is_recognisable_at_a_glance(self):
        """In a config file, in a log line, in a screenshot pasted into support.
        Someone who shipped the wrong one can see it without decoding."""
        self.assertTrue(self.raw.startswith("up_test_"))

    def test_an_async_call_answers_without_queueing_anything(self):
        response = self._call("/api/v1/public/caption/", product_id=self.product.pk)
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["sandbox"])
        self.assertEqual(Job.objects.count(), 0)

    def test_every_sandbox_response_says_it_is_one(self):
        """A developer who ships still holding a test key finds out from the
        first response, not from a customer asking where their videos went."""
        for path in ("/api/v1/public/caption/", "/api/v1/public/video/",
                     "/api/v1/public/poster/", "/api/v1/public/showcase/"):
            body = self._call(path, product_id=self.product.pk).json()
            self.assertTrue(body.get("sandbox"), path)

    def test_the_sales_agent_answers_from_the_shops_own_data(self):
        """A canned blob of lorem ipsum teaches nothing about the shape you
        actually get; their real product with their real price is something
        they can write code against."""
        body = self._call(
            "/api/v1/public/sales-agent/", message="قیمت چند؟",
        ).json()
        self.assertTrue(body["sandbox"])
        self.assertIn("کفش", body["reply"])
        self.assertIn("1,250,000", body["reply"])

    def test_the_shape_matches_the_live_response(self):
        """Otherwise the caller writes code against a structure that does not
        exist in production."""
        body = self._call("/api/v1/public/sales-agent/", message="سلام").json()
        for field in ("reply", "intent", "action", "needs_human", "products",
                      "order", "conversation_id"):
            self.assertIn(field, body, field)

    def test_a_sandbox_job_can_be_polled_and_finishes(self):
        """A sandbox job that stayed QUEUED would make the caller write a
        polling loop that never exits."""
        job_id = self._call(
            "/api/v1/public/caption/", product_id=self.product.pk,
        ).json()["job_id"]

        status_response = self.client.get(
            f"/api/v1/public/jobs/{job_id}/", HTTP_X_API_KEY=self.raw,
        )
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["state"], "COMPLETED")

    # --- what the sandbox must NOT skip ---------------------------------

    def test_a_missing_product_still_404s(self):
        response = self._call("/api/v1/public/caption/", product_id=999999)
        self.assertEqual(response.status_code, 404)

    def test_another_shops_product_is_still_invisible(self):
        other_owner = User.objects.create_user("sandbox-other", password="x")
        other = Store.objects.create(owner=other_owner, name="فروشگاه دیگر")
        foreign = Product.objects.create(store=other, name="کفش", price=1)
        self.assertEqual(
            self._call("/api/v1/public/caption/", product_id=foreign.pk).status_code,
            404,
        )

    def test_scopes_are_still_enforced(self):
        self.key.scopes = ["sales_agent"]
        self.key.save()
        response = self._call("/api/v1/public/caption/", product_id=self.product.pk)
        self.assertEqual(response.status_code, 403)

    def test_an_empty_message_is_still_refused(self):
        self.assertEqual(
            self._call("/api/v1/public/sales-agent/", message="  ").status_code, 400,
        )

    def test_a_revoked_test_key_is_still_revoked(self):
        self.key.is_active = False
        self.key.save()
        self.assertEqual(
            self._call("/api/v1/public/caption/", product_id=self.product.pk).status_code,
            401,
        )

    def test_a_live_key_never_gets_a_sandbox_response(self):
        raw, prefix, hashed = generate_key()
        APIKey.objects.create(
            store=self.store, name="واقعی", prefix=prefix, key_hash=hashed,
        )
        response = self.client.post(
            "/api/v1/public/caption/", {"product_id": self.product.pk},
            content_type="application/json", HTTP_X_API_KEY=raw,
        )
        self.assertNotIn("sandbox", response.json())

    def test_the_panel_explains_how_to_get_one(self):
        self.client.force_login(self.store.owner)
        body = self.client.get(
            f"/api/v1/stores/{self.store.pk}/api-keys/",
        ).json()
        self.assertIn("sandbox", body)
        self.assertIn("test", body["sandbox"]["how"])
