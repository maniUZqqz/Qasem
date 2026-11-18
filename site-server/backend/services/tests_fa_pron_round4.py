"""Round 4 of the review: a CONSERVATIVE automatic ezafe, and the normaliser gaps of that round.

Pure Python (no voice, no node, no database): ``python -m unittest services.tests_fa_pron_round4`` from backend/.
"""
import importlib
import unittest
from unittest import mock

from services.audio import fa_pron
from services.audio.fa_pron import dictionary as D, ezafe, ezafe_data as L, ezafe_gold, ezafe_v1, phones as P, pipeline

NM = importlib.import_module("services.audio.fa_pron.normalize")
render = importlib.import_module("services.audio.fa_pron.render")

KASRA = "ِ"


def norm(text: str) -> str:
    return NM.normalize(text).text


def words(text, depth="lexicon", **kw):
    return [t for t in pipeline.prepare(text, depth=depth, **kw).tokens if t.kind == "word"]


def linked(text, **kw):
    """The words of ``text`` that take an automatic ezafe."""
    return [t.text for t in words(text, **kw) if t.ezafe and not t.written_ezafe and not t.ezafe_inside]


def piper(text, depth="lexicon"):
    return render.render_piper(pipeline.prepare(text, depth=depth)).ipa


def edge_text(text, depth="lexicon"):
    return render.render_text(pipeline.prepare(text, depth=depth), engine="edge").text


# ───────────────────────────────────────────────────────────── 1. what the reviewer found: no ezafe where two nouns just stand together

class NoWrongEzafe(unittest.TestCase):
    """«با چغر برنامه بساز» was spoken «چغرِ برنامه»: the brand name, a name, a subject next to its bare object, a list item next to a plural
    noun, an adjective in front of a noun. Raw espeak never links these, so for them the layer made the voice WORSE."""

    def test_the_brand_is_never_linked(self):
        for text in ("با چغر برنامه بساز.", "با چغر غذا بساز.", "چغر برنامه ورزشی و غذایی هر ورزشکار را پیش‌نویس می‌کند.",
                     "چغر برنامه می‌سازد.", "چغر تمرین می‌دهد."):
            self.assertNotIn("چغر", linked(text), text)
            self.assertNotIn("tʃaq1are", piper(text), text)
            self.assertNotIn("چَغَرِ", edge_text(text), text)

    def test_the_reviewers_sentences_are_not_linked_by_mistake(self):
        for text, bad in (("علی کتاب می‌خواند.", ["علی"]), ("مربی برنامه می‌نویسد.", ["مربی"]),
                          ("پلانک و اسکات و شنا حرکت‌های پایه هستند.", ["شنا"]),
                          ("دکتر علی رضایی", ["دکتر", "علی"]), ("رضا کتاب را خرید.", ["رضا"]),
                          ("محمد کتاب را به مریم داد.", ["محمد", "کتاب"]), ("مربی غذا می‌پزد.", ["مربی"])):
            got = linked(text)
            for w in bad:
                self.assertNotIn(w, got, f"{w!r} in {text!r}")

    def test_an_adjective_in_front_of_a_noun_is_not_linked(self):
        got = linked("یک مرد قوی وزنه را بلند کرد.")
        self.assertIn("مرد", got)                       # «مردِ قوی» is right
        self.assertNotIn("قوی", got)                    # «قوی وزنه» is not
        self.assertNotIn("خوب", linked("عادت خوب عمر را عوض می‌کند."))
        self.assertNotIn("خوشمزه", linked("غذای خوشمزه را بخور"))

    def test_a_subject_with_a_predicate_complement_is_not_linked(self):
        for text in ("بچه‌ها سالم رسیدند.", "بچه‌ها خوشحال شدند.", "هوا سرد است.", "غذا آماده شد.", "خانه تمیز کرد."):
            self.assertEqual(linked(text), [], text)

    def test_the_pronoun_object_is_not_a_possessor(self):
        for text in ("مربی شما را راهنمایی می‌کند.", "ما فردا شما را می‌بینیم.", "او من را دید.", "چغر شما را همراهی می‌کند."):
            self.assertEqual(linked(text), [], text)
        self.assertEqual(linked("سلام من علی هستم."), [])

    def test_a_reflexive_is_only_a_possessor_in_front_of_ra(self):
        self.assertIn("کار", linked("کار خود را انجام بده."))
        self.assertEqual(linked("مربی خودش تصمیم نهایی را می‌گیرد."), ["تصمیم"])      # the coach himself: no link to «خودش»

    def test_a_noun_then_a_prepositional_object_is_not_linked(self):
        for text in ("قبل از تمرین بدن را گرم کن.", "بعد از تمرین پروتئین بخور.", "قبل از شروع تمرین بدن را گرم کن."):
            self.assertNotIn("تمرین", linked(text), text)

    def test_names_and_titles_are_never_linked(self):
        for text in ("علی ورزشی است.", "سارا شنا را دوست دارد.", "دکتر مربی است.", "مهندس سالم آمد.", "آقای رضایی سلام."):
            self.assertEqual(linked(text), [], text)

    def test_a_measure_after_a_number_is_not_linked(self):
        for text in ("دو لیتر آب بنوش.", "دویست گرم پروتئین کافی است.", "سه کیلو وزنه بردارید.", "ده دقیقه کشش انجام بده."):
            self.assertEqual(linked(text), [], text)

    def test_no_ezafe_before_a_predicate(self):
        for text in ("برنامه عالی است.", "غذا خوشمزه بود.", "وزنه سنگین است.", "برنامه ورزشی است.", "تمرین امروز سبک است."):
            self.assertNotIn(text.split()[0], linked(text), text)

    def test_where_in_doubt_none(self):
        """Two nouns, an unknown noun and a verb, an adjective that is also an adverb in front of a verb: nothing is added."""
        for text in ("غذا می‌پزد.", "گربه سفید", "مربی سریع جواب داد.", "علی سریع دوید.", "آب خوب بنوش"):
            self.assertEqual(linked(text), [], text)


