"""راهنمای آزمون: هر صفحهٔ پنل پوشش دارد، سند با داده یکی است، و آزمونِ خودکارِ سرورِ پردازش ثبت شده است."""
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from apps.panel import registry as panel_registry

from . import guide, kinds
from .models import MarketingPlan


class GuideCoverageTests(TestCase):
    def _registry_keys(self):
        return {p[0] for _sk, _t, _s, _d, pages in panel_registry.SECTIONS for p in pages}

    def test_every_panel_page_is_covered_by_some_guide_section(self):
        missing = sorted(self._registry_keys() - guide.covered_pages())
        self.assertEqual(missing, [], f"صفحه‌هایی که در راهنمای آزمون نیستند: {missing}")

    def test_guide_only_covers_real_pages_and_keys_are_unique(self):
        reg = self._registry_keys()
        self.assertEqual(sorted(guide.covered_pages() - reg), [])
        keys = [g["key"] for g in guide.GUIDE]
        self.assertEqual(len(keys), len(set(keys)))
        covers = [k for g in guide.GUIDE for k in g["covers"]]
        self.assertEqual(len(covers), len(set(covers)), "یک صفحه در دو بخش")

    def test_each_section_is_complete_and_ordered(self):
        last_phase = -1
        for g in guide.GUIDE:
            self.assertTrue(g["steps"] and g["expect"], g["key"])
            self.assertGreaterEqual(g["phase"], last_phase, "ترتیبِ مرحله‌ها")
            last_phase = g["phase"]
            for k in g["kinds"]:
                self.assertIn(k, kinds.KINDS, (g["key"], k))
            self.assertGreater(g["minutes"], 0)

    def test_every_node_dependent_plan_kind_is_explained_somewhere(self):
        explained = {k for g in guide.GUIDE if g["node"] for k in g["kinds"]}
        for kind, (_label, _section, node, _group) in kinds.KINDS.items():
            if node:
                self.assertIn(kind, explained, f"«{kind}» به سرورِ پردازش نیاز دارد ولی در هیچ بخشِ راهنما «منتظرِ سرور» توضیح داده نشده")

    def test_urls_resolve_for_a_store(self):
        for s in guide.public(34):
            self.assertTrue(s["url"], s["key"])
            self.assertNotIn(":id", s["url"])

    def test_committed_markdown_matches_the_data(self):
        path = Path(settings.BASE_DIR).parent / "docs" / "chagher" / "test-guide-fa.md"
        if not path.is_file():
            self.skipTest("docs/chagher/test-guide-fa.md در این نسخه نیست")
        self.assertEqual(path.read_text(encoding="utf-8"), guide.render_markdown("چغر", 34),
                         "سند قدیمی است: manage.py mktplan_guide_md --out ../docs/chagher/test-guide-fa.md --store 34")


class SelfTestRegistrationTests(TestCase):
    def test_virtual_selftest_is_registered_and_passes_with_no_plans(self):
        from apps.compute.selftests import Ctx, REGISTRY, load_all

        load_all(force=True)
        t = REGISTRY["mktplan"]
        self.assertIsNotNone(t.virtual)
        self.assertTrue(t.virtual(Ctx(None, None)).ok)

    def test_virtual_selftest_reports_waiting_then_fails_after_the_window(self):
        import datetime as dt

        from django.utils import timezone

        from apps.compute.selftests import Ctx, REGISTRY, load_all

        from . import planner
        from .models import PlanItem
        from .testkit import make_store

        load_all(force=True)
        _owner, store, _p = make_store()
        plan, _ = planner.ensure_plan(store, _owner)
        item = plan.items.get(key="d03.motion.reel1")
        plan.items.exclude(pk=item.pk).update(decision="skipped")        # تیک فقط همین یک کار را ببیند
        PlanItem.objects.filter(pk=item.pk).update(status=PlanItem.Status.WAITING_NODE, meta={"waiting_node": "گره خاموش"})
        t = REGISTRY["mktplan"]

        class R:
            started_at = timezone.now()

        v = t.virtual(Ctx(None, None, result=R()))
        self.assertTrue(v.wait and not v.ok, v.detail)
        R.started_at = timezone.now() - dt.timedelta(hours=2)
        v = t.virtual(Ctx(None, None, result=R()))
        self.assertFalse(v.ok or v.wait, v.detail)
        self.assertIn("منتظر", v.detail)
        MarketingPlan.objects.all().delete()
