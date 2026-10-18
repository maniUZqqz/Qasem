"""The checklist has to describe reality, or it is worse than nothing.

A store that already added products and then sees "add your first product"
learns that the checklist is decoration and stops reading it — which is the
one thing an onboarding list cannot survive.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.ai.models import ProductIntelligence, StoreAIPolicy
from apps.content.models import Caption
from apps.products.models import Product

from . import agent_settings, onboarding
from .models import Membership, Store

NO_PUBLISHING = {"NOVINHUB_TOKEN": "", "N8N_WEBHOOK_URL": ""}


@override_settings(UPMARKET_AI=NO_PUBLISHING)
class ChecklistTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("onboard-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه تازه")

    def _keys_done(self):
        return {s.key for s in onboarding.steps(self.store) if s.done}

    def test_a_brand_new_store_has_nothing_done(self):
        self.assertEqual(self._keys_done(), set())

    def test_the_first_suggestion_is_something_you_can_actually_finish(self):
        """`next` must never point at a step whose prerequisite is missing."""
        nxt = onboarding.summary(self.store)["next"]
        self.assertEqual(nxt["blocked_by"], [])

    def test_adding_a_product_ticks_exactly_that_step(self):
        Product.objects.create(store=self.store, name="کفش", price=100)
        self.assertEqual(self._keys_done(), {"first_product"})

    def test_writing_a_brand_voice_counts(self):
        self.store.profile.tone = "دوستانه"
        self.store.profile.save()
        self.assertIn("brand_voice", self._keys_done())

    def test_analysis_is_blocked_until_there_is_a_photo(self):
        """Analysing a product with no photo sends the owner somewhere they
        cannot finish."""
        rows = {s.key: s for s in onboarding.steps(self.store)}
        self.assertEqual(rows["analysis"].blocked_by, ["product_photo"])

    def test_a_photo_unblocks_analysis(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.products.models import ProductImage

        product = Product.objects.create(store=self.store, name="کفش", price=100)
        ProductImage.objects.create(
            product=product,
            image=SimpleUploadedFile("p.jpg", b"jpeg-bytes", content_type="image/jpeg"),
        )
        rows = {s.key: s for s in onboarding.steps(self.store)}
        self.assertTrue(rows["product_photo"].done)
        self.assertEqual(rows["analysis"].blocked_by, [])

    def test_analysis_of_any_product_counts(self):
        product = Product.objects.create(store=self.store, name="کفش", price=100)
        ProductIntelligence.objects.create(product=product)
        self.assertIn("analysis", self._keys_done())

    def test_content_counts_whichever_kind_it_is(self):
        Caption.objects.create(
            store=self.store,
            product=Product.objects.create(store=self.store, name="کفش", price=100),
            platform="INSTAGRAM", short_text="سلام",
        )
        self.assertIn("first_content", self._keys_done())

    def test_touching_the_agent_settings_counts_but_reading_them_does_not(self):
        """`settings_for` creates the row on first read. If mere creation
        counted, the step would tick itself the moment anyone opened the page.
        """
        agent_settings.settings_for(self.store)
        self.store.refresh_from_db()
        self.assertNotIn("agent_settings", self._keys_done())

        row = agent_settings.settings_for(self.store)
        row.tone = "FORMAL"
        row.save()
        self.store.refresh_from_db()
        self.assertIn("agent_settings", self._keys_done())

    def test_the_data_policy_step_needs_a_real_decision(self):
        """A row that exists is not a decision; an acknowledgement is."""
        StoreAIPolicy.objects.create(store=self.store)
        self.store.refresh_from_db()
        self.assertNotIn("data_policy", self._keys_done())

    def test_acknowledging_the_policy_counts(self):
        from django.utils import timezone

        StoreAIPolicy.objects.create(
            store=self.store, acknowledged_at=timezone.now(), acknowledged_by=self.owner,
        )
        self.store.refresh_from_db()
        self.assertIn("data_policy", self._keys_done())

    def test_the_shared_publishing_token_counts(self):
        """It is how a store publishes on day one, before the owner has their
        own NovinHub account."""
        with override_settings(UPMARKET_AI={"NOVINHUB_TOKEN": "shared", "N8N_WEBHOOK_URL": ""}):
            self.assertIn("publishing", self._keys_done())

    def test_a_store_specific_token_counts_too(self):
        self.store.profile.novinhub_token = "own-token"
        self.store.profile.save()
        self.assertIn("publishing", self._keys_done())

    def test_progress_is_counted_from_rows_not_from_clicks(self):
        summary = onboarding.summary(self.store)
        self.assertEqual(summary["done_count"], 0)
        self.assertEqual(summary["total"], len(summary["steps"]))
        self.assertFalse(summary["complete"])

    def test_every_step_explains_why_it_matters(self):
        """A checklist item with no reason gets skipped."""
        for step in onboarding.steps(self.store):
            self.assertTrue(step.why.strip(), f"«{step.key}» دلیلی ندارد")
            self.assertTrue(step.action, f"«{step.key}» جایی برای رفتن ندارد")


@override_settings(UPMARKET_AI=NO_PUBLISHING)
class OnboardingAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("ob-api-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه API")
        self.url = f"/api/v1/stores/{self.store.id}/onboarding/"

    def test_the_owner_sees_the_checklist(self):
        self.client.force_login(self.owner)
        body = self.client.get(self.url).json()
        self.assertEqual(body["done_count"], 0)
        self.assertIsNotNone(body["next"])

    def test_any_member_may_read_it(self):
        """A content manager who cannot tell the brand voice is empty keeps
        generating copy the owner throws away."""
        colleague = User.objects.create_user("ob-colleague", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.CONTENT_MANAGER
        )
        self.client.force_login(colleague)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_a_stranger_gets_404(self):
        stranger = User.objects.create_user("ob-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_anonymous_is_rejected(self):
        self.assertIn(self.client.get(self.url).status_code, (401, 403))
