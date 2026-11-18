"""Which way does a call to an outside service leave this server? One answer, in one place.

``route_for("telegram")`` says «direct» or «through proxy X». Everything below turns that answer into a working HTTP call:

* ``get / post / request (service, ...)``        - one call; direct = the plain ``requests`` call it always was;
* ``session_for(service)`` / ``client_for(...)``  - a ``requests.Session`` / ``httpx.Client`` bound to the route;
* ``*_for_url``                                  - the service is chosen by the HOST of a url (catalogue hosts only);
* ``reason(exc)``                                - the Persian sentence of a proxy-level failure (or None).

Rules this module keeps:

* the proxy is attached to the one call / session only - **never** to the process (no HTTP_PROXY / ALL_PROXY anywhere), so a service
  that is not in the table cannot leave through it;
* a service whose route is «direct» (the default, and the state of every service until the owner changes it) behaves exactly as the
  old code did;
* a proxied call that fails at the PROXY raises ``EgressError`` (Persian, secret-free); it never quietly falls back to a direct
  call - a filtered service would fail that way anyway, and the owner must see that the proxy is the broken part;
* the password of a proxy lives only in ``Route.password`` and in the DB row. ``repr`` / ``str`` / logs never contain it.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import requests
from django.conf import settings

from . import catalog, errors, socks
from .errors import EgressError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class Route:
    service: str
    proxy_id: int | None = None
    name: str = ""
    scheme: str = ""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = field(default="", repr=False)

    @property
    def proxied(self) -> bool:
        return bool(self.host and self.scheme)

    @property
    def is_socks(self) -> bool:
        return self.scheme.startswith("socks")

    def url(self) -> str:
        """The full proxy URL WITH credentials - for the HTTP library only. Never log it, never return it from an API."""
        auth = ""
        if self.username:
            auth = quote(self.username, safe="") + (":" + quote(self.password, safe="") if self.password else "") + "@"
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{self.scheme}://{auth}{host}:{self.port}"

    def public(self) -> str:
        """``scheme://host:port`` - safe to show."""
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{self.scheme}://{host}:{self.port}" if self.proxied else ""

    def __repr__(self) -> str:  # never the password, never the user name
        return f"Route({self.service!r}, {self.public() or 'direct'})"

    __str__ = __repr__


def direct(service: str = "") -> Route:
    return Route(service=service or "")


# ------------------------------------------------------------------------------------------------ the table (cached)

_STATE: dict = {"at": -1e9, "routes": {}, "warned": 0.0}
_LOCK = threading.Lock()


def _ttl() -> float:
    if getattr(settings, "IS_TEST", False):
        return 0.0                  # a rolled-back test row must never be remembered by the next test
    return float(getattr(settings, "EGRESS_CACHE_SECONDS", 5))


def invalidate() -> None:
    """Forget the cached table (called whenever a proxy or a route is saved; other processes catch up within the TTL)."""
    _STATE["at"] = -1e9


def _load() -> dict[str, Route]:
    from apps.egress.models import EgressRoute, EgressSwitch

    if EgressSwitch.objects.filter(pk=1, enabled=False).exists():
        return {}                    # the master switch is off: everything goes direct, the table stays for when it is switched on again
    rows = EgressRoute.objects.filter(proxy__isnull=False, proxy__enabled=True).select_related("proxy")
    out = {}
    for row in rows:
        p = row.proxy
        if row.service in catalog.CATALOG:
            out[row.service] = Route(row.service, p.pk, p.name, p.scheme, p.host, int(p.port), p.username, p.password)
    return out


def routes() -> dict[str, Route]:
    """Every service that currently leaves through a proxy: {service: Route}. Empty = everything is direct."""
    now = time.monotonic()
    ttl = _ttl()
    if ttl > 0 and now - _STATE["at"] < ttl:
        return _STATE["routes"]
    with _LOCK:
        if ttl > 0 and time.monotonic() - _STATE["at"] < ttl:
            return _STATE["routes"]
        try:
            _STATE["routes"] = _load()
        except Exception:  # noqa: BLE001 - no table (a test without the app, a locked DB): keep the last good answer, else direct
            if now - _STATE["warned"] > 300:
                _STATE["warned"] = now
                logger.warning("egress: the route table could not be read; keeping the last known routes", exc_info=True)
        _STATE["at"] = time.monotonic()
        return _STATE["routes"]


