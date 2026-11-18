"""The call sites: every place that talks to a filtered outside service goes through ``services.egress``, and nothing else does.

Inbox adapters (Telegram, WhatsApp), the channel cards, the legacy Telegram sender, receipts, the research / trends feeds, the growth
engine's fetcher (Brave / Google / Bing / DuckDuckGo / Instagram pages) and the foreign AI / media APIs - each against the fake proxies of
``fakes.py`` (never the real internet) - plus a static audit that fails when a new direct call to a catalogue host appears.
"""
from __future__ import annotations

import re
import types
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings

from apps.inbox import adapters, dispatch
from apps.inbox.tests_base import InboxTestCase
from services import egress
from services.egress import catalog

from . import fakes
from .models import EgressProxy, EgressRoute
from .tests import SECRET, TG, TOKEN, EgressCase

BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class _World:
    """A fake foreign service with an HTTP and a SOCKS5 proxy in front of it, for a test case that has its own base class."""

    def start(self):
        self.target = fakes.Target()
        self.http = fakes.HttpProxy(self.target.port)
        self.socks = fakes.SocksProxy(self.target.port)
        for fake in (self.target, self.http, self.socks):
            self.addCleanup(fake.stop)

    def route(self, service, *, scheme="http", port=None, name="VPN دفتر", host="127.0.0.1"):
        port = port or (self.http.port if scheme in ("http", "https") else self.socks.port)
        proxy = EgressProxy.objects.create(name=name, scheme=scheme, host=host, port=port)
        EgressRoute.objects.update_or_create(service=service, defaults={"proxy": proxy})
        egress.invalidate()
        return proxy


def bases(**kw):
    out = {k: "http://127.0.0.1:1" for k in ("BALE", "EITAA", "RUBIKA", "WHATSAPP", "TELEGRAM")}
    out.update(kw)
    return out


# ============================================================================================ inbox

