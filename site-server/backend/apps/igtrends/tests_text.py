"""Persian caption handling: normalization, hashtags, topic terms, the hook."""
from django.test import SimpleTestCase

from . import textproc as T


class NormalizeTests(SimpleTestCase):
    def test_arabic_letters_digits_and_marks_become_persian(self):
        self.assertEqual(T.normalize("كتاب يك ۱۲۳ ٤٥"), "کتاب یک 123 45")
        self.assertEqual(T.normalize("تَمرین"), "تمرین")

    def test_links_are_removed_and_spaces_collapsed(self):
        self.assertEqual(T.normalize("ببین   https://example.com/x?a=1  اینو"), "ببین اینو")

    def test_hashtags_in_order_without_repeats_and_generic_kept_for_display(self):
        tags = T.hashtags("سلام #تمرین_در_خانه و #تمرین_در_خانه و #Fitness #۱۲۳ #ریلز")
        self.assertEqual(tags, ["تمرین_در_خانه", "fitness", "ریلز"])

    def test_tag_phrase(self):
        self.assertEqual(T.tag_phrase("تمرین_در_خانه"), "تمرین در خانه")

    def test_strip_caption_keeps_only_written_words(self):
        self.assertEqual(T.strip_caption("سلام @user_1 ببین https://x.ir #تمرین 💪🔥 خوبه"), "سلام ببین خوبه")


class TermsTests(SimpleTestCase):
    def test_words_drop_stop_words_short_bits_digits_and_plural_ha(self):
        self.assertEqual(T.words("من و تو در باشگاه تمرین‌ها را 3 بار انجام می‌دهیم"), ["باشگاه", "تمرین", "بار", "انجام", "دهیم"])

    def test_terms_include_hashtags_words_and_pairs(self):
        terms = T.terms("تمرین سینه در خانه #تمرین_در_خانه #ریلز")
        self.assertIn("#تمرین_در_خانه", terms)
        self.assertNotIn("#ریلز", terms, "a generic tag says nothing about the topic")
        self.assertIn("تمرین", terms)
        self.assertIn("تمرین سینه", terms)
        self.assertIn("خانه", terms)

    def test_a_hashtags_own_words_count_too(self):
        terms = T.terms("بدون متن", ["حرکات_کششی"])
        self.assertIn("#حرکات_کششی", terms)
        self.assertIn("حرکات", terms)
        self.assertIn("کششی", terms)

    def test_display_term(self):
        self.assertEqual(T.display_term("#تمرین_در_خانه"), "تمرین در خانه")
        self.assertEqual(T.display_term("تمرین سینه"), "تمرین سینه")


class HookTests(SimpleTestCase):
    def test_first_sentence_is_the_hook(self):
        h = T.extract_hook("تمرین در خانه بدون وسیله؛ سه حرکت برای شکم. بقیهٔ متن #تمرین")
        self.assertEqual(h["text"], "تمرین در خانه بدون وسیله؛ سه حرکت برای شکم")

    def test_hashtag_and_emoji_lines_are_skipped(self):
        h = T.extract_hook("🔥🔥\n#تمرین #ورزش\nچرا بدنت تغییر نمی‌کند؟\nادامه")
        self.assertEqual(h["text"], "چرا بدنت تغییر نمی‌کند")
        self.assertEqual(h["type"], "question")

    def test_a_greeting_alone_is_not_a_hook(self):
        h = T.extract_hook("سلام.\nامروز می‌خواهم دربارهٔ خواب صحبت کنم")
        self.assertIn("سلام", h["text"])
        self.assertIn("خواب", h["text"])

    def test_long_hook_is_cut_on_a_word(self):
        h = T.extract_hook("کلمه " * 60, limit=50)
        self.assertLessEqual(len(h["text"]), 52)
        self.assertTrue(h["text"].endswith("…"))

    def test_empty_caption(self):
        self.assertEqual(T.extract_hook("#فقط_هشتگ"), {"text": "", "type": "statement"})
        self.assertEqual(T.extract_hook(None), {"text": "", "type": "statement"})

    def test_hook_types(self):
        cases = {
            "۵ اشتباه رایج در رژیم": "number",
            "3 tips for bigger arms": "number",
            "هیچ‌وقت این حرکت را نزن": "contrarian",
            "من سه سال پیش شروع کردم": "story",
            "همین الان ذخیره کن": "cta",
            "راز عضله‌سازی سریع": "claim",
            "امروز روز پا بود": "statement",
            "آیا پروتئین زیاد ضرر دارد؟": "question",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(T.hook_type(text), want)
