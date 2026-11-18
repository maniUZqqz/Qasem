"""Round 5 (the second fix round of the review): the automatic ezafe after a determiner / time word, light verbs, nouns in a row; the normaliser
gaps (a spaced «×», English dates, fitness words); «سُبح» for Edge / MOSS; the lexicon table (Piper's own phonemes, every word once).

Pure Python (no voice, no node, no database): ``python -m unittest services.tests_fa_pron_round5`` from backend/.
"""
import importlib
import itertools
import pathlib
import re
import unittest

from services.audio import fa_pron
from services.audio.fa_pron import dictionary as D, ezafe, ezafe_data as L, ezafe_gold, g2p, latin, phones as P, pipeline

NM = importlib.import_module("services.audio.fa_pron.normalize")
render = importlib.import_module("services.audio.fa_pron.render")


def norm(text: str) -> str:
    return NM.normalize(text).text


def linked(text, round5=True):
    """The words of ``text`` that take an automatic ezafe (``round5=False`` = the rules as they ran until round 5)."""
    dic = D.Dictionary()
    prep = pipeline.prepare(text, depth="lexicon", dictionary=dic, ezafe=False)
    ezafe.mark_ezafe(prep.tokens, dic, round5=round5)
    return [t.text for t in prep.tokens if t.kind == "word" and t.ezafe and not t.written_ezafe and not t.ezafe_inside]


def piper(text, depth="lexicon"):
    return render.render_piper(pipeline.prepare(text, depth=depth)).ipa


# ───────────────────────────────────────────────────────────── 1. «هر روز آب بنوش»: a time word after a determiner is an adverb

