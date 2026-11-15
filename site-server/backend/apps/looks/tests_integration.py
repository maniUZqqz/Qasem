"""«سبک تصویر» در کارِ واقعی: دستورِ استودیوی تصویر، پس‌زمینهٔ هوش مصنوعیِ تامنیل، پالتِ تم‌ها در تامنیل (کنتراست)، و آزمونِ نبودنِ نامِ برند در دستور."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from PIL import Image
from rest_framework.test import APITestCase

from apps.compute.models import ComputeJob
from apps.content.models import GeneratedImage
from apps.content.tasks import generate_image_task
from apps.jobs.models import Job
from apps.photoedit.designer import colorx
from apps.products.models import Product, ProductImage
from apps.stores.models import Store
from apps.thumbs import aibg, palette
from apps.thumbs import formats as F
from apps.thumbs import render as R
from apps.thumbs.models import Thumbnail
from apps.thumbs.styles import STYLES
from apps.thumbs.tests_aibg import node
from apps.thumbs.tests_api import SPEC, ThumbsApiBase
from services.ai.prompts import image_studio

from . import compose, fit, library
from .tests_library import BANNED

User = get_user_model()
TEMP_MEDIA = tempfile.mkdtemp(prefix="nmlooks-content-media-")


# ───────────────────────────── تم‌های رنگی ⇒ پالتِ تامنیل

class ThemePaletteTests(SimpleTestCase):
    def test_all_24_themes_build_a_deterministic_readable_palette(self):
        self.assertEqual(len(palette.themes_public()), 24)
        for tk in library.THEMES:
            mood = f"theme:{tk}"
            self.assertTrue(palette.is_mood(mood))
            self.assertTrue(palette.theme_known(mood))
            for variation in range(4):
                p = palette.build(mood, brand=["#126f85"], variation=variation)
                self.assertEqual(p, palette.build(mood, brand=["#126f85"], variation=variation), "قطعی")
                self.assertEqual(p, palette.build(mood, brand=[], variation=variation), "رنگ‌های برند تم را عوض نمی‌کنند")
                for c in (p.bg1, p.bg2, p.accent, p.accent2, p.text, p.ink, p.paper, p.primary):
                    self.assertRegex(c, r"^#[0-9a-f]{6}$", (tk, c))
                # نگهبانِ کنتراست: متنِ اصلی روی هر دو زمینه و تأکید روی زمینه
                self.assertGreaterEqual(colorx.contrast(p.text, p.bg1), 3.0, (tk, variation, p))
                self.assertGreaterEqual(colorx.contrast(p.text, p.bg2), 3.0, (tk, variation, p))
                self.assertGreaterEqual(colorx.contrast(p.accent, p.bg1), 2.9, (tk, variation, p))
                self.assertGreaterEqual(colorx.contrast(p.accent2, p.bg1), 1.9, (tk, variation, p))
                self.assertEqual(p.dark, colorx.to_hsl(library.THEMES[tk]["palette"][0])[2] < 0.5)

    def test_variations_differ_and_overrides_win(self):
        a, b, c = (palette.build("theme:warm_sunset", variation=v) for v in (0, 1, 2))
        self.assertNotEqual((a.accent, a.accent2), (b.accent, b.accent2))
        self.assertEqual((a.accent, a.accent2), (b.accent2, b.accent))
        self.assertEqual((c.bg1, c.bg2), (a.bg2, a.bg1))
        o = palette.build("theme:warm_sunset", overrides={"accent": "#00ff00", "primary": "#112233"})
        self.assertEqual((o.accent, o.primary), ("#00ff00", "#112233"))

    def test_unknown_theme_is_not_a_mood_and_falls_back_to_the_default_mood(self):
        self.assertFalse(palette.is_mood("theme:nope"))
        self.assertFalse(palette.is_mood("theme:"))
        self.assertEqual(palette.build("theme:nope"), palette.build("vivid"))
        self.assertEqual(palette.mood_title("theme:warm_sunset"), library.THEMES["warm_sunset"]["name_fa"])
        self.assertEqual(palette.mood_title("dark"), palette.MOOD_FA["dark"])
        self.assertTrue(all(m in palette.MOODS for m in ("vivid", "dark")), "حال‌وهواهای قدیمی سرِ جایشان‌اند")

    def test_spec_cleaning_keeps_known_themes_and_looks_only(self):
        spec = R.clean_spec({"format": "youtube", "style": "face_text", "colors": {"mood": "theme:warm_sunset"}, "background": {"kind": "ai", "look": "pixel_art_16bit"}}, STYLES)
        self.assertEqual(spec["colors"]["mood"], "theme:warm_sunset")
        self.assertEqual(spec["background"]["look"], "pixel_art_16bit")
        bad = R.clean_spec({"format": "youtube", "style": "face_text", "colors": {"mood": "theme:zzz"}, "background": {"kind": "ai", "look": "<script>"}}, STYLES)
        self.assertEqual((bad["colors"]["mood"], bad["background"]["look"]), ("", ""))
        old = R.clean_spec({"format": "youtube", "style": "face_text"}, STYLES)
        self.assertEqual(old["background"]["look"], "", "تامنیل‌های قدیمی بی‌سبک‌اند")

    def test_every_theme_renders_a_thumbnail_with_its_own_colours(self):
        for tk in list(library.THEMES)[:6]:
            spec = R.clean_spec({"format": "youtube", "style": "face_text", "content": {"title": "*۷* اشتباهِ تازه‌کارها"}, "colors": {"mood": f"theme:{tk}"}}, STYLES)
            res = R.render(spec, R.Inputs(), scale=0.25)
            self.assertEqual(res.palette["bg1"], palette.build(f"theme:{tk}").bg1)
            self.assertEqual(res.size[0], F.scaled(F.get("youtube"), 0.25)[0])


class ThemeAndLookThumbsApiTests(ThumbsApiBase):
    def test_overview_lists_the_24_themes_as_moods(self):
        body = self.api.get(f"{self.base}/").json()
        self.assertEqual(len(body["themes"]), 24)
        self.assertTrue(all(t["key"].startswith("theme:") and len(t["palette"]) == 6 and t["title"] for t in body["themes"]))
        self.assertEqual([m["key"] for m in body["moods"]], list(palette.MOODS), "حال‌وهواهای قدیمی همان‌اند")

    def test_preview_and_render_accept_a_theme_mood(self):
        spec = {**SPEC, "colors": {"mood": "theme:cool_midnight"}}
        r = self.api.post(f"{self.base}/preview/", {"spec": spec}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["palette"]["bg1"], palette.build("theme:cool_midnight").bg1)
        body = self.render(spec, variants=3)
        self.assertEqual(len(body["items"]), 3)
        for it in body["items"]:
            self.assertEqual(it["spec"]["colors"]["mood"], "theme:cool_midnight", "نسخه‌های A/B تمِ انتخابی را عوض نمی‌کنند")
        notes = [it["variant_note"] for it in body["items"]]
        self.assertTrue(any("«" + library.THEMES["cool_midnight"]["name_fa"] + "»" in n for n in notes[1:]), notes)

    def test_background_request_with_a_look_builds_a_look_prompt_with_hints(self):
        node()
        r = self.api.post(f"{self.base}/backgrounds/", {"format": "youtube", "look": "watercolour_storybook", "theme": "theme:warm_sunset"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        prompt = body["prompt"]
        look = library.STYLES["watercolour_storybook"]
        self.assertIn(fit.fragments(look["image_positive"])[0], prompt)
        self.assertIn(aibg.LOOK_SCENE, prompt)
        self.assertIn("warm golden hour palette", prompt, "تکه‌دستورِ تم")
        self.assertTrue(prompt.endswith(", no text, no letters, no logos, no watermark, no people, high quality, 8k"), prompt[-90:])
        self.assertNotIn("colour palette of", prompt, "با تم، رنگ‌های برند به دستور نمی‌آید")
        self.assertEqual([w for w in BANNED if w in prompt.lower()], [])
        job = ComputeJob.objects.get(uid=body["jobs"][0]["job"])
        meta = job.payload["x_thumbbg"]
        self.assertEqual((meta["look"], meta["theme"]), ("watercolour_storybook", "warm_sunset"))
        ks = job.payload["graph"]["24"]["inputs"]
        g = job.payload["graph"]["21"]["inputs"]["guidance"]
        self.assertTrue(16 <= ks["steps"] <= 32)
        self.assertTrue(2.5 <= g <= 5.0)

    def test_scene_text_and_look_combine_and_a_brand_colour_is_kept_without_a_theme(self):
        node()
        r = self.api.post(f"{self.base}/backgrounds/", {"format": "youtube", "preset": "gym_blur", "look": "pixel_art_16bit"}, format="json")
        prompt = r.json()["prompt"]
        self.assertIn("modern gym interior", prompt)
        self.assertIn(fit.fragments(library.STYLES["pixel_art_16bit"]["image_positive"])[0], prompt)
        self.assertIn("colour palette of", prompt)

    def test_unknown_look_is_ignored_and_the_old_behaviour_stays(self):
        node()
        r = self.api.post(f"{self.base}/backgrounds/", {"format": "youtube", "preset": "studio_light", "look": "no-such"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIn("photography studio backdrop", r.json()["prompt"])
        self.assertNotIn(aibg.LOOK_SCENE, r.json()["prompt"])

    def test_without_a_look_nothing_changed(self):
        p, info = aibg.resolve_prompt(self.store, preset="studio_light", colors=["#126f85"])
        self.assertTrue(p.startswith(aibg.PRESETS["studio_light"][1]))
        self.assertIn("colour palette of", p)
        self.assertEqual((info["look"], info["theme"], info["hints"]), ("", "", None))
        self.assertLessEqual(len(p), aibg.MAX_PROMPT)
        self.assertTrue(p.endswith("high quality, 8k"))

    def test_look_prompt_never_loses_its_no_text_no_people_suffix_when_long(self):
        p, _ = aibg.resolve_prompt(self.store, text="", style="face_text", colors=["#126f85", "#163f75"], look="cinematic_realistic", theme="warm_sunset",
                                   prompt_en="a" + ", very long scene description" * 25)
        self.assertLessEqual(len(p), aibg.MAX_PROMPT_LOOK)
        self.assertTrue(p.endswith("no people, high quality, 8k"))

    def test_waiting_thumbnail_with_a_look_requests_the_look_background_and_completes(self):
        n = node()
        spec = {**SPEC, "background": {"kind": "ai", "look": "claymation_stopmotion"}, "colors": {"mood": "theme:pastel_dream"}}
        body = self.render(spec, ai={"preset": "studio_light"})
        item = body["items"][0]
        self.assertEqual(item["state"], "WAITING_BG")
        job = ComputeJob.objects.get(uid=item["bg_job"])
        text = job.payload["graph"]["20"]["inputs"]["text"]
        self.assertIn("photography studio backdrop", text)
        self.assertIn(fit.fragments(library.STYLES["claymation_stopmotion"]["image_positive"])[0], text)
        self.assertEqual(job.payload["x_thumbbg"]["look"], "claymation_stopmotion")
        self.assertEqual(item["spec"]["background"]["look"], "claymation_stopmotion")
        self.assertEqual(Thumbnail.objects.get(pk=item["id"]).notes["ai"]["look"], "claymation_stopmotion")
        aibg.finish_for_test(job, n)
        self.assertEqual(self.api.get(f"{self.base}/items/{item['id']}/").json()["state"], "READY")


# ───────────────────────────── استودیوی تصویر

class ImagePromptTests(SimpleTestCase):
    class P:
        name = "بطری"
        description = ""

    def build(self, look=None):
        with patch.object(image_studio, "product_context", return_value="Product: test"):
            return image_studio.build_image_prompt(self.P(), None, "POSTER", "مینیمال", "", look=look)

    def test_the_look_block_is_added_only_when_a_look_is_chosen(self):
        self.assertEqual(image_studio.IMAGE_PROMPT_VERSION, "4")
        plain = self.build()
        self.assertNotIn("Look chosen by the store owner", plain)
        c = compose.compose("anime_90s_cel", "POSTER", theme_key="warm_sunset")
        with_look = self.build(c)
        self.assertIn("Look chosen by the store owner: " + c["name_en"], with_look)
        self.assertIn(c["positive"], with_look)
        self.assertIn("Put these in negative_en", with_look)
        self.assertIn("Never name any studio", with_look)
        self.assertEqual([w for w in BANNED if w in with_look.lower()], [])
        self.assertTrue(with_look.startswith("Design one image"))
        self.assertIn("Requested style: مینیمال", with_look)

    def test_a_product_safe_look_tells_the_director_it_may_only_change_the_scene(self):
        text = self.build(compose.compose("noir_bw", "PRODUCT_SHOT"))
        self.assertIn("PRODUCT RULE", text)
        self.assertIn(fit.PRODUCT_GUARD, text)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ImageStudioLookTests(APITestCase):
    VALID = {"concept_fa": "عکس با نورِ ملایم", "prompt_en": "a bottle on a table, soft window light", "negative_en": "blurry"}

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("looks-content", password="Str0ngPass!x")
        self.store = Store.objects.create(owner=self.user, name="فروشگاه سبک")
        self.product = Product.objects.create(store=self.store, name="بطری")
        self.client.force_authenticate(user=self.user)
        d = Path(TEMP_MEDIA) / "products" / "images"
        d.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "white").save(d / "lk.png")
        self.pi = ProductImage(product=self.product)
        self.pi.image.name = "products/images/lk.png"
        self.pi.save()

    URL = "/api/v1/products/{}/image-studio/"

    @patch("apps.content.views.generate_image_task")
    def test_endpoint_refuses_an_illustrated_look_on_product_preserving_kinds_with_a_persian_message(self, task):
        task.delay.return_value = MagicMock(id="x")
        for kind in ("PRODUCT_SHOT", "ENHANCED"):
            r = self.client.post(self.URL.format(self.product.id), {"kind": kind, "look": "claymation_stopmotion"}, format="json")
            self.assertEqual(r.status_code, 400, r.content)
            err = r.json()["error"]
            self.assertEqual(err["code"], "look_changes_product")
            self.assertIn("پوستر", err["message"])
            self.assertIn(library.STYLES["claymation_stopmotion"]["name_fa"], err["message"])
        task.delay.assert_not_called()
        self.assertEqual(Job.objects.count(), 0, "هیچ کاری ثبت نشد")

    @patch("apps.content.views.generate_image_task")
    def test_endpoint_accepts_illustrated_looks_for_posters_and_scene_looks_for_product_shots(self, task):
        task.delay.return_value = MagicMock(id="x")
        r = self.client.post(self.URL.format(self.product.id), {"kind": "POSTER", "look": "claymation_stopmotion", "look_theme": "warm_sunset"}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        self.assertEqual(task.delay.call_args.args[-2:], ("claymation_stopmotion", "warm_sunset"))
        r = self.client.post(self.URL.format(self.product.id), {"kind": "PRODUCT_SHOT", "look": "noir_bw"}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        self.assertEqual(task.delay.call_args.args[-2:], ("noir_bw", ""))
        # بدونِ سبک: همان فراخوانیِ قدیمی (آرگومانِ اضافه نمی‌رود)
        r = self.client.post(self.URL.format(self.product.id), {"kind": "POSTER", "style": "مینیمال"}, format="json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(len(task.delay.call_args.args), 6)
        for body, code in (({"kind": "POSTER", "look": "nope"}, "unknown_look"), ({"kind": "POSTER", "look": "noir_bw", "look_theme": "zzz"}, "unknown_theme")):
            r = self.client.post(self.URL.format(self.product.id), body, format="json")
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, code))

    def _mocks(self, mock_provider_cls, mock_client_cls):
        mock_provider_cls.return_value.generate_json.return_value = (dict(self.VALID), "{}")
        client = mock_client_cls.return_value
        client.upload_image.return_value = "uploaded.png"

        def fake_generate(workflow, dest, filename=None, timeout=None):
            Path(dest).mkdir(parents=True, exist_ok=True)
            path = Path(dest) / (filename or "gen.png")
            Image.new("RGB", (64, 64), (30, 30, 60)).save(path)
            return path

        client.generate.side_effect = fake_generate
        return client

    @patch("apps.content.tasks.ComfyUIClient")
    @patch("apps.content.tasks.text_provider")
    def test_task_puts_the_scene_look_and_product_guard_in_the_final_prompt(self, provider, client_cls):
        client = self._mocks(provider, client_cls)
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, self.product.id, "ENHANCED", "", "", None, "noir_bw", "mono_noir"))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        img = GeneratedImage.objects.get(product=self.product)
        c = compose.compose("noir_bw", "ENHANCED", theme_key="mono_noir")
        for frag in fit.fragments(c["positive"]):
            self.assertIn(frag.lower(), img.prompt_en.lower(), frag)
        self.assertTrue(img.prompt_en.startswith("a bottle on a table"), "متنِ کارگردان می‌ماند")
        self.assertIn("altered product", img.negative_en)
        self.assertEqual(img.style, library.STYLES["noir_bw"]["name_fa"])
        self.assertEqual(img.metadata["look"], {"key": "noir_bw", "name_fa": library.STYLES["noir_bw"]["name_fa"], "theme": "mono_noir", "scene_only": True})
        self.assertEqual(img.workflow_version, "flux_img_edit@v1")
        graph = client.generate.call_args.args[0]
        self.assertIn(fit.PRODUCT_GUARD, json.dumps(graph, ensure_ascii=False))
        director_prompt = str(provider.return_value.generate_json.call_args)
        self.assertIn("Look chosen by the store owner", director_prompt)
        self.assertEqual([w for w in BANNED if w in (img.prompt_en + img.negative_en).lower()], [])

    @patch("apps.content.tasks.ComfyUIClient")
    @patch("apps.content.tasks.text_provider")
    def test_task_for_a_poster_applies_an_illustrated_look_and_its_generation_hints(self, provider, client_cls):
        client = self._mocks(provider, client_cls)
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, self.product.id, "POSTER", "مینیمال", "", None, "pixel_art_16bit", ""))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        img = GeneratedImage.objects.get(product=self.product)
        for frag in fit.fragments(library.STYLES["pixel_art_16bit"]["image_positive"])[:3]:
            self.assertIn(frag.lower(), img.prompt_en.lower())
        self.assertEqual(img.style, "مینیمال")
        self.assertFalse(img.metadata["look"]["scene_only"])
        graph_text = json.dumps(client.generate.call_args.args[0])
        hints = compose.compose("pixel_art_16bit", "POSTER")["hints"]
        self.assertIn('"steps": %d' % max(20, min(32, int(hints["steps"]))), graph_text)

    @patch("apps.content.tasks.ComfyUIClient")
    @patch("apps.content.tasks.text_provider")
    def test_task_without_a_look_is_unchanged(self, provider, client_cls):
        self._mocks(provider, client_cls)
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, self.product.id, "ENHANCED"))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        img = GeneratedImage.objects.get(product=self.product)
        self.assertEqual(img.prompt_en, self.VALID["prompt_en"])
        self.assertNotIn("look", img.metadata)
        self.assertNotIn("Look chosen", str(provider.return_value.generate_json.call_args))

    @patch("apps.content.tasks.ComfyUIClient")
    @patch("apps.content.tasks.text_provider")
    def test_task_fails_with_the_persian_reason_if_an_illustrated_look_reaches_a_product_kind(self, provider, client_cls):
        self._mocks(provider, client_cls)
        job = Job.objects.create(store=self.store, type=Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, self.product.id, "PRODUCT_SHOT", "", "", None, "claymation_stopmotion", ""))
        job.refresh_from_db()
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertIn("پوستر", job.error)
        self.assertEqual(GeneratedImage.objects.count(), 0)
        provider.return_value.generate_json.assert_not_called()
