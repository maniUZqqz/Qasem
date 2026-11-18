"""The API of the «پراکسی و VPN» settings page (staff only) and the one endpoint the GPU node reads.

None of the responses of the staff API carries a password: a proxy shows ``has_password`` only. The node endpoint is the single place that
returns a real proxy URL (the node needs it to use it) and it answers only an authenticated node, and only for services marked ``node``.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.compute.api import _node, node_api
from services import egress
from services.egress import catalog, probe, util

from . import state
from .models import EgressProxy


def _fail(code: str, message: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": {"code": code, "message": message}, "detail": message}, status=http)


class Staff(APIView):
    permission_classes = [permissions.IsAdminUser]


class OverviewView(Staff):
    def get(self, request):
        return Response(state.overview())


class ProxyListView(Staff):
    def get(self, request):
        return Response({"proxies": state.overview()["proxies"]})

    def post(self, request):
        proxy = EgressProxy()
        try:
            state.apply_proxy_fields(proxy, request.data, creating=True)
        except util.ProxyInputError as exc:
            return _fail("bad_proxy", str(exc))
        if EgressProxy.objects.filter(name=proxy.name).exists():
            return _fail("name_taken", "پراکسی‌ای با این نام هست؛ نامِ دیگری بگذارید.")
        proxy.save()
        return Response(state.proxy_json(proxy), status=status.HTTP_201_CREATED)


class ProxyDetailView(Staff):
    def patch(self, request, pk):
        proxy = get_object_or_404(EgressProxy, pk=pk)
        before = (proxy.scheme, proxy.host, proxy.port, proxy.username, proxy.password)
        try:
            state.apply_proxy_fields(proxy, request.data, creating=False)
        except util.ProxyInputError as exc:
            return _fail("bad_proxy", str(exc))
        if EgressProxy.objects.filter(name=proxy.name).exclude(pk=proxy.pk).exists():
            return _fail("name_taken", "پراکسی‌ای با این نام هست؛ نامِ دیگری بگذارید.")
        if (proxy.scheme, proxy.host, proxy.port, proxy.username, proxy.password) != before:
            proxy.last_test, proxy.last_test_at = {}, None       # the old result belongs to the old address
        proxy.save()
        return Response(state.proxy_json(proxy))

    def delete(self, request, pk):
        proxy = get_object_or_404(EgressProxy, pk=pk)
        proxy.delete()                                              # its routes fall back to «direct» (SET_NULL)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _route_from_body(data):
    """(route, saved proxy or None, tested_as_saved): the proxy the «test» button should try - saved, or typed but not saved yet."""
    saved = None
    if data.get("id"):
        saved = get_object_or_404(EgressProxy, pk=data["id"])
        tmp = EgressProxy(pk=saved.pk, name=saved.name, scheme=saved.scheme, host=saved.host, port=saved.port,
                          username=saved.username, password=saved.password)
    else:
        tmp = EgressProxy(name="آزمایش")
    state.apply_proxy_fields(tmp, data, creating=saved is None)
    tested_as_saved = saved is not None and not (set(data) - {"id"})
    return state.route_of(tmp), saved, tested_as_saved


class ProxyTestView(Staff):
    """The «test» button: which address and country the services see, how fast, and which of them it can reach."""

    def post(self, request, pk=None):
        data = dict(request.data)
        if pk is not None:
            data["id"] = pk
        try:
            route, saved, as_saved = _route_from_body(data)
        except util.ProxyInputError as exc:
            return _fail("bad_proxy", str(exc))
        result = probe.run(route)
        if saved is not None and as_saved:
            state.record_proxy_test(saved, result)
        return Response(result)


class SwitchView(Staff):
    """The master switch: off = every service goes direct (the routing table is kept)."""

    def put(self, request):
        if not isinstance(request.data.get("enabled"), bool):
            return _fail("bad_request", "مقدارِ enabled (روشن/خاموش) فرستاده نشد.")
        state.set_master(request.data["enabled"], request.user)
        return Response(state.overview())


class RoutesView(Staff):
    def put(self, request):
        mapping = request.data.get("routes")
        if not isinstance(mapping, dict):
            return _fail("bad_request", "فهرستِ مسیرها (routes) فرستاده نشد.")
        try:
            changed = state.set_routes(mapping, request.user)
        except ValueError as exc:
            return _fail("bad_route", str(exc))
        data = state.overview()
        data["changed"] = changed
        return Response(data)


class ServiceTestView(Staff):
    def post(self, request, key):
        if key not in catalog.CATALOG:
            return _fail("unknown_service", "سرویس ناشناخته است.", status.HTTP_404_NOT_FOUND)
        health = state.check_service(key)
        return Response({"service": key, "health": health})


class CheckRoutedView(Staff):
    """Health-check every service that goes through a proxy right now."""

    def post(self, request):
        return Response({"checked": state.check_routed()})


class DirectTestView(Staff):
    """«Without a proxy»: what this server reaches directly - the baseline that tells which services need a proxy at all."""

    def post(self, request):
        return Response(probe.run(egress.direct(), echo=True))


@node_api("GET")
def node_proxy(request):
    """For the GPU node: the proxies it may use for work that runs there (Instagram / Abagram). It uses one ONLY when it has none of
    its own (an env var, proxy.txt, the system proxy, or one set inside Abagram).

    The answer can hold a proxy password, so ONLY an authenticated node gets it (``_node`` raises 401 for anything else)."""
    _node(request)
    return Response({"services": state.node_payload(), "ttl_s": 300})
