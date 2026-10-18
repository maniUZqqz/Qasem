"""Per-capability engine choice, and what the launcher does with it.

The point of splitting text/image/video: choosing an API for video alone must
not stop Ollama, and choosing one for text alone must not stop ComfyUI. The old
all-or-nothing switch got that wrong in both directions.
"""
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.jobs.management.commands import aisetup
from services.ai import providers


def ai(**overrides):
    """UPMARKET_AI with a few keys changed — never replaced wholesale, or the
    ComfyUI and Ollama URLs vanish and everything fails for the wrong reason."""
    from django.conf import settings

    return {**settings.UPMARKET_AI, **overrides}


class PerCapabilityModeTests(TestCase):
    def test_everything_local_by_default(self):
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="", AI_MODE_IMAGE="", AI_MODE_VIDEO="", AI_API_BASE_URL="",
        )):
            self.assertEqual(providers.local_services_needed(), {"ollama", "comfyui"})

    def test_text_on_api_still_needs_comfyui(self):
        """The old switch stopped ComfyUI too, which left a machine that had
        chosen an API for captions unable to render anything."""
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="api", AI_API_BASE_URL="https://x/v1",
            AI_MODE_IMAGE="local", AI_MODE_VIDEO="local",
        )):
            self.assertEqual(providers.local_services_needed(), {"comfyui"})

    def test_image_and_video_on_api_still_need_ollama(self):
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="local", AI_API_BASE_URL="",
            AI_MODE_IMAGE="api", AI_MODE_VIDEO="api", MEDIA_API_TOKEN="r8-x",
        )):
            self.assertEqual(providers.local_services_needed(), {"ollama"})

    def test_video_on_api_alone_still_needs_comfyui_for_images(self):
        """The case a single switch cannot express at all."""
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="local", AI_API_BASE_URL="",
            AI_MODE_IMAGE="local", AI_MODE_VIDEO="api", MEDIA_API_TOKEN="r8-x",
        )):
            self.assertEqual(providers.local_services_needed(), {"ollama", "comfyui"})

    def test_all_three_on_api_needs_no_gpu_at_all(self):
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="api", AI_API_BASE_URL="https://x/v1",
            AI_MODE_IMAGE="api", AI_MODE_VIDEO="api", MEDIA_API_TOKEN="r8-x",
        )):
            self.assertEqual(providers.local_services_needed(), set())

    def test_api_without_credentials_falls_back_to_local(self):
        """A launcher that skipped ComfyUI on the strength of a setting with no
        token behind it would leave the product unable to render, with no error
        until the first job."""
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_IMAGE="api", AI_MODE_VIDEO="api", MEDIA_API_TOKEN="",
            MEDIA_API_BASE_URL="", AI_MODE_TEXT="local", AI_API_BASE_URL="",
        )):
            self.assertIn("comfyui", providers.local_services_needed())

    def test_the_old_shortcut_still_means_text_on_api(self):
        """`AI_API_BASE_URL` alone, with no explicit mode — how every existing
        install is configured."""
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="", AI_API_BASE_URL="https://x/v1",
        )):
            self.assertTrue(providers.api_mode(providers.TEXT))

    def test_explicit_local_beats_the_old_shortcut(self):
        """Someone who answered "this machine" must not be overridden by a
        leftover URL in .env."""
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="local", AI_API_BASE_URL="https://x/v1",
        )):
            self.assertFalse(providers.api_mode(providers.TEXT))

    def test_vision_follows_text(self):
        """Same Ollama, same model host — splitting them would let a machine
        stop Ollama for captions while still needing it for photos."""
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="api", AI_API_BASE_URL="https://x/v1",
        )):
            self.assertTrue(providers.api_mode(providers.VISION))

    def test_api_mode_with_no_argument_still_means_text(self):
        """Old call sites pass nothing."""
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="api", AI_API_BASE_URL="https://x/v1",
        )):
            self.assertTrue(providers.api_mode())


class EnvWritingTests(TestCase):
    def test_existing_keys_are_replaced_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# my notes\nAI_MODE_TEXT=local\nOTHER=keep\n", encoding="utf-8"
            )
            with patch.object(aisetup, "ENV_PATH", path):
                aisetup.write_env({"AI_MODE_TEXT": "api", "AI_MODE_VIDEO": "local"})
                text = path.read_text(encoding="utf-8")

        self.assertEqual(text.count("AI_MODE_TEXT="), 1)
        self.assertIn("AI_MODE_TEXT=api", text)
        self.assertIn("AI_MODE_VIDEO=local", text)

    def test_comments_and_unknown_keys_survive(self):
        """The operator's own notes are not ours to delete."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# do not lose me\nZARINPAL_MERCHANT_ID=abc\n", encoding="utf-8"
            )
            with patch.object(aisetup, "ENV_PATH", path):
                aisetup.write_env({"AI_MODE_TEXT": "api"})
                text = path.read_text(encoding="utf-8")

        self.assertIn("# do not lose me", text)
        self.assertIn("ZARINPAL_MERCHANT_ID=abc", text)

    def test_a_missing_env_file_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / ".env"
            with patch.object(aisetup, "ENV_PATH", path):
                aisetup.write_env({"AI_MODE_TEXT": "local"})
            self.assertTrue(path.exists())


class LauncherOutputTests(TestCase):
    """What start.bat parses. A change in shape here silently breaks startup."""

    def test_needs_prints_a_space_separated_list(self):
        out = StringIO()
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="local", AI_MODE_IMAGE="local", AI_MODE_VIDEO="local",
            AI_API_BASE_URL="",
        )):
            call_command("aimode", "--needs", stdout=out)
        self.assertEqual(out.getvalue(), "comfyui ollama")

    def test_needs_prints_none_when_nothing_is_local(self):
        out = StringIO()
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="api", AI_API_BASE_URL="https://x/v1",
            AI_MODE_IMAGE="api", AI_MODE_VIDEO="api", MEDIA_API_TOKEN="r8-x",
        )):
            call_command("aimode", "--needs", stdout=out)
        self.assertEqual(out.getvalue(), "none")

    def test_overall_mode_says_local_when_anything_is_local(self):
        """A machine that sends text to an API but renders video here is not in
        "api" mode from the launcher's point of view — it still needs a GPU."""
        out = StringIO()
        with override_settings(UPMARKET_AI=ai(
            AI_MODE_TEXT="api", AI_API_BASE_URL="https://x/v1",
            AI_MODE_IMAGE="local", AI_MODE_VIDEO="local",
        )):
            call_command("aimode", stdout=out)
        self.assertEqual(out.getvalue(), "local")

    def test_no_console_does_not_crash_the_launcher(self):
        """`input()` hitting EOF used to take the whole startup down with a
        traceback. A scheduled task or a piped run must still boot."""
        out = StringIO()
        with patch("builtins.input", side_effect=EOFError):
            with patch.object(aisetup.Command, "_interactive", return_value=True):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / ".env"
                    with patch.object(aisetup, "ENV_PATH", path):
                        call_command("aisetup", stdout=out)
                        self.assertIn("AI_MODE_TEXT=local", path.read_text(encoding="utf-8"))
