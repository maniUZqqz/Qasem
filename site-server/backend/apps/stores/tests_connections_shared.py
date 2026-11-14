"""The connections page must not claim a shared token that does not exist.

Live, before this: `GET /stores/34/connections/` said `telegram_shared: true`
(«store has no token of its own», never checking that a shared bot exists) and
the channel list printed «تنظیم نشده: NOVINHUB_TOKEN / TELEGRAM_BOT_TOKEN» —
while the page's text said «توکن مشترک … کار می‌کند» and the checklist said the
step was open. Page, list and checklist disagreed, and the list showed raw
environment-variable names to a shop owner.

Both states are pinned: no shared credentials (the honest «وارد کنید») and
shared credentials present (the old, true sentence).
"""
import re

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from services.publishing import channels

from .models import Store, StoreProfile
from .onboarding import _has_publishing

NO_SHARED_AI = {
    "TELEGRAM_BOT_TOKEN": "", "WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_ID": "",
    "META_APP_SECRET": "", "META_VERIFY_TOKEN": "", "SMS_API_KEY": "",
    "NOVINHUB_TOKEN": "", "N8N_WEBHOOK_URL": "",
}
NO_SHARED_PUB = {"NOVINHUB_TOKEN": "", "N8N_WEBHOOK_URL": ""}
#: A settings key looks like `SOME_THING`; a person never has to read one.
ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


class _Base(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("shared-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.url = f"/api/v1/stores/{self.store.pk}/connections/"
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def body(self):
        return self.client.get(self.url).json()

    def channel(self, body, key):
        return next(c for c in body["channels"] if c["key"] == key)


@override_settings(UPMARKET_AI=NO_SHARED_AI, UPMARKET_PUBLISHING=NO_SHARED_PUB)
class NothingSharedTests(_Base):
    def test_the_page_does_not_claim_a_shared_token_or_bot(self):
        body = self.body()
        self.assertFalse(body["shared_token_available"])
        self.assertFalse(body["telegram_shared_available"])
        self.assertFalse(body["telegram_shared"])
        self.assertIn("توکن نوین‌هاب را در کادر پایین وارد کنید", body["shared_token_note"])
        self.assertNotIn("کار می‌کند", body["shared_token_note"])
        self.assertIn("@BotFather", body["telegram_note"])

    def test_the_channel_list_names_what_is_missing_in_words(self):
        body = self.body()
        instagram = self.channel(body, "INSTAGRAM")
        self.assertFalse(instagram["configured"])
        self.assertEqual(instagram["reason"], "تنظیم نشده: توکن نوین‌هاب")
        self.assertEqual(instagram["missing"], [{"label": "توکن نوین‌هاب", "input": "novinhub_token"}])
        telegram = self.channel(body, "TELEGRAM")
        self.assertEqual(telegram["reason"], "تنظیم نشده: توکن ربات تلگرام")
        self.assertEqual(telegram["missing"][0]["input"], "telegram_bot_token")

    def test_what_only_the_administrator_can_fix_says_so_and_has_no_input_to_link_to(self):
        body = self.body()
        for key in ("WHATSAPP", "SMS"):
            row = self.channel(body, key)
            self.assertIn("راه‌اندازی‌اش با مدیر سرویس است", row["reason"])
            self.assertTrue(row["missing"])
            self.assertTrue(all(item["input"] == "" for item in row["missing"]))

    def test_no_environment_variable_name_reaches_a_person(self):
        body = self.body()
        texts = [body["shared_token_note"], body["telegram_note"], body["webhook_note"]]
        for row in body["channels"]:
            texts += [row["reason"], row["note"]] + [m["label"] for m in row["missing"]]
            texts += [m["label"] for m in row["receives_missing"]]
        texts += [channels.send("SMS", self.store, to="0912", text="سلام")["reason"],
                  channels.send("INSTAGRAM", self.store, to="1", text="سلام")["reason"]]
        for text in texts:
            self.assertIsNone(ENV_NAME.search(text), text)

    def test_the_checklist_agrees_with_the_page(self):
        self.assertFalse(_has_publishing(self.store))


@override_settings(
    UPMARKET_AI={**NO_SHARED_AI, "TELEGRAM_BOT_TOKEN": "123:shared"},
    UPMARKET_PUBLISHING={**NO_SHARED_PUB, "NOVINHUB_TOKEN": "shared-nh"},
)
class SharedCredentialsTests(_Base):
    def test_the_shared_token_is_reported_and_the_old_sentence_is_true_again(self):
        body = self.body()
        self.assertTrue(body["shared_token_available"])
        self.assertTrue(body["telegram_shared_available"])
        self.assertTrue(body["telegram_shared"])           # no own token -> speaking through it
        self.assertIn("از توکن مشترک NMarketing استفاده می‌شود", body["shared_token_note"])
        self.assertEqual(body["telegram_note"], "")
        # the token itself is still never sent
        self.assertNotIn("shared-nh", str(body))
        self.assertNotIn("123:shared", str(body))

    def test_a_shared_novinhub_token_counts_wherever_settings_keep_it(self):
        """It lives in UPMARKET_PUBLISHING; only UPMARKET_AI used to be read, so
        a perfectly good shared token never made the channel «configured»."""
        body = self.body()
        self.assertTrue(self.channel(body, "INSTAGRAM")["configured"])
        self.assertTrue(self.channel(body, "TELEGRAM")["configured"])
        self.assertTrue(_has_publishing(self.store))

    def test_an_own_token_turns_the_shared_bot_off_for_this_shop(self):
        StoreProfile.objects.update_or_create(
            store=self.store, defaults={"telegram_bot_token": "999:own"},
        )
        body = self.body()
        self.assertTrue(body["has_telegram_token"])
        self.assertFalse(body["telegram_shared"])


@override_settings(UPMARKET_AI=NO_SHARED_AI, UPMARKET_PUBLISHING={**NO_SHARED_PUB, "NOVINHUB_TOKEN": "x"})
class InboundHalfTests(_Base):
    def test_instagram_without_meta_credentials_says_so_in_words(self):
        row = self.channel(self.body(), "INSTAGRAM")
        self.assertTrue(row["configured"])
        self.assertFalse(row["can_receive"])
        self.assertEqual(
            row["reason"],
            "فقط ارسال — برای دریافت لازم است: تأیید اپ در Meta (راه‌اندازی‌اش با مدیر سرویس است)",
        )
        self.assertEqual(row["receives_missing"], [{"label": "تأیید اپ در Meta", "input": ""}])
        self.assertIsNone(ENV_NAME.search(row["reason"]))
