"""Subtitles from narration we wrote ourselves. §8

The claim being defended: **for our own videos there is nothing to recognise.**
The text is a database column. So none of these tests mock a speech-to-text
model — there is none — and what they check instead is the part that is
genuinely unknown: where each line falls in time, and whether the module is
honest about how it knew.

`measured` is the flag that matters. False means the boundaries came from line
length rather than from listening, and a proportional guess presented as
measured timing produces subtitles that drift with nobody able to say why.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from services.video import subtitles as sub

SENTENCE = "این کفش چرم طبیعی است. دو سال ضمانت دارد، و ارسالش رایگان است."


class SplittingTests(SimpleTestCase):
    def test_persian_clause_marks_split_lines(self):
        """Splitting only on «.» gives lines nobody can read — Persian
        narration is long sentences with clause breaks."""
        self.assertEqual(len(sub.phrases(SENTENCE)), 3)

    def test_empty_narration_produces_no_lines(self):
        self.assertEqual(sub.phrases(""), [])
        self.assertEqual(sub.phrases("   "), [])

    def test_a_long_clause_with_no_punctuation_is_still_split(self):
        runaway = "این " * 80
        for line in sub.phrases(runaway):
            self.assertLessEqual(len(line), sub.MAX_LINE * sub.MAX_LINES + 10)

    def test_wrapping_never_breaks_a_word(self):
        """Persian joins letters; a word split across two subtitle lines is
        unreadable in a way an English one is not."""
        line = "فروشگاه اینترنتی لباس بچگانه با ارسال رایگان به سراسر کشور"
        for part in sub.wrap(line).split("\n"):
            self.assertFalse(part.startswith(" "))
        self.assertEqual(sub.wrap(line).replace("\n", " "), line)

    def test_wrapping_stops_at_two_lines(self):
        long_line = "کلمه " * 40
        self.assertLessEqual(len(sub.wrap(long_line).split("\n")), sub.MAX_LINES)


class TimingTests(SimpleTestCase):
    def test_one_line_fills_the_scene(self):
        cues, measured = sub.cues_for("سلام", 0.0, 5.0)
        self.assertEqual(len(cues), 1)
        self.assertEqual((cues[0].start, cues[0].end), (0.0, 5.0))
        self.assertTrue(measured)

    def test_without_audio_the_split_is_proportional_and_says_so(self):
        cues, measured = sub.cues_for(SENTENCE, 0.0, 12.0)
        self.assertFalse(measured)
        self.assertEqual(len(cues), 3)

    def test_with_audio_the_boundaries_come_from_the_pauses(self):
        """The whole reason to read the waveform rather than guess."""
        with patch.object(sub, "pauses_in", return_value=[2.0, 7.0]):
            cues, measured = sub.cues_for(
                SENTENCE, 0.0, 12.0, audio_path="x.m4a", work_dir=".",
            )
        self.assertTrue(measured)
        self.assertAlmostEqual(cues[0].end, 2.0)
        self.assertAlmostEqual(cues[1].end, 7.0)

    def test_the_wrong_number_of_pauses_falls_back_rather_than_guessing(self):
        """Two lines and five detected gaps means the detection did not find
        the boundaries; using them anyway would put cues in the wrong places."""
        with patch.object(sub, "pauses_in", return_value=[1.0]):
            _, measured = sub.cues_for(
                SENTENCE, 0.0, 12.0, audio_path="x.m4a", work_dir=".",
            )
        self.assertFalse(measured)

    def test_cues_never_overlap(self):
        """A player shown two overlapping cues displays both, stacked."""
        with patch.object(sub, "pauses_in", return_value=[8.0, 1.0]):
            cues, _ = sub.cues_for(
                SENTENCE, 0.0, 12.0, audio_path="x.m4a", work_dir=".",
            )
        for earlier, later in zip(cues, cues[1:]):
            self.assertLessEqual(earlier.end, later.start)

    def test_no_cue_runs_past_the_scene(self):
        with patch.object(sub, "pauses_in", return_value=[99.0, 100.0]):
            cues, _ = sub.cues_for(
                SENTENCE, 0.0, 12.0, audio_path="x.m4a", work_dir=".",
            )
        self.assertLessEqual(cues[-1].end, 12.0)

    def test_unreadable_audio_is_not_an_error(self):
        with patch("services.audio.qc.decode", side_effect=RuntimeError("no ffmpeg")):
            self.assertEqual(sub.pauses_in("x.m4a", ".", want=2), [])


class TidyTests(SimpleTestCase):
    def test_a_cue_too_short_to_read_is_merged(self):
        cues = [sub.Cue(1, 0.0, 0.3, "الف"), sub.Cue(2, 0.3, 4.0, "ب")]
        tidied = sub.tidy(cues)
        self.assertEqual(len(tidied), 1)
        self.assertIn("الف", tidied[0].text)
        self.assertIn("ب", tidied[0].text)

    def test_a_cue_that_outstays_its_welcome_is_capped(self):
        tidied = sub.tidy([sub.Cue(1, 0.0, 30.0, "سلام")])
        self.assertLessEqual(tidied[0].seconds, sub.MAX_CUE)

    def test_indexes_are_renumbered_after_merging(self):
        cues = [
            sub.Cue(1, 0.0, 0.2, "الف"),
            sub.Cue(2, 0.2, 3.0, "ب"),
            sub.Cue(3, 3.0, 6.0, "ج"),
        ]
        self.assertEqual([c.index for c in sub.tidy(cues)], [1, 2])

    def test_no_cues_is_not_a_crash(self):
        self.assertEqual(sub.tidy([]), [])


class SrtTests(SimpleTestCase):
    def test_the_stamp_format_is_what_players_expect(self):
        srt = sub.to_srt([sub.Cue(1, 1.5, 3.25, "سلام")])
        self.assertIn("00:00:01,500 --> 00:00:03,250", srt)

    def test_an_hour_long_video_stamps_correctly(self):
        srt = sub.to_srt([sub.Cue(1, 3661.0, 3662.0, "x")])
        self.assertIn("01:01:01,000", srt)

    def test_the_file_is_written_with_a_bom(self):
        """Some players still guess a subtitle file's encoding, and a Persian
        subtitle guessed as cp1256 is unreadable mojibake."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = sub.write_srt([sub.Cue(1, 0.0, 1.0, "سلام")],
                                 Path(directory) / "s.srt")
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))


