# -*- coding: utf-8 -*-
"""The automatic edit's entries in the node acceptance run (`selftests/autoedit.py` + the `autoedit_matte` block of docs/selftests/autoedit.md):
registered, skipped (with the reason) on an agent that lacks a kind of the pipeline, queued for the right node with the sample's files registered
for download, judged on what comes back, never hung.  A pretend node answers; no GPU and no real node are needed."""
import json
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from . import services as SV
from . import transfer
from .models import ComputeJob, ComputeNode, SelfTestResult, SelfTestRun
from .selftests import REGISTRY, Ctx, load_all, runner

try:
    from services.editing import export, selftest_autoedit as st
    from services.video.ffmpeg import FFMPEG
    HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))
except Exception:  # noqa: BLE001
    HAVE = False

ALL_KINDS = ["echo", "asr.transcribe", "edit.track", "edit.matte", "edit.render", "voice.tts", "selftest.gpu"]
WORDS = [{"word": "سلام", "start": 0.1, "end": 0.5}, {"word": "با", "start": 0.6, "end": 0.7}, {"word": "چغر", "start": 0.8, "end": 1.2},
         {"word": "چغرتر", "start": 1.3, "end": 1.8}, {"word": "شو", "start": 1.9, "end": 2.1}]


def mk_node(kinds=None, name="gpu-ae", **caps):
    base = {"agent": "2.11", "kinds": list(ALL_KINDS if kinds is None else kinds), "ffmpeg": True,
            "edit": {"render": True, "nvenc": {"h264": True}}}
    base.update(caps)
    return ComputeNode.objects.create(name=name, capabilities=base, last_seen=timezone.now())


