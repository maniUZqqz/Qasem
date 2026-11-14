"""«ایده بساز»: the template brief is honest, the AI brief is validated, the idea lands where the content page can run it."""
from unittest import mock

from django.test import TestCase

from apps.ai.trend_models import Trend, TrendIdea
from apps.products.models import Product

from . import ideas, ingest
from .models import IgTrendCluster
from .testkit import make_store, niche_pages, node_batch


class BriefTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        ingest.apply_batch(self.store, node_batch(self.store.pk, pages=niche_pages()))
        self.home = IgTrendCluster.objects.filter(store=self.store, active=True).order_by("-score").first()
        self.diet = next(c for c in IgTrendCluster.objects.filter(store=self.store, active=True) if "رژیم" in c.label)

    def test_template_brief_follows_the_format_and_the_dominant_hook_type(self):
        b = ideas.template_brief(self.store, self.home)
        self.assertEqual(b["source"], "template")
        self.assertEqual(b["format"], "reel")
        self.assertEqual(b["kind"], TrendIdea.Kind.VIDEO)
        self.assertEqual(b["outline"], ideas.OUTLINES["reel"])
        self.assertIn("تمرین در خانه", b["hook"])
        self.assertIn("[قالبِ ساده — بدونِ هوش مصنوعی]", b["idea"])
        self.assertTrue(b["needs_edit"])
        self.assertTrue(b["caption"].startswith(b["hook"]))
        carousel = ideas.template_brief(self.store, self.diet)
        self.assertEqual(carousel["format"], "carousel")
        self.assertEqual(carousel["kind"], TrendIdea.Kind.POST)
        self.assertEqual(carousel["outline"], ideas.OUTLINES["carousel"])

    def test_template_never_invents_a_product_a_price_or_a_number_claim(self):
        b = ideas.template_brief(self.store, self.home, product=None)
        self.assertIn("پیشنهادِ خودتان", b["idea"])
        text = b["hook"] + b["idea"] + b["caption"]
        for bad in ("درصد", "تومان", "٪", "%", "تضمین"):
            self.assertNotIn(bad, text)

    def test_product_matching_uses_the_topic_words_else_the_first_product(self):
        Product.objects.create(store=self.store, name="کفش ورزشی", price=10, is_available=True)
        Product.objects.create(store=self.store, name="برنامهٔ تمرین در خانه", price=10, is_available=True)
        product, matched = ideas.pick_product(self.store, self.home)
        self.assertEqual(product.name, "برنامهٔ تمرین در خانه")
        self.assertTrue(matched)
        product, matched = ideas.pick_product(self.store, self.diet)
        self.assertFalse(matched)
        self.assertEqual(product.name, "کفش ورزشی")

    def test_a_product_the_topic_is_not_about_is_never_named_in_the_template(self):
        """Review of 2026-11-13: the template named the shop's FIRST product (for Chagher a billing item) under a topic about something else."""
        Product.objects.create(store=self.store, name="بستهٔ توکنِ عادی — ۵۰ توکن", price=10, is_available=True)
        product, matched = ideas.pick_product(self.store, self.home)
        self.assertFalse(matched)
        self.assertIsNotNone(product)
        text = ideas.template_brief(self.store, self.home, product, matched)["idea"]
        self.assertNotIn("بستهٔ توکن", text)
        self.assertIn("پیشنهادِ خودتان", text)
        out = ideas.make_idea(self.store, self.home, use_ai=False)
        self.assertNotIn("بستهٔ توکن", out["brief"]["idea"])
        self.assertEqual(out["brief"]["product_id"], product.pk)               # the idea is still linked to a product for the content page
        self.assertFalse(out["brief"]["product_matched"])
        # a matching product IS named
        Product.objects.create(store=self.store, name="برنامهٔ تمرین در خانه", price=10, is_available=True)
        named = ideas.template_brief(self.store, self.home, *ideas.pick_product(self.store, self.home))["idea"]
        self.assertIn("برنامهٔ تمرین در خانه", named)

    def test_no_products_means_no_product_not_a_crash(self):
        out = ideas.make_idea(self.store, self.home, use_ai=False)
        self.assertIsNone(out["brief"]["product_id"])
        self.assertIsNone(TrendIdea.objects.get(pk=out["idea_id"]).product)

    def test_ai_brief_is_validated(self):
        weak = {"hook": "ok", "idea": "کوتاه", "why": "این ترند محبوب است", "outline": ["یک"]}
        ok, problems = ideas._valid(weak)
        self.assertFalse(ok)
        self.assertEqual(len(problems), 4)
        strong = {"hook": "از امروز در خانه تمرین کن", "idea": "یک ریلز ۲۰ ثانیه‌ای که یک حرکت را نشان می‌دهد و برنامهٔ شما را معرفی می‌کند.",
                  "why": "چند صفحهٔ هم‌حوزه همین موضوع را ساخته‌اند و باشگاهِ شما هم همین مخاطب را دارد", "outline": ["قلاب", "نمایش", "دعوت"]}
        self.assertEqual(ideas._valid(strong), (True, []))

    def test_ai_answer_is_used_cleaned_and_labelled(self):
        answer = {"kind": "post", "hook": " تمرین در خانه را شروع کن ", "idea": "یک پست آموزشی کوتاه با سه نکتهٔ ساده که شما هر روز به شاگردانتان می‌گویید.",
                  "why": "این موضوع همین حالا در چند صفحهٔ هم‌حوزه داغ است و با کارِ شما یکی است", "outline": ["الف", "ب"], "caption": "ک", "hashtags": ["#تمرین"]}
        with mock.patch.object(ideas.research_llm, "status", return_value=(True, "")), mock.patch.object(ideas.research_llm, "ask_json", return_value=answer):
            out = ideas.make_idea(self.store, self.home)
        self.assertEqual(out["source"], "ai")
        self.assertEqual(out["brief"]["hook"], "تمرین در خانه را شروع کن")
        self.assertEqual(out["brief"]["kind"], TrendIdea.Kind.POST)
        self.assertFalse(out["brief"]["needs_edit"])
        idea = TrendIdea.objects.get(pk=out["idea_id"])
        self.assertIn("مراحل:", idea.idea)
        self.assertEqual(idea.hook, "تمرین در خانه را شروع کن")

    def test_when_ai_is_out_of_credit_the_template_still_answers(self):
        with mock.patch.object(ideas.research_llm, "status", return_value=(True, "")), \
                mock.patch.object(ideas.research_llm, "ask_json", side_effect=RuntimeError("Metis HTTP 402")):
            out = ideas.make_idea(self.store, self.home)
        self.assertEqual(out["source"], "template")
        self.assertIn("جواب نداد", out["note"])
        self.assertEqual(TrendIdea.objects.filter(store=self.store).count(), 1)

    def test_the_prompt_carries_the_form_not_the_competitors_text(self):
        prompt = ideas.build_prompt(self.store, self.home, [], None)
        self.assertIn("Do not copy any caption", prompt)
        self.assertIn(self.home.label, prompt)
        for example in ideas.examples(self.home):
            self.assertNotIn(example["hook"], prompt, "another page's words are never handed to the model")

    def test_mirror_trend_is_one_per_topic_per_day_and_carries_examples(self):
        a = ideas.make_idea(self.store, self.home, use_ai=False)
        b = ideas.make_idea(self.store, self.home, use_ai=False)
        self.assertEqual(a["trend_id"], b["trend_id"])
        trend = Trend.objects.get(pk=a["trend_id"])
        self.assertEqual((trend.region, trend.source), ("IG", "instagram_scrape"))
        self.assertTrue(trend.context and trend.context[0]["url"].startswith("https://www.instagram.com/"))
        self.assertEqual(TrendIdea.objects.filter(store=self.store, state="OPEN").count(), 1)
