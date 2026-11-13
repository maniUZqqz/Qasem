"""The node side as the site sees it: what the node's report means, queuing a scan, taking a finished job into the tables, the finish hook,
the periodic auto scan, the node self-test verdicts."""
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.compute import services as SV
from apps.compute.models import ComputeJob, ComputeNode, capability_for

from . import dispatch, ingest, seeds, selftest, status
from .models import IgPost, IgScanRun, IgSeed, IgStoreConfig
from .testkit import abagram_post, make_store, niche_pages, node_batch

TMP = tempfile.mkdtemp(prefix="nm-igtrends-dispatch-")


def report(**kw):
    rep = {"ready": False, "problem": None, "state": "up", "step": "", "signed_in": False, "account": "", "url": "http://127.0.0.1:8791/",
           "open_with": "Open-Abagram.bat", "error": "", "proxy": ""}
    rep.update(kw)
    return rep


def node(name="home-gpu", online=True, rep=None, instagram=True, **caps):
    c = {"agent": "2.11", "kinds": ["echo"]}              # agent 2.11 advertises the job kinds it has handlers for (caps["kinds"])
    if instagram:
        c["instagram"] = True
        c["kinds"] = ["echo", "ig.scrape", "ig.health"]
    if rep is not None:
        c["abagram"] = rep
    c.update(caps)
    return ComputeNode.objects.create(name=name, last_seen=timezone.now() if online else timezone.now() - timedelta(hours=3), capabilities=c)