class TimeWordsAfterADeterminer(unittest.TestCase):
    """The reviewer: «هر روز صبح آب گرم بنوش» was read «har ruːze sobh», «هیچ وقت تمرین را رها نکن» «vaq1te tamrin»: a time or counting word after
    هر / هیچ / چند / این / آن / همین / همه or a number says WHEN or HOW MANY; it is not the head of a genitive."""

    CASES = (
        ("هر روز صبح آب گرم بنوش.", "روز"), ("هر روز عصر پیاده‌روی کن.", "روز"), ("مادرم هر روز غذا درست می‌کند.", "روز"),
        ("مربی چغر هر روز پیام می‌فرستد.", "روز"), ("هر روز آب بنوش.", "روز"), ("هیچ وقت تمرین را رها نکن.", "وقت"),
        ("هر ساعت آب بنوش.", "ساعت"), ("چند روز غذا سالم بخور.", "روز"), ("هر وقت وقت داشتی تمرین کن.", "وقت"),
        ("آن روز تمرین را سبک گرفتم.", "روز"), ("هر لحظه آب بنوش.", "لحظه"), ("همه روز آب بنوش.", "روز"),
        ("هر روز من پیاده‌روی می‌کنم.", "روز"), ("هر روز او تمرین می‌کند.", "روز"), ("هیچ روز تمرین را فراموش نکن.", "روز"),
        ("هر وقت خسته‌ای نفس عمیق بکش.", "وقت"), ("هر زمان که خسته شدی استراحت کن.", "زمان"), ("هر هفته وزن خود را بسنج.", "هفته"),
    )

    def test_the_time_word_gets_no_ezafe(self):
        for text, word in self.CASES:
            self.assertNotIn(word, linked(text), text)

    def test_piper_and_the_text_engines_do_not_say_it(self):
        self.assertNotIn("ruːze", piper("هر روز صبح آب گرم بنوش."))
        self.assertNotIn("ruːze", piper("هر روز آب بنوش."))
        self.assertNotIn("vaq1te", piper("هیچ وقت تمرین را رها نکن."))
        self.assertNotIn("sɑʔate", piper("هر ساعت آب بنوش."))
        for engine in ("edge", "moss"):
            text = render.render_text(pipeline.prepare("هر روز آب بنوش.", depth="lexicon"), engine=engine).text
            self.assertNotIn("روزِ", text)

    def test_the_old_rules_did_say_it(self):
        """The «previous» column of the ezafe check is real: the round-4 rules really linked these."""
        for text, word in self.CASES[:8]:
            self.assertIn(word, linked(text, round5=False), text)

    def test_the_whole_grid_has_no_ezafe_on_a_time_or_amount_word(self):
        """The reviewer's scan: 9 determiners x the time / counting words x eight kinds of what follows."""
        dets = "هر هیچ این آن همین چند همه چندین بعضی".split()
        follow = ["آب بنوش", "غذا بخور", "من تمرین می‌کنم", "سالم است", "چغر را ببین", "کن", "تمرین را ثبت کن"]
        heads = list(L.TIME_WORDS) + list(L.AMOUNT_WORDS) + list(L.PART_WORDS)
        for d, h, f in itertools.product(dets, heads, follow):
            self.assertNotIn(h, linked(f"{d} {h} {f}"), f"{d} {h} {f}")

    def test_a_classifying_adjective_after_a_counting_word_still_links(self):
        for text, word in (("دو جلسه رایگان داریم.", "جلسه"), ("هر جلسه تمرینی را ثبت کن.", "جلسه")):
            self.assertIn(word, linked(text), text)

    def test_a_number_before_a_time_word_is_not_linked_either(self):
        for text, word in (("سه روز غذا سالم بخور.", "روز"), ("ده دقیقه آب بنوش.", "دقیقه"), ("پنج روز تمرین کن.", "روز"),
                           ("هفت روز غذا سالم بخور و بعد وزن کن.", "روز"), ("دو ساعت قبل از تمرین غذا نخور.", "ساعت")):
            self.assertNotIn(word, linked(text), text)

    def test_a_time_word_with_no_determiner_is_still_a_head(self):
        """«ساعتِ تمرین», «زمانِ تمرین», «وقتِ استراحت»: after «روز» or no word at all they are heads."""
        for text, word in (("ساعت تمرین را ثبت کن.", "ساعت"), ("هر روز زمان تمرین را ثبت کن.", "زمان"),
                           ("هر روز ساعت تمرین را ثبت کن.", "ساعت"), ("وقت استراحت را کم کن.", "وقت"),
                           ("اولین روز تمرین را سبک شروع کن.", "روز"), ("امروز روز پا است.", "روز")):
            self.assertIn(word, linked(text), text)

    def test_a_head_before_a_time_word_after_a_determiner_is_not_linked(self):
        self.assertNotIn("دوره", linked("این دوره ماه آینده شروع می‌شود."))

    def test_the_product_word_after_a_demonstrative_is_the_subject(self):
        self.assertNotIn("برنامه", linked("این برنامه غذا پیشنهاد می‌کند."))
        self.assertNotIn("بخش", linked("این بخش تمرین را توضیح می‌دهد."))
        self.assertIn("برنامه", linked("این برنامه ورزشی رایگان است."))       # with an adjective it is still «برنامهٔ ورزشی»
        self.assertIn("اپ", linked("این اپ چغر را نصب کن."))


# ───────────────────────────────────────────────────────────── 2. light verbs, nouns in a row, predicates

