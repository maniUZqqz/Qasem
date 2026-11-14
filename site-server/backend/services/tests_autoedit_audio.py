"""«خروجی همزمان پخش می‌شود و صداها روی هم می‌افتند» — the regression tests of the overlapping-sound bug (1405/08/22).

What the owner heard had four independent causes, each pinned here with a REAL ffmpeg render of a tiny project and a referee that
listens to the file (`services.editing.audioqc`):

1. the export did not duck music under a person on camera (the preview did) → music on top of the voice;
2. the export defaulted ducking OFF when the project said nothing (the preview defaulted it ON);
3. a picture clip's own sound AND a detached/duplicated copy of it played together → the same speech twice;
4. a voice-over played over the original speaker at full level → two people talking at once.

(The before/after player of the panel playing both videos aloud is the fifth, covered by the frontend test.)
"""
import atexit
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from django.test import SimpleTestCase
from scipy import signal

from services.editing import audioqc, audiofx, compose, export
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG

HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))
TEMP = Path(tempfile.mkdtemp(prefix="nm-autoedit-audio-"))
atexit.register(shutil.rmtree, TEMP, ignore_errors=True)          # the module makes its folder at import: never leave it behind
SR = 32000


def synth_speech(seconds=10.0, sr=SR, seed=1, amp=0.3, start=0.0):
    """Speech-like test signal: syllables of a harmonic source with a wandering pitch through formant resonators (no two syllables
    alike, so — like real speech — it does not correlate with itself at short lags)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    out = np.zeros(n, dtype=np.float64)
    t = float(start)
    while t < seconds - 0.4:
        dur = float(rng.uniform(0.12, 0.34))
        i0, i1 = int(t * sr), min(n, int((t + dur) * sr))
        m = i1 - i0
        if m < 64:
            break
        f0 = rng.uniform(95, 230)
        ff = f0 * (1 + rng.uniform(-0.25, 0.25) * np.linspace(0, 1, m))
        phase = 2 * np.pi * np.cumsum(ff) / sr
        src = np.zeros(m)
        for h in range(1, 28):
            if h * f0 * 1.3 > 4200:
                break
            src += np.sin(h * phase + rng.uniform(0, 6.28)) / h
        src += 0.15 * rng.standard_normal(m)
        y = np.zeros(m)
        for fc, bw in ((rng.uniform(300, 800), 90), (rng.uniform(900, 2300), 140), (rng.uniform(2500, 3400), 200)):
            b, a = signal.iirpeak(fc / (sr / 2), fc / bw)
            y += signal.lfilter(b, a, src)
        out[i0:i1] += y * np.hanning(m)
        t += dur + float(rng.uniform(0.02, 0.22))
    out /= (np.max(np.abs(out)) + 1e-9)
    return (out * amp).astype(np.float32)


def tone(freq, seconds, amp=0.3, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def noise_band(lo, hi, seconds, amp=0.3, sr=SR, seed=4):
    """A band of noise — a 'music bed' that, unlike a pure tone, is not periodic (so it cannot pose as a repeating signal)."""
    rng = np.random.default_rng(seed)
    b, a = signal.butter(4, [lo / (sr / 2), hi / (sr / 2)], btype="band")
    y = signal.lfilter(b, a, rng.standard_normal(int(seconds * sr)))
    return (amp * y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def write_wav(path: Path, x: np.ndarray, sr=SR) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def mux(path: Path, wav: Path, seconds: float) -> Path:
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x335577:s=320x180:r=12:d={seconds}", "-i", str(wav),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def band_db(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    e = float(spec[(f >= lo) & (f <= hi)].sum()) / len(x) + 1e-12      # per second of signal: windows of different length compare
    return 10 * np.log10(e)


def clip(cid, ref, at, end, *, video=True, volume=1.0, kind=None, **extra):
    return {"id": cid, "type": "media", "ref": ref, "label": ref, "kind": kind or ("video" if video else "audio"), "at": at, "start": 0, "end": end,
            "src": end, "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1, "volume": volume, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0,
            "audio_on": True, "has_audio": True, "effects": [], "transition": None, **extra}


def project(video_clips, audio_tracks, **top):
    tracks = [{"id": "v1", "kind": "video", "name": "v", "clips": video_clips}]
    for i, (role, clips) in enumerate(audio_tracks):
        tracks.append({"id": f"a{i}", "kind": "audio", "name": role or "a", "role": role, "clips": clips})
    return {"format": {"width": 320, "height": 180, "fps": 12, "preset": "reel"}, "tracks": tracks, "global_ops": [], **top}


def build(data, files):
    def resolve(ref):
        if ref not in files:
            raise tl.TimelineError("ref")
        path, kind, dur = files[ref]
        return {"path": str(path), "kind": kind, "has_audio": True, "duration": dur, "width": 320, "height": 180}
    return tl.from_project(data, resolve)


def render(timeline, name, spans=None):
    out = TEMP / name
    export.render(timeline, out, quality="draft", spans=spans)
    return out


def samples(path, sr=SR):
    return audioqc.decode(path, sr=sr)


class RefereeTests(SimpleTestCase):
    """The detector must hear an echo when there is one, and stay quiet on clean speech."""

    def test_it_flags_the_same_speech_a_little_late_and_not_clean_speech(self):
        x = synth_speech(20, 16000, seed=3)
        self.assertFalse(audioqc.echo_report(x, 16000)["doubled"])
        for lag, gain in ((0.08, 1.0), (0.12, 0.5), (0.35, 0.5), (0.9, 1.0)):
            d = int(lag * 16000)
            y = x.copy()
            y[d:] += gain * x[:-d]
            report = audioqc.echo_report(y, 16000)
            self.assertTrue(report["doubled"], (lag, gain, report))
            self.assertAlmostEqual(report["lag_s"], lag, delta=0.012)

    def test_two_different_talkers_are_not_an_echo(self):
        a, b = synth_speech(20, 16000, seed=3), synth_speech(20, 16000, seed=9)
        self.assertFalse(audioqc.echo_report(a + b, 16000)["doubled"])

    def test_silence_and_short_files_are_not_judged(self):
        self.assertFalse(audioqc.echo_report(np.zeros(16000 * 10, dtype=np.float32), 16000)["doubled"])
        self.assertFalse(audioqc.echo_report(np.ones(100, dtype=np.float32), 16000)["doubled"])

    def test_out_of_phase_channels_are_reported(self):
        x = synth_speech(4, 16000, seed=2)
        self.assertTrue(audioqc.channel_report(x, -x)["out_of_phase"])
        self.assertFalse(audioqc.channel_report(x, x)["out_of_phase"])


class GraphTests(SimpleTestCase):
    """Structure of the filtergraph (no encode): who is heard, who is dropped, who is ducked."""

    def files(self):
        return {"v": ("/a.mp4", "video", 6.0), "m": ("/m.wav", "audio", 6.0), "vo": ("/vo.wav", "audio", 3.0)}

    def graph(self, data):
        return compose.build_graph(build(data, self.files()), need_base=True, spans=lambda p: [[0.0, 5.5]])

    def test_music_is_ducked_under_a_person_on_camera_when_the_project_says_nothing(self):
        data = project([clip("c1", "v", 0, 6)], [("music", [clip("m1", "m", 0, 6, video=False, volume=0.4)])])
        self.assertNotIn("ducking", data)
        g = self.graph(data)
        self.assertIn("volume=eval=frame", g.graph, "the music bus must carry the duck curve")
        self.assertTrue(build(data, self.files()).ducking["on"])

    def test_an_explicit_off_is_obeyed(self):
        data = project([clip("c1", "v", 0, 6)], [("music", [clip("m1", "m", 0, 6, video=False)])], ducking={"on": False})
        self.assertNotIn("volume=eval=frame", self.graph(data).graph)

    def test_a_speech_track_still_ducks_the_music(self):
        data = project([{**clip("c1", "v", 0, 6), "has_audio": False, "audio_on": False}],
                       [("speech", [clip("s1", "vo", 0, 3, video=False)]), ("music", [clip("m1", "m", 0, 6, video=False)])])
        self.assertIn("volume=eval=frame", self.graph(data).graph)

    def test_the_picture_sound_and_its_detached_copy_play_once(self):
        data = project([clip("c1", "v", 0, 6)], [("speech", [clip("d1", "v", 0.12, 6, video=False)])])
        g = self.graph(data)
        self.assertEqual(g.graph.count("adelay="), 1, "the source's sound must be taken ONCE")
        self.assertTrue(any("عیناً همان گفتار" in n for n in g.notes), g.notes)

    def test_a_different_part_of_the_same_file_is_not_a_duplicate(self):
        c1 = clip("c1", "v", 0, 3)
        c2 = {**clip("d1", "v", 0, 3, video=False), "start": 20.0, "end": 23.0, "src": 30}
        files = {"v": ("/a.mp4", "video", 30.0)}
        t = build(project([c1], [("speech", [c2])]), files)
        self.assertEqual(audiofx.duplicate_carriers(t), {})

    def test_music_layered_on_purpose_is_never_dropped(self):
        t = build(project([{**clip("c1", "v", 0, 6), "has_audio": False, "audio_on": False}],
                          [("music", [clip("m1", "m", 0, 6, video=False)]), ("music", [clip("m2", "m", 1, 6, video=False)])]), self.files())
        self.assertEqual(audiofx.duplicate_carriers(t), {})

    def test_a_voice_over_dips_the_speaker_under_it_and_can_be_switched_off(self):
        data = project([clip("c1", "v", 0, 6)], [("speech", [clip("o1", "vo", 1, 3, video=False)])])
        g = self.graph(data)
        self.assertTrue(any("زیرِ گویندگی" in n for n in g.notes), g.notes)
        off = project([clip("c1", "v", 0, 6)], [("speech", [clip("o1", "vo", 1, 3, video=False)])], ducking={"on": True, "voiceover": False})
        self.assertFalse(any("زیرِ گویندگی" in n for n in self.graph(off).notes))


class RenderTests(SimpleTestCase):
    """Real ffmpeg on tiny clips, judged by listening to the output."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE:
            return
        cls.speech = write_wav(TEMP / "speech.wav", synth_speech(10, seed=5))
        cls.speech_mp4 = mux(TEMP / "speech.mp4", cls.speech, 10)
        cls.hf = write_wav(TEMP / "hf.wav", noise_band(6700, 7300, 10))     # a music bed above the synthetic voice's band
        cls.speaker_tone = write_wav(TEMP / "tone5k.wav", tone(5000, 10, 0.3))
        cls.tone_mp4 = mux(TEMP / "tone5k.mp4", cls.speaker_tone, 10)

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")

    def test_music_sinks_under_the_speaker_in_the_exported_file(self):
        """Speech 2–6 s of a 10 s clip; a 7 kHz 'music' bed all along.  By default the bed must drop ≈ 12 dB while the person speaks."""
        sp = synth_speech(10, seed=5)
        sp[: 2 * SR] = 0
        sp[6 * SR:] = 0
        speech_wav = write_wav(TEMP / "speech_2_6.wav", sp)
        video = mux(TEMP / "speech_2_6.mp4", speech_wav, 10)
        files = {"v": (video, "video", 10.0), "m": (self.hf, "audio", 10.0)}
        data = project([clip("c1", "v", 0, 10)], [("music", [clip("m1", "m", 0, 10, video=False)])])
        out = render(build(data, files), "ducked.mp4", spans=lambda p: [[2.0, 6.0]])
        x = samples(out)
        quiet = band_db(x[int(0.4 * SR): int(1.6 * SR)], SR, 6920, 7080)
        loud = band_db(x[int(3.0 * SR): int(5.0 * SR)], SR, 6920, 7080)
        self.assertLess(loud, quiet - 8.0, f"music while the person speaks should be well under the open level: {loud:.1f} vs {quiet:.1f}")
        self.assertTrue(audioqc.analyze(out)["clean"], audioqc.analyze(out)["problems"])

    def test_no_ducking_key_and_ducking_off_really_differ(self):
        sp = synth_speech(10, seed=5)
        sp[: 2 * SR] = 0
        sp[6 * SR:] = 0
        video = mux(TEMP / "speech_b.mp4", write_wav(TEMP / "speech_b.wav", sp), 10)
        files = {"v": (video, "video", 10.0), "m": (self.hf, "audio", 10.0)}
        off = project([clip("c1", "v", 0, 10)], [("music", [clip("m1", "m", 0, 10, video=False)])], ducking={"on": False})
        x = samples(render(build(off, files), "not_ducked.mp4", spans=lambda p: [[2.0, 6.0]]))
        quiet = band_db(x[int(0.4 * SR): int(1.6 * SR)], SR, 6920, 7080)
        loud = band_db(x[int(3.0 * SR): int(5.0 * SR)], SR, 6920, 7080)
        self.assertAlmostEqual(loud, quiet, delta=3.0)

    def test_a_detached_copy_does_not_make_the_speech_play_twice(self):
        files = {"v": (self.speech_mp4, "video", 10.0)}
        data = project([clip("c1", "v", 0, 10)], [("speech", [clip("d1", "v", 0.12, 10, video=False)])])
        out = render(build(data, files), "dup_removed.mp4")
        report = audioqc.analyze(out)
        self.assertFalse(report["echo"]["doubled"], report)
        self.assertTrue(report["clean"], report["problems"])

    def test_the_referee_would_have_caught_the_old_mix(self):
        """The same two clips mixed WITHOUT the de-duplication (what the old export did) are heard as a double: proves the test above bites."""
        out = TEMP / "old_mix.m4a"
        cmd = [FFMPEG, "-y", "-v", "error", "-i", str(self.speech_mp4), "-i", str(self.speech_mp4), "-filter_complex",
               "[1:a]adelay=120|120[b];[0:a][b]amix=inputs=2:normalize=0[o]", "-map", "[o]", str(out)]
        subprocess.run(cmd, check=True, capture_output=True)
        self.assertTrue(audioqc.analyze(out)["echo"]["doubled"])

    def test_a_voice_over_does_not_talk_over_the_speaker(self):
        """The person on camera is a 5 kHz tone; the narrator is speech placed at 1–7 s.  While the narrator speaks the 5 kHz must dip hard."""
        vo_path = write_wav(TEMP / "vo_6s.wav", synth_speech(6, seed=11))
        files = {"v": (self.tone_mp4, "video", 10.0), "vo": (vo_path, "audio", 6.0)}
        data = project([clip("c1", "v", 0, 10)], [("speech", [clip("o1", "vo", 1, 6, video=False)])])
        x = samples(render(build(data, files), "vo_dip.mp4"))
        open_level = band_db(x[int(8.0 * SR): int(9.5 * SR)], SR, 4920, 5080)
        under = band_db(x[int(3.0 * SR): int(5.0 * SR)], SR, 4920, 5080)
        self.assertLess(under, open_level - 9.0, f"{under:.1f} vs {open_level:.1f}")


