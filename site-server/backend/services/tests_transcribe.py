"""Speech to text, and the alignment that makes it useful. §8

The load-bearing idea: **for our own videos, Whisper is used for timing and its
transcript is thrown away.** We wrote the narration, so the words are not in
question — only when each one was said. `align` carries our spelling across onto
the model's timings, which is why a brand name Whisper mangles still lands at
the right second with the right letters.

The model itself is never loaded here. Loading `small` downloads hundreds of
megabytes and takes seconds, and none of these tests are about whether Whisper
can hear — they are about what we do with what it heard.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from services.audio import transcribe as asr


def heard(*triples) -> asr.Transcript:
    """A transcript shaped like faster-whisper's, from (word, start, end)."""
    words = [asr.Word(text=t, start=s, end=e) for t, s, e in triples]
    return asr.Transcript(segments=[
        asr.Segment(
            text=" ".join(w.text for w in words),
            start=words[0].start if words else 0.0,
            end=words[-1].end if words else 0.0,
            words=words,
        )
    ])


class AvailabilityTests(SimpleTestCase):
    def test_it_says_what_to_install_rather_than_returning_nothing(self):
        """An empty transcript would produce a video with no subtitles and no
        explanation."""
        with patch.dict("sys.modules", {"faster_whisper": None}):
            ok, why = asr.available()
        self.assertFalse(ok)
        self.assertIn("faster-whisper", why)

    def test_an_unknown_model_is_refused_by_name(self):
        with self.assertRaises(asr.TranscriptionUnavailable) as caught:
            asr.transcribe("x.wav", model="enormous")
        self.assertIn("enormous", str(caught.exception))


class AlignmentTests(SimpleTestCase):
    KNOWN = "کفش نایکی اصل با دو سال ضمانت"

    def test_our_spelling_survives_the_model_mangling_it(self):
        """Whisper writing «نای کی» must not put «نای کی» on the customer's
        video — we know the brand is «نایکی»."""
        transcript = heard(
            ("کفش", 0.0, 0.4), ("نای", 0.4, 0.7), ("کی", 0.7, 0.9),
            ("اصل", 0.9, 1.3), ("با", 1.3, 1.5), ("دو", 1.5, 1.8),
            ("سال", 1.8, 2.2), ("ضمانت", 2.2, 2.9),
        )
        aligned = asr.align(self.KNOWN, transcript)
        self.assertEqual(" ".join(w.text for w in aligned), self.KNOWN)

    def test_the_mangled_word_lands_where_it_was_spoken(self):
        transcript = heard(
            ("کفش", 0.0, 0.4), ("نای", 0.4, 0.7), ("کی", 0.7, 0.9),
            ("اصل", 0.9, 1.3), ("با", 1.3, 1.5), ("دو", 1.5, 1.8),
            ("سال", 1.8, 2.2), ("ضمانت", 2.2, 2.9),
        )
        brand = next(w for w in asr.align(self.KNOWN, transcript) if w.text == "نایکی")
        self.assertAlmostEqual(brand.start, 0.4, places=2)
        self.assertAlmostEqual(brand.end, 0.9, places=2)

    def test_every_one_of_our_words_gets_a_time(self):
        """A word we cannot time exactly is better slightly off than missing —
        if one disappears, everything after it slides."""
        transcript = heard(("کفش", 0.0, 0.5), ("ضمانت", 2.0, 2.5))
        aligned = asr.align(self.KNOWN, transcript)
        self.assertEqual(len(aligned), len(self.KNOWN.split()))

    def test_words_come_back_in_order(self):
        transcript = heard(("کفش", 0.0, 0.4), ("ضمانت", 2.2, 2.9))
        aligned = asr.align(self.KNOWN, transcript)
        for earlier, later in zip(aligned, aligned[1:]):
            self.assertLessEqual(earlier.start, later.start)

    def test_a_word_the_model_never_heard_is_marked_down(self):
        """Its position is inferred, not observed, and the confidence says so."""
        transcript = heard(("کفش", 0.0, 0.4), ("ضمانت", 2.2, 2.9))
        aligned = asr.align(self.KNOWN, transcript)
        inferred = [w for w in aligned if w.text == "اصل"]
        self.assertTrue(inferred)
        self.assertLess(inferred[0].probability, 1.0)

    def test_an_empty_transcript_aligns_to_nothing(self):
        self.assertEqual(asr.align(self.KNOWN, asr.Transcript()), [])

    def test_empty_text_aligns_to_nothing(self):
        self.assertEqual(asr.align("", heard(("x", 0, 1))), [])


