"""«ایده بساز»: مسیرِ فرمولیِ همیشه‌کارا (متیس ۴۰۲ / گرهٔ خاموش / هوش مصنوعیِ خاموش) با دلیلِ فارسی، مسیرِ هوش مصنوعی با جوابِ ساختگی و وارسیِ سخت‌گیرانه،
بی‌تکراری، هدایت با ایده‌های ستاره‌دار، و «با برگشتنِ هوش مصنوعی دوباره کار می‌کند».

SOURCE: آزمون‌ها از InstAI:tests/test_idea_bank.py @ 2f8aa90 (جلوگیری از تکرارِ عنوان، پرامپتِ ایده‌ساز، ذخیره به‌عنوانِ ایدهٔ خودِ کاربر) و
NM:apps/thumbs/tests_ideation.py (هوش مصنوعیِ ساختگی، فرمول‌های بدونِ ادعای ساختگی، متیسِ بی‌اعتبار)."""
import datetime as dt
import threading
import time

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.products.models import Product
from apps.stores.models import Store

from . import ai, bank, fill, formulas, generator, guard
from .catalog import CATEGORIES, FORMATS
from .models import StoreIdea

User = get_user_model()
TODAY = dt.date(2026, 11, 14)
FACTS = ["با چغر چغر تر شو", "پیش‌نویسِ برنامه در کمتر از یک دقیقه"]


def make_store(name="چغر", owner="gen-owner"):
    user = User.objects.create_user(owner, password="x")
    return user, Store.objects.create(owner=user, name=name, business_type="نرم‌افزار برای مربیان ورزشی", target_audience="مربی‌های باشگاه که برنامه می‌نویسند")


def good_ai(store, prompt, system):
    assert "JSON" in prompt and "Persian" in prompt
    return ({"ideas": [
        {"category": "tips", "title": "*مربیِ* تازه‌کار از کجا شروع کند؟", "logline": "راهنمای شروعِ کارِ یک مربیِ تازه‌کار با چند اسلایدِ ساده و قابلِ ذخیره.",
         "hook": "تازه مربی شده‌ای؟ از اینجا شروع کن.", "shoot": "هر اسلاید یک گام.", "cta": "ذخیره کن", "format": "carousel", "channel": "both", "tags": ["آموزش", "مربی"]},
        {"category": "behind", "title": "پشتِ صحنهٔ نوشتنِ یک برنامه", "logline": "نشان بدهید نوشتنِ یک پیش‌نویسِ برنامه چطور پیش می‌رود، بدونِ هیچ ادعا.",
         "hook": "پیش‌نویس این‌طور شکل می‌گیرد.", "shoot": "صفحه‌نمایش و دستِ مربی.", "cta": "نظرت را بنویس", "format": "reel", "channel": "instagram"},
        {"category": "offer", "title": "پیشنهادِ این هفته", "logline": "پیشنهادِ واقعیِ شما را اینجا بنویسید و شرط‌هایش را روشن کنید.",
         "hook": "این هفته یک پیشنهاد داریم: [پیشنهادِ واقعیِ شما].", "shoot": "عکسِ ساده.", "cta": "پیام بده", "format": "photo", "channel": "both"},
        {"category": "tips", "title": "۵۰٪ تخفیفِ ویژه", "logline": "یک تخفیفِ ساختگی که باید دور ریخته شود.", "hook": "همین حالا بخر", "format": "photo"},
        {"category": "tips", "title": "یک ایدهٔ با عددِ ساختگی", "logline": "از مربی‌های ما ۹۰ نفر راضی بوده‌اند و این آمارِ ساختگی است.", "hook": "این را بخوان", "format": "reel"},
        {"category": "tips", "title": "قالبِ ناشناخته برای ایده", "logline": "قالبش وجود ندارد و دور ریخته می‌شود.", "hook": "این را نمی‌شناسیم", "format": "hologram"},
        {"category": "tips", "title": "ایده‌ای با جای‌گیرِ ناشناخته", "logline": "این متن {قیمت} را می‌خواهد که وجود ندارد.", "hook": "یک چیزِ تازه", "format": "photo"},
        {"category": "tips", "title": "کوتاه", "logline": "x", "hook": "y", "format": "photo"},
        "garbage",
    ]}, {"via": "local", "label": "لوکال (qwen3:8b)"})


