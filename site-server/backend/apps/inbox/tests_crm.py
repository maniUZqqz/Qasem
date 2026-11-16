"""Segments and broadcasts: rules, preview, owner approval, opt-out, rate limits."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.customers.models import Customer, Message, Order
from services.publishing import channels

from . import broadcast as bc
from . import contacts, segments, team
from .fakes import FakePlatform
from .models import Broadcast, BroadcastRecipient, Contact, ContactLink, Segment
from .tests_base import InboxTestCase


class SegmentTests(InboxTestCase):
    def person(self, name, *, phone="", tags=None, orders=0, last_purchase_days=None, active_days=1,
               first_seen_days=100, channel="TELEGRAM", sender=None):
        now = timezone.now()
        contact = Contact.objects.create(
            store=self.store, name=name, phone=phone, tags=tags or [], orders_count=orders,
            last_purchase_at=now - timedelta(days=last_purchase_days) if last_purchase_days is not None else None,
            last_activity_at=now - timedelta(days=active_days), first_seen_at=now - timedelta(days=first_seen_days),
        )
        customer = Customer.objects.create(
            store=self.store, name=name, channel=channel.lower(), external_id=sender or f"{name}-{channel}",
        )
        ContactLink.objects.create(contact=contact, customer=customer, matched_by="new")
        return contact

    def names(self, rules):
        return sorted(c.name for c in segments.contacts_in(self.store, rules))

    def test_loyal_customers_is_the_builtin_the_owner_asked_for(self):
        self.person("دائمی", orders=4, last_purchase_days=3)
        self.person("یک‌بار", orders=1, last_purchase_days=90)
        self.person("بی‌خرید")
        segments.ensure_builtin(self.store)
        loyal = Segment.objects.get(store=self.store, builtin_key="loyal")
        self.assertEqual(loyal.name, "مشتریِ دائمی")
        self.assertEqual(self.names(loyal.rules), ["دائمی"])

    def test_every_builtin_is_valid_and_ensure_is_idempotent(self):
        segments.ensure_builtin(self.store)
        segments.ensure_builtin(self.store)
        self.assertEqual(Segment.objects.filter(store=self.store).exclude(builtin_key="").count(), len(segments.BUILTIN))
        for seg in Segment.objects.filter(store=self.store):
            segments.validate(seg.rules)

    def test_builtin_time_segments(self):
        self.person("تازه", first_seen_days=2)
        self.person("قدیمی", first_seen_days=200, active_days=100)
        self.person("ریزشی", orders=2, last_purchase_days=120, active_days=100)
        self.person("اخیر", orders=1, last_purchase_days=10)
        segments.ensure_builtin(self.store)
        by_key = {s.builtin_key: s for s in Segment.objects.filter(store=self.store)}
        self.assertIn("تازه", self.names(by_key["new"].rules))
        self.assertEqual(self.names(by_key["churn_risk"].rules), ["ریزشی"])
        self.assertEqual(self.names(by_key["recent_buyer"].rules), ["اخیر"])
        self.assertIn("قدیمی", self.names(by_key["dormant"].rules))
        self.assertNotIn("تازه", self.names(by_key["dormant"].rules))

    def test_all_and_any(self):
        self.person("الف", tags=["vip"], orders=1)
        self.person("ب", tags=["vip"], orders=0)
        self.person("ج", tags=[], orders=5)
        rules = lambda match: {"match": match, "rules": [  # noqa: E731
            {"field": "tag", "op": "has", "value": "VIP"},
            {"field": "orders_count", "op": "gte", "value": 1}]}
        self.assertEqual(self.names(rules("all")), ["الف"])
        self.assertEqual(self.names(rules("any")), ["الف", "ب", "ج"])

    def test_channel_and_phone_and_name_rules(self):
        self.person("تلگرامی", channel="TELEGRAM", phone="09121234567")
        self.person("بله‌ای", channel="BALE")
        self.assertEqual(self.names({"rules": [{"field": "channel", "op": "has", "value": "bale"}]}), ["بله‌ای"])
        self.assertEqual(self.names({"rules": [{"field": "has_phone", "op": "is_true"}]}), ["تلگرامی"])
        self.assertEqual(self.names({"rules": [{"field": "has_phone", "op": "is_false"}]}), ["بله‌ای"])
        self.assertEqual(self.names({"rules": [{"field": "name_contains", "op": "contains", "value": "تلگ"}]}), ["تلگرامی"])

    def test_never_bought_is_not_recently_bought_but_is_long_since_bought(self):
        self.person("هرگز")
        self.assertEqual(self.names({"rules": [{"field": "last_purchase_days", "op": "lte", "value": 30}]}), [])
        self.assertEqual(self.names({"rules": [{"field": "last_purchase_days", "op": "gte", "value": 90}]}), ["هرگز"])

    def test_bad_rules_are_refused_in_words(self):
        for bad in ({"match": "some"}, {"rules": [{"field": "nope", "op": "eq"}]},
                    {"rules": [{"field": "orders_count", "op": "weird"}]}, "text"):
            with self.assertRaises(segments.RuleError):
                segments.validate(bad)
        self.person("x")  # a rule only fails when there is someone to compare
        with self.assertRaises(segments.RuleError):
            segments.contacts_in(self.store, {"rules": [{"field": "orders_count", "op": "gte", "value": "abc"}]})

    def test_other_stores_and_test_contacts_are_never_selected(self):
        self.person("من")
        Contact.objects.create(store=self.other_store, name="غریبه")
        Contact.objects.create(store=self.store, name="نمونه", is_test=True)
        self.assertEqual(self.names({"rules": []}), ["من"])


class BroadcastBase(InboxTestCase):
    def audience(self, count=3, channel="BALE", **kw):
        out = []
        for i in range(count):
            contact = Contact.objects.create(store=self.store, name=f"مخاطب {i}", phone=f"0912000000{i}", **kw)
            customer = Customer.objects.create(
                store=self.store, name=contact.name, channel=channel.lower(), external_id=f"{channel[0]}{i}",
            )
            ContactLink.objects.create(contact=contact, customer=customer, matched_by="new")
            out.append(contact)
        return out

    def draft(self, **kw) -> Broadcast:
        defaults = dict(store=self.store, name="تخفیف آخر هفته", text="سلام {name}! تخفیف داریم.",
                        created_by=self.sara, channels=["BALE"])
        defaults.update(kw)
        return Broadcast.objects.create(**defaults)


class PreviewTests(BroadcastBase):
    def test_preview_counts_skips_and_renders_without_queueing_anything(self):
        self.connect("BALE")
        people = self.audience(3)
        contacts.set_opt_out(people[0], "ALL", True)
        Contact.objects.create(store=self.store, name="بی‌آدرس")  # no channel at all
        preview = bc.preview(self.draft())
        self.assertEqual(preview["recipients"], 2)
        self.assertEqual(preview["skipped"]["opted_out"], 1)
        self.assertEqual(preview["skipped"]["no_address"], 1)
        self.assertEqual(preview["per_channel"], {"BALE": 2})
        self.assertTrue(preview["samples"][0]["text"].startswith("سلام مخاطب"))
        self.assertIn("لغو", preview["samples"][0]["text"])  # the way out is always there
        self.assertEqual(BroadcastRecipient.objects.count(), 0)

    def test_a_channel_that_is_off_is_named_and_dropped(self):
        self.audience(2)
        preview = bc.preview(self.draft())
        self.assertEqual(preview["recipients"], 0)
        self.assertEqual(preview["channels_off"], ["BALE"])

    def test_one_message_per_person_by_default_two_when_asked(self):
        self.connect("BALE")
        self.connect("RUBIKA", token="R" * 30)
        for contact in self.audience(2, channel="BALE"):
            customer = Customer.objects.create(store=self.store, name="r", channel="rubika", external_id=f"r{contact.pk}")
            ContactLink.objects.create(contact=contact, customer=customer, matched_by="new")
        once = bc.preview(self.draft(channels=["BALE", "RUBIKA"], dedupe=True))
        twice = bc.preview(self.draft(channels=["BALE", "RUBIKA"], dedupe=False))
        self.assertEqual(once["recipients"], 2)
        self.assertEqual(twice["recipients"], 4)

    def test_an_opt_out_of_one_channel_does_not_silence_the_others(self):
        self.connect("BALE")
        self.connect("RUBIKA", token="R" * 30)
        person = self.audience(1)[0]
        customer = Customer.objects.create(store=self.store, name="r", channel="rubika", external_id="r-x")
        ContactLink.objects.create(contact=person, customer=customer, matched_by="new")
        contacts.set_opt_out(person, "BALE", True)
        preview = bc.preview(self.draft(channels=["BALE", "RUBIKA"]))
        self.assertEqual(preview["per_channel"], {"RUBIKA": 1})

    def test_sms_needs_a_real_mobile_number(self):
        self.connect("SMS", token="", config={})
        Contact.objects.create(store=self.store, name="با شماره", phone="09121234567")
        Contact.objects.create(store=self.store, name="بی‌شماره", phone="")
        with patch("apps.inbox.dispatch.is_ready", return_value=True):
            preview = bc.preview(self.draft(channels=["SMS"]))
        self.assertEqual(preview["per_channel"], {"SMS": 1})

    def test_tests_are_never_in_the_audience(self):
        self.connect("BALE")
        self.audience(2, is_test=True)
        self.assertEqual(bc.preview(self.draft())["recipients"], 0)


class ApprovalTests(BroadcastBase):
    def setUp(self):
        super().setUp()
        self.connect("BALE")
        self.audience(3)

    def test_the_whole_path_draft_pending_approved(self):
        broadcast = self.draft()
        bc.submit(broadcast, self.sara)
        self.assertEqual(broadcast.status, Broadcast.Status.PENDING)
        self.assertEqual(BroadcastRecipient.objects.filter(broadcast=broadcast).count(), 3)
        bc.approve(broadcast, self.admin)
        self.assertEqual(broadcast.status, Broadcast.Status.APPROVED)
        self.assertEqual(broadcast.approved_by, self.admin)

    def test_support_staff_cannot_approve_and_nothing_is_sent_without_approval(self):
        broadcast = self.draft()
        bc.submit(broadcast, self.sara)
        with self.assertRaises(bc.BroadcastError):
            bc.approve(broadcast, self.reza)
        with FakePlatform({"sendMessage": {"ok": True, "result": {"message_id": 1}}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            stats = bc.send_tick()
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(fake.requests, [])

    def test_an_admin_cannot_approve_their_own_but_the_owner_can(self):
        broadcast = self.draft(created_by=self.admin)
        bc.submit(broadcast, self.admin)
        with self.assertRaises(bc.BroadcastError) as caught:
            bc.approve(broadcast, self.admin)
        self.assertIn("شخص دیگری", str(caught.exception))
        own = self.draft(created_by=self.owner, name="مالک")
        bc.submit(own, self.owner)
        bc.approve(own, self.owner)
        self.assertEqual(own.status, Broadcast.Status.APPROVED)

    def test_a_test_broadcast_can_never_be_approved_or_sent(self):
        broadcast = self.draft(is_test=True)
        self.assertFalse(bc.can_approve(self.owner, broadcast)[0])
        with FakePlatform({"sendMessage": {"ok": True, "result": {"message_id": 1}}}) as fake, \
                override_settings(INBOX_API_BASES={"BALE": fake.url}):
            bc.send_tick()
        self.assertEqual(fake.requests, [])

    def test_empty_text_or_no_recipients_cannot_be_submitted(self):
        with self.assertRaises(bc.BroadcastError):
            bc.submit(self.draft(text="  "), self.sara)
        with self.assertRaises(bc.BroadcastError):
            bc.submit(self.draft(channels=["RUBIKA"]), self.sara)  # that channel is not connected

    def test_reject_records_why_and_allows_editing_again(self):
        broadcast = self.draft()
        bc.submit(broadcast, self.sara)
        bc.reject(broadcast, self.admin, "متن را کوتاه‌تر کنید")
        self.assertEqual(broadcast.status, Broadcast.Status.REJECTED)
        self.assertEqual(broadcast.review_note, "متن را کوتاه‌تر کنید")
        bc.submit(broadcast, self.sara)
        self.assertEqual(broadcast.status, Broadcast.Status.PENDING)

    def test_approval_re_resolves_the_audience(self):
        broadcast = self.draft()
        bc.submit(broadcast, self.sara)
        leaver = Contact.objects.filter(store=self.store).first()
        contacts.set_opt_out(leaver, "ALL", True)
        bc.approve(broadcast, self.admin)
        self.assertEqual(BroadcastRecipient.objects.filter(broadcast=broadcast).count(), 2)


class SendingTests(BroadcastBase):
    def setUp(self):
        super().setUp()
        self.connect("BALE")
        self.audience(5)

    def approved(self, **kw) -> Broadcast:
        broadcast = self.draft(**kw)
        bc.submit(broadcast, self.sara)
        bc.approve(broadcast, self.admin)
        return broadcast

    def tick(self, fake_answers=None):
        answers = fake_answers or {"sendMessage": {"ok": True, "result": {"message_id": 1}}}
        with FakePlatform(answers) as fake, override_settings(INBOX_API_BASES={"BALE": fake.url}):
            stats = bc.send_tick()
        return stats, fake

    def test_sends_to_everyone_and_finishes(self):
        broadcast = self.approved()
        stats, fake = self.tick()
        self.assertEqual(stats["sent"], 5)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, Broadcast.Status.SENT)
        self.assertEqual(broadcast.stats["sent"], 5)
        first = fake.requests[0]["body"]
        self.assertIn("مخاطب", first["text"])
        self.assertIn("لغو", first["text"])
        # recorded in each person's thread, attributed to the broadcast
        self.assertEqual(Message.objects.filter(inbox_meta__kind="BROADCAST").count(), 5)

    def test_the_per_channel_rate_limit_spreads_it_over_minutes(self):
        cfg = team.settings_for(self.store)
        cfg.rate_limits = {"BALE": 2}
        cfg.save()
        broadcast = self.approved()
        first, _ = self.tick()
        self.assertEqual(first["sent"], 2)
        second, fake = self.tick()
        self.assertEqual(second["sent"], 0)  # the same minute: the budget is spent
        self.assertEqual(fake.requests, [])
        BroadcastRecipient.objects.filter(status="SENT").update(sent_at=timezone.now() - timedelta(minutes=2))
        third, _ = self.tick()
        self.assertEqual(third["sent"], 2)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, Broadcast.Status.SENDING)

    def test_two_broadcasts_share_one_channel_budget(self):
        cfg = team.settings_for(self.store)
        cfg.rate_limits = {"BALE": 3}
        cfg.save()
        one = self.approved(name="یک")
        two = self.approved(name="دو")
        stats, _ = self.tick()
        self.assertEqual(stats["sent"], 3)

    def test_someone_who_opts_out_after_approval_is_skipped(self):
        broadcast = self.approved()
        leaver = Contact.objects.filter(store=self.store).order_by("id").first()
        contacts.set_opt_out(leaver, "ALL", True)
        stats, _ = self.tick()
        self.assertEqual(stats["sent"], 4)
        row = BroadcastRecipient.objects.get(broadcast=broadcast, contact=leaver)
        self.assertEqual((row.status, row.skip_reason), ("SKIPPED", "opted_out"))

    def test_a_failing_channel_pauses_itself_after_three_failures(self):
        broadcast = self.approved()
        stats, fake = self.tick({"sendMessage": (500, {})})
        self.assertEqual(stats["failed"], 3)
        self.assertEqual(len(fake.requests), 3)  # not five: it stopped hammering
        self.assertEqual(BroadcastRecipient.objects.filter(status="QUEUED").count(), 2)
        broadcast.refresh_from_db()
        self.assertEqual(broadcast.status, Broadcast.Status.SENDING)

    def test_scheduled_for_later_waits(self):
        self.approved(scheduled_at=timezone.now() + timedelta(hours=2))
        stats, fake = self.tick()
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(fake.requests, [])

    def test_cancel_stops_the_rest(self):
        broadcast = self.approved()
        bc.cancel(broadcast, self.admin)
        stats, fake = self.tick()
        self.assertEqual(fake.requests, [])
        self.assertFalse(BroadcastRecipient.objects.filter(status="QUEUED").exists())

    def test_sms_goes_through_an_approved_marketing_campaign_only(self):
        from apps.mobile.models import SmsCampaignApproval, SmsMessage

        self.connect("SMS", token="")
        people = Contact.objects.filter(store=self.store)
        broadcast = self.draft(channels=["SMS"], name="پیامکی")
        with patch("apps.inbox.dispatch.is_ready", return_value=True):
            bc.submit(broadcast, self.sara)
            self.assertFalse(SmsCampaignApproval.objects.exists())  # nobody approved yet
            bc.approve(broadcast, self.admin)
            self.assertTrue(SmsCampaignApproval.objects.filter(ref=f"inbox-broadcast-{broadcast.pk}", approved_by=self.admin).exists())
            stats = bc.send_tick()
        self.assertEqual(stats["sent"], 5)
        self.assertEqual(SmsMessage.objects.filter(kind="marketing").count(), 5)
        # a person who texted «لغو» is on the gateway's own never-again list: still blocked there
        self.assertEqual(people.count(), 5)
