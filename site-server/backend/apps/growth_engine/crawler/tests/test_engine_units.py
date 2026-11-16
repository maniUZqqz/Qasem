"""Units of the finder's engine: names and distances, candidate merging, the sources' parsers, scoring. No network, no real clock."""
from __future__ import annotations

import base64

from django.test import TestCase

from apps.growth_engine.core import normalization as nz

from .. import presets
from ..engine import candidates, extras, scoring, textnorm
from ..engine.sources import directory, osm, search
from ..models import CrawlCandidate, CrawlMission, CrawlRun
from .helpers import BADANFIT_DETAIL, BADANFIT_LIST, JS_SHELL, SITE_ABOUT, SITE_CONTACT, SITE_HOME, Base, bing_page, make_mission, osm_node


class TextNormTests(TestCase):
    def test_name_core_ignores_generic_first_word_and_spelling(self):
        self.assertEqual(textnorm.name_core("باشگاه ورزشی آرمان"), textnorm.name_core("آرمان"))
        self.assertEqual(textnorm.name_core("کافه نادري"), textnorm.name_core("کافه نادری"))  # Arabic ye
        self.assertEqual(textnorm.name_core("Blue Gym"), textnorm.name_core("blue  gym"))
        self.assertNotEqual(textnorm.name_core("باشگاه آرمان"), textnorm.name_core("باشگاه سپهر"))

    def test_similar_and_distance(self):
        self.assertEqual(textnorm.similar("arman", "arman"), 1.0)
        self.assertGreater(textnorm.similar("armangym", "arman"), 0.9)
        self.assertLess(textnorm.similar("arman", "sepehr"), 0.5)
        d = textnorm.haversine_m(35.7, 51.4, 35.7009, 51.4)
        self.assertTrue(90 < d < 110)
        self.assertFalse(textnorm.valid_geo(0, 0))
        self.assertTrue(textnorm.valid_geo(35.7, 51.4))


class HoursTests(TestCase):
    def test_osm_hours_in_persian(self):
        self.assertEqual(extras.osm_hours_fa("Mo-Su 10:00-24:00"), "هر روز ۱۰:۰۰ تا ۲۴:۰۰")
        self.assertIn("جمعه", extras.osm_hours_fa("Mo-Fr 08:00-17:00; Sa 09:00-13:00") + "جمعه")
        self.assertEqual(extras.osm_hours_fa("sunrise-sunset"), "sunrise-sunset")  # unknown grammar: kept as written

    def test_find_hours_in_page_text_and_jsonld(self):
        self.assertIn("شنبه", extras.find_hours(SITE_CONTACT))
        ld = '<script type="application/ld+json">{"@type":"Gym","openingHours":"Mo-Su 06:00-23:00"}</script>'
        self.assertEqual(extras.find_hours(f"<html>{ld}</html>"), "Mo-Su 06:00-23:00")
        self.assertEqual(extras.find_hours("<html><body>سلام</body></html>"), "")

    def test_contacts_in_bio(self):
        got = extras.contacts_in_text("باشگاه X | ☎ ۰۹۱۲۳۴۵۶۷۸۹ | info@x.ir | x.ir | wa.me/989121234567 | t.me/xgym")
        self.assertIn("09123456789", got["phones"])
        self.assertEqual(got["emails"], ["info@x.ir"])
        self.assertEqual(got["telegram"], ["xgym"])
        self.assertEqual(got["whatsapp"], ["989121234567"])


class PresetTests(TestCase):
    def test_every_type_has_valid_osm_tags_and_words(self):
        for t in presets.TYPES.values():
            t.osm_selectors  # raises on an unsafe tag
            self.assertTrue(t.terms_fa or t.osm, t.key)
            self.assertTrue(t.fa)
        self.assertGreaterEqual(len(presets.TYPES), 40)

    def test_chagher_and_a_second_preset_exist_and_validate(self):
        from ..services import missions

        for key in ("chagher_gyms_tehran", "cafes_isfahan"):
            m = missions.create_from_preset(key)
            self.assertEqual(m.preset_key, key)
            self.assertTrue(m.spec["business_types"])
        self.assertEqual(presets.PRESETS["chagher_gyms_tehran"].store_id, 34)
        self.assertEqual(presets.PRESETS["cafes_isfahan"].spec["cities"], ["اصفهان"])

    def test_type_for_osm_tags(self):
        self.assertEqual(presets.type_for_osm_tags({"leisure": "fitness_centre"}), ["gym"])
        self.assertEqual(presets.type_for_osm_tags({"amenity": "cafe"}, ["cafe"]), ["cafe"])
        self.assertEqual(presets.type_for_osm_tags({"amenity": "cafe"}, ["gym"]), [])