class WholeVideoTests(SimpleTestCase):
    class Scene:
        def __init__(self, index, narration, duration=5):
            self.index = index
            self.narration = narration
            self.duration = duration

    def test_scenes_are_laid_out_end_to_end(self):
        built = sub.build_for_scenes(
            [self.Scene(1, "اول."), self.Scene(2, "دوم.")], ".",
        )
        self.assertEqual(built["count"], 2)
        self.assertEqual(built["seconds"], 10.0)
        self.assertAlmostEqual(built["cues"][1].start, 5.0)

    def test_a_scene_with_no_narration_gets_no_subtitle(self):
        """Captioning silence with the visual prompt would put our own stage
        directions on the customer's video."""
        built = sub.build_for_scenes(
            [self.Scene(1, "اول."), self.Scene(2, "")], ".",
        )
        self.assertEqual(built["count"], 1)
        self.assertEqual(built["silent_scenes"], 1)

    def test_the_real_scene_length_wins_over_the_planned_one(self):
        built = sub.build_for_scenes(
            [self.Scene(1, "اول.", duration=5)], ".",
            duration_for=lambda s: 7.5,
        )
        self.assertEqual(built["seconds"], 7.5)

    def test_estimated_timing_says_it_is_estimated(self):
        built = sub.build_for_scenes(
            [self.Scene(1, "اول. دوم. سوم.")], ".",
        )
        self.assertFalse(built["measured"])
        self.assertIn("تخمین", built["note"])

    def test_word_level_timing_is_reported_honestly(self):
        """Per-word timing needs Whisper, so the answer depends on the box this
        is running on. A panel that promises karaoke timing without the model
        is lying to the shop, and one that denies it when the model is right
        there is hiding a feature they paid the disk space for."""
        built = sub.build_for_scenes([self.Scene(1, "سلام.")], ".")
        self.assertEqual(built["word_level"], sub.word_level_available())

    def test_without_whisper_word_level_is_false(self):
        with patch("services.audio.transcribe.available", return_value=(False, "x")):
            built = sub.build_for_scenes([self.Scene(1, "سلام.")], ".")
        self.assertFalse(built["word_level"])

    def test_with_whisper_word_level_is_true(self):
        with patch("services.audio.transcribe.available", return_value=(True, "")):
            built = sub.build_for_scenes([self.Scene(1, "سلام.")], ".")
        self.assertTrue(built["word_level"])

    def test_an_uploaded_video_says_why_it_cannot_be_subtitled_for_free(self):
        reason = sub.transcribe_needed(None)
        self.assertIn("گفتار به متن", reason)

    def test_a_short_first_cue_joins_the_one_after_it(self):
        """The case an implementation that only looks backwards misses: a
        0.3-second flash at the very start has no predecessor."""
        cues = [sub.Cue(1, 0.0, 0.3, "الف"), sub.Cue(2, 0.3, 4.0, "ب")]
        tidied = sub.tidy(cues)
        self.assertEqual(len(tidied), 1)
        self.assertEqual(tidied[0].start, 0.0)
        self.assertEqual(tidied[0].end, 4.0)

    def test_a_short_last_cue_is_stretched_rather_than_flashed(self):
        cues = [sub.Cue(1, 0.0, 4.0, "الف"), sub.Cue(2, 4.0, 4.2, "ب")]
        tidied = sub.tidy(cues)
        self.assertGreaterEqual(tidied[-1].seconds, sub.MIN_CUE)

    def test_two_short_cues_in_a_row_become_one(self):
        cues = [
            sub.Cue(1, 0.0, 0.2, "الف"),
            sub.Cue(2, 0.2, 0.4, "ب"),
            sub.Cue(3, 0.4, 4.0, "ج"),
        ]
        self.assertEqual(len(sub.tidy(cues)), 1)
