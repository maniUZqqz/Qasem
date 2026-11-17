"""Second review round of the pronunciation layer: every case the reviewer found is a test here.

Pure Python (no voice, no node, no database): ``python -m unittest services.tests_fa_pron_round2`` from backend/.
"""
import importlib
import unittest

from services.audio import fa_pron
from services.audio.fa_pron import dictionary as D, g2p, latin, phones as P, pipeline

NM = importlib.import_module("services.audio.fa_pron.normalize")
render = importlib.import_module("services.audio.fa_pron.render")

ZW = "‌"


def norm(text: str) -> str:
    return NM.normalize(text).text


def toks(text, depth="lexicon", **kw):
    return [t for t in pipeline.prepare(text, depth=depth, **kw).tokens if t.kind == "word"]


_NO_NATIVE = object()


def piper(text, depth="lexicon", native=_NO_NATIVE, **kw):
    """The Piper rendering. Default: no front end at all (our own stress rule); pass ``native=`` a callback to see the hybrid."""
    prep = pipeline.prepare(text, depth=depth, **kw)
    if native is _NO_NATIVE:
        return render.render_piper(prep)
    return render.render_piper(prep, native_ipa=native)


# ───────────────────────────────────────────────────────────── 1. «ه‌ی» is the ezafe, not the indefinite «ی»

class WrittenEzafe(unittest.TestCase):
    def test_he_zwnj_ye_is_an_ezafe(self):
        for text, stem in (("برنامه‌ی تمرینی چغر", "برنامه"), ("وعده‌ی غذایی", "وعده"), ("دو هفته‌ی دیگر", "هفته"),
                           ("وزنه‌ی سنگین", "وزنه")):
            t = next(x for x in toks(text) if x.text == stem)
            self.assertTrue(t.ezafe and t.written_ezafe, text)
            self.assertNotIn("morph", t.source, text)
            ipa = piper(text).ipa
            self.assertIn("eje", ipa, f"{text}: «-ye» must be heard: {ipa}")
            self.assertNotIn("ije", ipa.split(" ")[0], text)          # not the extra /i/ syllable of the old layer

    def test_he_zwnj_ye_loses_nothing_when_the_next_word_is_unknown(self):
        t = next(x for x in toks("هفته‌ی دیگر") if x.text == "هفته")
        self.assertTrue(t.ezafe)
        t2 = next(x for x in toks("وزنه‌ی سنگین") if x.text == "وزنه")
        self.assertTrue(t2.ezafe)

    def test_the_indefinite_ending_is_not_an_ezafe(self):
        t = toks("برنامه‌ای عالی")[0]
        self.assertFalse(t.ezafe)
        self.assertEqual(t.pn, "barnAmeyi")                      # «ای» is the suffix, not the vocative «ای» (ey)
        self.assertNotIn("barnAmeey", t.pn)
        self.assertTrue(piper("برنامه‌ای عالی").ipa.startswith("barnɑmejˈi"))

    def test_phrase_lookup_sees_through_the_mark(self):
        t = toks("در مورد برنامه‌ی تمرینی")
        self.assertTrue(any(x.source == "phrase" for x in t))

    def test_explicit_ezafe_helper(self):
        self.assertEqual(pipeline.explicit_ezafe("برنامه‌ی"), (True, "برنامه"))
        self.assertEqual(pipeline.explicit_ezafe("برنامهٔ"), (True, "برنامه"))
        self.assertEqual(pipeline.explicit_ezafe("مربیِ"), (True, "مربی"))
        self.assertEqual(pipeline.explicit_ezafe("برنامه‌ای"), (False, "برنامه‌ای"))
        self.assertEqual(pipeline.explicit_ezafe("ایرانی"), (False, "ایرانی"))
        self.assertEqual(pipeline.explicit_ezafe("که"), (False, "که"))


# ───────────────────────────────────────────────────────────── 2. a written ezafe mark is always honoured

