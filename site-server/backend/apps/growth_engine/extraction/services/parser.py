"""HTML -> findings. Pure functions: no network, no database.

``parse_page(html, url, kind)`` reads ONE page and returns what the page itself shows, each value with
its evidence (where on the page) and a confidence from a fixed, explainable table (``CONF``). Nothing is
inferred beyond that: a number the page does not show is never produced, a link that is only a "share"
button is never a profile.

Confidence tiers (see docs/growth-engine/DESIGN-EXT.md):

    phone     tel: link 90 · JSON-LD 90 · text beside a contact word on a contact/about page 75 ·
              same on another page 65 · bare number in text 50
    email     mailto: 90 · JSON-LD 90 · text on a contact page 80 · elsewhere 65 · «[at]» obfuscation 50
    social    profile link 85 · JSON-LD sameAs 85
    contact_form   form with a message box 85 · ticket/support link 70 · contact page without a form 55 (crawler)
    address   JSON-LD PostalAddress 90 · <address> 80 · text after «آدرس:» 75
    city      JSON-LD addressLocality 80 · a known city inside the found address 65
    business_name   JSON-LD 80 · og:site_name 75 · <title> before « | » 55 (home page only)
    description  meta/og description 60
    language  <html lang> 70
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from apps.growth_engine.core import normalization as nz
from apps.growth_engine.leads.services.drafts import normalize_contact

CONF = {
    "phone_tel": 90, "phone_jsonld": 90, "phone_text_near_contact": 75, "phone_text_near_other": 65, "phone_text_bare": 50,
    "email_mailto": 90, "email_jsonld": 90, "email_text_contact": 80, "email_text_other": 65, "email_obfuscated": 50,
    "social_link": 85, "social_jsonld": 85,
    "form_with_message": 85, "ticket_link": 70, "contact_page_no_form": 55,
    "address_jsonld": 90, "address_tag": 80, "address_label": 75,
    "city_jsonld": 80, "city_in_address": 65,
    "name_jsonld": 80, "name_og": 75, "name_title": 55,
    "description": 60, "language": 70,
}

FORM_LABEL = "فرم تماس"
TICKET_LABEL = "تیکت/پشتیبانی"
CONTACT_PAGE_LABEL = "صفحهٔ تماس (فرمی دیده نشد)"

SINGLE_VALUED = ("business_name", "description", "address", "city", "language")
SOCIAL_FIELDS = ("instagram", "telegram", "whatsapp", "eitaa", "bale", "rubika", "linkedin")
CONTACT_FIELDS = ("phone", "email", *SOCIAL_FIELDS, "contact_form")


@dataclass
class Finding:
    field: str
    value: str
    key: str = ""  # normalised identity (empty for single-valued fields)
    source_url: str = ""
    evidence: str = ""
    confidence: int = 0
    label: str = ""


@dataclass
class Link:
    url: str
    text: str


@dataclass
class PageResult:
    url: str
    kind: str
    findings: list[Finding] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    title: str = ""
    lang: str = ""
    has_contact_form: bool = False
    is_challenge: bool = False
    is_app_shell: bool = False
    text_length: int = 0

    @property
    def contact_page_without_form(self) -> bool:
        return self.kind == "contact" and not self.has_contact_form and not self.is_app_shell and not self.is_challenge


# --------------------------------------------------------------------------- challenge / app shell

_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied", "checking your browser", "در حال بررسی مرورگر", "ddos protection")
_CHALLENGE_MARKERS = ("cf-chl", "__cf_chl", "challenge-platform", "cf-browser-verification", "cf_chl_opt", "cf-turnstile-response", "sucuri.net/privacy")


def looks_like_challenge(html: str, headers: dict | None = None) -> bool:
    """Cloudflare-style interstitial ("Just a moment..."): there is no site content to read behind it."""
    low = (html or "").lower()
    if headers and headers.get("cf-mitigated"):
        return True
    title = re.search(r"<title[^>]*>(.*?)</title>", low, re.S)
    if title and any(t in title.group(1) for t in _CHALLENGE_TITLES):
        return True
    return any(m in low for m in _CHALLENGE_MARKERS)


# --------------------------------------------------------------------------- link classification

_CONTACT_PATHS = {"contact", "contact-us", "contactus", "contact_us", "call", "call-us", "reach-us", "get-in-touch", "tamas", "tamas-ba-ma", "ertebat", "ertebat-ba-ma", "تماس-با-ما", "ارتباط-با-ما", "تماس", "ارتباط"}
_ABOUT_PATHS = {"about", "about-us", "aboutus", "about_us", "who-we-are", "darbare", "darbare-ma", "درباره-ما", "درباره"}
_SUPPORT_PATHS = {"support", "ticket", "tickets", "new-ticket", "help", "helpdesk", "پشتیبانی", "تیکت"}
_CONTACT_TEXT_FA = ("تماس با ما", "تماس", "ارتباط با ما", "ارتباط")
_ABOUT_TEXT_FA = ("درباره ما", "درباره", "معرفی")
_SUPPORT_TEXT_FA = ("پشتیبانی", "تیکت", "ارسال درخواست")
#: English menu labels must be the WHOLE link text ("Contact lens case" is a product, not the contact page)
_CONTACT_TEXT_EN = re.compile(r"(contact|contact us|contact page|get in touch|reach us|call us)", re.I)
_ABOUT_TEXT_EN = re.compile(r"(about|about us|who we are|our story)", re.I)
_SUPPORT_TEXT_EN = re.compile(r"(support|customer support|help|help center|help desk|helpdesk|tickets?|submit a ticket|my tickets)", re.I)
_MENU_TEXT_MAX = 24
_SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".rar", ".doc", ".docx", ".xls", ".xlsx", ".mp4", ".mp3", ".css", ".js", ".xml", ".ico")


def _path_segments(url: str) -> list[str]:
    return [unquote(s).lower() for s in urlsplit(url).path.split("/") if s]


def classify_link(url: str, text: str) -> tuple[str, int] | None:
    """('contact' | 'about' | 'support', score) for a link that looks like such a page, else None.

    Text carries 60 points, an exact path segment 40. Path matching is by whole segment so
    ``/products/contact-lens`` is not a contact page."""
    segments = _path_segments(url)
    text = nz.normalize_text(text)
    plain = re.sub(r"[^\w\s]", " ", text)  # drop arrows, bullets, punctuation
    plain = re.sub(r"\s+", " ", plain).strip()
    menu_sized = 0 < len(plain) <= _MENU_TEXT_MAX
    scores = {"contact": 0, "about": 0, "support": 0}
    if menu_sized and (any(w in plain for w in _CONTACT_TEXT_FA) or _CONTACT_TEXT_EN.fullmatch(plain)):
        scores["contact"] += 60
    if menu_sized and (any(w in plain for w in _ABOUT_TEXT_FA) or _ABOUT_TEXT_EN.fullmatch(plain)):
        scores["about"] += 60
    if menu_sized and (any(w in plain for w in _SUPPORT_TEXT_FA) or _SUPPORT_TEXT_EN.fullmatch(plain)):
        scores["support"] += 60
    if any(s in _CONTACT_PATHS for s in segments):
        scores["contact"] += 40
    if any(s in _ABOUT_PATHS for s in segments):
        scores["about"] += 40
    if any(s in _SUPPORT_PATHS for s in segments):
        scores["support"] += 40
    best = max(scores, key=lambda k: (scores[k], -("contact", "about", "support").index(k)))
    return (best, scores[best]) if scores[best] else None


def contact_form_key(url: str) -> str:
    """Identity of a contact-form page: its whole canonical URL (``shop.ir/contact`` and ``shop.ir/support`` differ)."""
    return nz.clean_url(url).url


def same_host(a: str, b: str) -> bool:
    def key(u: str) -> str:
        host = (urlsplit(u).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host

    return key(a) == key(b) and bool(key(a))


def _usable_href(href: str) -> bool:
    low = href.strip().lower()
    if not low or low.startswith(("#", "mailto:", "tel:", "javascript:", "sms:", "data:", "whatsapp:", "tg:")):
        return False
    return not urlsplit(low).path.endswith(_SKIP_EXTENSIONS)


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]


# --------------------------------------------------------------------------- social links

_WA_HOSTS = {"wa.me", "api.whatsapp.com", "web.whatsapp.com", "whatsapp.com", "chat.whatsapp.com"}
_IG_HOSTS = {"instagram.com", "instagr.am"}
_TG_HOSTS = {"t.me", "telegram.me", "telegram.dog"}
_LINKEDIN_OK = {"company", "in", "showcase", "school"}


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify_social(href: str) -> tuple[str, str, str] | None:
    """(field, value, key) when ``href`` is a profile link of a platform we collect; None for share /
    intent / post links and anything else. Never raises."""
    href = (href or "").strip()
    if not re.match(r"^https?://", href, re.I):
        return None
    host = _host(href)
    parts = urlsplit(href)
    segments = [s for s in parts.path.split("/") if s]
    try:
        if host in _IG_HOSTS:
            kind = "instagram"
            value, key = normalize_contact(kind, href)
        elif host in _TG_HOSTS:
            kind = "telegram"
            value, key = normalize_contact(kind, href)
        elif host == "eitaa.com":
            kind = "eitaa"
            value, key = normalize_contact(kind, href)
        elif host in ("ble.ir", "bale.ai"):
            kind = "bale"
            value, key = normalize_contact(kind, href)
        elif host == "rubika.ir":
            kind = "rubika"
            value, key = normalize_contact(kind, href)
        elif host == "linkedin.com":
            if len(segments) < 2 or segments[0].lower() not in _LINKEDIN_OK:
                return None
            kind = "linkedin"
            value, key = normalize_contact(kind, f"https://www.linkedin.com/{segments[0].lower()}/{segments[1]}")
        elif host in _WA_HOSTS:
            number = ""
            if host == "wa.me" and segments and re.fullmatch(r"\+?\d{8,15}", segments[0]):
                number = segments[0]
            elif host in ("api.whatsapp.com", "web.whatsapp.com", "whatsapp.com"):
                match = re.search(r"[?&]phone=\+?(\d{8,15})", href)
                number = match.group(1) if match else ""
            if not number:
                return None  # wa.me/?text=..., wa.me/message/..., group invites: no number shown
            kind = "whatsapp"
            value, key = normalize_contact(kind, "+" + number.lstrip("+"))
        else:
            return None
    except nz.NormalizationError:
        return None
    return kind, value, key


# --------------------------------------------------------------------------- text patterns

_PHONE_WORD_RE = re.compile(r"تلفن|تماس|موبایل|همراه|شماره|واتس|\b(?:phone|tel|telephone|mobile|call|cell|whatsapp|contact)\b", re.I)
_FAX_RE = re.compile(r"فکس|نمابر|\bfax\b", re.I)
_PHONE_CANDIDATE_RE = re.compile(r"(?<![\d])(\+?\(?\d(?:[\s\-.()]{0,2}\d){6,14})(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_OBFUSCATED_EMAIL_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*[\[\(\{]\s*at\s*[\]\)\}]\s*([A-Za-z0-9\-]+(?:\s*(?:[\[\(\{]\s*dot\s*[\]\)\}]|\.)\s*[A-Za-z0-9\-]+)+)", re.I
)
_FILE_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico", "woff", "woff2", "ttf", "pdf"}
_NO_REPLY = re.compile(r"^(no-?reply|do-?not-?reply|donotreply|mailer-daemon)$", re.I)
_ADDRESS_LABEL = r"(?:آدرس|ادرس|نشانی|address)"
_ADDRESS_LINE_RE = re.compile(rf"^\s*{_ADDRESS_LABEL}\s*[:：\-–]\s*(.{{8,}})$", re.I)
_ADDRESS_ALONE_RE = re.compile(rf"^\s*{_ADDRESS_LABEL}\s*[:：]?\s*$", re.I)

KNOWN_CITIES = [
    "تهران", "مشهد", "اصفهان", "شیراز", "تبریز", "کرج", "قم", "اهواز", "کرمانشاه", "ارومیه", "رشت", "زاهدان", "کرمان", "همدان", "یزد",
    "اردبیل", "بندرعباس", "اراک", "زنجان", "سنندج", "قزوین", "خرم‌آباد", "گرگان", "ساری", "بجنورد", "بیرجند", "ایلام", "شهرکرد", "بوشهر",
    "یاسوج", "سمنان", "کیش", "قشم", "رفسنجان", "سیرجان", "دزفول", "آبادان", "خرمشهر", "بابل", "آمل", "نیشابور", "سبزوار", "کاشان",
    "نجف‌آباد", "شاهرود", "ملایر", "مراغه", "خوی", "میانه", "بروجرد", "ورامین", "اسلامشهر", "پردیس", "شهریار", "ساوه", "لاهیجان",
    "بندر انزلی", "چالوس", "رامسر", "ماهشهر", "بم", "طبس", "اردکان", "کاشمر", "قائم‌شهر", "بهبهان", "گنبد کاووس",
]
_PERSIAN_LETTER = "ء-غف-يپچژکگی"  # letters only: the Arabic comma « ، » is not a letter
#: how a one-word canonical name may be written as two words (the pattern allows a space, a ZWNJ or nothing between them)
_CITY_SPLITS = {
    "بندرعباس": "بندر عباس", "خرم‌آباد": "خرم آباد", "شهرکرد": "شهر کرد", "نجف‌آباد": "نجف آباد", "قائم‌شهر": "قائم شهر",
    "اسلامشهر": "اسلام شهر", "رباط‌کریم": "رباط کریم",
}


def _city_pattern(name: str) -> re.Pattern:
    words = [re.escape(w) for w in _CITY_SPLITS.get(name, name).replace("‌", " ").split()]  # «بندر عباس» == «بندرعباس» == «بندر‌عباس»
    return re.compile(rf"(?<![{_PERSIAN_LETTER}])" + r"\s?".join(words) + rf"(?![{_PERSIAN_LETTER}])")


_CITY_PATTERNS = [(name, _city_pattern(name)) for name in KNOWN_CITIES]
_GENERIC_NAMES = {"home", "homepage", "welcome", "index", "صفحه اصلی", "صفحهٔ اصلی", "خانه", "خوش آمدید", "فروشگاه", "سایت", "untitled", "document"}
_ORG_TYPE_HINTS = ("organization", "business", "store", "shop", "corporation", "company", "service")


def _norm_digits(text: str) -> str:
    return nz.to_ascii_digits(text)


def find_known_cities(address: str) -> list[str]:
    """Distinct known city names that appear in ``address`` (whole-word, ZWNJ-insensitive)."""
    text = nz.normalize_text(address).replace("‌", " ")
    return [name for name, pattern in _CITY_PATTERNS if pattern.search(text)]


# --------------------------------------------------------------------------- JSON-LD


def _flatten_jsonld(node) -> list[dict]:
    out: list[dict] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_flatten_jsonld(item))
    elif isinstance(node, dict):
        out.append(node)
        for key in ("@graph", "mainEntity", "publisher", "provider", "parentOrganization"):
            if key in node:
                out.extend(_flatten_jsonld(node[key]))
    return out


def _jsonld_nodes(soup) -> list[dict]:
    nodes: list[dict] = []
    for script in soup.find_all("script"):
        if "ld+json" not in (script.get("type") or "").lower():
            continue
        raw = script.string or script.get_text() or ""
        try:
            nodes.extend(_flatten_jsonld(json.loads(raw)))
        except (ValueError, TypeError):
            continue
    return nodes


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _is_org(node: dict) -> bool:
    types = " ".join(str(t).lower() for t in _as_list(node.get("@type")))
    return any(h in types for h in _ORG_TYPE_HINTS)


def _is_website(node: dict) -> bool:
    return "website" in " ".join(str(t).lower() for t in _as_list(node.get("@type")))


def _address_text(address) -> tuple[str, str]:
    """(full address text, locality) from a JSON-LD address (dict or plain string)."""
    if isinstance(address, str):
        return nz.normalize_text(address), ""
    if not isinstance(address, dict):
        return "", ""
    parts = [nz.normalize_text(str(address.get(k) or "")) for k in ("streetAddress", "addressLocality", "addressRegion")]
    return "، ".join(p for p in parts if p), nz.normalize_text(str(address.get("addressLocality") or ""))


# --------------------------------------------------------------------------- the page parser


class _Collector:
    """Keeps the best finding per (field, key) while a page is parsed."""

    def __init__(self, url: str):
        self.url = url
        self.items: dict[tuple[str, str], Finding] = {}

    def add(self, finding: Finding) -> None:
        finding.source_url = self.url
        identity = (finding.field, finding.key or ("" if finding.field in SINGLE_VALUED else finding.value))
        best = self.items.get(identity)
        if best is None or finding.confidence > best.confidence:
            self.items[identity] = finding

    def contact(self, field_name: str, raw: str, confidence: int, evidence: str, label: str = "") -> None:
        kind = "phone" if field_name == "whatsapp_number" else field_name
        try:
            value, key = normalize_contact(kind, raw)
        except nz.NormalizationError:
            return
        if kind == "email":
            local, _, domain = value.partition("@")
            if nz.is_placeholder_email(value) or domain.rsplit(".", 1)[-1] in _FILE_TLDS or _NO_REPLY.match(local):
                return
        self.add(Finding(field=field_name, value=value, key=key, evidence=evidence, confidence=confidence, label=label))


def parse_page(html: str, url: str, kind: str = "home") -> PageResult:
    """Everything one page shows. ``kind`` is home / contact / about / support (the crawler decides)."""
    soup = BeautifulSoup(html or "", "html.parser")
    result = PageResult(url=url, kind=kind)
    out = _Collector(url)
    jsonld = _jsonld_nodes(soup)
    page_is_contactish = kind in ("contact", "about")

    # ---- links (collected before scripts are dropped)
    anchors = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = nz.normalize_text(a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or "")
        anchors.append((href, text))
        if _usable_href(href):
            result.links.append(Link(url=_strip_fragment(urljoin(url, href)), text=text))

    # ---- tel: / mailto: / social profile links / ticket-support links
    for href, text in anchors:
        low = href.lower()
        if low.startswith("tel:"):
            number = unquote(href[4:]).split(";")[0]
            out.contact("phone", number, CONF["phone_tel"], "لینک tel:")
        elif low.startswith("mailto:"):
            out.contact("email", unquote(href[7:]), CONF["email_mailto"], "لینک mailto:")
        else:
            absolute = urljoin(url, href)
            social = classify_social(absolute)
            if social:
                out.add(Finding(field=social[0], value=social[1], key=social[2], evidence="لینک پروفایل در صفحه", confidence=CONF["social_link"]))
            elif _usable_href(href) and same_host(url, absolute):
                classified = classify_link(absolute, text)
                if classified and classified[0] == "support" and _strip_fragment(absolute).rstrip("/") != url.rstrip("/"):
                    try:
                        value = key = contact_form_key(absolute)
                    except nz.NormalizationError:
                        continue
                    out.add(Finding(field="contact_form", value=value, key=key, label=TICKET_LABEL, confidence=CONF["ticket_link"], evidence=f"لینک «{text[:40] or 'پشتیبانی'}»"))

    # ---- JSON-LD
    for node in jsonld:
        if _is_website(node):  # a WebSite node names the site: as trusted as og:site_name, less than an organisation
            site_name = nz.normalize_text(str(node.get("name") or ""))
            if 2 <= len(site_name) <= 200 and site_name.casefold() not in _GENERIC_NAMES:
                out.add(Finding(field="business_name", value=site_name, evidence="JSON-LD WebSite", confidence=CONF["name_og"]))
        if not _is_org(node) and not any(k in node for k in ("telephone", "email", "address")):
            continue
        contact_points = [c for c in _as_list(node.get("contactPoint")) if isinstance(c, dict)]
        for source in [node, *contact_points]:
            for number in _as_list(source.get("telephone")):
                out.contact("phone", str(number), CONF["phone_jsonld"], "داده‌های ساختاریافته (JSON-LD)")
            for mail in _as_list(source.get("email")):
                out.contact("email", str(mail), CONF["email_jsonld"], "داده‌های ساختاریافته (JSON-LD)")
        for same_as in _as_list(node.get("sameAs")):
            social = classify_social(str(same_as))
            if social:
                out.add(Finding(field=social[0], value=social[1], key=social[2], evidence="JSON-LD sameAs", confidence=CONF["social_jsonld"]))
        address_text, locality = _address_text(node.get("address"))
        if address_text:
            out.add(Finding(field="address", value=address_text[:300], evidence="داده‌های ساختاریافته (JSON-LD)", confidence=CONF["address_jsonld"]))
        if locality:
            out.add(Finding(field="city", value=locality[:100], evidence="JSON-LD addressLocality", confidence=CONF["city_jsonld"]))
        name = nz.normalize_text(str(node.get("name") or ""))
        if _is_org(node) and 2 <= len(name) <= 200 and name.casefold() not in _GENERIC_NAMES:
            out.add(Finding(field="business_name", value=name, evidence="داده‌های ساختاریافته (JSON-LD)", confidence=CONF["name_jsonld"]))

    # ---- contact forms: a <form> with a message box (not a comment / search / login form)
    for form in soup.find_all("form"):
        if _is_contact_form(form):
            result.has_contact_form = True
            try:
                value = key = contact_form_key(url)
            except nz.NormalizationError:
                break
            out.add(Finding(field="contact_form", value=value, key=key, label=FORM_LABEL, confidence=CONF["form_with_message"], evidence="فرمی با جعبهٔ پیام در همین صفحه"))
            break

    # ---- <address> tags (read before the text clean-up)
    for tag in soup.find_all("address"):
        text = nz.normalize_text(tag.get_text(" ", strip=True))
        if _plausible_address(text):
            out.add(Finding(field="address", value=text[:300], evidence="برچسب <address>", confidence=CONF["address_tag"]))
            break

    # ---- meta / title / language
    title_tag = soup.find("title")
    result.title = nz.normalize_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
    html_tag = soup.find("html")
    lang = (html_tag.get("lang") or "").strip().lower().split("-")[0] if html_tag else ""
    if re.fullmatch(r"[a-z]{2,3}", lang):
        result.lang = lang
        out.add(Finding(field="language", value=lang, evidence="ویژگی lang در <html>", confidence=CONF["language"]))
    og_name = _meta(soup, "property", "og:site_name")
    if 2 <= len(og_name) <= 200 and og_name.casefold() not in _GENERIC_NAMES:
        out.add(Finding(field="business_name", value=og_name, evidence="og:site_name", confidence=CONF["name_og"]))
    if kind == "home" and result.title:
        first = re.split(r"\s+[|–—:·»]\s+|\s+-\s+|\s*\|\s*", result.title)[0].strip()
        if 2 <= len(first) <= 80 and first.casefold() not in _GENERIC_NAMES:
            out.add(Finding(field="business_name", value=first, evidence="عنوان صفحه (<title>)", confidence=CONF["name_title"]))
    description = _meta(soup, "name", "description") or _meta(soup, "property", "og:description")
    if len(description) >= 20:
        out.add(Finding(field="description", value=description[:500], evidence="meta description", confidence=CONF["description"]))

    # ---- visible text: phones, e-mails, labelled addresses
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    result.text_length = sum(len(ln) for ln in lines)
    result.is_challenge = looks_like_challenge(html)
    result.is_app_shell = (not result.is_challenge) and result.text_length < 60 and not result.has_contact_form and not result.links
    if not result.is_challenge:
        _scan_phones(lines, kind, page_is_contactish, out)
        _scan_emails(lines, kind, out)
        _scan_addresses(lines, out)

    # ---- a city that the found address names (exactly one)
    address_finding = out.items.get(("address", ""))
    if address_finding and ("city", "") not in out.items:
        cities = find_known_cities(address_finding.value)
        if len(cities) == 1:
            out.add(Finding(field="city", value=cities[0], evidence="نامِ شهر در نشانیِ پیداشده", confidence=CONF["city_in_address"]))

    result.findings = list(out.items.values())
    return result


# --------------------------------------------------------------------------- helpers of parse_page


def _meta(soup, attr: str, name: str) -> str:
    tag = soup.find("meta", attrs={attr: name})
    return nz.normalize_text(tag.get("content") or "") if tag else ""


def _is_contact_form(form) -> bool:
    if not form.find("textarea"):
        return False
    if form.find("input", attrs={"type": re.compile("^password$", re.I)}):
        return False
    marker = " ".join(str(form.get(a) or "") for a in ("id", "class", "action", "role", "name")).lower()
    if any(w in marker for w in ("search", "comment", "respond", "login", "signin", "register", "wp-comments-post", "newsletter", "subscribe", "review")):
        return False
    return True


def _plausible_address(text: str) -> bool:
    return 8 <= len(text) and bool(re.search(r"[؀-ۿA-Za-z]{3}", text))


def _scan_phones(lines: list[str], kind: str, contactish: bool, out: _Collector) -> None:
    for index, raw_line in enumerate(lines):
        line = _norm_digits(raw_line)
        if _FAX_RE.search(line):
            continue
        previous = _norm_digits(lines[index - 1]) if index else ""
        near = bool(_PHONE_WORD_RE.search(line)) or (len(previous) <= 40 and bool(_PHONE_WORD_RE.search(previous)) and not _FAX_RE.search(previous))
        for match in _PHONE_CANDIDATE_RE.finditer(line):
            candidate = match.group(1).strip()
            compact = re.sub(r"[^\d+]", "", candidate)
            if not (compact.startswith("0") or compact.startswith("+")):
                continue  # an explicit leading 0 or + is required in running text: dates, prices and codes are not numbers
            if near:
                confidence = CONF["phone_text_near_contact"] if contactish else CONF["phone_text_near_other"]
                evidence = "کنار کلمهٔ تماس/تلفن در متن"
            else:
                confidence = CONF["phone_text_bare"]
                evidence = "عددی شبیه شماره در متنِ صفحه"
            out.contact("phone", candidate, confidence, evidence)


def _scan_emails(lines: list[str], kind: str, out: _Collector) -> None:
    text = "\n".join(lines)
    for match in _EMAIL_RE.finditer(text):
        confidence = CONF["email_text_contact"] if kind == "contact" else CONF["email_text_other"]
        out.contact("email", match.group(0), confidence, "نوشته‌شده در متنِ صفحه")
    for match in _OBFUSCATED_EMAIL_RE.finditer(text):
        domain = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", match.group(2), flags=re.I)
        domain = re.sub(r"\s+", "", domain)
        out.contact("email", f"{match.group(1)}@{domain}", CONF["email_obfuscated"], "نوشته‌شده با [at]/[dot]")


def _scan_addresses(lines: list[str], out: _Collector) -> None:
    for index, line in enumerate(lines):
        match = _ADDRESS_LINE_RE.match(line)
        value = ""
        if match:
            value = match.group(1)
        elif _ADDRESS_ALONE_RE.match(line) and index + 1 < len(lines):
            value = lines[index + 1]
        value = nz.normalize_text(value)
        if _plausible_address(value) and not _EMAIL_RE.fullmatch(value):
            out.add(Finding(field="address", value=value[:300], evidence="متنِ بعد از «آدرس:»", confidence=CONF["address_label"]))
            return
