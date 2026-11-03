# -*- coding: utf-8 -*-
"""«بازسازیِ یک تکه»: ترجمهٔ پرامپتِ فارسی به انگلیسی با مدلِ متنیِ سامانه (apps.regen.services.model_prompt).

باگِ ۱۴۰۵/۰۸/۱۲: `generate_json` همیشه (dict, متنِ خام) برمی‌گرداند ولی کد آن را dict فرض می‌کرد ⇒ ترجمه هیچ‌وقت کار نمی‌کرد و
متنِ فارسی خام به مدلِ ویدیو می‌رفت. هیچ‌چیز این‌جا به مدلِ واقعی وصل نمی‌شود.
"""
from unittest import mock

from django.test import TestCase

from apps.regen import services

ENGLISH = "A young woman walks slowly along a rainy street at night, same lighting and camera as the surrounding shot."


class ModelPromptTests(TestCase):
    def provider(self, result=None, exc=None):
        m = mock.MagicMock()
        if exc is not None:
            m.generate_json.side_effect = exc
        else:
            m.generate_json.return_value = result
        return m

    def run_prompt(self, provider, text="زنی آرام در خیابانِ بارانی راه می‌رود"):
        with mock.patch("services.ai.gateway.text_provider", return_value=provider):
            return services.model_prompt(None, text)

    def test_the_tuple_generate_json_returns_is_unpacked(self):
        """the real return value: (parsed_dict, raw_text) — this is the bug that made the translation never work"""
        provider = self.provider(({"prompt": ENGLISH}, '{"prompt": "..."}'))
        out, source = self.run_prompt(provider)
        self.assertEqual(source, "ai")
        self.assertEqual(out, ENGLISH)
        args, kwargs = provider.generate_json.call_args
        self.assertIn("زنی آرام", args[1])
        self.assertEqual(kwargs["system"], services.PROMPT_SYSTEM)

    def test_a_plain_dict_still_works(self):
        out, source = self.run_prompt(self.provider({"prompt": ENGLISH}))
        self.assertEqual((out, source), (ENGLISH, "ai"))

    def test_an_answer_that_is_still_persian_or_too_short_is_not_used(self):
        for bad in ({"prompt": "یک زن در خیابان راه می‌رود، آرام و بی‌صدا در باران"}, {"prompt": "A cat."}, {"prompt": ""}, {}):
            out, source = self.run_prompt(self.provider((bad, "{}")))
            self.assertEqual(source, "fallback", bad)
            self.assertIn("زنی آرام", out)                     # the user's own text goes on (umT5 is multilingual)

    def test_a_dead_model_falls_back_to_the_users_text(self):
        out, source = self.run_prompt(self.provider(exc=RuntimeError("هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند")))
        self.assertEqual(source, "fallback")
        self.assertTrue(out.startswith("زنی آرام"))

    def test_an_english_request_and_an_empty_one_never_reach_the_model(self):
        provider = self.provider(({"prompt": ENGLISH}, "{}"))
        out, source = self.run_prompt(provider, "a woman walks in the rain")
        self.assertEqual(source, "user")
        out2, source2 = self.run_prompt(provider, "   ")
        self.assertEqual(source2, "default")
        provider.generate_json.assert_not_called()
