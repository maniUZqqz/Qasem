"""Shared helpers of the outreach tests: a fake web (httpx.MockTransport) with GET and POST routes, mocked fetchers,
and factories for leads, settings, templates, campaigns and prepared items. No test here touches a real site."""
from __future__ import annotations

import itertools
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl

import httpx

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.integrations import safe_http as sh
from apps.growth_engine.leads.choices import ContactKind
from apps.growth_engine.leads.models import ContactPoint
from apps.growth_engine.leads.services import intake
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.outreach.models import Campaign, ItemStatus, MessageTemplate, OutreachItem
from apps.growth_engine.outreach.services import approval, campaigns, preparing
from apps.growth_engine.sources.models import SourceProvider

PAGES = Path(__file__).parent / "fixtures" / "pages"
PUBLIC = "93.184.216.34"
IDENTITY = {
    "sender_name": "علی رضایی", "sender_company": "آپ‌مارکت", "sender_phone": "0912 123 4567", "sender_email": "ali@upmarket.ir",
}
_counter = itertools.count(1)


def page(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


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
    """A fake web. Routes are ``(METHOD, host, path)``; the Host header decides the host (the fetcher addresses the checked IP).
    A route body may be a callable ``(request) -> str`` so a page can change between two fetches (a captcha appearing...)."""

    def __init__(self):
        self.routes: dict[tuple[str, str, str], dict] = {}
        self.requests: list[httpx.Request] = []
        self.token = "TOKEN-1"

    def add(self, method, host, path, body="", status=200, ctype="text/html; charset=utf-8", headers=None, error=None):
        self.routes[(method, host, path)] = {"body": body, "status": status, "ctype": ctype, "headers": headers or {}, "error": error}
        return self

    def robots(self, host, text="User-agent: *\nAllow: /\n", status=200):
        return self.add("GET", host, "/robots.txt", text, status=status, ctype="text/plain")

    def form_page(self, host, path="/contact", fixture="contact_ok.html"):
        """The contact page, with a per-load CSRF token (so a re-fetch gives a different hidden value)."""
        return self.add("GET", host, path, lambda request: page(fixture).replace("{token}", self.token))

    def accept_posts(self, host, path="/send-message", fixture="thanks.html", status=200, headers=None):
        return self.add("POST", host, path, page(fixture), status=status, headers=headers)

    def shop(self, host, *, robots=True):
        """A complete cooperative site: robots, the contact form and an endpoint that thanks you."""
        if robots:
            self.robots(host)
        self.form_page(host)
        self.accept_posts(host)
        return self

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get((request.method, request.headers["host"], request.url.path))
        if route is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        if route["error"]:
            raise route["error"]
        body = route["body"](request) if callable(route["body"]) else route["body"]
        headers = {"content-type": route["ctype"], **route["headers"]}
        return httpx.Response(route["status"], content=body.encode("utf-8") if isinstance(body, str) else body, headers=headers)

    # ---- what the test wants to know
    def posts(self):
        return [r for r in self.requests if r.method == "POST"]

    def post_fields(self, index=-1) -> list[tuple[str, str]]:
        return parse_qsl(self.posts()[index].content.decode(), keep_blank_values=True)

    def paths(self, method=None):
        return [r.url.path for r in self.requests if method in (None, r.method)]


def make_fetcher(site: Site, resolver=None, **kwargs):
    clock = FakeClock()
    throttle = sh.DomainThrottle(clock=clock.time, sleep=clock.sleep)
    return sh.SafeFetcher(
        resolver=resolver or (lambda host, port: [PUBLIC]), transport=httpx.MockTransport(site), throttle=throttle, sleep=clock.sleep, **kwargs
    )


@contextmanager
def use_site(site: Site, **kwargs):
    """Every fetcher the prepare / send jobs create talks to ``site``."""
    with mock.patch.object(preparing, "make_fetcher", lambda: make_fetcher(site, **kwargs)):
        yield


class FakeSleep:
    """An injectable sleep: records every pause and can run a callback after the n-th one (to simulate a stop request)."""

    def __init__(self, after=None, callback=None):
        self.calls: list[float] = []
        self.after, self.callback = after, callback

    def __call__(self, seconds):
        self.calls.append(seconds)
        if self.callback and self.after is not None and len(self.calls) == self.after:
            self.callback()

    @property
    def total(self):
        return sum(self.calls)


class MidRng:
    """rng.uniform(low, high) -> the exact middle, so a test can assert on the spacing."""

    def uniform(self, low, high):
        return (low + high) / 2


# --------------------------------------------------------------------------- factories


def configure(**overrides) -> GrowthSettings:
    """Growth Settings that allow sending (identity complete, switch on). Override any field."""
    s = GrowthSettings.load()
    for key, value in {**IDENTITY, "sending_enabled": True, "emergency_stop": False, **overrides}.items():
        setattr(s, key, value)
    s.save()
    return s


def make_lead(host="shop-a.ir", *, form=True, name=None, city="تهران", **raw):
    """A lead with a website (and, by default, the contact page found by extraction)."""
    n = next(_counter)
    raw.setdefault("business_name", name or f"فروشگاه {n}")
    raw.setdefault("phone", f"0912{n:07d}")
    if host:
        raw.setdefault("website", f"https://{host}/")
    raw.setdefault("city", city)
    draft, errors = build_draft(raw)
    assert not errors, errors
    lead = intake.create_from_draft(draft, intake.SourceInfo(SourceProvider.MANUAL, "manual"), None)
    if form and host:
        ContactPoint.objects.create(
            lead=lead, kind=ContactKind.CONTACT_FORM, value=f"https://{host}/contact", normalized=f"https://{host}/contact",
            label="فرم تماس", confidence=85, source_ref="extract:1", source_url=f"https://{host}/contact",
        )
    return lead


def make_template(name="معرفی", body="سلام {business_name}\nما آپ‌مارکت هستیم؛ برای {city|شهر شما} پیشنهادی داریم.", subject="معرفی آپ‌مارکت", **kw):
    return MessageTemplate.objects.create(name=name, body=body, subject=subject, **kw)


def make_campaign(template=None, mode=Campaign.Mode.AUTO, name="کمپین آزمایشی", user=None) -> Campaign:
    return campaigns.create_campaign(name=name, template=template or make_template(), mode=mode, user=user)


def ready_item(site: Site, campaign: Campaign, host="shop-a.ir", settings_obj=None, **lead_kw) -> OutreachItem:
    """A lead in ``campaign`` whose form page was read by the REAL analyser against ``site``: the item is ``ready``."""
    lead = make_lead(host, **lead_kw)
    result = campaigns.add_leads(campaign, [lead.pk])
    assert len(result.added) == 1, result.skipped
    item = OutreachItem.objects.select_related("lead", "campaign", "campaign__template").get(pk=result.added[0].pk)
    with use_site(site):
        fetcher = preparing.make_fetcher()
        preparing.prepare_item(item, fetcher, settings_obj or GrowthSettings.load())
    item.refresh_from_db()
    assert item.status == ItemStatus.READY, (item.status, item.skip_reason, item.skip_reason_text)
    return item


def approved_item(site, campaign, host="shop-a.ir", staff=None, **lead_kw) -> OutreachItem:
    item = ready_item(site, campaign, host, **lead_kw)
    outcome = approval.approve_items(campaign, item_ids=[item.pk], actor=staff)
    assert outcome["approved"] == 1, outcome
    item.refresh_from_db()
    return item
