"""Pure normalisation helpers for the Growth Engine (no Django, no I/O).

Everything that decides "are these two leads the same business?" goes through
this file, so the rules live in exactly one place and are testable without a
database.

Identity keys produced here (stored in ``ContactPoint.normalized``):

* website   -> the host without ``www.`` as punycode (``shop.ir``); for platforms
               where many businesses share one host (instagram, linktree, t.me,
               marketplaces) the key is ``host/path`` instead.
* instagram -> the lower-cased handle (``myshop``) from ANY url form or ``@handle``.
* phone     -> Iranian national form ``09121234567`` / ``02112345678``; foreign
               numbers ``+442071234567``.
* email     -> lower-cased address, domain as punycode.

Nothing here invents data. A value that cannot be normalised raises
``NormalizationError`` with a stable ``code`` and a Persian ``message``; callers
turn that into a row-level error.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

# --------------------------------------------------------------------------- errors


class NormalizationError(ValueError):
    """A value that cannot be turned into a clean identifier."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- text

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = str.maketrans(
    {**{c: str(i) for i, c in enumerate(_FA_DIGITS)}, **{c: str(i) for i, c in enumerate(_AR_DIGITS)}}
)
# Arabic letters that look like Persian ones but are different code points.
_LETTER_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا"})
_INVISIBLE = re.compile("[‎‏‪-‮⁦-⁩﻿­⁠]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t  -   　]+")
_KEY_STRIP = re.compile(r"[\s‌\-_.,،؛;:!?\"'()\[\]{}<>/\\|*+=~`@#$%^&]+")


def to_ascii_digits(value: str | None) -> str:
    """Persian / Arabic-Indic digits -> ASCII digits."""
    return (value or "").translate(_DIGIT_MAP)


def normalize_text(value: str | None, *, multiline: bool = False) -> str:
    """Clean a free-text value for storage: Persian letters, no invisible marks,
    collapsed whitespace. Keeps the ZWNJ (it is meaningful in Persian) and keeps
    the letters/digits the user typed."""
    text = unicodedata.normalize("NFC", value or "")
    text = _INVISIBLE.sub("", text).translate(_LETTER_MAP)
    text = _CONTROL.sub("", text)
    if multiline:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    text = text.replace("\r", " ").replace("\n", " ")
    return _SPACES.sub(" ", text).strip()


def search_key(value: str | None) -> str:
    """Aggressive key for searching / matching names: ASCII digits, Persian
    letters, lower-case, and no spaces / ZWNJ / punctuation at all, so
    «کسب‌وکار» == «کسب و کار» and «Blue Shop» == «blueshop»."""
    text = normalize_text(to_ascii_digits(value)).casefold()
    return _KEY_STRIP.sub("", text)


