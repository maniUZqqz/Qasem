"""The Celery side: polling claims, health sweep, ticks - all runnable twice and late."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.customers.models import Conversation, Notification

from . import tasks
from .fakes import FakePlatform
from .models import ChannelConnection
from .tests_base import InboxTestCase

UPDATES = {"ok": True, "result": [{"update_id": 3, "message": {
    "message_id": 8, "from": {"id": 5, "first_name": "ع"}, "chat": {"id": 5, "type": "private"}, "text": "سلام"}}]}


@patch("apps.customers.views_webhook._respond_later")
class PollTaskTests(InboxTestCase):
    def test_polls_only_channels_that_need_it(self, _):
        polled = self.connect("BALE")  # AUTO and no webhook registered: poll
        hooked = self.connect("RUBIKA", token="R" * 30, config={"webhook_registered": True})  # push: do not poll
        self.connect("WEBCHAT", token="")  # nothing to poll
        with FakePlatform({"getUpdates": UPDATES}) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url, "RUBIKA": fake.url}):
            result = tasks.poll_channels()
        self.assertEqual(result["accepted"], 1)
        self.assertEqual([r["path"].split("/")[1] for r in fake.requests], [f"bot{polled.token}"])
        polled.refresh_from_db()
        hooked.refresh_from_db()
        self.assertIsNone(polled.poll_claimed_at)  # released
        self.assertIsNone(hooked.last_poll_at)

    def test_a_live_claim_blocks_a_second_worker_but_a_stale_one_does_not(self, _):
        row = self.connect("BALE")
        ChannelConnection.objects.filter(pk=row.pk).update(poll_claimed_at=timezone.now())
        with FakePlatform({"getUpdates": UPDATES}) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}):
            self.assertEqual(tasks.poll_channels()["polled"], 0)
            self.assertEqual(fake.requests, [])
            ChannelConnection.objects.filter(pk=row.pk).update(poll_claimed_at=timezone.now() - timedelta(minutes=5))
            self.assertEqual(tasks.poll_channels()["polled"], 1)

    def test_one_broken_channel_does_not_stop_the_others(self, _):
        self.connect("BALE")
        self.connect("RUBIKA", token="R" * 30)
        with FakePlatform({"getUpdates": (500, {})}) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url, "RUBIKA": fake.url}):
            result = tasks.poll_channels()
        self.assertEqual(result["polled"], 2)  # both were tried; neither raised


class HealthSweepTests(InboxTestCase):
    def test_a_channel_that_goes_bad_tells_the_owner_once(self):
        row = self.connect("BALE")
        row.health_ok = True
        row.save()
        with FakePlatform({"getMe": (401, {"ok": False, "error_code": 401})}) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}):
            first = tasks.health_sweep()
            self.assertEqual(first, {"checked": 1, "bad": 1})
            ChannelConnection.objects.filter(pk=row.pk).update(health_checked_at=timezone.now() - timedelta(hours=1))
            tasks.health_sweep()
        alerts = Notification.objects.filter(store=self.store, context__channel="BALE")
        self.assertEqual(alerts.count(), 1)
        self.assertIn("/inbox/channels", alerts.first().link)

    def test_recently_checked_channels_are_left_alone(self):
        row = self.connect("BALE")
        ChannelConnection.objects.filter(pk=row.pk).update(health_checked_at=timezone.now())
        with FakePlatform({"getMe": {"ok": True, "result": {}}}) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}):
            self.assertEqual(tasks.health_sweep()["checked"], 0)
            self.assertEqual(fake.requests, [])


class TickTests(InboxTestCase):
    def test_every_tick_returns_and_is_safe_on_an_empty_database(self):
        self.assertEqual(tasks.sla_tick(), {"warned": 0, "breached": 0})
        self.assertEqual(tasks.followups_tick()["sent"], 0)
        self.assertEqual(tasks.broadcast_tick()["sent"], 0)
        self.assertEqual(tasks.deliver_webhooks()["sent"], 0)

    def test_every_beat_entry_names_a_registered_task(self):
        from django.conf import settings

        names = {v["task"] for k, v in settings.CELERY_BEAT_SCHEDULE.items() if k.startswith("inbox-")}
        self.assertEqual(names, {"inbox.poll_channels", "inbox.sla_tick", "inbox.followups_tick",
                                 "inbox.broadcast_tick", "inbox.deliver_webhooks", "inbox.health_sweep"})
        from config.celery import app

        app.loader.import_default_modules()
        for name in names:
            self.assertIn(name, app.tasks, name)
