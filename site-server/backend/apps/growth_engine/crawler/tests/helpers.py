"""Shared test tools: a fake web (nothing real is ever contacted), sample pages and a ready-made mission."""
from __future__ import annotations

import base64
import json
from urllib.parse import urlsplit

import httpx

from apps.growth_engine.core.testing import NoNetworkMixin
from apps.growth_engine.integrations.safe_http import DomainThrottle

from ..engine.fetch import CrawlFetcher


class FakeWeb:
    """Routes ``(host, path)`` to canned answers. ``factory`` is what ``run_crawl(web_factory=...)`` takes."""

    def __init__(self):
        self.routes: list[tuple[str, str, object]] = []  # (host, path prefix, response or callable)
        self.calls: list[tuple[str, str]] = []

    def add(self, host: str, path: str, body: str = "", *, status: int = 200, ctype: str = "text/html; charset=utf-8", headers: dict | None = None, exact: bool = False):
        self.routes.append((host, path, (status, ctype, body, headers or {}, exact)))
        return self

    def add_fn(self, host: str, path: str, fn):
        self.routes.append((host, path, fn))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host", "").split(":")[0]
        path = request.url.raw_path.decode()
        self.calls.append((host, path))
        for h, prefix, resp in reversed(self.routes):
            if h != host:
                continue
            if callable(resp):
                out = resp(request)
                if out is not None:
                    return out
                continue
            status, ctype, body, headers, exact = resp
            if (exact and path.split("?")[0] == prefix) or (not exact and path.startswith(prefix)):
                return httpx.Response(status, text=body, headers={"content-type": ctype, **headers})
        if path.split("?")[0] == "/robots.txt":
            return httpx.Response(404, text="")
        return httpx.Response(404, text="not found", headers={"content-type": "text/html"})

    def fetcher(self, **kwargs) -> CrawlFetcher:
        return CrawlFetcher(
            transport=httpx.MockTransport(self.handler), resolver=lambda host, port: ["93.184.216.34"], throttle=DomainThrottle(sleep=lambda s: None), sleep=lambda s: None,
            read_timeout=kwargs.get("read_timeout"), domain_delay=0.0,
        )

    @property
    def factory(self):
        return lambda **kw: self.fetcher(**kw)

    def hits(self, host: str, prefix: str = "") -> int:
        return sum(1 for h, p in self.calls if h == host and p.startswith(prefix))


# --------------------------------------------------------------------------- pages


def bing_page(results: list[tuple[str, str, str]]) -> str:
    items = ""
    for url, title, snippet in results:
        wrapped = "https://www.bing.com/ck/a?!&&p=abc&u=a1" + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=") + "&ntb=1"
        items += f'<li class="b_algo"><h2><a href="{wrapped}">{title}</a></h2><div class="b_caption"><p>{snippet}</p></div></li>'
    return f'<html><body><ol id="b_results">{items}</ol></body></html>'


def overpass_json(elements: list[dict]) -> str:
    return json.dumps({"version": 0.6, "elements": elements}, ensure_ascii=False)


def osm_node(i: int, name: str, lat: float, lon: float, **tags) -> dict:
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"name": name, **tags}}


NOMINATIM_TEHRAN = json.dumps([{"osm_type": "relation", "osm_id": 6663864, "lat": "35.689", "lon": "51.389", "display_name": "تهران", "category": "boundary",
                                "boundingbox": ["35.5", "35.9", "51.0", "51.7"], "importance": 0.9}])
NOMINATIM_ISFAHAN = json.dumps([{"osm_type": "relation", "osm_id": 6566419, "lat": "32.65", "lon": "51.67", "display_name": "اصفهان", "category": "boundary",
                                 "boundingbox": ["32.5", "32.8", "51.5", "51.8"], "importance": 0.9}])

SITE_HOME = """<html lang="fa"><head><title>باشگاه آرمان | تهران</title><meta name="description" content="باشگاه بدنسازی و فیتنس آرمان با مربی‌های مجرب"></head>
<body><nav><a href="/">خانه</a> <a href="/contact">تماس با ما</a> <a href="/about">درباره ما</a></nav>
<h1>باشگاه آرمان</h1><p>باشگاه بدنسازی با مربی شخصی و برنامه تمرینی اختصاصی</p></body></html>"""
SITE_CONTACT = """<html lang="fa"><body><h1>تماس با ما</h1>
<p>آدرس: تهران، سعادت‌آباد، خیابان دوم، پلاک ۱۲</p>
<p>تلفن: <a href="tel:+989121834765">۰۹۱۲ ۱۸۳ ۴۷۶۵</a></p><p>ایمیل: <a href="mailto:info@arman-gym.ir">info@arman-gym.ir</a></p>
<p><a href="https://www.instagram.com/arman.gym/">اینستاگرام</a></p>
<p>ساعت کاری: شنبه تا چهارشنبه ۷ تا ۲۲</p></body></html>"""
SITE_ABOUT = "<html lang='fa'><body><h1>درباره ما</h1><p>مربی‌های ما شاگردان را با برنامه غذایی راهنمایی می‌کنند.</p></body></html>"
JS_SHELL = '<html><head><title>app</title></head><body><div id="root"></div><script src="/static/app.js"></script></body></html>'

