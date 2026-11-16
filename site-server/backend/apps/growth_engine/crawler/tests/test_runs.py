"""A whole run against a fake web: plan -> discover -> dedupe -> enrich -> finalize, pause / resume / cancel, budgets, the schedule, the node hand-over."""
from __future__ import annotations

import gzip
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.growth_engine.leads.models import ContactPoint, Lead
from apps.growth_engine.leads.services.drafts import build_draft
from apps.growth_engine.leads.services.intake import SourceInfo, create_from_draft

from ..engine import fetch, nodebridge, runner
from ..engine.sources import instagram
from ..models import CandidateKey, CrawlCandidate, CrawlFinding, CrawlLog, CrawlMission, CrawlRun, CrawlTask, LeadInsight
from ..services import missions
from .helpers import JS_SHELL, NOMINATIM_TEHRAN, Base, FakeWeb, make_mission, osm_node, overpass_json


def run_it(web: FakeWeb, mission: CrawlMission | None = None, **spec) -> CrawlRun:
    mission = mission or make_mission(**spec)
    run = missions.start_run(mission, None, dispatch=False)
    runner.run_crawl(run.pk, web_factory=web.factory)
    run.refresh_from_db()
    return run


class FullRunTests(Base, TestCase):
    def test_a_run_finds_dedupes_enriches_and_writes_leads(self):
        web = self.web_with_gyms()
        run = run_it(web)
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.stage, "done")
        # 5 map objects: «آرمان» twice at the same spot is ONE business, the far branch is another, the one without contact is skipped
        self.assertEqual(run.found_count, 5)
        self.assertEqual(run.unique_count, 4)
        self.assertEqual(run.created_count, 3)
        self.assertEqual(run.skipped_count, 1)
        leads = Lead.objects.filter(crawl_findings__mission=run.mission).distinct()
        self.assertEqual(leads.count(), 3)
        arman = leads.get(website__icontains="arman-gym.ir")
        kinds = {c.kind for c in arman.contacts.all()}
        self.assertTrue({"phone", "email", "website", "instagram"} <= kinds)  # the site's own contact page added e-mail + Instagram to the map's phone
        ins = LeadInsight.objects.get(lead=arman)
        self.assertAlmostEqual(ins.lat, 35.7001, places=3)
        self.assertTrue(ins.hours)
        finding = CrawlFinding.objects.get(mission=run.mission, lead=arman)
        self.assertGreaterEqual(finding.score, 60)
        self.assertTrue(any("نقشه" in r["text"] for r in finding.reasons))
        self.assertIn("تست", [t.name for t in arman.tags.all()])
        self.assertTrue(CrawlLog.objects.filter(run=run).exists())
        self.assertGreater(run.pages_fetched, 3)

    def test_second_run_updates_instead_of_duplicating_and_uses_the_cache(self):
        web = self.web_with_gyms()
        mission = make_mission()
        first = run_it(web, mission)
        hits_before = web.hits("arman-gym.ir", "/contact")
        second = run_it(web, mission)
        self.assertEqual(second.status, "completed")
        self.assertEqual(Lead.objects.filter(crawl_findings__mission=mission).distinct().count(), 3)
        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.merged_count, 3)
        self.assertGreater(second.cache_hits, 0)
        self.assertEqual(web.hits("arman-gym.ir", "/contact"), hits_before)  # the contact page was not downloaded again
        self.assertEqual(CrawlFinding.objects.get(mission=mission, lead__website__icontains="arman-gym.ir").seen_count, 2)
        self.assertIsNotNone(first.finished_at)

    def test_existing_lead_with_the_same_phone_is_merged_not_duplicated(self):
        draft, _ = build_draft({"business_name": "فیتنس سپهر (قدیمی)", "phone": "09121112222", "city": "تهران"}, source_ref="manual")
        old = create_from_draft(draft, SourceInfo(provider="manual"))
        web = self.web_with_gyms()
        run = run_it(web)
        self.assertEqual(Lead.objects.filter(contacts__normalized="09121112222").distinct().count(), 1)
        self.assertEqual(run.merged_count, 1)
        self.assertTrue(CrawlFinding.objects.filter(lead=old).exists())
        old.refresh_from_db()
        self.assertEqual(old.business_name, "فیتنس سپهر (قدیمی)")  # fill-only: a name that exists is never overwritten

    def test_name_and_place_dedupe_against_an_existing_lead_without_shared_identifiers(self):
        draft, _ = build_draft({"business_name": "باشگاه آرمان", "city": "تهران", "website": "https://other-site.ir"}, source_ref="manual")
        old = create_from_draft(draft, SourceInfo(provider="manual"))
        LeadInsight.objects.create(lead=old, lat=35.7001, lon=51.4001)
        run = run_it(self.web_with_gyms())
        self.assertGreaterEqual(run.merged_count, 1)
        self.assertEqual(Lead.objects.filter(business_name="باشگاه آرمان").count(), 2)  # the old lead (now enriched) + the branch 14 km away
        self.assertTrue(CrawlFinding.objects.filter(lead=old).exists())

    def test_nothing_is_ever_sent(self):
        from apps.growth_engine.outreach.models import OutreachItem, SendAttempt

        run_it(self.web_with_gyms())
        self.assertEqual(OutreachItem.objects.count(), 0)
        self.assertEqual(SendAttempt.objects.count(), 0)


