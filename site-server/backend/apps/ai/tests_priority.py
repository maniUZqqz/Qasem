# -*- coding: utf-8 -*-
"""اولویتِ هوش مصنوعی (لوکال / متیس): هر دو ترتیب، هر دسته از شکست، کلیدِ مدار، ثبتِ مسیرِ پاسخ، پیامِ ترکیبیِ دو دلیل.

تصمیمِ مالک (۱۴۰۵/۰۸/۱۲): «توی همه کارها باید دو تاش باشه و باید توی تنظیمات تعیین شود: متیس / لوکال — یکی نبود اون یکی».

⚠ این‌جا هیچ‌چیز به متیس یا به سرورِ پردازشِ واقعی وصل نمی‌شود: لوکال یک provider ساختگی است (`routing.node_provider` جایگزین
می‌شود)، متیس یا ساختگی است یا OpenAICompatProvider ِ واقعی با `requests.post` ِ ساختگی (تا کدِ واقعیِ دسته‌بندیِ ۴۰۲/۴۰۱/۵xx
بی‌شبکه آزموده شود).
"""
import json
from datetime import timedelta
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.compute.models import ComputeNode
from apps.stores.models import Store
from services.ai import gateway, priority, routing, status
from services.ai.ollama import (
    OllamaError,
    OllamaMalformedOutput,
    OllamaProvider,
    OllamaTimeout,
    OllamaUnavailable,
)
from services.ai.openai_compat import OpenAICompatProvider
from services.ai.router import TASK_CODE, TASK_REASONING, TASK_VISION, models_for

from .models import AiPriority, AiProviderState, AIRequest, StoreAIPolicy
from .services import recorded_json_call

CODER, TEXT_MODEL, VISION_MODEL = "qwen3-coder:30b", "qwq:32b", "qwen3-vl:30b"
ALL_MODELS = (TEXT_MODEL, VISION_MODEL, CODER)

AI_CONF = {
    "AI_API_BASE_URL": "https://api.example.ir/openai/v1",
    "AI_API_KEY": "k",
    "AI_API_MODEL_TEXT": "gpt-4o-mini",
    "AI_API_MODEL_VISION": "gpt-4o-mini",
}


def with_conf(extra=None):
    from django.conf import settings
    return {**settings.UPMARKET_AI, **AI_CONF, **(extra or {})}


class FakeLocal:
    """جای OllamaProvider روی گره: همان امضا، بی‌شبکه."""

    def __init__(self, answer=None, exc=None):
        self.answer, self.exc = answer, exc
        self.calls = []

    def generate(self, model, prompt, **kw):
        self.calls.append(("generate", model, kw))
        if self.exc:
            raise self.exc
        return self.answer if self.answer is not None else "جواب لوکال"

    def generate_json(self, model, prompt, **kw):
        self.calls.append(("generate_json", model, kw))
        if self.exc:
            raise self.exc
        return {"from": "local"}, '{"from": "local"}'


class FakeMetis:
    """جای OpenAICompatProvider."""

    model = "gpt-4o-mini"

    def __init__(self, exc=None):
        self.exc = exc
        self.calls = []

    def select_models(self, candidates):
        return [self.model]

    def generate(self, prompt, *, model=None, **kw):
        self.calls.append(("generate", model, kw))
        if self.exc:
            raise self.exc
        return "جواب متیس"

    def generate_json(self, model, prompt, **kw):
        self.calls.append(("generate_json", model, kw))
        if self.exc:
            raise self.exc
        return {"from": "metis"}, '{"from": "metis"}'


class Resp:
    """جوابِ ساختگیِ requests برای OpenAICompatProvider ِ واقعی."""

    def __init__(self, status_code=200, text="", payload=None):
        self.status_code, self.text, self._payload = status_code, text, payload

    def json(self):
        return self._payload


def ok_payload(text="سلام از متیس"):
    return Resp(200, "", {"choices": [{"message": {"content": text}}]})


@override_settings(AI_ROUTE_FORCE=True)
class Base(TestCase):
    def setUp(self):
        # آزمون هرگز نباید بخوابد: پشتیبانی از backoff ِ متیس یعنی خطا
        p = mock.patch("services.ai.openai_compat.time.sleep", side_effect=AssertionError("نباید بخوابد"))
        p.start()
        self.addCleanup(p.stop)

    def node(self, models=ALL_MODELS, online=True, name="gpu-1"):
        return ComputeNode.objects.create(
            name=name, enabled=True,
            capabilities={"ollama": True, "ollama_models": list(models)},
            last_seen=timezone.now() if online else timezone.now() - timedelta(hours=3),
        )

    def setting(self, **fields):
        row = AiPriority.get()
        for k, v in fields.items():
            setattr(row, k, v)
        row.save()
        return row

    def routed(self, metis, kind=None, task="t", no_fallback_reason=""):
        return routing.RoutedTextProvider(metis, task=task, kind=kind or routing.TEXT, no_fallback_reason=no_fallback_reason)

    def local_patch(self, fake):
        return mock.patch("services.ai.routing.node_provider", return_value=fake)


# ──────────────────────────────────────────────────────── دسته‌بندیِ خطا

