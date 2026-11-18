# -*- coding: utf-8 -*-
"""دورِ «تعمیر امشب» (۱۴۰۵/۰۸/۲۸): «در صف تا روشن شدنِ سرورِ پردازش» برای فروشگاهِ «فقط لوکال» (چغر) هم کار می‌کند + چند مسیرِ AIِ دیگر که صف نبودند
(نقدِ موشن، سبکِ سفارشیِ موشن، ترند/رقبا، تماسِ موبایل، «محصول پیداست؟»)؛ وضعیتِ ردیف‌های «امشب»؛ قرمزِ کهنهٔ آزمون‌های شبانه."""
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.stores.models import Store

from . import deferred, ops_status, tonight
from . import updates as U
from .models import ComputeJob, ComputeNode
from .tests_deferred import node

User = get_user_model()
QUEUED = "در صف تا روشن شدنِ سرورِ پردازش"


def routed_failure(local="offline", metis="policy"):
    """همان خطایی که مسیریاب می‌انداخت (دو مسیر، هر کدام با علتِ خودش)."""
    from services.ai import routing
    from services.ai.priority import Failure

    return routing.AllProvidersFailed("هیچ‌کدام از دو مسیر جواب ندادند", {"local": Failure(local, "سرورِ پردازش خاموش است", provider="local"),
                                                                           "metis": Failure(metis, "متیس", provider="metis")})


def down_provider(parkable_cause=True):
    """ارائه‌دهنده‌ای که availability آن «نه» می‌گوید و علتِ واقعی را (مثلِ RoutedTextProvider) از unavailable_error می‌دهد."""
    err = routed_failure("offline" if parkable_cause else "no_model", "policy")
    return SimpleNamespace(availability=lambda: (False, "سرورِ پردازش: خاموش است؛ متیس: سیاستِ داده"), unavailable_error=lambda: err,
                           generate=mock.Mock(side_effect=AssertionError("a down provider must never be called")))


class Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-deferred-e-"))
        ctx = override_settings(NM_DATA_DIR=self.tmp, MEDIA_ROOT=str(self.tmp / "media"), AI_DEFER_FORCE=True)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user = User.objects.create_user("owner", password="x")
        self.store = Store.objects.create(owner=self.user, name="چغر آزمایشی")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def only_ticket(self):
        rows = deferred.pending_rows()
        self.assertEqual(len(rows), 1, [r.payload.get("deferred", {}).get("feature") for r in rows])
        return rows[0]

    def run_once(self, ticket, **extra):
        node(online=True, name="gpu-run")
        return deferred.run(ticket["uid"] if isinstance(ticket, dict) else ticket)


# ───────────────────────────── ۱) «توصیف کن، بساز» برای فروشگاهِ «فقط لوکال»

@override_settings(AI_ROUTE_FORCE=True)
class MotionScriptLocalOnlyTests(Base):
    """باگِ اصلی: availability() نه می‌گفت ⇒ AIUnavailable(why) بی‌علت ⇒ parkable=False ⇒ هیچ نوار و صفی نبود (فقط برای فروشگاه‌های «فقط لوکال»)."""

    def setUp(self):
        super().setUp()
        from apps.ai.models import StoreAIPolicy

        StoreAIPolicy.objects.create(store=self.store, mode="LOCAL_ONLY")
        node(online=False, name="DESKTOP-EAFBTGQ")
        from services.ai import gateway

        # get_provider زیرِ آزمون هوشِ واقعی را قطع می‌کند؛ مسیریابِ واقعی (نه ساختگی) را با یک پوششِ Mock رد می‌کنیم
        patcher = mock.patch.object(gateway, "text_provider", wraps=gateway.text_provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    IDEA = "معرفیِ چغر برای مربی‌ها؛ سه مزیت: برنامهٔ ورزشی و غذایی، کتابخانهٔ حرکت‌ها، و دعوت به ثبت‌نام"

    def test_the_real_router_says_the_outage_is_parkable_for_a_local_only_store(self):
        from apps.motion import ai

        prov = ai.get_provider(self.store)
        self.assertIsNone(prov.fallback, "local-only: the Metis path does not exist")
        with self.assertRaises(ai.AIUnavailable) as cm:
            ai.ensure_available(prov)
        self.assertIs(cm.exception.parkable, True)
        self.assertTrue(deferred.is_outage(cm.exception))

    def test_script_from_idea_is_parkable_and_keeps_the_rule_draft(self):
        from apps.motion import ai

        res = ai.script_from_idea(self.store, self.IDEA, style="flat-vector")
        self.assertEqual(res["source"], "rules")
        self.assertIs(res["parkable"], True)
        self.assertTrue(res["spec"]["scenes"])
        self.assertIn("هوش مصنوعی الان در دسترس نیست", res["message"])

    def test_the_view_queues_it_with_the_banner_text(self):
        r = self.client.post(f"/api/v1/stores/{self.store.pk}/motion/ai/", {"idea": self.IDEA, "style": "flat-vector"}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        q = r.json()["queued"]
        self.assertEqual((q["feature"], q["message"]), ("motion.script", QUEUED))
        self.assertEqual(deferred.pending_count(), 1)
        self.assertEqual(self.only_ticket().store_id, self.store.pk)

    def test_a_missing_model_on_an_online_node_is_not_promised_to_wait(self):
        from apps.motion import ai

        state = {"ready": False, "online": True, "has_model": False, "reason": "مدلِ متن روی گره نصب نیست", "wanted": "gemma3:12b", "model": "", "chain": [],
                 "known_models": [], "node": "x"}
        with mock.patch("services.ai.routing.node_state", return_value=state):
            res = ai.script_from_idea(self.store, self.IDEA, style="flat-vector")
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/motion/ai/", {"idea": self.IDEA, "style": "flat-vector"}, format="json")
        self.assertIs(res["parkable"], False, "a missing model needs a person, not patience")
        self.assertNotIn("queued", r.json())
        self.assertEqual(deferred.pending_count(), 0)

    def test_patch_from_chat_still_answers_with_the_rules(self):
        from apps.motion import ai, specs

        spec = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "lang": "fa", "fps": 30, "brand": {}, "scenes": ai.rules_scenes(self.IDEA)})
        res = ai.patch_from_chat(self.store, spec, "تیتر بزرگ‌تر شود")
        self.assertEqual(res["source"], "rules")


