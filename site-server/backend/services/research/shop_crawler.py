"""Read a competitor's own shop site: which products, at what price.

The shop owner asked for this directly: «خودش بره کرال کنه محصولات رو». Until
now every competitor product was typed in by hand, so the competitor list was
as long as the owner's patience.

**What this does, and the limits it keeps.**

* It reads pages a shop *publishes for machines*: ``robots.txt`` first, then
  the sitemap(s) it points to, then — only if no sitemap lists products — the
  links on the home page. It never logs in, never submits forms, never runs
  JavaScript.
* A page is a product only when it *says so*: a JSON-LD ``Product`` (with an
  ``Offer``), OpenGraph ``product:price``, schema.org microdata, or the
  WooCommerce price markup. A page that merely mentions a price is skipped —
  a guessed price is worse than no price.
* Bounded: ``max_pages`` product pages, a timeout per request, a polite delay
  between requests, and ``robots.txt`` respected (a disallowed URL is counted
  and skipped, never fetched).
* Prices are stored in **toman**. The currency comes from what the page
  declares (``IRR``/``IRT``/«ریال»/«تومان»). When a page does not say, the
  number is kept but marked ``currency_guess`` so the panel can flag it.

Everything here is pure functions over HTML strings plus one ``crawl`` driver,
so parsing is unit-testable offline against saved fixtures.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; UpMarketBot/1.0; +https://upmarket.ir/bot) "
    "price-comparison for the shop owner"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "fa,en;q=0.8"}

#: Defaults the panel uses. The owner can lower them; the task caps them.
DEFAULT_MAX_PAGES = 30
HARD_MAX_PAGES = 120
REQUEST_TIMEOUT = 15
POLITE_DELAY = 1.0
#: Sitemaps can be enormous; we only need enough URLs to pick from.
MAX_SITEMAP_URLS = 2000
MAX_SITEMAP_FILES = 12
MAX_BYTES = 3_000_000
#: Category / collection pages read only to find product links.
MAX_LISTING_PAGES = 8

# ---------------------------------------------------------------- text helpers

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def to_ascii_digits(text: str) -> str:
    return (text or "").translate(_FA_DIGITS)


def clean_text(text: str | None) -> str:
    text = html_lib.unescape(_TAG.sub(" ", text or ""))
    return _SPACE.sub(" ", text).strip()


def parse_number(text) -> int | None:
    """``"۱۲۵,۰۰۰"`` / ``"125.000"`` / ``"125000.00"`` → 125000.

    Iranian shops write thousands with ``,`` ``٬`` ``.`` or a space, and a few
    WooCommerce themes add ``.00`` decimals. A trailing two-digit decimal is
    dropped; every other separator is a thousands separator.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text) if text >= 0 else None
    s = to_ascii_digits(str(text)).strip()
    s = s.replace("٬", ",").replace("،", ",").replace("٫", ".")
    m = re.search(r"\d[\d,.\s]*", s)
    if not m:
        return None
    raw = m.group(0).strip()
    # "125000.00" → drop the decimals; "125.000" / "1,250,000" are thousands.
    raw = re.sub(r"[.,]\d{1,2}$", "", raw)
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    value = int(digits)
    return value if value > 0 else None


#: Declared currency → divisor to reach toman. None = not declared.
_CURRENCY = {
    "IRR": 10, "RIAL": 10, "ریال": 10, "ريال": 10,
    "IRT": 1, "TOMAN": 1, "TOM": 1, "تومان": 1, "تومن": 1, "ت": 1,
}


def currency_divisor(declared: str | None) -> int | None:
    if not declared:
        return None
    key = str(declared).strip().upper()
    if key in _CURRENCY:
        return _CURRENCY[key]
    for word, divisor in _CURRENCY.items():
        if len(word) > 1 and word in str(declared):
            return divisor
    return None


def to_toman(amount, declared_currency: str | None = None, context_text: str = "") -> tuple[int | None, str]:
    """Return (toman, how) — ``how`` says where the currency came from."""
    value = parse_number(amount)
    if value is None:
        return None, "no_price"
    divisor = currency_divisor(declared_currency)
    if divisor is not None:
        return value // divisor, f"declared:{declared_currency}"
    divisor = currency_divisor(context_text) or currency_divisor(
        amount if isinstance(amount, str) else ""
    )
    if divisor is not None:
        return value // divisor, "text"
    # Not declared anywhere. Kept, but flagged: the panel shows «واحد نامعلوم».
    return value, "currency_guess"


