# -*- coding: utf-8 -*-
"""مدل‌های لوکال (۱۴۰۵/۰۸/۱۲): متنِ روزمره ≠ پژوهش، زنجیرهٔ جایگزین پیش از متیس، و «دانلود مدل» از پنل.

⚠ هیچ‌چیز به متیس یا گرهٔ واقعی وصل نمی‌شود: لوکال provider ساختگی است، «گره» یک APIClient با توکنِ گره است (همان پروتکلِ
heartbeat / claim / progress / finish) و صفِ کارها پوشهٔ موقتِ خودش را دارد.
"""
import importlib
import inspect
import os
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.stores.models import Store
from services.ai import model_catalog, model_pull, priority, routing, status
from services.ai.ollama import OllamaError, OllamaProvider, OllamaTimeout
from services.ai.router import TASK_REASONING, TASK_RESEARCH, TASK_VISION, configured_model, models_for

from .models import AiPriority, AiProviderState, AIRequest
from .services import recorded_json_call
from .tests_priority import Base, FakeLocal, FakeMetis, with_conf

GEMMA, QWEN14, QWQ, CODER, VL = "gemma3:12b", "qwen3:14b", "qwq:32b", "qwen3-coder:30b", "qwen3-vl:30b"


class SeqLocal(FakeLocal):
    """a node whose Ollama answers «model not found» for the models in `missing` (what a stale model list looks like)."""

    def __init__(self, missing=()):
        super().__init__()
        self.missing = set(missing)

    def generate(self, model, prompt, **kw):
        self.calls.append(("generate", model, kw))
        if model in self.missing:
            raise OllamaError('Ollama روی سرورِ پردازش خطا داد (model=%s): model "%s" not found (404)' % (model, model))
        return "جواب " + model


# ──────────────────────────────────────────────────────── فهرست و فهرستِ مجاز

class CatalogTests(SimpleTestCase):
    def test_only_catalogued_tags_may_be_pulled(self):
        for tag in (GEMMA, QWEN14, QWQ, CODER, VL, "qwen3:8b"):
            self.assertTrue(model_catalog.is_pullable(tag), tag)
        for bad in ("evil:1", "gemma3:12b; rm -rf /", "", "../x:y", "gemma3", "gemma3:12b ", "http://x/y:1", "a b:c", None):
            self.assertFalse(model_catalog.is_pullable(bad), repr(bad))

    def test_sizes_are_the_registry_manifest_sizes(self):
        """مگابایتِ ۱۰۰۰۰۰۰ تایی، جمعِ لایه‌های manifest ِ registry.ollama.ai در ۱۴۰۵/۰۸/۱۲ (همان بایتی که دانلود می‌شود)."""
        want = {GEMMA: 8164, QWEN14: 9276, QWQ: 19851, CODER: 18557, VL: 19595, "qwen3:8b": 5225}
        self.assertEqual({t: model_catalog.info(t)["size_mb"] for t in want}, want)
        self.assertEqual(model_catalog.info("nope:1"), {})

    def test_chains_start_with_the_choice_and_have_no_repeats(self):
        for kind in priority.KINDS:
            chain = model_catalog.chain_for(kind, "mine:1b")
            self.assertEqual(chain[0], "mine:1b")
            self.assertEqual(len(chain), len(set(chain)))
        self.assertEqual(model_catalog.chain_for(priority.TEXT, GEMMA)[:4], [GEMMA, QWEN14, "qwen3:8b", QWQ])
        self.assertEqual(model_catalog.chain_for(priority.RESEARCH, QWQ)[:2], [QWQ, QWEN14])
        self.assertEqual(model_catalog.chain_for(priority.CODE, CODER)[0], CODER)
        # بینایی فقط مدلِ بینا (قابِ متنیِ qwq به عکس نگاه نمی‌کند)
        self.assertNotIn(QWQ, model_catalog.chain_for(priority.VISION, VL))
        self.assertNotIn(QWQ, model_catalog.chain_for(priority.CODE, CODER))      # too slow for a whole site
        self.assertEqual(model_catalog.chain_for(priority.TEXT, QWQ)[0], QWQ)

    def test_request_profile(self):
        self.assertEqual(model_catalog.request_profile(QWEN14), {"think": False, "num_ctx_max": 8192})
        self.assertEqual(model_catalog.request_profile("qwen3:8b"), {"think": False})
        self.assertEqual(model_catalog.request_profile(GEMMA), {"num_ctx_max": 8192})     # no think switch, only a window cap
        self.assertEqual(model_catalog.request_profile(VL), {"think": False})      # vision answers without thinking (08/21)
        for tag in (QWQ, CODER, "gemma3:4b", "qwen3:30b-a3b-instruct-2507-q4_K_M", "", None):
            self.assertEqual(model_catalog.request_profile(tag), {}, tag)

    def test_extra_models_from_the_environment(self):
        with mock.patch.dict(os.environ, {"NM_AI_PULLABLE_EXTRA": "llama3.2:3b=2000, bad tag=1 ,../x:y=5,qwq:32b=1"}):
            self.assertTrue(model_catalog.is_pullable("llama3.2:3b"))
            self.assertEqual(model_catalog.info("llama3.2:3b")["size_mb"], 2000)
            self.assertFalse(model_catalog.is_pullable("bad tag"))
            self.assertFalse(model_catalog.is_pullable("../x:y"))
            self.assertEqual(model_catalog.info(QWQ)["size_mb"], 19851)       # the catalogue wins over the environment
        self.assertFalse(model_catalog.is_pullable("llama3.2:3b"))


# ──────────────────────────────────────────────────────── نگاشتِ نوعِ کار ⇒ مدل

