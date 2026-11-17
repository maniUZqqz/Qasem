"""The address the outside world reaches this site at.

Three things we hand out are absolute URLs that *another party* must be able to
open: the one-line widget snippet (`<script src=...>` on the shop's own website),
the webhook URLs of Bale / Eitaa / Rubika / WhatsApp / Telegram, and the API
base in the developer docs. Until now they were built from whatever address the
panel happened to be opened on - on the owner's server that is a bare IP with a
port and **no HTTPS**, so:

* a browser refuses to load an `http://` script into an `https://` page (mixed
  content) - the widget never appears on a real shop website; and
* Telegram-style platforms refuse to register an `http://` webhook at all.

So the address is a *setting* (`InboxSettings.public_base_url`, edited on the
channels page), falls back to the site-wide `PUBLIC_BASE_URL`, then to the
request's own address - and whenever the result is plain `http://` on a real
host the panel says so, in Persian, next to the snippet and the webhook URLs.
This module is that decision and nothing else.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from django.conf import settings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver"}
_HOST = re.compile(r"[a-z0-9]([a-z0-9.\-]*[a-z0-9])?")

WARNING_HTTP = (
    "نشانی عمومیِ این سایت «http» است (بدون رمزگذاری). مرورگر اجازه نمی‌دهد صفحه‌ای که با «https» باز شده "
    "(مثل سایت چغر) اسکریپتی را از نشانی http بارگذاری کند؛ پس ویجت چت روی سایت‌های https نشان داده نمی‌شود. "
    "بله، ایتا و روبیکا هم وب‌هوکِ http را نمی‌پذیرند. راه‌حل: برای این سرور یک دامنه با گواهی https راه بیندازید و "
    "نشانی آن را (مثلاً https://chat.example.ir) در کادر «نشانی عمومی سایت» بنویسید. "
    "تا آن موقع ربات‌ها با «پرسش دوره‌ای» کار می‌کنند و ویجت فقط روی سایت‌های http جواب می‌دهد."
)
WARNING_LOCAL = (
    "این نشانی فقط روی همین رایانه کار می‌کند؛ پلتفرم‌ها و بازدیدکننده‌های سایت شما به آن نمی‌رسند. "
    "نشانی عمومی سایت را در کادر «نشانی عمومی سایت» بنویسید."
)


class BadAddress(ValueError):
    """The text is not an address we can use. The message is Persian and shown as is."""


def clean(raw) -> str:
    """`https://Chat.Example.ir/` -> `https://chat.example.ir`. '' stays ''. Anything odd raises `BadAddress`."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text  # «chat.example.ir» is what people type; https is the only sensible guess
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise BadAddress("نشانی نامعتبر است؛ مثل https://chat.example.ir بنویسید.") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BadAddress("نشانی باید با http:// یا https:// شروع شود، مثل https://chat.example.ir")
    if parts.username or parts.password:
        raise BadAddress("نشانی نباید نام‌کاربری یا رمز داشته باشد.")
    if parts.path.strip("/") or parts.query or parts.fragment:
        raise BadAddress("فقط نشانی سایت را بنویسید، بدون مسیر (مثلاً https://chat.example.ir).")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"  # an IPv6 literal
    else:
        try:
            host = host.encode("idna").decode("ascii")  # a Persian / unicode domain becomes its punycode form
        except UnicodeError:
            raise BadAddress("نام دامنه نامعتبر است؛ مثل chat.example.ir بنویسید.") from None
        if not _HOST.fullmatch(host):
            raise BadAddress("نام دامنه نامعتبر است؛ مثل chat.example.ir بنویسید.")
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_local(url: str) -> bool:
    return host_of(url) in LOCAL_HOSTS


def is_secure(url: str) -> bool:
    return url.lower().startswith("https://") and not is_local(url)


def warning_for(url: str) -> str:
    """The Persian sentence to show next to a snippet / webhook URL built on `url`, or ''."""
    if is_local(url):
        return WARNING_LOCAL
    if url.lower().startswith("http://"):
        return WARNING_HTTP
    return ""


def _site_wide() -> str:
    try:
        raw = (getattr(settings, "UPMARKET_PUBLISHING", {}) or {}).get("PUBLIC_BASE_URL", "")
        return clean(raw)
    except BadAddress:
        return ""


def resolve(request, store) -> dict:
    """`{"url", "source", "secure", "warning"}` - the address to build absolute URLs on.

    `source` is `"setting"` (the store chose it), `"request"` (the panel is open over https on a
    real host), `"site"` (`PUBLIC_BASE_URL`, when it is a real address) or, last, `"request"` again
    (however the panel happened to be opened, http included).
    """
    from .team import settings_for

    chosen = ""
    try:
        chosen = clean(settings_for(store).public_base_url) if store is not None else ""
    except BadAddress:
        chosen = ""
    source = "setting"
    here = request.build_absolute_uri("/").rstrip("/")
    if not chosen and request.is_secure() and not is_local(here):
        # The panel itself is being served over https on a real host: that address demonstrably
        # works from outside, and is better than an http `PUBLIC_BASE_URL` left over in the .env.
        chosen, source = here, "request"
    if not chosen:
        site = _site_wide()
        if site and not is_local(site):
            chosen, source = site, "site"
    if not chosen:
        chosen, source = here, "request"
    return {
        "url": chosen, "source": source, "secure": is_secure(chosen), "warning": warning_for(chosen),
    }


def build(request, store, path: str) -> str:
    """An absolute URL for `path` (`/api/v1/...`) on the public address."""
    return resolve(request, store)["url"] + "/" + path.lstrip("/")
