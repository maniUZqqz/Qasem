"""The proxy / VPN layer: routing, the fake-proxy proofs, Persian errors, the settings API and the guarantee that no secret leaks.

Every network call here goes to a fake on 127.0.0.1 (see ``fakes.py``): a «foreign service», an HTTP/CONNECT proxy and a SOCKS5 proxy
that record what they were asked for. «This call left through the proxy» is proven by the proxy's own log, «that one did not» by the
same log staying empty.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from unittest import mock, skipUnless

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from services import egress
from services.egress import catalog, errors, probe, util

from . import fakes, state
from .models import EgressProxy, EgressRoute

SECRET = "p@ss-SECRET-9x/Zq"          # a password with characters that must be percent-encoded in a URL
TOKEN = "123456:SECRETTOKENSECRETTOKENabcdef"
TG = "http://api.telegram.org/bot%s/getMe" % TOKEN


def http_probes() -> dict:
    """Every probe URL of the catalogue as plain http (the fake proxy connects to the fake target whatever the host is)."""
    return {k: [(label, url.replace("https://", "http://")) for label, url in s.probes] for k, s in catalog.CATALOG.items()}


class EgressCase(TestCase):
    """A fake foreign service, an HTTP proxy and a SOCKS5 proxy in front of it."""

    def setUp(self):
        super().setUp()
        self.target = fakes.Target()
        self.http = fakes.HttpProxy(self.target.port)
        self.socks = fakes.SocksProxy(self.target.port)
        for fake in (self.target, self.http, self.socks):
            self.addCleanup(fake.stop)

    def route(self, service, proxy=None, *, scheme="http", port=None, enabled=True, username="", password="", name="VPN دفتر", host="127.0.0.1"):
        """Send ``service`` through a proxy (the fake HTTP proxy by default)."""
        if proxy is None:
            default = self.http.port if scheme in ("http", "https") else self.socks.port
            proxy, _ = EgressProxy.objects.update_or_create(
                name=name, defaults={"scheme": scheme, "host": host, "port": port or default, "username": username, "password": password,
                                     "enabled": enabled})
        EgressRoute.objects.update_or_create(service=service, defaults={"proxy": proxy})
        egress.invalidate()
        return proxy


# ============================================================================================ the table

class CatalogTests(TestCase):
    def test_every_filtered_service_the_owner_named_is_in_the_table(self):
        for key in ("telegram", "instagram", "whatsapp", "meta", "brave", "google", "search_other", "ai_foreign", "osm"):
            self.assertIn(key, catalog.CATALOG)
        self.assertEqual(catalog.service_for_host("api.telegram.org"), "telegram")
        self.assertEqual(catalog.service_for_host("graph.instagram.com"), "instagram")
        self.assertEqual(catalog.service_for_host("graph.facebook.com"), "whatsapp")       # longer match wins over facebook.com
        self.assertEqual(catalog.service_for_host("www.facebook.com"), "meta")
        self.assertEqual(catalog.service_for_host("lookaside.fbsbx.com"), "whatsapp")
        self.assertEqual(catalog.service_for_host("api.search.brave.com"), "brave")
        self.assertEqual(catalog.service_for_host("news.google.com"), "google")
        self.assertEqual(catalog.service_for_host("API.OpenAI.com."), "ai_foreign")

    def test_everything_else_is_never_in_the_table(self):
        for host in ("nmarketing.ir", "api.metisai.ir", "tapi.bale.ai", "api.eitaa.com", "botapi.rubika.ir", "api.zarinpal.com",
                     "api.novinhub.com", "pypi.org", "registry.npmjs.org", "127.0.0.1", "localhost", "192.168.1.5", "huggingface.co",
                     "hf-mirror.com", "example.ir", "notbrave.com", "evil-telegram.org", "telegram.org.evil.com"):
            self.assertIsNone(catalog.service_for_host(host), host)

    def test_a_catalogue_entry_has_what_the_page_needs(self):
        groups = {k for k, _t in catalog.GROUPS}
        for s in catalog.CATALOG.values():
            self.assertIn(s.group, groups)
            self.assertTrue(s.title and s.summary and s.used_by and s.hosts and s.probes, s.key)


class RoutingTests(EgressCase):
    def test_the_default_is_everything_direct(self):
        self.assertEqual(egress.routes(), {})
        for key in catalog.CATALOG:
            self.assertFalse(egress.route_for(key).proxied, key)
        data = state.overview()
        self.assertTrue(data["all_direct"])
        self.assertFalse(data["any_proxy"])
        self.assertTrue(all(s["effective"] == "direct" and s["mode"] == "direct" for s in data["services"]))

    def test_a_configured_service_leaves_through_the_proxy(self):
        self.route("telegram")
        response = egress.get("telegram", TG, timeout=10)
        self.assertEqual(response.json()["result"]["username"], "testbot")
        self.assertEqual(self.http.forwards, [("GET", TG)])                  # the proxy was asked for exactly this
        self.assertEqual(self.target.requests[0][2], "api.telegram.org")      # and it reached the target under the right Host

    def test_other_services_do_not_use_it(self):
        self.route("telegram")
        direct_url = self.target.url("/x")
        for service in ("brave", "instagram", "whatsapp", None, "", "not_in_the_catalogue"):
            self.assertEqual(egress.get(service, direct_url, timeout=10).status_code, 200, service)
        self.assertEqual(egress.get_for_url(direct_url, timeout=10).status_code, 200)       # an unknown host is direct
        self.assertEqual(requests.get(direct_url, timeout=10).status_code, 200)             # and plain requests are untouched
        self.assertEqual(self.http.events, [], "a service that was not routed must never reach the proxy")

    def test_the_table_decides_by_service_and_by_host(self):
        self.route("telegram")
        self.assertTrue(egress.route_for("telegram").proxied)
        self.assertTrue(egress.route_for_url("https://api.telegram.org/bot1/getMe").proxied)
        for url in ("https://api.search.brave.com/x", "https://graph.facebook.com/x", "https://api.metisai.ir/v1/x",
                    "https://tapi.bale.ai/x", "https://nmarketing.ir/", "http://127.0.0.1:8041/x", "https://pypi.org/simple"):
            self.assertFalse(egress.route_for_url(url).proxied, url)

    def test_the_proxy_never_becomes_a_process_wide_setting(self):
        before = dict(os.environ)
        self.route("telegram")
        egress.get("telegram", TG, timeout=10)
        with egress.session_for("telegram") as session:
            session.get(TG, timeout=10)
        with egress.client_for("telegram", timeout=10) as client:
            client.get(TG)
        self.assertEqual(dict(os.environ), before)
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            self.assertEqual(os.environ.get(name), before.get(name), name)

    def test_a_proxied_session_ignores_the_environment_and_a_direct_one_is_the_plain_old_call(self):
        self.route("telegram")
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            with egress.session_for("telegram") as session:
                self.assertFalse(session.trust_env)
                self.assertEqual(session.get(TG, timeout=10).status_code, 200)       # the env proxy (a closed port) was not used
        egress.invalidate()
        EgressRoute.objects.all().delete()
        egress.invalidate()
        with mock.patch("requests.get") as plain:
            plain.return_value = mock.Mock(status_code=200)
            egress.get("telegram", "https://api.telegram.org/x", timeout=5)
        plain.assert_called_once_with("https://api.telegram.org/x", timeout=5)         # direct = the exact old call

    def test_a_disabled_proxy_or_a_deleted_one_means_direct(self):
        proxy = self.route("telegram")
        self.assertTrue(egress.route_for("telegram").proxied)
        proxy.enabled = False
        proxy.save()
        self.assertFalse(egress.route_for("telegram").proxied)
        proxy.enabled = True
        proxy.save()
        self.assertTrue(egress.route_for("telegram").proxied)
        proxy.delete()
        self.assertFalse(egress.route_for("telegram").proxied)
        self.assertEqual(EgressRoute.objects.get(service="telegram").proxy_id, None)

    def test_a_route_for_a_name_outside_the_catalogue_is_ignored(self):
        proxy = EgressProxy.objects.create(name="x", scheme="http", host="127.0.0.1", port=self.http.port)
        EgressRoute.objects.create(service="my-intranet", proxy=proxy)
        egress.invalidate()
        self.assertEqual(egress.routes(), {})
        self.assertFalse(egress.route_for("my-intranet").proxied)

    def test_the_route_never_prints_its_password(self):
        proxy = self.route("telegram", username="ali", password=SECRET)
        route = egress.route_for("telegram")
        for text in (repr(route), str(route), str(proxy), repr(proxy), route.public(), "%s" % (route,)):
            self.assertNotIn(SECRET, text)
            self.assertNotIn("ali", text)
        self.assertIn(SECRET.replace("/", "%2F").replace("@", "%40"), route.url())          # only the library gets the real URL


class HttpProxyTests(EgressCase):
    def test_login_is_sent_and_checked(self):
        self.http.credentials = ("ali", SECRET)
        self.route("telegram", username="ali", password=SECRET)
        self.assertEqual(egress.get("telegram", TG, timeout=10).status_code, 200)
        self.assertEqual(self.http.forwards, [("GET", TG)])

    def test_a_wrong_password_is_said_in_persian(self):
        self.http.credentials = ("ali", SECRET)
        self.route("telegram", username="ali", password="not-the-password")
        with self.assertRaises(egress.EgressError) as ctx:
            egress.get("telegram", TG, timeout=10)
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertIn("نامِ کاربری یا رمز", str(ctx.exception))
        self.assertIn("VPN دفتر", str(ctx.exception))
        self.assertNotIn("not-the-password", str(ctx.exception))
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_a_closed_port_is_said_in_persian_and_does_not_leak_the_token(self):
        self.route("telegram", port=fakes.closed_port())
        for call in (lambda: egress.get("telegram", TG, timeout=5), lambda: egress.post("telegram", TG, json={"a": 1}, timeout=5)):
            with self.assertRaises(egress.EgressError) as ctx:
                call()
            self.assertEqual(ctx.exception.kind, "refused")
            text = str(ctx.exception)
            self.assertIn("پراکسی", text)
            self.assertIn("برقرار نشد", text)
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(TOKEN, repr(ctx.exception))
            self.assertEqual(egress.reason(ctx.exception), text)
        # every call site that catches requests.RequestException keeps working
        self.assertTrue(issubclass(egress.EgressError, requests.RequestException))

    def test_a_hanging_proxy_times_out_in_persian(self):
        silent = fakes.SilentServer()
        self.addCleanup(silent.stop)
        self.route("telegram", port=silent.port)
        with self.assertRaises(egress.EgressError) as ctx:                      # https ⇒ the proxy never answers the CONNECT
            egress.get("telegram", "https://api.telegram.org/bot1/getMe", timeout=1.5)
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertIn("به‌موقع جواب نداد", str(ctx.exception))
        self.assertIsInstance(ctx.exception, requests.exceptions.Timeout)       # call sites that treat timeouts specially still do
        self.assertIsInstance(ctx.exception, egress.EgressTimeout)
        with self.assertRaises(requests.exceptions.Timeout):                    # plain http: nobody can tell proxy from destination
            egress.get("telegram", TG, timeout=1.5)

    def test_a_proxy_of_the_wrong_type_is_named(self):
        self.route("telegram", scheme="socks5h", port=self.http.port)          # an HTTP proxy port, declared as SOCKS
        with self.assertRaises(egress.EgressError) as ctx:
            egress.get("telegram", TG, timeout=2)
        self.assertIn(ctx.exception.kind, ("protocol", "refused", "tunnel", "timeout"))
        self.assertIn("پراکسی", str(ctx.exception))
        EgressRoute.objects.all().delete()
        self.route("telegram", scheme="http", port=self.socks.port)            # a SOCKS port, declared as HTTP
        with self.assertRaises(requests.RequestException) as ctx:
            egress.get("telegram", TG, timeout=2)
        self.assertIn("پراکسی", str(ctx.exception))

    def test_a_failing_destination_is_not_blamed_on_the_proxy(self):
        self.route("telegram")
        response = egress.get("telegram", "http://api.telegram.org/missing", timeout=10)
        self.assertEqual(response.status_code, 404)                              # the service's own answer, delivered as it is
        with self.assertRaises(requests.HTTPError) as ctx:
            response.raise_for_status()
        self.assertNotIsInstance(ctx.exception, egress.EgressError)

    def test_a_proxy_that_cannot_reach_the_destination_is_named_for_a_tunnel(self):
        down = fakes.HttpProxy(fakes.closed_port())
        self.addCleanup(down.stop)
        self.route("telegram", port=down.port)
        # TLS target ⇒ CONNECT ⇒ the proxy answers 502 ⇒ «the proxy could not reach the destination»
        with self.assertRaises(egress.EgressError) as ctx:
            egress.get("telegram", "https://api.telegram.org/bot1/getMe", timeout=5)
        self.assertEqual(ctx.exception.kind, "tunnel")
        self.assertIn("نتوانست به مقصد", str(ctx.exception))
        self.assertIn("api.telegram.org", str(ctx.exception))

    def test_a_proxy_that_refuses_the_connection_is_named_for_denied(self):
        deny = fakes.HttpProxy(self.target.port, reject=True)
        self.addCleanup(deny.stop)
        self.route("telegram", port=deny.port)
        with self.assertRaises(egress.EgressError) as ctx:
            egress.get("telegram", "https://api.telegram.org/bot1/getMe", timeout=5)
        self.assertEqual(ctx.exception.kind, "denied")
        self.assertIn("مجاز نکرد", str(ctx.exception))


@skipUnless(shutil.which("openssl"), "needs the openssl command line to make a throw-away certificate")
class TunnelTests(EgressCase):
    """Real TLS through a CONNECT tunnel and through SOCKS5 - the way api.telegram.org is really reached."""

    def setUp(self):
        super().setUp()
        directory = fakes.tmpdir()
        self.addCleanup(shutil.rmtree, directory, True)
        self.cert, key = fakes.make_cert(directory)
        self.tls = fakes.Target(cert=(self.cert, key))
        self.addCleanup(self.tls.stop)
        self.http_tls = fakes.HttpProxy(self.tls.port)
        self.socks_tls = fakes.SocksProxy(self.tls.port)
        self.addCleanup(self.http_tls.stop)
        self.addCleanup(self.socks_tls.stop)

    def test_https_goes_through_connect(self):
        self.route("telegram", port=self.http_tls.port)
        response = egress.get("telegram", "https://api.telegram.org/bot1/getMe", timeout=10, verify=self.cert)
        self.assertEqual(response.json()["result"]["username"], "testbot")
        self.assertEqual(self.http_tls.connects, ["api.telegram.org:443"])        # a tunnel to the name, nothing was resolved here

    def test_https_goes_through_socks5h_and_the_proxy_gets_the_name(self):
        self.route("telegram", scheme="socks5h", port=self.socks_tls.port)
        response = egress.get("telegram", "https://api.telegram.org/bot1/getMe", timeout=10, verify=self.cert)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.socks_tls.connects, [("api.telegram.org", 443)])
        self.assertEqual(self.socks_tls.events[0][3], 3)                          # ATYP 3 = a domain name

    def test_httpx_client_through_connect_and_socks(self):
        self.route("telegram", port=self.http_tls.port)
        with egress.client_for("telegram", timeout=10, verify=self.cert) as client:
            self.assertEqual(client.get("https://api.telegram.org/bot1/getMe").status_code, 200)
        self.assertEqual(self.http_tls.connects, ["api.telegram.org:443"])
        EgressRoute.objects.all().delete()
        self.route("telegram", scheme="socks5h", port=self.socks_tls.port)
        with egress.client_for("telegram", timeout=10, verify=self.cert) as client:
            self.assertEqual(client.get("https://api.telegram.org/bot1/getMe").status_code, 200)
        self.assertEqual(self.socks_tls.connects, [("api.telegram.org", 443)])

    def test_a_certificate_error_is_not_blamed_on_the_proxy(self):
        self.route("telegram", port=self.http_tls.port)
        with self.assertRaises(requests.exceptions.SSLError) as ctx:              # the fake CA is not trusted: the destination's problem
            egress.get("telegram", "https://api.telegram.org/bot1/getMe", timeout=10)
        self.assertNotIsInstance(ctx.exception, egress.EgressError)
        self.assertEqual(self.http_tls.connects, ["api.telegram.org:443"])


class SocksTests(EgressCase):
    def test_socks5h_sends_the_name_to_the_proxy(self):
        self.route("telegram", scheme="socks5h")
        self.assertEqual(egress.get("telegram", TG, timeout=10).status_code, 200)
        self.assertEqual(self.socks.connects, [("api.telegram.org", 80)])
        self.assertEqual(self.target.requests[0][2], "api.telegram.org")

    def test_socks5_resolves_the_name_here_and_says_so_when_it_cannot(self):
        self.route("telegram", scheme="socks5")
        with self.assertRaises(egress.EgressError) as ctx:
            egress.get("telegram", "http://name-that-cannot-exist.invalid/x", timeout=5)
        self.assertEqual(ctx.exception.kind, "dns_target")
        self.assertIn("socks5h", str(ctx.exception))

    def test_socks_login_is_checked(self):
        self.socks.credentials = ("ali", SECRET)
        self.route("telegram", scheme="socks5h", username="ali", password=SECRET)
        self.assertEqual(egress.get("telegram", TG, timeout=10).status_code, 200)
        EgressRoute.objects.all().delete()
        self.route("telegram", scheme="socks5h", username="ali", password="wrong-password", name="VPN دوم")
        with self.assertRaises(egress.EgressError) as ctx:
            egress.get("telegram", TG, timeout=10)
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertIn("نامِ کاربری یا رمز", str(ctx.exception))
        self.assertNotIn("wrong-password", str(ctx.exception))

    def test_a_proxy_that_cannot_reach_the_destination_is_said_in_persian(self):
        refusing = fakes.SocksProxy(self.target.port, fail_reply=5)
        self.addCleanup(refusing.stop)
        self.route("telegram", scheme="socks5h", port=refusing.port)
        with self.assertRaises(egress.EgressError) as ctx:
            egress.get("telegram", TG, timeout=10)
        self.assertEqual(ctx.exception.kind, "tunnel")
        self.assertIn("نتوانست به مقصد", str(ctx.exception))

    def test_a_closed_socks_port_is_said_in_persian(self):
        self.route("telegram", scheme="socks5h", port=fakes.closed_port())
        with self.assertRaises(egress.EgressError) as ctx:
            egress.post("telegram", TG, json={}, timeout=5)
        self.assertEqual(ctx.exception.kind, "refused")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_httpx_through_socks(self):
        self.route("telegram", scheme="socks5h")
        with egress.client_for("telegram", timeout=10) as client:
            self.assertEqual(client.get(TG).status_code, 200)
        self.assertEqual(self.socks.connects, [("api.telegram.org", 80)])

    def test_httpx_failures_are_translated_for_the_proxied_route(self):
        import httpx

        self.route("telegram", scheme="socks5h", port=fakes.closed_port())
        route = egress.route_for("telegram")
        with egress.client_for("telegram", timeout=5) as client:
            with self.assertRaises(httpx.HTTPError) as ctx:
                client.get(TG)
        err = egress.httpx_failure(ctx.exception, route, TG)
        self.assertIsNotNone(err)
        self.assertEqual(err.kind, "refused")
        self.assertIsNone(egress.httpx_failure(ctx.exception, egress.direct("telegram"), TG))     # a direct client is never blamed on a proxy


# ============================================================================================ the «test» button

@override_settings(EGRESS_IP_ECHO_URLS=("http://ipinfo.test/json",))
class ProbeTests(EgressCase):
    def test_a_test_says_which_address_and_country_the_services_see_and_what_it_reaches(self):
        self.route("telegram")
        with override_settings(EGRESS_PROBE_URLS=http_probes()):
            result = probe.run(egress.route_for("telegram"), ["telegram", "brave", "instagram", "whatsapp"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["via"], "proxy")
        self.assertEqual(result["ip"], "203.0.113.7")
        self.assertEqual(result["country"], "Germany")
        self.assertEqual(result["country_code"], "DE")
        self.assertEqual(result["city"], "Berlin")
        self.assertIsInstance(result["latency_ms"], int)
        labels = {t["label"] for t in result["targets"]}
        self.assertTrue({"api.telegram.org", "api.search.brave.com", "graph.instagram.com", "graph.facebook.com", "web.whatsapp.com"} <= labels)
        self.assertTrue(all(t["ok"] and isinstance(t["ms"], int) for t in result["targets"]))
        asked = {target for _m, target in self.http.forwards}
        self.assertTrue(any("api.telegram.org" in a for a in asked) and any("api.search.brave.com" in a for a in asked))
        self.assertIn("203.0.113.7", result["summary"])

    def test_the_real_probe_urls_name_the_services_the_owner_asked_for(self):
        urls = " ".join(url for s in catalog.CATALOG.values() for _l, url in s.probes)
        for host in ("api.telegram.org", "graph.instagram.com", "graph.facebook.com", "web.whatsapp.com", "api.search.brave.com"):
            self.assertIn(host, urls)

    def test_a_broken_proxy_is_reported_once_in_persian(self):
        self.route("telegram", port=fakes.closed_port())
        with override_settings(EGRESS_PROBE_URLS=http_probes()):
            result = probe.run(egress.route_for("telegram"), ["telegram", "brave"])
        self.assertFalse(result["ok"])
        self.assertIn("پراکسی", result["proxy_error"])
        self.assertEqual(result["summary"], result["proxy_error"])
        self.assertTrue(all(t.get("proxy_failure") for t in result["targets"]))

    def test_a_service_health_record(self):
        self.route("telegram")
        with override_settings(EGRESS_PROBE_URLS=http_probes()):
            health = probe.check_service("telegram")
        self.assertEqual(health["state"], "ok")
        self.assertEqual(health["via"], "proxy")
        self.assertEqual(health["proxy"], "VPN دفتر")
        self.assertIn("api.telegram.org", health["detail"])
        EgressProxy.objects.update(port=fakes.closed_port())
        egress.invalidate()
        with override_settings(EGRESS_PROBE_URLS=http_probes()):
            down = probe.check_service("telegram")
        self.assertEqual(down["state"], "down")
        self.assertIn("پراکسی", down["detail"])
        self.assertEqual(probe.service_state([]), "unknown")
        self.assertEqual(probe.service_state([{"ok": True}, {"ok": False}]), "partial")

    def test_a_direct_route_can_be_tested_too(self):
        with override_settings(EGRESS_PROBE_URLS={"telegram": [("local", self.target.url("/"))]}):
            result = probe.run(egress.direct(), ["telegram"], echo=False)
        self.assertEqual(result["via"], "direct")
        self.assertTrue(result["ok"])
        self.assertEqual(self.http.events, [])


# ============================================================================================ the settings API

@override_settings(EGRESS_IP_ECHO_URLS=("http://ipinfo.test/json",))
class ApiTests(EgressCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user("staffer", "s@example.com", "pw-12345-pw", is_staff=True)
        self.plain = User.objects.create_user("plain", "p@example.com", "pw-12345-pw")
        self.c = APIClient()
        self.c.force_authenticate(self.staff)
        self.responses: list[str] = []
        self.probes = override_settings(EGRESS_PROBE_URLS=http_probes())
        self.probes.enable()
        self.addCleanup(self.probes.disable)

    def call(self, method, path, data=None):
        response = getattr(self.c, method)("/api/v1/egress/" + path, data, format="json") if data is not None else getattr(self.c, method)("/api/v1/egress/" + path)
        if hasattr(response, "content"):
            self.responses.append(response.content.decode("utf-8", "replace"))
        return response

    def test_only_staff_may_see_or_change_anything(self):
        for who in (APIClient(), self._as(self.plain)):
            for method, path in (("get", "overview/"), ("get", "proxies/"), ("put", "routes/"), ("put", "switch/"), ("post", "proxies/test/"),
                                 ("post", "services/telegram/test/"), ("post", "test-direct/"), ("post", "check-routed/")):
                response = getattr(who, method)("/api/v1/egress/" + path, {}, format="json") if method != "get" else who.get("/api/v1/egress/" + path)
                self.assertIn(response.status_code, (401, 403), (method, path))

    def _as(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_overview_lists_every_service_and_defaults_to_direct(self):
        data = self.call("get", "overview/").json()
        self.assertEqual([s["key"] for s in data["services"]], list(catalog.CATALOG))
        self.assertTrue(data["all_direct"])
        self.assertEqual(data["proxies"], [])
        self.assertEqual(data["settings_path"], "/tools/egress")
        tg = next(s for s in data["services"] if s["key"] == "telegram")
        self.assertEqual((tg["mode"], tg["effective"], tg["health"]["state"]), ("direct", "direct", "unknown"))

    def test_add_a_proxy_from_one_address_or_from_fields_and_never_get_the_password_back(self):
        r = self.call("post", "proxies/", {"name": "VPN دفتر", "url": f"socks5h://ali:{SECRET.replace('/', '%2F').replace('@', '%40')}@127.0.0.1:{self.socks.port}"})
        self.assertEqual(r.status_code, 201, r.content)
        first = r.json()
        self.assertEqual((first["scheme"], first["host"], first["port"], first["username"]), ("socks5h", "127.0.0.1", self.socks.port, "ali"))
        self.assertTrue(first["has_password"])
        self.assertEqual(EgressProxy.objects.get(pk=first["id"]).password, SECRET)         # stored, decoded
        r = self.call("post", "proxies/", {"name": "دوم", "url": "http://10.0.0.9:3128", "username": "bob", "password": SECRET})
        self.assertEqual(r.status_code, 201, r.content)
        r = self.call("post", "proxies/", {"name": "سوم", "scheme": "socks5", "host": "10.0.0.8", "port": 1080, "username": "u", "password": "p"})
        self.assertEqual(r.status_code, 201, r.content)
        third = r.json()
        self.assertEqual(third["address"], "socks5://10.0.0.8:1080")
        listing = self.call("get", "proxies/").json()["proxies"]
        self.assertEqual(len(listing), 3)
        for item in listing:
            self.assertNotIn("password", item)
        for name in ("overview/",):
            self.call("get", name)
        for text in self.responses:
            self.assertNotIn(SECRET, text)
            self.assertNotIn("SECRET-9x", text)

    def test_bad_input_is_refused_in_persian(self):
        cases = [
            ({"url": "ftp://x:1"}, "نوعِ پراکسی"),
            ({"url": "http://127.0.0.1:99999"}, "پورت"),
            ({"url": "127.0.0.1"}, "نشانیِ پراکسی"),
            ({"url": ""}, "نشانیِ پراکسی"),
            ({"scheme": "http", "host": "bad host!", "port": 80}, "نشانیِ پراکسی"),
            ({"scheme": "http", "host": "h.example", "port": "abc"}, "پورت"),
            ({"scheme": "http", "host": "h.example", "port": 8080, "password": "x"}, "رمز بدونِ نامِ کاربری"),
        ]
        for body, expected in cases:
            r = self.call("post", "proxies/", {"name": "x", **body})
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(expected, r.json()["detail"], body)
        self.assertEqual(EgressProxy.objects.count(), 0)
        EgressProxy.objects.create(name="کپی", scheme="http", host="h.example", port=1)
        r = self.call("post", "proxies/", {"name": "کپی", "url": "http://h2.example:2"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("نامِ دیگری", r.json()["detail"])

    def test_editing_keeps_the_saved_password_unless_told_otherwise(self):
        pid = self.call("post", "proxies/", {"name": "p", "url": "http://h.example:8080", "username": "ali", "password": SECRET}).json()["id"]
        r = self.call("patch", f"proxies/{pid}/", {"name": "p", "url": "http://h.example:9090", "username": "ali"})
        self.assertEqual(r.status_code, 200, r.content)
        proxy = EgressProxy.objects.get(pk=pid)
        self.assertEqual((proxy.port, proxy.password), (9090, SECRET))
        r = self.call("patch", f"proxies/{pid}/", {"enabled": False})
        self.assertEqual(EgressProxy.objects.get(pk=pid).password, SECRET)
        self.assertFalse(r.json()["enabled"])
        r = self.call("patch", f"proxies/{pid}/", {"url": "http://h.example:9090", "username": "ali", "clear_password": True})
        self.assertEqual(EgressProxy.objects.get(pk=pid).password, "")
        self.assertFalse(r.json()["has_password"])
        r = self.call("patch", f"proxies/{pid}/", {"url": "http://h.example:9090", "username": "ali", "password": "new-pw"})
        self.assertEqual(EgressProxy.objects.get(pk=pid).password, "new-pw")
        for text in self.responses:
            self.assertNotIn(SECRET, text)
            self.assertNotIn("new-pw", text)

    def test_routes_are_set_through_the_api_and_really_change_where_calls_go(self):
        pid = self.call("post", "proxies/", {"name": "VPN دفتر", "url": f"http://127.0.0.1:{self.http.port}"}).json()["id"]
        r = self.call("put", "routes/", {"routes": {"telegram": pid, "brave": pid}})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(r.json()["changed"]), ["brave", "telegram"])
        data = r.json()
        for key in ("telegram", "brave"):
            row = next(s for s in data["services"] if s["key"] == key)
            self.assertEqual((row["mode"], row["effective"], row["proxy_name"]), ("proxy", "proxy", "VPN دفتر"))
        self.assertFalse(data["all_direct"])
        untouched = next(s for s in data["services"] if s["key"] == "instagram")
        self.assertEqual(untouched["effective"], "direct")
        # ...and the calls follow, at once (the table is read from the database, not from the process start)
        egress.get("telegram", TG, timeout=10)
        egress.get("brave", "http://api.search.brave.com/res/v1/web/search?q=x", timeout=10)
        egress.get("instagram", self.target.url("/ig"), timeout=10)
        self.assertEqual(len(self.http.forwards), 2)
        r = self.call("put", "routes/", {"routes": {"telegram": None}})
        self.assertEqual(r.json()["changed"], ["telegram"])
        self.assertFalse(egress.route_for("telegram").proxied)
        self.assertTrue(egress.route_for("brave").proxied)

    def test_the_master_switch_sends_everything_direct_and_brings_the_routes_back(self):
        pid = self.call("post", "proxies/", {"name": "p", "url": f"http://127.0.0.1:{self.http.port}"}).json()["id"]
        self.call("put", "routes/", {"routes": {"telegram": pid, "instagram": pid}})
        self.assertTrue(self.call("get", "overview/").json()["enabled"])
        egress.get("telegram", TG, timeout=10)
        self.assertEqual(len(self.http.forwards), 1)
        r = self.call("put", "switch/", {"enabled": False})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertFalse(data["enabled"])
        self.assertTrue(data["all_direct"])
        row = next(s for s in data["services"] if s["key"] == "telegram")
        self.assertEqual((row["mode"], row["effective"]), ("proxy", "direct"))            # the table is kept...
        self.assertIn("کلیدِ کلیِ پراکسی خاموش", row["note"])
        self.assertFalse(egress.route_for("telegram").proxied)                            # ...but nothing leaves through a proxy
        self.assertEqual(egress.get("telegram", self.target.url("/x"), timeout=10).status_code, 200)
        self.assertEqual(len(self.http.forwards), 1)
        self.assertEqual(state.node_payload()["instagram"], {"routed": False})
        self.assertEqual(state.status_for("telegram")["via"], "direct")
        self.assertEqual(EgressRoute.objects.get(service="telegram").proxy_id, pid)
        r = self.call("put", "switch/", {"enabled": True})
        self.assertTrue(r.json()["enabled"])
        self.assertTrue(egress.route_for("telegram").proxied)
        self.assertTrue(egress.route_for("instagram").proxied)
        self.assertEqual(self.call("put", "switch/", {"enabled": "yes"}).status_code, 400)
        self.assertEqual(self.call("put", "switch/", {}).status_code, 400)

    def test_bad_routes_are_refused(self):
        pid = self.call("post", "proxies/", {"name": "p", "url": "http://h.example:8080"}).json()["id"]
        self.assertEqual(self.call("put", "routes/", {"routes": {"my-intranet": pid}}).status_code, 400)
        self.assertEqual(self.call("put", "routes/", {"routes": {"telegram": 9999}}).status_code, 400)
        self.assertEqual(self.call("put", "routes/", {"routes": [1, 2]}).status_code, 400)
        self.assertEqual(self.call("put", "routes/", {}).status_code, 400)
        self.assertEqual(EgressRoute.objects.exclude(proxy=None).count(), 0)

    def test_a_disabled_proxy_says_so_and_the_service_goes_direct(self):
        pid = self.call("post", "proxies/", {"name": "p", "url": f"http://127.0.0.1:{self.http.port}", "enabled": False}).json()["id"]
        self.call("put", "routes/", {"routes": {"telegram": pid}})
        row = next(s for s in self.call("get", "overview/").json()["services"] if s["key"] == "telegram")
        self.assertEqual((row["mode"], row["effective"]), ("proxy", "direct"))
        self.assertIn("خاموش است", row["note"])

    def test_deleting_a_proxy_turns_its_services_direct(self):
        pid = self.call("post", "proxies/", {"name": "p", "url": f"http://127.0.0.1:{self.http.port}"}).json()["id"]
        self.call("put", "routes/", {"routes": {"telegram": pid}})
        self.assertEqual(self.call("delete", f"proxies/{pid}/").status_code, 204)
        self.assertTrue(self.call("get", "overview/").json()["all_direct"])
        self.assertFalse(egress.route_for("telegram").proxied)

    def test_the_test_button_of_a_typed_proxy_and_of_a_saved_one(self):
        r = self.call("post", "proxies/test/", {"url": f"http://127.0.0.1:{self.http.port}"})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertTrue(data["ok"], data)
        self.assertEqual((data["ip"], data["country_code"]), ("203.0.113.7", "DE"))
        self.assertGreaterEqual(len(data["targets"]), len(catalog.CATALOG))
        self.assertEqual(EgressProxy.objects.count(), 0)                          # a typed test saves nothing
        pid = self.call("post", "proxies/", {"name": "p", "url": f"http://ali:{SECRET.replace('/', '%2F').replace('@', '%40')}@127.0.0.1:{self.http.port}"}).json()["id"]
        self.http.credentials = ("ali", SECRET)
        r = self.call("post", f"proxies/{pid}/test/", {})
        self.assertTrue(r.json()["ok"], r.json())
        proxy = EgressProxy.objects.get(pk=pid)
        self.assertEqual(proxy.last_test["ip"], "203.0.113.7")
        self.assertIsNotNone(proxy.last_test_at)
        self.assertNotIn(SECRET, json.dumps(proxy.last_test))
        listing = self.call("get", "proxies/").json()["proxies"][0]
        self.assertEqual(listing["last_test"]["country"], "Germany")
        for text in self.responses:
            self.assertNotIn(SECRET, text)

    def test_the_test_button_with_a_wrong_proxy_says_why(self):
        r = self.call("post", "proxies/test/", {"url": f"http://127.0.0.1:{fakes.closed_port()}"})
        data = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(data["ok"])
        self.assertIn("پراکسی", data["proxy_error"])
        r = self.call("post", "proxies/test/", {"url": "nonsense"})
        self.assertEqual(r.status_code, 400)
        r = self.call("post", "proxies/test/", {"url": f"http://ali:{SECRET.replace('/', '%2F').replace('@', '%40')}@127.0.0.1:{fakes.closed_port()}"})
        self.assertNotIn(SECRET, r.content.decode())

    def test_a_service_test_stores_the_health_that_the_page_and_the_cards_show(self):
        pid = self.call("post", "proxies/", {"name": "p", "url": f"http://127.0.0.1:{self.http.port}"}).json()["id"]
        self.call("put", "routes/", {"routes": {"telegram": pid}})
        r = self.call("post", "services/telegram/test/", {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["health"]["state"], "ok")
        row = next(s for s in self.call("get", "overview/").json()["services"] if s["key"] == "telegram")
        self.assertEqual(row["health"]["state"], "ok")
        self.assertFalse(row["health"]["stale"])
        short = state.status_for("telegram")
        self.assertEqual((short["via"], short["state"], short["proxy_name"]), ("proxy", "ok", "p"))
        self.assertEqual(short["settings_path"], "/tools/egress?service=telegram")
        self.assertEqual(self.call("post", "services/nope/test/", {}).status_code, 404)
        # changing the route makes the old result «stale» instead of letting it lie
        self.call("put", "routes/", {"routes": {"telegram": None}})
        short = state.status_for("telegram")
        self.assertEqual(short["via"], "direct")
        self.assertEqual(short["state"], "unknown")

    def test_check_routed_does_nothing_when_everything_is_direct_and_tests_the_routed_ones(self):
        self.assertEqual(state.check_routed(), {})
        self.assertEqual(self.call("post", "check-routed/", {}).json()["checked"], {})
        pid = self.call("post", "proxies/", {"name": "p", "url": f"http://127.0.0.1:{self.http.port}"}).json()["id"]
        self.call("put", "routes/", {"routes": {"telegram": pid, "brave": pid}})
        got = self.call("post", "check-routed/", {}).json()["checked"]
        self.assertEqual(got, {"telegram": "ok", "brave": "ok"})
        from .tasks import check_routed

        self.assertEqual(check_routed(), {"telegram": "ok", "brave": "ok"})

    def test_direct_test_is_the_baseline(self):
        with override_settings(EGRESS_PROBE_URLS={k: [(label, self.target.url("/"))] for k, s in catalog.CATALOG.items() for label, _u in s.probes[:1]},
                               EGRESS_IP_ECHO_URLS=(self.target.url("/json"),)):
            r = self.call("post", "test-direct/", {})
        data = r.json()
        self.assertEqual(data["via"], "direct")
        self.assertTrue(data["ok"])
        self.assertEqual(self.http.events, [])

    def test_no_response_and_no_log_ever_holds_a_password(self):
        records: list[str] = []

        class Catch(logging.Handler):
            def emit(self, record):
                records.append(self.format(record) + " " + str(record.args) + " " + str(record.exc_text))

        handler = Catch(level=logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        pid = self.call("post", "proxies/", {"name": "p", "url": f"socks5h://ali:{SECRET.replace('/', '%2F').replace('@', '%40')}@127.0.0.1:{fakes.closed_port()}"}).json()["id"]
        self.call("put", "routes/", {"routes": {"telegram": pid}})
        for method, path, body in (("post", f"proxies/{pid}/test/", {}), ("post", "services/telegram/test/", {}), ("post", "check-routed/", {}),
                                   ("get", "overview/", None), ("get", "proxies/", None), ("patch", f"proxies/{pid}/", {"note": "n"}),
                                   ("put", "routes/", {"routes": {"brave": pid}})):
            self.call(method, path, body)
        with self.assertRaises(egress.EgressError):
            egress.post("telegram", TG, json={"text": "hi"}, timeout=3)
        egress.reason(RuntimeError("x"))
        proxy = EgressProxy.objects.get(pk=pid)
        for text in self.responses + records + [str(proxy), repr(proxy), json.dumps(proxy.last_test), json.dumps(EgressRoute.objects.get(service="telegram").health)]:
            self.assertNotIn(SECRET, text)
            self.assertNotIn("SECRET-9x", text)
            self.assertNotIn(TOKEN, text)
        self.assertTrue(records, "the logging capture itself must have worked")


# ============================================================================================ the GPU node

class NodeTests(EgressCase):
    def test_nothing_is_handed_out_by_default(self):
        self.assertEqual(state.node_payload(), {"instagram": {"routed": False}})

    def test_only_a_proxy_the_node_can_really_use_is_handed_out(self):
        self.route("instagram", host="203.0.113.5", port=3128, name="خارجی")
        got = state.node_payload()["instagram"]
        self.assertEqual((got["routed"], got["proxy_url"], got["name"]), (True, "http://203.0.113.5:3128", "خارجی"))
        EgressRoute.objects.all().delete()
        self.route("instagram")                                                    # 127.0.0.1 = this server: meaningless for another computer
        self.assertEqual(state.node_payload()["instagram"], {"routed": False, "reason": "proxy_is_local_to_server"})
        EgressRoute.objects.all().delete()
        EgressProxy.objects.all().delete()
        self.route("instagram", scheme="socks5h", host="203.0.113.6", port=1080, username="a", password="b")
        self.assertEqual(state.node_payload()["instagram"]["reason"], "socks_login_unsupported_by_node")
        EgressRoute.objects.all().delete()
        EgressProxy.objects.all().delete()
        self.route("instagram", scheme="socks5h", host="203.0.113.6", port=1080)
        self.assertEqual(state.node_payload()["instagram"]["proxy_url"], "socks5://203.0.113.6:1080")

    def test_a_service_that_is_not_for_the_node_is_never_handed_out(self):
        self.route("telegram", host="203.0.113.5", port=3128)
        self.assertNotIn("telegram", state.node_payload())

    def test_the_node_endpoint_answers_only_an_authenticated_node(self):
        from apps.compute.models import ComputeNode

        self.route("instagram", host="203.0.113.5", port=3128, username="ali", password=SECRET)
        anonymous = APIClient().get("/api/v1/egress/node/")
        self.assertIn(anonymous.status_code, (401, 403))
        self.assertNotIn(SECRET, anonymous.content.decode())
        staff = APIClient()
        staff.force_authenticate(User.objects.create_user("s", "s@e.com", "pw", is_staff=True))
        self.assertIn(staff.get("/api/v1/egress/node/").status_code, (401, 403))     # a person, even staff, is not a node
        node = ComputeNode.objects.create(name="N", token="tok-egress-test-token")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Node " + node.token)
        r = c.get("/api/v1/egress/node/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["services"]["instagram"]["routed"])
        self.assertIn("203.0.113.5:3128", r.json()["services"]["instagram"]["proxy_url"])
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION="Node wrong")
        self.assertEqual(bad.get("/api/v1/egress/node/").status_code, 401)

    def test_node_status_shows_what_the_node_reports_without_a_url(self):
        from apps.compute.models import ComputeNode

        ComputeNode.objects.create(name="GPU", token="t", capabilities={"abagram": {"proxy": "http://127.0.0.1:10809", "proxy_source": "site", "signed_in": True}})
        rows = state.node_status()
        self.assertEqual(rows[0]["name"], "GPU")
        self.assertEqual((rows[0]["has_proxy"], rows[0]["proxy_source"]), (True, "site"))


# ============================================================================================ small pieces

class ParsingTests(TestCase):
    def test_the_formats_people_paste(self):
        self.assertEqual(util.parse("socks5h://127.0.0.1:10808")["scheme"], "socks5h")
        self.assertEqual(util.parse("127.0.0.1:10808"), {"scheme": "http", "host": "127.0.0.1", "port": 10808, "username": "", "password": ""})
        got = util.parse("user:p%40ss@host.example:8080")
        self.assertEqual((got["username"], got["password"], got["host"]), ("user", "p@ss", "host.example"))
        got = util.parse("203.0.113.9:3128:bob:pw")                                 # what proxy sellers send
        self.assertEqual((got["host"], got["port"], got["username"], got["password"]), ("203.0.113.9", 3128, "bob", "pw"))
        self.assertEqual(util.parse("[::1]:1080", "socks5")["host"], "::1")
        with self.assertRaises(util.ProxyInputError):
            util.parse("http://nohost")

    def test_local_addresses_are_recognised(self):
        for host in ("127.0.0.1", "localhost", "10.1.2.3", "192.168.0.4", "::1", "172.16.0.1", "proxy.local"):
            self.assertTrue(util.is_local_host(host), host)
        for host in ("203.0.113.5", "proxy.example.com", "8.8.8.8"):
            self.assertFalse(util.is_local_host(host), host)

    def test_error_text_never_quotes_the_url(self):
        route = egress.Route("telegram", 1, "VPN", "http", "10.0.0.1", 3128)
        exc = requests.exceptions.ProxyError("Cannot connect to proxy: HTTPSConnectionPool(host='api.telegram.org', port=443): "
                                             "Max retries exceeded with url: /bot%s/getMe (Caused by ProxyError('x', ConnectionRefusedError(111, 'Connection refused')))" % TOKEN)
        err = errors.from_exception(exc, route, "https://api.telegram.org/bot%s/getMe" % TOKEN)
        self.assertEqual(err.kind, "refused")
        self.assertNotIn(TOKEN, str(err))
        self.assertIsNone(errors.from_exception(requests.exceptions.ReadTimeout("read timed out"), route, ""))
