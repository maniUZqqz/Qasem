"""A Director edit (15–30 cuts at 1080×1920) used to take ~2.4 GB inside ffmpeg and was killed by the kernel on the 4 GB server («Command failed (ffmpeg):
exit code -9»). Now: single-threaded decoders/filters for many-clip edits, a Persian sentence when ffmpeg is killed anyway, and one automatic retry at a
smaller picture."""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase, override_settings

from services.editing import export
from services.editing import timeline as tl
from services.video.ffmpeg import FFMPEG, VideoProcessingError, probe

from .tests_editor_modes import make_video

TEMP = tempfile.mkdtemp(prefix="nm-render-mem-")
HAVE = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))


class LeanFlagTests(SimpleTestCase):
    def test_small_simple_edits_keep_full_speed(self):
        self.assertEqual(export.lean_flags(1, 1080, 1920), ([], []))
        self.assertEqual(export.lean_flags(2, 1080, 1920), ([], []))
        self.assertEqual(export.lean_flags(4, 640, 360), ([], []))

    def test_many_clips_or_big_pictures_run_single_threaded(self):
        glob, per = export.lean_flags(export.LEAN_INPUTS, 640, 360)
        self.assertEqual((glob, per), (["-filter_complex_threads", "1"], ["-threads", "1"]))
        self.assertEqual(export.lean_flags(3, 1080, 1920)[0], ["-filter_complex_threads", "1"])
        self.assertEqual(export.lean_flags(18, 1080, 1920)[1], ["-threads", "1"])


@override_settings(MEDIA_ROOT=TEMP)
class OutOfMemoryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.src = make_video(Path(TEMP) / "m.mp4", size="320x180", seconds=3)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg نیست")

    def timeline(self, n=6, w=480, h=854):
        clips = [{"id": f"c{i}", "type": "media", "ref": "x", "label": "x", "kind": "video", "at": i * 0.5, "start": 0, "end": 0.5, "src": 3, "opacity": 1, "x": 0, "y": 0,
                  "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": True, "has_audio": True, "effects": [], "transition": None}
                 for i in range(n)]
        data = {"format": {"width": w, "height": h, "fps": 12, "preset": "reel"}, "tracks": [{"id": "t1", "kind": "video", "name": "v", "clips": clips}], "global_ops": []}
        info = {"path": str(self.src), "kind": "video", "has_audio": True, "duration": 3.0, "width": 320, "height": 180}
        return tl.from_project(data, lambda ref: dict(info))

    def test_a_many_clip_edit_is_rendered_with_the_lean_flags_and_plays(self):
        timeline = self.timeline(n=7)
        seen = {}
        real = export.run_ffmpeg

        def spy(cmd, **kw):
            seen["cmd"] = list(cmd)
            return real(cmd, **kw)
        with patch.object(export, "run_ffmpeg", side_effect=spy):
            out = export.render(timeline, Path(TEMP) / "lean.mp4", quality="draft")
        cmd = seen["cmd"]
        self.assertIn("-filter_complex_threads", cmd)
        self.assertEqual(cmd.count("-threads"), 7 + 1)                              # one per input + the encoder's own
        self.assertAlmostEqual(float(probe(out)["format"]["duration"]), 3.5, delta=0.4)

    def test_ffmpeg_killed_by_the_kernel_becomes_a_clear_exception(self):
        fake = Path(TEMP) / "fake-ffmpeg.sh"
        fake.write_text("#!/bin/sh" + chr(10) + "kill -9 $$" + chr(10))
        fake.chmod(0o755)
        with self.assertRaises(export.RenderMemoryError) as ctx:
            export.run_ffmpeg([str(fake)])
        self.assertIn("حافظه", str(ctx.exception))
        self.assertIn("۷۲۰", str(ctx.exception))

    def test_an_oom_kill_triggers_one_smaller_retry_and_says_so(self):
        timeline = self.timeline(n=4, w=1080, h=1920)
        sizes, calls = [], {"n": 0}
        real = export.run_ffmpeg

        def flaky(cmd, **kw):
            calls["n"] += 1
            sizes.append(next((a for a in cmd if isinstance(a, str) and a.endswith(".ffgraph")), ""))
            if calls["n"] == 1:
                raise export.RenderMemoryError(export.OOM_MESSAGE)
            return real(cmd, **kw)
        notes: list[str] = []
        with patch.object(export, "run_ffmpeg", side_effect=flaky):
            out = export.render(timeline, Path(TEMP) / "retry.mp4", quality="draft", notes=notes)
        self.assertEqual(calls["n"], 2)
        self.assertTrue(out.exists() and out.stat().st_size > 1000)
        self.assertEqual(len(notes), 1)
        self.assertIn("۷۲۰", notes[0])
        v = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
        self.assertEqual(min(v["width"], v["height"]), 720)                          # the retry really is smaller than 1080×1920

    def test_when_even_the_retries_die_the_person_gets_the_persian_message(self):
        timeline = self.timeline(n=3, w=1080, h=1920)

        def always(cmd, **kw):
            raise export.RenderMemoryError(export.OOM_MESSAGE)
        with patch.object(export, "run_ffmpeg", side_effect=always):
            with self.assertRaises(VideoProcessingError) as ctx:
                export.render(timeline, Path(TEMP) / "dead.mp4", quality="final", export={"preset": "reels"})
        self.assertIn("حافظه", str(ctx.exception))
        self.assertFalse((Path(TEMP) / "dead.mp4").exists())


