"""کیتِ پرامپت: اندازهٔ کران‌دار، فقط قطعه‌های مرتبط، نمونه‌های معتبر، شمای JSON، مسیرِ مدل (ساختگی) و بازگشت به قاعده‌ها؛ حالتِ قالبی بدونِ هوش مصنوعی."""
import json
from unittest import mock

from django.test import SimpleTestCase, override_settings

from . import ai, catalog, components, promptkit, specs


class Prompt(SimpleTestCase):
    IDEA = "معرفیِ چغر برای مربی‌ها؛ سه مزیت، یک مقایسهٔ قیمت و دعوت به ثبت‌نام"

    def test_the_prompt_is_bounded_even_for_a_huge_idea(self):
        for idea in (self.IDEA, "ایده " * 3000, "قیمت نمودار مقایسه مراحل چک لیست آیکون " * 200):
            kit = promptkit.build_prompt(idea, style="flat-vector")
            self.assertLessEqual(kit["chars"], promptkit.MAX_PROMPT_CHARS)
            self.assertLessEqual(len(kit["ids"]), promptkit.MAX_COMPONENTS)

    def test_only_the_chosen_style_and_the_fitting_components_are_in_the_prompt(self):
        kit = promptkit.build_prompt("نمودار میله‌ایِ مقایسهٔ سه گزینه با درصد", style="pixel-art")
        self.assertIn("pixel-art", kit["system"])
        self.assertNotIn("flat-vector", kit["system"])
        self.assertIn("bar_chart", kit["ids"])
        self.assertLess(len(kit["ids"]), len(components.COMPONENTS))
        for cid in components.COMPONENTS:
            self.assertEqual(f"- {cid} (" in kit["system"], cid in kit["ids"], cid)

    def test_the_catalogue_carries_each_components_parameter_schema(self):
        kit = promptkit.build_prompt("نمودار", style="flat-vector", ids=["bar_chart", "title", "cta"])
        self.assertIn("bars:[{label:str<=40,value:num}]x6", kit["system"])
        self.assertIn("title: str<=140", kit["system"].replace("title:str<=140", "title: str<=140"))

    def test_guide_has_the_typography_timing_and_safe_zone_rules(self):
        kit = promptkit.build_prompt(self.IDEA, style="flat-vector", platform="reels")
        for needle in ("0.32 s per word", "WORDS never letters", "Persian digits", "NEVER invent", "safe margins", "Hook in the first 1.5 s"):
            self.assertIn(needle, kit["system"])
        self.assertIn("wipe", kit["system"])
        self.assertIn("out-expo", kit["system"])

    def test_the_few_shot_examples_are_valid_plans(self):
        self.assertGreaterEqual(len(promptkit.EXAMPLES), 3)
        for e in promptkit.EXAMPLES:
            out = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "scenes": e["plan"]["scenes"]})
            self.assertEqual(len(out["scenes"]), len(e["plan"]["scenes"]), e["name"])
        kit = promptkit.build_prompt(self.IDEA, style="flat-vector")
        self.assertIn('"scenes"', kit["system"])

    def test_the_json_schema_constrains_the_scene_types_and_is_serialisable(self):
        kit = promptkit.build_prompt(self.IDEA, style="flat-vector")
        json.dumps(kit["schema"])
        types = kit["schema"]["properties"]["scenes"]["items"]["properties"]["type"]["enum"]
        self.assertEqual(types, kit["ids"])
        self.assertEqual(kit["schema"]["required"], ["scenes"])
        props = kit["schema"]["properties"]["scenes"]["items"]["properties"]
        self.assertEqual(props["transition"]["enum"][:2], ["cut", "fade"])
        self.assertIn("iris", props["transition"]["enum"])

    def test_components_are_picked_by_the_request(self):
        self.assertIn("price_card", promptkit.pick_components("قیمت بسته و تخفیف"))
        self.assertIn("steps", promptkit.pick_components("مراحل کار: چهار قدم"))
        self.assertIn("testimonial", promptkit.pick_components("نظر مشتری و رضایت"))
        for ids in (promptkit.pick_components("x"), promptkit.pick_components("")):
            self.assertEqual(ids[:2], ["title", "cta"])

    def test_the_patch_prompt_shows_the_plan_without_the_noise(self):
        plan = specs.normalize_spec({"style": "flat-vector", "aspect": "9:16", "scenes": [{"type": "title", "duration": 3, "title": "سلام", "cues": [{"w": "سلام", "s": 0, "e": 1}]}]})
        kit = promptkit.build_patch_prompt(plan, "تیتر بزرگ‌تر شود")
        self.assertIn("سلام", kit["user"])
        self.assertNotIn("cues", kit["user"])
        self.assertIn("scenes/1/tokens/font_scale", kit["system"])
        self.assertTrue(kit["schema"]["properties"]["ops"])


