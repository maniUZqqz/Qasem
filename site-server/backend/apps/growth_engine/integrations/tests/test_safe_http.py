"""SafeFetcher against mocked HTTP only (httpx.MockTransport) - nothing here touches the network."""
import httpx
from django.test import SimpleTestCase, override_settings

from apps.growth_engine.core.testing import NoNetworkMixin
from apps.growth_engine.integrations import safe_http as sh

PUBLIC = "93.184.216.34"


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class Site:
    """A tiny fake web: routes by (Host header, path); records every request it sees."""

    def __init__(self):
        self.routes: dict[tuple[str, str], object] = {}
        self.requests: list[httpx.Request] = []

    def add(self, host, path, body="", status=200, ctype="text/html; charset=utf-8", headers=None, repeat=None):
        self.routes[(host, path)] = {"body": body, "status": status, "ctype": ctype, "headers": headers or {}, "seq": repeat}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get((request.headers["host"], request.url.path))
        if route is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        if route["seq"]:
            route = route["seq"].pop(0) if len(route["seq"]) > 1 else route["seq"][0]
        headers = {"content-type": route["ctype"], **route["headers"]}
        body = route["body"]
        return httpx.Response(route["status"], content=body.encode("utf-8") if isinstance(body, str) else body, headers=headers)

    def paths(self, method=None):
        return [r.url.path for r in self.requests if method in (None, r.method)]


def make(site, resolver=None, **kwargs):
    clock = FakeClock()
    throttle = sh.DomainThrottle(clock=clock.time, sleep=clock.sleep)
    fetcher = sh.SafeFetcher(
        resolver=resolver or (lambda host, port: [PUBLIC]), transport=httpx.MockTransport(site), throttle=throttle, sleep=clock.sleep, **kwargs
    )
    return fetcher, clock


class FetchBasicsTests(NoNetworkMixin, SimpleTestCase):
    def test_get_returns_html_and_sends_a_clear_user_agent_and_the_real_host(self):
        site = Site()
        site.add("shop.ir", "/robots.txt", "User-agent: *\nDisallow: /admin\n", ctype="text/plain")
        site.add("shop.ir", "/", "<html><body>سلام</body></html>")
        fetcher, _ = make(site)
        result = fetcher.get_page("https://shop.ir/")
        self.assertTrue(result.ok, result.outcome)
        self.assertIn("سلام", result.text)
        page = [r for r in site.requests if r.url.path == "/"][0]
        self.assertIn("NMarketingBot", page.headers["user-agent"])
        self.assertEqual(page.headers["host"], "shop.ir")
        self.assertEqual(page.url.host, PUBLIC, "the request goes to the address that was checked, not to the name")

    def test_only_get_is_used_for_pages_and_robots(self):
        site = Site()
        site.add("shop.ir", "/", "<html></html>")
        fetcher, _ = make(site)
        fetcher.get_page("https://shop.ir/")
        self.assertEqual({r.method for r in site.requests}, {"GET"})

    def test_charset_from_header_and_meta(self):
        site = Site()
        site.add("a.ir", "/", "<html>سلام</html>".encode("cp1256"), ctype="text/html; charset=windows-1256")
        site.add("b.ir", "/", ('<html><head><meta charset="windows-1256"></head>' + "سلام").encode("cp1256"), ctype="text/html")
        fetcher, _ = make(site)
        self.assertIn("سلام", fetcher.get_page("http://a.ir/").text)
        self.assertIn("سلام", fetcher.get_page("http://b.ir/").text)

    def test_non_html_is_not_read(self):
        site = Site()
        site.add("shop.ir", "/file", b"%PDF-1.4", ctype="application/pdf")
        fetcher, _ = make(site)
        result = fetcher.get_page("https://shop.ir/file")
        self.assertEqual((result.outcome, result.text), (sh.NON_HTML, ""))

    @override_settings(GROWTH_ENGINE={"HTTP_MAX_BYTES": 1000})
    def test_size_cap(self):
        site = Site()
        site.add("shop.ir", "/big", "<html>" + "x" * 5000 + "</html>")
        fetcher, _ = make(site)
        result = fetcher.get_page("https://shop.ir/big")
        self.assertEqual((result.outcome, result.bytes_read), (sh.TOO_LARGE, 1000))

    def test_http_error_status_is_reported_not_raised(self):
        site = Site()
        site.add("shop.ir", "/gone", "no", status=404)
        fetcher, _ = make(site)
        result = fetcher.get_page("https://shop.ir/gone")
        self.assertEqual((result.outcome, result.status), (sh.HTTP_ERROR, 404))


