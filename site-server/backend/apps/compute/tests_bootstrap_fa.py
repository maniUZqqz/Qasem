# -*- coding: utf-8 -*-
"""Persian text of the node's install report in the panel (bootstrap_fa.py)."""
import json

from django.test import TestCase
from django.utils import timezone

from . import bootstrap_fa as fa
from . import updates as U
from .models import ComputeNode
from .views_platform import node_block


class BootstrapFaTests(TestCase):
    def test_every_shipped_step_title_has_a_persian_text(self):
        """A feature added tomorrow with an English title fails here, not in front of the owner."""
        for path in sorted((U.source_dir() / "requirements.d").glob("*.json")):
            spec = json.loads(path.read_text(encoding="utf-8"))
            for item in spec["items"]:
                if item.get("title"):
                    self.assertIn(item["title"], fa.TITLES, "%s/%s: add a Persian title to bootstrap_fa.TITLES" % (path.name, item["id"]))
                else:
                    self.assertIn(item["type"], fa.TYPE_TITLES, "%s/%s has no title and its type has no generic Persian title" % (path.name, item["id"]))

    def test_the_status_sentences_the_node_writes_come_out_persian(self):
        cases = {
            "installing ...": "در حال نصب …",
            "waiting for the download window": "منتظرِ بازهٔ دانلودِ شبانه",
            "waiting for: gpu-runtime": "منتظرِ نصبِ پیش‌نیاز: gpu-runtime",
            "waiting for the previous step": "منتظرِ گامِ پیش از خود",
            "failed (try 12)": "ناموفق (تلاشِ ۱۲)",
            "creating the Python environment asr": "ساختنِ محیطِ پایتونِ asr",
            "pip install from pypi.org": "نصبِ بسته‌ها از pypi.org",
            "downloading model.bin (1/4)": "دانلودِ model.bin (1/4)",
            "unpacking": "بازکردنِ فایل‌ها",
        }
        for english, persian in cases.items():
            self.assertIn(persian, fa.fa_detail(english), english)
        path = r"C:\Users\QQz\NMarketing-data\vendor\node\node.exe"
        self.assertEqual(fa.fa_detail(path), path)
        self.assertEqual(fa.fa_detail(None), "")

    def test_translate_copies_and_keeps_what_it_does_not_know(self):
        boot = {"summary": {"installing": 1}, "blocked_kinds": {"asr.transcribe": "asr-gpu: installing"}, "features": {
            "asr-gpu": {"title": "تشخیص گفتار", "state": "installing", "why": "", "items": [
                {"id": "venv", "type": "venv", "title": "Python environment asr", "state": "ready", "detail": "D:/data/venvs/asr/python.exe", "error": "", "tail": []},
                {"id": "pip", "type": "pip", "title": "pip", "state": "installing", "detail": "installing ...", "error": "", "tail": []}]},
            "other": {"title": "x", "state": "skipped", "why": "no NVIDIA GPU on this computer", "items": [{"id": "z", "type": "cmd", "title": "z", "state": "skipped", "detail": ""}]}}}
        out = fa.translate(boot)
        items = out["features"]["asr-gpu"]["items"]
        self.assertEqual(items[0]["title"], "محیطِ پایتونِ تشخیصِ گفتار")
        self.assertEqual(items[0]["detail"], "D:/data/venvs/asr/python.exe")
        self.assertEqual((items[1]["title"], items[1]["detail"]), ("نصبِ بسته‌های پایتون", "در حال نصب …"))   # its title was just its id
        self.assertEqual(out["features"]["other"]["why"], "کارتِ NVIDIA در این رایانه نیست")
        self.assertEqual(boot["features"]["asr-gpu"]["items"][1]["detail"], "installing ...", "the node's own report is never edited")
        self.assertEqual(out["blocked_kinds"], boot["blocked_kinds"])
        self.assertEqual(fa.translate({}), {})
        self.assertIsNone(fa.translate(None))

    def test_a_step_whose_title_is_just_its_id_gets_the_generic_persian_title(self):
        boot = {"features": {"f": {"items": [{"id": "pip", "type": "pip", "title": "pip", "detail": ""}, {"id": "x", "type": "venv", "title": "A custom title", "detail": ""}]}}}
        items = fa.translate(boot)["features"]["f"]["items"]
        self.assertEqual(items[0]["title"], "نصبِ بسته‌های پایتون")
        self.assertEqual(items[1]["title"], "A custom title")                                         # not just the id: it stays as the feature wrote it

    def test_the_panel_block_of_a_node_carries_the_persian_text(self):
        node = ComputeNode.objects.create(name="fa-node", last_seen=timezone.now(), capabilities={"agent": "2.11", "bootstrap": {
            "summary": {"installing": 1}, "blocked_kinds": {}, "features": {"f": {"title": "t", "state": "installing", "items": [
                {"id": "node", "type": "archive", "title": "Node.js 20.18.0 (win-x64)", "state": "installing", "detail": "unpacking"}]}}}})
        item = node_block(node)["bootstrap"]["features"]["f"]["items"][0]
        self.assertEqual((item["title"], item["detail"]), ("Node.js 20.18.0 (ویندوز)", "بازکردنِ فایل‌ها"))
