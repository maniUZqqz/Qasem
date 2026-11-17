"""The fixes after the review of the finder on the live site (2026-11-17): wrong-city leads, false cross-city merges, the personal trainers,
personal data and filler values taken from web pages, the SMS length, results that are not the asked type, city spellings, directory boilerplate.

Everything runs against canned pages (``FakeWeb``); nothing real is contacted and nothing is sent.
"""
from __future__ import annotations

import re

from django.test import TestCase

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.leads.choices import ActivityKind
from apps.growth_engine.leads.models import ContactPoint, Lead, LeadActivity, LeadTag
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.leads.services.intake import SourceInfo, create_from_draft
from apps.growth_engine.outreach.channels import sms as sms_channel
from apps.growth_engine.outreach.models import Channel
from apps.growth_engine.outreach.services import rendering

from .. import presets
from ..engine import candidates, contactrules, finalize, place, runner, scoring, textnorm
from ..engine.candidates import Found
from ..engine.sources import coaches, directory, search, website
from ..engine.sources.website import PageData
from ..models import CrawlCandidate, CrawlFinding, CrawlLog, CrawlRun, CrawlTask, LeadInsight, LeadReminder
from ..services import drafts as draft_service
from ..services import missions, repair
from .helpers import BADANFIT_LIST, NOMINATIM_TEHRAN, Base, FakeWeb, bing_page, make_mission, osm_node, overpass_json


def run_it(web: FakeWeb, mission=None, **spec) -> CrawlRun:
    mission = mission or make_mission(**spec)
    run = missions.start_run(mission, None, dispatch=False)
    runner.run_crawl(run.pk, web_factory=web.factory)
    run.refresh_from_db()
    return run


# --------------------------------------------------------------------------- where is a business


class PlaceTests(TestCase):
    def test_city_names_are_made_canonical(self):
        for raw in ("شهر تهران", "tehran", "Tehran", "منطقه ۴ شهر تهران", "TEHRAN", "تهران"):
            self.assertEqual(place.canonical_city(raw), "تهران", raw)
        for raw in ("Isfahan", "isfahan", "Esfahan", "اصفهان خوراسگان", "شهر اصفهان"):
            self.assertEqual(place.canonical_city(raw), "اصفهان", raw)
        self.assertEqual(place.canonical_city("شهر مشهد"), "مشهد")
        self.assertEqual(place.canonical_city("شهر ناشناخته"), "ناشناخته")
        self.assertEqual(place.canonical_city(""), "")

    def test_a_zwnj_next_to_a_space_does_not_hide_the_city(self):
        for text, city in (("نجف‌ آباد، یزدانشهر، بلوار طالقانی", "نجف‌آباد"), ("شاهین‌ شهر، گلدیس", "شاهین‌شهر"), ("خمینی‌  شهر، خیابان", "خمینی‌شهر")):
            self.assertEqual(place.address_cities(text), [city], text)
        # the Najafabad address of a lead labelled «Tehran» is another city's
        self.assertEqual(place.verdict(["تهران"], address="نجف‌ آباد، یزدانشهر، بلوار طالقانی، J8H5+7FG").state, "out")

    def test_a_street_named_after_a_city_is_not_the_city(self):
        self.assertEqual(place.address_cities("تهران، خیابان شیراز جنوبی، پلاک ۴"), ["تهران"])
        self.assertEqual(place.address_cities("خیابان شیراز، پلاک ۴"), [])
        self.assertEqual(place.address_cities("بلوار اصفهان، کرج"), ["کرج"])
        self.assertEqual(place.address_cities("Tehran, Valiasr Street"), ["تهران"])
        self.assertEqual(place.address_cities("اتوبان تهران-کرج، کیلومتر ۵"), [])  # the highway's name, both halves

    def test_verdict_uses_the_businesss_own_evidence(self):
        self.assertEqual(place.verdict(["تهران"], address="اصفهان، سپاهان شهر، HM5H+GJ7").state, "out")
        self.assertEqual(place.verdict(["تهران"], address="تهران، ونک، پلاک ۱۲").state, "in")
        self.assertEqual(place.verdict(["تهران"], address="کرج، گوهردشت").state, "out")
        self.assertEqual(place.verdict(["تهران", "اصفهان"], address="اصفهان، چهارباغ").state, "in")
        self.assertEqual(place.verdict(["تهران"], lat=32.65, lon=51.67).state, "out")  # a position in Isfahan
        self.assertEqual(place.verdict(["تهران"], lat=35.72, lon=51.41).state, "in")
        self.assertEqual(place.verdict(["تهران"], phones=["03132221111"]).state, "out")  # an Isfahan landline
        self.assertEqual(place.verdict(["تهران"], phones=["09121112222"]).state, "unknown")  # a mobile number says nothing about the place
        self.assertEqual(place.verdict(["تهران"]).state, "unknown")
        self.assertEqual(place.verdict(["تهران"], mapped=True).state, "in")
        self.assertEqual(place.verdict([], address="اصفهان").state, "unknown")  # a mission without cities asks for no place

    def test_a_listing_url_says_which_city_it_is_about(self):
        self.assertEqual(place.city_of_url("https://badanfit.ir/gym-hub.php?city=isfahan"), "اصفهان")
        self.assertEqual(place.city_of_url("https://badanfit.ir/gym-hub.php?city=tehran&type=fitness&area=north"), "تهران")
        self.assertEqual(place.city_of_url("https://www.gymcenter.ir/%D8%A8%D8%A7%D8%B4%DA%AF%D8%A7%D9%87-%D9%87%D8%A7%DB%8C/%D8%A7%D8%B3%D8%AA%D8%A7%D9%86/%D8%A7%D8%B5%D9%81%D9%87%D8%A7%D9%86"), "اصفهان")
        self.assertEqual(place.city_of_url("https://x.ir/gyms"), "")

    def test_map_plus_codes_are_not_part_of_an_address(self):
        self.assertEqual(place.strip_plus_code("Q863+VV3، تهران"), "تهران")
        self.assertEqual(place.strip_plus_code("ری، منطقه ۲۰، کوچه پویا، HCQJ+5HF"), "ری، منطقه ۲۰، کوچه پویا")

    def test_two_descriptions_of_different_places_conflict(self):
        tehran = place.place_of("تهران، ونک", [], 35.72, 51.41)
        isfahan = place.place_of("اصفهان، چهارباغ")
        self.assertTrue(place.conflicts(tehran, isfahan))
        self.assertTrue(place.conflicts(place.place_of("", [], 35.7, 51.4), place.place_of("", [], 32.6, 51.6)))
        self.assertFalse(place.conflicts(tehran, place.place_of("", [], None, None)))
        self.assertFalse(place.conflicts(tehran, place.place_of("تهران، سعادت‌آباد", [], 35.74, 51.37)))

    def test_names_that_differ_in_a_number_are_two_businesses(self):
        a, b = textnorm.name_core("باشگاه بدنسازی 7"), textnorm.name_core("باشگاه بدنسازی 12")
        self.assertEqual(textnorm.similar(a, b), 0.0)
        self.assertEqual(textnorm.similar(textnorm.name_core("باشگاه بدنسازی ۷"), a), 1.0)  # a Persian digit is the same digit