# ---------------------------------------------------------------- extraction


@dataclass
class ExtractedProduct:
    name: str
    url: str
    price_toman: int | None = None
    image: str = ""
    currency_how: str = ""
    method: str = ""
    in_stock: bool | None = None
    brand: str = ""
    sku: str = ""
    raw_price: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "url": self.url, "price_toman": self.price_toman,
            "image": self.image, "currency_how": self.currency_how,
            "method": self.method, "in_stock": self.in_stock, "brand": self.brand,
            "sku": self.sku, "raw_price": self.raw_price,
        }


_JSONLD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)


def _iter_jsonld(html: str):
    for block in _JSONLD.findall(html or ""):
        text = block.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            # Some themes emit trailing commas or raw newlines in strings.
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", text.replace("\n", " ")))
            except ValueError:
                continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                for key in ("@graph", "mainEntity", "itemListElement", "item"):
                    if key in node:
                        stack.append(node[key])


def _is_type(node: dict, wanted: str) -> bool:
    kind = node.get("@type")
    if isinstance(kind, list):
        return any(str(k).lower() == wanted.lower() for k in kind)
    return str(kind or "").lower() == wanted.lower()


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _image_of(value) -> str:
    value = _first(value)
    if isinstance(value, dict):
        return str(value.get("url") or value.get("contentUrl") or "")
    return str(value or "")


def _offer_price(offers) -> tuple[str | None, str | None, bool | None]:
    """(price, currency, in_stock) from an Offer / AggregateOffer / list."""
    candidates = offers if isinstance(offers, list) else [offers]
    for offer in candidates:
        if not isinstance(offer, dict):
            continue
        price = offer.get("price") or offer.get("lowPrice")
        currency = offer.get("priceCurrency")
        spec = offer.get("priceSpecification")
        if price in (None, "") and spec:
            spec = _first(spec) if isinstance(spec, list) else spec
            if isinstance(spec, dict):
                price = spec.get("price")
                currency = currency or spec.get("priceCurrency")
        if price in (None, ""):
            continue
        availability = str(offer.get("availability") or "")
        in_stock = None
        if availability:
            in_stock = "instock" in availability.lower().replace("_", "")
        return str(price), currency, in_stock
    return None, None, None


def extract_jsonld(html: str, url: str) -> ExtractedProduct | None:
    for node in _iter_jsonld(html):
        if not _is_type(node, "Product"):
            continue
        name = clean_text(str(node.get("name") or ""))
        if not name:
            continue
        price, currency, in_stock = _offer_price(node.get("offers"))
        toman, how = to_toman(price, currency) if price else (None, "no_price")
        brand = node.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        return ExtractedProduct(
            name=name[:200], url=str(node.get("url") or url), price_toman=toman,
            image=_image_of(node.get("image")), currency_how=how, method="json-ld",
            in_stock=in_stock, brand=clean_text(str(_first(brand) or ""))[:80],
            sku=str(node.get("sku") or "")[:60], raw_price=str(price or ""),
        )
    return None


def _meta(html: str, prop: str) -> str:
    pattern = (
        r'<meta[^>]+(?:property|name|itemprop)=["\']' + re.escape(prop)
        + r'["\'][^>]*content=["\']([^"\']*)["\']'
    )
    m = re.search(pattern, html, re.I)
    if m:
        return html_lib.unescape(m.group(1)).strip()
    pattern = (
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name|itemprop)=["\']'
        + re.escape(prop) + r'["\']'
    )
    m = re.search(pattern, html, re.I)
    return html_lib.unescape(m.group(1)).strip() if m else ""


