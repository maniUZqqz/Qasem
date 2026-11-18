# -*- coding: utf-8 -*-
"""«امشب: روشن کردنِ سرورِ پردازش» (tonight.py + views_tonight.py) و خودترمیمی (heal.py)."""
import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import heal, tonight
from . import updates as U
from .models import ComputeJob, ComputeNode, ComputeSettings
from .models_platform import SelfTestResult, SelfTestRun

User = get_user_model()


def caps(**over):
    base = {"agent": "2.34", "commands": ["status", "update", "restart", "build", "logs", "bootstrap"], "ollama": True, "comfyui": True,
            "ollama_models": ["qwen3:8b", "qwq:32b", "qwen3-vl:30b", "qwen3-coder:30b"], "code": {"version": "2.34", "id": "x"}}
    base.update(over)
    return base


def boot(features):
    return {"v": 1, "features": features, "summary": {}, "blocked_kinds": {}}


def feat(state, title="ویژگی", kinds=(), items=None):
    return {"title": title, "state": state, "kinds": list(kinds), "applicable": True, "why": "",
            "items": items or [{"id": "pip", "type": "pip", "title": "نصبِ بسته‌ها", "state": state, "progress": 0.4 if state == "installing" else None,
                                "detail": "downloading x" if state == "installing" else "", "error": "no space left" if state == "failed" else "", "tail": [], "tries": 1}]}


class TonightBase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-tonight-"))
        ctx = override_settings(NM_DATA_DIR=self.tmp, IS_TEST=True)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.latest = mock.patch.object(U, "latest", return_value={"version": "2.34", "id": "abc123", "size": 1, "built": ""})
        self.latest.start()
        self.addCleanup(self.latest.stop)

    def node(self, online=True, name="DESKTOP-EAFBTGQ", **c):
        return ComputeNode.objects.create(name=name, capabilities=caps(**c) if c.get("agent", True) else c, last_seen=timezone.now() if online else timezone.now() - timedelta(days=5))


class PlanTests(TonightBase):
    def test_every_requirements_file_is_in_the_plan_in_install_order_with_declared_sizes(self):
        plan = tonight.planned_features()
        names = {f["feature"] for f in plan}
        on_disk = {p.stem for p in (U.source_dir() / "requirements.d").glob("*.json")}
        self.assertTrue(on_disk and len(plan) == len(on_disk))
        self.assertEqual(names, {json.loads(p.read_text(encoding="utf-8"))["feature"] for p in (U.source_dir() / "requirements.d").glob("*.json")})
        self.assertEqual([f["order"] for f in plan], sorted(f["order"] for f in plan))
        self.assertTrue(any(f["bytes"] > 100_000_000 for f in plan), "Blender / Whisper / Piper sizes are declared")


class OffBeforeTests(TonightBase):
    def test_no_node_at_all(self):
        r = tonight.build()
        self.assertEqual(r["phase"], "off")
        self.assertEqual(r["steps"][0]["state"], "fail")
        self.assertTrue(r["checklist"])

    def test_offline_node_shows_the_checklist_and_the_planned_installs(self):
        self.node(online=False, agent="2.10", code={"version": "2.10", "id": "old"})
        r = tonight.build()
        self.assertEqual(r["phase"], "off")
        steps = {s["key"]: s for s in r["steps"]}
        self.assertEqual(steps["power"]["state"], "todo")
        self.assertIn("۵ روز", steps["power"]["detail"])
        self.assertEqual(steps["update"]["state"], "todo")
        self.assertIn("۲.۱۰", steps["update"]["detail"])
        self.assertIn("۲.۳۴", steps["update"]["detail"])
        self.assertTrue(r["installs"] and all(i["state"] == "todo" for i in r["installs"]))
        self.assertEqual(len(r["checklist"]), 6)
        self.assertTrue(all(c["title"] and c["detail"] for c in r["checklist"]))
        self.assertEqual(steps["installs"]["state"], "todo")

    def test_auto_update_off_is_called_out_in_the_checklist(self):
        self.node(online=False)
        cfg = ComputeSettings.get()
        cfg.auto_update = False
        cfg.save()
        r = tonight.build()
        self.assertIn("خاموش", r["checklist"][1]["detail"])


