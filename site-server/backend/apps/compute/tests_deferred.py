# -*- coding: utf-8 -*-
"""«در صف تا روشن شدنِ سرورِ پردازش» (deferred.py) + ترتیبِ مسیر (اول گره، بعد متیس) + ممیزیِ ایستا: هیچ ویژگی از دروازه دور نمی‌زند."""
import ast
import importlib
import inspect
import json
import re
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from datetime import timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import deferred, park, tasks
from .models import ComputeJob, ComputeNode

User = get_user_model()
APPS = Path(__file__).resolve().parents[1]
BACKEND = APPS.parent


def node(online=True, name="gpu-1", ollama=True):
    return ComputeNode.objects.create(name=name, capabilities={"ollama": ollama, "ollama_models": ["qwen3:8b"]}, last_seen=timezone.now() if online else None)


class Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-deferred-"))
        ctx = override_settings(NM_DATA_DIR=self.tmp, AI_DEFER_FORCE=True)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user = User.objects.create_user("owner", password="x")
        self.store = Store.objects.create(owner=self.user, name="چغر آزمایشی")


class DeferQueueTests(Base):
    def test_defer_creates_one_durable_waiting_row_and_dedupes(self):
        node(online=False)
        a = deferred.defer("brandchar.persona", self.store, {"brief": "شاد"}, user=self.user, reason="سرورِ پردازش خاموش است")
        self.assertIsNotNone(a)
        self.assertEqual(a["message"], "در صف تا روشن شدنِ سرورِ پردازش")
        self.assertEqual(a["state"], "queued")
        row = ComputeJob.objects.get(uid=a["uid"])
        self.assertEqual(row.kind, park.PARK_KIND)
        self.assertEqual(row.state, ComputeJob.State.QUEUED)
        self.assertEqual(row.store_id, self.store.pk)
        self.assertEqual(row.payload["capability"], "ollama")
        self.assertEqual(row.payload["title"], "پیش‌نویسِ شخصیتِ برند")
        b = deferred.defer("brandchar.persona", self.store, {"brief": "شاد"}, user=self.user)
        self.assertEqual(b["uid"], a["uid"], "the same request is not queued twice")
        c = deferred.defer("brandchar.persona", self.store, {"brief": "جدی"}, user=self.user)
        self.assertNotEqual(c["uid"], a["uid"])
        self.assertEqual(deferred.pending_count(), 2)

    def test_nothing_is_promised_when_no_node_and_no_metis_exist(self):
        with override_settings(UPMARKET_AI={**__import__("django.conf").conf.settings.UPMARKET_AI, "AI_API_BASE_URL": "", "AI_API_KEY": ""}):
            self.assertIsNone(deferred.defer("thumbs.ideas", self.store, {"topic": "x"}, user=self.user))

    def test_unknown_feature_and_test_mode_do_not_queue(self):
        node()
        self.assertIsNone(deferred.defer("no.such.feature", self.store, {}))
        with override_settings(AI_DEFER_FORCE=False):
            self.assertIsNone(deferred.defer("thumbs.ideas", self.store, {"topic": "x"}))

    def test_a_placeholder_is_not_cancelled_by_the_job_waker(self):
        node(online=True)
        q = deferred.defer("thumbs.ideas", self.store, {"topic": "x"}, user=self.user)
        with mock.patch.object(park, "_dispatch") as dispatch:
            park.wake_parked()
        dispatch.assert_not_called()
        self.assertEqual(ComputeJob.objects.get(uid=q["uid"]).state, ComputeJob.State.QUEUED)

    def test_registry_functions_exist_and_take_the_run_arguments(self):
        for key, spec in deferred.FEATURES.items():
            fn = deferred._resolve(spec["fn"])
            sig = inspect.signature(fn)
            self.assertIn("_user_id", sig.parameters, key)
            self.assertTrue(callable(spec["used"]), key)
            self.assertTrue(spec["label"], key)
            if not spec.get("platform"):
                self.assertEqual(list(sig.parameters)[0], "store", key)