def extract_opengraph(html: str, url: str) -> ExtractedProduct | None:
    amount = _meta(html, "product:price:amount") or _meta(html, "og:price:amount")
    og_type = _meta(html, "og:type").lower()
    if not amount and "product" not in og_type:
        return None
    if not amount:
        return None
    currency = _meta(html, "product:price:currency") or _meta(html, "og:price:currency")
    name = _meta(html, "og:title") or _h1(html)
    if not name:
        return None
    toman, how = to_toman(amount, currency)
    return ExtractedProduct(
        name=clean_text(name)[:200], url=_meta(html, "og:url") or url,
        price_toman=toman, image=_meta(html, "og:image"), currency_how=how,
        method="opengraph", raw_price=amount,
    )


def extract_microdata(html: str, url: str) -> ExtractedProduct | None:
    if not re.search(r'itemtype=["\']https?://schema\.org/Product["\']', html, re.I):
        return None
    price = _meta(html, "price")
    if not price:
        m = re.search(r'itemprop=["\']price["\'][^>]*>([^<]+)<', html, re.I)
        price = m.group(1) if m else ""
    if not price:
        return None
    currency = _meta(html, "priceCurrency")
    m = re.search(r'itemprop=["\']name["\'][^>]*>(.*?)</', html, re.I | re.S)
    name = clean_text(m.group(1)) if m else _h1(html)
    if not name:
        return None
    toman, how = to_toman(price, currency)
    return ExtractedProduct(
        name=name[:200], url=url, price_toman=toman, image=_meta(html, "og:image"),
        currency_how=how, method="microdata", raw_price=price,
    )


_WOO_SUMMARY = re.compile(
    r'<(?:p|span|div)[^>]+class=["\'][^"\']*\bprice\b[^"\']*["\'][^>]*>(.*?)</(?:p|div)>',
    re.S | re.I,
)
_WOO_AMOUNT = re.compile(
    r'<span[^>]+class=["\'][^"\']*woocommerce-Price-amount[^"\']*["\'][^>]*>(.*?)</span>\s*(?:</bdi>)?',
    re.S | re.I,
)


def extract_woocommerce(html: str, url: str) -> ExtractedProduct | None:
    """WooCommerce single-product page without structured data.

    The *sale* price is the ``<ins>`` amount when present; otherwise the last
    amount in the summary price block (the first may be the struck-out one).
    """
    if "woocommerce" not in html.lower() or "single-product" not in html.lower():
        return None
    title = re.search(r'<h1[^>]*class=["\'][^"\']*product_title[^"\']*["\'][^>]*>(.*?)</h1>', html, re.S | re.I)
    name = clean_text(title.group(1)) if title else ""
    if not name:
        return None
    block = _WOO_SUMMARY.search(html)
    if not block:
        return None
    segment = block.group(1)
    ins = re.search(r"<ins[^>]*>(.*?)</ins>", segment, re.S | re.I)
    if ins:
        segment = ins.group(1)
    amounts = _WOO_AMOUNT.findall(segment) or [segment]
    text = clean_text(amounts[-1])
    toman, how = to_toman(text, None, clean_text(segment))
    if toman is None:
        return None
    return ExtractedProduct(
        name=name[:200], url=url, price_toman=toman, image=_meta(html, "og:image"),
        currency_how=how, method="woocommerce", raw_price=text,
    )


def _h1(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S | re.I)
    return clean_text(m.group(1)) if m else ""


EXTRACTORS = (extract_jsonld, extract_opengraph, extract_microdata, extract_woocommerce)


def extract_product(html: str, url: str) -> ExtractedProduct | None:
    """The first extractor that finds a named product wins; a later one may
    fill a missing price (JSON-LD without offers + OpenGraph price is common)."""
    found = None
    for extractor in EXTRACTORS:
        try:
            item = extractor(html, url)
        except Exception:  # noqa: BLE001 — one malformed block must not lose the page
            logger.debug("extractor %s failed on %s", extractor.__name__, url, exc_info=True)
            item = None
        if item is None:
            continue
        if found is None:
            found = item
        elif found.price_toman is None and item.price_toman is not None:
            found.price_toman = item.price_toman
            found.currency_how = item.currency_how
            found.raw_price = item.raw_price
            found.method += f"+{item.method}"
        if found.price_toman is not None:
            break
    if found is not None:
        if found.image:
            found.image = urljoin(url, found.image)
        found.url = urljoin(url, found.url or url)
    return found