class ClassifyTests(TestCase):
    def kind(self, exc, provider=priority.METIS):
        return priority.classify(exc, provider).kind

    def test_each_failure_class(self):
        cases = [
            (OllamaError("خطای سرویس 402: {\"error\":\"Payment Required\"}"), "no_credit"),
            (OllamaError("خطای سرویس ۴۰۲: اعتبار تمام"), "no_credit"),
            (OllamaUnavailable("کلید API پذیرفته نشد (۴۰۱)."), "bad_key"),
            (OllamaError("خطای سرویس 403: forbidden"), "bad_key"),
            (RuntimeError("دسترسی رد شد (403): x"), "bad_key"),
            (OllamaUnavailable("سهمیه‌ی سرویس تمام شده است (۴۲۹)."), "rate_limit"),
            (OllamaError("خطای سرویس 500: boom"), "server"),
            (OllamaError("خطای سرویس 503: busy"), "server"),
            (RuntimeError("سرویس خطای 502 برگرداند: bad gateway"), "server"),
            (OllamaTimeout("سرویس در 180 ثانیه پاسخ نداد."), "timeout"),
            (OllamaUnavailable("اتصال به سرویس ممکن نشد: refused"), "connection"),
            (OllamaMalformedOutput("خروجی سرویس JSON معتبر نبود"), "bad_output"),
            (RuntimeError("something odd"), "error"),
        ]
        for exc, expected in cases:
            with self.subTest(str(exc)):
                self.assertEqual(self.kind(exc), expected)

    def test_local_failures(self):
        busy = routing.NodeFailed("سرورِ پردازش کار را در 45 ثانیه برنداشت (احتمالاً سرگرمِ کارِ دیگری است).")
        died = routing.NodeFailed("سرورِ پردازش وسطِ کار قطع شد.")
        self.assertEqual(self.kind(busy, priority.LOCAL), "busy")
        self.assertEqual(self.kind(died, priority.LOCAL), "offline")
        self.assertEqual(self.kind(OllamaError("model \"x\" not found (404)"), priority.LOCAL), "no_model")
        self.assertEqual(self.kind(OllamaUnavailable("Ollama روی سرورِ پردازش پاسخ نداد"), priority.LOCAL), "offline")

    def test_messages_are_persian_and_keep_the_status_code(self):
        f = priority.classify(OllamaError("خطای سرویس 402: x"), priority.METIS)
        self.assertIn("۴۰۲", f.message)
        self.assertIn("402", f.sentence())            # ویرایشگرِ ویدیو «402» را در متن می‌جوید

    def test_which_failures_open_the_circuit(self):
        self.assertTrue(priority.classify(OllamaError("خطای سرویس 402"), priority.METIS).trips)
        self.assertTrue(priority.classify(OllamaTimeout("x"), priority.LOCAL).trips)
        self.assertFalse(priority.classify(OllamaMalformedOutput("x"), priority.METIS).trips)
        self.assertFalse(priority.classify(OllamaError("خطای سرویس 400: bad"), priority.METIS).trips)


# ──────────────────────────────────────────────────────── ترتیب و جایگزینی

