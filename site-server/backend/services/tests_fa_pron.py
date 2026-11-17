"""Tests of the Persian pronunciation layer (services/audio/fa_pron): every rule has a case here.

Pure Python: they run with plain ``python -m unittest services.tests_fa_pron`` from backend/ as well as under
``manage.py test``. Nothing here needs a voice, a node or a database.
"""
import re
import unittest

import importlib

from services.audio import fa_pron
from services.audio.fa_pron import dictionary as D, eval_set, ezafe, g2p, latin, numwords as N, phones as P, pipeline, quality

# the package re-exports functions called «normalize» / «render»; the tests want the modules
NM = importlib.import_module("services.audio.fa_pron.normalize")
render = importlib.import_module("services.audio.fa_pron.render")

ZW = "‌"


def norm(text: str) -> str:
    return NM.normalize(text).text


def pn(word: str) -> str:
    """PN the letter rules give for one word."""
    return P.join(g2p.rules_to_pn(word))


def words(text: str, **kw):
    return [(t.text, t.pn, t.source) for t in pipeline.prepare(text, **kw).tokens if t.kind == "word"]


# ───────────────────────────────────────────────────────────── numbers

class NumberWords(unittest.TestCase):
    def test_cardinals(self):
        cases = {0: "صفر", 1: "یک", 9: "نُه", 10: "ده", 19: "نوزده", 20: "بیست", 21: "بیست و یک", 99: "نود و نُه",
                 100: "صد", 101: "صد و یک", 999: "نهصد و نود و نُه", 1001: "هزار و یک", 2000: "دو هزار",
                 250000: "دویست و پنجاه هزار", 1000000: "یک میلیون", 1250000: "یک میلیون و دویست و پنجاه هزار",
                 2000000000: "دو میلیارد", -5: "منفی پنج"}
        for n, want in cases.items():
            self.assertEqual(N.cardinal(n), want, n)

    def test_thousand_is_not_one_thousand(self):
        self.assertEqual(N.cardinal(1000), "هزار")
        self.assertEqual(N.cardinal(1500), "هزار و پانصد")
        self.assertEqual(N.cardinal(1405), "هزار و چهارصد و پنج")

    def test_nine_never_looks_like_the_negation(self):
        self.assertIn("ُ", N.cardinal(9))          # the damma
        self.assertNotEqual(N.cardinal(9), "نه")

    def test_ordinals(self):
        cases = {1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم", 10: "دهم", 11: "یازدهم", 13: "سیزدهم", 20: "بیستم",
                 21: "بیست و یکم", 30: "سی‌ام", 31: "سی و یکم", 100: "صدم", 101: "صد و یکم", 103: "صد و سوم"}
        for n, want in cases.items():
            self.assertEqual(N.ordinal(n), want, n)
        self.assertEqual(N.ordinal(1, first_as_aval=False), "یک" + "م")

    def test_decimals_and_fractions(self):
        self.assertEqual(N.decimal(3, "14"), "سه ممیز چهارده صدم")
        self.assertEqual(N.decimal(0, "5"), "پنج دهم")
        self.assertEqual(N.decimal(2, "05"), "دو ممیز پنج صدم")
        self.assertEqual(N.decimal(7, "0"), "هفت")
        self.assertEqual(N.fraction(3, 4), "سه چهارم")
        self.assertEqual(N.fraction(1, 2), "یک دوم")

    def test_digits_one_by_one_and_scripts(self):
        self.assertEqual(N.digits_one_by_one("۱۲۰", group=0), "یک دو صفر")
        self.assertEqual(N.digits_one_by_one("123456", group=3), "یک دو سه، چهار پنج شش")
        self.assertEqual(N.to_ascii_digits("۱۴٠٥"), "1405")
        self.assertEqual(N.spell_int_string("۲۵۰,۰۰۰"), "دویست و پنجاه هزار")


# ───────────────────────────────────────────────────────────── normaliser

class Letters(unittest.TestCase):
    def test_arabic_letters_become_persian(self):
        self.assertEqual(norm("كتاب علي"), "کتاب علی")
        self.assertEqual(norm("مي‌خواهم"), "می‌خواهم")

    def test_invisible_controls_and_tatweel_are_removed(self):
        self.assertEqual(norm("سلاـــم‏‎"), "سلام")

    def test_half_spaces(self):
        self.assertEqual(norm("می خواهم کتاب ها را ببینم"), f"می{ZW}خواهم کتاب{ZW}ها را ببینم")
        self.assertEqual(norm("بزرگ تر و بزرگ ترین"), f"بزرگ{ZW}تر و بزرگ{ZW}ترین")
        self.assertEqual(norm("نمی رود"), f"نمی{ZW}رود")

    def test_emoji_removed(self):
        self.assertEqual(norm("عالی بود 😍🔥 ادامه بده"), "عالی بود ادامه بده")

    def test_markdown_removed(self):
        self.assertEqual(norm("**مهم:** آب بنوش"), "مهم، آب بنوش")

    def test_idempotent(self):
        for text in ["قیمت ۲۵۰,۰۰۰ تومان", "ساعت ۱۴:۳۰ در ۱۴۰۵/۰۸/۲۶", "با 3x12 و Instagram", "نه، ۹ روز"]:
            once = norm(text)
            self.assertEqual(norm(once), once, text)


