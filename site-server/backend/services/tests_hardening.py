"""
Tests for the hardening added after the v2 bug report (beter.md v2).

Covered here: model selection restricted to installed models, the VRAM/timeout
request options, market-prompt compaction and source-image preprocessing.
Job reaping, cancelling and queue dispatch live in apps/jobs/tests.py.
"""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from services.ai import models_registry
from services.ai.ollama import OllamaError, OllamaProvider, OllamaTimeout
from services.ai.prompts import market_analysis as market_prompts
from services.ai.router import TASK_REASONING, models_for


class ModelRegistryTests(SimpleTestCase):
    """Only models that are really pulled on the machine may be used."""

    INSTALLED = [
        {"name": "qwen3-vl:30b", "size": 19_000_000_000},
        {"name": "nomic-embed-text:latest", "size": 270_000_000},
        {"name": "llama3.2:3b", "size": 2_000_000_000},
    ]

    def _with(self, models):
        return patch.object(models_registry, "installed", return_value=models)

    def test_missing_preferred_model_is_skipped(self):
        # qwq:32b is the configured preference but is NOT pulled here
        with self._with(self.INSTALLED):
            chosen = models_registry.candidates("REASONING")
        self.assertNotIn("qwq:32b", chosen)
        self.assertEqual(chosen[0], "qwen3-vl:30b")

    def test_embedding_models_are_never_offered_for_generation(self):
        with self._with(self.INSTALLED):
            chosen = models_registry.candidates("REASONING")
        self.assertNotIn("nomic-embed-text:latest", chosen)

    def test_configured_preference_wins_over_other_installed_models(self):
        with self._with(self.INSTALLED):
            chosen = models_registry.candidates("REASONING")
        self.assertIn("llama3.2:3b", chosen)
        self.assertLess(chosen.index("qwen3-vl:30b"), chosen.index("llama3.2:3b"))

    def test_vision_tasks_only_get_multimodal_models(self):
        with self._with(self.INSTALLED):
            chosen = models_registry.candidates("VISION")
        self.assertEqual(chosen, ["qwen3-vl:30b"])

    def test_unreachable_ollama_falls_back_to_configured_names(self):
        with self._with([]):
            chosen = models_registry.candidates("REASONING")
        self.assertEqual(chosen[0], "qwq:32b")

    def test_tag_matching_is_tolerant(self):
        self.assertTrue(models_registry._same_model("qwq", "qwq:32b"))
        self.assertTrue(models_registry._same_model("qwq:latest", "qwq:32b"))
        self.assertFalse(models_registry._same_model("qwq:32b", "qwen3-vl:30b"))

    def test_models_for_never_returns_empty(self):
        with self._with([]):
            self.assertTrue(models_for(TASK_REASONING))


#: The HTTP path is what these tests exercise. A server whose .env routes
#: Ollama through the compute queue (OLLAMA_BASE_URL=agent://any) would
#: otherwise send every call there.
LOCAL_OLLAMA = override_settings(
    UPMARKET_AI={**settings.UPMARKET_AI, "OLLAMA_BASE_URL": "http://127.0.0.1:11434"},
)


@LOCAL_OLLAMA
class OllamaResourceOptionTests(SimpleTestCase):
    """VRAM-related request options and the no-retry-on-timeout rule."""

    def _response(self, payload):
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_keep_alive_and_num_ctx_are_sent(self):
        provider = OllamaProvider()
        with patch("services.ai.ollama.requests.post") as post:
            post.return_value = self._response({"response": "hello"})
            provider.generate("m", "hi")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["keep_alive"], settings.UPMARKET_AI["OLLAMA_KEEP_ALIVE"])
        self.assertEqual(payload["options"]["num_ctx"], settings.UPMARKET_AI["OLLAMA_NUM_CTX"])

    def test_timeout_is_not_retried(self):
        # three 600s attempts made a failing model cost half an hour
        provider = OllamaProvider(retries=2, timeout=1)
        with patch(
            "services.ai.ollama.requests.post", side_effect=requests.Timeout("slow")
        ) as post:
            with self.assertRaises(OllamaTimeout):
                provider.generate("m", "hi")
        self.assertEqual(post.call_count, 1)

    def test_connection_errors_are_still_retried(self):
        provider = OllamaProvider(retries=1, timeout=1, backoff=0)
        with patch(
            "services.ai.ollama.requests.post",
            side_effect=requests.ConnectionError("down"),
        ) as post:
            with self.assertRaises(OllamaError):
                provider.generate("m", "hi")
        self.assertEqual(post.call_count, 2)

    def test_json_budget_comes_from_settings(self):
        provider = OllamaProvider()
        with patch("services.ai.ollama.requests.post") as post:
            post.return_value = self._response({"response": '{"a": 1}'})
            provider.generate_json("m", "hi")
        options = post.call_args.kwargs["json"]["options"]
        self.assertEqual(options["num_predict"], settings.UPMARKET_AI["OLLAMA_NUM_PREDICT_JSON"])


