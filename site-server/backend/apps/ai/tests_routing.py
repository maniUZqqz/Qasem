"""Routing after the two owner-reported defects.

Bug 10 — the store chat said «سیاست داده‌ی این فروشگاه اجازه‌ی استفاده از هیچ
سرویس TEXT را نمی‌دهد» although a processing node with Ollama was online and an
API was configured. With no ModelProvider rows, `.env` produced exactly ONE
candidate (the API, because AI_MODE_TEXT=api), and an API may not see customer
messages — so nothing was left. Ollama on our own processing node is local and
must be a candidate alongside the API.

Bug 12 — the content page sent `qwen3-vl:30b` (an Ollama tag from .env) to the
OpenAI-compatible API, which answered `model_not_supported`. The provider now
decides which model names apply to it, and an Ollama provider with no local
Ollama reaches the processing node through the compute queue.
"""
import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.compute import services as compute
from apps.compute.models import ComputeNode
from apps.stores.models import Store
from services.ai import factory, gateway, models_registry, ollama_remote, providers
from services.ai.ollama import OllamaError, OllamaProvider, OllamaTimeout, OllamaUnavailable
from services.ai.openai_compat import OpenAICompatProvider

from .models import AIRequest, ModelProvider, StoreAIPolicy
from .services import recorded_json_call

TMP = tempfile.mkdtemp(prefix="nm-ai-routing-test-")

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

#: The site server as it is deployed: text via Metis, no Ollama on the box,
#: the processing node registered through apps.compute.
SITE_SERVER = {
    **settings.UPMARKET_AI,
    "AI_MODE_TEXT": "api",
    "AI_API_BASE_URL": "https://api.example.ir/openai/v1",
    "AI_API_KEY": "k",
    "AI_API_MODEL_TEXT": "gpt-4o-mini",
    "AI_API_MODEL_VISION": "gpt-4o-mini",
    "OLLAMA_BASE_URL": "agent://any",
    "MODEL_REASONING": "qwq:32b",
    "MODEL_VISION": "qwen3-vl:30b",
    "MODEL_FALLBACKS": ["qwen3-vl:30b", "qwen3-coder:30b"],
}


def _node(name="gpu-1", models=("qwq:32b", "qwen3-vl:30b", "qwen3-coder:30b"), online=True):
    return ComputeNode.objects.create(
        name=name,
        capabilities={"ollama": True, "ollama_models": list(models), "gpu": "RTX 3060"},
        last_seen=timezone.now() if online else None,
    )


def _node_answers(node, answer):
    """A stand-in for the processing node: claims the queued job, uploads
    `ollama.json` with Ollama's answer and finishes — inside `compute.wait`."""

    def fake_wait(job, timeout_s=None, poll=2.0, on_tick=None):
        claimed = compute.claim(node)
        assert claimed is not None and claimed.pk == job.pk, "the node did not get the job"
        compute.output_path(job, ollama_remote.OUTPUT_NAME).write_text(
            json.dumps(answer, ensure_ascii=False), encoding="utf-8",
        )
        return compute.finish(job, node, True, meta={"primary": ollama_remote.OUTPUT_NAME})

    return fake_wait


# ---------------------------------------------------------------------------
# Bug 10 — resolution with no admin rows
# ---------------------------------------------------------------------------


