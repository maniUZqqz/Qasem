"""The e-mail channel end to end on the in-memory mail backend: nothing here can reach a real mail server."""
from __future__ import annotations

import smtplib
import socket
from email.header import decode_header, make_header
from email.utils import parseaddr
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings

from apps.growth_engine.compliance.models import AuditEntry, GrowthSettings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.compliance.services import settings as compliance_settings
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_staff
from apps.growth_engine.outreach.channels import email as email_channel
from apps.growth_engine.outreach.models import Campaign, Channel, ItemStatus, OutreachItem, OutreachJob, SendAttempt
from apps.growth_engine.outreach.services import approval, campaigns, channel_config, preparing, sending

from .helpers import FakeSleep, MidRng, configure, make_lead, make_template

PASSWORD = "mail-PASSWORD-hush-7"
LOCMEM = {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


@override_settings(GROWTH_ENGINE=LOCMEM)
class EmailBase(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        channel_config.update(
            "email",
            {"config": {"host": "smtp.example.test", "port": 587, "security": "starttls", "from_email": "no-reply@upmarket.ir", "username": "mailer"},
             "secrets": {"smtp_password": PASSWORD}, "enabled": True}, self.staff,
        )
        self.template = make_template("ایمیل معرفی", channel="email", subject="معرفی آپ‌مارکت برای {business_name}")
        self.campaign = campaigns.create_campaign(name="ایمیل", template=self.template, mode=Campaign.Mode.AUTO, channel=Channel.EMAIL, user=self.staff)

    def lead(self, n, **kw):
        return make_lead(f"e{n}.ir", email=f"info@e{n}.ir", form=False, **kw)

    def ready(self, n=1, **kw):
        lead = self.lead(n, **kw)
        item = campaigns.add_leads(self.campaign, [lead.pk]).added[0]
        preparing.prepare_item(item, None, GrowthSettings.load())
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason_text), (ItemStatus.READY, ""), item.plan)
        return item

    def approved(self, n=1, **kw):
        item = self.ready(n, **kw)
        self.assertEqual(approval.approve_items(self.campaign, item_ids=[item.pk], actor=self.staff)["approved"], 1)
        item.refresh_from_db()
        return item

    def run_job(self, **kw):
        campaign, job, created = campaigns.start(self.campaign, self.staff)
        self.assertTrue(created)
        sleep = kw.pop("sleep", FakeSleep())
        status = sending.run_send(job.pk, sleep=sleep, rng=MidRng(), **kw)
        job.refresh_from_db()
        return job, sleep, status


class PrepareTests(EmailBase):
    def test_a_ready_item_knows_who_and_from_where(self):
        item = self.ready()
        self.assertEqual((item.channel, item.recipient), (Channel.EMAIL, "info@e1.ir"))
        self.assertEqual(item.plan["recipient"], "info@e1.ir")
        self.assertEqual((item.plan["from"], item.plan["reply_to"]), ("no-reply@upmarket.ir", "ali@upmarket.ir"))
        self.assertEqual(item.subject, f"معرفی آپ‌مارکت برای {item.lead.business_name}")
        self.assertTrue(item.fingerprint)
        self.assertNotIn(PASSWORD, str(item.plan))

    def test_without_a_mail_account_the_item_waits_with_the_reason(self):
        channel_config.ChannelConfig.objects.filter(channel="email").update(config={}, secrets={})
        item = campaigns.add_leads(self.campaign, [self.lead(2).pk]).added[0]
        preparing.prepare_item(item, None, GrowthSettings.load())
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.NEEDS_MANUAL, "channel_not_ready"))
        self.assertIn("سرورِ ایمیل", item.skip_reason_text)

    def test_an_empty_subject_is_a_problem(self):
        item = campaigns.add_leads(self.campaign, [self.lead(3).pk]).added[0]
        OutreachItem.objects.filter(pk=item.pk).update(subject="")
        item.refresh_from_db()
        item.text_edited = True
        preparing.prepare_item(item, None, GrowthSettings.load())
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.NEEDS_MANUAL)
        self.assertIn("موضوعِ ایمیل خالی است", item.skip_reason_text)

    def test_a_lead_whose_only_email_is_a_placeholder_is_not_added(self):
        lead = make_lead("e9.ir", email="name@example.com", form=False)
        result = campaigns.add_leads(self.campaign, [lead.pk])
        self.assertEqual([s["reason"] for s in result.skipped], ["no_email"])