class SsrfTests(NoNetworkMixin, SimpleTestCase):
    def fetch(self, url, resolver=None):
        site = Site()
        site.add("evil.test", "/", "<html>secret</html>")
        fetcher, _ = make(site, resolver=resolver)
        return fetcher.get_page(url), site

    def test_private_and_special_addresses_are_refused(self):
        for address in ["127.0.0.1", "10.1.2.3", "172.16.5.5", "192.168.0.9", "169.254.169.254", "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1"]:
            with self.subTest(address=address):
                result, site = self.fetch("http://evil.test/", resolver=lambda h, p, a=address: [a])
                self.assertEqual(result.outcome, sh.SSRF_BLOCKED)
                self.assertEqual(site.requests, [], "nothing may be sent")

    def test_one_bad_address_among_good_ones_is_enough_to_refuse(self):
        result, _ = self.fetch("http://evil.test/", resolver=lambda h, p: [PUBLIC, "127.0.0.1"])
        self.assertEqual(result.outcome, sh.SSRF_BLOCKED)

    def test_ip_literals_localhost_and_odd_ports_and_schemes(self):
        for url, outcome in [
            ("http://127.0.0.1/", sh.SSRF_BLOCKED), ("http://[::1]/", sh.SSRF_BLOCKED), ("http://169.254.169.254/latest/meta-data", sh.SSRF_BLOCKED),
            ("http://10.0.0.5:8080/api/", sh.SSRF_BLOCKED), ("http://10.0.0.5:8041/api/", sh.BLOCKED_PORT), ("http://example.com:22/", sh.BLOCKED_PORT), ("http://example.com:6379/", sh.BLOCKED_PORT),
            ("ftp://example.com/", sh.BAD_URL), ("file:///etc/passwd", sh.BAD_URL), ("javascript:alert(1)", sh.BAD_URL), ("http:///x", sh.BAD_URL),
        ]:
            with self.subTest(url=url):
                result, site = self.fetch(url)
                self.assertEqual(result.outcome, outcome)
                self.assertEqual(site.requests, [])

    def test_a_public_ip_literal_is_allowed(self):
        site = Site()
        site.add(PUBLIC, "/", "<html>ok</html>")
        fetcher, _ = make(site)
        self.assertTrue(fetcher.get_page(f"http://{PUBLIC}/").ok)

    def test_redirect_into_the_internal_network_is_refused_at_the_hop(self):
        site = Site()
        site.add("shop.ir", "/", "", status=302, headers={"location": "http://shop.ir/next"})
        site.add("shop.ir", "/next", "<html>x</html>")
        answers = {"shop.ir": [PUBLIC]}
        calls = []

        def resolver(host, port):
            calls.append(host)
            return answers["shop.ir"] if len(calls) < 3 else ["127.0.0.1"]  # robots, first page ok; the second hop resolves badly

        fetcher, _ = make(site, resolver=resolver)
        result = fetcher.get_page("http://shop.ir/")
        self.assertEqual(result.outcome, sh.SSRF_BLOCKED)

    def test_dns_rebinding_cannot_change_where_the_request_goes(self):
        # the name is resolved once per hop and the request is addressed to that very IP
        site = Site()
        site.add("shop.ir", "/", "<html>x</html>")
        seen = []

        def resolver(host, port):
            seen.append(host)
            return [PUBLIC]

        fetcher, _ = make(site, resolver=resolver)
        fetcher.get_page("http://shop.ir/")
        self.assertTrue(all(r.url.host == PUBLIC for r in site.requests))

    def test_dns_failure(self):
        def resolver(host, port):
            raise OSError("nxdomain")

        result, _ = self.fetch("http://nonexistent.test/", resolver=resolver)
        self.assertEqual(result.outcome, sh.DNS_ERROR)

    @override_settings(GROWTH_ENGINE={"HTTP_ALLOW_PRIVATE": True, "HTTP_ALLOWED_PORTS": (80, 18080)})
    def test_private_targets_work_only_when_explicitly_allowed(self):
        site = Site()
        site.add("127.0.0.1:18080", "/", "<html>local</html>")
        fetcher, _ = make(site, respect_robots=False)
        self.assertTrue(fetcher.get_page("http://127.0.0.1:18080/").ok)