class InboxRoutingTests(_World, InboxTestCase):
    def setUp(self):
        super().setUp()
        self.start()
        cache.clear()

    def adapter(self, kind, **kw):
        return adapters.for_connection(self.connect(kind, **kw))

    def test_telegram_calls_leave_through_the_proxy(self):
        self.route("telegram")
        with override_settings(INBOX_API_BASES=bases(TELEGRAM="http://api.telegram.org")):
            adapter = self.adapter("TELEGRAM", token=BOT_TOKEN)
            health = adapter.health()
            sent = adapter.send("42", "سلام")
            polled = adapter.poll("")
        self.assertTrue(health.ok, health.detail)
        self.assertEqual(health.account, "@testbot")
        self.assertTrue(sent.ok, sent.reason)
        self.assertEqual(polled.messages, [])
        methods = [(m, u.rsplit("/", 1)[-1]) for m, u in self.http.forwards]
        self.assertEqual(methods, [("POST", "getMe"), ("POST", "sendMessage"), ("POST", "getUpdates")])
        self.assertTrue(all(u.startswith(f"http://api.telegram.org/bot{BOT_TOKEN}/") for _m, u in self.http.forwards))

    def test_bale_eitaa_and_rubika_never_use_the_proxy_even_when_everything_else_does(self):
        for key in ("telegram", "instagram", "whatsapp", "meta", "brave", "google", "ai_foreign"):
            self.route(key, name=f"p-{key}")
        local = self.target.url("")
        with override_settings(INBOX_API_BASES=bases(BALE=local)):
            health = self.adapter("BALE", token=BOT_TOKEN).health()
        self.assertTrue(health.ok, health.detail)
        self.assertEqual(self.target.requests[0][1].rsplit("/", 1)[-1], "getMe")
        self.assertEqual(self.http.events, [], "Bale is an Iranian service: it must never be sent through a proxy")
        self.assertEqual(self.socks.events, [])

    def test_a_wrong_proxy_is_named_in_persian_and_the_token_stays_out(self):
        self.route("telegram", port=fakes.closed_port())
        with override_settings(INBOX_API_BASES=bases(TELEGRAM="http://api.telegram.org")):
            adapter = self.adapter("TELEGRAM", token=BOT_TOKEN)
            sent = adapter.send("42", "سلام")
            health = adapter.health()
        for text in (sent.reason, health.detail):
            self.assertIn("پراکسی", text)
            self.assertIn("برقرار نشد", text)
            self.assertNotIn(BOT_TOKEN, text)
            self.assertNotIn("ABCDEFGHIJ", text)
        self.assertFalse(sent.ok)

    def test_without_a_proxy_the_error_points_at_the_settings_page(self):
        adapter = self.adapter("TELEGRAM", token=BOT_TOKEN)                         # INBOX_API_BASES: a closed port, no route
        health = adapter.health()
        self.assertFalse(health.ok)
        self.assertIn("در دسترس نبود", health.detail)
        self.assertIn("پراکسی و VPN", health.detail)
        self.assertIn("بله، ایتا یا روبیکا", health.detail)

    def test_whatsapp_send_and_health_leave_through_the_proxy(self):
        self.route("whatsapp")
        with override_settings(INBOX_API_BASES=bases(WHATSAPP="http://graph.facebook.com")):
            adapter = self.adapter("WHATSAPP", token="EAAB-test-token", config={"phone_number_id": "1234567890"})
            sent = adapter.send("989120000000", "سلام")
            health = adapter.health()
        self.assertTrue(sent.ok, sent.reason)
        self.assertEqual(sent.external_id, "wamid.TEST1")
        self.assertTrue(health.ok, health.detail)
        self.assertEqual(health.account, "+98 912 000 0000")
        urls = [u for _m, u in self.http.forwards]
        self.assertTrue(any("/v20.0/1234567890/messages" in u for u in urls), urls)
        self.assertTrue(any(u.endswith("/v20.0/1234567890?fields=display_phone_number%2Cverified_name") for u in urls), urls)

    def test_whatsapp_through_a_wrong_proxy_says_so(self):
        self.route("whatsapp", port=fakes.closed_port())
        with override_settings(INBOX_API_BASES=bases(WHATSAPP="http://graph.facebook.com")):
            adapter = self.adapter("WHATSAPP", token="EAAB-test-token", config={"phone_number_id": "1234567890"})
            sent = adapter.send("989120000000", "x")
            health = adapter.health()
        self.assertFalse(sent.ok)
        self.assertIn("پراکسی", sent.reason)
        self.assertIn("پراکسی", health.detail)
        self.assertNotIn("EAAB-test-token", sent.reason + health.detail)

    def test_the_card_message_says_to_connect_a_proxy_and_links_to_the_settings(self):
        got = dispatch.probe_host(adapters.TelegramAdapter)                          # INBOX_API_BASES = a closed port, no route
        self.assertFalse(got["reachable"])
        self.assertEqual(got["via"], "direct")
        self.assertIn("دسترسی ندارد", got["message"])
        self.assertIn("با پراکسی وصل کنید", got["message"])
        self.assertIn("پراکسی و VPN", got["message"])
        self.assertIn("بله، ایتا یا روبیکا", got["message"])
        self.assertEqual(got["service"], "telegram")
        self.assertEqual(got["settings_path"], "/tools/egress?service=telegram")

    def test_the_card_turns_green_through_a_working_proxy_and_names_a_broken_one(self):
        self.route("telegram")
        with override_settings(INBOX_API_BASES=bases(TELEGRAM="http://api.telegram.org")):
            ok = dispatch.probe_host(adapters.TelegramAdapter)
        self.assertTrue(ok["reachable"])
        self.assertEqual((ok["via"], ok["proxy"], ok["message"]), ("proxy", "VPN دفتر", ""))
        EgressProxy.objects.update(port=fakes.closed_port())
        egress.invalidate()
        with override_settings(INBOX_API_BASES=bases(TELEGRAM="http://api.telegram.org")):
            bad = dispatch.probe_host(adapters.TelegramAdapter)
        self.assertFalse(bad["reachable"])
        self.assertEqual(bad["via"], "proxy")
        self.assertIn("از راهِ پراکسیِ «VPN دفتر»", bad["message"])
        self.assertIn("برقرار نشد", bad["message"])
        self.assertIn("پراکسی و VPN", bad["message"])
        self.assertNotIn("با پراکسی وصل کنید", bad["message"])

    def rows(self):
        return {c["kind"]: c for c in self.api(self.admin).get(self.url("channels/")).json()["channels"]}

    def test_the_channel_cards_carry_the_route_and_the_health(self):
        rows = self.rows()
        for kind in ("BALE", "EITAA", "RUBIKA", "SMS", "WEBCHAT"):
            self.assertNotIn("egress", rows[kind], kind)
        for kind, service in (("TELEGRAM", "telegram"), ("WHATSAPP", "whatsapp")):
            card = rows[kind]["egress"]
            self.assertEqual((card["service"], card["via"], card["state"]), (service, "direct", "unknown"))
            self.assertEqual(card["settings_path"], f"/tools/egress?service={service}")
        self.assertIn("با پراکسی وصل کنید", rows["TELEGRAM"]["network"]["message"])
        self.assertEqual(rows["TELEGRAM"]["network"]["settings_path"], "/tools/egress?service=telegram")
        # routing Telegram changes the card at once (the cached «unreachable» answer is dropped with the route)
        self.route("telegram", port=fakes.closed_port())
        rows = self.rows()
        self.assertEqual(rows["TELEGRAM"]["egress"]["via"], "proxy")
        self.assertEqual(rows["TELEGRAM"]["egress"]["proxy_name"], "VPN دفتر")
        self.assertEqual(rows["TELEGRAM"]["network"]["via"], "proxy")
        self.assertIn("از راهِ پراکسیِ «VPN دفتر»", rows["TELEGRAM"]["network"]["message"])
        self.assertEqual(rows["WHATSAPP"]["egress"]["via"], "direct")
        # a measured health shows on the card
        from apps.egress import state

        state.record_health("telegram", {"state": "down", "via": "proxy", "proxy": "VPN دفتر", "detail": "x", "checked_at": "2026-11-18T10:00:00+00:00", "targets": []})
        card = self.rows()["TELEGRAM"]["egress"]
        self.assertEqual((card["state"], card["stale"]), ("down", False))

    def test_the_card_row_never_holds_a_proxy_secret(self):
        proxy = self.route("telegram")
        proxy.username, proxy.password = "ali", SECRET
        proxy.save()
        text = self.api(self.admin).get(self.url("channels/")).content.decode()
        self.assertNotIn(SECRET, text)


