"""The provider layer: API fetching, Nominatim, Overpass, the keyed search APIs. Everything runs against a fake web."""
from __future__ import annotations

import httpx
from django.test import SimpleTestCase, TestCase

from apps.growth_engine.core.testing import NoNetworkMixin
from apps.growth_engine.discovery.models import GeoCache
from apps.growth_engine.discovery.providers import ProviderContext, ProviderError, SearchQuery, categories, nominatim, osm, search_api
from apps.growth_engine.discovery.providers.osm import OsmProvider, area_id, build_query, parse_elements
from apps.growth_engine.discovery.services import geo
from apps.growth_engine.integrations import safe_http as sh

from .helpers import HAMEDAN, NOMINATIM, OVERPASS, FakeApis, make_fetcher, overpass_payload, query_of, shop

PLACE = {"name": "همدان", "osm_type": "relation", "osm_id": 5800122, "bbox": [34.72, 34.86, 48.43, 48.60], "lat": 34.79, "lon": 48.51}


class GetApiTests(NoNetworkMixin, SimpleTestCase):
    def test_sends_an_honest_user_agent_asks_for_json_and_never_reads_robots_txt(self):
        apis = FakeApis().json("api.example.test", {"ok": True})
        fetcher, _ = make_fetcher(apis)
        result = fetcher.get_api("https://api.example.test/v1/thing", params={"q": "x"})
        self.assertEqual((result.outcome, result.status), (sh.OK, 200))
        request = apis.requests[0]
        self.assertIn("NMarketingBot", request.headers["user-agent"])
        self.assertEqual(request.headers["accept"], "application/json")
        self.assertEqual([r.url.path for r in apis.requests], ["/v1/thing"])  # no /robots.txt

    def test_secrets_in_the_query_never_appear_in_the_result(self):
        apis = FakeApis().json("api.example.test", {"ok": True})
        fetcher, _ = make_fetcher(apis)
        result = fetcher.get_api("https://api.example.test/v1", params={"key": "SECRET-KEY-123", "cx": "ENGINE-ID-9", "q": "shoes"})
        self.assertNotIn("SECRET-KEY-123", result.url + result.final_url)
        self.assertNotIn("ENGINE-ID-9", result.url + result.final_url)
        self.assertIn("q=shoes", result.url)
        self.assertEqual(apis.requests[0].url.params["key"], "SECRET-KEY-123")  # but the real request carried it

    def test_the_ssrf_guard_and_the_port_rule_apply_to_api_calls_too(self):
        apis = FakeApis().json("api.example.test", {})
        private, _ = make_fetcher(apis, resolver=lambda h, p: ["10.0.0.5"])
        self.assertEqual(private.get_api("https://api.example.test/").outcome, sh.SSRF_BLOCKED)
        fetcher, _ = make_fetcher(apis)
        self.assertEqual(fetcher.get_api("https://api.example.test:22/").outcome, sh.BLOCKED_PORT)
        self.assertEqual(apis.requests, [])

    def test_custom_headers_are_sent_and_transient_errors_are_retried_with_the_given_backoff(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"n": len(calls)})

        apis = FakeApis().on("api.example.test", handler)
        fetcher, clock = make_fetcher(apis)
        result = fetcher.get_api("https://api.example.test/", headers={"X-Subscription-Token": "tok-123456"}, retries=1, backoff=(7.0,))
        self.assertEqual(result.status, 200)
        self.assertEqual(calls[0].headers["x-subscription-token"], "tok-123456")
        self.assertIn(7.0, clock.slept)


class CategoryTests(SimpleTestCase):
    def test_every_preset_has_safe_tags(self):
        self.assertGreaterEqual(len(categories.PRESETS), 12)
        for key, _label, _tags in categories.PRESETS:
            for k, v in categories.tags_of(key):
                self.assertRegex(k, categories.SAFE_TAG)
                self.assertTrue(v == "*" or categories.SAFE_TAG.match(v), (key, v))

    def test_the_requested_shop_types_are_covered(self):
        wanted = {"clothes": "clothes", "cosmetics": "cosmetics", "jewelry": "jewelry", "shoes": "shoes", "bags": "bag", "gifts": "gift"}
        for key, value in wanted.items():
            self.assertIn(("shop", value), categories.tags_of(key), key)

    def test_unknown_key_is_not_a_preset(self):
        self.assertIsNone(categories.tags_of('clothes"];out;'))
        self.assertEqual(categories.label_of("nope"), "")


