"""Which contact values are really a BUSINESS's own? (pure functions)

The finder keeps only public business contact details. A web page is full of other people's: a blog commenter's e-mail, a customer's number in
a testimonial, the web agency that built the site, the example number a template ships with. The rules here keep the first kind and drop the
rest, and they are the same for every source:

* **placeholders** - «09123456789», «09121234567», «09111111111», «۰۹۱۲۰۰۰۰۰۰۰»: a run of six or more equal or consecutive digits is a filler, not a line;
* **free-mail addresses** (gmail, yahoo, hotmail ...) are a private person's by default. They are kept only when the page ITSELF presents them as
  its contact (a ``mailto:`` link, JSON-LD, or text on a contact page) and the local part does not look like a developer / agency account;
* an address on **another company's domain** is kept only with the same strong evidence (a ``mailto:``/JSON-LD/contact-page line), never from running text;
* **credits** («طراحی و توسعه توسط ...», «Designed by ...», «Powered by ...») are cut out of the page before anything is read from it;
* a **template's** number: a ``tel:`` link whose visible text is another number than the link's («0912000000» shown, ``+989134716857`` dialled) is the
  site template's demo line - it is dropped with the credits;
* an Instagram / Telegram **placeholder** («instagram.com/0», «t.me/test», «t.me/09385824083») is not a page;
* a site gives at most ``MAX_SITE_MOBILES`` mobile numbers and ``MAX_SITE_LANDLINES`` landlines (a page that lists ten numbers lists customers, not a business);
* a directory's own footer values and its own social handle are never a listed business's.

``evidence`` strings are the parser's (``CONF`` table of ``extraction.services.parser``): mailto / tel / JSON-LD = 90, contact-page text 75-80,
other text 65 and below.
"""
from __future__ import annotations

import re

from apps.growth_engine.core import normalization as nz

FREE_MAIL = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com", "icloud.com", "me.com",
    "aol.com", "mail.com", "gmx.com", "proton.me", "protonmail.com", "yandex.com", "yandex.ru", "mail.ru", "zoho.com", "chmail.ir", "iran.ir",
})
MAX_SITE_MOBILES = 3
MAX_SITE_LANDLINES = 2
#: confidence thresholds (parser CONF): 90 = mailto / tel / JSON-LD, 75-80 = text beside a contact word on a contact page
STRONG = 80
TEXT_PHONE = 75
TEXT_SAME_DOMAIN_EMAIL = 65

_DEV_LOCAL = re.compile(r"(?:dev|developer|design|designer|webdesign|webmaster|seo|hosting|programmer|coder|agency|softwar|webservice)", re.I)
_DOMAIN_IN_LOCAL = re.compile(r"\.(?:ir|com|net|org|co|app|dev|io)$", re.I)
_CREDIT = re.compile(
    r"(?:طراحی|طراح|توسعه|ساخته\s*شده|پیاده\s*سازی|پیاده‌سازی|برنامه\s*نویسی|برنامه‌نویسی|سئو|پشتیبانی\s*(?:و|،)?\s*(?:طراحی|توسعه))\s*(?:و\s*(?:توسعه|طراحی|پشتیبانی)\s*)?(?:وب\s*سایت|وب‌سایت|سایت)?\s*(?:توسط|by|:|-|–|—)"
    r"|(?:طراحی\s*و\s*توسعه|طراحی\s*سایت|طراحی\s*وب|توسعه\s*وب|powered\s+by|designed\s+by|developed\s+by|created\s+by|made\s+by|built\s+by|site\s+by|web\s*design\s+by|theme\s+by|crafted\s+by|ساخت\s*سایت)",
    re.I,
)


# --------------------------------------------------------------------------- phones


def is_mobile(value: str) -> bool:
    try:
        return nz.normalize_phone(value).kind == "mobile"
    except nz.NormalizationError:
        return False


def is_placeholder_phone(value: str) -> bool:
    """A number a template or a lazy form filler would type: «09123456789», «09121234567», «09111111111», «09120000000»."""
    digits = re.sub(r"\D", "", nz.to_ascii_digits(str(value or "")))
    if digits.startswith("98") and len(digits) >= 12:
        digits = "0" + digits[2:]
    if not digits:
        return False
    body = digits[1:] if digits.startswith("0") else digits
    if re.search(r"(\d)\1{5,}", body):
        return True
    for i in range(len(body) - 5):
        window = body[i:i + 6]
        steps = {int(window[j + 1]) - int(window[j]) for j in range(5)}
        if steps in ({1}, {-1}):
            return True
    return False


# --------------------------------------------------------------------------- e-mails


def email_domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


def is_free_mail(address: str) -> bool:
    return email_domain(address) in FREE_MAIL


def looks_like_agency_mail(address: str) -> bool:
    """A free-mail address of a web developer / agency («vanadiumdev.ir@gmail.com»): its local part names a service or a domain."""
    local = address.split("@", 1)[0].lower()
    return bool(_DEV_LOCAL.search(local) or _DOMAIN_IN_LOCAL.search(local))