class ControlTests(Base, TestCase):
    def test_pause_then_resume_continues_where_it_stopped(self):
        web = self.web_with_gyms()
        mission = make_mission()
        run = missions.start_run(mission, None, dispatch=False)
        calls = {"n": 0}
        original = runner.Engine.check_interrupt

        def interrupt_after_first_task(self_):
            calls["n"] += 1
            if calls["n"] == 2:
                CrawlRun.objects.filter(pk=self_.run.pk).update(pause_requested=True)
                self_._flags_at = 0
            return original(self_)

        with mock.patch.object(runner.Engine, "check_interrupt", interrupt_after_first_task):
            result = runner.run_crawl(run.pk, web_factory=web.factory)
        self.assertEqual(result, "paused")
        run.refresh_from_db()
        self.assertTrue(run.paused)
        self.assertEqual(run.status, "queued")
        self.assertFalse(Lead.objects.filter(crawl_findings__mission=mission).exists())
        done_before = CrawlTask.objects.filter(run=run, status="done").count()
        missions.resume_run(run, dispatch=False)
        self.assertEqual(runner.run_crawl(run.pk, web_factory=web.factory), "completed")
        run.refresh_from_db()
        self.assertFalse(run.paused)
        self.assertGreaterEqual(CrawlTask.objects.filter(run=run, status="done").count(), done_before)
        self.assertEqual(Lead.objects.filter(crawl_findings__mission=mission).distinct().count(), 3)

    def test_cancel_stops_and_marks_the_tasks(self):
        web = self.web_with_gyms()
        run = missions.start_run(make_mission(), None, dispatch=False)
        CrawlRun.objects.filter(pk=run.pk).update(cancel_requested=True)
        runner.run_crawl(run.pk, web_factory=web.factory)
        run.refresh_from_db()
        self.assertEqual(run.status, "cancelled")
        self.assertEqual(len(web.calls), 0)  # cancelled before anything was fetched

    def test_cancel_of_a_queued_run_through_the_service(self):
        run = missions.start_run(make_mission(), None, dispatch=False)
        run = missions.cancel_run(run)
        self.assertEqual(run.status, "cancelled")
        with self.assertRaises(Exception):
            missions.resume_run(run, dispatch=False)

    def test_only_one_active_run_per_mission(self):
        mission = make_mission()
        missions.start_run(mission, None, dispatch=False)
        with self.assertRaises(Exception):
            missions.start_run(mission, None, dispatch=False)

    def test_request_budget_ends_the_run_with_what_it_has(self):
        web = self.web_with_gyms()
        mission = make_mission(budget={"max_requests": 20, "max_sites": 10, "max_pages_per_site": 4, "max_seconds": 300, "domain_delay": 1.0})
        run = missions.start_run(mission, None, dispatch=False)
        CrawlRun.objects.filter(pk=run.pk).update(usage={"budget": {"requests": 19, "bytes": 0, "cache_hits": 0, "failures": 0, "seconds": 0, "per_host": {}}})
        runner.run_crawl(run.pk, web_factory=web.factory)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertTrue(CrawlLog.objects.filter(run=run, message__contains="سقف").exists())

    def test_a_busy_map_server_parks_the_run_and_the_tick_wakes_it(self):
        web = self.web_with_gyms()
        web.add("overpass-api.de", "/api/interpreter", "busy", status=502, ctype="text/plain")
        for host in ("maps.mail.ru", "overpass.private.coffee", "overpass.kumi.systems"):
            web.add(host, "/", "busy", status=502, ctype="text/plain")
        mission = make_mission()
        run = missions.start_run(mission, None, dispatch=False)
        self.assertEqual(runner.run_crawl(run.pk, web_factory=web.factory), "parked")
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertTrue((run.usage or {}).get("parked_until"))
        task = CrawlTask.objects.get(run=run, source="osm")
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.attempts, 1)
        # the map is back: the tick wakes the run and it finishes
        web2 = self.web_with_gyms()
        CrawlTask.objects.filter(pk=task.pk).update(not_before=timezone.now() - timedelta(seconds=1))
        CrawlRun.objects.filter(pk=run.pk).update(usage={**run.usage, "parked_until": (timezone.now() - timedelta(seconds=5)).isoformat()})
        from .. import tasks

        with mock.patch.object(tasks, "enqueue_run") as enq:
            out = tasks.tick()
        self.assertEqual(out["woken"], [run.pk])
        enq.assert_called_once_with(run.pk)
        self.assertEqual(runner.run_crawl(run.pk, web_factory=web2.factory), "completed")

    def test_the_map_task_falls_back_to_nominatim_after_three_busy_answers(self):
        web = self.web_with_gyms()
        for host in ("overpass-api.de", "maps.mail.ru", "overpass.private.coffee", "overpass.kumi.systems"):
            web.add(host, "/", "busy", status=502, ctype="text/plain")
        web.add_fn("nominatim.openstreetmap.org", "/search", lambda req: None)
        import httpx

        def nominatim(req: httpx.Request):
            if "extratags" in str(req.url):
                body = [{"osm_type": "node", "osm_id": 77, "lat": "35.7", "lon": "51.4", "name": "باشگاه نومیناتیم", "category": "leisure", "type": "fitness_centre",
                         "display_name": "باشگاه نومیناتیم, خیابان آزادی, تهران", "extratags": {"phone": "09125556666"}, "namedetails": {"name": "باشگاه نومیناتیم"}}]
                return httpx.Response(200, text=json.dumps(body), headers={"content-type": "application/json"})
            return None

        web.add_fn("nominatim.openstreetmap.org", "/search", nominatim)
        mission = make_mission()
        run = missions.start_run(mission, None, dispatch=False)
        for _ in range(4):
            status = runner.run_crawl(run.pk, web_factory=web.factory)
            if status != "parked":
                break
            CrawlTask.objects.filter(run=run, status="pending").update(not_before=timezone.now() - timedelta(seconds=1))
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertTrue(Lead.objects.filter(business_name="باشگاه نومیناتیم").exists())


