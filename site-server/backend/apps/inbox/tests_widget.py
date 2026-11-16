"""The site-chat widget: public endpoints, sessions, origins, limits, the script."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client

from apps.customers.models import Conversation, Message

from . import replies, team
from .models import AgentProfile, ChannelConnection, WidgetSession
from .tests_base import InboxTestCase


@patch("apps.customers.views_webhook._respond_later")
class WidgetTests(InboxTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.row = self.connect("WEBCHAT", token="", config={})
        self.base = f"/api/v1/widget/{self.row.secret}"
        self.http = Client()

    def post(self, path, body, **extra):
        return self.http.post(f"{self.base}/{path}/", data=json.dumps(body), content_type="application/json", **extra)

    def start(self, **body):
        return self.post("session", body).json()["token"]

    def test_the_script_is_served_with_cors_and_names_no_secret(self, _):
        response = self.http.get(f"{self.base}.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response["Content-Type"])
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        text = response.content.decode()
        self.assertIn("rtl", text)
        self.assertIn("/widget/", text)
        self.assertNotIn(self.row.secret, text)  # the script finds its key from its own address
        gone = self.http.get(f"/api/v1/widget/{'x' * 24}.js")
        self.assertIn("disabled", gone.content.decode())

    def test_config_reflects_the_stores_look_and_hours(self, _):
        cfg = team.settings_for(self.store)
        cfg.widget = {"title": "گفتگو با چغر", "color": "#16a34a", "position": "right"}
        cfg.save()
        data = self.http.get(f"{self.base}/config/").json()
        self.assertTrue(data["enabled"])
        self.assertEqual((data["title"], data["color"], data["position"]), ("گفتگو با چغر", "#16a34a", "right"))
        self.assertTrue(data["open_now"])
        self.assertFalse(data["agent_online"])
        team.set_status(self.store, self.sara, AgentProfile.Status.ONLINE)
        self.assertTrue(self.http.get(f"{self.base}/config/").json()["agent_online"])

    def test_a_disabled_or_unknown_widget_says_so_and_nothing_else(self, _):
        self.row.enabled = False
        self.row.save()
        self.assertEqual(self.http.get(f"{self.base}/config/").json(), {"enabled": False})
        self.assertEqual(self.post("session", {}).status_code, 403)
        self.assertEqual(self.http.get(f"/api/v1/widget/{'z' * 24}/config/").json(), {"enabled": False})

    def test_a_visitor_chats_and_the_team_sees_it_in_the_unified_inbox(self, respond):
        token = self.start(name="مریم")
        sent = self.post("send", {"token": token, "text": "سلام، عضویت چقدر است؟", "phone": "۰۹۱۲۳۴۵۶۷۸۹"})
        self.assertEqual(sent.status_code, 200)
        conversation = Conversation.objects.get(store=self.store, channel="WEBCHAT")
        self.assertEqual(conversation.messages.get().text, "سلام، عضویت چقدر است؟")
        self.assertEqual(conversation.customer.inbox_link.contact.phone, "09123456789")
        respond.assert_called_once()
        data = self.api(self.sara).get(self.url("v2/?channel=WEBCHAT")).json()
        self.assertEqual(len(data["conversations"]), 1)

    def test_replies_reach_the_visitor_by_polling_and_never_notes(self, _):
        token = self.start()
        self.post("send", {"token": token, "text": "سلام"})
        conversation = Conversation.objects.get(channel="WEBCHAT")
        replies.reply(conversation, self.sara, "درود، بفرمایید")
        replies.add_note(conversation, self.sara, "این یک یادداشت داخلی است")
        got = self.http.get(f"{self.base}/messages/", {"token": token, "after": 0}).json()["messages"]
        self.assertEqual([m["text"] for m in got], ["سلام", "درود، بفرمایید"])
        later = self.http.get(f"{self.base}/messages/", {"token": token, "after": got[-1]["id"]}).json()["messages"]
        self.assertEqual(later, [])

    def test_a_token_opens_only_its_own_conversation(self, _):
        mine, yours = self.start(), self.start()
        self.post("send", {"token": mine, "text": "راز من"})
        got = self.http.get(f"{self.base}/messages/", {"token": yours, "after": 0}).json()["messages"]
        self.assertEqual(got, [])
        self.assertEqual(self.http.get(f"{self.base}/messages/", {"token": "nope", "after": 0}).status_code, 404)
        # another store's widget key does not accept this store's token
        other = ChannelConnection.objects.create(store=self.other_store, kind="WEBCHAT", enabled=True)
        crossed = self.http.get(f"/api/v1/widget/{other.secret}/messages/", {"token": mine, "after": 0})
        self.assertEqual(crossed.status_code, 404)

    def test_allowed_origins_pin_the_widget_to_the_stores_own_site(self, _):
        self.row.config = {"allowed_origins": ["https://chagher.example"]}
        self.row.save()
        evil = self.http.get(f"{self.base}/config/", HTTP_ORIGIN="https://evil.example").json()
        self.assertEqual(evil, {"enabled": False})
        good = self.http.get(f"{self.base}/config/", HTTP_ORIGIN="https://chagher.example").json()
        self.assertTrue(good["enabled"])
        self.assertEqual(self.post("session", {}, HTTP_ORIGIN="https://evil.example").status_code, 403)

    def test_limits_empty_huge_and_flooding(self, _):
        token = self.start()
        self.assertEqual(self.post("send", {"token": token, "text": "  "}).status_code, 400)
        self.assertEqual(self.post("send", {"token": token, "text": "x" * 2001}).status_code, 400)
        codes = [self.post("send", {"token": token, "text": f"پیام {i}"}).status_code for i in range(15)]
        self.assertIn(429, codes)
        self.assertEqual(codes.count(200), 12)

    def test_preflight_is_allowed(self, _):
        response = self.http.options(f"{self.base}/send/")
        self.assertEqual(response.status_code, 204)
        self.assertIn("POST", response["Access-Control-Allow-Methods"])

    def test_the_widget_is_in_persian_and_works_on_phones(self, _):
        from pathlib import Path

        source = (Path(__file__).parent / "widget" / "widget.js").read_text(encoding="utf-8")
        for needle in ("rtl", "lang", "@media(max-width:520px)", "پیامتان را بنویسید", "ارسال", "async"):
            self.assertIn(needle, source)
        self.assertNotIn("document.cookie", source)  # no cookies: CORS * is safe

    def test_a_widget_session_row_is_created_per_visitor(self, _):
        self.start()
        self.start()
        self.assertEqual(WidgetSession.objects.count(), 2)
        self.assertEqual(Message.objects.count(), 0)


class SiteBuilderTests(InboxTestCase):
    def test_the_snippet_survives_in_a_published_site_builder_page(self):
        """«کدِ سفارشی» puts its code on the published page verbatim - so the one
        script tag is all a site-builder site needs; nothing in the builder changed."""
        from apps.projects.builder import clean, render

        row = self.connect("WEBCHAT", token="", config={})
        snippet = f'<script src="https://nm.example/api/v1/widget/{row.secret}.js" async></script>'
        doc = {"blocks": [clean.new_block("custom_html", code=snippet)]}
        published = render.render_doc(doc, render.Ctx(canvas=False)).html
        self.assertIn(snippet, published)
        # ...while the editing canvas keeps scripts inert, so editing never opens a chat
        canvas = render.render_doc(doc, render.Ctx(canvas=True)).html
        self.assertNotIn("<script", canvas)
