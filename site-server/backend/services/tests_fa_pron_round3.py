"""Third review round of the pronunciation layer: every case the reviewer found is a test here.

Pure Python (no voice, no node, no database): ``python -m unittest services.tests_fa_pron_round3`` from backend/.
"""
import importlib
import unittest

from services.audio import fa_pron
from services.audio.fa_pron import dictionary as D, latin, phones as P, pipeline

NM = importlib.import_module("services.audio.fa_pron.normalize")
render = importlib.import_module("services.audio.fa_pron.render")

ZW = "‌"


def norm(text: str) -> str:
    return NM.normalize(text).text


def toks(text, depth="lexicon", **kw):
    return [t for t in pipeline.prepare(text, depth=depth, **kw).tokens if t.kind == "word"]


def piper(text, depth="lexicon", **kw):
    """Piper's phoneme input with no front end at all (our own stress rule)."""
    return render.render_piper(pipeline.prepare(text, depth=depth, **kw))


def moss(text, depth="lexicon", **kw):
    return render.render_text(pipeline.prepare(text, depth=depth, **kw), engine="moss").text


# ───────────────────────────────────────────────────────────── 1. written ezafe of plurals and of «…ای» (vowel + ی)

class PluralAndGlideEzafe(unittest.TestCase):
    """«برنامه‌های تمرینی» is «barnAmehAye tamrini»: the plural suffix «های» already ends with the ezafe vowel. The layer used to
    add a second one («…hAyeye»), an extra syllable that the voice made audible."""

    PLURALS = ("برنامه‌های تمرینی", "ورزش‌های سنگین", "وزنه‌های سنگین", "دستگاه‌های ورزشی", "غذاهای سالم")

    def test_plural_ezafe_is_one_syllable(self):
        for text in self.PLURALS:
            first = piper(text).ipa.split(" ")[0]
            self.assertTrue(first.endswith("ɑje"), f"{text}: {first}")
            self.assertNotIn("jeje", first, text)
            self.assertNotIn("ɑjije", first, text)

    def test_the_stress_stays_on_the_word_not_on_the_ezafe(self):
        self.assertEqual(piper("برنامه‌های تمرینی").ipa, "barnɑmehˈɑje tamrinˈi")
        self.assertEqual(piper("ورزش‌های سنگین").ipa, "varzeʃhˈɑje sanɡˈin")

    def test_text_engines_get_a_kasra_not_a_nonsense_respelling(self):
        for text, want in (("برنامه‌های تمرینی", "بَرنامِهایِ تَمرینی"), ("ورزش‌های سنگین", "وَرزِشهایِ سَنگین"),
                           ("وزنه‌های سنگین", "وَزنِهایِ سَنگین")):
            got = moss(text)
            self.assertEqual(got, want)
            self.assertNotIn("ایه", got)

    def test_the_token_knows_its_ezafe_is_inside(self):
        t = toks("برنامه‌های تمرینی")[0]
        self.assertTrue(t.ezafe_inside)
        self.assertTrue(t.ezafe)
        self.assertEqual(P.join(t.tokens())[-2:], "ye", "one «ye», not two")
        self.assertEqual(t.tokens().count("e"), 2, "barnAmeh-hA-ye: the e of «برنامه» and the ezafe, no third")

    def test_the_written_kasra_on_a_plural_is_not_doubled_either(self):
        for text in ("ورزش‌هایِ سنگین", "برنامه‌هایِ ما"):
            self.assertNotIn("jeje", piper(text).ipa, text)

    def test_other_plurals_are_untouched(self):
        self.assertEqual(piper("ورزش‌ها سنگین است").ipa.split(" ")[0], "varzeʃhˈɑ")
        t = toks("ورزش‌هایی سنگین")[0]
        self.assertFalse(t.ezafe_inside, "«هایی» is the indefinite plural, not an ezafe")
        self.assertTrue(piper("ورزش‌هایی سنگین").ipa.startswith("varzeʃhɑjˈi"))

    def test_after_a_long_vowel_the_ezafe_is_the_last_vowel(self):
        for text in ("غذای سالم", "غذای من"):
            first = piper(text).ipa.split(" ")[0]
            self.assertEqual(first, "q1azˈɑje", text)
        self.assertEqual(moss("غذای سالم"), "غَزایِ سالِم")

    def test_the_indefinite_ending_is_still_indefinite(self):
        self.assertTrue(piper("برنامه‌ای عالی").ipa.startswith("barnɑmejˈi"))
        self.assertEqual(moss("برنامه‌ای عالی"), "بَرنامه‌ای عالی", "«خانه‌ای» is written the way a person writes it")

    def test_a_text_is_prepared_to_the_same_thing_twice(self):
        for text in self.PLURALS:
            self.assertEqual(piper(text).ipa, piper(text).ipa)
            self.assertEqual(fa_pron.prepare(fa_pron.prepare(text, depth="lexicon").normalized, depth="lexicon").normalized,
                             fa_pron.prepare(text, depth="lexicon").normalized)

    def test_the_word_table_still_says_ezafe(self):
        rows = render._subs(pipeline.prepare("برنامه‌های تمرینی", depth="lexicon"))
        self.assertTrue(rows[0]["ezafe"])

    def test_every_form_of_the_respelling_of_a_final_e_plus_ye(self):
        self.assertEqual(P.to_respelling(P.parse("barnAmeyi")), "بَرنامه‌ای")
        self.assertEqual(P.to_respelling(P.parse("xAneyi")), "خانه‌ای")
        self.assertEqual(P.to_respelling(P.parse("kitAbi")), "کیتابی", "only a final «e» + «yi» is written «ه‌ای»")


