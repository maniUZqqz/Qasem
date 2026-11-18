"""The closed list of outside services that may be sent through a proxy / VPN.

**Everything that is not in this list ALWAYS goes direct** (the site itself, Iranian services such as Bale / Eitaa / Rubika /
Zarinpal / Novinhub / Metis, the GPU node, local services, package mirrors ...). A route can only be attached to a service
named here, and a host decides its service only when it matches one of the ``hosts`` below - so a proxy can never become
«the way everything leaves the server».

Adding a service is one entry: a key, a Persian title, the hosts that belong to it and a few URLs the «test» button asks.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    key: str
    title: str
    group: str
    summary: str                    # one Persian sentence: what in NM talks to it
    used_by: tuple[str, ...]        # the features (Persian) that use it
    hosts: tuple[str, ...]          # a host belongs to the service when it IS one of these or ends with ".<one of these>"
    probes: tuple[tuple[str, str], ...]   # (label, url): what the test button asks - any HTTP answer means «reachable»
    node: bool = False              # the GPU node may be given this proxy (only for work that runs there)


GROUPS = (
    ("messaging", "پیام‌رسان‌ها و شبکه‌های اجتماعی"),
    ("search", "موتورهای جست‌وجو"),
    ("ai", "هوش مصنوعیِ خارجی"),
    ("maps", "نقشه و داده‌های باز"),
)

_SERVICES = (
    Service(
        "telegram", "تلگرام", "messaging",
        "ربات تلگرام (دریافت و ارسال پیام، وب‌هوک، دریافت عکسِ رسید) و هر دریافتِ دیگر از تلگرام.",
        ("صندوقِ یکپارچه › تلگرام", "ارسالِ پاسخ به مشتری", "دریافتِ عکسِ رسید"),
        ("telegram.org", "t.me", "telegram.me", "telegram-cdn.org"),
        (("api.telegram.org", "https://api.telegram.org/"),),
    ),
    Service(
        "instagram", "اینستاگرام (Graph و خواندنِ صفحه‌ها)", "messaging",
        "اینستاگرام و Graph ِ آن: دایرکت، انتشار، و خواندنِ پروفایل‌ها برای مشتری‌یاب و ترندها (آباگرام روی سرورِ پردازش هم می‌تواند از همین پراکسی استفاده کند).",
        ("صندوقِ یکپارچه › اینستاگرام", "مشتری‌یاب (پروفایلِ اینستاگرام)", "ترندهای اینستاگرام (آباگرام)"),
        ("instagram.com", "cdninstagram.com", "instagr.am"),
        (("graph.instagram.com", "https://graph.instagram.com/"), ("www.instagram.com", "https://www.instagram.com/")),
        node=True,
    ),
    Service(
        "whatsapp", "واتساپ (Cloud API)", "messaging",
        "واتساپ بیزینس (Meta Cloud API روی graph.facebook.com): ارسالِ پیام، بررسیِ حساب و دریافتِ عکس.",
        ("صندوقِ یکپارچه › واتساپ",),
        ("graph.facebook.com", "whatsapp.com", "whatsapp.net", "wa.me", "fbsbx.com"),
        (("graph.facebook.com", "https://graph.facebook.com/"), ("web.whatsapp.com", "https://web.whatsapp.com/")),
    ),
    Service(
        "meta", "فیسبوک و سایرِ سرویس‌های Meta", "messaging",
        "هر دریافتِ دیگر از فیسبوک (صفحه‌ها و فایل‌های fbcdn که اینستاگرام لینک می‌دهد). فایل‌های پیوستِ واتساپ (fbsbx) زیرِ «واتساپ» هستند.",
        ("خزشگرِ مشتری‌یاب (صفحه‌های فیسبوک)", "فایل‌های پیوستِ Meta"),
        ("facebook.com", "fb.com", "fbcdn.net"),
        (("www.facebook.com", "https://www.facebook.com/"),),
    ),
    Service(
        "brave", "جست‌وجوی Brave", "search",
        "Brave Search (API و صفحهٔ نتایج) برای مشتری‌یاب، پژوهشِ بازار و جست‌وجوی وب.",
        ("مشتری‌یاب (جست‌وجوی وب)", "پژوهشِ بازار"),
        ("brave.com",),
        (("api.search.brave.com", "https://api.search.brave.com/"),),
    ),
    Service(
        "google", "گوگل (جست‌وجو، ترندها، اخبار)", "search",
        "Google Custom Search، Google Trends، Google News و سایرِ APIهای گوگل.",
        ("مشتری‌یاب (Google CSE)", "ترندهای بازار", "اخبارِ بازار"),
        ("google.com", "googleapis.com"),
        (("www.google.com", "https://www.google.com/"), ("news.google.com", "https://news.google.com/")),
    ),
    Service(
        "search_other", "Bing و DuckDuckGo", "search",
        "صفحهٔ نتایجِ Bing و DuckDuckGo که خزشگرِ مشتری‌یاب می‌خواند.",
        ("مشتری‌یاب (جست‌وجوی وب)",),
        ("bing.com", "duckduckgo.com"),
        (("www.bing.com", "https://www.bing.com/"), ("duckduckgo.com", "https://duckduckgo.com/")),
    ),
    Service(
        "ai_foreign", "هوش مصنوعیِ خارجی (OpenAI، ElevenLabs، …)", "ai",
        "APIهای خارجی که از ایران معمولاً بسته‌اند. Metis و مدل‌های محلیِ سرورِ پردازش هرگز از این راه نمی‌روند.",
        ("موتورهای AI (ارائه‌دهندهٔ OpenAI)", "صدای ElevenLabs", "تصویر و ویدیوی API (Replicate)"),
        ("openai.com", "elevenlabs.io", "anthropic.com", "openrouter.ai", "groq.com", "x.ai", "mistral.ai", "replicate.com",
         "generativelanguage.googleapis.com"),
        (("api.openai.com", "https://api.openai.com/v1/models"), ("api.elevenlabs.io", "https://api.elevenlabs.io/")),
    ),
    Service(
        "osm", "نقشه (OpenStreetMap و Overpass)", "maps",
        "جست‌وجوی شهر و مکان‌ها (Nominatim و Overpass) که مشتری‌یاب برای پیدا کردنِ کسب‌وکارها می‌خواند.",
        ("مشتری‌یاب (نقشه)", "کشفِ مشتری (OSM)"),
        ("openstreetmap.org", "overpass-api.de", "kumi.systems", "private.coffee", "maps.mail.ru"),
        (("nominatim.openstreetmap.org", "https://nominatim.openstreetmap.org/status"),
         ("overpass-api.de", "https://overpass-api.de/api/status")),
    ),
)

CATALOG: dict[str, Service] = {s.key: s for s in _SERVICES}

# (host, key) with the longest hosts first, so «graph.facebook.com» (whatsapp) wins over «facebook.com» (meta)
_HOST_TABLE: tuple[tuple[str, str], ...] = tuple(
    sorted(((h, s.key) for s in _SERVICES for h in s.hosts), key=lambda item: -len(item[0]))
)


def get(key: str) -> Service | None:
    return CATALOG.get(key or "")


def service_for_host(host: str) -> str | None:
    """The service a host belongs to, or None (= it always goes direct)."""
    host = (host or "").strip().strip(".").lower().strip("[]")
    if not host:
        return None
    for suffix, key in _HOST_TABLE:
        if host == suffix or host.endswith("." + suffix):
            return key
    return None


def service_for_url(url: str) -> str | None:
    from urllib.parse import urlsplit

    try:
        return service_for_host(urlsplit(url or "").hostname or "")
    except ValueError:
        return None