class PeakCeilingTests(SimpleTestCase):
    """«صدا به سقف رسیده و می‌شکند» on the owner's own video (1405/08/23): the loudness step lifted the file to -14.7 LUFS but the DECODED file peaked
    at +0.27 dBFS with clipped samples - the limiter before the AAC encoder did not hold after encoding.  The delivered file must hold the
    true-peak ceiling when it is DECODED, and the QC verdict must go by that peak."""

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")

    def hot_mp4(self, name, seconds=12, push=1.8):
        """Speech at the very top of full scale (like a loudness-lifted mix): an AAC encode of it overshoots full scale when decoded."""
        x = np.clip(synth_speech(seconds, seed=21, amp=1.0) * push * 1.0, -1.0, 1.0)
        return mux(TEMP / f"{name}.mp4", write_wav(TEMP / f"{name}.wav", x), seconds)

    def test_the_master_limiter_has_real_headroom_for_the_aac_overshoot(self):
        from services.editing import audiofx

        self.assertGreaterEqual(audiofx.AAC_HEADROOM_DB, 1.0)
        self.assertEqual(audioqc.AAC_HEADROOM_DB, audiofx.AAC_HEADROOM_DB)           # one number for the graph and the settle step

    def test_a_file_that_clips_when_decoded_is_brought_under_the_ceiling(self):
        path = self.hot_mp4("hot_for_ceiling")
        before = audioqc.loudness_stats(path)
        self.assertIsNotNone(before)
        self.assertGreater(before["tp"], 0.0, f"the fixture must overshoot full scale like the owner's file: {before}")
        self.assertFalse(audioqc.quick_check(path)["clean"] and before["tp"] > -0.1, "the QC must call a file over the ceiling a problem")
        rep = audioqc.settle_loudness(path, target=-14.0, tp=-1.0)
        after = audioqc.loudness_stats(path)
        self.assertTrue(rep["adjusted"], rep)
        self.assertLessEqual(after["tp"], -0.8, f"decoded true peak after settling: {after} ({rep})")
        self.assertEqual(rep["tp"], after["tp"])
        qc = audioqc.quick_check(path)
        self.assertTrue(qc["clean"], qc["problems"])
        self.assertLessEqual(qc["peak_db"], -0.8)

    def test_the_quick_check_goes_by_the_true_peak_of_the_decoded_file(self):
        path = self.hot_mp4("hot_for_qc")
        stats = audioqc.loudness_stats(path)
        qc = audioqc.quick_check(path)
        self.assertAlmostEqual(qc["peak_db"], stats["tp"], delta=0.05)
        self.assertEqual(qc["true_peak_db"], qc["peak_db"])
        if stats["tp"] > -0.1:
            self.assertFalse(qc["clean"])
            self.assertIn("صدا به سقف رسیده و می‌شکند", qc["problems"])

    def test_peaks_only_mode_fixes_a_clipping_file_and_leaves_a_clean_one_alone(self):
        hot = self.hot_mp4("hot_peaks_only")
        lufs_before = audioqc.loudness_stats(hot)["lufs"]
        rep = audioqc.settle_loudness(hot, target=None, tp=-1.0)
        self.assertTrue(rep["adjusted"], rep)
        self.assertLessEqual(audioqc.loudness_stats(hot)["tp"], -0.8)
        self.assertLessEqual(audioqc.loudness_stats(hot)["lufs"], lufs_before + 0.3)       # loudness is not asked for: it never goes UP
        calm = mux(TEMP / "calm_peaks_only.mp4", write_wav(TEMP / "calm_peaks_only.wav", synth_speech(10, seed=5, amp=0.3)), 10)
        stamp = calm.stat().st_mtime_ns
        rep = audioqc.settle_loudness(calm, target=None, tp=-1.0)
        self.assertFalse(rep.get("adjusted"), rep)
        self.assertEqual(calm.stat().st_mtime_ns, stamp)

    def test_a_render_with_the_loudness_master_holds_the_ceiling_after_settling(self):
        """The whole chain on a real render: loud speech through the export graph (loudnorm + limiter), then the settle step on the file."""
        wav = write_wav(TEMP / "speech_for_chain.wav", synth_speech(10, seed=31, amp=0.9))
        files = {"v": (mux(TEMP / "speech_for_chain.mp4", wav, 10), "video", 10.0)}
        data = project([clip("c1", "v", 0, 10)], [])
        data["master"] = {"gain_db": 0, "limiter": True, "loudness": {"on": True, "target": -14, "tp": -1}}
        out = render(build(data, files), "chain_ceiling.mp4")
        audioqc.settle_loudness(out, target=-14.0, tp=-1.0)
        qc = audioqc.quick_check(out)
        self.assertTrue(qc["clean"], qc["problems"])
        self.assertLessEqual(audioqc.loudness_stats(out)["tp"], -0.8)