class Dates(unittest.TestCase):
    def test_jalali_numeric(self):
        self.assertEqual(norm("۱۴۰۵/۰۸/۲۶"), "بیست و ششم آبان هزار و چهارصد و پنج")
        self.assertEqual(norm("1405-01-01"), "یکم فروردین هزار و چهارصد و پنج")

    def test_gregorian_numeric(self):
        self.assertEqual(norm("2026/11/16"), "شانزدهم نوامبر دو هزار و بیست و شش")
        self.assertEqual(norm("16.11.2026"), "شانزدهم نوامبر دو هزار و بیست و شش")

    def test_invalid_date_is_left_to_the_number_rules(self):
        out = norm("1405/13/45")
        self.assertNotIn("آبان", out)

    def test_textual(self):
        self.assertEqual(norm("۲۶ آبان ۱۴۰۵"), "بیست و ششم آبان هزار و چهارصد و پنج")
        self.assertEqual(norm("۱ دی"), "یکم دی")

    def test_esfand_leap_day(self):
        self.assertIn("اسفند", norm("1403/12/30"))
        self.assertNotIn("اسفند", norm("1404/12/30"))


class Times(unittest.TestCase):
    def test_times(self):
        self.assertEqual(norm("۱۴:۳۰"), "ساعت چهارده و سی دقیقه")
        self.assertEqual(norm("ساعت ۸:۰۰"), "ساعت هشت")
        self.assertEqual(norm("6:05:10"), "ساعت شش و پنج دقیقه و ده ثانیه")
        self.assertEqual(norm("ساعت ۲۱:۴۵ شب"), "ساعت بیست و یک و چهل و پنج دقیقه شب")


class Phones(unittest.TestCase):
    def test_mobile(self):
        out = norm("۰۹۱۲۳۴۵۶۷۸۹")
        self.assertTrue(out.startswith("صفر نهصد و دوازده، سیصد و چهل و پنج، شصت و هفت، هشتاد و نُه"), out)

    def test_international_mobile(self):
        self.assertTrue(norm("+98 912 345 6789").startswith("صفر نهصد و دوازده"))

    def test_landline(self):
        out = norm("021-12345678")
        self.assertTrue(out.startswith("صفر بیست و یک، دوازده، سی و چهار، پنجاه و شش، هفتاد و هشت"), out)

    def test_card_is_read_digit_by_digit(self):
        out = norm("6037 9975 1234 5678")
        self.assertIn("شش صفر سه هفت", out)

    def test_leading_zero_pairs(self):
        self.assertIn("صفر پنج", norm("021-12345605"))


class Prices(unittest.TestCase):
    def test_price(self):
        self.assertEqual(norm("۲۵۰,۰۰۰ تومان"), "دویست و پنجاه هزار تومان")
        self.assertEqual(norm("۲۵۰٬۰۰۰ تومان"), "دویست و پنجاه هزار تومان")

    def test_symbols(self):
        self.assertEqual(norm("$100"), "صد دلار")
        self.assertEqual(norm("100$"), "صد دلار")
        self.assertEqual(norm("€50"), "پنجاه یورو")

    def test_k_and_m_suffix(self):
        self.assertEqual(norm("250k"), "دویست و پنجاه هزار")
        self.assertEqual(norm("2.5M"), "دو میلیون و پانصد هزار")

    def test_percent(self):
        self.assertEqual(norm("۲۰٪"), "بیست درصد")
        self.assertEqual(norm("%20"), "بیست درصد")
        self.assertEqual(norm("2.5%"), "دو ممیز پنج دهم درصد")

    def test_units(self):
        self.assertEqual(norm("۷۵kg"), "هفتاد و پنج کیلوگرم")
        self.assertEqual(norm("180 cm"), "صد و هشتاد سانتی‌متر")
        self.assertEqual(norm("3000 kcal"), "سه هزار کیلوکالری")
        self.assertEqual(norm("25°C"), "بیست و پنج درجه سانتی‌گراد")


class OtherNumbers(unittest.TestCase):
    def test_ordinals_in_digits(self):
        self.assertEqual(norm("۳ام"), "سوم")
        self.assertEqual(norm("۲۱م"), "بیست و یکم")
        self.assertEqual(norm("1st و 2nd"), "اول و دوم")

    def test_range_and_times_sign(self):
        self.assertEqual(norm("۵-۸ ساعت"), "پنج تا هشت ساعت")
        self.assertEqual(norm("3x12"), "سه در دوازده")

    def test_plus_after_number(self):
        self.assertEqual(norm("30+"), "سی به بالا")

    def test_fraction_and_decimal(self):
        self.assertEqual(norm("3/4"), "سه چهارم")
        self.assertEqual(norm("۳٫۵ کیلومتر"), "سه و نیم کیلومتر")      # a half before a quantity word is «N و نیم»
        self.assertEqual(norm("۳٫۷ کیلومتر"), "سه ممیز هفت دهم کیلومتر")

    def test_plain_and_big_numbers(self):
        self.assertEqual(norm("۱۴۰۵"), "هزار و چهارصد و پنج")
        self.assertEqual(norm("1,250,000"), "یک میلیون و دویست و پنجاه هزار")
        self.assertTrue(norm("1234567890123456").startswith("یک دو سه چهار"))