# --------------------------------------------------------------------------- merging and taking


class CandidateFixTests(Base, TestCase):
    def setUp(self):
        super().setUp()
        self.run = CrawlRun.objects.create(mission=make_mission(), spec={"cities": ["تهران"]})

    def add(self, **kw):
        kw.setdefault("source", "osm")
        return candidates.add_found(self.run, Found(**kw))

    def test_a_directory_entry_with_an_address_in_another_city_is_not_taken(self):
        cand, created = self.add(name="باشگاه بدنسازی پردیس", source="directory", city="تهران", address="اصفهان، سپاهان شهر", phones=["03136601234"])
        self.assertIsNone(cand)
        self.assertFalse(created)
        self.assertEqual(CrawlCandidate.objects.filter(run=self.run).count(), 0)

    def test_a_map_object_far_from_the_city_is_not_taken(self):
        cand, _ = self.add(name="باشگاه دور", city="تهران", lat=32.65, lon=51.67)
        self.assertIsNone(cand)

    def test_a_tehran_map_entry_and_an_isfahan_listing_with_the_same_name_never_merge(self):
        self.run.spec = {"cities": ["تهران", "اصفهان"]}
        a, _ = self.add(name="باشگاه بدنسازی 7", city="تهران", lat=35.7189, lon=51.4139, phones=["02126658025"])
        b, created = self.add(name="باشگاه بدنسازی 7", source="directory", city="اصفهان", city_src="evidence", address="اصفهان، سپاهان شهر", phones=["09195062507"])
        self.assertTrue(created)
        self.assertNotEqual(a.pk, b.pk)
        a.refresh_from_db()
        self.assertEqual(a.phones, ["02126658025"])  # the Isfahan phone did not get attached to the Tehran gym
        self.assertEqual(a.address, "")

    def test_a_phone_shared_by_two_cities_does_not_merge_them(self):
        self.run.spec = {"cities": ["تهران", "اصفهان"]}
        a, _ = self.add(name="الف", address="تهران، ونک", phones=["09195062507"])
        b, created = self.add(name="ب", address="اصفهان، چهارباغ", phones=["09195062507"], source="directory")
        self.assertTrue(created)
        self.assertNotEqual(a.pk, b.pk)

    def test_names_that_differ_in_a_number_are_not_merged(self):
        a, _ = self.add(name="باشگاه بدنسازی 7", city="تهران", lat=35.70, lon=51.40)
        b, created = self.add(name="باشگاه بدنسازی 12", city="تهران", lat=35.7002, lon=51.4002)
        self.assertTrue(created)
        self.assertNotEqual(a.pk, b.pk)

    def test_placeholder_social_pages_are_dropped(self):
        c, _ = self.add(name="باشگاه نمونه", city="تهران", phones=["02122223333"], instagram="https://www.instagram.com/0/", telegram="https://t.me/test")
        self.assertEqual((c.instagram, c.telegram), ("", ""))
        d, _ = self.add(name="باشگاه واقعی", city="تهران", phones=["02122224444"], instagram="https://www.instagram.com/arman.gym/", telegram="https://t.me/arman_gym")
        self.assertEqual((d.instagram, d.telegram), ("https://www.instagram.com/arman.gym/", "https://t.me/arman_gym"))

    def test_city_names_are_stored_canonical(self):
        c, _ = self.add(name="باشگاه آرمان", city="منطقه ۴ شهر تهران", phones=["09121112222"])
        self.assertEqual(c.city, "تهران")
        d, _ = self.add(name="باشگاه سپهر", city="Tehran", phones=["09121113333"])
        self.assertEqual(d.city, "تهران")

    def test_filler_numbers_are_dropped(self):
        c, _ = self.add(name="باشگاه آرمان", phones=["09123456789", "09121112222"], whatsapp=["09123456789"])
        self.assertEqual(c.phones, ["09121112222"])
        self.assertEqual(c.whatsapp, [])

    def test_every_contact_value_remembers_its_own_page(self):
        c, _ = self.add(name="باشگاه آرمان", url="https://www.openstreetmap.org/node/1", phones=["02122223333"])
        candidates.add_found(self.run, Found(
            name="باشگاه آرمان", source="website", url="https://arman-gym.ir", phones=["02122223333"], emails=["info@arman-gym.ir"],
            prov={"email:info@arman-gym.ir": {"url": "https://arman-gym.ir/contact", "evidence": "لینک mailto:", "confidence": 90}},
        ))
        c.refresh_from_db()
        prov = c.signals["prov"]
        self.assertEqual(prov["email:info@arman-gym.ir"]["url"], "https://arman-gym.ir/contact")
        self.assertEqual(prov["phone:02122223333"]["url"], "https://www.openstreetmap.org/node/1")  # the phone was first read on the map

    def test_a_media_site_is_not_a_businesss_website(self):
        c, _ = self.add(name="باشگاه یک", website="https://aparatsport.ir", phones=["09121112222"])
        self.assertEqual(c.website, "")
        d, _ = self.add(name="باشگاه دو", website="https://telewebion.ir", phones=["09121113333"])
        self.assertEqual(d.website, "")
        self.assertTrue(search.blocked_host("telewebion.ir"))

    def test_scoring_claims_the_city_only_with_evidence(self):
        spec = {"business_types": ["gym"], "cities": ["تهران"], "keywords": []}
        cand = self.run.candidates.model(name="باشگاه آرمان", types=["gym"], city="تهران", phones=["09121112222"], address="", lat=None, lon=None, sources=[{"source": "search"}], signals={})
        reasons = " ".join(r["text"] for r in scoring.score(cand, spec)["reasons"])
        self.assertNotIn("در «تهران» است", reasons)  # it only turned up in a search for Tehran
        cand.address = "تهران، ونک"
        self.assertIn("در «تهران» است", " ".join(r["text"] for r in scoring.score(cand, spec)["reasons"]))
        cand.address = "اصفهان، چهارباغ"
        self.assertLess(scoring.score(cand, spec)["value"], 10)