def split_multi(value: str | list | tuple | None) -> list[str]:
    """Split a cell holding several values (``a | b ; c ، d`` or a list)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            parts.extend(split_multi(item))
        return parts
    pieces = re.split(r"[|;؛,،\n\r]+", str(value))
    return [p.strip() for p in pieces if p and p.strip()]


# --------------------------------------------------------------------------- urls

#: query parameters that only track where a click came from
TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "dclid", "gbraid", "wbraid", "yclid", "msclkid", "igshid", "igsh", "mc_cid", "mc_eid",
        "_hsenc", "_hsmi", "mkt_tok", "ref_src", "ref_url", "spm", "s_cid", "oly_enc_id", "oly_anon_id",
    }
)

#: hosts where one host carries MANY businesses, so the path is part of the identity
SHARED_PLATFORM_DOMAINS = frozenset(
    {
        "instagram.com", "instagr.am", "facebook.com", "fb.com", "fb.me", "twitter.com", "x.com", "youtube.com",
        "youtu.be", "linkedin.com", "pinterest.com", "tiktok.com", "t.me", "telegram.me", "telegram.dog", "wa.me",
        "whatsapp.com", "linktr.ee", "linkpop.com", "bio.link", "beacons.ai", "eitaa.com", "ble.ir", "bale.ai",
        "rubika.ir", "aparat.com", "digikala.com", "torob.com", "divar.ir", "sheypoor.com", "basalam.com",
        "emalls.ir", "github.io", "blogspot.com", "wordpress.com", "blogfa.com", "blog.ir", "rozblog.com",
        "mihanblog.com", "wixsite.com", "sites.google.com", "business.site", "carrd.co", "taplink.cc",
    }
)

_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


@dataclass(frozen=True)
class CleanUrl:
    url: str  # canonical display URL (unicode host, no tracking, no fragment)
    host: str  # unicode host without a leading www.
    host_ascii: str  # punycode host without a leading www. (identity)
    path: str  # path without trailing slash ("" for the root)
    identity: str  # dedupe key: host or host/path for shared platforms
    scheme: str

    @property
    def fetch_url(self) -> str:
        """ASCII-only form of the URL, safe for an HTTP client."""
        return to_ascii_url(self.url)


def _is_shared_platform(host_ascii: str) -> bool:
    return any(host_ascii == d or host_ascii.endswith("." + d) for d in SHARED_PLATFORM_DOMAINS)


def _idna_host(host: str) -> str:
    try:
        return host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:  # label too long, bad characters ...
        raise NormalizationError("invalid_url", "نام دامنه معتبر نیست.") from exc


def _validate_host(host_ascii: str) -> None:
    if not host_ascii or len(host_ascii) > 253:
        raise NormalizationError("invalid_url", "نام دامنه معتبر نیست.")
    try:
        ip_address(host_ascii.strip("[]"))
        return
    except ValueError:
        pass
    labels = host_ascii.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels):
        raise NormalizationError("invalid_url", "نام دامنه معتبر نیست (باید مثل shop.ir باشد).")
    if labels[-1].isdigit():
        raise NormalizationError("invalid_url", "نام دامنه معتبر نیست.")


def clean_url(raw: str | None) -> CleanUrl:
    """Normalise a website URL. See the module docstring for the rules."""
    text = normalize_text(raw)
    text = text.strip("\"'<>«»()[]")
    if not text:
        raise NormalizationError("empty_url", "آدرس خالی است.")
    if re.search(r"\s", text):
        raise NormalizationError("invalid_url", "آدرس نباید فاصله داشته باشد.")
    match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):(.*)$", text)
    if match and not re.match(r"^[a-zA-Z0-9.-]+:\d+(/|$)", text):  # "host:8080" is not a scheme
        scheme = match.group(1).lower()
        if scheme not in ("http", "https"):
            raise NormalizationError("invalid_url", "فقط آدرس‌های http و https پذیرفته می‌شوند.")
        rest = match.group(2)
        text = f"{scheme}:{rest}" if rest.startswith("//") else f"{scheme}://{rest.lstrip('/')}"
    elif text.startswith("//"):
        text = "https:" + text
    else:
        text = "https://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise NormalizationError("invalid_url", "آدرس معتبر نیست.") from exc
    host = (parts.hostname or "").strip(".").lower()
    if not host:
        raise NormalizationError("invalid_url", "آدرس معتبر نیست.")
    host_ascii = _idna_host(host)
    if host_ascii.startswith("www."):
        host_ascii = host_ascii[4:]
    _validate_host(host_ascii)
    scheme = parts.scheme.lower()
    try:
        host_unicode = host_ascii.encode("ascii").decode("idna") if "xn--" in host_ascii else host_ascii
    except UnicodeError:
        host_unicode = host_ascii
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host_unicode}:{port}"
        identity_host = f"{host_ascii}:{port}"
    else:
        netloc = host_unicode
        identity_host = host_ascii
    path = re.sub(r"/{2,}", "/", parts.path or "")
    path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)
    ]
    query = urlencode(sorted(query_pairs))
    url = f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")
    identity = identity_host
    if _is_shared_platform(host_ascii):
        identity = identity_host + unquote(path).casefold()
    return CleanUrl(url=url, host=host_unicode, host_ascii=host_ascii, path=path, identity=identity, scheme=scheme)


def to_ascii_url(url: str) -> str:
    """Punycode the host and percent-encode the rest, for use with an HTTP client."""
    parts = urlsplit(url)
    host = _idna_host(parts.hostname or "")
    netloc = host + (f":{parts.port}" if parts.port else "")
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="=&%:@!$'()*+,;/?-._~")
    return f"{parts.scheme}://{netloc}{path}" + (f"?{query}" if query else "")


# --------------------------------------------------------------------------- instagram

_IG_HOSTS = {"instagram.com", "instagr.am"}
_IG_NON_PROFILE = {
    "p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct", "about", "legal", "developer",
    "web", "challenge", "oauth", "emails", "privacy", "directory", "locations", "tags", "s", "share", "ar",
}
_IG_HANDLE = re.compile(r"^[a-z0-9._]{1,30}$")


@dataclass(frozen=True)
class InstagramRef:
    handle: str  # lower-case, no @
    url: str  # https://www.instagram.com/<handle>/


def parse_instagram(raw: str | None) -> InstagramRef:
    """Handle + canonical URL from any Instagram URL form, ``@handle`` or ``handle``.

    Never fetches anything. Post/reel/story links are rejected: they are not a
    business profile and would create a wrong "handle"."""
    text = normalize_text(raw).strip("\"'<>«»()[]")
    if not text:
        raise NormalizationError("empty_instagram", "آدرس یا نام کاربریِ اینستاگرام خالی است.")
    handle = ""
    looks_like_url = bool(re.search(r"(instagram\.com|instagr\.am)", text, re.I)) or "/" in text
    if looks_like_url:
        candidate = text if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text) else "https://" + text.lstrip("/")
        try:
            parts = urlsplit(candidate)
        except ValueError as exc:
            raise NormalizationError("invalid_instagram", "آدرس اینستاگرام معتبر نیست.") from exc
        host = (parts.hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        if host.startswith("m."):
            host = host[2:]
        if host not in _IG_HOSTS:
            raise NormalizationError("invalid_instagram", "این آدرس مالِ اینستاگرام نیست.")
        segments = [s for s in parts.path.split("/") if s]
        if segments and segments[0].lower() == "_u" and len(segments) > 1:
            segments = segments[1:]
        if not segments:
            raise NormalizationError("invalid_instagram", "در این آدرس نام پیج پیدا نشد.")
        first = unquote(segments[0]).lstrip("@").lower()
        if first in _IG_NON_PROFILE:
            raise NormalizationError(
                "instagram_not_profile", "این لینکِ پست/ریلز/استوری است، نه صفحهٔ پیج. آدرس خودِ پیج را بدهید."
            )
        handle = first
    else:
        handle = text.lstrip("@").lower()
    if not _IG_HANDLE.match(handle) or handle.startswith(".") or handle.endswith(".") or ".." in handle:
        raise NormalizationError(
            "invalid_instagram", "نام کاربریِ اینستاگرام معتبر نیست (فقط حروف انگلیسی، عدد، نقطه و زیرخط)."
        )
    return InstagramRef(handle=handle, url=f"https://www.instagram.com/{handle}/")


# --------------------------------------------------------------------------- phones

_IR_MOBILE = re.compile(r"^09\d{9}$")
_IR_LANDLINE = re.compile(r"^0[1-8]\d{9}$")
_EXTENSION = re.compile(r"(?:داخلی|ext\.?|extension|int\.?|x|#)\s*\d{1,6}\s*$", re.I)


@dataclass(frozen=True)
class PhoneRef:
    normalized: str  # identity: 09121234567 / 02112345678 / +442071234567
    e164: str  # +989121234567
    kind: str  # mobile | landline | international


def normalize_phone(raw: str | None) -> PhoneRef:
    """Normalise an Iranian (default) or international phone number.

    Handles ``+98`` / ``0098`` / ``98`` / ``0`` prefixes, Persian and Arabic
    digits, separators, and the Excel habit of dropping the leading zero of a
    mobile number (``9121234567`` -> ``09121234567``). An 8-digit landline
    without an area code is rejected: guessing the city would be inventing data.
    """
    text = to_ascii_digits(normalize_text(raw))
    if not text:
        raise NormalizationError("empty_phone", "شماره خالی است.")
    text = _EXTENSION.sub("", text).strip()
    international = text.startswith("+") or text.startswith("00")
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    if not digits:
        raise NormalizationError("invalid_phone", "شماره معتبر نیست.")

    if not international and digits.startswith("98") and len(digits) == 12:
        international = True  # 989121234567
    if international:
        if digits.startswith("98"):
            rest = digits[2:]
            if rest.startswith("0"):  # +98 0912... (people write the 0 anyway)
                rest = rest[1:]
            national = "0" + rest
            return _iranian(national, raw)
        if 8 <= len(digits) <= 15 and not digits.startswith("0"):
            return PhoneRef(normalized="+" + digits, e164="+" + digits, kind="international")
        raise NormalizationError("invalid_phone", "شمارهٔ بین‌المللی معتبر نیست.")

    if len(digits) == 10 and digits[0] == "9":  # Excel dropped the leading zero
        digits = "0" + digits
    elif len(digits) == 10 and digits[0] in "12345678":  # landline typed without the leading 0
        digits = "0" + digits
    if len(digits) == 8 and digits[0] != "0":
        raise NormalizationError("missing_area_code", "کدِ شهر ندارد (مثلاً ۰۲۱). بدونِ کدِ شهر نمی‌شود ثبتش کرد.")
    return _iranian(digits, raw)


def _iranian(national: str, raw: str | None) -> PhoneRef:
    if _IR_MOBILE.match(national):
        return PhoneRef(normalized=national, e164="+98" + national[1:], kind="mobile")
    if _IR_LANDLINE.match(national):
        return PhoneRef(normalized=national, e164="+98" + national[1:], kind="landline")
    raise NormalizationError("invalid_phone", f"شمارهٔ «{normalize_text(raw)[:30]}» معتبر نیست.")


def format_phone_display(normalized: str) -> str:
    """Spaced form that Excel keeps as text (so the leading 0 survives)."""
    if _IR_MOBILE.match(normalized):
        return f"{normalized[:4]} {normalized[4:7]} {normalized[7:]}"
    if _IR_LANDLINE.match(normalized):
        return f"{normalized[:3]} {normalized[3:7]} {normalized[7:]}"
    return normalized


# --------------------------------------------------------------------------- email

_EMAIL_LOCAL = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}$")
_EMAIL_PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "domain.com", "email.com", "yourdomain.com", "test.com"}


def normalize_email(raw: str | None) -> str:
    """Lower-cased e-mail with the domain as punycode. No provider-specific
    tricks (no gmail dot removal): the address is kept as written."""
    text = normalize_text(raw).strip("\"'<>«»()[]")
    if text.lower().startswith("mailto:"):
        text = text[7:]
    text = text.split("?")[0].strip().lower()
    if not text:
        raise NormalizationError("empty_email", "ایمیل خالی است.")
    if text.count("@") != 1:
        raise NormalizationError("invalid_email", f"ایمیلِ «{text[:40]}» معتبر نیست.")
    local, domain = text.split("@")
    domain = _idna_host(domain.strip("."))
    if not _EMAIL_LOCAL.match(local) or local.startswith(".") or local.endswith(".") or ".." in local:
        raise NormalizationError("invalid_email", f"ایمیلِ «{text[:40]}» معتبر نیست.")
    labels = domain.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels) or labels[-1].isdigit():
        raise NormalizationError("invalid_email", f"ایمیلِ «{text[:40]}» معتبر نیست.")
    return f"{local}@{domain}"


def is_placeholder_email(address: str) -> bool:
    """example@example.com style filler that sites ship in templates."""
    domain = address.rsplit("@", 1)[-1]
    return domain in _EMAIL_PLACEHOLDER_DOMAINS or address.split("@")[0] in {"email", "name", "your", "yourname", "youremail"}


# --------------------------------------------------------------------------- telegram / other handles

_HANDLE = re.compile(r"^[a-z0-9_]{3,64}$")


def parse_handle(raw: str | None, hosts: tuple[str, ...], label: str) -> tuple[str, str]:
    """(handle, canonical key) from a URL on one of ``hosts`` or ``@handle``."""
    text = normalize_text(raw).strip("\"'<>«»()[]")
    if not text:
        raise NormalizationError("empty_handle", f"آدرس یا نام کاربریِ {label} خالی است.")
    if "/" in text or "." in text:
        candidate = text if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text) else "https://" + text.lstrip("/")
        parts = urlsplit(candidate)
        host = (parts.hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        if host not in hosts:
            raise NormalizationError("invalid_handle", f"این آدرس مالِ {label} نیست.")
        segments = [s for s in parts.path.split("/") if s]
        if not segments:
            raise NormalizationError("invalid_handle", f"در این آدرس نامِ {label} پیدا نشد.")
        text = unquote(segments[0])
        if text.lower() in {"share", "joinchat", "addstickers", "login", "dl", "s"}:
            raise NormalizationError("invalid_handle", f"این لینکِ اشتراک‌گذاری است، نه صفحهٔ {label}.")
    handle = text.lstrip("@").lower()
    if not _HANDLE.match(handle):
        raise NormalizationError("invalid_handle", f"نام کاربریِ {label} معتبر نیست.")
    return handle, handle


# --------------------------------------------------------------------------- country

#: ISO alpha-2 -> (Persian name, English name). Not exhaustive on purpose:
#: a two-letter ISO code outside this list is still accepted as typed.
COUNTRIES: dict[str, tuple[str, str]] = {
    "IR": ("ایران", "Iran"), "AF": ("افغانستان", "Afghanistan"), "IQ": ("عراق", "Iraq"), "TR": ("ترکیه", "Turkey"),
    "AE": ("امارات", "United Arab Emirates"), "AM": ("ارمنستان", "Armenia"), "AZ": ("آذربایجان", "Azerbaijan"),
    "TM": ("ترکمنستان", "Turkmenistan"), "PK": ("پاکستان", "Pakistan"), "OM": ("عمان", "Oman"),
    "QA": ("قطر", "Qatar"), "KW": ("کویت", "Kuwait"), "SA": ("عربستان", "Saudi Arabia"), "BH": ("بحرین", "Bahrain"),
    "LB": ("لبنان", "Lebanon"), "SY": ("سوریه", "Syria"), "JO": ("اردن", "Jordan"), "EG": ("مصر", "Egypt"),
    "TJ": ("تاجیکستان", "Tajikistan"), "UZ": ("ازبکستان", "Uzbekistan"), "KZ": ("قزاقستان", "Kazakhstan"),
    "GE": ("گرجستان", "Georgia"), "RU": ("روسیه", "Russia"), "IN": ("هند", "India"), "CN": ("چین", "China"),
    "DE": ("آلمان", "Germany"), "FR": ("فرانسه", "France"), "GB": ("بریتانیا", "United Kingdom"),
    "IT": ("ایتالیا", "Italy"), "ES": ("اسپانیا", "Spain"), "NL": ("هلند", "Netherlands"),
    "SE": ("سوئد", "Sweden"), "CA": ("کانادا", "Canada"), "US": ("آمریکا", "United States"),
    "AU": ("استرالیا", "Australia"), "MY": ("مالزی", "Malaysia"), "TH": ("تایلند", "Thailand"),
}
_COUNTRY_ALIASES = {
    "uae": "AE", "emirates": "AE", "dubai": "AE", "دبی": "AE", "امارات متحده عربی": "AE", "امارات‌متحده‌عربی": "AE",
    "uk": "GB", "england": "GB", "انگلیس": "GB", "انگلستان": "GB", "usa": "US", "america": "US", "ایالات متحده": "US",
    "united states of america": "US", "persia": "IR", "islamic republic of iran": "IR", "جمهوری اسلامی ایران": "IR",
    "turkiye": "TR", "ترکیه": "TR", "russian federation": "RU",
}
_COUNTRY_LOOKUP: dict[str, str] = {}
for _code, (_fa, _en) in COUNTRIES.items():
    _COUNTRY_LOOKUP[search_key(_fa)] = _code
    _COUNTRY_LOOKUP[search_key(_en)] = _code
for _alias, _code in _COUNTRY_ALIASES.items():
    _COUNTRY_LOOKUP[search_key(_alias)] = _code


def normalize_country(raw: str | None) -> str:
    """ISO alpha-2 code from a Persian / English name or a code ('' for empty)."""
    text = normalize_text(raw)
    if not text:
        return ""
    code = _COUNTRY_LOOKUP.get(search_key(text))
    if code:
        return code
    if re.fullmatch(r"[A-Za-z]{2}", text):
        return text.upper()
    raise NormalizationError("invalid_country", f"کشورِ «{text[:30]}» شناخته نشد. نام فارسی/انگلیسی یا کد دو‌حرفی (مثل IR) بنویسید.")


def country_name_fa(code: str) -> str:
    return COUNTRIES.get(code, (code, code))[0]