# ───────────────────────────────────────────────────────────── 2. what stays linked

class ConfidentEzafe(unittest.TestCase):
    def test_noun_and_adjective(self):
        for text, first in (("برنامه ورزشی بساز.", "برنامه"), ("با چغر برنامه تمرینی بساز.", "برنامه"), ("رژیم غذایی سالم است.", "رژیم"),
                            ("وعده غذایی سبک بخور.", "وعده"), ("ورزش منظم سلامت قلب را بهتر می‌کند.", "ورزش"),
                            ("تصمیم نهایی همیشه با مربی است.", "تصمیم"), ("مکمل ورزشی بدون نسخه مصرف نکن.", "مکمل"),
                            ("میوه تازه و سبزی تازه بخور.", "میوه"), ("دوستان عزیز سلام.", "دوستان"),
                            ("کفش ورزشی بخرید.", "کفش"), ("زبان فارسی را دوست دارم.", "زبان")):
            self.assertIn(first, linked(text), text)

    def test_a_chain(self):
        self.assertEqual(linked("رژیم غذایی سالم با مربی شروع می‌شود."), ["رژیم", "غذایی"])
        self.assertEqual(linked("برنامه تمرینی خود را هر هفته به‌روز کنید."), ["برنامه", "تمرینی"])

    def test_noun_and_possessive_pronoun(self):
        for text, first in (("کتاب من روی میز است.", "کتاب"), ("نام شما چیست؟", "نام"), ("خانه من است.", "خانه"), ("پدر من مربی است.", "پدر"),
                            ("همراه ما باشید.", "همراه"), ("به نظر من ورزش مهم است.", "نظر"), ("کنار شما هستیم.", "کنار")):
            self.assertIn(first, linked(text), text)

    def test_a_noun_that_takes_a_genitive(self):
        for text, first in (("کاهش وزن با رژیم ممکن است.", "کاهش"), ("قیمت محصول را ببینید.", "قیمت"), ("کیفیت خواب مهم است.", "کیفیت"),
                            ("شهر تهران بزرگ است.", "شهر"), ("کد تخفیف را وارد کنید.", "کد")):
            self.assertIn(first, linked(text), text)

    def test_a_product_word_and_the_brand(self):
        for text in ("اپ چغر را نصب کنید.", "پنل چغر را باز کنید.", "دستیار چغر شما را راهنمایی می‌کند.", "نسخه جدید چغر آماده است."):
            self.assertIn(text.split()[0], linked(text), text)
        self.assertNotIn("چغر", linked("اپ چغر را نصب کنید."))
        self.assertEqual(linked("این اپ چغر است."), [], "«این اپ چغر است»: the brand is the predicate")

    def test_the_writers_marks_are_always_honoured(self):
        for text in ("با چغرِ عزیز", "برنامهٔ ورزشی", "برنامه‌ی ورزشی", "علیِ مهربان", "کتابِ علی"):
            self.assertTrue(any(t.ezafe for t in words(text)), text)
        self.assertEqual(linked("برنامه‌های تمرینی"), [], "the plural «های» carries its own (spelled) ezafe")
        self.assertTrue(words("برنامه‌های تمرینی")[0].ezafe)

    def test_the_switch_still_turns_the_automatic_one_off(self):
        self.assertEqual(linked("برنامه ورزشی بساز.", ezafe=False), [])

    def test_a_derived_adjective_with_a_half_space(self):
        self.assertIn("برنامه", linked("برنامه حرفه‌ای بساز."))
        self.assertIn("مشاوره", linked("مشاوره تغذیه‌ای بگیرید."))
        self.assertNotIn("برنامه‌ای", linked("برنامه‌ای عالی بساز."), "«برنامه‌ای» is already the indefinite noun")

    def test_the_indefinite_adjective(self):
        self.assertIn("مکمل", linked("مکمل خوبی پیشنهاد کرد."))
        self.assertIn("تجربه", linked("یک تجربه سالمی داشت."))


