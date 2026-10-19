"""Crawl parsing, «رقیب کالایی» matching, «کجا بفروشم», trend relevance.

All offline: HTML/XML fixtures are inline strings and every network call is
replaced by a fake session or a patched function.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.products.models import Product
from apps.stores.models import Store
from services.research import channels, product_match, shop_crawler
from services.research import trends as trend_source

from . import competitor_research, opportunities
from . import trends as engine
from .competitor_models import Competitor, CompetitorProduct, Opportunity
from .trend_models import Trend

# ---------------------------------------------------------------- fixtures

WOO_JSONLD = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"WebPage","name":"x"},
 {"@type":"Product","name":"قهوه ترک ۲۵۰ گرمی بن مانو","sku":"BM-250",
  "image":"/wp-content/uploads/bm.jpg","brand":{"@type":"Brand","name":"بن مانو"},
  "offers":[{"@type":"Offer","price":"1850000","priceCurrency":"IRR",
  "availability":"https://schema.org/InStock"}]}]}</script>
</head><body><h1>قهوه</h1></body></html>"""

WOO_IRT = """<script type="application/ld+json">
{"@type":"Product","name":"ماگ سرامیکی","offers":{"@type":"Offer","price":"185000","priceCurrency":"IRT"}}
</script>"""

OPENGRAPH = """<html><head>
<meta property="og:type" content="product" />
<meta property="og:title" content="کفش دویدن نایکی مدل Pegasus 40" />
<meta property="product:price:amount" content="۴٬۲۰۰٬۰۰۰" />
<meta property="product:price:currency" content="IRT" />
<meta property="og:image" content="https://shop.example/p.jpg" />
</head></html>"""

WOO_MARKUP = """<html><body class="product-template-default single-product woocommerce">
<h1 class="product_title entry-title">چای سبز ارگانیک</h1>
<p class="price"><del><span class="woocommerce-Price-amount amount"><bdi>۱۵۰,۰۰۰&nbsp;<span class="woocommerce-Price-currencySymbol">تومان</span></bdi></span></del>
<ins><span class="woocommerce-Price-amount amount"><bdi>۱۲۰,۰۰۰&nbsp;<span class="woocommerce-Price-currencySymbol">تومان</span></bdi></span></ins></p>
</body></html>"""

SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex>
<sitemap><loc>https://shop.example/post-sitemap.xml</loc></sitemap>
<sitemap><loc>https://shop.example/product-sitemap.xml</loc></sitemap>
</sitemapindex>"""

PRODUCT_SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://shop.example/product/coffee-a/</loc></url>
<url><loc>https://shop.example/product/coffee-b/</loc></url>
<url><loc>https://shop.example/product/secret/</loc></url>
</urlset>"""


class FakeResponse:
    def __init__(self, text, status=200, url=""):
        self.text = text
        self.status_code = status
        self.url = url
        self.encoding = "utf-8"

        class Raw:
            def __init__(self, data):
                self.data = data

            def read(self, n, decode_content=True):
                return self.data[:n]

        self.raw = Raw(text.encode("utf-8"))
        self._content = None


class FakeSession:
    """Serves a dict of url → html; records every GET."""

    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None, stream=False):
        self.calls.append(url)
        if url in self.pages:
            return FakeResponse(self.pages[url], url=url)
        return FakeResponse("not found", status=404, url=url)


# ---------------------------------------------------------------- parsing


class PriceParsingTests(SimpleTestCase):
    def test_persian_digits_and_separators(self):
        self.assertEqual(shop_crawler.parse_number("۱۲۵,۰۰۰"), 125000)
        self.assertEqual(shop_crawler.parse_number("۴٬۲۰۰٬۰۰۰"), 4200000)
        self.assertEqual(shop_crawler.parse_number("125.000"), 125000)
        self.assertEqual(shop_crawler.parse_number("125000.00"), 125000)
        self.assertIsNone(shop_crawler.parse_number("تماس بگیرید"))

    def test_rial_is_converted_and_toman_is_kept(self):
        self.assertEqual(shop_crawler.to_toman("1850000", "IRR")[0], 185000)
        self.assertEqual(shop_crawler.to_toman("185000", "IRT")[0], 185000)
        self.assertEqual(shop_crawler.to_toman("۱,۸۵۰,۰۰۰ ریال")[0], 185000)
        self.assertEqual(shop_crawler.to_toman("۱۸۵,۰۰۰ تومان")[0], 185000)

    def test_an_undeclared_currency_is_flagged_not_guessed(self):
        value, how = shop_crawler.to_toman("185000")
        self.assertEqual(value, 185000)
        self.assertEqual(how, "currency_guess")


