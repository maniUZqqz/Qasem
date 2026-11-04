"""Preparing items (the dry run) and approving them. The REAL form analyser runs against local fixture pages served by a fake web."""
from unittest import mock

import httpx
from django.test import TestCase

from apps.growth_engine.compliance.models import AuditEntry, GrowthSettings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.testing import NoNetworkMixin, make_staff
from apps.growth_engine.leads.services.editing import ValidationFailed
from apps.growth_engine.outreach.models import ApprovalRecord, Campaign, ItemStatus, OutreachItem
from apps.growth_engine.outreach.services import approval, campaigns, fingerprint, guard, items, preparing
from apps.growth_engine.outreach.services.form_analysis import FormPlan

from .helpers import IDENTITY, Site, approved_item, configure, make_campaign, make_lead, page, ready_item, use_site


def prepare(campaign, site, user=None):
    job = preparing.create_prepare_job(campaign, user)
    with use_site(site):
        status = preparing.run_prepare(job.pk)
    job.refresh_from_db()
    return job, status


def add(campaign, host, **kw):
    lead = make_lead(host, **kw)
    return campaigns.add_leads(campaign, [lead.pk]).added[0]


class PrepareTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.campaign = make_campaign()

    def test_a_good_form_becomes_ready_with_the_exact_dry_run(self):
        site = Site().shop("shop-a.ir")
        item = add(self.campaign, "shop-a.ir")
        job, status = prepare(self.campaign, site)
        item.refresh_from_db()
        self.assertEqual((status, item.status, item.skip_reason), ("completed", "ready", ""))
        plan = FormPlan.from_dict(item.plan)
        self.assertTrue(plan.eligible)
        self.assertEqual((plan.action_url, plan.method), ("https://shop-a.ir/send-message", "POST"))
        pairs = dict(plan.payload_pairs())
        self.assertEqual((pairs["fullname"], pairs["email"], pairs["subject"], pairs["_token"]), ("علی رضایی", "ali@upmarket.ir", "معرفی آپ‌مارکت", "TOKEN-1"))
        self.assertEqual(pairs["message"], item.rendered_text)
        self.assertTrue(pairs["message"].endswith("«لغو»."))
        self.assertIsNotNone(item.plan_checked_at)
        self.assertEqual(item.fingerprint, fingerprint.compute(item))
        self.assertEqual(site.posts(), [], "preparing never posts anything")
        self.assertEqual(set(r.method for r in site.requests), {"GET"})
        self.assertEqual((job.status, job.processed_items), ("completed", 1))

    def test_each_kind_of_problem_makes_the_item_a_manual_one_with_a_reason(self):
        cases = {}

        def case(host, expected, build):
            site = Site()
            site.robots(host)
            build(site, host)
            cases[host] = (site, expected)

        def form(fixture):
            return lambda site, host: site.form_page(host, fixture=fixture)

        case("cap.ir", "captcha", form("contact_captcha.html"))
        case("login.ir", "login_required", form("contact_login.html"))
        case("noform.ir", "no_form_found", form("neutral.html"))
        case("gone.ir", "fetch_failed", lambda site, host: None)  # the contact page 404s
        case("slow.ir", "fetch_failed", lambda site, host: site.add("GET", host, "/contact", error=httpx.ReadTimeout("slow")))
        case("blocked.ir", "robots_blocked", lambda site, host: (site.robots(host, "User-agent: *\nDisallow: /contact\n"), site.form_page(host)))
        case("noaction.ir", "robots_blocked", lambda site, host: (site.robots(host, "User-agent: *\nDisallow: /send-message\n"), site.form_page(host), site.accept_posts(host)))
        case("rob500.ir", "robots_unavailable", lambda site, host: (site.robots(host, "x", status=500), site.form_page(host)))
        case(
            "cf.ir", "challenge_page",
            lambda site, host: site.add(
                "GET", host, "/contact", "<html><head><title>Just a moment...</title></head><body>Checking your browser <span class='cf-chl'>__cf_chl_opt</span></body></html>",
                status=403, headers={"cf-mitigated": "challenge"},
            ),
        )
        for host, (site, expected) in cases.items():
            with self.subTest(host=host):
                campaign = make_campaign(name=f"c-{host}")
                item = add(campaign, host)
                job, status = prepare(campaign, site)
                item.refresh_from_db()
                self.assertEqual((item.status, item.skip_reason), ("needs_manual", expected), item.skip_reason_text)
                self.assertTrue(item.skip_reason_text)
                self.assertIn("دستی", item.skip_reason_text if expected != "fetch_failed" else "دستی")
                self.assertEqual(site.posts(), [])
                self.assertEqual((job.status, job.items_blocked), ("completed", 1))

    def test_a_suppressed_lead_is_skipped_at_prepare(self):
        site = Site().shop("shop-a.ir")
        item = add(self.campaign, "shop-a.ir")
        suppression.suppress_lead(item.lead, "opt_out", "", None)
        prepare(self.campaign, site)
        item.refresh_from_db()
        self.assertEqual((item.status, item.skip_reason), ("skipped", "suppressed"))
        self.assertEqual(site.requests, [], "a do-not-contact lead's site is not even visited")

    def test_the_message_follows_identity_changes_unless_the_text_was_edited(self):
        site = Site().shop("a.ir").shop("b.ir")
        a, b = add(self.campaign, "a.ir"), add(self.campaign, "b.ir")
        items.edit_item(b, text=b.rendered_text + "\nپی‌نوشتِ دستی", actor=None)
        configure(sender_company="شرکتِ تازه")
        prepare(self.campaign, site)
        a.refresh_from_db(), b.refresh_from_db()
        self.assertIn("شرکتِ تازه", a.rendered_text)
        self.assertNotIn("شرکتِ تازه", b.rendered_text)
        self.assertIn("پی‌نوشتِ دستی", b.rendered_text)

    def test_retryable_reasons_are_prepared_again_but_hard_ones_are_not(self):
        site = Site().robots("gone.ir").robots("cap.ir").form_page("cap.ir", fixture="contact_captcha.html")
        gone, cap = add(self.campaign, "gone.ir"), add(self.campaign, "cap.ir")
        prepare(self.campaign, site)
        self.assertEqual(sorted(OutreachItem.objects.values_list("skip_reason", flat=True)), ["captcha", "fetch_failed"])
        site.form_page("gone.ir")  # the site comes back
        site.accept_posts("gone.ir")
        job, _ = prepare(self.campaign, site)
        self.assertEqual(job.total_items, 1)
        gone.refresh_from_db(), cap.refresh_from_db()
        self.assertEqual((gone.status, cap.status, cap.skip_reason), ("ready", "needs_manual", "captcha"))
        with self.assertRaises(campaigns.CampaignError) as ctx:
            preparing.create_prepare_job(make_campaign(name="empty"))
        self.assertEqual(ctx.exception.code, "nothing_to_prepare")

    def test_one_broken_item_does_not_stop_the_job(self):
        site = Site().shop("a.ir").shop("b.ir")
        a, b = add(self.campaign, "a.ir"), add(self.campaign, "b.ir")
        real = preparing.analyse
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("boom")
            return real(*args, **kwargs)

        with mock.patch.object(preparing, "analyse", flaky):
            job, status = prepare(self.campaign, site)
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((status, a.status, a.skip_reason, b.status), ("completed", "needs_manual", "fetch_failed", "ready"))
        self.assertEqual(job.items_failed, 1)

    def test_cancel_before_it_starts_and_manual_campaigns(self):
        add(self.campaign, "a.ir")
        job = preparing.create_prepare_job(self.campaign)
        from apps.growth_engine.outreach.services import sending

        sending.request_cancel(job)
        self.assertEqual(preparing.run_prepare(job.pk), "cancelled")
        with self.assertRaises(campaigns.CampaignError) as ctx:
            preparing.create_prepare_job(make_campaign(mode="manual", name="m"))
        self.assertEqual(ctx.exception.code, "manual_campaign")

    def test_a_running_prepare_job_is_not_duplicated(self):
        add(self.campaign, "a.ir")
        job = preparing.create_prepare_job(self.campaign)
        self.assertEqual(preparing.create_prepare_job(self.campaign).pk, job.pk)

    def test_resume_continues_after_the_cursor(self):
        site = Site().shop("a.ir").shop("b.ir").shop("c.ir")
        for host in ("a.ir", "b.ir", "c.ir"):
            add(self.campaign, host)
        job = preparing.create_prepare_job(self.campaign)
        real = preparing.prepare_item
        calls = {"n": 0}

        class Killed(BaseException):
            pass

        def die_on_second(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise Killed()
            return real(*args, **kwargs)

        with use_site(site), mock.patch.object(preparing, "prepare_item", die_on_second), self.assertRaises(Killed):
            preparing.run_prepare(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.cursor, job.processed_items), ("running", 1, 1))
        with use_site(site):
            self.assertEqual(preparing.run_prepare(job.pk), "completed")
        self.assertEqual(sorted(OutreachItem.objects.values_list("status", flat=True)), ["ready"] * 3)
        self.assertEqual(site.paths("GET").count("/contact"), 3, "the first lead was not read twice")


class ApprovalTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.campaign = make_campaign()
        self.site = Site().shop("shop-a.ir")

    def test_approving_creates_an_immutable_record_bound_to_the_exact_form(self):
        item = ready_item(self.site, self.campaign)
        result = approval.approve_items(self.campaign, item_ids=[item.pk], actor=self.staff)
        self.assertEqual(result, {"approved": 1, "refused": []})
        item.refresh_from_db()
        record = item.approved_record
        self.assertEqual((item.status, record.item_id, record.approved_by_id), ("approved", item.pk, self.staff.pk))
        self.assertEqual((record.fingerprint, record.target_url, record.action_url), (item.fingerprint, "https://shop-a.ir/contact", "https://shop-a.ir/send-message"))
        self.assertEqual(record.message_sha256, fingerprint.message_sha256(item.rendered_text))
        self.assertTrue(AuditEntry.objects.filter(kind="approval", data__item_ids=[item.pk]).exists())
        record.fingerprint = "tampered"
        with self.assertRaises(ValueError):
            record.save()

    def test_only_ready_items_can_be_approved(self):
        pending = add(self.campaign, "p.ir")
        manual = add(self.campaign, "m.ir")
        OutreachItem.objects.filter(pk=manual.pk).update(status=ItemStatus.NEEDS_MANUAL)
        result = approval.approve_items(self.campaign, item_ids=[pending.pk, manual.pk, 999999], actor=self.staff)
        self.assertEqual(result["approved"], 0)
        self.assertEqual(sorted((r["item_id"], r["code"]) for r in result["refused"]), sorted([(pending.pk, "not_ready"), (manual.pk, "not_ready"), (999999, "not_found")]))

    def test_all_ready(self):
        a = ready_item(self.site, self.campaign, "shop-a.ir")
        self.site.shop("shop-b.ir")
        b = ready_item(self.site, self.campaign, "shop-b.ir")
        manual = add(self.campaign, "m.ir")
        OutreachItem.objects.filter(pk=manual.pk).update(status=ItemStatus.NEEDS_MANUAL)
        self.assertEqual(approval.approve_items(self.campaign, all_ready=True, actor=self.staff)["approved"], 2)
        self.assertEqual(sorted(OutreachItem.objects.filter(status="approved").values_list("pk", flat=True)), sorted([a.pk, b.pk]))

    def test_the_guard_refuses_what_must_not_be_approved(self):
        item = ready_item(self.site, self.campaign)
        cases = [
            ("sending_disabled", lambda: configure(sending_enabled=False)),
            ("identity_incomplete", lambda: configure(sender_company="")),
            ("emergency_stop", lambda: configure(emergency_stop=True)),
        ]
        for code, setup in cases:
            with self.subTest(code=code):
                setup()
                result = approval.approve_items(self.campaign, item_ids=[item.pk], actor=self.staff)
                self.assertEqual((result["approved"], result["refused"][0]["code"]), (0, code))
                self.assertTrue(result["refused"][0]["text"])
                configure()
        suppression.suppress_lead(item.lead, "opt_out", "", None)
        self.assertEqual(approval.approve_items(self.campaign, item_ids=[item.pk])["refused"][0]["code"], "suppressed")
        self.assertEqual(OutreachItem.objects.get(pk=item.pk).status, "ready")
        self.assertEqual(ApprovalRecord.objects.count(), 0)

    def test_duplicates_and_closed_campaigns_cannot_be_approved(self):
        item = ready_item(self.site, self.campaign)
        other = make_campaign(self.campaign.template, name="x")
        OutreachItem.objects.create(campaign=other, lead=item.lead, status=ItemStatus.FAILED, domain="")
        self.assertEqual(approval.approve_items(self.campaign, item_ids=[item.pk])["refused"][0]["code"], "already_contacted")
        OutreachItem.objects.filter(campaign=other).delete()
        Campaign.objects.filter(pk=self.campaign.pk).update(status="cancelled")
        self.assertEqual(approval.approve_items(Campaign.objects.get(pk=self.campaign.pk), item_ids=[item.pk])["refused"][0]["code"], "campaign_closed")

    def test_an_item_whose_form_is_not_eligible_is_refused_even_if_forced_to_ready(self):
        item = add(self.campaign, "cap.ir")
        site = Site().robots("cap.ir").form_page("cap.ir", fixture="contact_captcha.html")
        prepare(self.campaign, site)
        OutreachItem.objects.filter(pk=item.pk).update(status=ItemStatus.READY)  # someone tampers with the status
        refused = approval.approve_items(self.campaign, item_ids=[item.pk])["refused"][0]
        self.assertEqual(refused["code"], "form_not_eligible")
        self.assertIn("کپچا", refused["text"])

    def test_a_manual_campaign_never_approves(self):
        manual = make_campaign(mode="manual", name="m")
        item = add(manual, "mm.ir")
        OutreachItem.objects.filter(pk=item.pk).update(status=ItemStatus.READY, plan=FormPlan(verdict="eligible", action_url="https://mm.ir/x").to_dict())
        self.assertEqual(approval.approve_items(manual, item_ids=[item.pk])["refused"][0]["code"], "manual_campaign")

    def test_revoke_returns_to_ready(self):
        item = approved_item(self.site, self.campaign, staff=self.staff)
        self.assertEqual(approval.revoke_items(self.campaign, [item.pk], self.staff), 1)
        item.refresh_from_db()
        self.assertEqual((item.status, item.approved_record), ("ready", None))
        self.assertEqual(ApprovalRecord.objects.filter(item=item).count(), 1, "the history stays")


class InvalidationTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.campaign = make_campaign()
        self.site = Site().shop("shop-a.ir")
        self.item = approved_item(self.site, self.campaign, staff=self.staff)

    def assertVoid(self, item):
        Campaign.objects.filter(pk=item.campaign_id).update(status="active")
        item = OutreachItem.objects.select_related("lead", "campaign", "campaign__template", "approved_record").get(pk=item.pk)
        self.assertEqual((item.status, item.approved_record), ("ready", None))
        self.assertEqual(guard.check_item(item, phase=guard.SEND).code, "no_approval")
        self.assertTrue(AuditEntry.objects.filter(kind="approval", summary__contains="باطل").exists())

    def test_editing_the_message_voids_the_approval(self):
        items.edit_item(self.item, text=self.item.rendered_text.replace("سلام", "درود"), actor=self.staff)
        self.assertVoid(self.item)
        self.assertEqual(ApprovalRecord.objects.filter(item=self.item).count(), 1)
        from apps.growth_engine.outreach.serializers import item_json

        self.assertIsNone(item_json(OutreachItem.objects.select_related("lead", "approved_record").get(pk=self.item.pk))["approval"])

    def test_editing_the_subject_voids_it(self):
        items.edit_item(self.item, subject="موضوع دیگر", actor=self.staff)
        self.assertVoid(self.item)

    def test_a_changed_target_voids_it(self):
        self.item.target_url = "https://shop-a.ir/another-contact-page"
        self.item.save()
        self.assertTrue(items.refresh_fingerprint(self.item, self.staff, "آدرس عوض شد"))
        self.assertVoid(self.item)

    def test_rerender_after_a_settings_change_voids_it(self):
        configure(opt_out_line="برای لغو، همین پیام را پاسخ دهید «لغو».")
        items.rerender_item(self.item, self.staff)
        self.assertVoid(self.item)
        self.item.refresh_from_db()
        self.assertTrue(self.item.rendered_text.endswith("«لغو»."))
        self.assertIn("برای لغو", self.item.rendered_text)

    def test_the_opt_out_line_cannot_be_edited_away(self):
        with self.assertRaises(ValidationFailed) as ctx:
            items.edit_item(self.item, text="فقط یک جملهٔ کوتاه", actor=self.staff)
        self.assertEqual(ctx.exception.errors[0]["code"], "opt_out_missing")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "approved")  # nothing changed

    def test_an_edit_that_changes_nothing_keeps_the_approval(self):
        items.edit_item(self.item, text=self.item.rendered_text, actor=self.staff)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "approved")

    def test_other_validation_and_final_items(self):
        for bad in ("", "x" * 6000):
            with self.assertRaises(ValidationFailed):
                items.edit_item(self.item, text=bad)
        OutreachItem.objects.filter(pk=self.item.pk).update(status=ItemStatus.SENT)
        self.item.refresh_from_db()
        with self.assertRaises(ValidationFailed):
            items.edit_item(self.item, text=self.item.rendered_text + " x")

    def test_the_fingerprint_ignores_hidden_values_but_not_the_form_shape(self):
        before = self.item.fingerprint
        self.site.token = "TOKEN-9"
        with use_site(self.site):
            analysis = preparing.analyse(self.item, preparing.make_fetcher(), GrowthSettings.load())
        self.assertEqual(fingerprint.compute(self.item, analysis.plan), before)
        self.site.form_page("shop-a.ir", fixture="contact_extra_field.html")
        with use_site(self.site):
            changed = preparing.analyse(self.item, preparing.make_fetcher(), GrowthSettings.load())
        self.assertNotEqual(fingerprint.compute(self.item, changed.plan), before)
        self.assertIn(IDENTITY["sender_name"], self.item.rendered_text)
