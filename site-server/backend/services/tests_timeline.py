"""Multi-track timeline and proxy editing. §23.4

Two properties carry this file, and both are about refusing rather than doing.

**Two clips at the same moment on one track is not an edit.** A track is a
single layer, so there is no defined answer for which one shows — and a renderer
asked anyway just picks one. Better to say so and name both clips.

**A proxy that changes the frame rate is worse than no proxy.** The whole point
is that decisions made against the small file apply unchanged to the big one; if
the timebase differs, a cut at 12.40 seconds lands on a different frame in each,
and the shop approves one video and exports another. The difference only shows
up on the final render, after they said yes.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from services.editing import timeline as T


def clip(source="a.mp4", **kwargs):
    kwargs.setdefault("at", 0.0)
    kwargs.setdefault("end", 5.0)
    return T.Clip(source=source, **kwargs)


def simple(**kwargs):
    return T.Timeline(tracks=[T.Track(kind="video", clips=[clip()])], **kwargs)


class ArrangementTests(SimpleTestCase):
    def test_a_clip_knows_where_it_ends(self):
        self.assertEqual(clip(at=3.0, start=1.0, end=5.0).ends_at, 7.0)

    def test_start_and_end_are_points_in_the_SOURCE_not_the_timeline(self):
        """The distinction every NLE makes and everyone gets wrong once —
        including me, in the first version of this test.

        `at` is where the clip lands. `start`/`end` are which part of the
        source file is used. So a clip placed at 10s using seconds 0–13 of its
        source ends at 23s, not at 13s.
        """
        placed = clip(at=10, start=0, end=13)
        self.assertEqual(placed.source_length, 13.0)
        self.assertEqual(placed.ends_at, 23.0)

    def test_the_timeline_is_as_long_as_its_last_clip(self):
        line = T.Timeline(tracks=[T.Track(clips=[
            clip(at=0, start=0, end=4), clip(at=10, start=0, end=3),
        ])])
        self.assertEqual(line.length, 13.0)

    def test_two_clips_at_once_on_one_track_is_refused(self):
        """A track is one layer. Rendering it anyway silently picks one."""
        line = T.Timeline(tracks=[T.Track(kind="video", name="اصلی", clips=[
            T.Clip(source="a.mp4", at=0, end=5, label="یکی"),
            T.Clip(source="b.mp4", at=2, end=5, label="دومی"),
        ])])
        with self.assertRaises(T.TimelineError) as caught:
            line.validate()
        message = str(caught.exception)
        self.assertIn("یکی", message)
        self.assertIn("دومی", message)

    def test_the_same_moment_on_two_tracks_is_fine(self):
        """That is what layers are for — a logo over footage."""
        line = T.Timeline(tracks=[
            T.Track(kind="video", clips=[clip()]),
            T.Track(kind="video", clips=[clip(source="logo.mp4")]),
        ])
        line.validate()

    def test_a_gap_is_reported_not_filled(self):
        """Black and holding the last frame are both legitimate, and guessing
        produces a video nobody asked for."""
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            clip(at=0, end=3), clip(at=6, end=9),
        ])])
        self.assertEqual([(round(a, 1), round(b, 1)) for a, b in line.gaps()],
                         [(3.0, 6.0)])

    def test_a_continuous_track_has_no_gaps(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            clip(at=0, end=3), clip(at=3, end=6),
        ])])
        self.assertEqual(line.gaps(), [])


class RefusalTests(SimpleTestCase):
    def test_an_empty_timeline_is_refused(self):
        with self.assertRaises(T.TimelineError):
            T.Timeline().validate()

    def test_audio_alone_is_refused(self):
        line = T.Timeline(tracks=[T.Track(kind="audio", clips=[clip()])])
        with self.assertRaises(T.TimelineError):
            line.validate()

    def test_a_clip_ending_before_it_starts_is_refused_by_name(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            T.Clip(source="a.mp4", at=0, start=5, end=2, label="برعکس"),
        ])])
        with self.assertRaises(T.TimelineError) as caught:
            line.validate()
        self.assertIn("برعکس", str(caught.exception))

    def test_a_clip_hanging_off_the_frame_is_refused(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            T.Clip(source="a.mp4", at=0, end=5, x=0.8, width=0.5),
        ])])
        with self.assertRaises(T.TimelineError) as caught:
            line.validate()
        self.assertIn("بیرون", str(caught.exception))

    def test_too_many_tracks_is_refused(self):
        line = T.Timeline(tracks=[
            T.Track(kind="video", clips=[clip()]) for _ in range(T.MAX_TRACKS + 1)
        ])
        with self.assertRaises(T.TimelineError):
            line.validate()

    def test_a_negative_start_is_refused(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            T.Clip(source="a.mp4", at=-1, end=5),
        ])])
        with self.assertRaises(T.TimelineError):
            line.validate()


class FiltergraphTests(SimpleTestCase):
    def test_every_clip_becomes_an_input(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            clip("a.mp4", at=0, end=3), clip("b.mp4", at=3, end=6),
        ])])
        inputs, _ = T.build_filtergraph(line)
        self.assertEqual(inputs, ["a.mp4", "b.mp4"])

    def test_the_canvas_is_explicit(self):
        """A gap in the base track is then black, rather than whatever the
        renderer felt like."""
        _, graph = T.build_filtergraph(simple())
        self.assertIn("color=c=black", graph)

    def test_a_clip_is_enabled_only_for_its_window(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            clip(at=2.0, end=5.0),
        ])])
        _, graph = T.build_filtergraph(line)
        self.assertIn("between(t,2.000,7.000)", graph)

    def test_transparency_is_applied_only_when_asked_for(self):
        _, opaque = T.build_filtergraph(simple())
        self.assertNotIn("colorchannelmixer", opaque)

        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            clip(opacity=0.5),
        ])])
        _, faded = T.build_filtergraph(line)
        self.assertIn("colorchannelmixer=aa=0.500", faded)

    def test_audio_tracks_are_mixed_and_level_compensated(self):
        """`amix` divides by the input count — without the compensation a
        six-clip timeline comes back quieter than any one of its clips."""
        line = T.Timeline(tracks=[
            T.Track(kind="video", clips=[clip()]),
            T.Track(kind="audio", clips=[clip("v.m4a")]),
            T.Track(kind="audio", clips=[clip("m.mp3")]),
        ])
        _, graph = T.build_filtergraph(line)
        self.assertIn("amix=inputs=2", graph)
        self.assertIn("volume=2", graph)

    def test_a_muted_track_is_left_out(self):
        line = T.Timeline(tracks=[
            T.Track(kind="video", clips=[clip()]),
            T.Track(kind="audio", muted=True, clips=[clip("v.m4a")]),
        ])
        _, graph = T.build_filtergraph(line)
        self.assertNotIn("[aout]", graph)


class ProxyTests(SimpleTestCase):
    def _probe(self, height):
        return patch(
            "services.video.ffmpeg.probe",
            return_value={"streams": [{"codec_type": "video", "height": height}]},
        )

    def test_a_big_clip_is_worth_a_proxy(self):
        with self._probe(2160):
            worth, why = T.needs_proxy("4k.mp4")
        self.assertTrue(worth)
        self.assertEqual(why, "")

    def test_an_already_small_clip_is_not(self):
        """Measured, not assumed: re-encoding a 640x360 clip produced a file
        1.4x *larger* than the original, and cost a render to do it."""
        with self._probe(360):
            worth, why = T.needs_proxy("small.mp4")
        self.assertFalse(worth)
        self.assertIn("کوچک‌تر", why)

    def test_making_a_pointless_proxy_is_refused_rather_than_done(self):
        with self._probe(360):
            with self.assertRaises(T.TimelineError):
                T.make_proxy("small.mp4", "out.mp4")

    def test_an_unreadable_file_does_not_get_a_proxy(self):
        with patch("services.video.ffmpeg.probe", side_effect=RuntimeError("x")):
            worth, why = T.needs_proxy("broken.mp4")
        self.assertFalse(worth)
        self.assertTrue(why)

    def test_the_proxy_does_not_touch_the_frame_rate(self):
        """The property the whole workflow rests on. A different timebase makes
        a cut land on a different frame in the proxy than in the original."""
        captured = {}
        with self._probe(2160), \
                patch("services.video.ffmpeg._run",
                      side_effect=lambda cmd: captured.setdefault("cmd", cmd)), \
                patch("pathlib.Path.exists", return_value=True), \
                patch("pathlib.Path.stat") as stat, \
                patch("pathlib.Path.mkdir"):
            stat.return_value.st_size = 10
            T.make_proxy("big.mp4", "proxy.mp4")
        command = " ".join(captured["cmd"])
        self.assertNotIn("-r ", command)
        self.assertNotIn("fps=", command)
        self.assertIn(f"scale=-2:{T.PROXY_HEIGHT}", command)

    def test_relinking_swaps_the_sources_and_nothing_else(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[
            T.Clip(source="proxy_a.mp4", at=1.5, start=0.5, end=4.5),
        ])])
        T.relink(line, {"proxy_a.mp4": "original_a.mp4"})
        moved = line.tracks[0].clips[0]
        self.assertEqual(moved.source, "original_a.mp4")
        self.assertEqual((moved.at, moved.start, moved.end), (1.5, 0.5, 4.5))

    def test_relinking_leaves_an_unmapped_clip_alone(self):
        line = T.Timeline(tracks=[T.Track(kind="video", clips=[clip("kept.mp4")])])
        T.relink(line, {"other.mp4": "x.mp4"})
        self.assertEqual(line.tracks[0].clips[0].source, "kept.mp4")