class MappingTests(TestCase):
    def test_four_kinds_and_their_defaults(self):
        self.assertEqual(priority.KINDS, (priority.TEXT, priority.RESEARCH, priority.CODE, priority.VISION))
        self.assertEqual(priority.DEFAULT_MODELS, {"text": GEMMA, "research": QWQ, "code": CODER, "vision": VL})
        silent = {**with_conf(), "MODEL_TEXT": "", "MODEL_CODER": "", "MODEL_REASONING": "", "MODEL_VISION": ""}
        with override_settings(UPMARKET_AI=silent):
            self.assertEqual({k: priority.local_model(k, priority.Config()) for k in priority.KINDS},
                             {"text": GEMMA, "research": QWQ, "code": CODER, "vision": VL})

    def test_task_types(self):
        self.assertEqual(priority.kind_of_task("REASONING"), priority.TEXT)
        self.assertEqual(priority.kind_of_task("RESEARCH"), priority.RESEARCH)
        self.assertEqual(priority.kind_of_task("CODE"), priority.CODE)
        self.assertEqual(priority.kind_of_task("VISION"), priority.VISION)
        with override_settings(UPMARKET_AI={**with_conf(), "MODEL_TEXT": "", "MODEL_REASONING": QWQ}):
            self.assertEqual(configured_model("REASONING"), GEMMA)
            self.assertEqual(configured_model("RESEARCH"), QWQ)
        with self.assertRaises(ValueError):
            configured_model("NOPE")

    def test_the_owners_pick_goes_first_per_kind(self):
        row = AiPriority.get()
        row.model_text, row.model_research = QWEN14, "mine:7b"
        row.save()
        self.assertEqual(models_for(TASK_REASONING)[0], QWEN14)
        self.assertEqual(models_for(TASK_RESEARCH)[0], "mine:7b")
        cfg = priority.config()
        self.assertEqual(cfg.models[priority.RESEARCH], "mine:7b")

    def test_research_has_its_own_order_override(self):
        row = AiPriority.get()
        row.priority = "local_first"
        row.priority_research = "metis_first"
        row.save()
        cfg = priority.config()
        self.assertEqual(cfg.order(priority.RESEARCH), [priority.METIS, priority.LOCAL])
        self.assertEqual(cfg.order(priority.TEXT), [priority.LOCAL, priority.METIS])

    def test_the_stored_default_migration_fills_only_blank_fields(self):
        mig = importlib.import_module("apps.ai.migrations.0020_ai_default_models")
        from django.apps import apps as registry

        row = AiPriority.get()
        row.model_text, row.model_research, row.model_code, row.model_vision = "", "", "", ""
        row.save()
        mig.forwards(registry, None)
        row.refresh_from_db()
        self.assertEqual((row.model_text, row.model_research, row.model_code, row.model_vision), (GEMMA, QWQ, CODER, VL))

        # a choice the owner made by hand is never overwritten — not even one that equals an old default
        row.model_text, row.model_code, row.model_research = QWQ, "mine:14b", ""
        row.save()
        mig.forwards(registry, None)
        row.refresh_from_db()
        self.assertEqual(row.model_text, QWQ)
        self.assertEqual(row.model_code, "mine:14b")
        self.assertEqual(row.model_research, QWQ)
        self.assertEqual(row.model_vision, VL)

    def test_the_migration_creates_the_row_when_there_is_none(self):
        mig = importlib.import_module("apps.ai.migrations.0020_ai_default_models")
        from django.apps import apps as registry

        AiPriority.objects.all().delete()
        mig.forwards(registry, None)
        row = AiPriority.objects.get(pk=1)
        self.assertEqual((row.model_text, row.model_research), (GEMMA, QWQ))


# ──────────────────────────────────────────────────────── زنجیرهٔ جایگزین پیش از متیس