@override_settings(UPMARKET_AI=SITE_SERVER)
class EnvDefaultsResolutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه ۲")

    def test_api_mode_offers_both_the_api_and_ollama(self):
        kinds = [c.kind for c in providers.candidates(providers.TEXT)]
        self.assertEqual(kinds, ["OPENAI", "OLLAMA"])
        self.assertEqual([c.kind for c in providers.candidates(providers.VISION)], ["OPENAI", "OLLAMA"])

    def test_product_copy_still_goes_to_the_api_first(self):
        chosen = gateway.resolve(providers.TEXT, self.store, gateway.PRODUCT)
        self.assertEqual(chosen.kind, "OPENAI")
        self.assertEqual(chosen.model_name, "gpt-4o-mini")

    def test_customer_messages_resolve_to_ollama_on_the_processing_node(self):
        """The exact failure the owner saw: previously PolicyBlocked."""
        chosen = gateway.resolve(providers.TEXT, self.store, gateway.CUSTOMER)
        self.assertEqual(chosen.kind, "OLLAMA")
        self.assertTrue(chosen.is_local)
        self.assertEqual(chosen.base_url, "agent://any")
        self.assertEqual(chosen.model_name, "qwq:32b")

    def test_local_only_store_gets_ollama_for_everything(self):
        StoreAIPolicy.objects.create(store=self.store, mode=StoreAIPolicy.Mode.LOCAL_ONLY)
        self.assertEqual(gateway.resolve(providers.TEXT, self.store, gateway.PRODUCT).kind, "OLLAMA")
        self.assertEqual(gateway.resolve(providers.VISION, self.store, gateway.PRODUCT).kind, "OLLAMA")

    def test_explain_shows_text_usable_for_customer_data(self):
        rows = {r["capability"]: r for r in gateway.explain(self.store, gateway.CUSTOMER)}
        self.assertFalse(rows["TEXT"]["blocked"])
        self.assertTrue(rows["TEXT"]["local"])
        self.assertEqual(rows["TEXT"]["data_location"], "ON_PREMISE")

    @override_settings(UPMARKET_AI={**SITE_SERVER, "AI_MODE_TEXT": "local"})
    def test_local_mode_puts_ollama_first_and_keeps_the_api_behind_it(self):
        kinds = [c.kind for c in providers.candidates(providers.TEXT)]
        self.assertEqual(kinds, ["OLLAMA", "OPENAI"])
        self.assertEqual(gateway.resolve(providers.TEXT, self.store).kind, "OLLAMA")

    @override_settings(UPMARKET_AI={**SITE_SERVER, "AI_API_BASE_URL": ""})
    def test_without_an_api_only_ollama_is_offered(self):
        self.assertEqual([c.kind for c in providers.candidates(providers.TEXT)], ["OLLAMA"])

    def test_admin_ollama_row_with_blank_address_uses_the_processing_node(self):
        """What the owner creates in the admin: kind=Ollama, address empty."""
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OLLAMA,
            name="Ollama سرور پردازش", model_name="qwq:32b", priority=1,
        )
        chosen = gateway.resolve(providers.TEXT, self.store, gateway.CUSTOMER)
        self.assertEqual(chosen.name, "Ollama سرور پردازش")
        self.assertEqual(chosen.base_url, "agent://any")
        self.assertTrue(chosen.is_local)

    def test_env_api_default_still_never_sees_customer_messages(self):
        api = providers.candidates(providers.TEXT)[0]
        self.assertIsNotNone(gateway.check(api, gateway.policy_for(self.store), gateway.CUSTOMER))


# ---------------------------------------------------------------------------
# Bug 12 — which model name goes to which provider
# ---------------------------------------------------------------------------


class ModelSelectionTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("picker", password="x")
        self.store = Store.objects.create(owner=user, name="انتخاب مدل")

    def _call(self, provider, models):
        return recorded_json_call(
            store=self.store, task_type=AIRequest.TaskType.REASONING,
            prompt_id="p", prompt_version="1", provider=provider, models=models, prompt="hi",
        )

    def test_openai_compat_replaces_ollama_tags_with_its_own_model(self):
        provider = OpenAICompatProvider("https://api.example.ir/openai/v1", "k", model="gpt-4o-mini")
        self.assertEqual(provider.select_models(["qwq:32b", "qwen3-vl:30b"]), ["gpt-4o-mini"])

    def test_openai_compat_without_a_model_keeps_the_candidates(self):
        provider = OpenAICompatProvider("https://api.example.ir/openai/v1", "k", model="")
        self.assertEqual(provider.select_models(["m1", "m2"]), ["m1", "m2"])

    @override_settings(UPMARKET_AI={**settings.UPMARKET_AI, "OLLAMA_BASE_URL": "http://127.0.0.1:11434"})
    def test_ollama_keeps_the_router_list_with_its_row_model_first(self):
        provider = OllamaProvider(model="qwq:32b")
        self.assertEqual(provider.select_models(["qwq:32b", "qwen3-vl:30b"]), ["qwq:32b", "qwen3-vl:30b"])
        provider = OllamaProvider(model="qwen3:30b")
        self.assertEqual(provider.select_models(["qwq:32b"]), ["qwen3:30b", "qwq:32b"])

    def test_recorded_call_sends_the_api_its_own_model_and_audits_it(self):
        provider = OpenAICompatProvider("https://api.example.ir/openai/v1", "k", model="gpt-4o-mini")
        seen = []

        def fake_generate(prompt, *, model=None, **kw):
            seen.append(model)
            return '{"summary": "ok"}'

        with patch.object(provider, "generate", side_effect=fake_generate):
            parsed, row = self._call(provider, ["qwq:32b", "qwen3-vl:30b"])
        self.assertEqual(parsed, {"summary": "ok"})
        self.assertEqual(seen, ["gpt-4o-mini"])
        self.assertEqual(row.model, "gpt-4o-mini")

    def test_a_provider_without_the_hook_keeps_the_router_list(self):
        provider = MagicMock()
        provider.generate_json.return_value = ({"ok": 1}, "{}")
        _, row = self._call(provider, ["qwq:32b"])
        self.assertEqual(row.model, "qwq:32b")
        provider.generate_json.assert_called_once()
        self.assertEqual(provider.generate_json.call_args.args[0], "qwq:32b")