class LoudnessSettleTests(SimpleTestCase):
    """The delivered file really sits at the requested loudness (-14 LUFS for social), not only "the filter was asked for"."""

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg is not installed")

    def quiet_mp4(self, name, amp):
        wav = write_wav(TEMP / f"{name}.wav", synth_speech(12, seed=7, amp=amp))
        return mux(TEMP / f"{name}.mp4", wav, 12)

    def test_a_quiet_file_is_brought_to_the_target_and_stays_under_the_peak_ceiling(self):
        path = self.quiet_mp4("quiet_for_loudness", 0.15)
        before = audioqc.loudness_lufs(path)
        self.assertLess(before, -22.0)
        rep = audioqc.settle_loudness(path, target=-14.0, tp=-1.0)
        self.assertTrue(rep["adjusted"], rep)
        after = audioqc.loudness_lufs(path)
        self.assertAlmostEqual(after, -14.0, delta=1.5, msg=f"{before} -> {after} ({rep})")
        self.assertLessEqual(audioqc.peak_db(audioqc.decode(path)), -0.5)
        probe = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True)
        self.assertEqual(probe.returncode, 0, "the touched file still decodes")

    def test_a_file_already_on_target_is_left_alone(self):
        path = self.quiet_mp4("on_target", 0.15)
        for _ in range(3):                                   # converges (the peak limiter can make the last 0.5 LU take a second pass)
            audioqc.settle_loudness(path, target=-14.0)
        stamp = path.stat().st_mtime_ns
        rep = audioqc.settle_loudness(path, target=-14.0)
        self.assertFalse(rep["adjusted"], rep)
        self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_nothing_to_measure_is_not_an_error(self):
        self.assertEqual(audioqc.settle_loudness(TEMP / "does_not_exist.mp4"), {})