class ChainTests(Base):
    def setUp(self):
        super().setUp()
        user = get_user_model().objects.create_user("chain-user", "c@x.ir", "pw-12345")
        self.store = Store.objects.create(owner=user, name="chain-shop")

    def test_nothing_changes_when_the_chosen_model_is_installed(self):
        self.node(models=(GEMMA, QWQ, VL, CODER))
        st = routing.node_state("text")
        self.assertEqual((st["model"], st["substitute"], st["wanted"]), (GEMMA, "", GEMMA))
        self.assertIs(st["wanted_installed"], True)
        self.assertTrue(st["ready"])

    def test_the_next_installed_model_of_the_chain_stands_in(self):
        self.node(models=(QWQ, VL, CODER))               # exactly the three the owner was thought to have
        st = routing.node_state("text")
        self.assertEqual(st["model"], QWQ)
        self.assertEqual(st["substitute"], QWQ)
        self.assertIs(st["has_model"], True)
        self.assertIs(st["wanted_installed"], False)
        self.assertTrue(st["ready"])
        self.assertEqual(st["chain"][:4], [GEMMA, QWEN14, "qwen3:8b", QWQ])
        self.node(models=(QWEN14, QWQ), name="gpu-2")    # a second node does not change the order of preference
        self.assertEqual(routing.node_state("text")["model"], QWEN14)

    def test_each_kind_has_its_own_chain(self):
        self.node(models=(QWQ,))
        self.assertEqual(routing.node_state("research")["substitute"], "")           # qwq IS the research model
        code = routing.node_state("code")                                            # a whole site from qwq would time out: no stand-in
        self.assertIs(code["has_model"], False)
        self.assertFalse(code["ready"])
        self.node(models=(QWEN14,), name="gpu-3")
        self.assertEqual(routing.node_state("code")["model"], QWEN14)                # qwen3:14b (no thinking) can stand in
        ComputeNode.objects.filter(name="gpu-3").delete()
        vision = routing.node_state("vision")
        self.assertIs(vision["has_model"], False)                                     # qwq cannot read photos
        self.assertFalse(vision["ready"])
        self.assertIn(VL, vision["reason"])
        self.node(models=(GEMMA,), name="gpu-2")
        self.assertEqual(routing.node_state("vision")["model"], GEMMA)               # gemma 3 is multimodal

    def test_no_model_of_the_chain_installed(self):
        self.node(models=("llama3:8b",))
        st = routing.node_state("text")
        self.assertIs(st["has_model"], False)
        self.assertFalse(st["ready"])
        self.assertIn(GEMMA, st["reason"])
        self.assertIn("جایگزین", st["reason"])

    def test_the_list_of_an_off_node_still_counts_but_is_marked_offline(self):
        self.node(models=(QWQ,), online=False)
        st = routing.node_state("text")
        self.assertFalse(st["online"])
        self.assertEqual(st["substitute"], QWQ)
        self.assertIs(st["wanted_installed"], False)
        self.assertTrue(st["models_reported_at"])

    def test_unknown_list_does_not_block(self):
        ComputeNode.objects.create(name="gpu-1", enabled=True, capabilities={"ollama": True},
                                   last_seen=timezone.now())
        st = routing.node_state("text")
        self.assertTrue(st["ready"])
        self.assertIsNone(st["has_model"])
        self.assertEqual(st["model"], GEMMA)

    def test_the_substitute_answers_locally_and_says_so(self):
        self.node(models=(QWQ, VL, CODER))
        local, metis = FakeLocal(), FakeMetis()
        p = self.routed(metis)
        with self.local_patch(local) as m:
            self.assertEqual(p.generate(GEMMA, "سلام"), "جواب لوکال")
        self.assertEqual(metis.calls, [])                                   # the owner's priority: local stays first
        self.assertEqual(local.calls[0][1], QWQ)
        self.assertEqual(m.call_args.kwargs["model"], QWQ)
        self.assertEqual((p.answered_via, p.answered_by, p.fell_back), ("local", QWQ, False))
        self.assertEqual(p.answered_label, "لوکال (qwq:32b)")
        self.assertIn(GEMMA, p.model_note)
        self.assertIn(QWQ, p.model_note)
        self.assertEqual(p.describe()["model_note"], p.model_note)

    def test_the_audit_row_records_the_stand_in(self):
        self.node(models=(QWQ,))
        p = self.routed(FakeMetis())
        with self.local_patch(FakeLocal()):
            parsed, row = recorded_json_call(
                store=self.store, task_type=AIRequest.TaskType.REASONING, prompt_id="x", prompt_version="1",
                provider=p, models=models_for(TASK_REASONING), prompt="p")
        self.assertEqual(parsed, {"from": "local"})
        self.assertEqual((row.via, row.model, row.fell_back), ("local", QWQ, False))
        self.assertIn(GEMMA, row.fallback_reason)
        self.assertEqual(row.answer_label, "لوکال (qwq:32b)")

    def test_no_note_when_the_chosen_model_answers(self):
        self.node(models=(GEMMA,))
        p = self.routed(FakeMetis())
        with self.local_patch(FakeLocal()):
            p.generate(GEMMA, "x")
        self.assertEqual(p.model_note, "")

    def test_a_failing_stand_in_falls_to_metis_and_trips_its_own_circuit(self):
        self.node(models=(QWQ,))
        metis = FakeMetis()
        p = self.routed(metis)
        with self.local_patch(FakeLocal(exc=OllamaTimeout("سرورِ پردازش در 420 ثانیه جوابِ مدل را نداد."))):
            self.assertEqual(p.generate(GEMMA, "x"), "جواب متیس")
        self.assertTrue(p.fell_back)
        keys = set(AiProviderState.objects.values_list("key", flat=True))
        self.assertIn("local:" + QWQ, keys)            # the model that actually failed
        self.assertNotIn("local:" + GEMMA, keys)

    def test_metis_only_when_no_model_of_the_chain_is_installed(self):
        self.node(models=("llama3:8b",))
        metis = FakeMetis()
        p = self.routed(metis)
        with self.local_patch(FakeLocal()) as m:
            self.assertEqual(p.generate(GEMMA, "x"), "جواب متیس")
        m.assert_not_called()
        self.assertIn("نصب نیست", p.fallback_reason)

    def test_the_owners_metis_first_order_is_untouched(self):
        self.node(models=(QWQ,))
        self.setting(priority="metis_first")
        local, metis = FakeLocal(), FakeMetis()
        p = self.routed(metis)
        with self.local_patch(local):
            self.assertEqual(p.generate("x", "y"), "جواب متیس")
        self.assertEqual(local.calls, [])

    # ---- فهرستِ کهنه: گره می‌گوید «مدل نیست» ⇒ مدلِ بعدیِ نصب‌شده، پیش از متیس

    def test_a_stale_list_gemma_is_not_really_there_so_the_next_model_answers_and_gemma_rests(self):
        self.node(models=(GEMMA, QWQ))                     # the list says gemma is installed ...
        local, metis = SeqLocal(missing=(GEMMA,)), FakeMetis()          # ... the node says it is not
        p = self.routed(metis)
        with self.local_patch(local):
            self.assertEqual(p.generate("x", "y"), "جواب " + QWQ)
        self.assertEqual([c[1] for c in local.calls], [GEMMA, QWQ])
        self.assertEqual(metis.calls, [])                                # still local: the owner's order is kept
        self.assertEqual((p.answered_via, p.answered_by, p.fell_back), ("local", QWQ, False))
        self.assertIn(GEMMA, p.model_note)
        row = AiProviderState.objects.get(key="local:" + GEMMA)
        self.assertEqual(row.fail_kind, "no_model")
        self.assertIsNotNone(row.open_until)
        # the second request does not knock on gemma's door again, and local is NOT pushed behind Metis because of it
        p2 = self.routed(FakeMetis())
        with self.local_patch(local):
            p2.generate("x", "y")
        self.assertEqual([c[1] for c in local.calls], [GEMMA, QWQ, QWQ])
        self.assertEqual(p2.answered_via, "local")
        self.assertFalse(p2.fell_back)
        st = routing.node_state("text")
        self.assertEqual((st["model"], st["substitute"]), (QWQ, QWQ))
        self.assertIs(st["wanted_installed"], False)                      # the node itself said so: more reliable than its list
        # when the download finishes the mark is forgotten
        priority.clear_model(GEMMA)
        self.assertEqual(routing.node_state("text")["model"], GEMMA)

    def test_an_unknown_list_tries_the_chain_in_order(self):
        ComputeNode.objects.create(name="gpu-1", enabled=True, capabilities={"ollama": True}, last_seen=timezone.now())
        local = SeqLocal(missing=(GEMMA,))
        p = self.routed(FakeMetis())
        with self.local_patch(local):
            self.assertEqual(p.generate("x", "y"), "جواب " + QWEN14)
        self.assertEqual([c[1] for c in local.calls], [GEMMA, QWEN14])
        self.assertEqual(p.answered_by, QWEN14)
        self.assertFalse(p.fell_back)

    def test_when_the_node_has_none_of_them_metis_answers(self):
        self.node(models=(GEMMA, QWQ))
        local, metis = SeqLocal(missing=(GEMMA, QWQ)), FakeMetis()
        p = self.routed(metis)
        with self.local_patch(local):
            self.assertEqual(p.generate("x", "y"), "جواب متیس")
        self.assertEqual([c[1] for c in local.calls], [GEMMA, QWQ])
        self.assertTrue(p.fell_back)
        self.assertEqual(set(AiProviderState.objects.filter(fail_kind="no_model").values_list("key", flat=True)),
                         {"local:" + GEMMA, "local:" + QWQ})

    def test_a_timeout_is_not_a_missing_model_and_does_not_walk_down_the_chain(self):
        self.node(models=(GEMMA, QWQ))
        local, metis = FakeLocal(exc=OllamaTimeout("سرورِ پردازش در 420 ثانیه جوابِ مدل را نداد.")), FakeMetis()
        p = self.routed(metis)
        with self.local_patch(local):
            self.assertEqual(p.generate("x", "y"), "جواب متیس")
        self.assertEqual(len(local.calls), 1)                              # one try, then the other path

    def test_the_research_asks_the_research_model_not_the_everyday_one(self):
        self.node(models=(GEMMA, QWQ))
        local = FakeLocal()
        p = self.routed(FakeMetis(), kind=routing.RESEARCH)
        with self.local_patch(local):
            p.generate("x", "y")
        self.assertEqual(local.calls[0][1], QWQ)
        text = self.routed(FakeMetis())
        with self.local_patch(local):
            text.generate("x", "y")
        self.assertEqual(local.calls[1][1], GEMMA)


