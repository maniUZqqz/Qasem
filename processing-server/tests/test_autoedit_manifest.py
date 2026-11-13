"""The automatic video edit asks nothing of the node's owner (agent 2.11 platform).

What its background step needs on the GPU computer is declared in ONE requirement file, `requirements.d/autoedit.json`: the Robust Video Matting
model in the folder `edit_rvm.py` reads, after the shared `gpu-runtime` feature made the Python environment (numpy, Pillow, OpenCV,
onnxruntime-directml).  Everything else the edit uses (asr.transcribe, edit.track, edit.matte, edit.render) is declared by the features that own
those kinds.  No installer of its own, no second download manifest that would race `gpu-runtime` on the same environment.

    python -m unittest tests/test_autoedit_manifest.py        (from the processing folder; Windows and Linux)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
import bootstrap as bs  # noqa: E402
import edit_rvm  # noqa: E402


def spec(feature):
    specs, errors = bs.load_specs(os.path.join(PROC, "requirements.d"))
    assert errors == [], errors
    return next(s for s in specs if s["feature"] == feature)


def matting_manifest_item(item_id):
    with open(os.path.join(PROC, "downloads", "matting.json"), encoding="utf-8") as fh:
        return next(i for i in json.load(fh)["items"] if i["id"] == item_id)


class AutoEditRequirementTests(unittest.TestCase):
    def test_it_is_a_valid_requirement_file_the_bootstrap_loads(self):
        s = spec("autoedit")
        self.assertTrue(s["title_fa"])
        for it in s["items"]:
            self.assertIn(it["type"], bs.ITEM_TYPES)

    def test_it_waits_for_the_shared_runtime_and_blocks_no_job_kind(self):
        s = spec("autoedit")
        self.assertEqual(s["requires"], ["gpu-runtime"])
        self.assertIn("gpu-runtime", {x["feature"] for x in bs.load_specs(os.path.join(PROC, "requirements.d"))[0]})
        self.assertEqual(s["kinds"], [], "a missing model must never make the editor's other jobs wait")

    def test_the_model_lands_where_the_matting_code_reads_it_with_the_same_bytes_as_the_old_package(self):
        item = next(i for i in spec("autoedit")["items"] if i["id"] == "rvm")
        f = item["files"][0]
        self.assertEqual(os.path.join(*item["dest"].split("/"), f["path"]), os.path.relpath(edit_rvm.model_file("."), "."),
                         "the folder edit_rvm.py looks in")
        old = matting_manifest_item("matting:rvm-mobilenetv3-fp32")
        self.assertEqual((f["sha256"], f["size"]), (old["sha256"], old["size"]))
        self.assertIn("site", f["sources"][0], "the site's own mirror first (GitHub is slow from Iran)")
        self.assertTrue(any("github.com/PeterL1n" in x.get("url", "") for x in f["sources"]))

    def test_the_old_second_installer_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(PROC, "downloads", "autoedit.json")),
                         "the python packages come from requirements.d/gpu-runtime.json only")

    def test_a_node_without_the_model_installs_it_by_itself_and_skips_it_when_present(self):
        s = spec("autoedit")
        item = next(i for i in s["items"] if i["id"] == "rvm")
        tmp = tempfile.mkdtemp(prefix="nm-autoedit-req-")
        self.addCleanup(shutil.rmtree, tmp, True)

        class Ctx:
            data = tmp
            say = staticmethod(lambda *a, **k: None)
            fetched = []

            def path(self, *parts):
                return os.path.join(tmp, *parts)

            def download_allowed(self):
                return True

            def fetch(self, url, dest, size=None, sha256=None, label=None):
                self.fetched.append(url)
                with open(dest, "wb") as fh:
                    fh.write(b"x" * int(size))

            site = "https://example.invalid"

        ctx = Ctx()
        check, install = bs.ITEM_TYPES["files"]
        self.assertFalse(check(ctx, item)[0])
        install(ctx, item)
        self.assertTrue(check(ctx, item)[0])
        self.assertEqual(len(ctx.fetched), 1)
        install(ctx, item)
        self.assertEqual(len(ctx.fetched), 1, "idempotent: nothing is fetched twice")


if __name__ == "__main__":
    unittest.main()