class MarketPromptCompactionTests(SimpleTestCase):
    """Prompt size is prefill time; search results are trimmed to the facts."""

    def test_items_are_capped_and_snippets_truncated(self):
        items = [
            {
                "source": "digikala",
                "title": "T" * 400,
                "price_toman": 120000,
                "url": "https://www.example-shop.ir/a/b?utm=1",
                "snippet": "S" * 900,
            }
            for _ in range(40)
        ]
        compact = market_prompts.compact_web_items(items)
        self.assertEqual(len(compact), market_prompts.MAX_WEB_ITEMS)
        entry = compact[0]
        self.assertEqual(entry["site"], "example-shop.ir")
        self.assertLessEqual(len(entry["snippet"]), market_prompts.MAX_SNIPPET_CHARS)
        self.assertLessEqual(len(entry["title"]), 120)
        self.assertNotIn("url", entry)

    def test_prices_are_preserved_because_the_analysis_cites_them(self):
        compact = market_prompts.compact_web_items(
            [{"source": "torob", "title": "x", "price_toman": 99000, "url": ""}]
        )
        self.assertEqual(compact[0]["price_toman"], 99000)


class SourceImagePreprocessTests(SimpleTestCase):
    """img2img inherits the input's quality, so the input is fixed first."""

    def test_small_photo_is_upscaled_to_the_workflow_size(self):
        from PIL import Image

        from services.imaging.preprocess import prepare_source_image

        tmp = Path(tempfile.mkdtemp(prefix="upmarket-preproc-"))
        try:
            source = tmp / "tiny.jpg"
            Image.new("RGB", (240, 180), (200, 60, 60)).save(source, quality=40)
            out = prepare_source_image(source, tmp / "out.png", 1024, 1024)
            self.assertEqual(out, tmp / "out.png")
            with Image.open(out) as prepared:
                self.assertEqual(prepared.size, (1024, 1024))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unreadable_source_returns_the_original_path(self):
        from services.imaging.preprocess import prepare_source_image

        tmp = Path(tempfile.mkdtemp(prefix="upmarket-preproc-"))
        try:
            broken = tmp / "broken.png"
            broken.write_bytes(b"not an image")
            out = prepare_source_image(broken, tmp / "out.png", 512, 512)
            self.assertEqual(out, broken)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PersianPriceTests(SimpleTestCase):
    """A poster that mixes Latin digits into Persian typography looks unfinished."""

    def test_price_is_rendered_in_persian_digits(self):
        from services.imaging.text_overlay import format_price_fa

        self.assertEqual(format_price_fa(2450000, "IRT"), "۲٬۴۵۰٬۰۰۰ تومان")

    def test_rial_keeps_its_own_label(self):
        from services.imaging.text_overlay import format_price_fa

        self.assertTrue(format_price_fa(1000, "IRR").endswith("ریال"))

    def test_missing_or_zero_price_produces_no_badge(self):
        from services.imaging.text_overlay import format_price_fa

        self.assertEqual(format_price_fa(None), "")
        self.assertEqual(format_price_fa(0), "")
        self.assertEqual(format_price_fa("nope"), "")