# ──────────────────────────────────────────────────────── درخواست به Ollama: بی‌فکر و اندازهٔ پنجره

class OllamaProfileTests(TestCase):
    def run_remote(self, model, **kw):
        sent = []

        def fake(payload, **_kw):
            sent.append(dict(payload, options=dict(payload.get("options") or {})))
            return {"response": "ok", "done": True}

        with mock.patch("services.ai.ollama_remote.generate", side_effect=fake):
            prov = OllamaProvider(base_url="agent://any")
            prov.num_ctx = 16384
            prov.generate(model, "سلام", **kw)
        return sent

    def test_qwen3_answers_without_thinking_and_in_a_window_that_fits(self):
        sent = self.run_remote(QWEN14)
        self.assertIs(sent[0]["think"], False)
        self.assertEqual(sent[0]["options"]["num_ctx"], 8192)
        self.assertIs(self.run_remote("qwen3:8b")[0]["think"], False)
        self.assertEqual(self.run_remote("qwen3:8b")[0]["options"]["num_ctx"], 16384)

    def test_other_models_get_no_think_switch(self):
        for model in (GEMMA, QWQ, CODER):
            sent = self.run_remote(model)
            self.assertNotIn("think", sent[0], model)
            self.assertEqual(sent[0]["options"]["num_ctx"], 8192 if model == GEMMA else 16384, model)
        sent = self.run_remote(VL)                      # 08/21: the vision model answers without thinking (it was slow)
        self.assertIs(sent[0]["think"], False)
        self.assertEqual(sent[0]["options"]["num_ctx"], 16384)

    def test_an_explicit_context_size_of_the_caller_is_kept(self):
        sent = self.run_remote(QWEN14, options={"num_ctx": 12000})
        self.assertEqual(sent[0]["options"]["num_ctx"], 12000)

    def test_a_server_that_refuses_the_think_switch_is_asked_again_without_it(self):
        sent = []
        replies = [OllamaError("Ollama خطا داد: model does not support thinking"), {"response": "ok", "done": True}]

        def fake(payload, **_kw):
            sent.append(dict(payload))
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        with mock.patch("services.ai.ollama_remote.generate", side_effect=fake):
            prov = OllamaProvider(base_url="agent://any")
            self.assertEqual(prov.generate(QWEN14, "x"), "ok")
        self.assertIn("think", sent[0])
        self.assertNotIn("think", sent[1])

    def test_other_errors_are_not_swallowed(self):
        with mock.patch("services.ai.ollama_remote.generate", side_effect=OllamaError("model not found")):
            with self.assertRaises(OllamaError):
                OllamaProvider(base_url="agent://any").generate(QWEN14, "x")


# ──────────────────────────────────────────────────────── وضعِ زنده، ذخیره و «آزمون»