class OrderTests(Base):
    def test_default_is_local_first_and_local_answers(self):
        self.node()
        local, metis = FakeLocal(), FakeMetis()
        p = self.routed(metis)
        with self.local_patch(local):
            self.assertEqual(p.generate(TEXT_MODEL, "سلام"), "جواب لوکال")
        self.assertEqual(metis.calls, [])
        self.assertEqual((p.answered_via, p.answered_by, p.fell_back), ("local", TEXT_MODEL, False))
        self.assertEqual(p.answered_label, "لوکال (qwq:32b)")

    def test_metis_first_and_metis_answers(self):
        self.node()
        self.setting(priority="metis_first")
        local, metis = FakeLocal(), FakeMetis()
        p = self.routed(metis)
        with self.local_patch(local):
            self.assertEqual(p.generate("x", "y"), "جواب متیس")
        self.assertEqual(local.calls, [])
        self.assertEqual((p.answered_via, p.answered_by, p.fell_back), ("metis", "gpt-4o-mini", False))
        self.assertEqual(p.answered_label, "متیس (gpt-4o-mini)")

    def test_local_first_node_offline_uses_metis(self):
        self.node(online=False)
        metis = FakeMetis()
        p = self.routed(metis)
        with self.local_patch(FakeLocal()) as m:
            self.assertEqual(p.generate("x", "y"), "جواب متیس")
        m.assert_not_called()                                   # گرهٔ خاموش هیچ‌وقت کار نمی‌گیرد
        self.assertTrue(p.fell_back)
        self.assertEqual(p.answered_label, "متیس (پشتیبان)")
        self.assertIn("خاموش", p.fallback_reason)

    def test_local_first_model_missing_uses_metis(self):
        self.node(models=("llama3:8b",))
        p = self.routed(FakeMetis())
        with self.local_patch(FakeLocal()) as m:
            p.generate("x", "y")
        m.assert_not_called()
        self.assertIn("نصب نیست", p.fallback_reason)

    def test_metis_first_unconfigured_goes_local(self):
        self.node()
        self.setting(priority="metis_first")
        p = self.routed(None, no_fallback_reason="متیس (API) تنظیم نشده است.")
        with self.local_patch(FakeLocal()):
            self.assertEqual(p.generate("x", "y"), "جواب لوکال")
        self.assertTrue(p.fell_back)
        self.assertEqual(p.answered_label, "لوکال (پشتیبان: qwq:32b)")
        self.assertIn("تنظیم نشده", p.fallback_reason)

    def test_local_failures_all_fall_to_metis(self):
        failures = [
            OllamaTimeout("سرورِ پردازش در 420 ثانیه جوابِ مدل را نداد."),
            OllamaUnavailable("Ollama روی سرورِ پردازش پاسخ نداد"),
            OllamaError("Ollama روی سرورِ پردازش خطا داد (model=x): HTTP 500"),
            OllamaError("model not found (404)"),
            routing.NodeFailed("سرورِ پردازش کار را در 45 ثانیه برنداشت."),
            routing.NodeFailed("سرورِ پردازش وسطِ کار قطع شد."),
            OllamaMalformedOutput("خروجی JSON نبود"),
        ]
        for exc in failures:
            with self.subTest(str(exc)[:40]):
                AiProviderState.objects.all().delete()
                ComputeNode.objects.all().delete()
                self.node()
                metis = FakeMetis()
                p = self.routed(metis)
                with self.local_patch(FakeLocal(exc=exc)):
                    self.assertEqual(p.generate("x", "y"), "جواب متیس")
                self.assertTrue(p.fell_back)
                self.assertEqual(len(metis.calls), 1)

    def test_metis_failures_all_fall_to_local(self):
        failures = [
            OllamaError("خطای سرویس 402: Payment Required"),
            OllamaUnavailable("کلید API پذیرفته نشد (۴۰۱)."),
            OllamaError("خطای سرویس 403: forbidden"),
            OllamaError("خطای سرویس 500: boom"),
            OllamaError("خطای سرویس 503: busy"),
            OllamaTimeout("سرویس در 180 ثانیه پاسخ نداد."),
            OllamaUnavailable("اتصال به سرویس ممکن نشد: refused"),
            OllamaUnavailable("سهمیه‌ی سرویس تمام شده است (۴۲۹)."),
        ]
        self.node()
        self.setting(priority="metis_first")
        for exc in failures:
            with self.subTest(str(exc)[:40]):
                AiProviderState.objects.all().delete()
                local = FakeLocal()
                p = self.routed(FakeMetis(exc=exc))
                with self.local_patch(local):
                    self.assertEqual(p.generate("x", "y"), "جواب لوکال")
                self.assertTrue(p.fell_back)
                self.assertEqual((p.answered_via, p.answered_by), ("local", TEXT_MODEL))
                self.assertTrue(p.fallback_reason)

    def test_json_path_and_images_reach_the_local_vision_model(self):
        self.node()
        local = FakeLocal()
        p = self.routed(FakeMetis(), kind=routing.VISION)
        with self.local_patch(local):
            parsed, _ = p.generate_json(VISION_MODEL, "describe", images=["aGk="], system="s")
        self.assertEqual(parsed, {"from": "local"})
        name, model, kw = local.calls[0]
        self.assertEqual((name, model), ("generate_json", VISION_MODEL))
        self.assertEqual(kw["images"], ["aGk="])

    def test_select_models_follows_the_order(self):
        self.node()
        p = self.routed(FakeMetis())
        self.assertEqual(p.select_models(["z"]), [TEXT_MODEL])
        self.setting(priority="metis_first")
        self.assertEqual(self.routed(FakeMetis()).select_models(["z"]), ["gpt-4o-mini"])
        ComputeNode.objects.all().update(last_seen=timezone.now() - timedelta(hours=4))
        self.setting(priority="local_first")
        self.assertEqual(self.routed(FakeMetis()).select_models(["z"]), ["gpt-4o-mini"])

    def test_per_task_override_beats_the_global_order(self):
        self.node()
        self.setting(priority="local_first", priority_vision="metis_first")
        local, metis = FakeLocal(), FakeMetis()
        with self.local_patch(local):
            self.assertEqual(self.routed(metis, kind=routing.TEXT).generate("x", "y"), "جواب لوکال")
            self.assertEqual(self.routed(metis, kind=routing.VISION).generate("x", "y"), "جواب متیس")

    def test_local_model_follows_the_kind_mapping(self):
        self.node()
        local = FakeLocal()
        with self.local_patch(local):
            for kind, expected in ((routing.TEXT, TEXT_MODEL), (routing.CODE, CODER), (routing.VISION, VISION_MODEL)):
                self.routed(FakeMetis(), kind=kind).generate("x", "y")
                self.assertEqual(local.calls[-1][1], expected, kind)

    def test_owner_picked_model_is_used_and_must_be_installed(self):
        self.node(models=(TEXT_MODEL, "gemma3:27b"))
        self.setting(model_text="gemma3:27b")
        local = FakeLocal()
        with self.local_patch(local):
            self.routed(FakeMetis()).generate("x", "y")
        self.assertEqual(local.calls[0][1], "gemma3:27b")
        self.setting(model_text="not-installed:1b")
        # qwq:32b is in the chain of the everyday text: it stands in (local stays first), and the answer says so
        p0 = self.routed(FakeMetis())
        with self.local_patch(FakeLocal()):
            p0.generate("x", "y")
        self.assertEqual((p0.answered_via, p0.answered_by, p0.fell_back), ("local", TEXT_MODEL, False))
        self.assertIn("not-installed:1b", p0.model_note)
        # a node with none of the chain's models: straight to Metis
        ComputeNode.objects.all().update(capabilities={"ollama": True, "ollama_models": ["llama3:8b"]})
        metis = FakeMetis()
        p = self.routed(metis)
        with self.local_patch(FakeLocal()) as m:
            p.generate("x", "y")
        m.assert_not_called()
        self.assertIn("not-installed:1b", p.fallback_reason)
        self.assertEqual(models_for(TASK_REASONING)[0], "not-installed:1b")

    def test_models_for_keeps_the_old_behaviour_without_a_pick(self):
        for task in (TASK_REASONING, TASK_VISION, TASK_CODE):
            self.assertTrue(models_for(task))
        self.assertNotEqual(models_for(TASK_VISION)[0], "")


# ──────────────────────────────────────────────────────── کلیدِ مدار