# ───────────────────────────────────────────────────────────── 3. the curated lists

class Lists(unittest.TestCase):
    def keys(self, name):
        return {D.canon(w).replace("‌", "") for w in getattr(L, name)}

    def test_no_word_is_in_two_adjective_lists(self):
        attr, qual, amb = self.keys("ATTR"), self.keys("QUAL"), self.keys("AMBIG")
        self.assertFalse((attr & qual) - {"حرفهای"}, attr & qual)        # «حرفه‌ای» is a classifying AND a qualitative adjective
        self.assertFalse(attr & amb, attr & amb)
        self.assertFalse(qual & amb, qual & amb)

    def test_a_noun_list_holds_no_adjective_name_or_brand(self):
        adj = self.keys("ATTR") | self.keys("QUAL") | self.keys("AMBIG")
        proper = self.keys("NAMES") | self.keys("BRANDS") | self.keys("TITLES")
        for name in ("HEADS", "PRODUCT_HEADS", "COMMON_NOUNS", "PREP_NOUNS"):
            got = self.keys(name)
            self.assertFalse(got & adj, (name, got & adj))
            self.assertFalse(got & proper, (name, got & proper))

    def test_every_word_is_persian(self):
        import re
        persian = re.compile(r"^[آ-یپچژگکی‌ء]+$")
        for name in ("ATTR", "QUAL", "AMBIG", "HEADS", "PRODUCT_HEADS", "NAMES", "BRANDS", "COMMON_NOUNS", "PERSON", "VERB_FORMS",
                     "RESULT_VERBS", "POSSESSOR", "REFLEXIVE", "PREP_NOUNS", "TITLES"):
            for w in getattr(L, name):
                self.assertRegex(w, persian, (name, w))

    def test_the_old_algorithm_is_kept_only_for_the_measurement(self):
        import pathlib
        root = pathlib.Path(fa_pron.__file__).parent
        for f in root.glob("*.py"):
            if f.name in ("ezafe_v1.py", "ezafe_gold.py"):
                continue
            self.assertNotIn("ezafe_v1", f.read_text(encoding="utf-8"), f.name)


# ───────────────────────────────────────────────────────────── 4. the measurement on hand-checked sentences

