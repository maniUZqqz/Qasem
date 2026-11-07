"""Parametric EQ, detailed compressor, pitch shift and echo of a clip's sound: the project JSON is clamped by the timeline cleaner, becomes
the right ffmpeg filters, and — measured on a real tone — really changes the sound the way the panel promises."""
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase

from services.editing import audiofx
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG

HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


def clean(audio):
    return tl._clean_extras({"audio": audio})["audio"]


def run_chain(filters, source):
    """Decode `source` through the filter chain to mono float samples at 48 kHz."""
    cmd = [FFMPEG, "-v", "error", *source, "-af", ",".join(filters) if filters else "anull", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, dtype=np.float32)


def tone(freq, seconds=1.0):
    return ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=48000"]


def rms_db(x):
    return 20 * np.log10(max(1e-9, float(np.sqrt(np.mean(np.square(x))))))


def dominant_hz(x, sr=48000):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spec) * sr / len(x))


class CleanerTests(SimpleTestCase):
    def test_neutral_settings_leave_the_project_exactly_as_before(self):
        self.assertEqual(clean({}), {})
        self.assertEqual(clean({"bands": [{"f": 1000, "g": 0}], "pitch": 0, "echo": {"on": False}, "cdetail": {"on": False}}), {})
        self.assertEqual(clean({"comp": 0.4}), {"comp": 0.4})

    def test_every_number_is_clamped_and_extras_are_dropped(self):
        a = clean({
            "bands": [{"f": 5, "g": 99, "q": 0}, {"f": 99999, "g": -99, "q": 99}, {"f": 1000, "g": 3}, "junk", {"f": 200, "g": 2}, {"f": 300, "g": 2}, {"f": 400, "g": 2}],
            "cdetail": {"on": True, "thr": -99, "ratio": 99, "attack": 0, "release": 99999, "makeup": 99},
            "pitch": 99, "echo": {"on": True, "delay": 1, "decay": 5}, "evil": "rm -rf"})
        self.assertEqual(len(a["bands"]), 5)                                    # at most five bands, junk skipped
        self.assertEqual((a["bands"][0]["f"], a["bands"][0]["g"], a["bands"][0]["q"]), (20.0, 18.0, 0.2))
        self.assertEqual((a["bands"][1]["f"], a["bands"][1]["g"], a["bands"][1]["q"]), (20000.0, -18.0, 10.0))
        self.assertEqual(a["cdetail"], {"on": True, "thr": -40.0, "ratio": 20.0, "attack": 1, "release": 2000, "makeup": 24.0})
        self.assertEqual(a["pitch"], 12.0)
        self.assertEqual(a["echo"], {"on": True, "delay": 20, "decay": 0.9})
        self.assertNotIn("evil", a)

    def test_garbage_types_do_not_crash(self):
        a = clean({"bands": "x", "cdetail": 3, "pitch": "high", "echo": [1]})
        self.assertEqual(a, {})


class ChainTests(SimpleTestCase):
    def test_the_filters_come_in_a_sensible_order(self):
        audio = clean({"eq": "voice", "bands": [{"f": 1000, "g": 6, "q": 1}], "comp": 0.5, "cdetail": {"on": True, "thr": -20, "ratio": 4, "attack": 10, "release": 200, "makeup": 3},
                       "pitch": 3, "echo": {"on": True, "delay": 300, "decay": 0.4}, "normalize": True})
        chain = audiofx.fx_chain(audio)
        text = "|".join(chain)
        for needle in ("equalizer=f=1000.0:t=q:w=1.00:g=6.0", "acompressor=threshold=0.1000:ratio=4.0:attack=10:release=200:makeup=1.41", "asetrate=", "aecho=0.8:0.88:300:0.40", "loudnorm"):
            self.assertIn(needle, text)
        order = [text.index(x) for x in ("equalizer=f=1000.0", "acompressor=threshold=0.1000", "asetrate", "aecho", "loudnorm")]
        self.assertEqual(order, sorted(order))
        self.assertLess(text.index("highpass"), text.index("equalizer=f=1000.0"))           # the preset first, then the bands

    def test_no_new_settings_means_the_old_chain_byte_for_byte(self):
        self.assertEqual(audiofx.fx_chain({"eq": "warm", "comp": 0.3, "normalize": True}),
                         audiofx.EQ_CHAINS["warm"] + ["acompressor=threshold=0.190:ratio=3.8:attack=20:release=250:makeup=1.60", "loudnorm=I=-16:TP=-1.5:LRA=11"])


