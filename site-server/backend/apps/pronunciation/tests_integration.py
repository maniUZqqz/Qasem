# -*- coding: utf-8 -*-
"""Integration fixes made at deploy time: (1) the acceptance test of the node kind `voice.pron_asr` (apps/compute/selftests/pron.py: pron_asr):
one short Piper recording made on the site is sent to the node, whose Whisper only listens; (2) the Piper voice the test box and that test use is
one that is really installed on THIS site (it has gyro, mana, ganji; not amir). Pure logic: no node, no Piper, no network."""
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from apps.compute import selftests
from apps.compute.selftests import REGISTRY
from apps.compute.selftests import pron as P
from services.audio import tts
from services.audio.fa_pron import eval_set

from . import services as svc
from .tests import Base


class _Ctx:
    def __init__(self, data):
        self.data = data

    def read_json(self, job, name):
        return self.data


def _node(kinds):
    return SimpleNamespace(capabilities={"kinds": kinds} if kinds is not None else {})


class PronAsrSelfTest(SimpleTestCase):
    def setUp(self):
        selftests.load_all()
        self.t = REGISTRY["pron_asr"]

    def test_it_is_the_acceptance_test_of_the_listen_only_kind(self):
        self.assertEqual(self.t.kind, "voice.pron_asr")
        self.assertEqual(self.t.after, ("pron_piper",))
        self.assertEqual(self.t.needs_features, ("pron",))
        self.assertIn("voice.pron_asr", self.t.requeue["kinds"])

    def test_an_agent_that_does_not_advertise_the_kind_is_skipped_not_failed(self):
        ok, why = self.t.available(_node(["voice.tts"]))
        self.assertFalse(ok)
        self.assertIn("به‌روزرسانی", why)
        self.assertFalse(self.t.available(_node(None))[0])
        self.assertTrue(self.t.available(_node(["voice.pron_asr", "voice.pron_eval"]))[0])

    def test_build_sends_one_local_recording(self):
        calls = {}

        class FakePiper:
            def __init__(self, voice):
                calls["voice"] = voice

            def synthesize(self, text, out):
                calls["text"] = text
                calls["flags"] = (self.store, self.language, self.use_pron)
                Path(out).write_bytes(b"RIFF....WAVEfmt ")
                return out

        with mock.patch("services.audio.tts.PiperProvider", FakePiper), mock.patch("apps.pronunciation.services.site_piper_voice", return_value="fa_IR-gyro-medium"):
            spec = self.t.build(None)
        self.assertEqual(spec.kind, "voice.pron_asr")
        (f,) = spec.payload["files"]
        self.assertEqual(list(spec.files), [f["name"]])
        self.assertTrue(spec.files[f["name"]].startswith(b"RIFF"))
        self.assertEqual(calls["text"], eval_set.SENTENCES[f["id"]][1])
        self.assertEqual(calls["voice"], "fa_IR-gyro-medium")
        self.assertEqual(calls["flags"], (None, "fa", False), "the recording is the plain text: the layer is not part of this test")

    def test_build_without_a_local_piper_voice_gives_none(self):
        with mock.patch("services.audio.tts.PiperProvider", side_effect=RuntimeError("no voice")):
            self.assertIsNone(self.t.build(None))

    def test_check_passes_when_the_sentence_is_heard(self):
        ref = eval_set.SENTENCES[P.ASR_SENTENCE][1]
        data = {"asr": {"model": "small", "device": "cuda"}, "items": [{"id": 0, "variant": "before", "hyp": ref}]}
        v = self.t.check(_Ctx(data), None)
        self.assertTrue(v.ok, v.detail)
        self.assertEqual(v.warning, "")

    def test_check_fails_on_silence_and_on_gibberish(self):
        self.assertFalse(self.t.check(_Ctx(None), None).ok)
        self.assertFalse(self.t.check(_Ctx({"items": [{"variant": "before", "hyp": "  "}]}), None).ok)
        v = self.t.check(_Ctx({"asr": {"device": "cuda"}, "items": [{"variant": "before", "hyp": "کلمه های نامربوط و بی ربط به جمله"}]}), None)
        self.assertFalse(v.ok)

    def test_a_cpu_fallback_passes_with_a_warning(self):
        ref = eval_set.SENTENCES[P.ASR_SENTENCE][1]
        data = {"asr": {"model": "small", "device": "cpu", "note": "no CUDA"}, "items": [{"variant": "before", "hyp": ref}]}
        v = self.t.check(_Ctx(data), None)
        self.assertTrue(v.ok)
        self.assertIn("پردازنده", v.warning)