def _registrable(host: str) -> str:
    host = (host or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov", "sch") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_site_domain(address: str, site_host: str) -> bool:
    return bool(site_host) and _registrable(email_domain(address)) == _registrable(site_host)


def email_ok(address: str, confidence: int, site_host: str = "") -> bool:
    """Is this e-mail, found on a business's site with this parser confidence, the business's own?"""
    if looks_like_agency_mail(address) and is_free_mail(address):
        return False
    if is_free_mail(address):
        return confidence >= STRONG
    if site_host and same_site_domain(address, site_host):
        return confidence >= TEXT_SAME_DOMAIN_EMAIL
    return confidence >= STRONG


def phone_ok(value: str, confidence: int) -> bool:
    """A number read from a site's text: not a filler, and shown as contact (tel: link / JSON-LD 90, text beside a contact word on a contact page 75)."""
    return not is_placeholder_phone(value) and confidence >= TEXT_PHONE


def cap_phones(items: list[tuple[str, int]], is_mobile) -> list[str]:
    """Keep the best ``MAX_SITE_MOBILES`` mobiles and ``MAX_SITE_LANDLINES`` landlines of ``[(number, confidence), ...]``."""
    mobiles, lines = [], []
    for number, conf in sorted(items, key=lambda x: -x[1]):
        if is_placeholder_phone(number):
            continue
        bucket = mobiles if is_mobile(number) else lines
        limit = MAX_SITE_MOBILES if bucket is mobiles else MAX_SITE_LANDLINES
        if len(bucket) < limit and number not in bucket:
            bucket.append(number)
    return [*mobiles, *lines]


# --------------------------------------------------------------------------- credits


def drop_template_tels(soup) -> None:
    """Remove ``<a href="tel:A">B</a>`` where the visible text is a number (7+ digits) that is not the dialled one: a site template's demo line."""
    for a in soup.find_all("a", href=True):
        if not a["href"].strip().lower().startswith("tel:"):
            continue
        shown = re.sub(r"\D", "", nz.to_ascii_digits(a.get_text(" ", strip=True)))
        dialled = re.sub(r"\D", "", nz.to_ascii_digits(a["href"]))
        if len(shown) >= 7 and len(dialled) >= 7 and shown[-9:] != dialled[-9:]:
            a.decompose()


def drop_credits(html: str) -> str:
    """The page without its «designed by ...» credit lines, so a developer's e-mail / number there is never read as the business's.

    Smallest elements first: a credit inside a footer that also holds the business's own phone removes only the credit."""
    from bs4 import BeautifulSoup

    if not html:
        return ""
    has_credit, has_tel = bool(_CREDIT.search(html)), "tel:" in html.lower()
    if not has_credit and not has_tel:
        return html
    soup = BeautifulSoup(html, "html.parser")
    if has_tel:
        drop_template_tels(soup)
    if not has_credit:
        return str(soup)
    found = []
    for tag in soup.find_all(["p", "div", "span", "li", "a", "small", "footer", "section", "td"]):
        text = tag.get_text(" ", strip=True)
        if text and len(text) <= 240 and _CREDIT.search(text):
            found.append((len(list(tag.parents)), tag))
    for _, tag in sorted(found, key=lambda x: -x[0]):
        if getattr(tag, "decomposed", False):
            continue
        if _CREDIT.search(tag.get_text(" ", strip=True)):
            tag.decompose()
    return str(soup)


# --------------------------------------------------------------------------- social handles

PLACEHOLDER_HANDLES = frozenset({
    "test", "tester", "username", "user", "example", "sample", "demo", "yourname", "yourusername", "your_username", "your_id", "yourid", "name", "handle",
    "admin", "instagram", "telegram", "page", "profile", "channel", "id", "null", "none", "undefined", "xxxx", "abcd",
})
_TG_HANDLE = re.compile(r"[a-z][a-z0-9_]{4,31}")


def handle_of(value: str) -> str:
    return (value or "").strip().split("?")[0].rstrip("/").rsplit("/", 1)[-1].lstrip("@").lower()


def is_placeholder_handle(value: str, kind: str = "instagram") -> bool:
    """«instagram.com/0», «t.me/test», «t.me/09385824083»: a link that points at nothing a business owns. Empty -> False (nothing to judge)."""
    h = handle_of(value)
    if not h:
        return False
    if h in PLACEHOLDER_HANDLES or h.isdigit() or len(h) < 2:
        return True
    return kind == "telegram" and not _TG_HANDLE.fullmatch(h)


# --------------------------------------------------------------------------- a directory's own values


def own_handle(handle: str, directory_host: str) -> bool:
    """«badanfitir» is the handle of badanfit.ir itself: the handle starts with (or equals) the directory's own name."""
    h = re.sub(r"[^a-z0-9]", "", (handle or "").lower().lstrip("@"))
    name = re.sub(r"[^a-z0-9]", "", _registrable(directory_host).split(".")[0])
    return bool(h and name and len(name) >= 4 and (h.startswith(name) or name.startswith(h) and len(h) >= 5))


def own_social(value: str, directory_host: str) -> bool:
    """``https://www.instagram.com/badanfitir/`` / ``@badanfitir`` / ``t.me/xyz`` is the directory's own page?"""
    handle = (value or "").strip().rstrip("/").rsplit("/", 1)[-1].lstrip("@")
    return own_handle(handle, directory_host)