# --------------------------------------------------------------------------- contacts of a site


HOME_WITH_STRANGERS = """<html lang="fa"><head><title>کافه سفر</title></head><body><h1>کافه سفر</h1>
<p>نظر مشتری: ممنون از آقای نمونه، تماس با ایشان 09138374010 یا m.dorri@gmail.com</p>
<p>safie558@yahoo.com و zarbaha.kiana_1415@yahoo.com هم از دوستان ما هستند.</p>
<p>شماره نمونه: 09123456789</p></body></html>"""
CONTACT_OK = """<html lang="fa"><head><script type="application/ld+json">{"@type":"Organization","name":"کافه سفر","email":"vanadiumdev.ir@gmail.com"}</script></head><body><h1>تماس با ما</h1>
<p>تلفن: <a href="tel:+989133093934">۰۹۱۳ ۳۰۹ ۳۹۳۴</a></p><p><a href="mailto:info@faslesafar.com">info@faslesafar.com</a></p>
<footer><p>تلفن دفتر: 03191015052</p><p>طراحی و توسعه وب‌سایت توسط <a href="mailto:webdev.agency@gmail.com">webdev.agency@gmail.com</a> 09121830000</p></footer></body></html>"""


class ContactHygieneTests(TestCase):
    def info(self, pages, home="https://faslesafar.com"):
        return website.analyze_site(pages, home_url=home, type_words=["کافه"], fit_words=[])

    def test_strangers_on_a_home_page_are_not_the_businesss_contacts(self):
        info = self.info([PageData("https://faslesafar.com/", "home", HOME_WITH_STRANGERS, 200)])
        self.assertEqual(info.fields["emails"], [])
        self.assertEqual(info.fields["phones"], [])  # a customer's number in a testimonial, a template's filler

    def test_a_contact_page_gives_the_businesss_own_lines_and_their_page(self):
        info = self.info([PageData("https://faslesafar.com/", "home", HOME_WITH_STRANGERS, 200), PageData("https://faslesafar.com/contact", "contact", CONTACT_OK, 200)])
        self.assertEqual(info.fields["emails"], ["info@faslesafar.com"])  # the developer's JSON-LD address and the credit line are not it
        self.assertIn("09133093934", info.fields["phones"])
        self.assertIn("03191015052", info.fields["phones"])
        self.assertNotIn("09121830000", info.fields["phones"])  # the web agency's number in the credit
        self.assertEqual(info.prov["email:info@faslesafar.com"]["url"], "https://faslesafar.com/contact")
        self.assertEqual(info.prov["phone:09133093934"]["url"], "https://faslesafar.com/contact")

    def test_a_site_gives_at_most_three_mobile_numbers(self):
        links = "".join(f'<p><a href="tel:0913{i}00{i}{i}{i}">x</a></p>' for i in (1, 2, 3, 4, 5, 6))
        info = self.info([PageData("https://shop.ir/contact", "contact", f"<html lang='fa'><body><h1>تماس</h1>{links}</body></html>", 200)], home="https://shop.ir")
        self.assertLessEqual(len(info.fields["phones"]), contactrules.MAX_SITE_MOBILES)

    def test_rules_of_the_policy(self):
        self.assertTrue(contactrules.is_placeholder_phone("09123456789"))
        self.assertTrue(contactrules.is_placeholder_phone("۰۹۱۲۱۲۳۴۵۶۷"))
        self.assertTrue(contactrules.is_placeholder_phone("09111111111"))
        self.assertFalse(contactrules.is_placeholder_phone("09133093934"))
        self.assertFalse(contactrules.is_placeholder_phone("02122209491"))
        self.assertFalse(contactrules.email_ok("m.dorri@gmail.com", 65, "x.ir"))  # a free-mail address in running text
        self.assertTrue(contactrules.email_ok("m.dorri@gmail.com", 90, "x.ir"))  # ... but a mailto: link is the page's own choice
        self.assertFalse(contactrules.email_ok("vanadiumdev.ir@gmail.com", 90, "sifo.ir"))
        self.assertTrue(contactrules.email_ok("info@x.ir", 65, "www.x.ir"))
        self.assertFalse(contactrules.email_ok("info@other.ir", 65, "x.ir"))

    def test_a_template_demo_number_is_not_the_businesss(self):
        filler = "<p>" + "باشگاه بدنسازی با مربی شخصی و برنامهٔ تمرینی. " * 12 + "</p>"
        html = f"<html lang='fa'><body><h1>تماس با ما</h1>{filler}<a href='tel:03145264867'>03145264867</a><a href='tel:+989134716857'>0912000000</a></body></html>"
        info = self.info([PageData("https://pw.ir/", "home", f"<html lang='fa'><body><h1>باشگاه</h1>{filler}</body></html>", 200), PageData("https://pw.ir/contact", "contact", html, 200)], home="https://pw.ir")
        self.assertIn("03145264867", info.fields["phones"])
        self.assertNotIn("09134716857", info.fields["phones"])  # the link dials another number than it shows: the template's own line

    def test_placeholder_social_pages(self):
        for value, kind in (("https://www.instagram.com/0/", "instagram"), ("https://t.me/test", "telegram"), ("https://t.me/09385824083", "telegram"), ("@username", "instagram")):
            self.assertTrue(contactrules.is_placeholder_handle(value, kind), value)
        self.assertFalse(contactrules.is_placeholder_handle("https://www.instagram.com/arman.gym/", "instagram"))
        self.assertFalse(contactrules.is_placeholder_handle("https://t.me/arman_gym", "telegram"))
        self.assertFalse(contactrules.is_placeholder_handle("", "instagram"))

    def test_the_directorys_own_handle_is_not_a_listed_businesss(self):
        self.assertTrue(contactrules.own_handle("badanfitir", "badanfit.ir"))
        self.assertTrue(contactrules.own_social("https://www.instagram.com/badanfitir/", "badanfit.ir"))
        self.assertFalse(contactrules.own_handle("arman.gym", "badanfit.ir"))