class UnavailableErrorTests(TestCase):
    def router(self):
        from services.ai import routing

        return routing.RoutedTextProvider(None, task="t", kind="text", no_fallback_reason="سیاستِ داده اجازه نمی‌دهد")

    @override_settings(AI_ROUTE_FORCE=True)
    def test_node_off_and_metis_forbidden_is_the_same_error_the_call_would_raise(self):
        node(online=False)
        err = self.router().unavailable_error()
        self.assertEqual(type(err).__name__, "AllProvidersFailed")
        self.assertEqual({k: v.kind for k, v in err.failures.items()}, {"local": "offline", "metis": "policy"})
        self.assertTrue(deferred.is_outage(err))

    @override_settings(AI_ROUTE_FORCE=True)
    def test_a_usable_path_means_no_error(self):
        node(online=True)
        state = {"ready": True, "online": True, "has_model": True, "reason": "", "wanted": "gemma3:12b", "model": "qwen3:8b", "chain": ["qwen3:8b"],
                 "known_models": ["qwen3:8b"], "node": "gpu-1"}
        with mock.patch("services.ai.routing.node_state", return_value=state):
            self.assertIsNone(self.router().unavailable_error())
            self.assertEqual(self.router().availability()[0], True)


# ───────────────────────────── ۲) سبکِ سفارشیِ موشن

class MotionStyleTests(Base):
    URL = "/api/v1/stores/%d/motion/custom-styles/describe/"
    GOOD = json.dumps({"name_fa": "سبکِ طلاییِ آزمون", "palette": {"bg": "#101820", "bg2": "#1b2733", "ink": "#f5f1e8", "paper": "#ffffff", "accent": "#d4a84b",
                                                                   "accent2": "#e8c36a", "accent3": "#8a6a1f", "muted": "#9aa5b1"}})

    def test_describe_is_queued_when_both_paths_are_down_and_then_replaced_by_the_model_draft(self):
        from apps.motion import ai

        node(online=False)
        with mock.patch.object(ai, "get_provider", return_value=down_provider()):
            r = self.client.post(self.URL % self.store.pk, {"text": "تیره و سینمایی با رنگِ طلایی، حرکتِ آرام"}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        data = r.json()
        self.assertEqual(data["source"], "rules")
        self.assertEqual(data["queued"]["feature"], "motion.style")
        self.assertIn("contrast", data)
        # the node comes back
        good = SimpleNamespace(availability=lambda: (True, "local"), generate=lambda *a, **k: self.GOOD)
        with mock.patch.object(ai, "get_provider", return_value=good):
            self.assertEqual(self.run_once(data["queued"]), "done")
        done = deferred.status(data["queued"]["uid"])
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["result"]["source"], "ai")
        self.assertIn("contrast", done["result"], "the queued result has the same shape as the synchronous answer")
        self.assertEqual(done["result"]["style"]["name_fa"], "سبکِ طلاییِ آزمون")

    def test_a_non_outage_failure_is_not_queued(self):
        from apps.motion import ai

        node(online=False)
        with mock.patch.object(ai, "get_provider", return_value=down_provider(parkable_cause=False)):
            r = self.client.post(self.URL % self.store.pk, {"text": "تیره و سینمایی"}, format="json")
        self.assertNotIn("queued", r.json())


