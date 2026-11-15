"""صدا: گفتارِ هر صحنه با زمانِ کلمه‌ها (ساختگیِ قطعی)، همگام‌سازیِ متنِ کینتیک/زیرنویس، برشِ روی بیت، افکتِ ساخته‌شده، مخلوطِ ‎-۱۴ LUFS و mux."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from . import sound, specs, timeline

FFMPEG = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
HAVE_FFMPEG = Path(FFMPEG).exists() or bool(shutil.which("ffmpeg"))


def tone(path: Path, seconds: float, freq=300, lead=0.0, tail=0.0) -> Path:
    """گفتارِ ساختگی: سکوت + تُن + سکوت (برای آزمونِ برشِ سکوت و مخلوط)."""
    flt = f"sine=frequency={freq}:duration={seconds}:sample_rate=48000,volume=0.5"
    if lead or tail:
        flt += f",adelay={int(lead * 1000)}|{int(lead * 1000)},apad=pad_dur={tail}"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", flt, "-ac", "1", str(path)], check=True, capture_output=True)
    return path


def plan(*scenes, **kw):
    s = {"style": "flat-vector", "aspect": "9:16", "platform": "reels", "scenes": list(scenes)}
    s.update(kw)
    return specs.normalize_spec(s)


class Text(SimpleTestCase):
    def test_auto_narration_uses_only_the_scenes_own_words(self):
        cases = [
            ({"type": "title", "duration": 4, "kicker": "معرفی", "title": "با چغر", "subtitle": "دستیار مربی‌ها"}, ["معرفی", "با چغر", "دستیار مربی‌ها"]),
            ({"type": "checklist", "duration": 6, "title": "چه دارد", "items": ["برنامه", "خروجی"]}, ["چه دارد", "برنامه", "خروجی"]),
            ({"type": "stat", "duration": 4, "value": "1300", "suffix": "+", "label": "حرکت"}, ["1300+", "حرکت"]),
            ({"type": "bar_chart", "duration": 6, "title": "مقایسه", "bars": [{"label": "الف", "value": 3}, {"label": "ب", "value": 5}]}, ["مقایسه", "الف", "ب"]),
            ({"type": "cta", "duration": 4, "title": "شروع کنید", "button": "ثبت‌نام"}, ["شروع کنید"]),
        ]
        for sc, words in cases:
            t = sound.auto_narration(specs.normalize_scene(sc, 0))
            for w in words:
                self.assertIn(w, t)

    def test_narration_texts_only_when_asked(self):
        p = plan({"type": "title", "duration": 4, "title": "سلام دنیا"})
        self.assertEqual(sound.narration_texts(p), [""])
        p = plan({"type": "title", "duration": 4, "title": "سلام دنیا"}, audio={"voice": {"on": True}})
        self.assertIn("سلام دنیا", sound.narration_texts(p)[0])
        p = plan({"type": "title", "duration": 4, "title": "سلام دنیا", "narration": "متنِ گفتار"})
        self.assertEqual(sound.narration_texts(p), ["متنِ گفتار"])

    def test_estimated_word_times_cover_the_speech_in_order(self):
        cues = sound.estimate_cues("برنامهٔ ورزشی شما، در چند ثانیه. بسیار ساده!", 4.0)
        self.assertEqual(len(cues), 8)
        self.assertEqual([c["w"] for c in cues][:2], ["برنامهٔ", "ورزشی"])
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["e"], b["s"] + 1e-6)
            self.assertLess(a["s"], a["e"])
        self.assertAlmostEqual(cues[-1]["e"], 4.0, delta=0.4)
        self.assertGreater(cues[3]["s"] - cues[2]["e"], 0)         # مکثِ بعد از «شما،»

    def test_estimate_follows_the_real_pauses_of_the_recording(self):
        text = "برنامهٔ ورزشی شما، در چند ثانیه. بسیار ساده!"
        # the recording has a long pause (2.0-2.6 s) where the full stop is, and no audible pause at the comma
        cues = sound.estimate_cues(text, 4.2, [(2.0, 2.6)])
        self.assertEqual(len(cues), 8)
        before = [c for c in cues if c["e"] <= 2.0 + 1e-6]
        after = [c for c in cues if c["s"] >= 2.6 - 1e-6]
        self.assertEqual(len(before) + len(after), 8, "no word may sit inside the pause")
        self.assertEqual([c["w"] for c in after], ["بسیار", "ساده"])
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["e"], b["s"] + 1e-6)
        self.assertAlmostEqual(cues[-1]["e"], 4.2, delta=0.4)
        # without usable pauses the plain proportional estimate is unchanged
        self.assertEqual(sound.estimate_cues(text, 4.0), sound.estimate_cues(text, 4.0, []))

    def test_more_pauses_than_punctuation_keeps_the_longest_and_fewer_matches_the_strongest(self):
        text = "الف ب، ج د. ه و"
        many = sound.estimate_cues(text, 6.0, [(0.5, 0.6), (2.0, 2.7), (4.0, 4.2)])
        self.assertEqual(len(many), 6)
        self.assertTrue(all(c["s"] < c["e"] for c in many))
        one = sound.estimate_cues(text, 6.0, [(3.0, 3.6)])          # one pause: it belongs to the full stop, not the comma
        self.assertEqual([c["w"] for c in one if c["s"] >= 3.6 - 1e-6], ["ه", "و"])

    def test_asr_words_are_laid_on_our_spelling(self):
        heard = [{"w": "برنامه", "s": 0.1, "e": 0.5}, {"w": "ورزشی", "s": 0.55, "e": 1.0}, {"w": "شما", "s": 1.1, "e": 1.4}]
        cues = sound.align_asr("برنامهٔ ورزشی شما", heard)
        self.assertEqual([c["w"] for c in cues], ["برنامهٔ", "ورزشی", "شما"])
        self.assertEqual(cues[1]["s"], 0.55)

    def test_word_cues_prefer_tts_then_asr_then_estimate(self):
        given = [{"w": "الف", "s": 0, "e": 0.3}]
        self.assertEqual(sound.word_cues("الف", Path("x.wav"), 1.0, given=given), (given, "tts"))
        cues, src = sound.word_cues("برنامه ورزشی", Path("x.wav"), 2.0, asr=lambda p: [{"w": "برنامه", "s": 0.1, "e": 0.6}, {"w": "ورزشی", "s": 0.7, "e": 1.3}])
        self.assertEqual(src, "asr")

        def off(path):
            raise RuntimeError("node is off")

        cues, src = sound.word_cues("برنامه ورزشی", Path("x.wav"), 2.0, asr=off)
        self.assertEqual(src, "estimate")
        self.assertEqual(len(cues), 2)


class Beats(SimpleTestCase):
    def test_cuts_land_on_the_beats_without_cutting_speech(self):
        p = plan({"type": "title", "duration": 3.1, "title": "الف"}, {"type": "cta", "duration": 3.2, "title": "ب"}, {"type": "cta", "duration": 3.3, "title": "ج"}, transition="cut")
        beats = [round(k * 0.5, 3) for k in range(0, 60)]              # 120 bpm
        out = sound.snap_durations(p, beats, [2.0, 2.0, 2.0])
        t = 0.0
        for i, d in enumerate(out[:-1]):
            t += d
            self.assertLess(min(abs(t - b) for b in beats), 0.04, (i, t))
        self.assertTrue(all(d >= m for d, m in zip(out, [2.0, 2.0, 2.0])))
        self.assertTrue(all(abs(d - o) <= sound.BEAT_TOLERANCE + 0.25 for d, o in zip(out, [3.1, 3.2, 3.3])))

    def test_speech_is_never_cut_even_if_the_beat_is_earlier(self):
        p = plan({"type": "title", "duration": 3.0, "title": "الف"}, {"type": "cta", "duration": 3.0, "title": "ب"}, transition="cut")
        out = sound.snap_durations(p, [0.0, 2.0, 4.0, 6.0], [4.6, 1.0])
        self.assertGreaterEqual(out[0], 4.6)

    def test_no_beats_keeps_the_durations(self):
        p = plan({"type": "title", "duration": 3.1, "title": "الف"}, {"type": "cta", "duration": 3.2, "title": "ب"})
        self.assertEqual(sound.snap_durations(p, [], [1, 1]), [3.1, 3.2])

    def test_a_regular_grid_fills_gaps_between_detected_onsets(self):
        got = sound.regular_beats([0.0, 0.5, 1.5], 120, 4.0)
        self.assertIn(1.0, got)
        self.assertIn(3.5, got)


class Sfx(SimpleTestCase):
    def test_every_kind_is_synthesised_here(self):
        import wave

        d = Path(tempfile.mkdtemp(prefix="nm-sfx-"))
        try:
            for kind in specs.SFX_KINDS:
                f = sound.synth_sfx(kind, d / f"{kind}.wav", -12.0)
                with wave.open(str(f)) as w:
                    self.assertEqual((w.getnchannels(), w.getframerate()), (2, 48000))
                    self.assertGreater(w.getnframes(), 1000)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_whoosh_goes_on_every_transition_when_sfx_is_on(self):
        p = plan({"type": "title", "duration": 3, "title": "الف"}, {"type": "cta", "duration": 3, "title": "ب"}, {"type": "cta", "duration": 3, "title": "ج"}, audio={"sfx": True})
        ev = sound.sfx_events(p, timeline.seconds(p)["starts"])
        self.assertEqual([e[1] for e in ev], ["whoosh", "whoosh"])
        off = plan({"type": "title", "duration": 3, "title": "الف"}, {"type": "cta", "duration": 3, "title": "ب"})
        self.assertEqual(sound.sfx_events(off, [0, 3]), [])


class RealPauses(SimpleTestCase):
    def test_inner_pauses_are_found_in_a_real_recording(self):
        ff = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        if not Path(ff).exists():
            self.skipTest("ffmpeg missing")
        d = Path(tempfile.mkdtemp(prefix="nm-pauses-"))
        try:
            wav = d / "t.wav"
            graph = "sine=f=300:d=0.8,apad=pad_dur=0.5[a];sine=f=330:d=0.8[b];[a][b]concat=n=2:v=0:a=1"
            subprocess.run([ff, "-y", "-loglevel", "error", "-filter_complex", graph, "-ar", "16000", str(wav)], check=True, capture_output=True)
            got = sound.inner_pauses(wav)
            self.assertEqual(len(got), 1, got)
            self.assertAlmostEqual(got[0][0], 0.8, delta=0.12)
            self.assertAlmostEqual(got[0][1], 1.3, delta=0.12)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Real(SimpleTestCase):
    """ffmpeg واقعی: برشِ سکوت، مخلوطِ کامل و بلندی، mux."""

    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg is not on this machine")
        self.work = Path(tempfile.mkdtemp(prefix="nm-sound-"))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_silence_around_the_speech_is_trimmed(self):
        raw = tone(self.work / "raw.wav", 1.0, lead=0.6, tail=0.7)
        s, e = sound.speech_bounds(raw)
        self.assertAlmostEqual(s, 0.6, delta=0.12)
        self.assertAlmostEqual(e, 1.6, delta=0.15)
        clip = sound.cut_clip(raw, self.work / "c.wav", s, e)
        self.assertAlmostEqual(sound.duration_of(clip), e - s, delta=0.1)

    def test_prepare_stretches_scenes_syncs_words_and_masters_at_minus_14_lufs(self):
        p = plan({"type": "kinetic_title", "duration": 2, "text": "برنامهٔ ورزشی شما در چند ثانیه", "narration": "برنامهٔ ورزشی شما در چند ثانیه"},
                 {"type": "cta", "duration": 3, "title": "همین حالا شروع کنید", "button": "ثبت‌نام", "narration": "همین حالا شروع کنید"},
                 audio={"voice": {"on": True}, "music": {"on": True, "ref": "auto"}, "sfx": True, "beat_sync": True})
        n = {"i": 0}

        def synth(text, voice_id, name):
            n["i"] += 1
            return {"path": tone(self.work / f"v{n['i']}.wav", 3.2, lead=0.2, tail=0.2), "engine": "fake", "voice": "fake:v"}

        music = tone(self.work / "m.wav", 30, freq=180)
        res = sound.prepare(None, None, p, self.work / "out", synth=synth, asr=lambda path: (_ for _ in ()).throw(RuntimeError("off")),
                            music_fn=lambda ref, secs: (music, {"ref": "audio:1", "title": "t", "license": "CC0"}),
                            beats_fn=lambda path: {"beats": [round(k * 0.5, 3) for k in range(60)], "bpm": 120.0})
        spec = res["spec"]
        self.assertGreaterEqual(spec["scenes"][0]["duration"], sound.LEAD + 3.2 + sound.TAIL - 0.5)      # the speech is not cut
        for sc in spec["scenes"]:
            self.assertTrue(sc["cues"])
            self.assertGreaterEqual(sc["cues"][0]["s"], sound.LEAD)
            self.assertLessEqual(sc["cues"][-1]["e"], sc["duration"])
        self.assertEqual(res["info"]["voice"]["cue_source"], "estimate")
        self.assertTrue(res["info"]["beat_sync"])
        mix = res["mix"]
        self.assertTrue(mix.is_file())
        stats = res["info"]["mix"]
        self.assertTrue(-15.6 <= stats["lufs"] <= -12.4, stats)
        self.assertLessEqual(stats["true_peak"], -0.9)
        self.assertAlmostEqual(stats["seconds"], timeline.total_seconds(spec), delta=0.6)

    def test_music_is_ducked_under_the_voice(self):
        voice = tone(self.work / "v.wav", 2.0, freq=500)
        music = tone(self.work / "m.wav", 8.0, freq=200)
        out = self.work / "mix.m4a"
        sound.build_mix(self.work, 8.0, [(str(voice), 1.0)], [], {"path": music, "level_db": -14}, out)

        def level_200hz(a, b):
            import re

            p = subprocess.run([FFMPEG, "-hide_banner", "-ss", str(a), "-t", str(b - a), "-i", str(out), "-af", "bandpass=f=200:width_type=h:w=60,volumedetect", "-f", "null", "-"],
                               capture_output=True, text=True)
            return float(re.search(r"mean_volume: (-?[\d.]+) dB", p.stderr).group(1))

        # the 200 Hz bed is quieter while the 500 Hz voice speaks (1-3 s) than after it stopped (5-7 s): the voice itself ducks the music
        self.assertGreater(level_200hz(5.0, 7.0), level_200hz(1.4, 2.6) + 3)

    def test_mux_puts_the_sound_under_a_silent_video(self):
        video = self.work / "v.mp4"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x126F85:s=320x568:d=3:r=30", "-pix_fmt", "yuv420p", str(video)], check=True)
        audio = self.work / "a.m4a"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=3", "-c:a", "aac", str(audio)], check=True)
        self.assertFalse(sound.has_audio(video))
        out = sound.mux(video, audio, self.work / "o.mp4")
        self.assertTrue(sound.has_audio(out))
        self.assertAlmostEqual(sound.duration_of(out), 3.0, delta=0.15)

    def test_an_empty_request_is_not_a_crash(self):
        with self.assertRaises(sound.SoundError):
            sound.build_mix(self.work, 3.0, [], [], None, self.work / "x.m4a")