class MarkIsHonoured(unittest.TestCase):
    CASES = ["برنامهٔ بزرگ", "خانهٔ بزرگ", "برنامهٔ اختصاصی", "وزنهٔ آزاد", "مربیِ باتجربه", "برنامهٔ ورزشی و غذاییِ اختصاصیِ هر ورزشکار"]

    def test_the_ezafe_survives_whatever_the_next_word_is(self):
        for text in self.CASES:
            first = toks(text)[0]
            self.assertTrue(first.ezafe, text)
            ipa = piper(text).ipa.split(" ")[0]
            self.assertTrue(ipa.endswith(("eje", "ije")) or "je" in ipa[-3:], f"{text}: {ipa}")

    def test_unknown_stem_goes_to_the_voice_with_the_mark(self):
        seen = []
        piper("کیسهٔ بزرگ", native=lambda w: seen.append(w) or "x")
        self.assertTrue(any(w.startswith("کیسه") and w.endswith(("ِ", "ٔ")) for w in seen), seen)

    def test_text_engines_get_the_mark_too(self):
        out = render.render_text(pipeline.prepare("کیسهٔ بزرگ", depth="lexicon")).text
        self.assertTrue(out.startswith("کیسه‌یِ") or out.startswith("کیسهٔ"), out)
        out2 = render.render_text(pipeline.prepare("اختصاصیِ بزرگ", depth="lexicon")).text
        self.assertTrue(out2.startswith("اختصاصیِ"), out2)           # never «اختصاصییِ»
        self.assertNotIn("ییِ", out2)

    def test_no_extra_ezafe_after_a_possessive_ending(self):
        self.assertFalse(toks("پدرش مرد")[0].ezafe)
        self.assertFalse(toks("کتابم خوب است")[0].ezafe)

    def test_names_do_not_take_an_ezafe_by_the_unknown_word_heuristic(self):
        self.assertFalse(toks("محمد و فاطمه کشتی گرفتند")[2].ezafe)


# ───────────────────────────────────────────────────────────── 3. letter-name acronyms

class Acronyms(unittest.TestCase):
    def test_normaliser_writes_letter_names_with_half_spaces(self):
        self.assertEqual(norm("خروجی PDF"), "خروجی پی‌دی‌اف")
        self.assertEqual(norm("GPS"), "جی‌پی‌اس")
        self.assertEqual(norm("HD"), "اچ‌دی")
        self.assertEqual(norm("BMI"), "بی‌ام‌آی")
        self.assertEqual(norm("QR"), "کیو‌آر")
        self.assertEqual(norm("iOS"), "آی‌او‌اس")
        self.assertEqual(norm("JPG"), "جی‌پی‌جی")
        self.assertEqual(norm("MP4"), "ام‌پی چهار")
        self.assertEqual(norm("pdf"), "پی‌دی‌اف")
        self.assertEqual(norm("gps"), "جی‌پی‌اس")

    def test_mobile_network_and_picture_size(self):
        self.assertEqual(norm("4G"), "چهار جی")
        self.assertEqual(norm("اینترنت 5G"), "اینترنت پنج جی")
        self.assertEqual(norm("4K"), "چهار کی")
        self.assertEqual(norm("۵ گرم"), "پنج گرم", "a real gram stays a gram")
        self.assertEqual(norm("۲۵۰ g"), "دویست و پنجاه گرم")

    def test_letter_word_is_read_with_the_letter_names(self):
        self.assertEqual(latin.letters_pn("پی‌دی‌اف"), "pidief")
        self.assertEqual(latin.letters_pn("جی‌پی‌اس"), "jipies")
        self.assertEqual(latin.letters_pn("آی‌او‌اس"), "Ayowes")
        self.assertIsNone(latin.letters_pn("پی"), "a single «پی» is the word footprint")
        self.assertIsNone(latin.letters_pn("دی"), "a single «دی» is the month Dey")
        self.assertIsNone(latin.letters_pn("پی‌گیری"), "a real word that starts with «پی»")

    def test_piper_gets_letter_names_not_pey_and_dey(self):
        for text in ("خروجی PDF", "ردیاب GPS", "ویدیو HD", "پیام BMI"):
            ipa = piper(text).ipa
            self.assertNotIn("pej", ipa, text)
            self.assertNotIn("dej", ipa, text)
        # letter by letter, each with its own stress (the way a person spells them), not as one word
        self.assertIn("pˈiː dˈiː ˈɛf", piper("خروجی PDF").ipa)
        self.assertIn("dʒˈiː pˈiː ˈɛs", piper("ردیاب GPS").ipa)
        self.assertIn("kjˈuː ˈɑr", piper("QR").ipa)

    def test_text_engines_keep_the_written_letter_names(self):
        out = render.render_text(pipeline.prepare("خروجی PDF", depth="lexicon")).text
        self.assertEqual(out, "خروجی پی‌دی‌اف")

    def test_letter_words_never_take_an_ezafe(self):
        t = toks("فایل PDF حجیم")
        self.assertFalse(any(x.ezafe for x in t))

    def test_spaced_letter_names_are_phrases(self):
        t = toks("جی پی اس و پی دی اف")
        self.assertEqual([x.pn for x in t if x.source == "phrase"], ["jipies", "pidief"])

    def test_vitamin_d_and_the_month(self):
        self.assertEqual(norm("ویتامین D"), "ویتامین دی")
        self.assertEqual([x.pn for x in toks("ویتامین دی")][-1], "di")
        self.assertEqual(toks("دی ماه")[0].pn, "dey")
        self.assertEqual(toks("پی کار")[0].pn, "pey")

    def test_idempotent(self):
        for t in ("خروجی PDF و GPS", "4G و HD", "MP4"):
            once = norm(t)
            self.assertEqual(norm(once), once)


