"""ابزارِ ممیزیِ سبک‌ها (`manage.py motion_style_audit`): با مرورگرِ ساختگی، بدونِ رندرِ واقعی."""
import io
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.stores.models import Store

from . import catalog, qa_browser, runner, styleaudit
from .tests_custom import fake_measure

User = get_user_model()


class ChagherPlan(SimpleTestCase):
    def test_only_verified_facts_are_in_the_plan(self):
        """هر جمله از docs/chagher/brand-facts-fa.md آمده؛ هیچ قیمت یا آمارِ ساختگی نیست."""
        text = " ".join(str(v) for sc in styleaudit.chagher_scenes() for v in sc.values() if isinstance(v, (str, list)))
        facts = (Path(__file__).resolve().parents[3] / "docs" / "chagher" / "brand-facts-fa.md")
        if not facts.exists():
            self.skipTest("brand-facts-fa.md is not in this tree")
        body = facts.read_text(encoding="utf-8")
        for needle in ("با چغر چغر تر شو", "panel.chagher.ir", "کمتر از یک دقیقه", "۱٬۳۰۰"):
            self.assertIn(needle, body)
        self.assertNotIn("تومان", text)
        self.assertNotIn("٪", text)
        self.assertEqual([sc["type"] for sc in styleaudit.chagher_scenes()], ["title", "list", "stat", "cta"])


class AuditTool(TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="nm-audit-test-"))
        self.owner = User.objects.create_user("audit-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="چغر", description="دستیار هوش مصنوعیِ مربی‌ها.", colors={"primary": "#126F85", "secondary": "#163F75"})

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def _patch(self, low_contrast=False):
        factory = fake_measure(low_contrast=low_contrast)
        return (mock.patch.object(qa_browser, "available", return_value=(True, "")),
                mock.patch.object(qa_browser, "make_measure", side_effect=lambda store, workdir, media_dir, prefix, per_scene=1, **kw: factory(store, workdir, media_dir, prefix)),
                mock.patch.object(runner, "SiteLock", return_value=mock.Mock()))

    def test_rows_files_and_contact_sheets(self):
        p1, p2, p3 = self._patch()
        with p1, p2, p3:
            rows = styleaudit.run(self.store, ["pixel-art", "chalkboard"], ["9:16", "16:9"], self.out, plan="chagher", say=lambda *_: None)
        self.assertEqual([(r["style"], r["aspect"]) for r in rows], [("pixel-art", "9:16"), ("pixel-art", "16:9"), ("chalkboard", "9:16"), ("chalkboard", "16:9")])
        for r in rows:
            self.assertEqual(r["frames"], 4)                                  # one frame per scene of the four-scene plan
            self.assertEqual(r["errors"], 0, r)
            self.assertTrue((self.out / f"{r['style']}__{r['aspect'].replace(':', 'x')}.json").exists())
        made = styleaudit.sheets(self.out, ["pixel-art", "chalkboard"])
        self.assertEqual(made, {"9:16": 1, "16:9": 1})
        self.assertTrue((self.out / "sheet-9x16-01.jpg").exists() and (self.out / "sheet-16x9-01.jpg").exists())
        self.assertIn("pixel-art", (self.out / "findings.txt").read_text(encoding="utf-8"))

    def test_a_style_that_cannot_be_read_is_reported_and_resume_skips_done_work(self):
        p1, p2, p3 = self._patch(low_contrast=True)
        with p1, p2, p3:
            rows = styleaudit.run(self.store, ["pixel-art"], ["9:16"], self.out, plan="store", say=lambda *_: None)
            self.assertGreaterEqual(rows[0]["errors"] + rows[0]["warnings"], 1)            # near-black on dark grey is found by the pixel QA
            again = styleaudit.run(self.store, ["pixel-art"], ["9:16"], self.out, plan="store", resume=True, say=lambda *_: None)
        self.assertEqual(again, [])

    def test_the_render_tool_missing_is_a_clear_error(self):
        with mock.patch.object(qa_browser, "available", return_value=(False, "no chrome")):
            with self.assertRaises(RuntimeError):
                styleaudit.run(self.store, ["pixel-art"], ["9:16"], self.out)

    def test_management_command(self):
        p1, p2, p3 = self._patch()
        buf = io.StringIO()
        with p1, p2, p3:
            call_command("motion_style_audit", store=self.store.pk, styles="pixel-art,glitch-art", aspects="9:16", out=str(self.out), plan="chagher", stdout=buf)
        self.assertIn("برگه‌های تماس", buf.getvalue())
        self.assertTrue((self.out / "glitch-art__9x16.json").exists())

    def test_every_catalog_style_gets_a_spec_in_both_aspects(self):
        for st in catalog.STYLES:
            for asp in ("9:16", "16:9"):
                spec = styleaudit.audit_spec(self.store, st["id"], asp, plan="chagher")
                self.assertEqual((spec["style"], spec["aspect"], len(spec["scenes"])), (st["id"], asp, 4))
