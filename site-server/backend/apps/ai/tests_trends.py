"""Trends: freshness, honesty about sources, and the rule that kills most ideas.

Two properties carry the weight.

**A trend has a clock.** Everything here that looks like a date test is really
about not sending a shop to film for a moment that has passed.

**Most trends fit no shop.** The suggestion layer throws away any idea whose
`why` is empty or generic, so several tests below feed it a model that answers
with plausible-looking nonsense and check that nonsense does not survive. A
trend page that pairs every trend with every product is one a shop stops reading
on the third visit.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.products.models import Product
from apps.stores.models import Store
from services.research import trends as source

from .trend_models import Trend, TrendIdea
from . import trends as engine

RSS = b"""<?xml version="1.0"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item>
  <title>\xd9\xbe\xd8\xa7\xdb\x8c\xdb\x8c\xd8\xb2</title>
  <ht:approx_traffic>20K+</ht:approx_traffic>
  <ht:picture>https://example.com/a.png</ht:picture>
  <ht:news_item><ht:news_item_title>\xd8\xae\xd8\xa8\xd8\xb1 \xdb\x8c\xda\xa9</ht:news_item_title></ht:news_item>
</item>
<item>
  <title>\xd8\xb4\xd8\xa8 \xdb\x8c\xd9\x84\xd8\xaf\xd8\xa7</title>
  <ht:approx_traffic>5K+</ht:approx_traffic>