def unavailable(store, prompt, system):
    raise ai.AIUnavailable("اعتبارِ سرویسِ ابری (متیس) تمام شده است (۴۰۲)؛ سرورِ پردازش خاموش است")


class FormulaPathTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        self.ctx = fill.context(self.store)

    def gen(self, **kw):
        kw.setdefault("ctx", self.ctx)
        kw.setdefault("today", TODAY)
        return generator.generate(self.store, **kw)

    def test_ai_off_still_answers_with_formula_ideas_and_a_persian_reason(self):
        r = self.gen(count=6, topic="برنامهٔ ورزشی", use_ai=True, ask=unavailable)
        self.assertEqual(r["via"], "formula")
        self.assertTrue(r["ai"]["tried"] and not r["ai"]["ok"])
        self.assertIn("۴۰۲", r["ai"]["reason"])
        self.assertIn("هوش مصنوعی در دسترس نبود", r["message"])
        self.assertIn("وقتی هوش مصنوعی برگردد", r["message"])
        self.assertEqual(len(r["ideas"]), 6)
        self.assertGreaterEqual(len({i["category"] for i in r["ideas"]}), 4)               # گوناگون، نه شش‌تا از یک دسته
        for i in r["ideas"]:
            self.assertTrue(i["title"] and i["logline"] and i["hook"] and i["shoot"] and i["cta"])
            self.assertIn(i["format"], FORMATS)

    def test_ai_switched_off_by_the_user_says_so(self):
        r = self.gen(count=4, topic="قهوه", use_ai=False)
        self.assertEqual(r["via"], "formula")
        self.assertFalse(r["ai"]["tried"])
        self.assertIn("هوش مصنوعی خاموش بود", r["message"])

    def test_the_ai_status_reason_is_short_and_clean_for_the_page_hint(self):
        raw = ("لوکال: هیچ سرورِ پردازشی ثبت نشده.؛ متیس: سیاستِ دادهٔ فروشگاه اجازهٔ استفاده از متیس را نمی‌دهد. "
               "سرویسِ ابریِ هوش مصنوعی (کلیدِ پیش‌فرضِ سایت) سرویس بیرونی است و سیاست این فروشگاه «فقط لوکال» است.")
        out = ai._short(raw)
        self.assertNotIn(".؛", out)
        self.assertFalse(out.endswith((".", "؛", " ")))
        self.assertLessEqual(len(out), 175)
        self.assertIn("متیس", out)
        ok, why = ai.status(self.store)                                                    # زیرِ آزمون: «در دسترس نیست» بدونِ شبکه
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_the_default_ask_never_calls_the_network_under_test(self):
        r = self.gen(count=3, topic="قهوه", use_ai=True)                                    # ask=None ⇒ default_ask ⇒ زیرِ آزمون AIUnavailable
        self.assertEqual(r["via"], "formula")
        self.assertIn("زیرِ آزمون", r["ai"]["reason"])

    def test_every_formula_idea_is_free_of_invented_claims(self):
        topics = ["برنامهٔ ورزشی", "قهوهٔ ترک", "طراحی لوگو", "", "کفشِ دویدن برای تازه‌کارها", "خدماتِ نصبِ کولر"]
        for topic in topics:
            for variation in range(3):
                for cat in ("", *CATEGORIES):
                    r = self.gen(count=8, topic=topic, category=cat, facts=FACTS, use_ai=False, variation=variation)
                    for i in r["ideas"]:
                        txt = " ".join(i[f] for f in bank.TEXT_FIELDS)
                        self.assertEqual(guard.problems(txt, topic + " " + " ".join(FACTS)), [], (topic, cat, i["formula"], txt))
                        unknown = set(guard.PLACEHOLDER.findall(txt)) - set(fill.FALLBACK) - {"فروشگاه"}
                        self.assertFalse(unknown, i["title"])
                        if cat:
                            self.assertEqual(i["category"], cat)

    def test_each_category_has_formulas(self):
        for cat in CATEGORIES:
            if cat == "occasion":
                continue                                                                   # مناسبت از ایده‌های آماده می‌آید (تست جدا)
            self.assertTrue([f for f in formulas.FORMULAS if f.category == cat], cat)

    def test_topic_or_product_or_business_becomes_the_subject(self):
        r = self.gen(count=8, topic="قهوهٔ ترک", use_ai=False)
        self.assertTrue(any("قهوهٔ ترک" in i["title"] for i in r["ideas"]))
        r2 = self.gen(count=8, topic="", use_ai=False)
        self.assertTrue(any("نرم‌افزار برای مربیان ورزشی" in i["title"] or "نرم‌افزار" in i["title"] for i in r2["ideas"]))

    def test_no_topic_and_no_product_uses_the_stores_own_products_and_does_not_run_dry(self):
        from .tests_bank import CHAGHER_PRODUCTS

        for n in CHAGHER_PRODUCTS:
            Product.objects.create(store=self.store, name=n, price=0)
        names = generator.default_product_names(self.store)
        self.assertEqual(len(names), 5)
        self.assertEqual(names[-1], CHAGHER_PRODUCTS[0])                                      # نامِ دارای عدد آخر می‌آید
        self.assertEqual(generator.default_product_names(self.store, variation=1)[0], names[1])      # با variation می‌چرخد
        self.assertEqual(generator.default_product_names(type("S", (), {"pk": 0})()), [])           # فروشگاهِ ذخیره‌نشده: بی‌محصول
        seen: set[str] = set()
        used_products: set[str] = set()
        for _ in range(4):
            r = generator.generate_and_save(self.store, count=8, category="tips", use_ai=False, ctx=self.ctx, today=TODAY)
            for i in r["ideas"]:
                self.assertNotIn(i["title"], seen)
                seen.add(i["title"])
                self.assertTrue(fill.balanced(i["title"]), i["title"])
                used_products |= {n for n in CHAGHER_PRODUCTS if n in i["title"]}
        self.assertGreaterEqual(len(seen), 30)                                                # پیش‌تر بعد از ~۶ ایده «چیزی نمانده» بود
        self.assertGreaterEqual(len(used_products), 3)                                        # ایده‌ها برای چند محصولِ واقعی‌اند، نه فقط «حوزه»

    def test_a_domain_that_already_names_its_audience_is_not_followed_by_another_audience(self):
        r = self.gen(count=12, topic="", use_ai=False)                                        # فروشگاهِ آزمون: «نرم‌افزار برای مربیان ورزشی»، بی‌محصول
        for i in r["ideas"]:                                                                  # «چک‌لیستِ نرم‌افزار برای مربیان ورزشی برای مربی‌های باشگاه…» ممنوع
            self.assertFalse("نرم‌افزار برای مربیان ورزشی" in i["title"] and "مربی‌های باشگاه" in i["title"], i["title"])
        self.assertTrue(any("نرم‌افزار برای مربیان ورزشی" in i["title"] for i in r["ideas"]))     # حوزه کامل، نه «نرم‌افزار» به‌تنهایی

    def test_slogans_never_become_facts_or_a_question_about_a_slogan(self):
        facts = ["با چغر چغر تر شو", "تصمیمِ نهایی با مربی است"]
        r = self.gen(count=12, topic="برنامهٔ ورزشی", facts=facts, use_ai=False)
        by = {}
        for i in r["ideas"]:
            by.setdefault(i["formula"], []).append(i)
        for key in ("fact_say", "fact_faq"):
            for i in by.get(key, []):
                self.assertNotIn(facts[0], i["title"] + i["logline"] + i["hook"], key)        # شعار «واقعیت» و موضوعِ «پرسش و پاسخ» نیست
                self.assertIn("تصمیمِ نهایی", i["logline"] + i["hook"])
        self.assertTrue(by.get("fact_slogan"), "شعار باید قالبِ خودش را داشته باشد")
        for i in by["fact_slogan"]:
            self.assertIn(facts[0], i["logline"])

    def test_repeat_clicks_give_new_ideas_until_the_formulas_run_out(self):
        seen: set[str] = set()
        for _ in range(4):
            r = generator.generate_and_save(self.store, count=6, topic="قهوهٔ ترک", use_ai=False, ctx=self.ctx, today=TODAY)
            titles = {i["title"] for i in r["ideas"]}
            self.assertFalse(titles & seen, "ایدهٔ تکراری ساخته شد")
            seen |= titles
        self.assertGreaterEqual(len(seen), 18)
        # وقتی دیگر چیزی نمانده پیامِ روشن می‌دهد، نه لیستِ خالی و خطای ۵۰۰
        with self.assertRaises(ValueError) as cm:
            for _ in range(12):
                generator.generate_and_save(self.store, count=8, topic="قهوهٔ ترک", use_ai=False, ctx=self.ctx, today=TODAY)
        self.assertIn("ایدهٔ تازه‌ای نمانده", str(cm.exception))

    def test_favourites_steer_the_choice(self):
        for k in ("engage_poll", "engage_quiz", "engage_challenge"):
            bank.set_mark(self.store, k, favorite=True)
        r = self.gen(count=4, topic="قهوه", use_ai=False)
        self.assertEqual(r["ideas"][0]["category"], "engage")
        _, other = make_store(name="دیگر", owner="o9")
        plain = generator.generate(other, count=4, topic="قهوه", use_ai=False, ctx=fill.context(other), today=TODAY)
        self.assertNotEqual(plain["ideas"][0]["category"], "engage")                         # ستاره‌ها فقط برای همان فروشگاه

    def test_brand_facts_appear_verbatim_and_only_when_given(self):
        with_facts = self.gen(count=8, topic="قهوه", facts=FACTS, use_ai=False)
        hooks = " ".join(i["hook"] + i["logline"] for i in with_facts["ideas"])
        self.assertTrue([i for i in with_facts["ideas"] if i["formula"].startswith("fact_")])
        self.assertTrue(any(f in hooks for f in FACTS), "جملهٔ تأییدشدهٔ برند باید عیناً بیاید")
        without = self.gen(count=12, topic="قهوه", use_ai=False)
        self.assertFalse([i for i in without["ideas"] if i["formula"].startswith("fact_")])

    def test_an_upcoming_fixed_date_occasion_is_offered_when_it_is_near(self):
        up = formulas.upcoming_occasion(dt.date(2026, 12, 10))                              # یلدا ۱۱ روز دیگر
        self.assertEqual(up["key"], "occasion_yalda")
        self.assertIsNone(formulas.upcoming_occasion(dt.date(2026, 11, 16), within_days=10))
        r = self.gen(count=12, category="occasion", use_ai=False, today=dt.date(2026, 12, 10))
        self.assertTrue(r["ideas"] and r["ideas"][0]["occasion"]["name"] == "شب یلدا")
        self.assertIn("مناسبتِ پیش‌رو", r["ideas"][0]["title"])

    def test_invalid_category_and_long_facts(self):
        with self.assertRaises(ValueError):
            self.gen(category="nope")
        long_fact = "پیش‌نویسِ برنامهٔ ورزشی و غذاییِ اختصاصیِ هر ورزشکار در کمتر از یک دقیقه"
        r = self.gen(count=12, facts=[long_fact], use_ai=False)
        for i in r["ideas"]:
            if i["formula"].startswith("fact_"):
                self.assertNotIn("هر ", i["title"][-3:])                                    # واقعیتِ بلند وسطِ عنوان بریده نمی‌شود
                self.assertLessEqual(len(i["title"]), 70)


class AIPathTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store(owner="ai-owner")
        self.ctx = fill.context(self.store)

    def test_good_ideas_are_kept_and_every_bad_one_is_dropped(self):
        r = generator.generate(self.store, count=8, topic="برنامهٔ ورزشی", use_ai=True, ask=good_ai, ctx=self.ctx)
        ai_ideas = [i for i in r["ideas"] if i["formula"] == "ai"]
        self.assertEqual(len(ai_ideas), 3)
        self.assertTrue(r["ai"]["ok"])
        self.assertEqual(r["ai"]["label"], "لوکال (qwen3:8b)")
        titles = " ".join(i["title"] for i in r["ideas"])
        for bad in ("تخفیف", "عددِ ساختگی", "قالبِ ناشناخته", "جای‌گیرِ ناشناخته", "garbage"):
            self.assertNotIn(bad, titles)
        first = ai_ideas[0]
        self.assertEqual((first["category"], first["format"], first["channel"]), ("tips", "carousel", "both"))
        self.assertEqual(first["tags"], ["آموزش", "مربی"])
        self.assertIn("هوش مصنوعی نوشت", r["message"]) if r["via"] == "ai" else self.assertIn("تکمیل شد", r["message"])

    def test_an_english_only_idea_is_dropped_but_a_latin_brand_name_is_fine(self):
        def english(store, prompt, system):
            return ({"ideas": [
                {"category": "tips", "title": "Five tips for coaches today", "logline": "Five short tips that every coach can try today.", "hook": "Try this today", "format": "reel"},
                {"category": "tips", "title": "Mixed idea with Persian hook", "logline": "An English sentence with only one Persian word سلام here.",
                 "hook": "سلام", "format": "reel"},
                {"category": "tips", "title": "راهنمای کوتاه برای Chagher", "logline": "نشان بدهید چطور با Chagher پیش‌نویسِ برنامه ساخته می‌شود، گام‌به‌گام.",
                 "hook": "با Chagher شروع کن.", "format": "reel"},
            ]}, {})

        out = generator.clean_ai_ideas(english(None, "", "")[0], category="", source="", taken=set())
        self.assertEqual([i["title"] for i in out], ["راهنمای کوتاه برای Chagher"])
        r = generator.generate(self.store, count=3, use_ai=True, ask=english, ctx=self.ctx)
        self.assertNotIn("Five tips", " ".join(i["title"] for i in r["ideas"]))
        self.assertTrue(guard.is_persian("مربیِ تازه‌کار") and not guard.is_persian("Hello coach") and not guard.is_persian("۱۲۳"))

    def test_a_busy_node_falls_back_to_formulas_after_the_wait_instead_of_hanging(self):
        from unittest import mock

        from django.test import override_settings

        release = threading.Event()

        def slow_router(store, prompt, system):
            release.wait(10)
            return {"ideas": []}, {}

        ai._inflight.clear()
        self.addCleanup(ai._inflight.clear)
        self.addCleanup(release.set)
        t0 = time.monotonic()
        with override_settings(IS_TEST=False), mock.patch.object(ai, "_ask_router", slow_router), mock.patch.object(ai, "AI_TIMEOUT", 0.2):
            r = generator.generate(self.store, count=4, topic="قهوه", use_ai=True, ctx=self.ctx)       # ask=None ⇒ مسیرِ واقعیِ default_ask
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(r["via"], "formula")
        self.assertEqual(len(r["ideas"]), 4)
        self.assertIn("ثانیه جواب نداد", r["ai"]["reason"])
        self.assertIn("هوش مصنوعی در دسترس نبود", r["message"])

    def test_the_prompt_lists_the_stores_products_only_when_none_was_chosen(self):
        from .tests_bank import CHAGHER_PRODUCTS

        for n in CHAGHER_PRODUCTS[1:3]:
            Product.objects.create(store=self.store, name=n, price=0)
        seen = {}

        def spy(store, prompt, system):
            seen["prompt"] = prompt
            return {"ideas": []}, {}

        generator.generate(self.store, count=3, use_ai=True, ask=spy, ctx=self.ctx)
        self.assertIn(CHAGHER_PRODUCTS[1], seen["prompt"])
        generator.generate(self.store, count=3, topic="قهوه", use_ai=True, ask=spy, ctx=self.ctx)
        self.assertNotIn(CHAGHER_PRODUCTS[1], seen["prompt"])                                 # با موضوعِ مشخص، فهرستِ محصول‌ها نمی‌آید

    def test_enough_good_ideas_means_via_ai_and_a_slot_survives(self):
        def many(store, prompt, system):
            return ({"ideas": [{"category": "tips", "title": f"نکتهٔ شمارهٔ {w} برای مربی", "logline": "یک نکتهٔ کوتاه و کاربردی برای مربی‌های باشگاه.",
                                "hook": "این نکته را امتحان کن.", "shoot": "یک نما.", "cta": "ذخیره کن", "format": "reel"} for w in ("الف", "ب", "ج", "د")]}, {})

        r = generator.generate(self.store, count=4, use_ai=True, ask=many, ctx=self.ctx)
        self.assertEqual(r["via"], "ai")
        self.assertEqual(len(r["ideas"]), 4)
        self.assertIn("هوش مصنوعی نوشت", r["message"])
        slot = generator.clean_ai_ideas(good_ai(None, "JSON Persian", "")[0], category="", source="", taken=set())
        self.assertTrue([i for i in slot if "[پیشنهادِ واقعیِ شما]" in i["hook"]])           # جای خالی بلامانع است

    def test_a_number_or_word_the_owner_wrote_is_not_a_fake_claim(self):
        def with_discount(store, prompt, system):
            return ({"ideas": [{"category": "offer", "title": "پیشنهادِ نوروزیِ ما", "logline": "پیشنهادِ ۲۰ درصدی برای نوروز، همان‌طور که خودتان نوشتید.",
                                "hook": "این هفتهٔ نوروز ۲۰ درصد تخفیف داریم.", "shoot": "عکسِ محصول.", "cta": "سفارش بده", "format": "photo"}]}, {})

        r = generator.generate(self.store, count=1, category="offer", instruction="یک پیشنهادِ ۲۰ درصد تخفیف برای نوروز بنویس", use_ai=True, ask=with_discount, ctx=self.ctx)
        self.assertEqual(r["via"], "ai")
        r = generator.generate(self.store, count=1, category="offer", use_ai=True, ask=with_discount, ctx=self.ctx)
        self.assertEqual(r["via"], "formula")                                               # بدونِ نوشتهٔ کاربر همان ایده ادعای ساختگی است

    def test_unavailable_ai_falls_back_and_comes_back(self):
        down = generator.generate(self.store, count=5, topic="قهوه", use_ai=True, ask=unavailable, ctx=self.ctx)
        self.assertEqual(down["via"], "formula")
        up = generator.generate(self.store, count=5, topic="قهوه", use_ai=True, ask=good_ai, ctx=self.ctx)
        self.assertIn(up["via"], ("ai", "mixed"))                                          # «با برگشتنِ هوش مصنوعی دوباره کار می‌کند»
        self.assertTrue(up["ai"]["ok"])

    def test_garbage_or_crashing_ai_never_breaks_the_button(self):
        for ask in (lambda s, p, sy: ({"ideas": "نه"}, {}), lambda s, p, sy: ("متن", {}), lambda s, p, sy: ({}, {})):
            r = generator.generate(self.store, count=4, topic="قهوه", use_ai=True, ask=ask, ctx=self.ctx)
            self.assertEqual(r["via"], "formula")
            self.assertEqual(r["ai"]["reason"], "هوش مصنوعی جوابِ قابل‌استفاده نداد.")

        def boom(store, prompt, system):
            raise RuntimeError("boom")

        r = generator.generate(self.store, count=4, topic="قهوه", use_ai=True, ask=boom, ctx=self.ctx)
        self.assertEqual(r["via"], "formula")
        self.assertIn("خطای پیش‌بینی‌نشده", r["ai"]["reason"])

    def test_titles_already_in_the_bank_are_never_repeated(self):
        existing = bank.get_idea(self.store, "tips_howto", self.ctx)["filled"]["title"]

        def repeats(store, prompt, system):
            assert existing in prompt                                                       # مدل فهرستِ عنوان‌های موجود را می‌بیند
            return ({"ideas": [{"category": "tips", "title": existing, "logline": "عنوانش تکراری است و باید دور ریخته شود.", "hook": "تکراری",
                                "format": "carousel"}]}, {})

        r = generator.generate(self.store, count=3, category="tips", use_ai=True, ask=repeats, ctx=self.ctx)
        self.assertNotIn(existing, [i["title"] for i in r["ideas"]])

    def test_prompt_names_the_category_rules_facts_liked_and_forbids_inventions(self):
        bank.set_mark(self.store, "tips_howto", favorite=True)
        seen = {}

        def spy(store, prompt, system):
            seen.update(prompt=prompt, system=system)
            return good_ai(store, prompt, system)

        generator.generate(self.store, count=5, category="faq", topic="ارسال", instruction="کوتاه بنویس", facts=FACTS, use_ai=True, ask=spy, ctx=self.ctx)
        p, s = seen["prompt"], seen["system"]
        self.assertIn("پرسش‌وپاسخ و رفعِ تردید", p)
        self.assertIn("exactly 5", p)
        self.assertIn("ارسال", p)
        self.assertIn(FACTS[0], p)
        self.assertIn("liked", p)
        self.assertIn(bank.get_idea(self.store, "tips_howto", self.ctx)["filled"]["title"], p)
        self.assertIn("existing_titles", p)
        self.assertIn("NEVER write prices", p)
        self.assertIn("FIXED Jalali", p)
        self.assertIn("never invent", s.lower())
        self.assertNotIn("password", p.lower())

    def test_generate_and_save_stores_ideas_for_this_store_only(self):
        r = generator.generate_and_save(self.store, count=4, topic="قهوه", use_ai=True, ask=good_ai, ctx=self.ctx)
        self.assertEqual(r["saved"], len(r["ideas"]))
        self.assertTrue(all(i["origin"] == "generated" and not i["builtin"] for i in r["ideas"]))
        self.assertEqual(StoreIdea.objects.filter(store=self.store).count(), r["saved"])
        _, other = make_store(name="دیگر", owner="o10")
        self.assertEqual(StoreIdea.objects.filter(store=other).count(), 0)
        self.assertEqual([i for i in bank.list_ideas(other, source="mine")], [])
        # «بدونِ ذخیره» پیش‌نمایش است
        before = StoreIdea.objects.count()
        generator.generate(self.store, count=3, topic="چای", use_ai=False, ctx=self.ctx)
        self.assertEqual(StoreIdea.objects.count(), before)


