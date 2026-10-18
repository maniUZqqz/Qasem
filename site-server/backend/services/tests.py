"""Tests for the service layer (Ollama provider, workflow patching, FFmpeg utils)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from services.ai.ollama import (
    OllamaMalformedOutput,
    OllamaProvider,
    close_truncated_json,
    extract_json_block,
    repair_json,
    strip_reasoning,
)
from services.ai.router import TASK_CODE, TASK_REASONING, TASK_VISION, model_for
from services.comfyui.workflows import WorkflowError, load_workflow, patch_workflow
from services.video.ffmpeg import (
    concat_audio,
    concat_videos,
    extract_last_frame,
    fit_audio,
    make_silence,
    probe_duration,
)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class OllamaProviderTests(SimpleTestCase):
    def test_strip_reasoning_removes_think_blocks(self):
        text = "<think>internal chain of thought</think>{\"a\": 1}"
        self.assertEqual(strip_reasoning(text), '{"a": 1}')

    def test_extract_json_block_repairs_wrapped_json(self):
        raw = 'Here is your answer: {"summary": "خوب", "n": 2} hope it helps'
        self.assertEqual(extract_json_block(raw), {"summary": "خوب", "n": 2})
        self.assertIsNone(extract_json_block("no json here"))

    @patch("services.ai.ollama.requests.post")
    def test_generate_json_parses_response(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": '<think>hmm</think>{"summary": "تست"}'},
            raise_for_status=lambda: None,
        )
        provider = OllamaProvider(retries=0)
        parsed, raw = provider.generate_json("qwq:32b", "test prompt")
        self.assertEqual(parsed, {"summary": "تست"})
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["model"], "qwq:32b")

    @patch("services.ai.ollama.requests.post")
    def test_generate_json_raises_on_garbage(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": "absolutely not json"},
            raise_for_status=lambda: None,
        )
        provider = OllamaProvider(retries=0)
        with self.assertRaises(OllamaMalformedOutput):
            provider.generate_json("qwq:32b", "test prompt")
        # one original call + one self-repair feedback call
        self.assertEqual(mock_post.call_count, 2)

    def test_repair_json_fixes_code_fences_and_trailing_commas(self):
        raw = '```json\n{"a": 1, "b": [1, 2,],}\n```'
        self.assertEqual(repair_json(raw), {"a": 1, "b": [1, 2]})

    def test_repair_json_fixes_missing_comma_between_lines(self):
        raw = '{"a": "یک"\n"b": "دو"}'
        self.assertEqual(repair_json(raw), {"a": "یک", "b": "دو"})

    def test_repair_json_recovers_truncated_output(self):
        # the exact failure mode from beter.md #5: generation cut off mid-object
        raw = '{"captions": [{"platform": "INSTAGRAM", "short": "سلام", "medium": "متن بلندتر'
        parsed = repair_json(raw)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["captions"][0]["platform"], "INSTAGRAM")
        self.assertEqual(parsed["captions"][0]["short"], "سلام")

    def test_close_truncated_json_balances_brackets(self):
        self.assertEqual(
            close_truncated_json('{"a": {"b": [1, 2'), '{"a": {"b": [1, 2]}}'
        )

    @patch("services.ai.ollama.requests.post")
    def test_generate_json_repairs_locally_without_second_call(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": '{"summary": "تست",}'},
            raise_for_status=lambda: None,
        )
        provider = OllamaProvider(retries=0)
        parsed, _ = provider.generate_json("qwq:32b", "test prompt")
        self.assertEqual(parsed, {"summary": "تست"})
        self.assertEqual(mock_post.call_count, 1)

    @patch("services.ai.ollama.requests.post")
    def test_generate_json_asks_model_to_fix_unrepairable_output(self, mock_post):
        responses = [
            {"response": 'کاملاً خراب و بدون آبجکت'},
            {"response": '{"summary": "درست شد"}'},
        ]
        mock_post.side_effect = [
            MagicMock(status_code=200, json=(lambda r=r: r), raise_for_status=lambda: None)
            for r in responses
        ]
        provider = OllamaProvider(retries=0)
        parsed, _ = provider.generate_json("qwq:32b", "test prompt")
        self.assertEqual(parsed, {"summary": "درست شد"})
        self.assertEqual(mock_post.call_count, 2)
        fix_prompt = mock_post.call_args.kwargs["json"]["prompt"]
        self.assertIn("INVALID JSON", fix_prompt)

    def test_market_v3_validator_defaults_and_normalizes_competitors(self):
        from services.ai.prompts.market_analysis import validate_market

        parsed = {
            "observations": [],
            "competitor_positioning": [],
            "common_messaging": [],
            "content_patterns": [],
            "pricing_observations": [],
            "common_customer_concerns": [],
            "content_gaps": [],
            "differentiation_opportunities": [],
            "strategy_summary": "استراتژی",
            "confidence": "low",
            "competitors": [
                {"name": "برند X", "strengths": "قیمت پایین", "price": 120000},
                "garbage-entry",
            ],
        }
        ok, problems = validate_market(parsed)
        self.assertTrue(ok, problems)
        self.assertEqual(parsed["comparison"], [])  # missing → defaulted, not fatal
        self.assertEqual(len(parsed["competitors"]), 1)  # non-dict entries dropped
        competitor = parsed["competitors"][0]
        self.assertEqual(competitor["strengths"], ["قیمت پایین"])  # str → list
        self.assertEqual(competitor["price"], "120000")  # scalar → str
        self.assertEqual(competitor["where_sells"], "")  # missing field filled
        self.assertEqual(parsed["confidence"], "LOW")

    def test_poster_text_overlay_draws_persian_text(self):
        from PIL import Image

        from services.imaging.text_overlay import OverlayError, add_poster_text

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "poster.png"
            Image.new("RGB", (416, 608), (10, 10, 40)).save(src)
            out = Path(tmp) / "poster_text.png"
            result = add_poster_text(
                src, out, headline="کفش رویایی", subline="سبک و راحت", badge="۲۵۰,۰۰۰ تومان"
            )
            self.assertTrue(Path(result).is_file())
            with Image.open(result) as final:
                self.assertEqual(final.size, (416, 608))
                # the dark source must now contain bright headline pixels
                self.assertGreater(final.convert("L").getextrema()[1], 200)
            with self.assertRaises(OverlayError):
                add_poster_text(src, out, headline="", subline="", badge="")

    def test_router_maps_tasks_to_configured_models(self):
        self.assertEqual(model_for(TASK_REASONING), "qwq:32b")
        self.assertEqual(model_for(TASK_VISION), "qwen3-vl:30b")
        self.assertEqual(model_for(TASK_CODE), "qwen3-coder:30b")
        with self.assertRaises(ValueError):
            model_for("NOPE")


class WebResearchTests(SimpleTestCase):
    @patch("services.research.web.requests.get")
    def test_digikala_parsing_converts_rial_to_toman(self, mock_get):
        from services.research.web import search_digikala

        mock_get.return_value = MagicMock(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {
                "data": {
                    "products": [
                        {
                            "title_fa": "کفش اسپرت مردانه",
                            "url": {"uri": "/product/dkp-1/"},
                            "default_variant": {
                                "price": {"selling_price": 11900000, "rrp_price": 12000000}
                            },
                        }
                    ]
                }
            },
        )
        items = search_digikala("کفش")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["price_toman"], 1190000)  # rial → toman
        self.assertEqual(items[0]["rrp_toman"], 1200000)
        self.assertTrue(items[0]["url"].startswith("https://www.digikala.com/"))

    @patch("services.research.web.requests.get")
    def test_research_product_records_source_failures(self, mock_get):
        import requests as requests_lib

        from services.research.web import research_product

        mock_get.side_effect = requests_lib.ConnectionError("blocked")
        result = research_product("کفش")
        self.assertEqual(result["items"], [])
        self.assertTrue(all(not source["ok"] for source in result["sources"]))
        # digikala + torob failures + web-search "not configured" note
        self.assertEqual(len(result["sources"]), 3)
        web_source = result["sources"][-1]
        self.assertTrue(web_source.get("skipped"))

    @patch("services.research.web.requests.get")
    def test_searxng_web_search_parsing(self, mock_get):
        from django.test import override_settings

        from services.research.web import research_product

        def fake_get(url, **kwargs):
            if "searxng" in url or ":8888" in url:
                return MagicMock(
                    raise_for_status=lambda: None,
                    json=lambda: {
                        "results": [
                            {
                                "title": "فروشگاه رقیب کفش",
                                "url": "https://competitor-shop.ir/shoes",
                                "content": "خرید کفش اسپرت با ارسال رایگان",
                            }
                        ]
                    },
                )
            import requests as requests_lib

            raise requests_lib.ConnectionError("marketplace down")

        mock_get.side_effect = fake_get
        with override_settings(
            UPMARKET_RESEARCH={
                "WEB_SEARCH_PROVIDER": "searxng",
                "SEARXNG_BASE_URL": "http://localhost:8888",
                "BRAVE_API_KEY": "",
            }
        ):
            result = research_product("کفش", web_query="خرید کفش")
        web_items = [i for i in result["items"] if i["source"] == "web:searxng"]
        self.assertEqual(len(web_items), 1)
        self.assertEqual(web_items[0]["url"], "https://competitor-shop.ir/shoes")
        self.assertIn("ارسال رایگان", web_items[0]["snippet"])
        web_source = [s for s in result["sources"] if s["source"] == "web:searxng"][0]
        self.assertTrue(web_source["ok"])
        self.assertEqual(web_source["query"], "خرید کفش")

    @patch("services.research.web.requests.get")
    def test_brave_web_search_requires_key(self, mock_get):
        from django.test import override_settings

        from services.research.web import WebSearchNotConfigured, search_web

        with override_settings(
            UPMARKET_RESEARCH={
                "WEB_SEARCH_PROVIDER": "brave",
                "SEARXNG_BASE_URL": "",
                "BRAVE_API_KEY": "",
            }
        ):
            with self.assertRaises(WebSearchNotConfigured):
                search_web("کفش")
        mock_get.assert_not_called()


class WorkflowTests(SimpleTestCase):
    def test_load_and_patch_wan22_workflow(self):
        graph, manifest = load_workflow("wan22_i2v", "v1")
        patched = patch_workflow(
            graph,
            manifest,
            image="anchor.png",
            positive="cinematic product shot",
            negative="blurry",
            seed=42,
            filename_prefix="upmarket/test",
        )
        self.assertEqual(patched["1"]["inputs"]["image"], "anchor.png")
        self.assertEqual(patched["10"]["inputs"]["text"], "cinematic product shot")
        self.assertEqual(patched["11"]["inputs"]["text"], "blurry")
        self.assertEqual(patched["13"]["inputs"]["noise_seed"], 42)
        self.assertEqual(patched["14"]["inputs"]["noise_seed"], 42)
        self.assertEqual(patched["17"]["inputs"]["filename_prefix"], "upmarket/test")
        # original graph must stay untouched
        self.assertEqual(graph["1"]["inputs"]["image"], "example.png")

    def test_unknown_input_rejected(self):
        graph, manifest = load_workflow("wan22_i2v", "v1")
        with self.assertRaises(WorkflowError):
            patch_workflow(graph, manifest, nonexistent="x")

    def test_missing_workflow_raises(self):
        with self.assertRaises(WorkflowError):
            load_workflow("does_not_exist", "v1")

    def test_flux_txt2img_template_loads_and_patches(self):
        graph, manifest = load_workflow("flux_txt2img", "v1")
        patched = patch_workflow(
            graph, manifest, positive="a red shoe poster", negative="blurry",
            seed=7, width=832, height=1216, filename_prefix="upmarket/test",
        )
        self.assertEqual(patched["4"]["inputs"]["text"], "a red shoe poster")
        self.assertEqual(patched["5"]["inputs"]["width"], 832)
        self.assertEqual(patched["2"]["inputs"]["seed"], 7)
        # FLUX-dev is guidance-distilled: cfg must stay 1.0 and the positive
        # conditioning must flow through the FluxGuidance node
        self.assertEqual(patched["2"]["inputs"]["cfg"], 1.0)
        self.assertEqual(patched["2"]["inputs"]["positive"], ["8", 0])
        self.assertEqual(patched["8"]["class_type"], "FluxGuidance")
        self.assertEqual(patched["8"]["inputs"]["conditioning"], ["4", 0])
        self.assertEqual(patched["6"]["inputs"]["vae"], ["1", 2])

    def test_flux_txt2img_guidance_is_patchable(self):
        graph, manifest = load_workflow("flux_txt2img", "v1")
        patched = patch_workflow(graph, manifest, guidance=4.0)
        self.assertEqual(patched["8"]["inputs"]["guidance"], 4.0)

    def test_flux_img_edit_template_loads_and_patches(self):
        graph, manifest = load_workflow("flux_img_edit", "v1")
        patched = patch_workflow(
            graph, manifest, image="prod.png", positive="clean studio background",
            denoise=0.45, guidance=3.5, seed=7, filename_prefix="upmarket/test",
        )
        self.assertEqual(patched["16"]["inputs"]["image"], "prod.png")
        self.assertEqual(patched["2"]["inputs"]["denoise"], 0.45)
        self.assertEqual(patched["19"]["inputs"]["guidance"], 3.5)
        self.assertEqual(patched["2"]["inputs"]["positive"], ["19", 0])
        self.assertEqual(patched["18"]["inputs"]["pixels"], ["17", 0])


@unittest.skipUnless(FFMPEG_AVAILABLE, "ffmpeg/ffprobe not installed")
class FFmpegTests(SimpleTestCase):
    """Real ffmpeg integration — generates tiny synthetic clips."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix="upmarket-ffmpeg-test-"))
        cls.clip1 = cls.tmp / "clip1.mp4"
        cls.clip2 = cls.tmp / "clip2.mp4"
        for clip, color in [(cls.clip1, "red"), (cls.clip2, "blue")]:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:d=1:r=8",
                 "-pix_fmt", "yuv420p", str(clip)],
                capture_output=True, check=True,
            )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def test_probe_duration(self):
        duration = probe_duration(self.clip1)
        self.assertAlmostEqual(duration, 1.0, delta=0.3)

    def test_extract_last_frame(self):
        frame = extract_last_frame(self.clip1, self.tmp / "last.png")
        self.assertTrue(frame.exists())
        self.assertGreater(frame.stat().st_size, 0)

    def test_concat_videos(self):
        out = concat_videos([self.clip1, self.clip2], self.tmp / "combined.mp4")
        self.assertTrue(out.exists())
        self.assertAlmostEqual(probe_duration(out), 2.0, delta=0.5)

    def test_audio_helpers(self):
        # 2s sine tone → fit into a 1s window (tempo capped + trim)
        tone = self.tmp / "tone.m4a"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:a", "aac", str(tone)],
            capture_output=True, check=True,
        )
        fitted = fit_audio(tone, self.tmp / "fitted.m4a", 1.0)
        self.assertAlmostEqual(probe_duration(fitted), 1.0, delta=0.15)

        silence = make_silence(1.0, self.tmp / "silence.m4a")
        self.assertAlmostEqual(probe_duration(silence), 1.0, delta=0.15)

        combined = concat_audio([fitted, silence], self.tmp / "voice.m4a")
        self.assertAlmostEqual(probe_duration(combined), 2.0, delta=0.3)


class TTSLanguageTests(SimpleTestCase):
    """Voice selection per narration language (fa default, en optional)."""

    def test_edge_voice_for_language(self):
        from services.audio.tts import EdgeTTSProvider, get_tts_provider

        fa = get_tts_provider(language="fa")
        en = get_tts_provider(language="en")
        self.assertIsInstance(fa, EdgeTTSProvider)
        self.assertTrue(fa.voice.startswith("fa-IR-"))
        self.assertTrue(en.voice.startswith("en-US-"))

    def test_unsupported_language_rejected(self):
        from services.audio.tts import TTSError, get_tts_provider

        with self.assertRaises(TTSError):
            get_tts_provider(language="de")
