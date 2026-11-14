"""The director's default reel title (audit 2026-11-14): never a library label, never cut in the middle of a word, the prompt and the
shop's name come before a media label, and the rubric flags a title that still looks like a file label."""
from django.test import SimpleTestCase

from services.editing.director import brief as B
from services.editing.director import critique
from services.editing.director import projectops as ops
from services.editing.director.runner import apply_steps
from services.tests_director import ASSETS, analyze, fake_ctx, run_tool, with_clip

LIB = "برنامهٔ ورزشی + غذایی با هوش مصنوعی — عکس"          # «<product> — <kind>» exactly as the media bin names it
SLIDE = "معرفی کاروسل: هزینه‌ها چقدر است؟ — اسلاید 1"


def asset(title, kind="image", ref="gimg:1"):
    return {"ref": ref, "title": title, "kind": kind, "duration": 0.0, "has_audio": False, "width": 1080, "height": 1350}


class CleanNameTests(SimpleTestCase):
    def test_the_library_suffix_and_the_dash_are_dropped_and_nothing_is_cut_mid_word(self):
        name = B._clean_name(LIB)
        self.assertEqual(name, "برنامهٔ ورزشی + غذایی")
        self.assertNotIn("—", name)
        self.assertFalse(B.title_problem(name))

    def test_a_slide_label_gives_the_clause_before_the_colon(self):
        self.assertEqual(B._clean_name(SLIDE), "معرفی کاروسل")
        self.assertEqual(B._clean_name("چغر — اسلاید ۳"), "چغر")
        self.assertEqual(B._clean_name("کرم مرطوب‌کننده — پوستر تبلیغاتی"), "کرم مرطوب‌کننده")
        self.assertEqual(B._clean_name("کفش ورزشی (تدوین‌شده)"), "کفش ورزشی")
        self.assertEqual(B._clean_name("بسته‌بندی (۹:۱۶ — ۱۰۸۰×۱۹۲۰)"), "بسته‌بندی")

    def test_file_names_and_placeholders_are_not_names(self):
        for label in ("IMG_2031.mp4", "rev_talk_test_1.mp4", "VID 20231012", "ویدیو 23", "عکس ۲", "photo 5", "2031", "", None):
            self.assertEqual(B._clean_name(label), "", label)

    def test_long_names_are_cut_between_words_at_a_clause(self):
        for text in ("برنامهٔ ورزشی و تغذیه‌ای شخصی‌سازی‌شده با هوش مصنوعی برای کاهش وزن سریع", LIB, "یک دو سه چهار پنج شش هفت هشت نه ده"):
            out = B._clean_name(text)
            self.assertLessEqual(len(out), 34, out)
            self.assertFalse(B.title_problem(out), out)
            self.assertTrue(text.startswith(out.split()[0]), out)
            for tok in out.split():
                self.assertIn(tok, text.split(), f"{tok} is a whole word of the source")


class PromptPhraseTests(SimpleTestCase):
    def test_the_name_in_the_sentence(self):
        self.assertEqual(B.phrase_from_prompt("یک ریلز ۱۵ ثانیه‌ای برای معرفی چغر بساز"), "چغر")
        self.assertEqual(B.phrase_from_prompt("ویدیو برای اپلیکیشن چغر با موسیقی شاد"), "چغر")
        self.assertEqual(B.phrase_from_prompt("تبلیغ کفش ورزشی نایک، سریع"), "کفش ورزشی نایک")
        self.assertEqual(B.phrase_from_prompt("make a reel about Chagher fitness app"), "Chagher fitness app")

    def test_a_sentence_without_a_name_gives_nothing(self):
        for text in ("", "ریلز ۲۰ ثانیه‌ای", "یک ریلز برای حراج ۳۰٪ تخفیف", "برای ۱۵ ثانیه", "جعبه‌گشایی برای ریلز", "قبل و بعد"):
            self.assertEqual(B.phrase_from_prompt(text), "", text)