class BoundedWaitTests(SimpleTestCase):
    """«ایده بساز» هرگز بی‌پایان منتظرِ هوش مصنوعی نمی‌ماند (بازبینی ۱۴۰۵/۰۸/۲۴: AI_TIMEOUT تعریف شده بود ولی استفاده نمی‌شد)."""

    def setUp(self):
        ai._inflight.clear()
        self.addCleanup(ai._inflight.clear)

    def test_a_fast_call_returns_its_value_and_an_error_is_passed_on(self):
        self.assertEqual(ai.run_bounded(1, lambda: ({"ideas": [1]}, {"label": "x"}), timeout=5), ({"ideas": [1]}, {"label": "x"}))

        def boom():
            raise ai.AIUnavailable("متیس: اعتبار تمام شده (۴۰۲)")

        with self.assertRaises(ai.AIUnavailable) as cm:
            ai.run_bounded(1, boom, timeout=5)
        self.assertIn("۴۰۲", str(cm.exception))
        with self.assertRaises(KeyError):
            ai.run_bounded(1, lambda: {}["x"], timeout=5)

    def test_a_slow_call_gives_up_with_a_persian_reason_and_a_second_click_does_not_queue_more(self):
        release = threading.Event()
        started = []

        def slow():
            started.append(time.monotonic())
            release.wait(10)
            return {"ideas": []}, {}

        t0 = time.monotonic()
        with self.assertRaises(ai.AIUnavailable) as cm:
            ai.run_bounded(7, slow, timeout=0.2)
        self.assertLess(time.monotonic() - t0, 3)                                            # سقف رعایت شد، نه ۹۰۰ ثانیه
        self.assertIn("ثانیه جواب نداد", str(cm.exception))
        with self.assertRaises(ai.AIUnavailable) as cm2:                                      # همان فروشگاه: کارِ قبلی هنوز در صف است
            ai.run_bounded(7, slow, timeout=0.2)
        self.assertIn("هنوز در صفِ", str(cm2.exception))
        self.assertEqual(len(started), 1)                                                     # کارِ دوم شروع نشد
        self.assertEqual(ai.run_bounded(8, lambda: "other store", timeout=2), "other store")   # فروشگاهِ دیگر آزاد است
        release.set()
        for _ in range(50):                                                                   # کارِ قبلی تمام شد ⇒ دوباره آزاد
            if not ai._inflight[7].is_alive():
                break
            time.sleep(0.05)
        self.assertEqual(ai.run_bounded(7, lambda: "again", timeout=2), "again")