class StatusTests(TestCase):
    def test_every_state_has_a_clear_persian_instruction(self):
        self.assertEqual(status.node_status()["problem"], "no_node")
        old = node("old-node", instagram=False)
        s = status.node_status()
        self.assertEqual(s["problem"], "node_old")
        self.assertFalse(s["can_queue"])
        self.assertIn("به‌روزرسانی", s["message"])
        old.delete()

        n = node(rep=report(ready=False, problem="installing", step="installing packages (pypi.org)"))
        s = status.node_status()
        self.assertEqual(s["problem"], "installing")
        self.assertIn("نصبِ خودکار", s["message"])
        self.assertIn("pypi.org", s["message"])

        for problem, needle in (("install_error", "نصبِ خودکارِ آباگرام"), ("service_down", "روشن نیست"), ("starting", "روشن نیست"),
                                ("unreachable", "فیلتر"), ("cooldown", "صبر کن")):
            n.capabilities = {"agent": "2.10", "instagram": True, "abagram": report(problem=problem, error="pip failed", cooldown_until=1_900_000_000)}
            n.save()
            s = status.node_status()
            self.assertEqual(s["problem"], problem)
            self.assertIn(needle, s["message"], problem)

        n.capabilities = {"agent": "2.10", "instagram": True, "abagram": report(problem="not_signed_in")}
        n.save()
        s = status.node_status()
        self.assertEqual(s["problem"], "not_signed_in")
        for needle in ("Open-Abagram.bat", "http://127.0.0.1:8791/", "پراکسی", "http://127.0.0.1:10809", "فایلِ آباگرام"):
            self.assertIn(needle, s["message"])
        self.assertTrue(s["can_queue"] is False or s["can_queue"] is True)
        self.assertEqual(s["address"], "http://127.0.0.1:8791/")

        n.capabilities = {"agent": "2.10", "instagram": True, "abagram": report(ready=True, problem=None, signed_in=True, account="demo")}
        n.save()
        s = status.node_status()
        self.assertTrue(s["ready"])
        self.assertIsNone(s["problem"])
        self.assertEqual(s["message"], "")

    def test_an_offline_node_can_still_queue(self):
        node(online=False, rep=report(ready=True))
        s = status.node_status()
        self.assertEqual(s["problem"], "node_offline")
        self.assertTrue(s["can_queue"])
        self.assertFalse(s["ready"])

    def test_the_best_node_is_the_ready_one(self):
        node("a-node", rep=report(problem="not_signed_in"))
        node("b-node", rep=report(ready=True))
        self.assertEqual(status.node_status()["node"]["name"], "b-node")

    def test_the_site_routes_the_kind_to_the_instagram_capability(self):
        self.assertEqual(capability_for("ig.scrape"), "instagram")
        self.assertEqual(capability_for("ig.health"), "instagram")
        old = node("old-node", instagram=False)
        good = node("good-node", rep=report(ready=True))
        job = SV.enqueue("ig.scrape", {"accounts": ["a_b"]}, require_online=False)
        self.assertIsNone(SV.claim(old), "an agent that does not advertise «instagram» never receives the kind")
        self.assertEqual(SV.claim(good).uid, job.uid)

    def test_a_node_whose_install_list_still_installs_abagram_does_not_get_the_reading_but_still_the_health_check(self):
        n = node("installing-node", rep=report(problem="installing"))
        n.capabilities = {**n.capabilities, "bootstrap": {"blocked_kinds": {"ig.scrape": "abagram: installing"}}}
        n.save()
        scrape = SV.enqueue("ig.scrape", {"accounts": ["a_b"]}, require_online=False)
        health = SV.enqueue("ig.health", {"test_connection": True}, require_online=False)
        got = SV.claim(n)
        self.assertEqual(got.uid, health.uid, "ig.health must still run so the self-test can see the state")
        self.assertIsNone(SV.claim(n), "ig.scrape waits in the site's queue until the install list says ready")
        n.capabilities = {**n.capabilities, "bootstrap": {"blocked_kinds": {}}}
        n.save()
        self.assertEqual(SV.claim(n).uid, scrape.uid)

    def test_an_agent_that_does_not_list_the_kind_never_receives_it(self):
        n = node("listless-node", rep=report(ready=True), kinds=["echo"])
        SV.enqueue("ig.scrape", {"accounts": ["a_b"]}, require_online=False)
        self.assertIsNone(SV.claim(n))


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class RequestScanTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        seeds.apply_defaults(self.store)

    def test_refusals_carry_the_instruction(self):
        with self.assertRaises(dispatch.ScanRefused) as cm:
            dispatch.request_scan(self.store)
        self.assertEqual(cm.exception.code, "no_node")
        node(rep=report(problem="not_signed_in"))
        with self.assertRaises(dispatch.ScanRefused) as cm:
            dispatch.request_scan(self.store)
        self.assertEqual(cm.exception.code, "not_signed_in")
        self.assertIn("Open-Abagram.bat", str(cm.exception))
        self.assertEqual(IgScanRun.objects.count(), 0)
        self.assertEqual(ComputeJob.objects.filter(kind="ig.scrape").count(), 0)

    def test_a_node_without_the_capability_is_node_old(self):
        node("old-node", instagram=False)
        with self.assertRaises(dispatch.ScanRefused) as cm:
            dispatch.request_scan(self.store)
        self.assertEqual(cm.exception.code, "node_old")

    def test_manual_scan_queues_for_an_offline_node_but_auto_does_not(self):
        node(online=False, rep=report(ready=True))
        with self.assertRaises(dispatch.ScanRefused):
            dispatch.request_scan(self.store, auto=True)
        run = dispatch.request_scan(self.store)
        job = ComputeJob.objects.get(uid=run.job_uid)
        self.assertEqual(job.state, "QUEUED")
        self.assertEqual(job.max_wait_s, dispatch.MAX_WAIT_S)

    def test_due_pages_come_never_read_first_then_oldest_and_not_again_too_soon(self):
        IgSeed.objects.filter(store=self.store, kind="account").delete()
        now = timezone.now()
        for name, ago in (("never_a", None), ("old_b", 30), ("older_c", 50), ("fresh_d", 1)):
            IgSeed.objects.create(store=self.store, kind="account", value=name, last_read_at=None if ago is None else now - timedelta(hours=ago))
        IgSeed.objects.create(store=self.store, kind="account", value="off_e", scrape=False)
        IgSeed.objects.create(store=self.store, kind="account", value="failing_f", fail_count=4)
        self.assertEqual(seeds.due_accounts(self.store, now), ["never_a", "older_c", "old_b"])
        self.assertEqual(seeds.due_accounts(self.store, now, limit=2), ["never_a", "older_c"])
        self.assertIn("fresh_d", seeds.due_accounts(self.store, now, force=True))

    def test_nothing_due_is_a_clear_refusal(self):
        node(rep=report(ready=True))
        IgSeed.objects.filter(store=self.store, kind="account").update(last_read_at=timezone.now())
        with self.assertRaises(dispatch.ScanRefused) as cm:
            dispatch.request_scan(self.store)
        self.assertEqual(cm.exception.code, "nothing_due")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class SyncTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        self.node = node(rep=report(ready=True))
        seeds.apply_defaults(self.store)
        self.run = dispatch.request_scan(self.store)
        self.job = ComputeJob.objects.get(uid=self.run.job_uid)

    def finish(self, batch, ok=True, meta=None, error=""):
        claimed = SV.claim(self.node)
        self.assertEqual(claimed.uid, self.job.uid)
        if batch is not None:
            SV.output_path(self.job, "ig_batch.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
        return SV.finish(self.job, self.node, ok, error, meta or {"primary": "ig_batch.json", "report": {"state": "up"}})

    def batch(self, **kw):
        pages = {n: niche_pages()[n] for n in list(niche_pages())[:2]}
        return node_batch(self.store.pk, self.run.pk, pages=pages, **kw)

    def test_state_follows_the_job(self):
        self.assertEqual(dispatch.sync_run(self.run).state, "queued")
        SV.claim(self.node)
        self.assertEqual(dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk)).state, "running")

    def test_a_completed_job_is_ingested_once(self):
        self.finish(self.batch())
        run = dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk))
        self.assertEqual(run.state, "ok")
        self.assertEqual((run.accounts_read, run.posts_new), (2, 9))
        self.assertIsNotNone(run.ingested_at)
        self.assertIn("۲ صفحه", run.message)
        self.assertEqual(IgPost.objects.count(), 9)
        again = dispatch.sync_run(run)
        self.assertEqual(again.posts_new, 9)
        self.assertEqual(IgPost.objects.count(), 9)

    def test_a_stopped_scan_keeps_what_it_read_and_says_why(self):
        batch = self.batch(stopped={"code": "challenge", "message": "x"})
        self.finish(batch)
        run = dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk))
        self.assertEqual(run.state, "stopped")
        self.assertEqual(run.stop_code, "challenge")
        self.assertIn("تأییدِ انسان", run.message)
        self.assertEqual(run.accounts_read, 2)

    def test_a_stop_before_anything_was_read(self):
        empty = node_batch(self.store.pk, self.run.pk, pages={}, stopped={"code": "not_signed_in", "message": "x"})
        self.finish(empty)
        run = dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk))
        self.assertEqual((run.state, run.accounts_read), ("stopped", 0))
        self.assertIn("وارد", run.message)

    def test_failed_or_cancelled_jobs_fail_the_run(self):
        SV.claim(self.node)
        SV.finish(self.job, self.node, False, "boom happened", {"retryable": False})
        run = dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk))
        self.assertEqual(run.state, "failed")
        self.assertIn("boom", run.message)

    def test_missing_output_or_garbage_fails_the_run_cleanly(self):
        self.finish(None)
        run = dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk))
        self.assertEqual(run.state, "failed")
        self.assertIn("فایلِ نتیجه", run.message)

    def test_garbage_batch(self):
        SV.claim(self.node)
        SV.output_path(self.job, "ig_batch.json").write_text("{\"format\": \"nope\"}", encoding="utf-8")
        SV.finish(self.job, self.node, True, {})
        run = dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk))
        self.assertEqual(run.state, "failed")
        self.assertIn("نتیجه خوانده نشد", run.message)

    def test_the_finish_endpoint_takes_the_result_in_at_once(self):
        claimed = SV.claim(self.node)
        SV.output_path(claimed, "ig_batch.json").write_text(json.dumps(self.batch(), ensure_ascii=False), encoding="utf-8")
        c = APIClient()
        r = c.post("/api/v1/compute/jobs/%s/finish/" % claimed.uid, {"ok": True, "meta": {"primary": "ig_batch.json"}}, format="json",
                   HTTP_AUTHORIZATION="Node " + self.node.token)
        self.assertEqual(r.status_code, 200, r.content)
        run = IgScanRun.objects.get(pk=self.run.pk)
        self.assertEqual(run.state, "ok")
        self.assertEqual(IgPost.objects.count(), 9)

    def test_a_broken_ingest_never_breaks_the_finish_call(self):
        claimed = SV.claim(self.node)
        from unittest import mock
        with mock.patch("apps.igtrends.dispatch.on_job_finished", side_effect=RuntimeError("db down")):
            r = APIClient().post("/api/v1/compute/jobs/%s/finish/" % claimed.uid, {"ok": True, "meta": {}}, format="json",
                                 HTTP_AUTHORIZATION="Node " + self.node.token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ComputeJob.objects.get(pk=claimed.pk).state, "COMPLETED")
        self.assertEqual(dispatch.sync_runs(), 1, "the periodic sync picks it up")

    def test_a_scan_that_vanished_from_the_queue_is_failed(self):
        ComputeJob.objects.filter(pk=self.job.pk).delete()
        self.assertEqual(dispatch.sync_run(IgScanRun.objects.get(pk=self.run.pk)).state, "failed")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class AutoScanTests(TestCase):
    def setUp(self):
        self.user, self.store = make_store()
        seeds.apply_defaults(self.store)

    def test_a_fitness_store_nobody_opened_still_gets_its_starter_pack_and_first_scan(self):
        user2, store2 = make_store("چغر", "owner-chagher", business_type="gym")
        other_user, other = make_store("فروشگاه لوازم خانگی", "owner-home", business_type="home")
        self.assertFalse(IgStoreConfig.objects.filter(store=store2).exists())
        node(rep=report(ready=True))
        out = dispatch.auto_scan_all()
        self.assertIn(store2.pk, out["seeded"])
        self.assertNotIn(other.pk, out["seeded"], "only fitness / coaching shops are seeded by themselves")
        self.assertTrue(IgSeed.objects.filter(store=store2, kind="account", value="cheg_her").exists(), "the shop's own page is watched too")
        self.assertIn(store2.pk, [IgScanRun.objects.get(pk=r).store_id for r in out["started"]])
        self.assertEqual(dispatch.auto_scan_all()["seeded"], [], "seeded once")

    def test_nothing_happens_while_the_node_is_not_ready(self):
        node(rep=report(problem="not_signed_in"))
        out = dispatch.auto_scan_all()
        self.assertEqual(out["started"], [])
        self.assertEqual(out["skipped"]["_node"], "not_signed_in")

    def test_one_scan_per_store_per_interval(self):
        node(rep=report(ready=True))
        out = dispatch.auto_scan_all()
        self.assertEqual(len(out["started"]), 1)
        self.assertEqual(ComputeJob.objects.filter(kind="ig.scrape").count(), 1)
        self.assertEqual(dispatch.auto_scan_all()["started"], [])
        IgScanRun.objects.update(state="ok", created_at=timezone.now() - timedelta(hours=9))
        IgSeed.objects.filter(store=self.store, kind="account").update(last_read_at=None)
        self.assertEqual(len(dispatch.auto_scan_all()["started"]), 1)

    def test_a_store_that_turned_it_off_or_has_no_pages_is_skipped(self):
        node(rep=report(ready=True))
        IgStoreConfig.objects.filter(store=self.store).update(auto_scan=False)
        self.assertEqual(dispatch.auto_scan_all()["started"], [])
        IgStoreConfig.objects.filter(store=self.store).update(auto_scan=True)
        IgSeed.objects.filter(store=self.store, kind="account").delete()
        out = dispatch.auto_scan_all()
        self.assertEqual(out["skipped"][self.store.pk], "no_seeds")

    def test_the_budget_is_tiny(self):
        node(rep=report(ready=True))
        run = dispatch.auto_scan_all()["started"][0]
        job = ComputeJob.objects.get(uid=IgScanRun.objects.get(pk=run).job_uid)
        self.assertLessEqual(len(job.payload["accounts"]), 5)
        self.assertGreaterEqual(job.payload["pace_s"][0], 30)