class CueBreakingTests(SimpleTestCase):
    def test_a_pause_starts_a_new_line(self):
        """A gap is where a sentence ended; breaking there gives lines that
        match how it was actually spoken."""
        words = [
            asr.Word("سلام", 0.0, 0.5),
            asr.Word("دوستان", 0.5, 1.0),
            asr.Word("امروز", 3.0, 3.5),
        ]
        self.assertEqual(len(asr.cues_from_words(words)), 2)

    def test_a_long_line_is_broken_on_length(self):
        words = [asr.Word("کلمه", i * 0.3, i * 0.3 + 0.3) for i in range(30)]
        for _, _, text in asr.cues_from_words(words, max_chars=42):
            self.assertLessEqual(len(text), 50)

    def test_a_long_stretch_is_broken_on_time(self):
        words = [asr.Word("ا", i * 0.5, i * 0.5 + 0.5) for i in range(40)]
        for start, end, _ in asr.cues_from_words(words, max_seconds=6.0):
            self.assertLessEqual(end - start, 7.0)

    def test_no_words_is_no_lines(self):
        self.assertEqual(asr.cues_from_words([]), [])


class ConfidenceTests(SimpleTestCase):
    def test_a_shaky_segment_is_marked_not_dropped(self):
        """A shop can fix a word we got wrong. They cannot fix a line we
        quietly deleted."""
        segment = asr.Segment(text="چیزی", start=0, end=1, confidence=-1.5)
        self.assertTrue(segment.uncertain)

    def test_a_confident_segment_is_not_marked(self):
        segment = asr.Segment(text="چیزی", start=0, end=1, confidence=-0.2)
        self.assertFalse(segment.uncertain)

    def test_the_transcript_counts_the_shaky_lines_and_says_so(self):
        transcript = asr.Transcript(segments=[
            asr.Segment(text="الف", start=0, end=1, confidence=-1.5),
            asr.Segment(text="ب", start=1, end=2, confidence=-0.1),
        ])
        body = transcript.as_dict()
        self.assertEqual(body["uncertain"], 1)
        self.assertIn("اطمینان پایین", body["note"])

    def test_a_clean_transcript_says_nothing(self):
        transcript = asr.Transcript(segments=[
            asr.Segment(text="الف", start=0, end=1, confidence=-0.1),
        ])
        self.assertEqual(transcript.as_dict()["note"], "")


class SubtitleIntegrationTests(SimpleTestCase):
    def test_our_own_video_gets_word_level_cues_with_our_words(self):
        from services.video import subtitles

        transcript = heard(
            ("کفش", 0.0, 0.4), ("نای", 0.4, 0.7), ("کی", 0.7, 0.9),
            ("اصل", 0.9, 1.3),
        )
        cues = subtitles.cues_from_transcript("کفش نایکی اصل", transcript)
        text = " ".join(c.text.replace("\n", " ") for c in cues)
        self.assertIn("نایکی", text)
        self.assertNotIn("نای کی", text)

    def test_an_uploaded_video_keeps_the_transcript_and_marks_the_shaky_lines(self):
        from services.video import subtitles

        transcript = asr.Transcript(segments=[
            asr.Segment(
                text="سلام دوستان", start=0, end=1.0, confidence=-1.5,
                words=[asr.Word("سلام", 0, 0.5), asr.Word("دوستان", 0.5, 1.0)],
            ),
        ])
        built = subtitles.from_transcript(transcript)
        self.assertTrue(built["cues"])
        self.assertTrue(built["measured"])
        self.assertTrue(built["word_level"])
        self.assertTrue(built["uncertain_lines"])

    def test_a_transcript_with_no_word_timings_still_produces_cues(self):
        from services.video import subtitles

        transcript = asr.Transcript(segments=[
            asr.Segment(text="سلام", start=0, end=2.0, words=[]),
        ])
        built = subtitles.from_transcript(transcript)
        self.assertEqual(built["count"], 1)
        self.assertFalse(built["word_level"])