# ───────────────────────────────────────────────────────────── 4. homographs with verbs

class Homographs(unittest.TestCase):
    def pn(self, text, word):
        return next(x.pn for x in toks(text) if x.text == word)

    def test_kushti_wrestling(self):
        for text in ("او کشتی می‌گیرد", "کشتی گرفتن", "او کشتی گرفت", "کشتی بگیر", "برادرم کشتی می‌گیرد و هر هفته مسابقه دارد",
                     "ورزش کشتی", "مسابقهٔ کشتی", "قهرمان کشتی"):
            self.assertEqual(self.pn(text, "کشتی"), "kuSti", text)

    def test_keshti_ship(self):
        for text in ("یک کشتی بزرگ", "کشتی دیشب به بندر رسید", "کشتی را گرفتند", "سوار کشتی شدیم"):
            self.assertEqual(self.pn(text, "کشتی"), "keSti", text)

    def test_mord_died(self):
        for text in ("پدرش مرد", "بعد از یک سال مرد", "او مرد.", "مادربزرگ ناگهان مرد و همه غمگین شدند", "پدرم مرد",
                     "مادرش مرد و او تنها ماند", "دیروز مرد"):
            self.assertEqual(self.pn(text, "مرد"), "mord", text)

    def test_mard_man(self):
        for text in ("یک مرد قوی وزنه را بلند کرد", "آن مرد خوب بود", "مرد قوی", "این مرد ورزشکار است", "او مرد خوبی بود"):
            self.assertEqual(self.pn(text, "مرد"), "mard", text)

    def test_the_verb_reading_takes_no_ezafe_in_front(self):
        t = toks("بعد از یک سال مرد")
        self.assertFalse(next(x for x in t if x.text == "سال").ezafe)

    def test_died_plural(self):
        self.assertEqual(self.pn("همه مردند", "مردند"), "mordand")


# ───────────────────────────────────────────────────────────── 5. numbers glued to words, formats