# ============================================================================================ legacy senders, receipts, feeds

class LegacySiteTests(EgressCase):
    def test_the_legacy_telegram_sender_and_receipts_go_through_the_proxy(self):
        from apps.customers import receipts
        from services.publishing import channels

        self.route("telegram")
        with mock.patch.object(channels, "telegram_token", return_value=TOKEN):
            channels._send_telegram(types.SimpleNamespace(profile=None), "42", "hi")
            self.assertEqual(self.http.connects, ["api.telegram.org:443"])          # https ⇒ a CONNECT tunnel to the name
            self.assertIsNone(receipts.fetch(types.SimpleNamespace(profile=None, id=1), {"kind": "telegram_file", "file_id": "f"}))
        self.assertEqual(self.http.connects, ["api.telegram.org:443", "api.telegram.org:443"])

    def test_the_legacy_telegram_sender_names_a_broken_proxy_and_hides_the_token(self):
        from services.publishing import channels

        self.route("telegram", port=fakes.closed_port())
        with mock.patch.object(channels, "telegram_token", return_value=TOKEN):
            result = channels._send_telegram(types.SimpleNamespace(profile=None), "42", "hi")
        self.assertFalse(result["sent"])
        self.assertIn("پراکسی", result["reason"])
        self.assertNotIn(TOKEN, result["reason"])
        egress.invalidate()
        EgressRoute.objects.all().delete()
        egress.invalidate()
        with mock.patch.object(channels, "telegram_token", return_value=TOKEN), mock.patch("requests.post", side_effect=__import__("requests").ConnectionError("x")):
            result = channels._send_telegram(types.SimpleNamespace(profile=None), "42", "hi")
        self.assertEqual(result["reason"], "تلگرام در دسترس نبود؛ کمی بعد دوباره امتحان کنید.")      # unchanged without a proxy

    def test_a_receipt_photo_from_an_ordinary_url_is_fetched_directly(self):
        from apps.customers import receipts

        self.route("telegram")
        got = receipts.fetch(types.SimpleNamespace(profile=None, id=1), {"kind": "url", "url": self.target.url("/img.png")})
        self.assertIsNotNone(got)
        self.assertEqual(self.http.events, [])

    def test_the_research_feeds_use_the_right_service(self):
        from services.research import trends, web

        response = mock.Mock(content=b"<rss><channel></channel></rss>")
        response.raise_for_status = lambda: None
        response.json = lambda: {"web": {"results": []}}
        with mock.patch.object(egress, "get", return_value=response) as get:
            web.google_news("q")
            trends.fetch_region("IR")
            with mock.patch.dict(settings.UPMARKET_RESEARCH, {"BRAVE_API_KEY": "k"}):
                web._search_brave("q")
        self.assertEqual([c.args[0] for c in get.call_args_list], ["google", "google", "brave"])
        self.assertEqual(get.call_args_list[0].args[1], "https://news.google.com/rss/search")
        self.assertEqual(get.call_args_list[2].args[1], "https://api.search.brave.com/res/v1/web/search")

    def test_the_trends_feed_through_a_proxy_and_a_broken_one(self):
        from services.research import trends

        self.route("google", port=fakes.closed_port())
        with self.assertRaises(trends.TrendsUnavailable) as ctx:
            trends.fetch_region("IR")
        self.assertIn("پراکسی", str(ctx.exception))

    def test_the_media_and_ai_apis_follow_their_host(self):
        from services.media import api_media

        resolved = types.SimpleNamespace(base_url="http://api.replicate.com/v1/predictions", options={}, api_key="key", timeout_s=10)
        self.route("ai_foreign")
        out = api_media._submit(resolved, {"input": 1})                                # a Replicate-style endpoint: «ai_foreign»
        self.assertTrue(out["ok"])
        self.assertEqual(self.http.forwards, [("POST", "http://api.replicate.com/v1/predictions")])
        local = types.SimpleNamespace(base_url=self.target.url("/v1/run"), options={}, api_key="key", timeout_s=10)
        api_media._submit(local, {"input": 1})                                         # a local / unknown host stays direct
        self.assertEqual(len(self.http.forwards), 1)
        self.assertEqual(self.target.requests[-1][1], "/v1/run")

    def test_the_instagram_status_text_points_at_the_one_central_place(self):
        from apps.igtrends import status

        for problem in ("not_signed_in", "unreachable"):
            self.assertIn("پراکسی و VPN", status.instruction(problem, {"url": "http://127.0.0.1:8791/"}, "GPU"))