class NominatimTests(NoNetworkMixin, TestCase):
    def test_picks_the_settlement_and_returns_its_area(self):
        apis = FakeApis().json(NOMINATIM, [
            {"osm_type": "node", "osm_id": 7, "category": "shop", "importance": 0.9, "display_name": "فروشگاه همدان", "lat": "1", "lon": "2", "boundingbox": ["1", "1.1", "2", "2.1"]},
            *HAMEDAN,
        ])
        fetcher, _ = make_fetcher(apis)
        place = nominatim.lookup(fetcher, "همدان", "IR")
        self.assertEqual((place["osm_type"], place["osm_id"]), ("relation", 5800122))
        self.assertEqual(place["bbox"], [34.72, 34.86, 48.43, 48.60])
        params = apis.requests[0].url.params
        self.assertEqual((params["q"], params["countrycodes"], params["format"]), ("همدان", "ir", "jsonv2"))

    def test_unknown_city_and_a_busy_service_are_different_errors(self):
        fetcher, _ = make_fetcher(FakeApis().json(NOMINATIM, []))
        with self.assertRaises(ProviderError) as cm:
            nominatim.lookup(fetcher, "شهرِ ساختگی", "IR")
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("city_not_found", False))
        busy, _ = make_fetcher(FakeApis().json(NOMINATIM, {"error": "x"}, status=503))
        with self.assertRaises(ProviderError) as cm:
            nominatim.lookup(busy, "همدان", "IR")
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("service_busy", True))

    def test_the_answer_is_cached_so_the_same_city_is_asked_once(self):
        apis = FakeApis().json(NOMINATIM, HAMEDAN)
        fetcher, _ = make_fetcher(apis)
        first = geo.geocode(fetcher, "همدان", "IR")
        second = geo.geocode(fetcher, " همدان ", "IR")  # spelled with spaces: same key
        third = geo.geocode(fetcher, "همدان", "IR")
        self.assertEqual((first["cached"], second["cached"], third["cached"]), (False, True, True))
        self.assertEqual(len(apis.to(NOMINATIM)), 1)
        self.assertEqual(GeoCache.objects.count(), 1)

    def test_two_different_cities_are_at_least_a_second_apart(self):
        apis = FakeApis().json(NOMINATIM, HAMEDAN)
        fetcher, clock = make_fetcher(apis)
        geo.geocode(fetcher, "همدان", "IR")
        geo.geocode(fetcher, "ملایر", "IR")
        self.assertTrue(any(s >= 1.0 for s in clock.slept), clock.slept)

    def test_a_bad_endpoint_url_is_refused(self):
        with self.assertRaises(ProviderError):
            nominatim.validate_url("ftp://nominatim.example/")