class LiveTests(TonightBase):
    def test_online_old_agent_is_in_the_update_phase_and_nothing_else_runs(self):
        n = self.node(agent="2.10", code={"version": "2.10", "id": "old"}, commands=["status", "update", "restart", "build", "logs"])
        r = tonight.build(n.pk)
        self.assertEqual(r["phase"], "update")
        upd = [s for s in r["steps"] if s["key"] == "update"][0]
        self.assertEqual(upd["state"], "doing")
        self.assertEqual(upd["action"], "update")
        self.assertIn("۲.۱۰", upd["detail"])
        self.assertIn("۲.۳۴", upd["detail"])

    def test_installs_show_progress_and_a_failed_item_turns_the_whole_step_red_with_a_retry(self):
        n = self.node(bootstrap=boot({"asr-gpu": feat("installing", "تشخیص گفتار"), "crawl": feat("ready", "مشتری‌یاب"), "pron": feat("failed", "تلفظ", kinds=["voice.pron_eval"])}))
        r = tonight.build(n.pk)
        head = [s for s in r["steps"] if s["key"] == "installs"][0]
        self.assertEqual(head["state"], "fail")
        self.assertEqual(head["action"], "bootstrap")
        rows = {x["feature"]: x for x in r["installs"]}
        self.assertEqual(rows["asr-gpu"]["state"], "doing")
        self.assertEqual(rows["crawl"]["state"], "done")
        self.assertEqual(rows["pron"]["state"], "fail")
        self.assertIn("no space left", rows["pron"]["detail"])
        self.assertAlmostEqual(rows["asr-gpu"]["progress"], 0.4)

    def test_installs_in_progress_without_failures(self):
        n = self.node(bootstrap=boot({"asr-gpu": feat("installing"), "crawl": feat("ready")}))
        r = tonight.build(n.pk)
        self.assertEqual([s for s in r["steps"] if s["key"] == "installs"][0]["state"], "doing")
        self.assertEqual(r["phase"], "installs")

    def test_self_installing_extras_are_shown_too(self):
        n = self.node(bootstrap=boot({"crawl": feat("ready")}), motion={"state": "installing", "message": "دانلودِ بستهٔ رندرر", "progress": 0.5},
                      brandchar={"ready": False, "note": "FLUX پیدا نشد"}, comfyui=False)
        r = tonight.build(n.pk)
        rows = {x["key"]: x for x in r["installs"]}
        self.assertEqual(rows["install:motion"]["state"], "doing")
        self.assertAlmostEqual(rows["install:motion"]["progress"], 0.5)
        self.assertEqual(rows["install:brandchar-flux"]["state"], "warn")
        self.assertIn("FLUX", rows["install:brandchar-flux"]["detail"])
        self.assertEqual(rows["install:comfyui"]["state"], "warn")
        self.assertEqual(rows["install:ollama"]["state"], "done")
        self.assertEqual([s for s in r["steps"] if s["key"] == "installs"][0]["state"], "doing")

    def test_selftests_group_by_feature_and_failures_carry_the_reason(self):
        n = self.node(bootstrap=boot({"crawl": feat("ready")}))
        run = SelfTestRun.objects.create(node=n, trigger="version", agent_version="2.34")
        for key, state, detail in (("echo", "PASSED", "رفت‌وبرگشت"), ("gpu", "FAILED", "nvidia-smi کارت را نمی‌بیند"), ("ollama_text", "RUNNING", ""), ("ollama_vision", "PENDING", ""),
                                   ("matting", "SKIPPED", "مدل نصب نیست")):
            SelfTestResult.objects.create(run=run, key=key, label=key, state=state, detail=detail)
        r = tonight.build(n.pk)
        rows = {t["key"]: t for t in r["tests"]}
        self.assertEqual(rows["test:اتصال صف ⇒ گره"]["state"], "done")
        self.assertEqual(rows["test:کارت گرافیک"]["state"], "fail")
        self.assertIn("nvidia-smi", rows["test:کارت گرافیک"]["detail"])
        self.assertEqual(rows["test:Ollama (متن و بینایی)"]["state"], "doing")
        self.assertEqual(rows["test:جداسازیِ پس‌زمینهٔ عکس"]["state"], "warn")
        head = [s for s in r["steps"] if s["key"] == "selftests"][0]
        self.assertEqual(head["state"], "doing")

    def test_queue_rows_show_what_runs_by_itself_and_what_failed(self):
        n = self.node(bootstrap=boot({}))
        ComputeJob.objects.create(kind="echo", state=ComputeJob.State.QUEUED, queued_at=timezone.now())
        ComputeJob.objects.create(kind="comfy.graph", state=ComputeJob.State.FAILED, finished_at=timezone.now(), error="x")
        r = tonight.build(n.pk)
        kinds = {q["kind"]: q for q in r["queue"]}
        self.assertEqual(kinds["echo"]["queued"], 1)
        self.assertEqual(kinds["comfy.graph"]["failed"], 1)
        self.assertEqual(kinds["comfy.graph"]["state"], "fail")
        self.assertIn("کار با آمدنِ گره اجرا می‌شود", kinds["echo"]["detail"])

    def test_models_row_follows_the_owners_models_without_changing_them(self):
        n = self.node()
        r = tonight.build(n.pk)
        models = [s for s in r["steps"] if s["key"] == "models"][0]
        self.assertEqual(models["models"], ["qwen3:8b", "qwq:32b", "qwen3-vl:30b", "qwen3-coder:30b"])
        self.assertTrue(all(k["installed"] for k in models["kinds"]), models["kinds"])
        self.assertEqual(models["state"], "done")
        text = [k for k in models["kinds"] if k["kind"] == "text"][0]
        self.assertEqual(text["model"], "qwen3:8b", "gemma3:12b is not installed: the chain picks the owner's qwen3:8b")

    def test_everything_green_is_done(self):
        n = self.node(bootstrap=boot({"crawl": feat("ready")}))
        run = SelfTestRun.objects.create(node=n, trigger="version", agent_version="2.34", state=SelfTestRun.State.FINISHED)
        SelfTestResult.objects.create(run=run, key="echo", label="echo", state="PASSED")
        r = tonight.build(n.pk)
        self.assertIn(r["phase"], ("done", "attention", "jobs"))
        self.assertEqual([s for s in r["steps"] if s["key"] == "power"][0]["state"], "done")
        self.assertEqual(r["checklist"], [])


