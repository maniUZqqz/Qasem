"""The second fix round after the live review (2026-11-17, site v3.44): the SMS drafts, Instagram discovery by hashtag and location, the repair of old
rows, one result per business, the empty-city report, the web-search engines (Brave, cooldown, API key), whole-word exclusion, the personal-data handling
of independent coaches, the tag filter and the pipeline phone.

Everything runs against canned pages (``FakeWeb``); nothing real is contacted and nothing is sent.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import httpx
from django.test import TestCase

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.core.testing import client_for, make_staff
from apps.growth_engine.discovery.models import ProviderConfig
from apps.growth_engine.leads.models import ContactPoint, Lead, LeadTag
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.leads.services.intake import SourceInfo, create_from_draft
from apps.growth_engine.outreach.channels import sms as sms_channel
from apps.growth_engine.outreach.models import Channel
from apps.growth_engine.outreach.services import rendering

from .. import presets
from ..engine import candidates, fetch, finalize, place, runner, textnorm
from ..engine.candidates import Found
from ..engine.sources import instagram, search
from ..models import CrawlCandidate, CrawlFinding, CrawlLog, CrawlRun, CrawlTask, LeadInsight, OutreachDraft
from ..services import drafts as draft_service
from ..services import missions, pipeline, repair, results
from .helpers import Base, FakeWeb, bing_page, brave_page, make_mission, osm_node, overpass_json, NOMINATIM_TEHRAN

SEARCH_ONLY = {"osm": False, "search": True, "directory": False, "website": False, "instagram": False, "neshan": False}
IG_ONLY = {"osm": False, "search": False, "directory": False, "website": False, "instagram": True, "neshan": False}


def run_it(web: FakeWeb, mission=None, **spec) -> CrawlRun:
    mission = mission or make_mission(**spec)
    run = missions.start_run(mission, None, dispatch=False)
    runner.run_crawl(run.pk, web_factory=web.factory)
    run.refresh_from_db()
    return run


def search_mission(**spec):
    budget = {"max_requests": 200, "max_sites": 10, "max_pages_per_site": 4, "max_seconds": 300, "domain_delay": 1.0, "max_search_queries": 2}
    budget.update(spec.pop("budget", {}))
    return make_mission(sources=SEARCH_ONLY, budget=budget, keywords=[], **spec)


# --------------------------------------------------------------------------- names, hosts and titles


class WholeWordTests(TestCase):
    def test_exclusion_words_are_whole_words_not_letters_inside_another_word(self):
        gym = presets.get_type("gym")
        for name in ("باشگاه بدنسازی اسپارتا", "باشگاه اسپارتان", "باشگاه بدنسازی کلینیکال", "باشگاه بدنسازی اسپاد فیت", "باشگاه بدنسازی اسپاتنا", "Sparta Gym"):
            self.assertEqual(textnorm.exclude_hits(name, gym.exclude), [], name)
        self.assertEqual(textnorm.exclude_hits("اسپا حس خوب زندگی", gym.exclude), ["اسپا"])
        self.assertEqual(textnorm.exclude_hits("مرکز یوگا و ماساژ مروارید آبی", gym.exclude), ["ماساژ"])
        self.assertEqual(textnorm.exclude_hits("کلینیک‌های ورزشی ایران", gym.exclude), ["کلینیک"])  # a ZWNJ and a plural do not hide the word
        self.assertEqual(textnorm.exclude_hits("مهد کودک آفتاب", gym.exclude), ["مهد کودک"])  # two words: both must stand together
        self.assertEqual(textnorm.exclude_hits("Royal Spa Club", gym.exclude), ["spa"])
        self.assertEqual(textnorm.exclude_hits("تجهیزات بدنسازی ویرا بازرگانی وزنه", gym.exclude), ["تجهیزات", "بازرگانی"])

    def test_a_gym_called_sparta_is_not_thrown_out_but_a_spa_is(self):
        spec = {"business_types": ["gym"]}
        self.assertEqual(finalize.type_mismatch(SimpleNamespace(name="باشگاه بدنسازی اسپارتا", types=["gym"]), spec), "")
        self.assertEqual(finalize.type_mismatch(SimpleNamespace(name="اسپا حس خوب زندگی", types=["gym"]), spec), "اسپا")


class DirectoryHostTests(TestCase):
    def test_directories_and_media_are_not_a_businesss_own_site(self):
        for host in ("cybo.com", "www.cybo.com", "cylex.ir", "www.yellowpages.com", "balad.ir", "badanfit.ir", "gymcenter.ir", "morabiyab.com"):
            self.assertTrue(textnorm.is_directory_host(host), host)
        for host in ("faslesafar.com", "arman-gym.ir", "myspa.ir", "x"):
            self.assertFalse(textnorm.is_directory_host(host), host)
        for host in ("aparatsport.ir", "telewebion.ir", "cybo.com"):
            self.assertTrue(textnorm.is_foreign_site(host), host)

    def test_a_directory_address_is_not_filed_as_the_businesss_website(self):
        f = candidates.clean_found(Found(name="Fiitac fitness Gym", source="search", website="https://www.cybo.com/IR-biz/fiitac-fitness-gym"))
        self.assertEqual(f.website, "")

    def test_article_and_list_pages_are_not_businesses(self):
        self.assertTrue(textnorm.looks_like_listing_page("بهترین باشگاه‌های بدنسازی تهران", "https://shahrzi.com/best-gym/"))
        self.assertTrue(textnorm.looks_like_listing_page("معرفی باشگاه آرمان", "https://x.ir/blog/arman"))
        self.assertTrue(textnorm.looks_like_listing_page("لیست کافه‌های اصفهان + آدرس", "https://x.ir/cafes/isfahan"))
        self.assertFalse(textnorm.looks_like_listing_page("باشگاه بدنسازی آرمان | تهران", "https://arman-gym.ir/"))
        self.assertFalse(textnorm.looks_like_listing_page("بهترین باشگاهِ منطقه | آرمان", "https://arman-gym.ir/"))  # a home page with a marketing title


class PlaceFallbackTests(TestCase):
    def test_a_position_in_another_city_names_that_city(self):
        v = place.verdict(["تهران"], address="ایران، خیابان امام رضا", lat=32.7015, lon=51.6089)
        self.assertEqual((v.state, v.city), ("out", "اصفهان"))


# --------------------------------------------------------------------------- web search


class BraveParserTests(TestCase):
    def test_brave_page_is_parsed(self):
        html = brave_page([("https://sepehr-gym.ir/", "باشگاه بدنسازی سپهر | تهران", "باشگاه بدنسازی با مربی در تهران"),
                           ("https://www.instagram.com/arman.gym/", "آرمان (@arman.gym) • Instagram photos and videos", "1,234 Followers, 56 Following, 78 Posts")])
        hits = search.parse_brave(html)
        self.assertEqual([h.url for h in hits], ["https://sepehr-gym.ir/", "https://www.instagram.com/arman.gym/"])
        self.assertEqual(hits[0].title, "باشگاه بدنسازی سپهر | تهران")
        self.assertIn("مربی", hits[0].snippet)
        self.assertEqual(hits[1].engine, "brave")
        self.assertEqual(search.instagram_numbers(hits[1]), {"followers": 1234, "posts": 78})

    def test_counters_of_a_profile(self):
        self.assertEqual(search.count_of("1,234"), 1234)
        self.assertEqual(search.count_of("12.5K"), 12500)
        self.assertEqual(search.count_of("1.2M"), 1_200_000)
        self.assertEqual(search.count_of("۲٬۳۴۵".replace("٬", ",")), 2345)
        self.assertIsNone(search.count_of("abc"))

    def test_only_a_page_that_calls_itself_a_coach_is_an_independent_person(self):
        self.assertTrue(search.is_individual_page("مربی خصوصی بانوان/مربی آنلاین", "fitness_marzi"))
        self.assertTrue(search.is_individual_page("مربی رسمی پرورش اندام و بدنسازی", "ava.gym_"))  # a handle says little
        self.assertTrue(search.is_individual_page("پویا | مربی بدنسازی و تغذیه ورزشی", "pouya.fit"))
        self.assertTrue(search.is_individual_page("Nazanin Trainer", "nazanin_trainer"))
        self.assertFalse(search.is_individual_page("تکنیک برتر / بدنسازی / ورزش گروهی", "tbgym"))
        self.assertFalse(search.is_individual_page("باشگاه مربیان تهران", "x"))

    def test_a_city_named_in_the_title_is_evidence_and_another_city_is_out(self):
        hit = search.Hit("https://www.instagram.com/x/", "مربی بدنسازی/شیراز📍 (@x) • Instagram", "", "brave")
        self.assertEqual(search.evidence_city(hit, "تهران"), ("شیراز", "evidence"))
        self.assertEqual(search.evidence_city(search.Hit("https://www.instagram.com/y/", "مربی بدنسازی (@y)", "", "brave"), "تهران"), ("", ""))  # no city named: no city claimed
        self.assertFalse(search.relevant_instagram(hit, words=["مربی"], cities=["تهران"]))
        self.assertTrue(search.relevant_instagram(hit, words=["مربی"], cities=["تهران", "شیراز"]))


class SearchEngineTests(Base, TestCase):
    def test_brave_results_become_candidates_and_articles_and_directories_do_not(self):
        web = FakeWeb()
        web.add("search.brave.com", "/search", brave_page([
            ("https://sepehr-gym.ir/", "باشگاه بدنسازی سپهر | تهران", "باشگاه بدنسازی با مربی در تهران"),
            ("https://shahrzi.com/best-gyms-in-tehran/", "بهترین باشگاه‌های بدنسازی تهران", "لیست باشگاه‌های بدنسازی تهران"),
            ("https://www.cybo.com/IR-biz/fiitac", "Fiitac gym Tehran", "gym in Tehran"),
            ("https://www.instagram.com/arman.gym/", "باشگاه بدنسازی آرمان (@arman.gym) • Instagram photos and videos", "1,234 Followers, 56 Following, 78 Posts - باشگاه بدنسازی آرمان تهران"),
        ]))
        run = run_it(web, search_mission(business_types=["gym"], cities=["تهران"]))
        self.assertEqual(run.status, "completed", run.error)
        names = list(CrawlCandidate.objects.filter(run=run).values_list("name", flat=True))
        self.assertIn("باشگاه بدنسازی سپهر", names)
        self.assertFalse([n for n in names if "بهترین" in n], names)
        self.assertFalse(CrawlCandidate.objects.filter(run=run, website__contains="cybo").exists())
        ig = CrawlCandidate.objects.get(run=run, instagram__icontains="arman.gym")
        self.assertEqual(ig.signals["ig"]["followers"], 1234)
        self.assertEqual(ig.city, "تهران")

    def test_a_blocked_answer_rests_the_engine_for_every_later_query(self):
        web = FakeWeb()
        web.add("search.brave.com", "/search", "<html>blocked</html>", status=403)
        web.add("www.bing.com", "/search", bing_page([("https://sepehr-gym.ir/", "باشگاه بدنسازی سپهر | تهران", "باشگاه بدنسازی در تهران")]))
        run = run_it(web, search_mission(business_types=["gym"], cities=["تهران"], budget={"max_search_queries": 3}))
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(web.hits("search.brave.com"), 1)  # asked once; the 403 put it to rest, the other queries did not touch it
        rest = search.cooldowns()
        self.assertIn("brave", rest)
        self.assertIn("403", rest["brave"]["reason"])
        self.assertTrue(CrawlCandidate.objects.filter(run=run, name="باشگاه بدنسازی سپهر").exists())  # the English query went to Bing
        logs = " ".join(CrawlLog.objects.filter(run=run).values_list("message", flat=True))
        self.assertIn("Brave", logs)
        self.assertNotIn("directory", logs)  # the diary is Persian: no «directory, osm, search»

    def test_persian_queries_do_not_go_to_bing_but_english_ones_do(self):
        order, why = search.usable_engines({}, persian=True, site_op=False)
        self.assertNotIn("bing", order)
        self.assertIn("bing", why)
        order, _ = search.usable_engines({}, persian=False, site_op=False)
        self.assertEqual(order[0], "brave")
        self.assertIn("bing", order)
        order, why = search.usable_engines({}, persian=False, site_op=True)
        self.assertNotIn("bing", order)

    def test_the_owners_brave_api_key_is_used_first_and_the_page_is_not_scraped(self):
        ProviderConfig.objects.create(provider="brave", enabled=True, secrets={"api_key": "k" * 24})
        seen: dict = {}

        def brave_api(req: httpx.Request):
            seen["token"] = req.headers.get("x-subscription-token")
            return httpx.Response(200, json={"web": {"results": [{"url": "https://sepehr-gym.ir/", "title": "باشگاه بدنسازی سپهر | تهران", "description": "باشگاه بدنسازی در تهران"}]}})

        web = FakeWeb()
        web.add_fn("api.search.brave.com", "/res/v1/web/search", brave_api)
        run = run_it(web, search_mission(business_types=["gym"], cities=["تهران"]))
        self.assertEqual(seen["token"], "k" * 24)
        self.assertEqual(web.hits("search.brave.com"), 0)
        self.assertTrue(CrawlCandidate.objects.filter(run=run, name="باشگاه بدنسازی سپهر").exists())
        self.assertTrue(search.brave_api_key())

    def test_the_probe_does_not_ask_an_engine_that_is_resting(self):
        search.start_cooldown("brave", "HTTP 403")
        web = FakeWeb()
        web.add("www.bing.com", "/search", bing_page([("https://sepehr-gym.ir/", "باشگاه بدنسازی سپهر", "gym")]))
        client = fetch.WebClient(web.fetcher(), fetch.Budget(max_requests=20, max_seconds=60), use_cache=False)
        out = search.probe(client)
        self.assertTrue(out["brave"]["resting"])
        self.assertEqual(web.hits("search.brave.com"), 0)
        self.assertTrue(out["bing"]["ok"])
        self.assertEqual(search.save_probe(out)["engines"]["bing"]["results"], 1)
        self.assertIn("brave", search.cooldowns())  # saving the probe keeps the rest

    def test_the_plan_log_names_the_sources_in_persian(self):
        web = FakeWeb()
        run = run_it(web, search_mission(business_types=["gym"], cities=["تهران"]))
        logs = list(CrawlLog.objects.filter(run=run).order_by("id").values_list("message", flat=True))
        plan_line = next(m for m in logs if m.startswith("برنامه ساخته شد"))
        self.assertIn("جست‌وجوی وب", plan_line)
        self.assertNotIn("search", plan_line)


# --------------------------------------------------------------------------- Instagram: hashtags and locations


class InstagramDiscoveryTests(Base, TestCase):
    def web_with_profiles(self) -> FakeWeb:
        web = FakeWeb()
        web.add("search.brave.com", "/search", brave_page([
            ("https://www.instagram.com/pouya.fit/", "پویا | مربی بدنسازی و تغذیه ورزشی تهران (@pouya.fit) • Instagram photos and videos", "2,345 Followers, 100 Following, 90 Posts - مربی بدنسازی تهران"),
            ("https://www.instagram.com/shiraz.coach/", "مربی بدنسازی شیراز (@shiraz.coach) • Instagram photos and videos", "500 Followers - مربی بدنسازی در شیراز"),
            ("https://www.instagram.com/music.band/", "گروه موسیقی (@music.band) • Instagram photos and videos", "آهنگ‌های ما"),
            ("https://www.instagram.com/p/ABC123/", "Post", "x"),
        ]))
        return web

    def mission(self, **spec):
        return make_mission(business_types=["personal_trainer"], keywords=[], cities=["تهران"], sources=IG_ONLY, ig_hashtags=["#مربی_بدنسازی"], ig_locations=["پونک"], **spec)

    def test_the_plan_shares_the_budget_between_cities_and_falls_back_to_the_types(self):
        spec = {"sources": {"instagram": True}, "business_types": ["gym"], "cities": ["تهران", "اصفهان", "مشهد", "شیراز"], "ig_hashtags": ["#a_b", "#c"], "budget": {"max_ig_queries": 5}}
        tasks = instagram.plan(spec)
        self.assertEqual(len(tasks), 5)
        self.assertEqual([t.params["city"] for t in tasks[:4]], ["تهران", "اصفهان", "مشهد", "شیراز"])  # the first hashtag in every city before the second hashtag
        self.assertEqual(tasks[0].params["query"], 'site:instagram.com "a b" تهران')
        self.assertTrue(all(t.stage == "discover" and t.source == "instagram" for t in tasks))
        self.assertEqual(instagram.plan({**spec, "sources": {"instagram": False}}), [])
        self.assertEqual(instagram.plan({**spec, "budget": {"max_ig_queries": 0}}), [])
        default = instagram.plan({"sources": {"instagram": True}, "business_types": ["gym"], "cities": ["تهران"]})
        self.assertTrue(default and "باشگاه بدنسازی" in default[0].params["query"])
        located = instagram.plan({"sources": {"instagram": True}, "business_types": ["gym"], "cities": ["تهران"], "ig_locations": ["پونک", "اصفهان"]})
        self.assertIn('site:instagram.com "باشگاه بدنسازی" "پونک"', [t.params["query"] for t in located])
        self.assertEqual([t.params["city"] for t in located], ["تهران", "اصفهان"])  # a city used as a location is that city

    def test_profiles_of_a_hashtag_and_a_location_are_found_and_the_node_is_asked_to_read_them(self):
        run = run_it(self.web_with_profiles(), self.mission())
        self.assertEqual(run.status, "completed", run.error)
        discover = CrawlTask.objects.filter(run=run, source="instagram", kind="discover")
        self.assertEqual(discover.count(), 2)  # one hashtag + one location
        cands = CrawlCandidate.objects.filter(run=run)
        self.assertEqual(cands.count(), 1)  # the Shiraz coach, the band and the post are not taken
        c = cands.get()
        self.assertIn("pouya.fit", c.instagram)
        self.assertEqual(c.signals["ig"]["followers"], 2345)  # the public counter shown with the search result
        self.assertTrue(c.signals["individual"])
        lead = Lead.objects.get(crawl_findings__mission=run.mission)
        self.assertIn(finalize.INDIVIDUAL_TAG, [t.name for t in lead.tags.all()])
        self.assertEqual(lead.category, finalize.INDIVIDUAL_CATEGORY)
        self.assertEqual(CrawlTask.objects.filter(run=run, kind="ig_profile", status="waiting_node").count(), 1)  # waits for Abagram on the node, nothing is lost
        self.assertEqual(run.tasks_waiting, 1)

    def test_an_independent_person_is_never_named_in_the_diary_or_the_task_list(self):
        run = run_it(self.web_with_profiles(), self.mission())
        text = " ".join([*CrawlLog.objects.filter(run=run).values_list("message", flat=True), run.message,
                         *CrawlTask.objects.filter(run=run).values_list("label", flat=True)])
        self.assertNotIn("پویا", text)
        self.assertNotIn("pouya.fit", text.replace("@", ""))
        self.assertEqual(finalize.log_name(CrawlCandidate.objects.get(run=run)), finalize.INDIVIDUAL_CATEGORY)

    def test_the_nodes_reading_of_a_page_replaces_the_counters_the_search_showed(self):
        run = run_it(self.web_with_profiles(), self.mission())
        c = CrawlCandidate.objects.get(run=run)
        self.assertEqual(c.signals["ig"]["from"], "search")
        instagram.apply_account(c, {"username": "pouya.fit", "followers": 2400, "biography": "مربی بدنسازی | 09121112233", "is_business": True})
        c.refresh_from_db()
        self.assertEqual(c.signals["ig"]["followers"], 2400)
        self.assertEqual(c.signals["ig"]["from"], "node")
        self.assertTrue(c.signals["ig"]["is_business"])
        self.assertIn("09121112233", c.phones)

    def test_independent_people_can_be_switched_off_for_a_mission(self):
        run = run_it(self.web_with_profiles(), self.mission(include_individuals=False))
        self.assertEqual(CrawlCandidate.objects.filter(run=run).count(), 0)
        self.assertEqual(Lead.objects.filter(crawl_findings__mission=run.mission).count(), 0)

    def test_the_coach_directory_is_planned_only_when_independent_people_are_wanted(self):
        from ..engine.sources import coaches

        spec = {"business_types": ["personal_trainer"], "cities": ["تهران"], "sources": {"directory": True}}
        self.assertTrue(coaches.plan(spec))
        self.assertEqual(coaches.plan({**spec, "include_individuals": False}), [])
        run_card = {"id": "77", "name": "علی رضایی", "url": "https://morabiyab.com/coach/77/", "specialties": "بدنسازی", "province": "تهران", "city": "تهران", "mode": "in_person"}
        found = coaches.parse_profile("<html><body><h1>علی رضایی</h1></body></html>", run_card["url"], run_card)
        self.assertTrue(found.signals["individual"])


# --------------------------------------------------------------------------- what every city gave


class CityReportTests(Base, TestCase):
    def test_a_city_that_gave_nothing_is_said_so(self):
        web = self.web_with_gyms()

        def nominatim(req: httpx.Request):
            return httpx.Response(200, json=[]) if "%D8%B4%DB%8C%D8%B1%D8%A7%D8%B2" in str(req.url) else None  # Shiraz: the geocoder knows nothing

        web.add_fn("nominatim.openstreetmap.org", "/search", nominatim)
        run = run_it(web, cities=["تهران", "شیراز"])
        self.assertEqual(run.status, "completed", run.error)
        report = run.usage["city_report"]
        self.assertEqual(report["empty"], ["شیراز"])
        self.assertGreaterEqual(report["cities"]["تهران"]["leads"], 1)
        self.assertEqual(report["cities"]["شیراز"]["leads"], 0)
        self.assertIn("نقشه", report["notes"]["شیراز"])
        self.assertIn("شیراز", run.message)
        self.assertTrue(CrawlLog.objects.filter(run=run, level="warn", message__contains="برای «شیراز» هیچ لیدی ساخته نشد").exists())
        staff = make_staff()
        data = client_for(staff).get(f"/api/v1/growth/finder/runs/{run.pk}/").json()
        self.assertEqual(data["city_report"]["empty"], ["شیراز"])

    def test_a_city_the_directory_has_no_page_for_is_named_in_the_plan_log(self):
        web = self.web_with_gyms()
        run = run_it(web, cities=["تهران", "شیراز"], sources={"osm": True, "search": False, "directory": True, "website": False, "instagram": False, "neshan": False})
        self.assertTrue(CrawlLog.objects.filter(run=run, message__contains="فهرستِ بدن‌فیت برای شیراز صفحه‌ای ندارد").exists())
        self.assertFalse(CrawlTask.objects.filter(run=run, source="directory", params__city="شیراز").exists())

    def test_a_run_where_every_city_gave_leads_reports_none_empty(self):
        run = run_it(self.web_with_gyms())
        self.assertEqual(run.usage["city_report"]["empty"], [])
        self.assertEqual(run.message, "تمام شد")


# --------------------------------------------------------------------------- SMS drafts


class SmsDraftTests(Base, TestCase):
    OLD_LONG = "دستیارِ هوش مصنوعیِ مربی‌ها برای پیش‌نویسِ برنامهٔ ورزشی و غذایی؛ شروع رایگان."

    def lead(self, phone="09121112222", name="باشگاه آرمان"):
        draft, _ = build_draft({"business_name": name, "phone": phone, "city": "تهران"}, source_ref="manual")
        return create_from_draft(draft, SourceInfo(provider="manual"))

    def final(self, body: str) -> str:
        return body

    def assert_good_sms(self, d: OutreachDraft):
        self.assertNotIn("…", d.body)
        self.assertLessEqual(sms_channel.segments(d.body)["parts"], 2, d.body)
        self.assertFalse([w for w in d.warnings if "بخش" in w], d.warnings)

    def test_a_mission_from_a_preset_uses_the_presets_sms_line(self):
        mission = missions.create_from_preset("chagher_gyms_tehran")
        mission.spec = {**mission.spec, "pitch": {}}  # what the panel's form saved for a preset mission
        mission.save()
        pitch = draft_service.pitch_of(mission)
        self.assertEqual(pitch["sms"], presets.PRESETS["chagher_gyms_tehran"].pitch.sms)
        lead = self.lead()
        out = draft_service.generate(mission, [lead.pk], ["sms"])
        self.assertEqual(out["created"], 1)
        d = lead.crawl_drafts.get(channel="sms")
        self.assert_good_sms(d)
        self.assertIn("چغر", d.body)
        self.assertIn(pitch["sms"], d.body)  # the whole line, not a cut piece of the long description

    def test_every_preset_writes_a_whole_sms_that_fits_two_parts(self):
        n = 0
        for company in ("", "شرکت نمونهٔ ایکس‌ایگرگ"):
            s = GrowthSettings.load()
            s.sender_company = company
            s.save()
            for key in presets.PRESETS:
                n += 1
                mission = missions.create_from_preset(key)
                mission.spec = {**mission.spec, "pitch": {}}
                mission.save()
                lead = self.lead(phone=f"0912{2000000 + n}")
                draft_service.generate(mission, [lead.pk], ["sms"])
                d = lead.crawl_drafts.get(channel="sms", mission=mission)
                self.assertNotIn("…", d.body, (key, d.body))
                self.assertLessEqual(sms_channel.segments(d.body)["parts"], 2, (key, company, d.body))
                self.assertIn(draft_service.pitch_of(mission)["brand"], d.body)

    def test_a_long_sms_line_of_the_mission_gives_way_to_the_presets_short_one(self):
        mission = missions.create_from_preset("chagher_gyms_tehran")
        mission.spec = {**mission.spec, "pitch": {**mission.spec["pitch"], "sms": self.OLD_LONG}}  # an older preset's 80 characters
        mission.save()
        lead = self.lead()
        draft_service.generate(mission, [lead.pk], ["sms"])
        d = lead.crawl_drafts.get(channel="sms")
        self.assert_good_sms(d)
        self.assertIn(presets.PRESETS["chagher_gyms_tehran"].pitch.sms, d.body)
        self.assertNotIn("پیش‌نویسِ برنامهٔ", d.body)

    def test_a_custom_mission_uses_a_whole_clause_of_its_description_never_a_cut(self):
        mission = make_mission(pitch={"brand": "چغر", "what": "چغر دستیارِ هوش مصنوعیِ مربی‌هاست: برنامهٔ ورزشی و غذاییِ هر ورزشکار را در کمتر از یک دقیقه پیش‌نویس می‌کند.",
                                      "benefit": "برای مربی‌ها.", "cta": "پاسخ بدهید."})
        lead = self.lead()
        draft_service.generate(mission, [lead.pk], ["sms"])
        d = lead.crawl_drafts.get(channel="sms")
        self.assert_good_sms(d)
        self.assertIn("چغر دستیارِ هوش مصنوعیِ مربی‌هاست", d.body)
        self.assertNotIn("پیش‌نویس می‌کند", d.body)  # the second half did not fit and is simply not there

    def test_when_nothing_fits_the_text_is_whole_and_flagged_not_cut(self):
        long = "این یک جملهٔ بسیار بلند است که دربارهٔ محصول چیزهای زیادی می‌گوید و هیچ بخشِ کوتاهی ندارد و باید از هر طرف از حدِ دو بخشِ پیامک بگذرد و باز هم ادامه دارد"
        mission = make_mission(pitch={"brand": "چغر", "what": long, "cta": "پاسخ بدهید."})
        lead = self.lead()
        draft_service.generate(mission, [lead.pk], ["sms"])
        d = lead.crawl_drafts.get(channel="sms")
        self.assertNotIn("…", d.body)
        self.assertIn(long, d.body)
        self.assertTrue([w for w in d.warnings if "بخش" in w], d.warnings)  # the owner is told to shorten it

    def test_fit_sms_picks_the_first_whole_line_that_fits(self):
        out = draft_service.fit_sms("چغر", ["الف " * 60, "دستیارِ مربی‌ها"], 60)
        self.assertIn("دستیارِ مربی‌ها", out)
        self.assertNotIn("…", out)
        self.assertEqual(draft_service.fit_sms("چغر", "دستیارِ مربی‌ها", 80), "سلام، از تیمِ «چغر». دستیارِ مربی‌ها")
        self.assertEqual(draft_service.fit_sms("چغر", "چغر دستیارِ مربی‌هاست", 80), "سلام، چغر دستیارِ مربی‌هاست")  # the brand is not said twice

    def test_the_opt_out_sentence_is_still_added(self):
        mission = missions.create_from_preset("chagher_gyms_tehran")
        lead = self.lead(phone="09121119999")
        draft_service.generate(mission, [lead.pk], ["sms"])
        d = lead.crawl_drafts.get(channel="sms")
        self.assertIn(GrowthSettings.load().opt_out_line.strip(), d.body)
        self.assertIsNotNone(rendering)


class OneMessagePerBusinessTests(Base, TestCase):
    def setUp(self):
        super().setUp()
        draft, _ = build_draft({"business_name": "باشگاه آرمان", "phone": "09121112222", "city": "تهران"}, source_ref="manual")
        self.lead = create_from_draft(draft, SourceInfo(provider="manual"))
        self.m1 = make_mission()
        self.m2 = make_mission()

    def test_an_approved_message_of_one_mission_blocks_a_second_one_from_another_mission(self):
        first = draft_service.generate(self.m1, [self.lead.pk], ["sms"])
        self.assertEqual(first["created"], 1)
        d1 = OutreachDraft.objects.get(lead=self.lead, channel="sms")
        draft_service.approve(d1)
        second = draft_service.generate(self.m2, [self.lead.pk], ["sms"])
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"][0]["reason"], "exists_elsewhere")
        self.assertEqual(OutreachDraft.objects.filter(lead=self.lead, channel="sms").count(), 1)
        # another channel is another message
        self.assertNotEqual(draft_service.generate(self.m2, [self.lead.pk], ["email"])["skipped"][0]["reason"], "exists_elsewhere")

    def test_an_unapproved_draft_of_another_mission_is_replaced_never_duplicated(self):
        draft_service.generate(self.m1, [self.lead.pk], ["sms"])
        again = draft_service.generate(self.m2, [self.lead.pk], ["sms"])
        self.assertEqual(again["created"], 1)
        rows = OutreachDraft.objects.filter(lead=self.lead, channel="sms")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().mission_id, self.m2.pk)

    def test_a_business_already_in_a_campaign_is_not_put_into_a_second_one(self):
        d1 = OutreachDraft.objects.create(mission=self.m1, lead=self.lead, channel="sms", recipient="09121112222", body="x", status=OutreachDraft.Status.QUEUED)
        d2 = OutreachDraft.objects.create(mission=self.m2, lead=self.lead, channel="sms", recipient="09121112222", body="x", status=OutreachDraft.Status.APPROVED)
        with self.assertRaises(Exception) as ctx:
            draft_service.queue(d2)
        self.assertIn("قبلاً", str(getattr(ctx.exception, "errors", ctx.exception)))
        self.assertIsNotNone(d1)


class IndependentCoachOptOutTests(Base, TestCase):
    def test_an_independent_coach_on_the_do_not_contact_list_gets_no_draft_and_cannot_be_approved(self):
        from apps.growth_engine.compliance.services import suppression

        draft, _ = build_draft({"business_name": "مربی آزمون", "phone": "09121110011", "city": "تهران", "tags": [finalize.INDIVIDUAL_TAG]}, source_ref="x")
        lead = create_from_draft(draft, SourceInfo(provider="crawl_directory", source_url="https://morabiyab.com/coach/9/"))
        suppression.add_entries([suppression.classify("09121110011")], "other", "", None)
        out = draft_service.generate(make_mission(), [lead.pk], ["sms"])
        self.assertEqual(out["blocked"], 1)
        d = lead.crawl_drafts.get(channel="sms")
        self.assertEqual(d.status, "blocked")
        with self.assertRaises(Exception):
            draft_service.approve(d)

    def test_the_sms_opt_out_list_blocks_an_independent_coach_too(self):
        from unittest import mock

        draft, _ = build_draft({"business_name": "مربی آزمون", "phone": "09121110022", "city": "تهران", "tags": [finalize.INDIVIDUAL_TAG]}, source_ref="x")
        lead = create_from_draft(draft, SourceInfo(provider="crawl_directory", source_url="https://morabiyab.com/coach/10/"))
        with mock.patch.object(draft_service.sms_channel, "is_opted_out", return_value=True):
            out = draft_service.generate(make_mission(), [lead.pk], ["sms"])
        self.assertEqual(out["blocked"], 1)


# --------------------------------------------------------------------------- results: one row per business


class OneResultPerBusinessTests(Base, TestCase):
    def setUp(self):
        super().setUp()
        self.m1 = make_mission()
        self.m2 = make_mission()
        draft, _ = build_draft({"business_name": "باشگاه بدنسازی پرشیا", "phone": "09121112222", "city": "تهران", "tags": ["چغر · تهران"]}, source_ref="x")
        self.lead = create_from_draft(draft, SourceInfo(provider="crawl_osm"))
        draft, _ = build_draft({"business_name": "کافه رز", "phone": "09125553333", "city": "اصفهان", "tags": ["کافه · اصفهان"]}, source_ref="x")
        self.cafe = create_from_draft(draft, SourceInfo(provider="crawl_osm"))
        CrawlFinding.objects.create(mission=self.m1, lead=self.lead, score=60, level="medium")
        CrawlFinding.objects.create(mission=self.m2, lead=self.lead, score=73, level="high")
        CrawlFinding.objects.create(mission=self.m2, lead=self.cafe, score=40, level="low")

    def rows(self, **params):
        qs = results.order(results.filter_findings(results.base_queryset(params), params), params.get("ordering"))
        return list(results.with_prefetch(qs))

    def test_without_a_mission_filter_a_business_is_one_row_with_its_best_score(self):
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        persia = next(r for r in rows if r.lead_id == self.lead.pk)
        self.assertEqual(persia.score, 73)
        self.assertEqual(results.result_dict(persia)["missions"], 2)
        self.assertEqual(results.result_dict(next(r for r in rows if r.lead_id == self.cafe.pk))["missions"], 1)
        self.assertEqual(len(self.rows(mission=self.m1.pk)), 1)  # with a mission every finding of THAT mission is a row
        self.assertEqual(len(self.rows(mission=self.m2.pk)), 2)

    def test_the_counters_and_the_csv_count_businesses(self):
        staff = make_staff()
        client = client_for(staff)
        self.assertEqual(client.get("/api/v1/growth/finder/results/summary/").json()["total"], 2)
        self.assertEqual(client.get("/api/v1/growth/finder/results/").json()["count"], 2)
        body = b"".join(client.get("/api/v1/growth/finder/results/export/").streaming_content).decode("utf-8-sig")
        lines = [ln for ln in body.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 3)  # the header + two businesses
        self.assertIn("مأموریت‌ها", lines[0])
        self.assertEqual(client.get(f"/api/v1/growth/finder/results/summary/?mission={self.m2.pk}").json()["total"], 2)

    def test_a_part_of_a_tag_finds_the_leads(self):
        self.assertEqual(len(self.rows(tag="چغر")), 1)
        self.assertEqual(len(self.rows(tag="چغر · تهران")), 1)
        self.assertEqual(len(self.rows(tag="کافه")), 1)
        self.assertEqual(len(self.rows(tag="نداریم")), 0)

    def test_a_directory_lead_shows_the_label_of_its_type(self):
        draft, _ = build_draft({"business_name": "باشگاه بدنسازی فیت جیم", "phone": "09121110000", "city": "تهران"}, source_ref="x")
        lead = create_from_draft(draft, SourceInfo(provider="crawl_directory"))
        CrawlFinding.objects.create(mission=self.m1, lead=lead, score=50, level="medium", matched={"types": ["gym"]})
        row = next(r for r in self.rows() if r.lead_id == lead.pk)
        self.assertEqual(results.result_dict(row)["category"], "باشگاه بدنسازی و فیتنس")

    def test_the_pipeline_card_shows_the_phone_like_the_list(self):
        board = pipeline.board()
        cards = [c for s in board["stages"] for c in s["cards"]]
        card = next(c for c in cards if c["id"] == self.cafe.pk)
        self.assertEqual(card["phone"], "0912 555 3333")
        self.assertEqual(card["phone_raw"], "09125553333")


# --------------------------------------------------------------------------- the repair of old rows


class RepairRound3Tests(Base, TestCase):
    def setUp(self):
        super().setUp()
        self.mission = make_mission(cities=["تهران"])

    def lead(self, name, *, city="تهران", address="", phones=(), lat=None, lon=None, provider="crawl_osm", touched=False, website="", types=("gym",),
             source_url="https://www.openstreetmap.org/node/1", category="", mission=None, matched=None):
        raw = {"business_name": name, "city": city, "phone": "; ".join(phones), "website": website, "category": category}
        draft, _ = build_draft({k: v for k, v in raw.items() if v}, source_ref="crawl:1")
        if address:
            draft.profile["address"] = address
        lead = create_from_draft(draft, SourceInfo(provider=provider, source_url=source_url))
        LeadInsight.objects.create(lead=lead, lat=lat, lon=lon, types=list(types))
        CrawlFinding.objects.create(mission=mission or self.mission, lead=lead, score=50, level="medium", matched=matched or {})
        if touched:
            lead.notes.create(body="تماس گرفتم")
        return lead

    def test_another_kind_of_business_is_removed_but_a_gym_called_sparta_stays(self):
        spa = self.lead("اسپا حس خوب زندگی", phones=["09121110001"])
        dealer = self.lead("تجهیزات بدنسازی ویرا بازرگانی وزنه", phones=["09121110002"])
        sparta = self.lead("باشگاه بدنسازی اسپارتا", phones=["09121110003"])
        worked = self.lead("مرکز ماساژ مجید", phones=["09121110004"], touched=True)
        out = repair.run(apply=False)
        self.assertEqual(out["report"]["deleted_not_the_asked_type"], 2)
        self.assertTrue(Lead.objects.filter(pk=spa.pk).exists())  # a dry run changes nothing
        repair.run(apply=True)
        self.assertFalse(Lead.objects.filter(pk__in=[spa.pk, dealer.pk]).exists())
        self.assertTrue(Lead.objects.filter(pk=sparta.pk).exists())
        self.assertTrue(CrawlFinding.objects.filter(lead=sparta).exists())
        self.assertTrue(Lead.objects.filter(pk=worked.pk).exists())  # somebody worked on it: the lead stays, it is just not a result any more
        self.assertFalse(CrawlFinding.objects.filter(lead=worked).exists())
        self.assertEqual(repair.run(apply=True)["report"].get("deleted_not_the_asked_type", 0), 0)  # idempotent

    def test_a_media_site_or_a_directory_is_not_a_website_and_a_lead_with_only_that_is_removed(self):
        media = self.lead("آپارات اسپرت", website="https://aparatsport.ir", provider="crawl_search", types=("sports_club",))
        cybo = self.lead("Fiitac fitness Gym", website="https://cybo.com", provider="crawl_search")
        worked = self.lead("پخش و پوشش مسابقات ورزشی", website="https://telewebion.ir", provider="crawl_search", touched=True, types=("sports_club",))
        own = self.lead("باشگاه آرمان", website="https://arman-gym.ir", phones=["09121110005"])
        self.assertTrue(ContactPoint.objects.filter(lead=media, kind="website").exists())
        out = repair.run(apply=True)
        self.assertEqual(out["report"]["deleted_only_a_foreign_site"], 2)
        self.assertFalse(Lead.objects.filter(pk__in=[media.pk, cybo.pk]).exists())
        worked.refresh_from_db()
        self.assertEqual(worked.website, "")
        self.assertFalse(worked.contacts.filter(kind="website").exists())
        self.assertFalse(CrawlFinding.objects.filter(lead=worked).exists())
        own.refresh_from_db()
        self.assertEqual(own.website, "https://arman-gym.ir")  # an own site is left alone

    def test_a_lead_with_a_position_in_another_city_gets_that_city(self):
        other = make_mission(cities=["اصفهان"], tag="تست اصفهان")
        lead = self.lead("باشگاه بدنسازی فیت لند آقایان", address="ایران، خیابان امام رضا کوچه ۴۳", phones=["09133017913"], lat=32.7015, lon=51.6089, provider="crawl_directory",
                         source_url="https://badanfit.ir/gym-detail.php?id=6470")
        CrawlFinding.objects.create(mission=other, lead=lead, score=54, level="medium")
        tag, _ = LeadTag.objects.get_or_create(name=repair.mission_tag(self.mission))
        lead.tags.add(tag)
        out = repair.run(apply=True)
        self.assertEqual(out["report"]["findings_removed_other_city"], 1)
        lead.refresh_from_db()
        self.assertEqual(lead.city, "اصفهان")
        self.assertEqual(list(lead.crawl_findings.values_list("mission_id", flat=True)), [other.pk])
        self.assertFalse(lead.tags.filter(pk=tag.pk).exists())
        self.assertEqual(repair.run(apply=False)["report"].get("findings_removed_other_city", 0), 0)

    def test_a_missing_category_is_filled_and_a_coach_is_tagged_as_an_independent_person(self):
        gym = self.lead("باشگاه بدنسازی فیت جیم", phones=["09121110006"], provider="crawl_directory", source_url="https://badanfit.ir/gym-detail.php?id=1")
        coach = self.lead("مربی نمونه", phones=["09121110007"], provider="crawl_directory", source_url="https://morabiyab.com/coach/1/", types=("personal_trainer",), category="مربی")
        out = repair.run(apply=True)
        gym.refresh_from_db()
        coach.refresh_from_db()
        self.assertEqual(gym.category, "باشگاه بدنسازی و فیتنس")
        self.assertIn(finalize.INDIVIDUAL_TAG, [t.name for t in coach.tags.all()])
        self.assertEqual(coach.category, finalize.INDIVIDUAL_CATEGORY)
        self.assertTrue(LeadInsight.objects.get(lead=coach).signals["individual"])
        self.assertEqual(out["report"]["individual_tagged"], 1)
        self.assertNotIn(finalize.INDIVIDUAL_TAG, [t.name for t in gym.tags.all()])

    def test_a_gym_loses_the_trainer_type_in_its_insight_and_findings(self):
        gym = self.lead("باشگاه بدنسازی نمونه", phones=["02188776655"], provider="crawl_directory", source_url="https://badanfit.ir/gym-detail.php?id=9",
                        types=("gym", "personal_trainer"), matched={"types": ["gym", "personal_trainer"]})
        repair.run(apply=True)
        self.assertEqual(LeadInsight.objects.get(lead=gym).types, ["gym"])
        self.assertEqual(CrawlFinding.objects.get(lead=gym).matched["types"], ["gym"])

    def test_a_map_gym_with_a_stray_trainer_type_loses_it_but_a_trainer_by_name_keeps_it(self):
        gym = self.lead("باشگاه ورزشی آرینا", phones=["09121110008"], provider="crawl_osm", types=("gym", "personal_trainer"), matched={"types": ["gym", "personal_trainer"]})
        coach = self.lead("مربی آرش", phones=["09121110009"], provider="crawl_osm", types=("gym", "personal_trainer"), matched={"types": ["gym", "personal_trainer"]})
        repair.run(apply=True)
        self.assertEqual(LeadInsight.objects.get(lead=gym).types, ["gym"])
        self.assertEqual(CrawlFinding.objects.get(lead=gym).matched["types"], ["gym"])
        self.assertIn("personal_trainer", LeadInsight.objects.get(lead=coach).types)  # the name says «مربی»: left alone
        self.assertEqual(repair.run(apply=False)["report"].get("trainer_type_removed_from_gym", 0), 0)

    def test_an_sms_draft_an_older_version_cut_is_written_again_but_an_approved_one_is_not(self):
        lead = self.lead("باشگاه آرمان", phones=["09121112222"])
        other = self.lead("باشگاه سپهر", phones=["09121113333"])
        cut = OutreachDraft.objects.create(mission=self.mission, lead=lead, channel="sms", recipient="09121112222", body="«چغر»: دستیارِ هوش مصنوعیِ مربی‌ها برای پیش‌نویسِ برنامهٔ…",
                                           status=OutreachDraft.Status.DRAFT)
        approved = OutreachDraft.objects.create(mission=self.mission, lead=other, channel="sms", recipient="09121113333", body="«چغر»: دستیار…", status=OutreachDraft.Status.APPROVED)
        twin = OutreachDraft.objects.create(mission=make_mission(), lead=lead, channel="sms", recipient="09121112222", body="«چغر»: چغر دستیار…", status=OutreachDraft.Status.DRAFT)
        out = repair.run(apply=True)
        self.assertEqual(out["report"]["sms_drafts_rewritten"], 1)  # two missions each wrote a cut draft for one lead: one rewritten draft remains
        self.assertEqual(OutreachDraft.objects.filter(lead=lead, channel="sms").count(), 1)
        self.assertIsNotNone(twin)
        cut = OutreachDraft.objects.get(lead=lead, channel="sms")
        approved.refresh_from_db()
        self.assertNotIn("…", cut.body)
        self.assertIn("چغر", cut.body)
        self.assertIn("…", approved.body)  # what a person approved is never changed behind their back

    def test_a_preset_mission_with_an_old_long_sms_line_gets_the_short_one(self):
        m = missions.create_from_preset("chagher_gyms_tehran")
        m.spec = {**m.spec, "pitch": {**m.spec["pitch"], "sms": SmsDraftTests.OLD_LONG}}
        m.save()
        repair.run(apply=True)
        m.refresh_from_db()
        self.assertEqual(m.spec["pitch"]["sms"], presets.PRESETS["chagher_gyms_tehran"].pitch.sms)
        self.assertTrue(m.spec["include_individuals"])
        self.assertTrue(m.spec["budget"].get("max_ig_queries") is not None)


# --------------------------------------------------------------------------- the API and the form's data


class ApiRound3Tests(Base, TestCase):
    def setUp(self):
        super().setUp()
        self.client = client_for(make_staff())

    def test_meta_carries_the_sms_room_the_individuals_note_and_the_engine_rest(self):
        search.start_cooldown("brave", "HTTP 403")
        data = self.client.get("/api/v1/growth/finder/meta/").json()
        self.assertGreater(data["outreach"]["sms_room"], 30)
        self.assertEqual(data["individuals"]["tag"], finalize.INDIVIDUAL_TAG)
        self.assertIn("brave", data["engines"]["cooldown"])
        self.assertFalse(data["engines"]["brave_api"])
        self.assertIn("Brave", [s for s in data["sources"] if s["key"] == "search"][0]["label"])
        preset = next(p for p in data["presets"] if p["key"] == "chagher_coaches_instagram")
        self.assertTrue(preset["spec"]["ig_hashtags"])
        self.assertTrue(preset["spec"]["include_individuals"])

    def test_a_mission_keeps_its_hashtags_locations_and_the_individuals_switch(self):
        body = {"name": "x", "product": "chagher", "spec": {"business_types": ["personal_trainer"], "cities": ["تهران"], "sources": {"instagram": True, "osm": False},
                                                              "ig_hashtags": ["#مربی_بدنسازی", "#مربی_بدنسازی", "#x"], "ig_locations": ["پونک"], "include_individuals": False,
                                                              "budget": {"max_ig_queries": 3}}}
        res = self.client.post("/api/v1/growth/finder/missions/", body, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        spec = res.json()["spec"]
        self.assertEqual(spec["ig_hashtags"], ["#مربی_بدنسازی", "#x"])
        self.assertEqual(spec["ig_locations"], ["پونک"])
        self.assertFalse(spec["include_individuals"])
        self.assertEqual(spec["budget"]["max_ig_queries"], 3)
        bad = self.client.post("/api/v1/growth/finder/missions/", {**body, "spec": {**body["spec"], "budget": {"max_ig_queries": 99}}}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_the_probe_answers_with_the_engine_state_including_the_rest(self):
        search.start_cooldown("brave", "HTTP 403")
        # the fake web comes from the test: no real engine is asked
        web = FakeWeb()
        web.add("www.bing.com", "/search", bing_page([("https://sepehr-gym.ir/", "باشگاه بدنسازی سپهر", "gym")]))
        from unittest import mock

        with mock.patch.object(fetch, "make_fetcher", web.factory):
            res = self.client.post("/api/v1/growth/finder/engines/probe/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["engines"]["brave"]["resting"])
        self.assertIn("brave", data["cooldown"])


class ReviewLeftoversTests(TestCase):
    def test_nothing_of_the_old_sms_cut_remains_in_the_code(self):
        self.assertFalse(re.search(r"…", draft_service.fit_sms("چغر", ["الف " * 80], 40)))
        self.assertIsNotNone(osm_node)
        self.assertIsNotNone(overpass_json)
        self.assertIsNotNone(NOMINATIM_TEHRAN)
        self.assertIsNotNone(Channel)
        self.assertIsNotNone(runner)