class StatusTests(Base):
    def test_snapshot_shows_every_kind_with_the_stand_in_and_the_download_info(self):
        self.node(models=(QWQ, VL, CODER))
        snap = status.snapshot()
        self.assertEqual(set(snap["kinds"]), set(priority.KINDS))
        text = snap["kinds"]["text"]
        self.assertEqual((text["model"], text["effective_model"], text["substitute"]), (GEMMA, QWQ, QWQ))
        self.assertIs(text["installed"], False)
        self.assertIs(text["usable"], True)
        self.assertTrue(text["pullable"])
        self.assertEqual(text["size_mb"], 8164)
        self.assertEqual(snap["kinds"]["research"]["effective_model"], QWQ)
        self.assertEqual(snap["kinds"]["research"]["substitute"], "")
        self.assertIs(snap["kinds"]["research"]["installed"], True)
        rows = {m["tag"]: m for m in snap["models"]}
        self.assertEqual(rows[GEMMA]["size_mb"], 8164)
        self.assertIs(rows[GEMMA]["installed"], False)
        self.assertIs(rows[QWQ]["installed"], True)
        self.assertEqual(snap["pulls"], [])
        self.assertTrue(snap["local"]["models_reported_at"])

    def test_a_stale_list_of_an_off_node_is_shown_as_such(self):
        self.node(models=(QWQ, GEMMA), online=False)
        snap = status.snapshot()
        self.assertFalse(snap["local"]["online"])
        self.assertTrue(snap["local"]["models_reported_at"])
        self.assertIs(snap["kinds"]["text"]["installed"], True)      # last known: it was installed

    def test_update_accepts_the_new_fields(self):
        status.update({"priority_research": "metis_first", "model_research": QWQ, "model_text": QWEN14})
        row = AiPriority.get()
        self.assertEqual((row.priority_research, row.model_research, row.model_text), ("metis_first", QWQ, QWEN14))
        with self.assertRaises(status.UpdateError):
            status.update({"priority_research": "sometimes"})
        with self.assertRaises(status.UpdateError):
            status.update({"model_research": "bad name"})

    def test_local_test_runs_the_stand_in_and_checks_json(self):
        self.node(models=(QWQ,))
        fake = FakeLocal(answer='{"ok": true}')
        with self.local_patch(fake):
            res = status.run_test("local", "text")
        self.assertTrue(res["ok"], res)
        self.assertEqual(fake.calls[0][1], QWQ)
        self.assertTrue(fake.calls[0][2]["format_json"])
        self.assertIn("JSON", res["message"])
        self.assertIn(GEMMA, res["message"])                       # says the chosen model is not installed

    def test_local_test_fails_when_the_model_cannot_produce_json(self):
        self.node(models=(GEMMA,))
        with self.local_patch(FakeLocal(answer="سلام، چطور کمک کنم؟")):
            res = status.run_test("local", "text")
        self.assertFalse(res["ok"])

    def test_vision_test_stays_a_plain_one_word_check(self):
        self.node(models=(VL,))
        fake = FakeLocal(answer="OK")
        with self.local_patch(fake):
            res = status.run_test("local", "vision")
        self.assertTrue(res["ok"], res)
        self.assertFalse(fake.calls[0][2]["format_json"])


# ──────────────────────────────────────────────────────── «دانلود مدل»: پنل ⇄ صف ⇄ گره

class PullBase(TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="nm-pull-test-")
        self.addCleanup(shutil.rmtree, self.data, True)
        override = override_settings(NM_DATA_DIR=self.data, AI_ROUTE_FORCE=True)
        override.enable()
        self.addCleanup(override.disable)
        User = get_user_model()
        self.admin = User.objects.create_user("pull-admin", "a@x.ir", "pw-12345", is_staff=True, is_superuser=True)
        self.user = User.objects.create_user("pull-user", "u@x.ir", "pw-12345")
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def node(self, models=(QWQ, VL, CODER), online=True, pull=True, name="gpu-1", ollama=True, **extra):
        caps = {"agent": "2.2" if pull else "2.0", "ollama": ollama, "ollama_models": list(models), **extra}
        if pull:
            caps["ollama_pull"] = True
        return ComputeNode.objects.create(
            name=name, enabled=True, capabilities=caps,
            last_seen=timezone.now() if online else timezone.now() - timedelta(hours=5))

    def pull(self, tag=GEMMA, **extra):
        return self.api.post("/api/v1/ai/models/pull/", {"tag": tag, **extra}, format="json")

    def as_node(self, node):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Node " + node.token)
        return c