# ---------------------------------------------------------------- discovery

_PRODUCT_PATH = re.compile(
    r"/(product|products|shop|p|item|kala|محصول|فروشگاه)/[^/?#]+",
    re.I,
)
_SKIP_PATH = re.compile(
    r"/(product-category|product-tag|category|tag|cart|checkout|my-account|"
    r"wp-admin|wp-login|wp-json|wp-content|login|register|blog|page|author|feed|search|"
    r"comments|embed)(/|$)"
    r"|\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|css|js|php|xml|json)$",
    re.I,
)
#: Listing pages that *link to* products (WooCommerce categories, Shopify
#: collections, generic shop pages). Read only to harvest product links.
_LISTING_PATH = re.compile(
    r"/(product-category|product-cat|collections|category|shop|store|فروشگاه|دسته)(/|$)",
    re.I,
)


def looks_like_listing_url(url: str) -> bool:
    path = unquote(urlparse(url).path)
    return bool(_LISTING_PATH.search(path)) and not re.search(
        r"/(feed|wp-json|embed)(/|$)|\.(php|xml|json)$", path, re.I,
    )


def looks_like_product_url(url: str) -> bool:
    path = unquote(urlparse(url).path)
    return bool(_PRODUCT_PATH.search(path)) and not _SKIP_PATH.search(path)


def normalise_site(website: str) -> str:
    website = (website or "").strip()
    if not website:
        raise ValueError("سایتِ این رقیب ثبت نشده است.")
    if not re.match(r"^https?://", website, re.I):
        website = "https://" + website
    parsed = urlparse(website)
    if not parsed.netloc:
        raise ValueError(f"نشانیِ سایت معتبر نیست: {website}")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), "/", "", "", ""))


def same_site(url: str, base: str) -> bool:
    a = urlparse(url).netloc.lower().removeprefix("www.")
    b = urlparse(base).netloc.lower().removeprefix("www.")
    return bool(a) and a == b


def parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """(child sitemaps, page urls) from a sitemap or sitemap index."""
    locs = [html_lib.unescape(x.strip()) for x in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml or "", re.S)]
    if re.search(r"<sitemapindex", xml or "", re.I):
        return locs, []
    return [], locs


def links_in(html: str, base_url: str) -> list[str]:
    out, seen = [], set()
    for href in re.findall(r'href=["\']([^"\'#]+)["\']', html or "", re.I):
        url = urljoin(base_url, html_lib.unescape(href.strip()))
        if url not in seen and url.startswith("http"):
            seen.add(url)
            out.append(url)
    return out


def sitemap_kind(url: str) -> str:
    """``product`` (product pages), ``listing`` (product categories /
    collections — pages that link to products) or ``other``."""
    low = unquote(url.lower())
    if re.search(r"product[_-]?(cat|tag|categor)|collection", low):
        return "listing"
    if "product" in low or "محصول" in low:
        return "product"
    return "other"


def rank_child_sitemaps(children: list[str]) -> list[str]:
    """Product sitemaps first (WooCommerce/Yoast ``product-sitemap``, Shopify
    ``sitemap_products_1``, RankMath ``product-sitemap1``), then product
    categories; posts/pages last."""
    order = {"product": 0, "listing": 1, "other": 2}
    return sorted(children, key=lambda url: order[sitemap_kind(url)])


# ---------------------------------------------------------------- the crawl


@dataclass
class CrawlReport:
    site: str
    products: list[dict] = field(default_factory=list)
    pages_fetched: int = 0
    candidates: int = 0
    robots: str = "unknown"
    robots_blocked: int = 0
    sitemaps_read: list[str] = field(default_factory=list)
    discovery: str = ""
    errors: list[str] = field(default_factory=list)
    skipped_no_product: int = 0
    stopped: str = ""

    def as_dict(self) -> dict:
        return {
            "site": self.site, "products_found": len(self.products),
            "pages_fetched": self.pages_fetched, "candidates": self.candidates,
            "robots": self.robots, "robots_blocked": self.robots_blocked,
            "sitemaps_read": self.sitemaps_read[:MAX_SITEMAP_FILES],
            "discovery": self.discovery, "errors": self.errors[:10],
            "skipped_no_product": self.skipped_no_product, "stopped": self.stopped,
        }