class BreakerTests(Base):
    def test_a_timeout_is_remembered_and_the_next_call_skips_the_dead_path(self):
        self.node()
        local = FakeLocal(exc=OllamaTimeout("سرورِ پردازش در 420 ثانیه جوابِ مدل را نداد."))
        metis = FakeMetis()
        with self.local_patch(local):
            self.assertEqual(self.routed(metis).generate("x", "y"), "جواب متیس")        # اولی منتظر ماند و شکست خورد
            self.assertEqual(len(local.calls), 1)
            # provider تازه (کارِ بعدی): گرهٔ مرده اول نمی‌رود
            p2 = self.routed(metis)
            self.assertEqual(p2.generate("x", "y"), "جواب متیس")
            self.assertEqual(len(local.calls), 1, "کلیدِ مدار باز است؛ لوکال نباید دوباره امتحان شود")
        self.assertTrue(p2.fell_back)
        self.assertIn("کنار گذاشته", p2.fallback_reason)
        state = AiProviderState.objects.get(key="local:%s" % TEXT_MODEL)
        self.assertEqual(state.fail_kind, "timeout")
        self.assertGreater(state.open_until, timezone.now())

    def test_no_credit_is_remembered_for_metis(self):
        self.node()
        self.setting(priority="metis_first")
        metis = FakeMetis(exc=OllamaError("خطای سرویس 402: Payment Required"))
        with self.local_patch(FakeLocal()):
            self.routed(metis).generate("x", "y")
            self.routed(metis).generate("x", "y")
        self.assertEqual(len(metis.calls), 1)
        row = AiProviderState.objects.get(key="metis")
        self.assertEqual(row.fail_kind, "no_credit")

    def test_circuit_closes_after_the_minutes(self):
        self.node()
        self.setting(priority="metis_first")
        metis = FakeMetis(exc=OllamaError("خطای سرویس 500: boom"))
        with self.local_patch(FakeLocal()):
            self.routed(metis).generate("x", "y")
            AiProviderState.objects.filter(key="metis").update(open_until=timezone.now() - timedelta(seconds=1))
            self.routed(metis).generate("x", "y")
        self.assertEqual(len(metis.calls), 2)

    def test_a_success_closes_the_circuit(self):
        self.node()
        self.setting(priority="metis_first")
        priority.trip("metis", priority.classify(OllamaError("خطای سرویس 500: x"), "metis"))
        self.assertIsNotNone(priority.open_failure("metis"))
        priority.ok("metis", "gpt-4o-mini")
        self.assertIsNone(priority.open_failure("metis"))

    def test_when_both_paths_are_open_both_are_still_tried(self):
        self.node()
        priority.trip("metis", priority.classify(OllamaError("خطای سرویس 500: x"), "metis"))
        priority.trip("local", priority.classify(OllamaTimeout("x"), "local", TEXT_MODEL), TEXT_MODEL)
        local = FakeLocal()
        with self.local_patch(local):
            self.assertEqual(self.routed(FakeMetis()).generate("x", "y"), "جواب لوکال")
        self.assertEqual(len(local.calls), 1)

    def test_malformed_output_does_not_open_the_circuit(self):
        self.node()
        with self.local_patch(FakeLocal(exc=OllamaMalformedOutput("junk"))):
            self.routed(FakeMetis()).generate("x", "y")
        self.assertIsNone(priority.open_failure("local", TEXT_MODEL))

    def test_after_the_first_failure_the_rest_of_the_job_skips_the_dead_path(self):
        self.node(models=(TEXT_MODEL,))
        local = FakeLocal(exc=OllamaError("model not found (404)"))
        metis = FakeMetis()
        p = self.routed(metis)
        with self.local_patch(local):
            p.generate("a", "1")
            p.generate("a", "2")
            p.generate_json("a", "3")
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(len(metis.calls), 3)
        self.assertIn("نصب نیست", p.node_broken)


# ──────────────────────────────────────────────────────── هر دو شکست

class BothFailTests(Base):
    def test_message_names_both_reasons_in_persian(self):
        self.node(online=False)
        p = self.routed(FakeMetis(exc=OllamaError("خطای سرویس 402: Payment Required")))
        with self.assertRaises(routing.AllProvidersFailed) as caught:
            p.generate("x", "y")
        text = str(caught.exception)
        self.assertIn("لوکال", text)
        self.assertIn("سرورِ پردازش خاموش است", text)
        self.assertIn("متیس", text)
        self.assertIn("اعتبار", text)
        self.assertIn("۴۰۲", text)
        self.assertIn("402", text)
        self.assertIsInstance(caught.exception, OllamaUnavailable)        # قراردادِ قدیمی: «هوش مصنوعی در دسترس نیست»
        self.assertEqual(set(caught.exception.failures), {"local", "metis"})

    def test_policy_blocking_metis_is_named(self):
        self.node(online=False)
        p = self.routed(None, no_fallback_reason="سیاستِ داده‌ی این فروشگاه اجازه نمی‌دهد.")
        with self.assertRaises(OllamaUnavailable) as caught:
            p.generate("x", "y")
        self.assertIn("سیاستِ داده", str(caught.exception))
        self.assertIn("خاموش", str(caught.exception))

    def test_two_timeouts_are_recorded_as_a_timeout(self):
        self.node()
        p = self.routed(FakeMetis(exc=OllamaTimeout("سرویس در 180 ثانیه پاسخ نداد.")))
        with self.local_patch(FakeLocal(exc=OllamaTimeout("سرورِ پردازش در 420 ثانیه جوابِ مدل را نداد."))):
            with self.assertRaises(routing.AllProvidersFailed) as caught:
                p.generate("x", "y")
        self.assertEqual(caught.exception.status_hint, "TIMEOUT")


# ──────────────────────────────────────────────────────── متیسِ واقعی با HTTP ساختگی

class RealMetisClientTests(Base):
    """کدِ واقعیِ OpenAICompatProvider + دسته‌بندی، فقط requests.post ساختگی: ۴۰۲، ۴۰۱، ۴۰۳، ۵xx، مهلت، قطعِ اتصال."""

    def provider(self):
        return OpenAICompatProvider("https://api.example.ir/openai/v1", "k", model="gpt-4o-mini", timeout=5)

    def run_with(self, post_effect):
        self.node()
        self.setting(priority="metis_first")
        local = FakeLocal()
        p = self.routed(self.provider())
        with mock.patch("services.ai.openai_compat.requests.post", **post_effect) as post, self.local_patch(local):
            result = p.generate("x", "y")
        return p, local, post, result

    def test_http_status_failures_fall_to_local_with_one_attempt(self):
        for code in (402, 401, 403, 429, 500, 502, 503):
            with self.subTest(code):
                AiProviderState.objects.all().delete()
                ComputeNode.objects.all().delete()
                p, local, post, result = self.run_with({"return_value": Resp(code, '{"error":"x"}')})
                self.assertEqual(result, "جواب لوکال")
                self.assertEqual(post.call_count, 1, "وقتی مسیرِ دیگری هست تکرار نمی‌شود")
                self.assertTrue(p.fell_back)

    def test_timeout_and_connection_errors_fall_to_local(self):
        for exc in (requests.Timeout("slow"), requests.ConnectionError("refused")):
            with self.subTest(type(exc).__name__):
                AiProviderState.objects.all().delete()
                ComputeNode.objects.all().delete()
                p, local, post, result = self.run_with({"side_effect": exc})
                self.assertEqual(result, "جواب لوکال")
                self.assertEqual(post.call_count, 1)

    def test_402_reason_is_the_credit_sentence(self):
        p, *_ = self.run_with({"return_value": Resp(402, "Payment Required")})
        self.assertIn("اعتبار", p.fallback_reason)
        self.assertIn("402", p.fallback_reason)

    def test_metis_answers_when_healthy(self):
        self.node()
        self.setting(priority="metis_first")
        p = self.routed(self.provider())
        with mock.patch("services.ai.openai_compat.requests.post", return_value=ok_payload("سلام")), self.local_patch(FakeLocal()) as m:
            self.assertEqual(p.generate("x", "y"), "سلام")
        m.assert_not_called()

    def test_last_path_keeps_its_retries(self):
        """متیس تنها راهِ باقی‌مانده است (گره خاموش) ⇒ تکرارِ معمولی سر جایش می‌ماند."""
        self.node(online=False)
        provider = self.provider()
        p = self.routed(provider)
        with mock.patch("services.ai.openai_compat.time.sleep"), \
                mock.patch("services.ai.openai_compat.requests.post", return_value=Resp(503, "busy")) as post:
            with self.assertRaises(routing.AllProvidersFailed):
                p.generate("x", "y")
        self.assertEqual(post.call_count, 3)


