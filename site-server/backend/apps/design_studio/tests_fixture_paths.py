# -*- coding: utf-8 -*-
"""آزمونِ «مسیرِ موقتِ بلند»: اجرای شبانه TMPDIR را بلند می‌کرد (/tmp/nm-nightly-…/nm-testrun-…/…) و ارجاعِ عکسِ «file:<مسیر>» از ۸۰ نویسه می‌گذشت؛
scene.py آن را می‌برید، عکس «گم‌شده» حساب می‌شد و سه آزمونِ خروجی (PDF، PPTX، بستهٔ منبع) هر شب قرمز می‌شدند (فقط در اجرای شبانه، نه دستی)."""
import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from . import catalog_doc, exports, fixtures


class LongTempPathTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="nm-deep-"))
        self.deep = self.root / ("nm-testrun-1234567-abcdefgh") / ("a" * 40)
        self.deep.mkdir(parents=True)
        self.saved = tempfile.tempdir
        tempfile.tempdir = str(self.deep)
        self.made: list[Path] = []

    def tearDown(self):
        tempfile.tempdir = self.saved
        for d in self.made:
            shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)

    def refs(self, n=3):
        refs = fixtures.make_images(n, size=(1400, 1000))
        self.made += [Path(r[5:]).parent for r in refs]
        return refs

    def test_refs_fit_the_scene_limit_and_the_files_exist_under_a_long_temp_path(self):
        self.assertGreater(len(str(self.deep)), 60, "the fixture really sits under a long temp path")
        refs = self.refs()
        for r in refs:
            self.assertTrue(r.startswith("file:"))
            self.assertLessEqual(len(r), 80, r)
            self.assertTrue(Path(r[5:]).is_file(), r)

    def test_a_catalog_built_under_a_long_temp_path_still_places_its_images(self):
        refs = self.refs(6)
        items = fixtures.products(refs)
        src, info = fixtures.source(), fixtures.info("فروشگاهِ نمونه")
        cat = catalog_doc.new_doc(info, items, {}, {"featured": [1]}, src)
        bundle = exports.make_bundle("catalog", cat, info, src, "کاتالوگ نمونه", 1)
        _data, rep = exports.print_pdf(bundle)
        self.assertTrue(rep.get("images"), rep.get("missing_images"))
        self.assertFalse(rep.get("missing_images"))

    def test_a_short_temp_path_keeps_the_images_where_they_are(self):
        tempfile.tempdir = self.saved
        refs = self.refs(2)
        self.assertTrue(all(Path(r[5:]).is_file() for r in refs))