# ============================================================================================ the growth engine's fetcher

class FetcherTests(EgressCase):
    def fetcher(self, **kw):
        from apps.growth_engine.integrations import safe_http as sh

        def boom(host, port):
            raise AssertionError("a proxied host must not be resolved here: %s" % host)

        return sh.SafeFetcher(resolver=kw.pop("resolver", boom), respect_robots=False, **kw)

    def api(self, fetcher, url="http://api.search.brave.com/res/v1/web/search", **kw):
        return fetcher.get_api(url, params={"q": "باشگاه"}, retries=0, delay=0, **kw)

    def test_a_routed_search_api_goes_through_the_proxy_without_resolving_the_name_here(self):
        self.route("brave")
        with self.fetcher() as f:
            r = self.api(f, headers={"X-Subscription-Token": "k"})
        self.assertTrue(r.ok, (r.outcome, r.error))
        self.assertEqual(r.status, 200)
        (method, target), = self.http.forwards
        self.assertTrue(target.startswith("http://api.search.brave.com/res/v1/web/search?q="), target)
        self.assertEqual(self.target.requests[0][2], "api.search.brave.com")

    def test_a_routed_search_api_goes_through_socks5h_with_the_name(self):
        self.route("brave", scheme="socks5h")
        with self.fetcher() as f:
            r = self.api(f)
        self.assertTrue(r.ok, (r.outcome, r.error))
        self.assertEqual(self.socks.connects, [("api.search.brave.com", 80)])

    def test_every_search_engine_host_of_the_crawler_has_a_route(self):
        for url, service in (("https://api.search.brave.com/res/v1/web/search", "brave"), ("https://search.brave.com/search", "brave"),
                             ("https://www.googleapis.com/customsearch/v1", "google"), ("https://www.bing.com/search", "search_other"),
                             ("https://html.duckduckgo.com/html/", "search_other"), ("https://www.instagram.com/someone/", "instagram"),
                             ("https://nominatim.openstreetmap.org/search", "osm"), ("https://overpass-api.de/api/interpreter", "osm")):
            self.assertEqual(catalog.service_for_url(url), service, url)
        for url in ("https://www.mojeek.com/search", "https://api.neshan.org/v1/search", "https://badanfit.ir/"):
            self.assertIsNone(catalog.service_for_url(url), url)

    def test_a_wrong_proxy_is_said_in_persian_in_the_result_label(self):
        self.route("brave", port=fakes.closed_port())
        from apps.growth_engine.integrations import safe_http as sh

        with self.fetcher() as f:
            r = self.api(f)
        self.assertEqual(r.outcome, sh.CONNECT_ERROR)
        self.assertIn("پراکسی", r.error)
        self.assertIn("پراکسی", r.label)                                     # what «Brave جواب نداد (…)» shows the operator
        self.assertEqual(self.http.events, [])

    def test_other_hosts_keep_the_ssrf_guard_and_never_see_the_proxy(self):
        from apps.growth_engine.integrations import safe_http as sh

        self.route("brave")
        with self.fetcher(resolver=lambda h, p: ["127.0.0.1"]) as f:
            r = f.get_api("http://shop.example/x", retries=0, delay=0)
            self.assertEqual(r.outcome, sh.SSRF_BLOCKED)                         # a lead's site that resolves to a private address
            r2 = f.get_api("http://api.search.metis.example/x", retries=0, delay=0)
            self.assertEqual(r2.outcome, sh.SSRF_BLOCKED)
        self.assertEqual(self.http.events, [])

    def test_a_catalogue_host_without_a_route_still_goes_the_old_way(self):
        from apps.growth_engine.integrations import safe_http as sh

        with self.fetcher(resolver=lambda h, p: ["10.0.0.5"]) as f:                  # direct: resolved here, the guard refuses a private address
            r = self.api(f)
        self.assertEqual(r.outcome, sh.SSRF_BLOCKED)

    def test_an_injected_transport_always_wins(self):
        import httpx

        self.route("brave")
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, json={"ok": True})

        with self.fetcher(resolver=lambda h, p: ["93.184.216.34"], transport=httpx.MockTransport(handler)) as f:
            r = self.api(f)
        self.assertTrue(r.ok)
        self.assertEqual(self.http.events, [])
        self.assertTrue(seen)

    def test_the_crawler_fetcher_shares_its_timeout_with_the_proxied_client(self):
        from apps.growth_engine.crawler.engine import fetch

        f = fetch.CrawlFetcher(read_timeout=7, resolver=lambda h, p: ["93.184.216.34"])
        self.assertEqual(f._timeout().read, 7)
        self.route("brave")
        target = f._prepare("http://api.search.brave.com/x")
        self.assertTrue(target.proxied)
        self.assertEqual(f._egress_client(target).timeout.read, 7)
        f.close()