class LightVerbsAndPredicates(unittest.TestCase):
    def test_kand_is_the_verb(self):
        self.assertNotIn("عادت", linked("تا بدنت عادت کند."))
        self.assertIn("عادت", linked("تا بدنت عادت کند.", round5=False), "the round-4 rules read «کند» as the adjective «slow»")
        self.assertNotIn("ɑdate", piper("تا بدنت عادت کند."))

    def test_every_person_of_the_light_verbs(self):
        must = ("می‌دهیم", "می‌زند", "می‌کنیم", "می‌رساند", "نمی‌دهد", "ببر", "ببرید", "نکن", "بکنید", "بگذار", "نیاور", "بیاور", "کردند", "گرفتیم",
                "دارند", "ندارد", "داشتم", "کنند", "دهد", "شود", "کرده", "داشته")
        for w in must:
            self.assertTrue(ezafe._key(w) in ezafe._LIGHT_K, w)
        # a bare form that is also a noun / a preposition / colloquial speech is NOT a light verb on its own
        for w in ("زن", "ده", "بر", "برد", "نبرد", "نزد", "کش", "دار", "خور", "بریم"):
            self.assertFalse(ezafe._key(w) in ezafe._LIGHT_K, w)

    def test_the_reviewers_light_verb_sentences(self):
        for text, word in (("تمام حرکت‌ها را با فیلم نشان می‌دهیم.", "فیلم"), ("مصرف شکر زیاد به بدن آسیب می‌زند.", "بدن"),
                           ("از ورزش لذت ببر و از هدف غافل نشو.", "هدف"), ("همه به برنامه نیاز دارند.", "برنامه"),
                           ("بدن شما به این تمرین واکنش نشان می‌دهد.", "تمرین"), ("مربی به شما کمک می‌کند هدف را تعیین کنید.", "هدف")):
            self.assertNotIn(word, linked(text), text)

    def test_ordinary_links_before_a_verb_stay(self):
        for text, word in (("کیفیت تمرین تاثیر می‌گذارد.", "کیفیت"), ("برنامه تمرین را به شما تحویل می‌دهیم.", "برنامه"),
                           ("قیمت محصول را اعلام می‌کنیم.", "قیمت"), ("مصرف شکر به پوست آسیب می‌رساند.", "مصرف")):
            self.assertIn(word, linked(text), text)


class NounsInARowAndPredicates(unittest.TestCase):
    def test_the_object_of_the_verb_is_not_a_genitive(self):
        got = linked("برای ساخت عضله پروتئین کافی بخور.")
        self.assertIn("ساخت", got)
        self.assertNotIn("عضله", got)
        self.assertNotIn("عضله", linked("برای افزایش عضله پروتئین بخور."))
        self.assertIn("افزایش", linked("برای افزایش عضله پروتئین بخور."))

    def test_a_chain_of_genitives_still_links_when_it_closes(self):
        self.assertEqual(linked("مدیریت زمان تمرین را یاد بگیر."), ["مدیریت", "زمان"])
        self.assertEqual(linked("زمان تحویل سفارش دو روز است."), ["زمان", "تحویل"])
        self.assertEqual(linked("کیفیت خواب شما مهم است."), ["کیفیت", "خواب"])

    def test_an_ordinal_is_not_a_second_adjective(self):
        self.assertEqual(linked("خواب کافی اولین قدم برای ریکاوری است."), ["خواب"])
        self.assertEqual(linked("تغذیه سالم دومین قدم است."), ["تغذیه"])

    def test_a_comparative_before_az_is_the_predicate(self):
        self.assertEqual(linked("تمرین منظم بهتر از تمرین سنگین است."), ["تمرین"])
        self.assertEqual(linked("زمان تمرین مهم‌تر از مدت آن نیست."), ["زمان"])

    def test_a_superlative_stands_before_its_noun(self):
        self.assertEqual(linked("لحظه شروع سخت‌ترین لحظه است."), ["لحظه"])
        self.assertIn("برنامه", linked("بهترین برنامه تمرین همان است که به آن عمل می‌کنی."))

    def test_a_role_and_its_field_are_one_unit(self):
        self.assertEqual(linked("مربی تغذیه برنامه غذایی می‌نویسد."), ["برنامه"])
        self.assertIn("مشاور", linked("مشاور ورزشی برنامه تمرین می‌دهد."))

    def test_what_the_conservative_rules_always_kept(self):
        for text, word in (("برنامه ورزشی بساز.", "برنامه"), ("کتاب من روی میز است.", "کتاب"), ("اپ چغر را نصب کن.", "اپ"),
                           ("کاهش وزن با رژیم ممکن است.", "کاهش"), ("شهر تهران پر از زندگی است.", "شهر"),
                           ("چند تمرین ساده را امتحان کن.", "تمرین"), ("در هفته اول با وزنه سبک شروع کن.", "هفته"),
                           ("هر ورزشکار برنامه خودش را دارد.", "برنامه")):
            self.assertIn(word, linked(text), text)

    def test_what_it_never_links(self):
        for text, word in (("با چغر برنامه بساز.", "چغر"), ("علی کتاب می‌خواند.", "علی"), ("مربی برنامه می‌نویسد.", "مربی"),
                           ("دکتر علی رضایی", "دکتر"), ("برنامه عالی است.", "برنامه")):
            self.assertNotIn(word, linked(text), text)


