from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from apps.growth_engine.compliance.models import AuditEntry
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.testing import NoNetworkMixin, make_staff
from apps.growth_engine.leads.models import Lead
from apps.growth_engine.outreach.models import Campaign, ItemStatus, OutreachItem, OutreachJob
from apps.growth_engine.outreach.services import campaigns, targets

from .helpers import Site, approved_item, configure, make_campaign, make_lead, make_template


class CreateTests(NoNetworkMixin, TestCase):
    def test_create_audits_and_validates(self):
        staff = make_staff()
        campaign = campaigns.create_campaign(name=" بهار ", template=make_template(), mode="auto", user=staff)
        self.assertEqual((campaign.name, campaign.status, campaign.created_by_id), ("بهار", "draft", staff.pk))
        self.assertTrue(AuditEntry.objects.filter(kind="campaign_status", data__campaign_id=campaign.pk).exists())
        for kwargs, code in [({"name": ""}, "name_required"), ({"name": "x" * 151}, "name_too_long"), ({"mode": "robot"}, "invalid_mode")]:
            with self.subTest(code=code), self.assertRaises(campaigns.CampaignError) as ctx:
                campaigns.create_campaign(**{"name": "ok", "template": make_template(), "mode": "auto", **kwargs})
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(campaigns.CampaignError) as ctx:
            campaigns.create_campaign(name="ok", template=make_template(is_active=False), mode="auto")
        self.assertEqual(ctx.exception.code, "template_inactive")


class AddLeadsTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign()

    def reasons(self, result):
        return {s["lead_id"]: s["reason"] for s in result.skipped}

    def test_a_lead_with_a_form_page_is_added_with_the_final_message(self):
        configure()
        lead = make_lead("shop-a.ir", name="گل‌سرخ")
        result = campaigns.add_leads(self.campaign, [lead.pk])
        item = result.added[0]
        self.assertEqual((item.status, item.domain, item.target_url, item.forced), ("pending", "shop-a.ir", "https://shop-a.ir/contact", False))
        self.assertTrue(item.rendered_text.startswith("سلام گل‌سرخ"))
        self.assertIn("علی رضایی | آپ‌مارکت", item.rendered_text)
        self.assertTrue(item.rendered_text.endswith("«لغو»."))
        self.assertEqual(item.subject, "معرفی آپ‌مارکت")
        self.assertEqual(len(item.fingerprint), 64)

    def test_every_refusal_has_a_code_and_a_persian_text(self):
        other = make_campaign(self.campaign.template, name="دیگر")
        archived = make_lead("a1.ir")
        Lead.objects.filter(pk=archived.pk).update(is_archived=True)
        blocked = make_lead("a2.ir")
        suppression.suppress_lead(blocked, "opt_out", "", None)
        contacted = make_lead("a3.ir")
        OutreachItem.objects.create(campaign=other, lead=contacted, status=ItemStatus.SENT, domain="a3.ir")
        no_form = make_lead("a4.ir", form=False)
        ok = make_lead("a5.ir")
        dup = make_lead("a6.ir")
        campaigns.add_leads(self.campaign, [dup.pk])
        ids = [999999, archived.pk, blocked.pk, contacted.pk, no_form.pk, dup.pk, ok.pk]
        result = campaigns.add_leads(self.campaign, ids)
        self.assertEqual(
            self.reasons(result),
            {999999: "lead_missing", archived.pk: "archived", blocked.pk: "suppressed", contacted.pk: "already_contacted",
             no_form.pk: "no_target_url", dup.pk: "already_in_campaign"},
        )
        self.assertTrue(all(s["reason_text"] for s in result.skipped))
        self.assertEqual([i.lead_id for i in result.added], [ok.pk])

    def test_failed_and_sending_and_manual_sent_also_block_a_second_message(self):
        for status in (ItemStatus.FAILED, ItemStatus.SENDING, ItemStatus.MANUAL_SENT, ItemStatus.SENT):
            with self.subTest(status=status):
                other = make_campaign(self.campaign.template, name=f"x-{status}")
                host = f"{status}.ir".replace("_", "-")
                lead = make_lead(host)
                OutreachItem.objects.create(campaign=other, lead=lead, status=status, domain=host)
                self.assertEqual(self.reasons(campaigns.add_leads(self.campaign, [lead.pk])), {lead.pk: "already_contacted"})

    def test_other_outcomes_do_not_block(self):
        other = make_campaign(self.campaign.template, name="x")
        lead = make_lead("fine.ir")
        OutreachItem.objects.create(campaign=other, lead=lead, status=ItemStatus.NO_FORM, domain="fine.ir")
        self.assertEqual(len(campaigns.add_leads(self.campaign, [lead.pk]).added), 1)

    def test_a_different_template_is_a_different_message(self):
        other = make_campaign(make_template(name="دیگر"), name="x")
        lead = make_lead("t.ir")
        OutreachItem.objects.create(campaign=other, lead=lead, status=ItemStatus.SENT, domain="t.ir")
        self.assertEqual(len(campaigns.add_leads(self.campaign, [lead.pk]).added), 1)

    def test_one_site_one_message_per_campaign(self):
        a, b = make_lead("same.ir"), make_lead("other.ir")
        with mock.patch.object(targets, "domain_key", return_value="same.ir"):
            result = campaigns.add_leads(self.campaign, [a.pk, b.pk])
        self.assertEqual(self.reasons(result), {b.pk: "duplicate_domain"})

    def test_the_database_itself_refuses_a_second_message_per_lead_or_site(self):
        lead = make_lead("db.ir")
        OutreachItem.objects.create(campaign=self.campaign, lead=lead, domain="db.ir")
        with self.assertRaises(IntegrityError), transaction.atomic():
            OutreachItem.objects.create(campaign=self.campaign, lead=lead, domain="")
        with self.assertRaises(IntegrityError), transaction.atomic():
            OutreachItem.objects.create(campaign=self.campaign, lead=make_lead("db2.ir"), domain="db.ir")
        OutreachItem.objects.create(campaign=self.campaign, lead=make_lead("db3.ir"), domain="")  # no site: no constraint

    @override_settings(GROWTH_ENGINE={"SEND_MAX_ITEMS_PER_CAMPAIGN": 2})
    def test_campaign_size_limit(self):
        leads = [make_lead(f"l{i}.ir") for i in range(3)]
        result = campaigns.add_leads(self.campaign, [lead.pk for lead in leads])
        self.assertEqual((len(result.added), self.reasons(result)), (2, {leads[2].pk: "limit"}))

    def test_force_is_for_manual_campaigns_only(self):
        sent = make_lead("f.ir")
        other = make_campaign(self.campaign.template, name="x")
        OutreachItem.objects.create(campaign=other, lead=sent, status=ItemStatus.SENT, domain="f.ir")
        auto = campaigns.add_leads(self.campaign, [sent.pk], force=True)
        self.assertEqual(self.reasons(auto), {sent.pk: "already_contacted"})
        manual = make_campaign(self.campaign.template, mode="manual", name="m")
        result = campaigns.add_leads(manual, [sent.pk], force=True)
        self.assertTrue(result.added[0].forced)
        self.assertEqual(self.reasons(campaigns.add_leads(make_campaign(self.campaign.template, mode="manual", name="m2"), [sent.pk])), {sent.pk: "already_contacted"})

    def test_a_manual_campaign_accepts_a_lead_without_a_form_page(self):
        manual = make_campaign(mode="manual", name="m")
        lead = make_lead("nf.ir", form=False)
        item = campaigns.add_leads(manual, [lead.pk]).added[0]
        self.assertEqual((item.target_url, item.status), ("", "pending"))

    def test_closed_campaigns_take_no_leads(self):
        campaigns.cancel(self.campaign)
        with self.assertRaises(campaigns.CampaignError):
            campaigns.add_leads(self.campaign, [make_lead("z.ir").pk])

    def test_the_best_contact_page_is_chosen(self):
        from apps.growth_engine.leads.models import ContactPoint

        lead = make_lead("best.ir", form=False)
        for label, conf_, path in [("صفحهٔ تماس (فرمی دیده نشد)", 99, "/c1"), ("تیکت/پشتیبانی", 70, "/ticket"), ("فرم تماس", 60, "/form"), ("فرم تماس", 85, "/form2")]:
            ContactPoint.objects.create(lead=lead, kind="contact_form", value=f"https://best.ir{path}", normalized=f"https://best.ir{path}", label=label, confidence=conf_)
        self.assertEqual(targets.target_url(lead), "https://best.ir/form2")


class RemoveItemsTests(NoNetworkMixin, TestCase):
    def test_sent_failed_and_sending_items_stay_as_the_record(self):
        campaign = make_campaign()
        items = {s: OutreachItem.objects.create(campaign=campaign, lead=make_lead(f"{s}.ir".replace("_", "-")), status=s, domain=f"{s}.ir".replace("_", "-"))
                 for s in (ItemStatus.PENDING, ItemStatus.READY, ItemStatus.SENT, ItemStatus.FAILED, ItemStatus.SENDING, ItemStatus.MANUAL_SENT)}
        result = campaigns.remove_items(campaign, [i.pk for i in items.values()])
        self.assertEqual(result["removed"], 2)
        self.assertEqual(sorted(r["item_id"] for r in result["refused"]), sorted(items[s].pk for s in (ItemStatus.SENT, ItemStatus.FAILED, ItemStatus.SENDING, ItemStatus.MANUAL_SENT)))
        self.assertEqual(campaign.items.count(), 4)


class StatusTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.site = Site().shop("shop-a.ir")

    def test_start_is_refused_until_sending_is_ready(self):
        campaign = make_campaign()
        with self.assertRaises(campaigns.CampaignError) as ctx:
            campaigns.start(campaign, self.staff)
        self.assertEqual(ctx.exception.code, "not_ready")
        self.assertIn("خاموش", ctx.exception.message)
        self.assertIn("نام", ctx.exception.message)  # the identity problems are listed too
        configure(emergency_stop=True)
        with self.assertRaises(campaigns.CampaignError) as ctx:
            campaigns.start(campaign, self.staff)
        self.assertIn("توقفِ اضطراری", ctx.exception.message)

    def test_start_needs_an_approved_item_then_makes_one_send_job(self):
        configure()
        campaign = make_campaign()
        with self.assertRaises(campaigns.CampaignError) as ctx:
            campaigns.start(campaign, self.staff)
        self.assertEqual(ctx.exception.code, "nothing_approved")
        approved_item(self.site, campaign, staff=self.staff)
        started, job, created = campaigns.start(campaign, self.staff)
        self.assertEqual((started.status, created, job.kind, job.total_items, job.status), ("active", True, "send", 1, "queued"))
        again, same, created2 = campaigns.start(campaign, self.staff)
        self.assertEqual((same.pk, created2), (job.pk, False))  # a running job is not duplicated

    def test_a_cap_that_is_used_up_blocks_start(self):
        configure(daily_cap=1)
        campaign = make_campaign()
        approved_item(self.site, campaign, staff=self.staff)
        from apps.growth_engine.outreach.models import SendAttempt

        SendAttempt.objects.create(item=OutreachItem.objects.create(campaign=make_campaign(name="x"), lead=make_lead("c.ir"), status=ItemStatus.SENT), url="u")
        with self.assertRaises(campaigns.CampaignError) as ctx:
            campaigns.start(campaign, self.staff)
        self.assertIn("سقفِ روزانه", ctx.exception.message)

    def test_manual_campaign_starts_without_any_readiness(self):
        campaign = make_campaign(mode="manual")
        started, job, created = campaigns.start(campaign, self.staff)
        self.assertEqual((started.status, job, created), ("active", None, False))

    def test_pause_cancel_and_closed_campaigns(self):
        configure()
        campaign = make_campaign()
        approved_item(self.site, campaign, staff=self.staff)
        self.assertEqual(OutreachItem.objects.filter(status="approved").count(), 1)
        campaigns.start(campaign, self.staff)
        paused = campaigns.pause(campaign, self.staff)
        self.assertEqual(paused.status, "paused")
        self.assertTrue(OutreachJob.objects.get(kind="send").cancel_requested)
        with self.assertRaises(campaigns.CampaignError):
            campaigns.pause(campaign, self.staff)  # not active any more
        cancelled = campaigns.cancel(campaign, self.staff)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(OutreachItem.objects.get(campaign=campaign).status, "cancelled")
        self.assertIsNone(OutreachItem.objects.get(campaign=campaign).approved_record)
        for action in (campaigns.cancel, campaigns.start):
            with self.assertRaises(campaigns.CampaignError):
                action(campaign, self.staff)

    def test_cancel_keeps_what_was_already_sent(self):
        campaign = make_campaign()
        sent = OutreachItem.objects.create(campaign=campaign, lead=make_lead("s.ir"), status=ItemStatus.SENT, domain="s.ir")
        failed = OutreachItem.objects.create(campaign=campaign, lead=make_lead("f.ir"), status=ItemStatus.FAILED, domain="f.ir")
        pending = OutreachItem.objects.create(campaign=campaign, lead=make_lead("p.ir"), status=ItemStatus.PENDING, domain="p.ir")
        campaigns.cancel(campaign)
        self.assertEqual([OutreachItem.objects.get(pk=i.pk).status for i in (sent, failed, pending)], ["sent", "failed", "cancelled"])

    def test_an_active_campaign_with_nothing_left_completes(self):
        campaign = make_campaign()
        campaign.status = Campaign.Status.ACTIVE
        campaign.save()
        item = OutreachItem.objects.create(campaign=campaign, lead=make_lead("d.ir"), status=ItemStatus.READY, domain="d.ir")
        self.assertFalse(campaigns.maybe_complete(campaign))
        OutreachItem.objects.filter(pk=item.pk).update(status=ItemStatus.SENT)
        self.assertTrue(campaigns.maybe_complete(campaign))
        self.assertEqual(Campaign.objects.get(pk=campaign.pk).status, "completed")
        self.assertIsNotNone(Campaign.objects.get(pk=campaign.pk).finished_at)

    def test_counts_for_several_campaigns_in_one_query(self):
        a, b = make_campaign(name="a"), make_campaign(name="b")
        OutreachItem.objects.create(campaign=a, lead=make_lead("c1.ir"), status=ItemStatus.READY, domain="c1.ir")
        OutreachItem.objects.create(campaign=a, lead=make_lead("c2.ir"), status=ItemStatus.READY, domain="c2.ir")
        OutreachItem.objects.create(campaign=b, lead=make_lead("c3.ir"), status=ItemStatus.SENT, domain="c3.ir")
        with self.assertNumQueries(1):
            counted = campaigns.counts([a.pk, b.pk])
        self.assertEqual(counted, {a.pk: {"ready": 2}, b.pk: {"sent": 1}})