def gray_frame(path, t):
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=160:90", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, stdin=subprocess.DEVNULL, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).astype(float)


def audio_rms_db(path):
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, stdin=subprocess.DEVNULL, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    return 20 * np.log10(max(1e-9, float(np.sqrt(np.mean(np.square(x)))))), len(x) / 16000


def many_clip_timeline(src, n=10, step=0.7, transitions=(), has_audio=True, w=320, h=180):
    clips = []
    for i in range(n):
        clips.append({"id": f"c{i}", "type": "media", "ref": "x", "label": "x", "kind": "video", "at": round(i * step, 3), "start": (i % 3) * 0.5, "end": (i % 3) * 0.5 + step, "src": 3,
                      "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "cover", "fade_in": 0, "fade_out": 0, "audio_on": has_audio,
                      "has_audio": has_audio, "effects": [], "transition": ({"kind": "fade", "duration": 0.3} if i in transitions else None)})
    data = {"format": {"width": w, "height": h, "fps": 12, "preset": "wide"}, "tracks": [{"id": "t1", "kind": "video", "name": "v", "clips": clips}], "global_ops": []}
    info = {"path": str(src), "kind": "video", "has_audio": has_audio, "duration": 3.0, "width": 320, "height": 180}
    return tl.from_project(data, lambda ref: dict(info))


