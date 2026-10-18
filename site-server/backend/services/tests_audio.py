"""The audio engine: how a name is said, and whether the result is listenable.

Two halves, and the split is the point.

`lexicon` is about what the voice is *asked* to say. Its bugs are silent — the
audio comes out fine, it just says the wrong thing — so the tests here are about
exact strings.

`qc` is about what came back. Every waveform below is built in Python rather
than rendered, which means each test contains exactly one defect and nothing
else: the choppy clip differs from the clean one only in the holes punched in
it. A recorded fixture would carry a dozen properties at once and could never
prove which one moved the score.
"""
import array
import math
import random
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from services.audio import lexicon, narration, qc

RATE = 16_000


def speech(seconds=4.0, level=6000, tail_silence=0.4, dropouts=0, seed=1):
    """A speech-like envelope: syllables with ordinary pauses between them.

    `dropouts` punches holes in the *middle* of loud syllables, which is what a
    decoder dropping frames does and what an inter-word pause never does.
    """
    rnd = random.Random(seed)
    out = array.array("h")
    elapsed = 0.0
    while elapsed < seconds - tail_silence:
        length = int(RATE * 0.18)
        amplitude = level * rnd.uniform(0.6, 1.0)
        for i in range(length):
            value = (
                amplitude
                * math.sin(2 * math.pi * 180 * i / RATE)
                * math.sin(math.pi * i / length)
            )
            out.append(int(max(-32768, min(32767, value))))
        elapsed += 0.18
        out.extend([0] * int(RATE * 0.05))  # normal inter-syllable pause
        elapsed += 0.05
    out.extend([0] * int(RATE * max(0.0, seconds - elapsed)))

    for index in range(dropouts):
        start = int(RATE * (0.09 + index * 0.23))
        for i in range(start, min(start + int(RATE * 0.03), len(out))):
            out[i] = 0
    return out


SENTENCE = "این کفش چرم طبیعی است و دو سال ضمانت دارد"


def scores(samples, text=SENTENCE) -> dict:
    return {a.name: a.score for a in qc.measure(samples, RATE, text=text)}


# --------------------------------------------------------------- lexicon


class PronunciationTests(SimpleTestCase):
    def test_a_brand_is_said_not_spelled(self):
        self.assertIn("نایکی", lexicon.apply("کفش Nike اصل"))

    def test_the_written_form_is_left_alone(self):
        """The caption still says Nike. Only the narration is rewritten, and
        conflating the two would corrupt the shop's own copy."""
        original = "کفش Nike اصل"
        lexicon.apply(original)
        self.assertEqual(original, "کفش Nike اصل")

    def test_a_longer_entry_wins(self):
        table = {"Galaxy": "گلکسی", "Galaxy Watch": "گلکسی واچ"}
        with patch.object(lexicon, "COMMON_BRANDS", table):
            spoken = lexicon.apply("Galaxy Watch جدید")
        self.assertIn("گلکسی واچ", spoken)
        self.assertNotIn("Watch", spoken)

    def test_a_brand_inside_a_longer_word_is_not_touched(self):
        with patch.object(lexicon, "COMMON_BRANDS", {"Nik": "نیک"}):
            self.assertNotIn("نیک", lexicon.apply("Nike"))

    def test_a_price_is_read_as_a_quantity(self):
        """Digit-by-digit is the failure that ruins a sales video."""
        self.assertIn("دویست و پنجاه هزار", lexicon.apply("۲۵۰۰۰۰ تومان"))

    def test_persian_and_arabic_digits_both_work(self):
        self.assertEqual(
            lexicon.spell_numbers_in("۱۲۰۰۰"), lexicon.spell_numbers_in("١٢٠٠٠"),
        )

    def test_separators_do_not_break_a_price(self):
        self.assertEqual(
            lexicon.spell_numbers_in("1,250,000"), lexicon.spell_number(1_250_000),
        )

    def test_a_short_number_is_left_alone(self):
        """A model number like 250 is already read correctly, and rewriting it
        only adds a chance of being wrong."""
        self.assertEqual(lexicon.spell_numbers_in("مدل 250"), "مدل 250")

    def test_numbers_across_every_scale(self):
        cases = {
            0: "صفر",
            15: "پانزده",
            100: "صد",
            1_000: "یک هزار",
            25_000: "بیست و پنج هزار",
            1_250_000: "یک میلیون و دویست و پنجاه هزار",
            2_000_000_000: "دو میلیارد",
        }
        for number, expected in cases.items():
            self.assertEqual(lexicon.spell_number(number), expected, number)

    def test_words_we_cannot_say_are_reported_not_guessed(self):
        """A transliteration engine inventing a pronunciation it has never seen
        is worse than asking the one person who knows."""
        unknown = lexicon.unresolved_latin("Nike و Hoka")
        self.assertEqual(unknown, ["Hoka"])

    def test_a_word_is_reported_once_however_often_it_appears(self):
        self.assertEqual(lexicon.unresolved_latin("Hoka Hoka HOKA"), ["Hoka"])


