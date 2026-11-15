"""آزمونِ «چغر» (محصولِ خودِ مالک، فروشگاهِ ۳۴): ایده‌ها فقط از واقعیت‌های ``docs/chagher/brand-facts-fa.md`` و پروفایلِ فروشگاه؛ بدونِ قیمت و آمار.

و خودآزمونِ بانکِ ایده (آفلاین + سنجشِ جوابِ مدل + وصل‌شدن به آزمونِ خودکارِ سرورِ پردازش)."""
import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.stores.models import Store, StoreProfile

from . import bank, demo, fill, guard, selftest
from .catalog import FORMATS

User = get_user_model()
DOCS = Path(__file__).resolve().parents[3] / "docs" / "chagher" / "brand-facts-fa.md"
PRICE_OR_STAT = ("تومان", "ریال", "درصد", "٪", "%", "تخفیف", "رایگان", "تضمین", "۶۰۰", "۹۸", "۵۰۰", "۱۳۰۰", "۲۴/۷")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("‌", "").replace("ِ", "").replace("ٔ", "").replace("‌", ""))


class ChagherDemoTests(SimpleTestCase):
    def test_the_verified_facts_are_really_in_the_brand_document(self):
        if not DOCS.is_file():
            self.skipTest("docs/chagher/brand-facts-fa.md در این نسخه نیست")
        doc = norm(DOCS.read_text(encoding="utf-8"))
        for fact in demo.CHAGHER_FACTS:
            self.assertIn(norm(fact), doc, f"جملهٔ برند در سند نیست: {fact}")
        self.assertIn(norm(demo.CHAGHER_TONE.split("؛")[0]), doc)
        for phrase in ("«پیش‌نویس» را همیشه بگو", "تصمیمِ نهایی با مربی است", "بدونِ «جایگزینِ مربی»", "بدونِ نظرِ مشتریِ ساختگی"):
            self.assertIn(norm(phrase), doc, phrase)
            self.assertIn(norm(phrase), norm(demo.CHAGHER_INSTRUCTION), phrase)
        self.assertEqual(guard.problems(demo.CHAGHER_INSTRUCTION), [], "دستورِ چغر نباید واژهٔ ریسکی داشته باشد")

    def test_demo_ideas_use_the_brand_facts_and_invent_nothing(self):
        r = demo.run(count=10, use_ai=False)
        self.assertEqual(r["via"], "formula")
        ctx = fill.context(demo.stand_in())
        source = " ".join(demo.CHAGHER_FACTS) + " " + demo.CHAGHER_TOPIC
        text = ""
        for i in r["ideas"]:
            filled = " ".join(fill.fill_text(i[f], ctx) for f in bank.TEXT_FIELDS)
            text += " " + filled
            self.assertEqual(guard.problems(filled, source), [], filled)
            self.assertNotIn("{", filled)
            self.assertIn(i["format"], FORMATS)
        for w in PRICE_OR_STAT:
            self.assertNotIn(w, text, f"قیمت/آمار در ایده‌های چغر: {w}")
        self.assertIn("چغر", text)                                                           # {فروشگاه} پر شده
        self.assertTrue(any(f in text for f in demo.CHAGHER_FACTS), "هیچ جملهٔ تأییدشدهٔ برند در ایده‌ها نیامد")
        self.assertNotIn("جایگزینِ مربی هستیم", text)

    def test_audience_and_business_come_from_the_profile(self):
        ctx = fill.context(demo.stand_in())
        self.assertEqual(ctx["values"]["مخاطب"], "مربی‌های باشگاه و مربی‌های شخصی")
        self.assertEqual(ctx["values"]["فروشگاه"], "چغر")
        self.assertEqual(ctx["tone"], demo.CHAGHER_TONE)