class MeasuredTests(SimpleTestCase):
    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")

    def test_a_band_boosts_its_own_frequency_only(self):
        flat = run_chain([], tone(1000))
        boosted = run_chain(audiofx.fx_chain(clean({"bands": [{"f": 1000, "g": 12, "q": 1}]})), tone(1000))
        elsewhere = run_chain(audiofx.fx_chain(clean({"bands": [{"f": 1000, "g": 12, "q": 1}]})), tone(100))
        flat100 = run_chain([], tone(100))
        self.assertAlmostEqual(rms_db(boosted) - rms_db(flat), 12.0, delta=1.5)
        self.assertLess(abs(rms_db(elsewhere) - rms_db(flat100)), 1.0)
        cut = run_chain(audiofx.fx_chain(clean({"bands": [{"f": 1000, "g": -12, "q": 1}]})), tone(1000))
        self.assertAlmostEqual(rms_db(cut) - rms_db(flat), -12.0, delta=1.5)

    def test_the_compressor_squeezes_loud_sound_and_makeup_gain_brings_it_back(self):
        loud = tone(440)
        flat = run_chain([], loud)
        squeezed = run_chain(audiofx.fx_chain(clean({"cdetail": {"on": True, "thr": -30, "ratio": 10, "attack": 1, "release": 100, "makeup": 0}})), loud)
        self.assertLess(rms_db(squeezed), rms_db(flat) - 6)
        restored = run_chain(audiofx.fx_chain(clean({"cdetail": {"on": True, "thr": -30, "ratio": 10, "attack": 1, "release": 100, "makeup": 12}})), loud)
        self.assertGreater(rms_db(restored), rms_db(squeezed) + 8)

    def test_pitch_moves_the_note_without_changing_the_length(self):
        base = run_chain([], tone(440, 1.0))
        up = run_chain(audiofx.fx_chain(clean({"pitch": 12})), tone(440, 1.0))
        down = run_chain(audiofx.fx_chain(clean({"pitch": -12})), tone(440, 1.0))
        self.assertAlmostEqual(dominant_hz(base), 440, delta=3)
        self.assertAlmostEqual(dominant_hz(up), 880, delta=6)
        self.assertAlmostEqual(dominant_hz(down), 220, delta=6)
        self.assertAlmostEqual(len(up) / 48000, len(base) / 48000, delta=0.1)
        self.assertAlmostEqual(len(down) / 48000, len(base) / 48000, delta=0.1)
        fifth = run_chain(audiofx.fx_chain(clean({"pitch": 7})), tone(440, 1.0))
        self.assertAlmostEqual(dominant_hz(fifth), 440 * 2 ** (7 / 12), delta=6)

    def test_echo_repeats_a_short_burst_after_its_delay(self):
        burst = ["-f", "lavfi", "-i", "sine=frequency=800:duration=0.15:sample_rate=48000,apad=whole_dur=1.2", "-t", "1.2"]
        cmd = [FFMPEG, "-v", "error", *burst, "-af", ",".join(audiofx.fx_chain(clean({"echo": {"on": True, "delay": 400, "decay": 0.6}}))), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]
        raw = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
        self.assertEqual(raw.returncode, 0, raw.stderr[-200:])
        x = np.frombuffer(raw.stdout, dtype=np.float32)
        window = lambda a, b: rms_db(x[int(a * 48000):int(b * 48000)])
        self.assertGreater(window(0.42, 0.52), window(0.70, 0.80) + 10)         # the repeat sits at ~400 ms, nothing after it but its own tail
        self.assertGreater(window(0.42, 0.52), -45)