class OverpassTests(NoNetworkMixin, TestCase):
    def ctx(self, apis, **settings):
        fetcher, clock = make_fetcher(apis)
        ctx = ProviderContext(fetcher=fetcher, settings=settings, geocode=lambda city, country: PLACE)
        return ctx, apis, clock

    def test_the_query_uses_the_city_area_and_only_the_preset_tags(self):
        ql = build_query(categories.tags_of("clothes"), PLACE, 400)
        self.assertIn("area(3605800122)->.a;", ql)
        self.assertIn('nwr["shop"="clothes"](area.a);', ql)
        self.assertIn('nwr["shop"="boutique"](area.a);', ql)
        self.assertIn("out center tags 400;", ql)
        self.assertTrue(ql.startswith("[out:json][timeout:60];"))

    def test_a_place_without_an_area_falls_back_to_the_bounding_box(self):
        node = {**PLACE, "osm_type": "node"}
        self.assertIsNone(area_id(node))
        ql = build_query([("shop", "gift")], node, 50)
        self.assertIn('nwr["shop"="gift"](34.720000,48.430000,34.860000,48.600000);', ql)
        self.assertNotIn("area(", ql)

    def test_elements_become_candidates_with_only_what_the_mapper_wrote(self):
        elements = [
            shop(1, "پوشاک آرمان", name__fa="پوشاک آرمان", phone="+98 912 111 1111; 081-38221100", website="https://arman.example/?utm_source=x",
                 email="info@arman.example", contact__instagram="https://instagram.com/arman_shop", addr__street="بوعلی", addr__housenumber="12", opening_hours="Mo-Fr 09:00-20:00"),
            shop(2, "بدون راه تماس"),
            shop(3, "شمارهٔ خراب", phone="123; abc", etype="way"),
            {"type": "node", "id": 4, "tags": {"shop": "clothes"}},  # no name -> never a lead
        ]
        out = parse_elements(elements, category_label="پوشاک و لباس", city="همدان")
        by_id = {c.external_id: c for c in out}
        self.assertEqual(set(by_id), {"node/1", "node/2", "way/3"})
        first = by_id["node/1"]
        self.assertEqual(first.phone, ["09121111111", "08138221100"])
        self.assertEqual(first.email, ["info@arman.example"])
        self.assertTrue(first.website.startswith("https://arman.example"))
        self.assertNotIn("utm_source", first.website)
        self.assertEqual(first.instagram, "https://www.instagram.com/arman_shop/")
        self.assertEqual((first.category, first.city), ("پوشاک و لباس", "همدان"))
        self.assertEqual(first.address, "بوعلی، پلاک 12")
        self.assertEqual(first.source_ref, "osm:node/1")
        self.assertEqual(first.source_url, "https://www.openstreetmap.org/node/1")
        self.assertEqual(first.extra["opening_hours"], "Mo-Fr 09:00-20:00")
        self.assertEqual(by_id["way/3"].phone, [])
        self.assertEqual(sorted(by_id["way/3"].dropped), ["123", "abc"])  # dropped, not fatal

    def test_fetch_filters_candidates_without_contact_and_respects_max_results(self):
        elements = [shop(i, f"فروشگاه {i}", website=f"https://s{i}.example/") for i in range(1, 8)] + [shop(99, "بی‌تماس")]
        apis = FakeApis().json(OVERPASS, overpass_payload(*elements))
        ctx, apis, _ = self.ctx(apis)
        got = OsmProvider().fetch(SearchQuery(category="clothes", city="همدان", max_results=5), ctx)
        self.assertEqual(len(got), 5)
        self.assertTrue(all(c.has_contact for c in got))
        loose = OsmProvider().fetch(SearchQuery(category="clothes", city="همدان", max_results=50, require_contact=False), ctx)
        self.assertEqual(len(loose), 8)

    def test_one_query_with_the_polite_headers(self):
        apis = FakeApis().json(OVERPASS, overpass_payload(shop(1, "الف", website="https://a.example/")))
        ctx, apis, _ = self.ctx(apis)
        OsmProvider().fetch(SearchQuery(category="clothes", city="همدان", max_results=10), ctx)
        self.assertEqual(len(apis.to(OVERPASS)), 1)
        request = apis.to(OVERPASS)[0]
        self.assertIn("NMarketingBot", request.headers["user-agent"])
        self.assertIn('"shop"="clothes"', query_of(request))

    def test_when_the_area_returns_nothing_one_bounding_box_query_follows(self):
        seen = []

        def handler(request):
            ql = query_of(request)
            seen.append(ql)
            if "area.a" in ql:
                return httpx.Response(200, json=overpass_payload())
            return httpx.Response(200, json=overpass_payload(shop(1, "الف", website="https://a.example/")))

        ctx, apis, _ = self.ctx(FakeApis().on(OVERPASS, handler))
        got = OsmProvider().fetch(SearchQuery(category="shoes", city="همدان", max_results=5), ctx)
        self.assertEqual(len(got), 1)
        self.assertEqual(len(seen), 2)
        self.assertNotIn("area.a", seen[1])

    def test_busy_server_moves_on_to_the_next_mirror(self):
        apis = FakeApis()
        apis.json(OVERPASS, {"error": "busy"}, status=502)
        apis.json("mirror.example.org", overpass_payload(shop(1, "الف", website="https://a.example/")))
        ctx, apis, _ = self.ctx(apis, overpass_endpoints=[f"https://{OVERPASS}/api/interpreter", "https://mirror.example.org/api/interpreter"])
        got = OsmProvider().fetch(SearchQuery(category="clothes", city="همدان", max_results=5), ctx)
        self.assertEqual(len(got), 1)
        self.assertIn("mirror.example.org", apis.hosts())

    def test_when_every_server_is_busy_the_error_is_plain_and_retryable(self):
        apis = FakeApis().json(OVERPASS, {"error": "busy"}, status=504)
        ctx, _, _ = self.ctx(apis)
        with self.assertRaises(ProviderError) as cm:
            OsmProvider().fetch(SearchQuery(category="clothes", city="همدان", max_results=5), ctx)
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("service_busy", True))
        self.assertIn("دوباره امتحان کنید", cm.exception.message)

    def test_a_query_the_server_gave_up_on_is_reported_as_too_big(self):
        apis = FakeApis().json(OVERPASS, overpass_payload(remark="runtime error: Query timed out in \"query\" at line 3 after 61 seconds."))
        ctx, _, _ = self.ctx(apis)
        with self.assertRaises(ProviderError) as cm:
            OsmProvider().fetch(SearchQuery(category="clothes", city="همدان", max_results=5), ctx)
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("query_too_big", False))

    def test_unknown_category_is_refused_before_any_request(self):
        ctx, apis, _ = self.ctx(FakeApis())
        with self.assertRaises(ProviderError) as cm:
            OsmProvider().fetch(SearchQuery(category="x", city="همدان"), ctx)
        self.assertEqual(cm.exception.code, "bad_category")
        self.assertEqual(apis.requests, [])

    def test_the_licence_line_is_part_of_the_provider(self):
        provider = OsmProvider()
        self.assertEqual(provider.attribution, "© OpenStreetMap contributors (ODbL)")
        self.assertIn("openstreetmap.org/copyright", provider.attribution_url)
        self.assertEqual(provider.source_provider, "osm_overpass")