class LocalhostIsIPv4Tests(SimpleTestCase):
    """`localhost` costs ~2s per call on Windows (IPv6 first). Measured, not guessed."""

    def test_localhost_urls_are_rewritten(self):
        from config.settings import prefer_ipv4_localhost

        self.assertEqual(
            prefer_ipv4_localhost("http://localhost:11434"), "http://127.0.0.1:11434"
        )
        self.assertEqual(
            prefer_ipv4_localhost("redis://localhost:6379/0"), "redis://127.0.0.1:6379/0"
        )

    def test_remote_and_explicit_ipv6_hosts_are_left_alone(self):
        from config.settings import prefer_ipv4_localhost

        for url in ("http://192.168.10.80:11434", "http://[::1]:11434", "", "not a url"):
            self.assertEqual(prefer_ipv4_localhost(url), url)

    def test_the_running_config_uses_ipv4(self):
        self.assertNotIn("localhost", settings.UPMARKET_AI["OLLAMA_BASE_URL"])
        self.assertNotIn("localhost", settings.CELERY_BROKER_URL)


class ServiceProbeTests(SimpleTestCase):
    """The probe must not declare a LAN service dead on a slow handshake."""

    def test_remote_hosts_get_a_longer_probe_timeout(self):
        from services import net

        net.clear_cache()
        with patch("services.net.socket.create_connection") as connect:
            net.is_listening("http://127.0.0.1:11434")
            local_timeout = connect.call_args.kwargs["timeout"]
            net.clear_cache()
            net.is_listening("http://192.168.10.80:11434")
            remote_timeout = connect.call_args.kwargs["timeout"]
        self.assertLess(local_timeout, remote_timeout)

    def test_a_refused_port_is_reported_as_down_without_raising(self):
        from services import net

        net.clear_cache()
        self.assertFalse(net.is_listening("http://127.0.0.1:9"))


@LOCAL_OLLAMA
class TruncatedAnswerTests(SimpleTestCase):
    """A cut-off answer is a budget problem, not a model problem."""

    def _cut(self, done_reason="length"):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": '{"summary": "نیمه',
            "done": True,
            "done_reason": done_reason,
        }
        return response

    def _full(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": '{"summary": "کامل"}',
            "done": True,
            "done_reason": "stop",
        }
        return response

    def test_a_cut_off_json_answer_is_retried_shorter(self):
        from services.ai.ollama import SHORTER_SUFFIX

        provider = OllamaProvider()
        with patch("services.ai.ollama.requests.post") as post:
            post.side_effect = [self._cut(), self._full()]
            parsed, _raw = provider.generate_json("m", "بنویس")
        self.assertEqual(parsed, {"summary": "کامل"})
        self.assertEqual(post.call_count, 2)
        second_prompt = post.call_args_list[1].kwargs["json"]["prompt"]
        self.assertIn(SHORTER_SUFFIX.strip()[:30], second_prompt)

    def test_a_still_cut_off_retry_salvages_the_partial_answer(self):
        provider = OllamaProvider()
        with patch("services.ai.ollama.requests.post") as post:
            post.side_effect = [self._cut(), self._cut()]
            parsed, _raw = provider.generate_json("m", "بنویس")
        # repaired into valid JSON rather than throwing everything away
        self.assertIn("summary", parsed)

    def test_a_normal_answer_is_never_treated_as_truncated(self):
        provider = OllamaProvider()
        with patch("services.ai.ollama.requests.post") as post:
            post.side_effect = [self._full()]
            parsed, _raw = provider.generate_json("m", "بنویس")
        self.assertEqual(parsed, {"summary": "کامل"})
        self.assertEqual(post.call_count, 1)


class CaptionLengthFallbackTests(SimpleTestCase):
    """An empty caption box reads as a broken app; reuse what we do have."""

    def _validate(self, caption):
        from services.ai.prompts.captions import validate_captions

        parsed = {"captions": [caption]}
        ok, problems = validate_captions(parsed, {"INSTAGRAM"})
        return ok, problems, parsed["captions"]

    def test_a_missing_length_reuses_the_best_available_text(self):
        ok, _problems, cleaned = self._validate(
            {"platform": "INSTAGRAM", "short": "کوتاه", "medium": "متن متوسط و کامل‌تر",
             "long": "", "hashtags": [], "cta": "سفارش بده"}
        )
        self.assertTrue(ok)
        self.assertEqual(cleaned[0]["long"], "متن متوسط و کامل‌تر")

    def test_a_caption_with_no_text_at_all_is_rejected(self):
        ok, problems, _cleaned = self._validate(
            {"platform": "INSTAGRAM", "short": "", "medium": "", "long": "",
             "hashtags": [], "cta": ""}
        )
        self.assertFalse(ok)
        self.assertTrue(any("INSTAGRAM" in str(p) for p in problems))
