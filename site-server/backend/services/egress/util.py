"""Reading what the owner types for a proxy: a URL, ``host:port``, ``user:pass@host:port`` or ``host:port:user:pass``."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote, urlsplit

SCHEMES = ("http", "https", "socks5", "socks5h")
#: addresses that mean «this machine / this LAN» - useless to hand to another computer
_LOCAL_NETS = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
    "::/128", "::1/128", "fc00::/7", "fe80::/10"))
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


class ProxyInputError(ValueError):
    """A Persian sentence the panel shows next to the field."""


def is_local_host(host: str) -> bool:
    """True for a host that means «this machine / this LAN»: it is useless to hand to another computer (the GPU node)."""
    host = (host or "").strip().strip("[]").lower()
    if host in ("localhost", "") or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # NOT ``ip.is_private``: Python counts the documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) as private too
    return any(ip in net for net in _LOCAL_NETS)


def valid_host(host: str) -> bool:
    host = (host or "").strip().strip("[]")
    if not host or len(host) > 255:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOST_RE.match(host))


def clean_fields(scheme, host, port, username="", password="") -> dict:
    scheme = str(scheme or "").strip().lower()
    if scheme not in SCHEMES:
        raise ProxyInputError("نوعِ پراکسی باید یکی از http، https، socks5 یا socks5h باشد.")
    host = str(host or "").strip().strip("[]")
    if not valid_host(host):
        raise ProxyInputError("نشانیِ پراکسی معتبر نیست (نامِ میزبان یا آدرسِ IP، بدونِ http:// و بدونِ پورت).")
    try:
        port_i = int(str(port).strip())
    except (TypeError, ValueError):
        raise ProxyInputError("پورت باید یک عدد باشد.") from None
    if not 1 <= port_i <= 65535:
        raise ProxyInputError("پورت باید بینِ ۱ تا ۶۵۵۳۵ باشد.")
    username, password = str(username or ""), str(password or "")
    if len(username) > 200 or len(password) > 300:
        raise ProxyInputError("نامِ کاربری یا رمز بیش از حد بلند است.")
    if password and not username:
        raise ProxyInputError("رمز بدونِ نامِ کاربری معنی ندارد.")
    return {"scheme": scheme, "host": host, "port": port_i, "username": username, "password": password}


def parse(text: str, default_scheme: str = "http") -> dict:
    """{scheme, host, port, username, password} from what a person pastes. Raises ``ProxyInputError``."""
    text = (text or "").strip()
    if not text:
        raise ProxyInputError("نشانیِ پراکسی را وارد کنید.")
    if "://" not in text:
        parts = text.split(":")
        if "@" not in text and len(parts) == 4 and parts[1].isdigit():          # host:port:user:pass (what proxy sellers send)
            text = f"{default_scheme}://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        else:
            text = f"{default_scheme}://{text}"
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        if "port" in str(exc).lower():
            raise ProxyInputError("پورت باید بینِ ۱ تا ۶۵۵۳۵ باشد.") from None
        raise ProxyInputError("نشانیِ پراکسی معتبر نیست.") from None
    if not host or port is None:
        raise ProxyInputError("نشانیِ پراکسی باید «نوع://نشانی:پورت» باشد؛ مثلاً socks5h://127.0.0.1:10808")
    return clean_fields(parts.scheme or default_scheme, host, port, unquote(parts.username or ""), unquote(parts.password or ""))
