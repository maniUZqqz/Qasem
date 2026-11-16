# -*- coding: utf-8 -*-
"""جدا شدنِ «ریموتِ کامپیوتر» از NMarketing (۱۴۰۵/۰۸/۲۶).

دسترسیِ راه‌دور به کلِ کامپیوتر ابزارِ جداست و مخزنِ خودش را دارد (اشاره‌گرش در README ِ پوشهٔ پردازش است). فایلِ راه‌اندازیِ آن
یک کلیدِ دعوتِ خصوصی در خودش دارد، پس نباید در هیچ مخزنِ عمومی (از جمله آینهٔ Qasem که git-autopush از روی همین پوشه
می‌سازد) یا در بستهٔ به‌روزرسانیِ گره بیاید. این آزمون‌ها نگه می‌دارند که چیزی از آن به NM برنگردد:

* هیچ فایلی در درختِ کد (و در بستهٔ گره) نامِ آن ابزار را ندارد؛
* هیچ متنی در کد/مستندات/پنل از آن نام نمی‌برد، جز یک اشاره‌گر به مخزنِ جدا در README ِ پوشهٔ پردازش؛
* ابزارِ «دستورها» ِ خودِ NM (status/update/restart/build/logs/bootstrap) سر جایش است.

نام‌های جست‌وجو را با «+» می‌سازیم تا خودِ این فایل هم جزو ردیف‌ها نیاید.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.test import SimpleTestCase

from . import commands, updates

ROOT = Path(__file__).resolve().parents[3]          # <ریشهٔ پروژه> = /var/www/NM/upmarket
NEEDLES = ("pc" + "-remote", "pc" + "_remote", "pc" + " remote", "pc" + "remote", "remote" + "-d")
NAME_NEEDLES = ("pc" + "-remote", "pc" + "_remote", "pc" + "remote")
POINTER_FILE = "processing/README-FA.md"
POINTER_URL = "https://github.com/maniUZqqz/" + "Remote" + "-d"
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".next", "media", "staticfiles", "vendor", "logs", "data",
             "models", "server-state", "bin", "obj"}
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".json", ".md", ".bat", ".cmd", ".ps1", ".sh", ".txt", ".html", ".css",
            ".service", ".timer", ".conf", ".cfg", ".toml", ".yml", ".yaml", ".env", ".cron", ".ini"}
MAX_BYTES = 2_000_000


def _walk():
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith("dist")]
        for f in files:
            if ".bak" in f or f.endswith((".pyc", ".pyo")):
                continue
            yield Path(d) / f


class RemoteToolIsNotPartOfNMTests(SimpleTestCase):
    def test_no_file_in_the_tree_is_named_after_it(self):
        bad = [str(p.relative_to(ROOT)) for p in _walk() if any(n in p.name.lower() for n in NAME_NEEDLES)]
        self.assertEqual(bad, [], "the separate remote-access tool has its own repository")

    def test_no_code_doc_or_panel_text_mentions_it_except_the_pointer(self):
        me = Path(__file__).resolve()
        hits = []
        for p in _walk():
            if p.resolve() == me or p.suffix.lower() not in TEXT_EXT:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            low = text.lower()
            if not any(n in low for n in NEEDLES):
                continue
            rel = str(p.relative_to(ROOT)).replace(os.sep, "/")
            for no, line in enumerate(text.splitlines(), 1):
                ll = line.lower()
                if any(n in ll for n in NEEDLES) and not (rel == POINTER_FILE and POINTER_URL.lower() in ll):
                    hits.append("%s:%d" % (rel, no))
        self.assertEqual(hits, [])

    def test_the_pointer_to_the_separate_repository_is_there_and_is_the_only_mention(self):
        text = (ROOT / POINTER_FILE).read_text(encoding="utf-8")
        self.assertEqual(text.count(POINTER_URL), 1)

    def test_the_node_update_package_does_not_list_any_such_file(self):
        rels = [rel for rel, _p in updates.source_files(ROOT / "processing")]
        self.assertIn("agent.py", rels)
        self.assertIn("START.bat", rels)
        self.assertIn("Update.bat", rels)
        self.assertEqual([r for r in rels if any(n in r.lower() for n in NAME_NEEDLES)], [])

    def test_the_public_mirror_script_has_no_special_case_for_it(self):
        text = (ROOT / "deploy" / "nm" / "git-autopush.sh").read_text(encoding="utf-8").lower()
        self.assertFalse(any(n in text for n in NEEDLES))
        # processing/ is mirrored as a whole: what is not in the live folder is not in the mirror either
        self.assertIn('rsync -a --delete', text)

    def test_nms_own_node_commands_are_untouched(self):
        self.assertEqual(tuple(commands.ACTIONS), ("status", "update", "restart", "build", "logs", "bootstrap"))
