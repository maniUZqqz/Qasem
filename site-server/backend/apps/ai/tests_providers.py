"""Switching a capability between our GPU and an API must be a data change."""
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from services.ai import factory, gateway, providers
from services.ai.ollama import OllamaProvider
from services.ai.openai_compat import OpenAICompatProvider

from .models import ModelProvider


#: پیکربندی «این دستگاه هر سه کار را روی سخت‌افزار خودش می‌کند».
#:
#: سه تست پایین دقیقاً همین حالت را ادعا می‌کنند، ولی تا پیش از این
#: پیکربندی را از `.env` **دستگاهِ اجراکننده** می‌خواندند. روی ماشینی که
#: `start.bat` رویش حالت API را انتخاب کرده بود شکست می‌خوردند — با اینکه
#: کد در هر دو حالت درست کار می‌کند.
#:
#: تستِ متن از این هم شکننده‌تر بود: `.env` این پروژه `AI_MODE_TEXT=api`
#: دارد و آن تست فقط چون `AI_API_BASE_URL` خالی مانده بود سبز می‌ماند —
#: یعنی سبزیِ تصادفی. اولین کسی که آن متغیر را پر می‌کرد، تستی را قرمز
#: می‌دید که هیچ ربطی به تغییرش نداشت.
#:
#: تستی که جوابش به تنظیمات ماشین بستگی داشته باشد، چیزی را که ادعا
#: می‌کند نمی‌سنجد.
LOCAL_GPU = {
    **settings.UPMARKET_AI,
    "AI_MODE_TEXT": "local",
    "AI_MODE_IMAGE": "",
    "AI_MODE_VIDEO": "",
    "AI_API_BASE_URL": "",
}


class ResolutionTests(TestCase):
    @override_settings(UPMARKET_AI=LOCAL_GPU)
    def test_no_rows_falls_back_to_env_defaults(self):
        chosen = providers.primary(providers.TEXT)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.kind, "OLLAMA")
        self.assertTrue(chosen.is_local)

    def test_a_row_overrides_the_default(self):
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT,
            kind=ModelProvider.Kind.OPENAI,
            name="OpenRouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-test",
            model_name="anthropic/claude-sonnet-4",
        )
        chosen = providers.primary(providers.TEXT)
        self.assertEqual(chosen.kind, "OPENAI")
        self.assertEqual(chosen.model_name, "anthropic/claude-sonnet-4")
        self.assertFalse(chosen.is_local)

    def test_priority_decides_the_order(self):
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OPENAI,
            name="پشتیبان", base_url="https://api.example.com/v1",
            model_name="gpt-4o-mini", priority=200,
        )
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OLLAMA,
            name="لوکال", model_name="qwq:32b", priority=10,
        )
        order = [p.name for p in providers.candidates(providers.TEXT)]
        self.assertEqual(order, ["لوکال", "پشتیبان"])

    @override_settings(UPMARKET_AI=LOCAL_GPU)
    def test_inactive_rows_are_skipped(self):
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.IMAGE, kind=ModelProvider.Kind.OPENAI,
            name="خاموش", base_url="https://api.example.com/v1",
            model_name="dall-e-3", is_active=False,
        )
        chosen = providers.primary(providers.IMAGE)
        self.assertEqual(chosen.kind, "COMFYUI")  # back to the .env default

    @override_settings(UPMARKET_AI=LOCAL_GPU)
    def test_uses_own_gpu_reflects_the_choice(self):
        self.assertTrue(providers.uses_own_gpu(providers.VIDEO))
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.VIDEO, kind=ModelProvider.Kind.REPLICATE,
            name="ابری", base_url="https://api.replicate.com/v1/predictions",
            api_key="r8-test", model_name="wan-2.2", priority=1,
        )
        self.assertFalse(providers.uses_own_gpu(providers.VIDEO))

    def test_empty_base_url_inherits_from_env(self):
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OLLAMA,
            name="لوکال", model_name="qwq:32b", base_url="",
        )
        chosen = providers.primary(providers.TEXT)
        self.assertTrue(chosen.base_url)  # filled in from settings