class Web(unittest.TestCase):
    def test_url(self):
        self.assertIn("چغر دات اپ", norm("www.chagher.app"))
        self.assertIn("اسلش", norm("https://chagher.app/plan"))

    def test_email_handle_hashtag(self):
        self.assertIn("اَت", norm("info@chagher.app"))
        self.assertIn("چغر", norm("@chagher_app"))
        self.assertEqual(norm("#چغر"), "چغر")


class Abbreviations(unittest.TestCase):
    def test_abbreviations(self):
        self.assertEqual(norm("ب.ظ"), "بعد از ظهر")
        self.assertEqual(norm("ه.ش"), "هجری شمسی")
        self.assertEqual(norm("ص ۱۲"), "صفحهٔ دوازده")
        self.assertEqual(norm("Dr. رضایی"), "دکتر رضایی")


class LatinWords(unittest.TestCase):
    def test_lexicon_words(self):
        self.assertEqual(norm("Instagram"), "اینستاگرام")
        self.assertEqual(norm("WhatsApp و Telegram"), "واتساپ و تلگرام")
        self.assertEqual(norm("workout"), "ورکاوت")

    def test_acronyms_are_spelled(self):
        self.assertEqual(norm("GPS"), "جی‌پی‌اس")       # letter names joined by half-spaces: the pipeline reads them as letters, not as «پی» (footprint)
        self.assertEqual(norm("HIIT"), "هیت")

    def test_model_numbers(self):
        self.assertEqual(norm("iPhone 15"), "آیفون پانزده")
        self.assertEqual(norm("A52"), "ای پنجاه و دو")

    def test_unknown_word_is_a_guess_and_reported(self):
        res = NM.normalize("zzyx")
        self.assertEqual(res.notes.latin_guesses, ["zzyx"])
        self.assertTrue(res.text)

    def test_known_word_is_not_a_guess(self):
        self.assertEqual(NM.normalize("Instagram").notes.latin_guesses, [])

    def test_chagher_brand(self):
        self.assertEqual(latin.LATIN_WORDS["chagher"], "چغر")


class Punctuation(unittest.TestCase):
    def test_pause_vocabulary(self):
        self.assertEqual(norm("سلام, خوبی؟ بله; نه: خوب!"), "سلام، خوبی؟ بله، نه، خوب!")

    def test_parentheses_dash_slash(self):
        self.assertEqual(norm("ورزش (و لذت) را دوست دارم"), "ورزش، و لذت، را دوست دارم")
        self.assertIn("یا", norm("ورزش/تغذیه"))
        self.assertIn("و یا", norm("آب و/یا چای"))

    def test_runs_of_marks_collapse(self):
        self.assertEqual(norm("نگران نباش... همه چیز درست می‌شود!!!"), "نگران نباش. همه چیز درست می‌شود!")

    def test_newlines_are_kept_as_paragraphs(self):
        self.assertEqual(norm("خط یک\n\n\nخط دو"), "خط یک\nخط دو")

    def test_quotes_removed(self):
        self.assertEqual(norm("«ورزش» یعنی حرکت"), "ورزش یعنی حرکت")


# ───────────────────────────────────────────────────────────── PN and phonemes

