"""The manual queue: a person sends by hand and records the outcome."""
from django.test import TestCase

from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.testing import NoNetworkMixin, make_staff
from apps.growth_engine.leads.models import Lead, LeadActivity
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.outreach.models import Campaign, ItemStatus, OutreachItem
from apps.growth_engine.outreach.services import campaigns, items, manual

from .helpers import configure, make_campaign, make_lead


class ManualOutcomeTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.campaign = make_campaign(mode="manual", user=self.staff)

    def add(self, host, **kw):
        lead = make_lead(host, **kw)
        return OutreachItem.objects.select_related("lead", "campaign", "campaign__template").get(pk=campaigns.add_leads(self.campaign, [lead.pk]).added[0].pk)

    def test_each_outcome_sets_its_status_and_logs_the_exact_message(self):
        expected = {"sent": "manual_sent", "no_form": "no_form", "needs_login": "needs_login", "skipped": "skipped"}
        pending = {outcome: self.add(f"{outcome.replace('_', '-')}.ir") for outcome in expected}  # all four first: the campaign stays open
        for outcome, status in expected.items():
            with self.subTest(outcome=outcome):
                item = pending[outcome]
                items.edit_item(item, text=item.rendered_text.replace("سلام", "درود"), actor=self.staff)
                item.refresh_from_db()
                manual.record_outcome(item, outcome, " یادداشتِ من ", self.staff)
                item = OutreachItem.objects.get(pk=item.pk)
                self.assertEqual((item.status, item.manual_note), (status, "یادداشتِ من"))
                activity = LeadActivity.objects.filter(lead=item.lead, kind="queue_outcome").get()
                self.assertEqual(activity.data["message_text"], item.rendered_text)
                self.assertIn("درود", activity.data["message_text"], "the EDITED text is what is logged")
                self.assertEqual((activity.data["outcome"], activity.data["note"], activity.data["channel"]), (outcome, "یادداشتِ من", "manual"))
                self.assertEqual((activity.data["campaign_id"], activity.data["item_id"], activity.actor_id), (self.campaign.pk, item.pk, self.staff.pk))
                self.assertIn("یادداشتِ من", activity.summary)

    def test_a_manual_send_moves_a_fresh_lead_to_contacted_but_not_a_further_one(self):
        fresh, advanced, no_form = self.add("a.ir"), self.add("b.ir"), self.add("c.ir")  # all added first: the campaign stays open
        Lead.objects.filter(pk=advanced.lead_id).update(status="interested")
        manual.record_outcome(fresh, "sent", "", self.staff)
        manual.record_outcome(advanced, "sent", "", self.staff)
        self.assertEqual(Lead.objects.get(pk=fresh.lead_id).status, "contacted")
        self.assertEqual(Lead.objects.get(pk=advanced.lead_id).status, "interested")
        self.assertTrue(LeadActivity.objects.filter(lead=fresh.lead, kind="status_changed").exists())
        manual.record_outcome(no_form, "no_form", "", self.staff)
        self.assertEqual(Lead.objects.get(pk=no_form.lead_id).status, "new")

    def test_a_suppressed_lead_can_never_be_recorded_as_sent(self):
        item = self.add("a.ir")
        suppression.suppress_lead(item.lead, "opt_out", "", self.staff)
        with self.assertRaises(ValidationFailed) as ctx:
            manual.record_outcome(item, "sent", "", self.staff)
        self.assertEqual(ctx.exception.errors[0]["code"], "suppressed")
        self.assertEqual(OutreachItem.objects.get(pk=item.pk).status, "pending")
        manual.record_outcome(item, "skipped", "", self.staff)  # but skipping is fine
        self.assertEqual(OutreachItem.objects.get(pk=item.pk).status, "skipped")

    def test_the_same_lead_and_template_at_most_once_unless_forced(self):
        first = self.add("a.ir")
        manual.record_outcome(first, "sent", "", self.staff)
        second_campaign = make_campaign(self.campaign.template, mode="manual", name="second")
        self.assertEqual(campaigns.add_leads(second_campaign, [first.lead_id]).skipped[0]["reason"], "already_contacted")
        forced = campaigns.add_leads(second_campaign, [first.lead_id], force=True).added[0]
        forced = OutreachItem.objects.select_related("lead", "campaign", "campaign__template").get(pk=forced.pk)
        self.assertTrue(forced.forced)
        manual.record_outcome(forced, "sent", "", self.staff)  # a deliberate second message is allowed
        self.assertEqual(OutreachItem.objects.get(pk=forced.pk).status, "manual_sent")
        # but an unforced item cannot be marked sent when the lead already got this template elsewhere
        third_campaign = make_campaign(self.campaign.template, mode="manual", name="third")
        lead = make_lead("z.ir")
        item = OutreachItem.objects.select_related("lead", "campaign", "campaign__template").get(pk=campaigns.add_leads(third_campaign, [lead.pk]).added[0].pk)
        OutreachItem.objects.create(campaign=second_campaign, lead=lead, status=ItemStatus.SENT)
        with self.assertRaises(ValidationFailed) as ctx:
            manual.record_outcome(item, "sent", "", self.staff)
        self.assertEqual(ctx.exception.errors[0]["code"], "already_contacted")

    def test_an_outcome_can_be_recorded_once(self):
        item, _other = self.add("a.ir"), self.add("b.ir")  # a second open item keeps the campaign open
        manual.record_outcome(item, "no_form", "", self.staff)
        with self.assertRaises(ValidationFailed) as ctx:
            manual.record_outcome(item, "sent", "", self.staff)
        self.assertEqual(ctx.exception.errors[0]["code"], "not_open")

    def test_validation(self):
        item = self.add("a.ir")
        for outcome, note in [("explode", ""), ("sent", "x" * 501)]:
            with self.subTest(outcome=outcome), self.assertRaises(ValidationFailed):
                manual.record_outcome(item, outcome, note, self.staff)
        Campaign.objects.filter(pk=self.campaign.pk).update(status="cancelled")
        item = OutreachItem.objects.select_related("lead", "campaign", "campaign__template").get(pk=item.pk)
        with self.assertRaises(ValidationFailed):
            manual.record_outcome(item, "skipped", "", self.staff)

    def test_working_the_queue_starts_the_campaign_and_finishing_it_completes_it(self):
        a, b = self.add("a.ir"), self.add("b.ir")
        self.assertEqual(Campaign.objects.get(pk=self.campaign.pk).status, "draft")
        manual.record_outcome(a, "sent", "", self.staff)
        self.assertEqual(Campaign.objects.get(pk=self.campaign.pk).status, "active")
        manual.record_outcome(b, "no_form", "", self.staff)
        done = Campaign.objects.get(pk=self.campaign.pk)
        self.assertEqual(done.status, "completed")
        self.assertIsNotNone(done.finished_at)

    def test_the_skipped_leads_of_an_automatic_campaign_use_the_same_queue(self):
        auto = make_campaign(self.campaign.template, name="auto")
        lead = make_lead("auto.ir")
        item = campaigns.add_leads(auto, [lead.pk]).added[0]
        OutreachItem.objects.filter(pk=item.pk).update(status=ItemStatus.NEEDS_MANUAL, skip_reason="captcha", skip_reason_text="کپچا دارد")
        item = OutreachItem.objects.select_related("lead", "campaign", "campaign__template").get(pk=item.pk)
        manual.record_outcome(item, "sent", "از راهِ فرمِ سایت و با حل کپچا دستی فرستادم", self.staff)
        self.assertEqual(OutreachItem.objects.get(pk=item.pk).status, "manual_sent")

    def test_an_approved_item_must_be_revoked_first(self):
        item = self.add("a.ir")
        OutreachItem.objects.filter(pk=item.pk).update(status=ItemStatus.APPROVED)
        item.refresh_from_db()
        with self.assertRaises(ValidationFailed):
            manual.record_outcome(item, "sent", "", self.staff)