class WakeTests(Base):
    def queue_one(self):
        return deferred.defer("thumbs.ideas", self.store, {"topic": "x"}, user=self.user)

    def test_offline_node_and_open_metis_circuit_do_nothing(self):
        node(online=False)
        self.queue_one()
        with mock.patch("services.ai.priority.metis_configured", return_value=True), \
             mock.patch("services.ai.priority.open_failure", return_value={"kind": "no_credit"}), \
             mock.patch.object(tasks.run_deferred, "delay") as delay:
            self.assertEqual(deferred.wake(), 0)
        delay.assert_not_called()

    def test_online_node_dispatches_exactly_one_per_minute(self):
        node(online=True)
        self.queue_one()
        deferred.defer("thumbs.ideas", self.store, {"topic": "y"}, user=self.user)
        with mock.patch.object(tasks.run_deferred, "delay") as delay:
            self.assertEqual(deferred.wake(), 1)
            self.assertEqual(deferred.wake(), 0, "the first one is still running - the card has one slot")
        self.assertEqual(delay.call_count, 1)

    def test_metis_back_with_closed_circuit_is_enough_without_a_node(self):
        node(online=False)
        self.queue_one()
        with mock.patch("services.ai.priority.metis_configured", return_value=True), \
             mock.patch("services.ai.priority.open_failure", return_value=None), \
             mock.patch.object(tasks.run_deferred, "delay") as delay:
            self.assertEqual(deferred.wake(), 1)
        delay.assert_called_once()

    def test_a_stale_dispatch_is_retried_later(self):
        node(online=True)
        q = self.queue_one()
        row = ComputeJob.objects.get(uid=q["uid"])
        d = dict(row.payload["deferred"])
        d["dispatched_at"] = (timezone.now() - timedelta(minutes=45)).isoformat()
        row.payload = {**row.payload, "deferred": d}
        row.save()
        with mock.patch.object(tasks.run_deferred, "delay") as delay:
            self.assertEqual(deferred.wake(), 1)
        delay.assert_called_once()


class RunTests(Base):
    def setUp(self):
        super().setUp()
        node(online=True)

    def run_with(self, fn, feature="thumbs.ideas", params=None):
        q = deferred.defer(feature, self.store, params or {"topic": "x"}, user=self.user)
        spec = dict(deferred.FEATURES[feature], fn="apps.compute.tests_deferred:_fake")
        with mock.patch.dict(deferred.FEATURES, {feature: spec}), mock.patch(__name__ + "._fake", fn, create=True):
            out = deferred.run(q["uid"])
        return q, out

    def test_success_writes_the_result_and_removes_the_row(self):
        q, out = self.run_with(lambda store, **kw: {"via": "ai", "ideas": [1, 2], "uid_user": kw.get("_user_id")})
        self.assertEqual(out, "done")
        self.assertFalse(ComputeJob.objects.filter(uid=q["uid"]).exists())
        doc = deferred.status(q["uid"])
        self.assertEqual(doc["state"], "done")
        self.assertEqual(doc["result"]["ideas"], [1, 2])
        self.assertEqual(doc["result"]["uid_user"], self.user.pk)

    def test_ai_still_down_keeps_it_queued_with_a_counter(self):
        q, out = self.run_with(lambda store, **kw: {"via": "rules", "ai": {"reason": "سرور خاموش"}})
        self.assertEqual(out, "requeued")
        row = ComputeJob.objects.get(uid=q["uid"])
        self.assertEqual(row.state, ComputeJob.State.QUEUED)
        self.assertEqual(row.payload["deferred"]["attempts"], 1)
        self.assertIsNone(row.payload["deferred"]["started_at"])
        self.assertEqual(deferred.status(q["uid"])["state"], "queued")

    def test_an_outage_exception_requeues_and_a_bug_fails_with_a_persian_status(self):
        class Down(Exception):
            parkable = True

        q, out = self.run_with(lambda store, **kw: (_ for _ in ()).throw(Down("گره شلوغ")))
        self.assertEqual(out, "requeued")
        q2, out2 = self.run_with(lambda store, **kw: (_ for _ in ()).throw(ValueError("خراب")), params={"topic": "y"})
        self.assertEqual(out2, "failed")
        self.assertEqual(deferred.status(q2["uid"])["state"], "failed")
        self.assertIn("خراب", deferred.status(q2["uid"])["error"])

    def test_cancel_marks_the_result_cancelled(self):
        q = deferred.defer("thumbs.ideas", self.store, {"topic": "z"}, user=self.user)
        self.assertTrue(deferred.cancel(q["uid"]))
        self.assertEqual(deferred.status(q["uid"])["state"], "cancelled")
        self.assertFalse(deferred.cancel(q["uid"]))

    def test_too_old_requests_are_dropped_with_a_clear_reason(self):
        q = deferred.defer("thumbs.ideas", self.store, {"topic": "old"}, user=self.user)
        row = ComputeJob.objects.get(uid=q["uid"])
        d = dict(row.payload["deferred"])
        d["created"] = (timezone.now() - timedelta(hours=100)).isoformat()
        row.payload = {**row.payload, "deferred": d}
        row.save()
        self.assertEqual(deferred.run(q["uid"]), "failed")
        self.assertIn("۷۲ ساعت", deferred.status(q["uid"])["error"])

    def test_run_uses_the_long_wait_inside_a_deferred_run(self):
        seen = []

        def probe(store, **kw):
            seen.append(deferred.in_deferred_run())
            return {"via": "ai"}

        self.run_with(probe)
        self.assertEqual(seen, [True])
        self.assertFalse(deferred.in_deferred_run())