class SelfTestVerdictTests(TestCase):
    def test_health(self):
        ok = selftest.evaluate("health", {"ok": True, "report": {"ready": True}})
        self.assertEqual(ok["status"], "pass")
        self.assertTrue(ok["ready"])
        waiting = selftest.evaluate("health", {"ok": True, "report": {"ready": False, "problem": "not_signed_in"}})
        self.assertEqual(waiting["status"], "pass")
        self.assertIn("Open-Abagram", waiting["message"])
        bad = selftest.evaluate("health", {"ok": False, "report": {"problem": "install_error", "error": "pip failed"}})
        self.assertEqual(bad["status"], "fail")
        self.assertIn("pip failed", bad["message"])

    def test_scrape(self):
        self.assertEqual(selftest.evaluate("scrape", {"accounts_read": 1, "posts": 6})["status"], "pass")
        self.assertEqual(selftest.evaluate("scrape", {"accounts_read": 0, "stopped": {"code": "challenge"}})["status"], "skip")
        self.assertEqual(selftest.evaluate("scrape", {"accounts_read": 0, "stopped": {"code": "weird", "message": "m"}})["status"], "fail")
        self.assertEqual(selftest.evaluate("nope", {})["status"], "fail")

    def test_the_job_specs_are_minimal(self):
        self.assertEqual(selftest.SCRAPE["payload"]["max_accounts"], 1)
        self.assertEqual(selftest.SCRAPE["payload"]["accounts"], ["instagram"])
        self.assertEqual(selftest.HEALTH["kind"], "ig.health")


