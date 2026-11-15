"""The market-trends tab: word forms in relevance, the owner's category chips, and the tab filling itself.

Three things were wrong and each has a test here:

1. **Relevance matched whole tokens.** «ورزشی / ورزشکاران / مربیان» never matched «ورزش»,
   so a coaching app was only «موبایل و دیجیتال» and fitness trends were «نامرتبط».
2. **Nothing refreshed the tab.** No beat entry, a 36-hour window, newest row three weeks old.
3. **The categories could not be corrected** by the owner.

The Chagher text below is the public description of the owner's product (docs/chagher/brand-facts-fa.md),
used as a fixture; nothing personal.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.products.models import Product
from apps.stores.models import Store
from services.research import trends as source

from . import trend_refresh
from . import trends as engine
from .trend_models import StoreTrendGroups, Trend, TrendRefreshState
from .trend_text import contains_phrase, stem_sequence, stems


class StemTests(TestCase):
    def test_persian_word_forms_share_a_stem(self):
        self.assertIn("ورزش", stems("ورزشی"))
        self.assertIn("ورزش", stems("ورزشکاران"))
        self.assertIn("ورزش", stems("ورزشگاه"))
        self.assertIn("مربی", stems("مربیان"))
        self.assertIn("تمرین", stems("تمرینات"))
        self.assertIn("تمرین", stems("تمرینی"))
        self.assertIn("مسابقه", stems("مسابقات"))  # Arabic-style plural
        self.assertIn("کفش", stems("کفشها"))

    def test_short_words_do_not_turn_into_other_words(self):
        """The point of a minimum stem length: no «کت» in «کتاب», no «شیر» in «شیرین»."""
        self.assertNotIn("کت", stems("کتاب"))
        self.assertNotIn("شیر", stems("شیرین"))
        self.assertNotIn("ایر", stems("ایران"))
        self.assertNotIn("خان", stems("خانه"))
        self.assertEqual(stems("مد"), frozenset({"مد"}))

    def test_english_forms(self):
        self.assertIn("workout", stems("workouts"))
        self.assertIn("coach", stems("coaching"))
        self.assertIn("coach", stems("coaches"))
        self.assertIn("sport", stems("sports"))
        self.assertEqual(stems("1300"), frozenset({"1300"}))

    def test_phrase_matching_is_contiguous_and_form_aware(self):
        seq = stem_sequence("کاهش وزن سریع")
        self.assertTrue(contains_phrase(seq, [stems("کاهش"), stems("وزن")]))
        self.assertFalse(contains_phrase(seq, [stems("وزن"), stems("کاهش")]))
        self.assertFalse(contains_phrase([], [stems("وزن")]))


def chagher_like_store():
    owner = User.objects.create_user("coach-owner", password="x")
    store = Store.objects.create(
        owner=owner, name="چغر", business_type="نرم‌افزار و خدمات دیجیتال برای مربیان ورزشی",
    )
    for name, tags in (
        ("برنامهٔ ورزشی + غذایی با هوش مصنوعی", ["هوش مصنوعی", "برنامه ورزشی", "برنامه غذایی", "PDF"]),
        ("برنامه‌سازِ دستیِ چغر (بدونِ هوش مصنوعی)", ["برنامه‌ساز دستی", "PDF"]),
        ("کتابخانهٔ حرکت‌ها و اسکنِ دستگاه", ["کتابخانه حرکت", "آموزش حرکت"]),
        ("بستهٔ توکنِ «عادی» — ۵۰ توکن", ["توکن", "هزینه"]),
    ):
        Product.objects.create(store=store, name=name, price=1000, tags=tags)
    return owner, store


def trend(title, *headlines, region="IR"):
    return Trend.objects.create(
        title=title, region=region, seen_at=timezone.now(),
        context=[{"title": h, "url": "", "source": ""} for h in headlines],
    )


class ChagherRelevanceTests(TestCase):
    def setUp(self):
        self.owner, self.store = chagher_like_store()
        self.vocab = engine.store_vocabulary(self.store)

    def test_a_coaching_app_is_not_a_phone_shop(self):
        groups = self.vocab["groups"]
        self.assertIn("ورزش و تناسب اندام", groups)
        self.assertIn("نرم‌افزار و ابزار", groups)
        self.assertNotIn("موبایل و دیجیتال", groups)  # «خدمات دیجیتال» is not «کالای دیجیتال»

    def test_a_phone_shop_is_still_a_phone_shop(self):
        owner = User.objects.create_user("phone-owner", password="x")
        store = Store.objects.create(owner=owner, name="دیجی‌شاپ", business_type="فروشگاه کالای دیجیتال")
        self.assertIn("موبایل و دیجیتال", engine.store_vocabulary(store)["groups"])

    def test_fitness_trends_are_recognised_through_word_forms(self):
        cases = [
            trend("تمرینات خانگی ورزشکاران"),
            trend("چالش جدید", "برنامه تمرینی مربیان بدنسازی"),
            trend("رژیم لاغری"),
            trend("کاهش وزن در یک ماه"),
            trend("Home workouts", "Best coaching apps"),
        ]
        for t in cases:
            rel = engine.relevance(t, self.vocab)
            self.assertNotEqual(rel["key"], "none", (t.title, rel))

    def test_a_trend_about_phones_or_a_cake_is_still_unrelated(self):
        for t in (trend("آیفون ۱۷", "قیمت گوشی جدید"), trend("شیرینی شب یلدا"), trend("شیرین"),
                  trend("ایران و عراق"), trend("کتاب جدید")):
            self.assertEqual(engine.relevance(t, self.vocab)["key"], "none", t.title)

    def test_the_reason_names_the_words_that_matched(self):
        rel = engine.relevance(trend("ورزشکاران ایران"), self.vocab)
        self.assertIn("واژه‌های مشترک", rel["reason"])
        self.assertIn("«ورزشکاران»", rel["reason"])
        self.assertTrue(rel["words"])

    def test_one_word_is_counted_once_even_with_several_forms_in_the_vocabulary(self):
        """«ورزشی» is in the shop twice (a product word and a lexicon word) — one text word, one hit."""
        rel = engine.relevance(trend("ورزشی"), self.vocab)
        self.assertEqual(rel["score"], 2)

    def test_generic_product_words_do_not_make_everything_relevant(self):
        self.assertEqual(engine.relevance(trend("فقط امروز", "بدون هزینه و عادی"), self.vocab)["key"], "none")

    def test_words_with_a_second_meaning_in_the_news_do_not_count_alone(self):
        """«رژیم» is a diet here but «رژیم صهیونیستی» in the news; «باشگاه» is a gym but «باشگاه پرسپولیس»;
        a football story is not a fitness trend. Found by probing the real trend rows against store 34."""
        for t in (
            trend("رژیم صهیونیستی"),
            trend("باشگاه پرسپولیس"),
            trend("لیونل مسی", "فوتبال و لیگ برتر"),
            trend("اجلاس", "دستگاه‌های اجرایی"),
            trend("football player dies", region="US"),
        ):
            self.assertEqual(engine.relevance(t, self.vocab)["key"], "none", t.title)
        for t in (trend("رژیم غذایی کتو"), trend("باشگاه بدنسازی نزدیک من")):
            self.assertNotEqual(engine.relevance(t, self.vocab)["key"], "none", t.title)

    def test_team_sports_belong_to_shops_that_talk_about_football(self):
        owner = User.objects.create_user("boot-owner", password="x")
        store = Store.objects.create(owner=owner, name="کفش", business_type="کفش فوتبال و والیبال")
        vocab = engine.store_vocabulary(store)
        self.assertIn("ورزش‌های تیمی و رویدادها", vocab["groups"])
        self.assertNotEqual(engine.relevance(trend("لیگ برتر فوتبال"), vocab)["key"], "none")
        self.assertNotIn("ورزش‌های تیمی و رویدادها", self.vocab["groups"])

    def test_the_owners_category_choice_replaces_detection(self):
        vocab = engine.store_vocabulary(self.store, groups=["پوشاک و مد"])
        self.assertEqual(vocab["groups"], ["پوشاک و مد"])
        self.assertIn("ورزش و تناسب اندام", vocab["detected_groups"])
        self.assertNotEqual(engine.relevance(trend("مانتو بهاره"), vocab)["key"], "none")

    def test_several_groups_can_apply_at_once(self):
        self.assertGreaterEqual(len(self.vocab["groups"]), 2)


class TrendRefreshTests(TestCase):
    PAYLOAD = {
        "trends": [{"title": "پاییز", "region": "IR", "region_title": "ایران", "traffic": "20K+",
                    "image": "", "context": [], "source": "google_trends"}],
        "problems": ["ترندهای آلمان گرفته نشد: down"],
    }

    def test_run_stores_trends_and_records_what_happened(self):
        with patch.object(source, "fetch", return_value=self.PAYLOAD) as fetch:
            result = trend_refresh.run(trigger="beat")
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(fetch.call_args[0][0], trend_refresh.DEFAULT_REGIONS)
        row = TrendRefreshState.objects.get(pk=1)
        self.assertIsNotNone(row.last_success_at)
        self.assertIsNone(row.running_since)
        self.assertEqual(row.last_trigger, "beat")
        self.assertEqual(row.last_result["problems"], ["ترندهای آلمان گرفته نشد: down"])
        self.assertEqual(Trend.objects.count(), 1)

    def test_every_country_and_instagram_are_refreshed_by_default(self):
        self.assertEqual(set(trend_refresh.DEFAULT_REGIONS), set(source.REGIONS) | {source.INSTAGRAM})

    def test_all_sources_down_is_recorded_not_raised(self):
        down = {"trends": [], "problems": ["هیچ منبعی جواب نداد"]}
        with patch.object(source, "fetch", return_value=down):
            trend_refresh.run(trigger="beat")
        row = TrendRefreshState.objects.get(pk=1)
        self.assertIsNone(row.last_success_at)  # an empty run is not a refresh
        self.assertEqual(row.last_result["problems"], ["هیچ منبعی جواب نداد"])

    def test_an_exception_in_a_background_run_is_swallowed_but_the_button_sees_it(self):
        with patch.object(source, "fetch", side_effect=RuntimeError("boom")):
            result = trend_refresh.run(trigger="beat")
            self.assertEqual(result["fetched"], 0)
            self.assertIsNone(TrendRefreshState.objects.get(pk=1).running_since)  # never left "running"
            with self.assertRaises(RuntimeError):
                trend_refresh.run(trigger="manual")

    def test_a_second_run_does_not_start_while_one_is_running(self):
        TrendRefreshState.objects.create(pk=1, running_since=timezone.now())
        with patch.object(source, "fetch", return_value=self.PAYLOAD) as fetch:
            self.assertEqual(trend_refresh.run(trigger="page"), {"skipped": "already_running"})
        fetch.assert_not_called()

    def test_a_dead_run_does_not_block_forever(self):
        TrendRefreshState.objects.create(
            pk=1, running_since=timezone.now() - trend_refresh.RUNNING_TIMEOUT - timedelta(minutes=1),
        )
        with patch.object(source, "fetch", return_value=self.PAYLOAD):
            self.assertEqual(trend_refresh.run(trigger="page")["fetched"], 1)

    def test_the_button_runs_even_if_a_background_run_is_marked_running(self):
        TrendRefreshState.objects.create(pk=1, running_since=timezone.now())
        with patch.object(source, "fetch", return_value=self.PAYLOAD):
            self.assertEqual(trend_refresh.run(["IR"], trigger="manual")["fetched"], 1)


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
class EnsureFreshTests(TestCase):
    """Opening the tab with stale data queues exactly one background refresh."""

    def _stale(self):
        TrendRefreshState.objects.update_or_create(
            pk=1, defaults={"last_success_at": timezone.now() - timedelta(days=3), "last_attempt_at": None,
                            "running_since": None},
        )

    def test_stale_data_queues_one_refresh_and_not_a_second(self):
        self._stale()
        with patch("apps.ai.tasks.refresh_market_trends.apply_async") as queued:
            self.assertEqual(trend_refresh.ensure_fresh(), "started")
            self.assertEqual(trend_refresh.ensure_fresh(), "recent")  # a retry window, not a stampede
        self.assertEqual(queued.call_count, 1)
        self.assertEqual(queued.call_args.kwargs["kwargs"], {"trigger": "page"})

    def test_an_empty_database_counts_as_stale(self):
        with patch("apps.ai.tasks.refresh_market_trends.apply_async") as queued:
            self.assertEqual(trend_refresh.ensure_fresh(), "started")
        queued.assert_called_once()

    def test_fresh_data_queues_nothing(self):
        TrendRefreshState.objects.update_or_create(pk=1, defaults={"last_success_at": timezone.now()})
        with patch("apps.ai.tasks.refresh_market_trends.apply_async") as queued:
            self.assertEqual(trend_refresh.ensure_fresh(), "fresh")
        queued.assert_not_called()

    def test_a_running_refresh_is_not_doubled(self):
        self._stale()
        TrendRefreshState.objects.filter(pk=1).update(running_since=timezone.now())
        with patch("apps.ai.tasks.refresh_market_trends.apply_async") as queued:
            self.assertEqual(trend_refresh.ensure_fresh(), "running")
        queued.assert_not_called()

    def test_a_dead_queue_does_not_break_the_page(self):
        self._stale()
        with patch("apps.ai.tasks.refresh_market_trends.apply_async", side_effect=OSError("redis down")):
            self.assertEqual(trend_refresh.ensure_fresh(), "error")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_without_a_queue_the_page_never_runs_the_fetch_in_the_request(self):
        self._stale()
        with patch.object(source, "fetch") as fetch:
            self.assertEqual(trend_refresh.ensure_fresh(), "queue_off")
        fetch.assert_not_called()


class BeatTests(TestCase):
    def test_the_daily_refresh_is_scheduled_twice_a_day(self):
        entry = settings.CELERY_BEAT_SCHEDULE["market-trends-refresh"]
        self.assertEqual(entry["task"], "apps.ai.tasks.refresh_market_trends")
        self.assertEqual(sorted(entry["schedule"].hour), [3, 15])
        self.assertEqual(entry["options"]["expires"], 3600)

    def test_the_task_exists_and_runs_on_the_ai_queue(self):
        from fnmatch import fnmatch

        from config.celery import app

        self.assertIn("apps.ai.tasks.refresh_market_trends", app.tasks)
        patterns = [k for k in settings.CELERY_TASK_ROUTES if fnmatch("apps.ai.tasks.refresh_market_trends", k)]
        self.assertTrue(patterns)
        self.assertEqual(settings.CELERY_TASK_ROUTES[patterns[0]]["queue"], "ai")

    def test_the_task_runs_the_refresh_without_raising(self):
        from apps.ai.tasks import refresh_market_trends

        with patch.object(source, "fetch", return_value=TrendRefreshTests.PAYLOAD):
            out = refresh_market_trends.apply().get()
        self.assertEqual(out["fetched"], 1)


class TrendsApiTests(TestCase):
    def setUp(self):
        self.owner, self.store = chagher_like_store()
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = reverse("store-trends", args=[self.store.pk])

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_opening_the_tab_with_no_data_starts_a_refresh_and_says_so(self):
        with patch("apps.ai.tasks.refresh_market_trends.apply_async") as queued:
            body = self.client.get(self.url).json()
        queued.assert_called_once()
        self.assertEqual(body["trends"], [])
        self.assertEqual(body["freshness"]["auto"], "started")
        self.assertTrue(body["freshness"]["stale"])
        self.assertIsNone(body["freshness"]["last_refresh_at"])

    def test_the_page_reports_when_it_last_updated_and_what_failed(self):
        trend("تمرین مربیان")
        TrendRefreshState.objects.update_or_create(pk=1, defaults={
            "last_success_at": timezone.now() - timedelta(hours=2), "last_trigger": "beat",
            "last_result": {"problems": ["ترندهای ترکیه گرفته نشد: down"]},
        })
        body = self.client.get(self.url).json()
        fresh = body["freshness"]
        self.assertEqual(fresh["auto"], "fresh")
        self.assertFalse(fresh["stale"])
        self.assertEqual(fresh["last_trigger"], "beat")
        self.assertAlmostEqual(fresh["age_hours"], 2.0, delta=0.2)
        self.assertEqual(fresh["problems"], ["ترندهای ترکیه گرفته نشد: down"])
        self.assertEqual(len(body["trends"]), 1)
        self.assertNotEqual(body["trends"][0]["relevance"]["key"], "none")

    def test_the_button_goes_through_the_same_path_and_updates_the_clock(self):
        with patch.object(source, "fetch", return_value=TrendRefreshTests.PAYLOAD):
            res = self.client.post(self.url, {"regions": ["IR"]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["fetched"], 1)
        self.assertEqual(TrendRefreshState.objects.get(pk=1).last_trigger, "manual")

    def test_the_button_still_answers_503_when_the_refresh_blows_up(self):
        with patch.object(source, "fetch", side_effect=RuntimeError("boom")):
            res = self.client.post(self.url, {"regions": ["IR"]}, format="json")
        self.assertEqual(res.status_code, 503)

    def test_groups_are_detected_and_the_owner_can_edit_them(self):
        body = self.client.get(self.url).json()
        self.assertIn("ورزش و تناسب اندام", body["store_groups"])
        self.assertFalse(body["groups_custom"])
        self.assertIn("پوشاک و مد", body["all_groups"])

        url = reverse("trend-groups", args=[self.store.pk])
        res = self.client.put(url, {"groups": ["ورزش و تناسب اندام", "قهوه و کافه"]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["store_groups"], ["قهوه و کافه", "ورزش و تناسب اندام"])
        self.assertTrue(res.json()["groups_custom"])
        self.assertEqual(StoreTrendGroups.objects.get(store=self.store).groups,
                         ["ورزش و تناسب اندام", "قهوه و کافه"])

        again = self.client.get(self.url).json()
        self.assertEqual(again["store_groups"], ["قهوه و کافه", "ورزش و تناسب اندام"])
        self.assertTrue(again["groups_custom"])
        self.assertIn("نرم‌افزار و ابزار", again["detected_groups"])  # detection is still reported

        res = self.client.put(url, {"reset": True}, format="json")
        self.assertFalse(res.json()["groups_custom"])
        self.assertIn("نرم‌افزار و ابزار", res.json()["store_groups"])
        self.assertFalse(StoreTrendGroups.objects.filter(store=self.store).exists())

    def test_an_empty_choice_is_allowed_and_means_no_category(self):
        url = reverse("trend-groups", args=[self.store.pk])
        res = self.client.put(url, {"groups": []}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["store_groups"], [])
        self.assertTrue(res.json()["groups_custom"])

    def test_unknown_or_malformed_groups_are_refused_in_persian(self):
        url = reverse("trend-groups", args=[self.store.pk])
        bad = self.client.put(url, {"groups": ["نامعلوم"]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("دستهٔ ناشناخته", bad.json()["error"]["message"])
        self.assertEqual(self.client.put(url, {"groups": "x"}, format="json").status_code, 400)
        self.assertFalse(StoreTrendGroups.objects.exists())

    def test_someone_elses_shop_cannot_be_edited(self):
        stranger = User.objects.create_user("stranger", password="x")
        client = APIClient()
        client.force_authenticate(stranger)
        res = client.put(reverse("trend-groups", args=[self.store.pk]), {"groups": []}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.assertFalse(StoreTrendGroups.objects.exists())

    def test_the_saved_choice_drives_relevance_on_the_page(self):
        trend("مانتو بهاره")
        before = self.client.get(self.url).json()["trends"][0]["relevance"]["key"]
        self.client.put(reverse("trend-groups", args=[self.store.pk]), {"groups": ["پوشاک و مد"]}, format="json")
        after = self.client.get(self.url).json()["trends"][0]["relevance"]["key"]
        self.assertEqual(before, "none")
        self.assertNotEqual(after, "none")
