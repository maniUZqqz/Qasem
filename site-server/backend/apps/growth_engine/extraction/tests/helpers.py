"""Shared helpers of the extraction tests: HTML fixtures, a fake web (httpx.MockTransport) and a mocked SafeFetcher."""
from pathlib import Path

import httpx

from apps.growth_engine.integrations import safe_http as sh

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC = "93.184.216.34"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def by_field(findings, field_name):
    return [f for f in findings if f.field == field_name]


def one(findings, field_name, key=None):
    """The single finding of ``field_name`` (optionally with this key); fails loudly if there is not exactly one."""
    found = [f for f in findings if f.field == field_name and (key is None or f.key == key)]
    assert len(found) == 1, f"expected one {field_name} {key or ''}, got {[(f.field, f.key, f.confidence) for f in found]}"
    return found[0]


def keys(findings, field_name):
    return sorted(f.key or f.value for f in findings if f.field == field_name)


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
    """A tiny fake web. Routes are ``(host, path)``; the request's Host header decides the host (the fetcher
    addresses the checked IP, not the name). Records every request; refuses anything but GET."""

    def __init__(self):
        self.routes: dict[tuple[str, str], dict] = {}
        self.requests: list[httpx.Request] = []

    def add(self, host, path, body="", status=200, ctype="text/html; charset=utf-8", headers=None, error=None):
        self.routes[(host, path)] = {"body": body, "status": status, "ctype": ctype, "headers": headers or {}, "error": error}
        return self

    def page(self, host, path, fixture_name, **kwargs):
        return self.add(host, path, fixture(fixture_name), **kwargs)

    def robots(self, host, text="User-agent: *\nAllow: /\n", status=200):
        return self.add(host, "/robots.txt", text, status=status, ctype="text/plain")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET", f"extraction must only GET, got {request.method} {request.url}"
        route = self.routes.get((request.headers["host"], request.url.path))
        if route is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        if route["error"]:
            raise route["error"]
        headers = {"content-type": route["ctype"], **route["headers"]}
        body = route["body"]
        return httpx.Response(route["status"], content=body.encode("utf-8") if isinstance(body, str) else body, headers=headers)

    def paths(self):
        return [r.url.path for r in self.requests]

    def page_paths(self):
        return [p for p in self.paths() if p != "/robots.txt"]

    def methods(self):
        return {r.method for r in self.requests}


def make_fetcher(site, resolver=None, **kwargs):
    clock = FakeClock()
    throttle = sh.DomainThrottle(clock=clock.time, sleep=clock.sleep)
    fetcher = sh.SafeFetcher(
        resolver=resolver or (lambda host, port: [PUBLIC]), transport=httpx.MockTransport(site), throttle=throttle, sleep=clock.sleep, **kwargs
    )
    return fetcher, clock


def add_shop(site, host, robots=True, with_support=True, with_about=True):
    """The fixture shop on ``host``: home + contact page with a form + support + about."""
    if robots:
        site.robots(host)
    site.page(host, "/", "home_shop.html")
    site.page(host, "/contact-us", "contact_with_form.html")
    if with_support:
        site.page(host, "/support", "support_page.html")
    if with_about:
        site.page(host, "/about", "about_page.html")
    return site


def golsorkh_site(robots=True, with_support=True, with_about=True):
    return add_shop(Site(), "golsorkh.ir", robots, with_support, with_about)


def add_mini_shop(site, host, number):
    """A tiny shop with ITS OWN phone and e-mail (so several leads do not collide on identifiers)."""
    site.robots(host)
    phone = f"0912000{number:04d}"
    site.add(
        host, "/",
        f'<html lang="fa"><head><title>فروشگاه {number}</title></head><body><nav><a href="/contact">تماس با ما</a></nav>'
        f"<p>خوش آمدید به فروشگاه شمارهٔ {number} که محصولات زیادی دارد.</p>"
        f'<a href="tel:{phone}">تماس</a> <a href="mailto:shop{number}@{host}">ایمیل</a></body></html>',
    )
    site.add(host, "/contact", "<html><body><h1>تماس با ما</h1><form action='/send'><textarea name='m'></textarea></form></body></html>")
    return phone
