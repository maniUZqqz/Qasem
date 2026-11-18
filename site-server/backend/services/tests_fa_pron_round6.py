"""Round 6 (a quick fix after the live review of v3.54): «بهتر / بهترین / بهتری / بهتره» were split into the preposition «به» + «تر» (betar: Piper lost
its h, Edge / MOSS got «بِتَر»); control characters (a NUL made Piper fail with an English message); «دکتر تغذیه برنامه ...» got «تغذیهٔ».

Pure Python (no voice, no node, no database): ``python -m unittest services.tests_fa_pron_round6`` from backend/.
"""
import importlib
import tempfile
import unittest
from pathlib import Path

from services.audio import fa_pron, tts
from services.audio.fa_pron import dictionary as D, ezafe, phones as P, pipeline

NM = importlib.import_module("services.audio.fa_pron.normalize")
render = importlib.import_module("services.audio.fa_pron.render")

STRESS = "ˈ"


def norm(text: str) -> str:
    return NM.normalize(text).text


def piper(text, depth="lexicon", **opts):
    return render.render_piper(pipeline.prepare(text, depth=depth), **opts).ipa


def plain(text, depth="lexicon"):
    return render.render_text(pipeline.prepare(text, depth=depth), engine="moss").text


def edge_ssml(text, depth="lexicon"):
    return render.render_edge(pipeline.prepare(text, depth=depth)).ssml


def words_of(text, depth="lexicon"):
    return [t for t in pipeline.prepare(text, depth=depth).tokens if t.kind == "word"]


def linked(text):
    dic = D.Dictionary()
    prep = pipeline.prepare(text, depth="lexicon", dictionary=dic, ezafe=False)
    ezafe.mark_ezafe(prep.tokens, dic)
    return [t.text for t in prep.tokens if t.kind == "word" and t.ezafe and not t.written_ezafe and not t.ezafe_inside]


# ───────────────────────────────────────────────────────────── 1. «بهتر» is one word