class _Fetcher:
    """One session, one politeness clock, robots checked before every GET."""

    def __init__(self, base: str, delay: float, timeout: int, session=None):
        self.base = base
        self.delay = delay
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        # A redirect loop (seen on real robots.txt) should cost seconds, not 30 hops.
        try:
            self.session.max_redirects = 5
        except AttributeError:
            pass
        self._last = 0.0
        self.robots = robotparser.RobotFileParser()
        self.robots_state = "unknown"
        self.robots_sitemaps: list[str] = []

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def load_robots(self):
        url = urljoin(self.base, "/robots.txt")
        try:
            self._wait()
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            # Unreachable robots.txt (timeouts, redirect loops) is treated as
            # "no rules", like every major crawler does — but recorded.
            self.robots_state = f"unreachable ({type(exc).__name__})"
            self.robots.parse([])
            return
        if response.status_code >= 500:
            # Server error on robots.txt: be conservative and crawl nothing.
            self.robots_state = f"error {response.status_code} — crawl stopped"
            self.robots.parse(["User-agent: *", "Disallow: /"])
            return
        if response.status_code >= 400:
            self.robots_state = "none"
            self.robots.parse([])
            return
        lines = response.text.splitlines()
        self.robots.parse(lines)
        self.robots_state = "read"
        self.robots_sitemaps = [
            line.split(":", 1)[1].strip() for line in lines
            if line.lower().startswith("sitemap:")
        ]

    def allowed(self, url: str) -> bool:
        try:
            return self.robots.can_fetch(USER_AGENT, url) and self.robots.can_fetch("*", url)
        except Exception:  # noqa: BLE001
            return True

    def crawl_delay(self) -> float | None:
        try:
            value = self.robots.crawl_delay(USER_AGENT) or self.robots.crawl_delay("*")
            return float(value) if value else None
        except Exception:  # noqa: BLE001
            return None

    def get(self, url: str) -> requests.Response | None:
        self._wait()
        response = self.session.get(url, timeout=self.timeout, stream=True)
        content = response.raw.read(MAX_BYTES + 1, decode_content=True)
        response._content = content[:MAX_BYTES]
        response._content_consumed = True
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = "utf-8"
        return response