class RobotsTests(NoNetworkMixin, SimpleTestCase):
    def site_with(self, robots, status=200):
        site = Site()
        site.add("shop.ir", "/robots.txt", robots, status=status, ctype="text/plain")
        site.add("shop.ir", "/", "<html>home</html>")
        site.add("shop.ir", "/contact", "<html>contact</html>")
        site.add("shop.ir", "/private/page", "<html>x</html>")
        return site

    def test_disallowed_path_is_not_fetched_at_all(self):
        site = self.site_with("User-agent: *\nDisallow: /private\n")
        fetcher, _ = make(site)
        blocked = fetcher.get_page("https://shop.ir/private/page")
        self.assertEqual(blocked.outcome, sh.ROBOTS_BLOCKED)
        self.assertNotIn("/private/page", site.paths())
        self.assertTrue(fetcher.get_page("https://shop.ir/contact").ok)

    def test_our_own_token_overrides_the_wildcard(self):
        site = self.site_with("User-agent: NMarketingBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
        fetcher, _ = make(site)
        self.assertEqual(fetcher.get_page("https://shop.ir/").outcome, sh.ROBOTS_BLOCKED)

    def test_disallow_everything(self):
        site = self.site_with("User-agent: *\nDisallow: /\n")
        fetcher, _ = make(site)
        self.assertEqual(fetcher.get_page("https://shop.ir/contact").outcome, sh.ROBOTS_BLOCKED)

    def test_missing_robots_means_allowed(self):
        site = Site()
        site.add("shop.ir", "/", "<html>home</html>")
        fetcher, _ = make(site)
        self.assertTrue(fetcher.get_page("https://shop.ir/").ok)

    def test_robots_401_403_means_disallowed(self):
        for status in (401, 403):
            with self.subTest(status=status):
                fetcher, _ = make(self.site_with("", status=status))
                self.assertEqual(fetcher.get_page("https://shop.ir/").outcome, sh.ROBOTS_BLOCKED)

    def test_robots_5xx_or_unreachable_is_treated_as_disallowed_not_guessed(self):
        fetcher, _ = make(self.site_with("oops", status=500))
        self.assertEqual(fetcher.get_page("https://shop.ir/").outcome, sh.ROBOTS_UNAVAILABLE)

        def boom(request):
            raise httpx.ConnectTimeout("slow")

        fetcher = sh.SafeFetcher(resolver=lambda h, p: [PUBLIC], transport=httpx.MockTransport(boom), throttle=sh.DomainThrottle(sleep=lambda s: None), sleep=lambda s: None)
        self.assertEqual(fetcher.get_page("https://shop.ir/").outcome, sh.ROBOTS_UNAVAILABLE)

    def test_robots_is_fetched_once_per_host(self):
        site = self.site_with("User-agent: *\nDisallow: /nothing\n")
        fetcher, _ = make(site)
        fetcher.get_page("https://shop.ir/")
        fetcher.get_page("https://shop.ir/contact")
        self.assertEqual(site.paths().count("/robots.txt"), 1)

    def test_robots_can_be_switched_off_only_explicitly(self):
        site = self.site_with("User-agent: *\nDisallow: /\n")
        fetcher, _ = make(site, respect_robots=False)
        self.assertTrue(fetcher.get_page("https://shop.ir/").ok)
        self.assertNotIn("/robots.txt", site.paths())


class ThrottleAndRetryTests(NoNetworkMixin, SimpleTestCase):
    def test_same_host_is_spaced_other_hosts_are_not(self):
        site = Site()
        for host in ("a.ir", "b.ir"):
            site.add(host, "/", "<html>x</html>")
            site.add(host, "/x", "<html>x</html>")
        fetcher, clock = make(site, respect_robots=False)
        fetcher.get_page("http://a.ir/")
        self.assertEqual(clock.slept, [])
        fetcher.get_page("http://a.ir/x")
        self.assertEqual(clock.slept, [2.0])
        fetcher.get_page("http://b.ir/")
        self.assertEqual(clock.slept, [2.0], "a different host is independent")

    def test_threads_reserve_their_slots_in_order(self):
        clock = FakeClock()
        throttle = sh.DomainThrottle(clock=clock.time, sleep=lambda s: None)
        waits = [throttle.wait("a.ir", 2.0) for _ in range(3)]
        self.assertEqual(waits, [0.0, 2.0, 4.0])

    def test_transient_errors_are_retried_with_backoff_then_succeed(self):
        site = Site()
        site.add("shop.ir", "/", repeat=[{"body": "busy", "status": 503, "ctype": "text/html", "headers": {}}, {"body": "<html>ok</html>", "status": 200, "ctype": "text/html", "headers": {}}])
        fetcher, clock = make(site, respect_robots=False)
        result = fetcher.get_page("https://shop.ir/")
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertIn(1.0, clock.slept)

    def test_retry_after_is_honoured_but_capped(self):
        site = Site()
        site.add("shop.ir", "/", repeat=[
            {"body": "", "status": 429, "ctype": "text/html", "headers": {"retry-after": "999"}},
            {"body": "<html>ok</html>", "status": 200, "ctype": "text/html", "headers": {}},
        ])
        fetcher, clock = make(site, respect_robots=False)
        self.assertTrue(fetcher.get_page("https://shop.ir/").ok)
        self.assertIn(10.0, clock.slept)
        self.assertNotIn(999.0, clock.slept)

    def test_client_errors_are_not_retried(self):
        site = Site()
        site.add("shop.ir", "/x", "no", status=404)
        site.add("shop.ir", "/y", "no", status=403)
        fetcher, _ = make(site, respect_robots=False)
        fetcher.get_page("https://shop.ir/x")
        fetcher.get_page("https://shop.ir/y")
        self.assertEqual(site.paths(), ["/x", "/y"])

    def test_timeouts_give_up_after_the_configured_retries(self):
        calls = []

        def slow(request):
            calls.append(1)
            raise httpx.ReadTimeout("slow")

        fetcher = sh.SafeFetcher(resolver=lambda h, p: [PUBLIC], transport=httpx.MockTransport(slow), throttle=sh.DomainThrottle(sleep=lambda s: None), sleep=lambda s: None, respect_robots=False)
        result = fetcher.get_page("https://shop.ir/")
        self.assertEqual(result.outcome, sh.TIMEOUT)
        self.assertEqual(len(calls), 3)  # 1 try + 2 retries

    def test_tls_errors_are_not_retried_and_never_downgraded(self):
        calls = []

        def bad_cert(request):
            calls.append(request.url.scheme)
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

        fetcher = sh.SafeFetcher(resolver=lambda h, p: [PUBLIC], transport=httpx.MockTransport(bad_cert), throttle=sh.DomainThrottle(sleep=lambda s: None), sleep=lambda s: None, respect_robots=False)
        result = fetcher.get_page("https://shop.ir/")
        self.assertEqual(result.outcome, sh.TLS_ERROR)
        self.assertEqual(calls, ["https"], "one attempt, no retry, and never a fallback to plain http")


class RedirectTests(NoNetworkMixin, SimpleTestCase):
    def test_same_site_redirects_are_followed(self):
        site = Site()
        site.add("shop.ir", "/", "", status=301, headers={"location": "https://www.shop.ir/fa/"})
        site.add("www.shop.ir", "/fa/", "<html>fa</html>")
        fetcher, _ = make(site, respect_robots=False)
        result = fetcher.get_page("http://shop.ir/")
        self.assertTrue(result.ok)
        self.assertEqual((result.final_url, result.redirects), ("https://www.shop.ir/fa/", ["https://www.shop.ir/fa/"]))

    def test_offsite_redirect_is_not_followed(self):
        site = Site()
        site.add("shop.ir", "/", "", status=302, headers={"location": "https://other.com/"})
        site.add("other.com", "/", "<html>other</html>")
        fetcher, _ = make(site, respect_robots=False)
        result = fetcher.get_page("http://shop.ir/")
        self.assertEqual(result.outcome, sh.REDIRECT_OFFSITE)
        self.assertNotIn("other.com", [r.headers["host"] for r in site.requests])

    def test_redirect_loop_is_cut(self):
        site = Site()
        site.add("shop.ir", "/a", "", status=302, headers={"location": "/b"})
        site.add("shop.ir", "/b", "", status=302, headers={"location": "/a"})
        fetcher, _ = make(site, respect_robots=False)
        self.assertEqual(fetcher.get_page("http://shop.ir/a").outcome, sh.REDIRECT_LOOP)

    def test_robots_is_checked_on_every_hop(self):
        site = Site()
        site.add("shop.ir", "/robots.txt", "User-agent: *\nDisallow: /private\n", ctype="text/plain")
        site.add("shop.ir", "/", "", status=302, headers={"location": "/private/x"})
        site.add("shop.ir", "/private/x", "<html>secret</html>")
        fetcher, _ = make(site)
        self.assertEqual(fetcher.get_page("http://shop.ir/").outcome, sh.ROBOTS_BLOCKED)
        self.assertNotIn("/private/x", site.paths())


class PostFormTests(NoNetworkMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.site = Site()
        self.site.add("shop.ir", "/robots.txt", "User-agent: *\nDisallow: /secret\n", ctype="text/plain")

    def test_post_is_urlencoded_once_with_the_referer(self):
        self.site.add("shop.ir", "/contact", "<html>thanks</html>")
        fetcher, _ = make(self.site)
        result = fetcher.post_form("https://shop.ir/contact", [("name", "علی"), ("msg", "سلام"), ("tag", "a"), ("tag", "b")], referer="https://shop.ir/contact-page")
        posts = [r for r in self.site.requests if r.method == "POST"]
        self.assertEqual(len(posts), 1)
        body = posts[0].content.decode()
        self.assertIn("name=%D8%B9%D9%84%DB%8C", body)
        self.assertEqual(body.count("tag="), 2)
        self.assertEqual(posts[0].headers["content-type"], "application/x-www-form-urlencoded")
        self.assertEqual(posts[0].headers["referer"], "https://shop.ir/contact-page")
        self.assertEqual((result.status, result.outcome), (200, sh.OK))
        self.assertIn("thanks", result.text)

    def test_multipart_when_the_form_asks_for_it(self):
        self.site.add("shop.ir", "/contact", "<html>thanks</html>")
        fetcher, _ = make(self.site)
        fetcher.post_form("https://shop.ir/contact", [("name", "x"), ("msg", "y")], multipart=True)
        post = [r for r in self.site.requests if r.method == "POST"][0]
        self.assertTrue(post.headers["content-type"].startswith("multipart/form-data"))

    def test_a_failure_is_never_retried(self):
        self.site.add("shop.ir", "/contact", "boom", status=503)
        fetcher, clock = make(self.site)
        result = fetcher.post_form("https://shop.ir/contact", [("a", "b")])
        self.assertEqual((result.status, result.outcome, result.attempts), (503, sh.HTTP_ERROR, 1))
        self.assertEqual(len([r for r in self.site.requests if r.method == "POST"]), 1)

    def test_a_timeout_is_not_repeated_either(self):
        posts = []

        def handler(request):
            if request.method == "POST":
                posts.append(1)
                raise httpx.ReadTimeout("slow")
            return httpx.Response(200, text="")

        fetcher = sh.SafeFetcher(resolver=lambda h, p: [PUBLIC], transport=httpx.MockTransport(handler), throttle=sh.DomainThrottle(sleep=lambda s: None), sleep=lambda s: None)
        self.assertEqual(fetcher.post_form("https://shop.ir/c", [("a", "b")]).outcome, sh.TIMEOUT)
        self.assertEqual(len(posts), 1)

    def test_robots_disallowed_action_is_not_posted_to(self):
        self.site.add("shop.ir", "/secret/form", "<html></html>")
        fetcher, _ = make(self.site)
        result = fetcher.post_form("https://shop.ir/secret/form", [("a", "b")])
        self.assertEqual(result.outcome, sh.ROBOTS_BLOCKED)
        self.assertEqual([r for r in self.site.requests if r.method == "POST"], [])

    def test_post_to_an_internal_address_is_refused(self):
        fetcher, _ = make(self.site)
        self.assertEqual(fetcher.post_form("http://127.0.0.1/contact", [("a", "b")]).outcome, sh.SSRF_BLOCKED)

    def test_a_redirect_after_post_is_read_with_one_get_not_re_posted(self):
        self.site.add("shop.ir", "/contact", "", status=302, headers={"location": "/thanks"})
        self.site.add("shop.ir", "/thanks", "<html>با تشکر، پیام شما ارسال شد</html>")
        fetcher, _ = make(self.site)
        result = fetcher.post_form("https://shop.ir/contact", [("a", "b")])
        self.assertEqual(result.status, 302)
        self.assertIn("ارسال شد", result.text)
        self.assertEqual([r.method for r in self.site.requests if r.url.path in ("/contact", "/thanks")], ["POST", "GET"])
        self.assertTrue(result.final_url.endswith("/thanks"))

    def test_offsite_redirect_after_post_is_not_followed(self):
        self.site.add("shop.ir", "/contact", "", status=302, headers={"location": "https://payment.example.com/x"})
        fetcher, _ = make(self.site)
        result = fetcher.post_form("https://shop.ir/contact", [("a", "b")])
        self.assertEqual((result.status, result.text), (302, ""))
        self.assertEqual(len(self.site.requests), 2)  # robots.txt + the POST, nothing else