# ───────────────────────────────────────────────────────────── 3. the numbers: four sets, three algorithms

class GoldSetsRound5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = {}
        for key, _name, _label, text_name in ezafe_gold.SET_DEFS:
            for which, _en, fn in ezafe_gold.mark_functions():
                cls.table[(key, which)] = ezafe_gold.measure(fn, text=ezafe_gold.set_text(text_name))

    def test_the_four_sets_and_their_sizes(self):
        self.assertEqual([d[0] for d in ezafe_gold.SET_DEFS], ["main", "heldout", "det", "det_heldout"])
        self.assertGreaterEqual(self.table[("det", "after")]["sentences"], 140)
        self.assertGreaterEqual(self.table[("det_heldout", "after")]["sentences"], 70)
        self.assertGreaterEqual(sum(self.table[(k, "after")]["sentences"] for k in ("main", "heldout", "det", "det_heldout")), 480)

    def test_every_gold_mark_sits_on_a_word_of_its_sentence(self):
        for text in (ezafe_gold.DET_TEXT, ezafe_gold.DET_HELDOUT_TEXT):
            for _cat, sentence, marked in ezafe_gold.parse_gold(text):
                keys = [ezafe_gold._norm(w.strip("،.؟!:؛")) for w in sentence.split()]
                for key, n in marked:
                    self.assertGreaterEqual(keys.count(key), n, (sentence, key))

    def test_the_round_5_rules_make_no_wrong_ezafe_on_the_new_sets(self):
        for key in ("det", "det_heldout"):
            after = self.table[(key, "after")]
            self.assertEqual(after["wrong"], 0, after["wrong_rows"])
            self.assertEqual(after["precision"], 1.0)

    def test_the_old_rules_did_make_them(self):
        for key in ("det", "det_heldout"):
            self.assertGreaterEqual(self.table[(key, "previous")]["wrong"], 20 if key == "det" else 3)
            self.assertLess(self.table[(key, "after")]["wrong"] * 5, self.table[(key, "previous")]["wrong"] + 1)

    def test_no_loosening_of_the_older_sets(self):
        """The lead: «do not loosen any other rule». On the two older sets the new rules say nothing new that is wrong, and lose at most one ezafe."""
        for key in ("main", "heldout"):
            before, after = self.table[(key, "previous")], self.table[(key, "after")]
            self.assertLessEqual(after["wrong"], before["wrong"])
            self.assertLessEqual(after["predicted"], before["predicted"])
            self.assertLessEqual(before["correct"] - after["correct"], 1)

    def test_recall_stays_useful(self):
        self.assertGreaterEqual(self.table[("det", "after")]["recall"], 0.7)
        self.assertGreaterEqual(self.table[("det_heldout", "after")]["recall"], 0.65)

    def test_the_previous_column_is_the_algorithm_that_ran_until_now(self):
        """``round5=False`` still reproduces the numbers of the live round-4 rules (main set: 146 said, 43 missing)."""
        main = self.table[("main", "previous")]
        self.assertEqual((main["predicted"], main["wrong"], main["missing"]), (146, 0, 43))
        held = self.table[("heldout", "previous")]
        self.assertEqual((held["predicted"], held["wrong"], held["missing"]), (41, 1, 17))

    def test_the_report_prints_all_sets_and_algorithms(self):
        text = ezafe_gold.report()
        for name in ("main set before", "held-out set previous", "determiner set after", "determiner held-out set after"):
            self.assertIn(name, text)

    def test_the_documentation_table_is_the_live_table(self):
        """The doc once said 145 / 44 / 76.7% while the panel computed 146 / 43 / 77.2%: the docs table is generated from the same code and this test
        fails when the markdown page is not the table the code prints."""
        doc = pathlib.Path(__file__).resolve().parents[2] / "docs" / "pronunciation" / "ezafe-fa.md"
        if not doc.exists():
            self.skipTest("docs are not shipped in this tree")
        text = doc.read_text(encoding="utf-8")
        for line in ezafe_gold.docs_table().splitlines():
            self.assertIn(line, text, "docs/pronunciation/ezafe-fa.md is out of date: regenerate its table with ezafe_gold.docs_table()")


