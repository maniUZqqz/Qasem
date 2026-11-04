"""Reading a whole site through a mocked SafeFetcher: page choice, limits, robots, failures, shared platforms."""
import httpx
from django.test import SimpleTestCase

from apps.growth_engine.core.testing import NoNetworkMixin
from apps.growth_engine.extraction.services import crawler
from apps.growth_engine.extraction.services.parser import CONF, CONTACT_PAGE_LABEL, TICKET_LABEL
from apps.growth_engine.integrations import safe_http as sh

from .helpers import Site, fixture, golsorkh_site, keys, make_fetcher, one


def crawl(site, url="https://golsorkh.ir/", **kwargs):
    fetcher, clock = make_fetcher(site)
    return crawler.crawl_site(url, fetcher, **kwargs), site, clock


def nav_page(*anchors):
    links = "".join(f'<a href="{href}">{text}</a>' for href, text in anchors)
    return f"<html lang='fa'><head><title>x</title></head><body><nav>{links}</nav><p>خوش آمدید به فروشگاه ما، اینجا همه‌چیز پیدا می‌شود.</p></body></html>"


class PageSelectionTests(NoNetworkMixin, SimpleTestCase):
    def test_home_then_contact_about_support_in_that_order(self):
        result, site, _ = crawl(golsorkh_site())
        self.assertEqual(site.page_paths(), ["/", "/contact-us", "/about", "/support"])
        self.assertEqual((result.status, result.reason, result.pages_fetched), ("done", "", 4))
        kinds = [(e.kind, e.outcome) for e in result.logs]
        self.assertEqual(kinds, [("robots", "ok"), ("home", "ok"), ("contact", "ok"), ("about", "ok"), ("support", "ok")])
        self.assertEqual(result.robots_state, "ok")
        self.assertEqual(site.methods(), {"GET"})

    def test_merged_findings_keep_the_most_trusted_value_per_field(self):
        result, _, _ = crawl(golsorkh_site())
        f = result.findings
        self.assertEqual(keys(f, "phone"), ["02112345678", "02187654321", "09120001111", "09123456789"])
        self.assertEqual(one(f, "phone", "02112345678").confidence, 90)  # tel: link
        self.assertEqual(one(f, "phone", "09123456789").confidence, 75)  # seen on the contact and the about page
        self.assertEqual(one(f, "address").confidence, CONF["address_jsonld"])  # JSON-LD (90) beats <address> (80) and the label (75)
        self.assertEqual(one(f, "city").confidence, CONF["city_jsonld"])
        self.assertEqual(one(f, "business_name").confidence, CONF["name_jsonld"])
        self.assertEqual(one(f, "description").evidence, "meta description")
        # the form on the contact page and the two ticket links, each with its own URL
        forms = sorted((x.value, x.confidence) for x in f if x.field == "contact_form")
        self.assertEqual(forms, [("https://golsorkh.ir/contact-us", 85), ("https://golsorkh.ir/support", 70), ("https://golsorkh.ir/tickets/new", 70)])
        self.assertEqual(one(f, "contact_form", "https://golsorkh.ir/contact-us").source_url, "https://golsorkh.ir/contact-us")

    def test_never_more_than_the_page_budget_even_with_a_huge_menu(self):
        site = Site().robots("big.ir")
        menu = [(f"/contact-{i}", "تماس با ما") for i in range(6)] + [("/contact", "Contact"), ("/about", "About"), ("/about-us", "About us"), ("/support", "Support"), ("/help", "Help")]
        site.add("big.ir", "/", nav_page(*menu))
        for _, path in [(0, "/contact"), (0, "/about"), (0, "/about-us"), (0, "/support"), (0, "/help")] + [(0, f"/contact-{i}") for i in range(6)]:
            site.add("big.ir", path, fixture("contact_no_form.html"))
        result, site, _ = crawl(site, "https://big.ir/")
        self.assertLessEqual(len(site.page_paths()), 5)
        self.assertEqual(len(site.page_paths()), 5)
        self.assertEqual(site.page_paths()[0], "/")
        self.assertEqual(result.pages_fetched, 5)

    def test_the_budget_can_be_lowered(self):
        fetcher, _ = make_fetcher(golsorkh_site())
        result = crawler.crawl_site("https://golsorkh.ir/", fetcher, max_pages=2)
        self.assertEqual(result.pages_fetched, 2)

    def test_only_the_same_host_is_read(self):
        site = golsorkh_site()
        site.add("other-site.com", "/contact", fixture("contact_with_form.html"))
        _, site, _ = crawl(site)
        self.assertNotIn("other-site.com", [r.headers["host"] for r in site.requests])

    def test_english_menu_and_paths_and_the_budget_of_five(self):
        site = Site().robots("english-shop.com")
        site.page("english-shop.com", "/", "english_home.html")
        for path in ("/get-in-touch", "/contactus", "/company/about-us", "/help"):
            site.add("english-shop.com", path, fixture("contact_no_form.html"))
        site.add("english-shop.com", "/products/contact-lens-case", "must not be read")
        site.add("english-shop.com", "/account/login", "must not be read")
        result, site, _ = crawl(site, "https://english-shop.com/")
        self.assertEqual(site.page_paths(), ["/", "/get-in-touch", "/contactus", "/company/about-us", "/help"])
        self.assertNotIn("/products/contact-lens-case", site.paths())

    def test_guessing_common_paths_only_when_the_home_page_links_nothing(self):
        site = Site().robots("bare.ir")
        site.add("bare.ir", "/", nav_page(("/shop", "محصولات"), ("/cart", "سبد")))
        site.page("bare.ir", "/contact", "contact_with_form.html")
        result, site, _ = crawl(site, "https://bare.ir/")
        self.assertEqual(site.page_paths(), ["/", "/contact", "/contact-us", "/contactus", "/about"])
        guesses = [e for e in result.logs if e.kind == "guess"]
        self.assertEqual([(e.status, e.outcome) for e in guesses], [(200, "ok"), (404, "http_error"), (404, "http_error"), (404, "http_error")])
        self.assertEqual(one(result.findings, "contact_form").value, "https://bare.ir/contact")
        # ... and a home page that links to a contact page is not guessed at
        site2 = golsorkh_site()
        _, site2, _ = crawl(site2)
        self.assertNotIn("/contactus", site2.paths())

    def test_contact_page_without_form_counts_55_only_when_nothing_better_exists(self):
        site = Site().robots("nofrm.ir")
        site.add("nofrm.ir", "/", nav_page(("/contact", "تماس با ما")))
        site.page("nofrm.ir", "/contact", "contact_no_form.html")
        result, _, _ = crawl(site, "https://nofrm.ir/")
        form = one(result.findings, "contact_form")
        self.assertEqual((form.value, form.confidence, form.label), ("https://nofrm.ir/contact", CONF["contact_page_no_form"], CONTACT_PAGE_LABEL))
        # a ticket link on the same site is better evidence: the bare page is dropped
        site2 = Site().robots("nofrm.ir")
        site2.add("nofrm.ir", "/", nav_page(("/contact", "تماس با ما"), ("/support", "پشتیبانی")))
        site2.page("nofrm.ir", "/contact", "contact_no_form.html")
        site2.add("nofrm.ir", "/support", "<html><body>" + "پشتیبانی " * 20 + "</body></html>")
        result2, _, _ = crawl(site2, "https://nofrm.ir/")
        self.assertEqual([(f.value, f.label) for f in result2.findings if f.field == "contact_form"], [("https://nofrm.ir/support", TICKET_LABEL)])

    def test_shared_platform_is_read_as_one_page_only(self):
        site = Site().robots("linktr.ee")
        site.page("linktr.ee", "/golsorkhshop", "linktree.html")
        site.add("linktr.ee", "/contact", "must not be read")
        result, site, _ = crawl(site, "https://linktr.ee/golsorkhshop")
        self.assertEqual(site.page_paths(), ["/golsorkhshop"])
        self.assertEqual(one(result.findings, "instagram").key, "golsorkhshop")
        self.assertEqual(one(result.findings, "whatsapp").value, "09351112233")

    def test_heartbeat_per_page_and_stop_request(self):
        beats = []
        fetcher, _ = make_fetcher(golsorkh_site())
        crawler.crawl_site("https://golsorkh.ir/", fetcher, heartbeat=lambda: beats.append(1))
        self.assertEqual(len(beats), 4)
        site = golsorkh_site()
        fetcher, _ = make_fetcher(site)
        result = crawler.crawl_site("https://golsorkh.ir/", fetcher, should_stop=lambda: True)
        self.assertTrue(result.aborted)
        self.assertEqual(site.page_paths(), ["/"])


