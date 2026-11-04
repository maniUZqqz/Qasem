"""Helpers of the provider tests: a fake web for the OpenStreetMap / search APIs (httpx.MockTransport), mocked fetchers."""
from __future__ import annotations

import json

import httpx

from apps.growth_engine.integrations import safe_http as sh

PUBLIC = "93.184.216.34"
OVERPASS = "overpass-api.de"
NOMINATIM = "nominatim.openstreetmap.org"

HAMEDAN = [{
    "osm_type": "relation", "osm_id": 5800122, "category": "boundary", "type": "administrative", "importance": 0.62,
    "display_name": "همدان، استان همدان، ایران", "lat": "34.7989", "lon": "48.5148", "boundingbox": ["34.7200", "34.8600", "48.4300", "48.6000"],
}]


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeApis:
    """A fake of the outside APIs. ``handlers`` maps a host to ``f(request) -> httpx.Response``; every request is recorded."""

    def __init__(self):
        self.handlers: dict[str, callable] = {}
        self.requests: list[httpx.Request] = []

    def on(self, host, handler):
        self.handlers[host] = handler
        return self

    def json(self, host, payload, status=200):
        return self.on(host, lambda request: httpx.Response(status, json=payload))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET", f"discovery providers only GET, got {request.method}"
        handler = self.handlers.get(request.headers["host"])
        if handler is None:
            return httpx.Response(404, text="not found")
        return handler(request)

    def hosts(self):
        return [r.headers["host"] for r in self.requests]

    def to(self, host):
        return [r for r in self.requests if r.headers["host"] == host]


def make_fetcher(apis: FakeApis, resolver=None, **kwargs):
    clock = FakeClock()
    throttle = sh.DomainThrottle(clock=clock.time, sleep=clock.sleep)
    fetcher = sh.SafeFetcher(
        resolver=resolver or (lambda host, port: [PUBLIC]), transport=httpx.MockTransport(apis), throttle=throttle, sleep=clock.sleep,
        respect_robots=False, **kwargs,
    )
    return fetcher, clock


def overpass_payload(*elements, remark=""):
    data = {"version": 0.6, "generator": "Overpass API", "elements": list(elements)}
    if remark:
        data["remark"] = remark
    return data


def shop(eid, name, *, etype="node", **tags):
    """An OSM element. Tag names use ``__`` for ``:`` (contact__phone -> contact:phone)."""
    fixed = {k.replace("__", ":"): v for k, v in tags.items()}
    element = {"type": etype, "id": eid, "tags": {"shop": "clothes", "name": name, **fixed}}
    if etype == "node":
        element.update(lat=34.79, lon=48.51)
    else:
        element["center"] = {"lat": 34.79, "lon": 48.51}
    return element


def query_of(request: httpx.Request) -> str:
    return dict(request.url.params).get("data", "")


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