class _Base(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm-ae-selftest-"))
        self.ctx_settings = override_settings(NM_DATA_DIR=self.tmp, IS_TEST=True)
        self.ctx_settings.enable()
        load_all()
        self.node = mk_node()

    def tearDown(self):
        self.ctx_settings.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx(self, key="autoedit_mix", results=None):
        run = SelfTestRun.objects.create(node=self.node, trigger="manual")
        res = SelfTestResult.objects.create(run=run, key=key, label="x", started_at=timezone.now())
        return Ctx(self.node, run, results or {}, result=res)


class RegistrationTests(_Base):
    def test_the_three_entries_are_registered(self):
        for key in ("autoedit_words", "autoedit_mix", "autoedit_matte"):
            self.assertIn(key, REGISTRY, key)
        self.assertEqual(REGISTRY["autoedit_matte"].kind, "edit.matte")
        self.assertEqual(REGISTRY["autoedit_words"].kind, "asr.transcribe")
        self.assertIsNotNone(REGISTRY["autoedit_mix"].virtual)
        self.assertEqual(REGISTRY["autoedit_mix"].after, ("edit_render",))

    def test_a_node_with_the_whole_pipeline_gets_the_tests(self):
        for key in ("autoedit_words", "autoedit_mix"):
            self.assertEqual(REGISTRY[key].available(self.node), (True, ""), key)

    def test_a_missing_kind_skips_with_its_name_never_fails(self):
        old = mk_node(kinds=[k for k in ALL_KINDS if k != "edit.matte"], name="old-agent")
        for key in ("autoedit_words", "autoedit_mix"):
            ok, why = REGISTRY[key].available(old)
            self.assertFalse(ok)
            self.assertIn("edit.matte", why)

    def test_an_agent_without_a_kind_list_is_too_old(self):
        node = mk_node(name="no-kinds")
        node.capabilities.pop("kinds")
        ok, why = REGISTRY["autoedit_words"].available(node)
        self.assertFalse(ok)
        self.assertIn("قدیمی", why)

    def test_the_mix_needs_a_render_capable_ffmpeg(self):
        node = mk_node(name="no-render", edit={"render": False, "missing": ["ass"]})
        self.assertFalse(REGISTRY["autoedit_mix"].available(node)[0])


class WordsTests(_Base):
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

    def test_good_words_with_the_sentences_own_words_pass(self):
        t = REGISTRY["autoedit_words"]
        job = self.job({"duration": 3.0, "words": WORDS, "text": "سلام با چغر چغرتر شو"})
        v = t.check(self.ctx("autoedit_words"), job)
        self.assertTrue(v.ok, v.detail)
        self.assertEqual(v.device, "cuda")

    def test_nonsense_words_fail_with_the_reason(self):
        t = REGISTRY["autoedit_words"]
        v = t.check(self.ctx("autoedit_words"), self.job({"duration": 3.0, "words": [1], "text": "x"}))
        self.assertFalse(v.ok)
        v = t.check(self.ctx("autoedit_words"), self.job({"duration": 0.5, "words": WORDS}))
        self.assertFalse(v.ok, "words that end long after the clip does are not the clip's words")

    def test_the_job_is_the_whisper_job_built_from_the_piper_sample(self):
        t = REGISTRY["autoedit_words"]
        tts = SV.enqueue("voice.tts", {"text": "x"}, dedupe=False, require_online=False)
        SV.output_path(tts, "speech.wav").write_bytes(b"RIFFwav")
        res = SelfTestResult.objects.create(run=SelfTestRun.objects.create(node=self.node, trigger="manual"), key="tts_piper", label="t", job_uid=tts.uid)
        spec = t.build(self.ctx("autoedit_words", {"tts_piper": res}))
        self.assertEqual(spec.kind, "asr.transcribe")
        self.assertEqual((spec.payload["language"], spec.payload["word_timestamps"], spec.payload["audio"]), ("fa", True, "audio.wav"))
        self.assertEqual(spec.files, {"audio.wav": b"RIFFwav"})
        self.assertIsNone(t.build(self.ctx("autoedit_words", {})), "no sample, no test")


class MixTests(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.keep = Path(tempfile.mkdtemp(prefix="nm-ae-mix-"))
        cls.good = cls.bad = None
        if HAVE:
            media = st.make_media(cls.keep / "media")
            cls.good = cls.keep / "good.mp4"
            export.render(st.build_timeline(st.mix_project(), media), cls.good, quality="draft")
            data = st.mix_project()
            data["ducking"] = {"on": False}
            cls.bad = cls.keep / "unducked.mp4"
            export.render(st.build_timeline(data, media), cls.bad, quality="draft")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.keep, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")
        super().setUp()

    def finish(self, job, out, ok=True, meta=None, error=""):
        if out is not None:
            shutil.copyfile(out, SV.output_path(job, "render.mp4"))
        job.refresh_from_db()
        job.state = ComputeJob.State.RUNNING
        job.node = self.node
        job.claimed_at = timezone.now()
        job.attempts = 1
        job.save()
        SV.finish(job, self.node, ok, meta=meta or {"encoder": "NVENC H.264"}, error=error)
        job.refresh_from_db()

    def test_the_first_step_queues_the_sample_render_for_this_node_with_its_files_registered(self):
        ctx = self.ctx()
        v = REGISTRY["autoedit_mix"].virtual(ctx)
        self.assertTrue(v.wait and not v.ok, v.detail)
        state = v.extra["autoedit_mix"]
        job = ComputeJob.objects.get(uid=state["job"])
        self.assertEqual((job.kind, job.origin, job.node_wanted, job.max_attempts), ("edit.render", "selftest", self.node.name, 1))
        assets = transfer.load_assets(job)
        self.assertEqual(len(assets), len(job.payload["files"]))
        self.assertTrue(assets and all(Path(a["path"]).is_file() for a in assets.values()), "the node can download what the render reads")
        self.assertTrue(job.payload["audio"], "the sample has a sound track the node must mix")

    def test_it_waits_while_the_job_runs_then_passes_a_correct_render(self):
        ctx = self.ctx()
        t = REGISTRY["autoedit_mix"]
        first = t.virtual(ctx)
        ctx.result.extra = first.extra
        job = ComputeJob.objects.get(uid=first.extra["autoedit_mix"]["job"])
        again = t.virtual(ctx)
        self.assertTrue(again.wait, "the job is not done: ask again later")
        self.finish(job, self.good)
        v = t.virtual(ctx)
        self.assertTrue(v.ok, v.detail)
        self.assertIn("NVENC", v.detail)
        self.assertFalse(Path(first.extra["autoedit_mix"]["dir"]).exists(), "the sample media is removed when the verdict is in")

    def test_a_render_without_the_default_ducking_fails_and_says_what(self):
        ctx = self.ctx()
        first = REGISTRY["autoedit_mix"].virtual(ctx)
        ctx.result.extra = first.extra
        self.finish(ComputeJob.objects.get(uid=first.extra["autoedit_mix"]["job"]), self.bad)
        v = REGISTRY["autoedit_mix"].virtual(ctx)
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)
        self.assertIn("دسی‌بل", v.detail)

    def test_a_cpu_render_on_a_card_with_nvenc_passes_with_a_warning(self):
        ctx = self.ctx()
        first = REGISTRY["autoedit_mix"].virtual(ctx)
        ctx.result.extra = first.extra
        self.finish(ComputeJob.objects.get(uid=first.extra["autoedit_mix"]["job"]), self.good, meta={"encoder": "libx264"})
        v = REGISTRY["autoedit_mix"].virtual(ctx)
        self.assertTrue(v.ok, v.detail)
        self.assertIn("NVENC", v.warning)

    def test_a_failed_render_job_fails_with_the_nodes_error(self):
        ctx = self.ctx()
        first = REGISTRY["autoedit_mix"].virtual(ctx)
        ctx.result.extra = first.extra
        self.finish(ComputeJob.objects.get(uid=first.extra["autoedit_mix"]["job"]), None, ok=False, error="ffmpeg: Unknown encoder")
        v = REGISTRY["autoedit_mix"].virtual(ctx)
        self.assertFalse(v.ok)
        self.assertIn("Unknown encoder", v.detail)

    def pass_the_editors_own_render_test(self, run):
        """The prerequisite (`edit_render`): the pretend node answers its job like a healthy one."""
        base = run.results.get(key="edit_render")
        job = ComputeJob.objects.get(uid=base.job_uid)
        SV.output_path(job, "render.mp4").write_bytes(b"v" * 9000)
        self.finish(job, None, meta={"encoder": "NVENC H.264", "device": "nvenc"})
        for _ in range(2):
            runner.advance(run)

    def test_the_whole_runner_drives_it_to_a_verdict(self):
        run = runner.start_run(self.node, "manual", only=["autoedit_mix"])            # the prerequisite (the editor's own render test) comes along
        self.assertEqual({r.key for r in run.results.all()}, {"edit_render", "autoedit_mix"})
        self.pass_the_editors_own_render_test(run)
        res = run.results.get(key="autoedit_mix")
        self.assertEqual(res.state, "WAITING", res.detail)
        job = ComputeJob.objects.get(uid=res.extra["autoedit_mix"]["job"])
        self.finish(job, self.good)
        for _ in range(3):
            runner.advance(run)
        res.refresh_from_db()
        self.assertEqual(res.state, "PASSED", res.detail)

    def test_a_node_that_lacks_a_kind_is_skipped_by_the_runner_not_failed(self):
        node = ComputeNode.objects.create(name="old", capabilities={"agent": "2.11", "kinds": ["echo", "edit.render"], "ffmpeg": True,
                                                                  "edit": {"render": True}}, last_seen=timezone.now())
        self.node = node
        run = runner.start_run(node, "manual", only=["autoedit_mix"])
        self.pass_the_editors_own_render_test(run)
        res = run.results.get(key="autoedit_mix")
        self.assertEqual(res.state, "SKIPPED", res.detail)
        self.assertIn("edit.matte", res.detail)
