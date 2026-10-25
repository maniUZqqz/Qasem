"""«صدا»: speech / effects / music generation, the shop's library, node routing, MOSS as a narrator and a scene
sound source, and the background mix under a finished video (with real ffmpeg).

The processing node is faked in-process (claim → write outputs → finish), as in the compute and clone tests.
"""
import io
import json
import shutil
import subprocess
import tempfile
import wave
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai.models import AudioAsset, AudioEngine, ClonedVoice, SoundClip
from apps.compute import services as SV
from apps.compute.models import ComputeJob, ComputeNode
from apps.content.models import VideoScript
from apps.products.models import Product
from apps.stores.models import Store
from services.audio import node_audio, studio, tts

TMP = tempfile.mkdtemp(prefix="nm-audio-studio-")


def wav_bytes(seconds=2.0, sr=24000, freq=220.0):
    t = np.arange(int(seconds * sr)) / sr
    a = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((a * 32767).astype("<i2").tobytes())
    return buf.getvalue()


AUDIO_ALL = {"moss": True, "sfx": True, "music": True}


@override_settings(NM_DATA_DIR=Path(TMP), MEDIA_ROOT=TMP, IS_TEST=True, CELERY_TASK_ALWAYS_EAGER=True)
class AudioStudioTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.owner = User.objects.create_user("audio-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه صدا")
        self.client.force_login(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/audio/"
        self.node = ComputeNode.objects.create(name="GPU-1", last_seen=timezone.now(),
                                               capabilities={"voice": True, "agent": "1.7", "audio": dict(AUDIO_ALL)})

    # ------------------------------------------------------------------ helpers
    def post(self, **body):
        return self.client.post(self.base + "assets/", body, content_type="application/json")

    def complete(self, job, name="speech.wav", seconds=2.0, ok=True, error=""):
        claimed = SV.claim(self.node)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, job.pk)
        if ok:
            SV.output_path(job, name).write_bytes(wav_bytes(seconds))
        SV.finish(job, self.node, ok, error, {"retryable": False} if not ok else {})

    def set_audio(self, **audio):
        caps = dict(self.node.capabilities)
        caps["audio"] = {**AUDIO_ALL, **audio}
        self.node.capabilities = caps
        self.node.save()

    # ------------------------------------------------------------------ overview / routing
    def test_overview(self):
        data = self.client.get(self.base).json()
        self.assertTrue(data["status"]["engines"]["moss"]["ready"])
        self.assertEqual(data["status"]["engines"]["music"]["license"], "MIT")
        ids = [v["id"] for v in data["voices"]]
        self.assertIn("moss:mana", ids)
        self.assertIn("moss:lora", ids)
        self.assertNotIn("moss:sara", ids, "Pocket's CC-BY-NC sample voices are never a MOSS reference")
        edge = next(v for v in data["voices"] if v["engine"] == "edge")
        self.assertFalse(edge["commercial"])
        self.assertTrue(any(s["key"] == "rain" for s in data["sfx_presets"]))
        self.assertTrue(data["music_styles"])

    def test_node_messages(self):
        self.set_audio(sfx=False)
        msg = self.client.get(self.base).json()["status"]["engines"]["sfx"]["message"]
        self.assertIn("«دانلود»", msg)  # the owner presses a button; no command line
        r = self.post(kind="sfx", preset="rain", seconds=5)
        self.assertEqual(r.status_code, 503)
        self.assertFalse(AudioAsset.objects.exists(), "nothing is stored for a job no node can run")
        self.node.capabilities = {"voice": True, "agent": "1.6"}
        self.node.save()
        self.assertIn("git pull", node_audio.status()["engines"]["music"]["message"])
        ComputeNode.objects.update(last_seen=timezone.now() - timedelta(hours=2))
        self.assertIn("START.bat", node_audio.status()["engines"]["moss"]["message"])

    # ------------------------------------------------------------------ speech
    def test_moss_speech_end_to_end(self):
        r = self.post(kind="speech", text="سفارش 1250 آماده است", voice="moss:arash", speed=1.0)
        self.assertEqual(r.status_code, 201, r.content)
        a = r.json()
        self.assertEqual(a["status"], "PENDING")
        self.assertTrue(a["commercial"])
        job = ComputeJob.objects.get(kind="voice.tts")
        self.assertEqual(job.payload["engine"], "moss-fa")
        self.assertEqual(job.payload["voice"], "arash")
        self.assertEqual(job.node_wanted, "GPU-1")
        self.assertNotIn("1250", job.payload["text"], "numbers spoken as words, as in narration")
        self.complete(job)
        a = self.client.get(f"{self.base}assets/{a['id']}/").json()
        self.assertEqual(a["status"], "READY")
        self.assertTrue(a["has_file"])
        self.assertGreater(a["duration"], 1.5)
        f = self.client.get(f"{self.base}assets/{a['id']}/file/?download=1")
        self.assertEqual(f.status_code, 200)
        self.assertIn("attachment", f["Content-Disposition"])
        # keep it, then delete it (the file goes too)
        self.assertTrue(self.client.patch(f"{self.base}assets/{a['id']}/", {"saved": True},
                                          content_type="application/json").json()["saved"])
        path = studio.asset_path(AudioAsset.objects.get(pk=a["id"]))
        self.assertEqual(self.client.delete(f"{self.base}assets/{a['id']}/").status_code, 204)
        self.assertFalse(path.exists())

    def test_failed_node_job_is_reported(self):
        a = self.post(kind="speech", text="سلام", voice="moss:mana").json()
        job = ComputeJob.objects.get(kind="voice.tts")
        job.max_attempts = 1
        job.save()
        self.complete(job, ok=False, error="JobError: MODELS_MISSING: x | مدل‌های «MOSS» روی این سرور نصب نیست.")
        a = self.client.get(f"{self.base}assets/{a['id']}/").json()
        self.assertEqual(a["status"], "FAILED")
        self.assertIn("نصب نیست", a["error"])

    def test_piper_speech_is_immediate_and_deduplicated(self):
        def fake(self_, text, out_path):
            out = Path(out_path).with_suffix(".wav")
            out.write_bytes(wav_bytes(1.0, 22050))
            return out
        with patch("services.audio.tts.PiperProvider.synthesize", fake):
            a = self.post(kind="speech", text="سلام دوستان", voice="piper:fa_IR-gyro-medium", speed=1.1).json()
            self.assertEqual(a["status"], "READY")
            b = self.post(kind="speech", text="سلام دوستان", voice="piper:fa_IR-gyro-medium", speed=1.1).json()
        self.assertEqual(a["id"], b["id"], "the same request reuses the same take")

    def test_edge_respects_the_data_policy(self):
        from apps.ai.models import StoreAIPolicy

        StoreAIPolicy.objects.update_or_create(store=self.store, defaults={"mode": "LOCAL_ONLY"})
        r = self.post(kind="speech", text="سلام", voice="edge:fa-IR-FaridNeural")
        self.assertEqual(r.status_code, 409)

    def test_cloned_voice_speech(self):
        voice = ClonedVoice.objects.create(store=self.store, name="صدای من", person="من", consent_text="x",
                                           consent_at=timezone.now(), engine="moss-fa", status="READY", revision=1,
                                           node_voice_id="nm-s-v")
        from services.audio import voice_clone as vc

        ref = vc.moss_reference_path(voice)
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_bytes(wav_bytes(10))
        a = self.post(kind="speech", text="سلام", voice=f"clone:{voice.pk}").json()
        self.assertEqual(a["license"], "Apache-2.0")
        job = ComputeJob.objects.get(kind="voice.tts")
        self.assertEqual(job.payload["reference"], "moss_ref.wav")

    # ------------------------------------------------------------------ effects / music
    def test_sfx_from_a_preset_and_a_persian_description(self):
        a = self.post(kind="sfx", preset="rain", seconds=45).json()
        job = ComputeJob.objects.get(kind="voice.sfx")
        self.assertIn("rain", job.payload["prompt"])
        self.assertEqual(job.payload["seconds"], 30.0)
        self.complete(job, "sfx.wav", 3)
        self.assertEqual(self.client.get(f"{self.base}assets/{a['id']}/").json()["status"], "READY")
        with patch("services.audio.studio.to_english", return_value="footsteps on a wooden floor"):
            self.post(kind="sfx", description="صدای قدم روی چوب", seconds=4)
        self.assertEqual(ComputeJob.objects.filter(kind="voice.sfx").order_by("-id")[0].payload["prompt"],
                         "footsteps on a wooden floor")

    def test_translation_refuses_rather_than_guesses(self):
        with patch("apps.ai.services.recorded_json_call", side_effect=RuntimeError("no model")):
            with self.assertRaises(studio.StudioError):
                studio.to_english("صدای باران", self.store, "sfx")
        self.assertEqual(studio.to_english("rain on a roof", self.store, "sfx"), "rain on a roof")

    def test_music_style(self):
        a = self.post(kind="music", style="persian", seconds=500).json()
        job = ComputeJob.objects.get(kind="voice.music")
        self.assertIn("santur", job.payload["prompt"])
        self.assertIn("instrumental", job.payload["prompt"].lower())
        self.assertEqual(job.payload["seconds"], studio.MUSIC_MAX)
        self.assertEqual(job.payload["bpm"], 90)
        self.assertEqual(a["license"], "MIT (ACE-Step)")
        self.assertEqual(self.post(kind="music").status_code, 400)

    @override_settings(NM_AUDIO_DAILY_SECONDS=40)
    def test_daily_allowance(self):
        self.assertEqual(self.post(kind="music", style="calm", seconds=30).status_code, 201)
        r = self.post(kind="music", style="calm", seconds=30)
        self.assertEqual(r.status_code, 429)
        self.assertIn("سقفِ روزانه", r.json()["error"]["message"])

    # ------------------------------------------------------------------ library
    def test_library_scoping_and_draft_sweep(self):
        a = self.post(kind="sfx", preset="cafe", seconds=5).json()
        AudioAsset.objects.filter(pk=a["id"]).update(created_at=timezone.now() - timedelta(days=2))
        kept = self.post(kind="sfx", preset="city", seconds=5, save=True).json()
        AudioAsset.objects.filter(pk=kept["id"]).update(created_at=timezone.now() - timedelta(days=2))
        ids = [x["id"] for x in self.client.get(self.base + "assets/").json()["assets"]]
        self.assertNotIn(a["id"], ids, "an unsaved draft is swept after a day")
        self.assertIn(kept["id"], ids)
        other = User.objects.create_user("stranger", password="x")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"{self.base}assets/{kept['id']}/").status_code, 404)

    # ------------------------------------------------------------------ narration + scene sounds
    def test_moss_narrates_with_the_profiles_preset(self):
        profile = self.store.profile
        profile.voice_profile = {"gender": "male", "preset": "kaveh"}
        profile.save()
        provider = tts.get_tts_provider("fa", Store.objects.get(pk=self.store.pk))
        first = provider.providers[0] if hasattr(provider, "providers") else provider
        self.assertIsInstance(first, node_audio.NodeMossProvider)
        self.assertEqual(first.voice, "kaveh")
        self.assertTrue(first.is_local)
        en = tts.get_tts_provider("en", Store.objects.get(pk=self.store.pk))
        chain = en.providers if hasattr(en, "providers") else [en]
        self.assertFalse(any(isinstance(p, node_audio.NodeMossProvider) for p in chain), "MOSS is Persian-only")

        real_wait = SV.wait

        def fake_wait(job, timeout_s=None, **kw):
            self.complete(job)
            return real_wait(job, 5, poll=0.01)
        with patch("apps.compute.services.wait", side_effect=fake_wait):
            out = first.synthesize("سلام", Path(TMP) / "n" / "take.mp3")
        self.assertTrue(out.is_file())
        ComputeNode.objects.update(last_seen=timezone.now() - timedelta(hours=1))
        chain = tts.get_tts_provider("fa", Store.objects.get(pk=self.store.pk))
        names = [p.name for p in getattr(chain, "providers", [chain])]
        self.assertNotIn("moss", names, "with the node off MOSS is skipped and Edge/Piper read")

    def test_scene_sound_from_moss_joins_the_library(self):
        from services.audio import soundscape

        AudioEngine.objects.filter(role="SOUND").exclude(kind="NODE_SFX").update(is_active=False)
        real_wait = SV.wait

        def fake_wait(job, timeout_s=None, **kw):
            self.complete(job, "sfx.wav", 6)
            return real_wait(job, 5, poll=0.01)
        work = Path(TMP) / "scape"
        work.mkdir(parents=True, exist_ok=True)
        with patch("apps.compute.services.wait", side_effect=fake_wait):
            picked = soundscape.pick("rain", seconds=8, seed="x", work=work)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.engine, "MOSS-SoundEffect")
        self.assertTrue(SoundClip.objects.filter(category="rain", origin="MOSS", licence="Apache-2.0").exists())

    # ------------------------------------------------------------------ under a finished video (real ffmpeg)
    def test_video_background_mix(self):
        from services.video.ffmpeg import FFMPEG

        product = Product.objects.create(store=self.store, name="کفش", price=1000)
        video = Path(TMP) / "src.mp4"
        subprocess.run([str(FFMPEG), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=3",
                        "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-shortest", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True)
        script = VideoScript.objects.create(store=self.store, product=product, concept="x")
        from services.media import files as media

        rel = Path(TMP) / "generated" / "videos" / "voiced.mp4"
        rel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(video, rel)
        script.final_video_voiced.name = "generated/videos/voiced.mp4"
        script.save()
        music = self.post(kind="music", style="calm", seconds=10).json()
        self.complete(ComputeJob.objects.get(kind="voice.music"), "music.wav", 5)
        amb = self.post(kind="sfx", preset="rain", seconds=4).json()
        self.complete(ComputeJob.objects.get(kind="voice.sfx"), "sfx.wav", 4)
        url = f"/api/v1/stores/{self.store.pk}/video-scripts/{script.pk}/sound-mix/"
        r = self.client.post(url, {"music_asset": music["id"], "music_level_db": -18, "ambience_asset": amb["id"],
                                   "ambience_level_db": -60, "mix": True}, content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        state = self.client.get(url).json()
        self.assertEqual(state["music_asset"], music["id"])
        self.assertEqual(state["ambience"]["level_db"], -40.0, "levels are clamped to a safe range")
        self.assertTrue(state["video"], "the mixed cut exists")
        script.refresh_from_db()
        from services.video.ffmpeg import probe

        with media.reading(script.final_video_music) as path:
            streams = [s["codec_type"] for s in probe(path)["streams"]]
        self.assertIn("audio", streams)
        self.assertIn("video", streams)
        used = AudioAsset.objects.get(pk=music["id"])
        self.assertTrue(used.saved)
        self.assertEqual(used.used_in[0]["as"], "music")
        r = self.client.post(url, {"ambience_asset": None, "music_asset": None}, content_type="application/json")
        self.assertIsNone(r.json()["ambience"])
