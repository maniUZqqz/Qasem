# -*- coding: utf-8 -*-
"""محافظِ نشانی برای «عکس گرفتن از صفحه»: سرورِ ما نباید بتواند به شبکهٔ داخلی (Redis، پایگاه‌داده، پنل‌های محلی، متادیتای ابر) سر بزند.

قاعده: فقط http و https، بی‌نام‌کاربری/رمز در نشانی، و نامِ میزبان فقط به نشانی‌های **عمومی** (ipaddress.is_global) برسد.
همین بررسی برای هر درخواستی که مرورگر می‌زند (ریدایرکت، تصویر، اسکریپت) هم تکرار می‌شود (runner.py).

⚠ مرورگر خودش دوباره DNS می‌زند؛ پس یک پنجرهٔ بسیار باریکِ «DNS rebinding» می‌ماند. کاهشش: خروجیِ مرورگر هیچ‌جا ذخیره یا اجرا نمی‌شود
(فقط یک تصویرِ PNG)، و به‌خاطرِ بررسیِ تک‌تکِ درخواست‌ها سرورِ داخلی نمی‌تواند پاسخی پس بدهد که ما نشانش بدهیم مگر DNS در همان میلی‌ثانیه عوض شود.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")
MAX_URL_LEN = 2000


class UrlRefused(ValueError):
    """نشانی پذیرفته نشد؛ متنِ خطا فارسی است و به کاربر نشان داده می‌شود."""


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return bool(addr.is_global and not addr.is_multicast)


def resolve_public(host: str, resolver=None) -> list[str]:
    """همهٔ نشانی‌های IP ِ میزبان؛ اگر حتی یکی عمومی نباشد ⇒ UrlRefused. ``resolver`` برای آزمون."""
    host = (host or "").strip().strip("[]").lower()
    if not host:
        raise UrlRefused("نامِ سایت در نشانی پیدا نشد.")
    try:  # خودِ IP نوشته شده؟
        ipaddress.ip_address(host.split("%")[0])
        ips = [host]
    except ValueError:
        try:
            infos = (resolver or socket.getaddrinfo)(host, None, type=socket.SOCK_STREAM)
        except OSError:
            raise UrlRefused("این نشانی پیدا نشد (نامِ سایت از اینترنتِ سرور دیده نمی‌شود).") from None
        ips = sorted({i[4][0] for i in infos})
    if not ips:
        raise UrlRefused("این نشانی پیدا نشد.")
    bad = [ip for ip in ips if not _is_public(ip)]
    if bad:
        raise UrlRefused("این نشانی به شبکهٔ داخلی یا یک آدرسِ غیرعمومی می‌رسد؛ فقط سایت‌های عمومیِ اینترنت پذیرفته می‌شود.")
    return ips


def check_url(url: str, resolver=None) -> str:
    """نشانیِ پاک‌سازی‌شده یا UrlRefused."""
    raw = (url or "").strip()
    if not raw:
        raise UrlRefused("نشانیِ صفحه را بنویسید.")
    if len(raw) > MAX_URL_LEN:
        raise UrlRefused("نشانی بیش از اندازه بلند است.")
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise UrlRefused("نشانی درست نیست.") from None
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlRefused("فقط نشانی‌های http و https پذیرفته می‌شود.")
    if parts.username or parts.password:
        raise UrlRefused("نشانی نباید نام‌کاربری یا رمز داشته باشد.")
    if not parts.hostname:
        raise UrlRefused("نامِ سایت در نشانی پیدا نشد.")
    if port is not None and not (1 <= port <= 65535):
        raise UrlRefused("درگاهِ نشانی درست نیست.")
    resolve_public(parts.hostname, resolver)
    return parts.geturl()
