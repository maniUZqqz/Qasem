"""«سرورهای پردازش › مدل‌های صدا»: the switches (and what falls back when a model is off), jobs that wait while a model
downloads, «تست» and «دانلود». The node is faked in-process (claim -> outputs -> finish)."""
import io
import shutil
import tempfile
import wave
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai.models import AudioAsset, AudioEngine, ClonedVoice
from services.audio import node_audio, soundscape, studio, tts
from services.audio import voice_clone as vc
from apps.stores.models import Store

from . import services as SV
from . import voice_models as vm
from .bench_models import AudioBenchmark
from .models import ComputeJob, ComputeNode

TMP = tempfile.mkdtemp(prefix="nm-voice-models-")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)
ALL = {"moss": True, "sfx": True, "music": True}


def wav_bytes(seconds=2.0, sr=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x01\x00" * int(seconds * sr))
    return buf.getvalue()


@override_settings(NM_DATA_DIR=Path(TMP), MEDIA_ROOT=TMP, IS_TEST=True)
class VoiceModelsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("vm-staff", password="x", is_staff=True)
        self.owner = User.objects.create_user("vm-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")
        self.node = ComputeNode.objects.create(name="GPU-1", last_seen=timezone.now(), capabilities={
            "voice": True, "agent": "1.8", "audio": dict(ALL),
            "models": {"running": False, "packages": {
                "moss-tts": {"installed": True, "optional": False, "missing_mb": 0, "total_mb": 15800},
                "fun-inp": {"installed": False, "optional": True, "missing_mb": 4190, "total_mb": 4190}}},
            "preflight": [{"key": "python", "ok": True, "detail": "3.12.10"}]})
        self.url = f"/api/v1/compute/nodes/{self.node.pk}/audio/"

    def switch(self, **values):
        self.client.force_login(self.staff)
        r = self.client.patch(self.url, values, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.node.refresh_from_db()
        return r.json()

    def complete(self, job, outputs=None, meta=None, ok=True, error=""):
        claimed = SV.claim(self.node)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, job.pk)
        for name, data in (outputs or {}).items():
            SV.output_path(job, name).write_bytes(data)
        SV.finish(job, self.node, ok, error, meta or {})

    # ------------------------------------------------------------ the card + switches
    def test_card_and_switches(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 403, "staff only")
        card = self.switch(music=False, idle_min=7)
        self.assertEqual(self.node.desired["audio"], {"music": False, "idle_min": 7})
        rows = {r["key"]: r for r in card["rows"]}
        self.assertFalse(rows["music"]["enabled"])
        self.assertTrue(rows["speech"]["enabled"] and rows["speech"]["installed"])
        self.assertEqual(card["settings"]["idle_min"], 7)
        self.assertTrue(any(p["package"] == "fun-inp" and p["optional"] for p in card["packages"]))
        self.assertEqual(card["preflight"][0]["key"], "python")

    def test_speech_off_falls_back_to_the_next_voice(self):
        AudioEngine.objects.filter(role="VOICE", kind="EDGE").update(is_active=False)   # next engine: Piper
        first = tts.get_tts_provider("fa", Store.objects.get(pk=self.store.pk))
        first = first.providers[0] if hasattr(first, "providers") else first
        self.assertIsInstance(first, node_audio.NodeMossProvider)
        self.switch(speech=False)
        chain = tts.get_tts_provider("fa", Store.objects.get(pk=self.store.pk))
        names = [p.name for p in getattr(chain, "providers", [chain])]
        self.assertNotIn("moss", names)
        self.assertEqual(names[0], "piper")
        with self.assertRaises(node_audio.NodeAudioError) as ctx:
            node_audio.pick_node("moss", purpose="speech")
        self.assertEqual(ctx.exception.code, "disabled")
        self.assertEqual(node_audio.pick_node("moss", purpose="clone"), "GPU-1", "cloning has its own switch")

    def test_clone_off_says_so_for_both_engines(self):
        self.switch(clone=False)
        voice = ClonedVoice.objects.create(store=self.store, name="صدا", person="x", consent_text="x",
                                           consent_at=timezone.now(), engine="moss-fa", status="READY", revision=1,
                                           node_voice_id="v")
        with self.assertRaises(vc.VoiceCloneError) as ctx:
            vc.enqueue_tts(voice, "سلام")
        self.assertIn("کلونِ صدا خاموش است", str(ctx.exception))
        voice.engine = "pocket"
        voice.save()
        with self.assertRaises(vc.VoiceCloneError) as ctx:
            vc.enqueue_tts(voice, "سلام")
        self.assertIn("کلونِ صدا خاموش است", str(ctx.exception))

    def test_sfx_and_music_off(self):
        self.switch(sfx=False, music=False)
        AudioEngine.objects.filter(role="SOUND").exclude(kind="NODE_SFX").update(is_active=False)
        work = Path(TMP) / "w"
        work.mkdir(parents=True, exist_ok=True)
        self.assertIsNone(soundscape.pick("rain", seconds=8, seed="s", work=work), "no node job for a switched-off model")
        self.assertFalse(ComputeJob.objects.filter(kind="voice.sfx").exists())
        with self.assertRaises(studio.StudioError) as ctx:
            studio.create_music(self.store, self.owner, style="calm", seconds=20)
        self.assertIn("موسیقیِ ساختهٔ ماشین خاموش است", str(ctx.exception))

    def test_claim_keeps_switched_off_and_downloading_jobs_back(self):
        echo = SV.enqueue("echo", {"x": 1})
        sfx = SV.enqueue("voice.sfx", {"prompt": "rain", "seconds": 3}, node="GPU-1")
        self.switch(sfx=False)
        self.assertEqual(SV.claim(self.node).pk, echo.pk)
        self.assertIsNone(SV.claim(self.node), "a job for a switched-off model is never handed out")
        self.switch(sfx=True)
        caps = dict(self.node.capabilities, audio={"moss": True, "sfx": False, "music": True})
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities=caps)
        self.node.refresh_from_db()
        self.assertIsNone(SV.claim(self.node), "not installed yet: the job waits in the queue")
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities=dict(caps, audio=dict(ALL)))
        self.node.refresh_from_db()
        self.assertEqual(SV.claim(self.node).pk, sfx.pk)

    def test_studio_jobs_wait_for_a_download(self):
        caps = dict(self.node.capabilities, audio={"moss": False, "sfx": True, "music": True}, models={
            "running": True, "progress": {"packages": ["moss-tts"], "bytes_done": 45, "bytes_total": 100},
            "packages": {"moss-tts": {"installed": False, "optional": False}}})
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities=caps)
        with self.assertRaises(node_audio.NodeAudioError) as ctx:
            node_audio.pick_node("moss", purpose="speech")              # narration: do not wait, fall back
        self.assertEqual(ctx.exception.code, "downloading")
        self.assertFalse(node_audio.moss_ready()[0])
        asset = studio.create_speech(self.store, self.owner, text="سلام", voice_id="moss:mana")
        self.assertEqual(asset.status, AudioAsset.Status.PENDING)
        job = ComputeJob.objects.get(kind="voice.tts")
        self.assertIsNone(SV.claim(ComputeNode.objects.get(pk=self.node.pk)))
        msg = studio.asset_json(asset)["job"]["message"]
        self.assertIn("در حالِ دانلود", msg)
        self.assertIn("45", msg)
        self.assertEqual(node_audio.status()["engines"]["moss"]["downloading"], 45.0)
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities=dict(caps, audio=dict(ALL)))
        self.assertEqual(SV.claim(ComputeNode.objects.get(pk=self.node.pk)).pk, job.pk)

    # ------------------------------------------------------------ «تست»
    def test_benchmark(self):
        self.client.force_login(self.staff)
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now() - timedelta(hours=1))
        r = self.client.post(self.url + "test/", {"model": "speech"}, content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], "QUEUED")
        self.assertIn("سرورِ پردازش روشن شود", r.json()["waiting"], "an offline node: the test waits with a message")
        job = ComputeJob.objects.get(kind="node.bench")
        self.assertEqual(job.node_wanted, "GPU-1")
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now())
        self.node.refresh_from_db()
        bench = {"model": "speech", "load_s": 42.0, "gen_s": 6.1, "audio_s": 10.2, "rtf": 0.6, "vram_peak_mb": 10200,
                 "vram_base_mb": 900, "vram_total_mb": 12288, "ram_peak_used_mb": 9000, "ram_total_mb": 32000,
                 "gpu_util_peak": 97, "gpu_util_avg": 81, "cold": True}
        self.complete(job, {"bench.wav": wav_bytes(10), "bench.json": b"{}"}, {"bench": bench})
        tests = self.client.get(self.url + "tests/").json()["tests"]
        self.assertEqual(tests[0]["status"], "DONE")
        self.assertEqual(tests[0]["verdict"], "medium")
        self.assertEqual(tests[0]["verdict_label"], "متوسط")
        self.assertIn("۳۶ ثانیه", tests[0]["meaning"])
        self.assertTrue(tests[0]["has_audio"])
        self.assertEqual(self.client.get(tests[0]["audio"]).status_code, 200)
        card = self.client.get(self.url).json()
        self.assertEqual({r["key"]: r for r in card["rows"]}["speech"]["last_test"]["verdict"], "medium")

    def test_verdicts_and_refusals(self):
        self.assertEqual(vm.verdict({"rtf": 0.3, "vram_peak_mb": 5000, "vram_base_mb": 500})[0], "light")
        self.assertEqual(vm.verdict({"rtf": 2.0, "vram_peak_mb": 5000, "vram_base_mb": 500})[0], "heavy")
        self.assertEqual(vm.verdict({"rtf": 0.4, "vram_peak_mb": 11800, "vram_base_mb": 500})[0], "heavy")
        self.switch(music=False)
        r = self.client.post(self.url + "test/", {"model": "music"}, content_type="application/json")
        self.assertEqual(r.status_code, 409)
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities=dict(self.node.capabilities, agent="1.7"))
        r = self.client.post(self.url + "test/", {"model": "speech"}, content_type="application/json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("git pull", r.json()["error"])

    # ------------------------------------------------------------ «دانلود»
    def test_download_button(self):
        self.client.force_login(self.staff)
        r = self.client.post(f"/api/v1/compute/nodes/{self.node.pk}/models/download/",
                             {"packages": ["fun-inp", "wan22-4step"]}, content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        self.assertEqual(r.json()["download"]["queued"], ["fun-inp", "wan22-4step"])
        job = ComputeJob.objects.get(kind="node.models")
        self.assertEqual(SV.claim(self.node).pk, job.pk, "node.* jobs are claimable by the node they name")
        SV.finish(job, self.node, True, "", {"result": "started"})
        self.assertEqual(vm.card(self.node)["download"]["queued"], ["fun-inp", "wan22-4step"],
                         "answered, but no heartbeat says 'downloading' yet: still «در صف», so the card keeps polling")
        caps = dict(self.node.capabilities)
        caps["models"] = {**caps["models"], "running": True,
                          "progress": {"packages": ["fun-inp", "wan22-4step"], "bytes_done": 1, "bytes_total": 4}}
        self.node.capabilities = caps
        self.node.save()
        card = vm.card(self.node)
        self.assertEqual(card["download"]["queued"], [])
        self.assertTrue(card["download"]["running"])
        self.assertEqual(card["download"]["percent"], 25.0)
        other = ComputeNode.objects.create(name="GPU-2", last_seen=timezone.now(), capabilities={"agent": "1.8"})
        SV.enqueue("node.models", {"action": "download", "packages": ["x"]}, node="GPU-1", dedupe=False)
        self.assertIsNone(SV.claim(other), "never another node's")