# --------------------------------------------------------------------------- directories


CARD_ISFAHAN = """<a href="gym-detail.php?id=77" class="gym-card"><div class="gym-card-name">باشگاه پاسارگاد</div><div class="gym-card-address">اصفهان، خیابان چهارباغ</div>
<div class="gym-card-meta"><span class="gym-card-phone">031 3222 1111</span></div></a>"""
DETAIL_WITH_OWN_HANDLE = """<html><head><title>باشگاه ورزشی نمونه | بدن‌فیت</title></head><body><h1>باشگاه ورزشی نمونه</h1>
<p>تلفن: <a href="tel:02122000001">021 2200 0001</a></p>
<p><a href="https://www.instagram.com/badanfitir/">اینستاگرام ما</a></p><p><a href="https://www.instagram.com/arman.gym/">اینستاگرام باشگاه</a></p>
<footer><a href="https://t.me/badanfit_channel">تلگرام</a> <a href="mailto:info@badanfit.ir">info@badanfit.ir</a></footer></body></html>"""


class DirectoryFixTests(Base, TestCase):
    def test_a_bodybuilding_list_is_a_list_of_gyms_not_of_trainers(self):
        self.assertNotIn("personal_trainer", directory.BADANFIT_TYPES)
        task = directory._list_task("badanfit", "تهران", "tehran", "bodybuilding", "", ["gym", "personal_trainer", "sports_club"])
        self.assertEqual(task.params["types"], ["gym"])
        fitness = directory._list_task("badanfit", "تهران", "tehran", "fitness", "", ["gym", "sports_club"])
        self.assertEqual(fitness.params["types"], ["gym", "sports_club"])

    def test_every_city_gets_its_share_of_the_directory_pages(self):
        spec = {"business_types": ["gym", "personal_trainer"], "cities": ["تهران", "اصفهان", "مشهد", "شیراز"], "sources": {"directory": True},
                "budget": {"max_directory_pages": 12}}
        urls = [t.params["url"] for t in directory.plan(spec) if t.params.get("directory") == "badanfit"]
        for slug in ("tehran", "isfahan", "mashhad"):
            self.assertGreaterEqual(sum(1 for u in urls if f"city={slug}" in u), 3, slug)
        self.assertFalse([u for u in urls if "shiraz" in u])  # badanfit.ir has no Shiraz page (HTTP 404): no failing tasks are planned for it
        self.assertEqual(directory.unsupported_cities(spec), ["شیراز"])
        self.assertEqual(directory.unsupported_cities({**spec, "business_types": ["cafe"]}), [])
        self.assertEqual([u for u in urls[:4]], [u for u in urls[:4] if "area=" not in u])  # the basic lists come before the sub-area lists
        self.assertTrue(any(t.params.get("directory") == "morabiyab" for t in directory.plan(spec)))  # the coach directory is planned for personal trainers

    def test_search_queries_are_shared_between_the_cities(self):
        qs = search.build_queries({"business_types": ["gym"], "cities": ["تهران", "اصفهان", "مشهد", "شیراز"], "keywords": []}, 8)
        self.assertEqual({q["city"] for q in qs}, {"تهران", "اصفهان", "مشهد", "شیراز"})

    def test_a_listing_of_another_city_found_by_search_is_not_followed(self):
        web = FakeWeb()
        web.add("www.bing.com", "/search", bing_page([("https://badanfit.ir/gym-hub.php?city=isfahan", "باشگاه بدنسازی تهران | بدن فیت", "باشگاه‌های بدنسازی تهران و اصفهان")]))
        run = run_it(web, sources={"osm": False, "search": True, "directory": False, "website": False, "instagram": False, "neshan": False},
                     budget={"max_requests": 40, "max_search_queries": 2, "domain_delay": 1.0})
        self.assertEqual(run.status, "completed", run.error)
        self.assertFalse(CrawlTask.objects.filter(run=run, source="directory").exists())
        self.assertEqual(web.hits("badanfit.ir"), 0)

    def test_a_card_of_another_city_is_not_a_tehran_lead_and_the_directory_footer_is_not_a_contact(self):
        web = FakeWeb()
        web.add("nominatim.openstreetmap.org", "/search", NOMINATIM_TEHRAN)
        page = BADANFIT_LIST.replace("</div></body>", CARD_ISFAHAN + "</div></body>")
        web.add("badanfit.ir", "/gym-hub.php", page)
        web.add("badanfit.ir", "/gym-detail.php?id=11", DETAIL_WITH_OWN_HANDLE)
        web.add("badanfit.ir", "/gym-detail.php?id=12", DETAIL_WITH_OWN_HANDLE.replace("02122000001", "02122000002").replace("arman.gym", "sepehr.gym").replace("باشگاه ورزشی نمونه", "باشگاه نمونه دو"))
        run = run_it(web, sources={"osm": False, "search": False, "directory": True, "website": False, "instagram": False, "neshan": False}, require_contact=True)
        names = set(CrawlCandidate.objects.filter(run=run).values_list("name", flat=True))
        self.assertNotIn("باشگاه پاسارگاد", names)
        self.assertTrue({"باشگاه ورزشی نمونه یک", "باشگاه نمونه دو"} <= names)
        for c in CrawlCandidate.objects.filter(run=run):
            self.assertNotIn("badanfitir", c.instagram)
            self.assertNotIn("badanfit_channel", c.telegram)
            self.assertNotIn("info@badanfit.ir", c.emails)
        self.assertTrue(CrawlLog.objects.filter(run=run, message__contains="شهرِ دیگری").exists())

    def test_detail_page_drops_the_directorys_own_social_pages(self):
        found = directory.parse_detail(DETAIL_WITH_OWN_HANDLE, "https://badanfit.ir/gym-detail.php?id=5", directory="badanfit", types=["gym"], city="تهران")
        self.assertIn("arman.gym", found.instagram)
        self.assertEqual(found.telegram, "")
        self.assertEqual(found.emails, [])