class NumberFormats(unittest.TestCase):
    def test_digits_glued_to_a_word_are_separated(self):
        self.assertEqual(norm("هفته‌ای ۳جلسه تمرین"), "هفته‌ای سه جلسه تمرین")
        self.assertEqual(norm("۲۰تومان"), "بیست تومان")
        self.assertEqual(norm("۵کیلو"), "پنج کیلو")
        self.assertEqual(norm("۱۰دقیقه‌ای"), "ده دقیقه‌ای")
        self.assertEqual(norm("جلسه۳"), "جلسه سه")

    def test_ordinal_endings_are_not_split(self):
        self.assertEqual(norm("۱۲ام"), "دوازدهم")
        self.assertEqual(norm("جلسهٔ ۱۲ام"), "جلسهٔ دوازدهم")
        self.assertEqual(norm("۱۰ مین"), "دهمین")
        self.assertEqual(norm("۳مین"), "سومین")
        self.assertEqual(norm("۳م"), "سوم")

    def test_decimal_mark_is_not_a_word_boundary(self):
        self.assertEqual(norm("۳٫۱۴ متر"), "سه ممیز چهارده صدم متر")

    def test_dot_thousands(self):
        self.assertEqual(norm("۴۵۰.۰۰۰ تومان"), "چهارصد و پنجاه هزار تومان")
        self.assertEqual(norm("۱.۲۵۰.۰۰۰ ریال"), "یک میلیون و دویست و پنجاه هزار ریال")
        self.assertEqual(norm("۲.۵۰۰ تومان"), "دو هزار و پانصد تومان")
        self.assertEqual(norm("۳.۱۴۱"), "سه ممیز صد و چهل و یک هزارم", "no price word: a decimal")
        self.assertEqual(norm("۲٫۵۰۰"), "دو ممیز پانصد هزارم", "the real decimal separator stays a decimal")

    def test_slash_thousands(self):
        self.assertEqual(norm("۹۹۰/۰۰۰ تومان"), "نهصد و نود هزار تومان")
        self.assertEqual(norm("۱۲/۵۰۰ تومان"), "دوازده هزار و پانصد تومان")
        self.assertEqual(norm("۳/۴"), "سه چهارم")
        self.assertEqual(norm("۱۴۰۵/۰۸/۲۶"), "بیست و ششم آبان هزار و چهارصد و پنج")

    def test_minus_sign(self):
        self.assertEqual(norm("-۵ کیلو"), "منفی پنج کیلو")
        self.assertEqual(norm("دمای اتاق -۵ درجه"), "دمای اتاق منفی پنج درجه")
        self.assertEqual(norm("وزن ۵-۱۰ کیلو"), "وزن پنج تا ده کیلو")
        self.assertEqual(norm("برنامه - ۵ روز"), "برنامه، پنج روز")

    def test_half_is_said_va_nim(self):
        self.assertEqual(norm("۲٫۵ میلیون"), "دو و نیم میلیون")
        self.assertEqual(norm("۲.۵ ساعت"), "دو و نیم ساعت")
        self.assertEqual(norm("۰٫۵ ساعت"), "نیم ساعت")
        self.assertEqual(norm("۱.۵ کیلومتر"), "یک و نیم کیلومتر")
        self.assertEqual(norm("۲.۵kg"), "دو و نیم کیلوگرم")
        self.assertEqual(norm("۲٫۷ میلیون"), "دو ممیز هفت دهم میلیون", "only a half gets «و نیم»")
        self.assertEqual(norm("۲٫۵"), "دو ممیز پنج دهم", "a bare decimal stays a decimal")

    def test_html_is_not_read_aloud(self):
        self.assertEqual(norm("<b>سلام</b>"), "سلام")
        self.assertEqual(norm("سلام<br/>خوب"), "سلام\nخوب")
        self.assertEqual(norm("<p class=\"x\">متن</p>"), "متن")

    def test_everything_is_idempotent(self):
        for t in ("هفته‌ای ۳جلسه", "۴۵۰.۰۰۰ تومان", "-۵ کیلو", "۲٫۵ میلیون", "۱۰ مین", "<b>سلام</b>"):
            once = norm(t)
            self.assertEqual(norm(once), once, t)


# ───────────────────────────────────────────────────────────── 6. the respelling converter

class Respelling(unittest.TestCase):
    def pn(self, word):
        return g2p.respelling_to_pn(word)

    def test_shadda_on_vav_is_a_doubled_v(self):
        self.assertEqual(self.pn("اَوَّل"), "avval")
        self.assertEqual(self.pn("دُوّم"), "dovvom")
        self.assertEqual(self.pn("سَوّم"), "savvam")
        for w in ("اَوَّل", "دُوّم", "سَوّم"):
            self.assertNotIn("u", self.pn(w))
            self.assertNotIn("ow", self.pn(w))

    def test_kasra_before_final_he_does_not_make_an_audible_h(self):
        self.assertEqual(self.pn("خانِه"), "xAne")
        self.assertEqual(self.pn("تَغذیِه"), "taqzye")
        self.assertNotIn("h", self.pn("خانِه"))

    def test_final_he_after_a_long_vowel_is_still_an_h(self):
        self.assertEqual(self.pn("راه"), "rAh")

    def test_the_letter_the_owner_wrote_comes_back(self):
        pn = self.pn("چَغَر")
        self.assertEqual(P.to_respelling(P.parse(pn), q_letter=P.q_letter_for("چَغَر")), "چَغَر")
        self.assertEqual(P.to_respelling(P.parse(self.pn("قیمت")), q_letter=P.q_letter_for("قیمت"))[0], "ق")
        self.assertEqual(P.q_letter_for("چغر", "چَغَر"), "غ")
        self.assertEqual(P.q_letter_for("قغ"), "ق")

    def test_respell_token_keeps_the_brand_letter(self):
        t = next(x for x in toks("چغر") if x.text == "چغر")
        self.assertEqual(render.respell_token(t), "چَغَر")

    def test_shared_rows_show_the_brand_with_ghayn(self):
        row = next(r for r in D.all_shared_rows() if r["word"] == "چغر")
        self.assertIn("غ", row["respelling"])
        self.assertNotIn("ق", row["respelling"])


