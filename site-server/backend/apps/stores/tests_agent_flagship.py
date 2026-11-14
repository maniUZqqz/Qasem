"""The sales agent must be able to answer «جای مربی رو می‌گیره؟».

Chagher's owner banned the CLAIMS «جایگزین مربی» and «تضمین». The brand's own
answers (campaign templates, comment 3 and DM 1) say «چغر جایگزینِ مربی نیست»
and «ما نتیجه را تضمین نمی‌کنیم» - sentences that contain the banned words in
order to deny them. A guard that cannot tell the two used to reject the
flagship answer and hand the chat to a human.
"""
from django.test import TestCase

from apps.stores import agent_settings

# the real never_say list of the store (docs/chagher/brand-facts-fa.md, §6)
CHAGHER_NEVER_SAY = [
    "۹۸٪ رضایت", "۹۸ درصد", "۵۰۰ برنامه", "امنیت ۱۰۰", "پشتیبانی ۲۴",
    "جایگزین مربی", "تضمین", "درمان", "بدون خطا", "بدون اشتباه",
]

APPROVED_ANSWERS = [
    # comment template 3
    "نه 🙂 چغر جایگزینِ مربی نیست؛ پیش‌نویس می‌دهد و بازبینی و تصمیمِ نهایی با خودِ مربی است.",
    # DM template 1 (the last sentence)
    "چغر دستیارِ هوش مصنوعیِ مربی‌هاست و جایگزینِ مربی نیست؛ بازبینی با خودِ توست.",
    "ما نتیجه را تضمین نمی‌کنیم؛ چغر پیش‌نویسِ برنامه می‌دهد و تصمیمِ نهایی با مربی است.",
    "چغر خدماتِ پزشکی و درمانی نمی‌دهد؛ برای این موضوع با پزشک مشورت کن.",
    "هوش مصنوعی ممکن است اشتباه کند؛ برنامه بدون خطا نیست و همیشه بازبینی لازم دارد.",
]

FORBIDDEN_CLAIMS = [
    "چغر جایگزینِ مربی است",
    "با چغر دیگر مربی لازم نیست؛ چغر جایگزین مربی می‌شود.",
    "نتیجه را تضمین می‌کنیم",
    "۹۸٪ رضایتِ مربیان را داریم",
    "برنامه‌ها بدون خطا ساخته می‌شوند",
    "ما درمان می‌کنیم",
]


class FlagshipAnswerTests(TestCase):
    def test_the_approved_answers_are_not_violations(self):
        for reply in APPROVED_ANSWERS:
            self.assertEqual(agent_settings.violations(reply, CHAGHER_NEVER_SAY), [], reply)

    def test_the_banned_claims_are_still_violations(self):
        for reply in FORBIDDEN_CLAIMS:
            self.assertNotEqual(agent_settings.violations(reply, CHAGHER_NEVER_SAY), [], reply)

    def test_the_prompt_tells_the_model_that_denying_a_banned_claim_is_fine(self):
        from services.ai.prompts import sales_agent

        class _Store:
            name = "چغر"
            business_type = description = ""

        class _Profile:
            tone = brand_voice = shipping_policy = return_policy = ""
            refund_policy = payment_info = business_rules = ""

        text = sales_agent.build_sales_prompt(_Store(), _Profile(), [], "", "سلام", [], rules={"never_say": ["تضمین"]})
        self.assertIn("Denying one in your own words is allowed", text)