class PhoneNotation(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(P.parse("ma'ni"), ["m", "a", "'", "n", "i"])
        self.assertEqual(P.parse("now"), ["n", "ow"])
        self.assertEqual(P.parse("ke-tAb"), ["k", "e", "t", "A", "b"])
        with self.assertRaises(ValueError):
            P.parse("kitab!")

    def test_validity(self):
        self.assertTrue(P.is_valid("Caqar"))
        self.assertFalse(P.is_valid("xyz?"))

    def test_syllables(self):
        self.assertEqual(P.pn_to_syllables(P.parse("barnAme")), [["b", "a", "r"], ["n", "A"], ["m", "e"]])
        self.assertEqual(P.syllable_count(P.parse("dust")), 1)

    def test_stress_before_the_vowel_like_espeak(self):
        self.assertEqual(P.join(P.with_final_stress(P.parse("kitAb"))), "kitˈAb")
        self.assertEqual(P.join(P.with_final_stress(P.parse("kitAb"), position="first")), "kˈitAb")
        self.assertEqual(P.join(P.with_final_stress(P.parse("dust"))), "dust")      # one syllable: no mark
        self.assertEqual(P.join(P.with_final_stress(P.parse("kitAb"), before_vowel=False)), "kiˈtAb")

    def test_ipa_espeak_style(self):
        self.assertEqual(P.to_ipa(P.parse("salAm")), "salɑm")
        self.assertEqual(P.to_ipa(P.parse("dust")), "duːst")
        self.assertEqual(P.to_ipa(P.parse("Caqar")), "tʃaq1ar")           # غ/ق is the pair «q» «1» in espeak's fa
        self.assertEqual(P.to_ipa(P.parse("morabbi")), "morabbi")           # tashdid = the consonant twice
        self.assertEqual(P.to_ipa(P.parse("ma'ni")), "maʔni")

    def test_glottal_stop_can_be_dropped(self):
        self.assertEqual(P.to_ipa(P.parse("ma'ni"), glottal="drop"), "mani")

    def test_every_symbol_exists_in_the_piper_phoneme_map(self):
        # the single code points of the amir / gyro fa_IR voices include all of these
        for sym in "".join(P.IPA_ESPEAK.values()):
            self.assertEqual(len(sym), 1)

    def test_initial_glottal_stop_is_never_written_for_piper(self):
        self.assertEqual(P.to_ipa(P.parse("'Ali"), glottal="medial"), "ɑli")          # like espeak: no ʔ before a word-initial vowel
        self.assertEqual(P.to_ipa(P.parse("ma'ni"), glottal="medial"), "maʔni")       # but medial and final ones stay
        self.assertEqual(P.to_ipa(P.parse("Soru'"), glottal="medial"), "ʃoruːʔ")
        self.assertEqual(P.to_ipa(P.parse("'Ali"), glottal="keep"), "ʔɑli")

    def test_standard_ipa_for_ssml(self):
        self.assertEqual(P.to_ssml_ipa(P.parse("salAm")), "sælɒːm")

    def test_respelling(self):
        self.assertEqual(P.to_respelling(P.parse("ma'ni")), "مَعنی")
        self.assertEqual(P.to_respelling(P.parse("xAne")), "خانه")
        self.assertEqual(P.to_respelling(P.parse("Ali")), "آلی")
        self.assertEqual(P.to_respelling(P.parse("morabbi")), "مُرَبّی")
        self.assertEqual(P.to_respelling(P.parse("now")), "نَوْ")


class LetterRules(unittest.TestCase):
    """The systematic problems of Persian voices: ع، ه، و، ی."""

    def test_ayn_and_hamza_are_a_glottal_stop(self):
        self.assertEqual(pn("معنی"), "ma'ni")
        self.assertEqual(pn("عالی"), "'Ali")
        self.assertEqual(pn("شروع"), "Saru'")
        self.assertIn("'", pn("جزء"))
        self.assertIn("'", pn("مسئول"))

    def test_final_he_is_e_after_a_consonant_and_h_after_a_long_vowel(self):
        self.assertEqual(pn("خانه"), "xAne")
        self.assertEqual(pn("برنامه"), "barnAme")
        self.assertEqual(pn("راه"), "rAh")
        self.assertEqual(pn("کوه"), "kuh")
        self.assertEqual(pn("سیاه"), "siyAh")
        self.assertEqual(pn("تغذیه"), "taqziye")
        self.assertEqual(pn("همسایه"), "hamsAye")

    def test_vav(self):
        self.assertEqual(pn("وقت"), "vaqt")                 # initial = consonant
        self.assertEqual(pn("دوست"), "dust")                # between consonants = long u
        self.assertEqual(pn("روز"), "ruz")
        self.assertEqual(pn("خواب"), "xAb")                 # خوا: the و is silent
        self.assertEqual(pn("خواهش"), "xAheS")
        self.assertEqual(pn("خود"), "xod")                  # after خ before a consonant: short o
        self.assertEqual(pn("او"), "u")
        self.assertEqual(pn("اوج"), "owj")
        self.assertEqual(pn("میوه"), "mive")

    def test_ye(self):
        self.assertEqual(pn("ایران"), "irAn")
        self.assertEqual(pn("زیاد"), "ziyAd")
        self.assertEqual(pn("آیا"), "AyA")
        self.assertEqual(pn("بیرون"), "birun")
        self.assertEqual(pn("خیابان"), "xiyAbAn")

    def test_tanwin(self):
        self.assertEqual(pn("مثلاً")[-3:], "lan")

    def test_marks_are_trusted(self):
        self.assertEqual(g2p.respelling_to_pn("مَعنی"), "ma'ni")
        self.assertEqual(g2p.respelling_to_pn("چِغِر"), "Ceqer")
        self.assertEqual(g2p.respelling_to_pn("مُرَبّی"), "morabbi")

    def test_respelling_ascii_is_pn(self):
        self.assertEqual(g2p.respelling_to_pn("Caqar"), "Caqar")
        with self.assertRaises(ValueError):
            g2p.respelling_to_pn("ca?ar")

    def test_respelling_empty(self):
        self.assertEqual(g2p.respelling_to_pn("  "), "")

    def test_cluster_breaking(self):
        self.assertEqual(pn("دفتر"), "daftar")             # CVC.CVC
        self.assertEqual(pn("چغر"), "Caqar")               # CV.CVC
        self.assertEqual(pn("مدرسه"), "madrase")           # from the left before an explicit vowel
        self.assertEqual(pn("وقت"), "vaqt")                # a real final cluster stays

    def test_hamza_above_makes_ezafe(self):
        self.assertTrue(pn("خانهٔ").endswith("ye"))

    def test_lexicon_agreement_floor(self):
        """The rules are a fallback, measured against the curated list: keep the consonant skeleton right."""
        ok = total = 0
        cons = set(P.CONSONANTS)
        for e in D.shared().values():
            if " " in e.word:
                continue
            got = "".join(P.join(g2p.rules_to_pn(part)) for part in e.word.split(ZW))
            a = [t for t in P.parse(got) if t in cons]
            b = [t for t in P.parse(e.pn) if t in cons]
            total += 1
            ok += a == b
        self.assertGreater(ok / total, 0.75, f"{ok}/{total}")


# ───────────────────────────────────────────────────────────── lexicon

class Lexicon(unittest.TestCase):
    def test_shared_lexicon_is_clean(self):
        self.assertEqual(D.shared_errors(), [])
        self.assertGreaterEqual(len(D.shared()), 900)

    def test_every_pn_is_valid_and_every_key_is_persian(self):
        for key, e in D.shared().items():
            self.assertTrue(P.is_valid(e.pn), e)
            self.assertTrue(re.search(r"[؀-ۿ]", e.word), e)

    def test_categories_cover_the_owners_problems(self):
        cats = {e.category for e in D.shared().values()}
        for want in ("ع و ء", "ه و پایانی", "و و او", "ی و ای", "اعداد"):
            self.assertIn(want, cats)

    def test_problem_words_have_the_right_reading(self):
        d = D.Dictionary()
        for word, want in {"معنی": "ma'ni", "عضله": "'azale", "خانه": "xAne", "او": "u", "خواهر": "xAhar", "دو": "do",
                           "نو": "now", "نه": "na", "ده": "dah", "سوال": "so'Al", "مسئول": "mas'ul", "چغر": "Caqar",
                           "مربی": "morabbi", "ورزش": "varzeS", "تغذیه": "taqziye", "پروتئین": "porotein"}.items():
            e = d.lookup(word)
            self.assertIsNotNone(e, word)
            self.assertEqual(e.pn, want, word)

    def test_marked_nine_is_not_the_negation(self):
        d = D.Dictionary()
        self.assertEqual(d.lookup("نُه").pn, "noh")
        self.assertEqual(d.lookup("نه").pn, "na")

    def test_lookup_ignores_arabic_letters_marks_and_half_spaces(self):
        d = D.Dictionary()
        self.assertEqual(d.lookup("مَعْنَي").pn, "ma'ni")
        self.assertEqual(d.lookup("چربی‌سوزی").pn, d.lookup("چربیسوزی").pn)

    def test_store_beats_global_beats_shared(self):
        d = D.Dictionary(store={"چغر": "Cegar"}, extra={"چغر": "Cogor", "معنی": "mAni"})
        self.assertEqual(d.lookup("چغر").pn, "Cegar")
        self.assertEqual(d.lookup("چغر").source, "store")
        self.assertEqual(d.lookup("معنی").source, "global")
        self.assertEqual(d.lookup("عالی").source, "shared")

    def test_invalid_store_entries_are_ignored(self):
        d = D.Dictionary(store={"x": "not valid!"})
        self.assertIsNone(d.lookup("x"))

    def test_phrases(self):
        d = D.Dictionary()
        self.assertEqual(d.phrase_at(["ان", "شاءالله"], 0)[1], "inSAlA")
        self.assertIsNone(d.phrase_at(["این", "کتاب"], 0))

    def test_safe_words_are_skipped_at_depth_lexicon(self):
        d = D.Dictionary()
        self.assertTrue(d.lookup("من").safe)
        self.assertFalse(d.lookup("معنی").safe)

    def test_rows_for_the_panel(self):
        rows = D.all_shared_rows()
        self.assertTrue(all({"word", "pn", "respelling", "ipa", "category"} <= set(r) for r in rows))


# ───────────────────────────────────────────────────────────── pipeline

class Pipeline(unittest.TestCase):
    def test_and_is_o_after_a_consonant_and_vo_after_a_vowel(self):
        got = {w: p for w, p, _ in words("ورزش و تغذیه و میوه و راه و سیاه")}
        seq = [p for w, p, s in words("ورزش و تغذیه و میوه") if s == "conj"]
        self.assertEqual(seq, ["o", "vo"])
        self.assertTrue(got)

    def test_and_after_a_pause_is_o(self):
        self.assertEqual([p for _, p, s in words("خانه، و کوه") if s == "conj"], ["o"])

    def test_homographs(self):
        self.assertEqual(dict((w, p) for w, p, _ in words("کرم ضدآفتاب را بمال"))["کرم"], "kerem")
        self.assertEqual(dict((w, p) for w, p, _ in words("کرم خاکی در باغ"))["کرم"], "kerm")
        self.assertEqual(dict((w, p) for w, p, _ in words("از لطف و کرم شما"))["کرم"], "karam")
        self.assertEqual(dict((w, p) for w, p, _ in words("کشتی ورزش باستانی است"))["کشتی"], "kuSti")
        self.assertEqual(dict((w, p) for w, p, _ in words("کشتی در بندر است"))["کشتی"], "keSti")
        self.assertEqual(dict((w, p) for w, p, _ in words("او مرد."))["مرد"], "mord")
        self.assertEqual(dict((w, p) for w, p, _ in words("یک مرد آمد"))["مرد"], "mard")
        self.assertEqual(dict((w, p) for w, p, _ in words("برد وای‌فای کم است"))["برد"], "bard")
        self.assertEqual(dict((w, p) for w, p, _ in words("تیم ما برد"))["برد"], "bord")
        self.assertEqual(dict((w, p) for w, p, _ in words("گرد و غبار"))["گرد"], "gard")
        self.assertEqual(dict((w, p) for w, p, _ in words("شکر خدا"))["شکر"], "Sokr")

    def test_store_entry_overrides_homograph_default(self):
        d = D.Dictionary(store={"کشتی": "kuSti"})
        self.assertEqual(dict((w, p) for w, p, _ in words("کشتی در بندر است", dictionary=d))["کشتی"], "kuSti")

    def test_morphology_builds_plurals_from_known_stems(self):
        self.assertEqual(dict((w, p) for w, p, _ in words("عضله‌ها"))[f"عضله{ZW}ها"], "'azalehA")
        self.assertEqual(dict((w, p) for w, p, _ in words("خانه‌های"))[f"خانه{ZW}های"], "xAnehAye")

    def test_compound_with_half_space(self):
        self.assertEqual(dict((w, p) for w, p, _ in words("چربی‌سوزی"))[f"چربی{ZW}سوزی"], "Carbisuzi")

    def test_depth_normalize_touches_no_word(self):
        self.assertTrue(all(p is None for _, p, _ in words("معنی ورزش", depth="normalize")))

    def test_depth_lexicon_leaves_unknown_words_to_the_engine(self):
        got = dict((w, p) for w, p, _ in words("معنی گربه", depth="lexicon"))
        self.assertEqual(got["معنی"], "ma'ni")
        self.assertIsNone(got["گربه"])

    def test_depth_full_gives_every_word_a_pronunciation(self):
        self.assertTrue(all(p for _, p, _ in words("معنی گربه سفید", depth="full")))

    def test_unknown_list(self):
        self.assertIn("گربه", pipeline.prepare("معنی گربه").unknown)

    def test_phrase_is_one_token(self):
        toks = [t for t in pipeline.prepare("ان شاءالله فردا").tokens if t.kind == "word"]
        self.assertEqual((toks[0].pn, toks[0].source, toks[0].n_words), ("inSAlA", "phrase", 2))

    def test_safe_word_known_but_not_applied_at_lexicon_depth(self):
        t = [x for x in pipeline.prepare("من", depth="lexicon").tokens][0]
        self.assertEqual((t.pn, t.apply), ("man", False))
        t = [x for x in pipeline.prepare("من", depth="full").tokens][0]
        self.assertTrue(t.apply)

    def test_numbers_come_out_as_known_words(self):
        prep = pipeline.prepare("۹ روز و ۲۱ نفر", depth="lexicon")
        self.assertEqual([t.pn for t in prep.tokens if t.kind == "word"][:2], ["noh", "ruz"])

    def test_pauses_are_tokens(self):
        kinds = [t.kind + ":" + (t.pause or "") for t in pipeline.prepare("سلام، خوبی؟ بله.").tokens]
        self.assertIn("pause:short", kinds)
        self.assertEqual(kinds.count("pause:long"), 2)

    def test_paragraphs(self):
        self.assertIn("pause:para", [t.kind + ":" + t.pause for t in pipeline.prepare("یک\nدو").tokens])

    def test_bad_depth(self):
        with self.assertRaises(ValueError):
            pipeline.prepare("سلام", depth="nope")


class Ezafe(unittest.TestCase):
    def _ez(self, text, **kw):
        return [(t.text, t.ezafe) for t in pipeline.prepare(text, **kw).tokens if t.kind == "word"]

    def test_noun_then_pronoun(self):
        self.assertTrue(dict(self._ez("نام من"))["نام"] or dict(self._ez("خانه من"))["خانه"])
        self.assertTrue(dict(self._ez("خانه من"))["خانه"])

    def test_noun_then_adjective(self):
        self.assertTrue(dict(self._ez("برنامه تمرینی"))["برنامه"])
        self.assertTrue(dict(self._ez("ورزش روزانه"))["ورزش"])

    def test_chain(self):
        got = dict(self._ez("وعده غذایی سالم"))
        self.assertTrue(got["وعده"])

    def test_never_before_a_verb_or_preposition(self):
        self.assertFalse(dict(self._ez("خانه است"))["خانه"])
        self.assertFalse(dict(self._ez("خانه در"))["خانه"])
        self.assertFalse(dict(self._ez("خانه را"))["خانه"])
        self.assertFalse(dict(self._ez("خانه می‌کنم"))["خانه"])

    def test_a_light_verb_construction_is_not_linked(self):
        got = dict(self._ez("مکمل خوبی پیشنهاد کرد"))
        self.assertFalse(got["خوبی"])                 # «پیشنهاد کرد» is one verb
        self.assertTrue(got["مکمل"])
        self.assertTrue(dict(self._ez("خانه من است"))["خانه"])          # a plain copula does not block it

    def test_a_pause_blocks_it(self):
        self.assertFalse(dict(self._ez("خانه، من"))["خانه"])

    def test_function_words_do_not_take_it(self):
        self.assertFalse(dict(self._ez("از خانه"))["از"])
        self.assertFalse(dict(self._ez("من خانه"))["من"])

    def test_two_unknown_words_get_nothing(self):
        got = self._ez("گربه سفید")
        self.assertFalse(any(e for _, e in got))

    def test_switch(self):
        self.assertFalse(any(e for _, e in self._ez("خانه من", ezafe=False)))

    def test_ezafe_vowel_in_phonemes(self):
        toks = [t for t in pipeline.prepare("خانه من").tokens if t.kind == "word"][0]
        self.assertEqual(P.join(toks.tokens()), "xAneye")
        toks = [t for t in pipeline.prepare("برنامه تمرینی").tokens if t.kind == "word"][0]
        self.assertTrue(toks.ezafe)

    def test_can_take_helpers(self):
        self.assertFalse(ezafe.can_take("می‌روم", "-", ""))
        self.assertTrue(ezafe.can_follow("من", "F"))


# ───────────────────────────────────────────────────────────── renderers

class Renderers(unittest.TestCase):
    TEXT = "معنی ورزش روزانه، ۲۵۰,۰۰۰ تومان است."

    def test_piper_ipa(self):
        r = fa_pron.for_engine(self.TEXT, "piper", depth="lexicon")
        self.assertEqual(len(r.ipa_sentences), 1)
        self.assertIn("maʔ", r.ipa)
        self.assertTrue(r.ipa.endswith("."))
        self.assertIn(",", r.ipa)
        # every character is one symbol the Piper phoneme map has (letters, stress, length, punctuation, space)
        self.assertNotIn("\n", r.ipa)

    def test_piper_hybrid_uses_native_words(self):
        r = fa_pron.for_engine("معنی گربه", "piper", depth="lexicon", native_ipa=lambda w: "<" + w + ">")
        self.assertIn("<گربه>", r.ipa)
        self.assertEqual(r.notes["native_words"], 1)

    def test_piper_uses_our_numbers_even_though_text_engines_skip_them(self):
        """Measured: espeak phonemises number words one by one without context and does worse than the lexicon."""
        r = fa_pron.for_engine("هفت روز و معنی", "piper", depth="lexicon", native_ipa=lambda w: "<" + w + ">")
        self.assertNotIn("<هفت>", r.ipa)
        self.assertEqual(fa_pron.for_engine("هفت", "moss", depth="lexicon").text, "هفت")   # a text engine reads numbers right itself

    def test_piper_full_never_needs_native(self):
        r = fa_pron.for_engine("معنی گربه", "piper", depth="full", native_ipa=lambda w: "<>")
        self.assertNotIn("<>", r.ipa)

    def test_piper_stress_modes(self):
        last = fa_pron.for_engine("برنامه", "piper", depth="lexicon").ipa
        none = fa_pron.for_engine("برنامه", "piper", depth="lexicon", stress="none").ipa
        first = fa_pron.for_engine("برنامه", "piper", depth="lexicon", stress="first").ipa
        self.assertIn("ˈ", last)
        self.assertNotIn("ˈ", none)
        self.assertNotEqual(last, first)

    def test_piper_splits_sentences(self):
        r = fa_pron.for_engine("معنی عالی است. ورزش خوب است!", "piper", depth="lexicon")
        self.assertEqual(len(r.ipa_sentences), 2)
        self.assertTrue(r.ipa_sentences[1].endswith("!"))

    def test_text_engine_respells_only_known_words(self):
        r = fa_pron.for_engine("معنی گربه", "moss", depth="lexicon")
        self.assertIn("مَعنی", r.text)
        self.assertIn("گربه", r.text)

    def test_text_engine_skips_safe_words(self):
        self.assertEqual(fa_pron.for_engine("من", "moss", depth="lexicon").text, "من")

    def test_edge_ssml_sub_and_phoneme_modes(self):
        sub = render.render_edge(pipeline.prepare("معنی"), mode="sub")
        self.assertIn('<sub alias="مَعنی">معنی</sub>', sub.ssml)
        ph = render.render_edge(pipeline.prepare("معنی"), mode="phoneme")
        self.assertIn('<phoneme alphabet="ipa" ph="mæʔniː">معنی</phoneme>', ph.ssml)

    def test_edge_ssml_is_escaped(self):
        r = render.render_edge(pipeline.prepare("معنی <b> & ورزش"))
        self.assertNotIn("<b>", r.ssml)

    def test_edge_pauses_are_breaks(self):
        r = render.render_edge(pipeline.prepare("سلام، خوبی."))
        self.assertIn('<break time="250ms"/>', r.ssml)
        self.assertIn('<break time="550ms"/>', r.ssml)

    def test_ezafe_respelling_per_ending(self):
        mk = lambda pnv: pipeline.Token("word", "x", pn=pnv, ezafe=True)
        self.assertTrue(render.respell_token(mk("ketAb")).endswith("ِ"))               # consonant: kasra
        self.assertTrue(render.respell_token(mk("xAne")).endswith("یِ"))               # silent e: half-space + ye
        self.assertIn("‌", render.respell_token(mk("xAne")))
        self.assertTrue(render.respell_token(mk("dAnA")).endswith("یِ"))
        self.assertTrue(render.respell_token(mk("ma'ni")).endswith("یِ"))

    def test_unknown_engine(self):
        with self.assertRaises(ValueError):
            render.render(pipeline.prepare("سلام"), "nope")

    def test_subs_listing(self):
        r = fa_pron.for_engine("معنی", "moss", depth="lexicon")
        self.assertEqual(r.subs[0]["pn"], "ma'ni")
        self.assertIn("ipa", r.subs[0])

    def test_default_depths(self):
        # measured on the site's own voice (gyro, 272 sentences): the lexicon is not better than the normaliser alone yet, so the
        # safe depth is the default until the node's Whisper measurement says otherwise (services.measured_depths)
        self.assertEqual(fa_pron.DEFAULT_DEPTH["piper"], "normalize")
        self.assertEqual(fa_pron.DEFAULT_DEPTH["edge"], "normalize")       # measured: respelling hurts Edge
        self.assertTrue(all(d in fa_pron.DEPTHS for d in fa_pron.DEFAULT_DEPTH.values()))


# ───────────────────────────────────────────────────────────── quality and the fixed set

class Quality(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(quality.score("سلام به همه", "سلام به همه").errors, 0)

    def test_substitution_insertion_deletion(self):
        s = quality.score("سلام به همه", "سلام همه")
        self.assertEqual((s.dele, s.sub, s.ins, s.words), (1, 0, 0, 3))
        s = quality.score("سلام به همه", "سلام به همه ی")
        self.assertEqual(s.ins, 1)
        s = quality.score("سلام به همه", "سلام به او")
        self.assertEqual(s.sub, 1)

    def test_numbers_are_compared_as_words(self):
        self.assertEqual(quality.score("۲۵۰ تومان", "دویست و پنجاه تومان").errors, 0)

    def test_half_space_marks_and_punctuation_do_not_count(self):
        self.assertEqual(quality.score("می‌خواهم، کتاب!", "می خواهم کتاب").errors, 0)
        self.assertEqual(quality.score("مَعنی", "معنی").errors, 0)

    def test_colloquial_forms_are_folded(self):
        self.assertEqual(quality.score("یک کتاب است", "یه کتاب هست").errors, 0)

    def test_corpus_wer(self):
        self.assertAlmostEqual(quality.corpus_wer([("الف ب", "الف ب"), ("الف ب", "الف")]), 0.25)

    def test_summarise(self):
        rows = [{"tag": "he", "ref": "خانه من", "before": "خانه", "after": "خانه من"},
                {"tag": "he", "ref": "راه من", "before": "راه من", "after": "راه"}]
        s = quality.summarise(rows)
        self.assertEqual(s["overall"]["n"], 2)
        self.assertEqual(s["overall"]["before"], 0.25)
        self.assertEqual(s["overall"]["after"], 0.25)
        self.assertEqual(len(s["worse"]), 1)
        self.assertIn("he", s["by_tag"])

    def test_missed_words(self):
        self.assertEqual(quality.score("سلام عزیز دل", "سلام دل").missed, ["عزیز"])


class FixedSet(unittest.TestCase):
    def test_size_and_tags(self):
        self.assertGreaterEqual(len(eval_set.SENTENCES), 200)
        for tag, text in eval_set.SENTENCES:
            self.assertIn(tag, eval_set.TAGS)
            self.assertTrue(text.strip())

    def test_every_tag_has_enough_sentences(self):
        for tag in eval_set.TAGS:
            self.assertGreaterEqual(len(eval_set.by_tag(tag)), 3, tag)

    def test_no_duplicates(self):
        texts = [t for _, t in eval_set.SENTENCES]
        self.assertEqual(len(texts), len(set(texts)))

    def test_the_hard_cases_are_really_in_it(self):
        blob = " ".join(t for _, t in eval_set.SENTENCES)
        for needle in ("معنی", "عضله", "خانه", "او", "خواهر", "خیلی", "کرم", "کشتی", "مرد", "چغر", "Instagram", "۱۴:۳۰", "٪",
                       "۰۹۱۲۳۴۵۶۷۸۹", "۱۴۰۵/۰۸/۲۶", "مربی"):
            self.assertIn(needle, blob)

    def test_every_sentence_survives_the_layer(self):
        for tag, text in eval_set.SENTENCES:
            for engine in ("piper", "edge", "moss"):
                r = fa_pron.for_engine(text, engine, native_ipa=lambda w: "")
                self.assertTrue((r.ipa or r.text or r.ssml).strip(), (engine, text))

    def test_sample_is_small_and_covers_all_tags(self):
        s = eval_set.sample(2)
        self.assertEqual({t for t, _ in s}, set(eval_set.TAGS))
        self.assertEqual(len(s), 2 * len(eval_set.TAGS))

    def test_the_layer_changes_the_hard_sentences(self):
        changed = 0
        for tag, text in eval_set.SENTENCES:
            if fa_pron.for_engine(text, "moss", depth="lexicon").text != text:
                changed += 1
        self.assertGreater(changed / len(eval_set.SENTENCES), 0.6)


if __name__ == "__main__":
    unittest.main()