class GoldSet(unittest.TestCase):
    """The lead's rule: count WRONG and MISSING automatic ezafes on at least 150 marketing sentences, before and after."""

    @classmethod
    def setUpClass(cls):
        cls.main_after = ezafe_gold.measure()
        cls.main_before = ezafe_gold.measure(ezafe_v1.mark_ezafe)
        cls.held_after = ezafe_gold.measure(text=ezafe_gold.HELDOUT_TEXT)
        cls.held_before = ezafe_gold.measure(ezafe_v1.mark_ezafe, text=ezafe_gold.HELDOUT_TEXT)

    def test_there_are_at_least_150_sentences(self):
        n = len(ezafe_gold.parse_gold())
        self.assertGreaterEqual(n, 150)
        self.assertEqual(self.main_after["sentences"], n)
        self.assertGreaterEqual(n + len(ezafe_gold.parse_gold(ezafe_gold.HELDOUT_TEXT)), 250)

    def test_every_gold_mark_sits_on_a_word_of_its_sentence(self):
        for cat, sentence, marked in ezafe_gold.parse_gold() + ezafe_gold.parse_gold(ezafe_gold.HELDOUT_TEXT):
            keys = [ezafe_gold._norm(w.strip("،.؟!:؛")) for w in sentence.split()]
            for key, n in marked:
                self.assertGreaterEqual(keys.count(key), n, (sentence, key))

    def test_wrong_ezafes_dropped_a_lot(self):
        for before, after in ((self.main_before, self.main_after), (self.held_before, self.held_after)):
            self.assertGreaterEqual(before["wrong"], 10, "the old algorithm really made these mistakes")
            self.assertLessEqual(after["wrong"], 2 if after is self.main_after else 3)
            self.assertLessEqual(after["wrong"] * 5, before["wrong"])
            self.assertGreaterEqual(after["precision"], 0.95)

    def test_the_conservative_rules_still_say_most_of_what_they_say_right(self):
        self.assertGreaterEqual(self.main_after["recall"], 0.65, "it must stay useful: «برنامهٔ ورزشی», «کتابِ من» ...")
        self.assertGreaterEqual(self.held_after["recall"], 0.55)
        self.assertGreaterEqual(self.main_after["correct"], 100)

    def test_the_old_rules_said_more_but_wrongly(self):
        self.assertGreater(self.main_before["wrong"], self.main_after["wrong"])
        self.assertGreater(self.main_before["predicted"] - self.main_before["correct"], self.main_after["predicted"] - self.main_after["correct"])

    def test_the_report_prints_both_sets(self):
        text = ezafe_gold.report()
        self.assertIn("main set before", text)
        self.assertIn("held-out set after", text)

    def test_the_wrong_ones_are_listed_for_the_docs(self):
        self.assertIsInstance(self.main_after["wrong_rows"], list)
        self.assertEqual(len(self.main_before["wrong_rows"]), self.main_before["wrong"])


# ───────────────────────────────────────────────────────────── 5. normaliser gaps

class NormaliserRound4(unittest.TestCase):
    def test_list_bullets_are_pauses(self):
        self.assertEqual(norm("• مورد ۱\n• مورد ۲"), "مورد یک\nمورد دو")
        self.assertNotIn("•", norm("• یک\n• دو"))
        self.assertEqual(norm("الف • ب"), "الف، ب")
        for b in "•‣◦▪●■·":
            self.assertNotIn(b, norm(f"{b} سلام"))

    def test_a_bulleted_list_reaches_piper_as_pauses(self):
        ipa = piper("• مورد ۱\n• مورد ۲")
        self.assertNotIn("•", ipa)
        self.assertNotIn("‹", ipa)

    def test_a_jalali_date_links_the_month_to_the_year(self):
        self.assertEqual(norm("۲۶ آبان ۱۴۰۵"), "بیست و ششم آبان" + KASRA + " هزار و چهارصد و پنج")
        self.assertEqual(norm("۱۴۰۵/۰۸/۲۶"), norm("۲۶ آبان ۱۴۰۵"))
        self.assertEqual(norm("۱۷ نوامبر ۲۰۲۶"), "هفدهم نوامبر" + KASRA + " دو هزار و بیست و شش")
        self.assertEqual(norm("۲۶ آبان"), "بیست و ششم آبان", "no year, no ezafe")

    def test_the_month_ezafe_is_spoken(self):
        self.assertIn("ɑbˈɑne", piper("۲۶ آبان ۱۴۰۵"))
        self.assertIn("آبانِ", edge_text("۲۶ آبان ۱۴۰۵", "normalize"))

    def test_an_equals_sign_is_said(self):
        self.assertEqual(norm("۲+۳=۵"), "دو به علاوه سه مساوی پنج")
        self.assertEqual(norm("۶÷۲=۳"), "شش تقسیم بر دو مساوی سه")
        self.assertEqual(norm("=====\nسلام"), "سلام")
        self.assertNotIn("=", norm("a = b"))

    def test_the_country_code_is_a_number_not_a_leading_zero(self):
        self.assertEqual(norm("+989121234567"), "نود و هشت، نهصد و دوازده، صد و بیست و سه، چهل و پنج، شصت و هفت")
        self.assertEqual(norm("00989121234567"), norm("+989121234567"))
        self.assertTrue(norm("09121234567").startswith("صفر نهصد و دوازده"))
        self.assertFalse(norm("تماس: +98 912 123 4567").endswith("،"))

    def test_no_stray_pause_at_the_end(self):
        for text in ("شماره ۰۹۱۲۱۲۳۴۵۶۷", "سلام،", "سلام، ،", "عدد ۱۲۰۰۰۰۰ ،"):
            self.assertFalse(norm(text).endswith("،"), text)
        self.assertTrue(norm("سلام.").endswith("."))

    def test_the_normaliser_is_still_idempotent_on_the_new_forms(self):
        for text in ("۲۶ آبان ۱۴۰۵", "• الف\n• ب", "۲+۳=۵", "+989121234567", "۱۷ نوامبر ۲۰۲۶ ساعت ۱۸:۰۰"):
            once = norm(text)
            self.assertEqual(norm(once), once, text)