class SendTests(EmailBase):
    def test_one_approved_email_goes_out_with_the_right_headers_and_footer(self):
        item = self.approved()
        job, sleep, status = self.run_job()
        self.assertEqual(status, "completed")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["info@e1.ir"])
        name, address = parseaddr(message.from_email)
        self.assertEqual((str(make_header(decode_header(name))), address), ("آپ‌مارکت", "no-reply@upmarket.ir"))
        self.assertEqual(message.reply_to, ["ali@upmarket.ir"])
        self.assertEqual(message.subject, item.subject)
        self.assertEqual(message.body, item.rendered_text)
        self.assertIn("ali@upmarket.ir", message.body)  # the sender block
        self.assertTrue(message.body.rstrip().endswith("اگر مایل به دریافت پیام نیستید، پاسخ دهید «لغو»."))
        self.assertEqual(message.extra_headers["List-Unsubscribe"], "<mailto:ali@upmarket.ir?subject=%D9%84%D8%BA%D9%88>")
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.SENT)
        item.lead.refresh_from_db()
        self.assertEqual(item.lead.status, "contacted")

    def test_the_attempt_the_history_and_the_audit_are_written_and_hold_no_password(self):
        item = self.approved()
        self.run_job()
        attempt = SendAttempt.objects.get(item=item)
        self.assertEqual((attempt.channel, attempt.method, attempt.outcome, attempt.success_guess), (Channel.EMAIL, "SMTP", "smtp_accepted", "likely_success"))
        self.assertEqual(attempt.url, "mailto:info@e1.ir")
        names = {p["name"] for p in attempt.payload}
        self.assertTrue({"to", "subject", "message_sha256", "from", "reply_to"} <= names)
        activity = item.lead.activities.filter(kind="queue_outcome").first()
        self.assertEqual((activity.data["channel"], activity.data["outcome"], activity.data["recipient"]), ("email", "sent", "info@e1.ir"))
        self.assertEqual(activity.data["message_text"], item.rendered_text)
        everything = str(list(SendAttempt.objects.values())) + str(list(AuditEntry.objects.values())) + str(list(item.lead.activities.values()))
        self.assertNotIn(PASSWORD, everything)

    def test_an_email_is_never_sent_twice(self):
        self.approved()
        self.run_job()
        self.assertEqual(len(mail.outbox), 1)
        # a second job finds nothing approved; and even a forced re-claim of a sent item is refused
        item = OutreachItem.objects.get()
        self.assertFalse(sending.claim(item.pk))
        job = OutreachJob.objects.create(campaign=self.campaign, kind=OutreachJob.Kind.SEND)
        sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng())
        self.assertEqual(len(mail.outbox), 1)

    def test_the_second_item_waits_one_spacing_of_its_own_channel(self):
        channel_config.update("email", {"spacing_min_seconds": 20, "spacing_max_seconds": 40}, self.staff)
        self.approved(1)
        self.approved(2)
        job, sleep, _ = self.run_job()
        self.assertEqual(len(mail.outbox), 2)
        self.assertAlmostEqual(sleep.total, 30, delta=1.5)  # one gap of (20+40)/2, not the global 60-120

    def test_the_channels_daily_cap_stops_the_run_and_the_rest_wait(self):
        channel_config.update("email", {"daily_cap": 2}, self.staff)
        for n in (1, 2, 3):
            self.approved(n)
        job, _, status = self.run_job()
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(OutreachItem.objects.filter(status=ItemStatus.APPROVED).count(), 1)
        self.assertIn("سقفِ روزانهٔ کانالِ «ایمیل» پر شد", job.note)
        self.assertEqual(channel_config.cap_remaining(Channel.EMAIL), 0)

    def test_the_global_cap_counts_every_channel(self):
        configure(daily_cap=1)
        self.approved(1)
        self.approved(2)
        job, _, _ = self.run_job()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("سقفِ روزانه (1 پیام)", job.note)

    def test_an_edited_text_voids_the_approval_and_nothing_is_sent(self):
        item = self.approved()
        from apps.growth_engine.outreach.services import items as item_service

        item_service.edit_item(item, text=item.rendered_text.replace("سلام", "درود"), actor=self.staff)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.READY)
        self.assertIsNone(item.approved_record)
        with self.assertRaises(campaigns.CampaignError):
            campaigns.start(self.campaign, self.staff)  # nothing approved any more
        self.assertEqual(mail.outbox, [])

    def test_changing_the_from_address_after_approval_voids_it(self):
        item = self.approved()
        channel_config.update("email", {"config": {"from_email": "other@upmarket.ir"}}, self.staff)
        job, _, _ = self.run_job()
        self.assertEqual(mail.outbox, [])
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.READY)
        self.assertEqual(item.plan["from"], "other@upmarket.ir")  # the fresh plan is kept so a new approval can follow
        self.assertEqual(job.items_blocked, 1)

    def test_do_not_contact_added_after_approval_skips_the_item(self):
        item = self.approved()
        suppression.suppress_lead(item.lead, "opt_out", "", self.staff)
        self.run_job()
        self.assertEqual(mail.outbox, [])
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.SKIPPED, "suppressed"))

    def test_emergency_stop_sends_nothing(self):
        item = self.approved()
        compliance_settings.set_emergency_stop(True, self.staff)
        job = OutreachJob.objects.create(campaign=self.campaign, kind=OutreachJob.Kind.SEND)
        sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng())
        self.assertEqual(mail.outbox, [])
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.APPROVED)

    def test_turning_the_channel_off_during_the_run_keeps_its_items_approved(self):
        item = self.approved()
        channel_config.update("email", {"enabled": False}, self.staff)
        job = OutreachJob.objects.create(campaign=self.campaign, kind=OutreachJob.Kind.SEND)
        self.campaign.status = Campaign.Status.ACTIVE
        self.campaign.save()
        status = sending.run_send(job.pk, sleep=FakeSleep(), rng=MidRng())
        self.assertEqual(mail.outbox, [])
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.APPROVED)
        job.refresh_from_db()
        self.assertIn("خاموش است", job.note)
        self.assertEqual(status, "completed")

    def test_a_campaign_cannot_start_while_its_channel_is_off(self):
        self.approved()
        channel_config.update("email", {"enabled": False}, self.staff)
        with self.assertRaises(campaigns.CampaignError) as cm:
            campaigns.start(self.campaign, self.staff)
        self.assertIn("خاموش است", cm.exception.message)

    def test_sending_off_in_settings_sends_nothing(self):
        self.approved()
        configure(sending_enabled=False)
        with self.assertRaises(campaigns.CampaignError):
            campaigns.start(self.campaign, self.staff)
        self.assertEqual(mail.outbox, [])


