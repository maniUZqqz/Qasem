"""The SMS channel: an adapter to NM-Mobile's queue. Nothing is sent by this system; the phone does, and its report settles the item."""
from __future__ import annotations

import itertools
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import settings as compliance_settings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_staff
from apps.growth_engine.outreach.channels import sms as sms_channel
from apps.growth_engine.outreach.models import Campaign, Channel, ItemStatus, OutreachItem, OutreachJob, SendAttempt
from apps.growth_engine.outreach.services import approval, campaigns, channel_config, preparing, sending
from apps.mobile import api as mobile
from apps.mobile.models import MobileDevice, SmsCampaignApproval, SmsMessage, SmsOptOut

from .helpers import FakeSleep, MidRng, configure, make_lead, make_template

_n = itertools.count(1)
SHORT_BODY = "سلام؛ ویدیو و پوسترِ تبلیغاتیِ فروشگاه را خودکار می‌سازیم. ۲ هفته رایگان."


def pair_phone(user, **kw):
    n = next(_n)
    return MobileDevice.objects.create(user=user, name=f"گوشی {n}", install_id=f"inst-{n}", token_hash=f"{n:064x}", **kw)


class SmsBase(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.device = pair_phone(self.staff, last_seen_at=timezone.now())
        channel_config.update("sms", {"enabled": True}, self.staff)
        self.template = make_template("پیامک", body=SHORT_BODY, subject="", channel="sms")
        self.campaign = campaigns.create_campaign(name="پیامک", template=self.template, mode=Campaign.Mode.AUTO, channel=Channel.SMS, user=self.staff)

    def lead(self, n, **kw):
        return make_lead(f"s{n}.ir", phone=f"0912666{n:04d}", form=False, **kw)

    def ready(self, n=1):
        item = campaigns.add_leads(self.campaign, [self.lead(n).pk]).added[0]
        preparing.prepare_item(item, None, GrowthSettings.load())
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason_text), (ItemStatus.READY, ""), item.plan)
        return item

    def approved(self, n=1):
        item = self.ready(n)
        self.assertEqual(approval.approve_items(self.campaign, item_ids=[item.pk], actor=self.staff)["approved"], 1)
        item.refresh_from_db()
        return item

    def run_job(self):
        campaign, job, created = campaigns.start(self.campaign, self.staff)
        self.assertTrue(created)
        sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng())
        job.refresh_from_db()
        return job

    def message(self, item):
        return SmsMessage.objects.get(idempotency_key=sms_channel.idempotency_key(item))


class AvailabilityTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def test_without_a_paired_phone_the_channel_says_what_it_needs(self):
        ok, reason, info = sms_channel.availability()
        self.assertFalse(ok)
        self.assertIn("نیاز به اپِ NM-Mobile", reason)
        self.assertEqual(info["devices"], 0)
        response = self.client.patch("/api/v1/growth/outreach/channels/sms/", {"enabled": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "not_ready")

    def test_a_paired_phone_makes_it_available_and_a_revoked_one_does_not(self):
        device = pair_phone(self.staff)
        ok, _, info = sms_channel.availability()
        self.assertTrue(ok)
        self.assertEqual((info["devices"], info["online"]), (1, 0))
        device.last_seen_at = timezone.now()
        device.save()
        self.assertEqual(sms_channel.availability()[2]["online"], 1)
        device.revoked_at = timezone.now()
        device.save()
        self.assertFalse(sms_channel.availability()[0])

    def test_the_apps_own_pause_switch_is_respected(self):
        from apps.mobile.models import MobileSettings

        pair_phone(self.staff)
        row = MobileSettings.get()
        row.sms_enabled = False
        row.save()
        ok, reason, _ = sms_channel.availability()
        self.assertFalse(ok)
        self.assertIn("خاموش است", reason)

    def test_the_listing_marks_the_sms_channel_ready_once_a_phone_is_there(self):
        pair_phone(self.staff)
        by = {c["key"]: c for c in self.client.get("/api/v1/growth/outreach/channels/").json()["channels"]}
        self.assertTrue(by["sms"]["ready"])
        self.assertFalse(by["sms"]["needs_app"])


class PrepareTests(SmsBase):
    def test_a_ready_sms_knows_its_size_and_target(self):
        item = self.ready()
        self.assertEqual((item.channel, item.recipient), (Channel.SMS, "09126660001"))
        self.assertLessEqual(item.plan["sms"]["parts"], 2)
        self.assertEqual(item.plan["sms"]["encoding"], "ucs2")

    def test_the_default_message_with_its_closing_line_fits_two_parts(self):
        item = self.ready()
        seg = sms_channel.segments(item.rendered_text)
        self.assertLessEqual(seg["parts"], 2, (seg, item.rendered_text))
        self.assertIn("لغو", item.rendered_text)

    def test_a_text_that_is_too_long_is_not_ready(self):
        long_template = make_template("بلند", body="س" * 200, subject="", channel="sms")
        campaign = campaigns.create_campaign(name="بلند", template=long_template, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        item = campaigns.add_leads(campaign, [self.lead(9).pk]).added[0]
        preparing.prepare_item(item, None, GrowthSettings.load())
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.NEEDS_MANUAL, "channel_not_ready"))
        self.assertIn("بخش", item.skip_reason_text)
        channel_config.update("sms", {"config": {"max_parts": 3}}, self.staff)
        self.assertEqual(channel_config.sms_max_parts(), 3)

    def test_a_number_that_asked_to_stop_is_not_ready(self):
        mobile.add_opt_out("09126660002")
        item = campaigns.add_leads(self.campaign, [self.lead(2).pk]).added[0]
        preparing.prepare_item(item, None, GrowthSettings.load())
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.NEEDS_MANUAL)
        self.assertIn("لغو", item.skip_reason_text)

    def test_a_lead_with_only_a_landline_is_not_added(self):
        landline = make_lead("s77.ir", phone="02188112233", form=False)
        self.assertEqual([s["reason"] for s in campaigns.add_leads(self.campaign, [landline.pk]).skipped], ["no_mobile"])


