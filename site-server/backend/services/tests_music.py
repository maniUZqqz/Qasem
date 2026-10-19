"""Music under narration. §7 (phase 22).

Two things are worth holding down here, and neither is about ffmpeg.

**The voice wins.** `MUSIC_CEILING` is a hard cap, and a shop that sets the
music too loud gets it clamped rather than getting a video whose narration
nobody can follow. A video whose voice is unintelligible has failed at the only
thing it was made for.

**We never ship the audio.** A track bundled without a watertight licence
becomes a copyright strike on the *customer's* account, weeks later, with no
explanation they can act on. So the tests check the licence note is part of the
refusal when there is no music — not buried in terms nobody reads.
"""
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from services.audio import music


class LevelTests(SimpleTestCase):
    def test_the_ceiling_cannot_be_crossed(self):
        """Past this the narration stops being intelligible, and a video whose
        voice nobody can follow has failed at its only job."""
        track = music.Track(path=Path("x.mp3"), level_db=0.0)
        self.assertEqual(track.safe_level(), music.MUSIC_CEILING)

    def test_a_sensible_level_is_left_alone(self):
        track = music.Track(path=Path("x.mp3"), level_db=-25.0)
        self.assertEqual(track.safe_level(), -25.0)

    def test_the_default_sits_well_under_the_ceiling(self):
        self.assertLess(music.MUSIC_DB, music.MUSIC_CEILING)


class FitTests(SimpleTestCase):
    def test_short_music_loops_rather_than_stopping(self):
        """Otherwise the last half of every video is silent."""
        self.assertIn("aloop", music._fit_filter(20.0, 60.0))

    def test_long_music_is_trimmed_not_looped(self):
        graph = music._fit_filter(180.0, 60.0)
        self.assertNotIn("aloop", graph)
        self.assertIn("atrim=0:60", graph)

    def test_music_always_fades_out(self):
        """A hard cut to silence at the end reads as a glitch."""
        self.assertIn("afade=t=out", music._fit_filter(180.0, 60.0))

    def test_the_fade_out_starts_before_the_end(self):
        graph = music._fit_filter(180.0, 60.0)
        self.assertIn(f"st={60.0 - music.FADE_OUT:.3f}", graph)

    def test_a_video_shorter_than_the_fade_does_not_fade_from_before_zero(self):
        self.assertIn("st=0.000", music._fit_filter(180.0, 1.0))


class MixTests(SimpleTestCase):
    def _render(self, **kwargs):
        captured = {}
        with patch.object(music, "_run", side_effect=lambda cmd: captured.setdefault("cmd", cmd)), \
                patch.object(music, "probe_duration", return_value=60.0), \
                patch.object(music, "inspect", return_value={"seconds": 30.0, "name": "m.mp3"}), \
                patch("pathlib.Path.exists", return_value=True), \
                patch("pathlib.Path.stat") as stat, \
                patch("pathlib.Path.mkdir"):
            stat.return_value.st_size = 10
            music.under_narration(
                "in.mp4", music.Track(path=Path("m.mp3")), "out.mp4", **kwargs,
            )
        return " ".join(captured["cmd"])

    def test_the_voice_ducks_the_music_not_the_other_way_round(self):
        """Flat music either drowns the narration or is inaudible. The voice
        drives the compressor on the music."""
        command = self._render()
        self.assertIn("sidechaincompress", command)

    def test_ducking_can_be_turned_off(self):
        self.assertNotIn("sidechaincompress", self._render(duck=False))

    def test_the_picture_is_copied_not_re_encoded(self):
        """Re-encoding video to add music costs minutes and loses quality for
        nothing."""
        self.assertIn("-c:v copy", self._render())

    def test_the_output_is_no_longer_than_the_video(self):
        self.assertIn("-shortest", self._render())


class EffectTests(SimpleTestCase):
    def _effects(self, *tracks):
        with patch.object(music, "probe_duration", return_value=60.0), \
                patch("pathlib.Path.exists", return_value=True):
            with patch.object(music, "inspect", return_value={"seconds": 1.0, "name": "e.mp3"}):
                with patch.object(music, "_run") as run, \
                        patch("pathlib.Path.stat") as stat, \
                        patch("pathlib.Path.mkdir"):
                    stat.return_value.st_size = 10
                    music.add_effects("in.mp4", list(tracks), "out.mp4")
                    return " ".join(run.call_args.args[0])

    def test_an_effect_lands_where_it_was_asked_for(self):
        command = self._effects(music.Track(path=Path("e.mp3"), at=3.5))
        self.assertIn("adelay=3500|3500", command)

    def test_the_mix_is_compensated_so_the_video_does_not_get_quieter(self):
        """`amix` divides by the input count; without this a video with six
        effects comes back noticeably quieter than it went in. normalize=0
        keeps every input at its own level (it replaced a volume=N make-up
        gain after a 1/N mix, which was the same thing done twice)."""
        command = self._effects(
            music.Track(path=Path("a.mp3"), at=1),
            music.Track(path=Path("b.mp3"), at=2),
        )
        self.assertIn("amix=inputs=3", command)
        self.assertIn("normalize=0", command)

    def test_music_in_the_effects_field_is_refused_by_name(self):
        with patch.object(music, "probe_duration", return_value=60.0), \
                patch("pathlib.Path.exists", return_value=True), \
                patch.object(music, "inspect", return_value={"seconds": 90.0, "name": "song.mp3"}):
            with self.assertRaises(music.MusicError) as caught:
                music.add_effects(
                    "in.mp4", [music.Track(path=Path("song.mp3"))], "out.mp4",
                )
        self.assertIn("song.mp3", str(caught.exception))
        self.assertIn("موسیقی است نه افکت", str(caught.exception))

    def test_an_effect_past_the_end_of_the_video_is_refused(self):
        with patch.object(music, "probe_duration", return_value=60.0), \
                patch("pathlib.Path.exists", return_value=True), \
                patch.object(music, "inspect", return_value={"seconds": 1.0, "name": "e.mp3"}):
            with self.assertRaises(music.MusicError):
                music.add_effects(
                    "in.mp4", [music.Track(path=Path("e.mp3"), at=99)], "out.mp4",
                )

    def test_no_effects_is_refused_rather_than_rendering_nothing(self):
        with self.assertRaises(music.MusicError):
            music.add_effects("in.mp4", [], "out.mp4")

    def test_too_many_effects_is_refused(self):
        """Past a dozen this is a filtergraph that takes longer to build than
        the render it decorates."""
        with patch("pathlib.Path.exists", return_value=True):
            with self.assertRaises(music.MusicError):
                music.add_effects(
                    "in.mp4",
                    [music.Track(path=Path(f"{i}.mp3")) for i in range(20)],
                    "out.mp4",
                )


class LicenceTests(SimpleTestCase):
    def test_the_licence_note_names_whose_account_takes_the_strike(self):
        """Not a disclaimer in terms nobody reads: the consequence lands on the
        shop's page, weeks later."""
        self.assertIn("خودتان", music.LICENCE_NOTE)
        self.assertIn("کپی‌رایت", music.LICENCE_NOTE)

    def test_a_missing_file_is_refused_in_persian(self):
        with patch("pathlib.Path.exists", return_value=False):
            with self.assertRaises(music.MusicError) as caught:
                music.inspect("nope.mp3")
        self.assertIn("پیدا نشد", str(caught.exception))

    def test_an_empty_file_is_refused(self):
        with patch("pathlib.Path.exists", return_value=True), \
                patch.object(music, "probe_duration", return_value=0.0):
            with self.assertRaises(music.MusicError):
                music.inspect("empty.mp3")