# ───────────────────────────────────────────────────────────── 6. a text with nothing to say

class NothingToSpeak(unittest.TestCase):
    def setUp(self):
        from services.audio import tts
        self.tts = tts

    def test_the_check(self):
        for text in ("...", "؟؟؟", "🙂", "🙂🙂 !!", "", "   ", "<br/>", "• • •", "—"):
            self.assertFalse(self.tts.is_speakable(text), repr(text))
        for text in ("سلام", "۱", "a", "ok.", "۳ جلسه", "؟ سلام"):
            self.assertTrue(self.tts.is_speakable(text), repr(text))

    def test_every_engine_refuses_it_with_one_persian_message(self):
        import tempfile
        from pathlib import Path
        out = Path(tempfile.mkdtemp()) / "x.wav"
        for provider in (self.tts.PiperProvider("fa_IR-gyro-medium"), self.tts.EdgeTTSProvider(voice="fa-IR-DilaraNeural"),
                         self.tts.OpenAITTSProvider.__new__(self.tts.OpenAITTSProvider),
                         self.tts.AzureTTSProvider.__new__(self.tts.AzureTTSProvider)):
            with self.assertRaises(self.tts.NothingToSpeakError) as cm:
                provider.synthesize("...", out)
            self.assertEqual(str(cm.exception), self.tts.NOTHING_TO_SPEAK)
        self.assertIn("متنی برای خواندن نیست", self.tts.NOTHING_TO_SPEAK)

    def test_it_is_a_tts_error_so_the_chain_and_the_callers_still_catch_it(self):
        self.assertTrue(issubclass(self.tts.NothingToSpeakError, self.tts.TTSError))
        chain = self.tts.ChainTTSProvider([self.tts.PiperProvider("fa_IR-gyro-medium")])
        with self.assertRaises(self.tts.NothingToSpeakError):
            chain.synthesize("🙂", "/tmp/never.wav")

    def test_english_text_is_checked_too(self):
        provider = self.tts.PiperProvider("fa_IR-gyro-medium")
        provider.language = "en"
        with self.assertRaises(self.tts.NothingToSpeakError):
            provider.synthesize("!!!", "/tmp/never.wav")

    def test_piper_that_makes_no_audio_says_so_in_persian_and_not_the_wave_error(self):
        import tempfile
        from pathlib import Path
        provider = self.tts.PiperProvider("fa_IR-gyro-medium")
        out = Path(tempfile.mkdtemp()) / "x.wav"
        with mock.patch.object(provider, "_load", return_value=object()), mock.patch.object(provider, "_config", return_value=None), \
                mock.patch.object(provider, "_chunks", return_value=iter(())):
            with self.assertRaises(self.tts.TTSError) as cm:
                provider.synthesize("سلام", out)
        msg = str(cm.exception)
        self.assertNotIn("channels", msg)
        self.assertIn("Piper", msg)
        self.assertIn("متنی", msg)
        self.assertFalse(out.with_suffix(".wav").exists(), "no half-written file is left")

    def test_a_normal_text_is_untouched_by_the_guard(self):
        provider = self.tts.PiperProvider("fa_IR-gyro-medium")
        calls = []

        class Chunk:
            sample_rate, sample_width, sample_channels, audio_int16_bytes = 16000, 2, 1, b"\0\0" * 1600

        import tempfile
        from pathlib import Path
        out = Path(tempfile.mkdtemp()) / "x.wav"
        with mock.patch.object(provider, "_load", return_value=object()), mock.patch.object(provider, "_config", return_value=None), \
                mock.patch.object(provider, "_chunks", side_effect=lambda v, c, t: calls.append(t) or iter([Chunk()])):
            path = provider.synthesize("سلام", out)
        self.assertEqual(calls, ["سلام"])
        self.assertTrue(Path(path).exists())


if __name__ == "__main__":
    unittest.main()
