"""The Chagher draft setup, the node self-test, and the guards that keep both honest."""
from __future__ import annotations

import re
from pathlib import Path

from apps.customers.models import Conversation, Message

from . import broadcast as bc
from . import demo, guides, segments
from .models import Broadcast, ChannelConnection, Contact, FollowUp, InboxSettings, WebhookDelivery, WebhookEndpoint
from .tests_base import InboxTestCase


class DemoTests(InboxTestCase):
    def test_seed_makes_a_draft_that_sends_nothing_and_switches_nothing_on(self):
        WebhookEndpoint.objects.create(store=self.store, url="https://hooks.example.com/x", events=[])
        result = demo.seed(self.store, owner=self.owner)
        self.assertEqual(result["conversations"], len(demo.CONVERSATIONS))
        self.assertFalse(ChannelConnection.objects.filter(store=self.store, enabled=True).exists())
        self.assertFalse(ChannelConnection.objects.filter(store=self.store).exclude(token="").exists())
        self.assertEqual(self.sent, [])
        self.assertEqual(WebhookDelivery.objects.count(), 0)  # a test thread never tells the outside world
        for meta_test in Conversation.objects.filter(store=self.store).values_list("inbox_meta__is_test", flat=True):
            self.assertTrue(meta_test)
        self.assertEqual(Contact.objects.filter(store=self.store, is_test=False).count(), 0)

    def test_seeding_twice_changes_nothing(self):
        demo.seed(self.store, owner=self.owner)
        counts = (Conversation.objects.count(), Message.objects.count(), Contact.objects.count(), Broadcast.objects.count(), FollowUp.objects.count())
        again = demo.seed(self.store, owner=self.owner)
        self.assertEqual(again["conversations"], 0)
        self.assertEqual(counts, (Conversation.objects.count(), Message.objects.count(), Contact.objects.count(),
                                  Broadcast.objects.count(), FollowUp.objects.count()))

    def test_the_demo_is_invisible_to_real_numbers_and_audiences(self):
        demo.seed(self.store, owner=self.owner)
        data = self.api().get(self.url("v2/")).json()
        self.assertEqual(data["conversations"], [])  # hidden by default
        self.assertEqual(data["counts"]["tests"], len(demo.CONVERSATIONS))
        shown = self.api().get(self.url("v2/?test=only")).json()["conversations"]
        self.assertEqual(len(shown), len(demo.CONVERSATIONS))
        self.assertTrue(all(c["is_test"] for c in shown))
        stats = self.api().get(self.url("stats/")).json()
        self.assertEqual((stats["open"], stats["waiting_for_person"]), (0, 0))
        self.assertEqual(segments.count_in(self.store, {"rules": []}), 0)
        self.assertEqual(bc.preview(Broadcast.objects.get(store=self.store))["recipients"], 0)

    def test_the_demo_broadcast_can_never_be_approved_or_sent(self):
        demo.seed(self.store, owner=self.owner)
        row = Broadcast.objects.get(store=self.store)
        self.assertTrue(row.is_test)
        self.assertFalse(bc.can_approve(self.owner, row)[0])

    def test_every_channel_is_covered_by_a_demo_conversation(self):
        shown = {c[0] for c in demo.CONVERSATIONS}
        self.assertEqual(shown, {"BALE", "TELEGRAM", "RUBIKA", "SMS", "WEBCHAT", "EITAA"})

    def test_demo_text_makes_no_claims_the_brand_facts_do_not_support(self):
        """No prices, no statistics: brand-facts-fa.md lists those as unconfirmed."""
        texts = [t for _, _, t in demo.CANNED]
        for _, _, _, _, lines, _, _ in demo.CONVERSATIONS:
            texts += [t for _, t in lines]
        digits = re.compile(r"[0-9۰-۹]")
        for text in texts:
            self.assertIsNone(digits.search(text), text)
            self.assertNotIn("۲۴/۷", text)
            self.assertNotIn("تضمین", text)

    def test_the_command_runs_and_reports(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("seed_inbox_demo", store=self.store.pk, stdout=out)
        self.assertIn("هیچ کانالی روشن نشد", out.getvalue())
        self.assertEqual(InboxSettings.objects.get(store=self.store).widget["color"], "#126F85")


class GuideTests(InboxTestCase):
    def test_every_guide_is_complete_and_persian(self):
        for kind in guides.CHANNEL_ORDER:
            guide = guides.GUIDES[kind]
            self.assertTrue(re.search(r"[؀-ۿ]", guide["summary"]), kind)
            self.assertGreaterEqual(len(guide["steps"]), 3, kind)
            for field in guide["fields"]:
                self.assertTrue(field["key"] and field["label"], kind)
        self.assertEqual(set(guides.GUIDES), set(guides.CHANNEL_ORDER))

    def test_no_brand_or_forbidden_names_leak_into_the_guides(self):
        text = " ".join(str(v) for g in guides.GUIDES.values() for v in g.values())
        for banned in ("nim.chat", "نیم‌چت", "Photoshop", "Premiere", "Adobe"):
            self.assertNotIn(banned, text)


class SelfTestRegistration(InboxTestCase):
    def test_the_node_self_test_is_registered_and_judges_answers(self):
        from apps.compute.selftests import REGISTRY, Verdict, load_all
        from apps.compute.selftests import inbox_bot

        load_all(force=True)
        self.assertIn("inbox_bot", REGISTRY)

        class Ctx:
            def __init__(self, text):
                self.text = text

            def read_json(self, job, name):
                return {"response": self.text}

            def meta(self, job):
                return {"device": "cuda"}

        class Job:
            payload = {"model": "qwen3:8b"}

        good = "چغر دستیار هوش مصنوعیِ مربی‌هاست و برنامه را پیش‌نویس می‌کند؛ جایگزین مربی نیست و تصمیم نهایی با مربی است."
        self.assertTrue(inbox_bot.check(Ctx(good), Job()).ok)
        self.assertFalse(inbox_bot.check(Ctx("hello there"), Job()).ok)
        self.assertFalse(inbox_bot.check(Ctx(good + " قیمتش ۶۰۰ هزار تومان است."), Job()).ok)  # invented numbers
        self.assertFalse(inbox_bot.check(Ctx("چغر دستیاری فارسی برای ورزشکارها و باشگاه‌هاست که همه‌چیز را انجام می‌دهد."), Job()).ok)  # ignored the question
        self.assertIsInstance(Verdict.passed("x"), Verdict)
        facts = (Path(__file__).resolve().parents[3].parent / "docs" / "chagher" / "brand-facts-fa.md")
        if facts.exists():
            self.assertIn("جایگزینِ مربی نیست", facts.read_text(encoding="utf-8"))
            self.assertIn("جایگزینِ مربی نیست", inbox_bot.FACTS)