# --------------------------------------------------------------------------- the coach directory (personal trainers)


COACH_LIST = """<html lang="fa"><body><section class="directory-results">
<article class="coach-card" data-coach-id="101"><h3><a href="https://morabiyab.com/coaches/a-tehran/">علی نمونه‌ی تهرانی</a></h3><p><span>بدنسازی، فیتس</span></p><p><span>تهران، تهران</span></p><p><span>حضوری</span></p></article>
<article class="coach-card" data-coach-id="102"><h3><a href="https://morabiyab.com/coaches/b-isfahan/">سارا نمونه‌ی اصفهانی</a></h3><p><span>بدنسازی</span></p><p><span>اصفهان، اصفهان</span></p><p><span>آنلاین</span></p></article>
<article class="coach-card" data-coach-id="103"><h3><a href="https://morabiyab.com/coaches/c-dance/">مریم نمونه‌ی رقص</a></h3><p><span>رقص، زومبا</span></p><p><span>تهران، تهران</span></p><p><span>حضوری</span></p></article>
<article class="coach-card" data-coach-id="104"><h3><a href="https://morabiyab.com/coaches/d-shiraz/">رضا نمونه‌ی شیرازی</a></h3><p><span>بدنسازی</span></p><p><span>فارس، شیراز</span></p><p><span>حضوری</span></p></article>
</section><nav class="pagination directory-pagination"><a class="page-numbers" href="https://morabiyab.com/all-coaches/?my_page=2">2</a></nav></body></html>"""
COACH_PROFILE = """<html lang="fa"><body><header><a href="tel:09372008782">پشتیبانی</a></header><h1>{name}</h1>
<aside class="coach-contact-panel" aria-label="ارتباط با مربی"><h2>ارتباط با مربی</h2><div class="coach-contact-actions">
<details><a data-coach-contact="phone" href="tel:{phone}"><bdi>{phone}</bdi></a></details>
<a data-coach-contact="whatsapp" href="https://wa.me/98{wa}">واتساپ</a><a data-coach-contact="instagram" href="https://www.instagram.com/{ig}">اینستاگرام</a>
<a data-coach-contact="telegram" href="https://t.me/{tg}">تلگرام</a></div></aside>
<footer><a href="https://wa.me/989372008782">پیام در واتساپ</a><a href="https://www.instagram.com/morabi_yab">morabi_yab</a></footer></body></html>"""


def coach_web() -> FakeWeb:
    web = FakeWeb()
    web.add("morabiyab.com", "/all-coaches/", COACH_LIST, exact=True)
    web.add("morabiyab.com", "/all-coaches/?my_page=2", "<html><body><section class='directory-results'></section></body></html>")
    web.add("morabiyab.com", "/coaches/a-tehran/", COACH_PROFILE.format(name="علی نمونه‌ی تهرانی", phone="09121834765", wa="9121834765", ig="ali.fit", tg="ali_fit"))
    web.add("morabiyab.com", "/coaches/b-isfahan/", COACH_PROFILE.format(name="سارا نمونه‌ی اصفهانی", phone="09131834765", wa="9131834765", ig="sara.coach", tg="sara_coach"))
    web.add("morabiyab.com", "/coaches/c-dance/", COACH_PROFILE.format(name="مریم", phone="09141834765", wa="9141834765", ig="m.dance", tg="m_dance"))
    web.add("morabiyab.com", "/coaches/d-shiraz/", COACH_PROFILE.format(name="رضا", phone="09171834765", wa="9171834765", ig="reza.fit", tg="reza_fit"))
    return web


class CoachNameTests(TestCase):
    def test_the_directorys_badge_is_not_part_of_the_coachs_name(self):
        html = ('<html><body><h1>مریم فرهادی <span class="icon"><svg></svg></span><span>تایید و توصیه شده از طرف تیم مربی یاب فارس</span></h1>'
                '<aside class="coach-contact-panel"><a href="tel:09121112233">تماس</a></aside></body></html>')
        found = coaches.parse_profile(html, "https://morabiyab.com/coaches/x/")
        self.assertEqual(found.name, "مریم فرهادی")
        bare = coaches.parse_profile(html.replace("<span>", "<b>").replace("</span></h1>", "</b></h1>"), "https://morabiyab.com/coaches/x/")
        self.assertEqual(bare.name, "مریم فرهادی")  # even when the badge is not wrapped in a span
        self.assertEqual(coaches.parse_profile(html, "https://morabiyab.com/coaches/x/", {"name": "مریم فرهادی"}).name, "مریم فرهادی")


