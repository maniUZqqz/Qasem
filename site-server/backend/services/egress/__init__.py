"""Per-service proxy / VPN routing: the ONE helper every call to a filtered outside service goes through.

    from services import egress

    egress.post("telegram", url, json=..., timeout=15)          # direct unless the owner routed «telegram» through a proxy
    with egress.session_for("brave") as s: s.get(url, ...)      # a requests.Session bound to the route
    egress.get_for_url(url)                                     # the service is picked by the url's host
    egress.client_for("instagram", timeout=...)                 # an httpx.Client bound to the route
    egress.reason(exc)                                          # Persian sentence when the PROXY failed, else None

The settings live in the database (``apps.egress``: proxies + one route per service, edited on the panel's «پراکسی و VPN» page).
Default: no proxy, every service direct. Anything that is not in ``egress.catalog.CATALOG`` always goes direct, and the proxy is
never put in the process environment. See docs/egress/proxy-fa.md.
"""
from . import catalog, errors
from .catalog import CATALOG, GROUPS, service_for_host
from .core import (
    DEFAULT_TIMEOUT, EgressSession, Route, client_for, direct, get, get_for_url, httpx_client, httpx_failure, invalidate, post,
    post_for_url, reason, request, request_for_url, route_for, route_for_url, routes, service_for_url, session_for, session_for_url,
)
from .errors import EgressError, EgressTimeout
from .tunnel import open_socket, telethon_kwargs

__all__ = [
    "CATALOG", "GROUPS", "DEFAULT_TIMEOUT", "EgressError", "EgressTimeout", "EgressSession", "open_socket", "telethon_kwargs", "Route", "catalog", "client_for", "direct", "errors", "get",
    "get_for_url", "httpx_client", "httpx_failure", "invalidate", "post", "post_for_url", "reason", "request", "request_for_url",
    "route_for", "route_for_url", "routes", "service_for_host", "service_for_url", "session_for", "session_for_url",
]
