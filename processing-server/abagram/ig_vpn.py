"""The office VPN gateway (Xray Gateway, its self-service «/me» portal): which country this computer's traffic leaves from,
and changing it — that is the exit address Instagram sees. The portal knows the computer by its LAN address, so no key and
no password is kept here; a sign-in (only when the gateway has none for this computer) is passed through and forgotten.
A change reaches new connections only; the browser of the next job opens fresh ones."""
import os
import re
import time

import httpx

import ig_prefs

GATEWAY = os.environ.get("IGS_VPN_API", "").rstrip("/")
TRACE = "https://www.cloudflare.com/cdn-cgi/trace"
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
KEEP = ("device", "identified", "reason", "logged_in", "via", "person", "session", "location")


async def _call(method, path, body=None):
    """One request to the portal: (status, data), status None when the gateway did not answer. Never through a proxy or the
    system's proxy settings: the gateway is on the office network."""
    if not GATEWAY:                      # no gateway on this computer (the NMarketing node): nothing to ask
        return None, {"error": "not configured"}
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            r = await c.request(method, GATEWAY + path, json=body)
    except httpx.HTTPError as e:
        return None, {"error": type(e).__name__}
    try:
        data = r.json()
    except ValueError:
        data = {}
    return r.status_code, data if isinstance(data, dict) else {}


def _answer(status, data):
    """What the settings page gets: the portal's view of this computer, or why there is none."""
    if status is None:
        return {"ok": False, "reachable": False, "gateway": GATEWAY, "error": data.get("error")}
    if status >= 400:
        msg = data.get("message") or data.get("detail") or data.get("error") or ""
        return {"ok": False, "reachable": True, "gateway": GATEWAY, "status": status, "message": str(msg)[:300]}
    return {"ok": True, "reachable": True, "gateway": GATEWAY, **{k: data.get(k) for k in KEEP}}


async def status():
    return _answer(*await _call("GET", "/api/portal/me"))


async def set_country(code):
    """code: two letters (e.g. "FI"), or "" for Auto (the gateway picks). The portal refuses a country with no working server."""
    code = (code or "").strip().upper()
    if code == "AUTO":
        code = ""
    if code and not COUNTRY_RE.match(code):
        return {"ok": False, "reachable": True, "gateway": GATEWAY, "status": 422, "message": "country"}
    return _answer(*await _call("POST", "/api/portal/location", {"country": code}))


async def login(username, password):
    """Sign this computer in on the gateway (its own portal login); the password goes straight there and is not kept."""
    return _answer(*await _call("POST", "/api/portal/login", {"username": username.strip(), "password": password}))


async def exit_address():
    """The address the internet (Instagram) sees right now, and its country: Cloudflare's trace, through the saved proxy
    when there is one — the same way the jobs go."""
    proxy = ig_prefs.load()["proxy"] or None
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=20) as c:
            r = await c.get(TRACE, headers={"user-agent": "Mozilla/5.0"})
        seen = dict(line.split("=", 1) for line in r.text.splitlines() if "=" in line)
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "via": "proxy" if proxy else "direct"}
    return {"ok": bool(seen.get("ip")), "ip": seen.get("ip", ""), "loc": seen.get("loc", ""), "colo": seen.get("colo", ""),
            "via": "proxy" if proxy else "direct", "ms": round((time.perf_counter() - start) * 1000)}
