"""
The model-fallback path (beter.md v2 #3).

A dense 32B model does not fit in 12 GB of VRAM, so it can time out or return
a 500 after ten minutes. Losing the whole feature to that is not acceptable —
the call moves on to the next model that is installed, and every attempt stays
in the audit trail.
"""
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.stores.models import Store
from services.ai.ollama import OllamaError, OllamaTimeout

from .models import AIRequest
from .services import recorded_json_call

ANSWER = {"summary": "ok"}


def _provider(*side_effects):
    provider = MagicMock()
    provider.generate_json.side_effect = side_effects
    return provider


class ModelFallbackTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("grace", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=user, name="Grace Shop")

    def _call(self, provider, models):
        return recorded_json_call(
            store=self.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id="test_prompt",
            prompt_version="1",
            provider=provider,
            models=models,
            prompt="hello",
        )

    @patch("apps.ai.services.gpu.unload_ollama_models")
    def test_second_model_is_used_when_the_first_times_out(self, unload):
        provider = _provider(OllamaTimeout("too slow"), (ANSWER, '{"summary": "ok"}'))
        parsed, request_row = self._call(provider, ["qwq:32b", "qwen3-vl:30b"])

        self.assertEqual(parsed, ANSWER)
        self.assertEqual(request_row.model, "qwen3-vl:30b")
        self.assertEqual(provider.generate_json.call_count, 2)
        # the dead model must be evicted before the next one loads
        unload.assert_called_once_with(except_model="qwen3-vl:30b")

    @patch("apps.ai.services.gpu.unload_ollama_models")
    def test_every_attempt_is_audited(self, _unload):
        provider = _provider(OllamaTimeout("too slow"), (ANSWER, "{}"))
        self._call(provider, ["qwq:32b", "qwen3-vl:30b"])

        rows = list(AIRequest.objects.order_by("id"))
        self.assertEqual([row.model for row in rows], ["qwq:32b", "qwen3-vl:30b"])
        self.assertEqual(rows[0].status, AIRequest.Status.TIMEOUT)
        self.assertEqual(rows[1].status, AIRequest.Status.OK)

    @patch("apps.ai.services.gpu.unload_ollama_models")
    def test_last_error_is_raised_when_every_model_fails(self, _unload):
        provider = _provider(OllamaTimeout("slow"), OllamaError("out of memory"))
        with self.assertRaises(OllamaError) as caught:
            self._call(provider, ["qwq:32b", "qwen3-vl:30b"])
        self.assertIn("out of memory", str(caught.exception))

    @patch("apps.ai.services.gpu.unload_ollama_models")
    def test_fallback_can_be_switched_off(self, _unload):
        provider = _provider(OllamaTimeout("slow"), (ANSWER, "{}"))
        disabled = {**settings.UPMARKET_AI, "MODEL_FALLBACK_ENABLED": False}
        with override_settings(UPMARKET_AI=disabled):
            with self.assertRaises(OllamaTimeout):
                self._call(provider, ["qwq:32b", "qwen3-vl:30b"])
        self.assertEqual(provider.generate_json.call_count, 1)

    def test_a_single_model_name_still_works(self):
        provider = _provider((ANSWER, "{}"))
        parsed, request_row = recorded_json_call(
            store=self.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id="test_prompt",
            prompt_version="1",
            provider=provider,
            model="qwq:32b",
            prompt="hello",
        )
        self.assertEqual(parsed, ANSWER)
        self.assertEqual(request_row.model, "qwq:32b")

    def test_no_model_at_all_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            recorded_json_call(
                store=self.store,
                task_type=AIRequest.TaskType.REASONING,
                prompt_id="test_prompt",
                prompt_version="1",
                provider=_provider((ANSWER, "{}")),
                models=[],
                prompt="hello",
            )