class ApiTests(TonightBase):
    def test_staff_only(self):
        self.node()
        u = User.objects.create_user("plain", password="x")
        c = APIClient()
        c.force_authenticate(u)
        self.assertEqual(c.get("/api/v1/compute/tonight/").status_code, 403)
        self.assertEqual(c.post("/api/v1/compute/tonight/retry/", {"what": "kick"}, format="json").status_code, 403)
        s = APIClient()
        s.force_authenticate(User.objects.create_user("st", password="x", is_staff=True))
        r = s.get("/api/v1/compute/tonight/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("steps", r.json())
        self.assertEqual(len(r.json()["steps"]), 7)

    def test_retry_actions_use_the_existing_tools(self):
        n = self.node()
        s = APIClient()
        s.force_authenticate(User.objects.create_user("st", password="x", is_staff=True))
        with mock.patch("apps.compute.commands.request", return_value={"id": "c1"}) as req:
            r = s.post("/api/v1/compute/tonight/retry/", {"what": "bootstrap", "node": n.pk}, format="json")
        self.assertEqual(r.status_code, 200)
        req.assert_called_once()
        self.assertEqual(req.call_args[0][1], "bootstrap")
        with mock.patch("apps.compute.selftests.runner.start_run", return_value=mock.Mock(pk=7)) as start:
            r = s.post("/api/v1/compute/tonight/retry/", {"what": "selftest", "node": n.pk}, format="json")
        self.assertEqual(r.status_code, 200)
        start.assert_called_once()
        self.assertEqual(s.post("/api/v1/compute/tonight/retry/", {"what": "rm -rf"}, format="json").status_code, 400)
        off = ComputeNode.objects.create(name="off", capabilities=caps(), last_seen=timezone.now() - timedelta(days=2))
        r = s.post("/api/v1/compute/tonight/retry/", {"what": "selftest", "node": off.pk}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertIn("خاموش", r.json()["message"])

    def test_selftest_retry_refuses_an_offline_node(self):
        n = self.node(online=False)
        out = tonight.retry("selftest", n.pk)
        self.assertFalse(out["ok"])
        self.assertIn("خاموش", out["message"])


# ───────────────────────────── خودترمیمی

class HealTests(TestCase):
    def setUp(self):
        from apps.jobs.models import Job
        from apps.products.models import Product

        self.Job = Job
        self.user = User.objects.create_user("o", password="x")
        self.store = Store.objects.create(owner=self.user, name="چغر")
        self.p1 = Product.objects.create(store=self.store, name="بستهٔ یک", is_available=True)
        self.p2 = Product.objects.create(store=self.store, name="بستهٔ دو", is_available=True)
        self.p3 = Product.objects.create(store=self.store, name="هرگز تحلیل نخواسته", is_available=True)

    def job(self, product, state, hours_ago=1):
        j = self.Job.objects.create(store=self.store, type=self.Job.Type.PRODUCT_ANALYSIS, state=state, context={"product_id": product.pk})
        self.Job.objects.filter(pk=j.pk).update(updated_at=timezone.now() - timedelta(hours=hours_ago))
        return j

    def test_only_products_that_asked_once_and_lost_it_are_orphans(self):
        self.job(self.p1, self.Job.State.FAILED)                      # asked, failed (server restart) -> orphan
        self.job(self.p2, self.Job.State.QUEUED)                      # a live job -> not an orphan
        names = [p.pk for p in heal.orphaned_products()]
        self.assertEqual(names, [self.p1.pk])
        self.assertNotIn(self.p3.pk, names, "a product nobody asked to analyse is never analysed behind the owner's back")

    def test_a_product_that_failed_twice_recently_is_left_alone(self):
        self.job(self.p1, self.Job.State.FAILED, 1)
        self.job(self.p1, self.Job.State.FAILED, 2)
        self.assertEqual(heal.orphaned_products(), [])
        self.Job.objects.filter(context__product_id=self.p1.pk).update(updated_at=timezone.now() - timedelta(hours=30))
        self.assertEqual([p.pk for p in heal.orphaned_products()], [self.p1.pk])

    def test_requeue_needs_an_online_ollama_node_and_a_real_queue(self):
        self.job(self.p1, self.Job.State.FAILED)
        with override_settings(CELERY_TASK_ALWAYS_EAGER=False), mock.patch("apps.jobs.services.dispatch_job", return_value=None) as dispatch:
            self.assertEqual(heal.requeue_analysis(), 0, "no node online")
            ComputeNode.objects.create(name="g", capabilities={"ollama": True}, last_seen=timezone.now())
            self.assertEqual(heal.requeue_analysis(), 1)
        dispatch.assert_called_once()
        new = self.Job.objects.filter(type=self.Job.Type.PRODUCT_ANALYSIS, state=self.Job.State.QUEUED, context__healed=True).first()
        self.assertIsNotNone(new)
        self.assertEqual(new.context["product_id"], self.p1.pk)

    def test_at_most_two_live_analyses_at_once(self):
        for p in (self.p2, self.p3):
            self.job(p, self.Job.State.QUEUED)
        self.job(self.p1, self.Job.State.FAILED)
        ComputeNode.objects.create(name="g", capabilities={"ollama": True}, last_seen=timezone.now())
        with override_settings(CELERY_TASK_ALWAYS_EAGER=False), mock.patch("apps.jobs.services.dispatch_job", return_value=None):
            self.assertEqual(heal.requeue_analysis(), 0)