BADANFIT_LIST = """<html><body><div class="results-grid">
<a href="gym-detail.php?id=11" class="gym-card"><div class="gym-card-name">باشگاه ورزشی نمونه یک</div><div class="gym-card-address">تهران، خیابان آزادی، Q9W7+MCG</div>
<div class="gym-card-meta"><span class="gym-card-rating">⭐ 4.5 (10 نظر)</span><span class="gym-card-phone">021 2200 0001</span></div></a>
<a href="gym-detail.php?id=12" class="gym-card"><div class="gym-card-name">باشگاه نمونه دو</div><div class="gym-card-address">تهران، ونک</div>
<div class="gym-card-meta"><span class="gym-card-rating">⭐ 5 (3 نظر)</span><span class="gym-card-phone">0912 000 0002</span></div></a></div></body></html>"""
BADANFIT_DETAIL = """<html><head><title>باشگاه ورزشی نمونه یک | بدن‌فیت</title><script type="application/ld+json">{"@context":"https://schema.org","@type":"ExerciseGym","name":"باشگاه ورزشی نمونه یک",
"address":{"@type":"PostalAddress","streetAddress":"تهران، خیابان آزادی","addressLocality":"تهران"},"telephone":"021 2200 0001","geo":{"@type":"GeoCoordinates","latitude":"35.7","longitude":"51.4"},"url":"https://badanfit.ir/gym-detail.php?id=11"}</script></head>
<body><h1>باشگاه ورزشی نمونه یک</h1><h3>ساعات کاری</h3><p>شنبه: 7:00 تا 22:00</p><p>جمعه: بسته</p></body></html>"""


def make_mission(**spec_overrides):
    """A small mission with every source that works offline switched on; returns the CrawlMission."""
    from ..models import CrawlMission
    from ..services import missions

    spec = {
        "business_types": ["gym"], "keywords": ["مربی"], "cities": ["تهران"], "language": "fa", "require_contact": True, "max_results": 100,
        "sources": {"osm": True, "search": False, "directory": False, "website": True, "instagram": False, "neshan": False},
        "budget": {"max_requests": 200, "max_sites": 10, "max_pages_per_site": 4, "max_seconds": 300, "domain_delay": 1.0}, "tag": "تست",
        "pitch": {"brand": "چغر", "what": "چغر دستیارِ هوش مصنوعیِ مربی‌هاست.", "benefit": "وقتِ نوشتنِ برنامه را کم می‌کند.", "cta": "اگر مایلید پاسخ بدهید.", "sms": "دستیارِ هوش مصنوعیِ مربی‌ها؛ شروع رایگان."},
        **spec_overrides,
    }
    return missions.create_mission({"name": "مأموریتِ آزمون", "product": "chagher", "spec": spec})


class Base(NoNetworkMixin):
    """Mixin for TestCase classes of this app."""

    def web_with_gyms(self) -> FakeWeb:
        web = FakeWeb()
        web.add("nominatim.openstreetmap.org", "/search", NOMINATIM_TEHRAN)
        web.add("overpass-api.de", "/api/interpreter", overpass_json([
            osm_node(1, "باشگاه آرمان", 35.7001, 51.4001, leisure="fitness_centre", phone="+98 21 2222 3333", website="http://arman-gym.ir", opening_hours="Mo-Su 07:00-22:00"),
            osm_node(2, "باشگاه آرمان", 35.7002, 51.4002, leisure="fitness_centre"),  # the same business mapped twice (a building and a node)
            osm_node(3, "فیتنس سپهر", 35.71, 51.41, leisure="fitness_centre", phone="09121112222"),
            osm_node(4, "باشگاه بدونِ تماس", 35.72, 51.42, leisure="fitness_centre"),
            osm_node(5, "باشگاه آرمان", 35.80, 51.50, leisure="fitness_centre", phone="02144445555"),  # another branch, 14 km away
        ]))
        web.add("arman-gym.ir", "/contact", SITE_CONTACT, exact=True)
        web.add("arman-gym.ir", "/about", SITE_ABOUT, exact=True)
        web.add("arman-gym.ir", "/", SITE_HOME, exact=True)
        return web
