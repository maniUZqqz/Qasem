"""The outreach API: permissions on every endpoint, then the flows the panel uses."""
from unittest import mock

from django.contrib import admin
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.growth_engine.analytics import registry
from apps.growth_engine.compliance.services import limits
from apps.growth_engine.core.testing import NoNetworkMixin, client_for, make_plain_user, make_staff
from apps.growth_engine.outreach import models
from apps.growth_engine.outreach.models import Campaign, OutreachItem, OutreachJob
from apps.growth_engine.outreach.services import approval, campaigns, sending
from apps.growth_engine.outreach.services.limits import attempts_on

from .helpers import FakeSleep, MidRng, Site, approved_item, configure, make_campaign, make_lead, make_template, ready_item, use_site

API = "/api/v1/growth/outreach"
G = "/api/v1/growth"


class PermissionTests(NoNetworkMixin, TestCase):
    """Every endpoint is for staff only: anonymous 401, ordinary user 403."""

    def setUp(self):
        super().setUp()
        self.template = make_template()
        self.campaign = make_campaign(self.template)
        self.item = OutreachItem.objects.create(campaign=self.campaign, lead=make_lead("a.ir"), domain="a.ir")
        self.job = OutreachJob.objects.create(campaign=self.campaign, kind="send")
        c, i = self.campaign.pk, self.item.pk
        self.endpoints = [
            ("get", "/placeholders/"), ("get", "/templates/"), ("post", "/templates/"), ("post", "/templates/preview/"),
            ("get", f"/templates/{self.template.pk}/"), ("patch", f"/templates/{self.template.pk}/"), ("delete", f"/templates/{self.template.pk}/"),
            ("get", "/campaigns/"), ("post", "/campaigns/"), ("get", f"/campaigns/{c}/"), ("patch", f"/campaigns/{c}/"),
            ("post", f"/campaigns/{c}/add-leads/"), ("post", f"/campaigns/{c}/remove-items/"), ("post", f"/campaigns/{c}/prepare/"),
            ("post", f"/campaigns/{c}/approve/"), ("post", f"/campaigns/{c}/revoke/"), ("post", f"/campaigns/{c}/start/"),
            ("post", f"/campaigns/{c}/pause/"), ("post", f"/campaigns/{c}/cancel/"), ("get", f"/campaigns/{c}/status/"),
            ("get", f"/campaigns/{c}/items/"), ("get", f"/campaigns/{c}/items/{i}/"), ("patch", f"/campaigns/{c}/items/{i}/"),
            ("post", f"/campaigns/{c}/items/{i}/rerender/"), ("post", f"/campaigns/{c}/items/{i}/outcome/"),
            ("get", f"/jobs/{self.job.pk}/"), ("post", f"/jobs/{self.job.pk}/cancel/"), ("post", f"/jobs/{self.job.pk}/resume/"),
        ]

    def test_anonymous_is_rejected_everywhere(self):
        anonymous = client_for()
        for method, path in self.endpoints:
            with self.subTest(path=path):
                self.assertIn(getattr(anonymous, method)(API + path).status_code, (401, 403))
        self.assertEqual((Campaign.objects.count(), OutreachItem.objects.count(), models.MessageTemplate.objects.count()), (1, 1, 1))

    def test_ordinary_users_are_forbidden_everywhere(self):
        plain = client_for(make_plain_user())
        for method, path in self.endpoints:
            with self.subTest(path=path):
                self.assertEqual(getattr(plain, method)(API + path).status_code, 403)
        self.assertEqual((Campaign.objects.get().status, OutreachItem.objects.get().status), ("draft", "pending"))

    def test_staff_gets_through(self):
        staff = client_for(make_staff())
        for method, path in self.endpoints:
            if method == "get":
                with self.subTest(path=path):
                    self.assertEqual(staff.get(API + path).status_code, 200)


class TemplateApiTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.client = client_for(make_staff())

    def test_placeholders(self):
        keys = [p["key"] for p in self.client.get(f"{API}/placeholders/").json()]
        self.assertEqual(keys, ["business_name", "city", "country", "category", "website", "domain", "instagram"])

    def test_crud(self):
        created = self.client.post(f"{API}/templates/", {"name": "اول", "body": "سلام {business_name}", "subject": "س", "language": "fa"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        data = created.json()
        self.assertEqual((data["name"], data["is_active"], data["used_by"], data["campaigns_count"], data["generator"]), ("اول", True, 0, 0, "placeholder"))
        tid = data["id"]
        patched = self.client.patch(f"{API}/templates/{tid}/", {"is_active": False, "body": "درود {city|شهر شما}"}, format="json").json()
        self.assertEqual((patched["is_active"], patched["body"]), (False, "درود {city|شهر شما}"))
        listing = self.client.get(f"{API}/templates/").json()
        self.assertEqual((listing["count"], listing["results"][0]["id"]), (1, tid))
        self.assertEqual(self.client.get(f"{API}/templates/?active=1").json()["count"], 0)
        self.assertEqual(self.client.delete(f"{API}/templates/{tid}/").status_code, 204)

    def test_validation_errors_are_400_with_field_and_text(self):
        bad = self.client.post(f"{API}/templates/", {"name": "x", "body": "سلام {nope}"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["errors"][0]["code"], "unknown_placeholder")
        self.assertEqual(self.client.post(f"{API}/templates/", {"name": "", "body": ""}, format="json").status_code, 400)

    def test_a_template_in_use_cannot_be_deleted(self):
        template = make_template()
        make_campaign(template)
        response = self.client.delete(f"{API}/templates/{template.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "in_use")
        self.assertEqual(self.client.get(f"{API}/templates/{template.pk}/").json()["used_by"], 1)

    def test_preview(self):
        lead = make_lead("a.ir", name="گل‌سرخ", city="")
        response = self.client.post(f"{API}/templates/preview/", {"body": "سلام {business_name} از {city}", "subject": "س", "lead_id": lead.pk}, format="json").json()
        self.assertTrue(response["text"].startswith("سلام گل‌سرخ از"))
        self.assertTrue(response["text"].endswith("«لغو»."))
        self.assertTrue(any("شهر" in w for w in response["warnings"]))
        self.assertEqual(self.client.post(f"{API}/templates/preview/", {"body": "{zz}"}, format="json").json()["unknown_placeholders"], ["zz"])
        self.assertEqual(self.client.post(f"{API}/templates/preview/", {"body": "x", "lead_id": 99999}, format="json").status_code, 404)


class CampaignApiTests(NoNetworkMixin, TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        self.template = make_template()
        self.site = Site()

    def create(self, **extra):
        return self.client.post(f"{API}/campaigns/", {"name": "کمپین", "template_id": self.template.pk, "mode": "auto", **extra}, format="json")

    def test_create_with_leads_reports_what_was_added_and_skipped(self):
        good, no_form = make_lead("a.ir"), make_lead("b.ir", form=False)
        response = self.create(lead_ids=[good.pk, no_form.pk, 99999])
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["status"], body["mode"], body["template"], body["created_by_name"]), ("draft", "auto", {"id": self.template.pk, "name": "معرفی"}, self.staff.username))
        self.assertEqual(body["add_result"]["added"], 1)
        self.assertEqual({s["lead_id"]: s["reason"] for s in body["add_result"]["skipped"]}, {no_form.pk: "no_target_url", 99999: "lead_missing"})
        self.assertTrue(all(s["reason_text"] and "lead_name" in s for s in body["add_result"]["skipped"]))
        self.assertEqual(body["counts"], {"pending": 1})

    def test_create_validation(self):
        self.assertEqual(self.client.post(f"{API}/campaigns/", {"name": "x", "template_id": 99999}, format="json").status_code, 400)
        self.assertEqual(self.create(name="").status_code, 400)
        self.template.is_active = False
        self.template.save()
        self.assertEqual(self.create().json()["errors"][0]["code"], "template_inactive")
        self.assertEqual(self.client.post(f"{API}/campaigns/", {"name": "x", "template_id": self.template.pk, "mode": "robot"}, format="json").status_code, 400)

    def test_list_detail_and_rename(self):
        first = self.create().json()
        make_campaign(self.template, name="دوم")
        listing = self.client.get(f"{API}/campaigns/").json()
        self.assertEqual(listing["count"], 2)
        self.assertEqual(self.client.get(f"{API}/campaigns/?status=active").json()["count"], 0)
        detail = self.client.get(f"{API}/campaigns/{first['id']}/").json()
        self.assertEqual(detail["name"], "کمپین")
        renamed = self.client.patch(f"{API}/campaigns/{first['id']}/", {"name": " نامِ تازه "}, format="json").json()
        self.assertEqual(renamed["name"], "نامِ تازه")
        self.assertEqual(self.client.patch(f"{API}/campaigns/{first['id']}/", {"name": " "}, format="json").status_code, 400)
        self.assertEqual(self.client.get(f"{API}/campaigns/99999/").status_code, 404)

    def test_add_leads_and_remove_items(self):
        campaign = self.create().json()
        lead = make_lead("a.ir")
        added = self.client.post(f"{API}/campaigns/{campaign['id']}/add-leads/", {"lead_ids": [lead.pk]}, format="json").json()
        self.assertEqual(added["added"], 1)
        again = self.client.post(f"{API}/campaigns/{campaign['id']}/add-leads/", {"lead_ids": [lead.pk]}, format="json").json()
        self.assertEqual((again["added"], again["skipped"][0]["reason"]), (0, "already_in_campaign"))
        self.assertEqual(self.client.post(f"{API}/campaigns/{campaign['id']}/add-leads/", {"lead_ids": []}, format="json").status_code, 400)
        item = OutreachItem.objects.get()
        removed = self.client.post(f"{API}/campaigns/{campaign['id']}/remove-items/", {"item_ids": [item.pk]}, format="json").json()
        self.assertEqual(removed["removed"], 1)

    def test_the_full_flow_prepare_approve_start_status_and_jobs(self):
        self.site.shop("a.ir").shop("b.ir")
        a, b = make_lead("a.ir"), make_lead("b.ir")
        campaign = self.create(lead_ids=[a.pk, b.pk]).json()
        cid = campaign["id"]
        with use_site(self.site), self.captureOnCommitCallbacks(execute=True):  # Celery runs eagerly in tests
            prepared = self.client.post(f"{API}/campaigns/{cid}/prepare/")
        self.assertEqual(prepared.status_code, 202, prepared.content)
        self.assertEqual(prepared.json()["kind"], "prepare")
        status = self.client.get(f"{API}/campaigns/{cid}/status/").json()
        self.assertEqual(status["counts"], {"ready": 2})
        self.assertEqual((status["job"]["kind"], status["job"]["status"], status["job"]["progress"]), ("prepare", "completed", 100))

        items = self.client.get(f"{API}/campaigns/{cid}/items/?status=ready").json()
        self.assertEqual(items["count"], 2)
        item = items["results"][0]
        self.assertEqual((item["status"], item["lead"]["id"], item["target_url"], item["approval"], item["attempt"]), ("ready", a.pk, "https://a.ir/contact", None, None))
        self.assertEqual(item["plan"]["verdict"], "eligible")
        self.assertEqual([f["name"] for f in item["plan"]["fields"]], ["_token", "fullname", "email", "mobile", "subject", "message"])
        self.assertTrue(item["plan"]["fields"][0]["hidden"])

        approved = self.client.post(f"{API}/campaigns/{cid}/approve/", {"item_ids": [item["id"]]}, format="json").json()
        self.assertEqual(approved, {"approved": 1, "refused": []})
        detail = self.client.get(f"{API}/campaigns/{cid}/items/{item['id']}/").json()
        self.assertEqual((detail["status"], detail["approval"]["valid"], detail["approval"]["by"]), ("approved", True, self.staff.username))
        self.assertEqual(self.client.post(f"{API}/campaigns/{cid}/approve/", {"all_ready": True}, format="json").json()["approved"], 1)
        self.assertEqual(self.client.post(f"{API}/campaigns/{cid}/approve/", {}, format="json").status_code, 400)

        nap = FakeSleep()  # the job really waits between two messages; the test must not
        with use_site(self.site), mock.patch.object(sending.time, "sleep", nap), self.captureOnCommitCallbacks(execute=True):
            started = self.client.post(f"{API}/campaigns/{cid}/start/")
        self.assertTrue(60 <= nap.total <= 120, "exactly one wait, between the two messages, inside the configured range")
        self.assertEqual(started.status_code, 202, started.content)
        self.assertEqual((started.json()["status"], started.json()["job"]["kind"]), ("active", "send"))
        self.assertEqual(len(self.site.posts()), 2)
        final = self.client.get(f"{API}/campaigns/{cid}/status/").json()
        self.assertEqual((final["campaign"]["status"], final["counts"]), ("completed", {"sent": 2}))
        self.assertEqual((final["sent_today"], final["daily_cap"], final["cap_remaining"]), (2, 40, 38))
        self.assertEqual((final["settings"]["sending_enabled"], final["settings"]["ready"]["ok"], final["emergency_stop"]), (True, True, False))
        sent = self.client.get(f"{API}/campaigns/{cid}/items/?status=sent").json()["results"][0]
        self.assertEqual((sent["attempt"]["status_code"], sent["attempt"]["success_guess"]), (200, "likely_success"))
        self.assertEqual({p["name"]: p["value"] for p in sent["attempt"]["payload"]}["_token"], "***")
        job = self.client.get(f"{API}/jobs/{started.json()['job']['id']}/").json()
        self.assertEqual((job["status"], job["items_sent"], job["can_resume"]), ("completed", 2, False))

    def test_start_explains_why_it_cannot(self):
        configure(sending_enabled=False)
        campaign = self.create().json()
        response = self.client.post(f"{API}/campaigns/{campaign['id']}/start/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("خاموش", response.json()["detail"])

    def test_approve_reports_what_it_refused(self):
        self.site.shop("a.ir")
        campaign = make_campaign(self.template)
        item = ready_item(self.site, campaign, "a.ir")
        configure(sending_enabled=False)
        response = self.client.post(f"{API}/campaigns/{campaign.pk}/approve/", {"item_ids": [item.pk]}, format="json").json()
        self.assertEqual((response["approved"], response["refused"][0]["code"]), (0, "sending_disabled"))

    def test_pause_cancel_revoke_and_closed_campaign_errors(self):
        self.site.shop("a.ir")
        campaign = make_campaign(self.template)
        item = approved_item(self.site, campaign, "a.ir", staff=self.staff)
        self.assertEqual(self.client.post(f"{API}/campaigns/{campaign.pk}/revoke/", {"item_ids": [item.pk]}, format="json").json(), {"revoked": 1})
        self.assertEqual(self.client.post(f"{API}/campaigns/{campaign.pk}/pause/").status_code, 400)  # not active
        self.assertEqual(self.client.post(f"{API}/campaigns/{campaign.pk}/cancel/").json()["status"], "cancelled")
        self.assertEqual(self.client.post(f"{API}/campaigns/{campaign.pk}/cancel/").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/campaigns/{campaign.pk}/add-leads/", {"lead_ids": [1]}, format="json").status_code, 400)

    def test_item_edit_rerender_and_the_opt_out_rule(self):
        self.site.shop("a.ir")
        campaign = make_campaign(self.template)
        item = approved_item(self.site, campaign, "a.ir", staff=self.staff)
        url = f"{API}/campaigns/{campaign.pk}/items/{item.pk}/"
        text = item.rendered_text.replace("سلام", "درود")
        edited = self.client.patch(url, {"rendered_text": text, "subject": "موضوعِ تازه"}, format="json").json()
        self.assertEqual((edited["status"], edited["approval"], edited["rendered_text"], edited["subject"], edited["text_edited"]), ("ready", None, text, "موضوعِ تازه", True))
        bad = self.client.patch(url, {"rendered_text": "بدونِ جملهٔ لغو"}, format="json")
        self.assertEqual((bad.status_code, bad.json()["errors"][0]["code"]), (400, "opt_out_missing"))
        back = self.client.post(url + "rerender/").json()
        self.assertEqual((back["text_edited"], "درود" in back["rendered_text"]), (False, False))

    def test_manual_outcome_endpoint(self):
        manual = make_campaign(self.template, mode="manual")
        lead = make_lead("m.ir", form=False)
        campaigns.add_leads(manual, [lead.pk])
        item = OutreachItem.objects.get(campaign=manual)
        url = f"{API}/campaigns/{manual.pk}/items/{item.pk}/outcome/"
        done = self.client.post(url, {"outcome": "sent", "note": "دستی"}, format="json").json()
        self.assertEqual((done["status"], done["manual_note"]), ("manual_sent", "دستی"))
        self.assertEqual(self.client.post(url, {"outcome": "sent"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"outcome": "bogus"}, format="json").status_code, 400)

    def test_job_cancel_and_resume_endpoints(self):
        campaign = make_campaign(self.template)
        job = OutreachJob.objects.create(campaign=campaign, kind="send", status="failed", error="x")
        resumed = self.client.post(f"{API}/jobs/{job.pk}/resume/")
        self.assertEqual((resumed.status_code, resumed.json()["status"]), (202, "queued"))
        self.assertEqual(self.client.post(f"{API}/jobs/{job.pk}/resume/").status_code, 400)  # now it is queued, not failed or stalled
        self.assertEqual(self.client.post(f"{API}/jobs/{job.pk}/cancel/").json()["status"], "cancelled")
        self.assertEqual(self.client.get(f"{API}/jobs/99999/").status_code, 404)

    def test_the_items_list_costs_a_fixed_number_of_queries(self):
        campaign = make_campaign(self.template)
        for i in range(3):
            OutreachItem.objects.create(campaign=campaign, lead=make_lead(f"q{i}.ir"), domain=f"q{i}.ir")
        with CaptureQueriesContext(connection) as small:
            self.client.get(f"{API}/campaigns/{campaign.pk}/items/?page_size=100")
        for i in range(3, 30):
            OutreachItem.objects.create(campaign=campaign, lead=make_lead(f"q{i}.ir"), domain=f"q{i}.ir")
        with CaptureQueriesContext(connection) as large:
            response = self.client.get(f"{API}/campaigns/{campaign.pk}/items/?page_size=100")
        self.assertEqual(response.json()["count"], 30)
        self.assertEqual(len(small), len(large))

    def test_item_filters_and_search(self):
        campaign = make_campaign(self.template)
        a = OutreachItem.objects.create(campaign=campaign, lead=make_lead("alpha.ir", name="الفبا"), domain="alpha.ir", status="ready")
        OutreachItem.objects.create(campaign=campaign, lead=make_lead("beta.ir", name="بتا"), domain="beta.ir", status="needs_manual")
        def ids(query):
            return [r["id"] for r in self.client.get(f"{API}/campaigns/{campaign.pk}/items/?{query}").json()["results"]]
        self.assertEqual(ids("status=ready"), [a.pk])
        self.assertEqual(len(ids("status=ready,needs_manual")), 2)
        self.assertEqual(ids("q=alpha"), [a.pk])
        self.assertEqual(ids("q=" + "الفبا"), [a.pk])


class WiringTests(NoNetworkMixin, TestCase):
    def test_the_dashboard_block_and_the_daily_cap_counter_are_registered(self):
        self.assertIn("outreach", registry._PROVIDERS)
        self.assertIn(attempts_on, limits._COUNTERS)
        client = client_for(make_staff())
        block = client.get(f"{G}/dashboard/").json()["extra"]["outreach"]
        self.assertEqual(block, {"sent_today": 0, "daily_cap": 40, "campaigns_active": 0, "items_ready": 0, "items_needs_manual": 0, "sent_total": 0})

    def test_dashboard_numbers_come_from_the_database(self):
        campaign = make_campaign()
        campaign.status = "active"
        campaign.save()
        OutreachItem.objects.create(campaign=campaign, lead=make_lead("a.ir"), domain="a.ir", status="ready")
        OutreachItem.objects.create(campaign=campaign, lead=make_lead("b.ir"), domain="b.ir", status="needs_manual")
        sent = OutreachItem.objects.create(campaign=campaign, lead=make_lead("c.ir"), domain="c.ir", status="sent")
        OutreachItem.objects.create(campaign=campaign, lead=make_lead("d.ir"), domain="d.ir", status="manual_sent")
        models.SendAttempt.objects.create(item=sent, url="u")
        block = client_for(make_staff()).get(f"{G}/dashboard/").json()["extra"]["outreach"]
        self.assertEqual(block, {"sent_today": 1, "daily_cap": 40, "campaigns_active": 1, "items_ready": 1, "items_needs_manual": 1, "sent_total": 2})

    def test_every_model_is_in_the_admin_and_the_records_are_read_only(self):
        for model in (models.MessageTemplate, models.Campaign, models.OutreachItem, models.ApprovalRecord, models.SendAttempt, models.OutreachJob):
            self.assertIn(model, admin.site._registry)
        staff = make_staff("super", is_superuser=True)
        request = type("R", (), {"user": staff})()
        for model in (models.Campaign, models.OutreachItem, models.ApprovalRecord, models.SendAttempt):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))

    def test_guard_texts_cover_every_code(self):
        from apps.growth_engine.outreach.services import guard

        codes = [v for k, v in vars(guard).items() if k.isupper() and isinstance(v, str) and k not in ("APPROVE", "SEND", "TEXTS")]
        self.assertTrue(set(codes) <= set(guard.TEXTS), set(codes) - set(guard.TEXTS))
        self.assertTrue(all(guard.TEXTS[c] for c in guard.TEXTS))
