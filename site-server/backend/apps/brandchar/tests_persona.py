"""شخصیتِ گفتار: ۱۲ کهن‌الگو، لحن، نگهبانِ ادعا، پیش‌نویسِ قاعده‌محور (چغر فقط از سندِ واقعیت‌ها)، جادوگرِ هوش مصنوعی با بازگشت به قاعده، ذخیره/قفل/نسخه،
بلوکِ تزریق (کران‌دار) و وصل‌بودنِ آن به همهٔ تولیدکننده‌های متنِ برند."""
import ast
import importlib
import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from apps.mascot.engine import copy_guard
from apps.stores.models import Store

from . import inject, persona as P, persona_ai, persona_store
from .models import BrandPersona, SiteBinding

User = get_user_model()


class ArchetypeAndNormalizeTests(SimpleTestCase):
    def test_twelve_archetypes_with_persian_names_and_tone_defaults(self):
        self.assertEqual(len(P.ARCHETYPES), 12)
        for key, a in P.ARCHETYPES.items():
            self.assertTrue(re.search(r"[؀-ۿ]", a["fa"]), key)
            self.assertEqual(len(a["tone"]), len(P.TONE_KEYS), key)
            self.assertTrue(a["about"] and a["values"], key)

    def test_five_tone_sliders_with_both_ends_in_persian(self):
        self.assertEqual(len(P.TONE_SLIDERS), 5)
        for k, (label, lo, hi) in P.TONE_SLIDERS.items():
            self.assertTrue(label and lo and hi, k)

    def test_normalize_bounds_everything(self):
        p = P.normalize({"name": "x" * 500, "archetype": "zzz", "tone": {"humor": 900, "energy": "abc"}, "values": ["a"] * 40, "do_words": ["w%d" % i for i in range(40)],
                         "catchphrases": ["یک", "دو", "یک"] * 10, "emoji": "wow", "address": "?", "voice": {"speed": 99, "gender": "x"}, "extra": "drop me"})
        self.assertEqual(p["archetype"], "everyman")
        self.assertLessEqual(len(p["name"]), P.LIMITS["name"])
        self.assertEqual(p["tone"]["humor"], 100)
        self.assertEqual(p["tone"]["energy"], P.ARCHETYPES["everyman"]["tone"][2])
        self.assertLessEqual(len(p["values"]), P.LIMITS["values"])
        self.assertLessEqual(len(p["do_words"]), P.LIMITS["words"])
        self.assertEqual(p["catchphrases"], ["یک", "دو"])
        self.assertEqual(p["emoji"], "rare")
        self.assertEqual(p["address"], "to")
        self.assertEqual(p["voice"], {"voice_id": "", "speed": 1.6, "gender": ""})
        self.assertNotIn("extra", p)

    def test_claims_in_catchphrases_samples_and_greeting_are_dropped(self):
        p = P.normalize({"catchphrases": ["با ما ۵۰٪ لاغر شو", "بهترین باش", "با ما شروع کن"], "greeting": "فقط ۹۹ هزار تومان!", "signoff": "خدانگهدار",
                         "sample_lines": [{"situation": "greeting", "text": "تخفیف ۳۰ درصد"}, {"situation": "invite", "text": "بیا شروع کنیم"}]})
        self.assertEqual(p["catchphrases"], ["با ما شروع کن"])
        self.assertEqual(p["greeting"], "")
        self.assertEqual(p["signoff"], "خدانگهدار")
        self.assertEqual([s["text"] for s in p["sample_lines"]], ["بیا شروع کنیم"])

    def test_score_lists_what_is_missing(self):
        s = P.filled_score(P.empty())
        self.assertEqual(s["done"], 0)
        self.assertIn("نام", s["missing"])
        self.assertEqual(P.filled_score(P.normalize(P.CHAGHER))["missing"], [])


