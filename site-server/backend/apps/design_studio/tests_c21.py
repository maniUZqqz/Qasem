# -*- coding: utf-8 -*-
"""قطعه‌های 21st.dev در «استودیوی طراحی»: بلوکِ c21 در طرحِ UI (جای‌نگهدارِ دقیق با عنوان، دسته، متن‌ها و مجوز) و همان بلوک در «ساختِ سایت از طرح».
شبکه و مرورگر در کار نیست."""
import json
import shutil
import tempfile
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from apps.projects.builder import c21_convert as CV, c21st
from apps.projects.tests_c21x import FakeNode

from . import ui_doc, ui_frames as uf


class C21InStudioTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="c21-studio-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._ov = override_settings(NM_DATA_DIR=self.tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        c21st._cache.update(mtime=0.0, rows=[])
        CV._CACHE.clear()
        rec = CV.convert_bundle("acme/price-table", {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [], "source": {}},
                                meta={"title": "Price Table", "license": "mit", "author": "Acme", "library": "Acme UI", "cats": ["pricing-section"]}, runner=FakeNode())
        CV.save_record(rec)
        self.rec = rec
        self.info = SimpleNamespace(name="چغر", has_logo=False)

    def block(self, ref=None):
        return {"t": "block", "type": "c21", "props": {"ref": ref or self.rec["key"], "texts": [{"v": t} for t in self.rec["texts"]], "links": [], "images": []}, "style": {}}

    def test_a_c21_node_can_be_added_and_is_drawn_as_a_labelled_placeholder(self):
        data = ui_doc.new_doc(self.info, template="blank", devices=("desktop", "phone"))
        fid = data["frames"][0]["id"]
        ui_doc.apply_ops(data, [{"op": "add_node", "frame": fid, "node": self.block()}])
        node = data["frames"][0]["children"][-1]
        self.assertEqual((node["t"], node["type"]), ("block", "c21"))
        self.assertEqual(node["props"]["ref"], self.rec["key"])
        sc = uf.build_scene(data, self.info)
        blob = json.dumps(sc, ensure_ascii=False)
        self.assertIn("Price Table", blob)
        self.assertIn("21st.dev", blob)
        self.assertIn("Big title", blob, "متن‌های نمونهٔ قطعه در جای‌نگهدار دیده می‌شود")

    def test_unknown_or_deleted_component_still_draws_something_not_a_crash(self):
        data = ui_doc.new_doc(self.info, template="blank", devices=("desktop",))
        ui_doc.apply_ops(data, [{"op": "add_node", "frame": data["frames"][0]["id"], "node": self.block("x000000000")}])
        sc = uf.build_scene(data, self.info)
        self.assertIn("21st.dev", json.dumps(sc, ensure_ascii=False))

    def test_the_block_survives_into_the_site_plan(self):
        data = ui_doc.new_doc(self.info, template="blank", devices=("desktop",))
        ui_doc.apply_ops(data, [{"op": "add_node", "frame": data["frames"][0]["id"], "node": self.block()}])
        plan = ui_doc.site_plan(data)
        blocks = plan["pages"][0]["blocks"]
        self.assertEqual([b["type"] for b in blocks], ["c21"])
        self.assertEqual(blocks[0]["props"]["ref"], self.rec["key"], "«ساختِ سایت از طرح» همین قطعه را (با ظاهرِ کاملش) در سایت‌ساز می‌گذارد")
