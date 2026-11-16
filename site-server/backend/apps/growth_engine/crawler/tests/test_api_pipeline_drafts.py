"""The API (staff only), the results list / map / CSV, the pipeline and reminders, and the outreach drafts (approval gates, opt-out, nothing is sent)."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.compliance.services import suppression
from apps.growth_engine.core.testing import client_for, make_plain_user, make_staff
from apps.growth_engine.leads.models import Lead, LeadActivity
from apps.growth_engine.outreach.models import Campaign, ItemStatus, OutreachItem, SendAttempt

from ..engine import runner
from ..models import CrawlFinding, LeadReminder, OutreachDraft
from ..services import drafts as draft_service
from ..services import missions, pipeline, results
from .helpers import Base, make_mission


class Fixture(Base):
    """A finished run with three leads, an API client and a mission with a pitch."""

    def setUp(self):
        super().setUp()
        self.staff = make_staff()
        self.client = client_for(self.staff)
        self.web = self.web_with_gyms()
        self.mission = make_mission()
        run = missions.start_run(self.mission, None, dispatch=False)
        runner.run_crawl(run.pk, web_factory=self.web.factory)
        self.run = run
        self.arman = Lead.objects.get(website__icontains="arman-gym.ir")
        self.sepehr = Lead.objects.get(business_name="فیتنس سپهر")
        s = GrowthSettings.load()
        s.sender_name, s.sender_company, s.sender_phone, s.sender_email = "علی", "تیم چغر", "09120000000", "hi@chagher.example"
        s.opt_out_line = "برای لغو، «لغو» را بفرستید."
        s.save()


class PermissionTests(Fixture, TestCase):
    def test_staff_only(self):
        anon = client_for(None)
        self.assertEqual(anon.get("/api/v1/growth/finder/meta/").status_code, 401)
        plain = client_for(make_plain_user())
        self.assertEqual(plain.get("/api/v1/growth/finder/results/").status_code, 403)
        self.assertEqual(plain.post("/api/v1/growth/finder/missions/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/growth/finder/meta/").status_code, 200)


class MetaAndMissionApiTests(Fixture, TestCase):
    def test_meta_lists_types_presets_sources_stages(self):
        data = self.client.get("/api/v1/growth/finder/meta/").json()
        self.assertGreaterEqual(len(data["types"]), 40)
        self.assertEqual([s["key"] for s in data["stages"]], ["new", "researched", "contacted", "interested", "customer", "rejected"])
        self.assertEqual({s["key"] for s in data["sources"]}, {"osm", "search", "directory", "website", "instagram", "neshan"})
        self.assertIn("chagher_gyms_tehran", [p["key"] for p in data["presets"]])
        self.assertIn("cafes_isfahan", [p["key"] for p in data["presets"]])
        self.assertIn("node", data)
        self.assertFalse(data["outreach"]["sending_enabled"])  # automatic sending is off by default

    def test_create_mission_validates_and_from_preset_starts_a_run(self):
        bad = self.client.post("/api/v1/growth/finder/missions/", {"name": "x", "spec": {"cities": []}}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(bad.json()["errors"])
        with mock.patch("apps.growth_engine.crawler.tasks.enqueue_run") as enq:
            ok = self.client.post("/api/v1/growth/finder/missions/from-preset/", {"preset": "cafes_isfahan", "start": True}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["mission"]["preset_key"], "cafes_isfahan")
        self.assertEqual(ok.json()["run"]["status"], "queued")
        enq.assert_called_once()
        again = self.client.post(f"/api/v1/growth/finder/missions/{ok.json()['mission']['id']}/run/")
        self.assertEqual(again.status_code, 400)  # one active run per mission

    def test_run_controls_and_logs(self):
        r = self.client.get(f"/api/v1/growth/finder/runs/{self.run.pk}/").json()
        self.assertEqual(r["status"], "completed")
        self.assertTrue(r["logs"])
        self.assertIn("osm", r["by_source"])
        self.assertTrue(self.client.get(f"/api/v1/growth/finder/runs/{self.run.pk}/logs/?after=0").json()["logs"])
        self.assertEqual(self.client.post(f"/api/v1/growth/finder/runs/{self.run.pk}/pause/").status_code, 400)  # already finished
        self.assertEqual(self.client.post(f"/api/v1/growth/finder/runs/{self.run.pk}/explode/").status_code, 404)
        mission_runs = self.client.get(f"/api/v1/growth/finder/runs/?mission={self.mission.pk}").json()
        self.assertEqual(mission_runs["count"], 1)
        tasks = self.client.get(f"/api/v1/growth/finder/runs/{self.run.pk}/tasks/?source=osm").json()
        self.assertEqual(tasks["count"], 1)

    def test_archive_mission(self):
        r = self.client.delete(f"/api/v1/growth/finder/missions/{self.mission.pk}/")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get("/api/v1/growth/finder/missions/").json()["count"], 0)


class ResultsTests(Fixture, TestCase):
    def test_list_filters_and_ordering(self):
        url = "/api/v1/growth/finder/results/"
        data = self.client.get(url).json()
        self.assertEqual(data["count"], 3)
        scores = [r["score"] for r in data["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        top = data["results"][0]
        self.assertTrue(top["reasons"])
        self.assertIn("phones", top)
        self.assertEqual(self.client.get(url + "?has_email=1").json()["count"], 1)
        self.assertEqual(self.client.get(url + "?has_instagram=1").json()["count"], 1)
        self.assertEqual(self.client.get(url + "?q=سپهر").json()["count"], 1)
        self.assertEqual(self.client.get(url + "?min_score=100").json()["count"], 1)
        self.assertEqual(self.client.get(url + "?min_score=101").json()["count"], 0)
        self.assertEqual(self.client.get(url + f"?mission={self.mission.pk}&city=تهران").json()["count"], 3)
        self.assertEqual(self.client.get(url + "?tag=تست").json()["count"], 3)
        self.assertEqual(self.client.get(url + "?stage=contacted").json()["count"], 0)
        self.assertEqual(self.client.get(url + "?bbox=35.69,51.39,35.705,51.41").json()["count"], 1)

    def test_map_points_have_positions(self):
        data = self.client.get("/api/v1/growth/finder/results/map/").json()
        self.assertEqual(data["total"], 3)
        self.assertTrue(all(-90 < p["lat"] < 90 and p["name"] for p in data["points"]))

    def test_csv_export_is_excel_safe_and_complete(self):
        r = self.client.get("/api/v1/growth/finder/results/export/")
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content).decode("utf-8-sig")
        lines = [ln for ln in body.splitlines() if ln]
        self.assertEqual(len(lines), 4)  # header + 3 leads
        self.assertIn("امتیاز تناسب", lines[0])
        self.assertIn("arman-gym.ir", body)

    def test_summary(self):
        data = self.client.get("/api/v1/growth/finder/results/summary/").json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["by_stage"]["new"], 3)


class PipelineTests(Fixture, TestCase):
    def test_move_between_stages_writes_history(self):
        r = self.client.post(f"/api/v1/growth/finder/leads/{self.arman.pk}/stage/", {"stage": "contacted"}, format="json").json()
        self.assertEqual(r["stage"], "contacted")
        self.arman.refresh_from_db()
        self.assertEqual(self.arman.status, "contacted")
        self.assertTrue(LeadActivity.objects.filter(lead=self.arman, kind="status_changed").exists())
        board = self.client.get("/api/v1/growth/finder/pipeline/").json()
        counts = {s["key"]: s["count"] for s in board["stages"]}
        self.assertEqual(counts["contacted"], 1)
        self.assertEqual(counts["new"], 2)
        self.assertEqual(len(board["stages"]), 6)
        self.assertEqual(self.client.post(f"/api/v1/growth/finder/leads/{self.arman.pk}/stage/", {"stage": "nope"}, format="json").status_code, 400)
        self.assertEqual(pipeline.stage_of("negotiation"), "interested")
        self.assertEqual(pipeline.stage_of("lost"), "rejected")

    def test_finer_status_is_kept_when_the_stage_is_the_same(self):
        Lead.objects.filter(pk=self.arman.pk).update(status="replied")
        self.arman.refresh_from_db()
        pipeline.move(self.arman, "contacted")
        self.arman.refresh_from_db()
        self.assertEqual(self.arman.status, "replied")

    def test_reminders_overdue_today_done(self):
        c = self.client
        r = c.post(f"/api/v1/growth/finder/leads/{self.arman.pk}/reminders/", {"in_days": 0, "note": "زنگ بزن"}, format="json")
        self.assertEqual(r.status_code, 201)
        LeadReminder.objects.filter(pk=r.json()["id"]).update(due_at=timezone.now() - timedelta(hours=3))
        c.post(f"/api/v1/growth/finder/leads/{self.sepehr.pk}/reminders/", {"in_days": 3}, format="json")
        data = c.get("/api/v1/growth/finder/reminders/?when=overdue").json()
        self.assertEqual(data["counts"]["overdue"], 1)
        self.assertEqual(data["items"][0]["note"], "زنگ بزن")
        self.assertTrue(data["items"][0]["overdue"])
        self.assertEqual(c.get("/api/v1/growth/finder/reminders/?when=week").json()["counts"]["open"], 2)
        done = c.patch(f"/api/v1/growth/finder/reminders/{r.json()['id']}/", {"done": True}, format="json").json()
        self.assertTrue(done["done_at"])
        self.assertEqual(c.get("/api/v1/growth/finder/reminders/?when=overdue").json()["counts"]["overdue"], 0)
        self.assertEqual(c.get("/api/v1/growth/finder/reminders/?when=done").json()["items"][0]["lead_id"], self.arman.pk)
        self.assertEqual(c.post(f"/api/v1/growth/finder/leads/{self.arman.pk}/reminders/", {"in_days": 9999}, format="json").status_code, 400)
        kinds = set(LeadActivity.objects.filter(lead=self.arman).values_list("summary", flat=True))
        self.assertTrue(any("یادآوری" in k for k in kinds))

    def test_board_in_overdue_reminder_card(self):
        pipeline.add_reminder(self.arman, {"in_days": 0})
        LeadReminder.objects.update(due_at=timezone.now() - timedelta(days=1))
        cards = [c for s in pipeline.board()["stages"] for c in s["cards"]]
        self.assertTrue(next(c for c in cards if c["id"] == self.arman.pk)["overdue"])


class DraftTests(Fixture, TestCase):
    def generate(self, channels, ids=None):
        return draft_service.generate(self.mission, ids or [self.arman.pk, self.sepehr.pk], channels)

    def test_drafts_use_only_the_pitch_and_end_with_the_opt_out_line(self):
        out = self.generate(["sms", "email", "instagram_dm", "contact_form"])
        self.assertEqual(out["created"], 4)  # sms for both, e-mail + DM for the one that has them; no site form was found for either
        sms = OutreachDraft.objects.get(lead=self.sepehr, channel="sms")
        self.assertIn("چغر", sms.body)
        self.assertTrue(sms.body.rstrip().endswith("برای لغو، «لغو» را بفرستید."))
        self.assertLessEqual(draft_service.sms_channel.segments(sms.body)["parts"], 2)
        email = OutreachDraft.objects.get(lead=self.arman, channel="email")
        self.assertIn("آرمان", email.body)
        self.assertIn("چغر", email.subject)
        self.assertNotRegex(email.body, r"\d+\s*(?:٪|%|درصد|تومان)")
        dm = OutreachDraft.objects.get(lead=self.arman, channel="instagram_dm")
        self.assertIn("instagram.com", dm.recipient)
        self.assertEqual(OutreachItem.objects.count(), 0)  # a draft is not a campaign item
        self.assertEqual(SendAttempt.objects.count(), 0)

    def test_a_lead_without_that_channel_is_skipped_with_a_reason(self):
        out = self.generate(["email"], [self.sepehr.pk])
        self.assertEqual(out["created"], 0)
        self.assertEqual(out["skipped"][0]["reason"], "no_email")

    def test_do_not_contact_blocks_the_draft_and_its_approval(self):
        entries = [suppression.classify("09121112222")]
        suppression.add_entries(entries, "other", "", None)
        out = self.generate(["sms"], [self.sepehr.pk])
        self.assertEqual(out["blocked"], 1)
        d = OutreachDraft.objects.get(lead=self.sepehr, channel="sms")
        self.assertEqual(d.status, "blocked")
        from apps.growth_engine.leads.services.editing import ValidationFailed

        with self.assertRaises(ValidationFailed):
            draft_service.approve(d, self.staff)

    def test_sms_opt_out_list_of_the_phone_app_blocks(self):
        with mock.patch.object(draft_service.sms_channel, "is_opted_out", return_value=True):
            out = self.generate(["sms"], [self.sepehr.pk])
        self.assertEqual(out["blocked"], 1)

    def test_edit_cannot_drop_the_opt_out_line_and_needs_a_new_approval(self):
        self.generate(["sms"], [self.sepehr.pk])
        d = OutreachDraft.objects.get(lead=self.sepehr, channel="sms")
        from apps.growth_engine.leads.services.editing import ValidationFailed

        with self.assertRaises(ValidationFailed):
            draft_service.edit(d, body="سلام بدونِ جملهٔ لغو")
        draft_service.approve(d, self.staff)
        self.assertEqual(d.status, "approved")
        draft_service.edit(d, body=d.body + " ممنون")
        self.assertEqual(d.status, "draft")

    def test_queue_needs_approval_and_only_creates_a_campaign_item_never_a_send(self):
        self.generate(["sms"], [self.sepehr.pk])
        d = OutreachDraft.objects.get(lead=self.sepehr, channel="sms")
        from apps.growth_engine.leads.services.editing import ValidationFailed

        with self.assertRaises(ValidationFailed):
            draft_service.queue(d, self.staff)  # not approved yet
        draft_service.approve(d, self.staff)
        d = draft_service.queue(d, self.staff)
        self.assertEqual(d.status, "queued")
        item = OutreachItem.objects.get(pk=d.item_id)
        self.assertEqual(item.rendered_text, d.body)
        self.assertEqual(item.channel, "sms")
        self.assertIn(item.status, (ItemStatus.PENDING, ItemStatus.READY))  # not approved, not sending
        self.assertEqual(Campaign.objects.get(pk=item.campaign_id).status, "draft")  # the campaign is not started
        self.assertEqual(SendAttempt.objects.count(), 0)
        self.assertFalse(GrowthSettings.load().sending_enabled)

    def test_manual_channel_is_copied_and_marked_by_hand(self):
        self.generate(["instagram_dm"], [self.arman.pk])
        d = OutreachDraft.objects.get(lead=self.arman, channel="instagram_dm")
        from apps.growth_engine.leads.services.editing import ValidationFailed

        with self.assertRaises(ValidationFailed):
            draft_service.queue(d, self.staff)
        draft_service.approve(d, self.staff)
        draft_service.mark_sent_manually(d, self.staff)
        self.arman.refresh_from_db()
        self.assertEqual(self.arman.status, "contacted")
        self.assertEqual(d.status, "sent_manual")

    def test_api_flow_generate_list_approve_bulk(self):
        c = self.client
        r = c.post(f"/api/v1/growth/finder/missions/{self.mission.pk}/drafts/", {"top": 3, "channels": ["sms", "instagram_dm"]}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertGreaterEqual(r.json()["created"], 3)
        lst = c.get(f"/api/v1/growth/finder/drafts/?mission={self.mission.pk}&channel=sms").json()
        self.assertTrue(lst["results"])
        self.assertIn("draft", lst["counts"])
        ids = [d["id"] for d in lst["results"]]
        bulk = c.post("/api/v1/growth/finder/drafts/bulk/", {"ids": ids, "action": "approve"}, format="json").json()
        self.assertEqual(bulk["done"], len(ids))
        one = c.post(f"/api/v1/growth/finder/drafts/{ids[0]}/queue/").json()
        self.assertEqual(one["status"], "queued")
        self.assertTrue(one["campaign_id"])
        self.assertEqual(c.post(f"/api/v1/growth/finder/drafts/{ids[0]}/oops/").status_code, 404)

    def test_no_pitch_means_no_invented_text(self):
        bare = make_mission(pitch={})
        from apps.growth_engine.leads.services.editing import ValidationFailed

        with self.assertRaises(ValidationFailed) as ctx:
            draft_service.generate(bare, [self.arman.pk], ["sms"])
        self.assertEqual(ctx.exception.errors[0]["code"], "no_pitch")

    def test_pitch_comes_from_the_store_when_the_mission_has_none(self):
        from apps.stores.models import Store

        owner = make_plain_user("store-owner")
        store = Store.objects.create(owner=owner, name="کافه‌یار", description="کافه‌یار منوی دیجیتال برای کافه‌هاست. خیلی ساده.", target_audience="کافه‌داران")
        m = make_mission(pitch={})
        m.store = store
        m.save()
        pitch = draft_service.pitch_of(m)
        self.assertEqual(pitch["brand"], "کافه‌یار")
        self.assertIn("منوی دیجیتال", pitch["what"])
        self.assertNotIn("خیلی ساده", pitch["what"])


class NeshanKeyTests(Fixture, TestCase):
    def test_key_is_stored_never_returned_and_can_be_removed(self):
        c = self.client
        self.assertFalse(c.get("/api/v1/growth/finder/neshan-key/").json()["set"])
        self.assertEqual(c.put("/api/v1/growth/finder/neshan-key/", {"api_key": "short"}, format="json").status_code, 400)
        r = c.put("/api/v1/growth/finder/neshan-key/", {"api_key": "service.ABCDEF0123456789abcdef"}, format="json")
        self.assertEqual(r.json(), {"set": True})
        self.assertNotIn("ABCDEF", str(c.get("/api/v1/growth/finder/neshan-key/").json()))
        meta = c.get("/api/v1/growth/finder/meta/").json()
        self.assertTrue(next(s for s in meta["sources"] if s["key"] == "neshan")["key_set"])
        self.assertNotIn("ABCDEF", str(meta))
        from apps.growth_engine.compliance.models import AuditEntry

        self.assertFalse(any("ABCDEF" in str(a.data) + a.summary for a in AuditEntry.objects.all()))
        self.assertFalse(c.delete("/api/v1/growth/finder/neshan-key/").json()["set"])
        self.assertFalse(c.get("/api/v1/growth/finder/neshan-key/").json()["set"])

    def test_the_neshan_source_uses_the_key_and_asks_for_one_when_missing(self):
        import json as _json

        import httpx

        from ..engine.sources import neshan
        from ..models import CrawlRun
        from .helpers import FakeWeb, NOMINATIM_TEHRAN

        web = FakeWeb().add("nominatim.openstreetmap.org", "/search", NOMINATIM_TEHRAN)
        seen = {}

        def api(req: httpx.Request):
            seen["key"] = req.headers.get("api-key")
            return httpx.Response(200, text=_json.dumps({"count": 1, "items": [{"title": "باشگاه نشانی", "address": "تهران، ونک", "category": "gym", "region": "x", "location": {"x": 51.4, "y": 35.7}}]}),
                                  headers={"content-type": "application/json"})

        web.add_fn("api.neshan.org", "/v1/search", api)
        mission = make_mission(sources={"osm": False, "search": False, "directory": False, "website": False, "instagram": False, "neshan": True})
        run = missions.start_run(mission, None, dispatch=False)
        runner.run_crawl(run.pk, web_factory=web.factory)
        run.refresh_from_db()
        self.assertEqual(run.tasks_failed, 1)  # no key yet: the task says so, the run goes on
        self.assertTrue(CrawlRun.objects.get(pk=run.pk).logs.filter(message__contains="کلیدِ API نشان").exists())
        self.client.put("/api/v1/growth/finder/neshan-key/", {"api_key": "service.ABCDEF0123456789abcdef"}, format="json")
        run2 = missions.start_run(mission, None, dispatch=False)
        runner.run_crawl(run2.pk, web_factory=web.factory)
        self.assertEqual(seen["key"], "service.ABCDEF0123456789abcdef")
        self.assertTrue(neshan.api_key())


class DashboardBlockTests(Fixture, TestCase):
    def test_dashboard_block_counts_real_rows(self):
        from ..services import dashboard

        block = dashboard.block()
        self.assertEqual(block["findings"], 3)
        self.assertEqual(block["missions"], 1)
        self.assertEqual(CrawlFinding.objects.count(), 3)
        self.assertIn("finder", __import__("apps.growth_engine.analytics.registry", fromlist=["x"])._PROVIDERS)