class PullApiTests(PullBase):
    def test_the_button_queues_a_pull_job_with_a_long_lease(self):
        node = self.node()
        r = self.pull()
        self.assertEqual(r.status_code, 200, r.content)
        job = ComputeJob.objects.get(kind="ollama.pull")
        self.assertEqual(job.node_wanted, node.name)
        self.assertEqual(job.state, "QUEUED")
        self.assertEqual(job.payload["tag"], GEMMA)
        self.assertEqual(job.payload["expected_bytes"], 8164 * 1_000_000)
        self.assertEqual(job.lease_s, model_pull.LEASE_S)
        self.assertGreaterEqual(job.lease_s, 1800)
        self.assertGreater(job.timeout_s, 3600)
        self.assertGreaterEqual(job.max_attempts, 2)
        pull = r.data["pull"]
        self.assertEqual((pull["tag"], pull["state"], pull["node"]), (GEMMA, "QUEUED", node.name))
        self.assertEqual([p["uid"] for p in r.data["pulls"]], [str(job.uid)])
        self.assertIn("در صف", pull["text"])

    def test_only_allow_listed_tags(self):
        self.node()
        for tag in ("evil:1", "gemma3:12b; rm -rf /", "", "../../x:y"):
            r = self.pull(tag)
            self.assertEqual(r.status_code, 400, tag)
            self.assertIn("فهرستِ مجاز", r.data["error"])
        self.assertFalse(ComputeJob.objects.filter(kind="ollama.pull").exists())

    def test_an_off_node_still_takes_the_job_and_the_panel_says_it_waits(self):
        self.node(online=False)
        r = self.pull()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.data["pull"]["waiting_for_node"])
        self.assertFalse(r.data["pull"]["node_online"])
        self.assertIn("خاموش", r.data["pull"]["text"])
        self.assertIn("روشن", r.data["pull"]["text"])

    def test_an_old_agent_is_told_to_update_instead_of_failing_later(self):
        self.node(pull=False)
        r = self.pull()
        self.assertEqual(r.status_code, 409)
        self.assertIn("Update.bat", r.data["error"])
        self.assertFalse(ComputeJob.objects.filter(kind="ollama.pull").exists())

    def test_a_model_that_is_already_there_is_not_pulled(self):
        self.node(models=(GEMMA, QWQ))
        r = self.pull()
        self.assertEqual(r.status_code, 409)
        self.assertIn("نصب است", r.data["error"])

    def test_no_node_at_all(self):
        r = self.pull()
        self.assertEqual(r.status_code, 409)
        self.assertIn("سرورِ پردازش", r.data["error"])

    def test_a_second_click_returns_the_same_download(self):
        self.node()
        a, b = self.pull(), self.pull()
        self.assertEqual(a.data["pull"]["uid"], b.data["pull"]["uid"])
        self.assertEqual(ComputeJob.objects.filter(kind="ollama.pull").count(), 1)
        # a different model is a different download
        self.pull(QWEN14)
        self.assertEqual(ComputeJob.objects.filter(kind="ollama.pull").count(), 2)

    def test_cancel(self):
        self.node()
        uid = self.pull().data["pull"]["uid"]
        r = self.api.post("/api/v1/ai/models/pull/cancel/", {"uid": uid}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(ComputeJob.objects.get(uid=uid).state, "CANCELLED")
        self.assertEqual(r.data["pull"]["state"], "CANCELLED")
        self.assertEqual(self.api.post("/api/v1/ai/models/pull/cancel/", {"uid": "nope"}, format="json").status_code, 404)

    def test_only_staff(self):
        self.node()
        anon = APIClient()
        self.assertIn(anon.post("/api/v1/ai/models/pull/", {"tag": GEMMA}, format="json").status_code, (401, 403))
        user = APIClient()
        user.force_authenticate(self.user)
        self.assertEqual(user.post("/api/v1/ai/models/pull/", {"tag": GEMMA}, format="json").status_code, 403)
        self.assertEqual(user.post("/api/v1/ai/models/pull/cancel/", {"uid": "x"}, format="json").status_code, 403)

    def test_the_generic_submit_cannot_be_used_to_pull_anything(self):
        self.node()
        r = self.api.post("/api/v1/compute/submit/", {"kind": "ollama.pull", "payload": '{"tag": "evil:1"}'}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ComputeJob.objects.filter(kind="ollama.pull").exists())


class FakeNodeTests(PullBase):
    """یک «گره» که پروتکلِ واقعی را می‌زند: heartbeat ⇒ claim ⇒ فهرستِ مجاز ⇒ progress ⇒ finish ⇒ heartbeat."""

    def test_the_whole_download_from_click_to_installed(self):
        node = self.node(online=False, models=(QWQ, VL, CODER))
        uid = self.pull().data["pull"]["uid"]                         # the PC is off: queued
        gpu = self.as_node(node)

        # the PC boots: heartbeat (now online), then claim
        hb = gpu.post("/api/v1/compute/heartbeat/", {"agent": "2.2", "ollama": True, "ollama_pull": True,
                                                       "ollama_models": [QWQ, VL, CODER]}, format="json")
        self.assertEqual(hb.status_code, 200, hb.content)
        claimed = gpu.post("/api/v1/compute/claim/", {}, format="json").data["job"]
        self.assertEqual((claimed["uid"], claimed["kind"]), (uid, "ollama.pull"))
        self.assertEqual(claimed["payload"]["tag"], GEMMA)

        # the node asks the site which tags it may pull (fail closed on anything else)
        tags = gpu.get("/api/v1/compute/ollama/pullable/").data["tags"]
        self.assertIn(GEMMA, tags)
        self.assertEqual(tags[GEMMA]["size_mb"], 8164)
        self.assertNotIn("evil:1", tags)
        self.assertEqual(APIClient().get("/api/v1/compute/ollama/pullable/").status_code, 401)

        # live progress: 4 GB of 8.16 GB at 24 MB/s
        live = {"kind": "pull", "tag": GEMMA, "done": 4_000_000_000, "total": 8_164_000_000, "speed_mbs": 24.1,
                "phase": "downloading", "attempt": 1, "max_attempts": 30}
        p = gpu.post("/api/v1/compute/jobs/%s/progress/" % uid, {"progress": 0.49, "message": "pull", "meta": live}, format="json")
        self.assertEqual(p.status_code, 200)
        snap = self.api.get("/api/v1/ai/priority/").data
        pull = snap["pulls"][0]
        self.assertEqual((pull["state"], pull["phase"]), ("RUNNING", "downloading"))
        self.assertAlmostEqual(pull["percent"], 49.0, delta=0.1)
        self.assertEqual((pull["done_mb"], pull["total_mb"]), (4000, 8164))
        self.assertEqual(pull["speed_mbs"], 24.1)
        self.assertIn("گیگابایت", pull["text"])
        self.assertIn("۴٫۰", pull["text"])                           # Persian digits, decimal sign
        self.assertIn("۴۹٪", pull["text"])
        self.assertTrue(pull["node_online"])

        # a broken stream: the agent reports it is retrying; bytes already downloaded stay in the numbers
        gpu.post("/api/v1/compute/jobs/%s/progress/" % uid,
                 {"progress": 0.49, "message": "retry", "meta": {**live, "phase": "retry", "attempt": 2}}, format="json")
        again = self.api.get("/api/v1/ai/priority/").data["pulls"][0]
        self.assertIn("تلاشِ دوباره", again["text"])
        self.assertEqual(again["done_mb"], 4000)

        # finished; the next heartbeat lists the new model and the card flips to «installed»
        done = gpu.post("/api/v1/compute/jobs/%s/finish/" % uid, {"ok": True, "meta": {"tag": GEMMA}}, format="json")
        self.assertEqual(done.data["state"], "COMPLETED")
        gpu.post("/api/v1/compute/heartbeat/", {"agent": "2.2", "ollama": True, "ollama_pull": True,
                                                  "ollama_models": [QWQ, VL, CODER, GEMMA]}, format="json")
        snap = self.api.get("/api/v1/ai/priority/").data
        self.assertEqual(snap["pulls"][0]["state"], "COMPLETED")
        self.assertEqual(snap["pulls"][0]["percent"], 100.0)
        text = snap["kinds"]["text"]
        self.assertIs(text["installed"], True)
        self.assertEqual((text["effective_model"], text["substitute"]), (GEMMA, ""))

    def test_a_node_with_ollama_off_still_takes_the_download_job(self):
        """Ollama stopped and not startable: the job must not wait forever in the queue — the agent answers (and says why)."""
        node = self.node(models=(QWQ,), ollama=False)
        node.capabilities = {**node.capabilities, "ollama": False, "ollama_models_source": "disk"}
        node.save()
        self.assertFalse(node.has("ollama"))
        uid = self.pull().data["pull"]["uid"]
        got = self.as_node(node).post("/api/v1/compute/claim/", {}, format="json").data["job"]
        self.assertEqual((got["uid"], got["kind"]), (uid, "ollama.pull"))
        # a job nobody named a node for: an agent without the flag does not get it, one with the flag does
        ComputeJob.objects.all().delete()
        job = compute.enqueue("ollama.pull", {"tag": GEMMA}, node="", dedupe=False, require_online=False)
        old = self.node(models=(QWQ,), pull=False, ollama=False, name="old-pc")
        self.assertIsNone(compute.claim(old))
        self.assertEqual(compute.claim(node).uid, job.uid)

    def test_finishing_a_pull_forgets_the_not_installed_mark_of_that_model(self):
        node = self.node()
        AiProviderState.objects.create(key="local:" + GEMMA, fail_kind="no_model", fails=1,
                                       open_until=timezone.now() + timedelta(minutes=5))
        uid = self.pull().data["pull"]["uid"]
        gpu = self.as_node(node)
        gpu.post("/api/v1/compute/claim/", {}, format="json")
        self.assertTrue(priority.blocked_models([GEMMA]))
        gpu.post("/api/v1/compute/jobs/%s/finish/" % uid, {"ok": True, "meta": {}}, format="json")
        self.assertFalse(priority.blocked_models([GEMMA]))

    def test_a_failed_download_shows_the_persian_reason_not_the_raw_error(self):
        node = self.node()
        uid = self.pull().data["pull"]["uid"]
        gpu = self.as_node(node)
        gpu.post("/api/v1/compute/claim/", {}, format="json")
        err = "JobError: DISK_FULL: the disk is full | دیسکِ این کامپیوتر پر شده است؛ جا باز کنید"
        gpu.post("/api/v1/compute/jobs/%s/finish/" % uid, {"ok": False, "error": err, "meta": {"retryable": False}}, format="json")
        pull = self.api.get("/api/v1/ai/priority/").data["pulls"][0]
        self.assertEqual(pull["state"], "FAILED")
        self.assertEqual(pull["error"], "دیسکِ این کامپیوتر پر شده است؛ جا باز کنید")
        self.assertEqual(pull["text"], pull["error"])

    def test_a_running_download_is_not_requeued_during_a_long_quiet_spell_but_is_after_the_lease(self):
        node = self.node()
        uid = self.pull().data["pull"]["uid"]
        self.as_node(node).post("/api/v1/compute/claim/", {}, format="json")
        job = ComputeJob.objects.get(uid=uid)
        job.state = "RUNNING"
        job.heartbeat_at = timezone.now() - timedelta(minutes=20)
        job.save()
        compute.requeue_stale()
        self.assertEqual(ComputeJob.objects.get(uid=uid).state, "RUNNING")      # a normal job (lease 600 s) would be back in the queue
        job.heartbeat_at = timezone.now() - timedelta(minutes=31)
        job.save()
        compute.requeue_stale()
        job = ComputeJob.objects.get(uid=uid)
        self.assertEqual(job.state, "QUEUED")                                   # the PC died: the next claim resumes from -partial
        self.assertEqual(job.payload["tag"], GEMMA)

    def test_a_node_that_goes_off_mid_download_is_shown_as_paused(self):
        node = self.node()
        uid = self.pull().data["pull"]["uid"]
        self.as_node(node).post("/api/v1/compute/claim/", {}, format="json")
        self.as_node(node).post("/api/v1/compute/jobs/%s/progress/" % uid, {"progress": 0.3, "meta": {
            "kind": "pull", "tag": GEMMA, "done": 2_000_000_000, "total": 8_164_000_000, "phase": "downloading"}}, format="json")
        ComputeNode.objects.filter(pk=node.pk).update(last_seen=timezone.now() - timedelta(minutes=10))
        pull = self.api.get("/api/v1/ai/priority/").data["pulls"][0]
        self.assertTrue(pull["waiting_for_node"])
        self.assertIn("خاموش", pull["text"])
        self.assertIn("ادامه", pull["text"])

    def test_the_model_list_survives_an_old_agent_that_stops_sending_it_while_ollama_is_off(self):
        node = self.node(models=(QWQ,), pull=False)
        gpu = self.as_node(node)
        gpu.post("/api/v1/compute/heartbeat/", {"agent": "2.0", "ollama": False}, format="json")
        node.refresh_from_db()
        self.assertEqual(node.capabilities["ollama_models"], [QWQ])
        self.assertIs(node.capabilities["ollama_models_stale"], True)
        self.assertNotIn("ollama_models_stale", compute.summary()["capabilities"])
        # a new agent sends the list again (read from disk while Ollama is off): not stale any more
        gpu.post("/api/v1/compute/heartbeat/", {"agent": "2.2", "ollama": False, "ollama_pull": True,
                                                  "ollama_models": [QWQ, GEMMA], "ollama_models_source": "disk"}, format="json")
        node.refresh_from_db()
        self.assertEqual(node.capabilities["ollama_models"], [QWQ, GEMMA])
        self.assertNotIn("ollama_models_stale", node.capabilities)

    def test_the_node_is_told_the_research_model_too(self):
        node = self.node()
        hb = self.as_node(node).post("/api/v1/compute/heartbeat/", {"agent": "2.2"}, format="json").data
        self.assertEqual(hb["ai"]["research_model"], QWQ)
        self.assertEqual(hb["ai"]["text_model"], GEMMA)

    def test_job_json_carries_the_live_numbers(self):
        node = self.node()
        uid = self.pull().data["pull"]["uid"]
        gpu = self.as_node(node)
        gpu.post("/api/v1/compute/claim/", {}, format="json")
        gpu.post("/api/v1/compute/jobs/%s/progress/" % uid, {"progress": 0.1, "meta": {"done": 5, "total": 10}}, format="json")
        data = self.api.get("/api/v1/compute/jobs/%s/" % uid).data
        self.assertEqual(data["live"], {"done": 5, "total": 10})
        # giant / non-dict meta is ignored, not stored
        gpu.post("/api/v1/compute/jobs/%s/progress/" % uid, {"progress": 0.1, "meta": {"x": "y" * 5000}}, format="json")
        self.assertEqual(self.api.get("/api/v1/compute/jobs/%s/" % uid).data["live"], {"done": 5, "total": 10})


# ──────────────────────────────────────────────────────── کدام کار به کدام مدل می‌رود

class TaskMappingTests(TestCase):
    RESEARCH_SITES = ("apps.ai.research_llm", "apps.ai.trends", "apps.ai.tasks", "services.research.call_analysis")
    EVERYDAY_SITES = ("apps.content.tasks", "apps.customers.agent", "apps.shoot.plan", "services.audio.narration",
                      "services.audio.studio", "apps.regen.services")

    def test_research_work_asks_for_the_research_model(self):
        for name in self.RESEARCH_SITES:
            src = inspect.getsource(importlib.import_module(name))
            self.assertIn("kind=RESEARCH", src, name)
            self.assertIn("TASK_RESEARCH", src, name)
            self.assertNotIn("models_for(TASK_REASONING)", src, name)

    def test_everyday_text_stays_on_the_fast_model(self):
        for name in self.EVERYDAY_SITES:
            src = inspect.getsource(importlib.import_module(name))
            self.assertNotIn("kind=RESEARCH", src, name)
            self.assertNotIn("TASK_RESEARCH", src, name)

    def test_ask_json_uses_the_research_provider_and_models(self):
        from apps.ai import research_llm

        store = mock.Mock(pk=1)
        provider = mock.MagicMock()
        with mock.patch.object(research_llm, "status", return_value=(True, "")), \
                mock.patch("services.ai.gateway.text_provider", return_value=provider) as tp, \
                mock.patch("apps.ai.services.recorded_json_call", return_value=({"a": 1}, None)) as call:
            self.assertEqual(research_llm.ask_json(store, prompt_id="p", prompt="x", system="s", validate=None), {"a": 1})
        self.assertEqual(tp.call_args.kwargs["kind"], priority.RESEARCH)
        self.assertEqual(call.call_args.kwargs["models"], models_for(TASK_RESEARCH))
        self.assertIs(call.call_args.kwargs["provider"], provider)

    def test_the_research_availability_probe_asks_about_the_research_path(self):
        from django.core.cache import cache

        from apps.ai import research_llm

        cache.clear()
        provider = routing.RoutedTextProvider(None, task="t", kind=routing.RESEARCH)
        with mock.patch("services.ai.gateway.text_provider", return_value=provider) as tp:
            research_llm.status(mock.Mock(pk=987))
        self.assertEqual(tp.call_args.kwargs["kind"], priority.RESEARCH)
        cache.clear()

    def test_product_intelligence_and_market_analysis_are_research(self):
        from apps.ai import tests as base_tests
        from apps.ai.tasks import analyze_market_task, analyze_product_task
        from apps.jobs.models import Job
        from apps.products.models import Product

        user = get_user_model().objects.create_user("map-user", "m@x.ir", "pw-12345")
        store = Store.objects.create(owner=user, name="map-shop")
        product = Product.objects.create(store=store, name="کفش اسپرت", description="کفش سبک")
        job = Job.objects.create(store=store, type=Job.Type.PRODUCT_ANALYSIS, context={"product_id": product.id})
        with mock.patch("apps.ai.tasks.vision_provider") as vision, mock.patch("apps.ai.tasks.text_provider") as text:
            provider = text.return_value
            vision.return_value = provider
            provider.generate_json.return_value = (base_tests.VALID_INTELLIGENCE, "{}")
            analyze_product_task.apply(args=(job.id, product.id))
        self.assertEqual(text.call_args.kwargs["kind"], priority.RESEARCH)
        self.assertNotIn("kind", vision.call_args.kwargs)               # the photo analysis stays vision

        job2 = Job.objects.create(store=store, type=Job.Type.MARKET_ANALYSIS)
        sample = {"fetched_at": "x", "query": "q", "sources": [], "items": []}
        with mock.patch("services.research.web.research_product", return_value=sample), \
                mock.patch("apps.ai.tasks.text_provider") as text2:
            text2.return_value.generate_json.return_value = (dict(base_tests.VALID_MARKET), "{}")
            analyze_market_task.apply(args=(job2.id, product.id, ""))
        self.assertEqual(text2.call_args.kwargs["kind"], priority.RESEARCH)


class NodeTimeoutsTests(SimpleTestCase):
    """۱۴۰۵/۰۸/۱۷: گرهٔ مالک (یک جا) هر کارِ متن را ۱–۷ دقیقه نگه می‌داشت ⇒ کارهای بعدی پس از ۴۵ ثانیه لغو و پارک می‌شدند."""

    def test_the_light_model_stands_in_before_the_32b_one(self):
        chain = model_catalog.chain_for(priority.TEXT, GEMMA)
        self.assertLess(chain.index("qwen3:8b"), chain.index(QWQ))

    def test_a_model_bigger_than_the_card_gets_more_run_time(self):
        self.assertEqual(routing.run_timeout_for("qwen3:8b"), routing.run_timeout())
        self.assertEqual(routing.run_timeout_for(GEMMA), routing.run_timeout())
        self.assertGreaterEqual(routing.run_timeout_for(QWQ), 1500)
        self.assertEqual(routing.run_timeout_for("unknown:1b"), routing.run_timeout())

    def test_local_as_the_only_path_waits_its_turn(self):
        self.assertGreater(routing.solo_claim_timeout(), routing.claim_timeout())
        with override_settings(AI_NODE_CLAIM_TIMEOUT_SOLO=120):
            self.assertEqual(routing.solo_claim_timeout(), 120)

    def test_call_local_passes_the_longer_waits(self):
        src = inspect.getsource(routing._Router._call_local)
        self.assertIn("solo_claim_timeout()", src)
        self.assertIn("run_timeout_for(model)", src)
        self.assertIn("self._call_local(local_call, cfg, has_alt)", inspect.getsource(routing._Router._route))
