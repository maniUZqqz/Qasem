"""Everything the settings page, the inbox cards and the GPU node need to know - assembled from the rows, with NO secret in any of it.

The only thing here that can hold a password is ``node_payload`` (the GPU node needs the real proxy URL to use it) and it is served
only to an authenticated node (see ``views.NodeView``).
"""
from __future__ import annotations

import logging

from django.utils import timezone

from services import egress
from services.egress import catalog, probe, util

from .models import EgressProxy, EgressRoute, EgressSwitch

logger = logging.getLogger(__name__)

SETTINGS_PATH = "/tools/egress"


def ensure_rows() -> dict[str, EgressRoute]:
    rows = {r.service: r for r in EgressRoute.objects.select_related("proxy")}
    for key in catalog.CATALOG:
        if key not in rows:
            rows[key] = EgressRoute.objects.create(service=key)
    return rows


def proxy_json(proxy: EgressProxy) -> dict:
    """A proxy as the API shows it: everything except the password."""
    return {
        "id": proxy.pk, "name": proxy.name, "scheme": proxy.scheme, "host": proxy.host, "port": proxy.port,
        "username": proxy.username, "has_password": bool(proxy.password), "enabled": proxy.enabled, "note": proxy.note,
        "address": f"{proxy.scheme}://{proxy.host}:{proxy.port}", "is_local": proxy.is_local,
        "last_test": proxy.last_test or {}, "last_test_at": proxy.last_test_at,
        "services": sorted(r.service for r in proxy.routes.all()) if hasattr(proxy, "_prefetched_objects_cache") else
        sorted(proxy.routes.values_list("service", flat=True)),
    }


def _health(row: EgressRoute, via: str, proxy_name: str) -> dict:
    health = dict(row.health or {})
    if not health:
        return {"state": "unknown", "detail": "هنوز آزمایش نشده است.", "checked_at": None, "stale": False, "targets": []}
    # a result measured through ANOTHER route says nothing about this one
    health["stale"] = health.get("via") != via or (health.get("proxy") or "") != (proxy_name or "")
    health.setdefault("targets", [])
    return health


def service_json(svc: catalog.Service, row: EgressRoute, master: bool = True) -> dict:
    proxy = row.proxy if row.proxy_id else None
    effective = "proxy" if proxy is not None and proxy.enabled and master else "direct"
    proxy_name = proxy.name if effective == "proxy" else ""
    note = ""
    if proxy is not None and not master:
        note = "کلیدِ کلیِ پراکسی خاموش است؛ این سرویس فعلاً مستقیم می‌رود."
    elif proxy is not None and not proxy.enabled:
        note = f"پراکسیِ «{proxy.name}» خاموش است؛ این سرویس فعلاً مستقیم می‌رود."
    return {
        "key": svc.key, "title": svc.title, "group": svc.group, "summary": svc.summary, "used_by": list(svc.used_by),
        "hosts": list(svc.hosts), "probes": [{"label": a, "url": b} for a, b in svc.probes], "node": svc.node,
        "proxy_id": proxy.pk if proxy is not None else None, "proxy_name": proxy.name if proxy is not None else "",
        "mode": "proxy" if proxy is not None else "direct", "effective": effective, "note": note,
        "health": _health(row, effective, proxy_name),
    }


def node_status() -> list[dict]:
    """What each processing node reports about Abagram's proxy (no URL, no secret - the node masks it itself)."""
    out = []
    try:
        from apps.compute.models import ComputeNode

        for node in ComputeNode.objects.filter(enabled=True):
            report = (node.capabilities or {}).get("abagram")
            if not isinstance(report, dict):
                continue
            out.append({
                "name": node.name, "online": bool(node.online), "proxy": str(report.get("proxy") or ""),
                "has_proxy": bool(report.get("proxy")), "proxy_source": str(report.get("proxy_source") or ""),
                "signed_in": bool(report.get("signed_in")),
            })
    except Exception:  # noqa: BLE001 - the compute app is optional here
        logger.debug("egress: node status unavailable", exc_info=True)
    return out