class SelfTestRegistryTests(TestCase):
    """The two checks live in apps/compute/selftests/trends_instagram.py and run in the node's automatic acceptance run."""

    def setUp(self):
        from types import SimpleNamespace

        from apps.compute.selftests import Ctx, load_all
        self.reg = load_all()
        self.ns, self.Ctx = SimpleNamespace, Ctx

    def ctx(self, n):
        return self.Ctx(n, None)

    def job(self, **meta):
        return self.ns(result={"meta": meta})

    def test_both_are_registered_with_the_right_shape(self):
        health, scrape = self.reg["ig_health"], self.reg["ig_scrape"]
        self.assertEqual((health.kind, scrape.kind), ("ig.health", "ig.scrape"))
        self.assertTrue(scrape.optional, "Instagram's mood must not turn the node's overall result red")
        self.assertEqual(scrape.after, ("ig_health",))
        n = node(rep=report(ready=True))
        self.assertEqual(health.build(self.ctx(n)).kind, "ig.health")
        spec = scrape.build(self.ctx(n))
        self.assertEqual(spec.kind, "ig.scrape")
        self.assertEqual(spec.payload["accounts"], ["instagram"])
        self.assertLessEqual(spec.payload["max_accounts"], 1)

    def test_availability_follows_what_the_node_reports(self):
        health, scrape = self.reg["ig_health"], self.reg["ig_scrape"]
        old = node("old-node", instagram=False)
        self.assertFalse(health.available(old)[0])
        self.assertFalse(scrape.available(old)[0])
        installing = node("installing-node", rep=report(problem="installing"))
        self.assertTrue(health.available(installing)[0])
        ok, why = scrape.available(installing)
        self.assertFalse(ok)
        self.assertIn("نصب", why)
        ready = node("ready-node", rep=report(ready=True))
        self.assertTrue(scrape.available(ready)[0])

    def test_health_verdicts(self):
        health = self.reg["ig_health"]
        n = node(rep=report(ready=True))
        ctx = self.ctx(n)
        self.assertTrue(health.check(ctx, self.job(ok=True, report={"ready": True, "state": "up"})).ok)
        v = health.check(ctx, self.job(ok=True, report={"ready": False, "state": "up", "problem": "not_signed_in"}))
        self.assertTrue(v.ok, "not being signed in is not a defect: one person has to do it once")
        self.assertIn("Open-Abagram", v.detail)
        self.assertTrue(health.check(ctx, self.job(ok=False, report={"problem": "installing"})).wait)
        bad = health.check(ctx, self.job(ok=False, report={"problem": "install_error", "error": "pip failed"}))
        self.assertFalse(bad.ok)
        self.assertFalse(bad.wait)

    def test_scrape_verdicts(self):
        scrape = self.reg["ig_scrape"]
        ctx = self.ctx(node(rep=report(ready=True)))
        self.assertTrue(scrape.check(ctx, self.job(accounts_read=1, posts=6, stopped=None)).ok)
        stopped = scrape.check(ctx, self.job(accounts_read=0, posts=0, stopped={"code": "challenge", "message": "x"}))
        self.assertTrue(stopped.skip, "a human check from Instagram is not a defect of the node: the stop itself worked")
        broken = scrape.check(ctx, self.job(accounts_read=0, posts=0, stopped={"code": "service_down", "message": "no answer"}))
        self.assertFalse(broken.ok)
        self.assertFalse(broken.skip)
