# -*- coding: utf-8 -*-
"""The node acceptance run also checks the speech LANGUAGE path (review of 2026-11-13): the Persian Piper sample is sent with language "auto"
and Whisper must detect Persian by itself - so an English video will be heard as English.  `selftests/autoedit.py: autoedit_words_auto`."""
import json

from django.utils import timezone

from . import services as SV
from .models import ComputeJob, SelfTestResult, SelfTestRun
from .selftests import REGISTRY
from .tests_selftest_autoedit import WORDS, _Base, mk_node


class AutoLanguageSelfTest(_Base):
    def job(self, doc, **meta):
        job = SV.enqueue("asr.transcribe", {"audio": "audio.wav"}, dedupe=False, require_online=False)
        SV.output_path(job, "transcript.json").write_bytes(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        job.refresh_from_db()
        job.state = ComputeJob.State.RUNNING
        job.node = self.node
        job.claimed_at = timezone.now()
        job.save()
        SV.finish(job, self.node, True, meta=meta or {"device": "cuda"})
        job.refresh_from_db()
        return job

    def test_it_is_registered_after_the_piper_sample(self):
        t = REGISTRY["autoedit_words_auto"]
        self.assertEqual(t.kind, "asr.transcribe")
        self.assertEqual(t.after, ("tts_piper",))

    def test_only_an_agent_that_advertises_auto_gets_the_test(self):
        t = REGISTRY["autoedit_words_auto"]
        new = mk_node(name="new-agent", asr_languages=["fa", "en", "auto"])
        ok, why = t.available(new)
        self.assertTrue(ok, why)
        old = mk_node(name="old-agent")                               # a whole pipeline but no asr_languages
        ok, why = t.available(old)
        self.assertFalse(ok)
        self.assertIn("تشخیصِ خودکارِ زبان", why)
        self.assertIn("به‌روزرسانی", why)

    def test_the_job_sends_an_empty_language_to_a_node_that_understands_it(self):
        t = REGISTRY["autoedit_words_auto"]
        self.node.capabilities = {**self.node.capabilities, "asr_languages": ["fa", "en", "auto"], "asr_models": ["small"]}
        self.node.save()
        tts = SV.enqueue("voice.tts", {"text": "x"}, dedupe=False, require_online=False)
        SV.output_path(tts, "speech.wav").write_bytes(b"RIFFwav")
        res = SelfTestResult.objects.create(run=SelfTestRun.objects.create(node=self.node, trigger="manual"), key="tts_piper", label="t", job_uid=tts.uid)
        spec = t.build(self.ctx("autoedit_words_auto", {"tts_piper": res}))
        self.assertEqual(spec.kind, "asr.transcribe")
        self.assertEqual(spec.payload["language"], "")
        self.assertEqual(spec.files, {"audio.wav": b"RIFFwav"})
        self.assertIsNone(t.build(self.ctx("autoedit_words_auto", {})), "no sample, no test")

    def test_passes_when_whisper_detects_persian(self):
        t = REGISTRY["autoedit_words_auto"]
        v = t.check(self.ctx("autoedit_words_auto"), self.job({"duration": 3.0, "language": "fa", "words": WORDS, "text": "سلام با چغر چغرتر شو"}))
        self.assertTrue(v.ok, v.detail)
        self.assertIn("فارسی", v.detail)

    def test_fails_when_the_detected_language_is_wrong(self):
        t = REGISTRY["autoedit_words_auto"]
        v = t.check(self.ctx("autoedit_words_auto"), self.job({"duration": 3.0, "language": "ar", "words": WORDS, "text": "سلام با چغر چغرتر شو"}))
        self.assertFalse(v.ok)
        self.assertIn("«ar»", v.detail)
        v = t.check(self.ctx("autoedit_words_auto"), self.job({"duration": 3.0, "words": WORDS, "text": "سلام با چغر چغرتر شو"}))
        self.assertFalse(v.ok, "a transcript without the detected language is not a pass")

    def test_the_words_check_still_applies(self):
        t = REGISTRY["autoedit_words_auto"]
        v = t.check(self.ctx("autoedit_words_auto"), self.job({"duration": 3.0, "language": "fa", "words": [1], "text": "x"}))
        self.assertFalse(v.ok)
