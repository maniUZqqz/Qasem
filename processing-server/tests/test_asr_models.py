"""The node picks the best Whisper model it really has (agent 2.19) - Persian cuts and subtitles need better ears than `small`.

    python -m unittest tests/test_asr_models.py        (from the processing folder; Windows and Linux)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.dirname(HERE)
sys.path.insert(0, PROC)
import asr_jobs  # noqa: E402
import bootstrap as bs  # noqa: E402


def spec(feature):
    specs, errors = bs.load_specs(os.path.join(PROC, "requirements.d"))
    assert errors == [], errors
    return next(s for s in specs if s["feature"] == feature)


REAL_MIN_BYTES = dict(asr_jobs.MIN_MODEL_BYTES)
TINY_MIN_BYTES = {"large-v3-turbo": 2000, "small": 1000}           # the tests use kilobytes, not gigabytes


def put_model(data, name, big=True, support=True):
    d = asr_jobs.model_dir(data, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "model.bin"), "wb") as fh:
        fh.write(b"x" * (TINY_MIN_BYTES[name] + (1 if big else -TINY_MIN_BYTES[name] // 2)))
    if support:
        for f in asr_jobs.SUPPORT_FILES:
            with open(os.path.join(d, f), "w") as fh:
                fh.write("{}")


class PickModelTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="nm-asr-models-")
        self.addCleanup(shutil.rmtree, self.data, True)
        patcher = mock.patch.dict(asr_jobs.MIN_MODEL_BYTES, TINY_MIN_BYTES)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_installed_nothing_listed(self):
        self.assertEqual(asr_jobs.installed_models(self.data), [])
        self.assertEqual(asr_jobs.pick_model(self.data, "auto"), (None, ""))

    def test_the_big_model_is_preferred_when_it_is_really_there(self):
        put_model(self.data, "small")
        put_model(self.data, "large-v3-turbo")
        self.assertEqual(asr_jobs.installed_models(self.data), ["large-v3-turbo", "small"])
        for asked in ("auto", "", "best", None, "AUTO"):
            self.assertEqual(asr_jobs.pick_model(self.data, asked), ("large-v3-turbo", ""), asked)

    def test_only_small_installed_auto_and_the_old_name_both_get_small(self):
        put_model(self.data, "small")
        self.assertEqual(asr_jobs.installed_models(self.data), ["small"])
        self.assertEqual(asr_jobs.pick_model(self.data, "auto"), ("small", ""))
        self.assertEqual(asr_jobs.pick_model(self.data, "small"), ("small", ""))

    def test_asking_for_the_big_model_before_it_is_downloaded_is_answered_by_small_with_a_note(self):
        put_model(self.data, "small")
        name, note = asr_jobs.pick_model(self.data, "large-v3-turbo")
        self.assertEqual(name, "small")
        self.assertIn("large-v3-turbo", note)
        self.assertIn("small", note)

    def test_a_download_in_progress_is_not_a_model(self):
        put_model(self.data, "small")
        put_model(self.data, "large-v3-turbo", big=False)               # model.bin is half there
        self.assertEqual(asr_jobs.installed_models(self.data), ["small"])
        shutil.rmtree(asr_jobs.model_dir(self.data, "small"))
        put_model(self.data, "small", support=False)                     # weights without the tokenizer
        self.assertEqual(asr_jobs.installed_models(self.data), [])

    def test_the_worker_command_carries_the_cpu_fallback_only_when_it_is_a_different_model(self):
        big, small = "/m/large", "/m/small"
        cmd = asr_jobs.worker_command("py", "a.wav", big, "o.json", "fa", True, True, cpu_model_dir=small)
        self.assertEqual(cmd[cmd.index("--cpu-model-dir") + 1], small)
        self.assertNotIn("--cpu-model-dir", asr_jobs.worker_command("py", "a.wav", small, "o.json", "fa", True, True, cpu_model_dir=small))
        self.assertNotIn("--cpu-model-dir", asr_jobs.worker_command("py", "a.wav", small, "o.json", "fa", True, True))


class FakeAgent:
    class JobError(Exception):
        def __init__(self, message, retryable=True):
            super().__init__(message)
            self.retryable = retryable

    class Cancelled(Exception):
        pass

    DATA = ""
    HANDLERS = {}


class FakeJob:
    def __init__(self, payload):
        self.payload = payload
        self.timeout_s = 60
        self.cancelled = False

    def input_path(self, name):
        return "/nonexistent/%s" % name

    def out(self, name):
        return "/nonexistent/out/%s" % name

    def progress(self, *a):
        pass


class RunGuardTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="nm-asr-run-")
        self.addCleanup(shutil.rmtree, self.data, True)
        self.agent = FakeAgent()
        self.agent.DATA = self.data

    def test_an_unknown_model_name_is_refused_for_good(self):
        with self.assertRaises(FakeAgent.JobError) as caught:
            asr_jobs.run(FakeJob({"audio": "a.wav", "model": "medium-xl"}), self.agent)
        self.assertFalse(caught.exception.retryable)

    def test_auto_with_nothing_installed_waits_for_the_install_instead_of_failing_the_user(self):
        with self.assertRaises(FakeAgent.JobError) as caught:
            asr_jobs.run(FakeJob({"audio": "a.wav", "model": "auto"}), self.agent)
        self.assertTrue(str(caught.exception).startswith("DOWNLOADING:"))


class ManifestTests(unittest.TestCase):
    def test_the_big_model_is_a_valid_requirement_that_never_blocks_a_job(self):
        s = spec("asr-large")
        self.assertEqual(s["requires"], ["asr-gpu"])
        self.assertEqual(s["kinds"], [], "the small model answers until the big one is on the disk")
        self.assertTrue(s["title_fa"])
        item = s["items"][0]
        self.assertEqual(item["type"], "files")
        self.assertEqual(item["dest"], "models/faster-whisper-large-v3-turbo")
        names = {f["path"] for f in item["files"]}
        self.assertTrue({"model.bin", "config.json", "tokenizer.json", "preprocessor_config.json", "vocabulary.json"} <= names)
        weights = next(f for f in item["files"] if f["path"] == "model.bin")
        self.assertRegex(weights["sha256"], r"^[0-9a-f]{64}$")
        self.assertGreater(weights["size"], REAL_MIN_BYTES["large-v3-turbo"], "the size check of the job is below the real size")
        for f in item["files"]:
            self.assertTrue(all("hf" in src for src in f["sources"]), f["path"])
            self.assertIn("4df90f75321148c3a29a9e2351b7ddf8f5b115a8", f["sources"][0]["hf"], "pinned revision, not 'main'")

    def test_the_folder_name_matches_what_the_job_reads(self):
        item = spec("asr-large")["items"][0]
        self.assertEqual(item["dest"], "models/" + os.path.basename(asr_jobs.model_dir("D", "large-v3-turbo")))

    def test_it_installs_into_the_same_environment_as_the_small_model(self):
        small = spec("asr-gpu")
        self.assertEqual(small["kinds"], ["asr.transcribe"])
        self.assertTrue(small["order"] < spec("asr-large")["order"])
        self.assertFalse([i for i in spec("asr-large")["items"] if i["type"] in ("venv", "pip")], "no second Python environment: faster-whisper 1.1.0 reads it as it is")

    def test_it_is_license_clean_and_documented(self):
        with open(os.path.join(PROC, "requirements.d", "asr-large.json"), encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertIn("MIT", raw["note"])
        self.assertIn("pinned revision", raw["note"])


if __name__ == "__main__":
    unittest.main()