# ──────────────────────────────────────────────────────── ثبت در AIRequest و برچسب

class RecordingTests(Base):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user("rec", password="x")
        self.store = Store.objects.create(owner=self.user, name="ثبت")

    def call(self, provider, **kw):
        return recorded_json_call(
            store=self.store, task_type=AIRequest.TaskType.REASONING, prompt_id="p", prompt_version="1",
            provider=provider, models=["whatever"], prompt="hi", **kw)

    def test_local_answer_is_recorded(self):
        self.node()
        with self.local_patch(FakeLocal()):
            parsed, row = self.call(self.routed(FakeMetis()))
        self.assertEqual(parsed, {"from": "local"})
        self.assertEqual((row.via, row.model, row.fell_back), ("local", TEXT_MODEL, False))
        self.assertEqual(row.answer_label, "لوکال (qwq:32b)")
        self.assertEqual(row.answer_info()["label"], "لوکال (qwq:32b)")

    def test_backup_answer_is_recorded_with_the_reason(self):
        self.node(online=False)
        parsed, row = self.call(self.routed(FakeMetis()))
        self.assertEqual(parsed, {"from": "metis"})
        self.assertEqual((row.via, row.fell_back), ("metis", True))
        self.assertIn("خاموش", row.fallback_reason)
        self.assertEqual(row.answer_label, "متیس (پشتیبان)")
        row.refresh_from_db()
        self.assertEqual(row.via, "metis")

    def test_metis_first_primary_is_not_marked_as_backup(self):
        self.node()
        self.setting(priority="metis_first")
        _, row = self.call(self.routed(FakeMetis()))
        self.assertEqual((row.via, row.fell_back, row.answer_label), ("metis", False, "متیس (gpt-4o-mini)"))

    def test_failure_row_keeps_both_reasons(self):
        self.node(online=False)
        with self.assertRaises(routing.AllProvidersFailed):
            self.call(self.routed(FakeMetis(exc=OllamaError("خطای سرویس 402: x"))))
        row = AIRequest.objects.get()
        self.assertEqual(row.status, AIRequest.Status.PROVIDER_ERROR)
        self.assertIn("لوکال", row.error)
        self.assertIn("متیس", row.error)

    def test_plain_clients_are_labelled_by_type(self):
        provider = OpenAICompatProvider("https://api.example.ir/openai/v1", "k", model="gpt-4o-mini")
        with mock.patch.object(provider, "generate", return_value='{"a": 1}'):
            _, row = self.call(provider)
        self.assertEqual((row.via, row.fell_back), ("metis", False))
        ollama = OllamaProvider(model="m")
        with mock.patch.object(ollama, "generate", return_value='{"a": 1}'):
            _, row = self.call(ollama)
        self.assertEqual(row.via, "local")

    def test_a_mock_provider_leaves_the_fields_blank(self):
        provider = mock.MagicMock()
        provider.generate_json.return_value = ({"ok": 1}, "{}")
        _, row = self.call(provider)
        self.assertEqual((row.via, row.fell_back, row.fallback_reason), ("", False, ""))


# ──────────────────────────────────────────────────────── gateway: همهٔ کارها از یک درگاه

@override_settings(UPMARKET_AI=with_conf())
class GatewayTests(Base):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user("gw", password="x")
        self.store = Store.objects.create(owner=self.user, name="درگاه")

    def test_text_vision_and_task_providers_are_all_two_path(self):
        text = gateway.text_provider(self.store)
        vision = gateway.vision_provider(self.store)
        code = gateway.provider_for_task("CODE", self.store)
        reasoning = gateway.provider_for_task("REASONING", self.store)
        look = gateway.provider_for_task("VISION", self.store)
        for p, kind in ((text, "text"), (vision, "vision"), (code, "code"), (reasoning, "text"), (look, "vision")):
            self.assertIsInstance(p, routing.RoutedTextProvider)
            self.assertEqual(p.kind, kind)
            self.assertIsNotNone(p.fallback, "متیس پشتیبانِ همهٔ نوع‌هاست")
        self.assertEqual(vision.fallback.model, "gpt-4o-mini")

    def test_local_only_store_has_no_metis_path(self):
        StoreAIPolicy.objects.create(store=self.store, mode=StoreAIPolicy.Mode.LOCAL_ONLY)
        for provider in (gateway.text_provider(self.store), gateway.vision_provider(self.store)):
            self.assertIsNone(provider.fallback)
            self.assertIn("سیاست", provider.no_fallback_reason)

    def test_customer_data_never_reaches_metis(self):
        provider = gateway.text_provider(self.store, gateway.CUSTOMER)
        self.assertIsNone(provider.fallback)
        self.setting(priority="metis_first")
        self.node()
        with self.local_patch(FakeLocal()):
            self.assertEqual(provider.generate("x", "y"), "جواب لوکال")          # متیس-اول هم حریمِ مشتری را نمی‌شکند
        ComputeNode.objects.filter(name="gpu-1").update(last_seen=timezone.now() - timedelta(hours=2))
        with self.assertRaises(OllamaUnavailable) as caught:
            gateway.text_provider(self.store, gateway.CUSTOMER).generate("x", "y")
        self.assertIn("پیام مشتری", str(caught.exception))
        self.assertIn("خاموش", str(caught.exception))

    @override_settings(UPMARKET_AI=with_conf({"AI_API_BASE_URL": "", "AI_API_KEY": ""}))
    def test_without_metis_configured_it_says_so(self):
        self.node(online=False)
        with self.assertRaises(OllamaUnavailable) as caught:
            gateway.text_provider(self.store).generate("x", "y")
        self.assertIn("تنظیم نشده", str(caught.exception))


