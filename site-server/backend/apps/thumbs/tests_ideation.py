"""ایده‌پردازی: فرمول‌های آمادهٔ فارسی (بدونِ هوش مصنوعی)، مسیرِ هوش مصنوعی با جوابِ ساختگی، وارسیِ جواب، متیسِ بی‌اعتبار، مودبرد."""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.products.models import Product
from apps.stores.models import Store

from . import archetypes, hooks, ideation, typo
from .styles import STYLES

User = get_user_model()


def good_ai(store, prompt):
    assert "Persian" in prompt and "JSON" in prompt
    return ({"ideas": [
        {"title": "*مربیِ* هوشمند چه می‌کند؟", "subtitle": "یک نگاهِ نزدیک", "kicker": "پرسش", "style": "question_hook",
         "concept": "نمای نزدیک با نگاهِ کنجکاو", "bg_prompt_en": "dark moody spotlight background with fog", "mood": "dark"},
        {"title": "برنامهٔ ورزشی از *کجا* شروع شود", "style": "face_text", "bg_prompt_en": "کاملاً فارسی"},
        {"title": "۵۰٪ تخفیفِ *ویژه*", "style": "product_hero"},                       # ادعای ساختگی: باید دور ریخته شود
        {"title": "*ورزش* در خانه", "style": "no-such-style", "number": "۷", "badge": "۹۹٬۰۰۰ تومان"},   # سبکِ ناشناخته ⇒ جایگزین؛ قیمتِ ساختگی ⇒ پاک
        {"title": "x", "style": "neon"},                                                # خیلی کوتاه
        "garbage",
    ]}, {"via": "local", "label": "لوکال (qwen3:8b)"})


class RuleIdeasTests(SimpleTestCase):
    def test_rules_are_deterministic_persian_and_varied(self):
        ideas = hooks.rule_ideas("برنامهٔ ورزشی شخصی", fmt="youtube", count=6)
        self.assertEqual(len(ideas), 6)
        self.assertGreaterEqual(len({i["style"] for i in ideas}), 3)
        for i in ideas:
            self.assertTrue(typo.is_rtl(i["title"]), i["title"])
            self.assertIn(i["style"], STYLES)
            self.assertTrue(i["concept"])
            self.assertTrue(hooks.ASCII_PROMPT.match(i["bg_prompt_en"]), i["bg_prompt_en"])
            self.assertIn("no text", i["bg_prompt_en"])
        self.assertEqual(ideas, hooks.rule_ideas("برنامهٔ ورزشی شخصی", fmt="youtube", count=6))
        self.assertNotEqual([i["title"] for i in ideas], [i["title"] for i in hooks.rule_ideas("برنامهٔ ورزشی شخصی", fmt="youtube", count=6, variation=1)])

    def test_no_invented_prices_or_statistics(self):
        for fmt in ("youtube", "story", "poster", "pinterest"):
            for i in hooks.rule_ideas("تغذیهٔ ورزشکاران", fmt=fmt, count=8):
                for text in (i["title"], i["subtitle"], i["badge"], i["kicker"]):
                    for risky in ("درصد", "تومان", "ریال", "تخفیف", "٪", "%", "رایگان", "تضمین"):
                        self.assertNotIn(risky, text, (fmt, text))

    def test_number_only_in_list_formulas(self):
        ideas = hooks.rule_ideas("عادت‌های سالم", fmt="youtube", count=8, number=7)
        for i in ideas:
            if i["number"]:
                self.assertEqual(i["number"], "۷")
                self.assertIn("۷", i["title"])
            else:
                self.assertFalse(any(ch in i["title"] for ch in "۰۱۲۳۴۵۶۷۸۹"), i["title"])

    def test_versus_needs_two_sides(self):
        self.assertTrue(any(i["style"] == "versus" for i in hooks.rule_ideas("دمبل یا هالتر", fmt="youtube", count=8)))
        self.assertFalse(any(i["style"] == "versus" for i in hooks.rule_ideas("دمبل", fmt="youtube", count=8)))
        self.assertEqual(hooks.split_versus("دمبل در برابر هالتر"), ("دمبل", "هالتر"))

    def test_platform_changes_the_first_style(self):
        self.assertIn(hooks.rule_ideas("چای سبز", fmt="poster", count=3)[0]["style"], hooks.PLATFORM_STYLES["poster"])
        self.assertEqual(hooks.rule_ideas("", fmt="youtube"), [])

    def test_product_ideas_carry_real_price_only_when_given(self):
        ideas = hooks.rule_ideas("x", fmt="ig_portrait", count=8, product={"name": "قهوهٔ ترک", "price_text": "۲۰۰٬۰۰۰ تومان", "short": "دان‌هٔ تازه"})
        prod = [i for i in ideas if i["formula"] == "new_product"]
        self.assertTrue(prod)
        self.assertEqual(prod[0]["badge"], "۲۰۰٬۰۰۰ تومان")
        self.assertEqual(prod[0]["title"], "قهوهٔ ترک")
        ideas = hooks.rule_ideas("x", fmt="ig_portrait", count=8, product={"name": "قهوهٔ ترک", "price_text": ""})
        self.assertTrue(all(not i["badge"] for i in ideas))