class SiteVoiceTests(Base):
    """The site has only the Piper voices audio_setup downloaded; the test box must never ask for one it does not have."""

    def setUp(self):
        super().setUp()
        self.models = Path(tempfile.mkdtemp(prefix="nmpron-models-"))
        self.addCleanup(shutil.rmtree, self.models, ignore_errors=True)
        patcher = mock.patch("services.audio.engines.piper_model_path", side_effect=lambda name: self.models / (str(name).removesuffix(".onnx") + ".onnx"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, *names):
        for n in names:
            (self.models / (n + ".onnx")).write_bytes(b"x")
            (self.models / (n + ".onnx.json")).write_bytes(b"{}")

    def test_the_first_installed_voice_of_the_preference_list_is_used(self):
        self.install("fa_IR-mana-medium", "fa_IR-gyro-medium")
        self.assertEqual(svc.site_piper_voice(""), "fa_IR-gyro-medium")
        self.assertEqual(svc.site_piper_voice("fa_IR-mana-medium"), "fa_IR-mana-medium")
        self.assertEqual(svc.site_piper_voice("fa_IR-amir-medium"), "fa_IR-gyro-medium", "a voice that is not installed falls back to an installed one")

    def test_a_model_without_its_json_does_not_count(self):
        (self.models / "fa_IR-amir-medium.onnx").write_bytes(b"x")
        self.install("fa_IR-ganji-medium")
        self.assertEqual(svc.site_piper_voice(""), "fa_IR-ganji-medium")

    def test_nothing_installed_gives_the_engine_default_so_the_error_names_it(self):
        self.assertEqual(svc.site_piper_voice(""), "fa_IR-gyro-medium")

    def test_the_test_box_listens_with_an_installed_voice(self):
        self.install("fa_IR-gyro-medium")
        used = []

        def fake(self_, text, out_path):
            used.append(self_.voice)
            p = Path(out_path).with_suffix(".wav")
            p.write_bytes(b"RIFF0000WAVE")
            return p

        with mock.patch.object(tts.PiperProvider, "synthesize", fake):
            r = self.api.post(f"{self.base}/listen/", {"text": "سلام", "engine": "piper", "variant": "after"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(used, ["fa_IR-gyro-medium"])


class BaselineVisibleTests(Base):
    """The measurement that ships with the version belongs to no store (store NULL, baseline=True): every store must see it."""

    def test_the_shipped_baseline_shows_for_every_store(self):
        ov = self.api.get(f"{self.base}/").json()
        self.assertTrue(ov["latest"], "the shipped measurement is in the overview table")
        self.assertTrue(all(r["baseline"] for r in ov["latest"].values()))
        self.assertIn("piper", ov["latest"])
        runs = self.api.get(f"{self.base}/eval/").json()["runs"]
        self.assertTrue(runs and all(r["baseline"] for r in runs), "the shipped measurement is in the history list")
        self.assertEqual(self.api.get(f"{self.base}/eval/{runs[0]['id']}/").status_code, 200, "and it can be opened")

    def test_a_baseline_cannot_be_deleted_from_a_store(self):
        runs = self.api.get(f"{self.base}/eval/").json()["runs"]
        self.assertEqual(self.api.delete(f"{self.base}/eval/{runs[0]['id']}/").status_code, 204)
        self.assertTrue(self.api.get(f"{self.base}/eval/").json()["runs"], "still there")
