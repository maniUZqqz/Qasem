"""The «test» button: what does the world see, and which of the services can this route reach?

A test answers three questions through ONE route (a proxy, or direct):

1. **Which address / country do the outside services see?** - an «IP echo» answers (ipinfo.io and two fallbacks);
2. **How fast is it?** - the round trip of that first answer, and of every probe;
3. **Can it reach api.telegram.org / graph.instagram.com / graph.facebook.com / web.whatsapp.com / api.search.brave.com ...?** - one
   GET per probe URL of the catalogue; *any* HTTP answer (even 401 / 404 / 302) means «reachable»: the server answered.

If the very first request fails at the proxy itself (refused, wrong password, wrong type ...) the test stops there and says so once,
in Persian, instead of hammering the proxy with twenty requests that all fail the same way.

Nothing here touches the database or any secret: the caller stores ``result`` (which has none) where it wants.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from django.conf import settings

from . import catalog, errors
from .core import EgressSession, Route
from .errors import EgressError

CONNECT_TIMEOUT = 6
READ_TIMEOUT = 8
#: tried in order; the first that answers wins (each one reports the address the REQUEST came from)
IP_ECHO_URLS = (
    "https://ipinfo.io/json",
    "http://ip-api.com/json/?fields=status,query,country,countryCode,city,isp",
    "https://api.ip.sb/geoip",
)


def _ip_urls() -> tuple[str, ...]:
    return tuple(getattr(settings, "EGRESS_IP_ECHO_URLS", None) or IP_ECHO_URLS)


def _probe_overrides() -> dict:
    """Tests (and an owner behind a very odd network) can replace a probe URL: {service key: [(label, url), ...]}."""
    return getattr(settings, "EGRESS_PROBE_URLS", None) or {}


def probes_of(service_key: str) -> list[tuple[str, str]]:
    override = _probe_overrides().get(service_key)
    if override is not None:
        return [tuple(item) for item in override]
    svc = catalog.get(service_key)
    return list(svc.probes) if svc else []


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _timeout():
    return (CONNECT_TIMEOUT, READ_TIMEOUT)


def _failure_text(exc: BaseException, route: Route | None = None) -> str:
    """A Persian reason for an ordinary (non-proxy) failure; never the exception text (it quotes the url)."""
    if isinstance(exc, EgressError):
        return str(exc)
    if isinstance(exc, requests.exceptions.ReadTimeout) and route is not None and route.proxied:
        return "پراکسی یا سایتِ مقصد به‌موقع جواب نداد"
    if isinstance(exc, requests.exceptions.SSLError):
        return "گواهیِ امنیتیِ سایت پذیرفته نشد"
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "اتصال به‌موقع برقرار نشد (زمان تمام شد)"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "سایت به‌موقع جواب نداد"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "اتصال برقرار نشد (بسته یا فیلتر است)"
    return "درخواست ناموفق بود"


def _one(route: Route, label: str, url: str) -> dict:
    started = time.monotonic()
    row = {"label": label, "ok": False, "status": None, "ms": None, "error": ""}
    try:
        with EgressSession(route) as session:
            response = session.get(url, timeout=_timeout(), allow_redirects=False, stream=True,
                                   headers={"User-Agent": "NMarketing-egress-test/1.0"})
            row["status"] = response.status_code
            response.close()
        row["ok"] = True
    except EgressError as exc:
        row["error"] = str(exc)
        row["proxy_failure"] = True
    except requests.RequestException as exc:
        row["error"] = _failure_text(exc, route)
    row["ms"] = int((time.monotonic() - started) * 1000)
    return row


def _echo_one(route: Route, url: str) -> dict:
    """What ONE echo service says about the address this route comes from: {ip, country, ...} | {} | {"proxy_error": text}."""
    started = time.monotonic()
    try:
        with EgressSession(route) as session:
            response = session.get(url, timeout=_timeout(), headers={"Accept": "application/json", "User-Agent": "NMarketing-egress-test/1.0"})
        data = response.json() if response.status_code == 200 else {}
    except EgressError as exc:
        return {"proxy_error": str(exc)}
    except (requests.RequestException, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    ip = str(data.get("ip") or data.get("query") or "")[:64]
    if not ip:
        return {}
    return {
        "ip": ip,
        "country": str(data.get("country") or data.get("country_name") or "")[:60],
        "country_code": str(data.get("country_code") or data.get("countryCode") or "")[:4],
        "city": str(data.get("city") or "")[:60],
        "org": str(data.get("org") or data.get("isp") or data.get("organization") or "")[:100],
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def run(route: Route, services: list[str] | None = None, *, echo: bool = True, workers: int = 10) -> dict:
    """Test ``route`` against the probes of ``services`` (default: every catalogue service).

    Everything (the echo services and every probe) is asked at the same time, so the whole test takes about one timeout, not a sum.
    Returns {ok, via, proxy, checked_at, ip, country, country_code, city, org, latency_ms, targets: [...], summary, proxy_error?}.
    ``ok`` is True when the route itself works (an echo or at least one probe answered)."""
    keys = [k for k in (services or list(catalog.CATALOG)) if k in catalog.CATALOG]
    result: dict = {
        "via": "proxy" if route.proxied else "direct", "proxy": route.name if route.proxied else "", "checked_at": now_iso(),
        "ip": "", "country": "", "country_code": "", "city": "", "org": "", "latency_ms": None, "targets": [],
    }
    echo_urls = list(_ip_urls()) if echo else []
    jobs = [(key, label, url) for key in keys for label, url in probes_of(key)]
    if not echo_urls and not jobs:
        result.update(ok=False, summary="مقصدی برای آزمایش نیست")
        return result
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(echo_urls) + len(jobs)))) as pool:
        echo_futures = [pool.submit(_echo_one, route, url) for url in echo_urls]
        probe_futures = [pool.submit(_one, route, label, url) for _key, label, url in jobs]
        echoes = [f.result() for f in echo_futures]
        rows = [{**f.result(), "service": job[0]} for f, job in zip(probe_futures, jobs)]
    result["targets"] = rows
    good = next((e for e in echoes if e.get("ip")), None)
    if good:
        result.update(good)
    broken = [e["proxy_error"] for e in echoes if e.get("proxy_error")] + [r["error"] for r in rows if r.get("proxy_failure")]
    reached = sum(1 for r in rows if r["ok"])
    if broken and not good and reached == 0:
        result.update(ok=False, proxy_error=broken[0], summary=broken[0])      # the proxy itself is broken: say so once
        return result
    if result["latency_ms"] is None:
        times = [r["ms"] for r in rows if r["ok"] and r["ms"] is not None]
        result["latency_ms"] = min(times) if times else None
    result["ok"] = bool(result["ip"]) or reached > 0
    bits = []
    if result["ip"]:
        where = " · ".join(x for x in (result["country"] or result["country_code"], result["city"]) if x)
        bits.append(f"آدرسی که سرویس‌ها می‌بینند: {result['ip']}" + (f" ({where})" if where else ""))
    if rows:
        bits.append(f"{reached} از {len(rows)} مقصد در دسترس است")
    result["summary"] = " — ".join(bits) or "پاسخی نیامد"
    return result


def service_state(targets: list[dict]) -> str:
    """ok (every probe answered) | partial | down | unknown (no probe)."""
    if not targets:
        return "unknown"
    reached = sum(1 for t in targets if t.get("ok"))
    if reached == len(targets):
        return "ok"
    return "partial" if reached else "down"


def check_service(service_key: str, route: Route | None = None) -> dict:
    """The health record of ONE service through the route it really uses (``route`` defaults to the live one). No echo: it is a
    health check, not the diagnostic page."""
    from .core import route_for

    route = route or route_for(service_key)
    got = run(route, [service_key], echo=False)
    state = service_state(got["targets"]) if not got.get("proxy_error") else "down"
    detail = got.get("proxy_error") or "؛ ".join(
        f"{t['label']}: " + ("در دسترس" + (f" ({t['status']})" if t.get("status") else "") if t["ok"] else t.get("error") or "در دسترس نیست")
        for t in got["targets"]) or "مقصدی برای آزمایش نیست"
    return {
        "state": state, "via": got["via"], "proxy": got["proxy"], "checked_at": got["checked_at"], "detail": detail[:600],
        "latency_ms": got.get("latency_ms"), "targets": got["targets"],
    }