class SearchApiTests(NoNetworkMixin, SimpleTestCase):
    BRAVE = "api.search.brave.com"
    GOOGLE = "www.googleapis.com"

    def brave_payload(self, *urls):
        return {"web": {"results": [{"title": f"فروشگاه {i} | لباس زنانه", "url": u, "description": f"توضیح {i}"} for i, u in enumerate(urls, 1)]}}

    def test_blocked_hosts_and_marketplaces_are_never_candidates(self):
        results = [
            {"title": "x", "url": "https://www.instagram.com/shop"}, {"title": "y", "url": "https://basalam.com/shop"},
            {"title": "z", "url": "https://shop.digikala.com/p"}, {"title": "w", "url": "https://torob.com/p"},
            {"title": "d", "url": "https://divar.ir/v/1"}, {"title": "فروشگاه رها | کالا", "url": "https://www.rahashop.example/about"},
            {"title": "ok2", "url": "https://rahashop.example/other"},
        ]
        seen: set[str] = set()
        out = search_api.candidates_from_results(results, provider="brave", category="لباس", city="همدان", seen=seen)
        self.assertEqual([c.website for c in out], ["https://rahashop.example"])
        self.assertEqual(out[0].name, "فروشگاه رها")
        self.assertEqual(out[0].source_url, "https://www.rahashop.example/about")
        self.assertEqual(out[0].source_ref, "search:brave:rahashop.example")
        self.assertTrue(out[0].extra["from_search"])

    def test_brave_sends_the_key_only_in_its_header_and_never_in_what_is_stored(self):
        apis = FakeApis().json(self.BRAVE, self.brave_payload("https://a.example/", "https://b.example/"))
        fetcher, _ = make_fetcher(apis)
        ctx = ProviderContext(fetcher=fetcher, secrets={"api_key": "BRAVE-KEY-ABCDEF"})
        out = search_api.BraveProvider().fetch(SearchQuery(category="فروشگاه لباس", city="همدان", max_results=10), ctx)
        self.assertEqual([c.website for c in out], ["https://a.example", "https://b.example"])
        request = apis.requests[0]
        self.assertEqual(request.headers["x-subscription-token"], "BRAVE-KEY-ABCDEF")
        self.assertNotIn("BRAVE-KEY-ABCDEF", str(request.url))
        self.assertEqual(request.url.params["q"], "فروشگاه لباس همدان")
        self.assertNotIn("BRAVE-KEY-ABCDEF", repr([c.to_row("brave_search") for c in out]))

    def test_google_sends_key_and_engine_and_maps_quota_errors(self):
        apis = FakeApis().json(self.GOOGLE, {"items": [{"title": "فروشگاه | الف", "link": "https://g.example/x", "snippet": "s"}]})
        fetcher, _ = make_fetcher(apis)
        ctx = ProviderContext(fetcher=fetcher, secrets={"api_key": "GOOGLE-KEY-12345", "cx": "ENGINE-ID-0001"})
        out = search_api.GoogleCseProvider().fetch(SearchQuery(category="کیف", city="تهران", max_results=10), ctx)
        self.assertEqual(out[0].website, "https://g.example")
        params = apis.requests[0].url.params
        self.assertEqual((params["key"], params["cx"], params["num"]), ("GOOGLE-KEY-12345", "ENGINE-ID-0001", "10"))

        quota = FakeApis().json(self.GOOGLE, {"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}, status=403)
        fetcher2, _ = make_fetcher(quota)
        with self.assertRaises(ProviderError) as cm:
            search_api.GoogleCseProvider().fetch(SearchQuery(category="کیف", city="تهران", max_results=5), ProviderContext(fetcher=fetcher2, secrets={"api_key": "GOOGLE-KEY-12345", "cx": "ENGINE-ID-0001"}))
        self.assertEqual((cm.exception.code, cm.exception.retryable), ("quota", True))
        bad = FakeApis().json(self.GOOGLE, {"error": {"errors": [{"reason": "keyInvalid"}]}}, status=400)
        fetcher3, _ = make_fetcher(bad)
        with self.assertRaises(ProviderError) as cm:
            search_api.GoogleCseProvider().fetch(SearchQuery(category="کیف", city="تهران", max_results=5), ProviderContext(fetcher=fetcher3, secrets={"api_key": "GOOGLE-KEY-12345", "cx": "ENGINE-ID-0001"}))
        self.assertEqual(cm.exception.code, "bad_key")

    def test_no_key_means_no_request(self):
        apis = FakeApis().json(self.BRAVE, {})
        fetcher, _ = make_fetcher(apis)
        with self.assertRaises(ProviderError) as cm:
            search_api.BraveProvider().fetch(SearchQuery(category="x y", city="a"), ProviderContext(fetcher=fetcher, secrets={}))
        self.assertEqual(cm.exception.code, "no_key")
        self.assertEqual(apis.requests, [])

    def test_pages_follow_max_results_and_stop_when_results_run_out(self):
        pages = []

        def handler(request):
            pages.append(request.url.params["offset"])
            return httpx.Response(200, json=self.brave_payload(*[f"https://p{request.url.params['offset']}-{i}.example/" for i in range(20)]) if len(pages) <= 2 else {"web": {"results": []}})

        fetcher, _ = make_fetcher(FakeApis().on(self.BRAVE, handler))
        out = search_api.BraveProvider().fetch(SearchQuery(category="لباس زنانه", city="", max_results=30), ProviderContext(fetcher=fetcher, secrets={"api_key": "BRAVE-KEY-ABCDEF"}))
        self.assertEqual(len(out), 30)
        self.assertEqual(pages, ["0", "1"])

    def test_title_names(self):
        self.assertEqual(search_api.name_from_title("فروشگاه رها | لباس زنانه", "x.ir"), "فروشگاه رها")
        self.assertEqual(search_api.name_from_title("", "x.ir"), "x.ir")
        self.assertEqual(search_api.name_from_title("Shop - Best prices", "x.ir"), "Shop")