# ---------------------------------------------------------------------------
# Ollama through the compute queue
# ---------------------------------------------------------------------------


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True, UPMARKET_AI=SITE_SERVER)
class RemoteOllamaTests(TestCase):
    def setUp(self):
        self.node = _node()

    def test_agent_url_means_remote(self):
        self.assertTrue(OllamaProvider().is_remote)
        self.assertTrue(ollama_remote.use_remote("agent://any"))
        self.assertTrue(ollama_remote.available())

    def test_generate_goes_through_the_queue_and_returns_ollama_text(self):
        answer = {"model": "qwq:32b", "response": "<think>hm</think>سلام! چطور کمک کنم؟", "done": True,
                  "done_reason": "stop"}
        with patch.object(compute, "wait", side_effect=_node_answers(self.node, answer)):
            text = OllamaProvider().generate("qwq:32b", "سلام", system="You are a shop", options={"num_predict": 50})
        self.assertEqual(text, "سلام! چطور کمک کنم؟")
        job = self.node.jobs.get()
        self.assertEqual(job.kind, "ollama.generate")
        self.assertEqual(job.state, "COMPLETED")
        self.assertEqual(job.payload["model"], "qwq:32b")
        self.assertEqual(job.payload["prompt"], "سلام")
        self.assertEqual(job.payload["system"], "You are a shop")
        self.assertEqual(job.payload["path"], "/api/generate")
        self.assertIs(job.payload["stream"], False)
        self.assertEqual(job.payload["options"]["num_predict"], 50)
        self.assertNotIn("images", job.payload)

    def test_images_travel_as_input_files_not_inline_base64(self):
        encoded = base64.b64encode(PNG).decode("ascii")
        answer = {"response": '{"objects": ["bag"]}', "done": True, "done_reason": "stop"}
        with patch.object(compute, "wait", side_effect=_node_answers(self.node, answer)):
            parsed, raw = OllamaProvider().generate_json("qwen3-vl:30b", "describe", images=[encoded])
        self.assertEqual(parsed, {"objects": ["bag"]})
        job = self.node.jobs.get()
        self.assertEqual(job.payload["images"], ["image_1.png"])
        self.assertEqual(job.payload["format"], "json")
        self.assertIn("image_1.png", job.inputs)
        stored = compute.job_root(job) / job.inputs["image_1.png"]
        self.assertEqual(stored.read_bytes(), PNG)

    def test_no_node_online_is_reported_as_ollama_unavailable(self):
        ComputeNode.objects.update(last_seen=None)
        with self.assertRaises(OllamaUnavailable) as caught:
            OllamaProvider().generate("qwq:32b", "سلام")
        self.assertIn("سرورِ پردازش", str(caught.exception))

    def test_node_timeout_and_failure_map_to_the_ollama_error_family(self):
        with patch.object(compute, "wait", side_effect=compute.ComputeTimeout("slow")):
            with self.assertRaises(OllamaTimeout):
                OllamaProvider().generate("qwq:32b", "x")
        with patch.object(compute, "wait", side_effect=compute.ComputeFailed("ollama service is not reachable at http://127.0.0.1:11434")):
            with self.assertRaises(OllamaUnavailable):
                OllamaProvider().generate("qwq:32b", "x")
        with patch.object(compute, "wait", side_effect=compute.ComputeFailed("/api/generate -> HTTP 404 model not found")):
            with self.assertRaises(OllamaError) as caught:
                OllamaProvider().generate("qwq:32b", "x")
        self.assertNotIsInstance(caught.exception, OllamaUnavailable)

    def test_registry_lists_the_models_the_node_reported(self):
        names = [m["name"] for m in models_registry.installed()]
        self.assertEqual(names, ["qwq:32b", "qwen3-vl:30b", "qwen3-coder:30b"])
        self.assertEqual(models_registry.candidates("REASONING")[:2], ["qwq:32b", "qwen3-vl:30b"])
        self.assertEqual(models_registry.candidates("VISION")[0], "qwen3-vl:30b")
        self.assertNotIn("qwq:32b", models_registry.candidates("VISION"))

    def test_health_probe_speaks_about_the_node(self):
        resolved = providers.candidates(providers.TEXT)[1]
        ok, detail = factory.health(resolved)
        self.assertTrue(ok, detail)
        self.assertIn("gpu-1", detail)
        missing = providers.Resolved(
            capability=providers.TEXT, kind="OLLAMA", name="x", base_url="agent://any", api_key="",
            model_name="llama9:1b", timeout_s=10,
        )
        ok, detail = factory.health(missing)
        self.assertFalse(ok)
        self.assertIn("نصب نیست", detail)

    def test_gateway_client_for_customer_data_is_the_remote_ollama(self):
        user = User.objects.create_user("chat", password="x")
        store = Store.objects.create(owner=user, name="چت")
        client = gateway.text_provider(store, gateway.CUSTOMER)
        self.assertIsInstance(client, OllamaProvider)
        self.assertTrue(client.is_remote)
        self.assertEqual(client.model, "qwq:32b")


# ---------------------------------------------------------------------------
# Vision through an OpenAI-compatible API
# ---------------------------------------------------------------------------


class OpenAICompatImagesTests(TestCase):
    def test_base64_images_become_data_urls(self):
        provider = OpenAICompatProvider("https://api.example.ir/openai/v1", "k", model="gpt-4o-mini")
        encoded = base64.b64encode(PNG).decode("ascii")
        messages = provider._messages("what is this", images=[encoded])
        part = messages[-1]["content"][1]
        self.assertEqual(part["type"], "image_url")
        self.assertTrue(part["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_file_paths_still_work(self):
        provider = OpenAICompatProvider("https://api.example.ir/openai/v1", "k", model="gpt-4o-mini")
        path = Path(TMP) / "ref.png"
        path.write_bytes(PNG)
        messages = provider._messages("look", images=[str(path)])
        self.assertTrue(messages[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