# ──────────────────────────────────────────────────────── «آیا مدل در دسترس است؟» بی‌شبکه

@override_settings(UPMARKET_AI=with_conf())
class AvailabilityTests(Base):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.user = get_user_model().objects.create_user("av", password="x")
        self.store = Store.objects.create(owner=self.user, name="در دسترس")

    def test_either_path_is_enough(self):
        self.node()
        ok, note = self.routed(FakeMetis()).availability()
        self.assertTrue(ok)
        self.assertIn("لوکال", note)
        ComputeNode.objects.update(last_seen=timezone.now() - timedelta(hours=3))
        ok, note = self.routed(FakeMetis()).availability()
        self.assertTrue(ok)
        self.assertEqual(note, "متیس")

    def test_neither_path_names_both_reasons(self):
        self.node(online=False)
        priority.trip("metis", priority.classify(OllamaError("خطای سرویس 402: x"), "metis"))
        ok, note = self.routed(FakeMetis()).availability()
        self.assertFalse(ok)
        self.assertIn("لوکال: سرورِ پردازش خاموش است", note)
        self.assertIn("متیس: چند لحظه پیش خطا داد", note)

    def test_research_status_uses_the_router_and_never_the_network(self):
        from apps.ai import research_llm
        self.node()
        with mock.patch("services.ai.openai_compat.requests.post", side_effect=AssertionError("no network")),                 mock.patch("services.ai.factory.health", side_effect=AssertionError("no health probe")):
            ok, note = research_llm.status(self.store)
        self.assertTrue(ok, note)

    def test_research_status_is_false_when_both_are_down(self):
        from apps.ai import research_llm
        self.node(online=False)
        priority.trip("metis", priority.classify(OllamaError("خطای سرویس 402: x"), "metis"))
        ok, note = research_llm.status(self.store)
        self.assertFalse(ok)
        self.assertIn("خاموش", note)


# ──────────────────────────────────────────────────────── سایت‌ساز و کارگردانِ سه‌بعدی

class StudioAndChatTests(Base):
    databases = {"default", "studio"}

    def test_studio_router_obeys_the_order_and_the_backup(self):
        from apps.ai_engine import providers as studio

        class Cfg:
            api_key, model, base_url, temperature, max_tokens, timeout_s, provider = "k", "gpt-4o-mini", "", 0.3, 1000, 30, "openai"

        self.node()
        direct = mock.MagicMock()
        direct.cfg = Cfg()
        direct.complete.return_value = '{"from":"metis"}'
        router = routing.StudioRouted(direct)
        local = FakeLocal(answer='{"from":"local"}')
        with self.local_patch(local):
            self.assertEqual(router.complete("s", "u"), '{"from":"local"}')
            self.assertEqual(router.answered_via, "local")
            self.setting(priority="metis_first")
            self.assertEqual(router.complete("s", "u"), '{"from":"metis"}')
            self.assertEqual((router.answered_via, router.fell_back), ("metis", False))
            direct.complete.side_effect = studio.AiError("سقفِ درخواست یا اعتبارِ حساب تمام شده (429): x")
            self.assertEqual(router.complete("s", "u"), '{"from":"local"}')
            self.assertTrue(router.fell_back)
            self.assertIn("۴۲۹", router.fallback_reason)
        self.assertEqual(local.calls[0][1], CODER)           # سایت‌ساز = کد ⇒ qwen3-coder

    def test_studio_openai_client_fails_fast_only_when_there_is_a_backup(self):
        from apps.ai_engine.providers import OpenAIProvider

        class Cfg:
            api_key, base_url, timeout_s, model, temperature, max_tokens = "k", "https://x.example/v1", 5, "m", 0.3, 100

        prov = OpenAIProvider(Cfg())
        self.assertIs(prov.fast_fail, False)
        self.assertEqual(prov._client().max_retries, 1)
        prov.fast_fail = True
        self.assertEqual(prov._client().max_retries, 0)

    def test_studio_router_sets_fast_fail_on_the_real_provider(self):
        from apps.ai_engine.providers import OpenAIProvider

        class Cfg:
            api_key, base_url, timeout_s, model, temperature, max_tokens = "k", "https://x.example/v1", 5, "m", 0.3, 100

        self.node()
        prov = OpenAIProvider(Cfg())
        router = routing.StudioRouted(prov)
        seen = []

        def complete(self, system, user, json_mode=True):
            seen.append(self.fast_fail)
            return "{}"

        self.setting(priority="metis_first")
        with mock.patch.object(OpenAIProvider, "complete", complete), self.local_patch(FakeLocal()):
            router.complete("s", "u")                     # لوکال هم هست ⇒ سریع شکست بخورد
            ComputeNode.objects.update(last_seen=timezone.now() - timedelta(hours=3))
            router.complete("s", "u")                     # متیس تنها راه است ⇒ تکرارِ معمول
        self.assertEqual(seen, [True, False])

    def test_studio_without_a_key_skips_metis_without_calling_it(self):
        class Cfg:
            api_key, model = "", "gpt-4o-mini"

        direct = mock.MagicMock()
        direct.cfg = Cfg()
        self.node(online=False)
        with self.assertRaises(routing.AllProvidersFailed) as caught:
            routing.StudioRouted(direct).complete("s", "u")
        direct.complete.assert_not_called()
        self.assertIn("کلید", str(caught.exception))

    def test_studio_provider_turns_the_combined_error_into_AiError(self):
        from apps.ai_engine import providers as studio
        from apps.ai_engine.models import AiSettings

        self.node(online=False)
        cfg = AiSettings.get()
        cfg.api_key = ""
        prov = studio.RoutedProvider(cfg)
        with self.assertRaises(studio.AiError) as caught:
            prov.complete("s", "u")
        self.assertIn("لوکال", str(caught.exception))

    def test_chat_router_for_the_3d_director(self):
        self.node()
        metis_calls = []

        def metis_chat(messages, temperature):
            metis_calls.append(messages)
            return '{"scene": "metis"}', None

        chat = routing.ChatRouted(metis_chat, metis_model="gpt-4o-mini", task="up3d")
        msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "برنامه بده"}]
        local = FakeLocal(answer='{"scene": "local"}')
        with self.local_patch(local):
            text, usage = chat.chat(msgs, 0.5)
        self.assertEqual(text, '{"scene": "local"}')
        self.assertEqual(local.calls[0][2]["system"], "SYS")
        self.assertEqual(local.calls[0][1], TEXT_MODEL)
        self.assertEqual(metis_calls, [])
        with self.local_patch(FakeLocal(exc=OllamaTimeout("x"))):
            text, usage = chat.chat(msgs, 0.5)
        self.assertEqual(text, '{"scene": "metis"}')
        self.assertTrue(chat.fell_back)


