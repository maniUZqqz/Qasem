"""What the data policy actually does when a job asks for a provider.

The rule under test throughout: a store that said its data stays home gets a
clear refusal, never a quiet external call. Every assertion here is the
difference between a privacy promise and a privacy claim.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.stores.models import Store
from services.ai import gateway, providers

from .models import ModelProvider, StoreAIPolicy


def _local_row(**kwargs):
    defaults = dict(
        capability=ModelProvider.Capability.TEXT,
        kind=ModelProvider.Kind.OLLAMA,
        name="اولامای خودمان",
        model_name="qwq:32b",
        priority=10,
    )
    defaults.update(kwargs)
    return ModelProvider.objects.create(**defaults)


def _external_row(**kwargs):
    defaults = dict(
        capability=ModelProvider.Capability.TEXT,
        kind=ModelProvider.Kind.OPENAI,
        name="API بیرونی",
        base_url="https://api.example.com/v1",
        api_key="k",
        model_name="gpt-4o-mini",
        priority=50,
    )
    defaults.update(kwargs)
    return ModelProvider.objects.create(**defaults)


class PolicyResolutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("shopkeeper", password="x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه تست")

    # ---- defaults --------------------------------------------------------

    def test_store_without_a_row_uses_the_platform_default(self):
        policy = gateway.policy_for(self.store)
        self.assertEqual(policy.mode, gateway.HYBRID)
        self.assertTrue(policy.is_default)

    @override_settings(UPMARKET_AI={**{}, "AI_DEFAULT_POLICY": "LOCAL_ONLY"})
    def test_platform_default_is_configurable(self):
        self.assertEqual(gateway.policy_for(self.store).mode, gateway.LOCAL_ONLY)

    @override_settings(UPMARKET_AI={"AI_DEFAULT_POLICY": "NONSENSE"})
    def test_unknown_platform_default_falls_back_rather_than_crashing(self):
        """A typo in .env must not take the product down."""
        self.assertEqual(gateway.policy_for(self.store).mode, gateway.HYBRID)

    # ---- Local Only ------------------------------------------------------

    def test_local_only_refuses_an_external_provider(self):
        _external_row()
        StoreAIPolicy.objects.create(store=self.store, mode=StoreAIPolicy.Mode.LOCAL_ONLY)
        with self.assertRaises(gateway.PolicyBlocked) as caught:
            gateway.resolve(providers.TEXT, self.store)
        self.assertIn("فقط لوکال", str(caught.exception))

    def test_local_only_still_uses_a_local_provider(self):
        _local_row()
        _external_row()
        StoreAIPolicy.objects.create(store=self.store, mode=StoreAIPolicy.Mode.LOCAL_ONLY)
        chosen = gateway.resolve(providers.TEXT, self.store)
        self.assertTrue(chosen.is_local)

    def test_local_only_does_not_silently_fall_through_to_the_api(self):
        """The defect this whole layer exists for.

        A local provider ranked first and an API behind it: under HYBRID the API
        is a legitimate fallback, under Local Only it must not be reachable at
        all — not even when the local one is the only thing that fails later.
        """
        _external_row(priority=1)
        _local_row(priority=2)
        StoreAIPolicy.objects.create(store=self.store, mode=StoreAIPolicy.Mode.LOCAL_ONLY)
        self.assertTrue(gateway.resolve(providers.TEXT, self.store).is_local)

    def test_hybrid_store_is_unaffected(self):
        """Existing installs keep behaving exactly as before the policy layer."""
        _external_row(priority=1)
        self.assertFalse(gateway.resolve(providers.TEXT, self.store).is_local)

    # ---- Approved External -----------------------------------------------

    def test_approved_external_rejects_an_unvetted_provider(self):
        _external_row(is_approved=False)
        StoreAIPolicy.objects.create(
            store=self.store, mode=StoreAIPolicy.Mode.APPROVED_EXTERNAL
        )
        with self.assertRaises(gateway.PolicyBlocked) as caught:
            gateway.resolve(providers.TEXT, self.store)
        self.assertIn("تأیید نشده", str(caught.exception))

    def test_approved_external_accepts_a_vetted_provider(self):
        _external_row(
            is_approved=True,
            data_location=ModelProvider.DataLocation.EU,
            data_retention="۳۰ روز",
        )
        StoreAIPolicy.objects.create(
            store=self.store, mode=StoreAIPolicy.Mode.APPROVED_EXTERNAL
        )
        self.assertEqual(gateway.resolve(providers.TEXT, self.store).name, "API بیرونی")

    def test_approval_requires_stating_where_the_data_goes(self):
        """"Approved" has to mean someone looked. A row with no stated location
        or retention is a rubber stamp, so the model refuses to save it."""
        from django.core.exceptions import ValidationError

        row = _external_row(is_approved=True)
        with self.assertRaises(ValidationError):
            row.full_clean()

    # ---- customer data ---------------------------------------------------

    def test_customer_messages_do_not_go_external_by_default(self):
        """Product copy leaving is the shop's decision. A customer's private
        message leaving is a decision made about someone who is not present."""
        _external_row(priority=1)
        with self.assertRaises(gateway.PolicyBlocked) as caught:
            gateway.resolve(providers.TEXT, self.store, gateway.CUSTOMER)
        self.assertIn("پیام", str(caught.exception))

    def test_product_data_may_go_external_while_customer_data_may_not(self):
        _external_row(priority=1)
        self.assertFalse(gateway.resolve(providers.TEXT, self.store, gateway.PRODUCT).is_local)
        with self.assertRaises(gateway.PolicyBlocked):
            gateway.resolve(providers.TEXT, self.store, gateway.CUSTOMER)

    def test_owner_can_opt_in_to_sending_customer_messages(self):
        _external_row(
            priority=1,
            allowed_data=[
                ModelProvider.DataClass.PRODUCT,
                ModelProvider.DataClass.BRAND,
                ModelProvider.DataClass.CUSTOMER,
            ],
        )
        StoreAIPolicy.objects.create(
            store=self.store, allow_customer_data_external=True
        )
        chosen = gateway.resolve(providers.TEXT, self.store, gateway.CUSTOMER)
        self.assertFalse(chosen.is_local)

    def test_owner_opt_in_does_not_override_the_provider_allow_list(self):
        """Two independent gates. The owner consenting does not grant a
        provider access to data the operator never permitted it to see."""
        _external_row(priority=1, allowed_data=[ModelProvider.DataClass.PRODUCT])
        StoreAIPolicy.objects.create(
            store=self.store, allow_customer_data_external=True
        )
        with self.assertRaises(gateway.PolicyBlocked):
            gateway.resolve(providers.TEXT, self.store, gateway.CUSTOMER)

    def test_local_provider_may_see_customer_messages(self):
        """Nothing leaves the building, so there is nothing to consent to."""
        _local_row()
        self.assertTrue(
            gateway.resolve(providers.TEXT, self.store, gateway.CUSTOMER).is_local
        )

    # ---- defaults on a fresh provider row --------------------------------

    def test_blank_allow_list_is_narrow_for_external_and_wide_for_local(self):
        external = _external_row()
        local = _local_row()
        self.assertNotIn(ModelProvider.DataClass.CUSTOMER, external.effective_allowed_data)
        self.assertIn(ModelProvider.DataClass.CUSTOMER, local.effective_allowed_data)

    def test_env_configured_api_gets_the_same_narrow_default(self):
        """An API named only in .env was never reviewed by anyone either."""
        resolved = providers.Resolved(
            capability=providers.TEXT, kind="OPENAI", name="env api",
            base_url="https://x/v1", api_key="k", model_name="m", timeout_s=10,
            is_local=False,
        )
        self.assertEqual(
            gateway._allowed_data_for(resolved), [gateway.PRODUCT, gateway.BRAND]
        )

    # ---- explain ---------------------------------------------------------

    def test_explain_names_the_reason_instead_of_just_failing(self):
        _external_row()
        StoreAIPolicy.objects.create(store=self.store, mode=StoreAIPolicy.Mode.LOCAL_ONLY)
        rows = {r["capability"]: r for r in gateway.explain(self.store)}
        self.assertTrue(rows["TEXT"]["blocked"])
        self.assertIn("فقط لوکال", rows["TEXT"]["reason"])

    def test_explain_reports_where_an_external_provider_processes_data(self):
        _external_row(
            is_approved=True,
            data_location=ModelProvider.DataLocation.US,
            data_retention="نگه‌داری نمی‌شود",
        )
        rows = {r["capability"]: r for r in gateway.explain(self.store)}
        self.assertEqual(rows["TEXT"]["data_location"], "US")
        self.assertFalse(rows["TEXT"]["local"])


class NarrationPolicyTests(TestCase):
    """edge-tts sends the narration text to Microsoft. The trust card used to
    say processing happens on our own servers; both cannot be true.

    Since the offline Piper voice was added, «فقط لوکال» no longer means
    silence — it means Piper, if its model is on this machine. What must
    never happen either way is a local-only shop's text leaving the building,
    so that is what these tests pin down instead of a fixed answer.
    """

    def setUp(self):
        self.user = User.objects.create_user("narrator", password="x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه صدا")

    def test_a_local_only_store_never_narrates_through_an_external_service(self):
        from services.audio.tts import TTSError, get_tts_provider

        StoreAIPolicy.objects.create(store=self.store, mode=StoreAIPolicy.Mode.LOCAL_ONLY)
        try:
            provider = get_tts_provider(language="fa", store=self.store)
        except TTSError as exc:
            # No local voice installed here: the refusal has to say why, so
            # the owner can install one instead of guessing.
            self.assertIn("فقط لوکال", str(exc))
            return
        self.assertTrue(
            provider.describe()["local"],
            "a local-only store was handed an external narrator",
        )

    def test_hybrid_store_still_gets_narration(self):
        from services.audio.tts import get_tts_provider

        self.assertEqual(get_tts_provider(language="fa", store=self.store).name, "edge")

    def test_every_shipped_engine_declares_itself_external(self):
        """If a local Persian voice is ever added, this is the test that has to
        be updated deliberately — not a comment someone forgets."""
        from services.audio.tts import EdgeTTSProvider, GTTSProvider

        self.assertFalse(EdgeTTSProvider.is_local)
        self.assertFalse(GTTSProvider.is_local)


class PolicyAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("api-owner", password="x")
        self.other = User.objects.create_user("stranger", password="x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه API")
        self.url = f"/api/v1/stores/{self.store.id}/ai-policy/"

    def test_owner_sees_the_effective_policy(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], gateway.HYBRID)
        self.assertTrue(response.json()["is_platform_default"])

    def test_owner_can_switch_to_local_only(self):
        self.client.force_login(self.user)
        response = self.client.patch(
            self.url, {"mode": "LOCAL_ONLY"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "LOCAL_ONLY")
        self.assertFalse(response.json()["is_platform_default"])

    def test_changing_the_policy_records_who_and_when(self):
        self.client.force_login(self.user)
        self.client.patch(self.url, {"mode": "LOCAL_ONLY"}, content_type="application/json")
        row = StoreAIPolicy.objects.get(store=self.store)
        self.assertEqual(row.acknowledged_by, self.user)
        self.assertIsNotNone(row.acknowledged_at)

    def test_the_response_says_who_will_narrate_under_local_only(self):
        """The owner finds out before the first silent video, not after.

        With the offline Piper voice installed the answer is "Piper, locally";
        without it, narration is off and the reason says so. Either answer is
        fine — an answer that does not match this machine is not.
        """
        self.client.force_login(self.user)
        narration = self.client.patch(
            self.url, {"mode": "LOCAL_ONLY"}, content_type="application/json"
        ).json()["narration"]

        if narration["available"]:
            self.assertTrue(narration["local"], "local-only, narrated externally")
            self.assertTrue(narration["engine"])
        else:
            self.assertIn("لوکال", narration["reason"])

    def test_invalid_mode_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.patch(
            self.url, {"mode": "WHATEVER"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_another_users_store_is_not_visible(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_anonymous_is_rejected(self):
        self.assertIn(self.client.get(self.url).status_code, (401, 403))