class MoodboardTests(SimpleTestCase):
    def test_archetypes_are_curated_not_scraped(self):
        self.assertGreaterEqual(len(archetypes.ARCHETYPES), 10)
        origins = {a["origin"] for a in archetypes.ARCHETYPES}
        self.assertTrue({"video", "poster", "pinterest"} <= origins)
        for a in archetypes.ARCHETYPES:
            self.assertIn(a["style"], STYLES)
            self.assertTrue(a["pattern"] and a["why"] and a["dos"] and a["donts"] and a["text_rule"])
            self.assertTrue(typo.is_rtl(a["pattern"]))
            blob = " ".join(str(v) for v in a.values())
            self.assertNotIn("http", blob)
            self.assertNotIn("pinterest.com", blob.lower())
        # هر سبکِ ساختنی یک الگوی توصیفی در مودبرد دارد (نبودنش = سبکِ بی‌توضیح)
        self.assertEqual({a["style"] for a in archetypes.ARCHETYPES}, set(STYLES))
        rows = archetypes.public(lambda s, f: f"/s/{s}.jpg?format={f}")
        self.assertTrue(all(r["sample"].startswith("/s/") for r in rows))


class IdeateTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("idea-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", target_audience="مربی‌های باشگاه", description="دستیارِ مربی")

    def test_fallback_without_ai(self):
        out = ideation.ideate(self.store, "برنامهٔ ورزشی", fmt="youtube", use_ai=False)
        self.assertEqual(out["via"], "rules")
        self.assertFalse(out["ai"]["tried"])
        self.assertGreaterEqual(len(out["ideas"]), 4)
        i0 = out["ideas"][0]
        self.assertEqual(i0["id"], "i1")
        self.assertEqual(i0["spec_patch"]["style"], i0["style"])
        self.assertEqual(i0["spec_patch"]["content"]["title"], i0["title"])
        self.assertIn("فرمول", out["message"])

    def test_ai_unavailable_degrades_with_clear_message(self):
        def dead(store, prompt):
            raise ideation.AIUnavailable("اعتبارِ متیس تمام شده است (۴۰۲).")

        out = ideation.ideate(self.store, "برنامهٔ ورزشی", ask=dead)
        self.assertEqual(out["via"], "rules")
        self.assertTrue(out["ai"]["tried"])
        self.assertFalse(out["ai"]["ok"])
        self.assertIn("۴۰۲", out["message"])
        self.assertIn("فرمول", out["message"])
        self.assertTrue(out["ideas"])

    def test_raw_service_errors_become_one_persian_sentence(self):
        raw = 'خطای سرویس (۴۰۲): {"error": {"message":"Insufficient credit, please top up","code":"insufficient_credit"}}'
        self.assertEqual(hooks.friendly_reason(raw), "اعتبارِ سرویسِ ابری (متیس) تمام شده است (۴۰۲)")
        out = hooks.friendly_reason('سرورِ پردازش پاسخ نداد {"detail": {"a": 1}}   دوباره امتحان کنید')
        self.assertNotIn("{", out)
        self.assertIn("پاسخ نداد", out)
        self.assertLessEqual(len(hooks.friendly_reason("الف " * 200)), 170)
        self.assertEqual(hooks.friendly_reason(None), "")

    def test_default_ask_never_hits_the_network_under_test(self):
        out = ideation.ideate(self.store, "تغذیهٔ ورزشی")      # بدونِ ask ⇒ _default_ask ⇒ زیرِ آزمون AIUnavailable
        self.assertEqual(out["via"], "rules")
        self.assertIn("آزمون", out["ai"]["reason"])

    def test_unexpected_ai_crash_still_gives_ideas(self):
        def boom(store, prompt):
            raise RuntimeError("kaboom")

        out = ideation.ideate(self.store, "یوگا", ask=boom)
        self.assertEqual(out["via"], "rules")
        self.assertIn("kaboom", out["ai"]["reason"])

    def test_ai_path_is_validated(self):
        out = ideation.ideate(self.store, "برنامهٔ ورزشی", ask=good_ai, count=5)
        titles = [i["title"] for i in out["ideas"] if i["source"] == "ai"]
        self.assertEqual(len(titles), 3)
        self.assertEqual(out["via"], "mixed" if len(out["ideas"]) > 3 else "ai")
        self.assertFalse(any("تخفیف" in t for t in titles))
        self.assertTrue(any("*مربیِ*" in t for t in titles))
        by_title = {i["title"]: i for i in out["ideas"]}
        q = by_title["*مربیِ* هوشمند چه می‌کند؟"]
        self.assertEqual(q["style"], "question_hook")
        self.assertEqual(q["mood"], "dark")
        self.assertEqual(q["bg_prompt_en"].split(",")[0], "dark moody spotlight background with fog")
        self.assertIn("no text", q["bg_prompt_en"])
        persian_prompt = by_title["برنامهٔ ورزشی از *کجا* شروع شود"]
        self.assertTrue(hooks.ASCII_PROMPT.match(persian_prompt["bg_prompt_en"]))      # دستورِ فارسی ⇒ جایگزینِ آماده
        weird = by_title["*ورزش* در خانه"]
        self.assertIn(weird["style"], STYLES)
        self.assertEqual(weird["number"], "۷")
        self.assertEqual(weird["badge"], "")                                          # قیمتِ ساختگی پاک شد
        self.assertIn("هوش مصنوعی", out["message"])
        self.assertEqual(out["ai"]["label"], "لوکال (qwen3:8b)")

    def test_ai_with_nothing_valid_falls_back(self):
        out = ideation.ideate(self.store, "یوگا", ask=lambda s, p: ({"ideas": [{"title": "۸۰٪ تخفیف", "style": "neon"}]}, {}))
        self.assertEqual(out["via"], "rules")
        self.assertIn("جوابِ قابل‌استفاده", out["ai"]["reason"])

    def test_claims_present_in_the_source_are_allowed(self):
        ask = lambda s, p: ({"ideas": [{"title": "تخفیفِ *ویژهٔ* پاییز", "style": "news_bold"}, {"title": "پیشنهادِ *ویژه* برای شما", "style": "face_text"},
                                       {"title": "*ورزش* با تخفیف", "style": "neon"}]}, {})
        out = ideation.ideate(self.store, "تخفیفِ پاییزه", ask=ask)
        self.assertTrue(any("تخفیف" in i["title"] for i in out["ideas"] if i["source"] == "ai"))

    def test_product_topic_and_price_flag(self):
        p = Product.objects.create(store=self.store, name="قهوهٔ ترک", price=200_000, short_description="دانهٔ تازه")
        out = ideation.ideate(self.store, "", product=p, fmt="ig_portrait", use_ai=False, count=8)
        self.assertTrue(any(i["title"] == "قهوهٔ ترک" for i in out["ideas"]))
        self.assertTrue(all(not i["badge"] for i in out["ideas"]))
        out = ideation.ideate(self.store, "", product=p, fmt="ig_portrait", use_ai=False, count=8, use_price=True)
        badges = [i["badge"] for i in out["ideas"] if i["badge"]]
        self.assertTrue(badges and all("۲۰۰٬۰۰۰" in b for b in badges), badges)

    def test_empty_topic_is_an_error(self):
        with self.assertRaises(ValueError):
            ideation.ideate(self.store, "   ", use_ai=False)

    def test_prompt_contains_only_known_facts(self):
        seen = {}

        def spy(store, prompt):
            seen["p"] = prompt
            return {"ideas": []}, {}

        ideation.ideate(self.store, "یوگا", ask=spy)
        self.assertIn("مربی‌های باشگاه", seen["p"])
        self.assertIn("NEVER invent prices", seen["p"])