class CandidateMergeTests(Base, TestCase):
    def setUp(self):
        super().setUp()
        self.run = CrawlRun.objects.create(mission=make_mission(), spec={})

    def add(self, **kw):
        kw.setdefault("source", "osm")
        return candidates.add_found(self.run, candidates.Found(**kw))

    def test_same_phone_is_one_business(self):
        a, created = self.add(name="باشگاه آرمان", phones=["021 2222 3333"], city="تهران")
        b, created2 = self.add(name="Arman Fitness", phones=["+982122223333"], source="directory")
        self.assertTrue(created)
        self.assertFalse(created2)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual({s["source"] for s in CrawlCandidate.objects.get(pk=a.pk).sources}, {"osm", "directory"})

    def test_same_website_domain(self):
        a, _ = self.add(name="الف", website="https://www.arman-gym.ir/")
        b, created = self.add(name="ب", website="http://arman-gym.ir/contact", source="search")
        self.assertFalse(created)
        self.assertEqual(a.pk, b.pk)

    def test_same_name_close_by_merges_but_far_branch_does_not(self):
        a, _ = self.add(name="باشگاه آرمان", lat=35.7001, lon=51.4001, city="تهران")
        b, merged = self.add(name="آرمان", lat=35.7003, lon=51.4003, city="تهران")
        c, branch = self.add(name="باشگاه آرمان", lat=35.80, lon=51.50, city="تهران")
        self.assertFalse(merged)
        self.assertTrue(branch)
        self.assertEqual(a.pk, b.pk)
        self.assertNotEqual(a.pk, c.pk)

    def test_same_name_without_geo_needs_same_city(self):
        a, _ = self.add(name="سپهر", city="تهران")
        _, same_city = self.add(name="باشگاه سپهر", city="تهران")
        _, other_city = self.add(name="باشگاه سپهر", city="شیراز")
        self.assertFalse(same_city)
        self.assertTrue(other_city)

    def test_instagram_in_website_box_is_filed_as_instagram(self):
        c, _ = self.add(name="Irooni", website="https://instagram.com/irooni_cafe")
        self.assertEqual(c.website, "")
        self.assertIn("irooni_cafe", c.instagram)

    def test_merge_fills_but_never_loses(self):
        a, _ = self.add(name="سپهر", phones=["09121112222"], hours="هر روز ۱۰:۰۰ تا ۲۲:۰۰")
        self.add(name="سپهر", phones=["09121112222", "02133334444"], emails=["a@sepehr.ir"], source="website")
        a.refresh_from_db()
        self.assertEqual(sorted(a.phones), ["02133334444", "09121112222"])
        self.assertEqual(a.emails, ["a@sepehr.ir"])
        self.assertTrue(a.hours)

    def test_invalid_values_are_dropped_not_stored(self):
        c, _ = self.add(name="تست", phones=["123", "09121112222"], emails=["not-an-email", "user@example.com"], website="javascript:alert(1)")
        self.assertEqual(c.phones, ["09121112222"])
        self.assertEqual(c.emails, [])
        self.assertEqual(c.website, "")


class OsmParseTests(TestCase):
    def test_parse_elements_types_hours_contacts(self):
        els = [osm_node(1, "باشگاه آرمان", 35.7, 51.4, leisure="fitness_centre", phone="+98 21 2222 3333;09121112222", website="http://a.ir", opening_hours="Mo-Su 07:00-22:00",
                        **{"contact:instagram": "arman_gym"}), {"type": "node", "id": 9, "tags": {"leisure": "fitness_centre"}}]
        found = osm.parse_elements(els, city="تهران", allowed=["gym"])
        self.assertEqual(len(found), 1)  # the unnamed object is dropped
        f = found[0]
        self.assertEqual(f.types, ["gym"])
        self.assertEqual(f.ref, "osm:node/1")
        self.assertIn("09121112222", [p.replace(" ", "") for p in f.phones] + ["09121112222"])
        self.assertEqual(f.instagram, "arman_gym")

    def test_query_uses_only_validated_tags_and_area(self):
        sel = osm.selectors_for(["gym", "cafe"])
        self.assertIn(("leisure", "fitness_centre"), sel)
        q = osm.build_query(sel, {"osm_type": "relation", "osm_id": 5, "bbox": [1, 2, 3, 4]}, 500)
        self.assertIn("area(3600000005)", q)
        self.assertIn('nwr["amenity"="cafe"](area.a);', q)
        self.assertIn("out center tags 500;", q)
        self.assertTrue(osm.plan({"business_types": ["gym", "personal_trainer"], "cities": ["تهران", "کرج"]}))  # personal_trainer has no map tag: only gym counts
        self.assertEqual(len(osm.plan({"business_types": ["gym"], "cities": ["تهران", "کرج"]})), 2)
        self.assertEqual(osm.plan({"business_types": ["personal_trainer"], "cities": ["تهران"]}), [])