class CoachDirectoryTests(Base, TestCase):
    NO_MAP = {"osm": False, "search": False, "directory": True, "website": False, "instagram": False, "neshan": False}

    def test_cards_and_profile_are_read(self):
        cards = coaches.parse_cards(COACH_LIST)
        self.assertEqual([c["name"] for c in cards][:2], ["علی نمونه‌ی تهرانی", "سارا نمونه‌ی اصفهانی"])
        self.assertEqual((cards[0]["city"], cards[0]["mode"]), ("تهران", "in_person"))
        self.assertEqual(cards[1]["mode"], "online")
        self.assertEqual(coaches.last_page(COACH_LIST), 2)
        found = coaches.parse_profile(COACH_PROFILE.format(name="علی", phone="09121834765", wa="9121834765", ig="ali.fit", tg="ali_fit"), "https://morabiyab.com/coaches/a-tehran/", cards[0])
        self.assertEqual(found.types, ["personal_trainer"])
        self.assertEqual(found.phones, ["09121834765"])
        self.assertIn("ali.fit", found.instagram)
        self.assertIn("ali_fit", found.telegram)
        self.assertEqual(found.city, "تهران")

    def test_trainers_of_the_asked_city_become_leads_and_the_directorys_own_numbers_do_not(self):
        run = run_it(coach_web(), business_types=["personal_trainer"], keywords=[], sources=self.NO_MAP, require_contact=True)
        self.assertEqual(run.status, "completed", run.error)
        names = set(CrawlCandidate.objects.filter(run=run).values_list("name", flat=True))
        self.assertEqual(names, {"علی نمونه‌ی تهرانی"})  # the Isfahan online coach needs «include_online», the dance teacher is no fitness coach, the Shiraz one is elsewhere
        lead = Lead.objects.get(business_name="علی نمونه‌ی تهرانی")
        values = {(c.kind, c.value) for c in lead.contacts.all()}
        self.assertIn(("phone", "09121834765"), values)
        self.assertFalse(any("09372008782" in v for _, v in values))
        self.assertFalse(any("morabi_yab" in v for _, v in values))
        self.assertTrue(all(c.source_url.startswith("https://morabiyab.com/coaches/") for c in lead.contacts.all()))

    def test_online_coaches_of_other_cities_come_only_when_the_mission_takes_them(self):
        run = run_it(coach_web(), business_types=["personal_trainer"], keywords=[], sources=self.NO_MAP, require_contact=True, include_online=True)
        names = set(CrawlCandidate.objects.filter(run=run).values_list("name", flat=True))
        self.assertEqual(names, {"علی نمونه‌ی تهرانی", "سارا نمونه‌ی اصفهانی"})

    def test_no_trainer_directory_is_planned_without_the_trainer_type(self):
        self.assertEqual(coaches.plan({"business_types": ["gym"]}), [])


# --------------------------------------------------------------------------- leads


class FinalizeFixTests(Base, TestCase):
    def web(self) -> FakeWeb:
        web = FakeWeb()
        web.add("nominatim.openstreetmap.org", "/search", NOMINATIM_TEHRAN)
        web.add("overpass-api.de", "/api/interpreter", overpass_json([
            osm_node(1, "باشگاه بدنسازی آرمان", 35.7001, 51.4001, leisure="fitness_centre", phone="09121112222"),
            osm_node(2, "اسپا حس خوب زندگی", 35.71, 51.41, leisure="fitness_centre", phone="02188507080"),
            osm_node(3, "تجهیزات بدنسازی ویرا بازرگانی", 35.72, 51.42, leisure="fitness_centre", phone="02188507081"),
            osm_node(4, "Sparta Gym", 35.73, 51.43, leisure="fitness_centre", phone="09121113333"),
            osm_node(5, "باشگاه بدون راه تماس", 35.74, 51.44, leisure="fitness_centre"),
            osm_node(6, "باشگاه دور از شهر", 32.65, 51.67, leisure="fitness_centre", phone="09121114444"),
        ]))
        return web

    def test_other_kinds_of_business_and_unreachable_ones_are_not_leads(self):
        run = run_it(self.web(), sources={"osm": True, "search": False, "directory": False, "website": False, "instagram": False, "neshan": False}, require_contact=False)
        self.assertEqual(run.status, "completed", run.error)
        names = set(Lead.objects.filter(crawl_findings__mission=run.mission).values_list("business_name", flat=True))
        self.assertEqual(names, {"باشگاه بدنسازی آرمان", "Sparta Gym"})  # a spa and an equipment dealer are not gyms; «Sparta» is not «spa»
        self.assertFalse(CrawlCandidate.objects.filter(run=run, name="باشگاه دور از شهر").exists())  # 400 km away: never a candidate
        self.assertGreaterEqual(run.usage.get("out_of_area", 0), 1)
        self.assertTrue(CrawlLog.objects.filter(run=run, message__contains="شهرِ دیگری").exists())

    def test_a_tehran_gym_never_merges_into_an_isfahan_lead_through_a_shared_number(self):
        draft, _ = build_draft({"business_name": "باشگاه پرشین وولف", "city": "اصفهان", "phone": "09134716857"}, source_ref="x")
        draft.profile["address"] = "اصفهان، شاهین‌شهر، خیابان سلمان"
        isfahan = create_from_draft(draft, SourceInfo(provider="crawl_search", source_url="https://pw.ir/"))
        mission = make_mission(cities=["تهران"])
        run = missions.start_run(mission, None, dispatch=False)
        cand = CrawlCandidate.objects.create(
            run=run, name="باشگاه فیت جیم", name_core=textnorm.name_core("باشگاه فیت جیم"), city="تهران", address="تهران، تجریش، ولنجک", lat=35.80, lon=51.40,
            phones=["09134716857", "02122224444"], types=["gym"], sources=[{"source": "osm", "ref": "osm:node/9", "url": "https://www.openstreetmap.org/node/9"}],
            signals={"city_ev": ["تهران"], "city_src": "evidence"},
        )
        out = finalize.finalize_candidate(run, cand, run.spec, mission)
        self.assertEqual(out, "created")
        cand.refresh_from_db()
        self.assertNotEqual(cand.lead_id, isfahan.pk)
        self.assertEqual({c.value for c in cand.lead.contacts.all()}, {"02122224444"})  # the number it only shares with an Isfahan lead is not its own
        self.assertEqual({c.value for c in isfahan.contacts.all()}, {"09134716857"})

    def test_a_candidate_whose_only_contact_is_shared_with_another_city_is_skipped(self):
        draft, _ = build_draft({"business_name": "باشگاه پرشین وولف", "city": "اصفهان", "phone": "09134716857"}, source_ref="x")
        draft.profile["address"] = "اصفهان، شاهین‌شهر، خیابان سلمان"
        create_from_draft(draft, SourceInfo(provider="crawl_search", source_url="https://pw.ir/"))
        mission = make_mission(cities=["تهران"])
        run = missions.start_run(mission, None, dispatch=False)
        cand = CrawlCandidate.objects.create(
            run=run, name="باشگاه فیت جیم", name_core=textnorm.name_core("باشگاه فیت جیم"), city="تهران", address="تهران، تجریش", phones=["09134716857"], types=["gym"],
            sources=[{"source": "osm", "ref": "osm:node/9", "url": "https://www.openstreetmap.org/node/9"}], signals={"city_ev": ["تهران"], "city_src": "evidence"},
        )
        self.assertEqual(finalize.finalize_candidate(run, cand, run.spec, mission), "skipped:shared_contact")

    def test_the_activity_line_and_the_diary_use_persian_digits(self):
        run = run_it(self.web(), sources={"osm": True, "search": False, "directory": False, "website": False, "instagram": False, "neshan": False})
        line = LeadActivity.objects.filter(kind=ActivityKind.EXTRACTION).first().summary
        self.assertIsNone(re.search(r"[0-9]", line), line)
        for log in CrawlLog.objects.filter(run=run):
            self.assertIsNone(re.search(r"(?<![A-Za-z0-9_./=:@#%+-])[0-9]+(?![A-Za-z0-9_])", log.message), log.message)

    def test_a_contact_point_names_the_page_it_was_read_from(self):
        web = FakeWeb()
        web.add("nominatim.openstreetmap.org", "/search", NOMINATIM_TEHRAN)
        web.add("overpass-api.de", "/api/interpreter", overpass_json([osm_node(1, "باشگاه آرمان", 35.7001, 51.4001, leisure="fitness_centre", phone="02122223333", website="http://arman-gym.ir")]))
        web.add("arman-gym.ir", "/contact", CONTACT_OK.replace("faslesafar.com", "arman-gym.ir"), exact=True)
        web.add("arman-gym.ir", "/", "<html lang='fa'><body><nav><a href='/contact'>تماس با ما</a></nav><h1>باشگاه آرمان</h1></body></html>", exact=True)
        run_it(web)
        lead = Lead.objects.get(business_name="باشگاه آرمان")
        by_value = {c.value: c for c in lead.contacts.all()}
        self.assertTrue(by_value["02122223333"].source_url.startswith("https://www.openstreetmap.org/node/"))
        self.assertEqual(by_value["info@arman-gym.ir"].source_url, "http://arman-gym.ir/contact")  # the page as it was fetched (the map's website tag says http)
        self.assertIn("mailto", by_value["info@arman-gym.ir"].evidence)
        self.assertEqual(by_value["info@arman-gym.ir"].confidence, 90)