class HandOffTests(SmsBase):
    def test_an_approved_sms_is_queued_for_the_phone_not_marked_sent(self):
        item = self.approved()
        job = self.run_job()
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.HANDED_OFF)
        message = self.message(item)
        self.assertEqual((message.kind, message.state, message.to_number), ("marketing", "QUEUED", "989126660001"))
        self.assertEqual(message.campaign_ref, f"ge:{self.campaign.pk}")
        self.assertEqual(message.body, item.rendered_text)
        approval_row = SmsCampaignApproval.objects.get(ref=f"ge:{self.campaign.pk}")
        self.assertTrue(approval_row.active)
        self.assertEqual(approval_row.approved_by_id, self.staff.pk)
        self.assertEqual(approval_row.source, "growth_engine")
        self.assertLessEqual(approval_row.valid_until - timezone.now(), timedelta(days=sms_channel.APPROVAL_VALID_DAYS, minutes=1))
        self.assertGreater(approval_row.valid_until, timezone.now() + timedelta(days=2))
        attempt = SendAttempt.objects.get(item=item)
        self.assertEqual((attempt.channel, attempt.method, attempt.outcome), (Channel.SMS, "SMS", "queued_on_phone"))
        self.assertEqual(job.items_sent, 1)
        item.lead.refresh_from_db()
        self.assertEqual(item.lead.status, "new")  # not "contacted" until the phone says it sent
        self.assertEqual(item.lead.activities.filter(kind="queue_outcome").first().data["outcome"], "queued_on_phone")

    def test_the_phones_report_settles_the_item(self):
        item = self.approved()
        self.run_job()
        SmsMessage.objects.filter(pk=self.message(item).pk).update(state="SENT", sent_at=timezone.now())
        self.assertEqual(sms_channel.reconcile(self.campaign.pk), 1)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.SENT)
        self.assertEqual(SendAttempt.objects.get(item=item).outcome, "sent_by_phone")
        item.lead.refresh_from_db()
        self.assertEqual(item.lead.status, "contacted")
        self.assertEqual(sms_channel.reconcile(self.campaign.pk), 0)  # settled once

    def test_delivered_and_failed_and_cancelled_are_mapped(self):
        items = [self.approved(n) for n in (1, 2, 3, 4)]
        self.run_job()
        states = [("DELIVERED", ""), ("FAILED", "no_service"), ("CANCELLED", ""), ("BLOCKED", "opted_out")]
        for item, (state, code) in zip(items, states):
            SmsMessage.objects.filter(pk=self.message(item).pk).update(state=state, error_code=code, error=code if state == "BLOCKED" else "")
        self.assertEqual(sms_channel.reconcile(), 4)
        for item in items:
            item.refresh_from_db()
        self.assertEqual([i.status for i in items], [ItemStatus.SENT, ItemStatus.FAILED, ItemStatus.CANCELLED, ItemStatus.CANCELLED])
        self.assertEqual(SendAttempt.objects.get(item=items[0]).outcome, "delivered")
        self.assertIn("آنتن", items[1].skip_reason_text)
        self.assertIn("دوباره تلاش نمی‌شود", items[1].skip_reason_text)
        self.assertIn("لغو داده بود", items[3].skip_reason_text)

    def test_a_queued_message_stays_handed_off_until_the_phone_reports(self):
        item = self.approved()
        self.run_job()
        SmsMessage.objects.filter(pk=self.message(item).pk).update(state="CLAIMED")
        self.assertEqual(sms_channel.reconcile(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.HANDED_OFF)

    def test_the_campaign_status_and_item_list_fold_the_phones_report_in(self):
        item = self.approved()
        self.run_job()
        SmsMessage.objects.filter(pk=self.message(item).pk).update(state="SENT")
        client = client_for(self.staff)
        status = client.get(f"/api/v1/growth/outreach/campaigns/{self.campaign.pk}/status/").json()
        self.assertEqual(status["counts"], {"sent": 1})
        self.assertIn("sms", status["channels"])

    def test_an_sms_is_handed_over_once_even_if_the_job_runs_again(self):
        item = self.approved()
        self.run_job()
        again = OutreachJob.objects.create(campaign=self.campaign, kind=OutreachJob.Kind.SEND)
        sending.run_send(again.pk, sleep=FakeSleep(), rng=MidRng())
        self.assertEqual(SmsMessage.objects.count(), 1)
        self.assertFalse(sending.claim(item.pk))

    def test_handed_off_items_count_as_contacted_for_the_duplicate_rules(self):
        item = self.approved()
        self.run_job()
        other = campaigns.create_campaign(name="دوباره", template=self.template, mode=Campaign.Mode.AUTO, channel=Channel.SMS)
        self.assertEqual(campaigns.add_leads(other, [item.lead_id]).skipped[0]["reason"], "already_contacted")
        self.assertEqual(campaigns.remove_items(self.campaign, [item.pk])["refused"][0]["reason"], "not_removable")

    def test_the_campaign_is_complete_once_everything_is_handed_off_or_settled(self):
        self.approved()
        self.run_job()
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.COMPLETED)

    def test_a_lost_message_is_marked_failed_never_retried(self):
        item = self.approved()
        self.run_job()
        SmsMessage.objects.all().delete()
        OutreachItem.objects.filter(pk=item.pk).update(updated_at=timezone.now() - timedelta(minutes=30))
        self.assertEqual(sms_channel.reconcile(), 1)
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.FAILED, "not_in_queue"))


