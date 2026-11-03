"""Waveform / filmstrip / beats / speech spans (services/editing/media_cache.py) on tiny synthetic media with the real
ffmpeg: known sines and silences for the waveform, a 120 bpm click track for the beats, tone bursts for the speech spans,
testsrc2 for the filmstrip — plus the cache itself (hits, invalidation, concurrency, cleanup)."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from services.editing import media_cache as mc
from services.editing.errors import TimelineError
from services.video.ffmpeg import FFMPEG

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg")) and np is not None


def write_wav(path, samples, sr=22050):
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return path


def tone(seconds, amp, freq=440, sr=22050):
    t = np.arange(int(seconds * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def silence(seconds, sr=22050):
    return np.zeros(int(seconds * sr))


def click_track(path, bpm, seconds, sr=22050, first=0.25):
    out = np.zeros(int(seconds * sr))
    period = 60.0 / bpm
    rng = np.random.default_rng(7)
    t = first
    truth = []
    while t < seconds - 0.05:
        i = int(t * sr)
        n = int(0.02 * sr)
        burst = rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / (0.004 * sr)) * 0.9
        out[i:i + n] += burst
        truth.append(t)
        t += period
    write_wav(path, out, sr)
    return truth


def sh(*args):
    subprocess.run(list(args), check=True, capture_output=True, stdin=subprocess.DEVNULL)


class CacheTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE_FFMPEG:
            return
        cls.root = Path(tempfile.mkdtemp(prefix="nm-mc-"))
        cls.override = override_settings(MEDIA_ROOT=str(cls.root / "media"))
        cls.override.enable()

    @classmethod
    def tearDownClass(cls):
        if HAVE_FFMPEG:
            cls.override.disable()
            shutil.rmtree(cls.root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg یا numpy نیست")
        mc._cleanup_at = time.monotonic()             # no housekeeping in the middle of an assertion


class WaveformTests(CacheTestCase):
    def test_known_sine_and_silence_gaps(self):
        wav = write_wav(self.root / "w.wav", np.concatenate([tone(1, 0.5), silence(1), tone(1, 0.25)]))
        result = mc.waveform(wav, per_second=20)
        self.assertAlmostEqual(result["duration"], 3.0, delta=0.1)
        self.assertAlmostEqual(result["per_second"], 20.0, delta=0.5)
        peaks, ps = result["peaks"], result["per_second"]
        self.assertAlmostEqual(len(peaks), 3 * ps, delta=3)
        self.assertTrue(all(0.0 <= p <= 1.0 for p in peaks))
        loud = max(peaks[: int(0.9 * ps)])
        quiet = max(peaks[int(2.1 * ps):])
        gap = max(peaks[int(1.15 * ps): int(1.85 * ps)])
        self.assertAlmostEqual(loud, 0.5, delta=0.06)
        self.assertAlmostEqual(quiet, 0.25, delta=0.04)
        self.assertLess(gap, 0.02, "the silent second is flat")
        self.assertEqual(max(peaks[: int(0.9 * ps)]), loud)

    def test_max_bins_lowers_the_resolution_and_a_second_call_is_a_cache_hit(self):
        wav = write_wav(self.root / "w2.wav", tone(4, 0.6))
        small = mc.waveform(wav, per_second=25, max_bins=40)
        self.assertLessEqual(len(small["peaks"]), 40)
        self.assertAlmostEqual(small["per_second"], 10.0, delta=1.0)
        files = list(mc.cache_dir().glob("*.wave.json"))
        self.assertTrue(files)
        before = {f: f.stat().st_mtime_ns for f in files}
        with patch.object(mc, "_pcm", side_effect=AssertionError("must come from the cache")):
            again = mc.waveform(wav, per_second=25, max_bins=40)
        self.assertEqual(again, small)
        self.assertEqual({f: f.stat().st_mtime_ns for f in mc.cache_dir().glob("*.wave.json") if f in before}.keys(), before.keys())

    def test_a_changed_file_gets_a_new_entry(self):
        wav = self.root / "w3.wav"
        write_wav(wav, tone(2, 0.8))
        first = mc.waveform(wav)
        time.sleep(0.02)
        write_wav(wav, tone(2, 0.2))
        os.utime(wav, (time.time() + 5, time.time() + 5))
        second = mc.waveform(wav)
        self.assertGreater(max(first["peaks"]), 0.7)
        self.assertLess(max(second["peaks"]), 0.3)

    def test_no_audio_or_missing_file_is_a_persian_error(self):
        silent = self.root / "novideo_audio.mp4"
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=10:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent))
        for call in (mc.waveform, mc.beats, mc.speech_spans):
            with self.assertRaises(TimelineError) as ctx:
                call(silent)
            self.assertIn("صدا", str(ctx.exception))
        with self.assertRaises(TimelineError):
            mc.waveform(self.root / "nope.wav")

    def test_four_threads_decode_once(self):
        wav = write_wav(self.root / "w4.wav", tone(3, 0.5))
        results, errors = [], []
        real = mc._pcm
        calls = []

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)

        def work():
            try:
                results.append(mc.waveform(wav, per_second=30))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with patch.object(mc, "_pcm", side_effect=counting):
            threads = [threading.Thread(target=work) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len(calls), 1, "the per-key lock makes the other three wait for the cache")


class FilmstripTests(CacheTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE_FFMPEG:
            return
        cls.clip = cls.root / "strip.mp4"
        sh(FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=6", "-f", "lavfi",
           "-i", "sine=frequency=330:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "15", "-c:a", "aac",
           "-shortest", str(cls.clip))
        cls.audio_only = write_wav(cls.root / "a.wav", tone(2, 0.3))
        from PIL import Image
        cls.png = cls.root / "still.png"
        Image.new("RGB", (120, 80), (200, 40, 40)).save(cls.png)

    def test_sprite_count_interval_size_and_the_thumbs_differ_over_time(self):
        from PIL import Image

        s = mc.filmstrip(self.clip, height=40, max_thumbs=4, min_interval=1.0)
        self.assertEqual(s["count"], 4)
        self.assertAlmostEqual(s["interval"], 1.5, places=2)
        self.assertEqual(s["h"], 40)
        self.assertEqual(s["w"] % 2, 0)
        self.assertAlmostEqual(s["w"], 71, delta=2)             # 320x180 scaled to 40 px high
        self.assertAlmostEqual(s["duration"], 6.0, delta=0.2)
        self.assertTrue(Path(s["file"]).is_file())
        self.assertLess(Path(s["file"]).stat().st_size, 80_000)
        img = Image.open(s["file"])
        self.assertEqual(img.size, (s["count"] * s["w"], s["h"]))
        first = np.asarray(img.crop((0, 0, s["w"], s["h"])), dtype=float)
        last = np.asarray(img.crop(((s["count"] - 1) * s["w"], 0, s["count"] * s["w"], s["h"])), dtype=float)
        self.assertGreater(float(np.abs(first - last).mean()), 8.0, "testsrc2 changes over time")
        self.assertGreater(float(first.std()), 10.0, "a real picture, not grey")

    def test_min_interval_limits_the_count_and_a_second_call_hits_the_cache(self):
        s = mc.filmstrip(self.clip, height=32, max_thumbs=48, min_interval=2.0)
        self.assertEqual(s["count"], 3)
        self.assertAlmostEqual(s["interval"], 2.0, places=2)
        with patch.object(mc, "_thumb", side_effect=AssertionError("must come from the cache")):
            again = mc.filmstrip(self.clip, height=32, max_thumbs=48, min_interval=2.0)
        self.assertEqual(again["file"], s["file"])
        self.assertEqual((again["count"], again["w"]), (s["count"], s["w"]))

    def test_a_still_image_gives_one_thumbnail_and_audio_only_is_refused(self):
        s = mc.filmstrip(self.png, height=30)
        self.assertEqual(s["count"], 1)
        self.assertEqual(s["h"], 30)
        with self.assertRaises(TimelineError) as ctx:
            mc.filmstrip(self.audio_only)
        self.assertIn("تصویر", str(ctx.exception))


class BeatsTests(CacheTestCase):
    def check_clicks(self, bpm, seconds, tolerance):
        wav = self.root / f"clicks_{bpm}.wav"
        truth = click_track(wav, bpm, seconds)
        result = mc.beats(wav)
        found = result["beats"]
        self.assertAlmostEqual(result["duration"], seconds, delta=0.1)
        self.assertEqual(found, sorted(found))
        matched = sum(1 for t in truth if any(abs(t - b) < 0.06 for b in found))
        self.assertGreaterEqual(matched, int(len(truth) * 0.9), f"{matched}/{len(truth)} clicks found: {found}")
        self.assertLessEqual(len(found), len(truth) + 2, "no flood of false beats")
        self.assertIsNotNone(result["bpm"])
        self.assertAlmostEqual(result["bpm"], bpm, delta=tolerance)
        return result

    def test_120_bpm_click_track(self):
        self.check_clicks(120, 10, 3)

    def test_90_bpm_click_track(self):
        self.check_clicks(90, 12, 4)

    def test_silence_has_no_beats_and_no_tempo(self):
        wav = write_wav(self.root / "quiet.wav", silence(5))
        result = mc.beats(wav)
        self.assertEqual(result["beats"], [])
        self.assertIsNone(result["bpm"])

    def test_max_beats_keeps_the_strongest_and_the_result_is_cached(self):
        wav = self.root / "clicks_cap.wav"
        click_track(wav, 120, 10)
        capped = mc.beats(wav, max_beats=5)
        self.assertEqual(len(capped["beats"]), 5)
        self.assertEqual(capped["beats"], sorted(capped["beats"]))
        with patch.object(mc, "_pcm", side_effect=AssertionError("must come from the cache")):
            self.assertEqual(mc.beats(wav, max_beats=5), capped)


class SpeechSpanTests(CacheTestCase):
    def test_spans_bridge_short_pauses_and_drop_blips(self):
        wav = write_wav(self.root / "speech.wav", np.concatenate([
            silence(0.5), tone(1.0, 0.5), silence(1.0), tone(0.7, 0.5), silence(0.2), tone(0.6, 0.5),
            silence(0.4), tone(0.15, 0.5), silence(0.6)]))
        spans = mc.speech_spans(wav)
        self.assertEqual(len(spans), 2, spans)
        self.assertAlmostEqual(spans[0][0], 0.5, delta=0.15)
        self.assertAlmostEqual(spans[0][1], 1.5, delta=0.15)
        self.assertAlmostEqual(spans[1][0], 2.5, delta=0.15)
        self.assertAlmostEqual(spans[1][1], 4.0, delta=0.2)
        self.assertTrue(all(s < e for s, e in spans))
        loose = mc.speech_spans(wav, min_len=0.1)
        self.assertEqual(len(loose), 3, "the 0.15 s blip counts when min_len allows it")
        stricter = mc.speech_spans(wav, min_gap=1.2)
        self.assertEqual(len(stricter), 1, "a longer min_gap bridges the one-second pause too")

    def test_silent_file_has_no_spans_and_continuous_sound_is_one_span(self):
        self.assertEqual(mc.speech_spans(write_wav(self.root / "s0.wav", silence(2))), [])
        spans = mc.speech_spans(write_wav(self.root / "s1.wav", tone(3, 0.5)))
        self.assertEqual(len(spans), 1)
        self.assertAlmostEqual(spans[0][0], 0.0, delta=0.1)
        self.assertAlmostEqual(spans[0][1], 3.0, delta=0.1)


class CleanupTests(CacheTestCase):
    def test_oldest_go_first_and_recent_entries_stay(self):
        folder = mc.cache_dir()
        for p in folder.iterdir():
            p.unlink()
        now = time.time()
        for name, age_days, size in (("old.json", 30, 10), ("a.bin", 5, 4000), ("b.bin", 3, 4000), ("c.bin", 1, 4000),
                                     ("stale.tmp", 0.5, 10)):
            f = folder / name
            f.write_bytes(b"x" * size)
            os.utime(f, (now - age_days * 86400, now - age_days * 86400))
        report = mc.cleanup(max_bytes=9000, max_age_days=14)
        names = sorted(p.name for p in folder.iterdir())
        self.assertNotIn("old.json", names, "older than max_age")
        self.assertNotIn("a.bin", names, "the oldest of the rest goes first")
        self.assertIn("c.bin", names)
        self.assertIn("b.bin", names)
        self.assertEqual(report["removed"], 3)
        self.assertLessEqual(report["bytes"], 9000)
        mc.cleanup(max_bytes=1, max_age_days=14)
        self.assertEqual([p.name for p in folder.iterdir()], [], "nothing fits in one byte")

    def test_cache_dir_lives_under_media_root_and_a_hit_refreshes_the_entry(self):
        self.assertEqual(mc.cache_dir().parts[-3:], ("generated", "editing", "cache"), mc.cache_dir())
        wav = write_wav(self.root / "touch.wav", tone(1, 0.4))
        mc.waveform(wav)
        entry = next(mc.cache_dir().glob("*.wave.json"))
        os.utime(entry, (time.time() - 5 * 86400,) * 2)
        mc.waveform(wav)
        self.assertGreater(entry.stat().st_mtime, time.time() - 60, "a cache hit counts as use")