def crawl(
    website: str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    delay: float = POLITE_DELAY,
    timeout: int = REQUEST_TIMEOUT,
    progress=None,
    should_stop=None,
    session=None,
) -> CrawlReport:
    """Find up to ``max_pages`` product pages on ``website`` and read them.

    ``progress(done, total, label)`` is called after each page so a job can
    show it; ``should_stop()`` lets the panel cancel between pages.
    """
    base = normalise_site(website)
    max_pages = max(1, min(int(max_pages or DEFAULT_MAX_PAGES), HARD_MAX_PAGES))
    report = CrawlReport(site=base)
    fetch = _Fetcher(base, delay, timeout, session=session)
    fetch.load_robots()
    report.robots = fetch.robots_state
    if fetch.crawl_delay():
        fetch.delay = max(fetch.delay, min(fetch.crawl_delay(), 10.0))

    def note(label):
        if progress:
            progress(len(report.products), max_pages, label)

    # ---- 1. sitemaps -------------------------------------------------------
    note("خواندنِ نقشه‌ی سایت (sitemap)")
    queue = list(dict.fromkeys(
        fetch.robots_sitemaps
        + [urljoin(base, "/sitemap_index.xml"), urljoin(base, "/sitemap.xml"),
           urljoin(base, "/product-sitemap.xml"), urljoin(base, "/wp-sitemap.xml")]
    ))
    seen_maps: set[str] = set()
    product_urls: list[str] = []
    listing_urls: list[str] = []
    other_urls: list[str] = []
    while queue and len(seen_maps) < MAX_SITEMAP_FILES and len(product_urls) < MAX_SITEMAP_URLS:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_maps:
            continue
        seen_maps.add(sitemap_url)
        if not fetch.allowed(sitemap_url):
            report.robots_blocked += 1
            continue
        try:
            response = fetch.get(sitemap_url)
        except requests.RequestException as exc:
            report.errors.append(f"sitemap {sitemap_url}: {type(exc).__name__}")
            continue
        body = response.text if response is not None else ""
        if response is None or response.status_code != 200 or "<loc>" not in body:
            continue
        report.sitemaps_read.append(sitemap_url)
        children, pages = parse_sitemap(body)
        # Only the product-ish child sitemaps are worth reading; a WordPress
        # site with 40 post sitemaps would otherwise eat the whole budget.
        ranked = rank_child_sitemaps(children)
        useful = [c for c in ranked if sitemap_kind(c) != "other"]
        queue = (useful or ranked[:4]) + queue
        kind = sitemap_kind(sitemap_url)
        for page in pages:
            if not same_site(page, base):
                continue
            if kind == "listing" or (looks_like_listing_url(page) and not looks_like_product_url(page)):
                listing_urls.append(page)
            elif looks_like_product_url(page) or kind == "product":
                product_urls.append(page)
            else:
                other_urls.append(page)
    product_urls = list(dict.fromkeys(product_urls))
    report.discovery = "sitemap" if product_urls else ""

    # ---- 2. links on the home page (and one shop page) -----------------------
    if len(product_urls) < max_pages:
        before = len(product_urls)
        note("خواندنِ صفحه‌ی اصلی برای پیوندِ محصولات")
        listing_pages = list(dict.fromkeys(
            [base, urljoin(base, "/shop/"), urljoin(base, "/products/")] + listing_urls[:MAX_LISTING_PAGES]
        ))
        for page in listing_pages:
            if len(product_urls) >= max_pages * 2:
                break
            if not fetch.allowed(page):
                report.robots_blocked += 1
                continue
            try:
                response = fetch.get(page)
            except requests.RequestException as exc:
                report.errors.append(f"{page}: {type(exc).__name__}")
                continue
            if response is None or response.status_code != 200:
                continue
            report.pages_fetched += 1
            # The home page itself may be a product listing with JSON-LD
            # ItemList — not needed; we follow its product links instead.
            for link in links_in(response.text, page):
                if same_site(link, base) and looks_like_product_url(link):
                    product_urls.append(link.split("?")[0])
                elif (
                    same_site(link, base) and looks_like_listing_url(link)
                    and len(listing_pages) < MAX_LISTING_PAGES + 3 and link not in listing_pages
                ):
                    listing_pages.append(link.split("?")[0])
        product_urls = list(dict.fromkeys(product_urls))
        if len(product_urls) > before:
            report.discovery = "sitemap+home-links" if report.discovery else "home-links"

    # A sitemap that listed only generic pages: try those, product markup
    # decides. Last resort, still bounded by max_pages.
    if not product_urls and other_urls:
        product_urls = other_urls[: max_pages * 2]
        report.discovery = "sitemap-generic"

    report.candidates = len(product_urls)
    if not product_urls:
        report.stopped = "no_product_urls"
        note("هیچ صفحه‌ی محصولی پیدا نشد")
        return report

    # ---- 3. read product pages ---------------------------------------------
    seen_names: set[tuple[str, int | None]] = set()
    attempts = 0
    for url in product_urls:
        if len(report.products) >= max_pages:
            report.stopped = "max_pages"
            break
        if attempts >= max_pages * 2:
            report.stopped = "attempt_budget"
            break
        if should_stop and should_stop():
            report.stopped = "cancelled"
            break
        if not fetch.allowed(url):
            report.robots_blocked += 1
            continue
        attempts += 1
        try:
            response = fetch.get(url)
        except requests.RequestException as exc:
            report.errors.append(f"{unquote(url)[:120]}: {type(exc).__name__}")
            continue
        report.pages_fetched += 1
        if response is None or response.status_code != 200:
            report.errors.append(f"{unquote(url)[:120]}: HTTP {getattr(response, 'status_code', '?')}")
            continue
        item = extract_product(response.text, response.url or url)
        if item is None:
            report.skipped_no_product += 1
            continue
        key = (item.name, item.price_toman)
        if key in seen_names:
            continue
        seen_names.add(key)
        item.url = unquote(item.url)
        report.products.append(item.as_dict())
        note(f"«{item.name[:40]}»")
    return report