# ───────────────────────────── ۳) نقدِ تصویریِ موشن

class MotionCritiqueTests(Base):
    def make_plan(self):
        from apps.motion.models import MotionPlan

        from apps.motion import ai, specs

        spec = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "lang": "fa", "fps": 30, "brand": {}, "scenes": ai.rules_scenes("سه مزیت: الف، ب و ج")})
        return MotionPlan.objects.create(store=self.store, user=self.user, title="آزمون", spec=spec, critique={"state": "waiting", "message": "", "started_at": timezone.now().isoformat()})

    def test_no_model_queues_the_critique_durably_and_cancel_clears_it(self):
        from apps.motion import ai, critique

        node(online=False)
        plan = self.make_plan()
        with mock.patch.object(critique.qa_browser, "available", return_value=(True, "")), mock.patch.object(ai, "get_provider", return_value=down_provider()):
            state = critique.run(plan)
        self.assertEqual(state["state"], "waiting")
        self.assertIn(QUEUED, state["message"])
        self.assertTrue(state["queued"]["uid"])
        row = self.only_ticket()
        self.assertEqual(row.payload["deferred"]["feature"], "motion.critique")
        # the 60-second Celery loop is not needed: the durable queue wakes it
        from apps.motion import tasks

        with mock.patch.object(tasks.critique_task, "apply_async") as again, mock.patch.object(critique, "run", return_value=state):
            tasks.critique_task(plan.pk)
        again.assert_not_called()
        # cancel: the plan does not wait for ever
        self.assertTrue(deferred.cancel(row.uid))
        plan.refresh_from_db()
        self.assertEqual(plan.critique["state"], "unavailable")
        self.assertNotIn("queued", plan.critique)

    def test_the_queued_run_stays_queued_while_the_model_is_down_and_finishes_when_it_is_back(self):
        from apps.motion import ai, critique

        node(online=False)
        plan = self.make_plan()
        with mock.patch.object(critique.qa_browser, "available", return_value=(True, "")), mock.patch.object(ai, "get_provider", return_value=down_provider()):
            critique.run(plan)
        row = self.only_ticket()
        node(online=True, name="gpu-run")
        with mock.patch.object(critique.qa_browser, "available", return_value=(True, "")), mock.patch.object(ai, "get_provider", return_value=down_provider()):
            self.assertEqual(deferred.run(row.uid), "requeued")
        self.assertEqual(deferred.pending_count(), 1)
        with mock.patch.object(critique, "run", return_value={"state": "done", "message": "مدلِ بینایی مشکلی ندید."}):
            self.assertEqual(deferred.run(row.uid), "done")
        self.assertEqual(deferred.pending_count(), 0)


# ───────────────────────────── ۴) ترند و رقبا

