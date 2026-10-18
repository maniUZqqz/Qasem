"""The filtergraphs, run against a real ffmpeg. §7, §8

Every other test in this repository checks the *command* we build. These check
what the command does, and the difference is not academic: a filtergraph can be
perfectly well-formed, produce a file, exit zero, and do nothing at all. The
ducking graph did exactly that in an early measurement, and only comparing
levels showed it was working.

Skipped when ffmpeg is absent, because most machines running the suite do not
have it and a skipped test is honest where a mocked one would not be.

**The measurement is the test.** `sidechaincompress` renders a file either way;
what has to be true is that the music is *quieter while someone is speaking and
not quieter in the gaps*. Nothing short of measuring both windows says that.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from services.audio import music as M
from services.video import subtitles as sub
from services.video.ffmpeg import FFMPEG, probe_duration


def _has_ffmpeg() -> bool:
    binary = FFMPEG
    if Path(binary).exists():
        return True
    return shutil.which(binary) is not None


requires_ffmpeg = unittest.skipUnless(_has_ffmpeg(), "ffmpeg not installed")

#: The narration in the fixture speaks over these windows, and is silent
#: between them. Every assertion below is anchored to them.
SPEAKING = (1.2, 2.8)
GAP = (3.5, 4.5)


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr[-600:])


def _level(path, start, end) -> float:
    """Mean dB over one window, straight from ffmpeg."""
    result = subprocess.run(
        [FFMPEG, "-ss", str(start), "-to", str(end), "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    found = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    assert found, result.stderr[-400:]
    return float(found.group(1))


@requires_ffmpeg
class RealRenderTests(SimpleTestCase):
    """Built once: these fixtures cost a second each and nothing mutates them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dir = tempfile.TemporaryDirectory()
        work = cls.work = Path(cls._dir.name)

        # A video whose audio speaks over SPEAKING and is silent over GAP.
        cls.video = work / "voiced.mp4"
        _run([FFMPEG, "-y",
              "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:d=10",
              "-f", "lavfi", "-i",
              "sine=f=200:d=10,volume='if(between(t,1,3)+between(t,5,8),1,0)':eval=frame",
              "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
              "-shortest", str(cls.video)])

        # Deliberately shorter than the video, so the loop path is exercised.
        cls.track = work / "bed.mp3"
        _run([FFMPEG, "-y", "-f", "lavfi", "-i", "sine=f=440:d=4",
              "-c:a", "libmp3lame", str(cls.track)])

        # Three bursts with real gaps between them. Not speech, but the pause
        # detection only looks at the envelope, and that is what this is.
        cls.clip = work / "speechlike.m4a"
        _run([FFMPEG, "-y", "-f", "lavfi", "-i",
              "sine=f=180:d=8,volume='if(between(t,0,1.8)+between(t,3.0,4.6)"
              "+between(t,6.0,7.6),1,0)':eval=frame",
              "-c:a", "aac", str(cls.clip)])

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()
        super().tearDownClass()

    # ---------------------------------------------------------- music

    def test_music_is_quieter_while_somebody_is_speaking(self):
        """The whole reason `sidechaincompress` is in the graph. Flat music
        either drowns the narration or is inaudible."""
        flat, ducked = self._beds()
        self.assertLess(
            _level(ducked, *SPEAKING) + 3.0, _level(flat, *SPEAKING),
            "the music was not pulled down under the voice",
        )

    def test_music_comes_back_up_in_the_gaps(self):
        """A hole in the music is as noticeable as music over speech."""
        flat, ducked = self._beds()
        self.assertAlmostEqual(
            _level(ducked, *GAP), _level(flat, *GAP), delta=1.0,
        )

    def _beds(self):
        """The music bed alone, flat and ducked.

        Rendered without the voice on purpose: in the finished mix the voice is
        far louder than the music, so it masks the change entirely — which is
        correct, and also why measuring the mix proves nothing.
        """
        fitted = M._fit_filter(4.0, 10.0)
        flat, ducked = self.work / "flat.wav", self.work / "ducked.wav"
        if not flat.exists():
            _run([FFMPEG, "-y", "-i", str(self.video), "-i", str(self.track),
                  "-filter_complex", f"[1:a]{fitted},volume=-22.00dB[a]",
                  "-map", "[a]", str(flat)])
            _run([FFMPEG, "-y", "-i", str(self.video), "-i", str(self.track),
                  "-filter_complex",
                  f"[1:a]{fitted},volume=-22.00dB[bed];"
                  f"[bed][0:a]sidechaincompress=threshold=0.03:ratio="
                  f"{M.DUCK_RATIO}:attack=20:release=400[a]",
                  "-map", "[a]", str(ducked)])
        return flat, ducked

    def test_the_whole_mix_renders_and_keeps_the_video_length(self):
        out = self.work / "mixed.mp4"
        M.under_narration(self.video, M.Track(path=self.track), out)
        self.assertAlmostEqual(probe_duration(out), 10.0, delta=0.3)

    def test_short_music_fills_the_whole_video(self):
        """Four seconds of music under a ten-second video: without the loop,
        six seconds of the video have no music at all."""
        out = self.work / "looped.mp4"
        M.under_narration(self.video, M.Track(path=self.track), out, duck=False)
        # Measured late in the video, well past the end of the source track.
        self.assertGreater(_level(out, 8.2, 9.2), -80.0)

    def test_sound_effects_land_without_breaking_the_mix(self):
        sfx = self.work / "ding.mp3"
        _run([FFMPEG, "-y", "-f", "lavfi", "-i", "sine=f=880:d=1",
              "-c:a", "libmp3lame", str(sfx)])
        out = self.work / "sfx.mp4"
        M.add_effects(
            self.video,
            [M.Track(path=sfx, at=2.0), M.Track(path=sfx, at=6.5)],
            out,
        )
        self.assertAlmostEqual(probe_duration(out), 10.0, delta=0.3)

    # ------------------------------------------------------ subtitles

    def test_pauses_are_found_where_the_silences_actually_are(self):
        """The subtitle timing rests on this. Everywhere else it is mocked."""
        found = sub.pauses_in(self.clip, self.work, want=2)
        self.assertEqual(len(found), 2)
        # The two silences are 1.8–3.0 and 4.6–6.0; a boundary is placed in the
        # middle of each, so a cue neither clips the word before nor waits out
        # the whole pause before the word after.
        self.assertAlmostEqual(found[0], 2.4, delta=0.3)
        self.assertAlmostEqual(found[1], 5.3, delta=0.3)

    def test_a_real_clip_produces_measured_timing_not_an_estimate(self):
        _, measured = sub.cues_for(
            "جمله‌ی اول. جمله‌ی دوم، و جمله‌ی سوم.",
            0.0, 8.0, audio_path=self.clip, work_dir=self.work,
        )
        self.assertTrue(measured)