class FailureTests(EmailBase):
    def send_with(self, exc):
        item = self.approved()
        with mock.patch("django.core.mail.message.EmailMessage.send", side_effect=exc):
            job, _, _ = self.run_job()
        item.refresh_from_db()
        return item, job

    def test_a_refused_login_sends_nothing_and_leaves_the_item_for_a_person(self):
        item, job = self.send_with(smtplib.SMTPAuthenticationError(535, b"bad credentials PASSWORD"))
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.NEEDS_MANUAL, "email_auth_failed"))
        self.assertFalse(SendAttempt.objects.filter(item=item).exists())  # nothing left: no attempt, no allowance used
        self.assertIn("نامِ کاربری یا رمز", item.skip_reason_text)
        self.assertNotIn("PASSWORD", item.skip_reason_text)
        self.assertEqual(job.items_blocked, 1)

    def test_a_refused_recipient_or_sender_is_not_an_attempt(self):
        item, _ = self.send_with(smtplib.SMTPRecipientsRefused({"info@e1.ir": (550, b"no such user")}))
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.NEEDS_MANUAL, "email_recipient_refused"))
        self.assertFalse(SendAttempt.objects.filter(item=item).exists())

    def test_a_connection_that_never_opened_is_not_an_attempt(self):
        item, _ = self.send_with(ConnectionRefusedError(111, "refused"))
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.NEEDS_MANUAL, "email_connect_error"))

    def test_a_timeout_may_have_delivered_so_it_is_failed_and_never_tried_again(self):
        item, job = self.send_with(socket.timeout("timed out"))
        self.assertEqual((item.status, item.skip_reason), (ItemStatus.FAILED, "send_failed"))
        attempt = SendAttempt.objects.get(item=item)
        self.assertEqual((attempt.outcome, attempt.success_guess), ("timeout", "unclear"))
        self.assertIn("معلوم نیست ایمیل رفته یا نه", item.skip_reason_text)
        self.assertEqual(job.items_failed, 1)
        # a second job must not touch it
        again = OutreachJob.objects.create(campaign=self.campaign, kind=OutreachJob.Kind.SEND)
        with mock.patch("django.core.mail.message.EmailMessage.send") as send:
            sending.run_send(again.pk, sleep=FakeSleep(), rng=MidRng())
        self.assertFalse(send.called)

    def test_a_dropped_session_is_also_never_retried(self):
        item, _ = self.send_with(smtplib.SMTPServerDisconnected("gone"))
        self.assertEqual(item.status, ItemStatus.FAILED)
        self.assertEqual(SendAttempt.objects.get(item=item).outcome, "disconnected")

    def test_an_unexpected_exception_keeps_the_record_and_the_one_attempt_rule(self):
        item, job = self.send_with(RuntimeError("weird"))
        self.assertEqual(item.status, ItemStatus.FAILED)
        attempt = SendAttempt.objects.get(item=item)
        self.assertEqual((attempt.channel, attempt.method, attempt.outcome), (Channel.EMAIL, "SMTP", "internal_error"))

    def test_one_broken_email_does_not_stop_the_next(self):
        first = self.approved(1)
        second = self.approved(2)
        calls = {"n": 0}
        real = email_channel.send

        def flaky(item):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(item)

        with mock.patch.object(email_channel, "send", flaky):
            job, _, _ = self.run_job()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.status, second.status), (ItemStatus.FAILED, ItemStatus.SENT))
        self.assertEqual(len(mail.outbox), 1)