class ScheduleTests(Base, TestCase):
    def test_due_missions_start_themselves_and_repeat(self):
        mission = make_mission()
        missions.update_mission(mission, {"schedule_days": 7})
        CrawlMission.objects.filter(pk=mission.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
        with mock.patch("apps.growth_engine.crawler.tasks.enqueue_run"):
            started = missions.tick_schedule()
        self.assertEqual(len(started), 1)
        mission.refresh_from_db()
        self.assertGreater(mission.next_run_at, timezone.now() + timedelta(days=6))
        self.assertEqual(CrawlRun.objects.get(pk=started[0]).trigger, "schedule")
        # while that run is active the mission is not started twice
        CrawlMission.objects.filter(pk=mission.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
        with mock.patch("apps.growth_engine.crawler.tasks.enqueue_run"):
            self.assertEqual(missions.tick_schedule(), [])

    def test_disabled_or_archived_missions_do_not_run(self):
        mission = make_mission()
        missions.update_mission(mission, {"schedule_days": 1})
        missions.update_mission(mission, {"enabled": False})
        mission.refresh_from_db()
        self.assertIsNone(mission.next_run_at)
        self.assertEqual(missions.tick_schedule(), [])


class MissionValidationTests(TestCase):
    def test_errors_are_persian_and_specific(self):
        from apps.growth_engine.leads.services.editing import ValidationFailed

        with self.assertRaises(ValidationFailed) as ctx:
            missions.validate_spec({"business_types": ["nope"], "cities": [], "sources": {"osm": False, "search": False, "directory": False, "website": False}, "budget": {"max_sites": 99999}})
        fields = {e["field"] for e in ctx.exception.errors}
        self.assertTrue({"business_types", "cities", "sources", "budget"} <= fields)
        self.assertTrue(all(e["message"] for e in ctx.exception.errors))

    def test_free_keywords_without_a_type_are_enough(self):
        spec = missions.validate_spec({"keywords": ["کلاس پیانو"], "cities": ["مشهد"]})
        self.assertEqual(spec["business_types"], [])
        self.assertTrue(spec["sources"]["osm"])


# --------------------------------------------------------------------------- the processing node


class NodeHandOverTests(Base, TestCase):
    def setUp(self):
        super().setUp()
        from apps.compute.models import ComputeNode

        self.ComputeNode = ComputeNode

    def make_gym_run_with_js_site(self):
        web = FakeWeb()
        web.add("nominatim.openstreetmap.org", "/search", NOMINATIM_TEHRAN)
        web.add("overpass-api.de", "/api/interpreter", overpass_json([osm_node(1, "باشگاه جاوا", 35.7, 51.4, leisure="fitness_centre", website="http://js-gym.ir")]))
        web.add("js-gym.ir", "/", JS_SHELL, exact=True)
        return web

    def test_a_js_site_waits_for_the_node_and_is_finished_when_it_answers(self):
        from apps.compute import services as SV
        from apps.compute.models import ComputeJob

        node = self.ComputeNode.objects.create(name="gpu1", capabilities={"crawl": True}, last_seen=timezone.now())
        web = self.make_gym_run_with_js_site()
        run = run_it(web, require_contact=False)
        self.assertEqual(run.status, "completed")
        task = CrawlTask.objects.get(run=run, kind="node_site")
        self.assertEqual(task.status, "waiting_node")
        self.assertTrue(task.node_job_uid)
        job = ComputeJob.objects.get(uid=task.node_job_uid)
        self.assertEqual(job.kind, "crawl.render")
        self.assertEqual(run.tasks_waiting, 1)
        lead = Lead.objects.get(business_name="باشگاه جاوا")
        self.assertFalse(lead.contacts.filter(kind="phone").exists())
        # the node renders the page and answers
        cand = CrawlCandidate.objects.get(run=run)
        site = {"id": cand.pk, "url": "http://js-gym.ir", "status": "ok", "pages": [{"url": "http://js-gym.ir/", "kind": "home", "status": 200, "outcome": "ok", "rendered": True,
                                                                                 "html": "<html lang='fa'><body><h1>باشگاه جاوا</h1><p>تلفن: <a href='tel:09123334444'>09123334444</a></p></body></html>"}]}
        path = SV.output_path(job, "pages.jsonl.gz")
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(json.dumps(site, ensure_ascii=False) + "\n")
        ComputeJob.objects.filter(pk=job.pk).update(state=ComputeJob.State.COMPLETED, finished_at=timezone.now())
        from .. import tasks

        out = tasks.tick()
        self.assertEqual(out["node"], 1)
        task.refresh_from_db()
        self.assertEqual(task.status, "done")
        self.assertTrue(lead.contacts.filter(kind="phone", normalized="09123334444").exists())
        run.refresh_from_db()
        self.assertEqual(run.tasks_waiting, 0)
        self.assertIsNotNone(node.pk)

    def test_without_any_capable_node_the_work_waits_without_a_job_and_starts_by_itself_later(self):
        from apps.compute.models import ComputeJob

        web = self.make_gym_run_with_js_site()
        # a node that has NOT been updated yet (an old agent advertises no «crawl»)
        old = self.ComputeNode.objects.create(name="gpu-old", capabilities={"photo": True}, last_seen=timezone.now() - timedelta(days=3))
        run = run_it(web, require_contact=False, sources={"osm": True, "search": False, "directory": False, "website": True, "instagram": True, "neshan": False})
        self.assertEqual(run.status, "completed")
        waiting = CrawlTask.objects.filter(run=run, status="waiting_node")
        self.assertEqual(waiting.count(), 0)  # a JS site is only queued when a node is known to be able to render it
        # an Instagram page needs the node as well
        cand = CrawlCandidate.objects.get(run=run)
        CrawlCandidate.objects.filter(pk=cand.pk).update(instagram="https://www.instagram.com/js_gym/")
        CrawlTask.objects.create(run=run, stage="ig", source="instagram", kind="ig_profile", key="ig:js_gym", params={"candidate_id": cand.pk, "handle": "js_gym"}, status="waiting_node")
        res = runner.sync_node(run)
        self.assertEqual(res["queued"], 0)
        self.assertFalse(ComputeJob.objects.filter(kind="ig.scrape").exists())  # no node can run it yet: nothing is queued, nothing is lost
        self.assertEqual(CrawlTask.objects.get(run=run, kind="ig_profile").status, "waiting_node")
        # the node is updated, switched on and reports the capability: the very next tick queues the job
        self.ComputeNode.objects.filter(pk=old.pk).update(capabilities={"photo": True, "instagram": True}, last_seen=timezone.now())
        res = runner.sync_node(run)
        self.assertEqual(res["queued"], 1)
        job = ComputeJob.objects.get(kind="ig.scrape")
        self.assertEqual(job.payload["accounts"], ["js_gym"])
        self.assertTrue(CrawlTask.objects.get(run=run, kind="ig_profile").node_job_uid)
        self.assertIsNotNone(instagram.KIND)

    def test_instagram_answer_fills_the_lead(self):
        from apps.compute import services as SV
        from apps.compute.models import ComputeJob

        self.ComputeNode.objects.create(name="gpu1", capabilities={"instagram": True, "crawl": True}, last_seen=timezone.now())
        web = self.make_gym_run_with_js_site()
        run = run_it(web, require_contact=False, sources={"osm": True, "search": False, "directory": False, "website": False, "instagram": True, "neshan": False})
        cand = CrawlCandidate.objects.get(run=run)
        CrawlCandidate.objects.filter(pk=cand.pk).update(instagram="https://www.instagram.com/js_gym/")
        cand.refresh_from_db()
        runner.add_task_specs(run, [instagram.task_for(cand)])
        runner.queue_node_work(run, run.spec)
        job = ComputeJob.objects.get(kind="ig.scrape")
        batch = {"format": "nm-ig-batch", "version": 1, "accounts": [{"username": "js_gym", "full_name": "باشگاه جاوا", "biography": "باشگاه بدنسازی | ☎ 09125550000 | js-gym.ir", "followers": 5400, "is_business": True, "category": "Gym"}],
                 "posts": [], "per_account": {"js_gym": {"status": "ok", "posts": 0}}, "stopped": None}
        with open(SV.output_path(job, "ig_batch.json"), "w", encoding="utf-8") as fh:
            json.dump(batch, fh, ensure_ascii=False)
        ComputeJob.objects.filter(pk=job.pk).update(state=ComputeJob.State.COMPLETED, finished_at=timezone.now())
        res = runner.sync_node(run)
        self.assertEqual(res["ingested"], 1)
        lead = Lead.objects.get(business_name="باشگاه جاوا")
        self.assertTrue(lead.contacts.filter(kind="phone", normalized="09125550000").exists())
        finding = CrawlFinding.objects.get(lead=lead)
        self.assertTrue(any("دنبال‌کننده" in r["text"] for r in finding.reasons))
        self.assertIsNotNone(nodebridge.KINDS)


class SpecKnobsTests(Base, TestCase):
    """min_score / exclude_words / max_results / size / language really change what is written."""

    def test_max_results_keeps_the_best_fitting(self):
        run = missions.start_run(make_mission(), None, dispatch=False)
        CrawlRun.objects.filter(pk=run.pk).update(spec={**run.spec, "max_results": 1})  # the validator's lowest is 10: set it directly
        runner.run_crawl(run.pk, web_factory=self.web_with_gyms().factory)
        run.refresh_from_db()
        self.assertEqual(run.created_count + run.merged_count, 1)
        best = CrawlFinding.objects.get(last_run=run)
        self.assertEqual(best.lead.website, "http://arman-gym.ir")  # the one that scores highest is the one that was kept

    def test_min_score_and_excluded_words_skip_with_a_reason(self):
        run = run_it(self.web_with_gyms(), min_score=90)
        self.assertEqual(run.created_count + run.merged_count, 1)
        self.assertGreaterEqual(run.skipped_count, 3)
        run2 = run_it(self.web_with_gyms(), None, exclude_words=["سپهر"])
        names = set(Lead.objects.filter(crawl_findings__last_run=run2).values_list("business_name", flat=True))
        self.assertNotIn("فیتنس سپهر", names)