class BehtarIsNotBePlusTar(unittest.TestCase):
    FAMILY = {"بهتر": "behtar", "بهترین": "behtarin", "بهتری": "behtari", "بهتره": "behtare", "بهترها": "behtarhA", "بهترین‌ها": "behtarinhA",
              "بهترم": "behtaram", "بهتریم": "behtarim", "بهترید": "behtarid", "بهترند": "behtarand"}

    def test_the_family_has_its_own_lexicon_entry(self):
        dic = D.Dictionary()
        for word, pn in self.FAMILY.items():
            e = dic.lookup(word)
            self.assertIsNotNone(e, word)
            self.assertEqual((e.pn, e.source, e.safe), (pn, "shared", False), word)

    def test_the_spelling_with_a_half_space_is_the_same_word(self):
        dic = D.Dictionary()
        for written, pn in (("به‌تر", "behtar"), ("به‌ترین", "behtarin"), ("به‌تری", "behtari"), ("بهتر‌ها", "behtarhA")):
            self.assertEqual(dic.lookup(written).pn, pn, written)
            (tok,) = words_of(written)
            self.assertEqual(tok.pn, pn, written)

    def test_morphology_never_splits_it(self):
        dic = D.Dictionary()
        for word in list(self.FAMILY) + ["بهی", "بهین", "بهان", "بهات", "به‌تر", "به‌ترین", "به‌ی"]:
            m = pipeline._morph(word, dic)
            self.assertTrue(m is None or m.startswith("beht"), (word, m))
        # ... also without any lexicon entry for the whole word: the preposition is no stem
        for word in ("بهی", "بهین", "بهان", "بهات"):
            self.assertIsNone(pipeline._morph(word, dic), word)
        self.assertEqual(pipeline._morph("به‌کار", dic), "bekAr")                                 # a real compound is still read as one

    def test_a_real_suffix_on_a_real_stem_still_works(self):
        for word, pn in (("کتاب‌ها", "ketAbhA"), ("برنامه‌ای", "barnAmeyi"), ("مربیان", "morabbiyAn"), ("سنگین‌تر", "sangintar"),
                         ("سنگین‌ترین", "sangintarin"), ("برتر", "bartar")):
            self.assertEqual(pipeline._morph(word, D.Dictionary()), pn, word)

    def test_piper_gets_the_h(self):
        for text, want in (("این برنامه بهترین انتخاب است", "behtarin"), ("حالت بهتر می‌شود", "behtar"), ("امروز بهتری؟", "behtari"),
                           ("بهتره شروع کنی", "behtare")):
            ipa = piper(text).replace(STRESS, "")
            self.assertIn(want, ipa, text)
            self.assertNotIn("betar", ipa, text)
        # with the voice's own front end present (the real call): its segments are replaced by ours, and the h is there
        native = lambda w: {"بهترین": "bɛtˈɑɾin", "بهتر": "bɛtˈɑɾ"}.get(w, "‹" + w + "›")
        for text, want in (("این برنامه بهترین انتخاب است", "behtarin"), ("حالت بهتر می‌شود", "behtar")):
            ipa = render.render_piper(pipeline.prepare(text, depth="lexicon"), native_ipa=native).ipa.replace(STRESS, "")
            self.assertIn(want, ipa, text)
            self.assertNotIn("betar", ipa, text)

    def test_piper_input_has_the_beh_syllable_at_every_depth_that_has_phonemes(self):
        for depth in ("lexicon", "full"):
            self.assertIn("beh", piper("این برنامه بهترین انتخاب است", depth=depth))
        self.assertIn("beh", piper("حالت بهتر می‌شود"))

    def test_edge_and_moss_respelling_keeps_the_he(self):
        for text, want, bad in (("این برنامه بهترین انتخاب است", "بِهتَرین", "بِتَرین"), ("حالت بهتر می‌شود", "بِهتَر", "بِتَر"),
                                ("بهتره", "بِهتَره", "بِتَره")):
            for engine_text in (plain(text), edge_ssml(text)):
                self.assertIn(want, engine_text, text)
                self.assertNotIn(bad, engine_text, text)
        t = [t for t in words_of("بهترین") if t.text == "بهترین"][0]
        self.assertEqual(render.respell_token(t), "بِهتَرین")
        self.assertEqual(P.to_respelling(P.parse("behtar")), "بِهتَر")

    def test_the_layer_off_depths_are_untouched(self):
        # normalize: the voice reads the text itself; nothing of ours is said
        self.assertEqual(norm("بهترین انتخاب"), "بهترین انتخاب")
        self.assertEqual(piper("بهترین انتخاب", depth="normalize"), "")

    def test_the_ezafe_decisions_did_not_move(self):
        self.assertEqual(linked("حالت بهتر می‌شود."), [])
        self.assertEqual(linked("تمرین منظم بهتر از تمرین سنگین است."), ["تمرین"])
        self.assertIn("برنامه", linked("بهترین برنامه تمرین همان است که به آن عمل می‌کنی."))
        self.assertEqual(linked("ورزش منظم سلامت قلب را بهتر می‌کند."), ["ورزش", "سلامت"])

    def test_the_preposition_itself_is_unchanged(self):
        self.assertEqual([t.pn for t in words_of("به خانه")], ["be", "xAne"])
        self.assertEqual([t.pn for t in words_of("به خاطر")], ["be", "xAter"])
        self.assertIn("be", piper("به خانه می‌روم").replace(STRESS, ""))


# ───────────────────────────────────────────────────────────── 2. the other «به»- words