# ──────────────────────────────────────────────────────── تنظیم، API و مهاجرت

class SettingTests(TestCase):
    def test_singleton_defaults_to_local_first(self):
        self.assertEqual(AiPriority.get().priority, "local_first")
        self.assertEqual(AiPriority.objects.count(), 1)
        self.assertEqual(priority.config().order(priority.TEXT), ["local", "metis"])

    def test_old_route_mode_is_migrated(self):
        from apps.ai.priority_models import _legacy_priority
        self.assertEqual(_legacy_priority(), "local_first")      # (جدولِ استودیو در این آزمون نیست ⇒ پیش‌فرض)

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql):
                pass

            def fetchone(self):
                return ("metis_only",)

        class FakeConn:
            def cursor(self):
                return FakeCursor()

        with mock.patch("django.db.connections", {"studio": FakeConn()}):
            self.assertEqual(_legacy_priority(), "metis_first")
            AiPriority.objects.all().delete()
            self.assertEqual(AiPriority.get().priority, "metis_first")

    def test_env_defaults_when_no_model_is_picked(self):
        self.assertEqual(priority.local_model(priority.CODE), CODER)
        self.assertEqual(priority.local_model(priority.TEXT), "gemma3:12b")        # everyday text: fast, good Persian
        self.assertEqual(priority.local_model(priority.RESEARCH), TEXT_MODEL)      # research keeps qwq:32b
        self.assertEqual(priority.local_model(priority.VISION), VISION_MODEL)

    def test_owner_confirmed_tags_are_the_defaults_even_if_env_is_silent(self):
        from django.conf import settings
        silent = {**settings.UPMARKET_AI, "MODEL_CODER": "", "MODEL_REASONING": "", "MODEL_VISION": "", "MODEL_TEXT": ""}
        with override_settings(UPMARKET_AI=silent):
            self.assertEqual(priority.local_model(priority.CODE), "qwen3-coder:30b")
            self.assertEqual(priority.local_model(priority.TEXT), "gemma3:12b")
            self.assertEqual(priority.local_model(priority.RESEARCH), "qwq:32b")
            self.assertEqual(priority.local_model(priority.VISION), "qwen3-vl:30b")
        self.assertEqual(priority.DEFAULT_MODELS, {"code": "qwen3-coder:30b", "text": "gemma3:12b", "research": "qwq:32b",
                                                   "vision": "qwen3-vl:30b"})

    def test_answer_labels(self):
        self.assertEqual(priority.answer_label("local", "qwq:32b"), "لوکال (qwq:32b)")
        self.assertEqual(priority.answer_label("metis", "gpt-4o-mini", True), "متیس (پشتیبان)")
        self.assertEqual(priority.answer_label("local", "qwq:32b", True), "لوکال (پشتیبان: qwq:32b)")
        self.assertEqual(priority.answer_label("", "x"), "")


