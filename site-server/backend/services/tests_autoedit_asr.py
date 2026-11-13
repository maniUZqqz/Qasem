"""The words behind the automatic edit come from the best recogniser the card has: faster-whisper (`asr.transcribe`, agent 2.11+) when an online node
advertises it, the PersianAiKit's `voice.asr` otherwise or as the second chance.  No node, no model: the compute layer is faked."""
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from services.editing import captions

WHISPER_JSON = {"language": "fa", "duration": 3.0, "text": "سلام دنیا", "segments": [{"start": 0.0, "end": 1.2, "text": "سلام دنیا", "words": [
    {"word": "سلام", "start": 0.1, "end": 0.5}, {"word": "دنیا", "start": 0.6, "end": 1.1}]}],
    "words": [{"word": "سلام", "start": 0.1, "end": 0.5}, {"word": "دنیا", "start": 0.6, "end": 1.1}]}


class Job(SimpleNamespace):
    def outputs(self):
        return self.outs


def node(kinds=None):
    return SimpleNamespace(capabilities={"kinds": kinds} if kinds is not None else {})


class WhisperPreferenceTests(SimpleTestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="nm-asr-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.wav = self.dir / "a.wav"
        self.wav.write_bytes(b"RIFF" + b"\0" * 100)
        (self.dir / "transcript.json").write_text(json.dumps(WHISPER_JSON), encoding="utf-8")
        (self.dir / "asr.json").write_text(json.dumps({"result": [{"word": "کهنه", "start": 0.0, "end": 0.4}]}), encoding="utf-8")

    def online(self, *, any_nodes, voice_nodes):
        return lambda cap=None: any_nodes if cap == "any" else voice_nodes

    def test_a_node_that_advertises_whisper_gets_the_whisper_job(self):
        card = node(["echo", "asr.transcribe", "edit.render"])
        job = Job(outs=[{"name": "transcript.json"}])
        with patch("apps.compute.services.online_nodes", side_effect=self.online(any_nodes=[card], voice_nodes=[card])), \
                patch("apps.compute.services.enqueue", return_value=job) as enqueue, patch("apps.compute.services.wait", return_value=job), \
                patch("apps.compute.services.output_path", side_effect=lambda j, name: self.dir / name):
            out = captions.transcribe_wav(self.wav)
        args, kwargs = enqueue.call_args
        self.assertEqual(args[0], "asr.transcribe")
        self.assertEqual((args[1]["language"], args[1]["word_timestamps"], args[1]["audio"]), ("fa", True, "audio.wav"))
        self.assertEqual(kwargs["files"], {"audio.wav": self.wav})
        self.assertEqual([w["w"] for w in out["words"]], ["سلام", "دنیا"])
        self.assertEqual((out["engine"], out["via"]), ("node", "asr.transcribe"))

    def test_an_older_agent_keeps_the_voice_asr_path(self):
        old = node(None)
        job = Job(outs=[{"name": "asr.json"}])
        with patch("apps.compute.services.online_nodes", side_effect=self.online(any_nodes=[old], voice_nodes=[old])), \
                patch("apps.compute.services.enqueue", return_value=job) as enqueue, patch("apps.compute.services.wait", return_value=job), \
                patch("apps.compute.services.output_path", side_effect=lambda j, name: self.dir / name):
            out = captions.transcribe_wav(self.wav)
        self.assertEqual(enqueue.call_args[0][0], "voice.asr")
        self.assertEqual(out["via"], "voice.asr")

    def test_whisper_still_installing_falls_back_to_the_voice_recogniser(self):
        from apps.compute import services as compute

        card = node(["asr.transcribe"])
        job = Job(outs=[{"name": "asr.json"}])
        waits = iter([compute.ComputeFailed("DOWNLOADING: the speech-recognition engine is still being installed"), job])

        def wait(*a, **k):
            r = next(waits)
            if isinstance(r, Exception):
                raise r
            return r

        with patch("apps.compute.services.online_nodes", side_effect=self.online(any_nodes=[card], voice_nodes=[card])), \
                patch("apps.compute.services.enqueue", return_value=job) as enqueue, patch("apps.compute.services.wait", side_effect=wait), \
                patch("apps.compute.services.output_path", side_effect=lambda j, name: self.dir / name):
            out = captions.transcribe_wav(self.wav)
        self.assertEqual([c[0][0] for c in enqueue.call_args_list], ["asr.transcribe", "voice.asr"])
        self.assertEqual(out["via"], "voice.asr")

    def test_a_whisper_only_card_without_the_voice_service_still_transcribes(self):
        card = node(["asr.transcribe"])
        job = Job(outs=[{"name": "transcript.json"}])
        with patch("apps.compute.services.online_nodes", side_effect=self.online(any_nodes=[card], voice_nodes=[])), \
                patch("apps.compute.services.enqueue", return_value=job), patch("apps.compute.services.wait", return_value=job), \
                patch("apps.compute.services.output_path", side_effect=lambda j, name: self.dir / name):
            self.assertEqual(captions.transcribe_wav(self.wav)["via"], "asr.transcribe")
        with patch("apps.compute.services.online_nodes", side_effect=self.online(any_nodes=[card], voice_nodes=[])), \
                patch("services.editing.captions._local_ready", return_value=False):
            self.assertTrue(captions.status()["node"], "the panel says the words are available")
