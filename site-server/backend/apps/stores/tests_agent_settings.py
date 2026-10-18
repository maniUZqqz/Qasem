"""Settings that actually change what the agent says.

ROADMAP §9.15: "این تنظیمات باید **واقعاً روی رفتار مدل اعمال شوند**، نه اینکه
فقط ذخیره شوند." So most of this file is about the second and third layers —
what happens when the model ignores the prompt, and what happens when the shop
owner writes a rule that would break a promise made to their customers.
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.customers.models import Conversation, Customer
from apps.products.models import Product
from services.ai.prompts import sales_agent as prompts

from . import agent_settings
from .agent_settings import SalesAgentSettings
from .models import Membership, Store

GOOD_REPLY = {
    "reply": "سلام! این محصول موجود است و قیمتش ۲۵۰ هزار تومان است.",
    "intent": "PRICE",
    "action": "ANSWER",
    "product_ids": [],
    "order": None,
    "ticket": None,
    "confidence": "HIGH",
    "needs_human": False,
}


class SettingsModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("agent-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه ایجنت")

    def test_defaults_are_the_cautious_ones(self):
        """An agent that offers discounts because nobody configured it is a
        bill the shop never agreed to."""
        row = agent_settings.settings_for(self.store)
        self.assertFalse(row.can_offer_discount)
        self.assertTrue(row.escalate_on_complaint)

    def test_custom_tone_falls_back_when_left_empty(self):
        row = agent_settings.settings_for(self.store)
        row.tone = SalesAgentSettings.Tone.CUSTOM
        row.custom_tone = "   "
        self.assertTrue(row.tone_instruction)

    def test_banned_phrases_are_read_one_per_line(self):
        row = agent_settings.settings_for(self.store)
        row.never_say = "تضمین می‌کنیم\n\n  ارزان‌ترین  \n"
        self.assertEqual(row.banned_phrases, ["تضمین می‌کنیم", "ارزان‌ترین"])

    def test_empty_fields_stay_out_of_the_prompt(self):
        """A prompt full of "(not set)" teaches the model that rules are optional."""
        rules = agent_settings.settings_for(self.store).as_prompt_rules()
        self.assertNotIn("always_mention", rules)
        self.assertNotIn("sale_terms", rules)
        self.assertIn("tone", rules)

    def test_discounts_off_produces_an_explicit_instruction_not_silence(self):
        rules = agent_settings.settings_for(self.store).as_prompt_rules()
        self.assertIn("تخفیف", rules["discounts"])

    def test_discounts_on_without_a_policy_still_refuses_to_invent_one(self):
        row = agent_settings.settings_for(self.store)
        row.can_offer_discount = True
        self.assertIn("ارجاع", row.as_prompt_rules()["discounts"])


class ViolationTests(TestCase):
    def test_a_forbidden_phrase_is_found_regardless_of_case(self):
        self.assertEqual(
            agent_settings.violations("This is the BEST price", ["best price"]),
            ["best price"],
        )

    def test_a_clean_reply_reports_nothing(self):
        self.assertEqual(agent_settings.violations("سلام، بفرمایید", ["تضمین"]), [])

    def test_no_rules_means_nothing_to_break(self):
        self.assertEqual(agent_settings.violations("هر چیزی", []), [])


class PromptTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("prompt-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه پرامپت")

    def _prompt(self, rules=None):
        return prompts.build_sales_prompt(
            self.store, self.store.profile, [], "", "سلام", [], rules=rules,
        )

    def test_rules_reach_the_prompt(self):
        row = agent_settings.settings_for(self.store)
        row.always_say = "ارسال تهران همان‌روز"
        prompt = self._prompt(row.as_prompt_rules())
        self.assertIn("ارسال تهران همان‌روز", prompt)

    def test_the_unbreakable_rules_come_after_the_store_rules(self):
        """The last instruction a model reads carries the most weight, so price,
        stock and payment confirmation must not lose an argument to a settings
        field."""
        row = agent_settings.settings_for(self.store)
        row.always_say = "MARKER_STORE_RULE"
        prompt = self._prompt(row.as_prompt_rules())
        self.assertLess(
            prompt.index("MARKER_STORE_RULE"),
            prompt.index("never confirm a payment"),
        )

    def test_a_prompt_without_rules_is_unchanged(self):
        self.assertNotIn("AGENT RULES", self._prompt(None))


class EnforcementTests(TestCase):
    """The layer that makes a rule a rule."""

    def setUp(self):
        self.owner = User.objects.create_user("enforce-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه اجرا")
        Product.objects.create(store=self.store, name="کفش", price=250_000, stock_quantity=3)
        customer = Customer.objects.create(store=self.store, name="مشتری")
        self.conversation = Conversation.objects.create(
            store=self.store, customer=customer,
        )
        self.settings = agent_settings.settings_for(self.store)

    def _provider(self, *replies):
        provider = MagicMock()
        provider.generate_json.side_effect = [(dict(r), "{}") for r in replies]
        return provider

    @patch("apps.customers.agent.text_provider")
    def test_a_clean_reply_passes_through(self, mock_provider):
        mock_provider.return_value = self._provider(GOOD_REPLY)
        from apps.customers.agent import run_sales_agent

        result = run_sales_agent(self.conversation, "قیمت چند؟")
        self.assertIn("۲۵۰", result["reply"])

    @patch("apps.customers.agent.text_provider")
    def test_a_reply_breaking_a_rule_is_retried_with_the_next_model(self, mock_provider):
        """Putting the phrase in the prompt makes the model usually comply.
        This is what makes it a rule."""
        self.settings.never_say = "تضمین می‌کنیم"
        self.settings.save()

        bad = {**GOOD_REPLY, "reply": "تضمین می‌کنیم که راضی می‌شوید."}
        mock_provider.return_value = self._provider(bad, GOOD_REPLY)
        from apps.customers.agent import run_sales_agent

        result = run_sales_agent(self.conversation, "قیمت چند؟")
        self.assertNotIn("تضمین می‌کنیم", result["reply"])

    @patch("apps.customers.agent.text_provider")
    def test_when_no_model_obeys_a_person_takes_over(self, mock_provider):
        """Saying nothing is better than saying the forbidden thing."""
        self.settings.never_say = "تضمین می‌کنیم"
        self.settings.save()

        bad = {**GOOD_REPLY, "reply": "تضمین می‌کنیم که راضی می‌شوید."}
        mock_provider.return_value = self._provider(bad, bad, bad)
        from apps.customers.agent import SalesRulesUnmet, run_sales_agent

        with self.assertRaises(SalesRulesUnmet):
            run_sales_agent(self.conversation, "قیمت چند؟")

    @patch("apps.customers.agent.text_provider")
    def test_a_store_with_no_rules_is_unaffected_by_the_check(self, mock_provider):
        mock_provider.return_value = self._provider(GOOD_REPLY)
        from apps.customers.agent import run_sales_agent

        self.assertTrue(run_sales_agent(self.conversation, "سلام")["reply"])


class SettingsAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("settings-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه تنظیمات")
        self.url = f"/api/v1/stores/{self.store.id}/agent-settings/"
        self.client.force_login(self.owner)

    def test_reading_creates_the_default_row(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SalesAgentSettings.objects.filter(store=self.store).exists())

    def test_the_response_says_what_cannot_be_overridden(self):
        """An owner about to write "always say the payment went through" should
        see why it will not happen before they type it."""
        body = self.client.get(self.url).json()
        self.assertTrue(any("پرداخت" in line for line in body["unbreakable"]))

    def test_the_owner_sees_the_instruction_their_choice_produces(self):
        body = self.client.get(self.url).json()
        self.assertTrue(body["settings"]["tone_instruction"])

    def test_changing_the_tone_sticks(self):
        response = self.client.patch(
            self.url, {"tone": "FORMAL"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tone"], "FORMAL")

    def test_custom_tone_with_no_text_is_rejected(self):
        response = self.client.patch(
            self.url, {"tone": "CUSTOM", "custom_tone": "  "},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_a_support_member_cannot_change_the_settings(self):
        colleague = User.objects.create_user("settings-support", password="x")
        Membership.objects.create(
            store=self.store, user=colleague, role=Membership.Role.SUPPORT
        )
        self.client.force_login(colleague)
        response = self.client.patch(
            self.url, {"tone": "FORMAL"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_stranger_gets_404(self):
        stranger = User.objects.create_user("settings-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