def overview() -> dict:
    rows = ensure_rows()
    proxies = list(EgressProxy.objects.prefetch_related("routes"))
    master = EgressSwitch.get().enabled
    services = [service_json(svc, rows[svc.key], master) for svc in catalog.CATALOG.values()]
    return {
        "enabled": master,
        "generated_at": timezone.now().isoformat(timespec="seconds"),
        "groups": [{"key": k, "title": t} for k, t in catalog.GROUPS],
        "services": services,
        "proxies": [proxy_json(p) for p in proxies],
        "nodes": node_status(),
        "any_proxy": any(p.enabled for p in proxies),
        "all_direct": not any(s["effective"] == "proxy" for s in services),
        "settings_path": SETTINGS_PATH,
    }


def status_for(service: str) -> dict | None:
    """The one-line state of a service for another page (an inbox channel card): route + the last health check. No network."""
    svc = catalog.get(service)
    if svc is None:
        return None
    row = EgressRoute.objects.select_related("proxy").filter(service=service).first() or EgressRoute(service=service)
    data = service_json(svc, row, not EgressSwitch.objects.filter(pk=1, enabled=False).exists())
    health = data["health"]
    return {
        "service": service, "title": svc.title, "via": data["effective"], "proxy_name": data["proxy_name"],
        "state": health.get("state", "unknown"), "stale": bool(health.get("stale")), "detail": health.get("detail", ""),
        "checked_at": health.get("checked_at"), "settings_path": f"{SETTINGS_PATH}?service={service}", "note": data["note"],
    }


# ------------------------------------------------------------------------------------------------ writes

def apply_proxy_fields(proxy: EgressProxy, data: dict, *, creating: bool) -> None:
    """Fill ``proxy`` from a request body (URL or separate fields). Raises ``util.ProxyInputError`` with a Persian sentence."""
    url = str(data.get("url") or "").strip()
    if url:
        fields = util.parse(url, default_scheme=str(data.get("scheme") or "http"))
        if not fields["username"]:
            # the login is not in the address: it may come from the form's own boxes, or stay as saved
            typed_user = str(data.get("username") or "").strip()
            typed_password = str(data.get("password") or "")
            if typed_user:
                fields["username"] = typed_user
                if typed_password:
                    fields["password"] = typed_password
                elif not creating and not data.get("clear_password") and typed_user == proxy.username:
                    fields["password"] = proxy.password                                  # empty box = «keep the saved password»
            elif not creating and not data.get("clear_password") and "username" not in data:
                fields["username"], fields["password"] = proxy.username, proxy.password       # a bare «host:port» keeps the saved login
        if str(data.get("password") or "") and not fields["username"]:
            raise util.ProxyInputError("رمز بدونِ نامِ کاربری معنی ندارد؛ نامِ کاربری را هم بنویسید.")
        util.clean_fields(fields["scheme"], fields["host"], fields["port"], fields["username"], fields["password"])
    else:
        password = data.get("password")
        if data.get("clear_password"):
            final_password = ""
        elif password:
            final_password = str(password)
        else:
            final_password = proxy.password or ""                                          # empty box = «leave the saved one»
        username = str(data.get("username", proxy.username) or "")
        if password and not username:
            raise util.ProxyInputError("رمز بدونِ نامِ کاربری معنی ندارد؛ نامِ کاربری را هم بنویسید.")
        fields = util.clean_fields(
            data.get("scheme") or proxy.scheme or "http", data.get("host", proxy.host), data.get("port", proxy.port or None),
            username, final_password if username else "",
        )
    for name, value in fields.items():
        setattr(proxy, name, value)
    if "name" in data:
        proxy.name = str(data["name"] or "").strip()[:80]
    if "note" in data:
        proxy.note = str(data["note"] or "").strip()[:200]
    if "enabled" in data:
        proxy.enabled = bool(data["enabled"])
    if not proxy.name:
        proxy.name = f"{proxy.host}:{proxy.port}"[:80]


