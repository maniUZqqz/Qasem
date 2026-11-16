"""pron_jobs.py (the pronunciation check on the node) without Piper, without Whisper, without a GPU:
the two workers are replaced by fakes, the agent by a tiny stand-in.

    python tests/test_pron_jobs.py
"""
import json
import os
import py_compile
import shutil
import sys
import tempfile
import unittest

PROC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROC)

import pron_jobs as PJ  # noqa: E402


class JobError(RuntimeError):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class Cancelled(Exception):
    pass


class FakeJob:
    def __init__(self, payload, root):
        self.payload = payload
        self.dir = root
        self.timeout_s = 600
        self.cancelled = False
        self.said = []
        os.makedirs(os.path.join(root, "outputs"), exist_ok=True)
        os.makedirs(os.path.join(root, "inputs"), exist_ok=True)

    def out(self, name):
        return os.path.join(self.dir, "outputs", os.path.basename(name))

    def input_path(self, name):
        p = os.path.join(self.dir, "inputs", os.path.basename(name))
        return p if os.path.isfile(p) else None

    def progress(self, frac, msg=""):
        self.said.append((frac, msg))


class FakeAgent:
    JobError = JobError
    Cancelled = Cancelled
    HANDLERS = {}
    DATA = ""


class PronJobs(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nm-pron-")
        self.agent = FakeAgent()
        self.agent.DATA = self.root
        self.agent.HANDLERS = {}
        self.job_dir = os.path.join(self.root, "job")
        self._saved = (PJ._synth_piper, PJ._synth_moss, PJ._listen)

    def tearDown(self):
        PJ._synth_piper, PJ._synth_moss, PJ._listen = self._saved
        shutil.rmtree(self.root, ignore_errors=True)

    def items(self):
        return [{"id": 3, "variant": "before", "text": "سلام"}, {"id": 3, "variant": "after", "ipa": ["salˈɑm"]}]

    def fake_pipeline(self):
        def synth(job, agent, p, items, wavs):
            for it in items:
                with open(os.path.join(wavs, "%s_%s.wav" % (it["id"], it["variant"])), "wb") as fh:
                    fh.write(b"RIFF")
            return {"voice": "fa_IR-amir-medium", "load_s": 1.0,
                    "items": [{"id": it["id"], "variant": it["variant"], "file": "%s_%s.wav" % (it["id"], it["variant"]), "took": 0.3}
                              for it in items]}

        def listen(job, agent, wavs, out_json):
            names = sorted(os.listdir(wavs))
            return {"model": "faster-whisper-small", "device": "cuda", "compute_type": "float16", "fallback_reason": "", "seconds": 2.0,
                    "results": {n: {"text": "سلام" if n.endswith("after.wav") else "سلم", "duration": 1.2} for n in names}}

        PJ._synth_piper = synth
        PJ._synth_moss = synth
        PJ._listen = listen

    def test_install_registers_both_kinds(self):
        PJ.install(self.agent)
        self.assertEqual(sorted(self.agent.HANDLERS), ["voice.pron_asr", "voice.pron_eval"])

    def test_eval_writes_result_json(self):
        self.fake_pipeline()
        job = FakeJob({"engine": "piper", "voice": "fa_IR-amir-medium", "items": self.items()}, self.job_dir)
        meta = PJ.run_eval(job, self.agent)
        self.assertEqual(meta["primary"], "result.json")
        self.assertEqual(meta["device"], "cuda")
        with open(job.out("result.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual({(i["id"], i["variant"]): i["hyp"] for i in data["items"]}, {(3, "before"): "سلم", (3, "after"): "سلام"})
        self.assertEqual(data["asr"]["model"], "faster-whisper-small")
        self.assertEqual(data["engine"], "piper")

    def test_moss_engine_is_accepted_other_engines_are_not(self):
        self.fake_pipeline()
        ok = FakeJob({"engine": "moss", "voice": "arash", "items": [{"id": 1, "variant": "before", "text": "x"}]}, self.job_dir)
        self.assertEqual(PJ.run_eval(ok, self.agent)["engine"], "pron:moss")
        bad = FakeJob({"engine": "edge", "items": self.items()}, os.path.join(self.root, "j2"))
        with self.assertRaises(JobError) as cm:
            PJ.run_eval(bad, self.agent)
        self.assertFalse(cm.exception.retryable)

    def test_item_limits(self):
        self.fake_pipeline()
        too_many = [{"id": i, "variant": "before", "text": "x"} for i in range(PJ.MAX_ITEMS + 1)]
        for n, items in enumerate(([], too_many, [{"id": 1, "variant": "other"}])):
            job = FakeJob({"engine": "piper", "items": items}, os.path.join(self.root, "j%d" % n))
            with self.assertRaises(JobError):
                PJ.run_eval(job, self.agent)

    def test_asr_job_copies_inputs_and_listens(self):
        self.fake_pipeline()
        job = FakeJob({"engine": "edge", "voice": "fa-IR-DilaraNeural",
                       "files": [{"id": 5, "variant": "after", "name": "5_after.mp3"}]}, self.job_dir)
        with open(os.path.join(job.dir, "inputs", "5_after.mp3"), "wb") as fh:
            fh.write(b"ID3")
        meta = PJ.run_asr(job, self.agent)
        self.assertEqual(meta["items"], 1)
        with open(job.out("result.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["items"][0]["id"], 5)
        self.assertEqual(data["engine"], "edge")

    def test_asr_job_missing_input_is_not_retried(self):
        self.fake_pipeline()
        job = FakeJob({"files": [{"id": 5, "variant": "after", "name": "nope.mp3"}]}, self.job_dir)
        with self.assertRaises(JobError) as cm:
            PJ.run_asr(job, self.agent)
        self.assertFalse(cm.exception.retryable)

    def test_not_installed_says_downloading(self):
        # the real _synth_piper with no venv / voice yet: the message the site understands (DOWNLOADING: ...)
        job = FakeJob({"engine": "piper", "items": self.items()}, self.job_dir)
        with self.assertRaises(JobError) as cm:
            self._saved[0](job, self.agent, job.payload, self.items(), os.path.join(self.root, "w"))
        self.assertTrue(str(cm.exception).startswith("DOWNLOADING:"))

    def test_piper_voice_path_defaults_to_amir(self):
        self.assertTrue(PJ.piper_voice_path(self.agent, "").endswith("fa_IR-amir-medium.onnx"))
        self.assertTrue(PJ.piper_voice_path(self.agent, "fa_IR-gyro-medium").endswith("fa_IR-gyro-medium.onnx"))
        self.assertTrue(PJ.piper_voice_path(self.agent, "../../evil").endswith("fa_IR-amir-medium.onnx"))


class Files(unittest.TestCase):
    def test_workers_compile(self):
        for name in ("pron_jobs.py", "pron_synth_worker.py", "pron_asr_worker.py"):
            py_compile.compile(os.path.join(PROC, name), doraise=True, cfile=os.path.join(tempfile.gettempdir(), name + "c"))

    def test_requirements_file(self):
        with open(os.path.join(PROC, "requirements.d", "pron.json"), encoding="utf-8") as fh:
            spec = json.load(fh)
        self.assertEqual(spec["feature"], "pron")
        self.assertEqual(sorted(spec["kinds"]), ["voice.pron_asr", "voice.pron_eval"])
        self.assertIn("asr-gpu", spec["requires"])
        self.assertEqual([i["id"] for i in spec["items"]], ["venv", "pip", "voices", "verify"])
        pip = next(i for i in spec["items"] if i["id"] == "pip")
        self.assertTrue(all("==" in p for p in pip["packages"]))               # pinned
        files = next(i for i in spec["items"] if i["id"] == "voices")["files"]
        for f in files:
            self.assertEqual(len(f["sha256"]), 64)
            self.assertGreater(f["size"], 1000)
            self.assertTrue(f["sources"][0]["hf"].startswith("rhasspy/piper-voices/"))
        self.assertEqual({f["path"] for f in files if f["path"].endswith(".onnx")}, {v + ".onnx" for v in PJ.VOICES})

    def test_synth_worker_keeps_native_markers(self):
        import pron_synth_worker as W

        self.assertEqual(W.NATIVE.sub(lambda m: "<%s>" % m.group(1), "ab{{گربه}}cd"), "ab<گربه>cd")


if __name__ == "__main__":
    unittest.main()