def _fake(store, **kw):  # replaced per test (mock.patch above)
    raise AssertionError("not patched")


class ApiTests(Base):
    def test_status_is_private_to_the_store_and_staff(self):
        node()
        q = deferred.defer("thumbs.ideas", self.store, {"topic": "x"}, user=self.user)
        url = "/api/v1/compute/deferred/%s/" % q["uid"]
        owner = APIClient()
        owner.force_authenticate(self.user)
        r = owner.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["message"], "در صف تا روشن شدنِ سرورِ پردازش")
        stranger = User.objects.create_user("stranger", password="x")
        c = APIClient()
        c.force_authenticate(stranger)
        self.assertEqual(c.get(url).status_code, 404)
        staff = User.objects.create_user("staff", password="x", is_staff=True)
        s = APIClient()
        s.force_authenticate(staff)
        self.assertEqual(s.get(url).status_code, 200)
        self.assertEqual(APIClient().get(url).status_code, 401)
        self.assertTrue(owner.post(url + "cancel/").json()["cancelled"])
        self.assertEqual(owner.get(url).json()["state"], "cancelled")

    def test_platform_level_requests_are_staff_only(self):
        node()
        q = deferred.defer("growth.writer", None, {"version_id": 1})
        self.assertIsNotNone(q)
        url = "/api/v1/compute/deferred/%s/" % q["uid"]
        c = APIClient()
        c.force_authenticate(self.user)
        self.assertEqual(c.get(url).status_code, 404)
        s = APIClient()
        s.force_authenticate(User.objects.create_user("st", password="x", is_staff=True))
        self.assertEqual(s.get(url).status_code, 200)