def route_of(proxy: EgressProxy, service: str = "") -> egress.Route:
    return egress.Route(service, proxy.pk, proxy.name, proxy.scheme, proxy.host, int(proxy.port), proxy.username, proxy.password)


def set_routes(mapping: dict, user=None) -> list[str]:
    """{service: proxy id | None}. Returns the services whose route changed. Raises ``ValueError`` (Persian) for a bad entry."""
    changed = []
    rows = ensure_rows()
    for service, proxy_id in mapping.items():
        if service not in catalog.CATALOG:
            raise ValueError(f"سرویسِ «{service}» در فهرست نیست؛ فقط سرویس‌های همین جدول می‌توانند از پراکسی بروند.")
        proxy = None
        if proxy_id not in (None, "", 0, "direct"):
            proxy = EgressProxy.objects.filter(pk=proxy_id).first()
            if proxy is None:
                raise ValueError("پراکسیِ انتخاب‌شده پیدا نشد.")
        row = rows[service]
        if (row.proxy_id or None) != (proxy.pk if proxy else None):
            row.proxy = proxy
            row.health = {}                              # measured through the old route: say «not tested» instead of lying
            row.checked_at = None
            row.updated_by = getattr(user, "username", "") or ""
            row.save()
            changed.append(service)
            logger.info("egress: %s now goes %s (by %s)", service, f"through proxy «{proxy.name}»" if proxy else "direct", row.updated_by or "?")
    return changed


def set_master(enabled: bool, user=None) -> bool:
    """Flip the master switch. Returns the new state."""
    switch = EgressSwitch.get()
    switch.enabled = bool(enabled)
    switch.updated_by = getattr(user, "username", "") or ""
    switch.save()
    logger.info("egress: master switch %s (by %s)", "on" if switch.enabled else "off", switch.updated_by or "?")
    return switch.enabled


def record_health(service: str, health: dict) -> None:
    row = ensure_rows()[service]
    row.health = health
    row.checked_at = timezone.now()
    row.save(update_fields=["health", "checked_at", "updated_at"])


def record_proxy_test(proxy: EgressProxy, result: dict) -> None:
    proxy.last_test = result
    proxy.last_test_at = timezone.now()
    proxy.save(update_fields=["last_test", "last_test_at", "updated_at"])


def check_service(service: str) -> dict:
    """Probe ONE service through the route it really uses now, store and return the health record."""
    health = probe.check_service(service)
    record_health(service, health)
    return health


def check_routed() -> dict[str, str]:
    """Health-check every service that leaves through a proxy (the scheduled task). Returns {service: state}."""
    out = {}
    for service in list(egress.routes()):
        try:
            out[service] = check_service(service)["state"]
        except Exception:  # noqa: BLE001 - one bad service must not stop the others
            logger.exception("egress: health check of %s crashed", service)
    return out


# ------------------------------------------------------------------------------------------------ the GPU node

def node_payload() -> dict:
    """What the GPU node may use. Only the services marked ``node`` in the catalogue (Instagram: Abagram runs there); the node
    uses it ONLY when it has no proxy of its own (the node decides - see processing/abagram_jobs.py).

    A proxy that points at THIS server (127.0.0.1, a LAN address) is useless to another computer and is not handed out. Chromium
    (which Abagram drives) has no SOCKS login and does not know ``socks5h`` (a SOCKS5 proxy there always resolves names remotely),
    so a SOCKS proxy is passed as ``socks5://host:port`` and only when it needs no login.
    """
    out: dict = {}
    routes = egress.routes()
    for key, svc in catalog.CATALOG.items():
        if not svc.node:
            continue
        route = routes.get(key)
        if route is None:
            out[key] = {"routed": False}
            continue
        if util.is_local_host(route.host):
            out[key] = {"routed": False, "reason": "proxy_is_local_to_server"}
            continue
        if route.is_socks:
            if route.username:
                out[key] = {"routed": False, "reason": "socks_login_unsupported_by_node"}
                continue
            url = f"socks5://{route.host}:{route.port}"
        else:
            url = route.url()
        out[key] = {"routed": True, "proxy_url": url, "name": route.name}
    return out