# ───────────────────────────────────────────────────────────── 7. lexicon coverage, version, eval set

class Coverage(unittest.TestCase):
    def test_new_common_words_are_known(self):
        for w in ("شو", "دیده", "محمد", "فاطمه", "علی", "حسین", "مردند", "گرفت", "مردم"):
            self.assertIsNotNone(D.Dictionary().lookup(w), w)

    def test_lexicon_has_no_errors(self):
        self.assertEqual(D.shared_errors(), [])

    def test_layer_has_a_version(self):
        self.assertRegex(fa_pron.VERSION, r"^\d{4}\.\d{2}\.\d{2}")

    def test_eval_set_is_append_only_and_has_the_new_categories(self):
        from services.audio.fa_pron import eval_set

        self.assertGreaterEqual(len(eval_set.SENTENCES), 270)
        for tag in ("ezw", "acro", "vh", "fmt"):
            self.assertTrue(eval_set.by_tag(tag), tag)
            self.assertIn(tag, eval_set.TAGS)
        # the first 230 are untouched: the old tags only
        old = {"ayn", "he", "vav", "ye", "ezafe", "num", "date", "price", "phone", "latin", "homo", "tashdid", "chagher", "fit",
               "punct", "mix"}
        self.assertTrue(all(t in old for t, _ in eval_set.SENTENCES[:230]))
        self.assertTrue(any("ه‌ی" in text for _, text in eval_set.SENTENCES), "a sentence with the everyday «ه‌ی» spelling")

    def test_every_new_eval_sentence_normalises_without_digits_or_latin_left(self):
        from services.audio.fa_pron import eval_set

        for tag, text in eval_set.SENTENCES[230:]:
            out = norm(text)
            self.assertNotRegex(out, r"[0-9A-Za-z]", f"{tag}: {out}")


# ───────────────────────────────────────────────────────────── 8. motion cues + hooks (pure helpers)

class Tidy(unittest.TestCase):
    def test_tags_in_the_middle_of_a_sentence(self):
        self.assertEqual(norm("قیمت <b>۲۵۰٬۰۰۰</b> تومان است"), "قیمت دویست و پنجاه هزار تومان است")


# ───────────────────────────────────────────────────────────── 9. «do no harm»: the voice's own front end has the last word on stress

class Reconcile(unittest.TestCase):
    NATIVE = {"برنامه": "barnˈɑmeː", "تمرینی": "tamrˈini", "کشتی": "keʃtˈi", "گرفت": "ɡerˈeft"}

    def native(self, word):
        return self.NATIVE.get(word, "")

    def test_same_segments_the_voices_own_string_is_used_untouched(self):
        self.assertEqual(P.reconcile_ipa("barnɑme", "barnˈɑmeː"), "barnˈɑmeː")
        self.assertEqual(P.reconcile_ipa("tamrini", "tamrˈini"), "tamrˈini")

    def test_different_segments_keep_ours_with_the_voices_stress(self):
        self.assertEqual(P.reconcile_ipa("kuːʃti", "keʃtˈi"), "kuːʃtˈi")
        self.assertEqual(P.reconcile_ipa("kuːʃti", "kˈeʃti"), "kˈuːʃti")

    def test_no_native_means_ours(self):
        self.assertEqual(P.reconcile_ipa("kuːʃti", ""), "kuːʃti")
        self.assertEqual(P.reconcile_ipa("kuːʃti", "ʃ"), "kuːʃti", "no stress mark in the native word: none added")

    def test_other_syllable_counts_use_the_distance_from_the_end(self):
        # native has 3 syllables, stress on the last; ours has 4: the stress goes on OUR last syllable
        self.assertEqual(P.with_stress_like("tamrinije", "tamrinˈi"), "tamrinijˈe".replace("ˈe", "ˈe"))

    def test_the_hybrid_render_keeps_what_the_voice_knows(self):
        out = piper("برنامه‌ی تمرینی", native=self.native)
        self.assertEqual(out.ipa, "barnˈɑmeːje tamrˈini")
        self.assertEqual(out.notes["reconciled_words"], 2)
        self.assertEqual(out.notes["native_words"], 0)

    def test_a_correction_keeps_its_segments_and_the_voices_stress(self):
        out = piper("او کشتی گرفت", native=self.native)
        self.assertIn("kuːʃtˈi", out.ipa)

    def test_a_failing_front_end_falls_back_to_our_own_stress(self):
        def boom(word):
            raise RuntimeError("no voice")

        out = piper("برنامه‌ی تمرینی", native=boom)
        self.assertTrue(out.ipa.startswith("barnɑmˈeje"), out.ipa)

    def test_the_node_gets_a_deferred_piece(self):
        out = piper("برنامه‌ی تمرینی", native=lambda w: "{{%s}}" % w)
        self.assertEqual(out.ipa, "{{برنامه|barnɑme}}je {{تمرینی|tamrini}}")

    def test_acronyms_are_never_overridden_by_the_voice(self):
        out = piper("خروجی PDF", native=lambda w: "pˈeːj" if w.startswith("پی") else "")
        self.assertIn("pˈiː dˈiː ˈɛf", out.ipa)