# --------------------------------------------------------------------------- the SMS draft


class SmsFitTests(Base, TestCase):
    def test_every_preset_sms_fits_the_allowed_parts_with_the_sender_block(self):
        for company in ("", "شرکت نمونهٔ ایکس‌ایگرگ"):
            settings_obj = GrowthSettings.load()
            settings_obj.sender_company = company
            settings_obj.save()
            budget = draft_service.sms_budget(settings_obj)
            for key, preset in presets.PRESETS.items():
                if preset.pitch is None:
                    continue
                body = draft_service.fit_sms(preset.pitch.brand, preset.pitch.sms, budget)
                final = body + "\n" + rendering.closing_block(settings_obj, Channel.SMS) if rendering.closing_block(settings_obj, Channel.SMS) else body
                if not company:
                    final += "\n" + "ا" * 18  # the line the owner has not written yet
                self.assertLessEqual(sms_channel.segments(final)["parts"], 2, (key, company, final))
                self.assertIn(preset.pitch.brand, body)

    def test_a_draft_for_the_chagher_mission_shows_no_length_warning(self):
        mission = make_mission(pitch={"brand": "چغر", "what": "چغر دستیارِ هوش مصنوعیِ مربی‌هاست.", "benefit": "وقتِ نوشتنِ برنامه را کم می‌کند.", "cta": "پاسخ بدهید.",
                                       "sms": presets.PRESETS["chagher_gyms_tehran"].pitch.sms})
        draft, _ = build_draft({"business_name": "باشگاه آرمان", "phone": "09121112222", "city": "تهران"}, source_ref="manual")
        lead = create_from_draft(draft, SourceInfo(provider="manual"))
        out = draft_service.generate(mission, [lead.pk], ["sms"])
        self.assertEqual(out["created"], 1)
        d = lead.crawl_drafts.get(channel="sms")
        self.assertLessEqual(sms_channel.segments(d.body)["parts"], 2, d.body)
        self.assertFalse([w for w in d.warnings if "بخش" in w], d.warnings)

    def test_the_length_warning_uses_persian_digits(self):
        mission = make_mission()
        warnings = draft_service._warnings({"avoid": ()}, Channel.SMS, "الف " * 200)
        self.assertTrue(warnings and not re.search(r"[0-9]", warnings[0]), warnings)
        self.assertIsNotNone(mission)


# --------------------------------------------------------------------------- the repair of old data