class SearchParseTests(TestCase):
    def test_bing_unwrap_and_parse(self):
        html = bing_page([("https://badanfit.ir/gym-hub.php?city=tehran", "باشگاه بدنسازی تهران | بدن فیت", "آدرس و تلفن باشگاه‌های تهران"),
                          ("https://www.instagram.com/arman.gym/", "Arman Gym (@arman.gym) • Instagram photos", "")])
        hits = search.parse_bing(html)
        self.assertEqual(hits[0].url, "https://badanfit.ir/gym-hub.php?city=tehran")
        self.assertEqual(search.instagram_handle(hits[1].url), "arman.gym")
        self.assertEqual(search.instagram_handle("https://www.instagram.com/p/ABC/"), "")

    def test_relevance_drops_garbage_and_keeps_the_right_kind(self):
        words = ["باشگاه", "بدنسازی"]
        good = search.Hit("https://sepehr-gym.ir/", "باشگاه بدنسازی سپهر تهران", "", "bing")
        bad = search.Hit("https://genius.com/x", "Amin Tijay – Bia Bebin Lyrics", "متن آهنگ", "bing")
        self.assertTrue(search.relevant(good, words=words, city="تهران"))
        english = search.Hit("https://gymcenter.ir/", "Gym Center | Tehran gyms", "", "bing")
        self.assertTrue(search.relevant(english, words=["gym"], city="تهران", city_en="tehran"))
        self.assertFalse(search.relevant(bad, words=words, city="تهران"))
        self.assertTrue(search.blocked_host("genius.com"))
        self.assertIsNone(search.hit_to_found(bad, types=["gym"], city="تهران", query="q"))
        f = search.hit_to_found(good, types=["gym"], city="تهران", query="q")
        self.assertEqual(f.website, "https://sepehr-gym.ir")
        self.assertEqual(f.name, "باشگاه بدنسازی سپهر تهران")
        self.assertEqual(search.name_from_title("باشگاه آرمان | تهران - بدنسازی", "x.ir"), "باشگاه آرمان")

    def test_block_detection(self):
        self.assertEqual(search.looks_blocked(202, "<html>anomaly</html>"), "HTTP 202")
        self.assertIn("captcha", search.looks_blocked(200, "<html>Please solve the CAPTCHA</html>"))
        self.assertEqual(search.looks_blocked(200, "<html><li class='b_algo'></li></html>"), "")

    def test_queries_are_capped_and_distinct(self):
        qs = search.build_queries({"business_types": ["gym", "cafe"], "cities": ["تهران"], "keywords": ["مربی"]}, 4)
        self.assertEqual(len(qs), 4)
        self.assertEqual(len({q["query"] for q in qs}), 4)
        every = [q["query"] for q in search.build_queries({"business_types": ["gym"], "cities": ["تهران", "ناکجاآباد"], "keywords": []}, 20)]
        self.assertIn("gym tehran", every)  # an English query too: it is the one that works from this server
        self.assertTrue(any("ناکجاآباد" in q for q in every))
        self.assertNotIn("gym ناکجاآباد", every)  # an unknown city has no English spelling: no made-up query


class DirectoryParseTests(TestCase):
    def test_badanfit_cards(self):
        cards = directory.parse_badanfit_cards(BADANFIT_LIST, "https://badanfit.ir")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["phone"], "021 2200 0001")
        self.assertEqual(cards[0]["rating"], 4.5)
        self.assertEqual(cards[0]["url"], "https://badanfit.ir/gym-detail.php?id=11")

    def test_detail_jsonld_geo_hours(self):
        f = directory.parse_detail(BADANFIT_DETAIL, "https://badanfit.ir/gym-detail.php?id=11", directory="badanfit", types=["gym"], city="تهران")
        self.assertEqual(f.name, "باشگاه ورزشی نمونه یک")
        self.assertEqual((f.lat, f.lon), (35.7, 51.4))
        self.assertIn("021 2200 0001", f.phones)
        self.assertIn("شنبه", f.hours)
        self.assertEqual(f.ref, "directory:badanfit:11")

    def test_generic_detail_links_by_repeated_shape(self):
        links = "".join(f'<a href="/gym/{i}">باشگاه شماره {i}</a>' for i in range(1, 8)) + '<a href="/about">درباره</a><a href="/contact">تماس با ما</a>'
        found = directory.detail_links(f"<html><body>{links}</body></html>", "https://dir.example.ir/list")
        self.assertEqual(len(found), 7)
        self.assertTrue(all("/gym/" in u for u in found))

    def test_plan_has_badanfit_pages_for_supported_city_only(self):
        spec = {"business_types": ["gym"], "cities": ["تهران", "کویر"], "sources": {"directory": True}, "budget": {"max_directory_pages": 20}}
        tasks = directory.plan(spec)
        self.assertTrue(any("city=tehran" in t.params["url"] for t in tasks))
        self.assertFalse(any("کویر" in t.label for t in tasks))
        custom = directory.plan({**spec, "directory_urls": ["https://dir.example.ir/list"]})
        self.assertTrue(any(t.params["directory"] == "generic" for t in custom))