@override_settings(MEDIA_ROOT=TEMP)
class SliceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAVE:
            cls.src = make_video(Path(TEMP) / "sl.mp4", size="320x180", seconds=3)

    def setUp(self):
        if not HAVE:
            self.skipTest("ffmpeg نیست")

    def test_a_light_edit_is_not_sliced_and_a_heavy_one_is_cut_on_clip_edges(self):
        tlm = many_clip_timeline(self.src, n=10)
        self.assertIsNone(export.plan_slices(tlm), "a small edit renders in one go")
        slices = export.plan_slices(tlm, budget=1)
        self.assertGreater(len(slices), 1)
        self.assertEqual(slices[0][0], 0.0)
        self.assertAlmostEqual(slices[-1][1], tlm.length, delta=0.1)
        for (a, b), (c, d) in zip(slices, slices[1:]):
            self.assertAlmostEqual(b, c, places=6)                                  # contiguous, no gap, no overlap
        for a, b in slices:
            self.assertGreaterEqual(b - a, export.MIN_SLICE - 1e-6)
        edges = {round(c.at, 3) for t in tlm.tracks for c in t.clips}
        for a, _ in slices[1:]:
            self.assertTrue(any(abs(a - e) < 1 / 12 + 1e-6 for e in edges), f"cut at {a} is not a clip edge")
        self.assertIsNone(export.plan_slices(many_clip_timeline(self.src, n=2), budget=1), "two clips never need slicing")

    def test_slices_never_cut_where_a_transition_joins_two_clips(self):
        tlm = many_clip_timeline(self.src, n=10, transitions=(3, 4, 5, 6))
        slices = export.plan_slices(tlm, budget=1)
        cuts = [a for a, _ in slices[1:]]
        for banned in (3 * 0.7, 4 * 0.7, 5 * 0.7, 6 * 0.7):
            self.assertFalse(any(abs(c - banned) < 0.05 for c in cuts), f"cut at the transition {banned}: {cuts}")

    def test_the_sliced_render_matches_the_one_go_render_picture_and_sound(self):
        tlm = many_clip_timeline(self.src, n=10)
        one = export.render(tlm, Path(TEMP) / "one.mp4", quality="draft", slice_budget=0)
        sliced = export.render(tlm, Path(TEMP) / "sliced.mp4", quality="draft", slice_budget=1)
        d1, d2 = float(probe(one)["format"]["duration"]), float(probe(sliced)["format"]["duration"])
        self.assertAlmostEqual(d1, d2, delta=0.2)
        v1 = next(s for s in probe(one)["streams"] if s["codec_type"] == "video")
        v2 = next(s for s in probe(sliced)["streams"] if s["codec_type"] == "video")
        self.assertEqual((v1["width"], v1["height"]), (v2["width"], v2["height"]))
        self.assertLessEqual(abs(int(v1["nb_frames"]) - int(v2["nb_frames"])), 2)
        for t in (0.3, 1.9, 3.6, 5.8):
            a, b = gray_frame(one, t), gray_frame(sliced, t)
            self.assertLess(float(np.mean(np.abs(a - b))), 9.0, f"frame at {t}s differs")
        (db1, len1), (db2, len2) = audio_rms_db(one), audio_rms_db(sliced)
        self.assertLess(abs(db1 - db2), 2.0, f"loudness {db1:.1f} vs {db2:.1f}")
        self.assertAlmostEqual(len1, len2, delta=0.25)
        self.assertEqual(sorted(p.name for p in Path(TEMP).glob(".slices_*")), [], "the slice folder is removed")

    def test_a_sliced_render_without_any_sound_still_works(self):
        tlm = many_clip_timeline(self.src, n=9, has_audio=False)
        out = export.render(tlm, Path(TEMP) / "mute.mp4", quality="draft", slice_budget=1)
        kinds = {s["codec_type"] for s in probe(out)["streams"]}
        self.assertEqual(kinds, {"video"})
        self.assertAlmostEqual(float(probe(out)["format"]["duration"]), tlm.length, delta=0.3)

    def test_progress_goes_up_and_never_past_one(self):
        tlm = many_clip_timeline(self.src, n=9)
        seen = []
        export.render(tlm, Path(TEMP) / "prog.mp4", quality="draft", slice_budget=1, progress=seen.append)
        self.assertTrue(seen)
        self.assertLessEqual(max(seen), 1.0)
        self.assertGreater(max(seen), 0.5)
        self.assertEqual(seen, sorted(seen) if len(set(seen)) == len(seen) else seen)

    def test_cancelling_between_slices_stops_and_cleans_up(self):
        tlm = many_clip_timeline(self.src, n=9)
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] > 2
        with self.assertRaises(export.RenderCancelled):
            export.render(tlm, Path(TEMP) / "cancel.mp4", quality="draft", slice_budget=1, cancel=cancel)
        self.assertEqual(sorted(p.name for p in Path(TEMP).glob(".slices_*")), [])