class FactoryTests(TestCase):
    """Which client class a row turns into. Routed through the gateway because
    that is now the only way to get one — see apps/ai/tests_boundary.py."""

    def setUp(self):
        from django.contrib.auth.models import User

        from apps.stores.models import Store

        user = User.objects.create_user("factory-owner", password="x")
        self.store = Store.objects.create(owner=user, name="فروشگاه سازنده")

    def test_ollama_row_builds_the_local_client(self):
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OLLAMA,
            name="لوکال", model_name="qwq:32b",
        )
        self.assertIsInstance(gateway.text_provider(self.store), OllamaProvider)

    def test_api_row_builds_the_http_client(self):
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OPENAI,
            name="ابری", base_url="https://api.example.com/v1",
            api_key="sk-x", model_name="gpt-4o-mini",
        )
        client = gateway.text_provider(self.store)
        self.assertIsInstance(client, OpenAICompatProvider)
        self.assertEqual(client.model, "gpt-4o-mini")
        self.assertEqual(client.api_key, "sk-x")

    @override_settings(UPMARKET_AI=LOCAL_GPU)
    def test_vision_and_text_resolve_independently(self):
        ModelProvider.objects.create(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OPENAI,
            name="متن ابری", base_url="https://api.example.com/v1", model_name="gpt-4o-mini",
        )
        self.assertIsInstance(gateway.text_provider(self.store), OpenAICompatProvider)
        self.assertIsInstance(gateway.vision_provider(self.store), OllamaProvider)


class ValidationTests(TestCase):
    def test_external_provider_requires_a_url(self):
        from django.core.exceptions import ValidationError

        row = ModelProvider(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.OPENAI,
            name="بی‌آدرس", model_name="gpt-4o-mini",
        )
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_comfyui_cannot_serve_text(self):
        from django.core.exceptions import ValidationError

        row = ModelProvider(
            capability=ModelProvider.Capability.TEXT, kind=ModelProvider.Kind.COMFYUI,
            name="غلط", model_name="x",
        )
        with self.assertRaises(ValidationError):
            row.full_clean()


class OpenAICompatTests(TestCase):
    def _reply(self, content):
        class R:
            status_code = 200

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": content}}]}

        return R()

    @patch("services.ai.openai_compat.requests.post")
    def test_generate_returns_text(self, mock_post):
        mock_post.return_value = self._reply("سلام")
        client = OpenAICompatProvider("https://api.example.com/v1", "k", "m")
        self.assertEqual(client.generate("hi"), "سلام")

    @patch("services.ai.openai_compat.requests.post")
    def test_generate_json_parses_a_fenced_block(self, mock_post):
        mock_post.return_value = self._reply('```json\n{"a": 1}\n```')
        client = OpenAICompatProvider("https://api.example.com/v1", "k", "m")
        parsed, raw = client.generate_json("m", "hi")
        self.assertEqual(parsed, {"a": 1})
        self.assertIn("{", raw)

    @patch("services.ai.openai_compat.requests.post")
    def test_bad_key_is_reported_not_retried(self, mock_post):
        class R:
            status_code = 401
            text = "unauthorized"

        mock_post.return_value = R()
        client = OpenAICompatProvider("https://api.example.com/v1", "bad", "m")
        with self.assertRaises(Exception) as ctx:
            client.generate("hi")
        self.assertIn("۴۰۱", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 1)  # no pointless retries

    def test_missing_url_fails_clearly(self):
        client = OpenAICompatProvider("", "k", "m")
        with self.assertRaises(Exception):
            client.generate("hi")


class ProviderContractTests(TestCase):
    """The local and remote providers must be interchangeable in fact, not only
    in intent.

    This exists because they were not. `_single_call` passes the model
    positionally and unpacks `(parsed, raw)`; the API provider took a
    keyword-only model and returned a bare dict, so switching TEXT to an API
    raised a TypeError before any request left the machine. Every test at the
    layer above mocks the provider, so nothing there noticed — only a run
    against a real ModelProvider row did.
    """

    def test_generate_json_signatures_line_up(self):
        import inspect

        local = inspect.signature(OllamaProvider.generate_json).parameters
        remote = inspect.signature(OpenAICompatProvider.generate_json).parameters

        # the two positional arguments the audited call site relies on
        self.assertEqual(list(local)[:3], ["self", "model", "prompt"])
        self.assertEqual(list(remote)[:3], ["self", "model", "prompt"])

        # every keyword the call site passes must exist on both
        for keyword in ("system", "images", "options", "timeout"):
            self.assertIn(keyword, local, f"OllamaProvider lost `{keyword}`")
            self.assertIn(keyword, remote, f"OpenAICompatProvider lost `{keyword}`")

    @patch("services.ai.openai_compat.requests.post")
    def test_remote_provider_works_through_the_audited_call_site(self, mock_post):
        """The exact call `apps.ai.services._single_call` makes."""

        class R:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        mock_post.return_value = R()
        client = OpenAICompatProvider("https://api.example.com/v1", "k", "m")
        parsed, raw = client.generate_json(
            "m", "prompt", system=None, images=None, options=None
        )
        self.assertEqual(parsed, {"ok": True})
        self.assertTrue(raw)