class OtherBeWords(unittest.TestCase):
    #: written -> (PN at depth «full», what the h must look like in a respelling)
    WORDS = {"بهداشت": "behdASt", "بهداشتی": "behdASti", "بهار": "bahAr", "بهاری": "bahAri", "بهره": "bahre", "بهانه": "bahAne", "بهمن": "bahman",
             "بهشت": "beheSt", "بهشتی": "beheSti", "بهینه": "behine", "بهبود": "behbud", "بهبودی": "behbudi", "بهزیستی": "behzisti",
             "بهسازی": "behsAzi", "بهنام": "behnAm", "بهروز": "behruz", "به‌روز": "behruz", "بهرام": "bahrAm", "بهزاد": "behzAd",
             "اردیبهشت": "ordibeheSt"}

    def test_the_full_depth_reads_every_one_right(self):
        for word, pn in self.WORDS.items():
            (tok,) = words_of(word, depth="full")
            self.assertEqual(tok.pn, pn, word)

    def test_no_one_is_read_as_the_preposition_plus_something(self):
        for word in self.WORDS:
            for depth in ("lexicon", "full"):
                for tok in words_of(word, depth=depth):
                    self.assertFalse(tok.pn and tok.pn.startswith("be") and not tok.pn.startswith("beh"), (word, depth, tok.pn))

    def test_the_text_engines_keep_the_he(self):
        for word in self.WORDS:
            for tok in words_of(word, depth="full"):
                spelled = render.respell_token(tok)
                self.assertIn("ه", spelled, (word, spelled))
                if word.startswith("ب"):
                    self.assertIn("ه", spelled[:3], (word, spelled))          # «بِهتَر» / «بَهار»: the he is the second letter

    def test_lexicon_depth_gives_the_beh_words_to_piper_and_leaves_the_bah_words_to_the_voice(self):
        # the «beh» words are the lexicon's (the voice and the letter rules disagree), the «bah» words are read right by both
        for word, pn in (("بهداشت", "behdASt"), ("بهشت", "beheSt"), ("بهینه", "behine"), ("بهبود", "behbud")):
            (tok,) = words_of(word)
            self.assertEqual((tok.pn, tok.apply), (pn, True), word)
        for word in ("بهار", "بهره", "بهانه"):
            (tok,) = words_of(word)
            self.assertIsNone(tok.pn, word)

    def test_every_new_lexicon_line_is_valid(self):
        self.assertEqual(D.shared_errors(), [])
        cats = {e.category for e in D.shared_entries() if e.word == "بهتر"}
        self.assertEqual(len(cats), 1)


# ───────────────────────────────────────────────────────────── 3. control characters

class ControlCharacters(unittest.TestCase):
    def test_nul_is_removed(self):
        self.assertEqual(norm("سلام\x00 برنامه"), "سلام برنامه")
        self.assertEqual(norm("برنا\x00مه"), "برنامه")
        self.assertEqual(norm("\x00سلام\x00"), "سلام")

    def test_every_c0_control_except_tab_and_newline_is_gone(self):
        for code in list(range(0x20)) + [0x7f] + list(range(0x80, 0xa0)):
            out = norm("الف" + chr(code) + "ب")
            for ch in out:
                self.assertTrue(ch in "\n\t" or ord(ch) >= 0x20 and not 0x7f <= ord(ch) < 0xa0, (hex(code), repr(out)))
            self.assertIn("الف", out)
            self.assertIn("ب", out)

    def test_line_breaks_and_tabs_still_work(self):
        self.assertEqual(norm("سلام\r\nبرنامه"), "سلام\nبرنامه")
        self.assertEqual(norm("سلام\rبرنامه"), "سلام\nبرنامه")
        self.assertEqual(norm("سلام\nبرنامه"), "سلام\nبرنامه")
        self.assertEqual(norm("سلام\tبرنامه"), "سلام برنامه")
        self.assertEqual(norm("سلام\x0bبرنامه"), "سلام\nبرنامه")

    def test_the_strip_function_alone(self):
        self.assertEqual(NM.strip_controls("a\x00b\x01c\x1fd\te\nf\x7fg"), "abcd\te\nfg")
        self.assertEqual(NM.strip_controls(""), "")

    def test_it_is_idempotent(self):
        once = norm("سلام\x00 ۳ جلسه\x07 تمرین!")
        self.assertEqual(norm(once), once)

    def test_the_pronunciation_layer_hands_no_control_character_to_any_engine(self):
        text = "سلام\x00 برنامه\x01 بهترین\x1f انتخاب است"
        outputs = [piper(text), plain(text), edge_ssml(text), pipeline.prepare(text).normalized]
        for out in outputs:
            self.assertFalse([c for c in out if ord(c) < 0x20 and c not in "\n\t"], repr(out))
        self.assertIn("behtarin", piper(text).replace(STRESS, ""))

    def test_a_text_of_only_controls_has_nothing_to_speak(self):
        self.assertFalse(tts.is_speakable("\x00\x00"))
        self.assertFalse(tts.is_speakable("\x00 ... \x01"))
        self.assertTrue(tts.is_speakable("سلام\x00"))

    def test_every_engine_gets_the_text_without_them(self):
        """The guard around ``synthesize``: also the «before» recording (layer off) and an engine that never calls the layer."""
        seen = []

        class Probe(tts.BaseTTSProvider):
            name = "probe"

            def synthesize(self, text, out_path):
                seen.append(text)
                return out_path

        with tempfile.TemporaryDirectory() as tmp:
            Probe().synthesize("سلام\x00 برنامه\x01 تمرینی", Path(tmp) / "a.wav")
        self.assertEqual(seen, ["سلام برنامه تمرینی"])
        with self.assertRaises(tts.NothingToSpeakError):
            Probe().synthesize("\x00\x00", "unused.wav")
        self.assertEqual(len(seen), 1)