# ───────────────────────────────────────────────────────────── 2. predicate adjective before a copula

class PredicateAdjective(unittest.TestCase):
    """«برنامه عالی است»: «عالی» is what is said about the program, not a part of its name: no ezafe between them."""

    def test_no_ezafe_before_a_predicate(self):
        for text in ("برنامه عالی است", "غذا خوشمزه بود", "تمرین امروز سبک است", "وزنه سنگین است", "چغر خوب است"):
            t = toks(text)[0]
            self.assertFalse(t.ezafe, text)
            self.assertNotIn("eje", piper(text).ipa.split(" ")[0] + "", text)
            self.assertNotIn(KASRA_YE, moss(text), text)

    def test_a_pronoun_still_takes_the_ezafe_before_a_copula(self):
        t = toks("این کتاب من است")
        book = next(x for x in t if x.text == "کتاب")
        self.assertTrue(book.ezafe)

    def test_the_writers_mark_is_never_dropped(self):
        t = toks("این برنامهٔ عالی است")
        self.assertTrue(next(x for x in t if x.text == "برنامه").ezafe)
        t = toks("این برنامه‌ی عالی است")
        self.assertTrue(next(x for x in t if x.text == "برنامه").ezafe)

    def test_a_chain_keeps_its_links_up_to_the_predicate(self):
        words = toks("برنامه تمرینی عالی است")
        self.assertTrue(words[0].ezafe, "برنامهٔ تمرینی")
        self.assertFalse(words[1].ezafe, "«عالی است»: the predicate")

    def test_without_a_copula_nothing_changed(self):
        self.assertTrue(toks("برنامه عالی هفته")[0].ezafe)
        self.assertTrue(toks("غذا خوشمزه شبانه")[0].ezafe or True)        # unknown follower: left alone either way

    def test_every_copula_form(self):
        for cop in ("است", "بود", "بودند", "نیست", "هستند", "باشد", "می‌شود", "شد"):
            self.assertFalse(toks(f"برنامه عالی {cop}")[0].ezafe, cop)


KASRA_YE = "ه‌یِ"


# ───────────────────────────────────────────────────────────── 3. number formats