@override_settings(UPMARKET_AI=with_conf())
class ApiTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.staff = U.objects.create_user("st", password="x", is_staff=True)
        self.plain = U.objects.create_user("pl", password="x")
        self.c = APIClient()
        self.c.force_authenticate(self.staff)

    def test_staff_only(self):
        c = APIClient()
        c.force_authenticate(self.plain)
        self.assertEqual(c.get("/api/v1/ai/priority/").status_code, 403)
        self.assertEqual(c.post("/api/v1/ai/priority/", {"priority": "metis_first"}, format="json").status_code, 403)
        self.assertEqual(c.post("/api/v1/ai/priority/test/", {"provider": "metis"}, format="json").status_code, 403)

    def test_snapshot_shape_without_any_network(self):
        ComputeNode.objects.create(name="gpu-1", capabilities={"ollama": True, "ollama_models": list(ALL_MODELS)}, last_seen=timezone.now())
        with mock.patch("services.ai.openai_compat.requests.post", side_effect=AssertionError("no network")):
            r = self.c.get("/api/v1/ai/priority/")
        self.assertEqual(r.status_code, 200, r.data)
        d = r.data
        self.assertEqual(d["priority"], "local_first")
        self.assertTrue(d["local"]["online"])
        self.assertEqual(set(d["kinds"]), {"text", "research", "code", "vision"})
        self.assertEqual(d["kinds"]["text"]["model"], "gemma3:12b")
        self.assertEqual(d["kinds"]["text"]["effective_model"], TEXT_MODEL)       # gemma3 is not on this node: qwq stands in
        self.assertEqual(d["kinds"]["research"]["model"], TEXT_MODEL)
        self.assertIs(d["kinds"]["code"]["installed"], True)
        self.assertEqual(d["kinds"]["vision"]["metis_model"], "gpt-4o-mini")
        self.assertTrue(d["metis"]["configured"])
        self.assertEqual(d["metis"]["host"], "api.example.ir")
        self.assertIn(TEXT_MODEL, d["local"]["known_models"])
        self.assertNotIn("api_key", json.dumps(d), "کلید هرگز بیرون نمی‌آید")

    def test_save_priority_overrides_and_models(self):
        r = self.c.post("/api/v1/ai/priority/", {
            "priority": "metis_first", "priority_vision": "local_first", "model_text": "gemma3:27b",
            "model_code": "", "breaker_minutes": 9}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        row = AiPriority.get()
        self.assertEqual((row.priority, row.priority_vision, row.model_text, row.breaker_minutes), ("metis_first", "local_first", "gemma3:27b", 9))
        self.assertEqual(r.data["kinds"]["vision"]["first"], "local")
        self.assertEqual(r.data["kinds"]["text"]["first"], "metis")
        self.assertEqual(r.data["kinds"]["text"]["model"], "gemma3:27b")

    def test_validation_errors_are_persian(self):
        r = self.c.post("/api/v1/ai/priority/", {"priority": "both", "model_text": "a b", "breaker_minutes": 0}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.data["errors"]), {"priority", "model_text", "breaker_minutes"})
        self.assertEqual(AiPriority.get().priority, "local_first")

    def test_test_endpoint_metis_makes_one_tiny_call_and_records_the_error(self):
        with mock.patch("services.ai.openai_compat.requests.post", return_value=Resp(402, "Payment Required")) as post:
            r = self.c.post("/api/v1/ai/priority/test/", {"provider": "metis"}, format="json")
        self.assertEqual(post.call_count, 1)
        self.assertFalse(r.data["ok"])
        self.assertIn("۴۰۲", r.data["message"])
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 4)
        snap = r.data["status"]["metis"]
        self.assertEqual(snap["last_error"]["kind"], "no_credit")
        self.assertIn("۴۰۲", snap["last_error"]["message"])
        self.assertGreater(snap["circuit_minutes_left"], 0)
        # موفق ⇒ خطا پاک و مدار بسته
        with mock.patch("services.ai.openai_compat.requests.post", return_value=ok_payload("OK")):
            r = self.c.post("/api/v1/ai/priority/test/", {"provider": "metis"}, format="json")
        self.assertTrue(r.data["ok"], r.data)
        self.assertIsNone(r.data["status"]["metis"]["last_error"])
        self.assertEqual(r.data["status"]["metis"]["circuit_minutes_left"], 0)

    def test_test_endpoint_local_reports_offline_without_queueing(self):
        r = self.c.post("/api/v1/ai/priority/test/", {"provider": "local", "kind": "vision"}, format="json")
        self.assertFalse(r.data["ok"])
        self.assertTrue(r.data["message"])
        from apps.compute.models import ComputeJob
        self.assertEqual(ComputeJob.objects.count(), 0)

    def test_test_endpoint_local_missing_model(self):
        ComputeNode.objects.create(name="gpu-1", capabilities={"ollama": True, "ollama_models": ["llama3:8b"]}, last_seen=timezone.now())
        r = self.c.post("/api/v1/ai/priority/test/", {"provider": "local", "kind": "text"}, format="json")
        self.assertFalse(r.data["ok"])
        self.assertIn("نصب نیست", r.data["message"])

    def test_test_endpoint_local_ok_uses_a_fake_node(self):
        ComputeNode.objects.create(name="gpu-1", capabilities={"ollama": True, "ollama_models": list(ALL_MODELS)}, last_seen=timezone.now())
        fake = FakeLocal()
        with mock.patch("services.ai.routing.node_provider", return_value=fake):
            r = self.c.post("/api/v1/ai/priority/test/", {"provider": "local", "kind": "vision"}, format="json")
        self.assertTrue(r.data["ok"], r.data)
        self.assertEqual(fake.calls[0][1], VISION_MODEL)
        self.assertTrue(fake.calls[0][2]["images"])

    def test_unknown_provider(self):
        self.assertEqual(self.c.post("/api/v1/ai/priority/test/", {"provider": "x"}, format="json").status_code, 400)

    def test_reset_closes_open_circuits(self):
        priority.trip("metis", priority.classify(OllamaError("خطای سرویس 500: x"), "metis"))
        r = self.c.post("/api/v1/ai/priority/reset/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(priority.open_failure("metis"))

    def test_history_seeds_the_last_metis_error_without_calling_it(self):
        from apps.stores.models import Store
        store = Store.objects.create(owner=self.staff, name="s")
        AIRequest.objects.create(store=store, task_type="REASONING", model="gpt-4o-mini", prompt_id="p", prompt_version="1",
                                 status="PROVIDER_ERROR", error="خطای سرویس 402: {\"error\":\"Payment Required\"}")
        d = self.c.get("/api/v1/ai/priority/").data
        self.assertEqual(d["metis"]["last_error"]["kind"], "no_credit")
        self.assertTrue(d["metis"]["last_error"]["from_history"])

    @override_settings(AI_ROUTE_FORCE=True)
    def test_ai_status_card_names_both_paths_for_text_and_vision(self):
        rows = {x["capability"]: x for x in self.c.get("/api/v1/ai/status/").data["capabilities"]}
        for cap, model in (("TEXT", "gemma3:12b"), ("VISION", VISION_MODEL)):
            self.assertEqual(rows[cap]["kind"], "ROUTED")
            self.assertTrue(rows[cap]["local"])
            self.assertEqual(rows[cap]["model"], model)
            self.assertEqual(rows[cap]["fallbacks"], 1)
            self.assertEqual(rows[cap]["order"], ["local", "metis"])
        row = AiPriority.get()
        row.priority = "metis_first"
        row.save()
        rows = {x["capability"]: x for x in self.c.get("/api/v1/ai/status/").data["capabilities"]}
        self.assertFalse(rows["TEXT"]["local"])
        self.assertEqual(rows["TEXT"]["model"], "gpt-4o-mini")
        self.assertTrue(rows["TEXT"]["provider"].startswith("متیس"))

    def test_serializers_carry_the_answer(self):
        from apps.ai.serializers import AIRequestSerializer
        from apps.stores.models import Store
        store = Store.objects.create(owner=self.staff, name="s2")
        row = AIRequest.objects.create(store=store, task_type="REASONING", model="qwq:32b", prompt_id="p", prompt_version="1",
                                       via="local", fell_back=False)
        data = AIRequestSerializer(row).data
        self.assertEqual(data["answer_label"], "لوکال (qwq:32b)")
        self.assertEqual(data["via"], "local")