class FakeProvider:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def generate(self, prompt, **kw):
        self.calls.append((prompt, kw))
        return self.reply


class AiFlow(SimpleTestCase):
    def test_a_valid_model_answer_becomes_a_polished_plan(self):
        reply = json.dumps({"title": "تیزر", "scenes": [
            {"type": "kinetic_title", "duration": 4, "text": "با چغر 50 توکن", "emphasis": []},
            {"type": "bar_chart", "duration": 6, "title": "مقایسه", "bars": [{"label": "الف", "value": 40}, {"label": "ب", "value": 70}], "transition": "wipe"},
            {"type": "cta", "duration": 4, "title": "ثبت‌نام کنید", "button": "ورود"}]}, ensure_ascii=False)
        prov = FakeProvider(reply)
        res = ai.script_from_idea(None, "معرفی چغر و مقایسه", style="flat-vector", provider=prov)
        self.assertEqual(res["source"], "ai")
        self.assertEqual(res["spec"]["scenes"][1]["transition"], "wipe")
        self.assertEqual(res["spec"]["platform"], "reels")                       # polish: platform from the aspect
        self.assertIn("camera", res["spec"]["scenes"][0])                        # polish: a slow push-in on the headline
        prompt, kw = prov.calls[0]
        self.assertIsInstance(kw["json_schema"], dict)
        self.assertTrue(kw["json_mode"])
        self.assertLessEqual(res["prompt_chars"], promptkit.MAX_PROMPT_CHARS)

    def test_one_scene_without_its_content_does_not_void_the_plan(self):
        reply = json.dumps({"scenes": [{"type": "title", "duration": 3, "title": "سلام"}, {"type": "bar_chart", "duration": 5}, {"type": "cta", "duration": 3, "title": "برو"}]}, ensure_ascii=False)
        res = ai.script_from_idea(None, "ایده", style="flat-vector", provider=FakeProvider(reply))
        self.assertEqual(res["source"], "ai")
        self.assertEqual([s["type"] for s in res["spec"]["scenes"]], ["title", "cta"])
        self.assertIn("کنار گذاشته شد", res["message"])

    def test_an_invented_component_name_refuses_the_whole_answer(self):
        reply = json.dumps({"scenes": [{"type": "title", "duration": 3, "title": "سلام"}, {"type": "evil", "duration": 3}]}, ensure_ascii=False)
        self.assertEqual(ai.script_from_idea(None, "ایده", style="flat-vector", provider=FakeProvider(reply))["source"], "rules")

    def test_a_provider_that_does_not_know_structured_output_still_works(self):
        class Old:
            def generate(self, prompt, system=None, temperature=None, num_predict=None, timeout=None):
                return json.dumps({"scenes": [{"type": "title", "duration": 3, "title": "سلام"}, {"type": "cta", "duration": 3, "title": "برو", "button": "ورود"}]})

        self.assertEqual(ai.script_from_idea(None, "ایده", style="flat-vector", provider=Old())["source"], "ai")

    def test_model_failure_falls_back_to_a_rules_draft_with_a_persian_message(self):
        class Boom:
            def generate(self, *a, **k):
                raise RuntimeError("HTTP 402 out of credit")

        res = ai.script_from_idea(None, "معرفیِ چغر. سه مزیت. همین حالا شروع کن", style="flat-vector", provider=Boom())
        self.assertEqual(res["source"], "rules")
        self.assertIn("هوش مصنوعی", res["message"])
        self.assertEqual(res["spec"]["scenes"][0]["type"], "title")
        self.assertEqual(res["spec"]["version"], 2)

    def test_garbage_json_falls_back(self):
        res = ai.script_from_idea(None, "معرفیِ چغر. سه مزیت", style="flat-vector", provider=FakeProvider("متن بدونِ JSON"))
        self.assertEqual(res["source"], "rules")

    def test_template_mode_never_needs_ai(self):
        with mock.patch.object(ai, "get_provider", side_effect=AssertionError("template mode must not call AI")):
            for t in specs.TEMPLATES:
                out = specs.normalize_spec(specs.sample_spec("flat-vector", t["id"]))
                self.assertTrue(out["scenes"])

    @override_settings(IS_TEST=False)
    def test_the_vision_provider_is_the_gateways_routed_one(self):
        with mock.patch("services.ai.gateway.vision_provider", return_value="V") as vp:
            self.assertEqual(ai.get_provider(None, kind="vision"), "V")
            vp.assert_called_once()

    def test_every_style_of_the_catalogue_can_be_described_to_the_model(self):
        for s in catalog.STYLES[:20]:
            self.assertIn(s["id"], promptkit.style_tokens(s["id"]))