class FinishBriefTitleTests(SimpleTestCase):
    def fin(self, assets, request="", store="", **brief):
        return B.finish_brief({**B.parse_prompt(request, assets=assets), **brief}, assets, request=request, store_name=store)

    def test_a_library_label_never_reaches_the_screen(self):
        b = self.fin([asset(LIB)])
        self.assertEqual(b["title"], "معرفی برنامهٔ ورزشی + غذایی")
        self.assertNotIn("عک", b["title"].split()[-1:])
        b = self.fin([asset(SLIDE)])
        self.assertEqual(b["title"], "معرفی کاروسل")                  # not «معرفی معرفی …»
        self.assertFalse(B.title_problem(b["title"]))

    def test_the_prompt_comes_before_the_media_label(self):
        b = self.fin([asset(SLIDE)], request="یک ریلز برای معرفی چغر بساز", store="فروشگاه ما")
        self.assertEqual(b["title"], "معرفی چغر")

    def test_then_the_product_then_the_shop(self):
        self.assertEqual(self.fin([asset("چای سبز", "video", "video:1")], store="چغر")["title"], "معرفی چای سبز")
        self.assertEqual(self.fin([asset("IMG_2031.mp4", "video", "video:1")], store="چغر")["title"], "معرفی چغر")
        self.assertEqual(self.fin([asset("ویدیو 3", "video", "video:1")], store="")["title"], "معرفیِ محصول")
        b = self.fin([asset("IMG_2031.mp4", "video", "video:1")], request="جعبه‌گشایی", store="چغر")
        self.assertEqual((b["recipe"], b["title"]), ("unboxing", "جعبه‌گشایی چغر"))

    def test_a_second_asset_is_used_when_the_first_has_no_name(self):
        b = self.fin([asset("IMG_2031.mp4", "video", "video:1"), asset("کرم دست — عکس", ref="pimg:4")])
        self.assertEqual(b["title"], "معرفی کرم دست")

    def test_what_the_owner_typed_is_kept_but_a_label_title_is_replaced(self):
        self.assertEqual(self.fin([asset(LIB)], request="ریلز «تخفیف زمستانی»")["title"], "تخفیف زمستانی")
        b = self.fin([asset("چغر", "video", "video:1")], title="معرفی برنامهٔ ورزشی + غذایی با هوش مصنوعی — عک")
        self.assertEqual(b["title"], "معرفی چغر")
        self.assertTrue(any("تیترِ تازه" in n for n in b["notes"]))

    def test_other_recipes_keep_their_titles(self):
        self.assertEqual(self.fin([asset(LIB)], request="تخفیف ۳۰٪")["title"], "30٪ تخفیف ویژه")        # (the sale title has always used the parsed number)
        self.assertEqual(self.fin([asset(LIB)], request="قبل و بعد")["title"], "قبل و بعد")
        self.assertEqual(self.fin([asset(LIB)], request="نظر مشتری")["title"], "نظرِ مشتریان")


class TitleProblemTests(SimpleTestCase):
    def test_the_old_mid_word_cut_and_labels_are_caught(self):
        for bad in ("معرفی برنامهٔ ورزشی + غذایی با هوش مصنوعی — عک", "معرفی کاروسل — اسلاید 1", "x — عکس", "چغر — پوستر تبلیغاتی", "IMG_2031.mp4", "rev_talk_test_1",
                    "بسته‌بندی (۹:۱۶ — ", "معرفی برنامهٔ ورزشی با", "معرفی برنامهٔ ورزشی +", "معرفی برنامهٔ ورزشی و غذایی هوشمند برای مص"):
            self.assertTrue(B.title_problem(bad), bad)

    def test_good_titles_pass(self):
        for good in ("معرفی چغر", "۳۰٪ تخفیف ویژه", "قبل و بعد", "همین حالا شروع کن", "Chagher", "جعبه‌گشایی کفش", "نظرِ مشتریان", "فروشِ ویژه", "معرفی تو", "چغر — اپ", "چغر — ویدیوی معرفی", "چغر — مربیِ ورزشی"):
            self.assertEqual(B.title_problem(good), "", good)


class CritiqueTitleTests(SimpleTestCase):
    def setUp(self):
        self.an = analyze.analyze([ASSETS["video:3"], ASSETS["audio:1"]], fake_ctx(), want_words=True, want_moments=False)

    def items(self, p, **brief):
        b = B.finish_brief(B.parse_prompt("ریلز"), [ASSETS["video:3"]])
        b.update(brief)
        return {i["key"]: i for i in critique.critique(p, self.an, b)["items"]}

    def project_with_title(self, text):
        p = with_clip("video:3", start=0, end=10)
        p, res = run_tool(p, "add_title", {"text": text, "at": 0.3, "duration": 2.6, "template": "title_big"})
        self.assertTrue(res["ok"], res)
        return p

    def test_a_label_title_burned_into_the_video_is_flagged(self):
        it = self.items(self.project_with_title("معرفی برنامهٔ ورزشی + غذایی با هوش مصنوعی — عک"))
        self.assertFalse(it["title"]["ok"])
        self.assertEqual(it["title"]["severity"], "warn")
        self.assertIn("تیترِ «", it["title"]["detail"])

    def test_a_good_title_passes_and_no_title_adds_no_item(self):
        self.assertTrue(self.items(self.project_with_title("معرفی چغر"), title="معرفی چغر")["title"]["ok"])
        self.assertNotIn("title", self.items(with_clip("video:3", start=0, end=10), title=""))