class FeatureHookTests(Base):
    """هر ویژگی وقتی هوش مصنوعی «با صبر درست می‌شود» ⇒ همان پاسخِ فرمولی + queued؛ وقتی نه ⇒ بدونِ queued."""

    def setUp(self):
        super().setUp()
        node(online=False)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def outage(self, parkable=True):
        from apps.ideabank import ai as IA

        return IA.AIUnavailable("سرورِ پردازش خاموش است؛ متیس: اعتبار تمام شده (۴۰۲)", parkable=parkable)

    def test_persona_draft_is_queued_and_keeps_the_rule_draft(self):
        from apps.brandchar import persona_ai

        with mock.patch.object(persona_ai, "default_ask", side_effect=self.outage()):
            r = self.client.post(reverse("brandchar-persona-draft", kwargs={"store_id": self.store.pk}), {"brief": "شاد و کوتاه"}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        data = r.json()
        self.assertTrue(data["persona"]["archetype"])
        self.assertEqual(data["queued"]["message"], "در صف تا روشن شدنِ سرورِ پردازش")
        self.assertTrue(any("در صف تا روشن شدنِ سرورِ پردازش" in n for n in data["notes"]))
        self.assertEqual(deferred.pending_count(), 1)

    def test_persona_draft_without_a_parkable_reason_is_not_queued(self):
        from apps.brandchar import persona_ai

        with mock.patch.object(persona_ai, "default_ask", side_effect=self.outage(parkable=False)):
            r = self.client.post(reverse("brandchar-persona-draft", kwargs={"store_id": self.store.pk}), {"brief": "x"}, format="json")
        self.assertNotIn("queued", r.json())
        self.assertEqual(deferred.pending_count(), 0)

    def test_concepts_are_queued(self):
        from apps.brandchar import concepts

        with mock.patch.object(concepts, "default_ask", side_effect=self.outage()):
            r = self.client.post(reverse("brandchar-concepts", kwargs={"store_id": self.store.pk}), {"description": "مربیِ خندانِ موبلند با هدبندِ فیروزه‌ای"}, format="json")
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertEqual(r.json()["queued"]["feature"], "brandchar.concepts")
        self.assertTrue(r.json()["options"], "the rule-based ideas are still there")

    def test_ideabank_is_queued(self):
        from apps.ideabank import ai as IA

        with mock.patch.object(IA, "default_ask", side_effect=self.outage()):
            r = self.client.post(reverse("ideabank-generate", kwargs={"store_id": self.store.pk}), {"count": 3, "topic": "کفش"}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        data = r.json()
        self.assertEqual(data["via"], "formula")
        self.assertEqual(data["queued"]["feature"], "ideabank.generate")
        self.assertIn("در صف تا روشن شدنِ سرورِ پردازش", data["message"])

    def test_thumbs_ideas_are_queued(self):
        from apps.thumbs import ideation

        err = ideation.AIUnavailable("سرورِ پردازش خاموش است")
        err.parkable = True
        with mock.patch.object(ideation, "_default_ask", side_effect=err):
            r = self.client.post(reverse("thumbs-ideas", kwargs={"store_id": self.store.pk}), {"topic": "تمرینِ خانگی"}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.json()["queued"]["feature"], "thumbs.ideas")

    def test_motion_code_returns_202_with_a_queue_ticket(self):
        from apps.motion import ai as motion_ai

        err = motion_ai.AIUnavailable("هوش مصنوعی الان در دسترس نیست: سرورِ پردازش خاموش است", parkable=True)
        with mock.patch.object(motion_ai, "code_from_idea", side_effect=err):
            r = self.client.post(reverse("motion-ai-code", kwargs={"store_id": self.store.pk}), {"idea": "یک تیتر بزرگ"}, format="json")
        self.assertEqual(r.status_code, 202, r.content[:300])
        self.assertEqual(r.json()["queued"]["feature"], "motion.code")

    def test_growth_writer_failure_queues_a_platform_request(self):
        from apps.growth_engine.knowledge.services import ai as growth_ai

        class Down(Exception):
            parkable = True

        exc = growth_ai.AiUnavailable("هوش مصنوعی در دسترس نیست")
        exc.__cause__ = Down("گره خاموش")
        self.assertTrue(deferred.is_outage(exc))
        self.assertFalse(deferred.is_outage(growth_ai.AiUnavailable("پاسخِ مدل ساختار نداشت")))


class OutageClassificationTests(SimpleTestCase):
    def test_chain_and_flag(self):
        class Inner(Exception):
            parkable = True

        try:
            try:
                raise Inner("x")
            except Inner as inner:
                raise RuntimeError("wrapped") from inner
        except RuntimeError as outer:
            self.assertTrue(deferred.is_outage(outer))
        self.assertFalse(deferred.is_outage(ValueError("plain bug")))

    def test_real_router_failures(self):
        from services.ai.priority import Failure
        from services.ai.routing import AllProvidersFailed

        down = AllProvidersFailed("both", {"local": Failure("offline", "off", provider="local"), "metis": Failure("no_credit", "402", provider="metis")})
        self.assertTrue(deferred.is_outage(down))
        key = AllProvidersFailed("both", {"local": Failure("no_model", "x", provider="local"), "metis": Failure("bad_key", "401", provider="metis")})
        self.assertFalse(deferred.is_outage(key))


# ───────────────────────────── ترتیبِ مسیر

class RouteOrderTests(TestCase):
    """اول گره (لوکال) و بعد متیس؛ هر دو خاموش ⇒ خطای قابل‌صف (node_waiting) نه خطای بی‌صدا؛ «فقط لوکال» هرگز به متیس نمی‌رود."""

    def setUp(self):
        self.user = User.objects.create_user("o", password="x")
        self.store = Store.objects.create(owner=self.user, name="s")

    def router(self, local_ok, metis_ok, store_policy=None):
        from services.ai import routing

        calls = []

        class Fallback:
            def select_models(self, c):
                return ["m"]

            def generate(self, prompt, model=None, **kw):
                calls.append("metis")
                if not metis_ok:
                    raise RuntimeError("HTTP 402 insufficient credit")
                return "from-metis"

        r = routing.RoutedTextProvider(Fallback(), task="t", kind="text")

        def local(prov, model):
            calls.append("local")
            if not local_ok:
                raise routing.NodeFailed("سرورِ پردازش وسطِ کار قطع شد.")
            return "from-local"

        return r, calls, local

    @override_settings(AI_ROUTE_FORCE=True)
    def test_default_order_is_local_then_metis(self):
        from services.ai import priority

        self.assertEqual(priority.config().order("text"), ["local", "metis"])
        for kind in ("text", "research", "code", "vision"):
            self.assertEqual(priority.config().order(kind)[0], "local", kind)

    @override_settings(AI_ROUTE_FORCE=True)
    def test_online_node_answers_and_metis_is_never_called(self):
        node(online=True)
        r, calls, local = self.router(True, True)
        with mock.patch("services.ai.routing.node_state", return_value={"ready": True, "model": "qwen3:8b", "wanted": "gemma3:12b", "chain": ["qwen3:8b"], "has_model": True,
                                                                         "known_models": ["qwen3:8b"], "node": "gpu-1", "online": True, "reason": ""}):
            out = r._route(local, lambda has_alt: ("x", "m"))
        self.assertEqual(out, "from-local")

    @override_settings(AI_ROUTE_FORCE=True)
    def test_node_down_then_metis_answers(self):
        node(online=False)
        r, calls, local = self.router(False, True)
        out = r._route(local, lambda has_alt: (r.fallback.generate("p"), "gpt"))
        self.assertEqual(out, "from-metis")
        self.assertEqual(calls, ["metis"], "an offline node is never waited for")

    @override_settings(AI_ROUTE_FORCE=True)
    def test_both_down_with_a_registered_node_is_a_queueable_outage(self):
        from services.ai import routing

        node(online=False)
        r, calls, local = self.router(False, False)
        with self.assertRaises(routing.AllProvidersFailed) as cm:
            r._route(local, lambda has_alt: (r.fallback.generate("p"), "gpt"))
        self.assertEqual(getattr(cm.exception, "node_waiting", ""), "ollama")
        self.assertTrue(deferred.is_outage(cm.exception))

    @override_settings(AI_ROUTE_FORCE=True)
    def test_local_only_policy_never_reaches_metis(self):
        from services.ai import gateway

        node(online=False)
        from apps.ai.models import StoreAIPolicy

        StoreAIPolicy.objects.create(store=self.store, mode="LOCAL_ONLY")
        prov = gateway.text_provider(self.store, gateway.CUSTOMER, kind="text")
        self.assertIsNone(prov.fallback, "the Metis path does not exist for a local-only store")


# ───────────────────────────── ممیزیِ ایستا

#: فایل‌هایی که اجازه دارند مستقیم با ارائه‌دهندهٔ هوش مصنوعی حرف بزنند (همه چیزِ دیگر باید از services.ai.gateway / routing بگذرد)
DIRECT_ALLOWED = {
    "apps/ai_engine/providers.py",       # سایت‌ساز: مسیریاب StudioRouted خودش همین‌جاست؛ «آزمونِ اتصال» direct=True
    "apps/ai_engine/admin.py", "apps/ai_engine/api.py", "apps/ai_engine/models.py",
    "apps/up3d/models.py", "apps/up3d/panel.py",   # تنظیماتِ صدای ویدیوی سه‌بعدی (TTS) — نه متن
    "apps/ai/models.py", "apps/jobs/management/commands/aisetup.py",
}
PATTERNS = (r"OllamaProvider\(", r"OpenAICompatProvider\(", r"api\.metisai", r"/chat/completions", r"api\.openai\.com/v1/", r"\b11434\b")


class RouteAuditTests(SimpleTestCase):
    def test_no_feature_talks_to_a_model_provider_around_the_gateway(self):
        bad = []
        for path in sorted(APPS.rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if "/tests" in rel or "/migrations/" in rel or rel.endswith("tests.py") or rel in DIRECT_ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
            for pat in PATTERNS:
                if re.search(pat, code):
                    bad.append("%s: %s" % (rel, pat))
        self.assertEqual(bad, [], "AI calls must go through services.ai.gateway (node first, Metis second):\n" + "\n".join(bad))

    def test_every_feature_ai_entry_uses_the_gateway_or_the_router(self):
        """هر ماژولی که «هوش مصنوعی» صدا می‌زند باید gateway/routing/ai_engine.providers را بخواند (فهرستِ ثابتِ ماژول‌های دورهای ۱ تا ۳)."""
        modules = {
            "apps/brandchar/persona_ai.py": "gateway", "apps/brandchar/concepts.py": "gateway", "apps/design_studio/ai.py": "gateway",
            "apps/ideabank/ai.py": "gateway", "apps/motion/ai.py": "gateway", "apps/thumbs/ideation.py": "gateway", "apps/content/tasks.py": "gateway",
            "apps/customers/agent.py": "gateway", "apps/growth_engine/knowledge/services/ai.py": "gateway", "apps/ai/tasks.py": "gateway",
            "apps/regen/services.py": "gateway", "apps/shoot/plan.py": "gateway", "apps/mobile/notes.py": "gateway", "apps/photoedit/translate.py": "gateway",
            "apps/projects/builder/c21_translate.py": "providers",
        }
        for rel, needle in modules.items():
            text = (BACKEND / rel).read_text(encoding="utf-8")
            self.assertIn(needle, text, rel)

    def test_every_deferred_feature_is_wired_in_its_view(self):
        """ثبت در FEATURES کافی نیست: view هم باید deferred.defer(<همان کلید>) را صدا بزند."""
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in APPS.rglob("*.py") if "/tests" not in p.as_posix() and "compute/deferred.py" not in p.as_posix())
        for key in deferred.FEATURES:
            self.assertRegex(text, r'defer\(\s*"%s"' % re.escape(key), key)


class C21TranslateTests(Base):
    """ترجمهٔ AI ِ قطعهٔ 21st: درجا با فرهنگ‌لغت درج می‌شود، بقیه «در صف تا روشن شدنِ سرورِ پردازش» می‌ماند و خودکار جایگزین می‌شود."""

    TEXTS = ["Build faster with our platform today", "Pricing"]

    def test_an_outage_is_marked_parkable_so_the_view_can_queue_it(self):
        from apps.projects.builder import c21_translate as TR

        class Down(Exception):
            parkable = True

        def boom(system, user):
            raise Down("گره خاموش")

        out, info = TR.ai_translate(list(self.TEXTS), complete=boom)
        self.assertEqual(out, self.TEXTS)
        self.assertFalse(info["ok"])
        self.assertTrue(info["parkable"])

        def bug(system, user):
            raise ValueError("پاسخِ خراب")

        _out, info2 = TR.ai_translate(list(self.TEXTS), complete=bug)
        self.assertFalse(info2.get("parkable"))

    def test_deferred_translate_returns_texts_and_seed_or_requeues(self):
        from apps.projects import c21_api

        rec = {"key": "lib/x", "texts": list(self.TEXTS), "links": [], "images": []}
        ok_info = {"ok": True, "translated": 1, "message": "۱ متن"}
        with mock.patch.object(c21_api, "_rec", return_value=rec), \
             mock.patch("apps.projects.builder.c21_translate.ai_translate", return_value=(["ساخت سریع‌تر با پلتفرم ما", "قیمت‌ها"], ok_info)):
            out = c21_api.deferred_translate(None, key="lib/x")
        self.assertTrue(out["ai_used"])
        self.assertEqual(out["texts"][0], "ساخت سریع‌تر با پلتفرم ما")
        self.assertEqual(out["old"][1], "قیمت‌ها", "the dictionary already translated «Pricing»")
        self.assertEqual(len(out["seed"].split(",")), 2)
        with mock.patch.object(c21_api, "_rec", return_value=rec), \
             mock.patch("apps.projects.builder.c21_translate.ai_translate", return_value=(list(self.TEXTS), {"ok": False, "parkable": True, "message": "x"})):
            self.assertFalse(c21_api.deferred_translate(None, key="lib/x")["ai_used"])
        with mock.patch.object(c21_api, "_rec", return_value=rec), \
             mock.patch("apps.projects.builder.c21_translate.ai_translate", return_value=(list(self.TEXTS), {"ok": False, "parkable": False, "message": "پاسخِ خراب"})):
            with self.assertRaises(RuntimeError):
                c21_api.deferred_translate(None, key="lib/x")

    def test_the_block_endpoint_queues_the_translation(self):
        from apps.projects import c21_api

        node()
        rec = {"key": "x000000001", "texts": list(self.TEXTS), "links": [], "images": [], "rtl": {}, "title": "t", "id": "x"}
        staff = APIClient()
        staff.force_authenticate(User.objects.create_user("st", password="x", is_staff=True))
        info = {"ok": False, "translated": 0, "message": "گره خاموش", "queued": False, "parkable": True}
        with mock.patch.object(c21_api, "_rec", return_value=rec), mock.patch.object(c21_api.vb, "_project", return_value=mock.Mock()),              mock.patch.object(c21_api.vb, "_guard", return_value=None),              mock.patch("apps.projects.builder.c21_translate.ai_translate", return_value=(list(self.TEXTS), info)):
            res = staff.post("/api/v1/studio/projects/demo/builder/c21/x000000001/block/", {"ai": True}, format="json")
        self.assertEqual(res.status_code, 200, res.content[:300])
        data = res.json()
        self.assertEqual(data["ai"]["queued"]["feature"], "c21.translate")
        self.assertIn("در صف تا روشن شدنِ سرورِ پردازش", data["ai"]["message"])
        self.assertTrue(data["block"], "the block is still inserted with the dictionary translation")
        self.assertEqual(deferred.pending_count(), 1)
        self.assertIsNone(ComputeJob.objects.get(kind=park.PARK_KIND).store_id, "platform-level request")


class ShootPlanTests(Base):
    """برنامهٔ فیلم‌برداری: الگوی آماده همان لحظه، تحلیلِ هوشمند «در صف تا روشن شدنِ سرورِ پردازش»؛ بعداً خودکار جایگزین می‌شود."""

    def setUp(self):
        super().setUp()
        from apps.products.models import Product

        self.product = Product.objects.create(store=self.store, name="دمبلِ تنظیم‌پذیر", is_available=True)

    def session(self):
        from apps.shoot import services

        return services.create_session(self.store, self.product, self.user, purpose="ad", analyze=True)

    def test_an_outage_queues_the_analysis_and_keeps_the_template(self):
        from apps.shoot import plan as planmod, services

        s = self.session()
        tpl = planmod.template_plan(self.product)
        with mock.patch.object(planmod, "analyze", return_value=(tpl, "template", ["تحلیلِ هوش مصنوعی انجام نشد (سرورِ پردازش خاموش است)."])), \
             mock.patch.object(planmod, "last_outage", return_value=True), mock.patch.object(deferred, "defer", return_value={"uid": "u"}) as defer:
            out = services.run_analysis(s)
        defer.assert_called_once()
        self.assertEqual(defer.call_args[0][0], "shoot.plan")
        self.assertEqual(out.plan_source, "template")
        self.assertTrue(any("در صف تا روشن شدنِ سرورِ پردازش" in n for n in out.plan["notes"]))

    def test_no_queue_when_the_failure_is_not_an_outage(self):
        from apps.shoot import plan as planmod, services

        s = self.session()
        tpl = planmod.template_plan(self.product)
        with mock.patch.object(planmod, "analyze", return_value=(tpl, "template", ["x"])), mock.patch.object(planmod, "last_outage", return_value=False), \
             mock.patch.object(deferred, "defer") as defer:
            services.run_analysis(s)
        defer.assert_not_called()

    def test_the_queued_run_replaces_the_template_unless_the_user_started(self):
        from apps.shoot import plan as planmod, services

        s = self.session()
        ai_plan = dict(planmod.template_plan(self.product), notes=["ai"])
        with mock.patch.object(planmod, "analyze", return_value=(ai_plan, "ai", ["تحلیل با هوش مصنوعی."])):
            out = services.deferred_analysis(self.store, session_id=s.pk)
        self.assertTrue(out["ai_used"])
        s.refresh_from_db()
        self.assertEqual(s.plan_source, "ai")
        with mock.patch.object(planmod, "analyze", return_value=(ai_plan, "template", ["x"])):
            self.assertFalse(services.deferred_analysis(self.store, session_id=s.pk)["ai_used"])
        self.assertTrue(services.deferred_analysis(self.store, session_id=99999)["ai_used"], "a deleted session ends the request")