</item>
</channel></rss>"""


class FetchTests(TestCase):
    def _response(self, content=RSS, status=200):
        class Fake:
            def __init__(self):
                self.content = content
                self.status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise source.requests.HTTPError("boom")

        return Fake()

    def test_trends_are_read_from_the_published_feed(self):
        with patch.object(source.requests, "get", return_value=self._response()):
            rows = source.fetch_region("IR")
        self.assertEqual([r["title"] for r in rows], ["پاییز", "شب یلدا"])

    def test_the_traffic_figure_is_kept_as_written(self):
        """Parsing "20K+" into a number would add precision we do not have and
        would then have to defend."""
        with patch.object(source.requests, "get", return_value=self._response()):
            rows = source.fetch_region("IR")
        self.assertEqual(rows[0]["traffic"], "20K+")

    def test_a_source_that_is_down_says_so_rather_than_returning_nothing(self):
        """"Nothing is trending" and "we could not check" are different answers
        and lead to different decisions."""
        with patch.object(source.requests, "get", side_effect=source.requests.RequestException("down")):
            with self.assertRaises(source.TrendsUnavailable):
                source.fetch_region("IR")

    def test_one_region_failing_does_not_lose_the_others(self):
        calls = []

        def sometimes(*args, **kwargs):
            calls.append(kwargs.get("params", {}).get("geo"))
            if len(calls) == 1:
                raise source.requests.RequestException("down")
            return self._response()

        with patch.object(source.requests, "get", side_effect=sometimes):
            result = source.fetch(["IR", "US"])
        self.assertTrue(result["trends"])
        self.assertEqual(len(result["problems"]), 1)

    def test_an_unknown_region_is_refused(self):
        with self.assertRaises(ValueError):
            source.fetch_region("XX")

    def test_platforms_we_cannot_measure_are_listed_as_such(self):
        """A shop that cannot see Instagram trends should know we did not
        check, not conclude that nothing is happening there."""
        rows = {row["key"]: row for row in source.available()}
        self.assertFalse(rows["instagram"]["live"])
        self.assertTrue(rows["instagram"]["note"])


class FreshnessTests(TestCase):
    def test_a_trend_from_today_is_current(self):
        trend = Trend.objects.create(title="پاییز", seen_at=timezone.now())
        self.assertFalse(trend.is_stale)

    def test_a_trend_from_last_week_is_not(self):
        old = Trend.objects.create(
            title="نوروز", seen_at=timezone.now() - timedelta(days=7),
        )
        self.assertTrue(old.is_stale)

    def test_stale_trends_are_not_returned_as_current(self):
        Trend.objects.create(
            title="نوروز", seen_at=timezone.now() - timedelta(days=7),
        )
        Trend.objects.create(title="پاییز", seen_at=timezone.now())
        self.assertEqual([t.title for t in engine.current()], ["پاییز"])

    def test_refreshing_twice_in_one_day_does_not_duplicate_a_trend(self):
        """A trend still trending this afternoon is the same trend as this
        morning; a row per fetch turns one story into fourteen."""
        payload = {"trends": [{
            "title": "پاییز", "region": "IR", "region_title": "ایران",
            "traffic": "20K+", "image": "", "context": [], "source": "google_trends",
        }], "problems": []}
        with patch.object(source, "fetch", return_value=payload):
            engine.refresh(["IR"])
            second = engine.refresh(["IR"])
        self.assertEqual(Trend.objects.count(), 1)
        self.assertEqual(second["new"], 0)


class SuggestionTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("trend-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه کفش")
        self.product = Product.objects.create(
            store=self.store, name="کفش دویدن", price=1_000_000,
        )
        self.trend = Trend.objects.create(title="دو ماراتن", seen_at=timezone.now())

    def _suggest(self, ideas):
        with patch(
            "apps.ai.services.recorded_json_call", return_value=({"ideas": ideas}, None),
        ):
            return engine.suggest(self.store)

    def _idea(self, **overrides):
        return {
            "trend_id": self.trend.pk,
            "product_id": self.product.pk,
            "kind": "VIDEO",
            "idea": "ویدیوی آماده‌شدن برای ماراتن با این کفش",
            "hook": "سه هفته تا مسابقه",
            "why": "کفش دویدن دقیقاً چیزی است که کسی که برای ماراتن آماده می‌شود می‌خرد",
            **overrides,
        }

    def test_a_well_connected_idea_is_kept(self):
        result = self._suggest([self._idea()])
        self.assertEqual(len(result["ideas"]), 1)

    def test_an_idea_that_cannot_say_why_is_thrown_away(self):
        """A suggestion nobody can justify is noise wearing the costume of
        insight."""
        result = self._suggest([self._idea(why="این ترند محبوب است")])
        self.assertEqual(result["ideas"], [])
        self.assertEqual(result["dropped"], 1)

    def test_an_empty_reason_is_thrown_away(self):
        self.assertEqual(self._suggest([self._idea(why="")])["ideas"], [])

    def test_a_trend_the_model_invented_is_thrown_away(self):
        self.assertEqual(self._suggest([self._idea(trend_id=9999)])["ideas"], [])

    def test_an_empty_idea_is_thrown_away(self):
        self.assertEqual(self._suggest([self._idea(idea="")])["ideas"], [])

    def test_an_unknown_kind_falls_back_rather_than_failing(self):
        result = self._suggest([self._idea(kind="HOLOGRAM")])
        self.assertEqual(result["ideas"][0].kind, TrendIdea.Kind.VIDEO)

    def test_the_list_is_capped(self):
        """A shop reads three ideas and acts on one; it reads twenty and acts
        on none."""
        result = self._suggest([self._idea() for _ in range(20)])
        self.assertLessEqual(len(result["ideas"]), engine.MAX_IDEAS)

    def test_yesterdays_open_ideas_are_replaced_not_accumulated(self):
        self._suggest([self._idea()])
        self._suggest([self._idea(idea="ایده‌ی تازه")])
        self.assertEqual(
            TrendIdea.objects.filter(state=TrendIdea.State.OPEN).count(), 1,
        )

    def test_an_idea_the_shop_already_used_survives_a_refresh(self):
        """It is a record of what they made, not a suggestion any more."""
        self._suggest([self._idea()])
        used = TrendIdea.objects.first()
        used.state = TrendIdea.State.USED
        used.save()
        self._suggest([self._idea(idea="ایده‌ی تازه")])
        self.assertTrue(TrendIdea.objects.filter(pk=used.pk).exists())

    def test_a_shop_with_no_products_is_told_what_to_do(self):
        Product.objects.all().delete()
        result = engine.suggest(self.store)
        self.assertEqual(result["ideas"], [])
        self.assertIn("محصول", result["note"])

    def test_no_fresh_trends_is_not_an_error(self):
        Trend.objects.update(seen_at=timezone.now() - timedelta(days=7))
        result = engine.suggest(self.store)
        self.assertEqual(result["ideas"], [])
        self.assertIn("به‌روزرسانی", result["note"])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TrendAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("trend-api", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه ترند")
        self.product = Product.objects.create(
            store=self.store, name="کفش", price=1000,
        )
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/trends/"
        self.trend = Trend.objects.create(title="پاییز", seen_at=timezone.now())

    def _idea(self, **overrides):
        return TrendIdea.objects.create(
            store=self.store, trend=self.trend, product=self.product,
            idea="ویدیوی پاییزی", why="کفش پاییزی می‌فروشید", **overrides,
        )

    def test_the_page_says_which_sources_it_could_reach(self):
        body = self.client.get(self.base).json()
        self.assertTrue(body["sources"])
        self.assertIn("instagram", [s["key"] for s in body["sources"]])

    def test_stale_trends_are_not_shown(self):
        Trend.objects.update(seen_at=timezone.now() - timedelta(days=7))
        self.assertEqual(self.client.get(self.base).json()["trends"], [])

    def test_using_an_idea_starts_the_generation_itself(self):
        """§6.3: an idea that has to be retyped on another page is an idea most
        shops abandon."""
        idea = self._idea()
        with patch("apps.ai.views_trends.dispatch_job", return_value=None):
            response = self.client.post(f"{self.base}ideas/{idea.pk}/use/")
        self.assertEqual(response.status_code, 202)
        idea.refresh_from_db()
        self.assertEqual(idea.state, TrendIdea.State.USED)
        self.assertIsNotNone(idea.job_id)

    def test_an_idea_on_a_stale_trend_is_refused_not_warned_about(self):
        """The shop is about to spend GPU minutes on a moment that has passed."""
        idea = self._idea()
        Trend.objects.update(seen_at=timezone.now() - timedelta(days=7))
        response = self.client.post(f"{self.base}ideas/{idea.pk}/use/")
        self.assertEqual(response.status_code, 409)

    def test_an_idea_with_no_product_cannot_be_generated(self):
        idea = self._idea()
        idea.product = None
        idea.save()
        response = self.client.post(f"{self.base}ideas/{idea.pk}/use/")
        self.assertEqual(response.status_code, 400)

    def test_dismissing_an_idea_keeps_it_out_of_the_list(self):
        idea = self._idea()
        self.client.post(f"{self.base}ideas/{idea.pk}/dismiss/")
        self.assertEqual(self.client.get(self.base).json()["ideas"], [])

    def test_a_stranger_sees_nothing(self):
        stranger = User.objects.create_user("trend-stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.base).status_code, 404)

    def test_another_shops_idea_is_invisible(self):
        other_owner = User.objects.create_user("trend-other", password="x")
        other = Store.objects.create(owner=other_owner, name="دیگری")
        foreign = TrendIdea.objects.create(
            store=other, trend=self.trend, idea="x", why="y",
        )
        response = self.client.post(f"{self.base}ideas/{foreign.pk}/use/")
        self.assertEqual(response.status_code, 404)

    def test_a_dead_trend_source_reports_a_service_error_not_a_crash(self):
        with patch.object(engine, "refresh", side_effect=RuntimeError("down")):
            response = self.client.post(
                self.base, {"regions": ["IR"]}, content_type="application/json",
            )
        self.assertEqual(response.status_code, 503)