class ExtractionTests(SimpleTestCase):
    def test_jsonld_graph_product_in_rial(self):
        item = shop_crawler.extract_product(WOO_JSONLD, "https://shop.example/product/bm/")
        self.assertEqual(item.name, "قهوه ترک ۲۵۰ گرمی بن مانو")
        self.assertEqual(item.price_toman, 185000)
        self.assertEqual(item.method, "json-ld")
        self.assertEqual(item.image, "https://shop.example/wp-content/uploads/bm.jpg")
        self.assertTrue(item.in_stock)
        self.assertEqual(item.brand, "بن مانو")

    def test_jsonld_in_toman(self):
        item = shop_crawler.extract_product(WOO_IRT, "https://shop.example/product/mug/")
        self.assertEqual(item.price_toman, 185000)

    def test_opengraph_product_price(self):
        item = shop_crawler.extract_product(OPENGRAPH, "https://shop.example/p/1")
        self.assertEqual(item.price_toman, 4200000)
        self.assertIn("Pegasus", item.name)

    def test_woocommerce_markup_takes_the_sale_price(self):
        item = shop_crawler.extract_product(WOO_MARKUP, "https://shop.example/product/tea/")
        self.assertEqual(item.name, "چای سبز ارگانیک")
        self.assertEqual(item.price_toman, 120000)
        self.assertEqual(item.method, "woocommerce")

    def test_a_page_without_product_markup_is_not_a_product(self):
        self.assertIsNone(shop_crawler.extract_product("<h1>درباره ما</h1> قیمت ۱۰۰۰ تومان", "https://x/"))

    def test_sitemap_and_url_rules(self):
        children, pages = shop_crawler.parse_sitemap(SITEMAP_INDEX)
        self.assertEqual(len(children), 2)
        self.assertEqual(pages, [])
        ranked = shop_crawler.rank_child_sitemaps(children)
        self.assertIn("product", ranked[0])
        self.assertTrue(shop_crawler.looks_like_product_url("https://s/product/abc/"))
        self.assertTrue(shop_crawler.looks_like_product_url("https://s/محصول/قهوه/"))
        self.assertFalse(shop_crawler.looks_like_product_url("https://s/product-category/coffee/"))


class CrawlTests(SimpleTestCase):
    def test_crawl_respects_robots_and_reads_products(self):
        page = WOO_JSONLD
        session = FakeSession({
            "https://shop.example/robots.txt": "User-agent: *\nDisallow: /product/secret/\nSitemap: https://shop.example/sitemap_index.xml",
            "https://shop.example/sitemap_index.xml": SITEMAP_INDEX,
            "https://shop.example/product-sitemap.xml": PRODUCT_SITEMAP,
            "https://shop.example/product/coffee-a/": page,
            "https://shop.example/product/coffee-b/": WOO_MARKUP,
            "https://shop.example/product/secret/": page,
        })
        report = shop_crawler.crawl("shop.example", max_pages=10, delay=0, session=session)
        names = [p["name"] for p in report.products]
        self.assertEqual(len(names), 2)
        self.assertIn("چای سبز ارگانیک", names)
        self.assertEqual(report.robots_blocked, 1)
        self.assertNotIn("https://shop.example/product/secret/", session.calls)
        self.assertEqual(report.discovery, "sitemap")

    def test_max_pages_bounds_the_crawl(self):
        pages = {"https://shop.example/robots.txt": ""}
        urls = "".join(f"<url><loc>https://shop.example/product/p{i}/</loc></url>" for i in range(20))
        pages["https://shop.example/sitemap.xml"] = f"<urlset>{urls}</urlset>"
        for i in range(20):
            pages[f"https://shop.example/product/p{i}/"] = WOO_IRT.replace("ماگ سرامیکی", f"ماگ {i}")
        session = FakeSession(pages)
        report = shop_crawler.crawl("https://shop.example", max_pages=5, delay=0, session=session)
        self.assertEqual(len(report.products), 5)
        self.assertEqual(report.stopped, "max_pages")