def route_for(service: str | None) -> Route:
    """The route of a catalogue service. A name that is not in the catalogue (or empty) is ALWAYS direct."""
    if not service or service not in catalog.CATALOG:
        return direct(service or "")
    return routes().get(service) or direct(service)


def service_for_url(url: str) -> str | None:
    return catalog.service_for_url(url)


def route_for_url(url: str) -> Route:
    """The route of the service a url's HOST belongs to (direct when the host is not in the catalogue)."""
    service = catalog.service_for_url(url)
    return route_for(service) if service else direct("")


# ------------------------------------------------------------------------------------------------ requests

class EgressSession(requests.Session):
    """A ``requests.Session`` that leaves through ``route`` (or direct), ignores the process environment and says Persian."""

    def __init__(self, route: Route | None = None):
        super().__init__()
        self.trust_env = False                      # HTTP_PROXY / NO_PROXY / .netrc of the process are NOT consulted
        self.egress_route = route or direct()
        if self.egress_route.proxied:
            if self.egress_route.is_socks:
                adapter = socks.requests_adapter(self.egress_route)
                self.mount("http://", adapter)
                self.mount("https://", adapter)
            else:
                proxy = self.egress_route.url()
                self.proxies = {"http": proxy, "https": proxy}

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        route = self.egress_route
        try:
            response = super().request(method, url, **kwargs)
        except EgressError:
            raise
        except requests.RequestException as exc:
            if route.proxied:
                err = errors.from_exception(exc, route, url)
                if err is not None:
                    raise err from None             # `from None`: the original message quotes the url (= the bot token)
            raise
        if route.proxied and not route.is_socks and response.status_code == 407:
            response.close()
            raise EgressError("auth", errors.message_for("auth", route), service=route.service, proxy_name=route.name)
        return response


def session_for(service: str | None) -> EgressSession:
    return EgressSession(route_for(service))


def session_for_url(url: str) -> EgressSession:
    return EgressSession(route_for_url(url))


def request(service: str | None, method: str, url: str, **kwargs) -> requests.Response:
    """One call. A direct route is the very same ``requests.<method>(url, ...)`` the code made before this layer existed."""
    route = route_for(service)
    if not route.proxied:
        return getattr(requests, method.lower())(url, **kwargs)
    return EgressSession(route).request(method.upper(), url, **kwargs)


def get(service: str | None, url: str, **kwargs) -> requests.Response:
    return request(service, "get", url, **kwargs)


def post(service: str | None, url: str, **kwargs) -> requests.Response:
    return request(service, "post", url, **kwargs)


def request_for_url(method: str, url: str, **kwargs) -> requests.Response:
    return request(catalog.service_for_url(url), method, url, **kwargs)


def get_for_url(url: str, **kwargs) -> requests.Response:
    return request_for_url("get", url, **kwargs)


def post_for_url(url: str, **kwargs) -> requests.Response:
    return request_for_url("post", url, **kwargs)


def reason(exc: BaseException) -> str | None:
    """The Persian reason when ``exc`` is a failure of the PROXY (so a call site can say it instead of «در دسترس نبود»); else None."""
    return str(exc) if isinstance(exc, EgressError) else None


# ------------------------------------------------------------------------------------------------ httpx

def httpx_client(route: Route | None, **kwargs):
    """An ``httpx.Client`` that leaves through ``route`` (or direct). The environment is ignored (``trust_env=False``)."""
    import httpx

    kwargs.setdefault("trust_env", False)
    if route is not None and route.proxied:
        if route.is_socks:
            transport = socks.httpx_transport(route, verify=kwargs.get("verify", True))
            return httpx.Client(transport=transport, **kwargs)
        return httpx.Client(proxy=route.url(), **kwargs)
    return httpx.Client(**kwargs)


def client_for(service: str | None, **kwargs):
    return httpx_client(route_for(service), **kwargs)


def httpx_failure(exc: BaseException, route: Route, url: str = "") -> EgressError | None:
    """An ``EgressError`` when an ``httpx`` failure on a PROXIED client is the proxy's doing (the only connection a proxied client
    opens is the one to the proxy, so a connect-stage failure is the proxy's)."""
    if not route.proxied:
        return None
    return errors.from_exception(exc, route, url)