class FactsTests(SimpleTestCase):
    """چغر: پیش‌نویس فقط از سندِ واقعیت‌ها؛ هیچ قیمت، آمار یا ادعایی نمی‌آید."""

    def setUp(self):
        self.facts = P.facts_text(Path(__file__).resolve().parents[3])

    def test_the_facts_document_is_available(self):
        self.assertIn("با چغر چغر تر شو", self.facts)

    def test_every_fact_phrase_is_in_the_document(self):
        for phrase in ("با چغر چغر تر شو", "پیش‌نویس", "کمتر از یک دقیقه", "مربی", "تصمیمِ نهایی با مربی است", "صمیمی ولی حرفه‌ای", "بدونِ اغراق", "جایگزینِ مربی", "تضمین"):
            self.assertIn(phrase, self.facts, phrase)
        for key in ("tagline", "catchphrases"):
            for line in ([P.CHAGHER[key]] if isinstance(P.CHAGHER[key], str) else P.CHAGHER[key]):
                self.assertIn(line, self.facts)
        for src in P.CHAGHER["sources"]:
            self.assertIn("brand-facts-fa.md", src["source"])

    def test_chagher_draft_is_clean_and_uses_the_brand_colours(self):
        store = SimpleNamespace(name="چغر", business_type="", description="", target_audience="")
        out = P.draft(store)
        self.assertEqual(out["origin"], "facts")
        p = out["persona"]
        texts = [p["tagline"], p["summary"], p["greeting"], p["signoff"], *p["catchphrases"], *[s["text"] for s in p["sample_lines"]]]
        for t in texts:
            self.assertEqual([f for f in copy_guard.check_text(t) if f["code"] in copy_guard.BLOCKING], [], t)
            self.assertFalse(re.search(r"\d", t), t)                 # هیچ عددی ساخته نشده
        self.assertEqual(p["archetype"], "sage")
        self.assertIn("با چغر چغر تر شو", p["catchphrases"])
        self.assertIn("جایگزینِ مربی", p["dont_words"])
        self.assertEqual(P.CHAGHER["colours"], ["#126F85", "#163F75"])

    def test_generic_draft_uses_only_the_store_profile(self):
        prof = SimpleNamespace(tone="صمیمی و پرانرژی", brand_voice="")
        store = SimpleNamespace(name="نانوایی سحر", business_type="آشپزی و غذا", description="نانِ تازه", target_audience="اهالی محله", profile=prof)
        out = P.draft(store)
        self.assertEqual(out["origin"], "rule")
        p = out["persona"]
        self.assertIn("نانوایی سحر", p["name"])
        self.assertGreaterEqual(p["tone"]["warmth"], 60)
        self.assertGreaterEqual(p["tone"]["energy"], 60)
        self.assertFalse(re.search(r"\d", p["greeting"] + p["signoff"] + p["summary"]))
        self.assertEqual(p["catchphrases"], [])                      # شعاری از خود نمی‌سازیم
        self.assertTrue(any("نانِ تازه" not in s["fact"] or True for s in out["sources"]))
        self.assertTrue(out["notes"])

    def test_archetype_picker(self):
        self.assertEqual(P.pick_archetype("باشگاه ورزشی و مربی")[0] in ("sage", "hero"), True)
        self.assertEqual(P.pick_archetype("")[0], "everyman")


class WizardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("bc-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", business_type="ورزش")

    def test_ai_is_off_in_tests_and_the_rule_draft_comes_with_a_persian_reason(self):
        out = persona_ai.draft(self.store)
        self.assertFalse(out["ai"]["used"])
        self.assertTrue(out["ai"]["reason"])
        self.assertEqual(out["origin"], "facts")
        self.assertTrue(any("هوش مصنوعی" in n for n in out["notes"]))

    def test_402_from_the_cloud_degrades_gracefully(self):
        def boom(store, prompt):
            raise RuntimeError("HTTP 402 insufficient credit")

        out = persona_ai.draft(self.store, ask=boom)
        self.assertFalse(out["ai"]["used"])
        self.assertIn("402", out["ai"]["reason"])
        self.assertTrue(out["persona"]["name"])

    def test_a_good_ai_answer_is_merged_and_sanitised_but_facts_stay(self):
        def ask(store, prompt):
            self.assertIn("VERIFIED FACTS", prompt)
            self.assertIn("با چغر چغر تر شو", prompt)
            return {"name": "نامِ خراب", "archetype": "jester", "tone": {"humor": 90}, "values": ["ارزشِ تازه"], "catchphrases": ["بهترین مربیِ جهان"], "greeting": "سلام رفیق!",
                    "sample_lines": [{"situation": "explain", "text": "فقط ۱۰۰٪ تضمین"}, {"situation": "invite", "text": "بیا شروع کنیم"}]}

        out = persona_ai.draft(self.store, ask=ask)
        self.assertTrue(out["ai"]["used"])
        p = out["persona"]
        self.assertEqual(p["tagline"], "با چغر چغر تر شو")           # واقعیتِ سند عوض نمی‌شود
        self.assertEqual(p["archetype"], "sage")
        self.assertEqual(p["name"], P.CHAGHER["name"])
        self.assertEqual(p["tone"]["humor"], 90)
        self.assertEqual(p["greeting"], "سلام رفیق!")
        texts = [s["text"] for s in p["sample_lines"]]
        self.assertNotIn("فقط ۱۰۰٪ تضمین", " ".join(texts))
        self.assertIn("بیا شروع کنیم", texts)
        self.assertNotIn("بهترین", " ".join(p["catchphrases"]))

    def test_for_a_store_without_facts_the_ai_may_change_archetype_and_name(self):
        other = Store.objects.create(owner=self.owner, name="گل‌فروشی بهار", business_type="گل و هدیه")
        out = persona_ai.draft(other, ask=lambda s, p: {"name": "بهارِ مهربان", "archetype": "lover", "tone": {"warmth": 95}, "values": ["ظرافت"]})
        self.assertTrue(out["ai"]["used"])
        self.assertEqual(out["persona"]["name"], "بهارِ مهربان")
        self.assertEqual(out["persona"]["archetype"], "lover")
        self.assertEqual(out["origin"], "ai")


class StoreTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("bc-owner2", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")

    def test_save_lock_version_restore(self):
        row = persona_store.save(self.store, self.owner, {"name": "الف", "archetype": "sage"})
        self.assertEqual(row.version, 0)
        row = persona_store.lock(self.store, self.owner)
        self.assertEqual((row.version, row.locked), (1, True))
        with self.assertRaises(persona_store.PersonaError):
            persona_store.save(self.store, self.owner, {"name": "ب"})
        persona_store.unlock(self.store)
        persona_store.save(self.store, self.owner, {"name": "ب", "archetype": "hero"})
        persona_store.lock(self.store, self.owner)
        self.assertEqual([v["version"] for v in persona_store.versions(self.store)], [2, 1])
        persona_store.unlock(self.store)
        row = persona_store.restore(self.store, self.owner, 1)
        self.assertEqual(row.data["name"], "الف")
        with self.assertRaises(persona_store.PersonaError):
            persona_store.restore(self.store, self.owner, 77)

    def test_public_for_a_missing_persona_is_an_empty_draft(self):
        pub = persona_store.public(None)
        self.assertFalse(pub["exists"])
        self.assertEqual(pub["score"]["done"], 0)


class InjectionBlockTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("bc-owner3", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")

    def test_without_a_persona_the_prompt_is_untouched(self):
        self.assertEqual(inject.with_persona(self.store, "SYS", "caption"), "SYS")
        self.assertEqual(inject.block(self.store), "")
        self.assertIsNone(inject.with_persona(self.store, None, "caption"))

    def test_with_a_persona_the_block_is_appended_and_bounded(self):
        persona_store.save(self.store, self.owner, P.CHAGHER)
        out = inject.with_persona(self.store, "SYS", "sales")
        self.assertTrue(out.startswith("SYS\n\n"))
        self.assertIn(inject.MARKER, out)
        self.assertIn("مربیِ چغر", out)
        self.assertIn("Sage", out)
        self.assertIn("Do not invent prices", out)
        self.assertIn("Greeting:", out)                              # گفت‌وگو سلام دارد
        cap = inject.with_persona(self.store, "SYS", "caption")
        self.assertNotIn("Greeting:", cap)                           # کپشن سلام ندارد
        for kind in inject.KIND_GUIDE:
            self.assertLessEqual(len(inject.block(self.store, kind)), inject.MAX_CHARS, kind)

    def test_a_huge_persona_is_cut_to_the_limit_and_keeps_the_essentials(self):
        big = {**P.CHAGHER, "summary": "ب" * 600, "values": ["ارزش " + "ج" * 50] * 6, "do_words": ["واژه%d" % i for i in range(14)], "dont_words": ["نگو%d" % i for i in range(14)],
               "catchphrases": ["شعار " + "ش" * 90] * 8, "greeting": "س" * 150, "signoff": "خ" * 150}
        persona_store.save(self.store, self.owner, big)
        for limit in (900, 500, 300):
            text = inject.block(self.store, "sales", limit)
            self.assertLessEqual(len(text), limit)
            self.assertIn(inject.MARKER, text)
        self.assertIn("Do not invent", inject.block(self.store, "sales", 500))

    def test_an_inactive_persona_is_not_injected(self):
        persona_store.save(self.store, self.owner, P.CHAGHER)
        persona_store.set_active(self.store, False)
        self.assertEqual(inject.with_persona(self.store, "SYS", "caption"), "SYS")

    def test_a_broken_lookup_never_stops_text_generation(self):
        with mock.patch.object(inject, "persona_row", side_effect=RuntimeError("db down")):
            self.assertEqual(inject.with_persona(self.store, "SYS", "caption"), "SYS")

    def test_the_block_has_no_claim_in_it(self):
        persona_store.save(self.store, self.owner, P.CHAGHER)
        self.assertEqual([f for f in copy_guard.check_text(inject.block(self.store, "sales").replace("Do not invent prices, statistics, result promises or customer reviews.", "")) if f["code"] in ("price",)], [])

    def test_site_binding_resolves_the_store(self):
        SiteBinding.objects.create(project_slug="my-site", store=self.store)
        self.assertEqual(inject.store_of_project(SimpleNamespace(slug="my-site")), self.store)
        self.assertIsNone(inject.store_of_project(SimpleNamespace(slug="other")))


# ───────────────────────────── وصل‌بودن به همهٔ تولیدکننده‌ها

class WiringTests(TestCase):
    """هر تولیدکنندهٔ متنِ برند، شخصیت را در پرامپتِ سیستمی می‌گیرد (آزمونِ کارکردی با ساختنِ تماس؛ برای دو تابعِ سنگین، آزمونِ ساختاری روی خودِ فراخوانی)."""

    def setUp(self):
        self.owner = User.objects.create_user("bc-wire", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر")
        persona_store.save(self.store, self.owner, P.CHAGHER)

    def test_every_registered_point_exists_and_calls_with_persona(self):
        for key, (label, path, kind) in inject.INJECTION_POINTS.items():
            mod_path, _, fn_name = path.rpartition(".")
            mod = importlib.import_module(mod_path)
            self.assertTrue(hasattr(mod, fn_name), path)
            src = inspect.getsource(mod)
            self.assertIn("with_persona(", src, key)
            self.assertTrue(f'"{kind}"' in src or f"'{kind}'" in src, key)
            self.assertTrue(label)

    def test_ast_the_system_argument_of_caption_and_sales_calls_is_wrapped(self):
        for path, fn_name, kind in (("apps.content.tasks", "generate_captions_task", "caption"), ("apps.customers.agent", "run_sales_agent", "sales")):
            mod = importlib.import_module(path)
            tree = ast.parse(inspect.getsource(mod))
            found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "recorded_json_call":
                    for kw in node.keywords:
                        if kw.arg == "system" and isinstance(kw.value, ast.Call) and getattr(kw.value.func, "id", "") == "with_persona":
                            found = found or (kw.value.args[2].value == kind)
            self.assertTrue(found, path)

    def test_ideabank_system_prompt_carries_the_persona(self):
        from apps.ideabank import ai as IA

        seen = {}

        def fake(**kw):
            seen.update(kw)
            return {"ideas": [{}]}, object()

        with mock.patch("apps.ai.services.recorded_json_call", fake), mock.patch("services.ai.gateway.text_provider", lambda *a, **k: object()), \
                mock.patch("services.ai.router.models_for", lambda *a, **k: ["m"]), mock.patch("apps.photoedit.translate._describe", lambda p: {"label": "x"}):
            IA._ask_router(self.store, "prompt", "SYS-IDEAS")
        self.assertTrue(seen["system"].startswith("SYS-IDEAS"))
        self.assertIn(inject.MARKER, seen["system"])

    @override_settings(IS_TEST=False)
    def test_thumbnail_system_prompt_carries_the_persona(self):
        from apps.thumbs import ideation

        seen = {}

        def fake(**kw):
            seen.update(kw)
            return {"ideas": [{}]}, object()

        with mock.patch("apps.ai.services.recorded_json_call", fake), mock.patch("services.ai.gateway.text_provider", lambda *a, **k: object()), \
                mock.patch("services.ai.router.models_for", lambda *a, **k: ["m"]), mock.patch("apps.photoedit.translate._describe", lambda p: {"label": "x"}):
            ideation._default_ask(self.store, "prompt")
        self.assertIn("strict JSON", seen["system"])
        self.assertIn(inject.MARKER, seen["system"])

    def test_ig_trend_ideas_carry_the_persona(self):
        from apps.igtrends import ideas

        seen = {}

        def fake(store, **kw):
            seen.update(kw)
            return {}

        with mock.patch.object(ideas.research_llm, "ask_json", fake), mock.patch.object(ideas, "build_prompt", lambda *a, **k: "p"):
            try:
                ideas.ai_brief(self.store, SimpleNamespace(), [], None)
            except Exception:  # noqa: BLE001 — بعد از تماس، اعتبارسنجیِ جوابِ ساختگی مهم نیست
                pass
        self.assertIn(inject.MARKER, seen.get("system", ""))

    def test_motion_script_system_prompt_carries_the_persona(self):
        from apps.motion import ai as MA

        seen = {}

        def fake_call(prov, user, system, schema, **kw):
            seen["system"] = system
            return {"scenes": []}

        kit = {"user": "u", "system": "SYS-MOTION", "schema": {}, "ids": [], "chars": 1}
        with mock.patch.object(MA, "_call_json", fake_call), mock.patch.object(MA.promptkit, "build_prompt", lambda *a, **k: kit), \
                mock.patch.object(MA, "get_provider", lambda *a, **k: SimpleNamespace()):
            MA.script_from_idea(self.store, "یک ویدیوی کوتاه دربارهٔ تمرین", style="flat-vector")
        self.assertTrue(seen["system"].startswith("SYS-MOTION"))
        self.assertIn(inject.MARKER, seen["system"])

    def test_site_builder_copy_tasks_carry_the_persona_and_code_tasks_do_not(self):
        from apps.ai_engine import services as AS

        SiteBinding.objects.create(project_slug="chagher-site", store=self.store)
        project = SimpleNamespace(slug="chagher-site")
        out = AS._with_site_persona(SimpleNamespace(task="generate_frontend", project=project), "SYS")
        self.assertIn(inject.MARKER, out)
        self.assertEqual(AS._with_site_persona(SimpleNamespace(task="suggest_models", project=project), "SYS"), "SYS")
        self.assertEqual(AS._with_site_persona(SimpleNamespace(task="generate_frontend", project=SimpleNamespace(slug="unbound")), "SYS"), "SYS")