# ───────────────────────────────────────────────────────────── 4. the normaliser

class NormaliserRound5(unittest.TestCase):
    def test_a_spaced_multiplication_sign_is_said(self):
        self.assertEqual(norm("۴ ست × ۱۲ تکرار"), "چهار ست در دوازده تکرار")
        self.assertEqual(norm("۴×۱۲"), "چهار در دوازده")
        self.assertEqual(norm("4 sets x 12 reps"), "چهار ست در دوازده تکرار")
        self.assertEqual(norm("۳ × ۴ = ۱۲"), "سه در چهار مساوی دوازده")
        self.assertNotIn("×", norm("ست × تکرار"))

    def test_english_dates(self):
        self.assertEqual(norm("Nov 18"), "هجدهم نوامبر")
        self.assertEqual(norm("Dec 5"), "پنجم دسامبر")
        self.assertEqual(norm("November 18th, 2026"), "هجدهم نوامبر" + NM.KASRA + " دو هزار و بیست و شش")
        self.assertEqual(norm("18 Nov 2026"), norm("November 18, 2026"))
        self.assertEqual(norm("Oct. 3"), "سوم اکتبر")
        self.assertEqual(norm("نوامبر ۲۰۲۶"), "نوامبر دو هزار و بیست و شش")

    def test_an_english_word_that_looks_like_a_month_is_left_alone(self):
        self.assertNotIn("هجدهم", norm("Marathon 18 km"))
        self.assertNotIn("نوامبر", norm("a decent plan"))
        self.assertEqual(norm("Nov 45"), norm("Nov") + " چهل و پنج")           # not a day of a month

    FITNESS = {"Zumba": "زومبا", "Lunge": "لانج", "lunges": "لانج‌ها", "Burpee": "برپی", "kettlebell": "کتل‌بل", "Crunch": "کرانچ", "Tabata": "تاباتا",
               "Spinning": "اسپینینگ", "aerobics": "ایروبیک", "Stretching": "استرچینگ", "Sit-up": "سیت‌آپ", "Push-ups": "شنا", "Pull-ups": "بارفیکس",
               "whey": "وی", "BCAA": "بی‌سی‌ای‌ای", "keto": "کتو", "smoothie": "اسموتی", "Sprint": "اسپرینت", "Marathon": "ماراتن",
               "Warm-up": "وارم‌آپ", "macros": "ماکروها", "creatine": "کراتین", "Monday": "دوشنبه", "November": "نوامبر", "Dec": "دسامبر"}

    def test_the_fitness_words_are_not_guessed(self):
        for word, want in self.FITNESS.items():
            res = NM.normalize(f"کلاس {word} امروز")
            self.assertIn(want.replace("‌", "‌"), res.text.replace("‌", "‌"), word)
            self.assertEqual(res.notes.latin_guesses, [], word)

    def test_every_new_word_is_readable_by_the_phonetic_layer(self):
        for key in ("zumba", "lunge", "burpee", "kettlebell", "crunch", "tabata", "spinning", "aerobic", "stretching", "rowing", "kickboxing",
                    "sit-up", "pushups", "leg", "chest", "shoulder", "curl", "pulldown", "superset", "dropset", "pump", "tempo", "interval",
                    "sprint", "jogging", "marathon", "warm-up", "cool-down", "cheat", "meal", "prep", "macro", "carb", "whey", "creatine",
                    "bcaa", "keto", "vegan", "detox", "smoothie", "shake", "snack", "gluten", "organic", "january", "september", "dec"):
            spoken = latin.LATIN_WORDS[key]
            prep = pipeline.prepare(spoken, depth="full")
            self.assertEqual(prep.unknown, [], (key, spoken))