class WebsiteAnalysisTests(TestCase):
    def pages(self, **over):
        from ..engine.sources.website import PageData

        base = [PageData("https://arman-gym.ir/", "home", SITE_HOME, 200), PageData("https://arman-gym.ir/contact", "contact", SITE_CONTACT, 200),
                PageData("https://arman-gym.ir/about", "about", SITE_ABOUT, 200)]
        return over.get("pages", base)

    def test_reads_phone_email_instagram_hours_and_words(self):
        from ..engine.sources import website

        words, fit = website.words_for(["gym"], {"keywords": []})
        info = website.analyze_site(self.pages(), home_url="https://arman-gym.ir", type_words=words, fit_words=fit)
        self.assertTrue(info.ok)
        self.assertIn("09121234567", info.fields["phones"])
        self.assertEqual(info.fields["emails"], ["info@arman-gym.ir"])
        self.assertIn("arman.gym", info.fields["instagram"])
        self.assertIn("شنبه", info.hours)
        self.assertIn("باشگاه", info.words)
        self.assertIn("مربی", info.fit_words)

    def test_js_shell_is_reported_not_guessed(self):
        from ..engine.sources import website
        from ..engine.sources.website import PageData

        info = website.analyze_site([PageData("https://x.ir/", "home", JS_SHELL, 200)], home_url="https://x.ir", type_words=[], fit_words=[])
        self.assertFalse(info.ok)
        self.assertTrue(info.js_shell)
        self.assertEqual(info.reason, "js_shell")
        rendered = website.analyze_site([PageData("https://x.ir/", "home", JS_SHELL.replace('<div id="root"></div>', "<h1>سلام</h1><p>تلفن: 09121234567</p>"), 200, rendered=True)], home_url="https://x.ir", type_words=[], fit_words=[])
        self.assertTrue(rendered.ok)

    def test_failed_home_gives_a_reason(self):
        from ..engine.sources import website
        from ..engine.sources.website import PageData

        info = website.analyze_site([PageData("https://x.ir/", "home", "", 0, outcome="robots_blocked")], home_url="https://x.ir", type_words=[], fit_words=[])
        self.assertEqual(info.reason, "robots_blocked")


class ScoringTests(TestCase):
    def cand(self, **kw):
        base = dict(name="باشگاه آرمان", types=["gym"], city="تهران", phones=["09121112222"], emails=[], website="", instagram="", telegram="", whatsapp=[], contact_form="", address="",
                    hours="", rating=None, lat=35.7, lon=51.4, sources=[{"source": "osm"}], signals={})
        base.update(kw)
        return type("C", (), base)()

    def test_points_are_explained_and_bounded(self):
        spec = {"business_types": ["gym"], "cities": ["تهران"], "keywords": []}
        r = scoring.score(self.cand(website="https://a.ir", emails=["a@a.ir"], instagram="x", sources=[{"source": "osm"}, {"source": "website"}],
                                    signals={"site": {"words": ["باشگاه"], "fit_words": ["مربی", "برنامه تمرینی"]}}), spec)
        self.assertGreaterEqual(r["value"], 70)
        self.assertEqual(r["level"], "high")
        self.assertTrue(all(x["text"] for x in r["reasons"]))
        self.assertEqual(r["value"], min(100, sum(x["points"] for x in r["reasons"])))

    def test_unreachable_business_scores_low_with_a_reason(self):
        r = scoring.score(self.cand(phones=[], lat=None, lon=None), {"business_types": ["gym"], "cities": ["تهران"], "keywords": []})
        self.assertLess(r["value"], 45)
        self.assertTrue(any("هیچ راهِ تماسی" in x["text"] for x in r["reasons"]))

    def test_landline_scores_below_mobile(self):
        spec = {"business_types": ["gym"], "cities": ["تهران"], "keywords": []}
        self.assertGreater(scoring.score(self.cand(phones=["09121112222"]), spec)["value"], scoring.score(self.cand(phones=["02122223333"]), spec)["value"])