# ───────────────────────────────────────────────────────────── 4. «دکتر تغذیه برنامه ...»

class TitleAndField(unittest.TestCase):
    def test_the_field_after_a_title_gets_no_ezafe(self):
        for role in ("دکتر", "پزشک", "کارشناس", "مشاور", "متخصص", "مربی", "روانشناس", "فیزیوتراپیست", "درمانگر", "استاد"):
            self.assertNotIn("تغذیه", linked(f"{role} تغذیه برنامه می‌نویسد."), role)
            self.assertNotIn("تغذیه", linked(f"{role} سلامت برنامه می‌نویسد."), role)

    def test_the_sentence_of_the_review(self):
        text = "دکتر تغذیه برنامه می‌نویسد"
        ipa = piper(text).replace(STRESS, "")
        self.assertNotIn("taq1zijeje", ipa)           # the ezafe on a word that already ends in «e»
        self.assertIn("taq1zije", ipa)
        for engine_text in (plain(text, depth="lexicon"), edge_ssml(text)):
            self.assertNotIn("تَغزییه‌یِ", engine_text)
            self.assertNotIn("تغذیهٔ", engine_text)
        self.assertEqual(linked(text), [])

    def test_the_phrase_after_the_field_still_links_like_with_a_coach(self):
        self.assertEqual(linked("مربی تغذیه برنامه غذایی می‌نویسد."), ["برنامه"])
        self.assertEqual(linked("دکتر تغذیه برنامه غذایی می‌نویسد."), ["برنامه"])
        self.assertIn("مشاور", linked("مشاور ورزشی برنامه تمرین می‌دهد."))

    def test_a_title_with_a_name_and_other_links_are_unchanged(self):
        self.assertNotIn("دکتر", linked("دکتر علی رضایی"))
        self.assertEqual(linked("برنامه تغذیه جدید بساز."), ["برنامه"])
        self.assertEqual(linked("مشاور ورزشی برنامه تمرین می‌دهد."), ["مشاور"])

    def test_the_role_list_only_grew(self):
        # the full check (4 gold sets x 3 algorithms) is in tests_fa_pron_round5 / apps.pronunciation.tests_round5; a role word only BLOCKS
        old = ezafe._set("مربی مشاور متخصص کارشناس پزشک معلم استاد مدرس".split())
        self.assertTrue(old <= ezafe._ROLES)
        self.assertIn(ezafe._key("دکتر"), ezafe._ROLES)


class LayerVersionRound6(unittest.TestCase):
    def test_the_version_moved(self):
        parts = tuple(int(x) for x in fa_pron.VERSION.split("."))
        self.assertGreaterEqual(parts, (2026, 11, 18, 2))