# ───────────────────────────────────────────────────────────── 5. «صبح» for Edge and MOSS

class RespellingOfAFinalH(unittest.TestCase):
    def test_sobh_is_not_written_with_a_final_he(self):
        self.assertEqual(P.to_respelling(P.parse("sobh")), "سُبح")
        self.assertEqual(P.to_respelling(P.parse("fath")), "فَتح")
        text = render.render_text(pipeline.prepare("هر روز صبح", depth="lexicon"), engine="edge").text
        self.assertIn("سُبح", text)
        self.assertNotIn("سُبه", text)

    def test_a_he_after_a_vowel_or_inside_a_word_stays(self):
        for pn, want in (("mAh", "ماه"), ("rAh", "راه"), ("sohbat", "سُهبَت"), ("hAl", "هال")):
            self.assertEqual(P.to_respelling(P.parse(pn)), want)

    def test_no_lexicon_word_ends_in_he_after_a_consonant(self):
        for e in D.shared_entries():
            toks = P.strip_stress(P.parse(e.pn))
            if len(toks) >= 2 and toks[-1] == "h" and toks[-2] in P.CONSONANTS:
                self.assertTrue(P.to_respelling(toks).endswith("ح"), e.word)

    def test_the_owner_can_type_the_same_letter_back(self):
        self.assertEqual(P.parse(g2p.respelling_to_pn("سُبح")), P.parse("sobh"))


# ───────────────────────────────────────────────────────────── 6. the lexicon table

class SharedLexiconTable(unittest.TestCase):
    def test_every_word_is_listed_once(self):
        rows = D.all_shared_rows()
        words = [r["word"] for r in rows]
        marked = [w for w in words if any(c in D.MARKS for c in w)]
        plain = [D.canon(w).replace("‌", "") for w in words if w not in marked]
        self.assertEqual(len(plain), len(set(plain)), "a word appears twice")
        self.assertEqual(len(rows), len(D.shared_entries()))
        self.assertLess(len(D.shared_entries()), len(D.shared()), "the lookup table holds the half-space variants as well")
        for w in ("سی‌ام", "علاقه‌مند", "برنامه‌ها", "می‌خواهم"):
            self.assertEqual(words.count(w), 1, w)

    def test_the_ipa_column_is_what_piper_receives(self):
        rows = {r["word"]: r for r in D.all_shared_rows()}
        self.assertEqual(rows["چهار"]["ipa"], "tʃahɑr")
        self.assertEqual(rows["عالی"]["ipa"], "ɑli")
        self.assertEqual(rows["چهار"]["ipa_ssml"], P.to_ssml_ipa(P.parse(rows["چهار"]["pn"])))
        self.assertNotEqual(rows["چهار"]["ipa"], rows["چهار"]["ipa_ssml"])
        for word in ("چهار", "عالی", "معنی", "ساعت", "ورزش", "خواهر", "مدرسه", "علاقه‌مند", "اشتراک", "مسئول"):
            row = rows[word]
            sent = render.render_piper(pipeline.prepare(word, depth="lexicon")).ipa
            self.assertEqual(sent.replace("ˈ", "").replace("ˌ", ""), row["ipa"], word)

    def test_the_count_in_the_overview_is_the_unique_count(self):
        self.assertEqual(len(D.shared_entries()), len(D.all_shared_rows()))
        self.assertGreaterEqual(len(D.shared_entries()), 1100)

    def test_a_lexicon_word_is_still_found_by_its_other_spelling(self):
        d = D.Dictionary()
        self.assertIsNotNone(d.lookup("چربی‌سوزی"))
        self.assertIsNotNone(d.lookup("چربیسوزی"))


class LayerVersion(unittest.TestCase):
    def test_the_version_moved(self):
        self.assertGreaterEqual(fa_pron.VERSION, "2026.11.18.1")
        self.assertTrue(re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+", fa_pron.VERSION))
