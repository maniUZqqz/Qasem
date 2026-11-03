"""«ویرایش با دستور» (kit_smart) وقتی سرورِ پردازش خاموش است یا «اول متیس» است: مسیرِ سایت (smart.py).

هیچ هوشِ مصنوعیِ واقعی (به‌ویژه متیس) صدا زده نمی‌شود: مسیریابِ واقعیِ services.ai.routing.RoutedTextProvider با دو پایانِ
ساختگی (لوکال و متیس) به کار می‌رود تا ترتیبِ «اول لوکال / اول متیس»، پشتیبان‌گیری و describe() همان‌طور که در تولید است
آزموده شود؛ گرهٔ پردازش هم ساختگی است.
"""
import base64
import contextlib
import io
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import numpy as np
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.ai.models import AiPriority
from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode
from apps.stores.models import Store
from services.ai import priority, routing

from . import catalog, ops, services, smart
from .models import PhotoAsset, PhotoEdit
from .tests import ApiTestBase, photo

GOOD = {"adjust": {"exposure": 0.45, "temperature": 18, "vibrance": 14}, "curve": {}, "preset": "",
        "ops": [], "notes": "گرم‌تر و روشن‌تر شد."}


# ───────────────────────────── پایان‌های ساختگی

class FakeLeg:
    """یک مسیرِ هوشِ مصنوعی (متیس: OpenAICompat، لوکال: Ollama) با همان رابطِ generate_json."""

    def __init__(self, reply=None, *, model="gpt-4o-mini", error=None):
        self.reply, self.model, self.error, self.calls = reply, model, error, []

    def select_models(self, candidates):
        return [self.model]

    def generate_json(self, model, prompt, *, system=None, images=None, options=None, repair_attempts=1, timeout=None,
                      schema_keys=None):
        self.calls.append({"model": model, "prompt": prompt, "images": images, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.reply, json.dumps(self.reply, ensure_ascii=False)


class PlainProvider(FakeLeg):
    """providerِ بی مسیریاب (فقط generate_json؛ بی describe)."""


def node_state(ready: bool):
    return {"model": "qwen3-vl:30b", "kind": "vision", "online": ready, "ready": ready, "has_model": True if ready else None,
            "node": "gpu-1" if ready else "", "nodes": [], "known_models": [],
            "reason": "" if ready else "سرورِ پردازش خاموش است."}


class Routed:
    """RoutedTextProvider ِ واقعی + دو پایانِ ساختگی؛ ``smart._vision`` را روی آن می‌گذارد.

    local=None ⇒ گرهٔ لوکال خاموش است (پیش‌بررسی همان‌جا رد می‌کند)؛ metis=None ⇒ متیس تنظیم نشده."""

    def __init__(self, *, local=None, metis=None):
        self.local, self.metis = local, metis
        self.provider = routing.RoutedTextProvider(
            metis, task="vision:PRODUCT", kind=priority.VISION,
            no_fallback_reason="" if metis is not None else "متیس (API) تنظیم نشده است (AI_API_BASE_URL و AI_API_KEY).")

    def _call_local(self, local_call, cfg):
        if self.local is None:
            raise routing.NodeFailed("سرورِ پردازش خاموش است.")
        return local_call(self.local, self.local.model), self.local.model

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        for cm in (override_settings(AI_ROUTE_FORCE=True),
                   patch.object(routing, "node_state", lambda kind=priority.CODE: node_state(self.local is not None)),
                   patch.object(routing._Router, "_call_local", lambda s, lc, cfg: self._call_local(lc, cfg)),
                   patch.object(smart, "_vision", lambda store: self.provider),
                   patch.object(smart, "_candidate_models", lambda: ["qwen3-vl:30b"])):
            self.stack.enter_context(cm)
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)


def set_order(order: str, vision: str = ""):
    row = AiPriority.get()
    row.priority, row.priority_vision = order, vision
    row.save()


def ctx(**kw):
    return {"notes": [], "store_name": "فروشگاهِ نمونه", "logo_path": lambda p: None, "scale": 1.0} | kw


# ═════════════════════════════ انتخابِ مسیر

class DecidePathTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user("smart-u", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاهِ آزمون")

    def online(self):
        return ComputeNode.objects.create(name="gpu-photo", last_seen=timezone.now(), capabilities={"photo": True})

    def test_local_first_with_online_photo_node_uses_the_node(self):
        set_order("local_first")
        self.online()
        d = smart.decide_path(self.store)
        self.assertEqual((d["path"], d["first"], d["node_online"]), ("node", "local", True))

    def test_local_first_but_node_offline_uses_the_site(self):
        set_order("local_first")
        d = smart.decide_path(self.store)
        self.assertEqual((d["path"], d["first"], d["node_online"]), ("site", "local", False))
        self.assertIn("خاموش", d["reason"])

    def test_metis_first_uses_the_site_even_with_the_node_online(self):
        set_order("metis_first")
        self.online()
        d = smart.decide_path(self.store)
        self.assertEqual((d["path"], d["first"], d["node_online"]), ("site", "metis", True))
        self.assertIn("متیس", d["reason"])

    def test_vision_override_beats_the_global_order(self):
        set_order("local_first", vision="metis_first")
        self.online()
        self.assertEqual(smart.decide_path(self.store)["path"], "site")
        set_order("metis_first", vision="local_first")
        self.assertEqual(smart.decide_path(self.store)["path"], "node")

    def test_node_without_photo_capability_does_not_count(self):
        set_order("local_first")
        ComputeNode.objects.create(name="comfy-only", last_seen=timezone.now(), capabilities={"comfyui": True})
        self.assertEqual(smart.decide_path(self.store)["path"], "site")


# ═════════════════════════════ وارسیِ جوابِ مدل

class ValidateReplyTests(SimpleTestCase):
    def test_values_are_clamped_and_unknown_keys_dropped(self):
        r = smart.validate_reply({"adjust": {"exposure": 99, "Temperature": "30", "contrast": -500, "tint": True,
                                             "nonsense": 5, "highlights": "NaN", "shadows": "1e999", 7: 3,
                                             "vibrance": "۲۵", "clarity": [1, 2], "levelsGamma": 0.01},
                                 "notes": "x"})
        self.assertEqual(r["adjust"], {"exposure": 4.0, "temperature": 30.0, "contrast": -100.0, "vibrance": 25.0,
                                       "levelsGamma": 0.2})

    def test_garbage_replies_are_rejected_not_raised(self):
        for bad in (None, "text", 7, [1, 2], [], {}, {"adjust": []}, {"adjust": "x"}, {"adjust": {"exposure": "NaN"}},
                    {"adjust": {"zzz": 1}}, {"ops": "rm -rf"}, {"ops": [1, "a", None]}, {"preset": ["clean"]},
                    {"adjust": {}, "curve": {"rgb": "x"}}, {"adjust": {"exposure": float("inf")}}):
            self.assertIsNone(smart.validate_reply(bad), bad)

    def test_only_safe_tools_survive_and_their_params_are_strict(self):
        r = smart.validate_reply({"adjust": {"exposure": 0.2}, "ops": [
            {"tool": "text", "params": {"text": "سلام"}},                    # ابزارِ ناامن
            {"tool": "logo", "params": {}}, {"tool": "export", "params": {"format": "png"}},
            {"tool": "look", "params": {"style": "zzz"}},                    # مقدارِ ناپذیرفتنی ⇒ کلِ کار دور
            {"tool": "look", "params": {"style": "warm", "strength": 400}},  # ← کلید ۱۰۰ می‌شود
            {"tool": "look", "params": {"style": "cool"}},                   # تکرارِ همان ابزار ⇒ دور
            {"tool": "color", "params": {"brightness": 0}},                  # بی‌اثر ⇒ دور
            {"tool": "color", "params": {"warmth": 500, "evil": 1}},
            {"tool": "resize", "params": {"long_edge": 100}},                # زیرِ حدِ مجاز ⇒ دور
            {"tool": "rotate", "params": {"turn": "0"}},                     # بی‌اثر
            {"tool": "crop_format", "params": {"format": "story", "fit": "contain"}},
            {"tool": "auto_tone", "params": {"strength": 60}},
        ]})
        got = [(o["tool"], o["params"]) for o in r["ops"]]
        self.assertEqual([t for t, _ in got], ["look", "color", "crop_format", "auto_tone"])
        self.assertEqual(got[0][1]["strength"], 100)
        self.assertEqual(got[1][1]["warmth"], 100)
        self.assertNotIn("evil", got[1][1])
        for tool, params in got:
            self.assertIn(tool, smart.SAFE_TOOLS)
            self.assertEqual(params, catalog.normalize_params(tool, params, strict=True))

    def test_unsafe_tool_names_and_the_cap_on_the_number_of_ops(self):
        for tool in ("text", "logo", "watermark", "compose", "develop", "export", "kit_background", "kit_smart", "perspective",
                     "__import__", "", None, 5, ["look"]):
            self.assertIsNone(smart.validate_reply({"ops": [{"tool": tool, "params": {}}]}), tool)
        six = [{"tool": "look", "params": {"style": "warm"}}, {"tool": "color", "params": {"contrast": 10}},
               {"tool": "auto_tone", "params": {}}, {"tool": "rotate", "params": {"turn": "90"}},
               {"tool": "crop_format", "params": {}}, {"tool": "resize", "params": {"long_edge": 1600}}]
        r = smart.validate_reply({"ops": six})
        self.assertEqual(len(r["ops"]), smart.MAX_AI_OPS)
        self.assertEqual([o["tool"] for o in r["ops"]], ["look", "color", "auto_tone", "rotate"])

    def test_preset_must_be_a_known_look(self):
        self.assertEqual(smart.validate_reply({"preset": "warm"})["preset"], "warm")
        self.assertIsNone(smart.validate_reply({"preset": "nope"}))
        self.assertIsNone(smart.validate_reply({"preset": "store"}), "فیلترِ «فروشگاهی» پس‌زمینه برمی‌دارد؛ مجاز نیست")

    def test_notes_are_cleaned_and_capped(self):
        r = smart.validate_reply({"adjust": {"exposure": 0.2}, "notes": "یک\x00دو\n\nسه " + "ا" * 5000})
        self.assertLessEqual(len(r["notes"]), smart.NOTES_MAX)
        self.assertNotIn("\x00", r["notes"])
        self.assertNotIn("\n", r["notes"])
        r = smart.validate_reply({"adjust": {"exposure": 0.2}, "notes": ["الف", "ب", {"x": 1}]})
        self.assertEqual(r["notes"], "الف ب")
        self.assertEqual(smart.validate_reply({"adjust": {"exposure": 0.2}, "notes": 5})["notes"], "")

    def test_kit_style_recipe_reply_is_accepted(self):
        r = smart.validate_reply({"recipe": {"adjust": {"exposure": 0.3}, "preset": "warm"}, "notes": "ok"})
        self.assertEqual((r["adjust"], r["preset"], r["notes"]), ({"exposure": 0.3}, "warm", "ok"))

    def test_curve_is_normalised(self):
        r = smart.validate_reply({"curve": {"rgb": [[0, 0], [128, 170], [255, 255], [9999, -5]], "evil": [[0, 0]]}})
        self.assertEqual(set(r["curve"]), {"rgb"})
        self.assertTrue(all(0 <= v <= 255 for pt in r["curve"]["rgb"] for v in pt))


# ═════════════════════════════ پرسش و تصویر

class PromptTests(ApiTestBase):
    def test_prompt_has_goal_measurements_catalogue_and_presets_and_stays_compact(self):
        (aid,) = self.upload(photo(900, 600, dark=True, seed=3))
        a = PhotoAsset.objects.get(pk=aid)
        text = smart.build_prompt(a, "گرم و روشن، مناسبِ کافه")
        self.assertIn("گرم و روشن، مناسبِ کافه", text)
        for key in ("exposure", "temperature", "shadowsHue", "redSat", "noiseLuma", "grain"):
            self.assertIn(key, text)
        for pk in ("clean", "warm", "cinematic", "food"):
            self.assertIn(pk, text)
        self.assertNotIn("storeTransparent", text)
        self.assertIn("نورِ میانه", text)
        self.assertIn("ابعاد 900×600", text)
        self.assertLess(len(text), 8000)
        self.assertIn("فقط JSON", text)

    def test_refine_prompt_carries_the_current_settings(self):
        (aid,) = self.upload(photo(seed=4))
        a = PhotoAsset.objects.get(pk=aid)
        text = smart.build_prompt(a, "گرم‌ترش کن", {"adjust": {"temperature": 20}, "curve": {}, "ops": []})
        self.assertIn('"temperature": 20', text)
        self.assertIn("اصلاح", text)

    def test_image_sent_is_a_small_jpeg_and_the_timeout_is_bounded(self):
        (aid,) = self.upload(photo(2400, 1800, seed=5))
        a = PhotoAsset.objects.get(pk=aid)
        leg = PlainProvider(dict(GOOD))
        with patch.object(smart, "_vision", lambda store: leg), patch.object(smart, "_candidate_models", lambda: ["m"]):
            smart.run_site_smart(a, "روشن‌تر", self.store)
        (call,) = leg.calls
        self.assertEqual(len(call["images"]), 1)
        with Image.open(io.BytesIO(base64.b64decode(call["images"][0]))) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertLessEqual(max(im.size), smart.IMAGE_SIDE)
        self.assertLessEqual(call["timeout"], 120)
        self.assertEqual(call["model"], "gpt-4o-mini", "نامِ مدل را خودِ provider می‌گوید (select_models)")
        self.assertIn("روشن‌تر", call["prompt"])


# ═════════════════════════════ چه کسی جواب داد (مسیریابِ واقعی + پایان‌های ساختگی)

class ProviderOrderTests(ApiTestBase):
    def asset(self):
        (aid,) = self.upload(photo(900, 600, dark=True, seed=6))
        return PhotoAsset.objects.get(pk=aid)

    def test_local_first_node_off_for_kit_but_local_ollama_ready_answers_as_local(self):
        set_order("local_first")
        a = self.asset()
        local, metis = FakeLeg(dict(GOOD), model="qwen3-vl:30b"), FakeLeg(dict(GOOD))
        with Routed(local=local, metis=metis) as r:
            res = smart.run_site_smart(a, "گرم و روشن", self.store)
        self.assertEqual((len(local.calls), len(metis.calls)), (1, 0))
        m = res["meta"]
        self.assertEqual((m["via"], m["model"], m["fell_back"], m["fallback"]), ("local", "qwen3-vl:30b", False, False))
        self.assertEqual(m["label"], "لوکال (qwen3-vl:30b)")
        self.assertEqual(res["adjust"]["exposure"], 0.45)
        self.assertEqual(res["notes"], "گرم‌تر و روشن‌تر شد.")
        self.assertTrue(local.calls[0]["images"] and local.calls[0]["timeout"] <= 120)

    def test_metis_first_answers_as_metis_and_local_is_never_asked(self):
        set_order("metis_first")
        a = self.asset()
        local, metis = FakeLeg(dict(GOOD), model="qwen3-vl:30b"), FakeLeg(dict(GOOD), model="gpt-4o-mini")
        with Routed(local=local, metis=metis):
            res = smart.run_site_smart(a, "گرم و روشن", self.store)
        self.assertEqual((len(local.calls), len(metis.calls)), (0, 1))
        m = res["meta"]
        self.assertEqual((m["via"], m["model"], m["fell_back"]), ("metis", "gpt-4o-mini", False))
        self.assertEqual(m["label"], "متیس (gpt-4o-mini)")
        self.assertEqual(metis.calls[0]["model"], "gpt-4o-mini")

    def test_metis_first_with_metis_out_of_credit_falls_back_to_local(self):
        set_order("metis_first")
        a = self.asset()
        local = FakeLeg(dict(GOOD), model="qwen3-vl:30b")
        metis = FakeLeg(error=RuntimeError("خطای سرویس (402): payment required"))
        with Routed(local=local, metis=metis):
            res = smart.run_site_smart(a, "گرم و روشن", self.store)
        self.assertEqual((len(metis.calls), len(local.calls)), (1, 1))
        m = res["meta"]
        self.assertEqual((m["via"], m["fell_back"], m["fallback"]), ("local", True, False))
        self.assertIn("پشتیبان", m["label"])
        self.assertIn("۴۰۲", m["reason"])
        self.assertIn("اعتبار", m["reason"])

    def test_local_first_with_node_off_falls_back_to_metis(self):
        set_order("local_first")
        a = self.asset()
        metis = FakeLeg(dict(GOOD), model="gpt-4o-mini")
        with Routed(local=None, metis=metis):
            res = smart.run_site_smart(a, "گرم و روشن", self.store)
        m = res["meta"]
        self.assertEqual((m["via"], m["fell_back"], m["fallback"]), ("metis", True, False))
        self.assertIn("خاموش", m["reason"])
        self.assertEqual(len(metis.calls), 1)

    def test_both_failing_gives_the_honest_deterministic_fallback(self):
        set_order("metis_first")
        a = self.asset()
        local = FakeLeg(error=routing.NodeFailed("سرورِ پردازش وسطِ کار قطع شد."))
        metis = FakeLeg(error=RuntimeError("خطای سرویس (402): payment required"))
        with Routed(local=local, metis=metis):
            res = smart.run_site_smart(a, "گرم و روشن", self.store)
        m = res["meta"]
        self.assertEqual((m["via"], m["model"], m["fallback"], m["fell_back"]), ("", "", True, True))
        self.assertEqual(m["label"], smart.FALLBACK_LABEL)
        self.assertIn("هیچ‌کدام از دو مسیر", m["reason"])
        self.assertIn("متیس", m["reason"])
        self.assertIn("لوکال", m["reason"])
        self.assertEqual(res["adjust"], {})
        self.assertEqual(res["ops"][0]["tool"], "auto_tone")
        self.assertGreaterEqual(res["ops"][0]["params"]["strength"], 70, "عکسِ تیره ⇐ شدتِ بالا")
        self.assertIn("دستورِ شما اجرا نشد", res["notes"])
        self.assertIn("هوشِ مصنوعی در دسترس نبود", res["notes"])

    def test_nothing_configured_and_policy_blocks_never_raise(self):
        a = self.asset()
        for exc in (RuntimeError("boom"), KeyError("x"), ValueError("bad")):
            with patch.object(smart, "_vision", MagicMock(side_effect=exc)):
                res = smart.run_site_smart(a, "x", self.store)
            self.assertTrue(res["meta"]["fallback"])
            self.assertEqual(res["meta"]["via"], "")
            self.assertTrue(res["meta"]["reason"])

    def test_unusable_reply_falls_back_with_the_provider_named(self):
        a = self.asset()
        for reply in ({"adjust": {"zzz": 1}}, "سلام", None, {"ops": [{"tool": "text"}]}):
            leg = PlainProvider(reply, model="gpt-4o-mini")
            with patch.object(smart, "_vision", lambda store: leg), patch.object(smart, "_candidate_models", lambda: ["m"]):
                res = smart.run_site_smart(a, "x", self.store)
            self.assertTrue(res["meta"]["fallback"], reply)
            self.assertIn("جوابِ قابل‌استفاده نداد", res["meta"]["reason"])

    def test_plain_provider_without_describe_still_gets_a_label(self):
        a = self.asset()
        leg = PlainProvider(dict(GOOD), model="gpt-4o-mini")
        with patch.object(smart, "_vision", lambda store: leg), patch.object(smart, "_candidate_models", lambda: ["gpt-4o-mini"]):
            res = smart.run_site_smart(a, "x", self.store)
        self.assertEqual((res["meta"]["via"], res["meta"]["label"], res["meta"]["fallback"]), ("", "gpt-4o-mini", False))

    def test_real_provider_is_never_called_under_test(self):
        a = self.asset()
        with patch.object(smart, "_candidate_models", lambda: ["m"]):
            res = smart.run_site_smart(a, "x", self.store)        # _vision ِ واقعی ⇒ زیرِ آزمون رد می‌شود
        self.assertTrue(res["meta"]["fallback"])
        self.assertIn("آزمون", res["meta"]["reason"])


# ═════════════════════════════ بازنویسیِ کارها

def norm(ops_):
    return catalog.normalize_operations(ops_)


class RewriteTests(SimpleTestCase):
    def result(self, **kw):
        return {"adjust": {}, "curve": {}, "preset": "", "ops": [], "notes": "یادداشت",
                "meta": {"via": "metis", "model": "gpt-4o-mini", "label": "متیس (gpt-4o-mini)", "fell_back": False,
                        "reason": "", "fallback": False}} | kw

    def build(self, operations, **kw):
        return smart._compose(norm(operations), self.result(**kw))

    def tools(self, ops_):
        return [o["tool"] for o in ops_]

    def test_smart_becomes_one_develop_with_preset_underlay_and_allowed_ops(self):
        ops_, eff = self.build(
            [{"tool": "kit_smart", "params": {"goal": "گرم"}}, {"tool": "export", "params": {"format": "jpeg", "quality": 88}}],
            adjust={"exposure": 0.4, "vibrance": 30}, preset="warm",
            ops=[{"tool": "color", "params": catalog.normalize_params("color", {"warmth": 20})}])
        self.assertTrue(eff)
        self.assertEqual(self.tools(ops_), ["develop", "color", "export"])
        dev = ops_[0]["params"]["adjust"]
        self.assertEqual(dev["exposure"], 0.4)
        self.assertEqual(dev["vibrance"], 30.0, "لغزندهٔ خودِ هوش مصنوعی روی فیلتر می‌نشیند")
        self.assertEqual(dev["temperature"], 18.0, "لغزنده‌های فیلتر زیرِ آن است")
        self.assertEqual(dev["highlightsSat"], 15.0)
        self.assertIn("متیس (gpt-4o-mini)", ops_[0]["reason"])
        self.assertEqual(ops_[-1]["params"]["quality"], 88)
        self.assertFalse(catalog.split(ops_)[0], "کارِ کیتی نمانده")

    def test_other_kit_ops_with_a_site_twin_are_converted_like_offline_presets(self):
        spots = [{"x": 0.2, "y": 0.3, "r": 0.02}]
        ops_, _ = self.build([
            {"tool": "kit_smart", "params": {"goal": "تمیز"}}, {"tool": "kit_auto"},
            {"tool": "kit_preset", "params": {"preset": "cool"}},
            {"tool": "kit_denoise", "params": {"luma": 30, "color": 20}},
            {"tool": "kit_sharpen", "params": {"amount": 55, "radius": 1.5, "masking": 25}},
            {"tool": "kit_adjust", "params": {"adjust": {"temperature": -40}, "curve": {"rgb": [[0, 10], [255, 240]]}}},
            {"tool": "kit_heal", "params": {"spots": spots}},
            {"tool": "export", "params": {"format": "png"}}], adjust={"exposure": 0.2})
        self.assertEqual(self.tools(ops_), ["develop", "auto_tone", "export"])
        p = ops_[0]["params"]
        self.assertEqual(p["adjust"]["temperature"], -40.0, "kit_adjust بالای فیلتر")
        self.assertEqual(p["adjust"]["shadowsSat"], 15.0, "شدتِ رنگِ سایه‌های فیلترِ «سرد» زیرِ لغزنده‌های دیگر مانده")
        self.assertEqual((p["adjust"]["noiseLuma"], p["adjust"]["noiseColor"]), (30.0, 20.0))
        self.assertEqual((p["adjust"]["sharpen"], p["adjust"]["sharpenRadius"], p["adjust"]["sharpenMasking"]), (55.0, 1.5, 25.0))
        self.assertEqual(p["adjust"]["exposure"], 0.2)
        self.assertEqual(p["curve"], {"rgb": [[0.0, 10.0], [255.0, 240.0]]})
        self.assertEqual(p["spots"], spots)
        self.assertEqual(ops_[1]["params"]["strength"], 70)

    def test_node_only_kit_ops_stay_in_front_as_node_ops(self):
        ops_, _ = self.build([
            {"tool": "kit_smart", "params": {"goal": "تمیز"}}, {"tool": "kit_background", "params": {"bg": "white"}},
            {"tool": "kit_upscale", "params": {"factor": "2"}}, {"tool": "crop_format", "params": {"format": "story", "fit": "contain"}},
            {"tool": "text", "params": {"text": "منو"}}, {"tool": "export", "params": {"format": "jpeg"}}], adjust={"exposure": 0.2})
        node, server = catalog.split(ops_)
        self.assertEqual([o["tool"] for o in node], ["kit_background", "kit_upscale"])
        self.assertEqual([o["tool"] for o in server], ["develop", "crop_format", "text", "export"])
        self.assertEqual([o["tool"] for o in smart.residual_node_ops(norm([
            {"tool": "kit_smart", "params": {"goal": "x"}}, {"tool": "kit_background"}, {"tool": "kit_adjust", "params": {"adjust": {"exposure": 1}}}]))],
                         ["kit_background"])

    def test_user_geometry_wins_but_ai_tone_replaces_older_tone(self):
        ops_, _ = self.build([
            {"tool": "kit_smart", "params": {"goal": "x"}},
            {"tool": "crop_format", "params": {"format": "story", "fit": "contain"}},
            {"tool": "color", "params": {"warmth": -50}}, {"tool": "export", "params": {"format": "jpeg"}}],
            adjust={"exposure": 0.1},
            ops=[{"tool": "crop_format", "params": catalog.normalize_params("crop_format", {"format": "square"})},
                 {"tool": "color", "params": catalog.normalize_params("color", {"warmth": 30})}])
        self.assertEqual(self.tools(ops_), ["develop", "color", "crop_format", "export"])
        crop = next(o for o in ops_ if o["tool"] == "crop_format")["params"]
        self.assertEqual((crop["format"], crop["fit"]), ("story", "contain"), "انتخابِ کاربر می‌ماند")
        color = next(o for o in ops_ if o["tool"] == "color")["params"]
        self.assertEqual(color["warmth"], 30, "انتخابِ تازهٔ هوش مصنوعی جای رنگِ قبلی را گرفت")

    def test_frame_first_order_is_kept_for_new_edits_only(self):
        # ترتیبِ قراردادیِ «قاب‌اول» (catalog.SERVER_ORDER_V2) را همین‌جا می‌گذاریم تا آزمون به نسخهٔ catalog وابسته نباشد
        rank = {k: i for i, k in enumerate(("develop", "liquify", "perspective", "rotate", "crop_rect", "crop_format", "auto_tone",
                                            "look", "color", "compose", "text", "logo", "watermark", "resize", "export"))}

        def op(tool, **p):
            return {"tool": tool, "params": catalog.normalize_params(tool, p)}

        operations = [op("kit_smart", goal="x"), op("text", text="منو"), op("crop_format", format="story", fit="contain"),
                      op("export", format="jpeg")]
        ai = {"adjust": {"exposure": 0.3}, "ops": [op("color", saturation=20)]}
        with patch.object(catalog, "_RANK_V2", rank, create=True):
            v2, _ = smart._compose(operations, self.result(**ai), order=2)
        self.assertEqual(self.tools(v2), ["develop", "crop_format", "color", "text", "export"], "قاب اول، بعد رنگ، بعد روکش")
        v1, _ = smart._compose(operations, self.result(**ai), order=1)
        self.assertEqual(self.tools(v1), ["develop", "color", "text", "crop_format", "export"],
                         "ترتیبِ قدیمی: کارهای کاربر به همان ترتیب")

    def test_existing_develop_is_the_base_of_a_refinement_and_is_replaced(self):
        prev = {"tool": "develop", "params": catalog.normalize_params("develop", {"adjust": {"temperature": 20, "exposure": 0.3}})}
        ops_, _ = self.build([prev, {"tool": "kit_smart", "params": {"goal": "گرم‌ترش کن"}},
                              {"tool": "export", "params": {"format": "jpeg"}}], adjust={"temperature": 35})
        self.assertEqual(self.tools(ops_), ["develop", "export"])
        adj = ops_[0]["params"]["adjust"]
        self.assertEqual((adj["temperature"], adj["exposure"]), (35.0, 0.3), "کلیدِ نیامده از ویرایشِ قبلی می‌ماند")
        base = smart.base_of(norm([prev, {"tool": "kit_smart", "params": {"goal": "x"}}]))
        self.assertEqual(base["adjust"], {"temperature": 20.0, "exposure": 0.3})

    def test_apply_site_with_no_effect_becomes_the_honest_fallback(self):
        asset = MagicMock(findings=[{"what": "dark"}], facts={})
        # لغزنده‌ای که همان پیش‌فرض است ⇒ هیچ اثری ⇒ جایگزینِ قطعی
        res = self.result(adjust={"exposure": 0.0}, notes="چیزی")
        ops_, final = smart.apply_site(asset, norm([{"tool": "kit_smart", "params": {"goal": "x"}},
                                                    {"tool": "export", "params": {"format": "jpeg"}}]), res)
        self.assertTrue(final["meta"]["fallback"])
        self.assertEqual(self.tools(ops_), ["auto_tone", "export"])
        self.assertIn("تغییری پیشنهاد نکرد", final["meta"]["reason"])

    def test_fallback_strength_follows_the_measurements(self):
        for kinds, lo, hi in (([{"what": "dark"}], 75, 75), ([{"what": "cast"}], 60, 60), ([], 50, 50)):
            r = smart.fallback_result(MagicMock(findings=kinds), "x")
            self.assertTrue(lo <= r["ops"][0]["params"]["strength"] <= hi)
        r = smart.fallback_result(MagicMock(findings=[{"what": "blurry"}]), "x")
        self.assertEqual([o["tool"] for o in r["ops"]], ["auto_tone", "color"])
        self.assertGreater(r["ops"][1]["params"]["sharpness"], 0)


# ═════════════════════════════ از ساختِ نسخه تا نتیجه

def pixels(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


class EndToEndTests(ApiTestBase):
    GOAL = "گرم و روشن، مناسبِ کافه"

    def post_smart(self, aid, extra=None):
        ops_ = [{"tool": "kit_smart", "params": {"goal": self.GOAL}, "reason": "دستورِ شما"}] + (extra or []) + \
               [{"tool": "export", "params": {"format": "jpeg", "quality": 90}}]
        r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "smart", "operations": ops_}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])

    def source_pixels(self, e):
        return pixels(self.media / e.asset.original)

    def online_node(self):
        return ComputeNode.objects.create(name="gpu-photo", last_seen=timezone.now(), capabilities={"photo": True})

    def finish_on_node(self, e, node, *, used_ai=False):
        job = ComputeJob.objects.get(uid=e.compute_job)
        got = compute.claim(node)
        self.assertEqual(got.pk, job.pk)
        src = compute.job_root(job) / job.inputs[job.payload["image"]]
        ops.load(src).convert("RGB").save(compute.output_path(job, "photo-a-edited.jpg"))
        compute.output_path(job, "photo-edit.json").write_text(json.dumps(
            {"recipe": {"adjust": {"temperature": 20}}, "notes": ["گرم‌تر شد"], "usedAi": used_ai}, ensure_ascii=False),
            encoding="utf-8")
        compute.finish(job, node, True, meta={"primary": "photo-a-edited.jpg", "engine": "photo"})
        return job

    # --- مسیرِ سرورِ پردازش وقتی «اول لوکال» و گره آنلاین است
    def test_local_first_with_online_node_keeps_the_node_path_and_records_it(self):
        set_order("local_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=11))
        node = self.online_node()
        with patch.object(smart, "run_site_smart", side_effect=AssertionError("site path must not run")):
            e = self.post_smart(aid)
        self.assertEqual(e.state, "NODE")
        job = ComputeJob.objects.get(uid=e.compute_job)
        self.assertEqual(job.payload["goal"], self.GOAL)
        self.assertEqual([o["tool"] for o in e.operations][:1], ["kit_smart"], "کارها بازنویسی نشدند")
        self.assertNotIn("original_operations", e.stats)
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        self.assertEqual((d["smart"]["path"], d["smart"].get("pending")), ("node", True))
        self.assertTrue(d["needs_node"])
        # گره جواب می‌دهد (با مدلِ بینا) ⇒ آماده + «لوکال»
        self.finish_on_node(e, node, used_ai=True)
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        self.assertEqual(d["state"], "READY", d)
        s = d["smart"]
        self.assertEqual((s["path"], s["via"], s["label"], s["fallback"], s["fell_back"]),
                         ("node", "local", "لوکال (سرورِ پردازش)", False, False))
        self.assertEqual(s["goal"], self.GOAL)
        self.assertEqual(s["adjust"], {"temperature": 20.0})
        self.assertTrue(s["model"], "مدلِ بینای لوکال (از تنظیماتِ هوش مصنوعی)")

    def test_node_path_without_a_vision_model_is_reported_honestly(self):
        set_order("local_first")
        (aid,) = self.upload(photo(900, 600, seed=12))
        node = self.online_node()
        e = self.post_smart(aid)
        self.finish_on_node(e, node, used_ai=False)
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        s = d["smart"]
        self.assertEqual((s["path"], s["via"], s["fallback"]), ("node", "", True))
        self.assertIn("بدون هوش مصنوعی", s["label"])
        self.assertTrue(s["reason"])

    # --- مسیرِ سایت
    def test_node_offline_local_first_runs_on_the_site_and_reports_local(self):
        set_order("local_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=13))
        local, metis = FakeLeg(dict(GOOD), model="qwen3-vl:30b"), FakeLeg(dict(GOOD))
        with Routed(local=local, metis=metis):
            e = self.post_smart(aid)
        e.refresh_from_db()
        self.assertEqual(e.state, "READY", e.error)
        self.assertEqual((len(local.calls), len(metis.calls)), (1, 0))
        self.assertEqual(ComputeJob.objects.count(), 0, "هیچ کاری به سرورِ پردازش نرفت")
        # کارها بازنویسی شدند و اصلشان مانده
        self.assertEqual([o["tool"] for o in e.operations], ["develop", "export"])
        self.assertEqual(e.operations[0]["params"]["adjust"]["exposure"], 0.45)
        self.assertEqual([o["tool"] for o in e.stats["original_operations"]], ["kit_smart", "export"])
        # نتیجه واقعاً با عکسِ اصل فرق دارد (روشن‌تر و گرم‌تر)
        before, after = self.source_pixels(e), pixels(self.media / e.files["result"])
        self.assertEqual(before.shape, after.shape)
        self.assertGreater(float(np.abs(after - before).mean()), 3.0)
        self.assertGreater(after.mean(), before.mean())
        self.assertGreater(after[..., 0].mean() - after[..., 2].mean(), before[..., 0].mean() - before[..., 2].mean())
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        s = d["smart"]
        self.assertEqual((s["path"], s["via"], s["model"], s["label"], s["fell_back"], s["fallback"]),
                         ("site", "local", "qwen3-vl:30b", "لوکال (qwen3-vl:30b)", False, False))
        self.assertEqual(s["adjust"]["exposure"], 0.45)
        self.assertEqual(s["notes"], "گرم‌تر و روشن‌تر شد.")
        self.assertEqual(s["goal"], self.GOAL)
        self.assertFalse(d["needs_node"])
        self.assertEqual(d["operations"][0]["tool"], "develop")
        self.assertIn("لوکال", d["operations"][0]["reason"])
        self.assertEqual(d["chosen"], [])

    def test_metis_first_runs_on_the_site_even_with_the_node_online(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=14))
        self.online_node()
        local, metis = FakeLeg(dict(GOOD), model="qwen3-vl:30b"), FakeLeg(dict(GOOD), model="gpt-4o-mini")
        with Routed(local=local, metis=metis):
            e = self.post_smart(aid)
        e.refresh_from_db()
        self.assertEqual(e.state, "READY", e.error)
        self.assertEqual((len(local.calls), len(metis.calls)), (0, 1))
        self.assertEqual(ComputeJob.objects.count(), 0)
        s = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]["smart"]
        self.assertEqual((s["path"], s["via"], s["model"], s["label"], s["fell_back"]),
                         ("site", "metis", "gpt-4o-mini", "متیس (gpt-4o-mini)", False))

    def test_metis_failing_falls_back_to_local_and_says_why(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=15))
        local = FakeLeg(dict(GOOD), model="qwen3-vl:30b")
        metis = FakeLeg(error=RuntimeError("خطای سرویس (402): payment required"))
        with Routed(local=local, metis=metis):
            e = self.post_smart(aid)
        e.refresh_from_db()
        self.assertEqual(e.state, "READY", e.error)
        s = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]["smart"]
        self.assertEqual((s["via"], s["fell_back"], s["fallback"]), ("local", True, False))
        self.assertIn("پشتیبان", s["label"])
        self.assertIn("اعتبار", s["reason"])

    def test_both_providers_failing_still_gives_a_brighter_photo_with_an_honest_note(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=16))
        local = FakeLeg(error=routing.NodeFailed("سرورِ پردازش خاموش است."))
        metis = FakeLeg(error=RuntimeError("اتصال برقرار نشد"))
        with Routed(local=local, metis=metis):
            e = self.post_smart(aid)
        e.refresh_from_db()
        self.assertEqual(e.state, "READY", e.error)
        self.assertEqual(e.operations[0]["tool"], "auto_tone")
        self.assertEqual(e.operations[-1]["tool"], "export")
        self.assertTrue(all(o["tool"] in ("auto_tone", "color", "export") for o in e.operations))
        before, after = self.source_pixels(e), pixels(self.media / e.files["result"])
        self.assertGreater(after.mean(), before.mean() + 10, "عکسِ تیره باید روشن‌تر شده باشد")
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        s = d["smart"]
        self.assertEqual((s["path"], s["via"], s["fallback"]), ("site", "", True))
        self.assertEqual(s["label"], smart.FALLBACK_LABEL)
        self.assertIn("دستورِ شما اجرا نشد", s["notes"])
        self.assertIn("هیچ‌کدام از دو مسیر", s["reason"])
        self.assertEqual(d["state"], "READY")

    def test_node_only_companion_ops_still_queue_after_the_site_rewrite(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=17))
        metis = FakeLeg(dict(GOOD), model="gpt-4o-mini")
        with Routed(local=None, metis=metis):
            e = self.post_smart(aid, extra=[{"tool": "kit_background", "params": {"bg": "white"}}])
        e.refresh_from_db()
        self.assertEqual(e.state, "NODE")
        self.assertEqual([o["tool"] for o in e.operations], ["kit_background", "develop", "export"])
        job = ComputeJob.objects.get(uid=e.compute_job)
        self.assertNotIn("goal", job.payload, "هوشِ مصنوعی دیگر روی گره نمی‌رود")
        self.assertTrue(job.payload["recipe"]["background"]["remove"])
        self.assertEqual(job.payload["recipe"]["output"]["format"], "jpeg")        # کارِ سرورِ سایت دنبالش است
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        self.assertTrue(d["needs_node"])
        self.assertEqual(d["smart"]["via"], "metis")
        self.finish_on_node(e, self.online_node())
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        self.assertEqual(d["state"], "READY", d)
        self.assertEqual(d["smart"]["via"], "metis", "پس از گره هم ثبتِ مسیرِ سایت نمی‌ماند/عوض نمی‌شود")
        self.assertEqual(d["smart"]["path"], "site")

    def test_site_path_converts_companion_kit_ops_and_keeps_user_server_ops(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=18))
        metis = FakeLeg({"adjust": {"vibrance": 20}, "notes": "رنگ زنده‌تر"}, model="gpt-4o-mini")
        with Routed(local=None, metis=metis):
            e = self.post_smart(aid, extra=[
                {"tool": "kit_adjust", "params": {"adjust": {"exposure": 0.3}}},
                {"tool": "crop_format", "params": {"format": "square", "fit": "cover", "focus": "center"}}])
        e.refresh_from_db()
        self.assertEqual(e.state, "READY", e.error)
        self.assertEqual([o["tool"] for o in e.operations], ["develop", "crop_format", "export"])
        adj = e.operations[0]["params"]["adjust"]
        self.assertEqual((adj["exposure"], adj["vibrance"]), (0.3, 20.0))
        self.assertIn("prompt", metis.calls[0])
        self.assertIn('"exposure": 0.3', metis.calls[0]["prompt"], "تنظیماتِ فعلی در پرسش آمد")
        with Image.open(self.media / e.files["result"]) as im:
            self.assertEqual(im.size, (1080, 1080))

    def test_refine_after_a_site_edit_keeps_earlier_sliders_and_asks_again(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=19))
        metis = FakeLeg(dict(GOOD), model="gpt-4o-mini")
        with Routed(local=None, metis=metis):
            e = self.post_smart(aid)
        e.refresh_from_db()
        prior = [{"tool": o["tool"], "params": o["params"]} for o in e.operations if o["tool"] != "export"]
        metis2 = FakeLeg({"adjust": {"temperature": 40}, "notes": "گرم‌تر"}, model="gpt-4o-mini")
        with Routed(local=None, metis=metis2):
            r = self.api.post(f"{self.base}/edits/", {"assets": [aid], "recipe": "smart", "operations": prior + [
                {"tool": "kit_smart", "params": {"goal": "گرم‌ترش کن"}}, {"tool": "export", "params": {"format": "jpeg"}}]},
                              format="json")
        e2 = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e2.state, "READY", e2.error)
        adj = e2.operations[0]["params"]["adjust"]
        self.assertEqual((adj["temperature"], adj["exposure"]), (40.0, 0.45))
        self.assertIn('"temperature": 18', metis2.calls[0]["prompt"])

    def test_retry_asks_the_ai_again_from_the_original_operations(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, dark=True, seed=20))
        metis = FakeLeg(error=RuntimeError("اتصال برقرار نشد"))
        with Routed(local=None, metis=metis):
            e = self.post_smart(aid)
        self.assertTrue(self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]["smart"]["fallback"])
        good = FakeLeg(dict(GOOD), model="gpt-4o-mini")
        with Routed(local=None, metis=good):
            r = self.api.post(f"{self.base}/edits/{e.pk}/retry/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        new = r.json()["new"]
        self.assertEqual(new["state"], "READY")
        self.assertEqual((new["smart"]["via"], new["smart"]["fallback"]), ("metis", False))
        self.assertEqual(len(good.calls), 1)

    def test_cancel_while_the_ai_is_thinking_wins(self):
        set_order("metis_first")
        (aid,) = self.upload(photo(900, 600, seed=21))
        holder = {}

        def slow(model, prompt, **kw):
            services.cancel(PhotoEdit.objects.get(pk=holder["id"]))     # کاربر «لغو» زد
            return dict(GOOD), "{}"

        leg = FakeLeg(dict(GOOD))
        leg.generate_json = slow
        a_ops = [{"tool": "kit_smart", "params": {"goal": "x"}}, {"tool": "export", "params": {"format": "jpeg"}}]
        edits = services.create_edits(self.store, self.owner, [aid], "smart", a_ops)
        holder["id"] = edits[0].pk
        with Routed(local=None, metis=leg):
            services.start(PhotoEdit.objects.get(pk=edits[0].pk))
        e = PhotoEdit.objects.get(pk=edits[0].pk)
        self.assertEqual(e.state, "CANCELLED")
        self.assertEqual(e.operations[0]["tool"], "kit_smart", "بازنویسی روی نسخهٔ لغوشده نمی‌نشیند")

    # --- plan / recipes / needs_node
    def test_recipe_list_and_plan_tell_the_truth(self):
        set_order("local_first")
        rec = {r["key"]: r for r in catalog.recipe_list()}
        self.assertFalse(rec["smart"]["needs_node"])
        self.assertTrue(rec["product_white"]["needs_node"], "دیگر دستورها همچنان سرورِ پردازش می‌خواهند")
        self.assertIn("بی سرورِ پردازشِ روشن", rec["smart"]["help"])
        (aid,) = self.upload(photo(seed=22))
        plan = self.api.post(f"{self.base}/plan/", {"asset": aid, "recipe": "smart"}, format="json").json()
        smart_op = next(o for o in plan["operations"] if o["tool"] == "kit_smart")
        self.assertEqual(plan["smart"]["path"], "site")
        self.assertEqual(smart_op["where"], "server")
        self.assertIn("از سرورِ سایت", smart_op["reason"])
        self.assertIn("اول لوکال", smart_op["reason"])
        self.online_node()
        plan = self.api.post(f"{self.base}/plan/", {"asset": aid, "recipe": "smart"}, format="json").json()
        smart_op = next(o for o in plan["operations"] if o["tool"] == "kit_smart")
        self.assertEqual((plan["smart"]["path"], smart_op["where"]), ("node", "node"))
        self.assertIn("سرورِ پردازش", smart_op["reason"])
        set_order("metis_first")
        plan = self.api.post(f"{self.base}/plan/", {"asset": aid, "recipe": "smart"}, format="json").json()
        self.assertEqual(plan["smart"]["path"], "site")
        self.assertIn("اول متیس", next(o for o in plan["operations"] if o["tool"] == "kit_smart")["reason"])

    def test_queued_edit_needs_node_only_when_the_decision_is_the_node(self):
        (aid,) = self.upload(photo(seed=23))
        asset = PhotoAsset.objects.get(pk=aid)
        e = PhotoEdit.objects.create(asset=asset, number=1, operations=norm([
            {"tool": "kit_smart", "params": {"goal": "x"}}, {"tool": "export", "params": {"format": "jpeg"}}]))
        set_order("local_first")
        self.assertFalse(services.edit_dict(e)["needs_node"])
        self.online_node()
        self.assertTrue(services.edit_dict(e)["needs_node"])
        set_order("metis_first")
        self.assertFalse(services.edit_dict(e)["needs_node"])
        e.operations = norm([{"tool": "kit_smart", "params": {"goal": "x"}}, {"tool": "kit_background"}])
        self.assertTrue(services.edit_dict(e)["needs_node"], "کارِ بی‌همتا (پس‌زمینه) سرورِ پردازش می‌خواهد")

    def test_recover_stale_does_not_restart_a_site_edit_that_is_waiting_for_the_ai(self):
        (aid,) = self.upload(photo(seed=24))
        e = PhotoEdit.objects.create(asset=PhotoAsset.objects.get(pk=aid), number=1, operations=norm([
            {"tool": "kit_smart", "params": {"goal": "x"}}]), stats={"smart_running": True})
        PhotoEdit.objects.filter(pk=e.pk).update(updated_at=timezone.now() - timedelta(minutes=8))
        e.refresh_from_db()
        self.assertFalse(services.recover_stale(e))
        PhotoEdit.objects.filter(pk=e.pk).update(updated_at=timezone.now() - timedelta(minutes=13))
        e.refresh_from_db()
        self.assertTrue(services.recover_stale(e), "اگر پردازه وسطِ کار مُرد، بعد از ۱۲ دقیقه دوباره شروع شود")
        PhotoEdit.objects.filter(pk=e.pk).update(stats={}, updated_at=timezone.now() - timedelta(minutes=6))
        e.refresh_from_db()
        self.assertTrue(services.recover_stale(e))