@override_settings(GROWTH_ENGINE=LOCMEM)
class VerifyTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.client = client_for(self.staff)

    def test_verify_reports_the_missing_account_and_sends_nothing(self):
        response = self.client.post("/api/v1/growth/outreach/channels/email/verify/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.assertIn("سرورِ ایمیل", response.json()["message"])
        self.assertEqual(mail.outbox, [])

    def test_verify_opens_a_session_but_never_sends(self):
        channel_config.update("email", {"config": {"host": "smtp.example.test", "from_email": "n@upmarket.ir"}}, self.staff)
        response = self.client.post("/api/v1/growth/outreach/channels/email/verify/").json()
        self.assertTrue(response["ok"])
        self.assertIn("ایمیلی فرستاده نشد", response["message"])
        self.assertEqual(mail.outbox, [])

    def test_verify_explains_a_refused_login_without_echoing_the_password(self):
        channel_config.update("email", {"config": {"host": "smtp.example.test", "from_email": "n@upmarket.ir", "username": "u"}, "secrets": {"smtp_password": PASSWORD}}, self.staff)
        with mock.patch("django.core.mail.backends.locmem.EmailBackend.open", side_effect=smtplib.SMTPAuthenticationError(535, PASSWORD.encode())):
            response = self.client.post("/api/v1/growth/outreach/channels/email/verify/").json()
        self.assertFalse(response["ok"])
        self.assertIn("نامِ کاربری یا رمز", response["message"])
        self.assertNotIn(PASSWORD, str(response))

    def test_staff_only(self):
        self.assertEqual(client_for().post("/api/v1/growth/outreach/channels/email/verify/").status_code, 401)