class RobotsTests(NoNetworkMixin, SimpleTestCase):
    def test_a_site_that_forbids_everything_is_not_fetched_and_the_refusal_is_logged(self):
        site = golsorkh_site(robots=False).robots("golsorkh.ir", "User-agent: *\nDisallow: /\n")
        result, site, _ = crawl(site)
        self.assertEqual((result.status, result.reason, result.findings), ("failed", "robots_blocked", []))
        self.assertEqual(site.page_paths(), [], "not one page may be requested")
        self.assertEqual(site.paths(), ["/robots.txt"])
        self.assertEqual([(e.kind, e.outcome) for e in result.logs], [("robots", "ok"), ("home", "robots_blocked")])
        self.assertEqual(result.robots_state, "ok")

    def test_our_own_token_is_obeyed(self):
        site = golsorkh_site(robots=False).robots("golsorkh.ir", "User-agent: NMarketingBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
        result, site, _ = crawl(site)
        self.assertEqual(result.reason, "robots_blocked")
        self.assertEqual(site.page_paths(), [])

    def test_one_forbidden_page_is_skipped_the_rest_is_read(self):
        site = golsorkh_site(robots=False).robots("golsorkh.ir", "User-agent: *\nDisallow: /contact-us\n")
        result, site, _ = crawl(site)
        self.assertEqual((result.status, result.reason), ("done", ""))
        self.assertNotIn("/contact-us", site.paths())
        refused = [e for e in result.logs if e.outcome == "robots_blocked"]
        self.assertEqual([(e.kind, e.url) for e in refused], [("contact", "https://golsorkh.ir/contact-us")])
        self.assertEqual(site.page_paths(), ["/", "/about", "/support"])

    def test_robots_that_cannot_be_read_stops_the_run_for_safety(self):
        site = golsorkh_site(robots=False).robots("golsorkh.ir", "oops", status=500)
        result, site, _ = crawl(site)
        self.assertEqual((result.status, result.reason, result.robots_state), ("failed", "robots_unavailable", "unavailable"))
        self.assertEqual(site.page_paths(), [])

    def test_robots_403_means_no(self):
        site = golsorkh_site(robots=False).robots("golsorkh.ir", "", status=403)
        result, _, _ = crawl(site)
        self.assertEqual((result.reason, result.robots_state), ("robots_blocked", "disallow_all"))

    def test_no_robots_file_is_logged_as_such(self):
        result, _, _ = crawl(golsorkh_site(robots=False))
        self.assertEqual(result.robots_state, "none")
        self.assertEqual(result.logs[0].kind, "robots")
        self.assertIn("ندارد", result.logs[0].note)


class FailureTests(NoNetworkMixin, SimpleTestCase):
    def test_a_timeout_on_one_page_is_logged_and_the_rest_continues(self):
        site = golsorkh_site().add("golsorkh.ir", "/contact-us", error=httpx.ReadTimeout("slow"))
        result, site, _ = crawl(site)
        self.assertEqual((result.status, result.reason), ("done", ""))
        timed_out = [e for e in result.logs if e.outcome == "timeout"]
        self.assertEqual([(e.kind, e.status) for e in timed_out], [("contact", 0)])
        self.assertEqual(site.paths().count("/contact-us"), 3)  # one try and two retries, GET only
        self.assertTrue(all(len(e.note) > 0 for e in timed_out))

    def test_home_page_failures_are_a_failed_run_with_the_reason_logged(self):
        cases = [
            (dict(error=httpx.ConnectError("refused")), "connect_error", 0),
            (dict(body="gone", status=404), "http_error", 404),
            (dict(body=b"%PDF", ctype="application/pdf"), "non_html", 200),
            (dict(body="", status=301, headers={"location": "https://another-company.com/"}), "redirect_offsite", 301),
        ]
        for kwargs, outcome, status in cases:
            with self.subTest(outcome=outcome):
                site = Site().robots("golsorkh.ir").add("golsorkh.ir", "/", **kwargs)
                result, _, _ = crawl(site)
                self.assertEqual((result.status, result.reason), ("failed", "fetch_failed"))
                home = [e for e in result.logs if e.kind == "home"][0]
                self.assertEqual((home.outcome, home.status), (outcome, status))
                self.assertTrue(home.note)

    def test_a_challenge_page_is_not_content(self):
        for status in (200, 403, 503):
            with self.subTest(status=status):
                site = Site().robots("shop.example").add("shop.example", "/", fixture("cloudflare_challenge.html"), status=status)
                result, _, _ = crawl(site, "https://shop.example/")
                self.assertEqual((result.status, result.reason, result.findings), ("failed", "fetch_failed", []))
                self.assertIn("چالش", [e for e in result.logs if e.kind == "home"][0].note)

    def test_a_javascript_shell_has_no_readable_pages(self):
        site = Site().robots("spa.ir").page("spa.ir", "/", "spa_shell.html")
        result, site, _ = crawl(site, "https://spa.ir/")
        self.assertEqual((result.status, result.reason), ("failed", "no_pages"))
        self.assertEqual(site.page_paths(), ["/"])
        self.assertIn("جاوااسکریپت", [e for e in result.logs if e.kind == "home"][0].note)

    def test_a_bad_website_value_is_logged_not_raised(self):
        for bad in ["not a url", "javascript:alert(1)", "ftp://x.ir"]:
            with self.subTest(bad=bad):
                result, site, _ = crawl(Site(), bad)
                self.assertEqual((result.status, result.reason), ("failed", "fetch_failed"))
                self.assertEqual((result.logs[0].kind, result.logs[0].outcome), ("home", "bad_url"))
                self.assertEqual(site.requests, [])

    def test_a_website_that_points_inside_the_network_is_refused_before_any_request(self):
        site = golsorkh_site()
        fetcher, _ = make_fetcher(site, resolver=lambda host, port: ["10.0.0.7"])
        result = crawler.crawl_site("https://golsorkh.ir/", fetcher)
        self.assertEqual((result.status, result.reason), ("failed", "fetch_failed"))
        self.assertEqual(site.requests, [])
        self.assertEqual([(e.kind, e.outcome) for e in result.logs], [("home", sh.SSRF_BLOCKED)])

    def test_only_get_requests_are_ever_issued(self):
        # the fake web asserts the method of every request it receives (see helpers.Site.__call__)
        small = Site().robots("x.ir").add("x.ir", "/", nav_page(("/contact", "تماس با ما"))).page("x.ir", "/contact", "contact_with_form.html")
        for site, url in ((golsorkh_site(), "https://golsorkh.ir/"), (small, "https://x.ir/")):
            fetcher, _ = make_fetcher(site)
            result = crawler.crawl_site(url, fetcher)
            self.assertEqual(result.status, "done")
            self.assertEqual(site.methods(), {"GET"})
