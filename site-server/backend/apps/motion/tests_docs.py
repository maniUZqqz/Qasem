"""اسناد و قراردادها: README ِ فارسی همهٔ سبک‌ها را دارد، بلوکِ آزمونِ خودکارِ گره درست است و با کدِ کارِ واقعی می‌خواند."""
import json
import re
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from . import catalog, runner, selftest, specs

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "docs" / "motion" / "README-fa.md"
SELFTEST_DOC = ROOT / "docs" / "selftests" / "motion.md"


class ReadmeFa(SimpleTestCase):
    def setUp(self):
        if not README.is_file():
            self.skipTest("docs/motion/README-fa.md is not in this tree")
        self.text = README.read_text(encoding="utf-8")

    def test_every_style_is_in_the_table(self):
        missing = [s["id"] for s in catalog.STYLES if f"`{s['id']}`" not in self.text]
        self.assertEqual(missing, [], "run: python motion/tools/gen_style_table.py --update docs/motion/README-fa.md")

    def test_the_explanation_covers_what_the_owner_asked(self):
        for topic in ("کلیدفریم", "منحنی‌های شتاب", "۱۲ اصلِ انیمیشن", "لایه‌ها", "ماسک", "تایپوگرافی", "ریتم", "گذارها", "دوربینِ مجازی",
                      "سامانهٔ سبک", "useCurrentFrame", "interpolate", "spring", "Sequence", "پیکسل‌به‌پیکسل"):
            self.assertIn(topic, self.text, topic)

    def test_the_twelve_principles_are_listed(self):
        rows = re.findall(r"^\| (?:۱|۲|۳|۴|۵|۶|۷|۸|۹|۱۰|۱۱|۱۲) \| \*\*", self.text, re.M)
        self.assertEqual(len(rows), 12)

    def test_licences_are_recorded(self):
        for word in ("Remotion", "SIL Open Font License", "Chrome headless shell", "MIT"):
            self.assertIn(word, self.text)


class SelftestBlock(SimpleTestCase):
    def blocks(self):
        if not SELFTEST_DOC.is_file():
            self.skipTest("docs/selftests/motion.md is not in this tree")
        return [json.loads(raw) for raw in re.findall(r"```json\s*\n(.*?)\n```", SELFTEST_DOC.read_text(encoding="utf-8"), re.S)]

    def test_block_is_valid_for_the_node_self_test_loader(self):
        blocks = self.blocks()
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual((b["key"], b["kind"]), ("motion_studio", "motion.render"))
        self.assertTrue(b["gpu_required"])
        self.assertIn("motion_render", b["requires"]["caps"])
        self.assertEqual(b["check"]["forbid_device"], ["cpu"])
        self.assertIn("device", b["check"]["json_has"])

    def test_payload_is_a_valid_spec_and_matches_the_python_selftest(self):
        b = self.blocks()[0]
        spec = specs.normalize_spec(b["payload"]["props"]["spec"])
        self.assertEqual(spec["scenes"][0]["type"], "title")
        self.assertEqual(round(spec["total_s"]), 3)
        self.assertEqual(b["payload"]["props"]["spec"]["scenes"], selftest.SPEC["scenes"])
        for k in ("scale", "crf", "max_seconds"):
            self.assertEqual(b["payload"][k], selftest.PAYLOAD[k])

    def test_payload_passes_the_node_validator(self):
        import sys

        proc = str(ROOT / "processing")
        if not (Path(proc) / "motion_jobs.py").is_file():
            self.skipTest("processing/motion_jobs.py is not in this tree")
        sys.path.insert(0, proc)
        try:
            import motion_jobs
        finally:
            sys.path.remove(proc)
        clean = motion_jobs.validate_payload(self.blocks()[0]["payload"])
        self.assertEqual(clean["composition"], "Template")
        self.assertEqual(clean["scale"], 0.5)


class BrowserLookup(SimpleTestCase):
    def test_the_browser_downloaded_by_motion_build_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "motion" / "browser" / "linux64" / "chrome-headless-shell-linux64" / "chrome-headless-shell"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"#!/bin/sh\n")
            with override_settings(NM_DATA_DIR=tmp, NM_MOTION_BROWSER=""):
                self.assertEqual(runner.browser_path(), str(exe))