# ---------------------------------------------------------------- matching


class MatchTests(SimpleTestCase):
    def test_normalisation(self):
        self.assertEqual(product_match.normalize("كيف‌ چرمي ۲"), "کیف چرمی 2")
        self.assertEqual(product_match.tokens("قهوه ۲۵۰ گرمی"), ["قهوه", "250g"])
        self.assertEqual(product_match.tokens("قهوه 250g"), ["قهوه", "250g"])

    def test_same_product_with_noisy_title(self):
        result = product_match.match_product(
            "قهوه ترک بن مانو ۲۵۰ گرم", "خرید قهوه ترک بن مانو مقدار 250 گرم - اصل",
            our_price=200_000, their_price=185_000,
        )
        self.assertEqual(result.verdict, "same")
        self.assertIn("250g", result.shared)

    def test_different_size_is_not_the_same_product(self):
        result = product_match.match_product(
            "قهوه ترک بن مانو ۲۵۰ گرم", "قهوه ترک بن مانو 1000 گرم",
            our_price=200_000, their_price=700_000,
        )
        self.assertNotEqual(result.verdict, "same")
        self.assertTrue(result.conflicts)

    def test_unrelated_product(self):
        result = product_match.match_product("قهوه ترک", "شارژر سامسونگ 45 وات")
        self.assertEqual(result.verdict, "different")

    def test_a_one_word_name_needs_the_price_to_agree(self):
        far = product_match.match_product("قهوه", "پودر قهوه اسپرسو ونزکافه", our_price=250_000, their_price=2_000_000)
        near = product_match.match_product("قهوه", "قهوه ۲۵۰ گرمی", our_price=250_000, their_price=280_000)
        long_title = product_match.match_product(
            "قهوه", "قهوه هسته خرما یک کیلویی", our_price=250_000, their_price=169_000,
        )
        self.assertNotEqual(far.verdict, "same")
        self.assertEqual(near.verdict, "same")
        self.assertEqual(long_title.verdict, "maybe")

    def test_a_substitute_confirmed_by_the_model_makes_a_product_competitor(self):
        verdict = product_match.classify_competitor(
            [{"verdict": "maybe", "llm": {"same": False, "substitute": True}, "our_product_id": 1}]
        )
        self.assertTrue(verdict["confirmed"])
        self.assertEqual(verdict["substitute"], 1)

    def test_competitor_verdict(self):
        self.assertTrue(product_match.classify_competitor([{"verdict": "same", "our_product_id": 1}])["confirmed"])
        self.assertEqual(product_match.classify_competitor([{"verdict": "maybe"}])["status"], "maybe")
        self.assertTrue(product_match.classify_competitor(
            [{"verdict": "maybe", "llm": {"same": True}, "our_product_id": 1}])["confirmed"])
        self.assertEqual(product_match.classify_competitor([])["status"], "unknown")


class CompetitorStorageTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("crawl-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="قهوه‌فروشی")
        self.product = Product.objects.create(store=self.store, name="قهوه ترک بن مانو ۲۵۰ گرم", price=200_000)
        self.rival = Competitor.objects.create(store=self.store, name="رقیب", website="https://shop.example")

    def test_crawl_rows_are_upserted_and_matched(self):
        items = [
            {"name": "قهوه ترک بن مانو 250 گرم", "url": "https://shop.example/product/a/", "price_toman": 190_000},
            {"name": "ماگ سرامیکی", "url": "https://shop.example/product/b/", "price_toman": 90_000},
        ]
        self.assertEqual(competitor_research.save_crawl(self.rival, items)["created"], 2)
        items[0]["price_toman"] = 180_000
        self.assertEqual(competitor_research.save_crawl(self.rival, items)["updated"], 2)
        verdict = competitor_research.match_competitor(self.rival)
        self.assertTrue(verdict["confirmed"])
        row = CompetitorProduct.objects.get(name__startswith="قهوه")
        self.assertEqual(row.matches, self.product)
        self.assertEqual(row.price_toman, 180_000)
        self.assertIsNone(CompetitorProduct.objects.get(name="ماگ سرامیکی").matches)

    def test_a_manual_match_is_never_overwritten(self):
        row = CompetitorProduct.objects.create(
            competitor=self.rival, name="چیزی کاملاً دیگر", matches=self.product,
            raw={"matches_manual": True},
        )
        competitor_research.match_competitor(self.rival)
        row.refresh_from_db()
        self.assertEqual(row.matches, self.product)

    def test_long_persian_urls_are_kept_in_raw(self):
        url = "https://shop.example/product/" + "قهوه-" * 60
        competitor_research.save_crawl(self.rival, [{"name": "x", "url": url, "price_toman": 1}])
        row = CompetitorProduct.objects.get(name="x")
        self.assertEqual(row.url, "")
        self.assertEqual(row.raw["url"], url)

    def test_discover_suggests_sellers_of_matching_listings(self):
        fake = {
            "digikala": lambda q, n: [
                {"title": "قهوه ترک بن مانو مقدار 250 گرم", "price_toman": 210_000, "url": "https://dk/p1",
                 "seller": "تجارت اطلس", "seller_url": "https://www.digikala.com/seller/X/"},
                {"title": "شارژر سامسونگ", "price_toman": 900_000, "url": "https://dk/p2", "seller": "موبایل‌شاپ"},
            ],
            "basalam": lambda q, n: [],
        }
        with patch.dict(competitor_research.web.SOURCES, fake):
            result = competitor_research.discover(self.store)
        names = [s["name"] for s in result["suggestions"]]
        self.assertEqual(names, ["تجارت اطلس"])
        added = competitor_research.add_suggestion(self.store, result["suggestions"][0])
        self.assertEqual(added.products.count(), 1)
        self.assertEqual(added.products.first().matches, self.product)


# ---------------------------------------------------------------- «کجا بفروشم»


class ChannelTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("chan-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="قهوه")
        self.product = Product.objects.create(store=self.store, name="قهوه ترک بن مانو ۲۵۰ گرم", price=200_000)

    def _presence(self, rows, channel="basalam"):
        with patch.dict(channels.web.SOURCES, {channel: lambda q, n: rows}):
            return channels.presence(channel, self.product.name, 200_000)

    def test_presence_counts_only_matching_listings(self):
        row = self._presence([
            {"title": "قهوه ترک بن مانو 250 گرم", "price_toman": 220_000, "seller": "a", "sales_count": 40, "sales_count_week": 3},
            {"title": "قهوه ترک بن مانو ۲۵۰ گرمی اصل", "price_toman": 240_000, "seller": "b", "sales_count": 10},
            {"title": "کیف چرمی", "price_toman": 100_000, "seller": "c"},
        ])
        self.assertEqual(row["relevant"], 2)
        self.assertEqual(row["sellers"], 2)
        self.assertEqual(row["min_price"], 220_000)
        self.assertEqual(row["demand"]["total"], 50)

    def test_a_blocked_marketplace_is_reported_not_hidden(self):
        def boom(q, n):
            raise RuntimeError("captcha")
        with patch.dict(channels.web.SOURCES, {"torob": boom}):
            row = channels.presence("torob", "قهوه", 1000)
        self.assertFalse(row["ok"])
        self.assertIn("captcha", row["error"])

    def test_competitive_price_becomes_a_channel_suggestion(self):
        row = self._presence([
            {"title": "قهوه ترک بن مانو 250 گرم", "price_toman": 220_000, "seller": "a", "sales_count": 40},
            {"title": "قهوه ترک بن مانو 250 گرم", "price_toman": 260_000, "seller": "b", "sales_count": 5},
        ])
        found = opportunities.channel_suggestions(self.product, {"basalam": row})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], Opportunity.Kind.CHANNEL)
        self.assertIn("باسلام", found[0]["title"])
        self.assertEqual(found[0]["evidence"]["median_price"], 240_000)

    def test_no_listings_is_not_an_opportunity(self):
        row = self._presence([{"title": "کیف", "price_toman": 1, "seller": "x"}])
        self.assertEqual(opportunities.channel_suggestions(self.product, {"basalam": row}), [])

    def test_refresh_does_not_close_channel_rows_it_did_not_recheck(self):
        Opportunity.objects.create(
            store=self.store, product=self.product, kind=Opportunity.Kind.CHANNEL,
            title="t", reason="r", action="a", evidence={"channel": "basalam"},
        )
        opportunities.refresh(self.store)  # no channel check this time
        self.assertEqual(Opportunity.objects.get(title="t").state, Opportunity.State.OPEN)

    def test_readiness_lists_what_is_missing(self):
        data = opportunities.readiness(self.store)
        keys = {i["key"]: i for i in data["items"]}
        self.assertFalse(keys["cost_price"]["done"])
        self.assertEqual(keys["cost_price"]["unlocks_count"], 1)
        self.assertEqual(keys["cost_price"]["fix"]["to"], f"/products/{self.product.pk}")
        self.assertFalse(keys["competitors"]["done"])
        self.assertFalse(keys["channels"]["done"])