class TrendResearchTests(Base):
    def llm_down(self, parkable=True):
        from apps.ai import research_llm

        return mock.patch.object(research_llm, "_probe", return_value=(False, "سرورِ پردازش خاموش است", parkable))

    def trend(self):
        from apps.ai.trend_models import Trend

        return Trend.objects.create(title="تمرین در خانه", region="IR", seen_at=timezone.now(), traffic="100+")

    def test_rank_is_queued_with_202_and_runs_when_the_model_is_back(self):
        from apps.ai import research_llm, trends

        node(online=False)
        self.trend()
        with self.llm_down():
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/trends/relevance/", {"regions": ["IR"]}, format="json")
        self.assertEqual(r.status_code, 202, r.content[:300])
        q = r.json()["queued"]
        self.assertEqual(q["feature"], "trends.rank")
        self.assertIn(QUEUED, r.json()["note"])
        with mock.patch.object(trends, "rank_with_llm", return_value={1: {"relevance": 2, "reason": "x"}}):
            self.assertEqual(self.run_once(q), "done")
        self.assertEqual(deferred.status(q["uid"])["result"]["ranked"], 1)
        # while the model is down the run is NOT lost
        with self.llm_down():
            r2 = self.client.post(f"/api/v1/stores/{self.store.pk}/trends/relevance/", {"regions": ["IR", "US"]}, format="json")
            self.assertEqual(deferred.run(r2.json()["queued"]["uid"]), "requeued")

    def test_rank_without_a_parkable_reason_stays_a_503(self):
        node(online=False)
        self.trend()
        with self.llm_down(parkable=False):
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/trends/relevance/", {}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(deferred.pending_count(), 0)

    def test_trend_ideas_keep_the_template_idea_and_queue_the_real_one(self):
        from apps.ai import trends
        from apps.ai.trend_models import TrendIdea
        from apps.products.models import Product

        node(online=False)
        t = self.trend()
        Product.objects.create(store=self.store, name="برنامهٔ تمرین در خانه", price=100000, is_available=True)
        with self.llm_down():
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/trends/ideas/", {"trend_id": t.pk, "regions": ["IR"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        data = r.json()
        self.assertEqual(data["queued"]["feature"], "trends.ideas")
        self.assertIn(QUEUED, data["note"])
        self.assertTrue(TrendIdea.objects.filter(store=self.store).exists(), "the template idea is there now")
        # strict run: no template, the model or nothing
        with self.llm_down(), self.assertRaises(Exception) as cm:
            trends.suggest(self.store, trend_ids=[t.pk], strict=True)
        self.assertTrue(deferred.is_outage(cm.exception))

    def test_instagram_trend_idea_is_queued_and_the_strict_run_refuses_a_template(self):
        from apps.ai import research_llm
        from apps.igtrends import ideas
        from apps.igtrends.models import IgTrendCluster

        node(online=False)
        cluster = IgTrendCluster.objects.create(store=self.store, key="k1", label="تمرین خانگی", fmt="reel")
        with self.llm_down():
            r = self.client.post(f"/api/v1/stores/{self.store.pk}/igtrends/clusters/{cluster.pk}/brief/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.assertEqual(r.json()["queued"]["feature"], "igtrends.brief")
        self.assertEqual(r.json()["source"], "template")
        with self.llm_down(), self.assertRaises(research_llm.LLMUnavailable) as cm:
            ideas.make_idea(self.store, cluster, use_ai=True, strict=True)
        self.assertTrue(deferred.is_outage(cm.exception))

    def test_competitor_check_is_queued_by_the_note_and_strict_run_raises(self):
        from apps.ai import competitor_research, research_llm
        from apps.ai.competitor_models import Competitor, CompetitorProduct
        from apps.products.models import Product

        node(online=False)
        ours = Product.objects.create(store=self.store, name="پروتئین وی ۲ کیلویی", price=900000, is_available=True)
        comp = Competitor.objects.create(store=self.store, name="رقیب", website="https://rival.example")
        row = CompetitorProduct.objects.create(competitor=comp, name="پروتئین whey دو کیلو", price_toman=950000, source="site",
                                               raw={"match": {"our_product_id": ours.pk, "verdict": "maybe"}})
        down = research_llm.LLMUnavailable("خاموش", parkable=True)
        with mock.patch.object(research_llm, "ask_json", side_effect=down):
            out = competitor_research.confirm_with_llm(comp, [row], [ours])
            self.assertIn(QUEUED, out)
            self.assertEqual(deferred.pending_count(), 1)
            with self.assertRaises(research_llm.LLMUnavailable):
                competitor_research.confirm_with_llm(comp, [row], [ours], strict=True)
        # not an outage (a wrong key ...): no promise
        for r in deferred.pending_rows():
            deferred.cancel(r.uid)
        with mock.patch.object(research_llm, "ask_json", side_effect=research_llm.LLMUnavailable("کلید نادرست", parkable=False)):
            self.assertNotIn(QUEUED, competitor_research.confirm_with_llm(comp, [row], [ours]))
        self.assertEqual(deferred.pending_count(), 0)


# ───────────────────────────── ۵) تماسِ موبایل

class MobileCallTests(Base):
    def make_call(self, tmpdir):
        from apps.mobile.models import MobileCall, MobileSettings

        s = MobileSettings.get()
        s.asr_enabled = True
        s.save()
        audio = Path(tmpdir) / "rec.m4a"
        audio.write_bytes(b"x" * 64)
        call = MobileCall.objects.create(number="989121234567", direction="in", status=MobileCall.Status.UPLOADED, user=self.user)
        return call, audio

    def test_asr_down_queues_the_call_and_the_queued_run_finishes_it(self):
        from apps.mobile import asr, calls, notes, tasks
        from apps.mobile.models import MobileCall

        node(online=False)
        call, audio = self.make_call(self.tmp)
        down = asr.AsrUnavailable("سرورِ پردازش خاموش است", parkable=True)
        with mock.patch.object(calls, "audio_file", return_value=audio), mock.patch.object(tasks.asr, "transcribe", side_effect=down):
            self.assertEqual(tasks.process(call.pk), "asr_queued")
        call.refresh_from_db()
        self.assertEqual((call.status, call.error), (MobileCall.Status.UPLOADED, tasks.PARKED_TEXT))
        self.assertIn(QUEUED, tasks.PARKED_TEXT)
        row = self.only_ticket()
        self.assertIsNone(row.store_id, "platform level: the phone app's store is the device's")
        # node back: transcribe + notes by themselves
        data = {"summary": "خلاصه", "sentiment": "POSITIVE", "objections": [], "commitments": [], "next_steps": ["پیگیری"]}
        with mock.patch.object(calls, "audio_file", return_value=audio), mock.patch.object(tasks.asr, "transcribe", return_value={"text": "سلام", "segments": [], "engine": "node"}), \
                mock.patch.object(notes, "analyse", return_value=data):
            self.assertEqual(self.run_once(row.uid), "done")
        call.refresh_from_db()
        self.assertEqual((call.status, call.summary, call.error), (MobileCall.Status.ANALYSED, "خلاصه", ""))

    def test_a_broken_audio_file_is_a_failure_not_a_promise(self):
        from apps.mobile import asr, calls, tasks
        from apps.mobile.models import MobileCall

        node(online=False)
        call, audio = self.make_call(self.tmp)
        bad = asr.AsrUnavailable("فایلِ صدا خوانده نشد (خراب یا ناشناخته).", parkable=False, file_problem=True)
        with mock.patch.object(calls, "audio_file", return_value=audio), mock.patch.object(tasks.asr, "transcribe", side_effect=bad):
            self.assertEqual(tasks.process(call.pk), "asr_failed")
        call.refresh_from_db()
        self.assertEqual(call.status, MobileCall.Status.FAILED)
        self.assertEqual(deferred.pending_count(), 0)

    def test_transcribe_marks_a_waiting_node_parkable_and_a_file_problem_not(self):
        from apps.mobile import asr

        waiting = asr.AsrUnavailable("x", parkable=True)
        broken = asr.AsrUnavailable("y", parkable=False, file_problem=True)
        policy = asr.AsrUnavailable("z", parkable=False)
        with mock.patch.object(asr, "_local", side_effect=waiting), mock.patch.object(asr, "_metis", side_effect=policy):
            with self.assertRaises(asr.AsrUnavailable) as cm:
                asr.transcribe(self.tmp / "a.m4a")
        self.assertIs(cm.exception.parkable, True)
        with mock.patch.object(asr, "_local", side_effect=broken), mock.patch.object(asr, "_metis", side_effect=waiting):
            with self.assertRaises(asr.AsrUnavailable) as cm:
                asr.transcribe(self.tmp / "a.m4a")
        self.assertIs(cm.exception.parkable, False, "an unreadable file does not get better with waiting")

    def test_notes_down_after_a_good_transcript_queues_only_the_notes(self):
        from apps.mobile import asr, calls, notes, tasks
        from apps.mobile.models import MobileCall

        node(online=False)
        call, audio = self.make_call(self.tmp)
        err = notes.NotesUnavailable("خاموش")
        err.__cause__ = routed_failure()
        with mock.patch.object(calls, "audio_file", return_value=audio), mock.patch.object(tasks.asr, "transcribe", return_value={"text": "سلام", "segments": [], "engine": "node"}), \
                mock.patch.object(notes, "analyse", side_effect=err):
            self.assertEqual(tasks.process(call.pk), "notes_queued")
        call.refresh_from_db()
        self.assertEqual((call.status, call.transcript), (MobileCall.Status.TRANSCRIBED, "سلام"))
        self.assertEqual(deferred.pending_count(), 1)

    def test_cancel_does_not_leave_the_call_waiting(self):
        from apps.mobile import asr, calls, tasks
        from apps.mobile.models import MobileCall

        node(online=False)
        call, audio = self.make_call(self.tmp)
        with mock.patch.object(calls, "audio_file", return_value=audio), mock.patch.object(tasks.asr, "transcribe", side_effect=asr.AsrUnavailable("x", parkable=True)):
            tasks.process(call.pk)
        self.assertTrue(deferred.cancel(self.only_ticket().uid))
        call.refresh_from_db()
        self.assertEqual(call.status, MobileCall.Status.FAILED)
        self.assertIn("لغو", call.error)


# ───────────────────────────── ۶) «محصول پیداست؟»

class ShootVisionTests(Base):
    def session(self):
        from apps.products.models import Product
        from apps.shoot import services

        product = Product.objects.create(store=self.store, name="قهوهٔ عربیکا", price=250000, description="دانهٔ تازه")
        return services.create_session(self.store, product, self.user, purpose="photos", analyze=False)

    def upload(self, session, keep=None):
        from apps.shoot import services
        from apps.shoot.tests import make_photo

        shot = session.plan["photos"][0]
        part = make_photo(self.tmp / "p.jpg")
        return services._finalize_photo(session, part, shot, "upload", True), shot

    def test_vision_down_keeps_the_size_checks_and_queues_the_product_check(self):
        from apps.shoot import checks

        node(online=False)
        session = self.session()
        with mock.patch.object(checks, "vision_probe", return_value=(None, True)):
            take, _shot = self.upload(session)
        self.assertTrue(take.ok and take.accepted, "the take is usable now")
        self.assertTrue(take.checks["vision_pending"])
        self.assertIn(QUEUED, take.checks["summary"])
        self.assertIn(QUEUED, take.checks["where"])
        self.assertEqual(self.only_ticket().payload["deferred"]["params"], {"take_id": take.pk})
        from apps.shoot import services

        self.assertTrue(services.take_dict(take)["vision_pending"])

    def test_the_late_answer_flips_a_take_that_does_not_show_the_product(self):
        from apps.shoot import checks, services

        node(online=False)
        session = self.session()
        with mock.patch.object(checks, "vision_probe", return_value=(None, True)):
            take, _ = self.upload(session)
        row = self.only_ticket()
        # still down: stays queued
        node(online=True, name="gpu-run")
        with mock.patch.object(checks, "vision_probe", return_value=(None, True)):
            self.assertEqual(deferred.run(row.uid), "requeued")
        take.refresh_from_db()
        self.assertTrue(take.checks["vision_pending"])
        # back: the model says the product is not in the picture
        vis = {"product_visible": False, "centered": True, "angle_ok": True, "verdict": "retake", "problems": ["محصول در عکس نیست"]}
        with mock.patch.object(checks, "vision_probe", return_value=(vis, False)):
            self.assertEqual(deferred.run(row.uid), "done")
        take.refresh_from_db()
        self.assertFalse(take.checks["vision_pending"])
        self.assertFalse(take.ok)
        self.assertFalse(take.accepted)
        self.assertIn("ai_not_visible", [p["code"] for p in take.checks["problems"]])
        self.assertEqual(take.checks["vision"]["product_visible"], False)
        self.assertNotIn(QUEUED, take.checks["summary"])
        self.assertEqual(services.take_dict(take)["vision_pending"], False)

    def test_cancel_removes_the_pending_mark_and_keeps_the_size_checks(self):
        from apps.shoot import checks

        node(online=False)
        session = self.session()
        with mock.patch.object(checks, "vision_probe", return_value=(None, True)):
            take, _ = self.upload(session)
        self.assertTrue(deferred.cancel(self.only_ticket().uid))
        take.refresh_from_db()
        self.assertFalse(take.checks["vision_pending"])
        self.assertTrue(take.ok and take.accepted)
        self.assertNotIn(QUEUED, take.checks["summary"])

    def test_no_queue_when_the_vision_failure_is_not_an_outage(self):
        from apps.shoot import checks

        node(online=False)
        session = self.session()
        with mock.patch.object(checks, "vision_probe", return_value=(None, False)):
            take, _ = self.upload(session)
        self.assertFalse(take.checks.get("vision_pending"))
        self.assertEqual(deferred.pending_count(), 0)

    def test_vision_probe_reports_an_outage_from_the_router_error(self):
        from apps.shoot import checks
        from services.ai import gateway

        err = routed_failure()
        prov = SimpleNamespace(generate_json=mock.Mock(side_effect=err))
        node(online=False)
        with mock.patch.object(gateway, "vision_provider", return_value=prov), mock.patch("apps.ai.services._models_for_provider", return_value=["qwen3-vl:30b"]):
            img = Image.new("RGB", (64, 64), "white")
            vis, outage = checks.vision_probe(self.store, img, product_name="x", shot={"title": "t", "instruction": "i"}, use_flag=False)
        self.assertEqual((vis, outage), (None, True))


# ───────────────────────────── ۷) ردیف‌های «امشب» + قرمزِ کهنهٔ آزمون‌های شبانه

class TonightStatusTests(Base):
    def setUp(self):
        super().setUp()
        self.latest = mock.patch.object(U, "latest", return_value={"version": "2.35", "id": "abc", "size": 1, "built": ""})
        self.latest.start()
        self.addCleanup(self.latest.stop)

    def rows(self, **kw):
        r = tonight.build(kw.get("pk"))
        return {s["key"]: s for s in r["steps"]}, r

    def test_node_off_with_waiting_jobs_is_waiting_not_in_progress(self):
        ComputeNode.objects.create(name="DESKTOP-EAFBTGQ", capabilities={"agent": "2.10"}, last_seen=timezone.now() - timedelta(days=5))
        ComputeJob.objects.create(kind="comfy.graph", state=ComputeJob.State.QUEUED, queued_at=timezone.now())
        steps, r = self.rows()
        self.assertEqual(steps["queue"]["state"], "waiting")
        self.assertIn("منتظرِ روشن شدنِ سرورِ پردازش", steps["queue"]["detail"])
        self.assertEqual([q["state"] for q in r["queue"] if q["kind"] == "comfy.graph"], ["waiting"])

    def test_empty_ai_queue_is_green_only_when_something_can_answer_or_ran(self):
        ComputeNode.objects.create(name="DESKTOP-EAFBTGQ", capabilities={"agent": "2.10"}, last_seen=timezone.now() - timedelta(days=5))
        with mock.patch.object(deferred, "ai_ready", return_value=(False, "")), mock.patch.object(deferred, "recent_done_count", return_value=0):
            steps, _ = self.rows()
        self.assertEqual(steps["ai_queue"]["state"], "waiting")
        self.assertIn(QUEUED, steps["ai_queue"]["detail"])
        with mock.patch.object(deferred, "ai_ready", return_value=(False, "")), mock.patch.object(deferred, "recent_done_count", return_value=2):
            steps, _ = self.rows()
        self.assertEqual(steps["ai_queue"]["state"], "done")
        with mock.patch.object(deferred, "ai_ready", return_value=(True, "local")), mock.patch.object(deferred, "recent_done_count", return_value=0):
            steps, _ = self.rows()
        self.assertEqual(steps["ai_queue"]["state"], "done")

    def test_queued_requests_while_nothing_can_answer_are_waiting(self):
        node(online=False)
        deferred.defer("thumbs.ideas", self.store, {"topic": "x"}, user=self.user)
        with mock.patch.object(deferred, "ai_ready", return_value=(False, "")):
            steps, _ = self.rows()
        self.assertEqual(steps["ai_queue"]["state"], "waiting")
        self.assertEqual(steps["ai_queue"]["pending"], 1)

    def write_motion_manifest(self):
        d = self.tmp / "up3d" / "downloads"
        d.mkdir(parents=True)
        (d / "nm-motion-pack.json").write_text(json.dumps({"version": "x", "pack": {"name": "p.zip", "size": 80_000_000}, "node": {"name": "n.zip", "size": 30_000_000},
                                                           "browser": {"name": "b.zip", "size": 60_000_000}}), encoding="utf-8")

    def test_the_motion_bundle_is_one_of_the_planned_installs(self):
        self.write_motion_manifest()
        plan = tonight.planned_features()
        motion = [f for f in plan if f["feature"] == "motion"]
        self.assertEqual(len(motion), 1)
        self.assertEqual(motion[0]["bytes"], 170_000_000)
        self.assertEqual(motion[0]["kinds"], ["motion.render"])
        self.assertEqual([f["order"] for f in plan], sorted(f["order"] for f in plan))
        ComputeNode.objects.create(name="DESKTOP-EAFBTGQ", capabilities={"agent": "2.10"}, last_seen=timezone.now() - timedelta(days=5))
        r = tonight.build()
        keys = [i["key"] for i in r["installs"]]
        self.assertIn("install:motion", keys)
        self.assertEqual(len(keys), len(plan))
        self.assertIn(tonight.fa(len(plan)), r["checklist"][2]["detail"])

    def test_an_old_agent_without_the_motion_module_still_shows_the_row(self):
        self.write_motion_manifest()
        n = ComputeNode.objects.create(name="DESKTOP-EAFBTGQ", capabilities={"agent": "2.10", "bootstrap": {"v": 1, "features": {"crawl": {"title": "x", "state": "ready", "kinds": [], "applicable": True,
                                                                                                                                              "why": "", "items": []}}}},
                                       last_seen=timezone.now())
        r = tonight.build(n.pk)
        row = [i for i in r["installs"] if i["key"] == "install:motion"]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["state"], "todo")


class NightlyOutdatedTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-ops-"))
        ctx = override_settings(NM_DATA_DIR=self.tmp, OPS_RERUN_FORCE=True)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.script = self.tmp / "nm-nightly-tests"
        self.script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        env = mock.patch.dict("os.environ", {"NM_NIGHTLY_SCRIPT": str(self.script)})
        env.start()
        self.addCleanup(env.stop)
        ver = mock.patch.object(ops_status, "current_version", return_value="3.60")
        ver.start()
        self.addCleanup(ver.stop)

    def report(self, version="3.53", app_version=None, red=True):
        iso = (datetime.now(dt_timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        app = {"app": "design_studio", "ok": not red, "tests": 88, "failures": 2 if red else 0, "errors": 1 if red else 0, "skipped": 0, "seconds": 300,
               "red": [{"id": "t", "kind": "fail", "message": "m"}] if red else []}
        if app_version:
            app["version"] = app_version
        (self.tmp / "test-report.json").write_text(json.dumps({"started_at": iso, "finished_at": iso, "version": version, "apps": [app, {"app": "jobs", "ok": True, "tests": 5, "failures": 0,
                                                                                                                                          "errors": 0, "skipped": 0, "seconds": 3, "red": []}],
                                                                "totals": {"apps": 2, "red_apps": 1 if red else 0, "tests": 93, "failures": 2 if red else 0, "errors": 1 if red else 0,
                                                                           "skipped": 0}}), encoding="utf-8")

    def test_red_from_an_older_version_is_outdated_not_red(self):
        self.report("3.53")
        s = ops_status.test_status()
        self.assertEqual(s["state"], "outdated")
        self.assertEqual(s["rerun"]["apps"], ["design_studio"])
        self.assertEqual(s["current_version"], "3.60")

    def test_red_from_the_current_version_stays_red(self):
        self.report("3.60")
        self.assertEqual(ops_status.test_status()["state"], "red")
        self.report("3.53", app_version="3.60")                      # merged report: this app was re-tested on the current version and is still red
        self.assertEqual(ops_status.test_status()["state"], "red")

    def test_green_stays_green(self):
        self.report("3.53", red=False)
        self.assertEqual(ops_status.test_status()["state"], "green")

    def test_the_rerun_starts_once_per_version_with_only_the_red_apps(self):
        self.report("3.53")
        with mock.patch.object(ops_status.shutil, "which", return_value=None), mock.patch.object(ops_status.subprocess, "Popen") as popen:
            first = ops_status.maybe_rerun_red()
            second = ops_status.maybe_rerun_red()
        self.assertEqual(first, {"started": True, "apps": ["design_studio"]})
        self.assertEqual((second["started"], second["why"]), (False, "already-tried"))
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(popen.call_args.kwargs["env"]["NM_NIGHTLY_APPS"], "design_studio")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertTrue(ops_status.test_status()["rerun"]["started"])

    def test_it_uses_a_separate_systemd_unit_so_a_deploy_restart_does_not_kill_it(self):
        self.report("3.53")
        with mock.patch.object(ops_status.shutil, "which", return_value="/usr/bin/systemd-run"), mock.patch.object(ops_status.subprocess, "run") as run:
            self.assertTrue(ops_status.maybe_rerun_red()["started"])
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "/usr/bin/systemd-run")
        self.assertIn("--setenv=NM_NIGHTLY_APPS=design_studio", cmd)
        self.assertEqual(cmd[-1], str(self.script))

    def test_nothing_starts_when_green_running_current_or_the_script_is_missing(self):
        self.report("3.53", red=False)
        self.assertEqual(ops_status.maybe_rerun_red()["why"], "not-outdated")
        self.report("3.60")
        self.assertEqual(ops_status.maybe_rerun_red()["why"], "not-outdated")
        self.report("3.53")
        (self.tmp / "test-report.json.running").write_text(json.dumps({"app": "jobs", "since": "x"}), encoding="utf-8")
        self.assertEqual(ops_status.maybe_rerun_red()["why"], "running")
        (self.tmp / "test-report.json.running").unlink()
        self.script.unlink()
        self.assertEqual(ops_status.maybe_rerun_red()["why"], "no-script")

    def test_a_failed_spawn_does_not_burn_the_one_chance(self):
        self.report("3.53")
        with mock.patch.object(ops_status.shutil, "which", return_value=None), mock.patch.object(ops_status.subprocess, "Popen", side_effect=OSError("boom")):
            self.assertFalse(ops_status.maybe_rerun_red()["started"])
        with mock.patch.object(ops_status.shutil, "which", return_value=None), mock.patch.object(ops_status.subprocess, "Popen"):
            self.assertTrue(ops_status.maybe_rerun_red()["started"])

    def test_test_mode_never_spawns(self):
        self.report("3.53")
        with override_settings(OPS_RERUN_FORCE=False):
            self.assertEqual(ops_status.maybe_rerun_red()["why"], "test-mode")


# ───────────────────────────── ۸) هر ویژگیِ صف‌دار ثبت و به view وصل است (قراردادِ دورِ تازه)

class RegistryTests(TestCase):
    NEW = ("motion.style", "motion.critique", "trends.rank", "trends.ideas", "igtrends.brief", "competitor.confirm", "mobile.call", "shoot.vision")

    def test_new_features_are_registered_with_labels_and_functions_that_exist(self):
        import inspect

        for key in self.NEW:
            spec = deferred.FEATURES[key]
            self.assertTrue(spec["label"], key)
            fn = deferred._resolve(spec["fn"])
            params = inspect.signature(fn).parameters
            self.assertIn("_user_id", params, key)
            if spec.get("on_end"):
                self.assertTrue(callable(deferred._resolve(spec["on_end"])), key)
        self.assertTrue(deferred.FEATURES["mobile.call"]["platform"])

    def test_sentence_for_the_owner_is_the_same_everywhere(self):
        self.assertEqual(deferred.UI_TEXT, QUEUED)