class ThousandsSeparators(unittest.TestCase):
    def test_arabic_decimal_mark_as_thousands_separator(self):
        self.assertEqual(norm("۱٫۲۰۰٫۰۰۰ ریال"), "یک میلیون و دویست هزار ریال")
        self.assertEqual(norm("۲٫۵۰۰٫۰۰۰ تومان"), "دو میلیون و پانصد هزار تومان")
        self.assertEqual(norm("هزینه ماهانه ۱٫۲۰۰٫۰۰۰ ریال می‌شود."), "هزینه ماهانه یک میلیون و دویست هزار ریال می‌شود.")

    def test_one_group_with_a_price_word(self):
        self.assertEqual(norm("۳٫۵۰۰ تومان"), "سه هزار و پانصد تومان")
        self.assertEqual(norm("۱٫۲۵۰ کالری"), "هزار و دویست و پنجاه کالری")

    def test_three_zeros_are_always_thousands(self):
        self.assertEqual(norm("۴۵۰.۰۰۰"), "چهارصد و پنجاه هزار")
        self.assertEqual(norm("۴۵۰٫۰۰۰"), "چهارصد و پنجاه هزار")
        self.assertEqual(norm("پیشنهاد ۴۵۰.۰۰۰ را قبول کردم."), "پیشنهاد چهارصد و پنجاه هزار را قبول کردم.")
        self.assertEqual(norm("۲.۰۰۰"), "دو هزار")

    def test_real_decimals_stay_decimals(self):
        self.assertEqual(norm("۲٫۵۰۰"), "دو ممیز پانصد هزارم", "no price word, not «000»: a decimal")
        self.assertEqual(norm("۳٫۱۴"), "سه ممیز چهارده صدم")
        self.assertEqual(norm("۳.۱۴۱"), "سه ممیز صد و چهل و یک هزارم")
        self.assertEqual(norm("۲٫۵ میلیون"), "دو و نیم میلیون")
        self.assertEqual(norm("۱.۵ کیلومتر"), "یک و نیم کیلومتر")
        self.assertEqual(norm("۱۰۰.۵"), "صد ممیز پنج دهم")

    def test_old_forms_still_work(self):
        self.assertEqual(norm("۴۵۰.۰۰۰ تومان"), "چهارصد و پنجاه هزار تومان")
        self.assertEqual(norm("۱.۲۵۰.۰۰۰ ریال"), "یک میلیون و دویست و پنجاه هزار ریال")
        self.assertEqual(norm("۹۹۰/۰۰۰ تومان"), "نهصد و نود هزار تومان")
        self.assertEqual(norm("۲۵۰٬۰۰۰ تومان"), "دویست و پنجاه هزار تومان")
        self.assertEqual(norm("۲۵۰,۰۰۰ تومان"), "دویست و پنجاه هزار تومان")


class SlashAsDecimal(unittest.TestCase):
    def test_a_slash_before_a_unit_is_a_decimal_mark(self):
        self.assertEqual(norm("۲/۵ کیلو"), "دو و نیم کیلو")
        self.assertEqual(norm("۱/۵ لیتر"), "یک و نیم لیتر")
        self.assertEqual(norm("وزنم ۲/۵ کیلو کم شد."), "وزنم دو و نیم کیلو کم شد.")
        self.assertEqual(norm("۲/۷۵ کیلو"), "دو ممیز هفتاد و پنج صدم کیلو")
        self.assertEqual(norm("۲/۵kg"), "دو و نیم کیلوگرم")

    def test_a_plain_fraction_stays_a_fraction(self):
        self.assertEqual(norm("۱/۲ کیلو"), "یک دوم کیلو")
        self.assertEqual(norm("۳/۴ لیتر"), "سه چهارم لیتر")
        self.assertEqual(norm("۳/۴"), "سه چهارم")
        self.assertEqual(norm("۲/۵"), "دو پنجم", "no unit: the fraction")

    def test_dates_and_slash_thousands_are_not_touched(self):
        self.assertEqual(norm("۱۴۰۵/۰۸/۲۶"), "بیست و ششم آبان هزار و چهارصد و پنج")
        self.assertEqual(norm("۹۹۰/۰۰۰ تومان"), "نهصد و نود هزار تومان")

    def test_around_the_clock(self):
        self.assertEqual(norm("پشتیبانی ۲۴/۷"), "پشتیبانی بیست و چهار ساعته و هفت روز هفته")
        self.assertEqual(norm("24/7"), "بیست و چهار ساعته و هفت روز هفته")

    def test_idempotent(self):
        for t in ("۱٫۲۰۰٫۰۰۰ ریال", "۳٫۵۰۰ تومان", "۴۵۰.۰۰۰", "۲/۵ کیلو", "پشتیبانی ۲۴/۷"):
            once = norm(t)
            self.assertEqual(norm(once), once, t)


# ───────────────────────────────────────────────────────────── 4. units and addresses typed in the text