# ============================================================================================ the static audit

#: the hosts whose calls must go through ``services.egress`` (the catalogue's own hosts, longest names only - «google.com» would match prose)
AUDITED = sorted({h for s in catalog.CATALOG.values() for h in s.hosts if len(h) > 7 and h not in ("fbcdn.net", "kumi.systems", "private.coffee")}
                 | {p.split("/")[0] for s in catalog.CATALOG.values() for _l, u in s.probes for p in [u.split("://", 1)[1]]})
CALL = re.compile(r"\brequests\.(get|post|put|patch|delete|request|head)\(|\bhttpx\.(get|post|put|patch|delete|request|Client)\(|urllib\.request\.urlopen\(")


class AuditTests(EgressCase):
    def test_no_direct_call_to_a_catalogue_host_is_left(self):
        root = Path(settings.BASE_DIR)
        offenders = []
        for folder in ("apps", "services"):
            for path in (root / folder).rglob("*.py"):
                rel = path.relative_to(root).as_posix()
                if "/migrations/" in rel or "/tests" in rel or path.name.startswith("tests") or rel.startswith(("apps/egress/", "services/egress/")):
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for m in CALL.finditer(text):
                    window = text[m.start(): m.start() + 450]
                    for host in AUDITED:
                        if host in window:
                            offenders.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1} calls {host} directly")
        self.assertEqual(offenders, [], "send these calls through services.egress (get / post / get_for_url ...):\n" + "\n".join(offenders))

    def test_the_helper_is_what_the_call_sites_import(self):
        root = Path(settings.BASE_DIR)
        for rel in ("apps/inbox/adapters/tgcompat.py", "apps/inbox/adapters/whatsapp.py", "apps/inbox/dispatch.py", "apps/customers/receipts.py",
                    "services/publishing/channels.py", "services/research/web.py", "services/research/trends.py",
                    "apps/growth_engine/integrations/safe_http.py", "services/ai/openai_compat.py", "services/audio/tts.py",
                    "services/media/api_media.py"):
            self.assertIn("egress", (root / rel).read_text(encoding="utf-8"), rel)