class GuardrailTests(SmsBase):
    def test_a_number_that_replied_stop_after_approval_is_skipped_and_never_queued(self):
        item = self.approved()
        mobile.add_opt_out("09126660001")
        self.run_job()
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.SKIPPED, "channel_opted_out"))
        self.assertEqual(SmsMessage.objects.filter(kind="marketing").count(), 0)

    def test_the_do_not_contact_list_is_honoured_here_and_by_the_phone_app_too(self):
        item = self.approved()
        suppression.suppress_lead(item.lead, "opt_out", "", self.staff)
        self.assertTrue(mobile.is_opted_out("09126660001"))  # the app reads our list as well
        self.run_job()
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.SKIPPED, "suppressed"))
        self.assertEqual(SmsMessage.objects.count(), 0)

    def test_the_phone_going_away_after_approval_stops_the_hand_over(self):
        item = self.approved()
        MobileDevice.objects.update(revoked_at=timezone.now())
        self.run_job()
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.NEEDS_MANUAL, "channel_not_ready"))
        self.assertIn("NM-Mobile", item.skip_reason_text)
        self.assertEqual(SmsMessage.objects.count(), 0)

    def test_editing_the_text_voids_the_approval(self):
        item = self.approved()
        from apps.growth_engine.outreach.services import items as item_service

        item_service.edit_item(item, text=item.rendered_text.replace("سلام", "درود"), actor=self.staff)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.READY)
        self.assertEqual(SmsMessage.objects.count(), 0)

    def test_a_text_made_too_long_after_approval_is_refused_at_send(self):
        item = self.approved()
        from apps.growth_engine.outreach.services import items as item_service

        long_text = item.rendered_text + " " + "س" * 120
        item_service.edit_item(item, text=long_text, actor=self.staff)
        item.refresh_from_db()
        self.assertEqual(approval.approve_items(self.campaign, item_ids=[item.pk], actor=self.staff)["approved"], 0)

    def test_the_per_channel_cap_applies(self):
        channel_config.update("sms", {"daily_cap": 1}, self.staff)
        for n in (1, 2):
            self.approved(n)
        job = self.run_job()
        self.assertEqual(SmsMessage.objects.count(), 1)
        self.assertIn("سقفِ روزانهٔ کانالِ", job.note)

    def test_the_sender_block_of_an_sms_is_the_short_one(self):
        item = self.ready()
        self.assertEqual(item.rendered_text.splitlines()[-2], "آپ‌مارکت")
        self.assertNotIn("0912 123 4567", item.rendered_text)


class RecallTests(SmsBase):
    def queued(self, n=1):
        item = self.approved(n)
        return item

    def test_pausing_the_campaign_takes_the_unsent_messages_back(self):
        a, b = self.queued(1), self.queued(2)
        self.run_job()
        SmsMessage.objects.filter(pk=self.message(a).pk).update(state="CLAIMED")  # the phone already has this one
        campaigns.pause(self.campaign, self.staff)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.status, ItemStatus.HANDED_OFF)  # in the phone's hands: cannot be recalled
        self.assertEqual((b.status, b.skip_reason), (ItemStatus.CANCELLED, "campaign_revoked"))
        self.assertEqual(self.message(b).state, "BLOCKED")
        self.assertFalse(SmsCampaignApproval.objects.get(ref=f"ge:{self.campaign.pk}").active)

    def test_cancelling_the_campaign_does_the_same(self):
        item = self.queued()
        self.run_job()
        campaigns.cancel(self.campaign, self.staff)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.CANCELLED)
        self.assertEqual(self.message(item).state, "BLOCKED")

    def test_the_emergency_stop_recalls_every_campaigns_unsent_messages(self):
        item = self.queued()
        self.run_job()
        compliance_settings.set_emergency_stop(True, self.staff)
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.CANCELLED, "campaign_revoked"))
        self.assertEqual(self.message(item).state, "BLOCKED")
        self.assertIn("متوقف", item.skip_reason_text)

    def test_the_stop_hook_is_registered_and_failures_in_it_never_undo_the_stop(self):
        from unittest import mock

        self.queued()
        self.run_job()
        with mock.patch.object(sms_channel, "revoke_pending", side_effect=RuntimeError("gateway down")):
            compliance_settings.set_emergency_stop(True, self.staff)
        self.assertTrue(GrowthSettings.load().emergency_stop)

    def test_releasing_the_stop_does_not_resurrect_anything(self):
        item = self.queued()
        self.run_job()
        compliance_settings.set_emergency_stop(True, self.staff)
        compliance_settings.set_emergency_stop(False, self.staff)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.CANCELLED)
        self.assertEqual(self.message(item).state, "BLOCKED")


class OptOutRoundTripTests(SmsBase):
    def test_a_stop_reply_on_the_phone_is_seen_by_our_guard(self):
        item = self.ready()
        SmsOptOut.objects.create(number="989126660001", key="9126660001")
        outcome = approval.approve_items(self.campaign, item_ids=[item.pk], actor=self.staff)
        self.assertEqual(outcome["approved"], 0)
        self.assertEqual(outcome["refused"][0]["code"], "channel_opted_out")