class StorePronunciationTests(TestCase):
    def setUp(self):
        from apps.stores.models import Store

        owner = User.objects.create_user("lex-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه تلفظ")

    def test_the_shop_overrules_us(self):
        """They know how they say their own brand name and we do not."""
        self.store.profile.pronunciations = {"Nike": "نایک"}
        self.store.profile.save()
        self.assertIn("نایک ", lexicon.apply("Nike اصل", self.store) + " ")

    def test_a_shop_with_no_entries_still_gets_ours(self):
        self.assertIn("سامسونگ", lexicon.apply("Samsung", self.store))

    def test_rubbish_in_the_field_does_not_break_narration(self):
        self.store.profile.pronunciations = ["not", "a", "dict"]
        self.store.profile.save()
        self.assertIn("نایکی", lexicon.apply("Nike", self.store))


# -------------------------------------------------------------------- QC


class AudibilityTests(SimpleTestCase):
    def test_a_silent_file_scores_zero_and_says_why(self):
        """The engine produced a file and no speech — the failure that would
        otherwise ship as a video with a silent gap in it."""
        axes = qc.measure(array.array("h", [0] * RATE * 3), RATE)
        self.assertEqual(axes[0].name, qc.AUDIBLE)
        self.assertEqual(axes[0].score, 0.0)

    def test_silence_stops_the_report_there(self):
        """Scoring the pace of silence would be arithmetic about nothing."""
        self.assertEqual(len(qc.measure(array.array("h", [0] * RATE), RATE)), 1)

    def test_quiet_speech_is_not_called_silence(self):
        """It is a real clip a gain filter fixes. Calling it inaudible sends it
        back to the voice engine, which returns exactly the same quiet audio."""
        result = scores(speech(level=300))
        self.assertEqual(result[qc.AUDIBLE], 100.0)
        self.assertLess(result[qc.LEVEL], 40)

    def test_normal_speech_passes_everything(self):
        """The test that matters most: an ordinary clip must not trip a single
        axis, or the whole engine is noise."""
        report_scores = scores(speech())
        self.assertEqual(qc.verdict_for(qc.combine(qc.measure(speech(), RATE, text=SENTENCE))),
                         "EXCELLENT")
        for name, score in report_scores.items():
            self.assertGreaterEqual(score, 95, name)


class ContinuityTests(SimpleTestCase):
    def test_ordinary_pauses_are_not_choppiness(self):
        """Speech is full of short silences — a /t/ closure is 50–100 ms. An
        axis that counts those flags every clip ever recorded."""
        self.assertEqual(scores(speech())[qc.CONTINUITY], 100.0)

    def test_holes_punched_in_loud_speech_are(self):
        self.assertLess(scores(speech(dropouts=12))[qc.CONTINUITY], 30)

    def test_only_continuity_moves(self):
        """Proves the axis is measuring what it claims: the clip differs from
        the clean one only in the holes."""
        clean, broken = scores(speech()), scores(speech(dropouts=12))
        for name in clean:
            if name != qc.CONTINUITY:
                self.assertEqual(clean[name], broken[name], name)


class DistortionTests(SimpleTestCase):
    def test_clipped_audio_is_caught(self):
        self.assertLess(scores(speech(level=45000))[qc.DISTORTION], 30)

    def test_clean_audio_is_not(self):
        self.assertEqual(scores(speech())[qc.DISTORTION], 100.0)


class CompletenessTests(SimpleTestCase):
    def test_a_clip_ending_mid_word_is_caught(self):
        """§7: «وسط جمله قطع نمی‌شود»."""
        self.assertLess(scores(speech(tail_silence=0.0))[qc.COMPLETENESS], 50)

    def test_a_clip_that_finishes_its_sentence_is_not(self):
        self.assertEqual(scores(speech())[qc.COMPLETENESS], 100.0)


class PaceTests(SimpleTestCase):
    def test_speech_rushed_to_fit_a_scene_is_caught(self):
        self.assertLess(scores(speech(1.5))[qc.PACE], 40)

    def test_pace_is_not_scored_without_the_text(self):
        """Characters per second is meaningless when we do not know what was
        supposed to be said, and a number invented there would be a lie."""
        self.assertNotIn(qc.PACE, scores(speech(), text=""))


