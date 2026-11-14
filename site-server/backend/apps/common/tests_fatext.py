from django.test import SimpleTestCase

from . import fatext


class FaTextTests(SimpleTestCase):
    def test_digits_roundtrip(self):
        self.assertEqual(fatext.en_digits("۹۸٪ و ٣٥"), "98٪ و 35")
        self.assertEqual(fatext.fa_digits("12 از 8"), "۱۲ از ۸")
        self.assertEqual(fatext.fa_digits(None), "")

    def test_normalize_unifies_the_ways_one_claim_can_be_typed(self):
        self.assertEqual(fatext.normalize("۹۸٪ رضایت"), fatext.normalize("98% رضایت"))
        self.assertEqual(fatext.normalize("۹۸ ٪ رضایت"), fatext.normalize("۹۸٪ رضایت"))
        # half-space, kasra, Arabic ي/ك
        self.assertEqual(fatext.normalize("جایگزينِ مربي"), fatext.normalize("جایگزین مربی"))
        self.assertEqual(fatext.normalize("می‌خواهد"), fatext.normalize("میخواهد"))

    def test_contains_phrase(self):
        self.assertTrue(fatext.contains_phrase("رضایتِ ۹۸٪ مربی‌ها", "۹۸٪"))
        self.assertTrue(fatext.contains_phrase("only 98% happy", "۹۸٪"))
        self.assertFalse(fatext.contains_phrase("هدفِ ما جایگزین‌کردنِ مربی نیست", "جایگزین مربی"))
        self.assertFalse(fatext.contains_phrase("anything", ""))
