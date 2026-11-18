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
        """هر صفحهٔ دفترِ پنل در راهنما هست: یا بخشِ دست‌نویس دارد یا (اگر لِینِ دیگری تازه افزوده) بخشِ عمومیِ خودکار. این آزمون با افزودنِ صفحه نمی‌شکند."""
        covered = {k for g in guide.all_sections() for k in g["covers"]}
        missing = sorted(self._registry_keys() - covered)
        self.assertEqual(missing, [], f"صفحه‌هایی که در راهنمای آزمون نیستند: {missing}")

    def test_domain_and_egress_pages_have_hand_written_sections(self):
        for key in ("domain_ssl", "egress"):
            sec = guide.section_for_page(key)
            self.assertIsNotNone(sec, key)
            self.assertFalse(sec["key"].startswith("page_") and sec["phase"] == 11, f"«{key}» فقط بخشِ عمومی دارد")
            self.assertGreaterEqual(len(sec["steps"]), 2)

    def test_a_page_added_later_gets_a_generic_section_without_touching_the_guide(self):
        """صفحه‌ای که لِین دیگری به دفترِ پنل اضافه کند و در GUIDE نباشد: بخشِ عمومی می‌گیرد، در فهرستِ «گزارشِ ایراد» و نشانیِ فروشگاه هم هست."""
        from unittest import mock

        fake = ("fake_page", "صفحهٔ آزمایشیِ تازه", "/stores/:id/fake-page", "یک کارِ تازه که هنوز راهنما ندارد", [])
        sections = [(sk, st, staff, d, list(pages)) for sk, st, staff, d, pages in panel_registry.SECTIONS]
        sk, st, staff, d, pages = sections[0]
        sections[0] = (sk, st, staff, d, pages + [fake])
        with mock.patch.object(panel_registry, "SECTIONS", sections):
            self.assertNotIn("fake_page", guide.covered_pages())
            generic = [g for g in guide.generic_sections() if g["covers"] == ["fake_page"]]
            self.assertEqual(len(generic), 1)
            g = generic[0]
            self.assertEqual((g["key"], g["phase"], g["title"]), ("page_fake_page", 11, "صفحهٔ آزمایشیِ تازه"))
            self.assertTrue(g["steps"] and g["expect"])
            self.assertIn("page_fake_page", guide.by_key())
            self.assertEqual(guide.section_for_page("fake_page")["key"], "page_fake_page")
            row = next(x for x in guide.public(34, live=False) if x["key"] == "page_fake_page")
            self.assertEqual(row["url"], "/stores/34/fake-page")
            self.assertIn("صفحهٔ آزمایشیِ تازه", guide.render_markdown("نمونه", 34))
            self.assertNotIn("صفحهٔ آزمایشیِ تازه", guide.render_markdown("نمونه", 34, generic=False))

    def test_guide_only_covers_real_pages_and_keys_are_unique(self):
        reg = self._registry_keys()
        self.assertEqual(sorted(guide.covered_pages() - reg), [])
        keys = [g["key"] for g in guide.all_sections()]
        self.assertEqual(len(keys), len(set(keys)))
        covers = [k for g in guide.all_sections() for k in g["covers"]]
        self.assertEqual(len(covers), len(set(covers)), "یک صفحه در دو بخش")

    def test_each_section_is_complete_and_ordered(self):
        last_phase = -1
        for g in guide.all_sections():
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

    def test_product_tabs_link_uses_the_product_id_not_the_store_id(self):
        """«زبانه‌های صفحهٔ محصول» باید روی یک محصولِ واقعیِ همان فروشگاه باز شود؛ شناسهٔ فروشگاه (که محصولی با آن شناسه ندارد) «پیدا نشد» می‌داد."""
        from apps.products.models import Product

        from .testkit import make_store

        _owner, store, prod = make_store()
        real = Product.objects.create(id=store.pk + 4000, store=store, name="محصولِ اصلی", price=0)         # شناسهٔ محصول عمداً با شناسهٔ فروشگاه فرق دارد
        Product.objects.filter(pk=prod.pk).delete()
        sec = next(x for x in guide.public(store.pk) if x["key"] == "product_tabs")
        self.assertEqual(sec["url"], f"/products/{real.pk}/intelligence")
        self.assertNotEqual(real.pk, store.pk)
        _o2, store2, _p2 = make_store(products=False, name="بدونِ محصول")
        sec2 = next(x for x in guide.public(store2.pk) if x["key"] == "product_tabs")
        self.assertEqual(sec2["url"], kinds.url_for("products", store2.pk))     # محصولی نیست ⇒ فهرستِ محصولاتِ فروشگاه، نه نشانیِ شکسته
        self.assertNotIn("/products/", sec2["url"])

    def test_committed_markdown_matches_the_data(self):
        """سندِ commit‌شده باید با بخش‌های دست‌نویس یکی باشد؛ بخش‌های عمومیِ صفحه‌های تازه در انتهای سند می‌آیند و این آزمون را نمی‌شکنند."""
        path = Path(settings.BASE_DIR).parent / "docs" / "chagher" / "test-guide-fa.md"
        if not path.is_file():
            self.skipTest("docs/chagher/test-guide-fa.md در این نسخه نیست")
        hand = guide.render_markdown("چغر", 34, generic=False).rstrip("\n")
        self.assertTrue(path.read_text(encoding="utf-8").startswith(hand),
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