class DoubledYa(unittest.TestCase):
    """«رضایی»: a name or noun ending in «ایی» is the stem + ONE ی (it was read with the suffix twice: rezAyiyi)."""

    def test_one_suffix_only(self):
        for text in ("رضایی", "مهندس رضایی", "آقای رضایی"):
            t = [x for x in toks(text) if x.text == "رضایی"][0]
            self.assertEqual(t.pn, "rezAyi", text)

    def test_the_piper_phonemes_have_no_extra_syllable(self):
        self.assertNotIn("jiji", piper("مهندس رضایی").ipa)


class AcronymsAtEveryDepth(unittest.TestCase):
    """The voice's own front end reads the Persian spelling «پی‌دی‌اف» as the words «پی» and «دی» (measured: pˈej dˈej ˈef), so a text
    with a spelled-out acronym goes in as phonemes even at the default depth «normalize»; every other word stays the voice's own."""

    def test_normalize_depth_without_acronym_is_text_only(self):
        r = piper("برنامهٔ ورزشی برای هر روز", depth="normalize", native=lambda w: "<%s>" % w)
        self.assertEqual(r.ipa, "")
        self.assertEqual(r.ipa_sentences, [])
        self.assertTrue(r.text)

    def test_normalize_depth_with_acronym_gives_letters_and_native_words(self):
        r = piper("خروجی PDF را ببین", depth="normalize", native=lambda w: "<%s>" % w)
        self.assertEqual(r.ipa, "<خروجی> pˈiː dˈiː ˈɛf <را> <ببین>")
        self.assertEqual(r.notes["letter_words"], 1)

    def test_a_written_ezafe_is_handed_to_the_voice_untouched_at_normalize_depth(self):
        r = piper("برنامهٔ GPS", depth="normalize", native=lambda w: "<%s>" % w)
        self.assertIn("<برنامهٔ>", r.ipa)

    def test_a_store_word_for_the_acronym_wins(self):
        """The owner's own respelling of an acronym is never overridden by the letter names."""
        d = D.Dictionary(store={"پی‌دی‌اف": "pidief"})
        r = piper("خروجی PDF", depth="lexicon", dictionary=d)
        self.assertNotIn("pˈiː dˈiː", r.ipa)
        self.assertEqual(r.notes.get("letter_words", 0), 0)

    def test_without_a_voice_front_end_normalize_stays_text(self):
        r = piper("خروجی PDF", depth="normalize")
        self.assertEqual(r.ipa, "")

    def test_letters_ipa_needs_two_letter_names(self):
        self.assertIsNone(latin.letters_ipa("دی"))
        self.assertIsNone(latin.letters_ipa("پی‌گیری"))
        self.assertEqual(latin.letters_ipa("ام‌پی"), "ˈɛm pˈiː")

    def test_every_letter_ipa_symbol_is_in_the_voice_alphabet(self):
        """The Piper fa_IR voices share one broad IPA symbol set (checked against fa_IR-gyro-medium: all of these are in its phoneme map)."""
        ok = set("abcdefghijklmnopqrstuvwxyzɑɛɪʃʒˈˌː")
        for name, ipa in latin.LETTER_IPA.items():
            self.assertTrue(set(ipa.replace(" ", "")) <= ok, (name, ipa))
