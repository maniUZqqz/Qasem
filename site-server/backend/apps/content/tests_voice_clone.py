"""«کلونِ صدا»: consent first, every clip checked, builds and speech through the compute queue, no silent fallback.

The processing node is faked in-process (claim → write outputs → finish), exactly the way the
compute tests drive the queue — the real node (agent.py) is tested separately in processing/tests.
"""
import io
import json
import shutil
import tempfile
import wave
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai.models import ClonedVoice
from apps.compute import services as SV
from apps.compute.models import ComputeJob, ComputeNode
from apps.stores.models import Store
from services.audio import tts, voice_clone as vc

TMP = tempfile.mkdtemp(prefix="nm-voice-clone-test-")


def wav_bytes(a, sr=44100) -> bytes:
    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def speechlike(seconds=3.0, amp=0.3, noise=0.0008, sr=44100, seed=1):
    """Syllable-like bursts over a quiet floor: what a clean read sentence looks like to the check."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    bursts = (np.sin(2 * np.pi * 3 * t) > -0.2).astype(np.float32)
    a = amp * np.sin(2 * np.pi * 180 * t) * bursts * (0.6 + 0.4 * np.sin(2 * np.pi * 5 * t))
    return (a + rng.normal(0, noise, len(t))).astype(np.float32)


@override_settings(NM_DATA_DIR=Path(TMP), MEDIA_ROOT=TMP, IS_TEST=True)
class VoiceCloneTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("clone-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه صدا")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/voice/clones/"
        self.node = ComputeNode.objects.create(name="DESKTOP-TEST", last_seen=timezone.now(),
                                               capabilities={"voice": True, "agent": "1.6", "voice_clone": True})

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def create(self, **extra):
        body = {"name": "صدای علی", "person": "علی رضایی", "purpose": "ویدیوهای محصول", "consent": True,
                "engine": "pocket", **extra}
        return self.client.post(self.base, body, content_type="application/json")

    def upload(self, voice_id, index, audio_bytes, name="take.wav", text=""):
        return self.client.post(f"{self.base}{voice_id}/clips/", {
            "index": index, "text": text, "source": "record",
            "file": SimpleUploadedFile(name, audio_bytes, content_type="audio/wav"),
        })

    def ready_voice(self, clips=3):
        voice_id = self.create().json()["id"]
        for i in range(1, clips + 1):
            self.assertEqual(self.upload(voice_id, i, wav_bytes(speechlike(seed=i))).status_code, 201)
        r = self.client.post(f"{self.base}{voice_id}/build/", {"consent": True}, content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        job = ComputeJob.objects.get(kind="voice.clone")
        self.fake_node(job, {"clone.json": json.dumps({
            "ready": True, "voice_id": f"nm-s{self.store.pk}-v{voice_id}", "engine": "pocket", "minutes": 0.2,
            "check": 0.08, "clips": [{"index": i, "ok": True, "message": "خوب بود ✓", "heard": "x", "wer": 0.1,
                                      "snr": 40, "seconds": 3} for i in range(1, clips + 1)]}).encode(),
            "ref.wav": wav_bytes(speechlike(5)), "sample.wav": wav_bytes(speechlike(4))})
        voice = ClonedVoice.objects.get(pk=voice_id)
        vc.sync(voice)
        self.assertEqual(voice.status, "READY", voice.error)
        return voice

    def fresh_store(self):
        """The store as a new request sees it (the test's instance caches its profile)."""
        return Store.objects.get(pk=self.store.pk)

    def fake_node(self, job, outputs, *, ok=True, error="", meta=None):
        claimed = SV.claim(self.node)
        self.assertIsNotNone(claimed, "the fake node could not claim the job")
        self.assertEqual(claimed.pk, job.pk)
        for name, data in outputs.items():
            SV.output_path(job, name).write_bytes(data)
        return SV.finish(job, self.node, ok, error, meta or {})

    # ------------------------------------------------------------------ consent
    def test_consent_is_required_and_recorded(self):
        r = self.create(consent=False)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "consent_required")
        self.assertFalse(ClonedVoice.objects.exists())
        self.assertEqual(self.create(person="").status_code, 400)

        r = self.create()
        self.assertEqual(r.status_code, 201, r.content)
        voice = ClonedVoice.objects.get()
        self.assertIn("علی رضایی", voice.consent_text)
        self.assertIn("فروشگاه صدا", voice.consent_text)
        self.assertIn("ویدیوهای محصول", voice.consent_text)
        self.assertEqual(voice.consent_by, self.owner)
        self.assertIsNotNone(voice.consent_at)
        self.assertEqual(voice.engine_license, "CC-BY-NC-4.0")

    def test_build_asks_for_consent_again(self):
        voice_id = self.create().json()["id"]
        for i in range(1, 4):
            self.upload(voice_id, i, wav_bytes(speechlike(seed=i)))
        r = self.client.post(f"{self.base}{voice_id}/build/", {}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "consent_required")
        self.assertFalse(ComputeJob.objects.filter(kind="voice.clone").exists())

    # ------------------------------------------------------------------ clips
    def test_clip_checks(self):
        voice_id = self.create().json()["id"]
        good = self.upload(voice_id, 1, wav_bytes(speechlike()), text="هر متنی")
        self.assertEqual(good.status_code, 201, good.content)
        self.assertTrue(good.json()["check"]["ok"], good.json())
        # a script sentence is always stored with the script's own text (the node compares what it hears with it)
        self.assertEqual(good.json()["clip"]["text"], vc.script()[0]["text"])

        cases = {
            2: (wav_bytes(speechlike(0.6)), "کوتاه"),
            3: (wav_bytes(speechlike(amp=1.3)), "بریده"),
            4: (wav_bytes(speechlike(noise=0.12)), "نویز"),
            5: (wav_bytes(speechlike(amp=0.004, noise=0.0002)), "آرام"),
            6: (wav_bytes(speechlike(30)), "بلند"),
        }
        for index, (audio, word) in cases.items():
            r = self.upload(voice_id, index, audio)
            self.assertEqual(r.status_code, 201, r.content)
            self.assertFalse(r.json()["check"]["ok"], (index, r.json()["check"]))
            self.assertIn(word, r.json()["check"]["message"], (index, r.json()["check"]))

        # not audio / not an allowed type
        self.assertEqual(self.upload(voice_id, 7, b"hello", name="notes.txt").status_code, 400)
        self.assertEqual(self.upload(voice_id, 7, b"RIFF....garbage", name="x.wav").status_code, 400)
        # custom sentence needs its text
        self.assertEqual(self.upload(voice_id, vc.CUSTOM_INDEX_BASE, wav_bytes(speechlike())).status_code, 400)
        r = self.upload(voice_id, vc.CUSTOM_INDEX_BASE, wav_bytes(speechlike()), text="کفش‌های تازه رسید.")
        self.assertEqual(r.json()["clip"]["text"], "کفش‌های تازه رسید.")

        # the audio is served only through the API, to members
        audio = self.client.get(f"{self.base}{voice_id}/clips/1/audio/")
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio["Content-Type"], "audio/wav")
        stranger = User.objects.create_user("stranger", password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(f"{self.base}{voice_id}/clips/1/audio/").status_code, 404)

    def test_mp3_upload_is_converted(self):
        import subprocess
        from services.video.ffmpeg import FFMPEG

        src = Path(TMP) / "src.wav"
        src.write_bytes(wav_bytes(speechlike()))
        mp3 = Path(TMP) / "take.mp3"
        subprocess.run([str(FFMPEG), "-y", "-v", "error", "-i", str(src), str(mp3)], check=True)
        voice_id = self.create().json()["id"]
        r = self.upload(voice_id, 1, mp3.read_bytes(), name="take.mp3")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["check"]["ok"], r.json()["check"])
        voice = ClonedVoice.objects.get(pk=voice_id)
        with wave.open(str(vc.clip_wav(voice, 1)), "rb") as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 44100))

    # ------------------------------------------------------------------ build
    def test_build_needs_three_good_clips_and_an_online_node(self):
        voice_id = self.create().json()["id"]
        self.upload(voice_id, 1, wav_bytes(speechlike(seed=1)))
        self.upload(voice_id, 2, wav_bytes(speechlike(seed=2)))
        self.upload(voice_id, 3, wav_bytes(speechlike(noise=0.12)))      # rejected: does not count
        r = self.client.post(f"{self.base}{voice_id}/build/", {"consent": True}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("دست‌کم", r.json()["error"]["message"])

        self.upload(voice_id, 4, wav_bytes(speechlike(seed=4)))
        ComputeNode.objects.update(last_seen=timezone.now() - timedelta(minutes=30))
        r = self.client.post(f"{self.base}{voice_id}/build/", {"consent": True}, content_type="application/json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "node_offline")
        self.assertIn("START.bat", r.json()["error"]["message"])

        ComputeNode.objects.update(last_seen=timezone.now())
        r = self.client.post(f"{self.base}{voice_id}/build/", {"consent": True}, content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        job = ComputeJob.objects.get(kind="voice.clone")
        self.assertEqual(job.node_wanted, "DESKTOP-TEST")
        self.assertTrue(job.payload["consent"]["given"])
        self.assertIn("علی رضایی", job.payload["consent"]["text"])
        self.assertEqual(job.payload["name"], f"nm-s{self.store.pk}-v{voice_id}")
        self.assertEqual([c["index"] for c in job.payload["clips"]], [1, 2, 4])
        self.assertEqual(sorted(job.inputs), ["clip_0001.wav", "clip_0002.wav", "clip_0004.wav"])
        self.assertEqual(job.payload["clips"][0]["text"], vc.script()[0]["text"])
        self.assertEqual(r.json()["status"], "BUILDING")
        # no new clips while it builds
        self.assertEqual(self.upload(voice_id, 5, wav_bytes(speechlike())).status_code, 409)

    def test_finished_build_makes_the_voice_ready(self):
        voice = self.ready_voice()
        detail = self.client.get(f"{self.base}{voice.pk}/").json()
        self.assertEqual(detail["status"], "READY", detail)
        self.assertTrue(detail["usable"])
        self.assertEqual(detail["node_name"], "DESKTOP-TEST")
        self.assertEqual(detail["revision"], 1)
        self.assertTrue(detail["has_preview"])
        self.assertEqual(detail["clips"][0]["node"]["wer"], 0.1)
        self.assertFalse(detail["needs_rebuild"])
        self.assertEqual(self.client.get(f"{self.base}{voice.pk}/sample/").status_code, 200)
        # a new clip after the build ⇒ the panel offers a rebuild
        self.upload(voice.pk, 9, wav_bytes(speechlike(seed=9)))
        self.assertTrue(self.client.get(f"{self.base}{voice.pk}/").json()["needs_rebuild"])

    def test_build_where_the_node_rejects_every_clip(self):
        voice_id = self.create().json()["id"]
        for i in range(1, 4):
            self.upload(voice_id, i, wav_bytes(speechlike(seed=i)))
        self.client.post(f"{self.base}{voice_id}/build/", {"consent": True}, content_type="application/json")
        job = ComputeJob.objects.get(kind="voice.clone")
        self.fake_node(job, {"clone.json": json.dumps({"ready": False, "voice_id": None, "clips": [
            {"index": i, "ok": False, "message": "جمله با متن جور نبود"} for i in range(1, 4)]}).encode()})
        detail = self.client.get(f"{self.base}{voice_id}/").json()
        self.assertEqual(detail["status"], "FAILED")
        self.assertIn("جور نبود", detail["error"])
        self.assertFalse(detail["usable"])

    def test_failed_build_job_shows_the_nodes_message(self):
        voice_id = self.create().json()["id"]
        for i in range(1, 4):
            self.upload(voice_id, i, wav_bytes(speechlike(seed=i)))
        self.client.post(f"{self.base}{voice_id}/build/", {"consent": True}, content_type="application/json")
        job = ComputeJob.objects.get(kind="voice.clone")
        job.max_attempts = 1
        job.save()
        self.fake_node(job, {}, ok=False, error="JobError: VOICE_SETUP: run tools\\PersianAiKit\\Voice\\Setup-Voice.bat once")
        detail = self.client.get(f"{self.base}{voice_id}/").json()
        self.assertEqual(detail["status"], "FAILED")
        self.assertIn("Setup-Voice.bat", detail["error"])

    # ------------------------------------------------------------------ narration
    def test_narration_routes_to_the_cloned_voice(self):
        voice = self.ready_voice()
        # not usable yet ⇒ cannot be chosen
        draft = ClonedVoice.objects.create(store=self.store, name="پیش‌نویس", person="x", consent_text="x",
                                           consent_at=timezone.now())
        r = self.client.patch(f"/api/v1/stores/{self.store.pk}/voice/",
                              {"profile": {"gender": "male", "rate": 0, "pitch": 0, "volume": 0, "cloned_voice": draft.pk}},
                              content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}{draft.pk}/use/", {"use": True},
                                          content_type="application/json").status_code, 409)

        r = self.client.post(f"{self.base}{voice.pk}/use/", {"use": True}, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["in_use"])
        provider = tts.get_tts_provider("fa", self.fresh_store())
        self.assertIsInstance(provider, vc.ClonedVoiceProvider)
        self.assertTrue(provider.is_local)
        # English narration keeps the normal chain (the cloned engine is Persian-only)
        self.assertNotIsInstance(tts.get_tts_provider("en", self.fresh_store()), vc.ClonedVoiceProvider)
        page = self.client.get(f"/api/v1/stores/{self.store.pk}/voice/").json()
        self.assertEqual(page["profile"]["cloned_voice"], voice.pk)
        self.assertIn("صدای علی", page["description"])
        self.assertEqual(page["speakers"]["fa"]["speakers"][0]["engine"], "clone")
        self.assertEqual(len(page["speakers"]["fa"]["speakers"]), 1, "a cloned voice has no fallback voices")

    def test_no_node_means_a_clear_error_not_another_voice(self):
        voice = self.ready_voice()
        vc.set_in_use(voice, True)
        provider = tts.get_tts_provider("fa", self.fresh_store())
        ComputeNode.objects.update(last_seen=timezone.now() - timedelta(hours=3))
        with self.assertRaises(tts.TTSError) as ctx:
            provider.synthesize("سلام", Path(TMP) / "out.mp3")
        self.assertIn("START.bat", str(ctx.exception))
        self.assertIn("صدای دیگری", str(ctx.exception))
        self.assertFalse(ComputeJob.objects.filter(kind="voice.tts").exists())

    def _wait_with_fake_node(self, plan):
        """compute.wait replaced by a node that answers each job per `plan` (list of callables job → None)."""
        real_wait = SV.wait
        calls = []

        def fake_wait(job, timeout_s=None, **kw):
            calls.append(job)
            plan[len(calls) - 1](job)
            return real_wait(job, 5, poll=0.01)
        return patch("apps.compute.services.wait", side_effect=fake_wait), calls

    def test_speech_job_payload_and_output(self):
        voice = self.ready_voice()
        vc.set_in_use(voice, True)
        provider = tts.get_tts_provider("fa", self.fresh_store())

        def speak(job):
            self.fake_node(job, {"speech.wav": wav_bytes(speechlike(2))}, meta={"engine": "voice:pocket", "check": 0.05})
        waiter, calls = self._wait_with_fake_node([speak, speak])
        with waiter:
            out = provider.synthesize("محصول تازه رسید", Path(TMP) / "scene" / "take1.mp3")
            out2 = provider.synthesize("محصول تازه رسید", Path(TMP) / "scene" / "take2.mp3")
        self.assertEqual(out.suffix, ".wav")
        self.assertTrue(out.is_file() and out2.is_file())
        job = calls[0]
        self.assertEqual(job.kind, "voice.tts")
        self.assertEqual(job.node_wanted, "DESKTOP-TEST")
        self.assertTrue(job.payload["clone"] and job.payload["strict"])
        self.assertEqual(job.payload["voice"], voice.node_voice_id)
        self.assertEqual(job.payload["rev"], 1)
        self.assertNotIn("restore", job.payload)
        self.assertNotIn("seed", job.payload)
        # the retake is a different take, not the cached first one
        self.assertIn("seed", calls[1].payload)
        self.assertNotEqual(calls[0].pk, calls[1].pk)

    def test_a_node_that_lost_the_voice_rebuilds_it_from_the_clips(self):
        voice = self.ready_voice()
        vc.set_in_use(voice, True)
        provider = tts.get_tts_provider("fa", self.fresh_store())

        def lost(job):
            self.fake_node(job, {}, ok=False, error="VoiceMissing: VOICE_MISSING: voice 'nm' is not on this node",
                           meta={"retryable": False})

        def restored(job):
            self.assertIn("restore", job.payload)
            self.assertTrue(job.payload["restore"]["consent"]["given"])
            self.assertTrue(job.inputs, "the restore job must carry the clips")
            self.fake_node(job, {"speech.wav": wav_bytes(speechlike(2))}, meta={"voice_id": "nm-restored"})
        waiter, calls = self._wait_with_fake_node([lost, restored])
        with waiter:
            out = provider.synthesize("سلام", Path(TMP) / "restore.mp3")
        self.assertTrue(out.is_file())
        self.assertEqual(len(calls), 2)
        voice.refresh_from_db()
        self.assertEqual(voice.node_voice_id, "nm-restored")

    def test_test_box_is_async(self):
        voice = self.ready_voice()
        r = self.client.post(f"{self.base}{voice.pk}/test/", {"text": "سفارش 1250 آماده است"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        uid = r.json()["job"]["uid"]
        self.assertNotIn("1250", r.json()["spoken_text"], "numbers are spoken as words, as in narration")
        status_url = f"{self.base}{voice.pk}/test/{uid}/"
        self.assertEqual(self.client.get(status_url).json()["job"]["state"], "QUEUED")
        job = ComputeJob.objects.get(uid=uid)
        self.fake_node(job, {"speech.wav": wav_bytes(speechlike(2))}, meta={"check": 0.1})
        state = self.client.get(status_url).json()["job"]
        self.assertEqual(state["state"], "COMPLETED")
        self.assertTrue(state["audio"])
        self.assertEqual(self.client.get(status_url + "audio/").status_code, 200)

    def test_delete_removes_everything_and_the_choice(self):
        voice = self.ready_voice()
        vc.set_in_use(voice, True)
        folder = vc.voice_dir(voice)
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.client.delete(f"{self.base}{voice.pk}/").status_code, 204)
        self.assertFalse(ClonedVoice.objects.filter(pk=voice.pk).exists())
        self.assertFalse(folder.exists())
        self.store.profile.refresh_from_db()
        self.assertNotIn("cloned_voice", self.store.profile.voice_profile)
        forget = ComputeJob.objects.get(kind="voice.http")
        self.assertEqual(forget.payload["method"], "DELETE")
        self.assertIn(voice.node_voice_id, forget.payload["path"])
        self.assertEqual(forget.node_wanted, "DESKTOP-TEST")
        # the shop narrates with its normal voice again
        self.assertNotIsInstance(tts.get_tts_provider("fa", self.fresh_store()), vc.ClonedVoiceProvider)

    def test_list_payload(self):
        self.ready_voice()
        data = self.client.get(self.base).json()
        self.assertGreaterEqual(len(data["script"]), 5)
        self.assertTrue(data["nodes"]["online"])
        self.assertIn("{person}", data["consent_template"])
        self.assertTrue(data["engine"]["commercial"], "new voices default to MOSS (Apache-2.0)")
        engines = {e["id"]: e for e in data["engines"]}
        self.assertFalse(engines["pocket"]["commercial"])
        self.assertEqual(engines["moss-fa"]["license"], "Apache-2.0")
        self.assertFalse(engines["moss-fa"]["ready"], "this test node has no MOSS models")
        self.assertEqual(data["voices"][0]["status"], "READY")


@override_settings(NM_DATA_DIR=Path(TMP), MEDIA_ROOT=TMP, IS_TEST=True)
class MossCloneTests(TestCase):
    """The commercially usable engine: the reference is made on the site and travels with every job."""

    def setUp(self):
        self.owner = User.objects.create_user("moss-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه موس")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/voice/clones/"
        self.node = ComputeNode.objects.create(name="GPU-MOSS", last_seen=timezone.now(), capabilities={
            "voice": True, "agent": "1.7", "audio": {"moss": True, "sfx": False, "music": False}})

    def voice_with_clips(self, n=4):
        r = self.client.post(self.base, {"name": "صدای مینا", "person": "مینا", "consent": True},
                             content_type="application/json")
        self.assertEqual(r.json()["engine"], "moss-fa")
        self.assertTrue(r.json()["commercial"])
        vid = r.json()["id"]
        for i in range(1, n + 1):
            self.client.post(f"{self.base}{vid}/clips/", {"index": i, "file": SimpleUploadedFile(
                "t.wav", wav_bytes(speechlike(3.5, seed=i)), content_type="audio/wav")})
        return ClonedVoice.objects.get(pk=vid)

    def test_build_sends_a_reference_and_consent(self):
        voice = self.voice_with_clips()
        r = self.client.post(f"{self.base}{voice.pk}/build/", {"consent": True}, content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        job = ComputeJob.objects.get(kind="voice.clone")
        self.assertEqual(job.payload["engine"], "moss-fa")
        self.assertEqual(job.node_wanted, "GPU-MOSS")
        self.assertEqual(list(job.inputs), ["moss_ref.wav"])
        self.assertTrue(job.payload["consent"]["given"])
        self.assertTrue(any(c["in_reference"] for c in job.payload["clips"]))
        ref = vc.moss_reference_path(voice)
        with wave.open(str(ref)) as w:
            seconds = w.getnframes() / w.getframerate()
            self.assertEqual((w.getframerate(), w.getnchannels()), (24000, 1))
        self.assertTrue(vc.MOSS_REF_MIN <= seconds <= vc.MOSS_REF_MAX + 1, seconds)
        claimed = SV.claim(self.node)
        SV.output_path(claimed, "clone.json").write_text(json.dumps({"ready": True, "voice_id": job.payload["name"],
                                                                       "engine": "moss-fa", "clips": []}))
        SV.output_path(claimed, "sample.wav").write_bytes(wav_bytes(speechlike(2)))
        SV.output_path(claimed, "ref.wav").write_bytes(ref.read_bytes())
        SV.finish(claimed, self.node, True)
        detail = self.client.get(f"{self.base}{voice.pk}/").json()
        self.assertEqual(detail["status"], "READY")
        self.assertEqual(detail["license"], "Apache-2.0")

    def test_speech_in_the_cloned_voice_carries_the_reference(self):
        voice = self.voice_with_clips()
        voice.status, voice.revision, voice.node_voice_id = "READY", 1, "nm-x"
        voice.save()
        job = vc.enqueue_tts(voice, "سلام")
        self.assertEqual(job.payload["engine"], "moss-fa")
        self.assertEqual(job.payload["reference"], "moss_ref.wav")
        self.assertEqual(list(job.inputs), ["moss_ref.wav"])
        self.assertEqual(job.node_wanted, "GPU-MOSS")

    def test_missing_models_and_old_agents_are_explained(self):
        voice = self.voice_with_clips()
        self.node.capabilities = {"voice": True, "agent": "1.7", "audio": {"moss": False}}
        self.node.save()
        r = self.client.post(f"{self.base}{voice.pk}/build/", {"consent": True}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("START.bat", r.json()["error"]["message"])
        self.node.capabilities = {"voice": True, "agent": "1.6"}
        self.node.save()
        r = self.client.post(f"{self.base}{voice.pk}/build/", {"consent": True}, content_type="application/json")
        self.assertIn("git pull", r.json()["error"]["message"])
        self.assertFalse(ComputeJob.objects.filter(kind="voice.clone").exists())

    def test_engine_can_be_switched(self):
        voice = self.voice_with_clips()
        r = self.client.patch(f"{self.base}{voice.pk}/", {"engine": "pocket"}, content_type="application/json")
        self.assertEqual(r.json()["license"], "CC-BY-NC-4.0")
        self.assertFalse(r.json()["commercial"])