class CombineTests(SimpleTestCase):
    def test_one_catastrophic_axis_is_not_averaged_away(self):
        """Same rule as video QC: loud, clean, well-paced and inaudible is not
        an 80."""
        axes = [
            qc.Axis(qc.AUDIBLE, 0.0),
            qc.Axis(qc.CONTINUITY, 100.0),
            qc.Axis(qc.DISTORTION, 100.0),
            qc.Axis(qc.LEVEL, 100.0),
        ]
        self.assertLessEqual(qc.combine(axes), qc.WORST_AXIS_HEADROOM)

    def test_loudness_alone_cannot_fail_a_clip_outright(self):
        """It is a comfort axis a filter fixes, not a correctness one."""
        good = [qc.Axis(n, 100.0) for n in (qc.AUDIBLE, qc.CONTINUITY, qc.DISTORTION)]
        self.assertGreater(qc.combine(good + [qc.Axis(qc.LEVEL, 55.0)]), 60)

    def test_no_axes_is_zero_not_an_error(self):
        self.assertEqual(qc.combine([]), 0.0)


class ReportTests(SimpleTestCase):
    def test_an_unreadable_file_is_not_a_bad_score(self):
        """A missing ffmpeg is a configuration problem. Reporting it as a
        quality collapse turns one broken install into a wall of prompts."""
        report = qc.AudioQCReport(error="صدا قابل خواندن نبود")
        self.assertFalse(report.judged)
        self.assertIsNone(report.score_fraction)

    def test_pronunciation_is_never_scored(self):
        """There is no signal-level difference between a correctly and
        incorrectly pronounced word. A number there would be fabricated."""
        report = qc.AudioQCReport(axes=[qc.Axis(qc.AUDIBLE, 90.0)], overall=90.0)
        self.assertFalse(report.as_dict()["pronunciation_judged"])
        self.assertNotIn(
            "تلفظ", [a["name"] for a in report.as_dict()["axes"]],
        )


# ------------------------------------------------------------- narration


class FakeTTS:
    """Records what it was asked to say. Writes a byte so the file exists."""

    def __init__(self, fail_times=0):
        self.said = []
        self.fail_times = fail_times

    def synthesize(self, text, out_path):
        self.said.append(text)
        if len(self.said) <= self.fail_times:
            from services.audio.tts import TTSError

            raise TTSError("engine unavailable")
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0")
        return path


class NarrationLengthTests(SimpleTestCase):
    def test_a_line_that_fits_is_left_alone(self):
        self.assertTrue(narration.fits("سلام", 5))

    def test_a_line_far_too_long_does_not_fit(self):
        long_line = "این " * 60
        self.assertFalse(narration.fits(long_line, 5))

    def test_the_estimate_costs_nothing(self):
        """Deciding to shorten before synthesising saves a round trip; the
        estimate has to work without one."""
        self.assertGreater(narration.estimate_seconds("سلام دوستان عزیز"), 0)

    def test_tightening_keeps_the_original_when_the_model_is_unreachable(self):
        """A voice job dying because the shortening model was down would be a
        worse outcome than a slightly rushed sentence."""
        text = "این " * 60
        with patch("apps.ai.services.recorded_json_call", side_effect=RuntimeError("down")):
            result, changed = narration.tighten(text, 3)
        self.assertEqual(result, text)
        self.assertFalse(changed)

    def test_a_model_that_returns_something_longer_is_ignored(self):
        """Reporting `tightened=True` about a line we did not shorten would be
        a false claim in the job result."""
        text = "این " * 60
        with patch(
            "apps.ai.services.recorded_json_call",
            return_value=({"text": text + " و باز هم بیشتر"}, None),
        ):
            result, changed = narration.tighten(text, 3)
        self.assertEqual(result, text)
        self.assertFalse(changed)