class RepairTests(Base, TestCase):
    def setUp(self):
        super().setUp()
        self.mission = make_mission(cities=["تهران"])

    def lead(self, name, *, city="تهران", address="", phones=(), emails=(), lat=None, lon=None, provider="crawl_osm", touched=False, website="",
             source_url="https://www.openstreetmap.org/node/1"):
        raw = {"business_name": name, "city": city, "phone": "; ".join(phones), "email": "; ".join(emails), "website": website}
        draft, _ = build_draft({k: v for k, v in raw.items() if v}, source_ref="crawl:1")
        if address:
            draft.profile["address"] = address
        lead = create_from_draft(draft, SourceInfo(provider=provider, source_url=source_url))
        if lat is not None:
            LeadInsight.objects.create(lead=lead, lat=lat, lon=lon)
        CrawlFinding.objects.create(mission=self.mission, lead=lead, score=50, level="medium")
        if touched:
            lead.notes.create(body="تماس گرفتم")
        return lead

    def test_a_dry_run_changes_nothing_and_apply_cleans(self):
        wrong = self.lead("باشگاه اصفهانی", address="اصفهان، چهارباغ", phones=["03132221111"])
        mixed = self.lead("باشگاه بدنسازی 7", address="اصفهان، سپاهان شهر", phones=["09195062507"], lat=35.7189, lon=51.4139)
        unreachable = self.lead("باشگاه بی‌راه", address="تهران، ونک")
        kept = self.lead("باشگاه خوب", address="تهران، ونک", phones=["09121112222"], city="Tehran")
        worked = self.lead("باشگاه اصفهانیِ کارشده", address="اصفهان، چهارباغ", phones=["03132223333"], touched=True)
        tag, _ = LeadTag.objects.get_or_create(name=repair.mission_tag(self.mission))
        worked.tags.add(tag)
        out = repair.run(apply=False)
        self.assertFalse(out["applied"])
        self.assertEqual(Lead.objects.count(), 5)
        self.assertEqual(out["report"]["deleted_other_city"], 1)
        out = repair.run(apply=True)
        self.assertTrue(out["applied"])
        self.assertFalse(Lead.objects.filter(pk__in=[wrong.pk, mixed.pk, unreachable.pk]).exists())
        kept.refresh_from_db()
        self.assertEqual(kept.city, "تهران")  # «Tehran» -> «تهران»
        worked.refresh_from_db()  # somebody worked on it: it stays, as a lead of its real city, no longer a result of the Tehran mission
        self.assertEqual(worked.city, "اصفهان")
        self.assertFalse(CrawlFinding.objects.filter(lead=worked).exists())
        self.assertFalse(worked.tags.filter(pk=tag.pk).exists())  # and it no longer wears the Tehran mission's tag

    def test_a_gym_of_a_directory_list_loses_the_trainer_tag_but_a_coach_keeps_it(self):
        tag, _ = LeadTag.objects.get_or_create(name=finalize.clean_tag(presets.get_type("personal_trainer").fa))
        gym = self.lead("باشگاه بدنسازی نمونه", address="تهران، ونک", phones=["02188776655"], provider="crawl_directory", source_url="https://badanfit.ir/gym.php?id=9")
        coach = self.lead("مربی بدنسازی نمونه", address="تهران، ونک", phones=["09121112233"], provider="crawl_directory", source_url="https://morabiyab.com/coach/1/")
        gym.tags.add(tag)
        coach.tags.add(tag)
        out = repair.run(apply=True)
        self.assertEqual(out["report"]["trainer_tag_removed_from_gym"], 1)
        self.assertFalse(gym.tags.filter(pk=tag.pk).exists())
        self.assertTrue(coach.tags.filter(pk=tag.pk).exists())

    def test_placeholder_social_pages_and_a_landline_of_another_province_are_removed(self):
        self.mission = make_mission(cities=["اصفهان"])
        lead = self.lead("باشگاه اصفهانی خوب", city="اصفهان", address="اصفهان، شاهین‌شهر، خیابان سلمان", phones=["03145264867", "02122424055", "09385824083"])
        for kind, value in (("instagram", "https://www.instagram.com/0/"), ("telegram", "https://t.me/test"), ("telegram", "https://t.me/09385824083")):
            ContactPoint.objects.create(lead=lead, kind=kind, value=value, normalized=value.rsplit("/", 2)[-2] if value.endswith("/") else value.rsplit("/", 1)[-1])
        out = repair.run(apply=True)
        kinds = {(c.kind, c.value) for c in lead.contacts.all()}
        self.assertIn(("phone", "03145264867"), kinds)
        self.assertIn(("phone", "09385824083"), kinds)  # a mobile number says nothing about the place
        self.assertNotIn(("phone", "02122424055"), kinds)  # a Tehran landline on an Isfahan address
        self.assertFalse([k for k in kinds if k[0] in ("instagram", "telegram")])
        self.assertGreaterEqual(out["report"]["contact_removed:تلفنِ ثابتِ استانِ دیگر"], 1)

    def test_the_activity_line_gets_persian_digits(self):
        lead = self.lead("باشگاه خوب", address="تهران، ونک", phones=["09121112222"])
        act = LeadActivity.objects.create(lead=lead, kind=ActivityKind.EXTRACTION, summary="مشتری‌یاب «چغر»: امتیازِ تناسب 59 (متوسط)")
        out = repair.run(apply=True)
        act.refresh_from_db()
        self.assertEqual(act.summary, "مشتری‌یاب «چغر»: امتیازِ تناسب ۵۹ (متوسط)")
        self.assertEqual(out["report"]["activity_digits_fixed"], 1)

    def test_filler_and_personal_contact_values_are_removed(self):
        lead = self.lead("باشگاه سفر", address="تهران، ونک", phones=["09133093934", "09123456789"], emails=["info@faslesafar.com", "m.dorri@gmail.com", "vanadiumdev.ir@gmail.com"],
                         website="https://faslesafar.com")
        repair.run(apply=True)
        values = {c.value for c in lead.contacts.all()}
        self.assertIn("09133093934", values)
        self.assertIn("info@faslesafar.com", values)
        self.assertNotIn("09123456789", values)
        self.assertNotIn("m.dorri@gmail.com", values)
        self.assertNotIn("vanadiumdev.ir@gmail.com", values)

    def test_a_lead_that_a_person_made_is_never_touched(self):
        draft, _ = build_draft({"business_name": "باشگاه دستی", "city": "Tehran", "phone": "09121112222"}, source_ref="manual")
        manual = create_from_draft(draft, SourceInfo(provider="manual"))
        CrawlFinding.objects.create(mission=self.mission, lead=manual, score=10, level="low")
        repair.run(apply=True)
        manual.refresh_from_db()
        self.assertEqual(manual.business_name, "باشگاه دستی")
        self.assertEqual(manual.city, "تهران")  # only the spelling of the city is normalised
        self.assertTrue(ContactPoint.objects.filter(lead=manual, value="09121112222").exists())

    def test_preset_missions_get_the_current_preset(self):
        m = missions.create_from_preset("chagher_coaches_instagram")
        m.spec = {**m.spec, "require_contact": False, "include_online": False}
        m.save()
        repair.run(apply=True)
        m.refresh_from_db()
        self.assertTrue(m.spec["require_contact"])
        self.assertTrue(m.spec["include_online"])
        self.assertEqual(m.spec["tag"], "چغر · اینستاگرام")
        self.assertIsNotNone(LeadReminder)