class ChagherStoreTests(TestCase):
    def test_a_real_store_row_works_end_to_end_and_the_facts_survive_saving(self):
        owner = User.objects.create_user("chagher-owner", password="x")
        p = demo.CHAGHER_PROFILE
        store = Store.objects.create(owner=owner, name=p["name"], business_type=p["business_type"], target_audience=p["target_audience"])
        StoreProfile.objects.filter(store=store).update(tone=p["tone"])
        store = Store.objects.get(pk=store.pk)
        r = demo.run(store, count=6, save=True)
        self.assertEqual(r["saved"], len(r["ideas"]))
        saved = bank.list_ideas(store, source="mine", ctx=fill.context(store))
        self.assertEqual(len(saved), r["saved"])
        for i in saved:
            filled = " ".join(i["filled"].values())
            self.assertEqual(guard.problems(filled, " ".join(demo.CHAGHER_FACTS) + " " + demo.CHAGHER_TOPIC), [])
        with self.assertRaises(ValueError):
            demo.run(save=True)                                                              # فروشگاهِ ساختگی ذخیره نمی‌شود

    def test_management_commands_run(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("ideabank_demo", "--count", "4", stdout=out)
        self.assertIn("via=formula", out.getvalue())
        self.assertIn("چغر", out.getvalue())
        with self.assertRaises(SystemExit) as cm:
            call_command("ideabank_selftest", stdout=StringIO())
        self.assertEqual(cm.exception.code, 0)


class SelfTestTests(TestCase):
    def test_offline_selftest_passes_every_check(self):
        res = selftest.run_offline()
        self.assertTrue(res["ok"], res)
        self.assertEqual([c["key"] for c in res["checks"]],
                         ["seeds", "fill", "formulas_without_ai", "ai_path_validated", "ai_back_again"])

    def test_node_prompt_is_the_real_generator_prompt_without_prices(self):
        prompt, system = selftest.node_prompt()
        for w in ("تومان", "درصد", "تخفیف", "۶۰۰"):
            self.assertNotIn(w, prompt)
        self.assertIn("با چغر چغر تر شو", prompt)
        self.assertIn("NEVER write prices", prompt)
        spec = selftest.node_spec("qwen3:8b")
        self.assertEqual(spec["kind"], "ollama.generate")
        p = spec["payload"]
        self.assertEqual((p["model"], p["stream"], p["think"], p["format"]), ("qwen3:8b", False, False, "json"))
        self.assertTrue(p["prompt"] and p["system"])

    def test_node_check_accepts_a_good_answer_and_rejects_bad_ones(self):
        good = {"ideas": [{"category": "tips", "title": "مربیِ تازه‌کار از کجا شروع کند؟", "logline": "راهنمای شروعِ کارِ یک مربیِ تازه‌کار با چند اسلایدِ ساده.",
                           "hook": "تازه مربی شده‌ای؟ از اینجا شروع کن.", "shoot": "هر اسلاید یک گام.", "cta": "ذخیره کن", "format": "carousel", "channel": "both"}]}
        ok, msg = selftest.node_check(json.dumps(good, ensure_ascii=False))
        self.assertTrue(ok, msg)
        ok, _ = selftest.node_check("```json\n" + json.dumps(good, ensure_ascii=False) + "\n```")
        self.assertTrue(ok)                                                                  # حصارِ ``` را می‌برد
        self.assertFalse(selftest.node_check("نه JSON")[0])
        self.assertFalse(selftest.node_check(json.dumps({"ideas": []}))[0])
        priced = {"ideas": [dict(good["ideas"][0], title="پنجاه درصد تخفیفِ ویژه", logline="یک پیشنهاد با تخفیفِ ساختگی برای همه")]}
        self.assertFalse(selftest.node_check(json.dumps(priced, ensure_ascii=False))[0])
        english = {"ideas": [dict(good["ideas"][0], title="Start the coach plan now", logline="An english sentence for a coach plan", hook="Start")]}
        self.assertFalse(selftest.node_check(json.dumps(english))[0])

    def test_central_acceptance_run_knows_the_ideabank_tests(self):
        from apps.compute import selftests as ST

        reg = ST.load_all(force=True)
        self.assertIn("ideabank_ai", reg)
        self.assertIn("ideabank_seeds", reg)
        ai = reg["ideabank_ai"]
        self.assertEqual((ai.kind, ai.group, ai.optional), ("ollama.generate", "text", True))
        self.assertIn("ollama_text", ai.after)

        class Ctx:
            caps = {"ollama": True, "ollama_models": ["qwen3:8b", "qwq:32b"]}

            def installed_ollama(self):
                return self.caps["ollama_models"]

        spec = ai.build(Ctx())
        self.assertEqual((spec.kind, spec.payload["model"]), ("ollama.generate", "qwen3:8b"))          # مدلِ کوچکِ خودِ مالک، نه qwq:32b
        self.assertEqual(ST.REGISTRY["ideabank_seeds"].virtual(None).ok, True)
        node = type("N", (), {"capabilities": {"ollama": True, "ollama_models": []}, "auto_switch": False})()
        self.assertFalse(ai.available(node)[0])                                                         # بدونِ مدل: «اجرا نشد»، نه «رد»