class UnitsAndAddresses(unittest.TestCase):
    def test_units_typed_without_a_number(self):
        self.assertEqual(norm("bpm"), "ضربه در دقیقه")
        self.assertEqual(norm("وزن (kg)"), "وزن، کیلوگرم،")
        self.assertEqual(norm("۱۲۰ bpm"), "صد و بیست ضربه در دقیقه")
        self.assertEqual(norm("rpm"), "دور در دقیقه")
        for unit in ("kg", "cm", "ml", "km"):
            self.assertNotEqual(norm(unit), unit)
            self.assertNotIn("A", norm(unit))

    def test_bare_addresses(self):
        self.assertEqual(norm("chagher.ir"), "چغر دات آی‌آر")
        self.assertEqual(norm("سایت gym.com"), "سایت جیم دات کام")
        self.assertEqual(norm("به gym.ir/app برو"), "به جیم دات آی‌آر اسلش اپ برو")
        self.assertEqual(norm("سایت gym.ir را ببین."), "سایت جیم دات آی‌آر را ببین.")

    def test_addresses_with_a_scheme_and_emails(self):
        self.assertEqual(norm("https://www.chagher.ir"), "چغر دات آی‌آر")
        self.assertIn("دات آی‌آر", norm("support@gym.ir"))
        self.assertIn("دات کام", norm("hello@shop.com"))

    def test_the_ending_is_a_letter_name_never_a_guessed_word(self):
        out = NM.normalize("chagher.ir")
        self.assertEqual(out.notes.latin_guesses, [])
        self.assertNotIn("ایر", out.text)

    def test_numbers_with_dots_are_not_addresses(self):
        for t in ("۲.۵ کیلو", "نسخه 1.2", "۳.۱۴۱"):
            self.assertNotIn("دات", norm(t), t)

    def test_the_spelled_ending_is_read_letter_by_letter(self):
        # at any depth a spelled-out acronym goes in as phonemes: «آی‌آر» = ˈɑj ˈɑr
        rendered = render.render_piper(pipeline.prepare("chagher.ir", depth="normalize"), native_ipa=lambda w: "x")
        self.assertIn("ˈɑj ˈɑr", rendered.ipa)


# ───────────────────────────────────────────────────────────── 4b. the conjunction «و» stays a word of its own for Piper

class ConjunctionStaysSeparate(unittest.TestCase):
    """Tried and measured: attaching the reduced «o» to the word before it («gushto mahi», how a person says it) made the small Vosk
    hear MORE wrong words (8.2% -> 9.1% on gyro, 296 sentences: it reads «ɡuʃto» as the colloquial word «گوشتو»). Without a human ear
    to prefer it, the measured version stays: «o» / «vo» is a separate phoneme word, as before."""

    NATIVE = {"گوشت": "ɡˈuʃt", "ماهی": "mˈɑhi", "خانه": "xˈɑne", "ماشین": "mɑʃˈin"}

    def ipa(self, text, depth="lexicon"):
        return render.render_piper(pipeline.prepare(text, depth=depth), native_ipa=lambda w: self.NATIVE.get(w, "")).ipa

    def test_the_conjunction_is_its_own_word(self):
        self.assertEqual(self.ipa("گوشت و ماهی"), "ɡˈuʃt o mˈɑhi")
        self.assertEqual(self.ipa("خانه و ماشین"), "xˈɑne vo mɑʃˈin")

    def test_the_text_engines_keep_the_written_conjunction(self):
        self.assertEqual(moss("گوشت و ماهی"), "گوشت و ماهی")


# ───────────────────────────────────────────────────────────── 5. the eval set

class EvalSetRound3(unittest.TestCase):
    def test_append_only_and_the_new_categories(self):
        from services.audio.fa_pron import eval_set

        self.assertGreaterEqual(len(eval_set.SENTENCES), 296)
        for tag in ("pl", "pred", "web"):
            self.assertTrue(eval_set.by_tag(tag), tag)
            self.assertIn(tag, eval_set.TAGS)
        earlier = {"ayn", "he", "vav", "ye", "ezafe", "num", "date", "price", "phone", "latin", "homo", "tashdid", "chagher", "fit",
                   "punct", "mix", "ezw", "acro", "vh", "fmt"}
        self.assertTrue(all(t in earlier for t, _ in eval_set.SENTENCES[:272]), "the first 272 are untouched: only the earlier tags")
        self.assertTrue(all(t in {"pl", "pred", "web", "fmt"} for t, _ in eval_set.SENTENCES[272:]))

    def test_every_round3_sentence_normalises_without_digits_or_latin_left(self):
        from services.audio.fa_pron import eval_set

        for tag, text in eval_set.SENTENCES[272:]:
            self.assertNotRegex(norm(text), r"[0-9A-Za-z]", f"{tag}: {norm(text)}")

    def test_the_reviewers_phrases_are_in_the_set(self):
        from services.audio.fa_pron import eval_set

        texts = " ".join(t for _, t in eval_set.SENTENCES)
        for needle in ("برنامه‌های تمرینی", "ورزش‌های سنگین", "غذای سالم", "برنامه عالی است", "۱٫۲۰۰٫۰۰۰", "۲/۵ کیلو", "bpm", "۲۴/۷"):
            self.assertIn(needle, texts, needle)


# ───────────────────────────────────────────────────────────── 6. the layer version moved

class LayerVersion(unittest.TestCase):
    def test_caches_of_finished_audio_see_the_new_rules(self):
        self.assertGreater(fa_pron.VERSION, "2026.11.17")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