class NarrateSceneTests(TestCase):
    """The orchestration, with ffmpeg stubbed — it is not installed here and
    these tests are about the decisions, not about the filters."""

    def setUp(self):
        from apps.stores.models import Store

        owner = User.objects.create_user("narr-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="فروشگاه صدا")
        self.tmp = Path(__file__).resolve().parent / "_audio_tmp"
        self.tmp.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, text, *, reports, tts=None, target=5.0):
        """Run one scene with a scripted sequence of QC verdicts."""
        tts = tts or FakeTTS()
        made = []

        def fake_silence(duration, out_path, **kwargs):
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"")
            made.append(("silence", duration))
            return Path(out_path)

        def fake_fit(audio_path, out_path, target_duration, **kwargs):
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"\0")
            return Path(out_path)

        with patch.object(narration, "make_silence", fake_silence), \
                patch.object(narration, "fit_audio", fake_fit), \
                patch.object(narration, "probe_duration", return_value=1.0), \
                patch.object(narration.qc, "check", side_effect=list(reports)):
            result = narration.narrate_scene(
                tts=tts, text=text, target_duration=target,
                out_path=self.tmp / "scene.m4a", work_dir=self.tmp / "work",
                store=self.store, scene_label="صحنه ۱",
            )
        result.made = made
        return result

    def _report(self, score, *, fixable=None, resynth=None):
        return qc.AudioQCReport(
            axes=[qc.Axis(qc.AUDIBLE, score)],
            overall=score,
            verdict=qc.verdict_for(score),
            code_fixable=fixable or [],
            needs_resynthesis=resynth or [],
        )

    def test_a_scene_with_no_narration_gets_real_silence(self):
        """§7: «برای صحنه‌های بدون حرف، سکوت می‌گذاریم نه صدای الکی»."""
        result = self._run("", reports=[])
        self.assertTrue(result.silent)
        self.assertEqual(result.made, [("silence", 5.0)])

    def test_silence_is_not_scored(self):
        """«شنیده شدن: ۰» on a scene we deliberately left quiet would be the
        system flagging its own correct behaviour."""
        self.assertIsNone(self._run("", reports=[]).report)

    def test_the_voice_is_given_the_spoken_form(self):
        tts = FakeTTS()
        self._run("کفش Nike", reports=[self._report(95)], tts=tts)
        self.assertIn("نایکی", tts.said[0])

    def test_a_good_take_is_not_retried(self):
        tts = FakeTTS()
        self._run("سلام", reports=[self._report(95)], tts=tts)
        self.assertEqual(len(tts.said), 1)

    def test_a_bad_take_is_made_again(self):
        """§7: «اگر بد بود، دوباره ساخته می‌شود»."""
        tts = FakeTTS()
        self._run(
            "سلام",
            reports=[self._report(30, resynth=[qc.AUDIBLE]),
                     self._report(92)],
            tts=tts,
        )
        self.assertEqual(len(tts.said), 2)

    def test_the_best_take_wins_not_the_last(self):
        """A retry is allowed to come out worse. Keeping whatever finished last
        means sometimes shipping the worse take after paying for both."""
        result = self._run(
            "سلام",
            reports=[self._report(64, resynth=[qc.AUDIBLE]),
                     self._report(20, resynth=[qc.AUDIBLE])],
        )
        self.assertEqual(result.report.overall, 64)

    def test_a_filter_is_tried_before_the_voice_engine(self):
        """Loudness is fixable for free; asking for the same sentence again
        would return the same quiet audio."""
        tts = FakeTTS()
        with patch.object(narration, "normalize_audio") as normalize:
            normalize.side_effect = lambda src, dst, **kw: (
                Path(dst).write_bytes(b"\0") or Path(dst)
            )
            self._run(
                "سلام",
                reports=[self._report(55, fixable=[qc.LEVEL]), self._report(90)],
                tts=tts,
            )
        self.assertEqual(len(tts.said), 1)

    def test_the_first_failure_is_not_hidden(self):
        """No audio at all must not become a silent gap in a finished video
        that nobody was told about."""
        from services.audio.tts import TTSError

        with self.assertRaises(TTSError):
            self._run("سلام", reports=[], tts=FakeTTS(fail_times=1))

    def test_unknown_words_are_reported_to_the_shop(self):
        result = self._run("کفش Hoka", reports=[self._report(95)])
        self.assertTrue(any("Hoka" in w for w in result.warnings))


class SummaryTests(SimpleTestCase):
    def _scene(self, score=None, silent=False, attempts=1):
        report = None
        if score is not None:
            report = qc.AudioQCReport(
                axes=[qc.Axis(qc.AUDIBLE, score)], overall=score,
                verdict=qc.verdict_for(score),
            )
        return narration.SceneAudio(
            path=Path("scene.m4a"), report=report, silent=silent, attempts=attempts,
        )

    def test_the_track_scores_its_worst_scene_not_its_average(self):
        """A video is watched start to finish. One unlistenable scene is what
        the viewer remembers, and a mean describes an experience nobody has."""
        summary = narration.summarize([self._scene(95), self._scene(40), self._scene(95)])
        self.assertEqual(summary["overall"], 40)

    def test_it_names_the_scene_to_look_at(self):
        summary = narration.summarize([self._scene(95), self._scene(40)])
        self.assertIn("weakest_scene", summary)

    def test_a_track_nobody_could_score_says_so(self):
        summary = narration.summarize([self._scene(silent=True), self._scene(silent=True)])
        self.assertEqual(summary["verdict"], "UNJUDGED")
        self.assertIsNone(summary["overall"])

    def test_silent_scenes_do_not_drag_the_score_down(self):
        summary = narration.summarize([self._scene(90), self._scene(silent=True)])
        self.assertEqual(summary["overall"], 90)
        self.assertEqual(summary["silent"], 1)

    def test_retries_are_counted_for_the_shop_to_see(self):
        summary = narration.summarize([self._scene(90, attempts=2), self._scene(90)])
        self.assertEqual(summary["retries"], 1)