# ---------------------------------------------------------------- trends


GOOGLE_RSS = """<?xml version="1.0"?>
<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>la mode des mocassins</title><ht:approx_traffic>2000+</ht:approx_traffic>
<ht:news_item><ht:news_item_title>Les mocassins, chaussures de la rentrée</ht:news_item_title>
<ht:news_item_url>https://news.example/a</ht:news_item_url><ht:news_item_source>Le Monde</ht:news_item_source></ht:news_item>
</item>
<item><title>meteo toulon</title><ht:approx_traffic>200+</ht:approx_traffic></item>
</channel></rss>"""


class TrendTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("trend-rel", password="x")
        self.store = Store.objects.create(owner=owner, name="کفش‌فروشی", business_type="پوشاک")
        Product.objects.create(store=self.store, name="کفش چرم مردانه", price=1_000_000)

    def test_news_items_are_kept_with_link_and_source(self):
        rows = trend_source.parse_rss(GOOGLE_RSS.encode(), "FR")
        self.assertEqual(rows[0]["context"][0]["url"], "https://news.example/a")
        self.assertEqual(rows[0]["context"][0]["source"], "Le Monde")
        self.assertEqual(rows[0]["region_title"], "فرانسه")

    def test_relevance_crosses_languages_through_the_lexicon(self):
        vocabulary = engine.store_vocabulary(self.store)
        fashion = Trend.objects.create(
            title="la mode des mocassins", region="FR",
            context=[{"title": "Les mocassins, chaussures de la rentrée", "url": "", "source": ""}],
        )
        weather = Trend.objects.create(title="meteo toulon", region="FR")
        self.assertEqual(engine.relevance(fashion, vocabulary)["key"], "high")
        self.assertEqual(engine.relevance(weather, vocabulary)["key"], "none")

    def test_regions_expand(self):
        self.assertEqual(trend_source.expand_regions(["ALL"]), list(trend_source.REGIONS))
        self.assertIn("IG", trend_source.expand_regions(["IR", "IG"]))
        self.assertEqual(trend_source.expand_regions(["XX"]), ["IR"])

    def test_instagram_source_keeps_only_recent_trend_headlines(self):
        now = datetime.now(dt_timezone.utc)
        fake = [
            {"title": "Instagram's new viral trend: #coffeeart reels", "url": "u1", "publisher": "P",
             "published": now.isoformat()},
            {"title": "Old trend from last year", "url": "u2", "publisher": "P",
             "published": (now - timedelta(days=40)).isoformat()},
            {"title": "Meta quarterly earnings", "url": "u3", "publisher": "P", "published": now.isoformat()},
        ]
        with patch("services.research.web.google_news", return_value=fake), \
                patch("services.research.web.web_search_configured", return_value=False):
            rows = trend_source.fetch_instagram()
        self.assertEqual([r["title"] for r in rows], ["Instagram's new viral trend: #coffeeart reels"])
        self.assertEqual(rows[0]["context"][0]["hashtags"], ["coffeeart"])
        self.assertEqual(rows[0]["source"], "instagram_news")

    def test_template_idea_without_a_model_only_for_relevant_trends(self):
        relevant = Trend.objects.create(title="mocassins chaussures", region="FR", seen_at=timezone.now())
        unrelated = Trend.objects.create(title="meteo toulon", region="FR", seen_at=timezone.now())
        with patch("apps.ai.research_llm.status", return_value=(False, "offline")):
            ok = engine.suggest(self.store, trend_ids=[relevant.pk])
            none = engine.suggest(self.store, trend_ids=[unrelated.pk])
        self.assertEqual(len(ok["ideas"]), 1)
        self.assertIn("قالبِ ساده", ok["ideas"][0].idea)
        self.assertEqual([i for i in none["ideas"] if i.trend_id == unrelated.pk], [])
